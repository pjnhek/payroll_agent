# Phase 8: Data-Layer Hygiene & Diagnostics - Pattern Map

**Mapped:** 2026-07-02
**Files analyzed:** 10 (5 modify-in-place source files, 2 templates, 2 test files extended, 1 test file possibly extended for supabase.py)
**Analogs found:** 10 / 10 (all touch points are modifications to existing files — each file is its own best analog for surrounding style; cross-file patterns extracted below)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `app/db/schema.sql` (error_detail column) | migration | CRUD (DDL) | same file, `ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS` block :107-112 | exact (self-analog) |
| `app/db/schema.sql` (CREATE INDEX statements) | migration | CRUD (DDL) | same file, `ADD COLUMN IF NOT EXISTS` idempotent-block style — no prior index precedent exists, so the nearest structural analog is the column-add block's placement/comment discipline | role-match (no index precedent in repo) |
| `app/db/schema.sql` (status CHECK swap, NEEDS_CLARIFICATION removal) | migration | CRUD (DDL) | same file, `email_messages.purpose` DROP+ADD CHECK `DO $$ ... END $$;` block :178-199 | exact |
| `app/db/repo.py` (`record_run_error` gains `detail`) | service (data-access) | CRUD | same function, current body :370-404 | exact (self-analog, additive) |
| `app/db/repo.py` (`load_all_runs` explicit columns + aliases) | service (data-access) | CRUD | `load_roster_for_business` :1106-1118 (explicit-column-list + dict_row discipline) and `RUN_COLS` constant :90-93 | exact |
| `app/pipeline/orchestrator.py` (2 call sites + docstring) | controller (pipeline stage) | event-driven (error boundary) | same file, existing catch blocks :179-188 and :661-667 | exact (self-analog, additive) |
| `app/main.py` (approve boundary call site) | controller (route handler) | request-response | same file, existing catch block :502-506 | exact (self-analog, additive) |
| `app/models/status.py` (enum member removal) | model | CRUD | same file — no removal precedent; N/A structurally, single-line edit | exact (self-analog) |
| PII scrubber helper (new, likely inline in `repo.py`) | utility | transform | `app/email/clean.py` (module-level compiled `re.compile`, pure function, docstring-first design rationale) | exact |
| `app/templates/run_detail.html` (error banner 2nd line) | component (Jinja template) | request-response (SSR) | same file, existing error banner block :66-69 | exact (self-analog, additive) |
| `app/templates/runs_list.html` (Summary cell alias switch) | component (Jinja template) | request-response (SSR) | same file, existing Summary cell :63-71 | exact (self-analog, in-place swap) |
| `app/db/supabase.py` (pool singleton lock) | config/singleton | CRUD (connection mgmt) | same file, `get_pool()` :29-51 | exact (self-analog, additive) |
| `tests/test_status_drift.py` (index static guard + count 11→10) | test | CRUD (hermetic static-parse) | same file, `TestEnumCheckDrift` class :89-163 | exact |
| `tests/test_persistence.py` (scrub-ordering + fail-open tests) | test | CRUD (offline FakeConnection) | same file, `test_record_run_error_*` :139-195 | exact |
| `tests/test_dashboard.py` (projection SQL-assertion test) | test | CRUD (offline FakeConnection) | `tests/test_persistence.py`'s `test_record_run_error_skips_terminal_run` `all_sql()` assertion pattern :139-158 | exact (pattern donor is a different file — same fixture) |
| `tests/conftest.py` (`InMemoryRepo.record_run_error`, if new kwargs must be accepted) | test fixture | CRUD | same file, `InMemoryRepo.record_run_error` :331-339 | exact (self-analog, additive) |
| `tests/test_models_contracts.py` (line ~130 expected-values list) | test | CRUD | same file, existing expected-values list | exact (self-analog, one-line edit) |

## Pattern Assignments

### `app/db/schema.sql` — new `error_detail` column (additive)

**Analog:** same file, the existing idempotent column-add block (lines 100-112)

**Pattern to copy** (lines 107-112):
```sql
-- ── Idempotent column adds for payroll_runs (Plan 02-01 / Plan 05-03) ───────────
-- CREATE TABLE IF NOT EXISTS above is a no-op on an existing (Phase 1) table, so
-- these ALTER ... ADD COLUMN IF NOT EXISTS blocks are what actually add the new
-- columns when re-applying schema.sql via the non-destructive bootstrap path.
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS reconciliation    JSONB;  -- D-A3-05
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS error_reason      TEXT;   -- D-A1-03
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS alias_candidates  JSONB;  -- D-04 (Plan 05-03)
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS record_only       BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS pre_clarify_extracted JSONB;  -- D-19 MONEY-03
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS clarified_fields      JSONB;  -- D-13 MONEY-03
```

**What to add:** one more line in this exact block —
```sql
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS error_detail      TEXT;   -- D-8-01/D-8-02: PII-scrubbed, stage-prefixed, truncated exception detail
```
Nullable TEXT, no DEFAULT — matches `error_reason`'s own declaration exactly (nullable, no default, additive comment citing the decision ID).

---

### `app/db/schema.sql` — first-ever `CREATE INDEX IF NOT EXISTS` statements

**Analog:** No prior index precedent exists in this file (confirmed: zero `CREATE INDEX` statements currently). Structural analog is the idempotent-block comment discipline used for column adds and the DO-block constraint adds (lines 201-216, 246-258) — same "one clearly-commented, decision-ID-cited block, placed near the table it targets" convention.

**Pattern to follow:**
```sql
-- Idempotent unique-constraint add for (run_id, purpose) on email_messages (Plan 05-03).
-- NOTE: Postgres does NOT support ADD CONSTRAINT IF NOT EXISTS — the DO $$ pg_constraint
-- guard is the ONLY correct idempotent pattern for adding a named constraint on an existing
-- table. Mirror of the fk_payroll_runs_source_email DO $$ block above.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_email_run_purpose'
          AND conrelid = 'email_messages'::regclass
    ) THEN
        ALTER TABLE email_messages
            ADD CONSTRAINT uq_email_run_purpose UNIQUE (run_id, purpose);
    END IF;
END;
$$;
```
`CREATE INDEX IF NOT EXISTS` is directly idempotent (unlike named constraints) — no DO-block wrapper is needed, unlike the pattern above. Follow the SAME comment-header convention (decision ID + "why this column order" + placement directly after the table's own idempotent-column-add block) but the DDL itself is a flat statement:
```sql
-- D-8-09: first explicit indexes in schema.sql. Column order traced against LIVE
-- query predicates (repo.py), not copied from the audit's guess (see 08-RESEARCH.md
-- Pattern 3). businesses.contact_email is DELIBERATELY excluded — already covered
-- by the NOT NULL UNIQUE constraint's implicit index (D-8-09).
CREATE INDEX IF NOT EXISTS idx_email_messages_run_direction_state
    ON email_messages (run_id, direction, send_state);
CREATE INDEX IF NOT EXISTS idx_payroll_runs_created_at
    ON payroll_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payroll_runs_status
    ON payroll_runs (status);
```
Place these near the end of each table's own section (mirrors where `uq_email_run_purpose`'s DO-block sits directly after the `email_messages` table body) — NOT all bundled at the file's end, to keep index-to-table locality consistent with the rest of the file's organization.

---

### `app/db/schema.sql` — `payroll_runs.status` CHECK swap (NEEDS_CLARIFICATION removal)

**Analog:** `email_messages.purpose` DROP+ADD CHECK block, schema.sql lines 174-199 (D-7.5-03a pattern, exact template)

**Pattern to copy verbatim, columns/values swapped** (lines 178-199):
```sql
-- N4 MONEY-03: Idempotent DROP + RE-ADD of email_messages purpose CHECK constraint
-- (D-7.5-03a atomic DROP+ADD in one transaction). The pg_constraint lookup is narrowed
-- by BOTH contype='c' AND conrelid='email_messages'::regclass before applying the LIKE
-- pattern (Finding 9 defensive matcher). The new CHECK includes 'clarification_field_regression'.
DO $$
DECLARE
    _con_name TEXT;
BEGIN
    SELECT conname INTO _con_name
    FROM pg_constraint
    WHERE contype = 'c'
      AND conrelid = 'email_messages'::regclass
      AND conname LIKE '%purpose%';
    IF _con_name IS NOT NULL THEN
        EXECUTE 'ALTER TABLE email_messages DROP CONSTRAINT ' || quote_ident(_con_name);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'email_messages_purpose_check'
          AND conrelid = 'email_messages'::regclass
    ) THEN
        ALTER TABLE email_messages ADD CONSTRAINT email_messages_purpose_check
            CHECK (purpose IN ('clarification','confirmation','clarification_field_regression'));
    END IF;
END;
$$;
```
Adapt to `contype = 'c' AND conrelid = 'payroll_runs'::regclass AND conname LIKE '%status%'`, target constraint name `payroll_runs_status_check`, and the new value list is the CURRENT 11-value list at schema.sql:66-78 minus `'needs_clarification'` (10 values: received, extracting, awaiting_reply, computed, awaiting_approval, approved, sent, reconciled, rejected, error). Also update the INLINE `CHECK (status IN (...))` at table-creation time (lines 65-78) to drop the value too — the DO-block only fixes an EXISTING table; a fresh `CREATE TABLE` still needs the inline CHECK corrected so a brand-new bootstrap doesn't need the DO-block to self-correct.

**Pre-migration guard (human checkpoint, not code):** `SELECT count(*) FROM payroll_runs WHERE status = 'needs_clarification'` must return 0 before this runs live — `ADD CONSTRAINT` validates all existing rows.

---

### `app/db/repo.py` — `record_run_error` gains `detail` (+ centralized scrub helper)

**Analog:** same function, current body (repo.py lines 370-404)

**Imports pattern already established at top of file** (repo.py lines 59-72):
```python
from __future__ import annotations

import contextlib
import json
import logging
import uuid
from typing import Any

import psycopg.rows

from app.db.supabase import get_connection
from app.models.contracts import ClarifiedFields, Decision, Extracted, PaystubLineItem
from app.models.roster import Employee, NameMatchResult, Roster
from app.models.status import RunStatus
```
Add `import re` alongside `contextlib`/`json`/`logging`/`uuid` (alphabetical stdlib-import convention already followed).

**Current core pattern to extend** (lines 370-404, full function — this is what the plan modifies in place):
```python
def record_run_error(run_id: uuid.UUID, reason: str, conn=None) -> None:
    """Write payroll_runs.error_reason AND advance the run to ERROR. ..."""
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            current = c.execute(
                "SELECT status FROM payroll_runs WHERE id = %s", (str(run_id),)
            ).fetchone()
            if current is not None and current[0] in _TERMINAL_STATUSES:
                logger.info(
                    "record_run_error skipped: run %s is terminal (%s) — not "
                    "clobbering to ERROR (WR-04). reason was: %s",
                    run_id, current[0], reason,
                )
                return
            c.execute(
                "UPDATE payroll_runs SET error_reason = %s, updated_at = now() WHERE id = %s",
                (reason, str(run_id)),
            )
            set_status(run_id, RunStatus.ERROR, conn=c)
```
**Key invariant to preserve:** the `_TERMINAL_STATUSES` early-return (WR-04) must stay BEFORE any new detail-building work — a terminal run must not have `error_detail` computed OR written, matching today's `error_reason` no-op. The new `UPDATE` statement adds `error_detail = %s` as a second SET clause + a new bound param; this is still ONE UPDATE inside the SAME transaction (no new query, matching the RESEARCH.md recommendation).

**Fail-open wrapper pattern to write (new, no direct in-repo analog — closest structural precedent is the file's own docstring-driven "one documented exception" style used for `record_run_error` itself, i.e. wrap the risky step in its own try/except with a comment explaining WHY it must never propagate):**
```python
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_REDACTED = "[REDACTED]"


def _scrub(message: str, roster: Roster | None = None) -> str:
    """Deterministic, fail-open PII scrub (D-8-01b). NEVER loads roster from DB —
    the error path may be running because the DB itself is down."""
    scrubbed = _EMAIL_RE.sub(_REDACTED, message)
    if roster is not None:
        for employee in roster.employees:
            for name in (employee.full_name, *employee.known_aliases):
                if name:
                    scrubbed = scrubbed.replace(name, _REDACTED)
    return scrubbed


def _build_error_detail(stage: str, exc: Exception, roster: Roster | None = None) -> str | None:
    """Scrub-THEN-truncate (D-8-01); fail-open on any scrub exception (D-8-01b)."""
    try:
        scrubbed = _scrub(str(exc), roster=roster)
        return f"{stage}: {scrubbed}"[:200]
    except Exception:  # noqa: BLE001 — diagnostics must never break diagnostics
        return None
```
This mirrors the file's existing `# noqa: BLE001` broad-except convention already used at orchestrator.py:181/661 and main.py:502 — the SAME comment style ("diagnostics must never break X") should be reused here for consistency.

**Error handling pattern (existing broad-except convention across the codebase, to match exactly):**
```python
except Exception as exc:  # noqa: BLE001 — <specific reason this boundary exists>
```
Every one of the 3 call sites already uses this exact `# noqa: BLE001` + inline reason-comment convention (orchestrator.py:181, orchestrator.py:661, main.py:502) — the new `_build_error_detail`'s internal try/except should follow the identical style.

---

### `app/db/repo.py` — `load_all_runs` explicit columns + computed aliases

**Analog:** `load_roster_for_business` (repo.py lines 1106-1118) for the explicit-column-list + dict_row discipline; `RUN_COLS` constant (repo.py lines 90-93) for the naming/comment convention of an explicit column-list constant.

**Current `load_all_runs` body to replace** (repo.py lines 1088-1103):
```python
def load_all_runs(conn=None) -> list[dict]:
    """Return all payroll runs in reverse-chronological order, with business_name.

    Used by the runs-list route (DASH-01). Joins businesses to surface business_name
    without requiring a second query in the route layer.
    """
    sql = (
        "SELECT pr.*, b.name as business_name"
        " FROM payroll_runs pr"
        " JOIN businesses b ON pr.business_id = b.id"
        " ORDER BY pr.created_at DESC"
    )
    with _conn_ctx(conn) as (c, _owns):
        with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql)
            return cur.fetchall() or []
```

**Explicit-column-list constant convention to match** (`RUN_COLS`, repo.py lines 84-93):
```python
# Explicit column list for reading a run (only what callers need; no SELECT *).
# CR-02 fix: updated_at is included so load_run() returns it as a tz-aware
# datetime (the column is TIMESTAMPTZ — psycopg returns tz-aware datetimes).
RUN_COLS = (
    "id, business_id, source_email_id, status, extracted_data, decision,"
    " reconciliation, error_reason, pay_period_start, pay_period_end, updated_at"
)
```
`load_all_runs` should NOT reuse `RUN_COLS` verbatim (it doesn't need `extracted_data`/`decision` whole — that's the exact JSONB-blob-crossing-the-wire problem D-8-07 closes) — instead build its OWN scalar list + the two SQL-computed aliases, matching the `dict_row` cursor pattern from `load_roster_for_business`:
```python
def load_all_runs(conn=None) -> list[dict]:
    """Return all payroll runs in reverse-chronological order, with business_name.

    D-8-07: explicit scalar column list + 2 SQL-computed aliases — no JSONB blob
    (decision/extracted_data) crosses the wire for the list view (WR-03 perf fix).
    summary_gate_reason and employee_count are NULL-safe (COALESCE) so an early-stage
    run (decision/extracted_data still NULL) renders without a Jinja guard needed
    server-side.
    """
    sql = (
        "SELECT pr.id, pr.business_id, pr.status, pr.created_at, pr.updated_at,"
        " b.name AS business_name,"
        " pr.decision->'gate_reasons'->>0 AS summary_gate_reason,"
        " COALESCE(jsonb_array_length(pr.extracted_data->'employees'), 0) AS employee_count"
        " FROM payroll_runs pr"
        " JOIN businesses b ON pr.business_id = b.id"
        " ORDER BY pr.created_at DESC"
    )
    with _conn_ctx(conn) as (c, _owns):
        with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql)
            return cur.fetchall() or []
```
Verify the exact scalar set (`business_id`/`updated_at` inclusion) against `runs_list.html`'s actual field usage at implementation time — D-8-07's own discretion note.

---

### `app/pipeline/orchestrator.py` — 2 call sites gain `detail=`/`stage=`

**Analog:** same file, existing catch blocks (this is a same-file additive change, not a cross-file pattern borrow)

**Call site 1 — `run_pipeline` catch-all** (lines 179-188, current):
```python
def run_pipeline(run_id: uuid.UUID, *, llm=None) -> None:
    try:
        _run(run_id, llm=llm)
    except Exception as exc:  # noqa: BLE001 — the D-A1-03 error-wrap boundary
        reason = type(exc).__name__
        logger.warning("run %s failed: %s", run_id, reason)
        repo.record_run_error(run_id, reason)   # <- gains detail_exc=exc, stage="pipeline"
```
**Roster-availability caveat (verified):** `roster = repo.load_roster_for_business(...)` happens inside `_run()` (line 199), NOT in `run_pipeline`'s own scope — `run_pipeline`'s except block has NO roster variable in scope at all. Passing `roster=` here is not possible without restructuring `_run` to return/expose it; simplest correct approach is `roster=None` at this call site (regex-only fallback, which D-8-01b explicitly sanctions as correct, not degraded).

**Call site 2 — `resume_pipeline` catch-all** (lines 661-667, current):
```python
    except Exception as exc:  # noqa: BLE001 — the D-A1-03 error-wrap boundary (resume)
        reason = type(exc).__name__
        logger.warning("resume of run %s failed: %s", run_id, reason)
        repo.record_run_error(run_id, reason)   # <- gains detail_exc=exc, stage="resume"
```
**Roster-availability caveat:** `roster = repo.load_roster_for_business(run["business_id"])` executes at line 247, INSIDE the same try block this except clause guards — so roster MAY be unbound if the exception is raised before line 247 (e.g. `load_run` returning `None` at line 245-246). Guard with `roster = locals().get("roster")` or initialize `roster = None` at the top of the try block before first use.

**Stale docstring to update** (line ~174, per CONTEXT.md D-none but folded todo 260623-06): the `run_pipeline` docstring currently reads:
```python
    """Drive one run from received → awaiting_approval (or needs_clarification).
```
Update the parenthetical since `needs_clarification` is removed and was never actually the real routing target (`_clarify()` always routes to `awaiting_reply`) — e.g. `"""Drive one run from received → awaiting_approval (or awaiting_reply on a clarification)."""`.

---

### `app/main.py` — approve boundary call site gains `detail=`/`stage=`

**Analog:** same file, existing catch block (lines 502-506, current)
```python
        try:
            run = repo.load_run(run_id)
            _deliver(run_id, run)
        except Exception as exc:  # noqa: BLE001 — D-13b error boundary
            logger.warning("delivery of run %s failed: %s", run_id, type(exc).__name__)
            repo.record_run_error(run_id, type(exc).__name__)   # <- gains detail_exc=exc, stage="delivery"
```
**Roster availability:** `approve()` never loads a roster at all — `roster=None` here is correct by design (D-8-01b: `roster=None` degrades to regex-only, not a gap), matching RESEARCH.md's explicit confirmation of this call site.

---

### `app/models/status.py` — `NEEDS_CLARIFICATION` removal

**Analog:** same file (single-line removal from the `RunStatus` enum, line 19)
```python
class RunStatus(str, enum.Enum):
    RECEIVED = "received"
    EXTRACTING = "extracting"
    NEEDS_CLARIFICATION = "needs_clarification"   # <- DELETE this line
    AWAITING_REPLY = "awaiting_reply"
    ...
```
Also update the module docstring's "Eleven-state lifecycle" (line 10) → "Ten-state lifecycle" and the file-header comment (line 1) "11 pipeline status values" → "10 pipeline status values" — both are drift-adjacent comments that should track the real count for the next reader (not machine-checked, but the file's own stated discipline is to be the "canonical source").

---

### `app/templates/run_detail.html` — error banner second line

**Analog:** same file, existing error banner block (lines 66-69)
```html
{% if run.status == 'error' %}
<div class="banner banner-error banner-mb">
  <strong>Error</strong> — {{ run.error_reason }}. Use the Re-trigger button below to restart this run from the beginning.
</div>
{% elif ...
```
**D-8-06 pattern:** keep the existing line BYTE-IDENTICAL, append a conditional second line:
```html
{% if run.status == 'error' %}
<div class="banner banner-error banner-mb">
  <strong>Error</strong> — {{ run.error_reason }}. Use the Re-trigger button below to restart this run from the beginning.
  {% if run.error_detail %}
  <div class="banner-detail">{{ run.error_detail }}</div>
  {% endif %}
</div>
{% elif ...
```
Match the existing `banner-divider`/`column-label` inline-style convention used elsewhere in this same file (lines 73-74) if a dedicated CSS class isn't already defined — check the project stylesheet for an existing `banner-detail`-equivalent class before inventing a new one.

---

### `app/templates/runs_list.html` — Summary cell alias switch

**Analog:** same file, existing Summary cell (lines 63-71)
```html
<td class="text-muted">
  {% if run.decision and run.decision.gate_reasons %}
    {{ run.decision.gate_reasons[0] }}
  {% elif run.extracted_data and run.extracted_data.employees %}
    {{ run.extracted_data.employees | length }} employee{{ 's' if run.extracted_data.employees | length != 1 else '' }}
  {% else %}
    —
  {% endif %}
</td>
```
**D-8-08 replacement** (switch to the two SQL-computed aliases; NULL-safety already handled server-side by `COALESCE`/`->>'` chain-NULL, so the Jinja guard simplifies):
```html
<td class="text-muted">
  {% if run.summary_gate_reason %}
    {{ run.summary_gate_reason }}
  {% elif run.employee_count %}
    {{ run.employee_count }} employee{{ 's' if run.employee_count != 1 else '' }}
  {% else %}
    —
  {% endif %}
</td>
```

---

### `app/db/supabase.py` — pool-singleton thread-safety guard (WR-02)

**Analog:** same file, `get_pool()` (lines 29-51, current)
```python
_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=5,
            open=True,
            kwargs={"prepare_threshold": None},
            timeout=5,
        )
    return _pool
```
**Guard pattern to add** — a module-level `threading.Lock()` around the check-then-create (standard double-checked-locking idiom; no existing lock precedent elsewhere in the codebase to copy, so this introduces the pattern fresh, matching stdlib `threading` conventions):
```python
import threading

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:  # re-check inside the lock (double-checked locking)
                settings = get_settings()
                _pool = ConnectionPool(
                    conninfo=settings.database_url,
                    min_size=1,
                    max_size=5,
                    open=True,
                    kwargs={"prepare_threshold": None},
                    timeout=5,
                )
    return _pool
```
Per RESEARCH.md Open Question 1: treat as a real (not theoretical) race given FastAPI's threadpool executor for sync routes/BackgroundTasks even under Render's single-process deploy — implement the lock rather than document-only.

## Shared Patterns

### Broad-except + `# noqa: BLE001` + reason comment
**Source:** `app/pipeline/orchestrator.py:181,661`, `app/main.py:502`
**Apply to:** the new `_build_error_detail` internal try/except, and any new call-site edits
```python
except Exception as exc:  # noqa: BLE001 — <boundary-specific reason, one line>
```

### PII-safe logging discipline (D-A1-03 lineage)
**Source:** `app/pipeline/orchestrator.py:182-186`, `app/main.py:488,503-504`
**Apply to:** any new log line touching `str(exc)` — the codebase's established rule is `reason = type(exc).__name__` for LOGGING (never the full message), while `error_detail` is the FIRST place `str(exc)` is persisted at all (post-scrub). Do not introduce a new raw `str(exc)` log line anywhere in this phase — that would reopen the exact leak D-8-01 closes, just via `logger.warning` instead of the DB.

### Explicit-column-list discipline (no `SELECT *` / no `pr.*`)
**Source:** `EMPLOYEE_COLS`/`RUN_COLS` (`app/db/repo.py:76-93`), `load_roster_for_business` (`app/db/repo.py:1106-1118`), `load_outbound_emails` (`app/db/repo.py:834-852`)
**Apply to:** `load_all_runs` rewrite — every read-back in this file that rebuilds a contract or renders a dashboard already follows "explicit column list, `dict_row` cursor, comment citing why no `SELECT *`." Match that exactly; do not introduce a bare `SELECT *` or `pr.*` anywhere.

### Idempotent DDL block style (`ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, DO-block CHECK swap)
**Source:** `app/db/schema.sql:100-112` (column adds), `:174-199` (DROP+ADD CHECK), `:201-216` (DO-block constraint add), `:246-258` (deferred FK DO-block)
**Apply to:** all three schema.sql changes this phase makes (error_detail column, 3 new indexes, status CHECK swap). Every block in this file has a header comment citing the decision ID and WHY (not just what) — match that convention for the new blocks; this is the single most consistent stylistic signature in the file.

### FakeConnection offline SQL-assertion test pattern
**Source:** `tests/conftest.py:81-167` (`FakeCursor`/`FakeTransaction`/`FakeConnection`, `fake_conn` fixture), `tests/test_persistence.py:139-195` (`test_record_run_error_skips_terminal_run` et al.)
**Apply to:** the new `record_run_error` detail/scrub tests (D-8-04a straddle-boundary, D-8-04b fail-open) AND the new `load_all_runs` projection test — both use `fake_conn.script_fetchone(...)` to script a return row, call the real `repo.*` function with `conn=fake_conn`, then assert against `fake_conn.all_sql()`:
```python
def test_record_run_error_skips_terminal_run(fake_conn):
    from app.db import repo
    fake_conn.script_fetchone(("sent",))
    repo.record_run_error(uuid.uuid4(), "boom: a late resume hit an exception", conn=fake_conn)
    sql = fake_conn.all_sql()
    assert "SELECT status" in sql
    assert "SET error_reason" not in sql
```
For the `load_all_runs` projection test, the analogous shape is: script a `fetchall` result, call `repo.load_all_runs(conn=fake_conn)`, then assert on `fake_conn.all_sql()` that `"pr.*"` is absent and the explicit column names ARE present.

### `roster_from_seed` fixture for scrub tests needing a real roster
**Source:** `tests/conftest.py:196-204`
```python
@pytest.fixture
def roster_from_seed() -> Roster:
    """Build a Roster for the happy-path business from seed(dry_run=True)."""
    from app.db.seed import seed
    result = seed(dry_run=True)
    business_id = result.employees[0].business_id
    employees = [e for e in result.employees if e.business_id == business_id]
    return Roster(business_id=business_id, employees=employees)
```
**Apply to:** the D-8-04 PII test that seeds an exception message containing BOTH a roster name and an email address — use this fixture to get a real `Roster` with real employee names/aliases to pass into `_build_error_detail(stage, exc, roster=roster_from_seed)`.

### Static-file drift-guard test pattern (`test_status_drift.py`)
**Source:** `tests/test_status_drift.py:89-163` (`TestEnumCheckDrift` class), especially `test_no_db_connection_needed` (AST-based import guard, lines 133-163)
**Apply to:** the new index static guard — mirror the class structure: parse `schema.sql` text with `re`/regex extraction helpers (not a real SQL parser), assert the 3-4 new `CREATE INDEX IF NOT EXISTS` statements are present with the correct column lists, assert `businesses.contact_email` is still `NOT NULL UNIQUE` (the substitute proof for the "don't duplicate" decision), and copy the `test_no_db_connection_needed` AST-walk verbatim (adjust `_FORBIDDEN` set if needed) so the new test class is provably hermetic like its sibling. Also update `test_status_exact_count_is_eleven` → rename and change `11` to `10` in both the SQL-parsed count and the enum-member count (lines 118-131).

### `InMemoryRepo.record_run_error` — must accept new kwargs without erroring
**Source:** `tests/conftest.py:331-339`
```python
def record_run_error(self, run_id, reason, conn=None):
    from app.db.repo import _TERMINAL_STATUSES
    from app.models.status import RunStatus
    ...
```
**Apply to:** add `detail_exc=None, stage=None, roster=None` (or whatever final param names are chosen) as accepted-but-optionally-no-op kwargs here, so integration-style tests that monkeypatch through `InMemoryRepo` don't raise `TypeError` on the new call shape from orchestrator.py/main.py. This is Pitfall 4 from RESEARCH.md — verify `tests/test_threading.py`'s own fake `record_run_error` similarly at implementation time (not read in this session; grep for it before finalizing the plan).

## No Analog Found

None — every file this phase touches is a modification to an existing file, and every modification has either a direct same-file precedent (additive change, e.g. one more line in an existing block) or a clear cross-file precedent (e.g. the CHECK-swap DO-block, the FakeConnection test style). The only genuinely NEW code is the PII scrubber helper (`_scrub`/`_build_error_detail`) and the `threading.Lock()` guard in `supabase.py` — both are small enough (< 20 lines each) that RESEARCH.md's own "Don't Hand-Roll" section already concluded no external library or existing analog is warranted; the design sketch in RESEARCH.md Pattern 1 (Code Examples) is the pattern to implement, refined above against the CURRENT `_TERMINAL_STATUSES` guard ordering.

## Metadata

**Analog search scope:** `app/db/`, `app/pipeline/`, `app/main.py`, `app/models/`, `app/templates/`, `app/email/`, `tests/` (conftest.py, test_status_drift.py, test_persistence.py, test_dashboard.py, test_models_contracts.py)
**Files scanned:** `app/db/schema.sql` (258 lines, full), `app/db/repo.py` (lines 1-200, 360-460, 751-900, 1080-1130 — targeted, non-overlapping), `app/pipeline/orchestrator.py` (lines 160-270, 640-670 — targeted), `app/main.py` (lines 470-510 — targeted), `app/models/status.py` (full, 27 lines), `app/models/roster.py` (lines 1-80 — targeted), `app/db/supabase.py` (full, 83 lines), `app/email/clean.py` (full, 75 lines), `app/templates/run_detail.html` (lines 55-75 — targeted), `app/templates/runs_list.html` (lines 40-75 — targeted), `tests/test_status_drift.py` (full, 164 lines), `tests/conftest.py` (lines 75-335 — targeted), `tests/test_persistence.py` (lines 1-200 — targeted)
**Pattern extraction date:** 2026-07-02

---

## PATTERN MAPPING COMPLETE

**Phase:** 8 - Data-Layer Hygiene & Diagnostics
**Files classified:** 17
**Analogs found:** 17 / 17

### Coverage
- Files with exact analog (same-file additive or direct cross-file template): 17
- Files with role-match analog only: 0
- Files with no analog: 0

### Key Patterns Identified
- Every schema.sql change follows the file's own idempotent-DDL-block convention (`ADD COLUMN IF NOT EXISTS` for the new nullable column, the exact D-7.5-03a DROP+ADD `DO $$` block for the CHECK swap, flat `CREATE INDEX IF NOT EXISTS` statements placed near their target table) — no new DDL idiom is introduced.
- `record_run_error` centralizes ALL PII scrubbing in one place inside the data-access layer itself (not at the 3 call sites), preserving the existing `_TERMINAL_STATUSES` early-return ordering and the codebase-wide `# noqa: BLE001` + reason-comment broad-except convention.
- `load_all_runs` adopts the file's established explicit-column-list discipline (already used by `RUN_COLS`/`EMPLOYEE_COLS`/`load_roster_for_business`) plus two NULL-safe SQL-computed aliases so no JSONB blob crosses the wire — matching, not deviating from, the "extra='forbid' means no SELECT *" philosophy stated in the module docstring.
- All new tests reuse existing fixtures verbatim: `fake_conn` (FakeConnection SQL-assertion), `roster_from_seed` (real Roster for PII-scrub tests), and `TestEnumCheckDrift`'s static-parse-and-assert class shape for the new index guard — zero new test infrastructure needed.

### File Created
`/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-PATTERNS.md`

### Ready for Planning
Pattern mapping complete. Planner can now reference analog patterns in PLAN.md files.
