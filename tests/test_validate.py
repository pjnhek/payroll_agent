"""Field-validation stage tests (LLM-06; review FIX 1). Pure, DB-free, no model.

validate() emits issue_type="missing" for an absent required hours field and does
NOT (structurally cannot) emit `non_numeric` over a typed Extracted — non-numeric
values fail at the extraction parse boundary, not here (FIX 1).
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.models.contracts import Extracted, ExtractedEmployee
from app.models.roster import NameMatchResult
from app.pipeline.validate import validate


def _extracted(employees) -> Extracted:
    return Extracted(
        run_id=uuid.uuid4(),
        employees=employees,
        pay_period_start=date(2026, 6, 15),
    )


def _match(name, emp_id, mtype="exact", conf="1.0") -> NameMatchResult:
    return NameMatchResult(
        submitted_name=name,
        matched_employee_id=emp_id,
        match_type=mtype,
        confidence=Decimal(conf),
        reason="t",
    )


def test_missing_hours_for_hourly_employee(roster_from_seed):
    """An HOURLY employee (Maria Chen) with no hours at all → a missing issue."""
    maria = next(e for e in roster_from_seed.employees if e.full_name == "Maria Chen")
    extracted = _extracted([ExtractedEmployee(submitted_name="Maria Chen")])  # all None
    matches = [_match("Maria Chen", maria.id)]

    issues = validate(extracted, roster_from_seed, matches)

    assert any(i.issue_type == "missing" for i in issues), (
        "an hourly employee with no hours must produce a missing issue (LLM-06)"
    )


def test_salaried_employee_with_no_hours_is_not_missing(roster_from_seed):
    """A SALARIED employee (James Okafor) legitimately reports no hours — NOT a
    missing issue (the calc uses annual_salary). Keeps the clean path green."""
    james = next(e for e in roster_from_seed.employees if e.full_name == "James Okafor")
    extracted = _extracted([ExtractedEmployee(submitted_name="James Okafor")])
    matches = [_match("James Okafor", james.id)]

    issues = validate(extracted, roster_from_seed, matches)

    assert issues == [], "a salaried employee with no hours is not missing data"


def test_present_hours_produce_no_missing(roster_from_seed):
    maria = next(e for e in roster_from_seed.employees if e.full_name == "Maria Chen")
    extracted = _extracted(
        [ExtractedEmployee(submitted_name="Maria Chen", hours_regular=Decimal("40"))]
    )
    matches = [_match("Maria Chen", maria.id)]
    assert validate(extracted, roster_from_seed, matches) == []


def test_validate_never_emits_non_numeric(roster_from_seed):
    """FIX 1: over a TYPED Extracted, validate() can never produce a non_numeric
    issue — a non-numeric value already failed at the extraction parse boundary."""
    maria = next(e for e in roster_from_seed.employees if e.full_name == "Maria Chen")
    extracted = _extracted(
        [ExtractedEmployee(submitted_name="Maria Chen", hours_regular=Decimal("40"))]
    )
    matches = [_match("Maria Chen", maria.id)]
    issues = validate(extracted, roster_from_seed, matches)
    assert all(i.issue_type != "non_numeric" for i in issues), (
        "validate() must never classify non_numeric (it's an extraction-stage "
        "parse failure, FIX 1)"
    )
