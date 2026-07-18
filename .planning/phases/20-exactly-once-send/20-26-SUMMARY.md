---
phase: 20-exactly-once-send
plan: 26
subsystem: outbound-delivery
tags: [postgres, provider-handoff, delivery-review, lease-fencing, in-memory-parity]

# Dependency graph
requires:
  - phase: 20-exactly-once-send
    provides: immutable outbound snapshots, deadline-bounded provider authorization, and exact handoff settlement
provides:
  - bounded pre-provider replay-window expiry translation before provider I/O
  - exact no-handoff authorization-expiry settlement to purpose-aware delivery review
  - production SQL-shape and in-memory parity coverage for expiry, stale lease, and foreign handoff fences
affects: [outbound delivery, queue settlement, delivery review, exactly-once verification]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - pre-provider expiry is a typed terminal delivery result, never a generic no-op
    - no-handoff review settlement locks the active-handoff slot empty before writing append-only review evidence

key-files:
  created: []
  modified:
    - app/queue/handlers/send_outbound.py
    - app/db/repo/job_settlement.py
    - tests/conftest.py
    - tests/test_gateway.py
    - tests/test_phase20_fake_parity.py
    - tests/test_send_idempotency.py

key-decisions:
  - "Only ProviderHandoffActive('replay_window_closed') maps to DELIVERY_AUTHORIZATION_EXPIRED before the gateway seam."
  - "Pre-provider review requires the exact leased reserved slot, current purpose status and epoch, an expired replay window, and no active handoff; an active handoff follows the existing exact-owner path."

patterns-established:
  - "Delivery-review evidence is shared after the authority-specific release decision, so the no-handoff path cannot release an authority it never acquired."
  - "The in-memory repository models the same expired-window, empty-handoff fence as production settlement."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "The handler preserves the closed replay-window result as a terminal authorization-expired delivery outcome and makes no gateway or Resend call."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: "tests/test_gateway.py#test_send_handler_translates_pre_provider_replay_window_expiry_without_provider_io"
        status: pass
    human_judgment: false
  - id: D2
    description: "An expired confirmation or clarification reservation with no provider handoff appends one authorization_expired review fact, preserves its snapshot, and completes its exact job."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: "tests/test_phase20_fake_parity.py#test_fake_pre_provider_expiry_enters_purpose_review_without_handoff"
        status: pass
      - kind: unit
        ref: "tests/test_send_idempotency.py#test_pre_provider_expiry_settlement_requires_no_active_handoff_and_writes_review"
        status: pass
    human_judgment: false
  - id: D3
    description: "Stale leases, foreign active handoffs, and unrelated terminal results cannot use the no-handoff review branch."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: "tests/test_phase20_fake_parity.py#test_fake_pre_provider_expiry_rejects_a_foreign_active_handoff"
        status: pass
      - kind: unit
        ref: "tests/test_phase20_fake_parity.py#test_fake_pre_provider_expiry_lost_lease_writes_no_review_evidence"
        status: pass
    human_judgment: false

# Metrics
duration: ~32min
completed: 2026-07-18
status: complete
---

# Phase 20 Plan 26: Pre-Provider Expiry Settlement Summary

**A closed pre-provider replay window now becomes purpose-aware delivery review without minting a replacement key, composing content, creating a handoff, or calling Resend.**

## Accomplishments

- Translated only the authorizer's fixed `replay_window_closed` result into terminal `DELIVERY_AUTHORIZATION_EXPIRED` before the frozen-snapshot gateway boundary.
- Added fenced settlement for an expired reservation with no active handoff: it appends `authorization_expired`, transitions the correct delivery purpose to review, and completes the exact lease.
- Mirrored the no-handoff branch in the in-memory repository and added regressions for confirmation, clarification, stale leases, foreign handoffs, unrelated results, and immutable snapshots.

## Task Commits

1. **Task 1: Preserve the bounded pre-provider replay-window-expired result** — `63074d1` (fix)
2. **Task 2: Settle pre-provider authorization expiry directly to purpose-aware review** — `0c48c2c` (fix)

## Files Created/Modified

- `app/queue/handlers/send_outbound.py` — preserves the exact replay-window expiry result before provider work.
- `app/db/repo/job_settlement.py` — locks any active handoff and directly writes review evidence only when the slot is empty.
- `tests/conftest.py` — mirrors the narrowly fenced no-handoff branch.
- `tests/test_gateway.py` — proves the handler forwards the exact job and remains provider-free.
- `tests/test_phase20_fake_parity.py` — proves purpose-specific review, snapshot preservation, stale/foreign fences, and no arbitrary missing-handoff review.
- `tests/test_send_idempotency.py` — verifies production settlement SQL shape without an outbound-handoff update.

## Decisions Made

- The no-handoff path requires terminal delivery expiry, an expired immutable replay window, non-record-only context, and no active handoff for the locked run.
- An active exact handoff keeps using the existing release-to-review path; a foreign handoff is invalid context and cannot create review evidence.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Imported the bounded stage enum in the in-memory settlement mirror.**

- **Found during:** Task 2 focused regression execution.
- **Issue:** The added exact-result guard referenced `PipelineStage` without importing it in the local fake method.
- **Fix:** Imported `PipelineStage` with the other bounded pipeline values.
- **Files modified:** `tests/conftest.py`.
- **Verification:** focused parity tests, the full plan test selection, Ruff, and mypy passed.
- **Committed in:** `0c48c2c`.

**Total deviations:** 1 auto-fixed (Rule 1 correctness).
**Impact on plan:** The fix only restores the intended bounded-result fence in the required in-memory parity implementation.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 20-27 still owns the schema-vocabulary deployment proof for `authorization_expired`; this plan intentionally does not claim that a live database accepts that new attempt category yet.

## Verification

- RED: `uv run pytest -q tests/test_gateway.py -k 'replay_window_closed or authorization_expired or send_handler'` — **1 failed, 4 passed** before the Task 1 handler implementation.
- `uv run pytest -q tests/test_gateway.py -k 'replay_window_closed or authorization_expired or send_handler'` — **5 passed** after Task 1.
- RED: `uv run pytest -q tests/test_phase20_fake_parity.py tests/test_send_idempotency.py -k 'pre_provider_expiry or pre_provider_branch'` — **4 failed, 1 passed** before the Task 2 settlement implementation.
- `uv run pytest -q tests/test_phase20_fake_parity.py tests/test_send_idempotency.py tests/test_gateway.py` — **126 passed, 6 skipped**.
- `uv run ruff check app/queue/handlers/send_outbound.py app/db/repo/job_settlement.py tests/conftest.py tests/test_gateway.py tests/test_phase20_fake_parity.py tests/test_send_idempotency.py` — **passed**.
- `uv run mypy` — **Success: no issues found in 161 source files**.

## Self-Check: PASSED

---
*Plan: 20-26*
*Completed: 2026-07-18*
