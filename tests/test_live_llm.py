"""Live hero-fixture exit gate (D-A4-01a, D-21 reframe) — the DISTINCT live proof.

THIS TEST DOES NOT RUN IN CI OR ON A NORMAL `pytest` INVOCATION.

It is a two-factor env-gated live test mirroring the Phase 1 live-DB guard
(tests/test_seed_roundtrip.py §2) verbatim, swapping the env-var pair:

    _HAS_LLM_KEYS = bool(EXTRACTION_API_KEY and DRAFT_API_KEY)
    _LIVE_LLM     = os.environ.get("ALLOW_LIVE_LLM") == "1"

Both must be set or the test SKIPS individually. It is also marked
`@pytest.mark.live_llm`, so the default CI invocation
`pytest -m "not integration and not live_llm"` never collects it — green and free.

What it proves (the property no mock can assert — D-A5-01: the mocked suite passing
is NECESSARY but NOT SUFFICIENT). The Phase 2.1 thesis made the DECISION pure code
(no model judgment, no score — D-21-01), so the live proof is no longer a score
gate. The two LLM calls that remain — EXTRACTION (DeepSeek) and the clarification
SUGGESTION (Kimi, copy only, D-21-05) — are where live model quality matters, so
the live gate proves:

  1. LIVE EXTRACTION works: the real DeepSeek model reads the hero email and
     returns the submitted name "David Reyez" with its 38 hours.
  2. DETERMINISTIC DECIDE gates: run through the IDENTICAL pure stages the eval
     reuses — reconcile resolves "David Reyez" to source="none" (no unique match)
     and decide computes final_action == "request_clarification" purely from the
     resolution facts. No model, no score.
  3. LIVE SUGGESTION quality (advisory copy only): the real Kimi suggestion call
     maps the unresolved "David Reyez" back to the roster "David Reyes" so the
     clarification email can be specific ("did you mean David Reyes?"). This NEVER
     feeds decide / final_action — it is email copy (D-21-05).

That is "the system never guesses; it clarifies with a specific suggestion" on LIVE
output, not a recording.

Tuning loop (human judgment, NOT an automated pass/fail — see Task 3 checkpoint):
if the live extraction misreads the name, or the live suggestion fails to map
"David Reyez" → "David Reyes", tune the submitted-name variant and/or the
extraction/suggestion prompts (AI-SPEC) and repeat until the live run genuinely
produces extract-correct + deterministic-clarify + a specific suggestion.

Live-vs-mock marker (FIX 12): a structured LOG field `source="live"` is emitted at
the decide step, derived from `Settings.allow_live_llm` — NOT a key inside the
`extra="forbid"` Decision object (contracts.py, which would raise a ValidationError)
and NOT a schema column. It records DECISION PROVENANCE only.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import uuid

import pytest

# ---------------------------------------------------------------------------
# Two-factor guard (EXACT analog tests/test_seed_roundtrip.py:26-27).
# Swap the env-var pair: live-LLM keys + ALLOW_LIVE_LLM=1. The keys are the TWO
# surviving tiers (D-21-05): extraction (DeepSeek) + draft (Kimi, suggestion copy).
# ---------------------------------------------------------------------------
_HAS_LLM_KEYS = bool(
    os.environ.get("EXTRACTION_API_KEY") and os.environ.get("DRAFT_API_KEY")
)
_LIVE_LLM = os.environ.get("ALLOW_LIVE_LLM") == "1"

_SKIP_LIVE_LLM = pytest.mark.skipif(
    not (_HAS_LLM_KEYS and _LIVE_LLM),
    reason=(
        "Live-LLM hero test requires EXTRACTION_API_KEY, DRAFT_API_KEY and "
        "ALLOW_LIVE_LLM=1 (two-factor guard, mirrors ALLOW_DB_RESET). It hits the "
        "REAL DeepSeek/Kimi APIs and is a manual Phase 2.1 exit gate, never CI."
    ),
)

_GATE_BLOCK_FIXTURE = (
    pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "gate_block_hero.json"
)

_logger = logging.getLogger("payroll_agent.live_llm")


@_SKIP_LIVE_LLM
@pytest.mark.live_llm
def test_hero_fixture_live() -> None:
    """The live exit gate: real extraction + deterministic clarify + a real suggestion.

    Runs the David Reyez hero fixture through the REAL configured DeepSeek/Kimi
    models via the IDENTICAL pure judgment stages the eval (Phase 4) reuses — DB-free
    (the roster is built from seed(dry_run=True); the run_id is a code-owned literal).
    No orchestrator, no DB, no email send.

    Asserts (D-A4-01a, D-21 reframe):
      - LIVE EXTRACTION returns "David Reyez" (the real model read the email), AND
      - DETERMINISTIC reconcile resolves it to source="none" / resolved=False, AND
      - DETERMINISTIC decide computes final_action == "request_clarification"
        purely from the resolution facts (no model, no score), AND
      - the LIVE SUGGESTION call (copy only) maps "David Reyez" → "David Reyes" so
        the clarification can name the specific intended employee.
    """
    from app.config import get_settings
    from app.db.seed import seed
    from app.models.contracts import InboundEmail
    from app.models.roster import Roster
    from app.pipeline.decide import decide
    from app.pipeline.extract import extract
    from app.pipeline.reconcile_names import reconcile_names
    from app.pipeline.suggest import suggest_employees
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

    # --- LIVE extraction (DeepSeek) → PURE reconcile/decide → LIVE suggestion (Kimi) ---
    extracted = extract(email, roster, run_id=run_id)
    submitted_names = [e.submitted_name for e in extracted.employees]
    matches = reconcile_names(submitted_names, roster)  # pure, no model
    issues = validate(extracted, roster, matches)
    decision = decide(extracted, matches, issues)  # pure, no model, no score

    # --- live-vs-mock provenance marker (FIX 12): a STRUCTURED LOG field, derived
    #     from Settings.allow_live_llm; NOT a key in the extra="forbid" Decision and
    #     NOT a schema column. It records that this decision came from a live call. ---
    source = "live" if get_settings().allow_live_llm else "mock"
    _logger.info(
        "decision", extra={"run_id": str(run_id), "source": source,
                           "final_action": decision.final_action}
    )

    # --- exit-gate assertions (D-A4-01a, D-21 reframe) ---
    # 1. LIVE EXTRACTION read the submitted name.
    assert "David Reyez" in submitted_names, (
        "live extraction must return the submitted name 'David Reyez' — if the model "
        "misreads it, TUNE the extraction prompt and re-run (Task 3 checkpoint)"
    )

    # 2 & 3. DETERMINISTIC reconcile + decide: the unknown shorthand is unresolved
    # and the code gate clarifies — purely from the resolution facts.
    reyez = next(m for m in matches if m.submitted_name == "David Reyez")
    assert reyez.resolved is False and reyez.source == "none", (
        "the deterministic resolver must leave the unknown shorthand unresolved "
        "(source='none') — it never guesses on a money-moving decision (D-21-01)"
    )
    assert decision.final_action == "request_clarification", (
        "decide must gate the run to clarification from the resolution facts — "
        "deterministic, no model action, no score (D-21-01)"
    )

    # 4. LIVE SUGGESTION quality (advisory copy only, never feeds decide).
    suggestions = suggest_employees(decision.unresolved_names, roster)
    assert suggestions.get("David Reyez") == "David Reyes", (
        "the live suggestion call must map 'David Reyez' → 'David Reyes' so the "
        "clarification names the specific employee — if it fails, TUNE the "
        "suggestion prompt and re-run (Task 3 checkpoint). This is COPY ONLY and "
        "never feeds decide (D-21-05)."
    )


def test_live_marker_is_not_a_decision_field() -> None:
    """FIX 12 guard (ALWAYS runs): the live-vs-mock 'source' marker must NOT be a key
    inside the extra="forbid" Decision object — adding it would raise a ValidationError.

    This pins the contract decision: provenance is a structured LOG field, not a
    Decision column, and is verifiable with NO live call. The Decision shape is the
    deterministic one (D-21-04): final_action + gate detail + per-name resolutions —
    no model action, no score.
    """
    from app.models.contracts import Decision

    base = {
        "final_action": "request_clarification",
        "gate_reasons": ["David Reyez: unresolved (no roster match)"],
        "unresolved_names": ["David Reyez"],
        "missing_fields": [],
        "resolutions": [
            {
                "submitted_name": "David Reyez",
                "matched_employee_id": None,
                "source": "none",
                "resolved": False,
                "reason": "no deterministic or stored-alias match",
            }
        ],
    }
    # The honest deterministic Decision constructs fine.
    Decision.model_validate(base)
    # Smuggling a 'source' provenance key into the Decision must FAIL (extra="forbid").
    with pytest.raises(Exception):
        Decision.model_validate({**base, "source": "live"})
