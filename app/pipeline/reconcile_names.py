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

from app.models.roster import Employee, NameMatchResult, Roster


def _norm(name: str) -> str:
    """Whitespace-normalize + casefold for deterministic comparison."""
    return " ".join(name.split()).casefold()


def deterministic_match(name: str, roster: Roster) -> NameMatchResult | None:
    """Resolve a name to EXACTLY ONE roster employee, or None if it can't.

    Uniqueness is enforced ACROSS BOTH tiers, not within each separately: the name
    is matched against every employee's normalized full_name AND every stored
    known_alias, and the set of DISTINCT candidate employees is what must be unique.
    So a name that is one employee's full_name AND a *different* employee's alias is
    ambiguous (2 distinct candidates) → None, even though it is a unique exact hit on
    its own (review fix: cross-tier exact-vs-alias collision, D-21-02). A name shared
    by 2+ employees in either tier is likewise ambiguous → None. No match → None.
    When the single resolved employee was reached by full_name the source is "exact";
    otherwise (alias-only) it is "alias".
    """
    norm = _norm(name)

    exact_ids = [emp.id for emp in roster.employees if _norm(emp.full_name) == norm]
    alias_ids = [
        emp.id
        for emp in roster.employees
        if any(_norm(alias) == norm for alias in emp.known_aliases)
    ]

    # Distinct candidate employees across BOTH tiers — uniqueness is global.
    candidate_ids = set(exact_ids) | set(alias_ids)
    if len(candidate_ids) != 1:
        # Zero candidates (no match) or 2+ distinct employees (ambiguous collision,
        # D-21-02) → not uniquely resolvable; falls through to the unresolved result.
        return None

    matched_id = next(iter(candidate_ids))
    if matched_id in exact_ids:
        return NameMatchResult(
            submitted_name=name,
            matched_employee_id=matched_id,
            source="exact",
            resolved=True,
            reason="exact match",
        )
    return NameMatchResult(
        submitted_name=name,
        matched_employee_id=matched_id,
        source="alias",
        resolved=True,
        reason="known alias",
    )


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


def _safe_to_learn_alias(
    token: str,
    target_employee: Employee,
    roster: Roster,
) -> bool:
    """Return True only if token uniquely resolves to target_employee on the full roster
    AFTER the alias is appended (D-01b write-side collision guard).

    Uses deterministic_match on a synthetic roster to simulate the post-write state.
    If deterministic_match returns None (ambiguous or no match) or resolves to a
    DIFFERENT employee, return False — do NOT learn (log and skip).

    The synthetic roster appends the token to the target employee's known_aliases only.
    This correctly detects:
    - Tokens already carried by 2+ employees (e.g. "D. Reyes" shared by David and
      Daniel Reyes): the synthetic roster still has 2 candidates → None → False.
    - Tokens that would introduce a NEW collision (token matches another employee's
      exact name or alias): synthetic roster has 2 candidates → None → False.
    - Unambiguous tokens: only target_employee carries the alias post-append → True.
    - Idempotent re-adds that are still unambiguous: True (safe to call twice).

    CRITICAL: Do NOT mutate the actual roster objects. The synthetic roster is a
    temporary computation object only (uses Pydantic v2 model_copy, never in-place).
    """
    synthetic_employees = []
    for emp in roster.employees:
        if emp.id == target_employee.id:
            new_aliases = list(emp.known_aliases) + [token]
            synthetic_employees.append(
                emp.model_copy(update={"known_aliases": new_aliases})
            )
        else:
            synthetic_employees.append(emp)
    synthetic_roster = roster.model_copy(update={"employees": synthetic_employees})
    result = deterministic_match(token, synthetic_roster)
    return result is not None and result.matched_employee_id == target_employee.id
