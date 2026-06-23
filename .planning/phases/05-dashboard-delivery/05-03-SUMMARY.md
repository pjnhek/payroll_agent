---
phase: 05-dashboard-delivery
plan: 03
subsystem: database
tags: [postgres, psycopg, cas, atomic, schema, ddl, validation, payroll]

# Dependency graph
requires:
  - phase: 05-01
    provides: Wave 0 RED stubs for claim_status and validate D-05 tests (green targets)
  - phase: 05-02
    provides: Wave 0 RED stubs for delivery, dashboard, pdf, compose_confirmation
provides:
  - claim_status(run_id, expected, new) CAS atomic helper in repo.py (D-12/FOUND-04)
  - _TERMINAL_STATUSES fix — RunStatus.APPROVED removed (D-13b: delivery failure can route approved runs to ERROR)
  - Invariant doc updated to "two writers" in repo.py module docstring and set_status docstring
  - set_alias_candidates(run_id, candidates) helper in repo.py (D-04 separate JSONB column)
  - get_outbound_message_id(run_id, purpose) — purpose-aware + send_state='sent' filtered (R2-HIGH fix, CLAR-04)
  - insert_email_message UPSERT on (run_id, purpose) for outbound rows (NEW-1 D-13c sharpening)
  - schema.sql DDL: alias_candidates JSONB on payroll_runs; purpose TEXT + send_state TEXT (nullable) + uq_email_run_purpose UNIQUE on email_messages
  - DDL confirmed applied live on dev DB (Task 3 checkpoint passed)
  - resume_pipeline CAS refactor in orchestrator.py — closes CR-02 non-atomic race (D-12)
  - validate.py D-05 OT rule: weekly >40h / biweekly >80h with no/zero overtime emits ValidationIssue
affects:
  - 05-04 (dashboard routes — reads payroll_runs.alias_candidates, email_messages.purpose)
  - 05-05 (delivery — write send_state='sent' via insert_email_message; uses uq_email_run_purpose upsert)
  - 05-06 (PDF / compose_confirmation)
  - 05-07 (alias write gate — writes to alias_candidates via set_alias_candidates)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CAS atomic status claim: UPDATE payroll_runs SET status=%s WHERE id=%s AND status=%s RETURNING id; returns bool"
    - "DO $$ pg_constraint guard: idempotent ADD CONSTRAINT via pg_constraint check (Postgres has no ADD CONSTRAINT IF NOT EXISTS)"
    - "send_state nullable column: inbound rows keep NULL; outbound rows written 'sent' by gateway; 'reserved'/'failed' for Phase 6 crash-safe lifecycle"
    - "Purpose-aware idempotency: get_outbound_message_id(run_id, purpose) + send_state='sent' filter — reserved/failed rows do not count as proof-of-delivery"
    - "UPSERT on (run_id, purpose): outbound insert_email_message resolves retry-over-reserved constraint crash (NEW-1 D-13c)"

key-files:
  created: []
  modified:
    - app/db/repo.py
    - app/db/schema.sql
    - app/pipeline/orchestrator.py
    - app/pipeline/validate.py
    - tests/conftest.py
    - tests/test_delivery.py
    - tests/test_persistence.py
    - tests/test_threading.py

key-decisions:
  - "D-12: claim_status is the second sanctioned status writer (alongside set_status); every contended gate uses CAS not load-then-set"
  - "D-13b: RunStatus.APPROVED is NOT terminal — delivery failure after approval must route to ERROR for retriggering"
  - "D-13c sharpened (NEW-1): insert_email_message upserts on (run_id, purpose) so retry over a reserved/failed row advances to sent rather than crashing on the unique constraint"
  - "send_state nullable (not NOT NULL DEFAULT 'sent'): inbound rows must never appear 'sent' — weakened audit semantics was the R2-MEDIUM risk rejected"
  - "D-05 OT rule: explicit hours_overtime=0 treated same as absent — never silently underpays"
  - "DO $$ pg_constraint guard is the only correct idempotent pattern for named constraint migration (ADD CONSTRAINT IF NOT EXISTS is invalid Postgres syntax)"

patterns-established:
  - "CAS pattern: claim_status bool return; losing caller returns cleanly; no exception on lost race"
  - "Purpose-aware outbound query: always pass purpose= to get_outbound_message_id; ValueError on invalid value"
  - "Validate pure: D-05 OT rule reads only submitted hours fields — no calculate.py import"

requirements-completed:
  - FOUND-04
  - INGEST-05

# Metrics
duration: ~35min (Tasks 1+2 by prior agent; Task 3 = human checkpoint verified by user)
completed: 2026-06-22
---

# Phase 05 Plan 03: Atomic Status-Claim Slice Summary

**claim_status CAS helper + _TERMINAL_STATUSES fix + schema DDL (alias_candidates, purpose, send_state, uq_email_run_purpose) applied live + resume_pipeline race closed + D-05 OT validation rule**

## Performance

- **Duration:** ~35 min (Tasks 1-2 automated; Task 3 = human-verified live-DB DDL apply)
- **Started:** 2026-06-22T18:16Z (Task 1 commit timestamp)
- **Completed:** 2026-06-22
- **Tasks:** 3 (Task 1 + Task 2 automated; Task 3 = checkpoint passed)
- **Files modified:** 8

## Accomplishments

- Race-safe approval gate: `claim_status(run_id, expected, new)` CAS atomic helper in repo.py — double-approval structurally impossible (D-12/FOUND-04 closed)
- Schema DDL confirmed live: `alias_candidates JSONB` on payroll_runs; `purpose TEXT` + `send_state TEXT` (nullable) + `uq_email_run_purpose UNIQUE` on email_messages — verified via information_schema (Task 3 checkpoint passed by user)
- D-05 OT validation rule in validate.py: weekly employee with >40h regular hours and no/zero OT emits ValidationIssue — the "Bob worked 45h with no overtime" demo beat now flows to the clarification gate
- CR-02 non-atomic seam closed: resume_pipeline uses `claim_status(AWAITING_REPLY, EXTRACTING)` — late/duplicate replies drop cleanly without re-running the pipeline
- R2-HIGH proof-of-delivery fix: `get_outbound_message_id(run_id, purpose)` now filters `AND send_state='sent'` — a pre-send-crash `reserved` row or `failed` row never counts as proof of delivery

## Task Commits

Each task was committed atomically:

1. **Task 1: claim_status CAS + _TERMINAL_STATUSES fix + schema DDL** - `a315040` (feat)
2. **Task 2: resume_pipeline CAS refactor + over-40-no-OT validate rule** - `3dda7b9` (feat)
3. **Task 3 (checkpoint): Live-DB DDL apply** - Human-verified; `uv run python -m app.db.bootstrap` applied by user; all information_schema checks passed (alias_candidates, purpose, send_state nullable, uq_email_run_purpose present)

## Files Created/Modified

- `app/db/repo.py` — claim_status CAS helper; _TERMINAL_STATUSES fix (APPROVED removed); invariant doc updated to "two writers"; set_alias_candidates helper; get_outbound_message_id(run_id, purpose) + send_state='sent' filter; insert_email_message UPSERT on (run_id, purpose)
- `app/db/schema.sql` — alias_candidates JSONB on payroll_runs; purpose TEXT + send_state TEXT (nullable) + uq_email_run_purpose UNIQUE on email_messages; idempotent ALTERs + DO $$ pg_constraint guard for the unique key
- `app/pipeline/orchestrator.py` — resume_pipeline CAS refactor: claim_status(AWAITING_REPLY, EXTRACTING) replaces non-atomic load_run+set_status at CR-02 seam
- `app/pipeline/validate.py` — _employee_pay_periods_per_year helper + D-05 OT rule loop (weekly >40h / biweekly >80h with no/zero OT → ValidationIssue)
- `tests/conftest.py` — InMemoryRepo extended with claim_status + set_alias_candidates stubs
- `tests/test_delivery.py` — Fixed 3 incorrect SQL-string assertions (parameterized SQL puts values in params, not the SQL string); updated for purpose-aware get_outbound_message_id
- `tests/test_persistence.py` — Fixed 'approved' terminal example to 'sent'; added test_record_run_error_processes_approved_run for D-13b contract
- `tests/test_threading.py` — _MiniStore extended with claim_status stub; patched in two threading tests

## Decisions Made

- D-12 closed: claim_status is the second sanctioned status writer; all contended gates use CAS (not load-then-set)
- D-13b applied: RunStatus.APPROVED removed from _TERMINAL_STATUSES — a delivery failure after approval must route to ERROR so the operator can retrigger
- D-13c sharpened (NEW-1 Codex finding): insert_email_message upserts on (run_id, purpose) for outbound rows — turns a retry over a prior reserved/failed row into a sent-advancement instead of a unique constraint crash
- send_state nullable (not NOT NULL DEFAULT 'sent'): inbound rows have no send lifecycle; giving them 'sent' by default weakened audit semantics (R2-MEDIUM risk rejected)
- D-05 OT explicit-zero decision: `hours_overtime=0` treated same as absent — never silently underpays a weekly employee

## Deviations from Plan

None — plan executed exactly as written. The D-13c sharpening (NEW-1 upsert interaction) and R2-HIGH send_state guard were already incorporated into the plan's action block and deviation_note from prior Codex reviews.

## Issues Encountered

None. The three Wave 0 RED import-error stubs (`test_alias_write.py`, `test_compose_confirmation.py`, `test_pdf.py`) and the three dashboard route stubs (`test_dashboard.py`) are pre-existing Wave 0 stubs from plans 05-01 and 05-02 — they are expected RED until their respective later plans (05-04 through 05-07) implement those features. No regressions introduced by this plan.

**Verification result:**
- `tests/test_claim_status.py` + `tests/test_validate.py` D-05 cases: 14 passed, 1 skipped (integration live-DB test skipped, expected)
- Full mocked suite (excluding known Wave 0 stubs): 337 passed, 14 deselected
- `RunStatus.APPROVED not in _TERMINAL_STATUSES`: PASS
- Live-DB DDL (Task 3 checkpoint): all information_schema checks PASS (alias_candidates, purpose, send_state nullable, uq_email_run_purpose)

## User Setup Required

None — the live-DB DDL was applied at the Task 3 checkpoint by the user (`uv run python -m app.db.bootstrap`).

## Next Phase Readiness

- Plan 05-04 (dashboard routes) can proceed: `alias_candidates`, `purpose`, `send_state` columns exist in the live DB
- Plan 05-05 (delivery wiring) can proceed: `insert_email_message` UPSERT and `uq_email_run_purpose` constraint are live; `get_outbound_message_id(run_id, purpose)` is purpose-aware and delivery-proven
- Plan 05-07 (alias write gate) can proceed: `set_alias_candidates` helper is in repo.py; `alias_candidates` column is live
- D-05 OT rule is live in validate.py: the demo's "Bob worked 45h with no OT" clarification beat works

---
*Phase: 05-dashboard-delivery*
*Completed: 2026-06-22*
