---
phase: 20-exactly-once-send
plan: 24
subsystem: outbound-delivery
tags: [postgres, provider-handoff, lease-fencing, retry, in-memory-parity]

# Dependency graph
requires:
  - phase: 20-exactly-once-send
    provides: durable pre-provider authority, immutable frozen snapshots, and deadline-bounded gateway results
provides:
  - exact-owner handoff finalization, retry release, delivery-review release, and final-lease reaping
  - no-provider record-only settlement and explicit authorization-expiry review routing
  - in-memory provider-handoff adoption and exact-release parity
affects: [outbound delivery, retry settlement, delivery review, exactly-once verification]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - settlement locks jobs -> frozen reservation -> run -> current handoff, and never adopts provider authority
    - every provider result releases or finalizes the current exact handoff before changing the matching job lease
    - hermetic queue tests model active handoff ownership, predecessor expiry, and adopted-token fencing

key-files:
  created: []
  modified:
    - app/db/repo/job_settlement.py
    - app/queue/handlers/send_outbound.py
    - tests/conftest.py
    - tests/test_phase20_fake_parity.py

key-decisions:
  - "Only the pre-provider authorizer may adopt an expired predecessor; settlement and final-lease reaping can only lock and release an already-current handoff."
  - "DELIVERY_RECORD_ONLY has no provider-attempt row or handoff, while DELIVERY_AUTHORIZATION_EXPIRED writes the bounded authorization_expired review category and cannot reschedule."

patterns-established:
  - "A retry turns the current handoff into retry_scheduled history in the same transaction before the job becomes pending."
  - "A fake repository must preserve exact owner, lease expiry, and handoff identity semantics instead of simplifying external-provider fencing."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "Delivery settlement and final-lease reaping release or finalize only the exact current provider handoff before job state changes."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: "tests/test_phase20_fake_parity.py#test_fake_retry_releases_exact_handoff_then_reauthorizes_frozen_slot"
        status: pass
      - kind: unit
        ref: "tests/test_send_idempotency.py#test_delivery_settlement_uses_an_exact_lease_and_pii_safe_attempt_facts"
        status: pass
    human_judgment: false
  - id: D2
    description: "An expired provider authorization becomes purpose-aware delivery review with a bounded deadline category and no retry job."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: "tests/test_phase20_fake_parity.py#test_fake_expired_authorization_releases_exact_handoff_to_review"
        status: pass
    human_judgment: false
  - id: D3
    description: "The in-memory repository preserves crash adoption, predecessor-token rejection, original frozen snapshot identity, and record-only completion semantics."
    requirement: SEND-02
    verification:
      - kind: unit
        ref: "tests/test_phase20_fake_parity.py#test_fake_crash_reclaim_adopts_only_expired_exact_handoff"
        status: pass
      - kind: unit
        ref: "tests/test_phase20_fake_parity.py#test_fake_record_only_settlement_completes_without_attempt_or_handoff"
        status: pass
    human_judgment: false

# Metrics
duration: ~50min
completed: 2026-07-18
status: complete
---

# Phase 20 Plan 24: Exact Handoff Settlement Summary

**SEND_OUTBOUND settlement now changes only the handoff currently owned by its exact leased job, while retries, review outcomes, reaping, and the in-memory fake preserve the same durable fence.**

## Accomplishments

- Added job → reservation → run → exact-handoff locking to normal settlement and final-lease reaping; success finalizes, retry releases to `retry_scheduled`, and review releases to `delivery_review` before any lease transition.
- Routed record-only work to a no-attempt/no-handoff completion and authorization expiry to `authorization_expired` delivery review without rescheduling.
- Made the in-memory repository model active provider ownership, crash-safe expired-lease adoption, exact release, and retrigger fencing; added retry/replay, expiry, record-only, and reclaimed-send regressions.

## Task Commits

1. **Task 1: Finalize only the current exact handoff and prove reclaimed adoption parity** — `4218057` (fix)

## Files Created/Modified

- `app/db/repo/job_settlement.py` — locks and releases/finalizes the exact active handoff before delivery settlement or final reaping changes a job.
- `app/queue/handlers/send_outbound.py` — consumes bounded authorization results without leaking repository class references into queue-tier static checks.
- `tests/conftest.py` — in-memory active-handoff storage, exact owner release, adoption, and epoch fence parity.
- `tests/test_phase20_fake_parity.py` — record-only, expiry-review, retry reauthorization, predecessor-token, and crash-adoption regressions.
- `tests/test_send_idempotency.py`, `tests/test_clarify.py`, `tests/test_queue_drain.py` — existing hermetic delivery contracts now acquire and release current provider authority.

## Decisions Made

- Settlement has no adoption branch: only `authorize_outbound_provider_handoff` can transfer an expired predecessor to a newly claimed lease.
- A record-only completion marks the frozen slot complete without pretending to have made a provider attempt; expiration writes only the fixed `authorization_expired` category and enters delivery review.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Kept existing hermetic delivery tests on the new provider-authority contract.**

- **Found during:** Task 1 verification.
- **Issue:** Older tests and gateway doubles settled SEND_OUTBOUND jobs without acquiring a handoff or rejected the gateway's already-established deadline keywords, bypassing or misreporting the new safety path.
- **Fix:** Added exact-handoff scripts to the SQL doubles and updated provider doubles to accept the established keyword boundary.
- **Files modified:** `tests/test_send_idempotency.py`, `tests/test_clarify.py`, `tests/test_alias_full_loop.py`, `tests/test_delivery.py`, `tests/test_queue_drain.py`.
- **Verification:** `uv run pytest -q tests/test_alias_full_loop.py tests/test_delivery.py tests/test_queue_drain.py tests/test_phase20_fake_parity.py tests/test_send_idempotency.py tests/test_clarify.py` — 191 passed, 3 skipped.
- **Committed in:** `4218057`

**2. [Rule 2 - Missing Critical] Added exact handoff lifecycle behavior to the in-memory repository.**

- **Found during:** Task 1 implementation.
- **Issue:** The fake had no provider-handoff data, so default-running tests could not detect an adoption or exact-owner-release violation.
- **Fix:** Added active-handoff storage, predecessor-expiry adoption, exact-owner final/retry/review release, and an active-fence check before fake epoch changes.
- **Files modified:** `tests/conftest.py`, `tests/test_phase20_fake_parity.py`.
- **Verification:** focused fake parity suite — 45 passed.
- **Committed in:** `4218057`

**Total deviations:** 2 auto-fixed (1 Rule 1 test-contract bug, 1 Rule 2 critical parity safeguard).
**Impact on plan:** Both changes enforce the planned exact-owner boundary across production and hermetic execution; no scope expansion.

## Issues Encountered

- Guarded live-Postgres queueproof tests remain skipped without `DATABASE_URL` and `ALLOW_DB_RESET=1`; hermetic and SQL-shape coverage passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Provider handoff ownership is now settled/reaped consistently with pre-provider authorization, including bounded deadline review and retry release.
- Live database queueproofs can be run when resettable Postgres credentials are available.

## Verification

- `uv run pytest -q tests/test_phase20_fake_parity.py tests/test_queue_durability.py tests/test_queue_drain.py` — **114 passed, 49 skipped**.
- `uv run pytest -q tests/test_alias_full_loop.py tests/test_delivery.py tests/test_queue_drain.py tests/test_phase20_fake_parity.py tests/test_send_idempotency.py tests/test_clarify.py` — **191 passed, 3 skipped**.
- `uv run ruff check app/db/repo/job_settlement.py app/queue/handlers/send_outbound.py tests/conftest.py tests/test_alias_full_loop.py tests/test_delivery.py tests/test_queue_drain.py tests/test_phase20_fake_parity.py tests/test_send_idempotency.py tests/test_clarify.py` — **passed**.
- `uv run mypy` — **passed: 161 source files**.

## Self-Check: PASSED

---
*Plan: 20-24*
*Completed: 2026-07-18*
