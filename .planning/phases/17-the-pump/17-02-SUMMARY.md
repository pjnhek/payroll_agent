---
phase: 17-the-pump
plan: 02
subsystem: queue
tags: [python, postgres, sql, pytest, mypy, queue-depth]

# Dependency graph
requires:
  - phase: 16-queue-substrate-unblocked-webhook
    provides: the `jobs` table and app/db/repo/jobs.py's `_conn_ctx`-based six-function read/write surface this plan extends
provides:
  - "`count_open_jobs(conn=None) -> int` in app/db/repo/jobs.py — a point-in-time backlog count (`state IN ('pending', 'leased')`)"
  - "`count_open_jobs` re-exported through app/db/repo/__init__.py (import + __all__)"
  - "an honest hermetic FakeConnection test proving return->int mapping and the exact WHERE text, NOT a behavioral mixed-population claim"
affects: ["17-04 (the pump route's queue_depth response field)", "17-05 (the live mixed pending/leased/done/dead behavioral proof)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "backlog-scoped read, not claimable-now: count_open_jobs deliberately omits claim_job's available_at <= now() filter — total outstanding depth is the useful ops signal, not the instantaneously-claimable subset"
    - "hermetic-honesty discipline: a FakeConnection-backed test proves the WHERE text and the return-type conversion, never a claim about what Postgres would actually count for a mixed population — that proof is reserved for a live-DB test"

key-files:
  created: []
  modified:
    - app/db/repo/jobs.py
    - app/db/repo/__init__.py
    - tests/test_repo_jobs_sql.py

key-decisions:
  - "count_open_jobs stays a plain state IN ('pending','leased') count — no special-casing to exclude the documented final-attempt lease-strand residual (carried to Phase 18/FAIL-02), so queue_depth honestly reflects the residual rather than hiding it."
  - "count_open_jobs() passes an explicit empty params tuple to execute() (not a bare SQL string) to satisfy this module's f-string-discipline convention and its own guard test, even though the query has no interpolated values."

requirements-completed: [PUMP-01]

coverage:
  - id: D1
    description: "count_open_jobs() returns the point-in-time backlog count (pending + leased) via a plain SELECT count(*), following the _conn_ctx read convention"
    requirement: "PUMP-01"
    verification:
      - kind: unit
        ref: "tests/test_repo_jobs_sql.py::test_count_open_jobs_maps_scalar_row_to_int_and_scopes_the_where"
        status: pass
      - kind: unit
        ref: "tests/test_repo_jobs_sql.py::test_count_open_jobs_empty_row_returns_zero"
        status: pass
    human_judgment: false
  - id: D2
    description: "count_open_jobs is reachable through the app.db.repo facade (import + __all__), matching the existing six-function pattern"
    requirement: "PUMP-01"
    verification:
      - kind: unit
        ref: "tests/test_repo_jobs_sql.py::test_facade_exports_all_seven_functions"
        status: pass
      - kind: cli
        ref: "uv run python -c \"from app.db import repo; print(repo.count_open_jobs)\""
        status: pass
    human_judgment: false
  - id: D3
    description: "The module docstring and all three six-function surface tests (f-string guard, facade-exports, conn/_conn_ctx inventory) now cover seven functions including count_open_jobs, so none falsely claims full-surface coverage"
    requirement: "PUMP-01"
    verification:
      - kind: cli
        ref: "grep -c \"Six functions\" app/db/repo/jobs.py -> 0; grep -q \"Seven functions\" app/db/repo/jobs.py -> found"
        status: pass
      - kind: cli
        ref: "grep -c \"all six functions\\|all_six_functions\" tests/test_repo_jobs_sql.py -> 0"
        status: pass
      - kind: unit
        ref: "tests/test_repo_jobs_sql.py::test_no_function_builds_sql_with_an_fstring"
        status: pass
      - kind: unit
        ref: "tests/test_repo_jobs_sql.py::test_every_function_takes_conn_and_uses_conn_ctx"
        status: pass
    human_judgment: false
  - id: D4
    description: "The hermetic test honestly proves return->int and the exact WHERE text only — no claim of a mixed pending/leased/done/dead population count, and no pytest.mark.integration/queueproof marker added"
    requirement: "PUMP-01"
    verification:
      - kind: cli
        ref: "git diff tests/test_repo_jobs_sql.py | grep -E \"pytest.mark.integration|pytest.mark.queueproof\" -> no hits"
        status: pass
    human_judgment: false

duration: 9min
completed: 2026-07-15
status: complete
---

# Phase 17 Plan 2: count_open_jobs Summary

**Added `count_open_jobs()` — a plain `SELECT count(*) FROM jobs WHERE state IN ('pending', 'leased')` — as the point-in-time backlog read the pump reports as `queue_depth`, re-exported through the facade, with an honest hermetic test and all three stale six-function surface tests updated to seven.**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-07-15T14:24:41Z (immediately following 17-01)
- **Completed:** 2026-07-15T14:33:01Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- `count_open_jobs(conn: psycopg.Connection | None = None) -> int` added to `app/db/repo/jobs.py`, modeled on `get_job`'s `_conn_ctx` read shape: `SELECT count(*) FROM jobs WHERE state IN ('pending', 'leased')`, `int(row[0]) if row else 0`.
- Deliberately backlog-scoped (total outstanding pending+leased), not "claimable right now" — it does not filter on `available_at <= now()` the way `claim_job`'s subquery does.
- No special-casing to exclude the documented final-attempt lease-strand residual (17-01/T-17-16) — `queue_depth` honestly inflates until Phase 18's dead-letter transition reaps it, rather than hiding the residual behind a smarter query.
- Re-exported through `app/db/repo/__init__.py` (import block + `__all__`), matching the existing pattern for `enqueue_job`/`claim_job`/`complete_job`/`fail_job`/`release_leases`/`get_job`.
- Module docstring updated from "Six functions" to "Seven functions", enumerating `count_open_jobs`.
- An honest hermetic `FakeConnection` test (`test_count_open_jobs_maps_scalar_row_to_int_and_scopes_the_where`) proves the return→`int` conversion and the exact `state IN ('pending', 'leased')` WHERE text — explicitly NOT a claim that Postgres actually counts a mixed pending/leased/done/dead population correctly; that behavioral proof is reserved for 17-05's live-DB test. A companion test (`test_count_open_jobs_empty_row_returns_zero`) covers the None-row → 0 case.
- All three stale six-function surface tests updated to seven: `test_no_function_builds_sql_with_an_fstring` now also exercises `count_open_jobs`; `test_facade_exports_all_six_functions` renamed to `test_facade_exports_all_seven_functions` and its name tuple extended; `test_every_function_takes_conn_and_uses_conn_ctx`'s name tuple extended. None of the three now falsely claims full-surface coverage.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add count_open_jobs to jobs.py, re-export it, update the docstring count** - `8c91c4c` (feat)
2. **Task 2: Honest hermetic test for count_open_jobs + update all three stale six-function surface tests to seven** - `90ea867` (test)
3. **Deviation fix: drop review-ticket-shaped citation from the new docstring** - `23ca0f7` (fix) — surfaced by the full-suite run after Task 2; see Deviations below.

**Plan metadata:** committed as part of this SUMMARY's own commit (state/roadmap/requirements docs)

## Files Created/Modified

- `app/db/repo/jobs.py` - `count_open_jobs()` added; module docstring six→seven; `execute()` call passes an explicit empty params tuple (f-string-discipline convention)
- `app/db/repo/__init__.py` - `count_open_jobs` added to the jobs import block and `__all__`
- `tests/test_repo_jobs_sql.py` - 2 new tests for `count_open_jobs` (scalar-row + empty-row cases); 3 stale six-function surface tests updated to seven

## Decisions Made

- `count_open_jobs` stays a plain `state IN ('pending','leased')` count with no strand-exclusion special-casing — this was already locked by the plan (per 17-REVIEWS round-3 finding, the strand is a documented, deferred, non-money residual; hiding it behind a smarter query would defeat the purpose of surfacing it honestly).
- Passed `count_open_jobs`'s `execute()` call an explicit empty tuple rather than a bare SQL string, to satisfy `test_no_function_builds_sql_with_an_fstring`'s params-type assertion, which the plan's Task 2 action explicitly required extending to cover the new function.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] count_open_jobs's execute() call recorded params of type NoneType, tripping the f-string-discipline guard test**
- **Found during:** Task 2 (running `test_no_function_builds_sql_with_an_fstring` after extending it to cover `count_open_jobs`)
- **Issue:** `count_open_jobs`'s SQL has no interpolated values, so the Task 1 implementation called `c.execute(sql)` with no params argument, recording `params=None`. The file's own guard asserts every recorded `execute()` call's params is a `tuple` or `dict` — a bare no-params call breaks that invariant even with a static, injection-free query.
- **Fix:** Changed the call to `c.execute(sql, ())` — an explicit empty tuple, consistent with the module's stated SQL discipline ("every value reaches SQL through a `%s` or named placeholder — never an f-string", even where there happens to be no value).
- **Files modified:** `app/db/repo/jobs.py`
- **Verification:** `uv run pytest tests/test_repo_jobs_sql.py -q` — 13 passed
- **Committed in:** `90ea867` (Task 2 commit)

**2. [Rule 1 - Bug] New docstring line tripped the repo-wide comment-provenance guard**
- **Found during:** post-Task-2 full-suite verification run (`uv run pytest -q -m "not integration"`)
- **Issue:** `count_open_jobs`'s docstring cited `(OPS-01)` as the future ops-view consumer. `tests/test_comment_provenance_guard.py` (a repo-wide CI gate) flags any `*-NN` token matching its `review-ticket` pattern; the guard's requirement-ID exclusion only covers 4+-letter prefixes (`\b[A-Z]{4,}-[0-9]{2}\b`), so the 3-letter `OPS` prefix was caught even though it is a genuine `REQUIREMENTS.md` ID, not stale review provenance.
- **Fix:** Reworded the docstring to describe the future consumer ("a queue-depth panel on the operator dashboard") without citing the requirement ID literal — matching this repo's convention that source comments explain the code, not cite the ticket that produced it.
- **Files modified:** `app/db/repo/jobs.py`
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py -q` — 1 passed; full suite `uv run pytest -q -m "not integration"` — 719 passed, 21 skipped, 48 deselected
- **Committed in:** `23ca0f7` (separate fix commit, since the guard only surfaced on the full-suite run after Task 2's code existed)

---

**Total deviations:** 2 auto-fixed (both Rule 1 bugs surfaced by this repo's own guard tests, neither changing `count_open_jobs`'s SQL semantics or return contract)
**Impact on plan:** Both fixes were necessary to satisfy this repo's pre-existing CI gates (f-string-discipline test, comment-provenance guard). No scope creep — `count_open_jobs`'s query, return type, and re-export surface are exactly as the plan specified.

## Issues Encountered

None beyond the two auto-fixed deviations above.

## User Setup Required

None - no external service configuration required. No schema-push, no migration (this plan adds only a read against the existing `jobs` table).

## Next Phase Readiness

- `count_open_jobs` is ready for 17-04 (the pump route's `queue_depth` response field) and 17-05 (the live-Postgres behavioral proof that a mixed pending/leased/done/dead population is counted correctly — a `FakeConnection` cannot prove that, only real Postgres can).
- No blockers. The final-attempt lease-strand residual (carried from 17-01/T-17-16 to Phase 18/FAIL-02) remains explicitly unaddressed by design — `count_open_jobs` will honestly report it as open backlog until the Phase 18 dead-letter transition reaps it.

---
*Phase: 17-the-pump*
*Completed: 2026-07-15*

## Self-Check: PASSED

All 3 modified files found on disk; all three commits (`8c91c4c`, `90ea867`, `23ca0f7`) found in git log. Full hermetic suite green: 719 passed, 21 skipped, 0 failures. `uv run ruff check .` and `uv run mypy app` both clean.
