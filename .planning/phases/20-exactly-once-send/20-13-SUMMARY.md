---
phase: 20-exactly-once-send
plan: 13
subsystem: database
tags: [postgres, durable-queue, exactly-once, idempotency, delivery-review]

# Dependency graph
requires:
  - phase: 20-09
    provides: lease-fenced outbound delivery settlement and immutable reservation
  - phase: 20-11
    provides: bounded delivery review and retry-now repository seam
  - phase: 20-12
    provides: executable send consumer and snapshot-backed delivery flow
provides:
  - persisted-email identity fencing before outbound settlement writes
  - strict four-reason automatic delivery replay allowlist
  - purpose-aware final SEND_OUTBOUND lease review with bounded attempt evidence
  - job-first lock ordering and same-row clarification delivery retry operation
affects: [phase-20, phase-21, send-delivery, queue-operations]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - job-first row locking for operator retry and delivery settlement
    - reservation-time replay classification with fail-closed operator review

key-files:
  created:
    - .planning/phases/20-exactly-once-send/20-13-SUMMARY.md
  modified:
    - app/db/repo/job_settlement.py
    - app/db/repo/jobs.py
    - app/db/repo/__init__.py
    - app/db/schema.sql
    - tests/test_send_idempotency.py
    - tests/test_queue_durability.py

key-decisions:
  - "Persisted jobs.email_id is a required logical identity fence; an absent or mismatched identity returns FENCED before reservation or attempt SQL."
  - "Only delivery timeout, connection failure, rate limit, and provider 5xx results may be automatically replayed inside the locked reservation-time window."
  - "Final SEND_OUTBOUND lease expiry preserves the frozen reservation and records final_attempt_lease_expired before entering purpose-specific operator review."

patterns-established:
  - "Both retry-now and settlement lock the durable job before the owned immutable snapshot."
  - "Clarification delivery review retry advances the existing pending job and never creates a send slot or provider call."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "Outbound settlement fences persisted email identity and rejects unsafe retryable delivery reasons."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: "uv run pytest -q tests/test_send_idempotency.py tests/test_queue_durability.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Final confirmation and clarification lease expiry preserves the frozen snapshot and enters bounded purpose-specific delivery review."
    requirement: SEND-02
    verification:
      - kind: unit
        ref: "tests/test_send_idempotency.py::test_delivery_settlement_fences_a_claimed_email_id_against_the_persisted_job"
        status: pass
      - kind: integration
        ref: "uv run pytest -q -m 'integration and queueproof' tests/test_send_idempotency.py tests/test_queue_durability.py"
        status: unknown
    human_judgment: true
    rationale: "The real-Postgres queueproof is guarded by DATABASE_URL and ALLOW_DB_RESET=1, which were unavailable locally."
  - id: D3
    description: "Operator retry-now and clarification delivery-review retry share job-first locking and reuse the existing durable row."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: "tests/test_send_idempotency.py::test_clarification_delivery_review_retry_reopens_the_same_row"
        status: pass
      - kind: other
        ref: "uv run mypy app/db/repo/job_settlement.py app/db/repo/jobs.py && uv run ruff check app/db/repo/job_settlement.py app/db/repo/jobs.py tests/test_send_idempotency.py tests/test_queue_durability.py"
        status: pass
    human_judgment: false

# Metrics
duration: 10min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 13: Settlement Gap Closure Summary

**Lease-fenced, purpose-aware outbound settlement with a strict replay allowlist and same-row clarification retry.**

## Performance

- **Duration:** approximately 10 minutes
- **Started:** 2026-07-17T22:44:27Z
- **Completed:** 2026-07-17T22:53:04Z
- **Tasks:** 2
- **Files modified:** 6 code/test files plus this summary

## Accomplishments

- Settlement now compares the claimed `Job.email_id` with the persisted leased job identity before touching the reservation, attempt ledger, email row, run, or job state.
- Automatic replay is limited to timeout, connection failure, eligible rate-limit, and provider-5xx reasons; all other retryable results enter bounded delivery review.
- Final confirmation, clarification, and clarification-field-regression lease expiry preserve the original reservation and Message-ID, append `final_attempt_lease_expired`, and persist `needs_operator` with the matching review reason.
- Retry-now uses job-first locking, and clarification delivery review can reopen only the existing pending SEND_OUTBOUND row while preserving the frozen snapshot.

## Task Commits

1. **Task 1: Fence logical email identity and make replay/final-lease settlement purpose-aware** - `b688df2` (`fix`)
2. **Task 2: Unify lock ordering and expose same-row clarification retry for explicit review** - `633601e` (`feat`)

TDD regression tests were introduced in `e8470de` before the implementation commits.

## Files Created/Modified

- `app/db/repo/job_settlement.py` - persisted email fence, replay allowlist, and purpose-aware final lease reaper.
- `app/db/repo/jobs.py` - common job-first retry ordering and clarification review retry operation.
- `app/db/repo/__init__.py` - facade export for the new clarification retry operation.
- `app/db/schema.sql` - append-only attempt category and idempotent live migration for final lease evidence.
- `tests/test_send_idempotency.py` - hermetic fencing, category, lock-order, and same-row retry proofs.
- `tests/test_queue_durability.py` - guarded live final-lease preservation proofs for all outbound purposes.

## Decisions Made

- The persisted database identity, not the caller’s claimed object, is authoritative for outbound settlement.
- Automatic delivery replay remains an explicit allowlist rather than inheriting generic `PipelineOutcome.RETRYABLE` semantics.
- Final lease expiry is an operator-review fact, not generic pipeline recovery; the original reservation remains untouched.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] Added the final-lease attempt category to the schema.**

- **Found during:** Task 1
- **Issue:** The plan required persisting `final_attempt_lease_expired`, but the deployed `failure_category` CHECK constraint accepted only provider and transport categories.
- **Fix:** Added the bounded category to the fresh-table CHECK and an idempotent column-anchored migration for existing databases.
- **Files modified:** `app/db/schema.sql`, `tests/test_send_idempotency.py`
- **Verification:** Focused suite and schema-shape assertion pass.
- **Committed in:** `b688df2`

**Total deviations:** 1 Rule 2 auto-fix.

**Impact on plan:** Required for the requested append-only evidence to be writable in both fresh and already-bootstrapped databases; no architectural scope expansion.

## Issues Encountered

- `tests/test_clarify.py` and two tests in `tests/test_repo_jobs_sql.py` still script the pre-20-13 four-column fake row and reservation-first SQL order. They are outside this plan’s owned file list and were not changed; the plan-scoped suite is green.

## Unavailable Evidence

- `uv run pytest -q -m 'integration and queueproof' tests/test_send_idempotency.py tests/test_queue_durability.py` collected 48 guarded tests and skipped all 48 because `DATABASE_URL` and `ALLOW_DB_RESET=1` were not present. This is unavailable real-Postgres evidence, not a pass.

## User Setup Required

None.

## Next Phase Readiness

The settlement and retry seams are ready for Plan 20-16’s loadability and resolve/retrigger guard proofs. The real-Postgres concurrency and final-lease proofs should be rerun in an environment with the two-factor database configuration.

---
*Phase: 20-Exactly-Once Send*
*Plan: 20-13*
*Completed: 2026-07-17*

## Self-Check: PASSED

- Summary file exists at the expected phase path.
- Task commits `e8470de`, `b688df2`, and `633601e` are present in git history.
- No unplanned threat surface or blocking stub was introduced by this plan.

## Correction Note

2026-07-17: Wave 8’s ten blocking failures were corrected by updating stale fake
cursor rows to the exact Plan 20-13 SQL projection shapes; production settlement,
persisted-email fencing, and final-lease logic were unchanged.
