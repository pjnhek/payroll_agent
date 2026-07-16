---
phase: 18-failure-policy-sweep-deletion
plan: 06
subsystem: operator-failure-recovery
tags: [fastapi, jinja2, postgres, diagnostics, retries, immutable-history]

requires:
  - phase: 18-03
    provides: fenced terminal settlement, stable error codes, and durable retry jobs
provides:
  - bounded terminal-failure presentation shared by list, detail, and polling surfaces
  - canonical Error badges with a secondary Retries exhausted label
  - regression proof that retrigger creates a fresh job generation beside immutable dead history
affects: [18-10, 18-11, 21-durability-proofs-ops-view]

tech-stack:
  added: []
  patterns:
    - persisted diagnostics are reduced through one strict allowlist before browser use
    - manual retrigger advances reply_epoch and creates new work without reopening dead rows

key-files:
  created: []
  modified:
    - app/db/repo/demo.py
    - app/routes/runs.py
    - app/templates/runs_list.html
    - app/templates/run_detail.html
    - tests/test_dashboard.py
    - tests/test_hitl.py
    - tests/test_alias_and_run_column_regressions.py

key-decisions:
  - "Browser routes copy each run, derive a strict safe failure projection, and remove raw diagnostic fields before template or JSON use."
  - "Error remains the sole canonical run status; RetryExhausted and FinalAttemptLeaseExpired add only a secondary Retries exhausted label."
  - "The existing retrigger transaction remains unchanged because it already advances reply_epoch and inserts fresh work without mutating dead history."

patterns-established:
  - "Safe diagnostic projection: require a complete stage:reason grammar match and bounded attempt counters before rendering."
  - "Recovery history: a human action mints a new epoch-keyed job generation beside an immutable terminal row."

requirements-completed: [FAIL-02]

coverage:
  - id: D1
    description: "Run list, detail, and polling show canonical Error plus bounded retry-exhaustion context without raw diagnostics."
    requirement: FAIL-02
    verification:
      - kind: integration
        ref: "tests/test_dashboard.py#safe failure presentation and polling tests"
        status: pass
      - kind: other
        ref: "uv run pytest -q tests/test_dashboard.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Retrigger preserves the run and prior dead row while creating a fresh epoch-keyed job with a clean attempt and lease lifecycle."
    requirement: FAIL-02
    verification:
      - kind: integration
        ref: "tests/test_hitl.py#test_retrigger_preserves_dead_job_and_mints_fresh_generation"
        status: pass
      - kind: integration
        ref: "tests/test_alias_and_run_column_regressions.py#test_retrigger_clears_all_reply_context"
        status: pass
    human_judgment: false

duration: 7min
completed: 2026-07-16
status: complete
---

# Phase 18 Plan 06: Safe Failure Presentation and Immutable Retrigger Summary

**Existing operator surfaces now explain bounded terminal failures consistently, while same-run retrigger creates a fresh auditable job generation without exposing raw diagnostics or rewriting dead history.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-07-16T02:20:45Z
- **Completed:** 2026-07-16T02:27:46Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Added one strict failure-presentation map for list HTML, detail HTML, and polling JSON; malformed or unknown diagnostics degrade to generic Error copy.
- Kept Error canonical while displaying Retries exhausted only as a secondary label, with allowlisted stage, reason, and bounded attempt context.
- Proved manual recovery retains the payroll run ID, advances reply_epoch, creates a distinct clean job generation, and leaves the prior dead job unchanged.

## Task Commits

Each task was committed atomically:

1. **Task 1: Render bounded terminal diagnostics on existing run surfaces** - `ebdf152` (RED), `a415aec` (GREEN)
2. **Task 2: Restart the same run with a fresh immutable-history job generation** - `f154e33` (regression proof; established production transaction required no change)

## Files Created/Modified

- `app/db/repo/demo.py` - Projects stable run error codes and latest bounded job attempt counters without `last_error` or payloads.
- `app/routes/runs.py` - Central allowlisted failure projection and raw-diagnostic removal for browser boundaries.
- `app/templates/runs_list.html` - Canonical Error badge, secondary exhaustion label, and polling parity.
- `app/templates/run_detail.html` - Generic safe Error copy plus allowlisted stage, reason, and attempts beside Retrigger.
- `tests/test_dashboard.py` - Hostile diagnostic absence, recognized-code parity, and projection regression proofs.
- `tests/test_hitl.py` - Same-run, fresh-generation, no-new-email, no-new-run, and dead-job immutability proofs.
- `tests/test_alias_and_run_column_regressions.py` - Context reset, reply_epoch advancement, and epoch-keyed dedup regression proof.

## Decisions Made

- Raw `error_reason`, `error_detail`, `last_error`, and job counters are removed from the copied run dictionary before any template or polling response sees it.
- A terminal diagnostic renders only when the whole persisted code matches the fixed stage/reason grammar; arbitrary exception types and malformed text display generic Error copy.
- The established retrigger transaction was preserved exactly: ERROR to RECEIVED CAS, `clear_reply_context` epoch bump, then a new `run_pipeline:{run_id}:{epoch}` job in the same transaction.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The first route-inventory assertion inspected the top-level FastAPI app before lifespan router installation, producing a test-only false RED. The assertion was corrected to inspect the runs router directly; the intended no-new-retry-surface proof then passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Bounded operator diagnostics and immutable same-run recovery are ready for the producer-contract and sweep-deletion plans.
- No blockers. Plan 18-05 remains the next incomplete plan by numeric order and is independently scheduled in Wave 7.

## Self-Check: PASSED

- Plan verification suite: 12 passed, 48 deselected.
- Full dashboard regression suite: 31 passed, 2 skipped.
- Retrigger-focused recovery suite: 8 passed, 19 deselected.
- Ruff and mypy checks passed for all plan-specified source targets.
- All seven modified implementation/test files exist and all three task commits are present.

---
*Phase: 18-failure-policy-sweep-deletion*
*Completed: 2026-07-16*
