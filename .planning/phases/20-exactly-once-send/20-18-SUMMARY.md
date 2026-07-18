---
phase: 20-exactly-once-send
plan: 18
subsystem: database/testing
tags: [postgres, queue, exactly-once, idempotency, reply-epoch]

# Dependency graph
requires:
  - phase: 20-exactly-once-send
    provides: immutable outbound snapshots, current-epoch sent proof, and purpose-aware delivery settlement
provides:
  - stale-epoch SEND_OUTBOUND jobs stop before provider work
  - locked settlement and final-lease reaping fence stale message epochs without mutating the current slot
  - in-memory repository parity for stale-epoch no-write handling
affects: [outbound delivery, queue settlement, plan-20-19, phase-21 durability proofs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - handler authorization compares immutable snapshot epoch with the loaded run reply_epoch before provider work
    - settlement and final reaping lock both message and run epochs before delivery evidence or business-state writes

key-files:
  created: []
  modified:
    - app/queue/handlers/send_outbound.py
    - app/db/repo/job_settlement.py
    - app/db/repo/runs.py
    - tests/conftest.py
    - tests/test_queue_durability.py
    - tests/test_phase20_fake_parity.py

key-decisions:
  - "A stale epoch is a bounded no-op before provider work and a fenced no-write result under locked settlement or reaping."
  - "Stale leases remain unretired in this plan; Plan 20-19 owns named outcomes and exact-token retirement."
  - "load_run exposes reply_epoch through RUN_COLS so the planned handler fence reads the authoritative run generation."

patterns-established:
  - "External send authorization requires a persisted snapshot and the run's current reply epoch to agree."
  - "Fake queue settlement mirrors production epoch fencing so route tests cannot accept stale work production rejects."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "A stale outbound handler stops before the provider and preserves the current epoch reservation."
    requirement: SEND-02
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py::test_send_handler_noops_before_gateway_for_stale_epoch"
        status: unknown
    human_judgment: true
    rationale: "The provider-spy regression requires the guarded live-Postgres fixture; DATABASE_URL and ALLOW_DB_RESET=1 were unavailable locally."
  - id: D2
    description: "Locked delivery settlement and final-lease reaping fence stale epochs before attempt, send-state, payroll-status, or review writes."
    requirement: SEND-01
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py::test_delivery_settlement_rejects_stale_epoch_without_current_reservation_mutation"
        status: unknown
      - kind: integration
        ref: "tests/test_queue_durability.py::test_final_send_lease_rejects_stale_epoch_without_current_review_mutation"
        status: unknown
    human_judgment: true
    rationale: "Both no-write regressions require the guarded live-Postgres fixture; DATABASE_URL and ALLOW_DB_RESET=1 were unavailable locally."
  - id: D3
    description: "The in-memory repository preserves the current reserved Message-ID when stale settlement or final reaping is rejected."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: "tests/test_phase20_fake_parity.py::test_fake_stale_epoch_send_settlement_rejects_without_mutation"
        status: pass
      - kind: unit
        ref: "tests/test_phase20_fake_parity.py::test_fake_stale_epoch_final_lease_rejects_without_mutation"
        status: pass
    human_judgment: false

# Metrics
duration: ~8min implementation
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 18: Stale-Epoch Send Fence Summary

**Outbound jobs now verify their frozen message epoch against the run's current reply epoch before provider work, settlement, or final-lease review can affect the active delivery slot.**

## Performance

- **Duration:** approximately 8 minutes of committed implementation; closeout verification completed 2026-07-18.
- **Started:** 2026-07-17T17:45:04-07:00
- **Completed:** 2026-07-17T17:52:46-07:00
- **Tasks:** 2/2
- **Files modified:** 6 implementation/test files, plus this summary and tracking artifacts

## Accomplishments

- Added a pre-provider epoch comparison in the send handler, with a provider-spy regression proving old work is a bounded no-op after a retrigger advances the run epoch.
- Locked message and run epochs in normal settlement and final-lease reaping, rejecting stale work without appending attempts, changing email state, mutating payroll status, or creating current-run review evidence.
- Matched the fence in `InMemoryRepo` and added fake-parity tests proving the current reserved Message-ID remains untouched.

## Task Commits

Each task followed the required RED/GREEN sequence:

1. **Task 1 RED: add stale epoch delivery regressions** — `343aeef` (test)
2. **Task 1 GREEN: fence stale outbound epochs** — `8eeb561` (feat)
3. **Task 2 RED: add fake stale epoch regressions** — `108e7df` (test)
4. **Task 2 GREEN: mirror stale epoch fencing in fake repo** — `7eeee1e` (feat)

The summary and tracking closeout are committed separately.

## Files Created/Modified

- `app/queue/handlers/send_outbound.py` — compares frozen snapshot and run reply epochs before calling the gateway.
- `app/db/repo/job_settlement.py` — locks and fences message/run epochs in settlement and final-lease reaping.
- `app/db/repo/runs.py` — exposes `reply_epoch` to the handler's existing run load.
- `tests/conftest.py` — mirrors stale-epoch no-write behavior in `InMemoryRepo`.
- `tests/test_queue_durability.py` — provider-free and no-mutation live repository regressions.
- `tests/test_phase20_fake_parity.py` — stale fake settlement, reaping, and handler parity regressions.

## Decisions Made

- Used the run's persisted `reply_epoch` as the single authoritative current-generation fact at every send boundary.
- Left a stale exact lease untouched after the fence; Plan 20-19 is responsible for outcome mapping and durable token retirement.

## Deviations from Plan

None — plan executed as written. The small `RUN_COLS` addition in `app/db/repo/runs.py` is required to expose the plan-mandated loaded-run `reply_epoch` fence.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

Plan 20-19 can retire invalid-context leases using the fenced no-write boundary established here.

## Verification

- `uv run pytest -q tests/test_queue_durability.py tests/test_phase20_fake_parity.py tests/test_send_idempotency.py` — **68 passed, 51 skipped**.
- `uv run ruff check app/queue/handlers/send_outbound.py app/db/repo/job_settlement.py tests/conftest.py tests/test_phase20_fake_parity.py tests/test_queue_durability.py` — **passed**.

The 51 skips are existing environment-guarded test cases. The three named live-Postgres regressions were confirmed skipped locally because `DATABASE_URL` and `ALLOW_DB_RESET=1` were not set; their coverage is recorded as unavailable rather than passing evidence.

## TDD Gate Compliance

- Task 1 RED/GREEN commits: `343aeef` → `8eeb561`.
- Task 2 RED/GREEN commits: `108e7df` → `7eeee1e`.

## Self-Check: PASSED

- The four implementation commits collectively cover both planned tasks and their listed artifacts.
- Focused pytest and Ruff verification passed.
- No production or test defect was found during recovery verification.

---
*Plan: 20-18*
*Completed: 2026-07-17*
