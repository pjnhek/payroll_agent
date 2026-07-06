---
phase: 11-clarification-round-machine-alias-learning
plan: 01
subsystem: database
tags: [postgres, schema-migration, psycopg, pydantic, hermetic-tests, round-machine]

# Dependency graph
requires:
  - phase: 09
    provides: "sweep_stranded_runs / claim_status CAS idioms, _STRANDED_SCOPE_STATUSES scope-pin convention, PII-safe logging discipline this plan's new functions follow"
  - phase: 07.5
    provides: "pre_clarify_extracted / clarified_fields columns and repo accessors this plan's clear_reply_context also nulls"
provides:
  - "payroll_runs.clarification_round (NOT NULL DEFAULT 0) + email_messages.round (NOT NULL DEFAULT 0) / consumed_round (nullable) columns"
  - "RunStatus.NEEDS_OPERATOR (11th status) mirrored in both schema.sql CHECK spots"
  - "uq_email_run_purpose widened to uq_email_run_purpose_round (run_id, purpose, round) via one atomic DROP+ADD DO-block"
  - "One-shot idempotent backfills: clarification_round from sent-row counts; alias_candidates flat-to-nested shape migration"
  - "8 new repo.py data-layer primitives: get_clarification_round, set_clarification_round, get_outbound_for_round, mark_reply_consumed, load_consumed_replies, get_inbound_by_message_id, clear_reply_context, find_stranded_unconsumed_replies"
  - "insert_email_message round: int = 0 kwarg with ON CONFLICT arbiter widened in lockstep"
  - "Faithful InMemoryRepo mirrors for all 8 new functions + the round-aware insert_email_message upsert"
affects: [11-02, 11-03, 11-04, 11-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Round-aware outbound send guard: (run_id, purpose, round) replaces (run_id, purpose) as the uniqueness/upsert key everywhere a clarification send is tracked"
    - "Idempotent-by-derivation round increment: get_outbound_for_round returns the found row's own round so a later plan's caller derives round+1 from evidence, never a blind counter increment (crash-safety)"
    - "Single-statement 'clear all reply context' write (clear_reply_context) so a retrigger can never leave partial stale state"

key-files:
  created: []
  modified:
    - app/db/schema.sql
    - app/models/status.py
    - app/db/repo.py
    - tests/conftest.py
    - tests/test_status_drift.py
    - tests/test_models_contracts.py

key-decisions:
  - "Widened uq_email_run_purpose -> uq_email_run_purpose_round in ONE atomic DO-block (DROP old + ADD new) per the existing D-7.5-03a pattern, so a failed ADD rolls back the DROP and a live migration can never end up with neither constraint present"
  - "insert_email_message's round param defaults to 0 and every existing caller (gateway.send_outbound, orchestrator's two record_only branches) is left unchanged in this plan — confirmed via grep across app/ that no caller passes round yet"
  - "get_outbound_for_round returns a dict including the found row's round (not just message_id) specifically so a later plan derives the next round from evidence rather than a blind +1 (Pitfall #3 crash-safety)"
  - "clear_reply_context nulls clarified_fields, pre_clarify_extracted, clarification_round, AND alias_candidates in one UPDATE statement — 'context lost means ALL of it' (D-11-04)"

requirements-completed: [CLAR2-01, CLAR2-02, CLAR2-06, CLAR2-07]

# Metrics
duration: ~35min
completed: 2026-07-06
---

# Phase 11 Plan 01: Round Machine Data-Layer Foundations Summary

**Round/consumed-round columns, the needs_operator status, a widened (run_id, purpose, round) uniqueness constraint, and 8 new repo.py accessors — landed with zero behavior change (round defaults to 0 everywhere, nothing yet reads the new state).**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-07-06T01:08:30Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments
- `payroll_runs.clarification_round` and `email_messages.round`/`consumed_round` columns added to schema.sql (both the fresh-bootstrap inline CREATE TABLE path and the idempotent live-migration ALTER path), plus one-shot backfill/migration DO-blocks for live production rows
- `RunStatus.NEEDS_OPERATOR` added as the enum's 11th member, mirrored in both schema.sql CHECK spots (inline + DO-block re-ADD) — the drift guard (`test_status_drift.py`) forces both locations to agree
- `uq_email_run_purpose` widened to `uq_email_run_purpose_round (run_id, purpose, round)` in one atomic DROP+ADD DO-block; `insert_email_message`'s ON CONFLICT arbiter changed in lockstep in the SAME task so the constraint and the upsert clause can never drift apart
- 8 new repo.py functions covering round lookup, write-once reply consumption, consumed-reply retrieval, persisted-inbound-row lookup, all-context clearing, and the stranded-unconsumed-reply recovery query
- `tests/conftest.py`'s `InMemoryRepo` faithfully mirrors every one of the 8 new functions plus the round-aware `insert_email_message` upsert semantics, so every later Phase 11 plan can write hermetic tests immediately

## Task Commits

Each task was committed atomically:

1. **Task 1: Schema DDL — columns, needs_operator status, widened uniqueness, backfills** - `7674e9e` (feat)
2. **Task 2: repo.py — round/consumed accessors, clear-context, stranded query, ON CONFLICT lockstep** - `a48223f` (feat)
3. **Task 3: conftest.py InMemoryRepo mirrors** - `ffd5c17` (test)

**Plan metadata:** (this commit, immediately following)

## Files Created/Modified
- `app/db/schema.sql` - clarification_round/round/consumed_round columns, needs_operator in both status CHECK spots, uq_email_run_purpose_round widening DO-block, backfill + alias_candidates shape migration DO-blocks
- `app/models/status.py` - `RunStatus.NEEDS_OPERATOR` member, "Ten-state" → "Eleven-state" docstring update
- `app/db/repo.py` - 8 new functions (get_clarification_round, set_clarification_round, get_outbound_for_round, mark_reply_consumed, load_consumed_replies, get_inbound_by_message_id, clear_reply_context, find_stranded_unconsumed_replies), `insert_email_message` round param + ON CONFLICT arbiter change, module docstring inventory updated
- `tests/conftest.py` - InMemoryRepo mirrors for all 8 new functions; insert_inbound_email/insert_email_message fakes now carry direction/round/consumed_round/created_at keys; create_run fake carries clarification_round
- `tests/test_status_drift.py` - RunStatus count assertion updated 10 → 11
- `tests/test_models_contracts.py` - RunStatus count/value-set assertions updated 10 → 11

## Decisions Made
- Widened the unique constraint and changed the ON CONFLICT arbiter in the SAME task (Task 2), per Pitfall #1 in the phase RESEARCH — sequencing them apart would leave a window where `insert_email_message` raises `InvalidColumnReference`
- Kept `insert_email_message`'s `round` param strictly additive (`= 0` default) so this plan introduces zero behavior change; no caller across `app/` was touched to pass a real round value — that is explicitly deferred to Plan 11-02
- `get_outbound_for_round` and its InMemoryRepo mirror both return `{"message_id", "round"}` (not a bare string) specifically so a later plan's round-increment logic derives the next round from the row Postgres actually has, never from an in-process counter that could be stale after a crash

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Hardcoded `RunStatus` count assertions (10) broken by the new enum member**
- **Found during:** Task 1 (adding `NEEDS_OPERATOR` to the enum)
- **Issue:** `tests/test_status_drift.py::test_status_exact_count_is_ten` and `tests/test_models_contracts.py::test_run_status_count`/`test_run_status_values` all hardcode "10" / the 10-value set. Adding the 11th enum member (as the plan's own truths/acceptance-criteria required) would make both tests fail immediately.
- **Fix:** Updated both test files' assertions from 10 to 11 members, and added `needs_operator` to the expected value set in `test_run_status_values`.
- **Files modified:** `tests/test_status_drift.py`, `tests/test_models_contracts.py`
- **Verification:** `uv run pytest -q tests/test_status_drift.py` (18 passed) and full offline suite (548 passed) both green.
- **Committed in:** `7674e9e` (Task 1 commit)

**2. [Rule 1 - Bug] InMemoryRepo's `insert_inbound_email` fake row was missing an explicit `direction` key**
- **Found during:** Task 3 (writing an ad-hoc smoke check of the new mirrors before considering them "real semantics" per Pitfall #7)
- **Issue:** The real `repo.insert_inbound_email` always inserts `direction='inbound'` as a hardcoded SQL literal — it is not a caller-supplied kwarg, so the fake's `row = {"id": eid, **kw}` never actually stored a `direction` key. This was harmless before this plan (nothing read `direction` off a fake inbound row), but the three new mirrors this task adds — `mark_reply_consumed`, `get_inbound_by_message_id`, `find_stranded_unconsumed_replies` — all filter on `row.get("direction") == "inbound"`, so every one of them would have silently never matched a fake inbound row.
- **Fix:** Added an explicit `"direction": "inbound"` key to the fake row dict in `insert_inbound_email`, alongside the new `round`/`consumed_round`/`created_at` defaults.
- **Files modified:** `tests/conftest.py`
- **Verification:** Ran an ad-hoc smoke script (scratchpad, not committed) exercising `set_clarification_round`, the round-aware `insert_email_message` upsert, `get_outbound_for_round`, `mark_reply_consumed` (including its write-once guard), `load_consumed_replies`, `get_inbound_by_message_id`, `clear_reply_context`, and `find_stranded_unconsumed_replies` end-to-end against `InMemoryRepo` directly — all assertions passed after the fix. Full offline suite (548 passed) confirmed unaffected.
- **Committed in:** `ffd5c17` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule-1 bugs, both directly caused by this plan's own changes)
**Impact on plan:** Both fixes are necessary corrections for the exact behavior the plan's own truths/acceptance-criteria require (11 statuses; faithful, real-semantics mirrors per Pitfall #7). No scope creep — neither fix touches orchestrator/main.py or wires any new state into production code paths.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. The live-DB migration checkpoint (applying this schema.sql against the Supabase pooler) is explicitly deferred to a later plan's blocking human checkpoint (per RESEARCH Runtime State Inventory / Assumption A2), not this plan.

## Next Phase Readiness
- All Phase 11 durable foundations are in place: schema columns, the needs_operator status, the widened constraint, all 8 repo primitives, and faithful hermetic mirrors.
- Zero behavior change confirmed: full offline suite (548 passed, 20 skipped, 28 deselected) is identical before and after this plan.
- Plan 11-02 can now wire the round-aware send guard, cap/escape logic, and the accumulated-context builder into `orchestrator.py` against this foundation without touching schema or repo signatures again.
- No blockers.

---
*Phase: 11-clarification-round-machine-alias-learning*
*Completed: 2026-07-06*

## Self-Check: PASSED

- `app/db/schema.sql` — FOUND
- `app/models/status.py` — FOUND
- `app/db/repo.py` — FOUND
- `tests/conftest.py` — FOUND
- `.planning/phases/11-clarification-round-machine-alias-learning/11-01-SUMMARY.md` — FOUND
- Commit `7674e9e` (Task 1) — FOUND in `git log --oneline --all`
- Commit `a48223f` (Task 2) — FOUND in `git log --oneline --all`
- Commit `ffd5c17` (Task 3) — FOUND in `git log --oneline --all`
- `uv run pytest -q -m "not integration and not live_llm"` — 548 passed, 20 skipped, 28 deselected (re-run immediately before this self-check)
- `uv run pytest -q tests/test_status_drift.py` — 18 passed
- `grep -q "ON CONFLICT (run_id, purpose, round)" app/db/repo.py` — PASS
- All plan `<acceptance_criteria>` for Tasks 1-3 re-verified via grep/pytest — PASS
