# Pitfalls Research — v4 Durable Execution

**Domain:** Adding a Postgres-backed durable job queue + in-process worker pool to an existing, shipped, money-moving transactional pipeline (FastAPI · Supavisor transaction-mode pooler · `ConnectionPool(max_size=5)` · Render free · GitHub Actions as the only timer).
**Researched:** 2026-07-13
**Confidence:** HIGH on the code-traced findings (every "smoking gun" below cites a live line I read, not a guess). HIGH on Supavisor/pgbouncer transaction-mode semantics and Render free-tier accounting (verified against vendor docs + corroborating sources). HIGH on the queue/lease/fencing canon. MEDIUM on Resend `Idempotency-Key` retention semantics (SDK support verified in the design doc; the provider's dedup *window* is not verified — see Gap G-1).

> **Scope discipline.** This document deliberately does NOT rehearse generic "be careful with concurrency" advice. Every pitfall below is either (a) traced to a specific line in this repo, or (b) a specific property of *this* deployment (Supavisor 6543, 5 connections, Render free, GH cron). Where the approved design (`docs/superpowers/specs/2026-07-13-durable-execution-design.md`) already guards a pitfall, it is marked **[DESIGN COVERS]** and the entry only records the *residual* gap. Where the design is silent, it is marked **[DESIGN GAP]** — those are the ones the roadmap must not lose.

**Phase labels** map to the approved design: **A** = durable handoff, **B** = the pump, **C** = failure policy + exactly-once send, **D** = prove it. Two pitfalls demand a **Phase A-0** (a small pre-flight *before* the queue exists) — flagged inline.

---

## The five findings that are new (not in the approved design)

Read these first. Everything else is elaboration.

| # | Finding | Why it matters | Phase |
|---|---------|----------------|-------|
| **G-1** | `insert_email_message`'s outbound upsert does `ON CONFLICT (run_id,purpose,round,epoch) DO UPDATE SET message_id = EXCLUDED.message_id` (`app/db/repo/emails.py:83-89`). A retry **overwrites** the reserved row's `message_id` with a fresh `uuid4`. The design says "reuse the reserved `message_id`" but the write path *erases the row it needs to read*. | Defeats the idempotency key **and** erases the reply-threading anchor of an email that may already be in the client's inbox. | **C** |
| **G-2** | A pump cadence frequent enough to be useful (< 15 min) keeps the Render free service **permanently awake** → ~730 instance-hours/month against a **750 h/workspace/month** budget. Zero headroom. The design never costs the pump. | The service **suspends until next month** if the budget blows — the demo dies, silently, mid-month. | **B** |
| **G-3** | The send idempotency guards filter on `send_state = 'sent'` (`delivery.py:88`, `emails.py:180-193`). `reserved` and `failed` are **not** `sent` — and `failed` is written on *any* Resend exception, **including a timeout after the mail was accepted**. The design only names `reserved` as the reuse case. | A `failed` row is not proof of non-delivery. Retrying it with a fresh key sends the second payroll email. | **C** |
| **G-4** | `gateway.send_outbound(send_state=...)` is a **dead parameter** on the outbound path: both callers pass `send_state="sent"` (`delivery.py:196`, `clarification.py:493`) and the function hard-codes `send_state="reserved"` in its insert (`gateway.py:286`). | Anyone "fixing" send state via that parameter will change nothing and believe they did. A live trap during Phase C. | **C** (+ A-0 to delete it) |
| **G-5** | The Phase-10 concurrency proof was already once vacuous (threads serialized through an `async def` route; Surface A passed even with the `ON CONFLICT` clause deleted). Every durability proof in Phase D is exposed to the **same** failure mode, amplified: a queue test that drives an HTTP endpoint proves the endpoint, not the queue. | A green-but-vacuous durability suite is *worse* than no suite — it launders a false claim. | **D** |

---

## Critical Pitfalls

### Pitfall 1: Durable storage that is not durable execution — the "queue that never drains"

**What goes wrong:**
Jobs commit reliably to Postgres. Nothing ever runs them. The failure is invisible in every test (a test process is always awake) and catastrophic in production: `available_at = now() + 30s` on a retry is a promise the platform cannot keep, because on Render free **only inbound HTTP wakes the service** — an internal `sleep()`, a `threading.Timer`, an `asyncio` background loop, and an APScheduler job all sleep *with* the process. The 15-minute idle spin-down vaporizes the worker; the lease expires; the row becomes eligible; **no process exists to claim it**. The run sits at `extracting` forever with a durable job row proudly asserting that work is owed.

**Why it happens:**
"Durable" is an adjective people attach to the *table*. It is a property of the **loop**. Every Postgres-queue tutorial assumes a long-lived worker process (a `worker` dyno, a systemd unit, a k8s Deployment). Render free has **no worker service type**. The tutorial's most load-bearing assumption is the one this platform removes, and it is never stated out loud, so it is never noticed as missing.

**How to avoid:**
- **[DESIGN COVERS]** `POST /internal/pump` — an authenticated endpoint that claims and drains due jobs — called by external cron. This is the whole ballgame; it is what converts storage into execution.
- **Also drain opportunistically on any inbound HTTP.** Every real webhook, every dashboard load, every approval already wakes the service — each is a free pump tick. Wire a bounded drain (claim ≤ N jobs, hard wall-clock budget) into the request path so recovery does not depend *solely* on a scheduler nobody controls.
- **Ban every in-process timer.** No `asyncio.create_task` + `sleep` loop, no APScheduler, no `threading.Timer`. Add a CI grep guard the same way the repo already guards module boundaries (BOUND-01) and status-enum drift. If it sleeps, it dies with the dyno.
- **Write the honest guarantee before writing the code.** GitHub Actions cron is documented best-effort: **5–30 minute delays are normal**, hour-plus delays occur under load, the minimum interval is 5 minutes, and scheduled workflows **auto-disable after 60 days without a push** (this repo's `keepalive.yml` already carries a `workflow_dispatch` escape hatch and a comment explaining exactly that). So the true claim is:

  > *Automatic recovery, typically within 5–30 minutes. Best-effort: the pump is driven by GitHub Actions cron, which is not a scheduler — it can be delayed under load and auto-disables after 60 quiet days. The dashboard sweep and operator retry are the documented fallbacks.*

  Not "within minutes." The repo already had to correct one lying artifact (the v3 eval chart). Do not mint a second one in the README.

**Warning signs:**
- Any retry path that computes a future `available_at` without a sentence somewhere explaining *what process will be alive to see it*.
- A durability test that passes in `pytest` (process always alive) with no equivalent that proves the drain happens from a **cold start**.
- The word "worker" in a design doc, unqualified, on a platform with no worker.

**Phase to address:** **B** (the pump is the phase). But the *ban on in-process timers* and the *opportunistic drain seam* belong in **A** — build the drain function as a plain callable (`drain(max_jobs, budget_seconds)`) with no scheduler attached, so B just wires an HTTP route to it and the request path can call it too.

---

### Pitfall 2: The pump eats the free tier — a cadence/budget collision the design never costs [DESIGN GAP]

**What goes wrong:**
Render grants **750 free instance-hours per workspace per calendar month**, and a service **consumes them whenever it is running** (a spun-down service consumes none). It spins down after **15 idle minutes**.

Do the arithmetic the design skipped: a pump at **any cadence under 15 minutes** means the service is *never* idle for 15 minutes, so it **never spins down**, so it burns **~730 hours** (a 31-day month) out of 750. That is **97% of the workspace budget with ~20 hours of headroom** — and the headroom is shared with *every other free service in the workspace*, and consumed by deploy churn. Blow it and free services **suspend until the next calendar month**. The demo URL in `PROJECT.md` — the thing a hiring manager clicks — goes dark, and it goes dark *silently*, at whatever point in the month the budget ran out.

The design's stated cadence is "every 5–10 minutes." That is exactly the collision.

**Why it happens:**
Two constraints are individually well-understood in this repo (the 15-minute spin-down is in `PROJECT.md`; the 750-hour cap is in `CLAUDE.md`) and were never **multiplied together**. The pump was scoped as a *latency* decision ("how fast must recovery be?") when it is also a *budget* decision ("how many hours may we spend staying awake?").

**How to avoid:** pick one, explicitly, and write the number down:
1. **Accept permanent wakefulness (recommended).** Confirm the Render workspace hosts **exactly one** free web service, pump at 10 minutes, and budget ~730 h/month deliberately. Add a checked assertion to the milestone: "this workspace contains one free service." *Upside: the cold-start problem in the demo disappears too — the service is always warm.* This is very likely the right call for a portfolio demo, but it must be a **decision**, not an accident.
2. **Cadence > 15 min.** The service sleeps between pumps; hours drop sharply. But recovery latency becomes 15–45 min (cadence + GH cron's own 5–30 min slop), which materially weakens the milestone's headline claim.
3. **Duty-cycle the pump.** Frequent during a demo window, sparse otherwise. Cute, but it makes the guarantee time-of-day dependent — hard to state honestly. Avoid.

Also: on a **public** repo, Actions minutes are free — verify the repo is public before committing to a 5-min cron, or ~8,600 runs/month will shred a private repo's 2,000-minute budget.

**Warning signs:**
- A cron cadence chosen without anyone stating the resulting monthly instance-hours.
- Render's usage page trending toward 750 mid-month.
- A second free service (a staging deploy, a preview env) quietly added to the same workspace.

**Phase to address:** **B**, as an explicit written decision with the arithmetic in the phase doc, and a line in `PROJECT.md`'s Key Decisions table. Do not let the cadence be a config default nobody defended.

---

### Pitfall 3: Connection-pool starvation — `max_size=5` is the real ceiling, and an LLM call inside a checked-out connection is the way you hit it

**What goes wrong:**
`ConnectionPool(min_size=1, max_size=5, timeout=5)` (`app/db/supabase.py:57-69`) is the **entire** database budget for the process: N workers **plus** the ingest path **plus** the operator approval POST **plus** every dashboard page load **plus** the pump's own claim query **plus** `/health/ready`'s `SELECT 1`. The design already names this (Finding 3). What it does not name is the *shape of the failure*, which is the part that gets missed in review:

- **Symptom 1 — everything looks like a DB outage.** `pool.timeout=5` means a starved caller raises `PoolTimeout` after 5 seconds. The dashboard's `except Exception: render empty list` (`runs.py:490`) swallows it and shows an **empty runs list** — an operator sees "no runs" during the exact incident they need to see runs. `/health/ready` fails → the keepalive workflow turns **RED** → you go looking for a Supabase outage that isn't happening.
- **Symptom 2 — the failure is self-amplifying.** Starved requests time out → Resend's webhook times out → Resend **redelivers** → more work lands on an already-starved app.
- **Symptom 3 — deadlock-by-budget.** If workers hold connections while blocked on an LLM call, 5 workers × 45s extraction timeout = **five connections pinned for 45 seconds** and *zero* left for ingest, approval, or the pump itself. The pump cannot even claim a job to discover that the queue is backed up.

**Why it happens:**
Two seductive, wrong instincts:
1. *"Open the connection once per job, close it at the end."* It reads as efficient. It is the single worst thing you can do here: it pins a connection across LLM + PDF + Resend I/O, i.e. across *minutes*, and it is also **incompatible with transaction-mode pooling** (see Pitfall 4).
2. *"Size the pool to the threadpool."* AnyIO's ~40 threads is a decoy. The binding constraint is 5.

**How to avoid — the sizing rule, stated as an invariant:**

> **`worker_concurrency + reserved_headroom ≤ max_size`**, where `reserved_headroom ≥ 2` (one for ingest, one for the operator/dashboard/health path). With `max_size=5`: **worker concurrency = 2**, headroom = 3. Three, not two, because the pump's claim query is itself a connection *and* it may run concurrently with an operator approval.

Concretely:
- **Every DB touch is a short, self-contained checkout.** `with repo.get_connection() as conn, conn.transaction(): ...` around a bounded set of statements, then **release**. The orchestrator already follows this discipline and *documents why* (`orchestrator.py:1015-1018`: "No transaction may span a network/LLM call"). The queue must inherit it, not regress it.
- **The claim transaction commits before any real work begins.** **[DESIGN COVERS]** — this is rule 1 of the design's claim protocol. Hold the line in review.
- **Make worker concurrency a named constant with a comment naming `max_size`,** not a magic `3`. If someone later bumps `max_size`, the relationship should be discoverable by grep.
- **Consider raising `max_size` — carefully.** Supavisor transaction-mode connections are cheap-ish, but the free-tier Supabase pooler has its own client cap. If you raise it, raise the reserved headroom proportionally, and re-run the pool-starvation proof (below). Do not raise it as a reflex to make a test pass.
- **Do not swallow `PoolTimeout` into "empty list."** Distinguish "DB unreachable" from "pool exhausted" in `runs.py`'s handler and render a visible degraded-state banner. An operator staring at an empty runs list during an incident is a *user-facing* failure of an operations tool.

**Warning signs:**
- A `get_connection()` whose `with` block contains a call into `app/llm/`, `app/email/`, or `reportlab`.
- Pool-timeout / "couldn't get a connection" entries in the Render log.
- `/health/ready` flapping while Supabase's own status page is green.
- A worker-count constant that does not mention `max_size` within three lines of itself.

**Phase to address:** **A** (bound worker concurrency against the connection budget — design already calls for it). The *proof* is **D** (Pitfall 12). The `PoolTimeout`-vs-outage distinction in the dashboard is a small **A** or **C** carve-out.

---

### Pitfall 4: Supavisor transaction-mode pooling — the queue primitives that *silently* break

**What goes wrong:**
Port 6543 is **transaction-mode** pooling: a backend connection is held only for the duration of a transaction, then handed to somebody else. Everything session-scoped is a trap. The critical asymmetry — and the reason this one is dangerous rather than merely annoying:

| Primitive | Failure mode under transaction pooling | Loud or silent? |
|---|---|---|
| **Session advisory locks** (`pg_advisory_lock`) | Acquired on one backend, "released" against another; locks leak and never release; two workers can both believe they hold the lock. | **SILENT.** No error. It just doesn't do what you think. **This is the worst one.** |
| **`LISTEN` / `NOTIFY`** | You subscribe on one backend and receive on another — notifications simply never arrive. | **SILENT.** The queue looks like it "just has latency," forever. |
| **Server-side prepared statements** | Prepared on backend A, executed on backend B: `prepared statement "..." does not exist`. Only appears *after* a statement has run a few times (psycopg3's default `prepare_threshold=5`), so it never shows up in a smoke test. | **LOUD** — and **already fixed**: `kwargs={"prepare_threshold": None}` (`app/db/supabase.py:65`), with the whole failure mode documented in the module docstring. |
| **Session `SET` / GUCs / `SET ROLE`** | Leak into the next transaction on the same backend, or vanish before your next statement. | **SILENT.** |
| **Session-scoped temp tables** | Gone, or worse, someone else's. | **SILENT.** |
| **`FOR UPDATE SKIP LOCKED` inside one transaction** | Works perfectly. Row locks are transaction-scoped. | ✅ **This is why the design is right.** |

**Why it happens:**
Every "Postgres as a queue" article eventually reaches for `pg_advisory_lock` — as a singleton-worker guard, a "only one pump at a time" mutex, or a per-run mutex. It is the most natural-feeling tool in Postgres for exactly the problem the queue has. **And it silently does nothing here.** There is no error, no warning, no log line. You will write it, it will pass every local test against a direct Postgres connection (port 5432, session mode — where it works!), and it will be a no-op in production. That local-vs-prod divergence is what makes this a genuine footgun rather than a documented limitation.

**How to avoid:**
- **Row leases + CAS only.** **[DESIGN COVERS]** — the design bans session advisory locks explicitly. Enforce it: add `pg_advisory_lock`, `pg_advisory_unlock`, `LISTEN`, `NOTIFY` to a **CI grep guard** over `app/`. This repo already has the muscle for exactly this (the BOUND-01 AST guard, the status-enum drift test, the comment-hygiene guard). A code-review promise is not a guard; a failing CI job is.
- If a lock is ever genuinely unavoidable, it must be **`pg_advisory_xact_lock`** (transaction-scoped) and held for milliseconds. Prefer not needing it.
- **No `LISTEN/NOTIFY` wake-ups.** The tempting "NOTIFY on enqueue so the worker starts instantly instead of polling" optimization is doubly dead here: it is broken by the pooler *and* useless on a platform where the process may not exist to listen. Poll on the pump tick. Accept it.
- **Test against 6543, not 5432, wherever the queue's locking semantics are being asserted.** The `concurrency-proof.yml` workflow runs an ephemeral `postgres:16` container — i.e. **session mode, direct**. That environment *cannot reproduce* the transaction-mode failures. It is still the right place for the race proofs (Postgres semantics are the same); it is the **wrong** place to conclude "our locking works." Cover the pooler-specific behavior with a grep guard, not a test that cannot fail.

**Warning signs:**
- Any of the banned identifiers in `app/`.
- A queue behavior that works locally and "mysteriously does nothing" on Render — that shape *is* the session-state signature.
- Anyone proposing "just use session mode (5432) for the workers." Session mode holds a backend for the connection's entire life; with 5 pooled connections and a sleeping dyno that is a *worse* trade, and it splits the app across two pooler modes.

**Phase to address:** **A** (the claim protocol and its CI guard land with the queue). Re-assert at **C** when retry/backoff tempts a "let me just take a lock while I compute the next `available_at`."

---

### Pitfall 5: Lease/fencing bugs — the zombie worker that commits a stale result

**What goes wrong:**
The canonical sequence:

1. Worker **W1** claims job J (lease 5 min), starts a run. The extraction LLM call stalls.
2. The lease expires. J becomes eligible again.
3. Worker **W2** (or a pump tick after a redeploy) claims J, rotates the lease token, runs the pipeline, **sends the client the payroll email**, marks J done.
4. **W1 wakes up.** It has no idea anything happened. It writes its own result: `UPDATE jobs SET state='done' WHERE id = J` — clobbering W2's bookkeeping — and, far worse, it **continues into the pipeline** and re-sends, re-persists, re-advances status.

That is double-processing on a money path.

**Why it happens:**
The lease is treated as *mutual exclusion* when it is only a *hint*. A lease cannot prevent a stalled process from waking up — nothing can. The only defense is that the zombie's **writes are rejected**, and that defense has to be present at **every** write, not just the obvious one. The classic omission: developers remember to fence `mark_done()`, and forget to fence `mark_failed()` / `reschedule()` / the heartbeat / the attempt-counter bump. A zombie that "only" writes a failure is still corrupting the queue — it can move a job W2 already completed into `pending` and cause a **third** execution.

**How to avoid — the standard fence, stated precisely:**

> **Every** job-state write carries `WHERE id = %s AND lease_token = %s AND state = 'leased'`, and **checks the affected-row count**. Zero rows affected = "I am a zombie" = abandon everything, log, **do not** raise into the run's error path (the run is not broken; *you* are stale).

Enforcement, concretely:
- **Make it structurally impossible to write a job row without a token.** One module (`app/queue/`) owns every `UPDATE jobs`; the functions take `lease_token` as a **required positional** argument. A grep for `UPDATE jobs` outside that module is a CI failure.
- **Fence the *side effects*, not only the bookkeeping.** This is the step people skip and it is the one that matters here. Before the run's **irreversible** step — the Resend send — re-verify lease ownership *inside the same transaction* that records the send intent. A fenced `mark_done` that runs *after* the client has already been emailed twice has protected nothing.
- **Fortunately, this project has a second, independent fence already.** `repo.claim_status(run_id, from, to)` is an atomic CAS on `payroll_runs.status`, and `resume_pipeline` already uses it (`orchestrator.py:305`). A zombie re-running a resume loses the CAS and drops cleanly. **But `run_pipeline` does NOT** — it writes `received → extracting` unconditionally (`orchestrator.py:232`). **[DESIGN COVERS]** — "give the initial pipeline an atomic claim" is on the Phase A list. It is arguably the single highest-value line item in Phase A: it turns the run state machine into a *second, independent* fence behind the lease, so a lease bug alone cannot double-process. **Do not let it get cut.**
- **Lease duration must exceed the worst-case job.** Bound it from the code, not from vibes: extraction 45 s (`llm/client.py:218`), clarification 30 s, confirmation 3 s, plus a *second* extraction on Round-2 resumes (`orchestrator.py:496,499` — two `extract()` calls), plus PDF generation, plus the Resend send. A 5-minute lease is plausible; **write the arithmetic down**, and set the lease from a constant that cites those timeouts. A lease shorter than the work it guards is a **guaranteed** zombie generator, not a possible one.
- **Prefer a lease long enough that expiry is rare + rely on the fence, over a short lease + heartbeats.** Heartbeats mean another connection checkout on a 5-connection budget, and another thing to get wrong.

**Warning signs:**
- Any `UPDATE jobs` in a diff whose `WHERE` clause lacks `lease_token`.
- A `mark_failed` / `reschedule` path that is not fenced (the classic).
- A lease timeout smaller than the sum of the LLM timeouts.
- `run_pipeline` still writing `EXTRACTING` unconditionally after Phase A.

**Phase to address:** **A** (fence in the claim protocol + the `run_pipeline` CAS claim). **C** (fence the retry/dead-letter writes — the ones people forget). **D** (the reclaim-safety proof).

---

### Pitfall 6: Duplicate side effects — retrying a job that already emailed the client [MOSTLY DESIGN GAP]

This is the money pitfall. It has five variants; the design names one and a half.

#### Variant A — the fresh-key mint (**[DESIGN COVERS]**, but the fix is harder than stated — see G-1)

The design correctly identifies it: on retry, `send_outbound` mints a **new** `uuid4` synthetic `message_id`, which becomes a **new** `Idempotency-Key`, which defeats provider-side dedup, which sends the client a second payroll email.

**What the design misses:** the reserved row you intend to reuse is **destroyed by the retry itself.** Look at the write:

```sql
-- app/db/repo/emails.py:83-89
ON CONFLICT (run_id, purpose, round, epoch) DO UPDATE
    SET send_state = EXCLUDED.send_state,
        message_id = EXCLUDED.message_id,   -- ← overwrites the reservation
        subject    = EXCLUDED.subject,
        body_text  = EXCLUDED.body_text,
        created_at = now()
```

`send_outbound` mints the id at `gateway.py:274` and immediately upserts it. So on retry the durable pre-send reservation — the exact artifact the design calls "already a durable, unique, pre-send key" — is **overwritten before anything can read it**.

Two consequences, and the second is the one that will not show up in a naive test:
1. The idempotency key changes → **second payroll email**.
2. **The reply-routing anchor is erased.** That synthetic `message_id` is, per `gateway.py:271-273`, *"the SOLE routing anchor for every subsequent operation — a client reply is matched back to this run by it and nothing else."* If the first send actually escaped with id `A`, and the retry rewrites the row to id `B`, then the client's reply — threaded on `A` — **matches no row**, fails the header-chain lookup in `pipeline_glue.route_reply`, and is ingested as a **brand-new payroll run from a known sender**. A clarification reply becomes a phantom payroll run. That is a corrupted state machine reached purely through a retry.

**The fix:** `send_outbound` must **read before it mints**.
```
existing = repo.get_outbound_for_run_purpose_round_epoch(...)   # ANY send_state
message_id = existing["message_id"] if existing else f"<{uuid4()}@{_OUTBOUND_DOMAIN}>"
```
and the `ON CONFLICT DO UPDATE` must **stop overwriting `message_id`** (drop the column from the SET list, or set it to `email_messages.message_id`). Both halves are required: reading the row is useless if the write clobbers it, and preserving the column is useless if the caller mints a fresh one anyway. Guard it with a regression test that asserts `message_id` is **stable across a simulated retry** — that single assertion is the difference between "we implemented idempotency" and "we have it."

#### Variant B — `failed` is not proof of non-delivery [DESIGN GAP — G-3]

`send_outbound` catches **any** exception from `resend.Emails.send` and flips the row to `failed` (`gateway.py:341-345`). A **read timeout after Resend accepted the message** is such an exception. The mail is gone; the row says `failed`.

The retry guards only recognize `send_state = 'sent'` as proof of delivery (`delivery.py:88` via `get_outbound_message_id`; `get_outbound_for_round`'s docstring at `emails.py:180-193` says the same). So a `failed` row **does not suppress a retry** — and if that retry mints a fresh key (Variant A), the client gets the second email.

**The fix:** `reserved` and `failed` are both **"may have escaped."** Both must reuse the reserved `message_id` on retry, and both must therefore pass the *same* `Idempotency-Key` to Resend. Provider-side dedup then makes the second attempt a no-op. This is precisely why the idempotency key must be keyed on the **reservation**, not on the attempt.

#### Variant C — the dead `send_state` parameter [DESIGN GAP — G-4]

`send_outbound(..., send_state: str = "sent")` — both live callers pass `send_state="sent"` (`delivery.py:196`, `clarification.py:493`) and the function **ignores it**, hard-coding `send_state="reserved"` into the insert (`gateway.py:286`). It is vestigial. It is also a **loaded gun during Phase C**: an engineer touching send-state semantics will read the signature, adjust the argument, observe no change, and conclude something false about the system. **Delete the parameter in a pre-flight commit (Phase A-0),** before anyone reasons about send state.

#### Variant D — non-email side effects re-run on retry

The send is not the only irreversible thing a retried job repeats:
- **Alias learning** (`write_aliases_if_safe`) — already documented as idempotent ("only writes when the candidate is unambiguous and new," `delivery.py:87-90`). ✅ Verify, don't assume.
- **`mark_reply_consumed`** — write-once, guarded on `consumed_round IS NULL` (`orchestrator.py:348`). ✅
- **`replace_line_items`** — DELETE-by-run then INSERT; safe to repeat. ✅
- **The `reply_epoch` counter and the retrigger context-wipe** — these mutate provenance. A retry that bumps the epoch would orphan the run's own outbound rows. **Audit that the retry path never touches the epoch.**
- **LLM spend.** Every retry of a Round-2 resume is **two** extraction calls (`orchestrator.py:496,499`). A retry storm is a bill.

The discipline: **enumerate every side effect the job performs and classify each as idempotent / fenced / reserved-key-protected.** Any side effect that is *none of the three* is a bug waiting for its first retry. Put that table in the Phase C plan.

#### Variant E — the provider's dedup window is not infinite

`Idempotency-Key` dedup is only a guarantee **within the provider's retention window**. A job retried after that window (a poison job retried over hours with exponential backoff — exactly what Phase C builds) is a fresh request to Resend. **Verify Resend's documented `Idempotency-Key` retention** and cap total retry age **below** it. If the window is 24 h and your backoff schedule can reach 30 h, the provider fence is gone at exactly the moment you most rely on it.
> **Gap G-1 (research):** the retention window was not verified in this pass. Confirm against Resend's docs during Phase C. **Do not design a backoff schedule before you know the number.**

**Phase to address:** **A-0** (delete the dead param). **C** (all of A/B/D/E — this is the heart of the phase). **D** (the send-crash proof).

---

### Pitfall 7: Two sources of truth — a `jobs` table that starts deciding what happens next

**What goes wrong:**
The queue arrives. Its rows are convenient. Someone adds `jobs.next_status`, or `jobs.stage`, or a `kind = 'send_confirmation'`, and now **two tables answer "what happens next for this run?"** The moment they can disagree, they will:
- The job is `done` and the run is `extracting` → the run is stranded and nothing will ever pick it up, because the queue believes it finished.
- The job is `pending` and the run is `sent` → a retry re-drives a **completed payroll** and re-sends.
- The job says "next: send" and `payroll_runs.status` says `awaiting_approval` → the queue **bypasses the single human gate.** That is not a bug; that is the destruction of the project's central thesis.

**Why it happens:**
It is a genuinely attractive refactor. The job row is right there, it already has a `kind`, and encoding the next stage in it *feels* like making the pipeline explicit. It is the classic way a queue corrupts the state machine it was added to protect — and this state machine (`payroll_runs.status`: workflow position + durable checkpoint + HITL gate + crash-recovery anchor, per `PROJECT.md`) is the *entire* orchestration design.

**How to avoid:**
- **[DESIGN COVERS]** — "`jobs` is transport state ONLY," already a v4 Key Decision in `PROJECT.md`. This entry exists to make it *enforceable*, because a decision in a table is not a guard.
- **The discipline, stated as three rules:**
  1. A job row records **that an operation is owed and who owns it right now.** Never what payroll status comes next.
  2. **Job completion never implies a run transition.** The run transitions because the orchestrator committed it, inside the orchestrator's own transaction, through `repo.set_status` / `repo.claim_status` — which remain the **sole** status writers (`orchestrator.py:14-17`).
  3. **The job is not allowed to make the run's decision.** If the queue must know "should I re-drive this?", it asks **`payroll_runs.status`**, via a CAS that fails closed.
- **Guard it in CI:** `jobs` must have **no column whose name references a run status**, and no `RunStatus` value may be written into a `jobs` column. A schema assertion + a grep over `app/queue/` for `RunStatus`. Cheap, and it makes the invariant survive people.
- **Never enqueue a `send_confirmation` job.** The send is downstream of the human gate. If it is ever a job kind, someone will eventually drain it without the gate having been passed. Delivery stays where it is: triggered by the operator's approval, guarded by `claim_status`.
- **Recovery is a CAS, not a replay.** When the pump re-drives a stranded run, it must re-enter through `claim_status(from_status → …)` — the *existing* mechanism — so a run that has moved on since the job was enqueued is simply not re-driven.

**Warning signs:**
- Any column on `jobs` whose name is a stage or a status.
- Code that reads `jobs.state` to decide what to do to a *run*.
- A `kind` that names a *stage* (`kind='extract'`) rather than an *idempotent operation* (`kind='run_pipeline'`). The design's three kinds — `ingest` / `run_pipeline` / `resume_reply` — are correct precisely because each is "re-enter the state machine and let it decide," not "do stage N."

**Phase to address:** **A** (schema + the CI guard, at the moment `jobs` is created — the only moment the discipline is cheap).

---

### Pitfall 8: The error-swallowing orchestrator — jobs that "succeed" while the run burns

**What goes wrong:**
`_run` (`orchestrator.py:235-247`) and `resume_pipeline` (`orchestrator.py:850-859`) each catch **every** exception, call `repo.record_run_error(...)`, and **return `None` normally**. `run_pipeline`'s docstring says so plainly: *"`_run` never lets an exception escape, so no try/except is needed here; the external contract (never raises) holds."* And `pipeline_glue.run_pipeline_bg` wraps it in a **second** swallow.

That contract was **correct** for a `BackgroundTask` (nothing was listening; a raised exception would just print a traceback and vanish). It is **catastrophic** for a worker: the worker calls `run_pipeline(run_id)`, gets a clean return, and records the job **`done`**. A transient DeepSeek 503 — the single most likely failure in the entire system, and the most obviously retryable — becomes a **permanently terminal** run. The queue was added to make failures recover automatically, and this one line means the queue never retries the failures that matter most.

Worse: it fails **prettily**. The dashboard shows `error` with a clean `error_detail`, the job shows `done`, the queue depth is zero, and the ops page is green. Everything looks healthy and nothing will ever recover.

**Why it happens:**
The swallow is *load-bearing today* — it is what makes `error_detail` (OPS2-01) and the PII-scrubbing roster-aware error path work, and it is documented as an intentional invariant ("No failure is silent," `orchestrator.py:18-21`). It will read to a reviewer as a *feature*, and it is one — for the old execution model. It cannot simply be deleted, and **retry cannot be bolted on from the outside**: the worker literally cannot distinguish success from failure.

**The correct contract:**
- **[DESIGN COVERS]** — stages return `ok` / `retryable(reason)` / `terminal(reason)`. Sharpen it into rules:
  1. **The orchestrator keeps its catch-all** (it must — `error_detail` and PII scrubbing depend on it), but it **classifies and returns a result**, rather than returning `None`. `record_run_error` still fires; that behavior is preserved exactly.
  2. **Classification is by exception type, allow-list style, and it fails *retryable*.** Timeouts, connection errors, HTTP 5xx/429, `PoolTimeout` → **retryable**. Validation errors, `ValueError` from the process-run integrity check (`orchestrator.py:1073`), Pydantic parse failures after the built-in retry, "run not found" → **terminal**. *Unknown → retryable, bounded by the attempt cap.* An unknown-terminal default silently recreates today's bug for every exception type nobody thought about; an unknown-retryable default costs at most `max_attempts` wasted tries and then dead-letters.
  3. **A `retryable` result must NOT leave the run at `error`... or must be able to leave it and come back.** Decide this explicitly. Cleanest: `error` remains the durable, dashboard-visible parking state (it already is, with a retrigger path), and the **job's** retry re-drives it via `claim_status(ERROR → …)`. That reuses the existing, proven retrigger machinery rather than inventing a `retrying` status — and it keeps `payroll_runs.status` as the single source of truth (Pitfall 7).
  4. **Infrastructure failure ≠ `needs_operator`.** **[DESIGN COVERS]** and it is exactly right: `/runs/{id}/resolve` requires `decision.unresolved_names` (`runs.py:203-213`); an LLM timeout during extraction has no `decision` at all, so parking it there produces a run the operator UI **cannot service**. Keep it in `error`.
  5. **Delete the double swallow.** `pipeline_glue.*_bg` wrappers exist to stop a crash escaping a `BackgroundTask`. Once the worker is the caller, that wrapper is a **second** place the result gets destroyed. Retire the `_bg` wrappers with the `BackgroundTasks` producers (Pitfall 10) — or the classification will be laundered right back into `None`.

**Warning signs:**
- A worker's `try: run_pipeline(id) except: ...` with an empty-ish body — a tell that the caller believes exceptions propagate. They do not.
- Job success rate ~100% while `payroll_runs.status='error'` is nonzero. **Make this an ops-page alarm.** It is the exact signature of this bug, and it is otherwise invisible.
- Any `except Exception` in the queue↔orchestrator seam that does not *return* something the caller acts on.

**Phase to address:** **C** (the result contract is the phase's first item — retry policy is meaningless without it). But the **`_bg` wrapper retirement** must be sequenced with **A**, or the double-swallow survives the phase that was supposed to fix it.

---

### Pitfall 9: Poison jobs, infinite retry, and the retry storm

**What goes wrong:**
1. **Unbounded attempts.** A job that fails deterministically (a malformed payload, a `NOT NULL` violation, an oversized body) retries **forever**, spending LLM tokens and — on a 2-worker, 5-connection budget — **crowding out real work**. One bad job is a self-inflicted denial of service against a system whose entire throughput is 2.
2. **The thundering herd.** Resend has an outage; 5 jobs fail; all 5 get `available_at = now() + 30s`; all 5 retry **simultaneously** at t+30, saturating the 2 workers and the 5 connections at exactly the moment the service is degraded. Without jitter, retries **synchronize** and stay synchronized.
3. **Retry-until-timeout-cliff.** Backoff eventually schedules `available_at` past Resend's `Idempotency-Key` retention window (Pitfall 6E) — the retry that finally succeeds is the one that sends the **second** email.
4. **Silent dead-letter.** Jobs move to `dead` and nobody looks. Payroll emails go unprocessed for a week and the client is the one who notices.
5. **The retrigger-vs-retry double drive.** The operator retrigger path (`runs.py:380`) and the queue's own retry can both target the same run. Without a shared CAS, that is two concurrent pipelines on one run.

**How to avoid:**
- **[DESIGN COVERS]** backoff + jitter + attempt cap + dead-letter. The design is right; the details are where it dies:
- **Full jitter, not "exponential plus a little noise."** `sleep = random(0, min(cap, base * 2^attempt))`. Additive jitter still leaves the herd synchronized.
- **Cap total retry *age*, not just attempt count** — and cap it **below** the provider's idempotency window (Pitfall 6E). Two independent caps: `max_attempts` **and** `max_age`. Whichever trips first → `dead`.
- **`attempts` is incremented in the claim, not in the failure handler** (the design's claim SQL already does this: `attempts = attempts + 1`). ✅ Correct — a worker that **crashes without reporting** still burns an attempt, so an OOM-loop job cannot retry forever.
- **The dead-letter must be *loud*.** Surface it on the ops page **and** fail the keepalive workflow when `dead > 0` (the same trick `keepalive.yml` already plays with `/health/schema` returning 503 on drift → `curl -f` → RED run). A dead-letter list nobody looks at is a `/dev/null` with extra steps. This repo already invented the right pattern; reuse it.
- **A `dead` job must leave the run in a state a human can act on** — `error` with `error_detail`, retriggerable. The dead-letter and the run status must not disagree (Pitfall 7).
- **Route the operator retrigger *through the queue*.** After Phase A, "retrigger" enqueues a job (with a `dedup_key` that resets on retrigger — the `reply_epoch` mechanism is the natural key). Two paths to "re-drive this run" is exactly the two-execution-systems problem (Pitfall 10) wearing a different hat.
- **A "circuit breaker" is explicitly out of scope** — correctly. At 1 email/client/week, the attempt cap *is* the breaker.

**Warning signs:**
- `attempts` incremented only on the failure path (a crashed worker then never burns one → infinite).
- A backoff schedule whose max age was never compared against the provider's dedup window.
- `dead` jobs accumulating with a green keepalive.
- Jitter added as `+ random(0, 5s)`.

**Phase to address:** **C** (policy). **D** (the ops view + the dead-letter alarm; a poison-job test that asserts it *stops*).

---

### Pitfall 10: Migrating the `BackgroundTasks` producers — the ones you will miss

**What goes wrong:**
Some producers move to the queue; others don't. Now there are **two execution systems** — and the un-migrated ones still lose work on restart, which was the entire point of the milestone. Worse, they can **race** the queue: an un-migrated `BackgroundTask` and a queued job both drive the same run.

**The complete producer inventory (I grepped it — the design's list is incomplete):**

| # | Site | What it schedules | Notes |
|---|------|-------------------|-------|
| 1 | `webhook.py:261` | `resume_pipeline_bg` (reply resume, redelivery path) | in the design's list |
| 2 | `webhook.py:309` | `run_pipeline_bg` (the main ingest) | in the design's list |
| 3 | `runs.py:262` | `operator_resume_bg` (the `needs_operator` **/resolve** path) | in the design's list |
| 4 | `runs.py:380` | `run_pipeline_bg` (operator **retrigger**) | in the design's list |
| 5 | `demo.py:205` | `run_pipeline_bg` (demo "Send Test Email") | in the design's list |
| 6 | `demo.py:313` | `run_pipeline_bg` (demo "Simulate client reply") | in the design's list |
| 7 | **`runs.py:475`** | **`resume_pipeline_bg` — from inside the `runs_list` page-load sweep** | **NOT in the design's list.** ⚠️ |
| 8 | **`runs.py:792`** | **`pipeline_glue.route_reply(...)` — takes `background_tasks` and dispatches internally** | **NOT in the design's list.** ⚠️ Indirect: the `add_task` lives in `pipeline_glue.py:127`, so a grep for `add_task` in `runs.py` **misses it**. |
| — | `pipeline_glue.py:127` | the shared `add_task` used by (1), (7), (8) | the seam itself |

**Sites 7 and 8 are the ones that get missed**, and for two different reasons that generalize:
- **7** is a producer inside a *sweep* inside a *page render* — nobody thinks of the dashboard as a producer. It is also the very seam the design says to "keep until the queue is proven, then retire." If it is kept but **not migrated**, the dashboard is a second, un-durable execution system, still scheduling `BackgroundTask`s that die with the process — i.e. the milestone's headline bug, still live, in the recovery path.
- **8** passes `background_tasks` **down into a helper**. Grepping for `add_task` finds `pipeline_glue.py:127`, not `runs.py:792`. **The correct grep is for the `BackgroundTasks` *type annotation* in route signatures** (`runs.py:87,161,269,445,687`; `webhook.py:30`; `demo.py:125,220`; `pipeline_glue.py:84,135`) — a route that takes `BackgroundTasks` is a producer, whether or not the word `add_task` appears in it.

**How to avoid:**
- **Migrate all eight, in one phase.** A partial migration is worse than none: it doubles the execution surface while claiming to have unified it.
- **Then delete the capability.** Remove `BackgroundTasks` from **every** route signature and add a **CI grep guard** banning the import in `app/routes/` and `app/pipeline/`. This is the only durable fix — otherwise the next feature adds producer #9 and nobody notices. (Again: this repo already knows how to build exactly this guard.)
- **Retire `*_bg` wrappers with the producers**, not later — they are the double-swallow of Pitfall 8.
- **Keep the sweep for one phase, migrate it immediately.** The sweep is genuinely useful during A→B (a safety net while the pump is unproven), but it must **enqueue jobs**, not `add_task`. Then retire it in B once the pump is proven — and *state the retirement criterion in the phase doc* ("retired when the durability proof passes"), or it will live forever as an un-owned parallel execution path.
- **`dedup_key` design must survive all eight producers.** A retrigger of a run that already has a `done` job must enqueue a **new** job, not `ON CONFLICT DO NOTHING` into oblivion. The `reply_epoch` counter is the right discriminator — the same reason `epoch` is already in the `uq_email_run_purpose_round_epoch` arbiter (`emails.py:52-63`). **A `dedup_key` of `('run_pipeline', run_id)` is a bug**: it makes retrigger a silent no-op. Include the epoch.

**Warning signs:**
- `grep -rn "BackgroundTasks" app/` returns anything after Phase A.
- A `dedup_key` that omits the epoch/attempt discriminator (test it: retrigger a completed run and assert a *new* job appears).
- The dashboard sweep still calling `add_task`.

**Phase to address:** **A** (migrate all eight + the ban guard). **B** (retire the sweep, with a written criterion).

---

### Pitfall 11: Unbounded raw-payload storage — the durable inbox that eats the free tier

**What goes wrong:**
`raw_body: bytes = await request.body()` (`webhook.py:57`) reads the request body with **no size limit**. Today that is merely a memory risk. After Phase A it becomes a **durable** one: the design persists the raw signed event so the body-fetch can move to the worker. Now:
- A 40 MB payload is **committed to Supabase** (free tier: **500 MB**), and then **retried** — each retry re-reading the blob through a pool of 5 connections. A handful of these and the database is full; a full Postgres is a hard stop for *everything*, including the operator gate on a legitimate payroll run.
- The raw body is a **signed Resend envelope containing PII** (sender addresses, and after the worker's fetch, employee names and hours). It is now sitting in a table with **no retention policy** — the repo already invested real effort in PII-safe `error_detail` scrubbing (OPS2-01) and would be quietly undoing it by persisting raw bodies forever.
- `demo.py:139-151` **does** enforce size limits — on the demo composer. Those limits **do not protect the real webhook**. That asymmetry is exactly the shape of a gap nobody sees.

**How to avoid:**
- **[DESIGN COVERS]** "cap the raw request body… a byte cap and a retention policy." Sharpen it into decisions the roadmap can verify:
- **Reject over-cap at the door, before persisting.** Check `Content-Length` **and** enforce the cap on the actual bytes read (a lying `Content-Length` is trivial). Over-cap → **413**, log, **do not enqueue**. A payload you refuse to process must not become a durable job that retries forever. Pick a real number: a payroll email is a few KB; **256 KB** is generous. Attachments are out of scope (spreadsheet parsing is explicitly deferred in `PROJECT.md`), so the cap can be aggressive.
- **A retention policy with an actual deleter.** "We'll add retention later" means never. `raw_events` older than N days (30) and `done` → **deleted**, by the **pump** (it is the only thing that reliably runs). Retention with no reaper is a comment, not a policy.
- **Do not store the *fetched* body in the raw inbox.** The cleaned body already lives in `email_messages` (that is what `load_source_email` reads). Two copies of the PII is one too many.
- **Count the free-tier budget.** Supabase free = 500 MB. Write the arithmetic in the phase doc, same discipline as Pitfall 2.

**Warning signs:**
- `request.body()` with no cap after Phase A.
- A `raw_events`-shaped table with no `DELETE` anywhere in the codebase.
- Supabase storage trending up on a system that processes ~1 email/client/week.

**Phase to address:** **A** (the cap — it ships with the raw inbox, or the raw inbox ships a hole). The **reaper** can be **B** (the pump is its natural home), but the *retention decision* must be written in A.

---

### Pitfall 12: Vacuous durability tests — this project has been burned by this **exact** failure mode already ⚠️⚠️

**Read the memory first.** Phase 10's "concurrency proof" was **verified, merged, and celebrated** — and was **vacuous**. Surfaces A and C fired 8 OS threads at `async def /webhook/inbound`, whose DB body contains no `await`. A shared `TestClient` therefore **serialized** them through the event loop. The `ON CONFLICT` race the test claimed to prove **never fired**. The falsifying observation: *Surface A passed even with the `ON CONFLICT` clause deleted.* Only Surface B (a genuinely sync route) raced. It took a cross-AI code review to catch, and gap-plan 10-02 to fix by driving the **sync repo seam directly** under a `threading.Barrier`.

**The lesson generalizes, and Phase D is more exposed than Phase 10 was**, because durability tests are *harder to falsify* than race tests. A race test at least has a clear "did the race happen?" question. A durability test asserts that something **recovers** — and a system that never actually broke also "recovers," perfectly, every time.

**The five ways each Phase D proof goes vacuous:**

| Proof | The vacuous version | What makes it real |
|---|---|---|
| **1. Durability** (kill worker mid-run → pump completes it) | The "kill" is a mocked exception, or the job was never actually leased, or the pipeline had **already finished** before the kill landed. Passes trivially. | **Falsify it:** the test must **fail** if the pump is not called. Assert an intermediate observable — the job is `leased` with a `lease_token` and the run is mid-flight (`extracting`) — **before** the kill. Kill via a real process/thread abort, not a mock. Then assert the pump — and *only* the pump — completes it. |
| **2. Ingress idempotency** (redeliver Svix event → 1 job, 1 run, 1 email) | Sequential redelivery. Proves `ON CONFLICT`, not the race. **This is Phase 10's exact bug, resurrected.** | Drive the **sync ingest seam** from N threads behind a `threading.Barrier` (the 10-02 pattern — reuse it verbatim). **And falsify:** delete the `dedup_key` UNIQUE constraint and prove the test **goes red**. If it stays green, it proves nothing. |
| **3. Send safety** (crash between Resend-accept and `sent` commit → no second email) | A fake gateway that records calls. It will happily "prove" the design while `send_outbound` mints a fresh `uuid4` and the upsert overwrites `message_id` (Pitfall 6A) — because the fake never checks the key. | Assert on the **`Idempotency-Key` actually passed to the provider**, and assert the persisted `message_id` is **byte-identical** across attempt 1 and attempt 2. That single assertion is the whole proof. Then run it for **both** `reserved` **and** `failed` rows (Pitfall 6B). |
| **4. Reclaim safety** (zombie's stale-token write rejected) | Two sequential "workers" in one thread with hand-set tokens. Proves the `WHERE` clause; proves nothing about the zombie **continuing into the pipeline** and re-sending. | Prove the fence at **every** write (`done`, `failed`, `reschedule`) **and** prove the zombie's *side effects* are blocked — the run-level `claim_status` CAS is what actually stops the second email. **Falsify:** drop `lease_token` from the `WHERE` and confirm red. |
| **5. Pool starvation** (not in the design — **add it**) | Absent entirely. | Saturate the workers, then assert an **ingest** and an **approval** still succeed. This is the test that proves the sizing rule (Pitfall 3) rather than asserting it in a comment. |

**The non-negotiable discipline for Phase D — three rules:**

1. **Every durability test must be proven able to FAIL.** For each one, name the line of production code you delete/mutate to turn it red, run it, and **paste the red output into the phase's verification artifact.** A test whose falsifying mutation was never executed is a test whose scope is unknown — and *"guards are blind where they don't look"* is already a learned lesson in this repo. Apply it here.
2. **Never drive a race through an HTTP route.** Drive the **sync seam** (the repo function, the claim function, the drain function) from real threads behind a `threading.Barrier`, respecting `max_size=5`. HTTP routes are for *behavior* tests. They are **structurally incapable** of proving parallelism in this app, and that is not a hypothesis — it is a finding from this repo's own git history.
3. **These tests need a real Postgres.** Note the trap already documented in the project's memory: **34/37 `-m integration` tests never run in CI** — only `concurrency-proof.yml` provisions Postgres, and it **hard-codes one file**. A new `tests/test_durability_proof.py` will be **silently skipped in CI** unless that workflow is updated to include it. *A durability proof that does not run is worse than no durability proof.* **Check `concurrency-proof.yml` explicitly as a Phase D exit criterion,** and assert the file's tests actually executed (non-zero collected count), not merely that the job was green.

**Warning signs:**
- A durability test with no named falsifying mutation.
- Threads pointed at a FastAPI `TestClient`.
- A new test file that doesn't appear in `concurrency-proof.yml`'s file list.
- A green Phase D whose tests all complete in under a second (real leases expire; real timeouts elapse).
- The word "should" in a durability assertion.

**Phase to address:** **D**, and D's *definition of done* is "each proof has a demonstrated red." Consider a **cross-AI adversarial review of Phase D specifically** — that is what caught it last time (Phase 10 CR-01, and 5 critical bugs in Phase 11).

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|---|---|---|---|
| Keep the dashboard page-load sweep alongside the queue | A safety net while the pump is unproven | **Two execution systems.** The sweep still schedules non-durable `BackgroundTask`s (`runs.py:475`) — the exact bug v4 exists to kill | **A→B only**, and only if the sweep is migrated to *enqueue jobs*. Retirement criterion written into the phase doc |
| Ship the queue in A, defer the result contract to C | Smaller phase A | Between A and C, **every worker records failure as success** — strictly worse than today's `BackgroundTask`, which at least didn't lie | **Never as a *release*.** Fine as an internal phase boundary only if A→C ship together |
| One connection held per job ("simpler") | Less code | Pins 1 of 5 across a 45 s LLM call; breaks under transaction-mode pooling; **guaranteed** starvation | **Never** |
| `pg_advisory_lock` for a singleton pump | One line, feels obviously right | **Silently does nothing** on 6543. Passes every local test against direct Postgres (5432) | **Never.** Use a row lease |
| Mock the gateway in the send-safety proof | Fast, hermetic | Proves the design doc, not the code. Would pass today, with the `message_id`-overwriting upsert fully intact | **Never** for proof #3. Fine for *behavior* tests elsewhere |
| Persist the raw body with "retention later" | Ships A faster | Later never comes; PII + free-tier storage grow unbounded | **Never.** The reaper is ~15 lines |
| Skip `provider_message_id` persistence | One less column | No durable evidence of what the provider actually accepted; post-incident forensics is guesswork | Acceptable only if the reserved `message_id` reuse (Pitfall 6A) is airtight. Cheap enough to just do |
| Leave `send_outbound`'s dead `send_state` param | Zero diff | A live trap in the exact function Phase C rewrites | **Never.** Delete it in A-0 |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|---|---|---|
| **Supavisor 6543 (transaction mode)** | `pg_advisory_lock` / `LISTEN` / `NOTIFY` / session `SET` — all **silently** no-op or leak | Row leases + CAS only. CI grep guard on those identifiers. (Prepared statements already fixed: `prepare_threshold=None`) |
| **Supavisor 6543** | Testing locking against direct Postgres (5432, session mode) — where advisory locks **work** — and concluding prod is fine | The `postgres:16` CI container is session-mode. It is the right place for **race** proofs and the **wrong** place to conclude "our locking works." Guard by grep, not by a test that cannot fail |
| **Resend `Idempotency-Key`** | Minting a fresh `uuid4` per attempt → key changes → dedup defeated | Reuse the **reserved** `message_id`. And stop `insert_email_message`'s `ON CONFLICT DO UPDATE` from **overwriting** it (`emails.py:85`) |
| **Resend `Idempotency-Key`** | Assuming an unbounded dedup window | **Verify the retention window (open gap G-1)** and cap total retry *age* below it |
| **Resend send** | Treating an exception as proof of non-delivery (`gateway.py:341`) | A timeout **after** acceptance also raises. `failed` = "may have escaped." Retry must reuse the key |
| **Resend webhook** | Redelivery mints a new job because dedup keys on the RFC `Message-ID`, which is unknown once the body-fetch moves to the worker | **[DESIGN COVERS]** — key the raw inbox on the **Svix event ID**; keep the RFC-`Message-ID` dedup one layer deeper as the second gate |
| **GitHub Actions cron** | Treating it as a scheduler | Best-effort: **5–30 min delays are normal**, 5-min minimum interval, **auto-disables after 60 quiet days**. `keepalive.yml` already models the mitigation (`workflow_dispatch`). Write the guarantee to match |
| **Render free** | Pump cadence chosen without costing instance-hours | < 15 min cadence ⇒ **never sleeps** ⇒ **~730 h** of a **750 h/workspace** budget. Decide it explicitly (Pitfall 2) |
| **Render free** | Assuming an internal timer can drain the queue | **Only inbound HTTP wakes the service.** Ban in-process schedulers by CI guard |
| **Supabase free** | Unbounded raw-payload storage | 500 MB cap. Byte cap at the door + a reaper that actually runs (in the pump) |

---

## Performance Traps

At ~1 payroll email per client per week, "performance" here means **the failure modes that bite at N=2**, not throughput.

| Trap | Symptoms | Prevention | When It Breaks |
|---|---|---|---|
| Pool starvation | Empty dashboard runs list; `/health/ready` red; keepalive RED with Supabase green; `PoolTimeout` | `workers + 2 ≤ max_size` (⇒ **2 workers**); never hold a connection across LLM/PDF/Resend | **Immediately at 3+ workers.** Not a scale issue — a *config* issue |
| Connection held across an LLM call | Latency cliff; everything blocks for ~45 s at a time | Short checkouts; claim transaction commits before work | The first concurrent run |
| Retry storm (no jitter) | Synchronized failure waves after any outage | **Full jitter**: `random(0, min(cap, base·2^n))` | The first Resend/DeepSeek blip |
| Poison job burning the worker budget | One `run_id` monopolizes both workers forever | Attempt cap **and** age cap → `dead` | The first malformed payload |
| Two extractions per Round-2 resume × retries | LLM bill; long leases | Lease must exceed 2× extraction timeout; cap attempts | Any retried Round-2 resume |
| `SKIP LOCKED` contention | Not a real risk here | — | ~thousands of workers. **Ignore.** Do not build for it (throughput machinery is explicitly out of scope) |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---|---|---|
| `/internal/pump` unauthenticated | **Anyone can drain, re-drive, and DoS the queue** — and force-wake the service, burning the instance-hour budget (Pitfall 2). The dashboard's lack of auth is a *known, accepted* gap; the pump is **not** in that bucket — it *mutates execution* | Shared-secret header, constant-time compare, secret in Render env + GH Actions secret. **Never** a query param (it lands in access logs). Non-2xx on failure so the cron run goes RED |
| Unbounded `request.body()` (`webhook.py:57`) | Memory exhaustion → **durable** storage exhaustion after Phase A | Hard byte cap (~256 KB) → **413**, before persisting or enqueuing |
| Raw signed envelopes persisted with no retention | PII accumulation — quietly undoing the OPS2-01 scrubbing investment | Retention policy **with a reaper**, run by the pump |
| Persisting an oversized/malicious body *then* rejecting it | The rejected payload still becomes a retried job | Reject **before** the durable write. Never enqueue what you refuse to process |
| Verifying the Svix signature **after** persisting | An unsigned attacker payload lands in the durable inbox | The existing ordering contract (`webhook.py:47-53`: *verify before parse*) must extend to **verify before persist**. Do not let "offload to a thread" reorder it |
| Sweep re-drive skipping the sender revalidation | A spoofed reply auto-resumes | `runs.py:466-476` **already** re-asserts `reply_sender_ok` before re-scheduling. **The queue's re-drive path must do the same** — this check is easy to lose in the migration |
| Job payloads carrying PII | The `jobs` table becomes a second un-scrubbed PII store | Jobs carry **IDs only** (`run_id`, `raw_event_id`). Never a body, never a name |

---

## UX Pitfalls (operator-facing)

| Pitfall | User Impact | Better Approach |
|---|---|---|
| Retries are invisible | Operator sees a run "stuck at extracting" for 20 min with no explanation; retriggers it manually; now two drives race | Show attempt count + `available_at` ("retrying, next attempt ~14:32") on the run detail page |
| Dead-letter with no alarm | Payroll silently unprocessed for days; the **client** notices first | Ops page **plus** a RED keepalive when `dead > 0` (reuse the `/health/schema` 503 → `curl -f` pattern) |
| Pool starvation renders an **empty** runs list (`runs.py:490`) | During an incident, the operator's only tool shows "no runs" | Distinguish "DB unreachable" from "pool exhausted"; render a degraded banner, never a false empty |
| Operator retrigger competes with an automatic retry | Double-drive; confusing status flapping | Retrigger **enqueues**; `claim_status` absorbs the loser. One execution system |
| The README overclaims recovery latency | The first delayed cron makes the whole repo's honesty suspect — its central selling point | *"typically within 5–30 minutes, best-effort"* + the documented fallback. The v3 eval-chart correction is the precedent to honor |

---

## "Looks Done But Isn't" Checklist

- [ ] **Queue table + claim protocol:** often missing the **fence on `mark_failed` / `reschedule`** (only `mark_done` gets one) — verify **every** `UPDATE jobs` has `lease_token` in its `WHERE` **and checks the row count**
- [ ] **Worker pool:** often missing the **connection-budget bound** — verify `workers + 2 ≤ max_size` and that the constant *names* `max_size` in a comment
- [ ] **Worker pool:** often missing a **starvation proof** — verify an ingest + an approval still succeed with all workers busy
- [ ] **Producer migration:** often missing **`runs.py:475` (the sweep)** and **`runs.py:792` (via `route_reply`)** — verify `grep -rn "BackgroundTasks" app/` is **empty** and a CI guard bans the import
- [ ] **`run_pipeline`:** often still writing `received → extracting` **unconditionally** (`orchestrator.py:232`) — verify it uses `claim_status` like `resume_pipeline` does
- [ ] **Result contract:** often applied to the orchestrator but **not** to the `pipeline_glue._bg` wrappers, which re-swallow it — verify the wrappers are **deleted**, not just bypassed
- [ ] **Result contract:** often defaults unknown exceptions to **terminal** — verify unknown ⇒ **retryable** (bounded by the cap)
- [ ] **Exactly-once send:** often "passes the idempotency key" while **still minting a fresh `uuid4`** and letting the upsert **overwrite** `message_id` — verify the persisted `message_id` is **byte-identical across a simulated retry**, and that `ON CONFLICT DO UPDATE` no longer sets `message_id`
- [ ] **Exactly-once send:** often handles `reserved` but **not `failed`** — verify **both** reuse the key
- [ ] **Exactly-once send:** often forgets the **reply-threading** consequence — verify a reply threaded on the *first* attempt's `message_id` still routes to its run after a retry
- [ ] **Pump:** often missing the **instance-hour cost** — verify the cadence, the hours, and the "one free service in this workspace" assertion are **written down**
- [ ] **Pump:** often missing **auth** — verify a shared secret, constant-time, header-not-query
- [ ] **Raw inbox:** often missing the **size cap** and **always** missing the **reaper** — verify a `DELETE` exists and something calls it
- [ ] **Dead-letter:** often has no **alarm** — verify `dead > 0` turns the keepalive workflow RED
- [ ] **Durability proofs:** often **never proven able to fail** — verify each has a named falsifying mutation and a **pasted red run**
- [ ] **Durability proofs:** often **never run in CI** — verify the new test file is added to `concurrency-proof.yml` (34/37 integration tests currently never execute in CI) **and** that it reports a non-zero collected count

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---|---|---|
| Duplicate payroll email sent to a client | **HIGH — reputational, and the milestone's headline claim is falsified** | Apologize; audit `email_messages` for `purpose='confirmation'` rows sharing a `run_id` across epochs; **add the regression test first**, then fix the key reuse |
| Queue drains but jobs never retry (error-swallow) | MEDIUM | Detectable as `job success ≈ 100%` while `status='error' > 0`. Fix the result contract; re-drive `error` runs via the retrigger path (already exists) |
| Free instance-hours exhausted mid-month | **HIGH — the live demo is dark until the 1st** | No fix within the month. **Prevent:** cost the cadence up front (Pitfall 2), monitor Render usage |
| Zombie double-processed a run | HIGH | `claim_status` should have blocked it — if not, the run-level CAS is missing. Audit `payroll_runs.status` transitions; add the fence; add the reclaim proof |
| Advisory lock silently no-op in prod | MEDIUM | Symptom is "works locally, does nothing on Render." Replace with a row lease; add the CI grep guard so it cannot return |
| Raw inbox filled Supabase | MEDIUM | `DELETE` old rows; add the cap and the reaper. Note a full Postgres blocks the **operator gate** too — every run is stuck |
| Poison job burning both workers | LOW | Manually `dead` the row; then add the attempt+age cap |
| Vacuous durability suite shipped | **HIGH — the repo's credibility is its product** | The Phase 10 playbook: cross-AI review, a gap plan, and re-prove by **falsification** (delete the guard, watch it go red) |

---

## Pitfall-to-Phase Mapping

| # | Pitfall | Prevention Phase | Verification |
|---|---------|------------------|--------------|
| 6C | Dead `send_state` param; double-swallow `_bg` wrappers | **A-0** (pre-flight) | Param deleted; `grep -c "send_state=" gateway.py` reflects one real write path |
| 1 | Durable storage ≠ durable execution | **B** (route) / **A** (drain seam + no-timer guard) | CI grep bans `asyncio.sleep` loops / APScheduler / `threading.Timer` in `app/` |
| 2 | Pump cadence eats the 750 h budget | **B** | The arithmetic is written in the phase doc + a Key Decision row; workspace has one free service |
| 3 | Connection-pool starvation | **A** (bound) / **D** (prove) | `workers + 2 ≤ max_size`; starvation test: ingest + approval succeed with all workers busy |
| 4 | Supavisor transaction-mode primitives | **A** | CI grep guard: `pg_advisory_lock`, `pg_advisory_unlock`, `LISTEN`, `NOTIFY` absent from `app/` |
| 5 | Lease/fencing; zombie stale write | **A** (fence + `run_pipeline` CAS) / **C** (fence retry writes) | Every `UPDATE jobs` has `lease_token` + row-count check; **falsify** by dropping the token from the `WHERE` → red |
| 6A | Fresh-key mint + `message_id` overwrite | **C** | `message_id` **byte-identical** across a simulated retry; `ON CONFLICT DO UPDATE` no longer sets `message_id`; the `Idempotency-Key` sent to the provider is asserted |
| 6B | `failed` ≠ proof of non-delivery | **C** | Both `reserved` and `failed` rows reuse the key on retry |
| 6D | Non-email side effects on retry | **C** | A side-effect classification table (idempotent / fenced / key-protected) in the phase doc — nothing unclassified |
| 6E | Provider dedup window vs. backoff age | **C** | Resend retention verified (**open gap G-1**); `max_age` < window, asserted in a test |
| 7 | Two sources of truth (`jobs` vs `status`) | **A** (schema) | No status-named column on `jobs`; no `RunStatus` written into `jobs`; no `send_confirmation` job kind |
| 8 | Error-swallowing orchestrator | **C** (contract) / **A** (retire `_bg`) | Ops alarm: job-success ≈100% while `status='error' > 0`. Unknown exception ⇒ retryable, tested |
| 9 | Poison jobs / retry storm | **C** (policy) / **D** (ops view) | Attempt cap **and** age cap; **full** jitter; `dead > 0` ⇒ keepalive RED |
| 10 | Missed `BackgroundTasks` producers (esp. `runs.py:475`, `runs.py:792`) | **A** (all 8) / **B** (retire sweep) | `grep -rn "BackgroundTasks" app/` empty; CI guard bans the import; retrigger-after-`done` enqueues a **new** job (epoch in `dedup_key`) |
| 11 | Unbounded raw-payload storage | **A** (cap + policy) / **B** (reaper) | Over-cap ⇒ **413**, no durable write, no job; a `DELETE` exists and the pump calls it |
| 12 | **Vacuous durability tests** | **D** | **Every proof has a named falsifying mutation with a pasted red run**; races drive the **sync seam** under `threading.Barrier`, never an HTTP route; the new test file is in `concurrency-proof.yml` and reports a non-zero collected count |

---

## Open Gaps (unresolved by this research)

- **G-1 — Resend `Idempotency-Key` retention window.** SDK support is verified (`resend==2.32.2`, `SendOptions(idempotency_key=...)` → `Idempotency-Key` header). The **dedup window** is not. Phase C's backoff `max_age` **must** be capped below it. **Verify before designing the backoff schedule.**
- **Supabase free-tier pooler client cap.** If raising `max_size` above 5 is ever considered, the Supavisor client limit must be checked first. Not needed at 2 workers.
- **Whether `concurrency-proof.yml`'s Postgres container can meaningfully emulate transaction-mode pooling.** Almost certainly not (it is a direct session-mode connection). Treated above as "guard by grep, not by test" — revisit only if a pooler-specific bug escapes to production.

---

## Sources

- **This repository, read directly (HIGH — traced, not inferred):** `app/pipeline/orchestrator.py` (the catch-all error boundaries at :235-247 / :850-859; the unconditional `EXTRACTING` write at :232; the `claim_status` CAS at :305; the no-transaction-across-LLM contract at :1015-1018; the dual Round-2 extractions at :496,499), `app/email/gateway.py` (`uuid4` mint at :274; `send_state="reserved"` hard-code at :286; the `failed` flip on any exception at :341-345; the "sole routing anchor" comment at :271-273), `app/db/repo/emails.py` (**the `ON CONFLICT ... SET message_id = EXCLUDED.message_id` upsert at :83-89**; the `send_state='sent'` proof-of-delivery filter at :180-193; the epoch-arbiter rationale at :52-63), `app/db/supabase.py` (`max_size=5`, `timeout=5`, `prepare_threshold=None`), `app/pipeline/delivery.py` (the purpose-aware already-sent guard at :77-90), `app/routes/*` + `app/routes/pipeline_glue.py` (the **8** `BackgroundTasks` producers), `.github/workflows/keepalive.yml` (the 60-day auto-disable mitigation, already modeled).
- **`docs/superpowers/specs/2026-07-13-durable-execution-design.md`** — the approved, Codex-reviewed design. Everything marked **[DESIGN COVERS]** is credited to it.
- **Project memory / prior post-mortems (HIGH):** *"Phase 10 concurrency proof was vacuous"* (threads serialized through `async def`; Surface A passed with `ON CONFLICT` deleted) — the direct precedent for Pitfall 12. *"Guards are blind where they don't look."* *"Phase 15: 34/37 `-m integration` tests never run in CI."* *"Review traces argflow, not prose."*
- **PgBouncer / Supavisor transaction-mode semantics (HIGH):** [pgbouncer.org/features](https://www.pgbouncer.org/features.html); [pgbouncer#976 — warn on unsupported features in transaction mode](https://github.com/pgbouncer/pgbouncer/issues/976); [Supabase — Supavisor and connection terminology](https://supabase.com/docs/guides/troubleshooting/supavisor-and-connection-terminology-explained-9pr_ZO); [Supavisor#85 — LISTEN/NOTIFY with transaction pooling](https://github.com/supabase/supavisor/issues/85); [PgBouncer is useful, important, and fraught with peril — JP Camara](https://jpcamara.com/2023/04/12/pgbouncer-is-useful.html). **Key corroborated fact:** session advisory locks and LISTEN/NOTIFY fail **silently**; prepared statements fail **loudly** (already fixed here).
- **Render free tier (HIGH):** [render.com/docs/free](https://render.com/docs/free) — **750 instance-hours per workspace per calendar month; hours consumed only while running; 15-minute idle spin-down; ~1-minute cold start.** The 730 h ÷ 750 h collision in Pitfall 2 follows arithmetically.
- **GitHub Actions cron (HIGH):** [community discussion #156282 — unexpected cron delays](https://github.com/orgs/community/discussions/156282); [community discussion #147369](https://github.com/orgs/community/discussions/147369) — **5-minute minimum interval; 5–30 minute delays normal; explicitly not guaranteed; auto-disable after 60 quiet days.**
- **Postgres queue / lease / fencing canon (HIGH):** [faultline — lease coordination + fencing tokens](https://github.com/kritibehl/faultline) (side effects bound to `(job_id, fencing_token)`; stale-write rejection); [The Queue Was a Table — claim/unclaim, stale recovery, retry caps](https://dev.to/daniel_romitelli_44e77dc6/the-queue-was-a-table-how-i-built-claimunclaim-workers-with-skip-locked-stale-recovery-and-1ojm); [Potential consequences of using Postgres as a job queue](https://techcommunity.microsoft.com/blog/adforpostgresql/potential-consequences-of-using-postgres-as-a-job-queue/4514332).

---
*Pitfalls research for: v4 — Durable Execution (Postgres job queue + in-process worker pool on an existing money-moving pipeline)*
*Researched: 2026-07-13*
