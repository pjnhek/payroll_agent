---
phase: 22-frontend-foundation-runs-list
plan: 01
subsystem: testing
tags: [ast, pytest, ci, guard, registry, completeness-gate]

requires: []
provides:
  - "tests/assertion_inventory.py: the GUARD-01 machine registry (163 classified `.text` assertions, 19 file-scope notes)"
  - "tests/test_inventory_completeness.py: the AST completeness guard, 7 tests, demonstrated red and reverted"
  - "scripts/render_assertion_inventory.py + docs/ASSERTION-INVENTORY.md: the generated, --check-staled view"
  - ".github/workflows/ci.yml: two new lint-job steps enforcing GUARD-01 (view staleness + conversion ordering)"
affects: [22-02, 22-03, 22-04, 22-05, 22-06, 22-07, 22-08, 22-09, 22-10, 22-11, 22-12, 23-conversion-phase, 24-conversion-phase]

actuals:
  tokens: 29192
  tasks: 3
  commits: 3

tech-stack:
  added: []
  patterns:
    - "AST-walk completeness registry (copied from tests/test_proof_mutation_targets.py / scripts/check_proof_inventory.py): a machine dict keyed by {module_stem}:{line}:{col_offset}, cross-checked in both directions against a fresh, independent ast.Compare walk"
    - "Generated-artifact staleness gate (copied from eval/run_eval.py's --check): regenerate in memory, diff against the committed file, exit 1 with a unified diff on mismatch"

key-files:
  created:
    - tests/assertion_inventory.py
    - tests/test_inventory_completeness.py
    - scripts/render_assertion_inventory.py
    - docs/ASSERTION-INVENTORY.md
  modified:
    - .github/workflows/ci.yml

key-decisions:
  - "route/layer classification traced each assertion's enclosing test function back to its own client.get()/client.post() call via AST (not guessed from file name or a substring inside the assertion's own message) — this caught 5 false positives in tests/test_ops_route.py where a naive whole-function text scan would have misattributed a /runs/{run_id} link's HREF TEXT (asserted inside an /ops response) as a request to /runs/{run_id}"
  - "layer=JSON_ISLAND vs REACT_DOM split on /runs entries by whether the guarded content originates in a RunListRow/RunStatusPoll DTO field (JSON_ISLAND — will live in the __INITIAL_DATA__ blob, correct rewrite is a positive exact-shape JSON check) or is static JSX markup with no data backing (REACT_DOM — genuinely vacuous after conversion, e.g. the empty-state copy \"No payroll runs yet\")"
  - "FILE_SCOPE_NOTES grew from 17 to 19 files during Task 2/3: the two new GUARD-01 infrastructure files (tests/assertion_inventory.py, tests/test_inventory_completeness.py) themselves contain the literal substring `.text` in their own docstrings/identifiers, so the plan's own scope rule (every tests/ file containing `.text` gets a note) applies self-referentially; both got zero-affected notes explaining the false-positive substring match"

requirements-completed: [GUARD-01]

coverage:
  - id: D1
    description: "Machine registry classifies every discovered .text comparison across all 14 real-hit test files by route, presence/absence, and post-conversion layer, with explicit zero-affected notes for the other 5"
    requirement: "GUARD-01"
    verification:
      - kind: unit
        ref: "tests/test_inventory_completeness.py#test_every_discovered_assertion_has_a_registry_entry"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_completeness.py#test_no_registry_entry_is_stale"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_completeness.py#test_every_entry_has_a_layer_and_route_classification"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_completeness.py#test_every_entry_source_text_matches_live_source"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_completeness.py#test_every_text_bearing_file_is_scoped"
        status: pass
    human_judgment: false
  - id: D2
    description: "AST completeness guard is demonstrated red (an unclassified .text assertion added to live source fails the guard) and reverts byte-identically"
    requirement: "GUARD-01"
    verification:
      - kind: unit
        ref: "tests/test_inventory_completeness.py (full 7-test module, run against a deliberately mutated tests/test_dashboard.py, captured RED, then `git checkout --` reverted; git diff --stat produced no output)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Generated markdown view is deterministic, --check-gated for staleness, and the CI ordering gate blocks a frontend/src file from landing before the registry exists"
    requirement: "GUARD-01"
    verification:
      - kind: unit
        ref: "scripts/render_assertion_inventory.py --check (run twice in a row against the committed docs/ASSERTION-INVENTORY.md; also run against a deliberately mutated AssertionEntry.route, captured the exit-1 unified diff, then reverted byte-identically)"
        status: pass
      - kind: other
        ref: ".github/workflows/ci.yml lint job: 'Assertion inventory precedes conversion (GUARD-01 gate)' step, red-proofed locally against a simulated frontend/src/dummy.tsx with no tests/assertion_inventory.py present (exit 1), and green against the current repo state (exit 0)"
        status: pass
    human_judgment: false

duration: ~55min
completed: 2026-08-17
status: complete
---

# Phase 22 Plan 1: Assertion Registry + Completeness Guard + CI Gate Summary

**GUARD-01's baseline: an AST-derived, machine-checked registry of all 163 `.text` comparisons across 14 test files (route + presence/absence + post-conversion layer each), an independent AST completeness guard proven red and reverted, and two new CI steps — a generated-view staleness check and a conversion-ordering gate — wired into the existing `lint` job.**

## Performance

- **Duration:** ~55 min
- **Tasks:** 3 (all completed)
- **Files modified:** 5 (4 new, 1 modified)

## Accomplishments

- **Task 1 — the registry.** `tests/assertion_inventory.py` declares `AssertionEntry` (a frozen dataclass with `file`, `line`, `col_offset`, `source_text`, `route`, `assertion_class`, `layer`, `replaced_by`), `AssertionClass`/`AssertionLayer` (`enum.StrEnum`, matching the repo's existing `IngestOutcome`/`PipelineOutcome`/`JobKind` convention rather than the `class X(str, Enum)` shape ruff's `UP042` flags), `ASSERTION_INVENTORY` (163 entries, keyed `{module_stem}:{line}:{col_offset}`), and `FILE_SCOPE_NOTES` (19 files, each with a written reason).
- **Task 2 — the guard.** `tests/test_inventory_completeness.py` walks `tests/` independently with its own `ast.Compare`/`.text`-attribute scan and cross-checks the discovered set against the registry in both directions, plus source-text drift, route/layer presence, file-scope coverage, read-only determinism, and position-uniqueness — 7 tests, all copied-shape from `tests/test_proof_mutation_targets.py`'s completeness-gate idiom. Demonstrated red by adding one unclassified `.text` assertion to `tests/test_dashboard.py` and reverting byte-identically (transcript below).
- **Task 3 — the view and the CI gate.** `scripts/render_assertion_inventory.py` regenerates `docs/ASSERTION-INVENTORY.md` (baseline counts, per-layer/per-route/per-file breakdowns, the full classified listing, and the zero-affected-files section) as pure derived output — nothing hand-pinned. `--check` mirrors `eval/run_eval.py`'s regenerate-and-diff regression-gate contract. Two new steps land in `.github/workflows/ci.yml`'s existing `lint` job (inheriting its `pull_request` trigger, `concurrency` group, and `permissions` for free): "Assertion inventory view is current" and "Assertion inventory precedes conversion (GUARD-01 gate)" — the latter red-proofed locally against a simulated `frontend/src` with no registry present.

## Re-derived baseline (do not trust `REQUIREMENTS.md`'s prior figures, per plan instruction)

- `grep -rl "\.text" tests/ | wc -l` = **17** at Task 1 completion time (before the two new guard files existed); **19** after Tasks 2-3 added `tests/assertion_inventory.py` and `tests/test_inventory_completeness.py`, both of which contain the literal substring `.text` in their own docstrings/identifiers with zero real comparisons. Both got explicit `FILE_SCOPE_NOTES` zero-affected entries.
- A live AST walk over every `.py` file under `tests/` found **163** real `.text` comparisons (`ast.Compare` nodes), spread across exactly **14** files — 3 more files (`conftest.py`, `test_clarify_round_hours_safety.py`, `test_gateway.py`) match the substring scan but carry zero real comparisons (fake-response test-double attribute assignments, or a `.text` read into an intermediate variable compared several lines later).
- Split: **94 presence / 69 absence**. Layer: **122 UNCONVERTED / 31 JINJA_SHELL / 8 JSON_ISLAND / 2 REACT_DOM**. Route: `/runs/{run_id}` 89, `/ops` 23, `/runs` 16, `/runs/{run_id}/delivery-review/email` 9, `none` (non-HTTP, e.g. `caplog.text`) 8, `/eval` 6, `/health/queue` 4, `/`, `/health/ready`, `/health/schema` 2 each, `/runs/{run_id}/status` and `/webhook/inbound` 1 each.
- None of these numbers were copied from `REQUIREMENTS.md`'s prior "`14 files`, `42 presence / 31 absence`" figures — that document's own methodology was narrower and unstated; this pass re-derived independently as instructed.

## Task Commits

1. **Task 1: Build the assertion registry as a machine artifact** - `8bb9a9f` (feat)
2. **Task 2: AST completeness guard, demonstrated red and reverted byte-identically** - `998f774` (test)
3. **Task 3: Generated markdown view, staleness check, and the D-22-08 ordering gate in CI** - `ceefafc` (feat)

## Files Created/Modified

- `tests/assertion_inventory.py` (1698 lines) — the registry: dataclass/enums, `ASSERTION_INVENTORY` (163 entries), `FILE_SCOPE_NOTES` (19 entries)
- `tests/test_inventory_completeness.py` (214 lines) — the AST completeness guard, 7 tests
- `scripts/render_assertion_inventory.py` (223 lines) — `render_view()` + `main()` with `--check`
- `docs/ASSERTION-INVENTORY.md` (302 lines) — generated view, committed
- `.github/workflows/ci.yml` — two new steps in the `lint` job

## Decisions Made

- **Route/layer classification traced actual request calls, not file-name heuristics.** Every assertion's enclosing test function was walked back to its own `client.get(...)`/`client.post(...)` (or `response.headers["location"]` redirect target) call via AST, not guessed. This caught a real misattribution risk: 5 assertions in `tests/test_ops_route.py` contain the string `f"/runs/{run_id}"` inside their OWN assertion text (checking that an `/ops` page renders a working link), which a whole-function substring scan would have misread as a request to `/runs/{run_id}`. All 23 `test_ops_route.py` entries correctly resolve to `route=/ops`.
- **JSON_ISLAND vs REACT_DOM split for `/runs` entries.** Content backed by a DTO field (a run id, a badge class/label, a failure reason) is `JSON_ISLAND` — it will live inside the future `__INITIAL_DATA__` blob, so the honest rewrite is a positive exact-shape JSON assertion, not a `response.text` substring search (which would keep "passing" vacuously because the same string also sits in the raw JSON payload). Static JSX markup with no data behind it (the empty-state copy "No payroll runs yet", `runs_list.html:66/74`) is `REACT_DOM` — the genuinely vacuous class, since `TestClient` never executes JavaScript and cannot see React-rendered DOM at all.
- **`FILE_SCOPE_NOTES` self-reference.** The plan's own scope rule ("every file under `tests/` whose text contains `.text`") applies to the two new guard/registry files themselves once they exist, since their docstrings discuss `.text` comparisons in prose. Resolved by adding explicit zero-affected notes for both rather than special-casing them out of scope.
- **`from tests.assertion_inventory import ...` inside a directly-run script needed an explicit `sys.path` insert.** `pyproject.toml`'s `[tool.setuptools.packages.find]` only includes `app*` — `tests`/`eval`/`scripts` are not installed packages, so `uv run python scripts/render_assertion_inventory.py` (the plan's own literal `<verify>` invocation) puts `scripts/` on `sys.path[0]`, not the repo root. `pytest` sidesteps this via its own rootdir insertion; a directly-run script has none, so `REPO_ROOT` is inserted before the import, with an inline `# noqa: E402` and a comment explaining why.
- **`enum.StrEnum` over `class X(str, Enum)`.** Ruff's `UP042` flags the latter; the repo already uses `enum.StrEnum` in `app/ingest.py`, `app/pipeline/result.py`, `app/models/job.py` — matched that precedent.

## Demonstrated Red — Task 2 (completeness guard)

**`grep -n` confirming the mutation target is live source, not a docstring/comment copy:**
```
$ grep -n '"No payroll runs yet" not in response.text' tests/test_dashboard.py
66:    assert "No payroll runs yet" not in response.text
```

**The mutation** (one new, deliberately unclassified `.text` comparison added immediately after line 66):
```python
    assert "No payroll runs yet" not in response.text
    assert "Payroll Runs" in response.text  # RED-PROOF: deliberately unclassified .text assertion
```

**RED — `uv run pytest tests/test_inventory_completeness.py -x -q` (verbatim, truncated to the header/footer; the full 34-entry list is every downstream `test_dashboard.py` entry shifted one line by the insertion, which the guard correctly treats as both newly-discovered-and-unregistered):**
```
F
=================================== FAILURES ===================================
_____________ test_every_discovered_assertion_has_a_registry_entry _____________

    def test_every_discovered_assertion_has_a_registry_entry() -> None:
        discovered = discover_text_comparisons()
        missing = sorted(set(discovered) - set(ASSERTION_INVENTORY))
>       assert not missing, (
            "discovered `.text` comparisons with no ASSERTION_INVENTORY entry "
            f"(file:line:col): {[discovered[k] for k in missing]}"
        )
E       AssertionError: discovered `.text` comparisons with no ASSERTION_INVENTORY entry (file:line:col): [('tests/test_dashboard.py', 1072, 11), ('tests/test_dashboard.py', 1113, 11), ... 34 entries total ...]

tests/test_inventory_completeness.py:127: AssertionError
=========================== short test summary info ============================
FAILED tests/test_inventory_completeness.py::test_every_discovered_assertion_has_a_registry_entry
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.36s
```

**The revert:**
```
$ git checkout -- tests/test_dashboard.py
$ git diff --stat tests/test_dashboard.py
(no output — byte-identical)
$ uv run pytest tests/test_inventory_completeness.py -x -q
.......                                                                  [100%]
7 passed in 2.81s
```

## Demonstrated Red — Task 3 (`--check` staleness gate)

**The mutation** (`tests/assertion_inventory.py:235`, one `AssertionEntry.route` value changed):
```
-        route='/runs',
+        route='/runs-MUTATED',
```

**RED — `uv run python scripts/render_assertion_inventory.py --check` (verbatim, truncated):**
```
--- docs/ASSERTION-INVENTORY.md (committed)
+++ docs/ASSERTION-INVENTORY.md (regenerated)
@@ -27,7 +27,8 @@
 | `/health/ready` | 2 |
 | `/health/schema` | 2 |
 | `/ops` | 23 |
-| `/runs` | 16 |
+| `/runs` | 15 |
+| `/runs-MUTATED` | 1 |
 | `/runs/{run_id}` | 89 |
 ...
-| `test_dashboard:62:11` | `/runs` | presence | json_island | `str(run_id) in response.text` |
+| `test_dashboard:62:11` | `/runs-MUTATED` | presence | json_island | `str(run_id) in response.text` |
...
STALE: docs/ASSERTION-INVENTORY.md does not match tests/assertion_inventory.py. Regenerate with `uv run python scripts/render_assertion_inventory.py`.
```
Exit code: 1

**The revert:**
```
$ git checkout -- tests/assertion_inventory.py
$ git diff --stat tests/assertion_inventory.py
(no output — byte-identical)
$ uv run python scripts/render_assertion_inventory.py --check
--check passed: docs/ASSERTION-INVENTORY.md is current
```
Exit code: 0

## Red-proof — CI ordering gate

Simulated locally (a temp directory, not this repo) since GitHub Actions cannot be triggered from this session:
```
$ mkdir -p /tmp/guard01_test/frontend/src && touch /tmp/guard01_test/frontend/src/dummy.tsx
$ cd /tmp/guard01_test
$ bash -c '<the exact ci.yml step body>'
GUARD-01 violation: frontend/src contains files but tests/assertion_inventory.py does not exist.
```
Exit code: 1. Against the current repo state (no `frontend/src`, registry present), the same step body exits 0 (verified via the plan's own automated `<verify>` command, which parses `.github/workflows/ci.yml` and asserts the step names exist).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] New code violated the pre-existing comment-provenance guard**
- **Found during:** Task 3, running the full suite
- **Issue:** `tests/assertion_inventory.py`, `tests/test_inventory_completeness.py`, and `.github/workflows/ci.yml`'s new comments/docstrings cited `D-22-05`/`D-22-06`/`D-22-07`/`D-22-08`/`D-22-09`/`D-22-10`/`D-22-11`/`D-22-12` decision IDs, "Phase 23"/"Phase 23/24" phase references, and a `SUMMARY.md` doc reference — all forbidden by `tests/test_comment_provenance_guard.py`'s repo-wide sweep (`SCAN_GLOBS` includes `tests/**/*.py`, `scripts/*.py`, and `.github/workflows/*.yml`), which this project's v3 milestone established specifically to keep source comments legible without a planning document.
- **Fix:** Rewrote every flagged citation to state the actual constraint in plain language (e.g. "per D-22-12 React mount boundary" became "the React mount boundary is lines 64-115"). `GUARD-01`/`GUARD-02` requirement IDs were left as-is — the guard's `requirement-id` pattern explicitly excludes them as live traceability.
- **Files modified:** `tests/assertion_inventory.py`, `tests/test_inventory_completeness.py`, `.github/workflows/ci.yml`
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree -q` passes; full suite re-run green.
- **Committed in:** `ceefafc` (Task 3 commit, same commit as the code it fixed — caught before the task commit landed)

**2. [Rule 3 - Blocking] `scripts/render_assertion_inventory.py` could not import `tests.assertion_inventory` when run directly**
- **Found during:** Task 3, first run of the plan's own literal `<verify>` command
- **Issue:** `pyproject.toml`'s `[tool.setuptools.packages.find]` only installs `app*` as a package; `tests` is not on `sys.path` when a script is invoked as `python scripts/foo.py` (Python puts the script's own directory on `sys.path[0]`, not the repo root or cwd) — `ModuleNotFoundError: No module named 'tests'`.
- **Fix:** Inserted `REPO_ROOT` onto `sys.path` before the `tests` import, with an inline comment explaining why and a `# noqa: E402` (ruff's "import not at top of file," individually justified per the repo's noqa convention).
- **Files modified:** `scripts/render_assertion_inventory.py`
- **Verification:** `uv run python scripts/render_assertion_inventory.py` and `--check` both run cleanly from a fresh shell; `uv run ruff check` and `uv run mypy` both clean.
- **Committed in:** `ceefafc` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 pre-existing-guard fix, 1 blocking-import fix)
**Impact on plan:** Both fixes are necessary for correctness against this repo's own existing gates; no scope creep, no architectural change.

## Issues Encountered

None beyond the two deviations above. The classification pass (163 entries across 14 files) was performed via a scripted AST walk cross-checked against direct reads of the actual test source and `app/templates/runs_list.html`, rather than by hand-typing each entry — the scripting was necessary at this scale to keep `route`/`layer` accurate (hand-classification at 163 entries risks exactly the kind of silent drift GUARD-01 exists to prevent), but every route/layer decision rule is documented in the registry's own module docstring and this SUMMARY's Decisions Made section, and 5 of the AST-detected route candidates were caught and corrected against a naive whole-function scan (the `test_ops_route.py` false positives above).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- **GUARD-01 is now a committed, CI-enforced gate.** No plan in this phase (22-02 through 22-12) or in Phases 23/24 may land a `frontend/src` file without `tests/assertion_inventory.py` already being present — verified by both a local red-proof and the plan's own automated `<verify>` command.
- **The registry is the shared input for GUARD-02** (the safety-subset mutation registry, a separate sibling file per the plan's own scope note) — not built in this plan, deferred to whichever later plan owns it.
- **Route/layer classifications for `/runs/{run_id}` and `/eval` are recorded but intentionally not yet pinned/rewritten** — per the plan's own instruction, only `/runs`-attributed entries are rewritten in this phase; Phases covering `/runs/{run_id}` and `/eval` conversion inherit a finished classification and do not need to re-derive it.
- No blockers.

---
*Phase: 22-frontend-foundation-runs-list*
*Completed: 2026-08-17*
