"""GET /health/live, /health/ready, /health/schema — health probes (D-05, D-20).

Carved out of app/main.py (Phase 13 Plan 03).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.db.schema_introspect import diff_against_live
from app.db.supabase import get_connection

logger = logging.getLogger("payroll_agent.webhook")

router = APIRouter()


@router.get("/health/live")
def health_live() -> JSONResponse:
    """Liveness probe — no DB hit. Render deploy healthCheckPath target (D-20).

    T-06-02-01: Returns {"status": "ok"} only — no version, no stack, no DB state.
    A Supabase blip during deploy must NOT fail this check (that is why no DB is
    touched here). render.yaml points healthCheckPath at this route.
    """
    return JSONResponse({"status": "ok"})


@router.get("/health/ready")
def health_ready() -> JSONResponse:
    """Readiness probe — runs a real SELECT. GitHub Actions keep-alive target (D-16/D-20).

    Touches a real table (businesses) so Supabase free project registers DB activity
    and does not pause (D-16 / RESEARCH Pitfall 5 / Assumption A7).
    A bare SELECT 1 without a real table may not count as 'use' in Supabase's pause
    detection. On DB failure raises 503 — correct for a failed readiness probe.

    T-06-02-02: On failure raises 503 with "database not ready" only — no connection
    string or stack trace in the response body.
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
    Phase-11 unique constraint) vs what schema.sql declares.

    200 {"status":"in_sync"}                       — live DB matches schema.sql
    503 {"status":"drift","missing":{...}}         — declared-but-missing on live
    503 {"detail":"schema check unavailable"}      — DB unreachable / parse error

    Body carries only schema identifier NAMES (no row data, no connection string,
    no stack trace) — same PII rule as /health/ready (T-06-02).
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
