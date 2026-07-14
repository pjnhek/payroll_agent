"""A genuine claim race, an actually-reclaimed expired lease, and the
double-fence, driven at the sync repo seam under a threading.Barrier against a
real Postgres. Never through an HTTP route.

WHY THE SYNC REPO SEAM, NEVER AN HTTP ROUTE (mirrors tests/test_concurrency_proof.py's
own rationale — read that module's docstring for the full argument). A shared
TestClient funnels every thread through ONE ASGI portal; N threads posting to an
`async def` route with no `await` before the DB work execute strictly one at a time.
This repo has already shipped one concurrency proof that passed while proving nothing
for exactly that reason. Every test below calls `app.db.repo.claim_job` /
`complete_job` / `fail_job` / `release_leases` directly, from genuinely parallel OS
threads released simultaneously by a `threading.Barrier`.

ISOLATION — THE PROOFS IN THIS FILE CAN EAT EACH OTHER'S JOBS UNLESS GUARDED.
`seeded_db` is module-scoped: `bootstrap(reset=True)` runs ONCE for this whole
module, not once per test. Several proofs here (and more appended by later plans)
deliberately leave a row behind — a released lease, a mid-reclaim lease — and
`claim_job()` claims the oldest eligible row GLOBALLY, with no per-test scoping of
its own. A later test could therefore claim an EARLIER test's leftover row: a second
winner in a claim race, an attempts count that belongs to someone else's job, a
"reclaim" that reclaimed a stranger. This is the same vacuous-proof class this repo
has already shipped once (a concurrency proof whose threads never actually raced)
and had to fix. The `_isolated_jobs` fixture below closes it: autouse, function-
scoped, empties `jobs` on BOTH sides of every test. Every claim assertion in this
file is ALSO scoped to the id the test itself enqueued — belt and suspenders, since
a fixture bug should not be the only thing standing between a proof and a false
pass.

TEARDOWN ORDERING — THE DELETE MUST NEVER LAND UNDER A LIVE WORKER. A later plan
runs REAL daemon worker threads in this same file, and one of its proofs
deliberately constructs a handler that outlives its own test body on purpose. If
`_isolated_jobs`' teardown ran its DELETE while that straggler still held a leased
row, the straggler's own `complete_job` would then fence against a row that no
longer exists — a proof asserting "the zombie was fenced" would PASS against a
mechanism that never ran, which is worse than a failing proof. Two mechanisms close
this, and neither is redundant with the other: `_require_quiesced_workers()` is a
GATE — it runs immediately before EACH of `_isolated_jobs`' two deletes and fails
loudly, WITHOUT deleting, if any `queue-worker-*` thread is still alive. `live_worker`
is the ORDERED QUIESCE — the only sanctioned way to start a real worker in this
module. It REQUESTS `_isolated_jobs` as a parameter, and that dependency edge (not a
comment, not discipline) is what makes pytest finalize `live_worker` BEFORE
`_isolated_jobs`: pytest tears fixtures down in the reverse of their setup order, and
requesting a fixture forces it to be set up first. So teardown always runs
`live_worker`'s quiesce (release every blocker, stop the worker pool, wait for zero
live worker threads) THEN `_isolated_jobs`' delete — on every path, including an
aborted test body. A future edit that drops `_isolated_jobs` from `live_worker`'s
signature "because it's autouse anyway" would silently remove this ordering
guarantee while both fixtures still appear to run; say so at the fixture itself, not
only here.

TEARDOWN ORDERING CONTRACT FOR LATER PLANS: any test appended to this file that
starts a real queue worker MUST go through the `live_worker` fixture. A worker
started any other way (a bare `worker.start()` call) bypasses the ordering edge
entirely, and `_require_quiesced_workers()` is what turns that bypass into a loud,
attributable test failure at the next delete rather than a leased row silently
vanishing out from under a live thread.

WHAT A DOUBLE-EXECUTION ACTUALLY COSTS (the narrowed, true claim — never write
"harmless"). A stalled-not-dead worker whose lease expires can double-EXECUTE the
pipeline once a second worker reclaims its job. Every status advance is guarded by
`claim_status`'s compare-and-swap and every JSONB persist is last-write-wins by
value, so pipeline STATE cannot be corrupted by the double-run. But the CLIENT-FACING
SEND is not automatically safe: a worker killed between the email provider accepting
the send and this app's own `sent`-state commit leaves no `sent` row while the client
already has the email, and the existing already-sent guard counts ONLY `sent` rows —
so a naive rerun would send a second one. That gap is closed by
`app/pipeline/send_guard.py`'s fail-closed unconfirmed-reservation guard, which lands
in a later plan; this file's `rewind_for_reclaim` epoch-stability assertion is the
half of that mechanism that belongs here — leaving `reply_epoch` untouched on an
automatic rewind is what keeps a reclaimed run inside that guard's scope at all.

FALSIFYING MUTATIONS THIS FILE PROVES (each executed against a live Postgres,
red run pasted into the plan's SUMMARY, then reverted):
  (a) drop the expired-lease `OR` clause from claim_job's WHERE — the reclaim test
      must go red (the job never becomes claimable again).
  (b) drop the `lease_token` fence from fail_job only (leaving it on complete_job) —
      the zombie's failure write must wrongly succeed.
  (c) replace the `FOR UPDATE SKIP LOCKED` subquery with a SELECT-then-UPDATE — the
      N-thread barrier race must produce more than one winner.
  (d) add the epoch bump to rewind_for_reclaim — the epoch-stability assertion must
      go red.
  (e) — TWO-DIRECTIONAL — insert a probe test at the top of this file that enqueues a
      job and returns WITHOUT claiming it, and no-op `_isolated_jobs`' body: the claim-
      race test must go red with TWO winners (the probe's leftover row is claimable).
      Then restore `_isolated_jobs` while KEEPING the probe: the module must go GREEN
      again — proving the fixture, not test ordering, is what isolates.
  (f) drop `ck_jobs_run_pipeline_requires_run` from schema.sql — the raw-INSERT
      rejection test must go red (the INSERT that bypasses enqueue_job succeeds).
  (g) empty `_require_quiesced_workers()`'s body — the gate-refuses-to-delete test
      must go red.
  (h) delete the `_require_quiesced_workers()` call from the PRE-yield half of
      `_isolated_jobs` — the both-sides-of-the-yield wiring test must go red.
  (i) empty `fail_on_leaked_queue_workers()`'s body (tests/conftest.py) — the suite-
      wide leak guard's own test must go red.
"""
from __future__ import annotations

import inspect
import re
import threading
import time
import uuid

import psycopg
import pytest

from tests.conftest import QUEUE_WORKER_THREAD_PREFIX, live_queue_worker_threads

# EVERY test in this file carries both markers via this module-level list, so a
# later-added test cannot forget one: `integration` is what makes the module
# self-skip without a database (the two-factor guard `seeded_db` itself enforces);
# `queueproof` is the selector the narrow CI gate collects — a test missing this
# marker skips silently and forever, which is this milestone's own named
# cross-cutting hazard.
pytestmark = [pytest.mark.integration, pytest.mark.queueproof]

# Claimant threads bound by the same pool-budget ceiling test_concurrency_proof.py
# already documents: the app pool is min_size=1 / max_size=5 / timeout=5s, and each
# barrier-released thread here is a simultaneous connection holder for its own
# claim_job() call.
N_CLAIMANTS = 5

# The blocker Event's own wait timeout must be comfortably LONGER than
# _quiesce_workers' join budget. Otherwise a mutation that removes the blocker-
# release loop from _quiesce_workers can SELF-HEAL: the blocked handler simply times
# out on its own inside the join window, the thread exits, quiescence "succeeds", and
# a later plan's falsifying mutation for this mechanism would be green against the
# bug it exists to catch.
_BLOCKER_WAIT_SECONDS = 30.0
_QUIESCE_JOIN_BUDGET_SECONDS = 5.0
assert _BLOCKER_WAIT_SECONDS > _QUIESCE_JOIN_BUDGET_SECONDS

_COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
_COASTAL_EMAIL = "payroll@coastalcleaning.example"


# ---------------------------------------------------------------------------
# The delete gate: prevents `_isolated_jobs` from deleting beneath a live
# worker. A module-level plain function (not inlined into the fixture) so a
# test can drive it directly.
# ---------------------------------------------------------------------------


def _require_quiesced_workers() -> None:
    """Fail loudly, WITHOUT deleting, if any queue-worker-* thread is alive.

    Called immediately before EACH of `_isolated_jobs`' two DELETEs. A silent
    delete beneath a running worker is exactly the class of thing that makes a
    proof lie rather than fail, and this repo has shipped that class before.
    """
    survivors = live_queue_worker_threads()
    if survivors:
        pytest.fail(
            "a live queue-worker thread survived this test; deleting `jobs` "
            "beneath it would corrupt the proof rather than isolate it. A test "
            "that starts a real worker MUST use the live_worker fixture, whose "
            "teardown quiesces the pool before this fixture runs. Survivors: "
            + ", ".join(f"{t.name} (daemon={t.daemon})" for t in survivors)
        )


def _delete_all_jobs() -> None:
    from app.db import repo

    with repo.get_connection() as conn, conn.transaction():
        conn.execute("DELETE FROM jobs")


@pytest.fixture(autouse=True)
def _isolated_jobs(seeded_db):
    """Empty `jobs` on BOTH sides of every test in this module, gated on
    process quiescence.

    autouse + function-scoped is the whole design, not a style preference: this
    file already holds five-plus live-DB proofs and later plans append more —
    autouse means every one of them gets isolation for free and cannot opt out
    by omission (a fixture you have to remember to request is a fixture a later
    plan forgets). `DELETE`, not `TRUNCATE`: nothing references `jobs`, and
    `TRUNCATE` takes an ACCESS EXCLUSIVE lock, which is a gratuitous hazard in a
    file whose entire purpose is running concurrent claimants. Clearing BEFORE
    the yield protects a test from its predecessors; clearing AFTER protects the
    next test from a crashed one.

    The gate call before EACH delete is what keeps this fixture from being the
    exact mechanism that makes a proof lie: see the module docstring's teardown-
    ordering section for the full failure chain a delete-under-a-live-worker
    produces.
    """
    _require_quiesced_workers()
    _delete_all_jobs()
    yield
    _require_quiesced_workers()
    _delete_all_jobs()


# ---------------------------------------------------------------------------
# live_worker — the ONLY sanctioned way to start a real worker in this module.
# ---------------------------------------------------------------------------


class _LiveWorkerHandle:
    """Handed to a test by the `live_worker` fixture. `blocker()` mints an
    Event the fixture will release on teardown even if the test body never
    gets to; `start(n)` lazily imports `app.queue.worker` (this plan's own
    wave does not have that module yet) and starts n real daemon workers."""

    def __init__(self, blockers: list[threading.Event]) -> None:
        self._blockers = blockers

    def blocker(self) -> threading.Event:
        event = threading.Event()
        self._blockers.append(event)
        return event

    def start(self, n: int = 1) -> None:
        # Lazy import: app.queue.worker does not exist until a later plan.
        import app.queue.worker as worker  # type: ignore[import-not-found]  # noqa: PLC0415

        worker.start(n)


def _quiesce_workers(
    blockers: list[threading.Event], *, grace: float = _QUIESCE_JOIN_BUDGET_SECONDS
) -> None:
    """Release every registered blocker, stop the worker pool, then wait
    (bounded) for zero live queue-worker-* threads. Idempotent — safe even if
    the test already stopped its own worker cleanly. Fails loudly rather than
    letting `_isolated_jobs` proceed to a delete beneath a straggler.
    """
    for event in blockers:
        event.set()
    try:
        from app.queue import worker  # noqa: PLC0415

        worker.stop(grace_seconds=grace)
    except ImportError:
        pass
    # Thread.join(timeout=...) — not a sleep-poll loop. Each survivor gets
    # whatever budget remains of `grace` after the ones joined before it.
    deadline = time.monotonic() + grace
    for thread in live_queue_worker_threads():
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
    survivors = live_queue_worker_threads()
    if survivors:
        pytest.fail(
            "queue worker thread(s) did not quiesce within the join budget: "
            + ", ".join(t.name for t in survivors)
        )


@pytest.fixture
def live_worker(_isolated_jobs):
    """The ONLY sanctioned way to start a real worker in this module. It
    REQUESTS `_isolated_jobs` — that dependency edge, not a comment, is what
    orders quiescence before the delete. pytest sets a requested fixture up
    first and finalizes fixtures in REVERSE setup order, so setup runs
    `_isolated_jobs` -> `live_worker` and teardown runs `live_worker` ->
    `_isolated_jobs`: this fixture's quiesce always completes before
    `_isolated_jobs`' own DELETE, on every path including an aborted test
    body. If a future edit drops `_isolated_jobs` from this signature
    "because it's autouse anyway", that ordering guarantee evaporates while
    both fixtures still appear to run.
    """
    blockers: list[threading.Event] = []
    handle = _LiveWorkerHandle(blockers)
    yield handle
    _quiesce_workers(blockers)


# ---------------------------------------------------------------------------
# The delete gate, proven: behaviorally (it works) and by wiring (it is
# actually installed). Both are needed — a gate that is defined and never
# called is the exact decorative failure this repo has shipped before, and it
# is invisible to a purely behavioral test.
# ---------------------------------------------------------------------------


def test_the_isolation_fixture_refuses_to_delete_beneath_a_live_worker() -> None:
    release = threading.Event()
    sentinel = threading.Thread(
        name=f"{QUEUE_WORKER_THREAD_PREFIX}gate-sentinel",
        target=release.wait,
        daemon=True,
    )
    sentinel.start()
    try:
        assert sentinel in live_queue_worker_threads()
        with pytest.raises(pytest.fail.Exception, match="gate-sentinel"):
            _require_quiesced_workers()
    finally:
        release.set()
        sentinel.join(timeout=5)

    assert not sentinel.is_alive()
    _require_quiesced_workers()  # must now return cleanly


def test_the_delete_gate_runs_on_both_sides_of_the_yield() -> None:
    source = inspect.getsource(_isolated_jobs)
    gate_positions = [m.start() for m in re.finditer(r"_require_quiesced_workers\(\)", source)]
    delete_positions = [m.start() for m in re.finditer(r"_delete_all_jobs\(\)", source)]
    # A bare `yield` STATEMENT, not the word "yield" as it may appear in the
    # docstring's own prose (which discusses the yield) — anchored to a line
    # containing nothing else, so it cannot match an earlier mention.
    yield_match = re.search(r"^\s*yield\s*$", source, re.MULTILINE)
    assert yield_match is not None, "_isolated_jobs has no bare yield statement"
    yield_pos = yield_match.start()

    assert len(gate_positions) >= 2, (
        "_isolated_jobs must call _require_quiesced_workers() on BOTH sides of "
        f"its yield; found {len(gate_positions)} call(s) in its source"
    )
    assert len(delete_positions) >= 2
    assert gate_positions[0] < delete_positions[0] < yield_pos, (
        "the PRE-yield gate call must precede the PRE-yield delete"
    )
    assert yield_pos < gate_positions[-1] < delete_positions[-1], (
        "the POST-yield gate call must precede the POST-yield delete"
    )


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _seed_run_for_queue_proof() -> uuid.UUID:
    """Insert an inbound email + run against the REAL DB (repo.*, no conn=) —
    adapted from tests/test_concurrency_proof.py's own seed helper. Every
    proof in this file needs a real run_id: a run_pipeline job cannot exist
    without one (the database itself refuses it — see the last test below).
    """
    from app.db import repo

    eid, _ = repo.insert_inbound_email(
        message_id=f"<queueproof-{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=_COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular hours.",
    )
    return repo.create_run(business_id=_COASTAL_BIZ_ID, source_email_id=eid)


def _read_reply_epoch(run_id: uuid.UUID) -> int:
    from app.db import repo

    with repo.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT reply_epoch FROM payroll_runs WHERE id = %s", (str(run_id),))
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


# ---------------------------------------------------------------------------
# A genuine N-thread claim race: exactly one winner
# ---------------------------------------------------------------------------


def test_genuine_claim_race_exactly_one_winner(seeded_db) -> None:
    """Enqueue exactly ONE job, hold its id, release N_CLAIMANTS barrier-held
    OS threads calling repo.claim_job() directly. Exactly one must come back
    non-None, and it must be THIS test's own job — never a stranger's."""
    from app.db import repo
    from app.models.job import Job, JobKind

    run_id = _seed_run_for_queue_proof()
    enqueued_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-claim-race:{uuid.uuid4()}",
        run_id=run_id,
    )
    assert enqueued_id is not None

    barrier = threading.Barrier(N_CLAIMANTS, timeout=30)
    results: list[Job | None] = []
    lock = threading.Lock()

    def _claim() -> None:
        barrier.wait()  # release all N_CLAIMANTS threads at the same instant
        job = repo.claim_job()
        with lock:
            results.append(job)

    threads = [threading.Thread(target=_claim) for _ in range(N_CLAIMANTS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == N_CLAIMANTS

    winners = [r for r in results if r is not None]
    losers = [r for r in results if r is None]
    assert len(winners) == 1, (
        f"exactly one of {N_CLAIMANTS} genuinely-concurrent claimants must win "
        f"the SKIP LOCKED race; got {len(winners)} winners"
    )
    assert len(losers) == N_CLAIMANTS - 1

    winner = winners[0]
    assert winner.id == enqueued_id, "the winner must be THIS test's own job"
    assert winner.attempts == 1


# ---------------------------------------------------------------------------
# An expired lease is reclaimed by a genuinely different claim
# ---------------------------------------------------------------------------


def test_expired_lease_is_reclaimed(seeded_db) -> None:
    """No sleeping: the lease is expired by manipulating leased_until
    directly, exercising the exact `leased_until < now()` predicate."""
    from app.db import repo
    from app.models.job import JobKind

    run_id = _seed_run_for_queue_proof()
    enqueued_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-reclaim:{uuid.uuid4()}",
        run_id=run_id,
    )
    assert enqueued_id is not None

    first = repo.claim_job()
    assert first is not None
    assert first.id == enqueued_id
    assert first.attempts == 1
    token_a = first.lease_token

    with repo.get_connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE jobs SET leased_until = now() - interval '1 second' WHERE id = %s",
            (str(enqueued_id),),
        )

    second = repo.claim_job()
    assert second is not None
    assert second.id == enqueued_id
    assert second.attempts == 2
    assert second.lease_token != token_a


# ---------------------------------------------------------------------------
# The zombie is fenced on BOTH write paths
# ---------------------------------------------------------------------------


def test_zombie_is_fenced_on_BOTH_complete_and_fail(seeded_db) -> None:
    """After a reclaim, the ORIGINAL worker's stale token must be rejected by
    BOTH complete_job AND fail_job — not just one. A test that only checks
    complete_job's fence is the exact vacuous twin this file exists to avoid:
    "fail is the fence people forget."""
    from app.db import repo
    from app.models.job import JobKind

    run_id = _seed_run_for_queue_proof()
    enqueued_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-zombie:{uuid.uuid4()}",
        run_id=run_id,
    )
    assert enqueued_id is not None

    first = repo.claim_job()
    assert first is not None
    token_a = first.lease_token

    with repo.get_connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE jobs SET leased_until = now() - interval '1 second' WHERE id = %s",
            (str(enqueued_id),),
        )

    second = repo.claim_job()
    assert second is not None
    token_b = second.lease_token
    assert token_b != token_a

    assert repo.complete_job(enqueued_id, token_a) is False
    assert repo.fail_job(enqueued_id, token_a, error="zombie write", backoff_seconds=1.0) is None

    row = repo.get_job(enqueued_id)
    assert row is not None
    assert row["state"] == "leased", "the row must reflect ONLY worker B's action"
    assert row["lease_token"] == token_b


# ---------------------------------------------------------------------------
# The repo half of graceful release: release_leases returns a row to pending immediately
# ---------------------------------------------------------------------------


def test_release_leases_returns_the_row_to_pending_immediately(seeded_db) -> None:
    from app.db import repo
    from app.models.job import JobKind

    run_id = _seed_run_for_queue_proof()
    enqueued_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-release:{uuid.uuid4()}",
        run_id=run_id,
    )
    assert enqueued_id is not None

    claimed = repo.claim_job()
    assert claimed is not None
    assert claimed.id == enqueued_id

    count = repo.release_leases([claimed.lease_token])
    assert count == 1

    row = repo.get_job(enqueued_id)
    assert row is not None
    assert row["state"] == "pending"
    assert row["lease_token"] is None
    assert row["leased_until"] is None


# ---------------------------------------------------------------------------
# The database-level refusal — deliberately bypasses enqueue_job
# ---------------------------------------------------------------------------


def test_the_database_refuses_a_run_pipeline_job_with_a_null_run_id(seeded_db) -> None:
    """Bypass enqueue_job entirely and issue the raw INSERT: the CHECK
    constraint is the guarantee that holds against every future caller, not
    only against enqueue_job's own signature. enqueue_job's ValueError would
    mask this if it were exercised instead — the bypass is the whole point.
    """
    from app.db import repo

    with (
        pytest.raises(psycopg.errors.CheckViolation) as excinfo,  # noqa: PT011
        repo.get_connection() as conn,
        conn.transaction(),
    ):
        conn.execute(
            "INSERT INTO jobs (kind, dedup_key, run_id) VALUES (%s, %s, NULL)",
            ("run_pipeline", f"queueproof-null-run:{uuid.uuid4()}"),
        )
    assert "ck_jobs_run_pipeline_requires_run" in str(excinfo.value)


# ---------------------------------------------------------------------------
# The epoch-stability assertion — the reason rewind_for_reclaim exists at all
# ---------------------------------------------------------------------------


def test_rewind_for_reclaim_leaves_reply_epoch_untouched(seeded_db) -> None:
    """rewind_for_reclaim must move a stranded run back to RECEIVED and clear
    its reply-round context WITHOUT bumping reply_epoch — that bump is a
    licence to email the client again, and only a deliberate human retrigger
    is allowed to grant it. Falsifying mutation: add the bump to
    rewind_for_reclaim's UPDATE; this assertion must go red.
    """
    from app.db import repo
    from app.models.status import RunStatus

    run_id = _seed_run_for_queue_proof()
    repo.set_status(run_id, RunStatus.EXTRACTING)
    before_epoch = _read_reply_epoch(run_id)

    rewound = repo.rewind_for_reclaim(run_id)
    assert rewound is True

    after = repo.load_run(run_id)
    assert after is not None
    assert after["status"] == "received"
    assert _read_reply_epoch(run_id) == before_epoch
    assert repo.load_clarified_fields(run_id) == {}
    assert repo.load_pre_clarify_extracted(run_id) is None
