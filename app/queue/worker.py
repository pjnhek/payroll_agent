"""The queue's running body: a bounded pool of daemon worker threads, owned by
the FastAPI application lifespan, that wake instantly on the in-process
signal, poll slowly otherwise, and — the part that actually matters on a
platform that spins services down and redeploys them routinely — release
every lease they hold the moment the process is asked to stop.

WHY A HARD BOOT-TIME BUDGET REFUSAL, NOT A CLAMP. Every worker thread holds a
pooled database connection for as long as it runs a job. `POOL_BUDGET_RESERVE`
is the number of connections that must stay available for everything that is
NOT a worker — inbound webhook ingest, operator approve/reject, dashboard
reads. If `worker_count + POOL_BUDGET_RESERVE` exceeds the pool's own
`max_size`, the workers can check out every connection the pool has, and every
other request then hangs waiting for one that will never come free. Clamping
the configured count down and logging a warning would still boot into that
same state — quietly. `lifespan()` below RAISES instead, so a misconfigured
deploy fails loudly at boot, the same fail-fast posture this codebase already
takes for a missing database URL.

WHY THE STOP EVENT IS MINTED FRESH PER GENERATION, NEVER SHARED. A single
module-level stop `Event` that `start()` `.clear()`s on every call looks like
the obvious design and is wrong: clearing a SHARED event un-stops any straggler
thread that was told to stop but has not yet reached its own loop boundary to
notice — for example a thread wedged inside a slow handler past a timed-out
join. Resurrecting that thread on top of a brand-new generation would hold a
pooled connection against the same budget the boot-time guard exists to
protect, arriving through the back door instead of the front. The fix: every
`start()` call mints a BRAND NEW `threading.Event()` and passes it to each
thread it spawns as a plain function ARGUMENT, never a module global read.
Nothing anywhere in this module ever calls `.clear()` on a stop event. A
generation's event, once set, stays set forever — it belongs to that
generation and to no other, so a straggler can never be un-stopped and a
freshly-started generation can never observe an already-set event on its
first iteration. A `thread.is_alive()` check would stay GREEN under the bug
this design prevents (a corpse that exists but never does anything again);
the module's own tests prove liveness by an actually-invoked drain, never by
a heartbeat.

WHY ONE LIFECYCLE LOCK HELD ACROSS THE WHOLE TRANSITION, NOT PER-FIELD.
Guarding individual field WRITES is not the property `start()`/`stop()` need.
Two `stop()` calls that interleave around the join-then-release-then-partition
sequence would each read `_threads`, each join, each partition, and the
second would write `_threads`/`_orphans`/`_stop` back from a snapshot taken
before the first one finished — and `release_leases` would run twice. Holding
`_LIFECYCLE_LOCK` across the ENTIRE body of both functions makes a second,
concurrent caller BLOCK until the first's transition is fully complete, at
which point it finds the state already clean and returns as a genuine no-op:
no re-join, no second release call. `_loop` itself NEVER acquires this lock —
it reads its own stop event from its thread argument and reads `_generation`
as a plain int load, which is safe under the GIL and in any case only
advisory (see `_loop`'s own docstring). Because no worker thread can ever be
waiting on `_LIFECYCLE_LOCK`, holding it across `thread.join(...)` inside
`stop()` cannot deadlock. Do not "clean up" `_loop` to read its stop event or
`_generation` under this lock — that edit would look like a tidy-up and it
would reintroduce the exact deadlock this design avoids.

WHY A THREAD THAT SURVIVES A TIMED-OUT JOIN BECOMES A TRACKED ORPHAN, NEVER A
FORGOTTEN ONE. The lease fencing on `complete_job`/`fail_job` already keeps a
straggler's eventual write safe — a stale lease token is rejected regardless
of how many threads are running. But fencing says nothing about the
CONNECTION budget: two live worker sets on top of each other is twice the
configured connection pressure, which is the exact failure the boot-time
guard exists to prevent, now arriving at runtime instead of at startup.
`stop()` therefore partitions its threads after the join: a thread that is
still alive moves into `_orphans` and is never forgotten; `start()` refuses to
spawn a new generation while any orphan is alive, and only prunes an orphan
from that list once it has actually died.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db import repo, supabase
from app.queue import drain, wake

logger = logging.getLogger("payroll_agent.queue")

# Connections reserved for everything that is NOT a worker: inbound webhook
# ingest, operator approve/reject, dashboard reads. See the module docstring
# for why the boot-time guard using this constant raises rather than clamps.
POOL_BUDGET_RESERVE = 2

# ── Module state, all four names mutated only under _LIFECYCLE_LOCK ────────
_threads: list[threading.Thread] = []
_orphans: list[threading.Thread] = []
_generation: int = 0
_stop: threading.Event | None = None

# Held across the ENTIRE body of start()/stop() — see the module docstring's
# "WHY ONE LIFECYCLE LOCK" section for why this is safe against deadlock and
# what property it actually buys. _loop() must NEVER acquire this lock.
_LIFECYCLE_LOCK = threading.Lock()


def start(n: int) -> None:
    """Start `n` daemon worker threads as a new generation.

    Refuses (raises `RuntimeError`) while any thread or orphan from a
    previous generation is still alive — a second worker set spawned on top
    of a live one carries more live connections than the pool budget allows,
    even though the lease fencing keeps their eventual writes safe. `n <= 0`
    is a genuine no-op (the test/dev off switch): no thread, no stop event,
    no state mutated at all.
    """
    global _threads, _orphans, _generation, _stop
    with _LIFECYCLE_LOCK:
        _orphans = [t for t in _orphans if t.is_alive()]
        if _threads or _orphans:
            raise RuntimeError(
                f"worker.start() refused: {len(_threads)} live thread(s) and "
                f"{len(_orphans)} orphan(s) from generation {_generation} are "
                "still alive. Starting a second worker set on top of a live "
                "one would carry more open connections than the pool budget "
                "allows — call stop() and let it fully drain first."
            )
        if n <= 0:
            logger.info("queue workers disabled (worker_count=%d)", n)
            return
        _generation += 1
        gen = _generation
        stop_evt = threading.Event()
        _stop = stop_evt
        _threads = [
            threading.Thread(
                target=_loop,
                args=(gen, stop_evt),
                daemon=True,
                name=f"queue-worker-{gen}-{i}",
            )
            for i in range(n)
        ]
        for t in _threads:
            t.start()


def _loop(gen: int, stop_evt: threading.Event) -> None:
    """One worker thread's run loop: drain until the queue is empty, then
    wait for either a wakeup or the slow poll timeout, and repeat.

    `stop_evt` and `gen` are the thread's own ARGUMENTS, never a module
    global read — that is the whole of what binds this thread to exactly one
    generation and no other, and it is one word wide, so it is exactly the
    kind of thing a later "cleanup" edit deletes by accident. Comment it
    everywhere it matters.

    The `gen != _generation` compare is a cheap second fence so a thread from
    a previous generation winds itself down at its next loop boundary rather
    than racing a brand-new one. `start()` already refuses to spawn a new
    generation while any previous-generation thread or orphan is alive, so
    this state is UNREACHABLE through the public start()/stop() lifecycle —
    this fence is defence-in-depth against a future edit that relaxes that
    refusal, not a mechanism normal operation ever reaches. Say so plainly
    anywhere this is tested; do not let a reader mistake the fence working
    for the fence being exercised in production.

    This function NEVER acquires `_LIFECYCLE_LOCK` — see the module
    docstring for why holding that lock across `stop()`'s joins depends on
    that being true.

    A stop request that arrives WHILE this thread is inside `drain_once()`
    sets `stop_evt` and calls `wake.wake()` before this thread ever reaches
    `wake.clear()`/`wake.wait()` below — and `wake.clear()` would then erase
    that pending signal before this thread ever gets to observe it, leaving
    it to sleep out the full poll interval before noticing the stop request
    at the top of the next iteration. The explicit `stop_evt.is_set()` check
    immediately after `clear()` and before `wait()` closes exactly that gap,
    so a stop is never slower than the current `drain_once()`/`clear()` pair
    plus a lock acquisition — never a full poll interval.
    """
    while True:
        if stop_evt.is_set() or gen != _generation:
            return
        try:
            if drain.drain_once():
                continue
            wake.clear()
            if stop_evt.is_set():
                return
            wake.wait(timeout=get_settings().queue_poll_seconds)
        except Exception:  # noqa: BLE001 — a transient DB blip (or any other
            # exception raised anywhere in this iteration) must not take this
            # worker's poll loop down with it; log and keep polling rather
            # than letting one bad iteration cost the process a permanent,
            # silent unit of claim capacity.
            logger.exception(
                "queue worker gen=%s: iteration raised; continuing", gen
            )


def stop(grace_seconds: float = 10) -> None:
    """Stop the current worker generation and release every lease it holds.

    IDEMPOTENT: a caller that finds `_stop is None` — a never-started pool,
    or a second concurrent caller that lost the race for the lock — returns
    immediately as a genuine no-op. It does not set an event, does not join,
    and does not call `release_leases`, not even with an empty list. Across N
    concurrent callers, exactly ONE performs the transition and exactly ONE
    `release_leases` call is issued; every other caller blocks on
    `_LIFECYCLE_LOCK` until the transition is complete and then finds nothing
    left to do.

    `release_leases` runs UNCONDITIONALLY, even when a thread's join times
    out and it is still running. This is intentional and is the entire point
    of releasing gracefully at all: releasing a lease out from under a still-
    running worker is CORRECT, because that worker's own eventual
    `complete_job`/`fail_job` call is fenced on the lease token it was
    issued — it comes back `False`, the worker logs it and drops the job
    cleanly, and the row is meanwhile back at `pending` for the NEXT instance
    to pick up in seconds instead of waiting out the full lease duration. Do
    not "fix" this to only release after every thread has cleanly joined —
    that would turn every slow shutdown back into the multi-minute stall this
    exists to eliminate.
    """
    global _threads, _orphans, _stop
    with _LIFECYCLE_LOCK:
        if _stop is None:
            return
        stop_evt = _stop
        stop_evt.set()
        wake.wake()
        for t in _threads:
            t.join(timeout=grace_seconds)

        repo.release_leases(drain.held_tokens())

        still_alive = [t for t in _threads if t.is_alive()]
        if still_alive:
            logger.warning(
                "queue worker stop(): %d thread(s) did not exit within "
                "grace_seconds=%s; tracking as orphan(s) rather than "
                "forgetting them",
                len(still_alive),
                grace_seconds,
            )
        _orphans = _orphans + still_alive
        _threads = []
        _stop = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """The application's lifespan: start the worker pool on boot, stop it and
    release every held lease on shutdown.

    Refuses to start at all (raises `RuntimeError` before the yield) when the
    configured worker count would leave fewer than `POOL_BUDGET_RESERVE`
    connections for everything that is not a worker — see the module
    docstring's "WHY A HARD BOOT-TIME BUDGET REFUSAL" section for why this is
    a raise, never a clamp-and-warn.
    """
    settings = get_settings()
    if settings.worker_count + POOL_BUDGET_RESERVE > supabase.POOL_MAX_SIZE:
        raise RuntimeError(
            f"WORKER_COUNT={settings.worker_count} + reserve="
            f"{POOL_BUDGET_RESERVE} exceeds the connection pool's max_size="
            f"{supabase.POOL_MAX_SIZE}. Every worker holds a pooled "
            "connection for as long as it runs a job; booting anyway would "
            "let the workers check out every connection the pool has, and "
            "every other request would then hang waiting for one that never "
            "comes free. Lower WORKER_COUNT or raise the pool's max_size "
            "before redeploying."
        )
    start(settings.worker_count)
    try:
        yield
    finally:
        stop(grace_seconds=10)
