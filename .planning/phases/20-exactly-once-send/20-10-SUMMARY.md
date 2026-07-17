---
phase: 20-exactly-once-send
plan: "10"
subsystem: delivery
tags: [clarification, durable-queue, immutable-snapshot, reply-threading, alias-learning]

requires:
  - phase: 20-exactly-once-send
    provides: "immutable outbound snapshots, SEND_OUTBOUND dispatch, and purpose-safe delivery settlement"
provides:
  - "Clarification and field-regression producers that reserve one frozen envelope and enqueue identifier-only delivery work"
  - "Replay paths that read a pre-existing clarification reservation before LLM composition"
  - "Regression coverage for frozen clarification threading and alias-safe field-regression settlement"
affects: [20-12, outbound-delivery, clarification-reply, alias-learning]

tech-stack:
  added: []
  patterns: [reserve-and-enqueue producer, snapshot-first replay, post-commit worker wake]

key-files:
  created: []
  modified:
    - app/pipeline/clarification.py
    - tests/test_clarify.py
    - tests/test_clarify_rounds.py
    - tests/test_alias_full_loop.py
    - tests/test_send_idempotency.py

key-decisions:
  - "Clarification state, alias-candidate facts, snapshot reservation, and identifier-only job enqueue commit together before waking a worker."
  - "A present unconfirmed clarification snapshot is replayed without another suggestion or draft; a completed row remains a local reply-state finalization path."
  - "Record-only clarification delivery shares the durable snapshot path and is settled by the worker rather than using a producer-side send branch."

patterns-established:
  - "Clarification producer: read sent/unconfirmed slot first, otherwise compose once then reserve, enqueue, advance round, and pause in one transaction."
  - "Clarification transport settlement never confirms aliases; only the established human reply-resolution path can do that."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "Standard clarification freezes one RFC-threaded envelope, queues one immutable send job, and pauses awaiting a reply."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: tests/test_clarify.py#test_clarify_reserves_and_queues_before_pausing
        status: pass
    human_judgment: false
  - id: D2
    description: "Repeated standard and field-regression clarification entry reuses the original snapshot and job before drafting."
    requirement: SEND-02
    verification:
      - kind: unit
        ref: tests/test_clarify.py#test_clarify_reentry_reuses_the_frozen_slot_before_drafting
        status: pass
      - kind: unit
        ref: tests/test_alias_full_loop.py#test_field_regression_replay_preserves_its_slot_without_confirming_an_alias
        status: pass
    human_judgment: false
  - id: D3
    description: "Field-regression delivery cannot cross into alias confirmation."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: tests/test_alias_full_loop.py#test_field_regression_replay_preserves_its_slot_without_confirming_an_alias
        status: pass
    human_judgment: false

duration: 43min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 10: Clarification Producer Migration Summary

**Clarification and field-regression sends now freeze one thread-correct envelope and hand delivery to the durable worker without exposing the alias-confirmation path.**

## Performance

- **Duration:** 43 min
- **Completed:** 2026-07-17
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Replaced producer-side clarification provider calls with atomic reservation, identifier-only queueing, round advancement, and post-commit waking.
- Re-entry now loads an existing immutable reservation before suggestion or drafting, retaining its message identifier, reply headers, content, and single queue identity.
- Extended standard, round, idempotency, and alias-loop regressions for durable clarification delivery and alias-safe field-regression replay.

## Task Commits

1. **Task 1: Reserve and enqueue standard clarification only after the shared consumer exists** - `eb29080` (feat)
2. **Task 2: Carry field-regression clarification through the same alias-safe path** - `2d3a900` (test)

## Files Created/Modified

- `app/pipeline/clarification.py` - Reserves and queues clarification snapshots instead of calling the provider directly.
- `tests/test_clarify.py` - Covers standard immutable reservation, threading, queueing, and no-draft replay.
- `tests/test_clarify_rounds.py` - Keeps new-round coverage aligned with the queued producer contract.
- `tests/test_alias_full_loop.py` - Covers field-regression snapshot replay and alias non-mutation during scheduled delivery.
- `tests/test_send_idempotency.py` - Keeps the producer non-vacuity check aligned with durable queueing.

## Decisions Made

- Stored alias-candidate data alongside reservation and queue work so the reply workflow is committed before a worker can send the question.
- Used the existing snapshot-only handler for record-only and provider-backed clarification sends, leaving no synchronous producer send path.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated stale direct-send regression expectations**

- **Found during:** Task 1 verification
- **Issue:** Existing round and idempotency tests asserted the removed producer-side provider call, causing the focused verification suite to fail despite the required durable handoff.
- **Fix:** Replaced those assertions with frozen-reservation and identifier-only job assertions.
- **Files modified:** `tests/test_clarify_rounds.py`, `tests/test_send_idempotency.py`
- **Verification:** Focused clarification, round, alias, and idempotency tests passed.
- **Committed in:** `eb29080`

**Total deviations:** 1 auto-fixed (Rule 1 bug).
**Impact:** The affected tests now prove the durable producer contract instead of the retired synchronous behavior.

## Issues Encountered

- Guarded live-Postgres proofs skipped because `DATABASE_URL` and `ALLOW_DB_RESET=1` are not configured. They remain unavailable evidence; all hermetic checks passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 20-12 can now remove or fail-close the legacy compatibility send method after both confirmation and clarification producers use immutable queue jobs.
- Clarification replay, threading, alias, and purpose boundaries are covered by focused hermetic tests.

## Verification

- `uv run pytest tests/test_clarify.py tests/test_clarify_rounds.py tests/test_alias_full_loop.py tests/test_send_idempotency.py tests/test_comment_provenance_guard.py -q` - 49 passed, 3 skipped.
- `uv run mypy app/pipeline/clarification.py` - passed.
- `uv run ruff check app/pipeline/clarification.py tests/test_clarify.py tests/test_clarify_rounds.py tests/test_alias_full_loop.py tests/test_send_idempotency.py` - passed.
- `git diff --check` - passed.

## Self-Check: PASSED

- Both task commits and all listed files are present.
- The focused test, provenance, type, lint, and diff checks passed; guarded database proofs were reported as skipped rather than passes.

---
*Phase: 20-exactly-once-send*
*Completed: 2026-07-17*
