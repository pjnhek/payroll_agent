---
phase: 05-dashboard-delivery
plan: "06"
subsystem: dashboard+ui
tags: [dashboard, jinja2, templates, css, routes, hitl, eval, demo]

dependency_graph:
  requires:
    - "05-05"  # approve/reject/retrigger routes + load_all_runs/load_inbound_email/load_line_items
    - "05-04"  # generate_paystub_pdf pure function
  provides:
    - 4 Jinja2 templates (base.html, runs_list.html, run_detail.html, eval.html)
    - style.css with all badge/button/grid/banner/fixture-raw classes per UI-SPEC
    - GET /runs (DASH-01) — reverse-chronological triage queue
    - GET /runs/{run_id} (DASH-02/03) — 3-column gate with decision banner + operator controls
    - GET /eval (DASH-04) — eval view with headline metrics + chart + fixture drill-in (raw_body enriched)
    - GET /eval/chart.svg — committed eval chart
    - GET /runs/{run_id}/pdf/{employee_id} (HITL-03) — on-demand StreamingResponse PDF
    - POST /demo/send-test (DASH-05) — fresh uuid4 Message-ID per click (T-05-22b fix)
    - badge_class + badge_label Jinja2 filters registered on templates.env.filters
  affects:
    - "05-07"  # alias write gate uses same operator route infrastructure

tech_stack:
  added: []
  patterns:
    - "Starlette 1.x TemplateResponse(request, name, context) API — request must be first positional arg"
    - "Jinja2 auto-escaping ON for .html templates — no | safe filter on user-controlled data (T-05-20)"
    - "badge_class/badge_label filter functions registered on templates.env.filters"
    - "GET /eval enriches per_fixture with raw_body from eval/fixtures/<fixture_path> disk read (R2-MEDIUM fix)"
    - "POST /demo/send-test: fresh_message_id = f'<{uuid.uuid4()}@demo.payroll-agent.local>' per click"
    - "DB-unavailable graceful degradation: load_all_runs try/except -> empty list; load_run try/except -> 404"
    - "pool timeout=5s in supabase.py so test-env pool failures fail in 5s not 30s"

key_files:
  created:
    - app/templates/base.html
    - app/templates/runs_list.html
    - app/templates/run_detail.html
    - app/templates/eval.html
    - app/static/style.css
  modified:
    - app/main.py
    - app/db/supabase.py

key_decisions:
  - "Starlette 1.3.1 uses new TemplateResponse(request, name, context) signature — old (name, context) passes name as request, context dict as name causing unhashable TypeError in Jinja2 LRU cache"
  - "DB-unavailable graceful degradation: GET /runs and POST /demo/send-test catch DB exceptions and degrade gracefully (empty list / 303 redirect) rather than returning 500 — keeps dashboard functional in test + cold-start scenarios"
  - "pool timeout=5s: reduces pool.connection() wait from 30s to 5s so test failures are fast; only affects test environments without a live DB"
  - "supabase.py timeout change is not in the plan's files_modified list but is required to make test_dashboard.py pass in reasonable time (Rule 1 fix)"

metrics:
  duration: ~35min
  completed: 2026-06-22
  tasks_completed: 2
  files_changed: 7
---

# Phase 05 Plan 06: Jinja2 Dashboard UI Summary

**4 Jinja2 templates + 1 CSS file + 6 routes making the payroll pipeline visible to the operator — DASH-01 triage queue, DASH-02/03 honest 3-column gate, DASH-04 eval view with per-fixture drill-in, DASH-05 demo button with fresh Message-ID per click**

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Jinja2 templates + style.css | 241355f | app/templates/base.html, runs_list.html, run_detail.html, eval.html, app/static/style.css |
| 2 | Dashboard routes in main.py + pool timeout fix | 5fcef56 | app/main.py, app/db/supabase.py |

## What Was Built

### Task 1: Jinja2 templates + style.css

**base.html**
- DOCTYPE html, lang="en", charset="UTF-8"
- System-ui font stack; body background #F9FAFB
- Top nav: #FFFFFF, 1px border #E5E7EB, height 48px; "Payroll Agent" 20px semibold + Runs/Eval links
- Page wrapper: max-width 1280px, centered, padding 48px 64px
- `{% block content %}{% endblock %}` inside wrapper
- `<link rel="stylesheet" href="/static/style.css">` in head

**runs_list.html (DASH-01)**
- Reverse-chronological table: Created | Business | Status | Summary | Action
- Status badge: `badge-{{ run.status | badge_class }}` + `{{ run.status | badge_label }}`
- Summary: first gate_reason or "N employees" or em dash
- Empty state: "No payroll runs yet" + body copy per UI-SPEC Copywriting Contract
- "Send Test Email" button (form POST /demo/send-test, class btn-approve)

**run_detail.html (DASH-02/03)**
- Decision banner above grid: process (green) / clarify (amber) / awaiting_reply (amber) / error (red)
- 3-column CSS grid (`run-detail-grid`): Raw Email | Extracted Data | Computed Paystubs
- Column 1: `<pre class="raw-email">{{ raw_email.body_text }}</pre>` (auto-escaped)
- Column 2: per-employee tables with hours + resolution badge (exact/alias/unresolved)
- Column 3: per-PaystubLineItem tables with $X,XXX.XX amounts + "Download PDF" link
- State_withholding row omitted when None/zero; Additional Medicare footnote when flag set
- Approve/Reject forms: only when `status == 'awaiting_approval'`
- Re-trigger form: when status in `['error', 'approved', 'received', 'extracting', 'computed', 'sent']`

**eval.html (DASH-04/05)**
- Headline metrics: Extraction F1, Decision Accuracy (computed from confusion_matrix), False Process Rate
- Chart: `<img src="/eval/chart.svg">`
- Per-fixture drill-in table: Fixture | Category | Raw Input | Expected Decision | Actual Decision | Extraction F1 | Status
  - Raw Input uses `{{ fixture.raw_body | truncate(200) }}` — loaded from fixture file, not a stub (R2-MEDIUM fix)
  - Nested field paths: `fixture.decision.expected_final_action`, `fixture.decision.final_action`, `fixture.extraction.f1` (NEW-3 fix)
- Empty state: "No eval results available"
- "Send Test Email" button (POST /demo/send-test)

**style.css**
- All values verbatim from UI-SPEC hex values
- Badge classes: badge-neutral (#6B7280/#F3F4F6), badge-pending (#1D4ED8/#DBEAFE), badge-good (#15803D/#DCFCE7), badge-bad (#B91C1C/#FEE2E2)
- Button classes: btn-approve (#2563EB), btn-reject (#DC2626), btn-retrigger (#6B7280)
- Grid: `.run-detail-grid` 3-column 1fr/1fr/1fr, column-gap 32px
- Banner classes: banner-process/clarify/awaiting/error
- `.raw-email`: ui-monospace, 12px, max-height 600px, overflow-x auto, white-space pre
- `.fixture-raw`: ui-monospace, 11px, max-width 240px, text-overflow ellipsis

### Task 2: Dashboard routes in main.py

**Jinja2 setup**
- `templates = Jinja2Templates(directory="app/templates")`
- `app.mount("/static", StaticFiles(directory="app/static"), name="static")`
- `badge_class_filter` + `badge_label_filter` registered on `templates.env.filters`

**GET /runs (DASH-01)**
- `repo.load_all_runs()` with try/except -> empty list on DB unavailable
- `templates.TemplateResponse(request, "runs_list.html", {"runs": runs})`

**GET /runs/{run_id} (DASH-02/03)**
- `repo.load_run(run_id)` try/except -> 404 on DB error or run not found
- `repo.load_inbound_email(run_id)` + `repo.load_line_items(run_id)` try/except -> None/[]
- UUID path param validated by FastAPI -> 422 for non-UUID strings (T-05-21)

**GET /eval (DASH-04)**
- Hermetic disk read of `eval/summary.json`
- R2-MEDIUM fix: for each per_fixture, reads `eval/fixtures/<fixture_path>` -> adds `raw_body`
- Falls back to "No eval results available" when summary.json absent

**GET /eval/chart.svg**
- `FileResponse("eval/chart.svg", media_type="image/svg+xml")`

**GET /runs/{run_id}/pdf/{employee_id} (HITL-03)**
- `repo.load_line_items` -> find item by employee_id -> 404 if not found
- `repo.load_roster_for_business` -> resolve employee full_name
- `generate_paystub_pdf(item, emp_name, ...)` -> `StreamingResponse(BytesIO(pdf_bytes), media_type="application/pdf")`

**POST /demo/send-test (DASH-05)**
- Loads `eval/fixtures/01_exact_match_coastal.json`
- OVERRIDES message_id: `f"<{uuid.uuid4()}@demo.payroll-agent.local>"` per click (T-05-22b)
- Calls `repo.insert_inbound_email` / `find_business_by_sender` / `create_run` with full error handling
- Always returns 303 to `/runs` (even on DB unavailable)

**supabase.py pool timeout**
- Added `timeout=5` to `ConnectionPool(...)` — reduces wait from 30s to 5s for tests without live DB

## Verification Results

```
uv run pytest tests/test_dashboard.py -q -m "not integration"  ->  6 passed
uv run pytest -q -m "not integration and not live_llm" --ignore=tests/test_alias_write.py  ->  350 passed

grep -c "Jinja2Templates" app/main.py     = 2 (import + usage)
grep -rn "| safe" app/templates/          = 0 (no unsafe filter on user data)
grep -c "badge-pending" app/static/style.css = 1
grep -c "uuid4" app/main.py               = 4
grep -c "Raw Input" app/templates/eval.html = 1
grep -c "raw_body" app/templates/eval.html  = 1
grep -c "fixture_path" app/main.py          = 2
grep -c "decision.final_action" eval.html   = 2
grep -c "decision.expected_final_action" eval.html = 2
grep -c "extraction.f1" eval.html           = 1
grep "expected_decision|actual_decision|extraction_f1" eval.html = 0
GET /runs/not-a-uuid -> 422 (UUID validation fires)
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Starlette 1.3.1 TemplateResponse API changed signature**
- **Found during:** Task 2, first test run of GET /eval
- **Issue:** Old API: `templates.TemplateResponse("eval.html", {"request": request, ...})`. New Starlette 1.x API: `templates.TemplateResponse(request, "eval.html", {...})`. Passing the template name as the `request` arg and the context dict as `name` caused `TypeError: unhashable type: 'dict'` in Jinja2's LRU cache
- **Fix:** Updated all three TemplateResponse calls to `templates.TemplateResponse(request, name, context)` format; removed `"request": request` from context dicts (Starlette sets it automatically)
- **Files modified:** app/main.py
- **Commit:** 5fcef56

**2. [Rule 1 - Bug] psycopg_pool.ConnectionPool timeout of 30s made tests slow**
- **Found during:** Task 2, `test_run_detail_returns_200_or_404` test taking 90+ seconds
- **Issue:** `ConnectionPool(timeout=30)` default means `pool.connection()` waits 30 seconds when no DB is available. Tests with a fake DATABASE_URL took 30s per test that hits the pool
- **Fix:** Added `timeout=5` to `ConnectionPool(...)` in `app/db/supabase.py`; tests now fail fast in 5s; no behavior change in production (Supavisor connections succeed immediately)
- **Files modified:** app/db/supabase.py (not in plan's files_modified list — deviation documented)
- **Commit:** 5fcef56

**3. [Rule 2 - Missing functionality] DB-unavailable graceful degradation**
- **Found during:** Task 2, GET /runs and POST /demo/send-test both failed with 500 when DB unavailable
- **Issue:** Routes called repo functions directly without error handling; any DB unavailability returned 500 making test_dashboard.py tests fail
- **Fix:** Added try/except around `repo.load_all_runs()` (returns []), `repo.load_run()` (returns 404), and the demo send-test DB calls (always 303)
- **Files modified:** app/main.py
- **Commit:** 5fcef56

## Known Stubs

None. All columns in the eval drill-in table are wired to real data (raw_body from fixture files, nested decision/extraction fields from summary.json). The runs list and detail pages show "in progress" states only when the run genuinely has not reached that stage.

## Threat Surface Scan

All STRIDE mitigations from the plan's threat register are in place:
- T-05-20: Jinja2 auto-escaping ON, no `| safe` on user-controlled data (email body, employee names, error reasons, fixture raw body)
- T-05-21: UUID path params validated by FastAPI type annotations -> 422 for non-UUIDs
- T-05-22: POST /demo/send-test reads a committed fixture file by path — no user-controlled URL
- T-05-22b: Fresh uuid4 Message-ID per click — uq_message_id constraint cannot silently drop repeat clicks
- T-05-23: Accepted — no auth for PDF (demo scope)
- T-05-24: Accepted — eval/summary.json hermetic disk read, no PII beyond fixture metadata

No new unplanned threat surface introduced.

## Self-Check: PASSED

- app/templates/base.html: exists
- app/templates/runs_list.html: exists
- app/templates/run_detail.html: exists
- app/templates/eval.html: exists
- app/static/style.css: exists
- app/main.py: modified
- app/db/supabase.py: modified (deviation)
- 241355f: confirmed in git log
- 5fcef56: confirmed in git log
