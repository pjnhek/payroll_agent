"""Immutable typed persistence for complete operator-resume mappings."""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

import psycopg

from app.db.repo._shared import _conn_ctx, _nulltx


def _uuid_text(value: object, field: str) -> str:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a UUID")
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc


def _normalize_overrides(overrides: Mapping[str, uuid.UUID | str]) -> dict[str, str]:
    try:
        pairs = list(overrides.items())
    except (AttributeError, TypeError) as exc:
        raise ValueError("overrides must be a submitted-name mapping") from exc
    if not pairs:
        raise ValueError("overrides must contain at least one submitted name")

    normalized: dict[str, str] = {}
    for submitted_name, employee_id in pairs:
        if not isinstance(submitted_name, str) or not submitted_name.strip():
            raise ValueError("submitted_name must be a nonblank string")
        if submitted_name in normalized:
            raise ValueError(f"duplicate submitted_name {submitted_name!r}")
        normalized[submitted_name] = _uuid_text(employee_id, "employee_id")
    return normalized


def _load_rows(
    conn: psycopg.Connection,
    run_id: str,
    operator_resolution_id: str,
) -> list[tuple[Any, Any, Any]]:
    return conn.execute(
        """
        SELECT r.run_id, o.submitted_name, o.employee_id
          FROM operator_resume_resolutions r
          LEFT JOIN operator_resume_overrides o
            ON o.operator_resolution_id = r.id
         WHERE r.run_id = %s AND r.id = %s
         ORDER BY o.submitted_name
        """,
        (run_id, operator_resolution_id),
    ).fetchall()


def _mapping_from_rows(rows: list[tuple[Any, Any, Any]], run_id: str) -> dict[str, str]:
    if not rows:
        raise ValueError("operator resume resolution is missing")

    result: dict[str, str] = {}
    for stored_run_id, submitted_name, employee_id in rows:
        if _uuid_text(stored_run_id, "stored run_id") != run_id:
            raise ValueError("operator resume resolution belongs to another run")
        if not isinstance(submitted_name, str) or not submitted_name.strip():
            raise ValueError("operator resume resolution has missing or blank names")
        if submitted_name in result:
            raise ValueError("operator resume resolution has duplicate names")
        result[submitted_name] = _uuid_text(employee_id, "stored employee_id")
    return result


def create_operator_resume_resolution(
    run_id: uuid.UUID,
    operator_resolution_id: uuid.UUID,
    overrides: Mapping[str, uuid.UUID | str],
    conn: psycopg.Connection | None = None,
) -> None:
    """Atomically create one immutable generation, or accept an exact duplicate."""
    run_id_text = _uuid_text(run_id, "run_id")
    resolution_id_text = _uuid_text(
        operator_resolution_id, "operator_resolution_id"
    )
    normalized = _normalize_overrides(overrides)

    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        inserted = c.execute(
            """
            INSERT INTO operator_resume_resolutions (id, run_id)
            VALUES (%s, %s)
            ON CONFLICT (id) DO NOTHING
            RETURNING id
            """,
            (resolution_id_text, run_id_text),
        ).fetchone()

        if inserted is None:
            try:
                existing = _mapping_from_rows(
                    _load_rows(c, run_id_text, resolution_id_text), run_id_text
                )
            except ValueError as exc:
                raise ValueError(
                    "conflicting operator resolution identifier or corrupt generation"
                ) from exc
            if existing != normalized:
                raise ValueError("conflicting operator resolution mapping")
            return

        if _uuid_text(inserted[0], "inserted operator_resolution_id") != resolution_id_text:
            raise ValueError("inserted operator resolution identifier mismatch")
        for submitted_name, employee_id in sorted(normalized.items()):
            c.execute(
                """
                INSERT INTO operator_resume_overrides (
                    operator_resolution_id, submitted_name, employee_id
                ) VALUES (%s, %s, %s)
                """,
                (resolution_id_text, submitted_name, employee_id),
            )


def load_operator_resume_resolution(
    run_id: uuid.UUID,
    operator_resolution_id: uuid.UUID,
    conn: psycopg.Connection | None = None,
) -> dict[str, str]:
    """Load and validate the exact mapping for one run/resolution pair."""
    run_id_text = _uuid_text(run_id, "run_id")
    resolution_id_text = _uuid_text(
        operator_resolution_id, "operator_resolution_id"
    )
    with _conn_ctx(conn) as (c, _owns):
        return _mapping_from_rows(
            _load_rows(c, run_id_text, resolution_id_text), run_id_text
        )
