"""The in-process wake signal — how a producer tells an idle worker "there is
work" without a database round trip.

The obvious design reaches for `LISTEN`/`NOTIFY` or a session advisory lock to
wake a sleeping worker the instant something is enqueued. Both are silent
no-ops under Supavisor transaction-mode pooling (see `app/db/supabase.py`'s
own rationale for why no session state can survive across statements on that
pool) — so a design built on either would simply never fire, with no error to
notice by. The queue in this deployment never needs cross-process wakeup
anyway: the producer (an HTTP route enqueuing a job) and the consumer (a
worker thread) live in the SAME process. A plain in-process `threading.Event`
is therefore both simpler and more correct than the DB-notification designs
it replaces — it costs nothing, it cannot silently fail, and it wakes an idle
worker in microseconds instead of waiting out a poll interval.

**The one way to get this wrong: firing `wake()` from inside the enqueue
transaction, before it commits.** A worker blocked on `wait()` can resume the
instant `wake()` is called — which, if that call happens before `COMMIT`, is
before the new row is visible to any other connection's claim query. The
woken worker races ahead, finds nothing to claim, and goes back to sleep,
and the caller has paid for a wakeup that accomplished nothing. `wake()` must
always be called strictly AFTER the enqueuing transaction has committed.

The slow DB poll (the queue's own poll-interval knob) is not made redundant
by this signal — it is demoted to the fallback covering exactly what an
in-process signal cannot: an expired lease that needs reclaiming with no new
enqueue to trigger a wakeup, a job whose `available_at` backoff has just
elapsed, and a job enqueued by a process that has since restarted or died
(so there is no live thread anywhere holding a reference to this specific
`Event` instance to have called `wake()` on it in the first place).
"""
from __future__ import annotations

import threading

_event = threading.Event()


def wake() -> None:
    """Signal that new work may be available. Call this strictly AFTER the
    enqueuing transaction has committed — see this module's docstring for why
    calling it from inside the transaction wakes a worker into an empty claim.
    """
    _event.set()


def wait(timeout: float) -> bool:
    """Block up to `timeout` seconds for a wakeup. Returns True if a wakeup
    was signalled during the wait, False on a plain timeout — the caller uses
    the return value only for logging/metrics; either way it should loop back
    to drain, since a timeout is exactly the slow-poll fallback path working
    as designed.
    """
    return _event.wait(timeout)


def clear() -> None:
    """Reset the signal. A worker calls this immediately after waking, before
    it starts draining, so a wakeup that arrives WHILE this worker is already
    draining is not lost — it simply sets the event again for the worker's
    next wait() call rather than being swallowed by a wait() that already
    returned.
    """
    _event.clear()
