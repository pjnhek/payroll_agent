---
phase: 16
slug: queue-substrate-unblocked-webhook
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-14
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `16-RESEARCH.md` § Validation Architecture. Every proof below names
> the **falsifying mutation** that must turn it red — a proof that survives its own
> mutation is vacuous and does not count.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (with the `integration` marker registered in `pyproject.toml` `[tool.pytest.ini_options]`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (markers only; no separate `pytest.ini`) |
| **Quick run command** | `uv run pytest -q` |
| **Full suite command** | `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres ALLOW_DB_RESET=1 ALLOW_UNSIGNED_FIXTURES=true uv run pytest tests/ -m integration -v` |
| **Estimated runtime** | ~60s hermetic; ~90s live-DB |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q` (hermetic — covers Proofs 1 and 5, plus offline SQL-shape assertions for `enqueue_job`/`claim_job` via the existing `FakeConnection` pattern)
- **After every plan wave:** Run the full live-DB suite (Proofs 2, 3, 4)
- **Before `/gsd-verify-work`:** Both hermetic and live-DB suites must be green
- **Max feedback latency:** 90 seconds

**Ordering constraint (load-bearing):** the D-04 generalization of
`.github/workflows/concurrency-proof.yml` (collection over `pytest tests/ -m integration`
instead of the hard-coded 2-file list) must land **before** any new `@pytest.mark.integration`
file is written — otherwise the new proofs skip silently and forever, which is the exact
failure mode that workflow's own comment (`:65-68`) warns about.

---

## Per-Task Verification Map

> Task IDs are filled in by the planner. Each row's proof must name its falsifying mutation.

| Proof | Criterion | Requirement | Needs live DB? | Test Type | Automated Command | Falsifying mutation (must turn it RED) | Status |
|-------|-----------|-------------|----------------|-----------|-------------------|----------------------------------------|--------|
| 1 | #1 webhook non-blocking | QUEUE-01 | No | `httpx.AsyncClient` + `ASGITransport` | `uv run pytest tests/test_webhook_unblocked.py -q` | Revert the route to call the blocking Resend fetch directly (no `run_in_threadpool`) → wall-clock must go ≈2× | ⬜ pending |
| 2 | #2 retrigger survives worker death | QUEUE-02 | **Yes** | `@pytest.mark.integration` | `uv run pytest tests/test_queue_durability.py -m integration` | Remove `OR (state='leased' AND leased_until < now())` from the claim SQL → job must never be reclaimed | ⬜ pending |
| 3 | #3 expired lease reclaimed; zombie fenced | QUEUE-03 | **Yes** | `@pytest.mark.integration` + `threading.Barrier` | `uv run pytest tests/test_queue_durability.py -m integration` | Remove the `AND lease_token = %(token)s` fence from **`fail_job`** (leaving it only on `complete_job`) → a zombie's failure-write must wrongly succeed | ⬜ pending |
| 4 | #4 graceful shutdown releases leases | QUEUE-03 | Yes (recommended) | `@pytest.mark.integration` | `uv run pytest tests/test_queue_durability.py -m integration` | A `worker.stop()` that joins threads but never calls the release SQL → row must stay `leased` with a future `leased_until` | ⬜ pending |
| 5 | #5 kind/status collision + JobKind drift guard | QUEUE-05 | No | unit, static-file parsing | `uv run pytest tests/test_job_kind_drift.py -q` | Add a `JobKind` member with no `CHECK` value, or no dispatch handler → each must independently fail | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Anti-vacuity constraint (D-06 / PROOF-05):** workers are OFF under test
(`WORKER_COUNT=0`); tests call `drain_once()` explicitly. Races drive the **sync repo
seam** under a `threading.Barrier` — never an HTTP route. The sole exception is Proof 1,
whose subject *is* the HTTP/event-loop layer; it must therefore use
`httpx.AsyncClient` + `ASGITransport` (real `asyncio.gather` concurrency), never
`TestClient`, whose synchronous portal serializes concurrent threads and produced this
repo's prior vacuous concurrency proof.

**Thread-count ceiling:** any barrier-held race is bounded by the app pool's
`max_size=5` (`app/db/supabase.py:60`) — matching the existing `N_INGEST` precedent in
`tests/test_concurrency_proof.py`.

---

## Wave 0 Requirements

- [ ] `.github/workflows/concurrency-proof.yml` — D-04 generalization, **landed first** (collection over `pytest tests/ -m integration`; keep the existing skip-guard at `:90-97`)
- [ ] `tests/test_webhook_unblocked.py` — Proof 1 (QUEUE-01), hermetic
- [ ] `tests/test_queue_durability.py` — Proofs 2, 3, 4 (QUEUE-02, QUEUE-03), `@pytest.mark.integration`
- [ ] `tests/test_job_kind_drift.py` — Proof 5 (QUEUE-05); needs a **new** inline-`CHECK (kind IN (...))` parser — `schema_introspect._do_block_check_values` only understands the DO-block migration pattern, which `jobs.kind` does not use
- [ ] `tests/test_status_drift.py` — D-05 rewrite: replace the magic-number guards with inventory-pinned assertions. Per research, only the `CREATE INDEX IF NOT EXISTS` count (`:329`) actually detonates; the `ANY (c.conkey)` count (`:228`) does **not** need bumping, because `jobs`' CHECKs are inline on a new table, not DO-block migrations
- [ ] `tests/conftest.py` `fake_repo` name tuple (`:994-1052`) — **unconditionally required**: every new `app/db/repo/jobs.py` function name must be added to both `InMemoryRepo` and this tuple. A missing name is *silently* never patched (falls through to the real DB, no error)
- [ ] `tests/test_threading.py` (`:340-354`, `:423-436`) — research **verified** these two tuples back `resume_pipeline`-only tests and need **no change** for Phase 16 as scoped. Re-grep once `retrigger()`'s refactor lands, in case new retrigger tests are added to this file and reuse a `_MiniStore` tuple

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live Render redeploy releases in-flight leases within seconds | QUEUE-03 | Requires a real Render deploy cycle; the automated Proof 4 covers the release *function*, not the platform's SIGTERM delivery | Deploy to Render with a job mid-lease; confirm the run resumes within seconds of the new instance booting, not after `LEASE_SECONDS` |

---

## Validation Sign-Off

- [ ] All 5 proofs exist and each has been run against its falsifying mutation (paste the red run)
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references above
- [ ] `concurrency-proof.yml` generalized BEFORE the first new integration file is committed
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
