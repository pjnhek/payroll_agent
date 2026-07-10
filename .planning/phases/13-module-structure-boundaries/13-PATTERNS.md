# Phase 13: Module Structure & Boundaries - Pattern Map

**Mapped:** 2026-07-09
**Files analyzed:** 24 new/modified files (5 routers + 2 shared route modules + thin `main.py`; 5 repo aggregate modules + 1 shared internal + facade `__init__.py`; 3 pipeline carve-outs + trimmed `orchestrator.py` + 2 promotion-only edits; 1 new AST guard test)
**Analogs found:** 24 / 24 (this is a pure internal decomposition — every new file's analog is a slice of the god-file it's extracted from, or a small existing module showing the target module's shape/docstring/import conventions)

**How to read this document:** Because STRUCT-01/02/03 require **verbatim code movement** (no
rewriting, no re-deriving), the "pattern" for the bulk of each new file's *body* is simply "the
exact lines already at the cited location in the god-file" (see 13-RESEARCH.md's line-number
inventory — this document does not repeat that full inventory). What this document adds on top:
concrete **module-header conventions** (docstring style, import block shape, section-banner
style) from the best-fit existing small module for each new file's *role*, plus the exact
**import-discipline patterns** (module-object imports, `_conn_ctx`-style helpers, package-facade
re-export shape) the planner must apply at every cut line.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `app/routes/health.py` | route | request-response | `app/main.py` lines 244-301 (health routes, in place) | exact (verbatim extract) |
| `app/routes/webhook.py` | route | event-driven (ingest) | `app/main.py` lines 304-577 (webhook route, in place) | exact (verbatim extract) |
| `app/routes/runs.py` | route | request-response (CRUD + CAS) | `app/main.py` lines 769-1090, 1335-1523, 1583-1751 (runs*/pdf/simulate-reply, in place) | exact (verbatim extract) |
| `app/routes/dashboard.py` | route | request-response (SSR) | `app/main.py` lines 1143-1213, 1528-1627 (landing/eval/chart, in place) | exact (verbatim extract) |
| `app/routes/demo.py` | route | request-response | `app/main.py` lines 1218-1330, 1751-1857 (demo routes, in place) | exact (verbatim extract) |
| `app/routes/pipeline_glue.py` | utility (HTTP↔orchestrator bridge) | event-driven / background-task | `app/main.py` lines 578-760, 944-963 (shared helpers, in place) | exact (verbatim extract) |
| `app/routes/templating.py` | config/provider | n/a (module-level singleton) | `app/main.py` lines 180-236 (templates + badge filters, in place) | exact (verbatim extract) |
| `app/routes/__init__.py` | config (package marker) | n/a | `app/pipeline/__init__.py` (6-line package docstring) | role-match |
| `app/main.py` (rewritten, thin) | config (app assembly) | n/a | `app/db/bootstrap.py` (small, single-purpose, clear docstring + `if __name__` pattern) for docstring/structure tone; FastAPI app-creation lines 178-186 (in place) for the assembly body itself | role-match |
| `app/db/repo/__init__.py` | provider (package facade) | request-response (pass-through re-export) | none exists yet in this codebase — closest shape precedent is `app/pipeline/__init__.py` (package docstring style) + `app/db/repo.py` itself (the full symbol list to re-export) | no direct facade analog; RESEARCH Pattern 1 code example is authoritative |
| `app/db/repo/_shared.py` | utility (internal plumbing) | n/a | `app/db/repo.py` lines 156-164, 1731-1734 (`_conn_ctx`/`_nulltx`, in place) | exact (verbatim extract) |
| `app/db/repo/runs.py` | model/service (DB aggregate) | CRUD + event-driven (status CAS) | `app/db/repo.py` lines 171-521, 556-728 (ingest/lifecycle + status CAS + scrub/error, in place) | exact (verbatim extract) |
| `app/db/repo/pipeline_state.py` | model/service (DB aggregate) | CRUD (JSONB persistence) | `app/db/repo.py` lines 729-1055 (persist/load extracted/decision/clarify context, in place) | exact (verbatim extract) |
| `app/db/repo/emails.py` | model/service (DB aggregate) | CRUD + event-driven (threading) | `app/db/repo.py` lines 1062-1449 (email_messages, in place) | exact (verbatim extract) |
| `app/db/repo/roster.py` | model/service (DB aggregate) | CRUD (read) | `app/db/repo.py` lines 1712-1723 (`load_roster_for_business`, in place) | exact (verbatim extract) |
| `app/db/repo/demo.py` | model/service (DB aggregate) | CRUD | `app/db/repo.py` lines 1450-1652, 1657-1710 (demo/dashboard, in place) | exact (verbatim extract) |
| `app/pipeline/alias_learning.py` | service (pipeline stage helper) | transform + CRUD (writes via repo) | `app/pipeline/orchestrator.py` lines 80-157, 1503-1590 (alias helpers, in place) + `app/pipeline/reconcile_names.py` lines 167-203 (`_safe_to_learn_alias`, relocating in) | exact (verbatim extract + relocation) |
| `app/pipeline/clarification.py` | service (pipeline stage helper) | event-driven (compose + send) | `app/pipeline/orchestrator.py` lines 937-1088, 1229-1500 (clarify cluster, in place) | exact (verbatim extract) |
| `app/pipeline/delivery.py` | service (pipeline stage helper) | event-driven (compose + send + PDF) | `app/pipeline/orchestrator.py` lines 1592-1800 (`_deliver`, in place) | exact (verbatim extract) |
| `app/pipeline/orchestrator.py` (trimmed) | service (state machine) | event-driven / batch (multi-stage pipeline) | itself, minus the three carve-outs above (core stays: `run_pipeline`, `_run`, `resume_pipeline`, `_run_stages`, `_compute_line_items`, `backfill_extracted`) | exact (subtraction, not extraction) |
| `app/pipeline/reconcile_names.py` (promotion edit) | service (pure stage) | transform | itself, lines 39, 167 (`_norm`→`normalize_name` rename; `_safe_to_learn_alias` moves out entirely per D-10) | exact (rename-in-place) |
| `app/pipeline/validate.py` (promotion edit) | service (pure stage) | transform | itself, lines 30, 39 (`_HOURS_FIELDS`→`HOURS_FIELDS`, `_is_paid`→`is_paid`) | exact (rename-in-place) |
| `eval/run_eval.py` (import retarget) | script | batch | itself, line 39 (`_norm` import → `normalize_name`) | exact (mechanical) |
| `tests/test_bound01_private_imports.py` (new) | test | batch (static analysis) | RESEARCH.md's "AST-based BOUND-01 guard" code example (fully-formed, ready to adapt) — no existing test in this codebase does AST-walking, so the RESEARCH example is the primary source, not a codebase analog | no codebase analog; use RESEARCH code example directly |

## Pattern Assignments

### `app/routes/health.py`, `webhook.py`, `runs.py`, `dashboard.py`, `demo.py` (route, request-response)

**Analog:** `app/main.py` itself — the routes already exist verbatim at the cited line ranges;
this is a **cut-and-paste-with-import-fixups** operation, not a rewrite. Below is the header/import
convention every new router module must replicate, taken directly from `main.py`'s own style.

**Module docstring pattern** (from `app/main.py` lines 1-37 — every router module should open with
a short "what lives here" list mirroring this style, scaled down to just its own routes):
```python
"""FastAPI entrypoint — the thin webhook adapter + operator gate routes.
...
Endpoints:
  POST /webhook/inbound          — ingest an InboundEmail, dedupe, sender-match,
                                   clean the body, create the run, schedule run_pipeline
  ...
"""
from __future__ import annotations
```

**Imports pattern** (`app/main.py` lines 38-60 — `from __future__ import annotations` first,
stdlib block, then `fastapi.*`, then `app.*` alphabetized by module):
```python
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.db import repo
from app.db.schema_introspect import diff_against_live
from app.db.supabase import get_connection
from app.email import gateway
from app.email.clean import clean_body
from app.models.contracts import InboundEmail
from app.models.status import RunStatus
```
Per-router, trim to only what that router's cut-out routes use, plus (per D-08/Pattern 3 in
RESEARCH) `from app.routes.templating import templates` and `from fastapi import APIRouter` /
`router = APIRouter()` in place of `app = FastAPI(...)`.

**APIRouter registration pattern** (RESEARCH Pattern 3, concrete target shape for each router
module and for the new thin `main.py`):
```python
# app/routes/runs.py
from fastapi import APIRouter
from app.routes.templating import templates
from app.db import repo

router = APIRouter()

@router.get("/runs")
def runs_list(request: Request, background_tasks: BackgroundTasks):
    ...
    return templates.TemplateResponse(request, "runs_list.html", {...})

# app/main.py
from fastapi import FastAPI
from app.routes import webhook, runs, dashboard, demo, health

app = FastAPI(title="Payroll Agent")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(health.router)
app.include_router(webhook.router)
app.include_router(runs.router)
app.include_router(dashboard.router)
app.include_router(demo.router)
```

**Core route pattern — CAS claim + error boundary** (`app/main.py` lines 769-814, `approve()` —
copy verbatim into `routes/runs.py`, only the `_deliver` import line changes per D-07):
```python
@app.post("/runs/{run_id}/approve")
def approve(
    run_id: uuid.UUID,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    """Hardened approve: CAS claim (AWAITING_APPROVAL → APPROVED) + D-13b delivery. ..."""
    from app.pipeline.orchestrator import _deliver   # BECOMES: from app.pipeline import delivery

    claimed = repo.claim_status(run_id, RunStatus.AWAITING_APPROVAL, RunStatus.APPROVED)
    if claimed:
        try:
            run = repo.load_run(run_id)
            _deliver(run_id, run)                    # BECOMES: delivery.deliver(run_id, run)
        except Exception as exc:  # noqa: BLE001 — D-13b error boundary
            logger.warning("delivery of run %s failed: %s", run_id, type(exc).__name__)
            repo.record_run_error(
                run_id, type(exc).__name__, detail_exc=exc, stage="delivery",
                roster=getattr(exc, "payroll_roster", None),
            )
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
```

**Error handling pattern** (repeated throughout `main.py`'s HITL routes): `except Exception as exc:
# noqa: BLE001 — <named boundary>` + `logger.warning`/`logger.error` with `type(exc).__name__`
ONLY (never `str(exc)`, per D-A1-03 PII-safety) + a `repo.record_run_error(...)` call. Every moved
route keeps this exact shape unchanged.

**Health-probe error pattern** (`app/main.py` lines 255-301, → `routes/health.py` verbatim):
```python
@app.get("/health/ready")
def health_ready() -> JSONResponse:
    try:
        from app.db.supabase import get_connection
        with get_connection() as conn:
            conn.execute("SELECT 1 FROM businesses LIMIT 1")
        return JSONResponse({"status": "ready"})
    except Exception as exc:
        logger.error("readiness probe failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="database not ready") from exc
```

**Shared module-level constants** — per RESEARCH Open Question #1 (Claude's Discretion), land
`STALE_THRESHOLD`/`STALE_THRESHOLD_SECONDS`/`IN_FLIGHT_STATUSES` in `routes/runs.py` (verbatim from
`main.py` lines 62-115) since `retrigger`/`runs_list` are the heaviest consumers; `pipeline_glue.py`
imports them from there. Land `_DEMO_FIXTURES`/`DEMO_OPERATOR_EMAIL`/`_SEED_CONTACTS`/
`_SEED_BUSINESS_IDS` (lines 117-174) in `routes/demo.py`; `routes/dashboard.py`'s `landing` imports
what it needs from `routes/demo.py`. Do not duplicate either constant set.

---

### `app/routes/pipeline_glue.py` (utility, event-driven / background-task bridge)

**Analog:** `app/main.py` lines 578-760, 944-963 (the shared `_run_pipeline`/`_resume_pipeline`/
`_route_reply`/`_reply_sender_ok`/`_row_to_inbound`/`_finish_reply_resume`/`_operator_resume`
cluster, in place today).

**Promotion requirement (D-07 + BOUND-01):** these seven helpers move to `app/routes/pipeline_glue.py`
with **public names** (drop the leading underscore on all seven — this is itself a BOUND-01-style
promotion even though it's not in D-14's inventory, because `webhook.py` and `runs.py` will need to
call them as **cross-module** references once split out of `main.py`).

**Module-object import discipline at the call sites** (mirrors D-11's orchestrator pattern, applied
here per RESEARCH Pitfall 3):
```python
# app/routes/webhook.py
from app.routes import pipeline_glue

...
    background_tasks.add_task(pipeline_glue.run_pipeline_bg, run_id)   # was: background_tasks.add_task(_run_pipeline, run_id)
```
Never `from app.routes.pipeline_glue import run_pipeline_bg` — the module-object form is what
keeps `monkeypatch.setattr(pipeline_glue, "run_pipeline_bg", ...)` (the retargeted test seam) able
to intercept the call. RESEARCH Pitfall 3 additionally flags **two string-form monkeypatch
targets** (`tests/test_webhook.py` ~lines 232-235, 301: `monkeypatch.setattr("app.main._resume_pipeline", ...)`)
that must retarget to `"app.routes.pipeline_glue.resume_pipeline"` (or whatever final public name
is chosen) — grep for the quoted-string form separately from attribute-form patches.

---

### `app/routes/templating.py` (config/provider, singleton)

**Analog:** `app/main.py` lines 180-236 (Jinja2Templates instance + badge filters, in place).

**Core pattern** (verbatim move, RESEARCH Pattern 3 code example):
```python
# app/routes/templating.py
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")

def _badge_class_filter(status: str) -> str: ...
def _badge_label_filter(status: str) -> str: ...

templates.env.filters["badge_class"] = _badge_class_filter
templates.env.filters["badge_label"] = _badge_label_filter
```
`_BADGE_CLASS`/`_BADGE_LABEL` dicts (lines 193-222) move here too, verbatim. `_build_alias_rationale_notes`
(lines 1090-1137) does **not** belong here — per D-08 it lands in `routes/runs.py` beside its only
caller, not in `templating.py`.

---

### `app/routes/__init__.py`, `app/main.py` (thin, post-split)

**Analog:** `app/pipeline/__init__.py` (6-line package docstring, minimal) for the `__init__.py`
style; `app/db/bootstrap.py`'s docstring economy (short "what this file does" + no inline essay)
as the tone target for the ~100-line thin `main.py`.

**`app/pipeline/__init__.py` full content** (the entire file — this is the target length/tone for
`app/routes/__init__.py`):
```python
"""Pipeline package — the pure judgment stages + orchestrator (Plans 02/03/04).

Plan 01 only creates the package so later waves import a stable seam; the stage
modules (extract/reconcile_names/validate/decide/calculate/compose_email) and the
orchestrator land in subsequent plans.
"""
```
`app/db/__init__.py` is empty (0 lines) — either an empty or a one-line docstring `__init__.py` is
consistent with existing convention; prefer the `pipeline/__init__.py` one-paragraph style since
`app/routes/` is a brand-new package that benefits from a pointer to its contents.

**Thin `main.py` target shape** (RESEARCH Pattern 3 + System Architecture Diagram, ~100 lines):
```python
"""FastAPI entrypoint — app assembly only. Routes live in app/routes/*."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import webhook, runs, dashboard, demo, health

app = FastAPI(title="Payroll Agent")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(health.router)
app.include_router(webhook.router)
app.include_router(runs.router)
app.include_router(dashboard.router)
app.include_router(demo.router)
```

---

### `app/db/repo/__init__.py` (provider, package facade)

**Analog:** No direct precedent exists in this codebase (no package currently re-exports another
module's full public surface) — RESEARCH.md's "Pattern 1: Package-facade split" code example is
the authoritative source, cross-checked against `app/db/repo.py`'s own docstring style (lines 1-89)
for the facade docstring's tone.

**Facade docstring + re-export pattern** (RESEARCH Pattern 1, verbatim code example — planner fills
in the exact symbol list from the D-02 function inventory):
```python
"""DB repo package facade — re-exports the full public API so existing callers
(`from app.db import repo`, `import app.db.repo as repo_mod`) and test monkeypatch
seams (`monkeypatch.setattr(repo, "fn", ...)`) keep working unchanged post-split."""
from app.db.repo.runs import (
    insert_inbound_email, find_business_by_sender, create_run, load_run,
    set_status, claim_status, sweep_stranded_runs, record_run_error,
    _scrub,   # RESEARCH Pitfall 2: tests/test_persistence.py reaches repo._scrub directly
)
from app.db.repo.pipeline_state import (
    persist_extracted, persist_decision, persist_reconciliation,
    replace_line_items, set_alias_candidates, clear_reply_context,  # ... full D-02 list
)
from app.db.repo.emails import (
    insert_email_message, get_outbound_message_id, mark_reply_consumed,  # ... full D-02 list
)
from app.db.repo.roster import load_roster_for_business
from app.db.repo.demo import list_businesses, bind_demo_business, get_demo_binding
```

**Critical constraint (RESEARCH Anti-Pattern + Pitfall 2):** re-export **`_scrub`** alongside the
public API — `tests/test_persistence.py` does `monkeypatch.setattr(repo, "_scrub", _boom)` and
`repo._scrub(message, roster=roster)` directly against `from app.db import repo`; omitting it from
the facade breaks that pre-existing, in-scope test (STRUCT-04 violation). Do NOT let any repo
submodule import a sibling's function **through this facade** (`from app.db import repo` inside
`runs.py` to reach `demo.get_record_only_flag`) — that is a circular import at package-init time;
submodules must import siblings directly (`from app.db.repo import demo as repo_demo`).

---

### `app/db/repo/_shared.py` (utility, internal plumbing)

**Analog:** `app/db/repo.py` lines 156-164 (`_conn_ctx`) and 1731-1734 (`_nulltx`), in place.

**Core pattern** (verbatim move — both context managers, unchanged):
```python
@contextlib.contextmanager
def _conn_ctx(conn):
    """Yield (conn, owns): use the caller's conn, or open a pooled one we own."""
    if conn is not None:
        yield conn, False
    else:
        with get_connection() as owned:
            yield owned, True


@contextlib.contextmanager
def _nulltx():
    """No-op CM: when a caller passes their own conn, they own the transaction."""
    yield
```
Every aggregate submodule (`runs.py`, `pipeline_state.py`, `emails.py`, `roster.py`, `demo.py`)
imports these via `from app.db.repo._shared import _conn_ctx, _nulltx` — a direct sibling import,
not through the package `__init__`.

---

### `app/db/repo/runs.py`, `pipeline_state.py`, `emails.py`, `roster.py`, `demo.py` (model/service, CRUD)

**Analog:** `app/db/repo.py` itself — each aggregate is a verbatim slice at the D-02/RESEARCH-cited
line ranges (see 13-RESEARCH.md's "Full function → aggregate mapping" section for the authoritative
per-function list; not repeated here to avoid drift between two documents).

**Imports pattern common to every aggregate module** (`app/db/repo.py` lines 90-105 — trim per
aggregate's actual needs):
```python
from __future__ import annotations

import contextlib
import json
import logging
import re
import unicodedata
import uuid
from typing import Any

import psycopg.rows

from app.db.repo._shared import _conn_ctx, _nulltx
from app.db.supabase import get_connection
from app.models.contracts import ClarifiedFields, Decision, Extracted, PaystubLineItem
from app.models.roster import Employee, NameMatchResult, Roster
from app.models.status import RunStatus

logger = logging.getLogger("payroll_agent.repo")
```

**Core CRUD pattern — the `_conn_ctx`/optional-transaction idiom** (`app/db/repo.py` lines 428-441,
`set_status`, → `repo/runs.py` verbatim; every write function in every aggregate follows this exact
shape):
```python
def set_status(run_id: uuid.UUID, status: RunStatus, conn=None) -> None:
    """Unguarded status writer — one of two writers on payroll_runs.status (D-12). ..."""
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE payroll_runs SET status = %s, updated_at = now() WHERE id = %s",
            (RunStatus(status).value, str(run_id)),
        )
```

**Atomic CAS pattern** (`app/db/repo.py` lines 444-468, `claim_status`, → `repo/runs.py` verbatim —
the load-bearing idiom behind every HITL gate; same-aggregate callers `record_run_error`/
`set_clarification_round`/`set_pre_clarify_extracted` call `set_status` directly, same-module, no
cross-import needed post-split):
```python
def claim_status(run_id: uuid.UUID, expected: RunStatus, new: RunStatus, conn=None) -> bool:
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute(
            "UPDATE payroll_runs SET status = %s, updated_at = now() "
            "WHERE id = %s AND status = %s RETURNING id",
            (RunStatus(new).value, str(run_id), RunStatus(expected).value),
        ).fetchone()
    return row is not None
```

**Read pattern — explicit columns + dict_row** (`app/db/repo.py` lines 1712-1723, `load_roster_for_business`,
→ `repo/roster.py` verbatim — the "no `SELECT *`" discipline stated in the module docstring, lines
82-83, applies identically to every read function moved into any aggregate):
```python
def load_roster_for_business(business_id: uuid.UUID, conn=None) -> Roster:
    """Rebuild a typed Roster (explicit EMPLOYEE_COLS + dict_row, no SELECT *)."""
    sql = "SELECT " + EMPLOYEE_COLS + " FROM employees WHERE business_id = %s"
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, (str(business_id),))
        rows = cur.fetchall()
    return Roster(business_id=business_id, employees=[Employee(**row) for row in rows])
```
`EMPLOYEE_COLS` (module constant, `app/db/repo.py` lines 109-115) moves with `load_roster_for_business`
into `repo/roster.py`. `RUN_COLS` (lines 117-136) and `_TERMINAL_STATUSES` (lines 138-153) move into
`repo/runs.py` alongside `load_run`/`record_run_error`.

**Upsert pattern** (`app/db/repo.py` lines 1466-1500, `bind_demo_business`, → `repo/demo.py` verbatim
— demonstrates `ON CONFLICT ... DO UPDATE`):
```python
def bind_demo_business(business_name: str, operator_email: str, seed_business_ids: dict, conn=None) -> bool:
    business_id = seed_business_ids.get(business_name)
    if business_id is None:
        return False
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            """
                INSERT INTO demo_sender_bindings (operator_email, business_id, bound_at)
                VALUES (%s, %s, now())
                ON CONFLICT (operator_email) DO UPDATE
                    SET business_id = EXCLUDED.business_id, bound_at = now()
                """,
            (operator_email, str(business_id)),
        )
    return True
```

**Cross-aggregate call requiring a direct sibling import** (D-03/RESEARCH-confirmed the ONE such
edge): `create_run` (→ `repo/runs.py`) calls `get_record_only_flag` (→ `repo/demo.py`):
```python
# app/db/repo/runs.py
from app.db.repo import demo as repo_demo   # direct sibling import, NOT through __init__ facade
...
def create_run(..., conn=None) -> ...:
    ...
    if repo_demo.get_record_only_flag(...):
        ...
```

**Section-banner style** (`app/db/repo.py` lines 166-168, 523, 1057-1059, 1450-1452, 1652-1654,
1726-1728 — carry the banner text into each new module's own header, scoped to that module's
concern only):
```python
# ---------------------------------------------------------------------------
# Ingest / run lifecycle
# ---------------------------------------------------------------------------
```

**Docstring deletion (D-04):** the 76-line function-index docstring at the top of `app/db/repo.py`
(lines 1-89) is deleted at split time — do not carry it into any of the five new modules. Each new
module gets a **one-line placeholder docstring** only, e.g.:
```python
"""DB repo — run lifecycle, status CAS, sweep, and error/scrub helpers."""
```
Phase 15 (COMM-02) writes the real module-purpose statement later; do not attempt to write a
comprehensive docstring now (out of scope, "no refactoring/documenting while moving").

---

### `app/pipeline/alias_learning.py` (service, transform + CRUD-via-repo)

**Analog:** `app/pipeline/orchestrator.py` lines 80-157 (`_normalize_candidate`,
`_bind_evidence_for_token`) + 1503-1590 (`_write_aliases_if_safe`), PLUS `app/pipeline/reconcile_names.py`
lines 167-203 (`_safe_to_learn_alias`, relocating in per D-10).

**Imports pattern for the new module** (assembled from orchestrator's existing imports, trimmed to
what alias_learning actually needs, plus the relocated helper's own needs):
```python
from __future__ import annotations

import logging
import uuid

from app.db import repo
from app.pipeline.reconcile_names import normalize_name  # was: _norm, promoted D-13

logger = logging.getLogger("payroll_agent.orchestrator")  # or a new "payroll_agent.alias_learning" logger — planner's call, but keep ONE logger name per module
```

**Core pattern — the collision-guard + idempotent-write cycle** (`app/pipeline/orchestrator.py`
lines 1503-1590, `_write_aliases_if_safe` → `alias_learning.write_aliases_if_safe`, BOUND-01 rename
per D-12; body moves verbatim except the internal calls become same-module references since
`_safe_to_learn_alias`/`_normalize_candidate` now live in this same file):
```python
def write_aliases_if_safe(run_id: uuid.UUID, run: dict, roster, conn=None) -> None:
    """Write any unambiguous, non-colliding alias candidates to employees.known_aliases.
    Called in delivery.deliver BEFORE set_status(SENT) ... Must be wrapped in try/except
    at the call site: any internal exception is logged and swallowed ..."""
    import uuid as _uuid
    run_data = repo.load_run(run_id, conn=conn)
    ...
    for token, value in alias_candidates.items():
        cand = normalize_candidate(value)          # same-module call, was _normalize_candidate
        ...
        if not safe_to_learn_alias(token, target_employee, current_roster):  # relocated in from reconcile_names
            ...
        written = repo.update_known_alias(employee_id, token, conn=conn)
```

**Relocated collision-guard function** (`app/pipeline/reconcile_names.py` lines 167-202,
`_safe_to_learn_alias` → `alias_learning.safe_to_learn_alias`, moves file per D-10, renamed per
D-12 in the same commit; imports `reconcile_names.deterministic_match` cross-module — this is a
NEW, intentional cross-module public reference, not a violation, since `deterministic_match` is
already public):
```python
def safe_to_learn_alias(token: str, target_employee: Employee, roster: Roster) -> bool:
    """Return True only if token uniquely resolves to target_employee on the full roster
    AFTER the alias is appended (D-01b write-side collision guard). ..."""
    from app.pipeline.reconcile_names import deterministic_match
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

**Call-graph edges requiring module-object imports back into `orchestrator.py`** (D-11, RESEARCH
"Full function → concern mapping"): `resume_pipeline` (stays in `orchestrator.py`) calls
`_normalize_candidate`/`_bind_evidence_for_token` at ~lines 872/903 — post-split these become:
```python
# app/pipeline/orchestrator.py
from app.pipeline import alias_learning
...
    cand = alias_learning.normalize_candidate(value)
    bound = alias_learning.bind_evidence_for_token(token, suggested_id, suggested_full_name, post_reconciliation)
```
And `delivery.deliver` (moving to `delivery.py`) calls `write_aliases_if_safe` at ~lines 1655/1778:
```python
# app/pipeline/delivery.py
from app.pipeline import alias_learning
...
    alias_learning.write_aliases_if_safe(run_id, run, existing_roster)
```

---

### `app/pipeline/clarification.py` (service, event-driven compose+send)

**Analog:** `app/pipeline/orchestrator.py` lines 937-1088 (`_defer_field_regression_clarification`,
`_render_asked_summary`, `_combined_context_email`) + 1229-1500 (`_clarify`), in place.

**Core pattern — deferred-clarification write-then-send** (`app/pipeline/orchestrator.py` lines
937-1024, `_defer_field_regression_clarification`, verbatim move except the internal `_clarify`
call becomes a same-module reference):
```python
def _defer_field_regression_clarification(
    run_id, clarified: dict, stage: _RunStagesResult, combined_email: InboundEmail, roster, *, llm,
) -> None:
    """Shared helper for deferred field-regression clarification (IN-01, CR-02 fix). ..."""
    post_run = repo.load_run(run_id)
    ...
    with repo.get_connection() as conn, conn.transaction():
        repo.set_clarified_fields(run_id, clarified, conn=conn)
    ...
    if persisted_decision is not None and persisted_extracted is not None:
        _clarify(   # same-module call post-split, no cross-import needed
            run_id, combined_email, persisted_decision, roster, persisted_extracted,
            llm=llm, purpose="clarification_field_regression",
        )
```

**Pure-transform pattern (no I/O)** (`app/pipeline/orchestrator.py` lines 1027-1052,
`_render_asked_summary`, verbatim — a model for how the clarification module's pure helpers should
read: typed in, typed out, no DB/no LLM):
```python
def _render_asked_summary(decision, clarified_fields: dict) -> list[str]:
    """Render the code-owned "what we asked" lines from PERSISTED decision facts only ..."""
    lines: list[str] = []
    unresolved_names = list(getattr(decision, "unresolved_names", None) or [])
    for name in unresolved_names:
        lines.append(f"{name}: name could not be matched to a roster employee")
    for emp_id_str, field_outcomes in (clarified_fields or {}).items():
        ...
    return lines
```

**`_clarify`'s call site in `orchestrator.py` post-split** (module-object import, D-11):
```python
# app/pipeline/orchestrator.py
from app.pipeline import clarification
...
    clarification.clarify(run_id, email, decision, roster, extracted, llm=llm, purpose="clarification")
```
(Rename `_clarify` → `clarify` is Claude's Discretion per D-13's "drop-underscore is the default"
— not explicitly listed in D-12's examples but consistent with the same rule; the planner should
apply it since `clarification.clarify` reads naturally at the call site, mirroring `delivery.deliver`.)

---

### `app/pipeline/delivery.py` (service, event-driven compose+send+PDF)

**Analog:** `app/pipeline/orchestrator.py` lines 1592-1800 (`_deliver`), in place.

**Core pattern — idempotency guard + multi-step compose/send** (verbatim move, rename `_deliver` →
`deliver` per D-12):
```python
def deliver(run_id: uuid.UUID, run: dict) -> None:
    """Compose + send the confirmation email + per-employee PDFs.
    Called synchronously by the approve route. Raises freely — the caller (approve
    handler) wraps this in the D-13b error boundary ..."""
    run = dict(run)  # shallow copy — do not mutate the caller's dict
    biz_name = repo.load_business_name(run["business_id"])
    ...
    existing = repo.get_outbound_message_id(run_id, purpose="confirmation")
    if existing is not None:
        ...
        existing_roster = repo.load_roster_for_business(run["business_id"])
        try:
            alias_learning.write_aliases_if_safe(run_id, run, existing_roster)  # was: _write_aliases_if_safe(...)
        except Exception as alias_exc:  # noqa: BLE001 — D-13b defensive isolation
            logger.warning("alias write skipped for run %s: %s (run continues to SENT)", run_id, type(alias_exc).__name__)
        with repo.get_connection() as conn, conn.transaction():
            repo.set_status(run_id, RunStatus.SENT, conn=conn)
            repo.set_status(run_id, RunStatus.RECONCILED, conn=conn)
        return
    ...
```
`from app.pipeline import alias_learning` at module top (D-11 module-object import).

**Caller-side retarget** (D-07's integration point, `app/main.py:784` → `routes/runs.py`'s
`approve()`, already shown above under routes/runs.py — repeated here for the delivery-module side
of the same seam):
```python
# app/routes/runs.py
from app.pipeline import delivery
...
    delivery.deliver(run_id, run)   # replaces: from app.pipeline.orchestrator import _deliver; _deliver(run_id, run)
```

---

### `app/pipeline/orchestrator.py` (trimmed core, stays ~800-900 lines)

**Analog:** itself, before the split — no change to what stays; only its imports change to add the
three new sibling-module imports and drop the now-relocated symbols.

**New imports needed post-split** (append to the existing import block, `app/pipeline/orchestrator.py`
lines 45-62):
```python
from app.pipeline import alias_learning, clarification, delivery
```
**Imports to remove** from the current block: `from app.pipeline.reconcile_names import
_safe_to_learn_alias, reconcile_names` → becomes `from app.pipeline.reconcile_names import
reconcile_names` only (`_safe_to_learn_alias` relocates to `alias_learning.py`, not imported by
orchestrator anymore). `from app.pipeline.validate import _HOURS_FIELDS, _is_paid,
detect_field_regression, validate` → becomes `from app.pipeline.validate import HOURS_FIELDS,
is_paid, detect_field_regression, validate` (BOUND-01 rename, same commit as the rename in
`validate.py`).

---

### BOUND-01 promotions — `app/pipeline/reconcile_names.py`, `app/pipeline/validate.py`

**Analog:** the files themselves; this is a rename-in-place, not a move.

**`reconcile_names.py` line 39** (`app/pipeline/reconcile_names.py`, verbatim body, name only
changes):
```python
def normalize_name(name: str) -> str:   # was: def _norm(name: str) -> str:
    """Whitespace-normalize + NFC(casefold(s)) for deterministic Unicode-safe comparison (D-05). ..."""
    return " ".join(unicodedata.normalize("NFC", name.casefold()).split())
```
Every same-module call site inside `reconcile_names.py` (`deterministic_match`'s two `_norm(...)`
calls) updates to `normalize_name(...)` in the same commit. `eval/run_eval.py:39`'s import
retargets to `from app.pipeline.reconcile_names import normalize_name` (drop the `as _normalize`
alias or keep it as a local alias — `import x as _x` local aliases of public names are explicitly
NOT a BOUND-01 violation per D-14).

**`validate.py` lines 30-46** (`app/pipeline/validate.py`, verbatim bodies, names only change):
```python
HOURS_FIELDS = (          # was: _HOURS_FIELDS = (
    "hours_regular", "hours_overtime", "hours_vacation", "hours_sick", "hours_holiday",
)


def is_paid(v: Decimal | None) -> bool:   # was: def _is_paid(v: Decimal | None) -> bool:
    """True iff value is present AND strictly positive (D-09 shared predicate). ..."""
    return v is not None and v > 0
```
**Explicit non-scope (RESEARCH Pitfall 5):** `app/pipeline/calculate.py`'s own, textually-identical
`_HOURS_FIELDS` tuple is a **different symbol**, same-module-only, NOT cross-module referenced —
do NOT touch it, do NOT de-duplicate it against `validate.HOURS_FIELDS`. Any diff touching
`calculate.py` during this promotion is out of scope.

---

### `tests/test_bound01_private_imports.py` (test, static-analysis guard)

**Source:** RESEARCH.md's "AST-based BOUND-01 guard (D-15 recommended implementation)" — a
complete, ready-to-adapt code example (reproduced there in full: `ast.walk`-based, scans
`app/`/`eval`/`scripts`, flags any `ast.ImportFrom` whose name starts with `_` and whose module
differs from the importing module, module-level AND function-body). No existing test in this
codebase performs AST-walking, so this is genuinely new test infrastructure — do not search for a
closer analog; use the RESEARCH example directly, keyed to this repo's actual `SCAN_ROOTS = ["app",
"eval", "scripts"]`. RESEARCH's Sources section confirms this was validated live against
`ruff check --select PLC2701 --preview` and found to be the ONLY mechanism that catches this
codebase's actual violation shapes (same-package exemption + function-body blindness both apply to
`ruff`'s own candidate rule).

**Validation order (RESEARCH Wave 0 Gaps):** write and run this test against the PRE-split code
first to confirm it finds all 7 known D-14 violations (manual/interactive check, not committed as a
red test), THEN apply the BOUND-01 renames/relocations, THEN confirm it passes clean — this proves
the guard's detection logic against real positives before trusting it as a permanent CI gate.

---

## Shared Patterns

### `_conn_ctx` / `_nulltx` optional-transaction idiom
**Source:** `app/db/repo.py` lines 156-164, 1731-1734 → moves to `app/db/repo/_shared.py`
**Apply to:** every write/read function in all five `app/db/repo/*.py` aggregate modules
```python
with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
    c.execute(...)
```
This is the single most repeated pattern in the entire repo split — every one of the ~55 moved
functions uses it verbatim.

### Module-object import discipline (D-11)
**Source:** RESEARCH Pattern 2, applied throughout the orchestrator split and the routes split
**Apply to:** `app/pipeline/orchestrator.py` → `alias_learning`/`clarification`/`delivery`;
`app/routes/webhook.py`/`runs.py` → `pipeline_glue`; any repo submodule needing a sibling's public
helper
```python
from app.pipeline import delivery
...
    delivery.deliver(run_id, run)
```
Never `from app.pipeline.delivery import deliver` for any of these — the module-object form is
what keeps every `monkeypatch.setattr(<module>, "<fn>", ...)` test seam able to intercept the call
post-split.

### PII-safe error logging (D-A1-03)
**Source:** `app/main.py` lines 796-813 (`approve()`'s except block, in place), repeated at every
HITL route and at `_deliver`'s two exception-carrying paths
**Apply to:** every moved route in `routes/runs.py`, `routes/webhook.py`; `delivery.deliver`;
`alias_learning.write_aliases_if_safe`'s internal try/except
```python
except Exception as exc:  # noqa: BLE001 — <named boundary>
    logger.warning("... %s: %s", run_id, type(exc).__name__)   # type name ONLY, never str(exc)
```

### Explicit-column reads, never `SELECT *`
**Source:** `app/db/repo.py` module docstring lines 82-83 + `EMPLOYEE_COLS`/`RUN_COLS` constants
(lines 109-136)
**Apply to:** every read function across all five `repo/*.py` aggregates — constants move with
their primary consumer function, are never re-declared in a second module

### Section-banner headers
**Source:** `app/db/repo.py`'s seven `# ---` banners, `app/main.py`'s per-route-cluster banners
**Apply to:** every new module gets at least one top-of-file banner matching its scoped concern
(scaled down from the god-file's banner text, not copied wholesale)

## No Analog Found

None. Every file in this phase's scope is a slice of one of the three known god-files, or (for the
package-facade `__init__.py` and the AST-walking guard test) is fully specified by RESEARCH.md's
own code examples rather than needing a codebase precedent.

## Metadata

**Analog search scope:** `app/main.py`, `app/db/repo.py`, `app/pipeline/orchestrator.py` (the three
files being split — read via targeted offset/limit reads across this session, no re-reads of
already-loaded ranges), `app/pipeline/reconcile_names.py` (full read), `app/pipeline/validate.py`
(targeted read, lines 1-50), `app/pipeline/__init__.py` / `app/db/__init__.py` (full read, both
trivial), `app/db/bootstrap.py` (full read, docstring/structure analog for thin `main.py`),
`app/email/clean.py` (targeted read, docstring-style analog), plus `grep` over `app/main.py` and
`app/db/repo.py` for every `def`/route decorator/section-banner line to confirm RESEARCH.md's line
numbers still hold at pattern-mapping time.
**Files scanned:** 10 read directly (3 god-files via targeted ranges + 7 small analog modules),
plus grep-based structural scans of the 3 god-files and `tests/` for monkeypatch-seam density.
**Pattern extraction date:** 2026-07-09
