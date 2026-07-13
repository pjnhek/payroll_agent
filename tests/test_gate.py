"""The code-gate tests (LLM-07) — THE THESIS. Pure, no model.

decide() is PURE CODE over resolution facts: no model call, no confidence score. There
is no model action for the code to disagree with, so the system cannot be talked into
paying the wrong person. final_action is computed deterministically and is the SOLE
branch source:

  - every name resolved + one-to-one holds + no missing field -> 'process'
  - any unresolved name (resolved is False) -> 'request_clarification'
  - any run-level collision (two distinct names -> the same employee; a duplicated
    submitted name) -> 'request_clarification', EVEN when both names resolved
    individually. Collisions are a property of the RUN, not of any one name, so
    folding them into per-name `resolved` would let a colliding pair look clean.
  - any missing required field -> 'request_clarification'
  - ZERO extracted employees -> 'request_clarification'. The degenerate run must fail
    CLOSED: every "all names resolved" and "no missing fields" check is vacuously true
    over an empty list, so without an explicit guard an empty extraction sails straight
    through to 'process'.

gate_reasons lists exactly what triggered the clarify, so the operator can always see
why. No confidence value and no model action exist anywhere in this module.
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
    # The per-name resolution detail is persisted on the decision, so the operator can
    # always see HOW each name was resolved, not just what the gate concluded.
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
# empty extraction -> clarify (the gate must fail CLOSED)
# ---------------------------------------------------------------------------


def test_empty_extraction_clarifies():
    """A run that extracts ZERO employees must NOT auto-process.

    Every other rule is reason-additive — each iterates over matches or issues — so all
    of them are vacuously satisfied by an empty list, and an empty extraction would sail
    through to 'process'. An explicit guard is what makes the degenerate run fail CLOSED.
    """
    decision = decide(_extracted(), [], [])

    assert decision.final_action == "request_clarification"
    assert any("no employees" in r.lower() for r in decision.gate_reasons)


# ---------------------------------------------------------------------------
# Run-level collisions — two RESOLVED names mapping to the SAME employee still clarify.
# A collision is a property of the RUN, never folded into per-name `resolved`.
# ---------------------------------------------------------------------------


def test_two_resolved_names_same_employee_still_clarifies():
    """The thesis in one test: both names resolve, yet the run STILL clarifies.

    "David Reyes" and "D. Reyes" each resolve cleanly and individually — but they
    collapse onto ONE employee, so the submitted hours are ambiguous: pay one line, the
    other, or the sum? A per-name view sees nothing wrong here. Only a RUN-LEVEL check
    catches it, and getting it wrong pays someone twice.
    """
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
# check_one_to_one stays a NAMED run-level function called by decide(). A clean mapping
# returns [], so the collision guard never gates a legitimately clean run.
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
    """Source-level guard: no score, no model action, no threshold anywhere in decide.

    This greps the module rather than testing behavior, because the invariant is about
    what decide is ALLOWED to contain: the moment a confidence value or a model-supplied
    action appears in this file, the decision has stopped being deterministic — even if
    every existing test still passes.
    """
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
    """A MISSING resolution record must gate the run closed.

    decide() is a pure public function the eval calls with arbitrary inputs, so it cannot
    assume reconcile produced exactly one match per employee. With 2 extracted and only 1
    resolved, trusting the input would silently DROP the unmatched employee from a
    'process' run — they simply would not get paid, and nothing would say so.
    """
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
# NameMatchResult semantic invariant
# ---------------------------------------------------------------------------


def test_name_match_result_rejects_impossible_states():
    """source, resolved, and matched_employee_id are NOT independent fields.

    A resolved match must name a real employee; an unresolved one must name none.
    Rejecting the impossible combinations at CONSTRUCTION is what lets decide() trust
    `resolved` as a single boolean — otherwise every gate check would have to re-derive
    the truth from all three fields, and one that forgot would gate open.
    """
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
