---
phase: 18-failure-policy-sweep-deletion
verified: 2026-07-16T16:47:02Z
status: passed
score: 9/9 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 7/9
  gaps_closed:
    - "CR-01: final-attempt lease settlement is exhaustive, atomic, and starvation-free for every RunStatus"
    - "CR-02: persisted reply ownership is proven against job.run_id before conversion, reclaim, or orchestration"
    - "WR-01: resume-handler regressions run hermetically and require explicit PipelineOutcome.OK"
  gaps_remaining: []
  regressions: []
---

# Phase 18: Failure Policy & Sweep Deletion Verification Report

**Phase Goal:** A pipeline failure is classified honestly — ok, retryable, or terminal — instead of being swallowed into a silent success, and the queue's own lease-based recovery becomes the sole recovery mechanism.
**Verified:** 2026-07-16T16:47:02Z
**Status:** passed
**Re-verification:** Yes — after gap-closure Plans 18-13 and 18-14

## Verdict

Phase 18 achieves its goal. All nine observable must-haves are verified in current source and exercised by always-run behavioral tests. The three prior findings are closed:

- **CR-01 closed:** every exact expired final-attempt lease with a valid associated `RunStatus` is dead-lettered in one run-locked transaction. Active crash states become bounded `ERROR`; completed, human-wait, rejected, and existing-error states remain authoritative. A preserved oldest row no longer strands itself or starves the next candidate.
- **CR-02 closed:** `RESUME_REPLY` canonicalizes the persisted email row's non-null `run_id` and requires equality with `job.run_id` before `row_to_inbound`, reclaim, or orchestration. Null, malformed, same-business wrong-run, and cross-business context fail terminally with a bounded identifier-free diagnostic.
- **WR-01 closed:** `tests/test_resume_pipeline.py` has no module-wide database skip, passes with `DATABASE_URL` absent and with a harmless stub, and asserts explicit `PipelineOutcome.OK` on reclaim.

The reset-enabled live Postgres environment was unavailable because `DATABASE_URL` and `ALLOW_DB_RESET=1` were absent. Seventeen selected queueproof cases collected and skipped under that guard. Those skips are not counted as passing evidence. This does not leave a behavior-unverified truth: the same state transitions, ordering invariants, context rejection, and starvation behavior are exercised by always-run stateful tests, while the guarded tests remain additional database-engine evidence.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Initial and resume orchestration share one bounded, terminal-safe, PII-safe `PipelineResult`, and no active value-producing seam accepts `None` as success. | ✓ VERIFIED | `app/pipeline/result.py:16-62,121-131`; `app/pipeline/orchestrator.py:209-253`; strict call-graph test passed; focused Ruff/mypy passed. |
| 2 | Replay-safe extraction provider failures become durable delayed retries with bounded diagnostics and no in-memory retry loop. | ✓ VERIFIED | Classifier at `app/pipeline/result.py:65-118`; background bridge at `app/routes/pipeline_glue.py:225-250`; queued settlement at `app/db/repo/job_settlement.py:295-373`; representative retry bridge test passed. |
| 3 | A completed deterministic `request_clarification` action is an OK pipeline outcome and is not retried as a failure. | ✓ VERIFIED | Clarification is the deterministic branch at `app/pipeline/orchestrator.py:1028-1056`; `_run` returns coarse OK at lines 235-243; clarification behavior tests passed. |
| 4 | Durable reply and operator-resume jobs reconstruct complete context and prove it belongs to the claimed run before replay. | ✓ VERIFIED | Reply ownership is checked before conversion at `app/queue/handlers/resume_reply.py:36-64`; operator mapping remains run-scoped and roster-validated; always-run wrong-run/cross-business tests passed. |
| 5 | Retry exhaustion and final-attempt lease expiry always settle without a permanent leased row or starvation. | ✓ VERIFIED | Exhaustive status sets and run lock at `app/db/repo/job_settlement.py:37-59,113-120`; reap transaction at lines 419-457; all-status and second-candidate tests at `tests/test_queue_drain.py:729-824` passed. |
| 6 | Settled exhaustion is visible as canonical Error with bounded context, and Retrigger creates a fresh job generation without reopening dead history. | ✓ VERIFIED | Browser allowlist at `app/routes/runs.py:81-190`; retrigger immutability and safe presentation tests passed. |
| 7 | Pump accounting reports a final-lease reap as dead maintenance outside claimed work. | ✓ VERIFIED | `app/routes/pump.py:87-120`; pump accounting tests passed. |
| 8 | The two legacy sweep APIs and their route/facade/fake surfaces are absent; no fallback sweep remains. | ✓ VERIFIED | Production Python/HTML/SQL negative scan returned zero matches; source/fake pairing test passed. |
| 9 | `GET /runs` is a side-effect-free read and render route. | ✓ VERIFIED | `app/routes/runs.py:637-660`; AST read-only guard and hostile side-effect-spy coverage passed. |

**Score:** 9/9 truths verified (0 present-but-behavior-unverified).

### ROADMAP Success Criteria

| # | Success criterion | Status | Evidence |
|---|---|---|---|
| 1 | A transient extraction provider timeout is retried with backoff instead of becoming an unretried ERROR. | ✓ VERIFIED | Stage-aware classification returns RETRYABLE; background and queued consumers persist delayed retry work; focused retry-path tests passed. |
| 2 | `request_clarification` is not treated as failed work or duplicated by failure-policy retry. | ✓ VERIFIED | Deterministic clarification completes with coarse OK; clarification-path tests preserve a single send attempt. |
| 3 | Attempt-cap exhaustion becomes visible dead-letter work an operator can act on. | ✓ VERIFIED | Normal exhaustion and every valid expired final-attempt lease settle transport terminally; safe Error/Retry exhausted presentation and Retrigger remain wired. |
| 4 | Both legacy sweep APIs and the runs-list sweep block are removed. | ✓ VERIFIED | Application-source negative scan, AST/facade/fake inventories, and replacement pairing pass. |
| 5 | Viewing the run list has no state-transition side effect. | ✓ VERIFIED | The route only loads, reduces, and renders data; structural and behavioral read-only guards pass. |

## Prior Gap Re-adjudication

### CR-01 — Final-attempt lease settlement

**Status:** CLOSED

`reap_expired_final_attempt()` keeps the exact predicate (`leased`, `attempts = max_attempts`, expired lease), locks the oldest candidate with `FOR UPDATE SKIP LOCKED`, locks its associated run, and dispatches every canonical `RunStatus` through disjoint exhaustive sets. `RECEIVED`, `EXTRACTING`, `COMPUTED`, and `APPROVED` become bounded `ERROR`; `SENT`, `AWAITING_REPLY`, `AWAITING_APPROVAL`, `NEEDS_OPERATOR`, `RECONCILED`, `REJECTED`, and `ERROR` remain unchanged. Every valid branch then changes the job to `dead`, clears both lease fields, preserves `last_error`, and returns `REAPED_FINAL_LEASE`.

Always-run evidence covers all statuses, vocabulary drift, history preservation, and oldest-preserved-then-active progress. Guarded Postgres tests contain the corresponding status matrix, row-ordering, exact-predicate, and rollback counterexamples, but were unavailable to execute under the two-factor database guard.

### CR-02 — Persisted reply ownership

**Status:** CLOSED

`handle_resume_reply()` loads the exact inbound row, canonicalizes `row["run_id"]`, and requires equality with the already-required `job.run_id` before calling `row_to_inbound`, `rewind_for_reclaim`, or `resume_pipeline`. Missing, null, malformed, same-business wrong-run, and cross-business rows return `terminal/load/invalid_operator_override_context`. `_invalid_context()` logs only a static event and bounded reason code.

Always-run tests use fail-if-called spies to prove invalid context cannot reach conversion or orchestration and inject UUIDs, addresses, subject, body, business IDs, and names to prove none reach logs. A positive same-run case proves the handler was not disabled.

### WR-01 — Hermetic resume regression evidence

**Status:** CLOSED

The module documents and enforces fake-repository isolation, has no module-level `DATABASE_URL` skip, and the reclaimed handler path asserts `result.outcome is PipelineOutcome.OK`. Independent verifier runs produced 31 passed with `DATABASE_URL` absent and 31 passed with a harmless stub.

## Required Artifacts

The GSD artifact verifier reports all plan-declared artifacts valid across Plans 18-01 through 18-14. The load-bearing artifacts were inspected for existence, substance, wiring, and behavioral coverage.

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `app/pipeline/result.py` | Bounded shared result and contextual classifier | ✓ VERIFIED | Safe terminal defaults, bounded enums, extraction-only replay-safe retry classification, strict runtime validation. |
| `app/pipeline/orchestrator.py` | Explicit producers without terminal persistence | ✓ VERIFIED | Initial/resume entry points return `PipelineResult`; catch boundaries classify and return. |
| `app/models/job.py` and `app/db/schema.sql` | Identifier-only durable context | ✓ VERIFIED | Three exact kinds and typed run/email/operator-resolution identifiers; no generic payload. |
| `app/db/repo/operator_resume_resolutions.py` | Immutable complete operator authority | ✓ VERIFIED | Strict create/load seams and typed normalized rows are used by route, handler, and coordinator. |
| `app/queue/handlers/resume_reply.py` | Exact same-run persisted reply reconstruction | ✓ VERIFIED | Canonical owner check precedes content conversion, reclaim, and orchestration. |
| `app/queue/handlers/operator_resume.py` | Complete run-scoped operator mapping validation | ✓ VERIFIED | Exact unresolved-name set and roster membership are checked before replay. |
| `app/db/repo/job_settlement.py` | Atomic retry, terminal, exhaustion, and final-lease settlement | ✓ VERIFIED | Run/job writes are fenced; final-lease status matrix is exhaustive and starvation-free. |
| `app/queue/drain.py` | Shared claim, settlement, and reap-before-empty path | ✓ VERIFIED | Normal claims precede one reap; every successful reap is truthy; EMPTY remains the sole falsy result. |
| `app/routes/pump.py` | Honest bounded pump accounting | ✓ VERIFIED | Reap increments dead/reaped counters, not claimed; maintenance still consumes the drain bound. |
| `app/routes/runs.py` and templates | Safe visibility, immutable Retrigger, read-only list | ✓ VERIFIED | Strict browser projection, canonical Error, fresh recovery generation, side-effect-free list GET. |
| `app/db/schema_introspect.py` | Live schema expectation for typed resolution storage | ✓ VERIFIED | Tables, linkage column, named indexes, and constraints are explicitly inventoried. |

## Key Link Verification

GSD key-link checks passed for every syntactically valid plan declaration, including both new gap-closure plans. Plans 18-10 and 18-11 use compound path notation that the query parser rejects as a file path; those links were verified manually.

| From | To | Status | Details |
|---|---|---|---|
| Orchestrator catch boundaries | `app/pipeline/result.py` | ✓ WIRED | Active bounded stage reaches the classifier; all control paths return a bounded result. |
| Background wrappers | classified retry coordinators | ✓ WIRED | RETRYABLE selects identifier-only durable enqueue; wake occurs only after durable settlement. |
| Queue handlers and dispatch | shared drain settlement | ✓ WIRED | Results are runtime-validated, forwarded, and atomically settled. |
| Reply handler | persisted email repository and orchestrator | ✓ WIRED | Exact row loads by `email_id`; canonical row owner must equal job owner before replay. |
| Operator handler | immutable resolution and roster | ✓ WIRED | Resolution run scope, complete keys, and employee membership are validated. |
| Drain empty path | final-attempt reaper | ✓ WIRED | One exact candidate is settled before EMPTY, with a truthy result for every valid run status. |
| Pump | shared drain | ✓ WIRED | Reap outcome is counted as dead maintenance outside claimed work. |
| Run list | read-side projection and templates | ✓ WIRED | No mutation, enqueue, reply consumption, or scheduling call exists. |
| Repository facade | durable replacement seams | ✓ WIRED | Persisted email, operator-resolution, retry, settlement, and reaper APIs remain public and fake-paired. |

## Data-Flow Trace

| Surface | Source | Boundary reduction | Status |
|---|---|---|---|
| Run failure context | Persisted run reason/detail plus bounded attempt projection | Full grammar match and fixed allowlists before HTML or JSON | ✓ VERIFIED |
| Pump counters | `drain_once()` outcome | Reaped maintenance increments dead/reaped while claimed remains unchanged | ✓ VERIFIED |
| Reply retry context | `jobs.email_id` → inbound row → `InboundEmail` | Canonical row owner equality before body conversion or replay | ✓ VERIFIED |
| Operator retry context | `jobs.operator_resolution_id` → typed rows and run roster | Exact keys and employee membership before resume | ✓ VERIFIED |

## Behavioral Spot-Checks

| Behavior | Command/result | Status |
|---|---|---|
| Final-lease status matrix, starvation, read-only/deletion/result-contract selection | Focused verifier run: 62 passed | ✓ PASS |
| Resume ownership and strict explicit-result contract without `DATABASE_URL` | `tests/test_resume_pipeline.py`: 31 passed | ✓ PASS |
| Same module with harmless stub `DATABASE_URL` | `tests/test_resume_pipeline.py`: 31 passed | ✓ PASS |
| Retry classification/bridge, clarification, bounded dashboard, read-only route, retired symbols, immutable Retrigger | Nine named representative tests: 9 passed | ✓ PASS |
| Full current checkout with database variables absent | `uv run --offline --no-sync pytest -q`: 899 passed, 69 skipped, one dependency deprecation warning | ✓ PASS for executed tests |
| Guarded final-lease, pump-reap, and reply-association queueproofs | 17 selected, 17 skipped because `DATABASE_URL` or `ALLOW_DB_RESET=1` was absent | UNAVAILABLE — not counted as pass |
| Focused source quality | Ruff passed; mypy passed for eight load-bearing production files | ✓ PASS |

## Probe Execution

No Phase 18 plan declares a standalone probe script. Verification uses pytest, Ruff, mypy, source inventories, and guarded queueproofs.

## Requirements Coverage

| Requirement | Source plans | Status | Evidence |
|---|---|---|---|
| FAIL-01 | 18-01, 18-02, 18-04, 18-09, 18-10, 18-11, 18-14 | ✓ SATISFIED | Explicit safe-default result, contextual retry classification, clarification OK, and no active `None`-as-success seam. |
| FAIL-02 | 18-02, 18-03, 18-04, 18-05, 18-06, 18-09, 18-10, 18-11, 18-12, 18-13, 18-14 | ✓ SATISFIED | Durable reconstructable retries, atomic terminal/exhaustion settlement, status-aware final-lease cleanup, bounded visibility, and safe run-bound reply replay. |
| FAIL-03 | 18-07, 18-08 | ✓ SATISFIED | Retired definitions, exports, callers, fakes, and page-load recovery are absent; `GET /runs` is side-effect free. |

No Phase 18 requirement is orphaned: all three are declared in plan frontmatter and mapped in `REQUIREMENTS.md`.

## Anti-Patterns Found

No `TBD`, `FIXME`, `XXX`, `TODO`, `HACK`, placeholder implementation, generic job payload, retired sweep symbol, or active `PipelineResult | None` seam was found in phase-owned production files. The only `PipelineResult | None` match is an intentional hostile mutation string inside the call-graph guard.

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| `app/routes/pipeline_glue.py` | 253-301 | Docstrings still describe pre-cutover producer-owned ERROR persistence and `fail_job` behavior | INFO | Runtime wiring is correct; narrative is stale after Plans 18-10/18-11. |
| `app/queue/dispatch.py` | 13-17 | Module docstring says the table has one handler although all three are registered | INFO | Set-equality and runtime dispatch are correct; documentation is stale. |

## Human Verification Required

None. Every behavior-dependent must-have has passing automated behavioral coverage. The unavailable live Postgres run is external execution evidence, not a manual UX or judgment check and not a source-observable defect.

## Gaps Summary

No gaps remain. CR-01, CR-02, and WR-01 are closed in actual source and always-run tests. Later phases may add stronger CI/live-database falsification, send idempotency, and operations visibility, but none is required to make the Phase 18 goal true.

---

_Verified: 2026-07-16T16:47:02Z_
_Verifier: the agent (gsd-verifier, generic-agent workaround)_
