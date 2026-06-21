"""Name-reconciliation tests (LLM-04 layer-1 + LLM-05 layer-2). Pure, DB-free.

Layer 1 resolves exact / casefold / whitespace / known-alias names with NO model
call (confidence 1.0). Residual names go to the layer-2 LLM (Plan 03), which
classifies each as llm_typo/llm_nickname/unknown + per-name confidence via the
NameReconciliationResponse wrapper (review FIX 6); the stage unwraps `.matches`
and merges with layer-1. A clean layer-1 hit is NEVER re-decided by the model.
"""
from __future__ import annotations

import json
from decimal import Decimal

from app.models.roster import NameMatchResult
from app.pipeline.reconcile_names import reconcile_names


class _SpyLLM:
    """Records whether the model was called; reconcile must NOT call it for clean
    names in this plan (Layer 1 is pure code)."""

    def __init__(self):
        self.calls = 0

    def call_structured(self, *a, **k):  # pragma: no cover - must not be hit
        self.calls += 1
        raise AssertionError("Layer 1 must not call the model for clean names")


def test_layer1_deterministic(roster_from_seed):
    spy = _SpyLLM()
    submitted = [
        "Maria Chen",        # exact
        "maria  chen",       # casefold + whitespace-normalize
        "M. Chen",           # known alias
        "James Okafor",      # exact
    ]
    results = reconcile_names(submitted, roster_from_seed, llm=spy)

    assert len(results) == 4
    by_name = {r.submitted_name: r for r in results}

    assert by_name["Maria Chen"].match_type == "exact"
    assert by_name["Maria Chen"].confidence == Decimal("1.0")
    assert by_name["maria  chen"].match_type == "exact"  # normalized exact match
    assert by_name["M. Chen"].match_type == "alias"
    assert by_name["M. Chen"].confidence == Decimal("1.0")
    assert by_name["James Okafor"].match_type == "exact"

    # No model call for clean names (LLM-04 row).
    assert spy.calls == 0, "deterministic layer must not invoke the model"


def test_residual_name_is_unknown(roster_from_seed):
    """With NO llm wired, a residual name still degrades to `unknown` (gated)."""
    results = reconcile_names(["Totally Unseen Person"], roster_from_seed)
    assert len(results) == 1
    assert results[0].match_type == "unknown"
    assert results[0].matched_employee_id is None
    assert results[0].confidence < Decimal("0.8")


# ---------------------------------------------------------------------------
# Layer-2 LLM reconciliation (LLM-05) — residual names → the model via the
# NameReconciliationResponse wrapper (review FIX 6); merged with layer-1.
# ---------------------------------------------------------------------------


class _RecordingLLM:
    """A call_structured stand-in that records its (tier, messages, response_model)
    and returns a scripted NameReconciliationResponse for the residual names."""

    def __init__(self, scripted_matches):
        self._scripted = scripted_matches
        self.calls: list[tuple] = []

    def call_structured(self, tier, messages, response_model):
        self.calls.append((tier, messages, response_model))
        # Validate through the REAL wrapper exactly as the client does, so the test
        # proves the wrapper round-trips via model_validate_json.
        payload = json.dumps(
            {"matches": [m.model_dump(mode="json") for m in self._scripted]}
        )
        return response_model.model_validate_json(payload)


def _typo_match(name, emp_id):
    return NameMatchResult(
        submitted_name=name,
        matched_employee_id=emp_id,
        match_type="llm_typo",
        confidence=Decimal("0.6"),
        reason="likely a typo",
    )


def test_reconcile_wrapper_model(roster_from_seed):
    """The layer-2 call uses the NameReconciliationResponse wrapper (a BaseModel
    with model_validate_json), and the stage unwraps `.matches` into the merged
    list — a bare list[...] could not be model_validate_json'd (review FIX 6)."""
    from app.models.reconcile import NameReconciliationResponse

    target = roster_from_seed.employees[0]
    residual_variant = target.full_name[:-1] + "x"  # a one-letter near-miss
    llm = _RecordingLLM([_typo_match(residual_variant, target.id)])

    results = reconcile_names([residual_variant], roster_from_seed, llm=llm)

    # The response_model passed to the model is the wrapper, NEVER a bare list.
    assert llm.calls, "layer-2 must call the model for a residual name"
    _, _, response_model = llm.calls[0]
    assert response_model is NameReconciliationResponse
    assert issubclass(response_model, __import__("pydantic").BaseModel)

    # The stage unwrapped `.matches` into one merged NameMatchResult.
    assert len(results) == 1
    assert results[0].submitted_name == residual_variant
    assert results[0].match_type == "llm_typo"
    assert results[0].matched_employee_id == target.id
    assert results[0].confidence == Decimal("0.6")


def test_residual_only_to_llm(roster_from_seed):
    """Only residual names reach the model; a clean layer-1 hit is NEVER re-decided
    (LLM-05, D-A3-01). The single residual name is the ONLY one in the prompt."""
    target = roster_from_seed.employees[0]
    residual_variant = target.full_name[:-1] + "x"
    llm = _RecordingLLM([_typo_match(residual_variant, target.id)])

    submitted = [target.full_name, residual_variant]  # one clean + one residual
    results = reconcile_names(submitted, roster_from_seed, llm=llm)

    # Exactly ONE model call, carrying ONLY the residual name (not the clean one).
    assert len(llm.calls) == 1
    _, messages, _ = llm.calls[0]
    convo = " ".join(m["content"] for m in messages)
    assert residual_variant in convo
    assert f"  - {target.full_name}\n" not in convo  # clean name not asked about

    by_name = {r.submitted_name: r for r in results}
    assert by_name[target.full_name].match_type == "exact"  # layer-1, no model
    assert by_name[target.full_name].confidence == Decimal("1.0")
    assert by_name[residual_variant].match_type == "llm_typo"  # layer-2


def test_reconcile_merges_one_per_submitted_name(roster_from_seed):
    """Layer-2 results merge with layer-1 into one list[NameMatchResult], exactly
    one per submitted name, preserving submitted order."""
    target = roster_from_seed.employees[0]
    residual_variant = target.full_name[:-1] + "x"
    llm = _RecordingLLM([_typo_match(residual_variant, target.id)])

    submitted = [target.full_name, residual_variant, target.full_name]
    results = reconcile_names(submitted, roster_from_seed, llm=llm)

    assert [r.submitted_name for r in results] == submitted  # one per name, in order


def test_reconcile_is_db_free():
    """FIX A purity = no-DB: reconcile_names imports no DB module and takes no
    connection (statically assertable)."""
    import inspect
    import pathlib

    import app.pipeline.reconcile_names as recon_mod

    src = pathlib.Path(recon_mod.__file__).read_text()
    assert "supabase" not in src
    assert "get_connection" not in src
    assert "from app.db" not in src and "import app.db" not in src
    # No `conn` parameter on the public stage.
    params = inspect.signature(reconcile_names).parameters
    assert "conn" not in params
