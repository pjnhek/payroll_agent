---
phase: 05-dashboard-delivery
reviewed: 2026-06-22T00:00:00Z
depth: deep
files_reviewed: 17
files_reviewed_list:
  - app/db/repo.py
  - app/db/schema.sql
  - app/db/supabase.py
  - app/email/gateway.py
  - app/llm/client.py
  - app/main.py
  - app/pipeline/compose_email.py
  - app/pipeline/orchestrator.py
  - app/pipeline/pdf.py
  - app/pipeline/reconcile_names.py
  - app/pipeline/validate.py
  - app/templates/base.html
  - app/templates/eval.html
  - app/templates/run_detail.html
  - app/templates/runs_list.html
  - app/static/style.css
  - scripts/reset_stuck_runs.py
  - scripts/show_confirmation_subject.py
findings:
  critical: 0
  warning: 1
  info: 1
  total: 2
resolved:
  warning: 1   # WR-01 (non-latin-1 Content-Disposition) fixed via re.ASCII (commit 0278edf) + parametrized regression test
  info: 0      # IN-01 (load_all_runs SELECT pr.*) deferred -> todo 260623-07
status: resolved
resolution_note: >
  Round-3 verified all five REVIEW-2 fixes correct (incl. the IN-02 awaiting_reply / poll
  interaction — no reload loop, no list reload). It found ONE real regression in the
  REVIEW-2 CR-01 fix: re.sub kept unicode \w chars (>U+00FF) which 500 on Starlette's
  latin-1 header encode. Fixed with flags=re.ASCII (commit 0278edf); regression test now
  covers quote+CRLF injection AND two non-latin-1 names, asserting the header is latin-1
  encodable. Full suite 407 passed / 0 failed. IN-01 (SELECT pr.* in load_all_runs) is a
  low-priority consistency nit deferred to todo 260623-07.

# Phase 05: Code Review Report — Round 3

**Reviewed:** 2026-06-22
**Depth:** deep
**Files Reviewed:** 17
**Status:** issues_found

## Summary

This is the third review. All REVIEW-1 and REVIEW-2 findings were verified against the
submitted fixes. Four of the five REVIEW-2 targeted fixes are correct and complete. One
fix — CR-01 (Content-Disposition filename sanitization) — is functionally close but has
a residual crash-on-edge-case gap introduced by Python's unicode-aware `\w` in `re.sub`.

Fresh independent pass found no new security vulnerabilities, no logic errors in the
money-decision path, no SQL injection surface, no LLM-decides issues, and no XSS
(Jinja2 autoescape confirmed ON for `.html` files). The full list of prior-review fixes
and fresh scan results follows.

---

## REVIEW-2 Fix Verification

### CR-01 (REVIEW-2): Content-Disposition filename sanitization — PARTIAL REGRESSION

**Verdict: Incomplete fix.** The regex neutralizes CRLF, double-quote, null bytes, and
ASCII non-word characters correctly. However, Python's `re` module treats `\w` as
unicode-aware by default (PEP 3131 / Python 3 default). Unicode word characters beyond
the latin-1 range (U+00FF) — such as Turkish dotless-i `ı` (U+0131), Polish `ł`
(U+0142), Greek letters, Arabic, or CJK — pass through the filter unchanged. Starlette
encodes all HTTP header values using `latin-1` in `MutableHeaders.__setitem__` and
`Response.init_headers`. A `full_name` or `submitted_name` containing any character
above U+00FF causes `UnicodeEncodeError` when the `StreamingResponse` writes the
`Content-Disposition` header — a 500 Internal Server Error on `GET /runs/{id}/pdf/{emp}`.

Confirmed via code inspection of `starlette/responses.py` `init_headers` and
`starlette/datastructures.py` `MutableHeaders.__setitem__`, both of which call
`value.encode("latin-1")`.

Reproduced:
```python
import re
emp_name = "Ünsal Yılmaz"  # ı = U+0131, above latin-1 range
safe_name = re.sub(r"[^\w.\-]", "_", emp_name) or "employee"
# safe_name = 'Ünsal_Yılmaz' — ı survived the filter
f'attachment; filename="paystub_{safe_name}.pdf"'.encode("latin-1")
# -> UnicodeEncodeError: ordinal not in range(256)
```

Note: characters within latin-1 range (é, ü, ñ, etc., U+00C0–U+00FF) work fine; only
characters above U+00FF cause the crash. See WR-01 below.

### WR-01 (REVIEW-2): simulate-reply _route_reply return value check — CORRECT

`handled = _route_reply(...)` is checked; a non-None return logs a warning. The
unconditional `return RedirectResponse(...)` at line 770 executes in both branches
(handled and not-handled). Verified: no fall-through to 500.

### WR-02 (REVIEW-2): reset_stuck_runs = ANY(%s::text[]) parameterized — CORRECT

The `--fail-stuck` branch uses `= ANY(%s::text[])` with `list(IN_FLIGHT)` as the bound
parameter. No f-string SQL remains in the UPDATE statement. The interval construction
`(%s || ' minutes')::interval` with `str(minutes)` as the bound value is also safe
because `minutes` is produced by `int(args[1])` before binding — an injection attempt
via `args[1]` would raise `ValueError` from `int()` before reaching SQL.

### IN-01 (REVIEW-2): simulate-reply inserts synthetic row with run_id=run_id — CORRECT

The synthetic inbound row carries `run_id=run_id`. Verified it does NOT appear in the
"Sent Emails" section: `load_outbound_emails` filters `direction = 'outbound'` and the
insert uses `direction='inbound'`. `get_outbound_message_id` also filters
`direction = 'outbound'`, so the inbound row does not interfere. `find_awaiting_reply_for_header`
joins on `em.direction = 'outbound'`, so the inbound row is invisible to resume routing.
No adverse interactions found.

### IN-02 (REVIEW-2): awaiting_reply added to IN_FLIGHT_STATUSES — CORRECT, NO NEW RISKS

Traced the full interaction:

- **Reload loop risk**: None. The JS detail-page poller reloads only when `data.status`
  is NOT in `IN_FLIGHT`. While a run stays at `awaiting_reply`, the badge updates but no
  reload fires. The run parks harmlessly for up to 30 × 2 s = 60 s then the poller
  stops. No loop.

- **Badge flickering**: None. `awaiting_reply` maps to badge class `neutral`; the
  badge re-renders with the same class and label on each poll tick. Visually stable.

- **Runs-list page reload**: Not triggered. The runs-list JS (`runs_list.html`) only
  updates the badge in-place via `querySelector`; it does NOT call
  `window.location.reload()` regardless of status.

- **Settle-reload correctness**: When the run transitions from `awaiting_reply` →
  `extracting` → … → `awaiting_approval`, the detail-page poller detects
  `awaiting_approval` is not in `IN_FLIGHT` and fires exactly one `window.location.reload()`.
  This is correct: it pulls in the freshly-computed paystubs and decision banner.

- **Retrigger button**: Not shown for `awaiting_reply` (template gates on
  `['error', 'approved', 'received', 'extracting', 'computed', 'sent']`). Correct.

- **Simulate-reply form**: Gated on `run.status == 'awaiting_reply'` (literal string
  comparison). IN_FLIGHT membership does not affect this gate. Correct.

---

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: Content-Disposition filename crash on non-latin-1 unicode names (CR-01 regression)

**File:** `app/main.py:641`
**Issue:** `re.sub(r"[^\w.\-]", "_", emp_name)` uses Python 3's unicode-aware `\w`, which
matches unicode word characters (letters, digits, underscore) across all scripts — not just
ASCII. Characters like Turkish `ı` (U+0131), Polish `ł` (U+0142), or any character with a
codepoint above U+00FF pass through unchanged. Starlette's `Response.init_headers` then
encodes the `Content-Disposition` header value with latin-1
(`v.encode("latin-1")` in `starlette/datastructures.py`). This raises `UnicodeEncodeError`
and produces a 500 Internal Server Error for any employee whose name contains a character
above U+00FF (outside the latin-1 range). The crash is confined to the PDF download
endpoint; it does not affect pipeline correctness or payroll computation.

**Affected scope:** `GET /runs/{run_id}/pdf/{employee_id}` when the employee's
`full_name` or `submitted_name` contains a non-latin-1 unicode character.

**Fix:** Add `re.ASCII` flag to restrict `\w` to `[A-Za-z0-9_]` only:

```python
# app/main.py line 641
safe_name = re.sub(r"[^\w.\-]", "_", emp_name, flags=re.ASCII) or "employee"
```

This replaces every non-ASCII character (and any other non-ASCII non-word char) with
`_`. A Turkish employee "Ünsal Yılmaz" becomes `_nsal_Y_lmaz` — not pretty, but
latin-1 safe, no crash, no header injection. The alternative (`encode("latin-1",
errors="replace")`) would produce `Ünsal_Y?lmaz` (question marks for chars above
U+00FF), which is slightly more readable but the ASCII-flag approach is simpler.

---

## Info

### IN-01: load_all_runs uses SELECT pr.* — inconsistent with documented no-SELECT-* discipline

**File:** `app/db/repo.py:796-797`
**Issue:** `load_all_runs` uses `SELECT pr.*, b.name as business_name` rather than an
explicit column list. The project's documented discipline (repo.py docstring, line 46)
states "Read-backs that rebuild a contract use an explicit column list + dict_row." This
query returns a plain `dict`, not a Pydantic model with `extra="forbid"`, so there is no
crash risk from an unexpected column. However, the inconsistency means that a future
schema change adding a column to `payroll_runs` silently widens the payload returned to
the `runs_list` template without any call-site awareness.

**Fix:** Replace `SELECT pr.*` with an explicit column list aligned with what the
`runs_list.html` template actually uses:

```python
sql = (
    "SELECT pr.id, pr.business_id, pr.status, pr.extracted_data, pr.decision,"
    " pr.error_reason, pr.pay_period_start, pr.pay_period_end, pr.created_at,"
    " b.name as business_name"
    " FROM payroll_runs pr"
    " JOIN businesses b ON pr.business_id = b.id"
    " ORDER BY pr.created_at DESC"
)
```

This matches the no-SELECT-* discipline documented in the module and in PATTERNS.md.

---

_Reviewed: 2026-06-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
