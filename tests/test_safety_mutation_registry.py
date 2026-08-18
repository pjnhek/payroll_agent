"""GUARD-02's completeness guard for `tests/safety_mutation_registry.py`.

Two independent halves, mirroring `tests/test_proof_mutation_targets.py`'s own
split:

1. Synthetic-source proofs (below) that each new resolver kind this registry
   introduces (`dict_entry`, `frozenset_member`, `call_count`, `tsx_fragment`)
   behaves correctly in isolation: it resolves a genuine target, rejects an
   absent one, and rejects a docstring/comment copy of the target text --
   proven against small hand-written source strings, the same style
   `tests/test_proof_mutation_targets.py` uses for its own three kinds. Also
   proves each Python-source resolver against this registry's REAL live
   targets, and proves `resolve_tsx_fragment` against REAL live TypeScript
   source (`frontend/src/boot/pageData.ts`), even though no `tsx_fragment`
   entry is populated in `SAFETY_MUTATION_TARGETS` this pass (see that
   module's own docstring for why).

2. The six registry-driven completeness tests this plan's Task 1 requires:
   the key set matches the canonical id set exactly, no two entries share a
   (file, scope, predicate) triple, every entry resolves against live source,
   every entry's named assertion text is genuinely asserted inside its named
   pinning test, every pinning test's node id is real, and a negative control
   proves each USED predicate kind rejects an absent fragment against live
   source (so a resolver that matches everything would be caught).

This module never re-executes a mutation against a database or a live
process -- these are markup/DTO/route-table edits with no database in the
loop, so it must stay a hermetic sibling run by the existing test job and
must NOT be added to `.github/workflows/concurrency-proof.yml` (a missing
DATABASE_URL there silently converts a proof into a skip -- a failure mode
this project has already been bitten by). The demonstrated-red evidence for
each registry entry is captured once, by hand, and recorded in this plan's
SUMMARY.md -- the same convention `docs/DURABILITY-PROOFS.md` documents for
PROOF-01..04.
"""

from __future__ import annotations

import ast

import pytest

from tests.safety_mutation_registry import (
    EXPECTED_SAFETY_IDS,
    REPO_ROOT,
    SAFETY_MUTATION_TARGETS,
    SafetyPredicate,
    assertion_is_asserted_in,
    resolve_safety_predicate,
    resolve_tsx_fragment,
)

# ===========================================================================
# Part 1 -- synthetic-source proofs of the new resolver kinds
# ===========================================================================

# --- dict_entry --------------------------------------------------------


def test_dict_entry_resolves_live_module_level_dict() -> None:
    source = (
        "_ESCAPES = {\n"
        "    '<': '\\\\u003c',\n"
        "    '>': '\\\\u003e',\n"
        "}\n"
    )
    result = resolve_safety_predicate(
        source,
        scope="<module>",
        predicate=SafetyPredicate(
            kind="dict_entry", target_name="_ESCAPES", dict_key="<", value_path=r"'\\u003c'"
        ),
    )
    assert result.resolved, "a live, non-docstring module-level dict entry must resolve"


def test_dict_entry_does_not_resolve_docstring_only_copy() -> None:
    source = (
        "'''The escapes map maps < to \\\\u003c.'''\n"
        "_ESCAPES = {\n"
        "    '<': 'SOMETHING_ELSE',\n"
        "}\n"
    )
    result = resolve_safety_predicate(
        source,
        scope="<module>",
        predicate=SafetyPredicate(
            kind="dict_entry", target_name="_ESCAPES", dict_key="<", value_path=r"'\\u003c'"
        ),
    )
    assert not result.predicate_satisfied, (
        "a docstring-only copy of the dict entry must not satisfy the resolver"
    )


def test_dict_entry_does_not_resolve_comment_only_copy() -> None:
    source = "# '<': '\\\\u003c' used to live here\n_ESCAPES = {'<': 'SOMETHING_ELSE'}\n"
    result = resolve_safety_predicate(
        source,
        scope="<module>",
        predicate=SafetyPredicate(
            kind="dict_entry", target_name="_ESCAPES", dict_key="<", value_path=r"'\\u003c'"
        ),
    )
    assert not result.predicate_satisfied, (
        "a comment-only copy of the dict entry must not satisfy the resolver"
    )


def test_dict_entry_missing_scope_says_so_distinctly() -> None:
    result = resolve_safety_predicate(
        "x = 1\n",
        scope="_NO_SUCH_MODULE_LEVEL_NAME",
        predicate=SafetyPredicate(
            kind="dict_entry", target_name="_ESCAPES", dict_key="<", value_path=r"'\\u003c'"
        ),
    )
    assert result.scope_found is False
    assert result.predicate_satisfied is False
    assert result.resolved is False


def test_dict_entry_resolves_against_real_live_templating_source() -> None:
    """The real SAFETY-01 target, read from this repository's own live source."""
    source = (REPO_ROOT / "app" / "routes" / "templating.py").read_text(encoding="utf-8")
    result = resolve_safety_predicate(
        source,
        scope="<module>",
        predicate=SafetyPredicate(
            kind="dict_entry",
            target_name="_JSON_SCRIPT_ESCAPES",
            dict_key="<",
            value_path=r'"\\u003c"',
        ),
    )
    assert result.resolved, "must resolve the real _JSON_SCRIPT_ESCAPES entry"


# --- frozenset_member ----------------------------------------------------


def test_frozenset_member_resolves_live_class_level_set() -> None:
    source = (
        "class Row:\n"
        "    EXCLUDED = frozenset({'business_id', 'source_email_id'})\n"
    )
    result = resolve_safety_predicate(
        source,
        scope="Row",
        predicate=SafetyPredicate(
            kind="frozenset_member", target_name="EXCLUDED", member="source_email_id"
        ),
    )
    assert result.resolved, "a live frozenset element must resolve"


def test_frozenset_member_does_not_resolve_docstring_or_comment_copy() -> None:
    source = (
        "class Row:\n"
        "    '''EXCLUDED contains source_email_id.'''\n"
        "    # source_email_id used to be here\n"
        "    EXCLUDED = frozenset({'business_id'})\n"
    )
    result = resolve_safety_predicate(
        source,
        scope="Row",
        predicate=SafetyPredicate(
            kind="frozenset_member", target_name="EXCLUDED", member="source_email_id"
        ),
    )
    assert not result.predicate_satisfied, (
        "a docstring or comment copy of the member must not resolve"
    )


def test_frozenset_member_does_not_resolve_different_member() -> None:
    source = "class Row:\n    EXCLUDED = frozenset({'business_id'})\n"
    result = resolve_safety_predicate(
        source,
        scope="Row",
        predicate=SafetyPredicate(
            kind="frozenset_member", target_name="EXCLUDED", member="source_email_id"
        ),
    )
    assert result.scope_found
    assert not result.predicate_satisfied, "a DIFFERENT member must not resolve"


def test_frozenset_member_resolves_against_real_live_runs_list_source() -> None:
    """The real SAFETY-02 target, read from this repository's own live source."""
    source = (REPO_ROOT / "app" / "schemas" / "runs_list.py").read_text(encoding="utf-8")
    result = resolve_safety_predicate(
        source,
        scope="RunListRow",
        predicate=SafetyPredicate(
            kind="frozenset_member", target_name="EXCLUDED", member="source_email_id"
        ),
    )
    assert result.resolved, "must resolve the real EXCLUDED entry naming source_email_id"


# --- call_count ------------------------------------------------------------


def test_call_count_resolves_matching_count() -> None:
    source = "app.mount('/static', x)\n"
    result = resolve_safety_predicate(
        source,
        scope="<module>",
        predicate=SafetyPredicate(kind="call_count", attr_name="mount", expected_count=1),
    )
    assert result.resolved, "a single matching call must satisfy expected_count=1"


def test_call_count_rejects_extra_call() -> None:
    source = "app.mount('/static', x)\napp.mount('/', y)\n"
    result = resolve_safety_predicate(
        source,
        scope="<module>",
        predicate=SafetyPredicate(kind="call_count", attr_name="mount", expected_count=1),
    )
    assert result.scope_found
    assert not result.predicate_satisfied, "a SECOND mount call must fail expected_count=1"


def test_call_count_excludes_docstring_and_comment_copies() -> None:
    source = (
        "'''Calls app.mount(...) exactly once.'''\n"
        "# app.mount('/', y) is not real\n"
        "app.mount('/static', x)\n"
    )
    result = resolve_safety_predicate(
        source,
        scope="<module>",
        predicate=SafetyPredicate(kind="call_count", attr_name="mount", expected_count=1),
    )
    assert result.resolved, (
        "a docstring/comment mentioning `.mount(` must not be counted as a real call"
    )


def test_call_count_resolves_against_real_live_main_source() -> None:
    """The real SAFETY-03 target, read from this repository's own live source."""
    source = (REPO_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    result = resolve_safety_predicate(
        source,
        scope="<module>",
        predicate=SafetyPredicate(kind="call_count", attr_name="mount", expected_count=1),
    )
    assert result.resolved, "must resolve exactly one live app.mount(...) call"


# --- tsx_fragment ------------------------------------------------------------


def test_tsx_fragment_resolves_within_named_symbol_region() -> None:
    source = (
        "export function readInitialData() {\n"
        "  return JSON.parse(element.textContent);\n"
        "}\n"
        "export function other() {\n"
        "  return element.innerHTML;\n"
        "}\n"
    )
    assert resolve_tsx_fragment(
        source, scope="readInitialData", fragment="JSON.parse(element.textContent)"
    ), "a fragment genuinely inside the named symbol's region must resolve"


def test_tsx_fragment_does_not_resolve_fragment_in_a_different_symbol() -> None:
    source = (
        "export function readInitialData() {\n"
        "  return JSON.parse(element.textContent);\n"
        "}\n"
        "export function other() {\n"
        "  return element.innerHTML;\n"
        "}\n"
    )
    assert not resolve_tsx_fragment(
        source, scope="readInitialData", fragment="element.innerHTML"
    ), "a fragment living only in a DIFFERENT exported symbol must not resolve"


def test_tsx_fragment_missing_symbol_returns_false() -> None:
    source = "export function somethingElse() { return 1; }\n"
    assert not resolve_tsx_fragment(
        source, scope="readInitialData", fragment="JSON.parse(element.textContent)"
    )


def test_tsx_fragment_resolves_against_real_live_pagedata_source() -> None:
    """Capability proof against REAL TypeScript source: `readInitialData` reads
    the island via `element.textContent` before JSON.parse, never `innerHTML`
    -- the client-side half of the XSS discipline SAFETY-01 enforces
    server-side. No `tsx_fragment` entry is populated in
    `SAFETY_MUTATION_TARGETS` this pass (see that module's docstring); this
    test only proves the resolver CAN see real TS source, so a future
    TypeScript-sourced safety target can be added without redesigning the
    predicate schema.
    """
    source = (REPO_ROOT / "frontend" / "src" / "boot" / "pageData.ts").read_text(
        encoding="utf-8"
    )
    assert resolve_tsx_fragment(
        source, scope="readInitialData", fragment="JSON.parse(element.textContent)"
    )
    assert not resolve_tsx_fragment(
        source, scope="readInitialData", fragment="element.innerHTML"
    ), "negative control: a plausible-but-absent fragment must be rejected on live source"


# ===========================================================================
# Part 2 -- the six registry-driven completeness tests
# ===========================================================================


def test_registry_covers_expected_safety_ids_exactly() -> None:
    assert sorted(SAFETY_MUTATION_TARGETS) == sorted(EXPECTED_SAFETY_IDS), (
        "the registry's key set must equal the canonical safety-id set exactly -- "
        "no missing id, no extra id"
    )


def test_registry_targets_are_mutually_distinct() -> None:
    triples = [
        (entry.file, entry.scope, entry.predicate) for entry in SAFETY_MUTATION_TARGETS.values()
    ]
    assert len(triples) == len(set(triples)), (
        "two safety targets sharing one (file, scope, predicate) triple would mean "
        "one of them was never independently falsified"
    )


def test_every_registry_entry_resolves_against_live_source() -> None:
    """The guard's real job: a refactor that moves, rewrites, or repoints a
    registered target must red this test, so the published evidence gets
    updated instead of quietly becoming fiction."""
    for safety_id, entry in sorted(SAFETY_MUTATION_TARGETS.items()):
        source = (REPO_ROOT / entry.file).read_text(encoding="utf-8")
        result = resolve_safety_predicate(source, scope=entry.scope, predicate=entry.predicate)
        assert result.resolved, (
            f"{safety_id}'s target does not resolve against live "
            f"{entry.file}::{entry.scope} -- scope_found={result.scope_found}, "
            f"predicate_satisfied={result.predicate_satisfied}"
        )


def test_every_registry_entrys_pinned_assertions_are_genuinely_asserted() -> None:
    """Uses the assertion resolver, never a substring search over the pinning
    test's file -- a comment quoting the assertion text must not satisfy this."""
    for safety_id, entry in sorted(SAFETY_MUTATION_TARGETS.items()):
        for pin in entry.pinning_tests:
            source = (REPO_ROOT / pin.test_file).read_text(encoding="utf-8")
            assert assertion_is_asserted_in(
                source, function_name=pin.test_name, assertion_text=pin.assertion_text
            ), (
                f"{safety_id}'s named assertion {pin.assertion_text!r} is not asserted "
                f"inside an ast.Assert node in {pin.test_file}::{pin.test_name}"
            )


def test_every_registry_entrys_pinning_test_node_id_is_real() -> None:
    for safety_id, entry in sorted(SAFETY_MUTATION_TARGETS.items()):
        for pin in entry.pinning_tests:
            test_file_path = REPO_ROOT / pin.test_file
            assert test_file_path.is_file(), f"{safety_id}'s pinning test_file does not exist"
            source = test_file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            found = any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == pin.test_name
                for node in ast.walk(tree)
            )
            assert found, (
                f"{safety_id}'s pinning test_name {pin.test_name!r} does not resolve to a "
                f"real test function in {pin.test_file} -- the registry may be pointing at "
                "a renamed test"
            )


@pytest.mark.parametrize(
    ("safety_id", "wrong_predicate"),
    [
        (
            "SAFETY-01",
            SafetyPredicate(
                kind="dict_entry",
                target_name="_JSON_SCRIPT_ESCAPES",
                dict_key="<",
                value_path=r'"DEFINITELY_NOT_THE_REAL_ESCAPE"',
            ),
        ),
        (
            "SAFETY-02",
            SafetyPredicate(
                kind="frozenset_member",
                target_name="EXCLUDED",
                member="definitely_not_a_real_excluded_column",
            ),
        ),
        (
            "SAFETY-03",
            SafetyPredicate(kind="call_count", attr_name="mount", expected_count=999),
        ),
    ],
)
def test_negative_control_rejects_absent_fragment_on_live_source(
    safety_id: str, wrong_predicate: SafetyPredicate
) -> None:
    """A deliberately wrong predicate value must be rejected against the SAME
    real live source the genuine entry resolves against -- proving the
    resolver does not simply match everything."""
    entry = SAFETY_MUTATION_TARGETS[safety_id]
    source = (REPO_ROOT / entry.file).read_text(encoding="utf-8")
    result = resolve_safety_predicate(source, scope=entry.scope, predicate=wrong_predicate)
    assert result.scope_found
    assert not result.predicate_satisfied, (
        f"a deliberately wrong predicate for {safety_id} must be rejected against real "
        "live source"
    )
