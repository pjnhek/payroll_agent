---
phase: 19
fixed_at: 2026-07-17T05:19:15Z
review_path: .planning/phases/19-webhook-cutover-durable-ingest/19-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 19: Code Review Fix Report

**Fixed at:** 2026-07-17T05:19:15Z
**Source review:** .planning/phases/19-webhook-cutover-durable-ingest/19-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4
- Fixed: 4
- Skipped: 0

## Fixed Issues

### CRITICAL-01: Authority postflight can reopen writes over invalid or remembering legacy generations

**Files modified:** `scripts/migrate_operator_resolution_authority.py`, `tests/test_operator_resolution_migration.py`
**Commit:** 28049f4
**Applied fix:** Added fail-closed counters for remembered overrides, superseded authorities, and losers that do not point to the authoritative generation for the same run. Added negative check and reopen-path regressions for every malformed relationship. Status: fixed; requires downstream re-review because this changes cutover logic.

### CRITICAL-02: Reapplying schema resurrects historical clarification rounds after a retrigger

**Files modified:** `app/db/schema.sql`, `tests/test_schema_introspect.py`
**Commit:** cd65f09
**Applied fix:** Scoped the clarification-round backfill and aggregate to `email_messages.epoch = payroll_runs.reply_epoch`, with a schema-reapplication regression that rejects an all-epoch aggregate. Status: fixed; requires downstream re-review because this changes migration logic.

### WARNING-01: Exact revision gate accepts abbreviated commit prefixes

**Files modified:** `scripts/migrate_operator_resolution_authority.py`, `tests/test_operator_resolution_migration.py`
**Commit:** 0e1c340
**Applied fix:** Restricted the deployed revision gate to a canonical lowercase 40-character SHA and expanded the rejection matrix for abbreviated, overlong, and uppercase values. Status: fixed; requires downstream re-review because this changes reopen-gate logic.

### WARNING-02: Schema health treats extra state-machine values as in sync

**Files modified:** `app/db/schema_introspect.py`, `tests/test_schema_introspect.py`
**Commit:** 7363fb8
**Applied fix:** Added unexpected status and purpose diagnostics and made either catalog difference fail schema synchronization. Added regressions for one extra value in each finite catalog. Status: fixed; requires downstream re-review because this changes schema-health logic.

---

_Fixed: 2026-07-17T05:19:15Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 1_
