# Requirements — Milestone v4: Durable Execution

**Milestone goal:** No accepted email is ever lost; every failure recovers automatically within ~30 minutes
without a human noticing; and a client is sent at most one confirmation per approved run, per epoch.

**Design:** `docs/superpowers/specs/2026-07-13-durable-execution-design.md` (revised 2026-07-14 after
adversarial research — 4 parallel researchers + a Codex review found 5 defects in the first draft, two of them
independently corroborated).

**Research:** `.planning/research/SUMMARY.md`

**Stack verdict: zero new dependencies.** Every primitive is already installed and in production use
(`pgcrypto`/`gen_random_uuid()` live at `schema.sql:13`, used 7× as a PK default; `SKIP LOCKED` needs PG 9.5,
Supabase ships 15+). Every queue library surveyed (`procrastinate`, `pgqueuer`, `pgmq`) died on a specific
constraint — and none could supply the failure contract, which is the actual work.

---

## v4 Requirements

### QUEUE — Durable job substrate

- [x] **QUEUE-01**: The webhook never blocks the event loop. Blocking ingest I/O (the synchronous Resend fetch
  at `webhook.py:96` and the psycopg transaction at `webhook.py:139`) runs off-loop via `run_in_threadpool`,
  while the route keeps `async def` because HMAC verification needs `await request.body()` over the raw bytes.
  **Zero new schema — independently shippable.**

- [x] **QUEUE-02**: A `jobs` table provides durable transport state — a UNIQUE `dedup_key` (enqueue is
  `ON CONFLICT DO NOTHING`), `lease_token` + `leased_until` fencing, and `attempts` incremented **at claim** so
  a poison job that kills its worker before it can report failure is still bounded. The claim query
  (`FOR UPDATE SKIP LOCKED`, in a short transaction that commits before any real work) **reclaims an expired
  lease** — `state = 'pending' OR (state = 'leased' AND leased_until < now())`.

- [x] **QUEUE-03**: A bounded worker pool drains the queue — 2 daemon threads managed by FastAPI `lifespan`,
  sized against the **connection** budget (`workers + 2 ≤ max_size=5`), never the 40-thread AnyIO pool. Workers
  **release their leases on graceful shutdown**, so a routine redeploy does not strand every in-flight job for
  a full lease duration.

- [x] **QUEUE-04**: Every producer is migrated — all **8** `BackgroundTasks` route-signature producers across
  `webhook.py`, `demo.py` (×2), and `runs.py` (×5, including one hiding inside the `runs_list()` page render).
  No pipeline work is ever again scheduled into process memory.

- [x] **QUEUE-05**: `jobs` carries transport state ONLY, never a business status. **Invariant J-1:** a
  handler's first durable action is a `claim_status(expected → next)` CAS, and **a failed CAS is a DONE job,
  not a retry** — converting at-least-once job delivery into at-most-once state advance. Enforced by a CI guard
  in the shape the repo already uses (`RunStatus`↔CHECK drift test, BOUND-01 AST guard).

### PUMP — Turning durable storage into durable execution

- [x] **PUMP-01**: An authenticated pump endpoint claims and drains due jobs, sharing **one** `drain_once()`
  implementation with the worker threads. It is the **primary** execution trigger, not a redundancy: on a
  cold-started Render instance the worker threads may not exist when a retried job's `available_at` matures.

- [x] **PUMP-02**: Cron drives the pump every **30 minutes**, and the README documents the duty-cycle math
  (`awake ≈ 15 ÷ cadence`), the **750 instance-hour/month** ceiling that forces it, and the deliberately
  best-effort wording (GitHub Actions cron can be delayed and auto-disables after 60 quiet days; operator retry
  is the stated fallback).

### FAIL — Failure policy

- [x] **FAIL-01**: The orchestrator returns an explicit **result type** — `ok` / `retryable` / `terminal`,
  defaulting to `terminal` (the safe default in a money system). Today it catches stage failures, writes
  `ERROR`, and **returns normally** (`orchestrator.py:235-247`), so any worker wrapping it would record
  success. Critically, **`request_clarification` is `ok`, not a failure** — a worker retrying a deterministic
  gate's decision to clarify would email the client the same question five times.

- [x] **FAIL-02**: Retries use exponential backoff + jitter via `available_at`; an attempt cap moves the job to
  a `dead` state surfaced to the operator. Infrastructure failures stay in `error` with a durable retrigger —
  **not** `needs_operator`, which the resolve route cannot service without `decision.unresolved_names`
  (`runs.py:203-213`).

- [x] **FAIL-03**: `sweep_stranded_runs` is **DELETED**, replaced by the dead-letter transition. Keeping it
  alongside the queue *is* the hazard: two status writers, both firing at ~15 minutes, with the sweep winning by
  flipping a run to `ERROR` exactly as the queue reclaims it — defeating the headline claim with its own safety
  net. Net effect: a deletion of three recovery hacks, including the dashboard-page-load-as-cron block at
  `runs.py:464-465`.

### SEND — At most one confirmation per approved run, per epoch

- [x] **SEND-01**: A retry **reuses** the reserved `message_id` (read-before-mint), and the upsert stops
  overwriting it. Today `emails.py:85` does `ON CONFLICT ... DO UPDATE SET message_id = EXCLUDED.message_id`
  while `gateway.py:274` mints a fresh `uuid4` every call — **the write path erases the row the retry must
  read.** Because that synthetic id is the sole reply-routing anchor, a naive retry does not merely double-email;
  it **orphans the client's reply into a brand-new payroll run**. `failed` must reuse the key too — it is not
  proof of non-delivery (`gateway.py:341-345` flips to `failed` on *any* Resend exception, including a timeout
  after the mail was accepted).

- [x] **SEND-02**: A retry **replays the persisted payload** (`subject`/`body_text`/`to_addr`, already on the
  reserved row) and **never re-derives it** — no re-draft through the LLM (`delivery.py:120`), and deterministic
  PDF bytes (reportlab stamps a fresh `/CreationDate` and `/ID` per document). Resend binds the idempotency key
  to the **payload**, so any drift turns a safe retry into a **409 `invalid_idempotent_request`** hard error.

- [x] **SEND-03**: Resend's `Idempotency-Key` is passed on send (`resend==2.32.2` supports it —
  `SendOptions.idempotency_key` → the header at `resend/request.py:65-66`), and the retry ladder is **bounded
  below the provider's 24-hour retention window** (verified against Resend's docs). Past that window there is no
  provider dedup at all: a stale reservation **escalates to a human and is never auto-resent**. Pre-flight:
  delete the dead `send_outbound(send_state=...)` parameter (`gateway.py:286` hard-codes `"reserved"`; both
  callers pass `"sent"`) — a loaded gun in the exact function this requirement rewrites.

### PROOF — Evidence, not assertion

> This repo has already shipped a "concurrency proof" that passed while proving nothing — its threads
> serialized through an async route and never raced. **Every proof below must be demonstrated able to fail.**

- [ ] **PROOF-01**: Kill the worker mid-run → the run completes on the next drain. Vacuous if the job never
  actually leased; must assert the reclaim path fired and `attempts` incremented.

- [ ] **PROOF-02**: Redeliver the same Svix event → exactly one job, one run, one email. Vacuous if dedup is
  keyed on something available only post-fetch; must assert exactly one `jobs` row survives the `ON CONFLICT`.

- [ ] **PROOF-03**: Crash between Resend-accept and the `sent` commit → **no second email**. Vacuous if it
  passes against a fake gateway while SEND-01 is unfixed; must assert the persisted `message_id` is
  **byte-identical** across attempts.

- [ ] **PROOF-04**: An expired lease is reclaimed by a second worker, and the zombie's write is fenced —
  including `mark_failed`/`reschedule`, which is the fence people forget (not just `mark_done`).

- [x] **PROOF-05**: Every new integration test is registered in `concurrency-proof.yml` — the **only** workflow
  with a real Postgres, and it hard-codes its test files by name (`concurrency-proof.yml:89`). Three of the four
  proofs need a real database; land them outside that line and **they never run**. Races drive the **sync seam**
  under a `threading.Barrier`, never an HTTP route.

- [ ] **OPS-01**: An ops view surfaces queue depth, oldest-pending age, attempts, and the dead-letter list —
  making "it's healthy" a checkable claim rather than a vibe. Includes the alarm for the swallowing bug:
  *job success ≈100% while `status='error' > 0`.*

---

## Out of Scope (explicit exclusions)

| Excluded | Reason |
|---|---|
| Per-tenant fairness, priority lanes | Machinery for load that never arrives (~1 email/client/week). `jobs.business_id` and `jobs.priority` exist so this stays a later `ORDER BY` change, not a migration. All four researchers agree. |
| Adaptive backpressure | Meaningless here — you cannot push back on Resend's webhook. |
| Circuit breakers | A stuck-open breaker would silently blackhole a week's payroll — **worse than what it prevents**. |
| N-concurrent-email load chart | The durability proofs are the claims worth making; a throughput chart proves a property nobody is testing us on. |
| Autoscaling, distributed tracing, a metrics stack | It would scale between 2 and 2. |
| Operator authentication | A different axis from durability; folding it in would blur the milestone. Remains the known/accepted gap. |
| Async psycopg / a second async pool | Zero durability benefit, and it would mean rewriting the money-critical `app/db/repo/` package to async. |
| `uvicorn --workers N` | Now a load-bearing invariant: it would multiply both the connection pool and the worker threads per process, silently blowing the 5-connection budget. |

## Accepted residual risk

**An operator retrigger can legitimately send a second email.** It bumps `reply_epoch` by design (Phase 11 /
CLAR2-07), minting a new key under `uq_email_run_purpose_round_epoch` (`schema.sql:279`). This is intended
behavior — and it is exactly why the claim is *"at most once per approved run, per epoch"* rather than a flat
"never twice."

**Exactly-once delivery is not achievable.** It is the Two Generals problem, not a library gap. Publishing that
limitation honestly is itself the differentiator.

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| QUEUE-01 | Phase 16 | Complete |
| QUEUE-02 | Phase 16 | Complete |
| QUEUE-03 | Phase 16 | Complete |
| QUEUE-05 | Phase 16 | Complete |
| PUMP-01 | Phase 17 | Complete |
| PUMP-02 | Phase 17 | Complete |
| FAIL-01 | Phase 18 | Complete |
| FAIL-02 | Phase 18 | Complete |
| FAIL-03 | Phase 18 | Complete |
| QUEUE-04 | Phase 19 | Complete |
| SEND-01 | Phase 20 | Complete |
| SEND-02 | Phase 20 | Complete |
| SEND-03 | Phase 20 | Complete |
| PROOF-01 | Phase 21 | Pending |
| PROOF-02 | Phase 21 | Pending |
| PROOF-03 | Phase 21 | Pending |
| PROOF-04 | Phase 21 | Pending |
| PROOF-05 | Phase 21 | Complete |
| OPS-01 | Phase 21 | Pending |

**Coverage: 19/19 v4 requirements mapped, no orphans, no duplicates.**

Note: this milestone's header count ("the 17 REQ-IDs") undercounts by 2 against the actual enumerated
requirements below (QUEUE ×5, PUMP ×2, FAIL ×3, SEND ×3, PROOF ×5, OPS ×1 = 19). The roadmap maps all 19
IDs actually present in this file.
