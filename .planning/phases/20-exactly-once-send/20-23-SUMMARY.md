---
phase: 20-exactly-once-send
plan: 23
subsystem: testing
tags: [postgres, concurrency, queueproof, provider-handoff, epoch-fence]

# Dependency graph
requires:
  - phase: 20-exactly-once-send
    provides: durable provider-handoff authorization, exact settlement, and retrigger fencing
provides:
  - barrier-driven two-Postgres-connection regression for the post-authorization provider window
  - intentionally unsafe control proving the race schedule can observe a stale gateway epoch
  - marker-selected queueproof collection evidence for both provider-handoff cases
affects: [phase-20-verification, concurrency-proof-ci, outbound-delivery]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - a real authorizer may be wrapped only to commit and pause before the otherwise unmodified handler reaches its provider seam
    - queueproof controls may use reset-fixture-local SQL to remove a fence and demonstrate that a protected race test is non-vacuous

key-files:
  created: []
  modified:
    - tests/test_queue_durability.py

key-decisions:
  - "The authorization pause is before, not inside, the gateway spy, so the proof cannot pass by gateway-mock serialization."
  - "The control releases only its exact active handoff through direct SQL in the reset-guarded fixture, then settles the obsolete job as invalid context."

patterns-established:
  - "Real queueproof races assert distinct pg_backend_pid values, barrier participation, and explicit worker-thread quiescence."
  - "Unavailable reset-authorized Postgres is recorded as unknown live evidence, never as a passing concurrency claim."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "A durable handoff blocks a separate retrigger connection from bumping the epoch before the authorized handler reaches the gateway."
    requirement: SEND-01
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py#test_provider_handoff_blocks_epoch_bump_before_gateway"
        status: unknown
    human_judgment: true
    rationale: "The reset-authorized real Postgres run is unavailable locally; the guarded test skipped and must obtain a zero-skip CI or resettable-DB pass."
  - id: D2
    description: "The paired unsafe control proves the same schedule observes epoch 1 at the gateway when its active handoff is deliberately released."
    requirement: SEND-02
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py#test_provider_handoff_race_control_observes_stale_gateway_when_fence_is_released"
        status: unknown
    human_judgment: true
    rationale: "The reset-authorized real Postgres run is unavailable locally; marker collection succeeded but execution skipped."
  - id: D3
    description: "Both proofs are selected by the existing marker-based queue durability CI command."
    requirement: SEND-03
    verification:
      - kind: other
        ref: "uv run pytest tests/ -m queueproof --collect-only -q"
        status: pass
    human_judgment: false

# Metrics
duration: ~25min
completed: 2026-07-18
status: complete
---

# Phase 20 Plan 23: Real-Connection Provider Handoff Proof Summary

**The provider-handoff fence now has a two-connection Postgres regression at its post-authorization/pre-gateway boundary, paired with an unsafe control that would expose a stale provider call.**

## Accomplishments

- Added a barrier-driven protected case that commits the real authorization, asserts distinct database backend PIDs, rejects `clear_reply_context`, and records gateway epoch 0 only after the rejection.
- Added a reset-fixture-local unsafe control that releases the exact handoff before retrigger, advances to epoch 1, and proves the unchanged handler would call the stale authorization at epoch 1.
- Confirmed both tests are collected by the existing `tests/ -m queueproof` CI selector without changing its filename lists.

## Task Commits

1. **Task 1: Add the barrier-driven two-connection handoff regression** — `d72b001` (test)
2. **Task 2: Prove the race harness can observe the unsafe control and register live evidence correctly** — `d72b001` (test)

## Files Created/Modified

- `tests/test_queue_durability.py` — real-Postgres protected/control race tests, backend-PID assertions, passive provider spies, exact cleanup settlement, and falsifying-mutation documentation.

## Decisions Made

- The test wraps only the imported repository authorizer to create the committed pause. It does not alter the handler flow or use the gateway spy to control scheduling.
- The control uses direct SQL only inside the two-factor reset fixture and settles the now-stale lease as `INVALID_CONTEXT`, leaving no leased worker job behind.

## Deviations from Plan

None - plan executed as written. Both TDD tasks are implemented in one cohesive test commit because the paired control shares the helper and the same barrier harness.

## Issues Encountered

- No `DATABASE_URL` or `ALLOW_DB_RESET=1` was available in this workspace. The focused live command therefore reported **2 skipped, 49 deselected**. This is unavailable evidence, not a passing real-Postgres proof.

## User Setup Required

None - no external service configuration required. A reset-authorized PostgreSQL environment is required only to close the live-evidence gap.

## Next Phase Readiness

- CI's existing ephemeral Postgres `queueproof` step will execute both new tests and fail if either skips.
- Phase verification must retain the live-evidence gap until CI or a local `DATABASE_URL` with `ALLOW_DB_RESET=1` records a no-skip pass.

## Verification

- `uv run ruff check tests/test_queue_durability.py` — **passed**.
- `uv run mypy` — **passed: 161 source files**.
- `uv run pytest tests/ -m queueproof --collect-only -q | rg 'test_provider_handoff_(blocks_epoch_bump_before_gateway|race_control_observes_stale_gateway_when_fence_is_released)'` — **both tests collected**.
- `uv run pytest -q tests/test_queue_durability.py -m 'integration and queueproof' -k provider_handoff -rs` — **2 skipped, 49 deselected**; unavailable credentials, not a pass.

## Self-Check: PASSED

---
*Plan: 20-23*
*Completed: 2026-07-18*
