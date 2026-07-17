---
phase: 20-exactly-once-send
plan: 15
subsystem: testing
tags: [in-memory-repository, exactly-once, outbound-delivery, fake-parity, queue]

# Dependency graph
requires:
  - phase: 20-05
    provides: immutable outbound snapshot and delivery identity seams
  - phase: 20-12
    provides: snapshot-backed SEND_OUTBOUND queue execution
  - phase: 20-13
    provides: production settlement replay allowlist and final-lease review behavior
  - phase: 20-14
    provides: current-epoch routing, body-free review projection, and fail-closed state mutation
provides:
  - production-parity InMemoryRepo SEND_OUTBOUND validation, deduplication, and attempt budget
  - append-only fake delivery evidence with bounded review projections
  - fake replay, final-lease, epoch-routing, clarification-retry, and legacy-mutation safety proofs
affects: [phase-20, phase-21, ordinary-test-evidence, durable-send]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - fake delivery review counts derive from append-only bounded attempt facts
    - fake outbound replay uses the exact four-reason production allowlist
    - fake repository facades register every production method by exact name

key-files:
  created:
    - tests/test_phase20_fake_parity.py
    - .planning/phases/20-exactly-once-send/20-15-SUMMARY.md
  modified:
    - tests/conftest.py

decisions:
  - "SEND_OUTBOUND fake jobs require only run_id and email_id, use send_outbound:{email_id}, and always store max_attempts=8."
  - "Only delivery timeout, connection failure, rate limit, and provider 5xx reasons schedule automatic fake replay; every other retryable reason enters review."
  - "Clarification delivery review retry advances the existing pending row only after purpose, review ownership, reservation age, and reserved-state checks."

metrics:
  duration: 35min
  completed: 2026-07-17
  tasks: 2
  files_changed: 2
status: complete
---

# Phase 20 Plan 15: InMemoryRepo SEND_OUTBOUND Parity Summary

The ordinary-test fake now mirrors the production outbound safety contract: malformed send jobs fail before mutation, valid jobs use the exact dedup identity and eight-attempt ladder, delivery evidence is append-only, and replay/review decisions preserve purpose, epoch, and frozen-content boundaries.

## Accomplishments

- Added strict `SEND_OUTBOUND` enqueue validation, duplicate no-op behavior, identifier-only storage, and fixed `max_attempts=8`.
- Added a bounded in-memory delivery-attempt ledger; review projections derive `attempt_count` from it and omit `body_text` while the frozen snapshot reader retains the body.
- Matched production’s exact four-reason automatic replay allowlist and direct-review behavior for every other `PipelineReason`.
- Added purpose-aware final lease reaping for confirmation, clarification, and clarification-field-regression sends, preserving the reservation and entering the correct operator review reason/detail.
- Added and registered `advance_existing_clarification_delivery_review_job_due_now`, with same-row, open-window, reserved-state, and review-ownership checks.
- Proved current-epoch reply routing, late-reply observability, and fail-closed legacy email-state mutation in the fake.

## Task Commits

1. **Task 1 RED: add fake send enqueue parity regressions** — `16cfc26`
2. **Task 1 GREEN: mirror fake outbound enqueue contract** — `b8972d3`
3. **Task 2 RED: add fake delivery safety regressions** — `5b7ab69`
4. **Task 2 GREEN: complete fake outbound delivery parity** — `928a735`

## Verification

- `uv run pytest -q tests/test_phase20_fake_parity.py tests/test_repo_jobs_sql.py tests/test_job_kind_drift.py tests/test_send_idempotency.py tests/test_clarify.py tests/test_dashboard.py` — **227 passed, 5 skipped**.
- `uv run ruff check tests/conftest.py tests/test_phase20_fake_parity.py` — **passed**.
- `uv run mypy tests/conftest.py` — **passed**.
- `uv run pytest -q -m 'integration and queueproof' tests/test_send_idempotency.py tests/test_queue_durability.py` — **48 skipped, 27 deselected**; no configured live database evidence.

## Unavailable Evidence

The guarded Postgres queueproof tests were unavailable because `DATABASE_URL` and `ALLOW_DB_RESET=1` were not configured. The skips are not reported as successful database verification; the ordinary fake-backed evidence is separate.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

- `tests/conftest.py:638` contains the pre-existing word “placeholder” in an intentional stable business-name fallback for unrelated in-memory dashboard tests. It is not part of the SEND_OUTBOUND fake and does not affect this plan’s goal.

## Threat Surface

No new network endpoint, authentication path, file-access pattern, or schema/trust-boundary surface was introduced. The changes strengthen the planned fake-repository mitigations for malformed queue context, replay safety, attempt evidence, stale epochs, final leases, and body disclosure.

## Self-Check: PASSED

- Summary file exists at the expected phase path.
- Task commits `16cfc26`, `b8972d3`, `5b7ab69`, and `928a735` are present in git history.
- Summary diff check passed.
- `.planning/STATE.md` remains the orchestrator’s pre-existing unstaged modification; `.planning/ROADMAP.md` was not changed or staged.
