"""Live hero-fixture exit gate (D-A4-01a) — the DISTINCT Phase 2 exit criterion.

THIS TEST DOES NOT RUN IN CI OR ON A NORMAL `pytest` INVOCATION.

It is a two-factor env-gated live test mirroring the Phase 1 live-DB guard
(tests/test_seed_roundtrip.py §2) verbatim, swapping the env-var pair:

    _HAS_LLM_KEYS = bool(EXTRACTION_API_KEY and DECISION_API_KEY)
    _LIVE_LLM     = os.environ.get("ALLOW_LIVE_LLM") == "1"

Both must be set or the test SKIPS individually. It is also marked
`@pytest.mark.live_llm`, so the default CI invocation
`pytest -m "not integration and not live_llm"` never collects it — green and free.

What it proves (the property no mock can assert — D-A5-01: the mocked suite passing
is NECESSARY but NOT SUFFICIENT): the REAL configured DeepSeek/Kimi models, run on
the David Reyez hero fixture, genuinely return `model_action == "process"` (the
model is WILLING to run payroll) AND a per-name reconciliation confidence
`< Decimal("0.8")`, so the CODE GATE fires and `final_action == "request_clarification"`.
That is "the model was willing; the code said no" on LIVE output, not a recording.

Tuning loop (human judgment, NOT an automated pass/fail — see Task 3 checkpoint):
if the live model SELF-clarifies (proposes request_clarification on its own → the
gate never fires) or returns confidence ≥ 0.8 (a mismatch would process), tune the
submitted-name variant ("David Reyez") and/or the reconcile prompt (AI-SPEC §7) and
repeat until the live run genuinely produces model-says-process AND gate-blocks.

Live-vs-mock marker (FIX 12): a structured LOG field `source="live"` is emitted at
the decide step, derived from `Settings.allow_live_llm` — NOT a key inside the
`extra="forbid"` Decision object (contracts.py:124, which would raise a
ValidationError) and NOT a schema column. It records DECISION PROVENANCE only.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import uuid
from decimal import Decimal

import pytest

# ---------------------------------------------------------------------------
# Two-factor guard (EXACT analog tests/test_seed_roundtrip.py:26-27, 271-277).
# Swap the env-var pair: live-LLM keys + ALLOW_LIVE_LLM=1.
# ---------------------------------------------------------------------------
_HAS_LLM_KEYS = bool(
    os.environ.get("EXTRACTION_API_KEY") and os.environ.get("DECISION_API_KEY")
)
_LIVE_LLM = os.environ.get("ALLOW_LIVE_LLM") == "1"

_SKIP_LIVE_LLM = pytest.mark.skipif(
    not (_HAS_LLM_KEYS and _LIVE_LLM),
    reason=(
        "Live-LLM hero test requires EXTRACTION_API_KEY, DECISION_API_KEY and "
        "ALLOW_LIVE_LLM=1 (two-factor guard, mirrors ALLOW_DB_RESET). It hits the "
        "REAL DeepSeek/Kimi APIs and is a manual Phase 2 exit gate, never CI."
    ),
)

_GATE_BLOCK_FIXTURE = (
    pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "gate_block_hero.json"
)

# The locked confidence threshold (CLAUDE.md / decide.py:_THRESHOLD).
_THRESHOLD = Decimal("0.8")

_logger = logging.getLogger("payroll_agent.live_llm")


@_SKIP_LIVE_LLM
@pytest.mark.live_llm
def test_hero_fixture_live() -> None:
    """The live exit gate: real models say PROCESS at sub-0.8 → the code gate BLOCKS.

    Runs the David Reyez hero fixture through the REAL configured DeepSeek/Kimi
    models via the IDENTICAL pure judgment stages the eval (Phase 4) reuses — DB-free
    (the roster is built from seed(dry_run=True); the run_id is a code-owned literal).
    No orchestrator, no DB, no email send.

    Asserts (D-A4-01a):
      - model_action == "process"  (the model is WILLING to run payroll), AND
      - some per-name reconciliation confidence < 0.8, AND
      - final_action == "request_clarification"  (the code gate OVERRODE the model).
    """
    from app.config import get_settings
    from app.db.seed import seed
    from app.models.contracts import InboundEmail
    from app.models.roster import Roster
    from app.pipeline.decide import decide
    from app.pipeline.extract import extract
    from app.pipeline.reconcile_names import reconcile_names
    from app.pipeline.validate import validate

    # --- build the pure stage inputs from committed fixtures (no DB) ---
    email = InboundEmail.model_validate(json.loads(_GATE_BLOCK_FIXTURE.read_text()))
    seeded = seed(dry_run=True)
    # Metro Deli Group business — the hero David Reyes lives here (seed emp 3).
    business_id = seeded.businesses[1]["id"]  # b0000002 (Metro Deli)
    roster = Roster(
        business_id=business_id,
        employees=[e for e in seeded.employees if str(e.business_id) == str(business_id)],
    )
    run_id = uuid.uuid4()  # code-owned run_id (FIX A) — the model never supplies it

    # --- the REAL stages hit DeepSeek (extraction) + Kimi (decision/reconcile) ---
    extracted = extract(email, roster, run_id=run_id)
    submitted_names = [e.submitted_name for e in extracted.employees]
    matches = reconcile_names(submitted_names, roster)
    issues = validate(extracted, roster, matches)
    decision = decide(extracted, matches, issues)

    # --- live-vs-mock provenance marker (FIX 12): a STRUCTURED LOG field, derived
    #     from Settings.allow_live_llm; NOT a key in the extra="forbid" Decision and
    #     NOT a schema column. It records that this decision came from a live call. ---
    source = "live" if get_settings().allow_live_llm else "mock"
    _logger.info(
        "decision", extra={"run_id": str(run_id), "source": source,
                           "model_action": decision.model_action,
                           "final_action": decision.final_action}
    )

    # --- the exit-gate assertions (D-A4-01a) ---
    assert decision.model_action == "process", (
        "the live model must be WILLING (say process) — if it self-clarifies, TUNE "
        "the submitted-name variant / reconcile prompt and re-run (Task 3 checkpoint)"
    )
    sub_threshold = [m for m in matches if m.confidence < _THRESHOLD]
    assert sub_threshold, (
        "at least one per-name confidence must be < 0.8 so the gate fires — if the "
        "live model returns ≥0.8, TUNE the fixture/prompt and re-run (Task 3 checkpoint)"
    )
    assert decision.final_action == "request_clarification", (
        "the code gate must OVERRIDE the willing model on the live sub-0.8 match — "
        "'the model was willing; the code said no' on REAL output (D-A4-01a)"
    )


def test_live_marker_is_not_a_decision_field() -> None:
    """FIX 12 guard (ALWAYS runs): the live-vs-mock 'source' marker must NOT be a key
    inside the extra="forbid" Decision object — adding it would raise a ValidationError.

    This pins the contract decision: provenance is a structured LOG field, not a
    Decision column, and is verifiable with NO live call.
    """
    from app.models.contracts import Decision

    base = {
        "model_action": "process",
        "gate_triggered": True,
        "gate_reasons": ["x: confidence 0.6 < 0.8"],
        "final_action": "request_clarification",
        "unresolved_names": ["x"],
        "missing_fields": [],
        "confidence": "0.6",
        "reasons": ["advisory"],
    }
    # The honest Decision constructs fine.
    Decision.model_validate(base)
    # Smuggling a 'source' provenance key into the Decision must FAIL (extra="forbid").
    with pytest.raises(Exception):
        Decision.model_validate({**base, "source": "live"})
