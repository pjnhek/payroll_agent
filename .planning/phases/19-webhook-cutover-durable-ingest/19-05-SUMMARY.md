---
phase: 19-webhook-cutover-durable-ingest
plan: 05
subsystem: durable-queue
tags: [python, postgres, ingest, settlement, lease-fencing, fake-parity]

requires:
  - phase: 19-webhook-cutover-durable-ingest
    provides: exact identifier-only ingest job kind, context, claim, and dispatch contract
  - phase: 18-failure-policy-sweep-deletion
    provides: atomic run-associated settlement and starvation-free final-attempt reaping
provides:
  - transport-only success, retry, exhaustion, and terminal settlement for null-run ingest jobs
  - expired final-attempt ingest reaping without payroll status mutation
  - ingest-aware in-memory queue parity and non-vacuous facade pairing proofs
affects: [19-06-webhook-receipt-cutover, 21-durability-proofs-ops-view]

tech-stack:
  added: []
  patterns:
    - branch on the locked transport kind before requiring a payroll run
    - preserve one lease-token fence while keeping ingest failure policy transport-only

key-files:
  created: []
  modified:
    - app/db/repo/job_settlement.py
    - tests/conftest.py
    - tests/test_queue_drain.py
    - tests/test_queue_durability.py
    - tests/test_fake_repo_pairing.py

key-decisions:
  - "Null-run ingest results settle only the leased jobs row; no ingest outcome reads or writes payroll_runs."
  - "Retryable ingest failures retain the existing attempt cap, bounded diagnostic code, backoff, and lease-token fence; exhausted work becomes dead and terminal work becomes done."
  - "The final-attempt reaper distinguishes ingest by the locked database kind and clears its expired lease without requiring a run row."

patterns-established:
  - "Transport settlement validates the stored kind under the same row lock and lease token used for the final write."
  - "The in-memory repository mirrors ingest enqueue, claim, result settlement, infrastructure retry, and final-lease cleanup exactly enough for facade-pairing guards to fail closed."

requirements-completed: [QUEUE-04]

coverage:
  - id: D1
    description: "Null-run ingest success, retry, exhaustion, terminal, and infrastructure outcomes settle only transport state under the existing lease fence."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py#test_null_run_ingest_settlement_is_transport_only_in_fake_repo"
        status: pass
      - kind: unit
        ref: "tests/test_queue_drain.py#test_null_run_ingest_real_coordinator_never_calls_payroll_writers"
        status: pass
      - kind: unit
        ref: "tests/test_queue_drain.py#test_null_run_ingest_infrastructure_failure_uses_bounded_transport_retry"
        status: pass
    human_judgment: false
  - id: D2
    description: "An expired final-attempt ingest lease becomes dead, clears both lease fields, retains prior attempt history, and never reaches a payroll writer."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py#test_null_run_ingest_expired_final_attempt_is_reaped_without_payroll_write"
        status: pass
      - kind: unit
        ref: "tests/test_queue_drain.py#test_null_run_ingest_stale_token_is_fenced_before_any_transport_or_payroll_write"
        status: pass
    human_judgment: false
  - id: D3
    description: "Fake enqueue, claim, settlement, and reap semantics include ingest, and a synthetic facade escape proves the pairing inventory is non-vacuous."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_fake_repo_pairing.py#test_durable_recovery_facade_and_fake_surfaces_remain_paired"
        status: pass
      - kind: unit
        ref: "tests/test_fake_repo_pairing.py#test_durable_recovery_pairing_guard_detects_one_unpaired_facade_method"
        status: pass
    human_judgment: false
  - id: D4
    description: "Guarded Postgres cases preserve payroll rows across null-run settlement and final-attempt reaping."
    requirement: QUEUE-04
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py#test_null_run_ingest_settlement_does_not_write_payroll_status"
        status: unknown
      - kind: integration
        ref: "tests/test_queue_durability.py#test_null_run_ingest_final_attempt_reap_clears_lease_without_payroll_write"
        status: unknown
    human_judgment: true
    rationale: "The tests collected, but DATABASE_URL and ALLOW_DB_RESET=1 were unavailable, so no live Postgres pass is claimed."

duration: 10min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 05: Null-Run Ingest Settlement Summary

**Identifier-only ingest jobs now settle every result and expired final-attempt lease under the existing transport fence without reading or writing payroll business state.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-07-17T01:00:34Z
- **Completed:** 2026-07-17T01:10:24Z
- **Tasks:** 2 TDD tasks
- **Files modified:** 5

## Accomplishments

- Added a locked-kind ingest branch before the coordinator's run requirement, covering OK, bounded retry/backoff, retry exhaustion, terminal, and escaped infrastructure outcomes without a payroll mutation.
- Extended final-attempt reaping so an expired null-run ingest lease becomes dead and clears its lease instead of remaining fenced forever.
- Brought the in-memory repository's event identifier, claim model, settlement matrix, and reaper behavior into exact ingest parity, with a synthetic facade escape proving the pairing guard is live.

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Pin null-run settlement, reaper, and fake-pairing behavior** - `58bba59` (test)
2. **Task 2 GREEN: Settle, reap, and fake-pair every null-run ingest outcome** - `1c022c0` (feat)

## Files Created/Modified

- `app/db/repo/job_settlement.py` - Locks and validates job kind, settles ingest results without run state, and reaps expired ingest leases.
- `tests/conftest.py` - Mirrors ingest enqueue, event-aware claim, settlement, infrastructure retry, and final-lease cleanup in memory.
- `tests/test_queue_drain.py` - Provides fail-if-called payroll writers, transport outcome matrices, stale-token distinction, and reaper proofs.
- `tests/test_queue_durability.py` - Adds reset-authority-guarded Postgres payroll snapshot proofs for settlement and reaping.
- `tests/test_fake_repo_pairing.py` - Makes the durable seam inventory explicitly nonempty and proves it detects a synthetic unpaired facade method.

## Decisions Made

- Use the kind loaded under `FOR UPDATE` as settlement authority and require it to match the claimed `Job.kind` before any result write.
- Keep successful ingest history intact, persist only bounded diagnostic codes for non-OK outcomes, and reuse the existing attempt cap and backoff ceiling.
- Preserve the complete run-associated settlement and status matrix; only the explicit ingest branch bypasses payroll state.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The initial RED draft referenced an ingest-specific pipeline stage that is intentionally absent from the bounded result vocabulary; the test harness was corrected to use the existing `LOAD` stage before the RED commit.
- Guarded Postgres cases collected but skipped because the environment did not provide both `DATABASE_URL` and `ALLOW_DB_RESET=1`. This is unavailable evidence, not a pass.
- The full suite emitted the existing Starlette/httpx deprecation warning.

## User Setup Required

None - no external service configuration required.

## Verification

- RED focused gate: 9 expected failures, 32 related passes, and 23 guarded skips before implementation.
- Final settlement/reaper/fake modules: 75 passed, 41 guarded skips.
- Adjacent job-kind, SQL, delayed-ingest, worker, and pump slice: 119 passed.
- Full offline suite: 969 passed, 75 guarded skips.
- Ruff: passed for all five modified production/test files.
- Mypy: passed for `app/db/repo/job_settlement.py`.
- `git diff --check`: passed.

## Next Phase Readiness

- Plan 19-06 can expose the webhook ingest producer because every null-run transport outcome now settles or reaps safely.
- Live Postgres evidence remains pending on the two-factor reset-authorized environment; no implementation blocker remains.
- No unmitigated high-severity threat, new network surface, schema change, or dependency was introduced.

## Self-Check: PASSED

- All five modified implementation/test files exist.
- RED/GREEN commits `58bba59` and `1c022c0` are present in history.
- Task acceptance criteria, plan verification, adjacent queue regression, and full-suite gates are green.
- Guarded integration skips are reported as unavailable evidence.

---
*Phase: 19-webhook-cutover-durable-ingest*
*Completed: 2026-07-16*
