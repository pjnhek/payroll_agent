---
status: awaiting_human_verify
trigger: "ci run failed"
created: 2026-07-16T17:52:59Z
updated: 2026-07-16T18:12:00Z
---

# Debug Session: Jobs Kind Array Mismatch

## Symptoms

- expected: `uv run python -m app.db.bootstrap` applies `app/db/schema.sql` successfully to both PostgreSQL 16 and live Supabase, after which concurrency proofs and live schema checks run.
- actual: both `concurrency-proof` run 29521110897 and `deploy-migrate` run 29521109427 fail while applying the schema; the core hermetic `ci` workflow passes.
- error: `psycopg.errors.UndefinedFunction: operator does not exist: name[] = text[]` at the jobs constraint lookup expression ending `= ARRAY['kind']`.
- timeline: first exposed after pushing master through `ad60c9c` on 2026-07-16; blame attributes the faulty query shape to Phase 18 commit `c66d5227`.
- reproduction: run `uv run python -m app.db.bootstrap` against PostgreSQL 16 with `DATABASE_URL` configured; failure occurs in the jobs-kind live-migration DO block before Phase 18 DDL commits.

## Current Focus

- hypothesis: five real-Postgres queueproofs still use Phase 17 test doubles that implicitly return `None`; Phase 18 intentionally rejects `None` at `normalize_pipeline_result`, so the drain enters infrastructure-failure settlement instead of the proofs' intended OK path. The graceful-shutdown proof additionally spies `complete_job`, a seam no longer called by `drain_once` after atomic `settle_pipeline_job` landed.
- hypothesis: confirmed; the remaining failures were stale queueproof doubles and an obsolete observation seam, not runtime defects.
- test: after commit and push, rerun `concurrency-proof` against PostgreSQL 16 and require all 38 selected queueproofs to pass with zero skips.
- expecting: the five repaired proofs join the existing 33 green proofs, while `deploy-migrate` remains green and strict `None` rejection stays covered.
- next_action: parent agent should review and commit `tests/test_queue_durability.py` plus the debug artifact, push, and use the next `concurrency-proof` result as final human/environment verification.
- reasoning_checkpoint:
    hypothesis: the remaining five failures are test-contract drift: their monkeypatched handlers/orchestrators return `None`, which Phase 18's strict dynamic boundary converts into `TypeError`, and one proof observes a repository seam retired from the drain path.
    confirming_evidence:
      - workflow 29522253906 names exactly the graceful shutdown, quiesce, restart, retrigger, and pump proofs; the first three monkeypatch handlers with no return and the latter two monkeypatch `run_pipeline_now` with no return.
      - `normalize_pipeline_result` now raises `TypeError` for every non-`PipelineResult`, explicitly including `None`, and commit `c1ea21c` documents removal of legacy `None` normalization.
      - `drain_once` now settles successful dispatch through `repo.settle_pipeline_job`; it never calls `repo.complete_job`, so the graceful proof's old spy cannot observe the zombie fence.
    falsification_test: if any named proof still reaches retry/fenced behavior from its double after returning explicit OK, or if a spy on `settle_pipeline_job` does not observe `SettlementOutcome.FENCED` after shutdown releases the lease, this diagnosis is wrong.
    fix_rationale: making the tests implement the production result protocol restores their intended success path without weakening the runtime contract; observing the active atomic settlement seam restores the same zombie-fence assertion at the current boundary.
    blind_spots: the five proofs require reset-enabled PostgreSQL and will skip locally if that environment is absent; authoritative behavioral proof remains the rerun of `concurrency-proof` after commit and push.
- tdd_checkpoint: workflow.tdd_mode is false; the current CI failure is the pre-fix red evidence.

## Evidence

- timestamp: 2026-07-16T17:46:21Z
  source: GitHub Actions concurrency-proof 29521110897
  observation: PostgreSQL 16 rejects `name[] = text[]` at `ARRAY['kind']` during bootstrap.
- timestamp: 2026-07-16T17:46:01Z
  source: GitHub Actions deploy-migrate 29521109427
  observation: live Supabase rejects the identical query with the identical type error.
- timestamp: 2026-07-16T17:52:59Z
  source: source inspection
  observation: the payroll-runs and email-purpose constraint migrations already cast `a.attname::text`; only the jobs-kind migration omits the cast.
- timestamp: 2026-07-16T17:54:56Z
  source: debug knowledge base check
  observation: `.planning/debug/knowledge-base.md` does not exist, so there is no prior resolved pattern to test first.
- timestamp: 2026-07-16T17:55:39Z
  source: complete source and test inspection
  observation: `app/db/schema.sql` has exactly three `pg_attribute.attname` aggregate constraint matchers; the payroll-runs and email-purpose matchers cast to text, while the jobs-kind matcher does not. `tests/test_repo_jobs_sql.py` reads schema source but has no test pinning the jobs matcher operand type.
- timestamp: 2026-07-16T17:55:39Z
  source: git history
  observation: `git blame` attributes lines 610-626, including the uncast jobs aggregate and comparison, to Phase 18 commit `c66d5227`.
- timestamp: 2026-07-16T17:56:28Z
  source: focused regression before schema fix
  observation: `uv run pytest -q tests/test_repo_jobs_sql.py::test_jobs_kind_live_migration_casts_catalog_names_to_text` fails exactly because the jobs migration does not contain `array_agg(a.attname::text ORDER BY u.ord)`.
- timestamp: 2026-07-16T17:57:12Z
  source: focused regression after schema fix
  observation: the same focused command passes (`1 passed`), demonstrating the targeted cast satisfies the regression that was red before the fix.
- timestamp: 2026-07-16T17:57:42Z
  source: schema-adjacent regression suite
  observation: `uv run pytest -q tests/test_repo_jobs_sql.py tests/test_check_schema_cli.py tests/test_health_schema.py tests/test_schema_introspect.py` passes with `77 passed` and one unrelated Starlette deprecation warning.
- timestamp: 2026-07-16T17:58:15Z
  source: static and diff verification
  observation: Ruff passes the changed test, mypy reports no issues in it, and `git diff --check` passes. The implementation diff is limited to the element-level SQL cast and the targeted regression.
- timestamp: 2026-07-16T18:00:02Z
  source: full hermetic and repository-wide verification
  observation: `uv run pytest -q` passes with `901 passed, 68 skipped`; `uv run ruff check .` passes; and `uv run mypy .` reports no issues in 146 source files.
- timestamp: 2026-07-16T18:07:00Z
  source: GitHub Actions deploy-migrate 29522253630
  observation: live Supabase migration passes after commit `8c78123`, confirming the `name[] = text[]` schema defect is fixed in the production-like database.
- timestamp: 2026-07-16T18:08:00Z
  source: GitHub Actions concurrency-proof 29522253906
  observation: PostgreSQL 16 applies the schema and all original concurrency invariants plus 33 queue durability proofs pass; five legacy queueproofs fail because their monkeypatched handlers/orchestrators return `None` under Phase 18's explicit `PipelineResult` boundary. Four rows remain leased or settle FENCED, and the graceful-shutdown proof still spies the retired `complete_job` seam instead of `settle_pipeline_job`.
- timestamp: 2026-07-16T18:09:00Z
  source: failed workflow and current runtime/test inspection
  observation: the five failures are `test_graceful_shutdown_releases_held_leases_immediately`, `test_quiesce_releases_a_blocked_handler_and_joins_to_zero`, `test_a_restarted_worker_claims_and_completes_a_real_job`, `test_retrigger_survives_worker_crash_mid_lease`, and `test_pump_drains_future_due_job_with_zero_workers`. Six test doubles across them have implicit `None` returns; `drain_once` validates through `normalize_pipeline_result` and settles through `repo.settle_pipeline_job`.
- timestamp: 2026-07-16T18:10:00Z
  source: test-only compatibility patch
  observation: all four handler doubles and both `run_pipeline_now` doubles now return explicit OK `PipelineResult` values. The graceful-shutdown proof now spies `repo.settle_pipeline_job` and requires `SettlementOutcome.FENCED`; no runtime file was changed.
- timestamp: 2026-07-16T18:11:00Z
  source: focused local queueproof command
  observation: all five exact pytest node IDs collect successfully and skip only because the local environment lacks the required `DATABASE_URL` plus `ALLOW_DB_RESET=1`; no test import or collection failure occurs.
- timestamp: 2026-07-16T18:12:00Z
  source: full hermetic and static verification after test repair
  observation: `uv run pytest -q` passes with `901 passed, 68 skipped`; `uv run ruff check .` passes; `uv run mypy .` reports no issues in 146 source files; and `git diff --check` passes.
- timestamp: 2026-07-16T18:12:00Z
  source: strict dynamic-result boundary regression check
  observation: the three focused tests that inject `None` into operator-resume, generic pipeline normalization, and resume-reply dispatch all pass (`3 passed`), proving runtime rejection of `None` remains intact.

## Eliminated

- hypothesis: dependency or Python-version drift
  reason: both workflows install successfully and fail inside PostgreSQL query type resolution; core CI is green.
- hypothesis: missing GitHub secret or unavailable PostgreSQL service
  reason: both databases accept connections and execute bootstrap until the same SQL expression.

## Specialist Review

Not dispatched: the mapped `engineering:debug` specialist skill was not available in this session. The generic-agent debugger independently verified the SQL type diagnosis against both failing workflow logs and the two neighboring working constraint-discovery blocks before applying the minimal fix.

## Resolution

- root_cause: the original jobs migration omitted an `attname::text` cast, aborting schema bootstrap. Once fixed, PostgreSQL exposed five stale queueproofs whose Phase 17 doubles returned `None` despite Phase 18's explicit `PipelineResult` contract; the graceful proof also spied retired `complete_job` instead of active atomic settlement.
- fix: cast the jobs catalog aggregate to text with a regression guard; update only the six stale queueproof doubles to return explicit OK results and move the zombie-fence spy to `settle_pipeline_job`.
- verification: the schema fix is proven in live Supabase and PostgreSQL 16. The test-only repair collects locally, the full hermetic suite passes (`901 passed, 68 skipped`), repository-wide Ruff/mypy and diff integrity pass, and three explicit `None`-rejection regressions pass. Final verification is the reset-enabled PostgreSQL `concurrency-proof` rerun, which must execute all 38 queueproofs with zero skips.
- files_changed: `app/db/schema.sql`, `tests/test_repo_jobs_sql.py`, `tests/test_queue_durability.py`, `.planning/debug/jobs-kind-array-mismatch.md`
- cycles: 2 investigation, 2 fix
