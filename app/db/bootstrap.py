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
    The DATABASE_URL password is stripped before any diagnostic print, so a
    credential can never reach CI logs or a terminal transcript.
    prepare_threshold=None on the connection (the Supavisor transaction-mode
    pooling gotcha — see app/db/supabase.py).

Destructiveness — read before running this against a live database:
    --reset is opt-in and drops EVERY table in _DROP_ORDER. That is the destructive path.

    The default path is NOT drop-free. It drops in two distinct ways:

    1. PERMANENT removals, issued directly by this module on every apply:
         - DROP TABLE IF EXISTS name_matches CASCADE
         - ALTER TABLE paystub_line_items DROP COLUMN IF EXISTS match_confidence
       Both retire schema that the deterministic-decisioning redesign removed. They must
       run outside --reset because CREATE TABLE IF NOT EXISTS can add a table but can
       never REMOVE one that already exists on a live database — so re-applying schema.sql
       alone would leave the dead table and column in place forever. IF EXISTS makes both
       a no-op once they are gone.

    2. TRANSIENT drops, issued by schema.sql itself, which this path also applies:
       four DROP CONSTRAINT statements (the payroll_runs status CHECK, the email_messages
       purpose CHECK, and the two superseded uq_email_* unique constraints). Each is an
       idempotent DROP-and-RE-ADD inside a single atomic block, so the constraint is never
       absent at rest — but a DROP CONSTRAINT does execute. Do not read "no permanent
       removals" as "no DROP runs".

    The practical consequence: running this with no flags against a live database WILL
    permanently remove name_matches and match_confidence if they are still present, and
    WILL churn the four constraints above. It removes no other table, column, or row.
"""

import pathlib
import sys
import urllib.parse

import psycopg
import psycopg.sql

from app.config import get_settings

# Path to the DDL source of truth relative to this file's location
_SCHEMA_SQL = pathlib.Path(__file__).parent / "schema.sql"

# Bound how long a DDL may wait on / hold a lock against the live app, so lock
# contention fails RED instead of hanging the deploy-migrate job indefinitely.
LOCK_TIMEOUT_MS = 10000        # 10s: abort if a DDL can't get its lock
STATEMENT_TIMEOUT_MS = 60000   # 60s: abort a single runaway statement

# Reverse-dependency drop order (name_matches + paystub_line_items first,
# businesses last). CASCADE handles any lingering FK dependencies, but explicit
# reverse order documents the dependency direction and avoids races without CASCADE.
#
# name_matches is the DEAD relational reconciliation table (resolutions now live in
# the payroll_runs.reconciliation JSONB column). schema.sql no longer creates it, so
# it is dropped FIRST on a --reset to clear it from an existing DB. The default
# (non-reset) apply path ALSO drops it unconditionally below, because
# CREATE TABLE IF NOT EXISTS cannot remove a table that already exists on a live DB.
#
# "jobs" is positioned immediately after "eval_results" — i.e. BEFORE ALL THREE of
# its FK targets: payroll_runs, email_messages (via email_id), and businesses (via
# business_id). Placing it merely "before payroll_runs" would still land it AFTER
# email_messages, backwards relative to this file's own reverse-dependency-order
# convention. Without "jobs" in this list at all, the seeded_db fixture's --reset
# path (the sole hermetic reset owner, gated by ALLOW_DB_RESET) would silently
# orphan job rows referencing dropped-and-recreated run_ids across every test run
# that resets the DB — poisoning isolation for any live-DB test that asserts
# durability across resets. Each DROP TABLE IF EXISTS ... CASCADE below
# already cascades, so exact ordering is defensive-not-required for correctness —
# but a comment that documents the dependency direction wrongly is worse than none.
_DROP_ORDER = [
    "name_matches",
    "paystub_line_items",
    "eval_results",
    "operator_resume_overrides",
    "jobs",
    "operator_resume_resolutions",
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
    reserved for genuine parse failures and empty/scheme-less input — do not widen
    it to cover the password-less case, or a legitimate target becomes undiagnosable.
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
    # prepare_threshold=None prevents psycopg3's auto-prepare from firing under
    # Supavisor transaction-mode pooling (see app/db/supabase.py for the failure).
    with psycopg.connect(db_url, prepare_threshold=None) as conn:
        # Bound lock/statement time on this admin connection so a DDL blocked by the
        # live app aborts red rather than hanging CI. Session-level SET; applies to
        # every statement below on this connection.
        # (These are integer literals from trusted module constants formatted into a
        # SET — not user input. Postgres does not accept `SET ... = %s` for these
        # GUCs, so a literal is required; the "never f-string SQL" rule targets
        # untrusted values, which these are not.)
        # statement_timeout also bounds the one-shot DATA migrations inside
        # schema.sql (the DO-block re-adds and the clarification_round backfill
        # UPDATE), not only DDL. If a table ever grows large enough that a backfill
        # exceeds 60s, the migrate aborts RED — which is safe, because schema.sql's
        # migrations are atomic and idempotent so a re-run converges. Raise
        # STATEMENT_TIMEOUT_MS if that happens; do not remove the bound.
        conn.execute(f"SET lock_timeout = '{LOCK_TIMEOUT_MS}ms'")
        conn.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'")
        conn.commit()

        if reset:
            print(
                "RESET: dropping all tables in reverse dependency order"
                " — this is destructive"
            )
            for table in _DROP_ORDER:
                print(f"  DROP TABLE IF EXISTS {table} CASCADE")
                # Identifier-quote the table name rather than f-string it into SQL.
                # The list is a trusted module constant, but "never f-string SQL" is
                # absolute here — an exception granted for "trusted" values is how
                # the rule erodes.
                conn.execute(
                    psycopg.sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
                        psycopg.sql.Identifier(table)
                    )
                )
            conn.commit()

        # Live-DB migration: drop the DEAD name_matches table on EVERY apply, not
        # just --reset. schema.sql no longer creates it, but CREATE TABLE IF NOT
        # EXISTS cannot REMOVE a table that already exists on a live DB — so an
        # explicit DROP here, BEFORE re-applying schema.sql, is the only way to
        # retire it on a running database. IF EXISTS makes this a no-op once gone.
        print("  DROP TABLE IF EXISTS name_matches CASCADE  (dead-table migration)")
        conn.execute("DROP TABLE IF EXISTS name_matches CASCADE;")
        # The same CREATE-IF-NOT-EXISTS limitation applies to the removed
        # paystub_line_items.match_confidence column: schema.sql dropped it from the
        # CREATE, but an existing table keeps the column until an explicit ALTER.
        # Drop it on every apply; IF EXISTS makes it a no-op once gone. Match
        # confidence is gone from the design entirely — line-item provenance is
        # employee_id + submitted_name, with no score anywhere.
        print(
            "  ALTER TABLE paystub_line_items DROP COLUMN IF EXISTS match_confidence "
            " (dead-column migration)"
        )
        conn.execute(
            "ALTER TABLE IF EXISTS paystub_line_items DROP COLUMN IF EXISTS match_confidence;"
        )
        conn.commit()

        # Apply the full DDL source of truth atomically.
        schema_sql = _SCHEMA_SQL.read_text()
        conn.execute(schema_sql)
        conn.commit()

    print("Bootstrap complete. Tables applied.")


if __name__ == "__main__":
    reset_flag = "--reset" in sys.argv
    bootstrap(reset=reset_flag)
