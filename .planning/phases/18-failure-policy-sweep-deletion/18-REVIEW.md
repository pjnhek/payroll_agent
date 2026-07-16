---
phase: 18-failure-policy-sweep-deletion
reviewed: 2026-07-16T16:34:01Z
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
  critical: 0
  warning: 0
  info: 0
  total: 0
status: clean
---

# Phase 18: Code Review Report

**Reviewed:** 2026-07-16T16:34:01Z
**Depth:** standard
**Files Reviewed:** 41
**Status:** clean

## Summary

All reviewed files meet the applicable correctness, security, and robustness standards. No actionable issues were found.

The two prior critical findings and the skipped-regression warning are closed:

- Final-attempt settlement now locks the selected transport row and its associated run in one transaction, applies a disjoint and exhaustive `RunStatus` disposition, preserves authoritative human-wait/completed/error states, transitions active crash states to bounded `ERROR`, and dead-letters every valid selected transport row. The update clears both lease fields while preserving `last_error`; the oldest preserved-state candidate can no longer starve the next candidate.
- Persisted reply handling canonicalizes `row["run_id"]` and requires exact equality with `job.run_id` before `row_to_inbound`, reclaim, or orchestration. Null, malformed, same-business wrong-run, and cross-business ownership all fail closed with one bounded, identifier-free diagnostic.
- `tests/test_resume_pipeline.py` no longer has a module-wide `DATABASE_URL` guard, and the reclaim assertion requires the explicit `PipelineOutcome.OK` contract.

The transaction and lock ordering is coherent across normal settlement and final-lease reaping: both acquire the job row before the associated run row, the exact expired-final-attempt predicate is established under `FOR UPDATE SKIP LOCKED`, and any failure after the run write rolls back the transport and business-state changes together.

## Verification Evidence

- Hermetic focused run with `DATABASE_URL` unset: **99 passed** (`tests/test_resume_pipeline.py`, `tests/test_queue_drain.py`, and `tests/test_pump_route.py`).
- Complete resume module with a harmless `DATABASE_URL` stub: **31 passed**.
- Broader reviewed offline selection: **322 passed, 2 skipped**; the two skips were guarded live-database cases, not hermetic reply-handler regressions.
- Ruff passed for all reviewed Python files.
- Mypy passed for the two gap-closure production files.
- The guarded Postgres matrix, rollback, starvation, and reply-association tests were reviewed for substance. They remain environment-gated by both `DATABASE_URL` and `ALLOW_DB_RESET=1`; this review does not claim a live-database execution that was unavailable in the current environment.

## Narrative Findings (AI reviewer)

No Critical, Warning, or Info findings. The review is clean.

---

_Reviewed: 2026-07-16T16:34:01Z_
_Reviewer: the agent (gsd-code-reviewer, generic-agent workaround)_
_Depth: standard_
