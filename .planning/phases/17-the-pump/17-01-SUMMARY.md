---
phase: 17-the-pump
plan: 01
subsystem: queue
tags: [python, enum, strenum, pytest, mypy, queue-drain]

# Dependency graph
requires:
  - phase: 16-queue-substrate-unblocked-webhook
    provides: the `jobs` table, `repo.claim_job`/`complete_job`/`fail_job`, and the original `drain_once() -> bool` this plan enriches
provides:
  - "`DrainOutcome` StrEnum (empty/done/retried/dead/fenced) in app/queue/drain.py with EMPTY as the sole falsy member"
  - "`drain_once() -> DrainOutcome`, capturing repo.complete_job's bool / repo.fail_job's JobState|None into the specific settled outcome instead of discarding it"
  - "the fail_job()-itself-fails double-failure branch now RE-RAISES instead of returning a truthy FENCED, so a genuine DB outage propagates rather than reporting false success"
  - "a worker-loop survival test proving worker.py:203 catches a propagated drain_once() exception and the loop resumes polling"
affects: ["17-02 (count_open_jobs)", "17-04 (the pump route, which aggregates DrainOutcome counts and turns a propagated exception into a 503)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "capture-don't-thread: repo.complete_job/repo.fail_job signatures unchanged; drain_once() only captures what they already return"
    - "settled-fence vs infra-failure distinction: FENCED is reserved for a write that landed but matched zero rows; a write that itself raised re-raises instead"

key-files:
  created: []
  modified:
    - app/queue/drain.py
    - tests/test_queue_drain.py
    - tests/test_hitl.py
    - tests/test_alias_and_run_column_regressions.py
    - tests/test_stuck_run_recovery.py
    - tests/test_retrigger_threading.py
    - tests/test_queue_durability.py
    - tests/test_queue_worker.py

key-decisions:
  - "The double-failure branch (fail_job() itself raising) re-raises rather than mapping to DrainOutcome.FENCED, so a real DB outage cannot be silently reported as a truthy/successful outcome by any caller (worker or, later, the pump route)."
  - "Added two new drain_once() behavior tests (DEAD, FENCED) to test_queue_drain.py since neither prior test suite exercised those two outcomes directly — needed so all five DrainOutcome members have real, non-comment coverage in the module."

requirements-completed: [PUMP-01]

coverage:
  - id: D1
    description: "drain_once() returns DrainOutcome.EMPTY on an empty queue, and DrainOutcome.EMPTY is the only falsy member (worker.py:198's truthiness contract preserved)"
    requirement: "PUMP-01"
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py::test_drain_once_empty_queue_returns_false_and_dispatches_nothing"
        status: pass
    human_judgment: false
  - id: D2
    description: "drain_once() returns the specific settled outcome (DONE/RETRIED/DEAD/FENCED) for each terminal branch, captured from repo.complete_job's bool and repo.fail_job's JobState|None"
    requirement: "PUMP-01"
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py::test_drain_once_claims_dispatches_and_completes_with_the_same_token"
        status: pass
      - kind: unit
        ref: "tests/test_queue_drain.py::test_drain_once_handler_raises_calls_fail_job_not_complete_job"
        status: pass
      - kind: unit
        ref: "tests/test_queue_drain.py::test_drain_once_dispatch_raises_at_max_attempts_returns_dead"
        status: pass
      - kind: unit
        ref: "tests/test_queue_drain.py::test_drain_once_complete_job_fenced_out_returns_fenced"
        status: pass
    human_judgment: false
  - id: D3
    description: "The fail_job()-itself-fails double-failure branch re-raises out of drain_once() (never mapped to a truthy FENCED), retaining the lease token; the worker loop catches it and survives"
    requirement: "PUMP-01"
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py::test_a_failed_fail_job_keeps_the_lease_recorded"
        status: pass
      - kind: unit
        ref: "tests/test_queue_worker.py::test_worker_survives_a_propagated_drain_once_exception"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every drain_once() identity assertion (assert ... is True/False) across the six affected test files is rewritten to a specific DrainOutcome comparison"
    requirement: "PUMP-01"
    verification:
      - kind: unit
        ref: "grep -rn \"drain_once() is True|drain_once() is False\" tests/ -> zero hits"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-07-15
status: complete
---

# Phase 17 Plan 1: DrainOutcome Summary

**`drain_once()` now returns a `DrainOutcome` StrEnum (empty/done/retried/dead/fenced, EMPTY-only-falsy) instead of a bare `bool`, and the `fail_job()`-itself-fails double-failure re-raises instead of masquerading as a truthy `FENCED`.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-15T14:05:39Z
- **Completed:** 2026-07-15T14:24:41Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- `DrainOutcome` (StrEnum: EMPTY/DONE/RETRIED/DEAD/FENCED) defined in `app/queue/drain.py` with an overridden `__bool__` so `worker.py:198`'s `if drain.drain_once():` is byte-identical in behavior — EMPTY is the only falsy member.
- `drain_once()` captures `repo.complete_job`'s `bool` and `repo.fail_job`'s `JobState | None` (both already computed, previously discarded) into the specific settled `DrainOutcome` instead of returning a bare `True`.
- The double-failure branch (the failure write itself raising — a genuine DB outage) now re-raises rather than mapping to a truthy `FENCED`, so the eventual pump route (17-04) can turn it into a 503 instead of a false HTTP 200, and the worker loop (`worker.py:203`) catches it and survives.
- All ~15 `assert drain.drain_once() is True/False` identity-check sites across six test files rewritten to assert the *specific* expected `DrainOutcome` — a proof-strengthening rewrite, not a mechanical repair.
- The double-failure test (`test_a_failed_fail_job_keeps_the_lease_recorded`) reconciled to `pytest.raises(RuntimeError, match="simulated database outage")`, retaining its `held_tokens() == [token]` lease-retention assertion verbatim.
- A new worker-loop survival test (`test_worker_survives_a_propagated_drain_once_exception`) proves `worker.py:203`'s `except` catches a propagated `drain_once()` exception and the loop *resumes polling* — confirmed by a second real `drain_once()` invocation after the raise (`calls >= 2` / second-Event handshake), not merely `thread.is_alive()`.
- Two new `drain_once()` behavior tests added (`..._returns_dead`, `..._returns_fenced`) so all five `DrainOutcome` members have real assertion coverage in `test_queue_drain.py`, not just the three the original "five behaviors" section happened to exercise.

## Task Commits

Each task was committed atomically:

1. **Task 1: Define DrainOutcome and enrich drain_once() to return it** - `bd178cc` (feat)
2. **Task 2: Rewrite the drain_once() identity assertions to specific DrainOutcome values; reconcile the double-failure test to pytest.raises; add a worker-loop survival test** - `c529561` (test) — also carries a small drain.py comment fix (see Deviations)

**Plan metadata:** committed as part of this SUMMARY's own commit (state/roadmap/requirements docs)

## Files Created/Modified
- `app/queue/drain.py` - `DrainOutcome` enum + `drain_once() -> DrainOutcome`, capturing existing repo return values; double-failure branch re-raises
- `tests/test_queue_drain.py` - rewrote 6 identity-check sites to specific `DrainOutcome` values; reconciled the double-failure test to `pytest.raises`; added 2 new behavior tests (DEAD, FENCED)
- `tests/test_hitl.py` - rewrote 3 identity-check sites to `DrainOutcome.DONE`
- `tests/test_alias_and_run_column_regressions.py` - rewrote 2 identity-check sites to `DrainOutcome.DONE`
- `tests/test_stuck_run_recovery.py` - rewrote 1 identity-check site to `DrainOutcome.DONE`
- `tests/test_retrigger_threading.py` - rewrote 1 identity-check site to `DrainOutcome.DONE`
- `tests/test_queue_durability.py` - rewrote 1 live-DB assertion (reclaim→success path) to `DrainOutcome.DONE`; updated its docstring's falsifying-mutation reference for consistency
- `tests/test_queue_worker.py` - added `test_worker_survives_a_propagated_drain_once_exception`, a new worker-loop survival test

## Decisions Made
- The double-failure branch re-raises rather than mapping to `DrainOutcome.FENCED` — this was already locked by the plan (overturning 17-RESEARCH Open Question #1 per 17-REVIEWS finding #1); implemented exactly as specified.
- Added DEAD and FENCED behavior tests to `test_queue_drain.py` beyond what the plan's task list enumerated verbatim, because the plan's own acceptance criteria require all five `DrainOutcome` members to appear in that file's assertions, and the pre-existing "five behaviors" section only actually exercised three (empty/done/retried) plus the separate double-failure test — DEAD and FENCED had no real test anywhere in the module.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Comment-provenance guard violation in new comments**
- **Found during:** Task 2 (full-suite verification run)
- **Issue:** Several new comments (in `app/queue/drain.py` and two test files) cited ticket/decision-style provenance (`D-10`, `review finding #1`, `Task 1`), which this repo's `test_comment_provenance_guard.py` (a Phase 15/v3-era CI guard) rejects — the project convention requires comments to explain the reasoning directly rather than cite the ticket that produced it.
- **Fix:** Reworded the four flagged comments/docstring lines in `app/queue/drain.py` (the `DrainOutcome` docstring and the re-raise comment) and `tests/test_queue_drain.py`/`tests/test_queue_worker.py` (the double-failure test comment and the new survival test's docstring/section header) to state the constraint plainly without ticket citations.
- **Files modified:** `app/queue/drain.py`, `tests/test_queue_drain.py`, `tests/test_queue_worker.py`
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py -q` — 5 passed
- **Committed in:** `c529561` (Task 2 commit, since the guard only surfaced on the full-suite run after both tasks' code existed)

**2. [Rule 2 - Missing coverage] Added DrainOutcome.DEAD and DrainOutcome.FENCED behavior tests**
- **Found during:** Task 2 (acceptance criteria verification)
- **Issue:** The plan's Task 2 acceptance criteria require `DrainOutcome.DONE`, `.EMPTY`, `.RETRIED`, `.DEAD`, and `.FENCED` each present at least once as real assertions in `tests/test_queue_drain.py` — the module's pre-existing "five behaviors" section only actually asserted DONE/EMPTY/RETRIED (from the original 3 rewritten sites); DEAD and FENCED had zero test coverage anywhere in the file.
- **Fix:** Added `test_drain_once_dispatch_raises_at_max_attempts_returns_dead` (enqueues a job with `max_attempts=1` so the failure write dead-letters) and `test_drain_once_complete_job_fenced_out_returns_fenced` (stubs `repo.complete_job` to return `False`, simulating a lease stolen mid-run).
- **Files modified:** `tests/test_queue_drain.py`
- **Verification:** `uv run pytest tests/test_queue_drain.py -k drain_once -q` — 5 passed
- **Committed in:** `c529561` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 bug/lint-gate fix, 1 missing-coverage addition)
**Impact on plan:** Both fixes were necessary to satisfy the plan's own stated acceptance criteria and this repo's pre-existing CI gates. No scope creep — no production behavior changed beyond what Task 1 already specified.

## Issues Encountered
None beyond the two auto-fixed deviations above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `DrainOutcome` and the enriched `drain_once()` are ready for 17-02 (`count_open_jobs`) and 17-04 (the pump route), which will aggregate `DrainOutcome` counts per invocation and turn a propagated double-failure exception into a 503.
- No blockers. The final-attempt lease-strand residual (a job that dies on its last allowed attempt is not reclaimed by `claim_job`) remains explicitly out of scope for this plan and is carried to Phase 18/FAIL-02 per the plan's own scope note — `drain_once()` and `DrainOutcome` are unchanged with respect to that residual (still 5 values, no reap path added).

---
*Phase: 17-the-pump*
*Completed: 2026-07-15*

## Self-Check: PASSED

All 8 modified files found on disk; both task commits (`bd178cc`, `c529561`) found in git log. Full hermetic suite green: 718 passed, 68 skipped, 0 failures.
