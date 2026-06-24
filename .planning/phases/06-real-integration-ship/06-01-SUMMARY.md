---
phase: "06"
plan: "01"
subsystem: "test-infrastructure"
tags: ["resend", "xfail", "wave-0", "gateway", "dedup", "threading", "health"]
dependency_graph:
  requires: []
  provides:
    - "resend==2.32.2 runtime dep (pyproject.toml + uv.lock)"
    - "Resend SDK mock fixtures in conftest.py (_FakeResendReceivedEmail, mock_resend_verify, mock_resend_send)"
    - "xfail gateway test stubs (D-17 verify, D-01a two-step, D-18 headers, D-13c ordering, D-14 threading)"
    - "dedup unit test (GREEN immediately — existing route + repo handle D-13)"
    - "health endpoint xfail stubs (D-20 liveness + readiness, xfail until 06-02)"
  affects:
    - "06-04 (xfail markers are the trigger to remove when gateway is wired)"
    - "06-02 (health xfail markers removed when /health/live + /health/ready added)"
tech_stack:
  added:
    - "resend==2.32.2 (Resend Python SDK: Webhooks.verify, EmailsReceiving.get, Emails.send)"
    - "requests==2.34.2 (transitive dep via resend)"
    - "urllib3==2.7.0 (transitive dep via resend)"
  patterns:
    - "xfail(strict=True) stub pattern: XFAIL exits 0, XPASS exits nonzero (the 06-04 signal)"
    - "mock_resend_verify / mock_resend_send: monkeypatch.setattr on resend.Webhooks and resend.Emails"
    - "_FakeResendReceivedEmail: mixed-case header keys to exercise Pitfall 4 normalization path"
    - "RELATIVE order assertions in test_send_outbound_reserved_before_sent_ordering (MEDIUM-6)"
key_files:
  created: []
  modified:
    - "pyproject.toml — added resend==2.32.2 to [project.dependencies]"
    - "uv.lock — updated atomically with resend + transitive deps"
    - "tests/conftest.py — added import resend + 4 Phase 6 Resend SDK mock fixtures"
    - "tests/test_gateway.py — added 12 tests (1 GREEN, 10 XFAIL, 1 integration XFAIL)"
    - "tests/test_ingest.py — added 2 dedup tests (1 unit GREEN, 1 integration skipped)"
    - "tests/test_dashboard.py — added 2 health tests (2 XFAIL until 06-02)"
decisions:
  - "MEDIUM-6: test_send_outbound_reserved_before_sent_ordering uses RELATIVE order assertion (search for 'reserved' in fake_conn.executed, assert it precedes send call) rather than absolute index [0]/[1] — absolute indexing breaks under D-14 because get_outbound_references_chain adds a DB READ before the reserved INSERT"
  - "test_parse_inbound_canonical_fixture_still_works has NO xfail — it must stay GREEN throughout all waves as the HIGH-2 fixture-path guard"
  - "_run_pipeline and _resume_pipeline (underscore prefix) are the actual function names in app.main — not run_pipeline/resume_pipeline (fixed via Rule 1 auto-fix during Task 2)"
metrics:
  duration: "9 minutes"
  completed_date: "2026-06-24"
  tasks: 2
  files_modified: 6
---

# Phase 06 Plan 01: Wave 0 Resend Package + xfail Test Stubs Summary

Installed `resend==2.32.2` runtime dependency, added Resend SDK mock fixtures to `tests/conftest.py`, and wrote 15 new xfail/green test stubs that encode the Phase 6 security/correctness requirements before any implementation exists.

## What Was Built

### Task 1: resend==2.32.2 + conftest mock fixtures

- Ran `uv add resend==2.32.2` from the main repo, then synced `pyproject.toml` and `uv.lock` to the worktree
- Added `import resend` to conftest.py imports (module availability for monkeypatching)
- Added `_FakeResendReceivedEmail` inner class with mixed-case header keys (exercises the A1/Pitfall 4 normalization path)
- Added four fixtures:
  - `fake_received_email` — minimal ReceivedEmail stand-in for gateway tests
  - `mock_resend_verify` — monkeypatches `resend.Webhooks.verify` to no-op (happy path)
  - `mock_resend_verify_reject` — monkeypatches verify to raise `ValueError("bad sig")` (D-17 reject)
  - `mock_resend_send` — monkeypatches `resend.Emails.send` to return fake response, captures calls

### Task 2: xfail test stubs

**tests/test_gateway.py** (12 new tests):

| Test | Status | Requirement |
|------|--------|-------------|
| `test_parse_inbound_canonical_fixture_still_works` | GREEN (no xfail) | HIGH-2 fixture-path guard |
| `test_verify_raises_on_bad_signature` | XFAIL 06-04 | D-17 signature reject |
| `test_verify_passes_on_valid_signature` | XFAIL 06-04 | D-17 signature happy path |
| `test_parse_inbound_two_step_fetch` | XFAIL 06-04 | D-01a two-step fetch |
| `test_parse_inbound_normalizes_headers_case_insensitively` | XFAIL 06-04 | D-18/Pitfall 4 |
| `test_parse_inbound_dedup_keys_on_rfc_message_id` | XFAIL 06-04 | D-13 dedup key |
| `test_parse_inbound_parseaddr_display_name` | XFAIL 06-04 | D-18/LOW-9 |
| `test_send_outbound_reserved_before_sent_ordering` | XFAIL 06-04 | D-13c/MEDIUM-6 |
| `test_send_outbound_failed_on_provider_exception` | XFAIL 06-04 | HIGH-3 reserved→failed |
| `test_threading_references_rebuilt_from_db_state` | XFAIL 06-04 | D-14 durable threading |
| `test_inbound_reply_routes_to_correct_run` | XFAIL 06-04 | MEDIUM-7/D-14 routing |
| `test_inbound_reply_routes_to_correct_run_integration` | XFAIL 06-04 + integration | D-14 real SQL predicate |

**tests/test_ingest.py** (2 new tests):

| Test | Status | Requirement |
|------|--------|-------------|
| `test_duplicate_delivery_pipeline_runs_once_unit` | GREEN (no xfail) | D-13 dedup gate |
| `test_duplicate_delivery_pipeline_runs_once` | SKIPPED (no live DB) + integration | D-13 end-to-end dedup |

**tests/test_dashboard.py** (2 new tests):

| Test | Status | Requirement |
|------|--------|-------------|
| `test_health_live_returns_200_no_db` | XFAIL 06-02 | D-20 liveness |
| `test_health_ready_returns_200_with_db` | XFAIL 06-02 + integration | D-20 readiness |

## Verification Results

All plan verification checks passed:

1. `uv run python -c "import resend; print(resend.__version__)"` → `2.32.2` ✓
2. `grep "resend==2.32.2" pyproject.toml` → exits 0 ✓
3. `uv run pytest tests/test_gateway.py -k "canonical_fixture" -v` → PASSED ✓
4. `uv run pytest tests/test_gateway.py -k "verify" -v` → XFAIL ✓
5. `uv run pytest tests/test_ingest.py::test_duplicate_delivery_pipeline_runs_once_unit` → PASSED ✓
6. All 12 new xfail tests: XFAIL (exit code 0) ✓

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Internal pipeline function names use underscore prefix**
- **Found during:** Task 2 implementation of `test_duplicate_delivery_pipeline_runs_once_unit`
- **Issue:** The plan referred to `run_pipeline` and `resume_pipeline` as the functions to monkeypatch in `app.main`, but the actual function names are `_run_pipeline` and `_resume_pipeline` (private, underscore-prefixed)
- **Fix:** Updated both test_ingest.py and test_gateway.py to patch `_main._run_pipeline` and `_main._resume_pipeline` correctly
- **Files modified:** `tests/test_ingest.py`, `tests/test_gateway.py`
- **Commit:** 91a19a9

### Pre-existing Baseline Failures (Out of Scope)

The worktree baseline already had 30 pre-existing failing tests in `tests/test_threading.py`, `tests/test_clarify.py`, `tests/test_demo_fixtures.py`, `tests/test_extract.py`, `tests/test_llm_client.py`, `tests/test_orchestrator_states.py`, and `tests/test_webhook.py`. These failures existed before any changes from this plan and are not caused by plan 06-01. The plan expected "422 passing tests" but the baseline shows 378 passing (30 pre-existing failures). This is a gap to document — the pre-existing failures are out of scope per the SCOPE BOUNDARY rule.

The no-op-swap invariant was preserved: our changes added 2 new GREEN tests and 11 new XFAIL tests, with zero new FAILED tests.

## Known Stubs

None. All test stubs are intentionally marked `xfail(strict=True)` as designed — they are Wave 0 contracts, not accidental stubs. The xfail markers are the spec; 06-04 removes them.

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 1b74ea2 | chore | add resend==2.32.2 runtime dep + conftest Resend mock fixtures |
| 91a19a9 | test | Wave 0 xfail stubs — gateway/ingest/dashboard (OPS-01/OPS-02) |

## Self-Check: PASSED

- pyproject.toml contains `resend==2.32.2`: FOUND
- uv.lock updated: FOUND (3 new packages: resend, requests, urllib3)
- tests/conftest.py has Resend fixtures: FOUND
- tests/test_gateway.py has 1036 lines (≥450 required): PASSED
- tests/test_ingest.py has 278 lines (≥120 required): PASSED
- tests/test_dashboard.py has 700 lines (≥670 required): PASSED
- Commits exist: 1b74ea2, 91a19a9 verified via git log
