---
phase: 20
slug: exactly-once-send
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-17
---

# Phase 20 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (managed by uv) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/test_send_idempotency.py tests/test_delivery.py -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | under 60 seconds for hermetic tests; live-Postgres queueproofs depend on configured database guard |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_send_idempotency.py tests/test_delivery.py -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `$gsd-verify-work`:** Full suite must be green; queueproof coverage must distinguish an unavailable local database from a pass.
- **Max feedback latency:** 60 seconds for hermetic checks

---

## Per-Requirement Verification Map

| Requirement | Secure behavior to prove | Test type | Automated command | Existing coverage | Status |
|-------------|--------------------------|-----------|-------------------|-------------------|--------|
| SEND-01 | A retry retains the original reserved Message-ID and no conflict path overwrites the logical send slot. | Unit + live-Postgres integration | `uv run pytest tests/test_send_idempotency.py -q` | Extend existing idempotency tests | ⬜ pending |
| SEND-02 | A replay reads one frozen subject/body/recipient/attachment-byte snapshot and never calls drafting or PDF generation. | Unit + integration | `uv run pytest tests/test_delivery.py tests/test_send_idempotency.py -q` | Extend existing delivery/idempotency tests | ⬜ pending |
| SEND-03 | Every provider call uses the reserved Message-ID-derived key; only classified transient failures reschedule before reservation age 20h, and ambiguity escalates safely. | Unit + queue integration + live-Postgres proof | `uv run pytest tests/test_delivery.py tests/test_send_idempotency.py -q` | Extend queue and delivery tests; add non-vacuity proof | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

## Planned Execution Coverage

All 51 planned implementation tasks include an automated verification command. Plan
20-27 also contains one blocking human-verify task for guarded live-Postgres evidence.
The implementation-task count includes Plans 20-26 and 20-27; the blocking checkpoint
is not implementation work and cannot be inferred from a skipped test. The
phase plan structure has been checked for task completeness, wave ordering, and
sampling continuity; these are planning facts, not evidence that the commands have
already passed.

| Wave | Plans | Feedback contract |
|------|-------|-------------------|
| 1–3 | 20-01, 20-02, 20-03 | Snapshot/schema, job vocabulary, and additive gateway checks remain focused and hermetic. |
| 4–6 | 20-09, 20-05, 20-11, 20-04, 20-10 | Queueproof/fencing and producer migration checks run before either live producer uses the new handler. |
| 7 | 20-06, 20-12 | Delivery-review regression checks plus the full `uv run pytest -q` no-bypass gate. |
| 8 | 20-07, 20-08 | YTD and eval polish remain isolated behind snapshot-safety regression checks. |
| 9 | 20-15 | Fake parity, repository SQL, and no-bypass regressions; guarded queueproof skips remain unavailable evidence. |
| 10 | 20-16 | Clarification review isolation, frozen evidence, typed actions, and browser-ready review contracts. |
| 11 | 20-17 | SEND-01 current-epoch sent-proof SQL and guarded epoch regression. |
| 12 | 20-18 | Epoch fencing before provider work and locked settlement/reaper no-write regressions; durable outcome mapping is deferred to 20-19. |
| 13 | 20-19 | Sole owner of LOST_LEASE/INVALID_CONTEXT, exact-token stale-epoch retirement, and drain token bookkeeping. |
| 14 | 20-20 | Confirmation-only route/repository/fake checks plus final ruff, bare mypy, bare full-suite, and guarded integration/queueproof evidence. |
| 15 | 20-21 | Handoff schema/repository authority tests establish the immutable reservation-derived `not_after` deadline, retain predecessor lease expiry, and prove only a reclaimed exact current lease can atomically adopt the matching active handoff without changing snapshot, epoch, `authorized_at`, or deadline. |
| 16 | 20-22 | Gateway/handler regression verifies the handler uses the authorizer's reclaimed matching-handoff result rather than a foreign-active no-op; equality at `not_after - 15 seconds` rejects with zero Resend I/O, while only a strictly earlier clock can send through the fixed 10-second synchronous transport. |
| 17 | 20-24 | Production and InMemoryRepo parity verify that timeout/5xx settlement exact-owner-releases the active handoff into retry history before rescheduling, then a due new lease reauthorizes and replays one original frozen snapshot/Message-ID under its reservation-derived deadline while the former token cannot settle or release; record-only, expired-authorization, and crash-after-authorization adoption remain covered. |
| 18 | 20-25 | Generic retrigger rollback and the D-09/D-11 review-only paths verify epoch changes cannot cross an active handoff. |
| 19 | 20-23 | The barrier-driven real-Postgres queueproof verifies protected and deliberately unsafe provider/epoch interleavings. |
| 20 | 20-26 | The bounded pre-provider replay-window-expired result is preserved and settled through exact, purpose-aware delivery review without provider I/O; production/fake parity remains hermetic evidence only. |
| 21 | 20-27 | Fresh/deployed schema-category parity, legacy-CHECK repair, and both expiry boundaries are proved on guarded Postgres; the blocking task also requires zero-skip execution of the protected/control provider-handoff proof. |

---

## Closure Plan Verification Commands

The closure plans 20-17 through 20-20 retain task-level verification and add the
following final evidence. A guarded database result with missing configuration is
reported as unavailable evidence, never as a passing queueproof.

| Plan | Task | Automated verification |
|------|------|------------------------|
| 20-17 | 1 | `uv run pytest -q tests/test_send_idempotency.py` |
| 20-17 | 2 | `uv run pytest -q tests/test_send_idempotency.py tests/test_delivery.py` |
| 20-18 | 1 | `uv run pytest -q tests/test_queue_durability.py tests/test_send_idempotency.py` |
| 20-18 | 2 | `uv run pytest -q tests/test_phase20_fake_parity.py tests/test_send_idempotency.py tests/test_clarify.py` |
| 20-19 | 1 | `uv run pytest -q tests/test_queue_durability.py tests/test_queue_drain.py` |
| 20-19 | 2 | `uv run pytest -q tests/test_queue_drain.py tests/test_queue_durability.py` |
| 20-20 | 1 | `uv run pytest -q tests/test_phase20_clarification_review.py tests/test_repo_jobs_sql.py tests/test_dashboard.py` |
| 20-20 | 2 | `uv run pytest -q tests/test_phase20_clarification_review.py tests/test_phase20_fake_parity.py tests/test_repo_jobs_sql.py tests/test_send_idempotency.py tests/test_queue_durability.py tests/test_queue_drain.py`; `uv run ruff check app/routes/runs.py app/db/repo/jobs.py app/db/repo/job_settlement.py app/db/repo/emails.py app/queue/handlers/send_outbound.py app/queue/drain.py tests/conftest.py tests/test_phase20_clarification_review.py tests/test_phase20_fake_parity.py tests/test_repo_jobs_sql.py tests/test_send_idempotency.py tests/test_queue_durability.py tests/test_queue_drain.py`; `uv run mypy`; `uv run pytest -q`; `uv run pytest -q -m 'integration and queueproof' tests/test_send_idempotency.py tests/test_queue_durability.py tests/test_queue_drain.py tests/test_threading.py`. |
| 20-21 | 1 | `uv run pytest -q tests/test_send_idempotency.py tests/test_repo_jobs_sql.py`; `uv run ruff check app/db/schema.sql app/db/repo/outbound_handoffs.py app/db/repo/__init__.py tests/test_send_idempotency.py` |
| 20-21 | 2 | `uv run pytest -q tests/test_send_idempotency.py tests/test_repo_jobs_sql.py`; `uv run ruff check app/db/repo/outbound_handoffs.py app/db/repo/__init__.py tests/test_send_idempotency.py`; `uv run mypy` |
| 20-22 | 1 | `uv run pytest -q tests/test_gateway.py tests/test_delivery.py tests/test_queue_durability.py` (including strict-deadline equality rejection and strictly-earlier send); `uv run ruff check app/queue/handlers/send_outbound.py app/email/gateway.py app/pipeline/result.py tests/test_gateway.py`; `uv run mypy` |
| 20-24 | 1 | `uv run pytest -q tests/test_phase20_fake_parity.py tests/test_queue_durability.py tests/test_queue_drain.py` (including timeout/5xx release → reschedule → new lease → original snapshot replay and old-token fencing in production/fake parity); `uv run ruff check app/db/repo/job_settlement.py tests/conftest.py tests/test_phase20_fake_parity.py tests/test_queue_durability.py`; `uv run mypy`; `DATABASE_URL="$DATABASE_URL" ALLOW_DB_RESET=1 uv run pytest -q tests/test_queue_durability.py -m 'integration and queueproof' -k handoff` |
| 20-25 | 1 | `uv run pytest -q tests/test_retrigger_epoch.py tests/test_phase20_clarification_review.py tests/test_delivery.py`; `uv run ruff check app/db/repo/pipeline_state.py app/routes/runs.py tests/test_retrigger_epoch.py tests/test_phase20_clarification_review.py`; `uv run mypy` |
| 20-23 | 1 | `uv run pytest tests/ -m queueproof --collect-only -q | rg 'test_provider_handoff_(blocks_epoch_bump_before_gateway|race_control_observes_stale_gateway_when_fence_is_released)'` |
| 20-23 | 2 | `DATABASE_URL="$DATABASE_URL" ALLOW_DB_RESET=1 uv run pytest -q tests/test_queue_durability.py -m 'integration and queueproof' -k provider_handoff -rs` |
| 20-26 | 1 | `uv run pytest -q tests/test_gateway.py -k 'replay_window_closed or authorization_expired or send_handler'` |
| 20-26 | 2 | `uv run pytest -q tests/test_phase20_fake_parity.py tests/test_send_idempotency.py tests/test_gateway.py` |
| 20-27 | 1 | `uv run pytest -q tests/test_send_idempotency.py -k 'outbound_snapshot_schema or authorization_expired or delivery_settlement'` |
| 20-27 | 2 | `DATABASE_URL="$DATABASE_URL" ALLOW_DB_RESET=1 uv run pytest -q tests/test_queue_durability.py -m 'integration and queueproof' -k 'authorization_expired or deployed_schema_repair or provider_handoff' -rs` |
| 20-27 | 3 (blocking) | On a disposable/resettable PostgreSQL target only, set a nonempty `DATABASE_URL` and `ALLOW_DB_RESET=1`, then run `DATABASE_URL="$DATABASE_URL" ALLOW_DB_RESET=1 uv run pytest -q tests/test_queue_durability.py -m 'integration and queueproof' -k 'authorization_expired or deployed_schema_repair or provider_handoff' -rs`; every selected test must pass with zero skips. |

Final quality commands required by Plan 20 are the bare `uv run mypy`, bare
`uv run pytest -q`, the listed `uv run ruff check`, and the guarded
`integration and queueproof` commands. Plan 20-27 is the blocking fresh/deployed
schema-repair and live-Postgres closure gate:
`DATABASE_URL="$DATABASE_URL" ALLOW_DB_RESET=1 uv run pytest -q tests/test_queue_durability.py -m 'integration and queueproof' -k 'authorization_expired or deployed_schema_repair or provider_handoff' -rs`.
Run it only against a disposable/resettable database. A missing or empty
`DATABASE_URL`, an `ALLOW_DB_RESET` value other than `1`, any selected-test skip, or any
failure is unavailable or failed evidence—not a pass—and leaves the checkpoint and
Phase 20 behavior-unverified item open. With the guarded environment present, every
selected test must pass with zero skips, including the deliberately unsafe control.

---

## Wave 0 Requirements

- [ ] Add/extend hermetic tests for immutable snapshot reservation, frozen attachment bytes, Resend error classification, and typed delivery-review actions.
- [ ] Add/extend a real-Postgres queueproof for one fenced identifier-only send job and the 20-hour cutoff; skipped DB checks are unavailable evidence, not passes.
- [ ] Keep `tests/test_send_idempotency.py` and `tests/test_delivery.py` as the focused regression entry points.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Resend acceptance and provider-side replay within its idempotency window | SEND-03 | Requires real provider credentials and must not send a payroll email during automated tests. | Use a dedicated non-client recipient and a frozen fixture snapshot; verify the provider receives the same key and returns the cached result for a matching replay. |
| Operator comprehension of the delivery-review card and duplicate-send acknowledgement | SEND-03 | Exact wording and display safety need a browser review beyond route assertions. | Open a `needs_operator` fixture, confirm raw provider dumps are absent, then verify `Mark delivered` and the exact typed acknowledgement gate independently. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verification or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verification
- [x] Wave 0/planning coverage identifies the SEND-01 through SEND-03 evidence paths
- [x] No watch-mode flags
- [x] Feedback latency under 60 seconds for hermetic checks
- [x] `nyquist_compliant: true` set in frontmatter after plans define task IDs

`wave_0_complete` remains `false`: none of this planned evidence has been executed yet.

**Approval:** pending
