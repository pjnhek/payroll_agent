"""Tests for detect_field_regression (Phase 7.5 Plan 02 — D-7.5-10 / R3-3 / SC2).

detect_field_regression is a PUBLIC pure function in validate.py that:
  - Takes four args: original Extracted, resumed Extracted, prior_matches (list|None),
    current_matches (list)
  - Returns list[RawFieldDrop]
  - Uses employee_id-keyed diff (not submitted_name intersection) to handle the
    restated-name case (SC2 / R3-3 fix)
  - Returns [] immediately when prior_matches is None (honest no-op)
  - Is NOT called internally by validate() — detection runs in the orchestrator
    (D-7.5-10 three-phase ordering)

validate() D-7.5-10 changes tested here:
  - validate() gains raw_field_drops= kwarg (pre-computed drops from orchestrator)
  - validate() promotes drops to ValidationIssue(issue_type="field_regression")
  - N8 resolved_drops suppression uses str(employee_id) key type
  - validate() does NOT self-detect — drops must be explicitly passed in
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from app.models.contracts import Extracted, ExtractedEmployee, RawFieldDrop
from app.models.roster import NameMatchResult, Roster
from app.pipeline.validate import detect_field_regression, validate

if TYPE_CHECKING:
    from app.models.roster import Employee

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extracted(employees: list[ExtractedEmployee]) -> Extracted:
    return Extracted(
        run_id=uuid.uuid4(),
        employees=employees,
        pay_period_start=date(2026, 6, 15),
    )


def _match(
    name: str, emp_id: uuid.UUID, source: str = "exact", resolved: bool = True
) -> NameMatchResult:
    if not resolved:
        return NameMatchResult(
            submitted_name=name,
            matched_employee_id=None,
            source="none",
            resolved=False,
            reason="no match",
        )
    return NameMatchResult(
        submitted_name=name,
        matched_employee_id=emp_id,
        source=source,
        resolved=True,
        reason="match",
    )


def _make_roster(emp_id: uuid.UUID, pay_type: str = "hourly") -> tuple[Roster, Employee]:
    """Build a minimal Roster + Employee for validate() calls."""
    from app.models.roster import Employee

    biz_id = uuid.uuid4()
    emp = Employee(
        id=emp_id,
        business_id=biz_id,
        full_name="Alice",
        known_aliases=[],
        pay_type=pay_type,
        hourly_rate=Decimal("20.00") if pay_type == "hourly" else None,
        annual_salary=Decimal("60000.00") if pay_type == "salary" else None,
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("0"),
        pay_periods_per_year=52,
    )
    return Roster(business_id=biz_id, employees=[emp]), emp


# ---------------------------------------------------------------------------
# detect_field_regression — core regression detection tests
# ---------------------------------------------------------------------------


def test_detect_regression_ot_absent():
    """OT present in original, absent in resumed → one RawFieldDrop for hours_overtime."""
    alice_id = uuid.uuid4()
    original = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("2"))])
    resumed = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=None)])
    prior_matches = [_match("Alice", alice_id)]
    current_matches = [_match("Alice", alice_id)]

    drops = detect_field_regression(original, resumed, prior_matches, current_matches)

    assert len(drops) == 1, f"expected 1 drop, got {len(drops)}"
    drop = drops[0]
    assert drop.field == "hours_overtime"
    assert drop.original_value == Decimal("2")
    assert drop.resumed_value is None
    assert drop.submitted_name == "Alice"


def test_explicit_drop_zero_resumed_value():
    """D-26: resumed hours_overtime=Decimal('0') → RawFieldDrop with
    resumed_value=Decimal('0'), NOT None.

    explicit zero preserved — confirmed_dropped signal must survive.
    """
    alice_id = uuid.uuid4()
    original = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("3"))])
    resumed = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("0"))])
    prior_matches = [_match("Alice", alice_id)]
    current_matches = [_match("Alice", alice_id)]

    drops = detect_field_regression(original, resumed, prior_matches, current_matches)

    assert len(drops) == 1
    assert drops[0].resumed_value == Decimal("0"), (
        "D-26: explicit zero must be Decimal('0'), not None (confirmed_dropped signal)"
    )


def test_no_regression_noop():
    """D-27: original and resumed identical → detect_field_regression returns []."""
    alice_id = uuid.uuid4()
    original = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("2"))])
    resumed = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("2"))])
    prior_matches = [_match("Alice", alice_id)]
    current_matches = [_match("Alice", alice_id)]

    drops = detect_field_regression(original, resumed, prior_matches, current_matches)

    assert drops == [], "no field change → no drops"


def test_predicate_consistency_ot_zero_and_absent():
    """D-25: OT 2->0 and OT 2->absent BOTH produce a RawFieldDrop (shared _is_paid predicate)."""
    alice_id = uuid.uuid4()
    prior_matches = [_match("Alice", alice_id)]
    current_matches = [_match("Alice", alice_id)]

    # Case A: OT 2 -> 0 (explicit zero)
    original_a = _extracted(
        [ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("2"))]
    )
    resumed_zero = _extracted(
        [ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("0"))]
    )
    drops_zero = detect_field_regression(original_a, resumed_zero, prior_matches, current_matches)

    # Case B: OT 2 -> absent (None)
    resumed_absent = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=None)])
    drops_absent = detect_field_regression(
        original_a, resumed_absent, prior_matches, current_matches
    )

    assert len(drops_zero) == 1, "D-25: OT 2->0 must produce a RawFieldDrop"
    assert len(drops_absent) == 1, "D-25: OT 2->absent must produce a RawFieldDrop"
    assert drops_zero[0].field == "hours_overtime"
    assert drops_absent[0].field == "hours_overtime"


def test_restated_name_same_employee_id_is_detected():
    """SC2 / R3-3 (headline restated-name case): 'M. Chen' in prior and 'Maria Chen' in resumed,
    SAME employee_id → detect_field_regression returns one RawFieldDrop.

    PREVIOUSLY FAILED because submitted_name intersection ('M. Chen' vs 'Maria Chen') was empty.
    NOW PASSES because both map to the same employee_id before diffing.
    """
    chen_id = uuid.uuid4()
    prior_matches = [_match("M. Chen", chen_id)]
    current_matches = [_match("Maria Chen", chen_id)]

    # Original run: 'M. Chen' with OT=2
    original = _extracted(
        [ExtractedEmployee(submitted_name="M. Chen", hours_overtime=Decimal("2"))]
    )
    # Resumed run: 'Maria Chen' with no OT
    resumed = _extracted([ExtractedEmployee(submitted_name="Maria Chen", hours_overtime=None)])

    drops = detect_field_regression(original, resumed, prior_matches, current_matches)

    assert len(drops) == 1, (
        "SC2/R3-3: same employee_id under different submitted names must produce a RawFieldDrop"
    )
    assert drops[0].field == "hours_overtime"
    assert drops[0].original_value == Decimal("2")
    assert drops[0].submitted_name == "Maria Chen", (
        "submitted_name on the drop must be the CURRENT (resumed) name"
    )


def test_re_resolution_different_employee_id_is_skipped():
    """D-11: if 'M. Chen' resolves to employee_A in prior but employee_B in current,
    no drop is produced — different employee_id means re-resolution, not regression.
    """
    employee_a = uuid.uuid4()
    employee_b = uuid.uuid4()
    prior_matches = [_match("M. Chen", employee_a)]
    current_matches = [_match("M. Chen", employee_b)]

    original = _extracted(
        [ExtractedEmployee(submitted_name="M. Chen", hours_overtime=Decimal("2"))]
    )
    resumed = _extracted([ExtractedEmployee(submitted_name="M. Chen", hours_overtime=None)])

    drops = detect_field_regression(original, resumed, prior_matches, current_matches)

    assert drops == [], (
        "D-11: different employee_id (re-resolution) must not produce a RawFieldDrop"
    )


def test_prior_matches_none_returns_empty():
    """Honest no-op: prior_matches=None → detect_field_regression returns [] immediately.

    Production (Plan 03) always threads prior_matches from the pre-resume reconciliation;
    this branch never fires on the real path. Documented as an honest no-op.
    """
    alice_id = uuid.uuid4()
    current_matches = [_match("Alice", alice_id)]
    original = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("2"))])
    resumed = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=None)])

    drops = detect_field_regression(original, resumed, None, current_matches)

    assert drops == [], "prior_matches=None → honest no-op, returns []"


# ---------------------------------------------------------------------------
# validate() D-7.5-10 compliant calling convention tests
# ---------------------------------------------------------------------------


def test_validate_field_regression_emitted_with_raw_drops():
    """D-7.5-10 compliant calling convention: validate() with raw_field_drops= kwarg
    → promotes pre-computed drops to ValidationIssue(issue_type='field_regression').

    validate() does NOT detect internally — it receives pre-computed drops from the
    orchestrator via raw_field_drops= (D-7.5-10 three-phase ordering).
    """
    alice_id = uuid.uuid4()
    roster, emp = _make_roster(alice_id, pay_type="hourly")

    # Simulate a backfilled extracted (OT backfilled from snapshot — so any_hours gate passes)
    extracted = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("2"))])
    matches = [_match("Alice", alice_id)]

    raw_drops = [
        RawFieldDrop(
            submitted_name="Alice",
            field="hours_overtime",
            original_value=Decimal("2"),
            resumed_value=None,
        )
    ]

    issues = validate(extracted, roster, matches, raw_field_drops=raw_drops)

    assert any(i.issue_type == "field_regression" for i in issues), (
        "validate() with raw_field_drops= must emit a field_regression ValidationIssue"
    )
    fr_issues = [i for i in issues if i.issue_type == "field_regression"]
    assert len(fr_issues) == 1
    assert "hours_overtime" in fr_issues[0].message


def test_validate_field_regression_not_emitted_when_raw_drops_none():
    """D-7.5-10 baseline: validate() without raw_field_drops= kwarg (defaults None)
    → does NOT emit a field_regression issue.

    Confirms validate() does NOT self-detect; it only promotes pre-computed drops.
    """
    alice_id = uuid.uuid4()
    roster, emp = _make_roster(alice_id, pay_type="hourly")

    # Employee has no hours — would trigger 'missing' but NOT 'field_regression'
    extracted = _extracted([ExtractedEmployee(submitted_name="Alice")])
    matches = [_match("Alice", alice_id)]

    issues = validate(extracted, roster, matches)  # no raw_field_drops= kwarg

    assert not any(i.issue_type == "field_regression" for i in issues), (
        "validate() without raw_field_drops= must NOT emit field_regression (not self-detecting)"
    )


def test_resolved_drops_suppression_is_per_field():
    """N8: resolved_drops suppresses the field_regression re-flag for suppressed fields.

    KEY TYPE: resolved_drops is set[tuple[str, str]] keyed by (employee_id_str, field).
    The N8 check uses str(current_emp_id) — UUID converted to str for consistent matching.

    resolved_drops ONLY suppresses field_regression issues; the MONEY-01 any_hours gate
    is completely unaffected.
    """
    alice_id = uuid.uuid4()
    roster, emp = _make_roster(alice_id, pay_type="hourly")
    matches = [_match("Alice", alice_id)]

    # Employee has hours_regular=0 (MONEY-01 gate fires) + no hours at all
    extracted = _extracted([ExtractedEmployee(submitted_name="Alice", hours_regular=Decimal("0"))])

    raw_drops = [
        RawFieldDrop(
            submitted_name="Alice",
            field="hours_overtime",
            original_value=Decimal("2"),
            resumed_value=None,
        )
    ]
    # resolved_drops suppresses hours_overtime for Alice (uses str(UUID) key)
    resolved_drops = {(str(alice_id), "hours_overtime")}

    issues = validate(
        extracted, roster, matches,
        resolved_drops=resolved_drops,
        raw_field_drops=raw_drops,
    )

    # MONEY-01 any_hours gate fires (missing issue — regular=0 is not paid)
    assert any(i.issue_type == "missing" for i in issues), (
        "N8: resolved_drops must NOT suppress the any_hours gate (MONEY-01)"
    )
    # field_regression is suppressed by resolved_drops
    assert not any(i.issue_type == "field_regression" for i in issues), (
        "N8: field_regression for suppressed (employee_id_str, field) must be suppressed"
    )


def test_any_hours_gate_sees_backfilled_data():
    """D-7.5-10 gate assignment: validate() receives BACKFILLED extracted
    (after orchestrator backfill).

    An employee whose OT was backfilled from snapshot (hours_overtime=2, all others None)
    is NOT flagged as missing by the any_hours gate — the backfilled value is present.

    This confirms validate() correctly receives BACKFILLED data per D-7.5-10.
    """
    alice_id = uuid.uuid4()
    roster, emp = _make_roster(alice_id, pay_type="hourly")
    matches = [_match("Alice", alice_id)]

    # Simulates the backfilled extracted: OT from snapshot (others None)
    extracted = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("2"))])

    issues = validate(extracted, roster, matches)  # no raw_field_drops

    missing_issues = [i for i in issues if i.issue_type == "missing"]
    assert not missing_issues, (
        "D-7.5-10: a carried-forward employee (OT backfilled) must NOT be flagged as missing"
    )
