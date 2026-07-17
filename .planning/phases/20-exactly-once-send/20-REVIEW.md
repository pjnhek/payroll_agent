---
phase: 20-exactly-once-send
reviewed: 2026-07-17T21:45:39Z
depth: standard
files_reviewed: 39
files_reviewed_list:
  - app/db/repo/__init__.py
  - app/db/repo/demo.py
  - app/db/repo/emails.py
  - app/db/repo/job_settlement.py
  - app/db/repo/jobs.py
  - app/models/job.py
  - app/pipeline/clarification.py
  - app/pipeline/delivery.py
  - app/pipeline/pdf.py
  - app/pipeline/send_guard.py
  - app/queue/dispatch.py
  - app/queue/drain.py
  - app/queue/handlers/send_outbound.py
  - app/routes/runs.py
  - app/static/style.css
  - app/templates/run_detail.html
  - eval/chart.svg
  - eval/run_eval.py
  - tests/conftest.py
  - tests/test_alias_full_loop.py
  - tests/test_alias_write.py
  - tests/test_clarify.py
  - tests/test_clarify_rounds.py
  - tests/test_dashboard.py
  - tests/test_delivery.py
  - tests/test_demo_fixtures.py
  - tests/test_demo_landing.py
  - tests/test_eval.py
  - tests/test_hitl.py
  - tests/test_job_kind_drift.py
  - tests/test_needs_operator.py
  - tests/test_pdf.py
  - tests/test_queue_drain.py
  - tests/test_queue_durability.py
  - tests/test_repo_jobs_sql.py
  - tests/test_retrigger_epoch.py
  - tests/test_retrigger_threading.py
  - tests/test_send_idempotency.py
  - tests/test_threading.py
findings:
  critical: 5
  warning: 5
  info: 0
  total: 10
status: issues_found
---

# Phase 20: Code Review Report

**Reviewed:** 2026-07-17T21:45:39Z  
**Depth:** standard  
**Files Reviewed:** 39  
**Status:** issues_found

## Summary

The immutable first-send snapshot and normal lease-aware send path are present, but several failure and replay paths do not preserve the same exactly-once invariants. In particular, final lease expiry can bypass delivery review, the replay policy is broader than the documented allowlist, and the lease fence does not verify the snapshot identity. The clarification review path and the in-memory test repository also diverge materially from production behavior.

## Critical Issues

### CR-01: Final lease expiry can hide an accepted send and permit a duplicate confirmation

**File:** `app/db/repo/job_settlement.py:722-765`
**Severity:** BLOCKER

**Issue:** `reap_expired_final_attempt` treats every non-`INGEST` final lease the same. It does not special-case `SEND_OUTBOUND`, preserve its immutable reservation, or create `DeliveryReview` after a worker may have crashed after the provider accepted the message but before settlement. For a confirmation job, the reaper instead changes the run to `ERROR` and marks the job dead. The generic retrigger route then clears the reply context/bumps the epoch and can compose and reserve another confirmation, while the first provider request remains ambiguous. This is a direct duplicate-send path. Clarification jobs can also be left awaiting a reply without a delivery-review action.

**Fix:** Handle `SEND_OUTBOUND` explicitly in the final-lease reaper. Lock the reservation, append the bounded attempt fact, and route ambiguous confirmation delivery to `DeliveryReview` (and clarification delivery to its corresponding review state) without allowing a generic retrigger to compose a new copy. Add crash-after-provider-acceptance tests for both purposes.

### CR-02: Stale pre-retrigger headers can resume the current reply round

**File:** `app/db/repo/emails.py:795-800`
**Severity:** BLOCKER

**Issue:** `find_awaiting_reply_for_header` joins every outbound message for an awaiting run but does not require the message epoch to equal the run's current `reply_epoch`. After a retrigger bumps the epoch and the run sends a new clarification, a reply quoting the old clarification's `Message-ID` can still match the run and be treated as the current answer. That can apply stale client input to the wrong clarification round.

**Fix:** Add the current-epoch predicate to this routing query, for example `AND em.epoch = pr.reply_epoch`. Keep the all-status header lookup separate for late-reply observability, and add a regression test with a stale outbound header after an epoch bump.

### CR-03: Any retryable delivery result is automatically replayed

**File:** `app/db/repo/job_settlement.py:279-300`
**Severity:** BLOCKER

**Issue:** The settlement code schedules another attempt whenever `result.outcome is RETRYABLE` and the time window is open. It computes a failure category, but never uses that category or the reason to enforce the documented D-02 replay allowlist. `PipelineResult` accepts retryable results for authentication, validation, configuration, payload-mismatch, and unknown reasons, so a caller or future gateway classifier can cause those permanent or unsafe failures to be replayed automatically. Payload mismatch is especially dangerous because replay must not send a potentially different payload.

**Fix:** Define an explicit set of replayable delivery reasons/categories (timeout, connection failure, eligible rate limiting, and provider 5xx) and schedule a retry only for that set. Route all other failures directly to operator review, with payload mismatch terminal and visible. Add parameterized tests for every non-replayable category.

### CR-04: Lease fencing does not fence the claimed snapshot identity

**File:** `app/db/repo/job_settlement.py:81-95`
**Severity:** BLOCKER

**Issue:** `_locked_job` verifies the job ID and lease token, but selects only attempts, max attempts, run ID, and kind. `settle_outbound_delivery_job` then uses `job.email_id` from the caller to lock and mutate the outbound reservation without comparing it with the persisted job row's `email_id`. A stale, forged, or otherwise mismatched claimed object with a valid job ID/token can therefore settle a different snapshot and mark the wrong email sent/reviewed. The exact lease token is not sufficient logical identity fencing.

**Fix:** Select the persisted `email_id` in `_locked_job` and require it to equal the claimed value before any reservation or attempt mutation; return `FENCED` on mismatch. Prefer making the job's logical identifiers immutable as well, and add a regression test that changes the claimed email ID and verifies no delivery or run state is written.

### CR-05: Clarification delivery review has no corresponding operator workflow

**File:** `app/routes/runs.py:257-291`
**Severity:** BLOCKER

**Issue:** Settlement can set `error_reason` to `ClarificationDeliveryReview` for a terminal clarification delivery (`app/db/repo/job_settlement.py:308-321`), but `_load_delivery_review` only accepts `error_reason == "DeliveryReview"` and only loads a confirmation-purpose snapshot. The template likewise renders review controls only for confirmation (`app/templates/run_detail.html:110-147`). A failed clarification can therefore appear as the generic unresolved-name state, with no frozen-question evidence and no retry/mark-delivered/operator-authorized action. The operator may be led to resolve names even though the question may never have reached the client.

**Fix:** Add a purpose-aware clarification delivery-review projection and actions for replaying the same frozen question within the window, marking delivery handled, or rejecting it. Do not route this state through alias resolution. Add dashboard coverage for `ClarificationDeliveryReview`.

## Warnings

### WR-01: Retry-now and settlement acquire locks in opposite order

**File:** `app/db/repo/jobs.py:240-264`
**Severity:** WARNING

**Issue:** `advance_existing_send_job_due_now` locks the snapshot/message first and then the job, while `settle_outbound_delivery_job` locks the job first and then the reservation. A concurrent operator retry and worker settlement can form a PostgreSQL deadlock; the route catches the exception and redirects without waking the job, so the operator's retry can be lost rather than safely retried.

**Fix:** Establish one lock order for both paths, preferably job then snapshot/reservation, and add a concurrent retry-versus-settlement test.

### WR-02: The fake queue accepts malformed send jobs and uses the wrong attempt budget

**File:** `tests/conftest.py:808-893`
**Severity:** WARNING

**Issue:** The in-memory `enqueue_job` validates the four older job kinds but has no `SEND_OUTBOUND` branch requiring `run_id`, `email_id`, and the exact send deduplication key. It accepts arbitrary send-job context and defaults `max_attempts` to 5, while production forces the send ladder to 8 (`app/db/repo/jobs.py:57,180-183`). Queue and producer tests using the fake can therefore pass invalid jobs and miss production rejection or retry-budget behavior.

**Fix:** Mirror production's `SEND_OUTBOUND` validation, deduplication requirements, and forced eight-attempt budget in the fake. Add parity tests that mutate each required field and assert both repositories reject it identically.

### WR-03: The fake delivery-review projection always reports zero attempts

**File:** `tests/conftest.py:1512-1530`
**Severity:** WARNING

**Issue:** The production delivery-review projection counts rows in the append-only attempt ledger, but the fake projection hardcodes `attempt_count` to `0`. Dashboard and send-idempotency tests consequently never exercise nonzero attempt counts or catch a broken attempt projection, even though the count is part of the operator evidence.

**Fix:** Add an attempt ledger to the fake, increment it from fake settlement, and test review projections with one and multiple attempts.

### WR-04: The bounded delivery-review projection returns the frozen message body

**File:** `app/db/repo/emails.py:335-367`
**Severity:** WARNING

**Issue:** `get_delivery_review_snapshot` is documented as a bounded projection that excludes provider request/response payloads, but its SQL still selects `snapshot.body_text` at line 345. The current route omits that field from its safe response and separately loads the body only for the authorized frozen-email view, so this is not an immediate endpoint leak; however, the repository contract unnecessarily exposes immutable payroll/client content to every caller of the review projection and makes accidental PII disclosure easy.

**Fix:** Remove `snapshot.body_text` from the bounded review projection and retain body access only in the explicitly authorized frozen-email reader. Update the fake and projection tests accordingly.

### WR-05: Legacy email-state mutation can update inbound rows and arbitrary states

**File:** `app/db/repo/emails.py:661-677`
**Severity:** WARNING

**Issue:** `update_email_message_state` updates by `message_id` alone, without constraining `direction` to outbound or validating the requested state. Despite its legacy/synthetic-outbound documentation, a caller can mutate an inbound audit row or write an invalid send state. This leaves a public repository API that can corrupt the immutable delivery record if reused by compatibility code.

**Fix:** Remove/fail-closed the legacy mutator, or constrain it to outbound rows and an explicit allowed state transition set. Add a test proving inbound rows and invalid states are rejected.

---

_Reviewed: 2026-07-17T21:45:39Z_  
_Reviewer: the agent (gsd-code-reviewer)_  
_Depth: standard_
