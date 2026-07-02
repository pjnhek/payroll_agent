---
phase: 08-data-layer-hygiene-diagnostics
plan: 03
subsystem: pipeline
tags: [orchestrator, error-boundaries, pii-redaction, dashboard, jinja2, threading, live-db-migration]

# Dependency graph
requires:
  - phase: 08-data-layer-hygiene-diagnostics
    provides: "08-01 schema DDL (payroll_runs.error_detail column, 3 hot-path indexes, 10-value status CHECK swap) — applied live at this plan's blocking checkpoint"
  - phase: 08-data-layer-hygiene-diagnostics
    provides: "08-02 record_run_error(conn, *, detail_exc=, stage=, roster=) extended signature + load_all_runs summary_gate_reason/employee_count aliases — wired into call sites/templates by this plan"
provides:
  - "_run owns its own try/except (HIGH #1 fix) — the error path sees the roster _run already loaded; run_pipeline is a thin, non-raising delegator"
  - "All 3 record_run_error call sites pass detail_exc=/stage= (pipeline + resume also roster=): a real production failure now writes a non-NULL, PII-scrubbed error_detail"
  - "RUN_COLS includes error_detail — load_run's SELECT returns it to every caller including the run_detail dashboard route"
  - "run_detail.html conditional error-detail second line (autoescape intact); runs_list.html Summary cell on the SQL-computed aliases"
  - "app/db/supabase.py thread-safe pool singleton (WR-02 double-checked locking)"
  - "Live Supabase schema migrated + human-verified: error_detail column, 3 indexes, contact_email UNIQUE coverage, 10-value status CHECK"
affects: [09-transaction-surgery]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Error-wrap boundary lives INSIDE the function that loads the data its error path needs (moved from run_pipeline into _run) — scope-correct by construction, not by roster=None initialization in the wrong scope"
    - "Behavioral argument-flow spy test (wrap-don't-replace the fake) proving the RUNTIME kwargs a money-adjacent call receives, not just the call-site source text (R2-2, Phase 7.5 lesson)"
    - "Double-checked locking for a lazy module-level singleton (threading.Lock + re-check under the lock)"

key-files:
  created: []
  modified:
    - app/pipeline/orchestrator.py
    - app/main.py
    - app/db/repo.py
    - app/templates/run_detail.html
    - app/templates/runs_list.html
    - app/db/supabase.py
    - tests/conftest.py
    - tests/test_threading.py
    - tests/test_dashboard.py
    - tests/test_orchestrator_states.py

key-decisions:
  - "HIGH #1 fixed at the root: the try/except moved INTO _run (where roster lives), not a roster=None patch in run_pipeline's scope — run_pipeline's never-raises external contract preserved exactly (app/main.py's _run_pipeline catch-all unchanged)"
  - "approve()'s delivery boundary passes no roster= — approve() never loads one; roster=None is correct by design (D-8-01b), not a gap"
  - "run_detail.html's error-detail line reuses the existing banner-divider class instead of inventing new global CSS; Jinja2 autoescape stays ON (T-8-08)"
  - "InMemoryRepo.record_run_error no-ops the new kwargs (real scrub logic is proven by 08-02's unit tests against the real repo); InMemoryRepo.load_all_runs computes the real alias contract so route-level fakes keep exercising runs_list.html's new branches (review fix #7)"

patterns-established:
  - "R2-2 spy-test pattern: monkeypatch the module-under-test's repo.record_run_error with a closure that captures kwargs then delegates to the fake — proves argument FLOW, keeps the normal error path intact"

requirements-completed: [OPS2-01, OPS2-02]

# Metrics
duration: ~25min (Task 1) + human checkpoint (Task 2)
completed: 2026-07-02
---

# Phase 8 Plan 03: Wiring + Live-DB Checkpoint Summary

**Every error boundary now writes a roster-scrubbed, stage-prefixed `error_detail` (with the HIGH #1 roster-scope gap fixed at the root by moving the error-wrap into `_run`), the dashboard renders it end-to-end, and the live Supabase schema was migrated and human-verified at the blocking checkpoint — schema strictly before code, per the deploy-order gate.**

## Performance

- **Duration:** ~25 min (Task 1 execution) + blocking human checkpoint (Task 2)
- **Completed:** 2026-07-02
- **Tasks:** 2/2 (Task 2 = human-verified live-DB checkpoint, approved)
- **Files modified:** 10

## Accomplishments

- **HIGH #1 root fix:** `_run` now owns its own try/except — `roster = None` is the first statement, reassigned after the real `load_roster_for_business` call, so `_run`'s own except block calls `repo.record_run_error(run_id, reason, detail_exc=exc, stage="pipeline", roster=roster)` with whatever the happy path had already loaded. `run_pipeline` is a thin, non-raising delegator (no try/except of its own); its external never-raises contract is unchanged and `app/main.py`'s `_run_pipeline` catch-all needed no edit. Stale docstring updated (`needs_clarification` → `awaiting_reply`).
- **resume_pipeline** gained the simpler top-of-try `roster = None` guard; its except block now passes `detail_exc=exc, stage="resume", roster=roster` (roster guaranteed bound — None before the load line, the real Roster after).
- **approve()** (delivery boundary, `app/main.py`) enriched with `detail_exc=exc, stage="delivery"` — no `roster=` by design (D-8-01b).
- **RUN_COLS** now includes `error_detail` immediately after `error_reason`, with a comment mirroring the CR-02 `updated_at` rationale — closing the key-link gap where 08-02's write was invisible to every `load_run` caller.
- **Templates:** `run_detail.html`'s error banner keeps the byte-identical `error_reason` line and adds `{% if run.error_detail %}<div class="banner-divider">{{ run.error_detail }}</div>{% endif %}` (autoescape intact, existing CSS class reused). `runs_list.html`'s Summary cell switched to `summary_gate_reason` / `employee_count` (no `run.decision.gate_reasons` / `run.extracted_data.employees` remain in the cell).
- **WR-02:** `get_pool()` guarded by `threading.Lock()` double-checked locking — outer fast-path check, inner re-check under the lock before constructing the `ConnectionPool`.
- **Test doubles:** `InMemoryRepo.record_run_error` and `test_threading.py`'s fake both accept the new `conn`-positional-then-keyword-only shape; `InMemoryRepo.load_all_runs` computes the same two aliases as the real SQL (jsonb_typeof-style guard mirrored: non-list `employees` degrades to 0); `create_run` initializes `error_detail: None` for shape parity.
- **Integration proof:** `test_run_detail_renders_error_detail_end_to_end` scripts a full RUN_COLS row through the REAL `load_run` (asserting `error_detail` in the actual SQL text via `fake_conn.all_sql()`), then feeds that same dict through the real route + template and asserts the scrubbed text reaches the rendered HTML.
- **R2-2 behavioral spy test:** `test_first_run_failure_after_roster_load_passes_nonnull_roster_to_record_run_error` wraps (not replaces) the fake's `record_run_error`, forces an extract-stage failure (fires strictly after the roster-load line), and asserts the captured runtime kwargs: `stage == "pipeline"`, `roster is not None`, `isinstance(roster, Roster)`, `len(roster.employees) > 0` — argument-flow proof, not a source grep.
- **Task 2 (blocking checkpoint, human-approved):** live Supabase schema migrated via `uv run python -m app.db.bootstrap` against the pooler (`aws-1-us-west-2.pooler.supabase.com:6543`), with the deploy-order gate honored (schema applied while Task 1's code was still unmerged/undeployed).

## Task Commits

1. **Task 1: HIGH #1 restructure + 3 wired call sites + RUN_COLS + templates + pool lock + test doubles + integration proof + R2-2 spy test** — `e1e3919` (feat)
2. **Task 2: Live-DB schema apply (blocking human-verify checkpoint)** — no code commit; human-executed migration, evidence below

## Task 2 Checkpoint Evidence (human-approved)

All 6 SQL checks passed against the live Supabase database, schema-before-code order honored:

1. Pre-migration guard: `SELECT count(*) FROM payroll_runs WHERE status = 'needs_clarification'` returned **0** ✓
2. `uv run python -m app.db.bootstrap` completed against `aws-1-us-west-2.pooler.supabase.com:6543` — "Bootstrap complete. Tables applied." ✓
3. All 3 new indexes exist: `idx_email_messages_run_direction_state`, `idx_payroll_runs_created_at`, `idx_payroll_runs_status` ✓
4. `businesses_contact_email_key` UNIQUE index confirmed present — no duplicate index created (D-8-09) ✓
5. `error_detail | text | YES` column confirmed via information_schema ✓
6. `payroll_runs_status_check` lists exactly the 10 remaining values; `needs_clarification` absent ✓
7. Full hermetic suite green post-migration on the main tree (pre-merge of Task 1): 513 passed, 36 skipped ✓

**Post-merge follow-ups (outside this plan's scope, sequenced by the deploy-order gate):**
- Step 8: deploy/restart Task 1's code against the now-migrated environment (after this branch merges to master and the user pushes/deploys to Render).
- Step 9: deterministic dashboard verification on the deployed service — `UPDATE` a run to `status='error'` with a test `error_detail`, confirm both banner lines render on `/runs/{id}`, then revert.
- Per D-8-11 (recorded in the plan's `<done>`): at phase close, update REQUIREMENTS.md's OPS2-02 wording from "an index on businesses.contact_email" to "hot path verified index-covered by the existing UNIQUE constraint."

## Files Created/Modified

- `app/pipeline/orchestrator.py` — `_run` owns its own try/except (HIGH #1); `run_pipeline` thin delegator; `resume_pipeline` roster guard + enriched except; stale docstring fixed
- `app/main.py` — `approve()` delivery boundary passes `detail_exc`/`stage="delivery"`
- `app/db/repo.py` — `RUN_COLS` includes `error_detail` (+ rationale comment)
- `app/templates/run_detail.html` — conditional error-detail second line, autoescaped
- `app/templates/runs_list.html` — Summary cell on `summary_gate_reason`/`employee_count`
- `app/db/supabase.py` — `threading.Lock()` double-checked pool singleton (WR-02)
- `tests/conftest.py` — `InMemoryRepo.record_run_error` new kwargs; `load_all_runs` aliases (review fix #7); `create_run` error_detail key
- `tests/test_threading.py` — fake `record_run_error` accepts new kwargs
- `tests/test_dashboard.py` — `test_run_detail_renders_error_detail_end_to_end` (DB column → RUN_COLS/load_run → template key link)
- `tests/test_orchestrator_states.py` — R2-2 behavioral spy test

## Decisions Made

- Followed the plan's HIGH #1 restructure exactly: error-wrap moved into `_run` (scope-correct), not a wrong-scope `roster=None` patch. `run_pipeline`'s docstring documents the delegation.
- `run_detail.html` reuses the existing `banner-divider` class per the plan's instruction not to invent new global CSS.
- Pre-existing ruff F401 warnings in `tests/test_dashboard.py` (unused imports at lines untouched by this plan) were left alone per the scope boundary — logged here, not fixed.

## Deviations from Plan

None — plan executed exactly as written. One additive detail beyond the letter of the plan: `InMemoryRepo.create_run` also initializes `error_detail: None` so the fake's run-dict shape stays consistent with the extended `RUN_COLS` (shape parity, same spirit as the record_run_error fake update).

## Issues Encountered

None. All acceptance-criteria greps passed on first verification; full hermetic suite green in the worktree: **514 passed, 37 skipped** (baseline 502 passed / 37 skipped from 08-02 — the delta is this plan's 2 new tests plus existing suite growth; zero regressions).

## User Setup Required

Completed at the Task 2 checkpoint — the live Supabase schema apply was executed and verified by the human (evidence above). Remaining: post-merge deploy of Task 1's code (step 8) and the deployed-dashboard render check (step 9), both sequenced after this branch merges.

## Next Phase Readiness

- All Phase 8 logic (08-01 schema, 08-02 helpers, 08-03 wiring) is now live end-to-end at the code level; the live DB schema already has every column/index/CHECK the code needs, so the code deploy can happen at any time (deploy-order gate satisfied in the safe direction).
- Phase 09 (transaction surgery) can build on the thread-safe pool singleton and the fully-wired error diagnostics without touching these files' contracts.

## Self-Check: PASSED

- FOUND: app/pipeline/orchestrator.py
- FOUND: app/main.py
- FOUND: app/db/repo.py
- FOUND: app/templates/run_detail.html
- FOUND: app/templates/runs_list.html
- FOUND: app/db/supabase.py
- FOUND: tests/conftest.py
- FOUND: tests/test_threading.py
- FOUND: tests/test_dashboard.py
- FOUND: tests/test_orchestrator_states.py
- FOUND commit e1e3919 (Task 1)

---
*Phase: 08-data-layer-hygiene-diagnostics*
*Completed: 2026-07-02*
