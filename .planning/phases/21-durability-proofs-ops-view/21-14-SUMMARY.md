---
phase: 21-durability-proofs-ops-view
plan: 14
subsystem: testing
tags: [live-postgres, concurrency-proof, contract-drift, queue-durability, delivery, resume-pipeline]

# Dependency graph
requires:
  - phase: 21-durability-proofs-ops-view (wave 0 gap plans)
    provides: "The Phase 16-20 durable-queue architecture (reserve->settle outbound contract, fenced job settlement, producer/consumer PipelineResult split) that these tests must be re-aligned to."
provides:
  - "A1 fixed: the app.pipeline.delivery.deliver monkeypatch stub in tests/test_concurrency_proof.py now matches production's real keyword-only conn signature; test_concurrent_approvals_exactly_one_wins passes and is falsification-proven to still discriminate a broken CAS."
  - "A2 fixed: test_a_retry_within_the_same_conversation_updates_the_row_in_place in tests/test_email_epoch_arbiter_integration.py now drives the real reserve_outbound_snapshot -> update_email_message_sent contract instead of the retired ON CONFLICT DO UPDATE assumption."
  - "Written app-bug/test-bug verdicts with file:line citations for all 8 CI-invisible failures in tests/test_atomic_persist.py and tests/test_ingest.py, gating task 3's fix work."
  - "A measured (not inferred) pre-existing failure set at 47c0af0: 2 in test_atomic_persist.py + 1 in test_ingest.py, via a scratch worktree + throwaway DB bisection."
affects: [durability-proofs, concurrency-proof.yml, delivery, orchestrator, queue]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Falsification-before-commit for repaired assertions: temporarily break the invariant the test claims to prove (CAS guard, settle call), confirm the test reds, then revert byte-identical before committing — applied to both A1 and A2."
    - "Bisection via a scratch git worktree + a throwaway Postgres database, reusing the caller's built venv with UV_PROJECT_ENVIRONMENT + `uv run --no-sync` so the shared venv is never resynced against an older lockfile."

key-files:
  created: []
  modified:
    - tests/test_concurrency_proof.py
    - tests/test_email_epoch_arbiter_integration.py

key-decisions:
  - "A2's rewritten test exercises reserve_outbound_snapshot (freeze) then update_email_message_sent (settle) as two explicit steps, keyed on the SAME frozen message_id, matching the real production contract at app/db/repo/emails.py:184 and :657 — not a paraphrase of the old ON CONFLICT DO UPDATE behavior."
  - "All 8 CI-invisible failures are diagnosed as test-bug/contract drift, not app bugs — no production code was changed in this plan."

requirements-completed: []  # PROOF-04/PROOF-05 land fully only after task 3; this SUMMARY covers tasks 1-2 only (checkpoint).

# Metrics
duration: ~55min (tasks 1-2 only; task 3 not started)
completed: 2026-07-20
status: checkpoint
---

# Phase 21 Plan 14: Durability Proofs — CI-Invisible Failure Repair Summary

**Task 1 (A1 delivery-stub signature + A2 epoch-arbiter send-state contract) is fixed and falsification-proven; Task 2 diagnosed all 8 CI-invisible `test_atomic_persist.py`/`test_ingest.py` failures as test-bug contract drift with file:line citations — STOPPED at the mandatory checkpoint before Task 3's fixes.**

## Status: 2 of 3 tasks complete — Task 3 (apply fixes per the verdicts below) is a pending checkpoint, awaiting direction.

## Performance

- **Duration:** ~55 min (tasks 1-2)
- **Tasks:** 2 of 3 complete
- **Files modified:** 2 (tests/test_concurrency_proof.py, tests/test_email_epoch_arbiter_integration.py)

## Task 1 — A1 + A2 repair (commit `fddb918`)

### A1 — `test_concurrent_approvals_exactly_one_wins`

**Root cause:** the monkeypatch stub at `tests/test_concurrency_proof.py:122` declared `lambda rid, run:` while `app/routes/runs.py:424` calls `delivery.deliver(run_id, run, conn=conn)`. The keyword-only `conn` argument TypeErrored, the delivery error boundary in `app/routes/runs.py` caught it, the transaction rolled back, the CAS was undone, and all 8 threads re-claimed — 0 deliveries instead of 1.

**Fix:** the stub now reads `lambda rid, run, *, conn=None: deliver_calls.append(rid)`, matching `app/pipeline/delivery.py:79-84`'s real signature and the `test_hitl.py:110,430,470` sibling idiom.

**Non-tautology falsification (truth #3):** temporarily removed the `AND status = %s` clause from `claim_status`'s SQL in `app/db/repo/runs.py` (an executable statement, confirmed via `grep -n` before mutating — not a docstring copy), reran `test_concurrent_approvals_exactly_one_wins`, and observed a genuine red: `assert 8 == 1` — all 8 threads won the broken CAS and all 8 called `deliver`. Reverted byte-identical (`git diff` confirmed empty) before committing. The repaired test still discriminates a broken CAS; it is not a tautology.

### A2 — `test_a_retry_within_the_same_conversation_updates_the_row_in_place`

**Root cause:** the test asserted a retired contract — two `insert_email_message` calls (send_state `reserved` then `sent`) expecting an in-place `ON CONFLICT ... DO UPDATE`. `app/db/repo/emails.py:84`'s outbound `ON CONFLICT` clause is now `DO NOTHING`; a second `insert_email_message` call can only return the id of the row already there, never advance its state. `send_state` now legitimately advances through exactly one door: `update_email_message_sent` (`app/db/repo/emails.py:657`), keyed on the SAME synthetic `message_id` the reservation minted.

**Fix:** rewrote the test to drive the real reserve→settle contract — `repo.reserve_outbound_snapshot(...)` freezes the slot and its `message_id` once, then `repo.update_email_message_sent(reserved_message_id)` advances `reserved -> sent`. Assertions: exactly one row, `send_state == "sent"`, and `message_id` unchanged from the frozen reservation identity (proving the settle step advances the SAME row rather than minting a second one under a new identity).

**Falsification (truth #4, task 1 step 4):** temporarily skipped the `update_email_message_sent` call (replaced with `pass`), reran the test, and observed a genuine red: `assert 'reserved' == 'sent'` — the rewritten assertions are not rewritten-to-match-observed-behavior; they discriminate a genuinely wrong (never-advanced) outcome. Reverted before committing (`git diff` confirmed empty on the mutation).

**Verification:** `uv run pytest tests/test_concurrency_proof.py tests/test_email_epoch_arbiter_integration.py -m integration -v -rs` → **5 passed, 0 skipped** (baseline was 2 failed, 3 passed).

## Task 2 — Diagnosis of the 8 CI-invisible failures (commit pending — this SUMMARY IS the diagnosis artifact)

### Measured pre-existing set (task 2 step 1)

Per the plan's mandate, the pre-existing set was **measured**, not inferred from counts. Created a scratch git worktree at `47c0af0` under `/private/tmp/gsd-p2114-scratch/wt-47c0af0`, reused this worktree's already-built venv via `UV_PROJECT_ENVIRONMENT=<this-worktree>/.venv` + `uv run --no-sync` (confirmed no resync/mutation of the shared venv — a follow-up `--no-sync` run against the current worktree's own test suite still passed 3/3 afterward), and ran the same two test files against a separate throwaway database `pa_p21_14_bisect_47c0af0` (never touching `pa_p21_14`). Both the initial run and a repeat `--no-sync` run agreed:

```
3 failed, 16 passed
FAILED tests/test_atomic_persist.py::test_defer_field_regression_write_survives_later_clarify_failure
FAILED tests/test_atomic_persist.py::test_round2_clarified_fields_persist_before_run_stages
FAILED tests/test_ingest.py::test_duplicate_delivery_pipeline_runs_once
```

This exactly matches the plan's "2-failed atomic_persist + 1 ingest failure" description and identifies WHICH three they are. The scratch worktree and throwaway database were removed after measurement (`git worktree remove --force`, `DROP DATABASE`).

Also confirmed: `git log --oneline 47c0af0..HEAD -- tests/test_atomic_persist.py tests/test_ingest.py` returns **zero commits** — neither test file has been edited at all since `47c0af0` (163 commits later). Every one of the 8 failures is therefore production-code drift underneath an unedited test, not a test edited incorrectly.

### Verdict table (all 8 — required before any fix, per truth #4 / T-21-14-01)

| # | Test | File:line | Verdict | Evidence |
|---|------|-----------|---------|----------|
| 1 | `test_deliver_finalize_alias_failure_still_reaches_reconciled` | `tests/test_atomic_persist.py:769` | **TEST-BUG** (Phase 20 contract drift) | Calls `delivery.deliver(run_id, run)` directly expecting it to synchronously call Resend, `write_aliases_if_safe`, and `set_status` through to `reconciled`. `app/pipeline/delivery.py:79-107`'s `deliver()` now only reserves the confirmation snapshot and enqueues a `SEND_OUTBOUND` job — "Provider work is intentionally absent from this function; the queue handler reads the stored snapshot later" (docstring, `delivery.py:83-85`). Ran the test: run status stays `approved`, never reaches `reconciled` (`assert 'approved' == 'reconciled'`). Zero `drain`/`claim_job`/`settle_outbound` calls anywhere in the file (`grep -c` = 0). |
| 2 | `test_deliver_finalize_genuine_db_alias_failure_still_reaches_reconciled` | `tests/test_atomic_persist.py:802` | **TEST-BUG** (Phase 20 contract drift) | Same root cause as #1 — same direct `_deliver(run_id, run)` call, same synchronous-finalize assumption. Ran: `assert 'approved' == 'reconciled'`. |
| 3 | `test_deliver_finalize_status_crash_leaves_run_at_approved` | `tests/test_atomic_persist.py:865` | **TEST-BUG** (Phase 20 contract drift) | Monkeypatches `repo.set_status` to raise, expecting `deliver()` to call it inline (`pytest.raises(RuntimeError, match="injected crash")`). Ran: `Failed: DID NOT RAISE RuntimeError` — `deliver()` never calls `set_status` at all anymore; that write happens later in the fenced settlement handler (`app/db/repo/job_settlement.py`), not inside `deliver()`. |
| 4 | `test_deliver_finalize_crash_preserves_payroll_roster_attribute` | `tests/test_atomic_persist.py:901` | **TEST-BUG** (Phase 20 contract drift) | Same as #3 — same `set_status` boom, same `pytest.raises` expectation. Ran: `Failed: DID NOT RAISE RuntimeError`. |
| 5 | `test_deliver_retry_over_sent_completes_alias_write_exactly_once` | `tests/test_atomic_persist.py:936` | **TEST-BUG** (Phase 20 contract drift) | First `_deliver(run_id, run)` call already fails its own `post_first["status"] == "reconciled"` assertion (`assert 'approved' == 'reconciled'`) before the exactly-once alias-write assertion is ever reached — same root cause as #1/#2. |
| 6 | `test_defer_field_regression_write_survives_later_clarify_failure` | `tests/test_atomic_persist.py:503` | **TEST-BUG** (Phase 18 contract drift; pre-existing at `47c0af0`, measured) | Calls `resume_pipeline(run_id, reply)` directly, expecting `resume_pipeline`'s own except block (`app/pipeline/orchestrator.py:857-859`) to write `RunStatus.ERROR`. Confirmed by grep: `resume_pipeline` (`orchestrator.py:246-859`) contains **zero** `set_status`/`RunStatus.ERROR` calls in its body — the except block only calls `classify_pipeline_exception(...)` and **returns** a `PipelineResult`; it never persists. The actual terminal-error writer is `_set_run_error` in `app/db/repo/job_settlement.py:615-633`, gated on `expected_status=RunStatus.EXTRACTING` — called only from the queue-drain settlement path after a queue handler (`app/queue/handlers/resume_reply.py:92-95`) wraps `resume_pipeline`'s returned `PipelineResult`. This is exactly the Phase 18 "producers classify and return; drain settlement is the sole terminal-persistence owner" split (STATE.md Phase 18 decisions). Ran: run status stays `extracting` (the pre-persist claim state), never advances to `error` — matching `_set_run_error`'s `expected_status` gate precisely. |
| 7 | `test_round2_clarified_fields_persist_before_run_stages` | `tests/test_atomic_persist.py:579` | **TEST-BUG** (Phase 18 contract drift; pre-existing at `47c0af0`, measured) | Identical root cause to #6 — same direct `resume_pipeline(run_id, reply)` call, same "resume_pipeline's own genuine second `set_status` call" assumption stated explicitly in its own docstring (`:602-603`). Ran: `assert 'extracting' == 'error'`. |
| 8 | `test_duplicate_delivery_pipeline_runs_once` | `tests/test_ingest.py:259` | **TEST-BUG** (Phase 19 contract drift; pre-existing at `47c0af0`, measured) | POSTs directly to `/webhook/inbound` twice and expects `email_messages` to already hold the row synchronously. `app/routes/webhook.py:84-108`'s durable receipt boundary now only commits the `inbound_events` row + an identifier-only `INGEST` job and calls `wake.wake()` (`webhook.py:174-175`) — a plain `threading.Event.set()` (`app/queue/wake.py`) that only a running lifespan-owned worker thread (`app/queue/worker.py`, `app.main.app`'s `lifespan=worker.lifespan`) would observe. The test's `TestClient(app, raise_server_exceptions=True)` is constructed **without** the `with` context manager, so ASGI lifespan startup never fires and no worker thread exists to drain the enqueued job. Confirmed empirically (diagnosis-only, reverted before commit): inserting `assert drain.drain_once() is DrainOutcome.DONE` between the two POSTs and the DB assertion makes the test pass. This test's own **mocked twin one function above it** (`test_duplicate_delivery_pipeline_runs_once_unit`, `tests/test_ingest.py:176`) was already updated for exactly this durable contract (`assert fake_repo.runs == {}` after both POSTs, then an explicit `drain.drain_once()` call) — the live-DB counterpart was simply never brought forward to match when Phase 19's webhook cutover landed. Ran (unmodified): `assert 0 == 1` — zero rows, not two — confirming this is a missing-drain gap, not a broken dedup constraint (a genuinely broken `ON CONFLICT` would have produced 2 rows, not 0). |

### Summary of the 8

- **5 of 8** are Phase 20 contract drift (`deliver()`'s job changed from synchronous send-through-reconciled to reserve+enqueue only).
- **2 of 8** are Phase 18 contract drift (`resume_pipeline()`'s job changed from self-terminal-persisting ERROR to returning a `PipelineResult` for the queue-drain settlement layer to persist) — these are 2 of the 3 pre-existing failures measured at `47c0af0`.
- **1 of 8** is Phase 19 contract drift (`/webhook/inbound` changed from synchronous end-to-end processing to durable-receipt-only + async drain) — the 3rd pre-existing failure measured at `47c0af0`.
- **0 of 8 are app bugs.** No production code defect was found. This finding — that all three pre-existing, previously-undiagnosed failures are also contract drift rather than genuine defects — is itself the deliverable of this checkpoint, per the plan's "a real bug is most likely to be hiding here" framing. None was found; all three resolve to the same class of gap as the other five (a test never updated when its producer's contract moved behind the queue).

**No production code was changed in this plan.** `app/db/repo/runs.py`'s temporary A1 falsification mutation was reverted byte-identical (confirmed via `git diff` returning empty) before the task 1 commit.

## Task Commits

1. **Task 1: A1 + A2 — repair the two CI-visible integration failures** - `fddb918` (fix)
2. **Task 2: Diagnose the eight invisible failures — CHECKPOINT** - pending (this SUMMARY is the diagnosis artifact; docs commit follows)

## Files Created/Modified

- `tests/test_concurrency_proof.py` — A1: keyword-only `conn` parameter on the `deliver` monkeypatch stub
- `tests/test_email_epoch_arbiter_integration.py` — A2: rewritten to the reserve→settle contract

## Decisions Made

- A2's rewrite exercises the two real production entry points (`reserve_outbound_snapshot`, `update_email_message_sent`) as two explicit steps rather than trying to paraphrase the old upsert behavior through a single call — this is the only way to test the ACTUAL contract instead of a plausible-looking approximation of it.
- Both falsification mutations (A1's CAS removal, A2's skipped settle call) were applied directly to `grep -n`-confirmed executable code/test lines, run, observed to red, and reverted before any commit — never left in place, never deferred.

## Deviations from Plan

None — plan executed exactly as written through task 2. No Rule 1-4 auto-fixes were needed or applied; task 2 explicitly forbids fixing anything before the checkpoint, which was honored (diagnosis only, all diagnostic mutations reverted).

## Issues Encountered

None blocking. The scratch-worktree venv reuse via `UV_PROJECT_ENVIRONMENT` required `uv run --no-sync` (not the plan's example bare `uv run`) to avoid resyncing the shared venv against `47c0af0`'s older lockfile mid-session — verified safe by confirming the current worktree's own tests still passed after the scratch-worktree runs.

## User Setup Required

None.

## Next Phase Readiness

**BLOCKED on human/orchestrator direction before task 3 can proceed**, per this plan's `autonomous: false` checkpoint. Task 3 ("Fix the eight, per the verdicts") should:

1. Migrate the 5 Phase-20-drift tests (`test_deliver_finalize_*`, `test_deliver_retry_over_sent_completes_alias_write_exactly_once`) off the direct `_deliver(run_id, run)` call onto the real reserve→enqueue→drain→settle path — a currently-passing live-DB test that already drives delivery through the queue should be the model to follow (not yet identified by file:line in this diagnosis; task 3 should locate one, e.g. among `tests/test_send_idempotency.py` or `tests/test_queue_durability.py`).
2. Migrate the 2 Phase-18-drift tests (`test_defer_field_regression_write_survives_later_clarify_failure`, `test_round2_clarified_fields_persist_before_run_stages`) to either (a) assert the returned `PipelineResult`'s classification directly instead of a persisted `RunStatus.ERROR`, or (b) route the call through the queue handler (`app/queue/handlers/resume_reply.py`) + `drain.drain_once()` so the fenced settlement layer actually persists ERROR — task 3 must decide which preserves the test's stated intent (diagnosable ERROR state) without becoming a tautology.
3. Fix `test_duplicate_delivery_pipeline_runs_once` by adding the same `drain.drain_once()` step its mocked twin (`test_duplicate_delivery_pipeline_runs_once_unit`) already uses — empirically confirmed sufficient in this diagnosis pass (reverted before commit).
4. Re-verify `test_deliver_retry_over_sent_completes_alias_write_exactly_once` and `test_duplicate_delivery_pipeline_runs_once` specifically still exercise their stated exactly-once claims after migration (T-21-14-04) — a version that passes because it no longer exercises the retry is a regression disguised as a fix.
5. Re-run the full plan's two verification commands (the 2-file `-m integration` suite, then the full `tests/` live-DB run) once task 3 lands, scoped against this plan's 4 files only (the 13 `test_queue_durability.py` failures belong to plan 21-13, not this plan).

---
*Phase: 21-durability-proofs-ops-view*
*Completed (checkpoint): 2026-07-20*
