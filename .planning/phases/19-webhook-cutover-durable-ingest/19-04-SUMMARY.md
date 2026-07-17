---
phase: 19-webhook-cutover-durable-ingest
plan: 04
subsystem: queue
tags: [postgres, durable-queue, ingest, dispatch, identifier-only]

requires:
  - phase: 19-webhook-cutover-durable-ingest
    provides: persisted inbound receipts and bounded delayed ingest service
  - phase: 18-failure-policy-sweep-deletion
    provides: explicit PipelineResult and fenced durable queue consumers
provides:
  - exact four-kind JobKind, SQL, and late-bound dispatch vocabulary
  - event-only ingest enqueue and claim rehydration contract
  - fail-closed ingest queue handler over process_inbound_event
affects: [19-05-null-run-settlement, 19-06-webhook-receipt-cutover, queue-drift-guards]

tech-stack:
  added: []
  patterns:
    - exact enum SQL handler equality
    - identifier-only queue context by job kind
    - late-bound module and function dispatch

key-files:
  created:
    - app/queue/handlers/ingest.py
  modified:
    - app/models/job.py
    - app/db/repo/jobs.py
    - app/db/schema.sql
    - app/queue/dispatch.py
    - tests/test_job_kind_drift.py
    - tests/test_repo_jobs_sql.py

key-decisions:
  - "Open ingest work requires exactly one event_id; terminal done or dead audit rows may lose that reference only through receipt retention."
  - "The ingest dedup key is exactly ingest:{event_id}, and enqueue rejects every run, email, operator, or business identifier."
  - "The ingest handler validates its kind and identifier context, then forwards only process_inbound_event's bounded PipelineResult through the existing late-bound dispatch seam."

patterns-established:
  - "Queue kind widening is atomic across enum, fresh SQL, live SQL, model, enqueue, claim, dispatch, handler, and exact-set tests."
  - "Retention-safe transport references remain mandatory while work is open and may be nulled only after terminal transport state."

requirements-completed: [QUEUE-04]

coverage:
  - id: D1
    description: "INGEST is an exact fourth transport kind across Python, fresh/live SQL, and late-bound dispatch."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_job_kind_drift.py#TestDispatchTableMatchesJobKind"
        status: pass
      - kind: unit
        ref: "tests/test_job_kind_drift.py#test_ingest_sql_requires_only_an_event_identifier_while_open"
        status: pass
    human_judgment: false
  - id: D2
    description: "Ingest enqueue and claim carry one event identifier with no business payload or next payroll status."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_repo_jobs_sql.py -k 'ingest or claim or context'"
        status: pass
      - kind: other
        ref: "uv run mypy app/models/job.py app/db/repo/jobs.py app/queue/handlers/ingest.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "The internal ingest handler forwards the persisted event identifier to delayed ingest and remains unreachable from HTTP routes."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_job_kind_drift.py#test_ingest_handler_forwards_only_the_event_identifier"
        status: pass
      - kind: unit
        ref: "tests/test_job_kind_drift.py#test_http_routes_do_not_produce_ingest_jobs"
        status: pass
    human_judgment: false

duration: 13min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 04: Identifier-Only Ingest Queue Contract Summary

**Durable ingest is now an exact fourth queue operation whose open rows carry only a persisted event identifier and dispatch through a fail-closed delayed-ingest handler.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-07-17T00:42:00Z
- **Completed:** 2026-07-17T00:55:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Widened `JobKind`, the fresh and live SQL kind checks, `Job`, enqueue SQL, claim `RETURNING`, and row rehydration as one exact four-kind contract.
- Added an open-work context constraint that permits `event_id` only for ingest while retaining terminal audit rows after bounded receipt deletion.
- Registered `handle_ingest` through the module/function-name dispatch table, preserving monkeypatchability and forwarding only the delayed service's bounded result.
- Added exact-set, ordered-bijection, parameterization, malformed-context, synthetic-drift, retention, handler, and no-HTTP-producer proofs.

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Pin exact ingest vocabulary, context, claim, and dispatch contracts** - `5b86db0` (test)
2. **Task 2 GREEN: Activate the identifier-only ingest kind and delayed handler** - `3c572c3` (feat)

## Files Created/Modified

- `app/queue/handlers/ingest.py` - Fail-closed event-identifier consumer over delayed ingest.
- `app/models/job.py` - Four-kind transport vocabulary and nine-column claimed job model.
- `app/db/repo/jobs.py` - Exact context validation, stable ingest dedup, parameterized event persistence, and claim rehydration.
- `app/db/schema.sql` - Fresh/live kind widening and retention-safe exact ingest context checks.
- `app/queue/dispatch.py` - Late-bound ingest handler registration.
- `tests/test_job_kind_drift.py` - Exact enum/SQL/handler equality, handler forwarding, context, and route-producer guards.
- `tests/test_repo_jobs_sql.py` - Ordered claim bijection and event-only enqueue/claim proofs.

## Decisions Made

- Receipt deletion may set `event_id` to null only after an ingest job reaches `done` or `dead`; pending and leased work remains referentially intact.
- `enqueue_job` owns the stable `ingest:{event_id}` key and rejects mixed identifier context before issuing SQL.
- `handle_ingest` checks both kind and identifiers before calling the delayed service; it never loads by run ID or writes payroll status.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Guarded live-database tests remained unavailable and are reported as skips. Fresh/live DDL equality and SQL mapping are proven hermetically; no live migration result is claimed.
- The root suite emitted the existing Starlette/httpx deprecation warning.

## User Setup Required

None - no external service configuration required.

## Verification

- RED focused gate: 10 expected failures on absent ingest contracts, with 17 selected checks still passing.
- Final focused queue-contract suite: 81 passed.
- Queue drain, pump, and durability regression slice: 68 passed, 36 guarded skips.
- Schema-introspection and source-comment gates: 32 passed.
- Ruff: passed for all modified Python production and test files.
- Mypy: passed for `app/models/job.py`, `app/db/repo/jobs.py`, and `app/queue/handlers/ingest.py`.
- Root offline suite: 957 passed, 70 guarded skips.
- `git diff --check`: passed.

## Next Phase Readiness

- The null-run settlement plan can now make ingest success, retry, exhaustion, and final-lease reaping transport-safe before any request producer exists.
- The webhook cutover can later atomically create `INGEST` using the enforced `ingest:{event_id}` key after settlement and fake parity are complete.
- No HTTP route, settlement branch, reaper, fake repository, or payroll status writer changed in this plan.

---
*Phase: 19-webhook-cutover-durable-ingest*
*Completed: 2026-07-16*

## Self-Check: PASSED

All seven production/test files and this summary exist; task commits `5b86db0` and
`3c572c3` are present; focused, static, queue-regression, provenance, full-suite,
and diff-check gates are green. No generated artifact remains untracked.
