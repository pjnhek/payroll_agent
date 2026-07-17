---
phase: 20-exactly-once-send
verified: 2026-07-17T21:54:11Z
status: gaps_found
score: 25/32 must-haves verified
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "Final lease expiry for SEND_OUTBOUND preserves ambiguity as delivery review and cannot create a duplicate confirmation"
    status: failed
    reason: "reap_expired_final_attempt treats SEND_OUTBOUND like every other non-ingest job, marks the job dead, and can leave an accepted provider send outside the delivery-review path."
    artifacts:
      - path: "app/db/repo/job_settlement.py:722-768"
        issue: "The final-lease reaper has no SEND_OUTBOUND branch, attempt append, reservation lock, or purpose-aware review transition."
    missing:
      - "Add confirmation and clarification-specific final-lease handling that preserves the frozen reservation and routes ambiguity to an operator workflow before generic retrigger can compose again."
      - "Add crash-after-provider-acceptance coverage for both outbound purposes."
  - truth: "Header reply routing is restricted to the run's current reply epoch"
    status: failed
    reason: "find_awaiting_reply_for_header matches any outbound row for an awaiting run without comparing em.epoch to pr.reply_epoch."
    artifacts:
      - path: "app/db/repo/emails.py:783-809"
        issue: "A stale pre-retrigger Message-ID can be accepted as the current clarification reply."
    missing:
      - "Add the current-epoch predicate and a regression covering a stale header after an epoch bump."
  - truth: "Only the approved transient delivery categories are automatically replayable"
    status: failed
    reason: "settle_outbound_delivery_job schedules every PipelineResult with RETRYABLE outcome while the reservation window is open; it never gates on the mapped delivery category."
    artifacts:
      - path: "app/db/repo/job_settlement.py:279-300"
        issue: "Authentication, validation, configuration, mismatch, unknown, or future retryable results can be rescheduled."
    missing:
      - "Gate scheduling on timeout, connection, eligible rate limit, and provider 5xx reasons; route all other categories directly to review."
      - "Add parameterized settlement tests for every non-replayable category."
  - truth: "The lease fence verifies the claimed job's persisted email_id before touching a snapshot"
    status: failed
    reason: "_locked_job selects no email_id and settlement locks the snapshot using caller-supplied job.email_id."
    artifacts:
      - path: "app/db/repo/job_settlement.py:81-94"
        issue: "A claimed object with a valid job id/token but a mismatched email_id is not logically fenced."
      - path: "app/db/repo/job_settlement.py:210-225"
        issue: "The caller value is used for reservation and email state writes."
    missing:
      - "Select persisted email_id in _locked_job, compare it to the claimed object, and return FENCED before reservation or attempt writes on mismatch."
      - "Add a mismatched-claimed-email regression."
  - truth: "Clarification delivery ambiguity has explicit operator review and evidence isolated from alias resolution"
    status: failed
    reason: "Settlement emits ClarificationDeliveryReview, but the route projection and template only recognize confirmation DeliveryReview."
    artifacts:
      - path: "app/routes/runs.py:257-291"
        issue: "_load_delivery_review rejects ClarificationDeliveryReview and loads only purpose=confirmation."
      - path: "app/templates/run_detail.html:110-179"
        issue: "The review card is confirmation-only; clarification ambiguity falls through to generic name resolution."
    missing:
      - "Add purpose-aware frozen-question review evidence and explicit retry/handled/reject actions that cannot enter alias confirmation."
      - "Add dashboard coverage for ClarificationDeliveryReview."
  - truth: "The in-memory queue mirrors SEND_OUTBOUND validation and its eight-attempt budget"
    status: failed
    reason: "The fake enqueue_job validates older kinds only and defaults send jobs to five attempts."
    artifacts:
      - path: "tests/conftest.py:808-893"
        issue: "No SEND_OUTBOUND branch enforces run_id, email_id, exact dedup key, or max_attempts=8."
    missing:
      - "Mirror production send-job validation, deduplication, and forced attempt budget in InMemoryRepo."
      - "Add paired malformed-context and attempt-budget tests."
  - truth: "Final lease reaping, retry-now, and settlement use one deadlock-safe lock order"
    status: failed
    reason: "Retry-now locks snapshot/message before job while settlement locks job before snapshot/message."
    artifacts:
      - path: "app/db/repo/jobs.py:240-264"
        issue: "advance_existing_send_job_due_now uses reservation-then-job order."
      - path: "app/db/repo/job_settlement.py:210-225"
        issue: "settle_outbound_delivery_job uses job-then-reservation order."
    missing:
      - "Choose one lock order and add concurrent retry-versus-settlement coverage."
  - truth: "The bounded delivery-review projection excludes the frozen message body"
    status: failed
    reason: "The repository projection selects body_text even though the route currently omits it from the browser-safe projection."
    artifacts:
      - path: "app/db/repo/emails.py:335-367"
        issue: "Every caller of the review projection receives immutable client/payroll body content unnecessarily."
    missing:
      - "Remove body_text from the review projection and retain it only in the authorized frozen-email reader."
  - truth: "The legacy email-state mutator cannot update inbound rows or arbitrary states"
    status: failed
    reason: "update_email_message_state updates by message_id alone and accepts any state string."
    artifacts:
      - path: "app/db/repo/emails.py:661-677"
        issue: "The public compatibility mutator can corrupt inbound audit rows or write invalid send state."
    missing:
      - "Remove/fail-close the mutator or constrain it to outbound rows and an explicit allowed transition set."
deferred: []
---

# Phase 20: Exactly-Once Send Verification Report

**Phase Goal:** A client is sent at most one payroll confirmation per approved run, per epoch — a retry never redrafts, never regenerates non-deterministic bytes, and never silently orphans a reply into a phantom run.

**Verified:** 2026-07-17T21:54:11Z  
**Status:** gaps_found  
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---:|---|---|---|
| 1 | D-12: provider-ready envelope and ordered attachment bytes are reserved before provider work | ✓ VERIFIED | `schema.sql` defines immutable snapshot/attachment tables and append-only triggers; `delivery.py` reserves then enqueues inside the caller transaction; focused reservation/queue tests pass. The guarded live trigger test is unavailable locally. |
| 2 | D-13: retries reuse the original Message-ID, body, headers, recipient, and bytes | ✓ VERIFIED | `reserve_outbound_snapshot` locks and returns the existing snapshot without caller-content updates; `gateway.send_reserved_outbound_snapshot` uses only stored fields; replay tests pass. |
| 3 | SEND-01: one logical run/purpose/round/epoch slot keeps its original Message-ID | ✓ VERIFIED | The unique slot arbiter and conflict branch return the original snapshot; the legacy caller send is fail-closed. |
| 4 | D-01: approval and retry-now create/advance durable work without synchronous provider calls | ✓ VERIFIED | Approval reserves/enqueues in `delivery.py` and `runs.py`; retry-now only advances an existing pending job; named approval/retry tests pass. |
| 5 | D-07: scheduled and accelerated retry converge on one identifier-only, lease-fenced send job | ✗ FAILED | Normal handler/settlement paths are wired, but final lease expiry enters the generic reaper, marks the send dead, and permits a generic retrigger/new snapshot path. |
| 6 | SEND-03: send queue rows admit only run plus persisted email/snapshot identity | ✗ FAILED | Production validation is exact in `app/db/repo/jobs.py`, but `InMemoryRepo.enqueue_job` has no SEND_OUTBOUND branch and accepts malformed context with the wrong attempt default. |
| 7 | D-02: only timeout, connection, eligible rate limit, and Resend 5xx are replayable | ✗ FAILED | The gateway classifier is allowlisted, but settlement reschedules any `RETRYABLE` result without checking its delivery reason/category. |
| 8 | D-03: reservation time, not attempt/restart time, bounds replay below 20 hours | ✓ VERIFIED | `delivery_replay_allowed`, `next_delivery_attempt_at`, handler, and database settlement all use `reserved_at`; cutoff tests pass. Live Postgres queueproof is skipped. |
| 9 | D-04: provider calls are deterministic projections of persisted snapshots | ✓ VERIFIED | The snapshot-only gateway rehydrates headers, body, recipients, and ordered encoded bytes and the legacy caller-argument method raises before provider setup. |
| 10 | D-06: payload mismatch is terminal review with no replacement key | ✓ VERIFIED | Resend 409 `invalid_idempotent_request` maps to terminal mismatch; no replacement key is minted; gateway tests pass. The unsafe generic settlement gate remains a related gap. |
| 11 | D-04: composition and PDF generation occur only for an absent confirmation snapshot | ✓ VERIFIED | `delivery.py` gates composition/YTD/PDF work behind `policy.has_existing_snapshot`; named replay test passes. |
| 12 | D-05: safe confirmation replay retains approved business state | ✓ VERIFIED | Delivery settlement reschedules the same job without updating approved status; named test passes. Final-lease ambiguity is a separate failed path. |
| 13 | D-12: snapshot and job commit before a worker can call Resend | ✓ VERIFIED | Approval and clarification producers reserve and enqueue in caller-owned transactions; the handler is reached only from the durable queue. |
| 14 | D-01/D-07: an executable SEND_OUTBOUND handler is backed by fenced settlement before producers enqueue | ✓ VERIFIED | `dispatch.HANDLERS` registers `send_outbound`; the handler loads the snapshot, calls the snapshot gateway, and forwards the exact lease to settlement. |
| 15 | D-04: the handler cannot call composition/PDF/current-payroll code | ✓ VERIFIED | `send_outbound.py` has no imports or calls to delivery, composition, PDF, or mutable payroll loaders; fail-if-called handler tests pass. |
| 16 | D-08: stale/non-replayable delivery uncertainty always appears as explicit delivery review | ✗ FAILED | Confirmation terminal paths set `DeliveryReview`, but final lease expiry bypasses it and clarification terminal paths have no route/template review workflow. |
| 17 | D-09: mark-delivered is provider-free and typed authorization creates a distinct human slot | ✓ VERIFIED | Routes use CAS/transaction, exact acknowledgement, frozen snapshot cloning, one job, and post-commit wake; dashboard tests pass. |
| 18 | D-10: review shows safe basis and frozen artifacts without raw provider dumps | ✓ VERIFIED | Browser projection allowlists recipient/subject/time/attempts/category/key/artifact references and routes read owned frozen artifacts. Repository projection unnecessarily includes body_text; see warning gap. |
| 19 | D-11: human authorization copies original frozen bytes, not current payroll/contact values | ✓ VERIFIED | `_snapshot_clone_fields` copies stored envelope and attachment bytes; authorization tests pass after historical data changes. |
| 20 | D-04: YTD presentation affects only future snapshot creation | ✓ VERIFIED | YTD aggregation is called only on first-time confirmation creation; PDF consumes supplied totals; YTD/PDF tests pass. |
| 21 | D-11: human-authorized repeat keeps original frozen attachment bytes | ✓ VERIFIED | Authorization clones persisted attachment content rather than regenerating; named dashboard test passes. |
| 22 | D-12/D-13: paystub presentation is captured before provider work and remains append-only | ✓ VERIFIED | PDF bytes are inserted into immutable attachment rows before queue/provider work; schema triggers and PDF boundary tests pass. |
| 23 | Eval chart is offline and isolated from delivery/database writers | ✓ VERIFIED | `tests/test_eval.py` boundary checks pass and `eval/run_eval.py --check` passes. |
| 24 | Changing eval artifacts cannot mutate outbound audit records | ✓ VERIFIED | Chart generation consumes aggregate eval data only and does not import delivery/queue/repository mutation modules. |
| 25 | SEND-01/SEND-02/SEND-03 safety remains green through the chart-polish gate | ✓ VERIFIED (test gate only) | Full suite: `1080 passed, 78 skipped`; focused phase suite: `339 passed, 8 skipped`; this does not override the code-level gaps above. |
| 26 | D-01/D-07: settlement fences the exact leased send job identity | ✗ FAILED | Lease token and job id are checked, but persisted `email_id` is not selected or compared before locking the caller-supplied snapshot. |
| 27 | D-07: winner appends bounded attempt history and fenced loser writes nothing | ✗ FAILED | The exact-token loser path is tested, but the logical identity fence is incomplete; a mismatched claimed email can target another snapshot. |
| 28 | Clarification initial/retry/retry-now work converges on one SEND_OUTBOUND job | ✓ VERIFIED | `clarification.py` reserves/loads by purpose/round/epoch, enqueues identifier-only work, and wakes after commit; clarification tests pass. |
| 29 | Clarification replay uses frozen RFC thread/round content before drafting | ✓ VERIFIED | Reentry loads the existing snapshot before suggestion/drafting; named replay and field-regression tests pass. |
| 30 | Clarification settlement preserves awaiting_reply and never confirms aliases | ✓ VERIFIED (settlement only) | Purpose-aware settlement preserves awaiting-reply and avoids alias writes; named clarification tests pass. Its emitted review state is not operator-routable, covered by Truth 16. |
| 31 | No confirmation or clarification producer bypasses the durable job/handler | ✓ VERIFIED | Both producers use reservation plus SEND_OUTBOUND; `gateway.send_outbound` is a fail-closed stub; legacy-path test passes. |
| 32 | No legacy caller can evade bounded classification, cutoff, fixed key, or fenced settlement | ✗ FAILED | The legacy method is inert, but settlement accepts unsafe retryable results and final lease reaping bypasses delivery-specific settlement/review. |

**Score:** 25/32 truths verified.

## Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `app/db/schema.sql` | Immutable snapshots, ordered bytes, bounded attempts, repair triggers | ✓ VERIFIED | Tables/checks/triggers are present; guarded deployed-schema mutation proof skipped. |
| `app/db/repo/emails.py` | Read-or-reserve and scoped snapshot/review readers | ⚠️ PRESENT WITH WARNINGS | Snapshot APIs are substantive and wired; review projection includes `body_text`, header routing lacks epoch, and legacy state mutator is broad. |
| `app/db/repo/jobs.py` | Exact send context and existing-job-only retry-now | ✓ VERIFIED | Production validation and transaction path pass; lock order conflicts with settlement. |
| `app/db/repo/job_settlement.py` | Purpose-aware exact-token settlement and bounded replay | ✗ FAILED | Missing persisted email-id fence, category gate, and final SEND_OUTBOUND reaper handling. |
| `app/email/gateway.py` | Snapshot-only provider adapter and inert legacy path | ✓ VERIFIED | Stable Message-ID/idempotency key and byte-equivalent request tests pass. |
| `app/pipeline/delivery.py` | Atomic confirmation reserve/enqueue and replay guard | ✓ VERIFIED | No synchronous send; first-time-only composition/YTD/PDF path. |
| `app/pipeline/clarification.py` | Atomic clarification reserve/enqueue and frozen replay | ✓ VERIFIED | Standard and field-regression paths are wired and tested. |
| `app/queue/handlers/send_outbound.py` | Identifier-only snapshot consumer | ✓ VERIFIED | Handler is substantive, registered, and calls only snapshot gateway/settlement. |
| `app/routes/runs.py` / `app/templates/run_detail.html` | Safe confirmation delivery review and actions | ⚠️ PARTIAL | Confirmation review works; clarification review is absent. |
| `app/pipeline/pdf.py` | Pure current/YTD PDF generation | ✓ VERIFIED | Supplied YTD totals and complete columns are tested. |
| `eval/run_eval.py` / `eval/chart.svg` | Offline aggregate-only chart | ✓ VERIFIED | Style, reproducibility, and boundary tests pass. |

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `reserve_outbound_snapshot` | immutable snapshot + attachments | caller-owned transaction | ✓ WIRED | Insert/read-back and producer transaction paths are present. |
| approval/clarification producers | `SEND_OUTBOUND` | enqueue after reservation | ✓ WIRED | Both producers enqueue identifier-only context and wake after commit. |
| `SEND_OUTBOUND` | snapshot gateway | late-bound handler | ✓ WIRED | Handler loads by run/email ownership and forwards stored snapshot. |
| handler | settlement | exact lease token | ⚠️ PARTIAL | Lease token is passed, but settlement does not compare persisted job `email_id` to claimed `email_id`. |
| result classification | retry settlement | category gate | ✗ NOT WIRED | Settlement checks outcome only, not the allowed delivery reason set. |
| final lease reaper | delivery review | purpose-aware send settlement | ✗ NOT WIRED | Generic reaper kills final send leases without snapshot/attempt/review handling. |
| inbound RFC header | current reply epoch | `find_awaiting_reply_for_header` SQL | ✗ NOT WIRED | Query has run/status scope but no `em.epoch = pr.reply_epoch`. |
| clarification review state | operator actions/template | delivery-review routes | ✗ NOT WIRED | `ClarificationDeliveryReview` is emitted but rejected by `_load_delivery_review`. |
| eval chart | delivery/persistence | module boundary | ✓ WIRED (isolated) | Boundary tests and eval check pass. |

## Data-Flow Trace (Level 4)

| Artifact | Data variable | Source | Produces real data | Status |
|---|---|---|---|---|
| `send_outbound.py` | provider payload | `load_outbound_snapshot` → stored envelope/bytes | Yes | ✓ FLOWING |
| confirmation delivery | PDF/YTD inputs | reconciled history query on absent snapshot only | Yes | ✓ FLOWING |
| delivery review card | safe facts/artifact links | owned review projection and attachment reader | Yes | ✓ FLOWING, but clarification review disconnected |
| eval chart | aggregate metrics | committed fixtures/scoring output | Yes | ✓ FLOWING |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Phase-focused implementation regression | `uv run pytest -q tests/test_send_idempotency.py tests/test_delivery.py tests/test_queue_drain.py tests/test_clarify.py tests/test_dashboard.py tests/test_gateway.py tests/test_orchestrator_states.py tests/test_repo_jobs_sql.py tests/test_job_kind_drift.py` | 339 passed, 8 skipped | ✓ PASS |
| Named replay/fence/clarification/authorization transitions | `uv run pytest -q` with 10 named tests | 10 passed | ✓ PASS |
| Whole repository regression | `uv run pytest -q` | 1080 passed, 78 skipped | ✓ PASS |
| Eval regression | `uv run python eval/run_eval.py --check` and `uv run pytest -q tests/test_eval.py tests/test_pdf.py` | check passed; 27 passed | ✓ PASS |
| Type/lint quality | `uv run mypy` on 12 implementation files; `uv run ruff check` on phase implementation | no issues; all checks passed | ✓ PASS |
| Configured Postgres settlement/trigger proof | `uv run pytest -q -m integration tests/test_queue_durability.py` | 42 skipped; no DATABASE_URL/ALLOW_DB_RESET | ? UNAVAILABLE EVIDENCE |

## Probe Execution

No phase-declared or conventional `scripts/*/tests/probe-*.sh` probes were found.

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| SEND-01 | 20-01, 20-02, 20-03, 20-04, 20-05, 20-09, 20-10, 20-12 | Reuse one reserved Message-ID and one durable send path per approved epoch | ✗ BLOCKED | Normal snapshot/job/idempotency paths pass; final-lease duplicate path, stale header routing, and logical email-id fencing remain. |
| SEND-02 | 20-01, 20-03, 20-04, 20-07, 20-09, 20-10, 20-12 | Replay exact persisted subject/body/PDF bytes with bounded retry | ✗ BLOCKED | Snapshot/PDF/YTD replay passes; settlement can replay an arbitrary retryable result and live DB proof is unavailable. |
| SEND-03 | 20-02, 20-03, 20-05, 20-06, 20-08, 20-09, 20-10, 20-11, 20-12 | Idempotency header, bounded ambiguity, safe human review, and isolated recruiter evidence | ✗ BLOCKED | Header and confirmation review paths pass; clarification review is not wired, fake parity is incomplete, and final send ambiguity bypasses review. |

## Anti-Patterns Found

No unreferenced `TBD`, `FIXME`, or `XXX` markers, placeholder implementations, console-only handlers, or hardcoded empty user-visible data were found in the phase implementation/test files. The findings below are correctness/wiring defects, not debt-marker matches.

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| `app/db/repo/job_settlement.py` | 722-768 | Generic final-lease reaper for SEND_OUTBOUND | 🛑 BLOCKER | Ambiguous accepted sends can be retriggered as fresh confirmations. |
| `app/db/repo/job_settlement.py` | 279-300 | Retry outcome without category allowlist | 🛑 BLOCKER | Unsafe/permanent failures may be automatically replayed. |
| `app/db/repo/job_settlement.py` | 81-225 | Claimed email identity supplied by caller | 🛑 BLOCKER | Lease token does not fence logical snapshot identity. |
| `app/db/repo/emails.py` | 795-800 | Header routing lacks current epoch | 🛑 BLOCKER | Stale clarification replies can resume the wrong round. |
| `app/routes/runs.py` | 257-291 | Confirmation-only delivery review loader | 🛑 BLOCKER | Clarification delivery ambiguity has no operator-safe route. |
| `tests/conftest.py` | 808-893 | Fake send validation/attempt budget drift | ⚠️ WARNING | Tests can accept malformed send jobs and miss production attempt policy. |
| `app/db/repo/jobs.py` / `app/db/repo/job_settlement.py` | 240-264 / 210-225 | Opposite lock order | ⚠️ WARNING | Retry-now/worker races can deadlock and lose operator acceleration. |
| `app/db/repo/emails.py` | 344-345 | Body included in bounded review projection | ⚠️ WARNING | Unnecessary PII exposure to projection callers. |
| `tests/conftest.py` | 1524-1526 | Fake review attempts hardcoded to zero | ⚠️ WARNING | Nonzero attempt evidence is not tested through the fake. |
| `app/db/repo/emails.py` | 661-677 | Broad legacy email-state mutator | ⚠️ WARNING | Inbound/arbitrary state mutation remains reachable. |

## Human Verification Required

The automated gate is blocked before browser/UAT can be authoritative. After the blockers are fixed, manually verify the clarification delivery-review card, frozen-question evidence, retry/handled actions, and stale-epoch reply behavior in a browser. Visual appearance and end-to-end external-provider behavior remain human checks.

## Gaps Summary

The phase successfully implements the normal immutable snapshot → identifier-only job → snapshot gateway → lease settlement path, and all available unit/fake/full-suite checks pass. The phase goal is nevertheless not achieved because the most failure-sensitive paths are incomplete: final lease expiry bypasses delivery review, replay eligibility is not enforced at settlement, claimed logical email identity is not fenced, stale headers ignore the current epoch, and clarification ambiguity has no operator workflow. Fake parity and projection/mutator hygiene also need correction. The live Postgres proofs were skipped because the required database configuration is absent; they must be run after the code gaps are closed.

**Next action:** fix the five blocker paths first (final-lease send handling, epoch predicate, replay category gate, persisted email-id fence, clarification review workflow), then fix the parity/wiring warnings, run the configured Postgres queueproof and full suite, and re-verify Phase 20.

---

_Verified: 2026-07-17T21:54:11Z_  
_Verifier: the agent (gsd-verifier)_
