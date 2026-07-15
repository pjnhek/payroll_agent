# Phase 18: Failure Policy & Sweep Deletion - Context

**Gathered:** 2026-07-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 18 replaces swallowed pipeline failures with one explicit failure policy and makes
the durable queue the sole automatic recovery mechanism.

This phase delivers all of the following as one coherent change:

1. `run_pipeline` and `resume_pipeline` return the same explicit
   `ok | retryable | terminal` result contract. `request_clarification` is an `ok`
   outcome; it is never retried as a failure.
2. Retryable outcomes use the queue's existing `available_at`, exponential-backoff,
   jitter, attempt-cap, lease, and fencing machinery. Until Phase 19 performs the full
   producer cutover, existing `BackgroundTask` wrappers bridge retryable outcomes into
   the durable queue rather than creating a second recovery path.
3. Exhausted retries and expired final-attempt leases are dead-lettered. The accepted
   Phase 17 strand (`state='leased'`, `attempts == max_attempts`, expired lease) MUST be
   reaped by the shared drain path; it may not remain permanently unreclaimable.
4. Final job settlement and the associated business-run error transition are fenced and
   atomic. Transient failures return the run to `received`; final failures put it in
   `error` and make the existing Retrigger action useful.
5. `sweep_stranded_runs`, `find_stranded_unconsumed_replies`, the runs-list recovery
   block, their facade exports, and their recovery-specific tests/fakes are deleted.
   There is exactly one automatic recovery mechanism after this phase: the queue. The
   old sweep is not retained, renamed, or kept as a fallback.

**Requirements:** FAIL-01, FAIL-02, FAIL-03.

**Out of scope:** the full eight-producer queue cutover (Phase 19), exactly-once send
(Phase 20), and the full queue-health/dead-letter operations page and alarms (Phase 21).
Phase 18 may add a narrow exhaustion label to the existing runs UI, but it does not pull
the Phase 21 ops dashboard forward.

</domain>

<decisions>
## Implementation Decisions

### Result contract

- **D-01: One shared contract covers both orchestrator entry points.** Both initial runs
  and clarification resumes return the same `ok | retryable | terminal` result. Phase 19
  must not inherit a second swallow-and-return contract when it queues resume work.
- **D-02: The result carries `outcome`, `stage`, and a safe reason code.** It carries no
  raw exception text, model output, submitted names, employee data, or other PII. Queue
  scheduling remains outside the result; the queue owns backoff timing.
- **D-03: `ok` stays coarse.** The result does not duplicate `process` versus
  `request_clarification`. `Decision.final_action` and `payroll_runs.status` remain the
  business authorities; the queue learns only that execution succeeded.
- **D-04: Pre-cutover background wrappers bridge retryable outcomes into the queue.** A
  first attempt may still begin as a framework `BackgroundTask` until Phase 19, but any
  classified retry uses durable queue work. No in-memory retry loop and no sweep fallback
  are introduced.

### Run status during retries

- **D-05: A retryable attempt returns the run to `received`.** While the job waits for
  `available_at`, the run is visibly queued rather than falsely shown as actively
  extracting or terminally failed. The next attempt uses the existing
  `received -> extracting` CAS.
- **D-06: `payroll_runs.status='error'` is final for this policy.** It is written only for
  an explicitly terminal result or retry exhaustion, including final-attempt lease
  reaping. It is not written and cleared on every transient attempt.
- **D-07: Dead-letter settlement is one fenced atomic transaction.** The job's transition
  to `dead` and the associated run's transition to `error` commit together or neither
  commits. The run write is CAS-scoped so a late/zombie worker cannot clobber a newer
  business state.
- **D-08: Transient diagnostics live on the job.** Safe stage/reason information remains
  in `jobs.last_error` with the attempt history. `payroll_runs.error_reason` and
  `error_detail` are reserved for terminal/exhausted outcomes.

### Dead-letter visibility and operator action

- **D-09: Reuse the existing runs list and run-detail pages.** Atomic settlement puts the
  run in `error` with a safe dead-letter reason. The existing Retrigger action is the
  operator's recovery path; Phase 18 does not create the Phase 21 queue dashboard.
- **D-10: Retrigger creates a new job generation.** The exhausted job row remains immutable
  audit history. An operator-authorized Retrigger enqueues a new row/dedup generation with
  a fresh bounded attempt budget and fencing token; it does not reset or reopen the dead
  row.
- **D-11: The final run diagnostic is stable and bounded.** It shows the final reason,
  safe stage when durably known, and exhausted attempt count (for example `5/5`). It
  distinguishes ordinary retry exhaustion from final-attempt lease expiry and never
  copies raw provider/model output.
- **D-12: Keep the real run status `error`; add a secondary exhaustion label.** Existing
  list and detail pages show `Retries exhausted` alongside the real `error` status, and
  the detail page retains Retrigger. No new `RunStatus` is invented for queue state.

### Exhaustion and final-attempt lease reaping

- **D-13: Reaping is part of every shared `drain_once()` path.** Before the drain reports
  the queue empty, it can atomically settle an expired `leased` row whose
  `attempts == max_attempts` as `dead`. Workers and `/internal/pump` therefore use the same
  code path; a separate maintenance sweep is forbidden.
- **D-14: Pump accounting is truthful.** A final-lease reap increments `dead` and a
  `reaped_final_lease` subcount, but not `claimed`, because the pump settled the row
  without executing the job.
- **D-15: A reaped lease uses the dedicated `FinalAttemptLeaseExpired` reason.** Any
  earlier `jobs.last_error` remains attempt history but is not misattributed to the final
  worker death. Include a stage only if it is durably known.
- **D-16: An explicit terminal result settles the job as `done` and the run as `error`.**
  The transport successfully executed and classified the work. `dead` remains reserved
  for exhausted retries and expired final-attempt lease reaping.

### Locked recovery constraints supplied before discussion

- **D-17: The Phase 17 accepted lease strand is closed here.** The failure-policy
  dead-letter transition MUST reap `state='leased' AND attempts=max_attempts AND
  leased_until<now()`. Excluding it from queue depth or documenting it again is not a fix.
- **D-18: Sweep deletion is complete and unconditional.** Delete
  `sweep_stranded_runs`, `find_stranded_unconsumed_replies`, the runs-list page-load
  recovery block, facade exports, fakes, and tests that exist only to preserve those
  mechanisms. Do not preserve `sweep_stranded_runs` under a new name or behind a fallback.
  `GET /runs` becomes a side-effect-free read.

### the agent's Discretion

- The concrete Python representation of the result contract (for example, enum plus
  frozen dataclass versus an equivalent typed structure), provided D-01 through D-03 are
  enforced and the safe default remains `terminal`.
- The exact SQL/CTE/function decomposition used to atomically select and settle an
  exhausted lease, provided it is fenced, shared by workers and pump, observable as the
  D-14 outcome, and cannot race a legitimate lease owner.
- The exact styling of the secondary `Retries exhausted` label within the existing
  templates.
- Backoff constants and jitter implementation details may be validated during research
  against the already-shipped curve and the milestone recovery bound; exponential
  backoff, jitter, `available_at`, and a bounded attempt cap are not optional.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 18 scope and requirements

- `.planning/ROADMAP.md` — Phase 18 goal and five success criteria, including visible
  dead-lettering, full sweep deletion, and side-effect-free `GET /runs`.
- `.planning/REQUIREMENTS.md` — FAIL-01, FAIL-02, and FAIL-03; authoritative contract,
  retry/dead-letter, and deletion requirements.
- `.planning/PROJECT.md` — v4 Durable Execution boundary and the approved failure-policy
  feature description.
- `.planning/STATE.md` — current Phase 17/18 decisions, especially transport/business
  state separation and the non-negotiable same-phase sweep deletion.

### Accepted upstream risk that Phase 18 must close

- `.planning/phases/17-the-pump/17-SECURITY.md` — T-17-16 and AR-17-03 define the accepted
  final-attempt expired-lease strand and explicitly charter its dead-letter fix here.
- `.planning/phases/17-the-pump/17-CONTEXT.md` — Phase 17 drain outcomes, pump accounting,
  and the explicit deferral of real failure classification and sweep deletion to Phase 18.
- `.planning/phases/16-queue-substrate-unblocked-webhook/16-CONTEXT.md` — queue invariants,
  attempts-at-claim semantics, CAS/fencing rules, no automatic epoch bump, and the Phase 18
  deferrals this phase now resolves.

### Approved milestone design

- `docs/superpowers/specs/2026-07-13-durable-execution-design.md` — authoritative sections
  `Build order`, `Deleting the sweep is not optional`, and `Failure policy`; locks the
  contextual result classification, safe-terminal default, backoff/dead-letter direction,
  and forced order before webhook cutover.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `app/queue/drain.py::DrainOutcome` and `drain_once()` — the worker/pump shared drain
  seam. `EMPTY` is the only falsy outcome; every settled/retried/dead/reaped outcome must
  stay truthy so `worker.py` continues draining.
- `app/queue/drain.py::_backoff_seconds()` — existing exponential backoff with injectable
  jitter and a cap; Phase 18 connects classified retryable stage failures to this real
  queue path rather than inventing another timer.
- `app/db/repo/jobs.py::fail_job()` — already fenced on `lease_token`, writes safe
  `last_error`, schedules `available_at`, and returns `pending` versus `dead` for ordinary
  caught failures.
- `app/db/repo/jobs.py::claim_job()` — increments attempts at claim and reclaims expired
  leases only while `attempts < max_attempts`. Its guard is the direct cause of the
  accepted final-attempt strand D-17 must close.
- `app/db/repo/pipeline_state.py::rewind_for_reclaim()` and
  `app/db/repo/runs.py::claim_status()` — established CAS-only business-state recovery and
  forward-claim patterns. Automatic recovery does not bump `reply_epoch`.
- `app/routes/runs.py` plus `app/templates/runs_list.html` and
  `app/templates/run_detail.html` — existing error visibility and Retrigger surface to
  extend narrowly for D-09 through D-12.

### Established Patterns

- **INVARIANT J-1:** `jobs` is transport state only; `payroll_runs.status` is the sole
  business state machine. No new run status may be invented to mirror `JobState.DEAD`.
- **Fencing on both success and failure:** `complete_job()` and `fail_job()` reject zombie
  writes using the exact lease token. The new reaper and atomic final settlement must keep
  that discipline.
- **PII-safe diagnostics:** queue failures already pass through `_build_error_detail` and
  orchestrator boundaries persist/log exception type rather than raw prompt/name content.
- **One shared drain implementation:** workers and `/internal/pump` both call
  `drain_once()`. The final-attempt reaper belongs on this seam, not in a dashboard route or
  a renamed sweep.
- **Immutable audit rows:** dead job history is preserved; Retrigger creates a new job
  generation rather than mutating the exhausted row back to pending.

### Integration Points

- `app/pipeline/orchestrator.py::run_pipeline`, `_run`, and `resume_pipeline` — replace the
  catch-and-return-`None` contract with D-01 through D-03 while preserving PII scrubbing and
  deterministic clarification-as-success behavior.
- `app/routes/pipeline_glue.py::{run_pipeline_now,run_pipeline_bg,resume_pipeline_bg}` —
  propagate/interpret the shared result and implement the temporary D-04 durable retry
  bridge without a private in-memory retry loop.
- `app/queue/handlers/pipeline.py::handle_run_pipeline()` — map `ok`, `retryable`, and
  `terminal` to transport settlement while preserving CAS-only run writes.
- `app/queue/drain.py` and `app/db/repo/jobs.py` — add the shared exhausted-lease outcome,
  D-07 atomic final settlement, D-13 reaping, and D-14 accounting without weakening lease
  fencing.
- `app/routes/pump.py` — add the `reaped_final_lease` response subcount while preserving
  the existing truthful `claimed/done/retried/dead/queue_depth` contract.
- `app/routes/runs.py`, `app/db/repo/runs.py`, `app/db/repo/emails.py`, and
  `app/db/repo/__init__.py` — delete both sweep functions, the runs-list recovery block, and
  facade exports; `GET /runs` must only load/render runs.
- `tests/test_stuck_run_recovery.py`, `tests/test_reply_redelivery.py`,
  `tests/test_needs_operator.py`, and `tests/conftest.py` — remove or rewrite assertions,
  fakes, and patch lists that exist to preserve the deleted sweep behavior.
- `tests/test_queue_drain.py`, `tests/test_queue_durability.py`, and pump route tests — add
  hermetic and live-DB coverage for the result mapping, retry state, atomic settlement,
  final-attempt expired-lease reap, truthful counts, and zombie fencing. Phase 21 still owns
  the milestone-wide red-proof/CI registration work.

</code_context>

<specifics>
## Specific Ideas

- The final-attempt strand predicate is exact and load-bearing:
  `state='leased'`, `attempts == max_attempts`, and `leased_until < now()`.
- A reaped row produces `dead += 1`, `reaped_final_lease += 1`, and no increment to
  `claimed`.
- `FinalAttemptLeaseExpired` is a distinct stable reason; an earlier `last_error` is not
  treated as evidence of what killed the final worker.
- The story of this phase is subtraction: the queue's failure policy makes three old
  recovery hacks deletable, leaving `GET /runs` as a read rather than an accidental cron.

</specifics>

<deferred>
## Deferred Ideas

- **Full durable producer cutover** — migrate all eight `BackgroundTasks` producers and
  durable ingest/reply work in Phase 19. Phase 18 only bridges classified retries.
- **Exactly-once send** — persisted payload replay and Resend idempotency remain Phase 20.
- **Full queue operations view and alarm** — depth, oldest-pending age, attempts
  distribution, dead-letter list, and the swallowing-bug alarm remain OPS-01 / Phase 21.

</deferred>

---

*Phase: 18-Failure Policy & Sweep Deletion*
*Context gathered: 2026-07-15*
