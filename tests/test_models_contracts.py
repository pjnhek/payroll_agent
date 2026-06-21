"""Persistent contract tests — CI gate with no DB connection required.

Finding #6: these tests run in CI on every push.  They are the living proof that:
- All 10 public types import from app.models
- RunStatus has exactly 11 members with the right values (mirrors Plan 02 CHECK)
- Decimal serializes to JSON strings (D-06 guard at the DB jsonb boundary)
- Decision carries structurally-separate model_action + final_action (D-08)
- ExtractedEmployee hours are nullable so missing-hours cases don't parse-crash (Finding #3)
- Employee enforces the pay_type compensation invariant at construction (D-10/FOUND-06)
"""
import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models import (
    Decision,
    Employee,
    Extracted,
    ExtractedEmployee,
    InboundEmail,
    NameMatchResult,
    PaystubLineItem,
    Roster,
    RunStatus,
    ValidationIssue,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = "2026-06-20T12:00:00Z"
_TODAY = "2026-06-16"


def _employee_kwargs(**overrides) -> dict:
    """Return a minimal valid Employee field dict."""
    base = dict(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        full_name="Alice Smith",
        known_aliases=[],
        pay_type="hourly",
        hourly_rate=Decimal("25.00"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0.03"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("0"),
        pay_periods_per_year=52,
    )
    base.update(overrides)
    return base


def _paystub_kwargs(**overrides) -> dict:
    """Return a minimal valid PaystubLineItem field dict."""
    import datetime

    base = dict(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        submitted_name="Alice Smith",
        match_confidence=Decimal("0.99"),
        hours_regular=Decimal("40"),
        hours_overtime=Decimal("0"),
        hours_vacation=Decimal("0"),
        hours_sick=Decimal("0"),
        hours_holiday=Decimal("0"),
        gross_pay=Decimal("1234.56"),
        pretax_401k=Decimal("37.04"),
        fica_ss=Decimal("76.54"),
        fica_medicare=Decimal("17.90"),
        federal_withholding=Decimal("123.45"),
        state_withholding=None,
        net_pay=Decimal("979.63"),
        created_at=datetime.datetime(2026, 6, 20, 12, 0, 0),
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# test_imports
# ---------------------------------------------------------------------------


def test_imports() -> None:
    """All 10 public names import from app.models without error (Finding #6)."""
    # The import at the top of this file already exercises this; an explicit
    # assertion makes the intent clear in the test output.
    for name in (
        RunStatus,
        InboundEmail,
        Extracted,
        ExtractedEmployee,
        Decision,
        PaystubLineItem,
        Roster,
        Employee,
        NameMatchResult,
        ValidationIssue,
    ):
        assert name is not None


# ---------------------------------------------------------------------------
# RunStatus
# ---------------------------------------------------------------------------


def test_run_status_count() -> None:
    """RunStatus has exactly 11 members (D-02 / D-03)."""
    assert len(RunStatus) == 11


def test_run_status_values() -> None:
    """RunStatus values match the 11-value set verbatim (mirrors Plan 02 CHECK)."""
    expected = {
        "received",
        "extracting",
        "needs_clarification",
        "awaiting_reply",
        "computed",
        "awaiting_approval",
        "approved",
        "sent",
        "reconciled",
        "rejected",
        "error",
    }
    assert {s.value for s in RunStatus} == expected


# ---------------------------------------------------------------------------
# Decimal JSON serialization (D-06)
# ---------------------------------------------------------------------------


def test_decimal_json_serialization() -> None:
    """gross_pay serializes to the string '1234.56', not the float 1234.56 (D-06)."""
    item = PaystubLineItem(**_paystub_kwargs(gross_pay=Decimal("1234.56")))
    dumped = item.model_dump(mode="json")
    assert isinstance(dumped["gross_pay"], str), (
        f"expected str, got {type(dumped['gross_pay'])}"
    )
    assert dumped["gross_pay"] == "1234.56"


# ---------------------------------------------------------------------------
# Decision gate shape (D-08)
# ---------------------------------------------------------------------------


def test_decision_gate_shape() -> None:
    """model_action and final_action can differ when gate fires (D-08)."""
    d = Decision(
        model_action="process",
        gate_triggered=True,
        gate_reasons=["confidence below 0.8"],
        final_action="request_clarification",
        unresolved_names=["Reyez"],
        missing_fields=[],
        confidence=Decimal("0.72"),
        reasons=["name confidence 0.72 below threshold 0.80"],
    )
    assert d.model_action != d.final_action
    assert d.gate_triggered is True
    assert d.unresolved_names == ["Reyez"]


def test_decision_pass_through() -> None:
    """Decision with model_action == final_action validates (happy path, no gate)."""
    d = Decision(
        model_action="process",
        gate_triggered=False,
        gate_reasons=[],
        final_action="process",
        unresolved_names=[],
        missing_fields=[],
        confidence=Decimal("0.95"),
        reasons=["all names matched cleanly"],
    )
    assert d.model_action == d.final_action == "process"
    assert d.gate_triggered is False


# ---------------------------------------------------------------------------
# ExtractedEmployee nullable hours (Finding #3)
# ---------------------------------------------------------------------------


def test_extracted_employee_nullable_hours() -> None:
    """ExtractedEmployee with all hours=None validates without error (Finding #3).

    If hours were non-nullable, a client email with missing hours would raise
    ValidationError before decide() can inspect missing_fields and gate the run.
    """
    e = ExtractedEmployee(
        submitted_name="Bob",
        hours_regular=None,
        hours_overtime=None,
        hours_vacation=None,
        hours_sick=None,
        hours_holiday=None,
        contribution_401k_override=None,
    )
    assert e.submitted_name == "Bob"
    assert e.hours_regular is None


def test_extracted_employee_fully_supplied() -> None:
    """ExtractedEmployee with all hours supplied also validates."""
    e = ExtractedEmployee(
        submitted_name="Alice",
        hours_regular=Decimal("40"),
        hours_overtime=Decimal("0"),
        hours_vacation=Decimal("0"),
        hours_sick=Decimal("0"),
        hours_holiday=Decimal("0"),
        contribution_401k_override=None,
    )
    assert e.hours_regular == Decimal("40")


# ---------------------------------------------------------------------------
# Roster shapes
# ---------------------------------------------------------------------------


def test_employee_valid() -> None:
    """A fully-specified hourly Employee validates without error."""
    e = Employee(**_employee_kwargs())
    assert e.pay_type == "hourly"
    assert e.hourly_rate == Decimal("25.00")


def test_roster_valid() -> None:
    """Roster with one employee validates without error."""
    employee = Employee(**_employee_kwargs())
    roster = Roster(business_id=uuid.uuid4(), employees=[employee])
    assert len(roster.employees) == 1


# ---------------------------------------------------------------------------
# NameMatchResult
# ---------------------------------------------------------------------------


def test_name_match_result() -> None:
    """NameMatchResult with llm_typo match validates."""
    result = NameMatchResult(
        submitted_name="Reyez",
        matched_employee_id=uuid.uuid4(),
        match_type="llm_typo",
        confidence=Decimal("0.72"),
        reason="likely typo of Reyes",
    )
    assert result.match_type == "llm_typo"
    assert result.confidence == Decimal("0.72")


# ---------------------------------------------------------------------------
# ValidationIssue
# ---------------------------------------------------------------------------


def test_validation_issue() -> None:
    """ValidationIssue with missing issue_type validates."""
    issue = ValidationIssue(
        field="hours_regular",
        issue_type="missing",
        message="hours_regular not present",
    )
    assert issue.issue_type == "missing"


# ---------------------------------------------------------------------------
# Employee compensation invariant (FIX A — D-10/FOUND-06)
# ---------------------------------------------------------------------------


def test_employee_hourly_requires_hourly_rate() -> None:
    """An hourly Employee without hourly_rate raises ValidationError (D-10)."""
    with pytest.raises(ValidationError):
        Employee(**_employee_kwargs(pay_type="hourly", hourly_rate=None))


def test_employee_salary_requires_annual_salary() -> None:
    """A salaried Employee without annual_salary raises ValidationError (D-10)."""
    with pytest.raises(ValidationError):
        Employee(
            **_employee_kwargs(pay_type="salary", hourly_rate=None, annual_salary=None)
        )


def test_employee_salary_valid() -> None:
    """A salaried Employee with annual_salary validates without error."""
    e = Employee(
        **_employee_kwargs(
            pay_type="salary",
            hourly_rate=None,
            annual_salary=Decimal("60000"),
        )
    )
    assert e.annual_salary == Decimal("60000")
    assert e.hourly_rate is None
