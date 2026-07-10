---
phase: 14-full-type-checking-mypy
plan: 03
subsystem: testing
tags: [mypy, typing, payroll-pipeline, email-gateway, pydantic, reportlab]

# Dependency graph
requires:
  - phase: 14-full-type-checking-mypy
    provides: Strict mypy configuration and typed application/database substrate from Plans 14-01 and 14-02
provides:
  - Strict annotations for the deterministic payroll calculation, decision, reconciliation, validation, and alias-learning stages
  - Fully mypy-clean email gateway and pipeline orchestration/delivery modules
  - One documented D-09 exception-attribute ignore at the delivery scrub boundary
affects: [14-04, 14-05, 14-06, 14-07, 14-08, 14-09, 14-10, full-repo-mypy]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Use concrete Decimal, UUID, Pydantic model, and typed collection annotations throughout money-path logic."
    - "Keep dict[str, Any] and explicit casts at dynamic LLM, JSONB, Resend, and raw-input boundaries only."
    - "Preserve provider runtime shapes with a narrow Protocol/cast rather than changing gateway behavior."

key-files:
  created:
    - .planning/phases/14-full-type-checking-mypy/deferred-items.md
  modified:
    - app/pipeline/calculate.py
    - app/pipeline/decide.py
    - app/pipeline/validate.py
    - app/pipeline/alias_learning.py
    - app/email/gateway.py
    - app/pipeline/extract.py
    - app/pipeline/suggest.py
    - app/pipeline/compose_email.py
    - app/pipeline/clarification.py
    - app/pipeline/pdf.py
    - app/pipeline/delivery.py
    - app/pipeline/orchestrator.py

key-decisions:
  - "Keep the existing _ReceivedEmailLike Protocol and attribute access after confirming the installed Resend runtime returns an attribute-style ReceivedEmail object."
  - "Keep the single sanctioned delivery.py # type: ignore[attr-defined] on the best-effort payroll_roster exception attribute, with the WR-04 reason comment and unchanged exception structure."
  - "Keep Task 1 ownership atomic by placing the raw-hours compatibility cast at orchestrator's calculate call site rather than changing the committed calculate.py annotation afterward."

patterns-established:
  - "Injected LLM clients use explicit Any at the dependency boundary while stage inputs and outputs remain concrete Pydantic contracts."
  - "Optional state-machine values are narrowed explicitly before existing reads and transaction writes."

requirements-completed: [TYPE-01]

coverage:
  - id: D1
    description: "The complete app/pipeline and app/email scopes pass strict mypy with no errors."
    requirement: TYPE-01
    verification:
      - kind: other
        ref: "uv run mypy app/pipeline/ app/email/"
        status: pass
    human_judgment: false
  - id: D2
    description: "Email signature verification, inbound parsing, and outbound gateway behavior remain covered by the existing gateway tests."
    requirement: TYPE-01
    verification:
      - kind: unit
        ref: "tests/test_gateway.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "The full hermetic suite remains green after all pipeline and gateway annotations."
    requirement: TYPE-01
    verification:
      - kind: unit
        ref: "uv run pytest -q -m 'not integration and not live_llm'"
        status: pass
    human_judgment: false

# Metrics
duration: 13 min
completed: 2026-07-10
status: complete
---

# Phase 14 Plan 03: Full Pipeline and Email Type Checking Summary

**Strictly typed payroll pipeline and Resend email gateway with deterministic money-path annotations, one justified delivery ignore, and a green hermetic suite**

## Performance

- **Duration:** 13 min
- **Started:** 2026-07-10T18:29:15Z
- **Completed:** 2026-07-10T18:42:09Z
- **Tasks:** 3
- **Files modified:** 12 source files plus planning notes

## Accomplishments

- Added concrete strict annotations to the payroll calculation, deterministic decision, reconciliation/validation, tax-table, and alias-learning paths without changing payroll logic.
- Closed the residual `app/email/gateway.py` and `app/email/` mypy ownership gap while preserving Resend runtime attribute access, signature checks, threading, and send ordering.
- Typed extraction, suggestion, clarification, PDF, delivery, and orchestration paths, including the state-machine narrowing and the exact D-09-sanctioned WR-04 exception attribute ignore.

## Verification

- `uv run mypy app/pipeline/ app/email/` — `Success: no issues found in 18 source files`.
- `uv run pytest tests/test_calculate.py tests/test_decide_field_regression.py tests/test_reconcile.py tests/test_validate.py tests/test_tax_tables_2026.py tests/test_alias_write.py tests/test_alias_full_loop.py -q` — 100 passed.
- `uv run pytest tests/test_gateway.py -q` — 36 passed, 3 skipped.
- `uv run pytest tests/test_extract.py tests/test_suggest.py tests/test_clarify.py tests/test_clarify_rounds.py tests/test_pdf.py tests/test_delivery.py tests/test_orchestrator_states.py tests/test_resume_pipeline.py tests/test_multi_employee_delivery.py -q` — 78 passed, 20 skipped.
- `uv run pytest -q -m "not integration and not live_llm"` — 615 passed, 20 skipped, 31 deselected.
- Scoped Ruff check over all Task 3 files — passed. A pre-existing Ruff import issue in `app/pipeline/federal_withholding.py` remains outside this plan and is recorded in `deferred-items.md`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Annotate money-path core** — `9b85d3a` (feat)
2. **Task 2: Annotate app/email gateway** — `ab6b599` (feat)
3. **Task 3: Annotate remaining pipeline modules** — `564b240` (feat)

**Plan metadata:** final metadata commit records this summary and normal GSD state/roadmap updates.

## Files Created/Modified

- `app/pipeline/calculate.py`, `decide.py`, `validate.py`, and `alias_learning.py` — concrete money-path and alias-learning types.
- `app/email/gateway.py` — typed Resend envelope, connection, threading, and send payload boundaries.
- `app/pipeline/extract.py`, `suggest.py`, `compose_email.py`, and `clarification.py` — typed LLM-facing stage seams and clarification state values.
- `app/pipeline/pdf.py` and `delivery.py` — typed reportlab/delivery paths with the one sanctioned dynamic exception attribute.
- `app/pipeline/orchestrator.py` — typed state-machine stage contracts, backfill, and line-item computation.
- `.planning/phases/14-full-type-checking-mypy/deferred-items.md` — records the unrelated pre-existing federal withholding Ruff finding.

## Decisions Made

- Confirmed Resend's installed `EmailsReceiving.get()` runtime returns an attribute-style object, so the existing `_ReceivedEmailLike` Protocol/cast remains the correct boundary.
- Used explicit concrete types for money-path values and typed collections; retained `Any` only for dynamic payloads and injected LLM/provider objects.
- Preserved the delivery exception handling shape exactly and scoped the only new ignore to `exc.payroll_roster` with the WR-04 rationale.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking type mismatch] Narrowed the raw-hours mapping at the orchestrator boundary**
- **Found during:** Task 3 (remaining pipeline modules)
- **Issue:** After the Task 3 line-item annotations, mypy rejected the invariant `dict[str, Decimal | None]` passed to the Task 1 `dict[str, object]` calculate contract.
- **Fix:** Added an explicit static cast at the existing orchestrator-to-calculate boundary, preserving Task 1's committed file ownership and runtime behavior.
- **Files modified:** `app/pipeline/orchestrator.py`
- **Verification:** Plan-level mypy and the full hermetic suite passed.
- **Committed in:** `564b240`

---

**Total deviations:** 1 auto-fixed (Rule 3: blocking type mismatch)
**Impact on plan:** No scope creep or behavior change; the fix makes the existing dynamic raw-input boundary explicit.

## Issues Encountered

- The sandbox initially blocked `uv` cache access and Git index writes in the main checkout. Required commands were rerun with elevated access; no dependencies or unrelated files were changed.
- A pre-existing Ruff import-order/unused-import finding in `app/pipeline/federal_withholding.py` was outside Plan 14-03 ownership and was logged in `deferred-items.md` rather than modified.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

TYPE-01 is complete for the pipeline and email scopes. Plan 14-04 can type-check the route packages and `app/main.py` against these clean transitive imports. The only known lint item is the deferred Plan 14-01 `federal_withholding.py` finding.

---
*Phase: 14-full-type-checking-mypy*
*Completed: 2026-07-10*

## Self-Check: PASSED

- Summary file exists at `.planning/phases/14-full-type-checking-mypy/14-03-SUMMARY.md`.
- Task commits `9b85d3a`, `ab6b599`, and `564b240` are present in git history.
- The exact plan-level mypy and hermetic test commands passed before summary creation.
