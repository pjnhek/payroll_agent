---
phase: 16-queue-substrate-unblocked-webhook
plan: 07
subsystem: infra
tags: [queue, threading, asyncio, fastapi-lifespan, pytest, psycopg-pool]

# Dependency graph
requires:
  - phase: 16-queue-substrate-unblocked-webhook (plan 02)
    provides: "queue Settings knobs (worker_count, lease_seconds, max_attempts, queue_poll_seconds); the queueproof marker"
  - phase: 16-queue-substrate-unblocked-webhook (plan 04)
    provides: "app/db/repo/jobs.py claim/lease/fencing protocol (release_leases used unconditionally by stop()); tests/test_queue_durability.py's _isolated_jobs/live_worker fixtures, which this plan's tests append to"
  - phase: 16-queue-substrate-unblocked-webhook (plan 06)
    provides: "app/queue/drain.py (drain_once/held_tokens), app/queue/wake.py (wake/wait/clear) — the execution layer this plan's worker threads drive"
  - phase: 16-queue-substrate-unblocked-webhook (plan 10)
    provides: "the fail-closed unconfirmed-send guard, merged before this plan's first live workers could ever reclaim an expired lease"
provides:
  - "app/queue/worker.py — start(n)/stop(grace_seconds)/lifespan(app), POOL_BUDGET_RESERVE=2, _LIFECYCLE_LOCK, per-generation stop Event, orphan tracking"
  - "app/db/supabase.py::POOL_MAX_SIZE=5 — the shared connection-budget constant the worker's boot-time guard compares against"
  - "app/main.py — the app's first-ever FastAPI lifespan (lifespan=worker.lifespan)"
  - "tests/test_queue_worker.py — 10 hermetic proofs of the worker lifecycle"
  - "tests/test_queue_durability.py — Proof 4 (live), the quiesce-mechanism proof, the live restart proof, and an AST-based static guard"
affects: [16-08, 16-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A per-generation threading.Event, minted fresh in start() and passed to each worker thread as a plain function argument (never a module global the thread reads), is what makes stop()-then-start() actually restart drain capacity instead of spawning corpses that observe an already-set event."
    - "One threading.Lock held across the ENTIRE body of both start() and stop() (not per-field) is the serialization primitive; the worker loop itself never acquires it, which is what makes holding it across thread.join(...) safe from deadlock."
    - "A thread that survives a timed-out join moves into a tracked _orphans list rather than being forgotten — start() refuses to spawn a new generation while any orphan is alive, closing the connection-budget escape hatch that lease fencing alone does not close."
    - "A boot-time connection-pool budget guard (worker_count + reserve > pool max_size) raises RuntimeError rather than clamping, mirroring the existing fail-fast posture for a missing DATABASE_URL."
    - "asyncio.run() drives an @asynccontextmanager lifespan function directly in a hermetic pytest test with no pytest-asyncio dependency — the project's first async test code, using only the stdlib."

key-files:
  created:
    - app/queue/worker.py
    - tests/test_queue_worker.py
  modified:
    - app/db/supabase.py
    - app/main.py
    - tests/test_queue_durability.py
    - tests/test_demo_landing.py

key-decisions:
  - "_loop rechecks stop_evt.is_set() a second time immediately after wake.clear() and before wake.wait() — found during manual verification, not specified in the plan text. Without it, a stop() that fires while a thread is mid-drain_once() sets the stop event and wakes the signal before the thread ever reaches wake.clear(), which then erases the pending wakeup; the thread would sleep out the full queue_poll_seconds before noticing the stop request. The extra check closes that gap so a stop is never slower than one drain_once()/clear() pair plus a lock acquisition."
  - "test_stop_serializes_a_concurrent_stop counts entries into the wedged held_tokens() stub rather than asserting 'the second stop() call has not completed yet' — found while executing the D-20 falsifying mutation. The original design wedged both callers on the SAME shared proceed Event, so a second caller with no lock at all still appeared to 'not complete' for an unrelated reason (it reached the same wedge independently), making the mutation's expected red not actually fire on that assertion. Counting wedge ENTRIES discriminates correctly: under the real lock the second caller can never reach the wedge while the first is inside it; under the mutation it reaches it immediately."
  - "test_quiesce_releases_a_blocked_handler_and_joins_to_zero accepts the job row ending at EITHER pending or done, not only pending as the plan's prose states. _quiesce_workers releases every blocker BEFORE calling stop(), so a handler that returns immediately once unblocked can legitimately race ahead and complete the job through the normal complete_job path before stop()'s own release_leases call ever observes it still leased. complete_job clears lease_token/leased_until exactly like release_leases does, so both outcomes are safe and the property that actually matters — no live worker thread survives and no row is left dangling in leased — holds either way."

requirements-completed: [QUEUE-03]

coverage:
  - id: D1
    description: "A bounded pool of daemon worker threads is started and stopped by the app's FastAPI lifespan; a worker count that would starve the connection pool refuses to boot"
    requirement: "QUEUE-03"
    verification:
      - kind: unit
        ref: "tests/test_queue_worker.py::test_worker_count_zero_starts_no_threads, ::test_lifespan_refuses_to_start_when_the_pool_budget_is_violated, ::test_lifespan_starts_and_stops_the_configured_workers"
        status: pass
    human_judgment: false
  - id: D2
    description: "A graceful shutdown releases every lease the process holds immediately, even from a worker still running a blocked handler, and the resulting zombie is fenced out rather than corrupting the row"
    requirement: "QUEUE-03"
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py::test_graceful_shutdown_releases_held_leases_immediately"
        status: pass
    human_judgment: false
  - id: D3
    description: "Workers wake instantly on an in-process signal and otherwise poll slowly; a stop request is never slower than one drain/clear cycle"
    requirement: "QUEUE-03"
    verification:
      - kind: unit
        ref: "tests/test_queue_worker.py::test_wake_breaks_the_poll_immediately"
        status: pass
    human_judgment: false
  - id: D4
    description: "A second start() while a previous generation is still alive is refused (tracked as an orphan, not forgotten); stop() is idempotent"
    requirement: "QUEUE-03"
    verification:
      - kind: unit
        ref: "tests/test_queue_worker.py::test_start_refuses_while_a_previous_generation_is_still_alive, ::test_stop_is_idempotent"
        status: pass
    human_judgment: false
  - id: D5
    description: "A restarted worker (start -> stop -> start) actually drains — proven by an invoked drain_once/a completed real job, never by thread liveness"
    requirement: "QUEUE-03"
    verification:
      - kind: unit
        ref: "tests/test_queue_worker.py::test_a_restarted_worker_actually_drains"
        status: pass
      - kind: integration
        ref: "tests/test_queue_durability.py::test_a_restarted_worker_claims_and_completes_a_real_job"
        status: pass
    human_judgment: false
  - id: D6
    description: "start()/stop() serialize under one lifecycle lock held across the whole transition; release_leases is issued exactly once across N concurrent stop() calls"
    requirement: "QUEUE-03"
    verification:
      - kind: unit
        ref: "tests/test_queue_worker.py::test_stop_serializes_a_concurrent_stop, ::test_concurrent_stops_release_exactly_once"
        status: pass
    human_judgment: false
  - id: D7
    description: "The gen != _generation fence in _loop works when a stale generation is constructed directly (defence-in-depth, unreachable through the public lifecycle)"
    requirement: "QUEUE-03"
    verification:
      - kind: unit
        ref: "tests/test_queue_worker.py::test_a_stale_generation_thread_winds_itself_down"
        status: pass
    human_judgment: false
  - id: D8
    description: "The abort-path quiesce mechanism (_quiesce_workers) actually releases a blocked handler and joins the pool to zero live threads, driven directly rather than only exercised when a test body dies"
    requirement: "QUEUE-03"
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py::test_quiesce_releases_a_blocked_handler_and_joins_to_zero"
        status: pass
    human_judgment: false

duration: ~55min
completed: 2026-07-14
status: complete
---

# Phase 16 Plan 07: Queue Worker Lifecycle Summary

**`app/queue/worker.py` — 2 daemon worker threads owned by the app's first-ever FastAPI lifespan, a boot-time connection-pool budget guard that raises rather than clamps, a fresh per-generation stop Event that makes a restarted worker actually drain, one lifecycle lock serializing start()/stop(), and an unconditional graceful-shutdown lease release proven against a real held lease on a real Postgres database.**

## Performance

- **Duration:** ~55 min
- **Tasks:** 3 of 3 completed
- **Files modified:** 6 (2 created, 4 modified)

## Accomplishments

- `app/db/supabase.py`: extracted the bare `max_size=5` literal into a shared `POOL_MAX_SIZE` constant, used at the `ConnectionPool` call site and by the worker's boot-time guard — one number, one place.
- `app/queue/worker.py`: `start(n)`/`stop(grace_seconds)`/`lifespan(app)`. `POOL_BUDGET_RESERVE = 2`. Four module-state names (`_threads`, `_orphans`, `_generation`, `_stop`) mutated only under one `_LIFECYCLE_LOCK` held across the complete body of both `start()` and `stop()`. A fresh `threading.Event()` minted per generation and passed to each thread as an argument — nothing in the module ever calls `.clear()` on a stop event. A thread that survives a timed-out join is tracked as an orphan, never forgotten; `start()` refuses to spawn a new generation while any orphan is alive. `stop()` calls `repo.release_leases(drain.held_tokens())` unconditionally, even when a join times out — the whole mechanism ROADMAP criterion #4 is about. `lifespan()` raises `RuntimeError` before ever starting a thread when `worker_count + POOL_BUDGET_RESERVE > POOL_MAX_SIZE`.
- `app/main.py`: the app's first-ever `lifespan=worker.lifespan` wired into the `FastAPI(...)` constructor — the entire change, per the file's own "thin app assembly only" docstring.
- `tests/test_queue_worker.py` (10 hermetic tests, no live DB): `worker_count=0` no-op, the D-07 pool-budget refusal (and its exactly-at-budget acceptance), the lifespan starting/stopping the configured count, `wake()` breaking a 60-second poll almost instantly via a race-free Event handshake, `stop()`'s idempotence, the second-start orphan guard (and that it is a real liveness check, not a permanent latch), the restart-drains proof (asserting an invoked `drain_once`, never `is_alive()`), the lifecycle-lock's deterministic serialization proof, exactly-once `release_leases` across 4 concurrent `stop()` calls, and the stale-generation fence.
- `tests/test_queue_durability.py` (+4 tests, live Postgres): Proof 4 — a real held lease, released immediately by `worker.stop()` while its handler is still blocked, with the resulting zombie's `complete_job` fenced out; the quiesce-mechanism proof driven directly against a genuinely blocked worker; the live restart proof (job B reaches `done`, read back by its own id); and an AST-based static guard that every `worker.start(...)` call in the file goes through the `live_worker` fixture (carving out only the fixture's own sanctioned wrapper).
- Found and fixed a real timing gap during manual verification, before any test caught it: a stop request arriving while a worker thread is mid-`drain_once()` could erase its own wake signal and sleep out the full poll interval before noticing. Fixed with a second `stop_evt` check immediately after `wake.clear()`.
- Full suite green against a live Postgres (774 passed, 2 skipped — an unrelated live-LLM gate) and hermetically with no DB (708 passed, 68 skipped). `uv run mypy app tests` (strict) clean. `uv run ruff check .` clean. `tests/test_comment_provenance_guard.py` and `tests/test_bound01_private_imports.py` both green.

## Task Commits

Each task was committed atomically:

1. **Task 1: `app/queue/worker.py` — bounded worker pool, D-07 budget guard, per-generation stop event** — `c8e289b` (feat)
2. **Task 2: wire `worker.lifespan` into `app/main.py`; `tests/test_queue_worker.py`** — `7447ba8` (test)
3. **Task 3: Proof 4 (live), the quiesce proof, and the live restart proof** — `43ec6e2` (test)

**Plan metadata:** committed by the orchestrator after wave merge (this executor runs in worktree mode and does not write STATE.md/ROADMAP.md).

## Files Created/Modified

- `app/queue/worker.py` — `start`, `stop`, `_loop`, `lifespan`, `POOL_BUDGET_RESERVE`, `_LIFECYCLE_LOCK` (NEW)
- `app/db/supabase.py` — `POOL_MAX_SIZE` constant, used at the `ConnectionPool` call site
- `app/main.py` — `lifespan=worker.lifespan` passed to `FastAPI(...)`
- `tests/test_queue_worker.py` — 10 hermetic worker-lifecycle proofs (NEW)
- `tests/test_queue_durability.py` — Proof 4, the quiesce proof, the live restart proof, the AST static guard; dropped a now-stale `type: ignore[import-not-found]`; reworded four comments that had tripped the comment-provenance guard
- `tests/test_demo_landing.py` — an autouse `DATABASE_URL` stub fixture for the 10 `with TestClient(...) as tc:` tests, which now execute the app's first lifespan

## Decisions Made

- `_loop` rechecks `stop_evt.is_set()` immediately after `wake.clear()` and before `wake.wait()` — not in the plan text, found during manual verification of the second-start guard scenario (a thread blocked at drain time takes up to `queue_poll_seconds` to notice a stop otherwise).
- `test_stop_serializes_a_concurrent_stop` was rewritten mid-execution to count entries into the wedged `held_tokens()` stub rather than checking whether the second `stop()` call had completed — the original design's "did not complete" assertion was satisfied by the shared wedge Event even with `_LIFECYCLE_LOCK` removed, which would have made the D-20 falsifying mutation pass against the exact bug it exists to catch. Verified: the rewritten assertion reds correctly under the mutation and stays green on the fix.
- `test_quiesce_releases_a_blocked_handler_and_joins_to_zero` accepts the job ending at either `pending` or `done`, deviating from the plan's literal "back to pending" expectation — `_quiesce_workers` (pre-existing, from plan 16-04) releases its blockers before calling `stop()`, so a handler that returns immediately once released legitimately races ahead to a normal completion; both terminal states clear `lease_token`, and both are safe.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_loop` could sleep out the full poll interval before noticing a stop request**
- **Found during:** Task 1, manual verification of the second-start-guard scenario
- **Issue:** A stop request arriving while a worker thread is mid-`drain_once()` sets the stop event and calls `wake.wake()` before the thread ever reaches `wake.clear()`/`wake.wait()`. The thread's own `wake.clear()` call then erases that pending signal, and it proceeds to block on `wake.wait(timeout=queue_poll_seconds)` with no way to notice the stop request until the full poll interval elapses (or the next legitimate wakeup arrives). Manually reproduced: an orphan constructed this way took up to 20s (the default poll interval) to die instead of exiting promptly.
- **Fix:** Added an explicit `if stop_evt.is_set(): return` immediately after `wake.clear()` and before `wake.wait()`. Verified via a manual reproduction script: the orphan now dies within its join timeout instead of the full poll interval.
- **Files modified:** `app/queue/worker.py`
- **Verification:** Manual script reproduction before/after; `tests/test_queue_worker.py::test_start_refuses_while_a_previous_generation_is_still_alive`'s post-release re-`start()` step relies on prompt death and passes reliably across 5 repeated runs.
- **Committed in:** `c8e289b` (Task 1 commit)

**2. [Rule 3 - Blocking] Wiring the lifespan broke 10 pre-existing `with TestClient(...) as tc:` tests that never set `DATABASE_URL`**
- **Found during:** Task 2, first full-suite run after wiring `lifespan=worker.lifespan`
- **Issue:** All 10 route tests in `tests/test_demo_landing.py` that open `with TestClient(fastapi_app, ...) as tc:` now execute the app's lifespan on entry. `lifespan()` calls `get_settings()` eagerly for the D-07 budget guard, and `database_url` has no default — none of these 10 tests previously needed a database (every DB call is monkeypatched), so none of them set `DATABASE_URL`, and `Settings()` validation failed before any route ran.
- **Fix:** Added an autouse `_lifespan_database_url` fixture to `tests/test_demo_landing.py` that stubs `DATABASE_URL` and clears the `get_settings` cache before/after every test in the module, mirroring the existing `mock_llm`/`test_webhook.py` convention.
- **Files modified:** `tests/test_demo_landing.py`
- **Verification:** `uv run pytest tests/test_demo_landing.py -q` → 25 passed (was 10 failed / 15 passed before the fix).
- **Committed in:** `7447ba8` (Task 2 commit)

**3. [Rule 1 - Bug] `tests/test_queue_durability.py`'s `_LiveWorkerHandle.start()` carried a now-stale `type: ignore[import-not-found]`**
- **Found during:** Task 3, `uv run mypy app tests` after appending the new tests
- **Issue:** That comment and suppression predate this plan (`app.queue.worker` did not exist when 16-04 wrote it). Now that the module exists, the unused `type: ignore` itself became a mypy error (`unused-ignore`).
- **Fix:** Removed the stale suppression and its explanatory comment; the deferred import is retained (mirrors `_quiesce_workers`' own deferred import of the same module).
- **Files modified:** `tests/test_queue_durability.py`
- **Verification:** `uv run mypy app tests` → clean (132 source files).
- **Committed in:** `7447ba8` (Task 2 commit)

**4. [Rule 1 - Bug] Four new comments cited a design-decision ID, tripping the repo's own comment-provenance guard**
- **Found during:** Task 3, full-suite run after appending the live-DB tests
- **Issue:** `release_me = live_worker.blocker()  # minted BY THE FIXTURE (D-19) — ...`, two `live_worker.start(n=1)  # never worker.start() directly (D-19)` lines, and the new AST guard's leading comment all cited `(D-19)` directly — exactly the pattern `tests/test_comment_provenance_guard.py` is built to catch, and exactly the trap this plan's own briefing warned about in advance.
- **Fix:** Reworded all four to state the constraint directly with no ticket citation (e.g. "never `worker.start()` directly" with the parenthetical dropped).
- **Files modified:** `tests/test_queue_durability.py`
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py -q` → 5 passed (was 1 failed).
- **Committed in:** `43ec6e2` (Task 3 commit)

---

**Total deviations:** 4 auto-fixed (1 bug found by manual reasoning ahead of any test, 1 blocking test-suite breakage, 1 stale-suppression bug, 1 comment-provenance violation)
**Impact on plan:** No scope creep. Deviation 1 is a genuine correctness fix to the mechanism the plan's own success criteria describe ("wake instantly ... never the DB is the latency path"). Deviations 2-4 are direct, foreseeable consequences of this plan's own required changes (the app's first lifespan; a new module existing; new test comments), fixed the same way plan 16-04 fixed its own analogous `WORKER_COUNT=0` fallout.

## Falsifying Mutations Executed

All mutations were executed against the real, unmutated source files in this worktree, confirmed RED, and reverted with a byte-identical `diff` check against a pre-mutation backup before moving to the next mutation.

### 1. D-07: clamp-and-warn instead of raise

```
FAILED tests/test_queue_worker.py::test_lifespan_refuses_to_start_when_the_pool_budget_is_violated
E       Failed: lifespan must raise before yielding when over budget
------------------------------ Captured log call -------------------------------
WARNING  payroll_agent.queue:worker.py:260 MUTATION: clamped worker_count to 3
1 failed in 0.20s
```
Reverted; `diff` against backup empty.

### 2. Second-start guard: revert `stop()` to clearing `_threads` unconditionally after a timed-out join

```
FAILED tests/test_queue_worker.py::test_start_refuses_while_a_previous_generation_is_still_alive
E       IndexError: list index out of range
    orphan = worker._orphans[0]
FAILED tests/conftest.py::_no_leaked_queue_workers (teardown)
E       Failed: leaked queue-worker thread(s) still alive after test teardown: queue-worker-1-0 (daemon=True)
1 failed, 1 error in 0.30s
```
Reverted; `diff` against backup empty. (The orphan list is empty because the mutation forgot the still-alive thread instead of tracking it — the collateral leak-guard failure is the expected knock-on effect.)

### 3. D-15 (hermetic): a single module-level stop `Event` that `start()` never resets

```
FAILED tests/test_queue_worker.py::test_a_restarted_worker_actually_drains
E       AssertionError: the restarted worker's drain_once was never invoked — the second generation observed a still-set stop event from the first
E       assert False
E        +  where False = wait(timeout=5.0)
1 failed in 5.21s
```
Reverted; `diff` against backup empty. **Observation recorded, as required:** a direct check confirmed the restarted thread was `is_alive() == False` within ~0.1s under this mutation (it exits almost instantly on its very first loop iteration, having never called `drain_once`) — a naive immediate `is_alive()` assertion is therefore vacuous here regardless of timing; the plan's own "vacuous twin" characterization is about checking liveness at all, not about the exact instant checked. This is exactly why every restart proof in this plan asserts an invoked `drain_once`/a completed job, never liveness.

### 4. D-20: remove `_LIFECYCLE_LOCK` from `stop()`, leaving it in `start()`

```
FAILED tests/test_queue_worker.py::test_stop_serializes_a_concurrent_stop
E       AssertionError: the second concurrent stop() reached the wedged held_tokens() call while the first was still inside it — entered_wedge=['stopper-a', 'stopper-b']. This means _LIFECYCLE_LOCK did not serialize the two stop() calls.
E       assert ['stopper-a', 'stopper-b'] == ['stopper-a']
1 failed in 1.21s

FAILED tests/test_queue_worker.py::test_concurrent_stops_release_exactly_once
E       AssertionError: release_leases must be issued exactly once across 4 concurrent stop() calls; got 4
E       assert 4 == 1
1 failed in 0.16s
```
Both reds captured (the second run in isolation, to avoid a leaked thread from the first mutated run's abandoned wedge contaminating its collection). Reverted; `diff` against backup empty.

### 5. D-21: delete `or gen != _generation` from `_loop`'s first line

```
FAILED tests/test_queue_worker.py::test_a_stale_generation_thread_winds_itself_down
E       AssertionError: the stale-generation thread did not exit — the gen != _generation fence in _loop did not fire
E       assert not True
E        +  where True = is_alive()
1 failed, 1 error in 5.24s
```
Reverted; `diff` against backup empty. **Confirmed as documented:** this fence is defence-in-depth, unreachable through the public `start()`/`stop()` lifecycle — `start()` already refuses while any previous-generation thread or orphan is alive, so a stale generation can never coexist with a new one except by directly poking `worker._generation`, exactly as this test does. Its docstring says so explicitly and this SUMMARY does not present it as a proven production guarantee.

### 6. Proof 4 (live): `worker.stop()` joins but does not release

```
FAILED tests/test_queue_durability.py::test_graceful_shutdown_releases_held_leases_immediately
E       AssertionError: worker.stop() must release the held lease IMMEDIATELY, without waiting out LEASE_SECONDS
E       assert 'leased' == 'pending'
------------------------------ Captured log call -------------------------------
WARNING  payroll_agent.queue:worker.py:233 queue worker stop(): 1 thread(s) did not exit within grace_seconds=1; tracking as orphan(s) rather than forgetting them
1 failed in 1.34s
```
Reverted; `diff` against backup empty. `live_worker`'s own teardown quiesced the still-blocked handler cleanly (releasing it, stopping, joining) — no leaked thread survived the failing test.

### 7. D-15 (live): a single shared stop Event that `start()` never resets

```
FAILED tests/test_queue_durability.py::test_a_restarted_worker_claims_and_completes_a_real_job
E       AssertionError: the restarted worker's dispatch was never invoked for job B — generation 2 likely observed generation 1's still-set stop event
E       assert False
E        +  where False = wait(timeout=30.0)
1 failed in 30.32s
```
Reverted; `diff` against backup empty. (Took the full 30-second blocker timeout to fail — a genuine hang under this defect, exactly as the plan describes: "job B stays pending forever.")

### 8. D-19: delete the `for evt in blockers: evt.set()` loop from `_quiesce_workers`

```
FAILED tests/test_queue_durability.py::test_quiesce_releases_a_blocked_handler_and_joins_to_zero
E       Failed: queue worker thread(s) did not quiesce within the join budget: queue-worker-1-0
------------------------------ Captured log call -------------------------------
WARNING  payroll_agent.queue:worker.py:233 queue worker stop(): 1 thread(s) did not exit within grace_seconds=5.0; tracking as orphan(s) rather than forgetting them
1 failed, 1 error in 15.37s
```
Reverted; `diff` against backup empty. `_quiesce_workers` FAILS LOUDLY exactly as required, and the module's own `_isolated_jobs` delete-gate independently refused to proceed with the still-live thread (the collateral `ERROR`) — both safety mechanisms fired correctly under this mutation.

## D-21 disclosure (required, verbatim per the plan)

The `gen != _generation` fence in `_loop` is **defence-in-depth, unreachable through the public lifecycle** — `start()` refuses to spawn a new generation while any previous-generation thread or orphan is still alive, so a stale generation cannot coexist with a live one through normal `start()`/`stop()` usage. `test_a_stale_generation_thread_winds_itself_down` constructs that state directly by poking `worker._generation`, and it says so in its own docstring. It proves the fence WORKS. It does **not** prove the fence is ever REACHED in production, and nothing in this SUMMARY or the test suite presents it as a proven production guarantee.

## Issues Encountered

None beyond the deviations documented above.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `app/queue/worker.py` is the queue's running body: plan 16-08's retrigger route can now rely on a live worker pool actually picking up an `enqueue_job` call within seconds via the wake signal, and plan 16-09's Proof 2 can append to `tests/test_queue_durability.py` and inherit the same `_isolated_jobs`/`live_worker` fixture ordering this plan's own tests depend on.
- ROADMAP criterion #4 (graceful shutdown releases held leases immediately) is proven live against a real Postgres database, not merely at the repo layer.
- No blockers for downstream plans.

---
*Phase: 16-queue-substrate-unblocked-webhook*
*Completed: 2026-07-14*

## Self-Check: PASSED

All 6 claimed files found on disk (app/queue/worker.py, tests/test_queue_worker.py,
app/db/supabase.py, app/main.py, tests/test_queue_durability.py,
tests/test_demo_landing.py). All 3 claimed commit hashes (c8e289b, 7447ba8, 43ec6e2)
found in `git log --oneline --all`. No missing items.
