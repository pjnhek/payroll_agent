"""`drain_once()` — the single drain step shared by every worker thread and,
later, by any process-external pump that wants to run exactly one job
without importing thread-lifecycle machinery. It lives in its own module for
that reason: a caller that only wants to run one job should never have to
pull in `threading.Thread` subclassing or a start/stop lifecycle.

Both `repo.complete_job` and `repo.fail_job` are FENCED on the exact
`lease_token` the claim returned. A `False`/`None` return from either means
this worker's lease has already been reclaimed by someone else — it is a
zombie, and the only correct response is to log and drop: never retry, never
error the run, never re-enqueue. `dispatch.handle(job)` is the only thing
between the claim and the completion write, and nothing in this module holds
a database transaction across it — the claim already committed, the
completion/failure writes are each their own statement, and the work
`dispatch.handle` does in between may include a slow network or LLM call
that must never be allowed to pin a pooled connection.
"""
from __future__ import annotations

import logging
import random
import threading
import uuid
from collections.abc import Callable

from app.db import repo
from app.queue import dispatch

logger = logging.getLogger("payroll_agent.queue")

# Held leases, guarded by a lock rather than left to bare dict/set mutation —
# multiple worker threads call drain_once() concurrently, and this set is read
# by held_tokens() from a DIFFERENT thread (the one driving shutdown).
_held_tokens: set[uuid.UUID] = set()
_held_tokens_lock = threading.Lock()

# The backoff curve: doubles per attempt, capped, then jittered by +/-50% so a
# batch of jobs that failed together does not all retry in the same instant
# and immediately re-collide. Computed here in plain Python (not inside SQL)
# specifically so it is unit-testable without a clock or a live database.
_BACKOFF_BASE_SECONDS = 5.0
_BACKOFF_CAP_SECONDS = 300.0


def _backoff_seconds(
    attempts: int,
    *,
    rand: Callable[[float, float], float] = random.uniform,
) -> float:
    """The retry delay for a job that has been claimed `attempts` times and
    just failed. `rand` defaults to `random.uniform` but is injectable so a
    test can stub it and get a fully deterministic value back.

    Only infrastructural failures reach this path today (a database hiccup,
    an import error) — a genuine pipeline stage failure never raises out of
    the handler; it is caught and persisted as an ERROR on the run before the
    handler returns normally. That may change once a real failure-retry
    design exists for stage failures, but this curve is not built ahead of
    that design.
    """
    doubled = _BACKOFF_BASE_SECONDS * (2 ** max(attempts - 1, 0))
    return float(min(_BACKOFF_CAP_SECONDS, doubled) * rand(0.5, 1.5))


def held_tokens() -> list[uuid.UUID]:
    """A snapshot of the lease tokens THIS process currently holds — the list
    a shutdown path passes to `repo.release_leases` so an in-flight claim is
    handed back immediately instead of sitting until its lease naturally
    expires.
    """
    with _held_tokens_lock:
        return list(_held_tokens)


def drain_once() -> bool:
    """Claim one job, dispatch it, and complete or fail it. Returns whether a
    job was claimed at all — False on an empty queue means there is nothing
    left to do right now, not an error.
    """
    job = repo.claim_job()
    if job is None:
        return False

    with _held_tokens_lock:
        _held_tokens.add(job.lease_token)
    try:
        dispatch.handle(job)
        if not repo.complete_job(job.id, job.lease_token):
            logger.warning(
                "queue: complete_job fenced out job=%s — lease was reclaimed "
                "while this worker was still running it; dropping cleanly",
                job.id,
            )
    except Exception as exc:  # noqa: BLE001 — every dispatch failure must route
        # through the fenced fail_job write below, never escape and crash the
        # worker loop; a poison job must dead-letter, not take the process down.
        if not repo.fail_job(
            job.id,
            job.lease_token,
            error=exc,
            backoff_seconds=_backoff_seconds(job.attempts),
        ):
            logger.warning(
                "queue: fail_job fenced out job=%s — lease was reclaimed "
                "while this worker was still running it; dropping cleanly",
                job.id,
            )
    finally:
        with _held_tokens_lock:
            _held_tokens.discard(job.lease_token)
    return True
