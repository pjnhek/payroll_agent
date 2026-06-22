"""The clarification drafting call (CLAR-01, AI-SPEC §1 Drafting call).

When final_action == request_clarification, the cheap DRAFT_* tier drafts a
human-readable clarification email asking the client to resolve what the code gate
blocked. This is the ONE LLM call that is NOT JSON mode — it is prose, so it goes
through `client.call_text` (free text, no schema, no reflective retry) and may run
a low non-zero temperature.

A draft failure must NEVER strand the run: `call_text` returns None on empty
content, and this module falls back to a deterministic templated body built from
the Decision's gate detail (gate_reasons / unresolved_names / missing_fields). So
the run always has a body to send and always pauses cleanly at AWAITING_REPLY.

PURE: typed Decision in, str out. No DB, no connection — the orchestrator owns the
send + status transition.
"""
from __future__ import annotations

import logging

from app.llm import client as llm_client
from app.llm.prompts import clarify as clarify_prompt
from app.models.contracts import Decision

logger = logging.getLogger("payroll_agent.compose_email")

_SUBJECT = "Quick question before we run your payroll"


def _template_body(
    decision: Decision,
    suggestions: dict[str, str] | None = None,
) -> str:
    """A deterministic clarification body from the gate detail (fallback / floor).

    Surfaces exactly what the code gate blocked on so the client can resolve it,
    even when the draft model returns nothing.

    `suggestions` (submitted_name → suggested roster full_name) is advisory COPY
    from the suggestion call (D-21-05). When a suggestion exists for an unresolved
    name, the line names the likely intended employee ("We could not match
    'David Reyez' — did you mean David Reyes?") instead of the bare name. This is
    the DETERMINISTIC floor of the new Phase 2 hero, so the specific ask survives
    even a total draft-tier failure (WR-03).
    """
    suggestions = suggestions or {}
    lines = [
        "Hello,",
        "",
        "We started processing your payroll but need to confirm a few details "
        "before we can finish:",
        "",
    ]
    if decision.unresolved_names:
        # Split names with a suggestion (specific "did you mean ...?" line) from
        # those without (the generic bundled ask) — the suggestion is copy only.
        suggested_names = [n for n in decision.unresolved_names if suggestions.get(n)]
        plain_names = [n for n in decision.unresolved_names if not suggestions.get(n)]
        for name in suggested_names:
            lines.append(
                f"  - We could not match '{name}' — did you mean "
                f"{suggestions[name]}?"
            )
        if plain_names:
            lines.append(
                "  - We could not confidently match these names to an employee: "
                + ", ".join(plain_names)
                + "."
            )
    if decision.missing_fields:
        lines.append(
            "  - We are missing required information for: "
            + ", ".join(decision.missing_fields)
            + "."
        )
    if not decision.unresolved_names and not decision.missing_fields:
        # Fall back to the raw gate reasons if the structured lists are empty.
        for reason in decision.gate_reasons:
            lines.append(f"  - {reason}")
    lines += [
        "",
        "Could you please reply with the correct details so we can complete the "
        "run? Thank you!",
    ]
    return "\n".join(lines)


def compose_clarification(
    decision: Decision,
    *,
    suggestions: dict[str, str] | None = None,
    llm=llm_client,
) -> str:
    """Draft a clarification email body for a gated run (CLAR-01).

    Uses the DRAFT_* tier free-text path; on empty model content falls back to a
    templated body so a draft failure never strands the run. Returns the body
    string the orchestrator hands to gateway.send_outbound.

    `suggestions` (submitted_name → suggested roster full_name) is advisory COPY
    from the suggestion call (D-21-05), threaded into BOTH the draft prompt (so the
    model can write "did you mean David Reyes?") AND the deterministic template
    fallback (so the specific ask survives a draft failure, WR-03). It is copy
    only — it never feeds decide / final_action.
    """
    messages = clarify_prompt.build_messages(decision, suggestions)
    # WR-03: the "draft failure never strands the run" guarantee must cover BOTH
    # empty content AND an API error (auth/rate-limit/etc.). call_text returns None
    # on empty content but RAISES on an API error — unwrapped, that exception would
    # propagate out through _clarify and route the run to ERROR instead of falling
    # back to the template. Wrap it so an API error also degrades to the templated
    # body, and LOG every fallback so a misconfigured draft tier (wrong key/model)
    # is VISIBLE rather than silently templating every clarification.
    api_error = False
    try:
        body = llm.call_text("draft", messages, temperature=0.3)
    except Exception as exc:  # noqa: BLE001 — a draft failure must never strand the run (CLAR-01)
        # Log the failure TYPE only — no exc_info (a traceback can echo the prompt /
        # submitted names — payroll PII — review fix).
        logger.warning(
            "draft call failed (%s) — falling back to templated clarification body",
            type(exc).__name__,
        )
        body = None
        api_error = True
    if not body or not body.strip():
        # An API error was already logged above; log the empty-content case here so a
        # silently-templating draft tier is still visible (but don't double-log errors).
        if not api_error:
            logger.warning("draft returned empty content — using templated clarification body")
        return _template_body(decision, suggestions)
    return body


def clarification_subject() -> str:
    """The clarification email subject (kept here so the orchestrator stays thin).

    WR-05: takes NO arguments. It previously accepted a `decision` it ignored
    entirely — a misleading signature implying the subject reflected the decision.
    The subject is a constant in Phase 2; a real provider's subject-based threading
    fallback is a deferred P6 concern. Drop the dead parameter (the honest minimum).
    """
    return _SUBJECT
