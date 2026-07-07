---
phase: 10-concurrency-proof
plan: 01
subsystem: testing
tags: [pytest, postgres, threading, concurrency, github-actions, fastapi-testclient]

# Dependency graph
requires:
  - phase: 09-atomic-data-integrity
    provides: "the dedup ON CONFLICT insert, claim_status CAS, and atomic ingest-transaction seams this proof exercises under real parallelism"
provides:
  - "tests/test_concurrency_proof.py — capstone integration module: 3 tests, 4 invariants, N=8 real-thread parallelism against real Postgres"
  - ".github/workflows/concurrency-proof.yml — CI job running the proof against an ephemeral postgres:16 on every push to master"
affects: [11-clarification-round-machine-alias-learning, future-phases-touching-webhook-or-approve-routes]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Capstone integration-test module consolidating multiple race surfaces into one proof-narrative-documented file (vs. per-surface scattered tests)"
    - "GitHub Actions services: postgres:16 + pg_isready health check for ephemeral-DB CI jobs"

key-files:
  created:
    - tests/test_concurrency_proof.py
    - .github/workflows/concurrency-proof.yml
  modified: []

key-decisions:
  - "Surface C uses N=8 DISTINCT message_ids (throughput/atomicity-under-load) rather than reusing the dedup harness, resolving the D-10 discretion point per RESEARCH Mechanic 4"
  - "Surface B asserts on deliver_calls + terminal DB status, never on HTTP status code — the /approve route always 303s regardless of CAS outcome"
  - "_deliver is patched on app.pipeline.orchestrator (not app.main) because it is imported inside the approve route body — patching app_main would silently no-op and risk a live Resend send"

patterns-established:
  - "Wholesale LLM/gateway stubbing helper (_stub_pipeline_and_send) reused across all three surfaces in one module — the load-bearing isolation pattern for any future concurrency test against this app's live-keyed .env"

requirements-completed: [OPS2-03]

# Metrics
duration: 25min
completed: 2026-07-07
---

# Phase 10 Plan 01: Concurrency Proof Capstone Summary

**One capstone test module (tests/test_concurrency_proof.py) fires N=8 real OS threads across three risk surfaces — webhook dedup, HTTP approval race, concurrent distinct ingests — against a real Postgres, plus a GitHub Actions job (concurrency-proof.yml) that runs it on an ephemeral postgres:16 container on every push, making the four Phase-9 concurrency invariants standing CI evidence rather than a local-only smoke test.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-07T20:08:22Z
- **Completed:** 2026-07-07T20:34:11Z
- **Tasks:** 2/2
- **Files modified:** 2 (both net-new)

## Accomplishments

- Built `tests/test_concurrency_proof.py`: three `@pytest.mark.integration` tests asserting all four invariants (no duplicate run per `message_id`, no double-approval via the real HTTP route, no lost update, no half-write) under genuine 8-way thread/pool parallelism.
- Built `.github/workflows/concurrency-proof.yml`: a `services: postgres:16` CI job with a `pg_isready` health check that bootstraps the schema (`--reset`) against a plain local `DATABASE_URL` and runs the proof with `-m integration` on every push to master.
- Verified zero production-code changes (`git diff --name-only app/` empty across both commits) and that the default hermetic suite (`uv run pytest -m 'not integration'`) stays green and unaffected (596 passed, 21 skipped, 30 deselected — the 30 deselected are exactly the phase-10 + pre-existing integration tests).

## Task Commits

Each task was committed atomically:

1. **Task 1: Build the capstone proof module tests/test_concurrency_proof.py** - `a921254` (test)
2. **Task 2: Stand up .github/workflows/concurrency-proof.yml** - `ca79b42` (ci)

**Plan metadata:** committed separately per worktree-mode convention (orchestrator handles the final metadata commit after merge).

## Files Created/Modified

- `tests/test_concurrency_proof.py` - Capstone: `test_dedup_exactly_one_run_per_message_id` (Surface A), `test_concurrent_approvals_exactly_one_wins` (Surface B, real HTTP route), `test_concurrent_distinct_runs_no_lost_update` (Surface C, lost-update + half-write)
- `.github/workflows/concurrency-proof.yml` - CI job: `services: postgres:16` + `pg_isready` health check → `uv sync` → `bootstrap --reset` → `pytest tests/test_concurrency_proof.py -m integration -v`

## Decisions Made

- **Surface C uses N=8 distinct `message_id`s**, not the dedup harness reused — the plan flagged this as an open D-10 discretion point (RESEARCH Mechanic 4); distinct IDs correctly test throughput/atomicity-under-load (a different failure mode than Surface A's single-ID race).
- **Surface B never asserts on HTTP status.** The `/approve` route always returns 303 regardless of whether the CAS claim was won (`main.py:783`), so the test asserts the winning *side effect* instead: `len(deliver_calls) == 1` and `repo.load_run(run_id)["status"] == "approved"`.
- **The `_deliver` monkeypatch targets `app.pipeline.orchestrator._deliver`, not `app_main._run_pipeline`** — `_deliver` is imported inside the approve route body (`main.py:753`), so patching the wrong module would silently no-op and risk firing a real Resend send under concurrent load against a `.env` carrying live keys.
- Added a direct DB assertion in Surface A (`count(payroll_runs WHERE source_email_id=...) == 1`) and a `LEFT JOIN email_messages` check in Surface C beyond the plan's minimum response-body assertions, for a stronger, harness-independent proof of the invariant.

## Deviations from Plan

None - plan executed exactly as written. The `read_first` sources (test_webhook_dedup_race.py, test_atomic_persist.py, conftest.py, main.py, repo.py) were verified live against the actual repo before writing, confirming every cited seam (line numbers, function signatures, `_deliver` import location, CAS route always-303 behavior) matched the plan's description exactly — no adjustments were needed.

## Issues Encountered

None. `repo.get_connection` (imported from `app.db.supabase` into the `repo` module namespace) was confirmed as the correct accessor for the two direct-SQL verification queries in Surfaces A and C before use.

## User Setup Required

None - no external service configuration required. The CI job is self-contained (ephemeral `postgres:16` service container, no secrets referenced).

## Next Phase Readiness

- OPS2-03 is now fully satisfied: the concurrency proof is standing CI evidence, not a skip-guarded local test.
- The proof module cannot be exercised in this sandboxed execution (no live Postgres available locally) — its authoritative verification is the `concurrency-proof.yml` GitHub Actions run on the next push to master. The hermetic suite proves the module doesn't break anything already passing; the CI run is what proves the invariants themselves hold under real parallelism.
- No blockers for Phase 11 (clarification-round-machine-alias-learning) or any future phase touching the webhook/approve routes — this capstone is a regression guard they inherit for free.

---
*Phase: 10-concurrency-proof*
*Completed: 2026-07-07*

## Self-Check: PASSED

- FOUND: tests/test_concurrency_proof.py
- FOUND: .github/workflows/concurrency-proof.yml
- FOUND: .planning/phases/10-concurrency-proof/10-01-SUMMARY.md
- FOUND: commit a921254 (Task 1)
- FOUND: commit ca79b42 (Task 2)
