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


def _match(name, emp_id, source="exact") -> NameMatchResult:
    return NameMatchResult(
        submitted_name=name,
        matched_employee_id=emp_id,
        source=source,
        resolved=True,
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


# ---------------------------------------------------------------------------
# D-05: Over-40-no-OT guard — Wave 0 RED stubs
#
# These tests WILL FAIL RED until Wave 1 Plan 03 adds the _employee_pay_periods_per_year
# helper and the OT rule loop to validate.py. That is the expected Wave 0 outcome.
#
# Rule summary (D-05):
#   - weekly (pay_periods_per_year=52): regular > 40 AND no OT → flag
#   - biweekly (pay_periods_per_year=26): regular > 80 AND no OT → flag (partial)
#   - semi-monthly / monthly (ppy 24/12): no flag (period crosses workweeks — limitation)
#   - explicit hours_overtime=0 is treated same as None (recommended decision)
# ---------------------------------------------------------------------------


def _make_weekly_hourly_employee(name: str = "Test Worker") -> "Employee":
    """Build a minimal weekly (pay_periods_per_year=52) hourly Employee inline."""
    from app.models.roster import Employee

    return Employee(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        full_name=name,
        known_aliases=[],
        pay_type="hourly",
        hourly_rate=Decimal("18.50"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("0"),
        pay_periods_per_year=52,  # weekly
    )


def _make_biweekly_hourly_employee(name: str = "Biweekly Worker") -> "Employee":
    """Build a minimal biweekly (pay_periods_per_year=26) hourly Employee inline."""
    from app.models.roster import Employee

    return Employee(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        full_name=name,
        known_aliases=[],
        pay_type="hourly",
        hourly_rate=Decimal("22.00"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("0"),
        pay_periods_per_year=26,  # biweekly
    )


def _make_semimonthly_salary_employee(name: str = "Semimonthly Worker") -> "Employee":
    """Build a minimal semi-monthly (pay_periods_per_year=24) salaried Employee inline.

    Semi-monthly used for the documented-limitation test (no OT flag, ppy=24).
    Salary employee used because the OT rule does not apply to salaried staff anyway
    — this makes the no-flag case doubly-clean for the documented-limitation test.
    """
    from app.models.roster import Employee

    return Employee(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        full_name=name,
        known_aliases=[],
        pay_type="salary",
        hourly_rate=None,
        annual_salary=Decimal("60000.00"),
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("0"),
        pay_periods_per_year=24,  # semi-monthly
    )


def _one_employee_roster(emp: "Employee") -> "Roster":
    """Build a single-employee Roster for inline test use."""
    from app.models.roster import Roster

    return Roster(business_id=emp.business_id, employees=[emp])


def test_ot_rule_weekly_flagged():
    """D-05: weekly (pay_periods_per_year=52) hourly employee with hours_regular=45
    and hours_overtime=None → validate() emits at least one ValidationIssue whose
    message contains 'overtime'.

    45 regular hours > 40 with no OT field is a data integrity question — the system
    cannot distinguish '40 regular + 5 OT' from '45 straight time'.

    Will fail RED until Wave 1 adds the OT rule to validate.py.
    """
    emp = _make_weekly_hourly_employee("Maria Weekly")
    roster = _one_employee_roster(emp)
    extracted = _extracted(
        [ExtractedEmployee(submitted_name=emp.full_name, hours_regular=Decimal("45"))]
    )
    matches = [_match(emp.full_name, emp.id)]

    issues = validate(extracted, roster, matches)

    assert any("overtime" in i.message.lower() for i in issues), (
        "D-05: a weekly hourly employee with hours_regular=45 and no overtime field "
        "must emit a ValidationIssue mentioning 'overtime' (Wave 1 impl target)"
    )


def test_ot_rule_biweekly_flagged():
    """D-05: biweekly (pay_periods_per_year=26) hourly employee with hours_regular=85
    and hours_overtime=None → validate() emits a ValidationIssue.

    85 regular hours over 2 weeks guarantees OT in at least one week (>80 threshold
    — partial detection for biweekly periods per D-05).

    Will fail RED until Wave 1 adds the OT rule to validate.py.
    """
    emp = _make_biweekly_hourly_employee("Sandra Biweekly")
    roster = _one_employee_roster(emp)
    extracted = _extracted(
        [ExtractedEmployee(submitted_name=emp.full_name, hours_regular=Decimal("85"))]
    )
    matches = [_match(emp.full_name, emp.id)]

    issues = validate(extracted, roster, matches)

    assert any("overtime" in i.message.lower() for i in issues), (
        "D-05: a biweekly hourly employee with hours_regular=85 (>80) and no overtime "
        "field must emit a ValidationIssue mentioning 'overtime' (Wave 1 impl target)"
    )


def test_ot_rule_biweekly_not_flagged_below_threshold():
    """D-05: biweekly employee with hours_regular=78 (below 80 threshold) and no OT
    → validate() emits NO OT-related issue.

    78 hours over 2 weeks is below the 80-hour biweekly threshold, so no flag.

    Will fail RED until Wave 1 adds the OT rule to validate.py (the threshold check).
    """
    emp = _make_biweekly_hourly_employee("Sandra Below Threshold")
    roster = _one_employee_roster(emp)
    extracted = _extracted(
        [ExtractedEmployee(submitted_name=emp.full_name, hours_regular=Decimal("78"))]
    )
    matches = [_match(emp.full_name, emp.id)]

    issues = validate(extracted, roster, matches)

    assert not any("overtime" in i.message.lower() for i in issues), (
        "D-05: a biweekly employee with hours_regular=78 (below 80 threshold) must "
        "NOT emit an OT ValidationIssue (Wave 1 impl target — threshold is 80 for "
        "biweekly, not 40)"
    )


def test_ot_rule_no_flag_semimonthly():
    """D-05 documented limitation: a semi-monthly (pay_periods_per_year=24) employee
    with hours_regular=100 and no OT → validate() emits NO OT-related flag.

    Semi-monthly pay periods cross workweek boundaries in non-trivial ways; detecting
    OT reliably requires knowing the exact period start/end relative to workweeks.
    D-05 explicitly documents this as a limitation: ppy in (24, 12) → no OT flag.

    Will fail RED until Wave 1 adds the OT rule loop (which skips ppy=24).
    """
    emp = _make_semimonthly_salary_employee("Chris Semimonthly")
    roster = _one_employee_roster(emp)
    extracted = _extracted(
        [ExtractedEmployee(submitted_name=emp.full_name, hours_regular=Decimal("100"))]
    )
    matches = [_match(emp.full_name, emp.id)]

    issues = validate(extracted, roster, matches)

    assert not any("overtime" in i.message.lower() for i in issues), (
        "D-05 documented limitation: a semi-monthly employee (ppy=24) with high "
        "hours_regular must NOT emit an OT flag — period crosses workweek boundaries "
        "(Wave 1 impl target — ppy 24/12 is explicitly excluded from OT detection)"
    )


def test_ot_rule_explicit_zero_flagged():
    """D-05 edge: a weekly hourly employee with hours_regular=45 AND hours_overtime=0
    (explicit zero, not None) → validate() DOES emit a ValidationIssue.

    Per D-05 recommended decision: treat explicit 0 same as absent (ot_missing = True
    when hours_overtime is None OR hours_overtime == 0). A client who submits '0 OT'
    for 45 regular hours is in the same ambiguous situation as a client who omits OT.

    Will fail RED until Wave 1 adds the OT rule (with the explicit-zero case).
    """
    emp = _make_weekly_hourly_employee("Maria ExplicitZero")
    roster = _one_employee_roster(emp)
    extracted = _extracted(
        [
            ExtractedEmployee(
                submitted_name=emp.full_name,
                hours_regular=Decimal("45"),
                hours_overtime=Decimal("0"),  # explicit zero — same as absent per D-05
            )
        ]
    )
    matches = [_match(emp.full_name, emp.id)]

    issues = validate(extracted, roster, matches)

    assert any("overtime" in i.message.lower() for i in issues), (
        "D-05 edge: weekly employee with hours_regular=45 AND hours_overtime=0 must "
        "STILL emit a ValidationIssue — explicit zero treated same as absent per D-05 "
        "recommended decision (Wave 1 impl target)"
    )


# ---------------------------------------------------------------------------
# MONEY-01 RED tests (Wave 1 — D-01/D-02/D-03/D-09/D-25)
#
# These tests FAIL RED until Plan 07-02 replaces the `is not None` predicate
# in any_hours with the shared `_is_paid` predicate (D-09).
# test_partial_week_not_gated and test_salaried_not_gated_regression_guard
# are expected to PASS already (D-03 regression guards).
# ---------------------------------------------------------------------------


def test_zero_hours_hourly_gates(roster_from_seed):
    """MONEY-01 RED (D-01/D-02): hourly employee with hours_regular=Decimal('0')
    and all other four hours fields absent (None) must produce a missing issue.

    RED because current any_hours predicate is `is not None` — Decimal('0') is not
    None so any_hours=True, the employee is skipped, no issue is emitted, and a $0
    paystub ships silently. Plan 07-02 fixes this with the _is_paid predicate (D-09).
    """
    maria = next(e for e in roster_from_seed.employees if e.full_name == "Maria Chen")
    # hours_regular=0, all other hours fields absent (None)
    extracted = _extracted(
        [ExtractedEmployee(submitted_name="Maria Chen", hours_regular=Decimal("0"))]
    )
    matches = [_match("Maria Chen", maria.id)]

    issues = validate(extracted, roster_from_seed, matches)

    assert issues, (
        "MONEY-01: hourly employee with hours_regular=Decimal('0') and all other hours "
        "absent must produce a missing issue (D-01/D-02 — current is-not-None bug)"
    )
    assert any(i.issue_type == "missing" for i in issues), (
        "MONEY-01: the emitted issue must be issue_type='missing'"
    )


def test_partial_week_not_gated(roster_from_seed):
    """MONEY-01 D-03 regression guard: hourly employee with hours_regular=Decimal('0')
    AND hours_holiday=Decimal('8') must NOT produce a missing issue.

    D-03: a genuine partial week (hours_holiday=8 > 0) still processes — the holiday
    hours are paid, so the zero-hours gate must NOT fire. This guard must stay GREEN
    before AND after the MONEY-01 fix.

    May already be GREEN (hours_holiday=8 is not None → any_hours=True → no issue).
    Written explicitly as a D-03 regression guard so it stays green after Plan 07-02.
    """
    maria = next(e for e in roster_from_seed.employees if e.full_name == "Maria Chen")
    extracted = _extracted(
        [
            ExtractedEmployee(
                submitted_name="Maria Chen",
                hours_regular=Decimal("0"),
                hours_holiday=Decimal("8"),
            )
        ]
    )
    matches = [_match("Maria Chen", maria.id)]

    issues = validate(extracted, roster_from_seed, matches)

    # No missing issue — hours_holiday=8 is a paid field so the employee has work
    missing_issues = [i for i in issues if i.issue_type == "missing" and "hours_regular" in i.field]
    assert not missing_issues, (
        "D-03: partial week (hours_regular=0 but hours_holiday=8) must NOT gate to "
        "clarification — the holiday hours are paid and the run should process"
    )


def test_predicate_consistency(roster_from_seed):
    """MONEY-01 RED (D-25): hours_overtime=Decimal('0') must be treated identically
    to hours_overtime=None when ALL other hours fields are also absent/zero.

    Both represent 'no paid overtime'. The shared _is_paid predicate (D-09) treats
    both as absent. Currently the `is not None` predicate treats Decimal('0') as
    present, so the employee with hours_overtime=0 (all others None) produces no
    missing issue while the None variant does.

    RED because current predicate lets hours_overtime=Decimal('0') pass as present.
    Plan 07-02 fixes this with the _is_paid shared predicate.
    """
    maria = next(e for e in roster_from_seed.employees if e.full_name == "Maria Chen")

    # Case 1: all hours None — current code already emits a missing issue
    extracted_none = _extracted(
        [ExtractedEmployee(submitted_name="Maria Chen")]  # all hours None
    )
    matches = [_match("Maria Chen", maria.id)]
    issues_none = validate(extracted_none, roster_from_seed, matches)

    # Case 2: hours_overtime=Decimal('0'), all others None — currently no issue (bug)
    extracted_zero = _extracted(
        [ExtractedEmployee(submitted_name="Maria Chen", hours_overtime=Decimal("0"))]
    )
    issues_zero = validate(extracted_zero, roster_from_seed, matches)

    # Both should produce a missing issue (D-25 predicate consistency)
    assert any(i.issue_type == "missing" for i in issues_none), (
        "D-25: all-None hours must produce a missing issue (baseline)"
    )
    assert any(i.issue_type == "missing" for i in issues_zero), (
        "D-25 RED: hours_overtime=Decimal('0') with all other hours absent must gate "
        "identically to all-None — current is-not-None bug lets it through silently"
    )


def test_salaried_not_gated_regression_guard(roster_from_seed):
    """MONEY-01 regression guard: a SALARIED employee with hours_regular=Decimal('0')
    and all other hours absent must NOT produce a missing issue.

    Salaried employees compute from annual_salary; the zero-hours gate must NEVER apply
    to them. This guard must stay GREEN before AND after the MONEY-01 fix (Plan 07-02).
    """
    james = next(e for e in roster_from_seed.employees if e.full_name == "James Okafor")
    extracted = _extracted(
        [ExtractedEmployee(submitted_name="James Okafor", hours_regular=Decimal("0"))]
    )
    matches = [_match("James Okafor", james.id)]

    issues = validate(extracted, roster_from_seed, matches)

    missing_issues = [i for i in issues if i.issue_type == "missing"]
    assert not missing_issues, (
        "MONEY-01 regression guard: salaried employees must never be gated on zero hours "
        "— they compute from annual_salary (D-03 salaried exception)"
    )
