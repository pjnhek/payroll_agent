---
phase: 16-queue-substrate-unblocked-webhook
plan: 03
subsystem: database
tags: [postgres, ddl, queue, schema, mypy, pytest]

# Dependency graph
requires: []
provides:
  - "app/models/job.py — JobKind (1 member: run_pipeline), JobState (pending/leased/done/dead), Job (frozen dataclass, 6 fields mirroring the claim SQL's RETURNING clause)"
  - "jobs table in app/db/schema.sql — durable queue transport substrate, identifiers only (INVARIANT J-1 made structural)"
  - "uq_jobs_dedup_key, ck_jobs_lease_coherent, ck_jobs_run_pipeline_requires_run, idx_jobs_claimable"
  - "app/db/bootstrap.py _DROP_ORDER now drops jobs before all three of its FK targets"
  - "tests/test_status_drift.py schema guards rewritten to a named inventory (D-05)"
affects: [16-04, 16-05, 16-06, 16-07, 16-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "jobs.kind/jobs.state use an INLINE CHECK (no live rows to migrate on first deploy) — deliberately no third conkey-anchored DO-block, unlike payroll_runs.status/email_messages.purpose"
    - "kind-scoped CHECK constraint (ck_jobs_run_pipeline_requires_run) enforces a business rule at the DB level so it holds against every future caller, not just one Python function's signature"
    - "schema drift guards pinned to a harvested named set + symmetric-difference failure message, not a bare count"

key-files:
  created:
    - app/models/job.py
  modified:
    - app/db/schema.sql
    - app/db/bootstrap.py
    - tests/test_status_drift.py

key-decisions:
  - "Job dataclass has exactly 6 fields (no email_id) to match the claim SQL's RETURNING clause verbatim — the plan's resolved contradiction between an earlier 7-field draft and the 6-column canonical SQL."
  - "jobs.kind CHECK scoped to ('run_pipeline') only, not all 4 eventual kinds, so the CI dispatch-table guard (set equality) stays satisfiable this phase."
  - "jobs.event_id column omitted entirely (its FK target table does not exist yet) rather than declared without a REFERENCES clause — matches the plan's DEVIATION 2 instruction precisely."
  - "jobs.run_id has no cascading delete, matching the email_messages append-only-audit-log precedent, overriding the canonical design's CASCADE."
  - "ck_jobs_run_pipeline_requires_run added as a DB-level CHECK (not only a future Python ValueError) so a null-run run_pipeline job is unrepresentable regardless of caller."
  - "'jobs' inserted into bootstrap._DROP_ORDER immediately after 'eval_results' — before all three of its FK targets (payroll_runs, email_messages, businesses), not merely before payroll_runs."

patterns-established:
  - "Comment-provenance discipline: source comments must explain WHY directly, never cite a decision ID, pitfall number, phase number, or planning-doc filename — enforced project-wide by tests/test_comment_provenance_guard.py."

requirements-completed: [QUEUE-02, QUEUE-05]

coverage:
  - id: D1
    description: "JobKind has exactly 1 member (run_pipeline); JobState has exactly 4 (pending/leased/done/dead); neither collides with any RunStatus value"
    requirement: "QUEUE-05"
    verification:
      - kind: unit
        ref: "manual python -c assertion (see Task 1 verify block) — no dedicated pytest test yet; tests/test_job_kind_drift.py lands in plan 16-05"
        status: pass
    human_judgment: false
  - id: D2
    description: "Job is a frozen dataclass with exactly 6 fields (id, kind, run_id, attempts, max_attempts, lease_token) — no email_id, no payload"
    requirement: "QUEUE-05"
    verification:
      - kind: unit
        ref: "manual python -c assertion (see Task 1 verify block); bijection with claim_job's RETURNING clause machine-enforced in plan 16-04's tests/test_repo_jobs_sql.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "jobs table exists in schema.sql with uq_jobs_dedup_key, ck_jobs_lease_coherent, ck_jobs_run_pipeline_requires_run, idx_jobs_claimable; carries identifiers only"
    requirement: "QUEUE-02"
    verification:
      - kind: unit
        ref: "manual python -c static-parse assertion (see Task 2 verify block)"
        status: pass
      - kind: integration
        ref: "DATABASE_URL=... uv run python -m app.db.bootstrap / --reset (live-DB acceptance criteria)"
        status: unknown
    human_judgment: true
    rationale: "No DATABASE_URL/.env in this worktree — the live-DB bootstrap apply/reset acceptance criteria and the D-17 raw-INSERT rejection proof could not be executed in this environment. Needs a live-DB run before this plan's full verification is considered closed."
  - id: D4
    description: "'jobs' precedes all three of its FK targets (payroll_runs, email_messages, businesses) in bootstrap._DROP_ORDER"
    requirement: "QUEUE-02"
    verification:
      - kind: unit
        ref: "manual python -c assertion (see Task 2 verify block, index-order check)"
        status: pass
    human_judgment: false
  - id: D5
    description: "Schema guards in tests/test_status_drift.py pinned to a named index inventory and named DO-block set, not a magic number; falsifying mutation executed and reverted"
    verification:
      - kind: unit
        ref: "tests/test_status_drift.py::TestIndexStaticGuard::test_expected_indexes_present_and_no_others"
        status: pass
      - kind: unit
        ref: "tests/test_status_drift.py::TestEnumCheckDrift::test_do_block_constraint_drops_are_column_anchored"
        status: pass
    human_judgment: false

duration: 10min
completed: 2026-07-14
status: complete
---

# Phase 16 Plan 03: Queue Substrate DDL Summary

**Durable `jobs` table transport substrate transcribed into schema.sql with 4 documented deviations (including the D-17 kind-scoped run_id CHECK), the JobKind/JobState/Job Python vocabulary, and the D-05 schema-guard rewrite to a named index/DO-block inventory.**

## Performance

- **Duration:** ~10 min (commit-timestamp span)
- **Tasks:** 3 of 3 completed
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- `app/models/job.py`: `JobKind` (exactly `run_pipeline`), `JobState` (`pending`/`leased`/`done`/`dead`), and `Job` (frozen dataclass, 6 fields, no `email_id`) — collision-free against `RunStatus`, verified mechanically.
- `jobs` table landed in `app/db/schema.sql`: identifiers only (INVARIANT J-1 made structural), `uq_jobs_dedup_key`, `ck_jobs_lease_coherent`, `ck_jobs_run_pipeline_requires_run` (D-17), and the partial `idx_jobs_claimable` index matching the claim predicate exactly. Four documented deviations from the canonical DDL applied precisely as specified: scoped `kind` CHECK, omitted `event_id`, no cascading `run_id` FK, and the added kind-scoped CHECK.
- `app/db/bootstrap.py`'s `_DROP_ORDER` gained `"jobs"`, positioned immediately after `"eval_results"` — before all three of its FK targets (`payroll_runs`, `email_messages`, `businesses`), not merely before `payroll_runs`.
- `tests/test_status_drift.py`'s two magic-number schema guards rewritten per D-05: the index guard is now a set comparison against a named inventory (with `idx_jobs_claimable` added), and the DO-block guard's count of 2 is now derived from a named `EXPECTED_DO_BLOCKS` set with a comment explaining why `jobs`'s inline CHECKs don't add a third.
- Full test suite green (643 passed, 53 skipped), `mypy app` clean, `ruff check .` clean.

## Task Commits

Each task was committed atomically:

1. **Task 1: `app/models/job.py` — JobKind/JobState vocabulary** - `e17e632` (feat)
2. **Task 2: `jobs` table in schema.sql + bootstrap `_DROP_ORDER`** - `8391053` (feat)
3. **Fix: comment-provenance guard compliance** - `193da56` (fix — see Deviations)
4. **Task 3: D-05 schema-guard rewrite in `tests/test_status_drift.py`** - `080fcd0` (test)

**Plan metadata:** committed by the orchestrator after wave merge (this executor runs in worktree mode and does not write STATE.md/ROADMAP.md).

## Files Created/Modified

- `app/models/job.py` - `JobKind`, `JobState`, `Job` transport vocabulary (NEW)
- `app/db/schema.sql` - `jobs` table + `idx_jobs_claimable` index appended
- `app/db/bootstrap.py` - `"jobs"` added to `_DROP_ORDER`
- `tests/test_status_drift.py` - `test_expected_indexes_present_and_no_others` replaces `test_exactly_three_new_indexes`; `test_do_block_constraint_drops_are_column_anchored` rewritten to a named-set derivation

## Decisions Made

- `Job` dataclass ships with exactly 6 fields (no `email_id`), resolving the plan's flagged contradiction between an earlier 7-field draft and the 6-column canonical `RETURNING` clause — the SQL wins, per the plan's explicit instruction.
- `jobs.kind` CHECK scoped to `('run_pipeline')` only (not the 4 eventual kinds), keeping the future `set(JobKind) == set(dispatch.HANDLERS)` CI guard satisfiable.
- `jobs.event_id` omitted entirely rather than declared with a dangling/absent `REFERENCES` — its FK target table does not exist in this schema yet.
- `jobs.run_id` has no cascading delete, matching the `email_messages` append-only-audit-log precedent (CONTEXT.md's discretion override of the canonical design's `CASCADE`).
- `ck_jobs_run_pipeline_requires_run` added as a DB-level CHECK constraint (D-17) so a null-run `run_pipeline` job is unrepresentable regardless of which future caller inserts it — not solely a Python-side `ValueError` guard (that lands separately in plan 16-04).
- `"jobs"` positioned in `_DROP_ORDER` immediately after `"eval_results"`, before ALL THREE FK targets — the plan explicitly flagged an earlier draft's "before payroll_runs" framing as insufficient (it would still land after `email_messages`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Comment text violated the project's comment-provenance guard**
- **Found during:** Task 3 (running the full test suite before committing, per plan verification: "uv run pytest -q fully green")
- **Issue:** `tests/test_comment_provenance_guard.py` (a pre-existing, project-wide CI gate) failed with 20 violations. My Task 1 and Task 2 comments — following the plan's own instructions to cite `16-RESEARCH.md`, `Pitfall 7`, `D-17`, `CONTEXT.md`, `Phase 16/17/19/21`, and `OPS2-01` — tripped the guard's `decision-id`, `pitfall-ref`, `phase-ref`, `planning-doc-ref`, and `review-ticket` patterns. The plan's own prose (correctly, for planning purposes) cites these tickets; the guard requires shipped source comments to explain the code directly instead.
- **Fix:** Reworded every flagged comment in `app/models/job.py`, `app/db/schema.sql`, and `app/db/bootstrap.py` to state the underlying reasoning without citing a ticket ID, phase number, pitfall number, or planning-doc filename. No behavioral change — comment text only. The substantive reasoning (why each deviation exists, why the constraint is load-bearing) is fully preserved, just de-cited.
- **Files modified:** `app/models/job.py`, `app/db/schema.sql`, `app/db/bootstrap.py`
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py -q` → 5 passed. Full suite re-run green (643 passed).
- **Committed in:** `193da56`

---

**Total deviations:** 1 auto-fixed (1 bug — comment-hygiene compliance)
**Impact on plan:** No scope creep; purely a comment-wording fix required by a pre-existing project-wide test gate that the plan's own citation-heavy prose (reasonably, for a planning document) would have violated if transcribed verbatim into source comments.

## Issues Encountered

- **No live database available in this worktree.** No `.env`/`DATABASE_URL` present, so the plan's live-DB acceptance criteria for Task 2 — `DATABASE_URL=... uv run python -m app.db.bootstrap` (twice, idempotent), `--reset` (twice, `jobs` empty after), and hand-verifying `ck_jobs_run_pipeline_requires_run` rejects a raw null-run INSERT — could not be executed. All static verification (schema-text parsing, drop-order assertions, `mypy`/`ruff`/`pytest`) passed. This gap is flagged as `human_judgment: true` in the `coverage` block (D3) and should be closed by running the live-DB bootstrap before this plan's durability guarantees are treated as fully proven. The permanent regression test for the D-17 constraint (`test_the_database_refuses_a_run_pipeline_job_with_a_null_run_id`) is plan 16-04's responsibility per the original plan text.

## User Setup Required

None — no external service configuration required. A live Postgres connection (local or Supabase) is needed to run the deferred bootstrap verification above, but that is existing project infrastructure, not new setup.

## Next Phase Readiness

- `app/models/job.py` and the `jobs` table are ready for plan 16-04 (`app/db/repo/jobs.py` — `enqueue_job`, `claim_job`, `complete_job`, `fail_job`, `release_leases`, `get_job`), which will exercise the `Job`↔`RETURNING` bijection and the D-17 constraint against a live DB.
- `tests/test_job_kind_drift.py` (plan 16-05) still needs to be written — this plan only pinned the schema-side guards, not a dedicated `JobKind`↔SQL drift test.
- **Blocker for full closure:** live-DB verification of Task 2's bootstrap apply/reset and the D-17 raw-INSERT rejection is outstanding (see Issues Encountered). Recommend running this before the phase is marked fully verified.

---
*Phase: 16-queue-substrate-unblocked-webhook*
*Completed: 2026-07-14*
