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
| **Quick run command** | `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_queue_drain.py tests/test_pump_route.py tests/test_repo_jobs_sql.py tests/test_stuck_run_recovery.py tests/test_reply_redelivery.py` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | Quick feedback under 30 seconds; full-suite runtime measured during execution |

---

## Sampling Rate

- **After every task commit:** Run the task-specific test command from the applicable row below.
- **After every plan wave:** Run `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_queue_drain.py tests/test_pump_route.py tests/test_repo_jobs_sql.py tests/test_stuck_run_recovery.py tests/test_reply_redelivery.py`.
- **Before `$gsd-verify-work`:** `uv run ruff check .`, `uv run mypy`, and `uv run pytest -q` must all be green.
- **Max feedback latency:** 30 seconds for task-local and focused-wave checks.

---

## Per-Task Verification Map

Plan and task identifiers are assigned by the planner; every resulting task must map to at least one row and carry its concrete automated command.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| Planner-assigned | Planner-assigned | Planner-assigned | FAIL-01 | T-18-01 | Bounded result enums contain no exception text or PII; clarification remains an `ok` business outcome | unit | `uv run pytest -q tests/test_orchestrator_states.py tests/test_resume_pipeline.py tests/test_queue_drain.py` | ✅ | ⬜ pending |
| Planner-assigned | Planner-assigned | Planner-assigned | FAIL-02 | T-18-02 / T-18-03 | Lease-token fencing and run-state CAS prevent zombie writes; retry diagnostics remain bounded | unit + queueproof | `uv run pytest -q tests/test_queue_drain.py tests/test_repo_jobs_sql.py tests/test_pump_route.py && uv run pytest tests/test_queue_durability.py -m queueproof -v -rs` | ✅ | ⬜ pending |
| Planner-assigned | Planner-assigned | Planner-assigned | FAIL-03 | T-18-04 | `GET /runs` performs no writes or scheduling and no sweep symbol remains | route + source assertion | `uv run pytest -q tests/test_stuck_run_recovery.py tests/test_reply_redelivery.py && ! grep -R "sweep_stranded_runs\|find_stranded_unconsumed_replies" app tests` | ✅ | ⬜ pending |

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
