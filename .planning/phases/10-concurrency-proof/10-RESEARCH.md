# Phase 10: Concurrency Proof - Research

**Researched:** 2026-07-07
**Domain:** test harness engineering — OS-thread parallelism + real Postgres MVCC + FastAPI TestClient; GitHub Actions ephemeral Postgres service container
**Confidence:** HIGH (every mechanic below is verified against live source in THIS repo; the harness already exists in fragments — this is consolidation, not novel design)

## Summary

Phase 10 is a **test-only consolidation phase**. Every mechanic the planner needs is already proven in this repo's source — the job is to (1) unify three scattered per-surface race patterns into one capstone module, (2) lift the approval race from the `claim_status` primitive up to the real HTTP `/approve` route, and (3) stand up a CI job with an ephemeral Postgres service container so the proof actually runs on every push. No production code changes are planned.

The single load-bearing template is `tests/test_webhook_dedup_race.py` — it already demonstrates the exact pattern for all three surfaces: OS threads firing a real `TestClient` against a real Postgres, the `ALLOW_UNSIGNED_FIXTURES=true` env setup, the `_run_pipeline` no-op stub, and the documented "TestClient runs BackgroundTasks synchronously" caveat. The live-DB run-setup mechanics (seed → insert inbound → create_run → assert persisted values) are proven in `tests/test_atomic_persist.py`'s `_seed_live_run` helper.

**Primary recommendation:** Build `tests/test_concurrency_proof.py` as ONE `@pytest.mark.integration` module with three test functions (dedup, approval-race-via-HTTP, concurrent-distinct-runs), each reusing `test_webhook_dedup_race.py`'s thread+TestClient+env pattern verbatim. Fire N=8 threads via `ThreadPoolExecutor` per surface. Do NOT open per-thread raw `psycopg.connect` connections — the proven pattern drives everything through the app pool via `TestClient`, and the pool (min=1/max=5) is safe because pooled connections are held only for the microsecond-scale ingest/CAS transaction, not the whole thread lifetime. Stand up `.github/workflows/concurrency-proof.yml` following `eval.yml`'s uv+3.12 shape, adding a `services: postgres:16` block with a health check, `uv run python -m app.db.bootstrap`, and `uv run pytest -m integration`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Dedup race resolution | Database (Postgres MVCC) | API (webhook ingest txn) | The `uq_message_id` UNIQUE index + `ON CONFLICT DO NOTHING` inside one ingest transaction resolves the race — Python only fires the threads. |
| Approval CAS race resolution | Database (conditional UPDATE...RETURNING) | API (`/approve` route) | `claim_status`'s `WHERE id=%s AND status=%s RETURNING id` is the atomic primitive; the HTTP route is the tier under regression test (D-10-06). |
| No-half-write under concurrent runs | Database (single `conn.transaction()`) | Pipeline (orchestrator persist-txn) | D-9-04's status-advance-last invariant lives in `orchestrator._run_stages`; the DB transaction is what makes a crash roll back wholly. |
| Thread orchestration | Test harness (Python `ThreadPoolExecutor`) | — | The GIL is irrelevant (D-10-05) — contention resolves in Postgres, not Python; threads just create genuine near-simultaneity. |
| CI ephemeral Postgres | GitHub Actions runner (`services:` container) | — | A skip-guarded test that never runs proves nothing (D-10-03) — the service container makes the proof standing evidence. |

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-10-01** A NEW unified proof harness (`tests/test_concurrency_proof.py`) is the deliverable — one legible module firing ALL three surfaces under real parallelism, asserting ALL four invariants. Existing per-surface tests STAY as focused units; Phase 10 consolidates their invariants, it does not delete/replace them.
- **D-10-02** The test module IS the proof — no separate `PROOF.md`. Each invariant is its own clearly-named test with an explanatory docstring stating the invariant AND the crash/race window it guards.
- **D-10-03** A GitHub Actions CI job (`.github/workflows/concurrency-proof.yml`) runs the proof against an ephemeral Postgres on every push. Follows the `eval.yml` shape. Sets `DATABASE_URL` + `ALLOW_DB_RESET=1` + whatever the race tests require; runs with `-m integration` so it is NOT skipped.
- **D-10-04** Local reproduction documented, not required for the mocked suite. Proof stays `@pytest.mark.integration` so the default `uv run pytest -m 'not integration'` suite is unaffected.
- **D-10-05** OS threads (`ThreadPoolExecutor`) against a real Postgres — reuse the proven pattern. GIL is irrelevant; contention resolves in Postgres MVCC. No multiprocessing.
- **D-10-06** Prove "no double-approval" through the real HTTP `/runs/{run_id}/approve` route, not just the `claim_status` primitive. Fire N concurrent POSTs, assert exactly one succeeds. LLM draft/suggestion calls AND provider `send_outbound` MUST be stubbed (TestClient runs BackgroundTasks synchronously). Other two surfaces similarly stub pipeline/LLM.
- **D-10-07** Small fixed N (~5–10), deterministic assertions. Pool constraint the planner MUST respect: app pool is `min=1, max=5` — harness must not require >~5 simultaneously-held pooled connections, OR open its own connections outside the app pool.

### Claude's Discretion

- Exact module name, test/function names, and how the three surfaces are organized (one test each vs. shared fixture).
- Exact N per surface within ~5–10.
- Whether "concurrent runs" asserts via distinct `message_id`s in parallel or reuses the dedup harness with distinct ids.
- CI workflow specifics (Postgres service image/version, bootstrap step reuse, matrix vs. single job) — follow `eval.yml`.
- Whether to backfill `test_claim_status.py` with the HTTP-level approval race (capstone is the required home; backfill optional if trivially cheap).

### Deferred Ideas (OUT OF SCOPE)

- Guard-hardening the unguarded `set_status` writes against a swept-to-ERROR-but-alive run (D-9-13 accepted tension) — only pull in if THIS proof demonstrates the window matters in practice. Default: remains deferred; the proof documents the window if observed, does not add the guard speculatively.
- Larger-N load/soak flavor (50–100 concurrent, throughput numbers) — rejected (D-10-07: theater, CI-flaky, not stronger proof).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OPS2-03 | A concurrency proof test fires N simultaneous operations (concurrent runs, duplicate webhooks, simultaneous approvals on one run) and asserts the invariants hold — no double-approval, no lost update, no duplicate run, no half-written state. Evidence behind the production-grade claim. | Mechanics 1–4 below give the exact seams (`insert_inbound_email` ON CONFLICT, `claim_status` CAS via `/approve`, `create_run` + `_run_stages` persist-txn) and the proven thread+TestClient harness (`test_webhook_dedup_race.py`) + CI service-container recipe to make it standing evidence. |

---

## Mechanic 1 — GitHub Actions Postgres service container

**Recommendation:** Add ONE job to a new `.github/workflows/concurrency-proof.yml` that mirrors `eval.yml`'s `check` job (uv + Python 3.12 + `uv sync`) and adds a `services: postgres` block. Use `postgres:16` (matches Supabase's Postgres 15/16 line closely enough; the schema uses only vanilla DDL — verified below). Apply the schema via the existing `bootstrap` module invoked as `python -m app.db.bootstrap`.

### Evidence

- `.github/workflows/eval.yml:20-31` — the house CI shape: `actions/checkout@v4` → `astral-sh/setup-uv@v5` with `python-version: "3.12"` → `uv sync` → `uv run <cmd>` with `env: DATABASE_URL: ...`. **Copy this structure verbatim.**
- `app/db/bootstrap.py:96` — `psycopg.connect(db_url, prepare_threshold=None)` opens a **single direct connection** (NOT the app pool) and applies `schema.sql`. Entrypoint at `bootstrap.py:138-140`: `python -m app.db.bootstrap` (non-destructive) or `--reset` (destructive). **This runs fine against vanilla Postgres** — it's a plain `psycopg.connect`, no Supavisor/pooler dependency.
- `app/db/schema.sql` — verified vanilla-Postgres-compatible: standard `CREATE TABLE IF NOT EXISTS`, `UNIQUE` indexes, JSONB columns, `DO $$ ... $$` migration blocks, `now() - interval` arithmetic. No Supabase-specific extensions (`auth.*`, `storage.*`) or roles are referenced. `pgcrypto`/`uuid-ossp` are NOT required — UUIDs are generated Python-side (`uuid.uuid4()` in `repo.create_run`, `bootstrap` never calls `gen_random_uuid()`).
- `app/db/supabase.py:52-63` — the **pool** (`min_size=1, max_size=5`, `prepare_threshold=None`) is the ONLY pooler-specific surface. It reads `settings.database_url` and connects to whatever `DATABASE_URL` points at. Against a local `postgres:16` service on `localhost:5432` this Just Works — `prepare_threshold=None` is harmless on a non-pooled server (it only disables an optimization). **No pooler-specific assumption blocks CI.**

### Pooler flag (per the additional-context request)

The app normally connects to Supabase via the Supavisor pooler host on port **6543**. CI uses a plain `postgres:16` service on **5432**. This is fully supported:
- `bootstrap.py` and `supabase.py` both just consume `DATABASE_URL`; neither hardcodes a pooler host or port.
- `prepare_threshold=None` (the one pooler-motivated setting, `supabase.py:59`) is a no-op-but-harmless against vanilla Postgres.
- **Flag for the planner:** set `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres` (or a dedicated db) — a plain `postgresql://` URL, NOT a `...pooler.supabase.com:6543` URL. That is the only pooler-vs-local difference, and it is purely a connection-string value.

### Required env for the CI step (verified against the race tests + conftest)

| Env var | Why | Source |
|---------|-----|--------|
| `DATABASE_URL` | Two-factor DB guard `_HAS_DB` (`conftest.py:48`); pool + bootstrap target | `conftest.py:48`, `test_webhook_dedup_race.py:33` |
| `ALLOW_DB_RESET=1` | Two-factor guard `_HAS_RESET` (`conftest.py:49`) — required by `seeded_db` fixture and every `_SKIP_LIVE_DB` test | `conftest.py:49`, `test_atomic_persist.py:41` |
| `ALLOW_UNSIGNED_FIXTURES=true` | Webhook POSTs 400 on signature rejection without it — the dedup + approval surfaces post to `/webhook/inbound` and `/approve` via TestClient | `test_webhook_dedup_race.py:43` (set in-test via monkeypatch; ALSO safe to set as a job-level env) |

**Note on `ALLOW_UNSIGNED_FIXTURES`:** `test_webhook_dedup_race.py` sets this *inside the test* via `monkeypatch.setenv` (line 43) because pytest does not share monkeypatch state across modules. The planner should have the capstone module do the same (per-test `monkeypatch.setenv`), NOT rely solely on the job env — this keeps the module self-contained and runnable locally.

### Ready-to-adapt CI sketch

```yaml
name: concurrency-proof

on:
  push:
    branches: ["master"]
  workflow_dispatch:

jobs:
  proof:
    name: "Concurrency invariants proof (real Postgres)"
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: postgres
        ports:
          - 5432:5432
        # Wait until Postgres accepts connections before any step runs.
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      # Plain local Postgres — NOT a Supavisor pooler URL. prepare_threshold=None
      # in app/db/supabase.py is a harmless no-op against a vanilla server.
      DATABASE_URL: "postgresql://postgres:postgres@localhost:5432/postgres"
      ALLOW_DB_RESET: "1"
      ALLOW_UNSIGNED_FIXTURES: "true"
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Set up uv + Python 3.12
        uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.12"
      - name: Install deps (all groups)
        run: uv sync
      - name: Apply schema to ephemeral Postgres
        run: uv run python -m app.db.bootstrap --reset
      - name: Run the concurrency proof
        # -m integration selects the capstone (default suite skips it). The proof
        # module seeds its own rows via repo.* / the seeded_db fixture.
        run: uv run pytest tests/test_concurrency_proof.py -m integration -v
```

**Confidence: HIGH.** `services: postgres` with a `pg_isready` health check is the canonical GitHub Actions pattern; the bootstrap/DATABASE_URL path is verified vanilla-Postgres-clean.

**One planner decision:** whether the proof module uses the `seeded_db` fixture (`conftest.py:58`, which itself calls `bootstrap(reset=True)` + `seed()`) or the CI runs bootstrap as a separate step. **Recommendation:** let the CI step run `bootstrap --reset` for schema, and let each test use the `seeded_db` fixture for seed data (matching `test_atomic_persist.py` / `test_stuck_run_recovery.py`, which depend on the Coastal/business-2 seed for `business_id` and roster). `seeded_db` is module-scoped so it seeds once. The explicit bootstrap step is belt-and-suspenders (ensures schema exists even if a test doesn't request `seeded_db`).

---

## Mechanic 2 — TestClient under OS threads + real Postgres (connection behavior + stubbing seams)

**Recommendation:** Reuse `test_webhook_dedup_race.py`'s exact structure. For each surface: `monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")` → `get_settings.cache_clear()` → stub the pipeline/LLM/send seams → construct `TestClient(app_main.app)` → fire N threads (or a `ThreadPoolExecutor`) each POSTing → join → assert on collected responses AND on persisted DB state.

### The BackgroundTasks caveat (re-confirmed, load-bearing)

**TestClient runs FastAPI BackgroundTasks SYNCHRONOUSLY.** Verified in `test_webhook_dedup_race.py:49-59` (the module comment) and by tracing the routes:
- Webhook `new_run` outcome: `background_tasks.add_task(_run_pipeline, run_id)` at `app/main.py:539` — under TestClient this runs the REAL orchestrator (real LLM calls) inline unless `_run_pipeline` is stubbed.
- Approve route: `_deliver(run_id, run)` is called **synchronously inside the route** (`app/main.py:764`), NOT via BackgroundTasks — so the winning approve triggers real `send_outbound` immediately unless `_deliver`/`send_outbound` is stubbed.

### Exact stubbing seams (cite file:line)

| Surface | Seam to stub | Where | Why |
|---------|-------------|-------|-----|
| Dedup | `app.main._run_pipeline` → no-op appending to a list | `main.py:539` (add_task), stubbed at `test_webhook_dedup_race.py:57-59` | Winner's BackgroundTask would run real orchestrator (real DeepSeek/Kimi extraction). Stub captures the call so you can assert exactly-one `_run_pipeline`. |
| Approval (HTTP `/approve`) | `app.pipeline.orchestrator._deliver` (imported inside route at `main.py:753`) → no-op appending to a list | `main.py:764` | Winning approve calls `_deliver` synchronously → real `send_outbound` (real Resend + threading). Stubbing `_deliver` to a no-op isolates the CAS race. **Recommended primary seam.** |
| Approval (alt) | `resend.Emails.send` + `app.llm.client.OpenAI` | `conftest.py:1005` shows the resend no-op pattern; `test_atomic_persist.py:194` shows `LiveMockOpenAI` | If you want `_deliver` to actually run (to prove the winner delivers exactly once), stub only the external calls. **NOT recommended for the pure race assertion** — stub `_deliver` wholesale (simpler, matches D-10-06 "the race, not a live side effect"). |
| Concurrent runs | `app.main._run_pipeline` (same as dedup) | `main.py:539` | Same — each distinct-message_id POST schedules a pipeline; stub it so the assertion is purely the DB run-row invariant. |

### LLM/provider seams that flake if unstubbed (`.env` carries LIVE keys — MEMORY: execute-phase-integration-hazards)

- `app.llm.client.OpenAI` — extraction (DeepSeek) + drafting/suggestion (Kimi). Stub pattern: `monkeypatch.setattr("app.llm.client.OpenAI", LiveMockOpenAI)` where `LiveMockOpenAI` is a scriptable stand-in (`test_atomic_persist.py:194`; full class at `test_atomic_persist.py:62-90`). For Phase 10, stubbing `_run_pipeline`/`_deliver` wholesale means the LLM is never reached — **preferred**, since the proof asserts DB invariants, not extraction.
- `resend.Emails.send` — outbound provider. No-op via `monkeypatch.setattr(resend.Emails, "send", staticmethod(lambda params: {"id": "fake"}))` (`conftest.py:1005-1010`).
- **Belt-and-suspenders:** even with `_deliver`/`_run_pipeline` stubbed, add the `resend.Emails.send` no-op as a safety net (it's cheap and guarantees no accidental live send if a code path changes).

### Thread pattern (verified template)

`test_webhook_dedup_race.py:76-89` uses raw `threading.Thread` with a `threading.Lock`-guarded results list:
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
**Recommendation:** generalize to `ThreadPoolExecutor(max_workers=N)` + `list(executor.map(...))` for N>2 (cleaner than manual thread lists), or keep raw threads to match the proven template exactly. Either is fine per D-10-05. The results-collection lock is only needed with raw threads appending to a shared list; `executor.map` returns an ordered result list with no manual locking.

**Confidence: HIGH** — every seam verified in live source.

---

## Mechanic 3 — Pool-budget vs. N (the D-10-07 constraint, resolved)

**Recommendation: N=8, drive everything through the app pool via TestClient — do NOT open per-thread raw `psycopg.connect` connections.** The pool (`min=1, max=5`) does NOT get exhausted, because pooled connections are held only for the duration of a single short transaction, not the thread's lifetime.

### Evidence — the proven pattern does NOT hold connections per-thread

- `test_webhook_dedup_race.py` fires 2 threads through `TestClient`, and each thread's request touches the app pool ONLY during the ingest transaction (`main.py` webhook route: `with repo.get_connection() as conn: with conn.transaction(): ...`). The connection is **returned to the pool on `with` exit** (`supabase.py:78`, `pool.connection()` context manager). It is NOT held while the thread does anything else. **No test in the repo opens a raw `psycopg.connect` per thread** (verified: only `conftest.py` and `test_webhook_dedup_race.py` reference `psycopg.connect`/`threading`, and the race test uses TestClient, not raw connections).
- `supabase.py:52-63` — `max_size=5`, plus `timeout=5` (5-second wait timeout). If N transactions genuinely contended for the pool *simultaneously* and it saturated, callers would wait up to 5s, not fail — but they don't saturate because each transaction is sub-millisecond (`insert_inbound_email` is one INSERT; `claim_status` is one UPDATE).
- The dedup + approval races are resolved by Postgres MVCC (the `uq_message_id` UNIQUE index blocking; the conditional UPDATE...RETURNING), NOT by holding connections open — so even N=8 threads each grabbing a pool connection for one INSERT/UPDATE never needs more than a handful of connections in flight at once.

### The safe N ceiling

- **N=8 is safe and recommended.** It genuinely interleaves (well above the N≥2 minimum where the invariant already holds), is fast, and stays comfortably inside the pool's serving capacity (transactions are so short that peak concurrent pool checkouts stay ≤5 even at N=8; any brief overflow waits ≤5s, well within CI limits — but in practice it won't overflow).
- **Do NOT go above ~10** (D-10-07): larger N is theater and risks the 5s pool-wait timeout showing as flakiness if the runner is slow.
- **Alternative (NOT recommended):** open per-thread raw `psycopg.connect(DATABASE_URL, prepare_threshold=None)` connections OUTSIDE the app pool. This is a legitimate mechanism (D-10-07 permits it) and sidesteps the pool entirely, but it does NOT match any existing proven test, adds connection-lifecycle boilerplate, and is unnecessary given the app-pool path is proven at the transaction granularity that matters. **Use the app pool via TestClient.**

**Confidence: HIGH.** The pool-return-on-transaction-exit behavior is the definitive answer to "does N threads exhaust the pool": no, because connections are held per-transaction, not per-thread.

---

## Mechanic 4 — The three surfaces' exact seams (verified against live source)

### Surface A — Dedup (exactly-one-run per message_id)

- **Seam:** `app/db/repo.py:171 insert_inbound_email` → SQL at `repo.py:193-201`: `INSERT ... ON CONFLICT (message_id) DO NOTHING RETURNING id`. Returns `(None, False)` on conflict (`repo.py:213-214`). Then `repo.py:324 create_run` inserts the `payroll_runs` row (`repo.py:344-359`).
- **The whole ingest is ONE transaction** committed before `background_tasks.add_task` (D-9-09). Loser lookup: `repo.py:280 find_run_by_message_id` joins `email_messages → payroll_runs` via `source_email_id`.
- **Assertion:** fire N duplicate POSTs with ONE shared `message_id` (template: `test_webhook_dedup_race.py:63-89`); assert `len({r["run_id"] for r in results if r.get("run_id")}) == 1` AND `len(pipeline_calls) == 1` (exactly one winner scheduled the pipeline — `test_webhook_dedup_race.py:92-108`). Optionally add a direct DB assertion: `SELECT count(*) FROM payroll_runs WHERE source_email_id = (SELECT id FROM email_messages WHERE message_id = %s)` equals 1.

### Surface B — Approval CAS via the real HTTP route (exactly-one True)

- **Seam:** `app/main.py:738 @app.post("/runs/{run_id}/approve")` → `repo.claim_status(run_id, AWAITING_APPROVAL, APPROVED)` at `main.py:755` → on `claimed`, calls `_deliver` synchronously at `main.py:764`.
- **CAS primitive:** `repo.py:450 claim_status` → SQL at `repo.py:471-473`: `UPDATE payroll_runs SET status=%s ... WHERE id=%s AND status=%s RETURNING id`. `row is not None` → True (`repo.py:475`). Only one concurrent caller gets the row back.
- **Setup:** create ONE run and drive it to `AWAITING_APPROVAL` (the CAS's `expected` status). Cleanest path: seed a run, then `repo.set_status(run_id, RunStatus.AWAITING_APPROVAL)` directly (matches how `test_atomic_persist.py` seeds live runs via `_seed_live_run` at `test_atomic_persist.py:120-133`, then manipulates status).
- **Stub:** `app.pipeline.orchestrator._deliver` → no-op appending run_id to a list (so you can assert `len(deliver_calls) == 1`). Because `_deliver` is imported inside the route (`main.py:753`), patch it on the `orchestrator` module: `monkeypatch.setattr("app.pipeline.orchestrator._deliver", lambda rid, run: deliver_calls.append(rid))`.
- **Assertion:** fire N concurrent `client.post(f"/runs/{run_id}/approve")`; assert exactly one 303 redirect corresponds to a winning claim. Since all N return 303 (the route always 303s — `main.py:783`), assert on the DB (`SELECT status FROM payroll_runs WHERE id=%s` == 'approved', and it was 'approved' exactly once) AND on `len(deliver_calls) == 1`. **`deliver_calls == 1` is the cleanest exactly-once signal** — it proves the route-level "no double-delivery above the CAS" that D-10-06 exists to catch.

### Surface C — Concurrent distinct runs (no lost update, no half-write)

- **Recommendation (resolving the D-10 discretion point):** use **distinct parallel `message_id`s** (throughput/atomicity-under-load), NOT the dedup harness. Fire N webhook POSTs each with a UNIQUE `message_id` (and unique `id`). Assert exactly N runs are created (no lost update — every distinct ingest produced its own run) AND every run row is well-formed (no half-write).
- **No-half-write seam:** the run-creation ingest is one transaction (`create_run` + `insert_inbound_email` commit together, D-9-09), so a run row can never exist without its source email row. For the deeper "persist sequence is atomic" invariant, the canonical mechanic is `test_atomic_persist.py:170 test_process_branch_crash_leaves_run_unadvanced` — it fault-injects `replace_line_items` to raise mid-`_run_stages` and asserts status unchanged + `extracted_data`/`decision`/`reconciliation` all still None (`test_atomic_persist.py:217-233`). **For Phase 10's concurrent-runs surface, the assertion is simpler:** with `_run_pipeline` stubbed to no-op, the runs stay at `received`; assert all N rows exist at a consistent status with no orphaned/partial rows. The half-write *fault-injection* proof already lives in `test_atomic_persist.py` (D-10-01: consolidate the invariant, keep the focused unit).
- **Cleanest "no lost update" assertion:** `SELECT count(*) FROM payroll_runs WHERE source_email_id IN (<the N email ids>)` == N, with each distinct message_id producing exactly one run. This proves N concurrent ingests neither dropped a run (lost update) nor duplicated one.

**Confidence: HIGH** — all seams verified at the cited line numbers.

---

## Mechanic 5 — Phase 11 scope check (NEW contended write path?)

**Finding: NO new contended status-write path was introduced by Phase 11. The two sanctioned writers hold. No new proof surface is warranted.**

### Evidence (verified 2026-07-07)

- **All status transitions still route through exactly `set_status` (unguarded) and `claim_status` (CAS).** Grep for status writers outside `repo.py` returns ONLY `claim_status`/`set_status` calls in `app/main.py` and `app/pipeline/orchestrator.py` — no third writer, no raw `UPDATE payroll_runs SET status` anywhere outside `repo.py` and `schema.sql`'s one-shot migration blocks.
- **Phase 11's new data-layer writes are NOT status writes and NOT contended gates.** `set_clarification_round` (`orchestrator.py:1312/1473/1499`) and `clear_reply_context` (`main.py:1046`) write round/context columns, not `status`. They execute INSIDE an existing owned transaction (alongside `set_status`) or as a committed single statement — they do not introduce a new race on a money-moving decision.
- **Phase 11's `reply_epoch` mechanism (GAP-2/GAP-3)** is a monotonic counter bumped inside `clear_reply_context`'s single statement — it scopes stale replies out, it is not a contended CAS gate. No two actors race to claim it.
- **The Phase 11 auto-resume path** (`main.py:1323-1324` sweep + `find_stranded_unconsumed_replies`) reuses the SAME `claim_status(AWAITING_REPLY → EXTRACTING)` CAS already covered by the resume machinery — its race-safety is the existing `claim_status` property, already in Phase 10's charter (the approval surface proves the identical CAS primitive).

### Disposition

**No scope question to raise.** Phase 11 added round/epoch bookkeeping but no new sanctioned status writer and no new contended money-moving gate beyond the `claim_status` CAS the proof already exercises. The proof's charter (the Phase-9 data-integrity invariants) fully covers the concurrency surface. **Do NOT fold any Phase 11 round-logic surface into the proof.** (If the planner disagrees after re-tracing, raise it as a single flagged question per the scope constraint — do not silently add a fourth surface.)

**Confidence: HIGH.**

---

## Recommended Module Structure

```
tests/test_concurrency_proof.py    # NEW — the capstone (D-10-01)
  module docstring: the proof narrative (3 surfaces, 4 invariants, the crash/race windows)
  _seed_live_run(...)              # adapted from test_atomic_persist.py:120
  _stub_pipeline_and_send(mp)      # shared: no-op _run_pipeline + _deliver + resend.send
  test_dedup_exactly_one_run_per_message_id        # Surface A — no duplicate run
  test_concurrent_approvals_exactly_one_wins       # Surface B — no double-approval (via HTTP /approve)
  test_concurrent_distinct_runs_no_lost_update     # Surface C — no lost update + no half-write

.github/workflows/concurrency-proof.yml    # NEW — makes it standing evidence (D-10-03)
```

Each test carries `@pytest.mark.integration` + the two-factor guard (`if not os.environ.get("DATABASE_URL"): pytest.skip(...)`, matching `test_webhook_dedup_race.py:33`). The four invariants map to three test functions because "no lost update" and "no half-write" are both asserted by Surface C.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Thread + TestClient + real-PG harness | A new abstraction/fixture | `test_webhook_dedup_race.py`'s proven pattern (thread → TestClient → collect responses under lock) | Already handles the env gotchas (unsigned fixtures, cache_clear, BackgroundTasks-sync). Reinventing it re-hits every gotcha. |
| Live-DB run setup | Ad-hoc INSERTs | `test_atomic_persist.py:120 _seed_live_run` (insert_inbound_email + create_run via repo.*) | Proven to produce a valid run row against the seeded schema; uses the real repo helpers. |
| Two-factor DB skip guard | New skip logic | `conftest.py:52 _SKIP_LIVE_DB` + the inline `DATABASE_URL` check | The universal shape; keeps the default suite DB-free and green. |
| LLM/provider isolation | Partial stubs | Stub `_run_pipeline`/`_deliver` wholesale + `resend.Emails.send` no-op | Proof asserts DB invariants, not extraction/delivery — wholesale stubbing is simpler and matches D-10-06. |
| Schema apply in CI | Hand-written SQL step | `python -m app.db.bootstrap --reset` | The idempotent schema source of truth; already handles the D-21-06 dead-table migrations. |

## Common Pitfalls

### Pitfall 1: Unstubbed BackgroundTask hits live LLM/Resend and flakes
**What goes wrong:** TestClient runs BackgroundTasks + the synchronous `_deliver` inline; `.env` has LIVE keys → real DeepSeek/Kimi/Resend calls → slow, flaky, credit-burning.
**How to avoid:** stub `app.main._run_pipeline` (dedup + concurrent-runs surfaces) and `app.pipeline.orchestrator._deliver` (approval surface) to no-ops BEFORE firing threads. Add `resend.Emails.send` no-op as a safety net.
**Warning signs:** test takes >2s per surface; network calls in logs; intermittent failures.

### Pitfall 2: Missing `ALLOW_UNSIGNED_FIXTURES` → every POST 400s before the race
**What goes wrong:** the webhook rejects unsigned fixtures with 400 before reaching dedup/CAS logic; the race is never exercised, and the assertion may falsely pass (no runs created at all).
**How to avoid:** `monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")` per test (`test_webhook_dedup_race.py:43`) AND set it job-level in CI. Always `get_settings.cache_clear()` after setting env (`test_webhook_dedup_race.py:38`).
**Warning signs:** all responses are 400; zero runs in the DB post-test.

### Pitfall 3: Cross-module monkeypatch state assumption
**What goes wrong:** assuming the capstone inherits `test_webhook.py`'s client-fixture env — pytest does NOT share monkeypatch state across modules.
**How to avoid:** the capstone sets its own env (`ALLOW_UNSIGNED_FIXTURES`) and builds its own `TestClient` (`test_webhook_dedup_race.py:39-61` documents this exact trap).

### Pitfall 4: Pooler URL in CI
**What goes wrong:** using a `...pooler.supabase.com:6543` URL against the local service container → connection failure.
**How to avoid:** `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres` — a plain local URL. `prepare_threshold=None` remains harmless.

### Pitfall 5: Race not asserted at the DB, only at the response
**What goes wrong:** the approve route always 303s regardless of claim outcome (`main.py:783`), so counting 303s proves nothing.
**How to avoid:** assert on the winning side effect — `len(deliver_calls) == 1` and the DB row's terminal status — not on HTTP status codes.

## Validation Architecture

> `nyquist_validation: true` (verified in `.planning/config.json`) — section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (dev group, `pyproject.toml` `[dependency-groups].dev`) |
| Config file | `pyproject.toml` (markers: `integration`); `conftest.py` (fixtures + two-factor guard) |
| Quick run command | `uv run pytest -m 'not integration'` (hermetic, DB-free — the capstone is EXCLUDED here by design, D-10-04) |
| Full suite command | `uv run pytest` (includes integration when DATABASE_URL + ALLOW_DB_RESET=1 present) |
| Proof-only command | `DATABASE_URL=... ALLOW_DB_RESET=1 ALLOW_UNSIGNED_FIXTURES=true uv run pytest tests/test_concurrency_proof.py -m integration` |

### The Four Invariants → Concrete Asserted Conditions (Dimension-8 map)

| Invariant | Surface | Test | Concrete asserted condition |
|-----------|---------|------|------------------------------|
| No duplicate run per message_id | A (dedup) | `test_dedup_exactly_one_run_per_message_id` | `len({r["run_id"] for r in results if r.get("run_id")}) == 1` AND exactly one `_run_pipeline` call AND `count(payroll_runs WHERE source_email_id=...) == 1` |
| No double-approval | B (approval via HTTP `/approve`) | `test_concurrent_approvals_exactly_one_wins` | `len(deliver_calls) == 1` (exactly one `_deliver` fired above the CAS) AND run status == 'approved' (reached exactly once) |
| No lost update | C (concurrent distinct runs) | `test_concurrent_distinct_runs_no_lost_update` | N distinct message_ids → `count(payroll_runs) == N`; every distinct ingest produced exactly one run (none dropped) |
| No half-written state | C (concurrent distinct runs) | same test | every run row exists WITH its source email row (ingest txn atomicity, D-9-09); no orphaned/partial rows — assert each run has non-null `source_email_id` and a matching `email_messages` row. (Fault-injection half-write proof stays in `test_atomic_persist.py` per D-10-01.) |

### Sampling Rate
- **Per task commit:** `uv run pytest -m 'not integration'` (fast, DB-free — the capstone is skipped locally).
- **Per wave merge / phase gate:** the `concurrency-proof.yml` CI job runs the proof against the ephemeral Postgres — green = standing evidence.

### Wave 0 Gaps
- [ ] `tests/test_concurrency_proof.py` — NEW capstone module covering OPS2-03 (all four invariants).
- [ ] `.github/workflows/concurrency-proof.yml` — NEW CI job with `services: postgres:16` + health check.
- [ ] (No framework install gap — pytest + the two-factor guard + `integration` marker + `seeded_db` fixture already exist in `conftest.py`.)

## Security Domain

> `security_enforcement: true` (verified). This is a **test-only phase** — no new production endpoints, inputs, auth surfaces, or crypto. The proof exercises EXISTING seams; it introduces no new attack surface.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No new auth surface; the proof uses the existing single-operator model. |
| V3 Session Management | no | No sessions introduced. |
| V4 Access Control | no (indirect) | The approve/webhook routes' existing access controls (`ALLOW_UNSIGNED_FIXTURES` gates signature verification; sender revalidation FIX-5) are unchanged — the proof deliberately sets `ALLOW_UNSIGNED_FIXTURES=true` in the TEST context only (never production). |
| V5 Input Validation | no | The proof posts fixture payloads; validation logic is unchanged. |
| V6 Cryptography | no | No crypto touched. |

### CI-specific security notes
- The service-container password (`POSTGRES_PASSWORD: postgres`) is an ephemeral, network-isolated CI container — not a secret. No `secrets.*` reference is needed (unlike `eval.yml`'s `EXTRACTION_API_KEY` or `keepalive.yml`'s `RENDER_URL`). **Do NOT** point CI at the real Supabase `DATABASE_URL` — the proof runs `bootstrap --reset` (destructive) and must only ever touch the ephemeral container.
- `ALLOW_UNSIGNED_FIXTURES=true` and `ALLOW_DB_RESET=1` are test/CI-only two-factor guards — their presence in this workflow is correct and does not leak into any deployed environment (Render sets neither).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Scattered per-surface race tests (`test_webhook_dedup_race.py`, `test_claim_status.py` integration stub, `test_atomic_persist.py`) | ONE consolidated capstone proof + CI service container | Phase 10 (this phase) | A single pointable artifact (D-10-01); the invariants become standing CI evidence instead of skip-guarded local-only tests. |
| Approval race proven only at the `claim_status` primitive (`test_claim_status.py:159`, currently a stub) | Approval race proven through the real HTTP `/approve` route | Phase 10 (D-10-06) | Catches route-level regressions above the CAS (route → CAS → `_deliver`). |

**Deprecated/outdated:**
- `test_claim_status.py:159 test_claim_status_concurrent_calls_exactly_one_true` is currently a **skipped stub** (`pytest.skip("Integration test stub — full impl in Wave 1...")` at line 176). Phase 10's approval surface is the real implementation of this invariant, lifted to the HTTP route. Optional backfill of the primitive-level test into `test_claim_status.py` is Claude's discretion (D-10, capstone is the required home).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `postgres:16` is close enough to Supabase's Postgres line for the vanilla schema; no version-specific DDL | Mechanic 1 | LOW — `schema.sql` uses only standard DDL; `postgres:15` or `:16` both work. Verified no Supabase extensions referenced. If a DDL feature needs a specific version, bootstrap would error loudly in CI (caught immediately). |

**Note:** A1 is the only assumption; everything else is verified against live source at cited line numbers. All package/tool facts (pytest, uv, actions/checkout@v4, astral-sh/setup-uv@v5) are confirmed present in the existing `eval.yml`/`pyproject.toml`.

## Open Questions

1. **Does the concurrent-runs surface (C) need its own fault-injection half-write proof, or does referencing `test_atomic_persist.py` satisfy "no half-write"?**
   - What we know: D-10-01 says consolidate invariants but keep focused units; `test_atomic_persist.py:170` already fault-injects and asserts wholly-un-advanced.
   - What's unclear: whether the capstone should REPEAT a fault-injection or assert the lighter "all N rows well-formed, none orphaned."
   - Recommendation: capstone asserts the lighter "no orphaned/partial rows under concurrent distinct ingests"; the fault-injection half-write proof stays in `test_atomic_persist.py` (avoids duplicating the monkeypatch-crash machinery). Planner confirms.

2. **Backfill the primitive-level `test_claim_status.py` stub, or leave it as a stub?**
   - Recommendation: the capstone's HTTP-route approval surface is the required home (D-10-06). Backfilling the primitive stub is optional and trivially cheap (a few lines mirroring the capstone's thread pattern at the `claim_status` level). Planner's call per D-10 discretion; not required for OPS2-03.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | env + deps (all steps) | ✓ | pinned via `astral-sh/setup-uv@v5` | — |
| Python 3.12 | runtime | ✓ | 3.12 (`.python-version`, `setup-uv` input) | — |
| pytest | test runner | ✓ | `pyproject.toml` dev group | — |
| Postgres (CI) | the proof's real DB | ✓ (CI service container) | `postgres:16` image | — |
| Postgres (local repro) | documented local run | user-provided | any 15/16 | Docker `postgres:16`, documented in module docstring (D-10-04) |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** local Postgres for local reproduction — Docker `postgres` container documented per D-10-04 (CI is the required run path, D-10-03).

## Sources

### Primary (HIGH confidence) — live source in THIS repo, verified 2026-07-07
- `tests/test_webhook_dedup_race.py` — canonical thread+TestClient+real-PG template; env/stubbing gotchas.
- `tests/test_claim_status.py:159` — CAS approval-race stub (lifted to HTTP route in Phase 10).
- `tests/test_atomic_persist.py:120,168` — `_seed_live_run` live-run setup; fault-injection half-write proof.
- `tests/conftest.py:48-70` — two-factor DB guard, `_SKIP_LIVE_DB`, `seeded_db` fixture, resend no-op pattern.
- `app/main.py:539,738,755,764,783` — webhook enqueue, `/approve` route, `claim_status` call, synchronous `_deliver`, always-303.
- `app/db/repo.py:171,280,324,433,450,487` — `insert_inbound_email` (ON CONFLICT), `find_run_by_message_id`, `create_run`, `set_status`, `claim_status`, `sweep_stranded_runs`.
- `app/db/supabase.py:52-63` — pool `min=1/max=5`, `prepare_threshold=None`, `timeout=5`; per-transaction connection lifecycle.
- `app/db/bootstrap.py:96,138` — schema apply via plain `psycopg.connect`; `python -m app.db.bootstrap [--reset]`.
- `app/db/schema.sql` — verified vanilla-Postgres-clean (no Supabase extensions/roles/`gen_random_uuid`).
- `.github/workflows/eval.yml:20-31` — house CI shape (uv + 3.12 + `uv sync` + `uv run` + env).
- Phase 11 status-writer audit — grep confirmed only `set_status`/`claim_status` write `payroll_runs.status` outside `repo.py`.

### Secondary (MEDIUM confidence)
- GitHub Actions `services: postgres` + `pg_isready` health-check pattern (canonical, widely documented) — the sketch above follows the standard form; verify the exact `options:` syntax against the current Actions docs at plan time if desired.

## Metadata

**Confidence breakdown:**
- CI service container (Mechanic 1): HIGH — bootstrap/DATABASE_URL path verified vanilla-Postgres-clean; only the `services:` YAML syntax is convention (MEDIUM, easily verified).
- TestClient + threads + stubbing (Mechanic 2): HIGH — every seam cited at file:line.
- Pool-budget vs N (Mechanic 3): HIGH — per-transaction connection lifecycle is the definitive answer.
- Three surfaces' seams (Mechanic 4): HIGH — all cited at file:line.
- Phase 11 scope check (Mechanic 5): HIGH — grep-verified no new sanctioned status writer.

**Research date:** 2026-07-07
**Valid until:** ~2026-08-07 (stable — internal repo source; the only external-facing element is the GitHub Actions `services:` YAML, which is long-stable)
