---
phase: 8
slug: data-layer-hygiene-diagnostics
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-02
amended: 2026-07-02 — replan incorporating codex cross-AI review feedback (08-REVIEWS.md): DO-block-specific drift guard, JSONB-scalar-safe employee_count, case/Unicode-normalized scrub matching, roster-scope restructure, deploy-order gate
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (via uv-managed venv) |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run pytest -q -x tests/test_repo.py tests/test_status_drift.py tests/test_models_contracts.py` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~60 seconds (full suite: 492 passed, 36 skipped baseline) |

---

## Sampling Rate

- **After every task commit:** Run the quick run command
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 08-02 Task 1 | 08-02 | 1 | OPS2-01 | T-8-01 | error_detail excludes PII (emails + roster names redacted, scrub-before-truncate, case-insensitive + NFKC-Unicode-normalized + longest-name-first matching — review fix #4) | unit | `uv run pytest -q tests/test_persistence.py -k "record_run_error or normaliz"` | ✅ | ⬜ pending |
| 08-02 Task 1 | 08-02 | 1 | OPS2-01 | T-8-02 | scrubber fail-open: record_run_error still lands type-name-only write when scrub raises / roster absent; conn stays positional-compatible (review fix #8) | unit | `uv run pytest -q tests/test_persistence.py -k record_run_error` | ✅ | ⬜ pending |
| 08-01 Task 1/2 | 08-01 | 1 | OPS2-02 | — | schema.sql contains the new CREATE INDEX IF NOT EXISTS statements + coverage facts (static guard) | unit | `uv run pytest -q tests/test_status_drift.py -k index` | ✅ | ⬜ pending |
| 08-01 Task 2 | 08-01 | 1 | OPS2-02 | T-8-05 | payroll_runs.status CHECK swap: the DO-block re-add value list is independently drift-guarded (NOT just the inline CREATE TABLE CHECK a single parser would default to) — review fix #5; needs_clarification has zero occurrences file-wide | unit | `uv run pytest -q tests/test_status_drift.py -k "status or do_block"` | ✅ | ⬜ pending |
| 08-02 Task 2 | 08-02 | 1 | OPS2-02 | T-8-07 | load_all_runs names its columns, no `pr.*` (FakeConnection SQL assertion); employee_count uses a jsonb_typeof-guarded CASE expression, not a bare COALESCE, so a non-array JSON scalar in extracted_data->'employees' does not raise (review fix #2) | unit | `uv run pytest -q tests/test_dashboard.py -k load_all_runs` | ✅ | ⬜ pending |
| 08-03 Task 1 | 08-03 | 2 | OPS2-01 | T-8-13 | run_pipeline's error path (via _run's own try/except, restructured — review fix #1/HIGH) can see whatever roster was already loaded before a first-run failure; NOT limited to email-regex-only scrubbing on the most common failure path | unit/integration | `uv run pytest -q tests/test_orchestrator_states.py tests/test_clarify.py -k "error or fail"` | ✅ | ⬜ pending |
| 08-03 Task 1 | 08-03 | 2 | OPS2-01 | T-8-11 | RUN_COLS includes error_detail AND the value reaches the rendered run_detail.html template (full DB-column -> load_run -> template key link, not just template-text presence) | integration | `uv run pytest -q tests/test_dashboard.py -k error_detail` | ✅ | ⬜ pending |
| 08-03 Task 1 | 08-03 | 2 | OPS2-01 | — | all 3 record_run_error call sites (pipeline/resume/delivery) pass detail_exc/stage, pipeline + resume also roster guarded against UnboundLocalError; InMemoryRepo.load_all_runs mirrors the new aliases (review fix #7) | unit/integration | `uv run pytest -q tests/ -k "record_run_error or threading"` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements — pytest suite is green at baseline (492 passed, 36 skipped); new tests slot into existing files/patterns (FakeConnection repo tests, test_status_drift static-guard style).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live index apply + coverage check | OPS2-02 | Project convention: live-DB migrations run at a blocking human checkpoint, never in CI | Run bootstrap against Supabase, query `pg_indexes`, confirm every OPS2-02 hot path is index-covered (constraint-backed or new) |
| CHECK-constraint swap (NEEDS_CLARIFICATION removal) | OPS2-02 (drift-guard surface) | ADD CONSTRAINT validates existing rows on the live DB | First `SELECT count(*) FROM payroll_runs WHERE status = 'needs_clarification'` and confirm 0, then apply the single-transaction DROP+ADD swap (D-7.5-03a pattern) |
| Live error_detail dashboard render, deploy-order gate | OPS2-01 | Confirms the RUN_COLS fix works against the real Supabase schema, not just FakeConnection; AND confirms the schema apply happened BEFORE error_detail-writing code was deployed against that live database (review fix #3 — a schema-missing-column write would otherwise fail the very error path OPS2-01 exists to make diagnosable) | 08-03 Task 2 step 9: deterministically set an existing run's status/error_reason/error_detail via SQL UPDATE, view run_detail.html, confirm both lines render, then revert the row (review fix #9 — no need to wait for or manufacture a real failure) |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter
- [x] Amended 2026-07-02: new rows added for the DO-block drift guard (review fix #5), the JSONB-scalar-safe employee_count expression (review fix #2), and the roster-scope restructure (review fix #1/HIGH) — no existing row removed, only extended

**Approval:** approved 2026-07-02 (amended 2026-07-02 post-review)
