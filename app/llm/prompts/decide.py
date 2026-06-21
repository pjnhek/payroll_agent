"""Decision-advisory prompt template (Stage 3 model portion, LLM-07).

The model returns ONLY an advisory model_action + reasons as JSON. The code-owned
final_action (the gate) is computed separately in app/pipeline/decide.py and is
the SOLE branch source — the model's opinion never bypasses the gate (the thesis).
The prompt carries the literal word "json" + an example shape (Pitfall 1).
"""
from __future__ import annotations

from app.models.contracts import Extracted
from app.models.roster import NameMatchResult, ValidationIssue

_SYSTEM = (
    "You are a payroll decision assistant. Given the extracted employees, the "
    "name-reconciliation results, and the field-validation issues, advise whether "
    "this run can be processed or whether the client must be asked a clarifying "
    "question. Return ONLY a json object of this exact shape:\n"
    "{\n"
    '  "model_action": "process",\n'
    '  "reasons": ["all names matched cleanly", "all required hours present"]\n'
    "}\n"
    'model_action MUST be exactly "process" or "request_clarification". '
    "Recommend request_clarification when a name is unresolved or low-confidence, "
    "or a required hours field is missing. Your advice is advisory only — a "
    "separate code gate makes the final, binding decision."
)


def build_messages(
    extracted: Extracted,
    matches: list[NameMatchResult],
    issues: list[ValidationIssue],
) -> list[dict]:
    """Build the decision-advisory chat messages."""
    names = (
        "; ".join(
            f"{m.submitted_name} → {m.match_type} (confidence {m.confidence})"
            for m in matches
        )
        or "(all names resolved deterministically)"
    )
    issue_text = (
        "; ".join(f"{i.field}: {i.issue_type}" for i in issues) or "(none)"
    )
    emp_text = ", ".join(e.submitted_name for e in extracted.employees) or "(none)"
    user = (
        f"Extracted employees: {emp_text}\n"
        f"Name reconciliation: {names}\n"
        f"Validation issues: {issue_text}\n\n"
        "Return the advisory json now."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
