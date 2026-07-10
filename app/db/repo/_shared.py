"""DB repo — internal plumbing shared by every aggregate module (connection
context + no-op transaction).

Discipline (PATTERNS.md / RESEARCH Security Domain): pooled get_connection() +
conn.transaction(); %s / named placeholders ONLY, NEVER f-string SQL. The
header-chain `references` LIKE (app/db/repo/emails.py) is a named placeholder.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator

import psycopg


@contextlib.contextmanager
def _conn_ctx(
    conn: psycopg.Connection | None,
) -> Iterator[tuple[psycopg.Connection, bool]]:
    """Yield (conn, owns): use the caller's conn, or open a pooled one we own.

    `get_connection` is resolved through the PACKAGE (app.db.repo), at call
    time, rather than imported at module level here — this module (_shared.py)
    is a DIFFERENT module than the app/db/repo/__init__.py facade, so a
    module-level `from app.db.supabase import get_connection` here would bind
    its OWN private name, invisible to `monkeypatch.setattr(repo,
    "get_connection", ...)` (the exact seam tests/conftest.py's `fake_repo`
    fixture patches). Importing `app.db.repo` INSIDE the function body (not at
    this module's top level) avoids a circular-import-at-init-time failure —
    the package is fully initialized by the time any request-handling code
    actually calls `_conn_ctx`.
    """
    if conn is not None:
        yield conn, False
    else:
        import app.db.repo as _repo_pkg

        with _repo_pkg.get_connection() as owned:
            yield owned, True


@contextlib.contextmanager
def _nulltx() -> Iterator[None]:
    """No-op CM: when a caller passes their own conn, they own the transaction."""
    yield
