---
phase: 13-module-structure-boundaries
plan: 03
subsystem: http
tags: [python, fastapi, module-split, monkeypatch, module-object-imports, AST-testing]

# Dependency graph
requires:
  - phase: 13-module-structure-boundaries (plan 02)
    provides: app/pipeline/delivery.py's deliver() + app/main.py's ONE
      top-level `from app.pipeline import delivery` integration point,
      which this plan relocates intact into app/routes/runs.py
provides:
  - "app/routes/ package -- five APIRouter modules by URL-prefix concern
    (webhook.py, runs.py, dashboard.py, demo.py, health.py) plus two shared
    modules (pipeline_glue.py, templating.py)"
  - "app/main.py trimmed to thin app assembly (16 lines): create app, mount
    static, include 5 routers"
  - "BOUND-01 promotions: seven bridge helpers promoted public in
    pipeline_glue.py (row_to_inbound, reply_sender_ok, finish_reply_resume,
    route_reply, resume_pipeline_bg, run_pipeline_bg, operator_resume_bg);
    demo allowlist constants promoted public in demo.py (DEMO_FIXTURES,
    DEMO_FIXTURE_DEFAULT_KEY, DEMO_OPERATOR_EMAIL, SEED_CONTACTS,
    SEED_BUSINESS_IDS)"
affects: [14-full-type-checking, 15-comment-hygiene]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-object imports at every router boundary (from app.routes import
      pipeline_glue) so monkeypatch.setattr(<module>, <fn>) seams retarget
      mechanically to the one owning module, never a bare-name import"
    - "Round-3 cross-AI review discipline applied proactively: promote a
      Form(default=...) signature-default constant in the SAME commit as the
      function using it, to avoid an import-time NameError"
    - "raising=True (the monkeypatch default) deliberately chosen over
      raising=False for background-task patches so a future rename fails
      loudly (AttributeError) instead of silently letting the real,
      unpatched function run against live LLM/gateway keys"

key-files:
  created:
    - app/routes/__init__.py
    - app/routes/templating.py
    - app/routes/pipeline_glue.py
    - app/routes/webhook.py
    - app/routes/runs.py
    - app/routes/dashboard.py
    - app/routes/demo.py
    - app/routes/health.py
  modified:
    - app/main.py
    - tests/test_webhook.py
    - tests/test_needs_operator.py
    - tests/test_reply_redelivery.py
    - tests/test_concurrency_proof.py
    - tests/test_webhook_dedup_race.py
    - tests/test_stuck_run_recovery.py
    - tests/test_health_schema.py
    - tests/test_demo_landing.py
    - tests/test_dashboard.py
    - tests/test_gateway.py
    - tests/test_ingest.py
    - tests/test_cr_regressions.py
    - tests/test_threading.py
    - tests/test_hitl.py

key-decisions:
  - "app/main.py is now 16 lines (well under the 40-line acceptance ceiling
    and even under the plan's own 15-30-line target) -- app assembly only:
    create app, mount static, include 5 routers."
  - "webhook.py's inbound() calls pipeline_glue.finish_reply_resume after its
    transactional reply classification, NEVER route_reply -- route_reply's
    one legitimate call site is simulate_reply in runs.py, matching the
    pre-split control flow exactly (verified via grep acceptance criteria)."
  - "DEMO_FIXTURE_DEFAULT_KEY (the Codex Round-2-confirmed-omitted constant)
    moved to demo.py in the SAME commit as demo_send_test, avoiding the
    import-time NameError the plan's objective called out."
  - "The three test_demo_landing.py raising=False dead-attribute patches on
    app.main._run_pipeline are fixed (not merely retargeted) to raising=True
    against app.routes.pipeline_glue.run_pipeline_bg -- a future rename now
    fails loudly instead of silently letting the real pipeline run against
    this repo's live LLM/gateway keys (T-13-14)."

requirements-completed: [STRUCT-01, STRUCT-04, BOUND-01]

# Metrics
duration: 65min
completed: 2026-07-10
---

# Phase 13 Plan 03: Split app/main.py into app/routes/ router modules Summary

**Split the 1,857-line `app/main.py` into `app/routes/` -- five APIRouter modules by URL-prefix concern (webhook/runs/dashboard/demo/health) plus two shared modules (pipeline_glue.py, templating.py) -- trimming main.py to 16 lines of thin app assembly, with all 14 test-coupling files retargeted and the full suite green at the exact pre-split baseline (612 passed, 51 skipped, 663 collected).**

## Performance

- **Duration:** 65 min
- **Started:** 2026-07-10T01:00 (approx, worktree init/merge)
- **Completed:** 2026-07-10T02:03:31Z
- **Tasks:** 2/2
- **Files modified:** 23 (8 created under app/routes/, 1 trimmed app/main.py, 14 test files retargeted)

## Accomplishments

- `app/main.py` trimmed from 1,857 lines to 16 lines: `FastAPI(title=...)`, static mount, five `app.include_router(...)` calls. No route handlers, no business helpers remain.
- Seven HTTP-to-orchestrator bridge helpers promoted to public names in `app/routes/pipeline_glue.py` (D-07): `row_to_inbound`, `reply_sender_ok`, `finish_reply_resume`, `route_reply`, `resume_pipeline_bg`, `run_pipeline_bg`, `operator_resume_bg` — all moved verbatim, imported via `from app.routes import pipeline_glue` (module-object import) everywhere so every monkeypatch seam retargets to one owning module.
- `app/routes/webhook.py`'s `inbound()` preserves the exact transactional reply-classification-then-`finish_reply_resume` control flow byte-for-byte; `route_reply` is called nowhere in this file (confirmed by acceptance-criteria grep) — its one legitimate caller, `simulate_reply`, moved to `runs.py`.
- `app/routes/runs.py` (the largest router) carries everything under `/runs*`: `approve` (with the already-correct `delivery.deliver` wiring from 13-02 relocated intact), `reject`, `resolve`, `retrigger`, `runs_list` (including its stranded-sweep block), `run_status`, `run_detail`, `paystub_pdf` (using `StreamingResponse`, not `FileResponse`), `simulate_reply`, plus `STALE_THRESHOLD`/`STALE_THRESHOLD_SECONDS`/`IN_FLIGHT_STATUSES` and `_build_alias_rationale_notes`.
- `app/routes/demo.py` owns the demo affordances (`demo_bind`, `demo_compose`, `demo_send_test`) plus all five promoted-public demo allowlist constants — including `DEMO_FIXTURE_DEFAULT_KEY` (the Codex Round-2-confirmed-omitted constant, moved in the same commit as `demo_send_test` to avoid an import-time `NameError`).
- `app/routes/dashboard.py` (`landing`, `eval_view`, `eval_chart`) is the only router importing `FileResponse`; `app/routes/health.py` carries the three health probes.
- `app/routes/templating.py` is the single shared `Jinja2Templates` instance + badge class/label filters, imported by every router that renders a template.
- All 14 test-coupling files retargeted, each verified in isolation before the full-suite run: `test_webhook.py`, `test_needs_operator.py`, `test_reply_redelivery.py`, `test_concurrency_proof.py`, `test_webhook_dedup_race.py`, `test_stuck_run_recovery.py`, `test_health_schema.py`, `test_demo_landing.py`, `test_dashboard.py`, `test_gateway.py`, `test_ingest.py`, `test_cr_regressions.py`, `test_threading.py`, `test_hitl.py`.
- The three `test_demo_landing.py` `raising=False` dead-attribute patches (Codex Round 2 HIGH, security-relevant per this plan's threat model T-13-14) are fixed — not merely retargeted — to `raising=True` against `app.routes.pipeline_glue.run_pipeline_bg`.
- Full suite green at the exact pre-split baseline: 612 passed, 51 skipped, 663 collected (matches wave 1/2's documented figures exactly). `ruff check .` clean across the whole repo, zero violations.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create app/routes/ package (five routers + pipeline_glue.py + templating.py), trim main.py** - `fa4146d` (feat)
2. **Task 2: Migrate the 14-file test-coupling census, verify full suite green** - `1eb828f` (test)

## Files Created/Modified

- `app/routes/__init__.py` — package docstring
- `app/routes/templating.py` — shared Jinja2Templates instance + badge filters
- `app/routes/pipeline_glue.py` — the seven promoted-public bridge helpers
- `app/routes/webhook.py` — `POST /webhook/inbound`
- `app/routes/runs.py` — everything under `/runs*` (largest router)
- `app/routes/dashboard.py` — `GET /`, `/eval`, `/eval/chart.svg`
- `app/routes/demo.py` — `POST /demo/bind`, `/demo/compose`, `/demo/send-test` + demo allowlist constants
- `app/routes/health.py` — `GET /health/live`, `/ready`, `/schema`
- `app/main.py` (modified) — thin app assembly, 16 lines
- 14 test files (modified) — import-path/patch-target/attribute-name retargets only, no assertion-value changes

## Decisions Made

- **`app/main.py` at 16 lines** — comfortably under both the plan's 15-30-line target and the 40-line acceptance ceiling.
- **Redundant inline `from app.db.supabase import get_connection` removed from `health_ready`** — the original `app/main.py` had this import both at module scope and redundantly inline inside the function body; the module-scope import alone is sufficient in `health.py`, so the inline duplicate was dropped as dead code (Rule 1 — no behavior change, `get_connection` resolves identically either way).
- **Kept all seven `pipeline_glue` helpers together in one file** (not split further) per the plan's explicit D-07 grouping — they form one cohesive HTTP-to-orchestrator bridge concern.
- **`operator_resume_bg`'s `RunStatus` import stays at module top-level** in `pipeline_glue.py` (not function-local like the original `_operator_resume`'s inline import) since `RunStatus` is already imported at module scope for other uses in this file — no behavior change, just avoids a redundant inline import.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `IS_signed`/unused-import lint findings during initial draft, and one E501/one import-sort violation in test files**
- **Found during:** Task 1 draft (unused `HTTPException`/`Request` imports in `webhook.py`/`demo.py`) and Task 2's final ruff sweep (`test_needs_operator.py` import ordering, `test_webhook.py` line length)
- **Issue:** `webhook.py` initially imported `HTTPException` (unused — `inbound()` never raises it directly); `demo.py` initially imported `Request` (unused — none of its three routes reference it). Separately, after retargeting `test_needs_operator.py`'s `IN_FLIGHT_STATUSES` import into two `from` statements, ruff's `I001` flagged the resulting import block as unsorted; retargeting a monkeypatch string literal in `test_webhook.py` produced a line over the 100-char limit.
- **Fix:** Removed the two unused imports; ran `ruff check --fix` for the import-sort violation; manually wrapped the long monkeypatch call across two lines.
- **Files modified:** `app/routes/webhook.py`, `app/routes/demo.py`, `tests/test_needs_operator.py`, `tests/test_webhook.py`
- **Verification:** `uv run ruff check .` reports zero violations repo-wide; full suite still green after the fixes.
- **Committed in:** `fa4146d` (Task 1, for the app/routes/ import fixes) and `1eb828f` (Task 2, for the test file fixes)

---

**Total deviations:** 1 auto-fixed (Rule 3, lint cleanup — no behavior change, caught before each task's commit)
**Impact on plan:** No scope creep, no assertion changes, no behavior changes. Purely lint hygiene caught during the plan's own verification steps.

## Issues Encountered

None beyond the deviation documented above.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `app/main.py`, `app/routes/webhook.py`, `runs.py`, `dashboard.py`, `demo.py`, `health.py`, `pipeline_glue.py`, `templating.py` are all ready for Phase 14's full mypy adoption pass — eight smaller, more tractable modules instead of one 1,857-line file.
- This completes the Phase 13 god-file split trio: `app/db/repo.py` (Plan 01) → `app/pipeline/orchestrator.py` (Plan 02) → `app/main.py` (this plan). All three land under the CI protection established in Phase 12.
- No blockers.

## TDD Gate Compliance

Not applicable — this plan's tasks are `type="auto"` without `tdd="true"`; the plan-level frontmatter is `type: execute`, not `type: tdd`.

## Self-Check: PASSED

- FOUND: app/routes/__init__.py
- FOUND: app/routes/templating.py
- FOUND: app/routes/pipeline_glue.py
- FOUND: app/routes/webhook.py
- FOUND: app/routes/runs.py
- FOUND: app/routes/dashboard.py
- FOUND: app/routes/demo.py
- FOUND: app/routes/health.py
- FOUND commit: fa4146d
- FOUND commit: 1eb828f

---
*Phase: 13-module-structure-boundaries*
*Completed: 2026-07-10*
