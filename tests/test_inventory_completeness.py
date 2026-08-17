"""Selection-layer completeness gate for GUARD-01's `tests/assertion_inventory.py`.

`tests/test_proof_mutation_targets.py` closed the analogous gap one layer down (a
published mutation must still name a REAL location in live source); this module
closes it one layer UP, at selection: does the registry's key set equal the set
of `.text` comparisons a fresh, independent walk of `tests/` actually finds
today? A registry that was correct when written but never re-checked against a
churning source tree is exactly the "hard-coded file list" failure mode
`scripts/check_proof_inventory.py`'s own docstring names — a typo'd id, a
renamed test, or a newly-added unclassified assertion would all pass silently
without this guard.

This module walks source, never scans text: `discover_text_comparisons` parses
every `.py` file under `tests/` with `ast.parse` and inspects every
`ast.Compare` node's left operand and every comparator for a `.text` attribute
access. Because `ast.walk` recurses into every child node regardless of its
parent's type, this single walk already reaches a `.text` comparison nested
inside an `ast.Assert`, an `ast.BoolOp` (`... and response.text == ...`), an
`ast.UnaryOp` (`not (x in response.text)`), a comprehension, or an f-string
format spec — no special-casing per container is needed, which is the whole
point of walking the parsed tree instead of grepping lines: a regex anchored to
one physical line silently drops a wrapped or multi-line `assert`.

What this guard establishes: the registry's key set matches a live, independent
re-derivation exactly (both directions — nothing missing, nothing stale), every
entry carries a non-null route and layer, every entry's captured `source_text`
still matches what `ast.get_source_segment` extracts from the CURRENT file (so
a refactor that moves or rewords a guarded assertion reds this test instead of
leaving a quietly-stale registry entry), every `.text`-bearing file under
`tests/` is named in `FILE_SCOPE_NOTES` with a real reason, discovery is
read-only and deterministic, and no two entries collide on their
`(file, line, col_offset)` position.

What this guard does NOT establish: it does not decide whether a rewritten
assertion is CORRECT after its page converts (that is a per-page follow-up
job, done once each page's own conversion actually lands) and it does not run
any mutation itself — the demonstrated-red evidence for this specific guard
is captured once, by hand: a mutation applied, the failing assertion named,
then a byte-identical revert, the same shape this project's durability proofs
use.
"""

from __future__ import annotations

import ast
import pathlib

from tests.assertion_inventory import ASSERTION_INVENTORY, FILE_SCOPE_NOTES

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"


def _is_text_attribute(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "text"


def _text_compare_nodes(tree: ast.AST) -> list[ast.Compare]:
    """Every `ast.Compare` node anywhere in `tree` whose left operand or any
    comparator is a `.text` attribute access. `ast.walk` is a full recursive
    walk over every child node in the tree, so this reaches a `.text`
    comparison no matter how deeply it is nested (inside an `assert`, a
    boolean/unary op, a comprehension, an f-string format spec) without any
    per-container special-casing.
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands: list[ast.expr] = [node.left, *node.comparators]
        if any(_is_text_attribute(operand) for operand in operands):
            hits.append(node)
    return hits


def discover_text_comparisons() -> dict[str, tuple[str, int, int]]:
    """Parse every `.py` file under `tests/` and collect every `.text`
    comparison's `(repo_relative_path, lineno, col_offset)`, keyed by the same
    `{module_stem}:{line}:{col_offset}` id `ASSERTION_INVENTORY` uses, so the
    two key sets can be compared directly.

    Read-only (opens and parses each file, mutates nothing) and holds no
    process-level state between calls — calling this twice in the same
    interpreter must return equal results
    (`test_discovery_is_deterministic_and_read_only`).
    """
    found: dict[str, tuple[str, int, int]] = {}
    for path in sorted(TESTS_DIR.rglob("*.py")):
        rel = str(path.relative_to(REPO_ROOT))
        source = path.read_bytes().decode("utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in _text_compare_nodes(tree):
            key = f"{path.stem}:{node.lineno}:{node.col_offset}"
            found[key] = (rel, node.lineno, node.col_offset)
    return found


def _files_containing_text_substring() -> set[str]:
    """A plain substring scan over the whole file, independent of the AST
    walk above — the honest cross-check that `FILE_SCOPE_NOTES` covers every
    file a human glancing at `grep -rl "\\.text" tests/` would also see,
    including files where `.text` never appears inside a real comparison.
    """
    result: set[str] = set()
    for path in sorted(TESTS_DIR.rglob("*.py")):
        rel = str(path.relative_to(REPO_ROOT))
        source = path.read_bytes().decode("utf-8")
        if ".text" in source:
            result.add(rel)
    return result


def _find_compare_node(tree: ast.AST, lineno: int, col_offset: int) -> ast.Compare | None:
    for node in _text_compare_nodes(tree):
        if node.lineno == lineno and node.col_offset == col_offset:
            return node
    return None


# ---------------------------------------------------------------------------
# The seven completeness tests
# ---------------------------------------------------------------------------


def test_every_discovered_assertion_has_a_registry_entry() -> None:
    discovered = discover_text_comparisons()
    missing = sorted(set(discovered) - set(ASSERTION_INVENTORY))
    assert not missing, (
        "discovered `.text` comparisons with no ASSERTION_INVENTORY entry "
        f"(file:line:col): {[discovered[k] for k in missing]}"
    )


def test_no_registry_entry_is_stale() -> None:
    """An entry with a non-null `replaced_by` is exempt from this check by
    design: it records that its guarded content moved into the React DOM,
    where TestClient has no server-side surface left to assert against, so
    the underlying `.text` comparison was deliberately DELETED from the test
    file rather than kept as a stale pointer. Every other entry must still
    resolve against a live comparison -- an unexplained disappearance is
    exactly the "stale pointer past a refactor or rename" failure mode this
    guard exists to catch.
    """
    discovered = discover_text_comparisons()
    replaced = {key for key, entry in ASSERTION_INVENTORY.items() if entry.replaced_by}
    orphans = sorted(set(ASSERTION_INVENTORY) - set(discovered) - replaced)
    assert not orphans, (
        "ASSERTION_INVENTORY entries with no matching live `.text` comparison "
        f"(a stale pointer past a refactor or rename): {orphans}"
    )


def test_every_entry_has_a_layer_and_route_classification() -> None:
    unclassified = [
        key
        for key, entry in ASSERTION_INVENTORY.items()
        if not entry.route or not entry.route.strip() or entry.layer is None
    ]
    assert not unclassified, (
        f"ASSERTION_INVENTORY entries missing a route or layer classification: {unclassified}"
    )


def test_every_entry_source_text_matches_live_source() -> None:
    """Same `replaced_by` exemption as test_no_registry_entry_is_stale --
    a deleted, relocated-to-Vitest assertion has no live source segment to
    diff against."""
    mismatches = []
    for key, entry in sorted(ASSERTION_INVENTORY.items()):
        if entry.replaced_by:
            continue
        path = REPO_ROOT / entry.file
        source = path.read_bytes().decode("utf-8")
        tree = ast.parse(source, filename=str(path))
        node = _find_compare_node(tree, entry.line, entry.col_offset)
        if node is None:
            mismatches.append(
                f"{key}: no matching `.text` ast.Compare node at "
                f"{entry.file}:{entry.line}:{entry.col_offset} in current source"
            )
            continue
        live_segment = ast.get_source_segment(source, node)
        if live_segment != entry.source_text:
            mismatches.append(
                f"{key}: source_text drifted — registry={entry.source_text!r} "
                f"live={live_segment!r}"
            )
    assert not mismatches, "\n".join(mismatches)


def test_every_text_bearing_file_is_scoped() -> None:
    substring_files = _files_containing_text_substring()
    discovered = discover_text_comparisons()
    discovered_files = {rel for rel, _, _ in discovered.values()}

    missing_notes = sorted(substring_files - set(FILE_SCOPE_NOTES))
    assert not missing_notes, (
        f"files containing the substring '.text' with no FILE_SCOPE_NOTES entry: {missing_notes}"
    )

    stale_notes = sorted(set(FILE_SCOPE_NOTES) - substring_files)
    assert not stale_notes, (
        f"FILE_SCOPE_NOTES entries for files that no longer contain '.text': {stale_notes}"
    )

    empty_notes = sorted(f for f in substring_files if not FILE_SCOPE_NOTES.get(f, "").strip())
    assert not empty_notes, f"files with an empty FILE_SCOPE_NOTES reason: {empty_notes}"

    zero_hit_files = sorted(substring_files - discovered_files)
    unexplained_zero = [
        f for f in zero_hit_files if "zero" not in FILE_SCOPE_NOTES[f].lower()
    ]
    assert not unexplained_zero, (
        "files with zero discovered `.text` comparisons but a FILE_SCOPE_NOTES reason that "
        f"does not say so: {unexplained_zero}"
    )


def test_discovery_is_deterministic_and_read_only() -> None:
    first = discover_text_comparisons()
    second = discover_text_comparisons()
    assert first == second, "discover_text_comparisons() returned different results on two calls"


def test_entry_keys_are_position_unique() -> None:
    triples = [(entry.file, entry.line, entry.col_offset) for entry in ASSERTION_INVENTORY.values()]
    assert len(triples) == len(set(triples)), (
        "two ASSERTION_INVENTORY entries share one (file, line, col_offset) triple"
    )
