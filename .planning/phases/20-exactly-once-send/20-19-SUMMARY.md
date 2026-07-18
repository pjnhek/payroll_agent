---
phase: 20-exactly-once-send
plan: 19
subsystem: database/queue
tags: [postgres, queue, exactly-once, lease-fencing, outbound-delivery]

# Dependency graph
requires:
  - phase: 20-exactly-once-send
    provides: stale-epoch provider/no-write fences for outbound delivery
provides:
  - distinct lost-lease and invalid-context SEND_OUTBOUND settlement outcomes
  - exact-token retirement of stale or malformed outbound leases
  - drain token cleanup only after a durable send settlement outcome
affects: [outbound delivery, queue drain, phase-20-20, phase-21 durability proofs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - an absent exact lease is a no-write LOST_LEASE, while an owned invalid outbound context is retired before INVALID_CONTEXT returns
    - generic pipeline FENCED remains compatible; SEND_OUTBOUND uses explicit ownership/context outcomes

key-files:
  created: []
  modified:
    - app/db/repo/job_settlement.py
    - app/queue/drain.py
    - tests/test_queue_drain.py
    - tests/test_queue_durability.py
    - tests/conftest.py
    - tests/test_phase20_fake_parity.py

key-decisions:
  - "Invalid SEND_OUTBOUND context retires only the exact leased job with a bounded delivery:invalid_context diagnostic; it does not touch snapshots, attempts, or payroll state."
  - "Final-attempt stale or malformed SEND_OUTBOUND context dead-letters the exact row and returns INVALID_CONTEXT without creating review evidence."
  - "Drain retains generic pipeline FENCED behavior, but SEND_OUTBOUND cannot use FENCED to discard an invalid-context token."

patterns-established:
  - "Ownership loss and current-context invalidity are separate bounded queue outcomes."
  - "In-memory queue parity mirrors durable invalid-context retirement so offline drain tests exercise the same contract."

requirements-completed: [SEND-02, SEND-03]

coverage:
  - id: D1
    description: "Owned stale-epoch SEND_OUTBOUND leases retire by exact token without delivery, reservation, or payroll writes."
    requirement: SEND-02
    verification:
      - kind: unit
        ref: "tests/test_phase20_fake_parity.py::test_fake_stale_epoch_send_settlement_retires_invalid_lease_without_mutation"
        status: pass
      - kind: integration
        ref: "tests/test_queue_durability.py::test_invalid_context_stale_epoch_retirement_after_epoch_fence"
        status: unknown
    human_judgment: false
  - id: D2
    description: "Drain distinguishes invalid context from a reclaimed lease and discards held tokens only after the durable result."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py::test_drain_invalid_context_durably_retires_lease_before_token_discard"
        status: pass
      - kind: unit
        ref: "tests/test_queue_drain.py::test_drain_distinguishes_lost_lease_from_invalid_context"
        status: pass
    human_judgment: false

# Metrics
duration: ~15min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 19: Exact Lease Retirement Summary

**Outbound delivery now reports lost ownership separately from invalid business context, and retires the exact owned invalid lease before the drain forgets its token.**

## Performance

- **Duration:** ~15 minutes
- **Started:** 2026-07-18T01:02:00Z
- **Completed:** 2026-07-18T01:17:22Z
- **Tasks:** 2/2
- **Files modified:** 6

## Accomplishments

- Added `LOST_LEASE` and `INVALID_CONTEXT` settlement/drain outcomes for SEND_OUTBOUND while retaining generic pipeline `FENCED` behavior.
- Retired exact-token invalid delivery leases with a bounded diagnostic, including stale epochs and final-attempt reaping, without mutating delivery evidence, frozen reservations, or payroll state.
- Proved drain token handling for durable invalid-context retirement, no-write lost ownership, and the pre-existing settlement-exception shutdown path.

## Task Commits

1. **Task 1 RED: add invalid-context lease retirement regressions** — `c478190` (test)
2. **Task 1 GREEN: separate lost-lease and invalid-context settlement outcomes** — `8389245` (feat)
3. **Task 2: make drain token bookkeeping safe for invalid context** — `22b4382` (test)

## Files Created/Modified

- `app/db/repo/job_settlement.py` — introduces explicit outcomes and exact-token invalid-context retirement for normal settlement and final reaping.
- `app/queue/drain.py` — maps the new outcomes and only releases SEND_OUTBOUND tokens for durable or lost-ownership results.
- `tests/test_queue_drain.py` — exercises invalid-context and lost-lease drain bookkeeping.
- `tests/test_queue_durability.py` — covers stale-epoch and exact-token SQL retirement semantics.
- `tests/conftest.py` — mirrors delivery fencing outcomes in the in-memory repository.
- `tests/test_phase20_fake_parity.py` — keeps stale-epoch fake parity aligned with the durable retirement contract.

## Decisions Made

- Invalid-context normal settlement completes the obsolete job; invalid final-attempt reaping dead-letters it. Both clear the exact held token and return `INVALID_CONTEXT`.
- A missing or reclaimed lease returns `LOST_LEASE` without delivery, attempt, or payroll writes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Correctness] Updated the in-memory repository parity contract**
- **Found during:** Task 1
- **Issue:** The existing fake SEND_OUTBOUND settlement and Phase 20 parity regressions still treated stale context as `FENCED` and left its lease held, diverging from the newly required durable production behavior.
- **Fix:** Mirrored exact invalid-context retirement in `InMemoryRepo` and updated the paired stale-epoch regressions.
- **Files modified:** `tests/conftest.py`, `tests/test_phase20_fake_parity.py`
- **Verification:** `uv run pytest -q tests/test_phase20_fake_parity.py tests/test_queue_drain.py tests/test_queue_durability.py` — 69 passed, 49 skipped.
- **Committed in:** `8389245`

---

**Total deviations:** 1 auto-fixed (Rule 1 correctness).
**Impact on plan:** Required parity work only; no production scope expansion.

## Issues Encountered

The guarded live-Postgres durability tests were skipped because `DATABASE_URL` and `ALLOW_DB_RESET=1` are not configured locally. Unit/fake regression coverage passed; live integration coverage remains unavailable rather than claimed as passing.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 20-20 can now rely on explicit outbound fencing outcomes: stale send context no longer strands a lease or hides behind generic `FENCED`.

## Verification

- `uv run pytest -q tests/test_queue_drain.py tests/test_queue_durability.py` — **69 passed, 49 skipped**.
- `uv run ruff check app/db/repo/job_settlement.py app/queue/drain.py tests/test_queue_drain.py tests/test_queue_durability.py` — **passed**.

## Self-Check: PASSED

---
*Plan: 20-19*
*Completed: 2026-07-17*
