"""Repository primitives for signature-verified durable inbound receipts.

The receipt is transport state only.  It contains the bounded webhook envelope
needed for the delayed provider fetch; fetched bodies and payroll decisions are
persisted in their existing domain tables, never here or on ``jobs``.
"""
from __future__ import annotations

import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.db.repo._shared import _conn_ctx, _nulltx


def insert_or_get_inbound_event(
    *,
    external_event_id: str,
    payload: dict[str, Any],
    conn: psycopg.Connection | None = None,
) -> tuple[uuid.UUID, bool]:
    """Insert one transport receipt or return the exact conflicting receipt.

    ``external_event_id`` is the authenticated Svix delivery identifier (or
    the stable digest produced by the explicitly enabled fixture route).  The
    duplicate loser performs an exact-key lookup inside the caller's
    transaction so every redelivery receives the original internal UUID.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute(
            """
            INSERT INTO inbound_events (external_event_id, payload)
            VALUES (%s, %s)
            ON CONFLICT (external_event_id) DO NOTHING
            RETURNING id
            """,
            (external_event_id, Jsonb(payload)),
        ).fetchone()
        if row is not None:
            return uuid.UUID(str(row[0])), True

        existing = c.execute(
            "SELECT id FROM inbound_events WHERE external_event_id = %s",
            (external_event_id,),
        ).fetchone()
        if existing is None:
            raise RuntimeError("inbound event conflict row unavailable")
        return uuid.UUID(str(existing[0])), False


def load_inbound_event(
    event_id: uuid.UUID,
    conn: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Load only the internal identifier and verified transport envelope."""
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT id, payload FROM inbound_events WHERE id = %s",
            (str(event_id),),
        ).fetchone()
    if row is None:
        return None
    payload = row[1]
    if not isinstance(payload, dict):
        raise RuntimeError("inbound event payload has invalid stored shape")
    return {"id": uuid.UUID(str(row[0])), "payload": payload}
