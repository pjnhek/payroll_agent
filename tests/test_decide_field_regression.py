"""Tests for decide() Rule 2b — field_regression issues gate to request_clarification.

Phase 7.5 Plan 02 (D-17, C-1 resolution, MONEY-03):
  - Rule 2b: field_regression issues → gate_reasons (like Rule 2 for missing)
  - Decision.missing_fields is NOT widened (regressions feed gate_reasons only)
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.models.contracts import Extracted, ExtractedEmployee
from app.models.roster import NameMatchResult, ValidationIssue
from app.pipeline.decide import decide


def _extracted(*names: str) -> Extracted:
    return Extracted(
        run_id=uuid.uuid4(),
        employees=[
            ExtractedEmployee(submitted_name=n, hours_regular=Decimal("40"))
            for n in names
        ],
        pay_period_start=date(2026, 6, 15),
    )


def _resolved(name: str, emp_id: uuid.UUID | None = None) -> NameMatchResult:
    return NameMatchResult(
        submitted_name=name,
        matched_employee_id=emp_id or uuid.uuid4(),
        source="exact",
        resolved=True,
        reason="match",
    )


def test_field_regression_issue_gates_to_clarification():
    """Rule 2b: ValidationIssue(issue_type='field_regression') must gate the run to
    request_clarification, and the gate_reason must mention 'field regression'.

    Currently FAILS because decide() only checks issue_type='missing' (Rule 2).
    Plan 02 adds Rule 2b for field_regression.
    """
    alice_id = uuid.uuid4()
    extracted = _extracted("Alice")
    matches = [_resolved("Alice", alice_id)]
    issues = [
        ValidationIssue(
            issue_type="field_regression",
            field="alice.hours_overtime",
            message="field regression: hours_overtime was 2, now absent",
        )
    ]

    decision = decide(extracted, matches, issues)

    assert decision.final_action == "request_clarification", (
        "Rule 2b: a field_regression issue must gate to request_clarification"
    )
    assert any("field regression" in r for r in decision.gate_reasons), (
        "Rule 2b: gate_reasons must contain a 'field regression' entry"
    )


def test_field_regression_does_not_widen_missing_fields():
    """Rule 2b: regressions feed gate_reasons only, NOT Decision.missing_fields.

    D-7.5 PATTERNS §4: missing_fields stays scoped to issue_type='missing'.
    """
    alice_id = uuid.uuid4()
    extracted = _extracted("Alice")
    matches = [_resolved("Alice", alice_id)]
    issues = [
        ValidationIssue(
            issue_type="field_regression",
            field="alice.hours_overtime",
            message="regression",
        )
    ]

    decision = decide(extracted, matches, issues)

    assert decision.missing_fields == [], (
        "Rule 2b: Decision.missing_fields must NOT include field_regression fields"
    )
    assert decision.final_action == "request_clarification"


def test_field_regression_gate_reason_format():
    """The gate_reason string format is 'field regression: {ValidationIssue.field}'.

    ValidationIssue.field = '{submitted_name}.{field_name}' (qualified).
    compose_email uses this format to parse submitted_name and field_name.
    """
    alice_id = uuid.uuid4()
    extracted = _extracted("Alice")
    matches = [_resolved("Alice", alice_id)]
    issues = [
        ValidationIssue(
            issue_type="field_regression",
            field="Alice.hours_overtime",
            message="regression",
        )
    ]

    decision = decide(extracted, matches, issues)

    fr_reasons = [r for r in decision.gate_reasons if r.startswith("field regression:")]
    assert len(fr_reasons) == 1
    assert "Alice.hours_overtime" in fr_reasons[0], (
        "gate_reason format must be 'field regression: {submitted_name}.{field_name}'"
    )


def test_clean_run_with_regression_is_gated():
    """A run that would otherwise process is gated when there is a field_regression issue.

    All names resolved, no collision, no 'missing' issue — but field_regression gates it.
    """
    alice_id = uuid.uuid4()
    extracted = _extracted("Alice")
    matches = [_resolved("Alice", alice_id)]

    # No issues → should process
    decision_clean = decide(extracted, matches, [])
    assert decision_clean.final_action == "process", "baseline: clean run processes"

    # Same run + field_regression issue → must gate
    issues = [
        ValidationIssue(
            issue_type="field_regression",
            field="Alice.hours_overtime",
            message="regression",
        )
    ]
    decision_gated = decide(extracted, matches, issues)
    assert decision_gated.final_action == "request_clarification", (
        "Rule 2b: field_regression issue must convert a clean run to request_clarification"
    )
