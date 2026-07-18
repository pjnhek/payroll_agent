---
phase: 20-exactly-once-send
verified: 2026-07-18T03:46:57Z
status: gaps_found
score: 3/4 must-haves verified
behavior_unverified: 1
overrides_applied: 0
gaps:
  - truth: "A stale or deadline-expired confirmation delivery is escalated to purpose-aware operator review rather than silently retired or blindly replayed after Resend's deduplication window."
    status: failed
    reason: "CR-01 remains: `replay_window_closed` is converted to an unclassified OK no-op, then the exact lease is retired as invalid context. Separately, the real schema rejects the `authorization_expired` attempt category that the gateway-expiry settlement writes. Either path prevents the required durable delivery-review outcome."
    artifacts:
      - path: app/queue/handlers/send_outbound.py
        issue: "Lines 55-58 discard ProviderHandoffActive.reason, including replay_window_closed, as an unclassified OK result."
      - path: app/db/repo/job_settlement.py
        issue: "Lines 401-413 retire a no-handoff result as invalid context; lines 480-514 require an exact handoff before creating review."
      - path: app/db/schema.sql
        issue: "The outbound_delivery_attempts failure-category checks at lines 482 and 509-513 omit authorization_expired, although job_settlement.py emits it."
    missing:
      - "Map replay_window_closed to DELIVERY_AUTHORIZATION_EXPIRED (or an equally bounded distinct result) and settle its exact leased reservation directly into purpose-aware delivery review with zero provider calls."
      - "Allow authorization_expired in both fresh-schema and deployed-schema failure-category checks, and add production plus fake-parity regressions for pre-authorization and provider-boundary expiry."
behavior_unverified_items:
  - truth: "The durable provider-handoff fence prevents a post-authorization epoch bump from reaching the old snapshot gateway on real Postgres."
    test: "Run the two marker-selected provider_handoff queueproof tests with DATABASE_URL and ALLOW_DB_RESET=1 against a resettable Postgres database."
    expected: "The protected case performs one gateway call at epoch 0 after rejecting the separate epoch bump; the deliberately unfenced control observes epoch 1 at its gateway spy. Both run with zero skips."
    why_human: "The tests are collected but skipped locally because guarded database credentials are absent. Fake/unit checks cannot prove two-connection lock ordering."
---

# Phase 20: Exactly-Once Send Verification Report

**Phase Goal:** A client is sent at most one payroll confirmation per approved run, per epoch — a retry never redrafts, never regenerates non-deterministic bytes, and never silently orphans a reply into a phantom run.

**Verified:** 2026-07-18T03:46:57Z
**Status:** gaps_found
**Re-verification:** Yes — after Plans 20-17 through 20-25 gap closure

## Goal Achievement

### Observable Truths

| # | Roadmap must-have | Status | Evidence |
| --- | --- | --- | --- |
| 1 | A retry reuses the exact reserved Message-ID. | VERIFIED | `reserve_outbound_snapshot()` is a read-or-reserve operation over the epoch-scoped slot; `tests/test_send_idempotency.py::test_fake_reservation_reuses_the_original_provider_snapshot` passed. |
| 2 | A retry replays the persisted subject, body, and PDF bytes without redrafting or regeneration. | VERIFIED | `delivery.deliver()` returns to enqueue when a snapshot exists; `gateway.send_reserved_outbound_snapshot()` constructs Resend parameters only from the stored snapshot and attachments. `test_send_reserved_snapshot_replays_fixed_payload_and_idempotency_key` passed. |
| 3 | Every send uses a Message-ID-derived Resend idempotency key and retries remain bounded below retention. | VERIFIED | The gateway supplies `{"idempotency_key": message_id}` at `app/email/gateway.py:167`; handoff `not_after` is derived from `reserved_at + interval '20 hours'`; the final provider boundary rejects insufficient remaining time. |
| 4 | An ambiguous send is never blindly replayed beyond provider deduplication retention and instead enters human review. | FAILED (BLOCKER) | See CR-01 assessment below. A pre-provider expired reservation is collapsed to `ok/unknown/unclassified` and settled as invalid context; gateway-boundary expiry would emit `authorization_expired`, a value the real schema rejects. Neither path reliably reaches `needs_operator` delivery review. |

**Score:** 3/4 roadmap must-haves verified; 1 present-but-behavior-unverified real-Postgres concurrency invariant.

### CR-01 Assessment: confirmed

The review finding is correct and remains unresolved in the current implementation.

- `authorize_outbound_provider_handoff()` returns `ProviderHandoffActive("replay_window_closed")` for a reservation outside the 20-hour window (`app/db/repo/outbound_handoffs.py:275-276`).
- `handle_send_outbound()` then discards every active/no-snapshot outcome through `_bounded_noop()` (`app/queue/handlers/send_outbound.py:55-58`). An independent seam probe returned `ok unknown unclassified` for exactly that authorization outcome.
- Because no active handoff was created, `settle_outbound_delivery_job()` cannot satisfy `_lock_current_provider_handoff()` and retires the held job as `invalid_context` (`app/db/repo/job_settlement.py:401-413`), leaving the confirmation's approved state without the required delivery review.

There is also a second live-Postgres blocker on the related gateway-boundary-expiry path: `job_settlement._delivery_failure_category()` emits `authorization_expired` (`app/db/repo/job_settlement.py:161-162`), but both schema checks for `outbound_delivery_attempts.failure_category` omit that value (`app/db/schema.sql:482`, `509-513`). The fake-only expiry test passes because `InMemoryRepo` does not enforce the production check constraint; the production scripted-connection tests do not execute it against Postgres.

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `app/db/repo/emails.py` + `app/db/schema.sql` | Immutable snapshot, ordered attachment bytes, and logical epoch slot | VERIFIED | Append-only snapshot/attachment triggers and a conflict path that returns the stored record are substantive and used by delivery. |
| `app/pipeline/delivery.py` + `app/db/repo/jobs.py` | Approval creates one frozen snapshot and identifier-only durable job before wake | VERIFIED | `deliver()` reserves/enqueues in the caller transaction; it contains no provider call. |
| `app/email/gateway.py` | Frozen provider payload, Message-ID header/key, final deadline check | VERIFIED | The provider call is wired to frozen fields and stored key; focused replay and deadline tests passed. |
| `app/db/repo/outbound_handoffs.py` + `app/queue/handlers/send_outbound.py` | Exact job/snapshot/epoch authorization before provider work | VERIFIED (unit/fake evidence) | The handoff transaction locks job → snapshot/email → run → handoff; retrigger checks the active fence. Real-Postgres concurrency proof remains unavailable. |
| `app/db/repo/job_settlement.py` | Exact-owner retry/final/review settlement | FAILED | It has the intended exact-handoff path, but does not accept the pre-handoff expiry outcome and can write a category prohibited by the production schema. |
| `tests/test_queue_durability.py` | Non-vacuous two-connection provider-handoff proof and unsafe control | PRESENT_BEHAVIOR_UNVERIFIED | Both tests collect, but both skip without `DATABASE_URL` and `ALLOW_DB_RESET=1`; this is not a passing real-Postgres proof. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| Approval/delivery | durable send job | caller-owned snapshot reservation then `enqueue_job`, post-commit wake | WIRED | The provider is absent from `delivery.deliver()`. |
| Send handler | durable authority → frozen gateway request | `authorize_outbound_provider_handoff()` then `send_reserved_outbound_snapshot()` | WIRED | Valid authorization sends only its snapshot; record-only is provider-free. |
| Gateway | Resend | stored Message-ID in header and `idempotency_key` | WIRED | Focused frozen-payload/idempotency test passed. |
| Handler/drain | exact settlement | `drain_once()` forwards the handler's bounded result to `settle_outbound_delivery_job()` | PARTIAL / BLOCKED | `replay_window_closed` loses its bounded reason before this link, so the review settlement is unreachable. |
| Gateway expiry | delivery review ledger | `DELIVERY_AUTHORIZATION_EXPIRED` → attempt category → review | NOT WIRED IN PRODUCTION | The result is mapped, but the database constraint rejects `authorization_expired`. |

### Requirements Coverage

| Requirement | Status | Evidence |
| --- | --- | --- |
| SEND-01 — reuse reserved Message-ID | SATISFIED | Immutable epoch-scoped read-or-reserve snapshot; focused original-snapshot test passed. |
| SEND-02 — replay persisted payload, never rederive it | SATISFIED | Snapshot-only gateway and delivery replay branch; focused byte-equivalent gateway test passed. |
| SEND-03 — Idempotency-Key and bounded retry with stale sends escalated to human | BLOCKED | Key and nominal deadline bound exist, but both pre-provider and boundary-expiry review transitions are broken as described above. |

No Phase-20 requirement is orphaned: all three SEND IDs are claimed by one or more Phase-20 plans.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Frozen snapshot/Message-ID replay | Six focused Phase-20 tests covering reservation, frozen gateway replay, expiry review, handoff deadline, fake expiry, and retrigger fence | 6 passed | PASS |
| Static quality | `uv run ruff check ...` and `uv run mypy` | Ruff clean; 161 source files type-clean | PASS |
| Real provider-handoff race proof selection | `uv run pytest tests/ -m queueproof --collect-only -q` | Both protected/control tests collected | PASS (collection only) |
| Real provider-handoff race execution | `uv run pytest -q tests/test_queue_durability.py -m 'integration and queueproof' -k provider_handoff -rs` | 2 skipped; `DATABASE_URL` or `ALLOW_DB_RESET=1` absent | SKIPPED — unavailable evidence, not a pass |
| Pre-provider expiry reason preservation | Isolated handler seam with `ProviderHandoffActive('replay_window_closed')` | Returned `ok unknown unclassified` | FAIL |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- |
| `app/queue/handlers/send_outbound.py` | 55-58 | Bounded reason discarded into generic successful no-op | BLOCKER | Silently retires an expired confirmation without operator review. |
| `app/db/schema.sql` | 482; 509-513 | Result vocabulary and DB check constraint drift | BLOCKER | A real authorization-expiry review transaction rolls back on its attempt-ledger insert. |

## Human Verification Required

1. Run the guarded two-connection Postgres proof with reset-authorized credentials. The two skipped local tests are explicitly **not** proof that lock ordering and epoch fencing work in a real database.

2. After fixing the blockers, inspect both confirmation and clarification delivery-review cards in a browser. Verify frozen evidence is visible, confirmation alone offers typed new-confirmation authorization, clarification has only its purpose-specific actions, and neither exposes raw provider diagnostics or generic alias resolution.

## Gaps Summary

Phase 20's core immutable-replay, idempotency-key, and provider-handoff design is substantively implemented. It cannot be accepted because its required safe outcome after deduplication expiry is not durable: the CR-01 initial-expiry path is treated as invalid context, and the gateway-boundary-expiry path has a production schema vocabulary mismatch. Fix both routes to purpose-aware delivery review and add a real-Postgres regression for each. Then run the already-collected guarded two-connection proof with credentials; its current skips remain a warning rather than a passing claim.

---

_Verified: 2026-07-18T03:46:57Z_
_Verifier: the agent (generic-agent workaround for gsd-verifier)_
