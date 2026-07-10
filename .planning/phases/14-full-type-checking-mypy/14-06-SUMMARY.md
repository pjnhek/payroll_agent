---
phase: 14-full-type-checking-mypy
plan: 06
subsystem: testing
tags: [mypy, pytest, type-checking, test-fixtures]

# Dependency graph
requires:
  - phase: 14-full-type-checking-mypy
    provides: relaxed tests.* mypy override with check_untyped_defs enabled
provides:
  - Zero mypy errors across this plan's 20 test files
  - Typed shared fixtures, mocks, optional-row boundaries, and test helpers
  - Dynamic before/after hermetic-suite and assertion-diff proof for TYPE-02
affects: [14-07, 14-08, 14-09, 14-10, full-test-type-checking]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Type dynamic test doubles at their fixture boundary with dict[str, Any] and typed collections
    - Add only behavior-preserving None narrowing where mypy requires a runtime proof

key-files:
  created:
    - .planning/phases/14-full-type-checking-mypy/14-06-SUMMARY.md
  modified:
    - tests/conftest.py
    - tests/test_alias_full_loop.py
    - tests/test_compose_email_field_regression.py
    - tests/test_concurrency_proof.py
    - tests/test_delivery.py
    - tests/test_demo_landing.py
    - tests/test_needs_operator.py
    - tests/test_pdf.py
    - tests/test_resume_pipeline.py
    - tests/test_seed_roundtrip.py
    - tests/test_suggest.py
    - tests/test_threading.py
    - tests/test_webhook.py

key-decisions:
  - "Keep the tests.* relaxed annotation requirement; annotate only helpers and dynamic boundaries that produce real mypy errors."
  - "Use runtime None narrowing for optional database rows and payroll fields, preserving every existing assertion."
  - "Use the same-session dynamic pytest pass/skip counts plus a diff-level assertion review as the TYPE-02 proof."

patterns-established:
  - "Shared in-memory repositories and LLM doubles expose typed return contracts while retaining dynamic JSON payloads as Any."
  - "Test-only monkeypatch recorders return explicit values through typed helper functions rather than relying on list.append expressions."

requirements-completed: [TYPE-02]

coverage:
  - id: D1
    description: "The first 20 test files, including shared fixtures, pass the plan-scoped mypy gate."
    requirement: "TYPE-02"
    verification:
      - kind: automated
        ref: "uv run mypy tests/__init__.py plus the 19 scoped test modules"
        status: pass
    human_judgment: false
  - id: D2
    description: "The hermetic test suite remains behaviorally unchanged after typing fixes."
    verification:
      - kind: unit
        ref: "uv run pytest -q -m 'not integration and not live_llm'"
        status: pass
      - kind: other
        ref: "dynamic before/after counts and git diff assertion-line review"
        status: pass
    human_judgment: false

# Metrics
duration: 11m 29s
completed: 2026-07-10
status: complete
---

# Phase 14 Plan 06: Test Type-Checking Summary

**The scoped first test group now passes mypy with shared fixtures typed, optional boundaries narrowed, and all assertions preserved.**

## Performance

- **Duration:** 11m 29s
- **Started:** 2026-07-10T19:03:02Z
- **Completed:** 2026-07-10T19:14:48Z
- **Tasks:** 2
- **Files modified:** 13

## Accomplishments

- Resolved all mypy errors across the plan's 20 files under the `tests.*` relaxed override; the final command reports `Success: no issues found in 20 source files`.
- Typed the shared `InMemoryRepo`, fake database connection, LLM doubles, demo spies, webhook fixture, and helper seams without changing production code.
- Proved no assertion lines were removed or modified. Added only narrowing assertions for required values such as persisted IDs, fetched rows, `annual_salary`, and `state_withholding`.
- Captured the hermetic baseline before edits and matched it afterward exactly: **615 passed, 20 skipped, 31 deselected**. `test_live_llm.py` remained guarded and skipped.

## Task Commits

Each task was committed atomically:

1. **Task 1: Resolve mypy errors in the concurrency/delivery/resume/threading test cluster** - `6b5135b` (fix)
2. **Task 2: Resolve mypy errors in the remaining test files in this group** - `f82bbf6` (fix)

**Plan metadata:** pending final planning-artifact commit.

## Files Created/Modified

- `tests/conftest.py` - Typed shared fake connection, in-memory repository, and OpenAI/Resend doubles.
- `tests/test_alias_full_loop.py`, `tests/test_resume_pipeline.py`, `tests/test_threading.py` - Typed pipeline and threading helper boundaries.
- `tests/test_concurrency_proof.py`, `tests/test_delivery.py`, `tests/test_needs_operator.py` - Typed concurrency, delivery, escalation, and optional-row seams.
- `tests/test_demo_landing.py`, `tests/test_compose_email_field_regression.py`, `tests/test_suggest.py`, `tests/test_webhook.py` - Typed route, LLM, and payload test doubles.
- `tests/test_pdf.py`, `tests/test_seed_roundtrip.py` - Narrowed optional payroll fields and database rows before use.

## Decisions Made

- Kept the `tests.*` relaxed override and avoided annotating every test function; only real mypy errors drove annotations.
- Retained `Any` only at intentionally dynamic JSON/database/mock boundaries and used concrete types everywhere else.
- Added no production symbols, endpoints, schema changes, or trust-boundary surface.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Typed shared conftest errors surfaced through the scoped test imports**
- **Found during:** Task 1 (concurrency/delivery/resume/threading test cluster)
- **Issue:** The plan-scoped mypy command follows the imported pytest fixture module, and `tests/conftest.py` contained the remaining untyped fake repository/database/LLM boundaries.
- **Fix:** Added narrow annotations and typed dynamic containers to the shared doubles; runtime behavior is unchanged.
- **Files modified:** `tests/conftest.py`
- **Verification:** Task 1 and plan-level mypy commands pass; hermetic suite remains at the exact baseline.
- **Committed in:** `6b5135b`

---

**Total deviations:** 1 auto-fixed (1 blocking typing issue)
**Impact on plan:** Necessary shared-fixture work to make the declared 20-file mypy scope genuinely pass; no scope creep or production impact.

## Assertion and Stub Review

- **Removed or modified assertion lines:** None, verified with `git diff --unified=0 -- tests | rg '^-[^-].*(assert|pytest\\.raises|raises\\()'`.
- **Added narrowing assertions:** Only runtime proofs for values that the test already required to exist; no expected behavior was weakened.
- **Known stubs:** None introduced. Empty lists/dicts and placeholder strings found by the scan are intentional fixture values or test prose, not unconnected implementation stubs.
- **Threat flags:** None. This plan changes test-only code and introduces no deployed trust-boundary surface.

## Issues Encountered

- The sandbox initially blocked access to the shared uv cache and Git index lock. Approved escalations allowed the same required `uv` and git commands to run; no repository content was altered by the failed attempts.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- TYPE-02 coverage for this test group is complete and committed.
- The full hermetic suite and plan-level scoped mypy gate are green; later Phase 14 test groups can proceed.

---
*Phase: 14-full-type-checking-mypy*
*Completed: 2026-07-10*
