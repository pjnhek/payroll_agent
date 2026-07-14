"""Database connection pool for the payroll agent.

Uses psycopg (psycopg3) with a ConnectionPool that emits connections with
prepare_threshold=None — required for Supavisor transaction-mode pooling
(port 6543).  Without it, psycopg3's auto-prepare kicks in once a query repeats
(default threshold = 5), but transaction-mode pooling hands the next statement to
a DIFFERENT backend connection, where that server-side prepared statement does not
exist.  The result is intermittent "prepared statement does not exist" failures in
the seed upsert loop and in pipeline runs — failures that only appear after a
statement has run a few times, which is why they never show up in a quick smoke
test.  (Verified against the psycopg 3.3 docs and the pgbouncer/Supabase
transaction-mode caveat.)

Public API:
    get_pool()       → ConnectionPool singleton (min=1, max=5)
    get_connection() → context manager yielding a pooled psycopg Connection
    close_pool()     → drain the pool and reset the singleton (idempotent)
"""

import threading
from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool

from app.config import get_settings

# The shared connection budget every other consumer of this pool must reason
# against — most importantly the queue worker's own boot-time refusal, which
# compares the configured worker count against this exact number rather than
# a second hand-copied literal. One number, one place; a bare `max_size=5` at
# the ConnectionPool call site below and a second copy elsewhere is precisely
# the kind of drift that would make that refusal silently wrong.
POOL_MAX_SIZE = 5

# Module-level pool singleton — initialised lazily on first call to get_pool().
_pool: ConnectionPool | None = None
# Guards the double-checked-locking construction below. Without it, two concurrent
# first-callers (e.g. FastAPI's threadpool executor running sync routes, or two
# BackgroundTasks) can both observe `_pool is None` and each construct their own
# ConnectionPool — one of which is then orphaned, leaking its connections.
_pool_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    """Return the module-level ConnectionPool, creating it if needed.

    The pool is opened on first access and reused for the lifetime of the
    process.  Each connection in the pool has prepare_threshold=None so that
    Supavisor transaction-mode (port 6543) works correctly.

    Thread-safe via double-checked locking. The OUTER `_pool is None` check keeps
    the common (already-initialized) path lock-free. The INNER re-check, under the
    lock, is the part that actually closes the race: two threads can both pass the
    outer check before either takes the lock, so without the second check the loser
    would overwrite the winner's pool with a fresh one — leaking the first pool's
    open connections. Both checks are required; neither alone is correct.
    """
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                settings = get_settings()
                _pool = ConnectionPool(
                    conninfo=settings.database_url,
                    min_size=1,
                    max_size=POOL_MAX_SIZE,
                    open=True,  # explicit; avoids DeprecationWarning about default changing
                    # Disable server-side prepared statements on every connection so
                    # they cannot break under Supavisor transaction-mode pooling
                    # (see the module docstring for the failure mode).
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
