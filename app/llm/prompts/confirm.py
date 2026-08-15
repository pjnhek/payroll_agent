"""Confirmation-email drafting prompt (HITL-02, the DRAFT_* tier, free text).

Companion to clarify.py: this is the OTHER free-text drafting call, fired once the
operator has already approved the run and the confirmation goes out to the client.
Same convention — no "json" / example shape (free-text, not JSON mode) — and the
same format discipline clarify.py already had (BUG-13): plain text, no subject
line, no signature placeholder. The confirmation prompt lacked this guard until
BUG-13 (a real send carried a literal `Subject: ...` line in the body and signed
off `[Your Name]`); it now matches clarify.py's constraints, and
`compose_email._strip_format_violations` makes the violation impossible even if
the model ignores the prompt.

The model here only phrases the summary sentence around the per-employee net pay
figures the code already computed. It does not choose what to report — the figures
come from the approved PaystubLineItems, not the model.
"""
from __future__ import annotations

from typing import Any

from openai.types.chat import ChatCompletionMessageParam

from app.models.contracts import PaystubLineItem

_SYSTEM = (
    "You are a payroll assistant writing a brief, warm confirmation email telling "
    "a client their payroll run has been approved. Include the per-employee net "
    "pay summary. Keep it professional and concise. Write plain text only: no "
    "subject line, and no sign-off or signature placeholder — the system appends "
    "its own closing line, so end the email right after the net pay summary. Do "
    "NOT invent details beyond what is given below."
)


def build_messages(
    paystubs: list[PaystubLineItem], run: dict[str, Any]
) -> list[ChatCompletionMessageParam]:
    """Build the confirmation-drafting chat messages from the approved run.

    `run` is a dict from repo.load_run; `.get()` with a fallback so a missing key
    can never raise here and strand an approval the operator already gave.
    """
    user = (
        "Approved payroll run for "
        + run.get("business_name", "the client")
        + ".\n\nPer-employee net pay:\n"
        + "\n".join(
            f"- {item.submitted_name}: ${item.net_pay:,.2f} net" for item in paystubs
        )
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
