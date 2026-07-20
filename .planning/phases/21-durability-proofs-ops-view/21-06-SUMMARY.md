---
phase: 21-durability-proofs-ops-view
plan: 06
subsystem: ui
tags: [fastapi, jinja2, dashboard, ops-view, queue-metrics, read-only-route]

# Dependency graph
requires:
  - phase: 21-durability-proofs-ops-view
    provides: "plan 21-02's five bounded, side-effect-free repo facade reads (count_jobs_by_state, oldest_due_pending_age_seconds, attempts_distribution, list_dead_letter_jobs, list_unaccounted_error_runs) and their fake_repo pairing, which this route consumes verbatim without touching app/db/repo/"
provides:
  - "GET /ops — the transport-surface dashboard page: queue depth split (pending/leased), oldest-due-pending age against the pump-cadence bound, attempts distribution against max_attempts, the bounded dead-letter list linking to run detail, and the unaccounted-error alarm banner"
  - "app/main.py's seventh router registration"
  - "base.html's fourth nav entry (Pyrl | Runs | Eval | Ops)"
  - "PUMP_CADENCE_MINUTES, a module constant on app/routes/ops.py pinned by a live test against .github/workflows/pump.yml's cron expression"
affects: [app/routes, app/templates, app/static/style.css]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A single try/except around all of a route's read-only facade calls, falling back to zeroed/empty state on any failure (mirrors runs_list's cold-start tolerance) — this means any per-panel hermetic test must either monkeypatch every one of the five reads, or build on the fake_repo fixture (which already supplies working defaults for all five) and override only the one under test."
    - "A route's read-only contract is proven two-sided: a positive assertion that every expected read was actually invoked (catches a hardcoded-default panel), and a negative assertion — derived from app.db.repo.__all__ minus the expected reads, not a hand-picked pair — that every OTHER facade name raises if called (catches any write, including ones a future edit adds)."
    - "New CSS for a page must reuse existing design tokens exclusively (var(--danger) etc.); zero new hex/color literals introduced."

key-files:
  created:
    - app/routes/ops.py
    - app/templates/ops.html
    - tests/test_ops_route.py
  modified:
    - app/main.py
    - app/templates/base.html
    - app/static/style.css

key-decisions:
  - "Task 1 committed a functional but visually minimal ops.html (raw context values, no panel styling) rather than deferring template creation entirely to Task 2, because Task 1's own behavior explicitly requires 'GET /ops returns 200 and renders ops.html' and 'the template context carries: ...' — both of which are unfalsifiable against a nonexistent template. Task 2 then replaced it with the full panel/banner/nav layout. This keeps both task commits independently green (each task's own `pytest tests/test_ops_route.py -v` passes at that commit) while preserving the plan's two-task narrative: Task 1 proves the route's data contract, Task 2 proves the presentation contract."
  - "The plan's literal route-registration one-liner (`sorted({r.path for r in app.routes if getattr(r,'path','').startswith('/ops')})`) prints `[]` under the installed FastAPI 0.138.0, not `['/ops']` as the acceptance criteria states — this FastAPI version wraps each `include_router()` call in a lazy `_IncludedRouter` container whose concrete `APIRoute` objects live on `.original_router.routes`, not directly on `app.routes`. Verified this is a FastAPI-version behavior change, not a registration bug: TestClient requests to `/ops` succeed end-to-end. The route-registration test walks through `.original_router.routes` recursively to reach real routes, and asserts the same invariant (exactly one `/ops` GET route) the plan's one-liner intended."
  - "PUMP_CADENCE_MINUTES=30, read from `.github/workflows/pump.yml`'s `cron: \"*/30 * * * *\"` and pinned by a test that parses the workflow YAML directly (not a hardcoded regex against the raw text) — including a documented workaround for YAML 1.1 parsing a bare `on:` top-level key as the boolean `True`, not the string `\"on\"`."
  - "The alarm banner and the ops-bound helper text use only `var(--danger)`/`var(--danger-hover)`/`var(--surface)`/existing spacing tokens — no new hex literal — satisfying the acceptance criterion by construction rather than by re-using the pre-existing `.callout-error` class (which itself predates the token system and hardcodes its hex values)."

requirements-completed: [OPS-01]

coverage:
  - id: D1
    description: "GET /ops renders queue depth split (pending/leased), oldest-due-pending age against the pump-cadence bound, attempts distribution against max_attempts, and the bounded dead-letter list — each panel showing its number beside the bound that makes it meaningful"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_ops_route.py::test_ops_context_carries_depth_split_not_a_combined_total, ::test_ops_renders_attempts_distribution_against_max_attempts, ::test_ops_renders_oldest_due_pending_bound, ::test_ops_renders_no_due_pending_work_not_a_zero"
        status: pass
    human_judgment: false
  - id: D2
    description: "The unaccounted-error alarm banner renders above the panels exactly when unaccounted_error_rows is non-empty, states what it detects, links each row to run detail, and carries no acknowledge/mute/dismiss control anywhere on the page"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_ops_route.py::test_ops_alarm_banner_absent_when_no_unaccounted_errors, ::test_ops_alarm_banner_present_and_links_to_the_run"
        status: pass
    human_judgment: false
  - id: D3
    description: "The route is proven side-effect free against the whole repo facade mutation surface (derived from app.db.repo.__all__, not a hand-picked pair of seams) and against the five expected reads (positive half — every one genuinely invoked)"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_ops_route.py::test_ops_route_calls_all_five_reads, ::test_ops_route_never_calls_any_facade_mutation"
        status: pass
    human_judgment: false
  - id: D4
    description: "The dead-letter table renders only the bounded seven-column projection (no lease token, dedup key, or payload); a dead-letter row with a run_id links to /runs/{run_id}, a row without one renders no link"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_ops_route.py::test_ops_dead_letter_projects_only_the_bounded_fields, ::test_ops_dead_letter_row_links_to_run_detail, ::test_ops_dead_letter_row_with_no_run_id_renders_no_link"
        status: pass
    human_judgment: false
  - id: D5
    description: "The fourth nav entry (Ops) renders in the Pyrl | Runs | Eval | Ops order; the as-of stamp is present; the page carries no <script>, no polling, and no meta-refresh"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_ops_route.py::test_ops_nav_has_four_entries_in_order, ::test_ops_as_of_stamp_present, ::test_ops_page_has_no_script_or_polling"
        status: pass
    human_judgment: false
  - id: D6
    description: "PUMP_CADENCE_MINUTES is pinned against the cron expression that actually sets the cadence in .github/workflows/pump.yml, so a cadence change reds the suite instead of silently mis-rendering the bound"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_ops_route.py::test_pump_cadence_minutes_pinned_to_workflow_cron"
        status: pass
    human_judgment: false
  - id: D7
    description: "No regression: hermetic suite green (1231 passed, up from the 1212-passed wave-0/wave-1 baseline by exactly the 19 tests this plan adds), mypy --strict clean, ruff clean, app/db/repo/ untouched"
    verification:
      - kind: unit
        ref: "env -u DATABASE_URL uv run pytest -q -> 1231 passed, 104 skipped; uv run mypy --strict app -> clean (74 files); uv run ruff check . -> clean; git diff --stat <base>..HEAD -- app/db/repo/ -> empty"
        status: pass
    human_judgment: false

# Metrics
duration: 55min
completed: 2026-07-20
status: complete
---

# Phase 21 Plan 06: The /ops Transport-Surface View Summary

**A new read-only `/ops` dashboard page — the fourth nav destination — surfacing queue depth split, oldest-due-pending age against the pump cadence, attempts distribution against max_attempts, the bounded dead-letter list, and the unaccounted-error alarm banner, proven side-effect-free against the whole repository facade.**

## Performance

- **Duration:** ~55 min
- **Tasks:** 2
- **Files modified:** 6 (3 created: `app/routes/ops.py`, `app/templates/ops.html`, `tests/test_ops_route.py`)

## Accomplishments

- `GET /ops` reads through five facade functions plan 21-02 shipped (`count_jobs_by_state`, `oldest_due_pending_age_seconds`, `attempts_distribution`, `list_dead_letter_jobs`, `list_unaccounted_error_runs`), wraps them in one `try/except` so a DB outage renders a zeroed/empty page instead of a 500, and computes `generated_at` server-side for an honest "as of" stamp.
- Every panel renders its number beside the bound that makes it meaningful: depth stays a two-figure split (never a combined total); oldest-due-pending age is compared against a `PUMP_CADENCE_MINUTES` constant pinned live to `.github/workflows/pump.yml`'s cron; attempts distribution is rendered against `get_settings().max_attempts`; the empty-backlog case renders "No due pending work", not a zero.
- The unaccounted-error alarm banner appears only when the queue truly cannot account for an error run, states the actual failure mode in prose, links to run detail, and — per the plan's disposition — carries no acknowledge/mute/dismiss affordance; the page renders no `<form>` or `<button>` at all.
- The dead-letter table renders exactly the seven-column bounded projection plan 21-02 defined; a synthetic test proves extra dict keys (lease token, dedup key, payload) never reach the response body even if a future read widens the dict.
- `/ops` is proven read-only two ways: every one of the five expected reads is asserted invoked (catches a hardcoded panel), and every other name in `app.db.repo.__all__` is patched to raise and the page still renders 200 (catches any write, present or future).
- Added as the fourth nav entry (`Pyrl | Runs | Eval | Ops`) and the seventh router in `app/main.py`.

## Task Commits

1. **Task 1: Add the side-effect-free /ops route and register it** — `fb23d26` (feat)
2. **Task 2: Render the ops panels, the alarm banner, and the fourth nav item** — `8dfa5f1` (feat)

## Files Created/Modified

- `app/routes/ops.py` — new `GET /ops` route; `PUMP_CADENCE_MINUTES = 30`; reads the five plan-21-02 facade functions in one guarded block; builds the template context (`pending_count`, `leased_count`, `oldest_due_pending_seconds`, `attempts_rows`, `max_attempts`, `dead_letter_rows`, `unaccounted_error_rows`, `pump_cadence_minutes`, `generated_at`).
- `app/templates/ops.html` — the as-of stamp, the conditional alarm banner, and four panels (depth, oldest-due-pending, attempts, dead-letter), each composed from the existing `.card`/`.metric-strip`/`table` classes.
- `app/templates/base.html` — added `<a href="/ops">Ops</a>` as the fourth nav entry.
- `app/static/style.css` — `.ops-asof`, `.ops-panels`, `.ops-bound`, `.ops-alarm-banner` (and its `a` rule), all composed from existing `var(--...)` tokens.
- `app/main.py` — `ops` added to the router import tuple; `app.include_router(ops.router)` as the seventh registration (2 lines changed).
- `tests/test_ops_route.py` — 19 hermetic tests: render/cold-start, route registration, context-keys-reach-the-template, per-panel content, alarm banner present/absent, nav order, as-of stamp, no-script/no-polling, the two-sided read-only contract, and the pump-cadence pin.

## Template Context Keys (for plan 21-11's human verification)

`pending_count`, `leased_count`, `oldest_due_pending_seconds`, `attempts_rows`, `max_attempts`, `dead_letter_rows`, `unaccounted_error_rows`, `pump_cadence_minutes`, `generated_at`.

**`PUMP_CADENCE_MINUTES = 30`** — read from `.github/workflows/pump.yml`'s `cron: "*/30 * * * *"`; pinned by `tests/test_ops_route.py::test_pump_cadence_minutes_pinned_to_workflow_cron`.

## Decisions Made

- **Split the plan's two tasks into two genuinely independent, passing commits** rather than landing one large commit at the end. Task 1's own `<behavior>` block requires the route to render `ops.html` and expose its context keys — both unfalsifiable without *some* template existing — so Task 1 ships a functional but visually minimal template (raw context values, no panels/nav/banner), and Task 2 replaces it with the full presentation the plan's `<action>` describes. Both commits pass `uv run pytest tests/test_ops_route.py -v` independently.
- **FastAPI 0.138.0's route-listing shape differs from the plan's literal verification one-liner.** `app.routes` now holds lazy `_IncludedRouter` wrappers instead of flat routes; the real `APIRoute` objects live on `.original_router.routes`. Confirmed this is a FastAPI-version artifact (not a registration defect) by exercising `/ops` end-to-end through `TestClient` and by manually walking `app.routes` for all seven registered routers. `tests/test_ops_route.py::test_ops_is_registered_exactly_once_as_a_get_route` recurses through `.original_router.routes` to reach concrete routes and asserts the same invariant the plan intended (`['/ops']`, exactly one `GET`).
- **The alarm banner's CSS deliberately does not reuse the pre-existing `.callout-error` class**, even though it is visually similar, because `.callout-error` predates this repo's design-token system and hardcodes its own hex colors — reusing it would not satisfy "styled with the existing `--danger` token" as a literal, checkable fact. `.ops-alarm-banner` references `var(--danger)`/`var(--danger-hover)`/`var(--surface)` directly instead.
- **Chose structural assertions (`no <form>`, no `<button>`) over substring checks (`"mute"`, `"dismiss"`) for the "no dismissal control" test**, because `"mute"` is a substring of the pre-existing `text-muted` CSS class used throughout the page — a naive substring check would have been a false-positive trap.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Two of the plan's own literal verification commands do not hold under this repo's pinned FastAPI version**
- **Found during:** Task 1's acceptance-criteria verification pass.
- **Issue:** `uv run python -c "from app.main import app; print(sorted({r.path for r in app.routes if getattr(r,'path','').startswith('/ops')}))"` printed `[]`, not `['/ops']`, against the installed `fastapi==0.138.0`. That version wraps every `include_router()` target in a lazy `_IncludedRouter` container; concrete routes live on `.original_router.routes`.
- **Fix:** Confirmed via `TestClient` (all seven routers, including `ops`, respond correctly end-to-end) that this is a version-shape change, not a registration bug. Wrote `_flatten_routes()` in `tests/test_ops_route.py` to recurse through `.original_router.routes` and assert the identical invariant (exactly one `/ops` GET route) the plan's one-liner intended.
- **Files modified:** `tests/test_ops_route.py`.
- **Verification:** `test_ops_is_registered_exactly_once_as_a_get_route` passes; manual `TestClient` walk confirms all seven routers (health, webhook, runs, dashboard, demo, pump, ops) are reachable.
- **Committed in:** `fb23d26` (Task 1 commit).

**2. [Rule 1 - Bug] YAML parses `pump.yml`'s bare `on:` key as the boolean `True`**
- **Found during:** Task 1, writing the cron-pinning test.
- **Issue:** `yaml.safe_load(...)["on"]` raised `KeyError: 'on'` — YAML 1.1 (which PyYAML implements) treats an unquoted top-level `on:` as the boolean `True`, a well-known GitHub Actions workflow parsing trap.
- **Fix:** `workflow.get("on", workflow.get(True))`, with an inline comment explaining the trap.
- **Files modified:** `tests/test_ops_route.py`.
- **Verification:** `test_pump_cadence_minutes_pinned_to_workflow_cron` passes.
- **Committed in:** `fb23d26` (Task 1 commit).

---

**Total deviations:** 2 auto-fixed (both Rule 1, both caught by this plan's own mandated verification steps before the relevant task commit).
**Impact on plan:** None on behavior or scope — both fixes make the plan's own stated acceptance criteria hold against the actual installed toolchain, rather than the plan's specific command syntax. No production code was affected; both fixes are test-only.

## Issues Encountered

None beyond the deviations documented above.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `/ops` is live, registered, side-effect-free, and hermetically tested; plan 21-11's human verification walk can use the template context keys and `PUMP_CADENCE_MINUTES` value recorded above.
- `app/db/repo/` is confirmed untouched by this plan (`git diff --stat <wave-1-base>..HEAD -- app/db/repo/` is empty) — no risk of collision with plan 21-07's concurrent work on `app/routes/health.py`, which this plan never touched.
- No blockers for the rest of phase 21.

---
*Phase: 21-durability-proofs-ops-view*
*Completed: 2026-07-20*

## Self-Check: PASSED

- FOUND: app/routes/ops.py
- FOUND: app/templates/ops.html
- FOUND: tests/test_ops_route.py
- FOUND: app/main.py
- FOUND: app/templates/base.html
- FOUND: app/static/style.css
- FOUND: .planning/phases/21-durability-proofs-ops-view/21-06-SUMMARY.md
- FOUND commit: fb23d26 (task 1)
- FOUND commit: 8dfa5f1 (task 2)
