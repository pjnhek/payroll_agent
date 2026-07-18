---
phase: 20-exactly-once-send
plan: 17
subsystem: database/testing
tags: [postgres, psycopg, exactly-once, idempotency, reply-epoch]

# Dependency graph
requires:
  - phase: 20-exactly-once-send
    provides: immutable outbound reservations, purpose-aware delivery proof, and reply-epoch state
provides:
  - current-reply-epoch scoping for sent outbound Message-ID proof
  - hermetic SQL-shape protection and delivery seam regression coverage
  - guarded real-Postgres regression for stale and current confirmation epochs
affects: [confirmation delivery, retrigger recovery, Phase 21 durability proofs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - sent proof queries correlate the immutable email epoch with payroll_runs.reply_epoch
    - delivery proof tests reject broad run-level lookup and preserve frozen replay boundaries

key-files:
  created: []
  modified:
    - app/db/repo/emails.py
    - tests/test_send_idempotency.py

key-decisions:
  - "Use the existing correlated payroll_runs.reply_epoch predicate as the sole current-epoch source; do not alter reservation or snapshot behavior."
  - "Keep confirmation delivery purpose-aware through get_outbound_message_id and explicitly reject a broad round lookup in the regression."

patterns-established:
  - "Historical sent rows remain append-only evidence, but only the run's current reply epoch can authorize delivery suppression."
  - "A stale-epoch test must prove the new epoch remains eligible before proving the current epoch is idempotently suppressed."

requirements-completed: [SEND-01]

coverage:
  - id: D1
    description: "Sent confirmation proof is scoped to the run's current reply epoch, so epoch 0 cannot suppress epoch 1."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: tests/test_send_idempotency.py#test_get_outbound_message_id_sql_shape_requires_current_epoch
        status: pass
      - kind: integration
        ref: tests/test_send_idempotency.py#test_sent_confirmation_proof_is_scoped_to_current_reply_epoch
        status: unknown
    human_judgment: true
    rationale: "The guarded live-Postgres regression was skipped because DATABASE_URL and ALLOW_DB_RESET=1 were not configured in this environment."
  - id: D2
    description: "Confirmation delivery consumes the purpose-aware current-epoch proof seam without broad lookup or frozen-content rebuilding."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: tests/test_send_idempotency.py#test_delivery_confirmation_uses_current_epoch_sent_proof
        status: pass
      - kind: other
        ref: uv run pytest -q tests/test_send_idempotency.py tests/test_delivery.py
        status: pass
    human_judgment: false

# Metrics
duration: 2min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 17: Current-Epoch Sent-Proof Summary

Sent confirmation proof now requires the outbound row's epoch to equal the run's current `reply_epoch`, preventing a successful epoch-0 confirmation from suppressing a human-authorized epoch-1 confirmation.

## Performance

- **Duration:** ~2 minutes
- **Started:** 2026-07-17T17:35:57-07:00
- **Completed:** 2026-07-17T17:37:11-07:00
- **Tasks:** 2/2
- **Files modified:** 2

## Accomplishments

- Added `email_messages.epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s)` to `get_outbound_message_id`, preserving purpose, outbound direction, sent-state, ordering, and parameterization.
- Added a hermetic SQL-shape guard and guarded real-Postgres regression covering epoch-0 invisibility after `clear_reply_context()` and epoch-1 visibility.
- Added a delivery-link regression proving stale proof leaves the current slot eligible, current proof takes the already-delivered branch, and delivery does not use `get_outbound_for_round` or rebuild frozen content.

## Task Commits

Each task was committed atomically:

1. **Task 1: Scope sent-proof lookup to the run's current epoch** - `df4b695` (TDD RED), `8b8b38a` (GREEN)
2. **Task 2: Reconfirm the delivery guard's current-epoch call contract** - `4b123ce` (focused delivery-proof regression refinement)

The Task 1 RED commit introduced the shared test-module regressions for both tasks; the Task 2 commit added the explicit broad-lookup failure guard.

## Files Created/Modified

- `app/db/repo/emails.py` - correlates sent-proof lookup to the current run epoch.
- `tests/test_send_idempotency.py` - SQL-shape, live epoch, and delivery-to-proof regressions.

## Decisions Made

- Reused the existing correlated `payroll_runs.reply_epoch` source rather than introducing another epoch read or changing the immutable reservation path.
- Kept the delivery branch purpose-aware and proof-only; epoch handling belongs in the repository query, while snapshot replay remains unchanged.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The guarded live-Postgres test was unavailable locally because `DATABASE_URL` and `ALLOW_DB_RESET=1` were not set. It remains skip-guarded and is included in the summary as unknown evidence rather than treated as a pass.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

SEND-01's sent-proof epoch leak is closed. Phase 21 can consume the current-epoch proof contract; run the guarded Postgres regression in an environment with the required database credentials for live evidence.

## Verification

- `uv run pytest -q tests/test_send_idempotency.py tests/test_delivery.py` — 47 passed, 3 skipped.
- `uv run ruff check app/db/repo/emails.py tests/test_send_idempotency.py` — passed.

## TDD Gate Compliance

- RED commit present: `df4b695`.
- GREEN implementation commit present after RED: `8b8b38a`.
- Task 2 regression refinement committed separately: `4b123ce`.

## Self-Check: PASSED

- Summary file created at `.planning/phases/20-exactly-once-send/20-17-SUMMARY.md`.
- Commits `df4b695`, `8b8b38a`, and `4b123ce` found in git history.
- Targeted tests and Ruff verification passed.
- No plan-created stubs or unplanned threat surfaces found.

---
*Plan: 20-17*
*Completed: 2026-07-17*
