---
phase: 20-exactly-once-send
verified: 2026-07-17
status: gaps_found
score: "29/32 must-haves verified; 2 failed; 1 uncertain"
requirements:
  - id: SEND-01
    status: verified_with_phase_blocker
  - id: SEND-02
    status: verified_with_phase_blocker
  - id: SEND-03
    status: verified_with_phase_blocker
gaps:
  - severity: blocker
    truth: "A stale epoch must be unable to reach Resend after an operator retrigger."
    remediation: "Add a durable provider-handoff fence that serializes the exact leased job, snapshot epoch, and run epoch with clear_reply_context, then prove the after-preflight epoch-bump interleaving cannot invoke the gateway."
  - severity: warning
    truth: "Database lock ordering and epoch fencing must be exercised with genuine concurrent Postgres connections."
    remediation: "Run the guarded queueproof/live-Postgres tests with DATABASE_URL and ALLOW_DB_RESET=1 after the blocker is fixed."
---

# Phase 20 Verification

## Goal assessment

**Verdict: FAILED — phase completion is not authorized.**

The immutable reservation, frozen replay payload, Resend idempotency key, bounded replay ladder, and review escalation are implemented and exercised. However, the current-epoch authorization check is a non-atomic preflight. A retrigger can increment `reply_epoch` after that read and before the provider request, allowing an obsolete epoch to send. Settlement notices the epoch later, but cannot undo the external email.

## Roadmap success criteria

| Criterion | Status | Evidence |
|---|---|---|
| Retry retains the reserved `message_id` | VERIFIED | `reserve_outbound_snapshot()` locks/returns the established logical slot without applying retry arguments; `test_fake_reservation_reuses_the_original_provider_snapshot` exercises original-ID replay. |
| Retry replays original subject, body, and PDF bytes | VERIFIED | Handler loads the frozen snapshot only; gateway constructs the request from its persisted fields/attachments; `test_send_reserved_snapshot_replays_fixed_payload_and_idempotency_key` exercises byte-equivalent replay. |
| Every call carries a Message-ID-derived Resend key; ladder stays within retention | VERIFIED | `gateway.send_reserved_outbound_snapshot()` passes `{"idempotency_key": message_id}`; `delivery_replay_allowed()` and `next_delivery_attempt_at()` enforce the reservation-time 20-hour bound. Gateway/result/settlement tests passed. |
| Ambiguous timeout/5xx outcomes never auto-replay beyond retention | VERIFIED | `settle_outbound_delivery_job()` permits only timeout, connection, rate-limit, and server-failure reasons while the reservation window remains open; otherwise it writes purpose-specific operator review. Focused settlement tests passed. |

## Truth-by-truth evidence

| # | Plan must-have / wiring truth | Status | Evidence |
|---:|---|---|---|
| 1 | Provider envelope and ordered attachment bytes persist before provider work | VERIFIED | Immutable snapshot/attachment schema plus producer reserve-and-enqueue path; Phase-20 regression suite passed. |
| 2 | Same-slot reservation cannot overwrite Message-ID, headers, recipient, body, or bytes | VERIFIED | `reserve_outbound_snapshot()` reads/locks existing slot; immutable replay test passed. |
| 3 | Logical run/purpose/round/epoch slot retains one Message-ID | VERIFIED | Epoch-scoped uniqueness/read-or-reserve and current-epoch sent-proof regression passed. |
| 4 | Send work is an identifier-only durable job, not a route provider call | VERIFIED | `SEND_OUTBOUND` queue context plus fail-closed legacy gateway; queue and gateway tests passed. |
| 5 | Automatic and operator retry reopen the same eligible job, not a new job | VERIFIED | Existing-job-only due-now repository operations and fake/SQL tests passed. |
| 6 | Snapshot gateway sends only persisted fields and original idempotency key | VERIFIED | Gateway replay test captured two identical provider requests and the stored key. |
| 7 | Only classified timeout/connection/rate-limit/5xx outcomes auto-replay | VERIFIED | Exact allowlist in settlement; unsafe-category regressions passed. |
| 8 | Replay age is anchored to `reserved_at`, capped before 20 hours | VERIFIED | Result and settlement cutoff tests passed. |
| 9 | Handler cannot draft or regenerate PDF on replay | VERIFIED | Handler calls only `load_outbound_snapshot()` then snapshot gateway; delivery/queue tests exercise frozen snapshot use. |
| 10 | Payload mismatch is terminal review, never a replacement send | VERIFIED | Gateway classification and settlement review tests passed. |
| 11 | Composition/YTD/PDF work is absent when a snapshot already exists | VERIFIED | `delivery.deliver()` returns to enqueue path before composition; delivery/PDF tests passed. |
| 12 | Allowed replay keeps a confirmation approved until delivery outcome settles | VERIFIED | Same-job reschedule path and settlement regression passed. |
| 13 | Snapshot and job commit before a worker can be woken | VERIFIED | Producer caller-owned transactions reserve then enqueue; provider is absent from producer path. |
| 14 | Dispatch invokes executable send handler and exact-token settlement | VERIFIED | `HANDLERS` registration and `drain_once()` outbound settlement path exercised. |
| 15 | Stale/unowned static context no-ops before provider work | VERIFIED | `test_send_handler_drops_unowned_or_stale_context_before_provider_work` passed. |
| 16 | Final lease expiry / unsafe outcome enters purpose-aware review with bounded facts | VERIFIED | Final reaper and review tests passed. |
| 17 | Confirmation and clarification review actions are purpose-isolated | VERIFIED | Direct-POST negative tests and confirmation-owned retry predicates passed. |
| 18 | Review projection is bounded; frozen body/attachments require scoped readers | VERIFIED | Repository hygiene and clarification-review tests passed. |
| 19 | Human-authorized confirmation repeat clones frozen bytes | VERIFIED | Delivery/route tests cover snapshot clone rather than regeneration. |
| 20 | Clarification initial and retry paths use frozen SEND_OUTBOUND slots | VERIFIED | Clarification/alias loop tests passed. |
| 21 | Clarification replay preserves RFC thread, round, and awaiting-reply state | VERIFIED | Clarification regression suite passed. |
| 22 | Clarification delivery cannot write aliases | VERIFIED | Clarification and alias tests passed. |
| 23 | Stale reply headers cannot resume the current epoch | VERIFIED | Current-epoch routing guard and threading regression passed. |
| 24 | Settlement fences claimed `email_id` before reservation/attempt writes | VERIFIED | Persisted-job identity fence tests passed. |
| 25 | Invalid outbound context retires exact held lease before drain forgets token | VERIFIED | `INVALID_CONTEXT`/`LOST_LEASE` separation and drain tests passed. |
| 26 | No legacy producer sends caller-supplied content | VERIFIED | `gateway.send_outbound()` is fail-closed; legacy-caller test passed. |
| 27 | Final reaper and settlement reject an already-stale epoch without mutating current evidence | VERIFIED | Production/fake stale-context branches are present and hermetic parity tests passed. |
| 28 | Current-epoch check authorizes the actual irreversible provider handoff | **FAILED (BLOCKER)** | The check at `send_outbound.py:70-79` is a separate, unlocked read; provider call is at line 89. `clear_reply_context()` increments `reply_epoch` in a separate update (`pipeline_state.py:403-413`). A controlled exercising probe changed epoch at the provider boundary and `handle_send_outbound()` still called the provider and returned `ok`. |
| 29 | No phase path silently creates a phantom reply-routing anchor | VERIFIED | Frozen Message-ID is reused for retry and stale header routing is epoch-scoped; relevant gateway/threading tests passed. |
| 30 | The durable DB fence/lock ordering survives genuine concurrent connections | UNCERTAIN (WARNING) | Guarded live-Postgres queueproof selection was unavailable locally: 53 skipped because `DATABASE_URL` and `ALLOW_DB_RESET=1` are absent. |
| 31 | Phase quality gates remain clean | VERIFIED | `uv run ruff check` and `uv run mypy` both passed. |
| 32 | All current-epoch guarantees hold through provider work, settlement, and retry | **FAILED (BLOCKER)** | Settlement fencing is after provider work; it cannot repair truth 28's external side effect. |

## Artifact and wiring evidence

- `app/db/repo/emails.py` provides immutable read-or-reserve snapshots and owner-scoped loading; it does not reapply retry content.
- `app/pipeline/delivery.py` and `app/pipeline/clarification.py` create a snapshot/job before wake and do not call the provider directly.
- `app/email/gateway.py` projects only frozen snapshot fields and passes the stored Message-ID as Resend's idempotency key.
- `app/queue/drain.py` sends the claimed job result to fenced settlement. `app/db/repo/job_settlement.py` correctly fences state writes, but that occurs after the provider request.
- `app/queue/handlers/send_outbound.py` is the broken link: it observes run epoch before, rather than atomically with, the provider handoff.

## Test evidence

Completed checks:

- `uv run pytest -q tests/test_send_idempotency.py tests/test_delivery.py tests/test_gateway.py tests/test_queue_drain.py tests/test_queue_durability.py tests/test_phase20_fake_parity.py tests/test_phase20_clarification_review.py tests/test_phase20_repo_hygiene.py tests/test_threading.py tests/test_dashboard.py tests/test_repo_jobs_sql.py tests/test_job_kind_drift.py tests/test_clarify.py tests/test_alias_full_loop.py tests/test_alias_write.py tests/test_pdf.py` — **429 passed, 58 skipped**.
- Targeted smaller Phase-20 core suite — **195 passed, 55 skipped**.
- `uv run ruff check` — passed.
- `uv run mypy` — passed (160 source files).
- Guarded live-Postgres selection — **53 skipped, 114 deselected**; unavailable evidence, not a pass.

Independent failure probe (no repository files changed): a `Job` and current-epoch snapshot entered `handle_send_outbound`; the gateway boundary advanced the simulated run epoch from 0 to 1. The handler had already completed its preflight and still invoked the provider, returning `{"result": "ok", "provider_called_after_epoch_bump": true, "epoch_after": 1}`.

## Gaps and remediation

### BLOCKER — preflight epoch check is not a provider-handoff fence

`handle_send_outbound()` reads snapshot/run facts, releases them, and then calls Resend. A concurrent retrigger may commit `clear_reply_context()` in the gap. The old snapshot can reach the client after a new epoch is authorized, and later settlement merely retires the obsolete job.

Remediate with a durable authorization state that serializes retrigger and provider handoff: lock/check exact leased job, snapshot, run status/epoch, and reservation age in one transaction; record a provider-attempt fence before releasing the transaction; make retrigger reject or wait on that state; then call the provider. Add a two-connection regression with a barrier immediately after authorization that proves an epoch bump cannot permit the stale gateway call.

### WARNING — live database concurrency evidence unavailable

Run the guarded integration/queueproof tests with a resettable Postgres database after implementing the fence. This warning does not downgrade the blocker: the handler probe and source ordering already demonstrate the unsafe interleaving.

## Concise verdict

The retry payload/key/retention mechanics are sound, but the phase goal is not. **Do not mark Phase 20 complete** until provider authorization is made linearizable against `reply_epoch` changes and is proven with a real concurrent Postgres regression.

## Verification Complete
