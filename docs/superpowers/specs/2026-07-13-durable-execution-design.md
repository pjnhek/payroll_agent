# v4 — Durable Execution

**Status:** Approved design, **revised 2026-07-14 after adversarial research** (4 parallel researchers + a Codex review)
**Supersedes:** the informal "queue + split ingestion/processing" framing, and the first draft of this document

> **Revision note.** The first draft of this spec contained five defects, listed under
> [Corrections](#corrections-to-the-first-draft). Two researchers independently found the same bug in its
> claim SQL. Everything below is the corrected design.

---

## The claim

The first draft promised:

> ~~No accepted email is ever lost. Every failure recovers automatically within minutes. And no client is
> ever emailed twice.~~

Research proved the second and third clauses false as written. **The honest claim:**

> **No accepted email is ever lost.** Once the webhook returns 200, the work is durable in Postgres and
> survives any process death.
>
> **Every failure recovers automatically within ~30 minutes**, best-effort — bounded by the pump cadence,
> which is in turn bounded by Render's 750 instance-hour/month free-tier budget. Operator retry is the
> documented fallback.
>
> **A client is sent at most one confirmation per approved run, per epoch**, anchored on a durable pre-send
> reservation and deduplicated provider-side within Resend's 24-hour idempotency window. Past that window a
> stale reservation escalates to a human — it is never auto-resent.

Exactly-once delivery is not achievable. It is the Two Generals problem, not a library gap. Narrowing the
claim to what is true is the same move this repo already made once, when it discovered its eval chart was
lying.

This is deliberately **not** "survive 100x traffic." Real traffic is ~1 payroll email per client per week.

---

## Why this milestone exists

An adversarial audit flagged two ways the system breaks under pressure. They are **different problems with
different fixes** — a queue only addresses one.

### Finding 1 — Stage two is durable in memory only

The pipeline is already off the request path (`app/routes/webhook.py:309` schedules a `BackgroundTask`), and
the sync `def` wrappers (`app/routes/pipeline_glue.py:195,210`) run in the AnyIO threadpool, not on the loop.
That part is fine.

What is not: **a `BackgroundTask` is an object in process memory.** A Render redeploy, a 15-minute idle
spin-down, or an OOM vaporizes it, and nothing on disk records that the work was owed.

Recovery today is entirely *externally triggered*: `repo.sweep_stranded_runs` fires only on a dashboard page
load (`app/routes/runs.py:464-465`); webhook redelivery re-schedules a lost *reply* (`webhook.py:225-265`);
operator retrigger is manual (`runs.py:266-380`). A lost **initial** run that is never redelivered and whose
dashboard is never visited stays lost.

### Finding 2 — The webhook blocks the event loop

`inbound()` is `async def` (`webhook.py:30`) and performs synchronous, un-awaited blocking I/O directly on the
loop: `gateway.parse_inbound()` (`webhook.py:96`) makes a **synchronous Resend API call** to fetch the body
(`app/email/gateway.py:158-175`), and the ingest transaction (`webhook.py:139`) is synchronous psycopg.

Every inbound email freezes the whole service for a third-party round-trip plus a multi-query transaction.
**A queue does not fix this** — the blocking is in front of wherever the queue sits.

### Finding 3 — The capacity ceiling is 5, not 40

The AnyIO threadpool holds ~40 threads; the Postgres pool is `max_size=5` (`app/db/supabase.py:57-68`). Worker
count is sized against **connections**: `workers + 2 ≤ max_size` ⇒ **2 workers**, reserving headroom for
ingest, approvals, and dashboard reads. A worker holding a pooled connection across a 45-second LLM call is
deadlock-by-budget.

Corollary, now load-bearing: `uvicorn` runs **single-process** (`Dockerfile:61`). Adding `--workers N` would
multiply both the pool and the worker threads per process and silently blow the budget.

---

## The constraint that shapes everything: durable storage ≠ durable execution

Render free has **no background-worker service type**, no Redis, an ephemeral filesystem, and it spins down
after 15 idle minutes. **Only inbound HTTP wakes it** — internal timers do not.

A naive queue drained by an in-process worker therefore has a fatal hole: the dyno sleeps, the worker dies, the
lease expires, the job becomes eligible — **and no process exists to claim it.** A retry scheduled with a
future `available_at` has the same problem. The existing keep-alive runs twice a week and drains nothing
(`.github/workflows/keepalive.yml:16-20`).

**Resolution: an authenticated pump endpoint, hit by cron.** And the cadence is a **budget** decision, not just
a latency one — a fact the first draft missed entirely.

### The 750-hour math

Render free grants **750 instance-hours/month/workspace**; hours burn whenever the service is awake, and it
sleeps 15 minutes after its last request. So duty cycle ≈ `15 ÷ cadence`:

| Cadence | Awake | Hours/month | Recovery latency |
|---|---|---|---|
| 5–10 min | ~100% | **~730 / 750** ⚠️ no headroom; blowing it **suspends the service until next month** | minutes |
| **30 min (CHOSEN)** | ~50% | **~365** | **≤ 30 min** |
| 60 min | ~25% | ~182 | ≤ 60 min |

**Decision: 30 minutes.** Half the budget, real headroom for inbound traffic and redeploy churn. The cadence is
a cron schedule plus an env var — not architecture — and the duty-cycle math and the 750h ceiling get written
into the README so the next reader can dial it knowingly.

The pump is the **primary** execution trigger, not a redundancy: on a cold-started instance the worker threads
may not even exist when a retried job's `available_at` matures. The pump and the worker threads must therefore
share **one** `drain_once()` implementation.

---

## Architecture

### Two state machines, one authority — INVARIANT J-1

- **`payroll_runs.status` is the sole business state machine.** Canonical, mirrored into a SQL CHECK, guarded
  by a CI drift test (`app/models/status.py:1-7`, `app/db/schema.sql:69-86`).
- **`jobs` is transport state only.** A job row records *that an operation is owed and who owns it now* —
  never *what payroll status comes next*.

**INVARIANT J-1:** every job handler's first durable action is a `claim_status(expected → next)` CAS. **A
failed CAS is a SUCCESSFUL job (`done`), not a retry.** This converts at-least-once job delivery into
at-most-once state advance. And because the handler derives its own transition from the run's current status,
the job row never *needs* to carry one — so it must not have one.

**The crux the first draft overclaimed:** `lease_token` fences the **jobs row only**. The business writes
commit minutes later in a different transaction; they are fenced by `claim_status`,
`uq_email_run_purpose_round_epoch`, and `replace_line_items`' delete-then-insert. **The lease is an
optimization; the CAS is the correctness.**

### The `jobs` table

| Column | Purpose |
|---|---|
| `id` | PK (`gen_random_uuid()` — `pgcrypto` already live, `schema.sql:13`) |
| `kind` | `ingest` \| `run_pipeline` \| `resume_reply` \| `operator_resume` — an idempotent operation |
| `dedup_key` | UNIQUE. Enqueue is `ON CONFLICT DO NOTHING` |
| `run_id` | nullable — an `ingest` job has no run yet |
| `business_id` | nullable — **sender routing happens after the body fetch** (`webhook.py:195-220`), which now lives in the worker, so the tenant key is unknown at ingress. Backfilled by the ingest job. |
| `priority` | written, **not read** |
| `available_at` | claimable-after (drives backoff) |
| `attempts` | incremented **at claim**, so a poison job that kills its worker before it can report failure is still bounded |
| `state` | `pending` \| `leased` \| `done` \| `dead` |
| `lease_token` | uuid, rotated on every claim |
| `leased_until` | lease expiry |

`priority` and `available_at` exist from day one so fairness and priority lanes stay a later `ORDER BY` change
rather than a migration. **We do not build that logic now.**

### The claim protocol — CORRECTED

```sql
-- Short transaction. Claims and commits the lease, then gets out of the way.
UPDATE jobs SET
  state        = 'leased',
  lease_token  = gen_random_uuid(),
  leased_until = now() + interval '5 minutes',
  attempts     = attempts + 1
WHERE id = (
  SELECT id FROM jobs
  WHERE available_at <= now()
    AND (
      state = 'pending'
      OR (state = 'leased' AND leased_until < now())   -- ← RECLAIM AN EXPIRED LEASE.
    )                                                   --   The first draft omitted this and
  ORDER BY priority, available_at                       --   would have stranded every job whose
  FOR UPDATE SKIP LOCKED                                --   worker died holding the lease.
  LIMIT 1
)
RETURNING *;
```

Three rules that make this safe:

1. **The claim transaction never spans real work.** It commits before any LLM, PDF, Resend, or DB-heavy call.
   Holding it would pin one of five connections for minutes and is incompatible with Supavisor
   transaction-mode pooling.
2. **Every completion *and failure* write must match the `lease_token`.** The forgotten fence is
   `mark_failed`/`reschedule`, not `mark_done` — a zombie worker rescheduling a job another worker already
   completed is the subtle variant.
3. **No session-level advisory locks and no LISTEN/NOTIFY.** Under transaction-mode pooling these fail
   *silently*. Row leases and CAS only. Guard by CI grep, because a session-mode CI container cannot fail the
   test that would catch it.

### Graceful shutdown

On `lifespan` shutdown, workers release their leases (set `state='pending'`, clear the token). Without this, a
routine redeploy strands every in-flight job for the full lease duration.

---

## Build order — 7 phases, each independently shippable

The first draft's ordering shipped a **regression window**: landing the queue before the failure contract means
the worker records **success on a failed payroll** (the orchestrator writes `ERROR` and returns *normally*,
`orchestrator.py:235-247`), while the old sweep races the new queue with both firing at ~15 minutes.

**Forced order: the pump and the failure policy precede the webhook cutover.**

1. **Unblock the loop.** `await run_in_threadpool(_ingest_sync, raw_body)`. **Zero new schema.** The route keeps
   `async def` because HMAC verification needs `await request.body()` over the raw bytes.
2. **Queue substrate + ONE producer** (`retrigger` — the lowest-risk, already-manual path). Jobs table, claim
   protocol, 2 worker threads via `lifespan`.
3. **The pump.** Authenticated endpoint + 30-min cron. Shares `drain_once()` with the workers.
4. **Failure policy + CAS + delete the sweep.** The result contract; backoff; dead-letter; J-1.
5. **Webhook cutover + raw inbox + Svix re-keying.** The Resend fetch moves into the worker.
6. **Exactly-once send.**
7. **Proofs + ops view.**

### Why "unblock the front door" IS independently shippable

Codex asserted it wasn't, and the first draft accepted that. **It's wrong.** It conflated two distinct defects:
*event-loop blocking* and *fetch-in-the-request-path*. The first is fixed by `run_in_threadpool` with no schema
at all, using the same mechanism `pipeline_glue`'s sync wrappers already exploit. Splitting them lets the risky
schema/worker/lease work land on a webhook already proven good under load.

### Deleting the sweep is not optional

Keeping `sweep_stranded_runs` alongside the queue **is** the hazard: two status writers, both firing at ~15
minutes, and the sweep wins by flipping a run to `ERROR` exactly as the queue reclaims it — defeating the
headline claim with its own safety net. It must be **replaced** by the dead-letter transition in phase 4, not
"retired later." Net effect: a **deletion of three recovery hacks**, including the
dashboard-page-load-as-cron block.

---

## Failure policy

The orchestrator currently catches stage failures, writes `ERROR`, and **returns normally**
(`orchestrator.py:235-247,850-859`) — so a worker wrapping it records success. Retry cannot be bolted on
outside it.

Stages return an explicit **result type** (not an exception hierarchy — the orchestrator already swallows
exceptions, and the same Resend 409 can be retryable or terminal depending on context, so classification is
contextual, not type-intrinsic). The default is **`Terminal`** — the safest default in a money system.

- **`ok`** — including **`request_clarification`**. This is the trap: a deterministic gate deciding to clarify
  is a *success*, not a failure. A worker that retried it would email the client the same question five times.
- **`retryable`** — provider 429/5xx/timeout. Exponential backoff + jitter via `available_at`; attempt cap →
  `dead`, surfaced to the operator.
- **`terminal`** — validation failure, business-logic stop.

**Infrastructure failures stay in `error` with a durable retrigger — not `needs_operator`.** `needs_operator` is
a settled gate awaiting a human decision, and the resolve route requires `decision.unresolved_names`
(`runs.py:203-213`); an LLM timeout during extraction has no decision, so parking it there produces a run the
operator UI cannot service.

**Ops alarm for the swallowing bug:** `job success ≈100% while status='error' > 0`.

---

## Exactly-once send — REDESIGNED

The first draft said: *"pass the reserved `message_id` to Resend as the idempotency key; reuse it on retry."*
**That does not work.** Three independent defects:

1. **Resend binds the key to the PAYLOAD.** Same key + different payload = **HTTP 409
   `invalid_idempotent_request`** — a hard error, not a silent dedup. (Verified against Resend's docs. Keys are
   retained **24 hours**; identical payload + same key returns the original id without resending.)
2. **Retries drift the payload.** `delivery.py:120` re-runs `compose_confirmation` — a **live LLM draft** — and
   the PDFs are regenerated by reportlab, which stamps a fresh `/CreationDate` and `/ID` into every document.
   Different bytes every attempt.
3. **The repo's own upsert erases the reservation.** `app/db/repo/emails.py:85`:
   `ON CONFLICT (run_id, purpose, round, epoch) DO UPDATE SET ... message_id = EXCLUDED.message_id`. Meanwhile
   `gateway.py:274` mints a fresh `uuid4` on every call. **The write path overwrites the very row the retry
   needs to read.** And that synthetic id is, per the code's own comment, *"the SOLE routing anchor"* for reply
   threading — so a naive retry doesn't merely double-email, it **orphans the client's reply into a brand-new
   payroll run.**

### The corrected mechanism

1. **Read before mint.** On retry, load the existing `reserved` (or `failed`) row and reuse its `message_id`.
   Only mint a `uuid4` when no row exists.
2. **Stop the upsert from overwriting `message_id`.** Remove it from the `DO UPDATE SET` list.
3. **Replay the persisted payload — never re-derive it.** The reserved row already stores `subject`,
   `body_text`, and `to_addr`. A retry must **never** re-draft via the LLM.
4. **Make PDF bytes deterministic** (pin reportlab's invariant mode), or the attachment alone drifts the
   payload into a 409.
5. **`failed` is not proof of non-delivery.** `gateway.py:341-345` flips to `failed` on *any* Resend exception —
   including a timeout **after** the mail was accepted. `failed` must reuse the key too; today the retry guard
   only recognizes `sent` (`delivery.py:88`).
6. **Bound the retry ladder below 24 hours.** Past the provider window there is no dedup at all — escalate to a
   human, never auto-resend.
7. **Pre-flight cleanup:** `send_outbound(send_state=...)` is a dead parameter — both callers pass `"sent"`,
   the function hard-codes `"reserved"` (`gateway.py:286`). A loaded gun in the exact function phase 6
   rewrites. Delete it first.

### The residual, stated plainly

An operator **retrigger** bumps `reply_epoch` by design (Phase 11 / CLAR2-07), which mints a new key under
`uq_email_run_purpose_round_epoch` (`schema.sql:279`). **A retrigger can therefore legitimately send a second
email.** That is intended behavior, not a bug — and it is precisely why the claim is *"at most once per
approved run, per epoch"* rather than the flat "never twice" the first draft promised.

---

## Proofs — and how each one goes vacuous

This repo has already shipped a "concurrency proof" that passed while proving nothing: its threads serialized
through an async route and never actually raced. Every proof below therefore names its **vacuous twin** and the
mutation that must make it go red.

| # | Proof | Vacuous if… | Must assert |
|---|---|---|---|
| 1 | Kill the worker mid-run → run completes | the job never actually leased | the reclaim path fires; `attempts` incremented |
| 2 | Redeliver the same Svix event → one job, one run, one email | dedup keyed on something present only post-fetch | exactly one `jobs` row survives `ON CONFLICT` |
| 3 | Crash between Resend-accept and `sent` commit → **no second email** | it passes against a fake gateway **while defect 3 above is fully intact** | the persisted `message_id` is **byte-identical** across attempts |
| 4 | Expired lease → second worker claims → zombie's write rejected | the claim SQL can't reclaim a `leased` row at all (**the first draft's bug**) | the zombie's `mark_failed` is fenced, not just `mark_done` |

**Three non-negotiables:** every proof ships with a pasted red run; races drive the **sync seam** under a
`threading.Barrier`, never an HTTP route; and **the new test file must be added to `concurrency-proof.yml`** —
it is the only workflow with a real Postgres and it hard-codes its test files by name
(`concurrency-proof.yml:89`). Three of the four proofs need a real database. Land them outside that line and
**they never run.**

Plus an ops view: queue depth, oldest-pending age, attempts, dead-letter list.

---

## Corrections to the first draft

For the record — what adversarial research changed, ranked by severity.

| # | Defect | Found by |
|---|---|---|
| 1 | **Claim SQL could not reclaim an expired lease** (`WHERE state='pending'` only). The design's own Proof #4 would have failed against its own SQL. | **2 researchers, independently** |
| 2 | **Pump cadence collides with the 750-hour free-tier budget.** Latency was costed; hours were not. | 2 researchers |
| 3 | **Exactly-once send broken 3 ways** — payload-bound key (409), payload drift on retry, and the repo's own upsert erasing the reserved `message_id`. | 2 researchers |
| 4 | **Phase ordering shipped a regression window** — queue before failure contract ⇒ worker records success on failed payrolls; sweep races the queue. | 1 researcher |
| 5 | **Producer list was half the real one** — 8 `BackgroundTasks` producers by type annotation, not 3 files. | 1 researcher |
| — | *Refuted:* "unblock the front door is not shippable before the queue" (Codex's claim, which the first draft accepted). It is — `run_in_threadpool` needs zero schema. | 1 researcher |

---

## Explicitly out of scope

Deferred to backlog, with the schema shaped so each stays additive:

- **Per-tenant fairness, priority lanes, adaptive backpressure, circuit breakers.** All four researchers agree.
  (A stuck-open breaker would silently blackhole a week's payroll — worse than what it prevents. And
  backpressure is meaningless: you cannot push back on Resend's webhook.)
- **The N-concurrent-email load chart.** The durability proofs are the claims worth making.
- **Operator authentication** — a different axis; folding it in would blur the milestone.
