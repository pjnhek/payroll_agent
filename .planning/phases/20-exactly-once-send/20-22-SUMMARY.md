---
phase: 20-exactly-once-send
plan: 22
subsystem: outbound-delivery
tags: [resend, provider-handoff, deadline, idempotency, timeout]

# Dependency graph
requires:
  - phase: 20-exactly-once-send
    provides: durable frozen-snapshot provider-handoff authorization and immutable deadline
provides:
  - authorization-first SEND_OUTBOUND handler with bounded record-only and no-op outcomes
  - final provider-boundary deadline check over a fixed synchronous Resend timeout budget
  - process-static Resend RequestsClient and deadline/authority regression coverage
affects: [outbound delivery, retry settlement, exactly-once verification]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - durable authorization returns the only frozen provider payload a handler may forward
    - provider entry rechecks immutable deadline after all local payload preparation
    - Resend synchronous transport configuration is process-static, never request-scoped

key-files:
  created: []
  modified:
    - app/queue/handlers/send_outbound.py
    - app/email/gateway.py
    - app/pipeline/result.py
    - tests/test_gateway.py

key-decisions:
  - "The handler has no independent snapshot, run, record-only, or replay-deadline preflight; it uses only provider-handoff authority."
  - "The 10-second RequestsClient timeout and five-second safety margin are immutable shared budget facts, with the strict check immediately before Resend I/O."

patterns-established:
  - "A record-only handoff returns a bounded successful delivery result without gateway work."
  - "A gateway boundary accepts the frozen snapshot, original deadline, injected clock, and budget explicitly, so elapsed preparation time cannot be hidden."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "SEND_OUTBOUND forwards only an authorized frozen snapshot and treats record-only or active outcomes as bounded no-provider results."
    requirement: SEND-02
    verification:
      - kind: unit
        ref: "tests/test_gateway.py#test_send_handler_record_only_authority_never_reaches_gateway"
        status: pass
      - kind: unit
        ref: "tests/test_gateway.py#test_send_handler_forwards_reclaimed_authorization_unchanged"
        status: pass
    human_judgment: false
  - id: D2
    description: "Resend I/O is denied when the immutable authorization cannot cover its fixed timeout and safety margin after payload preparation."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: "tests/test_gateway.py#test_send_handler_rechecks_authorization_after_authority_is_granted"
        status: pass
      - kind: unit
        ref: "tests/test_gateway.py#test_reserved_snapshot_rejects_expired_authorization_before_resend"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every synchronous Resend request shares one 10-second RequestsClient and preserves the stored Message-ID idempotency key."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: "tests/test_gateway.py#test_reserved_snapshot_installs_one_fixed_sync_resend_timeout"
        status: pass
      - kind: unit
        ref: "tests/test_gateway.py#test_reserved_snapshot_accepts_only_time_strictly_before_deadline"
        status: pass
    human_judgment: false

# Metrics
duration: ~30min
completed: 2026-07-18
status: complete
---

# Phase 20 Plan 22: Durable Provider-Boundary Deadline Summary

**A SEND_OUTBOUND job now gets its only provider authority from the durable handoff, while the Resend boundary independently rejects a frozen request that no longer fits its fixed transport budget.**

## Accomplishments

- Replaced unlocked run/snapshot/replay preflight with the typed handoff authorizer; only authorizations reach the gateway, and record-only work yields `DELIVERY_RECORD_ONLY`.
- Added immutable 10-second-plus-five-second send budget and strict post-preparation deadline check, returning `DELIVERY_AUTHORIZATION_EXPIRED` before any Resend I/O.
- Installed one module-initialized `resend.RequestsClient(timeout=10)` and covered static-client, equality-boundary, gateway, record-only, and reclaimed-handoff forwarding paths.

## Task Commits

1. **Task 1: Enforce the immutable handoff deadline at the synchronous Resend boundary** — `c329f20` (fix)

## Files Created/Modified

- `app/queue/handlers/send_outbound.py` — forwards only the durable authorization snapshot, deadline, clock, and shared budget.
- `app/email/gateway.py` — uses one static Resend client and performs the final strict deadline guard before sending.
- `app/pipeline/result.py` — supplies bounded delivery reasons and the immutable send-budget value object.
- `tests/test_gateway.py` — proves authority forwarding, expiry denial, fixed timeout, and Message-ID preservation.

## Decisions Made

- The gateway requires its budget as an explicit argument and rejects a timeout mismatch instead of mutating Resend's process-global client.
- Equality at the deadline minus timeout and safety margin is denied; only a strictly earlier timestamp can initiate provider I/O.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected aware-datetime deadline validation.**

- **Found during:** Task 1 verification.
- **Issue:** The initial validation inverted the timezone test and rejected valid UTC deadlines.
- **Fix:** Accept aware datetimes and reject only naive deadlines.
- **Files modified:** `app/email/gateway.py`
- **Verification:** focused gateway tests, Ruff, and mypy passed.
- **Committed in:** `c329f20`

**Total deviations:** 1 auto-fixed (Rule 1 correctness).
**Impact on plan:** No scope expansion; the correction is necessary for every durable UTC authorization to reach the intended strict check.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Retry/settlement consumers can release or finalize the exact handoff after the bounded gateway result; the provider boundary no longer permits a send after its immutable deadline.

## Verification

- `uv run pytest -q tests/test_gateway.py tests/test_delivery.py tests/test_queue_durability.py` — **54 passed, 52 skipped**.
- `uv run ruff check app/queue/handlers/send_outbound.py app/email/gateway.py app/pipeline/result.py tests/test_gateway.py` — **passed**.
- `uv run mypy` — **passed: 161 source files**.

## Self-Check: PASSED

---
*Plan: 20-22*
*Completed: 2026-07-18*
