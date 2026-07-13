"""Extraction prompt template (LLM-03).

The prompt MUST contain the literal word "json" plus an example object shape, or
DeepSeek silently does not enter JSON mode and returns prose. The example targets the
ExtractionPayload schema (employees + pay_period, NO run_id): the model returns only
the judgment payload, and extract() stamps the code-owned run_id afterwards.

Absent hours MUST be null (None), never 0. Null is how the client signals "didn't say",
which is what lets decide() gate on a missing field. Coercing an absent value to 0 would
turn "the client forgot to tell us" into "this employee worked zero hours" and pay them
nothing, with no clarification ever sent.

The resume/reply extraction context (see orchestrator._combined_context_email) may carry
a "QUESTIONS WE ASKED:" anchor plus one or more "CLARIFICATION REPLY" sections. The
system prompt below instructs the model not to blindly attribute a bare answer to an
asked field unless the reply attributably addresses it. That is a PROMPT INSTRUCTION
ONLY — a best-effort nudge, NOT the enforcement mechanism, and it must never be relied
on as one. The real money-safety guarantee is downstream and deterministic: a
still-absent asked field flows through decide() into a NEW, narrower clarification
round, never a silent guess onto an unaddressed employee. The tests assert that
deterministic backstop, never this instruction's effect on the LLM.
"""
from __future__ import annotations

from openai.types.chat import ChatCompletionMessageParam

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
    "employees who are not named in the email. Hours are decimal strings. "
    "If the email does not state a pay period / date, set pay_period_start to "
    "null — do NOT invent or guess a date. "
    "If the email contains a \"QUESTIONS WE ASKED:\" section followed by one or "
    "more \"CLARIFICATION REPLY\" sections: an asked field may be filled in from "
    "a reply ONLY if that reply attributably answers it — either the reply "
    "names the employee the question was about, or exactly ONE question was "
    "asked so a bare answer is unambiguous. If a reply's answer cannot be "
    "clearly attributed to the employee/field it was asked about, leave that "
    "field null rather than guessing — do not attribute an unaddressed reply "
    "to an employee it did not name."
)


def build_messages(
    email: InboundEmail, roster: Roster
) -> list[ChatCompletionMessageParam]:
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
