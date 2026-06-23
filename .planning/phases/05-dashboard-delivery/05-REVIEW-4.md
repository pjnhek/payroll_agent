---
phase: 05-dashboard-delivery
reviewed: 2026-06-23T00:00:00Z
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
  info: 0
  total: 1
resolved:
  warning: 1   # WR-01 load_run moved inside the D-13b boundary (commit pending) + regression test
status: resolved
resolution_note: >
  Round 4 verified the R3 re.ASCII Content-Disposition fix is correct and final, and a fresh
  deep pass found ONE new Warning: in the approve route, repo.load_run() sat between the CAS
  claim and the D-13b try/except, so a transient DB failure during load left the run stuck at
  APPROVED with a raw 500 and no error_reason (violates INGEST-05 'nothing silently hangs').
  Fixed by moving load_run inside the try/except so a load failure routes to ERROR + error_reason
  like any delivery failure (APPROVED is non-terminal → retriggerable). Regression test
  (test_hitl.py::test_approve_load_run_failure_routes_to_error_not_500) asserts 303 + ERROR.
  Everything else reviewed clean (SQL params, autoescape, JS XSS-safe, PDF reconciliation,
  CAS idempotency, simulate-reply guard chain, PII error boundary). Full suite 408 passed / 0 failed.

# Phase 05: Code Review Report (Round 4 — Convergence Check)

**Reviewed:** 2026-06-23
**Depth:** deep
**Files Reviewed:** 17
**Status:** issues_found (1 WARNING; 0 CRITICAL)

## Summary

Deep pass over the complete Phase 5 surface after three prior rounds that resolved all
previously found issues. The surface is in good shape. One new structural inconsistency
was found in the `approve` handler that was not present in prior rounds' scope of
analysis: `repo.load_run()` is called outside the D-13b try/except boundary, so a DB
failure between the successful CAS claim and the load leaves the run stuck at `APPROVED`
with no error recorded and a 500 returned to the browser. The run is recoverable via
retrigger (APPROVED → RECEIVED is a claimed path), so this is a WARNING, not a blocker.

All prior findings (R1–R3) were verified resolved and no regressions detected.

---

## R3 Fix Verification

**Target:** `re.sub(r"[^\w.\-]", "_", emp_name, flags=re.ASCII) or "employee"`
(`app/main.py:643`, `paystub_pdf` handler)

**Verdict: correct and complete.**

1. `import re` is present at module level (line 42) — no NameError risk.
2. `flags=re.ASCII` restricts `\w` to `[A-Za-z0-9_]`, so every character outside
   that set plus `.` and `-` is replaced with `_`. All outputs are ASCII-only and
   therefore always latin-1 encodable — no 500 on non-latin1 names.
3. The `or "employee"` fallback fires on empty-string output (e.g. `emp_name=""`);
   names consisting only of `.` and/or `-` pass through unchanged (e.g. `".-"` →
   `"paystub_-.-.pdf"` — valid Content-Disposition, not a path-traversal concern for
   an in-memory response).
4. CRLF and double-quote characters are replaced with `_` — header injection
   eliminated.
5. The `.pdf` suffix is appended in the f-string, not derived from the name, so it
   cannot be overridden or doubled by a tricky name.

Tested representative inputs: `André`, `Łukasz`, `John\r\nSmith`, `John"Smith`,
`""`, `"\x80\x90"` — all produce latin-1-safe, header-safe output.

---

## Narrative Findings (AI reviewer)

### WR-01: `repo.load_run()` Outside the D-13b Error Boundary in `approve`

**File:** `app/main.py:352-360`
**Severity:** WARNING

The `approve` handler claims the run via `claim_status` (atomic CAS) and then calls
`repo.load_run()` before entering the `try/except` block that is the D-13b error
boundary for `_deliver`:

```python
claimed = repo.claim_status(run_id, RunStatus.AWAITING_APPROVAL, RunStatus.APPROVED)
if claimed:
    run = repo.load_run(run_id)      # ← OUTSIDE try/except
    try:
        _deliver(run_id, run)
    except Exception as exc:
        repo.record_run_error(run_id, type(exc).__name__)
```

If `load_run` raises (e.g. a transient DB connection failure immediately after the
successful CAS), the exception propagates unhandled: FastAPI returns HTTP 500 to the
browser, the run stays at `APPROVED`, and no `error_reason` is recorded. The operator
sees a raw 500 with no context, and the run appears stuck at `APPROVED` in the queue.

**Impact:** The run is not lost — it remains at `APPROVED` and the retrigger handler
accepts `APPROVED → RECEIVED` as a valid claim, so the operator can recover manually.
However, the operator gets no explanation and the run does not self-describe as
needing intervention.

**Fix:** Move `load_run` inside the try/except so a DB failure during load is treated
identically to a `_deliver` failure — routes the run to ERROR with an error_reason:

```python
claimed = repo.claim_status(run_id, RunStatus.AWAITING_APPROVAL, RunStatus.APPROVED)
if claimed:
    try:
        run = repo.load_run(run_id)          # ← moved inside
        _deliver(run_id, run)
    except Exception as exc:
        logger.warning("delivery of run %s failed: %s", run_id, type(exc).__name__)
        repo.record_run_error(run_id, type(exc).__name__)
```

---

## Deferred Findings (DO NOT re-raise)

The following were explicitly deferred in prior rounds and remain out of scope for
this review. They are listed here for completeness and to confirm they have not
regressed:

- **260623-06** — `NEEDS_CLARIFICATION` dead status
- **260623-07** — `load_all_runs` uses `SELECT pr.*`
- **260623-04** — eval-chart aesthetics
- **260623-05** — fixture label
- **260623-03** — full YTD
- **260623-02** — frontend progressive enhancement
- **260623-01** — five R1-review warnings

All remain at their prior deferred state. No regressions observed.

---

_Reviewed: 2026-06-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
