"""Fail-closed deployment controls for legacy operator-resolution authority."""
from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from contextlib import nullcontext
from typing import Any, NoReturn

import psycopg

from app.config import get_settings
from app.db.schema_introspect import diff_against_live

_POSTFLIGHT_FIELDS = (
    "affected_run_count",
    "ambiguous_run_count",
    "winnerless_run_count",
    "multiple_winner_run_count",
    "unclassified_generation_count",
)

_INVENTORY_SQL = """
WITH unresolved AS (
    SELECT pr.id AS run_id, COUNT(r.id)::bigint AS generation_count
      FROM payroll_runs pr
      LEFT JOIN operator_resume_resolutions r ON r.run_id = pr.id
     WHERE pr.status = 'needs_operator'
     GROUP BY pr.id
)
SELECT COUNT(*)::bigint,
       COUNT(*) FILTER (WHERE generation_count = 1)::bigint,
       COUNT(*) FILTER (WHERE generation_count > 1)::bigint
  FROM unresolved
"""

_POSTFLIGHT_SQL = """
WITH per_run AS (
    SELECT pr.id AS run_id,
           COUNT(r.id)::bigint AS generation_count,
           COUNT(r.id) FILTER (WHERE r.authoritative)::bigint AS winner_count,
           COUNT(r.id) FILTER (
               WHERE NOT r.authoritative AND r.superseded_by IS NULL
           )::bigint AS unclassified_count
      FROM payroll_runs pr
      LEFT JOIN operator_resume_resolutions r ON r.run_id = pr.id
     WHERE pr.status = 'needs_operator'
     GROUP BY pr.id
), affected AS (
    SELECT * FROM per_run WHERE generation_count > 0
)
SELECT COUNT(*)::bigint,
       COUNT(*) FILTER (WHERE generation_count > 1)::bigint,
       COUNT(*) FILTER (WHERE winner_count = 0)::bigint,
       COUNT(*) FILTER (WHERE winner_count > 1)::bigint,
       COALESCE(SUM(unclassified_count), 0)::bigint
  FROM affected
"""

_FENCE_STATE_SQL = """
SELECT f.writes_open,
       t.tgenabled,
       (t.tgtype & 2) <> 0 AS is_before,
       (t.tgtype & 4) <> 0 AS fires_on_insert
  FROM operator_resolution_writer_fence f
  JOIN pg_trigger t
    ON t.tgrelid = 'operator_resume_resolutions'::regclass
   AND t.tgname = 'trg_operator_resolution_writer_fence'
   AND NOT t.tgisinternal
  JOIN pg_proc p
    ON p.oid = t.tgfoid
   AND p.proname = 'enforce_operator_resolution_writer_fence'
 WHERE f.singleton IS TRUE
"""

_FENCE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION enforce_operator_resolution_writer_fence()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM operator_resolution_writer_fence
         WHERE singleton IS TRUE AND writes_open IS TRUE
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'operator resolution writes are fenced';
    END IF;
    RETURN NEW;
END;
$$
"""

_FENCE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS operator_resolution_writer_fence (
    singleton   BOOLEAN     NOT NULL DEFAULT TRUE,
    writes_open BOOLEAN     NOT NULL DEFAULT TRUE,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT operator_resolution_writer_fence_pkey PRIMARY KEY (singleton),
    CONSTRAINT ck_operator_resolution_writer_fence_singleton CHECK (singleton)
)
"""

_INSTALL_TRIGGER_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_trigger
         WHERE tgrelid = 'operator_resume_resolutions'::regclass
           AND tgname = 'trg_operator_resolution_writer_fence'
           AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_operator_resolution_writer_fence
        BEFORE INSERT ON operator_resume_resolutions
        FOR EACH ROW
        EXECUTE FUNCTION enforce_operator_resolution_writer_fence();
    END IF;
END;
$$
"""


class _SilentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _SilentParser(add_help=False)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--fence-writes", action="store_true")
    modes.add_argument("--check-fence", action="store_true")
    modes.add_argument("--migrate-authority", action="store_true")
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--reopen-writes", action="store_true")
    parser.add_argument("--deployed-revision")
    parser.add_argument("--schema-verified", action="store_true")
    parser.add_argument("--authority-verified", action="store_true")
    return parser


def _counts(row: Any, expected: int) -> tuple[int, ...] | None:
    if row is None or len(row) != expected:
        return None
    try:
        return tuple(int(value) for value in row)
    except (TypeError, ValueError):
        return None


def _print_postflight(counts: tuple[int, ...]) -> None:
    for field, value in zip(_POSTFLIGHT_FIELDS, counts, strict=True):
        print(f"{field}={value}")


def _postflight(conn: Any) -> tuple[int, ...] | None:
    return _counts(conn.execute(_POSTFLIGHT_SQL).fetchone(), len(_POSTFLIGHT_FIELDS))


def _postflight_ok(counts: tuple[int, ...] | None) -> bool:
    return counts is not None and all(value == 0 for value in counts[1:])


def _fence_closed(conn: Any) -> bool:
    row = conn.execute(_FENCE_STATE_SQL).fetchone()
    return bool(row == (False, "O", True, True))


def _fence_writes(conn: Any) -> bool:
    with conn.transaction():
        # ACCESS EXCLUSIVE waits for every earlier legacy-writer INSERT transaction to
        # finish, then prevents a later INSERT from crossing the close boundary.
        conn.execute(
            "LOCK TABLE operator_resume_resolutions IN ACCESS EXCLUSIVE MODE"
        )
        # Phase 18 does not have the Phase 19 fence table yet. Install only this
        # cutover prerequisite while the legacy writer table is exclusively locked;
        # the full additive schema still belongs to the later bootstrap gate.
        conn.execute(_FENCE_TABLE_SQL)
        conn.execute(_FENCE_FUNCTION_SQL)
        conn.execute(_INSTALL_TRIGGER_SQL)
        conn.execute(
            "INSERT INTO operator_resolution_writer_fence "
            "(singleton, writes_open) VALUES (TRUE, FALSE) "
            "ON CONFLICT (singleton) DO NOTHING"
        )
        conn.execute(
            "UPDATE operator_resolution_writer_fence "
            "SET writes_open = FALSE, updated_at = now() "
            "WHERE singleton IS TRUE"
        )
        conn.execute(
            "ALTER TABLE operator_resume_resolutions "
            "ENABLE TRIGGER trg_operator_resolution_writer_fence"
        )
    return True


def _lock_unresolved_runs(conn: Any) -> None:
    conn.execute(
        "SELECT id FROM payroll_runs "
        "WHERE status = 'needs_operator' FOR UPDATE"
    )
    conn.execute(
        "LOCK TABLE operator_resume_resolutions IN SHARE ROW EXCLUSIVE MODE"
    )


def _migrate_authority(conn: Any) -> tuple[int, ...] | None:
    with conn.transaction():
        _lock_unresolved_runs(conn)
        inventory = _counts(conn.execute(_INVENTORY_SQL).fetchone(), 3)
        if inventory is None or inventory[2] != 0:
            return None

        conn.execute(
            """
            WITH generation_counts AS (
                SELECT run_id, COUNT(*)::bigint AS generation_count
                  FROM operator_resume_resolutions
                 GROUP BY run_id
            ), sole AS (
                SELECT r.id
                  FROM operator_resume_resolutions r
                  JOIN generation_counts counts ON counts.run_id = r.run_id
                  JOIN payroll_runs pr ON pr.id = r.run_id
                 WHERE pr.status = 'needs_operator'
                   AND counts.generation_count = 1
            )
            UPDATE operator_resume_resolutions target
               SET authoritative = TRUE, superseded_by = NULL
              FROM sole
             WHERE target.id = sole.id
            """
        )
        conn.execute(
            """
            WITH generation_counts AS (
                SELECT run_id, COUNT(*)::bigint AS generation_count
                  FROM operator_resume_resolutions
                 GROUP BY run_id
            )
            UPDATE operator_resume_overrides target
               SET remember = FALSE
             WHERE EXISTS (
                 SELECT 1
                   FROM operator_resume_resolutions r
                   JOIN generation_counts counts ON counts.run_id = r.run_id
                   JOIN payroll_runs pr ON pr.id = r.run_id
                  WHERE r.id = target.operator_resolution_id
                    AND pr.status = 'needs_operator'
                    AND counts.generation_count = 1
             )
            """
        )
        postflight = _postflight(conn)
        if not _postflight_ok(postflight):
            raise RuntimeError("authority postflight failed")
    return postflight


def _revision_is_exact(value: str | None) -> bool:
    return value is not None and re.fullmatch(r"[0-9a-f]{7,40}", value) is not None


def _reopen_writes(conn: Any, args: argparse.Namespace) -> bool:
    if not (
        _revision_is_exact(args.deployed_revision)
        and args.schema_verified
        and args.authority_verified
    ):
        return False

    with conn.transaction():
        conn.execute(
            "LOCK TABLE operator_resume_resolutions IN ACCESS EXCLUSIVE MODE"
        )
        if not diff_against_live(conn).is_in_sync:
            return False
        if not _fence_closed(conn):
            return False
        if not _postflight_ok(_postflight(conn)):
            return False
        conn.execute(
            "UPDATE operator_resolution_writer_fence "
            "SET writes_open = TRUE, updated_at = now() "
            "WHERE singleton IS TRUE AND writes_open IS FALSE"
        )
    return True


def _run(args: argparse.Namespace, conn: Any) -> int:
    if args.fence_writes:
        if not _fence_writes(conn):
            return 2
        print("writer_fence=closed")
        return 0
    if args.check_fence:
        if not _fence_closed(conn):
            return 1
        print("writer_fence=closed")
        return 0
    if args.migrate_authority:
        postflight = _migrate_authority(conn)
        if postflight is None:
            return 1
        _print_postflight(postflight)
        return 0
    if args.check:
        postflight = _postflight(conn)
        if postflight is None:
            return 2
        _print_postflight(postflight)
        return 0 if _postflight_ok(postflight) else 1
    if args.reopen_writes:
        if not _reopen_writes(conn, args):
            return 2
        print("writer_fence=open")
        print(f"deployed_revision={args.deployed_revision}")
        return 0
    return 2


def main(argv: Sequence[str] | None = None, conn: Any | None = None) -> int:
    """Run one explicit deployment mode without exposing database diagnostics."""
    try:
        args = _parser().parse_args(list(argv) if argv is not None else None)
        connection_context = (
            psycopg.connect(get_settings().database_url, prepare_threshold=None)
            if conn is None
            else nullcontext(conn)
        )
        with connection_context as active_conn:
            return _run(args, active_conn)
    except Exception:
        return 2


if __name__ == "__main__":
    sys.exit(main())
