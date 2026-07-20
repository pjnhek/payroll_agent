---
phase: 21-durability-proofs-ops-view
plan: 10
subsystem: testing
tags: [ast-guard, anti-rot, mutation-registry, pytest, durability-proof]

requires:
  - phase: 21-durability-proofs-ops-view
    provides: "21-03/21-04/21-05/21-08's executed, evidenced falsifying mutations for PROOF-01..04, each SUMMARY recording the exact mutation diff and the observed red assertion"
provides:
  - "MUTATION_TARGETS — one entry per PROOF-01..04, each carrying a structured AST predicate (kind + fields), verified to resolve against live source, not copied from a planning prediction"
  - "resolve_target_in_source() — a pure AST resolver dispatching over three predicate kinds (sql_fragment, assignment, dict_value), scoped to one named function's subtree, structurally blind to comments and excluding the function's own docstring node"
  - "assertion_is_asserted_in() — a pure AST resolver requiring a named failing assertion inside an ast.Assert condition or message within one named test function, never a whole-file text search"
  - "A third predicate kind (dict_value) beyond the plan's original two, needed because PROOF-03's real target is a dict-literal value inside a call argument — neither a bare assignment nor a SQL string literal"
affects: [21-11]

tech-stack:
  added: []
  patterns:
    - "AST-predicate dispatch table (kind -> resolver function) so a fourth predicate kind can be added without touching the shared function-lookup/subtree-restriction walk, mirroring tests/test_bound01_private_imports.py's detector-plus-synthetic-fixture pairing"
    - "ast.unparse() used as the structural normalizer for both value-expression comparison (assignment/dict_value kinds) and whitespace-insensitive assertion-text matching, instead of any source-text slicing"

key-files:
  created:
    - tests/test_proof_mutation_targets.py
  modified: []

key-decisions:
  - "Added a third predicate kind, dict_value, not present in the plan's original two-kind design. Verifying PROOF-03's mutation against live app/email/gateway.py showed its target is resend.Emails.send(send_params, {\"idempotency_key\": message_id}) — a dict-literal value passed as a call argument, which is neither an ast.Assign/AnnAssign (the assignment kind) nor a string literal (the sql_fragment kind). Force-fitting it into either would have anchored the registry to a node that is not the real mutation target, defeating the guard's own purpose. The resolver's dispatch-table design (stated goal: a third kind addable without rewriting the walker) accommodated this without structural rework."
  - "Assertion text registered per entry is the bare condition expression (e.g. \"claimed.attempts == 1\", \"reclaimed is not None\"), not the full assert statement text, so it matches directly against ast.unparse(node.test) — the assertion resolver also checks node.msg separately (proven by test_assertion_resolves_when_only_in_message), covering PROOF-04's assertion message form as an alternate resolution path even though the registry entry uses the condition."
  - "Registered assertion_text/value_path strings were derived by running ast.unparse() against the exact live condition/expression source, not typed from memory, so registry comparisons match the resolver's own normalization (single-quote string rendering) exactly — verified directly in-session with a throwaway ast.parse/unparse script before writing the registry."

requirements-completed: [PROOF-01, PROOF-02, PROOF-03, PROOF-04]

coverage:
  - id: D1
    description: "resolve_target_in_source() resolves sql_fragment, assignment, and dict_value predicates against a named function's AST subtree, proven to reject docstring-only and comment-only copies for every kind, and to distinguish 'function not found' from 'predicate unsatisfied'"
    requirement: PROOF-01
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_proof_mutation_targets.py -v -> 31 passed (21 synthetic-source resolver tests spanning all three kinds plus the assertion resolver, 4 negative controls, 2 kind-coverage tests, plus the 4 live-registry tests)"
        status: pass
    human_judgment: false
  - id: D2
    description: "assertion_is_asserted_in() requires the named assertion text inside an ast.Assert node's condition or message within the named test function only — a comment or docstring copy of the text, or the same text inside a different function, does not satisfy it"
    requirement: PROOF-02
    verification:
      - kind: unit
        ref: "test_assertion_does_not_resolve_comment_only_copy, test_assertion_does_not_resolve_docstring_only_copy, test_assertion_does_not_resolve_other_function, test_assertion_resolves_when_only_in_message -> all pass"
        status: pass
    human_judgment: false
  - id: D3
    description: "MUTATION_TARGETS carries exactly the four canonical proof ids, each entry's predicate resolves against its real source file (including PROOF-02's assignment/Subscript target and PROOF-03's dict_value target), and no two entries share a (file, function, predicate) triple"
    requirement: PROOF-03
    verification:
      - kind: unit
        ref: "test_registry_covers_expected_ids_exactly, test_registry_targets_are_mutually_distinct, test_every_registry_entry_resolves_against_live_source -> all pass"
        status: pass
    human_judgment: false
  - id: D4
    description: "The guard reds on a synthetic mis-targeted mutation and passes on the conforming real repository — both halves demonstrated live in this session, not merely asserted"
    requirement: PROOF-04
    verification:
      - kind: integration
        ref: "Live red-proof: temporarily reverted claim_job's attempts increment in app/db/repo/jobs.py, ran test_every_registry_entry_resolves_against_live_source, observed it FAIL naming 'PROOF-01's target does not resolve', then git checkout -- app/db/repo/jobs.py (git diff --stat empty), re-ran green"
        status: pass
      - kind: unit
        ref: "uv run pytest tests/test_proof_mutation_targets.py tests/test_proof_inventory.py tests/test_queue_config.py -v -> 48 passed"
        status: pass
    human_judgment: false

duration: ~35min
completed: 2026-07-20
status: complete
---

# Phase 21 Plan 10: Anti-Rot Mutation-Target Registry Summary

**Built an AST-predicate resolver and a scoped assertion resolver — three predicate kinds (sql_fragment, assignment, and a newly-added dict_value for PROOF-03's dict-literal target), a populated MUTATION_TARGETS registry for all four durability proofs verified against live source, and a live red-proof/green-proof demonstration run in this session, not merely asserted from inspection.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 2 of 2 complete (implemented as a single coherent file/commit — the resolver and the registry share the same module and were built together)
- **Files modified:** 1 (`tests/test_proof_mutation_targets.py`, created)

## Accomplishments

- Built `resolve_target_in_source()`, a pure AST resolver dispatching over a `kind` discriminator to one of three resolver functions, each restricted to the named function's own AST subtree (`ast.walk(fn)`), with comments structurally invisible to every path and the function's own docstring node explicitly excluded from string-literal collection.
- Implemented `sql_fragment` (whitespace-normalized containment inside non-docstring string constants — PROOF-01's attempts increment and PROOF-04's expired-lease disjunct, both inside `claim_job`'s SQL) and `assignment` (`ast.Assign`/`ast.AnnAssign` matched by target name, value node type, and a normalized `ast.unparse()`-rendered value path — PROOF-02's `external_event_id = request.headers["svix-id"]`, an executable `Assign`/`Subscript` no string scan can see).
- **Added a third predicate kind, `dict_value`**, not in the plan's original design. Reading PROOF-03's live mutation target in `app/email/gateway.py` (`resend.Emails.send(send_params, {"idempotency_key": message_id})`) showed it is a dict-literal value inside a call argument — neither a string literal nor a plain assignment. `dict_value` walks `ast.Dict` nodes for a matching string key and a value structurally equal (via the same `ast.unparse()` normalization) to the declared value path.
- Built `assertion_is_asserted_in()`, scoped to `ast.Assert` nodes inside one named test function, checking both the condition and the message — never a substring search over the file. Proved it rejects a comment copy, a docstring copy, and the identical assertion living only in a different function, and resolves when the target text appears only in the message (PROOF-04's shape).
- Populated `MUTATION_TARGETS` from each of the four proofs' own execution transcripts — the mutation diff actually applied and the assertion that actually reddened — not from any plan's prediction. Verified every registry field (function name, exact fragment/value-path text, assertion text) directly against the live source and test files, using a throwaway `ast.parse`/`ast.unparse` script to derive the exact normalized rendering before writing the registry, rather than typing expected strings from memory.
- Proved both required properties on live source: `test_every_registry_entry_resolves_against_live_source` (all four entries resolve against real `app/` files, including PROOF-02's `assignment` and PROOF-03's `dict_value` targets) and `test_every_registry_entrys_named_assertion_is_genuinely_asserted` (every entry's assertion text resolves through the assertion resolver against the real proof test file).
- Added four negative-control tests against live source (one per predicate kind plus the assertion resolver) confirming the guard can still say no when pointed at the real repository, not only at synthetic fixtures.
- Added two predicate-kind-coverage tests (`assignment` and `dict_value` each used at least once) so a future edit cannot quietly downgrade either executable target back to a string-fragment predicate without reddening a test.
- **Live red-proof, demonstrated in this session:** temporarily reverted `claim_job`'s attempts increment in `app/db/repo/jobs.py` (`attempts     = j.attempts + 1,` -> `attempts     = j.attempts,`), ran `test_every_registry_entry_resolves_against_live_source`, observed it FAIL naming `PROOF-01's target does not resolve against live app/db/repo/jobs.py::claim_job`, then reverted via `git checkout -- app/db/repo/jobs.py` (`git diff --stat` empty afterward) and re-ran green.

## Task Commits

Both plan tasks (build the resolver + synthetic proofs, then populate and prove the registry) were implemented and verified together as one coherent module, committed once:

1. **Task 1 + Task 2: Build the AST resolver/assertion resolver and populate+prove the registry** - `7ad10e8` (feat)

## Files Created/Modified

- `tests/test_proof_mutation_targets.py` (created) - `TargetPredicate`/`ResolutionResult`/`RegistryEntry` dataclasses; `resolve_target_in_source()` dispatching over `sql_fragment`/`assignment`/`dict_value`; `assertion_is_asserted_in()`; 21 synthetic-source resolver/assertion tests; the populated `MUTATION_TARGETS` registry; 10 registry-level tests (coverage, uniqueness, live-source resolution, live-source assertion resolution, node-id reality, 4 negative controls, 2 kind-coverage tests).

## Decisions Made

- **Third predicate kind added (`dict_value`).** See `key-decisions` in frontmatter. This is a correction found by verifying the plan's assumption against live source, in the same spirit as the two corrections the plan's own objective already documents (the resolver needing to see executable targets, and the assertion check needing to be AST-scoped) — a third real mutation target this phase executed did not fit either of the plan's original two kinds, so a third was added rather than force-fitting.
- **Assertion text registered as the bare condition/message expression**, matched via `ast.unparse()` normalization derived from the live source rather than typed from memory — confirmed with a throwaway interpreter session before writing the registry (pasted output below).
- **Both tasks landed in one commit.** The resolver and the registry share one file and were designed together (the registry's shape depends directly on which predicate kinds the resolver supports), so splitting them into two commits would have produced an intermediate commit whose registry either didn't exist yet or referenced a resolver kind not yet implemented — no genuine intermediate stable state existed to commit separately.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Added a third predicate kind (`dict_value`) not specified in the plan**
- **Found during:** Verifying PROOF-03's mutation target against live `app/email/gateway.py` before writing the registry entry, per this plan's own explicit instruction ("verify each against live source before registering it... rather than trusting this list").
- **Issue:** The plan specified only two predicate kinds (`sql_fragment`, `assignment`) and predicted PROOF-03 "if it lands on a SQL literal" would use `sql_fragment`. The real, live mutation target — confirmed via `grep -n` and direct source reading — is `resend.Emails.send(send_params, {"idempotency_key": message_id})`: a dict-literal value passed as a call argument. This is not inside any string literal (ruling out `sql_fragment`) and is not an `ast.Assign`/`ast.AnnAssign` (ruling out `assignment`). Registering it under either kind would have required either fabricating a nearby string fragment (anchoring the published evidence to something that is not the mutation target — exactly the failure mode the plan's own PROOF-02 correction warned against) or silently dropping PROOF-03 from the registry.
- **Fix:** Implemented a third predicate kind, `dict_value`, matching a specific string key inside an `ast.Dict` literal to a value expression of a specific node type and normalized rendering. Added it to the dispatch table (no changes needed to the shared function-lookup/subtree-restriction walk, confirming the plan's own stated design goal — "a third kind can be added later without rewriting the walker" — held in practice) and gave it the same five-test treatment (resolves, wrong-value rejected, docstring/comment-copy rejected, wrong-key rejected, other-function rejected) as the `assignment` kind, plus a dedicated live-source negative control and a kind-coverage test.
- **Files modified:** `tests/test_proof_mutation_targets.py` (this is the only file this plan modifies; the fix landed inside the plan's own single task, not as a separate change).
- **Verification:** `uv run pytest tests/test_proof_mutation_targets.py -v` — 31 passed, including `test_dict_value_resolves_matching_key_and_value` against a synthetic fixture and `test_every_registry_entry_resolves_against_live_source` resolving PROOF-03's real target in `app/email/gateway.py`.
- **Committed in:** `7ad10e8`

---

**Total deviations:** 1 auto-fixed (a missing predicate kind, found by verifying the plan's assumption against live source as the plan itself instructed). No scope creep — the addition stayed inside this plan's one declared file and directly served the plan's own stated goal (every registered target must be a real, resolvable AST node, not a force-fit).

## Issues Encountered

None blocking. One `ruff` finding (`SIM102`, nested-if that should combine with `and`) surfaced on the first pass through `_resolve_sql_fragment` and was fixed before committing. One comment-provenance-guard violation (a decision id cited by name inside a docstring) was caught by `tests/test_comment_provenance_guard.py` before committing and rewritten in prose describing the constraint instead of citing the decision id.

## Ast.unparse() derivation check (pasted, used to write the registry's exact strings)

```
$ uv run python3 -c "
import ast
srcs = [
    'assert claimed.attempts == 1',
    'assert {result[\"status\"] for result in results} == {\"accepted\", \"duplicate\"}',
    'assert provider_calls[0][\"idempotency_key\"] == captured_message_id',
    'assert reclaimed is not None, \"worker B must have reclaimed the expired lease\"',
    'external_event_id = request.headers[\"svix-id\"]',
]
for s in srcs:
    tree = ast.parse(s)
    stmt = tree.body[0]
    if isinstance(stmt, ast.Assert):
        print('TEST:', ast.unparse(stmt.test))
        if stmt.msg:
            print('MSG:', ast.unparse(stmt.msg))
    else:
        print('EXPR:', ast.unparse(stmt))
"
TEST: claimed.attempts == 1
TEST: {result['status'] for result in results} == {'accepted', 'duplicate'}
TEST: provider_calls[0]['idempotency_key'] == captured_message_id
TEST: reclaimed is not None
MSG: 'worker B must have reclaimed the expired lease'
EXPR: external_event_id = request.headers['svix-id']
```

## Live Red-Proof / Green-Proof Demonstration (both guard halves, run this session)

**Red half** — a registered mutation target moved/rewritten reds the guard, naming the target:

```
$ python3 -c "
import pathlib
p = pathlib.Path('app/db/repo/jobs.py')
s = p.read_text()
old = 'attempts     = j.attempts + 1,'
new = 'attempts     = j.attempts,'
assert s.count(old) == 1
p.write_text(s.replace(old, new))
"
$ git diff --stat app/db/repo/jobs.py
 app/db/repo/jobs.py | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)

$ env -u DATABASE_URL uv run pytest tests/test_proof_mutation_targets.py::test_every_registry_entry_resolves_against_live_source -v
FAILED tests/test_proof_mutation_targets.py::test_every_registry_entry_resolves_against_live_source
AssertionError: PROOF-01's target does not resolve against live app/db/repo/jobs.py::claim_job — function_found=True, predicate_satisfied=False

$ git checkout -- app/db/repo/jobs.py
$ git diff --stat app/db/repo/jobs.py
(no output — byte-identical revert)
```

**Green half** — silent on the conforming tree and on docstring/comment near-misses:

```
$ env -u DATABASE_URL uv run pytest tests/test_proof_mutation_targets.py -q
31 passed in 0.17s
```
(includes `test_sql_fragment_does_not_resolve_docstring_only_copy`, `test_sql_fragment_does_not_resolve_comment_only_copy`, `test_assignment_does_not_resolve_docstring_or_comment_copy`, `test_dict_value_does_not_resolve_docstring_or_comment_copy`, `test_assertion_does_not_resolve_comment_only_copy`, `test_assertion_does_not_resolve_docstring_only_copy` — every near-miss shape proven silent.)

## Full-Suite Verification (post-plan, confirms no regression)

- `env -u DATABASE_URL uv run pytest -q` (hermetic) → **1282 passed, 105 skipped** (baseline 1251 passed, 105 skipped + this plan's 31 new hermetic-passing tests, 0 regression).
- `uv run pytest tests/ -m proof --collect-only -q` → **4 node ids** (PROOF-01..04) — this module added none, as required.
- `env -u DATABASE_URL uv run pytest tests/ -m "not integration and not live_llm" -q` → **1281 passed, 1 skipped, 105 deselected** — green.
- `uv run pytest tests/test_proof_mutation_targets.py tests/test_proof_inventory.py tests/test_queue_config.py -v` → **48 passed**.
- `uv run python scripts/check_proof_inventory.py` → exit 0.
- `uv run ruff check .` → All checks passed.
- `uv run mypy --strict app` → Success: no issues found in 74 source files (unchanged — this plan touches no `app/` file).
- `git status --porcelain app/` → empty.

## User Setup Required

None — no external service configuration required. This guard is fully hermetic (no `DATABASE_URL` needed).

## Next Phase Readiness

- `MUTATION_TARGETS` (four entries, each with `file`, `function_name`, `predicate`, `proof_test_file`, `proof_test_name`, `assertion_text`) is ready for plan 21-11 to publish in prose form — plan 21-11 must not restate the entries differently from what is registered here.
- The registry and its resolvers are the machine-checkable half of what plan 21-11's document publishes; a future refactor that moves, rewrites, or repoints any of the four registered targets will red `test_every_registry_entry_resolves_against_live_source` or `test_every_registry_entrys_named_assertion_is_genuinely_asserted`, naming the specific proof id affected.

## Self-Check: PASSED

- FOUND: tests/test_proof_mutation_targets.py
- FOUND: commit 7ad10e8

---
*Phase: 21-durability-proofs-ops-view*
*Completed: 2026-07-20*
