---
phase: 20-exactly-once-send
verified: 2026-07-18T17:39:00Z
status: passed
score: 4/4 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 3/4
  gaps_closed:
    - "Replay-window expiry is preserved as DELIVERY_AUTHORIZATION_EXPIRED and settles directly into purpose-aware review without provider I/O."
    - "Fresh and deployed outbound-delivery attempt constraints both admit authorization_expired, proven against a repaired legacy PostgreSQL constraint."
    - "The guarded two-connection provider-handoff proof executed with zero skips after its transaction-boundary repair."
  gaps_remaining: []
  regressions: []
---

# Phase 20: Exactly-Once Send Verification Report

**Phase Goal:** A client is sent at most one payroll confirmation per approved run, per epoch — a retry never redrafts, never regenerates non-deterministic bytes, and never silently orphans a reply into a phantom run.

**Verified:** 2026-07-18T17:39:00Z
**Status:** passed
**Re-verification:** Yes — after Plans 20-26 and 20-27 closed the prior delivery-expiry and live-evidence gaps.

## Goal Achievement

### Observable Truths

| # | Roadmap must-have | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Retrying after a crash reuses the exact reserved Message-ID; it is never overwritten. | ✓ VERIFIED | `reserve_outbound_snapshot()` is read-or-reserve over the epoch-scoped logical slot, while immutable snapshot/attachment rows have database append-only triggers. The focused suite passed `126 passed, 6 skipped`; its reservation and mutation tests cover the stored identity rather than a newly generated retry value. |
| 2 | Retrying replays the exact persisted subject, body, and PDF bytes; it never redrafts or regenerates them. | ✓ VERIFIED | `delivery.deliver()` creates content only on an absent snapshot and enqueues by identifier; `send_reserved_outbound_snapshot()` builds the provider payload only from the stored snapshot and attachment bytes. `test_send_reserved_snapshot_replays_fixed_payload_and_idempotency_key` is in the passing focused suite. |
| 3 | Every send carries a Message-ID-derived idempotency key and automatic replay is bounded below provider retention. | ✓ VERIFIED | The gateway supplies `{"idempotency_key": message_id}` and performs its final deadline comparison immediately before provider I/O. Handoff `not_after` comes from immutable `reserved_at + interval '20 hours'`; classified delivery results allow only the explicit replayable set before that window. |
| 4 | A send that may have reached Resend is never blindly replayed past deduplication retention; it enters human review. | ✓ VERIFIED | The handler preserves `replay_window_closed` as `DELIVERY_AUTHORIZATION_EXPIRED`; pre-provider settlement accepts that single no-handoff terminal result only when the reservation window is closed and writes purpose-aware review. Both fresh DDL and the deployed repair enumerate `authorization_expired`; real-Postgres tests cover legacy-constraint repair, pre-provider expiry, and gateway-boundary expiry. The recorded authorized command passed all 9 selected tests with zero skips. |

**Score:** 4/4 roadmap truths verified.

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- |
| `app/db/schema.sql` | Immutable snapshot/attachment evidence and identical fresh/deployed bounded attempt-category vocabulary | ✓ VERIFIED | Fresh `outbound_delivery_attempts.failure_category` and the idempotent repair both include the same `authorization_expired` category; append-only triggers remain installed. Static parity test and real legacy-CHECK repair prove both paths. |
| `app/db/repo/emails.py`, `app/pipeline/delivery.py` | Read-or-reserve frozen payload and identifier-only scheduling | ✓ VERIFIED | The conflict path returns the existing snapshot; composition/PDF generation occurs only when no snapshot exists, and the durable job contains identifiers rather than provider payload. |
| `app/db/repo/outbound_handoffs.py`, `app/queue/handlers/send_outbound.py` | Exact durable authority before gateway I/O | ✓ VERIFIED | Authorization locks the leased job, frozen snapshot, run generation, and active handoff in order; only a valid authorization reaches the frozen gateway. Expired pre-authorizations return the bounded terminal result without creating provider authority. |
| `app/db/repo/job_settlement.py` | Exact-owner settlement, durable review at expiry, and no stale lease mutation | ✓ VERIFIED | Settlement permits only the specifically fenced pre-provider expiry path without a handoff; all ordinary success/retry/review paths require the matching active handoff. It appends a PII-safe attempt fact, transitions to the purpose-specific review state, and completes the exact lease. |
| `tests/test_queue_durability.py` | Guarded real-Postgres repair, expiry, and two-connection handoff proof | ✓ VERIFIED | Nine marker-selected tests are currently collected. The authorized resettable-Postgres execution recorded in `.planning/debug/handoff-live-proof-fail.md` reports `9 passed, 49 deselected` with zero skips after repairing the test transaction boundary. |
| `.github/workflows/concurrency-proof.yml` | CI execution of all queueproof-marked real-Postgres tests with zero-skip guard | ✓ VERIFIED | The marker-selected queueproof step runs `uv run pytest tests/ -m queueproof -v -rs`; it fails CI on any skip or on absence of passed tests, so the live proof cannot silently opt out. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- |
| Approval / clarification producer | Frozen snapshot and durable send job | Caller-owned reserve-or-load transaction followed by identifier-only enqueue and post-commit wake | WIRED | No producer-side provider-send path remains after the legacy gateway removal. |
| Send handler | Provider handoff → frozen gateway request | `authorize_outbound_provider_handoff()` followed by `send_reserved_outbound_snapshot()` | WIRED | The handler rejects invalid, record-only, stale, closed-window, and unrelated-authority outcomes before gateway entry; its closed-window mapping is specifically tested. |
| Gateway | Resend | Frozen headers/attachment bytes plus `idempotency_key=message_id` | WIRED | The gateway performs no content composition and returns `DELIVERY_AUTHORIZATION_EXPIRED` before I/O at the fixed deadline boundary. |
| Handler / drain | Exact settlement | Handler's bounded result is settled against current leased job, snapshot, run epoch, and (where present) handoff | WIRED | The direct pre-provider expiry exception is limited to a closed replay window with no active handoff; all other no-handoff outcomes are invalid context. |
| Schema bootstrap | Durable expiry review ledger | Fresh CREATE constraint and non-reset repair use one category vocabulary | WIRED | `test_deployed_schema_repair_accepts_authorization_expired` replaces the live CHECK, calls production `bootstrap(reset=False)`, inspects `pg_constraint`, and executes a real constrained INSERT. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Immutable snapshot replay, gateway payload, fake/production parity | `uv run pytest -q tests/test_send_idempotency.py tests/test_gateway.py tests/test_phase20_fake_parity.py` | `126 passed, 6 skipped` | ✓ PASS |
| Queueproof selection | `uv run pytest tests/ -m queueproof --collect-only -q \| rg 'authorization_expired\|deployed_schema_repair\|test_provider_handoff_(blocks_epoch_bump_before_gateway\|race_control_observes_stale_gateway_when_fence_is_released)'` | All 9 required repair, expiry, protected-race, and deliberately unsafe-control tests collected | ✓ PASS |
| Phase-20 Python quality | `uv run ruff check app/db/repo/emails.py app/db/repo/outbound_handoffs.py app/db/repo/job_settlement.py app/queue/handlers/send_outbound.py app/email/gateway.py app/pipeline/delivery.py tests/test_send_idempotency.py tests/test_queue_durability.py tests/test_gateway.py tests/test_phase20_fake_parity.py` | `All checks passed!` | ✓ PASS |
| Static type check | `uv run mypy` | `Success: no issues found in 161 source files` | ✓ PASS |
| Real schema/expiry/handoff behavior | `DATABASE_URL="$DATABASE_URL" ALLOW_DB_RESET=1 uv run pytest -q tests/test_queue_durability.py -m 'integration and queueproof' -k 'authorization_expired or deployed_schema_repair or provider_handoff' -rs` | Recorded authorized execution: `9 passed, 49 deselected in 31.68s`, zero skips | ✓ PASS (recorded live evidence) |

The verifier did not re-run the destructive command: this process has no `DATABASE_URL`. That absence is recorded as unavailable, not a passing rerun; it does not invalidate the post-fix authorized result above, which is documented with its diagnosis and exact output in `.planning/debug/handoff-live-proof-fail.md`.

### Requirements Coverage

| Requirement | Source plans | Status | Evidence |
| --- | --- | --- | --- |
| SEND-01 — retry reuses the reserved Message-ID | 20-01, 20-04/05, 20-17/18, 20-21/23/25 | SATISFIED | Immutable logical slot and frozen snapshot preserve the original ID; current-epoch lookup and the real protected/control handoff proof prevent a stale epoch from sending its old snapshot. |
| SEND-02 — retry replays persisted payload and never rederives it | 20-01, 20-03/04/05, 20-07, 20-10/12 | SATISFIED | Provider adapter consumes only stored envelope and bytes; current/YTD/PDF generation is absent from replay paths, with focused payload equivalence tests passing. |
| SEND-03 — idempotency key, bounded replay, stale-send escalation | 20-02/03/09, 20-13, 20-21/22/24/26/27 | SATISFIED | Stored ID is used as the Resend key, replay is constrained by the reservation-derived deadline, and both expiry boundaries append `needs_operator/authorization_expired` then enter purpose-aware review in real PostgreSQL. |

All three Phase-20 requirement IDs are claimed by the plans and mapped in `.planning/REQUIREMENTS.md`; no Phase-20 requirement is orphaned.

### Anti-Patterns Found

No blocker debt markers (`TBD`, `FIXME`, or `XXX`) were found in the Phase-20 production or test files. Occurrences of “placeholder”/“not available” are explanatory test/template wording or the intentional safe review message, not incomplete implementation.

### Disconfirmation Pass

- **Prior partial requirement:** the previous report correctly found the closed replay window collapsed into a generic no-op and the live schema rejected `authorization_expired`. The handler now preserves the typed reason, settlement has a narrowly fenced direct review path, and a real legacy-CHECK repair test proves the deployed database accepts it.
- **Prior misleading test risk:** fake parity could not prove a production `CHECK` constraint. The live proof now modifies a resettable database to the legacy constraint, invokes production non-reset bootstrap, examines PostgreSQL's catalog, and inserts the real bounded category.
- **Prior uncovered error path:** the two-connection test had an implicit transaction before its intended authorization transaction, so the handoff was uncommitted. The control case was retained deliberately and now observes the forbidden epoch-1 gateway condition only when its fence is manually released; the protected case blocks the bump and sees epoch 0. The post-fix authorized run covers both.

## Gaps Summary

None. The re-verification closed the prior expiry-settlement and real-Postgres evidence gaps. Phase 20 achieves its narrower, honest guarantee: it prevents duplicate automatic confirmation sends per approved run/epoch through immutable payloads, provider idempotency, bounded replay, exact authority, and human review for ambiguity. It does not claim exactly-once delivery.

---

_Verified: 2026-07-18T17:39:00Z_
_Verifier: the agent (generic-agent workaround for gsd-verifier)_
