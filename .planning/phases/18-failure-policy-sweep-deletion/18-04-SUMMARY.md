---
phase: 18-failure-policy-sweep-deletion
plan: 04
subsystem: durable-queue
tags: [python, postgres, pipeline-result, atomic-settlement, lease-reaper]

requires:
  - phase: 18-03
    provides: fenced atomic job/run settlement and final-attempt reaper repository seams
  - phase: 18-09
    provides: result-forwarding initial, reply, and operator queue handlers
provides:
  - result-aware shared drain settlement for explicit and compatibility pipeline results
  - bounded atomic infrastructure retry/dead settlement with held-token retention on write failure
  - exact final-attempt lease reaping before shared drains report EMPTY
affects: [18-05, 18-10, 18-11, 19-webhook-cutover-durable-ingest]

tech-stack:
  added: []
  patterns:
    - one compatibility normalization seam feeds one fenced cross-aggregate coordinator
    - normal claim wins before one bounded final-attempt reap per drain call

key-files:
  created: []
  modified:
    - app/queue/handlers/pipeline.py
    - app/queue/drain.py
    - app/db/repo/job_settlement.py
    - tests/conftest.py
    - tests/test_queue_drain.py
    - tests/test_queue_durability.py

key-decisions:
  - "Queue consumers normalize legacy None only through normalize_pipeline_result; every normalized result uses the same fenced settlement coordinator."
  - "A final-attempt reap preserves jobs.last_error as prior-attempt history while the run receives the distinct bounded FinalAttemptLeaseExpired diagnostic."

patterns-established:
  - "Settlement-write exceptions retain the held lease token and re-raise; only a returned bounded settlement outcome releases it."
  - "DrainOutcome.EMPTY remains the sole falsy outcome; REAPED_FINAL_LEASE is distinct and truthy."

requirements-completed: [FAIL-01, FAIL-02]

coverage:
  - id: D1
    description: "The shared drain maps legacy None and all explicit pipeline outcomes through one fenced atomic settlement matrix, including terminal transport DONE plus business ERROR."
    requirement: FAIL-01
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py#test_drain_once_maps_pipeline_results_through_atomic_settlement"
        status: pass
      - kind: unit
        ref: "tests/test_queue_drain.py#test_pipeline_handler_forwards_result_and_cas_loser_returns_ok"
        status: pass
    human_judgment: false
  - id: D2
    description: "Escaped infrastructure failures settle retry/dead with bounded diagnostics, while a settlement-write failure re-raises and retains the exact held token."
    requirement: FAIL-02
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py#test_drain_once_infrastructure_exception_uses_atomic_settlement"
        status: pass
      - kind: unit
        ref: "tests/test_queue_drain.py#test_infrastructure_settlement_write_failure_re_raises_and_keeps_token"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every shared drain attempts one exact expired final-attempt reap only after an empty normal claim and returns a distinct truthy outcome."
    requirement: FAIL-02
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py#final_attempt_reap and normal_claim_precedes tests"
        status: pass
      - kind: integration
        ref: "tests/test_queue_durability.py#test_final_attempt_reap_exact_predicate_fence_and_rollback"
        status: unknown
    human_judgment: true
    rationale: "The hermetic ordering and exact-predicate mirrors pass, but the live Postgres proof was skipped because DATABASE_URL and ALLOW_DB_RESET were unavailable."

duration: 11min
completed: 2026-07-16
status: complete
---

# Phase 18 Plan 04: Result-Aware Drain and Final-Lease Reaper Summary

**The shared drain now atomically settles explicit pipeline outcomes and bounded infrastructure failures, then closes one exact expired final-attempt lease before honestly reporting the queue empty.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-07-16T02:01:31Z
- **Completed:** 2026-07-16T02:12:54Z
- **Tasks:** 2 TDD tasks
- **Files modified:** 6

## Accomplishments

- Forwarded the initial pipeline handler's `PipelineResult | None`, made a lost run-status CAS an explicit OK no-op, and centralized compatibility normalization plus atomic settlement in `drain_once()`.
- Replaced raw `fail_job` exception persistence with bounded cross-aggregate infrastructure settlement; transient failures become PENDING/RECEIVED, exhaustion becomes DEAD/ERROR, and an unpersisted settlement re-raises while retaining the lease token.
- Added `DrainOutcome.REAPED_FINAL_LEASE` and a claim-first, one-reap-per-call path that closes the exact expired leased/final-attempt strand without misattributing an earlier diagnostic.

## Task Commits

1. **Task 1 RED: Result-aware drain and infrastructure settlement proofs** - `f7d4333` (test)
2. **Task 1 GREEN: Atomic explicit-result drain settlement** - `6f459f0` (feat)
3. **Task 2 RED: Claim-before-reap and exact-predicate proofs** - `429c9c4` (test)
4. **Task 2 GREEN: Shared final-attempt lease reaper** - `e88dd46` (feat)

## Files Created/Modified

- `app/queue/handlers/pipeline.py` - Forwards producer results and returns explicit OK on a lost CAS.
- `app/queue/drain.py` - Normalizes results, invokes atomic coordinators, retains failed-settlement tokens, and reaps before EMPTY.
- `app/db/repo/job_settlement.py` - Preserves prior `last_error` when assigning the distinct final-lease run diagnostic.
- `tests/conftest.py` - Keeps the strict in-memory reaper mirror aligned with history preservation.
- `tests/test_queue_drain.py` - Hermetic result, infrastructure, fencing, ordering, truthiness, and static-boundary proofs.
- `tests/test_queue_durability.py` - Guarded live exact-predicate, CAS-fence, rollback, and history proof.

## Decisions Made

- Treat returned settlement outcomes as the only evidence that a lease is settled; exceptions from either coordinator leave the token held for graceful release.
- Keep an expired worker's earlier `jobs.last_error` as attempt history and write the final cause only to the run as `FinalAttemptLeaseExpired`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Preserved the earlier attempt diagnostic during final-lease reaping**
- **Found during:** Task 2 exact-reason proof
- **Issue:** The pre-existing reaper coordinator replaced `jobs.last_error` with `unknown:unclassified`, discarding the earlier attempt history required by the locked final-reason contract.
- **Fix:** The reaper now changes only transport state/token/lease fields; the bounded run diagnostic remains `FinalAttemptLeaseExpired` and never copies the earlier error.
- **Files modified:** `app/db/repo/job_settlement.py`, `tests/conftest.py`, `tests/test_queue_drain.py`, `tests/test_queue_durability.py`
- **Verification:** 41 queue-drain tests passed; Ruff and mypy passed; guarded live proof collected and skipped only at the database environment gate.
- **Committed in:** `e88dd46`

---

**Total deviations:** 1 auto-fixed (1 correctness bug)
**Impact on plan:** The fix directly enforces the locked history and non-misattribution requirement; no feature scope or trust boundary was added.

## Issues Encountered

- The live Postgres queueproof suite collected all 20 tests, including the new reaper proof, but skipped because the environment did not provide both `DATABASE_URL` and `ALLOW_DB_RESET=1`.
- A broad offline-suite invocation was interrupted by the execution harness after partial progress; the plan's complete hermetic module, worker/pump compatibility suite, Ruff, and mypy checks all completed green.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Consumer settlement is complete before producer cutover, so Plan 18-10 can remove legacy producer persistence without creating a result-loss window.
- Pump accounting can now distinguish final-lease reaps without counting them as claimed work.
- No unmitigated high-severity threat or code blocker remains. Live Postgres evidence remains pending only on the guarded test environment.

## Self-Check: PASSED

- All six modified implementation/test files exist.
- All four RED/GREEN commits are present in git history.
- `tests/test_queue_drain.py`: 41 passed.
- Worker/pump compatibility: 22 passed.
- Ruff and mypy: passed.
- Live queueproof collection: 20 collected, 20 skipped by the two-factor database guard.

---
*Phase: 18-failure-policy-sweep-deletion*
*Completed: 2026-07-16*
