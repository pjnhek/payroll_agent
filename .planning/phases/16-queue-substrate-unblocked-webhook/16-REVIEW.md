---
status: findings-open
phase: 16-queue-substrate-unblocked-webhook
reviewer: codex-cli 0.144.0 (external, cross-AI)
scope: git diff phase16-base..HEAD -- app/ tests/  (45 files, +6414/-246)
date: 2026-07-14
findings_total: 6
findings_fixed: 2
findings_open: 4
---

# Phase 16 — Cross-AI Code Review (Codex)

Two passes were run against the **merged** tree (not any single worktree — several of
this phase's bugs only exist where two plans meet):

1. `codex exec review --base phase16-base` — Codex's own tuned review.
2. `codex exec` with a custom money-path prompt — claim/fence protocol, the double-send
   window, lost-run CAS collisions, worker lifecycle, and vacuous proofs.

## What Codex explicitly validated

These were the two things most at risk, and both cleared review:

- **The claim protocol is sound.** "`claim_job()`'s single-statement UPDATE is sound for
  claim mutual exclusion. The subquery locks the selected row until the statement
  transaction commits; a concurrent claimant cannot reclaim it 'mid-claim.' The missing
  outer state predicate is safe because the subquery's row lock is held through the
  update."
- **The send guard is correctly placed.** "Both current real provider call sites pass
  `assert_no_unconfirmed_send`: clarification at `clarification.py:326-332`, delivery at
  `delivery.py:116-128`. Retrigger reaches those paths through the queued pipeline.
  Record-only branches do not call the provider." No path reaches a send without the guard.

---

## FIXED (commit 3679df0)

### F-1 — Lost wakeup delays a queued job by the full poll interval. `app/queue/worker.py:179-184`
**Severity:** Medium (latency, not correctness — but operator-visible)

The poll loop cleared the wake event *after* draining. A producer that commits its job and
calls `wake()` in the window between `drain_once()` reporting "no work" and the trailing
`clear()` had its signal erased; the worker then slept the full `queue_poll_seconds`
(default 20s) with a claimable job already in the table. Not lost — the next poll finds it
— but the operator clicks Retrigger and watches nothing happen for 20 seconds.

The loop's own docstring already documented this race **for a stop request** and closed it
with a `stop_evt` recheck. A queued job loses the identical race and had no guard.

**Fix:** clear *before* the drain. Safe precisely because a producer commits before it
wakes, so any signal arriving during a drain refers to work the next drain can already see.
Regression test `test_a_wake_arriving_during_the_drain_is_not_erased` asserts a wall-clock
bound; against the old ordering it fails, having slept through a 30s poll.

### F-2 — Vacuous fence assertion. `tests/test_repo_jobs_sql.py:104`
**Severity:** Medium (false confidence)

`assert "lease_token = " in complete_sql` was meant to be a tripwire for the double-fence
mutation. But `complete_job` also does `SET ... lease_token = NULL` to release the lease —
so the substring is present **with the entire WHERE fence deleted**. It asserted the
RELEASE and called it the FENCE. Demonstrated against mutated source: old assertion still
`True`, new one red.

**Fix:** split on `WHERE` and match the fence itself. (The live zombie proof did catch this
mutation independently, so real coverage existed — the tripwire was false confidence sitting
on top of it, which is worse than no tripwire.)

---

## OPEN — require a decision

### F-3 — TOCTOU: two concurrent workers can double-send. `send_guard.py` + `delivery.py:185-203`
**Severity:** High (catastrophic impact, very low probability)

`assert_no_unconfirmed_send` is a **read**. The reservation that follows is
`insert_email_message`, which is `ON CONFLICT (run_id, purpose, round, epoch) DO UPDATE` —
an **upsert**. It does not raise and does not fence. So between the check and the provider
call there is nothing serializing two workers:

1. Workers A and B both execute the same run (possible once a lease expires mid-pipeline).
2. Both call `assert_no_unconfirmed_send`; both see no reserved row; both proceed.
3. A reserves and calls the provider.
4. B's reserve **upserts over A's row** — no error — and B calls the provider too.
5. **Two payroll emails reach the client.**

**Reachability is much narrower than it first appears.** `lease_seconds = 900` (15 min). In
the ordinary stall, A hangs inside the LLM call — which is *before* delivery's guard. B
reclaims, runs the pipeline, sends, marks `sent`. A unstalls, reaches `deliver()`, and its
**Step-1 proven-sent guard** sees B's `sent` row and returns without sending. Safe. For a
real double-send, A must stall >15 min *after* passing its guard read but *before* its
reservation commits — a window two adjacent DB writes wide.

**But note the direction of travel:** before Phase 16 there was no reclaim, therefore no
concurrent execution. This phase *introduced* the vector that 16-10 was written to close,
and closed only the sequential-after-crash half of it. For a system whose entire claim is
"never guesses on a money-moving action," a known TOCTOU on the send path is a defect
regardless of probability.

**Proposed fix (small):** make the reservation *reserve-or-lose*. Use
`ON CONFLICT ... DO NOTHING RETURNING id` for the reserve step; a writer that gets no row
back has lost the race, and raises `UnconfirmedSendError` (fail-closed, matching existing
semantics). Only the winner ever reaches `send_outbound`. This is one SQL clause plus a
branch, but it sits on the money path and deserves its own plan + live-DB proof.

### F-4 — A claimed job can be marked done without the pipeline running. `app/queue/handlers/pipeline.py:130-144`
**Severity:** High (lost payroll run)

`run_pipeline_bg()` catches a catastrophic start failure (orchestrator import error, DB
down) and returns *normally* rather than raising. `drain_once()` then calls
`complete_job()`. The job disappears as successful, the run strands at `EXTRACTING`, and no
worker ever retries it.

**This is already known and honestly disclosed** — `test_swallowed_start_failure_marks_the_job_done_KNOWN_GAP_FAIL01`
pins it, and its docstring says: *"This test PINS a KNOWN GAP; it does not endorse it. A
future fix … must INVERT this assertion, never delete this test — it is that fix's
red-to-green target."* That is the right instinct. But the phase currently ships with a
green suite that asserts a catastrophic job-loss behavior is correct.

**Proposed fix:** the broad swallow in `run_pipeline_bg` exists so a *FastAPI BackgroundTask*
can't crash the process that scheduled it. Now that the pipeline runs on the **queue**, the
handler calls it synchronously in a worker thread that already has its own error boundary —
so the swallow is no longer load-bearing on this path. Let the failure propagate, let
`drain` mark the job `failed`, and let the queue retry it up to `max_attempts`. That is what
a durable queue is *for*. Flip the KNOWN_GAP assertion red-to-green.

### F-5 — Lease fencing does not fence side effects (architectural). `drain.py:80-110`, `handlers/pipeline.py:116-144`
**Severity:** Informational / design

An expired lease (or a `worker.stop()` release) lets worker B reclaim while worker A is
still inside `dispatch.handle()`. A's eventual *completion write* is fenced by
`lease_token` — but A's *pipeline execution* is not. The system therefore guarantees
**at-most-one valid completion write, not at-most-one execution or outbound side effect.**

This is inherent to at-least-once lease queues and the code base already knows it (16-10's
module docstring states it explicitly). F-3 is its concrete money consequence. Recording it
so the guarantee is stated honestly rather than assumed away.

### F-6 — Shutdown can miss a newly claimed lease. `worker.py:220-231`, `drain.py:80-86`
**Severity:** Medium

A worker returns from `claim_job()` holding a lease but is descheduled before
`_held_tokens.add(...)`. Shutdown then snapshots `drain.held_tokens()`, sees nothing, and
does not release that lease. The app finishes shutting down with a live lease outstanding;
it later expires and permits a reclaim (→ the F-5 overlap window).

**Proposed fix:** record the token as held *inside* the same critical section that claims
it, so a claim can never be visible in the DB but invisible to `held_tokens()`.

---

## Test-proof issues raised

- **`test_repo_jobs_sql.py:104`** — vacuous. **FIXED** (F-2).
- **`test_queue_drain.py:199-242`** — not a false proof; it deliberately pins the F-4 lost-run
  gap. Correctly labelled, but the gap itself is open.
- **`test_queue_drain.py:572-619`** — the static CAS scan only covers direct status calls under
  `app/queue/`. It cannot prove the called orchestrator actually runs, or that its failures
  preserve the job. F-4 is exactly that blind spot.

## Verification independently performed by the orchestrator

Every falsifying mutation below was executed against a real Postgres 16 and confirmed to
turn its proof RED (16-04 had deferred six of these "to the queueproof CI gate" — but that
gate runs *tests*, not *mutations*, so they would never have run anywhere):

| Mutation | Invariant | Result |
|---|---|---|
| drop expired-lease `OR` clause | lease reclaim | RED |
| drop `lease_token` fence on `complete_job` | zombie double-complete | RED |
| drop `lease_token` fence on `fail_job` | zombie double-fail | RED |
| strip the claim row lock (SELECT-then-UPDATE) | claim atomicity | RED |
| drop `ck_jobs_run_pipeline_requires_run` | null `run_id` at DB level | RED |
| remove `SKIP LOCKED` | worker liveness | RED (new proof; see below) |

Two blind spots were found and closed during execution, both of the same species — *a proof
that could not fail*:

- **16-01's concurrency proof** measured ~1.6s of unstubbed live LLM traffic on top of the
  0.6s it meant to measure. Its noise floor was larger than its signal; it passed only where
  no API key existed. Fixed by stubbing the LLM (`f85fbca`).
- **`test_genuine_claim_race_exactly_one_winner`** stays green with `SKIP LOCKED` deleted —
  plain `FOR UPDATE` still yields exactly-one-winner. It proves mutual exclusion, not the
  property the clause exists for (liveness: stepping *over* a row another worker holds).
  New proof `test_skip_locked_steps_over_a_row_another_worker_is_holding` pins it: green in
  0.22s with the clause, red after blocking the full 5.21s timeout without it (`66dafa7`).
