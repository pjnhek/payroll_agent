# Phase 18: Failure Policy & Sweep Deletion - Research

**Researched:** 2026-07-15
**Phase:** 18 - Failure Policy & Sweep Deletion
**Overall confidence:** HIGH

<user_constraints>
## User Constraints

### Locked Decisions

- **D-01: One shared contract covers both orchestrator entry points.** Both initial runs and clarification resumes return the same `ok | retryable | terminal` result. Phase 19 must not inherit a second swallow-and-return contract when it queues resume work.
- **D-02: The result carries `outcome`, `stage`, and a safe reason code.** It carries no raw exception text, model output, submitted names, employee data, or other PII. Queue scheduling remains outside the result; the queue owns backoff timing.
- **D-03: `ok` stays coarse.** The result does not duplicate `process` versus `request_clarification`. `Decision.final_action` and `payroll_runs.status` remain the business authorities; the queue learns only that execution succeeded.
- **D-04: Pre-cutover background wrappers bridge retryable outcomes into the queue.** A first attempt may still begin as a framework `BackgroundTask` until Phase 19, but any classified retry uses durable queue work. No in-memory retry loop and no sweep fallback are introduced.
- **D-05: A retryable attempt returns the run to `received`.** While the job waits for `available_at`, the run is visibly queued rather than falsely shown as actively extracting or terminally failed. The next attempt uses the existing `received -> extracting` CAS.
- **D-06: `payroll_runs.status='error'` is final for this policy.** It is written only for an explicitly terminal result or retry exhaustion, including final-attempt lease reaping. It is not written and cleared on every transient attempt.
- **D-07: Dead-letter settlement is one fenced atomic transaction.** The job's transition to `dead` and the associated run's transition to `error` commit together or neither commits. The run write is CAS-scoped so a late/zombie worker cannot clobber a newer business state.
- **D-08: Transient diagnostics live on the job.** Safe stage/reason information remains in `jobs.last_error` with the attempt history. `payroll_runs.error_reason` and `error_detail` are reserved for terminal/exhausted outcomes.
- **D-09: Reuse the existing runs list and run-detail pages.** Atomic settlement puts the run in `error` with a safe dead-letter reason. The existing Retrigger action is the operator's recovery path; Phase 18 does not create the Phase 21 queue dashboard.
- **D-10: Retrigger creates a new job generation.** The exhausted job row remains immutable audit history. An operator-authorized Retrigger enqueues a new row/dedup generation with a fresh bounded attempt budget and fencing token; it does not reset or reopen the dead row.
- **D-11: The final run diagnostic is stable and bounded.** It shows the final reason, safe stage when durably known, and exhausted attempt count (for example `5/5`). It distinguishes ordinary retry exhaustion from final-attempt lease expiry and never copies raw provider/model output.
- **D-12: Keep the real run status `error`; add a secondary exhaustion label.** Existing list and detail pages show `Retries exhausted` alongside the real `error` status, and the detail page retains Retrigger. No new `RunStatus` is invented for queue state.
- **D-13: Reaping is part of every shared `drain_once()` path.** Before the drain reports the queue empty, it can atomically settle an expired `leased` row whose `attempts == max_attempts` as `dead`. Workers and `/internal/pump` therefore use the same code path; a separate maintenance sweep is forbidden.
- **D-14: Pump accounting is truthful.** A final-lease reap increments `dead` and a `reaped_final_lease` subcount, but not `claimed`, because the pump settled the row without executing the job.
- **D-15: A reaped lease uses the dedicated `FinalAttemptLeaseExpired` reason.** Any earlier `jobs.last_error` remains attempt history but is not misattributed to the final worker death. Include a stage only if it is durably known.
- **D-16: An explicit terminal result settles the job as `done` and the run as `error`.** The transport successfully executed and classified the work. `dead` remains reserved for exhausted retries and expired final-attempt lease reaping.
- **D-17: The Phase 17 accepted lease strand is closed here.** The failure-policy dead-letter transition MUST reap `state='leased' AND attempts=max_attempts AND leased_until<now()`. Excluding it from queue depth or documenting it again is not a fix.
- **D-18: Sweep deletion is complete and unconditional.** Delete `sweep_stranded_runs`, `find_stranded_unconsumed_replies`, the runs-list page-load recovery block, facade exports, fakes, and tests that exist only to preserve those mechanisms. Do not preserve `sweep_stranded_runs` under a new name or behind a fallback. `GET /runs` becomes a side-effect-free read.

### The Agent's Discretion

- The concrete Python representation of the result contract (for example, enum plus frozen dataclass versus an equivalent typed structure), provided D-01 through D-03 are enforced and the safe default remains `terminal`.
- The exact SQL/CTE/function decomposition used to atomically select and settle an exhausted lease, provided it is fenced, shared by workers and pump, observable as the D-14 outcome, and cannot race a legitimate lease owner.
- The exact styling of the secondary `Retries exhausted` label within the existing templates.
- Backoff constants and jitter implementation details may be validated during research against the already-shipped curve and the milestone recovery bound; exponential backoff, jitter, `available_at`, and a bounded attempt cap are not optional.

### Deferred Ideas

- **Full durable producer cutover** — migrate all eight `BackgroundTasks` producers and durable ingest/reply work in Phase 19. Phase 18 only bridges classified retries.
- **Exactly-once send** — persisted payload replay and Resend idempotency remain Phase 20.
- **Full queue operations view and alarm** — depth, oldest-pending age, attempts distribution, dead-letter list, and the swallowing-bug alarm remain OPS-01 / Phase 21.
</user_constraints>

<phase_requirements>
## Phase Requirements

| Requirement | What the phase must prove | Research implication |
|---|---|---|
| FAIL-01 | Both orchestrator entry points return an explicit safe-default `ok | retryable | terminal` result; clarification is success. | Introduce one typed contract and make classification stage-aware. Never infer failure from the business action. [VERIFIED: `.planning/REQUIREMENTS.md` and codebase trace] |
| FAIL-02 | Retryable failures use the existing bounded queue; exhausted work is visible and durably retriggerable. | Settle the job and run together, add final-attempt lease reaping, retain dead rows, and surface a bounded exhaustion reason. [VERIFIED: `.planning/REQUIREMENTS.md` and codebase trace] |
| FAIL-03 | The old sweep and dashboard-as-cron path are deleted. | Remove both repository sweep APIs, facade exports, route mutation, fakes, and preservation-only tests; add a negative grep and side-effect-free route proof. [VERIFIED: `.planning/REQUIREMENTS.md` and codebase trace] |
</phase_requirements>

## Executive Summary

Phase 18 should be planned as a coordinated contract-and-settlement change, not as an exception-catching patch. Today both orchestrator entry points convert stage failures into `ERROR` and return normally, while `drain_once()` interprets normal return as transport success. The durable fix is to make the orchestrator return a typed, PII-safe result; let the queue translate it into atomic fenced settlement; and delete every automatic recovery path that is not the queue. [VERIFIED: codebase trace]

The most important hidden seam is clarification-resume retry. `resume_pipeline()` consumes a persisted reply and uses its body/history, while ordinary `run_pipeline()` reloads the original inbound. A retryable resume therefore cannot be bridged to the existing `run_pipeline` job kind without losing the client's clarification. The narrow Phase 18 bridge should use the already-present `jobs.email_id` column and a dedicated resume job kind/handler that reconstructs the persisted reply. This does not pull the full eight-producer cutover from Phase 19 forward: the first attempt may remain a `BackgroundTask`; only a classified retry becomes durable. [VERIFIED: codebase trace]

No new package or runtime configuration is required. Installed versions are FastAPI 0.138.0, OpenAI 2.43.0, psycopg 3.3.4, and pytest 9.1.1. [VERIFIED: current environment inspection]

## Project Constraints

- Use Python 3.12 and `uv`; do not introduce pip, Poetry, virtualenv commands, or a hand-maintained `requirements.txt`. [VERIFIED: `AGENTS.md`]
- Preserve deterministic money-moving decisions: the LLM extracts and drafts, while code alone resolves names and chooses process versus clarify. [VERIFIED: `AGENTS.md`]
- Preserve exactly one human approval gate and Postgres as durable state. [VERIFIED: `AGENTS.md`]
- Keep the plain-Python fixed workflow; do not introduce an agent framework or an external queue dependency. [VERIFIED: `AGENTS.md` and milestone research]
- Structured LLM calls use JSON mode plus Pydantic with one parse retry. [VERIFIED: `AGENTS.md` and `app/llm/client.py`]
- Security enforcement is enabled at ASVS L1, and Nyquist validation is enabled. [VERIFIED: `.planning/config.json`]

## Current-System Trace

### Orchestrator behavior

- `run_pipeline()` delegates to `_run()`, whose catch-all records a run error and returns `None`; `resume_pipeline()` has the same swallow-and-record pattern. A queue handler therefore cannot distinguish success, retryability, and terminal failure. [VERIFIED: `app/pipeline/orchestrator.py`]
- Extraction occurs before deterministic reconciliation and decisioning. The extraction client has SDK retries disabled (`max_retries=0`) and retains the application-level one parse retry. [VERIFIED: `app/pipeline/orchestrator.py` and `app/llm/client.py`]
- The clarification branch is a successful business outcome and eventually writes `awaiting_reply`; draft/suggestion failures already degrade to safe fallback text. It must return `ok`, and it must not re-send merely because the business decision was to clarify. [VERIFIED: codebase trace]
- Resume claims and consumes clarification context, then operates on the persisted reply body and run history. Re-running initial pipeline work is not an equivalent retry. [VERIFIED: `app/pipeline/orchestrator.py`]

### Queue behavior

- `claim_job()` increments `attempts` at claim and can reclaim an expired lease only while `attempts < max_attempts`. Therefore the exact row `state='leased' AND attempts=max_attempts AND leased_until<now()` is permanently unclaimable today. [VERIFIED: `app/db/repo/jobs.py`]
- `drain_once()` has one falsy outcome (`EMPTY`) and truthy `DONE`, `RETRIED`, `DEAD`, and `FENCED` outcomes. Workers and `/internal/pump` both use this seam. [VERIFIED: `app/queue/drain.py`]
- `_backoff_seconds()` uses a 5-second base, doubles per claimed attempt, caps at 300 seconds, and jitters by 0.5x–1.5x. With five attempts, the four retry waits are nominally 5, 10, 20, and 40 seconds; their maximum jittered total is 112.5 seconds. The existing curve is comfortably inside the milestone's roughly 30-minute recovery target, with pump cadence dominating while the service is asleep. Keep it. [VERIFIED: `app/queue/drain.py` and arithmetic]
- `complete_job()` and `fail_job()` are fenced by the exact lease token. The new settlement APIs must retain that behavior and must not let a late worker overwrite a newer run state. [VERIFIED: `app/db/repo/jobs.py`]

### Sweep and UI behavior

- `sweep_stranded_runs()` and `find_stranded_unconsumed_replies()` remain exported through the repository facade and are invoked by the runs-list route. The GET therefore still mutates state and schedules work. [VERIFIED: `app/db/repo/runs.py`, `app/db/repo/emails.py`, `app/db/repo/__init__.py`, and `app/routes/runs.py`]
- `STALE_THRESHOLD` is also used by manual Retrigger behavior. Delete the runs-list sweep block, not the constant indiscriminately. [VERIFIED: `app/routes/runs.py`]
- The list query does not currently select `error_reason`, while the detail load does. Both initial rendering and polling need enough bounded data to display `Retries exhausted` without inventing a new `RunStatus`. [VERIFIED: `app/db/repo/runs.py`, `app/templates/runs_list.html`, `app/templates/run_detail.html`, and route response shaping]
- Retrigger already advances the reply epoch and enqueues a new dedup generation. The dead job can remain immutable audit history. [VERIFIED: `app/routes/runs.py`]

## Recommended Architecture

### 1. Shared result contract

Use a small `StrEnum` plus frozen dataclass in a neutral module such as `app/pipeline/result.py`:

```python
class PipelineOutcome(StrEnum):
    OK = "ok"
    RETRYABLE = "retryable"
    TERMINAL = "terminal"

@dataclass(frozen=True)
class PipelineResult:
    outcome: PipelineOutcome = PipelineOutcome.TERMINAL
    stage: PipelineStage = PipelineStage.UNKNOWN
    reason: PipelineReason = PipelineReason.UNCLASSIFIED
```

The concrete names are discretionary, but the constructor default should be terminal, and every field must come from a bounded enum/value set. Do not place exception strings, prompts, names, model content, or provider response bodies in the result. [VERIFIED: D-01 through D-03]

Track the active stage immediately before each side-effectful operation. Recommended high-level stages are `load`, `extract`, `persist`, `clarification`, `compute`, and `delivery`; reason codes should be narrower only where the policy can act differently. The classifier should be contextual, not merely `isinstance(exc, ...)`. [VERIFIED: approved milestone design and codebase trace]

For extraction, classify OpenAI SDK connection errors, timeouts, rate limits, and 5xx server responses as retryable. In OpenAI 2.43.0, `APITimeoutError` is an `APIConnectionError`, and `RateLimitError` plus `InternalServerError` are `APIStatusError` subclasses. Terminal 4xx responses and exhausted Pydantic schema/parse failures should remain terminal. [CITED: https://github.com/openai/openai-python]

Use safe-terminal for unclassified cases. In particular, do not auto-retry clarification/delivery sends in Phase 18: a timeout can occur after provider acceptance, and Phase 20 owns idempotent send replay. `request_clarification` as a completed deterministic branch remains `ok`; a failure while transmitting an email is a different event and should fail closed until the Phase 20 send contract exists. [VERIFIED: phase boundaries and codebase trace]

### 2. Durable retry bridge for both entry points

`run_pipeline_bg()` and `resume_pipeline_bg()` should interpret the shared result. `ok` and `terminal` require no in-memory retry. A retryable result must enter the durable queue in the same transaction that returns the run from `extracting` to `received`. [VERIFIED: D-04 through D-08]

Initial-run retry can use the existing `run_pipeline` kind. Resume retry needs a lossless bridge:

1. Add a dedicated resume-reply `JobKind` and widen the database CHECK constraint.
2. Add `email_id` to the claimed `Job` representation and `RETURNING` projection; the column already exists in `jobs`.
3. Enqueue the retry with the persisted reply email id and a dedup key scoped to run/reply generation.
4. The resume handler reloads the persisted email row, reconstructs `InboundEmail`, and calls `resume_pipeline()` from the retry waiting state.

This is the smallest design that satisfies D-01 and D-04 without discarding clarification context. Sending a resume retry to `run_pipeline` would silently process the original inbound instead of the client's answer. [VERIFIED: `app/models/job.py`, `app/db/schema.sql`, `app/routes/pipeline_glue.py`, and orchestrator trace]

Because the jobs table already exists, changing the inline schema definition alone is insufficient for deployed databases. Include an idempotent migration that replaces/widens the kind CHECK constraint, plus drift tests for Python kinds, SQL kinds, dispatch handlers, and claim projections. [VERIFIED: schema and existing drift-test pattern]

### 3. One atomic settlement seam

Keep `jobs.py` focused on transport primitives and add a focused cross-aggregate settlement module, for example `app/db/repo/job_settlement.py`. The exact file is discretionary; the important property is one caller-owned transaction covering both the fenced job write and CAS-scoped run write. Psycopg transaction contexts commit on success and roll back on exception; nested transaction contexts create savepoints, so document who owns the outer transaction and use a single connection throughout. [CITED: https://www.psycopg.org/psycopg3/docs/basic/transactions.html]

Use this settlement matrix:

| Pipeline result / queue event | Job transition | Run transition | Drain outcome |
|---|---|---|---|
| `ok` | leased → done, fenced | Business state already authoritative | `DONE` |
| `retryable`, attempts below cap | leased → pending with `available_at` and safe `last_error`, fenced | `extracting → received` CAS | `RETRIED` |
| `retryable`, attempts at cap | leased → dead, fenced | eligible active state → error CAS with bounded exhaustion diagnostic | `DEAD` |
| `terminal` | leased → done, fenced | eligible active state → error CAS with safe reason | `DONE` |
| expired final-attempt lease | leased → dead under exact expiry predicate | eligible active state → error CAS with `FinalAttemptLeaseExpired` | `REAPED_FINAL_LEASE` |

A lost lease-token fence means the current worker is a zombie and must return `FENCED` without another write. A lost run CAS means a newer business state owns the run; settlement must not clobber it. Plan explicit tests for both cases and define the latter as a deliberate fenced/no-op outcome rather than an accidental partial failure. [VERIFIED: existing fencing pattern and D-07]

### 4. Reap before reporting empty

In `drain_once()`, attempt the normal claim first. If no due job is claimable, call one atomic final-lease reaper before returning `EMPTY`. Give the reap its own truthy drain outcome. This ordering drains executable work first, settles at most one abandoned row per call, and makes both daemon workers and pump continue until no executable or reapable row remains. [VERIFIED: D-13 and current worker loop]

The SQL predicate is exact and non-negotiable:

```sql
state = 'leased'
AND attempts = max_attempts
AND leased_until < now()
```

Select/lock one candidate with `FOR UPDATE SKIP LOCKED`, then write job `dead` and run `error` in the same transaction. Do not require the expired token to equal a worker-held token: the reaper is acting only after expiry under a row lock. [VERIFIED: D-13, D-17, and queue schema]

### 5. Pump accounting

Add `reaped_final_lease` to the pump response. A reap increments `dead` and `reaped_final_lease`, but not `claimed`. The truthful invariant becomes:

```text
claimed == done + retried + (dead - reaped_final_lease) + fenced
```

Existing code assumes every non-empty drain outcome was claimed, so the route tests and count loop must change together with `DrainOutcome`. [VERIFIED: `app/routes/pump.py` and D-14]

### 6. Sweep deletion and UI

Delete the two repository functions, their facade imports/exports, and the runs-list recovery block. Remove only recovery-specific test cases/fakes; preserve webhook redelivery, spoof protection, late-reply handling, and manual retrigger tests. `row_to_inbound()` may remain if used by durable resume reconstruction, but its docstring must no longer claim a sweep caller. [VERIFIED: codebase trace]

Add two deletion gates:

- a source grep/AST assertion that neither sweep symbol remains; and
- a route test that patches mutating repository/scheduling functions to fail if called, then proves `GET /runs` only loads and renders.

For the narrow UI extension, select `error_reason` in the runs-list query and expose the stable secondary label both on initial render and status polling. The detail page should retain its existing bounded error data and Retrigger action. [VERIFIED: D-09 through D-12]

FastAPI `BackgroundTasks` execute after a response and are not a durable multi-process job system; FastAPI's documentation explicitly points heavier durable work toward a queue-backed tool. Phase 18's bridge therefore should be temporary and limited to the first attempt, with all classified retries persisted. [CITED: https://fastapi.tiangolo.com/tutorial/background-tasks/]

## Runtime State Inventory

This phase changes failure semantics and deletes a recovery mechanism, so runtime state must be handled explicitly.

| Runtime state | Existing state | Required transition / cleanup |
|---|---|---|
| Stored data | Existing `jobs` rows may include dead history and expired final-attempt leased rows. Existing reply rows may be linked and unconsumed. | Preserve dead rows. Reap exact final-attempt strands through `drain_once()`. Widen the job-kind CHECK idempotently for lossless resume retries. Do not bulk-delete replies; deletion removes the old automatic scan, while the retry bridge handles classified failures and Phase 19 owns full producer cutover. [VERIFIED: schema and codebase trace] |
| Live service configuration | Existing attempt cap, lease duration, worker poll interval, and pump token already support the policy. | No new environment variable is needed; keep existing bounded backoff constants. [VERIFIED: config/codebase trace] |
| OS-registered state | No launch daemon, cron registration, socket, or service unit is introduced by Phase 18. | No OS cleanup. [VERIFIED: phase scope] |
| Secrets and credentials | No new provider, token, or credential is required. | No secret migration. Continue storing only safe reason enums/codes. [VERIFIED: phase scope] |
| Build/cache artifacts | Python caches may exist locally but are not part of durable execution state. | No artifact migration; do not treat cache cleanup as a phase deliverable. [VERIFIED: repository inspection] |

## Security Domain

Security enforcement is enabled, and this phase touches integrity, authorization-adjacent recovery, and sensitive error handling. [VERIFIED: `.planning/config.json`]

| ASVS area / threat | Risk | Required mitigation |
|---|---|---|
| V4 access control: operator Retrigger | A public or new mutating path could reopen failed payroll work. | Reuse the existing operator action and auth posture; do not add a public dead-letter mutation route. [VERIFIED: phase scope] |
| V5 validation: exception and model data | Raw provider/model/PII content could reach job diagnostics, UI, or logs. | Store bounded stage/reason codes only; never serialize raw exceptions or model output. [VERIFIED: D-02, D-08, D-11] |
| Integrity: zombie worker | A late lease holder could overwrite a newer run or job state. | Require lease-token fencing for worker settlement and CAS-scoped run writes in the same transaction. [VERIFIED: existing queue invariants] |
| Integrity: duplicate clarification/send | Retrying a successful clarification branch or an ambiguous send failure could duplicate client email. | Treat clarification as `ok`; leave ambiguous send failures terminal until Phase 20 idempotency. [VERIFIED: phase boundaries] |
| Integrity: GET mutation | Dashboard reads can race durable queue recovery. | Delete the sweep/page-load cron behavior and prove `GET /runs` has no writes or scheduling. [VERIFIED: FAIL-03] |
| Audit integrity: operator retrigger | Reopening a dead row would erase failure history or confuse fencing. | Keep dead row immutable and create a fresh epoch/dedup generation. [VERIFIED: D-10 and current retrigger flow] |
| V5 SQL injection | New reaper/settlement SQL handles ids and diagnostics. | Use parameterized SQL and bounded enum-derived diagnostic values. [VERIFIED: project repository pattern] |

No new authentication, cryptography, session, file-upload, or deserialization surface is introduced. [VERIFIED: phase scope]

## Validation Architecture

Nyquist validation is enabled, so each behavior needs a fast hermetic proof plus live-Postgres coverage where atomicity/fencing is the claim. [VERIFIED: `.planning/config.json`]

### Requirement-to-test map

| Requirement | Hermetic coverage | Live/integration coverage |
|---|---|---|
| FAIL-01 | Result defaults terminal; both entry points return all three outcomes; OpenAI timeout/connection/429/5xx extraction failures classify retryable; parse/schema failure terminal; clarification returns `ok` and sends once. | Not required for pure classification; use repository-backed orchestrator tests only where state transition behavior is material. |
| FAIL-02 | Drain result mapping, backoff, attempt cap, resume bridge preserving `email_id`, final reaper outcome, pump counters/invariant, UI label, and Retrigger new generation. | Atomic retry/dead settlement, exact final-attempt reap predicate, rollback on half-failure, lease-token zombie fencing, and lost run-CAS behavior in `tests/test_queue_durability.py`. |
| FAIL-03 | Negative symbol grep, facade drift, no sweep fakes, and side-effect-free `GET /runs`. | A route-level repository spy is sufficient; no live DB is needed for the deletion claim. |

### Suggested test placement

- Extend `tests/test_queue_drain.py`, `tests/test_repo_jobs_sql.py`, and `tests/test_pump_route.py` for hermetic transport behavior. [VERIFIED: existing test organization]
- Add orchestrator contract/classifier tests alongside current state/orchestrator tests rather than hiding them inside queue tests. [VERIFIED: existing test organization]
- Extend `tests/test_queue_durability.py` for live database atomicity and fencing; it already carries the integration/queueproof markers used by the real-Postgres workflow. [VERIFIED: test and CI inspection]
- Rewrite `tests/test_stuck_run_recovery.py`, `tests/test_reply_redelivery.py`, `tests/test_needs_operator.py`, and `tests/conftest.py` selectively: delete sweep-preservation assertions and fakes while retaining unrelated safety/retrigger/redelivery coverage. [VERIFIED: codebase grep]
- Update `tests/test_job_kind_drift.py` and dispatch-bijection checks if the resume-reply kind is added. [VERIFIED: existing drift guards]

### Verification commands

```bash
UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q \
  tests/test_queue_drain.py tests/test_pump_route.py tests/test_repo_jobs_sql.py \
  tests/test_stuck_run_recovery.py tests/test_reply_redelivery.py

uv run pytest tests/test_queue_durability.py -m queueproof -v -rs
uv run ruff check .
uv run mypy
uv run pytest -q
```

The current focused baseline is `61 passed, 2 skipped` with one unrelated Starlette TestClient deprecation warning. [VERIFIED: current test run]

## Planning Decomposition

The plan should keep atomic dependencies together and preserve a red/green verification loop:

1. **Contract and classification:** add the typed safe result, stage tracking, both orchestrator returns, and classifier unit tests.
2. **Durable bridge and schema drift:** propagate results through wrappers/handlers; add lossless resume-reply retry support, schema migration, and drift tests.
3. **Atomic settlement and reaper:** implement fenced cross-aggregate settlement, exact final-lease reaping, drain outcomes, and live database proofs.
4. **Pump/UI/retrigger integration:** correct pump accounting, add bounded exhaustion display, and prove fresh-generation retrigger behavior.
5. **Sweep subtraction:** remove both sweep APIs, facade exports, route mutation, fakes, and preservation-only tests; add deletion and side-effect-free GET gates.
6. **Full verification:** targeted tests, queueproof real-DB tests, Ruff, mypy, full suite, and diff hygiene.

Do not split the dead-job write and run-error write into separately shippable tasks: their atomicity is the requirement. Do not delete the sweep before the queue path can durably bridge both initial and resume retries. [VERIFIED: D-04, D-07, D-18]

## Risks and Planning Warnings

1. **Resume-context loss (highest):** mapping resume retry to the existing initial-run handler discards the clarification reply. Require `email_id`-backed durable resume work. [VERIFIED: codebase trace]
2. **Send ambiguity:** over-broad retry classification can duplicate clarification or final delivery before Phase 20. Classify by stage and fail closed at send boundaries. [VERIFIED: phase boundary]
3. **Deployed CHECK drift:** adding a Python job kind without an idempotent SQL constraint migration works only on fresh databases. [VERIFIED: schema behavior]
4. **False atomicity:** calling two repository functions that each open their own transaction does not satisfy D-07. Pass one connection/transaction across both writes. [CITED: https://www.psycopg.org/psycopg3/docs/basic/transactions.html]
5. **Pump count inflation:** treating a reaped row as claimed breaks existing count meaning. Use a distinct outcome and the D-14 invariant. [VERIFIED: route trace]
6. **Over-deletion:** `STALE_THRESHOLD`, reply sender validation, and redelivery logic have non-sweep uses. Delete by symbol/call path, then run focused safety tests. [VERIFIED: codebase trace]
7. **Stale polling label:** updating only server-rendered templates makes exhaustion disappear on AJAX transitions until refresh. Update both initial and polling response shaping. [VERIFIED: UI trace]

## Assumptions Log

No material assumptions are required. The recommendation to add a dedicated resume-reply job kind is an inference from the locked lossless retry contract and verified persisted-reply behavior, not a new product decision. [VERIFIED: D-01, D-04, and codebase trace]

## Sources

### Primary project sources

- `.planning/phases/18-failure-policy-sweep-deletion/18-CONTEXT.md`
- `.planning/REQUIREMENTS.md`
- `.planning/ROADMAP.md`
- `.planning/PROJECT.md`
- `.planning/STATE.md`
- `.planning/phases/17-the-pump/17-SECURITY.md`
- `.planning/phases/17-the-pump/17-CONTEXT.md`
- `.planning/phases/16-queue-substrate-unblocked-webhook/16-CONTEXT.md`
- `docs/superpowers/specs/2026-07-13-durable-execution-design.md`
- `AGENTS.md`
- Current source and tests named throughout this document. [VERIFIED: codebase inspection]

### Official external sources

- OpenAI Python error handling and exception taxonomy: https://github.com/openai/openai-python [CITED: official repository]
- Psycopg transaction contexts and nested savepoints: https://www.psycopg.org/psycopg3/docs/basic/transactions.html [CITED: official documentation]
- FastAPI background task execution and durable-work caveat: https://fastapi.tiangolo.com/tutorial/background-tasks/ [CITED: official documentation]

## Confidence Assessment

| Area | Confidence | Basis |
|---|---|---|
| Current swallow/return behavior and sweep call graph | HIGH | Direct source trace and focused passing baseline. |
| Queue attempt/fencing/reaper design | HIGH | Direct SQL/source trace plus accepted Phase 17 risk. |
| Lossless resume bridge requirement | HIGH | Direct comparison of persisted resume inputs with initial-run inputs. |
| OpenAI exception taxonomy | HIGH | Installed-class inspection plus official SDK documentation. |
| Psycopg atomic transaction mechanics | HIGH | Existing repository pattern plus official documentation. |
| UI and test touch points | HIGH | Direct template, route, facade, fake, and test inspection. |
| External web lookup freshness | MEDIUM | Official-source web fallback was used because Context7 was unavailable; claims were cross-checked against installed versions. |

## Research Conclusion

Phase 18 is ready to plan. The implementation path is clear: one typed stage-aware result, one lossless durable retry bridge for each entry point, one fenced atomic settlement seam, one shared final-lease reaper, truthful pump/UI visibility, and complete deletion of the sweep. The phase introduces no new dependency or configuration and has a concrete hermetic-plus-live validation strategy. [VERIFIED: combined research]
