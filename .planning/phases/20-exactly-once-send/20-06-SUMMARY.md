---
phase: 20-exactly-once-send
plan: "06"
subsystem: dashboard-delivery-review
tags: [fastapi, jinja2, durable-queue, immutable-snapshot, operator-review]

requires:
  - phase: 20-exactly-once-send
    provides: immutable confirmation snapshots, bounded review readers, and fenced send jobs
provides:
  - Bounded delivery-review routes for frozen confirmation evidence and two explicit operator outcomes
  - Provider-free mark-delivered and typed, immutable new-confirmation authorization
  - Server-rendered review card using only allowlisted facts and read-only progressive enhancement
affects: [20-08, 20-12, outbound-delivery]

tech-stack:
  added: []
  patterns:
    - Validate delivery-review status plus owned frozen reservation before every evidence read or action
    - Advance an existing send job only inside the caller transaction and wake only after commit
    - Clone a human-authorized confirmation from stored envelope and attachment bytes, never current payroll data

key-files:
  created: []
  modified:
    - app/routes/runs.py
    - app/templates/run_detail.html
    - app/static/style.css
    - tests/test_dashboard.py
    - tests/test_needs_operator.py

key-decisions:
  - "A delivery review is eligible only for a confirmation reservation owned by a needs_operator run with the bounded DeliveryReview marker."
  - "Mark delivered CASes the run to reconciled without a provider call or worker wake."
  - "A typed authorization bumps the human-controlled epoch and creates one new confirmation slot from the original frozen bytes under a fresh Message-ID."

patterns-established:
  - "Browser delivery-review boundary: allowlisted recipient, subject, reservation time, attempts, category, Message-ID, and artifact links only."
  - "Frozen evidence routes verify review eligibility and run/snapshot ownership before returning stored email text or attachment bytes."

requirements-completed: [SEND-03]

coverage:
  - id: D1
    description: "Delivery-review evidence routes return only an owned frozen email and attachment, without mutable payroll reads."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: tests/test_dashboard.py#test_delivery_review_serves_only_owned_frozen_email_and_attachment
        status: pass
    human_judgment: false
  - id: D2
    description: "Retry-now advances only the existing pending job; mark delivered cannot reach the provider; stale submissions are safe no-ops."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: tests/test_dashboard.py#test_delivery_review_retry_now_advances_only_the_existing_pending_job
        status: pass
      - kind: unit
        ref: tests/test_dashboard.py#test_delivery_review_mark_delivered_is_a_provider_free_cas
        status: pass
    human_judgment: false
  - id: D3
    description: "Typed authorization creates one distinct confirmation slot with byte-identical frozen content and one durable job."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: tests/test_dashboard.py#test_delivery_review_authorization_clones_frozen_bytes_into_one_new_slot
        status: pass
    human_judgment: false
  - id: D4
    description: "The review card exposes safe facts, frozen evidence links, and exactly the two operator outcomes without client-side recovery."
    requirement: SEND-03
    verification:
      - kind: automated_ui
        ref: tests/test_dashboard.py#test_delivery_review_card_uses_only_the_safe_projection
        status: pass
      - kind: unit
        ref: tests/test_dashboard.py#test_delivery_review_template_has_no_automatic_recovery_action
        status: pass
    human_judgment: false

duration: 45min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 06: Delivery Review Controls Summary

**Unsafe confirmation-delivery uncertainty is now a bounded, server-rendered operator review with frozen evidence and two explicit outcomes.**

## Accomplishments

- Added owned frozen-email and attachment routes that cannot consult current payroll, contact, or PDF-generation data.
- Added transactional retry-now, provider-free mark-delivered, and exact-acknowledgement authorization routes; only authorization creates a fresh confirmation slot and queued job.
- Added a compact review card that shows safe delivery facts, frozen artifact links, duplicate-risk wording, and no automatic recovery action.

## Task Commits

1. **Task 1: Add bounded delivery-review projection and transactional operator actions** — `afb9b23`
2. **Task 2: Render the review card with narrow progressive enhancement** — `a9bfb0d`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated a stale clarification producer assertion**

- **Found during:** Task 1 focused verification.
- **Issue:** A cap-boundary test still required the clarification producer to call the provider synchronously, although the completed durable producer migration queues its frozen send job instead.
- **Fix:** Replaced the direct-send assertion with one identifier-only send-job assertion and retained the cap/state checks.
- **Files modified:** `tests/test_needs_operator.py`
- **Verification:** `uv run pytest tests/test_needs_operator.py tests/test_dashboard.py tests/test_send_idempotency.py -q`.
- **Committed in:** `afb9b23`

**Total deviations:** 1 auto-fixed (1 Rule 1 bug). **Impact:** The regression now proves the deployed durable producer contract and does not change production behavior.

## Issues Encountered

- The first focused test invocation was blocked from the shared uv cache by the sandbox. The approved scoped test command completed normally afterward.

## User Setup Required

None.

## Verification

- `uv run pytest tests/test_needs_operator.py tests/test_dashboard.py tests/test_send_idempotency.py -q` — 96 passed, 6 skipped.
- `uv run mypy app/routes/runs.py` — passed.
- `uv run ruff check app/routes/runs.py tests/test_dashboard.py tests/test_needs_operator.py` — passed.
- `git diff --check` — passed.

## Next Phase Readiness

- The remaining Phase 20 plans can rely on a review surface that preserves the original confirmation artifact and blocks automatic replacement sends.
- The configured live-Postgres proofs remain unavailable locally without `DATABASE_URL` and `ALLOW_DB_RESET=1`; skipped checks are not treated as passing live evidence.

## Self-Check: PASSED

- Both task commits are present and the five scoped files are committed.
- All plan-level focused tests, type checks, lint, and diff checks passed.
- The review routes and template expose no provider request/response diagnostics, queue identifiers, arbitrary form data, or mutable artifact generation path.

---
*Phase: 20-exactly-once-send*
*Completed: 2026-07-17*
