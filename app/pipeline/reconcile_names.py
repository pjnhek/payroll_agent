"""Stage 2 — name reconciliation: PURE deterministic resolver (D-21-01).

A PURE function: typed values in, list[NameMatchResult] out, NO DB, NO connection,
and (now) NO model — there is no second layer. The eval (Phase 4) calls this
identical function with fixture inputs (D-21-09).

Resolution is pure code over roster facts (D-21-01). Per submitted name:

  - exact normalized match (casefold + whitespace-normalize) to EXACTLY ONE
    employee, with no other employee sharing the normalized name →
    ``source="exact"``, ``resolved=True``.
  - a stored ``known_alias`` match for EXACTLY ONE employee, no collision →
    ``source="alias"``, ``resolved=True``. This is the READ side of the
    learning loop (D-21-07); the WRITE side (persisting a newly-confirmed alias
    at the operator-approval gate) lands in Phase 5.
  - anything else — no match, a typo, a first-time nickname, a garbled name, or a
    name that maps to 2+ employees — degrades to ``source="none"``,
    ``resolved=False``, ``matched_employee_id=None``. The resolver NEVER guesses
    on a money-moving decision.

Collision safety (D-21-02): if a normalized name (or alias) matches MORE THAN ONE
employee, the resolver refuses to pick either — it returns unresolved so the name
can't be silently routed to the wrong person. The run-level collision check in
decide() is the authority for the "shared by 2+ roster employees" / cross-name
cases; here the resolver simply declines to uniquely resolve.
"""
from __future__ import annotations

from app.models.roster import NameMatchResult, Roster


def _norm(name: str) -> str:
    """Whitespace-normalize + casefold for deterministic comparison."""
    return " ".join(name.split()).casefold()


def deterministic_match(name: str, roster: Roster) -> NameMatchResult | None:
    """Resolve a name to EXACTLY ONE roster employee, or None if it can't.

    Scans the whole roster. A unique exact normalized full_name match →
    source="exact"; otherwise a unique stored known_alias match → source="alias".
    If the name (or alias) matches 2+ employees, it is NOT uniquely resolvable, so
    this returns None (it falls through to the unresolved result — D-21-02). No
    match at all also returns None.
    """
    norm = _norm(name)

    # Exact normalized full_name match — require uniqueness.
    exact_ids = [emp.id for emp in roster.employees if _norm(emp.full_name) == norm]
    if len(exact_ids) == 1:
        return NameMatchResult(
            submitted_name=name,
            matched_employee_id=exact_ids[0],
            source="exact",
            resolved=True,
            reason="exact match",
        )
    if len(exact_ids) > 1:
        # Shared by 2+ employees → cannot uniquely resolve (D-21-02).
        return None

    # Stored known_alias match — require uniqueness.
    alias_ids = [
        emp.id
        for emp in roster.employees
        if any(_norm(alias) == norm for alias in emp.known_aliases)
    ]
    if len(alias_ids) == 1:
        return NameMatchResult(
            submitted_name=name,
            matched_employee_id=alias_ids[0],
            source="alias",
            resolved=True,
            reason="known alias",
        )

    return None


def _unresolved(name: str) -> NameMatchResult:
    """The degraded result for a name with no UNIQUE exact/alias match."""
    return NameMatchResult(
        submitted_name=name,
        matched_employee_id=None,
        source="none",
        resolved=False,
        reason="no deterministic or stored-alias match",
    )


def reconcile_names(
    submitted_names: list[str],
    roster: Roster,
) -> list[NameMatchResult]:
    """Resolve each submitted name against the roster (pure deterministic code).

    Returns one NameMatchResult per submitted name, in submitted order. A name that
    uniquely resolves via exact/alias is resolved=True; everything else degrades to
    source="none", resolved=False — there is no model layer and no fuzzy guessing
    (D-21-01). decide() owns the run-level decision over these facts.
    """
    return [
        deterministic_match(name, roster) or _unresolved(name)
        for name in submitted_names
    ]
