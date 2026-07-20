# Architecture Research — v4 Durable Execution

**Domain:** Integrating a durable Postgres job queue into an existing Postgres status-column state machine (FastAPI, Render free, Supavisor transaction-mode pooling)
**Researched:** 2026-07-13
**Supersedes:** the v1-era architecture research at this path (the pipeline architecture it described is now shipped; its content lives in `CLAUDE.md` and `.planning/PROJECT.md`).
**Confidence:** HIGH on the integration points (traced against live source at `9975a86`, not guessed). HIGH on the claim/lease SQL. MEDIUM on the Render instance-hours budget (the arithmetic is certain; the 750h cap should be re-confirmed against current Render docs before committing to a pump cadence).

**Method:** every `file:function` reference below was read. The approved design (`docs/superpowers/specs/2026-07-13-durable-execution-design.md`) was validated line-by-line against that source. It is **mostly right and load-bearing** — but contains **one critical SQL defect, one critical phase-ordering defect, one false claim about shippability, and four gaps.** Those are in [What the approved design got wrong](#what-the-approved-design-got-wrong) and are the highest-value part of this document.

---

## 1. The two-state-machines hazard — the concrete, enforceable rule

The design doc says *"`jobs` is transport state only… never what payroll status comes next."* Right instinct, but **not enforceable as written** — it is a statement of intent, not an invariant. Here is the enforceable version.

### INVARIANT J-1 (single authority)

> **Every job handler's first durable action is a `claim_status(expected → next)` CAS on `payroll_runs.status`.**
> **A failed CAS is a SUCCESSFUL job (`state='done'`) — not a retry, not an error.**
> **Therefore: job execution is at-least-once; status transition is at-most-once.**
> **The job row therefore never needs to name a status, and must not contain one.**

This is not a platitude — it is a test-pinnable property, and the primitive already exists: `repo.claim_status` (`app/db/repo/runs.py:356-380`), whose docstring already states the exact contract ("Returns False if it was NOT in `expected` — the caller logs a late/duplicate and **drops cleanly WITHOUT re-running the work**"). `resume_pipeline` already obeys it (`app/pipeline/orchestrator.py:305-313`). `/runs/{id}/resolve` already documents *why* the route must not pre-claim and must let the handler own the sole CAS (`app/routes/runs.py:257-262`). **The queue does not introduce a new discipline; it generalizes one the repo already blessed in three places.**

### Where the boundary is, precisely

| Question | Answered by | Never answered by |
|---|---|---|
| *Is an operation owed?* | `jobs` row with `state IN ('pending','leased')` | `payroll_runs.status` |
| *Who owns it right now?* | `jobs.lease_token` + `leased_until` | — |
| *Is it safe to retry?* | `jobs.attempts` / `max_attempts` / `available_at` | — |
| *What payroll state is this run in?* | `payroll_runs.status` | `jobs` — **ever** |
| *What happens next to the payroll?* | `decide.py` → `final_action`, then the orchestrator | `jobs` — **ever** |

A job says **"someone should look at this run."** It never says **"this run is now extracting."**

### The divergence cases, resolved

**Job succeeds but the run didn't advance.** *Not divergence — the design working.* A handler whose CAS failed (another actor owns the run) executed correctly and completes `done`. `done` means *"this owed operation was executed exactly once against the state machine; the state machine decided what that meant."* It never means *"the run advanced."* Anyone reading `jobs.state='done'` as a business fact has violated J-1.

**The run advanced but the job didn't complete** (worker committed the orchestrator's transaction, then died before the completion `UPDATE`). This is the real hazard, and J-1 dissolves it: the lease expires → another worker reclaims → re-runs the handler → its CAS `received → extracting` fails because the run is now `awaiting_approval` → no-op → `done`. **J-1 is precisely what converts at-least-once job delivery into at-most-once state advance.**

**The one hole J-1 opens — and the design doc does not see it.** A worker that dies *mid-run* leaves the run in `extracting`. On reclaim, `claim_status(received → extracting)` **fails** (already `extracting`), the handler no-ops, the job goes `done`, and **the run is stranded in `extracting` forever with a completed job.** The naive CAS-first rule silently re-creates the exact bug this milestone exists to kill.

**Fix — the rewind preamble.** Reuse the primitive `retrigger` already blesses (`app/routes/runs.py:344-359` rewinds a stale `EXTRACTING → RECEIVED`):

```python
# app/queue/handlers/pipeline.py  (NEW)
def handle_run_pipeline(job: Job) -> JobResult:
    if job.attempts > 1:
        # Rewind MY OWN crashed attempt. Safe because dedup_key makes (kind, run_id, epoch) a
        # unique job, and SKIP LOCKED + the lease make ME its only live holder -- so the only
        # actor who could have left this run in EXTRACTING under this job is a prior attempt
        # of this same job.
        repo.claim_status(job.run_id, RunStatus.EXTRACTING, RunStatus.RECEIVED)

    if not repo.claim_status(job.run_id, RunStatus.RECEIVED, RunStatus.EXTRACTING):
        # Another actor owns this run (operator retrigger, reject, a reply resume).
        # Not an error. Not a retry. The state machine said no.
        return JobResult.ok("run not at RECEIVED — another actor owns it")

    return orchestrator.run_pipeline(job.run_id)   # returns ok / retryable / terminal
```

This **requires deleting the unconditional `repo.set_status(run_id, RunStatus.EXTRACTING)` at `app/pipeline/orchestrator.py:232`** and — critically — **requires `retrigger` to stop pre-claiming `RECEIVED → EXTRACTING`** (`app/routes/runs.py:352-356`), or the handler's CAS always loses and **every retrigger becomes a silent no-op.** That is a real integration bug that only appears when both changes land. Mirror `/resolve`'s documented pattern: the route enqueues, the handler owns the sole CAS.

### The mechanical guard (this repo's idiom: pin it or it drifts)

The repo already enforces `RunStatus` ↔ SQL CHECK set-equality with a CI drift test (`app/models/status.py:1-7` ↔ `app/db/schema.sql:74-86`), pins `_STRANDED_SCOPE_STATUSES` with a scope test, and enforces module boundaries with an AST guard (BOUND-01). Add four in the same spirit:

1. **`set(JobKind) ∩ set(RunStatus) == ∅`** — a job kind can never *be* a status.
2. **`set(JobKind) == set(jobs.kind CHECK list)`** — the same drift-test shape as the status one.
3. **`set(JobKind) == {name for name in dispatch.HANDLERS}`** — the kinds are exactly the pipeline entry points, no more.
4. **A source guard:** no `RunStatus` value string may appear in any `INSERT INTO jobs` / `UPDATE jobs` statement in `app/db/repo/jobs.py`.

That is what makes J-1 *enforced* rather than *asserted*.

---

## 2. Job granularity — coarse. One job per orchestrator entry point. Not per stage.

**Recommendation: 4 kinds, mapping 1:1 onto the 4 existing `pipeline_glue` entry points.** Not literally "one per run" — *one per invocation of an entry point*, which is subtly better (a run can legitimately own a `run_pipeline` job and later a `resume_reply` job).

| `kind` | Handler calls | Entry status (the CAS `expected`) |
|---|---|---|
| `ingest` | `gateway.parse_inbound` + the moved DATA-02 transaction | *(no run yet)* |
| `run_pipeline` | `orchestrator.run_pipeline` | `received` |
| `resume_reply` | `orchestrator.resume_pipeline(from_status=AWAITING_REPLY)` | `awaiting_reply` |
| `operator_resume` | `orchestrator.resume_pipeline(from_status=NEEDS_OPERATOR)` | `needs_operator` |

**Why `resume_reply` and `operator_resume` must stay distinct kinds:** they differ only in `from_status`. Merging them forces `from_status` onto the job row — **a status in the job row, a direct violation of J-1.** Keeping them distinct keeps that status *statically in code*, where it belongs. This is a load-bearing argument, not bookkeeping.

### Why per-stage is wrong for THIS pipeline (four independent reasons)

1. **There is no durable checkpoint between the stages.** `_run_stages` (`app/pipeline/orchestrator.py:862-1046`) commits extract → reconcile → validate → decide → persist → status advance in **one transaction** (line 999). A per-stage queue would first have to invent 4 new statuses and 4 persisted intermediate artifacts to have anything to checkpoint *on*.
2. **It would rewrite the thesis-bearing module.** The eval's credibility rests on "the eval imports and scores the exact same spine production runs on" (`_run_stages`' own docstring, lines 876-881; PROJECT.md's DRY-seam decision). Splitting the spine across job boundaries breaks the seam the project exists to demonstrate.
3. **Re-running from the top is already free and already safe.** `persist_extracted` OVERWRITES wholesale; `replace_line_items` is DELETE-by-run-then-INSERT (documented at `orchestrator.py:268-271`). Idempotent re-entry from stage 1 *is already the retrigger semantic*. A redo costs one bounded DeepSeek call (45 s ceiling, `max_retries=0`, `app/llm/client.py:218-224`). At ~1 payroll email per client per week, that is free.
4. **Fine grain *increases* the two-sources-of-truth risk.** A per-stage job must encode which stage is next — the exact forbidden duplicate of `payroll_runs.status`.

### The payload problem the design doc missed

The doc lists 3 kinds. There are **4 BackgroundTasks producers with 3 distinct signatures**, and two carry non-`run_id` arguments the doc's `jobs` table has nowhere to put:

- **`resume_pipeline_bg(run_id, inbound: InboundEmail)`** — an **object**. But it is already durable: the reply row is in `email_messages`, and `pipeline_glue.row_to_inbound` (`app/routes/pipeline_glue.py:25-52`) exists *precisely* to rebuild it from the row — exactly what the redelivery reschedule (`webhook.py:264`) and the stranded sweep (`runs.py:478`) already do. → **the job carries `email_id UUID`, a FK to the persisted row. Never the object.** This *deletes* the pass-a-parsed-object-through-memory pattern entirely.
- **`operator_resume_bg(run_id, overrides: dict[str, str])`** (`app/routes/runs.py:262`) — a **dict of business data**. A `jobs.payload` JSONB would reintroduce business data into transport state. → **new column `payroll_runs.operator_overrides JSONB`**, written in the same transaction as the enqueue. (`resolve()` already persists the adjacent `alias_candidates` this way at `runs.py:256` — same shape, same place.)

**Net rule: a `jobs` row carries only `(kind, dedup_key, run_id?, email_id?, event_id?, business_id?)` — all identifiers, zero business data.** That is J-1 made structural: there is physically nowhere to put a next-status.

---

## 3. Enqueue atomicity — the enqueue is a co-tenant of the transaction that owes it

Every helper in `app/db/repo/` already takes `conn: psycopg.Connection | None = None` and runs through `_conn_ctx` / `_nulltx` (`app/db/repo/_shared.py:19-50`). `enqueue_job(..., conn=conn)` slots into that with **zero new machinery** — it is just another aggregate module in the existing per-aggregate repo package.

### The pattern

```python
# THE RULE: the enqueue lives inside the SAME `conn.transaction()` as the state change that
# owes it. The CAS in that transaction supplies EXCLUSIVITY. The dedup_key UNIQUE supplies
# IDEMPOTENCY. You need both, or you get a lost job (state advanced, no job) or a phantom
# job (job, no state).

# app/routes/runs.py :: retrigger   (MODIFIED — one transaction replaces CAS-then-add_task)
with repo.get_connection() as conn, conn.transaction():
    claimed = (
        repo.claim_status(run_id, RunStatus.ERROR, RunStatus.RECEIVED, conn=conn)
        or repo.claim_status(run_id, RunStatus.APPROVED, RunStatus.RECEIVED, conn=conn)
        or _claim_stale_in_flight(run_id, conn=conn)
    )
    if claimed:
        epoch = repo.clear_reply_context(run_id, conn=conn)   # MODIFIED: return the new reply_epoch
        repo.enqueue_job(
            kind=JobKind.RUN_PIPELINE,
            run_id=run_id,
            dedup_key=f"run_pipeline:{run_id}:{epoch}",       # ◄── the epoch is the discriminator
            conn=conn,
        )
# committed. Only the CAS winner enqueued. A crash anywhere above → nothing happened at all.
return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
```

```sql
-- app/db/repo/jobs.py :: enqueue_job
INSERT INTO jobs (kind, dedup_key, run_id, email_id, event_id, business_id, available_at)
VALUES (%(kind)s, %(dedup_key)s, %(run_id)s, %(email_id)s, %(event_id)s, %(business_id)s, now())
ON CONFLICT (dedup_key) DO NOTHING
RETURNING id;
```

### `dedup_key` must carry an epoch, or the second legitimate retrigger is swallowed

A naive `dedup_key = f"run_pipeline:{run_id}"` means: run errors → operator retriggers → job runs, goes `done` → run errors again → operator retriggers again → `ON CONFLICT DO NOTHING` against the **old `done` row** → **the second retrigger silently does nothing.**

The discriminator already exists: **`payroll_runs.reply_epoch`**, bumped by `clear_reply_context` on every retrigger (`app/db/schema.sql:112-116`, called at `app/routes/runs.py:378`). Make `clear_reply_context` return the new epoch and key on it.

| kind | `dedup_key` |
|---|---|
| `ingest` | `ingest:{event_id}` (the Svix id, or the fixture content hash) |
| `run_pipeline` | `run_pipeline:{run_id}:{reply_epoch}` |
| `resume_reply` | `resume_reply:{run_id}:{email_id}` (the inbound row is the natural unique cause) |
| `operator_resume` | `operator_resume:{run_id}:{reply_epoch}:{seq}` — ⚠️ an operator may legitimately re-resolve with a *different* mapping without an epoch bump, so this one needs a discriminator or the second resolve is swallowed. **Open question — see §8.** |

**`resume_reply`'s key collapses two mechanisms into one.** Today a lost reply-resume is recovered by *two* independent seams — the redelivery reschedule (`webhook.py:241-270`) and the stranded-unconsumed-reply sweep (`runs.py:465-484`). Both would enqueue `resume_reply:{run_id}:{email_id}`; the UNIQUE makes them **the same row**. Two code paths, one job — and then both code paths can be deleted (§7).

---

## 4. The claim/lease protocol — the SQL, and what it actually protects

### The `jobs` table (NEW)

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- The 4 kinds mirror the 4 pipeline_glue entry points EXACTLY. A CI drift test asserts
    -- set-equality with JobKind AND with the dispatch table -- the same guard shape that pins
    -- payroll_runs.status against RunStatus. A kind is a FUNCTION NAME, never a status.
    kind          TEXT NOT NULL CHECK (kind IN
                    ('ingest','run_pipeline','resume_reply','operator_resume')),
    dedup_key     TEXT NOT NULL,
    -- Identifiers ONLY. No business data, no target status, no payload. This is INVARIANT J-1
    -- made structural: there is physically nowhere to put "what payroll status comes next".
    run_id        UUID REFERENCES payroll_runs(id) ON DELETE CASCADE,
    email_id      UUID REFERENCES email_messages(id),
    event_id      UUID REFERENCES inbound_events(id),
    -- NULLABLE by necessity: sender->business routing happens AFTER the Resend body fetch,
    -- which this design moves into the worker. The tenant key does not exist at ingress.
    -- Backfilled by the ingest handler.
    business_id   UUID REFERENCES businesses(id),
    priority      INT  NOT NULL DEFAULT 100,   -- WRITTEN, NEVER READ in v4 (fairness lanes are out of scope)
    state         TEXT NOT NULL DEFAULT 'pending'
                    CHECK (state IN ('pending','leased','done','dead')),
    attempts      INT  NOT NULL DEFAULT 0,
    max_attempts  INT  NOT NULL DEFAULT 5,
    available_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_token   UUID,
    leased_until  TIMESTAMPTZ,
    last_error    TEXT,   -- PII-scrubbed through the EXISTING repo._scrub/_build_error_detail (OPS2-01)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_jobs_dedup_key UNIQUE (dedup_key),
    -- A half-written lease (state='leased' with a NULL token) is indistinguishable from an
    -- unclaimed job, and the fencing check below would silently degrade to "no fence at all".
    -- The database refuses to store one. Same discipline as employees.step_3_dependents >= 0.
    CONSTRAINT ck_jobs_lease_coherent CHECK (
        (state =  'leased' AND lease_token IS NOT NULL AND leased_until IS NOT NULL) OR
        (state <> 'leased' AND lease_token IS NULL     AND leased_until IS NULL)
    )
);

-- Partial index matching the claim predicate EXACTLY. done/dead rows (the overwhelming
-- majority over time) are not in the index at all, so the claim stays O(1) forever with no
-- purge job.
CREATE INDEX IF NOT EXISTS idx_jobs_claimable
    ON jobs (priority, available_at)
    WHERE state IN ('pending','leased');
```

### The claim — ONE statement, ONE implicit transaction, commits before any real work

```sql
UPDATE jobs j
   SET state        = 'leased',
       lease_token  = gen_random_uuid(),
       leased_until = now() + (%(lease_seconds)s || ' seconds')::interval,
       attempts     = j.attempts + 1,      -- attempt-on-CLAIM, not on failure. See below.
       updated_at   = now()
 WHERE j.id = (
       SELECT c.id
         FROM jobs c
        WHERE c.attempts < c.max_attempts
          AND (
                (c.state = 'pending' AND c.available_at <= now())
             OR (c.state = 'leased'  AND c.leased_until <  now())   -- ◄── RECLAIM AN EXPIRED LEASE
              )
        ORDER BY c.priority, c.available_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
 )
RETURNING j.id, j.kind, j.run_id, j.email_id, j.event_id,
          j.attempts, j.max_attempts, j.lease_token;
```

**The `OR (state='leased' AND leased_until < now())` clause is the single most important line in this document.** The approved design's claim SQL (`design.md:150-153`) is `WHERE state = 'pending' AND available_at <= now()` and **nothing else** — so a job whose worker died holding the lease stays `state='leased'` **forever** and is never reclaimed. That is the exact failure the milestone exists to eliminate, reintroduced by the queue meant to fix it. **The design's own Phase D proof #4 ("let a lease expire, let a second worker claim the job") would fail against the design's own SQL.**

Three things that make this correct under **Supavisor transaction-mode pooling**:

- **One statement ⇒ one implicit transaction.** No session state, no `LISTEN/NOTIFY`, no session-level advisory locks — all forbidden on port 6543. (`app/db/supabase.py:1-18` already documents why session state is fatal here: `prepare_threshold=None` exists for exactly this reason.)
- **`FOR UPDATE SKIP LOCKED` lives in the SUBQUERY**, and the outer `UPDATE` re-targets by `id`. A bare `UPDATE … LIMIT 1` is not valid Postgres, and `FOR UPDATE` on the outer statement does not give you row-skipping.
- **It commits immediately, releasing the pooled connection before any LLM / Resend / PDF call.** With `max_size=5` (`app/db/supabase.py:57-68`), holding a transaction across a 45-second LLM call would pin 20% of the entire connection budget per worker. `_run_stages` already honors this discipline — see the explicit comment at `orchestrator.py:1015-1018`: *"No transaction may span a network/LLM call."* **The queue inherits that rule; it does not invent it.**

**Attempt-on-claim is correct and non-obvious.** Incrementing `attempts` at *claim* time (not at failure time) is what bounds a **crash loop**: a worker that OOMs or is SIGKILLed before recording *anything* still burned an attempt, so a poison job dead-letters instead of looping forever. The design got this right; preserve it deliberately — and it means **the completion path must never also increment.**

### The completion — fenced on `lease_token`

```sql
UPDATE jobs
   SET state = 'done', lease_token = NULL, leased_until = NULL, updated_at = now()
 WHERE id = %(id)s AND state = 'leased' AND lease_token = %(token)s
RETURNING id;
```

`row is None` ⇒ **the lease was stolen; this worker is a zombie.** It must **not** retry, **not** error the run, **not** re-enqueue. It logs and drops. *This is the identical contract to `claim_status` returning `False`* — the repo already has the "lost the CAS → drop cleanly" idiom in four places; the fencing check is the fifth and should read the same way.

### The failure / retry — fenced, with dead-letter atomic against the run's ERROR

```sql
UPDATE jobs
   SET state = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'pending' END,
       available_at = now() + (%(backoff_seconds)s || ' seconds')::interval,
       last_error   = %(scrubbed_detail)s,
       lease_token  = NULL, leased_until = NULL, updated_at = now()
 WHERE id = %(id)s AND state = 'leased' AND lease_token = %(token)s
RETURNING state;
```

Backoff + jitter computed **in Python** (`min(cap, base * 2 ** (attempts - 1)) * uniform(0.5, 1.5)`) so it is unit-testable without a clock. When `RETURNING state` is `'dead'`, **the same transaction** calls `repo.record_run_error(run_id, "JobDeadLettered", stage=job.kind, conn=conn)` — so **`job dead ⟺ run in ERROR` is atomic.** That is what lets `sweep_stranded_runs` be deleted (§7).

### THE CRUX: the fencing token does **not** protect the business writes

This is the question's hardest sub-part, and the design's rule 2 (*"Every completion or failure write must match the `lease_token`"*) quietly overclaims. State it precisely:

> **The `lease_token` fences the `jobs` row and nothing else.** The orchestrator's business writes committed in a *different* transaction (`orchestrator.py:999`), minutes earlier, with no token in scope. There is no way to make `_run_stages` lease-aware without threading a transport token into the money path — which is J-1 inverted.
>
> **The business writes are fenced by `claim_status`, and only by `claim_status`. The lease is an optimization (don't pay for two DeepSeek calls); the CAS is the correctness.**

Reason the split-brain case out loud, because it is the only honest way to state the guarantee. Worker A **stalls** (network partition, not death) while holding a lease. The lease expires. Worker B reclaims and re-runs. Both are now executing `_run_stages` for the same run. What is the damage?

| Side effect | Guard that ALREADY exists | Outcome |
|---|---|---|
| Status advance | `claim_status` CAS | Exactly one wins. A's later `set_status` calls inside `_run_stages` are unguarded — **but both write the same forward transitions to the same values**, so they are idempotent by value. |
| Paystub line items | `replace_line_items` = DELETE-by-run + INSERT (`orchestrator.py:1012`) | Last-write-wins over identical inputs. No duplicate rows. |
| Extracted / decision / reconciliation | `persist_*` OVERWRITE one JSONB cell (`orchestrator.py:268-271`) | Last-write-wins. |
| **Clarification email to the client** | `uq_email_run_purpose_round_epoch` UNIQUE (`schema.sql:279`) + `get_outbound_for_round` (CLAR2-01) | **A second send is blocked by a DB constraint.** |
| **Confirmation email to the client** | purpose-aware already-sent guard (`delivery.py:95-113`) + the same UNIQUE | **Blocked.** |
| Job completion | `lease_token` fence | A's completion is rejected. Only B's counts. |

**The honest guarantee, then:** *a stalled-not-dead worker whose lease expired can double-**execute** the pipeline; the damage is bounded to a duplicated LLM call and a last-write-wins persist, because **every side-effecting write is already individually guarded by a DB constraint or a CAS.** No client is emailed twice; no paystub is duplicated; no status regresses.* A generous lease makes it vanishingly rare.

**Therefore `lease_seconds = 900` (15 min).** Not tight — and *derived*, not guessed. The derivation already exists in this repo: `app/routes/runs.py:34-68` computes the worst-case gap between two consecutive DB writes on the longest real path at **210 s** (the resume path's back-to-back double extraction — 45 s × 2 app-attempts × 2 calls — plus a 30 s clarification draft) and picks 15 min as ~4×. **Reuse `STALE_THRESHOLD` as `QUEUE_LEASE_SECONDS`: one constant, one already-reviewed derivation.**

---

## 5. Worker lifecycle on Render free

### Startup: `lifespan` — and `app/main.py` currently has none

`app/main.py` is 16 lines with no lifespan at all.

```python
# app/main.py (MODIFIED)
from contextlib import asynccontextmanager
from app.queue import worker

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # FAIL FAST at startup, in the pydantic-settings spirit: a worker count that starves
    # ingest / approvals / dashboard reads of connections is a config bug, not a runtime
    # surprise. Pool max_size=5 (app/db/supabase.py:57-68).
    assert settings.queue_workers + 3 <= 5, "worker count would starve the connection pool"
    worker.start(n=settings.queue_workers)
    yield
    worker.stop(grace_seconds=10)   # sets a threading.Event, joins, AND RELEASES HELD LEASES

app = FastAPI(title="Payroll Agent", lifespan=lifespan)
```

### The workers are OWN threads — NOT the AnyIO threadpool

`BackgroundTasks` and `run_in_threadpool` both execute on Starlette's shared ~40-thread AnyIO pool — **the same pool that serves every sync route** (`approve`, `retrigger`, `runs_list`, `run_detail`). A long-lived worker loop parked there permanently consumes a request-serving slot. Use `threading.Thread(daemon=True)` with an owned lifecycle. (The AnyIO pool *is* the right tool for the short ingest hop in §7 phase 1 — that's a burst, which is what it's for.)

### Worker count: **2** — a connection-budget decision, not a throughput one

The design's Finding 3 is correct and is the most under-appreciated constraint here: **the ceiling is 5 connections, not 40 threads.**

| Consumer | Connections (transient) |
|---|---|
| Webhook ingest | 1 |
| Dashboard reads (`/runs`, `/runs/{id}`, `/runs/{id}/status` polled every 2 s) | 1–2 |
| Operator approve → `delivery.deliver` | 1 |
| **Workers** | **2** |

Workers hold a connection only in **short bursts** — the claim statement, the orchestrator's persist transaction, the completion statement — and never across an LLM/Resend/PDF call (§4). So 2 fit comfortably. Make it a settings knob (`QUEUE_WORKERS`, default 2) with the startup assertion above. At ~1 email/client/week, worker count is a **safety** parameter, not a scaling knob. Say so in the README.

### The pump: what drains the queue when nothing is knocking

Render free has **no worker service type** and wakes **only on inbound HTTP**. Internal timers sleep with the dyno. Without an external pump, a job with a future `available_at` is **durable storage that is never executed** — which the design doc correctly calls *"a worse lie than the current design, which at least fails visibly."* That framing is right and must survive into the roadmap.

- **`POST /internal/pump`** (NEW, `app/routes/internal.py`) — shared-secret auth via **`hmac.compare_digest`** (constant-time; this repo already cares about this class of thing). Drains **inline and bounded**: claim-and-run up to `K` jobs or `T` seconds, then return `{"claimed": n, "done": n, "retried": n, "dead": n, "depth": d, "oldest_pending_age_s": s}`. **Returning real counts is what gives the GitHub Action something to fail on** — a pump that merely wakes the service and hopes the background workers notice is unassertable.
- **Safe to run concurrently with the background workers** — it uses the same `SKIP LOCKED` claim. That is what `SKIP LOCKED` is for.
- **The pump also owns retention:** `DELETE FROM inbound_events WHERE received_at < now() - interval '30 days'`. The design calls for "a byte cap and a retention policy" but names no executor. **The pump is the only recurring execution context this system has.** It is the executor.

### ⚠️ Pump cadence vs the 750 free instance-hours cap — an unflagged collision

A pump every **10 minutes** means the service is *never* idle for 15 minutes ⇒ **it never spins down** ⇒ it is awake ~**720–744 hours/month** against a **750 h/month** free cap. That is **six hours of margin**, and only if this is the **sole free web service in the workspace**. Over the cap, free services suspend until the next month — taking the live demo down.

| Option | Recovery latency | Instance-hours/mo | Note |
|---|---|---|---|
| **10-min pump (RECOMMENDED)** | ~10 min | **~720–744** — at the cap | Also eliminates cold-start latency on real inbound webhooks (Resend's webhook timeout never fires). **Requires: exactly one free web service in this workspace, documented as a hard constraint.** |
| 20-min pump | ~20 min | ~54 (the service sleeps between pumps; each pump costs a ~1-min cold start + ~30 s work) | Cheap, huge margin — but "recovers within *minutes*" starts to strain at 20. |

**Recommend 10 min**, and add *"exactly one Render free web service in this workspace"* to the milestone Constraints. This is a real, checkable deploy constraint that is currently written down nowhere.

**Fold `keepalive.yml` into `pump.yml`.** The pump call *is* a Render wake *and* a Supabase query — it strictly subsumes the existing 2×/week `/health/ready` ping (`.github/workflows/keepalive.yml:16-20,39-55`). Keep that workflow's `workflow_dispatch` escape hatch, whose comment already documents GitHub's 60-day auto-disable — the single most important honesty caveat in this milestone. **One workflow replaces two. Net deletion.**

### Dyno spins down mid-job → what happens to the lease

1. The process dies. The `leased` row sits with a `leased_until` in the future. Nothing else changes.
2. At `leased_until`, the row becomes claimable **via the `OR (state='leased' AND leased_until < now())` clause** — which is why that clause is non-negotiable.
3. The next pump wakes the service and reclaims it. `attempts` is now ≥ 2, so the handler's **rewind preamble** (§1) resets the run from `extracting` to its entry status and re-CASes forward. The run completes.
4. **Worst-case recovery = `lease_seconds` (15 min) + pump interval (10 min) ≈ 25 minutes.** Put that number in the README. Do not write "minutes" and let the reader infer 2.

### Graceful shutdown must release the lease — the design omits this

A Render **redeploy** is routine (several times a day during development). Without a release, every in-flight job strands for a full 15-minute lease *plus* a pump interval. One statement in `worker.stop()` fixes it:

```sql
UPDATE jobs SET state='pending', available_at=now(),
                lease_token=NULL, leased_until=NULL, updated_at=now()
 WHERE id=%(id)s AND state='leased' AND lease_token=%(token)s;
```

Turns a 25-minute stall into a sub-second handoff on every deploy.

---

## 6. Ingest re-keying — two layers, and why neither is redundant

Moving the Resend body-fetch (`gateway._parse_resend_envelope` → `resend.EmailsReceiving.get(email_id)`, `app/email/gateway.py:158-201`) out of the request path means **the RFC `Message-ID` — today's dedup key — is not known at ingest.** Once the fetch is in the worker, every Resend redelivery would mint a fresh `ingest` job.

### Layer 0 — transport dedup, at ingress: `inbound_events.event_id UNIQUE`

```sql
CREATE TABLE IF NOT EXISTS inbound_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- The Svix event id for a signed Resend webhook; 'sha256:<hex>' of the raw body for an
    -- UNSIGNED dev/fixture POST (which carries no svix-* headers at all). Content-addressing
    -- the fixture path preserves today's semantics EXACTLY -- the same bytes twice is the same
    -- event -- and keeps the tests exercising the same UNIQUE the production path uses.
    event_id    TEXT NOT NULL,
    signed      BOOLEAN NOT NULL,
    payload     JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_inbound_events_event_id UNIQUE (event_id)
);
```

`event_id = request.headers["svix-id"]` when signed, else `f"sha256:{hashlib.sha256(raw_body).hexdigest()}"`. The signature is already verified *before* this point (`webhook.py:70-85`), so the header is trusted. Fixture tests that want a fresh run already vary the `message_id`, which varies the body, which varies the hash — **semantics preserved, zero test churn.**

### Layer 1 — message dedup, one layer deeper: `email_messages.message_id UNIQUE` — **UNCHANGED**

`uq_message_id` (`app/db/schema.sql:260`) and `insert_inbound_email`'s `ON CONFLICT (message_id) DO NOTHING RETURNING id` (`app/db/repo/runs.py:82-105`) **stay exactly as they are.** They simply now execute inside the ingest *worker* instead of the webhook.

### Why both layers are required — the crisp argument

They are **not** redundant, and the reason is the *retry of the ingest job itself*:

> A worker crashes **after** the Resend fetch but **before** the ingest transaction commits. The job retries. It carries the **same `event_id`** — Layer 0 cannot help, and must not: the event was legitimately accepted and the work is legitimately still owed. The retry re-fetches, re-derives the same RFC `Message-ID`, and re-enters the ingest transaction — where **Layer 1's `message_id` UNIQUE is the only thing that stops a second run from being created.**
>
> **Layer 0 dedups the DELIVERY. Layer 1 dedups the MESSAGE. The ingest job's own retry is precisely the case that needs both.**

### The move, not the rewrite

The **entire five-outcome ingest-decision transaction** (`app/routes/webhook.py:139-220` — duplicate / reply_candidate / late_reply / unknown_sender / new_run) **moves verbatim into `app/queue/handlers/ingest.py`**, with `gateway.parse_inbound` in front of it.

That block **is** DATA-02. It survived Phase 9's atomicity surgery and is one of the three surfaces in Phase 10's real-Postgres concurrency proof. Its correctness argument is 80 lines of comments earned across two adversarial reviews. **Move it wholesale — `git mv`, function-for-function. Do not rewrite it.** Rewriting re-opens evidence that was expensively earned. (The AST-diff discipline v3's Phase 13 used for the god-file splits is the right proof technique here.)

The post-commit response-shaping block (`webhook.py:224-314`) does **not** move — it *dissolves*. The redelivery reschedule (`webhook.py:241-270`) becomes `enqueue_job(kind=RESUME_REPLY, dedup_key=f"resume_reply:{run_id}:{email_id}")` inside the ingest transaction. `finish_reply_resume` (`pipeline_glue.py:80-131`) keeps its sender revalidation (**`reply_sender_ok`, `pipeline_glue.py:55-77` — the spoof guard, which MUST survive intact and MUST be re-asserted in the `resume_reply` handler exactly as it is today at `webhook.py:257` and `runs.py:472`**) and loses its `BackgroundTasks` parameter.

### A free win nobody named

Once the fetch is in the worker, **the webhook's request payload is bounded by construction** — Resend's inbound webhook envelope is *metadata only* (`email_id`, `from`, `to`, `subject`). A 20 MB email attachment never touches the request path at all.

Combine with an explicit cap on `await request.body()` (`webhook.py:57`, currently **unbounded** — `demo.py`'s 4000-char cap does **not** protect the real webhook): **`MAX_WEBHOOK_BODY_BYTES = 256 * 1024`, reject with 413.** Without the cap, a durable raw inbox will happily persist an oversized body and then retry it forever.

---

## 7. Build order — and the design's "cannot be split" claim is **false**

### The refutation

> *Design doc, Phase A:* "The original plan split 'unblock the front door' and 'add a queue' into two phases. **It cannot be split**: 'persist raw → enqueue' requires the queue to exist. Merged."

**This conflates *one implementation* of unblocking with unblocking itself.** Unblocking the front door means: *no synchronous Resend HTTP call and no multi-query psycopg transaction on the event loop.* You can achieve that **today, with zero new schema, in one line**:

```python
# app/routes/webhook.py :: inbound  — Phase 1, no queue required
raw_body = await request.body()                            # genuinely async — fine on the loop
gateway.verify(raw_body, dict(request.headers), secret)    # pure-CPU HMAC — fine on the loop
result = await run_in_threadpool(_ingest_sync, raw_body)   # ◄── EVERYTHING blocking, off the loop
```

`starlette.concurrency.run_in_threadpool` is the exact primitive Starlette uses for sync endpoints — **the same mechanism `pipeline_glue`'s sync `def` wrappers already exploit on purpose** (their docstrings say so). The Resend fetch and the psycopg transaction now run off the loop. **Head-of-line blocking is gone. Independently shippable. Independently testable** (fire 2 concurrent webhooks against a stubbed slow `parse_inbound`; assert wall-clock ≈ max, not sum).

What it does *not* fix: a Resend outage still 502s the webhook and still triggers redelivery. **But that is a different defect (availability) from the one Finding 2 names (event-loop blocking).** Conflating them is what produced the false "cannot be split."

**Why the split matters practically:** it lets the riskiest change in the milestone — new schema + worker threads + leases + a connection-budget change — land on a webhook that is **already known-good under concurrent load**, instead of changing both at once.

### ⚠️ The design's phase ordering ships a regression window

The design orders **A** (full webhook cutover to the queue) → **B** (the pump) → **C** (retry policy + the result contract). Between the end of A and the end of C, the system is **strictly less durable than it is today**:

- The webhook now hands work to a queue, but **there is no pump** — a job with a future `available_at` never fires. (The design's own §"load-bearing constraint" calls this *"a worse lie than the current design."*)
- The orchestrator still **swallows stage failures into `ERROR` and returns normally** (`orchestrator.py:235-247`, `850-859`) — so **the worker records success on a failed payroll**, and there is no retry policy to catch it.
- Meanwhile Phase A says *"Keep the dashboard sweep until the queue is proven"* — so `sweep_stranded_runs` (15-min threshold) is now **racing** the queue's lease reclaim (also ~15 min) **on the same run.**

**The pump and the failure policy must precede the webhook cutover.** That is a correctness ordering, not a preference.

### ⚠️ Keeping `sweep_stranded_runs` alongside the queue IS the two-sources-of-truth hazard, literally

Two independent recovery mechanisms, both firing at ~15 minutes, both authorized to write `payroll_runs.status`, on the same run:

> The sweep flips a stale `extracting` run to **ERROR** (`repo.sweep_stranded_runs`, `app/db/repo/runs.py:394-450` — the *sanctioned third status writer*). Simultaneously the queue reclaims the expired lease and re-runs the handler, whose CAS now fails against `error` → no-op → job `done`. **The run sits in ERROR awaiting a human retrigger — and the milestone's headline claim ("recovers automatically within minutes, without a human noticing") is defeated by the very mechanism that was supposed to be a safety net.**

**The sweep is not "retired later." It is REPLACED — in the same phase the failure policy lands.** The sweep only *guesses* a worker died, from `updated_at`. The queue **knows**: expired lease → reclaim → attempts exhausted → `dead` → `record_run_error(run_id, "JobDeadLettered")`, **atomically, in the failure transaction** (§4). A strictly better answer to the identical question. That lets you **delete**:

- `repo.sweep_stranded_runs` (`app/db/repo/runs.py:394-450`) + `_STRANDED_SCOPE_STATUSES` + its scope-pin test
- `repo.find_stranded_unconsumed_replies` (`app/db/repo/emails.py:306`)
- **the entire sweep block in `runs_list()` (`app/routes/runs.py:463-486`)** — the dashboard-page-load-as-cron hack, the ugliest thing in the current architecture
- the redelivery-reschedule branch (`webhook.py:241-270`) — subsumed by `resume_reply`'s `dedup_key`

**A net deletion of the recovery machinery, replaced by one mechanism that is actually correct.** For a portfolio project read by hiring managers, *"the queue let me delete the three recovery hacks"* is a far stronger story than *"the queue was added alongside them."*

### The phase sequence — 7 steps, each independently shippable

| # | Phase | NEW | MODIFIED | **Shippable claim (provable at this step)** |
|---|---|---|---|---|
| **1** | **Unblock the loop** *(no schema)* | — | `webhook.py:inbound` → `run_in_threadpool`; `MAX_WEBHOOK_BODY_BYTES` cap on `webhook.py:57`; `config.py` | *"The webhook no longer blocks the event loop; a slow Resend fetch delays only its own request."* **Refutes the design's "cannot be split."** |
| **2** | **Queue substrate + ONE producer** | `schema.sql` → `jobs`; `app/models/job.py` (`JobKind`/`JobState`/`JobResult`); `app/db/repo/jobs.py`; `app/queue/{worker,dispatch}.py`; `lifespan` in `main.py` | `runs.py:retrigger` (the **only** producer cut over); pool-budget assertion | *"A retrigger survives a redeploy."* Kill the process mid-run, restart, assert completion. **Learn leases / pool / lifecycle on the cheapest, most observable surface — not on the money path.** BackgroundTasks stays for everything else; the two systems coexist for exactly one phase, safely, because each producer uses exactly one mechanism. |
| **3** | **The pump** | `app/routes/internal.py` (`POST /internal/pump`, `hmac.compare_digest`); `.github/workflows/pump.yml` | **delete `keepalive.yml`** (subsumed) | *"A job scheduled with a future `available_at` fires with no human present."* **MUST precede the webhook cutover** — after cutover, a lost job is a lost payroll. |
| **4** | **Failure policy + the CAS + the sweep deletion** | `JobResult` classification: `APITimeoutError`/`APIConnectionError`/`RateLimitError`/`psycopg.OperationalError` → **retryable**; `ValidationError`, the `orchestrator.py:1073` integrity raise, a gate decision → **terminal**; **unknown → terminal (fail closed)** | `run_pipeline`/`_run`/`resume_pipeline` **return** `JobResult` instead of `None`; `run_pipeline` gains the rewind preamble + CAS (delete `orchestrator.py:232`); `retrigger` stops pre-claiming; **DELETE `sweep_stranded_runs` + `find_stranded_unconsumed_replies` + `runs_list()`'s sweep block** | *"A transient LLM outage retries and recovers; a poison job dead-letters into a visible ERROR; the dashboard is no longer load-bearing for recovery."* **MUST precede the webhook cutover** — otherwise a DeepSeek 503 on a real payroll email is a permanent ERROR with no retry. |
| **5** | **Webhook cutover + raw inbox + re-keying** | `schema.sql` → `inbound_events`; `app/queue/handlers/ingest.py` (**the verbatim-moved DATA-02 transaction**); `payroll_runs.operator_overrides JSONB` | `webhook.py:inbound` → verify → threadpool(persist raw + enqueue) → 200; migrate remaining producers (`runs.py:262`, `demo.py:205`, `demo.py:313`, `runs.py:simulate_reply`); `pipeline_glue` wrappers become handlers | *"No accepted email is ever lost — the raw signed event is durable before we do anything with it, and the body fetch is a retryable job, not a 502."* |
| **6** | **Exactly-once send** | `email_messages.provider_message_id TEXT`; `repo.get_reserved_message_id(run_id, purpose, round, epoch)` | `gateway.send_outbound` (`app/email/gateway.py:271-289`): **reuse** the reserved `message_id` on retry (never mint a fresh `uuid4`) + pass it as `resend.Emails.SendOptions(idempotency_key=...)`; persist `provider_message_id` | *"A crash between Resend accepting the mail and the `sent` commit sends no second email."* **VERIFIED against the installed SDK:** `resend==2.32.2` ships `Emails.SendOptions.idempotency_key` (`resend/emails/_emails.py:187-202`), emitted as the `Idempotency-Key` header (`resend/request.py:65-66`). The design's key insight is confirmed. Independent of Phase 5 — could land in parallel. |
| **7** | **Proofs + ops view** | `tests/test_queue_durability.py` (the 4 proofs); `GET /internal/queue`; `POST /internal/jobs/{id}/retry` | `concurrency-proof.yml` | The 4 proofs. **⚠️ 3 of the 4 need a real Postgres, and `concurrency-proof.yml` is the ONLY workflow that has one — and it hard-codes a single test file.** Generalize it, or the proofs never run in CI. Consider pulling that generalization forward into Phase 2. |

**Forced dependency order (not preference):** 2 → 3 → 4 → 5. The pump and the failure policy are **prerequisites** of the cutover, not follow-ups. Phase 1 is independent of everything. Phase 6 is independent of 5. Phase 7 is last by definition.

---

## What the approved design got wrong

Ordered by severity. Every item traced against live source.

| # | Severity | Finding |
|---|---|---|
| **1** | 🔴 **CRITICAL** | **The claim SQL cannot reclaim an expired lease.** `design.md:150-153` reads `WHERE state = 'pending' AND available_at <= now()`. A job whose worker died holding the lease stays `state='leased'` **forever**. **The design's own Phase D proof #4 would fail against the design's own SQL.** Fix: add `OR (state='leased' AND leased_until < now())`. See §4. |
| **2** | 🔴 **CRITICAL** | **The phase ordering ships a window in which the system is *less* durable than today.** A (webhook→queue) lands before B (the pump) and C (retry + the result contract). Between them: no drain for future-dated jobs; the orchestrator still swallows failures and returns normally, so **the worker records success on a failed payroll**; and the sweep is being *kept*, racing the queue. **Pump and failure policy must precede the cutover.** See §7. |
| **3** | 🟠 **HIGH** | **"Unblock the front door is not independently shippable" is false.** `await run_in_threadpool(...)` around the existing body unblocks the loop with **zero new schema**, using the exact mechanism `pipeline_glue` already relies on. The doc conflated *event-loop blocking* (Finding 2) with *fetch-in-the-request-path* (an availability concern). Separating them de-risks the entire milestone. |
| **4** | 🟠 **HIGH** | **Keeping `sweep_stranded_runs` alongside the queue is the two-sources-of-truth hazard in literal form** — two status writers, both firing at ~15 min, on the same run, with the sweep winning by flipping to ERROR just as the queue reclaims. The sweep must be **replaced by the dead-letter transition**, not "retired once the queue is proven." Also a net code deletion (3 recovery hacks removed). |
| **5** | 🟠 **HIGH** | **The 4th producer is missing.** The doc names 3 kinds. `operator_resume_bg(run_id, overrides: dict)` (`runs.py:262`) carries a **dict of business data** with nowhere to live — needs a 4th kind + `payroll_runs.operator_overrides JSONB`. And `resume_pipeline_bg(run_id, inbound: InboundEmail)` carries an **object** — it must become an `email_id` FK (which `pipeline_glue.row_to_inbound` already knows how to rehydrate). |
| **6** | 🟡 **MEDIUM** | **`lease_token` fencing does not protect the business writes** — only the `jobs` row. The doc's rule 2 implies more safety than it delivers. The real guarantee comes from `claim_status` + `uq_email_run_purpose_round_epoch` + `replace_line_items`' delete-then-insert. State it precisely, or the milestone repeats the "eval chart was lying" mistake it already had to correct once. See §4 crux. |
| **7** | 🟡 **MEDIUM** | **A 10-min pump collides with Render's 750 free instance-hours/month.** It keeps the service permanently awake (~720–744 h/mo vs a 750 h cap — six hours of margin, and only if it is the sole free service in the workspace). Unflagged anywhere. Must become a documented deploy constraint. |
| **8** | 🟡 **MEDIUM** | **No graceful lease release on shutdown.** A Render redeploy — routine, several times a day — strands every in-flight job for `lease + pump interval` ≈ 25 min. One `UPDATE … SET state='pending'` in the lifespan teardown fixes it. |
| **9** | 🟢 **LOW** | **`inbound_events` retention has no executor.** The doc calls for "a byte cap and a retention policy" but names nobody to run it. **The pump is the only recurring execution context in the system.** It owns retention. |

### What the design got RIGHT (and must survive into the roadmap)

- **`jobs` is transport-only; `payroll_runs.status` stays the sole business state machine.** Correct, and it is the milestone's thesis. It just needed teeth (INVARIANT J-1).
- **`business_id` must be nullable** — sender→business routing (`webhook.py:195-220`) happens *after* the fetch, so the tenant key does not exist at ingress. Exactly right.
- **The pump is not optional.** *"Durable storage is not durable execution"* is the sharpest sentence in the document, and it is true.
- **The reserved `message_id` is already a durable pre-send idempotency key** (`gateway.py:271-289` mints it and writes a `reserved` row *before* calling Resend — then discards it). **Verified: `resend==2.32.2` accepts it.** This is the best insight in the design.
- **"Never mint a fresh `uuid4` on retry"** — the subtle one, correctly identified. A fresh synthetic id becomes a fresh idempotency key, which defeats the provider check entirely and sends the second payroll email.
- **Infrastructure failures stay in `error`, not `needs_operator`.** Confirmed against source: `/resolve` genuinely requires `decision.unresolved_names` (`runs.py:208-213`) and would 303-noop on a run whose extraction timed out — an unserviceable state. Correct call.
- **No session-level advisory locks, no `LISTEN/NOTIFY`.** Correct, and `app/db/supabase.py:1-18` already documents why session state is fatal under Supavisor transaction-mode.
- **Five connections is the ceiling, not forty threads.** The most under-appreciated constraint in the whole design.
- **Throughput machinery is out of scope.** At ~1 email/client/week, fairness lanes and backpressure would be machinery for load that never arrives. `priority` and `business_id` on the row keep each a future `ORDER BY` change rather than a migration. Right call, right reason.

---

## Integration points — complete NEW vs MODIFIED inventory

### NEW

| Path | Purpose |
|---|---|
| `app/db/schema.sql` → `jobs` | Transport state. 4-value `kind` CHECK, 4-value `state` CHECK, `uq_jobs_dedup_key`, `ck_jobs_lease_coherent`, `idx_jobs_claimable` partial index. |
| `app/db/schema.sql` → `inbound_events` | The durable raw inbox. `uq_inbound_events_event_id`. |
| `app/db/schema.sql` → `payroll_runs.operator_overrides JSONB` | The `operator_resume` payload — kept OUT of the job row. |
| `app/db/schema.sql` → `email_messages.provider_message_id TEXT` | Durable send evidence (today only logged, `gateway.py:347-353`). |
| `app/models/job.py` | `JobKind` / `JobState` / `Job` / `JobResult`. Canonical Python enums mirrored into SQL CHECKs and pinned by a drift test — **the exact pattern `app/models/status.py` establishes.** |
| `app/db/repo/jobs.py` | `enqueue_job` / `claim_job` / `complete_job` / `fail_job` / `release_lease` / `queue_stats` / `retry_dead_job`. A new aggregate in the existing per-aggregate repo package, exported through the `app/db/repo/__init__.py` facade. Every function takes `conn=` and runs through `_shared._conn_ctx`. |
| `app/queue/worker.py` | Thread pool + claim loop + lifecycle (`start` / `stop` with lease release). |
| `app/queue/dispatch.py` | The `kind → handler` table. **The only place a kind maps to a function.** |
| `app/queue/handlers/ingest.py` | `gateway.parse_inbound` + **the verbatim-moved** `webhook.py:139-220` ingest transaction. |
| `app/queue/handlers/pipeline.py` | The rewind preamble + CAS + orchestrator dispatch for the 3 run-scoped kinds. |
| `app/routes/internal.py` | `POST /internal/pump`, `GET /internal/queue` (ops view), `POST /internal/jobs/{id}/retry`. |
| `.github/workflows/pump.yml` | `*/10` cron + `workflow_dispatch`. **Absorbs and replaces `keepalive.yml`.** |

### MODIFIED

| File:function | Change |
|---|---|
| `app/main.py` | Add `lifespan=` (**currently none** — the file is 16 lines). Start/stop workers; assert the connection budget. |
| `app/routes/webhook.py:inbound` | Phase 1: `run_in_threadpool` hop + body cap on line 57. Phase 5: verify → persist `inbound_events` + `enqueue(ingest)` → 200. **Lines 139-220 MOVE OUT verbatim.** |
| `app/routes/pipeline_glue.py` | `run_pipeline_bg` / `resume_pipeline_bg` / `operator_resume_bg` become job handlers. `finish_reply_resume` / `route_reply` drop their `BackgroundTasks` param. **`reply_sender_ok` (the spoof guard, lines 55-77) survives untouched** and must be re-asserted in the `resume_reply` handler exactly as today. |
| `app/pipeline/orchestrator.py:195-247` (`run_pipeline` / `_run`) | Delete the unconditional `set_status(EXTRACTING)` (line 232). Return `JobResult`. Classify the except block (line 235) into retryable/terminal instead of always writing ERROR. |
| `app/pipeline/orchestrator.py:250-859` (`resume_pipeline`) | Return `JobResult`. Classify the except block (line 850). **Its existing CAS (line 305) already obeys J-1 — do not touch it.** |
| `app/routes/runs.py:266-381` (`retrigger`) | CAS + `clear_reply_context` + `enqueue_job` in **one transaction**. **Stop pre-claiming `RECEIVED → EXTRACTING`** (lines 352-356) or the handler's CAS always loses. |
| `app/routes/runs.py:159-263` (`resolve`) | Persist `operator_overrides` + `enqueue_job` in one transaction. (It already correctly declines to pre-claim — that pattern is now the rule.) |
| `app/routes/runs.py:444-503` (`runs_list`) | **DELETE the sweep block (lines 463-486).** |
| `app/routes/runs.py:684-809` (`simulate_reply`) | Enqueue `resume_reply` instead of `add_task`. |
| `app/routes/demo.py:205, 313` | Enqueue `run_pipeline` in the same transaction as `create_run`. |
| `app/email/gateway.py:209-359` (`send_outbound`) | Reuse an existing `reserved` row's `message_id` on retry; pass `options={"idempotency_key": message_id}` to `resend.Emails.send`; persist `provider_message_id`. |
| `app/db/repo/runs.py:394-450` | **DELETE `sweep_stranded_runs`** + `_STRANDED_SCOPE_STATUSES`. |
| `app/db/repo/emails.py:306` | **DELETE `find_stranded_unconsumed_replies`.** |
| `app/db/repo/runs.py` (`clear_reply_context`) | Return the new `reply_epoch` (needed for the `dedup_key`). |
| `app/config.py` | `queue_workers=2`, `queue_lease_seconds=900`, `queue_max_attempts=5`, `pump_secret`, `max_webhook_body_bytes=262144`. |
| `.github/workflows/concurrency-proof.yml` | Generalize — it is **the only workflow with a real Postgres** and it hard-codes one test file. 3 of the 4 durability proofs need a DB. |

---

## Data-flow changes

**Today**
```
Resend ──POST──► inbound()  [async def — ON THE EVENT LOOP]
                    │
                    ├─ verify (HMAC, cheap)
                    ├─ parse_inbound ──► SYNC HTTP to the Resend API   ◄── BLOCKS THE LOOP
                    ├─ clean_body
                    ├─ ingest transaction (multi-query psycopg)         ◄── BLOCKS THE LOOP
                    └─ background_tasks.add_task(run_pipeline_bg)       ◄── IN PROCESS MEMORY.
                       └─► 200                                              Dies on redeploy /
                                                                            spin-down. Recovered
                                                                            ONLY by a human loading
                                                                            /runs.
```

**After**
```
Resend ──POST──► inbound()  [async def]
                    ├─ verify (HMAC, cheap — stays on the loop)
                    └─ run_in_threadpool:
                         ┌── ONE TRANSACTION ───────────────────────────┐
                         │  INSERT inbound_events                       │  atomic:
                         │    ON CONFLICT (event_id) DO NOTHING         │  no lost job,
                         │  if inserted:                                │  no phantom job
                         │    INSERT jobs (kind='ingest')               │
                         │      ON CONFLICT (dedup_key) DO NOTHING      │
                         └──────────────────────────────────────────────┘
                    └─► 200   (bounded, ~5 ms, no third-party call, no LLM)

worker thread (×2, lifespan-owned)   ──or──   POST /internal/pump (cron, */10)
    │
    ├─ claim_job()  ── ONE STATEMENT, COMMITS IMMEDIATELY. FOR UPDATE SKIP LOCKED.
    │                  Reclaims expired leases. Releases the connection before any work.
    │
    ├─ dispatch[kind](job):
    │     ingest          → parse_inbound (the Resend fetch — RETRYABLE now, not a 502)
    │                       → the moved DATA-02 transaction (message_id UNIQUE = layer 1)
    │                       → enqueue(run_pipeline | resume_reply)   ◄── SAME TRANSACTION
    │     run_pipeline    → [rewind if attempts>1] → claim_status(received→extracting)
    │                       → orchestrator.run_pipeline → JobResult
    │     resume_reply    → reply_sender_ok (the spoof guard) → resume_pipeline(AWAITING_REPLY)
    │     operator_resume → resume_pipeline(NEEDS_OPERATOR, overrides read from payroll_runs)
    │
    └─ complete_job(id, lease_token)   ◄── FENCED. A zombie's write is rejected.
       or fail_job(...) → backoff+jitter → 'pending', or → 'dead'
                                             └─► record_run_error(run_id, "JobDeadLettered")
                                                 ATOMIC with the dead transition.
                                                 ◄── this REPLACES sweep_stranded_runs.
```

---

## Anti-patterns — specific to this integration

### AP-1: Putting the next payroll status in the job row
**What people do:** `jobs.next_status = 'extracting'`, or `jobs.payload = {"from": "awaiting_reply"}`.
**Why it's wrong:** two rows now answer "what happens next," and they *will* diverge — a retried job replays a transition the run has already moved past.
**Instead:** the `kind` implies the entry status **statically, in code**. Keep `resume_reply` and `operator_resume` as **separate kinds** precisely so `from_status` never needs a column.

### AP-2: Holding the claim transaction across the work
**What people do:** `BEGIN; SELECT … FOR UPDATE; <run the pipeline>; COMMIT;` — the "obvious" way to guarantee exclusivity.
**Why it's wrong:** it pins one of **five** pooled connections for up to 3.5 minutes (the derived worst case at `runs.py:34-68`), and **transaction-mode pooling on port 6543 hands your next statement to a different backend anyway.** Two workers doing this consume 40% of the pool while doing nothing.
**Instead:** claim → **commit** → work → **fenced** completion. The lease *replaces* the held lock. (The codebase already knows this: `orchestrator.py:1015-1018` explicitly forbids spanning a transaction across an LLM call.)

### AP-3: Treating `jobs.state='done'` as a business fact
**What people do:** an ops page that reports "12 payrolls processed" by counting `done` jobs.
**Why it's wrong:** a job whose CAS failed is *correctly* `done` and processed nothing. Under J-1 that is not a bug — it is the design. Reading it as a business fact re-couples the two state machines through the **reporting** layer, which is where this class of bug loves to hide.
**Instead:** every business number comes from `payroll_runs`. The queue's ops view reports queue metrics only (depth, oldest-pending age, attempts, dead list).

### AP-4: Running two recovery mechanisms "until the new one is proven"
**What people do:** exactly what the design says — keep `sweep_stranded_runs` alongside the queue.
**Why it's wrong:** both write `payroll_runs.status`, both fire at ~15 minutes, and the sweep wins the race by flipping the run to ERROR just as the queue reclaims the lease — **defeating the milestone's headline claim with its own safety net.**
**Instead:** the dead-letter transition **replaces** the sweep, atomically and with better information (it *knows* the worker died; the sweep only guesses from `updated_at`). Delete the sweep in the same phase.

### AP-5: An in-process timer to drain the queue
**What people do:** `asyncio.create_task(drain_forever())` in the lifespan.
**Why it's wrong:** Render free wakes **only on inbound HTTP**. The timer sleeps with the dyno. A job retried with a future `available_at` sits forever. You have shipped durable *storage* and called it durable *execution*.
**Instead:** the external pump. The in-process workers are the **fast path** (they drain immediately while the service happens to be awake); the pump is the **guarantee**.

### AP-6: Rewriting the ingest transaction instead of moving it
**What people do:** "while we're in here," re-derive the 5-outcome classification in the new handler.
**Why it's wrong:** `webhook.py:139-220` **is** DATA-02. It survived Phase 9's atomicity surgery and is one of the three surfaces in Phase 10's real-Postgres concurrency proof. Its correctness argument is 80 lines of comments earned across two adversarial reviews.
**Instead:** **move it function-for-function** and prove the move behavior-neutral against the existing tests (the same AST-diff discipline v3's Phase 13 used for the god-file splits). Then change nothing else.

---

## Scaling considerations *(honest — this milestone is explicitly not about throughput)*

| Load | What actually happens | Adjustment |
|---|---|---|
| **Real load (~1 email/client/week)** | The queue is empty ~100% of the time. Every job is claimed within milliseconds by an already-running worker. The pump never finds anything. | **None. This is the design point.** |
| **Burst (a demo click-storm; ~10 concurrent)** | 2 workers × ~2 min/run ≈ 10 min to drain. The dashboard stays responsive (the loop is unblocked; the workers don't touch the AnyIO pool). | None. Raise `QUEUE_WORKERS` to 3 *only if* the pool assertion still passes. |
| **The first thing that actually breaks** | **The 5-connection pool** — not the threadpool, not the queue. `ConnectionPool(timeout=5)` starts raising `PoolTimeout`. | Raise `max_size` (Supavisor transaction-mode tolerates it far better than a direct connection would) **before** touching worker count. |
| **The second thing** | Supabase free-tier storage — `inbound_events.payload` JSONB is retained forever without the pump's retention sweep. | The 30-day retention DELETE. Already in the design (it just needed an executor). |
| **Genuine multi-tenant scale** | `ORDER BY priority, available_at` becomes `ORDER BY priority, <per-business round-robin>, available_at`. | **Already a one-line `ORDER BY` change, not a migration** — `business_id` and `priority` are on the row from day one. The design's best deferred decision. |

---

## 8. Open questions for the roadmapper

1. **`operator_resume`'s `dedup_key` needs a discriminator.** An operator may legitimately re-resolve with a *different* mapping without an epoch bump, and `ON CONFLICT DO NOTHING` would swallow the second resolve. Bump `reply_epoch` on resolve too? Or add an explicit `resolve_seq` column? **Decide before Phase 5.**
2. **Pump cadence: 10 min (at the 750 h cap, always-on, no cold starts) vs 20 min (huge margin, ~20-min worst-case recovery).** A *product* decision about how literally "within minutes" is meant. Recommend 10 min + document *"exactly one free web service in this workspace"* as a hard constraint.
3. **`concurrency-proof.yml` is the only CI workflow with a real Postgres, and it hard-codes one file.** 3 of the 4 durability proofs need a DB. Generalizing it is a prerequisite for Phase 7 — and probably deserves to be pulled forward into Phase 2 so the queue's tests run in CI from the start.
4. **Should `jobs` cascade-delete from `payroll_runs`?** A cascade silently vaporizes a run's attempt history. Runs are never deleted today, so this is theoretical — but `email_messages` is deliberately append-only, and `jobs` arguably should be too.

---

## Sources

- **Live source, read at `9975a86`** (every line reference above): `app/routes/{webhook,pipeline_glue,runs,demo,health}.py`, `app/pipeline/{orchestrator,delivery}.py`, `app/email/gateway.py`, `app/db/supabase.py`, `app/db/schema.sql`, `app/db/repo/{_shared,runs,emails}.py`, `app/models/status.py`, `app/main.py`, `app/config.py`, `.github/workflows/keepalive.yml`, `pyproject.toml`. **HIGH — traced, not inferred.**
- **`resend==2.32.2`, installed in `.venv`** — `resend/emails/_emails.py:187-202` (`Emails.SendOptions.idempotency_key`) and `resend/request.py:65-66` (emitted as the `Idempotency-Key` header). **Verified by direct inspection. HIGH.**
- `docs/superpowers/specs/2026-07-13-durable-execution-design.md` (`3ed7db9`) — the approved design under validation.
- `.planning/PROJECT.md` — v4 milestone scope, constraints, and the Render/Supavisor facts.
- **Postgres `SELECT … FOR UPDATE SKIP LOCKED` queue pattern** — the subquery-targeted `UPDATE` is the standard correct form; `FOR UPDATE` on the outer `UPDATE` does not skip locked rows. **HIGH.**
- **Supavisor transaction-mode constraints** — no session state, no `LISTEN/NOTIFY`, no session advisory locks. Already documented and defended in `app/db/supabase.py:1-18` (the `prepare_threshold=None` rationale). **HIGH.**
- **Render free tier** — no worker service type, 15-min idle spin-down, inbound-HTTP-only wake, ephemeral FS, 750 instance-hours/month. Per `.planning/PROJECT.md` Context + the v1 STACK research. **MEDIUM on the 750 h figure — re-confirm against current Render docs before committing to the 10-min pump cadence.**

---
*Architecture research for: durable job queue ↔ Postgres status-column state machine integration*
*Researched: 2026-07-13*
