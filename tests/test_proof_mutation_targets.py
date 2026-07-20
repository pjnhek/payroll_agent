"""Anti-rot registry for every falsifying mutation this project's durability proofs
have executed, plus the AST resolver and the assertion resolver that keep the
registry honest against a source tree that keeps changing.

What this guard establishes: that a published mutation still names a REAL,
EXECUTABLE location in live source (a SQL string literal, an assignment, or a
call-site dict value — never a docstring or comment copy of the same text), and
that the specific assertion a mutation is claimed to redden still exists inside an
`ast.Assert` node in the named proof test — never merely as a comment or a
docstring sentence that happens to quote the same words.

What this guard does NOT establish: it does not re-execute any mutation. Running
the mutations live against a real database, observing the red, and reverting
byte-identically is expensive, was already done once per mutation, and its
transcript is the durable evidence a human reads. This module is the cheap,
hermetic, run-on-every-commit half — it proves the evidence still POINTS
somewhere real, not that the somewhere still BEHAVES as claimed. A refactor that
moves the mutated code without changing its behavior reds this guard; a refactor
that changes the code's behavior without moving it is outside what an AST-location
check can see, and is exactly what the (expensive, non-repeated) live execution
already covered once.

Two independent halves, because a guard that stops at "the fragment appears
somewhere in this function" repeats a hole this repository has been burned by
before: a mutation's own target string surviving unchanged inside a DOCSTRING
copy of the same SQL, while the live code the docstring describes had already
drifted. Comments are structurally absent from a parsed AST, so restricting every
resolver to `ast.parse` output — walking to the named function first, then
inspecting only nodes inside that function's subtree, and explicitly excluding the
function's own docstring node from string-literal collection — makes a comment or
docstring copy structurally unable to satisfy either resolver. No resolver in this
module performs a text/substring search over a whole file; every one walks a
parsed tree scoped to one named function.

Targets are modelled as small structured predicates, not bare strings, because one
of this phase's four real mutation targets is not inside any string literal at
all: it is an executable assignment whose value is a subscript expression. A
predicate carries a `kind` discriminator plus that kind's own fields, and three
kinds are implemented:

- `sql_fragment` — a fragment that must appear inside a non-docstring string
  constant somewhere in the named function (the shape both SQL-literal mutations
  in this phase's registry use).
- `assignment` — an `ast.Assign`/`ast.AnnAssign` binding a specific name to a
  value expression of a specific node type and a specific normalized rendering
  (the shape a header-derived identity assignment uses — a plain string scan
  cannot see this at all, because there is no string literal to find).
- `dict_value` — a specific string key inside an `ast.Dict` literal mapped to a
  value expression of a specific node type and a specific normalized rendering
  (the shape a keyword-argument payload built as a dict literal uses — this is
  neither a bare assignment nor a string literal, and needed its own kind rather
  than being force-fit into either of the other two).

Every registry entry below was checked directly against this repository's live
source before being written, not copied from a planning document's prediction —
each mutation's own execution transcript records the diff that was actually
applied and the assertion that actually reddened, and that observation is what
this module encodes.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from scripts.check_proof_inventory import EXPECTED_PROOF_IDS

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

PredicateKind = Literal["sql_fragment", "assignment", "dict_value"]


# ---------------------------------------------------------------------------
# Predicate + result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetPredicate:
    """A structured description of one mutation target's shape.

    Only the fields relevant to `kind` are populated; the others stay `None`.
    Dispatch is by `kind`, through a lookup table — adding a fourth kind means
    adding one more resolver function and one more table entry, not rewriting
    the function-lookup/subtree-restriction walk every kind shares.
    """

    kind: PredicateKind
    # sql_fragment
    fragment: str | None = None
    # assignment / dict_value
    target_name: str | None = None
    dict_key: str | None = None
    value_node_type: type[ast.AST] | None = None
    value_path: str | None = None


@dataclass(frozen=True)
class ResolutionResult:
    """Distinguishes "the named function does not exist" from "the function
    exists but the predicate is unsatisfied" — two different failure shapes a
    caller must be able to tell apart, so a typo'd function name does not read
    as a silently-failed predicate.
    """

    function_found: bool
    predicate_satisfied: bool

    @property
    def resolved(self) -> bool:
        return self.function_found and self.predicate_satisfied


# ---------------------------------------------------------------------------
# Shared AST helpers
# ---------------------------------------------------------------------------


def _normalize_ws(text: str) -> str:
    """Collapse whitespace runs to a single space and strip both ends.

    The SQL string literals this guard resolves live inside triple-quoted,
    multiply-indented Python strings; a harmless reindent of the surrounding
    function must not red this guard, only a change to the SQL's actual
    content should. Without this normalization the guard would fire on pure
    formatting churn, which is how a guard earns being deleted for being
    annoying rather than trusted for being right.
    """
    return " ".join(text.split())


def _normalize_expr(expr_source: str) -> str:
    """Parse `expr_source` as a standalone expression and render it back via
    `ast.unparse`, so two structurally-identical expressions compare equal
    regardless of quote style or incidental spacing in how a predicate's
    `value_path` field happens to be written. This is a structural rendering
    from a real parsed node, never a slice of the original source text — a
    source slice would reintroduce the text-matching weakness this whole
    module exists to avoid.
    """
    node = ast.parse(expr_source, mode="eval").body
    return _normalize_ws(ast.unparse(node))


def _find_function(
    tree: ast.Module, function_name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Locate a `def`/`async def` by name anywhere in the parsed tree. Returns
    `None` when no such function exists, which callers must treat as a
    distinct outcome from "found the function, predicate unsatisfied".
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return node
    return None


def _docstring_node(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.Constant | None:
    """Return the function's own docstring constant node, or `None` if it has
    none. Used to EXCLUDE that one node from string-literal collection — the
    exact node identity, not merely its text, so a live SQL string that
    happens to equal the docstring's own wording (it never does here, but
    nothing about the resolver should assume that) is still found correctly.
    """
    if not fn.body:
        return None
    first = fn.body[0]
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


def _resolve_sql_fragment(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, predicate: TargetPredicate
) -> bool:
    assert predicate.fragment is not None
    docstring_node = _docstring_node(fn)
    target = _normalize_ws(predicate.fragment)
    for node in ast.walk(fn):
        # Comments never reach the AST at all, so excluding them needs no code —
        # this loop structurally cannot see one. The one exclusion that DOES need
        # code is the function's own docstring, which IS a string constant and
        # WOULD otherwise satisfy a fragment that only survives there.
        if node is docstring_node:
            continue
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and target in _normalize_ws(node.value)
        ):
            return True
    return False


def _resolve_assignment(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, predicate: TargetPredicate
) -> bool:
    assert predicate.target_name is not None
    assert predicate.value_node_type is not None
    assert predicate.value_path is not None
    expected = _normalize_expr(predicate.value_path)
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            targets = node.targets
            value: ast.expr | None = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if value is None:
            continue
        if not any(isinstance(t, ast.Name) and t.id == predicate.target_name for t in targets):
            continue
        if not isinstance(value, predicate.value_node_type):
            continue
        if _normalize_ws(ast.unparse(value)) == expected:
            return True
    return False


def _resolve_dict_value(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, predicate: TargetPredicate
) -> bool:
    assert predicate.dict_key is not None
    assert predicate.value_node_type is not None
    assert predicate.value_path is not None
    expected = _normalize_expr(predicate.value_path)
    for node in ast.walk(fn):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                # A `**spread` entry inside the dict literal — no key to match.
                continue
            if not (isinstance(key, ast.Constant) and key.value == predicate.dict_key):
                continue
            if not isinstance(value, predicate.value_node_type):
                continue
            if _normalize_ws(ast.unparse(value)) == expected:
                return True
    return False


# Dispatch table: adding a fourth predicate kind means adding one more resolver
# function above and one more entry here, never touching the function-lookup or
# subtree-restriction walk every kind shares in `resolve_target_in_source`.
_ResolverFn = Callable[[ast.FunctionDef | ast.AsyncFunctionDef, TargetPredicate], bool]
_RESOLVERS: dict[PredicateKind, _ResolverFn] = {
    "sql_fragment": _resolve_sql_fragment,
    "assignment": _resolve_assignment,
    "dict_value": _resolve_dict_value,
}


def resolve_target_in_source(
    source: str, *, function_name: str, predicate: TargetPredicate
) -> ResolutionResult:
    """Resolve `predicate` against `source`, scoped to the named function.

    1. Parse the source.
    2. Locate the `FunctionDef`/`AsyncFunctionDef` named `function_name`. If
       none exists, return a result whose `function_found` is `False` — a
       distinct outcome from "found it, predicate unsatisfied".
    3. Restrict every further check to that function's own subtree via
       `ast.walk(fn)`. Nothing outside it is ever inspected.
    """
    tree = ast.parse(source)
    fn = _find_function(tree, function_name)
    if fn is None:
        return ResolutionResult(function_found=False, predicate_satisfied=False)
    resolver = _RESOLVERS[predicate.kind]
    return ResolutionResult(function_found=True, predicate_satisfied=resolver(fn, predicate))


def assertion_is_asserted_in(source: str, *, function_name: str, assertion_text: str) -> bool:
    """True when `assertion_text` appears inside an `ast.Assert` node's
    condition or message, within the named function's own subtree — never
    anywhere else in the file.

    This is the second, independent half of this module's job, and it must not
    be a text search over the whole file: a `# we assert claimed.attempts == 1`
    comment would satisfy a file-wide substring search while the assertion
    itself had been deleted, which is the exact docstring/comment false
    positive this whole module exists to prevent, recreated one level up.
    Walking to the named function
    by AST first, then collecting only its `ast.Assert` nodes, makes that
    structurally impossible: a comment is invisible to `ast.walk`, and a
    same-text `ast.Assert` in a different function is outside the subtree
    this function ever inspects.
    """
    tree = ast.parse(source)
    fn = _find_function(tree, function_name)
    if fn is None:
        return False
    target = _normalize_ws(assertion_text)
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assert):
            continue
        condition_text = _normalize_ws(ast.unparse(node.test))
        if target in condition_text:
            return True
        if node.msg is not None:
            message_text = _normalize_ws(ast.unparse(node.msg))
            if target in message_text:
                return True
    return False


# ===========================================================================
# Task 1 — synthetic-source proofs of the resolvers above
# ===========================================================================

# --- sql_fragment ------------------------------------------------------


def test_sql_fragment_resolves_live_string_in_named_function() -> None:
    source = (
        "def claim_job():\n"
        "    '''Docstring mentioning attempts = old + 1 but that is prose.'''\n"
        "    sql = '''\n"
        "        UPDATE jobs SET attempts = j.attempts + 1\n"
        "    '''\n"
        "    return sql\n"
    )
    result = resolve_target_in_source(
        source,
        function_name="claim_job",
        predicate=TargetPredicate(kind="sql_fragment", fragment="attempts = j.attempts + 1"),
    )
    assert result.resolved, "a live, non-docstring string literal must resolve"


def test_sql_fragment_does_not_resolve_docstring_only_copy() -> None:
    """The exact trap this guard exists to close: a docstring prose copy of
    the mutated SQL text must NOT satisfy the resolver, even though the text
    is present somewhere in the function.
    """
    source = (
        "def claim_job():\n"
        "    '''The SQL sets attempts = j.attempts + 1 at claim time.'''\n"
        "    sql = 'UPDATE jobs SET state = leased'\n"
        "    return sql\n"
    )
    result = resolve_target_in_source(
        source,
        function_name="claim_job",
        predicate=TargetPredicate(kind="sql_fragment", fragment="attempts = j.attempts + 1"),
    )
    assert not result.predicate_satisfied, (
        "a docstring-only copy of the fragment must not satisfy the resolver — "
        "this is the docstring-copy trap"
    )


def test_sql_fragment_does_not_resolve_comment_only_copy() -> None:
    """A comment can never appear in a parsed AST, so a fragment surviving
    only as a `#` comment must not satisfy the resolver either.
    """
    source = (
        "def claim_job():\n"
        "    # attempts = j.attempts + 1 used to live here\n"
        "    sql = 'UPDATE jobs SET state = leased'\n"
        "    return sql\n"
    )
    result = resolve_target_in_source(
        source,
        function_name="claim_job",
        predicate=TargetPredicate(kind="sql_fragment", fragment="attempts = j.attempts + 1"),
    )
    assert not result.predicate_satisfied, (
        "a comment-only copy of the fragment must not satisfy the resolver — "
        "this is the comment-copy trap"
    )


def test_sql_fragment_does_not_resolve_other_function_copy() -> None:
    source = (
        "def other_function():\n"
        "    sql = 'UPDATE jobs SET attempts = j.attempts + 1'\n"
        "    return sql\n"
        "\n"
        "\n"
        "def claim_job():\n"
        "    return None\n"
    )
    result = resolve_target_in_source(
        source,
        function_name="claim_job",
        predicate=TargetPredicate(kind="sql_fragment", fragment="attempts = j.attempts + 1"),
    )
    assert result.function_found
    assert not result.predicate_satisfied, (
        "a fragment living only in a DIFFERENT function must not resolve"
    )


def test_sql_fragment_missing_function_says_so_distinctly() -> None:
    source = "def some_other_name():\n    return None\n"
    result = resolve_target_in_source(
        source,
        function_name="claim_job",
        predicate=TargetPredicate(kind="sql_fragment", fragment="attempts = j.attempts + 1"),
    )
    assert result.function_found is False
    assert result.predicate_satisfied is False
    assert result.resolved is False


# --- assignment ----------------------------------------------------------


def test_assignment_resolves_matching_assign_subscript() -> None:
    """Models the one real registry target no string-constant scan can see:
    an executable `ast.Assign` whose value is a `Subscript`.
    """
    source = (
        "async def inbound(request):\n"
        "    external_event_id = request.headers['svix-id']\n"
        "    return external_event_id\n"
    )
    result = resolve_target_in_source(
        source,
        function_name="inbound",
        predicate=TargetPredicate(
            kind="assignment",
            target_name="external_event_id",
            value_node_type=ast.Subscript,
            value_path='request.headers["svix-id"]',
        ),
    )
    assert result.resolved, "the real Assign/Subscript shape must resolve"


def test_assignment_does_not_resolve_different_value() -> None:
    """Same variable name, a genuinely different derivation — the predicate is
    about the DERIVATION, not merely the variable being assigned to.
    """
    source = (
        "async def inbound(request):\n"
        "    external_event_id = str(uuid.uuid4())\n"
        "    return external_event_id\n"
    )
    result = resolve_target_in_source(
        source,
        function_name="inbound",
        predicate=TargetPredicate(
            kind="assignment",
            target_name="external_event_id",
            value_node_type=ast.Subscript,
            value_path='request.headers["svix-id"]',
        ),
    )
    assert result.function_found
    assert not result.predicate_satisfied, (
        "a same-name assignment with a different derivation must not resolve"
    )


def test_assignment_does_not_resolve_docstring_or_comment_copy() -> None:
    source = (
        "async def inbound(request):\n"
        "    '''external_event_id = request.headers[\"svix-id\"] is derived here.'''\n"
        "    # external_event_id = request.headers['svix-id']\n"
        "    external_event_id = str(uuid.uuid4())\n"
        "    return external_event_id\n"
    )
    result = resolve_target_in_source(
        source,
        function_name="inbound",
        predicate=TargetPredicate(
            kind="assignment",
            target_name="external_event_id",
            value_node_type=ast.Subscript,
            value_path='request.headers["svix-id"]',
        ),
    )
    assert not result.predicate_satisfied, (
        "a docstring or comment copy of the assignment text must not resolve"
    )


def test_assignment_does_not_resolve_different_target_name() -> None:
    source = (
        "async def inbound(request):\n"
        "    other_id = request.headers['svix-id']\n"
        "    return other_id\n"
    )
    result = resolve_target_in_source(
        source,
        function_name="inbound",
        predicate=TargetPredicate(
            kind="assignment",
            target_name="external_event_id",
            value_node_type=ast.Subscript,
            value_path='request.headers["svix-id"]',
        ),
    )
    assert not result.predicate_satisfied, (
        "an assignment to a DIFFERENT name must not resolve"
    )


def test_assignment_kind_resolves_real_proof02_target_in_live_source() -> None:
    """Required proof that the resolver can see an executable target, not
    only string literals: this is the real PROOF-02 mutation target, read
    from this repository's own live source.
    """
    source = (REPO_ROOT / "app" / "routes" / "webhook.py").read_text(encoding="utf-8")
    result = resolve_target_in_source(
        source,
        function_name="inbound",
        predicate=TargetPredicate(
            kind="assignment",
            target_name="external_event_id",
            value_node_type=ast.Subscript,
            value_path='request.headers["svix-id"]',
        ),
    )
    assert result.resolved, (
        "the assignment-kind resolver must resolve the real Assign/Subscript "
        "target in app/routes/webhook.py — a resolver that cannot see this is "
        "structurally incapable of covering one of the four real proofs"
    )


# --- dict_value ------------------------------------------------------------


def test_dict_value_resolves_matching_key_and_value() -> None:
    """Models the real send-path mutation target: a keyword-argument payload
    built as a dict literal, whose value at a specific string key is neither
    inside a string constant nor bound by a plain assignment — a third,
    distinct executable shape.
    """
    source = (
        "def send_reserved_outbound_snapshot(message_id):\n"
        "    provider.send(params, {'idempotency_key': message_id})\n"
    )
    result = resolve_target_in_source(
        source,
        function_name="send_reserved_outbound_snapshot",
        predicate=TargetPredicate(
            kind="dict_value",
            dict_key="idempotency_key",
            value_node_type=ast.Name,
            value_path="message_id",
        ),
    )
    assert result.resolved, "the real Dict-literal key/value shape must resolve"


def test_dict_value_does_not_resolve_different_value() -> None:
    source = (
        "def send_reserved_outbound_snapshot(message_id):\n"
        "    provider.send(params, {'idempotency_key': str(uuid.uuid4())})\n"
    )
    result = resolve_target_in_source(
        source,
        function_name="send_reserved_outbound_snapshot",
        predicate=TargetPredicate(
            kind="dict_value",
            dict_key="idempotency_key",
            value_node_type=ast.Name,
            value_path="message_id",
        ),
    )
    assert result.function_found
    assert not result.predicate_satisfied, (
        "a freshly-minted value at the same key must not resolve — the "
        "predicate is about the value's derivation, not merely the key"
    )


def test_dict_value_does_not_resolve_docstring_or_comment_copy() -> None:
    source = (
        "def send_reserved_outbound_snapshot(message_id):\n"
        "    '''Sends with {\"idempotency_key\": message_id}.'''\n"
        "    # {'idempotency_key': message_id}\n"
        "    provider.send(params, {'idempotency_key': str(uuid.uuid4())})\n"
    )
    result = resolve_target_in_source(
        source,
        function_name="send_reserved_outbound_snapshot",
        predicate=TargetPredicate(
            kind="dict_value",
            dict_key="idempotency_key",
            value_node_type=ast.Name,
            value_path="message_id",
        ),
    )
    assert not result.predicate_satisfied, (
        "a docstring or comment copy of the dict literal must not resolve"
    )


def test_dict_value_does_not_resolve_different_key() -> None:
    source = (
        "def send_reserved_outbound_snapshot(message_id):\n"
        "    provider.send(params, {'other_key': message_id})\n"
    )
    result = resolve_target_in_source(
        source,
        function_name="send_reserved_outbound_snapshot",
        predicate=TargetPredicate(
            kind="dict_value",
            dict_key="idempotency_key",
            value_node_type=ast.Name,
            value_path="message_id",
        ),
    )
    assert not result.predicate_satisfied, "a DIFFERENT dict key must not resolve"


def test_dict_value_does_not_resolve_other_function() -> None:
    source = (
        "def other_function():\n"
        "    provider.send(params, {'idempotency_key': message_id})\n"
        "\n"
        "\n"
        "def send_reserved_outbound_snapshot(message_id):\n"
        "    return None\n"
    )
    result = resolve_target_in_source(
        source,
        function_name="send_reserved_outbound_snapshot",
        predicate=TargetPredicate(
            kind="dict_value",
            dict_key="idempotency_key",
            value_node_type=ast.Name,
            value_path="message_id",
        ),
    )
    assert result.function_found
    assert not result.predicate_satisfied, (
        "a dict literal living only in a DIFFERENT function must not resolve"
    )


# --- assertion resolver ----------------------------------------------------


def test_assertion_resolves_inside_ast_assert_condition() -> None:
    source = (
        "def test_something():\n"
        "    claimed = claim()\n"
        "    assert claimed.attempts == 1\n"
    )
    assert assertion_is_asserted_in(
        source, function_name="test_something", assertion_text="claimed.attempts == 1"
    )


def test_assertion_does_not_resolve_comment_only_copy() -> None:
    """The review-found correction made executable: a comment stating the
    assertion text must not satisfy the resolver — only a real `ast.Assert`
    node's condition or message may.
    """
    source = (
        "def test_something():\n"
        "    claimed = claim()\n"
        "    # we assert claimed.attempts == 1\n"
        "    assert claimed is not None\n"
    )
    assert not assertion_is_asserted_in(
        source, function_name="test_something", assertion_text="claimed.attempts == 1"
    ), "a comment stating the assertion text must not satisfy the resolver"


def test_assertion_does_not_resolve_docstring_only_copy() -> None:
    source = (
        "def test_something():\n"
        "    '''Asserts claimed.attempts == 1 after the claim.'''\n"
        "    claimed = claim()\n"
        "    assert claimed is not None\n"
    )
    assert not assertion_is_asserted_in(
        source, function_name="test_something", assertion_text="claimed.attempts == 1"
    ), "a docstring stating the assertion text must not satisfy the resolver"


def test_assertion_does_not_resolve_other_function() -> None:
    source = (
        "def test_unrelated():\n"
        "    claimed = claim()\n"
        "    assert claimed.attempts == 1\n"
        "\n"
        "\n"
        "def test_something():\n"
        "    assert claimed is not None\n"
    )
    assert not assertion_is_asserted_in(
        source, function_name="test_something", assertion_text="claimed.attempts == 1"
    ), "the identical assertion living only in a DIFFERENT function must not resolve"


def test_assertion_resolves_when_only_in_message() -> None:
    """The assertion text may live in the message rather than the condition —
    both must be checked, not only the condition.
    """
    source = (
        "def test_something():\n"
        "    reclaimed = reclaim()\n"
        "    assert reclaimed is not None, 'worker B must have reclaimed the expired lease'\n"
    )
    assert assertion_is_asserted_in(
        source,
        function_name="test_something",
        assertion_text="worker B must have reclaimed the expired lease",
    )


# ===========================================================================
# Task 2 — the populated registry, resolved against live source
# ===========================================================================


@dataclass(frozen=True)
class RegistryEntry:
    file: str
    function_name: str
    predicate: TargetPredicate
    proof_test_file: str
    proof_test_name: str
    assertion_text: str


# Populated from each proof's own execution transcript — the mutation diff that
# was actually applied and the assertion that actually reddened — not from any
# planning document's prediction. Two entries (the first and the last) share a
# file and an enclosing function; their predicates are deliberately distinct
# fragments of that function's SQL, because sharing one target would mean one of
# the two proofs was never independently falsified.
MUTATION_TARGETS: dict[str, RegistryEntry] = {
    "PROOF-01": RegistryEntry(
        file="app/db/repo/jobs.py",
        function_name="claim_job",
        predicate=TargetPredicate(
            kind="sql_fragment",
            fragment="attempts = j.attempts + 1",
        ),
        proof_test_file="tests/test_queue_durability.py",
        proof_test_name="test_retrigger_survives_worker_crash_mid_lease",
        assertion_text="claimed.attempts == 1",
    ),
    "PROOF-02": RegistryEntry(
        file="app/routes/webhook.py",
        function_name="inbound",
        predicate=TargetPredicate(
            kind="assignment",
            target_name="external_event_id",
            value_node_type=ast.Subscript,
            value_path='request.headers["svix-id"]',
        ),
        proof_test_file="tests/test_webhook_dedup_race.py",
        proof_test_name="test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run",
        assertion_text="{result['status'] for result in results} == {'accepted', 'duplicate'}",
    ),
    "PROOF-03": RegistryEntry(
        file="app/email/gateway.py",
        function_name="send_reserved_outbound_snapshot",
        predicate=TargetPredicate(
            kind="dict_value",
            dict_key="idempotency_key",
            value_node_type=ast.Name,
            value_path="message_id",
        ),
        proof_test_file="tests/test_send_idempotency.py",
        proof_test_name=(
            "test_crash_between_provider_accept_and_local_sent_commit_sends_no_second_email"
        ),
        assertion_text="provider_calls[0]['idempotency_key'] == captured_message_id",
    ),
    "PROOF-04": RegistryEntry(
        file="app/db/repo/jobs.py",
        function_name="claim_job",
        predicate=TargetPredicate(
            kind="sql_fragment",
            fragment="OR (c.state = 'leased' AND c.leased_until < now())",
        ),
        proof_test_file="tests/test_queue_durability.py",
        proof_test_name=(
            "test_expired_lease_is_reclaimed_by_a_second_worker_and_zombie_is_fenced_on_both_writes"
        ),
        assertion_text="reclaimed is not None",
    ),
}


def test_registry_covers_expected_ids_exactly() -> None:
    assert sorted(MUTATION_TARGETS) == sorted(EXPECTED_PROOF_IDS), (
        "the registry's key set must equal the canonical proof-id set exactly — "
        "no missing id, no extra id"
    )


def test_registry_targets_are_mutually_distinct() -> None:
    triples = [
        (entry.file, entry.function_name, entry.predicate) for entry in MUTATION_TARGETS.values()
    ]
    assert len(triples) == len(set(triples)), (
        "two proofs sharing one (file, function, predicate) triple would mean "
        "one of them was never independently falsified"
    )


def test_every_registry_entry_resolves_against_live_source() -> None:
    """The guard's real job: a refactor that moves, rewrites, or repoints a
    registered target must red this test, so the published evidence gets
    updated instead of quietly becoming fiction.
    """
    for proof_id, entry in sorted(MUTATION_TARGETS.items()):
        source = (REPO_ROOT / entry.file).read_text(encoding="utf-8")
        result = resolve_target_in_source(
            source, function_name=entry.function_name, predicate=entry.predicate
        )
        assert result.resolved, (
            f"{proof_id}'s target does not resolve against live "
            f"{entry.file}::{entry.function_name} — function_found="
            f"{result.function_found}, predicate_satisfied={result.predicate_satisfied}"
        )


def test_every_registry_entrys_named_assertion_is_genuinely_asserted() -> None:
    """Uses the assertion resolver, never a substring search over the proof
    test's file — a comment quoting the assertion text must not satisfy this.
    """
    for proof_id, entry in sorted(MUTATION_TARGETS.items()):
        source = (REPO_ROOT / entry.proof_test_file).read_text(encoding="utf-8")
        assert assertion_is_asserted_in(
            source, function_name=entry.proof_test_name, assertion_text=entry.assertion_text
        ), (
            f"{proof_id}'s named assertion {entry.assertion_text!r} is not asserted "
            f"inside an ast.Assert node in {entry.proof_test_file}::{entry.proof_test_name}"
        )


def test_every_registry_entrys_proof_node_id_is_real() -> None:
    for proof_id, entry in sorted(MUTATION_TARGETS.items()):
        test_file_path = REPO_ROOT / entry.proof_test_file
        assert test_file_path.is_file(), f"{proof_id}'s proof_test_file does not exist"
        source = test_file_path.read_text(encoding="utf-8")
        fn = _find_function(ast.parse(source), entry.proof_test_name)
        assert fn is not None, (
            f"{proof_id}'s proof_test_name {entry.proof_test_name!r} does not resolve to "
            f"a real test function in {entry.proof_test_file} — the registry may be "
            "pointing at a renamed test"
        )


def test_negative_control_sql_fragment_rejects_absent_fragment_on_live_source() -> None:
    source = (REPO_ROOT / "app" / "db" / "repo" / "jobs.py").read_text(encoding="utf-8")
    result = resolve_target_in_source(
        source,
        function_name="claim_job",
        predicate=TargetPredicate(
            kind="sql_fragment", fragment="attempts = j.attempts + 999999"
        ),
    )
    assert result.function_found
    assert not result.predicate_satisfied, (
        "a deliberately absent fragment must be rejected against the real repository"
    )


def test_negative_control_assignment_rejects_wrong_value_path_on_live_source() -> None:
    source = (REPO_ROOT / "app" / "routes" / "webhook.py").read_text(encoding="utf-8")
    result = resolve_target_in_source(
        source,
        function_name="inbound",
        predicate=TargetPredicate(
            kind="assignment",
            target_name="external_event_id",
            value_node_type=ast.Subscript,
            value_path='request.headers["definitely-not-the-real-key"]',
        ),
    )
    assert result.function_found
    assert not result.predicate_satisfied, (
        "the real target name with a wrong value path must be rejected against "
        "the real repository"
    )


def test_negative_control_dict_value_rejects_wrong_value_path_on_live_source() -> None:
    source = (REPO_ROOT / "app" / "email" / "gateway.py").read_text(encoding="utf-8")
    result = resolve_target_in_source(
        source,
        function_name="send_reserved_outbound_snapshot",
        predicate=TargetPredicate(
            kind="dict_value",
            dict_key="idempotency_key",
            value_node_type=ast.Name,
            value_path="definitely_not_the_real_variable",
        ),
    )
    assert result.function_found
    assert not result.predicate_satisfied, (
        "the real dict key with a wrong value path must be rejected against "
        "the real repository"
    )


def test_negative_control_assertion_resolver_rejects_absent_text_on_live_source() -> None:
    source = (REPO_ROOT / "tests" / "test_queue_durability.py").read_text(encoding="utf-8")
    assert not assertion_is_asserted_in(
        source,
        function_name="test_retrigger_survives_worker_crash_mid_lease",
        assertion_text="claimed.attempts == 999999",
    ), "a plausible-but-absent assertion text must be rejected against the real proof source"


def test_registry_uses_the_assignment_predicate_kind_at_least_once() -> None:
    """Pins the correction that an earlier resolver draft could not make: if a
    future edit quietly downgraded the executable-assignment target back to a
    string-fragment predicate, the resolver would once again be structurally
    unable to see its real target, and this test reds.
    """
    kinds = {entry.predicate.kind for entry in MUTATION_TARGETS.values()}
    assert "assignment" in kinds


def test_registry_uses_the_dict_value_predicate_kind_at_least_once() -> None:
    """The send-path target is neither a string literal nor a plain
    assignment; it needed its own kind. This pins that a future edit cannot
    quietly force-fit it back into one of the other two kinds, which would
    anchor the published evidence to something that is not the real target.
    """
    kinds = {entry.predicate.kind for entry in MUTATION_TARGETS.values()}
    assert "dict_value" in kinds
