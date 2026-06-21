"""Extraction prompt template (Stage 1, LLM-03; review FIX A, Pitfall 1).

The prompt MUST contain the literal word "json" + an example object shape or
DeepSeek silently does not enter JSON mode (RESEARCH Pitfall 1). The example
targets the ExtractionPayload schema (employees + pay_period, NO run_id) — the
model returns only the judgment payload; extract() stamps the code-owned run_id
(FIX A). Absent hours MUST be null (None), never 0 — null is how the client
signals "didn't say" so decide() can gate on a missing field (Pitfall 2).
"""
from __future__ import annotations

from app.models.contracts import InboundEmail
from app.models.roster import Roster

_SYSTEM = (
    "You are a payroll data extraction assistant. Read the client's email and "
    "extract each named employee's reported hours and the pay period as JSON. "
    "Return ONLY a json object matching this exact shape (no run_id, no extra "
    "keys):\n"
    "{\n"
    '  "employees": [\n'
    '    {"submitted_name": "Jane Doe", "hours_regular": "40", '
    '"hours_overtime": null, "hours_vacation": null, "hours_sick": null, '
    '"hours_holiday": null, "contribution_401k_override": null}\n'
    "  ],\n"
    '  "pay_period_start": "2026-06-15",\n'
    '  "pay_period_end": null\n'
    "}\n"
    "Rules: use the employee's name EXACTLY as the client wrote it in "
    "submitted_name. If the client did not mention a particular hours field for "
    "an employee, set it to null — NEVER 0 and NEVER omit it. Do not invent "
    "employees who are not named in the email. Hours are decimal strings."
)


def build_messages(email: InboundEmail, roster: Roster) -> list[dict]:
    """Build the extraction chat messages for one inbound email.

    The roster's full names are provided ONLY as grounding context (a
    hallucination defense) — the model still records each name exactly as the
    client wrote it; reconciliation is a later, separate stage.
    """
    roster_names = ", ".join(e.full_name for e in roster.employees) or "(none)"
    user = (
        f"Roster employee names (context only): {roster_names}\n\n"
        f"Subject: {email.subject}\n"
        f"From: {email.from_addr}\n\n"
        f"Email body:\n{email.body_text}\n\n"
        "Extract the json now."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
