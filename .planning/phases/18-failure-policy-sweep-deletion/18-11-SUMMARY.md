---
phase: 18-failure-policy-sweep-deletion
plan: 11
subsystem: pipeline
tags: [python, pipeline-result, queue, ast-guard, mypy]

requires:
  - phase: 18-10
    provides: explicit PipelineResult producers for initial and resumed orchestration
  - phase: 18-04
    provides: result-aware queue drain and atomic settlement ownership
provides:
  - PipelineResult-only wrappers, handlers, dispatcher, and strict runtime adapter
  - non-vacuous AST inventory for every active result producer and consumer seam
  - repo-wide strict-mypy closure for the explicit result call graph
affects: [18-07, 18-08, 19-webhook-cutover-durable-ingest]

tech-stack:
  added: []
  patterns:
    - exact typed result forwarding with runtime validation at dynamic seams
    - positive AST inventories paired with hostile mutation cases

key-files:
  created:
    - .planning/phases/18-failure-policy-sweep-deletion/18-11-SUMMARY.md
  modified:
    - app/pipeline/result.py
    - app/routes/pipeline_glue.py
    - app/queue/handlers/pipeline.py
    - app/queue/handlers/resume_reply.py
    - app/queue/handlers/operator_resume.py
    - app/queue/dispatch.py
    - tests/test_queue_drain.py
    - tests/test_resume_pipeline.py
    - tests/test_needs_operator.py

key-decisions:
  - "Dynamic forwarding boundaries validate PipelineResult at runtime even though static annotations are exact, so an unsound handler or test double fails loudly instead of becoming success."
  - "Background wrappers remain None-returning terminal procedures, while every value-producing now seam and queue handler is PipelineResult-only."

patterns-established:
  - "Exact result graph: producers classify, forwarders preserve identity, and consumers exhaustively settle OK, RETRYABLE, or TERMINAL."
  - "Guard anti-vacuity: inventory the expected function set and prove representative optional, discarded, and truthiness mutations are rejected."

requirements-completed: [FAIL-01, FAIL-02]

coverage:
  - id: D1
    description: "Every active producer, wrapper, handler, and dispatcher seam forwards PipelineResult only; None fails loudly at dynamic boundaries."
    requirement: FAIL-01
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py tests/test_resume_pipeline.py tests/test_needs_operator.py -k 'result or caller or background or resume or operator'"
        status: pass
      - kind: integration
        ref: "uv run --offline pytest -q"
        status: pass
    human_judgment: false
  - id: D2
    description: "The active result call graph has a positive AST inventory with no optional annotations, discarded calls, None-success branches, or truthiness shortcuts."
    requirement: FAIL-02
    verification:
      - kind: unit
        ref: "tests/test_queue_drain.py#test_pipeline_result_call_graph_is_exact_non_vacuous_and_has_no_sinks"
        status: pass
      - kind: unit
        ref: "tests/test_queue_drain.py#test_pipeline_result_call_graph_guard_rejects_optional_discarded_and_truthy_results"
        status: pass
      - kind: other
        ref: "uv run --offline mypy"
        status: pass
    human_judgment: false

duration: 21min
completed: 2026-07-16
status: complete
---

# Phase 18 Plan 11: Strict Pipeline Result Call Graph Summary

**The initial, reply-resume, and operator-resume execution graph now carries one exact bounded result contract from producer through dynamic dispatch to atomic settlement, with no compatibility-era `None` success path.**

## Performance

- **Duration:** 21 min
- **Started:** 2026-07-16T03:38:21Z
- **Completed:** 2026-07-16T03:59:40Z
- **Tasks:** 2 TDD tasks
- **Files modified:** 15

## Accomplishments

- Removed the last `PipelineResult | None` normalizer, wrapper, handler, and dispatcher signatures; runtime validation now rejects unsound values while preserving explicit result identity.
- Preserved CAS-loser OK results, bounded invalid-context terminal results, persisted reply reconstruction, immutable operator-resolution identifiers, retry scheduling, and one settlement owner per execution mode.
- Added a positive 13-function producer/consumer inventory that fails on missing seams, optional returns, discarded calls, bare `None`, or result truthiness shortcuts, plus hostile anti-vacuity cases proving the guard can fail.
- Closed strict mypy over all 146 source files and passed the full hermetic regression suite with 860 passed and 83 environment-gated skips.

## Task Commits

1. **Task 1 RED: Strict result seam falsifying proofs** - `4a130bf` (test)
2. **Task 1 GREEN: Explicit result forwarding** - `c1ea21c` (feat)
3. **Task 2: Non-vacuous call-graph and strict-type proof** - `8355878` (test)
4. **Rule 1 regression repair: Remaining explicit-result test doubles** - `5415bf9` (fix)

## Files Created/Modified

- `app/pipeline/result.py` - Strict `PipelineResult` runtime validator with no legacy `None` conversion.
- `app/routes/pipeline_glue.py` - Exact now seams and exhaustive background result consumption.
- `app/queue/handlers/pipeline.py` - Explicit OK for lost CAS and strict forwarding for winning claims.
- `app/queue/handlers/resume_reply.py` - Exact persisted-email reconstruction and strict resume result forwarding.
- `app/queue/handlers/operator_resume.py` - Exact immutable-resolution reconstruction and strict resume result forwarding.
- `app/queue/dispatch.py` - Runtime-validated dynamic handler forwarding.
- `tests/test_queue_drain.py` - Behavioral matrices, positive call-graph inventory, and hostile guard cases.
- `tests/test_resume_pipeline.py`, `tests/test_needs_operator.py` - Reply and operator forwarding/identifier/context proofs.
- `tests/conftest.py`, `tests/test_queue_durability.py`, `tests/test_hitl.py`, `tests/test_orchestrator_states.py` - Minimal strict-type narrowing needed for the required repo-wide mypy gate.
- `tests/test_alias_and_run_column_regressions.py`, `tests/test_stuck_run_recovery.py` - Remaining retrigger test doubles updated to explicit OK results.

## Decisions Made

- Kept runtime validation at each dynamic or injection-sensitive forwarding boundary. Static typing protects checked application code, while the validator makes monkeypatches, plugin-style dispatch, and other unsound runtime values fail loudly.
- Kept background functions as `-> None` procedures because they fully consume and settle a result; only result-producing seams were narrowed to `PipelineResult`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Closed repo-wide strict-mypy errors outside the nine primary owned files**
- **Found during:** Task 2 (repo-wide strict typing gate)
- **Issue:** Earlier Phase 18 test additions left untyped fake calls, optional repository rows, and private-module attribute access that blocked the plan-mandated `uv run mypy` proof.
- **Fix:** Added explicit fake method types, narrowed optional live-proof rows after assertions, and imported public module objects for monkeypatch seams.
- **Files modified:** `tests/conftest.py`, `tests/test_queue_durability.py`, `tests/test_hitl.py`, `tests/test_orchestrator_states.py`
- **Verification:** `uv run --offline mypy` reports no issues in 146 source files.
- **Committed in:** `8355878`

**2. [Rule 1 - Bug] Updated remaining compatibility-era success doubles discovered by the full suite**
- **Found during:** Plan-level full regression verification
- **Issue:** Retrigger and lease-lifecycle tests still returned `None` from mocked result producers, and one terminal-stage test still modeled error persistence as producer-owned. Under the exact contract these correctly failed or fenced.
- **Fix:** Returned explicit OK results from those doubles and moved the terminal test's error expectation to the drain coordinator.
- **Files modified:** `tests/test_alias_and_run_column_regressions.py`, `tests/test_queue_drain.py`, `tests/test_stuck_run_recovery.py`
- **Verification:** Six-test regression slice passed; full suite passed 860 tests with 83 skips.
- **Committed in:** `5415bf9`

---

**Total deviations:** 2 auto-fixed (1 blocking type-closure issue, 1 compatibility regression). **Impact:** Both were required to make the plan's repo-wide typing and full regression evidence truthful; no production scope or architecture was broadened.

## Issues Encountered

- `rg` is unavailable in this checkout, so source searches used `grep`/`find` as the documented fallback.
- `tests/test_resume_pipeline.py` remains environment-gated without `DATABASE_URL`; the exact focused command reported 38 passed, 27 skipped, and 30 deselected. The same behaviors are covered unconditionally in `tests/test_needs_operator.py`, `tests/test_queue_drain.py`, and the full hermetic suite.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 18-07 can now consume an exact result graph with no compatibility semantics.
- Plan 18-08 can perform final sweep deletion and phase closure after Plans 18-07 and 18-11.
- No blockers remain from this plan.

## Self-Check: PASSED

- All strict result source and proof files exist.
- All four Plan 18-11 commits are present.
- Focused result/caller suite: 38 passed, 27 skipped, 30 deselected.
- Full hermetic suite: 860 passed, 83 skipped.
- Ruff passed on all nine primary owned files; strict mypy passed across 146 source files; `git diff --check` passed.
- No dependency, endpoint, authentication path, file-access pattern, schema object, unsafe diagnostic surface, or untracked stub was introduced.

---
*Phase: 18-failure-policy-sweep-deletion*
*Completed: 2026-07-16*
