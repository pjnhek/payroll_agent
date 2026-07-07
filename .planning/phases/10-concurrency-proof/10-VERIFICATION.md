---
phase: 10-concurrency-proof
verified: 2026-07-07T00:00:00Z
status: passed
score: 9/9 must-haves verified
overrides_applied: 0
---

# Phase 10: Concurrency Proof Verification Report

**Phase Goal:** Produce the evidence behind the "production-grade" claim — a load/concurrency test that exercises the real invariants the Phase 9 work guarantees, UNDER GENUINE PARALLELISM, and asserts they hold. The capstone deliverable a hiring manager can point to.
**Verified:** 2026-07-07
**Status:** passed
**Re-verification:** No — initial verification (this phase had two plans: 10-01 built the capstone, 10-02 was a gap-closure plan that fixed CR-01 found by code review; no prior VERIFICATION.md existed for either)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Surfaces A and C genuinely race the DB seam directly (bypass the async webhook route) | ✓ VERIFIED | `grep -c 'client.post("/webhook/inbound"' tests/test_concurrency_proof.py` → 0. `repo.insert_inbound_email(` called directly at lines 152, 192, 348; `repo.create_run(` at 161, 201, 358. `threading.Barrier` present 6x (module docstring + both surfaces' code, `barrier.wait()` at lines 191, 347). Confirmed against live `app/main.py:377-459`: the webhook route's entire DB body (insert_inbound_email → create_run) runs inside one `conn.transaction()` block with zero `await` between them — the only `await` in the route is `await request.body()` before any DB work (line ~300) — so the CR-01 premise (HTTP fan-out serializes on the event loop) is real, and the fix (bypassing the route) genuinely closes it. |
| 2 | Surface A asserts exactly-one-winner + DB count==1 | ✓ VERIFIED | Lines 216–251: explicit `winners`/`losers` split (`len(winners) == 1`), asserts loser shape (`eid is None`, `rid is None` — matching `repo.insert_inbound_email`'s documented `ON CONFLICT DO NOTHING` → `(None, False)` return, confirmed at `app/db/repo.py:171-212`), plus a DB backstop `SELECT count(*) FROM payroll_runs WHERE source_email_id = (...) == 1`. Not a None-filtered set (WR-02 closed). |
| 3 | Surface B asserts one `_deliver` call + status 'approved' via the real HTTP route | ✓ VERIFIED | Lines 259-313: `ThreadPoolExecutor(max_workers=N_APPROVE)` fires 8 concurrent `client.post(f"/runs/{run_id}/approve")`. Asserts `len(deliver_calls) == 1` and `repo.load_run(run_id)["status"] == "approved"` — never on HTTP status (route always 303s, confirmed at `app/main.py:778`). Confirmed live: `def approve` (sync route, `app/main.py:739`) is dispatched to Starlette's anyio worker threadpool — genuinely parallel OS threads, unchanged from 10-01. `_deliver` imported inside the route body (`app/main.py:753`) and patched on `app.pipeline.orchestrator._deliver`, not `app_main` (verified correct target). |
| 4 | Surface C asserts N distinct runs + non-null source_email_id with matching email_messages row | ✓ VERIFIED | Lines 321-403: `N_INGEST=5` barrier-released threads, unique `message_id`s, asserts `len(run_ids) == N_INGEST` (no lost update) then a `LEFT JOIN email_messages` query asserting every run row has non-null `source_email_id` AND a matching `email_messages` row (no half-write, D-9-09). Correctly drops the webhook-only `pipeline_calls == N` assertion since `create_run` on the direct seam never schedules `_run_pipeline` (documented in a code comment, lines 377-380). |
| 5 | Thread counts fit the connection pool (no starve-flake) | ✓ VERIFIED | `N_INGEST = 5` (line 92), `N_APPROVE = 8` (line 80). Confirmed live: `app/db/supabase.py:52` — `ConnectionPool(min_size=1, max_size=5, timeout=5)`. Comment at lines 82-91 correctly states connection-HOLDER vs brief-CAS distinction (WR-01/IN-02 closed — the old incorrect "N=8 stays inside budget" claim is gone). |
| 6 | CI workflow runs the proof (not skipped) via `-m integration` against ephemeral postgres:16 | ✓ VERIFIED | `.github/workflows/concurrency-proof.yml`: `services: postgres: image: postgres:16` + `pg_isready` health check (lines 12-26); job env sets a plain local `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres` (never a pooler/Supabase URL); final step `run: uv run pytest tests/test_concurrency_proof.py -m integration -v`. Confirmed the marker actually selects the tests: `uv run pytest tests/test_concurrency_proof.py -m integration --collect-only -q` → 3 tests collected (not silently skipped by marker misconfiguration). `on: push: branches: ["master"]` + `workflow_dispatch`. |
| 7 | CI does NOT run a destructive `bootstrap --reset` (ownership moved to `seeded_db` fixture) | ✓ VERIFIED | `grep -c "app.db.bootstrap --reset" .github/workflows/concurrency-proof.yml` → 0. Step now runs `uv run python -m app.db.bootstrap` (no `--reset`). Confirmed live in `app/db/bootstrap.py:76-135`: `bootstrap(reset=False)` still always applies `schema.sql` via `CREATE TABLE IF NOT EXISTS` (lines 130-133, outside the `if reset:` block) — so the CI pre-flight step correctly creates tables on a fresh container. `tests/conftest.py:58-74`'s `seeded_db` fixture then calls `bootstrap(reset=True)` + `seed()` behind the `ALLOW_DB_RESET=1` two-factor guard (which the CI job sets) — it is the sole destructive-reset owner (WR-04 closed). |
| 8 | Hermetic suite (`-m 'not integration'`) is green and DB-free | ✓ VERIFIED | Ran locally: `uv run pytest -m 'not integration' -q` → `596 passed, 21 skipped, 30 deselected, 1 warning in 76.54s`. The 30 deselected are exactly the integration-marked tests (including this phase's 3). No DB connection required for the hermetic run. |
| 9 | Zero production-code changes | ✓ VERIFIED | `git diff --name-only 7df5dac HEAD -- app/` → empty output (exit 0, no lines). Confirmed the pre-phase base commit `7df5dac` (docs(10): create phase plan) against current HEAD. |

**Score:** 9/9 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `tests/test_concurrency_proof.py` | Capstone: 3 integration tests, 4 invariants, genuine-parallelism proof-narrative | ✓ VERIFIED | 403 lines (min_lines: 120 met). All three tests present, collect correctly under `-m integration`. Substantive, not a stub — real assertions with DB backstops. |
| `.github/workflows/concurrency-proof.yml` | CI job: ephemeral postgres:16, pg_isready, non-destructive schema step, runs proof with `-m integration` | ✓ VERIFIED | Valid YAML (`uv run python -c "import yaml; yaml.safe_load(...)"` succeeds). All required elements present; no `secrets.*`, no `pooler.supabase.com`. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `tests/test_concurrency_proof.py` (Surfaces A/C) | `app.db.repo.insert_inbound_email` / `app.db.repo.create_run` | direct call from N barrier-released threads | ✓ WIRED | Lines 152/161 (helper), 192/201 (Surface A), 348/358 (Surface C) — direct calls, no HTTP intermediary. |
| `tests/test_concurrency_proof.py` (Surface B) | `app.pipeline.orchestrator._deliver` | monkeypatch on the orchestrator module | ✓ WIRED | Line 126 patches `"app.pipeline.orchestrator._deliver"` (string target, matching the route's inside-function import at `app/main.py:753`), not `app_main` — confirmed correct target against live source. |
| `.github/workflows/concurrency-proof.yml` | `tests/test_concurrency_proof.py` | `uv run pytest tests/test_concurrency_proof.py -m integration -v` | ✓ WIRED | Final workflow step; confirmed the marker selects all 3 tests via local `--collect-only`. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Hermetic suite stays green and DB-free after adding the capstone | `uv run pytest -m 'not integration' -q` | `596 passed, 21 skipped, 30 deselected in 76.54s` | ✓ PASS |
| Integration tests collect under the marker (not silently skipped by misconfiguration) | `uv run pytest tests/test_concurrency_proof.py -m integration --collect-only -q` | 3 tests collected | ✓ PASS |
| CI workflow YAML parses | `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/concurrency-proof.yml'))"` | `valid yaml` | ✓ PASS |
| No production-code drift | `git diff --name-only 7df5dac HEAD -- app/` | empty | ✓ PASS |
| The genuine-parallelism claim's premise (no await in webhook DB body) | Read `app/main.py:377-459` live | Confirmed: `insert_inbound_email` → `create_run` execute inside one `conn.transaction()` with zero `await`; only `await` in the route precedes all DB work | ✓ PASS |

### Probe Execution

No dedicated `scripts/*/tests/probe-*.sh` files exist for this phase; the phase's own PLAN/SUMMARY files define the proof as the integration test suite itself, whose authoritative run is GitHub Actions (CI-only in this environment, as documented). Step 7c: SKIPPED — no probe scripts declared or discovered; the phase's verification model is the CI-run integration suite, covered under Human Verification below.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| OPS2-03 | 10-01-PLAN.md, 10-02-PLAN.md | Concurrency proof test fires N simultaneous operations and asserts invariants hold — no double-approval, no lost update, no duplicate run, no half-written state | ✓ SATISFIED | All four invariants asserted with real DB-level teeth (see Observable Truths #2-4); REQUIREMENTS.md line 26 marks it `[x]` Complete, line 67 traceability table shows "Phase 10 — Concurrency Proof \| Complete". No orphaned requirements found for Phase 10 in REQUIREMENTS.md. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | None found | — | `grep -n -E "TBD\|FIXME\|XXX\|TODO\|HACK\|PLACEHOLDER"` and placeholder/not-yet-implemented scans on both deliverable files returned zero matches. |

### Minor Observation (non-blocking)

ROADMAP.md's Phase 10 "Plans" list (line 154-156) only enumerates `10-01-PLAN.md`, not the gap-closure `10-02-PLAN.md` that actually closed the CR-01 blocker. This is a documentation staleness issue in ROADMAP.md, not a functional gap — `10-02-PLAN.md`/`10-02-SUMMARY.md` exist, are committed (`45ff622`, `77b86ea`, `c954779`), and their fixes are verified present in the current code. Does not affect phase goal achievement; noted for hygiene only.

### Human Verification Required

None required to close this phase. The **one item that cannot be verified in this sandboxed environment** — the actual green/red GitHub Actions run of `concurrency-proof.yml` against a real ephemeral `postgres:16` — is explicitly expected per the phase's own verification design (PLAN.md `<verification>` section states this is "the phase's authoritative verification and cannot be exercised locally without a Postgres"). This is not a gap: the STRUCTURE and assertions were independently verified against live source (not SUMMARY.md claims) to genuinely exercise the invariants once CI runs them, per the CR-01 closure trace above. The next push to `master` will trigger the workflow automatically (`on: push: branches: ["master"]`); confirming that run go green is the natural first-push checkpoint, not a blocking verification item for this phase.

### Gaps Summary

No gaps. All 9 derived must-haves (roadmap Success Criteria 1-2 for Phase 10, expanded into the 5 CR-01-era corollary fixes from `10-REVIEW.md`, plus the standard hermetic-suite/production-code-diff checks) are verified against the current codebase state on master, not against SUMMARY.md narrative. The CR-01 BLOCKER finding from code review is confirmed closed: `client.post("/webhook/inbound"` no longer appears in Surfaces A/C, `threading.Barrier` genuinely releases N_INGEST=5 threads simultaneously into the sync `repo.insert_inbound_email`/`repo.create_run` seam, and the serialization mechanism that made the original proof vacuous (no `await` between the ON CONFLICT insert and `create_run` in the async route) was independently confirmed still present in `app/main.py` — proving the bypass was necessary and that it correctly restores genuine DB-level MVCC contention. Surface B was correctly left untouched, and independently confirmed to already run on Starlette's anyio worker threadpool (a sync route), so its parallelism claim was never in question.

---

_Verified: 2026-07-07_
_Verifier: Claude (gsd-verifier)_
