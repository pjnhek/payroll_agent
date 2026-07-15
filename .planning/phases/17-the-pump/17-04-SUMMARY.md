---
phase: 17-the-pump
plan: 04
subsystem: api
tags: [fastapi, hmac, queue, pump, pydantic-settings, pytest]

requires:
  - phase: 17-the-pump (plans 17-01, 17-02)
    provides: "DrainOutcome enum + drain_once() -> DrainOutcome (17-01); repo.count_open_jobs() (17-02)"
provides:
  - "GET /internal/pump — authenticated, bounded, real-count-returning pump route"
  - "Settings.pump_token config field"
  - "app.main router wiring"
  - "Hermetic auth/bounded/infra-failure test coverage for the pump route"
affects: [17-05, 18-failure-policy-sweep-deletion, 21-durability-proofs-ops-view]

tech-stack:
  added: []
  patterns:
    - "hmac.compare_digest Bearer-token auth, fail-closed on empty secret, matching app/routes/health.py's sync-def + disclosure-discipline convention"
    - "Dual-cap bounded drain loop (max-jobs AND wall-clock, checked between drain_once() calls)"

key-files:
  created:
    - app/routes/pump.py
    - tests/test_pump_route.py
  modified:
    - app/config.py
    - app/main.py

key-decisions:
  - "GET (not POST) for /internal/pump — simplest for a curl cron; the drain is idempotent (SKIP LOCKED)"
  - "pump_token: str = \"\" follows the empty-default-secret convention; fail-closed logic lives in the route's _authorized(), not as field validation"
  - "The catch-all 503 branch is honestly broad: it also catches a propagated drain_once() double-failure re-raise, not just a genuine infra outage on claim/count"

requirements-completed: [PUMP-01]

coverage:
  - id: D1
    description: "GET /internal/pump authenticates with hmac.compare_digest, fails closed on an unset/empty PUMP_TOKEN, and returns 401 on any bad/missing credential"
    requirement: "PUMP-01"
    verification:
      - kind: unit
        ref: "tests/test_pump_route.py -k auth"
        status: pass
    human_judgment: false
  - id: D2
    description: "The route loops the shared drain_once() bounded by a max-jobs cap AND a separately-proven wall-clock cap, and returns real per-invocation counts {claimed, done, retried, dead, fenced, queue_depth} satisfying claimed == done+retried+dead+fenced"
    requirement: "PUMP-01"
    verification:
      - kind: unit
        ref: "tests/test_pump_route.py -k bounded"
        status: pass
      - kind: unit
        ref: "tests/test_pump_route.py::test_auth_correct_token_returns_200_with_counts_invariant"
        status: pass
    human_judgment: false
  - id: D3
    description: "A dead-lettered/backed-off job returns 200 + counts (D-09); a genuine infra outage OR a propagated drain_once() double-failure re-raise returns 503 (D-10), including the real fake-repo double-failure chain driven through TestClient with the lease token retained"
    requirement: "PUMP-01"
    verification:
      - kind: unit
        ref: "tests/test_pump_route.py -k infra_failure"
        status: pass
    human_judgment: false

duration: ~12min
completed: 2026-07-15
status: complete
---

# Phase 17 Plan 04: The Pump Route Summary

**Authenticated `GET /internal/pump` — constant-time Bearer auth (fail-closed), a dual-capped drain loop over the shared `drain_once()`, real six-key counts, and 503 only on genuine infra failure including a propagated `drain_once()` double-failure re-raise.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-15T07:47:04-07:00
- **Completed:** 2026-07-15T07:58:46-07:00
- **Tasks:** 2
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- `app/routes/pump.py`: `GET /internal/pump` — `_authorized()` does a constant-time Bearer compare (`hmac.compare_digest`) that fails closed the instant `pump_token` is falsy, before ever reaching the compare; the route returns 401 (never 404) on any bad/missing/unset credential.
- The drain loop calls the exact `drain.drain_once()` the worker threads call (never a route-local fork), bounded by `_MAX_JOBS_PER_PUMP = 20` and `_MAX_WALL_CLOCK_SECONDS = 120` (checked between `drain_once()` calls, never mid-call), aggregating each `DrainOutcome` into `{claimed, done, retried, dead, fenced, queue_depth}` — `claimed == done + retried + dead + fenced` holds by construction.
- A `DrainOutcome.DEAD`/`RETRIED` result still returns 200 + counts (normal queue operation); any exception mid-drain — a genuine infra outage on claim/count, OR a propagated `drain_once()` double-failure re-raise (17-01's `fail_job`-itself-failed branch) — returns 503 with a fixed body, logging only `type(exc).__name__`, never `str(exc)`.
- `app/config.py` gains `pump_token: str = ""` in the empty-default-secret convention (mirrors `resend_api_key`/`webhook_signing_secret`); `app/main.py` wires `pump.router`.
- `tests/test_pump_route.py`: 10 hermetic tests via `TestClient(app_main.app)` — 4 auth tests (missing/wrong/empty-secret → 401; correct token → 200 with the invariant asserted), 2 bounded tests (max-jobs cap AND a separate wall-clock-only proof that jumps `time.monotonic` after exactly N < `_MAX_JOBS_PER_PUMP` iterations), and 4 infra_failure tests — `count_open_jobs` raising → 503, DEAD/RETRIED → 200 (D-09), the narrow `drain_once`-raises → 503 mapping, and the load-bearing real fake-repo double-failure chain (claim → leased job, `dispatch.handle` raises, `repo.fail_job` also raises) driven through `TestClient` so the REAL `drain_once()` re-raises into the route's `try/except`, asserting 503 AND `drain.held_tokens() == [token]` after the HTTP call.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add pump_token setting, write the /internal/pump route, wire it into main.py** - `c0debd0` (feat)
2. **Task 2: Hermetic tests — auth (401/200), bounded drain cap, D-10 infra-vs-business semantics** - `e3119a6` (test) — this commit also carries the comment-provenance fix to `app/config.py`/`app/routes/pump.py` from Task 1 (see Deviations)

## Files Created/Modified
- `app/routes/pump.py` - `GET /internal/pump` route, `_authorized()` helper, `_MAX_JOBS_PER_PUMP`/`_MAX_WALL_CLOCK_SECONDS` constants
- `app/config.py` - `Settings.pump_token: str = ""`
- `app/main.py` - `app.include_router(pump.router)`
- `tests/test_pump_route.py` - hermetic auth/bounded/infra_failure coverage

## Decisions Made
- `GET` (not `POST`) for `/internal/pump` — simplest for a `curl` cron; the drain is idempotent (`SKIP LOCKED` makes a repeat/concurrent hit safe).
- `pump_token` fail-closed logic lives in the route's `_authorized()`, not as `Settings` field validation — matching how `ALLOW_UNSIGNED_FIXTURES` gates behavior at its call site.
- The 503 catch-all is deliberately honest/broad in its comment: it also catches a propagated `drain_once()` double-failure and would catch an unexpected programming error too; in normal operation only infra failures reach it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Comments citing decision-IDs/phase/task-IDs tripped the repo's comment-provenance guard**
- **Found during:** Task 2, running the full suite (`uv run pytest -q`) as a pre-commit sanity check
- **Issue:** The plan's own frontmatter/action text is dense with `D-01`/`D-05`/`D-10`/`Phase 17`/`Phase 18`/`T-17-16`/"review MEDIUM #2" citations, and Task 1/2's implementation comments mirrored that style directly into `app/config.py`, `app/routes/pump.py`, and `tests/test_pump_route.py`. `tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree` (a permanent CI gate, part of this project's comment-hygiene discipline) fails the build on any decision-ID, phase-reference, or task-ID citation in source comments — source text must explain the code's reasoning, not cite the ticket/decision that produced it.
- **Fix:** Rewrote every flagged comment/docstring in the three files to keep the identical technical reasoning (fail-closed auth, the dual cap's derivation, the double-failure re-raise semantics, D-09/D-10-style outcome framing) while dropping the `D-XX`/`Phase N`/`T-17-16`/"review MEDIUM #2" labels. `PUMP-01` was left in place — it matches the guard's excluded `requirement-id` pattern (live traceability, not decayed history).
- **Files modified:** `app/config.py`, `app/routes/pump.py`, `tests/test_pump_route.py`
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree -q` → 1 passed; full suite re-run green (734 passed, 68 skipped); `uv run mypy --strict app/ tests/test_pump_route.py` → no issues in 64 source files.
- **Committed in:** `e3119a6` (part of Task 2's commit, since the guard failure only surfaced when running the whole suite after Task 2 landed)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug, a pre-existing CI gate the plan's own citation-heavy prose would have tripped verbatim)
**Impact on plan:** No scope creep — same code, same reasoning, comments only. All plan acceptance criteria still hold verbatim.

## Issues Encountered
- The wall-clock-cap test's first attempt patched the global `time.monotonic` directly, which the ASGI/anyio machinery driving `TestClient`'s own request also calls internally — this exhausted the fake's counted call budget before the route's own loop ran, so `claimed` came back at the max-jobs cap (20) instead of the intended N=3. Fixed by binding a fake `time`-like object onto `pump_module`'s own `time` name (`monkeypatch.setattr(pump_module, "time", _FakeTime)`) instead of patching the global stdlib module — isolates the fake to only the route's own `time.monotonic()` calls.

## User Setup Required
None - no external service configuration required (PUMP_TOKEN provisioning in Render/GitHub Actions secrets is Plan 17-03's scope, already landed).

## Next Phase Readiness
- `GET /internal/pump` is live, authenticated, bounded, and covered by hermetic tests; `pump.yml` (17-03) already targets this exact contract (`Authorization: Bearer $PUMP_TOKEN`, response keys unused by the cron beyond the HTTP status).
- Remaining phase work: 17-05 (the live-DB `queueproof` anti-vacuous-proof anchor proving the pump drains a due job with zero live worker threads) and the README duty-cycle documentation, per the phase's ROADMAP criteria.
- No blockers. The final-attempt lease-strand residual (T-17-16 in planning docs) remains a documented, accepted gap deferred to the failure-policy phase — this route does not attempt to work around it, matching the plan's prohibitions.

---
*Phase: 17-the-pump*
*Completed: 2026-07-15*

## Self-Check: PASSED

All created/modified files confirmed on disk (`app/routes/pump.py`, `tests/test_pump_route.py`,
`app/config.py`, `app/main.py`, this SUMMARY.md) and both task commits (`c0debd0`, `e3119a6`)
confirmed present in `git log --oneline --all`.
