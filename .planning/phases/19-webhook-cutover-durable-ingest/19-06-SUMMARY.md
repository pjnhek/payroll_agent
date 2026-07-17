---
phase: 19-webhook-cutover-durable-ingest
plan: 06
subsystem: api
tags: [fastapi, postgres, webhook, svix, durable-queue, run-in-threadpool]

requires:
  - phase: 19-webhook-cutover-durable-ingest
    provides: persisted inbound-event repository and identifier-only ingest jobs
  - phase: 16-queue-substrate-unblocked-webhook
    provides: behaviorally proven worker-thread boundary for blocking webhook work
provides:
  - bounded exact-byte webhook streaming and authentication before envelope parsing
  - atomic inbound-event plus ingest-job acceptance before wake and HTTP success
  - stable accepted or duplicate event receipts with no payroll or queue identifiers
affects: [19-10-retention-durability-proof, 19-11-test-consumer-migration, webhook-ingest]

tech-stack:
  added: []
  patterns:
    - synchronous caller-owned receipt transaction awaited through run_in_threadpool
    - post-commit wake with fixed diagnostic-free HTTP responses

key-files:
  created: []
  modified:
    - app/routes/webhook.py
    - tests/test_durable_ingest.py
    - tests/test_webhook_unblocked.py
    - tests/test_webhook.py

key-decisions:
  - "Signed receipts deduplicate on the authenticated Svix ID; explicitly enabled unsigned fixtures use a SHA-256 key over the exact bounded bytes."
  - "The request route validates only data.email_id for signed traffic or message_id for fixture traffic; provider fetch and payroll classification remain delayed worker responsibilities."
  - "Only a newly committed event wakes the worker; a duplicate returns the original internal event UUID without creating a second job."

patterns-established:
  - "Receipt boundary: stream and cap, authenticate exact bytes, await one blocking transaction, wake after commit, return fixed receipt."
  - "Transport failures expose only bounded 400, 413, or 503 responses and never database or provider diagnostics."

requirements-completed: [QUEUE-04]

coverage:
  - id: D1
    description: "The webhook commits one verified event and one identifier-only ingest job atomically before wake and 200."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_durable_ingest.py#test_acceptance_commits_event_and_identifier_only_job_before_wake_and_response"
        status: pass
      - kind: unit
        ref: "tests/test_durable_ingest.py#test_receipt_transaction_rollback_returns_bounded_503"
        status: pass
    human_judgment: false
  - id: D2
    description: "A repeated transport event returns the same internal event UUID and creates neither a second ingest job nor a second wake."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_durable_ingest.py#test_duplicate_redelivery_returns_stable_event_receipt_and_creates_no_second_job"
        status: pass
    human_judgment: false
  - id: D3
    description: "Slow synchronous receipt persistence runs off-loop while unrelated coroutine work continues."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_webhook_unblocked.py#test_slow_database_receipt_does_not_block_unrelated_event_loop_work"
        status: pass
    human_judgment: false
  - id: D4
    description: "The request boundary enforces 256 KiB streaming, signature-before-parse, fixture gating, and no provider fetch or payroll execution."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_webhook.py"
        status: pass
      - kind: other
        ref: "uv run mypy app/routes/webhook.py"
        status: pass
    human_judgment: false

duration: 8min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 06: Off-Loop Durable Webhook Receipt Summary

**The webhook now returns success only after exact authenticated bytes produce one committed inbound event and one identifier-only ingest job, with blocking Postgres work isolated from the event loop.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-17T02:19:06Z
- **Completed:** 2026-07-17T02:26:56Z
- **Tasks:** 2 TDD tasks
- **Files modified:** 4

## Accomplishments

- Replaced unbounded `request.body()` and request-lifetime provider/business ingest with a 256 KiB streamed, verify-before-parse receipt boundary.
- Added one synchronous caller-owned transaction that insert/gets the event and enqueues exact `ingest:{event_id}` work only for a new event, then wakes only after commit.
- Returned fixed `accepted` or `duplicate` event receipts with stable internal UUIDs and no run ID, job ID, message content, or diagnostics.
- Preserved the prior off-loop guarantee with a blocked synchronous persistence test that proves an unrelated coroutine reaches its sentinel before the database seam is released.

## Task Commits

1. **Task 1 RED: Pin atomic receipt, rollback, auth, cap, dedup, and responsiveness contracts** - `e4e4fb7` (test)
2. **Task 2 GREEN: Cut the webhook to bounded off-loop durable receipt** - `5c993d7` (feat)

## Files Created/Modified

- `app/routes/webhook.py` - Receipt-only route, bounded stream helper, minimal envelope validator, and atomic event/job persistence helper.
- `tests/test_durable_ingest.py` - Receipt co-commit, rollback, stable redelivery, exact-byte signature, and no-fetch proofs beside delayed-ingest coverage.
- `tests/test_webhook_unblocked.py` - Deterministic blocked-database event-loop responsiveness proof and awaited threadpool source guard.
- `tests/test_webhook.py` - Signature, production fixture gating, streaming cap, and no-inline-business guards.

## Decisions Made

- The fixture fallback key is `sha256:<hex>` over the exact bounded request bytes and is reachable only when unsigned fixtures are explicitly enabled.
- Signed traffic must minimally contain a nonempty `data.email_id`; canonical fixture traffic must minimally contain a nonempty `message_id`. Full provider fetch and domain validation happen in delayed ingest.
- A new event with a conflicting ingest dedup key is treated as an invariant failure so the caller-owned transaction rolls back and the provider receives a retryable bounded 503.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The RED gate produced 7 expected failures because the receipt helper, streaming cap, stable event receipt, rollback mapping, and route-level threadpool call did not yet exist.
- The focused final suite emits the existing Starlette/httpx TestClient deprecation warning.
- The complete legacy wrapper-consumer suite is intentionally migrated in Plan 19-11 after this request cutover; this plan does not claim that later wave's full-suite closeout.

## User Setup Required

None - no external service configuration required.

## Verification

- Focused receipt and delayed-ingest suite: 20 passed.
- Comment-provenance guard: 5 passed.
- Ruff: passed for all four modified production/test files.
- Mypy: passed for `app/routes/webhook.py`.
- `git diff --check`: passed.
- Guarded live-Postgres evidence remains outside this plan and is explicitly owned by Plan 19-10.

## Next Phase Readiness

- Plan 19-09 can add bounded queue-state presentation independently of the receipt boundary.
- Plan 19-11 can migrate legacy request/background-wrapper test consumers against the durable receipt and delayed-ingest seams now present.
- Plan 19-10 can add post-200 drain and guarded same-Svix Postgres evidence after the consumer/guard plans complete.

## Self-Check: PASSED

- All four modified production/test files exist.
- RED/GREEN commits `e4e4fb7` and `5c993d7` exist in history.
- Every task acceptance criterion and plan-level focused/static check is green.
- No generated or untracked artifact remains.

---
*Phase: 19-webhook-cutover-durable-ingest*
*Completed: 2026-07-16*
