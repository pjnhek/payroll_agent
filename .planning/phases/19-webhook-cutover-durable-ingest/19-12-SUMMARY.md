---
phase: 19-webhook-cutover-durable-ingest
plan: 12
subsystem: durable-queue-architecture
tags: [python, fastapi, pytest, ast, durable-queue, architecture-guard]

requires:
  - phase: 19-webhook-cutover-durable-ingest
    provides: durable route producers, reply/operator handlers, and migrated consumer tests
provides:
  - wrapper-free pipeline glue with explicit PipelineResult value seams only
  - route modules with no process-memory payroll scheduling signatures
  - exact non-vacuous AST guard for all historical producers and migrated consumers
affects: [19-10-phase-evidence, QUEUE-04, durable-queue, webhook-cutover]

tech-stack:
  added: []
  patterns:
    - queued handlers preserve explicit values and escaping failures for fenced drain settlement
    - architecture guards use exact inventories plus synthetic falsification mutations

key-files:
  created:
    - tests/test_background_task_cutover.py
  modified:
    - app/routes/pipeline_glue.py
    - app/routes/runs.py
    - app/queue/handlers/pipeline.py
    - tests/test_dashboard.py
    - tests/test_needs_operator.py
    - tests/test_webhook.py

key-decisions:
  - "Pipeline glue retains only durable reply classification/authorization helpers and explicit PipelineResult-producing seams; no procedure consumes or swallows queue-owned outcomes."
  - "The permanent cutover guard pins the exact eight historical route producers and nine Plan 19-11 consumers, plus six full-suite consumers discovered during migration."
  - "Synthetic BackgroundTasks/add_task and retired-wrapper mutations run through the same AST detector as the real inventory."

patterns-established:
  - "Cutover inventory: exact historical functions and files are asserted present before negative scans can pass."
  - "Retired compatibility names are rejected as definitions and references, while unrelated background facilities outside the payroll inventory remain legal."

requirements-completed: [QUEUE-04]

coverage:
  - id: D1
    description: "All process-memory payroll compatibility procedures and route BackgroundTasks signatures are absent after durable consumer migration."
    requirement: QUEUE-04
    verification:
      - kind: integration
        ref: "Task 1 focused route/reply/operator gate: 242 passed, 13 skipped"
        status: pass
      - kind: other
        ref: "mypy app/routes/pipeline_glue.py app/routes/runs.py app/queue/handlers/pipeline.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "An exact AST inventory rejects background producers, retired definitions, and stale references with two non-vacuous synthetic mutations."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_background_task_cutover.py: 3 passed"
        status: pass
      - kind: integration
        ref: "tests/test_webhook_dedup_race.py: guarded skip without DATABASE_URL"
        status: pass
    human_judgment: false
  - id: D3
    description: "The complete application suite remains green after compatibility deletion."
    requirement: QUEUE-04
    verification:
      - kind: integration
        ref: "UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q: 1003 passed, 75 skipped"
        status: pass
    human_judgment: false

duration: 14min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 12: Background Compatibility Deletion Summary

**Payroll execution can no longer fall back to process-owned background procedures: every route producer is durable, every queue result reaches fenced settlement explicitly, and an exact mutation-proven AST inventory makes reintroduction fail deterministically.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-07-17T03:44:59Z
- **Completed:** 2026-07-17T03:59:17Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Deleted `finish_reply_resume`, `_consume_background_result`, `resume_pipeline_bg`, `run_pipeline_bg`, `operator_resume_bg`, their private compatibility-only mapping helper, and the obsolete process-local reply router.
- Removed the final FastAPI `BackgroundTasks` route signature and rewrote pipeline/retrigger comments around identifier-only jobs, explicit values, and fenced drain settlement.
- Added an exact AST inventory covering all eight historical producers, all nine named former consumers, six additional migrated consumers, durable glue presence, and synthetic producer/wrapper falsification.
- Preserved sender revalidation ordering, first-commit operator authority, durable retrigger behavior, payroll state transitions, and delivery semantics through the full regression suite.

## Task Commits

Each task was committed atomically:

1. **Task 1: Delete migrated compatibility procedures and stale signatures** - `8c21ea6` (refactor)
2. **Task 2: Install complete producer and retired-symbol architecture guard** - `51a7e43` (test)

## Files Created/Modified

- `app/routes/pipeline_glue.py` - Retains durable reply helpers and exact PipelineResult value seams only.
- `app/routes/runs.py` - Removes the unused approval background parameter and describes durable reply/retrigger production accurately.
- `app/queue/handlers/pipeline.py` - Documents explicit value/exception propagation into fenced drain settlement without a retired fallback.
- `tests/test_background_task_cutover.py` - Pins exact production/consumer inventories and proves both producer and wrapper mutations are detected.
- `tests/test_dashboard.py` - Removes obsolete process-local reply spies while preserving durable simulated-reply assertions.
- `tests/test_needs_operator.py` - Removes superseded wrapper-policy tests and pins the identifier-only durable handler instead.
- `tests/test_webhook.py` - Removes obsolete request-boundary wrapper fakes; provider and payroll no-inline guards remain on active seams.

## Decisions Made

- The compatibility-only `route_reply` and `_load_operator_resume_mapping` helpers were deleted with their sole wrapper consumers; keeping either would leave a non-durable fallback surface or dead policy duplicate.
- The architecture guard scans a bounded payroll inventory, not every framework use in the repository. This prevents payroll producer regression while leaving unrelated background facilities outside the named surfaces legal.
- The nine Plan 19-11 consumers remain an exact primary tuple. Additional full-suite consumers are separately enumerated so dependency evidence stays precise without leaving discovered stale-reference seams unguarded.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Migrated three wrapper-reference test surfaces omitted from the plan file list**
- **Found during:** Task 1 (Delete migrated compatibility procedures and stale signatures)
- **Issue:** `tests/test_dashboard.py`, `tests/test_needs_operator.py`, and `tests/test_webhook.py` still referenced the removed process-local router/wrappers. Deleting production compatibility exactly as planned would otherwise break collection/runtime or leave stale source references.
- **Fix:** Removed obsolete spies/fakes, replaced the wrapper signature assertion with the durable `handle_operator_resume(job)` seam, and retained active no-inline/durable-job behavior checks.
- **Files modified:** `tests/test_dashboard.py`, `tests/test_needs_operator.py`, `tests/test_webhook.py`
- **Verification:** The expanded Task 1 gate passed 242 tests with 13 guarded skips; the complete suite passed 1,003 tests with 75 guarded skips.
- **Committed in:** `8c21ea6`

---

**Total deviations:** 1 auto-fixed (1 Rule 3 blocking issue)
**Impact on plan:** Test-only removal of stale compatibility references required by D-23; no schema, dependency, payload, status, provider behavior, or product capability changed.

## Issues Encountered

- The real-Postgres RFC Message-ID race remained guarded because `DATABASE_URL` is not configured. Its test collected successfully and reported one focused skip; the full suite reported 75 guarded database/environment skips.
- The existing Starlette/httpx deprecation warning remains unchanged.

## Verification

- Pre-deletion consumer gate: 198 passed, 11 skipped.
- Post-deletion expanded route/reply/operator gate: 242 passed, 13 skipped.
- Permanent cutover guard plus RFC dedup race: 3 passed, 1 guarded skip.
- Full suite: 1,003 passed, 75 skipped, 1 unchanged deprecation warning.
- Ruff: passed for `app/routes/pipeline_glue.py`, `app/routes/runs.py`, `app/queue/handlers/pipeline.py`, and `tests/test_background_task_cutover.py`.
- Mypy: passed for all three modified production modules.
- `git diff --check`: passed.

## User Setup Required

None. A configured test Postgres database is needed only to execute the already-guarded RFC Message-ID race locally.

## Next Phase Readiness

- Plan 19-10 can perform activation-fence and restart/retention closeout against a wrapper-free producer tree.
- D-23 and QUEUE-04 producer-cutover implementation are complete; authoritative phase completion still belongs to Plan 19-10 evidence and the phase verifier.
- No new dependency, business payload, payroll status, Phase 20 send behavior, or Phase 21 operations surface was introduced.

## Known Stubs

None introduced.

## Self-Check: PASSED

- The new guard file, all six modified production/test files, and this summary exist.
- Task commits `8c21ea6` and `51a7e43` are present in history.
- Focused tests, full suite, Ruff, mypy, retired-source scan, and diff checks are green; guarded Postgres evidence is reported explicitly.

---
*Phase: 19-webhook-cutover-durable-ingest*
*Completed: 2026-07-16*
