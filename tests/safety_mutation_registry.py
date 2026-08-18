"""GUARD-02's concrete formulation: a hermetic sibling of the durability-proof
registry (`tests/test_proof_mutation_targets.py`), scoped to the SAFETY subset of
assertions on the converted `/runs` page -- island XSS escaping, the PII/internal
allowlist exclusion, and the catch-all route absence GUARD-05 also depends on.

What this registry establishes: for each named safety property, a structured
`SafetyTarget` naming the live source location (file + scope, where "scope" is a
Python function/class name or the module itself), a `SafetyPredicate` describing
the SAFE, CURRENT state of that location (not the mutation -- the mutation is a
temporary, reverted edit performed once by hand and recorded in this plan's
SUMMARY.md, mirroring `docs/DURABILITY-PROOFS.md`'s convention), and one or more
`PinnedAssertion`s: a real pytest test whose named assertion text is proven to
genuinely exist inside it. `tests/test_safety_mutation_registry.py` is this
registry's own completeness guard -- it never re-executes a mutation (that would
require actually breaking the source on every CI run); it proves the registry's
own claims still point at something real: the predicate still resolves against
live source, the named assertion is still genuinely asserted inside the named
test, and the named test still exists.

What this registry does NOT establish: it is not `tests/assertion_inventory.py`
(GUARD-01's full route-attribution inventory) and it does not attempt to cover
every absence assertion converted on `/runs` -- only the safety-critical subset
(PII scrubbing, XSS, the catch-all/no-HTML route-table invariant), mirroring
PROOF-05's precedent of pinning four durability proofs rather than all 1,400
tests. See this plan's SUMMARY.md for the full derivation from
`tests/assertion_inventory.py`'s absence entries and for why two safety concerns
(the catch-all mount absence and the non-HTML service-route guarantee) are
recorded as ONE consolidated target rather than two: they share the exact same
safe-state invariant (`app/main.py` declares exactly one `Mount`, at `/static`),
and a second entry with the identical (file, scope, predicate) triple would fail
this module's own no-duplicate-triple guard -- an artificially distinguished
second predicate would not describe a genuinely different fact.

Why a new TypeScript/JSX predicate kind exists (`tsx_fragment`): `frontend/src/
boot/pageData.ts::readInitialData` reads the embedded island via
`element.textContent` before `JSON.parse`-ing it -- never `element.innerHTML` --
which is the client-side half of the same XSS discipline `json_script()`'s
escaping enforces server-side. Python's `ast` module cannot parse TypeScript, so
forcing one of the `dict_entry`/`frozenset_member`/`call_count` kinds (all of
which walk a real Python AST) against a `.ts` file would either raise on parse or,
worse, silently degrade to a text search with no docstring/comment exclusion --
a match that means nothing, per this plan's own instruction. `tsx_fragment` is
therefore implemented as an honest, clearly-labeled TEXT-based resolver (no real
TypeScript parser is available in this codebase) that locates a named exported
symbol's approximate source region and searches only within it. Its own
capability and negative-control tests below prove it can resolve against REAL
`frontend/src/boot/pageData.ts` source and can reject an absent fragment -- but
this plan's frontmatter scopes `files_modified` to `tests/` files only, so no new
Vitest test may be added to pin a `tsx_fragment` entry in `SAFETY_MUTATION_TARGETS`
this pass (a `SafetyTarget`'s `pinning_tests` must each name a test that already
exists on disk, per the registry's own "no stale pointer" discipline, and no such
Vitest test exists yet). The kind is declared and demonstrated capable, so a
future phase's genuinely TypeScript-sourced safety target (e.g. Phase 23's
`MutationForm` `preventDefault()` guard) can be added without a schema change --
this is a stated, explicit gap, not a silent one.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tests.test_proof_mutation_targets import assertion_is_asserted_in

__all__ = [
    "REPO_ROOT",
    "MODULE_SCOPE",
    "SafetyPredicateKind",
    "SafetyPredicate",
    "PinnedAssertion",
    "SafetyTarget",
    "SafetyResolution",
    "resolve_safety_predicate",
    "resolve_tsx_fragment",
    "assertion_is_asserted_in",
    "EXPECTED_SAFETY_IDS",
    "SAFETY_MUTATION_TARGETS",
]

REPO_ROOT = Path(__file__).resolve().parent.parent

# Sentinel `scope` value meaning "resolve against the whole module, not a named
# function or class" -- app/main.py's mount-count invariant and
# app/routes/templating.py's escape map both live at module top level, outside
# any function.
MODULE_SCOPE = "<module>"

SafetyPredicateKind = Literal[
    "dict_entry",
    "frozenset_member",
    "call_count",
    "tsx_fragment",
]


@dataclass(frozen=True)
class SafetyPredicate:
    """A structured description of one safety target's CURRENT, SAFE shape.

    Only the fields relevant to `kind` are populated. Dispatch is by `kind`
    through a lookup table, matching `tests/test_proof_mutation_targets.py`'s
    own dispatch-table shape.
    """

    kind: SafetyPredicateKind
    # dict_entry / frozenset_member share target_name (the assigned variable)
    target_name: str | None = None
    # dict_entry: a specific key inside the Dict literal bound to target_name,
    # mapped to a value whose normalized rendering equals value_path
    dict_key: str | None = None
    value_path: str | None = None
    # frozenset_member: a string element inside the frozenset(...) literal
    # bound to target_name
    member: str | None = None
    # call_count: the number of ast.Call nodes anywhere in scope whose func is
    # an Attribute with this .attr name
    attr_name: str | None = None
    expected_count: int | None = None
    # tsx_fragment: a text fragment that must appear within the named scope's
    # (an exported symbol's) approximate source region
    fragment: str | None = None


@dataclass(frozen=True)
class PinnedAssertion:
    """One test whose named assertion text goes red when this target's
    mutation is applied."""

    test_file: str
    test_name: str
    assertion_text: str


@dataclass(frozen=True)
class SafetyTarget:
    file: str
    scope: str
    predicate: SafetyPredicate
    pinning_tests: tuple[PinnedAssertion, ...]


# ---------------------------------------------------------------------------
# Shared AST helpers -- same normalization/docstring-exclusion discipline as
# tests/test_proof_mutation_targets.py, generalized to resolve against a
# MODULE or a ClassDef in addition to a FunctionDef/AsyncFunctionDef, since two
# of this registry's three Python targets live outside any function.
# ---------------------------------------------------------------------------

_Scope = ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef


def _normalize_ws(text: str) -> str:
    return " ".join(text.split())


def _normalize_expr(expr_source: str) -> str:
    node = ast.parse(expr_source, mode="eval").body
    return _normalize_ws(ast.unparse(node))


def _find_scope(tree: ast.Module, scope_name: str) -> _Scope | None:
    """Resolve `scope_name` to a Module (the sentinel `MODULE_SCOPE`), or to a
    FunctionDef/AsyncFunctionDef/ClassDef found anywhere in `tree` by name.
    Returns `None` when scope_name names nothing -- a distinct outcome from
    "found it, predicate unsatisfied", matching the durability registry's own
    `function_found`/`predicate_satisfied` split.
    """
    if scope_name == MODULE_SCOPE:
        return tree
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == scope_name
        ):
            return node
    return None


def _docstring_node(scope: _Scope) -> ast.Constant | None:
    """The scope's own docstring constant node (Module/ClassDef/FunctionDef all
    share the same shape: a bare string-constant Expr as the first body
    statement), excluded from every resolver below by NODE IDENTITY so a
    docstring copy of a mutation target can never satisfy a resolver -- the
    same trap `tests/test_proof_mutation_targets.py` closes.
    """
    if not scope.body:
        return None
    first = scope.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return first.value
    return None


# ---------------------------------------------------------------------------
# Per-kind resolvers
# ---------------------------------------------------------------------------


def _resolve_dict_entry(scope: _Scope, predicate: SafetyPredicate) -> bool:
    assert predicate.target_name is not None
    assert predicate.dict_key is not None
    assert predicate.value_path is not None
    expected = _normalize_expr(predicate.value_path)
    docstring_node = _docstring_node(scope)
    for node in ast.walk(scope):
        if node is docstring_node:
            continue
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = node.targets
            value: ast.expr | None = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if value is None or not isinstance(value, ast.Dict):
            continue
        if not any(isinstance(t, ast.Name) and t.id == predicate.target_name for t in targets):
            continue
        for key, val in zip(value.keys, value.values, strict=True):
            if key is None:
                continue
            if not (isinstance(key, ast.Constant) and key.value == predicate.dict_key):
                continue
            if _normalize_ws(ast.unparse(val)) == expected:
                return True
    return False


def _resolve_frozenset_member(scope: _Scope, predicate: SafetyPredicate) -> bool:
    assert predicate.target_name is not None
    assert predicate.member is not None
    docstring_node = _docstring_node(scope)
    for node in ast.walk(scope):
        if node is docstring_node:
            continue
        if isinstance(node, ast.AnnAssign):
            target: ast.expr = node.target
            value: ast.expr | None = node.value
        elif isinstance(node, ast.Assign):
            if len(node.targets) != 1:
                continue
            target = node.targets[0]
            value = node.value
        else:
            continue
        if value is None or not (
            isinstance(target, ast.Name) and target.id == predicate.target_name
        ):
            continue
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "frozenset"
        ):
            continue
        if not value.args:
            continue
        literal = value.args[0]
        elements: list[ast.expr] = []
        if isinstance(literal, (ast.Set, ast.List, ast.Tuple)):
            elements = list(literal.elts)
        for element in elements:
            if isinstance(element, ast.Constant) and element.value == predicate.member:
                return True
    return False


def _resolve_call_count(scope: _Scope, predicate: SafetyPredicate) -> bool:
    assert predicate.attr_name is not None
    assert predicate.expected_count is not None
    docstring_node = _docstring_node(scope)
    count = 0
    for node in ast.walk(scope):
        if node is docstring_node:
            continue
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == predicate.attr_name
        ):
            count += 1
    return count == predicate.expected_count


# Dispatch table: adding a fourth Python-source predicate kind means adding one
# more resolver function above and one more entry here, never touching
# `resolve_safety_predicate`'s scope-lookup logic.
_PyResolverFn = Callable[[_Scope, SafetyPredicate], bool]
_PY_RESOLVERS: dict[SafetyPredicateKind, _PyResolverFn] = {
    "dict_entry": _resolve_dict_entry,
    "frozenset_member": _resolve_frozenset_member,
    "call_count": _resolve_call_count,
}


@dataclass(frozen=True)
class SafetyResolution:
    scope_found: bool
    predicate_satisfied: bool

    @property
    def resolved(self) -> bool:
        return self.scope_found and self.predicate_satisfied


def resolve_safety_predicate(
    source: str, *, scope: str, predicate: SafetyPredicate
) -> SafetyResolution:
    """Resolve a Python-source `predicate` (kind in `_PY_RESOLVERS`) against
    `source`, scoped to `scope` (a function/class name, or `MODULE_SCOPE`).
    """
    tree = ast.parse(source)
    scope_node = _find_scope(tree, scope)
    if scope_node is None:
        return SafetyResolution(scope_found=False, predicate_satisfied=False)
    resolver = _PY_RESOLVERS[predicate.kind]
    return SafetyResolution(scope_found=True, predicate_satisfied=resolver(scope_node, predicate))


# ---------------------------------------------------------------------------
# tsx_fragment -- TEXT-based resolver for TypeScript/JSX source. Not a real
# parser: no TypeScript AST is available in this Python codebase. Locates a
# named exported symbol's APPROXIMATE source region (from its declaration to
# the next top-level `export` keyword, or end of file) and searches only
# within that region for `fragment`. This CANNOT exclude a `//` comment or a
# string literal the way the Python AST resolvers above structurally can --
# a documented blind spot, not a silent one; see the module docstring's
# "Why a new TypeScript/JSX predicate kind exists" section.
# ---------------------------------------------------------------------------

_TSX_SYMBOL_MARKERS: tuple[str, ...] = (
    "export function {symbol}",
    "export const {symbol}",
    "export async function {symbol}",
    "function {symbol}(",
)


def resolve_tsx_fragment(source: str, *, scope: str, fragment: str) -> bool:
    start = -1
    for template in _TSX_SYMBOL_MARKERS:
        marker = template.format(symbol=scope)
        idx = source.find(marker)
        if idx != -1:
            start = idx
            break
    if start == -1:
        return False
    rest = source[start:]
    next_export = rest.find("\nexport ", 1)
    region = rest if next_export == -1 else rest[:next_export]
    return fragment in region


# ---------------------------------------------------------------------------
# The populated registry -- derived from tests/assertion_inventory.py's
# absence entries for the /runs route plus this phase's own STRIDE threat
# register (T-22-53..T-22-57). See SUMMARY.md for the full derivation,
# including why the catch-all-mount and non-HTML-service-route concerns are
# recorded as one target ("SAFETY-03") rather than two.
# ---------------------------------------------------------------------------

EXPECTED_SAFETY_IDS: frozenset[str] = frozenset({"SAFETY-01", "SAFETY-02", "SAFETY-03"})

SAFETY_MUTATION_TARGETS: dict[str, SafetyTarget] = {
    "SAFETY-01": SafetyTarget(
        file="app/routes/templating.py",
        scope=MODULE_SCOPE,
        predicate=SafetyPredicate(
            kind="dict_entry",
            target_name="_JSON_SCRIPT_ESCAPES",
            dict_key="<",
            value_path=r'"\\u003c"',
        ),
        pinning_tests=(
            PinnedAssertion(
                test_file="tests/test_react_page_render.py",
                test_name="test_hostile_business_name_does_not_terminate_island_early",
                assertion_text="'<script>alert(1)</script>' not in response.text",
            ),
        ),
    ),
    "SAFETY-02": SafetyTarget(
        file="app/schemas/runs_list.py",
        scope="RunListRow",
        predicate=SafetyPredicate(
            kind="frozenset_member",
            target_name="EXCLUDED",
            member="source_email_id",
        ),
        pinning_tests=(
            PinnedAssertion(
                test_file="tests/test_react_page_render.py",
                test_name="test_payload_excludes_internal_and_pii_fields",
                assertion_text="key not in row",
            ),
        ),
    ),
    "SAFETY-03": SafetyTarget(
        file="app/main.py",
        scope=MODULE_SCOPE,
        predicate=SafetyPredicate(
            kind="call_count",
            attr_name="mount",
            expected_count=1,
        ),
        pinning_tests=(
            PinnedAssertion(
                test_file="tests/test_route_shadowing.py",
                test_name="test_only_mount_is_static",
                assertion_text="[m.path for m in mounts] == ['/static']",
            ),
            PinnedAssertion(
                test_file="tests/test_no_html_on_service_routes.py",
                test_name="test_service_route_never_answers_html",
                assertion_text="'text/html' not in content_type",
            ),
        ),
    ),
}
