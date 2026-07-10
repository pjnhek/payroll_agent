"""The clarification-SUGGESTION stage (LLM-05, D-21-05) — the new Phase 2 hero.

For a name the deterministic resolver could NOT resolve, ONE cheap-tier (`draft`)
structured call suggests the most likely intended roster employee. The result is
used ONLY to make the clarification email specific ("did you mean David Reyes?").

CRITICAL — copy only, never feeds decide (D-21-05, T-021-06):
  suggest_employees runs ONLY on the request_clarification branch, STRICTLY AFTER
  `decide` has already returned. Its output is passed to compose_clarification as
  `suggestions=`, NEVER to `decide` and NEVER influencing `final_action`. There is
  no code path from this function into the money-moving decision; `decide.py` never
  imports this module (a test pins that). The LLM here is doing real judgment
  (nickname/typo knowledge that beats plain string distance) but it is walled off
  from the decision — exactly the Phase 2.1 thesis.

PURE (D-21-09): Roster + names in, mapping out. No DB, no connection — so the
Phase 4 eval could reuse it. It imports the LLM client but is only called on the
clarify branch.

NEVER strands the run (mirrors compose_email's WR-03): any failure — API error,
empty content, parse/validation error, or the model returning null/unknown for a
name — degrades to NO entry for that name (an empty mapping in the worst case) and
NEVER raises out of this stage. The caller falls back to the generic ask.
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

    suggested_full_name is None when the model has no plausible match (it must not
    guess wildly). This is COPY only — no score, no decision (D-21-05).
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
    except Exception as exc:  # noqa: BLE001 — a suggestion failure must never strand the run (D-21-05)
        # Log the failure TYPE only — never the email body, submitted names, or
        # suggested names (payroll PII must not land in logs — review fix). No
        # exc_info: a traceback can echo the prompt/name arguments.
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
            # The suggestion must name an ACTUAL employee — a clarification can never
            # claim a non-existent employee. Drop a hallucinated name. Count only —
            # do NOT log the submitted/suggested names (PII — review fix).
            dropped += 1
            continue
        mapping[s.submitted_name] = name
    if dropped:
        logger.warning(
            "dropped %d hallucinated suggestion(s) not matching any roster full_name",
            dropped,
        )
    return mapping
