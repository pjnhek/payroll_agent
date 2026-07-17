---
phase: 19-webhook-cutover-durable-ingest
plan: 11
subsystem: durable-queue-consumer-tests
tags: [python, pytest, durable-queue, webhook-ingest, postgres, dedup]

requires:
  - phase: 19-webhook-cutover-durable-ingest
    provides: durable receipt, delayed ingest, pipeline, reply, and operator job seams
  - phase: 18-failure-policy-sweep-deletion
    provides: explicit PipelineResult settlement and retry policy
provides:
  - background-wrapper-free consumer tests for durable receipt and job execution
  - request-boundary fail-if-inline guards for provider fetch and payroll execution
  - delayed RFC Message-ID dedup race proof through real INGEST handlers
affects: [19-12-background-task-cutover, QUEUE-04]

tech-stack:
  added: []
  patterns:
    - split receipt acceptance from delayed queue execution in route tests
    - settle explicit terminal PipelineResult values when a test needs persisted error state
    - forbid inline value and handler seams at request boundaries

key-files:
  created:
    - .planning/phases/19-webhook-cutover-durable-ingest/19-11-SUMMARY.md
  modified:
    - tests/test_retrigger_threading.py
    - tests/test_queue_drain.py
    - tests/test_send_idempotency.py
    - tests/test_ingest.py
    - tests/test_concurrency_proof.py
    - tests/test_gateway.py
    - tests/test_stuck_run_recovery.py
    - tests/test_hitl.py
    - tests/test_webhook_dedup_race.py
    - tests/test_job_kind_drift.py
    - tests/test_reply_redelivery.py
    - tests/test_threading.py

key-decisions:
  - "Test transport receipt and business execution as two explicit phases so request tests cannot accidentally authorize inline provider or payroll work."
  - "Use explicit run_pipeline_now values and repository settlement in policy tests that must preserve a terminal ERROR state; retired background wrappers are not recreated as test helpers."
  - "Keep the RFC Message-ID race behind the existing real-Postgres guard because its proof depends on commit serialization, not an in-memory approximation."

patterns-established:
  - "Receipt-first route test: assert one INGEST job and no business work, then drain INGEST and assert the exact identifier-only downstream job."
  - "No-inline guard: patch both direct value functions and queue handlers to fail at the HTTP boundary, restoring only the handler under test before drain."

requirements-completed: [QUEUE-04]

coverage:
  - id: D1
    description: "Former background-wrapper consumers exercise explicit PipelineResult values or durable queue jobs without compatibility bridges."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "nine planned consumer modules: 128 passed, 10 guarded skips"
        status: pass
      - kind: static
        ref: "retired wrapper and BackgroundTasks scan across all twelve migrated modules"
        status: pass
    human_judgment: false
  - id: D2
    description: "Webhook, reply, runs-list, and demo request boundaries acknowledge durable receipt work without fetching providers or executing payroll inline."
    requirement: QUEUE-04
    verification:
      - kind: integration
        ref: "tests/test_ingest.py, tests/test_gateway.py, tests/test_reply_redelivery.py, tests/test_threading.py"
        status: pass
      - kind: full_suite
        ref: "1003 passed, 75 skipped"
        status: pass
    human_judgment: false
  - id: D3
    description: "Concurrent distinct transport receipts sharing one RFC Message-ID commit one inbound email, one run, and one identifier-only RUN_PIPELINE job after delayed ingest."
    requirement: QUEUE-04
    verification:
      - kind: integration
        ref: "tests/test_webhook_dedup_race.py"
        status: guarded-skip
    human_judgment: true
    rationale: "The real-Postgres proof is implemented but DATABASE_URL was not configured in this checkout, so the focused gate retained its existing guarded skip."

duration: 21min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 11: Durable Consumer Test Migration Summary

**Every stale synchronous consumer test now crosses the same durable receipt, identifier-only job, explicit-value, and terminal-settlement seams used by the Phase 19 implementation.**

## Performance

- **Duration:** 21 min
- **Started:** 2026-07-17T03:17:09Z
- **Completed:** 2026-07-17T03:37:57Z
- **Tasks:** 3
- **Files modified:** 12 test files

## Accomplishments

- Migrated execution-policy, retrigger, send-idempotency, route, recovery, HITL, and concurrency consumers away from retired background wrappers and companion-result bridges.
- Proved receipt-first behavior with fail-if-inline guards, then drained delayed INGEST work to assert exact `RUN_PIPELINE` or `RESUME_REPLY` jobs and preserved sender/run ownership checks.
- Rebuilt the RFC dedup race around concurrent durable receipts followed by concurrent real INGEST handlers, retaining database commit serialization as the proof boundary.
- Closed three additional stale consumer modules discovered by the full-suite gate without changing production code.

## Task Commits

Each task was committed atomically:

1. **Task 1: Migrate execution-policy consumers** - `da676d6` (test)
2. **Task 2: Migrate route consumers to durable jobs** - `1ede683` (test)
3. **Task 3: Migrate the RFC dedup race to delayed ingest** - `18cde7c` (test)
4. **Task 1 inventory cleanup: Remove the final retired consumer reference** - `d84e905` (test)
5. **Full-suite blocking fix: Close omitted durable-ingest consumer gaps** - `9b9777c` (test)

## Files Created/Modified

- `tests/test_retrigger_threading.py` - Uses explicit pipeline values and terminal settlement while retaining retrigger threading assertions.
- `tests/test_queue_drain.py` - Removes retired wrapper bridges and pins the current durable drain call graph.
- `tests/test_send_idempotency.py` - Exercises send idempotency through explicit results and persisted terminal settlement.
- `tests/test_ingest.py` - Separates durable receipt acceptance from delayed ingest and exact downstream jobs.
- `tests/test_concurrency_proof.py` - Preserves real thread barriers while forbidding inline pipeline/reply execution.
- `tests/test_gateway.py` - Tests reply receipt, delayed classification, sender ownership, and exact resume-job creation.
- `tests/test_stuck_run_recovery.py` - Keeps runs-list recovery read-only against the durable queue seams.
- `tests/test_hitl.py` - Removes the obsolete background monkeypatch while retaining actual operator-job generation and drain.
- `tests/test_webhook_dedup_race.py` - Proves transport-event multiplicity and RFC-level business dedup after delayed concurrent ingest.
- `tests/test_job_kind_drift.py` - Allows INGEST production only at the webhook receipt boundary and rejects other route producers.
- `tests/test_reply_redelivery.py` - Replays stored inbound content through receipt, INGEST, and RESUME_REPLY jobs.
- `tests/test_threading.py` - Drives clarification threading through receipt and queue drains and checks header ownership in delayed ingest.

## Decisions Made

- Error-policy tests call repository terminal settlement explicitly after receiving a `PipelineResult`; this preserves the test's state assertion without restoring a retired compatibility wrapper.
- A request response proves only durable acceptance. Business classification is asserted from delayed job state after an explicit drain.
- The race test uses two distinct transport event IDs with the same RFC Message-ID because transport idempotency and payroll-message idempotency are separate required layers.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Migrated three stale synchronous consumers omitted from the plan inventory**
- **Found during:** Full-suite verification after Tasks 1-3
- **Issue:** `test_job_kind_drift.py`, `test_reply_redelivery.py`, and `test_threading.py` still encoded the pre-cutover synchronous route contract. Their 15 failures blocked the phase gate and would also block Plan 19-12 deletion even though the planned nine modules were green.
- **Fix:** Migrated all three to receipt-first durable ingest and delayed job assertions, updated the route-source guard to the current delayed-ingest owner, and retained fail-if-inline protection.
- **Files modified:** `tests/test_job_kind_drift.py`, `tests/test_reply_redelivery.py`, `tests/test_threading.py`
- **Verification:** 40 focused tests passed; the complete suite passed with 1,003 tests and 75 guarded skips.
- **Committed in:** `9b9777c`

---

**Total deviations:** 1 auto-fixed (1 Rule 3 blocking issue)
**Impact on plan:** Test-only closure of the actual stale-consumer inventory; no production behavior, schema, dependency, or public interface changed.

## Issues Encountered

- The real-Postgres RFC dedup race remained guarded because this checkout has no `DATABASE_URL`; the test itself and its static/lint gates pass collection, and the full hermetic suite is green.
- The existing Starlette/httpx deprecation warning remains unchanged.

## User Setup Required

None for the hermetic suite. A configured test Postgres database is required only to execute the guarded RFC dedup race proof.

## Verification

- Planned nine-module focused gate: 128 passed, 10 skipped.
- Omitted-consumer blocking fix gate: 40 passed.
- Full hermetic suite: 1,003 passed, 75 skipped, 1 unchanged deprecation warning.
- Ruff: passed for all 12 modified test modules.
- Retired-name scan: no `run_pipeline_bg`, `resume_pipeline_bg`, `operator_resume_bg`, `_consume_background_result`, `finish_reply_resume`, or `BackgroundTasks` references in the migrated modules.
- `git diff --check`: passed.

## Next Phase Readiness

- Plan 19-12 can delete the retired background entrypoints and add its production-tree guard without stale test consumers masking compatibility use.
- Plan 19-10 still owns restart/retention and activation-fence proof; this plan made no claim about that out-of-order dependency.
- The only unexecuted proof in this plan is the existing real-Postgres guarded race; its test contract is ready for CI or a configured local database.

## Known Stubs

None introduced.

## Self-Check: PASSED

- All 12 modified test files and this summary exist.
- Task commits `da676d6`, `1ede683`, `18cde7c`, `d84e905`, and `9b9777c` are present in history.
- Focused, full-suite, Ruff, retired-name, and diff-check gates are green; the real-Postgres race is explicitly reported as guarded.

---
*Phase: 19-webhook-cutover-durable-ingest*
*Completed: 2026-07-16*
