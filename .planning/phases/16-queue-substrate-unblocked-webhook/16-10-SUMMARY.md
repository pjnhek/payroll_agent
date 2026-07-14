---
phase: 16-queue-substrate-unblocked-webhook
plan: 10
subsystem: pipeline
tags: [postgres, email, idempotency, concurrency, pytest, psycopg]

# Dependency graph
requires:
  - phase: 16-queue-substrate-unblocked-webhook (plan 03)
    provides: "email_messages send_state/round/epoch columns + uq_email_run_purpose_round_epoch"
  - phase: 16-queue-substrate-unblocked-webhook (plan 04)
    provides: "rewind_for_reclaim — the automatic reclaim path that never bumps reply_epoch, which is what keeps a reclaimed run inside this guard's scope"
provides:
  - "app/db/repo/emails.py::get_unconfirmed_outbound — epoch-scoped read of an UNCONFIRMED ('reserved'/'failed') outbound row for a run's current send slot"
  - "app/pipeline/send_guard.py — UnconfirmedSendError + assert_no_unconfirmed_send, the shared fail-closed guard both client-facing send sites call"
  - "the guard call wired into clarify() (immediately after the existing round-idempotency guard) and deliver() (immediately after the existing already-sent guard)"
  - "tests/test_send_idempotency.py — 9 tests: 1 hermetic SQL-shape proof, 6 hermetic pipeline-flow proofs (including the non-vacuity twin), 2 live-DB epoch/operator-recovery proofs"
affects: [16-07, 16-08, 16-09, 20]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A guard module imported as `from app.pipeline import send_guard` (a module object, not bare names) so both clarification.py and delivery.py resolve `send_guard.assert_no_unconfirmed_send` dynamically at call time — the same BOUND-01 seam convention `app.email.gateway` already uses."
    - "Two complementary, deliberately asymmetric outbound-row guards live side by side: get_outbound_message_id/get_outbound_for_round answer 'was this PROVEN sent?' (send_state='sent' only); get_unconfirmed_outbound answers 'might this have been sent?' (send_state IN ('reserved','failed')). Neither is ever widened to cover the other's case."
    - "A hermetic FakeConnection SQL-shape test (in the style of tests/test_repo_jobs_sql.py) is what actually catches a mutation to the real SQL predicate — the fake_repo/InMemoryRepo pipeline-flow tests exercise a hand-written Python mirror and structurally cannot see a change to the real query text. Both layers are needed; neither substitutes for the other."

key-files:
  created:
    - app/pipeline/send_guard.py
    - tests/test_send_idempotency.py
  modified:
    - app/db/repo/emails.py
    - app/db/repo/__init__.py
    - app/pipeline/clarification.py
    - app/pipeline/delivery.py
    - tests/conftest.py
    - tests/test_delivery.py

key-decisions:
  - "get_unconfirmed_outbound is a NEW function, never a widening of get_outbound_message_id/get_outbound_for_round — the two guard families fail in opposite directions (skip-on-proven-sent vs. block-on-possibly-sent) and merging them would let a crashed send look identical to a completed one, silently dropping a required email."
  - "The guard is epoch-scoped on purpose: an automatic reclaim (rewind_for_reclaim, plan 04) never bumps reply_epoch, so a rewound run stays inside this guard's reach; only a human-triggered clear_reply_context opens a new epoch and thereby a new send slot. This is what makes the guard fail-closed for the machine and recoverable for a human."
  - "The escalation reuses the existing ERROR status and orchestrator/approve() catch-all error boundaries rather than adding new vocabulary — ERROR already sits outside rewind_for_reclaim's three-status scope, so an escalated run cannot be auto-rewound back into a re-send."
  - "Added a hermetic FakeConnection SQL-shape test not explicitly named in the plan's per-test enumeration, because the plan's own falsifying-mutation table (mutation (a): revert the WHERE to send_state='sent') implicitly requires a hermetic test that can see the real SQL text — the fake_repo-driven pipeline tests cannot, by the codebase's own established (and documented) fake/real split."

requirements-completed: [QUEUE-02, QUEUE-03]

coverage:
  - id: D1
    description: "app/db/repo/emails.py::get_unconfirmed_outbound reads an epoch-scoped, purpose-scoped, round-scoped 'reserved'/'failed' outbound row and is byte-identical-safe alongside its two siblings (get_outbound_message_id, get_outbound_for_round)"
    requirement: "QUEUE-02"
    verification:
      - kind: unit
        ref: "tests/test_send_idempotency.py::test_get_unconfirmed_outbound_sql_shape"
        status: pass
      - kind: unit
        ref: "tests/test_fake_repo_pairing.py (4 tests) — get_unconfirmed_outbound registered in the fake_repo tuple"
        status: pass
    human_judgment: false
  - id: D2
    description: "Both client-facing send sites (clarify(), deliver()) call the guard immediately after their existing proven-sent guard and strictly before any LLM/provider call; a reserved/failed row blocks the send and escalates the run to ERROR"
    requirement: "QUEUE-02, QUEUE-03"
    verification:
      - kind: unit
        ref: "tests/test_send_idempotency.py::test_a_reserved_row_blocks_the_rerun_and_escalates, ::test_a_failed_row_blocks_the_rerun_too, ::test_a_reserved_confirmation_blocks_deliver"
        status: pass
      - kind: unit
        ref: "tests/test_send_idempotency.py::test_no_reserved_row_means_the_send_DOES_fire (non-vacuity twin), ::test_a_sent_row_takes_the_EXISTING_guard_not_this_one (complementary-not-overlapping proof)"
        status: pass
    human_judgment: false
  - id: D3
    description: "The guard is genuinely epoch-scoped against real SQL: a reserved row is visible to the new guard and invisible to the proven-sent guard, and a real clear_reply_context epoch bump restores the operator's ability to resend"
    requirement: "QUEUE-02"
    verification:
      - kind: integration
        ref: "tests/test_send_idempotency.py::test_the_unconfirmed_guard_is_epoch_scoped, ::test_a_human_epoch_bump_clears_the_guard (both @pytest.mark.integration + @pytest.mark.queueproof, executed against a live Postgres in this worktree)"
        status: pass
    human_judgment: false
  - id: D4
    description: "An escalated (ERROR) run is never auto-rewound by a reclaim, and all five falsifying mutations were executed against live code and reverted"
    requirement: "QUEUE-02, QUEUE-03"
    verification:
      - kind: unit
        ref: "tests/test_send_idempotency.py::test_an_escalated_run_is_not_rewound_by_a_reclaim"
        status: pass
      - kind: other
        ref: "Five falsifying mutations executed live in this session (see 'Falsifying Mutations' section below) — RED output captured, all reverted, git diff --stat clean afterward"
        status: pass
    human_judgment: false

duration: 55min
completed: 2026-07-14
status: complete
---

# Phase 16 Plan 10: Fail-Closed Unconfirmed-Send Guard Summary

**Closes the double-send window Phase 16's own reclaim path opens: an epoch-scoped `get_unconfirmed_outbound` read plus a shared `send_guard.assert_no_unconfirmed_send` check wired into both `clarify()` and `deliver()`, so a worker killed between the email provider accepting a send and the local `sent`-state commit escalates to `ERROR` instead of emailing the client a second time — proven against real Postgres and proven to red on all five falsifying mutations.**

## Performance

- **Duration:** ~55 min
- **Tasks:** 3 of 3 completed
- **Files modified:** 8 (2 created, 6 modified)

## Accomplishments

- `app/db/repo/emails.py::get_unconfirmed_outbound(run_id, *, purpose, round=0, conn=None)`: epoch-scoped, purpose-scoped, round-scoped read of a `'reserved'`/`'failed'` outbound row — complementary to (never a replacement for) `get_outbound_message_id`/`get_outbound_for_round`, which stay byte-identical. Re-exported through the `app/db/repo` facade.
- `app/pipeline/send_guard.py`: `UnconfirmedSendError` (its class name is the operator-facing `error_reason`) and `assert_no_unconfirmed_send(run_id, *, purpose, round=0, conn=None)`, the one shared guard both `clarify()` and `delivery.py::deliver()` call — a duplicated money-path guard is a DRY violation this project treats as a defect, so it lives in one module.
- `app/pipeline/clarification.py::clarify()`: the guard call sits immediately after the existing round-idempotency early-return and strictly before the alias-candidate capture, the suggestion LLM call, and `send_outbound` — nothing between the guard and the send can fire.
- `app/pipeline/delivery.py::deliver()`: the guard call sits immediately after the existing already-sent early-return (Step 1) and before line items load (Step 2).
- `tests/conftest.py`: `InMemoryRepo.get_unconfirmed_outbound` mirrors the real predicate (purpose ValueError guard, epoch scoping against the run's current `reply_epoch`, `send_state IN ('reserved','failed')`), registered in the `fake_repo` monkeypatch name tuple.
- `tests/test_send_idempotency.py`: 9 tests total — 1 hermetic FakeConnection SQL-shape proof (catches a real-SQL regression that the fake_repo pipeline tests structurally cannot see), 6 hermetic pipeline-flow proofs (including the non-vacuity twin and the complementary-guard proof), 2 live-DB proofs (`@pytest.mark.integration` + `@pytest.mark.queueproof`) executed against a real Postgres in this worktree.
- `tests/test_delivery.py`: two pre-existing tests that drive `deliver()` directly against a monkeypatched (non-`fake_repo`) `repo` needed a new stub for `get_unconfirmed_outbound` — otherwise the guard's real, DATABASE_URL-backed implementation would have fired inside a test with no database configured. Documented under Deviations.
- Full hermetic suite green (682 passed, 64 skipped — 2 of the new skips are this plan's own live-DB tests when `DATABASE_URL` is unset), `mypy app` (strict, 55 files) clean, `ruff check .` clean, `tests/test_bound01_private_imports.py` and `tests/test_comment_provenance_guard.py` both green.
- All five falsifying mutations executed against a live Postgres in this session (see below), reverted, `git diff --stat` clean on every mutated file afterward.

## Task Commits

Each task was committed atomically:

1. **Task 1: `get_unconfirmed_outbound` — the epoch-scoped unconfirmed-reservation read** — `fb36f6f` (feat)
2. **Task 2: `app/pipeline/send_guard.py` + the two call sites (clarify, deliver)** — `818a91b` (feat)
3. **Task 3: `tests/test_send_idempotency.py` — guard proofs, the non-vacuity twin, the live-DB epoch proof** — `be64511` (test)

**Plan metadata:** committed by the orchestrator after wave merge (this executor runs in worktree mode and does not write STATE.md/ROADMAP.md).

## Files Created/Modified

- `app/db/repo/emails.py` — `get_unconfirmed_outbound` (NEW function; `get_outbound_message_id`/`get_outbound_for_round` byte-identical to before)
- `app/db/repo/__init__.py` — facade re-export + `__all__` entry
- `app/pipeline/send_guard.py` — `UnconfirmedSendError`, `assert_no_unconfirmed_send` (NEW)
- `app/pipeline/clarification.py` — guard call in `clarify()`
- `app/pipeline/delivery.py` — guard call in `deliver()`
- `tests/conftest.py` — `InMemoryRepo.get_unconfirmed_outbound` + `fake_repo` tuple entry
- `tests/test_send_idempotency.py` — the 9-test proof file (NEW)
- `tests/test_delivery.py` — 2 pre-existing tests stubbed for the new repo call (see Deviations)

## Decisions Made

- `get_unconfirmed_outbound` is a genuinely new function, never a widening of the two proven-sent guards — see `key-decisions` above and the function's own docstring, which states the asymmetry explicitly so a future reader is not tempted to merge them.
- The guard reuses `ERROR` and the existing orchestrator/`approve()` catch-all error boundaries rather than adding a new `RunStatus` member or a bespoke escalation mechanism — `ERROR` is already outside `rewind_for_reclaim`'s scope, already operator-visible, and already the retrigger route's `ERROR -> RECEIVED` epoch-bumping escape hatch.
- Added a hermetic `FakeConnection`-backed SQL-shape test (`test_get_unconfirmed_outbound_sql_shape`) beyond the plan's own numbered test list, because the plan's falsifying mutation (a) — reverting the WHERE clause to `send_state = 'sent'` — cannot be observed by any test that goes through `fake_repo`'s `InMemoryRepo` mirror; that mirror is a hand-written Python reimplementation of the predicate, not the real SQL. This is the same fake/real split this codebase already documents in `tests/test_email_epoch_arbiter_integration.py`'s own docstring ("escaping [fake_repo and mock_llm] is the entire point"). Without the hermetic SQL-shape test, mutation (a) would only be caught by the two live-DB tests — still a real proof, but not the FAST hermetic feedback loop Task 1's own acceptance criteria asked for ("Assert the shape hermetically against FakeConnection's recorded statements, in the style of tests/test_repo_jobs_sql.py").

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Two pre-existing `test_delivery.py` tests needed a stub for the new repo call**

- **Found during:** Task 2 full-suite verification
- **Issue:** `test_deliver_attaches_roster_to_exception_after_roster_load` and `test_deliver_failure_before_roster_load_carries_no_roster` drive `deliver()` directly, monkeypatching individual `app.pipeline.delivery.repo.*` attributes rather than using the `fake_repo` fixture. Neither test stubbed the new `repo.get_unconfirmed_outbound` call the guard adds, so the guard's REAL, `DATABASE_URL`-backed implementation ran inside a test with no configured database, raising a Pydantic `ValidationError` on `Settings.database_url` instead of the test's intended `RuntimeError`.
- **Fix:** Added `monkeypatch.setattr("app.pipeline.delivery.repo.get_unconfirmed_outbound", lambda rid, *, purpose, round=0, conn=None: None)` alongside each test's existing `get_outbound_message_id` stub.
- **Files modified:** `tests/test_delivery.py`
- **Verification:** `uv run pytest tests/test_delivery.py -q` -> 42 passed (was 2 failed before the fix); full hermetic suite re-run green afterward.
- **Committed in:** `818a91b` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 — a blocking test-setup gap directly caused by this plan's own mandated new call site, not a pre-existing unrelated issue).
**Impact on plan:** No scope creep; a direct, unavoidable consequence of adding the guard call to a function two pre-existing tests already drove without the full `fake_repo` fixture.

## Falsifying Mutations

All five executed against live code in this worktree, RED output captured, then reverted. `git diff --stat` on each mutated file was empty after every revert (verified explicitly, not merely asserted).

### (a) THE ONE THE REVIEW DEMANDS — revert the WHERE to `send_state = 'sent'`

Mutated `app/db/repo/emails.py`'s single occurrence of `AND send_state IN ('reserved', 'failed')` to `AND send_state = 'sent'` (grep-confirmed exactly one occurrence in the file before mutating, to rule out a docstring-copy collision).

```
FAILED tests/test_send_idempotency.py::test_get_unconfirmed_outbound_sql_shape
FAILED tests/test_send_idempotency.py::test_the_unconfirmed_guard_is_epoch_scoped
FAILED tests/test_send_idempotency.py::test_a_human_epoch_bump_clears_the_guard
3 failed, 6 passed in 0.45s
```

The hermetic SQL-shape test and both live-DB tests go red. The `fake_repo`-driven pipeline tests (1, 3, 5 in the plan's own numbering) stay green here because they exercise `InMemoryRepo`'s hand-written Python mirror, not the real SQL — see "Decisions Made" above for why the hermetic SQL-shape test was added specifically to close this gap. Between the SQL-shape test and the two live-DB tests, mutation (a) is unambiguously caught at both a hermetic and a real-database layer.

Reverted; `git diff --stat app/db/repo/emails.py` empty afterward; full 9/9 green re-confirmed.

### (b) Delete the `assert_no_unconfirmed_send(...)` call from `clarify()`

```
FAILED tests/test_send_idempotency.py::test_a_reserved_row_blocks_the_rerun_and_escalates
FAILED tests/test_send_idempotency.py::test_a_failed_row_blocks_the_rerun_too
2 failed, 7 passed in 0.45s
```

Both clarify-side reserved/failed proofs go red (the send spy shows the provider WAS called: `assert 1 == 0`). Reverted; `git diff --stat app/pipeline/clarification.py` empty afterward; full 9/9 green re-confirmed.

### (c) Delete the guard call from `deliver()`

```
FAILED tests/test_send_idempotency.py::test_a_reserved_confirmation_blocks_deliver
1 failed, 8 passed in 0.45s
```

The confirmation twin goes red (`pytest.raises(UnconfirmedSendError)` — `Failed: DID NOT RAISE`). Reverted; `git diff --stat app/pipeline/delivery.py` empty afterward; full 9/9 green re-confirmed.

### (d) Drop the epoch correlated subquery from `get_unconfirmed_outbound`'s WHERE

```
FAILED tests/test_send_idempotency.py::test_get_unconfirmed_outbound_sql_shape
FAILED tests/test_send_idempotency.py::test_the_unconfirmed_guard_is_epoch_scoped
FAILED tests/test_send_idempotency.py::test_a_human_epoch_bump_clears_the_guard
3 failed, 6 passed in 0.46s
```

The hermetic SQL-shape test (asserts `"reply_epoch FROM payroll_runs"` is present in the recorded SQL text) and both live-DB tests go red — the operator-recovery test's `assert_no_unconfirmed_send` call now raises even after `clear_reply_context`, because the query can no longer see the epoch bump. Reverted (restored both the subquery clause and its parameter); `git diff --stat app/db/repo/emails.py` empty afterward; full 9/9 green re-confirmed.

### (e) Vacuity check — must stay GREEN

Ran `test_no_reserved_row_means_the_send_DOES_fire` unmodified (no mutation applied):

```
tests/test_send_idempotency.py::test_no_reserved_row_means_the_send_DOES_fire PASSED [100%]
1 passed in 0.23s
```

Confirms the non-vacuity twin is not itself a false-positive — every "no second send" assertion elsewhere in the file rests on a send that genuinely CAN fire when nothing blocks it.

## `-m queueproof --collect-only` Output (proves the narrow CI gate actually collects Section B)

```
tests/test_queue_durability.py::test_the_isolation_fixture_refuses_to_delete_beneath_a_live_worker
tests/test_queue_durability.py::test_the_delete_gate_runs_on_both_sides_of_the_yield
tests/test_queue_durability.py::test_genuine_claim_race_exactly_one_winner
tests/test_queue_durability.py::test_expired_lease_is_reclaimed
tests/test_queue_durability.py::test_zombie_is_fenced_on_BOTH_complete_and_fail
tests/test_queue_durability.py::test_release_leases_returns_the_row_to_pending_immediately
tests/test_queue_durability.py::test_the_database_refuses_a_run_pipeline_job_with_a_null_run_id
tests/test_queue_durability.py::test_rewind_for_reclaim_leaves_reply_epoch_untouched
tests/test_queue_durability.py::test_skip_locked_steps_over_a_row_another_worker_is_holding
tests/test_send_idempotency.py::test_the_unconfirmed_guard_is_epoch_scoped
tests/test_send_idempotency.py::test_a_human_epoch_bump_clears_the_guard

11/746 tests collected (735 deselected) in 0.52s
```

Both of this plan's Section B tests are listed, confirming the `queueproof` marker selector (from plan 16-02's narrow CI gate) actually picks them up.

Separately, driven against the live Postgres in this worktree with zero skips:

```
$ DATABASE_URL=postgresql://postgres:postgres@localhost:55432/wt1610 ALLOW_DB_RESET=1 \
  uv run pytest tests/test_send_idempotency.py -m queueproof -v
tests/test_send_idempotency.py::test_the_unconfirmed_guard_is_epoch_scoped PASSED [ 50%]
tests/test_send_idempotency.py::test_a_human_epoch_bump_clears_the_guard PASSED [100%]
2 passed, 6 deselected in 0.31s
```

## What a later phase changes about this guard

A later phase (message_id reuse, payload replay, an email-provider idempotency key) is expected to keep this guard's detection predicate — `(run_id, purpose, round, epoch)` scoped, `send_state IN ('reserved','failed')` — completely unchanged, and only widen the ACTION taken when it matches: instead of unconditionally escalating to `ERROR`, a retry that lands within the provider's replay-retention window becomes provably safe and can be replayed using the original reservation's identity; escalation is retained only for the case that falls outside that window. `get_unconfirmed_outbound` and `assert_no_unconfirmed_send` were written with that split already in mind — the repo function's job stays "detect a possible duplicate," never "decide what to do about it," so a later phase's planner inherits the boundary rather than re-deriving it.

## Issues Encountered

None beyond the Rule 3 auto-fix documented above. A live Postgres was reachable in this worktree throughout (a dedicated database provisioned for this session), so every live-DB acceptance criterion in the plan — including all five falsifying mutations — was actually executed, not deferred.

## User Setup Required

None — no external service configuration required. This plan's live-DB tests (`-m queueproof`) run against the same Postgres infrastructure the `queueproof` CI gate (plan 16-02) already targets.

## Next Phase Readiness

- `app/pipeline/send_guard.py` is ready for wave 4 (16-07's live daemon workers, 16-08's producer, 16-09's durability proofs) — the reclaim path those plans make live is exactly the path this guard protects, and it is merged ahead of them as this plan's own ordering constraint required.
- The guard's detection predicate is ready for a later phase's SEND-01/02/03-class work (message_id reuse, payload replay, an idempotency key) to widen the action without touching the predicate — see "What a later phase changes about this guard" above.

---
*Phase: 16-queue-substrate-unblocked-webhook*
*Completed: 2026-07-14*

## Self-Check: PASSED

All 9 claimed files found on disk (app/db/repo/emails.py, app/db/repo/__init__.py,
app/pipeline/send_guard.py, app/pipeline/clarification.py, app/pipeline/delivery.py,
tests/conftest.py, tests/test_send_idempotency.py, tests/test_delivery.py, this
SUMMARY.md). All 3 claimed commit hashes (fb36f6f, 818a91b, be64511) found in
`git log --oneline --all`. No missing items.
