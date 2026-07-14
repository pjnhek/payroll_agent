---
phase: 16-queue-substrate-unblocked-webhook
plan: 05
subsystem: database
tags: [postgres, schema-drift, ci-guard, health-check, queue, jobs]

# Dependency graph
requires:
  - phase: 16-03
    provides: "app/models/job.py (JobKind/JobState/Job), the jobs table in schema.sql, bootstrap._DROP_ORDER entry"
provides:
  - "app/db/schema_introspect.py — 'jobs' registered in expected_schema().tables, so /health/schema now covers column drift on the newest, most concurrency-critical table"
  - "tests/test_job_kind_drift.py — Proof 5: the kind/state <-> RunStatus collision guard and the JobKind/JobState <-> SQL CHECK drift guard, both set-EQUALITY, both directions"
  - "A purpose-built inline-CHECK parser (_inline_check_values, test-local) for CHECK constraints declared inline inside CREATE TABLE, distinct from schema_introspect's DO-block parser"
  - "A placeholder in tests/test_job_kind_drift.py marking where 16-06 appends the dispatch-table half of Proof 5"
affects: [16-06, 16-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two independent inline-CHECK vs DO-block-CHECK parsers now coexist in the schema-drift-guard family — schema_introspect._do_block_check_values for the two DO-block re-add constraints, and this plan's local _inline_check_values for the jobs table's live CREATE-time CHECKs. Calling the wrong one on the wrong table raises ValueError rather than silently returning an empty set."
    - "Column-coverage registration (expected_schema().tables) and CHECK-value drift coverage (the Q3 live-DB query / this plan's static parser) are DELIBERATELY decoupled per table — a table can gain column coverage without its CHECK values being expressible in the two-table CASE-WHEN live query."

key-files:
  created:
    - tests/test_job_kind_drift.py
  modified:
    - app/db/schema_introspect.py
    - tests/test_schema_introspect.py

key-decisions:
  - "'jobs' added to expected_schema().tables as a THIRD dict entry (after payroll_runs, email_messages) rather than reordering — dict insertion order drives diff_against_live's per-table live-column query loop, and test_schema_introspect.py's FakeConnection scripting had to be updated to match the new 3-query column-fetch sequence (previously 2) or the queue shifts and Q4/Q5 silently read the wrong scripted rows. This was found by running the full consumer-test suite after the registration change, not predicted in advance."
  - "The Q3 CHECK-value drift query in diff_against_live is UNCHANGED — jobs.kind/jobs.state are NOT added to it. Two independent reasons documented inline: the query's CASE WHEN can only express a binary choice, and jobs' CHECKs are inline (no DO-block constraint-name literal to anchor a third branch on) — feeding them through the existing DO-block parser would raise ValueError, not silently pass. Value-drift coverage for jobs lives entirely in the new static test file instead."
  - "test_job_kind_drift.py's inline-CHECK parser scopes its regex search to the jobs CREATE body (via schema_introspect._create_body) rather than the whole file, so a hypothetical future sibling table with its own 'kind'/'state' CHECK could never be matched by accident."

patterns-established: []

requirements-completed: [QUEUE-05]

coverage:
  - id: D1
    description: "expected_schema().tables includes 'jobs' with its columns parsed from schema.sql, so a live deploy on which the jobs table silently failed to apply trips /health/schema instead of reporting in_sync"
    requirement: "QUEUE-05"
    verification:
      - kind: unit
        ref: "manual python -c assertion (Task 1 verify block) — jobs covered: 16 cols"
        status: pass
      - kind: unit
        ref: "tests/test_schema_introspect.py, tests/test_health_schema.py, tests/test_check_schema_cli.py (14 tests, all consumers of expected_schema()/diff_against_live)"
        status: pass
      - kind: integration
        ref: "GET /health/schema against a live DB after bootstrap, asserting in_sync with no false-positive drift"
        status: unknown
    human_judgment: true
    rationale: "No DATABASE_URL/.env in this worktree — the live-DB acceptance criterion (GET /health/schema returns in_sync after bootstrap, proving the new expected columns genuinely exist live and registration introduced no false-positive drift alarm) could not be executed here. All static verification (column parsing, the 3 consumer test files, mypy, ruff) passed. Deferred to the queueproof CI gate, which runs with a real Postgres service container."
  - id: D2
    description: "tests/test_job_kind_drift.py: the kind/status collision guard, the JobKind/JobState <-> SQL CHECK drift guard (set equality, both directions), the jobs DDL inventory pin, and the bootstrap/health-schema regression guards — all hermetic, no DB connection"
    requirement: "QUEUE-05"
    verification:
      - kind: unit
        ref: "tests/test_job_kind_drift.py (8 tests, all pass)"
        status: pass
      - kind: unit
        ref: "Four falsifying mutations executed by hand: (a) extra JobKind member, (b) extra SQL CHECK value, (c) JobState value renamed to collide with RunStatus, (d) 'jobs' removed from expected_schema().tables — each independently confirmed red, then reverted (git diff clean afterward)"
        status: pass
    human_judgment: false
duration: 20min
completed: 2026-07-14
status: complete
---

# Phase 16 Plan 05: Jobs Schema Drift Guards & Health Coverage Summary

**ROADMAP criterion #5 is now machine-enforced: `tests/test_job_kind_drift.py` fails CI if `jobs.kind`/`jobs.state` collide with `RunStatus` or drift from the SQL CHECK in either direction, and `/health/schema` now detects a silently-missing `jobs` table on live deploy.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 2 of 2 completed
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments

- `app/db/schema_introspect.py`'s `expected_schema()` now registers `"jobs"` in its `tables` dict (16 columns parsed from `schema.sql`'s CREATE body), so the column-coverage half of `/health/schema`'s live-DB drift probe now sees the newest, most concurrency-critical table — a deploy on which `jobs` silently failed to apply now trips 503 `drift` instead of reporting `in_sync`. The Q3 CHECK-value drift query stays deliberately scoped to `payroll_runs`/`email_messages` only, with an inline comment explaining why (a two-branch CASE-WHEN query shape, and `jobs`' inline-not-DO-block CHECK pattern).
- New `tests/test_job_kind_drift.py` (8 tests): a purpose-built inline-CHECK parser (`_inline_check_values`) extracts `jobs.kind`/`jobs.state`'s CHECK value sets directly from the `jobs` CREATE body — genuinely different from, and never calling, `schema_introspect._do_block_check_values` (verified: `grep -cE '_do_block_check_values\s*\(' tests/test_job_kind_drift.py` == 0). Covers: kind/state never collide with any `RunStatus` value; kind/state SQL CHECK sets EQUAL their Python enum, both directions; the `jobs` DDL inventory (`uq_jobs_dedup_key`, `ck_jobs_lease_coherent`, `idx_jobs_claimable`, no cascade, no `event_id`) is pinned by name; `"jobs"` precedes `"payroll_runs"` in `bootstrap._DROP_ORDER`; `"jobs"` is a key of `expected_schema().tables`; the file imports no DB module.
- All four falsifying mutations (below) executed by hand and confirmed red, then reverted — `git status --short` clean before each commit.
- Full suite green (660 passed, 53 skipped, up from 652), `mypy app` clean, `ruff check .` clean.

## Task Commits

Each task was committed atomically:

1. **Task 1: Register `jobs` with `/health/schema`'s column-drift probe (D-12)** - `4822904` (feat)
2. **Task 2: Proof 5 — the kind/status collision guard and the JobKind drift guard** - `15a4e34` (test)

**Plan metadata:** committed by the orchestrator after wave merge (this executor runs in worktree mode and does not write STATE.md/ROADMAP.md).

## Files Created/Modified

- `app/db/schema_introspect.py` - `"jobs"` added to `expected_schema().tables`; comment added to the Q3 CHECK-value query explaining why `jobs` is deliberately excluded from it (Task 1)
- `tests/test_schema_introspect.py` - `_script_in_sync` helper updated to script a third fetchall (jobs columns) matching `diff_against_live`'s now-3-table column-query loop; found and fixed while running the consumer-test suite, not anticipated by the plan's read-ahead notes (Task 1)
- `tests/test_job_kind_drift.py` - new file, 8 tests: collision guards, CHECK-drift guards (set equality), DDL inventory pin, `_DROP_ORDER`/`expected_schema()` regression guards, hermeticity self-guard, and a placeholder for 16-06's dispatch-table appendix (Task 2)

## Decisions Made

- `"jobs"` was added as a third `tables` dict entry (after `payroll_runs`, `email_messages`) rather than reordering the dict — dict insertion order is what `diff_against_live`'s per-table live-column query loop iterates in, so `tests/test_schema_introspect.py`'s `FakeConnection` scripting needed a matching third scripted `fetchall` or the queue shifted and Q4/Q5 (the status/purpose CHECK query and the unique-constraint query) silently read the wrong rows. Discovered empirically by running the three consumer test files after the registration change, not predicted by the plan's read-ahead notes — fixed under Rule 1 (bug: the queue-order mismatch was a genuine breakage of existing green tests, not a design choice).
- The Q3 CHECK-value drift query in `diff_against_live` was left completely unchanged, per the plan's explicit instruction, with the two independent reasons written directly into the code comment (binary CASE-WHEN shape; inline-not-DO-block CHECK pattern) rather than cited to the plan.
- `test_job_kind_drift.py`'s inline-CHECK parser reuses `schema_introspect._create_body` (a private helper) to scope its regex search to the `jobs` CREATE body specifically — legitimate per the BOUND-01 guard's documented carve-out for tests reaching into a module's own internals, and avoids ever accidentally matching a same-named CHECK on a different table.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `test_schema_introspect.py`'s `FakeConnection` scripting broke when `expected_schema().tables` gained a third entry**
- **Found during:** Task 1, running `uv run pytest tests/test_schema_introspect.py tests/test_health_schema.py tests/test_check_schema_cli.py -q` per the plan's own verify block, immediately after adding `"jobs"` to the `tables` dict
- **Issue:** `diff_against_live` loops `for table, expected_cols in exp.tables.items(): live = _live_columns(conn, table)`, issuing one `conn.execute(...).fetchall()` per table. `_script_in_sync` (the test helper in `test_schema_introspect.py`) only scripted 2 column-fetch results (for `payroll_runs`/`email_messages`) before the Q3 (status/purpose CHECK) and Q4 (unique constraints) results. With `"jobs"` added as a third table, the loop now consumes 3 items from the FIFO scripted-results queue before reaching Q3, so the previously-Q3-scripted row set was consumed as `jobs`' live columns, and `conn.execute(...).fetchall()` for the real Q3 query returned an empty default (`[]`), producing `ValueError: not enough values to unpack (expected 2, got 1)` in the `for which, cdef in rows:` loop. 4 of 14 tests failed.
- **Fix:** Updated `_script_in_sync` to also script `jobs`' expected columns as a third `fetchall` between the `email_messages` (Q2) and status/purpose-CHECK (now Q4) scripts, matching `diff_against_live`'s new 3-table iteration order. No production code change — test-double scripting only.
- **Files modified:** `tests/test_schema_introspect.py`
- **Verification:** `uv run pytest tests/test_schema_introspect.py tests/test_health_schema.py tests/test_check_schema_cli.py -q` → 14 passed (was 4 failed / 10 passed before the fix). Full suite re-run green.
- **Committed in:** `4822904` (same commit as the Task 1 registration — the fix is inseparable from the change that caused it)

**2. [Rule 1 - Bug] Comment-provenance guard violation in the new test file's docstring**
- **Found during:** Task 2, running `uv run pytest tests/test_comment_provenance_guard.py -q` before committing (per the project's established discipline from 16-02/16-03's own deviations, not explicitly called out in this plan's read-ahead)
- **Issue:** The module-level falsifying-mutation docstring in `tests/test_job_kind_drift.py` originally cited `(D-12's registration is one careless refactor from silently disappearing without this)` — a decision-ID citation that trips `tests/test_comment_provenance_guard.py`'s repo-wide `decision-id` pattern.
- **Fix:** Reworded to state the reasoning directly: `(the registration this guards is one careless refactor from silently disappearing without this)`. No behavioral change — comment text only.
- **Files modified:** `tests/test_job_kind_drift.py`
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py -q` → 5 passed. Full suite re-run: 660 passed, 53 skipped.
- **Committed in:** `15a4e34` (the file was written clean into its single commit; the guard violation was caught and fixed before that commit was made)

---

**Total deviations:** 2 auto-fixed (1 bug — FakeConnection scripting-order mismatch; 1 bug — comment-hygiene compliance)
**Impact on plan:** No scope creep. Deviation 1 is a direct, inescapable consequence of the plan's own Task 1 instruction ("add jobs to expected_schema().tables") interacting with a scripted-queue test double the plan's read-ahead notes did not fully trace through; deviation 2 is the same comment-hygiene discipline every prior wave-1 plan in this phase hit.

## Falsifying Mutations Executed (pasted red runs)

**(a) Add a `JobKind` member with no corresponding value in the SQL CHECK** — added `PHANTOM_KIND = "phantom_kind"` to `JobKind` in `app/models/job.py`:

```
E       AssertionError: jobs.kind drift detected!
E           In SQL CHECK but not in JobKind: none
E           In JobKind but not in SQL CHECK: {'phantom_kind'}
E           SQL values:    ['run_pipeline']
E           Python values: ['phantom_kind', 'run_pipeline']
E       assert {'run_pipeline'} == {'phantom_kin...run_pipeline'}
FAILED tests/test_job_kind_drift.py::TestJobKindCheckDrift::test_job_kind_check_matches_python_enum
```

**(b) Add a value to the SQL CHECK with no `JobKind` member** — added `'phantom_sql_kind'` to `jobs.kind`'s inline CHECK in `app/db/schema.sql`:

```
E       AssertionError: jobs.kind drift detected!
E           In SQL CHECK but not in JobKind: {'phantom_sql_kind'}
E           In JobKind but not in SQL CHECK: none
E           SQL values:    ['phantom_sql_kind', 'run_pipeline']
E           Python values: ['run_pipeline']
E       assert {'phantom_sql...run_pipeline'} == {'run_pipeline'}
FAILED tests/test_job_kind_drift.py::TestJobKindCheckDrift::test_job_kind_check_matches_python_enum
```

**(c) Rename a `JobState` member's value to a string `RunStatus` already owns** — changed `DEAD = "dead"` to `DEAD = "error"` in `app/models/job.py` (`RunStatus.ERROR == "error"`):

```
E       AssertionError: JobState value(s) ['error'] collide with RunStatus — a future JobState member taking a string RunStatus already owns is exactly the trap this guard exists to catch
E       assert not {'error'}
FAILED tests/test_job_kind_drift.py::TestKindStatusCollision::test_job_state_never_collides_with_run_status
```

**(d) Remove `"jobs"` from `expected_schema().tables`** — deleted the `"jobs": frozenset(...)` line from `app/db/schema_introspect.py`:

```
E       AssertionError: 'jobs' must be a key of expected_schema().tables — without this, a live deploy on which the jobs table silently failed to apply would still report /health/schema as in_sync
E       assert 'jobs' in {'payroll_runs': frozenset(...), 'email_messages': frozenset(...)}
FAILED tests/test_job_kind_drift.py::TestJobsDdlInventory::test_health_schema_covers_jobs
```

Each mutation was reverted via `git checkout -- <file>` immediately after capturing the red run; `git status --short` confirmed a clean tree before the corresponding commit.

## Issues Encountered

- **No live database available in this worktree.** No `.env`/`DATABASE_URL` present (by design — gitignored, never checked out into a worktree), so the plan's live-DB acceptance criterion for Task 1 — `GET /health/schema` returning `in_sync` after `bootstrap`, proving the new expected columns genuinely exist live and the registration introduced no false-positive drift alarm — could not be executed here. All static verification (schema-text parsing, the three consumer test files, mypy, ruff, the full 660-test hermetic suite) passed. This gap is flagged `human_judgment: true` in the `coverage` block (D1) and deferred to the `queueproof` CI gate, which runs with a real Postgres service container per `16-02-SUMMARY.md`.

## User Setup Required

None — no external service configuration required. A live Postgres connection (local, Supabase, or the CI `queueproof` service container) is needed to close the deferred live-DB verification above, but that is existing project infrastructure, not new setup.

## Next Phase Readiness

- `tests/test_job_kind_drift.py` carries an explicit placeholder comment at the bottom naming where 16-06's dispatch-table half of Proof 5 (`set(JobKind) == set(dispatch.HANDLERS)`) should be appended once `app/queue/dispatch.py` exists — 16-06's executor should append a new test class there rather than creating a second drift-test file.
- `app/db/schema_introspect.py`'s Q3 CHECK-value query intentionally still excludes `jobs` — a future contributor extending live CHECK-value drift coverage to `jobs.kind`/`jobs.state` needs a genuinely new query shape (not a wider `IN` list on the existing `CASE WHEN`), and the reasoning is written into the code so nobody "fixes" this by force-fitting a third branch onto the two-table CASE expression.
- No blockers for downstream plans. The live-DB acceptance criterion (D1 above) should be closed before the phase is marked fully verified, consistent with the same outstanding item already flagged in `16-03-SUMMARY.md`.

---
*Phase: 16-queue-substrate-unblocked-webhook*
*Completed: 2026-07-14*

## Self-Check: PASSED

All claimed files found on disk (app/db/schema_introspect.py, tests/test_schema_introspect.py,
tests/test_job_kind_drift.py, this SUMMARY.md). Both claimed commit hashes (4822904, 15a4e34)
found in `git log --oneline --all`. No missing items.
