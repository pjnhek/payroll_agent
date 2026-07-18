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
  critical: 0
  warning: 0
  info: 0
  total: 0
status: clean
---

# Phase 20: Code Review Report

**Reviewed:** 2026-07-18T00:00:00Z
**Depth:** standard
**Files Reviewed:** 49
**Status:** clean

## Summary

The durable send path preserves the immutable snapshot through authorization,
provider dispatch, settlement, and delivery review. The pre-provider and
gateway-boundary expiration paths now both append the bounded
`authorization_expired` fact and transition the purpose-owned run to delivery
review without provider I/O. Settlement releases only the exact handoff owner,
and retrigger is fenced while a committed handoff remains active.

The deployed-schema repair recreates the same bounded failure-category
vocabulary used by fresh installs, including `authorization_expired`. The
two-connection queue proofs no longer execute SQL before their intended outer
transactions, so their authorization commit is observable before the race
interleaving begins.

The prior expired-reservation review finding is resolved by the handler's
explicit `replay_window_closed` result and the settlement branch that performs
the no-handoff delivery-review transition.

## Verification

- `uv run pytest -q tests/test_send_idempotency.py tests/test_delivery.py tests/test_queue_drain.py tests/test_queue_durability.py -m 'not integration'` — 125 passed, 61 deselected.
- `uv run ruff check` across the reviewed Python files — passed.

## Findings

No actionable BLOCKER or WARNING findings.

_Reviewed: 2026-07-18T00:00:00Z_
_Reviewer: generic-agent workaround (gsd-code-reviewer)_
_Depth: standard_
