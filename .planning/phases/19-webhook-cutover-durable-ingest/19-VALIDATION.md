---
phase: 19
slug: webhook-cutover-durable-ingest
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-16
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest, lock-resolved through `uv.lock` |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_webhook.py tests/test_webhook_unblocked.py tests/test_queue_drain.py tests/test_resume_pipeline.py tests/test_needs_operator.py` |
| **Full suite command** | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q` |
| **Estimated runtime** | Focused task checks target under 30 seconds; full-suite runtime is environment-dependent |

---

## Sampling Rate

- **After every task commit:** Run the task-specific command from the applicable row below.
- **After every plan wave:** Run the Phase 19 focused route, queue, resume, operator, schema, fake-parity, and dashboard tests.
- **Before `$gsd-verify-work`:** Run `uv run ruff check .`, `uv run mypy`, and the full pytest suite; guarded Postgres tests must either pass with configured reset authority or be reported as skipped evidence.
- **Max feedback latency:** 30 seconds for task-local and focused-wave checks.

---

## Per-Task Verification Map

Task IDs, plan numbers, and waves are provisional until the planner creates the Phase 19 PLAN files. The planner must replace each `TBD` with the owning executable task while preserving every behavior row.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | QUEUE-04 | T19-01 | Event and ingest job commit atomically before wake and `200`; rollback returns bounded `503` | integration | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_durable_ingest.py -k "acceptance or rollback or wake"` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | QUEUE-04 | T19-02 | Webhook acceptance performs no Resend body fetch or business processing | integration | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_durable_ingest.py tests/test_webhook_unblocked.py -k "fetch or acceptance or unblocked"` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | QUEUE-04 | T19-03 | Svix event dedup and RFC `Message-ID` dedup remain separate and each prevents duplicate owed work | integration | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_durable_ingest.py tests/test_webhook.py tests/test_reply_redelivery.py -k "duplicate or dedup or redelivery"` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | QUEUE-04 | T19-04 | Null-run ingest jobs settle, retry/dead-letter, and reap without mutating payroll status | unit + guarded DB | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_queue_drain.py tests/test_queue_durability.py -k "ingest or null_run or final_attempt or reap"` | ✅ extend | ⬜ pending |
| TBD | TBD | TBD | QUEUE-04 | T19-05 | Unauthorized or cross-run clarification replies are rejected before orchestration on every attempt | unit + integration | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_resume_pipeline.py tests/test_reply_redelivery.py -k "sender or unauthorized or binding or ownership"` | ✅ extend | ⬜ pending |
| TBD | TBD | TBD | QUEUE-04 | T19-06 | Demo email, run, and job are atomic; wake follows commit; both routes redirect to run detail | integration | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_demo.py tests/test_dashboard.py -k "demo or redirect or enqueue or rollback"` | ✅ extend | ⬜ pending |
| TBD | TBD | TBD | QUEUE-04 | T19-07 | First committed valid operator generation is authoritative; loser is retained/no-op; only winner projects alias intent | unit + guarded DB | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_needs_operator.py tests/test_queue_durability.py -k "generation or authority or superseded or remember"` | ✅ extend | ⬜ pending |
| TBD | TBD | TBD | QUEUE-04 | T19-08 | Route and pipeline surfaces contain no `BackgroundTasks` imports, parameters, or `.add_task()` producers | architecture guard | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_background_task_cutover.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | QUEUE-04 | T19-09 | Queue UI exposes only bounded labels/copy, stops polling at 120 seconds, and never triggers recovery | route/template | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_dashboard.py -k "queued or running or retry or polling or durability"` | ✅ extend | ⬜ pending |
| TBD | TBD | TBD | QUEUE-04 | T19-10 | Job-kind enum, SQL checks, handler map, introspection, and fake repositories remain exact peers | architecture + schema | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_job_kind_drift.py tests/test_schema_introspect.py tests/test_repo_jobs_sql.py tests/test_fake_repo_pairing.py` | ✅ extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ guarded*

---

## Wave 0 Requirements

- [ ] `tests/test_durable_ingest.py` — durable receipt, delayed fetch, two-layer dedup, and crash-before-drain coverage for QUEUE-04.
- [ ] Null-run settlement/reaper cases in the existing queue durability suites.
- [ ] `tests/test_background_task_cutover.py` — structural guard over all route/pipeline producer seams.
- [ ] Guarded real-thread operator-authority test proving first-commit selection rather than worker-first selection.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live legacy operator-generation inventory | QUEUE-04 | `DATABASE_URL` was unavailable during research, so deployed row counts cannot be asserted locally | Before schema deployment, run a read-only grouped count of unresolved `operator_resume_resolutions`; fail closed if any run has multiple generations whose authority cannot be established without inventing historical commit order |

All product behavior otherwise requires automated verification. Guarded Postgres tests that skip without `DATABASE_URL` are unavailable evidence, not passes.

---

## Validation Sign-Off

- [ ] Planner has replaced every provisional `TBD` row with an owning task/plan/wave.
- [ ] All tasks have `<automated>` verification or explicit Wave 0 dependencies.
- [ ] Sampling continuity has no three consecutive tasks without automated verification.
- [ ] Wave 0 covers every missing test reference.
- [ ] No watch-mode flags are used.
- [ ] Task-local feedback latency is under 30 seconds.
- [ ] `nyquist_compliant: true` is set in frontmatter after the plan-to-task map is complete.

**Approval:** pending
