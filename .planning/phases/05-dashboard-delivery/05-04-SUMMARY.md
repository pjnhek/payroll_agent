---
phase: "05"
plan: "04"
subsystem: pipeline
tags: [pdf, email, pure-function, hitl, tdd]
dependency_graph:
  requires:
    - "05-03"
  provides:
    - generate_paystub_pdf
    - compose_confirmation
    - confirmation_subject
  affects:
    - app/pipeline/pdf.py
    - app/pipeline/compose_email.py
    - app/llm/client.py
tech_stack:
  added: []
  patterns:
    - reportlab SimpleDocTemplate + BytesIO (in-memory PDF, Render ephemeral FS safe)
    - compose_clarification clone pattern (try/except + fallback floor)
    - call_text timeout_s kwarg (D-10b hard timeout on draft tier)
key_files:
  created:
    - app/pipeline/pdf.py
    - tests/test_pdf.py
    - tests/test_compose_confirmation.py
  modified:
    - app/pipeline/compose_email.py
    - app/llm/client.py
decisions:
  - "timeout_s added as named param + **kwargs to call_text (not pure **kwargs) for clarity and IDE discoverability while still absorbing fake-LLM stubs"
  - "PDF uses Table + SimpleDocTemplate (not Canvas) per plan — simpler, tabular layout"
  - "Pre-existing test failures (30) with missing DATABASE_URL env var are out-of-scope — tests pass GREEN when DATABASE_URL is set"
metrics:
  duration: "5 min"
  completed: "2026-06-23"
  tasks_completed: 2
  files_changed: 5
---

# Phase 05 Plan 04: Delivery Foundations (Pure Functions) Summary

**One-liner:** Pure BytesIO PDF generator (reportlab) + compose_confirmation clone with hard 3s timeout + call_text **kwargs fix so the "uses_draft_when_present" canary GREEN.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | generate_paystub_pdf pure function | 231a05a | app/pipeline/pdf.py, tests/test_pdf.py |
| 2 | compose_confirmation + confirmation_subject + call_text **kwargs | 57235fd | app/pipeline/compose_email.py, app/llm/client.py, tests/test_compose_confirmation.py |

## Verification Results

```
tests/test_pdf.py::test_generate_paystub_pdf_returns_bytes         PASSED
tests/test_pdf.py::test_generate_paystub_pdf_valid_pdf_magic       PASSED
tests/test_pdf.py::test_generate_paystub_pdf_pure_no_db            PASSED
tests/test_compose_confirmation.py::...template_floor_on_llm_exception  PASSED
tests/test_compose_confirmation.py::...template_floor_on_empty_draft    PASSED
tests/test_compose_confirmation.py::...uses_draft_when_present          PASSED  (canary)
tests/test_compose_confirmation.py::...floor_contains_net_pay           PASSED

7 passed — full mocked suite: 321 passed, 0 failed (with DATABASE_URL=test)
```

## What Was Built

### Task 1: app/pipeline/pdf.py (new)

`generate_paystub_pdf(item, employee_full_name, pay_period_start, pay_period_end) -> bytes`

- Pure function: BytesIO only, nothing written to disk (HITL-03, Render ephemeral FS)
- reportlab SimpleDocTemplate + Table, in-memory buf.getvalue() returns bytes
- Returns bytes starting with b'%PDF' (valid PDF magic bytes)
- UI-SPEC Column 3 row order: Employee, Pay Period, Gross Pay, Pre-tax 401k (if non-zero), Social Security (6.2%), Medicare (1.45%), Federal Withholding, Net Pay
- Omits State Withholding row when state_withholding is None or zero (DASH-02)
- Adds "Additional Medicare (0.9% over $200k) not modeled" footnote when flag is True
- No imports of psycopg, repo, or any DB module

### Task 2: compose_email.py additions + client.py fix

**`_confirmation_template_body(paystubs, run) -> str`**
- Deterministic floor (D-10): fires when draft times out or fails, never strands the send
- Format per UI-SPEC copywriting contract: opens with reviewed/approved, per-employee net pay lines, closes with contact us

**`confirmation_subject(run: dict) -> str`**
- Returns: `"Payroll Confirmation — {business_name} — {pay_period_label}"`
- Uses dict.get() with safe fallbacks

**`compose_confirmation(paystubs, run, *, llm, timeout_s=3.0) -> str`**
- Exact clone of compose_clarification pattern (DRY)
- Passes timeout_s=3.0 to llm.call_text as keyword argument (D-10b)
- Broad except catches timeout + API errors → falls to floor (T-05-10, T-05-11)
- Log messages use type(exc).__name__ only (D-A1-03 PII safety)

**`call_text` in client.py: `timeout_s: float | None = None, **kwargs`**
- Adds named timeout_s param + **kwargs to absorb test fake stubs (MEDIUM finding fix)
- When timeout_s is not None, passes `timeout=timeout_s` to OpenAI client constructor
- Backward-compatible: existing callers (compose_clarification) unaffected

## Deviations from Plan

None - plan executed exactly as written.

**Pre-existing environmental issue noted (out of scope):** 30 tests in test_llm_client.py, test_orchestrator_states.py, test_threading.py, test_webhook.py fail when `DATABASE_URL` env var is absent. These failures pre-date this plan — they pass GREEN when `DATABASE_URL=postgresql://test:test@localhost:5432/test` is set. Root cause: `Settings` class requires `database_url` with no default (D-04 design intent). Not caused by any change in this plan; not fixed per scope-boundary rule. Logged for operator awareness.

## Known Stubs

None — both functions return real data (bytes / string). No placeholder values.

## Threat Surface Scan

No new network endpoints, auth paths, or file system access introduced. Both functions are pure (data in → artifact out). Existing threat mitigations verified:
- T-05-10 (cold-dyno LLM latency): timeout_s=3.0 wired
- T-05-11 (total LLM failure): floor is always non-empty
- T-05-11b (TypeError from missing **kwargs): call_text + stubs accept **kwargs
- T-05-12 (payroll data in PDF): accepted (demo, no disk write, no auth)
- T-05-13 (error logging PII): type(exc).__name__ only, no str(exc)

## Self-Check

<br>

### File Existence

- [x] app/pipeline/pdf.py — FOUND
- [x] app/pipeline/compose_email.py — FOUND (modified)
- [x] app/llm/client.py — FOUND (modified)
- [x] tests/test_pdf.py — FOUND
- [x] tests/test_compose_confirmation.py — FOUND

### Commit Existence

- [x] 231a05a: feat(05-04): generate_paystub_pdf pure function (Task 1)
- [x] 57235fd: feat(05-04): compose_confirmation + confirmation_subject + call_text **kwargs fix (Task 2)

## Self-Check: PASSED
