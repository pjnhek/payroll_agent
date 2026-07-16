---
phase: 18-failure-policy-sweep-deletion
plan: 07
subsystem: routes
tags: [fastapi, durable-queue, ast-guard, recovery, security]

requires:
  - phase: 18-04
    provides: result-aware queue drain and atomic settlement ownership
  - phase: 18-06
    provides: bounded failure diagnostics on the existing run surfaces
  - phase: 18-11
    provides: strict PipelineResult forwarding across durable consumers
provides:
  - side-effect-free GET /runs with no mutation, enqueue, reply consumption, or scheduling
  - route AST and hostile-spy guards that prevent page-load recovery from returning
  - supported webhook, durable reply/operator resume, needs-operator, epoch, and Retrigger coverage
affects: [18-08, 19-webhook-cutover-durable-ingest]

tech-stack:
  added: []
  patterns:
    - unauthenticated read routes are structurally restricted to projection and rendering
    - automatic recovery is queue-owned while operator recovery stays behind explicit mutation routes

key-files:
  created:
    - .planning/phases/18-failure-policy-sweep-deletion/18-07-SUMMARY.md
  modified:
    - app/routes/runs.py
    - app/routes/pipeline_glue.py
    - tests/test_stuck_run_recovery.py
    - tests/test_reply_redelivery.py
    - tests/test_needs_operator.py
    - tests/test_retrigger_epoch.py

key-decisions:
  - "GET /runs accepts only Request and performs list projection, safe presentation, and template rendering; it owns no automatic recovery behavior."
  - "Webhook redelivery and durable RESUME_REPLY/OPERATOR_RESUME handlers remain the supported automatic resume entry points, while Retrigger remains the explicit operator recovery action."

patterns-established:
  - "Read-only route guard: exact AST call inventory plus spies that raise at mutation, enqueue, reply-consumption, and scheduling seams."
  - "Caller-first deletion: remove route/test callers while legacy repository definitions remain available for the immediately following API-deletion plan."

requirements-completed: [FAIL-03]

coverage:
  - id: D1
    description: "GET /runs is a read-only projection with no BackgroundTasks parameter or automatic recovery side effects."
    requirement: FAIL-03
    verification:
      - kind: integration
        ref: "tests/test_stuck_run_recovery.py#read-only AST and hostile-spy route proofs"
        status: pass
      - kind: other
        ref: "uv run --offline mypy app/routes/runs.py app/routes/pipeline_glue.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Supported webhook, durable resume, needs-operator, epoch isolation, and manual Retrigger safeguards remain covered after caller subtraction."
    requirement: FAIL-03
    verification:
      - kind: integration
        ref: "tests/test_reply_redelivery.py tests/test_needs_operator.py tests/test_retrigger_epoch.py tests/test_hitl.py"
        status: pass
      - kind: other
        ref: "uv run --offline pytest -q"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-07-16
status: complete
---

# Phase 18 Plan 07: Read-Only Runs List and Recovery Caller Subtraction Summary

**The operator run list is now a pure read-and-render view, with automatic recovery confined to durable queue entry points and explicit regression guards preventing page-load mutation from returning.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-16T04:06:49Z
- **Completed:** 2026-07-16T04:18:41Z
- **Tasks:** 2 TDD tasks
- **Files modified:** 6

## Accomplishments

- Removed the complete list-page age sweep, stranded-reply scan, sender replay branch, and background scheduling block while preserving safe list projection and rendering.
- Replaced sweep implementation tests with an exact route AST inventory and a successful request whose mutation, reply-consumption, enqueue, and scheduling seams all raise if touched.
- Deleted page-view recovery expectations while retaining direct coverage for webhook redelivery, spoof rejection, consumed/non-awaiting replies, durable reply/operator handlers, needs-operator behavior, epoch isolation, and manual Retrigger.

## Task Commits

1. **Task 1 RED: Failing read-only route guard** - `e887053` (test)
2. **Task 1 GREEN: Side-effect-free runs list** - `344964a` (feat)
3. **Task 2 RED: Failing supported recovery inventory** - `5c99a4f` (test)
4. **Task 2 GREEN: Supported recovery-path preservation** - `b0b9913` (test)

## Files Created/Modified

- `app/routes/runs.py` - Removes every legacy recovery caller from GET /runs and documents the operator-only stale Retrigger threshold.
- `app/routes/pipeline_glue.py` - Names webhook duplicate redelivery and the durable RESUME_REPLY handler as the persisted-row conversion callers.
- `tests/test_stuck_run_recovery.py` - Pins the read-only route signature, exact call inventory, absent legacy callers, and untouched side-effect seams.
- `tests/test_reply_redelivery.py` - Retains supported webhook redelivery and spoofed-sender rejection while rejecting list-page recovery expectations.
- `tests/test_needs_operator.py` - Keeps human-gate, durable operator-resume, and list rendering coverage without a sweep patch.
- `tests/test_retrigger_epoch.py` - Keeps current-epoch outbound/consumed-reply behavior without retired lookup prose.

## Decisions Made

- Kept the legacy repository APIs callable for this intermediate wave so the caller-removal commit stays green and Plan 18-08 can delete definitions, facade exports, and fakes atomically.
- Made the route guard intentionally non-vacuous: it proves the exact FastAPI signature and call set, then drives a real 200 response with every forbidden side-effect seam patched to raise.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The first AST expectation omitted the FastAPI decorator and existing debug-log call from its exact call inventory. The test was corrected during GREEN to include both harmless calls while retaining the strict read-only set.
- The provenance checkpoint's reported `D-14:` label was already absent from the committed checkout when this plan resumed. The dedicated provenance guard passed without an additional edit.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Every route and test caller of the legacy sweep APIs is removed; Plan 18-08 can now delete their repository definitions, facade exports, and fake implementations.
- Full hermetic suite, focused recovery suite, provenance guard, Ruff, and mypy are green. No blockers remain.

## Self-Check: PASSED

- All six modified implementation/test files exist and all four task commits are present.
- Focused plan suite: 79 passed, 2 environment-gated skips.
- Full hermetic suite: 851 passed, 81 environment-gated skips.
- Comment provenance guard: 5 passed.
- Ruff passed on both source files and all changed tests; mypy passed on both source files; `git diff --check` passed.
- No dependency, schema, endpoint, authentication, file-access, unsafe diagnostic, or stub surface was introduced.

---
*Phase: 18-failure-policy-sweep-deletion*
*Completed: 2026-07-16*
