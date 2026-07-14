"""Tests for detect_hours_changes — the cross-round paid->paid VALUE CHANGE detector.

The sibling of detect_field_regression, over the SAME id-keyed pairing helper, with a
deliberately DISJOINT trigger:

  detect_field_regression   paid -> UNPAID (dropped, or explicitly zeroed) -> GATES the run
  detect_hours_changes      paid -> PAID, different value                   -> DISPLAY ONLY

The two must NEVER double-report the same transition. A drop (10 -> None) and an explicit
zeroing (10 -> Decimal('0')) both belong to the regression detector — `is_paid(Decimal('0'))`
is False, so a zero is a REGRESSION, not a change. An ADDED line (None -> 40) is an explicit
non-goal: this detector is paid->paid only.

Why display-only, and why that is not a cop-out: the accumulation design (see
tests/test_multiround_context_edge.py) says the reply's corrected value WINS and is PAID
without re-asking — a client who says "actually 30, not 40" must not be interrogated about
their own correction. That is deliberate and it stands. What was missing is that the human
who APPROVES the payroll never saw the change happen. HoursChange has no `issue_type`, so it
structurally cannot become a ValidationIssue and cannot reach decide(). That type wall IS the
display-only guarantee.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.models.contracts import Extracted, ExtractedEmployee, HoursChange
from app.models.roster import NameMatchResult
from app.pipeline.validate import detect_hours_changes

# ---------------------------------------------------------------------------
# Helpers (mirroring tests/test_detect_field_regression.py)
# ---------------------------------------------------------------------------


def _extracted(employees: list[ExtractedEmployee]) -> Extracted:
    return Extracted(
        run_id=uuid.uuid4(),
        employees=employees,
        pay_period_start=date(2026, 6, 15),
    )


def _match(name: str, emp_id: uuid.UUID) -> NameMatchResult:
    return NameMatchResult(
        submitted_name=name,
        matched_employee_id=emp_id,
        source="exact",
        resolved=True,
        reason="match",
    )


EMP_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
EMP_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


def _one_employee_change(
    original_fields: dict[str, str | None],
    resumed_fields: dict[str, str | None],
) -> list[HoursChange]:
    """Diff ONE employee across the round boundary, restating the name in the reply.

    The restated name ("M. Chen" -> "Maria Chen") is the point: the pairing is
    employee-ID-keyed, so the same person is recognised across two different strings.
    """
    original = _extracted(
        [ExtractedEmployee(submitted_name="M. Chen", **original_fields)]
    )
    resumed = _extracted(
        [ExtractedEmployee(submitted_name="Maria Chen", **resumed_fields)]
    )
    return detect_hours_changes(
        original,
        resumed,
        [_match("M. Chen", EMP_A)],
        [_match("Maria Chen", EMP_A)],
    )


# ---------------------------------------------------------------------------
# The positive case
# ---------------------------------------------------------------------------


def test_paid_to_paid_change_is_reported():
    """20 -> 40 regular: both sides paid, values differ. This is THE case."""
    changes = _one_employee_change({"hours_regular": "20"}, {"hours_regular": "40"})
    assert len(changes) == 1, f"exactly one change expected; got {changes!r}"
    c = changes[0]
    assert c.field == "hours_regular"
    assert c.original_value == Decimal("20")
    assert c.resumed_value == Decimal("40")
    assert c.submitted_name == "Maria Chen", (
        "submitted_name must come from the RESUMED employee — the name the client used "
        "in their reply. Same convention as RawFieldDrop."
    )


def test_two_changed_fields_on_one_employee_produce_two_records():
    """The live e6fa8643 shape: regular 20 -> 40 AND overtime 10 -> 2."""
    changes = _one_employee_change(
        {"hours_regular": "20", "hours_overtime": "10"},
        {"hours_regular": "40", "hours_overtime": "2"},
    )
    assert len(changes) == 2, f"one record per changed field; got {changes!r}"
    by_field = {c.field: c for c in changes}
    assert by_field["hours_regular"].original_value == Decimal("20")
    assert by_field["hours_regular"].resumed_value == Decimal("40")
    assert by_field["hours_overtime"].original_value == Decimal("10")
    assert by_field["hours_overtime"].resumed_value == Decimal("2")


# ---------------------------------------------------------------------------
# The negative cases — the boundary with detect_field_regression
# ---------------------------------------------------------------------------


def test_a_drop_is_not_a_change():
    """10 -> None is a REGRESSION, not a change. detect_field_regression owns it.

    If both detectors fired on this transition the operator would see the drop reported
    as a "change to nothing" AND be asked about it — the same money event double-reported
    through two different mechanisms.
    """
    changes = _one_employee_change(
        {"hours_regular": "40", "hours_overtime": "10"}, {"hours_regular": "40"}
    )
    assert changes == [], (
        f"a paid->absent DROP belongs to detect_field_regression, never here; got "
        f"{changes!r}"
    )


def test_an_explicit_zeroing_is_not_a_change():
    """10 -> Decimal('0') is also a REGRESSION. is_paid(Decimal('0')) is False.

    Same reason as the drop: the client removed the hours. The regression detector emits
    it (preserving the None-vs-0 intent distinction in RawFieldDrop.resumed_value); this
    one must stay silent, or the zeroing is reported twice.
    """
    changes = _one_employee_change(
        {"hours_regular": "40", "hours_overtime": "10"},
        {"hours_regular": "40", "hours_overtime": "0"},
    )
    assert changes == [], (
        f"an explicit zero is not paid — it is a regression, not a change; got {changes!r}"
    )


def test_an_added_line_is_not_a_change():
    """None -> 40 is an explicit non-goal. This detector is paid->paid ONLY."""
    changes = _one_employee_change(
        {"hours_regular": "40"}, {"hours_regular": "40", "hours_overtime": "8"}
    )
    assert changes == [], (
        f"an ADDED hours line is not a paid->paid change; got {changes!r}"
    )


def test_an_unchanged_value_is_not_a_change():
    changes = _one_employee_change({"hours_regular": "40"}, {"hours_regular": "40"})
    assert changes == [], f"40 -> 40 is not a change; got {changes!r}"


def test_an_employee_in_only_one_extraction_is_not_reported():
    """No pair, no diff. There is nothing to compare a one-sided employee against."""
    original = _extracted(
        [ExtractedEmployee(submitted_name="M. Chen", hours_regular=Decimal("20"))]
    )
    resumed = _extracted(
        [ExtractedEmployee(submitted_name="James Okafor", hours_regular=Decimal("40"))]
    )
    changes = detect_hours_changes(
        original,
        resumed,
        [_match("M. Chen", EMP_A)],
        [_match("James Okafor", EMP_B)],
    )
    assert changes == [], f"only ids present in BOTH maps are paired; got {changes!r}"


def test_prior_matches_none_is_an_honest_no_op():
    """Mirrors detect_field_regression's documented no-op: no prior identity map, no diff."""
    original = _extracted(
        [ExtractedEmployee(submitted_name="M. Chen", hours_regular=Decimal("20"))]
    )
    resumed = _extracted(
        [ExtractedEmployee(submitted_name="M. Chen", hours_regular=Decimal("40"))]
    )
    assert detect_hours_changes(original, resumed, None, [_match("M. Chen", EMP_A)]) == []


# ---------------------------------------------------------------------------
# Determinism — the records are rendered to a human; unstable order churns the page
# ---------------------------------------------------------------------------


def test_output_order_is_deterministic_across_shuffled_inputs():
    """Two employees, both changed, fed in BOTH orders — the output order must not move."""
    def _run(order: list[int]) -> list[tuple[str, str]]:
        orig_emps = [
            ExtractedEmployee(submitted_name="M. Chen", hours_regular=Decimal("20")),
            ExtractedEmployee(submitted_name="J. Okafor", hours_regular=Decimal("30")),
        ]
        res_emps = [
            ExtractedEmployee(submitted_name="Maria Chen", hours_regular=Decimal("40")),
            ExtractedEmployee(submitted_name="James Okafor", hours_regular=Decimal("35")),
        ]
        prior = [_match("M. Chen", EMP_A), _match("J. Okafor", EMP_B)]
        current = [_match("Maria Chen", EMP_A), _match("James Okafor", EMP_B)]
        changes = detect_hours_changes(
            _extracted([orig_emps[i] for i in order]),
            _extracted([res_emps[i] for i in order]),
            [prior[i] for i in order],
            [current[i] for i in order],
        )
        return [(c.submitted_name, c.field) for c in changes]

    forward = _run([0, 1])
    reversed_ = _run([1, 0])
    assert len(forward) == 2
    assert forward == reversed_, (
        f"output order must be stable regardless of input order (sorted by employee id); "
        f"got {forward!r} vs {reversed_!r}"
    )


# ---------------------------------------------------------------------------
# The type wall — this is the ENFORCEMENT MECHANISM, not a nicety
# ---------------------------------------------------------------------------


def test_hours_change_has_no_issue_type_field():
    """HoursChange structurally CANNOT become a ValidationIssue, so it cannot reach decide().

    This is not a style preference. `extra="forbid"` + no `issue_type` field means any
    attempt to route a change through the gate fails at construction, not silently in
    production. The display-only guarantee is enforced by the TYPE, not by discipline.
    """
    assert "issue_type" not in HoursChange.model_fields, (
        "HoursChange must NEVER gain an issue_type — that is the wall keeping a "
        "display-only record out of the money gate"
    )
