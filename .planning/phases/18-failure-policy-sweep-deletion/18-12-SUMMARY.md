---
phase: 18-failure-policy-sweep-deletion
plan: 12
subsystem: database
tags: [postgres, schema-health, catalog-introspection, operator-resume, tdd]

# Dependency graph
requires:
  - phase: 18-failure-policy-sweep-deletion
    plan: 02
    provides: "Typed operator-resolution tables, jobs.operator_resolution_id, and named persistence relationships"
provides:
  - "Deployment schema health coverage for both typed operator-resolution tables and jobs.operator_resolution_id"
  - "Exact named catalog-shape validation for critical operator-resolution indexes and constraints"
  - "Hermetic anti-vacuity regressions with an explicit nine-query live-schema inventory"
affects: [18-03, 18-06, 18-09, deployment-health, operator-resume]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "catalog shape validation: a required name passes only with the exact owning table, key columns, constraint type, and referenced relationship"
    - "schema-health compatibility: new drift categories extend SchemaDiff with defaults while legacy status, purpose, and unique checks remain unchanged"

key-files:
  created:
    - .planning/phases/18-failure-policy-sweep-deletion/18-12-SUMMARY.md
  modified:
    - app/db/schema_introspect.py
    - tests/test_schema_introspect.py

key-decisions:
  - "Treat a same-named index or constraint with the wrong table, columns, type, or referenced target as missing drift rather than healthy schema."
  - "Keep legacy SchemaDiff positional construction compatible by defaulting the two new required-object drift lists."

patterns-established:
  - "Critical persistence relationships are represented as expected catalog tuples and compared exactly against live pg_catalog rows."
  - "FakeConnection scripts every expected-table query in insertion order before legacy checks and named-object queries."

requirements-completed: [FAIL-02]

coverage:
  - id: D1
    description: "Schema health inventories both typed operator-resolution tables and jobs.operator_resolution_id, failing closed when a table or key column is absent."
    requirement: "FAIL-02"
    verification:
      - kind: unit
        ref: "tests/test_schema_introspect.py#test_diff_missing_operator_resume_table"
        status: pass
      - kind: unit
        ref: "tests/test_schema_introspect.py#test_diff_missing_operator_resolution_key_column"
        status: pass
      - kind: integration
        ref: "uv run --offline pytest -q tests/test_schema_introspect.py tests/test_repo_jobs_sql.py (71 passed)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Schema health verifies exact named index and constraint shapes for operator-resolution lookup, identity, and foreign-key integrity."
    requirement: "FAIL-02"
    verification:
      - kind: unit
        ref: "tests/test_schema_introspect.py#test_diff_missing_or_malformed_required_index"
        status: pass
      - kind: unit
        ref: "tests/test_schema_introspect.py#test_diff_missing_or_malformed_required_constraint"
        status: pass
      - kind: other
        ref: "uv run --offline ruff check app/db/schema_introspect.py tests/test_schema_introspect.py; uv run --offline mypy app/db/schema_introspect.py"
        status: pass
    human_judgment: false

duration: 5min
completed: 2026-07-16
status: complete
---

# Phase 18 Plan 12: Typed Operator-Resolution Schema Health Summary

**Deployment health now fails closed on absent or malformed typed operator-resolution persistence by comparing exact table, column, index, and constraint catalog shapes.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-07-16T00:56:42Z
- **Completed:** 2026-07-16T01:02:19Z
- **Tasks:** 1 TDD task
- **Files modified:** 2

## Accomplishments

- Added `operator_resume_resolutions`, `operator_resume_overrides`, and the ALTER-provided `jobs.operator_resolution_id` to expected/live column drift checks.
- Added exact catalog-shape checks for the parent run lookup index, jobs-to-resolution foreign key, child composite identity, resolution-parent foreign key, and employee-integrity foreign key.
- Expanded the hermetic FakeConnection contract from five to nine explicit queries and proved missing tables, missing key columns, missing objects, malformed objects, legacy drift, and extra-column tolerance.

## Task Commits

Each TDD gate was committed atomically:

1. **Task 1 RED: Typed operator-resolution schema-health regressions** - `8e67459` (test)
2. **Task 1 GREEN: Exact table/index/constraint catalog validation** - `7a796ef` (feat)

## Files Created/Modified

- `app/db/schema_introspect.py` - Parses both typed tables and validates exact required live catalog relationships.
- `tests/test_schema_introspect.py` - Pins expected columns, nine-query ordering, and absent/malformed drift behavior.
- `.planning/phases/18-failure-policy-sweep-deletion/18-12-SUMMARY.md` - Records plan evidence and downstream readiness.

## Decisions Made

- A required index or constraint is healthy only when its exact catalog tuple matches; name-only presence cannot mask a malformed relationship.
- Existing four-argument `SchemaDiff` construction remains valid through defaulted new drift lists, preserving CLI and health-route test seams.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Verification

- `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_schema_introspect.py` — 16 passed.
- `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_schema_introspect.py tests/test_repo_jobs_sql.py` — 71 passed.
- `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_check_schema_cli.py tests/test_health_schema.py` — 5 passed with one existing Starlette deprecation warning.
- `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline ruff check app/db/schema_introspect.py tests/test_schema_introspect.py` — passed.
- `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline mypy app/db/schema_introspect.py` — passed.
- `git diff --check` — passed.

## Next Phase Readiness

- Plans 18-03, 18-06, and 18-09 can now depend on typed operator-resolution persistence without allowing a stale live deployment to report healthy.
- No blockers or unmitigated high-severity threats remain for this plan.

## Self-Check: PASSED

- `app/db/schema_introspect.py` and `tests/test_schema_introspect.py` exist and contain the shipped implementation and regressions.
- RED commit `8e67459` and GREEN commit `7a796ef` exist in git history.
- All task acceptance criteria and plan-level verification commands passed.

---
*Phase: 18-failure-policy-sweep-deletion*
*Completed: 2026-07-16*
