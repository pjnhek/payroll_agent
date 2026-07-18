---
phase: 20-exactly-once-send
reviewed: 2026-07-18T01:33:07Z
depth: standard
files_reviewed: 45
files_reviewed_list:
  - app/db/repo/__init__.py
  - app/db/repo/demo.py
  - app/db/repo/emails.py
  - app/db/repo/job_settlement.py
  - app/db/repo/jobs.py
  - app/db/repo/runs.py
  - app/db/schema.sql
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

Phase 20 correctly freezes the provider envelope, reuses its idempotency key, fences settlement/reaping with the current epoch, and isolates confirmation review actions from clarification reviews. The focused Phase 20 suite also passed: 269 passed, 52 skipped. One race remains in the provider preflight, so the phase's current-epoch send guarantee is not complete.

## Narrative Findings (AI reviewer)

### BLOCKER — The provider call is not fenced against a retrigger that lands after the epoch read

- Location: `app/queue/handlers/send_outbound.py:66-89`
- Evidence: `handle_send_outbound()` loads the frozen snapshot, then separately reads the run and compares `snapshot["epoch"]` with `run["reply_epoch"]` at lines 70-79. Neither read takes or retains a run-row lock, and the provider request at line 89 occurs later, outside a transaction. A concurrent operator retrigger can therefore commit `clear_reply_context()` (which increments `reply_epoch`) after line 79 and before `gateway.send_reserved_outbound_snapshot()`. The stale epoch's confirmation/clarification is then sent. Settlement subsequently detects the epoch mismatch and retires the old job, but that is after the irreversible provider side effect. The existing stale-epoch tests only bump the epoch before entering the handler and do not exercise this interleaving.
- Impact: This violates the explicitly required current-reply-epoch fence before the provider call. In particular, a human retrigger can intentionally open a fresh epoch while a stale worker still delivers the old payload, defeating the per-epoch authorization boundary even though Resend deduplicates duplicate requests for that old Message-ID.
- Remediation: Add a durable pre-send authorization/fence that serializes against `clear_reply_context` and remains valid through the provider handoff (for example, lock the run plus exact leased job/snapshot in one transaction and introduce a fenced, provider-attempt state that retrigger must reject or wait on). Recheck the exact lease token, snapshot epoch, run epoch, purpose-appropriate status, and replay window in that boundary; only then invoke the provider. Add a concurrent regression that pauses immediately after the preflight, performs a real epoch bump in a second connection, then proves the stale worker cannot call the gateway.
