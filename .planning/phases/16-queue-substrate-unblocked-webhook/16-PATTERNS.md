# Phase 16: Queue Substrate & Unblocked Webhook - Pattern Map

**Mapped:** 2026-07-14
**Files analyzed:** 15 (new + modified)
**Analogs found:** 15 / 15

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `app/models/job.py` (NEW) | model / enum | CRUD (state vocabulary) | `app/models/status.py` (`RunStatus`) | exact |
| `app/db/repo/jobs.py` (NEW) | repo (data-access module) | CRUD + claim/lease (queue transport) | `app/db/repo/runs.py` (`claim_status`, `sweep_stranded_runs`) | exact (CAS idiom); `app/db/repo/_shared.py` for the `conn=` convention |
| `app/queue/worker.py` (NEW) | service (daemon loop) | event-driven / polling | no direct analog — closest structural cousin is `tests/test_concurrency_proof.py`'s barrier-released `threading.Thread` pattern (test code, not app code) | no analog |
| `app/queue/dispatch.py` (NEW) | service (dispatch table) | request-response (kind → handler) | `app/routes/pipeline_glue.py` (module-object import discipline, BOUND-01) | role-match |
| `app/queue/handlers/pipeline.py` (NEW) | service (job handler) | request-response | `app/routes/pipeline_glue.py::run_pipeline_bg` / `app/routes/runs.py::retrigger` (CAS + rewind logic) | role-match |
| `app/main.py` (MODIFIED — adds `lifespan`) | config / app assembly | event-driven (startup/shutdown) | none in this repo (first `lifespan` ever) — use FastAPI's own `lifespan=` contextmanager convention | no analog (documented) |
| `app/db/schema.sql` (MODIFIED — `jobs` table) | migration / DDL | CRUD | `payroll_runs` table block (`schema.sql:69-148`) — CHECK-constrained TEXT status column + partial indexes | exact |
| `app/db/bootstrap.py` (MODIFIED — `_DROP_ORDER`) | config | batch | `_DROP_ORDER` list itself (`bootstrap.py:73-81`) | exact (self-analog, additive edit) |
| `app/routes/webhook.py` (MODIFIED — `run_in_threadpool`) | route/controller | request-response | itself — `webhook.py:56-220` (the ingest transaction to wrap) | exact (self-analog, additive edit) |
| `app/routes/runs.py::retrigger` (MODIFIED) | route/controller | request-response (CAS + enqueue) | itself — `runs.py:266-381` (existing multi-transaction retrigger) + `app/routes/runs.py::approve` (single caller-owned CAS pattern, `runs.py:84-` ) | exact (self-analog, refactor) |
| `app/db/repo/pipeline_state.py::clear_reply_context` (MODIFIED — add `RETURNING`) | repo function | CRUD | itself, plus `app/db/repo/runs.py::create_run` (the `RETURNING id` + `.fetchone()` idiom) | exact |
| `app/db/repo/__init__.py` (MODIFIED — facade re-export) | facade | — | itself (existing re-export block structure) | exact |
| `tests/test_webhook_unblocked.py` (NEW) | test | request-response (concurrency, hermetic) | none exact — modeled on `httpx.AsyncClient`+`ASGITransport` pattern described in RESEARCH.md; no prior test in repo uses this transport | no analog (research-specified pattern) |
| `tests/test_queue_durability.py` (NEW) | test | event-driven / concurrency (live DB) | `tests/test_concurrency_proof.py` (`threading.Barrier` + direct repo-seam pattern) | exact |
| `tests/test_job_kind_drift.py` (NEW) | test | static/CI-guard | `tests/test_status_drift.py` (`RunStatus` ↔ SQL CHECK drift test) | exact |
| `tests/test_status_drift.py` (MODIFIED — D-05 rewrite) | test | static/CI-guard | itself | exact (self-analog) |
| `tests/conftest.py` (MODIFIED — `fake_repo` tuple) | test fixture | CRUD (in-memory double) | itself, `fake_repo` tuple at `:994-1052` | exact (self-analog, additive) |
| `.github/workflows/concurrency-proof.yml` (MODIFIED — D-04) | CI config | batch | itself, line 89 hard-coded file list | exact (self-analog) |

## Pattern Assignments

### `app/models/job.py` (model, CRUD vocabulary)

**Analog:** `app/models/status.py`

**Full pattern to copy** (`app/models/status.py:1-41`):
```python
"""RunStatus — the single source of truth for every pipeline status value.
...
"""
import enum


class RunStatus(enum.StrEnum):
    """The lifecycle states a payroll run can occupy.

    This Python class is CANONICAL; the SQL mirrors it. In Postgres the column is
    modeled as TEXT + CHECK rather than a native ENUM ...
    """

    RECEIVED = "received"
    ...
```

**How to apply to `JobKind`/`JobState`:**
- Same `enum.StrEnum` shape, same "Python is canonical, SQL CHECK mirrors it" docstring convention.
- `JobKind` is scoped to exactly `{"run_pipeline"}` this phase (Pitfall 7 — do NOT pre-declare `ingest`/`resume_reply`/`operator_resume`).
- `JobState` members: `pending`, `leased`, `done`, `dead` (from the canonical claim/complete/fail SQL in RESEARCH.md § Code Examples).
- Add a module docstring cross-referencing the CI drift test (`tests/test_job_kind_drift.py`), mirroring `status.py`'s own reference to its drift test.
- **Collision guard (success criterion #5):** the new drift test must assert `set(JobKind) & set(RunStatus) == set()` — copy the enum member style but never reuse a value string already used by `RunStatus` (e.g. do not name a `JobState` member `"error"` — `RunStatus.ERROR` already owns that string and QUEUE-05 requires zero collision).

---

### `app/db/repo/jobs.py` (repo module, CRUD + claim/lease)

**Analog:** `app/db/repo/runs.py` (`claim_status`, `sweep_stranded_runs`) + `app/db/repo/_shared.py` (`_conn_ctx`/`_nulltx`)

**Imports pattern** (`app/db/repo/runs.py:1-16`):
```python
"""DB repo — run lifecycle, status CAS, sweep, and error/scrub helpers."""
from __future__ import annotations

import logging
import uuid
from typing import Any

import psycopg
import psycopg.rows

from app.db.repo._shared import _conn_ctx, _nulltx
from app.models.status import RunStatus
```
For `jobs.py`, import `from app.models.job import JobKind, JobState` instead of `RunStatus`.

**Caller-owns-transaction convention — MANDATORY** (`app/db/repo/_shared.py:19-48`, full file, already read):
```python
@contextlib.contextmanager
def _conn_ctx(
    conn: psycopg.Connection | None,
) -> Iterator[tuple[psycopg.Connection, bool]]:
    if conn is not None:
        yield conn, False
    else:
        import app.db.repo as _repo_pkg
        with _repo_pkg.get_connection() as owned:
            yield owned, True


@contextlib.contextmanager
def _nulltx() -> Iterator[None]:
    """No-op CM: when a caller passes their own conn, they own the transaction."""
    yield
```
Every new function in `jobs.py` — `enqueue_job`, `claim_job`, `complete_job`, `fail_job`, `release_lease` — MUST take `conn: psycopg.Connection | None = None` and open with:
```python
with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
    ...
```
This is the single most load-bearing pattern in this phase (per RESEARCH.md) — it is what lets `enqueue_job(..., conn=conn)` drop into `retrigger`'s existing transaction with zero new plumbing.

**CAS / atomic single-statement UPDATE idiom to copy** (`app/db/repo/runs.py:356-381`, `claim_status`):
```python
def claim_status(
    run_id: uuid.UUID,
    expected: RunStatus,
    new: RunStatus,
    conn: psycopg.Connection | None = None,
) -> bool:
    """Atomic compare-and-swap ... `WHERE id = %s AND status = %s RETURNING id` in
    a single statement is what makes this safe ...
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute(
            "UPDATE payroll_runs SET status = %s, updated_at = now() "
            "WHERE id = %s AND status = %s RETURNING id",
            (RunStatus(new).value, str(run_id), RunStatus(expected).value),
        ).fetchone()
    return row is not None
```
`claim_job` follows the same "one UPDATE, `RETURNING`, `.fetchone()` or `.fetchall()`, no SELECT-then-UPDATE" shape — but use the exact SQL already specified verbatim in RESEARCH.md § Code Examples (the `FOR UPDATE SKIP LOCKED` subquery form with the reclaim-expired-lease `OR` clause — this SQL is pre-corrected, transcribe verbatim, do not re-derive).

**`RETURNING`-based INSERT pattern to copy for `enqueue_job`** (`app/db/repo/runs.py:239-258`, `create_run`):
```python
def create_run(
    *,
    business_id: uuid.UUID,
    source_email_id: uuid.UUID | None,
    ...
    conn: psycopg.Connection | None = None,
) -> uuid.UUID:
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute(
            """
                INSERT INTO payroll_runs (...)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
            (...),
        ).fetchone()
    if row is None:
        raise RuntimeError("create_run did not return a new run id")
    return uuid.UUID(str(row[0]))
```
`enqueue_job` mirrors this but with `ON CONFLICT (dedup_key) DO NOTHING` (dedup pattern already proven at `insert_inbound_email`, `runs.py:83-106`, `ON CONFLICT (message_id) DO NOTHING ... RETURNING id`) — a `None` return means "already enqueued," not an error; do not raise.

**SQL discipline** (module docstring, `_shared.py:4-9`): every value through `%s`/named placeholders, never f-strings — same rule this module already enforces project-wide.

---

### `app/queue/dispatch.py` (dispatch table)

**Analog:** `app/routes/pipeline_glue.py:1-8` (BOUND-01 module-object import discipline)

**Pattern to copy verbatim (the discipline, not the code):**
```python
"""HTTP-to-orchestrator bridge helpers (BOUND-01).

Every router imports these via a module-object import
(`from app.routes import pipeline_glue`), NEVER a bare-name import. A bare-name
import would bind the function object at import time, and the tests'
`monkeypatch.setattr(pipeline_glue, <fn>)` seams would silently stop taking
effect — the router would keep calling the real orchestrator.
"""
```
**Apply to `app/queue/dispatch.py`:** the `HANDLERS` dict must be built so that a test can `monkeypatch.setattr(dispatch, "HANDLERS", {...})` or `monkeypatch.setattr(handlers.pipeline, "handle_run_pipeline", stub)` — resolve handler functions via **module-object attribute lookup at dispatch time**, not by binding a bare name into a dict at import time that a monkeypatch can't reach. `tests/test_bound01_private_imports.py` (`SCAN_ROOTS = ["app", "eval", "scripts"]`) auto-scans `app/queue/`, so no cross-module `_private` reference is permitted anywhere in the new package — keep every cross-module reference to public names.

**Scoping (Pitfall 7):** `HANDLERS = {JobKind.RUN_PIPELINE: handle_run_pipeline}` — exactly one entry in Phase 16. The CI guard `set(JobKind) == set(HANDLERS.keys())` must be satisfiable, not `⊇`.

---

### `app/queue/worker.py` (daemon loop, D-09 wake, D-07 pool budget)

**No direct in-app analog exists** (confirmed — `app/main.py` has never had a `lifespan`, and no daemon-thread worker loop exists anywhere in `app/`). The closest STRUCTURAL cousin is test code, not production code:

**Barrier/thread pattern to draw the claim-loop shape from** (`tests/test_concurrency_proof.py:204-208`, thread start/join idiom):
```python
threads = [threading.Thread(target=_ingest) for _ in range(N_INGEST)]
for t in threads:
    t.start()
for t in threads:
    t.join()
```
Adapt for daemon workers: `threading.Thread(target=_claim_loop, daemon=True)` × `WORKER_COUNT`, each running its own `while not _stop_event.is_set(): drain_once(); _wake_event.wait(timeout=POLL_INTERVAL_S)` loop — NOT a `ThreadPoolExecutor` (see RESEARCH.md § Don't Hand-Roll).

**Pool-budget assertion pattern (D-07)** — source the `max_size=5` value from `app/db/supabase.py:60` (read this session per RESEARCH.md citation; not independently re-read here since RESEARCH.md already confirms the exact line and value) — assert `WORKER_COUNT + 2 <= 5` at `lifespan` startup, raise/refuse to start on violation (fail-fast, not clamp-and-warn — this repo's `Settings.database_url` in `app/config.py:27` sets the "no default, fail fast" precedent to imitate: `database_url: str  # no default — fails fast if unset`).

**FastAPI `lifespan` itself:** no repo analog. Use FastAPI's own `@contextlib.asynccontextmanager` `lifespan(app: FastAPI)` convention (external framework pattern, not project-specific) — start workers before `yield`, call `worker.stop()` (release-all-held-leases, per the SHUTDOWN RELEASE SQL in RESEARCH.md § Code Examples) after `yield`.

---

### `app/main.py` (MODIFIED — first `lifespan`)

**Analog:** itself, current 16-line file (`app/main.py:1-17`, full file, already read):
```python
"""FastAPI entrypoint — thin app assembly only. Routes live in app/routes/*."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import dashboard, demo, health, runs, webhook

app = FastAPI(title="Payroll Agent")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(health.router)
app.include_router(webhook.router)
app.include_router(runs.router)
app.include_router(dashboard.router)
app.include_router(demo.router)
```
**Keep it thin.** Add `lifespan=lifespan` to the `FastAPI(...)` constructor call, with `lifespan` imported from `app.queue.worker` (or a small `app/queue/lifespan.py`) — do not inline the worker start/stop logic into `main.py` itself; this file's own docstring ("thin app assembly only") is the constraint to honor.

---

### `app/db/schema.sql` (MODIFIED — `jobs` table + index + CHECKs)

**Analog:** `payroll_runs` table block (`schema.sql:69-148`, partially read via grep — CHECK-constrained TEXT status column at line ~148 area, `CREATE INDEX IF NOT EXISTS idx_payroll_runs_status` at line 148, `CREATE INDEX IF NOT EXISTS idx_payroll_runs_created_at` at line 146).

**Index pattern to copy** (confirmed via grep, `schema.sql:146,148`):
```sql
CREATE INDEX IF NOT EXISTS idx_payroll_runs_created_at ...
CREATE INDEX IF NOT EXISTS idx_payroll_runs_status ...
```
New index for `jobs`: `CREATE INDEX IF NOT EXISTS idx_jobs_claimable ON jobs (priority, available_at) WHERE state IN ('pending','leased');` — a **partial index** exactly matching the claim query's `WHERE` predicate (RESEARCH.md § Jobs Index Set — verbatim recommendation, no additions).

**DO-block CHECK-migration pattern exists but is explicitly NOT used for `jobs`** (`schema.sql` lines ~177, ~315, the two `ANY (c.conkey)` occurrences for `payroll_runs.status` / `email_messages.purpose`) — `jobs.kind`/`jobs.state` use a plain **inline** `CHECK (kind IN (...))` / `CHECK (state IN (...))` inside `CREATE TABLE jobs (...)` since the table has no live rows to migrate on first deploy (RESEARCH.md § Jobs Index Set & D-05 Rewrite — do not add a third DO-block).

**`CREATE TABLE IF NOT EXISTS` + `gen_random_uuid()` PK default pattern** (`schema.sql:16-17`, `businesses`):
```sql
CREATE TABLE IF NOT EXISTS businesses (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    ...
```
`jobs.id` and `jobs.lease_token` both use `gen_random_uuid()` — zero new extension surface (pgcrypto already `CREATE EXTENSION IF NOT EXISTS` at `schema.sql:13`).

**The exact `jobs` DDL + claim/complete/fail/shutdown-release SQL is NOT re-derived here** — it is specified verbatim in `.planning/research/ARCHITECTURE.md` §3–§4 and copied into `16-RESEARCH.md` § Code Examples (already adversarially validated, C1-fix baked in). Transcribe from there, not from this pattern map.

---

### `app/db/bootstrap.py` (MODIFIED — `_DROP_ORDER`)

**Analog:** itself, current list (`app/db/bootstrap.py:73-81`, full block already read):
```python
_DROP_ORDER = [
    "name_matches",
    "paystub_line_items",
    "eval_results",
    "email_messages",
    "payroll_runs",
    "employees",
    "businesses",
]
```
**Apply:** add `"jobs"` before `"payroll_runs"` (its FK target), per Pitfall 4. Every `DROP TABLE IF EXISTS ... CASCADE` already uses `CASCADE` so exact ordering is defensive-not-strictly-required — but match the file's own stated convention ("explicit reverse order documents the dependency direction").

---

### `app/routes/webhook.py` (MODIFIED — `run_in_threadpool`)

**Analog:** itself — the exact control flow to wrap (`app/routes/webhook.py:56-220`, full ingest section already read).

**Current structure (the seam to wrap):**
```python
@router.post("/webhook/inbound")
async def inbound(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    raw_body: bytes = await request.body()          # STAYS on the loop (HMAC needs raw bytes)
    settings = get_settings()
    ...
    # signature verification — STAYS on the loop (pure CPU)
    ...
    email = gateway.parse_inbound(raw_body)          # BLOCKING — Resend HTTP fetch, moves off-loop
    ...
    with repo.get_connection() as conn, conn.transaction():   # BLOCKING psycopg, moves off-loop
        ... 5-outcome ingest transaction ...
    # response-shaping — see Pitfall 3 (additional blocking DB reads in the
    # 'duplicate' branch at webhook.py:224-270, also blocking, decide explicitly
    # whether to fold into the same run_in_threadpool call)
```
**Copy the exact import + call shape from RESEARCH.md § Code Examples** (verified against the installed package):
```python
from starlette.concurrency import run_in_threadpool

result = await run_in_threadpool(_parse_and_ingest_sync, raw_body)
```
Extract `gateway.parse_inbound(raw_body)` through the `with repo.get_connection() as conn, conn.transaction(): ...` block into one sync helper `_parse_and_ingest_sync(raw_body) -> <result>`, called via `run_in_threadpool`. The docstring at `webhook.py:112-130` ("the transaction commits BEFORE `add_task`") needs rewriting to describe the new `run_in_threadpool` boundary.

---

### `app/routes/runs.py::retrigger` (MODIFIED — one caller-owned transaction)

**Analog:** itself, current implementation (`app/routes/runs.py:266-381`, full function already read) — the CAS pattern to consolidate is proven at `claim_status` (see `jobs.py` section above).

**Current (broken) shape — THREE separate, uncoordinated transactions:**
```python
claimed = repo.claim_status(run_id, RunStatus.ERROR, RunStatus.RECEIVED) or repo.claim_status(
    run_id, RunStatus.APPROVED, RunStatus.RECEIVED
)
if not claimed:
    run = repo.load_run(run_id)               # separate transaction
    ...
    claimed = repo.claim_status(run_id, RunStatus(run["status"]), target)  # separate transaction

if claimed:
    repo.clear_reply_context(run_id)           # separate transaction, conn=None
    background_tasks.add_task(pipeline_glue.run_pipeline_bg, run_id)
```
**Target shape — copy verbatim from RESEARCH.md § Architecture Patterns → Pattern 2** (already adversarially specified against this exact live code):
```python
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
`_claim_stale_in_flight` is a NEW conn-aware helper extracted from the current inline `load_run` + `STALE_THRESHOLD` check + `claim_status` logic at `runs.py:318-366` — same stale-status set (`RECEIVED, EXTRACTING, COMPUTED, SENT` — the deliberately-divergent-from-the-sweep scope, `runs.py:327-337` comment) and same target-must-differ-from-current rule (`runs.py:345-356`), just threaded through `conn=conn` instead of opening its own.

**D-09 wake — must fire strictly after commit, never inside** `with repo.get_connection() as conn, conn.transaction(): ...` block — call `worker_wake_event.set()` as the very next statement after the `with` block exits, following this file's own established convention of keeping response-shaping/side-effects strictly outside the transaction body (see `webhook.py`'s "Transaction committed. Everything below is post-commit" comment at `webhook.py:221-222` for the same discipline applied elsewhere in this codebase).

---

### `app/db/repo/pipeline_state.py::clear_reply_context` (MODIFIED — add `RETURNING reply_epoch`)

**Analog:** itself, current implementation (`app/db/repo/pipeline_state.py:346-385`, full function already read) — the `RETURNING` + `.fetchone()` pattern to copy is `app/db/repo/runs.py::create_run` (`runs.py:239-258`, already excerpted above).

**Current (returns `None` implicitly):**
```python
def clear_reply_context(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> None:
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE payroll_runs SET clarified_fields = NULL, pre_clarify_extracted = NULL,"
            " clarification_round = 0, alias_candidates = NULL, hours_changes = NULL,"
            " reply_epoch = reply_epoch + 1, updated_at = now()"
            " WHERE id = %s",
            (str(run_id),),
        )
```
**Target — add `RETURNING reply_epoch`, `.fetchone()`, return the int:**
```python
def clear_reply_context(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> int:
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute(
            "UPDATE payroll_runs SET clarified_fields = NULL, pre_clarify_extracted = NULL,"
            " clarification_round = 0, alias_candidates = NULL, hours_changes = NULL,"
            " reply_epoch = reply_epoch + 1, updated_at = now()"
            " WHERE id = %s"
            " RETURNING reply_epoch",
            (str(run_id),),
        ).fetchone()
    if row is None:
        raise RuntimeError("clear_reply_context: run not found")
    return int(row[0])
```
**Also update the call site** at `app/routes/runs.py:378` (`repo.clear_reply_context(run_id)` → `epoch = repo.clear_reply_context(run_id, conn=conn)`) and the docstring's claim about "opens its own committed transaction (conn=None)" — no longer true once `retrigger` threads its own `conn`.

**D-02 constraint — a SEPARATE, NEW rewind path must NOT call this function** (or must call it with a `bump_epoch=False` flag) — the automatic reclaim handler in `app/queue/handlers/pipeline.py` needs the SAME field-clearing behavior (`clarified_fields`, `pre_clarify_extracted`, `clarification_round`, `alias_candidates`, `hours_changes`) but WITHOUT the `reply_epoch = reply_epoch + 1` line. Either add a `bump_epoch: bool = True` parameter to `clear_reply_context` itself (branching the SQL string), or write a sibling function in `pipeline_state.py` that shares the field list as a constant but omits the epoch bump — do not silently reuse `clear_reply_context` unmodified from the handler.

---

### `app/db/repo/__init__.py` (MODIFIED — facade re-export)

**Analog:** itself, current re-export block for `runs.py` (`app/db/repo/__init__.py:62-80` and `__all__` at `:130-141`, full file already read):
```python
from app.db.repo.runs import (
    _ACCENT_CLASS_MAP,
    _TERMINAL_STATUSES,
    RUN_COLS,
    _scrub,
    claim_status,
    create_run,
    ...
)
```
**Apply:** add a new import block `from app.db.repo.jobs import (enqueue_job, claim_job, complete_job, fail_job, release_lease, ...)` in the same alphabetized/grouped style as the existing `pipeline_state`/`emails`/`runs` blocks, and append every new name to `__all__`. Read the facade's own module docstring caveat (`__init__.py:8-14`) before wiring: `monkeypatch.setattr(repo, "fn", ...)` only intercepts the FACADE's own name — internal cross-module calls inside `jobs.py` itself would need `app.db.repo.jobs` patched directly, mirroring the `record_run_error`/`set_status` caveat already documented there.

---

### `tests/test_queue_durability.py` (NEW, live-DB proofs)

**Analog:** `tests/test_concurrency_proof.py` (full file, already read) — this is the single most important existing analog for the concurrency proofs per the phase brief.

**Barrier-released direct-repo-seam pattern to copy verbatim in shape** (`tests/test_concurrency_proof.py:166-252`, Surface A):
```python
@_SKIP_LIVE_DB
@pytest.mark.integration
def test_dedup_exactly_one_run_per_message_id(seeded_db, monkeypatch):
    from app.db import repo
    _pipeline_calls, _deliver_calls = _stub_pipeline_and_send(monkeypatch)

    barrier = threading.Barrier(N_INGEST, timeout=30)
    results: list[...] = []
    lock = threading.Lock()

    def _ingest() -> None:
        barrier.wait()  # release all threads at the same instant
        ... call repo.* functions DIRECTLY, never through an HTTP route ...
        with lock:
            results.append(...)

    threads = [threading.Thread(target=_ingest) for _ in range(N_INGEST)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == N_INGEST
    # then assert the winner/loser split EXPLICITLY, not via set-dedup that could
    # mask a broken loser path
```
**Why this is the correct pattern, not `TestClient`** — copy the module's own rationale verbatim into the new test file's docstring (`tests/test_concurrency_proof.py:27-39`):
> `/webhook/inbound` is `async def`, and its only `await` is `await request.body()` ... a shared TestClient funnels every thread through one ASGI portal — so N threads POSTing to that route execute strictly ONE AT A TIME ... Driving the sync repo seam directly under a Barrier is what makes the contention real.

**N_INGEST=5 pool-budget rationale to copy and adapt** (`tests/test_concurrency_proof.py:77-85`):
```
# The app pool is min_size=1 / max_size=5 / timeout=5s (app/db/supabase.py),
# so N_INGEST MUST stay <= 5 ...
```
Apply the same `<= 5` (or `<= max_size - held-by-other-tests` if workers are also live) ceiling to Proof 3's `N` claimants.

**Lease-expiry-without-sleeping technique** (RESEARCH.md § Proof 2, step 4) — manipulate the row directly (`UPDATE jobs SET leased_until = now() - interval '1 second' WHERE id = %s`) rather than sleeping — this mirrors `test_concurrency_proof.py`'s own "no sleeps, deterministic" discipline (implicit throughout that file — no `time.sleep` anywhere in it).

**`_stub_pipeline_and_send`-style monkeypatch-everything-live helper** (`tests/test_concurrency_proof.py:93-138`) — reuse or closely mirror this pattern for Proof 2's orchestrator-spy assertion (RESEARCH.md's own note: "assert via a stubbed `orchestrator.run_pipeline` spy, mirroring the existing `_MiniStore` pattern in `tests/test_threading.py`").

---

### `tests/test_webhook_unblocked.py` (NEW, hermetic, Proof 1)

**No exact analog in the existing suite** (this repo has never used `httpx.AsyncClient`+`ASGITransport`+`asyncio.gather` — confirmed by the RESEARCH.md sourcing list, which cites `starlette/concurrency.py` from the installed package, not from repo test code). Copy the exact pattern already fully specified in `16-RESEARCH.md:496-533` (§ Proof 1) verbatim — it is pre-written and adversarially reasoned, not to be re-derived. Falsifying-mutation discipline (revert to no-`run_in_threadpool`, assert the SAME test goes red at ~2× wall-clock) must be documented as "pasted red run" evidence per this repo's PROOF-05 convention, mirroring `test_concurrency_proof.py`'s own evidentiary framing.

---

### `tests/test_job_kind_drift.py` (NEW, Proof 5)

**Analog:** `tests/test_status_drift.py` (cited but not independently re-read here beyond the two magic-number lines already located via grep in RESEARCH.md — lines 228, 329). Mirror its "Python enum is canonical, SQL CHECK is asserted to match it exactly" shape:
```python
def test_job_kind_never_collides_with_run_status():
    from app.models.job import JobKind
    from app.models.status import RunStatus
    assert not ({m.value for m in JobKind} & {m.value for m in RunStatus})

def test_job_kind_check_matches_python_enum():
    # Parse the INLINE CHECK (kind IN (...)) from CREATE TABLE jobs (...) --
    # a fresh regex against the CREATE-body via schema_introspect._create_body
    # (already generic, parenthesis-balanced), NOT
    # schema_introspect._do_block_check_values (wrong pattern for jobs.kind).
    ...

def test_job_kind_equals_dispatch_table():
    from app.models.job import JobKind
    from app.queue.dispatch import HANDLERS
    assert {m.value for m in JobKind} == set(HANDLERS.keys())
```
(Full code block already specified verbatim in RESEARCH.md § Proof 5 / `16-RESEARCH.md:621-639` — transcribe from there.)

---

### `tests/test_status_drift.py` (MODIFIED — D-05 rewrite)

**Analog:** itself. Two exact rewritten test bodies are already fully specified in `16-RESEARCH.md:311-341` (§ Jobs Index Set & D-05 Rewrite) — transcribe verbatim:
- `test_expected_indexes_present_and_no_others` — named-set comparison replacing `sql.count(...) == 3`.
- `test_do_block_constraint_drops_are_column_anchored` — stays `== 2` but rewritten with an `EXPECTED_DO_BLOCKS` named set + explanatory comment (jobs' inline CHECK deliberately does NOT add a third DO-block occurrence).

---

### `tests/conftest.py` (MODIFIED — `fake_repo` tuple)

**Analog:** itself, the tuple at `tests/conftest.py:994-1052` (full block already read).

**Pattern — append every new `jobs.py` function name to the SAME tuple, same style:**
```python
for name in (
    "insert_inbound_email",
    "find_business_by_sender",
    ...
    "clear_reply_context",
    "find_stranded_unconsumed_replies",
    # NEW (Phase 16): app/db/repo/jobs.py
    "enqueue_job",
    "claim_job",
    "complete_job",
    "fail_job",
    "release_lease",
):
    if hasattr(store, name):
        monkeypatch.setattr(repo_mod, name, getattr(store, name), raising=False)
```
**Load-bearing warning to preserve in a comment near the addition** (`conftest.py:1033-1036`, verbatim):
> a method defined on `InMemoryRepo` but MISSING from this tuple is simply never patched in — no `AttributeError`, no failure, just a silent fall-through to the real DB-backed repo.

Also implement the corresponding methods on `InMemoryRepo` itself (not shown in the excerpted range but implied — `find_awaiting_reply_for_header`/`find_any_run_for_header` at `conftest.py:968-985` are the shape to copy for any new in-memory job-store methods).

**`tests/test_threading.py`'s two tuples (lines 340-354, 423-436) — per Pitfall 8, VERIFIED to need NO change for Phase 16 as scoped** (they back `resume_pipeline`-only tests, and Phase 16 does not touch `resume_pipeline`). Only revisit if new retrigger-specific tests are added to that file.

---

### `.github/workflows/concurrency-proof.yml` (MODIFIED — D-04)

**Analog:** itself, line 89's hard-coded file list (not independently re-read this session beyond RESEARCH.md's confirmed citation — "the hard-coded 2-file list", `.github/workflows/concurrency-proof.yml:89`, its own comment at `:65-68` reading *"A new live-DB test that is not added to this list will skip silently and forever."*).

**Apply:** change the test-selection line from the hard-coded 2-file list to whole-suite marker collection: `pytest tests/ -m integration` (transcribe D-04's exact wording — "Keep the existing skip-guard" at lines 90-97 unchanged). Land this change BEFORE any of the new integration test files are committed (RESEARCH.md § Sampling Rate / Wave 0 Gaps ordering requirement), so they are covered from their first commit rather than needing a second workflow-file edit.

## Shared Patterns

### Caller-owns-transaction / `conn=` threading
**Source:** `app/db/repo/_shared.py` (full file, `_conn_ctx`/`_nulltx`)
**Apply to:** every function in `app/db/repo/jobs.py`, the modified `clear_reply_context`, and the refactored `retrigger()` route.
```python
def some_repo_fn(..., conn: psycopg.Connection | None = None) -> ...:
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute("...", (...)).fetchone()
    return row
```

### Atomic CAS via single UPDATE + RETURNING
**Source:** `app/db/repo/runs.py::claim_status` (`runs.py:356-381`)
**Apply to:** `claim_job`, `complete_job`, `fail_job`, `release_lease` (all fenced by `lease_token`), and the new `_claim_stale_in_flight` helper in `runs.py`.
```python
row = c.execute(
    "UPDATE <table> SET <cols> WHERE id = %s AND <expected-condition> RETURNING id",
    (...),
).fetchone()
return row is not None
```

### Module-object imports for monkeypatch seams (BOUND-01)
**Source:** `app/routes/pipeline_glue.py:1-8`
**Apply to:** `app/queue/dispatch.py`, `app/queue/handlers/pipeline.py`, and any router calling into them — always `from app.queue import dispatch` / `from app.queue.handlers import pipeline`, never `from app.queue.dispatch import HANDLERS` as a bare-name import.
```python
"""Every router imports these via a module-object import
(`from app.routes import pipeline_glue`), NEVER a bare-name import ...
the tests' `monkeypatch.setattr(pipeline_glue, <fn>)` seams would silently
stop taking effect otherwise."""
```

### Fail-fast, no-default config for load-bearing values
**Source:** `app/config.py:27` (`database_url: str  # no default — fails fast if unset`)
**Apply to:** D-07's pool-budget assertion at `lifespan` startup — refuse to start, do not clamp-and-warn. `WORKER_COUNT`/`LEASE_SECONDS`/`MAX_ATTEMPTS` themselves DO get defaults (D-08 — env-driven with sane defaults, `WORKER_COUNT=0` off-switch for tests), but the budget CHECK (`WORKER_COUNT + 2 <= max_size`) must be a hard failure, mirroring this file's "fails fast" philosophy rather than the empty-string-default pattern used for optional keys like `resend_api_key`.

### Barrier-released direct-repo-seam concurrency proofs
**Source:** `tests/test_concurrency_proof.py` (full file)
**Apply to:** `tests/test_queue_durability.py` Proofs 2, 3, 4 — never drive races through an HTTP route unless the route itself is the thing under test (Surface B's pattern, `test_concurrency_proof.py:260-315`, applies only if a future proof specifically targets an HTTP-layer race; Phase 16's proofs are all repo-seam-driven per D-06).

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `app/queue/worker.py` | service (daemon loop) | event-driven | No daemon-thread worker loop exists anywhere in this repo today; nearest structural cousin is test-only barrier/thread code (`tests/test_concurrency_proof.py`), not production code. Build from the RESEARCH.md-specified claim-loop shape + FastAPI's own `lifespan` convention (external framework pattern). |
| `app/main.py` lifespan wiring | config | event-driven (startup/shutdown) | This is the app's first-ever `lifespan` hook — no prior startup/shutdown wiring exists to copy. Use FastAPI's native `@asynccontextmanager` convention. |
| `tests/test_webhook_unblocked.py` | test | request-response (async concurrency) | No existing test in this repo uses `httpx.AsyncClient` + `ASGITransport` + `asyncio.gather`; every prior concurrency test either uses `TestClient` (single-request cases) or drives the sync repo seam directly (`test_concurrency_proof.py`). The exact pattern is pre-specified in `16-RESEARCH.md` § Proof 1 — transcribe from there rather than searching the codebase further. |

## Metadata

**Analog search scope:** `app/db/repo/`, `app/routes/`, `app/models/`, `app/config.py`, `app/main.py`, `app/db/schema.sql`, `app/db/bootstrap.py`, `tests/test_concurrency_proof.py`, `tests/conftest.py`, `tests/test_status_drift.py` (line-targeted via RESEARCH.md citations)
**Files scanned:** 15 direct reads this session (all cited above with line ranges) + RESEARCH.md/CONTEXT.md as pre-validated secondary sources for the exact SQL/test bodies that are transcription-not-design
**Pattern extraction date:** 2026-07-14
