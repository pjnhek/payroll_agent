"""The code-gate tests (LLM-07/08/09) — THE THESIS. Mocked LLM, deterministic.

These prove decide.py's gate: a sub-0.8 / unresolved / missing-field name forces
final_action="request_clarification" EVEN WHEN the model says "process", the gate
evaluates EACH name (not the collapsed scalar), check_one_to_one is a real called
function, and confidence collapses via min().
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.models.contracts import Extracted, ExtractedEmployee
from app.models.roster import NameMatchResult
from app.pipeline import decide as decide_mod
from app.pipeline.decide import check_one_to_one, decide


class _StubLLM:
    """Returns a fixed advisory model_action without any network."""

    def __init__(self, model_action="process", reasons=None):
        self._action = model_action
        self._reasons = reasons or ["advisory"]
        self.calls = 0

    def call_structured(self, tier, messages, response_model):
        self.calls += 1
        return response_model(model_action=self._action, reasons=self._reasons)


def _extracted(*names) -> Extracted:
    return Extracted(
        run_id=uuid.uuid4(),
        employees=[ExtractedEmployee(submitted_name=n, hours_regular=Decimal("40")) for n in names],
        pay_period_start=date(2026, 6, 15),
    )


def _match(name, conf, mtype="llm_typo", emp_id=None) -> NameMatchResult:
    return NameMatchResult(
        submitted_name=name,
        matched_employee_id=emp_id or uuid.uuid4(),
        match_type=mtype,
        confidence=Decimal(conf),
        reason="t",
    )


# ---------------------------------------------------------------------------
# THE THESIS — sub-0.8 confidence hard-blocks even when the model says "process"
# ---------------------------------------------------------------------------


def test_sub_threshold_blocks_process():
    llm = _StubLLM(model_action="process")
    matches = [_match("David Reyez", "0.6")]
    decision = decide(_extracted("David Reyez"), matches, [], llm=llm)

    assert decision.model_action == "process"
    assert decision.final_action == "request_clarification", (
        "the gate must force clarify on a sub-0.8 name even when the model says process"
    )
    assert decision.gate_triggered is True
    assert "David Reyez" in decision.unresolved_names
    assert any("0.6" in r for r in decision.gate_reasons)


def test_per_name_not_average():
    """One 0.6 name among three 1.0 names fires the gate — proving the per-name
    test, not the collapsed scalar (a min/avg would let it hide)."""
    llm = _StubLLM(model_action="process")
    matches = [
        _match("Ann", "1.0", mtype="exact"),
        _match("Bob", "1.0", mtype="exact"),
        _match("David Reyez", "0.6"),
    ]
    decision = decide(_extracted("Ann", "Bob", "David Reyez"), matches, [], llm=llm)
    assert decision.final_action == "request_clarification"
    assert "David Reyez" in decision.unresolved_names
    # The audit scalar collapses to the weakest link (min), but the GATE used the
    # per-name test above, not this scalar.
    assert decision.confidence == Decimal("0.6")


def test_check_one_to_one_stub_shape():
    """check_one_to_one exists with the FINAL signature, is called inside decide(),
    and returns a list (empty-but-real; Plan 03 extends it)."""
    out = check_one_to_one([], _extracted())
    assert isinstance(out, list)

    # And it is genuinely invoked by decide() — spy on it.
    called = {"n": 0}
    real = decide_mod.check_one_to_one

    def _spy(matches, extracted):
        called["n"] += 1
        return real(matches, extracted)

    decide_mod.check_one_to_one = _spy
    try:
        decide(
            _extracted("Maria Chen"),
            [_match("Maria Chen", "1.0", mtype="exact")],
            [],
            llm=_StubLLM(),
        )
    finally:
        decide_mod.check_one_to_one = real
    assert called["n"] == 1, "decide() must call check_one_to_one"


def test_empty_extraction_blocks_process():
    """CR-01 — a run that extracts ZERO employees must NOT auto-process even when the
    model says 'process'. With no matches/issues the reason-additive gate rules never
    fire, so an explicit Rule 0 is what fails the gate closed on the degenerate run.
    Without it, final_action collapses to model_action and an empty payroll reaches
    awaiting_approval as if clean.
    """
    llm = _StubLLM(model_action="process")
    # Zero extracted employees, zero matches, zero issues — the degenerate run.
    decision = decide(_extracted(), [], [], llm=llm)

    assert decision.model_action == "process"
    assert decision.final_action == "request_clarification", (
        "a zero-employee run must gate to clarify even when the model says process"
    )
    assert decision.gate_triggered is True
    assert any("no employees" in r.lower() for r in decision.gate_reasons), (
        "the empty-extraction gate must record a legible gate_reason"
    )


def test_clean_run_collapses_to_one_and_processes():
    """A clean run with no LLM-layer names: confidence collapses to 1.0 via min()
    and final_action == model_action == 'process'."""
    llm = _StubLLM(model_action="process")
    # All-deterministic matches (confidence 1.0).
    matches = [
        _match("Maria Chen", "1.0", mtype="exact"),
        _match("James Okafor", "1.0", mtype="exact"),
    ]
    decision = decide(_extracted("Maria Chen", "James Okafor"), matches, [], llm=llm)
    assert decision.final_action == "process"
    assert decision.model_action == "process"
    assert decision.gate_triggered is False
    assert decision.confidence == Decimal("1.0")


def test_unresolved_name_blocks():
    llm = _StubLLM(model_action="process")
    matches = [
        NameMatchResult(
            submitted_name="Ghost",
            matched_employee_id=None,
            match_type="unknown",
            confidence=Decimal("0.0"),
            reason="no match",
        )
    ]
    decision = decide(_extracted("Ghost"), matches, [], llm=llm)
    assert decision.final_action == "request_clarification"
    assert "Ghost" in decision.unresolved_names


def test_missing_field_blocks():
    from app.models.roster import ValidationIssue

    llm = _StubLLM(model_action="process")
    matches = [_match("Maria Chen", "1.0", mtype="exact")]
    issues = [
        ValidationIssue(
            field="Maria Chen.hours_regular", issue_type="missing", message="no hours"
        )
    ]
    decision = decide(_extracted("Maria Chen"), matches, issues, llm=llm)
    assert decision.final_action == "request_clarification"
    assert "Maria Chen.hours_regular" in decision.missing_fields


def test_gate_uses_decimal_threshold_not_float_source():
    """Source-level: decide.py compares against Decimal('0.8'), never the float."""
    import pathlib

    src = pathlib.Path(decide_mod.__file__).read_text()
    assert 'Decimal("0.8")' in src, "gate must use Decimal('0.8'), never float 0.8"


# ---------------------------------------------------------------------------
# One-to-one mapping enforcement (LLM-09, D-A3-02) — the EXTENDED check_one_to_one.
# A confident model can NEVER let a name silently collapse onto another employee.
# ---------------------------------------------------------------------------


def test_one_to_one_collisions():
    """All three collision shapes gate to clarify as DISTINCT gate_reasons:
    (a) two distinct names → same employee, (b) a duplicated submitted name,
    (c) a name → no roster employee."""
    llm = _StubLLM(model_action="process")

    # (a) two distinct names → same matched_employee_id (all high-confidence).
    shared = uuid.uuid4()
    matches_a = [
        _match("David Reyes", "1.0", mtype="exact", emp_id=shared),
        _match("D. Reyes", "1.0", mtype="alias", emp_id=shared),
    ]
    out_a = check_one_to_one(matches_a, _extracted("David Reyes", "D. Reyes"))
    assert any("David Reyes" in r and "D. Reyes" in r for r in out_a), (
        "two distinct names → one employee must produce a collision gate_reason"
    )
    dec_a = decide(_extracted("David Reyes", "D. Reyes"), matches_a, [], llm=llm)
    assert dec_a.final_action == "request_clarification"

    # (b) a duplicated submitted_name (same name twice).
    eid = uuid.uuid4()
    matches_b = [
        _match("Maria Chen", "1.0", mtype="exact", emp_id=eid),
        _match("Maria Chen", "1.0", mtype="exact", emp_id=eid),
    ]
    out_b = check_one_to_one(matches_b, _extracted("Maria Chen", "Maria Chen"))
    assert any("Maria Chen" in r for r in out_b), (
        "a duplicated submitted name must produce a collision gate_reason"
    )
    dec_b = decide(_extracted("Maria Chen", "Maria Chen"), matches_b, [], llm=llm)
    assert dec_b.final_action == "request_clarification"

    # (c) a name → no roster employee (matched_employee_id is None).
    matches_c = [
        NameMatchResult(
            submitted_name="Ghosty McGhost",
            matched_employee_id=None,
            match_type="unknown",
            confidence=Decimal("0.0"),
            reason="no match",
        )
    ]
    out_c = check_one_to_one(matches_c, _extracted("Ghosty McGhost"))
    assert any("Ghosty McGhost" in r for r in out_c), (
        "a name resolving to no employee must produce a collision gate_reason"
    )


def test_high_confidence_collision_still_gates():
    """A collision between TWO 1.0-confidence names still gates (the mapping gate is
    independent of confidence, G6) — confidence alone would have let it process."""
    llm = _StubLLM(model_action="process")
    shared = uuid.uuid4()
    matches = [
        _match("David Reyes", "1.0", mtype="exact", emp_id=shared),
        _match("Dave Reyes", "1.0", mtype="llm_nickname", emp_id=shared),
    ]
    decision = decide(_extracted("David Reyes", "Dave Reyes"), matches, [], llm=llm)
    assert decision.final_action == "request_clarification", (
        "a high-confidence collision must still gate (mapping gate, not confidence)"
    )
    assert decision.gate_triggered is True


def test_check_one_to_one_stub_shape_still_passes_after_extend():
    """The Plan-02 signature is UNCHANGED: a clean, collision-free set returns []
    so the extended function never gates a legitimately clean run."""
    clean = [
        _match("Maria Chen", "1.0", mtype="exact", emp_id=uuid.uuid4()),
        _match("James Okafor", "1.0", mtype="exact", emp_id=uuid.uuid4()),
    ]
    out = check_one_to_one(clean, _extracted("Maria Chen", "James Okafor"))
    assert out == [], "a clean one-to-one mapping must produce NO collision reasons"
