---
phase: 09-atomic-data-integrity
verified: 2026-07-04T18:00:00Z
status: passed
score: 7/7 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 5/7
  gaps_closed:
    - "DATA-01: Each multi-write pipeline operation is atomic (resume_pipeline's Round-2 non-deferred clarified_fields write now commits in its own closed transaction strictly BEFORE _run_stages runs — orchestrator.py:604-606)"
    - "_deliver's alias-write isolation (a genuine DB-level error inside _write_aliases_if_safe no longer poisons the finalize transaction — nested conn.transaction() SAVEPOINT at orchestrator.py:1408-1409)"
  gaps_remaining: []
  regressions: []
deferred: []
human_verification: []
---

# Phase 9: Atomic Data Integrity Verification Report

**Phase Goal:** The data layer becomes correct under concurrency and crashes — the senior-engineer signal of the milestone. Every multi-write pipeline operation commits atomically, duplicate webhook deliveries can never create a second run even when raced, and a background task that dies mid-flight leaves a *recoverable* run rather than a permanently-stranded one.
**Verified:** 2026-07-04
**Status:** passed
**Re-verification:** Yes — after gap closure (plan 09-06, commits `e192c37` + `da1e962`)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `sweep_stranded_runs` marks only `{received, extracting, computed}` runs stale past threshold as ERROR, never parked statuses | VERIFIED (regression check) | `app/db/repo.py::sweep_stranded_runs` unchanged by 09-06 (confirmed: 09-06's `files_modified` is only `orchestrator.py` + `tests/test_atomic_persist.py`; `git diff --stat` between pre/post-09-06 commits shows no touch to `repo.py`). Code re-read confirms scope unchanged. |
| 2 | A swept run carries a distinguishing `error_reason`/`error_detail` sentinel, readable via `repo.load_run` | VERIFIED (regression check) | Unchanged; confirmed by code read. |
| 3 | `find_run_by_message_id` resolves the existing run for the webhook's dedup-loser path via a JOIN on `email_messages` | VERIFIED (regression check) | Unchanged; confirmed by code read. |
| 4 | **DATA-01: Each multi-write pipeline operation is atomic** (`_run_stages`, `_deliver`, AND every resume-path write sequence — including the Round-2 non-deferred fall-through) | **VERIFIED** | Direct source read of `app/pipeline/orchestrator.py:589-618` confirms the Round-2 non-deferred `repo.set_clarified_fields(run_id, clarified, conn=conn)` call now executes inside its own `with repo.get_connection() as conn: with conn.transaction():` block (lines 604-606), which closes and commits strictly BEFORE `_run_stages(...)` is called (line 608). No bare, unwrapped `set_clarified_fields` call remains anywhere in `resume_pipeline` after `_run_stages` returns (confirmed via `ast`-based regression test `test_round2_clarified_fields_persist_call_order_before_run_stages`, independently re-run against real source). |
| 5 | `_deliver`'s alias-write isolation: a forced `_write_aliases_if_safe` failure (including a genuine DB-level error, not only a Python exception) still reaches RECONCILED | **VERIFIED** | Direct source read of `app/pipeline/orchestrator.py:1407-1415` confirms `_write_aliases_if_safe(run_id, run, roster, conn=conn)` now executes inside a NESTED `with conn.transaction():` block (a genuine psycopg3 SAVEPOINT when entered inside an already-open outer transaction), itself inside the existing `try/except`. `update_known_alias`'s `_nulltx()` no-op (app/db/repo.py:1416-1419) is confirmed unchanged (the fix correctly lives at the CALLER, not inside the no-op helper). Independently re-executed the live-DB fault-injection test against a genuinely fresh local Postgres instance I stood up myself (see Behavioral Spot-Checks) — a real `UPDATE ... nonexistent_column` (psycopg.errors.UndefinedColumn) inside the alias path no longer poisons the outer transaction; the run reaches `reconciled`. |
| 6 | **DATA-02: Two concurrent duplicate webhook deliveries result in exactly one run**; a header-bearing reply is classified before `create_run` is reachable | VERIFIED (regression check) | `app/main.py::inbound` untouched by 09-06 (confirmed: 09-06's `files_modified` list, and direct `git show --stat` on both gap-closure commits, touch only `orchestrator.py` + `tests/test_atomic_persist.py`). Prior verification's evidence stands unchanged. |
| 7 | **DATA-03: A run whose background task died mid-flight becomes a recoverable ERROR** via sweep + the actual retrigger route | VERIFIED (regression check) | `app/main.py::runs_list` / `retrigger` untouched by 09-06. Prior verification's evidence stands unchanged. |

**Score:** 7/7 truths verified. Both DATA-01 gaps from the prior verification are closed and independently re-proven against a real, freshly-provisioned local Postgres instance (not `FakeConnection`, not trusted from SUMMARY.md narrative).

### Independent Re-Verification Method (this pass)

Unlike a review of prose, this verification stood up its own throwaway local Postgres database (`payroll_agent_verify09`, then `payroll_agent_verify09b`) via `uv run python -m app.db.bootstrap`, independent of any state the executor's environment may have had, and:

1. Ran the 4 targeted gap-closure tests (`round2` + `alias_failure` -k filters) live — all 4 passed.
2. Ran the full `tests/test_atomic_persist.py` file live — all 12 passed.
3. **Falsification check (gap 2):** Temporarily reverted the SAVEPOINT fix (removed the nested `with conn.transaction():` around `_write_aliases_if_safe`) and re-ran `test_deliver_finalize_genuine_db_alias_failure_still_reaches_reconciled` live — it genuinely FAILED with `psycopg.errors.InFailedSqlTransaction`, exactly the failure mode the gap described. Restored the fix; re-ran — passed. This proves the test is not tautological and the fix is load-bearing.
4. **Falsification check (gap 1):** Temporarily reverted the reordering fix (moved `set_clarified_fields` back to a bare call after `_run_stages`) and re-ran both `round2` tests live — both genuinely FAILED (the AST regression test correctly detected the bare, un-nested call; assertion message matched the predicted failure). Restored the fix; re-ran — passed. This proves the AST/source-order regression test actually pins the fix.
5. Ran the full offline suite (`-m "not integration"`) after restoring both fixes — 546 passed, 21 skipped, 27 deselected, 0 failed. `git status --porcelain` confirmed no residual diff from the temporary reverts.
6. Additionally ran the FULL live-DB suite (`uv run pytest -q`, no `-k`/`-m` filter) against a fresh live DB — found 1 unrelated pre-existing failure (see Anti-Patterns / WR-07 below); not part of DATA-01/02/03's scope and not introduced by 09-06.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/pipeline/orchestrator.py` (Round-2 non-deferred `set_clarified_fields`) | Persisted in its own closed transaction strictly BEFORE `_run_stages` | VERIFIED | Lines 604-606 (`with repo.get_connection() as conn: with conn.transaction(): repo.set_clarified_fields(run_id, clarified, conn=conn)`), followed by `stage = _run_stages(...)` at line 608. Identical shape to the already-correct sibling pattern in `_defer_field_regression_clarification` (lines ~763-765). |
| `app/pipeline/orchestrator.py` (`_deliver`'s alias write) | Wrapped in a nested `conn.transaction()` (SAVEPOINT) | VERIFIED | Lines 1407-1415: `try: with conn.transaction(): _write_aliases_if_safe(run_id, run, roster, conn=conn) except Exception as alias_exc: ...`. `repo.set_status(SENT)`/`repo.set_status(RECONCILED)` remain outside both the nested block and unaffected by its rollback, at lines 1420-1421 — confirmed positionally unchanged from the prior (pre-gap-closure) source. |
| `tests/test_atomic_persist.py` | 2 new/modified tests proving both fixes against a real Postgres connection | VERIFIED (existence + execution) | `test_round2_clarified_fields_persist_before_run_stages` (live-DB crash-injection), `test_round2_clarified_fields_persist_call_order_before_run_stages` (offline AST source-order guard), `test_deliver_finalize_genuine_db_alias_failure_still_reaches_reconciled` (live-DB genuine `psycopg.errors.UndefinedColumn` fault injection) — all independently executed by this verifier against a self-provisioned local Postgres, not merely trusted from 09-06-SUMMARY.md's execution log. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `resume_pipeline` Round-2 (non-deferred) | `payroll_runs.clarified_fields` | Own closed `with conn.transaction():` block, called BEFORE `_run_stages` | **WIRED** | Confirmed by direct code read (lines 604-608) and by live execution + falsification test above. This closes the previously `NOT_WIRED` link from the prior verification. |
| `_deliver` finalize block | `_write_aliases_if_safe` | Nested `conn.transaction()` (SAVEPOINT), inside the existing try/except | **WIRED** | Confirmed by direct code read (lines 1407-1415) and by live execution + falsification test proving genuine DB-level isolation, not just Python-exception isolation. This closes the previously `PARTIAL` link from the prior verification. |
| `_run_stages` | `payroll_runs` status/data columns | Single `conn.transaction()` block, status-advance-last | VERIFIED (regression, unchanged) | Untouched by 09-06. |
| `inbound()` | `payroll_runs`/`email_messages` | One transaction, reply-classification-before-`create_run` | VERIFIED (regression, unchanged) | Untouched by 09-06. |
| `runs_list()` | `repo.sweep_stranded_runs` | One-line call before `load_all_runs()` | VERIFIED (regression, unchanged) | Untouched by 09-06. |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DATA-01 | 09-02, 09-05, 09-06 | Each multi-write pipeline operation is atomic | **SATISFIED** | Both confirmed falsifying gaps (WR-01, WR-02) closed by plan 09-06; both fixes independently re-verified against live source AND against a self-provisioned real Postgres instance with falsification testing (reverting each fix and confirming its proving test genuinely fails). No remaining confirmed unwrapped multi-write call site. |
| DATA-02 | 09-01, 09-03 | Duplicate webhook deliveries never create a second run | SATISFIED (regression, unchanged) | Untouched by 09-06; prior verification's evidence stands. |
| DATA-03 | 09-01, 09-03, 09-04 | Stuck run recoverable via sweep or retrigger | SATISFIED (regression, unchanged) | Untouched by 09-06; prior verification's evidence stands. |

**Orphaned requirements check:** REQUIREMENTS.md maps exactly DATA-01/DATA-02/DATA-03 to Phase 9; all three appear in plan frontmatter (`09-01`: DATA-02/03; `09-02`: DATA-01; `09-03`: DATA-02/03; `09-04`: DATA-03; `09-05`: DATA-01; `09-06`: DATA-01, gap-closure). No orphaned requirements.

### Anti-Patterns Found

The post-gap-closure re-review (`09-REVIEW.md`, 0 Critical / 5 Warning / 9 Info) surfaced 3 NEW findings during the re-review pass (WR-05, WR-06, WR-07) in addition to the carried-forward WR-03/WR-04/IN-01..06. This verification independently re-confirmed the two most load-bearing new findings against live source/execution, and assessed each against DATA-01/02/03's literal wording (the phase's must-have contract) rather than accepting the review's own disposition at face value:

| File | Line | Pattern | Severity | Impact / Disposition |
|------|------|---------|----------|--------|
| `app/pipeline/orchestrator.py` | 589-618 (new persist), `app/main.py` 690-798 (retrigger) | WR-06: the WR-02 fix's chosen design ("independently committed and diagnosable") means `clarified_fields` can durably show a terminal label (`client_supplied`/`confirmed_dropped`) for a round whose extracted-data/line-items were rolled back by a later crash; if the operator then retriggers (which restarts from the ORIGINAL email — an already-accepted, pre-existing 09-03 "reply-context-loss on retrigger" limitation, confirmed by code comment at `app/main.py:705-717` predating 09-06), the provenance badge can mislabel a paid value at the approval gate. | ⚠️ WARNING (not a DATA-01 blocker) | Independently confirmed via code read: this is a residual, foreseeable consequence of an ALREADY-ACCEPTED, pre-existing limitation (documented since plan 09-03, before 09-06 existed) — not a new half-written-run/atomicity violation. The write itself is fully, genuinely committed (no partial state) at the moment it commits; the staleness only manifests after a separate, later, human-triggered action (retrigger) that already carries a documented context-loss caveat. Correctly classified as WARNING, same tier as WR-03/WR-04 from the prior verification — real, adjacent, worth a follow-up plan, but does not falsify DATA-01's literal "atomic, never half-written" wording. |
| `app/pipeline/orchestrator.py` | 980-995 (`_clarify` idempotency guard) | WR-05: `get_outbound_message_id`'s purpose-scoped guard is round-blind — a genuinely NEW clarification (same `purpose`, later round) can be silently skipped, parking the run at `awaiting_reply` with no sweep/retrigger recovery route. | ⚠️ WARNING (not a DATA-01/02/03 blocker) | This is a send-idempotency/business-logic completeness gap in `_clarify`, not a multi-write atomicity, dedup, or stuck-run-recovery gap. Independently confirmed real by code read but out of the literal DATA-01/02/03 must-have scope — same disposition class as WR-03/WR-04. |
| `tests/test_gateway.py` | 1129 | WR-07: `test_inbound_reply_routes_to_correct_run_integration` carries a stale `@pytest.mark.xfail(strict=True, reason="implemented in 06-04")` on behavior that IS implemented and passes — in any live-DB run it XPASSes, and `strict=True` converts that into a hard suite FAILURE. | ⚠️ WARNING (test-hygiene, not DATA-01/02/03) | **Independently reproduced live** by this verifier: stood up a fresh local Postgres, ran the full live-gated suite (`uv run pytest -q` with `DATABASE_URL`+`ALLOW_DB_RESET=1`+`ALLOW_UNSIGNED_FIXTURES=true`) — confirmed `1 failed, 591 passed, 2 skipped` with the sole failure being this XPASS. This means 09-06-SUMMARY.md's/PLAN's literal success criterion ("`uv run pytest -q` full suite is green when run live") is NOT currently true, though the failure is pre-existing (predates 09-06, unrelated to `orchestrator.py`/`test_atomic_persist.py`) and does not touch any DATA-01/02/03 code path. Flagged for a quick follow-up (remove the stale `xfail` decorator) — does not block this phase's goal. |
| (carried) `app/main.py` | 373-383, 385-454 | WR-03, WR-04 (reply rows never linked to run_id; duplicate-redelivered reply never re-triggers resume) | ⚠️ WARNING | Unchanged from prior verification's disposition — real, adjacent, not a literal DATA-02/03 violation. |
| (carried) various | — | IN-01 through IN-09 | ℹ️ INFO | Unchanged/incremental; none touch DATA-01/02/03's literal wording. |

No unreferenced `TBD`/`FIXME`/`XXX` debt markers found in the phase's modified files (09-06's diff: `app/pipeline/orchestrator.py`, `tests/test_atomic_persist.py`).

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Offline suite green (regression check) | `uv run pytest -q -m "not integration"` | 546 passed, 21 skipped, 27 deselected, 0 failed | PASS |
| Gap-closure tests pass against a genuinely fresh, self-provisioned local Postgres | `DATABASE_URL=postgresql://pnhek@localhost:5432/payroll_agent_verify09 ALLOW_DB_RESET=1 ALLOW_UNSIGNED_FIXTURES=true uv run pytest -q tests/test_atomic_persist.py -k "round2 or alias_failure"` | 4 passed, 8 deselected | PASS |
| Full `test_atomic_persist.py` passes live | same env, `uv run pytest -q tests/test_atomic_persist.py` | 12 passed | PASS |
| Gap 2 fix is load-bearing (falsification) | temporarily removed the nested `conn.transaction()` SAVEPOINT, re-ran `-k alias_failure` live | `test_deliver_finalize_genuine_db_alias_failure_still_reaches_reconciled` FAILED with `psycopg.errors.InFailedSqlTransaction`; restored fix, re-ran, PASSED | PASS (confirms fix is real, not tautological) |
| Gap 1 fix is load-bearing (falsification) | temporarily moved `set_clarified_fields` back to a bare post-`_run_stages` call, re-ran `-k round2` live | Both `round2` tests FAILED (AST guard correctly detected the un-nested, post-`_run_stages` call); restored fix, re-ran, PASSED | PASS (confirms fix is real, not tautological) |
| Full live-gated suite (unfiltered) | `uv run pytest -q` against a fresh local Postgres with `DATABASE_URL`+`ALLOW_DB_RESET=1`+`ALLOW_UNSIGNED_FIXTURES=true` | 591 passed, 2 skipped, 1 failed (`test_inbound_reply_routes_to_correct_run_integration`, stale strict-xfail, WR-07 — pre-existing, unrelated to 09-06) | INFO (not a DATA-01/02/03 gate; see Anti-Patterns) |

### Probe Execution

No dedicated `scripts/*/tests/probe-*.sh` probes declared for this phase; none found via `find scripts -path '*/tests/probe-*.sh'`. Step 7c: SKIPPED (no probes declared or discovered for this phase).

### Human Verification Required

None identified. Every must-have and gap in this report was resolvable via direct source inspection, git history, and running both the offline suite and a genuinely self-provisioned live-Postgres suite (including falsification tests reverting each fix) — no visual, real-time, or external-service-dependent behavior is in scope for this phase.

### Gaps Summary

Both DATA-01 gaps identified in the initial verification are closed, and this closure was independently re-proven — not merely re-read from SUMMARY.md/09-REVIEW.md prose:

1. **Gap 1 (WR-02, resolved):** `resume_pipeline`'s Round-2 non-deferred fall-through now persists `clarified_fields`'s terminal outcomes in its own closed transaction (`orchestrator.py:604-606`) strictly BEFORE `_run_stages` runs (`orchestrator.py:608`). Verified by direct source read, by live execution of the new live-DB and AST regression tests against a self-provisioned Postgres instance, and by a falsification test (temporarily reverting the fix and confirming both new tests then genuinely fail with the predicted failure mode).

2. **Gap 2 (WR-01, resolved):** `_deliver`'s alias write now executes inside a nested `conn.transaction()` (a genuine psycopg3 SAVEPOINT) at `orchestrator.py:1407-1409`. Verified the same way: direct source read, live execution against a self-provisioned Postgres of the new genuine-DB-level fault-injection test, and a falsification test proving the fix is load-bearing (without it, a real `psycopg.errors.UndefinedColumn` in the alias path reproduces the exact `InFailedSqlTransaction` cascade the gap described).

DATA-01, DATA-02, and DATA-03 are now all satisfied as literally worded. The phase goal — atomic multi-write operations, race-safe webhook dedup, and recoverable stranded runs — is achieved.

**Three new findings surfaced by the post-gap-closure re-review (WR-05, WR-06, WR-07)** were independently assessed against the phase's literal must-haves rather than accepted at face value:
- WR-06 is a foreseeable, downstream consequence of an *already-accepted, pre-existing* limitation (09-03's documented reply-context-loss on retrigger) — real and worth a follow-up plan, but not a new half-written-run/atomicity violation.
- WR-05 is a `_clarify` send-idempotency completeness gap, adjacent to but distinct from DATA-01/02/03's literal scope.
- WR-07 is a genuine, independently-reproduced test-hygiene bug (a stale `strict=True` xfail causes the full live-DB suite to hard-fail) — pre-existing (not introduced by 09-06), unrelated to any DATA-01/02/03 code path, but worth noting since it means the plan's own "`uv run pytest -q` full suite green live" success criterion is not currently literally true. Recommended as a fast follow-up (remove the stale decorator on `tests/test_gateway.py:1129`) but does not block this phase's goal achievement.

None of these three new findings block phase closure — they are flagged as WARNING/INFO for a future quick-task or the next phase's planning, consistent with how WR-03/WR-04 were treated in the initial verification.

---

_Verified: 2026-07-04_
_Verifier: Claude (gsd-verifier)_
