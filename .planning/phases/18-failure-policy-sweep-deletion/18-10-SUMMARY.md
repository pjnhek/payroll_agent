---
phase: 18-failure-policy-sweep-deletion
plan: 10
subsystem: pipeline
tags: [python, pipeline-result, failure-policy, orchestration, pii-safety]

requires:
  - phase: 18-01
    provides: bounded PipelineResult contract and contextual exception classifier
  - phase: 18-03
    provides: result-aware background consumers and atomic settlement
  - phase: 18-04
    provides: result-aware queue drain and terminal settlement ownership
provides:
  - explicit PipelineResult producers for initial and resume orchestration
  - active-stage classification across load, extraction, compute, persistence, and clarification
  - removal of orchestrator-owned terminal/error persistence
affects: [18-11, 19-webhook-cutover-durable-ingest]

tech-stack:
  added: []
  patterns:
    - mutable bounded stage tracker shared with one outer producer catch boundary
    - producer returns policy values while background and queue consumers own persistence

key-files:
  created: []
  modified:
    - app/pipeline/orchestrator.py
    - tests/test_orchestrator_states.py
    - tests/test_resume_pipeline.py

key-decisions:
  - "Both orchestrator entry points return one shared coarse OK result on completed and lost-claim paths; business action remains authoritative in run state."
  - "A mutable bounded stage tracker crosses the shared _run_stages seam so the outer catch boundary classifies failures without retaining exception content."

patterns-established:
  - "Producer/consumer ownership: orchestrators classify and return; wrappers and drain settle terminal state exactly once."

requirements-completed: [FAIL-01, FAIL-02]

coverage:
  - id: D1
    description: "Initial and resume orchestrators return bounded explicit results on every success, lost-claim, retryable, and terminal path."
    requirement: FAIL-01
    verification:
      - kind: unit
        ref: "tests/test_orchestrator_states.py tests/test_resume_pipeline.py -k 'result or classification or clarification or claim'"
        status: pass
      - kind: integration
        ref: "DATABASE_URL=postgresql://mock-test-stub/mockdb pytest tests/test_orchestrator_states.py tests/test_resume_pipeline.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Neither producer persists terminal/error state; stage and reason diagnostics remain bounded and exclude hostile exception content."
    requirement: FAIL-02
    verification:
      - kind: unit
        ref: "tests/test_orchestrator_states.py#test_pipeline_result_source_guard_requires_explicit_producers_without_error_persistence"
        status: pass
      - kind: other
        ref: "uv run mypy app/pipeline/orchestrator.py"
        status: pass
    human_judgment: false

duration: 9min
completed: 2026-07-16
status: complete
---

# Phase 18 Plan 10: Explicit Orchestrator Producer Cutover Summary

**Initial and resume orchestration now return stage-aware bounded outcomes on every path, leaving terminal persistence solely to the already-installed background and queue consumers.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-16T03:07:26Z
- **Completed:** 2026-07-16T03:16:24Z
- **Tasks:** 1 TDD task
- **Files modified:** 3

## Accomplishments

- Cut `run_pipeline`, `_run`, and `resume_pipeline` over from implicit `None` to explicit `PipelineResult` returns for success, clarification, lost claims, retryable failures, and terminal failures.
- Classified failures at the active bounded load, extract, compute, persist, or clarification stage without retaining exception text or persisting `payroll_runs.error_reason`.
- Removed both orchestrator-owned `record_run_error` calls so background wrappers and the durable drain remain the single persistence owner for their execution modes.
- Preserved exactly-one clarification attempts and all existing deterministic decision, transaction, alias-learning, and resume semantics.

## Task Commits

1. **Task 1 RED: Explicit producer result and non-persistence proofs** - `757a8e4` (test)
2. **Task 1 GREEN: Stage-aware explicit orchestrator producers** - `33b2ef2` (feat)

## Files Created/Modified

- `app/pipeline/orchestrator.py` - Explicit result annotations/returns, bounded stage tracking, classification-only catch boundaries, and no terminal persistence.
- `tests/test_orchestrator_states.py` - Initial producer success/failure matrices, stage accuracy, PII non-retention, and AST source contract.
- `tests/test_resume_pipeline.py` - Resume success and retryable extraction parity proofs.

## Decisions Made

- Kept OK coarse and shared because process versus clarification remains a business-state decision, not a transport outcome.
- Passed a small mutable stage tracker into `_run_stages` rather than moving its catch boundary or duplicating stage logic, preserving the shared deterministic spine while making classification accurate.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The phase-wide full-suite run stopped at a pre-existing comment-provenance violation in `tests/test_pump_route.py:65`, introduced by Plan 18-05 (`D-14` in a docstring). Plan 18-10 did not modify that file. The issue is recorded in `deferred-items.md` for post-wave orchestrator handling.
- Plan 18-10's complete focused suite passed with the resume module enabled: 64 passed. Its exact filtered command passed 33 tests with 4 environment-skipped tests when `DATABASE_URL` was absent.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Ready for Plan 18-11 to remove the sole temporary `None` compatibility branch and narrow consumer annotations.
- The unrelated Plan 18-05 provenance violation must be corrected before the phase-wide full-suite gate can pass.

## Self-Check: PASSED

- All three modified code/test files exist.
- Both RED/GREEN task commits are present.
- Focused full suite: 64 passed.
- Exact plan filter: 33 passed, 4 skipped without the optional test environment marker.
- Ruff and strict mypy passed.
- No new dependency, endpoint, authentication path, file-access pattern, schema object, or untracked stub was introduced.

---
*Phase: 18-failure-policy-sweep-deletion*
*Completed: 2026-07-16*
