"""Field-validation stage tests (LLM-06). Pure, DB-free, no model.

validate() is one of the four pure judgment stages: it emits issue_type="missing" for
an absent required hours field, and structurally CANNOT emit `non_numeric` over a typed
Extracted — a non-numeric value already failed at the extraction parse boundary, so any
non_numeric issue here would mean the type contract had been bypassed.

Two rule families are covered:
  - the paid-hours gate: an hourly employee with no PAID hours must gate to
    clarification rather than ship a $0 paystub (MONEY-01);
  - the over-40-no-overtime guard: hours above the weekly/biweekly threshold with no
    overtime field is an ambiguity the system must ask about, not guess at.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from app.models.contracts import Extracted, ExtractedEmployee
from app.models.roster import NameMatchResult
from app.pipeline.validate import validate

if TYPE_CHECKING:
    from app.models.roster import Employee, Roster


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
    """Over a TYPED Extracted, validate() can never produce a non_numeric issue.

    Decimal fields cannot hold a non-numeric value — one would have failed at the
    extraction parse boundary. A non_numeric issue emitted here would mean validate is
    re-parsing strings it should never see.
    """
    maria = next(e for e in roster_from_seed.employees if e.full_name == "Maria Chen")
    extracted = _extracted(
        [ExtractedEmployee(submitted_name="Maria Chen", hours_regular=Decimal("40"))]
    )
    matches = [_match("Maria Chen", maria.id)]
    issues = validate(extracted, roster_from_seed, matches)
    assert all(i.issue_type != "non_numeric" for i in issues), (
        "validate() must never classify non_numeric — that is an extraction-stage "
        "parse failure, caught before this stage runs"
    )


# ---------------------------------------------------------------------------
# The over-threshold-no-overtime guard.
#
# The system cannot distinguish "40 regular + 5 overtime" from "45 straight time", and
# guessing costs real money (overtime is paid at 1.5x). So above-threshold hours with
# no overtime field must gate to clarification instead of being silently paid straight.
#
# Rule:
#   - weekly (pay_periods_per_year=52): regular > 40 AND no OT → flag
#   - biweekly (pay_periods_per_year=26): regular > 80 AND no OT → flag (partial)
#   - semi-monthly / monthly (ppy 24/12): no flag — these periods cross workweek
#     boundaries, so the hours total alone cannot prove any single week exceeded 40.
#     A documented limitation, not an oversight.
#   - explicit hours_overtime=0 is treated the same as absent: a client reporting
#     "0 OT" alongside 45 regular hours is in exactly the same ambiguous position as
#     one who omitted the field.
# ---------------------------------------------------------------------------


def _make_weekly_hourly_employee(name: str = "Test Worker") -> Employee:
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


def _make_biweekly_hourly_employee(name: str = "Biweekly Worker") -> Employee:
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


def _make_semimonthly_salary_employee(name: str = "Semimonthly Worker") -> Employee:
    """Build a minimal semi-monthly (pay_periods_per_year=24) salaried Employee inline.

    Semi-monthly (ppy=24) is the pay frequency the overtime rule deliberately skips.
    A salaried employee is used because the overtime rule does not apply to salaried
    staff either — which makes the expected no-flag outcome doubly unambiguous.
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


def _one_employee_roster(emp: Employee) -> Roster:
    """Build a single-employee Roster for inline test use."""
    from app.models.roster import Roster

    return Roster(business_id=emp.business_id, employees=[emp])


def test_ot_rule_weekly_flagged():
    """A weekly hourly employee with hours_regular=45 and no overtime field is flagged.

    45 regular hours with no overtime field is ambiguous: the system cannot tell
    '40 regular + 5 OT' from '45 straight time'. Paying it straight underpays the
    employee by the half-time premium on 5 hours, so it must be asked about.
    """
    emp = _make_weekly_hourly_employee("Maria Weekly")
    roster = _one_employee_roster(emp)
    extracted = _extracted(
        [ExtractedEmployee(submitted_name=emp.full_name, hours_regular=Decimal("45"))]
    )
    matches = [_match(emp.full_name, emp.id)]

    issues = validate(extracted, roster, matches)

    assert any("overtime" in i.message.lower() for i in issues), (
        "a weekly hourly employee with hours_regular=45 and no overtime field must emit "
        "a ValidationIssue mentioning 'overtime' — paying it straight underpays"
    )


def test_ot_rule_biweekly_flagged():
    """A biweekly hourly employee with hours_regular=85 and no overtime field is flagged.

    85 regular hours across 2 weeks means at least one week necessarily exceeded 40, so
    overtime is owed somewhere in the period even though the split is unknown. Detection
    is partial by construction: only the >80 total is provable from the total alone.
    """
    emp = _make_biweekly_hourly_employee("Sandra Biweekly")
    roster = _one_employee_roster(emp)
    extracted = _extracted(
        [ExtractedEmployee(submitted_name=emp.full_name, hours_regular=Decimal("85"))]
    )
    matches = [_match(emp.full_name, emp.id)]

    issues = validate(extracted, roster, matches)

    assert any("overtime" in i.message.lower() for i in issues), (
        "a biweekly hourly employee with hours_regular=85 (>80) and no overtime field "
        "must emit a ValidationIssue mentioning 'overtime'"
    )


def test_ot_rule_biweekly_not_flagged_below_threshold():
    """A biweekly employee with hours_regular=78 and no overtime emits NO overtime issue.

    78 hours across 2 weeks is below the 80-hour biweekly threshold, so no week is
    provably over 40 and there is nothing to ask about. Applying the weekly threshold of
    40 here would flag every ordinary biweekly run and bury the operator in noise.
    """
    emp = _make_biweekly_hourly_employee("Sandra Below Threshold")
    roster = _one_employee_roster(emp)
    extracted = _extracted(
        [ExtractedEmployee(submitted_name=emp.full_name, hours_regular=Decimal("78"))]
    )
    matches = [_match(emp.full_name, emp.id)]

    issues = validate(extracted, roster, matches)

    assert not any("overtime" in i.message.lower() for i in issues), (
        "a biweekly employee with hours_regular=78 (below the 80-hour threshold) must "
        "NOT emit an overtime ValidationIssue — the biweekly threshold is 80, not 40"
    )


def test_ot_rule_no_flag_semimonthly():
    """A semi-monthly employee with hours_regular=100 and no overtime is NOT flagged.

    This is a deliberate limitation. Semi-monthly and monthly periods cross workweek
    boundaries, so a high period total does not prove any single week exceeded 40 —
    reliable detection would need the period's start/end aligned to workweeks. Flagging
    on the total anyway would clarify on runs that are perfectly fine.
    """
    emp = _make_semimonthly_salary_employee("Chris Semimonthly")
    roster = _one_employee_roster(emp)
    extracted = _extracted(
        [ExtractedEmployee(submitted_name=emp.full_name, hours_regular=Decimal("100"))]
    )
    matches = [_match(emp.full_name, emp.id)]

    issues = validate(extracted, roster, matches)

    assert not any("overtime" in i.message.lower() for i in issues), (
        "a semi-monthly employee (ppy=24) with high hours_regular must NOT emit an "
        "overtime flag — the period crosses workweek boundaries, so ppy 24 and 12 are "
        "excluded from overtime detection by design"
    )


def test_ot_rule_explicit_zero_flagged():
    """hours_regular=45 with an EXPLICIT hours_overtime=0 is still flagged.

    Explicit zero is treated the same as absent (ot_missing when hours_overtime is None
    OR == 0). A client reporting '0 OT' against 45 regular hours is in exactly the same
    ambiguous position as one who omitted the field — and honoring the zero would pay
    all 45 hours at straight time, underpaying the overtime premium.
    """
    emp = _make_weekly_hourly_employee("Maria ExplicitZero")
    roster = _one_employee_roster(emp)
    extracted = _extracted(
        [
            ExtractedEmployee(
                submitted_name=emp.full_name,
                hours_regular=Decimal("45"),
                hours_overtime=Decimal("0"),  # explicit zero — treated the same as absent
            )
        ]
    )
    matches = [_match(emp.full_name, emp.id)]

    issues = validate(extracted, roster, matches)

    assert any("overtime" in i.message.lower() for i in issues), (
        "a weekly employee with hours_regular=45 AND an explicit hours_overtime=0 must "
        "STILL emit a ValidationIssue — an explicit zero is as ambiguous as an absent "
        "field, and honoring it would pay all 45 hours at straight time"
    )


# ---------------------------------------------------------------------------
# The paid-hours gate (MONEY-01).
#
# The presence test for hours must be "is this field PAID?" (not None AND > 0), not
# merely "is this field present?" (is not None). Under an is-not-None predicate an
# hourly employee submitted with an explicit hours_regular=0 looks like they reported
# hours, no missing issue is emitted, and a $0 paystub ships silently — a failure the
# run's reconciliation check cannot catch, because $0 reconciles perfectly.
#
# The two "not gated" tests below are the counterweight: the gate must fire on the
# silent-$0 case WITHOUT firing on a genuine partial week or on salaried staff.
# ---------------------------------------------------------------------------


def test_zero_hours_hourly_gates(roster_from_seed):
    """An hourly employee with hours_regular=0 and no other paid hours must gate.

    Decimal('0') is not None, so an is-not-None presence check would treat this employee
    as having reported hours, emit no issue, and ship a $0 paystub without ever asking
    the client. Zero paid hours is a question, not an answer.
    """
    maria = next(e for e in roster_from_seed.employees if e.full_name == "Maria Chen")
    # hours_regular=0, all other hours fields absent (None)
    extracted = _extracted(
        [ExtractedEmployee(submitted_name="Maria Chen", hours_regular=Decimal("0"))]
    )
    matches = [_match("Maria Chen", maria.id)]

    issues = validate(extracted, roster_from_seed, matches)

    assert issues, (
        "an hourly employee with hours_regular=Decimal('0') and all other hours absent "
        "must produce a missing issue — otherwise a $0 paystub ships silently"
    )
    assert any(i.issue_type == "missing" for i in issues), (
        "the emitted issue must be issue_type='missing'"
    )


def test_partial_week_not_gated(roster_from_seed):
    """hours_regular=0 alongside hours_holiday=8 must NOT gate.

    A genuine partial week is fully payable: the holiday hours ARE paid, so the
    zero-hours gate must not fire. A gate that keyed on hours_regular alone would send
    a pointless clarification email on every holiday week.
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

    # No missing issue — hours_holiday=8 is a paid field, so the employee did work.
    missing_issues = [i for i in issues if i.issue_type == "missing" and "hours_regular" in i.field]
    assert not missing_issues, (
        "a partial week (hours_regular=0 but hours_holiday=8) must NOT gate to "
        "clarification — the holiday hours are paid and the run should process"
    )


def test_predicate_consistency(roster_from_seed):
    """hours_overtime=Decimal('0') must gate identically to hours_overtime=None.

    Both mean 'no paid overtime', so the paid-hours predicate must not distinguish them.
    An is-not-None check does: it counts Decimal('0') as present, so an employee with
    hours_overtime=0 and every other field None slips through the gate while the
    all-None variant is correctly caught. Same money, two different outcomes.
    """
    maria = next(e for e in roster_from_seed.employees if e.full_name == "Maria Chen")

    # Case 1: all hours None — the baseline the zero case must match.
    extracted_none = _extracted(
        [ExtractedEmployee(submitted_name="Maria Chen")]  # all hours None
    )
    matches = [_match("Maria Chen", maria.id)]
    issues_none = validate(extracted_none, roster_from_seed, matches)

    # Case 2: hours_overtime=Decimal('0'), all others None — semantically identical.
    extracted_zero = _extracted(
        [ExtractedEmployee(submitted_name="Maria Chen", hours_overtime=Decimal("0"))]
    )
    issues_zero = validate(extracted_zero, roster_from_seed, matches)

    # Both must produce a missing issue: the predicate cannot distinguish them.
    assert any(i.issue_type == "missing" for i in issues_none), (
        "all-None hours must produce a missing issue (the baseline)"
    )
    assert any(i.issue_type == "missing" for i in issues_zero), (
        "hours_overtime=Decimal('0') with all other hours absent must gate identically "
        "to all-None — an is-not-None predicate lets it through silently"
    )


def test_salaried_not_gated_regression_guard(roster_from_seed):
    """A SALARIED employee with zero hours must NOT gate.

    Salaried pay computes from annual_salary and does not read the hours fields at all,
    so the paid-hours gate must never apply to them. Applying it would block every
    salary-only run behind a clarification the client cannot meaningfully answer.
    """
    james = next(e for e in roster_from_seed.employees if e.full_name == "James Okafor")
    extracted = _extracted(
        [ExtractedEmployee(submitted_name="James Okafor", hours_regular=Decimal("0"))]
    )
    matches = [_match("James Okafor", james.id)]

    issues = validate(extracted, roster_from_seed, matches)

    missing_issues = [i for i in issues if i.issue_type == "missing"]
    assert not missing_issues, (
        "salaried employees must never be gated on zero hours — their pay comes from "
        "annual_salary, so the hours fields carry no money for them"
    )
