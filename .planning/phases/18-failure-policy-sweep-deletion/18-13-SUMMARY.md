---
phase: 18-failure-policy-sweep-deletion
plan: 13
subsystem: durable-queue
tags: [python, postgres, lease-reaper, state-machine, starvation]

requires:
  - phase: 18-04
    provides: exact final-attempt candidate selection and shared reap-before-empty drain seam
provides:
  - exhaustive run-locked final-lease settlement for every canonical RunStatus
  - active-crash ERROR transitions without overwriting authoritative human-wait or completed states
  - hermetic and guarded-live second-candidate starvation proofs
affects: [18-14, 19-webhook-cutover-durable-ingest, 21-durability-proofs-ops-view]

tech-stack:
  added: []
  patterns:
    - lock transport candidate then associated business row before atomic matrix settlement
    - fail closed at import and in tests when the canonical status vocabulary gains no disposition

key-files:
  created: []
  modified:
    - app/db/repo/job_settlement.py
    - tests/conftest.py
    - tests/test_queue_drain.py
    - tests/test_queue_durability.py

key-decisions:
  - "Final-attempt reaping changes active crash states to ERROR but never overwrites authoritative human-wait, completed, rejected, or existing ERROR state."
  - "A lost active-state CAS after the associated run row is locked is an invariant failure that rolls back, not a successful or fenced no-op."

requirements-completed: [FAIL-02]

coverage:
  - id: D1
    description: "Every canonical RunStatus has exactly one final-lease disposition; all valid branches clear the lease, preserve attempt history, and settle transport DEAD."
    requirement: FAIL-02
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py#test_final_attempt_reap_settles_every_run_status"
        status: pass
      - kind: unit
        ref: "tests/test_queue_drain.py#test_final_attempt_status_matrix_is_disjoint_and_exhaustive"
        status: pass
    human_judgment: false
  - id: D2
    description: "An oldest preserved-state lease settles first and cannot starve the next active-state candidate."
    requirement: FAIL-02
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py#test_final_attempt_preserved_oldest_does_not_starve_next_active_candidate"
        status: pass
    human_judgment: false
  - id: D3
    description: "Real Postgres exercises the status matrix, row-lock ordering, exact predicate, and transaction rollback."
    requirement: FAIL-02
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py#test_final_attempt_reap_status_matrix"
        status: unknown
      - kind: integration
        ref: "tests/test_queue_durability.py#test_final_attempt_reap_preserved_oldest_allows_second_candidate"
        status: unknown
      - kind: integration
        ref: "tests/test_queue_durability.py#test_final_attempt_reap_exact_predicate_and_rollback"
        status: unknown
    human_judgment: true
    rationale: "All 14 selected queueproof cases collected, but the environment lacked DATABASE_URL and ALLOW_DB_RESET=1, so no live Postgres pass is claimed."

duration: 9min
completed: 2026-07-16
status: complete
---

# Phase 18 Plan 13: Starvation-Free Final-Lease Settlement Summary

**Expired final-attempt leases now settle atomically for every business state, preserving authoritative pauses and completions while preventing the oldest row from starving later work.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-16T16:03:00Z
- **Completed:** 2026-07-16T16:11:44Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added disjoint, exhaustive active-error and authoritative-preserve status sets plus an associated-run `FOR UPDATE` lock inside final-attempt settlement.
- Changed every valid-status branch to dead-letter the locked transport row, clear both lease fields, retain `jobs.last_error`, and return `REAPED_FINAL_LEASE`; active crash states receive only the bounded final-expiry diagnostic.
- Added always-run all-status and two-candidate liveness coverage, with a faithful stateful fake and guarded Postgres matrix, ordering, exact-predicate, and rollback proofs.

## Task Commits

1. **Task 1 RED: Exhaustive status-matrix and starvation counterexamples** - `d7ea14f`
2. **Task 1 GREEN: Run-locked matrix and faithful fake** - `ac8f162`
3. **Task 2: Guarded Postgres matrix, ordering, and rollback proofs** - `b5acf5a`

## Files Created/Modified

- `app/db/repo/job_settlement.py` - Locks the associated run and applies the exhaustive active-error/preserve matrix before dead-lettering the transport row.
- `tests/conftest.py` - Mirrors ordering, status treatment, diagnostic preservation, and lease cleanup in the hermetic repository.
- `tests/test_queue_drain.py` - Proves vocabulary exhaustiveness, every status branch, cleanup/history, and second-candidate progress.
- `tests/test_queue_durability.py` - Covers the same matrix, deterministic oldest-first liveness, exact near misses, and rollback against guarded Postgres.

## Decisions Made

- Preserve SENT, AWAITING_REPLY, AWAITING_APPROVAL, NEEDS_OPERATOR, RECONCILED, REJECTED, and ERROR exactly because those states represent completed, human-owned, rejected, or already-terminal business authority even when transport cleanup is still required.
- Treat a failed active-state CAS after `SELECT ... FOR UPDATE` as an invariant violation so the transaction rolls back instead of reporting a false success or recreating a leased strand.

## Deviations from Plan

None - plan executed as specified.

## Issues Encountered

- The first offline `uv run` attempt hit a uv interpreter-cache panic. Re-running through uv with a fresh cache and `--no-sync` used the existing locked environment and completed every requested local check.
- The guarded Postgres suite collected 14 relevant cases but skipped them because `DATABASE_URL` and `ALLOW_DB_RESET=1` were unavailable. This is recorded as unavailable evidence, not a pass.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- CR-01 is closed by always-run behavioral evidence; Plan 18-14 can proceed with reply-ownership and always-run resume-regression gaps.
- Live Postgres verification remains useful when the reset-enabled queueproof environment is available, but no implementation blocker remains.

## Self-Check: PASSED

- RED proof: 13 failed and 4 passed before implementation.
- Focused hermetic final-lease suite: 17 passed.
- Full queue-drain module: 55 passed.
- Pump accounting compatibility: 13 passed.
- Ruff and production mypy: passed.
- Guarded live queueproof: 14 selected and 14 skipped by the two-factor database guard.
- Commits `d7ea14f`, `ac8f162`, and `b5acf5a` exist in history.

---
*Phase: 18-failure-policy-sweep-deletion*
*Completed: 2026-07-16*
