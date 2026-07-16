---
phase: 18-failure-policy-sweep-deletion
plan: 02
subsystem: database
tags: [postgres, durable-queue, typed-identifiers, immutable-generations, tdd]

# Dependency graph
requires:
  - phase: 16-queue-substrate-unblocked-webhook
    provides: "Identifier-only jobs table and leased Job claim contract"
  - phase: 18-failure-policy-sweep-deletion
    plan: 01
    provides: "Bounded pipeline stage and reason vocabulary for safe retry diagnostics"
provides:
  - "Eight-field identifier-only Job claims with bounded delayed enqueue inputs"
  - "Normalized immutable operator resolution generations with complete typed override rows"
  - "Strict inbound-email and operator-resolution repository reads with in-memory parity"
affects: [18-03, 18-09, 18-12, durable-retry, operator-resume]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "identifier-only transport: jobs refer to persisted context by UUID and never carry business payloads"
    - "immutable generation store: exact duplicate UUID writes are idempotent while conflicting reuse fails closed"
    - "live-safe DDL: nullable columns and named foreign keys install idempotently after dependent tables exist"

key-files:
  created:
    - app/db/repo/operator_resume_resolutions.py
  modified:
    - app/models/job.py
    - app/db/schema.sql
    - app/db/repo/jobs.py
    - app/db/repo/emails.py
    - app/db/repo/__init__.py
    - tests/conftest.py
    - tests/test_repo_jobs_sql.py

key-decisions:
  - "Future resume kinds are validated through bounded kind.value branches without widening JobKind or the SQL kind CHECK before their handlers land in Plan 18-09."
  - "A caller-generated operator_resolution_id scopes one immutable parent and its complete typed submitted_name-to-employee_id rows independently of reply_epoch."
  - "New nullable Job identifiers default to None on keyword construction while claim SQL still populates all eight fields explicitly and in exact order."

patterns-established:
  - "Persist retry context in domain tables first, then put only its UUID on jobs."
  - "Validate the complete mapping before SQL; compare existing rows exactly on idempotent replay; reject missing, cross-run, duplicate, or malformed rows on load."

requirements-completed: [FAIL-01, FAIL-02]

coverage:
  - id: D1
    description: "Job claims and enqueue operations carry only run, email, and operator-resolution identifiers, with parameterized bounded delay and diagnostic inputs."
    requirement: "FAIL-01"
    verification:
      - kind: unit
        ref: "tests/test_repo_jobs_sql.py#test_claim_returning_maps_bijectively_onto_the_job_dataclass"
        status: pass
      - kind: unit
        ref: "tests/test_repo_jobs_sql.py -k 'claim_projection or enqueue'"
        status: pass
    human_judgment: false
  - id: D2
    description: "Postgres represents every operator resolution as an immutable UUID parent plus complete typed submitted-name and employee child rows without JSON or reply-epoch authority."
    requirement: "FAIL-02"
    verification:
      - kind: unit
        ref: "tests/test_repo_jobs_sql.py -k 'operator_resume_schema'"
        status: pass
      - kind: integration
        ref: "tests/test_job_kind_drift.py tests/test_schema_introspect.py tests/test_status_drift.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Strict repository and in-memory primitives reload persisted reply context and exact operator mappings, accepting only identical duplicate generations."
    requirement: "FAIL-02"
    verification:
      - kind: unit
        ref: "tests/test_repo_jobs_sql.py -k 'inbound_email_by_id or operator_resume_resolution'"
        status: pass
      - kind: integration
        ref: "tests/test_fake_repo_pairing.py"
        status: pass
      - kind: other
        ref: "uv run --offline pytest -q (804 passed, 71 skipped)"
        status: pass
    human_judgment: false

duration: 15min
completed: 2026-07-16
status: complete
---

# Phase 18 Plan 02: Durable Resume Context Foundation Summary

**Identifier-only queue claims now point to persisted inbound emails and immutable typed operator-resolution generations, with bounded retry scheduling inputs and strict repository reconstruction.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-07-16T00:36:11Z
- **Completed:** 2026-07-16T00:51:10Z
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments

- Widened the frozen `Job` claim contract to the exact eight-column identifier projection and added bounded, parameterized enqueue delay and diagnostic inputs without adding a generic payload or business next-state field.
- Added history-preserving `operator_resume_resolutions` and `operator_resume_overrides` tables, a nullable jobs foreign key, an indexed run lookup, and reset-safe dependency ordering while keeping `jobs.kind` at `run_pipeline` only.
- Added exact inbound-email lookup plus atomic create/load primitives for complete operator mappings, including invalid-input rejection, exact replay idempotency, conflicting UUID rejection, corrupt-row detection, facade exports, and stateful in-memory parity.

## Task Commits

Each TDD task was committed atomically:

1. **Task 1 RED: Durable retry claim contract** - `8cb1d8b` (test)
2. **Task 1 GREEN: Identifier-aware Job claim and bounded enqueue inputs** - `2c2fcd1` (feat)
3. **Task 2 RED: Normalized operator-resolution schema contracts** - `d468997` (test)
4. **Task 2 GREEN: Immutable parent/child schema and live migration** - `3cc285a` (feat)
5. **Task 3 RED: Strict persisted-context repository contracts** - `d58802d` (test)
6. **Task 3 GREEN: Exact context repositories and in-memory parity** - `4d2f459` (feat)
7. **Full-suite compatibility: Nullable Job construction and index drift guard** - `727b6c7` (fix)

**Plan metadata:** committed as part of this SUMMARY's closeout commit.

## Files Created/Modified

- `app/db/repo/operator_resume_resolutions.py` - Validated atomic creation, exact replay handling, and strict scoped reconstruction of immutable operator mappings.
- `app/models/job.py` - Eight-field keyword-only identifier claim record with nullable persisted-context identifiers.
- `app/db/repo/jobs.py` - Kind-specific identifier validation, bounded delay/diagnostic validation, parameterized enqueue, and exact claim mapping.
- `app/db/schema.sql` - Normalized resolution tables, run index, nullable jobs identifier, and named history-preserving foreign key.
- `app/db/bootstrap.py` - Reverse-dependency reset ordering for both new tables.
- `app/db/repo/emails.py` - Explicit inbound row lookup by exact email UUID.
- `app/db/repo/__init__.py` - Public facade exports for all three context primitives.
- `tests/conftest.py` - Stateful operator-generation store, exact email-id lookup, and eight-field Job fake parity.
- `tests/test_repo_jobs_sql.py` - RED/GREEN SQL shape, validation, idempotency, corruption, and pairing proofs.
- `tests/test_status_drift.py` - Exact schema-index inventory widened for the operator-resolution run index.

## Decisions Made

- Deferred the actual `resume_reply` and `operator_resume` enum/SQL/dispatch widening to Plan 18-09; this wave validates their identifier contracts by bounded string value so the current one-kind equality guard remains green.
- Made resolution UUID—not reply epoch—the immutable generation identity. Multiple valid same-epoch submissions can coexist, while replaying one committed generation is idempotent only when the complete mapping matches exactly.
- Kept nullable context fields convenient for existing keyword-only test and handler construction through `None` defaults, while preserving ordered claim projection as the database-to-dataclass authority.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected the RED parameter-membership assertion**
- **Found during:** Task 1 GREEN
- **Issue:** One RED assertion checked whether an operator-resolution UUID was a dictionary key even though the same test contract required named parameters.
- **Fix:** Checked `params.values()` so the assertion proves parameterization without contradicting the named-parameter contract.
- **Files modified:** `tests/test_repo_jobs_sql.py`
- **Verification:** 36 focused repository tests passed.
- **Committed in:** `2c2fcd1`

**2. [Rule 2 - Missing Critical] Added reset ordering for the new relational tables**
- **Found during:** Task 2 GREEN
- **Issue:** Leaving the new tables out of `_DROP_ORDER` would let `--reset` drop referenced tables and foreign keys while retaining stale operator-resolution tables.
- **Fix:** Added child-before-parent entries around jobs and payroll runs in the existing reverse-dependency reset list.
- **Files modified:** `app/db/bootstrap.py`
- **Verification:** Schema/drift suite passed; the full offline suite passed.
- **Committed in:** `3cc285a`

**3. [Rule 3 - Blocking] Preserved Job fixture compatibility and global index inventory**
- **Found during:** Plan-wide full-suite verification
- **Issue:** Existing keyword `Job(...)` fixtures omitted the new nullable identifiers, and the exact global index guard rejected the required run index.
- **Fix:** Made `Job` keyword-only with nullable identifier defaults and registered the new index in the static inventory.
- **Files modified:** `app/models/job.py`, `tests/test_status_drift.py`
- **Verification:** 104 directly affected tests passed, followed by 804 passed and 71 skipped in the full suite.
- **Committed in:** `727b6c7`

---

**Total deviations:** 3 auto-fixed (1 bug, 1 missing critical, 1 blocking).
**Impact on plan:** All fixes preserve the planned identifier-only and immutable-generation design; no dependency, route, handler, producer cutover, payload, or environment setting was added.

## Issues Encountered

- `rg` was unavailable in this environment, so repository searches used `grep` as the documented fallback.
- The full suite emitted one existing Starlette `httpx` deprecation warning; it does not affect Phase 18 behavior.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 18-03 can persist the validated `/resolve` mapping and schedule only `(run_id, operator_resolution_id)` after the transaction commits.
- Plan 18-09 can atomically add `resume_reply` and `operator_resume` kinds, handlers, and dispatch using the already-green identifiers and context repositories.
- Plan 18-12 still owns live schema-introspection coverage for the new tables and column.
- No blockers.

---
*Phase: 18-failure-policy-sweep-deletion*
*Completed: 2026-07-16*

## Self-Check: PASSED

All ten changed files exist; all seven Plan 18-02 task/fix commits are present; the 77-test plan gate, Ruff, mypy, fake-repository pairing, and the full offline suite (804 passed, 71 skipped) are green; no tracked file was deleted and no untracked artifact remains.
