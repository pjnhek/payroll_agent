---
status: secured
phase: 08-data-layer-hygiene-diagnostics
audited: 2026-07-02
asvs_level: L1
threats_total: 14
threats_closed: 14
threats_open: 0
register_authored_at_plan_time: true
---

# Phase 8 Security Audit — Data Layer Hygiene & Diagnostics

**Audited:** 2026-07-02
**ASVS Level:** L1 (default)
**Scope:** Threat register from 08-01/08-02/08-03 PLAN.md `<threat_model>` blocks (14 threats), verified against the working tree AFTER the post-execution review-fix pass (ea28e2d..e5241a8, 08-REVIEW-FIX.md). Where the mechanism evolved past the plan text, verification was judged against the threat's intent.

**Result: SECURED — 14/14 threats closed** (13 mitigated + 1 documented accepted risk).

Guard-test confirmation (read-only run): `uv run pytest tests/test_status_drift.py tests/test_persistence.py tests/test_dashboard.py tests/test_orchestrator_states.py -q` → **73 passed, 2 skipped** (skips are live-DB-gated tests, not security guards).

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-8-01 | Information Disclosure | mitigate | CLOSED | `app/db/repo.py:394-511` — `_EMAIL_RE`, generated `_ACCENT_CLASS_MAP` (three-way alternation, `_build_accent_class_map` 415-435), `_compile_name_pattern` with NFC-normalized candidate (462, WR-01) and mark-aware lookarounds `(?<![\ẁ-ͯ])…(?![\ẁ-ͯ])` (468), longest-first `_scrub` (492), scrub-BEFORE-truncate in `_build_error_detail` (508-509). Tests: `tests/test_persistence.py:272` (PII exclusion), `:302` (boundary straddle), `:396` (case/Unicode/unaccented, no stray combining mark), `:444` (WR-02 umlaut/grave), `:488` (WR-01 NFD-stored candidate), `:526` (R3-1 trailing-accent NFD), `:548` (longest-first offset-safety), `:564` (Tom/Tomorrow non-over-redaction) — all passing |
| T-8-02 | DoS (silently-hung run) | mitigate | CLOSED | `app/db/repo.py:507-511` — `try/except Exception: return None` inside `_build_error_detail`; `record_run_error` proceeds with `detail=None`, writes `error_reason`, advances to ERROR via `set_status` (586). Post-review CAS form (WR-03, 572-586) preserves the fail-open contract. Tests: `tests/test_persistence.py:332` (scrub raises → still writes, `params[1] is None`), `:361` (no roster → no extra SELECT) |
| T-8-03 | Tampering (schema DO-block DROP) | mitigate | CLOSED (mechanism evolved, intent satisfied) | Plan's `conname LIKE '%status%'` matcher was REPLACED by WR-06 (e5241a8) with a strictly narrower column-set matcher: `app/db/schema.sql:141-171` — `contype='c' AND conrelid='payroll_runs'::regclass AND conkey→pg_attribute = ARRAY['status']`, so the DROP can only target CHECK constraints on exactly the `status` column; DROP+ADD remain inside one atomic `DO $$ … END $$;` block (failed ADD rolls back the DROP). Static guard pins the idiom: `tests/test_status_drift.py:220` asserts NO `conname LIKE` in executable SQL and conkey-anchored matchers present. Same fix applied to the email_messages purpose block (schema.sql:242-261) |
| T-8-04 | Information Disclosure (index metadata) | accept | CLOSED (accepted risk, logged below) | See Accepted Risks log |
| T-8-05 | DoS (enum/CHECK schema drift) | mitigate | CLOSED | `tests/test_status_drift.py:119,159,181` — value set live-derived via `{member.value for member in RunStatus}` (not hardcoded), asserted against the parsed inline CHECK AND, via the dedicated `_extract_do_block_status_values` parser (:68) + `test_do_block_status_check_matches_enum` (:170), against the DO-block re-add list independently; `test_needs_clarification_absent_file_wide` (:192). schema.sql inline CHECK (64-80) and DO-block (157-169) both enumerate the same 10 values; zero `needs_clarification` occurrences file-wide |
| T-8-06 | Information Disclosure (DB call in error path) | mitigate | CLOSED | `app/db/repo.py:472-497` — `_scrub(message, roster=None)` takes roster as an in-memory parameter only; body contains no DB call, no `get_connection`, no `load_roster_for_business` import/call; `_build_error_detail` (500-511) likewise. `tests/test_persistence.py:361` asserts no extra SELECT appears in the no-roster path |
| T-8-07 | Information Disclosure (schema creep) | mitigate | CLOSED | `app/db/repo.py:1288-1298` — `load_all_runs` SQL names 5 explicit scalar columns + `business_name` + 2 computed aliases; no `pr.*`/`SELECT *` anywhere in the function. Test: `tests/test_dashboard.py:54-62` asserts `"pr.*" not in sql` and explicit columns/aliases present |
| T-8-08 | Tampering/Injection (XSS) | mitigate | CLOSED | `app/templates/run_detail.html:69` — `{% if run.error_detail %}<div class="banner-divider">{{ run.error_detail }}</div>{% endif %}`; NO `\|safe` filter in run_detail.html or runs_list.html (grep: zero matches); `app/main.py:144` uses Starlette `Jinja2Templates` defaults (autoescape ON) |
| T-8-09 | Tampering (live CHECK swap data integrity) | mitigate | CLOSED | Blocking human checkpoint executed 2026-07-02: pre-migration guard `SELECT count(*) WHERE status='needs_clarification'` returned **0** before the apply; constraint verified post-apply to exclude `needs_clarification` and contain the 10 values (08-03-SUMMARY.md checkpoint evidence items 1 & 6, human-approved). DROP+ADD atomic in one DO block (schema.sql:141-171) |
| T-8-10 | DoS (pool singleton race) | mitigate | CLOSED | `app/db/supabase.py:32` — module-level `_pool_lock = threading.Lock()`; `get_pool()` (:48-63) implements double-checked locking: outer `if _pool is None`, `with _pool_lock:`, inner re-check before `ConnectionPool(...)` construction |
| T-8-11 | Information Disclosure (silent RUN_COLS gap) | mitigate | CLOSED | `app/db/repo.py:101-105` — `RUN_COLS` includes `error_detail` immediately after `error_reason` (with rationale comment, 92-95); integration test `tests/test_dashboard.py:321` (`test_run_detail_renders_error_detail_end_to_end`) asserts `"error_detail" in fake_conn.all_sql()` (:355) — the real SQL text, not template text — and that the value reaches the rendered HTML |
| T-8-12 | DoS (corrupt JSONB kills runs list) | mitigate | CLOSED | `app/db/repo.py:1292-1294` — `CASE WHEN jsonb_typeof(pr.extracted_data->'employees') = 'array' THEN jsonb_array_length(...) ELSE 0 END AS employee_count`; no bare `COALESCE(jsonb_array_length` remains. Test: `tests/test_dashboard.py:71-81` asserts the exact CASE/jsonb_typeof pattern in the SQL text |
| T-8-13 | Information Disclosure (roster-blind error path, HIGH #1) | mitigate | CLOSED | `app/pipeline/orchestrator.py:190-224` — `_run` owns its own try/except; `roster = None` first statement (:201), reassigned at `load_roster_for_business` (:210), except block calls `record_run_error(run_id, reason, detail_exc=exc, stage="pipeline", roster=roster)` (:224). `run_pipeline` (:174) is a thin delegator (no try/except). `resume_pipeline`: `roster = None` (:257), load (:275), except passes `stage="resume", roster=roster` (:697). Behavioral spy test `tests/test_orchestrator_states.py:134-182` asserts CAPTURED runtime kwargs: `stage == "pipeline"`, `roster is not None`, `isinstance(roster, Roster)`, `len(roster.employees) > 0` — passing |
| T-8-14 | DoS (deploy-order: error_detail write vs missing column) | mitigate | CLOSED | Procedural gate executed and documented: 08-03-SUMMARY.md checkpoint evidence — schema applied via bootstrap against the live pooler with Task 1's code still unmerged/undeployed ("deploy-order gate honored"), `error_detail \| text \| YES` confirmed via information_schema (item 5), human-approved 2026-07-02. Live DB now has the column, so the safe ordering is permanently satisfied for this migration |

## Accepted Risks Log

| Threat ID | Risk | Rationale | Accepted |
|-----------|------|-----------|----------|
| T-8-04 | New indexes `idx_payroll_runs_status`, `idx_payroll_runs_created_at`, `idx_email_messages_run_direction_state` add index metadata | Indexed columns are `status`/`direction`/`send_state` (closed enum-like value sets) and `run_id`/`created_at` (opaque UUID / timestamp) — no PII lives in any indexed column, so index metadata discloses nothing beyond what the table rows already carry. schema.sql:117-123, 280-287 | Phase 8 plan 08-01, disposition `accept`; logged here per audit |

## Post-Execution Mechanism Evolutions (review-fix pass, all strengthen — none weaken)

- **T-8-01 strengthened:** WR-01 (NFC-normalized candidates, repo.py:462), WR-02 (accent map generated from `unicodedata.decomposition` over Latin-1 at import time — 27 entries vs the planned 7; still static, still offset-safe, repo.py:415-435).
- **T-8-02/terminal guard strengthened:** WR-03 converted the terminal-status check-then-act into an atomic CAS UPDATE (`status <> ALL(%s) RETURNING id`, repo.py:572-577); fail-open contract unchanged and re-verified by tests.
- **Delivery boundary roster-aware (beyond plan):** WR-04 — `_deliver` stashes its already-loaded roster on the raised exception (`exc.payroll_roster`, orchestrator.py:1311) and `approve()` forwards `roster=getattr(exc, "payroll_roster", None)` (main.py:513-518). This upgrades the delivery-stage scrub from email-regex-only to roster-aware without violating D-8-01b (no roster is ever LOADED on the error path). Maps to T-8-01/T-8-13 intent.
- **T-8-03 mechanism replaced:** WR-06 conkey-anchored constraint matching (see table row) — strictly narrower targeting than the planned name-LIKE; verified atomicity preserved.
- **WR-05 contract note:** `error_detail` is ALWAYS overwritten (NULL when `detail_exc`/`stage` omitted) — deliberate; a stale detail beside a fresh `error_reason` would mislead the operator. Pinned by `tests/test_persistence.py:219`.

## Unregistered Threat Flags

None. No `## Threat Flags` section exists in 08-01/08-02/08-03 SUMMARY.md (grep: zero matches). All new attack surface introduced by the review-fix pass maps to existing threat IDs as noted above.
