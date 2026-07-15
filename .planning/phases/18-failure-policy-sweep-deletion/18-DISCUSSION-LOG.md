# Phase 18: Failure Policy & Sweep Deletion - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-15
**Phase:** 18-Failure Policy & Sweep Deletion
**Areas discussed:** Result contract, Run status during retries, Dead-letter visibility, Exhaustion behavior

---

## Result contract

### Contract coverage

| Option | Description | Selected |
|--------|-------------|----------|
| Both initial runs and clarification resumes | Establish one contract now and prevent Phase 19's resume path from inheriting swallow-and-return behavior. | ✓ |
| Initial `run_pipeline` only | Limit Phase 18 to the currently queued entry point and extend the contract in Phase 19. | |
| Planner discretion | Let research/planning choose while preserving locked behavior. | |

**User's choice:** Both initial runs and clarification resumes.

### Result fields

| Option | Description | Selected |
|--------|-------------|----------|
| Outcome + stage + safe reason | PII-safe diagnostics; queue continues to own scheduling. | ✓ |
| Outcome only | Smallest contract; diagnostics remain entirely separate. | |
| Outcome + stage + retry hint | Allow provider-specific delay but couple pipeline results to queue timing. | |

**User's choice:** Outcome, stage, and a safe reason code.

### Meaning of `ok`

| Option | Description | Selected |
|--------|-------------|----------|
| Keep `ok` coarse | Persisted decision and run status retain all business meaning. | ✓ |
| Add business-action variants | Return `ok_process` versus `ok_clarification`. | |
| Include the full decision | Duplicate business state across the transport boundary. | |

**User's choice:** Keep `ok` coarse.

### Pre-Phase-19 background callers

| Option | Description | Selected |
|--------|-------------|----------|
| Bridge retryable outcomes into the queue | Make automatic retries durable now without keeping a sweep. | ✓ |
| Retry only already-queued calls | Leave background-started paths waiting for Phase 19. | |
| Persist `ERROR`; require Retrigger | Keep recovery manual until Phase 19. | |

**User's choice:** Bridge retryable outcomes into the durable queue.

**Notes:** `request_clarification` remains an `ok` outcome. Raw exception/model/payroll data never crosses the result boundary.

---

## Run status during retries

### Status while waiting

| Option | Description | Selected |
|--------|-------------|----------|
| Return to `received` | Show queued work and reuse the existing forward CAS on the next attempt. | ✓ |
| Leave in-flight status | Avoid a write but falsely imply active work during backoff. | |
| Temporary `error` | Make transient failure visible but conflate retrying with final failure. | |

**User's choice:** Return the run to `received`.

### Final `error` boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Terminal result or exhaustion only | Reserve run error state for final outcomes. | ✓ |
| Every failed attempt | Write and clear error through retry churn. | |
| Explicit terminal only | Leave exhausted jobs attached to non-error runs. | |

**User's choice:** Terminal result or retry exhaustion only.

### Settlement consistency

| Option | Description | Selected |
|--------|-------------|----------|
| One fenced atomic transaction | Job dead and run error commit together or neither commits. | ✓ |
| Job then run | Can leave a dead job attached to a non-error run. | |
| Run then job | Can leave a retryable job attached to a final-error run. | |

**User's choice:** One fenced atomic settlement.

### Transient diagnostics

| Option | Description | Selected |
|--------|-------------|----------|
| Job only | Keep safe failure history in `jobs.last_error`; reserve run error fields for final outcomes. | ✓ |
| Copy onto run | Leave error metadata on a non-error run. | |
| Clear it | Lose attempt history. | |

**User's choice:** Keep transient diagnostics on the job only.

**Notes:** Every run transition from the queue/failure-policy path remains CAS-scoped. `jobs` stays transport-only.

---

## Dead-letter visibility

### Operator surface

| Option | Description | Selected |
|--------|-------------|----------|
| Existing runs list/detail + Retrigger | Meet Phase 18 visibility/actionability without pulling Phase 21 forward. | ✓ |
| Dedicated dead-letter filter | Add a narrow queue UI before the full ops view. | |
| Pump/database only | Minimal code but not reliably actionable by an operator. | |

**User's choice:** Reuse existing runs pages and Retrigger.

### Retrigger behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Preserve dead row; enqueue new generation | Keep immutable audit history and grant a fresh bounded budget. | ✓ |
| Reset dead row to pending | Reuse one row but erase the exhausted-generation boundary. | |
| Reopen with retained attempts | Preserve some history but leave little/no retry budget. | |

**User's choice:** Preserve the dead job and enqueue a new generation.

### Final diagnostic

| Option | Description | Selected |
|--------|-------------|----------|
| Stable reason + stage + attempts | Safe, actionable detail that distinguishes exhaustion modes. | ✓ |
| Generic exhaustion message | Safe but hides normal exhaustion versus lease reaping. | |
| Copy `jobs.last_error` | Richer but couples the run UI to transport diagnostics. | |

**User's choice:** Show stable reason, safe stage, and exhausted attempts.

### UI emphasis

| Option | Description | Selected |
|--------|-------------|----------|
| `error` plus secondary exhaustion label | Preserve the real business status and make exhaustion obvious. | ✓ |
| Detail page only | Leave the runs list unchanged. | |
| Generic existing error UI | Change only the reason text. | |

**User's choice:** Keep `error` and add `Retries exhausted` on list and detail.

**Notes:** No new `RunStatus` or Phase 21 queue dashboard is introduced.

---

## Exhaustion behavior

### Final-attempt lease reaping

| Option | Description | Selected |
|--------|-------------|----------|
| Every shared `drain_once()` path | Workers and pump share one reaper before reporting empty. | ✓ |
| Pump only | Eventual cron cleanup, but workers cannot settle the strand. | |
| Separate maintenance pass | Batch-friendly but creates another recovery path. | |

**User's choice:** Reap through every shared drain path.

### Pump accounting

| Option | Description | Selected |
|--------|-------------|----------|
| `dead` + `reaped_final_lease`, not `claimed` | Truthfully report settlement without pretending execution occurred. | ✓ |
| `dead` only | Preserve response shape but hide the reaping source. | |
| `claimed` + `dead` | Simplify arithmetic but falsely report job execution. | |

**User's choice:** Increment `dead` and `reaped_final_lease`, not `claimed`.

### Reaper reason

| Option | Description | Selected |
|--------|-------------|----------|
| `FinalAttemptLeaseExpired` | Describe the known fact and preserve old errors only as history. | ✓ |
| Reuse previous `last_error` | May misattribute an earlier failure to the final worker death. | |
| Generic exhaustion | Safe but loses the selected distinction. | |

**User's choice:** Use `FinalAttemptLeaseExpired`.

### Explicit terminal result

| Option | Description | Selected |
|--------|-------------|----------|
| Job `done`, run `error` | Transport completed classification; dead remains exhaustion-only. | ✓ |
| Job `dead`, run `error` | Put terminal business failures in the transport dead-letter bucket. | |
| Add a new job state | Preserve a distinction by expanding transport state. | |

**User's choice:** Mark the job `done` and the run `error`.

**Notes:** The exact accepted strand is `leased` + expired + `attempts == max_attempts`; it must become dead through the failure-policy path.

---

## the agent's Discretion

- Concrete typed representation of the result contract.
- SQL/CTE/function decomposition for fenced atomic settlement and reaping.
- Exact styling of the secondary exhaustion label.
- Backoff constants after research validates the existing curve against the recovery bound.

## Deferred Ideas

- Full eight-producer queue cutover and durable ingest/reply dispatch — Phase 19.
- Exactly-once send — Phase 20.
- Full queue operations view and swallowing-bug alarm — Phase 21.

