---
phase: 09-atomic-data-integrity
plan: 02
subsystem: database
tags: [psycopg, postgres, transactions, orchestrator, fault-injection, pytest]

# Dependency graph
requires:
  - phase: 09-atomic-data-integrity
    plan: 01
    provides: "the mockable repo.get_connection() seam (FakeConnection double patched into fake_repo) that this plan's transaction wiring runs against offline"
provides:
  - "app/pipeline/orchestrator.py: _run_stages' process branch, _clarify's three AWAITING_REPLY exit paths, _defer_field_regression_clarification's set_clarified_fields write, and _deliver's already-sent guard + main finalize sequence each wrapped in one with repo.get_connection(): with conn.transaction(): block, status-advance-last (D-9-02)"
  - "_write_aliases_if_safe(run_id, run, roster, conn=None) — now conn-threadable so its writes can join a caller's transaction"
  - "_deliver's already-sent guard hardened to attempt the idempotent alias write before advancing SENT/RECONCILED on a retry-over-sent (Codex HIGH-2 closed)"
  - "tests/test_atomic_persist.py — SC1 fault-injection proof: 3 offline AST/call-order tests + 6 @pytest.mark.integration tests, all verified green against a real local Postgres instance"
  - "tests/conftest.py::patch_get_connection — reusable helper for tests that monkeypatch individual repo.* functions directly (not via fake_repo) and now need the new get_connection() seam mocked"
affects: [09-03, 09-04, 09-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Persist-then-branch transaction pattern: pure computation (e.g. _compute_line_items) runs BEFORE the with repo.get_connection(): with conn.transaction(): block opens, so a calc exception never opens a doomed transaction (D-9-04)"
    - "Sibling-statement-after-close pattern: any call containing an LLM/provider call (_clarify) is placed as a source-order sibling AFTER a transaction block closes, never nested inside it (D-9-01) — verified in tests via AST walk (in_with flag), not just visual inspection"
    - "Already-sent-guard hardening: when a provider call's own internal write (gateway.send_outbound's send_state='sent' flip) has already durably committed before the caller's finalize transaction can exist, the caller's retry-path guard performs the OTHER caller-side work (alias write) idempotently instead of skipping it silently"
    - "conn= threading for defensive-isolation try/except: the alias-write try/except stays nested strictly INSIDE the new transaction block (not wrapping it) so a caught, swallowed exception there never rolls back the outer transaction's other writes"

key-files:
  created:
    - tests/test_atomic_persist.py
  modified:
    - app/pipeline/orchestrator.py
    - tests/conftest.py
    - tests/test_alias_write.py
    - tests/test_cr_regressions.py
    - tests/test_demo_landing.py

key-decisions:
  - "_run_stages' process-branch transaction covers persist_extracted/persist_decision/persist_reconciliation always, plus replace_line_items/set_status(COMPUTED)/set_status(AWAITING_APPROVAL) only on the process branch — computed via an if inside the same block rather than two separate transactions, since both share the identical persist-first three statements"
  - "_clarify's three AWAITING_REPLY exit paths (idempotency early-return, record_only, live-gateway) each get their OWN with-block rather than a shared helper — the plan's acceptance criteria pin each path's shape independently, and the three call sites are structurally distinct enough (different preceding side effects) that a shared helper would need to take a callback anyway"
  - "_deliver's hardened already-sent guard loads its own roster (existing_roster) rather than reusing a Step-4 roster load, because this early-return path returns BEFORE Step 4 runs today — confirmed by re-reading lines 1179-1227 per the plan's explicit instruction"
  - "9 pre-existing offline tests (5 in test_alias_write.py, 3 in test_demo_landing.py, 1 in test_cr_regressions.py) that monkeypatch individual repo.* functions directly (not via the fake_repo fixture) needed a new tests/conftest.py::patch_get_connection helper wired in, since they now exercise code paths that open repo.get_connection() blocks — this is Rule 3 (blocking issue) scope, not a plan deviation, since the transaction wiring itself is exactly what the plan specifies"
  - "tests/test_atomic_persist.py's live-DB tests deliberately do NOT use the shared mock_llm fixture (it monkeypatches DATABASE_URL to a stub, which would break a live-DB test) or mock_resend_send fixture — a local LiveMockOpenAI class + direct resend.Emails.send monkeypatch keep the real DATABASE_URL wired through"
  - "test_defer_field_regression_write_survives_later_clarify_failure asserts the run lands in ERROR (not that it re-raises) — resume_pipeline's own D-A1-03 error-wrap boundary swallows every exception and routes to record_run_error; this is the correct, diagnosable outcome the plan's threat model requires (a crash never looks like a successful send that never happened)"

requirements-completed: [DATA-01]

duration: ~90min
completed: 2026-07-04
---

# Phase 09 Plan 02: Atomic Multi-Write Transactions in the Orchestrator Summary

**Wired D-9-04 through D-9-08's transaction boundaries into `_run_stages`, `_clarify`, `_defer_field_regression_clarification`, and `_deliver` — a crash injected mid-sequence now leaves the run wholly un-advanced (never half-written), proven by 6 fault-injection tests run against a real local Postgres instance, plus hardened `_deliver`'s already-sent guard so a retry-over-sent no longer silently skips alias learning (Codex HIGH-2 closed).**

## Performance

- **Duration:** ~90 min
- **Started:** 2026-07-04T02:xx:xxZ
- **Completed:** 2026-07-04T04:xx:xxZ
- **Tasks:** 2/2 completed
- **Files modified:** 6 (1 created, 5 modified)

## Accomplishments

- `_run_stages`' process branch now commits `persist_extracted`/`persist_decision`/`persist_reconciliation`/`replace_line_items`/`set_status(COMPUTED)`/`set_status(AWAITING_APPROVAL)` as ONE transaction, status-advance-last (D-9-02/D-9-04); the `request_clarification` branch's three persists commit in the same block, and `_clarify(...)`'s call site is verifiably a sibling statement outside and after it (D-9-01) — pinned by an AST walk test, not just visual inspection.
- `_clarify`'s three `AWAITING_REPLY` exit paths (idempotency early-return, `record_only`, live-gateway) each commit `set_pre_clarify_extracted` + `set_status(AWAITING_REPLY)` as one transaction.
- `_defer_field_regression_clarification`'s `set_clarified_fields` write (the resume-path field-regression re-clarification helper — the exact MONEY-03 shape that failed three review rounds in Phase 7.5) now commits in its own transaction that closes strictly BEFORE the `_clarify(...)` call it makes.
- `_deliver`'s already-sent guard is hardened per Codex HIGH-2: since `gateway.send_outbound` already durably flips `send_state='sent'` before returning (verified against live `app/email/gateway.py` source), a retry-over-sent now loads the roster and attempts the idempotent alias write (isolated try/except) BEFORE advancing SENT/RECONCILED — closing the silent-alias-skip gap.
- `_deliver`'s main finalize sequence (alias write + SENT + RECONCILED) commits as one transaction nested INSIDE the existing WR-04 `try/except` so `exc.payroll_roster` attachment on a forced failure is preserved; the alias try/except stays nested STRICTLY INSIDE the transaction (Pitfall 2) so an alias-write failure never rolls back a genuine delivery.
- `_write_aliases_if_safe` gained `conn=None` so its internal `load_run`/`update_known_alias`/`load_roster_for_business` calls thread the caller's connection.
- New `tests/test_atomic_persist.py`: 3 offline tests (FakeConnection call-order + AST/indentation sibling-statement pins) + 6 `@pytest.mark.integration` tests, ALL VERIFIED GREEN against a real local Postgres instance (not just skip-guard-checked) — covering the process-branch crash (SC1), the already-sent-guard alias regression (Pitfall 2), the WR-04 preservation check, the retry-over-sent Codex HIGH-2 regression, and the defer-field-regression survive-later-failure case.
- Full offline suite: 536 passed (533 baseline + 3 new offline tests), 21 skipped, 0 regressions.

## Task Commits

Each task was committed atomically:

1. **Task 1: Wrap _run_stages' process branch in one transaction** - `ce4bbad` (feat)
2. **Task 2: Wrap _clarify/_defer_field_regression_clarification/_deliver finalize writes; harden already-sent guard; add conn= to _write_aliases_if_safe** - `275f4ed` (feat)

**Plan metadata:** (this commit)

## Files Created/Modified

- `app/pipeline/orchestrator.py` — `_run_stages` process-branch transaction; `_clarify`'s three exit-path transactions; `_defer_field_regression_clarification`'s Step-3 transaction; `_deliver`'s hardened already-sent guard + main finalize transaction; `_write_aliases_if_safe` gains `conn=`
- `tests/test_atomic_persist.py` (new) — SC1 fault-injection proof (offline + live-DB integration tests)
- `tests/conftest.py` — added `patch_get_connection(monkeypatch, repo_mod)` helper
- `tests/test_alias_write.py` — 5 tests wired with `patch_get_connection` (now exercise `_clarify`'s new transaction blocks)
- `tests/test_demo_landing.py` — 3 tests wired with `patch_get_connection`
- `tests/test_cr_regressions.py` — 1 test wired with `patch_get_connection`

## Decisions Made

- `_compute_line_items` (pure calc) is called unconditionally before the transaction opens and only USED inside the block on the process branch — kept the persist transaction's body free of anything that can raise for a business/integrity reason (D-9-04's "run BEFORE the transaction opens" instruction).
- The hardened already-sent guard loads its own roster rather than trying to reuse a later Step-4 load, since it returns before Step 4 runs today (verified against live source per the plan's explicit re-read instruction).
- Chose to fix the 9 offline tests broken by the new `repo.get_connection()` calls via a shared `patch_get_connection` helper rather than inlining `FakeConnection` context managers 9 times — DRY, and matches the existing `_fake_get_connection` double already established in 09-01.
- The live-DB integration tests use a local `LiveMockOpenAI` class (not the shared `mock_llm` fixture) because `mock_llm` monkeypatches `DATABASE_URL` to a stub value, which is incompatible with a test that needs the REAL live DB connection.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 9 pre-existing offline tests needed `repo.get_connection()` mocked**

- **Found during:** Task 2, running the full offline suite after wiring `_clarify`/`_deliver`'s new transaction blocks
- **Issue:** `tests/test_alias_write.py` (5 tests), `tests/test_demo_landing.py` (3 tests), and `tests/test_cr_regressions.py` (1 test) monkeypatch individual `app.db.repo.*` functions directly rather than using the `fake_repo` fixture. Once `_clarify`/`_deliver` started calling `repo.get_connection()` (this plan's core change), these tests attempted to open a REAL pooled Supabase connection and hit `psycopg_pool.PoolTimeout` after 5s.
- **Fix:** Added `tests/conftest.py::patch_get_connection(monkeypatch, repo_mod)` — a one-line reusable helper that monkeypatches `repo_mod.get_connection` to the existing `_fake_get_connection` `FakeConnection` double (established in 09-01). Wired it into all 9 affected tests alongside their existing `repo_mod.*` monkeypatches.
- **Files modified:** `tests/conftest.py`, `tests/test_alias_write.py`, `tests/test_demo_landing.py`, `tests/test_cr_regressions.py`
- **Verification:** Full offline suite (533 baseline + 3 new) green, 0 regressions.
- **Committed in:** `275f4ed` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3, blocking — necessary side effect of the plan's own transaction wiring, not scope creep)
**Impact on plan:** The fix is a direct, unavoidable consequence of implementing the plan as written — every test that calls `_clarify`/`_deliver` with individually-monkeypatched `repo.*` functions needed the same seam mocked that `fake_repo`-based tests already had via 09-01. No scope creep; no business logic touched.

## Issues Encountered

- The first draft of `tests/test_atomic_persist.py`'s AST-based "exactly one `with conn.transaction():` block" check used a naive substring match over source lines, which double-counted a CODE COMMENT that happened to contain the literal phrase `with conn.transaction():` (the D-9-01 sibling-statement note). Fixed by switching to a proper `ast.walk` over `ast.With` nodes checking `context_expr.func.attr == "transaction"`, which only counts real `with` statements.
- `test_defer_field_regression_write_survives_later_clarify_failure`'s first draft asserted `resume_pipeline` re-raises the forced `_clarify` failure — it does not. `resume_pipeline` owns its own D-A1-03 error-wrap `try/except` that swallows every exception and routes the run to `ERROR` via `record_run_error`. Fixed the test to call `resume_pipeline` without `pytest.raises` and assert `post_run["status"] == RunStatus.ERROR.value` instead — this is the correct, diagnosable outcome (never a state that implies a clarification was sent when it wasn't).
- Verified all 6 new `@pytest.mark.integration` tests against a REAL local Postgres instance (Postgres.app, `bootstrap(reset=True)` + `seed()` against a throwaway `payroll_agent_test09` database) rather than relying solely on the skip-guard's clean-skip behavior — all 6 passed on the first corrected run. The scratch database was dropped after verification; no artifacts left behind.
- Two PRE-EXISTING failures surfaced when running the FULL integration suite (`-m integration`, not just this plan's new file) against the same local Postgres: `tests/test_ingest.py::test_duplicate_delivery_pipeline_runs_once` (missing `ALLOW_UNSIGNED_FIXTURES` env var in the ad-hoc local test env — fixed by adding it) and `tests/test_gateway.py::test_inbound_reply_routes_to_correct_run_integration` (an `xfail(strict)` test now `XPASS` — reproduced identically on `git stash` of this plan's changes, confirming it is unrelated pre-existing test-state drift from an earlier phase, not something Task 1/2 introduced). Neither is in this plan's scope; not fixed here.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 09-03/09-04/09-05 (webhook dedup CAS, stuck-run recovery route wiring, and whatever remaining Phase 9 plans) can build on the same `repo.get_connection()` + `conn.transaction()` seam without re-deriving the mockable-offline pattern — `patch_get_connection` is now a shared, reusable test helper for any future test that monkeypatches individual `repo.*` functions.
- The two pre-existing unrelated integration-suite failures noted above (`test_duplicate_delivery_pipeline_runs_once` env-var gap, `test_inbound_reply_routes_to_correct_run_integration` XPASS) are flagged for whoever next runs the full `-m integration` suite locally — neither blocks this plan or Phase 9 wave 2.
- No blockers identified for the remaining Phase 9 plans.

---
*Phase: 09-atomic-data-integrity*
*Completed: 2026-07-04*

## Self-Check: PASSED

- FOUND: tests/test_atomic_persist.py
- FOUND: .planning/phases/09-atomic-data-integrity/09-02-SUMMARY.md
- FOUND: ce4bbad (Task 1 commit)
- FOUND: 275f4ed (Task 2 commit)
- FOUND: 54c5622 (SUMMARY.md commit)
