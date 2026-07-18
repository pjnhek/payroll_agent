---
phase: 20-exactly-once-send
reviewed: 2026-07-18T00:00:00Z
depth: standard
files_reviewed: 49
files_reviewed_list:
  - app/db/repo/__init__.py
  - app/db/repo/demo.py
  - app/db/repo/emails.py
  - app/db/repo/job_settlement.py
  - app/db/repo/jobs.py
  - app/db/repo/outbound_handoffs.py
  - app/db/repo/pipeline_state.py
  - app/db/repo/runs.py
  - app/db/schema.sql
  - app/email/gateway.py
  - app/models/job.py
  - app/pipeline/clarification.py
  - app/pipeline/delivery.py
  - app/pipeline/pdf.py
  - app/pipeline/result.py
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
  - tests/test_gateway.py
  - tests/test_hitl.py
  - tests/test_job_kind_drift.py
  - tests/test_needs_operator.py
  - tests/test_pdf.py
  - tests/test_phase20_clarification_review.py
  - tests/test_phase20_fake_parity.py
  - tests/test_phase20_repo_hygiene.py
  - tests/test_queue_drain.py
  - tests/test_queue_durability.py
  - tests/test_repo_jobs_sql.py
  - tests/test_retrigger_epoch.py
  - tests/test_retrigger_threading.py
  - tests/test_send_idempotency.py
  - tests/test_threading.py
findings:
  critical: 1
  warning: 0
  info: 0
  total: 1
status: issues_found
---

# Phase 20: Code Review Report

**Reviewed:** 2026-07-18T00:00:00Z
**Depth:** standard
**Files Reviewed:** 49
**Status:** issues_found

## Summary

Reviewed the immutable snapshot, fenced provider handoff, settlement, delivery-review, retrigger, and fake-parity paths. The provider-handoff fence correctly blocks an epoch bump after authorization, but an already-expired reservation takes a no-provider path that is retired as invalid context. This silently leaves a live confirmation run approved rather than escalating its ambiguous delivery state for operator review.

## Critical Issues

### CR-01: Expired reservation is dropped without delivery review

**File:** `app/queue/handlers/send_outbound.py:55-58`; `app/db/repo/outbound_handoffs.py:275-276`; `app/db/repo/job_settlement.py:401-413`
**Issue:** When a claimed `SEND_OUTBOUND` job is first handled after its reservation’s 20-hour window has expired, `authorize_outbound_provider_handoff()` returns `ProviderHandoffActive("replay_window_closed")` without creating a handoff. The handler collapses that outcome into a successful no-op. Settlement then cannot lock a handoff, retires the exact job as `invalid_context`, and returns without changing the run from `approved`/`awaiting_reply` to purpose-specific `needs_operator`. Thus a delayed initial send or delayed retry can disappear silently instead of entering the required delivery-review state; the fake repository reproduces the same behavior at `tests/conftest.py:1353-1358`.

**Fix:** Preserve the authorization outcome’s reason at the handler/settlement boundary. For `replay_window_closed`, settle the leased reservation directly into the existing purpose-aware delivery-review transition (append a bounded `authorization_expired` attempt, complete the job, and set the run to the appropriate `needs_operator` marker) without requiring a provider handoff. Add production and fake-parity tests that claim a snapshot with `reserved_at <= now() - interval '20 hours'` and assert zero provider calls, a completed job, and the delivery-review status.

---

_Reviewed: 2026-07-18T00:00:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
