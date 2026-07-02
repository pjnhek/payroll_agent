---
phase: 08-data-layer-hygiene-diagnostics
plan: 01
subsystem: database
tags: [postgres, schema, indexes, enum-drift-guard, ci]

# Dependency graph
requires:
  - phase: 07.5-clarification-reply-field-regression
    provides: the current schema.sql / RunStatus baseline this plan edits (pre_clarify_extracted, clarified_fields columns; 11-value status enum)
provides:
  - "app/db/schema.sql: nullable payroll_runs.error_detail TEXT column (OPS2-01 storage target)"
  - "app/db/schema.sql: 3 hot-path CREATE INDEX IF NOT EXISTS statements (OPS2-02) — idx_email_messages_run_direction_state, idx_payroll_runs_created_at, idx_payroll_runs_status"
  - "app/db/schema.sql: businesses.contact_email non-duplication comment (D-8-09)"
  - "app/db/schema.sql: payroll_runs.status CHECK swap to 10 values (needs_clarification removed), inline + idempotent DO-block re-add (folded todo 260623-06)"
  - "app/models/status.py: RunStatus reduced to 10 members, NEEDS_CLARIFICATION removed"
  - "tests/test_status_drift.py: dedicated DO-block value-list drift guard (independent of the inline-CHECK parser), D-8-10 index static guard class, file-wide needs_clarification-absence guard"
affects: [08-02-repo-logic, 08-03-wiring-and-live-checkpoint, 09-transaction-surgery]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Idempotent DO $$ DROP+ADD pattern for swapping a named CHECK constraint on an existing table (mirrors the proven email_messages.purpose D-7.5-03a pattern), narrowed by contype='c' AND conrelid=... AND conname LIKE '%status%' before the DROP"
    - "Dual-location SQL CHECK drift guard: a SEPARATE regex parser locates the DO-block's re-add value list by searching AFTER the constraint-name literal, so the original single-parser guard (which only ever finds the first CHECK match) cannot silently miss a stale DO-block value"

key-files:
  created: []
  modified:
    - app/db/schema.sql
    - app/models/status.py
    - tests/test_status_drift.py
    - tests/test_models_contracts.py

key-decisions:
  - "error_detail is purely additive alongside error_reason (D-8-03 unchanged) — nullable TEXT, no DEFAULT, no NOT NULL"
  - "businesses.contact_email gets no new index — its existing NOT NULL UNIQUE constraint's implicit index already serves find_business_by_sender (D-8-09, verify don't duplicate)"
  - "idx_email_messages_run_direction_state column order (run_id, direction, send_state) locked by D-8-09, traced against live repo.py predicates in 08-RESEARCH.md Pattern 3"
  - "payroll_runs.status CHECK swap edits BOTH the inline CREATE TABLE CHECK (fresh bootstrap) and adds a new idempotent DO-block (existing-table re-apply) — the DO-block reuses the exact D-7.5-03a atomic DROP+ADD pattern"
  - "The codex review MEDIUM #5 gap (the original _extract_check_in_values regex only ever finds the FIRST CHECK match, i.e. can never see the DO-block's re-add list) is closed by a new dedicated parser (_extract_do_block_status_values) and its own test, independent of the inline-CHECK guard"

patterns-established:
  - "D-8-10 static index guard: a TestIndexStaticGuard class in test_status_drift.py asserts exact column order + presence of every new hot-path index via regex against schema.sql text, no DB connection — the live half of the guard is deferred to 08-03"

requirements-completed: [OPS2-01, OPS2-02]

# Metrics
duration: 12min
completed: 2026-07-02
---

# Phase 8 Plan 01: Data Layer Schema Baseline Summary

**Landed the additive `error_detail` column, the project's first 3 `CREATE INDEX IF NOT EXISTS` statements, and the `payroll_runs.status` CHECK swap removing the dead `needs_clarification` value — with a new dedicated DO-block drift guard that closes a codex-review-flagged gap where the original enum/CHECK parser could only ever see the first CHECK match in the file.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-02T20:41:00Z
- **Completed:** 2026-07-02T20:54:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- `app/db/schema.sql` gained the nullable `error_detail TEXT` column, 3 new hot-path indexes with the researched column orders, and a `contact_email` non-duplication comment — all hermetic DDL-source edits, no live-DB write.
- `RunStatus` reduced from 11 to 10 members (`NEEDS_CLARIFICATION` removed); both the inline `CREATE TABLE` CHECK and a new idempotent DO-block re-add on `payroll_runs.status` mirror the 10-value set.
- Closed the codex MEDIUM #5 review finding: `tests/test_status_drift.py` now has a SEPARATE parser (`_extract_do_block_status_values`) and dedicated test (`test_do_block_status_check_matches_enum`) that specifically verifies the DO-block's re-add value list against `RunStatus`, independent of the inline-CHECK parser that could previously only ever see the first match.

## Task Commits

1. **Task 1: schema.sql — error_detail column + 3 hot-path indexes + contact_email coverage comment** - `04295a6` (feat)
2. **Task 2: NEEDS_CLARIFICATION removal — status.py enum + schema.sql CHECK swap + drift-guard/contract test updates** - `c523e45` (feat)

## Files Created/Modified
- `app/db/schema.sql` - added `error_detail` column, 3 `CREATE INDEX IF NOT EXISTS` statements, `contact_email` coverage comment, swapped `payroll_runs.status` CHECK (inline + DO-block) to 10 values, corrected stale "11 values" comment
- `app/models/status.py` - removed `NEEDS_CLARIFICATION` member; updated docstrings to "10 pipeline status values" / "Ten-state lifecycle"
- `tests/test_status_drift.py` - added `_extract_do_block_status_values` helper, `test_do_block_status_check_matches_enum`, `test_needs_clarification_absent_file_wide`, renamed `test_status_exact_count_is_eleven` → `test_status_exact_count_is_ten` (value 10), added `TestIndexStaticGuard` class (6 tests: 3 index-presence/column-order, exactly-3-indexes count, contact_email UNIQUE coverage, uq_email_run_purpose presence, hermetic AST guard)
- `tests/test_models_contracts.py` - updated `test_run_status_count` (11→10) and `test_run_status_values` expected set (removed `"needs_clarification"`)

## Decisions Made
- Followed the plan's exact DO-block adaptation of the proven `email_messages.purpose` D-7.5-03a pattern for the `payroll_runs.status` CHECK swap — no deviation.
- Chose to phrase the schema.sql comment about the removed status value without the literal string `needs_clarification` (e.g. "removing the dead needs-clarification value") so the plan's file-wide zero-occurrence acceptance criterion holds even inside explanatory comments — this is a stricter reading of "zero occurrences file-wide" than just the CHECK definitions, matching the plan's own stated intent ("inline CHECK, DO-block, and any stray comment").

## Deviations from Plan

None - plan executed exactly as written (with the one comment-wording clarification above, which is not a deviation from the plan's intent but a literal-compliance detail).

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required. This plan makes no live-DB call; the live `schema.sql` re-apply is deferred to the 08-03 blocking checkpoint.

## Next Phase Readiness

- `app/db/schema.sql` and `app/models/status.py` are now the clean, 10-value, index-augmented baseline that Plan 08-02 (repo.py logic) and Plan 08-03 (wiring + live checkpoint) can build on without touching either file again.
- Full test suite green: 501 passed, 37 skipped (baseline was 492 passed / 36 skipped — the delta is the new hermetic guard tests added by this plan; zero regressions).
- No live-DB apply has happened yet — 08-03's blocking checkpoint still owns applying this DDL to local + Supabase.

---
*Phase: 08-data-layer-hygiene-diagnostics*
*Completed: 2026-07-02*
