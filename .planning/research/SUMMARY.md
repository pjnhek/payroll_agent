# Project Research Summary

**Project:** Payroll Agent — v4 Durable Execution
**Domain:** Durable Postgres-backed job queue + in-process worker pool bolted onto a shipped, email-driven payroll pipeline (FastAPI, Supabase Postgres via Supavisor transaction-mode pooling, Render free tier)
**Researched:** 2026-07-13
**Confidence:** HIGH overall — every claim below is traced to a live file:line in this repo or a vendor doc, not inferred.

---

## Executive Summary

Four researchers adversarially validated the already-approved v4 design (`docs/superpowers/specs/2026-07-13-durable-execution-design.md`) against the live codebase and vendor docs. **The verdict: the design is substantially correct, and it needs zero new dependencies** — every primitive (`SELECT … FOR UPDATE SKIP LOCKED`, `gen_random_uuid()`, transactional enqueue, a bounded thread pool, `resend`'s `Idempotency-Key`) is already installed and already running in production on six live tables. `uv add` count: 0. The work is entirely schema, config, worker threads, and — the one genuinely hard piece — teaching the orchestrator to return an explicit `ok`/`retryable`/`terminal` result instead of swallowing every stage failure into `ERROR` and returning `None`.

But the design as written contains real defects, two of them severe enough to sink the milestone's headline claims if shipped as-is. Two researchers independently found, without coordinating, that **the design's own claim SQL can never reclaim an expired lease** (`WHERE state='pending'` never matches a job stuck at `state='leased'` after its worker died) — the exact failure the lease exists to prevent, and the exact scenario the design's own Phase D Proof #4 is supposed to exercise. Two researchers also independently found that **a pump cadence fast enough to be useful (5–10 min) keeps the Render free service permanently awake**, burning ~720–744 of the workspace's 750 free instance-hours/month — a cost the design costed for latency but never for budget. And two researchers found the **"no client is ever emailed twice" claim is false as designed**: Resend's `Idempotency-Key` is bound to the payload, the retry path re-drafts the email via a live LLM call and regenerates non-deterministic PDF bytes, and the repo's own upsert (`emails.py:83-89`) overwrites the very `message_id` the design says to reuse. None of these are exotic — they are the kind of defect only surfaced by tracing argument flow against live source, which is exactly what this research did.

The recommended path is NOT "start with the queue." Architecture research refutes the design's own claim that unblocking the webhook's event loop "cannot be split" from adding the queue — `run_in_threadpool` fixes the event-loop-blocking defect today, with zero schema changes, using a mechanism the codebase already relies on elsewhere. The queue, the pump, the failure/result-contract, and the exactly-once send policy decompose into 7 independently shippable phases, with one hard ordering constraint the design gets backwards: **the pump and the failure policy must land before the webhook is cut over to the queue**, or the cutover ships a window in which the worker silently records success on a payroll that actually failed.

---

## CORRECTIONS TO THE APPROVED DESIGN

Ranked by severity. Every item traced to file:line. This section is the load-bearing part of this research — do not let the roadmap flatten it into "add a queue."

### CRITICAL

**C1 — The claim SQL cannot reclaim an expired lease.** (ARCHITECTURE §4, FEATURES §1 — independently converged)
Design's claim SQL (`design.md:150-153`): `WHERE state = 'pending' AND available_at <= now()`. A job whose worker died holding the lease stays `state='leased'` **forever** and is never reclaimed. This is the exact failure the lease exists to prevent, and it means **the design's own Phase D Proof #4 ("reclaim safety") would fail against the design's own SQL.**
Fix: `WHERE (state='pending' AND available_at <= now()) OR (state='leased' AND leased_until < now())`.

**C2 — Phase ordering ships a durability regression window.** (ARCHITECTURE §7)
Design orders Phase A (full webhook cutover to queue) → B (pump) → C (retry policy/result contract). Between the end of A and the end of C: there is no pump draining future-dated jobs; the orchestrator still swallows stage failures into `ERROR` and returns normally, so **a worker records success on a payroll that actually failed**; and the dashboard sweep is being *kept* "until the queue is proven," so it now races the queue's own lease reclaim on the same run (both fire at ~15 min). **The pump and the failure policy must precede the webhook cutover** — this is a correctness ordering, not a preference.

**C3 — Exactly-once send is broken as designed.** (FEATURES §3, PITFALLS Pitfall 6 — independently converged, four compounding sub-bugs)
- **G1 (payload drift → hard 409, not a silent no-op):** Resend binds the idempotency key to the *payload*; same key + different payload = `409 invalid_idempotent_request` (vendor docs, verified). `delivery.py:118` re-drafts the confirmation body via a live Kimi LLM call on every retry; `delivery.py:136` regenerates PDFs via reportlab's `SimpleDocTemplate`, which stamps a fresh `/CreationDate` + `/ID` — non-deterministic bytes every call. Same key, different payload, on essentially every retry.
- **The repo's own write path destroys the reservation it needs to read:** `insert_email_message`'s upsert (`app/db/repo/emails.py:83-89`) does `ON CONFLICT (...) DO UPDATE SET message_id = EXCLUDED.message_id` — a retry **overwrites** the reserved row's `message_id` with a fresh `uuid4` before the design's "reuse it" logic can ever read it. This is also the reply-threading anchor (`gateway.py:271-273`); overwriting it silently misroutes a client's clarification reply into a brand-new phantom payroll run.
- **G2 (24h key expiry unbounded by the retry ladder):** Resend retains an idempotency key ~24h. The design's retry/backoff ladder has no bound tying it to that window — a dead-lettered job resumed by an operator on Monday, or any backoff schedule that stretches past a day, sends a second payroll email with provider-side dedup silently gone.
- **G3 (`failed` is not proof of non-delivery):** `send_outbound` flips a row to `send_state='failed'` on **any** exception including a timeout *after* Resend accepted the message (`gateway.py:341-345`). The retry guards only recognize `send_state='sent'` as proof of delivery — a `failed` row does not suppress a retry, and if that retry mints a fresh key, the client gets emailed twice.
- Fix requires ALL of: read-before-mint on `send_outbound`; stop overwriting `message_id` in the upsert; treat both `reserved` and `failed` as "may have escaped" (both must reuse the key); deterministic PDF bytes (pin `/CreationDate`/`/ID`); cap total retry age below the confirmed Resend window; the honest published claim is narrower than "never twice" (see below).

### HIGH

**C4 — "Unblock the front door is not shippable before the queue" is false.** (ARCHITECTURE §7)
Design (`design.md:175-176`): *"It cannot be split... Merged."* This conflates two different defects: event-loop blocking (Finding 2) vs. fetch-in-the-request-path availability risk. `await run_in_threadpool(_ingest_sync, raw_body)` fixes the event-loop-blocking defect **today, with zero new schema**, using `starlette.concurrency.run_in_threadpool` — the exact mechanism `pipeline_glue`'s existing sync-`def` wrappers already exploit on purpose. Independently shippable, independently testable (fire 2 concurrent webhooks against a stubbed slow fetch, assert wall-clock ≈ max not sum). It does NOT fix a Resend outage still 502ing the webhook — that's a different, later concern.

**C5 — Keeping `sweep_stranded_runs` alongside the queue is the two-sources-of-truth hazard, literally.** (ARCHITECTURE §7, PITFALLS Pitfall 7)
Two independent status writers, both firing at ~15 min, both authorized to write `payroll_runs.status`, racing on the same run: the sweep flips a stale `extracting` run to `ERROR` (the sanctioned third status writer) at the same moment the queue reclaims the expired lease, re-runs the handler, whose CAS fails against `error` → no-op → job `done`. The design's headline claim ("recovers automatically within minutes, without a human noticing") is defeated by the very safety net meant to back it up. **The sweep must be REPLACED by the dead-letter transition in the same phase the failure policy lands — not "retired once the queue is proven."** This is also a net deletion win: `sweep_stranded_runs`, `find_stranded_unconsumed_replies`, the `runs_list()` sweep block, and the redelivery-reschedule branch all become deletable.

**C6 — The producer/payload inventory is incomplete.** (ARCHITECTURE §2, PITFALLS Pitfall 10)
Design names 3 job kinds and 6 `BackgroundTasks` call sites. Actual grep of `BackgroundTasks` **type annotations** (not just `add_task` call sites — a route can take `background_tasks` and delegate to a helper, which a naive grep misses) finds **8 producers across 3 distinct payload signatures**:
- `operator_resume_bg(run_id, overrides: dict[str, str])` (`runs.py:262`) carries a **dict of business data** with nowhere to live in the design's 3-column job row → needs a 4th job kind (`operator_resume`) + a new `payroll_runs.operator_overrides JSONB` column.
- `resume_pipeline_bg(run_id, inbound: InboundEmail)` carries an **object**, not an identifier → must become an `email_id` FK (rehydrated via the already-existing `pipeline_glue.row_to_inbound`).
- Two producers the design's list misses entirely: `runs.py:475` (the dashboard sweep itself is a producer) and `runs.py:792` → `pipeline_glue.route_reply` → `pipeline_glue.py:127` (an indirect `add_task`, invisible to a `grep add_task` in `runs.py`).
Missing any one of the 8 leaves two competing execution systems, one of which still loses work on restart — the exact bug the milestone exists to kill.

### MEDIUM

**C7 — `lease_token` fencing does not protect the business writes; the design's rule 2 overclaims.** (ARCHITECTURE §4)
Design's rule 2: *"Every completion or failure write must match the `lease_token`."* True, but it only fences the `jobs` row. The orchestrator's actual business writes commit in a *different* transaction, minutes earlier, with no token in scope. The real guarantee comes from `claim_status` (the run-status CAS) + `uq_email_run_purpose_round_epoch` (blocks a second send) + `replace_line_items`'s delete-then-insert (idempotent by value). State this precisely in the README/ops page or repeat the "eval chart was lying" mistake this project already had to correct once.

**C8 — 10-min pump collides with Render's 750 free instance-hours/month.** (ARCHITECTURE §5, PITFALLS Pitfall 2 — independently converged)
A pump cadence under 15 minutes means the service never spins down → ~720–744 h/month against a 750 h/workspace/month cap → six hours of margin, and only if this is the *sole* free web service in the workspace. Blow the budget and free services suspend until next month — the demo dies silently, mid-month, unflagged anywhere in the design. This is an unmade decision dressed as an implementation detail; it must be written down explicitly (see Open Decisions below).

**C9 — No graceful lease release on shutdown.** (ARCHITECTURE §5)
A Render redeploy is routine (several times a day during development). Without releasing held leases in the `lifespan` teardown, every in-flight job strands for a full lease-plus-pump-interval (~25 min). One `UPDATE jobs SET state='pending', lease_token=NULL WHERE id=… AND lease_token=%(token)s` in `worker.stop()` turns a 25-minute stall into a sub-second handoff on every deploy.

### LOW

**C10 — `inbound_events` retention has no named executor.** The design calls for "a byte cap and a retention policy" but names nobody to run it. The pump is the only recurring execution context in the system — it must own retention (`DELETE FROM inbound_events WHERE received_at < now() - interval '30 days'`).

---

## What the design got RIGHT (must survive into the roadmap unchanged)

- `jobs` as transport-state-only, `payroll_runs.status` as the sole business state machine — correct, and it's the milestone's actual thesis. It just needed the enforcement teeth (INVARIANT J-1, CI drift guards) that the architecture research adds.
- `business_id` nullable on `jobs` — correct; sender→business routing happens after the (now-deferred) body fetch.
- The pump is not optional — "durable storage is not durable execution" is the sharpest sentence in the design and is true.
- The reserved `message_id` as a pre-send idempotency key is the best insight in the design — verified against the installed SDK (`resend==2.32.2` ships `SendOptions.idempotency_key`, emits `Idempotency-Key` header).
- "Never mint a fresh uuid4 on retry" — correctly identified as the subtle bug, even though the fix is incomplete as stated (see C3).
- Infrastructure failures stay in `error`, not `needs_operator` — confirmed correct against `/resolve`'s hard requirement on `decision.unresolved_names`.
- No session-level advisory locks, no LISTEN/NOTIFY — correct; both are silently broken under Supavisor transaction-mode pooling.
- Five connections is the ceiling, not forty AnyIO threads — the most under-appreciated constraint, and the design named it first.
- Throughput machinery (priority lanes, fairness, backpressure) explicitly out of scope — right call, schema already shaped to make each an `ORDER BY` change later, not a migration.

---

## Key Findings

### Recommended Stack

**Verdict: add nothing.** Every design primitive is already installed and in live production use: `FOR UPDATE SKIP LOCKED` (PG 9.5+, Supabase ships ≥15), `gen_random_uuid()` (already the PK default on 6 shipped tables via `pgcrypto`), `psycopg[binary,pool]==3.3.4` transactional enqueue, stdlib `threading.Thread` for the worker pool, FastAPI `lifespan=` (currently absent from `app/main.py` — the one new hook), `starlette.concurrency.run_in_threadpool`, and `resend==2.32.2`'s `SendOptions(idempotency_key=...)` (no version bump needed). Three lightweight Postgres-queue libraries were seriously evaluated and rejected: `procrastinate` (requires an async connector — a second connection pool against a 5-connection budget), `pgqueuer` (wants its own CLI worker process — Render free has none), `pgmq` (no fencing token → the zombie-reclaim proof is unimplementable; no unique dedup key → the ingress-idempotency proof is unimplementable). The only real "stack" changes are schema (`jobs` table + `provider_message_id` column) and config (`PUMP_SECRET`, `WORKER_COUNT`, `LEASE_SECONDS`, `MAX_ATTEMPTS`) — both already have first-class, CI-gated machinery in this repo.

**Core technologies (all pre-existing):**
- **Supabase Postgres ≥15**: `FOR UPDATE SKIP LOCKED` claim, `gen_random_uuid()` lease tokens — zero new extension surface.
- **psycopg[binary,pool] 3.3.4**: claim/complete/fail queries reuse the existing transactional discipline; already Supavisor-transaction-mode-safe (`prepare_threshold=None`).
- **stdlib `threading.Thread`, daemon=True**: the worker primitive — NOT `asyncio.Task` (all downstream work is blocking sync I/O) and NOT `ThreadPoolExecutor` (adds a dispatcher thread for zero safety gain over N self-driving claim loops).
- **FastAPI `lifespan=`**: start/stop N daemon worker threads; `app/main.py` has none today.
- **resend 2.32.2**: `SendOptions(idempotency_key=...)` already present at the pinned version — do not bump during this milestone.

### Expected Features

**Must have (P1, table stakes for the word "durable" to be earned):**
- Result contract (`ok`/`retryable`/`terminal`) — the hard prerequisite; nothing else in the milestone can be built without it.
- `jobs` table + SKIP LOCKED claim + lease + lease-token fencing + **the stale-lease reaper fix (C1)**.
- Svix-event-ID-keyed idempotent enqueue; RFC `Message-ID` dedup retained as a second, deeper gate.
- The pump — authenticated endpoint + cron; without it the rest is durable storage that never executes.
- Backoff + jitter + attempt cap → dead-letter, ladder bounded **inside** Resend's confirmed idempotency window.
- Exactly-once send: all parts of C3's fix (reuse reserved `message_id`, replay persisted payload without recomposing, deterministic PDF bytes, split the two distinct 409 sub-codes into retryable vs. terminal, persist `provider_message_id`, escalate stale `reserved`/`failed` rows to a human rather than auto-resend).
- Every `BackgroundTasks` producer migrated — all 8, not the design's 6 (C6).
- Atomic CAS claim for the initial pipeline (`run_pipeline` currently writes `received → extracting` unconditionally — a reclaimed job could otherwise run it twice, concurrently).
- The ops page (7 signals: queue depth, oldest-pending age, in-flight count, expired-lease count, attempts distribution, dead-letter list, stale-`reserved`-row list).
- The four durability proofs, on the existing real-Postgres barrier harness — each proven able to **fail** via a named falsifying mutation.
- The honest guarantee, published in README + ops page (narrower than "never twice" — see below).

**Should have / differentiators:** the falsification harness itself (this repo's identity is "every claim has a proof behind it"); enforcing `jobs`-as-transport-only via a CI drift guard, not just a stated intent; persisting `provider_message_id` as durable send evidence (today only logged).

**Defer (v2+), named anti-features — all four researchers agree:** priority lanes, per-tenant fairness/weighted round-robin, adaptive backpressure, circuit breakers (LLM/Resend), autoscaling worker pool, distributed tracing, a full metrics stack (Prometheus/Grafana), an N-concurrent-email load chart, a separate worker process. Real traffic is ~1 payroll email/client/week; every one of these is machinery for load that will never arrive. The schema already carries `priority` and `business_id` unread, so each remains a future `ORDER BY` change, not a migration, if traffic characteristics ever change.

### Architecture Approach

`jobs` is transport state only (enforced by a CI drift guard, not just documented intent); `payroll_runs.status` remains the sole business state machine. The queue is coarse-grained — one job kind per orchestrator entry point (4 kinds: `ingest`, `run_pipeline`, `resume_reply`, `operator_resume`), never per-stage, because there is no durable checkpoint between the pipeline's internal stages and per-stage granularity would force a next-status onto the job row (the exact forbidden duplication). Worker count is a tuned constant (2) derived from the 5-connection budget, not a scaling knob. The claim/lease/fencing protocol is the one piece of real machinery; everything else — enqueue atomicity, the pump, the failure taxonomy — composes around it using patterns (transactional co-tenancy with `conn.transaction()`, the `claim_status` CAS idiom) this repo has already proven correct in production.

**Major components:**
1. `app/queue/` (new package) — `enqueue()`, `claim_one()`, `settle()`, `drain_once()`; owns every `UPDATE jobs`.
2. `app/queue/handlers/{ingest,pipeline}.py` — the verbatim-moved DATA-02 ingest transaction; the rewind-preamble + CAS wrapper around the orchestrator.
3. `app/routes/internal.py` — `POST /internal/pump` (authenticated, bounded drain, returns real counts) + `GET /internal/queue` ops view.
4. The orchestrator's new result contract — `JobResult = Ok | Retryable(reason) | Terminal(reason)`, replacing the current swallow-and-return-None.

### Critical Pitfalls

1. **Durable storage that is never durable execution** — Render free wakes only on inbound HTTP; any in-process timer (asyncio sleep loop, APScheduler, `threading.Timer`) sleeps with the dyno and dies silently. Avoid: the pump is non-negotiable; ban in-process timers with a CI grep guard.
2. **The pump/free-tier collision (C8 above)** — must become a written decision with the arithmetic in the phase doc, not an unexamined config default.
3. **Connection-pool starvation** — `max_size=5` is the true ceiling; an LLM call held inside a checked-out connection is how you hit it. Enforce `worker_concurrency + reserved_headroom ≤ max_size` as a startup assertion.
4. **Supavisor transaction-mode pooling breaks session state silently** — advisory locks and LISTEN/NOTIFY don't error, they just quietly do nothing; only row leases + CAS survive port 6543.
5. **Vacuous durability tests** — this exact failure already happened once (Phase 10's concurrency proof passed even with its own safety clause deleted, because 8 threads were driven through a serialized async route). Every Phase D proof must be demonstrated able to fail via a named mutation, driven through the sync repo seam directly under a `threading.Barrier`, not through an HTTP route.

---

## Implications for Roadmap

Architecture research proposes **7 independently-shippable phases** with one hard, non-negotiable dependency order: **2 → 3 → 4 → 5** (queue substrate → pump → failure policy → webhook cutover). Phase 1 is independent of everything and should ship first regardless. Phase 6 (exactly-once send) is independent of phase 5 and can run in parallel. Phase 7 (proofs) is last by definition.

### Phase 1: Unblock the event loop
**Rationale:** Refutes the design's false "cannot be split" claim (C4). Needs zero new schema — pure risk reduction before the riskier queue work begins.
**Delivers:** `webhook.py:inbound` wraps its blocking body in `run_in_threadpool`; `MAX_WEBHOOK_BODY_BYTES` cap added.
**Addresses:** Finding 2 (event-loop blocking) from the design.
**Avoids:** Pitfall — conflating availability risk with event-loop blocking; keeps this change independently testable and independently shippable.

### Phase 2: Queue substrate + ONE producer
**Rationale:** Learn leases/pool/lifecycle on the cheapest, most observable surface (operator retrigger) — not the money path.
**Delivers:** `jobs` table (with the C1 stale-lease-reclaim fix baked into the claim SQL from day one), `app/queue/{worker,dispatch}.py`, `lifespan` hook, ONE producer (`retrigger`) cut over. BackgroundTasks coexists safely for exactly this one phase.
**Uses:** psycopg3, stdlib threading, FastAPI lifespan — all from STACK.md.
**Implements:** the claim/lease/fencing protocol (ARCHITECTURE §4).

### Phase 3: The pump
**Rationale:** MUST precede the webhook cutover (C2) — after cutover, a lost job is a lost payroll.
**Delivers:** `POST /internal/pump` (hmac-authenticated, bounded drain, real counts returned); `.github/workflows/pump.yml` (replaces `keepalive.yml` — net deletion); the pump cadence vs. 750h decision (C8) written down explicitly with the arithmetic.
**Avoids:** Pitfall 1 (durable storage, never durable execution) and Pitfall 2 (the free-tier collision).

### Phase 4: Failure policy + CAS + sweep deletion
**Rationale:** MUST precede the webhook cutover (C2) — otherwise a transient LLM 503 on a real payroll email becomes a permanent, unretried ERROR.
**Delivers:** `JobResult` classification (retryable vs. terminal, default-terminal for unknowns); `run_pipeline`/`resume_pipeline` return `JobResult` instead of `None`; the rewind-preamble CAS fix for `run_pipeline`; **deletion** of `sweep_stranded_runs`, `find_stranded_unconsumed_replies`, and the `runs_list()` sweep block (C5).
**Avoids:** Pitfall 8 (error-swallowing orchestrator) and Pitfall 7 / C5 (two sources of truth via the racing sweep).

### Phase 5: Webhook cutover + raw inbox + re-keying
**Rationale:** The riskiest change (new schema + threads + leases) now lands on a webhook that already has a pump and a failure policy backing it, not on top of a hole.
**Delivers:** `inbound_events` durable raw inbox (Svix-event-ID keyed, byte-capped, retention-policed by the pump per C10); `app/queue/handlers/ingest.py` (the verbatim-moved DATA-02 transaction); all remaining `BackgroundTasks` producers migrated — **all 8, not 6** (C6), including the two the design's list misses (`runs.py:475`, `runs.py:792`).
**Addresses:** Finding 1 (durable-in-memory-only) fully; the C6 producer-inventory gap.

### Phase 6: Exactly-once send
**Rationale:** Independent of Phase 5 — could land in parallel.
**Delivers:** the full C3 fix set — read-before-mint on `send_outbound`, stop overwriting `message_id` in the upsert, treat both `reserved` and `failed` as "may have escaped," deterministic PDF bytes, split the two 409 sub-codes, persist `provider_message_id`, retry ladder bounded below Resend's confirmed idempotency window, the honest narrowed published guarantee.
**Avoids:** Pitfall 6 (all five variants — G1 through G4 plus the dead `send_state` parameter, which should be deleted in a small pre-flight commit before anyone reasons about send state).

### Phase 7: Proofs + ops view
**Rationale:** Last by definition — proves everything above actually holds.
**Delivers:** the four durability proofs, each with a demonstrated red (falsifying mutation named and executed per proof, per PITFALLS Pitfall 12); `GET /internal/queue` ops view (7 signals); **widen `concurrency-proof.yml`** — it is the only CI workflow with a real Postgres and currently hard-codes a single test file, so new durability tests are silently never run unless this is fixed.
**Avoids:** Pitfall 12 (vacuous durability tests) — this repo has already shipped one vacuous "proof" once (Phase 10); do not repeat it.

### Phase Ordering Rationale

- **2 → 3 → 4 → 5 is forced, not preferred.** Cutting the webhook over to the queue (5) before the pump exists (3) or the failure policy lands (4) creates the exact regression window in C2: jobs commit reliably and are never executed, or execute and silently report success on failure.
- **Phase 1 is free and should ship immediately regardless of the rest of the roadmap** — it fixes a real, independently-provable defect with zero schema risk.
- **Phase 6 is decoupled from 5** because the exactly-once-send fix touches `gateway.py`/`delivery.py`/`emails.py`, not the ingest path — it can be planned and executed by a different wave.
- **This ordering directly avoids Pitfall 7/C5** (two sources of truth via the sweep racing the queue) by deleting the sweep in the same phase the failure policy lands, not deferring the deletion to "once the queue is proven."

### Research Flags

Needs deeper research/scrutiny during planning:
- **Phase 6 (exactly-once send):** Resend's idempotency-key retention window needs re-confirmation against current vendor docs before the retry-ladder cap is finalized (flagged as Gap G-1 in PITFALLS — not fully verified in this pass). Do not finalize a backoff schedule before this number is confirmed.
- **Phase 3 (the pump):** the pump-cadence-vs-750h decision is a genuine open tradeoff requiring a human call (see below) — plan this phase with the decision already made, not deferred into execution.
- **Phase 5 (webhook cutover):** the two-layer dedup argument (Svix event ID vs. RFC Message-ID) is subtle and worth a design-doc callout during planning so the "why both, not just one" reasoning survives into the PR.

Standard patterns (skip deep research-phase):
- **Phase 2 (queue substrate):** the claim/lease/fencing SQL is fully specified in ARCHITECTURE.md §4 with the C1 fix already incorporated — this is transcription, not design.
- **Phase 4 (failure policy):** the result-type pattern and classification table are fully specified in FEATURES.md §2 and PITFALLS Pitfall 8.
- **Phase 7 (proofs):** the falsification discipline is fully specified in PITFALLS Pitfall 12, including the exact vacuous-vs-real test shape for each of the 4 proofs.

---

## Open Decisions Requiring the Human

**Pump cadence vs. the 750-instance-hour free-tier budget (C8).** This is a latency/cost tradeoff the design never surfaced, and it cannot be resolved by further research — it needs an explicit choice:

| Option | Recovery latency | Instance-hours/month | Tradeoff |
|---|---|---|---|
| **10-min pump (architecture's recommendation)** | ~10 min | ~720–744 (6h margin against 750h cap) | Also eliminates cold-start latency on real webhooks entirely. **Requires: exactly one free web service in the Render workspace** — a new, currently-unwritten deploy constraint. |
| 20-min+ pump | ~20–45 min | ~54 (service sleeps between pumps) | Cheap, large margin, but the milestone's "recovers within minutes" claim weakens materially. |
| Duty-cycled pump (frequent during demos, sparse otherwise) | variable | variable | Makes the guarantee time-of-day dependent — hard to state honestly; not recommended by any researcher. |

**Recommendation surfaced by research: take option 1**, add "exactly one Render free web service in this workspace" to the milestone's written constraints, and budget the arithmetic explicitly in the Phase 3 plan doc. This is the single most consequential unresolved tradeoff in the whole milestone and should be decided before Phase 3 is planned in detail.

**The honest guarantee wording (a related, smaller decision).** The design's current claim — "no client is ever emailed twice" — is not promisable as stated (C3). The narrowed, defensible replacement, surfaced by FEATURES.md, is:

> *A payroll confirmation is sent at most once per approved run, per epoch, within Resend's confirmed idempotency window. Delivery is anchored on a durable pre-send reservation and deduplicated by the provider on that key. Beyond that window — or after an operator retrigger, which deliberately opens a new epoch — provider-side deduplication no longer applies and a resend is possible. A stale send-state row is therefore escalated to a human rather than retried automatically.*

This narrowing needs the human's sign-off before it goes in the README/ops page, since it changes what the milestone publicly promises.

---

## Anti-Features — build none of these

All four researchers agree, independently, that the following are machinery for load that will never arrive at ~1 payroll email per client per week. The schema is deliberately shaped (`priority`, `business_id` columns present but unread) so each remains a future `ORDER BY` change rather than a migration, should traffic characteristics ever change:

- **Priority lanes** — nothing to prioritize against at this queue depth.
- **Per-tenant fairness / weighted round-robin** — tenants never contend at this scale.
- **Adaptive backpressure** — the producer (Resend's webhook) cannot be pushed back on; the byte cap is the only real admission control available.
- **Circuit breakers (LLM/Resend)** — a breaker protects a shared downstream from your own stampede; two workers doing one email/week are not a stampede, and a breaker adds a new stateful failure mode (stuck-open = silent blackhole) worse than the one it prevents.
- **Autoscaling / dynamic worker pool** — Render free has one instance and five connections; worker count is a tuned constant, not a scaling knob.
- **Distributed tracing (OTel/Jaeger)** — there is one service; `run_id` + the existing `error_detail` already correlate everything.
- **A full metrics stack (Prometheus/Grafana)** — would need a second always-on service Render free doesn't offer, to graph a queue whose depth is 0 six days a week.
- **The N-concurrent-email load chart** — would prove a property nobody is testing this system on, and invites a throughput comparison a free-tier single instance necessarily loses.
- **A separate worker process** — Render free has no worker service type; in-process threads + the pump is the only shape that actually executes.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Every claim verified against PyPI JSON API + live production evidence in this repo (pgcrypto/`gen_random_uuid()` already running on 6 tables). Zero speculation. |
| Features | HIGH on Resend idempotency semantics (fetched from vendor docs) and all repo-source claims; MEDIUM on the general Postgres-queue-canon corroboration (multi-source, no single authority). |
| Architecture | HIGH on integration points (traced against live source at commit `9975a86`); MEDIUM on the exact 750h Render budget figure — the arithmetic is certain, the cap itself should be re-confirmed against current Render docs before committing to a cadence. |
| Pitfalls | HIGH on code-traced findings (every smoking gun cites a live line read directly); HIGH on Supavisor/pgbouncer transaction-mode semantics and Render free-tier accounting; MEDIUM on Resend's exact `Idempotency-Key` retention window (SDK support is verified; the provider's dedup *window* itself is flagged as an unverified gap — G-1). |

**Overall confidence:** HIGH — this is unusually well-grounded research; nearly every claim is either a direct source-code citation or a vendor-doc citation, and the two most severe corrections (C1, C3) were reached independently by different researchers using different methods.

### Gaps to Address

- **Resend's exact `Idempotency-Key` retention window (24h is stated by researchers but flagged as not independently re-verified in this specific pass — G-1 in PITFALLS).** Confirm against Resend's docs before finalizing the Phase 6 backoff/retry-age cap. Do not design that cap "blind."
- **The precise current Render 750-hour cap** should be re-confirmed against Render's live docs immediately before Phase 3 is planned — the arithmetic and the general shape are certain (multiple sources agree), but pinning the exact number to a dated citation matters given it drives an irreversible-feeling architectural decision (single free service in the workspace).
- **The `operator_resume` dedup_key discriminator** (C6 / ARCHITECTURE §3) — an operator may legitimately re-resolve a `needs_operator` run with a different name-mapping without an epoch bump; the current `dedup_key` scheme doesn't yet have a clean answer for whether the second resolve is a new job or silently swallowed by `ON CONFLICT DO NOTHING`. Flagged as an explicit open question in ARCHITECTURE.md §3 — resolve during Phase 2/5 planning.

## Sources

### Primary (HIGH confidence)
- This repository, read directly at commit `9975a86` and later — `app/db/schema.sql`, `app/db/supabase.py`, `app/db/repo/{runs,emails,jobs}.py`, `app/pipeline/{orchestrator,delivery,pdf}.py`, `app/email/gateway.py`, `app/routes/{webhook,runs,demo,pipeline_glue}.py`, `app/main.py`, `pyproject.toml`, `.github/workflows/{keepalive,concurrency-proof}.yml`.
- Resend — Idempotency Keys vendor documentation (fetched 2026-07-13): 24h retention, 256-char limit, identical-payload replay vs. `409 invalid_idempotent_request` vs. `409 concurrent_idempotent_requests`.
- PyPI JSON API — fastapi 0.138.0/0.139.0, pydantic 2.13.4, psycopg 3.3.4, resend 2.32.2/2.33.0, procrastinate 3.9.0, pgqueuer 1.1.1, pgmq 1.1.2. Verified 2026-07-13.
- PostgreSQL release history — `SKIP LOCKED` since 9.5, `gen_random_uuid()` built-in since 13 / via pgcrypto at any version.
- PgBouncer docs + issue #655 — `LISTEN` broken under transaction-mode pooling; directly applicable to Supavisor port 6543.
- Render docs — free-tier 750 instance-hours/month, 15-min idle spin-down, inbound-HTTP-only wake, ephemeral filesystem.

### Secondary (MEDIUM confidence)
- Postgres `SKIP LOCKED` queue canon (lease/visibility timeout, claim-token fencing, backoff+jitter) — corroborated across multiple independent community implementations, no single authority.
- The exact current Render 750h cap and Resend's exact 24h key retention — both flagged for re-confirmation against live vendor docs before Phase 3/6 are finalized.

### Repo memory (project-history corroboration)
- Phase 10's concurrency proof was verified-but-vacuous (threads serialized through an async route; passed even with the safety clause deleted) — the direct precedent motivating PITFALLS Pitfall 12's falsification discipline for Phase 7.

---
*Research completed: 2026-07-13*
*Ready for roadmap: yes*
