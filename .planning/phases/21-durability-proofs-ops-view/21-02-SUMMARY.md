---
phase: 21-durability-proofs-ops-view
plan: 02
subsystem: data-layer
tags: [ops-view, alarm-predicate, queue-metrics, postgres, fake-repo]

# Dependency graph
requires:
  - phase: 21-durability-proofs-ops-view
    provides: "wave-0 hermetic pool fail-fast guard + 19-test repair (21-15), and the earlier wave-0 plans this plan depends_on (21-12/13/14/15) for a clean, fast baseline to build on"
provides:
  - "app.db.repo.count_jobs_by_state / oldest_due_pending_age_seconds / attempts_distribution / list_dead_letter_jobs — the four bounded, side-effect-free D-12 queue-metric reads the /ops view (plans 21-06/07) will render"
  - "app.db.repo.list_unaccounted_error_runs — the equality-correlated D-13 alarm predicate that supersedes OPS-01's literal job-success-ratio requirement, proven live against real Postgres on both the silent and firing sides"
  - "five new InMemoryRepo methods + fake_repo pairing, so plan 21-06's /ops route tests can drive all five functions without a live database"
affects: [app/db/repo/jobs.py, app/db/repo/job_settlement.py, app/db/repo/__init__.py, tests/conftest.py]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Transaction-timestamp EQUALITY (never >=) as the correlation key between a run's error transition and a job's terminal settlement — same-transaction writes share an identical now(), so equality asserts 'same event' while >= would let an unrelated later settlement vouch for an earlier unaccounted error"
    - "A boolean _error_accounted marker threaded through the in-memory fake's every status='error' writer, standing in for the real predicate's transaction-timestamp equality without needing per-statement timestamp fidelity in RAM"

key-files:
  created:
    - tests/test_ops_alarm_predicate.py
  modified:
    - app/db/repo/jobs.py
    - app/db/repo/job_settlement.py
    - app/db/repo/__init__.py
    - tests/test_repo_jobs_sql.py
    - tests/conftest.py

key-decisions:
  - "The equality-vs->= design tension from the plan's own objective is load-bearing and was kept exactly as specified: list_unaccounted_error_runs correlates jobs.updated_at = payroll_runs.updated_at, never >=, because a strictly-later unrelated settlement (the reviewed false-negative sequence: record_run_error() errors a run alone, then a lost-CAS pipeline job settles done afterwards) must not silently vouch for an earlier unaccounted error."
  - "__init__.py's facade-export lines for both tasks landed in the Task 1 commit (both jobs.py's and job_settlement.py's new names were already written to the file by the time Task 1 committed, since job_settlement.py's function was drafted in the same session before either commit). This is a pragmatic, low-risk commit-boundary call, not a scope violation — the plan's own frontmatter already lists app/db/repo/__init__.py under BOTH tasks' <files>."
  - "tests/test_threading.py's two _MiniStore monkeypatch tuples need NO edit: _MiniStore (the orchestrator/pipeline-state test double) defines none of the five new names, confirmed both by direct source inspection and by the mechanized test_threading_ministore_patch_sets_are_complete guard passing unchanged."

requirements-completed: [OPS-01]

coverage:
  - id: D1
    description: "Four bounded, side-effect-free queue-metric reads (count split by state, oldest-due-pending age, attempts distribution, bounded dead-letter list) exist and are hermetically shape-tested"
    verification:
      - kind: unit
        ref: "tests/test_repo_jobs_sql.py (15 new tests: count_jobs_by_state x3, oldest_due_pending_age_seconds x3, attempts_distribution x2, list_dead_letter_jobs x2, facade/conn-ctx x1 covering all four)"
        status: pass
    human_judgment: false
  - id: D2
    description: "The D-13 predicate is an equality-correlated anti-join, proven live-Postgres silent on all three legitimate settlement paths and firing on all five unaccounted shapes including the late-no-op-job false-negative regression and the settle_background_terminal() classification"
    verification:
      - kind: integration
        ref: "tests/test_ops_alarm_predicate.py (8 tests, DATABASE_URL=postgresql://pnhek@localhost:5432/pa_p21_02 ALLOW_DB_RESET=1) — 8 passed, 0 skipped"
        status: pass
    human_judgment: false
  - id: D3
    description: "All five new facade names are paired into the fake-repo inventory; the pairing guard is green; test_threading.py's tuple count and _MiniStore tuples are unchanged"
    verification:
      - kind: unit
        ref: "tests/test_fake_repo_pairing.py -v (10 passed, 1 skipped — the skip is the expected hermetic-only pool-inertness test under a real DATABASE_URL, not a miss)"
        status: pass
    human_judgment: false
  - id: D4
    description: "No regression: hermetic suite, -m queueproof, full live-DB suite, mypy --strict app, and ruff all stay at baseline plus this plan's own additions"
    verification:
      - kind: unit
        ref: "env -u DATABASE_URL uv run pytest -q -> 1202 passed, 104 skipped (baseline 1191/96 + 11 new hermetic passes + 8 new integration tests that skip hermetically)"
        status: pass
      - kind: integration
        ref: "DATABASE_URL=... ALLOW_DB_RESET=1 uv run pytest tests/ -m queueproof -q -rs -> 71 passed, 0 skipped (baseline 63 + 8); uv run pytest tests/ -q -rs -> 1303 passed, 3 skipped (baseline 1284 + 19, skip count unchanged)"
        status: pass
      - kind: unit
        ref: "uv run mypy --strict app -> clean (73 files); uv run ruff check . -> clean"
        status: pass
    human_judgment: false

# Metrics
duration: 70min
completed: 2026-07-20
status: complete
---

# Phase 21 Plan 02: Ops Data Layer & the D-13 Alarm Predicate Summary

**Five new read-only repository functions — four bounded D-12 queue-metric reads on `jobs.py` and the D-13 equality-correlated unaccounted-error anti-join on `job_settlement.py` — proven live against real Postgres on both the silent (legitimate settlement) and firing (unaccounted error) sides, with all five names paired into the fake-repo test double.**

## Performance

- **Duration:** ~70 min
- **Tasks:** 3
- **Files modified:** 5 (1 created: `tests/test_ops_alarm_predicate.py`)

## Final Function Signatures

```python
# app/db/repo/jobs.py
def count_jobs_by_state(conn: psycopg.Connection | None = None) -> dict[str, int]
def oldest_due_pending_age_seconds(conn: psycopg.Connection | None = None) -> float | None
def attempts_distribution(conn: psycopg.Connection | None = None) -> list[tuple[int, int]]
def list_dead_letter_jobs(limit: int = 50, conn: psycopg.Connection | None = None) -> list[dict[str, Any]]

# app/db/repo/job_settlement.py
def list_unaccounted_error_runs(limit: int = 50, conn: psycopg.Connection | None = None) -> list[dict[str, Any]]
```

## The Alarm SQL (exact, for plans 21-06/21-07 to consume)

```sql
SELECT id, error_reason, updated_at FROM payroll_runs
 WHERE status = 'error' AND NOT EXISTS (
   SELECT 1 FROM jobs
    WHERE jobs.run_id = payroll_runs.id
      AND jobs.state IN ('done', 'dead')
      AND jobs.updated_at = payroll_runs.updated_at
 ) ORDER BY payroll_runs.updated_at DESC LIMIT %s
```

Projects only `id`, `error_reason`, `updated_at` (never `error_detail` — the operator follows the run-detail link for that, per the operator gate's existing honest-3-column design). Correlation is **equality**, never `>=`, in both directions.

## Task Commits

1. **Task 1: D-12 queue-metric reads on jobs.py** — `06a47e6` (feat)
2. **Task 2: D-13 alarm predicate on job_settlement.py** — `49ecbf1` (feat)
3. **Task 3: fake-repo pairing** — `a8831f0` (test) — also carries a Rule-1 comment-provenance fix caught by this task's own mandated full-suite run (see Deviations)

## Files Created/Modified

- `app/db/repo/jobs.py` — `count_jobs_by_state`, `oldest_due_pending_age_seconds`, `attempts_distribution`, `list_dead_letter_jobs`; module docstring's function-count inventory corrected (it already understated the true count at "eight" pre-plan — ten functions existed; now "twelve" and accurate).
- `app/db/repo/job_settlement.py` — `list_unaccounted_error_runs`, with the full design argument (why equality not `>=`, why the D-16 shape stays silent, why `settle_background_terminal()` is classified as unaccounted, why the approve-route boundary is a true positive) recorded in its docstring.
- `app/db/repo/__init__.py` — five new names imported and added to `__all__`.
- `tests/test_repo_jobs_sql.py` — 15 new hermetic SQL-shape tests covering all four `jobs.py` functions plus a facade/conn-ctx contract test.
- `tests/test_ops_alarm_predicate.py` (new) — 8 live-Postgres tests, `pytest.mark.integration` + `pytest.mark.queueproof` (not `proof` — deliberately not one of the four durability proofs plan 21-09 inventories).
- `tests/conftest.py` — five new `InMemoryRepo` methods; `created_at`/`updated_at`/`available_at` threaded through fake job rows; an `_error_accounted` boolean marker threaded through every fake status='error' writer (`record_run_error`, `settle_pipeline_job`'s two error branches, `settle_background_terminal`, `reap_expired_final_attempt`'s final-lease-error branch) so the fake mirrors the real equality correlation without needing per-statement timestamp fidelity; all five names added to the `fake_repo` fixture's monkeypatch tuple.

## Fake-Repo Pairing — Grep Gate Results

Per name, across all three monkeypatch inventories:

| Name | `tests/test_threading.py` occurrences | `tests/conftest.py` occurrences |
|---|---|---|
| `count_jobs_by_state` | 0 | 4 |
| `oldest_due_pending_age_seconds` | 0 | 4 |
| `attempts_distribution` | 0 | 4 |
| `list_dead_letter_jobs` | 0 | 4 |
| `list_unaccounted_error_runs` | 0 | 9 |

**The `0` in `tests/test_threading.py` is correct, not a miss.** `_MiniStore` (the orchestrator/pipeline-state test double that file's two tuples wire in) defines none of these five methods — it covers the pipeline-state seam (extraction/decision/reconciliation persistence), not the ops-metric seam. Verified two ways: (1) direct source inspection of `_MiniStore`'s method list (`load_run`, `load_source_email`, `load_roster_for_business`, `set_status`, `claim_status`, `record_run_error`, `persist_extracted`, `persist_decision`, `persist_reconciliation`, `replace_line_items`, `load_pre_clarify_extracted`, `load_clarified_fields`, `set_pre_clarify_extracted`, `set_clarified_fields`, `set_hours_changes`, `get_clarification_round`, `mark_reply_consumed`, `load_consumed_replies` — none of the five new names among them); (2) the mechanized `test_threading_ministore_patch_sets_are_complete` guard, which would fail red if `_MiniStore` defined a shadowing method missing from either tuple, and instead passed unchanged. `grep -c 'for name in (' tests/test_threading.py` still outputs exactly `2` — the tuple count is untouched.

`tests/conftest.py`'s `fake_repo` fixture's monkeypatch tuple carries all five name strings (>= 1 each, confirmed above); `test_every_inmemory_method_that_shadows_a_real_repo_name_is_actually_patched` (the general, unconditional pairing guard — not scoped to the `_DURABLE_RECOVERY_SYMBOLS` allowlist) passed, confirming every public `InMemoryRepo` method that also exists on `app.db.repo` resolves through the facade back to the fake, for all five new methods.

## Equality-Safety Enumeration (the check the predicate's correctness rests on)

Before finalizing the predicate, every writer of `payroll_runs.updated_at` was enumerated against the live source, checking specifically: **could any of them bump a run's `updated_at` while its `status` stays `'error'`**, breaking the equality match on an already-correctly-settled run (a false positive)?

**Direct status writers — all confirmed safe:**
- `record_run_error` (`app/db/repo/runs.py`) — its own CAS excludes every status in `_TERMINAL_STATUSES` (`sent`, `reconciled`, `rejected`, `error`); a second call against an already-`error` run is a no-op and writes nothing.
- `job_settlement.py`'s `_set_run_error` — CAS'd to a specific `expected_status` (default `EXTRACTING`, or the exact prior status the final-lease-reap branch already locked), never `error` itself; it cannot re-fire against an already-`error` run.
- `rewind_for_reclaim` (`app/db/repo/pipeline_state.py`) — its `WHERE status IN ('extracting', 'computed', 'sent')` explicitly excludes `error`.
- `claim_status` — grepped every call site across `app/`; `RunStatus.ERROR` appears only as the `expected` (FROM) argument at the retrigger route (`app/routes/runs.py:711`), never as the `new` (TO) argument anywhere. No caller CASes a run INTO `error` through `claim_status`.
- `clear_reply_context` — carries no status filter of its own, but its one production caller (the retrigger route) invokes it strictly AFTER a winning `claim_status(ERROR, RECEIVED)` claim inside the same transaction, so by the time it executes the run's status is already `received`, never `error`.

**JSONB-only writers (`pipeline_state.py`'s `persist_extracted`/`persist_decision`/`persist_reconciliation`/`set_alias_candidates`/`set_pre_clarify_extracted`/`set_clarified_fields`/`set_hours_changes`/`set_clarification_round`) carry no status gate at all.** Every one of them is called only from inside `_run_stages`, which itself only begins after `set_status(EXTRACTING)`, so under any single, non-racing execution a run is never `error` when they run. The one theoretical exception is the pre-existing, independently documented reclaimed-job double-execution hazard: a lease-expired worker's zombie predecessor can still be mid-flight in its own `_run_stages` call after a second worker has reclaimed the job and driven the run to a correctly-settled `error`; the zombie's unfenced JSONB writes could in principle bump `updated_at` afterward. This is **not a new hazard introduced by this predicate** — `tests/test_queue_durability.py`'s own module docstring already documents and accepts it ("every JSONB persist is last-write-wins by value") as a residual risk of the double-execution design, and it is consistent with the equality-over-`>=` tradeoff this plan's objective explicitly makes: a possible, narrow false positive is accepted in exchange for eliminating a real false negative.

**`operator_resume_resolutions.py`'s alias-candidate merge write** (inside `commit_operator_resume_resolution`) also carries no status gate at the SQL level, but its one route caller (`app/routes/runs.py` resolve route) requires `run.get("status") == RunStatus.NEEDS_OPERATOR.value` before entering the transaction at all — `needs_operator` is not `error`, so this writer cannot reach an `error` run through any reachable production path either.

**`demo.py`'s `set_record_only`** does not write `updated_at` at all (confirmed by reading its SQL) — not a candidate.

**Conclusion: safe.** No reachable writer, single-actor or the one documented double-execution race, can bump `updated_at` on an already-correctly-settled `error` run in a way that would falsely re-surface it as unaccounted.

## Live-Postgres Proof Details

Ran against a local throwaway Postgres (`DATABASE_URL=postgresql://pnhek@localhost:5432/pa_p21_02`, `ALLOW_DB_RESET=1`), never Supabase:

- `uv run pytest tests/test_ops_alarm_predicate.py -v -rs` → **8 passed, 0 skipped**. The `-rs` skip report is empty.
- All three legitimate-settlement tests (`settle_pipeline_job` terminal, `settle_pipeline_job` retry-exhausted, `reap_expired_final_attempt`) first assert the run genuinely reached `status='error'` before asserting the predicate is silent — so they cannot pass because nothing errored.
- The late-no-op-job test asserts the settling job's `updated_at` is **strictly greater than** the run's `updated_at` (both read via direct SQL after the fact), so it genuinely exercises the ordering a `>=` correlation would have wrongly suppressed — not merely landing both writes in one transaction by accident.
- `uv run pytest tests/ -m queueproof -q -rs` → 71 passed (baseline 63 + this plan's 8), 0 skipped.
- Full live-DB suite `uv run pytest tests/ -q -rs` → 1303 passed (baseline 1284 + 19: 11 new hermetic + 8 new integration), 3 skipped (unchanged from baseline — the pre-existing `test_claim_status.py` stub skip, the hermetic-only pool-inertness skip, and the live-LLM two-factor-guarded skip).
- Hermetic `env -u DATABASE_URL uv run pytest -q` → 1202 passed (baseline 1191 + 11 new hermetic), 104 skipped (baseline 96 + 8 — the 8 new live-Postgres tests correctly self-skip hermetically via `seeded_db`, they are not deselected).
- `uv run mypy --strict app` → clean (73 files). `uv run ruff check .` → clean (whole repo).
- `git diff --stat app/routes/` → empty; the route layer is untouched, exactly as the plan requires (it lands in plans 21-06/21-07).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Comment-provenance violations across all three new/modified source files**
- **Found during:** Task 3's mandated full-suite verification run (`uv run pytest -q`), before this plan's final commit.
- **Issue:** The docstrings and comments written in Tasks 1 and 2 (and Task 3's own new comments) cited design-decision IDs, phase references, `OPS-01`'s literal ticket form, and planning-document filenames directly in `app/db/repo/jobs.py`, `app/db/repo/job_settlement.py`, `tests/conftest.py`, and `tests/test_ops_alarm_predicate.py`. This repo's `test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree` forbids exactly that class of citation in source comments (the project's post-hygiene-pass "comments name the failure they prevent, not the ticket that fixed it" convention) — confirmed pre-existing and enforced by checking `git stash` against the two already-committed Task 1/2 commits, which also failed the guard before this fix.
- **Fix:** Rewrote every flagged comment/docstring to state the underlying constraint or design argument in prose, with no ID/phase/filename citations. The full design argument (equality vs. `>=`, why the "job done/dead + run error" shape stays silent, why `settle_background_terminal()` is classified as unaccounted, why the approve-route boundary is a true positive) is preserved verbatim in meaning — only the citation style changed.
- **Files modified:** `app/db/repo/jobs.py`, `app/db/repo/job_settlement.py`, `tests/conftest.py`, `tests/test_ops_alarm_predicate.py`.
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py -q` → 5 passed. Full hermetic and live-DB suites re-run clean after the fix (see counts above).
- **Committed in:** `a8831f0` (Task 3 commit — the fix touches Task 1/2's already-committed files, but since those commits already existed, the fix landed alongside Task 3's own mandated verification step that caught it, per Rule 1's "fix inline → verify → continue" process).

---

**Total deviations:** 1 auto-fixed (Rule 1, caught by this plan's own mandated verification step and fixed before commit).
**Impact on plan:** None — no behavior changed, only comment text. `app/routes/` untouched throughout.

## Issues Encountered

None beyond the deviation documented above.

## User Setup Required

None — no external service configuration required. The live-DB proof runs against a local throwaway Postgres the executor provisioned itself (never Supabase).

## Next Phase Readiness

- Plans 21-06 and 21-07 (the `/ops` route and the alarm surface) can now consume the exact function signatures and the exact alarm SQL recorded above.
- All five new facade names are exported, hermetically shape-tested, live-proven (the D-13 predicate), and fake-repo-paired — no blockers for the route-layer plans.
- `app/routes/` is untouched by this plan, confirmed via `git diff --stat app/routes/`.

---
*Phase: 21-durability-proofs-ops-view*
*Completed: 2026-07-20*

## Self-Check: PASSED

- FOUND: app/db/repo/jobs.py
- FOUND: app/db/repo/job_settlement.py
- FOUND: app/db/repo/__init__.py
- FOUND: tests/test_repo_jobs_sql.py
- FOUND: tests/test_ops_alarm_predicate.py
- FOUND: tests/conftest.py
- FOUND: .planning/phases/21-durability-proofs-ops-view/21-02-SUMMARY.md
- FOUND commit: 06a47e6 (task 1)
- FOUND commit: 49ecbf1 (task 2)
- FOUND commit: a8831f0 (task 3)
