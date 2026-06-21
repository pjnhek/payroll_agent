"""Stage 2 — name reconciliation, Layer 1 only in this plan (LLM-04, D-A3-01).

A PURE function: typed values in, list[NameMatchResult] out, NO DB, NO connection.

Layer 1 (deterministic, NO model — LLM-04): exact / casefold / whitespace-normalize
/ known_aliases membership against the Roster. A clean hit yields
NameMatchResult(match_type="exact"|"alias", confidence=Decimal("1.0")) and NEVER
reaches a model. The clean happy-path fixture is all-deterministic so no model is
called for it.

Layer 2 (LLM over residual names) lands in Plan 03. In THIS plan a residual name
(no deterministic hit) yields an `unknown` result (matched_employee_id=None,
confidence=Decimal("0.0")) so decide()'s gate already blocks it — the gate-block
hero fixture's LLM path is wired in Plan 03 by extending this function.
"""
from __future__ import annotations

from decimal import Decimal

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


def reconcile_names(
    submitted_names: list[str],
    roster: Roster,
    *,
    llm=None,
) -> list[NameMatchResult]:
    """Reconcile each submitted name to a roster employee (Layer 1 in this plan).

    Returns one NameMatchResult per submitted name. Layer-1 hits resolve with
    confidence 1.0 and no model call; residual names become `unknown` (the Layer-2
    LLM classification is Plan 03). `llm` is accepted for the Plan 03 extension but
    is unused here (clean fixture is all-deterministic).
    """
    results: list[NameMatchResult] = []
    for name in submitted_names:
        hit = deterministic_match(name, roster)
        if hit is not None:
            results.append(hit)
        else:
            results.append(
                NameMatchResult(
                    submitted_name=name,
                    matched_employee_id=None,
                    match_type="unknown",
                    confidence=Decimal("0.0"),
                    reason="no deterministic match (Layer-2 LLM lands in Plan 03)",
                )
            )
    return results
