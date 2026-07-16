---
phase: 18-failure-policy-sweep-deletion
plan: 03
subsystem: durable-execution
tags: [postgres, queue, retries, background-tasks, operator-resume]

requires:
  - phase: 18-01
    provides: bounded PipelineResult classification and the temporary None-to-OK adapter
  - phase: 18-02
    provides: typed immutable operator-resolution persistence
  - phase: 18-09
    provides: RUN_PIPELINE, RESUME_REPLY, and OPERATOR_RESUME queue kinds and handlers
  - phase: 18-12
    provides: queue schema and drift contracts consumed by settlement
provides:
  - fenced atomic job/run settlement for retry, terminal, exhaustion, and final-lease recovery
  - durable first-attempt retry bridges for initial, reply, and operator BackgroundTasks
  - atomic complete operator-resolution persistence with identifier-only post-commit dispatch
affects: [18-04, 18-10, 18-11, 19-webhook-cutover-durable-ingest]

tech-stack:
  added: []
  patterns:
    - one repository coordinator transaction owns every cross-aggregate job/run settlement
    - background consumers normalize producer results once and wake only after durable commit
    - operator authority is an immutable UUID-scoped mapping, never alias_candidates or job payload

key-files:
  created:
    - app/db/repo/job_settlement.py
  modified:
    - app/db/repo/__init__.py
    - app/queue/drain.py
    - app/routes/pipeline_glue.py
    - app/routes/runs.py
    - tests/conftest.py
    - tests/test_needs_operator.py
    - tests/test_queue_drain.py
    - tests/test_queue_durability.py

key-decisions:
  - "A single fenced repository coordinator owns cross-aggregate queue/run settlement; retry diagnostics stay on jobs until terminal or exhaustion."
  - "Every valid operator resolution is a fresh immutable UUID generation containing the complete mapping; remember choices affect only optional alias learning."
  - "Invalid operator context is settled from needs_operator with the same bounded terminal coordinator instead of a raw exception or mapping-bearing fallback."

patterns-established:
  - "Post-commit wake: durable state commits before any worker wake or BackgroundTask dispatch."
  - "Identifier-only operator replay: process-local and queued consumers carry run_id plus operator_resolution_id only."

requirements-completed: [FAIL-02]

coverage:
  - id: D1
    description: "Fenced atomic job/run settlement covers retry, exhaustion, terminal, infrastructure, and final-attempt lease outcomes."
    requirement: FAIL-02
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py#settlement and final_attempt focused suite"
        status: pass
      - kind: integration
        ref: "tests/test_queue_durability.py -m queueproof -k settlement/operator_resume"
        status: unknown
    human_judgment: true
    rationale: "Hermetic settlement proofs pass, but live Postgres queueproof tests were skipped because DATABASE_URL and ALLOW_DB_RESET were unavailable."
  - id: D2
    description: "Initial and persisted-reply BackgroundTasks preserve retryable results as reconstructable durable work and wake only after commit."
    requirement: FAIL-02
    verification:
      - kind: integration
        ref: "tests/test_queue_drain.py#background and resume focused suite"
        status: pass
    human_judgment: false
  - id: D3
    description: "Valid operator POSTs atomically persist complete UUID-scoped authority before identifier-only dispatch, including mixed remember choices."
    requirement: FAIL-02
    verification:
      - kind: e2e
        ref: "tests/test_needs_operator.py#resolve and operator_resume focused suite"
        status: pass
      - kind: integration
        ref: "tests/test_queue_durability.py -m queueproof -k operator_resume"
        status: unknown
    human_judgment: true
    rationale: "Route and hermetic retry proofs pass; live Postgres rollback and dedup proofs were collected but skipped without the guarded database environment."

duration: 25min
completed: 2026-07-16
status: complete
---

# Phase 18 Plan 03: Atomic Failure Policy and Durable Background Bridges Summary

**Fenced queue/run settlement now preserves retryable initial, reply, and operator work durably, with complete UUID-scoped operator authority committed before identifier-only dispatch.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-16T01:29:56Z
- **Completed:** 2026-07-16T01:55:16Z
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments

- Added the sole cross-aggregate settlement coordinator for leased-job success, retry, terminal failure, exhaustion, infrastructure failure, and expired final-attempt leases.
- Bridged initial and persisted-reply BackgroundTask results into durable delayed jobs without local loops, recursive scheduling, or context loss.
- Replaced raw operator mappings in BackgroundTask arguments with atomically persisted complete resolution generations and identifier-only replay/retry.

## Task Commits

Each task was committed atomically:

1. **Task 1: Fenced atomic settlement and operator retry persistence** - `bea2448` (RED), `879047f` (GREEN)
2. **Task 2: Initial and persisted-reply background retry bridges** - `29d97f3` (RED), `9121382` (GREEN)
3. **Task 3: Atomic operator-resolution handoff and identifier-only retries** - `9d60a0d` (RED), `91f7fb6` (GREEN)

**Verification gate fix:** `8dc32e8` (public backoff seam and provenance-clean test comments)

## Files Created/Modified

- `app/db/repo/job_settlement.py` - Atomic fenced settlement and classified retry coordinator.
- `app/db/repo/__init__.py` - Public coordinator exports.
- `app/queue/drain.py` - Public backoff helper shared across queue and background consumers.
- `app/routes/pipeline_glue.py` - Result-aware initial, reply, and operator background bridges.
- `app/routes/runs.py` - Locked transaction for complete operator-resolution persistence and post-commit identifier dispatch.
- `tests/conftest.py` - Strict stateful InMemoryRepo coordinator mirrors.
- `tests/test_queue_drain.py` - Hermetic settlement, retry bridge, wake ordering, and backoff proofs.
- `tests/test_needs_operator.py` - Route/wrapper signature, mixed-remember, failure, retry, terminal, and legacy-result proofs.
- `tests/test_queue_durability.py` - Guarded live Postgres atomicity, rollback, dedup, fence, and exhaustion proofs.

## Decisions Made

- Extended terminal background settlement with an explicit expected-status fence so malformed operator context can fail closed directly from `needs_operator` using bounded reason codes.
- Locked the payroll run row before revalidating and persisting an operator generation, preventing stale concurrent state changes from creating authority or scheduling work.
- Promoted the queue backoff calculator to a public seam because multiple consumers now require the same retry curve and the repository forbids cross-module private imports.

## Deviations from Plan

### Auto-fixed Issues

**1. Source-boundary and provenance gates found during the full suite**
- **Found during:** Plan-level verification
- **Issue:** The new background bridges imported a private queue helper, and two new test section labels cited the implementation phase.
- **Fix:** Promoted `backoff_seconds` as the public shared retry seam and rewrote the comments to explain behavior without project-history provenance.
- **Files modified:** `app/queue/drain.py`, `app/routes/pipeline_glue.py`, `tests/test_queue_drain.py`, `tests/test_queue_durability.py`
- **Verification:** Both permanent gates plus queue and operator focused suites pass (61 tests).
- **Committed in:** `8dc32e8`

---

**Total deviations:** 1 auto-fixed verification-gate issue
**Impact on plan:** The correction preserves the planned retry curve and strengthens the permanent module-boundary contract; no feature scope was added.

## Issues Encountered

- The guarded live Postgres queueproof tests were collected but skipped because this environment did not provide both `DATABASE_URL` and `ALLOW_DB_RESET=1`. Hermetic transaction/state mirrors and all focused suites pass.
- The first full-suite run reported only the two source-gate failures above: 833 passed, 79 skipped, 2 failed. After the fix, both failed gates and their affected focused suites passed (61 tests).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The retry/terminal consumers are installed before producer cutover, so later plans can tighten producer return contracts without losing background failures.
- Ready for Plan 18-04. A guarded live Postgres run remains useful verification evidence when the reset-enabled test database is available.

## Self-Check: PASSED

- Focused Task 1 suite: 6 passed.
- Focused Task 2 suite: 9 passed, 25 environment-skipped resume tests.
- Focused Task 3 suite: 22 passed.
- Ruff and mypy checks passed.
- Permanent source-boundary/provenance gates and affected suites: 61 passed.
- Live Postgres queueproof suite: 3 selected, 3 skipped by the two-factor environment guard.
