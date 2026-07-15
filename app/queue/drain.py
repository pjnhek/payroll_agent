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

import enum
import logging
import random
import threading
import time
import uuid
from collections.abc import Callable

from app.db import repo
from app.models.job import JobState
from app.queue import dispatch

logger = logging.getLogger("payroll_agent.queue")

# Held leases, guarded by a lock rather than left to bare dict/set mutation —
# multiple worker threads call drain_once() concurrently, and this set is read
# by held_tokens() from a DIFFERENT thread (the one driving shutdown).
_held_tokens: set[uuid.UUID] = set()
_held_tokens_lock = threading.Lock()

# Claims that the DATABASE may already have granted but that have not yet landed in
# `_held_tokens`. Incremented BEFORE repo.claim_job() and decremented in the same
# critical section that records the token, so the two can never be observed apart.
# `held_tokens()` refuses to snapshot while this is non-zero — see its docstring for
# what a snapshot taken inside that window costs.
_claims_in_flight = 0
_CLAIM_SETTLE_POLL_SECONDS = 0.005

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


def held_tokens(*, settle_timeout: float = 2.0) -> list[uuid.UUID]:
    """A snapshot of the lease tokens THIS process currently holds — the list
    a shutdown path passes to `repo.release_leases` so an in-flight claim is
    handed back immediately instead of sitting until its lease naturally
    expires.

    WAITS (bounded) FOR ANY MID-FLIGHT CLAIM, and that wait is the whole point.
    A worker is handed a lease by the DATABASE the instant `repo.claim_job()`
    returns, but this module does not learn about it until the very next line
    records the token. A snapshot taken in that window — one descheduled thread
    is all it takes — reports the lease as not-held, `release_leases` never hands
    it back, and the app finishes shutting down with a live lease outstanding.
    That job then sits unclaimable for the full `lease_seconds` (15 minutes) until
    it expires, on a platform that redeploys routinely. `drain_once` keeps
    `_claims_in_flight` non-zero across exactly that window, so this snapshot
    blocks until every claim has either landed in `_held_tokens` or come back
    empty.

    The timeout is a CEILING, not a policy: a claim is one fast UPDATE, so the
    normal wait is microseconds. But a shutdown must never hang on a wedged DB
    call — Render sends SIGTERM and then kills — so after `settle_timeout` this
    returns what it has and logs. That degrades to exactly today's behavior
    (a possibly-missed lease) rather than to a hung shutdown.
    """
    deadline = time.monotonic() + settle_timeout
    while True:
        with _held_tokens_lock:
            if _claims_in_flight == 0:
                return list(_held_tokens)
            if time.monotonic() >= deadline:
                logger.warning(
                    "queue: %d claim(s) still in flight after %.1fs; releasing the "
                    "%d lease(s) already recorded and giving up on the rest — a "
                    "lease granted but not yet recorded will be reclaimed only when "
                    "it expires",
                    _claims_in_flight,
                    settle_timeout,
                    len(_held_tokens),
                )
                return list(_held_tokens)
        time.sleep(_CLAIM_SETTLE_POLL_SECONDS)


class DrainOutcome(enum.StrEnum):
    """The per-call outcome of `drain_once()` — a pure in-process value, never
    persisted anywhere. `EMPTY` is the ONLY falsy member (see `__bool__`), so
    `worker.py:198`'s `if drain.drain_once():` keeps behaving exactly as it
    did when `drain_once()` returned a bare `bool` (D-04).

    This reuses the strings "done"/"dead" coincidentally with `JobState`
    (app/models/job.py) — it is a DIFFERENT vocabulary layer (a per-call
    transport-of-transport outcome, not a persisted row state) and MUST NOT
    be added to `tests/test_job_kind_drift.py`'s `JobKind`/`JobState`
    collision guard; it mirrors no SQL column.
    """

    EMPTY = "empty"
    DONE = "done"
    RETRIED = "retried"
    DEAD = "dead"
    FENCED = "fenced"

    def __bool__(self) -> bool:
        return self is not DrainOutcome.EMPTY


def drain_once() -> DrainOutcome:
    """Claim one job, dispatch it, and complete or fail it. Returns the
    specific `DrainOutcome` for what happened this call — `DrainOutcome.EMPTY`
    on an empty queue means there is nothing left to do right now, not an
    error, and is the only falsy member.
    """
    global _claims_in_flight

    # The claim and its bookkeeping are one indivisible step as far as any observer
    # is concerned. Between repo.claim_job() RETURNING and this module recording the
    # token, the database already considers the lease held by this process while
    # `held_tokens()` would report it as not-held — and a shutdown snapshotting that
    # window would leave the lease outstanding for its full 15-minute expiry. The
    # counter keeps `held_tokens()` out of the window rather than shrinking it.
    with _held_tokens_lock:
        _claims_in_flight += 1
    job = None
    try:
        job = repo.claim_job()
    finally:
        with _held_tokens_lock:
            if job is not None:
                _held_tokens.add(job.lease_token)
            _claims_in_flight -= 1

    if job is None:
        return DrainOutcome.EMPTY

    # Forget the token ONLY once the lease is genuinely settled — i.e. the database has
    # told us, in a write that actually landed, that this worker no longer owns it
    # (completed, failed, or fenced out because someone else already reclaimed it).
    # An unconditional discard is the bug: the failure that reaches the handler is very
    # often a DATABASE OUTAGE, and the fail_job write below fails for the same reason.
    # The row then stays `leased` in Postgres while this process has forgotten the token
    # — so a graceful shutdown cannot hand it back, and the job sits unclaimable for the
    # full lease (900s) even though we shut down cleanly.
    lease_settled = False
    try:
        dispatch.handle(job)
        if repo.complete_job(job.id, job.lease_token):
            outcome = DrainOutcome.DONE
        else:
            logger.warning(
                "queue: complete_job fenced out job=%s — lease was reclaimed "
                "while this worker was still running it; dropping cleanly",
                job.id,
            )
            outcome = DrainOutcome.FENCED
        # Fenced out counts as settled: the lease demonstrably belongs to someone else
        # now, so there is nothing left for THIS worker to hand back.
        lease_settled = True
    except Exception as exc:  # noqa: BLE001 — every dispatch failure must route
        # through the fenced fail_job write below, never escape and crash the
        # worker loop; a poison job must dead-letter, not take the process down.
        try:
            state = repo.fail_job(
                job.id,
                job.lease_token,
                error=exc,
                backoff_seconds=_backoff_seconds(job.attempts),
            )
            if state is None:
                logger.warning(
                    "queue: fail_job fenced out job=%s — lease was reclaimed "
                    "while this worker was still running it; dropping cleanly",
                    job.id,
                )
                outcome = DrainOutcome.FENCED
            elif state is JobState.DEAD:
                outcome = DrainOutcome.DEAD
            else:
                outcome = DrainOutcome.RETRIED
            lease_settled = True
        except Exception:  # noqa: BLE001 — the failure write ITSELF failed
            logger.exception(
                "queue: fail_job itself failed for job=%s — the row is still `leased` "
                "and this worker still owns it. KEEPING the lease token so a graceful "
                "shutdown can still hand it back; discarding it here is what would "
                "strand the job for the full lease.",
                job.id,
            )
            # RE-RAISE (D-10, review finding #1): an infra failure, never a settled
            # fence — worker.py:203 survives it, the pump route (17-04) turns it 503.
            raise
    finally:
        if lease_settled:
            with _held_tokens_lock:
                _held_tokens.discard(job.lease_token)
    return outcome
