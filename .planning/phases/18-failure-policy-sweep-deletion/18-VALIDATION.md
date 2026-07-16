---
phase: 18
slug: failure-policy-sweep-deletion
status: verified
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-15
audited: 2026-07-16
---

# Phase 18 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline --no-sync pytest -q tests/test_orchestrator_states.py tests/test_repo_jobs_sql.py tests/test_schema_introspect.py tests/test_resume_pipeline.py tests/test_needs_operator.py tests/test_queue_drain.py tests/test_pump_route.py tests/test_dashboard.py tests/test_stuck_run_recovery.py tests/test_fake_repo_pairing.py` |
| **Full suite command** | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline --no-sync pytest -q` |
| **Estimated runtime** | Task-local/focused checks target under 30 seconds; audited full suite: 156.06 seconds |

---

## Sampling Rate

- **After every task commit:** Run the task-specific test command from the applicable row below.
- **After every plan wave:** Run `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_orchestrator_states.py tests/test_job_kind_drift.py tests/test_repo_jobs_sql.py tests/test_resume_pipeline.py tests/test_needs_operator.py tests/test_queue_drain.py tests/test_pump_route.py tests/test_stuck_run_recovery.py tests/test_fake_repo_pairing.py`.
- **Before `$gsd-verify-work`:** `uv run ruff check .`, `uv run mypy`, and `uv run pytest -q` must all be green. Audit result: all three green after the two test-typing repairs below.
- **Max feedback latency:** 30 seconds for task-local and focused-wave checks.

---

## Per-Task Verification Map

The audit rebuilt this map from all 14 completed PLAN/SUMMARY pairs. Each of
the 29 tasks has its own executable command rather than sharing a plan-level
placeholder row.

| Task ID | Plan | Wave | Requirement | Automated Command | File Exists | Status |
|---------|------|------|-------------|-------------------|-------------|--------|
| 18-01-01 | 18-01 | 1 | FAIL-01 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_orchestrator_states.py -k "pipeline_result or classification"` | ✅ | ✅ green |
| 18-01-02 | 18-01 | 1 | FAIL-01 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_orchestrator_states.py -k "pipeline_result or classification or legacy_result"` | ✅ | ✅ green |
| 18-02-01 | 18-02 | 2 | FAIL-01, FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_repo_jobs_sql.py` | ✅ | ✅ green |
| 18-02-02 | 18-02 | 2 | FAIL-01, FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_job_kind_drift.py tests/test_repo_jobs_sql.py tests/test_schema_introspect.py` | ✅ | ✅ green |
| 18-02-03 | 18-02 | 2 | FAIL-01, FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_repo_jobs_sql.py -k "inbound_email_by_id or operator_resume_resolution or claim_projection or enqueue"` | ✅ | ✅ green |
| 18-12-01 | 18-12 | 3 | FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_schema_introspect.py` | ✅ | ✅ green |
| 18-09-01 | 18-09 | 4 | FAIL-01, FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_job_kind_drift.py tests/test_resume_pipeline.py -k "job_kind or resume_reply or persisted or received or reclaim"` | ✅ | ✅ green |
| 18-09-02 | 18-09 | 4 | FAIL-01, FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_job_kind_drift.py tests/test_needs_operator.py -k "operator_resume or override or reclaim or job_kind"` | ✅ | ✅ green |
| 18-09-03 | 18-09 | 4 | FAIL-01, FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_fake_repo_pairing.py tests/test_resume_pipeline.py tests/test_needs_operator.py -k "pairing or resume_reply or operator_resume or override"` | ✅ | ✅ green |
| 18-03-01 | 18-03 | 5 | FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_fake_repo_pairing.py tests/test_queue_drain.py -k "pairing or settlement or operator_resume or final_attempt" && uv run pytest tests/test_queue_durability.py -m queueproof -k "settlement or operator_resume or exhaustion or terminal_result or infrastructure or final_attempt" -v -rs` | ✅ | ✅ green |
| 18-03-02 | 18-03 | 5 | FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_fake_repo_pairing.py tests/test_queue_drain.py tests/test_resume_pipeline.py -k "pairing or background or resume or reply"` | ✅ | ✅ green |
| 18-03-03 | 18-03 | 5 | FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_fake_repo_pairing.py tests/test_needs_operator.py -k "pairing or resolve or resolution or operator_resume or override or retryable or signature or caller" && uv run pytest tests/test_queue_durability.py -m queueproof -k "operator_resume" -v -rs` | ✅ | ✅ green |
| 18-04-01 | 18-04 | 6 | FAIL-01, FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_queue_drain.py -k "pipeline_result or infrastructure or drain_once or status_writers" && uv run pytest tests/test_queue_durability.py -m queueproof -k "terminal_result or infrastructure" -v -rs` | ✅ | ✅ green |
| 18-04-02 | 18-04 | 6 | FAIL-01, FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_queue_drain.py && uv run pytest tests/test_queue_durability.py -m queueproof -k "final_attempt or reap" -v -rs` | ✅ | ✅ green |
| 18-06-01 | 18-06 | 6 | FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_dashboard.py -k "error or retried or polling or safe"` | ✅ | ✅ green |
| 18-06-02 | 18-06 | 6 | FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_hitl.py tests/test_alias_and_run_column_regressions.py -k "retrigger"` | ✅ | ✅ green |
| 18-05-01 | 18-05 | 7 | FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_pump_route.py` | ✅ | ✅ green |
| 18-05-02 | 18-05 | 7 | FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest tests/test_queue_durability.py -m queueproof -k "pump and reap" -v -rs` | ✅ | ⚠️ guarded |
| 18-10-01 | 18-10 | 7 | FAIL-01, FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_orchestrator_states.py tests/test_resume_pipeline.py -k "result or classification or clarification or claim"` | ✅ | ✅ green |
| 18-11-01 | 18-11 | 8 | FAIL-01, FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_resume_pipeline.py tests/test_needs_operator.py -k "result or resume or operator or context"` | ✅ | ✅ green |
| 18-11-02 | 18-11 | 8 | FAIL-01, FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_queue_drain.py tests/test_resume_pipeline.py tests/test_needs_operator.py -k "result or caller or background or resume or operator" && uv run mypy` | ✅ | ✅ green |
| 18-07-01 | 18-07 | 9 | FAIL-03 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_stuck_run_recovery.py tests/test_dashboard.py -k "runs or retired or read_only"` | ✅ | ✅ green |
| 18-07-02 | 18-07 | 9 | FAIL-03 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_stuck_run_recovery.py tests/test_reply_redelivery.py tests/test_needs_operator.py tests/test_retrigger_epoch.py tests/test_hitl.py` | ✅ | ✅ green |
| 18-08-01 | 18-08 | 10 | FAIL-03 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_fake_repo_pairing.py` | ✅ | ✅ green |
| 18-08-02 | 18-08 | 10 | FAIL-03 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_fake_repo_pairing.py tests/test_stuck_run_recovery.py tests/test_reply_redelivery.py tests/test_needs_operator.py && ! grep -R -n --exclude-dir='__pycache__' --include='*.py' --include='*.html' --include='*.sql' 'sweep_stranded_runs\|find_stranded_unconsumed_replies' app` | ✅ | ✅ green |
| 18-13-01 | 18-13 | 11 | FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_queue_drain.py -k "final_attempt or reap or starvation or status_matrix"` | ✅ | ✅ green |
| 18-13-02 | 18-13 | 11 | FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest tests/test_queue_durability.py -m queueproof -k "final_attempt or reap or starvation" -v -rs` | ✅ | ⚠️ guarded |
| 18-14-01 | 18-14 | 12 | FAIL-01, FAIL-02 | `env -u DATABASE_URL UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_resume_pipeline.py && DATABASE_URL=postgresql://stub:stub@localhost/stub UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_resume_pipeline.py` | ✅ | ✅ green |
| 18-14-02 | 18-14 | 12 | FAIL-01, FAIL-02 | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest tests/test_queue_durability.py -m queueproof -k "resume_reply and association" -v -rs` | ✅ | ⚠️ guarded |

*Status: ✅ green · ⚠️ guarded (automated live-Postgres check collected but environment unavailable; always-run behavioral equivalent is green) · ❌ red.*

---

## Wave 0 Requirements

Existing pytest infrastructure and all referenced test modules are present. No framework installation, shared fixture bootstrap, or test-file stub is required before implementation.

---

## Manual-Only Verifications

All Phase 18 requirements have always-run automated behavioral verification.
Operator-visible copy and Retrigger availability are asserted through
route/template tests rather than manual inspection.

Three additional real-Postgres task commands (18-05-02, 18-13-02, and
18-14-02) remain behind the existing `DATABASE_URL` plus `ALLOW_DB_RESET=1`
guard. They collected and skipped during Phase 18 verification and are recorded
as unavailable evidence, not passes. They do not make a requirement
manual-only: equivalent pump accounting, final-lease state/ordering, and reply
ownership behavior is covered by always-run stateful tests.

---

## Validation Audit 2026-07-16

| Metric | Count |
|--------|-------|
| Gaps found | 2 |
| Resolved | 2 |
| Escalated | 0 |

The generic-agent workaround for `gsd-nyquist-auditor` repaired two test-only
strict-mypy gaps without modifying implementation behavior:

- 18-14-01 now monkeypatches the public `app.pipeline.orchestrator` module
  directly while preserving the fail-if-called ownership guard.
- 18-13-02 now narrows optional job rows before asserting live transport state.

Post-repair evidence: full suite `899 passed, 69 skipped`; Ruff passed; repo-wide
mypy reported no issues in 146 source files; `git diff --check` passed.

---

## Validation Sign-Off

- [x] Every planned task has an automated verify command mapped above.
- [x] Sampling continuity has no three consecutive tasks without automated verification.
- [x] Wave 0 has no missing framework, fixture, or test-module dependency.
- [x] Commands use no watch-mode flags.
- [x] Task-local and focused-wave feedback target is under 30 seconds.
- [x] `nyquist_compliant: true` is set in frontmatter.

**Approval:** verified 2026-07-16
