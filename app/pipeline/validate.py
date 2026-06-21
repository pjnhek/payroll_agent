"""Stage 3 — deterministic field validation (LLM-06; review FIX 1).

A PURE function: typed values in, list[ValidationIssue] out, NO model, NO DB, NO
connection. It mirrors the issue-collection style of roster.py's
@model_validator (_require_compensation_field): inspect fields, accumulate
problems, return them rather than raising.

It emits issue_type="missing" for an absent REQUIRED hours field and cross-field
sanity issues. "Required" is pay-type aware: an HOURLY employee with no hours at
all is missing data the calc needs; a SALARIED employee computes from
annual_salary and legitimately reports no hours — so the roster is passed in (a
pure value, no DB) to decide what is required. The matched employee is found via
the reconciliation results (Layer 1 in this plan).

FIX 1 — what validate does NOT do: it does NOT (and structurally CANNOT) emit
`non_numeric` or `out_of_bounds` for the ge=0 case. A non-numeric/negative hours
value fails at the EXTRACTION parse boundary (ExtractedEmployee is Decimal|None +
ge=0 + extra="forbid"), routed through the client's one reflective retry → ERROR.
By the time a typed Extracted exists, every present hours value is already a
valid non-negative Decimal — so the typed path can never reach `non_numeric`.
"""
from __future__ import annotations

from app.models.contracts import Extracted
from app.models.roster import NameMatchResult, Roster, ValidationIssue

_HOURS_FIELDS = (
    "hours_regular",
    "hours_overtime",
    "hours_vacation",
    "hours_sick",
    "hours_holiday",
)


def _employee_pay_type(
    submitted_name: str,
    matches: list[NameMatchResult],
    roster: Roster,
) -> str | None:
    """Resolve the matched employee's pay_type via the reconciliation results."""
    for m in matches:
        if m.submitted_name == submitted_name and m.matched_employee_id is not None:
            for emp in roster.employees:
                if emp.id == m.matched_employee_id:
                    return emp.pay_type
    return None


def validate(
    extracted: Extracted,
    roster: Roster,
    matches: list[NameMatchResult],
) -> list[ValidationIssue]:
    """Emit field-validation issues for one run (LLM-06).

    Rules (deterministic, no model):
    - missing: an HOURLY employee with no hours of any kind (all five None). A
      salaried employee with no hours is fine (calc uses annual_salary). An
      unresolved name's pay_type is unknown, so no missing-hours issue is raised
      for it here — the gate already blocks it on the unknown match.
    """
    issues: list[ValidationIssue] = []
    for emp in extracted.employees:
        any_hours = any(
            getattr(emp, f) is not None for f in _HOURS_FIELDS
        )
        if any_hours:
            continue
        pay_type = _employee_pay_type(emp.submitted_name, matches, roster)
        if pay_type == "hourly":
            issues.append(
                ValidationIssue(
                    field=f"{emp.submitted_name}.hours_regular",
                    issue_type="missing",
                    message=(
                        f"hourly employee {emp.submitted_name!r} has no hours "
                        "reported — required for the calc"
                    ),
                )
            )
    return issues
