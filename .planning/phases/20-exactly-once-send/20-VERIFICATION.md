---
phase: 20-exactly-once-send
verified: 2026-07-17T23:54:07Z
status: gaps_found
score: 26/32 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 25/32
  gaps_closed:
    - "Final SEND_OUTBOUND lease expiry now preserves the reservation, appends bounded attempt evidence, and enters purpose-specific delivery review."
    - "Settlement now allowlists the four replayable delivery reasons and fences persisted email_id."
    - "Retry-now and settlement now use job-first lock ordering."
    - "Current-epoch awaiting-reply routing, body-free review projection, and fail-closed legacy email mutation are implemented."
    - "InMemoryRepo SEND_OUTBOUND validation, fixed eight-attempt budget, attempt ledger, replay allowlist, final reaper, and stale-header parity are implemented."
    - "Clarification delivery review loading, frozen-question evidence, isolated actions, and generic resolve/retrigger guards are implemented."
  gaps_remaining:
    - "Confirmation sent-proof lookup is not scoped to the current reply epoch."
    - "Old-epoch SEND_OUTBOUND jobs are not rejected before provider work or settlement."
    - "Confirmation-only delivery actions accept clarification reviews on direct POST."
    - "Invalid-context fenced leases can remain leased after the drain discards the worker token."
    - "Generic delivery retry is not purpose-isolated."
    - "The repo-wide strict mypy gate remains red with 10 errors."
  regressions: []
gaps:
  - truth: "SEND-01: sent confirmation idempotency is scoped to the current run reply epoch."
    status: failed
    reason: "get_outbound_message_id selects any sent confirmation for the run and purpose, without em.epoch = payroll_runs.reply_epoch; a sent epoch-0 row can suppress the epoch-1 confirmation after retrigger."
    artifacts:
      - path: "app/db/repo/emails.py:399-430"
        issue: "The proof-of-delivery lookup has no current-epoch predicate."
      - path: "app/pipeline/delivery.py:91-97"
        issue: "Confirmation delivery treats that unscoped result as proof that the current confirmation was sent."
    missing:
      - "Add the current-epoch predicate and a regression with a sent old-epoch confirmation followed by a new epoch."
  - truth: "D-07/D-08: an old-epoch SEND_OUTBOUND job cannot reach the provider or be settled as the current delivery."
    status: failed
    reason: "The handler validates snapshot shape and authorized run status but never compares snapshot/message epoch with the locked run reply_epoch; settlement and final-lease reaping likewise accept the reservation without an epoch check."
    artifacts:
      - path: "app/queue/handlers/send_outbound.py:28-80"
        issue: "_snapshot_matches_job checks that epoch is a nonnegative integer, not that it is current."
      - path: "app/db/repo/job_settlement.py:151-179, 235-255, 759-805"
        issue: "Reservation locking and final reaping do not require the current reply epoch."
    missing:
      - "Reject stale epochs before provider work and again in settlement/reaping; terminalize or safely no-op old jobs when a retrigger bumps the epoch."
  - truth: "D-09/D-16: confirmation-only delivery actions cannot resolve or authorize a clarification delivery review."
    status: failed
    reason: "mark_delivery_delivered and authorize_new_confirmation only check that a review exists; they do not require review_kind == confirmation. A direct POST can reconcile a clarification run or clone its frozen question into a confirmation slot."
    artifacts:
      - path: "app/routes/runs.py:1011-1081"
        issue: "Both confirmation action endpoints accept the shared loader's clarification result."
    missing:
      - "Require an explicit confirmation review kind before mark-delivered or new-confirmation authorization, with negative direct-POST tests proving no mutation."
  - truth: "Queue fencing durably retires an invalid-context job before the drain drops its lease token."
    status: failed
    reason: "settle_outbound_delivery_job returns FENCED for a still-owned lease whose run status or context is invalid; drain_once treats every FENCED result as settled and removes the held token, but no SQL transition retires or releases the still-leased row."
    artifacts:
      - path: "app/db/repo/job_settlement.py:220-255"
        issue: "Lost lease and invalid current context share the same FENCED outcome."
      - path: "app/queue/drain.py:186-245"
        issue: "Any settlement result, including invalid-context FENCED, sets lease_settled and discards the token."
    missing:
      - "Separate LOST_LEASE from INVALID_CONTEXT and durably complete, dead-letter, or release an exact current lease before token discard."
  - truth: "D-01/D-07: confirmation retry-now cannot advance a clarification delivery review through the generic confirmation operation."
    status: failed
    reason: "retry_delivery_now calls _load_delivery_review and advance_existing_send_job_due_now without requiring review_kind == confirmation; the generic repository operation also does not enforce confirmation purpose/review ownership."
    artifacts:
      - path: "app/routes/runs.py:934-952"
        issue: "The generic retry endpoint accepts either review kind."
      - path: "app/db/repo/jobs.py:225-285"
        issue: "The generic due-now operation checks only send kind, identity, pending state, and age."
    missing:
      - "Restrict the generic action/repository seam to confirmation and leave clarification retry on its dedicated purpose-checked operation."
  - truth: "The phase's strict type-check quality gate is green across the repository."
    status: failed
    reason: "uv run mypy exits 1 with 10 errors: one incompatible fake connection argument and nine app.routes.runs.repo attr-defined errors in the new clarification-review tests."
    artifacts:
      - path: "tests/test_phase20_fake_parity.py:320"
        issue: "object is passed where a psycopg Connection is expected."
      - path: "tests/test_phase20_clarification_review.py:98-221"
        issue: "The test module accesses app.routes.runs.repo without an exported type-visible attribute."
    missing:
      - "Fix the test typing or provide the appropriate typed seam, then rerun the bare configured mypy command."
---

# Phase 20: Exactly-Once Send Verification Report

**Phase Goal:** A client is sent at most one payroll confirmation per approved run, per epoch — a retry never redrafts, never regenerates non-deterministic bytes, and never silently orphans a reply into a phantom run.

**Verified:** 2026-07-17T23:54:07Z
**Status:** gaps_found  
**Re-verification:** Yes — after Plans 20-13 through 20-16

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---:|---|---|---|
| 1 | D-12: envelope and ordered attachment bytes are committed before provider work | ✓ VERIFIED | `schema.sql` has immutable snapshot/attachment tables and append-only triggers; producers reserve and enqueue before the handler. |
| 2 | D-13: retries reuse the original Message-ID, payload, headers, recipient, and bytes | ✓ VERIFIED | `reserve_outbound_snapshot` returns the existing row unchanged and the snapshot gateway reads stored fields/bytes only. |
| 3 | SEND-01: one logical run/purpose/round/epoch slot keeps its original Message-ID | ✗ FAILED | The reservation slot is epoch-keyed, but `get_outbound_message_id` is not epoch-scoped and can suppress a new epoch's send; see gap 1. |
| 4 | D-01: approval and retry-now use durable work without synchronous provider calls | ✓ VERIFIED | Approval and retry routes enqueue/advance jobs and wake after commit; no route calls the provider directly. |
| 5 | D-07: scheduled and accelerated retry work converges on one fenced send job | ✗ FAILED | Normal same-row paths exist, but stale-epoch jobs remain provider-eligible and invalid-context leases can be stranded; see gaps 2 and 4. |
| 6 | SEND-03: send jobs carry only run plus persisted email/snapshot identity | ✓ VERIFIED | Production and fake enqueue validation require the exact identifiers, dedup key, and fixed eight-attempt policy. |
| 7 | D-02: only timeout, connection, eligible rate-limit, and provider-5xx results replay automatically | ✓ VERIFIED | Production and fake settlement use the exact four-reason allowlist; all other retryable reasons enter review. |
| 8 | D-03: reservation time, not restart/attempt time, bounds replay at 20 hours | ✓ VERIFIED | Handler, settlement, retry-now, and fake paths use `reserved_at`; the cutoff regression passes. |
| 9 | D-04: provider calls are projections of persisted snapshots | ✓ VERIFIED | `send_outbound.py` has no composition/PDF/current-payroll calls and invokes the snapshot-only gateway. |
| 10 | D-06: payload mismatch is terminal review with no replacement key | ✓ VERIFIED | Gateway classification maps the mismatch to review and no replacement key is minted. |
| 11 | D-04: composition/PDF generation occurs only for an absent snapshot | ✓ VERIFIED | `delivery.py` gates composition, YTD, and PDF work behind the absent-snapshot branch. |
| 12 | D-05: safe confirmation retry retains approved business state | ✓ VERIFIED | Allowlisted replay reschedules the same job and leaves the run approved. |
| 13 | D-12: snapshot and job commit before a worker can call Resend | ✓ VERIFIED | Producer transactions reserve the snapshot and enqueue identifier-only work before post-commit wake. |
| 14 | D-01/D-07: an executable handler is backed by fenced settlement | ✓ VERIFIED | `dispatch.HANDLERS` registers `handle_send_outbound`, which passes the exact claimed job to settlement. |
| 15 | D-04: handler cannot compose or regenerate content | ✓ VERIFIED | Handler imports only repository, gateway, job/status, and result modules. |
| 16 | D-08: stale/non-replayable ambiguity always reaches explicit delivery review | ✗ FAILED | Normal terminal/final-lease paths now review, but old-epoch provider eligibility and invalid-context lease handling bypass safe retirement; see gaps 2 and 4. |
| 17 | D-09: delivery actions are provider-free or explicitly typed human authorization | ✗ FAILED | Confirmation actions do not reject a clarification review on direct POST; see gap 3. |
| 18 | D-10: review exposes safe facts and frozen artifact references without provider dumps | ✓ VERIFIED | Review projection omits body/provider payloads; frozen email/attachment routes are separate and ownership-scoped. |
| 19 | D-11: human-authorized repeat copies the original frozen snapshot | ✗ FAILED | The confirmation clone is byte-preserving, but the confirmation authorization endpoint is not restricted to confirmation reviews. |
| 20 | D-04: YTD presentation affects only future snapshot creation | ✓ VERIFIED | YTD/PDF work is absent from replay and uses persisted bytes for repeats. |
| 21 | D-11: authorized repeat retains original attachment bytes | ✓ VERIFIED | `_snapshot_clone_fields` copies stored attachment content. |
| 22 | D-12/D-13: paystub bytes are append-only provider evidence | ✓ VERIFIED | Attachment rows are immutable and guarded by database triggers. |
| 23 | Eval chart is offline and isolated from delivery writers | ✓ VERIFIED | `uv run python eval/run_eval.py --check` passed and module-boundary tests are present. |
| 24 | Eval artifact changes cannot mutate outbound audit records | ✓ VERIFIED | Eval code consumes aggregate fixture/scoring data and has no delivery/database writer path. |
| 25 | SEND-01/02/03 ordinary regression gate is green | ✓ VERIFIED | Full suite: `1144 passed, 82 skipped`; targeted Phase 20 suite: `236 passed, 51 skipped`. This does not erase source-level gaps. |
| 26 | Settlement fences persisted leased job identity before snapshot access | ✓ VERIFIED | `_locked_job` selects persisted `email_id` and settlement compares it before reservation/attempt writes. |
| 27 | Fenced loser writes no delivery evidence | ✓ VERIFIED | Identity mismatch returns before snapshot/attempt SQL; targeted fence tests pass. |
| 28 | Clarification initial/retry/retry-now work uses one SEND_OUTBOUND row | ✓ VERIFIED | Dedicated clarification retry advances the existing row and no new slot/key is created; generic cross-purpose retry remains a separate failed boundary. |
| 29 | Clarification replay uses frozen question/thread/round content | ✓ VERIFIED | Clarification producer loads the existing snapshot before drafting/provider work; frozen evidence tests pass. |
| 30 | Clarification settlement preserves awaiting-reply and avoids alias writes | ✓ VERIFIED | Purpose-aware settlement and clarification actions keep `awaiting_reply` semantics and do not write aliases. |
| 31 | No confirmation or clarification producer bypasses durable SEND_OUTBOUND | ✓ VERIFIED | Both producers reserve snapshots and enqueue identifier-only jobs; legacy gateway path is inert. |
| 32 | No legacy path evades bounded category, cutoff, key, and epoch fencing | ✗ FAILED | Category/cutoff/key fencing is present, but the sent-proof and handler/settlement epoch fences are incomplete. |

**Score:** 26/32 truths verified.

## Required Artifacts

| Artifact | Status | Evidence |
|---|---|---|
| `app/db/schema.sql` | ✓ VERIFIED | Snapshot, ordered `BYTEA` attachments, bounded attempts, and append-only triggers are substantive. Live deployed-schema mutation proof is unavailable locally. |
| `app/db/repo/emails.py` | ⚠️ PARTIAL | Reservation/review APIs are wired and body-free; sent-proof lookup and references-chain lookup lack current-epoch scoping. |
| `app/db/repo/jobs.py` | ⚠️ PARTIAL | Production retry seams are job-first and purpose-aware for clarification; generic retry lacks purpose enforcement and fake ordering/timing diverges. |
| `app/db/repo/job_settlement.py` | ⚠️ PARTIAL | Allowlist, identity fence, final reaper, and attempt ledger exist; epoch validation and invalid-context lease retirement do not. |
| `app/email/gateway.py` | ✓ VERIFIED | Snapshot-only Resend adapter carries the stored idempotency key and payload; legacy caller-content path is fail-closed. |
| `app/pipeline/delivery.py` / `app/pipeline/clarification.py` | ✓ VERIFIED | Producers reserve immutable snapshots and enqueue one identifier-only job before wake/provider work. |
| `app/queue/handlers/send_outbound.py` | ⚠️ PARTIAL | Snapshot-only handler is substantive and wired, but it lacks a run-current-epoch check before provider work. |
| `app/routes/runs.py` / `app/templates/run_detail.html` | ⚠️ PARTIAL | Distinct clarification UI/actions and generic guards exist; direct confirmation endpoints are not purpose-authorized. |
| `tests/conftest.py` / Phase 20 tests | ⚠️ PARTIAL | Fake safety contracts and regressions exist, but fake claim timing/reclaim behavior and strict typing are incomplete. |

## Key Link Verification

| From | To | Status | Details |
|---|---|---|---|
| Producer reservation | snapshot + attachments + SEND_OUTBOUND job | ✓ WIRED | Caller-owned transaction; post-commit wake. |
| SEND_OUTBOUND dispatch | snapshot gateway | ⚠️ PARTIAL | Identifier-only and snapshot-backed, but no current-epoch comparison. |
| Handler | settlement | ✓ WIRED | Exact job/token passed; persisted email identity is checked. |
| Result reason | replay settlement | ✓ WIRED | Four-category allowlist and 20-hour reservation cutoff. |
| Final lease reaper | purpose-specific review | ✓ WIRED | Confirmation/clarification markers and bounded attempt fact are persisted. |
| Sent-proof lookup | current epoch | ✗ NOT WIRED | `get_outbound_message_id` omits `epoch = reply_epoch`. |
| Generic delivery retry | confirmation-only seam | ✗ NOT WIRED | Generic route/repository operation accepts clarification review context. |
| Confirmation actions | confirmation-only review | ✗ NOT WIRED | `mark_delivery_delivered` and `authorize_new_confirmation` do not inspect `review_kind`. |
| Invalid context | durable lease retirement | ✗ NOT WIRED | `FENCED` is treated as settled without a corresponding row transition. |
| Clarification review marker | isolated review actions/UI | ✓ WIRED | Loader, frozen evidence, dedicated retry, handled/reject, and resolve/retrigger guards are connected. |

## Data-Flow Trace (Level 4)

| Artifact | Data source | Produces real data | Status |
|---|---|---|---|
| `send_outbound.py` | `load_outbound_snapshot` → stored envelope/attachment bytes | Yes | ⚠️ FLOWING but epoch authorization is incomplete. |
| Confirmation producer | roster/payroll inputs only on absent snapshot | Yes | ✓ FLOWING. |
| Clarification review | persisted review projection plus authorized frozen reader | Yes | ✓ FLOWING and purpose-matched. |
| Eval chart | committed aggregate fixtures/scoring output | Yes | ✓ FLOWING. |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Phase 20 targeted regressions | `uv run pytest -q tests/test_send_idempotency.py tests/test_queue_durability.py tests/test_phase20_fake_parity.py tests/test_phase20_clarification_review.py tests/test_phase20_repo_hygiene.py tests/test_threading.py tests/test_dashboard.py tests/test_repo_jobs_sql.py tests/test_job_kind_drift.py` | 236 passed, 51 skipped | ✓ PASS |
| Whole repository regression | `uv run pytest -q` | 1144 passed, 82 skipped | ✓ PASS |
| Eval regression | `uv run python eval/run_eval.py --check` | Check passed | ✓ PASS |
| Ruff quality gate | `uv run ruff check` | All checks passed | ✓ PASS |
| Strict type quality gate | `uv run mypy` | 10 errors in two Phase 20 test files | ✗ FAIL |
| Guarded live Postgres evidence | `uv run pytest -q -m 'integration and queueproof' tests/test_send_idempotency.py tests/test_queue_durability.py tests/test_threading.py` | 49 skipped; no `DATABASE_URL`/`ALLOW_DB_RESET=1` | ? UNAVAILABLE |

## Probe Execution

No phase-declared or conventional `scripts/*/tests/probe-*.sh` probes were found.

## Requirements Coverage

| Requirement | Status | Evidence |
|---|---|---|
| SEND-01 | ✗ BLOCKED | Normal reservation/idempotency tests pass, but unscoped sent-proof lookup and stale-epoch provider eligibility violate the per-epoch contract. |
| SEND-02 | ✗ BLOCKED | Frozen payload replay and bounded allowlist pass; stale-epoch handler authorization and provider-success rollback risk remain. |
| SEND-03 | ✗ BLOCKED | Idempotency header, queue vocabulary, and review projections pass; purpose-isolated action authorization and strict type/live evidence gates remain incomplete. |

## Anti-Patterns Found

| File | Pattern | Severity | Impact |
|---|---|---|---|
| `app/db/repo/emails.py:420-429` | Sent confirmation lookup is not epoch-scoped | 🛑 BLOCKER | Can suppress the current epoch's confirmation. |
| `app/queue/handlers/send_outbound.py:66-80` | Stale epoch accepted as provider-authorized | 🛑 BLOCKER | Old frozen sends can reach the provider after retrigger. |
| `app/routes/runs.py:1016-1050` | Confirmation actions lack review-kind authorization | 🛑 BLOCKER | Clarification review can be reconciled or cloned as confirmation. |
| `app/queue/drain.py:194-245` | Invalid-context `FENCED` discards a still-held lease token | 🛑 BLOCKER | Lease can remain stranded and later be misleadingly reaped. |
| `app/routes/runs.py:940-947` | Generic retry accepts clarification review | ⚠️ WARNING | Purpose-specific action boundary is incomplete. |
| `tests/conftest.py:915-937` | Fake claim ignores due time and expired-lease reclaim | ⚠️ WARNING | Offline tests do not model durable retry timing/recovery. |
| `app/db/repo/emails.py:710-713` | References chain is not current-epoch filtered | ⚠️ WARNING | New epoch threading can inherit stale outbound references. |
| `app/db/repo/job_settlement.py:182-204` | Roster load occurs before durable success settlement completes | ⚠️ WARNING | A post-provider roster failure can roll back local sent evidence. |
| `app/db/schema.sql:451-465` | Snapshot duplicates canonical `message_id` without equality enforcement | ⚠️ WARNING | Direct malformed SQL could split audit and provider identity. |
| `tests/conftest.py:1042-1051` | Fake error detail stores raw exception text | ⚠️ WARNING | Fake does not exercise production diagnostic scrubbing. |
| `uv run mypy` | Ten strict typing errors in Phase 20 tests | 🛑 BLOCKER | The configured repository type gate is red. |

No unreferenced `TBD`, `FIXME`, or `XXX` markers were found in the inspected Phase 20 implementation/test files.

## Authentication/CSRF Review Judgment

The review's CR-04 is a real deployment security risk: mutating dashboard routes have no operator authentication or CSRF protection. It is not counted as a Phase 20 SEND requirement failure because `.planning/REQUIREMENTS.md` explicitly lists operator authentication as out of scope/known accepted risk, and `.planning/PROJECT.md` explicitly says dashboard auth is out of scope for the demo. The Phase 16 action-boundary issue above is different and is in-scope: it violates the Phase 20 purpose-isolation contract even without considering authentication.

## Human Verification Required

After the blockers are fixed, run the guarded live-Postgres snapshot/trigger, epoch, lease-fence, and concurrency proofs with `DATABASE_URL` and `ALLOW_DB_RESET=1`; then manually inspect the confirmation and clarification review cards and exercise same-row retry, handled, reject, and typed confirmation authorization in a browser. External Resend crash/timeout behavior also remains a human/integration check.

## Gaps Summary

Plans 20-13 through 20-16 closed the prior settlement, replay-category, persisted-email fence, epoch-routing query, body-projection, fake enqueue, final-reaper, and clarification-review gaps in the normal paths. The goal is still not achieved: current-epoch fencing is incomplete at sent-proof lookup and provider dispatch, confirmation actions are not purpose-authorized, and invalid-context leases are not durably retired. Generic retry isolation, fake queue timing/reclaim parity, provider-success transaction ordering, and the strict mypy gate remain quality gaps. Authentication/CSRF is separately recorded as an explicitly accepted broader demo risk, not silently treated as a Phase 20 requirement.

---

_Verified: 2026-07-17T23:54:07Z_
_Verifier: the agent (gsd-verifier)_
