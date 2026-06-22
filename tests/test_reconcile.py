"""Deterministic name-resolution tests (LLM-04, D-21-01). Pure, DB-free, NO model.

reconcile_names is now PURE CODE — there is no LLM layer. Per submitted name it
resolves against the roster exactly three ways (D-21-01):

  - ``source="exact"`` — exact normalized (casefold + whitespace) match to exactly
    ONE employee, resolved=True.
  - ``source="alias"`` — a stored ``known_alias`` match for exactly ONE employee,
    resolved=True (the READ side of the learning loop, D-21-07).
  - ``source="none"`` — anything else (typo, first-time nickname, unknown, or a
    name that matches 2+ employees) — resolved=False, matched_employee_id=None.

A name that uniquely-resolves nowhere (first-time variant / typo / unknown) is NOT
guessed at here — it degrades to unresolved and the run-level clarify path in
decide() owns it. The eval (Phase 4) imports this SAME function (D-21-09).
"""
from __future__ import annotations

import inspect
import pathlib

from app.models.roster import Roster
from app.pipeline.reconcile_names import reconcile_names


def _emp(roster: Roster, full_name: str):
    return next(e for e in roster.employees if e.full_name == full_name)


# ---------------------------------------------------------------------------
# exact + normalized-exact + stored-alias → resolved (source exact / alias)
# ---------------------------------------------------------------------------


def test_exact_match_resolves(roster_from_seed):
    maria = _emp(roster_from_seed, "Maria Chen")
    [result] = reconcile_names(["Maria Chen"], roster_from_seed)

    assert result.source == "exact"
    assert result.resolved is True
    assert result.matched_employee_id == maria.id


def test_normalized_exact_match_resolves(roster_from_seed):
    """casefold + whitespace-normalize: 'maria  chen' resolves to Maria Chen."""
    maria = _emp(roster_from_seed, "Maria Chen")
    [result] = reconcile_names(["maria  chen"], roster_from_seed)

    assert result.source == "exact"
    assert result.resolved is True
    assert result.matched_employee_id == maria.id


def test_stored_alias_resolves(roster_from_seed):
    """A SEEDED known_alias ('M. Chen' for Maria Chen) resolves via source='alias'."""
    maria = _emp(roster_from_seed, "Maria Chen")
    [result] = reconcile_names(["M. Chen"], roster_from_seed)

    assert result.source == "alias"
    assert result.resolved is True
    assert result.matched_employee_id == maria.id


def test_single_word_stored_alias_resolves(roster_from_seed):
    """The bare-first-name stored alias ('Maria') resolves to source='alias'."""
    maria = _emp(roster_from_seed, "Maria Chen")
    [result] = reconcile_names(["Maria"], roster_from_seed)

    assert result.source == "alias"
    assert result.resolved is True
    assert result.matched_employee_id == maria.id


# ---------------------------------------------------------------------------
# first-time-alias variant / typo / unknown → source="none", resolved=False
# ---------------------------------------------------------------------------


def test_first_time_alias_variant_is_unresolved(roster_from_seed):
    """A first-time nickname NOT in known_aliases is NOT guessed at (D-21-07 READ
    side only): no write path, no model — it degrades to unresolved."""
    [result] = reconcile_names(["Mar"], roster_from_seed)

    assert result.source == "none"
    assert result.resolved is False
    assert result.matched_employee_id is None


def test_typo_is_unresolved(roster_from_seed):
    """A typo'd name ('Maira Chen') has no exact/alias match → unresolved. The
    deterministic resolver never fuzzy-guesses on a money-moving decision."""
    [result] = reconcile_names(["Maira Chen"], roster_from_seed)

    assert result.source == "none"
    assert result.resolved is False
    assert result.matched_employee_id is None


def test_unknown_name_is_unresolved(roster_from_seed):
    """A name matching no employee at all → source='none', resolved=False."""
    [result] = reconcile_names(["Totally Unseen Person"], roster_from_seed)

    assert result.source == "none"
    assert result.resolved is False
    assert result.matched_employee_id is None


# ---------------------------------------------------------------------------
# collision-safety at the resolver: a name shared by 2+ employees does NOT
# resolve to either (it can't be uniquely resolved). The run-level collision
# check in decide() is the authority; here it simply degrades to unresolved.
# ---------------------------------------------------------------------------


def test_name_matching_two_employees_does_not_resolve(roster_from_seed):
    """If the normalized submitted name matches 2+ roster employees, the resolver
    refuses to pick one — it returns source='none' (D-21-02 uniqueness)."""
    from app.models.roster import Employee, Roster as _R

    base = _emp(roster_from_seed, "Maria Chen")
    # A second employee sharing the same full_name (a real-world duplicate).
    twin = base.model_copy(update={"id": __import__("uuid").uuid4()})
    ambiguous = _R(business_id=roster_from_seed.business_id, employees=[base, twin])

    [result] = reconcile_names(["Maria Chen"], ambiguous)

    assert result.source == "none"
    assert result.resolved is False
    assert result.matched_employee_id is None


def test_alias_shared_by_two_employees_does_not_resolve(roster_from_seed):
    """A known_alias shared by two employees can't be uniquely resolved → none."""
    import uuid

    from app.models.roster import Roster as _R

    maria = _emp(roster_from_seed, "Maria Chen")  # has alias 'Maria'
    # A second employee that ALSO carries 'Maria' as an alias.
    other = maria.model_copy(
        update={"id": uuid.uuid4(), "full_name": "Maria Lopez", "known_aliases": ["Maria"]}
    )
    ambiguous = _R(business_id=roster_from_seed.business_id, employees=[maria, other])

    [result] = reconcile_names(["Maria"], ambiguous)

    assert result.source == "none"
    assert result.resolved is False
    assert result.matched_employee_id is None


def test_name_is_one_employees_fullname_and_another_employees_alias_does_not_resolve(
    roster_from_seed,
):
    """CROSS-TIER collision (review fix): a name that is employee A's exact full_name
    AND employee B's stored alias is ambiguous between TWO employees, so it must NOT
    silently resolve to A — uniqueness is enforced across both tiers (D-21-02)."""
    import uuid

    from app.models.roster import Roster as _R

    maria = _emp(roster_from_seed, "Maria Chen")
    # A different employee whose alias is exactly Maria's full name.
    other = maria.model_copy(
        update={
            "id": uuid.uuid4(),
            "full_name": "Dave Smithson",
            "known_aliases": ["Maria Chen"],
        }
    )
    ambiguous = _R(business_id=roster_from_seed.business_id, employees=[maria, other])

    [result] = reconcile_names(["Maria Chen"], ambiguous)

    assert result.source == "none", "exact-vs-alias collision must NOT resolve to one"
    assert result.resolved is False
    assert result.matched_employee_id is None


def test_roster_rejects_duplicate_employee_ids(roster_from_seed):
    """Review fix: a Roster with two employees sharing one UUID must raise — otherwise
    the set-based uniqueness check in deterministic_match could collapse two distinct
    rows into one candidate and wrongly resolve an ambiguous name."""
    import pytest
    from pydantic import ValidationError

    from app.models.roster import Roster as _R

    maria = _emp(roster_from_seed, "Maria Chen")
    dup = maria.model_copy(update={"full_name": "Maria Lopez"})  # SAME id
    with pytest.raises(ValidationError):
        _R(business_id=roster_from_seed.business_id, employees=[maria, dup])


# ---------------------------------------------------------------------------
# shape: one result per submitted name, in submitted order
# ---------------------------------------------------------------------------


def test_one_result_per_submitted_name_in_order(roster_from_seed):
    submitted = ["Maria Chen", "Ghost", "M. Chen"]
    results = reconcile_names(submitted, roster_from_seed)

    assert [r.submitted_name for r in results] == submitted
    assert results[0].source == "exact"
    assert results[1].source == "none"
    assert results[2].source == "alias"


# ---------------------------------------------------------------------------
# purity: no llm parameter, no LLM/DB/prompt import (D-21-09)
# ---------------------------------------------------------------------------


def test_reconcile_is_pure_no_llm_no_db():
    """reconcile_names takes NO llm/conn param and imports no LLM/DB/prompt module
    (statically assertable) — it is a pure importable function the eval reuses."""
    import app.pipeline.reconcile_names as recon_mod

    params = inspect.signature(reconcile_names).parameters
    assert "llm" not in params, "reconcile_names must not take an llm parameter"
    assert "conn" not in params, "reconcile_names must take no DB connection"

    src = pathlib.Path(recon_mod.__file__).read_text()
    assert "supabase" not in src
    assert "get_connection" not in src
    assert "from app.db" not in src and "import app.db" not in src
    assert "from app.llm" not in src and "import app.llm" not in src
    assert "NameReconciliation" not in src
