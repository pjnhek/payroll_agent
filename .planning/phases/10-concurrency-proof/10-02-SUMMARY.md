---
phase: 10-concurrency-proof
plan: 02
subsystem: testing
tags: [postgres, psycopg, threading, ci, github-actions, concurrency]

# Dependency graph
requires:
  - phase: 10-concurrency-proof
    provides: "Original 3-surface concurrency proof capstone (test_concurrency_proof.py) + concurrency-proof.yml CI workflow, from plan 10-01"
provides:
  - "Surfaces A and C rewritten to drive real DB-level concurrency through the sync repo seam (repo.insert_inbound_email -> repo.create_run) via a threading.Barrier, closing CR-01 (the async /webhook/inbound route serialized all fan-out on the event loop and never exercised the ON CONFLICT / lost-update races)"
  - "Pool-fit thread counts: N_INGEST=5 (<= app pool max_size) for genuine connection-holding surfaces, N_APPROVE=8 (unchanged) for the brief-CAS surface"
  - "Surface A's explicit winner/loser assertion (no None-filtered set) plus the retained DB count(*)==1 backstop"
  - "Non-destructive CI schema pre-flight (no bootstrap --reset); seeded_db fixture is the sole reset owner behind its ALLOW_DB_RESET guard"
  - "Truthful module/test docstrings describing the barrier-released direct-seam mechanism vs Surface B's genuinely-parallel HTTP route"
affects: [ci, testing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "threading.Barrier(N) to force N threads to enter a critical DB section at the same wall-clock instant, bypassing an async route's event-loop serialization by calling the underlying sync repo function directly"
    - "Explicit winner/loser assertion pattern for CAS/ON-CONFLICT races: assert the exact count of winners AND that every loser matches the documented loser shape, rather than filtering falsy values out of a result set"

key-files:
  created: []
  modified:
    - tests/test_concurrency_proof.py
    - .github/workflows/concurrency-proof.yml

key-decisions:
  - "Surfaces A and C bypass the async /webhook/inbound HTTP route entirely and call repo.insert_inbound_email/repo.create_run directly from barrier-released OS threads, because the route's only await precedes all DB work and a shared TestClient funnels every thread through one event-loop portal — CR-01 confirmed the old HTTP fan-out never triggered the races it claimed to prove."
  - "N_INGEST=5, matching the app pool's max_size=5, because Surfaces A/C threads are simultaneous connection HOLDERS for the full ingest transaction (unlike Surface B's brief CAS, which stays at N_APPROVE=8)."
  - "Surface C drops the pipeline_calls==N assertion since create_run does not schedule _run_pipeline on the direct seam (that only happens via the webhook route's BackgroundTask) — asserting it would test something the direct-seam code path cannot produce."
  - "CI schema step drops --reset; seeded_db fixture is the sole reset owner behind its ALLOW_DB_RESET two-factor guard, removing an unguarded destructive-drop pattern hazard if the workflow is ever copied/repointed."

requirements-completed: [OPS2-03]

duration: 25min
completed: 2026-07-07
---

# Phase 10 Plan 02: Concurrency-Proof Gap Closure Summary

**Rewrote Surfaces A/C of the concurrency capstone to race the real sync DB seam under a threading.Barrier instead of serializing through the async webhook route, closing the confirmed CR-01 blocker plus five corollary review findings.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-07T20:28:33Z
- **Completed:** 2026-07-07T20:51:48Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Surfaces A (`test_dedup_exactly_one_run_per_message_id`) and C (`test_concurrent_distinct_runs_no_lost_update`) now drive genuine DB-level MVCC contention: N_INGEST threads released simultaneously by a `threading.Barrier` call `repo.insert_inbound_email` / `repo.create_run` directly, closing the confirmed CR-01 finding that the old HTTP fan-out through the async `/webhook/inbound` route serialized every request on the single event loop and never exercised the `ON CONFLICT` / lost-update invariants.
- Surface B (`test_concurrent_approvals_exactly_one_wins`) left completely unchanged — it already races the real sync `/approve` route via Starlette's genuinely parallel anyio threadpool and was sound.
- Thread counts now respect the app connection pool: `N_INGEST=5` (<= pool `max_size=5`) for the two connection-holding ingest surfaces, `N_APPROVE=8` (unchanged) for the brief-CAS approve surface, with a comment stating the real N-vs-pool relationship instead of the prior incorrect claim.
- Surface A's assertion now explicitly proves the winner/loser split (exactly one `inserted=True`, every loser gets `email_id=None`/`run_id=None` per `repo.py:171`'s documented `ON CONFLICT DO NOTHING` behavior) plus keeps the DB `count(*)==1` backstop — no more filtering `None` out of a `run_id` set.
- CI workflow's schema pre-flight step dropped `--reset`; the `seeded_db` fixture is now the sole guarded reset owner.

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewrite Surfaces A & C to a barrier-driven direct-seam race; fix WR-01/WR-02/IN-01/IN-02** - `45ff622` (fix)
2. **Task 2: Make the CI schema step non-destructive (WR-04)** - `77b86ea` (fix)

**Plan metadata:** (this commit)

## Files Created/Modified
- `tests/test_concurrency_proof.py` - Surfaces A/C rewritten to a barrier-released direct repo-seam race (`repo.insert_inbound_email` -> `repo.create_run`); explicit winner/loser assertions; `N_INGEST`/`N_APPROVE` constants with correct pool-fit comment; truthful docstrings; Surface B untouched.
- `.github/workflows/concurrency-proof.yml` - Schema pre-flight step drops `--reset`; runs `uv run python -m app.db.bootstrap` (idempotent `CREATE TABLE IF NOT EXISTS`) with a comment explaining reset ownership now belongs solely to the `seeded_db` fixture's `ALLOW_DB_RESET` guard.

## Decisions Made
See `key-decisions` in frontmatter. Summary: bypass the async route entirely for the two DB-race surfaces (CR-01 fix Option 1, the plan's preferred option for a test-only phase); size the ingest thread count to the pool's `max_size` rather than raising the pool ceiling; drop the pipeline-count assertion that only makes sense on the webhook path; make CI's schema step idempotent and non-destructive rather than deleting it outright (keeps a fail-fast pre-flight while removing the redundant/unguarded drop).

## Deviations from Plan

None - plan executed exactly as written. Both tasks matched their `<action>` blocks precisely; all `<acceptance_criteria>` and `<verify>` commands passed without needing any Rule 1-4 auto-fixes.

## Issues Encountered

None. The `bootstrap(reset=False)` idempotent-create behavior was confirmed against `app/db/schema.sql`'s `CREATE TABLE IF NOT EXISTS` statements before editing the workflow, per the plan's guidance at Task 2's `<action>` — no ambiguity required a fallback path.

## User Setup Required

None - no external service configuration required. The integration proof itself still requires a real Postgres (CI-only, or local with `DATABASE_URL` + `ALLOW_DB_RESET=1`) and is expected to skip in this environment; that is unchanged from plan 10-01 and is not part of this gap closure's scope.

## Verification

- `uv run pytest -m 'not integration' -q` — 596 passed, 21 skipped, 30 deselected. Hermetic suite green and DB-free.
- `grep -c 'threading.Barrier' tests/test_concurrency_proof.py` — 6 occurrences (docstrings + both surfaces' code).
- `grep -c 'client.post("/webhook/inbound"' tests/test_concurrency_proof.py` — 0 (CR-01 dead).
- `repo.insert_inbound_email(` and `app.pipeline.orchestrator._deliver` both present; `client.post(f"/runs/{run_id}/approve")` intact (Surface B unchanged).
- `git diff --name-only app/` — empty. Zero production-code changes.
- YAML validity confirmed via `uv run python -c "import yaml; yaml.safe_load(...)"`; `bootstrap --reset` count is 0; `postgres:16`, `pg_isready`, `tests/test_concurrency_proof.py -m integration`, and `localhost:5432` all present; no `pooler.supabase.com` or `secrets.` strings.
- The authoritative proof (push-triggered GitHub Actions run against the ephemeral `postgres:16` service) was not executed in this session — it fires automatically on the next push to `master` per the workflow's `on: push` trigger.

## Next Phase Readiness

CR-01 (BLOCKER) and all five corollary findings (WR-01, WR-02, WR-04, IN-01, IN-02) from `10-REVIEW.md` are closed. WR-03 (shared-TestClient reentrancy) is resolved as a side effect for Surfaces A/C (no longer HTTP-driven) and remains moot for Surface B (which is genuinely parallel by design). IN-03 (lock discipline for shared collectors under real parallel appends) is satisfied — Surfaces A and C now append to their `results` lists under a `threading.Lock`, matching the pattern already used for Surface A's collector.

Phase 10 (concurrency-proof) has no further plans; this gap closure was the only remaining incomplete plan for the phase.

## Self-Check: PASSED

- `tests/test_concurrency_proof.py` — FOUND (modified, rewritten Surfaces A/C).
- `.github/workflows/concurrency-proof.yml` — FOUND (modified, `--reset` removed).
- Commit `45ff622` — FOUND in `git log --oneline`.
- Commit `77b86ea` — FOUND in `git log --oneline`.

---
*Phase: 10-concurrency-proof*
*Completed: 2026-07-07*
