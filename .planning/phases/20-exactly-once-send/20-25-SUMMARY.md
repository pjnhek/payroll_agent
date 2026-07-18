---
phase: 20-exactly-once-send
plan: 25
subsystem: outbound-delivery
tags: [postgres, provider-handoff, retrigger, delivery-review, epoch-fence]

# Dependency graph
requires:
  - phase: 20-exactly-once-send
    provides: durable provider-handoff fence, exact settlement, and frozen confirmation review
provides:
  - rollback-safe generic retrigger behavior while a provider handoff remains active
  - exact frozen-snapshot D-09/D-11 review resolution for an active handoff
  - in-memory parity and browser/repository regressions for reviewed delivery outcomes
affects: [outbound delivery, delivery review, queue recovery, exactly-once verification]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - active-handoff exceptions escape their caller-owned transaction before a bounded browser no-op
    - explicit delivery review may resolve only the active handoff matching its frozen email and snapshot

key-files:
  created: []
  modified:
    - app/db/repo/outbound_handoffs.py
    - app/routes/runs.py
    - tests/test_retrigger_epoch.py
    - tests/test_phase20_clarification_review.py

key-decisions:
  - "Generic retrigger catches ActiveOutboundProviderHandoffError only outside its transaction, so the prior status CAS is rolled back with the denied epoch bump."
  - "D-09 records finalized and D-11 records delivery_review only when the active handoff belongs to the review's exact frozen email/snapshot; a settled no-active-handoff case remains safe."

patterns-established:
  - "Browser delivery-review overrides are purpose-bound and snapshot-bound; they do not receive a worker lease or a generic handoff release capability."
  - "A new confirmation clones frozen envelope and attachment bytes into a distinct post-epoch slot only after the typed acknowledgement and handoff resolution commit together."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "Generic retrigger rolls back its status claim and creates no epoch, job, or wake while an active provider handoff exists; a released handoff permits the normal route."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: "tests/test_retrigger_epoch.py#test_generic_retrigger_rolls_back_when_provider_handoff_is_active"
        status: pass
      - kind: unit
        ref: "tests/test_retrigger_epoch.py#test_released_provider_handoff_allows_ordinary_retrigger"
        status: pass
    human_judgment: false
  - id: D2
    description: "D-09 mark-delivered resolves only its matching active confirmation handoff without another send, job, or wake."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: "tests/test_phase20_clarification_review.py#test_mark_delivered_releases_only_its_active_confirmation_handoff"
        status: pass
      - kind: unit
        ref: "tests/test_send_idempotency.py#test_delivery_review_can_release_only_its_matching_active_handoff"
        status: pass
    human_judgment: false
  - id: D3
    description: "Only the exact typed D-11 acknowledgement releases an ambiguous handoff and creates a distinct slot with byte-identical frozen content."
    requirement: SEND-02
    verification:
      - kind: unit
        ref: "tests/test_phase20_clarification_review.py#test_typed_confirmation_authorization_releases_handoff_and_clones_frozen_bytes"
        status: pass
    human_judgment: false

# Metrics
duration: ~25min
completed: 2026-07-18
status: complete
---

# Phase 20 Plan 25: Browser Handoff Fence Summary

**Generic browser retrigger now rolls back cleanly behind an unresolved provider handoff, while the two explicitly reviewed confirmation outcomes resolve only their exact frozen delivery generation.**

## Accomplishments

- Let `ActiveOutboundProviderHandoffError` leave retrigger's transaction before returning its existing bounded 303 response, preventing a committed status claim, epoch bump, enqueue, or wake.
- Added an exact review-only handoff resolver that checks the frozen review email and snapshot before D-09 finalizes or D-11 supersedes an active handoff.
- Preserved the D-11 post-epoch slot's frozen envelope and attachment bytes, and extended the in-memory repository so hermetic route tests model the same boundary.

## Task Commits

1. **Task 1: Prevent generic retrigger from crossing an active provider handoff** — `bdcfcec` (fix)

## Files Created/Modified

- `app/db/repo/outbound_handoffs.py` — exact D-09/D-11 active-handoff resolution seam.
- `app/db/repo/__init__.py` — exports the review-only repository seam.
- `app/routes/runs.py` — rollback-safe retrigger plus purpose-bound review resolution.
- `tests/conftest.py` — parity implementation for review-only handoff resolution.
- `tests/test_retrigger_epoch.py` — active rollback and released-handoff recovery regressions.
- `tests/test_phase20_clarification_review.py` — D-09/D-11 active handoff route contracts.
- `tests/test_send_idempotency.py` — production SQL shape/identity regression for review resolution.

## Decisions Made

- A review action may proceed if no active handoff remains (it may have been settled already), but it fails closed if the sole active handoff belongs to another frozen generation.
- The review resolver is intentionally not a generic release API: only the confirmation delivery-review routes call it, after their existing purpose and acknowledgement checks.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added the missing review-only handoff resolution seam and fake parity.**

- **Found during:** Task 1 implementation.
- **Issue:** Plan 20-21 exposed exact worker-owner release APIs but no safe D-09/D-11 consumer seam; the review routes could not clear an active ambiguous handoff without either blocking forever or gaining generic release authority.
- **Fix:** Added a snapshot-bound resolver for the sole active handoff, exported it through the facade, and mirrored it in the hermetic repository double.
- **Files modified:** `app/db/repo/outbound_handoffs.py`, `app/db/repo/__init__.py`, `tests/conftest.py`, `tests/test_send_idempotency.py`.
- **Verification:** focused route/repository tests, Ruff, and mypy passed.
- **Committed in:** `bdcfcec`.

**Total deviations:** 1 auto-fixed (Rule 2 correctness/security).
**Impact on plan:** The additional seam is narrowly required to implement the plan's D-09/D-11-only override requirement; it adds no provider, payload, or generic browser release capability.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Epoch-changing browser recovery and reviewed delivery actions now share the durable provider-handoff boundary.
- The remaining phase verification can rely on focused regressions for active, released, finalized, and human-authorized replacement paths.

## Verification

- `uv run pytest -q tests/test_retrigger_epoch.py tests/test_phase20_clarification_review.py tests/test_delivery.py` — **34 passed**.
- `uv run pytest -q tests/test_retrigger_epoch.py tests/test_phase20_clarification_review.py tests/test_delivery.py tests/test_send_idempotency.py` — **70 passed, 3 skipped**.
- `uv run ruff check app/db/repo/pipeline_state.py app/db/repo/outbound_handoffs.py app/db/repo/__init__.py app/routes/runs.py tests/conftest.py tests/test_retrigger_epoch.py tests/test_phase20_clarification_review.py tests/test_send_idempotency.py` — **passed**.
- `uv run mypy` — **passed: 161 source files**.

## Self-Check: PASSED

---
*Plan: 20-25*
*Completed: 2026-07-18*
