---
phase: 05-dashboard-delivery
plan: "02"
subsystem: tests
tags: [tdd, wave-0, red-stubs, hitl, delivery, dashboard, pdf]
dependency_graph:
  requires: []
  provides:
    - tests/test_pdf.py
    - tests/test_compose_confirmation.py
    - tests/test_delivery.py
    - tests/test_dashboard.py
    - tests/conftest.py (seed_roster fixture)
  affects:
    - app/pipeline/pdf.py (Wave 2 must satisfy test_pdf.py)
    - app/pipeline/compose_email.py (Wave 2 must add compose_confirmation)
    - app/db/repo.py (Wave 1 must add claim_status, purpose= to get_outbound_message_id, ON CONFLICT to insert_email_message)
    - app/main.py (Wave 3 must add /runs, /eval, /demo/send-test routes)
tech_stack:
  added: []
  patterns:
    - Wave 0 RED-first TDD stubs (Nyquist contract)
    - FakeConnection offline SQL assertion (conftest pattern)
    - FastAPI TestClient for route smoke tests
key_files:
  created:
    - tests/test_pdf.py
    - tests/test_compose_confirmation.py
    - tests/test_delivery.py
    - tests/test_dashboard.py
  modified:
    - tests/conftest.py
decisions:
  - "Fake-LLM stubs in test_compose_confirmation.py use **kwargs to absorb timeout_s=3.0 (MEDIUM finding fix); this prevents a false-positive TypeError failure in the uses-draft-when-present test"
  - "test_dashboard.py uses follow_redirects=False (not allow_redirects) per httpx API — auto-fixed (Rule 1)"
  - "seed_roster fixture returns Business 2 employees (biz2_id) not Business 1 — only Business 2 contains the David+Daniel Reyes collision pair"
  - "test_dashboard.py tests that accept 404/405 as valid Wave 0 behavior (test_run_detail, test_eval_no_summary, test_uuid_validation) pass now and will continue to pass once routes are added"
metrics:
  duration: "5m"
  completed_date: "2026-06-23"
  tasks_completed: 2
  files_changed: 5
---

# Phase 05 Plan 02: Wave 0 RED Stubs (Batch B) Summary

Wave 0 test stubs — batch B. Four new test files plus a conftest extension, all failing RED because the production implementations (pdf.py, compose_confirmation, delivery path, dashboard routes) do not yet exist.

## What Was Built

**Task 1: test_pdf.py + test_compose_confirmation.py**

- `tests/test_pdf.py`: 3 RED stubs asserting `generate_paystub_pdf()` returns bytes starting with `b'%PDF'`, is non-empty, and is pure (no DB dependency). Fails `ModuleNotFoundError` on missing `app.pipeline.pdf`.
- `tests/test_compose_confirmation.py`: 4 RED stubs mirroring `test_clarify.py` structure — template floor on LLM exception, template floor on empty/None draft, uses draft when present, floor contains net_pay. Fails `ImportError` on `compose_confirmation` not yet in `compose_email.py`.
- CRITICAL fix: both `_DraftLLM` and `_RaisingDraftLLM` stubs define `call_text(self, tier, messages, **kwargs)` with `**kwargs` — absorbs `timeout_s=3.0` from compose_confirmation without raising TypeError (MEDIUM finding fix).

**Task 2: test_delivery.py + test_dashboard.py + conftest extension**

- `tests/test_delivery.py`: 9 RED stubs covering:
  - `test_approved_not_in_terminal_statuses`: APPROVED must not be in `_TERMINAL_STATUSES` (D-13b)
  - `test_delivery_error_converts_approved_to_error`: D-13b error boundary with PII-safe logging
  - `test_idempotent_confirmation_skips_if_confirmation_outbound_exists`: CLAR-04 purpose-aware idempotency (finding #1, `purpose='confirmation'`)
  - `test_clarify_idempotency_skips_if_clarification_already_sent`: _clarify idempotency (finding #2, `purpose='clarification'`)
  - `test_retrigger_claims_from_error_state`: INGEST-05 retrigger
  - `test_retrigger_claims_from_approved_state`: D-13b recovery
  - `test_retrigger_claims_from_stale_extracting_state`: finding #6 stale-state recovery
  - `test_send_outbound_over_reserved_row_advances_to_sent`: NEW-1 upsert
  - `test_send_outbound_over_failed_row_advances_to_sent`: NEW-1 failed-row variant
  Fails `ImportError` on `claim_status` not yet in `app.db.repo`.

- `tests/test_dashboard.py`: 7 tests (4 RED) covering DASH-01..05:
  - RED: `test_runs_list_returns_200` (GET /runs missing)
  - PASS in Wave 0: `test_run_detail_returns_200_or_404` (accepts 404)
  - RED: `test_eval_view_returns_200` (GET /eval missing)
  - RED: `test_send_test_returns_303` (POST /demo/send-test missing)
  - PASS in Wave 0: `test_eval_returns_200_no_summary_json` (accepts 404)
  - PASS in Wave 0: `test_runs_invalid_uuid_returns_422` (accepts 404/405)
  - RED (integration): `test_send_test_mints_fresh_message_id_each_click` (finding MEDIUM)

- `tests/conftest.py`: added `seed_roster` fixture returning Business 2 Roster (David Reyes e0000003 + Daniel Reyes e0000007 collision pair, both `known_aliases=["D. Reyes"]`).

## RED State Verification

All new tests fail RED for the correct reasons:
- `test_pdf.py`: `ModuleNotFoundError: No module named 'app.pipeline.pdf'`
- `test_compose_confirmation.py`: `ImportError: cannot import name 'compose_confirmation'`
- `test_delivery.py`: `ImportError: cannot import name 'claim_status'`
- `test_dashboard.py`: 4 tests fail with `AssertionError: ... got 404` (routes not yet added)

Existing mocked suite baseline: 284 passed, 30 pre-existing failures (unchanged by this plan).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed TestClient `allow_redirects` kwarg**
- **Found during:** Task 2 (first run of test_dashboard.py)
- **Issue:** `TestClient.post()` in this project's httpx version uses `follow_redirects=False`, not `allow_redirects=False`. The TypeError caused a test error rather than a clean RED failure.
- **Fix:** Changed two occurrences of `allow_redirects=False` to `follow_redirects=False` in test_dashboard.py.
- **Files modified:** `tests/test_dashboard.py`
- **Commit:** 9e33604 (included in Task 2 commit)

## Known Stubs

All intentional — this plan IS the stub creation:

| File | Stub Type | Reason |
|------|-----------|--------|
| `tests/test_pdf.py` | ImportError stub | `app/pipeline/pdf.py` doesn't exist yet (Wave 2) |
| `tests/test_compose_confirmation.py` | ImportError stub | `compose_confirmation` not yet in `compose_email.py` (Wave 2) |
| `tests/test_delivery.py` | ImportError stub | `claim_status` not yet in `repo.py` (Wave 1) |
| `tests/test_dashboard.py` | Missing-route stubs | Dashboard routes not yet in `main.py` (Wave 3) |

## Threat Flags

None. This plan creates only test files — no new network endpoints, auth paths, file access patterns, or schema changes.

## Self-Check: PASSED
