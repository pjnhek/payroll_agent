---
phase: 20-exactly-once-send
plan: "05"
subsystem: queue
tags: [durable-queue, resend, immutable-snapshot, lease-fencing]

requires:
  - phase: 20-exactly-once-send
    provides: "snapshot-only gateway results and fenced outbound-delivery settlement"
provides:
  - "A late-bound identifier-only SEND_OUTBOUND consumer"
  - "Delivery-specific fenced settlement from the shared drain"
  - "Fake-pair and dispatch equality coverage for frozen send jobs"
affects: [20-10, outbound-delivery, durable-queue]

tech-stack:
  added: []
  patterns: [snapshot-only handler, purpose-aware lease settlement, late-bound dispatch]

key-files:
  created: [app/queue/handlers/send_outbound.py]
  modified:
    - app/queue/dispatch.py
    - app/queue/drain.py
    - tests/conftest.py
    - tests/test_queue_drain.py
    - tests/test_job_kind_drift.py

key-decisions:
  - "The shared drain selects delivery settlement for SEND_OUTBOUND jobs, so generic pipeline settlement cannot rewrite approved delivery state."
  - "The handler checks immutable ownership, expected business state, and the stored reservation cutoff before calling the snapshot-only gateway."

patterns-established:
  - "Every JobKind has an importable late-bound module/name handler entry."
  - "The in-memory fake mirrors delivery settlement and is pinned through the facade-pairing inventory."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "A frozen outbound job validates durable ownership and invokes only the stored snapshot gateway payload."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: tests/test_queue_drain.py#test_send_handler_uses_only_the_frozen_snapshot_before_provider_work
        status: pass
    human_judgment: false
  - id: D2
    description: "The shared drain settles SEND_OUTBOUND through the exact claimed lease rather than generic pipeline settlement."
    requirement: SEND-02
    verification:
      - kind: unit
        ref: tests/test_queue_drain.py#test_send_drain_uses_delivery_settlement_with_the_claimed_lease
        status: pass
    human_judgment: false
  - id: D3
    description: "Dispatch equality, dynamic handler lookup, and the fake facade all cover SEND_OUTBOUND."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: tests/test_job_kind_drift.py#TestDispatchTableMatchesJobKind
        status: pass
      - kind: unit
        ref: tests/test_fake_repo_pairing.py#test_durable_recovery_facade_and_fake_surfaces_remain_paired
        status: pass
    human_judgment: false

duration: 6min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 05: Snapshot-Only Send Consumer Summary

**Frozen outbound jobs now validate durable ownership before sending and settle through the delivery-specific exact lease fence.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-17T19:07:00Z
- **Completed:** 2026-07-17T19:13:40Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- Added and registered the late-bound `SEND_OUTBOUND` handler, which reads one immutable snapshot and never composes or regenerates delivery content.
- Routed outbound job results through `settle_outbound_delivery_job`, preserving the exact claimed lease and avoiding generic pipeline-state settlement.
- Restored exact JobKind-to-dispatch equality and paired the new settlement seam with the in-memory repository fake.

## Task Commits

1. **Task 1: Add and register a snapshot-only SEND_OUTBOUND handler** - `4e0e82f`
2. **Task 2: Complete fake parity and dispatch equality for the live handler** - `bac627c`

## Files Created/Modified

- `app/queue/handlers/send_outbound.py` - Validates frozen send context and delegates only to the snapshot gateway.
- `app/queue/dispatch.py` - Registers the handler as a late-bound module/name pair.
- `app/queue/drain.py` - Uses delivery-specific fenced settlement for outbound jobs.
- `tests/conftest.py` - Mirrors delivery settlement in the in-memory repository.
- `tests/test_queue_drain.py` - Proves snapshot-only provider input, no-op ownership rejection, lease settlement, and fake-pair execution.
- `tests/test_job_kind_drift.py` - Enforces full dispatch equality and send-handler dynamic lookup.

## Decisions Made

- Kept provider work in the handler and all delivery state transitions in the existing repository coordinator.
- Treated missing, cross-run, superseded, or non-authorized context as a bounded no-op before provider work.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Unexpected send-handler exceptions reached generic pipeline settlement**

- **Found during:** Final plan verification
- **Issue:** The drain's exception branch sent every handler failure through generic pipeline settlement, which could apply an invalid business-state policy to a frozen outbound job.
- **Fix:** Routed unexpected `SEND_OUTBOUND` handler failures to the delivery-specific fenced coordinator with a bounded delivery result.
- **Files modified:** `app/queue/drain.py`, `tests/test_queue_drain.py`
- **Verification:** Focused queue, dispatch, gateway, type, lint, and diff checks passed.
- **Committed in:** `987e0d9`

**Total deviations:** 1 auto-fixed (Rule 1 bug).
**Impact on plan:** Preserves the plan's delivery-only settlement boundary for both classified results and unexpected handler failures.

## Issues Encountered

- The sandbox could not read the shared uv cache or write Git metadata. Focused checks and commits completed after the scoped approval path was used.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Confirmation and clarification producers can now enqueue frozen outbound jobs only after an executable, lease-fenced consumer exists.
- The local guarded database proofs remain unavailable without `DATABASE_URL` and `ALLOW_DB_RESET=1`; hermetic queue, gateway, dispatch, fake-pair, type, and lint checks passed.

## Verification

- `uv run pytest tests/test_queue_drain.py tests/test_job_kind_drift.py tests/test_gateway.py -q` - 125 passed, 3 skipped.
- `uv run pytest tests/test_fake_repo_pairing.py -q` - 10 passed.
- `uv run mypy app/queue/handlers/send_outbound.py app/queue/dispatch.py app/queue/drain.py` - passed.
- `uv run ruff check app/queue/handlers/send_outbound.py app/queue/dispatch.py app/queue/drain.py tests/conftest.py tests/test_queue_drain.py tests/test_job_kind_drift.py tests/test_fake_repo_pairing.py` - passed.
- `git diff --check` - passed.

## Self-Check: PASSED

- All planned consumer, dispatch, drain, fake-pair, and test artifacts exist.
- Task commits `4e0e82f`, `bac627c`, and `987e0d9` are present in history.
- Required focused verification passed with guarded database checks explicitly unavailable rather than treated as passing.

---
*Phase: 20-exactly-once-send*
*Completed: 2026-07-17*
