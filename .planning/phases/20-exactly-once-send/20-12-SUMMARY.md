---
phase: 20-exactly-once-send
plan: "12"
subsystem: outbound-delivery
tags: [immutable-snapshot, durable-queue, test-migration, clarification]

requires:
  - phase: 20-exactly-once-send
    provides: "fail-closed legacy gateway plus immutable identifier-only send jobs"
provides:
  - "Migration-compatible tests that observe queued snapshot delivery rather than direct producer sends"
  - "Threading, retrigger, alias, and demo fixtures that drain SEND_OUTBOUND before asserting delivered state"
affects: [outbound-delivery, clarification, demo-fixtures, threading]

key-files:
  modified:
    - tests/conftest.py
    - tests/test_alias_write.py
    - tests/test_demo_fixtures.py
    - tests/test_demo_landing.py
    - tests/test_retrigger_epoch.py
    - tests/test_retrigger_threading.py
    - tests/test_threading.py

key-decisions:
  - "Producer tests fail if the obsolete gateway path is reached; they assert snapshot reservation and identifier-only job enqueueing instead."
  - "Fixture flows explicitly drain SEND_OUTBOUND before requiring a sent RFC threading anchor."
  - "The fake Resend fixture accepts the frozen snapshot adapter's idempotency options."

requirements-completed: [SEND-01, SEND-02, SEND-03]
status: complete
---

# Phase 20 Plan 12: Legacy Gateway Removal Summary

**The stale fixture layer now matches the immutable-snapshot, identifier-only durable delivery path and no longer expects a producer to call `gateway.send_outbound`.**

## Accomplishments

- Reworked alias and demo producer tests to reserve one snapshot and enqueue one send job while patching the old gateway symbol to fail if reached.
- Drained worker-owned clarification delivery before threading, reply, and fixture assertions that require a sent Message-ID.
- Migrated retrigger/threading proofs to inspect the worker's Resend payload and persisted immutable snapshot rather than a caller-supplied direct-send invocation.
- Updated the fake Resend seam for the snapshot adapter's idempotency-key options.

## Authorization and Deviation

The original plan listed four focused test files. The user explicitly authorized the bounded migration-compatible cleanup of stale direct-send assumptions outside that list. This update changed only directly affected test fixtures and compatibility seams:

- `tests/conftest.py`
- `tests/test_alias_write.py`
- `tests/test_demo_fixtures.py`
- `tests/test_demo_landing.py`
- `tests/test_retrigger_epoch.py`
- `tests/test_retrigger_threading.py`
- `tests/test_threading.py`

No production safety behavior changed.

## Commit

1. **Migrate stale delivery fixtures** — `2eaafb5`

## Verification

- `uv run pytest` focused stale alias failures — **4 passed**.
- `uv run pytest` focused demo producer failures — **2 passed**.
- `uv run pytest` focused threading and demo-fixture failures — **6 passed**.
- `uv run pytest` focused retrigger failures — **3 passed**.
- `uv run ruff check` on all seven changed test files — **passed**.
- `uv run mypy app/email/gateway.py app/pipeline/delivery.py app/pipeline/clarification.py` — **passed**.
- `uv run pytest tests/test_comment_provenance_guard.py -q` — **5 passed**.
- `git diff --check` — **passed**.

## Full-Suite Note

`uv run pytest -q` was started repeatedly, but this execution environment detached/terminated the child before returning a terminal summary. Its partial output contained no test failure; that is unavailable evidence, not a full-suite pass. The phase closeout gate still requires a terminal `uv run pytest -q` result in a stable runner.

---
*Phase: 20-exactly-once-send*
*Completed: 2026-07-17*
