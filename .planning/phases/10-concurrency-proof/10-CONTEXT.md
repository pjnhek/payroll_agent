# Phase 10: Concurrency Proof - Context

**Gathered:** 2026-07-07
**Status:** Ready for planning

<domain>
## Phase Boundary

The capstone evidence phase (OPS2-03). Phase 9 *established* the atomicity / dedup / recovery invariants; Phase 10 *proves* them under genuine parallelism, producing the single artifact a hiring manager can point to. **Test-only deliverable** — no production code change beyond what the proof exercises (if a real race-exposed gap surfaces, that is a Phase 9 bug to fix, not new capability here).

The proof fires N simultaneous operations across the three risk surfaces and asserts the four invariants hold, failing loudly if any is violated:

1. **Concurrent payroll runs** (many runs in flight at once — indexes + per-run atomicity hold under load).
2. **Duplicate webhook deliveries for one `message_id`** → exactly one run (DATA-02).
3. **Simultaneous approvals on a single run** → the `claim_status` CAS wins exactly once, no double-approval (DATA-01 / D-12).

Invariants asserted: **no double-approval, no lost update, no duplicate run per inbound `message_id`, no half-written run state.**

**Not in scope:** new run states or state-machine capabilities; any production-code hardening beyond fixing a genuine invariant violation the proof exposes (the D-9-13 "swept-but-alive `set_status` overwrite" guard-hardening stays deferred unless this proof shows the window matters in practice — Phase 9 deferred item); the clarify-round-machine surfaces from Phase 11 (this phase validates the Phase-9 data-integrity invariants, not Phase 11's round logic); any dashboard/UI work.

</domain>

<decisions>
## Implementation Decisions

### Deliverable shape
- **D-10-01 A NEW unified proof harness is the deliverable — one legible, hiring-manager-pointable artifact.** A single new test module (e.g. `tests/test_concurrency_proof.py`) fires ALL three surfaces under real parallelism and asserts ALL four invariants in one coherent capstone. It reuses the *mechanics* already proven in the scattered per-surface tests (`test_webhook_dedup_race.py`, `test_claim_status.py`, `test_atomic_persist.py`, `test_stuck_run_recovery.py`) but presents them as one story. The existing per-surface tests **stay** as focused units — Phase 10 does not delete or replace them; it consolidates their invariants into the capstone. (Rationale: ROADMAP frames this as "the capstone deliverable: the artifact a hiring manager can point to" — a single pointable module serves that better than a scattered set.)

### Artifact form
- **D-10-02 The test module IS the proof — no separate report to maintain.** Each of the four invariants is its own clearly-named test/assertion with an explanatory docstring stating the invariant AND the crash/race window it guards, in the same explain-the-why style the codebase already uses (mirrors the header docstrings in `test_webhook_dedup_race.py` and the D-9 seam comments). Reading the file — or scanning the CI test names — tells the whole story. No committed `PROOF.md` writeup that could drift from the tests. (If the writeup narrative is wanted for the recruiter README later, it lives in the project writeup, not as a phase artifact.)

### Run environment — the proof must actually RUN to be evidence
- **D-10-03 A GitHub Actions CI job runs the proof against an ephemeral Postgres on every push.** A skip-guarded test that never executes proves nothing; the credibility of "fails loudly as a genuine regression guard" depends on it actually running. The new workflow (e.g. `.github/workflows/concurrency-proof.yml`) spins up a service Postgres, applies the schema via the existing bootstrap, sets `DATABASE_URL` (+ the two-factor `ALLOW_DB_RESET=1` and any `ALLOW_UNSIGNED_FIXTURES` the race tests already require), and runs the proof module with `-m integration` (or an explicit selector) so it is NOT skipped. Green in CI = standing evidence; red = a caught regression. Follows the existing `eval.yml` CI pattern (repo already has `eval.yml` + `keepalive.yml`).
- **D-10-04 Local reproduction is documented, not required for the mocked suite.** The proof stays `@pytest.mark.integration` so the default hermetic `uv run pytest -m 'not integration'` suite is unaffected (stays green, fast, DB-free). The exact local invocation against a local/docker Postgres (`DATABASE_URL=… ALLOW_DB_RESET=1 uv run pytest tests/test_concurrency_proof.py`) is documented at the module docstring / phase writeup.

### Parallelism model
- **D-10-05 OS threads (e.g. `ThreadPoolExecutor`) against a real Postgres — reuse the proven pattern.** The contention is resolved in Postgres's MVCC, not in Python, so the GIL is irrelevant; multiprocessing would add fixture/connection-sharing complexity for no additional proof strength. This is exactly the pattern `test_webhook_dedup_race.py` and `test_claim_status.py`'s integration test already use — no new dependency, no new abstraction.

### Per-surface proof level
- **D-10-06 Prove "no double-approval" through the real HTTP `/runs/{run_id}/approve` route, not just the `claim_status` primitive.** Fire N concurrent POSTs to the real approve endpoint via `TestClient` and assert exactly one succeeds (CAS wins once) — this catches route-level regressions ABOVE the CAS (route → CAS → `_deliver`), where a real double-approval bug could still hide, whereas the existing `test_claim_status.py` integration test only races the CAS primitive. **The LLM draft/suggestion calls and the provider `send_outbound` MUST be stubbed** so the race — not a live side effect — is the only thing under test (mirror the `_run_pipeline` no-op stub `test_webhook_dedup_race.py` already applies; note TestClient runs BackgroundTasks synchronously, so the winning approve would otherwise trigger real delivery). The other two surfaces (dedup, concurrent runs) similarly stub the pipeline/LLM so the assertion is purely the DB invariant.

### Scale (N)
- **D-10-07 Small fixed N (~5–10), deterministic assertions.** Enough concurrent operations to genuinely interleave and expose a broken invariant; fast and non-flaky in CI. The invariant holds at any N≥2 (Postgres resolves it regardless of N), so a small N is not weaker proof — a large N (50–100) is theater that risks connection-pool exhaustion and CI flakiness. **Pool constraint the planner MUST respect:** the app pool is `min=1, max=5` (`app/db/supabase.py`) — the harness must not require more than ~5 *simultaneously-held* pooled connections, OR it must open its own threads' connections outside the app pool (the existing race tests open connections per-thread; the planner picks the mechanism). Assertions are deterministic: exactly-one-True across approve calls, exactly-one-run per `message_id`, no partial rows after any interleaving.

### Claude's Discretion
- Exact module name, test/function names, and how the three surfaces are organized within the module (one test each vs. a shared harness fixture).
- Exact N per surface within the ~5–10 band.
- Whether the "concurrent runs" surface asserts via distinct `message_id`s in parallel (throughput/atomicity-under-load) or reuses the dedup harness with distinct ids — planner traces the cleanest way to assert "no lost update" and "no half-write" under concurrent distinct runs.
- CI workflow specifics (Postgres service image/version, whether it reuses a bootstrap step, matrix vs. single job) — follow the `eval.yml` shape.
- Whether to add the missing HTTP-level approval-race coverage as a new test inside the capstone only, or also backfill `test_claim_status.py` (the capstone is the required home; backfill is optional if trivially cheap).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase definition + requirement
- `.planning/ROADMAP.md` — Phase 10 entry: goal ("the artifact a hiring manager can point to"), Success Criteria 1–2 (three surfaces under real parallelism; four invariants, fail loudly as a regression guard)
- `.planning/REQUIREMENTS.md` — OPS2-03 exact wording (line 26); dependency note "Phase 10 depends on Phase 9 — validates the atomicity/dedup/recovery invariants" (line 86)

### The invariants this phase proves (Phase 9's decisions — the spec for what "correct" means)
- `.planning/phases/09-atomic-data-integrity/09-CONTEXT.md` — the LOCKED decisions D-9-01…D-9-14 that define each invariant. Especially: **D-9-14** (test shape: crash-injection fault-hook, real concurrent ingests for SC2, strand+sweep for SC3 — assert PERSISTED values not labels), **D-9-08/D-9-09** (at-least-once delivery + exactly-one-run-per-message_id semantics the assertions must encode), **D-9-13** (the swept-but-alive `set_status` overwrite tension — the one place this proof might surface a real gap), and the explicit hand-off note (09-CONTEXT `code_context`): "Phase 10's concurrency proof will drive these exact seams under parallelism — keep the sweep + ingest txn callable as plain functions so the proof harness can exercise them directly."

### Existing test mechanics to reuse (do NOT reinvent the parallelism harness)
- `tests/test_webhook_dedup_race.py` — the canonical pattern: two OS threads, real TestClient, real Postgres, `message_id` collision, asserts exactly-one-run; documents the required env setup (`ALLOW_UNSIGNED_FIXTURES=true`, `_run_pipeline` no-op stub, BackgroundTasks-run-synchronously caveat). **This is the template for the dedup surface and the env/stubbing approach for all surfaces.**
- `tests/test_claim_status.py` — `test_claim_status_concurrent_calls_exactly_one_true` (integration): the CAS-level approval race; Phase 10 lifts this to the HTTP `/approve` route (D-10-06).
- `tests/test_atomic_persist.py`, `tests/test_stuck_run_recovery.py` — the half-write and recovery invariant mechanics.
- `tests/conftest.py` — the two-factor live-DB guard (`_HAS_DB` on `DATABASE_URL`, `ALLOW_DB_RESET=1`), the `integration` marker, `FakeConnection` (offline unit pattern — NOT usable for real-race proof, per RESEARCH Pitfall 3).

### Production seams under test (verified 2026-07-07)
- `app/main.py` — webhook `inbound` (dedup insert + create_run + enqueue), `_route_reply`, `POST /runs/{run_id}/approve` :738 (CAS claim `AWAITING_APPROVAL → APPROVED` + `_deliver`), retrigger, `STALE_THRESHOLD`
- `app/db/repo.py` — `claim_status` (the CAS), `insert_inbound_email` (ON CONFLICT (message_id) DO NOTHING), `create_run`, `set_status`
- `app/db/supabase.py` — pool singleton **min=1, max=5** (the D-10-07 connection-budget constraint)
- `app/db/bootstrap.py` + `app/db/schema.sql` — how the CI job applies the schema to its ephemeral Postgres

### CI pattern to follow
- `.github/workflows/eval.yml` — existing CI workflow shape (hermetic push check); the new `concurrency-proof.yml` follows this structure but adds a Postgres service container.
- `.github/workflows/keepalive.yml` — the other existing workflow (Supabase keep-alive) — reference only.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **The parallelism harness already exists in fragments.** `test_webhook_dedup_race.py` proves the two-thread/real-Postgres/TestClient pattern end-to-end including all env gotchas (unsigned-fixtures allow, pipeline no-op stub, synchronous BackgroundTasks). Phase 10 is largely *consolidation + generalization* of proven code, not novel harness design.
- `conftest.py`'s two-factor DB guard + `integration` marker: the capstone slots straight into this — no new test-infra pattern.
- The Phase 9 seams were deliberately left "callable as plain functions so the proof harness can exercise them directly" (09-CONTEXT hand-off) — the ingest txn and sweep are directly drivable.

### Established Patterns
- **Two sanctioned status writers only** (`set_status` owned-path, `claim_status` CAS, D-12) — the "no double-approval" proof asserts the CAS property; do not introduce a third status-write path.
- **`@pytest.mark.integration` + `DATABASE_URL` two-factor guard** is the universal live-DB test shape here — the capstone uses it so the default hermetic suite stays DB-free and green.
- **TestClient runs BackgroundTasks synchronously** — every surface that goes through the webhook/approve route MUST stub the pipeline/LLM/send so the race, not a live side effect, is under test (the recurring gotcha documented in `test_webhook_dedup_race.py`).
- **`.env` in this repo carries LIVE LLM keys** (per project memory: execute-phase-integration-hazards) — any unstubbed clarify/suggest/send in a proof test would hit the real model and flake. Stub all LLM/provider calls in the harness.

### Integration Points
- New `tests/test_concurrency_proof.py` (the capstone) + new `.github/workflows/concurrency-proof.yml` (makes it standing evidence). These are the two net-new files; everything else is exercised, not modified.
- If the proof exposes a genuine invariant violation, the FIX lands in the Phase-9 production seam it exposed (`orchestrator.py` / `main.py` / `repo.py`) — but that is a contingency, not planned scope.

</code_context>

<specifics>
## Specific Ideas

- **Tone:** this is the "senior-engineer signal" capstone of v2 — the module docstring and per-invariant docstrings should read as a proof narrative (what is fired, what must hold, which crash/race window it closes), matching the explain-the-why style already in `test_webhook_dedup_race.py` and the D-9 seam comments. The code is the artifact; make it read like one.
- The user delegated all sub-decisions to the recommended options across both discussion rounds — the shape above (new unified harness → CI with ephemeral Postgres → threads/real-PG → HTTP-route approval race → test-as-proof → small deterministic N) is fully locked; the researcher should validate *mechanics* (Postgres service-container setup in Actions, TestClient-under-threads connection behavior, pool-budget vs. N), not re-open the shape.
- Verify at plan time that Phase 11's clarify-round-machine additions did not introduce a new contended write path that also warrants a proof surface — if it did, that is a scope question to raise, not silently fold in (Phase 10's charter is the Phase-9 data-integrity invariants).

</specifics>

<deferred>
## Deferred Ideas

- **Guard-hardening the unguarded `set_status` writes against a swept-to-ERROR-but-alive run** (Phase 9's D-9-13 accepted tension, already noted-for-later in 09-CONTEXT `deferred`): only pull into scope if THIS proof demonstrates the window matters in practice. Default disposition: remains deferred; the proof documents the window if it observes it, but does not add the guard speculatively.
- **Larger-N load/soak flavor (50–100 concurrent, throughput numbers)** — considered and rejected for the capstone (D-10-07: theater, CI-flaky, not stronger proof). If a genuine load-benchmark artifact is ever wanted for the writeup, it is its own out-of-band exercise, not this regression-guard phase.

### Reviewed Todos (not folded)
None — no pending todo matched this test-only phase's scope; the 8 pending todos are clarify-round / security-hygiene / cosmetic items unrelated to the concurrency proof.

</deferred>

---

*Phase: 10-Concurrency Proof*
*Context gathered: 2026-07-07*
