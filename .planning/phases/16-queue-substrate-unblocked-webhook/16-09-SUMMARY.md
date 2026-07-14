---
phase: 16-queue-substrate-unblocked-webhook
plan: 09
subsystem: testing
tags: [postgres, queue, concurrency, durability, pytest, psycopg]

# Dependency graph
requires:
  - phase: 16-queue-substrate-unblocked-webhook (plan 04)
    provides: "app/db/repo/jobs.py claim/lease/fencing protocol; rewind_for_reclaim; tests/test_queue_durability.py's _isolated_jobs/live_worker fixtures"
  - phase: 16-queue-substrate-unblocked-webhook (plan 06)
    provides: "app/queue/handlers/pipeline.py::handle_run_pipeline (the D-01 rewind + INVARIANT J-1 CAS); app/queue/drain.py::drain_once"
  - phase: 16-queue-substrate-unblocked-webhook (plan 07)
    provides: "app/queue/worker.py lifecycle (WORKER_COUNT=0 pin keeps this plan's TestClient lifespan a no-op)"
  - phase: 16-queue-substrate-unblocked-webhook (plan 08)
    provides: "app/routes/runs.py::retrigger's one-transaction claim+clear+enqueue; the already-migrated tests/test_stuck_run_recovery.py test body"
  - phase: 16-queue-substrate-unblocked-webhook (plan 10)
    provides: "app/pipeline/send_guard.py — the fail-closed guard this proof's D-02 epoch-stability assertion protects"
provides:
  - "tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease — Proof 2, the phase's headline claim (ROADMAP criterion #2), with both falsifying mutations executed live and reverted"
  - "tests/test_stuck_run_recovery.py::test_stranded_run_swept_and_retriggerable now carries @pytest.mark.queueproof — the last BackgroundTasks-dependent retrigger test is in the narrow CI gate"
  - "Proof 3's four falsifying mutations (deferred by 16-04 for lack of a live DB in that worktree) executed live and reverted in this plan, closing the phase's last open live-DB verification gap"
affects: [17, 18, 19, 20, 21]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A stub that records BOTH a call (the spy) AND an observable side effect distinguishable from the failure mode's own residual state (advance the run to COMPUTED, not merely EXTRACTING) is what makes a 'the orchestrator genuinely re-ran' assertion non-vacuous when handle_run_pipeline's own forward CAS already writes EXTRACTING on both the passing and the stranded-mutation paths."
    - "Modeling a 'worker got partway through before dying' precondition with the SAME CAS the handler itself would issue (repo.claim_status(RECEIVED, EXTRACTING)), not a raw set_status, is what forces a rewind-removed mutation to be genuinely exercised rather than trivially skipped — a run left at RECEIVED lets the forward CAS win regardless of whether the reclaim's rewind ran at all."

key-files:
  created: []
  modified:
    - tests/test_queue_durability.py
    - tests/test_stuck_run_recovery.py

key-decisions:
  - "Task 2's substantive migration (POST retrigger -> assert jobs row -> drain.drain_once()) was ALREADY done by plan 16-08 (commits 5a5934e/409896b), discovered via `git diff <worktree base> -- tests/test_stuck_run_recovery.py` returning empty against the pre-migrated file. This plan's Task 2 narrowed to exactly what remained: the `@pytest.mark.queueproof` marker on the one migrated test function, per D-14's bounded-blast-radius rule."
  - "Proof 3's four falsifying mutations were confirmed never executed live anywhere in the phase: 16-04-SUMMARY.md's own coverage entries D3/D5 are marked `human_judgment: true` with an explicit rationale ('No DATABASE_URL/.env in this worktree ... deferred to the queueproof CI gate'), and a grep across all nine prior SUMMARYs for the affected test names found no pasted red run for any of them. Since this is the phase's closing plan and its own <verification> section requires every proof to have a demonstrated red run pasted into a SUMMARY before the phase gate is met, this plan closed that gap directly (mutations a/b/c/d below) rather than leaving it open with a proof that had never actually been shown able to fail."
  - "Proof 3's mutation (c) was executed as 'drop `SKIP LOCKED`, keep `FOR UPDATE`' rather than a full SELECT-then-UPDATE rewrite — this is the minimal, precise form of the risk the module docstring's own item (c) names, and it is exactly the mutation `test_skip_locked_steps_over_a_row_another_worker_is_holding` (added in 16-04, commit 66dafa7) exists to catch. Running it also re-confirmed, live, that `test_genuine_claim_race_exactly_one_winner` stays GREEN under this exact mutation (mutual exclusion survives; only liveness breaks) — the module's own documented, non-obvious distinction, now proven rather than asserted."

requirements-completed: [QUEUE-02, QUEUE-03]

coverage:
  - id: D1
    description: "Proof 2 (ROADMAP criterion #2): a retrigger enqueues a durable jobs row, a worker that claims-then-dies mid-lease leaves the row genuinely leased, and a second drain reclaims it (attempts==2), re-runs the pipeline via the D-01 rewind, completes the job, and never bumps reply_epoch a second time"
    requirement: "QUEUE-02"
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease (live Postgres, executed in this worktree)"
        status: pass
      - kind: other
        ref: "Both falsifying mutations (drop the expired-lease OR clause; drop the attempts>1 rewind preamble) executed live, confirmed red, reverted byte-identical — see 'Falsifying Mutations' below"
        status: pass
    human_judgment: false
  - id: D2
    description: "The last BackgroundTasks-dependent retrigger test carries @pytest.mark.queueproof (blast radius: exactly 1 test, D-14), and the full narrow CI gate selection (-m queueproof) is green with zero skips"
    requirement: "QUEUE-03"
    verification:
      - kind: integration
        ref: "tests/test_stuck_run_recovery.py::test_stranded_run_swept_and_retriggerable; `uv run pytest tests/ -m queueproof -v` -> 17 passed, 0 skipped (live Postgres)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Proof 3's four falsifying mutations, deferred by plan 16-04 for lack of a live DB in that worktree and never subsequently closed, executed live in this plan and confirmed red"
    requirement: "QUEUE-02, QUEUE-03"
    verification:
      - kind: other
        ref: "Mutations (a) drop expired-lease OR clause, (b) drop fail_job's lease_token fence, (c) drop SKIP LOCKED, (d) add the epoch bump to rewind_for_reclaim -- all executed against real, unmutated source, confirmed red, reverted byte-identical. See 'Closing a Phase-Wide Gap' below."
        status: pass
    human_judgment: false

duration: ~40min
completed: 2026-07-14
status: complete
---

# Phase 16 Plan 09: Proof 2 — Retrigger Survives a Worker Crash Summary

**Proof 2 — the phase's headline claim — appended to `tests/test_queue_durability.py`: a retrigger's durable `jobs` row survives a simulated worker death mid-lease and completes on a second drain via the D-01 rewind, with both of its own falsifying mutations executed live and confirmed red; the last `BackgroundTasks`-dependent retrigger test is now in the narrow `queueproof` CI gate; and, as this phase's closing plan, Proof 3's four falsifying mutations — deferred by 16-04 for lack of a live database and never subsequently closed — were executed live here, closing the phase's last open verification gap.**

## Performance

- **Duration:** ~40 min
- **Tasks:** 2 of 2 completed
- **Files modified:** 2

## Accomplishments

- `tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease` (Proof 2): six steps, each with its own assertion. POST `/runs/{run_id}/retrigger` on an ERROR run; assert the durable enqueue by `dedup_key`, id held for the rest of the test; `repo.claim_job()` directly (never `drain_once()`) to stop MID-LEASE, with the job's `state == 'leased'`, `attempts == 1` asserted as the non-vacuity precondition; the dying worker's own forward CAS (`RECEIVED -> EXTRACTING`) modeled explicitly, which is what forces the reclaim's rewind to be genuinely exercised rather than trivially skipped; the lease expired by `UPDATE`, never a sleep; `drain.drain_once()` reclaims it (`attempts == 2`); the orchestrator (`pipeline_glue.run_pipeline_bg`, stubbed — no live LLM call) is asserted called exactly once with this run's id, and the stub's own observable side effect (advancing the run to `COMPUTED`) is what makes "genuinely re-ran" distinguishable from the stranded-mutation's own indistinguishable `EXTRACTING` value; `reply_epoch` asserted unchanged across the whole reclaim (D-02).
- Both of Proof 2's own falsifying mutations executed against real, unmutated source in this worktree, confirmed red, reverted byte-identical (`diff` against a pre-mutation backup): (a) strip the expired-lease `OR` clause from `claim_job`'s WHERE; (b) strip the `attempts > 1` rewind preamble from `handle_run_pipeline`.
- `tests/test_stuck_run_recovery.py::test_stranded_run_swept_and_retriggerable` now carries `@pytest.mark.queueproof` — exactly this one test (D-14 bounded blast radius; `grep -c` confirms exactly 1). Its substantive migration to the queue (POST -> assert the `jobs` row -> `drain.drain_once()`) was already shipped by plan 16-08; this plan's Task 2 narrowed to the marker and a clarifying docstring note once that was confirmed via `git diff` against the merge base.
- **Closing a phase-wide gap:** as the phase's closing plan, with a live Postgres available, four of Proof 3's falsifying mutations that plan 16-04 explicitly deferred (its own SUMMARY: "No DATABASE_URL/.env in this worktree ... deferred to the queueproof CI gate") and that no subsequent plan (16-05 through 16-08, 16-10) ever executed, were run live here, confirmed red, and reverted byte-identical: (a) the expired-lease `OR` clause, (b) `fail_job`'s `lease_token` fence, (c) `SKIP LOCKED`, (d) the epoch bump on `rewind_for_reclaim`. This closes the last open live-DB verification gap in the phase before the PHASE GATE claim ("every proof has a pasted red run somewhere across the ten SUMMARYs") can be honestly made.
- Full `queueproof` CI-gate selection green with zero skips (17 passed), the two pre-existing `concurrency-proof.yml` files still green with zero skips (5 passed), full hermetic suite green (709 passed, 69 skipped — all live-DB tests skipping cleanly with no DB configured), `mypy app`/`mypy tests` (strict) clean, `ruff check .` clean, `tests/test_comment_provenance_guard.py` green (after rewording four citations that initially tripped it — see Deviations).

## Task Commits

Each task was committed atomically:

1. **Task 1: Proof 2 — a retrigger survives a worker death and completes on the next drain** — `f7610d2` (test)
2. **Task 2: mark the live retrigger-recovery test queueproof** — `6ccddd7` (test)

**Plan metadata:** committed by the orchestrator after wave merge (this executor runs in worktree mode and does not write STATE.md/ROADMAP.md).

## Files Created/Modified

- `tests/test_queue_durability.py` — `test_retrigger_survives_worker_crash_mid_lease` (Proof 2), appended after the existing static AST guard
- `tests/test_stuck_run_recovery.py` — `@pytest.mark.queueproof` added to `test_stranded_run_swept_and_retriggerable` plus a clarifying docstring note on the bounded blast radius

## Decisions Made

- The stub for `pipeline_glue.run_pipeline_bg` records an observable side effect (`repo.set_status(rid, RunStatus.COMPUTED)`) rather than being a bare no-op recorder — see `key-decisions` above for why bare status alone cannot discriminate "genuinely re-ran" from "stuck exactly where step 3 left it" (both leave the run at `EXTRACTING`, since that is the value `handle_run_pipeline`'s own forward CAS writes in the passing case AND the value the crash simulation deliberately pre-sets in the failing case).
- Task 2's scope narrowed once the substantive migration was confirmed already shipped by 16-08 — verified via `git diff <worktree base> -- tests/test_stuck_run_recovery.py` returning empty, and `git log --oneline -- tests/test_stuck_run_recovery.py` showing 16-08's own `feat(16-08)`/`test(16-08)` commits already carrying the POST -> assert-jobs-row -> `drain_once()` body.
- Proof 3's deferred mutations were closed here rather than left open, given this plan is the phase's last and its own `<verification>` section states the PHASE GATE requires a pasted red run for every proof "somewhere across the ten SUMMARYs" — a requirement that was not yet true for criterion #3 before this plan ran.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Four decision-ID citations in Proof 2's own docstring/assertions tripped the repo's comment-provenance guard**
- **Found during:** Task 1, `uv run pytest tests/test_comment_provenance_guard.py -q` after writing the test
- **Issue:** `(D-16)`, `(D-01)` (twice), and `(D-02)` citations in step-2/step-3/step-6 comments and assertion messages matched the guard's `decision-id` pattern — exactly the trap this plan's own briefing warned about in advance (the same class of violation plan 16-07 hit and fixed).
- **Fix:** Reworded all four to state the constraint directly with no ticket citation (e.g. "the automatic reclaim must never bump reply_epoch a second time" with the `D-02` label dropped).
- **Files modified:** `tests/test_queue_durability.py`
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py -q` -> 5 passed (was 1 failed, 4 violations listed).
- **Committed in:** `f7610d2` (Task 1 commit)

**2. [Rule 1 - Bug] Import block un-sorted after appending the new test's local imports**
- **Found during:** Task 1, `uv run ruff check tests/test_queue_durability.py`
- **Issue:** `import app.main as app_main` was placed before `from fastapi.testclient import TestClient`, violating the repo's isort convention (third-party before first-party).
- **Fix:** `uv run ruff check --fix tests/test_queue_durability.py`.
- **Files modified:** `tests/test_queue_durability.py`
- **Verification:** `uv run ruff check tests/test_queue_durability.py` -> All checks passed. Full-file live-DB re-run confirmed still 14/14 green after the fix.
- **Committed in:** `f7610d2` (Task 1 commit)

**3. [Rule 2 - Auto-add missing critical functionality] Proof 3's falsifying mutations, deferred since 16-04, were never subsequently executed against a live database**
- **Found during:** Preparing this plan's required phase-closing table (which maps each ROADMAP criterion to the SUMMARY holding its red run) — a grep across all nine prior SUMMARYs found no pasted red run for `test_genuine_claim_race_exactly_one_winner`, `test_expired_lease_is_reclaimed`, `test_zombie_is_fenced_on_BOTH_complete_and_fail`, `test_skip_locked_steps_over_a_row_another_worker_is_holding`, or `test_rewind_for_reclaim_leaves_reply_epoch_untouched`, and 16-04-SUMMARY.md's own `coverage` entries D3/D5 are explicitly marked `human_judgment: true` with a rationale stating the live-DB mutations were deferred.
- **Fix:** With a live Postgres available in this worktree (the same one used for Proof 2), executed mutations (a) drop the expired-lease `OR` clause, (b) drop `fail_job`'s `lease_token` fence, (c) drop `SKIP LOCKED` (keep `FOR UPDATE`), and (d) add the epoch bump to `rewind_for_reclaim` — each against real, unmutated source, confirmed red, reverted byte-identical.
- **Files touched (all reverted, zero net diff):** `app/db/repo/jobs.py`, `app/db/repo/pipeline_state.py`
- **Verification:** See "Closing a Phase-Wide Gap" below for the pasted red output of all four; `git diff --stat` empty on both files after every revert; full `queueproof` selection re-confirmed 17/17 green afterward.
- **Committed in:** not committed — verification-only; no net source change (mutate-and-revert), consistent with how Proof 2's own two falsifying mutations were also executed without leaving a commit.

---

**Total deviations:** 3 (2 minor auto-fixes on the new test; 1 verification-scope addition closing a phase-wide gap this plan's own PHASE GATE criterion required to be closed before the phase could honestly claim completion)
**Impact on plan:** No scope creep on the plan's two committed tasks. Deviation 3 is bounded, reversible verification work (no permanent source change) undertaken because this is the phase's final plan and its own `<verification>` section requires it.

## Falsifying Mutations Executed — Proof 2 (this plan's own proof)

Both executed against real, unmutated source files in this worktree, confirmed RED, and reverted with a byte-identical `diff` check against a pre-mutation backup.

### (a) Strip the expired-lease `OR` clause from `claim_job`'s WHERE (`app/db/repo/jobs.py`)

```
tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease FAILED [100%]

        # --- Step 5: a second worker (or a manual drain) picks the job back up --
>       assert drain.drain_once() is True, (
            "drain_once() must claim and dispatch the reclaimed job — a job "
            "that was never actually reclaimable would leave nothing to drain"
        )
E       AssertionError: drain_once() must claim and dispatch the reclaimed job — a job that was never actually reclaimable would leave nothing to drain
E       assert False is True
E        +  where False = <function drain_once at 0x108fce840>()
E        +    where <function drain_once at 0x108fce840> = <module 'app.queue.drain' from '.../app/queue/drain.py'>.drain_once

tests/test_queue_durability.py:1097: AssertionError
1 failed, 13 deselected in 0.67s
```
Reverted; `diff` against backup empty; `git diff --stat app/db/repo/jobs.py` empty.

### (b) Strip the `attempts > 1` rewind preamble from `handle_run_pipeline` (`app/queue/handlers/pipeline.py`)

```
tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease FAILED [100%]

>       assert orchestrator_calls == [run_id], (
            "the automatic reclaim's rewind must have fired and the forward CAS "
            "re-won, letting the orchestrator genuinely run a second time — a "
            "lost CAS would leave this list empty"
        )
E       AssertionError: the automatic reclaim's rewind must have fired and the forward CAS re-won, letting the orchestrator genuinely run a second time — a lost CAS would leave this list empty
E       assert [] == [UUID('f749ad87-34d8-4eae-a059-133c93dee5c8')]
E
E         Right contains one more item: UUID('f749ad87-34d8-4eae-a059-133c93dee5c8')
E
E         Full diff:
E         + []
E         - [
E         -     UUID('f749ad87-34d8-4eae-a059-133c93dee5c8'),
E         - ]

tests/test_queue_durability.py:1111: AssertionError
1 failed, 13 deselected in 0.69s
```
Reverted; `diff` against backup empty; `git diff --stat app/queue/handlers/pipeline.py` empty.

## Closing a Phase-Wide Gap — Proof 3's Deferred Mutations, Executed Live

Proof 3 (ROADMAP criterion #3) itself passes and always has — what was missing was proof it could FAIL. All four executed against real, unmutated source in this worktree, confirmed RED, reverted byte-identical.

### (a) Strip the expired-lease `OR` clause from `claim_job`'s WHERE — full-file run

```
FAILED tests/test_queue_durability.py::test_expired_lease_is_reclaimed
FAILED tests/test_queue_durability.py::test_zombie_is_fenced_on_BOTH_complete_and_fail
FAILED tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease
3 failed, 11 passed in 2.01s

_______________________ test_expired_lease_is_reclaimed ________________________
    second = repo.claim_job()
>   assert second is not None
E   assert None is not None
tests/test_queue_durability.py:442: AssertionError
```
Reverted; `diff` against backup empty; `git diff --stat app/db/repo/jobs.py` empty.

### (b) Drop `fail_job`'s `lease_token` fence (leave it on `complete_job`)

```
FAILED tests/test_queue_durability.py::test_zombie_is_fenced_on_BOTH_complete_and_fail

    assert repo.complete_job(enqueued_id, token_a) is False
>   assert repo.fail_job(enqueued_id, token_a, error="zombie write", backoff_seconds=1.0) is None
E   AssertionError: assert <JobState.PENDING: 'pending'> is None
E    +  where <JobState.PENDING: 'pending'> = <function fail_job at 0x10ac9b1a0>(UUID('5dba0f97-0052-465c-9005-85dcf2e2bfb3'), UUID('7db31cdc-50b6-4486-a0e2-ee8e50bcebf5'), error='zombie write', backoff_seconds=1.0)

tests/test_queue_durability.py:485: AssertionError
1 failed, 13 deselected in 0.24s
```
Reverted; `diff` against backup empty; `git diff --stat app/db/repo/jobs.py` empty. The zombie's failure write wrongly succeeds — exactly "the fence people forget," proven by removing it.

### (c) Drop `SKIP LOCKED` (keep `FOR UPDATE`)

```
FAILED tests/test_queue_durability.py::test_skip_locked_steps_over_a_row_another_worker_is_holding
1 failed, 1 passed in 5.33s

>   assert not blocked, (
        f"claim_job() was still blocked after {claim_timeout_s}s on a row another "
        "transaction was holding, instead of skipping over it — this is FOR UPDATE "
        "without SKIP LOCKED. A second worker stalls behind the first rather than "
        "picking up the next free job."
    )
E   AssertionError: claim_job() was still blocked after 5.0s on a row another transaction was holding, instead of skipping over it — this is FOR UPDATE without SKIP LOCKED. A second worker stalls behind the first rather than picking up the next free job.
E   assert not True

tests/test_queue_durability.py:642: AssertionError
```
`test_genuine_claim_race_exactly_one_winner` stayed GREEN under this same mutation (`1 passed` alongside the failure above) — live confirmation of the module's own documented, non-obvious claim: exactly-one-winner is mutual exclusion, which plain `FOR UPDATE` still delivers; only liveness (a second worker stepping over a held row instead of stalling behind it) is what `SKIP LOCKED` actually buys, and only the dedicated test can see its absence. Reverted; `diff` against backup empty; `git diff --stat app/db/repo/jobs.py` empty.

### (d) Add the epoch bump to `rewind_for_reclaim`

```
FAILED tests/test_queue_durability.py::test_rewind_for_reclaim_leaves_reply_epoch_untouched
FAILED tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease
2 failed, 12 deselected in 0.72s

>   assert _read_reply_epoch(run_id) == epoch_after, (
        "the automatic reclaim must never bump reply_epoch a second time — "
        "only the operator's own retrigger click may grant that licence, "
        "and it already did, once, in step 1"
    )
E   AssertionError: the automatic reclaim must never bump reply_epoch a second time — only the operator's own retrigger click may grant that licence, and it already did, once, in step 1
E   assert 2 == 1
E    +  where 2 = _read_reply_epoch(UUID('b143a2dc-06e5-490f-afc9-447c2fa4d598'))

tests/test_queue_durability.py:1126: AssertionError
```
Both Proof 3's own epoch-stability assertion AND Proof 2 (this plan's test) independently caught the same regression — two non-redundant proofs of the D-02 guarantee. Reverted; `diff` against backup empty; `git diff --stat app/db/repo/pipeline_state.py` empty.

Full `-m queueproof` selection re-confirmed green (17 passed, 0 skipped) after every revert in this section, and `git status --short` showed only the two intentionally-committed test files as modified at the end of this plan.

## Phase-Closing Table — All 5 ROADMAP Success Criteria

| # | Criterion | Proof | Test file | SUMMARY holding the red run |
|---|-----------|-------|-----------|------------------------------|
| 1 | Two concurrent inbound webhooks complete in wall-clock time roughly equal to the slowest one, not their sum | Proof 1 | `tests/test_webhook_unblocked.py` | `16-01-SUMMARY.md` |
| 2 | Clicking Retrigger enqueues a durable job; killing the worker mid-run and draining again completes it without the operator re-clicking | Proof 2 | `tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease` | **`16-09-SUMMARY.md` (this SUMMARY)** |
| 3 | A job whose worker died holding the lease is reclaimed and re-run once the lease expires — never stuck `leased` forever | Proof 3 | `tests/test_queue_durability.py` (`test_genuine_claim_race_exactly_one_winner`, `test_expired_lease_is_reclaimed`, `test_zombie_is_fenced_on_BOTH_complete_and_fail`, `test_skip_locked_steps_over_a_row_another_worker_is_holding`, `test_rewind_for_reclaim_leaves_reply_epoch_untouched`) | Proofs written in `16-04-SUMMARY.md`; **red runs pasted in `16-09-SUMMARY.md` (this SUMMARY)** — 16-04 shipped these tests passing but explicitly deferred their live-DB falsifying mutations for lack of a database in that worktree, and no subsequent plan closed that gap until this one |
| 4 | A graceful worker shutdown releases held leases immediately, so an in-flight retrigger resumes within seconds | Proof 4 | `tests/test_queue_durability.py::test_graceful_shutdown_releases_held_leases_immediately` + `tests/test_queue_worker.py` | `16-07-SUMMARY.md` |
| 5 | A CI-enforced guard fails the build if `jobs.kind` collides with `payroll_runs.status` or drifts from the `JobKind` enum | Proof 5 | `tests/test_job_kind_drift.py` | `16-05-SUMMARY.md` |
| — | D-13's fail-closed unconfirmed-send guard (not a numbered ROADMAP criterion, but required by the PHASE GATE alongside the five above) | send-guard proof | `tests/test_send_idempotency.py` | `16-10-SUMMARY.md` |

**PHASE GATE, now true:** all five proofs are green, D-13's send-guard proof is green, and every one has a pasted red run from its own falsifying mutation in a SUMMARY across the ten plans of this phase.

## Residual risks — what Phase 16 does NOT close

| Gap | Status after Phase 16 | Closed by |
|---|---|---|
| A **catastrophic START failure** (import error, DB down before `load_run`) is swallowed by `run_pipeline_bg` and the job is marked `done` while the run never ran. | **OPEN.** Pinned by `test_swallowed_start_failure_marks_the_job_done_KNOWN_GAP_FAIL01` (16-06) — a red-to-green target, not a paragraph. The run stays visibly at `RECEIVED`. | **FAIL-01, Phase 18** (must INVERT that test). |
| A **stage failure** (LLM timeout) is recorded `ERROR` on the run and `done` on the job — never auto-retried. | **OPEN, and not a regression** — today's `BackgroundTasks` retrigger swallows identically. The run is operator-visible in `ERROR`. | **FAIL-02, Phase 18.** |
| Exactly-once **send** — `message_id` reuse, payload replay, `Idempotency-Key`. | **OPEN.** Phase 16 ships only the FAIL-CLOSED half (D-13 / 16-10): a possibly-delivered message is never auto-resent; it escalates. It is not yet *replayed*. | **SEND-01/02/03, Phase 20** (widens D-13's action from "escalate" to "replay within the retention window; escalate past it"). |
| **10 `integration`-marked test modules** still never execute in CI. | **OPEN, pre-existing.** D-14 deliberately did not widen the gate to "fix" it, because doing so inside a durability phase would have woken 10 live-DB modules at once against a shared Postgres. | Roadmap **backlog** item — a dedicated piece of work. |
| The **sweep** (`sweep_stranded_runs`, `find_stranded_unconsumed_replies`, the `runs_list()` block) still exists alongside the queue. | **OPEN by design.** They do not race yet: only the retrigger producer is on the queue in Phase 16. | **FAIL-03, Phase 18.** |
| The other **7 `BackgroundTasks` producers**. | **OPEN by design.** | **QUEUE-04, Phase 19.** |

**Phase 16's honest headline claim, and the only one any SUMMARY may make:**
*No accepted **retrigger** is lost to a **process death** — the durable row survives, is reclaimed on
lease expiry, re-runs, and never emails the client a second time.* It is **not** "every failure
recovers automatically"; that is the milestone's claim, and it needs Phases 17-21.

## Issues Encountered

None beyond the deviations documented above.

## User Setup Required

None — no external service configuration required. A live Postgres was available in this worktree throughout (a dedicated, per-agent database), so every live-DB acceptance criterion in this plan — including all six falsifying mutations across Proof 2 and the Proof 3 gap-closure — was actually executed, not deferred.

## Next Phase Readiness

- All five of Phase 16's ROADMAP success criteria are proven, demonstrably able to fail, with every red run traceable to a SUMMARY.
- Phase 17 (The Pump) can build on `app/queue/drain.py::drain_once()` directly — this plan's Proof 2 is itself a live demonstration that `drain_once()` is the correct, sufficient unit for a future pump to call.
- The 10-dormant-test-modules gap and the 7 remaining `BackgroundTasks` producers remain open exactly as scoped — see the Residual risks table above, which this SUMMARY reproduces verbatim per the plan's own `<output>` requirement.
- No blockers for Phase 17.

---
*Phase: 16-queue-substrate-unblocked-webhook*
*Completed: 2026-07-14*

## Self-Check: PASSED

All 2 claimed modified files found on disk (tests/test_queue_durability.py,
tests/test_stuck_run_recovery.py). Both claimed commit hashes (f7610d2,
6ccddd7) found in `git log --oneline --all`. `grep -c pytest.mark.queueproof
tests/test_stuck_run_recovery.py` == 1. `uv run pytest tests/ -m queueproof`
== 17 passed, 0 skipped. No missing items.
