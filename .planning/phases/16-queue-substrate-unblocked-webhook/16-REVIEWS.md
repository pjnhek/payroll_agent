---
phase: 16
reviewers: [codex]
reviewed_at: 2026-07-14
plans_reviewed: [16-01-PLAN.md, 16-02-PLAN.md, 16-03-PLAN.md, 16-04-PLAN.md, 16-05-PLAN.md, 16-06-PLAN.md, 16-07-PLAN.md, 16-08-PLAN.md, 16-09-PLAN.md]
verdict: HIGH RISK — 4 blocking findings, 2 independently confirmed against live source
---

# Cross-AI Plan Review — Phase 16 (Queue Substrate & Unblocked Webhook)

Reviewer: Codex CLI (codex-cli 0.144.0, default model), run source-grounded inside the working
tree with instructions to trace claims against live code rather than review plan prose.

## Codex Review

## Summary

The plans are unusually thorough and strongly focused on non-vacuous concurrency proofs, transaction ownership, lease fencing, and preserving the money-path boundaries. However, they are not ready to execute unchanged: the queue handler’s J-1 invariant conflicts with the required reclaim rewind, the planned `Job` contract does not match the specified `RETURNING` columns, and the CI generalization will unexpectedly activate a large existing integration-test population. Most importantly, the plans repeatedly claim reclaim reruns are harmless while the current clarification-send path still has a provider-acceptance crash window that Phase 20 has not fixed. Overall risk is HIGH until these contracts and sequencing assumptions are resolved.

## Strengths

- The retrigger refactor correctly identifies that enqueueing cannot be a one-line `BackgroundTasks` replacement. The current route performs separate CAS, stale-run read, and context-clear transactions at [app/routes/runs.py:310-380](/Users/pnhek/usf%20msds/github/payroll_agent/app/routes/runs.py:310), so Plan 16-08’s caller-owned transaction is necessary for preventing “state advanced, no job” and “job inserted, no state advance” splits.

- The plans preserve the critical HMAC ordering. The current webhook reads raw bytes and verifies before parsing at [app/routes/webhook.py:38-83](/Users/pnhek/usf%20msds/github/payroll_agent/app/routes/webhook.py:38), and Plan 16-01 explicitly keeps that work on the event loop while offloading blocking parsing and database operations.

- The lease-fencing focus is well grounded. Current completion/failure-style state changes use conditional CAS patterns such as [app/db/repo/runs.py:356-381](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo/runs.py:356), and the plans correctly require fencing both completion and failure writes, not only successful completion.

- The plans correctly preserve the ordinary webhook pipeline path by refusing to remove the unconditional extraction transition at [app/pipeline/orchestrator.py:232-247](/Users/pnhek/usf%20msds/github/payroll_agent/app/pipeline/orchestrator.py:232). Removing it before all producers use the queue would strand ordinary webhook runs.

- The D-02 epoch rationale is grounded in the current implementation. `clear_reply_context` currently increments `reply_epoch` at [app/db/repo/pipeline_state.py:361-385](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo/pipeline_state.py:361), and outbound rows are keyed by epoch in [app/db/schema.sql:253-279](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/schema.sql:253). Returning the new epoch and using it in the dedup key is the correct direction.

## Concerns

- **HIGH — J-1 is internally contradictory with D-01.** Plan 16-06 says the handler’s “first durable action” must be `claim_status(RECEIVED → EXTRACTING)`, and that only the CAS may advance business state. But the same plan requires `rewind_for_reclaim()` to run first on `attempts > 1`; that function changes `payroll_runs.status` from `extracting`/`computed`/`sent` back to `received`. This is a second business-state writer, not merely transport state. The existing status model is centralized around status writes such as [app/pipeline/orchestrator.py:232](/Users/pnhek/usf%20msds/github/payroll_agent/app/pipeline/orchestrator.py:232) and CAS transitions such as [app/db/repo/runs.py:356-381](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo/runs.py:356). Either explicitly define reclaim rewind as a permitted recovery CAS under J-1, or redesign the invariant and its guard. Otherwise the plan’s own “first durable action” and “only CAS advances status” tests cannot both be true.

- **HIGH — The planned `Job` model does not match the claimed SQL result shape.** Plan 16-03 defines seven fields: `id`, `kind`, `run_id`, `email_id`, `attempts`, `max_attempts`, and `lease_token`. But the canonical claim SQL described in Plans 16-04/16-06 returns `id`, `kind`, `run_id`, `attempts`, `max_attempts`, and `lease_token`—no `email_id`. The plan repeatedly says the dataclass mirrors the claim’s `RETURNING` clause. This will produce either a runtime row-construction failure or an unused/made-up field. Decide whether `email_id` belongs in `RETURNING`, remove it from `Job`, or document a separate nullable construction path.

- **HIGH — The “double-run is harmless” argument is not fully true before Phase 20.** The current send path reserves a row with a fresh synthetic `message_id` at [app/email/gateway.py:271-289](/Users/pnhek/usf%20msds/github/payroll_agent/app/email/gateway.py:271), calls the provider at [app/email/gateway.py:339-345](/Users/pnhek/usf%20msds/github/payroll_agent/app/email/gateway.py:339), and only then marks the row sent at [app/email/gateway.py:355-359](/Users/pnhek/usf%20msds/github/payroll_agent/app/email/gateway.py:355). The current duplicate guard counts only `send_state='sent'` rows at [app/db/repo/emails.py:140-171](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo/emails.py:140). A worker can therefore die after provider acceptance but before the sent-state commit; a reclaim can see no sent row and send again with a new message ID. Phase 20’s SEND requirements explicitly address this, but Phase 16’s lease-duration comments and D-02 tests claim the existing guard makes reruns harmless. Narrow the claim to pipeline-state idempotence, exclude any path that can send before Phase 20, or pull the necessary reservation/replay fix forward.

- **HIGH — D-04 will activate many existing integration tests, not “the same two files.”** The current workflow explicitly runs only two files at [.github/workflows/concurrency-proof.yml:60-89](/Users/pnhek/usf%20msds/github/payroll_agent/.github/workflows/concurrency-proof.yml:60). The repository already contains integration markers in files including `tests/test_atomic_persist.py`, `tests/test_dashboard.py`, `tests/test_gateway.py`, `tests/test_ingest.py`, `tests/test_persistence.py`, `tests/test_seed_roundtrip.py`, `tests/test_stuck_run_recovery.py`, and `tests/test_webhook_dedup_race.py`. The Plan 16-02 acceptance criterion claiming whole-suite collection is behavior-preserving is therefore false. This may greatly increase CI runtime, cause unrelated live tests to reset shared state, and introduce skips that were previously outside the gate. Inventory the full marker set, run it against the CI Postgres, and explicitly accept or isolate tests before changing the workflow.

- **MEDIUM — The live-test reset model is vulnerable to the expanded marker set.** `seeded_db` performs a destructive reset at module scope in [tests/conftest.py:74-93](/Users/pnhek/usf%20msds/github/payroll_agent/tests/conftest.py:74), while many independently marked integration modules exist. Once all markers run, module-order-dependent seeded data and database state become a real risk. The plans add `jobs` to `_DROP_ORDER`, but that fixes only one table omission; they do not establish that every newly activated integration module is isolated or that test ordering is safe.

- **MEDIUM — The queue’s failure semantics knowingly lose jobs before FAIL-01.** `run_pipeline_bg` catches startup exceptions and returns normally at [app/routes/pipeline_glue.py:210-224](/Users/pnhek/usf%20msds/github/payroll_agent/app/routes/pipeline_glue.py:210). Plan 16-06 then treats normal handler return as successful completion, while Plan 16-04 only calls `fail_job` when an exception escapes. Thus an import failure, startup failure, or certain database failures can mark a durable job done without completing the run. The plans document this as deferred, but the phase’s “durable retrigger” language overstates the guarantee. Add an explicit phase-level residual-risk test and dashboard/operator visibility, or avoid calling this failure mode durable until FAIL-01 lands.

- **MEDIUM — `clear_reply_context` changes the fake-repo contract but existing tests rely on its current `None` behavior.** The live implementation currently returns `None` at [app/db/repo/pipeline_state.py:346-385](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo/pipeline_state.py:346), and the in-memory implementation also returns `None` at [tests/conftest.py:660-683](/Users/pnhek/usf%20msds/github/payroll_agent/tests/conftest.py:660). Plan 16-04 correctly identifies the need to return an epoch, but the plan should enumerate every caller and fake assertion that must be updated, especially because the route will now require `conn=conn` and consume the return value. A missing fake update would silently fall through to the real facade, which the fixture itself warns about at [tests/conftest.py:1033-1036](/Users/pnhek/usf%20msds/github/payroll_agent/tests/conftest.py:1033).

- **LOW — The webhook threadpool plan has a thread-safety assumption that should be tested directly.** `finish_reply_resume()` appends to `BackgroundTasks` from inside the helper at [app/routes/pipeline_glue.py:80-131](/Users/pnhek/usf%20msds/github/payroll_agent/app/routes/pipeline_glue.py:80). Plan 16-01/16-02 moves that call into `run_in_threadpool` while passing the request-owned `BackgroundTasks` object across the boundary. This is likely safe in CPython because the operation is a list append, but it is an undocumented cross-thread ownership assumption. Add a reply-candidate proof that verifies the task is present and executes, rather than testing only timing on the new-run branch.

- **LOW — The worker shutdown lifecycle needs a second-start guard.** Plan 16-07 clears the thread list after joining, even if a join times out, while the old daemon thread may still be executing and holding a released lease. A subsequent `start()` can create a second worker set while the old worker remains alive. Fencing makes the database writes safe, but the plan should prevent duplicate worker capacity or explicitly track generations. The risk follows from the proposed unconditional release behavior and the shared held-token set, not from the current app, which has no worker lifecycle yet at [app/main.py:1-16](/Users/pnhek/usf%20msds/github/payroll_agent/app/main.py:1).

## Suggestions

- Define J-1 precisely as: “every normal forward transition uses `claim_status`; reclaim rewind is a separately named, fenced recovery transition permitted only when `attempts > 1`.” Add a static guard that all business-status writers are either approved forward CAS or approved reclaim recovery.

- Resolve the `Job`/`RETURNING` mismatch before implementation and add one row-mapping test that asserts every returned column maps exactly once.

- Add a pre-Phase-20 test covering a crash after provider acceptance but before the sent-state commit. If the intended answer is “not guaranteed until Phase 20,” state that explicitly in the phase success criteria and remove the claim that the current guard makes every rerun harmless.

- Before changing CI, collect and classify every existing `integration` marker. Either make all of them reliable under the shared Postgres service or use a narrower queue-specific marker while retaining a separate explicit workflow inventory.

- Add a phase-level test for a handler startup exception and document whether it should be `done`, `pending`, or `dead`. If the safe behavior is not implementable until FAIL-01, make that limitation prominent in the roadmap proof rather than burying it in deferred notes.

- Make the webhook reply-candidate test exercise the actual `BackgroundTasks` scheduling after the threadpool hop, and add a worker generation/stop idempotency test.

## Risk Assessment

**Overall risk: HIGH.** The transaction and fencing design is strong, and the plans show excellent awareness of vacuous proofs and existing repository seams. But the J-1/reclaim contradiction, the `Job` row-shape mismatch, the false CI-scope assumption, and the pre-Phase-20 send-idempotency gap are all implementation-blocking issues. Resolve those before execution; after correction, the remaining risk should be medium and primarily operational/test-suite integration risk.

---

## Orchestrator Verification (Claude)

Single-reviewer run, so there is no cross-reviewer consensus to synthesize. Instead the two most
falsifiable HIGH findings were independently re-traced against live source before being accepted:

### CONFIRMED — `Job` / `RETURNING` shape mismatch (Codex HIGH #2)

- `16-RESEARCH.md:399` — the canonical claim SQL, which plan `16-04:135-136` says is "transcribed
  verbatim", ends: `RETURNING j.id, j.kind, j.run_id, j.attempts, j.max_attempts, j.lease_token;`
  That is **6 columns. No `email_id`.**
- `16-03-PLAN.md:115-117` defines `Job` as "a frozen dataclass mirroring exactly what the claim
  SQL's `RETURNING` clause yields" with **7** fields — including `email_id: uuid.UUID | None`.
- `16-04-PLAN.md:145` then asserts "`RETURNING` must yield exactly the `Job` dataclass's fields
  (no `event_id`)" — which contradicts the verbatim SQL it just told the executor to transcribe.

Two plans give the executor mutually exclusive instructions. `16-06` never reads `job.email_id`
(only `.run_id`, `.attempts`, `.id`, `.lease_token`), so the field has no consumer in this phase.
**Resolution needed before execution:** either drop `email_id` from `Job` and keep the 6-column
verbatim SQL, or add `j.email_id` to the `RETURNING` and stop calling the SQL verbatim.

### CONFIRMED — D-04 CI generalization activates far more than "the same two files" (Codex HIGH #4)

- `.github/workflows/concurrency-proof.yml:87` hard-codes exactly two files:
  `tests/test_concurrency_proof.py tests/test_email_epoch_arbiter_integration.py -m integration`.
  The surrounding comment block (`:60-84`) is explicit that **file selection is by name** and that
  `-m integration` only narrows what was already collected.
- The repo currently carries `integration` markers in **12** files: `test_atomic_persist.py`,
  `test_claim_status.py`, `test_concurrency_proof.py`, `test_dashboard.py`,
  `test_email_epoch_arbiter_integration.py`, `test_gateway.py`, `test_ingest.py`,
  `test_persistence.py`, `test_seed_roundtrip.py`, `test_stuck_run_recovery.py`,
  `test_threading.py`, `test_webhook_dedup_race.py`.

So generalizing collection to the whole suite turns on **10 previously-dormant live-DB modules** at
once, against a shared Postgres service, with `tests/conftest.py:74-93` doing a destructive
module-scope reset. Plan 16-02's "behavior-preserving" acceptance criterion is false as written.
This also matches a known project fact: the great majority of `-m integration` tests have never
executed in CI. Inventory and classify all 12 before flipping the workflow.

### Not re-verified (accepted as plausible, worth resolving)

- **J-1 vs D-01 reclaim rewind contradiction (HIGH #1)** — `rewind_for_reclaim()` writes
  `payroll_runs.status`, which makes it a second business-state writer under an invariant that says
  only `claim_status` may advance business state. The invariant needs an explicit carve-out or a
  redesign; as written, 16-06's own "first durable action" and "only CAS advances status" tests
  cannot both pass.
- **Pre-Phase-20 send idempotency (HIGH #3)** — `app/email/gateway.py` reserves → sends → marks
  sent, and the duplicate guard counts only `send_state='sent'` rows, so a crash between provider
  acceptance and the sent-state commit lets a reclaim re-send. The plans' "reruns are harmless"
  claim is true for pipeline state but **not** for the send path until Phase 20's SEND work lands.
- Three MEDIUM (live-test reset model under the expanded marker set; jobs silently marked done when
  `run_pipeline_bg` swallows a startup exception pre-FAIL-01; `clear_reply_context` fake-repo
  contract change) and two LOW (cross-thread `BackgroundTasks` append; worker second-start guard).

## Top Concerns (priority order)

1. **HIGH** `Job` dataclass vs claim SQL `RETURNING` — 7 fields vs 6 columns. CONFIRMED. Blocking.
2. **HIGH** D-04 CI scope — flips on 10 dormant live-DB modules, not zero. CONFIRMED. Blocking.
3. **HIGH** J-1 invariant contradicts the D-01 reclaim rewind (two business-state writers).
4. **HIGH** "Reruns are harmless" overclaims: the send path can double-send until Phase 20.

## Next Step

  /gsd-plan-phase 16 --reviews

---

# Cross-AI Plan Review — Phase 16, ROUND 2

Reviewer: Codex CLI, source-grounded, re-reviewing the REVISED 10 plans (commit b33f864) with round 1's
findings as an explicit checklist. Job 1: is each round-1 finding actually closed, or just reworded?
Job 2: what did the revision itself break?

# Part 1 — Round 1 finding verdicts

| Finding | Verdict | Evidence | Why |
|---|---|---|---|
| J-1 contradicted reclaim rewind | CLOSED | Revised 16-06 objective; current `claim_status` CAS at [app/db/repo/runs.py:356-381](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo/runs.py:356) | The revision explicitly permits exactly two queue-side CAS writers: forward `claim_status` and reclaim-only `rewind_for_reclaim`, gated by `attempts > 1`. The old “first action must always be claim_status” contradiction is removed. |
| `Job` vs `RETURNING` mismatch | CLOSED | Revised 16-03 Task 1 and 16-04 Task 1; current repo row-mapping conventions at [app/db/repo/runs.py:239-258](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo/runs.py:239) | `Job` is now explicitly six fields, with no `email_id`, and the plan requires ordered bidirectional `RETURNING` equality tests. An executor has a single coherent contract. |
| Pre-Phase-20 double-send window | CLOSED | New 16-10; current reserve/provider/sent sequence at [app/email/gateway.py:271-289](/Users/pnhek/usf%20msds/github/payroll_agent/app/email/gateway.py:271), [app/email/gateway.py:339-357](/Users/pnhek/usf%20msds/github/payroll_agent/app/email/gateway.py:339) | D-13 adds an epoch- and purpose/round-scoped fail-closed guard for `reserved` and `failed` rows before both send sites. The revised plans no longer claim generic reruns are harmless. Provider failure intentionally escalates to `ERROR`, which the plan keeps outside automatic rewind. |
| D-04 unexpectedly activates dormant integration tests | CLOSED | Revised D-14 in 16-02; current filename-limited workflow at [.github/workflows/concurrency-proof.yml:65-89](/Users/pnhek/usf%20msds/github/payroll_agent/.github/workflows/concurrency-proof.yml:65) | The existing two-file gate remains unchanged, and the new gate selects only `queueproof`. This avoids waking the ten dormant integration modules. |
| Expanded live-test reset model is unsafe | PARTIALLY CLOSED | D-14 narrows CI scope; reset remains module-scoped at [tests/conftest.py:57-73](/Users/pnhek/usf%20msds/github/payroll_agent/tests/conftest.py:57) | The broad CI blast radius is closed, but the new `tests/test_queue_durability.py` contains multiple live queue tests sharing one module-scoped reset. The plans do not require per-test queue cleanup or isolated dedup/claim state. |
| Startup exceptions silently mark jobs done | CLOSED | Revised 16-06 Task 2 residual-risk block and named `test_swallowed_start_failure_marks_the_job_done_KNOWN_GAP_FAIL01` | The limitation is now explicitly qualified, pinned by a regression target, and excluded from the phase’s headline guarantee. It is not fixed, but the revised plan no longer misrepresents it as fixed. |
| `clear_reply_context` fake/caller contract | CLOSED | Revised 16-04 Task 2 caller inventory; current implementation returns nothing at [app/db/repo/pipeline_state.py:346-385](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo/pipeline_state.py:346) and fake at [tests/conftest.py:660-683](/Users/pnhek/usf%20msds/github/payroll_agent/tests/conftest.py:660) | The revision names the production caller, fake implementation, tuple, and unchanged tests, and adds the universal pairing guard. It gives the executor the required updates. |
| Worker second-start lifecycle guard | CLOSED | Revised 16-07 Task 1/2; current app has no worker lifecycle yet ([app/main.py:1-16](/Users/pnhek/usf%20msds/github/payroll_agent/app/main.py:1)) | `_orphans`, generation tracking, refusal while an orphan lives, and an explicit liveness test close the original “clear timed-out threads then start another generation” defect. |

The only finding not fully closed is the live-test reset model: narrowing CI prevents the original ten-module blast radius, but it does not isolate the new multi-test queueproof module from leftover pending or leased jobs.

# Part 2 — New findings

- **HIGH — Worker restart is still broken because the stop event is never reset.** Revised 16-07 requires `stop()` to set the worker stop event, but `start()` never explicitly clears or replaces it. After a clean `start → stop`, a later `start()` creates threads whose first loop observes the already-set event and exits immediately. This directly contradicts the revised test requiring restart after the orphan dies. Failure sequence: clean shutdown → second `start(1)` → worker exits without draining. The plan must specify a fresh/cleared stop event at each new generation.

- **HIGH — Queueproof live tests can consume each other’s jobs.** `seeded_db` resets once per module, not per test ([tests/conftest.py:57-73](/Users/pnhek/usf%20msds/github/payroll_agent/tests/conftest.py:57)). The planned `test_queue_durability.py` contains claim-race, expiry, release, shutdown, and reclaim tests, while `claim_job()` selects globally claimable jobs. Several tests intentionally leave jobs leased or pending. A later test can claim an earlier test’s row, causing false winners, wrong attempt counts, or a proof that passes against the wrong run. Add per-test queue cleanup, unique-scoped claim filtering, or a fixture that resets jobs between tests.

- **MEDIUM — The AST J-1 guard is trivially bypassable.** The revised guard scans `repo.<name>(...)` calls, but an executor following that mechanism can miss `r = repo; r.set_status(...)`, `getattr(repo, "set_status")(...)`, or an imported alias. It also cannot infer which calls semantically write `payroll_runs.status`; it must rely on a hard-coded name list. A future queue handler using an alias can therefore add an unconditional status write while the AST guard remains green. The guard should reject aliases/imported repo objects or inspect all calls to known status-writing functions more robustly.

- **MEDIUM — `RUN_PIPELINE` jobs remain valid with `run_id = NULL`.** Revised 16-03 keeps `run_id` nullable and revised 16-04 exposes `enqueue_job(..., run_id=None)`. The sole `JobKind` is `run_pipeline`, yet the schema does not enforce that this kind has a run ID. A malformed or future caller can enqueue a null-run job; the handler then attempts `claim_status(None, ...)`, returns normally, and `drain_once()` can mark the job done without processing any payroll. Add a kind-specific constraint or reject null `run_id` in `enqueue_job`/dispatch.

- **LOW — The queueproof mutation rationale is overstated.** The new CI step uses `set -o pipefail`; `pytest tests/ -m queueprooof` with no matches normally exits 5, so the step is already red even without the `[0-9]+ passed` guard. The guard is still useful defense-in-depth, but the claimed “typo collects zero tests and exits green” mutation is not accurate for this invocation. More importantly, the guard cannot detect a typo on one newly added test if other queueproof tests still pass.

# Part 3 — Risk Assessment

Overall risk: **HIGH — NOT READY TO EXECUTE.**

The Round 1 contractual findings are largely addressed, and D-13 materially improves the money-path safety story. However, the missing stop-event reset can permanently brick worker restarts, and the shared live queue state makes the central durability proofs capable of consuming the wrong jobs. Those are execution-blocking defects in the new worker and proof substrate. Resolve them before implementation.

---

## Orchestrator Verification (Claude) — round 2

Both new HIGH findings independently re-traced against live source. Both CONFIRMED:

### CONFIRMED — stop event is never reset (new HIGH #1)

- `16-07-PLAN.md:141` — `_loop(gen)` runs "until the stop event is set **or its generation is stale**".
- `stop()` sets that event. Nothing in the plan clears or replaces it on the next `start()`.
- Therefore after a clean `start()` → `stop()`, a later `start()` spawns threads whose first loop
  iteration observes an already-set event and returns immediately. The workers exist but never drain.
- This makes the plan self-contradictory: `16-07:247` specifies
  `test_start_refuses_while_a_previous_generation_is_still_alive`, whose premise is that a start
  AFTER the orphan dies succeeds — but as specified it would spawn dead workers.

Fix: the stop event must be fresh (or explicitly `.clear()`ed) per generation in `start()`, and the
plan needs a test that a restarted worker actually CLAIMS a job — not merely that threads are alive.

### CONFIRMED — module-scoped reset lets queue proofs eat each other's jobs (new HIGH #2)

- `tests/conftest.py:57` — `@pytest.fixture(scope="module")`, `bootstrap(reset=True)` runs ONCE per module.
- The planned `tests/test_queue_durability.py` holds multiple live-DB queue proofs (claim race, lease
  expiry, release-on-shutdown, reclaim), and several deliberately LEAVE a job `pending` or `leased`.
- `claim_job()` claims the oldest eligible row GLOBALLY — it has no per-test scoping.
- So a later test in the same module can claim an earlier test's leftover row: false winners, wrong
  `attempts` counts, a proof that passes against the wrong run. This is the same vacuous-proof class as
  the Phase 10 concurrency proof.

Fix: per-test queue cleanup (truncate `jobs` between tests), or scope every claim assertion to a
job id the test itself enqueued. A durability proof that can claim someone else's row proves nothing.

### Accepted without re-tracing

- **MEDIUM — `run_pipeline` jobs may carry `run_id = NULL`.** `enqueue_job(..., run_id=None)` is
  exposed and the schema does not require a run id for the only `JobKind` there is. A null-run job
  would `claim_status(None, ...)`, no-op, and be marked `done` — a silently discarded job. Needs a
  kind-specific NOT NULL / CHECK constraint or a reject in `enqueue_job`.
- **MEDIUM — the AST J-1 guard is name-based** and misses `r = repo; r.set_status(...)`, `getattr`,
  and import aliases. Harden it or state the limitation.
- **LOW — the queueproof mutation rationale is factually wrong.** pytest exits 5 on zero-collected, so
  a marker typo is ALREADY red; the plan should not teach that it would "exit green". Keep the
  `[0-9]+ passed` guard (still useful) but fix the stated rationale.

### Round 1 scorecard

7 of 8 round-1 findings CLOSED. 1 PARTIAL (the live-test reset model — narrowing CI removed the
10-module blast radius but did not isolate the new queue proofs from each other; that partial is
exactly what new HIGH #2 makes concrete).

**Verdict: NOT READY TO EXECUTE.** The contractual round-1 defects are fixed and D-13 materially
improves money-path safety, but the revision introduced a bricked worker restart and a
self-interfering proof substrate. Both are in the new code this phase ships.
