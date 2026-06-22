---
phase: 5
slug: dashboard-delivery
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-22
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `05-RESEARCH.md` → Validation Architecture + Security Domain.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (dev dep in `pyproject.toml`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest -q -m "not integration and not live_llm"` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~15–30 seconds (mocked suite); integration adds live-DB time |

**Markers:** `integration` (requires live local DB), `live_llm` (requires real API keys — never run in CI/gates).

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q -m "not integration and not live_llm"` (full mocked suite, no live deps)
- **After every plan wave:** Run `uv run pytest -q -m "not live_llm"` (includes integration tests against live local DB)
- **Before `/gsd-verify-work`:** Full suite green (`uv run pytest -q`)
- **Max feedback latency:** ~30 seconds (mocked suite)

---

## Per-Task Verification Map

> Task IDs are assigned by the planner. This map is keyed by requirement + target test file so each
> plan task can cite the row it satisfies. Threat refs map to `05-RESEARCH.md` → Security Domain.

| Requirement | Behavior | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|----------|------------|-----------------|-----------|-------------------|-------------|--------|
| FOUND-04 | `claim_status` returns True on first caller, False on concurrent second | Double-approval (Repudiation) | CAS closes double-approval; DB audit trail provides repudiability | unit | `uv run pytest tests/test_claim_status.py -x -q` | ❌ W0 | ⬜ pending |
| FOUND-04 | `claim_status` + psycopg3 live-DB race (two callers race approve) → exactly one wins | Double-approval (Repudiation) | Atomic conditional UPDATE; one row returned | integration | `uv run pytest tests/test_claim_status.py -m integration -x` | ❌ W0 | ⬜ pending |
| D-01b | `_safe_to_learn_alias("D. Reyes", david, seed_roster)` is False (David+Daniel both carry it) | Silent misroute (Tampering) | Write-side collision guard refuses ambiguous tokens | unit | `uv run pytest tests/test_alias_write.py -x -q` | ❌ W0 | ⬜ pending |
| D-01b | `_safe_to_learn_alias(unambiguous_token, …)` is True; append is idempotent | Silent misroute (Tampering) | Only unambiguous tokens learned; no double-add | unit | `uv run pytest tests/test_alias_write.py -x -q` | ❌ W0 | ⬜ pending |
| D-05 | `validate()` emits `ValidationIssue` for weekly emp `hours_regular=45`, no OT field | Silent underpay (Integrity) | Over-40-no-OT detected → gates to clarify | unit | `uv run pytest tests/test_validate.py -x -q` | ✅ extend | ⬜ pending |
| D-05 | `validate()` emits `ValidationIssue` for biweekly emp `hours_regular=85`, no OT | Silent underpay (Integrity) | >80 sufficient trigger (partial detection) | unit | `uv run pytest tests/test_validate.py -x -q` | ✅ extend | ⬜ pending |
| D-05 | `validate()` does NOT flag biweekly emp `hours_regular=78` | — | No false-positive below threshold | unit | `uv run pytest tests/test_validate.py -x -q` | ✅ extend | ⬜ pending |
| D-05 | `validate()` does NOT flag semi-monthly/monthly emp regardless of hours | — | Documented limitation (period cuts workweeks) | unit | `uv run pytest tests/test_validate.py -x -q` | ✅ extend | ⬜ pending |
| D-05 | `validate()` flags explicit `hours_overtime=0` with weekly `hours_regular=45` | Silent underpay (Integrity) | Explicit-zero treated as absent (recommended flag) | unit | `uv run pytest tests/test_validate.py -x -q` | ✅ extend | ⬜ pending |
| HITL-03 | `generate_paystub_pdf()` returns non-empty bytes for a real `PaystubLineItem` | PDF data exposure (Info Disclosure) | In-memory only; no disk persist | unit | `uv run pytest tests/test_pdf.py -x -q` | ❌ W0 | ⬜ pending |
| HITL-03 | `generate_paystub_pdf()` bytes start with `b'%PDF'` | — | Valid PDF magic bytes | unit | `uv run pytest tests/test_pdf.py -x -q` | ❌ W0 | ⬜ pending |
| HITL-02 | `compose_confirmation()` returns template floor when LLM raises | Strand-on-failure (Availability) | Draft failure never strands an approved send | unit | `uv run pytest tests/test_compose_confirmation.py -x -q` | ❌ W0 | ⬜ pending |
| HITL-02 | `compose_confirmation()` returns template floor when LLM returns None | Strand-on-failure (Availability) | Deterministic floor on empty draft | unit | `uv run pytest tests/test_compose_confirmation.py -x -q` | ❌ W0 | ⬜ pending |
| D-13b | Delivery path error boundary: exception after claim → run advances to ERROR (not stuck in `approved`) | Strand (Availability) | `approved` removed from `_TERMINAL_STATUSES`; `record_run_error` fires; `error_reason` is `type(exc).__name__` only (no PII) | unit (FakeConnection) | `uv run pytest tests/test_delivery.py -x -q` | ❌ W0 | ⬜ pending |
| CLAR-04 | Idempotent send: `get_outbound_message_id` returns existing row → skip send, advance | Double-send (Integrity) | Already-sent guard; intent row before send (D-13c) | unit (FakeConnection) | `uv run pytest tests/test_delivery.py -x -q` | ❌ W0 | ⬜ pending |
| DASH-01 | `GET /runs` returns 200 with run rows in the response | SQLi via path param (Tampering) | Parameterized queries only | behavior | `uv run pytest tests/test_dashboard.py -x -q -m integration` | ❌ W0 | ⬜ pending |
| DASH-02 | `GET /runs/{id}` returns 200 with raw-body, extracted, paystubs columns visible | Template injection (Tampering); SQLi via run_id (Tampering) | Jinja2 auto-escape; UUID path validation + parameterized query | behavior | `uv run pytest tests/test_dashboard.py -x -q -m integration` | ❌ W0 | ⬜ pending |
| DASH-04 | `GET /eval` returns 200, SVG chart referenced, headline metrics present | — | Hermetic read of committed artifacts (no DB, no live eval) | behavior | `uv run pytest tests/test_dashboard.py -x -q` | ❌ W0 | ⬜ pending |
| DASH-05 | `POST /demo/send-test` with clean fixture → run created | SSRF (Tampering) | Committed fixture, no URL param → no SSRF surface | behavior | `uv run pytest tests/test_dashboard.py -x -q -m integration` | ❌ W0 | ⬜ pending |
| DASH-03 | Approve/reject/re-trigger via `<form method=post>` → 303 redirect; bounded approve wall-clock | Double-approval (Repudiation) | `claim_status` gate on every operator transition; hard draft timeout (D-10b) | behavior | `uv run pytest tests/test_dashboard.py -x -q -m integration` | ❌ W0 | ⬜ pending |
| INGEST-05 | Re-trigger re-runs from start; claim from `error` AND `approved`; already-sent check prevents duplicate confirmation | Double-send (Integrity); Strand (Availability) | Claim + already-sent guard make re-trigger structurally non-duplicating | unit (FakeConnection) + behavior | `uv run pytest tests/test_delivery.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Highest-Risk Units (priority test targets)

1. **`claim_status` race (FOUND-04, D-12)** — all four gates depend on it; a wrong impl is *silent* (no crash, wrong behavior under concurrency). Test two `FakeConnection`s racing the conditional UPDATE → exactly one True; plus a live psycopg3 two-connection race.
2. **D-01b alias-write collision exclusion** — a wrong impl silently misroutes a money-moving decision on camera (the "D. Reyes" trap). Test the trap explicitly.
3. **Delivery path strand recovery (D-13b)** — `FakeConnection` raising after a winning claim must drive `approved → error` (requires `approved` removed from `_TERMINAL_STATUSES`).
4. **`compose_confirmation` template floor (HITL-02)** — patch `llm.call_text` to raise; assert a non-empty floor string, not an exception. Mirror existing `test_clarify.py`.

---

## Wave 0 Requirements

- [ ] `tests/test_claim_status.py` — FOUND-04, D-12 (unit + `integration` variants)
- [ ] `tests/test_alias_write.py` — D-01b collision exclusion + idempotency
- [ ] `tests/test_pdf.py` — HITL-03 PDF generator pure function
- [ ] `tests/test_compose_confirmation.py` — HITL-02 template floor on failure
- [ ] `tests/test_delivery.py` — D-13b error boundary + CLAR-04/INGEST-05 idempotent send + re-trigger
- [ ] `tests/test_dashboard.py` — DASH-01/02/03/04/05 route smoke tests
- [ ] `tests/test_validate.py` — **EXTEND** existing file with D-05 OT-rule cases
- [ ] `tests/conftest.py` — extend shared fixtures (seed roster incl. David/Daniel Reyes pair; `FakeConnection`)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 3-column run-detail visually reads correctly (raw email leftmost, extracted middle, paystubs right) | DASH-02 | Visual/layout fidelity not assertable past 200-OK + content presence | Open `/runs/{id}` on a real run; confirm 3-col grid, status banner with gate reasons, monospace `<pre>` for raw email |
| Status badge colors (pending-action emphasized, terminal-good green, terminal-bad red) | DASH-01 | CSS class → color mapping is visual | Open `/runs`; confirm badge classes render with intended emphasis |
| Confirmation email + per-employee PDF attachments arrive and render (stub gateway → captured payload) | HITL-02, HITL-03 | End-to-end attach path; visual PDF check | Approve a run; inspect captured outbound payload + open each attached PDF |
| Demo third beat — clarify once, then learns (alias not re-asked on re-run) | D-01..D-04 | Cross-run narrative behavior | Run unambiguous-shorthand fixture → clarify → approve; re-run same shorthand → resolves with no clarification |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (7 new test files + 1 extend)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s (mocked suite)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
