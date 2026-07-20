---
phase: 21-durability-proofs-ops-view
plan: 14
subsystem: testing
tags: [live-postgres, concurrency-proof, contract-drift, queue-durability, delivery, resume-pipeline]

# Dependency graph
requires:
  - phase: 21-durability-proofs-ops-view (wave 0 gap plans)
    provides: "The Phase 16-20 durable-queue architecture (reserve->settle outbound contract, fenced job settlement, producer/consumer PipelineResult split) that these tests are re-aligned to."
provides:
  - "A1 fixed: the app.pipeline.delivery.deliver monkeypatch stub in tests/test_concurrency_proof.py now matches production's real keyword-only conn signature; test_concurrent_approvals_exactly_one_wins passes and is falsification-proven to still discriminate a broken CAS."
  - "A2 fixed: test_a_retry_within_the_same_conversation_updates_the_row_in_place in tests/test_email_epoch_arbiter_integration.py now drives the real reserve_outbound_snapshot -> update_email_message_sent contract instead of the retired ON CONFLICT DO UPDATE assumption."
  - "All 8 CI-invisible failures in tests/test_atomic_persist.py and tests/test_ingest.py diagnosed (app-bug/test-bug verdicts with file:line citations) and fixed, each migrated to the real contract that replaced the one it was written against — three distinct migration targets across Phase 18/19/20 contract drift, not one uniform pattern."
  - "A measured (not inferred) pre-existing failure set at 47c0af0: 2 in test_atomic_persist.py + 1 in test_ingest.py, via a scratch worktree + throwaway DB bisection."
  - "Both named exactly-once claims (test_deliver_retry_over_sent_completes_alias_write_exactly_once, test_duplicate_delivery_pipeline_runs_once) are falsification-proven, not just passing."
  - "A stale single-arg resend.Emails.send test mock (pre-existing, silently masking delivery-path test intent) fixed across 5 call sites."
affects: [durability-proofs, concurrency-proof.yml, delivery, orchestrator, queue]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Falsification-before-commit for repaired assertions: temporarily break the invariant the test claims to prove (CAS guard, settle call, exactly-once guard, uniqueness constraint), confirm the test reds, then revert byte-identical before committing — applied to every repaired/migrated assertion in this plan, not just the two CI-visible ones."
    - "Bisection via a scratch git worktree + a throwaway Postgres database, reusing the caller's built venv with UV_PROJECT_ENVIRONMENT + `uv run --no-sync` so the shared venv is never resynced against an older lockfile."
    - "Migrating a test off a retired direct-call contract means finding the CURRENT production entry point (deliver()+drain.drain_once() for queued delivery; a persisted reply + enqueued RESUME_REPLY job + drain.drain_once() for resume failures; the same drain idiom for webhook ingest) rather than re-asserting the old behavior against a new API shape."

key-files:
  created: []
  modified:
    - tests/test_concurrency_proof.py
    - tests/test_email_epoch_arbiter_integration.py
    - tests/test_atomic_persist.py
    - tests/test_ingest.py

key-decisions:
  - "A2's rewritten test exercises reserve_outbound_snapshot (freeze) then update_email_message_sent (settle) as two explicit steps, keyed on the SAME frozen message_id, matching the real production contract at app/db/repo/emails.py:184 and :657 — not a paraphrase of the old ON CONFLICT DO UPDATE behavior."
  - "All 8 CI-invisible failures are diagnosed and confirmed as test-bug/contract drift, not app bugs — no production code was changed in this plan (two falsification mutations touched app/ and app/db/schema.sql transiently, both reverted byte-identical before their respective commits)."
  - "The 5 Phase-20-drift delivery tests migrate to deliver() + drain.drain_once() (the real reserve-enqueue-drain-settle path); the 2 crash-injection tests among them (status-crash, roster-preservation) instead target deliver()'s own try/except directly, since deliver() no longer writes run status at all — the old set_status(SENT) injection point has no successor inside deliver()."
  - "The 2 Phase-18-drift resume_pipeline tests migrate to a persisted reply row + an enqueued RESUME_REPLY job drained via drain.drain_once(), reaching through the real handle_resume_reply CAS chain (AWAITING_REPLY->RECEIVED->EXTRACTING) rather than asserting on a returned PipelineResult in isolation — this exercises the actual settle_pipeline_job -> _set_run_error path that now owns terminal persistence."
  - "The Phase-19-drift ingest test is strengthened beyond the minimal drain-once fix: a bare identical-payload redelivery is fully caught at the event-dedup layer, which would leave the message_id-level ON CONFLICT DO NOTHING the test is named for permanently unreachable from the test's own perspective — a third, genuinely distinct event carrying the same message_id was added to actually exercise that second layer."

requirements-completed: [PROOF-04, PROOF-05]

# Metrics
duration: ~2h10min
completed: 2026-07-20
status: complete
---

# Phase 21 Plan 14: Durability Proofs — CI-Invisible Failure Repair Summary

**All 10 live-DB failures in this plan's scope are fixed and falsification-proven — 2 CI-visible integration failures (a stale delivery-stub signature, a retired epoch-arbiter send-state contract) and 8 CI-invisible failures spanning three separate phases of contract drift (Phase 18's producer/consumer settlement split, Phase 19's durable webhook cutover, Phase 20's queued delivery), diagnosed at a mandatory mid-plan checkpoint before any fix was applied, with zero production code changes.**

## Performance

- **Duration:** ~2h10min
- **Tasks:** 3 of 3 complete
- **Files modified:** 4 (tests/test_concurrency_proof.py, tests/test_email_epoch_arbiter_integration.py, tests/test_atomic_persist.py, tests/test_ingest.py)

## Task 1 — A1 + A2 repair (commit `fddb918`)

### A1 — `test_concurrent_approvals_exactly_one_wins`

**Root cause:** the monkeypatch stub at `tests/test_concurrency_proof.py:122` declared `lambda rid, run:` while `app/routes/runs.py:424` calls `delivery.deliver(run_id, run, conn=conn)`. The keyword-only `conn` argument TypeErrored, the delivery error boundary in `app/routes/runs.py` caught it, the transaction rolled back, the CAS was undone, and all 8 threads re-claimed — 0 deliveries instead of 1.

**Fix:** the stub now reads `lambda rid, run, *, conn=None: deliver_calls.append(rid)`, matching `app/pipeline/delivery.py:79-84`'s real signature and the `test_hitl.py:110,430,470` sibling idiom.

**Non-tautology falsification (truth #3):** temporarily removed the `AND status = %s` clause from `claim_status`'s SQL in `app/db/repo/runs.py` (an executable statement, confirmed via `grep -n` before mutating — not a docstring copy), reran `test_concurrent_approvals_exactly_one_wins`, and observed a genuine red: `assert 8 == 1` — all 8 threads won the broken CAS and all 8 called `deliver`. Reverted byte-identical (`git diff` confirmed empty) before committing.

### A2 — `test_a_retry_within_the_same_conversation_updates_the_row_in_place`

**Root cause:** the test asserted a retired contract — two `insert_email_message` calls (send_state `reserved` then `sent`) expecting an in-place `ON CONFLICT ... DO UPDATE`. `app/db/repo/emails.py:84`'s outbound `ON CONFLICT` clause is now `DO NOTHING`; a second `insert_email_message` call can only return the id of the row already there, never advance its state. `send_state` now legitimately advances through exactly one door: `update_email_message_sent` (`app/db/repo/emails.py:657`), keyed on the SAME synthetic `message_id` the reservation minted.

**Fix:** rewrote the test to drive the real reserve→settle contract — `repo.reserve_outbound_snapshot(...)` freezes the slot and its `message_id` once, then `repo.update_email_message_sent(reserved_message_id)` advances `reserved -> sent`. Assertions: exactly one row, `send_state == "sent"`, and `message_id` unchanged from the frozen reservation identity.

**Falsification (truth #4):** temporarily skipped the `update_email_message_sent` call, reran the test, and observed a genuine red: `assert 'reserved' == 'sent'`. Reverted before committing.

**Verification:** `uv run pytest tests/test_concurrency_proof.py tests/test_email_epoch_arbiter_integration.py -m integration -v -rs` → **5 passed, 0 skipped** (baseline was 2 failed, 3 passed).

## Task 2 — Diagnosis of the 8 CI-invisible failures (commit `f9a3fb7`, `c258116`)

### Measured pre-existing set

The pre-existing set was **measured**, not inferred from counts. Created a scratch git worktree at `47c0af0` under `/private/tmp/gsd-p2114-scratch/wt-47c0af0`, reused this worktree's already-built venv via `UV_PROJECT_ENVIRONMENT=<this-worktree>/.venv` + `uv run --no-sync`, and ran the same two test files against a separate throwaway database `pa_p21_14_bisect_47c0af0` (never touching `pa_p21_14`):

```
3 failed, 16 passed
FAILED tests/test_atomic_persist.py::test_defer_field_regression_write_survives_later_clarify_failure
FAILED tests/test_atomic_persist.py::test_round2_clarified_fields_persist_before_run_stages
FAILED tests/test_ingest.py::test_duplicate_delivery_pipeline_runs_once
```

This exactly matches the plan's "2-failed atomic_persist + 1 ingest failure" description and identifies WHICH three they are. The scratch worktree and throwaway database were removed after measurement.

Also confirmed: `git log --oneline 47c0af0..HEAD -- tests/test_atomic_persist.py tests/test_ingest.py` returns **zero commits** — neither test file had been edited since `47c0af0` (163 commits later). Every one of the 8 failures was therefore production-code drift underneath an unedited test.

### Verdict table (all 8)

| # | Test | File:line | Verdict | Drift source |
|---|------|-----------|---------|---------------|
| 1 | `test_deliver_finalize_alias_failure_still_reaches_reconciled` | `tests/test_atomic_persist.py:769` | **TEST-BUG** | `deliver()`'s job changed from synchronous send-through-reconciled to reserve+enqueue only |
| 2 | `test_deliver_finalize_genuine_db_alias_failure_still_reaches_reconciled` | `tests/test_atomic_persist.py:802` | **TEST-BUG** | Same as #1 |
| 3 | `test_deliver_finalize_status_crash_leaves_run_at_approved` | `tests/test_atomic_persist.py:865` | **TEST-BUG** | `deliver()` never calls `set_status` anymore — that write is later, in the fenced settlement handler |
| 4 | `test_deliver_finalize_crash_preserves_payroll_roster_attribute` | `tests/test_atomic_persist.py:901` | **TEST-BUG** | Same as #3 |
| 5 | `test_deliver_retry_over_sent_completes_alias_write_exactly_once` | `tests/test_atomic_persist.py:936` | **TEST-BUG** | Same as #1 (first call never reaches `reconciled` synchronously) |
| 6 | `test_defer_field_regression_write_survives_later_clarify_failure` | `tests/test_atomic_persist.py:503` | **TEST-BUG** (pre-existing at `47c0af0`, measured) | `resume_pipeline` no longer self-persists `RunStatus.ERROR` — it classifies and returns a `PipelineResult`; only the queue-drain settlement layer persists terminal state now |
| 7 | `test_round2_clarified_fields_persist_before_run_stages` | `tests/test_atomic_persist.py:579` | **TEST-BUG** (pre-existing at `47c0af0`, measured) | Same as #6 |
| 8 | `test_duplicate_delivery_pipeline_runs_once` | `tests/test_ingest.py:259` | **TEST-BUG** (pre-existing at `47c0af0`, measured) | `/webhook/inbound` is durable-receipt-only now; a bare `TestClient(app)` (no `with`) never starts the lifespan worker that would drain the enqueued job |

**0 of 8 are app bugs.** No production code defect was found — the checkpoint's central question (is a real bug hiding among the three pre-existing, previously-undiagnosed failures) resolved to "no": all three are the same class of gap as the other five, a test never updated when its producer's contract moved behind the queue.

Full per-test evidence (exact assertion failures observed, `grep`/code citations) was recorded at the checkpoint and is preserved below in the Task 3 detail per test.

## Task 3 — Fix the eight, per the verdicts (commit `69cf0e3`)

Direction from the coordinator after the checkpoint: proceed with all fixes, migrate each test to the contract that actually replaced the one it was written against (three distinct targets, not one uniform pattern), falsification-prove the two named exactly-once claims, and make no production changes unless a genuine defect surfaced (none did).

### Group 1 — Phase-20 drift: `deliver()` + `drain.drain_once()` (5 tests)

`deliver()` now only reserves the outbound snapshot and enqueues a `SEND_OUTBOUND` job; the old finalize sequence (alias write in a nested SAVEPOINT, then advance to `reconciled`) lives in `app/db/repo/job_settlement.py`'s `_complete_confirmation_after_send`, invoked from `settle_outbound_delivery_job` after the queue-drain handler (`app/queue/handlers/send_outbound.py`) sends via the provider.

- `test_deliver_finalize_alias_failure_still_reaches_reconciled` and `test_deliver_finalize_genuine_db_alias_failure_still_reaches_reconciled`: migrated to `deliver()` (reserve+enqueue) then `drain.drain_once()` (send + settle, alias write isolated in the nested SAVEPOINT exactly as before, just relocated). Both pass; the alias-write-failure isolation invariant is preserved in its new home.
- `test_deliver_finalize_status_crash_leaves_run_at_approved` and `test_deliver_finalize_crash_preserves_payroll_roster_attribute`: `deliver()` no longer writes run status at all, so the old `repo.set_status` injection point has no successor inside it. Both retargeted to `deliver()`'s own try/except instead — the crash is injected on `_enqueue_confirmation` (the last write in `deliver()`'s reserve+enqueue transaction), called with an explicit caller-owned `conn=` (matching how `app/routes/runs.py`'s approve route actually invokes it, per `deliver()`'s own "the caller owns the transaction" docstring). The status test now additionally asserts, via `send_guard.outbound_replay_policy(...).has_existing_snapshot`, that the crash rolled back the ENTIRE transaction — no orphaned "reserved but never enqueued" snapshot survives. `exc.payroll_roster` is still attached by `deliver()`'s own try/except (`app/pipeline/delivery.py:172-173`), unchanged.
- `test_deliver_retry_over_sent_completes_alias_write_exactly_once`: the retry-over-sent guard branch itself (`deliver()`'s `sent_message_id is not None` check -> `_complete_sent_confirmation`) is unaffected by Phase 20 — it was always synchronous and still is. Only the FIRST delivery needed a `drain.drain_once()` added to genuinely reach `reconciled` before the retry is exercised.

**Bonus fix (Rule 1 — bug found in-scope while executing):** all 5 tests' `resend.Emails.send` monkeypatch stub accepted only one positional argument (`lambda params: ...`), but `app/email/gateway.py:167` calls it with TWO (`resend.Emails.send(send_params, {"idempotency_key": message_id})`, added when Phase 20 wired the Idempotency-Key). The resulting `TypeError` was silently caught and misclassified as a genuine delivery failure by `classify_pipeline_exception`, masking what these tests actually meant to prove (confirmed via a standalone debug script — the run landed at `needs_operator` / `error_detail: delivery_review:unknown` instead of `reconciled`). Fixed to `lambda *_a, **_kw: {"id": "test-id"}`, matching the currently-passing idiom already used in `tests/test_queue_durability.py:1888`.

### Group 2 — Phase-18 drift: persisted reply + `RESUME_REPLY` job + `drain.drain_once()` (2 tests)

`resume_pipeline` does not self-persist `RunStatus.ERROR` — `app/pipeline/orchestrator.py:857-859`'s except clause only classifies and returns a `PipelineResult`. Terminal persistence is owned exclusively by `app/db/repo/job_settlement.py`'s `settle_pipeline_job` -> `_set_run_error`, reached from the queue-drain path after `app/queue/handlers/resume_reply.py`'s `handle_resume_reply` wraps `resume_pipeline`'s result.

- Both `test_defer_field_regression_write_survives_later_clarify_failure` and `test_round2_clarified_fields_persist_before_run_stages` migrated off the direct `resume_pipeline(run_id, reply)` call. Each now persists the reply as a real inbound row (`repo.insert_inbound_email(..., run_id=run_id)`, from the same business's `contact_email` so `handle_resume_reply`'s `reply_sender_ok` re-authorization passes), enqueues a `RESUME_REPLY` job (`dedup_key=f"resume_reply:{run_id}:{email_id}"`), and calls `drain.drain_once()`. This reaches through the real production chain: `handle_resume_reply`'s AWAITING_REPLY -> RECEIVED CAS, then `resume_pipeline`'s own RECEIVED -> EXTRACTING CAS, then (on the injected failure) `settle_pipeline_job`'s `_set_run_error` (gated on `expected_status=EXTRACTING`, which matches). Both assertions (the earlier `clarified_fields` write surviving the later crash; the run landing at `ERROR`) hold exactly as originally intended, just through the real settlement path instead of an assumed direct write.

### Group 3 — Phase-19 drift: strengthened dedup exercise + `drain.drain_once()` (1 test)

`/webhook/inbound` is now durable-receipt-only — it commits the `inbound_events` row + an identifier-only `INGEST` job and calls `wake.wake()` (a plain `threading.Event.set()` only a running lifespan-owned worker thread observes). A bare `TestClient(app, ...)` with no `with` block never starts that lifespan.

- `test_duplicate_delivery_pipeline_runs_once`'s minimal fix (add a `drain.drain_once()` call, matching the mocked twin `test_duplicate_delivery_pipeline_runs_once_unit`'s already-updated idiom) was insufficient on its own: the two identical-payload POSTs (r1/r2) are fully deduplicated at the `inbound_events` layer (`external_event_id` is a SHA-256 digest of the raw bytes in fixture mode, so the second POST never creates a second event or job at all) — meaning the message_id-level `ON CONFLICT (message_id) DO NOTHING` this test is *named* for would never actually run, an unreachable invariant masquerading as tested. Strengthened: added a THIRD delivery (`r3`) with a different top-level `id` (genuinely different raw bytes -> a genuinely different event, its own `INGEST` job) but the SAME `message_id`, so draining it actually reaches `insert_inbound_email`'s `ON CONFLICT (message_id) DO NOTHING` a second time. Added a `_drain_all()` helper (loops `drain.drain_once()` to `DrainOutcome.EMPTY`) since a single `drain_once()` call claims exactly one job in FIFO order — not necessarily the one the test means to observe, given the first INGEST job itself enqueues a follow-on `RUN_PIPELINE` job on success.

### Falsifying mutations for the two exactly-once claims (T-...-04, required and executed)

- **`test_deliver_retry_over_sent_completes_alias_write_exactly_once`:** temporarily duplicated the `write_aliases_if_safe(...)` call inside `_complete_sent_confirmation` (`app/pipeline/delivery.py:56`). Reran: `assert 2 == 1` — genuine red. Reverted (`git diff` confirmed empty).
- **`test_duplicate_delivery_pipeline_runs_once`:** temporarily removed `ON CONFLICT (message_id) DO NOTHING` from `insert_inbound_email`'s SQL (`app/db/repo/runs.py:90`) AND temporarily removed the `uq_message_id` UNIQUE constraint from `app/db/schema.sql` (the schema-level constraint alone made the query-level clause's removal a no-op — Postgres just raised `UniqueViolation` and rolled back the whole insert, leaving the row count unchanged at 1 regardless; dropping the constraint too was necessary to let a literal second row land). With both mutations in place: reran and observed `got 2` — two `email_messages` rows and two separate payroll runs created (confirmed via the captured orchestrator warnings). Genuine red. Reverted both mutations (`git diff` confirmed empty on both files).

### Comment-hygiene fix (in-scope, self-caught)

The full live-DB suite surfaced one additional failure I introduced mid-session: `tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree` — several of my new comments cited "Phase 20"/"Phase 18"/`T-21-14-04` (a project-internal ticket/phase-reference style this repo's CI-enforced guard explicitly forbids: "Source text must explain the code, not cite the ticket that produced it. Keep the constraint, drop the label."). Rewrote every flagged and stylistically-similar comment to state the architectural constraint directly instead of citing which phase changed it. Guard re-verified green.

### Verification

- `uv run pytest tests/test_atomic_persist.py tests/test_ingest.py -v -rs` → **19 passed, 0 skipped.**
- `uv run pytest tests/test_concurrency_proof.py tests/test_email_epoch_arbiter_integration.py tests/test_atomic_persist.py tests/test_ingest.py -v -rs` → **24 passed, 0 skipped.**
- Full live-DB `uv run pytest tests/ -q -rf`: **13 failed, 1270 passed, 2 skipped** — the 13 failures are exactly `tests/test_queue_durability.py` (plan 21-13's separate scope, not this plan's, per the environment section's out-of-scope carve-out), zero failures elsewhere. The 2 skips are pre-existing, legitimately two-factor-guarded (`test_claim_status.py`'s Wave-1 stub marker, `test_live_llm.py`'s `ALLOW_LIVE_LLM` gate) — unrelated to this plan.
- `uv run pytest tests/ -m "not integration and not live_llm"` (hermetic suite): **1190 passed, 95 deselected** — matches the project's documented hermetic baseline exactly.
- `uv run ruff check tests/test_atomic_persist.py tests/test_ingest.py`: clean (the one line-length violation from a new `with` statement was fixed). `ruff format --check` reports both files as already non-format-clean on the pre-plan `HEAD` (confirmed via `git show HEAD:<file>`) — pre-existing, not CI-enforced (`ci.yml` runs `ruff check` only), left as-is.

## Task Commits

1. **Task 1: A1 + A2 — repair the two CI-visible integration failures** - `fddb918` (fix)
2. **Task 2: Diagnose the eight invisible failures — CHECKPOINT** - `f9a3fb7` (docs), `c258116` (docs — self-check appendix)
3. **Task 3: Fix the eight, per the verdicts** - `69cf0e3` (fix)

## Files Created/Modified

- `tests/test_concurrency_proof.py` — A1: keyword-only `conn` parameter on the `deliver` monkeypatch stub
- `tests/test_email_epoch_arbiter_integration.py` — A2: rewritten to the reserve→settle contract
- `tests/test_atomic_persist.py` — 7 of the 8 CI-invisible tests migrated (5 delivery-queue tests, 2 resume-pipeline tests), plus a stale resend mock fix
- `tests/test_ingest.py` — the 8th CI-invisible test migrated and strengthened; added a `_drain_all()` helper

## Decisions Made

- A2's rewrite exercises the two real production entry points (`reserve_outbound_snapshot`, `update_email_message_sent`) as two explicit steps rather than trying to paraphrase the old upsert behavior through a single call.
- Every repaired or migrated assertion in this plan — not just the two originally CI-visible ones — was falsification-proven: the invariant it claims to prove was temporarily broken, the test was confirmed to red, then the mutation was reverted before any commit.
- The three Task-3 migration groups deliberately use three different techniques (queue-drain for delivery, persisted-reply + queue-drain for resume, strengthened multi-event dedup for ingest) rather than one uniform "just add drain_once()" pattern, because each producer's actual replacement contract differs.
- No production code was changed. The stale `resend.Emails.send` mock fix and the comment-hygiene fix are both test-file-only changes within this plan's declared scope (`tests/test_atomic_persist.py`, `tests/test_ingest.py`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Stale single-arg `resend.Emails.send` test mock across 5 delivery tests**
- **Found during:** Task 3, migrating the 5 Phase-20-drift delivery tests to actually exercise the send step for the first time
- **Issue:** the shared mock lambda accepted only one positional argument, but the real call site (`app/email/gateway.py:167`) passes two (send params + an Idempotency-Key dict, added by Phase 20). The resulting `TypeError` was silently reclassified as a generic delivery failure, sending the run to `needs_operator` instead of `reconciled` — masking the actual test intent.
- **Fix:** changed the stub to `lambda *_a, **_kw: {"id": "test-id"}`, matching the idiom already used by the currently-passing `tests/test_queue_durability.py:1888`.
- **Files modified:** `tests/test_atomic_persist.py`
- **Verification:** all 5 affected tests pass; confirmed via a standalone debug script before applying the fix that this was the actual root cause (not a real production defect — traced to `run.status == 'needs_operator'`, `error_detail: delivery_review:unknown`).
- **Committed in:** `69cf0e3` (Task 3 commit)

**2. [Rule 3 - Blocking] Comment-provenance-guard violation introduced mid-session**
- **Found during:** Task 3's own full-live-DB verification run
- **Issue:** several new test comments/docstrings cited "Phase 20"/"Phase 18"/`T-21-14-04` — patterns this repo's `tests/test_comment_provenance_guard.py` CI gate explicitly forbids (ticket/phase-reference citations instead of stating the constraint directly).
- **Fix:** rewrote every flagged comment (and, proactively, every stylistically-similar "POST-PHASE-XX CONTRACT" header that escaped the guard's exact regex but matched its stated intent) to describe the current architectural constraint without citing which phase produced it.
- **Files modified:** `tests/test_atomic_persist.py`, `tests/test_ingest.py`
- **Verification:** `tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree` passes.
- **Committed in:** `69cf0e3` (Task 3 commit — folded in before the commit, not a separate commit)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking guard violation). Both necessary for the plan's own stated migration to actually work and to keep the repo's existing CI gates green; no scope creep — both changes are confined to the plan's declared test files.

## Issues Encountered

None blocking beyond the two deviations above. The scratch-worktree venv reuse via `UV_PROJECT_ENVIRONMENT` required `uv run --no-sync` (not the plan's example bare `uv run`) to avoid resyncing the shared venv against `47c0af0`'s older lockfile mid-session — verified safe throughout. An early attempt at falsifying the ingest exactly-once claim by only removing the query-level `ON CONFLICT` clause was insufficient (the schema-level `uq_message_id` UNIQUE constraint alone still blocked a second row, just via a raw `UniqueViolation` instead) — the constraint itself had to be temporarily dropped too to get a genuine falsifying red.

## User Setup Required

None.

## Next Phase Readiness

Plan 21-14 is complete. `tests/test_concurrency_proof.py`, `tests/test_email_epoch_arbiter_integration.py`, `tests/test_atomic_persist.py`, and `tests/test_ingest.py` are all green with 0 skips against a live database. PROOF-04 and PROOF-05 are satisfied within this plan's declared scope. The 13 `tests/test_queue_durability.py` failures remain for plan 21-13 to close separately, as scoped — nothing in this plan touches or depends on them.

---
*Phase: 21-durability-proofs-ops-view*
*Completed: 2026-07-20*

## Self-Check: PASSED

- FOUND: `tests/test_concurrency_proof.py`
- FOUND: `tests/test_email_epoch_arbiter_integration.py`
- FOUND: `tests/test_atomic_persist.py`
- FOUND: `tests/test_ingest.py`
- FOUND: `.planning/phases/21-durability-proofs-ops-view/21-14-SUMMARY.md`
- FOUND: commit `fddb918` (task 1)
- FOUND: commit `f9a3fb7` (task 2 diagnosis)
- FOUND: commit `c258116` (task 2 self-check appendix)
- FOUND: commit `69cf0e3` (task 3 fixes)
