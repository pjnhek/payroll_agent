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
  critical: 1
  warning: 3
  info: 2
  total: 6
resolved:
  critical: 1   # CR-01 Content-Disposition sanitized (commit 17525ee) + regression test
  warning: 2    # WR-01 + WR-02 fixed (17525ee); WR-03 deferred -> todo 260623-06
  info: 2       # IN-01 + IN-02 fixed (17525ee)
status: resolved
resolution_note: >
  CR-01 fixed (filename sanitized via re.sub, regression test guards CRLF/quote injection),
  WR-01 (simulate-reply checks _route_reply return), WR-02 (no f-string SQL in --fail-stuck),
  IN-01 (synthetic reply linked to run_id), IN-02 (awaiting_reply added to IN_FLIGHT_STATUSES)
  all fixed and verified. Full suite 405 passed / 0 failed. WR-03 (NEEDS_CLARIFICATION dead
  status — pre-existing, not introduced this phase) deferred to todo 260623-06 because the
  fix touches the status enum/schema and risks the schema-drift CI guard.
---

# Phase 05: Code Review Report (Round 2)

**Reviewed:** 2026-06-22
**Depth:** deep
**Files Reviewed:** 17
**Status:** issues_found

---

## Summary

This is the second adversarial review of the Phase 5 dashboard-delivery implementation. The three prior Criticals (CR-01/02/03) were not re-raised; the review focused exclusively on the ~19 commits of new code added after the first review.

The new surfaces reviewed: `POST /runs/{run_id}/simulate-reply`, the vanilla-JS status poll and badge updater, the PDF rewrite in `pdf.py`, the pre-vs-post diff alias-binding in `resume_pipeline`, the `load_outbound_emails` helper, and the dev scripts.

**High-level verdict:** The simulate-reply trust chain is sound — FIX-5 spoof revalidation executes correctly, the HITL gate is not bypassed, and the CAS claim prevents double-resume. The PDF is pure and in-memory; the deductions reconcile with the stored `net_pay`. The JS poll is XSS-safe (textContent, not innerHTML). The money-moving invariant (LLM never decides) is intact across the new resume path.

One Critical was found: a malformed `Content-Disposition` header in the PDF download route when an employee name (either from the DB or from LLM-extracted `submitted_name` as fallback) contains a double-quote character. Three Warnings and two Info items follow.

---

## Critical Issues

### CR-01: Content-Disposition header malformed / injectable for employee names containing double quotes

**File:** `app/main.py:628-632`

**Issue:** The PDF download route constructs the `Content-Disposition` filename by replacing spaces with underscores and then embedding the result directly into a double-quoted RFC 6266 token:

```python
safe_name = emp_name.replace(" ", "_")
return StreamingResponse(
    BytesIO(pdf_bytes),
    media_type="application/pdf",
    headers={"Content-Disposition": f'attachment; filename="paystub_{safe_name}.pdf"'},
)
```

`replace(" ", "_")` does not strip or escape double-quote characters (`"`), backslashes (`\`), or CRLF sequences (`\r\n`). A name containing a double quote — e.g. `Maria "Ria" Chen` — produces:

```
Content-Disposition: attachment; filename="paystub_Maria_"Ria"_Chen.pdf"
```

which breaks the quoted-string per RFC 7230 §3.2.6. More critically, a name containing `\r\n` (possible if LLM extraction emits it as the fallback submitted_name when the matched employee is not found in the roster) produces a header-injection payload:

```
Content-Disposition: attachment; filename="paystub_John\r\nX-Custom: injected.pdf"
```

Starlette does not sanitize header values before writing them to the wire; a proof-of-concept run confirms no exception is raised during response construction.

**Exploit path:** The normal code path (`emp.full_name` from the DB roster) is low-risk because employee names are seeded directly and NUMERIC/TEXT DB columns don't auto-inject CRLF. The `submitted_name` fallback path (used when `employee_id` is not found in the freshly-loaded roster, e.g. if the employee row was deleted after the run computed) uses LLM-extracted text that is only constrained by Pydantic's `str` type — no regex or character allowlist.

**Fix:** Use RFC 5987 percent-encoding for the filename, or at minimum strip / replace any characters outside `[A-Za-z0-9._\-]`:

```python
import re
safe_name = re.sub(r'[^\w.\-]', '_', emp_name)
# Or use RFC 5987 encoding for full correctness:
from urllib.parse import quote
safe_name_encoded = quote(emp_name, safe='')
headers = {
    "Content-Disposition": (
        f"attachment; filename=\"paystub_{safe_name}.pdf\"; "
        f"filename*=UTF-8''{safe_name_encoded}.pdf"
    )
}
```

The simple regex replacement is sufficient to eliminate the header-injection risk. The RFC 5987 form handles international characters correctly for full robustness.

---

## Warnings

### WR-01: simulate-reply discards `_route_reply` return value — silent no-op if FIX-5 spoof guard fires

**File:** `app/main.py:740`

**Issue:** The simulate-reply route calls `_route_reply(email, cleaned, background_tasks)` but discards its return value:

```python
_route_reply(email, cleaned, background_tasks)
logger.info("simulate-reply: synthetic reply submitted for run %s (demo-only)", run_id)
return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
```

`_route_reply` returns a `JSONResponse` in three distinct failure cases: (1) `sender_mismatch` if FIX-5 fires, (2) `late_reply` if the header matches a non-awaiting-reply run, (3) `None` if no match. In the real webhook path (line 188-190), the return value is checked:

```python
handled = _route_reply(email, cleaned, background_tasks)
if handled is not None:
    return handled
```

In simulate-reply, all three failure branches are silently absorbed into the "submitted" success log and a 303 redirect. In practice the only likely failure is FIX-5 (business deleted after run creation), which is a race condition on a demo app. However, the silent success-log for a failed resume is misleading for the operator debugging a stuck run.

**Fix:** Check the return value and log a warning if `_route_reply` returned a non-resume response:

```python
result = _route_reply(email, cleaned, background_tasks)
if result is not None:
    logger.warning(
        "simulate-reply: _route_reply returned non-resume response for run %s — "
        "check sender/status (demo-only, run stays at awaiting_reply)",
        run_id,
    )
else:
    logger.info("simulate-reply: synthetic reply submitted for run %s (demo-only)", run_id)
return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
```

### WR-02: `reset_stuck_runs.py --fail-stuck` UPDATE uses f-string SQL for the status/error_reason SET clause

**File:** `scripts/reset_stuck_runs.py:43-48`

**Issue:** The `--fail-stuck` UPDATE uses an f-string to build the full SQL:

```python
rows = c.execute(
    f"UPDATE payroll_runs SET status='error', "
    f"error_reason=COALESCE(error_reason,'stuck-in-flight (manual reset)') "
    f"WHERE status IN ({placeholders}) "
    f"AND updated_at < now() - (%s || ' minutes')::interval "
    f"RETURNING id",
    (*IN_FLIGHT, str(minutes)),
).fetchall()
```

The f-string portions (`status='error'`, `error_reason=COALESCE(...)`, `{placeholders}`) contain only hardcoded values or values computed from a module-level tuple (`IN_FLIGHT`). The `minutes` parameter is correctly parameterized. However, the pattern violates the project's parameterized-SQL discipline stated in `repo.py`'s module docstring ("NEVER f-string SQL") — even for values that happen to be safe. Future maintainers may copy this pattern for user-supplied values.

The `{placeholders}` expansion (`",".join(["%s"] * len(IN_FLIGHT))`) is safe (building a fixed-length placeholder list, not interpolating values), but it is an unusual pattern that obscures the boundary between structural SQL and value parameters.

**Fix:** Refactor to use `ANY(%s::text[])` which allows a single placeholder for the entire IN-clause:

```python
rows = c.execute(
    "UPDATE payroll_runs SET status = %s, "
    "error_reason = COALESCE(error_reason, %s) "
    "WHERE status = ANY(%s::text[]) "
    "AND updated_at < now() - (%s || ' minutes')::interval "
    "RETURNING id",
    ("error", "stuck-in-flight (manual reset)", list(IN_FLIGHT), str(minutes)),
).fetchall()
```

This removes f-strings from the SQL, making the parameterized-SQL discipline unconditional in the scripts.

### WR-03: `RunStatus.NEEDS_CLARIFICATION` is declared but never written by the pipeline — stale status creates unreachable UI state

**File:** `app/models/status.py:19`, `app/db/schema.sql:69`, `app/pipeline/orchestrator.py:62`

**Issue:** `RunStatus.NEEDS_CLARIFICATION = "needs_clarification"` is defined in the enum and in the schema `CHECK` constraint. The orchestrator docstring still mentions it (`"or needs_clarification"`) but `_clarify()` transitions directly to `AWAITING_REPLY` — `NEEDS_CLARIFICATION` is never written to any run.

If a run somehow reaches this status (old data, manual DB write, or a future code path introduced by another engineer following the docstring), it would be stuck in the dashboard: it is absent from `IN_FLIGHT_STATUSES`, absent from the `_BADGE_CLASS` / `_BADGE_LABEL` maps, absent from the retrigger-button list in `run_detail.html`, and absent from the operator controls section. The badge degrades to neutral / title-cased label, and there is no recovery path in the UI.

**Fix:** Either:

(a) Remove `NEEDS_CLARIFICATION` from `RunStatus`, the schema `CHECK`, and the docstring — keeping the enum exactly matching the states the pipeline can actually enter (tightest option).

(b) Add `NEEDS_CLARIFICATION` to the badge maps, `IN_FLIGHT_STATUSES` (or a separate "recoverable" set), and the retrigger-button list so a run in this state is not a UI dead-end.

Option (a) is recommended: it removes drift between the declared state machine and the real one. The schema `CHECK` constraint's CI test (which asserts set-equality with the Python enum) would fail if the Python enum removes the value but the SQL keeps it, surfacing the drift before it ships.

---

## Info

### IN-01: Synthetic reply email row has `run_id = NULL` in `email_messages` — reply audit trail gap

**File:** `app/main.py:724-733`

**Issue:** The simulate-reply route inserts the synthetic inbound email with `run_id=None`:

```python
repo.insert_inbound_email(
    message_id=email.message_id,
    ...
    run_id=None,  # not linked to the run
)
```

This mirrors the real webhook path, which also inserts the initial inbound email with `run_id=None` (the run hasn't been created yet at that point). For a clarification reply, there IS an existing run — `run_id` is known — but it is not linked back to the email row. The reply email therefore has `email_messages.run_id = NULL`, which means:

- The run-detail page's "Sent Emails" section (which filters on `direction = 'outbound'`) never shows inbound reply rows, so this doesn't affect the existing UI.
- But an audit query joining `email_messages` on `run_id` to retrieve all emails for a run will miss the clarification reply. The confirmed real-provider webhook path (Phase 6) will face the same gap.

**Fix:** Pass `run_id=run_id` when inserting the clarification reply email in simulate-reply (and plan to do the same in the real Phase 6 webhook path for replies):

```python
repo.insert_inbound_email(
    message_id=email.message_id,
    ...
    run_id=run_id,  # link reply to the run for full audit trail
)
```

Note: The schema allows `email_messages.run_id` to be NULL (it is nullable), so this is a data quality improvement, not a correctness bug in the current code.

### IN-02: `awaiting_reply` status excluded from `IN_FLIGHT_STATUSES` — no auto-badge refresh after simulate-reply

**File:** `app/main.py:67`, `app/templates/run_detail.html:12`

**Issue:** `IN_FLIGHT_STATUSES = frozenset({"received", "extracting", "computed"})`. When a run is at `awaiting_reply`, the `{% if run.status in in_flight_statuses %}` block in `run_detail.html` is false, so the vanilla-JS poll does not run. After the operator submits the simulate-reply form:

1. The `POST /runs/{run_id}/simulate-reply` returns a `303` redirect.
2. The browser follows the redirect and loads `GET /runs/{run_id}`.
3. The run is still at `awaiting_reply` (the BackgroundTask hasn't claimed it yet).
4. The poll is not active (awaiting_reply is not in-flight).
5. The status badge stays at "Awaiting Reply" until the operator manually refreshes.

This means the operator has no visual feedback that the simulate-reply worked until they manually reload the page. In the TestClient path (synchronous BackgroundTask), the status advances before the redirect is followed, so this is invisible in tests.

**Fix (two options):**

(a) Add `"awaiting_reply"` to `IN_FLIGHT_STATUSES`. This causes the detail page for any `awaiting_reply` run to poll every 2s, which is desirable in the demo context (pipeline advances after a real inbound reply).

(b) Add a one-shot poll delay in the simulate-reply form submission via JS (`setTimeout` on page load if the previous URL was a simulate-reply POST) — more targeted but more complex.

Option (a) is the simpler and more correct fix: `awaiting_reply` is a transitional state for the demo (the operator submits a reply, the pipeline resumes), and polling there exactly mirrors the in-flight poll behavior on the extraction and computation phases.

---

_Reviewed: 2026-06-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
