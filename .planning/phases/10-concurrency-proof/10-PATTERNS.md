# Phase 10: Concurrency Proof - Pattern Map

**Mapped:** 2026-07-07
**Files analyzed:** 2 (both net-new; test-only phase, zero production-code changes)
**Analogs found:** 2 / 2 (both exact-role analogs; one is a near-verbatim template)

> This is a **test-only consolidation phase**. Every mechanic already exists in this repo's source — the two new files reuse proven excerpts. RESEARCH.md resolved all mechanics and cited every seam at file:line; this map pulls the exact excerpts so the planner writes concrete `<read_first>` / `<action>` fields. Do NOT reinvent the harness or re-open any locked D-10-0x decision.

---

## File Classification

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `tests/test_concurrency_proof.py` | test (integration capstone) | event-driven / request-response (N concurrent HTTP POSTs → DB CAS/dedup invariants) | `tests/test_webhook_dedup_race.py` | **exact** (same harness; new module consolidates 3 surfaces vs. its 1) |
| `.github/workflows/concurrency-proof.yml` | config (CI workflow) | batch (CI job: bootstrap → run integration suite) | `.github/workflows/eval.yml` | **role-match** (same house CI shape; new job ADDS `services: postgres` + bootstrap) |

Secondary analogs drawn on per surface:
- `tests/test_claim_status.py` — the CAS approval-race stub (`test_claim_status_concurrent_calls_exactly_one_true`, currently `pytest.skip`) that Phase 10 lifts to the HTTP `/approve` route (D-10-06).
- `tests/test_atomic_persist.py` — live-run seeding (`_seed_live_run`) + two-factor guard boilerplate + the `LiveMockOpenAI` stub class.
- `.github/workflows/keepalive.yml` — the other existing workflow (env/secrets convention; reference only).

---

## Pattern Assignments

### `tests/test_concurrency_proof.py` (test, event-driven capstone)

**Analog:** `tests/test_webhook_dedup_race.py` (verbatim template) + `tests/test_atomic_persist.py` (seed/stub helpers)

This module consolidates THREE surfaces (A dedup, B approval-via-HTTP, C concurrent distinct runs) proving FOUR invariants. Each surface reuses the template's thread+TestClient+env pattern. Three test functions map to four invariants (Surface C proves both "no lost update" and "no half-write").

**Module docstring (proof-narrative tone, D-10-02):** mirror the header docstring style of `test_webhook_dedup_race.py:1-18` — state what is fired, what must hold, and the crash/race window each surface closes. The module IS the proof; no separate `PROOF.md`.

**Two-factor DB skip guard** (copy from `test_atomic_persist.py:38-44`, universal shape):
```python
_HAS_DB = bool(os.environ.get("DATABASE_URL"))
_HAS_RESET = os.environ.get("ALLOW_DB_RESET") == "1"

_SKIP_LIVE_DB = pytest.mark.skipif(
    not (_HAS_DB and _HAS_RESET),
    reason="Live-DB tests require DATABASE_URL and ALLOW_DB_RESET=1 (two-factor guard)",
)
```
Each test carries `@pytest.mark.integration`. Use `@_SKIP_LIVE_DB` (or the inline `if not os.environ.get("DATABASE_URL"): pytest.skip(...)` shape at `test_webhook_dedup_race.py:33-34`) — both are proven; `@_SKIP_LIVE_DB` is the two-factor form and is preferred since the CI job sets both vars.

**Per-test env setup + cache clear** (copy from `test_webhook_dedup_race.py:36-43`) — pytest does NOT share monkeypatch state across modules (RESEARCH Pitfall 3), so the capstone MUST set its own:
```python
from app.config import get_settings

get_settings.cache_clear()
# Without this, every webhook/approve POST 400s on signature rejection BEFORE
# reaching the dedup/CAS logic under test (RESEARCH Pitfall 2).
monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
# ... build TestClient, stub seams, fire threads ...
get_settings.cache_clear()  # reset at end (template line 110)
```

**Shared stubbing seam — the load-bearing isolation** (mirror `test_webhook_dedup_race.py:56-59`; RESEARCH Mechanic 2). TestClient runs BackgroundTasks SYNCHRONOUSLY and `_deliver` is called synchronously inside the approve route — with `.env` carrying LIVE LLM/Resend keys, any unstubbed path flakes and burns credits. A shared `_stub_pipeline_and_send(monkeypatch)` helper should install all three no-ops:
```python
import app.main as app_main

# Surfaces A + C: winner's BackgroundTask would run the REAL orchestrator (real
# DeepSeek/Kimi). No-op captures the call so you can assert exactly-one call.
pipeline_calls: list = []
monkeypatch.setattr(
    app_main, "_run_pipeline", lambda run_id: pipeline_calls.append(run_id)
)

# Surface B: the winning approve calls _deliver synchronously inside the route
# (main.py:764) → real send_outbound. _deliver is imported INSIDE the route
# (main.py:753), so patch it on the orchestrator module, NOT app_main.
deliver_calls: list = []
monkeypatch.setattr(
    "app.pipeline.orchestrator._deliver",
    lambda rid, run: deliver_calls.append(rid),
)

# Belt-and-suspenders no-op (conftest.py:1005-1010 pattern) — guarantees no
# accidental live send if a code path changes.
import resend
monkeypatch.setattr(
    resend.Emails, "send",
    staticmethod(lambda params: {"id": "fake-resend-id"}), raising=True,
)
```

**Thread harness** (template `test_webhook_dedup_race.py:76-89`; RESEARCH Mechanic 2/3 recommends `ThreadPoolExecutor(max_workers=N)` for N=8 as the clean generalization, OR keep raw threads to match the template exactly — either is fine per D-10-05). Raw-thread form from the template:
```python
results: list[dict] = []
lock = threading.Lock()

def _post() -> None:
    r = client.post("/webhook/inbound", json=payload)
    with lock:
        results.append(r.json())

threads = [threading.Thread(target=_post) for _ in range(N)]
for t in threads: t.start()
for t in threads: t.join()
```
`ThreadPoolExecutor` form (no manual lock needed — `executor.map` returns an ordered list):
```python
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(max_workers=N) as ex:
    responses = list(ex.map(lambda _: client.post(url, json=payload), range(N)))
```
**N=8** (RESEARCH Mechanic 3): genuinely interleaves, stays inside the pool budget (min=1/max=5) because each pooled connection is held only for the sub-millisecond ingest/CAS transaction, not the thread lifetime. Drive everything through the app pool via TestClient — do NOT open per-thread raw `psycopg.connect` connections. Do NOT exceed ~10 (D-10-07).

**Live-run seeding helper** (adapt from `test_atomic_persist.py:120-133` — needed for Surface B, which must seed ONE run and drive it to `AWAITING_APPROVAL`):
```python
def _seed_live_run(*, body: str, from_addr: str = COASTAL_EMAIL) -> uuid.UUID:
    """Insert an inbound email + run against the REAL DB (repo.*, no conn=)."""
    from app.db import repo
    eid, _ = repo.insert_inbound_email(
        message_id=f"<{uuid.uuid4()}@test.example>",
        in_reply_to=None, references_header=None,
        subject="payroll hours", from_addr=from_addr,
        to_addr="agent@payroll-agent.local", body_text=body,
    )
    return repo.create_run(business_id=COASTAL_BIZ_ID, source_email_id=eid)
```
Reuse the shared seed identifiers (`test_atomic_persist.py:49-51`): `COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")`, `COASTAL_EMAIL = "payroll@coastalcleaning.example"`. Depend on the `seeded_db` fixture (`conftest.py:58-74`, module-scoped, seeds Coastal/business roster once) so `business_id`/roster exist.

---

#### Surface A — `test_dedup_exactly_one_run_per_message_id` (invariant: no duplicate run)

**Seam:** `repo.insert_inbound_email` (`repo.py:171`, SQL `INSERT ... ON CONFLICT (message_id) DO NOTHING RETURNING id` at `repo.py:193-201`) → `repo.create_run` (`repo.py:324`). Whole ingest is ONE transaction committed before `background_tasks.add_task` (D-9-09).
**Fire:** N=8 duplicate POSTs to `/webhook/inbound` with ONE shared `message_id` (payload shape at `test_webhook_dedup_race.py:63-74`).
**Assert** (from template `test_webhook_dedup_race.py:91-108`):
```python
run_ids = {r.get("run_id") for r in results if r.get("run_id")}
assert len(run_ids) == 1
assert {r.get("status") for r in results} <= {"accepted", "duplicate"}
assert len(pipeline_calls) == 1   # exactly one winner scheduled the pipeline
```
Optional direct DB assertion: `SELECT count(*) FROM payroll_runs WHERE source_email_id = (SELECT id FROM email_messages WHERE message_id = %s)` == 1.

#### Surface B — `test_concurrent_approvals_exactly_one_wins` (invariant: no double-approval)

**Seam:** `POST /runs/{run_id}/approve` (`main.py:738`) → `repo.claim_status(run_id, AWAITING_APPROVAL, APPROVED)` (`main.py:755`; CAS SQL `UPDATE ... WHERE id=%s AND status=%s RETURNING id` at `repo.py:471-473`) → on claimed, synchronous `_deliver` at `main.py:764`. Route ALWAYS returns 303 (`main.py:783`) regardless of claim outcome.
**Setup:** `_seed_live_run(...)` then `repo.set_status(run_id, RunStatus.AWAITING_APPROVAL)` to reach the CAS's `expected` status.
**Fire:** N=8 concurrent `client.post(f"/runs/{run_id}/approve")`.
**Assert** — do NOT count 303s (RESEARCH Pitfall 5: the route always 303s). Assert the winning side effect:
```python
assert len(deliver_calls) == 1   # exactly one _deliver above the CAS (D-10-06)
# and the DB terminal status reached 'approved' exactly once:
assert repo.load_run(run_id)["status"] == "approved"
```
This is the D-10-06 upgrade over `test_claim_status.py:159` (which only races the CAS primitive and is currently a `pytest.skip` stub at line 176) — the HTTP route catches route-level regressions ABOVE the CAS.

#### Surface C — `test_concurrent_distinct_runs_no_lost_update` (invariants: no lost update + no half-write)

**Recommendation (resolving the D-10 discretion point, RESEARCH Mechanic 4):** use **distinct parallel `message_id`s** (throughput/atomicity-under-load), NOT the dedup harness.
**Fire:** N=8 webhook POSTs each with a UNIQUE `message_id` AND unique `id`.
**Assert:**
```python
# no lost update — every distinct ingest produced exactly one run:
# SELECT count(*) FROM payroll_runs WHERE source_email_id IN (<the N email ids>) == N
# no half-write — every run row exists WITH its source email row (D-9-09 ingest
# txn atomicity): each run has non-null source_email_id and a matching
# email_messages row; no orphaned/partial rows.
```
The fault-injection half-write proof STAYS in `test_atomic_persist.py:170` (`test_process_branch_crash_leaves_run_unadvanced`) per D-10-01 — the capstone asserts the lighter "no orphaned/partial rows under concurrent distinct ingests" (with `_run_pipeline` stubbed, runs stay at `received`), it does NOT duplicate the monkeypatch-crash machinery.

---

### `.github/workflows/concurrency-proof.yml` (config, CI batch)

**Analog:** `.github/workflows/eval.yml` (house CI shape — copy verbatim) + `keepalive.yml` (env convention, reference only)

**Delta from analog:** the eval `check` job is hermetic (`DATABASE_URL: "placeholder"`, no DB). The new job ADDS a net-new `services: postgres` container + a schema-bootstrap step + runs `-m integration`. RESEARCH Mechanic 1 supplies a ready-to-adapt full sketch (10-RESEARCH.md:88-136) — copy it. The pattern deltas:

**Copy verbatim from `eval.yml:20-31`** — the house step sequence:
```yaml
steps:
  - name: Checkout
    uses: actions/checkout@v4
  - name: Set up uv + Python 3.12
    uses: astral-sh/setup-uv@v5
    with:
      python-version: "3.12"
  - name: Install deps (all groups)
    run: uv sync
```
And the `on:` trigger shape (`eval.yml:3-6`): `push: branches: ["master"]` + `workflow_dispatch:`.

**NET-NEW `services:` block** (RESEARCH sketch 10-RESEARCH.md:100-114; canonical `pg_isready` health-check form):
```yaml
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: postgres
    ports:
      - 5432:5432
    options: >-
      --health-cmd "pg_isready -U postgres"
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5
```

**NET-NEW job env block** — plain LOCAL Postgres URL, NOT a Supavisor pooler URL (RESEARCH Pitfall 4; `prepare_threshold=None` in `supabase.py` is a harmless no-op against vanilla PG):
```yaml
env:
  DATABASE_URL: "postgresql://postgres:postgres@localhost:5432/postgres"
  ALLOW_DB_RESET: "1"
  ALLOW_UNSIGNED_FIXTURES: "true"
```

**NET-NEW bootstrap + run steps** (RESEARCH sketch 10-RESEARCH.md:130-135):
```yaml
  - name: Apply schema to ephemeral Postgres
    run: uv run python -m app.db.bootstrap --reset
  - name: Run the concurrency proof
    run: uv run pytest tests/test_concurrency_proof.py -m integration -v
```
`app/db/bootstrap.py:96` opens a plain `psycopg.connect(db_url, prepare_threshold=None)` (NOT the app pool) and applies `schema.sql` — verified vanilla-Postgres-clean (no Supabase extensions/roles/`gen_random_uuid`). Entrypoint `python -m app.db.bootstrap [--reset]` at `bootstrap.py:138`.

**Security note (RESEARCH §Security):** `POSTGRES_PASSWORD: postgres` is an ephemeral, network-isolated CI container — NOT a secret, so NO `secrets.*` reference is needed (unlike `eval.yml`'s `EXTRACTION_API_KEY` or `keepalive.yml`'s `RENDER_URL`). NEVER point this job at the real Supabase `DATABASE_URL` — it runs `bootstrap --reset` (destructive) and must only touch the ephemeral container.

---

## Shared Patterns

### Env setup + config cache-clear (applies to EVERY test in the capstone)
**Source:** `tests/test_webhook_dedup_race.py:36-43,110`
`get_settings.cache_clear()` → `monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")` per test (NOT inherited across modules — RESEARCH Pitfall 3), reset cache at end. Also set `ALLOW_UNSIGNED_FIXTURES=true` job-level in CI (belt-and-suspenders).

### Wholesale LLM/provider stubbing (applies to all three surfaces)
**Source:** `tests/test_webhook_dedup_race.py:56-59` (`_run_pipeline`), `app/main.py:753-764` (`_deliver` import + sync call), `tests/conftest.py:1005-1010` (resend no-op)
**Apply to:** all three surfaces — a shared `_stub_pipeline_and_send(monkeypatch)` helper. Stub `_run_pipeline` (A+C), `_deliver` (B), `resend.Emails.send` (safety net). Rationale: `.env` carries LIVE keys (MEMORY: execute-phase-integration-hazards); TestClient runs BackgroundTasks + the sync `_deliver` inline → unstubbed = flaky, credit-burning.

### Two-factor live-DB guard + `integration` marker
**Source:** `tests/conftest.py:48-55` (`_SKIP_LIVE_DB`), `pyproject.toml` (`integration` marker), `conftest.py:58-74` (`seeded_db` fixture)
**Apply to:** every capstone test — `@pytest.mark.integration` + `@_SKIP_LIVE_DB`, depend on `seeded_db` for Coastal/business roster. Keeps the default `uv run pytest -m 'not integration'` suite DB-free and green (D-10-04).

### Live-run seeding via real repo helpers
**Source:** `tests/test_atomic_persist.py:120-133` (`_seed_live_run`), shared IDs at `:49-51`
**Apply to:** Surface B (seed a run → `AWAITING_APPROVAL`). Uses `repo.insert_inbound_email` + `repo.create_run` — the real ingest helpers, no ad-hoc INSERTs.

---

## No Analog Found

None. Both new files have direct in-repo analogs; the phase is explicitly a consolidation/generalization of proven code (RESEARCH §Summary, D-10-01). The only convention-not-verified element is the GitHub Actions `services: postgres` YAML syntax (RESEARCH Assumption A1 / Secondary source) — a widely-documented canonical pattern, supplied ready-to-adapt in the RESEARCH sketch.

---

## Metadata

**Analog search scope:** `tests/` (test_webhook_dedup_race, test_claim_status, test_atomic_persist, conftest), `.github/workflows/` (eval, keepalive), `app/main.py`, `app/db/repo.py`, `app/db/supabase.py`, `app/db/bootstrap.py`, `app/db/schema.sql` — all cited at file:line in RESEARCH and spot-verified live.
**Files scanned (read in this pass):** 6 (2 CONTEXT/RESEARCH inputs + test_webhook_dedup_race, eval.yml, test_claim_status excerpt, test_atomic_persist excerpt, keepalive.yml, main.py approve route, conftest guard+resend excerpts).
**Pattern extraction date:** 2026-07-07
