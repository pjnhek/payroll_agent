---
phase: 19
slug: webhook-cutover-durable-ingest
status: planned
nyquist_compliant: true
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

Task IDs, plan numbers, and waves below are the executable owners from the approved Phase 19 plan set.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 19-06-02 | 19-06 | 5 | QUEUE-04 | T19-01 | Event and ingest job commit atomically before wake and `200`; rollback returns bounded `503` | integration | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_durable_ingest.py -k "acceptance or rollback or wake"` | ❌ W0 in 19-03/19-06 | ⬜ pending |
| 19-06-02 | 19-06 | 5 | QUEUE-04 | T19-02 | Webhook acceptance performs no Resend body fetch/business processing, and slow receipt persistence stays off-loop | integration | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_durable_ingest.py tests/test_webhook_unblocked.py -k "fetch or acceptance or unblocked or slow_database or off_loop"` | ❌ W0 in 19-03/19-06 | ⬜ pending |
| 19-10-02 | 19-10 | 8 | QUEUE-04 | T19-03 | Svix event dedup and RFC `Message-ID` dedup remain separate and each prevents duplicate owed work | integration | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_durable_ingest.py tests/test_webhook.py tests/test_reply_redelivery.py tests/test_webhook_dedup_race.py -k "duplicate or dedup or redelivery or svix"` | ❌ W0 in 19-03; guarded extension in 19-10 | ⬜ pending |
| 19-05-02 | 19-05 | 4 | QUEUE-04 | T19-04 | Null-run ingest jobs settle, retry/dead-letter, and reap without mutating payroll status | unit + guarded DB | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_queue_drain.py tests/test_queue_durability.py -k "ingest or null_run or final_attempt or reap"` | ✅ extend | ⬜ pending |
| 19-08-01 | 19-08 | 4 | QUEUE-04 | T19-05 | Unauthorized or cross-run clarification replies are rejected before orchestration on every attempt | unit + integration | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_resume_pipeline.py tests/test_reply_redelivery.py -k "sender or unauthorized or binding or ownership"` | ✅ extend | ⬜ pending |
| 19-07-01 | 19-07 | 4 | QUEUE-04 | T19-06 | Demo email, run, and job are atomic; wake follows commit; both routes redirect to run detail | integration | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_demo_landing.py tests/test_demo_fixtures.py tests/test_dashboard.py -k "demo or redirect or enqueue or rollback"` | ✅ extend | ⬜ pending |
| 19-08-02 | 19-08 | 4 | QUEUE-04 | T19-07 | First committed valid operator generation is authoritative; loser is retained/no-op; only winner projects alias intent | unit + guarded DB | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_needs_operator.py tests/test_queue_durability.py -k "generation or authority or superseded or remember"` | ✅ extend; guarded real-thread W0 in 19-02 | ⬜ pending |
| 19-11-01 | 19-11 | 6 | QUEUE-04 | T19-08 | Execution-policy consumers preserve propagation, send guards, retry/terminal settlement, and exact value flow without retired swallowing wrappers | unit + architecture | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_retrigger_threading.py tests/test_queue_drain.py tests/test_send_idempotency.py` | ✅ migrate | ⬜ pending |
| 19-11-02 | 19-11 | 6 | QUEUE-04 | T19-08 | Route/concurrency consumers assert committed jobs and fail if payroll value/handler execution occurs inline | unit + integration | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_ingest.py tests/test_concurrency_proof.py tests/test_gateway.py tests/test_stuck_run_recovery.py tests/test_hitl.py` | ✅ migrate | ⬜ pending |
| 19-11-03 | 19-11 | 6 | QUEUE-04 | T19-08 | Existing RFC race consumer is wrapper-free and proves committed delayed-ingest/downstream jobs before deletion | guarded DB + source guard | `! rg -n 'run_pipeline_bg|resume_pipeline_bg|operator_resume_bg|_consume_background_result|finish_reply_resume|BackgroundTasks' tests/test_webhook_dedup_race.py &amp;&amp; UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_webhook_dedup_race.py` | ✅ migrate before deletion | ⬜ pending |
| 19-12-01 | 19-12 | 7 | QUEUE-04 | T19-08 | Compatibility procedures are deleted only after every former consumer passes against its durable replacement | unit + architecture | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_retrigger_threading.py tests/test_ingest.py tests/test_concurrency_proof.py tests/test_gateway.py tests/test_stuck_run_recovery.py tests/test_hitl.py tests/test_webhook_dedup_race.py tests/test_queue_drain.py tests/test_send_idempotency.py` | ✅ depends on 19-11 | ⬜ pending |
| 19-12-02 | 19-12 | 7 | QUEUE-04 | T19-08 | Route and pipeline surfaces contain no `BackgroundTasks` imports, parameters, `.add_task()` producers, retired wrappers, or stale test consumers | architecture guard | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_background_task_cutover.py tests/test_webhook_dedup_race.py` | ❌ W0 guard; ✅ migrated race consumer | ⬜ pending |
| 19-09-02 | 19-09 | 5 | QUEUE-04 | T19-09 | Queue UI exposes only bounded labels/copy, stops polling at 120 seconds, and never triggers recovery | route/template | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_dashboard.py -k "queued or running or retry or polling or durability"` | ✅ extend | ⬜ pending |
| 19-04-01 / 19-05-01 | 19-04 / 19-05 | 3 / 4 | QUEUE-04 | T19-10 | Job-kind enum, SQL checks, handler map, context, claim mapping, settlement, and fake repositories remain exact peers | architecture + schema | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_job_kind_drift.py tests/test_schema_introspect.py tests/test_repo_jobs_sql.py tests/test_queue_drain.py tests/test_fake_repo_pairing.py` | ✅ extend | ⬜ pending |
| 19-01-03 | 19-01 | 1 | QUEUE-04 | T19-01 | Writer fence closes before preflight; sole legacy generations migrate to one winner with `remember=false`; ambiguity blocks before authority writes | unit + deployment contract | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_operator_resolution_inventory.py tests/test_operator_resolution_migration.py` | ❌ W0 in 19-01 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ guarded*

---

## Wave 0 Requirements

- [ ] `tests/test_durable_ingest.py` — created test-first by 19-03-01 and extended by 19-06-01/19-10-02 for durable receipt, delayed fetch, two-layer dedup, and crash-before-drain coverage.
- [ ] Slow-database responsiveness case in `tests/test_webhook_unblocked.py` — created test-first by 19-06-01 and proves unrelated event-loop work progresses while synchronous receipt persistence is blocked.
- [ ] Null-run settlement/reaper cases — created test-first by 19-05-01 and completed by 19-05-02 in the existing queue durability suites.
- [ ] Nine existing consumer modules — migrated test-first by 19-11-01/02/03 from retired wrappers to explicit PipelineResult, queue handler/drain, committed-job, and fail-if-inline seams; `tests/test_webhook_dedup_race.py` has its bounded Task 3 migration before Plan 19-12 and is extended only later by Plan 19-10.
- [ ] `tests/test_background_task_cutover.py` — created test-first by 19-12-02 after 19-11's consumer migration, with a nonempty producer/retired-symbol inventory and synthetic reintroduction proofs.
- [ ] Guarded real-thread operator-authority test — created test-first by 19-02-01 and consumed by 19-08-02.
- [ ] `tests/test_operator_resolution_migration.py` — created test-first by 19-01-03 for ACCESS EXCLUSIVE fence close, old-writer rejection, ambiguity-before-authority-write, sole-generation migration, remember=false preservation, exact postflight, and fail-closed reopen.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live legacy operator-generation deployment | QUEUE-04 | `DATABASE_URL` and Render deployment authority were unavailable during research, so deployed row counts, writer quiescence, and activation cannot be asserted locally | Close/check the persistent DB writer fence under ACCESS EXCLUSIVE lock before accepting the exact three-count preflight; keep it closed through additive schema, sole-generation migration with remember=false, exact authority/schema postflight, Render activation of the identified Phase 19 revision, and repeated postflight; reopen only after the prior Phase 18 instance is replaced and every check remains clean |

All product behavior otherwise requires automated verification. Guarded Postgres tests that skip without `DATABASE_URL` are unavailable evidence, not passes.

---

## Validation Sign-Off

- [x] Planner has replaced every provisional placeholder row with an owning task/plan/wave.
- [x] All tasks have `<automated>` verification or explicit Wave 0 dependencies.
- [x] Sampling continuity has no three consecutive tasks without automated verification.
- [x] Wave 0 covers every missing test reference.
- [x] No watch-mode flags are used.
- [x] Task-local focused commands target under 30 seconds; the full suite remains a phase gate.
- [x] `nyquist_compliant: true` is set after the plan-to-task map is complete.

**Approval:** plan map complete; execution pending
