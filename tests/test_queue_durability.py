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

import ast
import inspect
import pathlib
import re
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
import resend

from app.models.job import Job
from app.models.status import RunStatus
from app.pipeline.result import (
    PipelineOutcome,
    PipelineReason,
    PipelineResult,
    PipelineStage,
)
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
_METRO_BIZ_ID = uuid.UUID("b0000002-0000-0000-0000-000000000002")
_METRO_EMAIL = "hr@metrodeli.example"


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
    gets to; `start(n)` starts n real daemon workers via `app.queue.worker`."""

    def __init__(self, blockers: list[threading.Event]) -> None:
        self._blockers = blockers

    def blocker(self) -> threading.Event:
        event = threading.Event()
        self._blockers.append(event)
        return event

    def start(self, n: int = 1) -> None:
        from app.queue import worker  # noqa: PLC0415 — deferred alongside
        # _quiesce_workers' own deferred import of the same module below

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


def _seed_run_for_queue_proof(
    *,
    business_id: uuid.UUID = _COASTAL_BIZ_ID,
    from_addr: str = _COASTAL_EMAIL,
) -> uuid.UUID:
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
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular hours.",
    )
    return repo.create_run(business_id=business_id, source_email_id=eid)


def _read_reply_epoch(run_id: uuid.UUID) -> int:
    from app.db import repo

    with repo.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT reply_epoch FROM payroll_runs WHERE id = %s", (str(run_id),))
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _first_coastal_employee_id() -> uuid.UUID:
    from app.db import repo

    with repo.get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM employees WHERE business_id = %s ORDER BY id LIMIT 1",
            (str(_COASTAL_BIZ_ID),),
        ).fetchone()
    assert row is not None
    return uuid.UUID(str(row[0]))


# ---------------------------------------------------------------------------
# Classified settlement and operator retry atomicity
# ---------------------------------------------------------------------------


def test_settlement_retry_exhaustion_and_terminal_result_are_atomic(seeded_db) -> None:
    from app.db import repo
    from app.db.repo.job_settlement import SettlementOutcome
    from app.models.job import JobKind
    from app.models.status import RunStatus
    from app.pipeline.result import (
        PipelineOutcome,
        PipelineReason,
        PipelineResult,
        PipelineStage,
    )

    retryable = PipelineResult(
        outcome=PipelineOutcome.RETRYABLE,
        stage=PipelineStage.EXTRACT,
        reason=PipelineReason.PROVIDER_TIMEOUT,
    )
    run_id = _seed_run_for_queue_proof()
    repo.set_status(run_id, RunStatus.EXTRACTING)
    job_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-settlement-retry:{uuid.uuid4()}",
        run_id=run_id,
    )
    assert job_id is not None
    job = repo.claim_job()
    assert job is not None and job.id == job_id
    assert repo.settle_pipeline_job(
        job, retryable, backoff_seconds=5.0
    ) is SettlementOutcome.RETRIED
    retry_job_row = repo.get_job(job_id)
    retry_run_row = repo.load_run(run_id)
    assert retry_job_row is not None
    assert retry_run_row is not None
    assert retry_job_row["state"] == "pending"
    assert retry_run_row["status"] == RunStatus.RECEIVED.value
    assert retry_run_row["error_reason"] is None

    exhausted_run = _seed_run_for_queue_proof()
    repo.set_status(exhausted_run, RunStatus.EXTRACTING)
    exhausted_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-settlement-exhaustion:{uuid.uuid4()}",
        run_id=exhausted_run,
        max_attempts=1,
    )
    assert exhausted_id is not None
    exhausted = repo.claim_job()
    assert exhausted is not None and exhausted.id == exhausted_id
    assert repo.settle_pipeline_job(
        exhausted, retryable, backoff_seconds=5.0
    ) is SettlementOutcome.DEAD
    exhausted_job_row = repo.get_job(exhausted_id)
    assert exhausted_job_row is not None
    assert exhausted_job_row["state"] == "dead"
    exhausted_row = repo.load_run(exhausted_run)
    assert exhausted_row is not None
    assert exhausted_row["status"] == RunStatus.ERROR.value
    assert exhausted_row["error_reason"] == "RetryExhausted"
    assert "1/1" in exhausted_row["error_detail"]

    terminal_run = _seed_run_for_queue_proof()
    repo.set_status(terminal_run, RunStatus.EXTRACTING)
    terminal_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-terminal-result:{uuid.uuid4()}",
        run_id=terminal_run,
    )
    assert terminal_id is not None
    terminal_job = repo.claim_job()
    assert terminal_job is not None and terminal_job.id == terminal_id
    terminal = PipelineResult(
        outcome=PipelineOutcome.TERMINAL,
        stage=PipelineStage.COMPUTE,
        reason=PipelineReason.UNCLASSIFIED,
    )
    assert repo.settle_pipeline_job(
        terminal_job, terminal, backoff_seconds=5.0
    ) is SettlementOutcome.DONE
    terminal_job_row = repo.get_job(terminal_id)
    terminal_run_row = repo.load_run(terminal_run)
    assert terminal_job_row is not None
    assert terminal_run_row is not None
    assert terminal_job_row["state"] == "done"
    assert terminal_run_row["status"] == RunStatus.ERROR.value


def test_outbound_delivery_settlement_proves_retry_cutoff_and_zombie_fence(
    seeded_db,
) -> None:
    """A configured database proves one reservation never grows a replacement send job."""
    from app.db import repo
    from app.db.repo.job_settlement import SettlementOutcome
    from app.models.job import JobKind

    retryable = PipelineResult(
        outcome=PipelineOutcome.RETRYABLE,
        stage=PipelineStage.DELIVERY,
        reason=PipelineReason.DELIVERY_TIMEOUT,
    )
    run_id = _seed_run_for_queue_proof()
    repo.set_status(run_id, RunStatus.APPROVED)
    snapshot = repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id=f"<delivery-retry-{uuid.uuid4()}@test.example>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@coastalcleaning.example",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Payroll confirmation",
        body_text="Delivery proof",
        attachments=(),
    )
    job_id = repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=repo.send_outbound_dedup_key(snapshot["email_id"]),
        run_id=run_id,
        email_id=snapshot["email_id"],
    )
    assert job_id is not None
    claimed = repo.claim_job()
    assert claimed is not None and claimed.id == job_id
    assert repo.settle_outbound_delivery_job(claimed, retryable) is SettlementOutcome.RETRIED
    assert repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=repo.send_outbound_dedup_key(snapshot["email_id"]),
        run_id=run_id,
        email_id=snapshot["email_id"],
    ) is None
    retry_row = repo.get_job(job_id)
    retry_run = repo.load_run(run_id)
    assert retry_row is not None and retry_row["state"] == "pending"
    assert retry_run is not None and retry_run["status"] == RunStatus.APPROVED.value

    with repo.get_connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE jobs SET state = 'leased', lease_token = %s, leased_until = now() "
            "WHERE id = %s",
            (str(uuid.uuid4()), str(job_id)),
        )
    with repo.get_connection() as conn:
        attempts_before_row = conn.execute(
            "SELECT count(*) FROM outbound_delivery_attempts WHERE snapshot_id = %s",
            (str(snapshot["snapshot_id"]),),
        ).fetchone()
    assert attempts_before_row is not None
    attempts_before = attempts_before_row[0]
    assert (
        repo.settle_outbound_delivery_job(claimed, retryable)
        is SettlementOutcome.LOST_LEASE
    )
    with repo.get_connection() as conn:
        attempts_after_row = conn.execute(
            "SELECT count(*) FROM outbound_delivery_attempts WHERE snapshot_id = %s",
            (str(snapshot["snapshot_id"]),),
        ).fetchone()
    assert attempts_after_row is not None
    attempts_after = attempts_after_row[0]
    assert attempts_after == attempts_before

    cutoff_run = _seed_run_for_queue_proof()
    repo.set_status(cutoff_run, RunStatus.APPROVED)
    with repo.get_connection() as conn, conn.transaction():
        email_row = conn.execute(
            "INSERT INTO email_messages "
            "(run_id, direction, message_id, subject, from_addr, to_addr, body_text, "
            "purpose, send_state, round, epoch) "
            "VALUES (%s, 'outbound', %s, 'Payroll confirmation', "
            "'agent@payroll-agent.local', 'payroll@coastalcleaning.example', "
            "'Delivery proof', 'confirmation', 'reserved', 0, 0) RETURNING id",
            (str(cutoff_run), f"<delivery-cutoff-{uuid.uuid4()}@test.example>"),
        ).fetchone()
        assert email_row is not None
        cutoff_email_id = email_row[0]
        snapshot_row = conn.execute(
            "INSERT INTO outbound_email_snapshots "
            "(email_id, message_id, from_addr, to_addr, subject, body_text, reserved_at) "
            "VALUES (%s, %s, 'agent@payroll-agent.local', "
            "'payroll@coastalcleaning.example', 'Payroll confirmation', "
            "'Delivery proof', now() - interval '20 hours') RETURNING id",
            (str(cutoff_email_id), f"<delivery-cutoff-{uuid.uuid4()}@test.example>"),
        ).fetchone()
        assert snapshot_row is not None
    cutoff_job_id = repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=repo.send_outbound_dedup_key(cutoff_email_id),
        run_id=cutoff_run,
        email_id=cutoff_email_id,
    )
    assert cutoff_job_id is not None
    cutoff_job = repo.claim_job()
    assert cutoff_job is not None and cutoff_job.id == cutoff_job_id
    assert repo.settle_outbound_delivery_job(cutoff_job, retryable) is SettlementOutcome.DONE
    cutoff_row = repo.get_job(cutoff_job_id)
    cutoff_run_row = repo.load_run(cutoff_run)
    assert cutoff_row is not None and cutoff_row["state"] == "done"
    assert cutoff_run_row is not None and cutoff_run_row["status"] == RunStatus.NEEDS_OPERATOR.value


@pytest.mark.integration
@pytest.mark.queueproof
@pytest.mark.parametrize(
    ("purpose", "run_status", "review_reason"),
    [
        ("confirmation", RunStatus.APPROVED, "DeliveryReview"),
        ("clarification", RunStatus.AWAITING_REPLY, "ClarificationDeliveryReview"),
        (
            "clarification_field_regression",
            RunStatus.AWAITING_REPLY,
            "ClarificationDeliveryReview",
        ),
    ],
)
def test_final_send_lease_reap_preserves_snapshot_and_enters_purpose_review(
    seeded_db,
    purpose: str,
    run_status: RunStatus,
    review_reason: str,
) -> None:
    """A crash after provider acceptance cannot become generic recovery."""
    from app.db import repo
    from app.db.repo.job_settlement import SettlementOutcome
    from app.models.job import JobKind

    run_id = _seed_run_for_queue_proof()
    repo.set_status(run_id, run_status)
    original_message_id = f"<final-lease-{purpose}-{uuid.uuid4()}@test.example>"
    snapshot = repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose=purpose,
        round=0,
        message_id=original_message_id,
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@coastalcleaning.example",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Payroll delivery review",
        body_text="Frozen delivery content",
        attachments=(),
    )
    job_id = repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=repo.send_outbound_dedup_key(snapshot["email_id"]),
        run_id=run_id,
        email_id=snapshot["email_id"],
    )
    assert job_id is not None
    claimed = repo.claim_job()
    assert claimed is not None and claimed.id == job_id
    with repo.get_connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE jobs SET attempts = max_attempts, "
            "leased_until = now() - interval '60 seconds' "
            "WHERE id = %s",
            (str(job_id),),
        )

    assert repo.reap_expired_final_attempt() is SettlementOutcome.REAPED_FINAL_LEASE
    run = repo.load_run(run_id)
    job = repo.get_job(job_id)
    frozen = repo.load_outbound_snapshot(run_id, snapshot["email_id"])
    assert run is not None
    assert job is not None
    assert frozen is not None
    assert run["status"] == RunStatus.NEEDS_OPERATOR.value
    assert run["error_reason"] == review_reason
    assert run["error_detail"] == "delivery_review:final_attempt_lease_expired"
    assert job["state"] == "dead"
    assert frozen["message_id"] == original_message_id
    assert frozen["body_text"] == "Frozen delivery content"
    with repo.get_connection() as conn:
        attempt = conn.execute(
            "SELECT attempt_state, failure_category "
            "FROM outbound_delivery_attempts WHERE snapshot_id = %s",
            (str(snapshot["snapshot_id"]),),
        ).fetchone()
        open_jobs = conn.execute(
            "SELECT count(*) FROM jobs WHERE run_id = %s "
            "AND state IN ('pending', 'leased')",
            (str(run_id),),
        ).fetchone()
    assert attempt == ("needs_operator", "final_attempt_lease_expired")
    assert open_jobs == (0,)


def test_send_handler_noops_before_gateway_for_stale_epoch(
    seeded_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-retrigger send job cannot call the provider for the new epoch."""
    from app.db import repo
    from app.models.job import JobKind
    from app.queue.handlers import send_outbound

    run_id = _seed_run_for_queue_proof()
    repo.set_status(run_id, RunStatus.APPROVED)
    old_snapshot = repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id=f"<stale-handler-{uuid.uuid4()}@test.example>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@coastalcleaning.example",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Old confirmation",
        body_text="Old frozen body",
        attachments=(),
    )
    old_job_id = repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=repo.send_outbound_dedup_key(old_snapshot["email_id"]),
        run_id=run_id,
        email_id=old_snapshot["email_id"],
    )
    assert old_job_id is not None
    old_job = repo.claim_job()
    assert old_job is not None and old_job.id == old_job_id

    assert repo.clear_reply_context(run_id) == 1
    current_snapshot = repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id=f"<current-handler-{uuid.uuid4()}@test.example>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@coastalcleaning.example",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Current confirmation",
        body_text="Current frozen body",
        attachments=(),
    )

    provider_calls: list[dict[str, object]] = []

    def provider_spy(snapshot: dict[str, object]) -> PipelineResult:
        provider_calls.append(snapshot)
        return PipelineResult(outcome=PipelineOutcome.OK)

    from app.email import gateway

    monkeypatch.setattr(
        gateway,
        "send_reserved_outbound_snapshot",
        provider_spy,
    )

    result = send_outbound.handle_send_outbound(old_job)

    assert result.outcome is PipelineOutcome.OK
    assert provider_calls == [], "stale work must stop before the provider call"
    assert current_snapshot["message_id"] != old_snapshot["message_id"]


def test_invalid_context_stale_epoch_retirement_after_epoch_fence(
    seeded_db,
) -> None:
    """Epoch fencing retires only the obsolete leased send row."""
    from app.db import repo
    from app.db.repo.job_settlement import SettlementOutcome
    from app.models.job import JobKind

    run_id = _seed_run_for_queue_proof()
    repo.set_status(run_id, RunStatus.APPROVED)
    old_snapshot = repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id=f"<stale-settlement-{uuid.uuid4()}@test.example>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@coastalcleaning.example",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Old confirmation",
        body_text="Old frozen body",
        attachments=(),
    )
    old_job_id = repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=repo.send_outbound_dedup_key(old_snapshot["email_id"]),
        run_id=run_id,
        email_id=old_snapshot["email_id"],
    )
    assert old_job_id is not None
    old_job = repo.claim_job()
    assert old_job is not None and old_job.id == old_job_id

    assert repo.clear_reply_context(run_id) == 1
    current_snapshot = repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id=f"<current-settlement-{uuid.uuid4()}@test.example>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@coastalcleaning.example",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Current confirmation",
        body_text="Current frozen body",
        attachments=(),
    )

    before = repo.load_run(run_id)
    assert before is not None
    assert repo.settle_outbound_delivery_job(
        old_job, PipelineResult(outcome=PipelineOutcome.OK)
    ) is SettlementOutcome.INVALID_CONTEXT

    with repo.get_connection() as conn:
        old_state = conn.execute(
            "SELECT send_state FROM email_messages WHERE id = %s",
            (str(old_snapshot["email_id"]),),
        ).fetchone()
        current_state = conn.execute(
            "SELECT send_state FROM email_messages WHERE id = %s",
            (str(current_snapshot["email_id"]),),
        ).fetchone()
        old_attempts = conn.execute(
            "SELECT count(*) FROM outbound_delivery_attempts WHERE snapshot_id = %s",
            (str(old_snapshot["snapshot_id"]),),
        ).fetchone()
        current_attempts = conn.execute(
            "SELECT count(*) FROM outbound_delivery_attempts WHERE snapshot_id = %s",
            (str(current_snapshot["snapshot_id"]),),
        ).fetchone()
    after = repo.load_run(run_id)

    assert old_state == ("reserved",)
    assert current_state == ("reserved",)
    assert old_attempts == (0,)
    assert current_attempts == (0,)
    assert after == before
    old_job_row = repo.get_job(old_job.id)
    assert old_job_row is not None
    assert old_job_row["state"] == "done"
    assert old_job_row["lease_token"] is None
    assert old_job_row["leased_until"] is None
    assert old_job_row["last_error"] == "delivery:invalid_context"


def test_invalid_context_settlement_retires_exact_leased_row(fake_conn) -> None:
    """An owned but invalid SEND_OUTBOUND lease is retired by its exact token."""
    from app.db.repo import job_settlement
    from app.models.job import Job, JobKind

    job = Job(
        id=uuid.uuid4(),
        kind=JobKind.SEND_OUTBOUND,
        run_id=uuid.uuid4(),
        email_id=uuid.uuid4(),
        attempts=1,
        max_attempts=5,
        lease_token=uuid.uuid4(),
    )
    fake_conn.script_fetchone(
        (1, 5, job.run_id, JobKind.SEND_OUTBOUND.value, job.email_id)
    )
    fake_conn.script_fetchone(
        (uuid.uuid4(), datetime.now(UTC), "not-an-outbound-purpose", 0, "reserved", True)
    )
    fake_conn.script_fetchone((job.id,))

    assert job_settlement.settle_outbound_delivery_job(
        job, PipelineResult(outcome=PipelineOutcome.OK), conn=fake_conn
    ) is job_settlement.SettlementOutcome.INVALID_CONTEXT

    retirement_sql, retirement_params = fake_conn.last()
    assert "UPDATE jobs SET state = %s, last_error = %s, lease_token = NULL" in str(
        retirement_sql
    )
    assert "AND state = 'leased' AND lease_token = %s" in str(retirement_sql)
    assert retirement_params == (
        "done",
        "delivery:invalid_context",
        str(job.id),
        str(job.lease_token),
    )
    assert "outbound_delivery_attempts" not in fake_conn.all_sql()
    assert "UPDATE payroll_runs" not in fake_conn.all_sql()


def test_final_send_lease_retires_stale_epoch_without_current_review_mutation(
    seeded_db,
) -> None:
    """The final-lease reaper cannot review an old epoch as current delivery."""
    from app.db import repo
    from app.db.repo.job_settlement import SettlementOutcome
    from app.models.job import JobKind

    run_id = _seed_run_for_queue_proof()
    repo.set_status(run_id, RunStatus.APPROVED)
    old_snapshot = repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id=f"<stale-reaper-{uuid.uuid4()}@test.example>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@coastalcleaning.example",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Old confirmation",
        body_text="Old frozen body",
        attachments=(),
    )
    old_job_id = repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=repo.send_outbound_dedup_key(old_snapshot["email_id"]),
        run_id=run_id,
        email_id=old_snapshot["email_id"],
    )
    assert old_job_id is not None
    old_job = repo.claim_job()
    assert old_job is not None and old_job.id == old_job_id

    assert repo.clear_reply_context(run_id) == 1
    current_snapshot = repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id=f"<current-reaper-{uuid.uuid4()}@test.example>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@coastalcleaning.example",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Current confirmation",
        body_text="Current frozen body",
        attachments=(),
    )
    with repo.get_connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE jobs SET attempts = max_attempts, "
            "leased_until = now() - interval '60 seconds' "
            "WHERE id = %s",
            (str(old_job.id),),
        )

    before = repo.load_run(run_id)
    assert before is not None
    assert repo.reap_expired_final_attempt() is SettlementOutcome.INVALID_CONTEXT

    with repo.get_connection() as conn:
        old_state = conn.execute(
            "SELECT send_state FROM email_messages WHERE id = %s",
            (str(old_snapshot["email_id"]),),
        ).fetchone()
        current_state = conn.execute(
            "SELECT send_state FROM email_messages WHERE id = %s",
            (str(current_snapshot["email_id"]),),
        ).fetchone()
        attempts = conn.execute(
            "SELECT count(*) FROM outbound_delivery_attempts "
            "WHERE snapshot_id = %s OR snapshot_id = %s",
            (str(old_snapshot["snapshot_id"]), str(current_snapshot["snapshot_id"])),
        ).fetchone()
    after = repo.load_run(run_id)

    assert old_state == ("reserved",)
    assert current_state == ("reserved",)
    assert attempts == (0,)
    assert after == before
    old_job_row = repo.get_job(old_job.id)
    assert old_job_row is not None
    assert old_job_row["state"] == "dead"
    assert old_job_row["lease_token"] is None
    assert old_job_row["leased_until"] is None
    assert old_job_row["last_error"] == "delivery:invalid_context"


def _payroll_status_snapshot() -> list[tuple[object, ...]]:
    from app.db import repo

    with repo.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, status, error_reason, error_detail"
            " FROM payroll_runs ORDER BY id"
        ).fetchall()
    return [tuple(row) for row in rows]


def _claim_live_ingest_job(*, max_attempts: int):
    from app.db import repo
    from app.models.job import JobKind

    event_id, inserted = repo.insert_or_get_inbound_event(
        external_event_id=f"queueproof-ingest-settlement:{uuid.uuid4()}",
        payload={"type": "email.received", "data": {"email_id": "fixture"}},
    )
    assert inserted
    job_id = repo.enqueue_job(
        kind=JobKind.INGEST,
        dedup_key=f"ingest:{event_id}",
        event_id=event_id,
        max_attempts=max_attempts,
    )
    assert job_id is not None
    claimed = repo.claim_job()
    assert claimed is not None and claimed.id == job_id
    assert claimed.run_id is None and claimed.event_id == event_id
    return claimed


@pytest.mark.parametrize(
    ("result", "max_attempts", "expected_outcome", "expected_state"),
    [
        (PipelineResult(outcome=PipelineOutcome.OK), 5, "done", "done"),
        (
            PipelineResult(
                outcome=PipelineOutcome.RETRYABLE,
                stage=PipelineStage.LOAD,
                reason=PipelineReason.PROVIDER_TIMEOUT,
            ),
            5,
            "retried",
            "pending",
        ),
        (
            PipelineResult(
                outcome=PipelineOutcome.RETRYABLE,
                stage=PipelineStage.LOAD,
                reason=PipelineReason.PROVIDER_TIMEOUT,
            ),
            1,
            "dead",
            "dead",
        ),
        (
            PipelineResult(
                outcome=PipelineOutcome.TERMINAL,
                stage=PipelineStage.LOAD,
                reason=PipelineReason.CLIENT_REQUEST_FAILURE,
            ),
            5,
            "done",
            "done",
        ),
    ],
)
def test_null_run_ingest_settlement_does_not_write_payroll_status(
    seeded_db,
    result: PipelineResult,
    max_attempts: int,
    expected_outcome: str,
    expected_state: str,
) -> None:
    from app.db import repo
    from app.db.repo.job_settlement import SettlementOutcome

    before = _payroll_status_snapshot()
    claimed = _claim_live_ingest_job(max_attempts=max_attempts)
    outcome = repo.settle_pipeline_job(
        claimed,
        result,
        backoff_seconds=5.0,
    )
    row = repo.get_job(claimed.id)
    assert outcome is SettlementOutcome(expected_outcome)
    assert row is not None and row["state"] == expected_state
    assert row["lease_token"] is None
    assert _payroll_status_snapshot() == before


def test_null_run_ingest_final_attempt_reap_clears_lease_without_payroll_write(
    seeded_db,
) -> None:
    from app.db import repo
    from app.db.repo.job_settlement import SettlementOutcome

    claimed = _claim_live_ingest_job(max_attempts=1)
    with repo.get_connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE jobs SET leased_until = now() - interval '60 seconds',"
            " last_error = %s WHERE id = %s",
            ("ingest:provider_timeout", str(claimed.id)),
        )
    before = _payroll_status_snapshot()

    assert repo.reap_expired_final_attempt() is SettlementOutcome.REAPED_FINAL_LEASE
    row = repo.get_job(claimed.id)
    assert row is not None
    assert row["state"] == "dead"
    assert row["lease_token"] is None
    assert row["leased_until"] is None
    assert row["last_error"] == "ingest:provider_timeout"
    assert _payroll_status_snapshot() == before


@pytest.mark.parametrize("status", list(RunStatus))
def test_final_attempt_reap_status_matrix(
    seeded_db, status: RunStatus
) -> None:
    from app.db import repo
    from app.db.repo.job_settlement import SettlementOutcome
    from app.models.job import JobKind
    from app.models.status import RunStatus

    error_statuses = {
        RunStatus.RECEIVED,
        RunStatus.EXTRACTING,
        RunStatus.COMPUTED,
        RunStatus.APPROVED,
    }
    run_id = _seed_run_for_queue_proof()
    repo.set_status(run_id, status)
    with repo.get_connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE payroll_runs SET error_reason = %s, error_detail = %s"
            " WHERE id = %s",
            ("existing_reason", "existing_detail", str(run_id)),
        )
    job_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-final-matrix:{status.value}:{uuid.uuid4()}",
        run_id=run_id,
        max_attempts=1,
    )
    assert job_id is not None
    claimed = repo.claim_job()
    assert claimed is not None and claimed.id == job_id
    with repo.get_connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE jobs SET leased_until = now() - interval '60 seconds',"
            " last_error = %s WHERE id = %s",
            ("extract:provider_timeout", str(job_id)),
        )

    assert repo.reap_expired_final_attempt() is SettlementOutcome.REAPED_FINAL_LEASE
    job_row = repo.get_job(job_id)
    run_row = repo.load_run(run_id)
    assert job_row is not None
    assert run_row is not None
    assert job_row["state"] == "dead"
    assert job_row["lease_token"] is None
    assert job_row["leased_until"] is None
    assert job_row["last_error"] == "extract:provider_timeout"
    if status in error_statuses:
        assert run_row["status"] == RunStatus.ERROR.value
        assert run_row["error_reason"] == "FinalAttemptLeaseExpired"
        assert run_row["error_detail"] == (
            "unknown:final_attempt_lease_expired;attempts=1/1"
        )
    else:
        assert run_row["status"] == status.value
        assert run_row["error_reason"] == "existing_reason"
        assert run_row["error_detail"] == "existing_detail"


def test_final_attempt_reap_preserved_oldest_allows_second_candidate(
    seeded_db,
) -> None:
    from app.db import repo
    from app.db.repo.job_settlement import SettlementOutcome
    from app.models.job import JobKind
    from app.models.status import RunStatus

    candidates: list[tuple[uuid.UUID, uuid.UUID]] = []
    for status, lease_age in (
        (RunStatus.AWAITING_APPROVAL, 120),
        (RunStatus.EXTRACTING, 60),
    ):
        run_id = _seed_run_for_queue_proof()
        repo.set_status(run_id, status)
        job_id = repo.enqueue_job(
            kind=JobKind.RUN_PIPELINE,
            dedup_key=f"queueproof-final-starvation:{status.value}:{uuid.uuid4()}",
            run_id=run_id,
            max_attempts=1,
        )
        assert job_id is not None
        claimed = repo.claim_job()
        assert claimed is not None and claimed.id == job_id
        with repo.get_connection() as conn, conn.transaction():
            conn.execute(
                "UPDATE jobs SET leased_until = now() - (%s || ' seconds')::interval,"
                " last_error = %s WHERE id = %s",
                (lease_age, f"attempt-{lease_age}", str(job_id)),
            )
        candidates.append((run_id, job_id))

    assert repo.reap_expired_final_attempt() is SettlementOutcome.REAPED_FINAL_LEASE
    first_run = repo.load_run(candidates[0][0])
    first_job = repo.get_job(candidates[0][1])
    second_job = repo.get_job(candidates[1][1])
    assert first_run is not None
    assert first_job is not None
    assert second_job is not None
    assert first_run["status"] == RunStatus.AWAITING_APPROVAL.value
    assert first_job["state"] == "dead"
    assert second_job["state"] == "leased"

    assert repo.reap_expired_final_attempt() is SettlementOutcome.REAPED_FINAL_LEASE
    second_run = repo.load_run(candidates[1][0])
    second_job = repo.get_job(candidates[1][1])
    assert second_run is not None
    assert second_job is not None
    assert second_run["status"] == RunStatus.ERROR.value
    assert second_job["state"] == "dead"
    assert repo.reap_expired_final_attempt() is None


def test_final_attempt_reap_exact_predicate_and_rollback(
    seeded_db, monkeypatch
) -> None:
    from app.db import repo
    from app.db.repo import job_settlement
    from app.models.job import JobKind
    from app.models.status import RunStatus

    def _leased_job(*, max_attempts: int, expired: bool) -> tuple[uuid.UUID, uuid.UUID]:
        run_id = _seed_run_for_queue_proof()
        repo.set_status(run_id, RunStatus.EXTRACTING)
        job_id = repo.enqueue_job(
            kind=JobKind.RUN_PIPELINE,
            dedup_key=f"queueproof-final-predicate:{uuid.uuid4()}",
            run_id=run_id,
            max_attempts=max_attempts,
        )
        assert job_id is not None
        claimed = repo.claim_job()
        assert claimed is not None and claimed.id == job_id
        with repo.get_connection() as conn, conn.transaction():
            conn.execute(
                "UPDATE jobs SET leased_until = now() + (%s || ' seconds')::interval,"
                " last_error = %s WHERE id = %s",
                (-60 if expired else 60, "extract:provider_timeout", str(job_id)),
            )
        return run_id, job_id

    unexpired_run, unexpired_job = _leased_job(max_attempts=1, expired=False)
    below_run, below_job = _leased_job(max_attempts=2, expired=True)
    assert repo.reap_expired_final_attempt() is None
    for run_id, job_id in (
        (unexpired_run, unexpired_job),
        (below_run, below_job),
    ):
        run_row = repo.load_run(run_id)
        job_row = repo.get_job(job_id)
        assert run_row is not None and run_row["status"] == RunStatus.EXTRACTING.value
        assert job_row is not None and job_row["state"] == "leased"
    with repo.get_connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE jobs SET leased_until = now() + interval '60 seconds' WHERE id = %s",
            (str(below_job),),
        )

    rollback_run, rollback_job = _leased_job(max_attempts=1, expired=True)
    original_set_run_error = job_settlement._set_run_error

    def _raise_after_run_write(*args, **kwargs):
        assert original_set_run_error(*args, **kwargs)
        raise RuntimeError("injected reap half-failure")

    monkeypatch.setattr(job_settlement, "_set_run_error", _raise_after_run_write)
    with pytest.raises(RuntimeError, match="injected reap half-failure"):
        repo.reap_expired_final_attempt()
    rollback_job_row = repo.get_job(rollback_job)
    rollback_run_row = repo.load_run(rollback_run)
    assert rollback_job_row is not None
    assert rollback_run_row is not None
    assert rollback_job_row["state"] == "leased"
    assert rollback_run_row["status"] == RunStatus.EXTRACTING.value


def test_pump_reaps_expired_final_attempt_once(
    seeded_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real HTTP pump reports one exact final-lease reap exactly once."""
    from fastapi.testclient import TestClient

    import app.main as app_main
    from app.config import get_settings
    from app.db import repo
    from app.models.job import JobKind
    from app.models.status import RunStatus

    token = f"queueproof-reap-token-{uuid.uuid4()}"
    monkeypatch.setenv("PUMP_TOKEN", token)
    get_settings.cache_clear()
    try:
        run_id = _seed_run_for_queue_proof()
        repo.set_status(run_id, RunStatus.EXTRACTING)
        job_id = repo.enqueue_job(
            kind=JobKind.RUN_PIPELINE,
            dedup_key=f"queueproof-pump-reap:{uuid.uuid4()}",
            run_id=run_id,
            max_attempts=1,
        )
        assert job_id is not None
        claimed = repo.claim_job()
        assert claimed is not None and claimed.id == job_id
        assert claimed.attempts == claimed.max_attempts == 1

        with repo.get_connection() as conn, conn.transaction():
            conn.execute(
                "UPDATE jobs SET leased_until = now() - interval '1 second',"
                " last_error = %s WHERE id = %s",
                ("extract:provider_timeout", str(job_id)),
            )

        assert live_queue_worker_threads() == []
        client = TestClient(app_main.app)
        response = client.get(
            "/internal/pump", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200, response.text
        assert response.json() == {
            "claimed": 0,
            "done": 0,
            "retried": 0,
            "dead": 1,
            "fenced": 0,
            "reaped_final_lease": 1,
            "queue_depth": 0,
        }

        job_row = repo.get_job(job_id)
        run_row = repo.load_run(run_id)
        assert job_row is not None and job_row["state"] == "dead"
        assert run_row is not None and run_row["status"] == RunStatus.ERROR.value
        assert run_row["error_reason"] == "FinalAttemptLeaseExpired"

        second = client.get(
            "/internal/pump", headers={"Authorization": f"Bearer {token}"}
        )
        assert second.status_code == 200, second.text
        assert second.json() == {
            "claimed": 0,
            "done": 0,
            "retried": 0,
            "dead": 0,
            "fenced": 0,
            "reaped_final_lease": 0,
            "queue_depth": 0,
        }
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("reply_business_id", "reply_from_addr"),
    [
        (_COASTAL_BIZ_ID, _COASTAL_EMAIL),
        (_METRO_BIZ_ID, _METRO_EMAIL),
    ],
    ids=("same-business-wrong-run", "cross-business"),
)
def test_resume_reply_association_returns_bounded_noop_for_real_wrong_run(
    seeded_db,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    reply_business_id: uuid.UUID,
    reply_from_addr: str,
) -> None:
    from app.db import repo
    from app.models.job import Job, JobKind
    from app.pipeline import orchestrator
    from app.pipeline.result import PipelineOutcome
    from app.queue.handlers import resume_reply

    job_run_id = _seed_run_for_queue_proof()
    reply_run_id = _seed_run_for_queue_proof(
        business_id=reply_business_id,
        from_addr=reply_from_addr,
    )
    reply_email_id, inserted = repo.insert_inbound_email(
        message_id=f"<queueproof-secret-{uuid.uuid4()}@test.example>",
        in_reply_to="<queueproof-clarification@test.example>",
        references_header="<queueproof-clarification@test.example>",
        subject="SECRET ASSOCIATION SUBJECT",
        from_addr=reply_from_addr,
        to_addr="secret-recipient@example.test",
        body_text="SECRET ASSOCIATION BODY Maria Chen payroll",
    )
    assert inserted and reply_email_id is not None
    repo.link_email_to_run(reply_email_id, reply_run_id)

    def _fail_resume(*_args, **_kwargs):
        raise AssertionError("wrong-run persisted content reached orchestration")

    monkeypatch.setattr(orchestrator, "resume_pipeline", _fail_resume)
    job = Job(
        id=uuid.uuid4(),
        kind=JobKind.RESUME_REPLY,
        run_id=job_run_id,
        email_id=reply_email_id,
        attempts=1,
        max_attempts=5,
        lease_token=uuid.uuid4(),
    )

    result = resume_reply.handle_resume_reply(job)

    assert result.outcome is PipelineOutcome.OK
    assert result.diagnostic_code == "unknown:unclassified"
    job_run = repo.load_run(job_run_id)
    reply_run = repo.load_run(reply_run_id)
    assert job_run is not None and job_run["status"] == RunStatus.RECEIVED.value
    assert reply_run is not None and reply_run["status"] == RunStatus.RECEIVED.value
    forbidden = (
        str(job.id),
        str(job_run_id),
        str(reply_run_id),
        str(reply_email_id),
        str(reply_business_id),
        "SECRET",
        "Maria Chen",
        "secret-recipient",
    )
    assert all(token not in caplog.text for token in forbidden)


def test_resume_reply_association_accepts_real_same_run_control(
    seeded_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db import repo
    from app.models.contracts import InboundEmail
    from app.models.job import Job, JobKind
    from app.pipeline import orchestrator
    from app.pipeline.result import PipelineOutcome, PipelineResult
    from app.queue.handlers import resume_reply

    run_id = _seed_run_for_queue_proof()
    reply_email_id, inserted = repo.insert_inbound_email(
        message_id=f"<queueproof-control-{uuid.uuid4()}@test.example>",
        in_reply_to="<queueproof-clarification@test.example>",
        references_header="<queueproof-clarification@test.example>",
        subject="control reply",
        from_addr=_COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="persisted same-run control",
    )
    assert inserted and reply_email_id is not None
    repo.link_email_to_run(reply_email_id, run_id)
    repo.set_status(run_id, RunStatus.AWAITING_REPLY)
    calls: list[tuple[uuid.UUID, InboundEmail, RunStatus]] = []

    def _resume(
        received_run_id: uuid.UUID,
        inbound: InboundEmail,
        *,
        from_status: RunStatus,
        **_kwargs,
    ) -> PipelineResult:
        calls.append((received_run_id, inbound, from_status))
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(orchestrator, "resume_pipeline", _resume)
    job = Job(
        id=uuid.uuid4(),
        kind=JobKind.RESUME_REPLY,
        run_id=run_id,
        email_id=reply_email_id,
        attempts=1,
        max_attempts=5,
        lease_token=uuid.uuid4(),
    )

    result = resume_reply.handle_resume_reply(job)

    assert result.outcome is PipelineOutcome.OK
    assert len(calls) == 1
    called_run_id, called_inbound, called_status = calls[0]
    assert called_run_id == run_id
    assert called_inbound.id == reply_email_id
    assert called_inbound.body_text == "persisted same-run control"
    assert called_status is RunStatus.RECEIVED
    run = repo.load_run(run_id)
    assert run is not None and run["status"] == RunStatus.RECEIVED.value


def test_operator_resume_retry_reloads_complete_resolution_and_dedupes_by_uuid(
    seeded_db,
) -> None:
    from app.db import repo
    from app.db.repo.job_settlement import SettlementOutcome
    from app.models.status import RunStatus
    from app.pipeline.result import (
        PipelineOutcome,
        PipelineReason,
        PipelineResult,
        PipelineStage,
    )

    run_id = _seed_run_for_queue_proof()
    employee_id = _first_coastal_employee_id()
    first_resolution = uuid.uuid4()
    second_resolution = uuid.uuid4()
    mapping = {"unchecked remember name": employee_id}
    repo.create_operator_resume_resolution(run_id, first_resolution, mapping)
    repo.create_operator_resume_resolution(run_id, second_resolution, mapping)
    retryable = PipelineResult(
        outcome=PipelineOutcome.RETRYABLE,
        stage=PipelineStage.EXTRACT,
        reason=PipelineReason.PROVIDER_CONNECTION_FAILURE,
    )

    repo.set_status(run_id, RunStatus.EXTRACTING)
    assert repo.enqueue_operator_resume_retry(
        run_id, first_resolution, retryable, available_in_seconds=5.0
    ) is SettlementOutcome.RETRIED
    assert repo.load_operator_resume_resolution(run_id, first_resolution) == {
        "unchecked remember name": str(employee_id)
    }

    repo.set_status(run_id, RunStatus.EXTRACTING)
    assert repo.enqueue_operator_resume_retry(
        run_id, first_resolution, retryable, available_in_seconds=5.0
    ) is SettlementOutcome.RETRIED
    repo.set_status(run_id, RunStatus.EXTRACTING)
    assert repo.enqueue_operator_resume_retry(
        run_id, second_resolution, retryable, available_in_seconds=5.0
    ) is SettlementOutcome.RETRIED

    with repo.get_connection() as conn:
        rows = conn.execute(
            "SELECT operator_resolution_id, email_id, last_error FROM jobs"
            " WHERE run_id = %s AND kind = 'operator_resume' ORDER BY created_at",
            (str(run_id),),
        ).fetchall()
    assert [uuid.UUID(str(row[0])) for row in rows] == [
        first_resolution,
        second_resolution,
    ]
    assert all(row[1] is None for row in rows)
    assert all(row[2] == retryable.diagnostic_code for row in rows)
    assert "unchecked remember name" not in repr(rows)


def test_operator_resume_retry_half_failure_rolls_back_run_and_preserves_resolution(
    seeded_db, monkeypatch
) -> None:
    from app.db import repo
    from app.db.repo import job_settlement
    from app.models.status import RunStatus
    from app.pipeline.result import (
        PipelineOutcome,
        PipelineReason,
        PipelineResult,
        PipelineStage,
    )

    run_id = _seed_run_for_queue_proof()
    employee_id = _first_coastal_employee_id()
    resolution_id = uuid.uuid4()
    mapping = {"private submitted name": employee_id}
    repo.create_operator_resume_resolution(run_id, resolution_id, mapping)
    repo.set_status(run_id, RunStatus.EXTRACTING)

    def _fail_enqueue(**kwargs):
        raise RuntimeError("injected enqueue failure")

    monkeypatch.setattr(job_settlement, "enqueue_job", _fail_enqueue)
    retryable = PipelineResult(
        outcome=PipelineOutcome.RETRYABLE,
        stage=PipelineStage.EXTRACT,
        reason=PipelineReason.PROVIDER_TIMEOUT,
    )
    with pytest.raises(RuntimeError, match="injected enqueue failure"):
        repo.enqueue_operator_resume_retry(
            run_id, resolution_id, retryable, available_in_seconds=5.0
        )

    run_row = repo.load_run(run_id)
    assert run_row is not None
    assert run_row["status"] == RunStatus.EXTRACTING.value
    assert repo.load_operator_resume_resolution(run_id, resolution_id) == {
        "private submitted name": str(employee_id)
    }
    with repo.get_connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM jobs WHERE operator_resolution_id = %s",
            (str(resolution_id),),
        ).fetchone()
    assert count is not None and int(count[0]) == 0


# ---------------------------------------------------------------------------
# A genuine N-thread claim race: exactly one winner
# ---------------------------------------------------------------------------


def test_genuine_claim_race_exactly_one_winner(seeded_db) -> None:
    """Enqueue exactly ONE job, hold its id, release N_CLAIMANTS barrier-held
    OS threads calling repo.claim_job() directly. Exactly one must come back
    non-None, and it must be THIS test's own job — never a stranger's."""
    from app.db import repo
    from app.models.job import JobKind

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
# Provider handoff / retrigger interleaving: real connections, post-commit pause
# ---------------------------------------------------------------------------


def _seed_claimed_confirmation_send() -> tuple[uuid.UUID, dict[str, Any], Job]:
    """Seed and claim one current-epoch confirmation SEND_OUTBOUND job."""
    from app.db import repo
    from app.models.job import JobKind

    run_id = _seed_run_for_queue_proof()
    repo.set_status(run_id, RunStatus.APPROVED)
    snapshot = repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id=f"<handoff-race-{uuid.uuid4()}@test.example>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@coastalcleaning.example",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Frozen confirmation",
        body_text="Frozen confirmation body",
        attachments=(),
    )
    job_id = repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=repo.send_outbound_dedup_key(snapshot["email_id"]),
        run_id=run_id,
        email_id=snapshot["email_id"],
    )
    assert job_id is not None
    job = repo.claim_job()
    assert job is not None and job.id == job_id
    return run_id, snapshot, job


def _seed_claimed_delivery(
    *, purpose: str, run_status: RunStatus
) -> tuple[uuid.UUID, dict[str, Any], Job]:
    """Seed one current-generation frozen delivery and claim its exact job."""
    from app.db import repo
    from app.models.job import JobKind

    run_id = _seed_run_for_queue_proof()
    repo.set_status(run_id, run_status)
    snapshot = repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose=purpose,
        round=0,
        message_id=f"<expiry-{purpose}-{uuid.uuid4()}@test.example>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@coastalcleaning.example",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Frozen delivery review",
        body_text="Frozen delivery review body",
        attachments=(),
    )
    job_id = repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=repo.send_outbound_dedup_key(snapshot["email_id"]),
        run_id=run_id,
        email_id=snapshot["email_id"],
    )
    assert job_id is not None
    job = repo.claim_job()
    assert job is not None and job.id == job_id
    return run_id, snapshot, job


_DELIVERY_FAILURE_CATEGORIES = {
    "none",
    "transport",
    "provider_5xx",
    "rate_limited",
    "payload_mismatch",
    "authorization",
    "validation",
    "configuration",
    "authorization_expired",
    "unknown",
    "final_attempt_lease_expired",
}


def test_deployed_schema_repair_accepts_authorization_expired(seeded_db) -> None:
    """Non-reset bootstrap repairs a real legacy failure-category CHECK."""
    from app.db import repo
    from app.db.bootstrap import bootstrap

    legacy_categories = _DELIVERY_FAILURE_CATEGORIES - {"authorization_expired"}
    with repo.get_connection() as conn, conn.transaction():
        constraints = conn.execute(
            """
            SELECT c.conname
              FROM pg_constraint AS c
             WHERE c.contype = 'c'
               AND c.conrelid = 'outbound_delivery_attempts'::regclass
               AND (
                   SELECT array_agg(a.attname::text ORDER BY u.ord)
                     FROM unnest(c.conkey) WITH ORDINALITY AS u(attnum, ord)
                     JOIN pg_attribute AS a
                       ON a.attrelid = c.conrelid AND a.attnum = u.attnum
               ) = ARRAY['failure_category']
            """
        ).fetchall()
        assert constraints
        for (constraint_name,) in constraints:
            conn.execute(
                "ALTER TABLE outbound_delivery_attempts DROP CONSTRAINT "
                + psycopg.sql.Identifier(str(constraint_name)).as_string(conn)
            )
        legacy_values = ", ".join(f"'{category}'" for category in sorted(legacy_categories))
        conn.execute(
            "ALTER TABLE outbound_delivery_attempts "
            "ADD CONSTRAINT legacy_outbound_delivery_failure_category_check "
            f"CHECK (failure_category IN ({legacy_values}))"
        )

    bootstrap(reset=False)

    with repo.get_connection() as conn:
        repaired = conn.execute(
            """
            SELECT c.conname, pg_get_constraintdef(c.oid)
              FROM pg_constraint AS c
             WHERE c.contype = 'c'
               AND c.conrelid = 'outbound_delivery_attempts'::regclass
               AND (
                   SELECT array_agg(a.attname::text ORDER BY u.ord)
                     FROM unnest(c.conkey) WITH ORDINALITY AS u(attnum, ord)
                     JOIN pg_attribute AS a
                       ON a.attrelid = c.conrelid AND a.attnum = u.attnum
               ) = ARRAY['failure_category']
            """
        ).fetchall()
    assert len(repaired) == 1
    repaired_categories = set(re.findall(r"'([^']+)'", str(repaired[0][1])))
    assert repaired_categories == _DELIVERY_FAILURE_CATEGORIES

    run_id, snapshot, _job = _seed_claimed_delivery(
        purpose="confirmation", run_status=RunStatus.APPROVED
    )
    with repo.get_connection() as conn, conn.transaction():
        attempt = conn.execute(
            """
            INSERT INTO outbound_delivery_attempts (
                snapshot_id, attempt_state, failure_category
            ) VALUES (%s, 'needs_operator', 'authorization_expired')
            RETURNING id
            """,
            (str(snapshot["snapshot_id"]),),
        ).fetchone()
    assert attempt is not None
    assert repo.load_run(run_id) is not None


@pytest.mark.parametrize(
    ("purpose", "run_status", "review_reason"),
    [
        ("confirmation", RunStatus.APPROVED, "DeliveryReview"),
        ("clarification", RunStatus.AWAITING_REPLY, "ClarificationDeliveryReview"),
        (
            "clarification_field_regression",
            RunStatus.AWAITING_REPLY,
            "ClarificationDeliveryReview",
        ),
    ],
)
def test_pre_provider_authorization_expired_enters_delivery_review(
    seeded_db,
    monkeypatch: pytest.MonkeyPatch,
    purpose: str,
    run_status: RunStatus,
    review_reason: str,
) -> None:
    """A stale reservation records review evidence before any provider boundary."""
    from app.db import repo
    from app.db.repo.job_settlement import SettlementOutcome
    from app.queue.handlers import send_outbound

    run_id, snapshot, job = _seed_claimed_delivery(
        purpose=purpose, run_status=run_status
    )
    before = repo.load_outbound_snapshot(run_id, snapshot["email_id"])
    assert before is not None
    with repo.get_connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE outbound_email_snapshots "
            "SET reserved_at = now() - interval '20 hours' WHERE id = %s",
            (str(snapshot["snapshot_id"]),),
        )

    provider_calls: list[object] = []
    monkeypatch.setattr(
        resend.Emails,
        "send",
        lambda *_args, **_kwargs: provider_calls.append(object()),
    )
    result = send_outbound.handle_send_outbound(job)

    assert result.reason is PipelineReason.DELIVERY_AUTHORIZATION_EXPIRED
    assert provider_calls == []
    assert repo.settle_outbound_delivery_job(job, result) is SettlementOutcome.DONE
    after = repo.load_outbound_snapshot(run_id, snapshot["email_id"])
    run = repo.load_run(run_id)
    settled_job = repo.get_job(job.id)
    assert after is not None
    assert run is not None
    assert settled_job is not None
    assert after["message_id"] == before["message_id"]
    assert after["body_text"] == before["body_text"]
    assert run["status"] == RunStatus.NEEDS_OPERATOR.value
    assert run["error_reason"] == review_reason
    assert settled_job["state"] == "done"
    with repo.get_connection() as conn:
        attempt = conn.execute(
            "SELECT attempt_state, failure_category FROM outbound_delivery_attempts "
            "WHERE snapshot_id = %s",
            (str(snapshot["snapshot_id"]),),
        ).fetchone()
        open_jobs = conn.execute(
            "SELECT count(*) FROM jobs WHERE run_id = %s "
            "AND state IN ('pending', 'leased')",
            (str(run_id),),
        ).fetchone()
    assert attempt == ("needs_operator", "authorization_expired")
    assert open_jobs == (0,)


@pytest.mark.parametrize(
    ("purpose", "run_status", "review_reason"),
    [
        ("confirmation", RunStatus.APPROVED, "DeliveryReview"),
        ("clarification", RunStatus.AWAITING_REPLY, "ClarificationDeliveryReview"),
        (
            "clarification_field_regression",
            RunStatus.AWAITING_REPLY,
            "ClarificationDeliveryReview",
        ),
    ],
)
def test_provider_handoff_authorization_expired_at_gateway_boundary_enters_review(
    seeded_db,
    monkeypatch: pytest.MonkeyPatch,
    purpose: str,
    run_status: RunStatus,
    review_reason: str,
) -> None:
    """A valid handoff that reaches its fixed send budget never calls Resend."""
    from app.db import repo
    from app.db.repo.job_settlement import SettlementOutcome
    from app.db.repo.outbound_handoffs import ProviderHandoffAuthorization
    from app.pipeline.result import DELIVERY_SEND_BUDGET
    from app.queue.handlers import send_outbound

    run_id, snapshot, job = _seed_claimed_delivery(
        purpose=purpose, run_status=run_status
    )
    before = repo.load_outbound_snapshot(run_id, snapshot["email_id"])
    assert before is not None
    authorization = repo.authorize_outbound_provider_handoff(job)
    assert isinstance(authorization, ProviderHandoffAuthorization)

    provider_calls: list[object] = []
    monkeypatch.setattr(
        resend.Emails,
        "send",
        lambda *_args, **_kwargs: provider_calls.append(object()),
    )
    boundary = authorization.not_after - timedelta(
        seconds=DELIVERY_SEND_BUDGET.timeout_seconds
    ) - DELIVERY_SEND_BUDGET.safety_margin
    result = send_outbound.handle_send_outbound(job, clock=lambda: boundary)

    assert result.reason is PipelineReason.DELIVERY_AUTHORIZATION_EXPIRED
    assert provider_calls == []
    assert repo.settle_outbound_delivery_job(job, result) is SettlementOutcome.DONE
    after = repo.load_outbound_snapshot(run_id, snapshot["email_id"])
    run = repo.load_run(run_id)
    settled_job = repo.get_job(job.id)
    assert after is not None
    assert run is not None
    assert settled_job is not None
    assert after["message_id"] == before["message_id"]
    assert after["body_text"] == before["body_text"]
    assert run["status"] == RunStatus.NEEDS_OPERATOR.value
    assert run["error_reason"] == review_reason
    assert settled_job["state"] == "done"
    with repo.get_connection() as conn:
        attempt = conn.execute(
            "SELECT attempt_state, failure_category FROM outbound_delivery_attempts "
            "WHERE snapshot_id = %s",
            (str(snapshot["snapshot_id"]),),
        ).fetchone()
        open_jobs = conn.execute(
            "SELECT count(*) FROM jobs WHERE run_id = %s "
            "AND state IN ('pending', 'leased')",
            (str(run_id),),
        ).fetchone()
    assert attempt == ("needs_operator", "authorization_expired")
    assert open_jobs == (0,)


def _backend_pid(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT pg_backend_pid()").fetchone()
    assert row is not None
    return int(row[0])


def test_provider_handoff_blocks_epoch_bump_before_gateway(
    seeded_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A committed active handoff blocks the only dangerous epoch-bump window.

    This is a two-connection, sync handler/repository proof. The wrapper pauses
    *after* the real authorizer committed its handoff and *before* the unmodified
    handler reaches its gateway seam; the gateway is only a passive recorder.
    Falsifying mutation: removing clear_reply_context's active-handoff predicate
    makes the retrigger advance to epoch 1 and this test fail.
    """
    from app.db import repo
    from app.db.repo.job_settlement import SettlementOutcome
    from app.queue.handlers import send_outbound

    run_id, snapshot, job = _seed_claimed_confirmation_send()
    before_run = repo.load_run(run_id)
    assert before_run is not None
    original_snapshot = repo.load_outbound_snapshot(run_id, snapshot["email_id"])
    assert original_snapshot is not None

    barrier = threading.Barrier(2, timeout=30)
    return_to_handler = threading.Event()
    barrier_passes: list[str] = []
    worker_pid: list[int] = []
    retrigger_pid: list[int] = []
    gateway_epochs: list[int] = []
    gateway_message_ids: list[str] = []
    worker_errors: list[BaseException] = []
    retrigger_errors: list[BaseException] = []
    real_authorize = repo.authorize_outbound_provider_handoff

    def authorize_then_pause(leased_job):
        with repo.get_connection() as conn:
            worker_pid.append(_backend_pid(conn))
            with conn.transaction():
                authorization = real_authorize(leased_job, conn=conn)
            barrier.wait()
            barrier_passes.append("worker")
            assert return_to_handler.wait(timeout=30), "retrigger did not release worker"
            return authorization

    def provider_spy(frozen_snapshot: dict[str, object], **_kwargs: object) -> PipelineResult:
        gateway_epochs.append(_read_reply_epoch(run_id))
        gateway_message_ids.append(str(frozen_snapshot["message_id"]))
        return PipelineResult(outcome=PipelineOutcome.OK)

    def run_handler() -> None:
        try:
            assert send_outbound.handle_send_outbound(job).outcome is PipelineOutcome.OK
        except BaseException as exc:  # surface thread failures in the test thread
            worker_errors.append(exc)

    def retrigger_after_authorization() -> None:
        try:
            with repo.get_connection() as conn:
                retrigger_pid.append(_backend_pid(conn))
                barrier.wait()
                barrier_passes.append("retrigger")
                with (
                    pytest.raises(repo.ActiveOutboundProviderHandoffError),
                    conn.transaction(),
                ):
                    repo.clear_reply_context(run_id, conn=conn)
                assert _read_reply_epoch(run_id) == 0
        except BaseException as exc:  # always unblock the handler, then fail visibly
            retrigger_errors.append(exc)
        finally:
            return_to_handler.set()

    monkeypatch.setattr(
        repo, "authorize_outbound_provider_handoff", authorize_then_pause
    )
    from app.email import gateway

    monkeypatch.setattr(gateway, "send_reserved_outbound_snapshot", provider_spy)
    worker = threading.Thread(target=run_handler, name="handoff-race-worker")
    retrigger = threading.Thread(
        target=retrigger_after_authorization, name="handoff-race-retrigger"
    )
    worker.start()
    retrigger.start()
    worker.join(timeout=35)
    retrigger.join(timeout=35)
    return_to_handler.set()

    assert not worker.is_alive(), "worker did not leave its post-authorization pause"
    assert not retrigger.is_alive(), "retrigger did not leave its barrier/transaction"
    assert worker_errors == []
    assert retrigger_errors == []
    assert sorted(barrier_passes) == ["retrigger", "worker"]
    assert len(worker_pid) == len(retrigger_pid) == 1
    assert worker_pid[0] != retrigger_pid[0], "the race needs two real backend connections"
    assert _read_reply_epoch(run_id) == 0
    assert repo.load_run(run_id) == before_run
    assert repo.load_outbound_snapshot(run_id, snapshot["email_id"]) == original_snapshot
    assert gateway_epochs == [0]
    assert gateway_message_ids == [str(snapshot["message_id"])]
    with repo.get_connection() as conn:
        run_jobs = conn.execute(
            "SELECT count(*) FROM jobs WHERE run_id = %s AND kind = 'run_pipeline'",
            (str(run_id),),
        ).fetchone()
    assert run_jobs == (0,), "blocked retrigger must not enqueue or wake a pipeline job"

    assert (
        repo.settle_outbound_delivery_job(job, PipelineResult(outcome=PipelineOutcome.OK))
        is SettlementOutcome.DONE
    )
    settled = repo.get_job(job.id)
    assert settled is not None and settled["state"] == "done"


def test_provider_handoff_race_control_observes_stale_gateway_when_fence_is_released(
    seeded_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The barrier catches stale provider work when this test releases its fence.

    This intentionally unsafe direct-SQL setup is confined to the resettable
    queueproof fixture. Falsifying mutation: retaining the handoff instead of
    releasing it makes clear_reply_context reject the bump, so the required epoch-1
    gateway observation fails. Together with the protected companion, that proves
    the schedule can expose the actual forbidden interleaving.
    """
    from app.db import repo
    from app.db.repo.job_settlement import SettlementOutcome
    from app.queue.handlers import send_outbound

    run_id, _snapshot, job = _seed_claimed_confirmation_send()
    barrier = threading.Barrier(2, timeout=30)
    return_to_handler = threading.Event()
    barrier_passes: list[str] = []
    worker_pid: list[int] = []
    retrigger_pid: list[int] = []
    authorizations: list[object] = []
    gateway_epochs: list[int] = []
    worker_errors: list[BaseException] = []
    retrigger_errors: list[BaseException] = []
    real_authorize = repo.authorize_outbound_provider_handoff

    def authorize_then_pause(leased_job):
        with repo.get_connection() as conn:
            worker_pid.append(_backend_pid(conn))
            with conn.transaction():
                authorization = real_authorize(leased_job, conn=conn)
            authorizations.append(authorization)
            barrier.wait()
            barrier_passes.append("worker")
            assert return_to_handler.wait(timeout=30), "control retrigger did not release worker"
            return authorization

    def provider_spy(_frozen_snapshot: dict[str, object], **_kwargs: object) -> PipelineResult:
        gateway_epochs.append(_read_reply_epoch(run_id))
        return PipelineResult(outcome=PipelineOutcome.OK)

    def run_handler() -> None:
        try:
            assert send_outbound.handle_send_outbound(job).outcome is PipelineOutcome.OK
        except BaseException as exc:
            worker_errors.append(exc)

    def release_fence_then_retrigger() -> None:
        try:
            with repo.get_connection() as conn:
                retrigger_pid.append(_backend_pid(conn))
                barrier.wait()
                barrier_passes.append("retrigger")
                assert len(authorizations) == 1
                handoff_id = getattr(authorizations[0], "handoff_id", None)
                assert handoff_id is not None
                with conn.transaction():
                    released = conn.execute(
                        "UPDATE outbound_provider_handoffs "
                        "SET released_at = now(), release_reason = 'finalized' "
                        "WHERE id = %s AND released_at IS NULL RETURNING id",
                        (str(handoff_id),),
                    ).fetchone()
                    assert released is not None
                    assert repo.clear_reply_context(run_id, conn=conn) == 1
        except BaseException as exc:
            retrigger_errors.append(exc)
        finally:
            return_to_handler.set()

    monkeypatch.setattr(
        repo, "authorize_outbound_provider_handoff", authorize_then_pause
    )
    from app.email import gateway

    monkeypatch.setattr(gateway, "send_reserved_outbound_snapshot", provider_spy)
    worker = threading.Thread(target=run_handler, name="handoff-control-worker")
    retrigger = threading.Thread(
        target=release_fence_then_retrigger, name="handoff-control-retrigger"
    )
    worker.start()
    retrigger.start()
    worker.join(timeout=35)
    retrigger.join(timeout=35)
    return_to_handler.set()

    assert not worker.is_alive()
    assert not retrigger.is_alive()
    assert worker_errors == []
    assert retrigger_errors == []
    assert sorted(barrier_passes) == ["retrigger", "worker"]
    assert len(worker_pid) == len(retrigger_pid) == 1
    assert worker_pid[0] != retrigger_pid[0]
    assert _read_reply_epoch(run_id) == 1
    assert gateway_epochs == [1], "the control must observe the stale gateway epoch"
    assert (
        repo.settle_outbound_delivery_job(job, PipelineResult(outcome=PipelineOutcome.OK))
        is SettlementOutcome.INVALID_CONTEXT
    )
    settled = repo.get_job(job.id)
    assert settled is not None and settled["state"] == "done"


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


def test_skip_locked_steps_over_a_row_another_worker_is_holding(seeded_db) -> None:
    """SKIP LOCKED is load-bearing, and exactly-one-winner is NOT the property it
    buys. Plain `FOR UPDATE` already delivers mutual exclusion: a second claimant
    blocks on the held row, re-evaluates it under READ COMMITTED once the holder
    commits, finds it leased, and walks away. So the claim-race proof above stays
    green with SKIP LOCKED deleted — it cannot see this regression.

    What SKIP LOCKED buys is LIVENESS. Without it, `LIMIT 1` has already committed
    to the locked row; Postgres discards it rather than advancing to the next
    candidate, so the claimant returns empty-handed while a perfectly claimable job
    sits one row over. With two daemon workers that is a silent collapse to one
    effective worker under exactly the contention the queue exists to absorb.

    Hold a genuine row lock on the oldest claimable job in a separate live
    transaction, then claim. The claim must (1) return promptly instead of blocking
    behind the held row, and (2) come back holding the OTHER job.
    """
    import psycopg as _psycopg

    from app.config import get_settings
    from app.db import repo
    from app.models.job import JobKind

    claim_timeout_s = 5.0

    run_id = _seed_run_for_queue_proof()
    # Two separate transactions => strictly increasing available_at, so `first` is
    # unambiguously the row that ORDER BY (priority, available_at) selects. Without
    # that, which row gets locked below would be a coin flip and the proof would
    # only bite intermittently.
    first = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-skiplocked-a:{uuid.uuid4()}",
        run_id=run_id,
    )
    second = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-skiplocked-b:{uuid.uuid4()}",
        run_id=run_id,
    )
    assert first is not None and second is not None and first != second

    claimed: list[Job | None] = []
    thread = threading.Thread(target=lambda: claimed.append(repo.claim_job()))

    holder = _psycopg.connect(get_settings().database_url)
    try:
        with holder.transaction():
            holder.execute(
                "SELECT id FROM jobs WHERE id = %s FOR UPDATE", (first,)
            ).fetchone()
            # The row lock on `first` is held for as long as this transaction stays
            # open — this is the "another worker is mid-claim" condition, made
            # deterministic instead of raced.
            thread.start()
            thread.join(timeout=claim_timeout_s)
            blocked = thread.is_alive()
    finally:
        # Release the lock unconditionally, so a claimer that DID block can finish
        # and never leaks past this test. Do this before asserting.
        holder.close()
    thread.join(timeout=claim_timeout_s)

    assert not blocked, (
        f"claim_job() was still blocked after {claim_timeout_s}s on a row another "
        "transaction was holding, instead of skipping over it — this is FOR UPDATE "
        "without SKIP LOCKED. A second worker stalls behind the first rather than "
        "picking up the next free job."
    )
    assert len(claimed) == 1
    winner = claimed[0]
    assert winner is not None, (
        "claim_job() returned nothing while a claimable job was sitting right "
        "there — LIMIT 1 discarded the locked row instead of skipping to the next."
    )
    assert winner.id == second, (
        "the claimer must step OVER the held row and take the other job, not "
        "return the locked one"
    )


# ---------------------------------------------------------------------------
# Proof 4 — a graceful shutdown releases a real held lease immediately, and
# the released row's own zombie worker is fenced out rather than corrupting it.
# ---------------------------------------------------------------------------


def test_graceful_shutdown_releases_held_leases_immediately(
    seeded_db, live_worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real worker holds a real lease; worker.stop() (not repo.release_leases
    called directly — that repo-level half already exists elsewhere) must hand
    it back to `pending` immediately, without waiting out LEASE_SECONDS. The
    straggler that stop() could not join is not corrupting anything: its own
    eventual settlement is fenced on the lease token it was issued and comes
    back FENCED.
    """
    from app.db import repo
    from app.models.job import JobKind
    from app.queue import worker
    from app.queue.handlers import pipeline

    run_id = _seed_run_for_queue_proof()
    enqueued_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-graceful-shutdown:{uuid.uuid4()}",
        run_id=run_id,
    )
    assert enqueued_id is not None

    handler_entered = threading.Event()
    release_me = live_worker.blocker()  # minted BY THE FIXTURE — its
    # teardown releases this even if the test body never reaches its own set()

    def blocking_handler(job) -> PipelineResult:
        handler_entered.set()
        release_me.wait(timeout=_BLOCKER_WAIT_SECONDS)
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(pipeline, "handle_run_pipeline", blocking_handler)

    settlement_results: list[repo.SettlementOutcome] = []
    real_settle_pipeline_job = repo.settle_pipeline_job

    def spy_settle_pipeline_job(  # noqa: ANN001
        job, result, *, backoff_seconds, conn=None
    ) -> repo.SettlementOutcome:
        settled = real_settle_pipeline_job(
            job,
            result,
            backoff_seconds=backoff_seconds,
            conn=conn,
        )
        settlement_results.append(settled)
        return settled

    monkeypatch.setattr(repo, "settle_pipeline_job", spy_settle_pipeline_job)

    live_worker.start(n=1)  # never worker.start() directly
    assert handler_entered.wait(timeout=_BLOCKER_WAIT_SECONDS), (
        "the worker never entered the blocked handler"
    )

    # Precondition: a genuinely held lease, or everything below is theatre.
    row = repo.get_job(enqueued_id)
    assert row is not None
    assert row["state"] == "leased"
    assert row["lease_token"] is not None
    assert row["leased_until"] is not None
    assert row["leased_until"] > datetime.now(UTC)

    straggler_candidates = live_queue_worker_threads()
    assert len(straggler_candidates) == 1
    straggler = straggler_candidates[0]

    worker.stop(grace_seconds=1)  # the blocked handler will not exit within
    # this grace window — that is intentional and exactly what the release
    # below must survive.

    row = repo.get_job(enqueued_id)
    assert row is not None
    assert row["state"] == "pending", (
        "worker.stop() must release the held lease IMMEDIATELY, without "
        "waiting out LEASE_SECONDS"
    )
    assert row["lease_token"] is None
    assert row["leased_until"] is None

    release_me.set()
    straggler.join(timeout=_BLOCKER_WAIT_SECONDS)
    assert not straggler.is_alive(), (
        "the straggler must actually exit once released — its generation's "
        "stop event is still set, so its next loop-boundary check returns"
    )

    assert settlement_results == [repo.SettlementOutcome.FENCED], (
        "the now-zombie worker's pipeline settlement must be FENCED OUT rather "
        f"than marking the job done; got {settlement_results}"
    )
    row = repo.get_job(enqueued_id)
    assert row is not None
    assert row["state"] == "pending", (
        "the zombie's fenced-out completion must not have moved the row off "
        "pending"
    )


def test_quiesce_releases_a_blocked_handler_and_joins_to_zero(
    seeded_db, live_worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_quiesce_workers` is what stands between a blocked worker and a DELETE
    landing on its leased row. It only ever runs on an abort path in normal
    use, so drive it head-on rather than leaving it exercised only when
    nobody is watching.
    """
    from app.db import repo
    from app.models.job import JobKind
    from app.queue.handlers import pipeline

    run_id = _seed_run_for_queue_proof()
    enqueued_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-quiesce:{uuid.uuid4()}",
        run_id=run_id,
    )
    assert enqueued_id is not None

    handler_entered = threading.Event()
    release_me = live_worker.blocker()

    def blocking_handler(job) -> PipelineResult:
        handler_entered.set()
        release_me.wait(timeout=_BLOCKER_WAIT_SECONDS)
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(pipeline, "handle_run_pipeline", blocking_handler)

    live_worker.start(n=1)
    assert handler_entered.wait(timeout=_BLOCKER_WAIT_SECONDS)

    assert live_queue_worker_threads(), (
        "the precondition: a live worker thread must exist before quiescing it"
    )
    row = repo.get_job(enqueued_id)
    assert row is not None
    assert row["state"] == "leased"

    # Do NOT release the blocker and do NOT call stop() — this is exactly
    # what live_worker's own teardown does when a test body dies here.
    _quiesce_workers([release_me])

    assert release_me.is_set(), "_quiesce_workers must release every blocker"
    row = repo.get_job(enqueued_id)
    assert row is not None
    # `_quiesce_workers` releases every blocker BEFORE calling stop(), so a
    # handler that (like this one) returns immediately once unblocked can
    # legitimately race ahead and complete the job through the normal
    # settle_pipeline_job path before stop()'s own release_leases call ever sees it
    # still leased — successful settlement clears lease_token/leased_until exactly
    # like release_leases does. Both outcomes are SAFE and both are what this
    # assertion accepts: what matters is that no row is left `leased` with a
    # stale token once the process is quiescent.
    assert row["state"] in ("pending", "done"), row["state"]
    assert row["lease_token"] is None
    assert live_queue_worker_threads() == [], (
        "the process must be fully quiescent — this is what makes it safe "
        "for _isolated_jobs to delete `jobs` next"
    )


def test_a_restarted_worker_claims_and_completes_a_real_job(
    seeded_db, live_worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live half of the restart proof: not "the restarted threads are
    alive", but "the restarted worker CLAIMS AND COMPLETES A JOB." Under the
    round-2 defect (a single stop event that start() never resets), the
    second generation's threads would observe generation 1's still-set event
    on their first iteration and return before ever calling drain_once — job
    B stays `pending` forever and `thread.is_alive()` would have been GREEN
    against the exact bug this proves absent.
    """
    from app.db import repo
    from app.models.job import JobKind
    from app.queue import worker
    from app.queue.handlers import pipeline

    run_id = _seed_run_for_queue_proof()

    handled_a: list[uuid.UUID] = []
    handled_a_event = threading.Event()

    def stub_a(job) -> PipelineResult:
        handled_a.append(job.id)
        handled_a_event.set()
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(pipeline, "handle_run_pipeline", stub_a)

    job_a = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-restart-a:{uuid.uuid4()}",
        run_id=run_id,
    )
    assert job_a is not None

    live_worker.start(n=1)  # never worker.start() directly
    assert handled_a_event.wait(timeout=_BLOCKER_WAIT_SECONDS)
    worker.stop(grace_seconds=_BLOCKER_WAIT_SECONDS)  # a CLEAN stop; the
    # thread joins — calling stop() directly (not through the fixture) is
    # fine and is the point of this test; it is START that must go through
    # the fixture, so the fixture knows a worker exists and can quiesce it.

    handled_b: list[uuid.UUID] = []
    handled_b_event = threading.Event()

    def stub_b(job) -> PipelineResult:
        handled_b.append(job.id)
        handled_b_event.set()
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(pipeline, "handle_run_pipeline", stub_b)

    job_b = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-restart-b:{uuid.uuid4()}",
        run_id=run_id,
    )
    assert job_b is not None

    live_worker.start(n=1)  # a second generation, with a brand-new stop event
    assert handled_b_event.wait(timeout=_BLOCKER_WAIT_SECONDS), (
        "the restarted worker's dispatch was never invoked for job B — "
        "generation 2 likely observed generation 1's still-set stop event"
    )
    worker.stop(grace_seconds=_BLOCKER_WAIT_SECONDS)  # joins: settle_pipeline_job
    # has provably already run by the time this join returns

    assert handled_b == [job_b], "the stub must have received job B's id, not a stranger's"

    row_b = repo.get_job(job_b)
    assert row_b is not None
    assert row_b["state"] == "done", (
        "job B must reach `done`, read back by its OWN id — a thread being "
        "alive proves nothing about whether it ever drained"
    )


# ---------------------------------------------------------------------------
# A static guard: the ONLY place in this file that may call
# `worker.start(...)` is `_LiveWorkerHandle.start`'s own body — the single
# wrapper every test call site goes through. An AST scan, not a grep: this
# module's own prose has to SAY the words "never worker.start() directly" to
# explain the rule, and a grep that counts its own explanation would be
# self-invalidating.
# ---------------------------------------------------------------------------


def test_every_worker_start_call_goes_through_the_live_worker_wrapper() -> None:
    tree = ast.parse(pathlib.Path(__file__).read_text())
    sanctioned_class = "_LiveWorkerHandle"
    sanctioned_method = "start"
    violations: list[int] = []

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._class_stack: list[str] = []
            self._func_stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._class_stack.append(node.name)
            self.generic_visit(node)
            self._class_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._func_stack.append(node.name)
            self.generic_visit(node)
            self._func_stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            is_worker_start = (
                isinstance(func, ast.Attribute)
                and func.attr == "start"
                and isinstance(func.value, ast.Name)
                and func.value.id == "worker"
            )
            if is_worker_start:
                in_sanctioned_wrapper = (
                    self._class_stack[-1:] == [sanctioned_class]
                    and self._func_stack[-1:] == [sanctioned_method]
                )
                if not in_sanctioned_wrapper:
                    violations.append(node.lineno)
            self.generic_visit(node)

    _Visitor().visit(tree)
    assert violations == [], (
        f"worker.start(...) called directly outside {sanctioned_class}."
        f"{sanctioned_method} at line(s) {violations} — every test in this "
        "file must start a worker through the live_worker fixture instead, "
        "so its teardown can quiesce a straggler before _isolated_jobs "
        "deletes beneath it."
    )


# ---------------------------------------------------------------------------
# Proof 2 — the phase's headline claim: a retrigger survives a worker death
# and completes on the next drain. ROADMAP criterion #2.
# ---------------------------------------------------------------------------


def test_retrigger_survives_worker_crash_mid_lease(
    seeded_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Six steps, each with its own assertion — a step with no assertion is
    where the vacuity gets in (see this file's own module docstring and
    16-VALIDATION.md's named vacuous twin: a test that never actually leases
    the job before "killing" the worker, so the reclaim path never fires and
    the first drain simply does the work on dumb luck).

    This test starts NO real worker. It drives `repo.claim_job()` and
    `drain.drain_once()` directly on the test thread, which is the only way
    to stop MID-LEASE — `drain_once()` would run the handler to completion.
    It therefore never trips `_isolated_jobs`' worker-quiescence delete gate
    and must not acquire a `worker.start()` call of its own; if a future
    edit ever needs a real worker here, it must go through `live_worker`.

    The orchestrator (`pipeline_glue.run_pipeline_now`) is stubbed — this
    repo's `.env` carries live LLM keys, and an unstubbed call would hit a
    real provider, bill real money, and flake. The stub also records an
    OBSERVABLE side effect (advancing the run to COMPUTED) rather than being
    a bare no-op recorder: bare status alone cannot discriminate "the
    reclaim fired and the run genuinely re-ran" from "the reclaim never
    fired and the run is exactly as stuck as it was after step 3" — both
    leave the run sitting at EXTRACTING, because that is the value
    `handle_run_pipeline`'s OWN forward CAS writes in the passing case, and
    it is also the value step 3 below left behind on its own in the failing
    case. Only the spy call list and the run's status moving PAST EXTRACTING
    tell the two apart.

    FALSIFYING MUTATIONS (each executed against real, unmutated source in
    this worktree, confirmed RED, then reverted — see the plan's SUMMARY for
    the pasted red output):
      (a) strip `OR (c.state = 'leased' AND c.leased_until < now())` from
          claim_job's WHERE (app/db/repo/jobs.py) — the job is never
          reclaimed, step 5's drain claims nothing, and this test must go
          red on `drain.drain_once() != DrainOutcome.DONE`.
      (b) strip the `if job.attempts > 1: repo.rewind_for_reclaim(run_id)`
          preamble from handle_run_pipeline (app/queue/handlers/pipeline.py)
          — the run stays at EXTRACTING (from step 3's own CAS), the
          RECEIVED->EXTRACTING forward CAS then fails because the run is no
          longer sitting at RECEIVED, the job is still marked `done` (a lost
          CAS is not an error), and this test must go red on the orchestrator
          spy never having been called / the run never reaching COMPUTED.
    """
    from fastapi.testclient import TestClient

    import app.main as app_main
    import app.routes.pipeline_glue as pipeline_glue_mod
    from app.db import repo
    from app.models.status import RunStatus
    from app.queue import drain
    from app.queue.drain import DrainOutcome

    # --- Step 1: seed an ERROR run, retrigger it -----------------------------
    run_id = _seed_run_for_queue_proof()
    repo.set_status(run_id, RunStatus.ERROR)
    epoch_before = _read_reply_epoch(run_id)

    orchestrator_calls: list[uuid.UUID] = []

    def _stub_run_pipeline_now(rid: uuid.UUID) -> PipelineResult:
        orchestrator_calls.append(rid)
        # Simulate ONLY the observable fact that a real orchestrator would
        # eventually advance the run past EXTRACTING — never a real
        # LLM/provider call. See the docstring above for why this side
        # effect, not a bare no-op, is what makes "genuinely re-ran"
        # distinguishable from the stranded-mutation's own EXTRACTING value.
        repo.set_status(rid, RunStatus.COMPUTED)
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(pipeline_glue_mod, "run_pipeline_now", _stub_run_pipeline_now)

    client = TestClient(app_main.app)
    response = client.post(f"/runs/{run_id}/retrigger")
    assert response.status_code in (200, 303)

    epoch_after = _read_reply_epoch(run_id)
    assert epoch_after == epoch_before + 1, (
        "retrigger's own clear_reply_context must bump the epoch exactly once"
    )

    # --- Step 2: assert the durable enqueue, looked up by dedup_key ---------
    # Never assert merely "a jobs row exists" — hold this id and scope every
    # assertion below to it, belt-and-suspenders alongside `_isolated_jobs`.
    dedup_key = f"run_pipeline:{run_id}:{epoch_after}"
    with repo.get_connection() as conn:
        row = conn.execute(
            "SELECT id, state, kind, attempts FROM jobs WHERE dedup_key = %s",
            (dedup_key,),
        ).fetchone()
    assert row is not None, f"no jobs row found for dedup_key={dedup_key!r}"
    job_id = uuid.UUID(str(row[0]))
    assert row[1] == "pending"
    assert row[2] == "run_pipeline"
    assert row[3] == 0
    assert orchestrator_calls == [], (
        "nothing may have run yet — WORKER_COUNT=0, and the pipeline has not "
        "been dispatched"
    )

    # --- Step 3: simulate a worker that claims the job, gets partway through
    # (its own forward CAS lands the run at EXTRACTING, mirroring what
    # handle_run_pipeline itself would have done on a first attempt), and
    # then dies mid-lease. NEVER drain_once() here — that would run the
    # handler to completion; repo.claim_job() is what lets this test stop
    # MID-LEASE. ------------------------------------------------------------
    claimed = repo.claim_job()
    assert claimed is not None
    assert claimed.id == job_id, "the claim in step 3 must be THIS test's own job"
    assert claimed.attempts == 1
    token_a = claimed.lease_token

    leased_row = repo.get_job(job_id)
    assert leased_row is not None
    assert leased_row["state"] == "leased", (
        "the job must be GENUINELY leased before the simulated crash — "
        "without this, the reclaim below never fires and the proof is "
        "vacuous by 16-VALIDATION.md's own naming"
    )
    assert leased_row["lease_token"] == token_a
    assert leased_row["leased_until"] is not None
    assert leased_row["leased_until"] > datetime.now(UTC)

    advanced = repo.claim_status(run_id, RunStatus.RECEIVED, RunStatus.EXTRACTING)
    assert advanced is True, (
        "modeling the dying worker's own forward CAS, using the SAME CAS "
        "handle_run_pipeline itself issues on a first attempt — this is what "
        "forces the automatic reclaim's rewind to be genuinely exercised "
        "below rather than trivially skipped (a run left at RECEIVED would "
        "let the forward CAS win regardless of whether the rewind ran at all)"
    )

    # --- Step 4: expire the lease WITHOUT sleeping ---------------------------
    with repo.get_connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE jobs SET leased_until = now() - interval '1 second' WHERE id = %s",
            (str(job_id),),
        )

    # --- Step 5: a second worker (or a manual drain) picks the job back up --
    assert drain.drain_once() == DrainOutcome.DONE, (
        "drain_once() must claim and dispatch the reclaimed job — a job "
        "that was never actually reclaimable would leave nothing to drain"
    )

    # --- Step 6: all four outcomes, separately -------------------------------
    final_row = repo.get_job(job_id)
    assert final_row is not None
    assert final_row["attempts"] == 2, (
        "the reclaim must have fired — a job that was never leased before "
        "the crash would show 1 here, not 2; this is the vacuity detector"
    )
    assert final_row["state"] == "done"

    assert orchestrator_calls == [run_id], (
        "the automatic reclaim's rewind must have fired and the forward CAS "
        "re-won, letting the orchestrator genuinely run a second time — a "
        "lost CAS would leave this list empty"
    )

    final_run = repo.load_run(run_id)
    assert final_run is not None
    assert final_run["status"] == "computed", (
        "the run must show the OBSERVABLE result of a real re-run (this "
        "test's stub advances to COMPUTED), never left stuck at EXTRACTING — "
        "which is exactly, and indistinguishably by status alone, what the "
        "run would show under the attempts>1 rewind-removed mutation"
    )

    assert _read_reply_epoch(run_id) == epoch_after, (
        "the automatic reclaim must never bump reply_epoch a second time — "
        "only the operator's own retrigger click may grant that licence, "
        "and it already did, once, in step 1"
    )


# ---------------------------------------------------------------------------
# THE ANTI-VACUOUS-PROOF ANCHOR (17-05, ROADMAP criterion #2, PUMP-01). A job
# scheduled for LATER, on an instance with NO live worker threads, is proven
# executed by hitting GET /internal/pump — never drain.drain_once() directly,
# because criterion #2 is specifically about the endpoint the external cron
# actually calls. WORKER_COUNT=0 is already this suite's default (see
# tests/conftest.py), so the zero-worker state is the default, not staging.
# ---------------------------------------------------------------------------


def test_pump_drains_future_due_job_with_zero_workers(
    seeded_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nine steps, each carrying its own assertion — a step with no assertion
    is where the vacuity gets in (see this module's own docstring). The four
    non-vacuity traps this test is deliberately built to make impossible:
    (a) never requests `live_worker` — no worker races ahead of the pump;
    (b) asserts the job is genuinely NOT claimable while future-dated, so the
    claim query is not trivially satisfied; (c) asserts `claimed == 1` and
    `done == 1` from the JSON body, plus a by-id row re-read — never merely
    status_code == 200; (d) STUBS `pipeline_glue.run_pipeline_now` and asserts the
    handler-side observable `orchestrator_calls == [run_id]` — the seeded job is kind
    `run_pipeline`, and an unstubbed
    drain would hit the real orchestrator and paid LLM providers
    (app/queue/handlers/pipeline.py:159) AND could let `done == 1` pass on a
    run that ended in ERROR, since the pipeline catches stage failures and
    returns normally (pipeline.py:74). The stub's OBSERVABLE side effect
    (advancing the run to COMPUTED — recoverable/in-flight per
    app/routes/runs.py:66-69, NOT terminal) is what lets the
    run-status assertion in step 9 discriminate "the pump genuinely drove the
    correct handler" from "the row merely says done."

    FALSIFYING MUTATION (executed against real, unmutated source in this
    worktree, confirmed RED, then reverted — see the plan's SUMMARY for the
    pasted red output): make GET /internal/pump's drain loop a no-op (the
    `while` condition in app/routes/pump.py never runs `drain_once()`) — the
    future-due-then-backdated job is never claimed, the response reports
    `claimed == 0`, and this test must go red on `body["claimed"] == 1`.
    """
    from fastapi.testclient import TestClient

    import app.main as app_main
    import app.routes.pipeline_glue as pipeline_glue_mod
    from app.config import get_settings
    from app.db import repo
    from app.models.job import JobKind
    from app.models.status import RunStatus

    # --- Step 0: stub the orchestrator BEFORE anything touches the endpoint —
    # mandatory: the seeded job is kind run_pipeline, and
    # an unstubbed drain hits the real orchestrator + paid LLM providers.
    orchestrator_calls: list[uuid.UUID] = []

    def _stub_run_pipeline_now(rid: uuid.UUID) -> PipelineResult:
        orchestrator_calls.append(rid)
        # The observable a real orchestrator would eventually produce — never
        # a bare no-op, or this test could not tell "the pump genuinely ran
        # the handler" apart from "the job row merely says done."
        repo.set_status(rid, RunStatus.COMPUTED)
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(pipeline_glue_mod, "run_pipeline_now", _stub_run_pipeline_now)

    # --- settings-cache discipline: clear BEFORE and AFTER,
    # not only before — copying tests/test_repo_jobs_sql.py:20-31 — or a
    # cached PUMP_TOKEN leaks into a later test.
    token = f"queueproof-pump-token-{uuid.uuid4()}"
    monkeypatch.setenv("PUMP_TOKEN", token)
    get_settings.cache_clear()
    try:
        # --- Step 1: seed a run at RECEIVED (the default) + enqueue its job -
        run_id = _seed_run_for_queue_proof()
        job_id = repo.enqueue_job(
            kind=JobKind.RUN_PIPELINE,
            dedup_key=f"queueproof-pump-anchor:{uuid.uuid4()}",
            run_id=run_id,
        )
        assert job_id is not None

        # --- Step 2: backdate available_at into the FUTURE, direct SQL, this
        # module's existing backdating idiom (no sleep) --------------------
        with repo.get_connection() as conn, conn.transaction():
            conn.execute(
                "UPDATE jobs SET available_at = now() + interval '1 hour'"
                " WHERE id = %s",
                (str(job_id),),
            )

        # --- Step 3: the precondition that makes the rest meaningful -------
        assert live_queue_worker_threads() == [], (
            "this proof requires ZERO live queue-worker threads on this "
            "instance — a running worker would race ahead of the pump and "
            "make the pump's own contribution unprovable, the vacuous twin "
            "this file's own module docstring names"
        )

        # --- Step 4: genuinely NOT claimable while future-dated ------------
        assert repo.claim_job() is None, (
            "a future-dated job must not be claimable yet — if this claims, "
            "the backdate above did not take and the drain below would "
            "prove nothing about the pump reclaiming a future-due job"
        )

        # --- Step 5: move available_at into the past ------------------------
        with repo.get_connection() as conn, conn.transaction():
            conn.execute(
                "UPDATE jobs SET available_at = now() - interval '1 second'"
                " WHERE id = %s",
                (str(job_id),),
            )

        # --- Step 6: hit the HTTP endpoint — never drain.drain_once() ------
        # directly; criterion #2 is specifically about the endpoint the
        # external cron calls.
        client = TestClient(app_main.app)
        response = client.get(
            "/internal/pump", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200, response.text
        body = response.json()

        # --- Step 7: the response reports real per-job outcomes, never a
        # bare 200 ------------------------------------------------------------
        assert body["claimed"] == 1, body
        assert body["done"] == 1, body

        # --- Step 8: the handler-side observable — the CORRECT run ran
        # exactly once, not merely "some job reached done" ------------------
        assert orchestrator_calls == [run_id], (
            "the pump must have driven THIS run's handler exactly once — a "
            "job marked done on an ERROR run (pipeline.py:74, unstubbed) or "
            "a stranger's run would not show up here"
        )

        # --- Step 9: re-read the row/run by their own ids -------------------
        final_job = repo.get_job(job_id)
        assert final_job is not None
        assert final_job["state"] == "done"

        final_run = repo.load_run(run_id)
        assert final_run is not None
        assert final_run["status"] == "computed", (
            "the run must show the stub's OBSERVABLE post-handler status "
            "(COMPUTED — in-flight, non-terminal), never "
            "merely 'the job row says done' while the run itself never ran"
        )

        # --- Step 10: queue_depth reflects the completed job, live ----------
        assert body["queue_depth"] == 0, (
            "the sole open job just completed; queue_depth must reflect "
            "that live, not a stale count"
        )
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# The LIVE half of count_open_jobs (17-05) — the behavioral proof 17-02's
# FakeConnection test could not give: a real pending/leased/done/dead
# population against actual Postgres, exact open count.
# ---------------------------------------------------------------------------


def test_count_open_jobs_live_mixed_population(seeded_db) -> None:
    """Built sequentially, not concurrently — claim_job() has no "claim THIS
    id" API, so a job is only unambiguously claimed while it is the SOLE
    claimable row in this test's (isolated) table. Each state is verified by
    its own id before the count is trusted, and the count is re-checked after
    one more transition to prove it reads live state on every call rather
    than returning something memoized from the first read.
    """
    from app.db import repo
    from app.models.job import JobKind

    # --- leased: claim immediately, while it is the only row in the table --
    leased_run_id = _seed_run_for_queue_proof()
    leased_job_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-mixed-leased:{uuid.uuid4()}",
        run_id=leased_run_id,
    )
    assert leased_job_id is not None
    leased_claim = repo.claim_job()
    assert leased_claim is not None
    assert leased_claim.id == leased_job_id

    # --- done: enqueue, claim (the only claimable row), complete -----------
    done_run_id = _seed_run_for_queue_proof()
    done_job_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-mixed-done:{uuid.uuid4()}",
        run_id=done_run_id,
    )
    assert done_job_id is not None
    done_claim = repo.claim_job()
    assert done_claim is not None
    assert done_claim.id == done_job_id
    assert repo.complete_job(done_claim.id, done_claim.lease_token) is True

    # --- dead: direct SQL, mirroring this module's existing backdating idiom
    dead_run_id = _seed_run_for_queue_proof()
    dead_job_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-mixed-dead:{uuid.uuid4()}",
        run_id=dead_run_id,
    )
    assert dead_job_id is not None
    with repo.get_connection() as conn, conn.transaction():
        conn.execute("UPDATE jobs SET state = 'dead' WHERE id = %s", (str(dead_job_id),))

    # --- pending: left untouched ---------------------------------------------
    pending_run_id = _seed_run_for_queue_proof()
    pending_job_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"queueproof-mixed-pending:{uuid.uuid4()}",
        run_id=pending_run_id,
    )
    assert pending_job_id is not None

    # --- verify each row's own state, by id, before trusting the count -----
    leased_row = repo.get_job(leased_job_id)
    done_row = repo.get_job(done_job_id)
    dead_row = repo.get_job(dead_job_id)
    pending_row = repo.get_job(pending_job_id)
    assert leased_row is not None
    assert done_row is not None
    assert dead_row is not None
    assert pending_row is not None
    assert leased_row["state"] == "leased"
    assert done_row["state"] == "done"
    assert dead_row["state"] == "dead"
    assert pending_row["state"] == "pending"

    assert repo.count_open_jobs() == 2, (
        "count_open_jobs must count exactly the pending+leased rows "
        "(leased_job_id, pending_job_id) and exclude done/dead — the live "
        "behavioral half 17-02's FakeConnection test could not prove"
    )

    # --- prove it reads live state, not something memoized from the first
    # call above: complete the leased job and confirm the count drops -------
    assert repo.complete_job(leased_claim.id, leased_claim.lease_token) is True
    assert repo.count_open_jobs() == 1, (
        "count_open_jobs must reflect the completion live — dropping from 2 "
        "to 1 once the leased job (not the still-pending one) transitions "
        "to done"
    )
