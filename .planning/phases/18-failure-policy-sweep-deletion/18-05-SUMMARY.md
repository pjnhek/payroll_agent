---
phase: 18-failure-policy-sweep-deletion
plan: 05
subsystem: durable-queue
tags: [python, fastapi, pump, dead-letter, accounting]

requires:
  - phase: 18-04
    provides: shared drain final-attempt lease reaper and distinct REAPED_FINAL_LEASE outcome
provides:
  - truthful pump response accounting for final-attempt lease maintenance
  - bounded reap-only and mixed-outcome pump behavior
  - guarded live endpoint proof for durable reap settlement and repeat-call idempotence
affects: [18-10, 18-11, 21-queue-operations]

tech-stack:
  added: []
  patterns:
    - separate drained-work and claimed-execution counters preserve both request bounds and accounting truth

key-files:
  created: []
  modified:
    - app/routes/pump.py
    - tests/test_pump_route.py
    - tests/test_queue_durability.py

key-decisions:
  - "Use a separate drained counter for the request cap so final-lease reaps remain bounded without inflating claimed work."
  - "Represent final-lease maintenance as dead plus reaped_final_lease while preserving every legacy outcome counter exactly."

patterns-established:
  - "Pump identity: claimed equals done plus retried plus non-reaped dead plus fenced."
  - "Maintenance outcomes consume the bounded drain budget even when they are not claimed executions."

requirements-completed: [FAIL-02]

coverage:
  - id: D1
    description: "The authenticated bounded pump reports final-attempt lease reaps as dead maintenance outside claimed work while preserving all existing outcome counts."
    requirement: FAIL-02
    verification:
      - kind: unit
        ref: "tests/test_pump_route.py#test_reaped_final_leases_are_dead_but_never_claimed"
        status: pass
      - kind: unit
        ref: "tests/test_pump_route.py#test_bounded_max_jobs_cap_includes_reaped_maintenance"
        status: pass
    human_judgment: false
  - id: D2
    description: "A reap-only real Postgres pump request settles the exact final-attempt lease once, updates durable job and run state, and reports zero work on an immediate repeat."
    requirement: FAIL-02
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py#test_pump_reaps_expired_final_attempt_once"
        status: unknown
    human_judgment: true
    rationale: "The proof is collected and guarded correctly, but the dedicated local Postgres service timed out before the test body could execute in this run."

duration: 8min
completed: 2026-07-16
status: complete
---

# Phase 18 Plan 05: Truthful Pump Reap Accounting Summary

**The bounded pump now reports expired final-attempt lease settlement as dead maintenance without pretending a worker claimed it.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-16T02:55:49Z
- **Completed:** 2026-07-16T03:03:37Z
- **Tasks:** 2 TDD tasks
- **Files modified:** 3

## Accomplishments

- Added `reaped_final_lease` to every successful pump response and enforced D-14's revised identity: `claimed == done + retried + (dead - reaped_final_lease) + fenced`.
- Kept maintenance settlement inside the existing 20-outcome and wall-clock request bounds by separating drained outcomes from claimed executions.
- Added hermetic mixed, reap-only, zero-work, serialization, and bound coverage plus a guarded live endpoint proof that checks durable job/run state and immediate repeat-call idempotence.

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Add failing pump reap accounting tests** - `c16d5c2` (test)
2. **Task 1 GREEN: Report final lease reaps honestly** - `ecc2cb5` (feat)
3. **Task 2: Add reap-only live endpoint proof** - `e3a2b33` (test)

**Plan metadata:** (this commit)

## Files Created/Modified

- `app/routes/pump.py` - Separates bounded drained work from claimed execution and reports reaped final leases as a dead subcount.
- `tests/test_pump_route.py` - Pins the revised identity across zero, reap-only, mixed, legacy, and bounded sequences.
- `tests/test_queue_durability.py` - Seeds one exact expired final attempt, drives the real HTTP pump twice, and checks durable settlement plus idempotence.

## Decisions Made

- Used the existing serialized response dictionary as the pump response contract because the route has no separate `PumpResponse` model; this preserves the established FastAPI surface without introducing an unnecessary abstraction.
- Counted every non-empty drain outcome against the request's work cap, while incrementing `claimed` only for outcomes produced by a claimed job.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Preserved the request bound for reap-only queues**
- **Found during:** Task 1 (Count reaped final leases without inflating claimed work)
- **Issue:** Simply excluding reaps from `claimed` would also exclude them from the loop's existing `claimed < _MAX_JOBS_PER_PUMP` bound, allowing an unbounded number of maintenance settlements until the wall-clock cap.
- **Fix:** Added a separate `drained` counter used only for the request bound; `claimed` retains its operator-facing execution meaning.
- **Files modified:** `app/routes/pump.py`, `tests/test_pump_route.py`
- **Verification:** `test_bounded_max_jobs_cap_includes_reaped_maintenance` and all 13 pump-route tests pass.
- **Committed in:** `ecc2cb5`

---

**Total deviations:** 1 auto-fixed (1 correctness bug)
**Impact on plan:** The fix preserves the pre-existing bounded synchronous pump guarantee while implementing D-14; no new route, state, dependency, or observability surface was added.

## Issues Encountered

- The exact live queueproof collected successfully but skipped under the normal two-factor guard when `DATABASE_URL` and `ALLOW_DB_RESET=1` were absent.
- A follow-up against the previously documented dedicated `payroll_pump_proof` database was allowed through the sandbox but the local Postgres service timed out during setup, before any test body ran. No live pass is claimed here; the integration coverage remains `unknown` for downstream verification/CI.
- An extra broad mypy invocation found 27 pre-existing errors in `tests/conftest.py` and earlier lines of `tests/test_queue_durability.py`; Plan 18-05's changed pump files pass their scoped mypy check, and no unrelated typing debt was modified.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Pump accounting now exposes the final-attempt reaper honestly for downstream operational consumers without pulling Phase 21 observability forward.
- No code blocker or unmitigated high-severity threat remains. Live Postgres evidence should be refreshed when the dedicated proof database or CI queueproof environment is available.

## Self-Check: PASSED

- All three modified files exist.
- Commits `c16d5c2`, `ecc2cb5`, and `e3a2b33` are present in history.
- `tests/test_pump_route.py`: 13 passed.
- Pump-route Ruff and scoped mypy: passed.
- Live queueproof: collected, but local execution remains unknown because Postgres was unavailable.

---
*Phase: 18-failure-policy-sweep-deletion*
*Completed: 2026-07-16*
