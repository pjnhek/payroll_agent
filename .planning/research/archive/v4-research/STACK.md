# Stack Research — v4 Durable Execution

**Domain:** Durable background execution (Postgres job queue + leases + in-process worker pool + HTTP pump) inside an existing FastAPI app on Render free
**Researched:** 2026-07-13
**Confidence:** HIGH
**Scope:** This document covers ONLY the v4 milestone's new capability. The v1 project-wide stack research (FastAPI/Supabase/LLM/Pub 15-T/Render) is unchanged and archived at `.planning/research/archive/v1-STACK.md` (also mirrored verbatim in `CLAUDE.md` → Technology Stack).

---

## Verdict, up front

# ADD NOTHING.

**No new runtime dependency is required, and none is recommended.** Every primitive the approved
design (`docs/superpowers/specs/2026-07-13-durable-execution-design.md`) calls for already exists in
the shipped stack:

| Design primitive | Already satisfied by | Evidence |
|---|---|---|
| `SELECT … FOR UPDATE SKIP LOCKED` | Supabase Postgres (≥15) | SKIP LOCKED landed in **PG 9.5**; Supabase's oldest supported major is 15. Trivially satisfied. |
| `gen_random_uuid()` for lease tokens | Supabase Postgres, **already in use** | `app/db/schema.sql:11-13` declares `CREATE EXTENSION IF NOT EXISTS pgcrypto`; `gen_random_uuid()` is the PK default on **6 shipped tables** (lines 17, 33, 70, 201, 225, 443) running live. Zero new surface. |
| Transactional enqueue + `ON CONFLICT DO NOTHING` dedup | `psycopg[binary,pool]==3.3.4` | The same `with conn.transaction()` pattern DATA-01/DATA-02 already ship. |
| Bounded worker pool | stdlib `threading` | Already used for the pool singleton lock (`app/db/supabase.py:20,35`) and by the Phase 10 concurrency proofs (8 real OS threads). |
| Worker startup/shutdown hook | `fastapi==0.138.0` `lifespan=` | `contextlib.asynccontextmanager`; stdlib + framework. |
| Unblocking the event loop | `starlette.concurrency.run_in_threadpool` | Transitive dep of FastAPI. Already installed. |
| Pump endpoint auth | stdlib `secrets.compare_digest` + `pydantic-settings` | Same `Settings` shape as `webhook_signing_secret` (`app/config.py:57`). |
| Exactly-once send (`Idempotency-Key`) | `resend==2.32.2` | `SendOptions(idempotency_key=…)` already present **at the pinned version** (verified in the design doc against `resend/request.py:65-66`). **No bump needed.** |
| Backoff + jitter | stdlib `random`, `datetime` | Expressed as `available_at = now() + interval`. |

**`uv add` count: 0.** The `pyproject.toml` dependency list is unchanged by this milestone.

The only "stack" changes are **schema** (a `jobs` table, plus a `provider_message_id` column) and
**config** (`PUMP_SECRET`, `WORKER_COUNT`, `LEASE_SECONDS`, `MAX_ATTEMPTS`, `POLL_SECONDS`) — both of
which this repo already has first-class, CI-gated machinery for (`schema.sql` + `/health/schema`
parity check + `deploy-migrate` workflow; `pydantic-settings`).

---

## The "add nothing" case, argued seriously

This is not laziness — it is the strongest option on the merits, for four reasons specific to this
project.

**1. The queue is ~40 lines of SQL you have already proven you can write.** The claim protocol is a
single `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *`. This repo has
already shipped and *falsified under genuine parallelism* (Phase 10, `test_concurrency_proof.py`, 8
real OS threads against a real Postgres in CI) the harder version of exactly this pattern: the atomic
`claim_status` CAS. Adopting a library to generate SQL you have demonstrably written correctly — and
already have a falsification harness for — is a loss of control for no gain in safety.

**2. The failure contract is the actual work, and no library can give it to you.** The design's
central insight (Phase C) is that `orchestrator.py` swallows stage failures into `ERROR` and *returns
normally* (`orchestrator.py:235-247,850-859`) — so **any** worker wrapping it records success. Fixing
that means introducing an explicit `ok` / `retryable(reason)` / `terminal(reason)` result type inside
the orchestrator. That is a change to your own code, in your own module, that no queue library can
make for you. Every library below sits *outside* that boundary and inherits the same bug verbatim.
**The dependency buys the easy half and leaves the hard half untouched.**

**3. Two state machines, one authority.** The design is explicit: `jobs` is *transport state only*;
`payroll_runs.status` remains the sole business state machine. A framework arrives with its own
job-state vocabulary, its own retry semantics, its own dead-letter concept, and its own migration
tooling. That is precisely the "two sources of truth for what happens next" the design names as the
classic way a queue corrupts the state machine it was added to protect. Owning a plain table keeps
that boundary enforceable by inspection.

**4. It is the same argument the project has already won twice.** "Plain Python workflow over
LangGraph/agent loop" and "psycopg direct SQL over supabase-py" are both logged Key Decisions with
outcome ✓ Good. The `status`-column-as-state-machine survived v2's atomicity work and v3's refactors
intact. A durable queue is the same shape of decision, and the same answer follows.

**Where "add nothing" *would* be wrong — and why it isn't here:** if this needed cron scheduling,
priority lanes, per-tenant fairness, distributed workers across machines, a job-admin UI, or real
throughput, rolling your own would be foolish. **All six are explicitly out of scope** (PROJECT.md →
Out of Scope → "v4: Throughput machinery"). At ~1 payroll email per client per week, with a fixed
three-kind job vocabulary (`ingest` / `run_pipeline` / `resume_reply`), a library's entire value
proposition is in features you have deliberately declined to build.

---

## Recommended stack (all already installed)

### Core technologies

| Technology | Version | Purpose in v4 | Why — for THIS project's constraints |
|---|---|---|---|
| **Supabase Postgres** | ≥15 (live project already runs `pgcrypto`) | The `jobs` table; `FOR UPDATE SKIP LOCKED` claim; `gen_random_uuid()` lease tokens; `available_at` backoff | Postgres-as-single-source-of-truth is a hard constraint. SKIP LOCKED needs PG≥9.5; `gen_random_uuid()` is already the PK default on 6 live tables. **No version risk, no new extension.** |
| **psycopg[binary,pool]** | `3.3.4` (pinned; also latest) | Claim / complete / fail queries; transactional enqueue | Already configured for Supavisor transaction-mode with `prepare_threshold=None` (`app/db/supabase.py:65`). The claim protocol is short-transaction SQL — exactly what transaction-mode pooling wants. **Nothing in the queue needs session state, which is why row leases were chosen over advisory locks.** |
| **fastapi** | `0.138.0` (pinned; latest 0.139.0) | `lifespan=` to start/stop worker threads; `POST /internal/pump` | `lifespan` is the correct, non-deprecated startup hook (`on_event` is deprecated). `app/main.py` has **no lifespan today** — this is the one new hook in app assembly. No bump needed. |
| **starlette** (transitive) | via FastAPI | `run_in_threadpool` — moves the blocking ingest off the event loop | Finding 2's fix. Import-only; already installed. |
| **Python stdlib** | 3.12 | `threading.Thread` workers, `threading.Event` shutdown, `secrets.compare_digest` pump auth, `random`/`datetime` jitter + backoff | Zero added supply-chain surface on a money-moving system. |
| **resend** | `2.32.2` (pinned; latest 2.33.0) | `SendOptions(idempotency_key=…)` → the `Idempotency-Key` header | The feature is **present at the pinned version**. Do **not** bump the send path during a milestone whose headline claim is "no client is ever emailed twice." |

### Supporting libraries

**None.** There is no `uv add` in this milestone.

### Development tools

| Tool | Purpose | Notes |
|---|---|---|
| **pytest** (existing dev-dep) | The Phase D proofs: kill-worker-mid-run durability, Svix redelivery idempotency, send-crash-sends-no-second-email, stale-lease zombie reclaim | These **require a real Postgres** — `SKIP LOCKED` and row locks have no meaningful fake. ⚠️ **Repo hazard:** only `concurrency-proof.yml` runs with a live Postgres in CI, and it **hard-codes a single test file**. Adding `tests/test_queue_durability.py` under `-m integration` without widening that workflow means **the proofs never run in CI** — the exact "guards are blind where they don't look" failure this repo has already been bitten by. |
| **ruff / mypy --strict** (existing dev-deps) | `app/queue/` must be type-clean | `[tool.mypy] files = ["app", …]` picks the new package up automatically. No config change. |
| **GitHub Actions** (existing) | The pump cron | A **new** `pump.yml`, not a job on `keepalive.yml`. See below. |

---

## Alternatives considered — the Postgres-queue library survey

Three genuinely-lightweight candidates were evaluated against the four constraints that actually bite
here. **All three are rejected**, each on a specific, non-negotiable ground.

| Library | Latest (PyPI, verified 2026-07-13) | Works with psycopg3? | Survives Supavisor **transaction-mode** pooling? | Needs its own worker process? | **Verdict** |
|---|---|---|---|---|---|
| **procrastinate** | `3.9.0` (2026-06-20) | Yes — depends on `psycopg[pool]` | Partly — LISTEN/NOTIFY is disableable | No separate process required, **but the worker requires an ASYNC connector** | ❌ **REJECT** |
| **pgqueuer** | `1.1.1` (2026-07-07) | Yes, via the `[psycopg]` extra | Partly — polling fallback exists | **Yes** — `pgq run …` CLI runner; async-first | ❌ **REJECT** |
| **pgmq** (extension + `pgmq` client) | client `1.1.2` (2026-06-14); extension supported by Supabase | Yes — `psycopg[binary,pool]>=3.2.10` | **Yes** — plain SQL function calls | N/A — it is storage only, no worker at all | ❌ **REJECT** |

### procrastinate 3.9.0 — REJECT

**What kills it: the worker requires an async connector.** Procrastinate's own documentation is
explicit — sync connectors (`SyncPsycopgConnector`) can *defer* jobs, but "other operations trigger
an error"; **workers require async connectors.** That means standing up a
`psycopg.AsyncConnectionPool` **as a second connection pool** alongside the existing sync
`ConnectionPool(min_size=1, max_size=5)`, both drawing from the same Supabase free connection budget
— which the design already identifies as the real capacity ceiling (Finding 3: *"the real capacity
ceiling is 5, not 40"*). And every task body would be an `async def` wrapping a **100% synchronous**
orchestrator (psycopg, openai, resend, reportlab), so each task would immediately `run_in_threadpool`
straight back out: an async shell around sync work, purchased with a doubled connection draw.

**Second, independently disqualifying:** procrastinate installs and migrates **its own schema**
(tables + PL/pgSQL functions + triggers) via `procrastinate schema --apply`. This repo has a single
`schema.sql` guarded by a `/health/schema` **live-drift parity check** and a `deploy-migrate` CI
workflow that turns the keepalive cron RED on drift. A second, externally-owned migration system
living inside that gate is a direct collision.

**Credit where due:** `app.run_worker(wait=False)` — "terminate as soon as it has caught up with the
queues" — **is** genuinely pump-shaped, and `listen_notify=False` **does** let it survive
transaction-mode pooling. Procrastinate is not architecturally incompatible with the pump idea. It is
incompatible with a fully-synchronous codebase and a foreign-schema-free deploy gate. That is the
honest reason, not a manufactured one.

*Also drags in:* `asgiref`, `attrs`, `croniter`, `python-dateutil`.

### pgqueuer 1.1.1 — REJECT

**What kills it: async-first, and it wants its own runner process.** The documented entrypoint is
`pgq run examples.consumer:main` — a separate CLI worker. **Render free has no background-worker
service type**, so a separate process is fatal by definition. It does ship a FastAPI integration
example, so embedding is *possible* — but that lands you exactly where procrastinate lands: an async
consumer loop wrapping sync work, plus the library's own retry/state vocabulary competing with
`payroll_runs.status`.

**Secondary:** its headline feature — "LISTEN/NOTIFY wakes workers the moment a job lands" — **does
not work under Supavisor transaction-mode pooling**. `LISTEN` is session-scoped; the pooler hands the
next statement to a different backend, so the listener silently never fires. You would adopt the
library and immediately disable the one thing it is best at, falling back to the polling you were
going to write anyway. It also pulls `typer`, `tabulate`, `uvloop`, `croniter` into a runtime image
whose slimness is a stated Render-cold-start constraint.

### pgmq (Supabase-supported extension + client 1.1.2) — REJECT

This is the tempting one, and it deserves a real hearing: it is genuinely lightweight, it is a
**Supabase-supported extension** (Supabase Queues is built on it), its Python client already depends
on `psycopg[binary,pool]>=3.2.10`, and its API is plain transactional SQL functions that survive
transaction-mode pooling cleanly. If the requirement were merely "I need a durable queue table," pgmq
would be a defensible answer.

**Two specific design requirements kill it:**

1. **No fencing token.** pgmq's model is `read(queue, vt, qty)` → a visibility timeout, then
   `delete(queue, msg_id)`. There is **no lease token**. The design's Rule 2 — *"every completion or
   failure write must match the `lease_token`… a zombie worker whose lease expired and was reclaimed
   by another worker cannot commit its stale result over the newer one"* — and **Phase D Proof #4
   (reclaim safety)** are precisely what pgmq cannot express. A zombie whose visibility timeout has
   expired can still `delete(msg_id)` a message a *second* worker is actively processing. **The single
   most important safety property of this milestone is the one pgmq does not have.**

2. **No unique dedup key.** The design's ingress idempotency anchor is `dedup_key UNIQUE` +
   `ON CONFLICT DO NOTHING`, keyed on the **Svix event ID** — the entire reason the ingress key had to
   move off the RFC `Message-ID` in Phase A. pgmq messages have no unique key and no upsert; a
   redelivered Svix event mints a second message. **Phase D Proof #2 (ingress idempotency) fails.**

**And the cost/benefit is upside-down regardless:** pgmq gives you *storage only*. You still write
100% of the worker pool, the pump, the backoff, the dead-letter, and the result contract. You would
pay an extension dependency + a client library + a `/health/schema` parity-gate complication, and
receive a queue that is strictly **less capable** than the ~40 lines of SQL it replaces.

### Not evaluated (ruled out by the milestone's own hard constraints)

`celery`, `rq`, `dramatiq`, `arq`, `huey`, `chancy` (0.25.1), `hatchet-sdk` (1.33.18) — each either
requires Redis / an external broker, requires a separate worker process, or *is* the "the project
owns its control flow" line the constraints draw. The constraint is dispositive; no further research
was warranted.

---

## What NOT to add

| Avoid | Why — specific to this project | Use instead |
|---|---|---|
| **`procrastinate`** | Worker requires an **async connector** → a *second* connection pool against a 5-connection budget, plus an async shell around 100% sync work. Its own schema/migration tooling collides with the `/health/schema` drift gate. | A `jobs` table in the existing `schema.sql`. |
| **`pgqueuer`** | Ships a **separate CLI worker process**; Render free has no worker service type. Its LISTEN/NOTIFY headline feature is dead under transaction-mode pooling. | In-process `threading.Thread` workers + the pump. |
| **`pgmq`** (extension + client) | **No fencing token** → Phase D Proof #4 (zombie reclaim safety) is unimplementable. **No unique dedup key** → Phase D Proof #2 (Svix ingress idempotency) is unimplementable. | Own `jobs` table with `lease_token UUID` + `dedup_key … UNIQUE`. |
| **`celery` / `rq` / `dramatiq` / `arq` / `huey` / `chancy` / `hatchet`** | Redis, or a separate worker process, or a foreign control flow. All three are locked-out constraints. | — |
| **`LISTEN` / `NOTIFY`** for worker wakeup | **`LISTEN` is session-scoped.** Supavisor transaction mode hands the next statement to a different backend; the listener silently never fires. (`NOTIFY` alone works — but a `NOTIFY` nobody can `LISTEN` for is a no-op.) | Poll `available_at <= now()` on an interval, plus the HTTP pump. |
| **`pg_advisory_lock`** / session advisory locks | Same session-scoping failure. The design calls this out by name. | Row leases: `FOR UPDATE SKIP LOCKED` + a `lease_token` CAS on every write. |
| **`psycopg.AsyncConnectionPool` / async psycopg** | Means either a **second pool** (doubling the draw on a 5-connection budget) or rewriting `app/db/repo/` — the most-tested, money-critical package in the repo, 100+ sync call sites — to async, for **zero durability benefit**. | Keep sync psycopg. Push blocking work into a thread via `run_in_threadpool`. |
| **`asyncio.Task` as the worker primitive** | The payload (psycopg, openai, resend, reportlab) is **entirely blocking**. A coroutine worker either blocks the event loop or immediately `run_in_threadpool`s — a thread wearing a coroutine costume. Worse: it draws from the **same ~40-thread AnyIO limiter the webhook uses**, which is Finding 3's exhaustion vector. | `threading.Thread`, with its own thread budget. |
| **`BackgroundTasks`** (all 6 producers) | The premise of the milestone: an object in process memory, vaporized by a redeploy / 15-min spin-down / OOM. Leaving *any* behind = two competing execution systems. | Enqueue a `jobs` row. Migrate `webhook.py:261,309`, `runs.py:262,380`, `demo.py:205,313`. |
| **Bumping `fastapi` → 0.139.0 or `resend` → 2.33.0** | Neither is needed — `lifespan` and `SendOptions(idempotency_key=…)` both exist at the pinned versions. A version bump on the **send path**, during a milestone whose claim is *"no client is ever emailed twice,"* is gratuitous unrelated risk. | Stay on `fastapi==0.138.0`, `resend==2.32.2`. |
| **`uvicorn --workers N`** | The Dockerfile CMD (`Dockerfile:61`) is correctly **single-process** today. Adding workers would multiply *both* the connection pool and the worker threads per process, silently blowing the 5-connection budget. | Keep single-process. This is now a **load-bearing invariant**, not an accident — comment it as one. |
| **`time.sleep()` / an internal timer as the retry driver** | Render free wakes **only on inbound HTTP**. An internal sleep sleeps *with* the service. This is the exact hole the pump exists to close. | The authenticated `/internal/pump` + GitHub Actions cron. |
| **A `ThreadPoolExecutor` + dispatcher** for the worker pool | Adds a dispatcher thread and a submission queue without adding a single safety property. See below. | N identical self-driving `threading.Thread` claim-loops. |

---

## Prescriptive patterns (the load-bearing part)

### 1. The worker primitive — `threading.Thread`, N=2, daemon, `lifespan`-managed

**Why threads, not `asyncio.Task`:** all downstream work is synchronous and blocking — verified
against the codebase: `psycopg` (sync `ConnectionPool`), `openai` (sync client), `resend` (sync
HTTP), `reportlab` (CPU). There is no async surface to exploit, so there is nothing for an event loop
to interleave.

**Why `threading.Thread`, not `concurrent.futures.ThreadPoolExecutor`:** a `ThreadPoolExecutor` is a
*task-submission* abstraction — it needs something upstream that pulls jobs from Postgres and submits
them. That "something" is itself a loop running in a thread. So a TPE means **N worker threads + 1
dispatcher thread + a submission queue**, versus **N identical self-driving threads**, each running:

```python
while not stop_event.is_set():
    job = queue.claim_one()                 # short txn; commits the lease immediately
    if job is None:
        stop_event.wait(POLL_SECONDS)       # interruptible sleep — NOT time.sleep()
        continue
    result = execute(job)                   # long: LLM / PDF / Resend
    queue.settle(job, result)               # CAS on lease_token
```

Identical concurrency bound, strictly fewer moving parts, and the claim-loop is the natural unit to
test. A `ThreadPoolExecutor` earns its keep when you need bounded *fan-out from one producer* — that
is not this shape. **Reach for it only if fan-out ever appears; today it adds a dispatcher without
adding safety.**

**Why N = 2 (a tuned constant, not a scaling knob):** the budget is **connections, not threads**
(Finding 3). `ConnectionPool(max_size=5)` must simultaneously serve worker threads, the ingest path,
operator approve/reject, and dashboard reads. Two workers leaves three for everything human-facing.
Put it in `Settings` as `worker_count`, and **assert `worker_count < pool.max_size` at startup** — a
silent misconfiguration here deadlocks the dashboard, which is exactly the class of failure that only
shows up in production.

> **Load-bearing invariant to enforce in review:** a worker must **never hold a pooled connection
> across an LLM / Resend / PDF call.** `orchestrator.py` looks compliant today (only two
> `with repo.get_connection()` blocks — lines 739 and 999, both wrapping transactions; repo functions
> open their own short-lived connections). **Verify this explicitly in Phase A**, because 2 workers
> pinning 2 of 5 connections across a 45s LLM timeout would starve ingest — and this is precisely the
> failure the design's Rule 1 ("the claim transaction never spans real work") is written to prevent.

**Why `lifespan`, not `on_event("startup")`:** `on_event` is deprecated. `app/main.py` has **no
lifespan today** — this is the single new hook in app assembly:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    workers = start_workers(n=settings.worker_count)   # threading.Thread(daemon=True)
    yield
    stop_workers(workers, timeout=…)                   # set threading.Event, then join
```

`daemon=True` so a hung worker can never block process exit — but still set the `Event` and `join()`
with a timeout, so a graceful redeploy drains in-flight work rather than recreating the very
lost-work bug the milestone exists to kill.

> **The pump must not depend on these threads existing.** On a cold-started Render instance, a job
> whose `available_at` has matured needs the pump to be its **primary** execution trigger, not a
> redundancy. Design `drain_once()` as the shared primitive that *both* the worker loop and the pump
> route call — one implementation, two callers.

### 2. Unblocking the event loop — keep `async def`, wrap the sync unit in `run_in_threadpool`

The route **must stay `async def`**: `await request.body()` is required for HMAC-over-raw-bytes, and a
sync `def` route cannot `await`.

*(You could smuggle the body into a sync `def` via `body: bytes = Body(...)` — FastAPI resolves that
in the async dependency phase, then runs the sync endpoint in the threadpool. **Rejected:** it trades
a clear, documented security-ordering contract (`webhook.py:36-55`, verify-before-parse) for a
framework trick, and it hands the *entire* route to the AnyIO threadpool instead of surgically marking
what actually blocks.)*

Correct shape:

```python
@router.post("/webhook/inbound")
async def inbound(request: Request) -> JSONResponse:
    raw_body: bytes = await request.body()      # cheap: a socket read, not blocking work
    headers = dict(request.headers)
    return await run_in_threadpool(ingest_sync, raw_body, headers)   # ALL blocking work
```

- **HMAC verify** is CPU-bound but microseconds. Move it *inside* `ingest_sync` so the whole
  authenticated unit is one sync, directly-testable function and the verify-before-parse ordering
  contract is preserved verbatim.
- **The Resend body-fetch leaves the request path entirely** (into the `ingest` job) — that is Phase
  A, and it is the *real* fix for Finding 2. `run_in_threadpool` handles the residual psycopg
  transaction, which is the only blocking work that remains.
- `run_in_threadpool` is `anyio.to_thread.run_sync` under a shared **~40-thread capacity limiter** —
  the same one Starlette uses for sync routes. Fine for a short ingest transaction. **Not** fine as
  the worker pool's home: a worker parked on a 45s LLM call would eat from the same limiter that
  ingest needs. **This is exactly why the workers get their own `threading.Thread`s and do not live
  in the AnyIO pool.**

### 3. Pump auth and cron — stdlib, no dependency

`POST /internal/pump` with a bearer token compared via `secrets.compare_digest` (constant-time)
against a new `pump_secret: str = ""` in `Settings` — the same shape as `webhook_signing_secret`
(`app/config.py:57`). **Bound the drain** (`≤ N jobs` or `≤ T seconds`) so it returns well inside the
GitHub Actions / Render HTTP timeout, and return counts (`claimed`, `done`, `failed`, `remaining`) so
a stuck queue turns the cron run RED — the same `curl -f` discipline `keepalive.yml` already uses.

**Cron placement: a new `pump.yml` (`*/10 * * * *`), not a job bolted onto `keepalive.yml`.**
Keepalive is 2×/week and its failure semantics ("is the service alive?") are categorically different
from the pump's ("did work drain?"). Carry keepalive's `workflow_dispatch:` escape hatch forward —
GitHub auto-disables scheduled workflows after 60 quiet days, which is the honesty the design already
commits to documenting rather than papering over.

---

## Postgres version requirements — confirmed

| Feature | Requires | Supabase free ships | Status |
|---|---|---|---|
| `SELECT … FOR UPDATE SKIP LOCKED` | PG **9.5+** | ≥15 (Supabase's oldest supported major; new projects on 15/17) | ✅ Enormous margin |
| `gen_random_uuid()` | Built-in PG 13+, **or** `pgcrypto` at any version | **Already enabled and in production** — `schema.sql:13` `CREATE EXTENSION IF NOT EXISTS pgcrypto`, used as the PK default on 6 live tables | ✅ Zero new surface |
| `ON CONFLICT DO NOTHING` | PG 9.5+ | ≥15 | ✅ Already used by `insert_inbound_email` |
| `now() + interval '…'`, `timestamptz` | any | — | ✅ |
| **Any extension for the queue** | — | — | ✅ **None. pgmq NOT required.** |

**Confidence: HIGH — and not inferred from docs.** `gen_random_uuid()` is verifiably already running
against the *live* Supabase instance across six shipped tables. **The queue asks Postgres for nothing
the app does not already do in production today.**

---

## Integration points into the existing app

| # | Where | Change |
|---|---|---|
| 1 | `app/db/schema.sql` | New `jobs` table: `dedup_key … UNIQUE`, `lease_token UUID`, `leased_until`, `available_at`, `attempts`, `state`, nullable `run_id` / `business_id`, `priority`. Index for the claim's `WHERE state='pending' AND available_at <= now()`. Plus `provider_message_id` for durable send evidence (Phase C). |
| 2 | `/health/schema` + `deploy-migrate.yml` | The parity check **must** learn the new table/columns, or the keepalive cron goes RED on first deploy. Schema-before-code deploy order (the Phase 8 discipline) applies. |
| 3 | `app/queue/` (**new package**) | `enqueue()`, `claim_one()`, `settle(job, lease_token, result)`, `drain_once(max_jobs)`. **Every completion/failure write is a CAS on `lease_token`** — the zombie guard, and Phase D Proof #4. |
| 4 | `app/db/supabase.py` | **Unchanged. Reuse the existing pool.** No second pool, sync or async. |
| 5 | `app/main.py` | Add `lifespan=` → start/stop N daemon worker threads. Has none today. |
| 6 | `app/routes/webhook.py` | `async def` + `await request.body()` + `await run_in_threadpool(ingest_sync, …)`. Re-key ingress dedup on the **Svix event ID**. **Cap the raw body** (`webhook.py:57` reads it unbounded — a durable raw inbox would otherwise persist and retry an oversized body forever). Enqueue an `ingest` job instead of `background_tasks.add_task`. |
| 7 | `app/routes/pipeline_glue.py` | `run_pipeline_bg` / `resume_pipeline_bg` (`:195,210`) become **job handlers returning `ok`/`retryable`/`terminal`** — not fire-and-forget wrappers whose `except` swallows everything. |
| 8 | `app/pipeline/orchestrator.py` | **The hard part.** Stop returning normally after writing `ERROR` (`:235-247,850-859`). Return an explicit result. Give `run_pipeline` an **atomic CAS claim** on `received → extracting` (`:223-234` writes it unconditionally — a reclaimed or duplicated job would run the initial pipeline twice, concurrently; `resume_pipeline` already CASes). |
| 9 | `app/routes/runs.py`, `app/routes/demo.py` | Migrate the remaining 4 `BackgroundTasks` producers (`runs.py:262,380`; `demo.py:205,313`). Leaving any behind = two competing execution systems. |
| 10 | `app/email/gateway.py` | Pass the already-reserved synthetic `message_id` (`:271-287`) as `SendOptions(idempotency_key=…)`; **on retry of a `reserved` row, reuse that row's id — never mint a fresh `uuid4`**; persist the provider's returned id (currently only logged, `:347-353`). |
| 11 | `app/config.py` | `pump_secret`, `worker_count` (2), `lease_seconds` (300), `max_attempts`, `poll_seconds`. Startup assertion: `worker_count < pool max_size`. |
| 12 | `.github/workflows/pump.yml` (**new**) | `*/10 * * * *` + `workflow_dispatch:`; `curl -f` the pump with the bearer secret. New Actions secret: `PUMP_SECRET`. |
| 13 | `.github/workflows/concurrency-proof.yml` | ⚠️ **Widen it.** It hard-codes a single test file and is the **only** CI job with a real Postgres. The Phase D proofs are worthless if they never run. |
| 14 | `Dockerfile:61` | Unchanged — but single-process `uvicorn` is now a **load-bearing invariant** (workers × processes × pool). Comment it as such so nobody "optimizes" it later. |
| 15 | `app/routes/runs.py` sweep | Keep `sweep_stranded_runs` until the queue is proven, **then retire it** (design, Phase A). |

---

## Version compatibility

| Package | Pinned | Latest (PyPI, 2026-07-13) | Action |
|---|---|---|---|
| `psycopg[binary,pool]` | `3.3.4` | `3.3.4` | ✅ Current. No change. |
| `fastapi` | `0.138.0` | `0.139.0` | ✅ Keep. `lifespan=` exists at 0.138.0. |
| `resend` | `2.32.2` | `2.33.0` | ✅ **Keep 2.32.2.** `SendOptions(idempotency_key=…)` already present. |
| `uvicorn[standard]` | `0.49.0` | `0.49.0` | ✅ Current. |
| `starlette` | transitive | `1.3.1` | ✅ `run_in_threadpool` is stable API; do not pin directly. |
| — | — | — | **Net new dependencies: 0** |

---

## Sources

- **PyPI JSON API** (`pypi.org/pypi/<pkg>/json`), queried 2026-07-13 — procrastinate `3.9.0` (deps: `psycopg[pool]`, asgiref, attrs, croniter, python-dateutil); pgqueuer `1.1.1` (deps: typer, tabulate, uvloop, croniter; `psycopg` only as an extra); pgmq `1.1.2` (`psycopg[binary,pool]>=3.2.10`); chancy `0.25.1`; hatchet-sdk `1.33.18`; psycopg `3.3.4`; fastapi `0.139.0`; resend `2.33.0`; starlette `1.3.1`. **HIGH.**
- **Procrastinate docs** — `howto/advanced/sync_defer.html` (**"Workers require async connectors"**; sync connectors can only defer, "other operations trigger an error"); `howto/production/connections.html` (LISTEN/NOTIFY costs one connection per worker, disableable); `howto/basics/worker.html` (`run_worker(wait=False)` terminates when caught up; `fetch_job_polling_interval`). **HIGH.**
- **PgQueuer README** (`github.com/janbjorge/pgqueuer`) — async-first; `pgq run <consumer>` CLI worker; LISTEN/NOTIFY with polling fallback; a FastAPI integration example exists. **HIGH.**
- **PgBouncer docs + issue #655** (`pgbouncer.org/features.html`, `github.com/pgbouncer/pgbouncer/issues/655`) — **`LISTEN` does not work in transaction mode** (`NOTIFY` does); advisory locks and session state likewise break. Directly applicable to Supavisor transaction mode (port 6543). **HIGH.**
- **Supabase Queues / PGMQ docs** (`supabase.com/docs/guides/queues/pgmq`) — pgmq is a supported extension; API is `send` / `read(vt)` / `delete(msg_id)` / `archive`. **No fencing token, no unique dedup key.** **HIGH.**
- **PostgreSQL release history** — `SKIP LOCKED` since 9.5; `gen_random_uuid()` built-in since 13, available via `pgcrypto` at any version. **HIGH.**
- **This repository — definitive, in-production evidence.** `app/db/schema.sql:11-13,17,33,70,201,225,443` (pgcrypto + `gen_random_uuid()` live on 6 tables); `app/db/supabase.py:57-69` (`max_size=5`, `prepare_threshold=None`); `Dockerfile:61` (single-process uvicorn); `app/main.py` (no lifespan); `pyproject.toml:7-18` (the pins); `.github/workflows/keepalive.yml` (2×/week, `workflow_dispatch` escape hatch). **HIGH.**
- **The approved design** — `docs/superpowers/specs/2026-07-13-durable-execution-design.md` (`3ed7db9`), Codex-reviewed; and `.planning/PROJECT.md` v4 milestone + Out of Scope. **Authoritative for scope.**

---
*Stack research for: durable Postgres-backed execution on a free-tier, worker-less, transaction-pooled deployment*
*Researched: 2026-07-13*
*Verdict: **add nothing.** 0 new dependencies. The work is schema, config, worker threads, and the orchestrator's result contract.*
