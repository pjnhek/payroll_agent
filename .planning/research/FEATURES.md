# Feature Research

**Domain:** Durable job execution (Postgres-backed queue) bolted onto a shipped, email-driven payroll pipeline
**Researched:** 2026-07-13
**Confidence:** HIGH on the Resend idempotency semantics (fetched from vendor docs) and on all claims about
this repo's existing code (read directly from source). MEDIUM on the queue-design canon (multi-source
community corroboration, no single authority).

---

## Headline: three things the approved design does not yet handle

The design (`docs/superpowers/specs/2026-07-13-durable-execution-design.md`) is sound and its categorization
is mostly right. Pressure-testing it against **Resend's actual documented idempotency semantics** and against
**this repo's live source** surfaces three gaps. All three sit on the "no client is ever emailed twice"
claim — the one claim in the milestone that is a promise about *money reaching a customer*.

| # | Gap | Why it matters |
|---|-----|----------------|
| **G1** | **Payload drift turns the idempotent replay into a hard 409.** Resend binds the key to the *payload*. Reuse the key with a **different** payload and you get `409 invalid_idempotent_request` — an error, not the silent no-op the design assumes. On retry, `delivery.py:118` re-drafts the body with an **LLM call** (`compose_confirmation`, Kimi) and `delivery.py:136` **regenerates the PDFs** with reportlab (`SimpleDocTemplate` stamps `/CreationDate` + `/ID` → non-deterministic bytes). Same key, different payload, every time. | The design says "pass the reserved `message_id` as the idempotency key." That alone **does not work**. The retry must *replay the persisted payload*, not recompose it. |
| **G2** | **The provider-side key expires after 24 hours.** Resend retains an idempotency key for 24h. A dead-lettered job resumed by an operator on Monday, or any retry ladder that stretches past a day, lands **outside the window** — the provider's dedup is simply gone, and it sends a second payroll email. | The design has no bound tying the retry ladder to the idempotency window, and no rule for what an operator retrigger is allowed to do to a `reserved` row after 24h. |
| **G3** | **An operator retrigger bumps `epoch`, which mints a new key — by design.** The real constraint is `uq_email_run_purpose_round_epoch (run_id, purpose, round, epoch)` (`schema.sql:279`), not the `uq_email_run_purpose` the design names (that's the stale v1 name). Phase 11's CLAR2-07 retrigger **wipes context and bumps the epoch**, so a retrigger deliberately produces a *new* reserved row → new `message_id` → **new idempotency key → Resend sends again.** | "No client is ever emailed twice" is **already false across an epoch bump**, on purpose. The guarantee must be scoped to *automatic* retries, or the retrigger path must be changed. This is a wording bug and possibly a behavior bug. |

**The honest claim** (see §3) is *not* "no client is ever emailed twice."

---

## Feature Landscape

### Table Stakes (a reviewer assumes these exist)

Missing any of these and the word "durable" is not earned. Complexity is relative to *this* codebase, which
already has CAS status claims, atomic transactions, and a real-Postgres concurrency-proof harness.

| Feature | Why Expected | Complexity | Notes / dependency on existing system |
|---|---|---|---|
| **Durable enqueue in the same transaction as the state write** | If the job row and the business-state write can diverge, the queue has added a failure mode instead of removing one. | **LOW** | Reuses the existing `conn.transaction()` discipline from DATA-01. The `jobs` INSERT must ride *inside* the webhook's ingest transaction — not after it. |
| **At-least-once delivery** | The only honest baseline. Exactly-once execution does not exist; it is at-least-once + idempotent effects. | **LOW** | Falls out of the claim protocol; nothing to build. Must be *stated*, not implied. |
| **Claim via `FOR UPDATE SKIP LOCKED`** | The canonical Postgres queue claim. Anything else (advisory locks, `SELECT` then `UPDATE`) either serializes workers or double-claims. | **LOW** | Design's SQL is correct. **Session-level advisory locks are forbidden** — Supavisor transaction-mode pooling does not preserve session state. |
| **Lease + visibility timeout (`leased_until`)** | A worker that dies holding a job must not strand it forever. This *is* the fix for the lost `BackgroundTask`. | **LOW** | Directly replaces `sweep_stranded_runs`. Keep the sweep until the queue is proven, then retire it (design says this; agreed). |
| **Stale-lease reclaim** | An expired lease must become claimable again, or the lease is decoration. | **LOW** | **See §1 — the design's claim SQL has a bug here.** Its predicate is `WHERE state='pending'`; an expired lease is `state='leased'` and is therefore **never reclaimed**. |
| **Lease-token fencing on every completion write** | Without it, a zombie worker whose lease expired can commit a stale result over the newer owner's. This is *the* subtle correctness bug in hand-rolled queues. | **MEDIUM** | Every terminal write carries `AND lease_token = $tok`. Composes with — but is **distinct from** — the existing `claim_status` CAS. **Both are needed:** CAS guards the *run's business status*; the lease token guards the *job's transport state*. Do not collapse them. |
| **`attempts` incremented AT CLAIM, not at failure** | A poison job that OOMs the worker never reaches a failure handler. Incrementing on failure means such a job retries **forever**. | **LOW** | The design's SQL already does `attempts = attempts + 1` inside the claim. **This is correct and worth defending in review** — it is the non-obvious choice. |
| **Exponential backoff + jitter, expressed as `available_at`** | Retrying an LLM 429 immediately, from N workers, in lockstep, is how you turn a blip into an outage. | **LOW** | `available_at` is already in the schema. Jitter is a one-line `random()`. **Cap the ladder inside the 24h Resend window (G2).** |
| **Attempt cap → dead-letter state** | Unbounded retry is not durability, it is a livelock with a log file. | **LOW** | `state='dead'`. Must be **visible to the operator** or it is a silent black hole. |
| **Idempotent enqueue (`dedup_key` UNIQUE + `ON CONFLICT DO NOTHING`)** | Resend redelivers webhooks. Without this, one email becomes N runs. | **LOW** | Keyed on the **Svix event ID** — correct, and forced: the RFC `Message-ID` is not known at ingest once the body-fetch moves to the worker. The existing `Message-ID` dedup **stays** as the second, deeper gate. Do not delete it. |
| **Explicit `ok` / `retryable` / `terminal` result contract** | The orchestrator currently catches stage failures, writes `ERROR`, and **returns normally** (`orchestrator.py:235-247`). A worker wrapping it would record **success**. Retry literally cannot be bolted on from outside. | **HIGH** | The single highest-effort item in the milestone and a **hard prerequisite** for retry, backoff, and dead-letter. Touches the money path — the one place a refactor could change behavior. |
| **The pump (`POST /internal/pump`, authenticated, cron-driven)** | Render free has no worker type and wakes **only on inbound HTTP**. Without an external pump you ship durable *storage* that never executes — strictly worse than today, which at least fails visibly. | **MEDIUM** | Non-negotiable. Auth is required: an unauthenticated drain endpoint is a free DoS surface. |
| **Replay the persisted send payload on retry (G1)** | Recomposing the email on retry produces a different payload → `409 invalid_idempotent_request`. | **MEDIUM** | The reserved row **already stores `body_text`, `subject`, `to_addr`** (`gateway.py:275-287`). Reuse them. **PDFs must additionally be made byte-deterministic** (pin reportlab's creation date / doc ID) or the attachment half of the payload still drifts. |
| **Reuse the reserved `message_id` on retry — never mint a fresh uuid4** | A new synthetic id = a new idempotency key = provider dedup defeated = second payroll email. | **LOW** | The design correctly identifies this. It is **necessary but not sufficient** — see G1. |
| **Bound worker concurrency against the *connection* budget (5), not the threadpool (40)** | The real ceiling. Dozens of pipelines parked on LLM calls contend for five connections and exhaust the AnyIO threadpool — after which *nothing* can be offloaded, including ingest. | **LOW** | 2–3 workers, reserving headroom for ingest, approvals, and dashboard reads. A tuned constant, **not a scaling knob**. |
| **Cap the raw request body + retention policy on the raw inbox** | `webhook.py:57` reads the body with **no size limit**. A durable raw inbox without a byte cap persists an oversized body and retries it forever. | **LOW** | The demo composer's limits (`demo.py:139-151`) do **not** protect the real webhook. |
| **Minimal ops surface (§4)** | "It's healthy" must be *checkable*, not a vibe. A dead-letter you cannot see is a lost email you have not noticed yet. | **LOW** | One Jinja2 page. The dashboard already exists — this is a 5th page, not a new system. |

### Differentiators (where this project actually wins the reviewer)

This repo's identity is **"every claim has a proof behind it."** The differentiator is *not* the queue — a
Postgres queue is a commodity. It is the **falsification harness around it** and the **refusal to overclaim**.

| Feature | Value Proposition | Complexity | Notes |
|---|---|---|---|
| **The four adversarial durability proofs** (kill-worker-mid-run; redelivery idempotency; send-crash-sends-no-second-email; stale-lease reclaim rejects the zombie's write) | This is the milestone's credibility. Anyone can write a `jobs` table; almost nobody proves the zombie-worker write is *rejected*. The repo already has the harness (`test_concurrency_proof.py`, real Postgres, `threading.Barrier`, CI job). | **MEDIUM** | Extends `concurrency-proof.yml`. **Reuse the existing barrier harness** — do not build a second one. Heed the v2 lesson: the *first* concurrency proof was **vacuous** (it serialized through an async route and passed even with the `ON CONFLICT` clause deleted). Drive the **sync repo seam directly** from N threads. |
| **Honest guarantee wording, published** (README + ops page) | The repo has already had to correct one lying artifact (the eval chart reporting a failure that never happened). *Naming the limits of your own durability claim* is the strongest possible signal to a hiring manager — and the cheapest thing in the milestone. | **LOW** | See §3. A paragraph of prose worth more than a month of machinery. |
| **`jobs` = transport state ONLY; `payroll_runs.status` stays the sole business state machine** | The classic way a queue corrupts the state machine it was added to protect is by encoding "what status comes next" in the job row. Stating *and enforcing* the boundary is a senior-engineer signal. | **LOW** | Enforceable with a test: no `jobs` column may name a `RunStatus` value. Cheap, and it makes the principle non-negotiable rather than aspirational. |
| **A terminal-vs-retryable taxonomy that is semantic, not status-code-shaped** | The two Resend 409s have **opposite** handling (§2). Anyone who buckets by HTTP status gets one of them wrong. | **MEDIUM** | Falls out of the result contract. The 409 pair is the demonstration case. |
| **Persist `provider_message_id` as durable send evidence** | Today the provider id is **only logged** (`gateway.py:347-353`). Logs are not evidence on an ephemeral filesystem. | **LOW** | One nullable column. Turns "did it actually go out?" from a support ticket into a `SELECT`. |

### Anti-Features (build none of these)

Real traffic is **~1 payroll email per client per week**. Every item below is machinery for load that will
never arrive. Naming them plainly is the point — this project has an explicit *not-over-engineered* mandate,
and the schema is already shaped so each remains a later `ORDER BY` change rather than a migration.

| Feature | Why Requested | Why Problematic *at this scale* | Alternative |
|---|---|---|---|
| **Priority lanes** | Every queue tutorial has them. | There is nothing to prioritize *against*. With a queue depth that is almost always 0 or 1, priority is a column nobody reads. | Write `priority`; **never read it**. Sort by `available_at`. |
| **Per-tenant fairness / weighted round-robin** | "What if one client floods us?" | One client sending 2 emails instead of 1 is not a flood. Fairness logic is only meaningful when tenants *contend*, and with 2–3 workers and weekly traffic they never do. | Write `business_id`; **never read it**. Revisit only if depth is ever sustained > 10. |
| **Adaptive backpressure** | Sounds rigorous. | Backpressure regulates a producer you control. The producer here is **Resend's webhook** — you cannot push back on it, you can only 200 fast and enqueue. The byte cap is the only real admission control available. | Cap the body. Return 200 fast. Done. |
| **Circuit breakers (LLM / Resend)** | Standard microservice hygiene. | A breaker protects a *shared* downstream from *your* stampede. Two workers doing one email a week are not a stampede. Backoff + jitter + attempt cap already bound the damage, and a breaker adds a **new stateful failure mode** — a stuck-open breaker silently blackholes the week's payroll — worse than the one it prevents. | Backoff + jitter + attempt cap + dead-letter. |
| **Autoscaling / dynamic worker pool** | "Production systems scale." | Render free has **one instance** and **five connections**. Worker count is a *tuned constant* dictated by the connection budget. An autoscaler here would scale between 2 and 2. | A constant. Document *why* it is a constant. |
| **Distributed tracing (OTel/Jaeger)** | Observability is good. | A trace correlates a request across *many services*. There is one service. `run_id` already correlates everything, and `error_detail` (OPS2-01) already surfaces failures on the dashboard without log access. | `run_id` + existing `error_detail` + the ops page. |
| **A full metrics stack (Prometheus/Grafana)** | Dashboards look impressive. | Standing up a metrics pipeline to graph a queue whose depth is 0 six days a week is the single most cargo-culted thing available here. It would also need a *second* always-on service that Render free does not offer. | Six `SELECT`s on one Jinja2 page (§4). |
| **The N-concurrent-email load chart** | The repo has a strong eval-chart precedent. | It would prove a property **nobody is testing us on** — and it invites a throughput comparison, the one question where a free-tier single instance loses. | The four falsification proofs. Ship those instead. |
| **A separate worker *process*** | "Queues have workers." | There is no worker service type on Render free, and an in-process worker + external pump is the *only* shape that actually executes. | In-process worker pool + `/internal/pump`. |
| **Parking infrastructure failures in `needs_operator`** | It's already a human-escape status. | `needs_operator` is a **settled gate awaiting a human decision**; the resolve route requires `decision.unresolved_names` (`runs.py:203-213`). An LLM timeout has **no decision at all** — parking it there produces a run the operator UI **cannot service**. | Stay in `error` + durable retrigger. (The design gets this right; keep it.) |

---

## 1. Queue/worker table stakes — verdict

The design's list is **complete and correct**. Every item the question enumerates is present and correctly
specified, including the two non-obvious ones:

- **Lease-token fencing** — present, and correctly stated as "every completion or failure write must match
  the `lease_token`." This is the item most hand-rolled queues get wrong.
- **`attempts` incremented at claim** — present in the claim SQL. This is what bounds a *poison job that
  kills the worker before it can report*, which a failure-time increment never catches.

One correction and one real bug:

- **Correction:** the design names `uq_email_run_purpose`. The live constraint is
  `uq_email_run_purpose_round_epoch (run_id, purpose, round, epoch)` (`schema.sql:279`). Any reserved-row
  lookup on the retry path must key on **all four columns**, or a round-2 clarification retry collides with
  round 1.
- **Bug — the stale-lease reaper is missing.** The design's claim SQL selects
  `WHERE state = 'pending' AND available_at <= now()`. An expired lease is `state = 'leased'`. As written,
  **an expired lease is never reclaimed** — precisely the failure the lease exists to fix, and the failure
  the milestone's own Proof #4 assumes is handled. Fix the predicate to
  `state='pending' OR (state='leased' AND leased_until < now())`, or add an explicit reaper sweep that flips
  expired leases back to `pending`.

## 2. Failure taxonomy

**The distinction is not "which exception" — it is "would doing this again, unchanged, plausibly succeed?"**

| Class | Meaning | Examples in *this* pipeline |
|---|---|---|
| **`retryable`** | The input was fine; the world was temporarily unavailable. | LLM 429 / 5xx / timeout (`client.py`, 45s, `max_retries=0`); Resend 5xx; Resend **`409 concurrent_idempotent_requests`**; psycopg `OperationalError` / pool exhaustion; Supabase connection reset. |
| **`terminal`** | Retrying is *guaranteed* to fail identically. Burning 5 attempts is theater. | Pydantic `ValidationError` after the one structured-output retry; unknown sender (no business); malformed/oversized body; Resend **`409 invalid_idempotent_request`** (payload drifted — the docs say retrying "is useless"); Resend `422` (bad address). |
| **`ok`** | Includes **business-logic outcomes that are not failures.** | `request_clarification` is a **successful** job. So is `needs_operator`. The gate firing is the system *working*. |

**That third row is the one that bites.** In a pipeline whose whole thesis is a deterministic gate, the most
likely new bug is a worker treating "the code decided to clarify" as a failure and retrying it — emailing the
client the same question five times. **`decide.py` returning `request_clarification` is `ok`.**

**How to model it: a result type, not an exception hierarchy.**

1. The orchestrator **already swallows** stage exceptions into `ERROR` and returns normally. An exception
   hierarchy would require *un-swallowing* — re-raising across the money path — the refactor most likely to
   change behavior. A returned `Result` threads through the existing `try/except` without inverting control
   flow.
2. Classification here is **contextual, not type-intrinsic.** The same `resend` error is retryable or
   terminal depending on its `409` sub-code. A type hierarchy forces that decision at `raise` time, far from
   the policy; a result type lets one `classify_exception(exc) -> Retryable | Terminal` own it — a **pure,
   importable, table-testable function**, exactly the shape of `decide.py`.
3. It is honest about the third state. An exception hierarchy has no natural way to express *"this stage
   succeeded, and the answer is: ask the client."*

**Recommendation:** `StageResult = Ok | Retryable(reason) | Terminal(reason)`, plus a pure
`classify_exception` whose **default is `Terminal`**. Default-terminal is the safe default in a money system:
an unclassified error dead-letters loudly in front of a human rather than silently retrying an unknown side
effect four more times.

## 3. Exactly-once side effects — the concrete answer

**Exactly-once delivery does not exist.** The crash window between "provider accepted" and "we committed that
it was sent" cannot be closed by any protocol between two systems that do not share a transaction. This is the
Two Generals problem; it is not an engineering gap a better library fixes.

What the standard patterns actually buy:

| Pattern | Applies here? | What it actually does |
|---|---|---|
| **Durable pre-send reservation** | ✅ **Already built.** `gateway.py:271-287` writes `send_state='reserved'` with a unique synthetic `message_id` **before** calling Resend. | Makes the crash window *diagnosable*: a `reserved` row means "may have escaped." |
| **Provider-side idempotency key** | ✅ **The right lever.** `resend==2.32.2` accepts `SendOptions(idempotency_key=...)`. | Moves the dedup decision to the one party that *knows* whether the mail went out. |
| **Transactional outbox** | ⚠️ **Redundant.** | The `reserved` row **is** the outbox. Do not build a second one. |
| **Local dedup-on-write** | ✅ **Already built.** `uq_email_run_purpose_round_epoch` + the purpose-aware already-sent guard (`delivery.py:77-92`). | Covers the *easy* window (crash **after** the `sent` commit). **Does not cover the `reserved` window** — the guard matches `send_state='sent'` only, so a retry over a `reserved` row **falls through and re-sends**. |

### Resend's documented semantics (vendor docs — HIGH confidence)

- Key retained **24 hours** after first use. Max 256 chars. Endpoints: `POST /emails`, `POST /emails/batch`.
- Same key + **identical payload** → returns the original response, **does not resend**. ← the happy path.
- Same key + **different payload** → **`409 invalid_idempotent_request`**; retrying "is useless without
  changing the idempotency key or payload." ← **a hard error, not a no-op.**
- Same key, request already in flight → **`409 concurrent_idempotent_requests`**, safe to retry later.

### What this means for *this* code

The design's plan — "pass the reserved `message_id` as the key, reuse it on retry" — is **necessary but
insufficient**, because the retry path does not reproduce the payload:

- `delivery.py:118` re-drafts the body with an **LLM call**. Non-deterministic by construction.
- `delivery.py:136` **regenerates the PDFs** with reportlab, whose `SimpleDocTemplate` stamps a
  `/CreationDate` and document `/ID` → **different bytes on every call**, even for identical inputs.

So the retry sends **the same key with a different payload** — the documented `409` case — on essentially
every attempt. The intended silent no-op becomes a hard failure.

**Three changes required, in addition to the design's three:**

1. **Replay, don't recompose.** On retry, load the `reserved` row and reuse its stored `subject`, `body_text`,
   and `to_addr`. They are **already persisted**. Never re-call the LLM on a retry.
2. **Make the PDF bytes deterministic** (pin reportlab's creation date + doc ID for a given input), so the
   attachment half of the payload is stable too. Without this, (1) is not enough.
3. **Split the two 409s.** `concurrent_idempotent_requests` → **retryable**.
   `invalid_idempotent_request` → **terminal, and do not resend** — it is *evidence the key was already
   consumed*, which means an email very likely went out. Escalate to the operator; never auto-resend.

### The honest wording

> **Not promisable:** "No client is ever emailed twice."
>
> **Promisable:** *"A payroll confirmation is sent at most once per approved run, per epoch, within Resend's
> 24-hour idempotency window. Delivery is anchored on a durable pre-send reservation and deduplicated by the
> provider on that key. Beyond 24 hours — or after an operator retrigger, which deliberately opens a new
> epoch — provider-side deduplication no longer applies and a resend is possible. A stale `reserved` row is
> therefore escalated to a human rather than retried automatically."*

That is a **narrower** claim than the milestone currently makes, and it is exactly the kind of narrowing this
repo has already shown it will do (the eval chart). Publishing it is a differentiator; papering over it is the
same class of error the project already corrected once.

## 4. Ops visibility — the smallest set that makes "healthy" checkable

Seven numbers on **one Jinja2 page** (the dashboard's 5th). Each maps to a *decision*, or it is decoration:

| Signal | The question it answers | Unhealthy when |
|---|---|---|
| **Queue depth** (`state='pending'`) | Is work piling up? | Sustained > ~5 at this traffic. |
| **Oldest pending age** (`now() - min(available_at)`) | **The single most important number.** Is anything *stuck*? | > ~15 min ⇒ **the pump is not firing.** The one metric that detects the milestone's own load-bearing failure — a queue that stores and never executes. |
| **In-flight count** (`state='leased' AND leased_until > now()`) | Are workers actually working? | > worker count ⇒ leases leaking. |
| **Expired leases** (`state='leased' AND leased_until < now()`) | Are workers dying mid-job? | Any sustained non-zero ⇒ crash loop (and, today, ⇒ the reaper bug in §1). |
| **Attempts distribution** (`count(*) GROUP BY attempts`) | Is something retrying quietly? | Mass at attempts ≥ 2 ⇒ a downstream is degraded. |
| **Dead-letter list** (`state='dead'`, with `run_id` + last error) | **The lost-email list.** | **Any row ⇒ a client's payroll is not moving.** Must link to the run and to a retrigger. |
| **Stale `reserved` outbound rows** (older than N minutes) | Did an email escape without us recording it? | Any row ⇒ the crash-during-send window fired. **Do not auto-resend** — surface it. |

Everything beyond these seven is the metrics-stack anti-feature.

---

## Feature Dependencies

```
[Result contract: ok/retryable/terminal]   <-- THE prerequisite. Nothing retries without it.
    └──required by──> [Backoff + jitter]
    └──required by──> [Attempt cap → dead-letter]
    └──required by──> [Exactly-once send policy]

[jobs table + SKIP LOCKED claim]
    └──requires──> [Lease + leased_until]
                       └──requires──> [Stale-lease reclaim]   <-- BUG in design's claim SQL
                       └──requires──> [Lease-token fencing]
    └──requires──> [dedup_key on Svix event ID]
                       └──requires──> [Resend body-fetch moved into the worker]
                                          └──forces──> [business_id nullable, backfilled by ingest job]

[The pump]  ──makes-executable──>  [everything above]
    (without it: durable STORAGE, never durable EXECUTION)

[Exactly-once send]
    └──requires──> [Reuse reserved message_id]        (design has this)
    └──requires──> [Replay persisted payload, no LLM] (G1 — MISSING)
    └──requires──> [Deterministic PDF bytes]          (G1 — MISSING)
    └──requires──> [Retry ladder bounded < 24h]       (G2 — MISSING)
    └──requires──> [Epoch-bump resend policy]         (G3 — MISSING / contradicts the claim)
    └──enhanced-by──> [persist provider_message_id]

[Existing claim_status CAS]     ──composes-with, DOES NOT REPLACE──> [lease_token fencing]
[Existing sweep_stranded_runs]  ──superseded-by──> [lease expiry]   (retire only after proofs pass)
[Existing Message-ID dedup]     ──demoted-to-second-gate-by──> [Svix dedup]  (keep both)
```

### Dependency notes

- **The result contract gates the entire milestone.** It is the only HIGH-complexity item and it touches the
  money path. Nothing in Phase C can start before it. If the milestone must be cut, cut *scope around* this —
  never this.
- **The stale-lease reaper is a silent hole.** The design's claim SQL selects `WHERE state = 'pending'`; an
  expired lease is `state='leased'`. As written, **an expired lease is never reclaimed** — the exact failure
  the lease exists to fix, and the one Proof #4 is supposed to exercise. Fix the predicate or add the reaper.
- **`claim_status` CAS and `lease_token` fencing are different guards.** CAS protects the *run's business
  status* from a double-approve. The lease token protects the *job's transport state* from a zombie worker.
  Collapsing them would let a zombie's stale job-completion write commit while CAS correctly rejects its
  status write — leaving a job marked `done` for work that never happened. **Keep both.**
- **Retiring the dashboard sweep depends on the durability proofs passing** — not on the queue merely
  existing. (v2's lesson: the first concurrency proof was vacuous and passed with the safety clause deleted.)

---

## MVP Definition

### Launch With (v4)

- [ ] **Result contract** (`ok`/`retryable`/`terminal`) — the hard prerequisite; nothing retries without it.
- [ ] **`jobs` table + SKIP LOCKED claim + lease + lease-token fencing + stale-lease reclaim** — the durable handoff.
- [ ] **Svix-keyed idempotent enqueue**; `Message-ID` dedup retained as the second gate.
- [ ] **Resend body-fetch moved into the worker**; webhook offloaded to a thread; body byte-capped.
- [ ] **Atomic claim for the initial pipeline** — `run_pipeline` currently writes `received → extracting` unconditionally, so a reclaimed job would run it twice, concurrently.
- [ ] **Every `BackgroundTasks` producer migrated** (webhook, runs ×2, demo ×2). Leaving one behind means two competing execution systems.
- [ ] **The pump** — authenticated endpoint + cron. Without it the rest is inert.
- [ ] **Backoff + jitter + attempt cap + dead-letter**, ladder bounded **inside 24h**.
- [ ] **Exactly-once send: all six parts** — reuse the reserved `message_id`; **replay the persisted payload**; **deterministic PDF bytes**; split the two 409s; persist `provider_message_id`; escalate stale `reserved` rows to the operator.
- [ ] **The ops page** — 7 signals, dead-letter list linked to retrigger.
- [ ] **The four proofs**, on the existing real-Postgres barrier harness.
- [ ] **The honest guarantee, published** in the README and on the ops page.

### Add After Validation (v4.x)

- [ ] **Retire `sweep_stranded_runs`** — trigger: the four proofs green in CI for a full milestone.
- [ ] **Raw-inbox retention/GC** — trigger: the raw event table crosses a size worth caring about.

### Future Consideration (v5+)

- [ ] Priority lanes / per-tenant fairness — trigger: **sustained** queue depth > 10. Schema is already shaped for it (`priority`, `business_id`); it is an `ORDER BY` change, not a migration. Deliberately deferred.
- [ ] Circuit breakers, adaptive backpressure, autoscaling, tracing, metrics stack — **no trigger at this scale.** These are named anti-features, not a backlog.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---|---|---|---|
| Result contract (`ok`/`retryable`/`terminal`) | HIGH | HIGH | **P1** |
| `jobs` + SKIP LOCKED + lease + fencing + **reaper** | HIGH | MEDIUM | **P1** |
| The pump (auth'd endpoint + cron) | HIGH | MEDIUM | **P1** |
| Exactly-once send: **payload replay + deterministic PDFs** (G1) | HIGH | MEDIUM | **P1** |
| Exactly-once send: reuse reserved `message_id` | HIGH | LOW | **P1** |
| Stale-`reserved`-row escalation (G2/G3) | HIGH | LOW | **P1** |
| Svix-keyed enqueue dedup | HIGH | LOW | **P1** |
| Migrate all `BackgroundTasks` producers | HIGH | LOW | **P1** |
| Atomic claim for `run_pipeline` | HIGH | LOW | **P1** |
| Backoff + jitter + attempt cap + dead-letter | HIGH | LOW | **P1** |
| Webhook body cap | MEDIUM | LOW | **P1** |
| Worker count bounded by connection budget | MEDIUM | LOW | **P1** |
| The four durability proofs | HIGH | MEDIUM | **P1** |
| Honest guarantee wording, published | HIGH | LOW | **P1** |
| Ops page (7 signals) | MEDIUM | LOW | **P1** |
| Persist `provider_message_id` | MEDIUM | LOW | **P2** |
| Retire the dashboard sweep | LOW | LOW | **P2** |
| Raw-inbox retention/GC | LOW | LOW | **P2** |
| Priority / fairness / breakers / autoscale / tracing / metrics | **LOW** | HIGH | **anti-feature** |

## How mature systems do it (comparison)

| Feature | Sidekiq / Celery | Temporal / River / Oban | Our approach |
|---|---|---|---|
| Claim | Redis BRPOP | Postgres `SKIP LOCKED` | `SKIP LOCKED` — same as River/Oban; no Redis on Render free. |
| Fencing | mostly absent (a known bug class) | lease/run tokens | **Lease token on every completion write.** The thing hand-rolled queues skip. |
| Terminal errors | `Sidekiq::Job.discard` / `Reject(requeue=False)` | non-retryable error types | **Result type**, not exception hierarchy — the orchestrator already swallows, and the 409 pair proves classification is contextual. |
| Attempts | usually incremented on failure | at claim | **At claim** — bounds a worker-killing poison job. |
| Exactly-once | disclaimed ("at-least-once") | at-least-once + idempotent activities | Same. **Disclaimed explicitly**, with the 24h window named. |
| Ops UI | full web UI + metrics stack | full web UI | **One page, 7 numbers.** Anything more is the metrics anti-feature. |

## Sources

- **Resend — Idempotency Keys** (vendor documentation, fetched 2026-07-13): 24h key retention, 256-char limit, `POST /emails` + `/emails/batch`, identical-payload replay returns the original response without resending, **different payload → `409 invalid_idempotent_request`**, in-flight → `409 concurrent_idempotent_requests`. — **HIGH** (primary vendor docs). https://resend.com/docs/dashboard/emails/idempotency-keys
- **This repo's source**, read directly — `app/email/gateway.py` (reserved row + discarded synthetic id + logged-only provider id), `app/pipeline/delivery.py` (purpose-aware `sent`-only guard; LLM recompose at :118; PDF regen at :136; the at-least-once admission at :199-207), `app/db/schema.sql:279` (`uq_email_run_purpose_round_epoch`), `app/pipeline/pdf.py` (reportlab `SimpleDocTemplate`), `pyproject.toml:17` (`resend==2.32.2`). — **HIGH**.
- **Postgres `SKIP LOCKED` queue canon** — lease/visibility timeout, claim-token fencing, stale-claim recovery, attempt caps, backoff+jitter. Corroborated across multiple independent implementations (pivovarit/fencepost; ente.com's Postgres task queue; several practitioner writeups). No single authority. — **MEDIUM**.
- **The approved design** — `docs/superpowers/specs/2026-07-13-durable-execution-design.md` (`3ed7db9`), Codex-reviewed. Its scope cuts are endorsed; its exactly-once section and its claim SQL are where this research diverges.

---
*Feature research for: durable job execution on a shipped payroll pipeline (Render free + Supabase + Resend)*
*Researched: 2026-07-13*
