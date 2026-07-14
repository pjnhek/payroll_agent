---
phase: 16-queue-substrate-unblocked-webhook
plan: 08
subsystem: infra
tags: [queue, postgres, fastapi, pytest, psycopg, concurrency]

# Dependency graph
requires:
  - phase: 16-queue-substrate-unblocked-webhook (plan 04)
    provides: "app/db/repo/jobs.py claim/lease/fencing protocol; clear_reply_context returning reply_epoch; rewind_for_reclaim"
  - phase: 16-queue-substrate-unblocked-webhook (plan 06)
    provides: "app/queue/wake.py (wake/wait/clear); app/queue/dispatch.py; app/queue/handlers/pipeline.py::handle_run_pipeline (INVARIANT J-1's two permitted CAS writers); app/queue/drain.py::drain_once()"
  - phase: 16-queue-substrate-unblocked-webhook (plan 10)
    provides: "app/pipeline/send_guard.py — the fail-closed unconfirmed-send guard both clarify() and deliver() call, which this plan's retriggered re-run must (and does) still route through"
provides:
  - "app/routes/runs.py::_claim_stale_in_flight — the conn-aware stale-in-flight claim helper, extracted so it can join retrigger()'s caller-owned transaction"
  - "app/routes/runs.py::retrigger() rewritten onto ONE transaction: the winning CAS (ERROR/APPROVED core claim or the stale in-flight claim), clear_reply_context, and enqueue_job all commit together; wake.wake() fires strictly post-commit"
  - "the retrigger producer moved off BackgroundTasks onto the durable jobs queue — QUEUE-02's producer half"
affects: [16-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "retrigger()'s three-way CAS chain (ERROR->RECEIVED or APPROVED->RECEIVED or _claim_stale_in_flight) all thread conn=conn into ONE `with repo.get_connection() as conn, conn.transaction():` block, mirroring the existing webhook.py caller-owned-transaction shape — no new plumbing needed since every repo.* function already accepts an optional conn."
    - "dedup_key = f\"run_pipeline:{run_id}:{epoch}\" where epoch is clear_reply_context's own return value — the epoch is the ONLY thing that lets a second, later retrigger enqueue a second job instead of being silently swallowed by ON CONFLICT DO NOTHING against the first retrigger's now-done job row."
    - "wake.wake() is called strictly AFTER the `with` block exits (post-commit), never inside it — the same discipline app/routes/webhook.py's ingest transaction already documents."
    - "D-06 hermetic test shape for a queue producer under WORKER_COUNT=0: POST the route, assert the durable jobs row exists (new coverage), then call drain.drain_once() explicitly to run the pipeline — deterministic, no sleeps, no polling, and it exercises the exact function a live worker calls."

key-files:
  created: []
  modified:
    - app/routes/runs.py
    - tests/test_hitl.py
    - tests/test_alias_and_run_column_regressions.py
    - tests/test_retrigger_threading.py
    - tests/test_needs_operator.py
    - tests/test_stuck_run_recovery.py

key-decisions:
  - "The stale-RECEIVED branch of _claim_stale_in_flight performs NO status write at all (a genuine behavior change from the plan's literal Step 2 pseudocode, which reused the pre-Phase-16 RECEIVED->EXTRACTING jump). Discovered live: pre-claiming EXTRACTING collided with the drained job handler's own sole forward transition (claim_status(RECEIVED -> EXTRACTING), INVARIANT J-1), silently completing the job without ever calling run_pipeline_bg — a real lost job (T-16-37), caught by migrating test_retrigger_clears_context_on_stale_inflight_claim to drain_once(). See Deviations for the full reasoning and the correctness argument for why leaving the run at RECEIVED (relying on the handler's own forward CAS for cross-click exclusivity) is safe."
  - "retrigger()'s stale_statuses AST-inspecting test (test_needs_operator_excluded_from_retrigger_stale_statuses) now inspects _claim_stale_in_flight's source, not retrigger's — a direct, unavoidable consequence of Task 1's mandated extraction."
  - "tests/test_delivery.py needed ZERO changes: its fake_conn-backed 'CAS-shape' tests call claim_status directly (never through the route), so nothing about the route's transaction consolidation touches them."

requirements-completed: [QUEUE-02]

coverage:
  - id: D1
    description: "retrigger()'s CAS claim (ERROR/APPROVED or stale in-flight), clear_reply_context, and enqueue_job all commit inside ONE caller-owned transaction; wake.wake() fires strictly post-commit; exactly one BackgroundTasks producer moved (3 -> 2 add_task call sites in app/routes/runs.py)"
    requirement: "QUEUE-02"
    verification:
      - kind: unit
        ref: "tests/test_hitl.py::test_retrigger_from_error_backgrounds_pipeline, ::test_retrigger_from_approved_backgrounds_pipeline"
        status: pass
      - kind: other
        ref: "grep -cE 'background_tasks\\.add_task\\(' app/routes/runs.py -> 2 (was 3); git diff --stat app/templates/ app/pipeline/orchestrator.py -> empty"
        status: pass
    human_judgment: false
  - id: D2
    description: "The dedup_key carries reply_epoch, so a second, later retrigger enqueues a second job rather than being swallowed by ON CONFLICT DO NOTHING against the first retrigger's now-done job row"
    requirement: "QUEUE-02"
    verification:
      - kind: unit
        ref: "tests/test_hitl.py::test_second_retrigger_enqueues_a_second_job"
        status: pass
      - kind: other
        ref: "Falsifying mutation (epoch stripped from dedup_key) executed live, RED captured, reverted — see Falsifying Mutations below"
        status: pass
    human_judgment: false
  - id: D3
    description: "The CAS, the reply-context clear, and the enqueue are genuinely atomic — a failure between the CAS commit and the enqueue must never leave a phantom 'state advanced, no job' split"
    requirement: "QUEUE-02"
    verification:
      - kind: other
        ref: "Falsifying mutation (enqueue_job moved outside the transaction + injected failure) executed live via a temporary test, RED/split captured, reverted and deleted — see Falsifying Mutations below"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every migrated retrigger test asserts the durable jobs row BEFORE calling drain_once() — new coverage for the enqueue half, not just the drain half; the pre-existing stale-retrigger CAS-exclusivity test still passes unchanged"
    requirement: "QUEUE-02"
    verification:
      - kind: unit
        ref: "tests/test_alias_and_run_column_regressions.py::test_retrigger_clears_all_reply_context, ::test_retrigger_clears_context_on_stale_inflight_claim; tests/test_retrigger_threading.py (both tests via the shared _crash_after_send_then_retrigger helper); tests/test_delivery.py::test_two_concurrent_stale_retriggers_only_one_wins"
        status: pass
      - kind: other
        ref: "grep -c drain_once tests/test_hitl.py tests/test_alias_and_run_column_regressions.py tests/test_retrigger_threading.py -> 5, 4, 2 respectively (all >= 1)"
        status: pass
    human_judgment: false
  - id: D5
    description: "The retriggered re-run does not route around the fail-closed unconfirmed-send guard from 16-10 — clarify()/delivery.py and app/pipeline/send_guard.py are byte-identical, untouched by this plan"
    requirement: "QUEUE-02"
    verification:
      - kind: other
        ref: "git diff --stat app/pipeline/send_guard.py app/pipeline/clarification.py app/pipeline/delivery.py -> empty; tests/test_send_idempotency.py 9/9 pass (incl. 2 live-DB queueproof tests)"
        status: pass
    human_judgment: false

duration: ~25min
completed: 2026-07-14
status: complete
---

# Phase 16 Plan 08: Retrigger Producer Cutover Summary

**`app/routes/runs.py::retrigger()` refactored off `BackgroundTasks` onto ONE caller-owned transaction that CAS-claims the run, clears reply context, and enqueues a durable `run_pipeline` job keyed on the fresh `reply_epoch` — with `wake.wake()` firing strictly post-commit — and, discovered live while migrating the tests, a genuine lost-job bug in the stale-RECEIVED reclaim branch fixed so it no longer collides with the queue handler's own forward CAS.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2 of 2 completed
- **Files modified:** 6 (0 created, 6 modified)

## Accomplishments

- `app/routes/runs.py::_claim_stale_in_flight(run_id, conn)`: the conn-aware extraction of retrigger's inline stale-in-flight logic — same scope (RECEIVED/EXTRACTING/COMPUTED/SENT), same DO-NOT-CONVERGE divergence from `sweep_stranded_runs`'s three-status scope, now able to join a caller-owned transaction via `conn=conn` on every repo call.
- `app/routes/runs.py::retrigger()`: rewritten onto exactly ONE `with repo.get_connection() as conn, conn.transaction():` block. The winning CAS (ERROR/APPROVED core claim or `_claim_stale_in_flight`), `clear_reply_context`, and `enqueue_job(kind=RUN_PIPELINE, dedup_key=f"run_pipeline:{run_id}:{epoch}")` all commit together — a crash anywhere in the block means nothing happened at all. `wake.wake()` fires strictly after the block exits, never inside it. The `background_tasks: BackgroundTasks` parameter is removed (retrigger no longer schedules anything into process memory); the other 7 `add_task` sites in this file and elsewhere are untouched (QUEUE-04, Phase 19).
- **A genuine bug found and fixed, not just a test-migration artifact**: the pre-Phase-16 stale-RECEIVED reclaim branch jumped straight to `EXTRACTING` (since `RECEIVED->RECEIVED` is a no-op CAS with no exclusivity) and then dispatched `run_pipeline_bg` directly and unconditionally. Under the queue, that pre-claim collides with `handle_run_pipeline`'s own sole forward transition — `claim_status(RECEIVED -> EXTRACTING)`, INVARIANT J-1 — which would find the run already at `EXTRACTING`, lose its claim, and mark the job `done` without ever calling `run_pipeline_bg`: a silent, permanent lost job for exactly the run retrigger was meant to revive (T-16-37). Fixed by having the stale-RECEIVED branch perform NO status write at all, leaving the run genuinely at `RECEIVED` — the handler's own forward CAS on drain now provides cross-click exclusivity one layer down (a harmless extra job row at worst, never a double pipeline run). See Deviations for the full correctness argument.
- Four retrigger test files migrated to the D-06 POST-then-`drain_once()` shape (workers are off, `WORKER_COUNT=0`): each asserts the durable `jobs` row exists BEFORE draining (new coverage for the enqueue half of ROADMAP criterion #2), then drains explicitly and keeps the original dispatch assertion.
- One new hermetic test, `tests/test_hitl.py::test_second_retrigger_enqueues_a_second_job`: retrigger, drain to done, re-error the run, retrigger again, assert a SECOND job row with a DIFFERENT `dedup_key` — the epoch-in-the-key falsifying-mutation target.
- Full hermetic suite green (761 passed, 2 skipped — up from the pre-plan baseline of 760/2), `mypy app`/`mypy tests` (strict) clean, `ruff check .` clean, `tests/test_comment_provenance_guard.py` and `tests/test_bound01_private_imports.py` both green, `pytest -m queueproof` 11/11 pass against the live worktree database.

## Task Commits

Each task was committed atomically:

1. **Task 1: Consolidate retrigger() into ONE transaction and enqueue the job inside it** — `5a5934e` (feat)
2. **Task 2: Migrate the hermetic retrigger tests to POST-then-drain_once(); fix the stale-RECEIVED lost-job bug** — `409896b` (test)

**Plan metadata:** committed by the orchestrator after wave merge (this executor runs in worktree mode and does not write STATE.md/ROADMAP.md).

## Files Created/Modified

- `app/routes/runs.py` — `_claim_stale_in_flight` (NEW helper); `retrigger()` rewritten onto one transaction + enqueue + post-commit wake
- `tests/test_hitl.py` — 2 retrigger tests migrated to POST-then-drain_once(); `test_second_retrigger_enqueues_a_second_job` (NEW)
- `tests/test_alias_and_run_column_regressions.py` — 2 of 3 retrigger tests migrated (the third needed no change)
- `tests/test_retrigger_threading.py` — the shared crash/recovery helper migrated (both tests use it)
- `tests/test_needs_operator.py` — [Rule 3] the stale_statuses AST-inspection test retargeted at `_claim_stale_in_flight`
- `tests/test_stuck_run_recovery.py` — [Rule 3] the live-DB SC3 recovery proof migrated to POST-then-drain_once()
- `tests/test_delivery.py` — unchanged (verified, not modified)

## Decisions Made

- The stale-RECEIVED branch's exclusivity model changed fundamentally from "a real status CAS provides exclusivity" to "no status write at all; the drained job handler's own forward CAS provides exclusivity one layer down." This is a deliberate, load-bearing departure from the plan's literal Step 1 pseudocode (which specified `target = EXTRACTING if run["status"]==RECEIVED else RECEIVED`, carried over unchanged from pre-Phase-16). The correctness argument: two concurrent retrigger clicks on the same stale RECEIVED run may now both pass the staleness check and both enqueue a job (a harmless extra row, each with its own epoch bump from `clear_reply_context`) — but `handle_run_pipeline`'s own `claim_status(RECEIVED, EXTRACTING)` is itself a genuine single-winner claim: only the job that drains first ever advances the run past RECEIVED, and every later one loses its claim and completes as a no-op, exactly like any other lost forward CAS under INVARIANT J-1. No double pipeline run is possible.
- `test_needs_operator_excluded_from_retrigger_stale_statuses` now inspects `_claim_stale_in_flight`'s source (not `retrigger`'s) for the `stale_statuses` set literal, since Task 1's mandated extraction moved that literal — the test's guarantee (needs_operator is never in the stale scope) is unchanged, only its inspection target.
- `tests/test_delivery.py`'s three CAS-shape tests at the plan's cited line numbers (`test_retrigger_claims_from_error_state`, `test_retrigger_claims_from_approved_state`, `test_retrigger_claims_from_stale_extracting_state`) call `claim_status` directly against a scripted `fake_conn` — they never drive the route, so nothing about consolidating the route's transaction touches them. Verified via a clean `git diff --stat tests/test_delivery.py` after the full migration.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] `test_needs_operator_excluded_from_retrigger_stale_statuses` broke on Task 1's mandated extraction**
- **Found during:** Task 1 verification (`uv run pytest tests/test_delivery.py tests/test_needs_operator.py tests/test_dashboard.py -q`)
- **Issue:** This pre-existing AST-based test asserted the `stale_statuses` set literal lives inside `inspect.getsource(runs_mod.retrigger)`. Task 1's own explicit instruction ("extract `_claim_stale_in_flight(run_id, conn) -> bool`") moved that literal into the new helper, so `retrigger`'s own source no longer contains any `ast.Set` node.
- **Fix:** Retargeted the test at `inspect.getsource(runs_mod._claim_stale_in_flight)`. The guarantee under test (needs_operator is never in the stale-in-flight scope) is unchanged.
- **Files modified:** `tests/test_needs_operator.py`
- **Verification:** `uv run pytest tests/test_needs_operator.py -q` → all pass.
- **Committed in:** `5a5934e` (Task 1 commit)

**2. [Rule 3 - Blocking issue] `test_stranded_run_swept_and_retriggerable` (live-DB) broke on the BackgroundTasks-synchronicity assumption**
- **Found during:** Task 1 full-suite verification
- **Issue:** This live-DB SC3 recovery proof POSTs the real `/runs/{run_id}/retrigger` route against a real Postgres and asserted `run_pipeline_bg` was dispatched synchronously via `TestClient`'s BackgroundTasks draining — an assumption that no longer holds once retrigger enqueues a job instead.
- **Fix:** Migrated to the D-06 shape: assert a `pending`/`run_pipeline` job row exists (queried directly via `get_connection()`) for the run BEFORE calling `drain.drain_once()`, then assert dispatch after the explicit drain.
- **Files modified:** `tests/test_stuck_run_recovery.py`
- **Verification:** `uv run pytest tests/test_stuck_run_recovery.py -q` → 11/11 pass (against the live worktree database).
- **Committed in:** `5a5934e` (Task 1 commit)

**3. [Rule 1 - Bug] Fixed a lost-job bug in the stale-RECEIVED reclaim branch of `_claim_stale_in_flight`**
- **Found during:** Task 2, migrating `test_retrigger_clears_context_on_stale_inflight_claim` to `drain_once()`
- **Issue:** With the plan's literal Step 1 pseudocode (stale RECEIVED claims straight to EXTRACTING, mirroring pre-Phase-16 behavior), the drained job's own `claim_status(RECEIVED -> EXTRACTING)` forward transition (INVARIANT J-1's sole permitted forward writer) found the run already at EXTRACTING, lost its claim, and completed the job WITHOUT ever calling `run_pipeline_bg` — silently stranding the exact run retrigger was meant to revive. Caught because the migrated test asserted `dispatched == [run_id]` after an explicit drain, which failed with `dispatched == []`.
- **Fix:** The stale-RECEIVED branch performs no status write at all, leaving the run genuinely at RECEIVED for the handler's own forward claim to succeed. See "Decisions Made" above for the full correctness argument for why this is safe under concurrent retrigger clicks.
- **Files modified:** `app/routes/runs.py`
- **Verification:** `uv run pytest tests/test_alias_and_run_column_regressions.py tests/test_hitl.py -q` → all pass; full suite re-run green (761 passed, 2 skipped).
- **Committed in:** `409896b` (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (2 blocking test-migration casualties directly caused by Task 1's mandated refactor; 1 real bug discovered only by driving the migrated test through an explicit drain — the exact kind of vacuous-proof gap D-06's test posture exists to catch).
**Impact on plan:** No scope creep. All three are direct, unavoidable consequences of this plan's own mandated changes, surfaced and closed within the same wave rather than deferred.

## Falsifying Mutations

Both required falsifying mutations executed against live code in this worktree, RED/anomalous output captured, then reverted. `git diff --stat app/routes/runs.py` was empty after each revert (verified explicitly).

### (a) Strip the epoch from retrigger's dedup_key

Mutated the single occurrence of `dedup_key=f"run_pipeline:{run_id}:{epoch}"` to `dedup_key=f"run_pipeline:{run_id}"` (grep-confirmed exactly one occurrence before mutating).

```
$ uv run pytest tests/test_hitl.py -q -k test_second_retrigger_enqueues_a_second_job
FAILED tests/test_hitl.py::test_second_retrigger_enqueues_a_second_job - AssertionError:
  the enqueued job's dedup_key must carry the run's CURRENT reply_epoch;
  got 'run_pipeline:d68a24c8-bd39-4bd0-bc09-d00b084367fe',
  expected 'run_pipeline:d68a24c8-bd39-4bd0-bc09-d00b084367fe:1'
1 failed, 9 deselected, 1 warning in 0.52s
```

The failure fires inside the shared `_assert_run_pipeline_job_enqueued` helper (called by the test as its first assertion) — an even more precise catch than the test's own second-job-specific assertions further down, since the epoch's absence is visible on the very FIRST enqueue already. Reverted; `git diff --stat app/routes/runs.py` empty afterward; `tests/test_hitl.py` 10/10 green re-confirmed.

### (b) Move enqueue_job outside the transaction block, inject a failure between the CAS commit and the enqueue

Mutated `retrigger()` so `repo.enqueue_job(...)` runs strictly after the `with repo.get_connection() as conn, conn.transaction():` block exits, with an unconditional `raise RuntimeError("MUTATION: ...")` inserted immediately after the block (before `enqueue_job` is ever reached). Drove it with a temporary test (`tests/test_zz_temp_atomicity_mutation.py`, written, run, then deleted — never committed):

```
$ uv run pytest tests/test_zz_temp_atomicity_mutation.py -q -s
POST-MUTATION STATE: run.status='received', jobs_for_run=0
.
1 passed, 1 warning in 0.42s
```

The temporary test's own assertions (which PASS, confirming the split occurred) prove the phantom "state advanced, no job" split QUEUE-02's single transaction exists to prevent: the CAS claim (ERROR -> RECEIVED) survived the injected failure — the run is genuinely `received` — while ZERO job rows exist for it, because `enqueue_job` was never reached. Under the real, unmutated code this cannot happen: `enqueue_job` sits INSIDE the same `with` block as the CAS, so a real crash anywhere in that block leaves nothing committed at all — no state advance without a job.

Reverted (restored the original in-transaction ordering) and deleted the temporary test file; `git diff --stat app/routes/runs.py` empty afterward; full suite re-run green (761 passed, 2 skipped).

## Issues Encountered

None beyond the deviations documented above. A live Postgres was reachable in this worktree throughout (a dedicated per-agent database), so every live-DB acceptance criterion — including `tests/test_stuck_run_recovery.py`'s SC3 recovery proof and the full `-m queueproof` selection (11/11) — was actually executed, not deferred.

## User Setup Required

None — no external service configuration required. This plan's live-DB coverage runs against the same Postgres infrastructure the `queueproof` CI gate (plan 16-02) already targets.

## Next Phase Readiness

- The retrigger producer is fully cut over: clicking Retrigger on a stuck run enqueues a durable `jobs` row atomically with the CAS that owes it, keyed so a second retrigger is never swallowed, and wakes an idle worker the instant the transaction commits (D-09).
- The stale-RECEIVED lost-job fix is a genuinely new invariant future producer-migration work (QUEUE-04, Phase 19) should carry forward: a route/handler that pre-claims a run's status ahead of enqueuing a job must land the run in EXACTLY the status the drained handler's own first-attempt forward CAS expects to find — never a status further along, or the job silently completes without doing its one job.
- `app/pipeline/send_guard.py` from 16-10 is untouched and still sits directly in the retriggered re-run's path (via `run_pipeline_bg` -> orchestrator -> `clarify()`/`deliver()`), confirmed by an empty diff on all three guard-adjacent files and a full green `tests/test_send_idempotency.py`.
- No blockers for plan 16-09 (the durability proofs) or Phase 17's pump work — `drain.drain_once()` is exercised end-to-end by this plan's own migrated tests, exactly the function both the pump and the live worker threads call.

---
*Phase: 16-queue-substrate-unblocked-webhook*
*Completed: 2026-07-14*

## Self-Check: PASSED

All 7 claimed files found on disk (app/routes/runs.py, tests/test_hitl.py,
tests/test_alias_and_run_column_regressions.py, tests/test_retrigger_threading.py,
tests/test_needs_operator.py, tests/test_stuck_run_recovery.py, this SUMMARY.md).
Both claimed commit hashes (5a5934e, 409896b) found in `git log --oneline --all`.
No missing items.
