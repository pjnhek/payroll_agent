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

from app.llm import client as llm_client
from app.llm.prompts import clarify as clarify_prompt
from app.models.contracts import Decision

_SUBJECT = "Quick question before we run your payroll"


def _template_body(decision: Decision) -> str:
    """A deterministic clarification body from the gate detail (fallback / floor).

    Surfaces exactly what the code gate blocked on so the client can resolve it,
    even when the draft model returns nothing.
    """
    lines = [
        "Hello,",
        "",
        "We started processing your payroll but need to confirm a few details "
        "before we can finish:",
        "",
    ]
    if decision.unresolved_names:
        lines.append(
            "  - We could not confidently match these names to an employee: "
            + ", ".join(decision.unresolved_names)
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


def compose_clarification(decision: Decision, *, llm=llm_client) -> str:
    """Draft a clarification email body for a gated run (CLAR-01).

    Uses the DRAFT_* tier free-text path; on empty model content falls back to a
    templated body so a draft failure never strands the run. Returns the body
    string the orchestrator hands to gateway.send_outbound.
    """
    messages = clarify_prompt.build_messages(decision)
    body = llm.call_text("draft", messages, temperature=0.3)
    if not body or not body.strip():
        return _template_body(decision)
    return body


def clarification_subject(decision: Decision) -> str:
    """The clarification email subject (kept here so the orchestrator stays thin)."""
    return _SUBJECT
