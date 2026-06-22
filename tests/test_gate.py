"""The code-gate tests (LLM-07, D-21-01/02/03/08) — THE THESIS. Pure, no model.

decide() is now PURE CODE over resolution facts — there is no model call and no
score. final_action is computed deterministically and is the SOLE branch source:

  - every name resolved + one-to-one holds + no missing field -> 'process'
  - any unresolved name (resolved is False) -> 'request_clarification'
  - any run-level collision (two distinct names -> same employee; a duplicated
    submitted name) -> 'request_clarification' EVEN when both names are resolved
    (D-21-02 — collisions are run-level, NOT folded into per-name resolved)
  - any missing required field -> 'request_clarification'
  - zero extracted employees -> 'request_clarification' (CR-01 / D-21-08)

gate_reasons lists exactly what triggered the clarify. No confidence, no 0.8, no
model_action anywhere.
"""
from __future__ import annotations

import pathlib
import uuid
from datetime import date
from decimal import Decimal

from app.models.contracts import Extracted, ExtractedEmployee
from app.models.roster import NameMatchResult
from app.pipeline import decide as decide_mod
from app.pipeline.decide import check_one_to_one, decide


def _extracted(*names) -> Extracted:
    return Extracted(
        run_id=uuid.uuid4(),
        employees=[
            ExtractedEmployee(submitted_name=n, hours_regular=Decimal("40"))
            for n in names
        ],
        pay_period_start=date(2026, 6, 15),
    )


def _resolved(name, emp_id=None, source="exact") -> NameMatchResult:
    """A uniquely-resolved match (source exact|alias, resolved=True)."""
    return NameMatchResult(
        submitted_name=name,
        matched_employee_id=emp_id or uuid.uuid4(),
        source=source,
        resolved=True,
        reason="t",
    )


def _unresolved(name) -> NameMatchResult:
    """An unresolved name (source='none', no employee)."""
    return NameMatchResult(
        submitted_name=name,
        matched_employee_id=None,
        source="none",
        resolved=False,
        reason="no match",
    )


# ---------------------------------------------------------------------------
# clean run -> process
# ---------------------------------------------------------------------------


def test_clean_run_processes():
    """All names resolved, one-to-one, no missing field -> process, empty gate."""
    matches = [
        _resolved("Maria Chen"),
        _resolved("James Okafor"),
    ]
    decision = decide(_extracted("Maria Chen", "James Okafor"), matches, [])

    assert decision.final_action == "process"
    assert decision.gate_reasons == []
    assert decision.unresolved_names == []
    assert decision.missing_fields == []
    # The per-name resolution detail is persisted on the decision (D-21-04).
    assert decision.resolutions == matches


# ---------------------------------------------------------------------------
# unresolved name (typo / unknown) -> clarify
# ---------------------------------------------------------------------------


def test_unresolved_name_clarifies():
    """A name with resolved=False forces clarify and lands in unresolved_names."""
    matches = [_unresolved("Maira Chen")]
    decision = decide(_extracted("Maira Chen"), matches, [])

    assert decision.final_action == "request_clarification"
    assert "Maira Chen" in decision.unresolved_names
    assert any("Maira Chen" in r and "unresolved" in r for r in decision.gate_reasons)


def test_unknown_name_clarifies():
    matches = [_unresolved("Ghost")]
    decision = decide(_extracted("Ghost"), matches, [])

    assert decision.final_action == "request_clarification"
    assert "Ghost" in decision.unresolved_names


# ---------------------------------------------------------------------------
# missing required field -> clarify
# ---------------------------------------------------------------------------


def test_missing_field_clarifies():
    from app.models.roster import ValidationIssue

    matches = [_resolved("Maria Chen")]
    issues = [
        ValidationIssue(
            field="Maria Chen.hours_regular", issue_type="missing", message="no hours"
        )
    ]
    decision = decide(_extracted("Maria Chen"), matches, issues)

    assert decision.final_action == "request_clarification"
    assert "Maria Chen.hours_regular" in decision.missing_fields


# ---------------------------------------------------------------------------
# empty extraction (CR-01 / D-21-08) -> clarify
# ---------------------------------------------------------------------------


def test_empty_extraction_clarifies():
    """CR-01 — a run that extracts ZERO employees must NOT auto-process. The other
    rules are reason-additive (they iterate matches/issues), so an explicit Rule 0
    fails the gate closed on the degenerate run (D-21-08)."""
    decision = decide(_extracted(), [], [])

    assert decision.final_action == "request_clarification"
    assert any("no employees" in r.lower() for r in decision.gate_reasons)


# ---------------------------------------------------------------------------
# run-level collisions (D-21-02) — the money shot: two RESOLVED names that map to
# the SAME employee still clarify. Collisions are run-level, NOT per-name resolved.
# ---------------------------------------------------------------------------


def test_two_resolved_names_same_employee_still_clarifies():
    """The thesis money shot: BOTH names are resolved=True, yet they collapse onto
    one employee, so the run still clarifies (D-21-02 — a resolved name can sit in
    a run that clarifies on a cross-name collision)."""
    shared = uuid.uuid4()
    matches = [
        _resolved("David Reyes", emp_id=shared, source="exact"),
        _resolved("D. Reyes", emp_id=shared, source="alias"),
    ]
    decision = decide(_extracted("David Reyes", "D. Reyes"), matches, [])

    # Both names individually resolved, but the RUN clarifies on the collision.
    assert all(m.resolved is True for m in matches)
    assert decision.final_action == "request_clarification"
    assert any("David Reyes" in r and "D. Reyes" in r for r in decision.gate_reasons)


def test_duplicate_submitted_name_clarifies():
    """A duplicated submitted name is a run-level collision -> clarify."""
    eid = uuid.uuid4()
    matches = [
        _resolved("Maria Chen", emp_id=eid),
        _resolved("Maria Chen", emp_id=eid),
    ]
    decision = decide(_extracted("Maria Chen", "Maria Chen"), matches, [])

    assert decision.final_action == "request_clarification"
    assert any("Maria Chen" in r for r in decision.gate_reasons)


# ---------------------------------------------------------------------------
# check_one_to_one stays a named RUN-LEVEL function (D-21-02) and is called by
# decide(); a clean mapping returns [] so it never gates a legitimately clean run.
# ---------------------------------------------------------------------------


def test_check_one_to_one_clean_returns_empty():
    clean = [
        _resolved("Maria Chen", emp_id=uuid.uuid4()),
        _resolved("James Okafor", emp_id=uuid.uuid4()),
    ]
    assert check_one_to_one(clean, _extracted("Maria Chen", "James Okafor")) == []


def test_check_one_to_one_flags_two_names_one_employee():
    shared = uuid.uuid4()
    matches = [
        _resolved("David Reyes", emp_id=shared),
        _resolved("D. Reyes", emp_id=shared),
    ]
    out = check_one_to_one(matches, _extracted("David Reyes", "D. Reyes"))
    assert any("David Reyes" in r and "D. Reyes" in r for r in out)


def test_decide_calls_check_one_to_one():
    """check_one_to_one is genuinely invoked by decide() (run-level, not folded
    into per-name resolved) — spy on it."""
    called = {"n": 0}
    real = decide_mod.check_one_to_one

    def _spy(matches, extracted):
        called["n"] += 1
        return real(matches, extracted)

    decide_mod.check_one_to_one = _spy
    try:
        decide(_extracted("Maria Chen"), [_resolved("Maria Chen")], [])
    finally:
        decide_mod.check_one_to_one = real
    assert called["n"] == 1, "decide() must call check_one_to_one"


# ---------------------------------------------------------------------------
# purity + grep-clean: no llm param, no confidence/0.8/model_action in source
# ---------------------------------------------------------------------------


def test_decide_is_pure_no_llm():
    import inspect

    params = inspect.signature(decide).parameters
    assert "llm" not in params, "decide must not take an llm parameter"


def test_decide_source_has_no_confidence_or_model_action():
    """Source-level guard: the deterministic decision carries no score, no model
    action, and no 0.8 threshold anywhere (D-21-01)."""
    src = pathlib.Path(decide_mod.__file__).read_text()
    lowered = src.lower()
    assert "confidence" not in lowered
    assert "model_action" not in lowered
    assert "0.8" not in src
    assert "_threshold" not in lowered


# ---------------------------------------------------------------------------
# fail-closed: matches must be one-for-one with the extracted employees
# ---------------------------------------------------------------------------


def test_decide_clarifies_when_a_match_record_is_missing():
    """Review fix: decide() is a pure public function the eval calls with arbitrary
    inputs, so it must not trust that reconcile produced one match per employee. A
    MISSING resolution record (here: 2 extracted, only 1 resolved) must gate the run
    closed rather than silently drop the unmatched employee from a 'process' run."""
    matches = [_resolved("Maria Chen")]  # James Okafor has NO resolution record
    decision = decide(_extracted("Maria Chen", "James Okafor"), matches, [])
    assert decision.final_action == "request_clarification"
    assert any("one-for-one" in r for r in decision.gate_reasons)


def test_decide_clarifies_when_a_match_record_is_extra():
    """Symmetric: an EXTRA resolution record (3 resolved, 2 extracted) also fails
    closed — the resolution set must mirror the extracted employees exactly."""
    matches = [_resolved("Maria Chen"), _resolved("James Okafor"), _resolved("Ghost")]
    decision = decide(_extracted("Maria Chen", "James Okafor"), matches, [])
    assert decision.final_action == "request_clarification"


# ---------------------------------------------------------------------------
# NameMatchResult semantic invariant (review fix)
# ---------------------------------------------------------------------------


def test_name_match_result_rejects_impossible_states():
    """source/resolved/matched_employee_id are not independent — a resolved match
    must name a real employee and an unresolved one must name none. Impossible
    combinations must raise at construction so decide() can trust `resolved`."""
    import pytest
    from pydantic import ValidationError

    # source='none' but resolved=True / has an id → invalid
    with pytest.raises(ValidationError):
        NameMatchResult(
            submitted_name="x", matched_employee_id=None,
            source="none", resolved=True, reason="bad",
        )
    # source='exact' but resolved=False → invalid
    with pytest.raises(ValidationError):
        NameMatchResult(
            submitted_name="x", matched_employee_id=uuid.uuid4(),
            source="exact", resolved=False, reason="bad",
        )
    # source='alias' but no employee id → invalid
    with pytest.raises(ValidationError):
        NameMatchResult(
            submitted_name="x", matched_employee_id=None,
            source="alias", resolved=True, reason="bad",
        )
