---
phase: 8
slug: data-layer-hygiene-diagnostics
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-02
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
| 08-02 Task 1 | 08-02 | 1 | OPS2-01 | T-8-01 | error_detail excludes PII (emails + roster names redacted, scrub-before-truncate) | unit | `uv run pytest -q tests/test_persistence.py -k record_run_error` | ✅ | ⬜ pending |
| 08-02 Task 1 | 08-02 | 1 | OPS2-01 | T-8-02 | scrubber fail-open: record_run_error still lands type-name-only write when scrub raises / roster absent | unit | `uv run pytest -q tests/test_persistence.py -k record_run_error` | ✅ | ⬜ pending |
| 08-01 Task 1/2 | 08-01 | 1 | OPS2-02 | — | schema.sql contains the new CREATE INDEX IF NOT EXISTS statements + coverage facts (static guard) | unit | `uv run pytest -q tests/test_status_drift.py -k index` | ✅ | ⬜ pending |
| 08-02 Task 2 | 08-02 | 1 | OPS2-02 | T-8-07 | load_all_runs names its columns, no `pr.*` (FakeConnection SQL assertion) | unit | `uv run pytest -q tests/test_dashboard.py -k load_all_runs` | ✅ | ⬜ pending |
| 08-03 Task 1 | 08-03 | 2 | OPS2-01 | T-8-11 | RUN_COLS includes error_detail AND the value reaches the rendered run_detail.html template (full DB-column -> load_run -> template key link, not just template-text presence) | integration | `uv run pytest -q tests/test_dashboard.py -k error_detail` | ✅ | ⬜ pending |
| 08-03 Task 1 | 08-03 | 2 | OPS2-01 | — | all 3 record_run_error call sites (pipeline/resume/delivery) pass detail_exc/stage, resume also roster guarded against UnboundLocalError | unit/integration | `uv run pytest -q tests/ -k "record_run_error or threading"` | ✅ | ⬜ pending |

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
| Live error_detail dashboard render | OPS2-01 | Confirms the RUN_COLS fix works against the real Supabase schema, not just FakeConnection | 08-03 Task 2 step 8: view a run in ERROR status on run_detail.html and confirm the stage-prefixed error_detail line renders beneath error_reason |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-02
