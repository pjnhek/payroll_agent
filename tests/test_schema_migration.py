"""Non-reset `python -m app.db.bootstrap` regression coverage.

Before this file existed, `app/db/schema.sql`'s non-reset apply path had ZERO test
coverage anywhere in the suite — every other schema-touching test goes through
`tests/conftest.py`'s `seeded_db` fixture, which always calls `bootstrap(reset=True)`
against a database it just dropped and recreated. A destructive reset can never
reproduce a live-deploy migration, because it never applies schema.sql to a database
that already holds data. `.github/workflows/deploy-migrate.yml:53` runs the exact
opposite: `python -m app.db.bootstrap` with NO `--reset`, against production, on every
deploy. That untested path is where the defect below lived, undetected, for a long
stretch of the project's history.

THE DEFECT (fixed at `app/db/schema.sql:325-347`)
-------------------------------------------------------------------
`email_messages` widens its uniqueness guard across app history:
`uq_email_run_purpose` (2-col) -> `uq_email_run_purpose_round` (3-col, now DELETED)
-> `uq_email_run_purpose_round_epoch` (4-col, current). The deleted 3-column ADD was
guarded only on ITS OWN absence, never on the presence of its 4-column successor — so
on a database that had already reached the 4-column state and then accumulated an
epoch-distinct retrigger pair (documented as the very reason `epoch` exists,
`schema.sql:265-273`), the ADD tried to create a 3-column unique index over rows that
violate it, raised `UniqueViolation`, and aborted the ENTIRE schema apply. Because
that ADD sits earlier in the file than the `failure_category` CHECK repair block, the
repair never ran either — this is the same failure class
`tests/test_queue_durability.py::test_deployed_schema_repair_accepts_authorization_expired`
exists to prove, on the repair side rather than the migration side.

WHY EACH TEST OWNS A THROWAWAY DATABASE, NEVER THE SHARED `seeded_db` TARGET
------------------------------------------------------------------------------
`seeded_db` (module-scoped, `tests/conftest.py`) resets and re-seeds the ONE database
named by `DATABASE_URL` for the whole test session — sharing that target here would
mean this file's deliberately-broken/legacy schema states leak into every other
live-DB module's fixture. Instead, `_scratch_database()` below `CREATE DATABASE`s a
fresh, uniquely-named database on the SAME Postgres server `DATABASE_URL` already
points at (never a different host — always localhost, never Supabase), runs
`app.db.bootstrap.bootstrap()` against THAT database by temporarily repointing
`DATABASE_URL` + clearing `get_settings()`'s cache, and always `DROP DATABASE`s it in
a `finally`, so a failing test leaves nothing behind.
"""
from __future__ import annotations

import contextlib
import os
import urllib.parse
import uuid
from collections.abc import Iterator

import psycopg
import psycopg.sql
import pytest

from app.config import get_settings

_HAS_DB = bool(os.environ.get("DATABASE_URL"))
_HAS_RESET = os.environ.get("ALLOW_DB_RESET") == "1"

# Mirrors the two-factor guard every other live-DB module defines locally
# (tests/test_email_epoch_arbiter_integration.py, tests/test_atomic_persist.py, ...).
_SKIP_LIVE_DB = pytest.mark.skipif(
    not (_HAS_DB and _HAS_RESET),
    reason="Live-DB tests require DATABASE_URL and ALLOW_DB_RESET=1 (two-factor guard)",
)

# `queueproof` is what makes CI's `concurrency-proof.yml` collect this file by
# MARKER (see that workflow's "Run the queue durability proofs" step) — the ONLY
# CI job with a real Postgres. Without it, this regression is unwatched, which is
# how the defect it guards survived nine phases in the first place.
pytestmark = [pytest.mark.integration, pytest.mark.queueproof, _SKIP_LIVE_DB]


def _admin_dsn_for(base_dsn: str) -> str:
    """The maintenance-DB DSN (`/postgres`) on the SAME server as `base_dsn`.

    `CREATE DATABASE` / `DROP DATABASE` cannot run against the database being
    created or dropped — they need a connection to a sibling database on the
    same server, and every Postgres install ships `postgres` for exactly this.
    """
    parsed = urllib.parse.urlparse(base_dsn)
    return urllib.parse.urlunparse(parsed._replace(path="/postgres"))


def _dsn_with_dbname(base_dsn: str, db_name: str) -> str:
    parsed = urllib.parse.urlparse(base_dsn)
    return urllib.parse.urlunparse(parsed._replace(path=f"/{db_name}"))


@contextlib.contextmanager
def _scratch_database() -> Iterator[str]:
    """Create a uniquely-named throwaway database on `DATABASE_URL`'s server,
    yield its DSN, then unconditionally drop it.

    Never touches `DATABASE_URL`'s own database — a sibling is created and
    dropped instead, so this file can never collide with or corrupt whatever
    `seeded_db` or another live-DB module is doing against the assigned target.
    """
    base_dsn = os.environ["DATABASE_URL"]
    admin_dsn = _admin_dsn_for(base_dsn)
    db_name = f"pa_schema_migration_test_{uuid.uuid4().hex[:16]}"
    scratch_dsn = _dsn_with_dbname(base_dsn, db_name)

    with psycopg.connect(admin_dsn, autocommit=True) as admin_conn:
        admin_conn.execute(
            psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(db_name))
        )
    try:
        yield scratch_dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin_conn:
            admin_conn.execute(
                psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    psycopg.sql.Identifier(db_name)
                )
            )


@contextlib.contextmanager
def _bootstrap_pointed_at(scratch_dsn: str) -> Iterator[None]:
    """Run `app.db.bootstrap.bootstrap()` against `scratch_dsn`, never the real
    `DATABASE_URL`.

    `bootstrap()` reads its target exclusively from `get_settings().database_url`
    (an `lru_cache`d pydantic-settings value) — there is no DSN parameter to pass
    directly. Temporarily repointing the `DATABASE_URL` env var and clearing the
    cache, then restoring both in `finally`, mirrors the exact pattern
    `tests/conftest.py::_stub_database_url_when_absent` already uses for the same
    reason: a stale cached Settings instance must never leak into a later test.
    """
    original = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = scratch_dsn
    get_settings.cache_clear()
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original
        get_settings.cache_clear()


def _unique_constraints_on_email_messages(dsn: str) -> set[str]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT conname FROM pg_constraint"
            " WHERE conrelid = 'email_messages'::regclass AND contype = 'u'"
        ).fetchall()
    return {row[0] for row in rows}


def _insert_epoch_distinct_retrigger_pair(dsn: str) -> None:
    """Seed the exact row shape that triggers the defect: two `email_messages`
    rows sharing `(run_id, purpose, round)` and differing only in `epoch` — the
    documented retrigger shape (`schema.sql:265-273`).

    `run_id` MUST be NOT NULL to reproduce: Postgres treats NULLs as distinct in
    a UNIQUE constraint, so a NULL `run_id` silently would not violate it.
    """
    business_id = uuid.uuid4()
    run_id = uuid.uuid4()
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO businesses (id, name, contact_email, pay_period)"
            " VALUES (%s, %s, %s, %s)",
            (str(business_id), "Repro Co", f"repro-{business_id}@example.test", "weekly"),
        )
        conn.execute(
            "INSERT INTO payroll_runs (id, business_id) VALUES (%s, %s)",
            (str(run_id), str(business_id)),
        )
        conn.execute(
            "INSERT INTO email_messages"
            " (run_id, direction, message_id, purpose, round, epoch)"
            " VALUES (%s, 'outbound', %s, 'confirmation', 1, 0),"
            "        (%s, 'outbound', %s, 'confirmation', 1, 1)",
            (
                str(run_id),
                f"msg-{run_id}-epoch0",
                str(run_id),
                f"msg-{run_id}-epoch1",
            ),
        )


def test_nonreset_bootstrap_succeeds_against_retrigger_shape_and_is_idempotent() -> None:
    """Truth #1: non-reset bootstrap succeeds against a DB holding the documented
    epoch-distinct retrigger shape, stays idempotent across repeated applies, and
    lands on the 4-column constraint alone.

    Reproduces the exact `UniqueViolation` failure on a scratch database, with the
    fix in place: bootstrap the empty scratch DB once (the
    initial deploy), seed the retrigger-shape row pair (simulating a production
    retrigger having happened), then re-apply non-reset bootstrap twice more —
    once to prove the fix (this call is what raised UniqueViolation before it),
    once again to prove the fix is idempotent, matching `deploy-migrate.yml`'s
    every-deploy invocation.
    """
    with _scratch_database() as scratch_dsn, _bootstrap_pointed_at(scratch_dsn):
        from app.db.bootstrap import bootstrap

        bootstrap(reset=False)  # initial apply — empty DB, establishes the schema

        _insert_epoch_distinct_retrigger_pair(scratch_dsn)

        bootstrap(reset=False)  # the call that raised UniqueViolation before the fix
        bootstrap(reset=False)  # idempotency: a second re-apply must also succeed

        constraints = _unique_constraints_on_email_messages(scratch_dsn)

    assert "uq_email_run_purpose_round_epoch" in constraints
    assert "uq_email_run_purpose_round" not in constraints
    assert "uq_email_run_purpose" not in constraints


def _create_legacy_two_column_email_messages_table(dsn: str) -> None:
    """Build the email_messages table exactly as it looked BEFORE the epoch
    mechanism existed: no epoch column, only the 2-column `uq_email_run_purpose`
    unique constraint. This is the earliest shape in the ladder
    (`uq_email_run_purpose` -> `uq_email_run_purpose_round` [deleted] ->
    `uq_email_run_purpose_round_epoch`), simulating a database that has never
    been migrated past the very first widening.

    Deliberately created with NO `run_id`/`purpose` FKs or CHECKs beyond what the
    migration blocks under test actually touch — this table exists only to prove
    the unique-constraint ladder, not to be a full production-shaped table.
    """
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE email_messages ("
            "    id         UUID PRIMARY KEY,"
            "    run_id     UUID,"
            "    direction  TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),"
            "    message_id TEXT NOT NULL,"
            "    purpose    TEXT,"
            "    send_state TEXT,"
            "    round      INT,"
            "    CONSTRAINT uq_email_run_purpose UNIQUE (run_id, purpose)"
            ")"
        )


def test_legacy_two_column_constraint_ladders_to_four_column_epoch_constraint() -> None:
    """Truth #2: a database carrying ONLY the legacy 2-column
    `uq_email_run_purpose` ends up on `uq_email_run_purpose_round_epoch`, with
    NEITHER obsolete constraint present — proven by actually walking that path
    on a legacy-shaped database, not argued.

    With the deleted 3-column ADD gone, the widening block that used to create
    it now only drops `uq_email_run_purpose` when present.
    The very next block's own DROP of `uq_email_run_purpose_round` is then a
    no-op (it was never created), and its ADD of the 4-column constraint
    proceeds directly — so a legacy 2-column database and a fresh database both
    reach the SAME end state through the SAME code path, without ever passing
    through the deleted intermediate.
    """
    with _scratch_database() as scratch_dsn:
        _create_legacy_two_column_email_messages_table(scratch_dsn)

        with _bootstrap_pointed_at(scratch_dsn):
            from app.db.bootstrap import bootstrap

            # Non-reset: email_messages already exists (legacy-shaped), so
            # CREATE TABLE IF NOT EXISTS is a no-op on it and every migration
            # block below runs against the hand-built legacy table.
            bootstrap(reset=False)

        constraints = _unique_constraints_on_email_messages(scratch_dsn)
        epoch_column_exists = _has_epoch_column(scratch_dsn)

    assert epoch_column_exists, "the idempotent ADD COLUMN IF NOT EXISTS must have run"
    assert "uq_email_run_purpose_round_epoch" in constraints
    assert "uq_email_run_purpose_round" not in constraints
    assert "uq_email_run_purpose" not in constraints


def _has_epoch_column(dsn: str) -> bool:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT 1 FROM information_schema.columns"
            " WHERE table_name = 'email_messages' AND column_name = 'epoch'"
        ).fetchone()
    return row is not None
