---
phase: 20-exactly-once-send
plan: "03"
subsystem: delivery
tags: [resend, idempotency, immutable-snapshot, retry-policy]

requires:
  - phase: 20-exactly-once-send
    provides: immutable outbound snapshots and durable send-job identity
provides:
  - Bounded delivery classifications that replay only approved transient failures
  - Reservation-time replay ladder with a fixed 20-hour cutoff
  - Snapshot-only Resend send adapter using the stored Message-ID as its idempotency key
affects: [20-05, 20-09, 20-10, outbound-delivery]

tech-stack:
  added: []
  patterns: [bounded provider result, fixed reservation-time retry schedule, snapshot-only provider adapter]

key-files:
  created: []
  modified: [app/pipeline/result.py, app/email/gateway.py, tests/test_orchestrator_states.py, tests/test_gateway.py]

key-decisions:
  - "Only timeout, connection, Resend 5xx, and rate_limit_exceeded receive retryable delivery outcomes."
  - "Quota, payload mismatch, validation, credential, and unknown provider outcomes stop for review."
  - "The new provider adapter performs no database transition and never reconstructs an outbound payload."

patterns-established:
  - "Delivery replay eligibility is calculated from reserved_at and not from worker attempts or process time."
  - "Provider retries reuse the stored Message-ID in both the RFC header and Resend idempotency option."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "Bounded delivery classifications allow only documented transient failures to replay."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: tests/test_orchestrator_states.py
        status: pass
    human_judgment: false
  - id: D2
    description: "Automatic replay schedule remains anchored to the original reservation and stops before 20 hours."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: tests/test_orchestrator_states.py
        status: pass
    human_judgment: false
  - id: D3
    description: "The Resend adapter sends only the persisted snapshot with a stable idempotency key."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: tests/test_gateway.py
        status: pass
    human_judgment: false
---

# Phase 20: Exactly-Once Send Summary

**Bounded Resend delivery outcomes and a snapshot-only send adapter preserve one immutable provider request across safe replays.**

## Performance

- **Duration:** 18 min
- **Started:** 2026-07-17T18:32:00Z
- **Completed:** 2026-07-17T18:50:02Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added delivery-specific terminal and retryable result codes without retaining provider content or exception text.
- Added the immediate/1m/5m/15m/1h/3h/8h/16h schedule guarded by the original 20-hour reservation window.
- Added a Resend adapter that rehydrates stored sender, recipient, reply chain, text, attachment bytes, and the original Message-ID-derived key without mutating database state.

## Task Commits

1. **Task 1: Extend bounded delivery classification for Resend responses** - `e34041a`, `cdf8bf7`
2. **Task 2: Add a snapshot-only Resend capability alongside the live legacy caller path** - `e57657d`, `3a6115b`

## Files Created/Modified

- `app/pipeline/result.py` - Delivery failure classifier and reservation-time replay schedule.
- `app/email/gateway.py` - Additive immutable-snapshot Resend send adapter.
- `tests/test_orchestrator_states.py` - Classification and cutoff coverage.
- `tests/test_gateway.py` - Snapshot request, stable-key, and no-local-state-write coverage.

## Decisions Made

- Kept the existing caller-argument `send_outbound` path intact for unmigrated producers.
- Classified `invalid_idempotent_request` as terminal and never created a replacement key.
- Treated Resend quota errors as terminal even though they share HTTP 429 with transient rate pressure.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

The sandbox could not read the existing uv cache or write Git metadata. Required test and commit commands completed after the scoped approval path was used.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 09 can use the bounded result and reservation-time helpers for fenced settlement. Plan 05 can call the snapshot-only adapter after that settlement coordinator exists. The compatibility send path remains available until producer migrations complete.

---
*Phase: 20-exactly-once-send*
*Completed: 2026-07-17*
