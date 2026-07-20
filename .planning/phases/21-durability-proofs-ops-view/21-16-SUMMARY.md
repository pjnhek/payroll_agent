---
phase: 21-durability-proofs-ops-view
plan: 16
subsystem: database
tags: [postgres, schema-migration, pytest, unique-constraint, deploy]

requires:
  - phase: 21-durability-proofs-ops-view
    provides: "plan 21-13's try/finally CHECK-restoration hygiene in test_deployed_schema_repair_accepts_authorization_expired, and the data-isolation workaround this plan removes"
provides:
  - "app/db/schema.sql's non-reset email_messages migration no longer aborts the entire schema apply when a deployed database holds an epoch-distinct retrigger pair — the exact command deploy-migrate.yml runs against production on every deploy"
  - "tests/test_schema_migration.py — the first test coverage anywhere in the suite for app.db.bootstrap's non-reset apply path, running against real scratch databases"
  - "test_deployed_schema_repair_accepts_authorization_expired now proves the failure_category repair against realistic accumulated deployed data, not an artificially isolated table"
affects: [21-03, 21-08]

tech-stack:
  added: []
  patterns:
    - "a live-DB regression test that needs a non-standard or legacy database shape (not the shared seeded_db target) creates and drops its own uniquely-named scratch database on the same Postgres server via CREATE DATABASE / DROP DATABASE ... WITH (FORCE), and temporarily repoints DATABASE_URL + clears get_settings()'s lru_cache to run app.db.bootstrap.bootstrap() against it — never against the shared DATABASE_URL target"
    - "a schema migration widening a UNIQUE constraint must guard its ADD on both the absence of the constraint it creates AND never assume a duplicate-tolerant intermediate step is safe to keep 'for symmetry' — an unconditional ADD against live data is a live production hazard, not idempotency"

key-files:
  created:
    - tests/test_schema_migration.py
  modified:
    - app/db/schema.sql
    - tests/test_queue_durability.py

key-decisions:
  - "Removed the obsolete uq_email_run_purpose_round ADD entirely rather than guarding it on the 4-column successor's absence too — the constraint is dead weight with no application-code dependency (confirmed via grep) and the next migration block already reaches the 4-column end state safely from both a fresh DB and a legacy 2-column DB without it"
  - "Deleted test_queue_durability.py's _isolate_outbound_history_before_widening_migration helper rather than keeping it as defense-in-depth — it existed solely to dodge the schema defect this plan fixes, and keeping it would have continued masking the schema-repair test against realistic deployed data even though the crash it avoided is now impossible"

requirements-completed: []

coverage:
  - id: D1
    description: "Non-reset bootstrap succeeds against a database holding the documented epoch-distinct retrigger shape (two email_messages rows sharing (run_id, purpose, round), differing only in epoch), and stays idempotent across repeated non-reset applies"
    verification:
      - kind: unit
        ref: "tests/test_schema_migration.py::test_nonreset_bootstrap_succeeds_against_retrigger_shape_and_is_idempotent"
        status: pass
    human_judgment: false
  - id: D2
    description: "A database carrying only the legacy 2-column uq_email_run_purpose constraint ladders to the 4-column uq_email_run_purpose_round_epoch constraint via non-reset bootstrap, with neither obsolete constraint present"
    verification:
      - kind: unit
        ref: "tests/test_schema_migration.py::test_legacy_two_column_constraint_ladders_to_four_column_epoch_constraint"
        status: pass
    human_judgment: false
  - id: D3
    description: "test_deployed_schema_repair_accepts_authorization_expired now proves the failure_category CHECK repair against the module's real accumulated outbound history (no data isolation), asserting the observable schema outcome — exactly one CHECK survives, it is the modern constraint by name, and its vocabulary includes authorization_expired — rather than merely the absence of an exception"
    verification:
      - kind: unit
        ref: "tests/test_queue_durability.py::test_deployed_schema_repair_accepts_authorization_expired"
        status: pass
      - kind: other
        ref: "manual red-proof: with app/db/schema.sql's fix temporarily reverted, tests/ -m queueproof (full selection) -> test_deployed_schema_repair_accepts_authorization_expired FAILED with UniqueViolation: could not create unique index \"uq_email_run_purpose_round\"; reverted back, same selection -> 75 passed, 0 skipped"
        status: pass
    human_judgment: false

duration: ~20min
completed: 2026-07-20
status: complete
---

# Phase 21 Plan 16: Fix the Live Deploy-Blocking Schema Defect and Remove the Test-Side Masking Summary

**Removed the obsolete `uq_email_run_purpose_round` ADD in `app/db/schema.sql` that aborted every non-reset production migration once a retriggered run existed, added the first-ever test coverage for the non-reset bootstrap path, and un-masked `test_deployed_schema_repair_accepts_authorization_expired` so it proves the CHECK repair against real accumulated data instead of an artificially cleaned table.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-20T19:12:51Z
- **Completed:** 2026-07-20T19:29:01Z
- **Tasks:** 2
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments

- **Reproduced the live defect before touching anything.** On a scratch database, bootstrapped fresh, inserted a business/payroll_run/two `email_messages` rows sharing `(run_id, purpose, round)` and differing only in `epoch` (the documented retrigger shape), then ran `python -m app.db.bootstrap` — the exact command `deploy-migrate.yml:53` runs against production on every deploy. It raised `psycopg.errors.UniqueViolation: could not create unique index "uq_email_run_purpose_round" DETAIL: Key (run_id, purpose, round)=(22222222-..., confirmation, 1) is duplicated`, matching the plan's pasted repro exactly.
- **Removed the obsolete 3-column ADD** (`app/db/schema.sql:342-349` in the pre-fix file) that was guarded only on its own absence, never on the presence of its 4-column successor `uq_email_run_purpose_round_epoch`. Kept the `DROP CONSTRAINT uq_email_run_purpose` step, which is still a live migration for genuinely legacy 2-column databases. Confirmed via `grep -rn "uq_email_run_purpose_round" app/ | grep -v _epoch` that nothing in application code depends on the deleted constraint's name — `insert_email_message`'s `ON CONFLICT` arbiter is already the 4-column tuple.
- **Re-ran the reproduction post-fix**: bootstrap succeeded, and running it a second and third time (idempotency) also succeeded, against the same scratch database still holding the retrigger-shape rows.
- **Proved the migration ladder end to end on a legacy-shaped database**, not argued: built a database whose `email_messages` table carries ONLY the 2-column `uq_email_run_purpose` constraint (no `epoch` column at all — the earliest historical shape), ran non-reset bootstrap once, and confirmed it lands on `uq_email_run_purpose_round_epoch` alone, with neither `uq_email_run_purpose` nor `uq_email_run_purpose_round` present, and the `epoch` column added.
- **Created `tests/test_schema_migration.py`** — the first test coverage anywhere in the suite for `app.db.bootstrap`'s non-reset apply path (every other schema-touching test goes through the shared `seeded_db` fixture, which always resets). Each test creates and drops its own uniquely-named scratch Postgres database on the same server as `DATABASE_URL`, rather than touching the shared assigned target, so these deliberately legacy/broken schema states can never leak into another live-DB module's fixture.
- **Red-proved the new regression test**: temporarily restored the deleted ADD in `app/db/schema.sql`, re-ran `tests/test_schema_migration.py` — `test_nonreset_bootstrap_succeeds_against_retrigger_shape_and_is_idempotent` failed with the same `UniqueViolation` naming `uq_email_run_purpose_round`. Reverted; both tests green again.
- **Removed the masking from `test_deployed_schema_repair_accepts_authorization_expired`**: deleted the `_isolate_outbound_history_before_widening_migration()` helper and its call, which had been clearing the module's accumulated outbound history specifically so the (now-fixed) unguarded ADD would never trip during this test's `bootstrap(reset=False)` call. With the schema fix landed, that isolation is no longer needed to avoid a crash — and removing it means the test now runs against the SAME accumulated retrigger-shaped state production would have, proving the repair genuinely completes rather than proving it completes only against sanitized data. Strengthened the assertions to name the surviving constraint explicitly (the modern one by name, confirmed the legacy one installed earlier in the test is gone) in addition to the existing category-set comparison.
- **Red-proved the un-masked test, in the full selection only**: temporarily reverted the schema fix and ran `tests/ -m queueproof` (the full selection, per the plan's explicit warning that a single-file run does not reproduce this — confirmed: `pytest tests/test_queue_durability.py::test_deployed_schema_repair_accepts_authorization_expired` alone still passed even with the fix reverted, because no earlier test in that lone run had left duplicate-epoch rows behind). In the full `-m queueproof` selection, the test failed at `bootstrap(reset=False)` with the same `UniqueViolation`. Reverted the schema.sql edit back (confirmed byte-identical to the committed fix via `git diff --stat`); full selection green again.
- **Confirmed all seven tests in the `authorization_expired` cluster pass in the full `-m queueproof` selection**: `test_deployed_schema_repair_accepts_authorization_expired`, `test_pre_provider_authorization_expired_enters_delivery_review` (3 params), and `test_provider_handoff_authorization_expired_at_gateway_boundary_enters_review` (3 params) — 75 passed, 0 skipped.

## Task Commits

Each task was committed atomically:

1. **Task 1: Prove the defect, then remove the obsolete block** - `7472a94` (fix)
2. **Task 2: Remove the masking from the schema-repair test** - `9cd1f52` (test)

## Files Created/Modified
- `app/db/schema.sql` - removed the unguarded `ADD CONSTRAINT uq_email_run_purpose_round`; kept the `uq_email_run_purpose` DROP; left a comment recording why the intermediate constraint is intentionally never created
- `tests/test_schema_migration.py` (new) - non-reset bootstrap regression coverage: the retrigger-shape reproduction + idempotency, and the legacy 2-column-to-4-column migration ladder, both against throwaway scratch databases
- `tests/test_queue_durability.py` - deleted `_isolate_outbound_history_before_widening_migration` and its call in `test_deployed_schema_repair_accepts_authorization_expired`; strengthened that test's assertions to name the surviving constraint explicitly

## Decisions Made
- Deleted the obsolete 3-column ADD entirely rather than guarding it on the 4-column successor's absence (which would have kept it alive but inert) — the constraint has zero live purpose once the 4-column successor exists, and the very next migration block already handles both a fresh DB and a legacy 2-column DB correctly without it. Simpler code, one less thing that could regress.
- Deleted `_isolate_outbound_history_before_widening_migration` rather than keeping it as extra defense — it existed only to route around the schema defect this plan fixes. Keeping it "just in case" would have continued masking the schema-repair test against realistic deployed data, which is the exact failure mode this plan exists to close.

## Deviations from Plan

None — plan executed exactly as written. Both `<critical_context>` warnings were honored: nothing in `app/` depends on the deleted constraint's name (confirmed by grep before editing), and the 2-column-to-4-column ladder was proven with a real legacy-shaped database rather than argued.

## Issues Encountered

- Initial attempt at pasting explanatory comments into `tests/test_schema_migration.py` and `app/db/schema.sql` tripped `tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree` — a reference to the SUMMARY document that produced the change matched the guard's planning-doc-reference pattern. Rewrote the comments to be self-contained (explaining the code without citing the planning artifact that produced it), matching the guard's stated purpose. Re-ran the guard and the full hermetic suite to confirm the baseline (1303 passed) was restored.
- `pytest tests/test_queue_durability.py::test_deployed_schema_repair_accepts_authorization_expired -v` run alone still passed even with the schema fix reverted, which initially looked like the red-proof had failed. This was expected per the plan's explicit warning: the failure is order-dependent on the module's accumulated `seeded_db` state, and a single-file/single-test run starts with none of that accumulated history. Re-ran the full `tests/ -m queueproof` selection, which reproduced the red as required.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The live deploy-blocking defect is closed: `deploy-migrate.yml`'s non-reset `python -m app.db.bootstrap` will no longer abort against a production database that has recorded a retriggered run.
- `app/db/schema.sql`'s non-reset apply path now has real regression coverage (`tests/test_schema_migration.py`), carrying `queueproof` so `concurrency-proof.yml` collects it automatically going forward.
- `test_deployed_schema_repair_accepts_authorization_expired` and the six previously-poisoned `authorization_expired`-cluster tests remain green in the full `-m queueproof` selection, unblocking plans 21-03 and 21-08 (both edit `tests/test_queue_durability.py` and both carry "`-m queueproof` is green with an empty skip report" as an acceptance criterion), same as after plan 21-13.
- Baselines confirmed unchanged or grown by exactly the expected amount: hermetic `1303 passed, 107 skipped` (baseline 1303 passed, 105 skipped — the +2 skips are this plan's two new live-DB tests self-skipping with no `DATABASE_URL`); `-m queueproof` `75 passed, 0 skipped` (baseline 73 + 2 new); full live-DB `1407 passed, 3 skipped` (baseline 1405 + 2 new, same 3 pre-existing skips); `check_proof_inventory` exit 0; `ruff check .` and `mypy --strict app` clean (74 files).

## Self-Check: PASSED

- FOUND: app/db/schema.sql
- FOUND: tests/test_schema_migration.py
- FOUND: tests/test_queue_durability.py
- FOUND: commit 7472a94
- FOUND: commit 9cd1f52

---
*Phase: 21-durability-proofs-ops-view*
*Completed: 2026-07-20*
