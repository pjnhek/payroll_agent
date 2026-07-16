---
phase: 18-failure-policy-sweep-deletion
reviewed: 2026-07-16T04:43:54Z
depth: standard
files_reviewed: 41
files_reviewed_list:
  - app/db/repo/__init__.py
  - app/db/repo/demo.py
  - app/db/repo/emails.py
  - app/db/repo/job_settlement.py
  - app/db/repo/jobs.py
  - app/db/repo/operator_resume_resolutions.py
  - app/db/repo/pipeline_state.py
  - app/db/repo/runs.py
  - app/db/schema.sql
  - app/db/schema_introspect.py
  - app/models/job.py
  - app/models/status.py
  - app/pipeline/orchestrator.py
  - app/pipeline/result.py
  - app/queue/dispatch.py
  - app/queue/drain.py
  - app/queue/handlers/operator_resume.py
  - app/queue/handlers/pipeline.py
  - app/queue/handlers/resume_reply.py
  - app/routes/pipeline_glue.py
  - app/routes/pump.py
  - app/routes/runs.py
  - app/templates/run_detail.html
  - app/templates/runs_list.html
  - tests/conftest.py
  - tests/test_alias_and_run_column_regressions.py
  - tests/test_dashboard.py
  - tests/test_fake_repo_pairing.py
  - tests/test_hitl.py
  - tests/test_job_kind_drift.py
  - tests/test_needs_operator.py
  - tests/test_orchestrator_states.py
  - tests/test_pump_route.py
  - tests/test_queue_drain.py
  - tests/test_queue_durability.py
  - tests/test_reply_redelivery.py
  - tests/test_repo_jobs_sql.py
  - tests/test_resume_pipeline.py
  - tests/test_retrigger_epoch.py
  - tests/test_schema_introspect.py
  - tests/test_stuck_run_recovery.py
findings:
  critical: 2
  warning: 1
  info: 0
  total: 3
status: issues_found
---

# Phase 18: Code Review Report

**Reviewed:** 2026-07-16T04:43:54Z
**Depth:** standard
**Files Reviewed:** 41
**Status:** issues_found

## Summary

The bounded result and atomic-settlement architecture is coherent, but two fail-closed gaps remain in the durable retry path. An expired final-attempt lease can become permanently unreapable after the handler has advanced the run, and a persisted reply is not checked against the job's run before its body is replayed. The Phase 18 regression module also hides a confirmed stale assertion behind its module-wide database skip.

## Critical Issues

### CR-01: Final-attempt reaper can fence the same expired lease forever

**File:** `/Users/pnhek/usf msds/github/payroll_agent/app/db/repo/job_settlement.py:389-406`

**Issue:** The reaper always selects the oldest expired `attempts = max_attempts` lease, but it can settle that row only when `_set_run_error` wins an `EXTRACTING -> ERROR` CAS. A worker may complete the business transition to `AWAITING_REPLY` or `AWAITING_APPROVAL` and then die before `settle_pipeline_job` clears the transport lease; a reclaimed attempt may also leave the run at `COMPUTED` or `SENT`. In every such case `_set_run_error` returns false, the function returns `FENCED`, and the job remains `leased` with an expired final-attempt lease. `claim_job` excludes it because `attempts < max_attempts` is false, while every later reaper call selects the same oldest row again. This makes the row permanent, can consume every pump drain slot as repeated `FENCED` outcomes, and can starve later expired final leases. The live test at `tests/test_queue_durability.py:525-533` currently codifies the stranded state instead of proving eventual settlement.

**Fix:** Lock the associated run and apply an explicit status-aware final-lease matrix in the same transaction. Active crash states should CAS to `ERROR` and dead-letter the job; business-complete or human-wait states should settle the transport row without overwriting authoritative business state. In no valid status may the exact expired final-attempt row remain eligible for selection forever. Add live cases for `COMPUTED`, `SENT`, `AWAITING_REPLY`, and `AWAITING_APPROVAL`, plus a second eligible row to prove one fenced candidate cannot starve the queue.

### CR-02: Resume-reply jobs can replay an email belonging to another run

**File:** `/Users/pnhek/usf msds/github/payroll_agent/app/queue/handlers/resume_reply.py:48-54`

**Issue:** The handler loads an inbound row by `job.email_id` and immediately forwards its body to `resume_pipeline(job.run_id, ...)`, but never checks the row's persisted `run_id` against `job.run_id`. The database has independent foreign keys for `jobs.run_id` and `jobs.email_id`; it has no cross-row constraint tying the email to that run. A malformed, manually inserted, or corrupted queue row can therefore feed one run's client reply into another run's deterministic payroll pipeline. This violates the exact durable-context boundary and can cross business boundaries in a money-moving path.

**Fix:** Before `row_to_inbound`, require a non-null persisted `row["run_id"]` whose canonical UUID equals `job.run_id`; otherwise return the bounded terminal invalid-context result. Add hermetic and live wrong-run/cross-business counterexamples, and keep the body and identifiers out of the diagnostic.

## Warnings

### WR-01: The resume-handler regression module skips a confirmed failing Phase 18 test

**File:** `/Users/pnhek/usf msds/github/payroll_agent/tests/test_resume_pipeline.py:50-56,235-240`

**Issue:** The module-wide `DATABASE_URL` skip also suppresses the newly added fake-repository handler tests, even though they are hermetic. One skipped test still expects `handle_resume_reply` to return `None` after the strict `PipelineResult` cutover. Running the focused case with any `DATABASE_URL` value produces a real assertion failure: the handler correctly returns `PipelineResult(OK)`. The reported default full-suite pass therefore does not exercise this Phase 18 reclaim contract.

**Fix:** Move the fake-repository handler/result tests into an always-run hermetic module (or narrow the skip to tests that truly require a configured database), and change the reclaim assertion to require the explicit `PipelineResult.OK`. Run the focused module both with and without `DATABASE_URL` so environment gating cannot hide contract drift.

---

_Reviewed: 2026-07-16T04:43:54Z_
_Reviewer: the agent (gsd-code-reviewer, generic-agent workaround)_
_Depth: standard_
