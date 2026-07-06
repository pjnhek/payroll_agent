---
phase: 11-clarification-round-machine-alias-learning
plan: 06
subsystem: database
tags: [postgres, retrigger, epoch, append-only-audit-log, clarification-round-machine]

requires:
  - phase: 11-01
    provides: "clarification_round / round / consumed_round columns, round-aware repo.py accessors, clear_reply_context"
  - phase: 11-05
    provides: "WR-06 retrigger-clears-all-reply-context call site in app/main.py's retrigger route"
provides:
  - "reply_epoch (payroll_runs) / epoch (email_messages) columns — a per-run conversation-epoch counter"
  - "clear_reply_context bumps reply_epoch on every retrigger, in the same statement as the existing round/snapshot clear"
  - "get_outbound_for_round / load_consumed_replies / find_stranded_unconsumed_replies all scoped to the run's CURRENT epoch"
  - "uq_email_run_purpose_round_epoch — widened UNIQUE constraint + ON CONFLICT arbiter so a retriggered round-0 send can never upsert-mutate a stale pre-retrigger round-0 row"
affects: [11-07, 11-09, 11-10]

tech-stack:
  added: []
  patterns:
    - "Per-run epoch counter as a scope boundary over an append-only audit log: bump-on-clear, stamp-at-write-or-link-time, scope-at-read-time — never delete or mutate historical rows"

key-files:
  created:
    - tests/test_retrigger_epoch.py
  modified:
    - app/db/schema.sql
    - app/db/repo.py
    - tests/conftest.py

key-decisions:
  - "Widened uq_email_run_purpose_round to uq_email_run_purpose_round_epoch (and insert_email_message's ON CONFLICT arbiter to match) — a deviation from the plan's literal Task 2 spec, required because the plan's own Task 1 note correctly identified that (run_id, purpose, round) alone cannot distinguish a retriggered round-0 send from a stale pre-retrigger round-0 row, but Task 2's action items did not widen the ON CONFLICT arbiter that actually collides on that constraint — leaving a live-DB corruption path where a retrigger would silently upsert-mutate history"

patterns-established:
  - "Epoch-scoped audit log reads: any new round-machine reader over email_messages must add `AND epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s)` (or the JOIN-condition equivalent) or it will see stale pre-retrigger state"

requirements-completed: [CLAR2-07]

duration: 45min
completed: 2026-07-06
---

# Phase 11 Plan 06: Retrigger Epoch Mechanism (GAP-2/GAP-3 Closure) Summary

**Per-run `reply_epoch` counter closes GAP-2 (stale round-0 'sent' row silently suppressing a retriggered clarification) and GAP-3 (stale consumed reply re-injected into post-retrigger extraction, mispay risk) without ever deleting or mutating the append-only `email_messages` audit log.**

## Performance

- **Duration:** 45 min
- **Started:** 2026-07-06T20:40:00Z (approx, worktree sync + baseline confirm included)
- **Completed:** 2026-07-06T21:25:36Z
- **Tasks:** 2 (Task 1: schema; Task 2: repo.py + tests, TDD)
- **Files modified:** 3 (app/db/schema.sql, app/db/repo.py, tests/conftest.py) + 1 created (tests/test_retrigger_epoch.py)

## Accomplishments

- `payroll_runs.reply_epoch` and `email_messages.epoch` (both `INT NOT NULL DEFAULT 0`) added via the project's existing idempotent dual-path idiom (inline `CREATE TABLE` column + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) — zero behavior change to any run that never retriggers.
- `clear_reply_context` now bumps `reply_epoch = reply_epoch + 1` in the SAME statement as the existing round/snapshot clear — one atomic write, "context lost means ALL of it" now includes the epoch.
- `link_email_to_run` and `insert_email_message`'s outbound path stamp a row's `epoch` from the owning run's CURRENT `reply_epoch` at write/link time (correlated subquery, zero caller changes).
- `get_outbound_for_round`, `load_consumed_replies`, and `find_stranded_unconsumed_replies` — all three round-machine readers named in the plan — are now epoch-scoped, closing GAP-2 and GAP-3 and the subtler stranded-reply variant.
- Widened `uq_email_run_purpose_round` → `uq_email_run_purpose_round_epoch` (deviation, see below) so the real Postgres `ON CONFLICT` arbiter cannot silently overwrite a stale pre-retrigger row.
- `tests/test_retrigger_epoch.py`: two new regression tests driving the REAL seam (`clear_reply_context`, `_clarify`, `resume_pipeline`, `mark_reply_consumed` — none mocked), proving both a fresh send and a forgotten stale reply, with an explicit append-only assertion (the historical row still exists, untouched, after the retrigger).

## Task Commits

Each task was committed atomically:

1. **Task 1: Schema — reply_epoch / epoch columns** - `88f4ca0` (feat)
2. **Task 2: repo.py — stamp epoch at write time, scope epoch at read time** - `c0ca2f9` (test, RED) + `0d97cea` (feat, GREEN — includes the constraint-widening deviation)

**Plan metadata:** (this commit)

_TDD: Task 2 followed RED (`c0ca2f9`, tests fail against pre-fix code) → GREEN (`0d97cea`, repo.py + conftest.py implementation, all tests pass)._

## Files Created/Modified

- `app/db/schema.sql` — `reply_epoch` (payroll_runs), `epoch` (email_messages), widened `uq_email_run_purpose_round_epoch` constraint + its idempotent live-migration DO-block
- `app/db/repo.py` — `clear_reply_context`, `link_email_to_run`, `insert_email_message`, `get_outbound_for_round`, `load_consumed_replies`, `find_stranded_unconsumed_replies` all epoch-aware
- `tests/conftest.py` — `InMemoryRepo` mirrors all six changes (reply_epoch key, epoch stamping, epoch-scoped filters, epoch-widened upsert key)
- `tests/test_retrigger_epoch.py` (new) — GAP-2 + GAP-3 regression tests

## Decisions Made

- **Widened `uq_email_run_purpose_round` → `uq_email_run_purpose_round_epoch`, and `insert_email_message`'s `ON CONFLICT` arbiter to match.** The plan's Task 1 explicitly reasoned that `(run_id, purpose, round)` alone cannot distinguish a retriggered round-0 send from the stale pre-retrigger round-0 row ("that is precisely GAP-2's bug") and stated Task 2's WHERE-clause scoping was "the actual fix." That is true for the three SELECT-based readers, but `insert_email_message`'s write path uses `INSERT ... ON CONFLICT (run_id, purpose, round) DO UPDATE` — an arbiter that, unwidened, would have caused the retriggered run's fresh round-0 send to silently UPSERT (mutate) the historical pre-retrigger row in a real Postgres database, corrupting the append-only audit log on every retrigger. Caught via TDD: the GAP-2 test initially passed the "does it send" assertion but failed the "does the stale row still exist" append-only assertion, revealing the gap. Fixed by widening the constraint via the exact same atomic DROP+ADD DO-block idiom already established in this file for the `uq_email_run_purpose` → `uq_email_run_purpose_round` migration (D-11-01) — purely additive, idempotent, zero behavior change for any row/run at epoch 0.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Widened uq_email_run_purpose_round to include epoch; widened insert_email_message's ON CONFLICT arbiter to match**
- **Found during:** Task 2 (TDD GREEN phase — the GAP-2 regression test's append-only assertion failed)
- **Issue:** With only the SELECT-side epoch scoping (get_outbound_for_round/load_consumed_replies/find_stranded_unconsumed_replies) implemented per the plan's literal action items, `insert_email_message`'s outbound upsert still used `ON CONFLICT (run_id, purpose, round)` — the pre-existing 3-column constraint. A retriggered run's fresh round-0 clarification send shares an identical `(run_id, purpose, round)` tuple with the stale pre-retrigger round-0 'sent' row (both are round 0, same run, same purpose). In real Postgres this collides on the constraint and the `DO UPDATE` clause overwrites the historical row's `message_id`/`body_text`/`created_at` in place — silently mutating the append-only audit log on every retrigger, which is the exact invariant the plan's own threat model and must_haves require ("email_messages remains strictly append-only — no row is ever deleted or has its historical round/content mutated by a retrigger").
- **Fix:** Widened the UNIQUE constraint from `uq_email_run_purpose_round (run_id, purpose, round)` to `uq_email_run_purpose_round_epoch (run_id, purpose, round, epoch)`, and widened `insert_email_message`'s `ON CONFLICT` arbiter to `(run_id, purpose, round, epoch)` to match. Applied via the same atomic DROP+ADD-in-one-DO-block idiom the file already uses for the D-11-01 `uq_email_run_purpose` → `uq_email_run_purpose_round` widening (idempotent, safe on a live re-apply). Mirrored the widened upsert key in `tests/conftest.py`'s `InMemoryRepo.insert_email_message`.
- **Files modified:** `app/db/schema.sql`, `app/db/repo.py`, `tests/conftest.py`
- **Verification:** `test_retrigger_sends_fresh_clarification_despite_stale_round0_sent_row` now asserts BOTH rows (stale epoch-0 and fresh epoch-1) coexist at round=0 after the fix, distinguished by epoch — proving append-only. Full offline suite stays green (590 passed, 20 skipped).
- **Committed in:** `0d97cea` (part of Task 2's GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 Rule 1 — bug in the plan's own literal spec, caught by TDD before it could reach a real database)
**Impact on plan:** Necessary for correctness — without it, the plan's headline must-have ("email_messages remains strictly append-only") would have been silently violated on every retrigger in production, even though the plan's own regression tests (as literally specified) would not have caught it, because InMemoryRepo's upsert key would need the identical fix to expose the bug. No scope creep — same migration pattern already established in the same file for the identical class of constraint widening.

## Issues Encountered

None beyond the deviation above (caught and fixed within the TDD cycle, no unresolved issues).

## User Setup Required

None — no external service configuration required. The schema changes apply via the existing idempotent bootstrap/live-migration path (`python -m app.db.bootstrap`); no manual migration step needed.

## Next Phase Readiness

- GAP-2 (CR-2) and GAP-3 (CR-3) from `11-REVIEW.md` are closed: a retrigger's fresh round-0 clarification genuinely sends despite a stale pre-retrigger round-0 'sent' row, and a retrigger's resume never re-accumulates a pre-retrigger consumed reply — both proven by tests driving the real seam, with the append-only audit log invariant intact and independently re-verified after the constraint-widening fix.
- CLAR2-07 marked complete.
- Remaining gap-closure plans (11-07 CR-1 operator-resolve double-CAS, 11-09/11-10 CR-4/CR-5 or related) are unaffected by this plan's scope — no shared files besides `app/db/repo.py`/`tests/conftest.py`, which any subsequent plan touching those files should re-diff against before editing.
- No blockers.

## Self-Check: PASSED

- `app/db/schema.sql` — FOUND
- `app/db/repo.py` — FOUND
- `tests/conftest.py` — FOUND
- `tests/test_retrigger_epoch.py` — FOUND
- Commit `88f4ca0` (Task 1: schema) — FOUND in git log
- Commit `c0ca2f9` (Task 2 RED: failing tests) — FOUND in git log
- Commit `0d97cea` (Task 2 GREEN: repo.py + conftest.py + constraint fix) — FOUND in git log
- `uv run pytest -q tests/test_retrigger_epoch.py` — 2 passed
- `uv run pytest -q -m "not integration and not live_llm"` — 590 passed, 20 skipped, 28 deselected (baseline 588 + 2 new, zero regressions)
- `grep -q "epoch" app/db/schema.sql` — PASS

---
*Phase: 11-clarification-round-machine-alias-learning*
*Completed: 2026-07-06*
