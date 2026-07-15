---
phase: 17-the-pump
plan: 05
subsystem: testing
tags: [pytest, postgres, fastapi, queue, pump, queueproof]

requires:
  - phase: 17-the-pump (plans 17-01, 17-02, 17-04)
    provides: "DrainOutcome enum + drain_once() -> DrainOutcome (17-01); repo.count_open_jobs() (17-02); GET /internal/pump + Settings.pump_token (17-04)"
provides:
  - "The phase's anti-vacuous-proof anchor: a live @pytest.mark.queueproof test proving GET /internal/pump drains a future-due job on a zero-worker instance (ROADMAP criterion #2, PUMP-01)"
  - "A live mixed-state count_open_jobs behavioral proof (the half 17-02's FakeConnection test could not give)"
  - "A demonstrated falsifying mutation (RED) + revert (GREEN), closing PROOF-05 house discipline for this test"
affects: [18-failure-policy-sweep-deletion, 21-durability-proofs-ops-view]

tech-stack:
  added: []
  patterns:
    - "Stub pipeline_glue.run_pipeline_now via monkeypatch.setattr on the module object (never the imported name) before an endpoint-level drain, asserting a handler-side observable (orchestrator_calls == [run_id]) rather than trusting a bare row state — copied from the sibling proof at test_queue_durability.py:1016-1028"
    - "Settings-cache discipline: get_settings.cache_clear() before AND after a test that sets an env-backed secret, via try/finally"
    - "Sequential (non-concurrent) live-DB state construction for a mixed-population proof: claim a row only while it is the SOLE claimable row in an isolated table, since claim_job() has no target-by-id API"

key-files:
  created: []
  modified:
    - tests/test_queue_durability.py

key-decisions:
  - "Falsifying mutation chosen: make GET /internal/pump's drain loop a no-op (while False:) rather than stripping claim_job's reclaim clause — a smaller, more surgical, more obviously-revertible one-line diff on the route under test"
  - "Test B (count_open_jobs) builds its mixed population sequentially, not via a threading.Barrier — the goal is a behavioral proof against real Postgres, not a race proof (that already exists in test_genuine_claim_race_exactly_one_winner); sequential claiming while each job is the sole claimable row is simpler and equally load-bearing"

requirements-completed: [PUMP-01]

coverage:
  - id: D1
    description: "A job with a future available_at, on an instance with ZERO live worker threads, is executed by hitting GET /internal/pump — never drain.drain_once() directly — proving the pump (not in-process workers) is the actual durable-execution guarantee"
    requirement: "PUMP-01"
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py::test_pump_drains_future_due_job_with_zero_workers"
        status: pass
    human_judgment: false
  - id: D2
    description: "The proof is non-vacuous: asserts live_queue_worker_threads() == [] as an explicit precondition, asserts the job is NOT claimable while future-dated, stubs pipeline_glue.run_pipeline_now and asserts orchestrator_calls == [run_id], asserts claimed==1/done==1 from the JSON body (never merely status_code==200), re-reads the job row by id to state=='done', re-reads the run to the stub's observable post-handler status (COMPUTED, non-terminal), and asserts queue_depth==0"
    requirement: "PUMP-01"
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py::test_pump_drains_future_due_job_with_zero_workers"
        status: pass
    human_judgment: false
  - id: D3
    description: "count_open_jobs is proven behaviorally against real Postgres: a mixed pending/leased/done/dead population returns the exact open (pending+leased) count, and the count is shown to drop live on a further state transition"
    requirement: "PUMP-01"
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py::test_count_open_jobs_live_mixed_population"
        status: pass
    human_judgment: false
  - id: D4
    description: "The proof is demonstrated able to fail: a falsifying mutation (pump's drain loop made a no-op) drives the anchor test RED (claimed==0), and reverting it drives the test GREEN again, with production source byte-identical after revert"
    requirement: "PUMP-01"
    verification:
      - kind: manual_procedural
        ref: "RED/GREEN pytest runs pasted below under 'FALSIFYING MUTATION'; git diff --exit-code app/routes/pump.py app/db/repo/jobs.py confirmed clean after revert"
        status: pass
    human_judgment: false

duration: ~9min
completed: 2026-07-15
status: complete
---

# Phase 17 Plan 05: Pump Anti-Vacuous-Proof Anchor Summary

**A live `@pytest.mark.queueproof` test proves GET /internal/pump — not the in-process worker threads — drains a future-due job on a zero-worker instance to `state='done'` with a stubbed orchestrator, plus a live mixed-state `count_open_jobs` proof; both demonstrated able to fail via a real RED/GREEN mutation cycle.**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-07-15T15:01:00Z
- **Completed:** 2026-07-15T15:09:29Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- `test_pump_drains_future_due_job_with_zero_workers` — the phase's single most important test (ROADMAP criterion #2). Enqueues a `run_pipeline` job, backdates `available_at` into the future, asserts `live_queue_worker_threads() == []` and `repo.claim_job() is None` while future-dated, backdates into the past, hits `GET /internal/pump` via `TestClient` (never `drain.drain_once()` directly), and asserts `claimed==1`/`done==1` from the JSON body, `orchestrator_calls == [run_id]` (the stubbed handler-side observable), a by-id job-row re-read to `state=='done'`, the run reaching the stub's observable post-handler status `COMPUTED` (in-flight/non-terminal, review LOW #4), and `queue_depth==0`.
- `test_count_open_jobs_live_mixed_population` — the live half of `count_open_jobs` 17-02's `FakeConnection` test could not prove: builds a real pending/leased/done/dead population sequentially against Postgres, verifies each row's own state by id, asserts `count_open_jobs()==2` (pending+leased only), then completes the leased job and re-asserts the count drops to `1` — proving the read is live, not memoized.
- Falsifying mutation executed against real source: `GET /internal/pump`'s drain loop made a no-op (`while False:`) drove the anchor test RED (`claimed: 0`); reverted, the test is GREEN again, and `git diff --exit-code app/routes/pump.py app/db/repo/jobs.py` confirms production source is byte-identical to 17-04's committed state.
- `uv run pytest tests/ -m queueproof -v -rs` → 19 passed, 785 deselected, **zero skipped** — the whole-marker CI gate's own guard.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write the future-due / zero-worker / pump-drains-it queueproof test** - `5d00733` (test)
2. **Task 2: Demonstrate the proof can fail — run the falsifying mutation RED, revert GREEN, paste both** - no commit (per plan design: the mutation is temporary and uncommitted; production source is byte-identical to Task 1's committed state after revert — `git diff --exit-code app/routes/pump.py app/db/repo/jobs.py` confirmed clean)

**Plan metadata:** (this commit)

## Files Created/Modified
- `tests/test_queue_durability.py` - appended `test_pump_drains_future_due_job_with_zero_workers` (the anti-vacuous anchor) and `test_count_open_jobs_live_mixed_population` (the live mixed-state proof), both carrying the module's `queueproof` marker via the existing `pytestmark`

## Decisions Made
- Falsifying mutation targeted `app/routes/pump.py`'s drain `while` condition (`while claimed < _MAX_JOBS_PER_PUMP and time.monotonic() < deadline:` → `while False:`) rather than `claim_job`'s SQL — a one-line, trivially-revertible diff isolated to the route under test, matching the plan's first suggested mutation ("make /internal/pump's drain loop a no-op stub").
- Test B's mixed population is built sequentially (claim-while-sole-claimable-row), not via a `threading.Barrier` — a genuine concurrent-claim race is already proven elsewhere in this file (`test_genuine_claim_race_exactly_one_winner`); this proof's job is the exact-count behavioral claim, which sequential construction proves just as rigorously with far less machinery.

## Deviations from Plan

None - plan executed exactly as written.

## FALSIFYING MUTATION

**Mutation applied (temporary, uncommitted):** `app/routes/pump.py`, replaced

```python
while claimed < _MAX_JOBS_PER_PUMP and time.monotonic() < deadline:
```

with

```python
while False:  # FALSIFYING MUTATION (17-05 Task 2): drain loop no-op
```

**Command:**
```
DATABASE_URL='postgresql://pnhek@localhost:5432/payroll_pump_proof' ALLOW_DB_RESET=1 \
  uv run pytest tests/test_queue_durability.py -m queueproof -k pump -v -rs
```

### RED (mutated — confirmed failing)

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.1.1, pluggy-1.6.0 -- .venv/bin/python
collected 16 items / 15 deselected / 1 selected

tests/test_queue_durability.py::test_pump_drains_future_due_job_with_zero_workers FAILED [100%]

=================================== FAILURES ===================================
______________ test_pump_drains_future_due_job_with_zero_workers _______________

        # --- Step 6: hit the HTTP endpoint — never drain.drain_once() ------
        client = TestClient(app_main.app)
        response = client.get(
            "/internal/pump", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200, response.text
        body = response.json()

        # --- Step 7: the response reports real per-job outcomes, never a
        # bare 200 ------------------------------------------------------------
>       assert body["claimed"] == 1, body
E       AssertionError: {'claimed': 0, 'done': 0, 'retried': 0, 'dead': 0, ...}
E       assert 0 == 1

tests/test_queue_durability.py:1256: AssertionError
---------------------------- Captured stdout setup -----------------------------
Bootstrap target: postgresql://pnhek@localhost:5432/payroll_pump_proof
RESET: dropping all tables in reverse dependency order — this is destructive
Bootstrap complete. Tables applied.
Seeded 3 businesses, 7 employees.
================ 1 failed, 15 deselected, 1 warning in 0.61s ==================
```

The mutation drove the anchor test RED exactly as designed: with the drain loop a no-op, the future-due-then-backdated job is never claimed, `claimed` stays `0`, and the test's own `body["claimed"] == 1` assertion (step 7) fails first — before any downstream assertion (`orchestrator_calls`, the by-id row re-read, the run-status check) even runs, confirming the response-body assertion is the load-bearing non-vacuity check it is designed to be.

### GREEN (reverted — confirmed passing)

**Revert command:** restored `while claimed < _MAX_JOBS_PER_PUMP and time.monotonic() < deadline:` exactly.

**Byte-identical confirmation:** `git diff --exit-code app/routes/pump.py app/db/repo/jobs.py` → exit 0, no output (clean).

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.1.1, pluggy-1.6.0 -- .venv/bin/python
collected 16 items / 15 deselected / 1 selected

tests/test_queue_durability.py::test_pump_drains_future_due_job_with_zero_workers PASSED [100%]

================= 1 passed, 15 deselected, 1 warning in 0.55s ==================
```

Full re-run of the whole-marker gate after revert (`uv run pytest tests/ -m queueproof -v -rs`) confirms all 19 queueproof tests pass with zero skips, including the two new tests from this plan and the pre-existing 17 from earlier plans.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The phase's anchor durability proof (ROADMAP criterion #2, PUMP-01) is live, non-vacuous, and demonstrated able to fail — the standing residual risk this milestone opened with (a prior vacuous "concurrency proof" that passed while proving nothing) is closed for the pump specifically.
- The documented final-attempt lease-strand residual (a `state='leased', attempts=max_attempts, leased_until<now()` job that the current claim query cannot reclaim) remains explicitly out of scope per this plan's SCOPE NOTE — no reaper exists yet, and none was added here. That gap is Phase 18/FAIL-02's (T-17-16), and is proven there, not here.
- Phase 17 (the-pump) is now fully executed: 17-01 through 17-05 all complete. Ready for phase closeout (review, security gate, and advancing to Phase 18).

---
*Phase: 17-the-pump*
*Completed: 2026-07-15*

## Self-Check: PASSED

- `tests/test_queue_durability.py` — FOUND (modified, contains both new tests; confirmed via `grep -n "def test_pump_drains_future_due_job_with_zero_workers\|def test_count_open_jobs_live_mixed_population"`).
- Commit `5d00733` — FOUND (`git log --oneline --all | grep 5d00733`).
- `app/routes/pump.py` — byte-identical to pre-mutation state — FOUND (`git diff --exit-code app/routes/pump.py` exit 0).
- Live re-run of both new tests plus the full `queueproof` marker (19 passed, 0 skipped) — FOUND, executed above.
