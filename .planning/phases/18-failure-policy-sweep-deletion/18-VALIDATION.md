---
phase: 18
slug: failure-policy-sweep-deletion
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-15
---

# Phase 18 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_orchestrator_states.py tests/test_job_kind_drift.py tests/test_repo_jobs_sql.py tests/test_resume_pipeline.py tests/test_needs_operator.py tests/test_queue_drain.py tests/test_pump_route.py tests/test_stuck_run_recovery.py tests/test_fake_repo_pairing.py` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | Quick feedback under 30 seconds; full-suite runtime measured during execution |

---

## Sampling Rate

- **After every task commit:** Run the task-specific test command from the applicable row below.
- **After every plan wave:** Run `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_orchestrator_states.py tests/test_job_kind_drift.py tests/test_repo_jobs_sql.py tests/test_resume_pipeline.py tests/test_needs_operator.py tests/test_queue_drain.py tests/test_pump_route.py tests/test_stuck_run_recovery.py tests/test_fake_repo_pairing.py`.
- **Before `$gsd-verify-work`:** `uv run ruff check .`, `uv run mypy`, and `uv run pytest -q` must all be green.
- **Max feedback latency:** 30 seconds for task-local and focused-wave checks.

---

## Per-Task Verification Map

Plan and task identifiers are assigned by the planner; every resulting task must map to at least one row and carry its concrete automated command.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 18-01 | 18-01 | 1 | FAIL-01 | T-18-01 / T-18-02 | Bounded result enums contain no exception text/PII; one temporary normalizer accepts legacy None while producers remain unchanged | unit | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_orchestrator_states.py -k "pipeline_result or classification or legacy_result"` | ✅ | ⬜ pending |
| 18-02 | 18-02 | 2 | FAIL-01, FAIL-02 | T-18-04 / T-18-05 / T-18-06 | Identifier-only Job gains email/resolution identifiers; immutable typed operator-resolution parent/mapping rows stay in SQL lockstep | static + SQL-shape | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_repo_jobs_sql.py` | ✅ | ⬜ pending |
| 18-12 | 18-12 | 3 | FAIL-02 | T-18-32 / T-18-33 | Live schema health fails when either typed resolution table, jobs resolution column, or critical named relationship/index is absent | unit + SQL-shape | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_schema_introspect.py` | ✅ | ⬜ pending |
| 18-09 | 18-09 | 4 | FAIL-01, FAIL-02 | T-18-08 / T-18-09 / T-18-10 / T-18-11 | Reply/operator handlers reconstruct exact persisted context by email/resolution id and stay fake-paired | unit + harness | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_job_kind_drift.py tests/test_fake_repo_pairing.py tests/test_resume_pipeline.py tests/test_needs_operator.py` | ✅ | ⬜ pending |
| 18-03 | 18-03 | 5 | FAIL-02 | T-18-12 / T-18-13 / T-18-14 / T-18-15 | Valid `/resolve` commits complete typed authority before identifier-only scheduling; all three BackgroundTask retries bridge durably; settlement is fenced and PII-safe | route + unit + queueproof | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_queue_drain.py tests/test_resume_pipeline.py tests/test_needs_operator.py tests/test_fake_repo_pairing.py && uv run pytest tests/test_queue_durability.py -m queueproof -k "settlement or operator_resume or exhaustion or terminal_result or infrastructure or final_attempt" -v -rs` | ✅ | ⬜ pending |
| 18-04 | 18-04 | 6 | FAIL-01, FAIL-02 | T-18-12 / T-18-13 / T-18-14 / T-18-15 | Drain maps explicit results atomically and reaps exact expired final-attempt leases before EMPTY | unit + queueproof | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_queue_drain.py` | ✅ | ⬜ pending |
| 18-06 | 18-06 | 6 | FAIL-02 | T-18-18 / T-18-19 | Operator-visible diagnostics remain bounded and same-run Retrigger preserves immutable dead history | route + unit | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_dashboard.py tests/test_hitl.py tests/test_alias_and_run_column_regressions.py` | ✅ | ⬜ pending |
| 18-05 | 18-05 | 7 | FAIL-02 | T-18-16 / T-18-17 | Pump counts reaped final leases as dead/reaped but not claimed | route + queueproof | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_pump_route.py` | ✅ | ⬜ pending |
| 18-10 | 18-10 | 7 | FAIL-01, FAIL-02 | T-18-27 / T-18-29 | Both producers cut over only after consumers and return PipelineResult on every path | unit | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_orchestrator_states.py tests/test_resume_pipeline.py -k "result or classification or clarification or claim"` | ✅ | ⬜ pending |
| 18-11 | 18-11 | 8 | FAIL-01, FAIL-02 | T-18-30 / T-18-31 | Every compatibility-era producer/forwarder/normalizer seam narrows to PipelineResult; caller inventory and mypy prove no None sink | unit + AST + typing | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_queue_drain.py tests/test_resume_pipeline.py tests/test_needs_operator.py -k "result or caller or background or resume or operator" && uv run mypy` | ✅ | ⬜ pending |
| 18-07 | 18-07 | 9 | FAIL-03 | T-18-24 / T-18-25 / T-18-26 | Route callers disappear after compatibility closure; GET /runs is read-only | route + AST | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_stuck_run_recovery.py tests/test_reply_redelivery.py tests/test_needs_operator.py tests/test_retrigger_epoch.py tests/test_hitl.py tests/test_dashboard.py` | ✅ | ⬜ pending |
| 18-08 | 18-08 | 10 | FAIL-03 | T-18-21 / T-18-22 / T-18-23 | Repository/facade/fake APIs disappear only after callers; final source-aware gate proves one recovery policy remains | harness + source gate | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_fake_repo_pairing.py tests/test_stuck_run_recovery.py tests/test_reply_redelivery.py tests/test_needs_operator.py && ! grep -R -n --exclude-dir='__pycache__' --include='*.py' --include='*.html' --include='*.sql' 'sweep_stranded_runs\|find_stranded_unconsumed_replies' app` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing pytest infrastructure and all referenced test modules are present. No framework installation, shared fixture bootstrap, or test-file stub is required before implementation.

---

## Manual-Only Verifications

All Phase 18 behaviors have automated verification. Operator-visible copy and Retrigger availability are asserted through route/template tests rather than manual inspection.

---

## Validation Sign-Off

- [ ] Every planned task has an automated verify command mapped above.
- [ ] Sampling continuity has no three consecutive tasks without automated verification.
- [x] Wave 0 has no missing framework, fixture, or test-module dependency.
- [x] Commands use no watch-mode flags.
- [x] Task-local and focused-wave feedback target is under 30 seconds.
- [x] `nyquist_compliant: true` is set in frontmatter.

**Approval:** pending
