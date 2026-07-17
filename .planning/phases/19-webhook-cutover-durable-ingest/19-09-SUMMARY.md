---
phase: 19-webhook-cutover-durable-ingest
plan: 09
subsystem: dashboard-queue-feedback
tags: [python, fastapi, postgres, jinja2, durable-queue, browser-safety]

requires:
  - phase: 19-webhook-cutover-durable-ingest
    provides: durable demo, reply, and operator jobs plus bounded redirect flags
  - phase: 18-failure-policy-sweep-deletion
    provides: pending/leased queue states and bounded failure presentation
provides:
  - fixed per-run Running, Queued, and Retry queued projection with deterministic precedence
  - secondary queue badges and exact durability/redirect copy on existing run surfaces
  - two-second status polling capped at 60 attempts with no recovery side effects
affects: [19-10-durability-proof, 19-11-stale-consumer-migration, 19-12-cutover-guard, 21-ops-view]

tech-stack:
  added: []
  patterns:
    - reduce transport state to an allowlisted label before it crosses the browser boundary
    - keep payroll status primary and render queue state as a separate secondary projection
    - stop bounded polling silently without mutating or re-enqueueing work

key-files:
  created: []
  modified:
    - app/db/repo/jobs.py
    - app/db/repo/demo.py
    - app/db/repo/__init__.py
    - app/routes/runs.py
    - app/templates/runs_list.html
    - app/templates/run_detail.html
    - app/static/style.css
    - tests/conftest.py
    - tests/test_dashboard.py

key-decisions:
  - "Open-job precedence is Running, then immediately due Queued, then delayed Retry queued; the projection returns no other job data."
  - "Status JSON carries only queue_label, queue_badge_class, and has_open_job in addition to the existing bounded payroll/failure presentation."
  - "List rows update in place, while detail reloads once only when payroll status or the bounded queue label changes."

patterns-established:
  - "Browser queue boundary: fixed label in, fixed class/boolean out; identifiers, attempts, timestamps, payloads, and diagnostics are stripped."
  - "Polling boundary: 2000 ms cadence, 60-attempt cap, and no enqueue, retrigger, reply-consumption, or payroll-state call."

requirements-completed: [QUEUE-04]

coverage:
  - id: D1
    description: "Per-run and runs-list queue projections expose only Running, Queued, Retry queued, or no label with fixed precedence."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_dashboard.py#test_get_run_queue_label_returns_only_bounded_labels"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard.py#test_get_run_queue_label_sql_pins_running_queued_retry_precedence"
        status: pass
    human_judgment: false
  - id: D2
    description: "Existing run list/detail surfaces keep payroll status primary while showing one accessible secondary badge and exact durability/redirect copy."
    requirement: QUEUE-04
    verification:
      - kind: automated_ui
        ref: "tests/test_dashboard.py#test_queued_run_detail_has_secondary_badge_durability_and_bounded_polling"
        status: pass
      - kind: automated_ui
        ref: "tests/test_dashboard.py#test_retry_queued_runs_list_keeps_payroll_badge_first_and_updates_in_place"
        status: pass
      - kind: automated_ui
        ref: "tests/test_dashboard.py#test_resolution_superseded_notice_uses_fixed_copy_not_query_text"
        status: pass
    human_judgment: false
  - id: D3
    description: "Status polling is browser-safe, read-only, every two seconds, and stops after 60 attempts without recovery calls."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_dashboard.py#test_running_queue_status_json_is_bounded_and_read_only"
        status: pass
      - kind: automated_ui
        ref: "tests/test_dashboard.py#test_queue_feedback_hidden_when_no_open_work"
        status: pass
    human_judgment: false

duration: 19min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 09: Bounded Queue Feedback Summary

**Existing payroll-run surfaces now show a safe secondary open-job signal and exact durability feedback without turning transport state into payroll state or exposing queue internals.**

## Performance

- **Duration:** 19 min
- **Started:** 2026-07-17T02:30:41Z
- **Completed:** 2026-07-17T02:49:11Z
- **Tasks:** 2 TDD tasks
- **Files modified:** 9

## Accomplishments

- Added one aggregate per-run queue projection with fixed `Running -> Queued -> Retry queued` precedence and an equivalent bounded runs-list projection.
- Extended existing list/detail/status surfaces with a distinct secondary queue badge, exact durability and superseded/error notices, and no job identifiers, counters, timestamps, payloads, or diagnostics.
- Extended both vanilla-JS pollers to 60 two-second attempts, preserving list controls/scroll and reloading detail only for a meaningful payroll or bounded queue-label transition.

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Pin bounded queue projection and hostile browser-data safety** - `ee2b815` (test)
2. **Task 2 GREEN: Render secondary queue state and 120-second no-recovery polling** - `5d7b1ce` (feat)

## Files Created/Modified

- `app/db/repo/jobs.py` - Projects one fixed open-job label for a run without selecting job internals.
- `app/db/repo/demo.py` - Adds the same bounded queue label to the reverse-chronological runs-list query.
- `app/db/repo/__init__.py` - Exposes the queue-label reader through the repository facade.
- `app/routes/runs.py` - Allowlists queue presentation, strips raw job fields, serves bounded status JSON, and maps query-flag presence to fixed notices.
- `app/templates/runs_list.html` - Keeps payroll status first, updates one secondary queue badge in place, and polls for at most 120 seconds.
- `app/templates/run_detail.html` - Adds the accessible secondary badge, exact durability/superseded copy, and one-reload meaningful-change poller.
- `app/static/style.css` - Adds token-based 8px status spacing, 12px semibold queue labels, neutral queued styling, and soft-indigo running styling.
- `tests/conftest.py` - Mirrors queue-label precedence and facade patch wiring in the in-memory repository.
- `tests/test_dashboard.py` - Proves exact labels/copy, hostile-data exclusion, hierarchy, accessibility, polling cap, and no-recovery behavior.

## Decisions Made

- Queue projection failures degrade to no secondary label; they never replace or infer the authoritative payroll status.
- A non-empty redirect flag selects fixed server-owned copy. Query values are never rendered, even when hostile.
- Detail renders empty live regions only when an in-flight run could acquire queue work; settled runs without open work render neither queue copy nor polling code.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Exported the queue projection and preserved fake-repository parity**
- **Found during:** Task 2 (Render secondary queue state and 120-second no-recovery polling)
- **Issue:** The planned `repo.get_run_queue_label` call required a facade export, and project context requires every new facade function to be paired with the in-memory repo patch inventory; neither file appeared in the plan's `files_modified` list.
- **Fix:** Re-exported the reader, mirrored due/delayed/leased precedence in `InMemoryRepo`, projected the label from fake list rows, and patched the new seam in the shared fixture.
- **Files modified:** `app/db/repo/__init__.py`, `tests/conftest.py`
- **Verification:** Focused queue tests, full dashboard suite, Ruff, mypy, and `git diff --check` passed.
- **Committed in:** `5d7b1ce`

---

**Total deviations:** 1 auto-fixed (1 Rule 3 blocking issue)
**Impact on plan:** The extra facade/fake work is required plumbing for the planned repository seam and hermetic test contract; it adds no product, payroll-state, or operations scope.

## Issues Encountered

- Dashboard route tests that deliberately monkeypatch `load_run` needed a default DB-free queue reader seam; the autouse fixture supplies `None`, and queue-specific tests opt into each fixed label.
- The existing Starlette/httpx deprecation warning remains unchanged.

## User Setup Required

None - no external service configuration required.

## Verification

- Task 1 RED gate: 9 expected failures before implementation.
- Focused queue/UI gate: 10 passed, 35 deselected.
- Full `tests/test_dashboard.py`: 43 passed, 2 skipped.
- Ruff: passed for every modified Python production and test file.
- Mypy: passed for `app/db/repo/jobs.py`, `app/db/repo/demo.py`, and `app/routes/runs.py`.
- `git diff --check`: passed.

## Next Phase Readiness

- Plans 19-11 and 19-12 can migrate/delete stale compatibility consumers without inventing a second queue presentation seam.
- Plan 19-10 can use the bounded queue signal for phase evidence while retaining Phase 21 ownership of depth, age, attempts, dead letters, alarms, and manual retry controls.
- No schema, dependency, new endpoint, new payroll status, modal, metric, operations control, or SPA was introduced.

## Known Stubs

None.

## Self-Check: PASSED

- All nine modified production/test files and this summary exist.
- TDD commits `ee2b815` and `5d7b1ce` are present in history with no tracked-file deletions.
- Exact plan verification, browser-safety tests, static analysis, and diff-check gates are green.

---
*Phase: 19-webhook-cutover-durable-ingest*
*Completed: 2026-07-16*
