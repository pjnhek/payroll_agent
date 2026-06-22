"""Idempotent schema bootstrap for the payroll agent.

Applies app/db/schema.sql to the target Postgres instance (local or Supabase).
DATABASE_URL is read from the environment via pydantic-settings — never from a
hardcoded string or a positional CLI argument.

Usage:
    # Non-destructive apply (default — safe to re-run at any time):
    python -m app.db.bootstrap

    # Opt-in destructive reset (drops all tables in reverse-dependency order,
    # then recreates them from schema.sql):
    python -m app.db.bootstrap --reset

Security:
    T-02-01: DATABASE_URL password is stripped before any diagnostic print.
    T-02-02: --reset is opt-in only; the default path never touches DROP.
    T-02-04: prepare_threshold=None on the connection (D-04 Supavisor gotcha).
"""

import pathlib
import sys
import urllib.parse

import psycopg
import psycopg.sql

from app.config import get_settings

# Path to the DDL source of truth relative to this file's location
_SCHEMA_SQL = pathlib.Path(__file__).parent / "schema.sql"

# Reverse-dependency drop order (name_matches + paystub_line_items first,
# businesses last). CASCADE handles any lingering FK dependencies, but explicit
# reverse order documents the dependency direction and avoids races without CASCADE.
#
# D-21-06: name_matches is the DEAD relational reconciliation table (resolutions now
# live in payroll_runs.reconciliation JSONB). It is no longer created by schema.sql,
# so it is dropped FIRST on a --reset to clear it from an existing DB. The default
# (non-reset) apply path ALSO drops it unconditionally below, because
# CREATE TABLE IF NOT EXISTS cannot remove a table that already exists on the live DBs.
_DROP_ORDER = [
    "name_matches",
    "paystub_line_items",
    "eval_results",
    "email_messages",
    "payroll_runs",
    "employees",
    "businesses",
]


def _safe_db_url(raw_url: str) -> str:
    """Return DATABASE_URL with the password replaced by '***'.

    Uses urllib.parse so the reconstruction is correct for all URL schemes.
    The reconstructed URL is returned in ALL parseable cases — including a
    perfectly valid password-less URL (e.g. postgresql://user@host:6543/db,
    where auth comes from PGPASSWORD/.pgpass/IAM).  '<unparseable url>' is
    reserved for genuine parse failures and empty/scheme-less input (WR-05).
    """
    try:
        parsed = urllib.parse.urlparse(raw_url)
        if not parsed.scheme:  # empty string or not a URL at all
            return "<unparseable url>"
        if parsed.password:
            safe_netloc = parsed.netloc.replace(
                f":{parsed.password}@", ":***@", 1
            )
            parsed = parsed._replace(netloc=safe_netloc)
        return urllib.parse.urlunparse(parsed)
    except Exception:
        return "<unparseable url>"


def bootstrap(reset: bool = False) -> None:
    """Apply schema.sql to the DATABASE_URL target.

    Args:
        reset: When True, drops all tables in reverse-dependency order before
               applying schema.sql.  Default False (non-destructive).

    Raises:
        ValidationError: If DATABASE_URL is not set in the environment.
        psycopg.Error: If the DB connection or schema application fails.
    """
    settings = get_settings()
    db_url = settings.database_url
    safe_url = _safe_db_url(db_url)

    print(f"Bootstrap target: {safe_url}")

    # Open a single direct connection for this admin operation.
    # D-04: prepare_threshold=None prevents psycopg3's auto-prepare from
    # firing under Supavisor transaction-mode pooling.
    with psycopg.connect(db_url, prepare_threshold=None) as conn:
        if reset:
            print(
                "RESET: dropping all tables in reverse dependency order"
                " — this is destructive"
            )
            for table in _DROP_ORDER:
                print(f"  DROP TABLE IF EXISTS {table} CASCADE")
                # Identifier-quote the table name rather than f-string it into SQL —
                # the list is trusted (no injection risk) but the project rule is
                # "never f-string SQL" (review fix).
                conn.execute(
                    psycopg.sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
                        psycopg.sql.Identifier(table)
                    )
                )
            conn.commit()

        # D-21-06 live-DB migration: drop the DEAD name_matches table on EVERY apply
        # (not just --reset). schema.sql no longer creates it, but CREATE IF NOT EXISTS
        # cannot remove a table that already exists on the live local / Supabase DBs —
        # so the only way to retire it on a running database is an explicit DROP here,
        # BEFORE re-applying schema.sql. IF EXISTS makes this a no-op once it is gone.
        print("  DROP TABLE IF EXISTS name_matches CASCADE  (D-21-06 dead-table migration)")
        conn.execute("DROP TABLE IF EXISTS name_matches CASCADE;")
        # D-21-06 (col): same CREATE-IF-NOT-EXISTS limitation applies to the removed
        # paystub_line_items.match_confidence column — schema.sql dropped it from the
        # CREATE, but an existing table keeps the column until an explicit ALTER. Drop
        # it here on every apply; IF EXISTS makes it a no-op once gone (confidence is
        # fully removed in 2.1 — provenance is employee_id + submitted_name).
        print("  ALTER TABLE paystub_line_items DROP COLUMN IF EXISTS match_confidence  (D-21-06 dead-column migration)")
        conn.execute("ALTER TABLE IF EXISTS paystub_line_items DROP COLUMN IF EXISTS match_confidence;")
        conn.commit()

        # Apply the full DDL source of truth atomically.
        schema_sql = _SCHEMA_SQL.read_text()
        conn.execute(schema_sql)
        conn.commit()

    print("Bootstrap complete. Tables applied.")


if __name__ == "__main__":
    reset_flag = "--reset" in sys.argv
    bootstrap(reset=reset_flag)
