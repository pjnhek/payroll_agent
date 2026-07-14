# Phase 16: Queue Substrate & Unblocked Webhook - Research

**Researched:** 2026-07-14
**Domain:** Durable Postgres job queue (SKIP LOCKED claim/lease/fencing) bolted onto an existing status-column state machine; FastAPI event-loop unblocking via `run_in_threadpool`. Zero new external dependencies.
**Confidence:** HIGH — every claim below is either read directly from live source at the cited `file:line` this session, or copied verbatim from the already-adversarially-validated canonical design docs. The only LOW-confidence items are the three discretionary numeric knobs (§ Discretionary Numbers), which are recommendations, not verified facts.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Phase boundary.** Two things land, nothing else: (1) the webhook stops blocking the event loop (`run_in_threadpool` around the Resend fetch + the psycopg ingest transaction; route stays `async def` for `await request.body()`; zero new schema); (2) a durable Postgres job queue (`jobs` table, `FOR UPDATE SKIP LOCKED` claim with expired-lease reclaim, lease-token fencing, 2 daemon worker threads via FastAPI `lifespan`, graceful lease release on shutdown) proven on exactly one producer — the operator "Retrigger" button. Nothing on the money path (the real webhook `new_run` path) moves. `BackgroundTasks` and the queue coexist safely because each producer uses exactly one mechanism; the other 7 `add_task` sites are untouched until Phase 19.
- **D-01 (rewind discriminated by `attempts`).** If `attempts > 1` on claim, this is a reclaim after a crash → the handler rewinds `EXTRACTING → RECEIVED` (clearing derived pipeline state) and re-runs from scratch. If `attempts == 1`, a failed CAS means another actor legitimately advanced the run → job goes `done`, no-op (strict INVARIANT J-1 preserved). This pulls part of the "Phase 18" rewind preamble forward deliberately, landing where its proof lives.
- **D-02 (rewind must NOT bump `reply_epoch`).** `clear_reply_context` bumps `reply_epoch`, which mints a fresh `message_id` under `uq_email_run_purpose_round_epoch`. That bump is the deliberate, documented residual risk for an **operator** retrigger. An **automatic** reclaim must NOT also bump it, or the milestone's headline claim ("at most one confirmation per run, per epoch") stops being DB-enforceable. The automatic rewind path must be distinct from `clear_reply_context` (or take a `bump_epoch=False` flag).
- **D-03 (`LEASE_SECONDS` is load-bearing).** Set well above the pipeline's observed worst case; document the chosen number, the measured runtime it derives from, and the double-run-is-harmless argument as a constraint comment. No lease heartbeat.
- **D-04 (generalize `concurrency-proof.yml` NOW).** Change the hard-coded test-file list to `pytest tests/ -m integration` collection so any `@pytest.mark.integration` test is picked up automatically. Keep the existing skip-guard.
- **D-05 (inventory-pinned test rewrites, not magic-number bumps).** `tests/test_status_drift.py`'s `test_exactly_three_new_indexes` (`sql.count("CREATE INDEX IF NOT EXISTS") == 3`) and `test_do_block_constraint_drops_are_column_anchored` (`sql.count("ANY (c.conkey)") == 2`) must be rewritten against a harvested name inventory, not just bumped.
- **D-06 (workers OFF under test; `drain_once()` explicit).** The whole suite depends on TestClient running `BackgroundTasks` synchronously. Tests for retrigger POST the route, assert a `jobs` row exists, then call `drain_once()` directly and assert the pipeline ran — the exact function the pump (Phase 17) and worker threads both call. Explicitly rejected: real threads + polling; a test-mode inline executor (vacuous-proof pattern).
- **D-07 (pool-budget hard-fails at boot).** `lifespan` asserts `WORKER_COUNT + 2 ≤ max_size (5)` and refuses to start if violated. Fail-fast, not clamp-and-warn.
- **D-08 (env-driven config).** `WORKER_COUNT`, `LEASE_SECONDS`, `MAX_ATTEMPTS` via the existing CI-gated `pydantic-settings` machinery. `WORKER_COUNT=0` is the test/dev off switch.
- **D-09 (in-process wake + slow durable poll).** `LISTEN/NOTIFY` and session advisory locks are banned under Supavisor transaction-mode pooling. After the enqueue transaction **commits**, set a `threading.Event` that wakes an idle worker immediately. DB polling is a slow durable fallback (~15–30s). The wake must fire after commit, never inside the transaction.
- **D-10 (no UI change this phase).** The retrigger CAS already lands the run at `RECEIVED`, already in `IN_FLIGHT_STATUSES`, already drives auto-refresh. Queue depth/attempts/dead-letter UI is OPS-01 (Phase 21) — out of scope.

### Claude's Discretion

- No `ON DELETE CASCADE` from `payroll_runs` to `jobs` (keep the attempt history append-only, matching the `email_messages` precedent).
- Exact numeric values for `LEASE_SECONDS`, the poll interval, and `MAX_ATTEMPTS` — pick them from the pipeline's measured runtime and document the derivation (D-03). See § Discretionary Numbers below.
- The precise `jobs` index set and the shape of the inventory-pinned guard rewrite (D-05). See § Jobs Index Set & D-05 Rewrite below.

### Deferred Ideas (OUT OF SCOPE)

- The `operator_resume` `dedup_key` discriminator — not a Phase 16 problem; that producer migrates in Phase 19.
- Ops view (queue depth, oldest-pending age, attempts, dead-letter list, the swallowing-bug alarm) — OPS-01, Phase 21.
- Deleting `sweep_stranded_runs` / `find_stranded_unconsumed_replies` / the `runs_list()` sweep block — FAIL-03, Phase 18. The sweep and the queue race long-term but in Phase 16 only retrigger is on the queue, so nothing yet races.
- The orchestrator's `ok`/`retryable`/`terminal` result contract — FAIL-01, Phase 18. In Phase 16 the orchestrator still swallows stage failures and returns normally; a retrigger job whose pipeline errors is recorded `done`. Not a regression — today's `BackgroundTasks` retrigger swallows identically.
- Migrating the other 7 `BackgroundTasks` producers — QUEUE-04, Phase 19.
- Versioned migrations + a hard deploy gate — pre-existing backlog, unchanged.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| QUEUE-01 | Webhook never blocks the event loop; `run_in_threadpool` around the Resend fetch + ingest transaction; zero new schema | § Architecture Patterns (Pattern 1), § run_in_threadpool Mechanics, § Validation Architecture Proof 1 |
| QUEUE-02 | `jobs` table with UNIQUE `dedup_key` (`ON CONFLICT DO NOTHING`), `lease_token`+`leased_until` fencing, `attempts` incremented at claim, claim query reclaims an expired lease | § Code Examples (claim/complete/fail SQL), § Jobs Index Set, § Validation Architecture Proofs 2 & 3 |
| QUEUE-03 | Bounded worker pool (2 daemon threads, FastAPI `lifespan`, `workers + 2 ≤ max_size=5`), workers release leases on graceful shutdown | § Architecture Patterns (worker lifecycle), § Discretionary Numbers, § Validation Architecture Proof 4 |
| QUEUE-05 | `jobs` carries transport state only (INVARIANT J-1); a failed CAS is a done job, not a retry; CI guard enforces the vocabulary | § Architecture Patterns (INVARIANT J-1), § Jobs Index Set & D-05 Rewrite (JobKind drift test), § Validation Architecture Proof 5 |

</phase_requirements>

## Summary

This phase is genuinely "transcription, not design" — `docs/superpowers/specs/2026-07-13-durable-execution-design.md` and `.planning/research/ARCHITECTURE.md` §3–§4 already specify the exact `jobs` DDL, the corrected claim/lease/fencing SQL (with the expired-lease reclaim fix baked in), and the enqueue-atomicity pattern. That work was adversarially validated by four researchers and is not re-derived here. This document's value-add is entirely in the parts CONTEXT.md flags as open: (1) a validation architecture that cannot be vacuous, given this repo's own documented history of a passing-but-meaningless concurrency proof; (2) concrete, derived values for the three discretionary knobs; (3) the exact `jobs` index set and the shape of the two magic-number test guards that will otherwise silently rot; (4) a definitive answer on `/health/schema` coverage; (5) the exact current line numbers of the three hard-coded monkeypatch tuples; and (6) `run_in_threadpool` mechanics traced against the installed Starlette version.

Beyond CONTEXT.md's explicit list, direct source tracing surfaced two load-bearing corrections the planner needs before writing tasks:

1. **`retrigger()` cannot be fixed by swapping `add_task` for `enqueue_job`.** The current route performs its CAS(es) and the stale-in-flight read-then-claim across **multiple separate, uncoordinated transactions** (each repo call defaults `conn=None` and opens its own). The canonical design requires the CAS, `clear_reply_context`, and the enqueue to share **one** caller-owned transaction. This is a genuine control-flow refactor (extracting a `conn`-aware `_claim_stale_in_flight` helper), not a one-line change.
2. **Deleting `orchestrator.py:232`'s unconditional `set_status(EXTRACTING)` — which ARCHITECTURE.md's own phase table assigns to its "Phase 4" (failure policy), not "Phase 2" (queue substrate) — must stay deleted-nowhere in Phase 16.** The plain webhook path (`new_run` → `run_pipeline_bg` → `orchestrator.run_pipeline`) is explicitly NOT migrated to the queue this phase (only retrigger is), and that line is the ONLY thing that ever moves a plainly-ingested run from `received` to `extracting`. Deleting it now would silently strand every ordinary (non-retriggered) run's visible status at `received` throughout processing. The new job handler must perform its own external CAS before calling the orchestrator; the orchestrator's internal call becomes a harmless same-value redundant write on the retrigger path and stays load-bearing everywhere else.

**Primary recommendation:** implement exactly what CONTEXT.md and ARCHITECTURE.md §3–§4 already specify for the `jobs` table and claim protocol verbatim; scope `JobKind` to exactly `{'run_pipeline'}` for this phase (not all 4 canonical kinds); refactor `retrigger()`'s transaction shape as its own explicit task; and build the validation architecture in § Validation Architecture below, which sequences hermetic-first (Proof 1, Proof 5 — no DB needed) before the two real-Postgres crash/reclaim proofs (Proof 2, Proof 3) and the lease-release proof (Proof 4).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Webhook request handling (verify, parse, enqueue) | API/Backend (FastAPI route) | — | Single-process FastAPI app; no separate frontend/SSR tier in this system |
| Blocking I/O offload (Resend fetch, ingest transaction) | API/Backend (AnyIO threadpool via `run_in_threadpool`) | — | Starlette's own threadpool primitive; not a separate worker service (Render free has none) |
| Durable job transport (`jobs` table) | Database/Storage (Postgres) | — | The queue's entire raison d'être is surviving process death; only a durable store can do that |
| Job claim/lease/dispatch | API/Backend (in-process daemon threads, `app/queue/`) | Database/Storage (the claim SQL itself) | Workers are Python threads inside the single Render instance; the atomicity guarantee lives in the SQL, not the Python |
| Business state transitions (`payroll_runs.status`) | API/Backend (`app/pipeline/orchestrator.py`, `app/db/repo/runs.py`) | Database/Storage (SQL CHECK constraint mirror) | INVARIANT J-1: this is the ONLY tier that ever decides "what's next"; the queue tier never does |
| Retrigger UI trigger | Browser/Client (POST form) → API/Backend (route) | — | No client-side queue awareness; D-10 explicitly defers any queue-status UI |

## Standard Stack

**Zero new dependencies.** Verified against `pyproject.toml` (read directly this session) and the installed package tree:

### Core (all pre-existing, all already pinned)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `psycopg[binary,pool]` | `3.3.4` (pinned) | Claim/complete/fail SQL, transactional enqueue | Already the sole DB driver; `_conn_ctx`/`conn=` convention already exists for exactly this "caller owns the transaction" pattern |
| `fastapi` | `0.138.0` (pinned) | `lifespan=` hook (currently absent — `app/main.py` is 16 lines with none) | `lifespan` is the FastAPI-native start/stop hook for the worker thread pool |
| `starlette` | `1.3.1` (installed, transitive via fastapi) | `run_in_threadpool` (`starlette.concurrency.run_in_threadpool`) — **[VERIFIED: direct read of the installed package source, `starlette/concurrency.py:32`]** | `async def run_in_threadpool(func, *args, **kwargs) -> T` — thin wrapper over `anyio.to_thread.run_sync`. This IS the mechanism `app/routes/pipeline_glue.py`'s sync `def` wrappers already exploit implicitly (FastAPI dispatches sync route handlers to the same AnyIO threadpool automatically) |
| stdlib `threading` | 3.12 | Daemon worker threads + `threading.Event` (D-09 wake) + `threading.Barrier` (test proofs) | NOT `asyncio.Task` (all downstream pipeline work is blocking sync I/O — LLM calls, psycopg); NOT `ThreadPoolExecutor` (adds a dispatcher thread for zero safety gain over N self-driving claim loops) |
| `pgcrypto` (Postgres extension) | already `CREATE EXTENSION IF NOT EXISTS` at `schema.sql:13` | `gen_random_uuid()` for `jobs.id` and `jobs.lease_token` | Already the PK default on 6 tables; zero new extension surface |
| Postgres | ≥15 (Supabase) | `FOR UPDATE SKIP LOCKED` | Available since PG 9.5; Supabase ships ≥15 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|-------------|-----------|----------|
| Hand-rolled `jobs` table + SQL | `procrastinate` / `pgqueuer` / `pgmq` | All three rejected by the prior research pass: `procrastinate` needs an async connector (a second connection pool against the 5-connection budget); `pgqueuer` wants its own CLI worker process (Render free has none); `pgmq` has no fencing token (the zombie-reclaim proof, criterion #3, would be unimplementable) and no unique dedup key |
| `threading.Thread(daemon=True)` workers | `asyncio.Task` workers | All downstream pipeline work (LLM calls via `openai`, psycopg, Resend) is synchronous blocking I/O — an `asyncio.Task` calling blocking code would itself block the loop, recreating QUEUE-01's exact defect one layer up |

**Installation:** none — every primitive above is already in `uv.lock`.

## Package Legitimacy Audit

**Not applicable.** This phase installs zero new external packages. All primitives (psycopg, FastAPI `lifespan`, Starlette `run_in_threadpool`, stdlib `threading`, Postgres `SKIP LOCKED`/`pgcrypto`) are already pinned in `pyproject.toml`/`uv.lock` and already running in production. `Package Legitimacy Audit` table intentionally omitted.

## Architecture Patterns

### System Architecture Diagram

```
Client-side action (operator clicks "Retrigger" in the dashboard)
        │
        ▼
POST /runs/{run_id}/retrigger  [sync route — Starlette dispatches to AnyIO threadpool]
        │
        ├─ ONE caller-owned transaction (conn.transaction()):
        │     ├─ CAS: claim_status(ERROR → RECEIVED) OR claim_status(APPROVED → RECEIVED)
        │     │        OR _claim_stale_in_flight(...)   [conn-aware, extracted from current inline logic]
        │     ├─ if claimed: epoch = clear_reply_context(run_id, conn=conn)   [MODIFIED: now RETURNS reply_epoch]
        │     └─ if claimed: enqueue_job(kind='run_pipeline', run_id=run_id,
        │                                dedup_key=f"run_pipeline:{run_id}:{epoch}", conn=conn)
        │        ON CONFLICT (dedup_key) DO NOTHING
        ├─ COMMIT
        ├─ after commit: worker_wake_event.set()   [D-09 — MUST be after commit, never inside]
        └─ 303 redirect to /runs/{run_id}   [dashboard already polls; run is IN_FLIGHT_STATUSES]

Daemon worker threads (×2, lifespan-owned)  ←──────────────┐
        │                                                    │ threading.Event.set() (in-process wake)
        ├─ drain_once():                                     │ OR slow durable poll (~15-30s, D-09)
        │     ├─ claim_job()  — ONE UPDATE statement, ────────┘
        │     │     commits immediately (releases the connection
        │     │     BEFORE any real work). FOR UPDATE SKIP LOCKED
        │     │     in the subquery. Reclaims: state='pending'
        │     │     OR (state='leased' AND leased_until < now()).
        │     │
        │     ├─ dispatch[job.kind](job):
        │     │     kind == 'run_pipeline':
        │     │       ├─ if job.attempts > 1:
        │     │       │     claim_status(EXTRACTING → RECEIVED)   [D-01 rewind, NOT clear_reply_context —
        │     │       │                                             D-02: must NOT bump reply_epoch]
        │     │       ├─ if not claim_status(RECEIVED → EXTRACTING): return (done, no-op — J-1)
        │     │       └─ orchestrator.run_pipeline(run_id)   [internal set_status(EXTRACTING) at :232
        │     │                                                becomes a harmless redundant same-value
        │     │                                                write here — see Pitfall 6]
        │     │
        │     └─ complete_job(id, lease_token)  — FENCED (WHERE lease_token = %(token)s)
        │        OR (on unhandled exception) fail_job(id, lease_token, ...) — ALSO fenced
        │
        └─ on lifespan shutdown: release ALL leases this process holds
              UPDATE jobs SET state='pending', lease_token=NULL, leased_until=NULL
              WHERE lease_token = ANY(%(held_tokens)s)   [instant handoff, not a 15-min stall]

Independently, unrelated to the above (QUEUE-01):
POST /webhook/inbound  [async def — UNCHANGED control flow, UNCHANGED schema]
        ├─ await request.body()                         [stays on the loop — HMAC needs raw bytes]
        ├─ gateway.verify(...)                            [pure CPU — stays on the loop]
        └─ await run_in_threadpool(_ingest_sync, raw_body) [NEW — the Resend fetch + the 5-outcome
                                                              ingest transaction move OFF the loop]
              └─ 200
```

### Recommended Project Structure
```
app/
├── queue/                    # NEW package
│   ├── __init__.py
│   ├── worker.py             # start(n)/stop(grace_seconds) — daemon threads, threading.Event wake,
│   │                          # lease-release-on-shutdown, drain_once() (shared with the future pump)
│   ├── dispatch.py           # kind -> handler table (scoped to {'run_pipeline': handle_run_pipeline}
│   │                          # in Phase 16 — NOT all 4 canonical kinds; see Pitfall 7)
│   └── handlers/
│       ├── __init__.py
│       └── pipeline.py       # handle_run_pipeline: D-01 rewind + CAS + orchestrator dispatch
├── models/
│   └── job.py                 # NEW: JobKind (scoped enum), JobState, Job (dataclass/pydantic model)
└── db/
    └── repo/
        └── jobs.py            # NEW: enqueue_job, claim_job, complete_job, fail_job, release_lease,
                                # queue_stats (test-only helper). Every fn takes conn: psycopg.Connection
                                # | None = None, follows _conn_ctx/_nulltx exactly like every other
                                # aggregate module in this package.
```

### Pattern 1: `run_in_threadpool` around the ingest boundary (QUEUE-01)
**What:** Wrap the currently-synchronous parse+ingest work in one `run_in_threadpool` call so the event loop is free while it executes.
**When to use:** Any `async def` route performing blocking I/O with no natural `await` point.
**Example:**
```python
# Source: starlette/concurrency.py:32 (installed package, read directly), applied to
# app/routes/webhook.py's current control flow (lines 56-220 as read this session).
from starlette.concurrency import run_in_threadpool

@router.post("/webhook/inbound")
async def inbound(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    raw_body: bytes = await request.body()          # UNCHANGED — HMAC needs raw bytes
    # ... signature verification stays on the loop (pure CPU) ...

    # NEW: everything blocking (gateway.parse_inbound's Resend fetch + the 5-outcome
    # ingest transaction, webhook.py:87-220 today) moves into ONE sync helper, called
    # via run_in_threadpool. Response-shaping (webhook.py:224-314) stays on the loop —
    # it does its own separate blocking repo calls in the 'duplicate' branch today
    # (see Pitfall 3) that a maximally-complete fix would ALSO wrap.
    result = await run_in_threadpool(_parse_and_ingest_sync, raw_body)
    return _shape_response(result, background_tasks)  # cheap, pure Python
```
**Note:** `run_in_threadpool` submits to AnyIO's threadpool (default ~40 threads) — the SAME pool Starlette already dispatches sync `def` routes to. This is not the queue's dedicated 2-worker pool; it is a burst-shaped, per-request offload, correctly scoped since it never holds a DB connection across an LLM call (there is no LLM call in the ingest path).

### Pattern 2: Caller-owned transaction spanning CAS + context-clear + enqueue (QUEUE-02)
**What:** `enqueue_job(..., conn=conn)` inside the SAME `conn.transaction()` as the state change that owes it — the enqueue and the CAS succeed or fail together.
**When to use:** Every producer that migrates to the queue. This phase: `retrigger` only.
**Example:**
```python
# Source: .planning/research/ARCHITECTURE.md §3 (verbatim canonical design), applied to
# the ACTUAL current app/routes/runs.py:266-381 control flow read this session.
with repo.get_connection() as conn, conn.transaction():
    claimed = (
        repo.claim_status(run_id, RunStatus.ERROR, RunStatus.RECEIVED, conn=conn)
        or repo.claim_status(run_id, RunStatus.APPROVED, RunStatus.RECEIVED, conn=conn)
        or _claim_stale_in_flight(run_id, conn=conn)   # NEW helper — extracted from the
    )                                                    # current inline load_run+threshold+
    if claimed:                                          # claim_status logic, conn-threaded
        epoch = repo.clear_reply_context(run_id, conn=conn)   # MODIFIED: now returns reply_epoch
        repo.enqueue_job(
            kind=JobKind.RUN_PIPELINE,
            run_id=run_id,
            dedup_key=f"run_pipeline:{run_id}:{epoch}",
            conn=conn,
        )
# committed. worker_wake_event.set() AFTER this block exits (D-09).
return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
```

### Anti-Patterns to Avoid

- **Deleting `orchestrator.py:232` in this phase:** the canonical design's general integration-points table lists this deletion, but ARCHITECTURE.md's OWN phase-by-phase breakdown assigns it to "Phase 4" (this project's Phase 18), not "Phase 2" (this project's Phase 16). In Phase 16 the plain webhook path still calls `orchestrator.run_pipeline` directly via `BackgroundTasks` with no external CAS anywhere — deleting the line strands every ordinary run visibly at `received`. See Pitfall 6.
- **Holding the claim transaction across `orchestrator.run_pipeline`:** the claim statement must commit and release its connection BEFORE the handler calls into the pipeline. `_run_stages` already has its own documented rule against spanning a transaction across an LLM call (`orchestrator.py` comments) — the queue inherits, does not invent, that rule.
- **A `JobResult` enum with real `retryable`/`terminal` classification in Phase 16:** `orchestrator.run_pipeline` never raises past its own boundary today (it catches every stage failure internally and writes `ERROR`). A rich failure taxonomy has nothing real to classify yet — that's FAIL-01, Phase 18. Build only what Phase 16 needs: the handler either returns normally (`complete_job`) or an exception escapes it (a DB blip, an import error) → `fail_job` with a blunt backoff, no retryable/terminal split.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|--------------|-----|
| Atomic claim under concurrent workers | A `SELECT ... FOR UPDATE` + application-level "is anyone else holding this" check | `UPDATE jobs SET state='leased' ... WHERE id = (SELECT id FROM jobs WHERE ... FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *` — the canonical single-statement claim from ARCHITECTURE.md §4 | This project already proved (Phase 10, live memory) that anything less than a genuine `SKIP LOCKED` subquery-targeted `UPDATE` either serializes falsely (via a shared connection/portal) or races incorrectly. Don't re-derive; the SQL is already specified and corrected (C1 fix baked in) |
| Cross-process wake-up under Supavisor transaction-mode pooling | `LISTEN/NOTIFY`, session advisory locks | In-process `threading.Event` (same-process wake) + slow durable DB poll (D-09) | Both `LISTEN/NOTIFY` and session advisory locks fail **silently** (not loudly) under transaction-mode pooling per `app/db/supabase.py:1-18`'s own documented rationale for `prepare_threshold=None` |
| Worker pool | A `ThreadPoolExecutor`, `concurrent.futures`, or a third-party task queue library | `threading.Thread(daemon=True)` × `WORKER_COUNT`, each running its own claim loop | N self-driving loops need no dispatcher; a `ThreadPoolExecutor` adds a submission/dispatch thread with zero safety benefit here |

**Key insight:** every piece of "real machinery" in this phase (the claim SQL, the fencing predicate, the enqueue-atomicity pattern) is already fully specified in `.planning/research/ARCHITECTURE.md` §3–§4 and cross-validated by 4 independent researchers plus a Codex review. The only genuinely new engineering in Phase 16 is (a) wiring these primitives into THIS repo's specific existing control flow (`retrigger`'s multi-transaction shape, `orchestrator.py`'s status-write discipline) without breaking the still-untouched plain webhook path, and (b) the test/proof harness.

## Runtime State Inventory

Not applicable — this is a greenfield feature addition (new `jobs` table, new `app/queue/` package), not a rename/refactor/migration phase. No existing stored data, live service config, OS-registered state, or build artifacts carry a name being changed.

## Common Pitfalls

### Pitfall 1: Vacuous concurrency proofs via a shared TestClient portal
**What goes wrong:** N threads POSTing to an `async def` route through a single shared `starlette.testclient.TestClient` execute serially through that client's internal AnyIO portal — the race under test never actually happens, and the proof passes even with the safety mechanism deleted.
**Why it happens:** This exact failure shipped once already in this repo (Phase 10's original concurrency proof, per project memory) — the precedent this milestone's own PROOF requirements explicitly name.
**How to avoid:** For criterion #1 (event-loop non-blocking), drive the ASGI app directly via `httpx.AsyncClient(transport=ASGITransport(app=app))` + `asyncio.gather(...)` inside a genuine `async def` test body (run via `asyncio.run()`), never `TestClient`. For criteria #2/#3 (claim races), drive `repo`-layer functions (`claim_job`, `complete_job`) directly from `threading.Barrier`-released OS threads against a real Postgres — never through an HTTP route (mirrors the Phase 10 fix's Surface A/C pattern).
**Warning signs:** A proof that passes on the very first attempt with zero flakiness across multiple runs, or a proof whose "kill the worker" step never actually holds a lease at the moment of the simulated crash.

### Pitfall 2: `/health/schema` does NOT auto-cover a new table — CONFIRMED
**What goes wrong:** Assuming `diff_against_live` (`app/db/schema_introspect.py`) generically diffs every table in `schema.sql` against the live DB.
**Why it happens:** `expected_schema()` (`schema_introspect.py:134-151`) hardcodes `tables = {"payroll_runs": ..., "email_messages": ...}` — read directly this session. `diff_against_live`'s live-column query (`_live_columns`) is generic (parameterized by table name), but the CHECK-value drift query (lines 221-242) is ALSO hardcoded to exactly these two tables via a `CASE WHEN c.conrelid = to_regclass('public.payroll_runs') THEN 'status' ELSE 'purpose' END` branch and an `IN (to_regclass('public.payroll_runs'), to_regclass('public.email_messages'))` filter.
**How to avoid:** If column-drift coverage for `jobs` is wanted on `/health/schema`, add `"jobs": frozenset(_columns_for_table(sql, "jobs"))` to the `tables` dict — that part generalizes for free. CHECK-value (kind/state) drift detection would need NEW code in `diff_against_live`'s live-query section, since `jobs.kind`/`jobs.state` are declared **inline** in `CREATE TABLE jobs (...)`, not via the DO-block migration pattern `_do_block_check_values` parses. This is optional for Phase 16 (success criterion #5 requires a CI guard, not necessarily wiring through the live health probe) — recommend a standalone static test mirroring `test_status_drift.py`'s shape instead (see § Jobs Index Set & D-05 Rewrite), and treat `/health/schema` registration as a nice-to-have, not blocking.
**Warning signs:** A live deploy silently missing the `jobs` table would still report `{"status": "in_sync"}`.

### Pitfall 3: The webhook's response-shaping branches ALSO do blocking DB I/O, outside QUEUE-01's cited scope
**What goes wrong:** QUEUE-01's file:line citation (`webhook.py:96` and `webhook.py:139-220`) doesn't mention that the "duplicate" outcome's redelivery-reschedule branch (`webhook.py:241-270`, read directly this session) performs ADDITIONAL synchronous repo calls (`repo.get_inbound_by_message_id`, `repo.load_run`) and `pipeline_glue.reply_sender_ok` → `repo.find_business_by_sender` — all still directly on the event loop, post-commit, outside the `run_in_threadpool` wrap described in Pattern 1 above.
**Why it happens:** These are fast, single-row, indexed lookups (~1-5ms), much cheaper than the Resend HTTP round-trip they were never designed to compete with attention-wise — easy to overlook when scoping "the ingest transaction."
**How to avoid:** Decide explicitly whether to fold these into the same `run_in_threadpool` call (cleanest, fully closes the loop-blocking surface) or leave them on the loop with a documented rationale (their cost is genuinely negligible vs. the Resend fetch). Either is defensible; leaving it undecided is not — criterion #1's proof will only exercise the `new_run` path (freshly distinct emails), so this gap won't be caught by that proof either way.
**Warning signs:** A future load test showing tail latency on duplicate/redelivery traffic that the primary proof never surfaces.

### Pitfall 4: `bootstrap.py`'s `_DROP_ORDER` will silently orphan `jobs` rows across test resets
**What goes wrong:** `app/db/bootstrap.py`'s `_DROP_ORDER` list (read directly this session, lines 73-81) enumerates `["name_matches", "paystub_line_items", "eval_results", "email_messages", "payroll_runs", "employees", "businesses"]` — no `jobs`. The `seeded_db` fixture's `--reset` path (the sole reset owner, gated by `ALLOW_DB_RESET`) drops exactly this list; `jobs` would never be included and would silently accumulate stale rows referencing deleted-and-recreated `run_id`s across every test run that resets the DB.
**Why it happens:** `_DROP_ORDER` is a hand-maintained list with no drift guard against the actual live schema.
**How to avoid:** Add `"jobs"` to `_DROP_ORDER`, positioned before `"payroll_runs"` (its FK target). Each `DROP TABLE IF EXISTS ... CASCADE` in bootstrap.py already uses `CASCADE`, so exact ordering is defensive-not-strictly-required, but explicit ordering documents intent and matches the file's own stated convention ("explicit reverse order documents the dependency direction").
**Warning signs:** A live-DB integration test passing locally with a fresh DB but flaking on CI's second run in the same session, or a `jobs` row count that only ever grows across a local dev session's repeated `--reset` cycles.

### Pitfall 5: `clear_reply_context` currently returns `None` and lives in a different file than the canonical docs imply
**What goes wrong:** ARCHITECTURE.md's SQL example calls `repo.clear_reply_context(run_id, conn=conn)` and expects the return value to be the new `reply_epoch` (needed for `dedup_key`). Read directly this session (`app/db/repo/pipeline_state.py:346-385`): the function currently executes an `UPDATE ... reply_epoch = reply_epoch + 1 ...` with **no `RETURNING` clause and no return statement** — it returns `None` implicitly. Also: it lives in `app/db/repo/pipeline_state.py`, not `app/db/repo/runs.py` (the canonical docs' prose loosely attributes it to "runs.py" in a comment, but the actual module is `pipeline_state.py` — confirmed via the facade re-export list in `app/db/repo/__init__.py`).
**How to avoid:** Add `RETURNING reply_epoch` to the `UPDATE` and `.fetchone()` + return the value. Edit `app/db/repo/pipeline_state.py`, not `runs.py`.
**Warning signs:** `epoch = repo.clear_reply_context(...)` silently binding `None`, producing a `dedup_key` of `f"run_pipeline:{run_id}:None"` — which still technically works as a unique string (Python renders `None` fine in an f-string) but defeats the entire purpose of keying on the numeric epoch, and would make every retrigger after the first look byte-identical in dedup-key SHAPE while differing only by the literal string `None` never changing — actually WORSE: since the column truly increments in the DB even though the caller never sees it, this bug produces `dedup_key` values that are all `"run_pipeline:{run_id}:None"` — identical across every retrigger — so the SECOND retrigger's enqueue would hit `ON CONFLICT DO NOTHING` against the FIRST retrigger's now-`done` job row and silently swallow itself. This is the exact "second retrigger is swallowed" failure ARCHITECTURE.md §3 warns about for a naive `dedup_key`, reintroduced by a return-value bug rather than a missing-epoch bug.

### Pitfall 6: Deleting `orchestrator.py:232` in Phase 16 strands ordinary (non-retriggered) runs at `received`
See § Architecture Patterns → Anti-Patterns above and § Summary point 2. Restated as a pitfall because it is the single highest-risk "looks like a simple refactor, actually breaks the money path" trap in this phase, and the canonical docs' own general integration-points table (as opposed to their phase-by-phase breakdown table) can read as if it belongs here.

### Pitfall 7: Pre-declaring all 4 canonical `JobKind` values when only 1 has a handler
**What goes wrong:** ARCHITECTURE.md's full design names 4 kinds (`ingest`, `run_pipeline`, `resume_reply`, `operator_resume`). Phase 16 implements a real handler for exactly ONE (`run_pipeline`, via retrigger). If `JobKind` is defined with all 4 members now, the CI guard `set(JobKind) == {name for name in dispatch.HANDLERS}` (ARCHITECTURE §1, one of the "four guards in the same spirit") is **unsatisfiable** in Phase 16 — 3 kinds would have no registered handler.
**How to avoid:** Scope `JobKind` (the Python enum) AND the `jobs.kind` SQL `CHECK` to exactly `{'run_pipeline'}` for this phase. Widen both in Phase 17/19 as each new kind gets a real handler — using the same idempotent DO-block DROP+RE-ADD pattern already proven twice in `schema.sql` for `payroll_runs.status` and `email_messages.purpose` (by then `jobs` will have live rows, so the widening genuinely needs that migration shape, unlike the inline-only definition Phase 16 can use on a still-empty table).
**Warning signs:** A CI guard for "JobKind == dispatch table" that is permanently red from the moment it's written, or one that's been pre-loosened to `⊇` instead of `==` — quietly defeating the guard's whole purpose (a phantom kind with no handler is exactly what J-1's guard #3 exists to catch).

### Pitfall 8: CONTEXT.md's citation of `test_threading.py`'s two monkeypatch tuples is broader than what Phase 16 actually touches — VERIFIED
**What goes wrong:** Assuming both `test_threading.py` tuples (lines 340-354, 423-436 — confirmed via `grep -n "for name in ("`, matching CONTEXT.md's citation almost exactly) need `app/db/repo/jobs.py` function names added, as the "three tuples total" framing implies.
**What was actually verified this session:** Both tuples exclusively back two `orchestrator.resume_pipeline`-level tests — `test_partial_reply_preserves_hours` (the function containing the line-340 tuple) and `test_resume_on_non_awaiting_reply_run_does_not_mutate` (line-423 tuple). Neither test calls `retrigger()`, and — per this document's own finding (§ Summary point 2, Pitfall 6) — Phase 16 does NOT touch `orchestrator.resume_pipeline` or its internals at all; the D-01 rewind preamble lives entirely in the NEW `app/queue/handlers/pipeline.py`, external to the orchestrator. `grep -n "^def test_\|retrigger" tests/test_threading.py` (run this session) confirms there is no `retrigger`-related test anywhere in this file today.
**Conclusion:** as scoped by this phase's actual code changes, these two specific tuples need NO modification. `tests/conftest.py`'s `fake_repo` tuple (lines 994-1052) is the one tuple that unconditionally needs new `jobs.py` function names (it backs `client`-fixture tests, which will include any new HTTP-level retrigger test). Treat CONTEXT.md's "three tuples total" as a vigilance reminder for whichever test file ends up hosting the new retrigger-specific tests, not a mandate to touch files that turn out not to need it — if the planner adds retrigger tests to `test_threading.py` itself (a plausible home, since it already hosts reply/threading tests), THEN these tuples would need the same treatment as `conftest.py`'s.
**Warning signs:** Editing these two tuples without a corresponding new test in the same file that actually exercises `jobs.py` functions — a change with no test coverage driving it.

## Jobs Index Set & D-05 Rewrite

### The `jobs` index set (Claude's Discretion, resolved)

Exactly what the canonical DDL (ARCHITECTURE.md §4) already specifies — no additions recommended for Phase 16:

| Index | Kind | Backing predicate |
|---|---|---|
| `jobs_pkey` | Implicit (PRIMARY KEY on `id`) | — |
| `uq_jobs_dedup_key` | Implicit (UNIQUE on `dedup_key`) | Serves both the `ON CONFLICT (dedup_key) DO NOTHING` enqueue AND any future dedup-key lookup |
| `idx_jobs_claimable` | Explicit `CREATE INDEX IF NOT EXISTS ... ON jobs (priority, available_at) WHERE state IN ('pending','leased')` | Matches the claim query's `WHERE` predicate exactly (partial index — `done`/`dead` rows, the overwhelming majority over time, are never indexed, so the claim stays O(1) with no purge job) |

No index on `run_id` is added in Phase 16 — nothing in this phase's scope queries `jobs` by `run_id` (the ops view that would, `GET /internal/queue`, is OPS-01/Phase 21). Adding one preemptively would be exactly the kind of speculative-scale machinery the milestone's own "Out of Scope" table warns against (`~1 email/client/week`). Revisit when Phase 21 actually needs it.

### The D-05 test rewrite — precise, verified shape

Two existing guards in `tests/test_status_drift.py` (both read directly this session):

**1. `test_exactly_three_new_indexes` (line 327-330) — WILL detonate.** Currently: `assert sql.count("CREATE INDEX IF NOT EXISTS") == 3`. Adding `idx_jobs_claimable` makes this 4. Per D-05, rewrite as a named-set comparison, not a bumped magic number:
```python
def test_expected_indexes_present_and_no_others(self) -> None:
    sql = _SCHEMA_SQL.read_text()
    expected = {
        "idx_payroll_runs_created_at",
        "idx_payroll_runs_status",
        "idx_email_messages_run_direction_state",
        "idx_jobs_claimable",
    }
    found = set(re.findall(r"CREATE INDEX IF NOT EXISTS (\w+)", sql))
    assert found == expected, f"index inventory drifted: {found ^ expected}"
```
This is self-documenting (a future index addition fails with the exact name missing from the assertion, not a bare "3 != 4"), and immune to false negatives from reordering.

**2. `test_do_block_constraint_drops_are_column_anchored` (line 207-232) — VERIFIED will NOT need its count bumped.** Currently: `assert sql.count("ANY (c.conkey)") == 2`. This pattern appears exactly twice, once each in the `payroll_runs.status` and `email_messages.purpose` idempotent DO-block CHECK-migration blocks (both read directly in `schema.sql`). **`jobs.kind` and `jobs.state` do NOT need this migration pattern**, because `jobs` is a brand-new table created via `CREATE TABLE IF NOT EXISTS jobs (...)` with its `CHECK (kind IN (...))`/`CHECK (state IN (...))` declared **inline** — the DO-block DROP+RE-ADD idiom exists specifically to widen a CHECK on a table that may already have LIVE ROWS under the old constraint, which is not jobs' situation on first deploy. The count should stay 2 through Phase 16. **Still rewrite it to a name/count-with-rationale form per D-05's spirit**, so a future genuine third DO-block (e.g. widening `jobs.kind`'s CHECK once Phase 17/19 add more kinds to an already-populated table) is a deliberate, reviewed bump rather than a silent one:
```python
def test_do_block_constraint_drops_are_column_anchored(self) -> None:
    sql = re.sub(r"--[^\n]*", "", _SCHEMA_SQL.read_text())
    assert "conname LIKE" not in sql
    # Exactly these two migration blocks exist today. jobs.kind/jobs.state use an
    # INLINE CHECK (no live rows to migrate on first deploy) and deliberately do NOT
    # add a third occurrence here -- see 16-RESEARCH.md § Jobs Index Set & D-05
    # Rewrite for why. A genuine third occurrence (e.g. widening jobs.kind's CHECK
    # once it has live rows, Phase 17+) is a reviewed, deliberate bump to this list.
    EXPECTED_DO_BLOCKS = {"payroll_runs_status_check", "email_messages_purpose_check"}
    assert sql.count("ANY (c.conkey)") == len(EXPECTED_DO_BLOCKS), (
        f"expected exactly {len(EXPECTED_DO_BLOCKS)} conkey-anchored constraint "
        "matchers; see the comment above before changing this count"
    )
```

### The NEW job-kind drift test needs its own inline-CHECK parser

`schema_introspect.py`'s `_do_block_check_values` (used by `expected_schema()` for `payroll_runs.status`/`email_messages.purpose`) specifically searches for a constraint-name literal FOLLOWED BY a `CHECK (col IN (...))` — the executable DO-block re-add form. `jobs.kind`'s CHECK has no such named DO-block re-add; it is the FIRST `CHECK (kind IN (...))` inside the `CREATE TABLE jobs (...)` body. Reuse `schema_introspect._create_body` (already generic, parenthesis-balanced) to extract the table body, then a plain regex for `CHECK\s*\(\s*kind\s+IN\s*\((.*?)\)\s*\)` within it — a genuinely different, simpler parser than the DO-block one, not a call to the same helper with different arguments.

## Discretionary Numbers

CONTEXT.md's D-03 requires each number to carry its measured-runtime derivation and the double-run-is-harmless argument as a written constraint comment, not just a bare default. Recommended values below, each traceable to a specific already-verified source in this codebase.

### `LEASE_SECONDS = 900` (15 minutes)

**Derivation (reuse, don't re-derive):** `app/routes/runs.py:34-68` (read in full this session) already computes and documents the pipeline's worst-case gap between two consecutive DB writes on the longest real path, for its OWN `STALE_THRESHOLD` constant:
- `call_structured`'s per-call ceiling: `_STRUCTURED_TIMEOUT_S` (45.0s) × 2 app-level retry attempts = 90s.
- The resume path's back-to-back double extraction (reply + combined-email extraction): 45s × 2 attempts × 2 calls = 180s.
- `call_text`'s clarification-draft ceiling: `_CLARIFICATION_TIMEOUT_S` (30.0s) × 1 = 30s, sequential (not concurrent) after the double extraction.
- Total worst case: 180s + 30s = **210s (3.5 min)**.
- `STALE_THRESHOLD = timedelta(minutes=15)` — ~4.3× that ceiling.

**Recommendation:** define a new `QUEUE_LEASE_SECONDS` settings field (D-08 requires it be its own env-driven knob, so it cannot literally BE `STALE_THRESHOLD_SECONDS`), defaulting to **900**, with a comment cross-referencing `STALE_THRESHOLD`'s derivation at `runs.py:34-68` rather than re-deriving the arithmetic a second time (single source of truth for the worst-case number; two independently-maintained copies of "210s × 4" is exactly the kind of drift risk this repo's own conventions warn against elsewhere).

**Double-run-is-harmless argument (write this into the constant's docstring, per D-03):** a lease that expires under a still-alive-but-slow worker causes AT MOST a duplicate `orchestrator.run_pipeline` execution, never a duplicate client-facing side effect — because (a) `claim_status`'s CAS makes every `payroll_runs.status` advance at-most-once regardless of how many times the handler runs, (b) `replace_line_items` is DELETE-by-run-then-INSERT (idempotent by value), and (c) delivery's purpose-aware already-sent guard + `uq_email_run_purpose_round_epoch` block a second client email even across a genuine double-run. This is the same argument `retrigger`'s own docstring already makes for allowing stale `SENT`-status claims — reuse it, don't reinvent it.

### Poll interval = 20 seconds

D-09 locks the band (~15-30s) but leaves the exact value to discretion. **Recommendation: 20s**, splitting the difference. Rationale: in Phase 16 the ONLY thing this poll can discover that the in-process `threading.Event` wake cannot is (a) an expired-lease reclaim (bounded below by `LEASE_SECONDS=900`, so polling faster than ~60s buys nothing for this case) or (b) a cold-started instance where the enqueuing process no longer exists (this scenario is genuinely latency-sensitive, favoring the low end of the band). 20s balances both without meaningfully increasing DB chatter against the 5-connection budget (a brief `SELECT`-shaped claim attempt every 20s is negligible load at ~1 email/client/week traffic).

### `MAX_ATTEMPTS = 5`

**Recommendation: 5**, matching the value already used as the canonical DDL's example default (`ARCHITECTURE.md` §4's `CREATE TABLE jobs (...)`). **Scoping caveat, load-bearing for planning:** in Phase 16, `attempts` only increments via genuine crash-reclaim (there is no retryable/terminal backoff loop yet — that's FAIL-02, Phase 18), so `MAX_ATTEMPTS=5` in THIS phase means "a single retrigger survives up to 5 worker-crash cycles before dead-lettering," not "5 retries of a classified failure." Given a single-instance Render deployment, 5 consecutive crashes on the same job is already an extreme, almost certainly infra-catastrophic scenario — 5 is generous headroom, not a tight bound. Document this scoping distinction in the constant's own comment so a future reader (Phase 18) doesn't assume `MAX_ATTEMPTS` already encodes a backoff policy it does not yet have.

## Code Examples

### The claim/complete/fail SQL (verbatim from the adversarially-corrected canonical design)
```sql
-- Source: .planning/research/ARCHITECTURE.md §4 (verbatim; already includes the C1 fix
-- both prior drafts of the design lacked). The `jobs` DDL itself, the partial index, and
-- the CHECK constraints are also specified there in full — not re-derived here.

-- CLAIM — one statement, one implicit transaction, commits before any real work.
UPDATE jobs j
   SET state        = 'leased',
       lease_token  = gen_random_uuid(),
       leased_until = now() + (%(lease_seconds)s || ' seconds')::interval,
       attempts     = j.attempts + 1,
       updated_at   = now()
 WHERE j.id = (
       SELECT c.id
         FROM jobs c
        WHERE c.attempts < c.max_attempts
          AND (
                (c.state = 'pending' AND c.available_at <= now())
             OR (c.state = 'leased'  AND c.leased_until <  now())   -- reclaim an expired lease
              )
        ORDER BY c.priority, c.available_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
 )
RETURNING j.id, j.kind, j.run_id, j.attempts, j.max_attempts, j.lease_token;

-- COMPLETE — fenced. row is None => this worker is a zombie; log and drop, do not retry.
UPDATE jobs
   SET state = 'done', lease_token = NULL, leased_until = NULL, updated_at = now()
 WHERE id = %(id)s AND state = 'leased' AND lease_token = %(token)s
RETURNING id;

-- FAIL/RESCHEDULE — ALSO fenced (the forgotten fence people miss is here, not complete).
UPDATE jobs
   SET state = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'pending' END,
       available_at = now() + (%(backoff_seconds)s || ' seconds')::interval,
       last_error   = %(scrubbed_detail)s,
       lease_token  = NULL, leased_until = NULL, updated_at = now()
 WHERE id = %(id)s AND state = 'leased' AND lease_token = %(token)s
RETURNING state;

-- SHUTDOWN RELEASE — this worker's own held leases, back to pending immediately.
UPDATE jobs SET state='pending', available_at=now(),
                lease_token=NULL, leased_until=NULL, updated_at=now()
 WHERE lease_token = ANY(%(held_tokens)s) AND state = 'leased';
```

### `run_in_threadpool` — the verified import
```python
# Source: starlette/concurrency.py:32, read directly from the installed package
# (starlette 1.3.1, transitive via fastapi==0.138.0). This IS the correct, currently-
# available import for QUEUE-01 — no version bump needed.
from starlette.concurrency import run_in_threadpool

result = await run_in_threadpool(_parse_and_ingest_sync, raw_body)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|-------------------|---------------|--------|
| `BackgroundTasks.add_task` for retrigger (in-process-memory, dies on redeploy/spin-down) | Durable `jobs` row + daemon worker claim | This phase | A retrigger survives a process death; a stuck run recovers without a human re-clicking |
| Implicit "the dashboard sweep is the only recovery mechanism" | An explicit lease-based reclaim protocol, independently correct of the sweep | This phase (queue substrate only); sweep deletion is Phase 18 | Sets up FAIL-03's later deletion of `sweep_stranded_runs` — not done yet, but the substrate that makes it safe to delete lands now |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|----------------|
| A1 | `LEASE_SECONDS = 900` (reusing the exact derivation already documented for `STALE_THRESHOLD` at `app/routes/runs.py:34-68`) is the right value | § Discretionary Numbers | If the real worst-case pipeline runtime has grown since that comment was written (e.g. a slower model swap), 900s could be too tight, causing a live-but-slow worker's lease to expire and get reclaimed while still legitimately working — the design's own analysis (ARCHITECTURE §4) shows this is bounded/harmless (idempotent re-run, guarded sends), so the risk is wasted work, not incorrectness |
| A2 | Poll interval = 20s (splitting D-09's locked 15-30s range) | § Discretionary Numbers | Low risk either way within the locked band; a value at the low end (15s) trades slightly more DB chatter for marginally faster cold-instance recovery |
| A3 | `MAX_ATTEMPTS = 5` (matching the value already used as an example in the canonical DDL) | § Discretionary Numbers | Since Phase 16 has no real retryable/terminal classification (FAIL-01 is Phase 18), `MAX_ATTEMPTS` in this phase only bounds how many worker-crash reclaims a single retrigger job survives before dead-lettering — 5 crash-cycles is generous headroom for a single-instance deploy; too low would dead-letter a retrigger that's merely unlucky across two or three real crashes |
| A4 | Registering `jobs` in `/health/schema`'s column-diff dict is worth doing in this phase even though it's not required by any of the 5 success criteria | Pitfall 2 | If skipped, a live deploy missing the `jobs` table (e.g. a bootstrap failure) would report `in_sync` — a real but narrow observability gap, not a correctness bug |

**If this table is empty:** N/A — see rows above; all four are recommendations built from verified derivations already present in this codebase, not blind guesses, but the exact final numbers are the discretion CONTEXT.md explicitly leaves to planning.

## Open Questions

1. **Should the response-shaping "duplicate" branch's extra blocking DB reads (Pitfall 3) also move into `run_in_threadpool`?**
   - What we know: they are fast (~1-5ms, single indexed lookups), and criterion #1's proof (fresh distinct emails) won't exercise them either way.
   - What's unclear: whether "the webhook never blocks the event loop" (QUEUE-01's plain-English framing) is meant literally-universally or scoped to the two cited hot paths.
   - Recommendation: fold them in for a genuinely complete fix (it's cheap — the same `run_in_threadpool` wrap, no new code shape) unless the planner has a reason to keep the diff minimal; either choice should be a stated decision, not an oversight.

2. **Does `/health/schema` need `jobs` column-diff coverage in Phase 16, or is a standalone static CI test (mirroring `test_status_drift.py`) sufficient for success criterion #5?**
   - What we know: the CI guard success criterion #5 requires is satisfiable by a pure static test with zero changes to `schema_introspect.py`.
   - What's unclear: whether the project wants live-deploy drift observability for `jobs` NOW or as part of a later ops-visibility pass.
   - Recommendation: ship the static CI test (required); treat `/health/schema` registration as optional discretionary scope, likely a 10-minute add given `_live_columns` is already generic — low cost either way.

## Environment Availability

Skipped — this phase has no external service dependency beyond the already-live Postgres connection (verified via `app/db/supabase.py`, already in production use) and zero new packages (see § Standard Stack / § Package Legitimacy Audit). No new CLI tools, runtimes, or third-party services are introduced.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (bare `pytest` + `pytest.mark.integration` custom marker, already registered in `pyproject.toml` `[tool.pytest.ini_options]`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (markers only; no separate `pytest.ini`) |
| Quick run command | `uv run pytest -q` (hermetic — no live DB, no live LLM; the default CI `test` job) |
| Full suite command (this phase's live-DB proofs) | `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres ALLOW_DB_RESET=1 ALLOW_UNSIGNED_FIXTURES=true uv run pytest tests/ -m integration -v` |

### Why the 5 success criteria need 5 DIFFERENT proof shapes, not 1 generic "test the queue" file

This repo has a documented precedent (Phase 10, memory) of a "concurrency proof" that passed while proving nothing, because N threads were fired at a shared `TestClient` wrapping an `async def` route with no genuine `await` in its blocking body — the threads serialized through one ASGI portal and the race under test never triggered. **Each proof below names its own vacuous twin and the exact mutation that must turn it red**, per the project's own PROOF-05 mandate and D-06's constraint (workers OFF under test; `drain_once()` called explicitly; races drive the sync repo seam under a `threading.Barrier`, never an HTTP route — EXCEPT Proof 1, which is specifically ABOUT the HTTP/event-loop layer and therefore cannot use the sync-seam technique).

### Phase Requirements → Proof Map

| Success Criterion | Proof # | Needs real Postgres? | Test Type | Vacuous twin (what would make it pass wrongly) |
|---|---|---|---|---|
| #1 (webhook non-blocking) | 1 | **No** (hermetic) | integration-shaped, but no DB needed | Using `TestClient` instead of `httpx.AsyncClient`+`ASGITransport` — would serialize and pass even without `run_in_threadpool` |
| #2 (retrigger survives worker death + resumes on drain) | 2 | **Yes** | `@pytest.mark.integration` | Never actually leasing the job before "killing" the worker — the reclaim path would never fire, and the test would pass on dumb luck |
| #3 (expired lease reclaimed; zombie's write fenced) | 3 | **Yes** | `@pytest.mark.integration` | Only testing `mark_done`'s fence, not `mark_failed`/`reschedule`'s (the design doc explicitly calls this the fence people forget); or a claim SQL that can't reclaim `leased` rows at all (the original C1 bug) |
| #4 (graceful shutdown releases leases) | 4 | Recommended, but can run hermetically against a stubbed repo if repo functions are unit-testable in isolation | unit or `@pytest.mark.integration` | Asserting `worker.stop()` was CALLED without asserting the DB row's `state` actually flipped back to `pending` |
| #5 (CI guard: kind/status collision + JobKind drift) | 5 | **No** (hermetic) | unit, static-file parsing | A guard that checks `⊇` instead of `==`, silently tolerating a phantom kind with no handler (see Pitfall 7) |

### Proof 1 — Webhook does not block the event loop (Criterion #1)

**Must assert:** two concurrent requests against a route whose downstream dependency is artificially slow complete in wall-clock time ≈ the slow dependency's duration, not 2×.

**Falsifying mutation:** temporarily revert the route to call the blocking dependency directly (no `run_in_threadpool`) — the same test, run against that reverted code, MUST show wall-clock ≈ 2× the slow duration. Document this as the "pasted red run" evidence the design doc's proof discipline calls for.

```python
# tests/test_webhook_unblocked.py (NEW, hermetic — fake_repo, no live DB)
import asyncio
import time
from httpx import ASGITransport, AsyncClient

from app.main import app

SLOW_S = 0.6

async def _slow_parse_inbound(raw_body):
    await asyncio.get_event_loop().run_in_executor(None, time.sleep, SLOW_S)
    # ... build and return a real InboundEmail from raw_body (two DISTINCT fixture
    # payloads across the two concurrent calls -- distinct message_id so neither
    # hits the dedup path, keeping this proof scoped to criterion #1 only) ...

def test_two_concurrent_webhooks_run_in_parallel_not_serially(monkeypatch, fake_repo):
    monkeypatch.setattr("app.email.gateway.parse_inbound", _slow_parse_inbound)
    # (fake_repo already stubs the DB-side of the ingest transaction to be near-instant,
    # so this test isolates the concurrency SHAPE, not DB throughput.)

    async def _fire_two():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            t0 = time.monotonic()
            await asyncio.gather(
                client.post("/webhook/inbound", content=FIXTURE_A_BYTES, headers=HEADERS_A),
                client.post("/webhook/inbound", content=FIXTURE_B_BYTES, headers=HEADERS_B),
            )
            return time.monotonic() - t0

    elapsed = asyncio.run(_fire_two())
    # Generous margin: parallel => ~SLOW_S; serial (the bug) => ~2*SLOW_S.
    assert elapsed < 1.5 * SLOW_S, (
        f"elapsed={elapsed:.2f}s suggests the two requests were serialized, not "
        f"run concurrently off the event loop (expected ~{SLOW_S}s, not ~{2*SLOW_S}s)"
    )
```
Note: `httpx.AsyncClient` + `ASGITransport` drives the REAL app through the REAL event loop via genuine `asyncio.gather` concurrency — this is the correct replacement for `TestClient` when the property under test IS event-loop behavior itself (TestClient's synchronous `.post()` calls block the calling thread and, per this repo's own Phase 10 precedent, funnel concurrent OS threads through one serializing portal).

### Proof 2 — Retrigger survives a worker death and resumes on the next drain (Criterion #2)

**Must assert:** the reclaim path genuinely fired (not just "the run eventually completed by coincidence") — assert `attempts` incremented across the simulated crash, and that a SECOND `drain_once()` call (simulating "a second worker, or a manual drain," per the criterion's own wording) is what completes it, not the first.

**Falsifying mutation:** remove the `OR (state='leased' AND leased_until < now())` clause from the claim SQL (reproduces the exact bug ARCHITECTURE §4 calls "the single most important line in this document") — the job must then NEVER be reclaimed, and the test must go red.

```python
# tests/test_queue_durability.py (NEW), @pytest.mark.integration, real Postgres
@_SKIP_LIVE_DB
def test_retrigger_survives_worker_crash_mid_lease(seeded_db, monkeypatch):
    # 1. Seed a run in ERROR. POST /runs/{id}/retrigger (or call retrigger() directly).
    # 2. Assert a `jobs` row exists: state='pending', kind='run_pipeline',
    #    dedup_key == f"run_pipeline:{run_id}:{epoch_after_clear}".
    # 3. Simulate "a worker claims it, then dies before finishing": call
    #    repo.claim_job() directly (NOT drain_once() -- we want to stop mid-lease,
    #    not run the handler to completion). Assert attempts == 1, state == 'leased'.
    # 4. Simulate lease expiry WITHOUT sleeping (standard technique -- manipulate the
    #    row directly, exercising the exact `leased_until < now()` predicate):
    #      UPDATE jobs SET leased_until = now() - interval '1 second' WHERE id = %s
    # 5. Call drain_once() again (the "second worker, or a manual drain"). Assert:
    #      - the job was reclaimed: attempts == 2
    #      - the handler's D-01 rewind fired (attempts > 1): the run was rewound
    #        EXTRACTING->RECEIVED then re-CAS'd RECEIVED->EXTRACTING (assert via a
    #        stubbed orchestrator.run_pipeline spy, mirroring the existing _MiniStore
    #        pattern in tests/test_threading.py)
    #      - reply_epoch did NOT change again from the rewind (D-02)
    #      - job state == 'done'
    ...
```

### Proof 3 — Expired lease reclaimed by a genuinely different claimant; zombie's write is fenced on BOTH success and failure paths (Criterion #3)

**Must assert:** (a) under real `threading.Barrier`-released concurrency, exactly one of N simultaneous claimants against a single available job wins; (b) a zombie holding a STALE (already-rotated) `lease_token` is rejected by `complete_job` AND `fail_job` — not just `complete_job` (the design doc explicitly names `mark_failed`/`reschedule` as "the fence people forget").

**Falsifying mutation:** remove the `WHERE ... AND lease_token = %(token)s` fencing predicate from `fail_job`'s `UPDATE` (leaving it only on `complete_job`) — a zombie's failure-write must then succeed when it should have been rejected, and the test must go red.

```python
# tests/test_queue_durability.py, @pytest.mark.integration, real Postgres
@_SKIP_LIVE_DB
def test_genuine_claim_race_exactly_one_winner(seeded_db):
    # Enqueue exactly ONE job. Release N (<= 5, matching the app pool's max_size=5
    # budget -- N_INGEST precedent in test_concurrency_proof.py) barrier-held threads,
    # each calling repo.claim_job() directly. Assert exactly 1 non-None result.
    N = 5
    barrier = threading.Barrier(N, timeout=30)
    ...

@_SKIP_LIVE_DB
def test_zombie_fenced_on_both_complete_and_fail_paths(seeded_db):
    # 1. Enqueue + claim a job (token_A).
    # 2. A second claim_job() call after manually expiring the lease rotates the
    #    token (token_B) -- this simulates worker B's legitimate reclaim.
    # 3. Zombie worker A, still holding stale token_A, attempts:
    #      - complete_job(id, token_A)  -> must return False/None (rejected)
    #      - fail_job(id, token_A, ...)  -> must ALSO return False/None (rejected)
    # 4. Assert the job's actual state reflects ONLY worker B's eventual action,
    #    never A's.
    ...
```

### Proof 4 — Graceful shutdown releases held leases immediately (Criterion #4)

**Must assert:** after the shutdown release runs, the job's `state` is back to `pending` with `lease_token`/`leased_until` cleared — immediately, not after `LEASE_SECONDS` elapses.

**Falsifying mutation:** a `worker.stop()` that joins threads but never calls the release SQL — the job must then stay `leased` with a future `leased_until`, and the test must go red.

```python
@_SKIP_LIVE_DB
def test_shutdown_releases_held_lease_immediately(seeded_db):
    job_id, token = enqueue_and_claim_directly()   # no real thread needed --
    # call the release function directly (the same one `worker.stop()` calls),
    # not the full lifespan machinery, for a fast + deterministic proof.
    release_held_leases(held_tokens=[token])
    row = fetch_job(job_id)
    assert row["state"] == "pending"
    assert row["lease_token"] is None
    assert row["leased_until"] is None
```

### Proof 5 — CI guard: `jobs.kind` never collides with `RunStatus`, and `JobKind` never drifts from the CHECK/dispatch table (Criterion #5)

**Must assert:** (a) `set(JobKind) & set(RunStatus) == set()`; (b) `set(JobKind values)` (parsed from the INLINE `CHECK (kind IN (...))` in `CREATE TABLE jobs`, using a NEW parser — NOT `schema_introspect._do_block_check_values`, which only understands the DO-block migration pattern `jobs.kind` doesn't use, see Pitfall 2) equals the Python enum's values; (c) `set(JobKind) == set(dispatch.HANDLERS.keys())` (scoped to `{'run_pipeline'}` in Phase 16, see Pitfall 7).

**Falsifying mutation:** add a `JobKind` member with no corresponding `CHECK` value (or vice versa), or a `JobKind` member with no dispatch handler — each must independently fail its own assertion.

```python
# tests/test_job_kind_drift.py (NEW) -- mirrors tests/test_status_drift.py's shape
def test_job_kind_never_collides_with_run_status():
    from app.models.job import JobKind
    from app.models.status import RunStatus
    assert not ({m.value for m in JobKind} & {m.value for m in RunStatus})

def test_job_kind_check_matches_python_enum():
    # Parse the inline `CHECK (kind IN (...))` from CREATE TABLE jobs (...) in
    # schema.sql -- a fresh regex against the CREATE-body, NOT
    # schema_introspect._do_block_check_values (wrong pattern -- no DO-block exists
    # for a brand-new table's inline CHECK).
    ...

def test_job_kind_equals_dispatch_table():
    from app.models.job import JobKind
    from app.queue.dispatch import HANDLERS
    assert {m.value for m in JobKind} == set(HANDLERS.keys())
```

### Sampling Rate
- **Per task commit:** `uv run pytest -q` (hermetic — covers Proofs 1, 5, and any unit tests for `enqueue_job`/`claim_job` SQL shape via the existing `FakeConnection` offline-SQL-assertion pattern this repo already uses elsewhere)
- **Per wave merge:** the full live-DB run (Proofs 2, 3, 4) — `DATABASE_URL=... ALLOW_DB_RESET=1 uv run pytest tests/ -m integration -v`
- **Phase gate:** both green before `/gsd-verify-work`; `.github/workflows/concurrency-proof.yml` generalized per D-04 BEFORE any of the new integration test files are written, so they're picked up automatically rather than needing a second commit to the workflow file

### Wave 0 Gaps
- [ ] `tests/test_webhook_unblocked.py` — Proof 1, covers QUEUE-01
- [ ] `tests/test_queue_durability.py` — Proofs 2, 3, 4, covers QUEUE-02/QUEUE-03, `@pytest.mark.integration`
- [ ] `tests/test_job_kind_drift.py` — Proof 5, covers QUEUE-05
- [ ] `tests/test_status_drift.py` — D-05 rewrite (see § Jobs Index Set & D-05 Rewrite)
- [ ] `.github/workflows/concurrency-proof.yml` — D-04 generalization (`pytest tests/ -m integration` collection instead of the hard-coded 2-file list), landed BEFORE the new integration files so they're covered from their first commit
- [ ] `tests/conftest.py` `fake_repo` tuple (lines 994-1052) — add every new `app/db/repo/jobs.py` function name (this one is unconditionally required: `fake_repo` backs every `client`-fixture test, and several existing webhook/threading tests will exercise `retrigger()`'s new enqueue call once it lands)
- [ ] `tests/test_threading.py` — see the correction in Pitfall 8 below: the two tuples at lines 340-354 and 423-436 back `resume_pipeline`-only tests (not `retrigger`) and, as verified this session, need NO change for Phase 16 as scoped. Still worth a final grep pass once `retrigger()`'s refactor lands, in case new retrigger-specific tests get added to this file (it already hosts reply/resume/threading tests, a plausible home for them) and reuse one of these `_MiniStore` tuples

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | No | This phase touches no auth surface (retrigger is an existing unauthenticated-operator route; no change to that posture here) |
| V3 Session Management | No | N/A |
| V4 Access Control | No (unchanged) | Retrigger's access control posture is unchanged by this phase — pre-existing known/accepted gap (operator auth is explicitly out of scope per the v4 milestone's own "Out of Scope" table) |
| V5 Input Validation | Yes | `jobs.kind`/`jobs.state` are DB-level `CHECK`-constrained TEXT (never free-form); `dedup_key` is a server-constructed string (`f"run_pipeline:{run_id}:{epoch}"`), never user input, so no injection surface there. All new SQL uses `%s` placeholders per this package's absolute "never f-string SQL" rule (`app/db/repo/_shared.py`'s own module docstring) |
| V6 Cryptography | Yes (reused, not new) | `gen_random_uuid()` (pgcrypto) for `jobs.id` and `jobs.lease_token` — cryptographically-random UUIDs, already the PK-default pattern on 6 existing tables |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---|---|---|
| A zombie worker's stale write silently overwriting a legitimate worker's result | Tampering | Lease-token fencing on EVERY write path (`complete_job` AND `fail_job` — see Pitfall/Proof 3) |
| A crash loop burning unbounded resources | Denial of Service (self-inflicted) | `attempts` incremented AT CLAIM (not at failure) bounds a poison job even if it kills its worker before reporting anything; `MAX_ATTEMPTS` → `dead` state |
| Advisory-lock/LISTEN-NOTIFY silent-failure under connection pooling | Tampering (silent correctness loss, not an attacker) | Row leases + CAS only, never session-level primitives, per `app/db/supabase.py`'s own documented Supavisor transaction-mode rationale |
| SQL injection via job payload | Tampering | Not applicable — this phase's `jobs` rows carry only server-generated identifiers (`run_id`, `dedup_key` built from a UUID + int), never externally-supplied free text |

## Sources

### Primary (HIGH confidence — read directly this session)
- `app/routes/webhook.py` (full file) — the current `inbound()` control flow, confirms QUEUE-01's exact blocking surface and the response-shaping branches' additional I/O (Pitfall 3)
- `app/routes/runs.py` (full file) — `retrigger()`, `resolve()`, `runs_list()`'s sweep block, `STALE_THRESHOLD`'s derivation comment (source for `LEASE_SECONDS`'s recommended value)
- `app/routes/pipeline_glue.py` (full file) — `resume_pipeline_bg`/`run_pipeline_bg`/`operator_resume_bg`, `reply_sender_ok`, `finish_reply_resume`
- `app/db/supabase.py` (full file) — pool `max_size=5`, `prepare_threshold=None` rationale
- `app/db/repo/_shared.py` (full file) — `_conn_ctx`/`_nulltx` convention every new `jobs.py` function must follow
- `app/db/repo/runs.py` (full file) — `claim_status`, `sweep_stranded_runs`, `_STRANDED_SCOPE_STATUSES`, `record_run_error`
- `app/db/repo/pipeline_state.py::clear_reply_context` (lines 346-385) — confirmed current `None` return, confirmed actual file location (Pitfall 5)
- `app/db/repo/__init__.py` (full file) — the facade re-export surface
- `app/main.py` (full file) — confirmed 16 lines, no `lifespan`
- `app/models/status.py` (full file) — `RunStatus`, 11 members
- `app/db/schema.sql` (full file) — confirmed 3 existing `CREATE INDEX IF NOT EXISTS`, 2 `ANY (c.conkey)` DO-blocks
- `app/db/bootstrap.py` (full file) — `_DROP_ORDER` list, confirmed `jobs` absent (Pitfall 4)
- `app/routes/health.py` + `app/db/schema_introspect.py` (full files) — confirmed `/health/schema` hardcodes exactly 2 tables (Pitfall 2)
- `app/pipeline/orchestrator.py` (lines 195-260) — confirmed exact line 232 (`repo.set_status(run_id, RunStatus.EXTRACTING)`, unconditional) and the still-BackgroundTasks-driven plain webhook path (Pitfall 6)
- `tests/conftest.py` (lines 960-1069) — confirmed `fake_repo` monkeypatch tuple at lines 994-1052 (exact match to CONTEXT.md's citation)
- `tests/test_threading.py` (lines 320-450) — confirmed both monkeypatch tuples via `grep -n "for name in ("` → lines 340 and 423
- `tests/test_status_drift.py` (lines 200-235, plus a full grep pass) — confirmed the two magic-number assertions at lines 228 and 329
- `tests/test_concurrency_proof.py` (lines 1-140) — the `threading.Barrier`/`N_INGEST=5`/direct-repo-seam pattern this phase's Proofs 2/3 must follow
- `.github/workflows/concurrency-proof.yml` (full file) — confirmed the hard-coded 2-file test list at line 89 and the skip-guard
- `tests/test_bound01_private_imports.py` (full file) — confirmed `SCAN_ROOTS = ["app", "eval", "scripts"]`, so `app/queue/` is auto-scanned by BOUND-01
- `app/config.py` (full file) — the `pydantic-settings` pattern new `WORKER_COUNT`/`LEASE_SECONDS`/`MAX_ATTEMPTS` fields must follow
- `pyproject.toml` (full file) — confirmed zero new deps needed; confirmed `mypy strict = true` scope includes `app` (new `app/queue/`, `app/models/job.py`, `app/db/repo/jobs.py` must be strict-clean); confirmed `ruff` select set
- `.github/workflows/ci.yml` + `render.yaml` — confirmed the 3-job CI shape (lint/test/typecheck) and that `render.yaml` currently has no `WORKER_COUNT`/queue-related env vars (a deploy-config gap outside this phase's stated scope, flagged for awareness only)
- `starlette/concurrency.py:32` (installed package, `starlette==1.3.1` transitive via `fastapi==0.138.0`) — confirmed `run_in_threadpool`'s exact signature and implementation (`anyio.to_thread.run_sync`)

### Canonical design (already adversarially validated — treated as authoritative, not re-verified)
- `docs/superpowers/specs/2026-07-13-durable-execution-design.md` — the approved, corrected v4 design
- `.planning/research/ARCHITECTURE.md` (full file, both halves read this session) — §3 (dedup_key + enqueue SQL), §4 (claim/lease/fencing protocol + DDL), §5 (worker lifecycle), §6 (ingest re-keying), §7 (build order), §8 (open questions), plus the full NEW/MODIFIED integration-points inventory
- `.planning/research/SUMMARY.md` (full file) — the 4-researcher adversarial validation, C1-C10 corrections
- `.planning/phases/16-queue-substrate-unblocked-webhook/16-CONTEXT.md` — the locked D-01 through D-10 decisions this document's User Constraints section copies verbatim
- `.planning/REQUIREMENTS.md` — QUEUE-01/02/03/05 verbatim, the PROOF section's vacuous-twin discipline, the Accepted Residual Risk statement

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new deps, every primitive verified either by direct source read (starlette) or already-pinned `pyproject.toml`
- Architecture (claim SQL, DDL, enqueue pattern): HIGH — verbatim from the already 4-researcher-validated canonical design; independently confirmed against live source for every integration point cited
- Validation architecture: HIGH on the proof SHAPES (directly modeled on this repo's own proven `test_concurrency_proof.py` pattern, read directly); MEDIUM on exact assertion thresholds (e.g. `SLOW_S`, timing margins) — these are implementation-time tuning, not architectural risk
- Discretionary numbers (LEASE_SECONDS/poll interval/MAX_ATTEMPTS): MEDIUM — derived from a real, already-documented worst-case analysis (`STALE_THRESHOLD`), but the exact final values are a planning-time choice, not a verified fact
- Pitfalls 2, 4, 5, 6, 7: HIGH — each is a direct source-code contradiction/gap found by tracing argument flow against live files this session, not inferred from the canonical docs' prose

**Research date:** 2026-07-14
**Valid until:** ~14 days (fast-moving — this phase is the first of 6 sequential v4 phases actively under construction; source line numbers cited here will drift as soon as Phase 16 itself starts landing code)
