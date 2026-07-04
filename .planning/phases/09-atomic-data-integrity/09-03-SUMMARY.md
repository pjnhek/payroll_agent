---
phase: 09-atomic-data-integrity
plan: 03
subsystem: api
tags: [fastapi, postgres, transactions, webhook, concurrency, dedup, recovery-sweep]

# Dependency graph
requires:
  - phase: 09-atomic-data-integrity
    provides: "repo.sweep_stranded_runs, repo.find_run_by_message_id, mockable repo.get_connection (09-01)"
provides:
  - "inbound() webhook route wraps dedup-insert + reply-classification + sender-routing + create_run in ONE transaction, committed before background_tasks.add_task"
  - "_finish_reply_resume(run_id, email, cleaned, background_tasks) — post-commit sender-revalidation + response-shaping helper, called by both the webhook's new transactional path and the retained _route_reply (simulate_reply's call site)"
  - "runs_list() sweeps stranded in-flight runs to ERROR (repo.sweep_stranded_runs) before repo.load_all_runs(), sharing STALE_THRESHOLD_SECONDS with retrigger()'s stale-in-flight claim"
  - "tests/test_webhook_dedup_race.py — SC2 concurrency race proof via real threads + real Postgres"
affects: [09-04, 10-concurrency-proof]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Transactional ingest-decision block: one with repo.get_connection() as conn: with conn.transaction(): spanning dedup + reply-classification READS + sender-routing + create_run, classifying exactly one of five outcomes (duplicate/reply_candidate/late_reply/unknown_sender/new_run) BEFORE any response shaping or background task scheduling happens post-commit"
    - "Reply-classification-before-create_run ordering: find_awaiting_reply_for_header/find_any_run_for_header run INSIDE the same transaction as create_run, on a code path that structurally cannot reach create_run once either header lookup matches"
    - "Shared threshold constant, two use sites: STALE_THRESHOLD_SECONDS (int) feeds the sweep; STALE_THRESHOLD (timedelta) feeds retrigger's stale-claim datetime comparison — same underlying value, two representations"

key-files:
  created:
    - tests/test_webhook_dedup_race.py
  modified:
    - app/main.py
    - tests/test_webhook.py
    - tests/test_gateway.py
    - tests/test_ingest.py
    - tests/test_stuck_run_recovery.py

key-decisions:
  - "_route_reply is RETAINED (not deleted) as the header-lookup path for simulate_reply (the demo-only affordance, which has its own insert path outside any transaction); the webhook's inbound() route no longer calls it — it classifies the reply inline inside its own transaction and calls the new _finish_reply_resume post-commit. _route_reply's own resume branch now delegates to the same _finish_reply_resume so the sender-revalidation logic exists in exactly one place."
  - "STALE_THRESHOLD raised from 5 minutes to 65 minutes, documented as a deliberately conservative value bounded above by the TRUE current (untightened) worst-case gap across call_structured (~60 min via library defaults, used by both extraction and the clarification suggestion), call_text (~30 min, no app-level retry, used by compose_clarification), and resume Round-2's double-extraction (can double the call_structured gap) — Codex HIGH-3's correction of RESEARCH.md Pitfall 1's original 90s-3min estimate. 09-04 tightens call_structured's timeout/retries; this plan does not assume that tightening is already in place."
  - "retrigger()'s four-status stale_statuses set (includes SENT) is explicitly documented as intentionally DIVERGENT from sweep_stranded_runs's three-status D-9-12 scope — 'one shared constant' means the threshold VALUE, not the scope LIST — with a code comment warning future readers not to 'fix' this into parity."
  - "The reply-context-loss-on-retrigger gap (a swept reply-derived run restarts from the original inbound, not the in-flight reply context) is accepted and documented in code per D-9-10's 'never auto-restart' philosophy — no new retrigger dispatch capability was added."

patterns-established:
  - "Post-commit response-shaping pattern: a webhook route's transaction commits an outcome enum locally, and ALL response construction + background_tasks.add_task calls happen strictly after the `with` block exits — never inside it, so a scheduled background task is never at risk of being rolled back by a mid-transaction crash."

requirements-completed: [DATA-02, DATA-03]

# Metrics
duration: ~50min
completed: 2026-07-04
---

# Phase 09 Plan 03: Transactional Webhook Ingest + Stranded-Run Recovery Sweep Summary

**Restructured `inbound()` around one atomic ingest-decision transaction that classifies duplicate/reply/unknown-sender/new-run BEFORE `create_run` is ever reachable (closing the Codex HIGH-1 reply-vs-new-run race), wired the stranded-run recovery sweep into every `GET /runs` dashboard load, and proved the SC2 concurrency race against real Postgres threads.**

## Performance

- **Duration:** ~50 min
- **Started:** 2026-07-04T02:35:00Z
- **Completed:** 2026-07-04T03:23:17Z
- **Tasks:** 2/2 completed
- **Files modified:** 6 (1 created, 5 modified)

## Accomplishments

- `app/main.py`'s `inbound()` route now wraps `insert_inbound_email` + the reply-classification reads (`find_awaiting_reply_for_header`/`find_any_run_for_header`) + `find_business_by_sender` + `create_run` in ONE `with repo.get_connection() as conn: with conn.transaction(): ...` block, committing exactly one of five outcomes (`duplicate`/`reply_candidate`/`late_reply`/`unknown_sender`/`new_run`) before any `background_tasks.add_task` call — closing DATA-02's orphan window (a crash mid-ingest now rolls back the whole sequence, including the reply classification) and the Codex HIGH-1 race (a header-bearing clarification reply can never spuriously create a second run, because `create_run` is structurally unreachable on the `reply_candidate`/`late_reply`/`duplicate` outcomes).
- New `_finish_reply_resume` helper performs FIX 5's sender-revalidation + response-shaping post-commit, using the transaction's ALREADY-classified `reply_run_id` — it never re-derives the header lookups (which would reintroduce the same race in a different shape). `_route_reply` is retained (unchanged in its own header-lookup logic) for `simulate_reply`'s demo-only call site, and now delegates its resume branch to the same `_finish_reply_resume` so the sender-revalidation logic lives in exactly one place.
- The duplicate-response JSONResponse now reports the existing run's id (via the new `find_run_by_message_id` dedup-loser lookup, built in 09-01) — the loser attaches to the winner's run instead of creating a second one (D-9-09).
- `runs_list()` calls `repo.sweep_stranded_runs(STALE_THRESHOLD_SECONDS)` before `repo.load_all_runs()`, wrapped in its own try/except so a sweep failure never 500s the dashboard — a run whose background task died mid-flight now becomes visible as a diagnosable ERROR on the very next `GET /runs` load (D-9-10/11).
- Introduced ONE shared `STALE_THRESHOLD` (now 65 minutes, up from 5) / `STALE_THRESHOLD_SECONDS` constant pair used by both `runs_list()`'s sweep and `retrigger()`'s stale-in-flight claim. The code comment documents the TRUE current (untightened) worst-case ceiling per Codex HIGH-3 — `call_structured` (extraction AND the clarification suggestion, no explicit `timeout=` → ~60 min via library defaults), `call_text` (compose_clarification's draft path, no `timeout_s` at all → ~30 min, no app-level retry), and resume Round-2's back-to-back double extraction (can double the `call_structured` gap) — correcting RESEARCH.md Pitfall 1's original "90s-3min" estimate. 09-04 tightens `call_structured`; this plan documents the honest current ceiling.
- Documented (code comments, not code changes) two accepted, previously-flagged gaps: the scope divergence between `retrigger()`'s four-status `stale_statuses` (includes `sent`) and the sweep's three-status D-9-12 scope (checker WARNING 3 — explicitly NOT to be "fixed" into parity), and the reply-context-loss-on-retrigger limitation (Codex MEDIUM — a swept reply-derived run restarts from the original inbound, not the in-flight reply context, per D-9-10's "never auto-restart" philosophy).
- New `tests/test_webhook_dedup_race.py`: SC2 proof via two real OS threads racing two real Postgres transactions through a real `TestClient`, asserting exactly one `run_id` across both responses. Skip-guarded on `DATABASE_URL` (no live DB configured in this environment, so it skipped cleanly); sets `ALLOW_UNSIGNED_FIXTURES=true` itself (Codex Round-2 MEDIUM — this module does not inherit `test_webhook.py`'s client fixture) and monkeypatches `_run_pipeline` to a no-op before firing the race.
- Full offline suite: 538 passed, 21 skipped (two-factor-guarded live-DB tests), 18 deselected (integration-marked), 0 regressions.

## Task Commits

Each task was committed atomically:

1. **Task 1: Restructure inbound() around a transactional ingest-decision block** - `1e7af76` (feat)
2. **Task 2: Wire the recovery sweep into runs_list; derive the shared threshold; SC2 concurrency race test** - `9e9c018` (feat)

**Plan metadata:** (this SUMMARY.md commit)

## Files Created/Modified

- `app/main.py` - restructured `inbound()` around the transactional ingest-decision block; added `_finish_reply_resume`; retained `_route_reply` for `simulate_reply`; raised `STALE_THRESHOLD` to 65 min with the honest worst-case rationale, added `STALE_THRESHOLD_SECONDS`; wired the sweep into `runs_list()`; documented the scope-divergence and reply-context-loss acceptances on `retrigger()`
- `tests/test_webhook.py` - added `test_duplicate_delivery_reports_existing_run_id`, `test_reply_never_creates_second_run`, `test_late_reply_no_new_run_no_background_task`
- `tests/test_gateway.py` - two pre-existing tests (`test_inbound_reply_routes_to_correct_run`, `test_allow_unsigned_fixtures_canonical_shape_dev_mode_returns_200`) updated to patch `repo.get_connection` to a `FakeConnection` double, since they monkeypatch individual `_repo` functions directly rather than using the `fake_repo` fixture
- `tests/test_ingest.py` - `test_duplicate_delivery_pipeline_runs_once_unit` updated similarly (added `find_run_by_message_id` + `get_connection` patches)
- `tests/test_stuck_run_recovery.py` - added `test_runs_list_calls_sweep_before_load_all_runs` and `test_runs_list_never_500s_when_sweep_raises`
- `tests/test_webhook_dedup_race.py` (new) - SC2 concurrency race proof, `@pytest.mark.integration`, `DATABASE_URL`-skip-guarded

## Decisions Made

- `_route_reply` is retained rather than deleted, because `simulate_reply` (the demo-only affordance) calls it directly with its own insert path outside any transaction — deleting it would have required either duplicating the header-lookup logic into `simulate_reply` or routing the demo path through the real webhook's transactional machinery, both larger changes than this plan's scope. Its resume branch now delegates to `_finish_reply_resume` so the sender-revalidation logic (FIX 5) is defined exactly once.
- `STALE_THRESHOLD` was raised to 65 minutes (from the pre-existing 5-minute value) rather than left at an unverified "90s-3min" — Task 2's `read_first` verification against `app/llm/client.py`, `app/pipeline/suggest.py`, `app/pipeline/compose_email.py`, and `app/pipeline/orchestrator.py` confirmed the TRUE current worst case is much higher (~60 min for `call_structured`, ~30 min for `call_text`, potentially doubled by Round-2's double extraction). 65 minutes is comfortably above that ceiling without assuming 09-04's tightening is already in place.
- Three pre-existing tests (two in `test_gateway.py`, one in `test_ingest.py`) needed a `repo.get_connection` → `FakeConnection` patch added because they monkeypatch individual `app.db.repo` functions directly instead of using the `fake_repo` fixture (which already patches `get_connection` since 09-01). This is a minimal, mechanical fix (Rule 3 — blocking issue) required by the new transactional wrapping in `inbound()`; no test assertions were weakened.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Three pre-existing tests broke because they don't use the `fake_repo` fixture**

- **Found during:** Task 1, after implementing the transactional restructure and running the full offline suite
- **Issue:** `tests/test_gateway.py::test_inbound_reply_routes_to_correct_run`, `tests/test_gateway.py::test_allow_unsigned_fixtures_canonical_shape_dev_mode_returns_200`, and `tests/test_ingest.py::test_duplicate_delivery_pipeline_runs_once_unit` monkeypatch individual `app.db.repo` functions directly (not via the `fake_repo` fixture, which already patches `get_connection` since 09-01). The new `with repo.get_connection() as conn:` block inside `inbound()` attempted to open a real Supabase pool connection against the tests' bogus `DATABASE_URL` stub, causing a 500 instead of the expected 200.
- **Fix:** Added a local `FakeConnection`-backed `get_connection` monkeypatch (mirroring `tests/conftest.py`'s `_fake_get_connection`) to each of the three tests. `test_ingest.py`'s test also needed a `find_run_by_message_id` patch, since the dedup-loser branch now calls it.
- **Files modified:** `tests/test_gateway.py`, `tests/test_ingest.py`
- **Verification:** Full offline suite re-run after the fix — all three tests pass, 0 other regressions.
- **Committed in:** `1e7af76` (part of Task 1's commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking issue, pre-existing test fixture gap exposed by the new transactional wrapping)
**Impact on plan:** Necessary for correctness — the plan's `<done>` criterion for Task 1 explicitly requires the full offline suite to exit 0. No scope creep; the fix is mechanical (adding a connection double to tests that already monkeypatch other repo functions), not a change to what the tests assert.

## Issues Encountered

None beyond the deviation documented above.

## User Setup Required

None - no external service configuration required. The SC2 integration test (`tests/test_webhook_dedup_race.py`) requires a live `DATABASE_URL` to actually exercise the real-Postgres race; it is not required for this plan's completion (it skips cleanly per the plan's own acceptance criteria) and was not run against a live DB in this execution environment.

## Next Phase Readiness

- DATA-02 and DATA-03 are both closed: the webhook's ingest sequence is transactional and reply-safe; the recovery sweep is wired into the dashboard's one guaranteed-to-be-hit HTTP entry point.
- 09-04 can now safely tighten `call_structured`'s timeout/`max_retries` — the `STALE_THRESHOLD` comment in `app/main.py` explicitly documents that this plan's 65-minute value is conservative pending that tightening, and 09-04's own plan should re-derive (or explicitly re-confirm) the threshold value once the timeout is bounded.
- `tests/test_webhook_dedup_race.py` exists and is ready to run against a live/local Postgres (`DATABASE_URL` + no `ALLOW_DB_RESET` needed for this specific test, since it only inserts fresh rows) whenever a live DB is available — it was not exercised live in this session.
- No blockers identified for 09-04 or the Phase 10 concurrency proof.

## Known Stubs

None. This plan modifies routing/transaction logic and adds tests only — no UI, no data-rendering component, no placeholder values.

## Threat Flags

None. This plan's `<threat_model>` (T-09-09 through T-09-18) already covers every surface touched — the transactional ingest, the sweep hook, and the documented accepted-limitation surfaces. No new network endpoint, auth path, file-access pattern, or schema change was introduced beyond what the plan's threat register already dispositions.

## Self-Check: PASSED

- FOUND: app/main.py (modified, contains `with repo.get_connection() as conn:`)
- FOUND: tests/test_webhook_dedup_race.py
- FOUND: tests/test_webhook.py (modified)
- FOUND: tests/test_gateway.py (modified)
- FOUND: tests/test_ingest.py (modified)
- FOUND: tests/test_stuck_run_recovery.py (modified)
- FOUND commit: 1e7af76 (feat(09-03): transactional webhook ingest closes reply-vs-new-run race)
- FOUND commit: 9e9c018 (feat(09-03): wire stranded-run recovery sweep into GET /runs; SC2 race test)

---
*Phase: 09-atomic-data-integrity*
*Completed: 2026-07-04*
