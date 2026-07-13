"""Tests for detect_field_regression — the "did you forget the OT?" detector.

detect_field_regression is a PUBLIC pure function in validate.py that:
  - Takes four args: original Extracted, resumed Extracted, prior_matches (list|None),
    current_matches (list)
  - Returns list[RawFieldDrop]
  - Diffs on employee_id, NOT on submitted_name intersection — a client who restates a
    name in their reply ("I meant M. Chen") would otherwise look like a different
    person, and the dropped field would go undetected
  - Returns [] immediately when prior_matches is None (an honest no-op, not a guess)
  - Is NOT called internally by validate(): detection must run in the orchestrator on
    the RAW reply, BEFORE the carry-forward backfill, or the backfill would restore the
    very value the detector is supposed to notice is missing

The validate() side tested here:
  - validate() takes a raw_field_drops= kwarg (drops pre-computed by the orchestrator)
  - validate() promotes those drops to ValidationIssue(issue_type="field_regression")
  - the resolved-drops suppression keys on str(employee_id)
  - validate() does NOT self-detect — drops must be passed in explicitly
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
    """resumed hours_overtime=Decimal('0') → RawFieldDrop carrying
    resumed_value=Decimal('0'), NOT None.

    An explicit zero is the client SAYING "no overtime this week", which is different
    from omitting the field. Collapsing it to None would let the backfill restore the
    original OT — paying overtime the client just removed.
    """
    alice_id = uuid.uuid4()
    original = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("3"))])
    resumed = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("0"))])
    prior_matches = [_match("Alice", alice_id)]
    current_matches = [_match("Alice", alice_id)]

    drops = detect_field_regression(original, resumed, prior_matches, current_matches)

    assert len(drops) == 1
    assert drops[0].resumed_value == Decimal("0"), (
        "an explicit zero must be preserved as Decimal('0'), not flattened to None — "
        "it is the client's removal signal, and the backfill must honor it"
    )


def test_no_regression_noop():
    """original and resumed identical → detect_field_regression returns []."""
    alice_id = uuid.uuid4()
    original = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("2"))])
    resumed = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("2"))])
    prior_matches = [_match("Alice", alice_id)]
    current_matches = [_match("Alice", alice_id)]

    drops = detect_field_regression(original, resumed, prior_matches, current_matches)

    assert drops == [], "no field change → no drops"


def test_predicate_consistency_ot_zero_and_absent():
    """OT 2->0 and OT 2->absent BOTH produce a RawFieldDrop.

    Both are "the money that was there is gone" and both must be surfaced. The drop's
    resumed_value is what later distinguishes them (removal vs omission).
    """
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

    assert len(drops_zero) == 1, "OT 2->0 must produce a RawFieldDrop"
    assert len(drops_absent) == 1, "OT 2->absent must produce a RawFieldDrop"
    assert drops_zero[0].field == "hours_overtime"
    assert drops_absent[0].field == "hours_overtime"


def test_restated_name_same_employee_id_is_detected():
    """The headline restated-name case: 'M. Chen' in prior and 'Maria Chen' in resumed,
    SAME employee_id → one RawFieldDrop.

    A submitted_name intersection is empty here ('M. Chen' vs 'Maria Chen'), so a
    name-keyed diff sees no shared employee and reports no drop — the client restates a
    name, drops the OT, and the OT loss goes unnoticed. Keying on employee_id is what
    makes the restated name survive the diff.
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
        "the same employee_id under two different submitted names must still produce "
        "a RawFieldDrop"
    )
    assert drops[0].field == "hours_overtime"
    assert drops[0].original_value == Decimal("2")
    assert drops[0].submitted_name == "Maria Chen", (
        "submitted_name on the drop must be the CURRENT (resumed) name"
    )


def test_re_resolution_different_employee_id_is_skipped():
    """If 'M. Chen' resolves to employee_A in prior but employee_B in current, no drop is
    produced — a different employee_id means the name was RE-RESOLVED to someone else,
    not that one person's field regressed. Reporting a drop here would carry employee_A's
    hours forward onto employee_B.
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
        "a different employee_id (re-resolution) must not produce a RawFieldDrop"
    )


def test_prior_matches_none_returns_empty():
    """Honest no-op: prior_matches=None → detect_field_regression returns [] immediately.

    Production always threads prior_matches from the pre-resume reconciliation, so this
    branch never fires on the real path. With no prior resolution there is nothing to
    diff against, and inventing one would be a guess.
    """
    alice_id = uuid.uuid4()
    current_matches = [_match("Alice", alice_id)]
    original = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("2"))])
    resumed = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=None)])

    drops = detect_field_regression(original, resumed, None, current_matches)

    assert drops == [], "prior_matches=None → honest no-op, returns []"


# ---------------------------------------------------------------------------
# validate()'s calling convention — it promotes drops, it does not detect them
# ---------------------------------------------------------------------------


def test_validate_field_regression_emitted_with_raw_drops():
    """validate(raw_field_drops=...) promotes pre-computed drops to
    ValidationIssue(issue_type='field_regression').

    validate() runs AFTER the backfill, so it cannot detect drops itself — by then the
    dropped value has been restored. Detection happens in the orchestrator against the
    RAW reply, and the result is handed in here.
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
    """validate() without raw_field_drops= (defaults None) does NOT emit a
    field_regression issue — confirming it never self-detects, only promotes.
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
    """resolved_drops suppresses the field_regression re-flag for already-answered fields.

    KEY TYPE: resolved_drops is set[tuple[str, str]] keyed by (employee_id_str, field) —
    the UUID must be str()'d on both sides or the lookup silently never matches and the
    run re-clarifies a field the client already answered (an infinite clarify loop).

    resolved_drops suppresses ONLY field_regression issues. The zero-hours gate is
    completely unaffected: a suppressed drop must never be able to unlock a $0 paystub.
    """
    alice_id = uuid.uuid4()
    roster, emp = _make_roster(alice_id, pay_type="hourly")
    matches = [_match("Alice", alice_id)]

    # Employee has hours_regular=0 — the zero-hours gate must fire
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

    # The zero-hours gate still fires (regular=0 is not paid hours)
    assert any(i.issue_type == "missing" for i in issues), (
        "resolved_drops must NOT suppress the zero-hours gate — suppressing a "
        "clarified field can never open the door to a silent $0 paystub"
    )
    # field_regression is suppressed by resolved_drops
    assert not any(i.issue_type == "field_regression" for i in issues), (
        "a field the client already answered must not be re-flagged, or the run "
        "clarifies the same field forever"
    )


def test_any_hours_gate_sees_backfilled_data():
    """validate() receives the BACKFILLED extracted, so carried-forward values count.

    An employee whose OT was restored from the snapshot (hours_overtime=2, all others
    None) must NOT be flagged as missing — the backfilled value is real paid hours.
    Validating the pre-backfill data instead would gate a run that has everything it
    needs.
    """
    alice_id = uuid.uuid4()
    roster, emp = _make_roster(alice_id, pay_type="hourly")
    matches = [_match("Alice", alice_id)]

    # Simulates the backfilled extracted: OT from snapshot (others None)
    extracted = _extracted([ExtractedEmployee(submitted_name="Alice", hours_overtime=Decimal("2"))])

    issues = validate(extracted, roster, matches)  # no raw_field_drops

    missing_issues = [i for i in issues if i.issue_type == "missing"]
    assert not missing_issues, (
        "a carried-forward employee (OT backfilled) must NOT be flagged as missing"
    )
