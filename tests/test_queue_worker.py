"""Hermetic proofs for `app/queue/worker.py` — the bounded daemon worker pool,
its FastAPI lifespan wiring, the connection-pool budget refusal, the
second-start guard, the per-generation stop-event handshake that makes a
restarted worker actually drain, and the lifecycle lock's serialization
guarantee. No live database anywhere in this file — every worker started here
runs against a stubbed `drain.drain_once`/`repo.release_leases`, never the
real `app/db/repo/jobs.py` SQL. The live-DB half (a real held lease actually
released, a restarted worker completing a real job) lives in
`tests/test_queue_durability.py`.

EVERY TEST HERE MUST LEAVE ZERO LIVE `queue-worker-*` THREADS. `worker`
module state is process-global, and `tests/conftest.py`'s autouse
`_no_leaked_queue_workers` fixture fails the offending test by name if one
survives — a daemon worker leaked by a test in this file would still be
alive, claiming rows, when a later live-DB test module runs in the same
process. Every test below stops what it starts, in a `try/finally` where the
body can raise before reaching its own `stop()` call.

NEITHER RESTART PROOF (`test_start_refuses_while_a_previous_generation_is_
still_alive`'s final `start(1)`, `test_a_restarted_worker_actually_drains`)
MAY ESTABLISH "the worker restarted" FROM `thread.is_alive()` OR A THREAD
COUNT. Both stay GREEN against the exact defect these tests exist to catch —
a stale, already-set stop event that a fresh generation's threads observe on
their very first iteration and return against, without ever calling
`drain_once`. A thread that exists and does nothing looks identical, by
`is_alive()`, to a thread that is genuinely working. Each restart proof below
establishes success from an ACTUALLY INVOKED `drain_once`, via an `Event` the
stub sets — never from liveness.
"""
from __future__ import annotations

import asyncio
import functools
import threading
import time
import uuid
from collections.abc import Sequence

import pytest
from fastapi import FastAPI

from app.config import get_settings
from app.db import repo
from app.queue import drain, wake, worker
from app.queue.drain import DrainOutcome

# A generous, deterministic upper bound for every Event.wait()/Thread.join()
# in this file — never a time.sleep poll. Long enough that a slow CI runner
# cannot make a legitimately-passing test flake; short enough that a genuinely
# broken mechanism fails the test suite promptly rather than hanging it.
_TIMEOUT = 5.0


@pytest.fixture(autouse=True)
def _worker_env(monkeypatch: pytest.MonkeyPatch):
    """Every worker thread this file starts calls `get_settings()` inside its
    own run loop (for `queue_poll_seconds`), and `lifespan()` calls it before
    ever spawning one — `database_url` has no default, so a bare stub value
    is required for any of this to run hermetically. Cleared before and after
    so a per-test env edit (`WORKER_COUNT`, `QUEUE_POLL_SECONDS`) never leaks
    into the next test via the cache.
    """
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://queue-worker-test-stub/mockdb")
    yield
    get_settings.cache_clear()


def _live_worker_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name.startswith("queue-worker-")]


def _drain_once_signalling(event: threading.Event) -> bool:
    """A `drain_once` stub that sets `event` (proving this iteration actually
    ran) and reports "no work claimed", used wherever a test needs an Event
    handshake on invocation rather than a return value."""
    event.set()
    return False


# ---------------------------------------------------------------------------
# 1. worker_count=0 is a genuine no-op; stop() on a never-started pool is safe
# ---------------------------------------------------------------------------


def test_worker_count_zero_starts_no_threads() -> None:
    before = threading.active_count()
    worker.start(0)
    assert threading.active_count() == before
    assert _live_worker_threads() == []

    worker.stop()  # never-started pool: must not raise, must spawn nothing
    assert threading.active_count() == before


# ---------------------------------------------------------------------------
# 2. The pool-budget guard: refuses over budget, accepts exactly-at-budget
# ---------------------------------------------------------------------------


def test_lifespan_refuses_to_start_when_the_pool_budget_is_violated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_stub = FastAPI()
    monkeypatch.setattr(drain, "drain_once", lambda: False)

    monkeypatch.setenv("WORKER_COUNT", "4")  # 4 + 2 reserve > 5 max_size
    get_settings.cache_clear()

    async def _enter_over_budget() -> None:
        async with worker.lifespan(app_stub):
            pytest.fail("lifespan must raise before yielding when over budget")

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(_enter_over_budget())
    message = str(excinfo.value)
    assert "WORKER_COUNT=4" in message, message
    assert "max_size=5" in message, message
    assert _live_worker_threads() == [], "a refused boot must spawn nothing"

    monkeypatch.setenv("WORKER_COUNT", "3")  # 3 + 2 reserve == 5 max_size: accepted
    get_settings.cache_clear()

    async def _enter_at_budget() -> None:
        async with worker.lifespan(app_stub):
            pass

    asyncio.run(_enter_at_budget())  # must not raise
    assert _live_worker_threads() == []


# ---------------------------------------------------------------------------
# 3. The lifespan starts exactly the configured count and joins them on exit
# ---------------------------------------------------------------------------


def test_lifespan_starts_and_stops_the_configured_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_stub = FastAPI()
    monkeypatch.setattr(drain, "drain_once", lambda: False)
    monkeypatch.setenv("WORKER_COUNT", "2")
    get_settings.cache_clear()

    seen_during: list[str] = []

    async def _run() -> None:
        async with worker.lifespan(app_stub):
            seen_during.extend(t.name for t in _live_worker_threads())

    asyncio.run(_run())

    assert len(seen_during) == 2, (
        f"expected exactly 2 queue-worker-* threads while the lifespan was "
        f"entered, saw: {seen_during}"
    )
    assert _live_worker_threads() == [], "exiting the lifespan must join every thread"


# ---------------------------------------------------------------------------
# 4. wake() breaks a worker out of its poll immediately, never waits for it
# ---------------------------------------------------------------------------


def test_wake_breaks_the_poll_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUEUE_POLL_SECONDS", "60")  # deliberately long
    get_settings.cache_clear()

    calls = 0
    drained_second_time = threading.Event()
    entered_wait = threading.Event()

    def fake_drain_once() -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            drained_second_time.set()
        return False

    real_wait = wake.wait

    def spy_wait(timeout: float) -> bool:
        # Set BEFORE calling the real wait — this handshake is race-free
        # because threading.Event.wait() checks its flag when invoked, not
        # only while it is already parked: any wake() the test fires after
        # observing this Event is guaranteed to be seen by the call below,
        # whether or not that call has "started blocking" yet.
        entered_wait.set()
        return real_wait(timeout)

    monkeypatch.setattr(drain, "drain_once", fake_drain_once)
    monkeypatch.setattr(wake, "wait", spy_wait)

    try:
        worker.start(1)
        assert entered_wait.wait(timeout=_TIMEOUT), "worker never reached its poll wait"
        wake.wake()
        assert drained_second_time.wait(timeout=_TIMEOUT), (
            "wake() did not break the worker out of its 60s poll promptly"
        )
    finally:
        worker.stop(grace_seconds=_TIMEOUT)
    assert _live_worker_threads() == []


# ---------------------------------------------------------------------------
# 5. stop() is idempotent: never-started, and stop();stop() after a clean start
# ---------------------------------------------------------------------------


def test_stop_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    release_calls: list[list[uuid.UUID]] = []

    def spy_release(tokens: Sequence[uuid.UUID]) -> int:
        release_calls.append(list(tokens))
        return 0

    monkeypatch.setattr(repo, "release_leases", spy_release)
    monkeypatch.setattr(drain, "drain_once", lambda: False)

    worker.stop()  # never-started pool
    assert release_calls == []

    worker.start(1)
    worker.stop(grace_seconds=_TIMEOUT)
    worker.stop()  # second call after a clean stop: no-op
    worker.stop()  # third call: still a no-op

    assert len(release_calls) == 1, (
        "release_leases must be issued exactly once across the one real "
        f"transition and two subsequent no-op stop() calls; got {release_calls}"
    )
    assert release_calls[0] == []
    assert _live_worker_threads() == []


# ---------------------------------------------------------------------------
# 6. start() refuses while an orphan from a previous generation is alive
# ---------------------------------------------------------------------------


def test_start_refuses_while_a_previous_generation_is_still_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked = threading.Event()
    release_blocker = threading.Event()

    def blocking_drain_once() -> bool:
        blocked.set()
        release_blocker.wait(timeout=_TIMEOUT)
        return False

    monkeypatch.setattr(drain, "drain_once", blocking_drain_once)

    worker.start(1)
    assert blocked.wait(timeout=_TIMEOUT), "worker never entered drain_once"

    worker.stop(grace_seconds=0.1)  # deliberately too short: the join times out
    orphan = worker._orphans[0]
    assert orphan.is_alive()

    with pytest.raises(RuntimeError) as excinfo:
        worker.start(1)
    assert "orphan" in str(excinfo.value)
    assert "1" in str(excinfo.value)  # names the live/orphan count

    # Release the straggler and wait for it to actually exit — a permanent
    # one-shot latch that never re-admits a start() after a rough shutdown
    # would brick the process, so this guard must be a real liveness check.
    release_blocker.set()
    orphan.join(timeout=_TIMEOUT)
    assert not orphan.is_alive(), "the orphan did not exit after its blocker released"

    # "SUCCEEDS" means DRAINS, not "spawned a thread" — establish the restart
    # from an actually-invoked drain_once, never from is_alive() or a count.
    restarted_drained = threading.Event()
    monkeypatch.setattr(
        drain, "drain_once", functools.partial(_drain_once_signalling, restarted_drained)
    )

    worker.start(1)  # the orphan is now dead and pruned: this must succeed
    assert restarted_drained.wait(timeout=_TIMEOUT), (
        "the restarted worker's drain_once was never invoked"
    )
    worker.stop(grace_seconds=_TIMEOUT)
    assert _live_worker_threads() == []


# ---------------------------------------------------------------------------
# 7. A restarted worker actually drains — never proven by thread liveness
# ---------------------------------------------------------------------------


def test_a_restarted_worker_actually_drains(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `thread.is_alive()` assertion would stay GREEN against the bug this
    test exists to catch: a stop event that `stop()` sets and that nothing
    ever resets would leave a restarted generation's threads observing an
    already-set event on their very first iteration and returning before
    ever calling `drain_once` — alive, and doing nothing. This test asserts
    a DRAIN, not a heartbeat.
    """
    drained_gen1 = threading.Event()
    monkeypatch.setattr(
        drain, "drain_once", functools.partial(_drain_once_signalling, drained_gen1)
    )

    worker.start(1)
    assert drained_gen1.wait(timeout=_TIMEOUT)
    worker.stop(grace_seconds=_TIMEOUT)  # a CLEAN stop: the thread joins
    assert _live_worker_threads() == []

    drained_gen2 = threading.Event()
    monkeypatch.setattr(
        drain, "drain_once", functools.partial(_drain_once_signalling, drained_gen2)
    )

    worker.start(1)  # a second generation, with a brand-new stop event
    assert drained_gen2.wait(timeout=_TIMEOUT), (
        "the restarted worker's drain_once was never invoked — the second "
        "generation observed a still-set stop event from the first"
    )
    worker.stop(grace_seconds=_TIMEOUT)
    assert _live_worker_threads() == []


# ---------------------------------------------------------------------------
# 8. stop() serializes: a second concurrent caller BLOCKS on the lock
# ---------------------------------------------------------------------------


def test_stop_serializes_a_concurrent_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    """The deterministic half of the lifecycle-lock proof.

    A plain "did B's stop() call complete yet" check is NOT sufficient here:
    the wedge below blocks on a shared `proceed` Event, and B would appear to
    "not complete" for that reason alone even with the lock removed, the
    moment B independently reaches the very same wedge. The proof this test
    actually needs is narrower and stronger: does B ever manage to CALL the
    wedged function AT ALL while A is still inside it? Under the real
    `_LIFECYCLE_LOCK`, B blocks at the lock ACQUISITION itself and can never
    reach the wedge until A's whole transition (including the wedge) is
    complete — so exactly one call is observed before `proceed` is released.
    Remove the lock and B races in independently, calling the wedge a SECOND
    time while A is still parked inside it.
    """
    monkeypatch.setattr(drain, "drain_once", lambda: False)

    entered_wedge: list[str] = []
    entered_lock = threading.Lock()
    inside_critical_section = threading.Event()
    proceed = threading.Event()

    def wedged_held_tokens() -> list[object]:
        with entered_lock:
            entered_wedge.append(threading.current_thread().name)
        inside_critical_section.set()
        proceed.wait(timeout=_TIMEOUT)
        return []

    release_calls: list[object] = []

    def spy_release(tokens: object) -> int:
        release_calls.append(tokens)
        return 0

    monkeypatch.setattr(drain, "held_tokens", wedged_held_tokens)
    monkeypatch.setattr(repo, "release_leases", spy_release)

    worker.start(1)

    def _stop() -> None:
        worker.stop(grace_seconds=_TIMEOUT)

    thread_a = threading.Thread(name="stopper-a", target=_stop)
    thread_a.start()
    assert inside_critical_section.wait(timeout=_TIMEOUT), (
        "thread A never reached the wedged held_tokens() call inside stop()"
    )

    thread_b = threading.Thread(name="stopper-b", target=_stop)
    thread_b.start()

    # Give B a bounded window to race in. Under the real lock B is parked at
    # the ACQUISITION line and can never reach the wedge during this window
    # no matter how long it is given, so this bound only needs to comfortably
    # exceed how long a genuinely-unblocked B takes to reach the wedge.
    thread_b.join(timeout=1.0)
    with entered_lock:
        assert entered_wedge == ["stopper-a"], (
            "the second concurrent stop() reached the wedged held_tokens() "
            f"call while the first was still inside it — entered_wedge="
            f"{entered_wedge}. This means _LIFECYCLE_LOCK did not serialize "
            "the two stop() calls."
        )

    proceed.set()
    thread_a.join(timeout=_TIMEOUT)
    thread_b.join(timeout=_TIMEOUT)
    assert not thread_a.is_alive() and not thread_b.is_alive()

    assert len(release_calls) == 1, (
        f"release_leases must be issued exactly once across the two "
        f"concurrent stop() calls; got {len(release_calls)}"
    )
    assert worker._threads == []
    assert worker._orphans == []
    assert worker._stop is None

    # State corruption that leaves the module unstartable must not hide
    # behind a green teardown — prove a subsequent start() actually drains.
    monkeypatch.setattr(drain, "held_tokens", lambda: [])
    drained = threading.Event()
    monkeypatch.setattr(
        drain, "drain_once", functools.partial(_drain_once_signalling, drained)
    )
    worker.start(1)
    assert drained.wait(timeout=_TIMEOUT)
    worker.stop(grace_seconds=_TIMEOUT)
    assert _live_worker_threads() == []


# ---------------------------------------------------------------------------
# 9. Across N concurrent stop()s, release_leases is issued exactly once
# ---------------------------------------------------------------------------


def test_concurrent_stops_release_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drain, "drain_once", lambda: False)

    release_calls: list[object] = []

    def spy_release(tokens: object) -> int:
        release_calls.append(tokens)
        return 0

    monkeypatch.setattr(repo, "release_leases", spy_release)

    worker.start(2)

    n_callers = 4
    barrier = threading.Barrier(n_callers, timeout=_TIMEOUT)
    errors: list[BaseException] = []
    lock = threading.Lock()

    def _stop() -> None:
        try:
            barrier.wait()
            worker.stop(grace_seconds=_TIMEOUT)
        except BaseException as exc:  # noqa: BLE001 — collected and reported below
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=_stop) for _ in range(n_callers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=_TIMEOUT)

    assert not errors, f"a concurrent stop() raised: {errors}"
    assert all(not t.is_alive() for t in threads)
    assert len(release_calls) == 1, (
        f"release_leases must be issued exactly once across {n_callers} "
        f"concurrent stop() calls; got {len(release_calls)}"
    )
    assert worker._threads == []
    assert worker._orphans == []
    assert worker._stop is None
    assert _live_worker_threads() == []


# ---------------------------------------------------------------------------
# 10. The stale-generation fence: unreachable through the public lifecycle,
#     proven directly by poking module-private state.
# ---------------------------------------------------------------------------


def test_a_stale_generation_thread_winds_itself_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`start()` refuses to spawn a new generation while any previous-
    generation thread or orphan is alive, so a stale generation coexisting
    with a live one is UNREACHABLE through the public start()/stop()
    lifecycle. This test constructs that state directly by poking
    `worker._generation` — it proves the fence in `_loop` WORKS, and it does
    NOT prove the fence is ever reached in production. Nothing in this repo
    may describe it as a proven production guarantee.
    """
    entered = threading.Event()
    monkeypatch.setattr(
        drain, "drain_once", functools.partial(_drain_once_signalling, entered)
    )

    worker.start(1)
    assert entered.wait(timeout=_TIMEOUT)
    thread = worker._threads[0]

    worker._generation += 1  # construct the unreachable stale-generation state
    assert worker._stop is not None and not worker._stop.is_set(), (
        "the stop event must remain UNSET so this proof cannot be passing "
        "because the thread was told to stop rather than because its "
        "generation went stale"
    )

    wake.wake()
    thread.join(timeout=_TIMEOUT)
    assert not thread.is_alive(), (
        "the stale-generation thread did not exit — the gen != _generation "
        "fence in _loop did not fire"
    )

    # Clean up module state by hand: this thread never went through stop()'s
    # own transition (it exited via the generation fence instead), so the
    # module's bookkeeping needs the same reset stop() would have performed.
    worker._threads = []
    worker._stop = None
    worker.stop()  # idempotent: confirms the module is left in a clean state
    assert _live_worker_threads() == []


def test_a_wake_arriving_during_the_drain_is_not_erased(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A producer that commits its job and wakes WHILE this worker is inside
    `drain_once()` must not have that signal thrown away.

    The lost-wakeup shape: `drain_once()` scans, finds nothing, returns False. A
    producer commits a job and calls `wake()` in the window before the worker
    reaches `wake.clear()`. A `clear()` placed AFTER the drain erases that
    brand-new signal, and the worker sleeps the FULL poll interval with a
    claimable job already in the table — the operator clicks Retrigger and
    watches nothing happen for `queue_poll_seconds`.

    WHAT THIS ASSERTS, AND WHY A WALL-CLOCK BOUND ALONE WOULD BE A FALSE PROOF.
    "The second drain came quickly" is NOT the property. A `wake.wait()` that
    never blocks (say it were changed to `return True`) would also redrain
    promptly — by hot-spinning — and a purely temporal assertion would sail
    straight through that. The actual property is that THE SIGNAL SURVIVED THE
    DRAIN, so this inspects the wake event's own state at the instant the loop
    enters `wait()`: it must be SET, which is why `wait()` returns immediately.
    The drain count is pinned at exactly 2 for the same reason — a hot-spinning
    loop would drain many more times than that.
    """
    monkeypatch.setenv("QUEUE_POLL_SECONDS", "30")
    get_settings.cache_clear()

    drain_times: list[float] = []
    set_at_wait_entry: list[bool] = []
    second_drain = threading.Event()
    real_wait = wake.wait

    def _drain_and_signal_midway() -> bool:
        drain_times.append(time.monotonic())
        if len(drain_times) == 1:
            # Stand in for a producer committing a job and waking while this
            # worker is still inside the drain. A trailing clear() would erase it.
            wake.wake()
            return False
        second_drain.set()
        return False

    def _spy_wait(timeout: float) -> bool:
        # The load-bearing observation: is the signal that arrived mid-drain STILL
        # set as we go to sleep, or did a trailing clear() eat it?
        set_at_wait_entry.append(wake._event.is_set())
        return real_wait(timeout)

    monkeypatch.setattr(drain, "drain_once", _drain_and_signal_midway)
    monkeypatch.setattr(wake, "wait", _spy_wait)

    try:
        worker.start(1)
        assert second_drain.wait(timeout=_TIMEOUT), (
            "the worker never ran a second drain — the wake that arrived during the "
            "first drain was erased by a trailing clear(), so it slept the full poll "
            "interval instead of observing the signal"
        )
    finally:
        worker.stop(grace_seconds=_TIMEOUT)

    assert set_at_wait_entry and set_at_wait_entry[0] is True, (
        "the worker entered wait() with the wake event CLEARED — the signal that "
        "arrived during the first drain was erased by a trailing clear(). It would "
        "now sleep the full poll interval with a claimable job already in the table."
    )
    assert len(drain_times) == 2, (
        f"expected exactly 2 drains, got {len(drain_times)} — more than that means the "
        "loop is hot-spinning rather than genuinely sleeping on the wake signal, and a "
        "purely temporal assertion would have called that a pass"
    )
    gap = drain_times[1] - drain_times[0]
    assert gap < 1.0, (
        f"second drain came {gap:.2f}s after the first; a wake delivered during the "
        "first drain must be observed immediately, not slept through "
        "(QUEUE_POLL_SECONDS=30 here, so a trailing clear() shows up as a ~30s gap)"
    )


# ---------------------------------------------------------------------------
# 11. A propagated drain_once() exception (a fail_job()-itself-fails infra
#     outage that re-raises rather than mapping to a truthy DrainOutcome)
#     does not kill the worker loop.
# ---------------------------------------------------------------------------


def test_worker_survives_a_propagated_drain_once_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """worker.py:203's `except Exception` must catch a `drain_once()` call
    that RAISES and keep the loop polling.

    `thread.is_alive()` ALONE is explicitly NOT the property under test: a
    thread that is merely still an object in memory says nothing about
    whether its run loop actually resumed calling drain_once() after the
    exception, versus having wedged or silently stopped iterating while
    technically not yet reaped. This test instead proves a SECOND, real
    `drain_once()` invocation happened AFTER the raising first call — the
    second-Event/`calls >= 2` handshake below — and only THEN asserts
    liveness, so a worker that "looks alive" but never resumed polling
    cannot pass.
    """
    calls = 0
    first_call_raised = threading.Event()
    second_call_happened = threading.Event()

    def _raise_once_then_signal() -> DrainOutcome:
        nonlocal calls
        calls += 1
        if calls == 1:
            first_call_raised.set()
            raise RuntimeError("simulated double-failure: fail_job itself failed")
        second_call_happened.set()
        return DrainOutcome.EMPTY

    monkeypatch.setattr(drain, "drain_once", _raise_once_then_signal)

    try:
        worker.start(1)
        assert first_call_raised.wait(timeout=_TIMEOUT), (
            "the worker never reached the raising first drain_once() call"
        )
        # The load-bearing wait: a SECOND real drain_once() invocation, not
        # merely the thread object surviving — proves worker.py:203's except
        # caught the propagated exception, logged, and the loop RESUMED
        # polling rather than dying silently after the first iteration.
        assert second_call_happened.wait(timeout=_TIMEOUT), (
            "the worker never ran a second drain_once() after the first one "
            "raised — worker.py:203's except did not keep the loop polling"
        )
        assert calls >= 2, f"expected at least 2 drain_once() calls, got {calls}"
        thread = worker._threads[0]
        assert thread.is_alive(), (
            "the worker thread died after a propagated drain_once() exception"
        )
    finally:
        worker.stop(grace_seconds=_TIMEOUT)
    assert _live_worker_threads() == []
