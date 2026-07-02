"""Database connection pool for the payroll agent.

Uses psycopg (psycopg3) with a ConnectionPool that emits connections with
prepare_threshold=None — required for Supavisor transaction-mode pooling
(port 6543).  Without this, psycopg3's auto-prepare kicks in after a query
repeats (default threshold = 5) and the server-side prepared statement is
lost when the backend connection is recycled, causing errors during the seed
upsert loop and pipeline runs.  (D-04 gotcha, verified against psycopg 3.3
docs + pgbouncer/Supabase transaction-mode caveat, Jun 2026.)

Public API:
    get_pool()       → ConnectionPool singleton (min=1, max=5)
    get_connection() → context manager yielding a pooled psycopg Connection
    close_pool()     → drain the pool and reset the singleton (idempotent)
"""

import threading
from contextlib import contextmanager
from typing import Generator

import psycopg
from psycopg_pool import ConnectionPool

from app.config import get_settings

# Module-level pool singleton — initialised lazily on first call to get_pool().
_pool: ConnectionPool | None = None
# WR-02: guards the double-checked-locking construction below so two concurrent
# first-callers (e.g. FastAPI's threadpool executor running sync routes /
# BackgroundTasks) cannot both observe `_pool is None` and each construct their
# own ConnectionPool, leaking one (08-RESEARCH.md Open Question 1).
_pool_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    """Return the module-level ConnectionPool, creating it if needed.

    The pool is opened on first access and reused for the lifetime of the
    process.  Each connection in the pool has prepare_threshold=None so that
    Supavisor transaction-mode (port 6543) works correctly.

    Thread-safe via double-checked locking (WR-02): the outer check avoids
    taking the lock on the common (already-initialized) path; the inner
    re-check under the lock closes the race where two threads could both pass
    the outer check before either constructs the pool.
    """
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                settings = get_settings()
                _pool = ConnectionPool(
                    conninfo=settings.database_url,
                    min_size=1,
                    max_size=5,
                    open=True,  # explicit; avoids DeprecationWarning about default changing
                    # D-04: disable server-side prepared statements on every connection
                    # so they do not break under Supavisor transaction-mode pooling.
                    kwargs={"prepare_threshold": None},
                    # Short wait timeout so tests and health checks that run without a live
                    # DB fail fast (5s) rather than blocking for the default 30s.
                    timeout=5,
                )
    return _pool


@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    """Context manager that yields a psycopg Connection from the pool.

    Usage:
        with get_connection() as conn:
            conn.execute("SELECT 1")

    The connection is returned to the pool on exit (normal or via exception).
    """
    pool = get_pool()
    with pool.connection() as conn:
        yield conn


def close_pool() -> None:
    """Close the ConnectionPool singleton and reset it to None.

    Drains active connections and stops the background worker thread so the
    process exits cleanly without "couldn't stop thread" warnings.  Safe to
    call when the pool is already None (idempotent).

    Use this in CLI entrypoints (e.g. seed.py __main__) via a finally block
    so the pool is always closed whether the caller succeeds or raises.
    """
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
