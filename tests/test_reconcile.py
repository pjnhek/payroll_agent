"""Name-reconciliation Layer-1 tests (LLM-04). Pure, deterministic, DB-free.

Layer 1 resolves exact / casefold / whitespace / known-alias names with NO model
call (confidence 1.0). Residual names become `unknown` (Layer-2 LLM is Plan 03).
"""
from __future__ import annotations

from decimal import Decimal

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
    results = reconcile_names(["Totally Unseen Person"], roster_from_seed)
    assert len(results) == 1
    assert results[0].match_type == "unknown"
    assert results[0].matched_employee_id is None
    assert results[0].confidence < Decimal("0.8")
