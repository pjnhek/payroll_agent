---
phase: 18-failure-policy-sweep-deletion
plan: 01
subsystem: pipeline
tags: [python, strenum, dataclass, openai, pydantic, failure-policy]

# Dependency graph
requires: []
provides:
  - "Bounded PipelineOutcome, PipelineStage, PipelineReason, and frozen PipelineResult contract"
  - "Stage-aware exception classifier that retries only replay-safe extraction provider failures"
  - "One temporary normalize_pipeline_result adapter for legacy None-returning producers"
affects: [18-03, 18-04, 18-09, 18-10, 18-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "safe-terminal default: missed classifications become terminal/unknown/unclassified"
    - "exception reduction: untrusted provider exceptions become bounded stage/reason codes without retained text"
    - "single compatibility seam: legacy None has one temporary meaning while explicit results pass through unchanged"

key-files:
  created:
    - app/pipeline/result.py
  modified:
    - tests/test_orchestrator_states.py

key-decisions:
  - "Only extraction-stage connection, timeout, rate-limit, and 5xx provider failures are retryable; every unclassified failure and ambiguous clarification/delivery send fails closed as terminal."
  - "Legacy None maps to one coarse OK singleton only through normalize_pipeline_result until the producer cutover; invalid runtime values raise TypeError and explicit results preserve identity."

patterns-established:
  - "Pipeline diagnostics are composed only from bounded stage and reason enum values."
  - "Provider replay safety is contextual to the active stage rather than inferred from exception class alone."

requirements-completed: [FAIL-01]

coverage:
  - id: D1
    description: "A frozen, terminal-safe pipeline result and contextual classifier expose only bounded outcome, stage, reason, and diagnostic values; sensitive exception text is never retained."
    requirement: "FAIL-01"
    verification:
      - kind: unit
        ref: "tests/test_orchestrator_states.py -k 'pipeline_result or classification'"
        status: pass
      - kind: other
        ref: "uv run mypy app/pipeline/result.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "One compatibility adapter maps legacy None to coarse OK, preserves explicit results, rejects invalid values, and leaves both orchestrator producers unchanged."
    requirement: "FAIL-01"
    verification:
      - kind: unit
        ref: "tests/test_orchestrator_states.py -k 'legacy_result'"
        status: pass
      - kind: unit
        ref: "tests/test_orchestrator_states.py::test_legacy_result_source_guard_keeps_orchestrator_producers_unchanged"
        status: pass
    human_judgment: false

duration: 4min
completed: 2026-07-16
status: complete
---

# Phase 18 Plan 01: Bounded Pipeline Result Contract Summary

**A terminal-safe, stage-aware pipeline result now reduces provider failures to bounded PII-safe codes, with one temporary adapter insulating future consumers from the legacy None-returning producers.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-07-16T00:17:54Z
- **Completed:** 2026-07-16T00:21:36Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `PipelineOutcome`, `PipelineStage`, `PipelineReason`, and frozen `PipelineResult`, whose no-argument constructor fails closed as `terminal/unknown/unclassified` and whose diagnostic code is derived only from bounded enum values.
- Added a contextual exception classifier: extraction connection, timeout, rate-limit, and 5xx failures are retryable; exhausted schema/parse failures, ordinary 4xx responses, unknown exceptions, and ambiguous clarification/delivery sends are terminal.
- Added `normalize_pipeline_result` as the only compatibility policy for current None-returning producers, preserving every explicit result by identity and rejecting all other runtime values.
- Proved through an AST source guard that `run_pipeline` and `resume_pipeline` retain their `-> None` annotations and existing `record_run_error` ownership; `app/pipeline/orchestrator.py` was not modified.

## Task Commits

Each TDD task was committed as a RED/GREEN pair:

1. **Task 1 RED: Safe-default contract and classification matrix** - `b756494` (test)
2. **Task 1 GREEN: Bounded pipeline result contract and classifier** - `f0c6ba7` (feat)
3. **Task 2 RED: Legacy compatibility adapter behavior and source guards** - `f8700d3` (test)
4. **Task 2 GREEN: Singular None-to-OK adapter** - `44ce1fd` (feat)

**Plan metadata:** committed as part of this SUMMARY's closeout commit.

## Files Created/Modified

- `app/pipeline/result.py` - Bounded result enums, frozen safe-default dataclass, contextual exception classifier, and temporary compatibility adapter.
- `tests/test_orchestrator_states.py` - Hermetic contract/classifier matrix, PII non-retention proof, adapter matrix, and producer source guard.

## Decisions Made

- Retryability is contextual: the same provider timeout that is safe to retry during extraction is terminal at clarification or delivery because provider acceptance may be ambiguous.
- The compatibility adapter returns a shared coarse OK result for legacy None while preserving explicit result objects exactly, preventing any retryable or terminal outcome from being collapsed.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The first self-check shell loop used `path` as its loop variable; in zsh, `path` is tied to `PATH`, so later commands were not found. The check was immediately rerun with a neutral variable name and all files/commits were found. No repository file was affected.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The contract and compatibility seam are ready for consumer installation in Plans 18-03, 18-04, and 18-09 without changing the current orchestrator producers.
- Plan 18-10 remains the explicit owner for removing legacy None compatibility after every consumer is installed.
- No blockers.

---
*Phase: 18-failure-policy-sweep-deletion*
*Completed: 2026-07-16*

## Self-Check: PASSED

Both key files exist; all four TDD commits are present; 28 focused contract tests and all 35 orchestrator-state tests pass; Ruff, strict mypy for the new module, the comment-provenance guard, and diff hygiene are green.
