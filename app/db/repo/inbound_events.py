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


def purge_terminal_inbound_events(
    *,
    older_than_days: int = 30,
    batch_size: int = 100,
    conn: psycopg.Connection | None = None,
) -> int:
    """Delete one bounded batch of old receipts whose ingest work is terminal.

    Open ``pending``/``leased`` work is excluded independently of the terminal
    predicate.  The named ``jobs.event_id`` foreign key uses ``ON DELETE SET
    NULL``, so deleting the payload envelope retains the terminal job audit.
    """
    if (
        isinstance(older_than_days, bool)
        or not isinstance(older_than_days, int)
        or older_than_days < 30
    ):
        raise ValueError("older_than_days must be an integer of at least 30")
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 1 <= batch_size <= 100
    ):
        raise ValueError("batch_size must be an integer from 1 to 100")

    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        deleted = c.execute(
            """
            WITH candidates AS (
                SELECT event.id
                  FROM inbound_events AS event
                 WHERE event.received_at <
                       now() - (%(older_than_days)s * interval '1 day')
                   AND EXISTS (
                       SELECT 1
                         FROM jobs AS j
                        WHERE j.event_id = event.id
                          AND j.kind = 'ingest'
                          AND j.state IN ('done', 'dead')
                   )
                   AND NOT EXISTS (
                       SELECT 1
                         FROM jobs AS open_job
                        WHERE open_job.event_id = event.id
                          AND open_job.kind = 'ingest'
                          AND open_job.state IN ('pending', 'leased')
                   )
                 ORDER BY event.received_at, event.id
                 LIMIT %(batch_size)s
                 FOR UPDATE OF event SKIP LOCKED
            )
            DELETE FROM inbound_events AS event
             USING candidates
             WHERE event.id = candidates.id
            RETURNING event.id
            """,
            {"older_than_days": older_than_days, "batch_size": batch_size},
        ).fetchall()
    return len(deleted)
