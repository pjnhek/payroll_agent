"""Clarification-email drafting prompt (CLAR-01, the DRAFT_* tier, free text).

This is the ONE prompt that is NOT JSON mode — it asks the cheap drafting model
for a short, friendly clarification email in plain prose. The gate detail
(unresolved names / missing fields / gate reasons) is summarized into the ask so
the client knows exactly what to fix. There is intentionally no "json" / example
shape here (that would be wrong for a free-text drafting call).
"""
from __future__ import annotations

from app.models.contracts import Decision

_SYSTEM = (
    "You are a friendly payroll assistant writing a short, polite email to a "
    "client. The client emailed in their employees' hours, but we cannot finish "
    "the payroll run until they confirm a few details. Write a brief, warm email "
    "(plain text, no subject line, no signature placeholder) that clearly asks "
    "them to confirm exactly the items listed. Do NOT invent details, do NOT quote "
    "the client's original email back verbatim, and do NOT include any dollar "
    "amounts or payroll figures."
)


def build_messages(decision: Decision) -> list[dict]:
    """Build the clarification-drafting chat messages from the gated Decision."""
    asks: list[str] = []
    if decision.unresolved_names:
        asks.append(
            "Names we could not confidently match: "
            + ", ".join(decision.unresolved_names)
        )
    if decision.missing_fields:
        asks.append(
            "Required information that is missing: "
            + ", ".join(decision.missing_fields)
        )
    if not asks:
        asks.extend(decision.gate_reasons)
    ask_text = "\n".join(f"- {a}" for a in asks) or "- (general clarification needed)"
    user = (
        "We need the client to confirm these items before we can run payroll:\n"
        f"{ask_text}\n\n"
        "Write the clarification email body now."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
