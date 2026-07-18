---
phase: 20-exactly-once-send
plan: 21
subsystem: database/queue
tags: [postgres, provider-handoff, lease-fencing, immutable-snapshots, exactly-once]

# Dependency graph
requires:
  - phase: 20-exactly-once-send
    provides: confirmation-only review ownership and exact SEND_OUTBOUND lease outcomes
provides:
  - PII-safe active provider-handoff storage with one active authorization per run
  - locked, typed authority for frozen outbound snapshots and immutable reservation deadlines
  - retrigger fence that rejects reply-epoch advancement during an active provider handoff
affects: [outbound delivery, send retry, delivery review, phase-20-22, phase-21 durability proofs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - short provider authority transactions lock job -> snapshot/email -> run -> handoff
    - reservation time, not retry scheduling time, is the source of every replay deadline

key-files:
  created:
    - app/db/repo/outbound_handoffs.py
  modified:
    - app/db/schema.sql
    - app/db/repo/__init__.py
    - app/db/repo/pipeline_state.py
    - tests/test_send_idempotency.py

key-decisions:
  - "Handoff rows carry only identities, lease ownership, timestamps, and fixed release reasons; snapshots and attempt ledgers retain all content and delivery history."
  - "A matching expired predecessor may transfer ownership without changing its handoff id, frozen snapshot, authorization time, or not_after deadline."
  - "Retriggers lock the run then inspect only the handoff fence, preserving the worker's deadlock-free job -> snapshot/email -> run -> handoff order."

patterns-established:
  - "Typed record-only and active outcomes are no-provider results and cannot be mistaken for frozen-snapshot authority."
  - "Every release/finalization predicates on handoff identity, all delivery identities, epoch, and the current lease token."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "Schema installs an identifier-only handoff record with one unreleased authorization per run and a bounded release vocabulary."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: "tests/test_send_idempotency.py#test_provider_handoff_schema_is_identifier_only_and_has_one_active_run_fence"
        status: pass
    human_judgment: false
  - id: D2
    description: "Provider authority locks the exact leased job, immutable snapshot, current run generation, and handoff in order; a record-only run receives no provider authority."
    requirement: SEND-02
    verification:
      - kind: unit
        ref: "tests/test_send_idempotency.py#test_provider_handoff_authorization_locks_exact_authority_order"
        status: pass
      - kind: unit
        ref: "tests/test_send_idempotency.py#test_provider_handoff_record_only_is_distinct_and_creates_no_fence"
        status: pass
    human_judgment: false
  - id: D3
    description: "Exact-owner release and an active-handoff query fence stale owners and block a reply-epoch advance before mutation."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: "tests/test_send_idempotency.py#test_provider_handoff_release_is_exact_owner_and_active_fence_is_queryable"
        status: pass
      - kind: unit
        ref: "tests/test_send_idempotency.py#test_clear_reply_context_checks_active_provider_handoff_before_epoch_bump"
        status: pass
    human_judgment: false

# Metrics
duration: ~25min
completed: 2026-07-18
status: complete
---

# Phase 20 Plan 21: Provider Handoff Fence Summary

**SEND_OUTBOUND workers now receive provider authority only through an exact, durable handoff over a frozen snapshot, while retriggers cannot advance the conversation epoch past an active handoff.**

## Accomplishments

- Added `outbound_provider_handoffs`, its one-active-run partial unique index, foreign-key identity, bounded release reasons, and an explicit no-payload boundary.
- Added typed authorization, record-only, and active outcomes; authorization locks job, immutable snapshot/email, run, then handoff and derives `not_after` from the locked reservation timestamp.
- Added exact-token adoption/finalization/retry-release/review-release seams and made `clear_reply_context` reject an active handoff before incrementing `reply_epoch`.

## Task Commits

1. **Task 1: Add idempotent active provider-handoff storage and its safety contract** — `f5de8e7` (feat)
2. **Task 2: Define the locked provider-handoff repository protocol** — `51aba7d` (feat)

## Files Created/Modified

- `app/db/schema.sql` — durable handoff table and active-run uniqueness fence.
- `app/db/repo/outbound_handoffs.py` — typed authorization, adoption, exact release, and active-fence contract.
- `app/db/repo/pipeline_state.py` — run-lock-first handoff assertion before a reply-epoch bump.
- `app/db/repo/__init__.py` — public repository facade exports.
- `tests/test_send_idempotency.py` — schema, lock-order, record-only, exact-release, and fence regressions.

## Decisions Made

- The handoff deadline is selected as `reserved_at + interval '20 hours'` from the locked snapshot and is never recalculated from a retry, adoption, or process clock.
- An expired matching predecessor can be adopted only by the exact currently leased job; adoption changes lease ownership only.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Fenced epoch clearing in `clear_reply_context`.**

- **Found during:** Task 2
- **Issue:** A durable handoff alone could not prevent a retrigger from advancing `reply_epoch` between authorization and the provider request.
- **Fix:** Locked the run, queried the active handoff in the same transaction, and raised a typed bounded exception before the epoch update.
- **Files modified:** `app/db/repo/pipeline_state.py`, `tests/test_send_idempotency.py`
- **Verification:** focused handoff fence regression, focused pytest suite, Ruff, and mypy passed.
- **Committed in:** `51aba7d`

**Total deviations:** 1 auto-fixed (Rule 2 correctness/security).
**Impact on plan:** Required by the plan's active-fence truth; no scope expansion beyond the specified retrigger integration seam.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 20-22 can wire the SEND_OUTBOUND consumer to `authorize_outbound_provider_handoff` and use the typed no-provider outcomes without rebuilding a provider payload. Retry/settlement consumers can use the exact-owner release seams in their shared transaction.

## Verification

- `uv run pytest -q tests/test_send_idempotency.py tests/test_repo_jobs_sql.py` — **111 passed, 3 skipped**.
- `uv run ruff check app/db/repo/outbound_handoffs.py app/db/repo/pipeline_state.py app/db/repo/__init__.py tests/test_send_idempotency.py` — **passed**.
- `uv run mypy` — **passed: 161 source files**.

## Self-Check: PASSED

---
*Plan: 20-21*
*Completed: 2026-07-18*
