---
phase: 11-clarification-round-machine-alias-learning
plan: 02
subsystem: orchestrator
tags: [python, pytest, ast-testing, state-machine, round-machine, escalation]

# Dependency graph
requires:
  - phase: 11
    plan: 01
    provides: "clarification_round/round/consumed_round columns, needs_operator status, uq_email_run_purpose_round constraint, get_clarification_round/set_clarification_round/get_outbound_for_round repo primitives, InMemoryRepo mirrors"
provides:
  - "MAX_CLARIFICATION_ROUNDS = 3 module constant in orchestrator.py with documented derivation"
  - "_clarify's idempotency guard re-keyed from (purpose) to (purpose, round) via repo.get_outbound_for_round — closes WR-05"
  - "Round cap check at the top of _clarify: escalates silently to needs_operator before any LLM/gateway call at the 4th would-be send (D-11-06/D-11-07/D-11-09)"
  - "Idempotent round advance (derived from the sent row, never a blind +1) in all three _clarify finalize paths"
  - "round kwarg threaded through gateway.send_outbound and the record_only insert_email_message call"
  - "needs_operator badge (own 'escalate' CSS class + 'Needs Operator' label) in app/main.py + app/static/style.css"
  - "needs_operator confirmed excluded from IN_FLIGHT_STATUSES, retrigger's stale_statuses, and the sweep scope, each pinned by a test"
  - "tests/test_clarify_rounds.py (CLAR2-01) and tests/test_needs_operator.py (CLAR2-02 escalation half)"
affects: [11-03, 11-04, 11-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cap-then-guard ordering inside a single function: the round cap check runs FIRST (before any LLM/gateway call), the (purpose, round) idempotency guard runs SECOND — both return early, both keep D-9-01 (no transaction spans a provider call) trivially satisfied"
    - "Idempotent-by-derivation round advance: every finalize path computes round+1 from the SENT ROW's own round (via get_outbound_for_round's return value or the just-inserted current_round), never from a blind in-process counter increment — a crash between send and finalize self-heals on re-entry"
    - "AST source-order testing for transaction-shape invariants: parsing the live function body to assert call order inside `with conn.transaction():` blocks, extended from test_atomic_persist.py's existing technique to cover 4 distinct transaction blocks in one function"

key-files:
  created:
    - tests/test_clarify_rounds.py
    - tests/test_needs_operator.py
  modified:
    - app/pipeline/orchestrator.py
    - app/email/gateway.py
    - app/main.py
    - app/static/style.css
    - tests/test_alias_write.py
    - tests/test_atomic_persist.py
    - tests/test_stuck_run_recovery.py

key-decisions:
  - "The round cap check is the textually FIRST transaction block in _clarify's source, placed before the (purpose, round) guard — this covers BOTH call sites (_run_stages' direct call and _defer_field_regression_clarification's Step 5 call) with a single check, and guarantees D-9-01 (no LLM/gateway call before a possible early return) by construction"
  - "gateway.send_outbound gained a round: int = 0 kwarg, threaded straight through to repo.insert_email_message — confirmation sends (which never pass round) are behavior-identical to pre-Phase-11, only the two clarification call sites in _clarify pass round=current_round"
  - "needs_operator's badge class is a NEW 'escalate' CSS class, not a reuse of an existing one — all four existing classes (neutral/pending/good/bad) are already semantically taken by other statuses (pending=awaiting_approval, bad=rejected/error), and needs_operator is neither routine nor a failure, it is an explicit escalation"
  - "Two pre-existing tests (test_alias_write.py, test_atomic_persist.py) that monkeypatched the OLD get_outbound_message_id/purpose-only guard shape were updated to the NEW get_outbound_for_round/(purpose, round) shape — this is the re-keying itself working as designed, not scope creep, since those tests exist specifically to pin _clarify's guard shape"

requirements-completed: [CLAR2-01, CLAR2-02]

# Metrics
duration: ~50min
completed: 2026-07-06
---

# Phase 11 Plan 02: Round-Aware Clarification Guard, Cap & Escalation Summary

**Re-keyed `_clarify`'s idempotency guard from purpose-only to (purpose, round) via a new `get_outbound_for_round` lookup, closing WR-05 (round-2+ questions no longer silently swallowed), and added a 3-round cap that escalates silently to a new `needs_operator` dashboard state with its own badge and confirmed scope exclusions.**

## Performance

- **Duration:** ~50 min
- **Completed:** 2026-07-06T01:30:18Z
- **Tasks:** 3
- **Files modified:** 7 (2 created, 5 modified across production + test code)

## Accomplishments
- `MAX_CLARIFICATION_ROUNDS = 3` module-level constant in `orchestrator.py`, documented STALE_THRESHOLD-style: the counter increments once per clarification send (any purpose), boundary semantics mean counter==3 has already sent 3 times, so the 4th attempt is what escalates.
- `_clarify`'s idempotency guard is now keyed on `(purpose, round)` via `repo.get_outbound_for_round`, replacing the old purpose-only `repo.get_outbound_message_id` lookup — this closes WR-05: a genuinely new round-2+ clarification question now actually sends instead of being silently parked at `awaiting_reply` with no email out.
- A round cap check runs at the very top of `_clarify`, strictly before any LLM or gateway call: at `MAX_CLARIFICATION_ROUNDS`, the run escalates to `needs_operator` with `set_status` as the sole write in its transaction — no new outbound row, no LLM call, no client-facing signal (D-11-09 silent handoff).
- The round advance in all three of `_clarify`'s finalize paths (idempotency early-return, record_only, live gateway) is derived from the SENT row's own round — never a blind counter increment — so a crash between a send and its finalize transaction self-heals correctly on re-entry (Pitfall #3).
- `gateway.send_outbound` gained a `round: int = 0` kwarg threaded through to `repo.insert_email_message`, so the clarification outbound row is stamped with the round it was actually sent at; confirmation sends (which never pass `round`) are behavior-identical to pre-Phase-11.
- `needs_operator` has its own dashboard badge (`.badge-escalate` CSS class, "Needs Operator" label) and is confirmed absent from `IN_FLIGHT_STATUSES`, retrigger's `stale_statuses`, and the stranded-run sweep scope — each exclusion pinned by an explicit test.
- Two new hermetic, unguarded test modules (`tests/test_clarify_rounds.py`, `tests/test_needs_operator.py`) prove the WR-05 fix, the crash-idempotency self-heal, the cap boundary (with a live regression check that neutering the cap check makes the "no LLM/gateway call" assertions fail), the silent-escalation write shape, and badge rendering.

## Task Commits

Each task was committed atomically:

1. **Task 1: `_clarify` — cap check, (purpose, round) guard, idempotent round advance in all three finalize paths** - `e64a0e0` (feat)
2. **Task 2: main.py status surfaces — badge maps, IN_FLIGHT exclusion; scope-exclusion pins** - `5e3a909` (feat)
3. **Task 3: New test modules — test_clarify_rounds.py + test_needs_operator.py** - `2e166a4` (test)

**Plan metadata:** (this commit, immediately following)

## Files Created/Modified
- `app/pipeline/orchestrator.py` - `MAX_CLARIFICATION_ROUNDS` constant; `_clarify`'s cap check + re-keyed `(purpose, round)` guard + idempotent round advance in all 3 finalize paths + `round=current_round` stamped on both sends
- `app/email/gateway.py` - `send_outbound` gained a `round: int = 0` kwarg threaded through to `repo.insert_email_message`
- `app/main.py` - `needs_operator` added to `_BADGE_CLASS` (new `"escalate"` class) and `_BADGE_LABEL` (`"Needs Operator"`); `IN_FLIGHT_STATUSES` and retrigger's `stale_statuses` left untouched (confirmed exclusion)
- `app/static/style.css` - new `.badge-escalate` CSS rule following the existing `.badge-{neutral,pending,good,bad}` idiom
- `tests/test_alias_write.py` - updated `test_clarify_idempotency_skips_if_clarification_already_sent` to mock `get_outbound_for_round`/`get_clarification_round` instead of the retired `get_outbound_message_id` call inside `_clarify`
- `tests/test_atomic_persist.py` - updated `test_clarify_idempotency_path_writes_snapshot_then_status_in_one_transaction` to the new guard shape and extended the ordering pin to include `set_clarification_round` before `set_status`
- `tests/test_stuck_run_recovery.py` - extended the D-9-12 scope-pin test with an explicit `"needs_operator" not in scope` assertion
- `tests/test_clarify_rounds.py` (NEW) - CLAR2-01 proof: new-question-sends (WR-05 regression), same-round-suppressed (CLAR-04), crash-idempotent advance (Pitfall #3), AST source-order guard (D-9-02), outbound row round-stamping
- `tests/test_needs_operator.py` (NEW) - CLAR2-02 escalation-half proof: cap boundary, silent escalation (no outbound row), escalation write order (AST), scope exclusions (`IN_FLIGHT_STATUSES` + retrigger `stale_statuses`), badge rendering (TestClient)

## Decisions Made
- Placed the round cap check as the textually first statement/transaction in `_clarify` so it covers both call sites (`_run_stages`'s direct call at the non-field-regression clarification branch, and `_defer_field_regression_clarification`'s Step 5 call) with a single guard, and trivially satisfies D-9-01 (no transaction spans an LLM/provider call) since the cap check returns before either seam is reached.
- Gave `needs_operator` a brand-new `escalate` badge class rather than reusing `pending` or `bad` — both are already semantically owned by other statuses (`pending`=`awaiting_approval`, `bad`=`rejected`/`error`), and an escalation is neither a routine wait nor a terminal failure.
- Derived every round advance from the actually-sent row (via `get_outbound_for_round`'s return value on the early-return path, or the just-passed `current_round` on the two send paths) rather than a blind `current_round + 1` — this is what makes the crash-then-reentry test in `tests/test_clarify_rounds.py` pass: the counter self-heals from ground truth, not from a potentially stale in-process value.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree forked before Phase 11 Plan 01 was merged to master**
- **Found during:** Pre-Task-1 context verification
- **Issue:** The task prompt stated Plan 11-01's data-layer foundations were "ALREADY PRESENT" in this worktree. Verification (`git merge-base HEAD master`) showed this worktree branch was actually forked from `4318c3e` — the commit immediately BEFORE 11-01 was merged into master at `1a6de64`. `app/db/schema.sql` had none of the `clarification_round`/`round`/`consumed_round` columns, and `app/db/repo.py` had none of the 8 new Plan 11-01 primitives (`get_clarification_round`, `get_outbound_for_round`, `set_clarification_round`, etc.) that this plan's Task 1 directly depends on.
- **Fix:** Ran `git merge master` (a clean fast-forward from `4318c3e` to `1a6de64`, no conflicts) to bring the 11-01 data-layer foundations into this worktree branch before starting Task 1. Confirmed this was a fast-forward (not a 3-way merge) — no risk of clobbering concurrent work.
- **Files modified:** None directly (the merge brought in 11-01's own committed changes: `app/db/schema.sql`, `app/db/repo.py`, `app/models/status.py`, `tests/conftest.py`, `tests/test_status_drift.py`, `tests/test_models_contracts.py`, plus planning docs).
- **Verification:** `uv run pytest -q -m "not integration and not live_llm"` immediately after the merge returned 548 passed, 20 skipped — matching the plan's stated baseline exactly, confirming the merge introduced no regressions and the worktree now has exactly Plan 11-01's foundation to build on.
- **Committed in:** Not a separate commit — a fast-forward merge, so no new commit object was created; `git log` shows the 11-01 commits (`7674e9e`, `a48223f`, `ffd5c17`, `20d440e`, `43155cf`, `1a6de64`) directly in this branch's history preceding `e64a0e0` (this plan's Task 1 commit).

**2. [Rule 1 - Bug] Two pre-existing tests monkeypatched the retired guard function**
- **Found during:** Task 1 verification (full offline suite run)
- **Issue:** `tests/test_alias_write.py::test_clarify_idempotency_skips_if_clarification_already_sent` and `tests/test_atomic_persist.py::test_clarify_idempotency_path_writes_snapshot_then_status_in_one_transaction` both monkeypatched `repo.get_outbound_message_id` to simulate an existing clarification row. After Task 1 re-keyed `_clarify`'s guard to call `repo.get_outbound_for_round` instead, these monkeypatches no longer intercepted anything, and the real (unmocked) `get_outbound_for_round` fell through to the real `send_outbound` call, tripping each test's own "must not send" assertion.
- **Fix:** Updated both tests to monkeypatch `get_clarification_round` and `get_outbound_for_round` (matching the new guard shape) instead of the retired call. Extended `test_atomic_persist.py`'s ordering-pin assertion to include the new `set_clarification_round` call between `set_pre_clarify_extracted` and `set_status`.
- **Files modified:** `tests/test_alias_write.py`, `tests/test_atomic_persist.py`
- **Verification:** `uv run pytest -q -m "not integration and not live_llm"` — 548 passed, 20 skipped (identical to baseline) after the fix.
- **Committed in:** `e64a0e0` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (1 Rule-3 blocking dependency issue, 1 Rule-1 bug in pre-existing tests caused directly by this plan's own guard re-keying)
**Impact on plan:** The worktree-merge fix was necessary to have any foundation to build Task 1 on — without it, none of the 8 repo primitives this plan calls would have existed. The test-mock fix is a direct, expected consequence of re-keying the guard (the exact behavior CLAR2-01 required) — not scope creep.

## Issues Encountered
None beyond the deviations above.

## User Setup Required
None - no external service configuration required. This plan is pure application code (orchestrator logic, dashboard badge, tests) with no new environment variables or schema changes (schema changes landed in Plan 11-01).

## Next Phase Readiness
- WR-05 is closed: a genuinely new clarification round always sends; a true same-round duplicate is still suppressed (CLAR-04 preserved).
- The 3-round cap and silent `needs_operator` escalation are live, with the round machine's own idempotency and crash-safety proven by the AST/crash-injection test suite.
- `needs_operator` renders correctly on both the runs list and run-detail dashboard pages and is confirmed excluded from every scope list (sweep, retrigger, in-flight) that would otherwise mistreat it as a recoverable/in-flight state.
- Full offline suite: 562 passed (548 baseline + 14 new tests), 20 skipped, 28 deselected — no regressions.
- Plan 11-03 (per ROADMAP dependency ordering) can build on this round machine: the D-11-08 operator resolve/resume form for `needs_operator` runs, and/or the question-anchored reply extraction (D-11-10 through D-11-13) both now have a stable, tested round counter and escalation state to key off of.
- No blockers.

---
*Phase: 11-clarification-round-machine-alias-learning*
*Completed: 2026-07-06*

## Self-Check: PASSED

- `app/pipeline/orchestrator.py` — FOUND
- `app/email/gateway.py` — FOUND
- `app/main.py` — FOUND
- `app/static/style.css` — FOUND
- `tests/test_alias_write.py` — FOUND
- `tests/test_atomic_persist.py` — FOUND
- `tests/test_stuck_run_recovery.py` — FOUND
- `tests/test_clarify_rounds.py` — FOUND
- `tests/test_needs_operator.py` — FOUND
- Commit `e64a0e0` (Task 1) — FOUND in `git log --oneline --all`
- Commit `5e3a909` (Task 2) — FOUND in `git log --oneline --all`
- Commit `2e166a4` (Task 3) — FOUND in `git log --oneline --all`
- `uv run pytest -q tests/test_clarify_rounds.py tests/test_needs_operator.py` — 14 passed
- `uv run pytest -q -m "not integration and not live_llm"` — 562 passed, 20 skipped, 28 deselected (re-run immediately before this self-check)
- `grep -q "MAX_CLARIFICATION_ROUNDS = 3" app/pipeline/orchestrator.py` — PASS
- `grep -q "get_outbound_for_round" app/pipeline/orchestrator.py` — PASS
- All plan `<acceptance_criteria>` for Tasks 1-3 re-verified via grep/pytest — PASS
