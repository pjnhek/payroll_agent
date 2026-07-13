"""Name reconciliation: the PURE deterministic resolver that never guesses.

A PURE function: typed values in, list[NameMatchResult] out. NO DB, NO connection, NO
model — there is no fuzzy second layer, by design. The eval calls this identical function
with fixture inputs, so the measured resolver is the shipped resolver.

Resolution is pure code over roster facts. Per submitted name:

  - exact normalized match (casefold + whitespace-normalize) to EXACTLY ONE employee,
    with no other employee sharing the normalized name -> ``source="exact"``,
    ``resolved=True``.
  - a stored ``known_alias`` match for EXACTLY ONE employee, no collision ->
    ``source="alias"``, ``resolved=True``. This is the READ side of the human-
    confirmation learning loop; alias_learning.py owns the WRITE side.
  - anything else — no match, a typo, a first-time nickname, a garbled name, or a name
    that maps to 2+ employees — degrades to ``source="none"``, ``resolved=False``,
    ``matched_employee_id=None``. The resolver NEVER guesses on a money-moving decision:
    an unresolved name costs one clarifying email, whereas a guessed name pays the wrong
    person.
  - an optional per-run ``overrides`` mapping lets a human operator state a name's
    resolution explicitly at the resolve form -> ``source="operator"``, ``resolved=True``.
    Still not a guess: a human, not the model, made the call.

Collision safety: if a normalized name (or alias) matches MORE THAN ONE employee, the
resolver refuses to pick either and returns unresolved, so the name cannot be silently
routed to the wrong person. decide() is the authority on run-level / cross-name collisions;
here the resolver simply declines to uniquely resolve.
"""
from __future__ import annotations

import unicodedata
import uuid

from app.models.roster import NameMatchResult, Roster


def normalize_name(name: str) -> str:
    """Whitespace-normalize + NFC(casefold(s)) for deterministic Unicode-safe comparison.

    Order matters: NFC is applied AFTER casefold, because casefold can emit a non-NFC
    sequence for some inputs. Without the post-casefold NFC, the same name typed as NFD
    and as NFC would compare UNEQUAL and a roster employee would fail to resolve — the
    client gets a clarifying email about a name that is actually a perfect match. (A
    pre-casefold NFC is not needed; a full Unicode scan showed only the post-casefold pass
    is load-bearing.)

    NFC, not NFKC: NFKC over-folds compatibility characters, which mangles real names.
    """
    return " ".join(unicodedata.normalize("NFC", name.casefold()).split())


def deterministic_match(name: str, roster: Roster) -> NameMatchResult | None:
    """Resolve a name to EXACTLY ONE roster employee, or None if it can't.

    Uniqueness is enforced ACROSS BOTH TIERS, not within each tier separately: the name is
    matched against every employee's normalized full_name AND every stored known_alias, and
    the set of DISTINCT candidate employees is what must be unique.

    So a name that is one employee's full_name AND a *different* employee's alias is
    ambiguous (2 distinct candidates) -> None, even though it is a unique hit within the
    exact tier on its own. Checking the tiers independently — "exact wins, alias is only a
    fallback" — would resolve that name straight to the exact employee and silently pay
    them the hours meant for whoever carries it as an alias. A name shared by 2+ employees
    within either tier is likewise ambiguous -> None. No match -> None.

    When the single resolved employee was reached via full_name the source is "exact";
    otherwise (alias-only) it is "alias".
    """
    norm = normalize_name(name)

    exact_ids = [emp.id for emp in roster.employees if normalize_name(emp.full_name) == norm]
    alias_ids = [
        emp.id
        for emp in roster.employees
        if any(normalize_name(alias) == norm for alias in emp.known_aliases)
    ]

    # Distinct candidate employees across BOTH tiers — uniqueness is global.
    candidate_ids = set(exact_ids) | set(alias_ids)
    if len(candidate_ids) != 1:
        # Zero candidates (no match) or 2+ distinct employees (an ambiguous collision):
        # not uniquely resolvable, so fall through to the unresolved result and let the
        # run ask the client rather than picking a person.
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
    *,
    overrides: dict[str, str] | None = None,
) -> list[NameMatchResult]:
    """Resolve each submitted name against the roster (pure deterministic code).

    Returns one NameMatchResult per submitted name, in submitted order. A name that
    uniquely resolves via exact/alias is resolved=True; everything else degrades to
    source="none", resolved=False. There is no model layer and no fuzzy guessing.
    decide() owns the run-level decision over these facts.

    overrides: an optional submitted_name -> employee_id_str mapping supplied by a HUMAN
    operator at the resolve form. When present, an override WINS BEFORE the exact and
    stored-alias tiers for that name. This does not weaken the no-guess guarantee: a human
    explicitly stated the match (source="operator"). The model still never decides.
    Default None leaves every caller behavior-identical — no override map means every name
    resolves via exact/alias/none exactly as it otherwise would.

    Validation: an override id that does NOT belong to a roster employee is silently
    ignored for that name and falls through to normal resolution. This function never
    accepts an id that is not actually on the roster, so a malformed, stale, or tampered
    override map can never bind hours to a person outside this business's roster. The
    caller (the resolve route) is responsible for rejecting an invalid employee_id at the
    HTTP boundary; this is the defense-in-depth layer behind it.
    """
    overrides = overrides or {}
    roster_ids = {emp.id for emp in roster.employees}
    results: list[NameMatchResult] = []
    for name in submitted_names:
        override_id_str = overrides.get(name)
        if override_id_str is not None:
            try:
                override_id = uuid.UUID(str(override_id_str))
            except (ValueError, AttributeError):
                override_id = None
            if override_id is not None and override_id in roster_ids:
                results.append(
                    NameMatchResult(
                        submitted_name=name,
                        matched_employee_id=override_id,
                        source="operator",
                        resolved=True,
                        reason="operator-resolved",
                    )
                )
                continue
            # Invalid/unknown override id — fall through to normal resolution
            # rather than trusting an id that isn't actually on this roster.
        results.append(deterministic_match(name, roster) or _unresolved(name))
    return results
