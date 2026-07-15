---
phase: 17
reviewers: [codex]
reviewed_at: 2026-07-15T02:50:00Z
plans_reviewed: [17-01-PLAN.md,17-02-PLAN.md,17-03-PLAN.md,17-04-PLAN.md,17-05-PLAN.md]
---

# Cross-AI Plan Review — Phase 17

## Codex Review

# Cross-AI Plan Review — Phase 17: The Pump

## Overall assessment

The phase is well decomposed and mostly grounded in the actual repository. Dependency ordering is coherent, the shared `drain_once()` seam is real, and Plan 17-05 has the right anti-vacuity structure. However, three issues should be resolved before execution:

1. The plans incorrectly treat 210 seconds as a maximum whole-job runtime; the source defines it only as the maximum gap between consecutive database writes.
2. Plan 17-05 does not stub the real pipeline, so its live-Postgres proof may call paid LLM providers.
3. A failure of `fail_job()` is classified as `FENCED` and swallowed, so the pump can return 200 for a genuine infrastructure failure, conflicting with D-10.

Overall risk: **HIGH until these are corrected**, then likely LOW–MEDIUM.

---

## Plan 17-01 — `DrainOutcome`

### Summary

This is a focused, source-grounded refactor. The capture-don’t-thread approach is correct because the repository already exposes the information needed to distinguish done, retried, dead, and fenced outcomes. The main unresolved problem is the proposed treatment of a failed failure-write as `FENCED`.

### Strengths

- The plan correctly identifies the existing return contracts:

  - `complete_job()` returns `bool` at [app/db/repo/jobs.py:182](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo/jobs.py:182).
  - `fail_job()` already returns `JobState | None` at [app/db/repo/jobs.py:204](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo/jobs.py:204), with the SQL returning the resulting state at [app/db/repo/jobs.py:232](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo/jobs.py:232).

  No repository signature changes are needed.

- Preserving truthiness is necessary and correctly planned. The worker uses only `if drain.drain_once()` at [app/queue/worker.py:198](/Users/pnhek/usf%20msds/github/payroll_agent/app/queue/worker.py:198).

- The assertion inventory is accurate. The repository has 15 boolean-identity assertions, including the five core behaviors at [tests/test_queue_drain.py:304](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_queue_drain.py:304) through [tests/test_queue_drain.py:404](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_queue_drain.py:404).

- Replacing `is True/False` with exact outcome assertions genuinely strengthens the tests.

### Concerns

- **HIGH — A failed `fail_job()` write is not a fenced lease.**

  The existing inner exception means the database failure-write itself failed and the process intentionally retains the lease token at [app/queue/drain.py:180](/Users/pnhek/usf%20msds/github/payroll_agent/app/queue/drain.py:180). A real fence instead means the database write completed but affected no row because the lease was reclaimed, as documented at [app/queue/drain.py:7](/Users/pnhek/usf%20msds/github/payroll_agent/app/queue/drain.py:7).

  Mapping both to `FENCED` makes the count semantically false. More importantly, the pump can return 200 even though a database write failed, contradicting D-10.

- **MEDIUM — The proposed behavior conflicts with an existing regression test.**

  [tests/test_queue_drain.py:798](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_queue_drain.py:798) explicitly requires a failed `fail_job()` not to escape. If the better resolution is to re-raise so the HTTP pump returns 503, this test must be revised to prove that the worker loop still catches the exception at [app/queue/worker.py:203](/Users/pnhek/usf%20msds/github/payroll_agent/app/queue/worker.py:203).

- **LOW — Task 1 is labeled TDD but does not first add or run outcome-specific behavioral tests.**

  Its verification checks enum shape and typing, while the behavioral assertions are rewritten only in Task 2.

### Suggestions

- Do not classify a failed failure-write as `FENCED`. Prefer:

  - log and re-raise while retaining `_held_tokens`; the worker loop already catches iteration exceptions, while the pump route can return 503; or
  - introduce an explicit infrastructure-error result if the locked vocabulary can be amended.

- Add a test distinguishing:

  - `fail_job() -> None` → `FENCED`;
  - `fail_job()` raises → infrastructure failure, not `FENCED`.

- If re-raising, replace the existing “must not escape” unit assertion with a worker-loop test proving the worker logs, survives, and retries polling.

### Risk assessment

**HIGH.** The normal outcome mappings are sound, but the double-failure mapping can turn a genuine database outage into a successful HTTP response and an inaccurate count.

---

## Plan 17-02 — `count_open_jobs()`

### Summary

The function and facade placement are correct, and the proposed SQL definition of backlog is reasonable. The test plan overstates what a `FakeConnection` can prove and misses three existing “six-function public surface” tests that will become stale.

### Strengths

- `jobs.py` is the correct location. It already owns the complete queue transport surface and documents that surface at [app/db/repo/jobs.py:1](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo/jobs.py:1).

- The facade re-export is necessary and correctly identified at [app/db/repo/__init__.py:46](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo/__init__.py:46) and [app/db/repo/__init__.py:136](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo/__init__.py:136).

- Counting both pending and leased jobs is a defensible definition of outstanding backlog. It also correctly includes future-dated pending jobs.

- No migration is needed; `jobs.state` and the relevant states already exist.

### Concerns

- **MEDIUM — The hermetic test cannot behaviorally prove a mixed state population.**

  `tests/test_repo_jobs_sql.py` is explicitly an SQL-recording suite, not an in-memory SQL engine, at [tests/test_repo_jobs_sql.py:1](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_repo_jobs_sql.py:1). A scripted `fetchone((3,))` can prove return-value mapping and inspect the WHERE clause, but it cannot prove that PostgreSQL actually counts pending/leased while excluding done/dead.

- **MEDIUM — Three existing public-surface tests remain stale.**

  The plan updates the production module docstring but not:

  - “all six functions” at [tests/test_repo_jobs_sql.py:228](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_repo_jobs_sql.py:228);
  - the six-function `conn`/`_conn_ctx` inventory at [tests/test_repo_jobs_sql.py:242](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_repo_jobs_sql.py:242);
  - the “all six functions” SQL parameterization exercise at [tests/test_repo_jobs_sql.py:193](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_repo_jobs_sql.py:193).

  These tests would remain green while falsely claiming to cover the whole public surface.

- **MEDIUM — The promised live behavioral half is not actually specified.**

  Plan 17-02 says live coverage rides with 17-05, but Plan 17-05 does not construct a pending/leased/done/dead mix or assert a mixed-state count.

### Suggestions

- Make the hermetic test honest:

  - script a count result;
  - assert the return converts it to `int`;
  - assert the SQL contains precisely `state IN ('pending', 'leased')`.

- Add a live `queueproof` test or extend 17-05 to construct mixed states and assert the real count.

- Update all three six-function inventory tests to seven and include `count_open_jobs`.

- If `fake_repo` will be used in pump-route tests, consider adding `count_open_jobs()` to `InMemoryRepo` and its patch tuple at [tests/conftest.py:1297](/Users/pnhek/usf%20msds/github/payroll_agent/tests/conftest.py:1297). Direct route-level monkeypatching is also acceptable, but it should be explicit.

### Risk assessment

**MEDIUM.** Production code is straightforward, but the current validation can claim stronger behavior than it proves and leaves authoritative tests stale.

---

## Plan 17-03 — Workflow, Render configuration, README

### Summary

The keepalive absorption is correctly scoped and preserves the important schema-drift monitor. The primary defect is the timeout derivation: 210 seconds is not the whole-job ceiling the plan claims. The YAML verification command also has a likely parser bug.

### Strengths

- The current workflow really has the two behaviors that must survive:

  - readiness/Supabase touch at [.github/workflows/keepalive.yml:39](/Users/pnhek/usf%20msds/github/payroll_agent/.github/workflows/keepalive.yml:39);
  - schema drift detection at [.github/workflows/keepalive.yml:50](/Users/pnhek/usf%20msds/github/payroll_agent/.github/workflows/keepalive.yml:50).

- The current tree has only one scheduled workflow, at [.github/workflows/keepalive.yml:17](/Users/pnhek/usf%20msds/github/payroll_agent/.github/workflows/keepalive.yml:17). Replacing it with `pump.yml` can therefore satisfy “only cron” cleanly.

- `PUMP_TOKEN` belongs in the existing `sync:false` block at [render.yaml:19](/Users/pnhek/usf%20msds/github/payroll_agent/render.yaml:19).

- The README locations identified by the plan are genuinely stale:

  - keepalive wording at [README.md:139](/Users/pnhek/usf%20msds/github/payroll_agent/README.md:139);
  - pre-queue BackgroundTasks limitation at [README.md:157](/Users/pnhek/usf%20msds/github/payroll_agent/README.md:157).

- Keeping `workflow_dispatch` preserves the existing operational recovery path documented at [.github/workflows/keepalive.yml:7](/Users/pnhek/usf%20msds/github/payroll_agent/.github/workflows/keepalive.yml:7).

### Concerns

- **HIGH — The `--max-time 360` derivation uses the wrong quantity.**

  The cited 210 seconds is explicitly the maximum gap between two consecutive database writes, not a whole pipeline-job runtime. That distinction is stated at [app/routes/runs.py:43](/Users/pnhek/usf%20msds/github/payroll_agent/app/routes/runs.py:43) and repeated in configuration at [app/config.py:84](/Users/pnhek/usf%20msds/github/payroll_agent/app/config.py:84).

  A single `drain_once()` executes the entire handler before checking the wall-clock cap again. Therefore:

  ```text
  request ceiling ≠ 120s + 210s
  request ceiling = time before starting final job + total runtime of that entire job
  ```

  The plan has not measured or bounded the latter.

- **MEDIUM — The duty-cycle arithmetic omits non-trivial request duration.**

  `awake ≈ 15 ÷ cadence` is a baseline for near-instant requests. A long pump request extends the awake period because the 15-minute idle window begins after the last activity. It likely remains below 750 hours at this scale, but the README should label the arithmetic as a baseline, not an exact upper bound.

- **MEDIUM — “≤30-minute worst-case recovery” is too absolute.**

  GitHub cron delay and Render cold-start time make 30 minutes a nominal scheduling bound, not a strict end-to-end recovery bound. The proposed caveat helps, but the headline should say “nominally within one 30-minute cadence.”

- **MEDIUM — The proposed PyYAML trigger assertion is unreliable.**

  The workflow uses an unquoted `on:` key, as the current file does at [.github/workflows/keepalive.yml:16](/Users/pnhek/usf%20msds/github/payroll_agent/.github/workflows/keepalive.yml:16). PyYAML’s default YAML 1.1 resolver commonly parses `on` as boolean `True`, making `d["on"]` fail even for valid GitHub workflow YAML.

- **LOW — There is no durable static test for criterion #4.**

  Grep checks help, but they are execution-script checks rather than a committed regression guard. A later edit could drop `/health/schema` after this phase.

### Suggestions

- Measure or conservatively derive the total worst-case `drain_once()` job duration before choosing the pump curl timeout. Document each sequential external-call ceiling and database stage.

- Add workflow-level `concurrency` to prevent overlapping scheduled/manual pump runs if a request can approach or exceed one cadence. SKIP LOCKED protects correctness, but serialization protects capacity.

- Phrase README timing as:

  > Jobs are normally picked up within the next 30-minute cadence, plus cold-start and execution time; GitHub scheduling delays can exceed that best-effort target.

- Describe `15 ÷ cadence` as idle-duty-cycle baseline arithmetic and mention job traffic adds awake time.

- Replace the `yaml.safe_load(...)[“on”]` verification with a loader that disables YAML 1.1 boolean coercion, or use a textual/static GitHub-workflow check.

- Add a committed static test that asserts:

  - `pump.yml` exists;
  - `keepalive.yml` does not;
  - one schedule exists across workflows;
  - all three endpoints remain present;
  - `workflow_dispatch` remains present.

### Risk assessment

**HIGH.** The workflow composition is good, but the request-timeout and recovery-bound claims are based on a source quantity that does not mean what the plan says it means.

---

## Plan 17-04 — Pump route

### Summary

The route design is compact, uses the correct shared seam, and has appropriate authentication and disclosure controls. Its infrastructure-failure contract is not fully achievable with Plan 17-01’s swallowed failure-write, and its bounding math inherits the invalid whole-job runtime assumption.

### Strengths

- A sync FastAPI route is appropriate. Existing DB-backed health routes use sync functions at [app/routes/health.py:29](/Users/pnhek/usf%20msds/github/payroll_agent/app/routes/health.py:29) and [app/routes/health.py:50](/Users/pnhek/usf%20msds/github/payroll_agent/app/routes/health.py:50).

- Fixed-body, exception-type-only disclosure follows the established health pattern at [app/routes/health.py:45](/Users/pnhek/usf%20msds/github/payroll_agent/app/routes/health.py:45).

- `pump_token: str = ""` follows existing secret defaults at [app/config.py:53](/Users/pnhek/usf%20msds/github/payroll_agent/app/config.py:53), while explicit route-level fail-closed behavior avoids an unauthenticated development mode.

- The route calls the exact same `drain_once()` used by workers, satisfying the central DRY requirement.

- Separate max-jobs and wall-clock tests are well specified. Requiring the wall-clock test to stop before the job cap avoids a vacuous test.

- Registering a new router in the thin assembly at [app/main.py:8](/Users/pnhek/usf%20msds/github/payroll_agent/app/main.py:8) is consistent with the refactored structure.

### Concerns

- **HIGH — D-10 cannot be guaranteed with the proposed `drain_once()` behavior.**

  A claim failure will propagate, and a queue-depth failure will propagate. But a failure of `repo.fail_job()` is caught and suppressed at [app/queue/drain.py:180](/Users/pnhek/usf%20msds/github/payroll_agent/app/queue/drain.py:180). Plan 17-01 maps it to `FENCED`, so the route can return 200 for a genuine write outage.

  A test that only makes `count_open_jobs()` raise does not cover this path.

- **HIGH — The route’s boundedness derivation is invalid.**

  `_MAX_WALL_CLOCK_SECONDS` is checked only between calls. Since 210 seconds is a maximum write gap rather than total job runtime, the asserted ~330-second maximum request duration is unsupported.

- **MEDIUM — The catch-all labels every route-loop error as infrastructure.**

  A programming error such as an unexpected outcome or aggregation `KeyError` would also become 503. That may be operationally acceptable, but the plan’s statement that only genuine infrastructure failures reach it is too strong.

- **MEDIUM — Settings-cache isolation needs an explicit teardown.**

  `get_settings()` is cached at [app/config.py:145](/Users/pnhek/usf%20msds/github/payroll_agent/app/config.py:145). Existing tests clear the cache before and after environment changes at [tests/test_repo_jobs_sql.py:20](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_repo_jobs_sql.py:20). The new route tests should do the same; otherwise a cached test token can survive after `monkeypatch` restores the environment.

- **LOW — GET is operationally simple but state-changing.**

  This is within the user’s discretion, but POST would communicate intent more accurately and avoid accidental invocation by link scanners or diagnostics.

### Suggestions

- Resolve the `fail_job()`-raises path before implementing D-10 tests. Add a route test that specifically simulates:

  1. handler raises;
  2. `fail_job()` also raises;
  3. endpoint returns 503 and retains the held lease token.

- Recalculate caps from total handler runtime, not the stale-run write-gap figure.

- Use a fixture that always clears `get_settings.cache_clear()` after each pump test.

- Consider testing the exact JSON values for sequences such as:

  ```text
  DONE, RETRIED, DEAD, FENCED, EMPTY
  ```

  This proves all buckets and `claimed == sum(outcome buckets)`.

- Add an invariant assertion in the route or tests:

  ```python
  claimed == done + retried + dead + fenced
  ```

### Risk assessment

**HIGH.** Authentication and aggregation are solid, but the promised 503 behavior and request-duration bound do not follow from the planned implementation.

---

## Plan 17-05 — Anti-vacuous durability proof

### Summary

The proof structure is the strongest part of the phase: it explicitly constructs a future-dated job, verifies it is not claimable, proves no worker thread exists, invokes the HTTP endpoint, and checks the exact job row. However, it omits the essential pipeline stub, which means the CI proof can execute the real payroll pipeline and external LLM calls.

### Strengths

- The zero-worker condition is real. The suite hard-pins `WORKER_COUNT=0` before importing the app at [tests/conftest.py:37](/Users/pnhek/usf%20msds/github/payroll_agent/tests/conftest.py:37).

- The worker-thread detector scans actual thread names rather than trusting worker-module state at [tests/conftest.py:67](/Users/pnhek/usf%20msds/github/payroll_agent/tests/conftest.py:67).

- The module already applies both `integration` and `queueproof` to every test at [tests/test_queue_durability.py:112](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_queue_durability.py:112).

- CI already collects the marker rather than filenames at [.github/workflows/concurrency-proof.yml:105](/Users/pnhek/usf%20msds/github/payroll_agent/.github/workflows/concurrency-proof.yml:105), so no workflow edit is needed.

- The proposed proof avoids the important vacuous twins:

  - verifies future-dated non-claimability;
  - asserts zero workers;
  - calls `/internal/pump`, not `drain_once()` directly;
  - asserts `claimed == 1` and `done == 1`;
  - reloads the exact `job_id` and checks `state == "done"`.

- The mandatory mutation RED/revert GREEN demonstration is appropriate given the repository’s existing proof discipline at [tests/test_queue_durability.py:988](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_queue_durability.py:988).

### Concerns

- **HIGH — The test does not stub `pipeline_glue.run_pipeline_now()`.**

  The job kind is `run_pipeline`; when the endpoint drains it, the handler invokes the actual pipeline at [app/queue/handlers/pipeline.py:154](/Users/pnhek/usf%20msds/github/payroll_agent/app/queue/handlers/pipeline.py:154).

  The existing durability proof explicitly warns that leaving this unstubbed can hit real providers and bill money at [tests/test_queue_durability.py:975](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_queue_durability.py:975), then stubs it at [tests/test_queue_durability.py:1018](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_queue_durability.py:1018).

  Plan 17-05 never instructs the executor to add that stub.

- **HIGH — Without a stub, `done == 1` may prove the wrong thing.**

  The pipeline catches recorded stage failures and returns normally; the queue then marks the job done. That behavior is documented at [app/queue/handlers/pipeline.py:74](/Users/pnhek/usf%20msds/github/payroll_agent/app/queue/handlers/pipeline.py:74). Therefore, `done == 1` could accompany a payroll run ending in `ERROR`, rather than a controlled proof handler executing successfully.

- **MEDIUM — The proof should assert a handler-side observable.**

  A route implementation that somehow bypassed dispatch and completed the job directly could satisfy the row-state assertion. An invocation list such as `orchestrator_calls == [run_id]` would prove the correct handler actually ran exactly once.

- **MEDIUM — Settings cache cleanup is again required.**

  The test changes `PUMP_TOKEN`; it must clear the settings cache after the test, not only before the request.

- **LOW — The mutation task temporarily edits production files not listed in frontmatter.**

  This is acceptable as uncommitted validation work, but the plan should state that `files_modified` describes final artifacts and that mutation edits are temporary.

### Suggestions

- Add the same controlled stub pattern already used in the module:

  ```python
  calls = []

  def _stub_run_pipeline_now(rid):
      calls.append(rid)
      repo.set_status(rid, RunStatus.COMPUTED)
  ```

  Then assert:

  ```python
  calls == [run_id]
  final_run["status"] == "computed"
  ```

- Retain all four proposed non-vacuity assertions. They are correctly chosen.

- Add `queue_depth == 0` after the one job completes. This provides a small live behavioral check for the new repository function, though a separate mixed-state live test is still needed.

- Use a post-yield fixture or `try/finally` to clear cached settings.

- For the falsifying mutation, making the HTTP route return an empty drain result is appropriate because it directly targets the phase responsibility. Record the exact failed assertion and ensure the production source diff is clean after revert.

### Risk assessment

**HIGH.** The proof design is excellent, but the missing pipeline stub can trigger real external calls and can let the test pass on a recorded payroll error rather than the intended controlled execution.

---

## Required revisions before execution

1. Resolve `fail_job()`-raises semantics so a genuine database write failure cannot be reported as `FENCED` with HTTP 200.
2. Derive pump and curl timeouts from total job runtime, not the 210-second consecutive-write gap.
3. Stub `pipeline_glue.run_pipeline_now()` in Plan 17-05 and assert it runs exactly once.
4. Update all existing six-function repository-surface tests for `count_open_jobs`.
5. Add real-Postgres behavioral coverage for the queue-depth state filter.
6. Add settings-cache teardown in pump route and durability tests.
7. Fix the GitHub workflow YAML verification so it does not rely on PyYAML interpreting unquoted `on` as a string.

With those changes, the plans should achieve all four roadmap success criteria with credible, non-vacuous evidence.

---

## Consensus Summary

Single external reviewer (Codex, codex-cli 0.144.0), source-grounded against the live tree. Codex read the referenced seams and cited `file:line` evidence for every finding, so these carry weight beyond impressionistic review. Overall verdict: **HIGH risk until the three HIGH findings are corrected**, then LOW–MEDIUM.

### Agreed Concerns (HIGH — address before execution)

1. **`fail_job()`-raises must NOT map to `FENCED` / must return 503 (17-01, 17-04) — contradicts D-10.**
   The double-failure branch at `app/queue/drain.py:180` is a *failed DB write that retains the lease* (infra failure), semantically distinct from a real lease-fence (`drain.py:7`: write succeeded but hit no row). Mapping it to `FENCED` lets the pump return **200 during a genuine DB outage**, breaking D-10's "5xx on infra failure." This overturns 17-RESEARCH.md Open Question #1's recommendation (which this planning cycle accepted and marked RESOLVED). Existing regression `tests/test_queue_drain.py:798` also requires a failed `fail_job()` not to escape — that test must be reconciled if the fix re-raises.

2. **The `--max-time`/wall-clock derivation misreads 210s (17-03, 17-04).**
   210s is the max **gap between consecutive DB writes** (stall threshold), NOT total job runtime — see `app/routes/runs.py:43` and `app/config.py:84`. `drain_once()` runs the whole handler before the wall-clock cap is re-checked, so the asserted ~330s request ceiling is unsupported; the real ceiling is `time-before-final-job + full runtime of that job`, unmeasured. Re-derive the curl timeout and `_MAX_WALL_CLOCK_SECONDS` from total handler runtime.

3. **17-05 durability proof must stub `pipeline_glue.run_pipeline_now()` (money + vacuity risk).**
   The seeded job is kind `run_pipeline`; draining it via the endpoint invokes the **real payroll pipeline and paid LLM providers** (`app/queue/handlers/pipeline.py:154`). The existing durability proof warns about exactly this (`tests/test_queue_durability.py:975`) and stubs it (`:1018`); 17-05 never instructs the stub. Worse, unstubbed, `done==1` can accompany a payroll run that ended in `ERROR` (the pipeline catches stage failures and returns normally — `pipeline.py:74`), so the proof could pass on the wrong outcome. Add the controlled stub and assert `orchestrator_calls == [run_id]`.

### Agreed Concerns (MEDIUM)

- **Stale "six-function public surface" tests (17-02):** `tests/test_repo_jobs_sql.py:193/228/242` still assert six functions and would stay green while falsely claiming full-surface coverage after `count_open_jobs` makes it seven.
- **Hermetic count test overstates proof (17-02):** a `FakeConnection` `fetchone` can prove return-mapping + WHERE text, not that Postgres counts pending/leased vs done/dead. The promised live half isn't actually specified in 17-05 — add a `queueproof` mixed-state count assertion.
- **PyYAML `on:` boolean-coercion bug (17-03):** a `yaml.safe_load(...)["on"]` verification fails on valid workflow YAML because YAML 1.1 parses unquoted `on` as boolean `True`. Use a loader without 1.1 boolean coercion or a static/text check.
- **Settings-cache teardown (17-04, 17-05):** `get_settings()` is `@lru_cache` (`app/config.py:145`); pump tests set `PUMP_TOKEN` and must `cache_clear()` *after* (post-yield/try-finally), not only before, or a cached token leaks across tests.
- **Catch-all over-claims "infra only" (17-04):** a `KeyError`/programming bug in the loop also becomes 503; the plan's "only genuine infra failures reach it" is too strong.

### Lower / discretionary

- 17-03: README timing wording ("≤30-min worst-case" → "nominally within one 30-min cadence"; `15 ÷ cadence` is idle-baseline arithmetic); add a committed static regression test for criterion #4 (not just grep).
- 17-04: GET vs POST for a state-changing route (user's discretion, D-locked).
- 17-01: Task 1 TDD-labeled but behavioral assertions land in Task 2.
- 17-05: note that mutation-demo edits to production files are temporary/uncommitted vs `files_modified`.

### Divergent Views
None — single reviewer.

### My read (orchestrator triage note)
Findings #1–#3 are the load-bearing ones and align precisely with this project's documented failure modes (infra-vs-business status honesty; unstubbed LLM calls in "proofs"; vacuous green tests). #1 and #3 are money/correctness-adjacent and should be treated as blocking. #2 is a real derivation error but the *mitigation* (a generous curl timeout + bounded loop) is directionally fine — it mainly needs an honest re-derivation and README wording, not a redesign. The MEDIUMs are all concrete and cheap. Recommend replanning via `--reviews`.
