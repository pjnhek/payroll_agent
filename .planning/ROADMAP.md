# Roadmap: Payroll Agent

## Milestones

- ✅ **v1.0 — MVP** (shipped 2026-06-25) — Email-driven payroll agent: messy email in, correct human-approved payroll out, every money-moving decision code-gated (deterministic, auditable, never guesses). 7 phases, deployed live on a free stack with a recorded demo. → [full archive](milestones/v1.0-ROADMAP.md) · [requirements](milestones/v1.0-REQUIREMENTS.md)
- ✅ **v2 — Production Hardening** (shipped 2026-07-07) — Took the working v1.0 MVP and made its money-logic and data layer genuinely production-grade — correct under real, messy, concurrent load, not just the demo path. 6 phases (7, 7.5, 8, 9, 10, 11), 16 requirements, scope discovered via an adversarial audit. → [full archive](milestones/v2-ROADMAP.md) · [requirements](milestones/v2-REQUIREMENTS.md) · [audit](milestones/v2-MILESTONE-AUDIT.md)
- ✅ **v3 — Production-Ready Codebase** (shipped 2026-07-13) — Made the codebase itself read as production-quality without changing a line of money behavior: enforced CI (ruff + full suite + `mypy --strict`, all blocking), the three god-files split into right-sized modules, the entire repo type-clean across 117 files, and provenance comments replaced with constraint-documenting ones behind a CI guard. 4 phases (12–15), 16/16 requirements, 227 commits. Found 3 real defects on the way — a lying eval chart, a path traversal, and a prompt-echo leak. → [full archive](milestones/v3-ROADMAP.md) · [requirements](milestones/v3-REQUIREMENTS.md) · [audit](milestones/v3-MILESTONE-AUDIT.md)
- 🚧 **v4 — Durable Execution** (started 2026-07-13) — No accepted email is ever lost; every failure recovers automatically within ~30 minutes without a human noticing; a client is sent at most one confirmation per approved run, per epoch. Origin: an adversarial audit found the pipeline's `BackgroundTask` handoff is durable in memory only, and the webhook blocks the event loop on a synchronous Resend fetch + a multi-query psycopg transaction. 6 phases (16–21), 19 requirements. Design: `docs/superpowers/specs/2026-07-13-durable-execution-design.md`.

## Active Milestone: v4 — Durable Execution

**Goal:** No accepted email is ever lost. Every failure recovers automatically within ~30 minutes,
best-effort, without a human noticing. A client is sent at most one confirmation per approved run, per
epoch. Exactly-once delivery is not claimed — it's the Two Generals problem, not a library gap; the
honest, narrower claim is published instead.

**Shape:** A durability-and-reliability milestone bolted onto a shipped, working pipeline — zero new
dependencies, all schema/worker/queue machinery on top of primitives already installed and already in
production use (`pgcrypto`/`gen_random_uuid()`, `SKIP LOCKED`-capable Postgres 15+, `psycopg[binary,pool]`,
`resend`'s `Idempotency-Key`). Research (4 parallel researchers + a Codex review) validated the approved
design and found 5 defects in its first draft — corrected before this roadmap was cut. The build order below
is research-derived, not imposed, with one **non-negotiable ordering constraint**: the pump and the failure
policy MUST precede the webhook cutover to the queue, or the cutover ships a regression window in which a
worker records SUCCESS on a payroll that actually FAILED (the orchestrator today writes `ERROR` and returns
normally), while the old `sweep_stranded_runs` races the new queue with both firing at ~15 minutes. Phase 1
of the original 7-phase research plan (unblock the event loop) carries zero schema risk and no forced-order
dependency, so it is folded into Phase 16 alongside the queue substrate rather than standing alone.

**Two cross-cutting hazards this milestone must not repeat:** (1) `concurrency-proof.yml` is the only CI
workflow with a real Postgres and hard-codes its test files by name — a durability proof landed outside that
line never runs; (2) this repo has already shipped a "concurrency proof" that passed while proving nothing
(its threads serialized through an async route and never actually raced) — every proof here must ship with a
demonstrated red run. Both are enforced as explicit success criteria in Phase 21.

### Phases

**Phase Numbering:** v4 continues the global phase sequence from v3 (last phase: 15). Integer phases
(16–21) are planned milestone work; decimal phases (e.g. 16.1) are reserved for urgent insertions.

- [x] **Phase 16: Queue Substrate & Unblocked Webhook** - The webhook stops blocking the event loop and a durable Postgres job queue exists, proven on one already-manual, low-risk producer (operator retrigger) before the money path touches it. (completed 2026-07-14)
- [x] **Phase 17: The Pump** - An authenticated, cron-driven pump endpoint turns durable storage into durable execution — a job scheduled for later actually fires with no human present. (completed 2026-07-15)
- [x] **Phase 18: Failure Policy & Sweep Deletion** - The orchestrator returns an explicit ok/retryable/terminal result instead of swallowing failures, and the queue's lease-based recovery replaces the racing dashboard sweep as the sole recovery mechanism. (completed 2026-07-16)
- [x] **Phase 19: Webhook Cutover & Durable Ingest** - The Resend body-fetch moves off the request path into a durable, retryable job; every remaining in-memory `BackgroundTasks` producer is migrated to the queue. (completed 2026-07-17)
- [x] **Phase 20: Exactly-Once Send** - A retry reuses the reserved `message_id`, replays the persisted payload, and carries Resend's `Idempotency-Key` — a client is sent at most one confirmation per approved run, per epoch. (completed 2026-07-17)
- [ ] **Phase 21: Durability Proofs & Ops View** - Four durability proofs, each demonstrated able to fail, wired into the only CI workflow with a real Postgres; an ops page makes "the queue is healthy" a checkable fact.

## Phase Details

### Phase 16: Queue Substrate & Unblocked Webhook

**Goal**: The webhook stops blocking the event loop, and a durable Postgres job queue exists — proven on
one already-manual, low-risk producer (operator retrigger) before the money path ever touches it.
**Depends on**: Nothing (first v4 phase)
**Requirements**: QUEUE-01, QUEUE-02, QUEUE-03, QUEUE-05
**Success Criteria** (what must be TRUE):

  1. Firing two concurrent inbound webhook requests against a slow Resend fetch completes in wall-clock time roughly equal to the slowest one, not their sum — the event loop is never blocked by the body-fetch or the ingest transaction.
  2. Clicking "Retrigger" on a stuck run enqueues a durable `jobs` row; killing the worker process mid-run and draining again (a second worker, or a manual drain) completes the retrigger without the operator re-clicking anything.
  3. A job whose worker died while holding the lease is reclaimed and re-run by another worker once the lease expires — it is never stuck in `leased` state forever.
  4. A routine redeploy (graceful worker shutdown) releases any held leases immediately, so an in-flight retrigger resumes within seconds rather than stalling for the full lease duration.
  5. A CI-enforced guard fails the build if a `jobs.kind` value ever collides with a `payroll_runs.status` value or drifts from the `JobKind` enum — the job row can never encode "what payroll status comes next."

**Plans**: 10/10 plans complete
*(Replanned 2026-07-14 after a cross-AI plan review. Two scope-level decisions were locked: **D-13** —
forward-port the send-idempotency fix into this phase, because this phase is where live workers and
lease-expiry reclaim actually ship, so this is where the double-send window actually opens; and
**D-14** — keep the CI gate narrow (a dedicated `queueproof` marker), superseding D-04's whole-suite
`-m integration` collection, which would have woken 10 dormant live-DB modules at once. Plan **16-10**
is the new plan; it is numbered 10 but **runs in wave 3** — deliberately BEFORE the wave-4 plans that
start the first live workers.)*

**Wave 1**

- [x] 16-01-PLAN.md — Unblock the inbound webhook: `run_in_threadpool` around the Resend fetch, the ingest transaction, and the response-shaping branches (D-11) + Proof 1 + the cross-thread `BackgroundTasks` proof *(wave 1)*
- [x] 16-02-PLAN.md — Proof surface + config knobs: the `queueproof` marker and a NARROW second CI gate (D-14) and `WORKER_COUNT`/`LEASE_SECONDS`/`MAX_ATTEMPTS` with derivations (D-03/D-08) *(wave 1)*
- [x] 16-03-PLAN.md — The `jobs` table, `JobKind`/`JobState`/`Job` (6 fields), `_DROP_ORDER`, and the D-05 inventory-pinned index guard *(wave 1)*

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 16-04-PLAN.md — `app/db/repo/jobs.py`: the claim/lease/fencing protocol, the `RETURNING`↔`Job` bijection test, `clear_reply_context -> epoch`, `rewind_for_reclaim` (D-02), the fakes + the universal fake-repo pairing guard, and Proof 3 *(wave 2)*
- [x] 16-05-PLAN.md — `/health/schema` covers `jobs` (D-12) + Proof 5's collision and enum-drift guards *(wave 2)*

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 16-06-PLAN.md — `app/queue/`: wake (D-09), dispatch, the `run_pipeline` handler (D-01 rewind + the restated INVARIANT J-1 + its CAS-only static guard), `drain_once()`, and the pre-FAIL-01 pin test *(wave 3)*
- [x] 16-10-PLAN.md — **D-13: the fail-closed send-idempotency guard.** A `reserved`/`failed` outbound row in the run's current epoch means the provider MAY already hold the message → do NOT re-send, escalate to the operator. Lands BEFORE the first live worker. *(wave 3)*

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 16-07-PLAN.md — Worker threads + the app's first `lifespan`, the D-07 pool-budget refusal, the second-start/generation guard, and Proof 4 *(wave 4)*
- [x] 16-08-PLAN.md — Retrigger cutover: one caller-owned transaction, `enqueue_job`, post-commit wake, no UI change (D-10) *(wave 4)*

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 16-09-PLAN.md — Proof 2: a retrigger survives a worker death and completes on the next drain; plus the phase's residual-risk table *(wave 5)*

### Phase 17: The Pump

**Goal**: Durable storage becomes durable execution — a job scheduled for later actually fires even when
nothing is knocking on the front door.
**Depends on**: Phase 16
**Requirements**: PUMP-01, PUMP-02
**Success Criteria** (what must be TRUE):

  1. Calling the authenticated `/internal/pump` endpoint claims and drains due jobs and returns real counts (claimed/done/retried/dead/queue depth) — not just a bare 200.
  2. A job scheduled with a future `available_at`, on an instance that has just cold-started with no live worker threads yet, still executes once the pump's cron fires — proving the pump, not the in-process workers, is the actual guarantee.
  3. The README states the chosen pump cadence, the resulting worst-case recovery-latency bound, and the 750-instance-hour/month arithmetic that forces that cadence, in plain checkable numbers.
  4. `.github/workflows/pump.yml` is the only cron hitting the service — the old twice-weekly keepalive workflow is gone, absorbed into the pump. **Absorbed means BOTH of keepalive.yml's jobs carry over, not just the wake-up ping:** the pump workflow must still fail RED on `/health/schema` returning 503 (live-DB schema drift) and on `/health/ready` failing. Deleting `keepalive.yml` without carrying the schema-parity check forward would silently drop drift detection that a prior milestone shipped deliberately — and it is the only monitor that catches a manual Supabase edit bypassing the deploy-migrate workflow.

**Plans**: 5/5 plans complete

**Wave 1** (foundation — no cross-deps, parallel):

- [x] 17-01-PLAN.md — Enrich `drain_once()` → `DrainOutcome` StrEnum (D-04) + rewrite the ~15 `is True/False` identity assertions
- [x] 17-02-PLAN.md — `count_open_jobs()` repo function (queue depth) + facade re-export + docstring update + hermetic test
- [x] 17-03-PLAN.md — `pump.yml` (30-min cron, 3 curl -f steps, D-06/07/08) replacing keepalive, `render.yaml` PUMP_TOKEN, README cadence/750h doc (PUMP-02, criteria #3/#4)

**Wave 2** (blocked on 17-01 + 17-02):

- [x] 17-04-PLAN.md — The authenticated `GET /internal/pump` route (D-01/02/03/05/09/10) + `pump_token` setting + main wiring + hermetic auth/bounded/infra tests

**Wave 3** (blocked on 17-04):

- [x] 17-05-PLAN.md — The criterion #2 anti-vacuous durability proof: future-due job, zero live workers, drained via the HTTP endpoint, with the falsifying-mutation demonstration (PROOF-05)

### Phase 18: Failure Policy & Sweep Deletion

**Goal**: A pipeline failure is classified honestly — ok, retryable, or terminal — instead of being
swallowed into a silent success, and the queue's own lease-based recovery becomes the sole recovery
mechanism.
**Depends on**: Phase 17 (the pump must exist before a retryable job can be trusted to actually fire)
**Requirements**: FAIL-01, FAIL-02, FAIL-03
**Success Criteria** (what must be TRUE):

  1. A transient LLM/provider timeout during extraction is retried automatically with backoff and eventually completes — it is never left as a permanent, un-retried ERROR.
  2. A run whose deterministic decision is `request_clarification` is never retried as though it failed — the client is never emailed the same clarification question more than once because a worker misread a correct decision as an error.
  3. A job that exhausts its attempt cap lands in a visible dead-letter state an operator can see and act on, rather than stalling silently.
  4. `sweep_stranded_runs`, `find_stranded_unconsumed_replies`, and the runs-list sweep block are removed from the codebase — there is exactly one recovery mechanism left, not two racing ones.
  5. Viewing the list of runs no longer has any side effect on any run's status — it is a read, not an accidental cron trigger.

**Plans**: 14/14 plans complete

**Wave 1** (result contract foundation):

- [x] 18-01-PLAN.md — Define the bounded pipeline result contract, classifier, and temporary legacy adapter

**Wave 2** (durable persistence foundation; blocked on 18-01):

- [x] 18-02-PLAN.md — Add identifier-only job context and typed operator-resolution persistence

**Wave 3** (schema parity; blocked on 18-02):

- [x] 18-12-PLAN.md — Extend schema introspection for operator-resolution storage and job linkage

**Wave 4** (durable resume consumers; blocked on 18-01, 18-02, and 18-12):

- [x] 18-09-PLAN.md — Add persisted-reply and operator-resolution queue handlers and dispatch

**Wave 5** (atomic background settlement; blocked on 18-01, 18-02, 18-09, and 18-12):

- [x] 18-03-PLAN.md — Install atomic result settlement and durable retry bridges before producer cutover

**Wave 6** (queue policy and operator visibility; blocked on 18-03):

- [x] 18-04-PLAN.md — Make queue drain result-aware and reap expired final-attempt leases
- [x] 18-06-PLAN.md — Surface bounded retry diagnostics and preserve same-run manual retrigger

**Wave 7** (pump accounting and producer cutover; blocked on 18-04):

- [x] 18-05-PLAN.md — Report final-lease reaping honestly in pump accounting
- [x] 18-10-PLAN.md — Cut both orchestrator entry points over to explicit PipelineResult returns

**Wave 8** (strict compatibility closure; blocked on 18-10):

- [x] 18-11-PLAN.md — Remove every remaining None-as-success compatibility path

**Wave 9** (caller-first sweep removal; blocked on 18-04, 18-06, and 18-11):

- [x] 18-07-PLAN.md — Make GET /runs read-only and remove all legacy sweep callers

**Wave 10** (retired API deletion; blocked on 18-07 and durable replacements):

- [x] 18-08-PLAN.md — Delete sweep repositories, facade exports, fakes, and obsolete status support

**Wave 11** (final-lease gap closure; blocked on 18-04):

- [x] 18-13-PLAN.md — Make final-attempt lease reaping status-aware, atomic, and starvation-free

**Wave 12** (resume-context and regression closure; blocked on 18-09, 18-11, and 18-13):

- [x] 18-14-PLAN.md — Bind persisted replies to their claimed run and restore always-run handler coverage

### Phase 19: Webhook Cutover & Durable Ingest

**Goal**: An accepted inbound email is durable the instant the webhook returns 200 — no client email is
ever lost to a restart, a crash, or a sleeping instance again.
**Depends on**: Phase 18 (and, transitively, Phase 17) — cutting the webhook over to the queue before the
pump and the failure policy exist would ship a durability regression, not an improvement.
**Requirements**: QUEUE-04
**Success Criteria** (what must be TRUE):

  1. All 8 background-task producers (the webhook, both demo triggers, and the five in the runs routes — including the one hiding inside the runs-list page render) are migrated to the durable queue; none schedule pipeline work into process memory anymore.
  2. Redelivering the same inbound webhook event (same Svix event ID) never creates a second job or a second run, even though the Resend body-fetch now happens later, inside a worker, not at ingest time.
  3. Killing the process immediately after the webhook returns 200 — before any pipeline work starts — does not lose the email; the accepted event is durably recorded and the run completes once a worker or the pump picks it up.
  4. A clarification reply from an unauthorized sender is still rejected exactly as it is today — moving the ingest transaction into a worker did not weaken the sender-revalidation guard.

**Plans**: 12/12 plans complete

**Wave 1** (additive receipt and operator-authority foundation):

- [x] 19-01-PLAN.md — Add receipt/authority schema plus fail-closed live inventory and introspection

**Wave 2** (independent authority and delayed-ingest services; blocked on 19-01):

- [x] 19-02-PLAN.md — Serialize first-commit-wins operator authority and winner-only alias learning
- [x] 19-03-PLAN.md — Move DATA-02 and authenticated inbound classification into a delayed-ingest service

**Wave 3** (bounded INGEST vocabulary/model/SQL/dispatch activation; blocked on 19-01 and 19-03):

- [x] 19-04-PLAN.md — Activate the exact identifier-only INGEST vocabulary, model, SQL, claim, dispatch, and delayed handler contract

**Wave 4** (null-run settlement plus independent run-associated producer cutovers):

- [x] 19-05-PLAN.md — Settle/reap every null-run INGEST outcome without payroll mutation and complete fake parity
- [x] 19-07-PLAN.md — Cut both demo triggers to durable jobs with bounded accepted notices
- [x] 19-08-PLAN.md — Cut reply/operator producers to durable jobs and winner-only handlers

**Wave 5** (off-loop webhook and secondary queue UI):

- [x] 19-06-PLAN.md — Cut the webhook to an atomic receipt/job commit through an awaited threadpool helper after vocabulary and settlement are both complete
- [x] 19-09-PLAN.md — Add safe queue badges, bounded notices, and 2-second status polling

**Wave 6** (stale-consumer migration; blocked on every producer cutover):

- [x] 19-11-PLAN.md — Migrate all nine stale wrapper-test consumers to explicit durable seams

**Wave 7** (compatibility deletion gate; blocked on the runs UI projection and all consumer migrations):

- [x] 19-12-PLAN.md — Delete the migrated compatibility surface and install the complete producer/retired-symbol guard

**Wave 8** (phase evidence and deploy checkpoint; blocked on all cutover and deletion plans):

- [x] 19-10-PLAN.md — Prove retention/restart durability and fence the Phase 18 writer through exact Phase 19 activation before reopening submissions

### Phase 20: Exactly-Once Send

**Goal**: A client is sent at most one payroll confirmation per approved run, per epoch — a retry never
redrafts, never regenerates non-deterministic bytes, and never silently orphans a reply into a phantom run.
**Depends on**: Phase 18 (the retry/backoff infrastructure) — independent of Phase 19, could ship in
parallel with it.
**Requirements**: SEND-01, SEND-02, SEND-03
**Success Criteria** (what must be TRUE):

  1. Retrying a send after a crash reuses the exact same reserved `message_id` from the first attempt — it is never overwritten by a freshly minted id.
  2. Retrying a send replays the exact persisted subject, body, and PDF bytes from the first attempt — it never re-drafts through the LLM and never regenerates non-deterministic PDF bytes.
  3. Resend's `Idempotency-Key` header is present on every send call, keyed on the reserved `message_id`, and the retry ladder is bounded below Resend's confirmed idempotency retention window.
  4. A send that may have already reached Resend before failing (timeout, 5xx) is never blindly auto-resent past the provider's dedup window — it escalates to a human instead of risking a second email.

**Plans**: 12/12 plans complete

- [x] 20-01-PLAN.md
- [x] 20-02-PLAN.md
- [x] 20-03-PLAN.md
- [x] 20-04-PLAN.md
- [x] 20-05-PLAN.md
- [x] 20-06-PLAN.md
- [x] 20-07-PLAN.md
- [x] 20-08-PLAN.md
- [x] 20-09-PLAN.md
- [x] 20-10-PLAN.md
- [x] 20-11-PLAN.md
- [x] 20-12-PLAN.md

### Phase 21: Durability Proofs & Ops View

**Goal**: Every durability and exactly-once claim made above is demonstrated able to fail, not just shown
passing — and an operator can check "is the queue healthy" as a fact, not a vibe.
**Depends on**: Phase 16, Phase 17, Phase 18, Phase 19, Phase 20 (this phase proves all of them)
**Requirements**: PROOF-01, PROOF-02, PROOF-03, PROOF-04, PROOF-05, OPS-01
**Success Criteria** (what must be TRUE):

  1. Killing a worker mid-run and draining again completes the run; the same test, with the lease-reclaim clause or the attempts-increment removed, demonstrably goes red — a pasted red run proves the proof isn't vacuous.
  2. Redelivering the same inbound event produces exactly one `jobs` row, one run, and one email, proven against a real Postgres — and the same test would fail if dedup were keyed on the RFC `Message-ID` alone (unavailable until after the fetch).
  3. Crashing between Resend accepting a send and the local `sent` commit results in zero second emails, with the persisted `message_id` asserted byte-identical across both attempts — and the same test fails if run against the pre-Phase-20 send path.
  4. An expired lease is reclaimed by a second, genuinely concurrent (real OS thread) worker, and the original worker's late `mark_failed`/reschedule write — not just its `mark_done` — is rejected by the fencing token; the same test fails against the original (pre-fix) claim SQL that cannot reclaim a `leased` row at all.
  5. All four proofs above are registered in `concurrency-proof.yml` and demonstrably run in CI against a real Postgres container — none are silently skipped by the workflow's hard-coded file list.
  6. An operator can view queue depth, oldest-pending-job age, attempts distribution, and the dead-letter list on one page, which surfaces an alarm when job success looks ~100% while `payroll_runs.status='error'` count is nonzero.

**Plans**: TBD
**UI hint**: yes

## Backlog

Captured ideas not yet scheduled into a milestone live in [`backlog.md`](backlog.md). Notable candidates carried forward / deferred from v2 and v3 scope:

- Real-email A5 threading verification (Path-2 inbound proven; the deep header-survival check stays a live-gate task, not a code change)
- Frontend progressive enhancement (no build step); paystub YTD columns; eval-chart restyle away from matplotlib look (all deferred out of v3, todos 260623-02/03/04)
- Custom email domain (send FROM a real address) — documented upgrade path in README
- Additional Medicare 0.9% surtax modeling; SS wage-base straddle exactness (per-employee YTD Medicare ledger) — accepted limitations, tax-completeness features not hardening
- Schema-parity backlog: versioned/ordered migrations + migration-history table, hard deploy gate blocking Render deploy on drift — separate future milestone, needs paid plan or self-managed release step
- **10 dormant `integration`-marked test modules never execute in CI.** `concurrency-proof.yml` is the only workflow with a real Postgres and selects test files BY NAME (2 files); **12** files under `tests/` carry `@pytest.mark.integration`. Phase 16 (D-14) deliberately did NOT widen the gate to fix this — collecting all 12 at once would wake 10 live-DB modules against a shared Postgres with a destructive module-scope reset (`tests/conftest.py:74-93`), which is a large, unbudgeted change to smuggle inside a durability phase. Phase 16 instead adds a NARROW `queueproof` gate for new durability proofs. **The 10 dormant modules are a pre-existing gap and need their own dedicated work:** inventory and classify each, make it reliable under a shared Postgres (or isolate it), then bring it into CI. Files: `test_atomic_persist`, `test_claim_status`, `test_dashboard`, `test_gateway`, `test_ingest`, `test_persistence`, `test_seed_roundtrip`, `test_stuck_run_recovery`, `test_threading`, `test_webhook_dedup_race`.
- v4 out-of-scope, schema-shaped for later if traffic ever changes: per-tenant fairness lanes, priority lanes, adaptive backpressure, circuit breakers (LLM/Resend), an N-concurrent-email load chart, operator authentication (`jobs.business_id`/`priority` are written but unread — each stays a future `ORDER BY` change, not a migration)

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Thin Foundation | v1.0 | — | Complete | 2026-06-21 |
| 2. Walking Skeleton | v1.0 | — | Complete | 2026-06 |
| 2.1. Deterministic Decisioning | v1.0 | — | Complete | 2026-06 |
| 3. Harden the Calc | v1.0 | — | Complete | 2026-06 |
| 4. The Eval, the Proof | v1.0 | — | Complete | 2026-06-22 |
| 5. Dashboard & Delivery | v1.0 | — | Complete | 2026-06-23 |
| 6. Real Integration & Ship | v1.0 | — | Complete | 2026-06-25 |
| 7. Money-Correctness Deepening | v2 | 2/2 | Complete | 2026-06-28 |
| 7.5. Clarification-Reply Field-Regression | v2 | 4/4 | Complete | 2026-06-28 |
| 8. Data-Layer Hygiene & Diagnostics | v2 | 3/3 | Complete | 2026-07-02 |
| 9. Atomic Data Integrity | v2 | 6/6 | Complete | 2026-07-04 |
| 10. Concurrency Proof | v2 | 2/2 | Complete | 2026-07-07 |
| 11. Clarification Round Machine & Alias Learning | v2 | 9/9 | Complete | 2026-07-07 |
| 12. CI Quality Gates | v3 | 4/4 | Complete    | 2026-07-09 |
| 13. Module Structure & Boundaries | v3 | 4/4 | Complete    | 2026-07-10 |
| 14. Full Type-Checking (mypy) | v3 | 10/10 | Complete    | 2026-07-10 |
| 15. Comment Hygiene & Deferred-Polish Triage | v3 | 11/11 | Complete    | 2026-07-13 |
| 16. Queue Substrate & Unblocked Webhook | v4 | 10/10 | Complete    | 2026-07-14 |
| 17. The Pump | v4 | 5/5 | Complete    | 2026-07-15 |
| 18. Failure Policy & Sweep Deletion | v4 | 14/14 | Complete    | 2026-07-16 |
| 19. Webhook Cutover & Durable Ingest | v4 | 12/12 | Complete    | 2026-07-17 |
| 20. Exactly-Once Send | v4 | 12/12 | Complete   | 2026-07-17 |
| 21. Durability Proofs & Ops View | v4 | 0/TBD | Not started | - |
