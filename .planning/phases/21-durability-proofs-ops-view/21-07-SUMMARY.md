---
phase: 21-durability-proofs-ops-view
plan: 07
subsystem: infra
tags: [health-probe, alarm, pump, github-actions, fastapi, ops-view]

# Dependency graph
requires:
  - phase: 21-durability-proofs-ops-view
    plan: "02"
    provides: "app.db.repo.list_unaccounted_error_runs — the equality-correlated alarm predicate, proven live against real Postgres on both the silent and firing sides, with its late-settling-job false-negative regression test passing"
provides:
  - "GET /health/queue — a fourth, unauthenticated health probe surfacing list_unaccounted_error_runs wholesale: 200 clear, 503 firing with a bounded count, 503 generic on DB failure"
  - "pump.yml's final always()-guarded curl -f step against /health/queue, positioned after the unconditional drain so recovery always runs first"
  - "TestAlarmStepOrdering — structural (parsed-YAML) pins that the alarm step sits after the drain, is last, shares the sibling health steps' always() guard, and that the drain step carries no if: key"
affects: [21-06, 21-09, docs/DURABILITY-PROOFS.md]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A fourth independent health probe rather than folding a new condition into an existing one — pump.yml already depends on /health/ready and /health/schema carrying distinct, non-overlapping meanings; a shared red signal would be ambiguous about which of two unrelated problems fired."
    - "Route adds zero logic of its own: it calls the facade predicate function directly and maps empty/non-empty to 200/503, inheriting the predicate's correctness entirely rather than re-deriving or widening it."

key-files:
  created:
    - tests/test_health_queue_alarm.py
  modified:
    - app/routes/health.py
    - .github/workflows/pump.yml
    - tests/test_pump_workflow.py

key-decisions:
  - "Firing-case body is exactly {\"status\": \"unaccounted_errors\", \"count\": N} — no run ids, no error_reason, no error_detail — pinned by a dedicated exact-key-set test so an added field reds rather than silently widening disclosure."
  - "DB-unreachable case returns 503 {\"detail\": \"queue check unavailable\"}, matching /health/schema's failure-branch shape exactly (generic detail, exception type name only in logs, never str(exc))."
  - "Followed 21-02's own precedent (its Deviation #1) and wrote the new docstrings/comments in app/routes/health.py, .github/workflows/pump.yml, and tests/test_health_queue_alarm.py with NO decision-ID/ticket/planning-doc citations — this repo's comment-provenance guard forbids exactly that citation shape, and the design argument is preserved in prose instead."

requirements-completed: []  # OPS-01 is not yet complete — the live checkpoint (Task 3) is still pending.

coverage:
  - id: D1
    description: "GET /health/queue returns 200 when there are no unaccounted error runs, and 503 with a bounded count when there are"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_health_queue_alarm.py::test_health_queue_no_unaccounted_errors_returns_200, ::test_health_queue_unaccounted_errors_returns_503_with_count, ::test_health_queue_clear_case_returns_200_and_firing_case_returns_503"
        status: pass
    human_judgment: false
  - id: D2
    description: "The firing-case response body discloses only a status and a count — no run id, no error text, no connection string, no stack trace"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_health_queue_alarm.py::test_health_queue_firing_body_keys_are_exactly_the_minimal_set, ::test_health_queue_firing_body_carries_no_run_id_or_error_detail_text, ::test_health_queue_db_error_returns_503_no_leak"
        status: pass
    human_judgment: false
  - id: D3
    description: "The three pre-existing health contracts (/health/live, /health/ready, /health/schema) are unweakened and unconflated by this change"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_health_queue_alarm.py::test_health_live_still_returns_200_ok, ::test_health_ready_still_returns_200_ready, ::test_health_ready_still_returns_503_no_leak_on_db_failure, ::test_health_schema_still_returns_200_in_sync, ::test_health_schema_still_returns_503_drift_with_missing"
        status: pass
    human_judgment: false
  - id: D4
    description: "pump.yml's alarm step is structurally positioned after the drain, is the last step, shares the sibling health steps' always() guard, and the drain step itself carries no if: key at all"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_pump_workflow.py::TestAlarmStepOrdering (5 tests: runs_after_the_drain_step, is_the_last_step, carries_the_same_always_guard, drain_step_carries_no_if_key, uses_the_failing_curl_form)"
        status: pass
    human_judgment: false
  - id: D5
    description: "A real workflow run proves the drain executes while the alarm is firing, and the live baseline of pre-existing unaccounted error runs (if any) is counted and each row explicitly dispositioned before the cron alarm is relied upon"
    requirement: "OPS-01"
    verification: []
    human_judgment: true
    rationale: "Requires live RENDER_URL access, a live Supabase query, and a manual workflow_dispatch trigger against the real GitHub Actions run log — none of which this worktree has credentials for (no .env, explicit prohibition on touching Supabase), and the baseline-disposition decision is an operator judgment call by design (no automated mute is permitted). This is Task 3's pending checkpoint; see 'Pending Human Checkpoint' below."

# Metrics
duration: ~25min (autonomous tasks; Task 3 pending)
completed: 2026-07-20
---

# Phase 21 Plan 07: The Cron-Checkable Alarm Endpoint Summary

**A new unauthenticated `GET /health/queue` probe surfaces the unaccounted-error-run predicate as a 200/503 signal (body: `status` + a bare `count`, nothing else), wired as the final `always()`-guarded `curl -f` step in `pump.yml` — positioned after the unconditional drain so recovery always runs first. The live-baseline disposition and the real-workflow drain-while-firing proof are a pending human checkpoint (Task 3), not yet performed.**

## Performance

- **Duration:** ~25 min (autonomous tasks 1–2)
- **Tasks:** 2 of 3 autonomous tasks complete; Task 3 = PENDING human-verify checkpoint
- **Files modified:** 3 (1 created: `tests/test_health_queue_alarm.py`)

## Accomplishments

- **`app/routes/health.py` (Task 1)** gains `GET /health/queue`: calls `repo.list_unaccounted_error_runs()` with no arguments (default `limit=50`), maps an empty result to `200 {"status":"ok"}`, a non-empty result to `503 {"status":"unaccounted_errors","count":N}`, and any exception to `503 {"detail":"queue check unavailable"}` with only the exception's type name logged — matching `health_schema`'s exact disclosure discipline. The route adds a new `from app.db import repo` import; the bodies of `health_live`, `health_ready`, and `health_schema` are untouched (`git diff` shows additions plus one import line only).
- **`tests/test_health_queue_alarm.py` (Task 1, new)** — 11 hermetic tests via `TestClient`, monkeypatching `repo.list_unaccounted_error_runs` directly (the same seam-patching idiom `tests/test_pump_route.py` uses for `repo.claim_job`/`repo.count_open_jobs`, not the `fake_repo` fixture, since this route has exactly one repo dependency and no state to seed). Covers: clear/firing/db-error status codes, the exact firing-body key set (`{"status", "count"}`), a disclosure test that plants a deliberately identifiable fake run id and error reason in the mocked rows and asserts neither string appears anywhere in the response text, and a 5-test regression pass proving `/health/live`, `/health/ready`, and `/health/schema` still return their documented statuses and bodies unchanged.
- **`.github/workflows/pump.yml` (Task 2)** gains one final step, `Check /health/queue (unaccounted-for error alarm — never gates recovery)`, appended after the two existing health steps: `if: ${{ always() }}` (byte-identical guard shape to its siblings), `curl -f --max-time 90 "$RENDER_URL/health/queue"`, `RENDER_URL` supplied through the same `env:` block shape as the sibling steps. The drain step above it is untouched — still carries no `if:` key, still runs unconditionally. No existing step was reordered or modified.
- **`tests/test_pump_workflow.py` (Task 2)** gains `TestAlarmStepOrdering`, a 5-test class parsing the workflow YAML structurally (never by text substring): the alarm step's index is greater than the drain step's index; the alarm step is the last step in the list; the alarm step's `if` value equals the sibling health steps' guard exactly; the drain step carries **no** `if` key at all (a dedicated assertion naming the exact regression this repo has already been bitten by once); and the alarm step's `run` uses the failing-curl form (`curl -f`).

## Task Commits

1. **Task 1: Add the GET /health/queue alarm endpoint** — `0ec4d23` (feat)
2. **Task 2: Wire the alarm into pump.yml last, and pin the ordering** — `9d17ce1` (feat)
3. **Task 3 (checkpoint): Human verification — live baseline + drain-while-firing proof** — PENDING human-verify checkpoint (NOT executed; see "Pending Human Checkpoint" below)

## Files Created/Modified

- `app/routes/health.py` — `GET /health/queue` route + `health_queue()` handler; one new import (`from app.db import repo`).
- `tests/test_health_queue_alarm.py` (new) — 11 hermetic tests over the new route plus a regression pass over the three pre-existing health routes.
- `.github/workflows/pump.yml` — one appended `always()`-guarded `curl -f` step against `/health/queue`, last in the steps list.
- `tests/test_pump_workflow.py` — `TestAlarmStepOrdering` (5 tests), structural pins over the parsed YAML.

## Predicate Gate Confirmation (required by this plan before writing the route)

Confirmed directly in `.planning/phases/21-durability-proofs-ops-view/21-02-SUMMARY.md`:

- The equality correlation shipped as specified: `list_unaccounted_error_runs` correlates `jobs.updated_at = payroll_runs.updated_at` (never `>=`), per that summary's `key-decisions` entry and its D2 coverage entry.
- The late-no-op-job false-negative regression test is present and passing: `tests/test_ops_alarm_predicate.py` (8 tests) includes it, run live against real Postgres — `8 passed, 0 skipped` (21-02-SUMMARY's "Live-Postgres Proof Details" section).

This route was therefore written — it was not stopped/reported per the plan's gating instruction, because the confirmation was present and affirmative.

## Decisions Made

- **Firing-case body keys are `{"status", "count"}` exactly**, pinned by a dedicated test so a future added field (e.g. a run id "for convenience") reds instead of silently widening disclosure.
- **DB-unreachable case matches `/health/schema`'s exact failure shape** (`503 {"detail": "queue check unavailable"}`, exception type name only in the log line) rather than inventing a new failure body shape.
- **Comment-provenance guard compliance (see Deviations below):** followed plan 21-02's own precedent and wrote every new docstring/comment without decision-ID (`D-13`, `D-14`, `D-16`), ticket (`OPS-01`), or planning-doc (`21-02-SUMMARY.md`, `CONTEXT.md`) citations — this repo's `tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree` forbids that citation shape in source comments and would have reded on first draft. The design argument itself (why a new route, why equality not `>=`, why no mute) survives in prose; only the citation labels were removed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Initial docstrings/comments cited decision IDs, tripping the comment-provenance guard**
- **Found during:** Task 1's own verification run (`uv run pytest tests/test_comment_provenance_guard.py -q`), before either task's commit.
- **Issue:** The first drafts of `health_queue()`'s docstring and `tests/test_health_queue_alarm.py`'s module docstring cited `D-13`, `D-14`, `D-16`, and `21-02-SUMMARY.md`/`SUMMARY.md` directly — exactly the citation shape `test_no_ticket_provenance_in_source_tree` forbids (confirmed as a pre-existing, live-enforced guard, not something this plan introduced). Plan 21-02's own SUMMARY documents hitting and auto-fixing the identical class of violation.
- **Fix:** Rewrote both docstrings to state the underlying design constraint in prose (why a fourth route, why the correlation must stay equality-only, why there is no mute/acknowledge/lookback-window) with no ID/phase/filename citations. The reasoning is preserved verbatim in meaning.
- **Files modified:** `app/routes/health.py`, `tests/test_health_queue_alarm.py`.
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py -q` → 5 passed, before Task 1's commit.
- **Committed in:** `0ec4d23` (Task 1 commit — caught and fixed before the commit was made, so the committed docstrings never carried the violation).

---

**Total deviations:** 1 auto-fixed (Rule 1, caught by this task's own mandated verification step before commit).
**Impact on plan:** None — no behavior changed, only comment/docstring text.

## Verification Run (Tasks 1–2, autonomous scope)

- `uv run pytest tests/test_health_queue_alarm.py tests/test_health_schema.py -v` → **14 passed**.
- `uv run pytest tests/test_pump_workflow.py -v` → **10 passed**, `TestAlarmStepOrdering`'s 5 tests visible individually.
- `uv run pytest tests/test_comment_provenance_guard.py -q` → **5 passed**.
- `uv run mypy app/routes/health.py` → clean. `uv run mypy --strict app` → clean (73 files).
- `uv run ruff check app/routes/health.py tests/test_health_queue_alarm.py` and `uv run ruff check .` (whole repo) → clean.
- `env -u DATABASE_URL uv run pytest -q` (full hermetic suite) → **1223 passed, 104 skipped** (baseline 1212 passed / 104 skipped + this plan's 11 new hermetic tests; skip count exactly unchanged).
- `uv run pytest tests/ -m "not integration and not live_llm" -q` → **1228 passed, 1 skipped, 103 deselected**.
- `git diff app/routes/health.py` → additions plus one import line only; the bodies of `health_live`, `health_ready`, `health_schema` are byte-identical to before.
- `git diff --stat .github/workflows/ci.yml .github/workflows/concurrency-proof.yml` → empty (byte-unchanged, as required).
- Route-inventory check: the plan's literal one-liner (`sorted(r.path for r in app.routes if ...)`) prints `[]` in this environment because FastAPI 0.138's `app.include_router()` now wraps included routers in a lazy `_IncludedRouter` object rather than flattening routes directly onto `app.routes` — a pre-existing environment quirk unrelated to this change (the same command would have printed `[]` for the three pre-existing health routes before this plan, too). Verified instead by walking each `_IncludedRouter.original_router.routes`, which correctly prints `['/health/live', '/health/queue', '/health/ready', '/health/schema']`, and independently by every `TestClient(app).get(...)` call in the test suite actually resolving and passing.
- Structural pump.yml checks: `d < len(st)-1, 'if' not in st[d], st[-1].get('if')` → `True True ${{ always() }}`. YAML still parses (`yaml.safe_load` → `'parsed'`).

## Pending Human Checkpoint (Task 3)

**Not performed in this session.** This worktree has no `.env`, is explicitly prohibited from pointing any command at Supabase, and has no `RENDER_URL`/GitHub Actions access — none of which Task 3 can substitute around, since its whole purpose is proving two properties no unit test in this plan (or any worktree) can establish:

1. **The live baseline count and per-row disposition.** Query `repo.list_unaccounted_error_runs()` against the live database, record the count and run ids, and decide — for each — one of exactly three dispositions: retriggered, terminally settled, or intentionally retained. This is a condition of approval per the plan, not a follow-up, and it requires an operator's judgment call that is deliberately not automated.
2. **The drain-runs-while-the-alarm-is-firing proof.** Trigger `pump.yml` manually via `workflow_dispatch` with at least one unaccounted error run present, and confirm in the real run log that the drain step executed and reported its counts, the alarm step ran last and red, and the drain's execution was not skipped or short-circuited.

See the plan's Task 3 `<how-to-verify>` for the exact five-step procedure. This plan's `requirements-completed` frontmatter is deliberately left empty (`[]`) — `OPS-01` is not complete until Task 3 is approved.

## Issues Encountered

None beyond the deviation documented above.

## User Setup Required

**Human verification required before this plan can close.** The operator must:
1. Query the live baseline (`repo.list_unaccounted_error_runs()` against the live Supabase database) and record the count + run ids.
2. Hit `<RENDER_URL>/health/queue` and `<RENDER_URL>/ops` to confirm the status/banner agree with step 1's baseline and that disclosure holds (no run ids/error text in the `/health/queue` body).
3. Manually trigger `pump.yml` via `workflow_dispatch` with at least one unaccounted error run present, and confirm in the run log that the drain executed, the alarm step ran last and red, and the drain was not suppressed.
4. Disposition every baseline row from step 1 as retriggered / terminally settled / intentionally retained, and record that disposition explicitly.

Resume with a continuation agent once this is done, per the plan's `<resume-signal>`.

## Next Phase Readiness

- The code and structural test coverage for the cron-checkable alarm are complete and green; nothing here blocks plan 21-06's `/ops` banner (which consumes the same predicate independently).
- The alarm predicate itself (equality correlation, false-negative regression) was proven live in plan 21-02 and is not re-derived here.
- The plan is NOT closeable until Task 3's human checkpoint is approved with the baseline count, per-row disposition, and drain-while-firing confirmation recorded.

---
*Phase: 21-durability-proofs-ops-view*
*Completed (autonomous tasks): 2026-07-20; Task 3 = pending human checkpoint*

## Self-Check: PASSED

- FOUND: app/routes/health.py
- FOUND: tests/test_health_queue_alarm.py
- FOUND: .github/workflows/pump.yml
- FOUND: tests/test_pump_workflow.py
- FOUND: .planning/phases/21-durability-proofs-ops-view/21-07-SUMMARY.md
- FOUND commit: 0ec4d23 (task 1)
- FOUND commit: 9d17ce1 (task 2)
