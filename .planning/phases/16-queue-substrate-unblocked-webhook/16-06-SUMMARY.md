---
phase: 16-queue-substrate-unblocked-webhook
plan: 06
subsystem: infra
tags: [queue, threading, ast, pytest, dispatch]

# Dependency graph
requires:
  - phase: 16-queue-substrate-unblocked-webhook (plan 04)
    provides: "app/db/repo/jobs.py claim/lease/fencing protocol (claim_job/complete_job/fail_job/release_leases/get_job); rewind_for_reclaim; the fake_repo InMemoryRepo mirrors of all seven"
  - phase: 16-queue-substrate-unblocked-webhook (plan 03)
    provides: "app/models/job.py (JobKind/JobState/Job); the jobs table"
  - phase: 16-queue-substrate-unblocked-webhook (plan 02)
    provides: "queueproof marker + config knobs (not directly consumed by this plan's hermetic tests, but load-bearing for claim_job's lease_seconds default)"
provides:
  - "app/queue/wake.py — wake()/wait(timeout)/clear(), the in-process threading.Event D-09 wake signal"
  - "app/queue/dispatch.py — HANDLERS (JobKind -> (module, function_name)), handle(job) resolved via getattr at dispatch time"
  - "app/queue/handlers/pipeline.py — handle_run_pipeline: the attempts>1 reclaim rewind then the RECEIVED->EXTRACTING CAS, both the ONLY two permitted payroll_runs.status writers reachable from app/queue/"
  - "app/queue/drain.py — drain_once()/held_tokens()/_backoff_seconds(); the single drain step the worker threads (16-07) and the future pump both call"
  - "tests/test_queue_drain.py — the AST-based J-1 CAS-only static guard (fails closed on the whole first-party import graph), the pre-existing swallowed-start-failure pin, and all ten hermetic drain/handler behavioral proofs"
  - "tests/test_job_kind_drift.py — the dispatch half of the collision/enum-drift/dispatch-drift guard: set(JobKind) == set(dispatch.HANDLERS)"
affects: [16-07, 16-08, 16-09, 16-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-object dispatch table: HANDLERS maps JobKind -> (module, function_name) pairs resolved via getattr(module, name)(job) at call time, never a dict of bound function objects — the same BOUND-01 discipline app/routes/pipeline_glue.py documents, kept live for monkeypatch test seams."
    - "A single in-process threading.Event (app/queue/wake.py) replaces LISTEN/NOTIFY entirely, because Supavisor transaction-mode pooling silently no-ops both, and producer+consumer share one process in this deployment."
    - "A CAS-only status-write guard that resolves the FULL first-party import graph (every app.* module binding, including the root name a plain `import app.db.repo` binds) rather than merely names bound to the repo module — fails closed on any restricted name that escapes into a value or an unresolvable attribute chain."
    - "'First durable action' as a CONDITIONAL, not a fixed step: attempts==1 -> claim_status is first; attempts>1 -> rewind_for_reclaim (itself a CAS) is first, immediately followed by claim_status. Both branches obey the same invariant — every business-status write from the queue tier is a CAS, and the tier drops cleanly on a lost one."

key-files:
  created:
    - app/queue/__init__.py
    - app/queue/wake.py
    - app/queue/dispatch.py
    - app/queue/handlers/__init__.py
    - app/queue/handlers/pipeline.py
    - app/queue/drain.py
    - tests/test_queue_drain.py
  modified:
    - tests/test_job_kind_drift.py

key-decisions:
  - "handle_run_pipeline raises ValueError on job.run_id is None (defensive type-narrowing) even though the jobs table's own CHECK constraint makes this unreachable in practice — Job.run_id stays optional in the dataclass because it is shared transport for every future job kind."
  - "The J-1 CAS-only guard's Pass 3 check is NEGATIVE/subset-based (observed_status_writers <= permitted) rather than an exact-equality check, specifically so it is vacuously true on an empty resolved-call set — this is what makes the separate anti-vacuity test (test_the_guard_actually_resolves_the_queue_tiers_real_calls) load-bearing rather than redundant, and it is what the vacuity falsifying mutation (l) actually proves."
  - "_backoff_seconds uses base=5.0s / cap=300.0s (5 minutes) — not specified numerically anywhere in the planning docs (only the formula shape was), chosen as reasonable defaults for a queue whose LEASE_SECONDS default is 900s and MAX_ATTEMPTS default is 5."
  - "The swallowed-start-failure pin test asserts the run lands at EXTRACTING (not RECEIVED) — this handler's own forward CAS moves the run to EXTRACTING BEFORE run_pipeline_bg is ever called, so the run is MORE visible mid-flight than a stale gap description assuming no queue-tier CAS existed yet would suggest. The test documents this precisely rather than asserting a stale expectation."

requirements-completed: [QUEUE-02, QUEUE-05]

coverage:
  - id: D1
    description: "app/queue/wake.py (wake/wait/clear) and app/queue/dispatch.py (HANDLERS, handle) exist; HANDLERS has exactly one entry (JobKind.RUN_PIPELINE) stored as a (module, function_name) pair; handle() raises on an unknown kind"
    requirement: "QUEUE-05"
    verification:
      - kind: unit
        ref: "manual python -c assertion (Task 1 verify block): set(dispatch.HANDLERS) == set(JobKind); wake.wait/wake/clear round-trip"
        status: pass
      - kind: unit
        ref: "tests/test_bound01_private_imports.py::test_no_cross_module_private_imports"
        status: pass
    human_judgment: false
  - id: D2
    description: "app/queue/handlers/pipeline.py's handle_run_pipeline implements the restated INVARIANT J-1: attempts>1 rewinds via rewind_for_reclaim before the forward claim_status CAS; a lost CAS returns cleanly; reply_epoch is never bumped; orchestrator.py is untouched"
    requirement: "QUEUE-02"
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py::test_handler_attempts_1_received_cas_wins_and_pipeline_runs, ::test_handler_attempts_1_computed_cas_loses_no_run, ::test_handler_attempts_2_extracting_rewinds_then_cas_wins, ::test_handler_attempts_2_reconciled_rewind_is_a_noop_cas_loses, ::test_reply_epoch_unchanged_across_every_handler_path, ::test_first_durable_action_is_a_cas_on_both_branches"
        status: pass
    human_judgment: false
  - id: D3
    description: "drain_once() claims one job, dispatches it, and completes (fenced on the exact lease_token the claim returned) or fails (fenced, positive backoff) it; held_tokens() reflects in-flight leases"
    requirement: "QUEUE-02"
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py::test_drain_once_empty_queue_returns_false_and_dispatches_nothing, ::test_drain_once_claims_dispatches_and_completes_with_the_same_token, ::test_held_tokens_populated_during_handler_and_cleared_after, ::test_drain_once_handler_raises_calls_fail_job_not_complete_job, ::test_backoff_seconds_exponential_capped_jittered_and_deterministic"
        status: pass
    human_judgment: false
  - id: D4
    description: "The J-1 CAS-only static guard fails closed on the whole first-party import graph (restricted-name escape, getattr indirection, function-import-out-of-repo, unresolvable chains, importlib/__import__), is proven non-vacuous, and runs GREEN against the real app/queue/ with no false positive on dispatch.py's own HANDLERS/getattr mechanism"
    requirement: "QUEUE-02"
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py::test_queue_tier_status_writers_are_cas_only, ::test_the_guard_actually_resolves_the_queue_tiers_real_calls"
        status: pass
    human_judgment: false
  - id: D5
    description: "The dispatch half of the collision/enum-drift/dispatch-drift guard: set(JobKind) == set(dispatch.HANDLERS), set EQUALITY"
    requirement: "QUEUE-05"
    verification:
      - kind: unit
        ref: "tests/test_job_kind_drift.py::TestDispatchTableMatchesJobKind::test_job_kind_equals_dispatch_table"
        status: pass
    human_judgment: false
  - id: D6
    description: "The pre-existing swallowed-catastrophic-start-failure gap is pinned by a named test rather than left as a paragraph, so a future fix has a concrete red-to-green target"
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py::test_swallowed_start_failure_marks_the_job_done_KNOWN_GAP_FAIL01"
        status: pass
    human_judgment: false

duration: ~20min
completed: 2026-07-14
status: complete
---

# Phase 16 Plan 06: Queue Execution Layer Summary

**`app/queue/` — the D-09 in-process wake signal, the BOUND-01-safe kind-to-handler dispatch table, `handle_run_pipeline`'s reclaim rewind + restated INVARIANT J-1 CAS, `drain_once()`'s claim/dispatch/complete-or-fail cycle, and an AST-based J-1 CAS-only guard that resolves the whole first-party import graph and fails closed on six independent bypass shapes — all hermetic, all 24 tests passing, all twelve falsifying mutations executed live against real files and confirmed red.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 3 of 3 completed
- **Files modified:** 8 (7 created, 1 modified)

## Accomplishments

- `app/queue/wake.py`: a module-level `threading.Event` (`wake`/`wait`/`clear`) replacing LISTEN/NOTIFY entirely — Supavisor transaction-mode pooling silently no-ops both, and the producer (an HTTP route) and consumer (a worker thread) share one process in this deployment. Docstring states the one way to get it wrong: firing `wake()` before the enqueuing transaction commits races the woken worker ahead of visibility.
- `app/queue/dispatch.py`: `HANDLERS` maps `JobKind.RUN_PIPELINE` to `(pipeline_module, "handle_run_pipeline")`, resolved via `getattr` at dispatch time so a test's `monkeypatch.setattr(pipeline, "handle_run_pipeline", stub)` seam stays live. `handle()` raises on an unknown kind rather than silently no-op'ing.
- `app/queue/handlers/pipeline.py`: `handle_run_pipeline` — the restated INVARIANT J-1's two permitted CAS writers (`claim_status` the sole forward transition, `rewind_for_reclaim` the sole `attempts>1`-gated recovery transition), in the order the ordered-call-sequence test proves. `orchestrator.py`'s own unconditional `EXTRACTING` write is untouched (`git diff --stat` empty, confirmed).
- `app/queue/drain.py`: `drain_once()` — claim, dispatch, complete-or-fail, both fenced on the exact `lease_token` the claim returned; `held_tokens()` for graceful-shutdown lease release; `_backoff_seconds` — exponential, capped, jittered, deterministic under a stubbed rand source.
- `tests/test_queue_drain.py` (15 tests): all five `handle_run_pipeline` behaviors, all five `drain_once` behaviors, the ordered-call-sequence proof for both J-1 branches, the pre-existing swallowed-start-failure pin, and the two-part J-1 CAS-only guard (the guard itself + its anti-vacuity proof) — a from-scratch AST resolver that walks the whole first-party import graph, not merely names bound to `repo`.
- `tests/test_job_kind_drift.py` (+1 test, 9 total): `set(JobKind) == set(dispatch.HANDLERS)`, the third and final leg of the collision/enum-drift/dispatch-drift guard.
- Full hermetic suite green (751 passed, 2 unrelated skips against a real Postgres 16 database), `mypy app`/`mypy tests` (strict) clean, `ruff check .` clean, `tests/test_bound01_private_imports.py` and `tests/test_comment_provenance_guard.py` both green.

## Task Commits

Each task was committed atomically:

1. **Task 1: `app/queue/wake.py` + `dispatch.py` — the wake signal and kind-to-handler table** — `8dadf34` (feat)
2. **Task 2: `app/queue/handlers/pipeline.py` — the reclaim rewind and INVARIANT J-1's CAS** — `82d6e72` (feat)
3. **Task 3: `app/queue/drain.py` + the drain/J-1/D-01 proofs + the dispatch half of Proof 5** — `edd6c52` (test)

**Plan metadata:** committed by the orchestrator after wave merge (this executor runs in worktree mode and does not write STATE.md/ROADMAP.md).

## Files Created/Modified

- `app/queue/__init__.py` — package docstring only, no re-exports (NEW)
- `app/queue/wake.py` — `wake`/`wait`/`clear` (NEW)
- `app/queue/dispatch.py` — `HANDLERS`, `handle` (NEW)
- `app/queue/handlers/__init__.py` — package docstring only, no re-exports (NEW)
- `app/queue/handlers/pipeline.py` — `handle_run_pipeline` (NEW)
- `app/queue/drain.py` — `drain_once`, `held_tokens`, `_backoff_seconds` (NEW)
- `tests/test_queue_drain.py` — 15 hermetic tests + the AST resolver (NEW)
- `tests/test_job_kind_drift.py` — `TestDispatchTableMatchesJobKind` appended below the plan-16-05 placeholder marker

## Decisions Made

- `handle_run_pipeline` raises on `job.run_id is None` even though the `jobs` table's own CHECK constraint makes this unreachable — a type-narrowing defensive raise rather than an `assert` (assertions can be stripped under `-O`), consistent with the codebase's existing `enqueue_job` precedent.
- The J-1 CAS-only guard's Pass 3 assertion is NEGATIVE/subset-based (`observed_status_writers <= permitted`) rather than exact equality, so it is vacuously true on an empty resolved-call set — this is precisely what makes `test_the_guard_actually_resolves_the_queue_tiers_real_calls` a necessary, non-redundant second test, and it is exactly what falsifying mutation (l) proves.
- `_backoff_seconds` uses `base=5.0s` / `cap=300.0s`, chosen as reasonable numeric defaults (the planning research fixed the FORMULA shape — `min(cap, base * 2**(attempts-1)) * uniform(0.5, 1.5)` — but not specific numbers) against a queue whose `LEASE_SECONDS` default is 900s and `MAX_ATTEMPTS` default is 5.
- The swallowed-start-failure pin asserts the run lands at `EXTRACTING`, not `RECEIVED` — this handler's own forward CAS always fires before `run_pipeline_bg` is ever called, so the run is visibly further along mid-flight than a description written before this handler's CAS existed would suggest; the test states this precisely rather than copying a now-inexact expectation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] A `pipeline.py` docstring line tripped the repo's own retryable/terminal-taxonomy guard**
- **Found during:** Task 3 (running the plan's own acceptance-criteria grep after writing the tests)
- **Issue:** The plan's own acceptance criteria requires `grep -vE '^\s*#' app/queue/handlers/pipeline.py | grep -cE '(retryable|terminal)'` to equal 0 (no rich failure-taxonomy language in executable code). One line inside `handle_run_pipeline`'s module docstring — prose explaining that no such taxonomy is built yet — used the literal words "retryable" and "terminal" together, and since a module docstring is a string literal (not a `#`-prefixed comment), the `grep -vE '^\s*#'` strip did not remove it, so it counted as "executable code" under this exact check.
- **Fix:** Reworded the sentence to convey the identical meaning ("a rich, multi-outcome failure-classification contract") without using either literal word. No behavior change.
- **Files modified:** `app/queue/handlers/pipeline.py`
- **Verification:** `grep -vE '^\s*#' app/queue/handlers/pipeline.py | grep -cE '(retryable|terminal)'` → 0. Full suite re-run green (751 passed).
- **Committed in:** `edd6c52` (Task 3 commit, alongside the tests that depend on this file)

---

**Total deviations:** 1 auto-fixed (1 bug — a docstring wording fix required by the plan's own acceptance-criteria grep)
**Impact on plan:** No scope creep; no behavior change; purely a wording fix to satisfy a criterion the plan itself specifies.

## Falsifying Mutations Executed

All TWELVE falsifying mutations from the plan's frontmatter and acceptance criteria were executed against real, unmutated source files in this worktree (never a synthetic fixture), confirmed RED, and reverted with a byte-identical diff check (`diff` against a pre-mutation backup) before moving to the next mutation. The final, post-revert suite is the one committed.

### (a) Handler re-raises instead of returning cleanly on a lost CAS

```
FAILED tests/test_queue_drain.py::test_handler_attempts_1_computed_cas_loses_no_run
FAILED tests/test_queue_drain.py::test_handler_attempts_2_reconciled_rewind_is_a_noop_cas_loses
E           RuntimeError: mutation (a): re-raise on a lost CAS
2 failed, 13 deselected in 0.17s
```
Reverted; `diff` against backup empty.

### (b) Remove the `attempts > 1` rewind preamble

```
FAILED tests/test_queue_drain.py::test_handler_attempts_2_extracting_rewinds_then_cas_wins
FAILED tests/test_queue_drain.py::test_first_durable_action_is_a_cas_on_both_branches
E       AssertionError: ['claim_status']
E       assert ['claim_status'] == ['rewind_for_reclaim', 'claim_status']
2 failed, 13 deselected in 0.18s
```
Reverted; `diff` against backup empty. (Proves the reclaim would have stranded the run: the forward CAS could never win on a run sitting at EXTRACTING/COMPUTED/SENT with no rewind ahead of it.)

### (c) Make the rewind guard unconditional (drop `attempts > 1`)

```
FAILED tests/test_queue_drain.py::test_first_durable_action_is_a_cas_on_both_branches
E       AssertionError: ['rewind_for_reclaim', 'claim_status']
E       assert ['rewind_for_reclaim', 'claim_status'] == ['claim_status']
1 failed, 14 deselected in 0.17s
```
Reverted; `diff` against backup empty. (Proves an unconditional rewind would clobber a first-attempt CAS loss that legitimately means "someone else already advanced this run.")

### (d) Add a `JobKind` member with no `HANDLERS` entry

```
FAILED tests/test_job_kind_drift.py::TestDispatchTableMatchesJobKind::test_job_kind_equals_dispatch_table
E       AssertionError: assert {'phantom_kind', 'run_pipeline'} == {<JobKind.RUN_PIPELINE: 'run_pipeline'>}
E       Extra items in the left set:
E       'phantom_kind'
1 failed, 8 deselected in 0.17s
```
Reverted; `diff` against backup empty.

### (e) Add a `repo.set_status(...)` call to `handle_run_pipeline`

```
FAILED tests/test_queue_drain.py::test_queue_tier_status_writers_are_cas_only
E       AssertionError: payroll_runs.status may be written from app/queue/ ONLY via claim_status/rewind_for_reclaim; found: ['claim_status', 'rewind_for_reclaim', 'set_status']
1 failed, 14 deselected in 0.17s
```
Reverted; `diff` against backup empty. Names `set_status` exactly.

### (f) `r = repo` then `r.set_status(...)`

```
FAILED tests/test_queue_drain.py::test_queue_tier_status_writers_are_cas_only
E       AssertionError: J-1 CAS-only guard violation(s):
E         .../app/queue/drain.py:115: restricted name 'repo' (bound to 'app.db.repo') appears outside an
            attribute-chain root — as an assignment target/value, a call argument (including getattr),
            a container element, or a return value
1 failed, 14 deselected in 0.17s
```
Reverted; `diff` against backup empty. Red on the restricted-name-escape rule, as required.

### (g) `getattr(repo, "set_status")(...)`

```
FAILED tests/test_queue_drain.py::test_queue_tier_status_writers_are_cas_only
E       AssertionError: J-1 CAS-only guard violation(s):
E         .../app/queue/drain.py:115: restricted name 'repo' (bound to 'app.db.repo') appears outside an
            attribute-chain root — as an assignment target/value, a call argument (including getattr),
            a container element, or a return value
1 failed, 14 deselected in 0.17s
```
Reverted; `diff` against backup empty. Red on the getattr rule (the flagged shape's message explicitly names `getattr` as a caught form).

### (h) `from app.db.repo.runs import set_status` + a bare `set_status(...)` call

```
FAILED tests/test_queue_drain.py::test_queue_tier_status_writers_are_cas_only
E       AssertionError: J-1 CAS-only guard violation(s):
E         .../app/queue/drain.py:27: imports 'set_status' directly out of repo-reaching module
            'app.db.repo.runs' — import the module object instead
1 failed, 14 deselected in 0.17s
```
Reverted; `diff` against backup empty. Red on the dedicated function-import rule, naming `set_status`.

### (i) `import app.db as db` then `db.repo.set_status(...)`

```
FAILED tests/test_queue_drain.py::test_queue_tier_status_writers_are_cas_only
E       AssertionError: payroll_runs.status may be written from app/queue/ ONLY via claim_status/rewind_for_reclaim; found: ['claim_status', 'rewind_for_reclaim', 'set_status']
1 failed, 14 deselected in 0.17s
```
Reverted; `diff` against backup empty. Red on the RESOLVED nested chain (root binding `db` -> `app.db`, then `.repo` -> `app.db.repo`, then `.set_status` -> the terminal function), naming `set_status`. **A guard that only collected names bound to `repo` directly would have been GREEN on this bypass** — this is exactly the import-graph family the resolver exists to close.

### (j) `from app import db` then `db.repo.set_status(...)`

```
FAILED tests/test_queue_drain.py::test_queue_tier_status_writers_are_cas_only
E       AssertionError: payroll_runs.status may be written from app/queue/ ONLY via claim_status/rewind_for_reclaim; found: ['claim_status', 'rewind_for_reclaim', 'set_status']
1 failed, 14 deselected in 0.17s
```
Reverted; `diff` against backup empty. Same resolution path as (i), reached via `ast.ImportFrom` instead of `ast.Import as`.

### (k) `import app.db as db` then `d = db` then `d.repo.set_status(...)`

```
FAILED tests/test_queue_drain.py::test_queue_tier_status_writers_are_cas_only
E       AssertionError: J-1 CAS-only guard violation(s):
E         .../app/queue/drain.py:117: restricted name 'db' (bound to 'app.db') appears outside an
            attribute-chain root — as an assignment target/value, a call argument (including getattr),
            a container element, or a return value
1 failed, 14 deselected in 0.17s
```
Reverted; `diff` against backup empty. Red on the restricted-name-ESCAPE rule (`d = db` — `db`'s bare appearance as an assignment RHS), naming `db`, **NOT** `d` (which is never a bound import name and so the "name rule" a naive by-name guard would apply cannot even see it) — exactly the distinction the plan requires.

### (l) Pass 1 returns an empty binding map (vacuity proof)

```
tests/test_queue_drain.py::test_queue_tier_status_writers_are_cas_only PASSED
tests/test_queue_drain.py::test_the_guard_actually_resolves_the_queue_tiers_real_calls FAILED
E       AssertionError: the resolver found zero repo-targeted calls under app/queue/ — it has stopped
        seeing the code it is supposed to guard
E       assert set()
1 failed, 1 passed, 13 deselected in 0.19s
```
Reverted; `diff` against backup empty. Confirms the exact designed behavior: `test_queue_tier_status_writers_are_cas_only`'s negative/subset checks are vacuously true on an empty resolved-call set and stay GREEN, while `test_the_guard_actually_resolves_the_queue_tiers_real_calls` — the dedicated anti-vacuity, positive-presence proof — goes RED. This is precisely why the second test exists as a non-redundant, separate assertion.

## The J-1 guard, GREEN against the real `app/queue/`

Confirmed as part of every mutation's revert step and the final full-suite run below — no false positive on `dispatch.py`'s `HANDLERS` module-object tuple or its `getattr(module, name)(job)` dispatch (`module`/`name` are local variables from tuple-unpacking, never bound import names, so the guard never even considers them):

```
$ uv run pytest tests/test_queue_drain.py tests/test_job_kind_drift.py -q
........................
24 passed in 0.18s
```

## Full Verification

```
$ uv run pytest -q
751 passed, 2 skipped (unrelated: a Wave-1 stub + the manual live-LLM gate), 1 warning in 3.3s
$ uv run pytest tests/test_bound01_private_imports.py -q
2 passed
$ uv run mypy app
Success: no issues found in 60 source files
$ uv run mypy tests
Success: no issues found in 68 source files
$ uv run ruff check .
All checks passed!
$ git diff --stat app/pipeline/orchestrator.py
(empty)
```

Live Postgres 16 (`wt1606`, an isolated per-agent database) was available in this worktree, and `uv run python -m app.db.bootstrap` was run against it before verification — the full hermetic suite above includes every prior plan's DB-dependent test (751 passed vs. this worktree's earlier plans' 743-and-deferred counts).

## Issues Encountered

None beyond the deviation above.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `app/queue/drain.py::drain_once()` is ready for plan 16-07's worker threads and the future pump to call directly — it is the one shared execution step, deliberately not embedded inside a thread-lifecycle module.
- `app/queue/handlers/pipeline.py::handle_run_pipeline` is ready for plan 16-08's retrigger route to enqueue against — the reclaim rewind's safety for the client depends on plan 16-10's send guard landing before the first live worker in wave 4, exactly as this plan's docstrings state.
- The J-1 CAS-only guard (`tests/test_queue_drain.py::test_queue_tier_status_writers_are_cas_only`) will auto-scan any future file added under `app/queue/` (it globs `QUEUE_ROOT.rglob("*.py")`), so plan 16-07's `worker.py` inherits this guard for free with zero new wiring.
- `test_swallowed_start_failure_marks_the_job_done_KNOWN_GAP_FAIL01` is the concrete red-to-green target for a future fix that turns a swallowed catastrophic START failure into a real retry — it currently asserts `job.state == "done"`; that future fix must invert the assertion, never delete the test.
- No blockers for downstream plans.

---
*Phase: 16-queue-substrate-unblocked-webhook*
*Completed: 2026-07-14*

## Self-Check: PASSED

All 9 claimed files found on disk (app/queue/__init__.py, app/queue/wake.py,
app/queue/dispatch.py, app/queue/handlers/__init__.py,
app/queue/handlers/pipeline.py, app/queue/drain.py, tests/test_queue_drain.py,
tests/test_job_kind_drift.py, this SUMMARY.md). All 3 claimed commit hashes
(8dadf34, 82d6e72, edd6c52) found in `git log --oneline --all`. No missing items.
