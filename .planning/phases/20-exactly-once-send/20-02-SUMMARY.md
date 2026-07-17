---
phase: 20-exactly-once-send
plan: "02"
subsystem: database
tags: [postgres, durable-queue, outbound-email, idempotency, tdd]

# Dependency graph
requires:
  - phase: 20-exactly-once-send
    provides: "immutable outbound email snapshots and reservation timestamps"
provides:
  - "Identifier-only outbound-send queue vocabulary with exact SQL and Python context checks"
  - "One existing-job-only retry-now operation gated by the database reservation cutoff"
  - "In-memory queue parity and a fail-closed pre-handler dispatch guard"
affects: [20-03, durable-send-handler, delivery-review, queue-settlement]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Outbound work is keyed only by a persisted run and frozen email identifier"
    - "Retry-now locks the snapshot and job, advances only pending work, and lets the route wake only after commit"
    - "A staged queue kind is explicitly fail-closed until an executable handler is registered"

key-files:
  created: []
  modified:
    - app/models/job.py
    - app/db/schema.sql
    - app/db/repo/jobs.py
    - app/db/repo/__init__.py
    - tests/conftest.py
    - tests/test_job_kind_drift.py
    - tests/test_repo_jobs_sql.py

key-decisions:
  - "The frozen email UUID determines both the dedup key and the exact send-job context."
  - "Send jobs use eight attempts, matching the reservation-time retry ladder instead of the generic short queue cap."
  - "The temporary absence of a handler is tested as a fail-closed dispatch error; no producer can enqueue the staged kind yet."

patterns-established:
  - "Existing-job-only acceleration: caller transaction -> lock reservation cutoff -> lock one pending job -> set due now -> wake after commit"
  - "Temporary dispatch staging: validate enum and SQL first, then make the missing handler observable and non-silent"

requirements-completed: [SEND-01, SEND-03]

coverage:
  - id: D1
    description: "The durable queue accepts an outbound send only with a run UUID, frozen email UUID, and snapshot-derived dedup key."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: tests/test_repo_jobs_sql.py#test_enqueue_send_outbound_requires_its_immutable_slot_identifiers
        status: pass
      - kind: unit
        ref: tests/test_job_kind_drift.py#test_send_outbound_sql_requires_exact_identifier_context
        status: pass
    human_judgment: false
  - id: D2
    description: "An operator retry advances only one existing, pending, unexpired send job and cannot synchronously send or insert another job."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: tests/test_repo_jobs_sql.py#test_advance_existing_send_job_due_now_locks_then_updates_only_pending_work
        status: pass
      - kind: unit
        ref: tests/test_repo_jobs_sql.py#test_fake_retry_now_advances_only_the_one_eligible_send_job
        status: pass
    human_judgment: false
  - id: D3
    description: "The staged send kind fails closed through dispatch until the fenced handler is available."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: tests/test_job_kind_drift.py#TestDispatchTableMatchesJobKind.test_unregistered_send_outbound_dispatch_fails_closed
        status: pass
    human_judgment: false

duration: 13min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 02: Identifier-Only Send Queue Summary

**Outbound delivery now has one immutable queue identity and a transaction-bound retry-now path that cannot create a second send job or invoke a provider.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-07-17T18:27:00Z
- **Completed:** 2026-07-17T18:40:44Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Added `SEND_OUTBOUND` to the job model, initial DDL, deployed-schema repair, and exact identifier validation.
- Added a snapshot-derived dedup key, an eight-attempt send policy, and an existing-pending-job-only retry-now repository operation.
- Mirrored retry-now behavior in the fake repository and proved that an unregistered send handler refuses work rather than silently completing it.

## Task Commits

Each task was committed atomically:

1. **Task 1: Define the exact send-outbound job context and SQL mirror** - `0c789d7` (feat)
2. **Task 2: Preserve fake queue parity while withholding dispatch until settlement exists** - `fbe2956` (test)

## Files Created/Modified

- `app/models/job.py` - Adds the outbound-send transport kind.
- `app/db/schema.sql` - Mirrors the kind and its exact identifier context in initial and deployed-schema constraints.
- `app/db/repo/jobs.py` - Defines dedup identity, send-specific attempt count, and locked retry-now advancement.
- `app/db/repo/__init__.py` - Exposes the new repository operations.
- `tests/conftest.py` - Mirrors the retry-now behavior in the in-memory repository.
- `tests/test_repo_jobs_sql.py` - Proves identifier-only queue context, locking, cutoff, and fake behavior.
- `tests/test_job_kind_drift.py` - Pins the SQL context and fail-closed pre-handler state.

## Decisions Made

- The frozen email ID, rather than caller content, is the only durable send-slot identity.
- Retry-now requires a caller-owned transaction and returns a bounded outcome so routes can wake workers only after commit.
- The send kind intentionally has no dispatch registration yet; the dispatcher raises a bounded error instead of treating it as completed work.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Corrected stale queue-vocabulary comments during staged handler wiring**
- **Found during:** Task 2
- **Issue:** Existing comments asserted immediate enum-to-handler equality, while the required staged send kind must deliberately fail closed before its handler exists.
- **Fix:** Reworded the comments to describe the guarded staged state without changing dispatch behavior.
- **Files modified:** `app/models/job.py`, `app/db/schema.sql`
- **Verification:** Focused queue tests, provenance guard, and lint passed.
- **Committed in:** `42895ab`

**Total deviations:** 1 auto-fixed (1 Rule 3 blocking documentation correction). **Impact:** Clarifies the intended fail-closed boundary; no runtime behavior changed.

## Issues Encountered

- The sandbox initially prevented `uv` from reading its existing shared cache; the required checks completed after scoped approval.
- A final Ruff invocation accidentally included the SQL schema, which Ruff parses as Python. The supported Python-only lint command passed after excluding the SQL file.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The next handler/settlement work can consume one durable `SEND_OUTBOUND` job using only the persisted run and frozen email IDs.
- No application producer or provider call has changed; dispatch registration remains deliberately deferred until the fenced handler exists.

## Verification

- `uv run pytest tests/test_repo_jobs_sql.py tests/test_job_kind_drift.py -q` — 94 passed.
- `uv run mypy app/models/job.py app/db/repo/jobs.py` — passed.
- `uv run pytest tests/test_fake_repo_pairing.py -q` — 10 passed, 1 pre-existing Starlette/httpx deprecation warning.
- `uv run pytest tests/test_comment_provenance_guard.py -q` — 5 passed.
- `uv run ruff check app/models/job.py app/db/repo/jobs.py app/db/repo/__init__.py tests/conftest.py tests/test_repo_jobs_sql.py tests/test_job_kind_drift.py` — passed.
- `git diff --check` — passed.

## Self-Check: PASSED

- The summary and all seven planned implementation/test files exist.
- Task commits `0c789d7` and `fbe2956` are present in history.
- Focused queue, fake-pairing, provenance, type, lint, and diff checks passed.

---
*Phase: 20-exactly-once-send*
*Completed: 2026-07-17*
