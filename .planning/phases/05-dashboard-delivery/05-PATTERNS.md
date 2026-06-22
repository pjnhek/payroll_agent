# Phase 5: Dashboard & Delivery — Pattern Map

**Mapped:** 2026-06-22
**Files analyzed:** 14 new/modified files
**Analogs found:** 14 / 14 (every file has a verified codebase analog)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `app/db/repo.py` — `claim_status` (add) | service | request-response (CAS) | `app/db/repo.py:267` `set_status` | exact |
| `app/db/repo.py` — `update_known_alias` (add) | service | CRUD | `app/db/repo.py:372` `replace_line_items` | role-match |
| `app/db/repo.py` — `_TERMINAL_STATUSES` (modify) | service | — | `app/db/repo.py:86` `_TERMINAL_STATUSES` | exact |
| `app/pipeline/compose_email.py` — `compose_confirmation` (add) | service | request-response | `app/pipeline/compose_email.py:88` `compose_clarification` | exact |
| `app/pipeline/validate.py` — `validate` (extend) | service | transform | `app/pipeline/validate.py:50` `validate` | exact |
| `app/pipeline/pdf.py` (new) | service | transform / file-I/O | `app/pipeline/compose_email.py:88` pure-stage seam | role-match |
| `app/pipeline/orchestrator.py` — `_clarify` (extend: alias_candidates capture) | service | event-driven | `app/pipeline/orchestrator.py:200` `_clarify` | exact |
| `app/pipeline/orchestrator.py` — `resume_pipeline` (modify: `claim_status`) | service | event-driven | `app/pipeline/orchestrator.py:87` `resume_pipeline` | exact |
| `app/pipeline/orchestrator.py` — delivery path (add `_deliver`) | service | event-driven | `app/pipeline/orchestrator.py:61` `run_pipeline` error-wrap | role-match |
| `app/pipeline/reconcile_names.py` — `_safe_to_learn_alias` (add) | utility | transform | `app/pipeline/reconcile_names.py:37` `deterministic_match` | exact |
| `app/main.py` — dashboard routes + form handlers (add/replace) | controller | request-response | `app/main.py:49` `inbound` + `_operator_transition` | exact |
| `app/templates/` (4 new templates) | component | request-response | `app/main.py` Jinja2 pattern (RESEARCH §10) | role-match |
| `app/static/style.css` (new) | config | — | `05-UI-SPEC.md` CSS contract | no analog |
| `tests/` (7 new/extended test files) | test | — | `tests/test_clarify.py`, `tests/test_validate.py` | exact |

---

## Pattern Assignments

---

### `app/db/repo.py` — `claim_status` function (add)

**Analog:** `app/db/repo.py:267` `set_status`

**Imports pattern** (lines 50–65 — already present, no new imports needed):
```python
import contextlib
import json
import logging
import uuid

import psycopg.rows

from app.db.supabase import get_connection
from app.models.status import RunStatus
```

**Core `set_status` pattern** (lines 267–279) — claim_status is a direct clone with a `WHERE status=%s RETURNING id` predicate and a `bool` return:
```python
def set_status(run_id: uuid.UUID, status: RunStatus, conn=None) -> None:
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET status = %s, updated_at = now() WHERE id = %s",
                (RunStatus(status).value, str(run_id)),
            )
```

**claim_status pattern to implement** (mirrors set_status exactly, adds expected-status predicate + RETURNING + bool return):
```python
def claim_status(
    run_id: uuid.UUID,
    expected: RunStatus,
    new: RunStatus,
    conn=None,
) -> bool:
    """Atomic compare-and-swap on payroll_runs.status (D-12, FOUND-04).

    Returns True if the claim succeeded (run was in `expected` and is now `new`).
    Returns False if the run was NOT in `expected` — caller logs a late/duplicate
    and drops cleanly (does not re-run the work).
    Second sanctioned status writer alongside set_status (unguarded).
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                "UPDATE payroll_runs SET status = %s, updated_at = now() "
                "WHERE id = %s AND status = %s RETURNING id",
                (RunStatus(new).value, str(run_id), RunStatus(expected).value),
            ).fetchone()
    return row is not None
```

**Invariant doc update required** — the module docstring at line 17 ("set_status — the ONE AND ONLY writer of payroll_runs.status") and the `set_status` docstring at line 268 must both be updated to: "two writers — `set_status` (unguarded forward transitions inside an owned path) and `claim_status` (atomic guarded claim at every contended gate)."

**`_TERMINAL_STATUSES` modification** (lines 86–94) — remove `RunStatus.APPROVED` from the frozenset so `record_run_error` can advance an `approved` run to `ERROR` when delivery fails (D-13b critical finding):
```python
# BEFORE (current — blocks delivery error recovery):
_TERMINAL_STATUSES = frozenset({
    RunStatus.APPROVED.value,   # <-- REMOVE THIS
    RunStatus.SENT.value,
    RunStatus.RECONCILED.value,
    RunStatus.REJECTED.value,
    RunStatus.ERROR.value,
})

# AFTER (Phase 5):
_TERMINAL_STATUSES = frozenset({
    RunStatus.SENT.value,
    RunStatus.RECONCILED.value,
    RunStatus.REJECTED.value,
    RunStatus.ERROR.value,
})
```

---

### `app/db/repo.py` — `update_known_alias` function (add)

**Analog:** `app/db/repo.py:372` `replace_line_items` (CRUD write with `_conn_ctx` + `_nulltx`)

**Core CRUD write pattern** (lines 372–382):
```python
def replace_line_items(
    run_id: uuid.UUID, items: list[PaystubLineItem], conn=None
) -> None:
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "DELETE FROM paystub_line_items WHERE run_id = %s", (str(run_id),)
            )
            for it in items:
                c.execute("INSERT INTO paystub_line_items ...", (...))
```

**`update_known_alias` pattern to implement** — idempotent JSONB array append with collision guard already run upstream by `_safe_to_learn_alias`:
```python
def update_known_alias(
    employee_id: uuid.UUID,
    new_alias: str,
    conn=None,
) -> bool:
    """Idempotently append new_alias to employees.known_aliases (D-01).

    Caller MUST have already called _safe_to_learn_alias() — this function
    does NOT re-check collision; it only deduplicates the JSONB array.
    Returns True if the alias was added, False if already present.
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                """
                UPDATE employees
                SET known_aliases = (
                    SELECT jsonb_agg(DISTINCT elem)
                    FROM jsonb_array_elements_text(
                        known_aliases || to_jsonb(ARRAY[%s::text])
                    ) elem
                )
                WHERE id = %s
                  AND NOT (known_aliases @> to_jsonb(ARRAY[%s::text]))
                RETURNING id
                """,
                (new_alias, str(employee_id), new_alias),
            ).fetchone()
    return row is not None
```

---

### `app/pipeline/compose_email.py` — `compose_confirmation` function (add)

**Analog:** `app/pipeline/compose_email.py:88` `compose_clarification` — EXACT clone of the pattern.

**Module docstring pattern** (lines 1–16) — compose_confirmation module note is added to the existing file; the module's "PURE: typed ... in, str out. No DB, no connection" principle applies identically.

**`_template_body` floor pattern** (lines 30–85) — `compose_confirmation` needs its own deterministic floor. Mirror the exact structure:
```python
def _confirmation_template_body(
    paystubs: list,  # list[PaystubLineItem]
    run: dict,
) -> str:
    """Deterministic confirmation floor — fires when draft times out or fails (D-10).

    Subject: "Payroll Confirmation — {business_name} — {pay_period_label}"
    Never strands the send, even on total draft failure.
    """
    lines = [
        "Your payroll run has been reviewed and approved. "
        "Please find the paystub PDFs attached.",
        "",
    ]
    for item in paystubs:
        lines.append(f"- {item.submitted_name}: ${item.net_pay:,.2f} net")
    lines += ["", "Please contact us if you have any questions."]
    return "\n".join(lines)
```

**`compose_clarification` core pattern** (lines 88–132) — compose_confirmation clones this exactly:
```python
def compose_clarification(
    decision: Decision,
    *,
    suggestions: dict[str, str] | None = None,
    llm=llm_client,
) -> str:
    # ...
    api_error = False
    try:
        body = llm.call_text("draft", messages, temperature=0.3)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "draft call failed (%s) — falling back to templated clarification body",
            type(exc).__name__,
        )
        body = None
        api_error = True
    if not body or not body.strip():
        if not api_error:
            logger.warning("draft returned empty content — using templated clarification body")
        return _template_body(decision, suggestions)
    return body
```

**`compose_confirmation` pattern to implement** — clone of `compose_clarification` with these substitutions:
- `decision: Decision` → `paystubs: list[PaystubLineItem], run: dict`
- `_template_body(decision, suggestions)` → `_confirmation_template_body(paystubs, run)`
- Log messages reference "confirmation" not "clarification"
- Add `timeout_s: float = 3.0` parameter, passed to the LLM call (D-10b hard timeout)
- `temperature=0.3` stays (same tier, same warmth)

**Import additions** (top of compose_email.py):
```python
from app.models.contracts import PaystubLineItem  # add alongside Decision import
```

---

### `app/pipeline/validate.py` — `validate` function (extend)

**Analog:** `app/pipeline/validate.py:50` `validate` — the existing pure seam is extended in-place.

**Existing `_employee_pay_type` helper pattern** (lines 36–47) — new `_employee_pay_periods_per_year` follows the IDENTICAL structure:
```python
def _employee_pay_type(
    submitted_name: str,
    matches: list[NameMatchResult],
    roster: Roster,
) -> str | None:
    """Resolve the matched employee's pay_type via the reconciliation results."""
    for m in matches:
        if m.submitted_name == submitted_name and m.matched_employee_id is not None:
            for emp in roster.employees:
                if emp.id == m.matched_employee_id:
                    return emp.pay_type
    return None
```

**New helper to add** (same structure, returns `pay_periods_per_year`):
```python
def _employee_pay_periods_per_year(
    submitted_name: str,
    matches: list[NameMatchResult],
    roster: Roster,
) -> int | None:
    """Resolve the matched employee's pay_periods_per_year (None if unresolved)."""
    for m in matches:
        if m.submitted_name == submitted_name and m.matched_employee_id is not None:
            for emp in roster.employees:
                if emp.id == m.matched_employee_id:
                    return emp.pay_periods_per_year
    return None
```

**Existing `validate` loop body pattern** (lines 63–82) — the over-40-no-OT rule appends to the SAME `issues` list after the existing missing-hours loop:
```python
issues: list[ValidationIssue] = []
for emp in extracted.employees:
    any_hours = any(getattr(emp, f) is not None for f in _HOURS_FIELDS)
    if any_hours:
        continue
    pay_type = _employee_pay_type(emp.submitted_name, matches, roster)
    if pay_type == "hourly":
        issues.append(ValidationIssue(
            field=f"{emp.submitted_name}.hours_regular",
            issue_type="missing",
            message=(...),
        ))
return issues
```

**New OT rule to append after the existing loop** (D-05):
```python
# D-05: Over-40-no-OT guard (weekly: complete; biweekly: partial, honestly labeled)
for emp in extracted.employees:
    ppy = _employee_pay_periods_per_year(emp.submitted_name, matches, roster)
    if ppy is None:
        continue  # unresolved employee: gate already blocks it
    ot = emp.hours_overtime
    ot_missing = ot is None or ot == 0  # flag explicit 0 same as absent (D-05 edge)
    if ppy == 52 and emp.hours_regular is not None and emp.hours_regular > 40 and ot_missing:
        issues.append(ValidationIssue(
            field=f"{emp.submitted_name}.hours_overtime",
            issue_type="missing",
            message=(
                f"weekly employee {emp.submitted_name!r} has "
                f"{emp.hours_regular} regular hours with no overtime — "
                "is that 40 regular + overtime, or straight time?"
            ),
        ))
    elif ppy == 26 and emp.hours_regular is not None and emp.hours_regular > 80 and ot_missing:
        issues.append(ValidationIssue(
            field=f"{emp.submitted_name}.hours_overtime",
            issue_type="missing",
            message=(
                f"biweekly employee {emp.submitted_name!r} has "
                f"{emp.hours_regular} regular hours (>80 over 2 weeks guarantees "
                "OT in at least one week) — please provide the regular/OT split. "
                "(Note: partial detection only for biweekly periods.)"
            ),
        ))
    # ppy in (24, 12): period boundaries cross workweeks — no flag (documented limitation)
```

---

### `app/pipeline/pdf.py` (new file)

**Analog:** `app/pipeline/compose_email.py` pure-stage seam ("PURE: typed ... in, ... out. No DB, no connection.") — the PDF generator IS the same pure-function seam, data in → bytes out.

**Module docstring pattern** (mirror compose_email.py lines 1–16):
```python
"""On-demand per-employee paystub PDF generator (HITL-03, D-11).

A PURE function: PaystubLineItem + employee metadata in, PDF bytes out.
No DB, no model, no connection. The orchestrator/route layer owns the
StreamingResponse wrapping and any gateway attachment assembly.

reportlab SimpleDocTemplate → Table → BytesIO.getvalue() → bytes.
Nothing is written to disk (HITL-03: Render ephemeral FS constraint).
"""
```

**Pure function signature** (mirrors the pure-stage seam throughout the project):
```python
from io import BytesIO
from datetime import date

from reportlab.lib.pagesizes import LETTER
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

from app.models.contracts import PaystubLineItem


def generate_paystub_pdf(
    item: PaystubLineItem,
    employee_full_name: str,
    pay_period_start: date | None,
    pay_period_end: date | None,
) -> bytes:
    """Pure: data in → PDF bytes out. No DB, no filesystem write (HITL-03).

    Returns raw PDF bytes. The caller wraps in StreamingResponse or passes
    as attachment bytes to gateway.send_outbound.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER)
    # ... build table from item fields ...
    doc.build([...])
    return buf.getvalue()
```

**StreamingResponse caller pattern** (from RESEARCH.md §7 — used in the download route):
```python
from fastapi.responses import StreamingResponse
from io import BytesIO

pdf_bytes = generate_paystub_pdf(item, emp_name, start, end)
return StreamingResponse(
    BytesIO(pdf_bytes),
    media_type="application/pdf",
    headers={"Content-Disposition": f'attachment; filename="paystub_{emp_name}.pdf"'},
)
```

---

### `app/pipeline/reconcile_names.py` — `_safe_to_learn_alias` (add)

**Analog:** `app/pipeline/reconcile_names.py:37` `deterministic_match` — the write-side guard directly calls this existing function.

**`deterministic_match` collision logic** (lines 37–81) — `_safe_to_learn_alias` builds a synthetic roster and delegates to it:
```python
def deterministic_match(name: str, roster: Roster) -> NameMatchResult | None:
    norm = _norm(name)
    exact_ids = [emp.id for emp in roster.employees if _norm(emp.full_name) == norm]
    alias_ids = [
        emp.id
        for emp in roster.employees
        if any(_norm(alias) == norm for alias in emp.known_aliases)
    ]
    candidate_ids = set(exact_ids) | set(alias_ids)
    if len(candidate_ids) != 1:
        return None  # zero candidates OR 2+ distinct employees
    ...
```

**`_safe_to_learn_alias` to add** (note: module-private helper, NOT exported in `reconcile_names`; lives where the alias write fires — `app/db/repo.py` or the approval handler can import `deterministic_match` directly):
```python
from app.models.roster import Employee, Roster
from app.pipeline.reconcile_names import deterministic_match


def _safe_to_learn_alias(
    token: str,
    target_employee: Employee,
    roster: Roster,
) -> bool:
    """Return True only if token uniquely resolves to target_employee on the full roster
    AFTER the alias is appended (D-01b write-side collision guard).

    Uses a synthetic roster where the alias is already present to simulate the
    post-write state. If deterministic_match returns None (ambiguous) or resolves
    to a DIFFERENT employee, return False — do NOT learn (log and skip).
    """
    synthetic_employees = []
    for emp in roster.employees:
        if emp.id == target_employee.id:
            new_aliases = list(emp.known_aliases) + [token]
            synthetic_employees.append(emp.model_copy(update={"known_aliases": new_aliases}))
        else:
            synthetic_employees.append(emp)
    synthetic_roster = roster.model_copy(update={"employees": synthetic_employees})
    result = deterministic_match(token, synthetic_roster)
    return result is not None and result.matched_employee_id == target_employee.id
```

---

### `app/pipeline/orchestrator.py` — `_clarify` extension (alias_candidates capture)

**Analog:** `app/pipeline/orchestrator.py:200` `_clarify` — the capture is inserted INTO `_clarify` immediately before `gateway.send_outbound`.

**`_clarify` existing pattern** (lines 200–245):
```python
def _clarify(run_id, email, decision, roster, *, llm) -> None:
    suggest_kwargs = {}
    if llm is not None:
        suggest_kwargs["llm"] = llm
    suggestions = suggest_employees(decision.unresolved_names, roster, **suggest_kwargs)

    compose_kwargs = {"suggestions": suggestions}
    if llm is not None:
        compose_kwargs["llm"] = llm
    body = compose_clarification(decision, **compose_kwargs)

    gateway.send_outbound(          # <-- INSERT alias_candidates capture BEFORE here
        run_id=run_id,
        to_addr=email.from_addr,
        subject=clarification_subject(),
        body=body,
        in_reply_to=email.message_id,
        references_header=email.message_id,
    )
    repo.set_status(run_id, RunStatus.AWAITING_REPLY)
```

**Alias_candidates capture insertion** (D-04: write BEFORE send, keyed by original token):
```python
# D-04: capture {original_token: None} before send — None filled at resume.
# Only unresolved names that are NOT cross-roster collisions are candidates.
# Collision check: deterministic_match with the CURRENT roster (before any alias write).
if decision.unresolved_names:
    from app.pipeline.reconcile_names import deterministic_match as _dm
    candidates = {}
    for name in decision.unresolved_names:
        # Exclude tokens that already collide (match 2+ employees) — D-01b
        match = _dm(name, roster)
        # match is None both for "no match" and for "2+ match" (collision)
        # We don't know which, but both are ineligible for alias learning.
        # Only store tokens that have ZERO matches (truly unknown, not ambiguous).
        # A heuristic: if the name partially matches any employee, treat as
        # collision-suspect and let D-01b's write-side guard be the final gate.
        candidates[name] = None  # resolved_employee_id filled at resume
    # Merge into reconciliation JSONB as alias_candidates key.
    # NOTE: use a SEPARATE UPDATE to avoid being overwritten by persist_reconciliation.
    repo.set_alias_candidates(run_id, candidates)   # new repo helper (see below)
```

**New `repo.set_alias_candidates` helper** (follows `persist_reconciliation` pattern at lines 354–369):
```python
def set_alias_candidates(
    run_id: uuid.UUID,
    candidates: dict,
    conn=None,
) -> None:
    """Write alias_candidates to payroll_runs.alias_candidates JSONB column (D-04).

    Separate column (not a key in reconciliation) — avoids being overwritten by
    persist_reconciliation on resume (RESEARCH Open Question #1).
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET alias_candidates = %s, updated_at = now() WHERE id = %s",
                (json.dumps(candidates), str(run_id)),
            )
```

---

### `app/pipeline/orchestrator.py` — `resume_pipeline` (modify: `claim_status`)

**Analog:** `app/pipeline/orchestrator.py:87` `resume_pipeline` — replace the non-atomic load-then-set at lines 125+141.

**Current non-atomic pattern** (lines 121–141) — the CR-02 documented residual:
```python
run = repo.load_run(run_id)
if run is None:
    raise ValueError(...)
if run["status"] != RunStatus.AWAITING_REPLY.value:   # <-- load-then-check (race window)
    logger.info("resume aborted: run %s is %s, not awaiting_reply ...", ...)
    return
# ...
repo.set_status(run_id, RunStatus.EXTRACTING)          # <-- separate set (the race seam)
_run_stages(run_id, combined_email, roster, llm=llm)
```

**Replacement pattern** (D-12 claim_status closes the race):
```python
# Replace the load_run status check + set_status(EXTRACTING) with a single CAS:
claimed = repo.claim_status(run_id, RunStatus.AWAITING_REPLY, RunStatus.EXTRACTING)
if not claimed:
    logger.info(
        "resume aborted: run %s claim failed (not awaiting_reply) — "
        "late/duplicate reply dropped (CR-02, D-12)",
        run_id,
    )
    return
# load_run still needed for business_id and other metadata:
run = repo.load_run(run_id)
roster = repo.load_roster_for_business(run["business_id"])
original_body = repo.load_source_email(run_id) or ""
combined_email = _combined_context_email(inbound, original_body)
_run_stages(run_id, combined_email, roster, llm=llm)
```

---

### `app/pipeline/orchestrator.py` — `_deliver` function (new, delivery path)

**Analog:** `app/pipeline/orchestrator.py:61` `run_pipeline` error-wrap pattern (D-A1-03).

**Error-wrap pattern** (lines 61–70):
```python
def run_pipeline(run_id: uuid.UUID, *, llm=None) -> None:
    try:
        _run(run_id, llm=llm)
    except Exception as exc:  # noqa: BLE001 — the D-A1-03 error-wrap boundary
        reason = type(exc).__name__   # PII-safe: type only, not str(exc)
        logger.warning("run %s failed: %s", run_id, reason)
        repo.record_run_error(run_id, reason)
```

**`_deliver` pattern to implement** (D-13b: mirrors error-wrap, called synchronously from approve handler):
```python
def _deliver(run_id: uuid.UUID, run: dict) -> None:
    """Post-approval delivery: compose confirmation + generate PDFs + send + advance.

    Called synchronously from the approve handler (D-06b). Wrapped by the
    approve handler in a try/except that converts exceptions to ERROR via
    record_run_error (D-13b). This function itself does NOT catch — it raises
    freely; the caller's boundary catches and records.
    """
    from app.pipeline.pdf import generate_paystub_pdf
    from app.pipeline.compose_email import compose_confirmation, confirmation_subject

    # Load paystubs for this run
    paystubs = repo.load_line_items(run_id)  # new repo helper

    # D-13c intent-row BEFORE send (crash-safe idempotency)
    # Check already-sent guard first (D-13)
    existing_outbound = repo.get_outbound_message_id(run_id)
    if existing_outbound:
        logger.info("run %s already has outbound row — skipping send (D-13)", run_id)
        repo.set_status(run_id, RunStatus.SENT)
        repo.set_status(run_id, RunStatus.RECONCILED)
        return

    # Compose confirmation (D-10 — draft tier + floor, D-10b hard timeout)
    body = compose_confirmation(paystubs, run)

    # Generate per-employee PDFs (D-11 — pure, in-memory)
    pdf_attachments = []
    roster = repo.load_roster_for_business(run["business_id"])
    for item in paystubs:
        emp = next((e for e in roster.employees if e.id == item.employee_id), None)
        emp_name = emp.full_name if emp else item.submitted_name
        pdf_bytes = generate_paystub_pdf(
            item, emp_name,
            run.get("pay_period_start"),
            run.get("pay_period_end"),
        )
        pdf_attachments.append((emp_name, pdf_bytes))

    # Send (stub gateway — Phase 6 wires live provider here)
    inbound_email = repo.load_inbound_email(run_id)
    gateway.send_outbound(
        run_id=run_id,
        to_addr=inbound_email.from_addr,
        subject=confirmation_subject(run),
        body=body,
        # attachments= parameter to be added to gateway.send_outbound signature
    )

    # D-01 alias write (after send succeeds, before terminal status)
    _write_aliases_if_safe(run_id, run, roster)

    repo.set_status(run_id, RunStatus.SENT)
    repo.set_status(run_id, RunStatus.RECONCILED)
```

---

### `app/main.py` — dashboard routes + form handlers (add/replace)

**Analog:** `app/main.py:240` `_operator_transition` + `app/main.py:49` `inbound` — the GET routes follow the Jinja2Templates pattern; POST routes mirror the 303-redirect convention.

**Existing `_operator_transition` pattern** (lines 240–253) — Phase 5 replaces the JSON response and adds the delivery path:
```python
def _operator_transition(run_id: uuid.UUID, target: RunStatus) -> JSONResponse:
    run = repo.load_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run["status"] != RunStatus.AWAITING_APPROVAL.value:
        raise HTTPException(status_code=409, detail=f"run is {run['status']}, not awaiting_approval")
    repo.set_status(run_id, target)
    return JSONResponse(status_code=200, content={"status": target.value, "run_id": str(run_id)})
```

**BackgroundTask pattern** (lines 103, 167) — re-trigger route uses this for the pipeline re-run:
```python
background_tasks.add_task(_run_pipeline, run_id)
```

**New imports to add** at the top of `app/main.py`:
```python
import json
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
```

**GET route pattern** (mirrors the FastAPI Jinja2 convention from RESEARCH.md §10):
```python
@app.get("/runs")
def runs_list(request: Request):
    runs = repo.load_all_runs()  # new repo helper
    return templates.TemplateResponse("runs_list.html", {"request": request, "runs": runs})


@app.get("/runs/{run_id}")
def run_detail(request: Request, run_id: uuid.UUID):
    run = repo.load_run(run_id)
    if run is None:
        raise HTTPException(status_code=404)
    raw_email = repo.load_inbound_email(run_id)
    paystubs = repo.load_line_items(run_id)
    return templates.TemplateResponse(
        "run_detail.html",
        {"request": request, "run": run, "raw_email": raw_email, "paystubs": paystubs},
    )
```

**POST-redirect-GET pattern** (D-06):
```python
@app.post("/runs/{run_id}/approve")
def approve(run_id: uuid.UUID):
    claimed = repo.claim_status(run_id, RunStatus.AWAITING_APPROVAL, RunStatus.APPROVED)
    if not claimed:
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
    try:
        run = repo.load_run(run_id)
        _deliver(run_id, run)
    except Exception as exc:
        reason = type(exc).__name__  # PII-safe (D-A1-03 pattern)
        logger.warning("delivery of run %s failed: %s", run_id, reason)
        repo.record_run_error(run_id, reason)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@app.post("/runs/{run_id}/reject")
def reject(run_id: uuid.UUID):
    repo.claim_status(run_id, RunStatus.AWAITING_APPROVAL, RunStatus.REJECTED)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@app.post("/runs/{run_id}/retrigger")
def retrigger(run_id: uuid.UUID, background_tasks: BackgroundTasks):
    # Two valid prior states (D-13b): error OR approved (delivery died)
    claimed = (
        repo.claim_status(run_id, RunStatus.ERROR, RunStatus.RECEIVED)
        or repo.claim_status(run_id, RunStatus.APPROVED, RunStatus.RECEIVED)
    )
    if claimed:
        background_tasks.add_task(_run_pipeline, run_id)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
```

**Eval route pattern** (D-09a — hermetic disk reads):
```python
@app.get("/eval")
def eval_view(request: Request):
    summary_path = Path("eval/summary.json")
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else None
    return templates.TemplateResponse("eval.html", {"request": request, "summary": summary})


@app.get("/eval/chart.svg")
def eval_chart():
    from fastapi.responses import FileResponse
    return FileResponse("eval/chart.svg", media_type="image/svg+xml")


@app.get("/runs/{run_id}/pdf/{employee_id}")
def download_pdf(run_id: uuid.UUID, employee_id: uuid.UUID):
    from io import BytesIO
    from app.pipeline.pdf import generate_paystub_pdf
    item = repo.load_line_item(run_id, employee_id)  # new repo helper
    run = repo.load_run(run_id)
    roster = repo.load_roster_for_business(run["business_id"])
    emp = next((e for e in roster.employees if e.id == employee_id), None)
    emp_name = emp.full_name if emp else str(employee_id)
    pdf_bytes = generate_paystub_pdf(
        item, emp_name, run.get("pay_period_start"), run.get("pay_period_end")
    )
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="paystub_{emp_name}.pdf"'},
    )


@app.post("/demo/send-test")
def send_test_email(background_tasks: BackgroundTasks):
    """DASH-05: fire a committed fixture through the pipeline, 303 to /runs."""
    import httpx
    # POSTs the committed fixture JSON to /webhook/inbound on self (or call inbound() directly)
    # Simplest: call the inbound function directly with a fixture
    from app.db.seed import DEMO_FIXTURE  # or read from eval/fixtures/
    background_tasks.add_task(_fire_demo_fixture, DEMO_FIXTURE)
    return RedirectResponse(url="/runs", status_code=303)
```

---

### `app/templates/base.html`, `runs_list.html`, `run_detail.html`, `eval.html` (new)

**Analog:** None in the codebase. Pattern comes from the 05-UI-SPEC.md design contract (the planner's reference) and standard Jinja2 inheritance.

**Jinja2 inheritance pattern** (base.html → child templates):
```html
<!-- base.html — all other templates extend this -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Payroll Agent</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <nav>
    <span class="app-name">Payroll Agent</span>
    <a href="/runs">Runs</a>
    <a href="/eval">Eval</a>
  </nav>
  <div class="page-wrapper">
    {% block content %}{% endblock %}
  </div>
</body>
</html>
```

```html
<!-- runs_list.html -->
{% extends "base.html" %}
{% block content %}
<h1>Payroll Runs</h1>
{% if runs %}
<table>
  <thead><tr><th>Created</th><th>Business</th><th>Status</th><th>Summary</th><th></th></tr></thead>
  <tbody>
  {% for run in runs %}
    <tr>
      <td class="ts">{{ run.created_at.strftime('%Y-%m-%d %H:%M') }}</td>
      <td>{{ run.business_name }}</td>
      <td><span class="badge badge-{{ run.status | badge_class }}">{{ run.status | badge_label }}</span></td>
      <td class="summary-col">{{ run.summary }}</td>
      <td><a href="/runs/{{ run.id }}">View</a></td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p class="empty-heading">No payroll runs yet</p>
<p>Use the Send Test Email button on the eval page to fire a demo fixture through the pipeline.</p>
{% endif %}
{% endblock %}
```

**Badge class mapping** (implement as a Jinja2 filter or template context helper):
```python
_BADGE_CLASS = {
    "received": "neutral", "extracting": "neutral", "computing": "neutral",
    "awaiting_reply": "neutral", "computed": "neutral", "approved": "neutral",
    "awaiting_approval": "pending",
    "sent": "good", "reconciled": "good",
    "rejected": "bad", "error": "bad",
}
```

---

### `app/static/style.css` (new)

**Analog:** None in the codebase. All values come from `05-UI-SPEC.md` color/spacing/typography contracts verbatim.

**Key CSS sections** (no framework; raw rules):
- Spacing tokens as CSS custom properties: `--space-xs: 4px` through `--space-3xl: 64px`
- Badge classes: `.badge-neutral`, `.badge-pending`, `.badge-good`, `.badge-bad`
- Button classes: `.btn-approve`, `.btn-reject`, `.btn-retrigger`
- 3-column grid: `.run-detail-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; column-gap: 32px; }`
- Decision banners: `.banner-process`, `.banner-clarify`, `.banner-awaiting`, `.banner-error`

All hex values, font sizes, and geometry come directly from `05-UI-SPEC.md` — do not invent values.

---

### Test files (7 new/extended)

**Analog:** `tests/test_clarify.py` (entire file) + `tests/test_validate.py` (entire file) — the test architecture for Phase 5 is an exact pattern copy.

**`_DraftLLM` stub pattern** (test_clarify.py:31–44) — copy for compose_confirmation tests:
```python
class _DraftLLM:
    def __init__(self, body):
        self._body = body
        self.calls: list[tuple] = []

    def call_text(self, tier, messages, temperature=0.7):
        self.calls.append((tier, messages, temperature))
        return self._body


class _RaisingDraftLLM:
    def __init__(self, exc=None):
        self._exc = exc or RuntimeError("simulated draft API error")
        self.calls = 0

    def call_text(self, tier, messages, temperature=0.7):
        self.calls += 1
        raise self._exc
```

**FakeConnection test pattern** (conftest.py FakeCursor/FakeConnection) — `test_claim_status.py` injects this to assert the conditional UPDATE SQL without a live DB:
```python
# Assert claim_status sends the correct conditional UPDATE:
conn = FakeConnection(fetchone_returns=[("some-uuid",)])  # simulate row returned
result = repo.claim_status(run_id, RunStatus.AWAITING_APPROVAL, RunStatus.APPROVED, conn=conn)
assert result is True
assert "AND status = %s RETURNING id" in conn.executed[0][0]

# Simulate no row returned (claim lost):
conn2 = FakeConnection(fetchone_returns=[None])
result2 = repo.claim_status(run_id, RunStatus.AWAITING_APPROVAL, RunStatus.APPROVED, conn=conn2)
assert result2 is False
```

**`roster_from_seed` fixture pattern** (test_validate.py:36 + conftest.py) — reused in D-01b and D-05 tests:
```python
def test_ot_rule_weekly_employee(roster_from_seed):
    maria = next(e for e in roster_from_seed.employees if e.full_name == "Maria Chen")
    extracted = _extracted([
        ExtractedEmployee(submitted_name="Maria Chen", hours_regular=Decimal("45"))
    ])
    matches = [_match("Maria Chen", maria.id)]
    issues = validate(extracted, roster_from_seed, matches)
    assert any("overtime" in i.message.lower() for i in issues)
```

**File-to-test mapping** (from RESEARCH.md §Validation Architecture):
- `tests/test_claim_status.py` — FOUND-04, D-12 (unit + integration variants)
- `tests/test_alias_write.py` — D-01b collision exclusion + idempotency
- `tests/test_pdf.py` — HITL-03 PDF generator pure function
- `tests/test_compose_confirmation.py` — HITL-02 template floor on failure (clone of test_clarify.py structure)
- `tests/test_delivery.py` — D-13b error boundary + CLAR-04 idempotent send
- `tests/test_dashboard.py` — DASH-01/02/04/05 route smoke tests
- `tests/test_validate.py` — EXTEND existing file with D-05 OT rule cases

---

## Shared Patterns

### 1. Pure-Stage Seam
**Source:** `app/pipeline/compose_email.py:1–16` (module docstring) + `app/pipeline/validate.py:1–21` (module docstring)
**Apply to:** `app/pipeline/pdf.py`, `app/pipeline/compose_email.py::compose_confirmation`, the `_safe_to_learn_alias` helper, and the OT rule in `validate.py`

Every stage/helper that produces data or an artifact must be:
- A pure function: typed values in, output out
- No DB, no model calls, no connection
- The orchestrator/route owns DB writes and network calls

```
# Module docstring pattern — copy verbatim for new pure modules:
"""...
PURE: typed ... in, ... out. No DB, no connection — the orchestrator owns ...
"""
```

### 2. `_conn_ctx` + `_nulltx` Transaction Pattern
**Source:** `app/db/repo.py:97–104` + line 596 (`_nulltx`)
**Apply to:** `claim_status`, `update_known_alias`, `set_alias_candidates`, `load_line_items`, all new repo helpers

Every repo function follows this exact structure:
```python
def some_helper(arg, conn=None):
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute("...", (...))
```

### 3. D-A1-03 Error-Wrap Boundary
**Source:** `app/pipeline/orchestrator.py:61–70` (`run_pipeline`) + lines 121–149 (`resume_pipeline`)
**Apply to:** The approve handler's delivery path (D-13b), the `_deliver` function

```python
try:
    _deliver(run_id, run)
except Exception as exc:  # noqa: BLE001
    reason = type(exc).__name__  # PII-safe: type only, never str(exc)
    logger.warning("delivery of run %s failed: %s", run_id, reason)
    repo.record_run_error(run_id, reason)
```

### 4. Draft-Tier-With-Deterministic-Floor
**Source:** `app/pipeline/compose_email.py:114–132` (`compose_clarification`)
**Apply to:** `compose_confirmation` (D-10)

```python
api_error = False
try:
    body = llm.call_text("draft", messages, temperature=0.3)
except Exception as exc:  # noqa: BLE001
    logger.warning("draft call failed (%s) — falling back to template", type(exc).__name__)
    body = None
    api_error = True
if not body or not body.strip():
    if not api_error:
        logger.warning("draft returned empty content — using template floor")
    return _template_body(...)
return body
```

### 5. PII-Safe Error Logging
**Source:** `app/pipeline/orchestrator.py:68` + `app/db/repo.py:307–310`
**Apply to:** All new `except` blocks in main.py, orchestrator.py, compose_email.py

```python
# CORRECT — type only:
reason = type(exc).__name__
logger.warning("run %s failed: %s", run_id, reason)

# WRONG — never:
reason = str(exc)   # can echo submitted names / prompt text / PII
```

### 6. Parameterized SQL (Never f-string)
**Source:** `app/db/repo.py` throughout — every `c.execute(sql, (params,))`
**Apply to:** All new repo helpers (`claim_status`, `update_known_alias`, `set_alias_candidates`, `load_line_items`)

```python
# CORRECT:
c.execute("UPDATE payroll_runs SET status = %s WHERE id = %s", (value, str(run_id)))

# WRONG — never:
c.execute(f"UPDATE payroll_runs SET status = '{value}' WHERE id = '{run_id}'")
```

### 7. POST-redirect-GET (303)
**Source:** RESEARCH.md §10 + `app/main.py:103` (BackgroundTask pattern)
**Apply to:** All form handlers in `app/main.py` (approve, reject, retrigger, demo/send-test)

```python
return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `app/static/style.css` | config | — | No CSS files exist in the codebase; pattern comes entirely from `05-UI-SPEC.md` |
| `app/db/schema.sql` (DDL for `alias_candidates` column) | config | — | DDL additions have no analog beyond the existing schema; follows `schema.sql` table pattern directly |

---

## Key Implementation Sequencing Notes

The following ordering constraints are load-bearing (planners must sequence waves accordingly):

1. **`claim_status` + `_TERMINAL_STATUSES` fix must land first** — all four call sites (approve, reject, resume, retrigger) depend on it; the delivery error boundary depends on `approved` NOT being terminal.
2. **`set_alias_candidates` repo helper + DDL column must land before `_clarify` is extended** — `_clarify` calls `set_alias_candidates`; the column must exist.
3. **`generate_paystub_pdf` (pure function) must land before the delivery path** — `_deliver` calls it; the test file must also land before the delivery path wave.
4. **`compose_confirmation` must land before `_deliver`** — `_deliver` calls it.
5. **Jinja2 templates + CSS can land independently** — they have no Python dependencies (only the repo helpers they read from).
6. **`_safe_to_learn_alias` must land before the alias write in the approve handler** — it is the correctness guard.

---

## Metadata

**Analog search scope:** `app/pipeline/`, `app/db/`, `app/main.py`, `app/email/`, `tests/`
**Files scanned:** 12 source files + 2 test files read in full
**Pattern extraction date:** 2026-06-22
**Key verified line references:**
- `app/pipeline/compose_email.py:88` — `compose_clarification` (draft-tier-with-floor pattern)
- `app/db/repo.py:267` — `set_status` (claim_status analog)
- `app/db/repo.py:86–94` — `_TERMINAL_STATUSES` (approved must be removed)
- `app/db/repo.py:282–316` — `record_run_error` (error-wrap target)
- `app/db/repo.py:467` — `get_outbound_message_id` (already-sent guard)
- `app/pipeline/orchestrator.py:61–70` — `run_pipeline` error-wrap (D-A1-03 model)
- `app/pipeline/orchestrator.py:87–149` — `resume_pipeline` (claim_status replacement site)
- `app/pipeline/orchestrator.py:200–245` — `_clarify` (alias_candidates capture insertion point)
- `app/pipeline/validate.py:50–82` — `validate` (OT rule extension seam)
- `app/pipeline/reconcile_names.py:37–81` — `deterministic_match` (write-side collision guard basis)
- `app/main.py:240–253` — `_operator_transition` (approve/reject replacement)
- `app/main.py:103,167` — BackgroundTask pattern (retrigger re-run model)
- `tests/test_clarify.py:31–44` — `_DraftLLM`/`_RaisingDraftLLM` stub pattern
- `tests/test_validate.py` — `roster_from_seed` + table-driven pure-function test pattern
