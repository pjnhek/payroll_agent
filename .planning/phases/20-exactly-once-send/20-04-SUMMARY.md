---
phase: 20-exactly-once-send
plan: "04"
subsystem: delivery
tags: [confirmation, durable-queue, immutable-snapshot, approval]

requires:
  - phase: 20-exactly-once-send
    provides: "immutable outbound snapshots and executable fenced send jobs"
provides:
  - "Confirmation approval reserves one immutable snapshot and identifier-only send job"
  - "Replay-aware confirmation scheduling that never re-drafts or regenerates paystubs"
  - "Post-commit wake ordering with approved business state while delivery is pending"
affects: [20-06, 20-07, 20-10, 20-12, outbound-delivery]

tech-stack:
  added: []
  patterns: [reserve-or-load delivery, approval-to-job transaction, post-commit wake]

key-files:
  created: []
  modified:
    - app/pipeline/delivery.py
    - app/pipeline/send_guard.py
    - app/db/repo/emails.py
    - app/routes/runs.py
    - app/queue/handlers/send_outbound.py
    - tests/conftest.py
    - tests/test_delivery.py
    - tests/test_hitl.py

key-decisions:
  - "Approval owns the transaction that claims the run, freezes the confirmation, and inserts its one send job."
  - "An unconfirmed slot exposes its immutable email ID so replay can enqueue existing work without rebuilding content."
  - "Record-only runs flow through the frozen snapshot and settlement path but do not call the external provider."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "A confirmation is composed and converted into exactly one frozen send job, while a replay loads the existing slot without drafting, PDF generation, or mutable reads."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: tests/test_delivery.py#test_confirmation_reservation_enqueues_one_frozen_send_job
        status: pass
      - kind: unit
        ref: tests/test_delivery.py#test_confirmation_replay_loads_snapshot_without_rebuilding_payload
        status: pass
    human_judgment: false
  - id: D2
    description: "Approval commits its durable handoff before waking a worker, creates no second job on a repeated submission, and retains approved while delivery is owed."
    requirement: SEND-02
    verification:
      - kind: unit
        ref: tests/test_hitl.py#test_approve_commits_one_delivery_job_before_waking
        status: pass
    human_judgment: false
  - id: D3
    description: "A record-only confirmation uses the frozen snapshot contract without calling the provider."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: tests/test_delivery.py#test_record_only_snapshot_settles_without_calling_the_provider
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 04: Durable Confirmation Scheduling Summary

**Approval now freezes and queues confirmation delivery atomically; only the durable worker can send the stored payload.**

## Performance

- **Duration:** 25 min
- **Completed:** 2026-07-17T19:27:28Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- Replaced synchronous confirmation sends with reserve-or-load scheduling that persists one provider-ready snapshot and one identifier-only `SEND_OUTBOUND` job.
- Changed approval to claim the run, reserve/enqueue delivery work in the same transaction, and wake workers only after commit.
- Made replay use an immutable email identifier rather than current line items, contact data, drafting, or PDF generation.
- Kept record-only confirmations on the same frozen contract while preventing their queued handler from contacting the provider.

## Task Commits

1. **Task 1: Make confirmation composition a one-time reserve-and-enqueue transaction** — `7bb7678` (RED), `b7797a0` (GREEN)
2. **Task 2: Make the operator approval route schedule only durable delivery work** — `7fd440f` (RED), `0b57dc4` (GREEN)

## Files Created/Modified

- `app/pipeline/delivery.py` — Creates or reloads one frozen confirmation slot and enqueues only its stored email ID.
- `app/pipeline/send_guard.py` — Returns a replay policy with the immutable slot identity while retaining the scoped unconfirmed-send boundary.
- `app/db/repo/emails.py` — Returns the immutable email ID for an unconfirmed slot.
- `app/routes/runs.py` — Commits approval and durable delivery scheduling together, then wakes after commit.
- `app/queue/handlers/send_outbound.py` — Completes record-only frozen work without a provider request.
- `tests/conftest.py`, `tests/test_delivery.py`, and `tests/test_hitl.py` — Mirror immutable slot IDs and pin one-time composition, replay isolation, post-commit wake, duplicate approval no-op, and record-only behavior.

## Decisions Made

- The approval request has no provider side effect; a claimed worker owns the external send.
- A valid reserved confirmation is replayed only through its stored email ID and the existing job dedup key.
- The queue status represents delivery owed; an eligible replay does not turn an approved payroll into an error.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Critical behavior] Record-only jobs would have reached the provider**

- **Found during:** Task 2 verification
- **Issue:** Moving delivery to the queue bypassed the former producer-side record-only branch.
- **Fix:** The send handler now returns a successful bounded result for a record-only run after loading and authorizing its frozen snapshot.
- **Files modified:** `app/queue/handlers/send_outbound.py`, `tests/test_delivery.py`
- **Verification:** Focused delivery, approval, queue, type, lint, and diff checks passed.
- **Committed in:** `0b57dc4`

**Total deviations:** 1 auto-fixed (Rule 2 critical behavior). **Impact:** Preserves demo safety without adding a parallel delivery path.

## Issues Encountered

- Guarded database tests skipped because `DATABASE_URL` and `ALLOW_DB_RESET=1` are not configured locally; they were not treated as passing evidence.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Delivery review, paystub presentation, and clarification migration can rely on the confirmation producer's immutable reserve-and-enqueue boundary.
- The legacy caller-argument gateway remains only for the still-unmigrated clarification producer until the planned compatibility removal.

## Verification

- `uv run pytest tests/test_delivery.py tests/test_hitl.py tests/test_send_idempotency.py -q` — 42 passed, 3 skipped.
- `uv run pytest tests/test_delivery.py tests/test_hitl.py tests/test_send_idempotency.py tests/test_queue_drain.py -q` — 109 passed, 3 skipped.
- `uv run mypy app/pipeline/delivery.py app/pipeline/send_guard.py app/routes/runs.py` — passed.
- `uv run ruff check app/pipeline/delivery.py app/pipeline/send_guard.py app/routes/runs.py app/queue/handlers/send_outbound.py tests/test_delivery.py tests/test_hitl.py` — passed.
- `git diff --check` — passed.

## Self-Check: PASSED

- The confirmation producer creates one frozen snapshot/job pair and never reaches the provider at request time.
- Replay avoids all mutable content reads and payload generators.
- Approval remains a bounded redirect/no-op on duplicate submissions and wakes only after its durable handoff is committed.

---
*Phase: 20-exactly-once-send*
*Completed: 2026-07-17*
