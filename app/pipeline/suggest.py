"""The clarification-SUGGESTION stage: the model guesses a name, for COPY only.

For a name the deterministic resolver could NOT resolve, one cheap-tier (`draft`)
structured call suggests the most likely intended roster employee. The result is used
ONLY to make the clarification email specific: "did you mean David Reyes?" instead of a
generic "we couldn't match a name".

CRITICAL — this suggestion is copy, and NEVER feeds the decision:
  suggest_employees runs ONLY on the request_clarification branch and STRICTLY AFTER
  decide() has already returned. Its output goes to compose_clarification as
  `suggestions=`. It is never passed to decide() and can never influence final_action.
  decide.py does not import this module, and a test pins that. The model here IS doing
  real judgment — nickname and typo knowledge that beats plain string distance — which is
  exactly why it must stay walled off from the money-moving decision: a wrong suggestion
  costs a slightly-off question in an email, while a wrong decision pays the wrong person.

PURE: Roster + names in, mapping out. No DB, no connection. It imports the LLM client but
is only ever called on the clarify branch.

NEVER strands the run: any failure — API error, empty content, parse/validation error, or
the model returning null/unknown for a name — degrades to NO entry for that name (an empty
mapping in the worst case) and NEVER raises out of this stage. The caller falls back to
the generic ask. A cosmetic nicety must not be able to kill a payroll run.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.llm import client as llm_client
from app.llm.prompts import suggest as suggest_prompt
from app.models.roster import Roster

logger = logging.getLogger("payroll_agent.suggest")


class NameSuggestion(BaseModel):
    """One suggestion: a submitted name → the roster full_name it likely meant.

    suggested_full_name is None when the model has no plausible match — it must be able to
    say "I don't know" rather than guess wildly. There is deliberately NO confidence score
    on this model: a score invites somebody to threshold on it, and any threshold turns
    this copy hint into a decision.
    """

    model_config = ConfigDict(extra="forbid")

    submitted_name: str
    suggested_full_name: str | None = None


class NameSuggestionResponse(BaseModel):
    """The structured wrapper validated by call_structured (a BaseModel, not a bare
    list, per the model_validate_json contract). Confidence-free by construction."""

    model_config = ConfigDict(extra="forbid")

    suggestions: list[NameSuggestion]


def suggest_employees(
    unresolved_names: list[str],
    roster: Roster,
    *,
    llm: Any = llm_client,
) -> dict[str, str]:
    """Suggest the likely intended roster employee for each unresolved name.

    Returns a mapping of submitted_name → suggested roster full_name, containing
    ONLY entries the model is reasonably sure about (a null/unknown suggestion, or
    a suggestion that is not an actual roster full_name, is omitted). Returns {}
    when there is nothing unresolved or on ANY failure — it never raises.
    """
    # Nothing unresolved → nothing to suggest, and NO LLM call.
    if not unresolved_names:
        return {}

    valid_full_names = {e.full_name for e in roster.employees}

    try:
        messages = suggest_prompt.build_messages(unresolved_names, roster)
        response = llm.call_structured("draft", messages, NameSuggestionResponse)
    except Exception as exc:  # noqa: BLE001 — a suggestion failure must never strand the run
        # Log the failure TYPE only — never the email body, the submitted names, or the
        # suggested names. Those are payroll PII and must not land in logs. Deliberately
        # no exc_info either: a traceback can echo the prompt and name arguments.
        logger.warning(
            "suggestion call failed (%s) — clarification falls back to the generic ask",
            type(exc).__name__,
        )
        return {}

    mapping: dict[str, str] = {}
    dropped = 0
    for s in response.suggestions:
        name = s.suggested_full_name
        if not name:
            continue  # null/unknown — fall back to the generic ask for this name
        if name not in valid_full_names:
            # The suggestion must name an ACTUAL roster employee. Asking the client "did
            # you mean <person who does not exist>?" would be worse than asking nothing.
            # Drop the hallucinated name; count it only — never log the submitted or
            # suggested names (PII).
            dropped += 1
            continue
        mapping[s.submitted_name] = name
    if dropped:
        logger.warning(
            "dropped %d hallucinated suggestion(s) not matching any roster full_name",
            dropped,
        )
    return mapping
