---
phase: 19
reviewed: 2026-07-17T05:26:04Z
depth: standard
files_reviewed: 56
files_reviewed_list:
  - app/db/bootstrap.py
  - app/db/repo/__init__.py
  - app/db/repo/demo.py
  - app/db/repo/inbound_events.py
  - app/db/repo/job_settlement.py
  - app/db/repo/jobs.py
  - app/db/repo/operator_resume_resolutions.py
  - app/db/schema.sql
  - app/db/schema_introspect.py
  - app/ingest.py
  - app/models/job.py
  - app/queue/dispatch.py
  - app/queue/handlers/ingest.py
  - app/queue/handlers/operator_resume.py
  - app/queue/handlers/pipeline.py
  - app/queue/handlers/resume_reply.py
  - app/routes/dashboard.py
  - app/routes/demo.py
  - app/routes/pipeline_glue.py
  - app/routes/pump.py
  - app/routes/runs.py
  - app/routes/webhook.py
  - app/static/style.css
  - app/templates/index.html
  - app/templates/run_detail.html
  - app/templates/runs_list.html
  - scripts/check_operator_resolution_inventory.py
  - scripts/migrate_operator_resolution_authority.py
  - tests/conftest.py
  - tests/test_background_task_cutover.py
  - tests/test_concurrency_proof.py
  - tests/test_dashboard.py
  - tests/test_demo_fixtures.py
  - tests/test_demo_landing.py
  - tests/test_durable_ingest.py
  - tests/test_fake_repo_pairing.py
  - tests/test_gateway.py
  - tests/test_hitl.py
  - tests/test_ingest.py
  - tests/test_job_kind_drift.py
  - tests/test_needs_operator.py
  - tests/test_operator_resolution_inventory.py
  - tests/test_operator_resolution_migration.py
  - tests/test_queue_drain.py
  - tests/test_queue_durability.py
  - tests/test_reply_redelivery.py
  - tests/test_repo_jobs_sql.py
  - tests/test_resume_pipeline.py
  - tests/test_retrigger_threading.py
  - tests/test_schema_introspect.py
  - tests/test_send_idempotency.py
  - tests/test_stuck_run_recovery.py
  - tests/test_threading.py
  - tests/test_webhook.py
  - tests/test_webhook_dedup_race.py
  - tests/test_webhook_unblocked.py
findings:
  critical: 0
  warning: 1
  info: 0
  total: 1
status: issues_found
---

# Phase 19: Code Review Report

**Reviewed:** 2026-07-17T05:26:04Z
**Depth:** standard
**Files Reviewed:** 56
**Status:** issues_found

## Summary

All four findings from the first review are resolved by the committed fixes. The authority postflight now rejects remembering overrides and malformed supersession relationships; clarification backfill is scoped to the current reply epoch; deployment revision input requires a canonical 40-character SHA; and a single live state-machine CHECK containing extra values now produces schema drift.

The full persisted scope was reviewed again after those changes. One distinct schema-health false-pass remains when PostgreSQL has more than one CHECK constraint on the same state-machine column.

## Original Finding Resolution

| Original finding | Result | Evidence |
|---|---|---|
| CRITICAL-01: incomplete authority postflight | Resolved | `28049f4` adds zero-required counters for remembered overrides, authoritative rows with supersession targets, and losers not pointing to the authoritative generation for the same run; reopen consumes the expanded predicate. |
| CRITICAL-02: all-epoch clarification backfill | Resolved | `cd65f09` groups by `(run_id, epoch)` and joins `sub.epoch` to the run's current `reply_epoch`. |
| WARNING-01: abbreviated deployment revision | Resolved | `0e1c340` requires exactly 40 lowercase hexadecimal characters and rejects short, long, and uppercase inputs. |
| WARNING-02: extra live state value accepted | Resolved for the reported single-constraint case | `7363fb8` records unexpected status/purpose values and makes them fail `SchemaDiff.is_in_sync`. |

## Narrative Findings (AI reviewer)

### WR-01 — Multiple CHECK constraints are unioned, masking restrictive schema drift

**File:** `app/db/schema_introspect.py:431-453`

**Issue:** `diff_against_live` gathers every CHECK whose constrained column is `payroll_runs.status` or `email_messages.purpose`, then unions all values into one set with `|=`. PostgreSQL applies multiple CHECK constraints with AND semantics, not OR semantics. If the expected status CHECK exists alongside a second restrictive CHECK such as `status IN ('received')`, the union is still the complete expected set and the health check returns `is_in_sync=True`, even though nearly every legal application transition will fail at the database. An unparseable second CHECK is similarly ignored because it contributes an empty set. The same false-pass is used by `/health/schema`, the schema CLI, and the writer-fence reopen gate.

This was reproduced against the existing hermetic schema-introspection test double by supplying the normal expected status constraint plus `CHECK (status = ANY (ARRAY['received'::text]))`; the current result was `is_in_sync=True` with empty diagnostics.

**Fix:** Preserve constraints as separate parsed rows instead of unioning them. For these exact finite state-machine catalogs, fail closed unless each column has exactly one parseable CHECK and that CHECK's value set exactly equals the expected set. Alternatively, compute the actual intersection while separately rejecting any unparseable or additional constraint. Add regression cases for an expected CHECK plus a restrictive second CHECK and for an expected CHECK plus an unparseable second CHECK.

## Verification Notes

- Persisted-scope test run: `487 passed, 55 skipped` in 173.51s. The skips are guarded live-database cases unavailable to the local run.
- Ruff across all scoped Python source and test files: `All checks passed!`.
- No source file was modified during re-review.

---

_Reviewed: 2026-07-17T05:26:04Z_
_Reviewer: the agent (gsd-code-reviewer generic-agent workaround)_
_Depth: standard_
