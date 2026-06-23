---
phase: 05-dashboard-delivery
reviewed: 2026-06-23T10:30:00Z
depth: deep
files_reviewed: 12
files_reviewed_list:
  - app/main.py
  - app/templates/run_detail.html
  - app/templates/runs_list.html
  - app/templates/base.html
  - app/db/repo.py
  - app/pipeline/orchestrator.py
  - app/pipeline/pdf.py
  - app/pipeline/compose_email.py
  - app/pipeline/reconcile_names.py
  - app/email/gateway.py
  - app/static/style.css
  - scripts/reset_stuck_runs.py
findings:
  critical: 0
  warning: 0
  info: 1
  total: 1
status: clean
---

# Phase 05: Code Review Report — Round 5

**Reviewed:** 2026-06-23T10:30:00Z
**Depth:** deep
**Files Reviewed:** 12
**Status:** clean (one info-level nit)

## Summary

This is the fifth adversarial review, focused on the commit `f668809` "reload on ANY status change" pattern in `run_detail.html`, plus a full fresh pass over all twelve files.

**Primary focus — status poll redesign (f668809):** The new logic is correct and loop-safe. All four required verification points from the prompt check out:

1. **Loop safety confirmed.** After a reload, `INITIAL_STATUS` re-seeds to the new status. If the new status is terminal (`awaiting_approval`, `error`, `reconciled`, `rejected`, `sent`) the `{% if run.status in in_flight_statuses %}` guard prevents the script from rendering entirely — no further polling, no reload. If the new status is another in-flight state (e.g. `awaiting_reply → extracting` on resume), the script renders with `INITIAL_STATUS=extracting` and reloads again only on the *next* change. The maximum automatic reload chain (no operator action) is five: `received → extracting → awaiting_reply → extracting (resume) → computed → awaiting_approval`. Each transition is a single reload seeded with the new status. There is no unbounded loop.

2. **Rapid multi-step transition confirmed safe.** If the status advances twice between two 2-second polls (e.g. `awaiting_reply → extracting → awaiting_approval`), the poll sees the latest state, fires one reload, and lands on the correct final page. No missed-reload stranding, no double-reload.

3. **Textarea not reloaded while parked at awaiting_reply confirmed.** While parked at `awaiting_reply` with no reply yet, `data.status === INITIAL_STATUS` — the `!==` branch is false, `!POLL_WHILE.has('awaiting_reply')` is false — so the poll loops harmlessly, the badge stays current, and the textarea is never disturbed.

4. **runs_list.html not changed to reload confirmed.** `window.location.reload` is absent from `runs_list.html`; it still does badge-only in-place swaps.

**Regression checks confirmed:**
- REVIEW-4 WR-01: `repo.load_run(run_id)` is on line 359, inside the `try` block at lines 354–365 in `app/main.py`. A transient DB failure during load routes to `record_run_error` (ERROR), not a silent 500.
- REVIEW-3: `re.sub(r"[^\w.\-]", "_", emp_name, flags=re.ASCII)` is present at `app/main.py:648`. The `re.ASCII` flag is confirmed, restricting `\w` to `[A-Za-z0-9_]` and preventing `UnicodeEncodeError` on non-latin-1 names.
- simulate-reply guard chain intact: status check at line 696, `clar_mid` guard at line 703–705, source-inbound guard at line 712–715, all precede `_route_reply`.
- CAS idempotency on approve/reject/retrigger/resume/deliver: all confirmed using `claim_status` with atomic `WHERE id=? AND status=? RETURNING id`.

**Fresh pass findings:** The codebase remains in the same sound state as prior rounds. SQL parameterization is correct throughout (`%s` / named `%(key)s` placeholders, no f-string SQL). The `INITIAL_STATUS` injection via `|tojson` is XSS-safe (Jinja2's `tojson` HTML-escapes `<`, `>`, `&` by default; status values are a fixed DB-checked enum). Money decisions are deterministic code only; the LLM is confined to extraction and the advisory suggestion copy. PII boundary (type-only error reasons) is maintained in every error path. The `_conn_ctx` / `_nulltx` transaction discipline is consistent. PDF generation is pure and in-memory; no disk writes.

One info-level inconsistency is noted below.

---

## Structural Findings (fallow)

None provided.

---

## Narrative Findings (AI reviewer)

### IN-01: run_detail.html — timer not cleared when MAX_ATTEMPTS is reached

**File:** `app/templates/run_detail.html:32`

**Issue:** When the poll hits the 30-attempt cap, the `poll()` function returns early (`return;`) without calling `clearInterval(timer)`. The interval object continues firing every 2 seconds indefinitely; each invocation immediately returns on the `attempts >= MAX_ATTEMPTS` check. The wasted overhead is negligible (one integer comparison per tick), but the behavior is inconsistent with `runs_list.html`, which correctly calls `clearInterval(timer)` before returning at cap (`runs_list.html:16`).

**Fix:** Add `clearInterval(timer);` before the early return, matching `runs_list.html`:

```javascript
function poll() {
  if (attempts >= MAX_ATTEMPTS) { clearInterval(timer); return; }
  attempts++;
  // ... rest of poll
```

---

_Reviewed: 2026-06-23T10:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
