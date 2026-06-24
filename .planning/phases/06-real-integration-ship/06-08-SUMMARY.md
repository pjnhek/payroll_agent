---
phase: 06-real-integration-ship
plan: "08"
subsystem: ui
tags: [fastapi, jinja2, psycopg, record-only, demo, tdd]

# Dependency graph
requires:
  - phase: 06-real-integration-ship
    provides: schema.sql, repo.py, orchestrator.py, main.py foundation, seed data

provides:
  - GET / landing page with business picker, roster table, composer form, Path-2 proof section
  - POST /demo/compose: routes by stable seed UUID, creates record_only=True run, fires real pipeline
  - POST /demo/bind: writes demo_sender_bindings for operator email → business (Path-2 arming)
  - record_only flag on payroll_runs: compose-created runs skip Resend, write synthetic outbound rows
  - Additive find_business_by_sender: contact_email first, then demo_sender_bindings fallback
  - load_thread_messages: conversation thread view in run_detail
  - list_businesses, get_demo_binding, bind_demo_business repo helpers
  - run_detail extended with alias-rationale notes and conversation thread

affects:
  - 06-05 (Path-2 binding runbook uses demo_sender_bindings, no contact_email mutation)
  - 06-07 (demo video asset slot in index.html)
  - future plans needing thread view or record-only pattern

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "record_only flag: compose-created runs write synthetic outbound rows, skip Resend — HIGH-1"
    - "HIGH-2 ordering: get_record_only_flag AFTER set_alias_candidates + body composition in _clarify"
    - "Additive sender lookup: demo_sender_bindings fallback AFTER contact_email check (never mutates businesses table)"
    - "LOW-6: record_only=True passed directly to create_run, no separate set_record_only call"
    - "Seed UUID routing: /demo/compose resolves business_id from _SEED_BUSINESS_IDS dict, no DB lookup by sender"
    - "DEMO_OPERATOR_EMAIL hardcoded constant, never user-supplied (T-06-08-02)"
    - "No |safe filter on any user-originated or DB-stored strings in templates"

key-files:
  created:
    - app/templates/index.html
    - tests/test_demo_landing.py
  modified:
    - app/db/schema.sql
    - app/db/repo.py
    - app/pipeline/orchestrator.py
    - app/main.py
    - app/templates/run_detail.html
    - tests/conftest.py
    - tests/test_alias_write.py
    - tests/test_cr_regressions.py
    - tests/test_llm_client.py
    - app/llm/client.py

key-decisions:
  - "HIGH-2 ordering: record_only check in _clarify placed AFTER alias-candidate capture AND body composition — protects Beat 3 alias learning on in-app runs"
  - "Additive demo_sender_bindings: operator email mapped to business without touching businesses.contact_email — decouples demo identity from live identity"
  - "LOW-6: record_only=True passed directly to create_run — eliminates separate set_record_only call at compose time"
  - "Seed UUID routing: /demo/compose bypasses find_business_by_sender entirely for Path-1 (in-app) runs"
  - "pre-existing regression fix: mock_llm fixture stubs DATABASE_URL to satisfy Settings validation in worktrees; _resolve_tier validates tier before get_settings()"

patterns-established:
  - "record_only pattern: flag on run row controls outbound path at _clarify and _deliver; steps 8-10 (alias write + SENT + RECONCILED) run unconditionally"
  - "Worktree test isolation: mock_llm fixture must stub DATABASE_URL when no .env is present"

requirements-completed: []

# Metrics
duration: 90min
completed: 2026-06-23
---

# Phase 06 Plan 08: Demo Landing — Interactive Self-Serve Compose Surface Summary

**Self-serve demo surface: GET / landing with business picker + composer, POST /demo/compose fires real pipeline as record_only run (no Resend), run_detail shows conversation thread and alias-rationale notes**

## Performance

- **Duration:** ~90 min
- **Started:** 2026-06-23T20:00:00Z
- **Completed:** 2026-06-23T21:30:00Z
- **Tasks:** 2 TDD tasks (RED + Task 1 GREEN + Task 2 GREEN)
- **Files modified:** 11

## Accomplishments

- `record_only` flag on `payroll_runs` and `demo_sender_bindings` table added to schema.sql (idempotent DDL)
- Seven new repo helpers: `list_businesses`, `bind_demo_business`, `get_demo_binding`, `set_record_only`, `get_record_only_flag`, `load_thread_messages`, plus `find_business_by_sender` and `create_run` patched
- `_clarify` and `_deliver` both have HIGH-1 record-only branches — compose-created runs write synthetic outbound rows without calling Resend
- HIGH-2 ordering: `get_record_only_flag` check is placed AFTER `set_alias_candidates` and `compose_clarification` in `_clarify` — Beat 3 alias learning works on in-app runs
- `GET /` landing: business picker with roster table, composer form (POST /demo/compose), Path-2 proof section, armed-business display
- `POST /demo/compose`: validates against `_SEED_CONTACTS` allowlist, resolves `business_id` from `_SEED_BUSINESS_IDS` (no DB sender lookup), creates run with `record_only=True`, fires real pipeline
- `POST /demo/bind`: writes `demo_sender_bindings` for operator email; never mutates `businesses.contact_email`
- `run_detail` extended with alias-rationale notes and conversation thread view
- 25/25 new tests pass; 436/436 total mocked suite passes (0 failures)

## Task Commits

1. **RED (failing tests)** - `964a9c6` (test)
2. **Task 1 GREEN (schema + repo)** - `ec331ab` (feat)
3. **Task 2 GREEN (orchestrator + main + templates + regression fixes)** - `233e51d` (feat)

## Files Created/Modified

- `app/db/schema.sql` - `record_only` column on `payroll_runs` + `demo_sender_bindings` table (idempotent DDL)
- `app/db/repo.py` - patched `find_business_by_sender` (additive fallback), `create_run` (record_only param), 6 new helpers
- `app/pipeline/orchestrator.py` - record-only branches in `_clarify` and `_deliver` (HIGH-1, HIGH-2 ordering)
- `app/main.py` - `GET /`, `POST /demo/compose`, `POST /demo/bind` routes; `_build_alias_rationale_notes` helper; extended `run_detail`
- `app/templates/index.html` - landing page (created)
- `app/templates/run_detail.html` - alias-rationale + thread view + secondary simulate-reply form
- `app/llm/client.py` - `_resolve_tier` validates tier before `get_settings()` (pre-existing bug fix)
- `tests/conftest.py` - `mock_llm` stubs `DATABASE_URL`; `InMemoryRepo` 5 new methods + `create_run` `record_only` param
- `tests/test_demo_landing.py` - 25 new tests (created)
- `tests/test_alias_write.py` - patch `get_record_only_flag=False` for direct `_clarify` callers
- `tests/test_cr_regressions.py` - patch `get_record_only_flag=False` for direct `_deliver` callers
- `tests/test_llm_client.py` - `_set_tier_env` stubs `DATABASE_URL`

## Decisions Made

- HIGH-2 ordering: `record_only` check in `_clarify` after alias capture and body composition — Beat 3 protection (in-app runs must capture the alias before the record-only branch returns early)
- Additive `demo_sender_bindings` table: operator email maps to business without touching `businesses.contact_email` — decouples demo identity from live identity, matches Path-2 runbook
- LOW-6: `record_only=True` passed directly to `create_run` at `/demo/compose` — no separate `set_record_only` call at compose time
- Seed UUID routing: `/demo/compose` resolves `business_id` from `_SEED_BUSINESS_IDS` dict, bypassing `find_business_by_sender` entirely for Path-1 runs
- `DEMO_OPERATOR_EMAIL = "pjnhek@gmail.com"` hardcoded constant — never user-supplied

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Pre-existing regression: mock_llm fixture missing DATABASE_URL stub**
- **Found during:** Task 2 GREEN (first mocked suite run in worktree)
- **Issue:** `mock_llm` fixture patches `app.llm.client.OpenAI` but `_resolve_tier()` calls `get_settings()` before constructing `OpenAI`. In a worktree without a `.env` file, `Settings()` raises `ValidationError: database_url`. This caused 35 pre-existing test failures in `test_orchestrator_states.py`, `test_threading.py`, `test_webhook.py`, etc.
- **Fix:** Added `monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")` and `get_settings.cache_clear()` calls to `mock_llm` fixture; changed `return` to `yield` for teardown. Also added `DATABASE_URL` stub to `_set_tier_env` in `test_llm_client.py`.
- **Files modified:** `tests/conftest.py`, `tests/test_llm_client.py`
- **Verification:** `uv run pytest -q -m "not integration and not live_llm"` → 436 passed, 0 failed
- **Committed in:** `233e51d`

**2. [Rule 1 - Bug] `_resolve_tier` called `get_settings()` before checking tier validity**
- **Found during:** Task 2 GREEN (`test_llm_client.py::test_decision_tier_is_removed`)
- **Issue:** `test_decision_tier_is_removed` expects `ValueError: unknown tier` but got `ValidationError: database_url` because `get_settings()` ran before the `if tier not in (...)` guard.
- **Fix:** Moved tier validity check to the top of `_resolve_tier`, before `get_settings()` call. D-21-05 intent now surfaces clearly even without env vars.
- **Files modified:** `app/llm/client.py`
- **Verification:** `uv run pytest tests/test_llm_client.py -q` → 11 passed
- **Committed in:** `233e51d`

**3. [Rule 2 - Missing Critical] New `_clarify`/`_deliver` callers in test_alias_write.py and test_cr_regressions.py missing `get_record_only_flag` patch**
- **Found during:** Task 2 GREEN (mocked suite after implementing record-only branches)
- **Issue:** Tests that call `_clarify` or `_deliver` directly with manual monkeypatching didn't patch `repo.get_record_only_flag` (not in scope before 06-08). Without it, the real repo function opens a DB connection → `ValidationError`.
- **Fix:** Added `monkeypatch.setattr(repo_mod, "get_record_only_flag", lambda *a, **kw: False, raising=False)` to each affected test (4 in `test_alias_write.py`, 1 in `test_cr_regressions.py`).
- **Files modified:** `tests/test_alias_write.py`, `tests/test_cr_regressions.py`
- **Verification:** All 5 tests now pass
- **Committed in:** `233e51d`

---

**Total deviations:** 3 auto-fixed (2 Rule 1 bug, 1 Rule 2 missing critical)
**Impact on plan:** All fixes are correctness requirements for the mocked test suite to run in worktree mode without a .env file. No scope creep.

## Known Stubs

- `app/templates/index.html` line 115: `[ Demo video — 06-07 delivers the asset ]` — intentional placeholder for the recorded demo video. Plan 06-07 delivers this asset. Does not block 06-08's goal (the composer and live pipeline run work independently of the video).

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: input_validation | app/main.py | `/demo/compose` validates `business_name` against `_SEED_CONTACTS` allowlist and caps `body` ≤ 4000 chars, `subject` ≤ 200 chars. `from_addr` resolved from allowlist, never user-supplied. XSS guard: no `|safe` filter in templates. Covered by T-06-08-01 through T-06-08-04 in plan threat model. |

## Issues Encountered

None beyond the pre-existing regression described in Deviations.

## Next Phase Readiness

- Landing page + compose surface complete; demo can run Path-1 (in-app) end-to-end without email client
- Path-2 (operator Gmail → Resend inbound) arming via `/demo/bind` is implemented; requires live Resend + DB (06-05 human gate)
- `demo_sender_bindings` DDL must be applied to live DB at the 06-05 human gate step (`bootstrap.py --no-reset`)
- Video asset slot in `index.html` ready for 06-07 to populate

## Self-Check

Checking all created/modified files exist and commits are recorded.

---
*Phase: 06-real-integration-ship*
*Completed: 2026-06-23*
