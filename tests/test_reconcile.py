"""Deterministic name-resolution tests (LLM-04). Pure, DB-free, NO model.

reconcile_names is PURE CODE — there is no LLM layer here, because deciding WHICH
employee a name refers to is a money-moving judgment the system must never guess at.
Per submitted name it resolves against the roster in exactly three ways:

  - ``source="exact"`` — exact normalized (casefold + whitespace) match to exactly
    ONE employee, resolved=True.
  - ``source="alias"`` — a stored ``known_alias`` match for exactly ONE employee,
    resolved=True (the READ side of the learning loop).
  - ``source="none"`` — anything else (typo, first-time nickname, unknown, or a
    name that matches 2+ employees) — resolved=False, matched_employee_id=None.

A name that uniquely resolves nowhere is NOT guessed at: it degrades to unresolved and
the run-level clarify path in decide() owns it. "Probably David" is how the wrong person
gets paid.

The eval imports this SAME function, so the eval scores the code production actually runs.
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
    """A first-time nickname NOT in known_aliases is NOT guessed at.

    The resolver only READS stored aliases; it never invents one. An alias is learned
    later, and only from an explicit human confirmation — never inferred here.
    """
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
    """A name matching 2+ roster employees resolves to NEITHER.

    Resolution requires UNIQUENESS. With two employees sharing a name, picking either
    one is a coin flip over someone's paycheck, so the resolver returns source='none'
    and the run clarifies.
    """
    from app.models.roster import Roster as _R

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
    """A CROSS-TIER collision must not resolve either.

    A name that is employee A's exact full_name AND employee B's stored alias is
    ambiguous between two people. A resolver that checked the exact tier first and
    returned on the first hit would silently pay A and never notice B — so uniqueness
    must be enforced ACROSS both tiers, not within each one.
    """
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
    """A Roster with two employees sharing one UUID must raise.

    The resolver's uniqueness check is set-based over employee ids. Two distinct rows
    carrying the same id would collapse into ONE candidate, so an ambiguous name would
    look unique and resolve — defeating the collision guard at its root.
    """
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
# Purity: no llm parameter, no LLM/DB/prompt import
# ---------------------------------------------------------------------------


def test_reconcile_is_pure_no_llm_no_db():
    """reconcile_names takes NO llm/conn param and imports no LLM/DB/prompt module.

    Purity is what lets the eval import and score the EXACT function production runs. An
    llm= or conn= parameter would make the eval's scored path diverge from the shipped
    one — and the eval's credibility rests entirely on them being the same code.
    """
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


# ---------------------------------------------------------------------------
# Unicode normalization (MONEY-02): visually identical names resolve identically.
#
# The roster stores names in NFC (precomposed) form, but a client's mail client may send
# the very same name in NFD decomposition. The two are indistinguishable on screen yet
# casefold to DIFFERENT byte sequences, so a casefold-only normalizer finds no match and
# the employee silently fails to resolve — the client is asked to clarify a name they
# spelled correctly. _norm normalizes both sides to NFC: NFC(casefold(NFC(s))).
# ---------------------------------------------------------------------------


def test_nfd_name_resolves_same_as_nfc(roster_from_seed):
    """A submitted name in NFD Unicode form must resolve to the same employee as its
    NFC equivalent — otherwise a correctly-spelled name is rejected as unknown.

    The roster stores names in NFC form. A client email may submit the same name in
    NFD decomposition (e.g. 'e' + combining acute rather than precomposed 'é').
    Without NFC normalization in _norm, the two forms casefold to different byte
    sequences -> no match -> a silent fail-to-resolve on a name the client spelled
    perfectly. _norm therefore uses the hardened form NFC(casefold(NFC(s))).

    The test builds a minimal roster with an employee whose full_name is the NFC form of
    a name containing combining characters, submits the NFD form, and asserts the match
    resolves to that employee's id.
    """
    import unicodedata

    from app.models.roster import Roster as _Roster

    # Build NFC and NFD forms of a name with combining characters.
    nfc_name = unicodedata.normalize("NFC", "Jos\xe9 Mart\xednez")   # precomposed
    nfd_name = unicodedata.normalize("NFD", nfc_name)                 # decomposed

    # Sanity: NFC and NFD must be byte-distinct (otherwise the test is vacuous).
    assert nfc_name != nfd_name, (
        "NFC and NFD forms must differ at the byte level to exercise the bug"
    )

    # Use an existing employee as the base; override full_name to the NFC form.
    maria = next(e for e in roster_from_seed.employees if e.full_name == "Maria Chen")
    jose = maria.model_copy(update={"full_name": nfc_name, "known_aliases": []})
    roster_with_jose = _Roster(
        business_id=roster_from_seed.business_id,
        employees=[jose],
    )

    # Submit the NFD form against the NFC-named roster entry.
    [result] = reconcile_names([nfd_name], roster_with_jose)

    assert result.resolved is True, (
        f"NFD submitted name {nfd_name!r} must resolve to the same employee as the NFC "
        f"roster name {nfc_name!r} -- a casefold-only _norm produces no match across "
        "the two forms and silently rejects a correctly-spelled name"
    )
    assert result.matched_employee_id == jose.id, (
        "MONEY-02: resolved employee must be the NFC-named roster entry"
    )
