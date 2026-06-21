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

from app.config import get_settings

# Path to the DDL source of truth relative to this file's location
_SCHEMA_SQL = pathlib.Path(__file__).parent / "schema.sql"

# Reverse-dependency drop order (paystub_line_items first, businesses last)
# CASCADE handles any lingering FK dependencies, but explicit reverse order
# documents the dependency direction and avoids races without CASCADE.
_DROP_ORDER = [
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
    """
    try:
        parsed = urllib.parse.urlparse(raw_url)
        # netloc without password: user@host:port
        if parsed.password:
            safe_netloc = parsed.netloc.replace(
                f":{parsed.password}@", ":***@", 1
            )
            safe = parsed._replace(netloc=safe_netloc)
            return urllib.parse.urlunparse(safe)
    except Exception:
        pass
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
                conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
            conn.commit()

        # Apply the full DDL source of truth atomically.
        schema_sql = _SCHEMA_SQL.read_text()
        conn.execute(schema_sql)
        conn.commit()

    print("Bootstrap complete. Tables applied.")


if __name__ == "__main__":
    reset_flag = "--reset" in sys.argv
    bootstrap(reset=reset_flag)
