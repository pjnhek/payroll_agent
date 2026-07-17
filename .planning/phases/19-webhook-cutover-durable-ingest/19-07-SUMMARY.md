---
phase: 19-webhook-cutover-durable-ingest
plan: 07
subsystem: durable-demo-ingest
tags: [python, fastapi, postgres, durable-queue, jinja2, recruiter-demo]

requires:
  - phase: 19-webhook-cutover-durable-ingest
    provides: identifier-only run_pipeline jobs and caller-owned enqueue transactions
  - phase: 17-the-pump
    provides: post-commit in-process queue wake signal
provides:
  - atomic email, payroll run, and run_pipeline job creation for both demo triggers
  - direct run-detail navigation after successful durable demo commits
  - bounded PII-safe enqueue failure notices on each action-owning surface
affects: [19-12-producer-cutover-guards, 21-durability-proofs-ops-view, recruiter-demo]

tech-stack:
  added: []
  patterns:
    - caller-owned transaction around every write that creates owed demo work
    - post-commit wake followed by exact run-detail redirect
    - fixed query flag projected to fixed browser copy

key-files:
  created: []
  modified:
    - app/routes/demo.py
    - app/routes/dashboard.py
    - app/routes/runs.py
    - app/templates/index.html
    - app/templates/runs_list.html
    - app/static/style.css
    - tests/test_demo_landing.py
    - tests/test_demo_fixtures.py
    - tests/test_dashboard.py

key-decisions:
  - "Both demo producers treat an unexpected inbound duplicate or job dedup conflict as transaction failure because each click mints a fresh message and run identity."
  - "The composer remains record-only, while the curated fixture retains normal delivery behavior; both owe the same identifier-only run_pipeline job before redirect."
  - "Browser failure state is derived only from demo_queue_error=1 and renders one fixed sentence; exception values and submitted content never cross the route boundary."

patterns-established:
  - "Demo owed-work invariant: inbound email, payroll run, and demo_run:{run_id} job commit together or all roll back."
  - "A demo producer calls wake.wake only after transaction exit and then redirects to /runs/{run_id}."

requirements-completed: [QUEUE-04]

coverage:
  - id: D1
    description: "Composer and curated fixture each commit one inbound email, one run, and one identifier-only run_pipeline job before waking."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_demo_landing.py#test_demo_compose_commits_email_run_and_job_before_wake"
        status: pass
      - kind: unit
        ref: "tests/test_demo_fixtures.py#test_demo_fixture_commits_email_run_and_job_before_wake"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every email, run, job, and unexpected-duplicate failure rolls back all demo writes, wakes nothing, and renders only the fixed retry message."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_demo_landing.py#test_demo_compose_rolls_back_every_write_failure_and_renders_bounded_notice"
        status: pass
      - kind: unit
        ref: "tests/test_demo_fixtures.py#test_demo_fixture_rolls_back_every_write_failure_and_renders_bounded_notice"
        status: pass
    human_judgment: false
  - id: D3
    description: "Both successful demo actions redirect directly to their exact run detail and no demo route retains a BackgroundTasks producer."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_demo_landing.py#test_demo_routes_have_no_process_memory_pipeline_handoff"
        status: pass
      - kind: integration
        ref: "tests/test_dashboard.py#test_send_test_mints_fresh_message_id_each_click"
        status: unknown
    human_judgment: true
    rationale: "The direct route contract passed hermetically, but the two-click live-Postgres integration requires DATABASE_URL and ALLOW_DB_RESET=1 and was not claimed in this environment."

duration: 13min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 07: Durable Recruiter Demo Producers Summary

**Both recruiter demo triggers now atomically commit their inbound email, payroll run, and durable pipeline job, then wake after commit and open the exact run detail page.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-07-17T01:13:32Z
- **Completed:** 2026-07-17T01:26:31Z
- **Tasks:** 2 TDD tasks
- **Files modified:** 9

## Accomplishments

- Replaced both demo `BackgroundTasks` handoffs with caller-owned transactions that commit email, run, and `demo_run:{run_id}` work as one unit.
- Preserved record-only composer behavior, fixture allowlisting, input caps, clean-body handling, deterministic payroll behavior, and direct one-click recruiter navigation.
- Added exact bounded failure notices to the composer and curated-fixture surfaces, with exception type-only logging and no identifier, body, or provider detail exposure.

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Prove demo atomicity, redirects, and bounded failures** - `92d72c4` (test)
2. **Task 2 GREEN: Commit durable demo jobs and bounded notices** - `5fa1d9e` (feat)

## Files Created/Modified

- `app/routes/demo.py` - Shares one transaction across each demo email, run, and `RUN_PIPELINE` enqueue; wakes after commit and redirects to detail.
- `app/routes/dashboard.py` - Projects the allowlisted composer failure flag to a boolean template value.
- `app/routes/runs.py` - Projects the allowlisted curated-fixture failure flag to the runs template.
- `app/templates/index.html` - Renders the exact bounded retry copy beside the composer action.
- `app/templates/runs_list.html` - Renders the exact bounded retry copy beside the curated fixture action.
- `app/static/style.css` - Applies the approved destructive color treatment at the existing callout scale.
- `tests/test_demo_landing.py` - Proves composer commit order, rollback matrix, PII-safe copy, and complete process-memory deletion.
- `tests/test_demo_fixtures.py` - Proves the same transaction and failure matrix for curated fixtures.
- `tests/test_dashboard.py` - Updates existing demo route tests for durable enqueue dependencies and exact detail redirects.

## Decisions Made

- Duplicate email or job insertion is an error for demo clicks, not an idempotent success: each click owns a fresh UUID-derived message and run, so a conflict means the owed unit did not commit as designed.
- `business_id` is included as transport context on demo `RUN_PIPELINE` jobs while the job remains identifier-only and carries no business payload or next payroll status.
- Error redirects use only `demo_queue_error=1`; every other query value renders no notice.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Routed failure presentation through the actual template and route owners**
- **Found during:** Task 2 (Commit each demo run with its durable job and bounded notice)
- **Issue:** The plan named `app/templates/dashboard.html`, which does not exist, and assigned the runs-list projection to `dashboard.py`, while this checkout renders the composer from `index.html` and owns `GET /runs` in `runs.py`.
- **Fix:** Added the composer notice to `index.html`, the curated notice to `runs_list.html`, projected the fixed flag from `dashboard.py` and `runs.py`, added the approved destructive callout style, and updated the existing dashboard tests that depended on the deleted background handoff.
- **Files modified:** `app/routes/dashboard.py`, `app/routes/runs.py`, `app/templates/index.html`, `app/templates/runs_list.html`, `app/static/style.css`, `tests/test_dashboard.py`
- **Verification:** Focused demo/queue/redirect gate, Ruff, mypy, provenance guard, and diff check passed.
- **Committed in:** `5fa1d9e`

---

**Total deviations:** 1 auto-fixed (1 Rule 3 blocking issue)
**Impact on plan:** The adjustment targets the real action-owning surfaces and is required for the specified behavior; no unrelated UI or route behavior changed.

## Issues Encountered

- The repository-wide offline suite exceeded the command runner's single-call execution window after reaching 13%; no full-suite result is claimed here. The exact plan gate, all modified-file static checks, and the source-comment provenance guard completed successfully.
- The existing Starlette/httpx deprecation warning remains unchanged.

## User Setup Required

None - no external service configuration required.

## Verification

- TDD RED gate: 13 expected failures and 32 related passes before implementation.
- Final demo/queue/redirect gate: 48 passed, 30 deselected.
- Composer module: 32 passed.
- Curated fixture module: 13 passed.
- Comment provenance guard: 5 passed.
- Ruff: passed for all modified Python production and test files.
- Mypy: passed for `app/routes/demo.py` and `app/routes/dashboard.py`.
- `git diff --check`: passed.

## Next Phase Readiness

- Later producer-cutover guards can assert there is no demo route `BackgroundTasks` handoff and that both demo actions owe a durable `run_pipeline` job.
- Live Postgres two-click evidence remains for the reset-authorized integration environment; no implementation blocker remains.
- No new endpoint, schema, dependency, business status, or money-moving decision was introduced.

## Known Stubs

None. Empty collections found by the scan are existing typed test recorders or intentional empty-state fallbacks, not UI or data-source stubs introduced by this plan.

## Self-Check: PASSED

- All nine modified production/test files and this summary exist.
- Task commits `92d72c4` and `5fa1d9e` are present in history.
- Exact plan verification, static analysis, comment-provenance, and diff-check gates are green.
- No generated or unrelated untracked file remains.

---
*Phase: 19-webhook-cutover-durable-ingest*
*Completed: 2026-07-16*
