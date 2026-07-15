# Phase 17: The Pump - Pattern Map

**Mapped:** 2026-07-15
**Files analyzed:** 10 (create + modify)
**Analogs found:** 10 / 10 (RESEARCH.md already resolved the two hardest ones — the enriched `drain_once()` diff and the pump route body — to working code; this file cites those and adds the remaining router/test/workflow/config/render analogs RESEARCH.md didn't fully excerpt)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|-----------------|---------------|
| `app/routes/pump.py` | route/controller | request-response (thin, sync, delegates to queue) | `app/routes/health.py` | exact (router shape, JSONResponse, disclosure discipline, sync `def`) |
| `tests/test_pump_route.py` | test | request-response (hermetic, TestClient) | `tests/test_queue_drain.py` (fake_repo style) + `app/routes/health.py`'s own contract | role-match |
| `.github/workflows/pump.yml` | config (CI/CD) | event-driven (cron) | `.github/workflows/keepalive.yml` (deleted this phase) | exact (structure, comment style, `-f`/`workflow_dispatch` carried forward almost verbatim) |
| `app/queue/drain.py` (`drain_once()`) | service/orchestration | event-driven → CRUD (claim/dispatch/complete-or-fail) | itself, pre-enrichment (`app/queue/drain.py:117-192`, RESEARCH.md already produced the exact diff) | exact — RESEARCH.md's Pattern 1 is the analog and the target in one |
| `app/db/repo/jobs.py` (`count_open_jobs`) | repo/model (CRUD, point-in-time read) | CRUD | every existing function in the same file (`enqueue_job`, `get_job`) — the `_conn_ctx`/`_nulltx` convention | exact |
| `app/db/repo/__init__.py` | config/facade | CRUD (re-export) | its own existing six-function re-export block | exact |
| `app/queue/worker.py:198` | orchestration | event-driven (truthiness only, no logic change) | itself (unchanged call site; contract preserved) | exact |
| `app/main.py` | config (wiring) | request-response (router registration) | its existing `app.include_router(health.router)` line | exact |
| `app/config.py` (`Settings.pump_token`) | config | CRUD (env-var load) | `resend_api_key` / `webhook_signing_secret` fields, same file | exact |
| `render.yaml` (`PUMP_TOKEN`) | config | CRUD (secret provisioning) | `WEBHOOK_SIGNING_SECRET` entry, same file | exact |
| `tests/test_queue_durability.py` (new `queueproof` test) | test | event-driven (live-DB durability proof) | `test_retrigger_survives_worker_crash_mid_lease` (available_at/leased_until backdating idiom, same file) | exact |
| `README.md` (cadence/750h doc block) | docs | n/a | `app/config.py`'s `lease_seconds` derivation-comment convention (prose style to imitate) | role-match |

## Pattern Assignments

### `app/routes/pump.py` (route, request-response)

**Analog:** `app/routes/health.py` (full file, 74 lines — read in full, small file, no re-read needed)

**Imports pattern** (`app/routes/health.py:1-10`):
```python
"""GET /health/live, /health/ready, /health/schema — health probes."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.db.schema_introspect import diff_against_live
from app.db.supabase import get_connection

logger = logging.getLogger("payroll_agent.webhook")

router = APIRouter()
```
For `pump.py`, swap the last two imports for `from app.config import get_settings`, `from app.db import repo`, `from app.queue.drain import DrainOutcome, drain_once`, and add stdlib `hmac`, `time`. Use `logger = logging.getLogger("payroll_agent.queue")` (matches `drain.py`'s own logger name, not `health.py`'s `webhook` name — the pump belongs to the queue subsystem).

**Route shape / disclosure discipline** (`app/routes/health.py:29-47`, the `/health/ready` probe — closest existing analog for "hits the DB, 503 on genuine failure, body never leaks internals"):
```python
@router.get("/health/ready")
def health_ready() -> JSONResponse:
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1 FROM businesses LIMIT 1")
        return JSONResponse({"status": "ready"})
    except Exception as exc:
        logger.error("readiness probe failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="database not ready") from exc
```
Note the disclosure rule to copy verbatim: log `type(exc).__name__` only, never `str(exc)` (which could contain a connection string), and the HTTP body carries a fixed short string, never the exception text. Apply the identical rule to the pump's 503 branch (D-10).

**Full target route body:** already produced end-to-end in RESEARCH.md's "Pattern 2: The pump route — thin, sync, bounded" (`app/routes/health.py`-modeled `_authorized()` + `pump()`). Use that code verbatim as the plan's action; it already encodes D-01/D-02/D-03/D-04/D-05/D-09/D-10.

**Sync-def rationale to cite:** RESEARCH.md's own note — FastAPI runs a plain `def` route in the AnyIO threadpool, keeping the event loop free while blocking psycopg + LLM calls run inside `dispatch.handle`; this mirrors `health.py`'s own all-sync-def convention (no route in that file is `async def`).

---

### `tests/test_pump_route.py` (test, hermetic)

**Analog:** `tests/test_queue_drain.py` (module-level fake_repo + fixture style, lines 1-80 read) for the fixture/seeding idiom, plus `app/routes/health.py`'s own contract as the thing under test's shape.

**Fixture/seeding conventions to copy** (`tests/test_queue_drain.py:52-70`):
```python
def _coastal_business_id(fake_repo: Any) -> uuid.UUID:
    business_id: uuid.UUID = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    return business_id


def _seed_run(fake_repo: Any, *, status: RunStatus) -> uuid.UUID:
    run_id: uuid.UUID = fake_repo.create_run(
        business_id=_coastal_business_id(fake_repo), source_email_id=None
    )
    fake_repo.set_status(run_id, status)
    return run_id
```
Use `TestClient(app_main.app)` (already the whole suite's convention per `tests/conftest.py`'s suite-wide `WORKER_COUNT=0`) rather than calling the route function directly — this is what actually exercises FastAPI's dependency/exception handling for the 401/503 paths. Monkeypatch `get_settings().pump_token` (or set the env var via `monkeypatch.setenv("PUMP_TOKEN", ...)` before `get_settings.cache_clear()`, matching how other tests in this suite override cached settings — grep `get_settings.cache_clear` for the exact idiom used elsewhere in the suite before writing this).

**Required test cases** (from RESEARCH.md's Validation Architecture table — do not re-derive, just implement):
- 401 on missing/wrong/empty-secret Bearer token; 200 on correct token.
- Bounded drain loop: stub `drain_once` to always return a non-EMPTY `DrainOutcome`, assert the loop exits at `_MAX_JOBS_PER_PUMP` or the wall-clock cap.
- D-10 infra-failure test: make `fake_repo`/a monkeypatched `repo.count_open_jobs` or `repo.claim_job` raise, assert 503 (not 200, not a swallowed 500-as-200).

---

### `.github/workflows/pump.yml` (config, cron)

**Analog:** `.github/workflows/keepalive.yml` (deleted this phase; full 51-line file read above) — this is a near-verbatim template, not a partial pattern.

**Structure to carry forward exactly:**
- The `Validate secrets are set` fail-fast step (`keepalive.yml:26-35`), extended to check both `RENDER_URL` and `PUMP_TOKEN`.
- The `-f` (fail-on-non-2xx) discipline and the comment explaining why swallowing would make the check silently useless (`keepalive.yml:11-13`).
- `workflow_dispatch` with the 60-day auto-disable rationale comment (`keepalive.yml:8-9`).
- The `/health/ready` and `/health/schema` steps, copied verbatim including their `--max-time 90` (`keepalive.yml:37-51`) — RESEARCH.md's Pitfall 2 is explicit that only the *new* pump step needs a different, larger `--max-time` (360s, sized against `wall_clock_cap + single_job_worst_case = 120 + 210`); do not uniformly copy `90` onto all three steps.

**Full target file:** already produced end-to-end in RESEARCH.md's "Code Examples → `pump.yml`". Use verbatim as the plan's action.

---

### `app/queue/drain.py` (`drain_once()` enrichment, D-04)

**Analog:** the function's own pre-enrichment body. RESEARCH.md's "Pattern 1: Capture-don't-thread" already produced the full target diff against `app/queue/drain.py:117-192` — cite it directly, do not re-derive. Key facts already confirmed by direct source read (not to be re-verified by the planner):
- `complete_job` returns `bool`, `fail_job` returns `JobState | None` **today** — no signature change needed to either; `drain_once()` only needs to capture what they already return.
- `DrainOutcome` (new `enum.StrEnum` with `__bool__`) lives in `app/queue/drain.py`, not `app/models/job.py` (it mirrors no SQL column, unlike `JobKind`/`JobState`).
- `worker.py:198`'s `if drain.drain_once():` needs **zero changes** — truthiness contract preserved by `__bool__`.

**Mechanical cost, not a new pattern to design:** ~15 `assert drain.drain_once() is True`/`is False` sites across 6 test files must be rewritten to assert the specific `DrainOutcome` value. RESEARCH.md's Pitfall 1 enumerates every site by file:line — reuse that list verbatim in the plan's task breakdown rather than re-grepping.

---

### `app/db/repo/jobs.py` (`count_open_jobs`, new function)

**Analog:** every existing function in the same file — the `_conn_ctx`/`_nulltx` convention is uniform across all six current functions (`app/db/repo/jobs.py:1-60` read in full above).

**Imports already in place, nothing new needed:**
```python
from app.db.repo._shared import _conn_ctx, _nulltx
```

**Target function** (already produced in RESEARCH.md's "Code Examples → the queue-depth repo function"):
```python
def count_open_jobs(conn: psycopg.Connection | None = None) -> int:
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT count(*) FROM jobs WHERE state IN ('pending', 'leased')"
        ).fetchone()
    return int(row[0]) if row else 0
```

**Two things NOT to forget** (RESEARCH.md Pitfall 4 — must land in the same commit):
1. Update the module docstring's `"Six functions, and this is the whole public surface: ..."` line (`app/db/repo/jobs.py:2-3`) to seven and add `count_open_jobs` to the enumerated list.
2. Re-export through `app/db/repo/__init__.py` — both the import statement and `__all__`, matching the existing six-function pattern in that file.

---

### `app/config.py` (`Settings.pump_token`)

**Analog:** `resend_api_key` / `webhook_signing_secret` fields, same file (`app/config.py:56-57`):
```python
resend_api_key: str = ""            # RESEND_API_KEY env var
webhook_signing_secret: str = ""    # WEBHOOK_SIGNING_SECRET env var
```
Add `pump_token: str = ""` immediately following this style — empty-default-secret, one-line trailing comment naming the env var. Per D-03, the fail-closed behavior (reject when empty) is implemented in the **route** (`_authorized()`), not as validation on this field — matching how `allow_unsigned_fixtures`/`ALLOW_UNSIGNED_FIXTURES` gates behavior at the call site rather than in `Settings` itself (`app/config.py:60-65` is the precedent for "a boolean gate lives in Settings but its *meaning* is enforced elsewhere").

Place it in — or immediately adjacent to — the existing `# ── Durable job queue ──` block (`app/config.py:72` onward, alongside `worker_count`/`lease_seconds`/`max_attempts`/`queue_poll_seconds`), since it's a queue-adjacent secret, not a general app secret. Either location is defensible; adjacency to the queue block is slightly more discoverable.

---

### `render.yaml` (`PUMP_TOKEN`)

**Analog:** `WEBHOOK_SIGNING_SECRET` entry, same file (`render.yaml:27-28`):
```yaml
      - key: WEBHOOK_SIGNING_SECRET
        sync: false        # Resend inbound webhook signing secret (from resend.com webhook settings)
```
Add immediately after it (or grouped with the other `sync:false` secrets, lines 20-34):
```yaml
      - key: PUMP_TOKEN
        sync: false        # Shared secret the pump.yml cron sends as `Authorization: Bearer $PUMP_TOKEN`
```

---

### `tests/test_queue_durability.py` (new `queueproof` test — criterion #2 anchor)

**Analog:** `test_retrigger_survives_worker_crash_mid_lease` in the same file — the `available_at`/`leased_until` direct-SQL backdating idiom (already excerpted verbatim in RESEARCH.md's "Manipulating `available_at` for the durability proof" — reuse verbatim, do not re-derive):
```python
with repo.get_connection() as conn, conn.transaction():
    conn.execute(
        "UPDATE jobs SET available_at = now() + interval '1 hour' WHERE id = %s",
        (str(job_id),),
    )
# ... assert not claimable while future-dated ...
with repo.get_connection() as conn, conn.transaction():
    conn.execute(
        "UPDATE jobs SET available_at = now() - interval '1 second' WHERE id = %s",
        (str(job_id),),
    )
```

**Full 8-step design already specified** in RESEARCH.md's "Designing the anti-vacuous-proof anchor (criterion #2)" — reuse verbatim, including: reuse `seeded_db`/`_isolated_jobs`/`_seed_run_for_queue_proof()` fixtures already in this file; explicitly assert `live_queue_worker_threads() == []` as a precondition (mirroring the existing module's own precondition-assertion style, e.g. in `test_a_restarted_worker_claims_and_completes_a_real_job`); hit `/internal/pump` via `TestClient(app_main.app)`, not `drain.drain_once()` directly, since the endpoint itself is what's under test for this one proof.

**Marker:** `pytestmark = [pytest.mark.integration, pytest.mark.queueproof]` (already registered per Phase 16 D-14 — `concurrency-proof.yml`'s second step already collects it; no workflow edit needed).

---

## Shared Patterns

### Constant-time secret compare (D-01)
**Source:** none in-repo (RESEARCH.md confirmed via `grep -rn "compare_digest\|hmac\." app/` — zero hits; the webhook's HMAC check is fully delegated to `resend.Webhooks.verify()`, nothing to extract).
**Apply to:** `app/routes/pump.py`'s `_authorized()` only.
```python
import hmac

def _authorized(request: Request) -> bool:
    token = get_settings().pump_token
    if not token:  # D-03: fail closed on an unset/empty secret
        return False
    expected = f"Bearer {token}".encode()
    got = request.headers.get("authorization", "").encode()
    return hmac.compare_digest(got, expected)
```
Do not spend planning time searching for an existing seam to reuse — RESEARCH.md's Pitfall 5 already ruled this out.

### Disclosure discipline (log type name only, fixed short body)
**Source:** `app/routes/health.py:45-47` and `:65-67` (both `/health/ready` and `/health/schema`).
**Apply to:** the pump route's 503 branch — `logger.error("pump: infra failure mid-drain: %s", type(exc).__name__)` then `raise HTTPException(status_code=503, detail="pump unavailable") from exc`. Never log/return `str(exc)` (could contain a connection string).

### `_conn_ctx`/`_nulltx` repo convention
**Source:** `app/db/repo/jobs.py` (every one of its 6 existing functions) via `app.db.repo._shared`.
**Apply to:** `count_open_jobs`.

### Empty-default-secret `Settings` field convention
**Source:** `app/config.py:56-57` (`resend_api_key`, `webhook_signing_secret`).
**Apply to:** `pump_token`.

### `sync:false` three-point secret topology
**Source:** `render.yaml:27-28` (`WEBHOOK_SIGNING_SECRET`) + `app/config.py` field + GitHub Actions repo secret (`PUMP_TOKEN` in `pump.yml`'s `env:`).
**Apply to:** `render.yaml`, `app/config.py`, `.github/workflows/pump.yml`.

### `-f` cron discipline (RED on failure, never swallow)
**Source:** `.github/workflows/keepalive.yml:11-13`, `:37,50` (`curl -f`).
**Apply to:** all three `pump.yml` steps, with the pump step's own `--max-time` sized independently (360s vs the health steps' 90s) per RESEARCH.md Pitfall 2.

## No Analog Found

None — RESEARCH.md's direct-source-read pass already resolved every file in this phase's scope to a concrete in-repo or produced-verbatim analog; there is no file here that needs to fall back to an external/generic pattern.

## Metadata

**Analog search scope:** `app/routes/`, `app/queue/`, `app/db/repo/`, `app/config.py`, `render.yaml`, `.github/workflows/`, `tests/test_queue_drain.py`, `tests/test_queue_durability.py` — all read directly this session or already fully excerpted in 17-RESEARCH.md.
**Files scanned:** 8 source files read in full/targeted this session + RESEARCH.md's own direct-read set (drain.py, worker.py, jobs.py, models/job.py, repo/__init__.py, main.py, config.py, health.py, webhook.py, gateway.py, dispatch.py, pipeline.py, schema.sql, render.yaml, keepalive.yml, concurrency-proof.yml, pyproject.toml, conftest.py, test_queue_drain.py, test_queue_durability.py, test_repo_jobs_sql.py).
**Pattern extraction date:** 2026-07-15
