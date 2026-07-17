---
phase: 20-exactly-once-send
plan: 14
subsystem: database/testing
tags: [postgres, psycopg, email-threading, exactly-once, repository-boundaries]

# Dependency graph
requires:
  - phase: 20-exactly-once-send
    provides: immutable outbound snapshots, epoch-stamped email rows, and durable send jobs
provides:
  - current-reply-epoch header routing with separate late-reply observability
  - body-free delivery-review projection with purpose and attachment metadata
  - constrained outbound reserved-to-sent compatibility transition and retired arbitrary mutator
  - regression coverage for stale headers, projection boundaries, and state mutation
affects: [durable reply routing, delivery review, outbound settlement, Phase 21 durability proofs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - current-epoch SQL predicates are required for live reply authorization
    - bounded review projections expose facts and attachment references, not frozen body content
    - compatibility writers fail closed unless they implement one explicit outbound transition

key-files:
  created:
    - tests/test_phase20_repo_hygiene.py
    - .planning/phases/20-exactly-once-send/deferred-items.md
  modified:
    - app/db/repo/emails.py
    - tests/conftest.py
    - tests/test_threading.py
    - tests/test_send_idempotency.py

key-decisions:
  - "Awaiting-reply routing requires em.epoch = pr.reply_epoch; any-status lookup remains the late-reply observability path."
  - "The bounded review projection retains purpose, identity, timing, attempt, and attachment metadata while body access stays on load_outbound_snapshot."
  - "update_email_message_state remains importable only as a fail-closed compatibility seam; update_email_message_sent permits outbound reserved-to-sent only."

patterns-established:
  - "Append-only email history may retain stale epochs, but only the current epoch can authorize resume."
  - "Fake repositories mirror production negative boundaries so offline tests cannot accept unsafe state or projection behavior."

requirements-completed: [SEND-01, SEND-03]

coverage:
  - id: D1
    description: "Clarification reply routing rejects stale epoch headers and accepts only the current epoch."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: tests/test_threading.py#test_stale_epoch_header_cannot_resume_current_awaiting_run
        status: pass
      - kind: integration
        ref: tests/test_threading.py#test_live_header_routing_rejects_stale_epoch
        status: unknown
    human_judgment: true
    rationale: "The guarded live-Postgres proof was unavailable because DATABASE_URL and ALLOW_DB_RESET=1 were not configured."
  - id: D2
    description: "Delivery-review facts are body-free while the authorized frozen snapshot reader retains the exact body and attachments."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: tests/test_phase20_repo_hygiene.py#test_delivery_review_projection_is_body_free_but_frozen_reader_is_not
        status: pass
    human_judgment: false
  - id: D3
    description: "The legacy arbitrary email-state writer cannot mutate inbound or invalid state, and the retained sent helper is outbound reserved-only."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: tests/test_phase20_repo_hygiene.py#test_retired_email_state_mutator_fails_before_sql
        status: pass
      - kind: unit
        ref: tests/test_phase20_repo_hygiene.py#test_sent_transition_is_outbound_reserved_only_and_row_count_safe
        status: pass
    human_judgment: false

# Metrics
duration: 20min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 14: Repository Boundary Closure Summary

Current-epoch clarification routing, body-free delivery-review facts, and a fail-closed email-state compatibility boundary now protect the exactly-once send path.

## Performance

- **Duration:** ~20 minutes
- **Started:** 2026-07-17T15:44:27-07:00
- **Completed:** 2026-07-17T16:03:04-07:00
- **Tasks:** 2/2
- **Files modified:** 6 implementation/test/deferred files, plus this summary

## Accomplishments

- Added `em.epoch = pr.reply_epoch` to awaiting-reply header routing and mirrored it in the in-memory repository; stale headers remain observable through the separate any-status lookup.
- Removed frozen `body_text` from the bounded delivery-review projection while retaining purpose, safe envelope facts, attempt count, and attachment references; frozen body access remains on `load_outbound_snapshot`.
- Retired arbitrary `update_email_message_state` writes and constrained `update_email_message_sent` to outbound reserved-to-sent rows with a row-count-safe failure.
- Added focused ordinary and guarded live routing tests plus repository hygiene tests.

## Task Commits

1. **Task 1: Restrict awaiting-reply header routing to the current epoch** - `fd301a9`, `3d2d2bf` (RED tests); `6fb89d5` (implementation)
2. **Task 2: Remove body text from review projection and retire unsafe email-state mutation** - `ef33693` (RED tests); `7b50ff5` (projection completion); `9fddc64` (provenance/deferred-item documentation)

The shared `app/db/repo/emails.py` implementation commit `6fb89d5` also carried the body-free projection and state-mutator closure because both planned tasks modify the same repository module; the remaining Task 2-specific projection contract was committed separately in `7b50ff5`.

## Files Created/Modified

- `app/db/repo/emails.py` - current-epoch header predicate, safe review projection, and constrained/retired state writers.
- `tests/conftest.py` - fake repository parity for epoch routing, body-free review facts, and constrained sent transitions.
- `tests/test_threading.py` - ordinary and guarded live stale-epoch routing regressions.
- `tests/test_phase20_repo_hygiene.py` - projection and state-mutator boundary tests.
- `tests/test_send_idempotency.py` - updated review projection contract expectation.
- `.planning/phases/20-exactly-once-send/deferred-items.md` - records unrelated full-suite settlement/job-lock failures without changing Plan 20-13 code.

## Decisions Made

- Preserve the shared header predicate and add the epoch condition only to the awaiting-reply query so late-reply attribution remains available.
- Keep the review projection intentionally non-content-bearing; callers needing the frozen body must use the separately scoped snapshot reader.
- Keep the legacy symbol for import compatibility, but make arbitrary state mutation fail before connection use.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical parity] Completed the projection contract in the fake repository**
- **Found during:** Task 2 verification
- **Issue:** The bounded projection was body-free but omitted the required `purpose` fact, and the fake did not expose it.
- **Fix:** Added `purpose` to the production SQL projection and fake mapping, then updated the existing review assertion.
- **Files modified:** `app/db/repo/emails.py`, `tests/conftest.py`, `tests/test_send_idempotency.py`
- **Verification:** Focused suite passed; mypy and ruff passed.
- **Committed in:** `7b50ff5`

**2. [Rule 1 - Test hygiene bug] Removed provenance-sensitive wording from the new test module**
- **Found during:** Full-suite verification
- **Issue:** The repository's comment-provenance guard rejected the new module's literal phase label.
- **Fix:** Reworded the module docstring without changing behavior.
- **Files modified:** `tests/test_phase20_repo_hygiene.py`
- **Verification:** `test_no_ticket_provenance_in_source_tree` passed.
- **Committed in:** `9fddc64`

**Total deviations:** 2 auto-fixed.
**Impact on plan:** Both changes were required for repository parity and the existing quality guard. The Task 2 code shared one repository commit with Task 1; no unrelated production behavior was changed.

## TDD Gate Compliance

- Task 1 RED: `fd301a9` and guarded live regression `3d2d2bf`; GREEN: `6fb89d5`.
- Task 2 RED: `ef33693`; the initial body/mutator assertions already passed because the shared repository commit had landed those changes, so the missing `purpose` assertion was added to establish a genuine failing RED case; GREEN: `7b50ff5`.

## Issues Encountered

- The full suite finished with 10 failures in pre-existing Plan 20-13 settlement/job-locking tests (`tests/test_clarify.py`, `tests/test_queue_drain.py`, and `tests/test_repo_jobs_sql.py`). Those failures are outside this plan's files and were recorded in `deferred-items.md`; no Plan 20-13 code was changed.
- Guarded live database evidence is unavailable: all 4 selected integration/queueproof tests skipped because `DATABASE_URL` and `ALLOW_DB_RESET=1` were absent. This is unavailable evidence, not a passing database proof.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The repository boundaries are ready for downstream delivery-review and durability proof work. Run the guarded Postgres tests when database configuration is available; separately resolve the recorded Plan 20-13 fake-row shape failures before relying on a clean whole-repository suite.

## Self-Check: PASSED

- Summary file exists at `.planning/phases/20-exactly-once-send/20-14-SUMMARY.md`.
- Task commits `fd301a9`, `3d2d2bf`, `6fb89d5`, `ef33693`, `7b50ff5`, and `9fddc64` were found in git history.
- `git diff --check` passed for the summary.
- `.planning/STATE.md` remains the orchestrator's pre-existing unstaged modification; `.planning/ROADMAP.md` was not changed or staged.

---
*Plan: 20-14*
*Completed: 2026-07-17*
