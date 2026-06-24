"""Persistent contract tests — CI gate with no DB connection required.

Finding #6: these tests run in CI on every push.  They are the living proof that:
- All 10 public types import from app.models
- RunStatus has exactly 11 members with the right values (mirrors Plan 02 CHECK)
- Decimal serializes to JSON strings (D-06 guard at the DB jsonb boundary)
- Decision is purely code-owned: final_action is the sole branch source and
  resolutions carries per-name detail (D-21-01 / D-21-04) — no model_action,
  no confidence, no gate_triggered
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
    """gross_pay serializes to the string '1234.56', not the float 1234.56 (D-06).

    This is the behavioral guard for WR-04: with the hand-rolled
    @field_serializer machinery removed, Pydantic v2's default Decimal -> str
    JSON serialization must still hold across all monetary fields, including a
    nullable one (state_withholding) which the old serializer special-cased.
    """
    item = PaystubLineItem(
        **_paystub_kwargs(gross_pay=Decimal("1234.56"), state_withholding=None)
    )
    dumped = item.model_dump(mode="json")
    assert isinstance(dumped["gross_pay"], str), (
        f"expected str, got {type(dumped['gross_pay'])}"
    )
    assert dumped["gross_pay"] == "1234.56"
    # A nullable Decimal still round-trips to JSON null (default behavior).
    assert dumped["state_withholding"] is None
    # fica_ss is another Decimal-bearing field that must serialize to a string
    # (Decision no longer carries a Decimal field — confidence is gone, D-21-01).
    assert dumped["fica_ss"] == "76.54"


# ---------------------------------------------------------------------------
# Decision deterministic shape (D-21-01 / D-21-04)
# ---------------------------------------------------------------------------


def test_decision_process_shape() -> None:
    """A clean process Decision validates with the deterministic field set.

    final_action is the sole branch source; there is no model_action to diverge
    from (D-21-01). resolutions carries per-name detail folded into the decision
    JSONB (D-21-04 / D-21-06).
    """
    resolution = NameMatchResult(
        submitted_name="Maria Chen",
        matched_employee_id=uuid.uuid4(),
        source="exact",
        resolved=True,
        reason="exact normalized match",
    )
    d = Decision(
        final_action="process",
        gate_reasons=[],
        unresolved_names=[],
        missing_fields=[],
        resolutions=[resolution],
    )
    assert d.final_action == "process"
    assert d.gate_reasons == []
    assert len(d.resolutions) == 1
    assert d.resolutions[0].resolved is True
    # The deterministic Decision has no model action to diverge from.
    assert not hasattr(d, "model_action")
    assert not hasattr(d, "gate_triggered")
    assert not hasattr(d, "confidence")


def test_decision_clarify_shape() -> None:
    """A request_clarification Decision validates with gate_reasons + unresolved names."""
    resolution = NameMatchResult(
        submitted_name="Dave",
        matched_employee_id=None,
        source="none",
        resolved=False,
        reason="no deterministic or alias match",
    )
    d = Decision(
        final_action="request_clarification",
        gate_reasons=["Dave: unresolved (no roster match)"],
        unresolved_names=["Dave"],
        missing_fields=[],
        resolutions=[resolution],
    )
    assert d.final_action == "request_clarification"
    assert d.unresolved_names == ["Dave"]
    assert d.gate_reasons == ["Dave: unresolved (no roster match)"]


def test_decision_resolutions_serialize_to_json() -> None:
    """Decision.model_dump(mode='json')['resolutions'] is a list of resolution dicts.

    This is what gets persisted in the decision JSONB (D-21-06) so the dashboard
    and eval can read why each name resolved/didn't.
    """
    d = Decision(
        final_action="process",
        gate_reasons=[],
        unresolved_names=[],
        missing_fields=[],
        resolutions=[
            NameMatchResult(
                submitted_name="Maria Chen",
                matched_employee_id=uuid.uuid4(),
                source="alias",
                resolved=True,
                reason="known_alias match",
            )
        ],
    )
    dumped = d.model_dump(mode="json")
    assert isinstance(dumped["resolutions"], list)
    res = dumped["resolutions"][0]
    assert res["submitted_name"] == "Maria Chen"
    assert res["source"] == "alias"
    assert res["resolved"] is True
    assert "reason" in res


def test_decision_rejects_legacy_kwargs() -> None:
    """Legacy confidence-era kwargs raise ValidationError (extra='forbid', D-21-04)."""
    base = dict(
        final_action="process",
        gate_reasons=[],
        unresolved_names=[],
        missing_fields=[],
        resolutions=[],
    )
    for dead_kwarg in (
        {"model_action": "process"},
        {"confidence": Decimal("0.95")},
        {"gate_triggered": False},
        {"reasons": ["ok"]},
    ):
        with pytest.raises(ValidationError):
            Decision(**{**base, **dead_kwarg})


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


def test_extraction_payload_nullable_pay_period_start() -> None:
    """A real email with no stated pay period must NOT crash extraction.

    Regression (06-05 live gate): a casual real email ("hours for this week:
    Dave Reyes 38") states no date, so the LLM returns pay_period_start=null (or
    omits it). pay_period_start was a REQUIRED non-nullable date, so the model
    raised ValidationError → the run errored at parse time before decide() could
    run. It must be Decimal|None-style nullable like the hours fields: a missing
    pay period is "didn't say", not a crash. The fixtures always carried a date,
    so this was invisible until a real email hit the deployed service.
    """
    from app.models.contracts import ExtractionPayload

    # LLM returns null for the unstated pay period.
    p_null = ExtractionPayload.model_validate_json(
        '{"employees": [{"submitted_name": "Dave Reyes", "hours_regular": "38", '
        '"hours_overtime": null, "hours_vacation": null, "hours_sick": null, '
        '"hours_holiday": null, "contribution_401k_override": null}], '
        '"pay_period_start": null, "pay_period_end": null}'
    )
    assert p_null.pay_period_start is None
    assert p_null.employees[0].submitted_name == "Dave Reyes"

    # LLM omits the key entirely — also tolerated (defaults to None).
    p_omitted = ExtractionPayload.model_validate_json(
        '{"employees": [{"submitted_name": "Priya", "hours_regular": null, '
        '"hours_overtime": null, "hours_vacation": null, "hours_sick": null, '
        '"hours_holiday": null, "contribution_401k_override": null}]}'
    )
    assert p_omitted.pay_period_start is None

    # A supplied date still parses to a real date (no regression).
    p_dated = ExtractionPayload.model_validate_json(
        '{"employees": [], "pay_period_start": "2026-06-15", "pay_period_end": null}'
    )
    assert str(p_dated.pay_period_start) == "2026-06-15"


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


def test_name_match_result_exact_resolved() -> None:
    """An exact deterministic resolution validates with source/resolved (D-21-04)."""
    emp_id = uuid.uuid4()
    result = NameMatchResult(
        submitted_name="Maria Chen",
        matched_employee_id=emp_id,
        source="exact",
        resolved=True,
        reason="exact normalized match",
    )
    assert result.source == "exact"
    assert result.resolved is True
    assert result.matched_employee_id == emp_id


def test_name_match_result_unresolved_none() -> None:
    """An unresolved name validates with source='none', no employee, resolved=False."""
    result = NameMatchResult(
        submitted_name="Dave",
        matched_employee_id=None,
        source="none",
        resolved=False,
        reason="no deterministic or alias match",
    )
    assert result.source == "none"
    assert result.resolved is False
    assert result.matched_employee_id is None


def test_name_match_result_rejects_bad_source() -> None:
    """source only accepts exact|alias|none — any other value raises (D-21-04)."""
    with pytest.raises(ValidationError):
        NameMatchResult(
            submitted_name="Dave",
            matched_employee_id=None,
            source="llm_typo",  # dead value from the confidence era
            resolved=False,
            reason="bad source",
        )


def test_name_match_result_rejects_confidence_kwarg() -> None:
    """A leftover confidence= kwarg raises ValidationError (extra='forbid', D-21-01)."""
    with pytest.raises(ValidationError):
        NameMatchResult(
            submitted_name="Maria Chen",
            matched_employee_id=uuid.uuid4(),
            source="exact",
            resolved=True,
            reason="r",
            confidence=Decimal("0.99"),
        )


def test_name_match_result_rejects_match_type_kwarg() -> None:
    """A leftover match_type= kwarg raises ValidationError (extra='forbid', D-21-01)."""
    with pytest.raises(ValidationError):
        NameMatchResult(
            submitted_name="Maria Chen",
            matched_employee_id=uuid.uuid4(),
            source="exact",
            resolved=True,
            reason="r",
            match_type="exact",
        )


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


# ---------------------------------------------------------------------------
# Employee compensation mutual exclusivity (WR-07)
# ---------------------------------------------------------------------------


def test_employee_hourly_rejects_stray_annual_salary() -> None:
    """An hourly Employee carrying a stray annual_salary raises ValidationError (WR-07)."""
    with pytest.raises(ValidationError):
        Employee(
            **_employee_kwargs(
                pay_type="hourly",
                hourly_rate=Decimal("18.50"),
                annual_salary=Decimal("99999"),
            )
        )


def test_employee_salary_rejects_stray_hourly_rate() -> None:
    """A salaried Employee carrying a stray hourly_rate raises ValidationError (WR-07)."""
    with pytest.raises(ValidationError):
        Employee(
            **_employee_kwargs(
                pay_type="salary",
                hourly_rate=Decimal("18.50"),
                annual_salary=Decimal("60000"),
            )
        )


# ---------------------------------------------------------------------------
# Numeric field bounds (WR-01)
# ---------------------------------------------------------------------------


def test_employee_rejects_negative_hourly_rate() -> None:
    """A negative hourly_rate raises ValidationError (WR-01)."""
    with pytest.raises(ValidationError):
        Employee(**_employee_kwargs(hourly_rate=Decimal("-50.00")))


def test_employee_rejects_negative_annual_salary() -> None:
    """A negative annual_salary raises ValidationError (WR-01)."""
    with pytest.raises(ValidationError):
        Employee(
            **_employee_kwargs(
                pay_type="salary",
                hourly_rate=None,
                annual_salary=Decimal("-60000"),
            )
        )


def test_employee_rejects_retirement_pct_above_one() -> None:
    """retirement_contribution_pct > 1 (e.g. 50 == 5000%) raises ValidationError (WR-01)."""
    with pytest.raises(ValidationError):
        Employee(**_employee_kwargs(retirement_contribution_pct=Decimal("50")))


def test_employee_rejects_negative_retirement_pct() -> None:
    """A negative retirement_contribution_pct raises ValidationError (WR-01)."""
    with pytest.raises(ValidationError):
        Employee(**_employee_kwargs(retirement_contribution_pct=Decimal("-0.01")))


def test_employee_accepts_retirement_pct_bounds() -> None:
    """retirement_contribution_pct of exactly 0 and 1 are accepted (inclusive bounds)."""
    e0 = Employee(**_employee_kwargs(retirement_contribution_pct=Decimal("0")))
    e1 = Employee(**_employee_kwargs(retirement_contribution_pct=Decimal("1")))
    assert e0.retirement_contribution_pct == Decimal("0")
    assert e1.retirement_contribution_pct == Decimal("1")


def test_extracted_employee_rejects_negative_hours() -> None:
    """ExtractedEmployee with negative hours raises ValidationError (WR-01)."""
    with pytest.raises(ValidationError):
        ExtractedEmployee(submitted_name="Bob", hours_regular=Decimal("-10"))


# ---------------------------------------------------------------------------
# PaystubLineItem confidence-free shape (D-21-01)
# ---------------------------------------------------------------------------


def test_paystub_line_item_rejects_match_confidence_kwarg() -> None:
    """A leftover match_confidence= kwarg raises ValidationError (extra='forbid').

    Confidence is gone everywhere (D-21-01); provenance on a paystub is carried
    by employee_id + submitted_name, not a score.
    """
    with pytest.raises(ValidationError):
        PaystubLineItem(**_paystub_kwargs(match_confidence=Decimal("0.99")))


# ---------------------------------------------------------------------------
# NameReconciliationResponse is deleted (D-21-05 — no layer-2 LLM wrapper)
# ---------------------------------------------------------------------------


def test_name_reconciliation_response_module_gone() -> None:
    """app.models.reconcile no longer exists (the layer-2 LLM wrapper is dead)."""
    with pytest.raises(ModuleNotFoundError):
        __import__("app.models.reconcile")


# ---------------------------------------------------------------------------
# W-4 / YTD dollar-field non-negativity (WR-08)
# ---------------------------------------------------------------------------


def test_employee_rejects_negative_ytd_ss_wages() -> None:
    """A negative ytd_ss_wages raises ValidationError (WR-08).

    A negative YTD makes remaining_cap = 184500 - ytd_ss_wages exceed the wage
    base, breaking the SS-cap straddle logic.
    """
    with pytest.raises(ValidationError):
        Employee(**_employee_kwargs(ytd_ss_wages=Decimal("-99999")))


def test_employee_rejects_negative_step_3_dependents() -> None:
    """A negative step_3_dependents raises ValidationError (WR-08).

    step_3_dependents is *subtracted* in the Pub 15-T worksheet; a negative
    value nonsensically inflates withholding.
    """
    with pytest.raises(ValidationError):
        Employee(**_employee_kwargs(step_3_dependents=Decimal("-5000")))


def test_employee_rejects_negative_step_4a_other_income() -> None:
    """A negative step_4a_other_income raises ValidationError (WR-08)."""
    with pytest.raises(ValidationError):
        Employee(**_employee_kwargs(step_4a_other_income=Decimal("-1")))


def test_employee_rejects_negative_step_4b_deductions() -> None:
    """A negative step_4b_deductions raises ValidationError (WR-08)."""
    with pytest.raises(ValidationError):
        Employee(**_employee_kwargs(step_4b_deductions=Decimal("-1")))


# ---------------------------------------------------------------------------
# pay_periods_per_year drift guard (WR-02)
# ---------------------------------------------------------------------------


def test_employee_rejects_invalid_pay_periods() -> None:
    """A pay_periods_per_year not in {12,24,26,52} raises ValidationError (WR-02).

    Mirrors schema.sql CHECK (pay_periods_per_year IN (12,24,26,52)) so a value
    like 13 cannot pass the contract and silently drift toward the DB boundary.
    """
    for bad in (0, -1, 13, 1):
        with pytest.raises(ValidationError):
            Employee(**_employee_kwargs(pay_periods_per_year=bad))


def test_employee_accepts_all_legal_pay_periods() -> None:
    """All four legal pay_periods_per_year values construct (WR-02)."""
    for good in (12, 24, 26, 52):
        e = Employee(**_employee_kwargs(pay_periods_per_year=good))
        assert e.pay_periods_per_year == good
