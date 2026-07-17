---
phase: 19
reviewed: 2026-07-17T05:11:51Z
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
  critical: 2
  warning: 2
  info: 0
  total: 4
status: issues_found
---

# Phase 19 Code Review

## Narrative Findings (AI reviewer)

### CRITICAL-01 — Authority postflight can reopen writes over invalid or remembering legacy generations

**Path:** `scripts/migrate_operator_resolution_authority.py:38-59`, `scripts/migrate_operator_resolution_authority.py:240-262`, `scripts/migrate_operator_resolution_authority.py:278-292`

The migration explicitly resets legacy overrides to `remember = FALSE`, and the runtime rejects malformed parent states such as an authoritative generation that also has `superseded_by` set. The postflight does not verify either invariant. Its five counters only detect winner counts and non-authoritative rows with a null supersession target. It therefore returns success for at least these unsafe states:

- a legacy override still has `remember = TRUE`;
- an authoritative generation also has `superseded_by` set;
- a losing generation points at a winner from another run or at a non-authoritative generation.

`--reopen-writes` relies on this same incomplete predicate immediately before opening the persistent writer fence. A migration defect or manual/live-data drift can consequently pass the advertised authority gate even though the Phase 19 reader later rejects the generation, or can retain alias-learning intent that was never explicitly approved under the new contract.

**Fix:** Extend `_POSTFLIGHT_SQL` and `_POSTFLIGHT_FIELDS` with zero-required counters for `remember = TRUE` on migrated legacy overrides and for invalid supersession relationships. Validate that an authoritative row has no supersession target, and that every non-authoritative row points to the authoritative generation for the same run. Make `_postflight_ok` require those counters to be zero, and add negative tests for every malformed state before allowing reopen.

### CRITICAL-02 — Reapplying schema resurrects historical clarification rounds after a retrigger

**Path:** `app/db/schema.sql:378-395`

The backfill sets `payroll_runs.clarification_round` to the count of every sent clarification row for the run, across all `reply_epoch` values. Retrigger intentionally resets `clarification_round` to zero and increments `reply_epoch`, while preserving old email rows as immutable audit history. Reapplying `schema.sql` after such a retrigger therefore counts stale prior-epoch sends and raises the current epoch's counter. A run that had three historical sends can immediately look capped in its fresh conversation and escalate to `needs_operator` instead of sending the first new clarification.

The comment calling the update idempotent is only true before epoch-scoped retriggers exist; it is not safe as a permanently re-runnable schema statement.

**Fix:** Restrict the backfill to `email_messages.epoch = payroll_runs.reply_epoch`, using a correlated aggregate or by joining the run inside the aggregate. Prefer an explicit migration marker or a condition that only initializes rows introduced with the new column, so future bootstrap runs cannot recompute mutable current-epoch state from all-time history. Add a regression with prior-epoch sent rows, a retriggered run at round zero, and schema reapplication.

### WARNING-01 — “Exact revision” gate accepts abbreviated commit prefixes

**Path:** `scripts/migrate_operator_resolution_authority.py:266-275`; `tests/test_operator_resolution_migration.py:251-279`

`_revision_is_exact` accepts any lowercase hexadecimal string from 7 to 40 characters, and the green-path test uses a 16-character prefix. That is a bounded prefix, not the exact immutable git revision required by the cutover protocol. The reopen command can print and accept an ambiguous or mistyped prefix while claiming the live Phase 19 artifact was proven.

**Fix:** Require the canonical full 40-character commit SHA (`[0-9a-f]{40}`) and update the positive test to use one. Keep abbreviated values in the rejection matrix.

### WARNING-02 — Schema health treats extra state-machine values as in sync

**Path:** `app/db/schema_introspect.py:415-441`, `app/db/schema_introspect.py:552-560`

The live status and email-purpose checks compute only `expected - live`. A live CHECK constraint that permits all expected values plus a stale or misspelled extra value reports `is_in_sync`. Extra state-machine values are not equivalent to harmless extra columns: the database can persist them while Python enum construction and handlers do not recognize them. This also weakens the schema check used by the writer-fence reopen path.

**Fix:** Compare these two finite state-machine catalogs exactly. Add `unexpected_status_values` and `unexpected_purpose_values` to `SchemaDiff` (or otherwise treat the symmetric difference as drift), include them in `is_in_sync`/diagnostics, and add tests where the live CHECK contains one extra value.

## Verification Notes

- Reviewed the 56 scoped production, migration, template/static, and test files against base `a6efbbf37ee6828680abf6694abf99f0a5acd4ee`.
- Targeted existing coverage passes: `UV_CACHE_DIR=/tmp/gsd-phase19-review-uv-cache uv run --offline --no-sync pytest -q tests/test_operator_resolution_migration.py tests/test_schema_introspect.py` -> `41 passed`.
- The passing targeted suite does not invalidate the findings: its positive reopen case explicitly accepts a short SHA, and it has no negative coverage for `remember=true`, malformed supersession relationships, extra state values, or a prior-epoch clarification backfill.
