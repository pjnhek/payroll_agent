---
phase: 20-exactly-once-send
plan: "09"
subsystem: database
tags: [postgres, durable-queue, resend, delivery, idempotency]

requires:
  - phase: 20-exactly-once-send
    provides: "immutable outbound reservations, send-job identity, and bounded delivery results"
provides:
  - "A purpose-aware coordinator that settles snapshot-backed delivery under an exact lease"
  - "Reservation-time retry cutoff enforcement and fixed-category append-only attempt evidence"
  - "Hermetic and guarded live-Postgres proof paths for retry, cutoff, and zombie rejection"
affects: [20-05, 20-10, 20-11, outbound-delivery]

tech-stack:
  added: []
  patterns: [exact lease settlement, reservation-time cutoff, append-only delivery evidence]

key-files:
  created: []
  modified:
    - app/db/repo/job_settlement.py
    - app/db/repo/__init__.py
    - tests/test_queue_durability.py
    - tests/test_send_idempotency.py

key-decisions:
  - "A delivery retry only reschedules the existing leased job and never calls generic pipeline rewind logic."
  - "The database evaluates the reservation cutoff while the immutable reservation is locked."
  - "Terminal confirmation delivery moves approved work to needs_operator with a fixed review category."

patterns-established:
  - "Delivery settlement: exact job lease lock -> immutable reservation lock -> expected run-state lock -> append bounded attempt fact -> atomically settle the same job."
  - "A fenced loser returns before any attempt, reservation, queue, or run write."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "Confirmation delivery success, replay, terminal review, and lost-lease paths are fenced and append only bounded delivery facts."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: tests/test_send_idempotency.py#test_delivery_settlement_uses_an_exact_lease_and_pii_safe_attempt_facts
        status: pass
      - kind: unit
        ref: tests/test_send_idempotency.py#test_delivery_settlement_rejects_a_lost_lease_before_any_attempt_write
        status: pass
    human_judgment: false
  - id: D2
    description: "Transient delivery reuses the existing job only inside the reservation cutoff and keeps approval intact."
    requirement: SEND-02
    verification:
      - kind: unit
        ref: tests/test_send_idempotency.py#test_delivery_settlement_reschedules_the_same_job_without_rewinding_approval
        status: pass
      - kind: unit
        ref: tests/test_send_idempotency.py#test_delivery_settlement_moves_expired_or_terminal_delivery_to_review
        status: pass
      - kind: integration
        ref: tests/test_queue_durability.py#test_outbound_delivery_settlement_proves_retry_cutoff_and_zombie_fence
        status: unknown
    human_judgment: false

duration: 9min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 09: Fenced Delivery Settlement Summary

**Snapshot-backed delivery now settles success, replay, and review under the exact lease token without rewinding approved payroll state or creating a replacement send key.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-17T18:50:02Z
- **Completed:** 2026-07-17T18:59:14Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added `settle_outbound_delivery_job`, which locks the exact leased job, immutable snapshot, and expected run state before writing an outcome.
- Records only fixed delivery-attempt categories; success marks the reservation sent, transient failures reschedule the original job, and unsafe confirmation delivery enters bounded operator review.
- Added non-vacuous hermetic checks and a guarded Postgres queueproof covering same-job deduplication, cutoff escalation, and stale-token rejection.

## Task Commits

Each task was committed atomically:

1. **Task 1: Settle confirmation send outcomes under the exact lease fence** - `c0e44f9` (test), `9f80433` (feat)
2. **Task 2: Register non-vacuous database proof for cutoff and zombie rejection** - `c061fff` (test)

## Files Created/Modified

- `app/db/repo/job_settlement.py` - Adds exact-token delivery settlement, fixed attempt categorization, database-time cutoff checks, and review escalation.
- `app/db/repo/__init__.py` - Re-exports the delivery settlement facade.
- `tests/test_send_idempotency.py` - Adds hermetic success, retry, cutoff, terminal-review, and no-write-loser checks.
- `tests/test_queue_durability.py` - Adds the guarded live Postgres proof for deduplication, cutoff, and zombie-token fencing.

## Decisions Made

- Kept delivery settlement separate from generic pipeline retry because generic retry rewinds business state that delivery must preserve.
- Made the database, while holding the immutable reservation lock, decide whether the fixed replay window remains open.
- Used `needs_operator` with a fixed category for unsafe confirmation delivery, retaining the original reservation and provider key for review.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Enforced the current reservation cutoff at the database seam**
- **Found during:** Task 1
- **Issue:** Checking only whether the next scheduled slot preceded the cutoff allowed a retry when the reservation was already expired.
- **Fix:** Added a locked database-time cutoff predicate and routed expired retryable outcomes to bounded review.
- **Files modified:** `app/db/repo/job_settlement.py`, `tests/test_send_idempotency.py`
- **Verification:** Focused suite, mypy, and Ruff passed.
- **Committed in:** `9f80433`

**Total deviations:** 1 auto-fixed (1 Rule 3 blocking issue). **Impact:** Necessary safety correction; no scope expansion.

## Issues Encountered

- The guarded live-Postgres proof is unavailable locally because `DATABASE_URL` and `ALLOW_DB_RESET=1` are not configured. It skipped visibly; the hermetic safety checks passed.

## User Setup Required

None - no external service configuration required. A configured disposable Postgres database is needed only to execute the guarded queueproof locally.

## Next Phase Readiness

- Plan 20-05 can register its handler against this coordinator without using generic retry or a new send key.
- Plan 20-11 should add its focused clarification/alias regression coverage before migrating that producer.

## Verification

- `uv run pytest tests/test_queue_durability.py tests/test_send_idempotency.py -q` — 14 passed, 45 skipped (guarded live-DB evidence unavailable).
- `uv run mypy app/db/repo/job_settlement.py` — passed.
- `uv run ruff check app/db/repo/job_settlement.py app/db/repo/__init__.py tests/test_queue_durability.py tests/test_send_idempotency.py` — passed.
- `uv run pytest tests/test_comment_provenance_guard.py -q` — 5 passed.
- `git diff --check` — passed.

## Self-Check: PASSED

- All four planned files exist and the coordinator is re-exported by the repository facade.
- Task commits `c0e44f9`, `9f80433`, and `c061fff` are present in history.
- Required focused tests, type check, lint, provenance guard, and diff check passed; the configured-database proof is explicitly unavailable rather than treated as passing.

---
*Phase: 20-exactly-once-send*
*Completed: 2026-07-17*
