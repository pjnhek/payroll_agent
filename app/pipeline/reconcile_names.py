"""Stage 2 — name reconciliation, Layer 1 (deterministic) + Layer 2 (LLM).

A PURE function: typed values in, list[NameMatchResult] out, NO DB, NO connection
(FIX A purity = no-DB, not no-run_id). The eval (Phase 4) calls this identical
function with fixture inputs.

Layer 1 (deterministic, NO model — LLM-04): exact / casefold / whitespace-normalize
/ known_aliases membership against the Roster. A clean hit yields
NameMatchResult(match_type="exact"|"alias", confidence=Decimal("1.0")) and NEVER
reaches a model — the model can never re-decide a layer-1 hit (LLM-05, D-A3-01).

Layer 2 (LLM over RESIDUAL names — LLM-05): only names that failed layer-1 are
sent to the model, with the FULL roster in-context (RESEARCH §Pattern 3 — so
genuine ambiguity drives low confidence by construction). The structured call uses
the `NameReconciliationResponse` wrapper (review FIX 6: `call_structured` validates
via `model_validate_json`, which a bare `list[NameMatchResult]` cannot satisfy),
then unwraps `.matches`. The model classifies each residual as
`llm_typo`/`llm_nickname`/`unknown` with a per-name confidence (the 0.8 gate in
decide.py keys off it, D-A2-03 — temperature 0 is mandatory, enforced by the
client wrapper for the decision tier).

If no `llm` is wired (eval/clean-fixture path), a residual name degrades to
`unknown` (matched_employee_id=None, confidence=0.0) so decide()'s gate still
blocks it — no model call, no crash.
"""
from __future__ import annotations

from decimal import Decimal

from app.llm import client as llm_client
from app.llm.prompts import reconcile as reconcile_prompt
from app.models.reconcile import NameReconciliationResponse
from app.models.roster import NameMatchResult, Roster


def _norm(name: str) -> str:
    """Whitespace-normalize + casefold for deterministic comparison."""
    return " ".join(name.split()).casefold()


def deterministic_match(name: str, roster: Roster) -> NameMatchResult | None:
    """Resolve a clean name with NO model call, or None if residual (Layer 2)."""
    norm = _norm(name)
    for emp in roster.employees:
        if _norm(emp.full_name) == norm:
            return NameMatchResult(
                submitted_name=name,
                matched_employee_id=emp.id,
                match_type="exact",
                confidence=Decimal("1.0"),
                reason="exact match",
            )
        if any(_norm(alias) == norm for alias in emp.known_aliases):
            return NameMatchResult(
                submitted_name=name,
                matched_employee_id=emp.id,
                match_type="alias",
                confidence=Decimal("1.0"),
                reason="known alias",
            )
    return None


def _unknown(name: str) -> NameMatchResult:
    """The degraded result for a residual name when no model resolves it."""
    return NameMatchResult(
        submitted_name=name,
        matched_employee_id=None,
        match_type="unknown",
        confidence=Decimal("0.0"),
        reason="no deterministic or model match",
    )


def _llm_reconcile(
    residual_names: list[str],
    roster: Roster,
    *,
    llm,
) -> dict[str, NameMatchResult]:
    """Layer-2: classify residual names via the model, keyed by submitted_name.

    Uses the NameReconciliationResponse wrapper so call_structured can
    model_validate_json the untrusted output, then unwraps `.matches`. A residual
    name the model omits degrades to `unknown` so the gate still blocks it.
    """
    messages = reconcile_prompt.build_messages(residual_names, roster)
    response: NameReconciliationResponse = llm.call_structured(
        "decision", messages, NameReconciliationResponse
    )
    by_name: dict[str, NameMatchResult] = {m.submitted_name: m for m in response.matches}
    return {name: by_name.get(name, _unknown(name)) for name in residual_names}


def reconcile_names(
    submitted_names: list[str],
    roster: Roster,
    *,
    llm=llm_client,
) -> list[NameMatchResult]:
    """Reconcile each submitted name to a roster employee (Layer 1 + Layer 2).

    Returns one NameMatchResult per submitted name, in submitted order. Layer-1
    hits resolve with confidence 1.0 and NO model call; only residual names reach
    the layer-2 model (LLM-05). When `llm` is None, residual names degrade to
    `unknown` (no model call) so the eval/clean path runs offline.
    """
    # First pass: resolve every name deterministically; collect the residuals.
    layer1: dict[int, NameMatchResult] = {}
    residual_names: list[str] = []
    for i, name in enumerate(submitted_names):
        hit = deterministic_match(name, roster)
        if hit is not None:
            layer1[i] = hit
        else:
            residual_names.append(name)

    # Layer 2: only the residuals reach the model (a layer-1 hit is never re-decided).
    layer2: dict[str, NameMatchResult] = {}
    if residual_names:
        if llm is not None:
            layer2 = _llm_reconcile(residual_names, roster, llm=llm)
        else:
            layer2 = {name: _unknown(name) for name in residual_names}

    # Merge back into one result per submitted name, preserving submitted order.
    results: list[NameMatchResult] = []
    for i, name in enumerate(submitted_names):
        if i in layer1:
            results.append(layer1[i])
        else:
            results.append(layer2.get(name, _unknown(name)))
    return results
