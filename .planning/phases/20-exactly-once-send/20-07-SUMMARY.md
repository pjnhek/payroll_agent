---
phase: 20-exactly-once-send
plan: "07"
subsystem: payroll-document-delivery
tags: [paystub, ytd, immutable-snapshot, confirmation]

requires:
  - phase: 20-exactly-once-send
    provides: "first-time confirmation reservation and immutable snapshot replay"
provides:
  - "Complete per-employee reconciled YTD display totals for first-time confirmation paystubs"
  - "Current and YTD earnings, deductions, and net-pay presentation in immutable PDF attachments"
affects: [confirmation-delivery, paystubs, outbound-delivery]

key-files:
  created: []
  modified:
    - app/db/repo/demo.py
    - app/pipeline/delivery.py
    - app/pipeline/pdf.py
    - tests/test_delivery.py
    - tests/test_pdf.py

key-decisions:
  - "YTD totals are reconstructed from reconciled historical line items, never the partial Social Security wage-base field."
  - "Historical reads and PDF generation occur only before an absent confirmation snapshot is reserved; existing slots replay stored bytes."

requirements-completed: [SEND-02]

coverage:
  - id: D1
    description: "A first-time confirmation uses employee-scoped, complete reconciled YTD totals for every displayed category."
    requirement: SEND-02
    verification:
      - kind: unit
        ref: "tests/test_delivery.py#test_new_confirmation_passes_complete_prior_ytd_to_paystub"
        status: pass
      - kind: unit
        ref: "tests/test_delivery.py#test_prior_ytd_query_is_employee_scoped_and_complete"
        status: pass
    human_judgment: false
  - id: D2
    description: "Existing confirmation snapshots replay without YTD derivation or a regenerated PDF attachment."
    requirement: SEND-02
    verification:
      - kind: unit
        ref: "tests/test_delivery.py#test_confirmation_replay_loads_snapshot_without_rebuilding_payload"
        status: pass
    human_judgment: false
  - id: D3
    description: "New paystubs show aligned Current and YTD values for all supported earnings, deduction, and net-pay categories."
    requirement: SEND-02
    verification:
      - kind: unit
        ref: "tests/test_pdf.py#test_current_and_ytd_columns_render_complete_honest_totals"
        status: pass
    human_judgment: false

duration: resumed
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 07: Current and YTD Paystub Summary

**New confirmation reservations now create complete, employee-scoped Current/YTD paystubs while every reserved or sent confirmation reuses its original attachment bytes.**

## Accomplishments

- Added a reconciled-history query that aggregates gross, FIT, FICA-SS, Medicare, state withholding, pre-tax 401(k), and net pay per employee within the calendar year before the current period.
- Passed the resulting display-only totals into the first-time confirmation snapshot path, with no history read or PDF generation in replay and repeat-authorization paths.
- Extended the pure ReportLab paystub layout with aligned Current/YTD earnings, deductions, totals, and net-pay values, validated from extracted PDF text.

## Task Commits

1. **Task 1: Derive complete per-category YTD totals for new paystub generation** — `76c20f3` (feat)
2. **Task 2: Render honest current-versus-YTD paystub columns** — `773adf5` (feat)

## Files Created/Modified

- `app/db/repo/demo.py` — reads complete employee-scoped reconciled history for YTD presentation.
- `app/db/repo/__init__.py` — exports the YTD display-total repository function.
- `app/pipeline/delivery.py` — derives display YTD only at first-time confirmation snapshot creation.
- `app/pipeline/pdf.py` — accepts supplied YTD totals and renders aligned current/YTD tables.
- `tests/conftest.py`, `tests/test_delivery.py`, `tests/test_pdf.py` — cover category completeness, replay immutability, and rendered PDF content.

## Decisions Made

- The YTD display ledger is independent of `ytd_ss_wages`: it must contain every rendered category or show only the current-period total.
- Paystub generation remains pure and in-memory; delivery owns when it may be called, strictly before the first snapshot reservation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Code quality] Corrected the resumed PDF module's Python 3.12 mapping import**

- **Found during:** final scope verification
- **Issue:** the resumed implementation imported `Mapping` from `typing`, failing the repository Ruff gate.
- **Fix:** imported `Mapping` from `collections.abc`.
- **Files modified:** `app/pipeline/pdf.py`
- **Verification:** `uv run ruff check app/pipeline/pdf.py tests/test_pdf.py` passed.
- **Committed in:** `773adf5`

**Total deviations:** 1 auto-fixed (1 Rule 1 code-quality correction). **Impact:** no scope expansion; restores the required lint gate.

## Issues Encountered

- Database-dependent checks remain skipped locally without `DATABASE_URL` and `ALLOW_DB_RESET=1`; the skipped checks were not treated as a live-database pass.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Confirmation delivery now has a complete YTD presentation only at its immutable snapshot boundary.
- Plan 08 can proceed against the finished confirmation and paystub contract.

## Verification

- `uv run pytest tests/test_delivery.py tests/test_send_idempotency.py -q` — 32 passed, 3 skipped.
- `uv run pytest tests/test_pdf.py tests/test_delivery.py tests/test_send_idempotency.py -q` — 55 passed, 3 skipped.
- `uv run mypy app/pipeline/pdf.py app/pipeline/delivery.py` — passed.
- `uv run ruff check app/db/repo/__init__.py app/db/repo/demo.py app/pipeline/delivery.py app/pipeline/pdf.py tests/conftest.py tests/test_delivery.py tests/test_pdf.py` — passed.
- `git diff --check` — passed.

## Self-Check: PASSED

- First-time reservations use complete reconciled history only for the newly frozen PDF bytes.
- Replays and human-authorized repeats bypass all mutable history and PDF generation.
- Every displayed paystub amount has an aligned Current and YTD value.

---
*Phase: 20-exactly-once-send*
*Completed: 2026-07-17*
