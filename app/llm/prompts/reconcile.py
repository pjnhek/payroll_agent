"""Layer-2 name-reconciliation prompt template (Stage 2 model portion, LLM-05).

ONLY residual names (those that failed deterministic layer-1) reach this prompt.
The model classifies each against the FULL roster as `llm_typo` / `llm_nickname`
/ `unknown` with a per-name `confidence` (0–1) + `reason`, returned as the
`{"matches": [...]}` wrapper (NameReconciliationResponse).

Two locked prompt constraints (RESEARCH §7 / AI-SPEC §7):
- The literal word "json" + an example object shape MUST appear or DeepSeek
  silently does not enter JSON mode (Pitfall 1).
- The FULL roster is provided in-context so genuine ambiguity (two similar
  roster names) drives a low confidence BY CONSTRUCTION — this is the tuning
  surface for the live hero run (Plan 04, D-A4-01a). The submitted-name variant
  ("David Reyez") + this prompt must together land model-says-process AND
  sub-0.8 confidence on a live run.
"""
from __future__ import annotations

from app.models.roster import Roster

_SYSTEM = (
    "You are a payroll name-reconciliation assistant. You are given a small list "
    "of submitted employee names that did NOT match the roster exactly, plus the "
    "business's FULL employee roster. For EACH submitted name, decide which roster "
    "employee (if any) it most likely refers to, and how confident you are. "
    "Return ONLY a json object of this exact shape:\n"
    "{\n"
    '  "matches": [\n'
    "    {\n"
    '      "submitted_name": "David Reyez",\n'
    '      "matched_employee_id": "e0000003-0000-0000-0000-000000000003",\n'
    '      "match_type": "llm_typo",\n'
    '      "confidence": "0.6",\n'
    '      "reason": "likely a typo of David Reyes (y->z)"\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "Rules: emit EXACTLY one match per submitted name, in the same order. "
    'match_type MUST be one of "llm_typo", "llm_nickname", or "unknown". '
    "Use the roster employee's id (a UUID from the roster below) for "
    "matched_employee_id; use null and match_type \"unknown\" when no roster "
    "employee plausibly matches. confidence is a decimal string between 0 and 1 — "
    "be HONEST: if two roster names are similarly close, your confidence must be "
    "low. Do NOT invent employees who are not in the roster."
)


def build_messages(
    residual_names: list[str],
    roster: Roster,
) -> list[dict]:
    """Build the layer-2 reconciliation chat messages for the residual names.

    The FULL roster (id → full_name, with any known aliases) is provided so the
    model can see genuine ambiguity; only the residual names are asked about.
    """
    roster_lines = "\n".join(
        f"  - {emp.full_name} (id={emp.id})"
        + (f" [aliases: {', '.join(emp.known_aliases)}]" if emp.known_aliases else "")
        for emp in roster.employees
    ) or "  (empty roster)"
    names_text = "\n".join(f"  - {n}" for n in residual_names) or "  (none)"
    user = (
        f"Full roster for this business:\n{roster_lines}\n\n"
        f"Submitted names that need reconciliation:\n{names_text}\n\n"
        "Return the reconciliation json now."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
