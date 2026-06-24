---
phase: "06"
plan: "04"
subsystem: "gateway"
tags: [resend, webhook, gateway, auth, threading, send_outbound, xfail-cleanup]
dependency_graph:
  requires: ["06-03"]
  provides: ["06-05"]
  affects: ["app/email/gateway.py", "app/main.py", "app/db/repo.py", "tests/"]
tech_stack:
  added: []
  patterns:
    - "MEDIUM-5 verify-before-parse: signature check before json.loads"
    - "HIGH-2 dual-path: Resend-envelope vs canonical InboundEmail shape detection"
    - "HIGH-1-AUTH: resend.api_key set as first line of send_outbound"
    - "D-13c crash-safe ordering: reserved INSERT → provider call → failed/sent UPDATE"
    - "D-14 durable threading: get_outbound_references_chain before every send"
    - "HIGH-4 prod closure: ALLOW_UNSIGNED_FIXTURES=False rejects all unsigned POSTs before json.loads"
    - "REPLY-TO TOPOLOGY: conditional reply_to key in send dict (omitted when empty)"
key_files:
  created: []
  modified:
    - "app/email/gateway.py"
    - "app/main.py"
    - "app/db/repo.py"
    - "tests/test_gateway.py"
    - "tests/test_ingest.py"
    - "tests/test_webhook.py"
    - "tests/test_threading.py"
    - "tests/test_demo_fixtures.py"
    - "tests/conftest.py"
decisions:
  - "BLOCKER-2: ALLOW_UNSIGNED_FIXTURES=False is the prod default; flag absent from render.yaml"
  - "HIGH-1 schema waiver: email_messages has no provider_message_id or updated_at; Resend provider id is logged only (not persisted)"
  - "HIGH-1-AUTH: resend.api_key set as FIRST line of send_outbound (not at import time, not in parse_inbound only)"
  - "D-14 threading: last-hop append (prior chain from DB + new in_reply_to); sufficient for single-turn demo"
  - "InMemoryRepo extended with 06-04 repo helpers + no-op resend.Emails.send mock in fake_repo fixture"
  - "WARNING-1 remediation: all client fixtures in pipeline test files updated to set ALLOW_UNSIGNED_FIXTURES=true"
metrics:
  duration: "~120 minutes (context-resumed)"
  completed: "2026-06-24T02:40:28Z"
  tasks_completed: 4
  files_changed: 9
---

# Phase 06 Plan 04: Real Resend Gateway Wiring Summary

Real Resend provider wired behind the gateway seam with dual-path parse_inbound (Resend-envelope + canonical fixture), verified signature auth, crash-safe D-13c send ordering, D-14 durable threading rebuild from DB, HIGH-1-AUTH outbound key discipline, REPLY-TO topology fix, and ALLOW_UNSIGNED_FIXTURES prod closure — all 06-01 xfail stubs turned GREEN, 454 mocked tests passing.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 0 | SDK smoke-check (MEDIUM-5 guard) | 4959e9a | tests/test_gateway.py |
| 1 | Real gateway.py: verify(), dual-path parse_inbound, send_outbound | 4959e9a | app/email/gateway.py, app/db/repo.py, tests/test_gateway.py |
| 2 | /webhook/inbound route update + ALLOW_UNSIGNED dual-path + BLOCKER-2 tests | 4759e34 | app/main.py, tests/test_gateway.py, tests/test_ingest.py |
| 3 | Remove all xfail markers + no-op-swap invariant fix | a03737c | tests/test_gateway.py, tests/conftest.py, tests/test_webhook.py, tests/test_threading.py, tests/test_demo_fixtures.py |

## What Was Built

**app/email/gateway.py** — Completely rewritten from Phase 2 stub:
- `verify(raw_body, headers, signing_secret)`: wraps `resend.Webhooks.verify(VerifyWebhookOptions)` with svix-id/timestamp/signature header mapping. Raises ValueError on failure (propagates to route for 400).
- `parse_inbound(raw)` dual-path: structural detection via `_is_resend_envelope()` (checks `data.email_id` presence). Path A (Resend envelope): sets resend.api_key defensively, calls `resend.EmailsReceiving.get(email_id)`, normalizes headers case-insensitively, strips display names via `email.utils.parseaddr` (LOW-9). Path B (canonical): `InboundEmail.model_validate(raw)` passthrough.
- `send_outbound(...)`: HIGH-1-AUTH first line (`resend.api_key = get_settings().resend_api_key`); D-14 DB chain load via `repo.get_outbound_references_chain`; D-13c reserved INSERT before `resend.Emails.send`; try/except flips to `failed` state and re-raises; success path logs provider id (not persisted — HIGH-1 waiver); REPLY-TO TOPOLOGY (conditional `reply_to` key when `resend_reply_to` non-empty).
- LOG_WEBHOOK_DEBUG_IDS guard: `if os.getenv("LOG_WEBHOOK_DEBUG_IDS"):` logs only header key names + IDs (no PII).

**app/main.py** — `/webhook/inbound` route restructured:
- `async def inbound(request: Request, background_tasks: BackgroundTasks)`: captures `raw_body = await request.body()` as first line.
- MEDIUM-5 verify-before-parse ordering: signed requests (svix-* headers present) → `gateway.verify(raw_body, ...)` → 400 on failure BEFORE json.loads.
- HIGH-4 prod closure: unsigned + `allow_unsigned_fixtures=False` → 400 BEFORE json.loads.
- Dev mode (`allow_unsigned_fixtures=True`): proceeds to `gateway.parse_inbound(raw_body)`.

**app/db/repo.py** — Three new helpers:
- `get_outbound_references_chain(run_id, conn)`: loads most recent sent outbound references_header for D-14 threading rebuild.
- `update_email_message_sent(message_id, conn)`: delegates to `update_email_message_state(message_id, "sent")` — both state and message_id appear in params tuple (BLOCKER-3 test-compatible).
- `update_email_message_state(message_id, state, conn)`: `UPDATE email_messages SET send_state=%s WHERE message_id=%s` — two %s, no updated_at, no provider_message_id (HIGH-1 waiver confirmed).

**tests/conftest.py** — InMemoryRepo extended:
- Added `get_outbound_references_chain`, `update_email_message_sent`, `update_email_message_state` methods.
- `fake_repo` fixture now patches all three new repo helpers AND adds no-op `resend.Emails.send` mock so pipeline tests don't attempt live API calls.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_inbound_reply_routes_to_correct_run FIX-5 spoof guard mismatch**
- **Found during:** Task 2 (running test to verify it's XPASS after route change)
- **Issue:** Test monkeypatched `find_business_by_sender` to return a random UUID, but `awaiting_run["business_id"]` was a DIFFERENT random UUID — FIX-5 spoof guard compared the two and rejected the sender as a spoof, preventing `_resume_pipeline` from being called.
- **Fix:** Introduced a fixed `sender_business_id = uuid.uuid4()` used both in the `find_business_by_sender` mock and in `awaiting_run["business_id"]`.
- **Files modified:** tests/test_gateway.py
- **Commit:** 4759e34

**2. [Rule 2 - Missing Critical] InMemoryRepo missing 06-04 repo helpers**
- **Found during:** Task 3 (full mocked suite run: 16 tests failing with PoolTimeout)
- **Issue:** `send_outbound` now calls `get_outbound_references_chain`, `update_email_message_sent`, `update_email_message_state` via the real repo path (not patched in fake_repo). These tried to open a real DB pool connection, failed, and pipeline tests reached `error` status instead of `awaiting_reply` or `awaiting_approval`.
- **Fix:** Added all three methods to InMemoryRepo + patched them in fake_repo fixture. Also added no-op `resend.Emails.send` mock in fake_repo to prevent live API calls.
- **Files modified:** tests/conftest.py
- **Commit:** a03737c

**3. [Rule 3 - Blocking] WARNING-1 remediation: client fixtures returning 400**
- **Found during:** Task 3 (full mocked suite run: test_webhook.py, test_threading.py, test_demo_fixtures.py POSTs returning 400)
- **Issue:** After route change, canonical dict POSTs without svix-* headers return 400 in prod mode (correct behavior). But all `client` fixtures in the three test files didn't set `ALLOW_UNSIGNED_FIXTURES=true`, so their canonical-dict POST tests got 400 instead of 200.
- **Fix:** Updated `client` fixtures in `test_webhook.py`, `test_threading.py`, `test_demo_fixtures.py`, `test_ingest.py` to set `ALLOW_UNSIGNED_FIXTURES=true` + `DATABASE_URL` via monkeypatch (matching the pattern from Task 1's test updates).
- **Files modified:** tests/test_webhook.py, tests/test_threading.py, tests/test_demo_fixtures.py, tests/test_ingest.py
- **Commit:** a03737c

## Verification

### Done Criteria Met

- `uv run pytest -q -m "not integration and not live_llm"` → **454 passed, 0 failed** (no-op-swap invariant)
- `uv run pytest tests/test_gateway.py -v` → **36 passed, 3 skipped, 0 failed, 0 XPASS, 0 XFAIL** (only integration test remains skipped; no xfail markers in non-integration tests)
- Schema waiver confirmed: `grep "provider_message_id" app/db/schema.sql` exits non-zero; `grep "updated_at" app/db/schema.sql | grep email_messages` exits non-zero
- `grep "ALLOW_UNSIGNED_FIXTURES" render.yaml` exits 1 (absent from render.yaml — BLOCKER-2)
- `grep "await request.body()" app/main.py` exits 0
- `grep "EmailsReceiving.get" app/email/gateway.py` exits 0
- `grep "LOG_WEBHOOK_DEBUG_IDS" app/email/gateway.py` exits 0
- `grep "update_email_message_state" app/db/repo.py` exits 0
- HIGH-1-AUTH: `grep "resend.api_key" app/email/gateway.py` has >=2 matches (send_outbound first line + parse_inbound defensive)

### Remaining Acceptable Gaps

- `test_inbound_reply_routes_to_correct_run_integration` — @pytest.mark.integration; requires live DB + ALLOW_DB_RESET=1; correctly SKIPPED in mocked suite
- `test_parse_inbound_parseaddr_display_name` — xfail marker removed; test now passes GREEN (LOW-9 parseaddr implemented in gateway.py _parse_resend_envelope)

## Known Stubs

None — the gateway is fully wired. All send_outbound calls go to `resend.Emails.send` (mocked in tests via fake_repo; real in production). No placeholder text, no empty data sources wired to UI rendering from this plan.

## Self-Check: PASSED

- `app/email/gateway.py` — EXISTS ✓
- `app/main.py` — EXISTS ✓
- `app/db/repo.py` — EXISTS ✓
- `tests/test_gateway.py` — EXISTS ✓
- `tests/conftest.py` — EXISTS ✓
- Commit `4959e9a` — EXISTS ✓ (Task 0 + Task 1)
- Commit `4759e34` — EXISTS ✓ (Task 2)
- Commit `a03737c` — EXISTS ✓ (Task 3)
- Full mocked suite: 454 passed, 0 failed ✓
