---
phase: 19-webhook-cutover-durable-ingest
plan: 01
subsystem: database
tags: [postgres, durable-ingest, schema-health, writer-fence, tdd]

# Dependency graph
requires:
  - phase: 18-failure-policy-sweep-deletion
    plan: 02
    provides: "Immutable typed operator-resolution generations and identifier-only jobs"
  - phase: 18-failure-policy-sweep-deletion
    plan: 12
    provides: "Exact catalog-shape schema health for operator-resolution persistence"
provides:
  - "Additive durable inbound-event storage with a history-preserving jobs.event_id reference"
  - "Explicit operator-generation authority, supersession, remember intent, and persistent writer fencing"
  - "PII-safe legacy inventory plus fail-closed sole-generation migration and verified reopen controls"
affects: [19-02, 19-03, 19-05, 19-10, durable-webhook-cutover]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "live-safe additive DDL installs fresh and existing-database shapes without reopening a closed deployment fence"
    - "catalog health compares exact column types, index uniqueness/predicates, FK delete action, and trigger shape"
    - "legacy authority migration locks and recounts before any write, never inferring authority from timestamps or IDs"

key-files:
  created:
    - scripts/check_operator_resolution_inventory.py
    - scripts/migrate_operator_resolution_authority.py
    - tests/test_operator_resolution_inventory.py
    - tests/test_operator_resolution_migration.py
  modified:
    - app/db/schema.sql
    - app/db/bootstrap.py
    - app/db/schema_introspect.py
    - tests/test_schema_introspect.py
    - tests/test_job_kind_drift.py

key-decisions:
  - "Initialize the singleton writer fence with INSERT-on-conflict-do-nothing only, so schema reapplication can never reopen a closed cutover boundary."
  - "Classify only an unresolved run's sole legacy generation as authoritative; any multiple-generation history aborts before the first authority write."
  - "Require the reopen command to receive a bounded deployed revision and explicit verification flags, then re-run schema, fence, and authority postflights inside the lock before opening writes."

requirements-completed: [QUEUE-04]

coverage:
  - id: D1
    description: "Fresh and additive schema paths store bounded inbound receipts, jobs.event_id, operator authority/supersession/remember state, and a persistent enabled writer fence."
    requirement: "QUEUE-04"
    verification:
      - kind: unit
        ref: "tests/test_schema_introspect.py"
        status: pass
      - kind: integration
        ref: "tests/test_job_kind_drift.py tests/test_repo_jobs_sql.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "The read-only legacy inventory emits only three aggregate fields and fails closed without revealing identifiers, mappings, or database diagnostics."
    requirement: "QUEUE-04"
    verification:
      - kind: unit
        ref: "tests/test_operator_resolution_inventory.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Deployment controls fence old writers, reject ambiguous history before mutation, migrate sole winners with remember=false, and reopen only after exact postflight checks."
    requirement: "QUEUE-04"
    verification:
      - kind: unit
        ref: "tests/test_operator_resolution_migration.py"
        status: pass
      - kind: other
        ref: "uv run --offline --no-sync mypy app/db/schema_introspect.py scripts/check_operator_resolution_inventory.py scripts/migrate_operator_resolution_authority.py"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 01: Durable Ingest and Authority Cutover Foundation Summary

**Postgres now stores verified inbound receipts before payroll runs exist and provides a fail-closed, PII-safe operator-authority cutover fenced against every legacy writer.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-16T23:15:46Z
- **Completed:** 2026-07-16T23:27:44Z
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments

- Added `inbound_events`, a unique external transport key, retention index, nullable `jobs.event_id`, and an exact named `ON DELETE SET NULL` foreign key in fresh and live-safe schema paths.
- Added explicit authoritative/superseded operator generations, per-override `remember`, one-winner partial uniqueness, and an insert-if-absent singleton writer fence with an enabled fail-closed parent INSERT trigger.
- Added exact catalog health for Phase 19 column types/nullability, index uniqueness/predicates, constraint targets/delete actions, and trigger ownership/function/timing.
- Added a read-only inventory that emits only `unresolved_run_count`, `single_generation_run_count`, and `ambiguous_run_count`, plus a mutating deployment CLI that fences old writers, migrates only sole legacy generations, asserts safe authority state, and reopens only after verified activation.

## Task Commits

Each TDD gate was committed atomically:

1. **Task 1 RED: Receipt, catalog, and inventory contracts** - `a29cb69` (test)
2. **Task 2 GREEN: Additive receipt/authority schema and fail-closed inventory** - `3fbfbb3` (feat)
3. **Task 3 RED: Writer-fence and authority migration controls** - `ea06413` (test)
4. **Task 3 GREEN: Guarded authority migration and verified reopen** - `c57806c` (feat)

## Files Created/Modified

- `app/db/schema.sql` - Durable receipt table, job event reference, operator authority columns, partial winner index, persistent fence, and live-safe additive DDL.
- `app/db/bootstrap.py` - Reverse dependency ordering that drops jobs before inbound events and retains the fence relation safely.
- `app/db/schema_introspect.py` - Exact typed-column, index, constraint, delete-action, and trigger catalog comparisons.
- `scripts/check_operator_resolution_inventory.py` - Read-only aggregate inventory with exact PII-safe output and ambiguity exit contract.
- `scripts/migrate_operator_resolution_authority.py` - Access-exclusive fence close, sole-generation migration, postflight, fence check, and verified reopen modes.
- `tests/test_schema_introspect.py` - Fresh/live shape parity, malformed-object drift, reset order, and fence reapply coverage.
- `tests/test_operator_resolution_inventory.py` - Read-only SQL, exact output, ambiguity, and diagnostic-suppression regressions.
- `tests/test_operator_resolution_migration.py` - Lock ordering, trigger rejection, zero-write ambiguity, winner migration, postflight, and reopen regressions.
- `tests/test_job_kind_drift.py` - Updated durable-ingest job identifier inventory.

## Decisions Made

- The writer fence is a database-enforced deployment boundary, not an application flag. The singleton row is initialized only if absent and the trigger rejects every new parent generation while closed.
- Historical authority is never guessed. Only a cardinality-one unresolved generation is migrated; multiple legacy generations stop the procedure before any authority or remember update.
- Reopening is a distinct command that requires a bounded hexadecimal deployed revision and explicit schema/authority verification inputs, then independently reruns all three postflights under an access-exclusive lock.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated the pre-Phase-19 jobs event-id negative guard**
- **Found during:** Task 2
- **Issue:** `tests/test_job_kind_drift.py` still asserted that `jobs.event_id` must not exist, which directly contradicted the Phase 19 durable receipt requirement and would fail the broader regression suite.
- **Fix:** Replaced the stale absence assertion with a positive durable-ingest identifier requirement.
- **Files modified:** `tests/test_job_kind_drift.py`
- **Verification:** The 121-test plan regression gate passed.
- **Commit:** `3fbfbb3`

---

**Total deviations:** 1 auto-fixed blocking issue.
**Impact on plan:** The adjustment removes a deliberately obsolete guard; it does not widen job kinds, add payload columns, or change payroll business state.

## Issues Encountered

- `DATABASE_URL` was not available, so no live database state, row count, migration, or concurrency pass is claimed. The guarded live deployment checkpoint remains owned by Plan 19-10.

## User Setup Required

None - this plan adds deployment commands but does not run them against a live database.

## Verification

- `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_schema_introspect.py tests/test_operator_resolution_inventory.py tests/test_operator_resolution_migration.py tests/test_bootstrap_safe_url.py tests/test_repo_jobs_sql.py tests/test_job_kind_drift.py` - 121 passed.
- `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync ruff check ...` across all changed Python source/tests - passed.
- `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync mypy app/db/schema_introspect.py scripts/check_operator_resolution_inventory.py scripts/migrate_operator_resolution_authority.py` - passed.
- `git diff --check` - passed.

## Next Phase Readiness

- Plan 19-02 can widen the job/event model and repository contract against the additive schema now pinned here.
- Plan 19-10 retains the guarded live fence, inventory, migration, schema postflight, verified-code activation, and reopen sequence.
- No code blocker remains; live-data authority remains intentionally unknown until the guarded checkpoint runs.

---
*Phase: 19-webhook-cutover-durable-ingest*
*Completed: 2026-07-16*

## Self-Check: PASSED

The summary, both deployment scripts, and all four task commits exist; the 121-test plan regression, Ruff, mypy, and `git diff --check` gates are green. No tracked file was deleted, no untracked runtime artifact remains, and no live-database result is claimed.
