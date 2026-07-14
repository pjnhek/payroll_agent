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
