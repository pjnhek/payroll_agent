---
phase: 16-queue-substrate-unblocked-webhook
plan: 04
subsystem: database
tags: [postgres, queue, concurrency, pytest, psycopg]

# Dependency graph
requires:
  - phase: 16-queue-substrate-unblocked-webhook (plan 02)
    provides: "queueproof pytest marker + narrow CI gate; worker_count/lease_seconds/max_attempts/queue_poll_seconds config knobs"
  - phase: 16-queue-substrate-unblocked-webhook (plan 03)
    provides: "JobKind/JobState/Job vocabulary; the jobs table + its constraints/index"
provides:
  - "app/db/repo/jobs.py — enqueue_job, claim_job, complete_job, fail_job, release_leases, get_job (the claim/lease/fencing protocol)"
  - "clear_reply_context now returns the incremented reply_epoch (was None)"
  - "rewind_for_reclaim — the automatic-reclaim rewind that never bumps reply_epoch"
  - "tests/conftest.py: hard-pinned WORKER_COUNT=0, InMemoryRepo mirrors of all seven new repo functions, the suite-wide queue-worker leak guard"
  - "tests/test_repo_jobs_sql.py — hermetic SQL-shape + bijection proofs"
  - "tests/test_fake_repo_pairing.py — the universal fake-repo pairing guard"
  - "tests/test_queue_durability.py — the isolation/live_worker fixtures + 8 live-DB proofs (Proof 3, the D-17 DB refusal, the epoch-stability assertion)"
affects: [16-05, 16-06, 16-07, 16-08, 16-09, 16-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Every app/db/repo/*.py function takes conn: psycopg.Connection | None = None and opens with _conn_ctx(conn)/_nulltx() — the caller-owns-transaction convention, now extended to the queue's six functions."
    - "A single-statement UPDATE with FOR UPDATE SKIP LOCKED in a subquery, re-targeted by id in the outer UPDATE, is the canonical safe claim idiom under Supavisor transaction-mode pooling — one implicit transaction, no session state."
    - "A shared SQL-fragment constant (_REPLY_CONTEXT_CLEAR_COLUMNS) is the DRY seam between two functions whose only real difference is a single side-effect (the epoch bump) — prevents the two from silently drifting apart."
    - "A universal fake-repo pairing guard (tests/test_fake_repo_pairing.py) closes the class of bug where a method defined on an in-memory test double is missing from its monkeypatch name tuple and silently falls through to the real DB-backed function."
    - "A suite-wide autouse leak guard (tests/conftest.py) plus a module-local autouse delete-gate (tests/test_queue_durability.py) are two NON-redundant mechanisms: one prevents a corrupt delete, the other reports (after the fact) a leak the first one didn't need to catch."

key-files:
  created:
    - app/db/repo/jobs.py
    - tests/test_repo_jobs_sql.py
    - tests/test_fake_repo_pairing.py
    - tests/test_queue_durability.py
  modified:
    - app/db/repo/pipeline_state.py
    - app/db/repo/__init__.py
    - tests/conftest.py
    - tests/test_queue_config.py

key-decisions:
  - "claim_job's RETURNING carries exactly the six columns Job's dataclass declares (id, kind, run_id, attempts, max_attempts, lease_token) — no email_id, no event_id — machine-checked as an ORDERED-LIST equality so the bijection cannot silently drift in either direction."
  - "fail_job scrubs last_error internally by importing the package-private _build_error_detail from app/db/repo/runs.py (the declared intra-app/db/repo BOUND-01 exemption) rather than requiring every caller to pre-scrub."
  - "rewind_for_reclaim is a NEW function, not a rewired clear_reply_context — the one difference (never bumping reply_epoch) is the load-bearing part of its contract, so it needed to be a distinct function with its own docstring rather than a flag on the existing one."
  - "tests/conftest.py's WORKER_COUNT=0 pin is a hard os.environ[...] = \"0\" assignment (not setdefault), placed at module top before any test can import app.main — a TestClient's lifespan runs for real once a later plan adds the queue worker's startup hook."
  - "The suite-wide daemon-worker leak guard and the module-local isolation fixture's own delete-gate are BOTH required and neither is redundant: pytest tears conftest-level (suite-wide) fixtures down AFTER module-local ones, so the leak guard only ever sees state the delete gate already acted on."

requirements-completed: [QUEUE-02, QUEUE-03]

coverage:
  - id: D1
    description: "app/db/repo/jobs.py exists with exactly six functions (enqueue_job, claim_job, complete_job, fail_job, release_leases, get_job), each taking conn= and using _conn_ctx/_nulltx; claim_job's RETURNING maps bijectively onto Job's six fields"
    requirement: "QUEUE-02"
    verification:
      - kind: unit
        ref: "tests/test_repo_jobs_sql.py::test_claim_returning_maps_bijectively_onto_the_job_dataclass"
        status: pass
      - kind: unit
        ref: "tests/test_repo_jobs_sql.py (11 tests total, hermetic FakeConnection-backed)"
        status: pass
    human_judgment: false
  - id: D2
    description: "enqueue_job rejects a run-less run_pipeline job with a ValueError before issuing any SQL, independent of the DB-level CHECK constraint"
    requirement: "QUEUE-02"
    verification:
      - kind: unit
        ref: "tests/test_repo_jobs_sql.py::test_enqueue_run_pipeline_without_a_run_id_raises_before_touching_the_db"
        status: pass
    human_judgment: false
  - id: D3
    description: "clear_reply_context returns the incremented reply_epoch; rewind_for_reclaim rewinds a stranded run to RECEIVED without ever bumping reply_epoch, scoped to exactly {extracting, computed, sent}"
    requirement: "QUEUE-02"
    verification:
      - kind: unit
        ref: "manual python -c signature/grep assertions (see Task 2 verify block) — the live-DB epoch-stability behavioral proof is tests/test_queue_durability.py::test_rewind_for_reclaim_leaves_reply_epoch_untouched"
        status: unknown
    human_judgment: true
    rationale: "No DATABASE_URL/.env in this worktree — the live-DB behavioral proof (a real run rewound, reply_epoch read back unchanged) could not be executed. All static/hermetic verification (return-type signature, SQL text shape, the shared-constant usage, no-caller-breakage across tests/test_retrigger_epoch.py etc.) passed. Needs a live-DB run (the queueproof CI gate) before this plan's guarantee is considered fully proven."
  - id: D4
    description: "A universal pairing guard makes it impossible for an InMemoryRepo/_MiniStore method to silently fall through to the real DB-backed repo function"
    requirement: "QUEUE-02"
    verification:
      - kind: unit
        ref: "tests/test_fake_repo_pairing.py (4 tests, all hermetic)"
        status: pass
    human_judgment: false
  - id: D5
    description: "A genuine N=5 claim race resolves to exactly one winner; an expired lease is reclaimed by a genuinely different claim; the zombie's stale token is fenced on BOTH complete_job and fail_job; release_leases returns a claimed row to pending immediately; the database itself refuses a null-run run_pipeline job — all driven at the sync repo seam, never through an HTTP route"
    requirement: "QUEUE-02, QUEUE-03"
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py (8 tests, @pytest.mark.integration + @pytest.mark.queueproof; collected cleanly via `pytest tests/ -m queueproof --collect-only` — 8/8)"
        status: unknown
    human_judgment: true
    rationale: "No DATABASE_URL/.env in this worktree — none of these live-DB proofs could execute. The file's correctness was verified as far as possible without a database: full mypy --strict + ruff clean, zero TestClient/time.sleep usage, threading.Barrier present, all 8 tests collected under both plain collection and the queueproof marker selector, and every fixture-wiring fact (autouse-ness, scope, the live_worker->_isolated_jobs dependency edge, the blocker-timeout-exceeds-quiesce-budget invariant, the delete gate's behavior and its both-sides-of-the-yield wiring) verified mechanically via direct Python calls outside pytest. The actual live-DB run — including all nine falsifying mutations — is deferred to the queueproof CI gate (16-02) against a real Postgres service container."
  - id: D6
    description: "The suite-wide daemon-worker leak guard (tests/conftest.py) exists, is autouse, and is wired into its fixture's teardown; both are proven independently and their falsifying mutations executed"
    requirement: "QUEUE-03"
    verification:
      - kind: unit
        ref: "tests/test_fake_repo_pairing.py::test_the_leak_guard_fails_on_a_surviving_worker_thread, ::test_the_leak_guard_is_wired_into_an_autouse_fixture"
        status: pass
    human_judgment: false

duration: 35min
completed: 2026-07-14
status: complete
---

# Phase 16 Plan 04: Queue Claim/Lease/Fencing Protocol Summary

**`app/db/repo/jobs.py`'s six-function claim/lease/fencing protocol (SKIP LOCKED claim, dual-fenced complete/fail), `rewind_for_reclaim`'s epoch-stable automatic reclaim, a universal fake-repo pairing guard, and an 8-test live-DB durability proof file — all hermetic verification green, live-DB execution deferred to the `queueproof` CI gate (no DATABASE_URL in this worktree).**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3 of 3 completed
- **Files modified:** 8 (4 created, 4 modified)

## Accomplishments

- `app/db/repo/jobs.py`: `enqueue_job` (idempotent on `dedup_key`, rejects a run-less `run_pipeline` job before any SQL), `claim_job` (the canonical `FOR UPDATE SKIP LOCKED` subquery claim with the expired-lease reclaim clause and attempt-at-claim increment), `complete_job`/`fail_job` (both fenced on `lease_token`), `release_leases`, `get_job`. All six re-exported through the `app/db/repo` facade.
- `tests/test_repo_jobs_sql.py`: 11 hermetic tests, including the machine-checked ORDERED-LIST bijection between `claim_job`'s `RETURNING` clause and `Job`'s six dataclass fields — proven to fail in BOTH directions (extra `Job` field; extra `RETURNING` column) and reverted.
- `app/db/repo/pipeline_state.py`: `clear_reply_context` now returns the incremented `reply_epoch` (was `None`); new `rewind_for_reclaim` rewinds a stranded run to `RECEIVED` and clears the same reply-round context WITHOUT ever bumping the epoch — the two functions share one `_REPLY_CONTEXT_CLEAR_COLUMNS` SQL fragment so they cannot silently drift apart.
- `tests/conftest.py`: hard-pinned `WORKER_COUNT=0` at module top; `InMemoryRepo` mirrors of all seven new repo functions; all seven registered in the `fake_repo` monkeypatch name tuple; the suite-wide daemon-worker leak guard (`QUEUE_WORKER_THREAD_PREFIX`, `live_queue_worker_threads()`, `fail_on_leaked_queue_workers()`, the autouse `_no_leaked_queue_workers` fixture).
- `tests/test_fake_repo_pairing.py`: the universal pairing guard — asserts, inside `fake_repo`'s active patch, that every `InMemoryRepo` method shadowing a real `app.db.repo` name is actually patched in; a static AST guard over `tests/test_threading.py`'s two other monkeypatch tuples; the leak guard's own two tests.
- `tests/test_queue_durability.py`: the `_isolated_jobs` autouse isolation fixture (empties `jobs` on both sides of every test, gated on process quiescence) and the `live_worker` fixture (the only sanctioned way to start a real worker in this file — its dependency on `_isolated_jobs` is what orders the quiesce before the delete), plus 8 tests: 2 gate-proving tests and 6 live-DB behavioral proofs (claim race, expired-lease reclaim, dual-fence, `release_leases`, the database's own CHECK-constraint refusal, and the `rewind_for_reclaim` epoch-stability assertion).
- Full hermetic suite green (667 passed, 61 skipped — the +8 skips are this plan's own live-DB tests), `mypy` (bare, 126 files) clean, `ruff check .` clean, `tests/test_bound01_private_imports.py` and `tests/test_comment_provenance_guard.py` both green.

## Task Commits

Each task was committed atomically:

1. **Task 1: `app/db/repo/jobs.py` — the claim/lease/fencing protocol** — `2f9ea6b` (feat)
2. **Task 2: `clear_reply_context` returns the epoch; `rewind_for_reclaim` rewinds without bumping it** — `f6e0386` (feat)
3. **Task 3: Proof 3 — a genuine claim race and the double-fence (live DB)** — `1c9c1c9` (test)

**Plan metadata:** committed by the orchestrator after wave merge (this executor runs in worktree mode and does not write STATE.md/ROADMAP.md).

## Files Created/Modified

- `app/db/repo/jobs.py` — `enqueue_job`, `claim_job`, `complete_job`, `fail_job`, `release_leases`, `get_job` (NEW)
- `app/db/repo/pipeline_state.py` — `clear_reply_context` return-type change, new `rewind_for_reclaim`, shared `_REPLY_CONTEXT_CLEAR_COLUMNS` constant
- `app/db/repo/__init__.py` — facade re-exports for all seven new names
- `tests/test_repo_jobs_sql.py` — hermetic SQL-shape + bijection tests (NEW)
- `tests/conftest.py` — `WORKER_COUNT=0` pin, `InMemoryRepo` job-queue mirrors + `rewind_for_reclaim`, `fake_repo` tuple additions, the suite-wide leak guard
- `tests/test_fake_repo_pairing.py` — the universal pairing guard (NEW)
- `tests/test_queue_durability.py` — the isolation/`live_worker` fixtures + 8 live-DB proofs (NEW)
- `tests/test_queue_config.py` — one test updated to unset `WORKER_COUNT` (see Deviations)

## Decisions Made

- `Job`'s `RETURNING` bijection is enforced as an ORDERED-LIST equality (not a subset/superset check), specifically because a prior cross-AI review round found a 7-fields-vs-6-columns defect that a one-directional check would have let through.
- `fail_job` reuses `runs.py`'s private `_build_error_detail`/`_scrub` via the package's own declared intra-module exemption, rather than duplicating scrub logic or requiring every caller to pre-scrub.
- `rewind_for_reclaim`'s status scope is exactly `{extracting, computed, sent}` — every other status is deliberately excluded, with the reasoning (legitimate pause vs. terminal vs. a genuine failure that must stay visible) written into the function's own docstring rather than left implicit.
- The suite-wide leak guard and the module-local delete gate are BOTH kept, deliberately non-redundant: fixture teardown ordering (conftest-level fixtures finalize after module-local ones) means the leak guard can only ever report a leak after the delete gate already acted — it cannot prevent the delete itself.
- `tests/test_queue_durability.py`'s two gate-proving tests are also gated behind the module's autouse `_isolated_jobs` fixture (which itself depends on `seeded_db`), even though they need no live worker module — pytest's autouse semantics apply per-module, not per-test, so there was no clean way to let them run DB-free while the rest of the module stays DB-gated. This is accepted as correct: in CI (with Postgres) all 8 tests run together; without a DB, all 8 skip together.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `tests/test_queue_config.py`'s default-values test broke under the new suite-wide `WORKER_COUNT=0` pin**
- **Found during:** Full-suite verification after Task 2
- **Issue:** `tests/test_queue_config.py::TestQueueKnobDefaults::test_four_defaults_exact` constructs `Settings()` directly and asserts `worker_count == 2` (the field's own default). `Settings` reads `os.environ` directly (not only `.env`), and this plan's own required change hard-sets `os.environ["WORKER_COUNT"] = "0"` at `tests/conftest.py`'s module top for the whole suite — so that test's `Settings()` call now always observed `0`, not the field default.
- **Fix:** Added `monkeypatch.delenv("WORKER_COUNT", raising=False)` to that one test, so it observes the field's real default rather than the suite-wide pin. No other test in the file needed this — `test_worker_count_zero_overrides_cleanly` already explicitly sets `WORKER_COUNT=0` itself and is unaffected.
- **Files modified:** `tests/test_queue_config.py`
- **Verification:** `uv run pytest tests/test_queue_config.py -q` → 7 passed; full suite re-run green (667 passed, 61 skipped).
- **Committed in:** `f6e0386` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — a pre-existing test's assumption broken by this plan's own mandated env pin)
**Impact on plan:** No scope creep; a direct, unavoidable consequence of hard-pinning `WORKER_COUNT=0` suite-wide, exactly as the plan instructed.

## Issues Encountered

- **No live database available in this worktree.** No `.env`/`DATABASE_URL` present (this worktree is gitignored and never checks one out). This blocks:
  - Executing any of the 8 tests in `tests/test_queue_durability.py` — every one carries the two-factor live-DB guard via the module's autouse `_isolated_jobs` fixture (which itself requires `seeded_db`), so all 8 skip cleanly rather than erroring. Collection was verified (`pytest tests/test_queue_durability.py --collect-only` → 8 tests; `pytest tests/ -m queueproof --collect-only` → the same 8/8, confirming the narrow CI gate from plan 16-02 actually picks them up).
  - Six of the nine falsifying mutations this plan's frontmatter demands (claim-SQL reclaim clause removed; `fail_job`'s fence removed; `SKIP LOCKED` subquery replaced; the epoch bump added to `rewind_for_reclaim`; both directions of the D-16 isolation probe; the `ck_jobs_run_pipeline_requires_run` constraint dropped) — all require a live Postgres and are **deferred to the `queueproof` CI gate**.

  **What WAS executed and verified in this worktree (hermetic, no DB):**

  1. **The `RETURNING`↔`Job` bijection, both directions** (`tests/test_repo_jobs_sql.py::test_claim_returning_maps_bijectively_onto_the_job_dataclass`):
     - Direction (i) — added a 7th field `email_id` to `Job`:
       ```
       E       AssertionError: claim_job's RETURNING clause must map bijectively, in order, onto Job's fields.
       E           RETURNING: ['id', 'kind', 'run_id', 'attempts', 'max_attempts', 'lease_token']
       E           Job fields: ['id', 'kind', 'run_id', 'attempts', 'max_attempts', 'lease_token', 'email_id']
       E           symmetric difference: {'email_id'}
       1 failed in 0.09s
       ```
     - Direction (ii) — added `j.email_id` to `claim_job`'s `RETURNING` (Job unmodified):
       ```
       E       AssertionError: claim_job's RETURNING clause must map bijectively, in order, onto Job's fields.
       E           RETURNING: ['id', 'kind', 'run_id', 'attempts', 'max_attempts', 'lease_token', 'email_id']
       E           Job fields: ['id', 'kind', 'run_id', 'attempts', 'max_attempts', 'lease_token']
       E           symmetric difference: {'email_id'}
       1 failed in 0.10s
       ```
     - Both reverted; `uv run pytest tests/test_repo_jobs_sql.py -q` → 11 passed after each revert.

  2. **The D-17-class Python guard** (`tests/test_repo_jobs_sql.py::test_enqueue_run_pipeline_without_a_run_id_raises_before_touching_the_db`) — deleted the `raise ValueError` from `enqueue_job`:
     ```
     E       Failed: DID NOT RAISE ValueError
     1 failed in 0.10s
     ```
     Reverted; 11 passed.

  3. **The fake-repo pairing guard** (`tests/test_fake_repo_pairing.py::test_every_inmemory_method_that_shadows_a_real_repo_name_is_actually_patched`) — removed `"claim_job"` from the `fake_repo` name tuple while leaving the `InMemoryRepo` method in place:
     ```
     E       AssertionError: these methods are defined on InMemoryRepo but missing from the fake_repo name tuple, so the REAL DB-backed function is running against a FakeCursor -- a silent-corruption bug, not a test failure: ['claim_job']
     1 failed in 0.09s
     ```
     Reverted; names the missing method exactly as required.

  4. **The leak guard's own behavioral test** (`tests/test_fake_repo_pairing.py::test_the_leak_guard_fails_on_a_surviving_worker_thread`) — emptied `fail_on_leaked_queue_workers()`'s body:
     ```
     E       Failed: DID NOT RAISE Failed
     1 failed in 0.04s
     ```
     Reverted; 4 passed.

  5. **The leak guard's wiring test** (`tests/test_fake_repo_pairing.py::test_the_leak_guard_is_wired_into_an_autouse_fixture`) — removed the `fail_on_leaked_queue_workers()` call from `_no_leaked_queue_workers`'s teardown:
     ```
     E       assert 'fail_on_leaked_queue_workers()' in '@pytest.fixture(autouse=True)\ndef _no_leaked_queue_workers():\n    """Suite-wide autouse fixture...its own delete statement, can prevent that\n    delete from landing beneath a still-live worker.\n    """\n    yield\n'
     1 failed in 0.04s
     ```
     Reverted; 4 passed.

  **Additional non-mutation verification performed on `tests/test_queue_durability.py` (no DB needed):**
  - `uv run mypy tests/test_queue_durability.py` → clean; `uv run ruff check tests/test_queue_durability.py` → clean.
  - `grep -cE '(TestClient\(|testclient)'` → 0; `grep -cE 'time\.sleep\('` → 0; `grep -c threading.Barrier` → 3 (present).
  - `pytest tests/test_queue_durability.py --collect-only` → 8 tests; `pytest tests/ -m queueproof --collect-only` → the same 8/8, confirming the narrow CI gate collects them.
  - Direct Python introspection (outside pytest) confirmed: `_isolated_jobs` is `autouse=True`, function-scoped, depends on `seeded_db`; `live_worker` depends on `_isolated_jobs`; `_BLOCKER_WAIT_SECONDS (30.0) > _QUIESCE_JOIN_BUDGET_SECONDS (5.0)`; `_require_quiesced_workers()` raises when a `queue-worker-*` thread is alive and returns cleanly once it's joined; the both-sides-of-the-yield wiring assertion passes against the real (unmutated) source.

## User Setup Required

None — no external service configuration required. A live Postgres connection (local or Supabase, with `ALLOW_DB_RESET=1`) is needed to execute `tests/test_queue_durability.py`'s 8 tests and the six live-DB-dependent falsifying mutations listed above — this is existing project infrastructure (the `queueproof` CI gate from plan 16-02), not new setup.

## Next Phase Readiness

- `app/db/repo/jobs.py` is ready for plan 16-06 (`app/queue/dispatch.py`, `handlers/pipeline.py`) and plan 16-07 (`app/queue/worker.py`), which will call `claim_job`/`complete_job`/`fail_job`/`release_leases` from real daemon worker threads.
- `rewind_for_reclaim` is ready for plan 16-07's automatic-reclaim handler and gives plan 16-10 (D-13's send guard) the epoch stability it needs to stay in scope on a machine-driven rerun.
- `tests/test_queue_durability.py`'s `_isolated_jobs`/`live_worker` fixtures are ready for plans 16-07 (Proof 4's `release_leases` worker-lifecycle half) and 16-09 (Proof 2) to APPEND tests to this same file and inherit isolation and teardown ordering for free — that dependency-edge design is the entire point of the fixture split.
- **Blocker for full closure:** live-DB verification of this plan's `tests/test_queue_durability.py` (all 8 tests) and the six live-DB-dependent falsifying mutations is outstanding — see Issues Encountered. Must run before this plan's durability guarantees, and ROADMAP criterion #3, are treated as fully proven. The `queueproof` CI gate (plan 16-02) is the sanctioned place this runs.

---
*Phase: 16-queue-substrate-unblocked-webhook*
*Completed: 2026-07-14*

## Self-Check: PASSED

All 9 claimed files found on disk (app/db/repo/jobs.py, app/db/repo/pipeline_state.py,
app/db/repo/__init__.py, tests/test_repo_jobs_sql.py, tests/conftest.py,
tests/test_fake_repo_pairing.py, tests/test_queue_durability.py,
tests/test_queue_config.py, this SUMMARY.md). All 3 claimed commit hashes (2f9ea6b,
f6e0386, 1c9c1c9) found in `git log --oneline --all`. No missing items.
