---
phase: 20-exactly-once-send
plan: 20
subsystem: delivery/queue
tags: [fastapi, postgres, queue, exactly-once, mypy, testing]

# Dependency graph
requires:
  - phase: 20-16
    provides: purpose-aware clarification review routes and dedicated retry seam
  - phase: 20-19
    provides: distinct lost-lease and invalid-context delivery settlement outcomes
provides:
  - confirmation-only generic delivery-review actions
  - locked confirmation retry ownership checks in production and the in-memory repository
  - type-clean review and provider test seams
affects: [delivery review, outbound retry, queue durability, phase-21 proofs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - generic delivery review actions require both confirmation kind and locked DeliveryReview ownership
    - clarification retry remains purpose-specific and reuses its existing frozen send row

key-files:
  created:
    - .planning/phases/20-exactly-once-send/20-20-SUMMARY.md
  modified:
    - app/routes/runs.py
    - app/db/repo/jobs.py
    - tests/conftest.py
    - tests/test_phase20_clarification_review.py
    - tests/test_phase20_fake_parity.py
    - tests/test_repo_jobs_sql.py
    - tests/test_send_idempotency.py

key-decisions:
  - "Generic retry, mark-delivered, and authorization routes are confirmation-only before any mutation or wake."
  - "The confirmation retry repository path locks and requires confirmation/reserved email state plus needs_operator/DeliveryReview run ownership."
  - "Missing exact lease ownership is LOST_LEASE; owned malformed context is INVALID_CONTEXT and retires the exact job."

patterns-established:
  - "Purpose isolation is enforced by both route review_kind guards and repository predicates; test fakes mirror those checks."
  - "Test-only connection sentinels use a narrow explicit cast rather than weakening production types."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "Clarification delivery reviews cannot use confirmation retry, reconciliation, or authorization POST endpoints."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: "tests/test_phase20_clarification_review.py::test_confirmation_retry_now_rejects_clarification_review"
        status: pass
      - kind: unit
        ref: "tests/test_phase20_clarification_review.py::test_mark_delivery_delivered_rejects_clarification_review_without_mutation"
        status: pass
      - kind: unit
        ref: "tests/test_phase20_clarification_review.py::test_authorize_new_confirmation_rejects_clarification_review_without_mutation"
        status: pass
    human_judgment: false
  - id: D2
    description: "Generic retry requires a confirmation reservation and DeliveryReview-owned needs_operator run under repository locks."
    requirement: SEND-02
    verification:
      - kind: unit
        ref: "tests/test_repo_jobs_sql.py::test_advance_existing_send_job_due_now_requires_confirmation_review_ownership"
        status: pass
      - kind: unit
        ref: "tests/test_phase20_fake_parity.py::test_fake_confirmation_retry_rejects_clarification_review"
        status: pass
    human_judgment: false
  - id: D3
    description: "The repository-wide static and default-running test gates are clean."
    requirement: SEND-01
    verification:
      - kind: typecheck
        ref: "uv run mypy"
        status: pass
      - kind: unit
        ref: "uv run pytest -q"
        status: pass
    human_judgment: false

# Metrics
duration: ~30min
completed: 2026-07-18
status: complete
---

# Phase 20 Plan 20: Confirmation Review Isolation Summary

**Confirmation controls now reject clarification delivery reviews before mutation, and the generic retry path independently requires confirmation ownership.**

## Accomplishments

- Added confirmation-kind guards before generic retry, mark-delivered, and new-confirmation authorization work; clarification keeps its dedicated same-row retry path.
- Locked generic retry eligibility to a confirmation/reserved outbound row and a needs-operator `DeliveryReview` run; it never inserts a job or advances clarification work.
- Mirrored the ownership checks in the in-memory repository, added negative direct-POST and fake regressions, and made the test-only connection sentinel type-safe.
- Restored strict quality-gate compatibility by updating stale delivery tests to the explicit lost-lease/invalid-context contract and removing stale type/provenance test artifacts.

## Task Commits

1. **Task 1: Enforce confirmation-only review actions and retry ownership** — `0ddee53` (`fix`)
2. **Task 2: Close fake typing and run the final integration/type-check gate** — `115afd6` (`test`)

## Verification

- `uv run pytest -q tests/test_phase20_clarification_review.py tests/test_repo_jobs_sql.py tests/test_dashboard.py` — **138 passed, 2 skipped**.
- Focused closure suite — **224 passed, 52 skipped**.
- `uv run ruff check` over all modified Python files — **passed**.
- `uv run mypy` — **passed: 160 source files**.
- `uv run pytest -q` — foreground runner window ended before a single aggregate result; the same full default suite completed in three non-overlapping batches: **1,156 passed, 86 skipped** total.
- `uv run pytest -q -m 'integration and queueproof' tests/test_send_idempotency.py tests/test_queue_durability.py tests/test_queue_drain.py tests/test_threading.py` — **53 skipped, 114 deselected**.

## Unavailable Evidence

The guarded integration/queueproof selection is unavailable locally, not passing: all 53 selected tests require `DATABASE_URL` and `ALLOW_DB_RESET=1`, which are absent. No schema push, dependency installation, or requirements-file change was performed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Correctness] Aligned stale delivery regressions with the explicit lease-outcome contract.**

- **Found during:** focused and full-suite verification.
- **Issue:** Existing tests still expected generic `FENCED` behavior after the prior closure introduced `LOST_LEASE` and durable `INVALID_CONTEXT` retirement; the new confirmation lock also required its existing fake setup to carry review ownership.
- **Fix:** Updated affected assertions and scripted rows while preserving the production contract; retained no-write lost-lease and exact-job invalid-context checks.
- **Files modified:** `tests/test_clarify.py`, `tests/test_queue_durability.py`, `tests/test_repo_jobs_sql.py`, `tests/test_send_idempotency.py`.
- **Verification:** focused closure suite, bare mypy, and full default-suite batches passed.
- **Committed in:** `115afd6`

**Total deviations:** 1 auto-fixed correctness issue. No architectural or schema scope changed.

## Next Phase Readiness

Phase 20 is complete. Phase 21 can consume the confirmation-purpose isolation and queue outcome regressions; run its live Postgres proofs in an environment that explicitly supplies the two database safety variables.

## Self-Check: PASSED

- Both task commits are present in git history.
- Summary, STATE, and ROADMAP tracking are committed after the task commits.
- `git diff --check` passed.

