"""Immutable, commit-serialized operator-resolution persistence."""
from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from pydantic import ValidationError

from app.db.repo._shared import _conn_ctx, _nulltx
from app.models.contracts import Decision
from app.models.status import RunStatus


@dataclass(frozen=True, slots=True)
class OperatorResolutionSubmission:
    """PII-bounded authority classification for one immutable generation."""

    resolution_id: uuid.UUID
    authoritative: bool
    winner_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class _StoredGeneration:
    run_id: uuid.UUID
    authoritative: bool
    winner_id: uuid.UUID
    overrides: dict[str, str]
    remember: dict[str, bool]


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


def _normalize_remember(
    remember: Mapping[str, bool], names: set[str]
) -> dict[str, bool]:
    try:
        pairs = list(remember.items())
    except (AttributeError, TypeError) as exc:
        raise ValueError("remember must be a submitted-name mapping") from exc
    normalized: dict[str, bool] = {}
    for submitted_name, choice in pairs:
        if not isinstance(submitted_name, str) or not submitted_name.strip():
            raise ValueError("remember submitted_name must be a nonblank string")
        if submitted_name in normalized:
            raise ValueError("remember has duplicate submitted names")
        if not isinstance(choice, bool):
            raise ValueError("remember choices must be booleans")
        normalized[submitted_name] = choice
    if set(normalized) != names:
        raise ValueError("remember choices must exactly match the complete mapping")
    return normalized


def operator_resume_dedup_key(
    run_id: uuid.UUID, operator_resolution_id: uuid.UUID
) -> str:
    """Return the generation-specific queue deduplication key."""
    return (
        "operator_resume:"
        f"{_uuid_text(run_id, 'run_id')}:"
        f"{_uuid_text(operator_resolution_id, 'operator_resolution_id')}"
    )


def _load_generation_rows(
    conn: psycopg.Connection,
    operator_resolution_id: str,
) -> list[tuple[Any, Any, Any, Any, Any, Any]]:
    return conn.execute(
        """
        SELECT r.run_id, r.authoritative, r.superseded_by,
               o.submitted_name, o.employee_id, o.remember
          FROM operator_resume_resolutions r
          LEFT JOIN operator_resume_overrides o
            ON o.operator_resolution_id = r.id
         WHERE r.id = %s
         ORDER BY o.submitted_name
        """,
        (operator_resolution_id,),
    ).fetchall()


def _load_mapping_rows(
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


def _mapping_from_rows(
    rows: list[tuple[Any, Any, Any]], run_id: str
) -> dict[str, str]:
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


def _stored_generation(
    rows: list[tuple[Any, Any, Any, Any, Any, Any]],
    operator_resolution_id: str,
) -> _StoredGeneration:
    if not rows:
        raise ValueError("operator resume resolution is missing")

    run_ids: set[str] = set()
    authority_values: set[bool] = set()
    superseded_values: set[str | None] = set()
    overrides: dict[str, str] = {}
    remember: dict[str, bool] = {}
    for (
        stored_run_id,
        authoritative,
        superseded_by,
        submitted_name,
        employee_id,
        remember_choice,
    ) in rows:
        run_ids.add(_uuid_text(stored_run_id, "stored run_id"))
        if not isinstance(authoritative, bool):
            raise ValueError("operator resume resolution has invalid authority state")
        authority_values.add(authoritative)
        superseded_values.add(
            _uuid_text(superseded_by, "superseded_by")
            if superseded_by is not None
            else None
        )
        if not isinstance(submitted_name, str) or not submitted_name.strip():
            raise ValueError("operator resume resolution has missing or blank names")
        if submitted_name in overrides:
            raise ValueError("operator resume resolution has duplicate names")
        if not isinstance(remember_choice, bool):
            raise ValueError("operator resume resolution has invalid remember state")
        overrides[submitted_name] = _uuid_text(employee_id, "stored employee_id")
        remember[submitted_name] = remember_choice

    if len(run_ids) != 1 or len(authority_values) != 1 or len(superseded_values) != 1:
        raise ValueError("operator resume resolution has inconsistent parent state")
    authoritative = authority_values.pop()
    superseded_by = superseded_values.pop()
    if authoritative:
        if superseded_by is not None:
            raise ValueError("authoritative operator resolution cannot be superseded")
        winner_id = operator_resolution_id
    else:
        if superseded_by is None:
            raise ValueError("superseded operator resolution has no winner")
        if superseded_by == operator_resolution_id:
            raise ValueError("operator resolution cannot supersede itself")
        winner_id = superseded_by
    return _StoredGeneration(
        run_id=uuid.UUID(run_ids.pop()),
        authoritative=authoritative,
        winner_id=uuid.UUID(winner_id),
        overrides=overrides,
        remember=remember,
    )


def _submission(
    operator_resolution_id: str, generation: _StoredGeneration
) -> OperatorResolutionSubmission:
    return OperatorResolutionSubmission(
        resolution_id=uuid.UUID(operator_resolution_id),
        authoritative=generation.authoritative,
        winner_id=generation.winner_id,
    )


def _locked_run(
    conn: psycopg.Connection,
    run_id: str,
) -> tuple[uuid.UUID, uuid.UUID, str, Decision, dict[str, Any]]:
    row = conn.execute(
        """
        SELECT id, business_id, status, decision, alias_candidates
          FROM payroll_runs
         WHERE id = %s
         FOR UPDATE
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        raise ValueError("operator resolution run is missing")
    try:
        stored_run_id = uuid.UUID(_uuid_text(row[0], "stored run_id"))
        business_id = uuid.UUID(_uuid_text(row[1], "business_id"))
        status = str(row[2])
        decision = Decision.model_validate(row[3])
        alias_candidates = row[4] or {}
    except (IndexError, TypeError, ValueError, ValidationError) as exc:
        raise ValueError("operator resolution run context is invalid") from exc
    if str(stored_run_id) != run_id:
        raise ValueError("operator resolution run identity mismatch")
    if not isinstance(alias_candidates, dict):
        raise ValueError("operator resolution alias context is invalid")
    return stored_run_id, business_id, status, decision, alias_candidates


def _validate_generation_for_run(
    conn: psycopg.Connection,
    generation: _StoredGeneration,
    *,
    run_id: uuid.UUID,
    business_id: uuid.UUID,
    decision: Decision,
) -> None:
    unresolved = decision.unresolved_names
    if not unresolved or len(unresolved) != len(set(unresolved)):
        raise ValueError("operator resolution unresolved-name context is invalid")
    if generation.run_id != run_id:
        raise ValueError("operator resume resolution belongs to another run")
    if set(generation.overrides) != set(unresolved):
        raise ValueError("operator resume resolution is not a complete mapping")

    employee_ids = sorted(set(generation.overrides.values()))
    rows = conn.execute(
        """
        SELECT id
          FROM employees
         WHERE business_id = %s
           AND id = ANY(%s::uuid[])
        """,
        (str(business_id), employee_ids),
    ).fetchall()
    roster_ids = {_uuid_text(row[0], "roster employee_id") for row in rows}
    if roster_ids != set(employee_ids):
        raise ValueError("operator resume resolution crosses the run business roster")


def commit_operator_resume_resolution(
    run_id: uuid.UUID,
    operator_resolution_id: uuid.UUID,
    overrides: Mapping[str, uuid.UUID | str],
    remember: Mapping[str, bool],
    conn: psycopg.Connection | None = None,
) -> OperatorResolutionSubmission:
    """Commit a complete generation and classify first-commit authority under lock."""
    run_id_text = _uuid_text(run_id, "run_id")
    resolution_id_text = _uuid_text(
        operator_resolution_id, "operator_resolution_id"
    )
    normalized = _normalize_overrides(overrides)
    normalized_remember = _normalize_remember(remember, set(normalized))

    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        (
            stored_run_id,
            business_id,
            status,
            decision,
            _alias_candidates,
        ) = _locked_run(c, run_id_text)

        rows = _load_generation_rows(c, resolution_id_text)
        if rows:
            existing = _stored_generation(rows, resolution_id_text)
            if (
                existing.run_id != stored_run_id
                or existing.overrides != normalized
                or existing.remember != normalized_remember
            ):
                raise ValueError("conflicting operator resolution identifier")
            return _submission(resolution_id_text, existing)

        if status != RunStatus.NEEDS_OPERATOR.value:
            raise ValueError("operator resolution run is not awaiting an operator")
        candidate = _StoredGeneration(
            run_id=stored_run_id,
            authoritative=False,
            winner_id=uuid.UUID(resolution_id_text),
            overrides=normalized,
            remember=normalized_remember,
        )
        _validate_generation_for_run(
            c,
            candidate,
            run_id=stored_run_id,
            business_id=business_id,
            decision=decision,
        )

        winner_row = c.execute(
            """
            SELECT id
              FROM operator_resume_resolutions
             WHERE run_id = %s AND authoritative IS TRUE
            """,
            (run_id_text,),
        ).fetchone()
        if winner_row is None:
            authoritative = True
            winner_id_text = resolution_id_text
            superseded_by: str | None = None
        else:
            authoritative = False
            winner_id_text = _uuid_text(winner_row[0], "winner_id")
            superseded_by = winner_id_text

        inserted = c.execute(
            """
            INSERT INTO operator_resume_resolutions (
                id, run_id, authoritative, superseded_by
            ) VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (
                resolution_id_text,
                run_id_text,
                authoritative,
                superseded_by,
            ),
        ).fetchone()
        if inserted is None or _uuid_text(
            inserted[0], "inserted operator_resolution_id"
        ) != resolution_id_text:
            raise ValueError("inserted operator resolution identifier mismatch")
        for submitted_name, employee_id in sorted(normalized.items()):
            c.execute(
                """
                INSERT INTO operator_resume_overrides (
                    operator_resolution_id, submitted_name, employee_id, remember
                ) VALUES (%s, %s, %s, %s)
                """,
                (
                    resolution_id_text,
                    submitted_name,
                    employee_id,
                    normalized_remember[submitted_name],
                ),
            )
        return OperatorResolutionSubmission(
            resolution_id=uuid.UUID(resolution_id_text),
            authoritative=authoritative,
            winner_id=uuid.UUID(winner_id_text),
        )


def prepare_authoritative_operator_resume(
    run_id: uuid.UUID,
    operator_resolution_id: uuid.UUID,
    conn: psycopg.Connection | None = None,
) -> OperatorResolutionSubmission:
    """Validate one generation and project remembered aliases only for its winner."""
    run_id_text = _uuid_text(run_id, "run_id")
    resolution_id_text = _uuid_text(
        operator_resolution_id, "operator_resolution_id"
    )
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        (
            stored_run_id,
            business_id,
            _status,
            decision,
            _alias_candidates,
        ) = _locked_run(c, run_id_text)
        generation = _stored_generation(
            _load_generation_rows(c, resolution_id_text), resolution_id_text
        )
        _validate_generation_for_run(
            c,
            generation,
            run_id=stored_run_id,
            business_id=business_id,
            decision=decision,
        )
        result = _submission(resolution_id_text, generation)
        if not result.authoritative:
            return result

        remembered = {
            submitted_name: {
                "suggested": employee_id,
                "bound": employee_id,
            }
            for submitted_name, employee_id in generation.overrides.items()
            if generation.remember[submitted_name]
        }
        if remembered:
            c.execute(
                """
                UPDATE payroll_runs
                   SET alias_candidates =
                       COALESCE(alias_candidates, '{}'::jsonb) || %s::jsonb,
                       updated_at = now()
                 WHERE id = %s
                """,
                (json.dumps(remembered), run_id_text),
            )
        return result


def create_operator_resume_resolution(
    run_id: uuid.UUID,
    operator_resolution_id: uuid.UUID,
    overrides: Mapping[str, uuid.UUID | str],
    conn: psycopg.Connection | None = None,
) -> None:
    """Create one legacy immutable generation, or accept an exact duplicate."""
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
                    _load_mapping_rows(c, run_id_text, resolution_id_text), run_id_text
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
            _load_mapping_rows(c, run_id_text, resolution_id_text), run_id_text
        )
