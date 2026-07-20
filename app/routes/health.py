"""GET /health/live, /health/ready, /health/schema, /health/queue — health probes."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.db import repo
from app.db.schema_introspect import diff_against_live
from app.db.supabase import get_connection

logger = logging.getLogger("payroll_agent.webhook")

router = APIRouter()


@router.get("/health/live")
def health_live() -> JSONResponse:
    """Liveness probe — no DB hit. The Render deploy healthCheckPath target.

    Returns {"status": "ok"} only — no version, no stack, no DB state. A Supabase
    blip during deploy must NOT fail this check, which is why no DB is touched
    here: a DB-dependent liveness probe would roll back an otherwise healthy
    deploy. render.yaml points healthCheckPath at this route.
    """
    return JSONResponse({"status": "ok"})


@router.get("/health/ready")
def health_ready() -> JSONResponse:
    """Readiness probe — runs a real SELECT. The GitHub Actions keep-alive target.

    Touches a real table (businesses) so the Supabase free project registers DB
    activity and does not pause. A bare `SELECT 1` against no table may not count
    as 'use' in Supabase's pause detection — keep the table reference.
    On DB failure raises 503 — correct for a failed readiness probe.

    The 503 body carries "database not ready" only — never the connection string
    or a stack trace, which would leak DB host/credential shape to any caller.
    """
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1 FROM businesses LIMIT 1")
        return JSONResponse({"status": "ready"})
    except Exception as exc:
        logger.error("readiness probe failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="database not ready") from exc


@router.get("/health/schema")
def health_schema() -> JSONResponse:
    """Live schema-parity probe (columns + status/purpose CHECK values + the
    clarification-round unique constraint) vs what schema.sql declares.

    200 {"status":"in_sync"}                       — live DB matches schema.sql
    503 {"status":"drift","missing":{...}}         — declared-but-missing on live
    503 {"detail":"schema check unavailable"}      — DB unreachable / parse error

    The body carries only schema identifier NAMES — no row data, no connection
    string, no stack trace. Same disclosure rule as /health/ready.
    """
    try:
        with get_connection() as conn:
            diff = diff_against_live(conn)
    except Exception as exc:  # noqa: BLE001 — probe must not leak internals
        logger.error("schema parity probe failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="schema check unavailable") from exc
    if diff.is_in_sync:
        return JSONResponse({"status": "in_sync"})
    return JSONResponse(
        {"status": "drift", "missing": diff.as_missing_dict()},
        status_code=503,
    )


@router.get("/health/queue")
def health_queue() -> JSONResponse:
    """The swallowing-bug alarm, as a cron-checkable endpoint.

    200 {"status":"ok"}                       — no unaccounted error runs
    503 {"status":"unaccounted_errors","count":N} — N runs in `error` with no
                                                     corresponding terminal/dead
                                                     job settlement
    503 {"detail":"queue check unavailable"}  — DB unreachable / query error

    A new route rather than extending `/health/ready` or `/health/schema`:
    `pump.yml` already depends on those two carrying distinct, non-overlapping
    meanings (DB-reachable vs. schema-in-sync). Folding a third condition into
    either would make one red signal ambiguous about which of two unrelated
    problems fired. A fourth, independent probe keeps each `curl -f` step
    diagnostic on its own.

    This endpoint adds no logic of its own — it surfaces
    `repo.list_unaccounted_error_runs` (a run in `error` that no job's
    terminal/dead settlement accounts for, correlated by transaction-timestamp
    EQUALITY, never `>=`) wholesale, and inherits that predicate's correctness
    entirely.

    Disclosure discipline, matching the sibling probes: the body carries a
    `status` and, in the firing case, a bare `count` — never a run id, an
    `error_reason`, an `error_detail`, a connection string, or a stack trace.
    This route is unauthenticated like every other health probe, so its body
    is public; an operator gets the actionable, linked list from `/ops`.

    The alarm is purely derived: there is no acknowledge action, no mute
    state, and no time-boxed auto-clear — this endpoint returns to 200 on its
    own once every unaccounted error run is retriggered or settled. A
    lookback window was considered and rejected: a window is a time-boxed
    auto-clear by another name.
    """
    try:
        rows = repo.list_unaccounted_error_runs()
    except Exception as exc:  # noqa: BLE001 — probe must not leak internals
        logger.error("queue alarm probe failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="queue check unavailable") from exc
    if not rows:
        return JSONResponse({"status": "ok"})
    return JSONResponse(
        {"status": "unaccounted_errors", "count": len(rows)},
        status_code=503,
    )
