---
phase: 20-exactly-once-send
reviewed: 2026-07-17T23:41:58Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - app/db/repo/job_settlement.py
  - app/db/repo/jobs.py
  - app/db/repo/__init__.py
  - app/db/schema.sql
  - app/db/repo/emails.py
  - app/routes/runs.py
  - app/templates/run_detail.html
  - app/static/style.css
  - tests/conftest.py
  - tests/test_send_idempotency.py
  - tests/test_queue_durability.py
  - tests/test_clarify.py
  - tests/test_queue_drain.py
  - tests/test_repo_jobs_sql.py
  - tests/test_threading.py
  - tests/test_phase20_repo_hygiene.py
  - tests/test_phase20_fake_parity.py
  - tests/test_dashboard.py
  - tests/test_phase20_clarification_review.py
findings:
  critical: 5
  warning: 6
  info: 0
  total: 11
status: issues_found
---

# Phase 20: Code Review Report

**Reviewed:** 2026-07-17T23:41:58Z
**Depth:** standard  
**Files Reviewed:** 19
**Status:** issues_found

## Narrative Findings (AI reviewer)

## Summary

The review covered the Phase 20 persistence fences, delivery settlement, queue/retry behavior, current-epoch routing, clarification review actions, and the in-memory fake. The focused suite passed (`234 passed, 51 skipped`), but the implementation still has several correctness and security gaps that tests do not cover. Most seriously, an old epoch can suppress a new confirmation or send a stale frozen email, and clarification review endpoints can be reached through confirmation-only actions by direct POST.

## Critical Issues

### CR-01: Sent confirmation idempotency is not scoped to the current reply epoch

**File:** `/Users/pnhek/usf msds/github/payroll_agent/app/db/repo/emails.py:420-429`
**Issue:** `get_outbound_message_id()` finds any sent outbound confirmation for the run and purpose, without requiring `email_messages.epoch` to equal `payroll_runs.reply_epoch`. After a retrigger increments the epoch, `app/pipeline/delivery.py` treats an old epoch's sent message as proof that the new confirmation was already delivered and skips creating/sending the current confirmation. This can silently suppress a required payroll email.
**Fix:** Add the current-epoch predicate to this query and pass the run id to the correlated lookup, for example `AND epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s)`. Add a regression test with a sent epoch-0 confirmation followed by a delivery attempt in epoch 1.

### CR-02: Old-epoch send jobs can reach the provider after a retrigger

**File:** `/Users/pnhek/usf msds/github/payroll_agent/app/db/repo/job_settlement.py:151-179`, `/Users/pnhek/usf msds/github/payroll_agent/app/queue/handlers/send_outbound.py:55-80`
**Issue:** Retriggering bumps `reply_epoch` but does not cancel old `SEND_OUTBOUND` jobs. The handler checks that the snapshot epoch is a nonnegative integer and that the run is in an authorized status, but never checks `snapshot.epoch == payroll_runs.reply_epoch`. A stale frozen clarification or confirmation can therefore be sent once the retriggered run reaches the same status. Settlement and final-attempt reaping also accept the reservation without a current-epoch check, so they cannot repair this before or after the provider call.
**Fix:** Under the run lock, require the snapshot/message epoch to equal the current `reply_epoch` before calling the provider and again in settlement/reaping. On an epoch bump, explicitly terminalize or cancel old send jobs; if a stale job is still held by a worker, complete it as a stale no-op under the exact lease rather than leaving it eligible for reclaim.

### CR-03: Confirmation-only delivery actions accept clarification reviews

**File:** `/Users/pnhek/usf msds/github/payroll_agent/app/routes/runs.py:1011-1022`, `/Users/pnhek/usf msds/github/payroll_agent/app/routes/runs.py:1039-1069`
**Issue:** Both `mark_delivery_delivered()` and `authorize_new_confirmation()` call `_load_delivery_review()` but do not require `review_kind == "confirmation"`. A direct POST against a `ClarificationDeliveryReview` can mark a run waiting for a client reply as reconciled, or clone the clarification question into a new `purpose="confirmation"` reservation and enqueue it for delivery. The template hides these forms for clarification reviews, but that is not an endpoint authorization boundary.
**Fix:** Reject unless the loaded review is non-null and has `review_kind == "confirmation"` before any CAS, epoch bump, snapshot clone, or enqueue. Add negative tests for both endpoints that assert no run, email, or job mutation occurs for a clarification review.

### CR-04: Operator mutation routes have no authentication or CSRF protection

**File:** `/Users/pnhek/usf msds/github/payroll_agent/app/routes/runs.py:390-447`, `/Users/pnhek/usf msds/github/payroll_agent/app/routes/runs.py:450-581`, `/Users/pnhek/usf msds/github/payroll_agent/app/routes/runs.py:934-1087`
**Issue:** Approval, rejection, alias resolution, retrigger, delivery retry, delivery completion, and new-confirmation authorization are executable by any caller able to POST a run UUID. The typed acknowledgement is only a form value, not operator authentication, and there is no CSRF token or Origin protection. On a deployed service, a guessed/leaked run id or cross-site form can approve payroll, write aliases, alter state, or authorize a second outbound email.
**Fix:** Require an authenticated operator identity and authorization on every mutating run route, add CSRF protection (or strict same-origin and one-time form tokens), and keep any unauthenticated demo trigger isolated from payroll mutation endpoints.

### CR-05: Context-fenced jobs can remain leased after the drain discards the worker token

**File:** `/Users/pnhek/usf msds/github/payroll_agent/app/db/repo/job_settlement.py:220-255`, `/Users/pnhek/usf msds/github/payroll_agent/app/queue/drain.py:194-245`
**Issue:** `settle_outbound_delivery_job()` returns `FENCED` both when the lease token is lost and when the worker still owns the lease but the run status/context is no longer valid. The drain treats every `FENCED` result as settled and drops its held token, while the SQL path does not transition the still-leased job. A stale send job can consequently remain leased until timeout, be reclaimed later, and be final-reaped into a misleading delivery review instead of being durably retired as stale.
**Fix:** Separate `LOST_LEASE` from `INVALID_CONTEXT`. For an exact current lease with an invalid epoch/status, atomically mark the job done/dead with a bounded stale-context reason (or release it explicitly); only discard the worker token after a corresponding durable state transition.

## Warnings

### WR-01: Generic delivery retry is not purpose-isolated

**File:** `/Users/pnhek/usf msds/github/payroll_agent/app/routes/runs.py:934-947`, `/Users/pnhek/usf msds/github/payroll_agent/app/db/repo/jobs.py:225-271`
**Issue:** `retry_delivery_now()` uses the generic review loader and generic `advance_existing_send_job_due_now()` without requiring a confirmation review. It can be posted for a clarification review and advance its frozen job through a confirmation-shaped recovery path. The current operation is mostly a same-row retry, but it violates the Phase 20 action boundary and leaves the generic repository method able to mutate a clarification reservation without checking purpose or review marker.
**Fix:** Require `review_kind == "confirmation"` in the generic route and enforce the same purpose/status invariant in the repository method; leave clarification retry on its dedicated method only.

### WR-02: Fake queue claiming does not model delay or expired-lease recovery

**File:** `/Users/pnhek/usf msds/github/payroll_agent/tests/conftest.py:915-937`
**Issue:** The fake `claim_job()` claims any pending job immediately, ignoring `available_in_seconds`, and never reclaims expired leased jobs. Its generic due-now operation also locks/checks the snapshot before the job, while production locks the job first. Tests using the fake can therefore pass for retries that should still be delayed and cannot exercise crash recovery or the production lock/order contract.
**Fix:** Store comparable `available_at` and `leased_until` values in the fake, claim only due pending jobs or expired leases with the same attempt rules, and mirror production's job-first checks. Add parity tests for delayed retry and expired lease reclaim.

### WR-03: Outbound References can cross reply epochs

**File:** `/Users/pnhek/usf msds/github/payroll_agent/app/db/repo/emails.py:695-717`
**Issue:** `get_outbound_references_chain()` selects the most recent sent outbound message for a run without filtering to the current `reply_epoch`. A retriggered confirmation can therefore inherit a stale epoch's Message-ID in its `References` header, confusing threading and allowing a new workflow epoch to be attached to an old conversation.
**Fix:** Filter the chain to the current epoch, or explicitly build the new chain from the current inbound root and current-epoch outbound messages only. Add a retrigger/threading regression test.

### WR-04: Provider success can be rolled back by roster loading during confirmation completion

**File:** `/Users/pnhek/usf msds/github/payroll_agent/app/db/repo/job_settlement.py:182-204`
**Issue:** `_complete_confirmation_after_send()` loads the business roster before the guarded alias-write block. If roster loading fails after the provider has accepted the email, the surrounding transaction aborts before the sent attempt, message state, and run completion are committed. The job can then be retried or reaped without a durable local record of the provider acceptance, undermining the exactly-once audit fence.
**Fix:** Make the provider-acceptance ledger, message transition, and job completion commit independently of best-effort alias learning; load/calculate alias updates after the durable send settlement or catch roster-load failures and record them without rolling back the send outcome.

### WR-05: Snapshot and message identity are duplicated without a database equality constraint

**File:** `/Users/pnhek/usf msds/github/payroll_agent/app/db/schema.sql:451-465`
**Issue:** `outbound_email_snapshots` stores both `email_id` and a copied `message_id`, but the schema does not enforce that the copied value matches `email_messages.message_id`. The handler and settlement use these persisted values as identity fences; a malformed or future direct SQL insertion can make the provider envelope, audit row, and threading identity disagree.

**Fix:** Remove the redundant snapshot `message_id` and join the canonical email row, or enforce the relationship with a trigger/transactional insert and verify the canonical message id while locking the reservation.

### WR-06: Fake failure recording does not match production's bounded/scrubbed error detail

**File:** `/Users/pnhek/usf msds/github/payroll_agent/tests/conftest.py:1037-1051`
**Issue:** The fake stores `str(error)[:200]` directly, while production builds sanitized error detail. This can let tests pass with exception text containing secrets or personal data and fails to exercise the production redaction contract.

**Fix:** Reuse the same `_build_error_detail()` behavior in the fake (or expose a shared pure helper) and add a test asserting sensitive exception text is not persisted.

---

_Reviewed: 2026-07-17T23:41:58Z_
_Reviewer: the agent (gsd-code-reviewer)_  
_Depth: standard_
