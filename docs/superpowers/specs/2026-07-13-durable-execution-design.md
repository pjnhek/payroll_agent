# v4 — Durable Execution

**Status:** Approved design, ready for planning
**Date:** 2026-07-13
**Supersedes:** the informal "queue + split ingestion/processing" framing

---

## The claim

> No accepted email is ever lost. Every failure recovers automatically within minutes,
> without a human noticing. And no client is ever emailed twice.

This is deliberately **not** "survive 100x traffic." Real traffic is roughly one payroll
email per client per week. A milestone built around throughput would be machinery for load
that never arrives. A milestone built around *durability* is proportionate, provable, and
is the floor that any future productization or scheduling sophistication stands on.

---

## Why this milestone exists

An adversarial audit flagged two ways the system breaks under pressure. Both are real, and
they are **different problems with different fixes** — a queue only addresses one of them.

### Finding 1 — Stage two is durable in memory only

The pipeline is already off the request path: the webhook commits its ingest transaction
and schedules the LLM-heavy work as a FastAPI `BackgroundTask` (`app/routes/webhook.py:309`).
Those wrappers are sync `def` (`app/routes/pipeline_glue.py:195,210`), so Starlette runs them
in the AnyIO threadpool, not on the event loop. That part is fine.

What is not fine: **a `BackgroundTask` is an object in process memory.** A Render redeploy, a
15-minute idle spin-down, or an OOM vaporizes it, and nothing on disk records that the work
was ever owed.

Recovery today is entirely *externally triggered*:

| Seam | Trigger | Covers |
|---|---|---|
| `repo.sweep_stranded_runs` + `repo.find_stranded_unconsumed_replies` | a human loading the runs-list page (`app/routes/runs.py:464-465`) | stale in-flight runs, unconsumed replies |
| redelivery re-schedule | Resend redelivering the same webhook (`app/routes/webhook.py:225-265`) | a lost *reply* resume |
| operator retrigger | a human clicking retry (`app/routes/runs.py:266-380`) | anything, manually |

No cron sweep, no startup sweep. A lost **initial** run that is never redelivered and whose
dashboard is never visited stays lost.

### Finding 2 — The webhook blocks the event loop

`inbound()` is `async def` (`app/routes/webhook.py:30`), and its body performs synchronous,
un-awaited blocking I/O directly on the loop:

- `gateway.parse_inbound(raw_body)` (`app/routes/webhook.py:96`) — for a real Resend envelope
  this makes a **synchronous HTTP call to the Resend API** to fetch the message body
  (`app/email/gateway.py:158-175`).
- the ingest transaction (`app/routes/webhook.py:139`) — synchronous psycopg, multi-query,
  against Supabase.

Every inbound email therefore freezes the entire web service for a third-party API round-trip
plus a multi-query database transaction. Under load, requests stack behind each other, Resend's
webhook times out, Resend redelivers, and the redelivery lands on an app that is still frozen.

**A queue does not fix this.** The blocking happens in the *ingest* path, in front of wherever
the queue is placed. It needs its own fix.

### Finding 3 (found while scoping) — the real capacity ceiling is 5, not 40

The AnyIO threadpool holds ~40 threads. The Postgres pool is `min_size=1, max_size=5`
(`app/db/supabase.py:57-68`). Under burst, dozens of pipelines parked on LLM calls contend for
five connections and can exhaust the threadpool — after which *nothing* can be offloaded,
including ingest. Any worker pool must be sized against the **connection** budget, reserving
headroom for ingest, approvals, and dashboard reads.

(Correction to an earlier assumption: LLM timeouts are *not* unbounded. Structured calls use
45s with `max_retries=0` (`app/llm/client.py:218-224`); confirmation 3s and clarification 30s
(`app/pipeline/compose_email.py:33-39`, `app/pipeline/clarification.py:438-494`). Only the
generic `call_text` path can inherit the library default.)

---

## The load-bearing constraint: durable storage is not durable execution

Render's free tier has **no background-worker service type**, no Redis, an ephemeral filesystem,
and it spins down after 15 idle minutes. Only *inbound HTTP* wakes it — internal timers and
sleeps do not.

So a naive Postgres queue drained by an in-process worker has a fatal hole:

1. HTTP wakes the service; a job is committed; a worker leases it.
2. Render spins down. The worker dies. The lease sits until it expires.
3. The job is now eligible again — **but no process exists to claim it.**
4. A retry scheduled with a future `available_at` has exactly the same problem.

The existing keep-alive runs Monday and Thursday and only pings health endpoints
(`.github/workflows/keepalive.yml:16-20,39-55`). It drains nothing.

Without an external pump, this milestone would ship a queue that stores work reliably and never
processes it — a *worse* lie than the current design, which at least fails visibly.

**Resolution: an authenticated pump endpoint, called frequently by cron.** See Phase B.

---

## Architecture

### Two state machines, one authority

- **`payroll_runs.status` remains the sole business state machine.** It is canonical, mirrored
  into a SQL CHECK constraint, and guarded by a CI drift test (`app/models/status.py:1-7`,
  `app/db/schema.sql:69-86`). Nothing about that changes.
- **`jobs` is transport state only.** A job row records *that an operation is owed and who owns
  it right now* — never *what payroll status comes next*. Job completion does not imply a run
  transition; the run transitions because the orchestrator committed it.

Violating this produces two sources of truth for "what happens next," which is the classic way
a queue corrupts a state machine.

### The `jobs` table

| Column | Purpose |
|---|---|
| `id` | PK |
| `kind` | `ingest` \| `run_pipeline` \| `resume_reply` — an idempotent operation |
| `dedup_key` | UNIQUE. The idempotency anchor; enqueue is `ON CONFLICT DO NOTHING` |
| `run_id` | nullable — an `ingest` job has no run yet |
| `business_id` | nullable — **see below** |
| `priority` | written, not yet read |
| `available_at` | when the job becomes claimable (drives backoff) |
| `attempts` | retry counter |
| `state` | `pending` \| `leased` \| `done` \| `dead` |
| `lease_token` | uuid, rotated on every claim |
| `leased_until` | lease expiry |

`business_id` **must be nullable.** Sender-to-business routing happens *after* the Resend body
fetch (`app/routes/webhook.py:195-220`), and this design moves that fetch into the worker — so
the tenant key is simply not known at ingress. It is backfilled by the ingest job.

`priority` and `available_at` are carried from day one so that per-tenant fairness and priority
lanes are later a change to the claim query's `ORDER BY`, not a migration. **We do not build
that logic now.**

### Claim protocol

```sql
-- Short transaction. Claims and commits the lease, then gets out of the way.
UPDATE jobs SET
  state = 'leased',
  lease_token = gen_random_uuid(),
  leased_until = now() + interval '5 minutes',
  attempts = attempts + 1
WHERE id = (
  SELECT id FROM jobs
  WHERE state = 'pending' AND available_at <= now()
  ORDER BY priority, available_at
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING *;
```

Two rules that make this safe:

1. **The claim transaction never spans real work.** It commits before any LLM, PDF, Resend, or
   email call. Holding a transaction across those would pin one of five connections for minutes
   and is incompatible with Supavisor's transaction-mode pooling.
2. **Every completion or failure write must match the `lease_token`.** A zombie worker whose
   lease expired and was reclaimed by another worker cannot commit its stale result over the
   newer one. (For the same reason: **no session-level advisory locks** — transaction-mode
   pooling does not preserve session state. Row leases and CAS only.)

---

## Phase A — The durable handoff

*(The original plan split "unblock the front door" and "add a queue" into two phases. It cannot
be split: "persist raw → enqueue" requires the queue to exist. Merged.)*

**Webhook becomes:** verify signature → offload to a thread → persist the raw signed event →
enqueue an `ingest` job → return 200. The event loop never blocks.

**The Resend body-fetch moves out of the webhook and into the `ingest` job.** This is the split
the milestone was reaching for. It also converts a Resend outage from a 502-plus-redelivery-storm
into an ordinary retried job.

**The consequence that must be handled:** today's dedup keys on the RFC `Message-ID`
(`app/routes/webhook.py:140-160`), which we only possess *because* we fetched the body. Once the
fetch is in the worker, that key does not exist at ingest time, and every Resend redelivery would
mint a fresh job. **The raw inbox is therefore keyed on the Svix event ID** — unique, present in
the signed envelope, no body required. The RFC-`Message-ID` dedup stays exactly as it is, one
layer deeper, as the second gate.

Also in this phase, because skipping any of them leaves two competing execution systems or a
known hole:

- **Migrate every `BackgroundTasks` producer** to the queue: `app/routes/webhook.py:261,309`,
  `app/routes/runs.py:262,380`, `app/routes/demo.py:205,313`.
- **Give the initial pipeline an atomic claim.** `resume_pipeline` uses CAS, but `run_pipeline`
  writes `received → extracting` unconditionally (`app/pipeline/orchestrator.py:223-234`). A
  reclaimed or duplicated job could otherwise run the initial pipeline twice, concurrently.
- **Cap the raw request body.** `app/routes/webhook.py:57` reads it with no size limit; the demo
  composer's limits (`app/routes/demo.py:139-151`) do not protect the real webhook. A durable raw
  inbox needs a byte cap and a retention policy, or an oversized body is persisted and retried
  forever.
- **Bound worker concurrency against the connection budget** (2–3 workers against a pool of 5),
  not against the 40-thread pool.
- **Keep the dashboard sweep** until the queue is proven, then retire it.

## Phase B — The pump

`POST /internal/pump` (authenticated): claims and drains due jobs, returns counts. GitHub Actions
cron calls it every 5–10 minutes. It is simultaneously the drain trigger and the Render wake-up,
since inbound HTTP is the only thing that wakes the service.

**The guarantee is documented honestly**, in the README and the ops page:

> Automatic recovery, typically within minutes. Best-effort: GitHub Actions cron can be delayed,
> and auto-disables after 60 days without a push. Operator retry is the documented fallback.

Overclaiming production-grade scheduling here would be the same class of error the repo already
corrected once, when it found its eval chart was lying.

## Phase C — Failure policy and exactly-once send

**An explicit result contract.** The orchestrator currently catches stage failures, writes
`ERROR`, and **returns normally** (`app/pipeline/orchestrator.py:235-247,850-859`) — so a worker
wrapping it would record the job as succeeded. Retry cannot be bolted on outside it. Stages
return `ok` / `retryable(reason)` / `terminal(reason)`, and the worker acts on that.

**Retry policy.** Exponential backoff with jitter, expressed as `available_at`. An attempt cap
moves the job to `dead`, surfaced to the operator.

**Infrastructure failures stay in `error`, not `needs_operator`.** `needs_operator` is a settled
gate awaiting a human decision, and the resolve route requires `decision.unresolved_names`
(`app/routes/runs.py:203-213`) — an LLM timeout during extraction has no decision at all. Parking
an outage there produces a run the operator UI cannot service. The fix is a durable retrigger on
`error`, not a new meaning for `needs_operator`.

**Exactly-once send.** The existing code already does the hard part: `gateway.py` mints a
synthetic `message_id` and writes a `reserved` row **before** calling Resend
(`app/email/gateway.py:271-287`). That is already a durable, unique, pre-send key — it is simply
discarded instead of being handed to the provider, so a crash between Resend accepting the mail
and the `sent` commit means a retry sends the client a second payroll email
(`app/pipeline/delivery.py:199-207` already admits this is at-least-once).

Three changes:

1. **Pass the reserved `message_id` to Resend as the idempotency key.** Verified available:
   `resend==2.32.2` (`pyproject.toml:17`) accepts `SendOptions(idempotency_key=...)` and emits it
   as the `Idempotency-Key` header (`resend/request.py:65-66`).
2. **On retry of a `reserved` row, reuse that row's `message_id` — never mint a fresh `uuid4`.**
   This is the subtle one. Today a retry would generate a new synthetic ID, which becomes a new
   idempotency key, which defeats the provider-side check entirely and sends the second email.
3. **Persist the provider's returned ID** as durable send evidence. There is no
   `provider_message_id` column today; it is only logged (`app/email/gateway.py:347-353`).

The resulting guarantee is precise and defensible: *provider-deduplicated send, keyed on a
durable pre-send reservation.*

## Phase D — Prove it

The repo's identity is that every claim has a proof behind it. Four:

1. **Durability.** Kill the worker mid-run; assert the run completes after the pump fires.
2. **Ingress idempotency.** Redeliver the same Svix event; assert exactly one job, one run, one
   email.
3. **Send safety.** Simulate a crash between Resend accepting and the `sent` commit; assert the
   retry sends **no second email** and the reserved `message_id` is reused.
4. **Reclaim safety.** Let a lease expire, let a second worker claim the job, then let the zombie
   first worker try to commit; assert its write is rejected on the stale `lease_token`.

Plus an ops view: queue depth, oldest-pending age, attempt counts, dead-letter list.

---

## Explicitly out of scope

Deferred to backlog, with the schema shaped so each is additive rather than a migration:

- **Per-tenant fairness and priority lanes.** `business_id` and `priority` are on the row; the
  logic that reads them is not built. Disproportionate at one email per client per week.
- **Adaptive backpressure, circuit breakers.**
- **The N-concurrent-email load chart.** Cut deliberately: the durability proofs above are the
  claims worth making. A throughput chart would be proving a property nobody is testing us on.
- **Operator authentication** (the known/accepted gap). A different axis from durability; folding
  it in would blur the milestone.

## What could still go wrong

- **GitHub cron is not a scheduler.** It can be delayed by many minutes and auto-disables after
  60 quiet days. The guarantee is written to match this, not to paper over it.
- **Supavisor transaction-mode pooling** forbids session-level state. If any advisory lock ever
  appears in this code, it must be transaction-scoped and short. Row leases avoid the issue.
- **Five connections is the ceiling.** Every new worker spends from the same budget as ingest,
  approvals, and dashboard reads. Worker count is a tuned constant, not a scaling knob.
