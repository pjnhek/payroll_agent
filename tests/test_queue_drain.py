"""Hermetic proofs for the queue's execution layer.

Covers `drain_once()`'s claim/dispatch/complete-or-fail cycle,
`handle_run_pipeline`'s reclaim rewind and INVARIANT J-1's CAS, the static
J-1 CAS-only guard, and the failure taxonomy: a catastrophic START failure is
RETRIED (the job returns to pending), while a STAGE failure the pipeline already
handled itself COMPLETES the job. Everything here runs against `fake_repo` (the
in-memory mirror) — the live-DB durability proofs live in
`tests/test_queue_durability.py`.

THE J-1 CAS-ONLY GUARD (`test_queue_tier_status_writers_are_cas_only`) FAILS
CLOSED. A guard that only collects `repo.<name>(...)` calls by matching the
literal bound name "repo" is trivially bypassable: an alias (`r = repo`), a
`getattr` indirection, or — the sneakiest bypass, and the reason this guard
resolves the whole first-party import graph rather than just the names bound
to the repo module — a chain that never binds a name to `repo` at all
(`import app.db as db; db.repo.set_status(...)`, or the plain, unaliased
`import app.db.repo`, which binds only the ROOT name `app`). The resolver
below (`_module_bindings`, `_resolve_call_chain`, `_scan_file`) walks every
`ast.Import`/`ast.ImportFrom` in a file to build a LOCAL NAME -> DOTTED
MODULE map, treats any name bound to `app`, `app.db`, `app.db.repo`, or any
`app.db.repo.*` submodule as RESTRICTED (every module name a dotted chain
could use to arrive at the repo facade), and then REFUSES — fails the file,
by name and line — any restricted name that appears anywhere other than as
the root of a fully-resolved, actually-called attribute chain. Two
`app/queue/`-specific shapes are deliberately UNRESTRICTED and must stay
green: `dispatch.py` storing the `pipeline` module object inside its
`HANDLERS` table (the module is not repo-reaching), and `dispatch.handle`'s
`getattr(module, name)(job)` (both `module` and `name` are local variables,
never bound import names).

A resolver that silently matched nothing would pass every assertion in
`test_queue_tier_status_writers_are_cas_only` while inspecting zero calls —
the guard's own Pass 3 check is written NEGATIVE/subset-based specifically so
it is vacuously true on an empty result, which is exactly why
`test_the_guard_actually_resolves_the_queue_tiers_real_calls` exists as a
SEPARATE, POSITIVE proof that the resolver actually saw the real code.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib
import threading
import time
import uuid
from typing import Any, cast

import pytest

from app.db import repo
from app.models.job import Job, JobKind
from app.models.status import RunStatus
from app.pipeline.result import PipelineOutcome, PipelineReason, PipelineResult, PipelineStage
from app.queue import dispatch, drain
from app.queue.drain import DrainOutcome
from app.queue.handlers import pipeline
from app.routes import pipeline_glue

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
QUEUE_ROOT = REPO_ROOT / "app" / "queue"


# ── seeding helpers ──────────────────────────────────────────────────────


def _coastal_business_id(fake_repo: Any) -> uuid.UUID:
    business_id: uuid.UUID = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    return business_id


def _seed_run(fake_repo: Any, *, status: RunStatus) -> uuid.UUID:
    """A run with no source email — none of these tests ever run a real
    extraction, so there is nothing for that email row to be read by."""
    run_id: uuid.UUID = fake_repo.create_run(
        business_id=_coastal_business_id(fake_repo), source_email_id=None
    )
    fake_repo.set_status(run_id, status)
    return run_id


def _job(
    *,
    run_id: uuid.UUID | None,
    attempts: int = 1,
    max_attempts: int = 5,
    kind: JobKind = JobKind.RUN_PIPELINE,
) -> Job:
    return Job(
        id=uuid.uuid4(),
        kind=kind,
        run_id=run_id,
        attempts=attempts,
        max_attempts=max_attempts,
        lease_token=uuid.uuid4(),
    )


# ── Classified settlement coordinator ────────────────────────────────────────


def _claim_seeded_job(fake_repo: Any, run_id: uuid.UUID, *, max_attempts: int = 5) -> Job:
    job_id = fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"settlement:{run_id}:{uuid.uuid4()}",
        run_id=run_id,
        max_attempts=max_attempts,
    )
    assert job_id is not None
    row = fake_repo.jobs[str(job_id)]
    row["state"] = "leased"
    row["attempts"] += 1
    row["lease_token"] = uuid.uuid4()
    return Job(
        id=job_id,
        kind=JobKind.RUN_PIPELINE,
        run_id=run_id,
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        lease_token=row["lease_token"],
    )


def _claim_ingest_job(fake_repo: Any, *, max_attempts: int = 5) -> Job:
    event_id = uuid.uuid4()
    job_id = fake_repo.enqueue_job(
        kind=JobKind.INGEST,
        dedup_key=f"ingest:{event_id}",
        event_id=event_id,
        max_attempts=max_attempts,
    )
    assert job_id is not None
    claimed = fake_repo.claim_job()
    assert claimed is not None and claimed.id == job_id
    assert claimed.kind is JobKind.INGEST
    assert claimed.run_id is None
    assert claimed.event_id == event_id
    return cast(Job, claimed)


def test_classified_settlement_matrix_is_atomic_in_fake_repo(fake_repo):
    from app.db.repo.job_settlement import SettlementOutcome

    ok_run = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    ok_job = _claim_seeded_job(fake_repo, ok_run)
    assert repo.settle_pipeline_job(
        ok_job,
        PipelineResult(outcome=PipelineOutcome.OK),
        backoff_seconds=5.0,
    ) is SettlementOutcome.DONE
    assert fake_repo.get_job(ok_job.id)["state"] == "done"
    assert fake_repo.runs[str(ok_run)]["status"] == RunStatus.EXTRACTING.value

    retry_run = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    retry_job = _claim_seeded_job(fake_repo, retry_run)
    retryable = PipelineResult(
        outcome=PipelineOutcome.RETRYABLE,
        stage=PipelineStage.EXTRACT,
        reason=PipelineReason.PROVIDER_TIMEOUT,
    )
    assert repo.settle_pipeline_job(
        retry_job, retryable, backoff_seconds=5.0
    ) is SettlementOutcome.RETRIED
    assert fake_repo.get_job(retry_job.id)["state"] == "pending"
    assert fake_repo.get_job(retry_job.id)["last_error"] == retryable.diagnostic_code
    assert fake_repo.runs[str(retry_run)]["status"] == RunStatus.RECEIVED.value

    dead_run = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    dead_job = _claim_seeded_job(fake_repo, dead_run, max_attempts=1)
    assert repo.settle_pipeline_job(
        dead_job, retryable, backoff_seconds=5.0
    ) is SettlementOutcome.DEAD
    assert fake_repo.get_job(dead_job.id)["state"] == "dead"
    assert fake_repo.runs[str(dead_run)]["status"] == RunStatus.ERROR.value
    assert fake_repo.runs[str(dead_run)]["error_reason"] == "RetryExhausted"

    terminal_run = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    terminal_job = _claim_seeded_job(fake_repo, terminal_run)
    terminal = PipelineResult(
        outcome=PipelineOutcome.TERMINAL,
        stage=PipelineStage.COMPUTE,
        reason=PipelineReason.UNCLASSIFIED,
    )
    assert repo.settle_pipeline_job(
        terminal_job, terminal, backoff_seconds=5.0
    ) is SettlementOutcome.DONE
    assert fake_repo.get_job(terminal_job.id)["state"] == "done"
    assert fake_repo.runs[str(terminal_run)]["status"] == RunStatus.ERROR.value


@pytest.mark.parametrize(
    ("result", "max_attempts", "expected_outcome", "expected_state"),
    [
        (
            PipelineResult(outcome=PipelineOutcome.OK),
            5,
            "done",
            "done",
        ),
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
def test_null_run_ingest_settlement_is_transport_only_in_fake_repo(
    fake_repo,
    result: PipelineResult,
    max_attempts: int,
    expected_outcome: str,
    expected_state: str,
) -> None:
    from app.db.repo.job_settlement import SettlementOutcome

    before_runs = {run_id: dict(row) for run_id, row in fake_repo.runs.items()}
    claimed = _claim_ingest_job(fake_repo, max_attempts=max_attempts)

    outcome = repo.settle_pipeline_job(
        claimed,
        result,
        backoff_seconds=7.0,
    )

    assert outcome is SettlementOutcome(expected_outcome)
    row = fake_repo.get_job(claimed.id)
    assert row is not None
    assert row["state"] == expected_state
    assert row["lease_token"] is None
    assert fake_repo.runs == before_runs
    if result.outcome is not PipelineOutcome.OK:
        assert row["last_error"] == result.diagnostic_code
    if expected_state == "pending":
        assert row["available_in_seconds"] == 7.0


@pytest.mark.parametrize(
    ("result", "attempts", "max_attempts", "expected_outcome", "target_state"),
    [
        (PipelineResult(outcome=PipelineOutcome.OK), 1, 5, "done", "done"),
        (
            PipelineResult(
                outcome=PipelineOutcome.RETRYABLE,
                stage=PipelineStage.LOAD,
                reason=PipelineReason.PROVIDER_TIMEOUT,
            ),
            1,
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
            1,
            5,
            "done",
            "done",
        ),
    ],
)
def test_null_run_ingest_real_coordinator_never_calls_payroll_writers(
    fake_conn,
    monkeypatch,
    result: PipelineResult,
    attempts: int,
    max_attempts: int,
    expected_outcome: str,
    target_state: str,
) -> None:
    from app.db.repo import job_settlement

    claimed = _job(
        run_id=None,
        attempts=attempts,
        max_attempts=max_attempts,
        kind=JobKind.INGEST,
    )
    fake_conn.script_fetchone(
        (attempts, max_attempts, None, JobKind.INGEST.value)
    )
    fake_conn.script_fetchone((claimed.id,))

    def _fail_payroll_writer(*_args, **_kwargs):
        raise AssertionError("null-run ingest settlement reached a payroll writer")

    monkeypatch.setattr(job_settlement, "_rewind_run", _fail_payroll_writer)
    monkeypatch.setattr(job_settlement, "_set_run_error", _fail_payroll_writer)
    monkeypatch.setattr(job_settlement, "_lock_run_status", _fail_payroll_writer)

    outcome = job_settlement.settle_pipeline_job(
        claimed,
        result,
        backoff_seconds=9.0,
        conn=fake_conn,
    )

    assert outcome is job_settlement.SettlementOutcome(expected_outcome)
    assert "payroll_runs" not in fake_conn.all_sql()
    update_sql, update_params = fake_conn.executed[-1]
    assert "UPDATE jobs SET state" in str(update_sql)
    assert target_state in update_params
    if result.outcome is not PipelineOutcome.OK:
        assert result.diagnostic_code in update_params


def test_null_run_ingest_stale_token_is_fenced_before_any_transport_or_payroll_write(
    fake_conn,
    monkeypatch,
) -> None:
    from app.db.repo import job_settlement

    stale = _job(run_id=None, kind=JobKind.INGEST)
    fake_conn.script_fetchone(None)

    def _fail_writer(*_args, **_kwargs):
        raise AssertionError("stale ingest worker reached a writer")

    monkeypatch.setattr(job_settlement, "_rewind_run", _fail_writer)
    monkeypatch.setattr(job_settlement, "_set_run_error", _fail_writer)
    monkeypatch.setattr(job_settlement, "_lock_run_status", _fail_writer)

    assert job_settlement.settle_pipeline_job(
        stale,
        PipelineResult(outcome=PipelineOutcome.OK),
        backoff_seconds=1.0,
        conn=fake_conn,
    ) is job_settlement.SettlementOutcome.FENCED
    assert len(fake_conn.executed) == 1
    assert "payroll_runs" not in fake_conn.all_sql()


def test_null_run_ingest_infrastructure_failure_uses_bounded_transport_retry(
    fake_repo,
) -> None:
    from app.db.repo.job_settlement import SettlementOutcome

    claimed = _claim_ingest_job(fake_repo)
    before_runs = {run_id: dict(row) for run_id, row in fake_repo.runs.items()}

    assert repo.settle_infrastructure_failure(
        claimed,
        backoff_seconds=11.0,
        stage=PipelineStage.LOAD,
        reason=PipelineReason.PROVIDER_CONNECTION_FAILURE,
    ) is SettlementOutcome.RETRIED

    row = fake_repo.get_job(claimed.id)
    assert row is not None
    assert row["state"] == "pending"
    assert row["last_error"] == "load:provider_connection_failure"
    assert row["available_in_seconds"] == 11.0
    assert row["lease_token"] is None
    assert fake_repo.runs == before_runs


def test_operator_retry_uses_committed_resolution_identifier_only(fake_repo):
    from app.db.repo.job_settlement import SettlementOutcome

    run_id = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    resolution_id = uuid.uuid4()
    overrides = {"submitted worker": uuid.uuid4()}
    fake_repo.create_operator_resume_resolution(run_id, resolution_id, overrides)
    retryable = PipelineResult(
        outcome=PipelineOutcome.RETRYABLE,
        stage=PipelineStage.EXTRACT,
        reason=PipelineReason.PROVIDER_CONNECTION_FAILURE,
    )

    assert repo.enqueue_operator_resume_retry(
        run_id, resolution_id, retryable, available_in_seconds=5.0
    ) is SettlementOutcome.RETRIED
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.RECEIVED.value
    rows = list(fake_repo.jobs.values())
    assert len(rows) == 1
    assert rows[0]["kind"] == JobKind.OPERATOR_RESUME.value
    assert rows[0]["operator_resolution_id"] == resolution_id
    assert rows[0]["email_id"] is None
    assert "submitted worker" not in repr(rows[0])

    fake_repo.runs[str(run_id)]["status"] = RunStatus.EXTRACTING.value
    assert repo.enqueue_operator_resume_retry(
        run_id, resolution_id, retryable, available_in_seconds=5.0
    ) is SettlementOutcome.RETRIED
    assert len(fake_repo.jobs) == 1

    second_resolution = uuid.uuid4()
    fake_repo.create_operator_resume_resolution(run_id, second_resolution, overrides)
    fake_repo.runs[str(run_id)]["status"] = RunStatus.EXTRACTING.value
    assert repo.enqueue_operator_resume_retry(
        run_id, second_resolution, retryable, available_in_seconds=5.0
    ) is SettlementOutcome.RETRIED
    assert len(fake_repo.jobs) == 2


def test_settlement_lost_fences_leave_both_aggregates_unchanged(fake_repo):
    from app.db.repo.job_settlement import SettlementOutcome

    run_id = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    claimed = _claim_seeded_job(fake_repo, run_id)
    stale = dataclasses.replace(claimed, lease_token=uuid.uuid4())
    retryable = PipelineResult(
        outcome=PipelineOutcome.RETRYABLE,
        stage=PipelineStage.EXTRACT,
        reason=PipelineReason.PROVIDER_TIMEOUT,
    )
    before_job = dict(fake_repo.get_job(claimed.id))
    assert repo.settle_pipeline_job(
        stale, retryable, backoff_seconds=5.0
    ) is SettlementOutcome.FENCED
    assert fake_repo.get_job(claimed.id) == before_job
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.EXTRACTING.value


# ── handle_run_pipeline: the five behaviors ─────────────────────────────


def test_handler_attempts_1_received_cas_wins_and_pipeline_runs(fake_repo, monkeypatch):
    run_id = _seed_run(fake_repo, status=RunStatus.RECEIVED)
    calls: list[uuid.UUID] = []

    def _run(rid: uuid.UUID) -> PipelineResult:
        calls.append(rid)
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(
        pipeline_glue,
        "run_pipeline_now",
        _run,
    )

    pipeline.handle_run_pipeline(_job(run_id=run_id, attempts=1))

    assert calls == [run_id]
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.EXTRACTING.value


def test_handler_attempts_1_computed_cas_loses_no_run(fake_repo, monkeypatch):
    run_id = _seed_run(fake_repo, status=RunStatus.COMPUTED)
    calls: list[uuid.UUID] = []

    def _run(rid: uuid.UUID) -> PipelineResult:
        calls.append(rid)
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(
        pipeline_glue,
        "run_pipeline_now",
        _run,
    )

    pipeline.handle_run_pipeline(_job(run_id=run_id, attempts=1))

    assert calls == []
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.COMPUTED.value


def test_handler_attempts_2_extracting_rewinds_then_cas_wins(fake_repo, monkeypatch):
    run_id = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    calls: list[uuid.UUID] = []

    def _run(rid: uuid.UUID) -> PipelineResult:
        calls.append(rid)
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(
        pipeline_glue,
        "run_pipeline_now",
        _run,
    )

    pipeline.handle_run_pipeline(_job(run_id=run_id, attempts=2))

    assert calls == [run_id]
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.EXTRACTING.value


def test_handler_attempts_2_reconciled_rewind_is_a_noop_cas_loses(fake_repo, monkeypatch):
    run_id = _seed_run(fake_repo, status=RunStatus.RECONCILED)
    calls: list[uuid.UUID] = []

    def _run(rid: uuid.UUID) -> PipelineResult:
        calls.append(rid)
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(
        pipeline_glue,
        "run_pipeline_now",
        _run,
    )

    pipeline.handle_run_pipeline(_job(run_id=run_id, attempts=2))

    assert calls == []
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.RECONCILED.value


def test_reply_epoch_unchanged_across_every_handler_path(fake_repo, monkeypatch):
    """Neither the forward CAS nor the reclaim rewind ever bumps reply_epoch
    — only a human retrigger, through clear_reply_context, may grant the
    licence to email the client a second time."""
    monkeypatch.setattr(
        pipeline_glue,
        "run_pipeline_now",
        lambda rid: PipelineResult(outcome=PipelineOutcome.OK),
    )

    for status, attempts in (
        (RunStatus.RECEIVED, 1),
        (RunStatus.COMPUTED, 1),
        (RunStatus.EXTRACTING, 2),
        (RunStatus.RECONCILED, 2),
    ):
        run_id = _seed_run(fake_repo, status=status)
        before = fake_repo.runs[str(run_id)].get("reply_epoch", 0)
        pipeline.handle_run_pipeline(_job(run_id=run_id, attempts=attempts))
        after = fake_repo.runs[str(run_id)].get("reply_epoch", 0)
        assert after == before, f"reply_epoch moved for status={status!r} attempts={attempts}"


def test_handler_raises_on_missing_run_id(fake_repo):
    with pytest.raises(ValueError, match="no run_id"):
        pipeline.handle_run_pipeline(_job(run_id=None, attempts=1))


def test_first_durable_action_is_a_cas_on_both_branches(fake_repo, monkeypatch):
    """The restated INVARIANT J-1 makes 'first durable action' a conditional,
    not a fixed step — this proves both branches are internally consistent by
    recording the ORDERED sequence of business-status calls, not merely which
    ones fired. A set assertion would pass even with the calls reversed,
    which is exactly the bug (rewinding AFTER the CAS is a no-op and leaves
    the run stranded)."""
    order: list[str] = []
    orig_claim_status = repo.claim_status
    orig_rewind = repo.rewind_for_reclaim

    def _spy_claim_status(*args: Any, **kwargs: Any) -> bool:
        order.append("claim_status")
        result: bool = orig_claim_status(*args, **kwargs)
        return result

    def _spy_rewind(*args: Any, **kwargs: Any) -> bool:
        order.append("rewind_for_reclaim")
        result: bool = orig_rewind(*args, **kwargs)
        return result

    monkeypatch.setattr(repo, "claim_status", _spy_claim_status)
    monkeypatch.setattr(repo, "rewind_for_reclaim", _spy_rewind)
    monkeypatch.setattr(
        pipeline_glue,
        "run_pipeline_now",
        lambda rid: PipelineResult(outcome=PipelineOutcome.OK),
    )

    run_id_first_attempt = _seed_run(fake_repo, status=RunStatus.RECEIVED)
    pipeline.handle_run_pipeline(_job(run_id=run_id_first_attempt, attempts=1))
    assert order == ["claim_status"], order

    order.clear()
    run_id_reclaim = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    pipeline.handle_run_pipeline(_job(run_id=run_id_reclaim, attempts=2))
    assert order == ["rewind_for_reclaim", "claim_status"], order


def test_catastrophic_start_failure_is_retried_not_marked_done(fake_repo, monkeypatch):
    """This test was `..._marks_the_job_done_KNOWN_GAP_FAIL01`, and it PINNED a
    known gap: a catastrophic START failure was swallowed, the job was marked
    `done`, the durable row vanished as a success, and the run stranded
    mid-flight with nothing left to retry it — a silently lost payroll run,
    with a green suite. Its docstring said the fix must INVERT this assertion
    rather than delete the test. This is that inversion; the assertion below is
    the same one, flipped.

    The handler now calls `pipeline_glue.run_pipeline_now`, which lets a
    catastrophic start failure PROPAGATE (an import error, the database
    unreachable at the first read). `drain_once` catches it, routes it through
    the fenced `fail_job` write with backoff, and the job returns to `pending`
    to be retried — dead-lettering only after `max_attempts`. The explicit value
    propagates into fenced infrastructure settlement; a swallowing procedure here
    would instead make the durable job disappear as a false success.

    The forward CAS has already moved the run to EXTRACTING before the pipeline
    is invoked, so the run legitimately sits there while the retry is pending —
    what must NOT happen is the JOB disappearing as done.
    """
    run_id = _seed_run(fake_repo, status=RunStatus.RECEIVED)

    def _failing_run_pipeline_now(rid: uuid.UUID) -> None:
        raise RuntimeError("simulated catastrophic import/start failure")

    monkeypatch.setattr(pipeline_glue, "run_pipeline_now", _failing_run_pipeline_now)

    dedup_key = f"run_pipeline:{run_id}:0"
    job_id = fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE, dedup_key=dedup_key, run_id=run_id
    )
    assert job_id is not None

    assert drain.drain_once() == DrainOutcome.RETRIED

    job_row = fake_repo.get_job(job_id)
    assert job_row is not None
    # THE INVERTED ASSERTION. `done` here is the lost-run bug: it means the queue
    # threw away a payroll run it never actually executed.
    assert job_row["state"] == "pending", (
        "a catastrophic start failure must leave the job retryable, not `done` — "
        f"got {job_row['state']!r}. `done` is the silently-lost-run bug: the handler "
        "swallowed the failure, drain_once read that as success, and the durable row "
        "that was the run's only chance of ever executing was deleted from the queue."
    )
    assert job_row["attempts"] == 1
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.RECEIVED.value


def test_a_stage_failure_still_completes_the_job(fake_repo, monkeypatch):
    """The other half of the contract, and the reason the fix above is not simply
    "make every failure retry".

    A STAGE failure (the LLM refuses, the calc raises) is caught by the pipeline's
    OWN catch-all and returned as a bounded TERMINAL result. The drain's fenced
    settlement coordinator atomically records ERROR on the run and completes the job.
    Retrying it would re-run a terminal pipeline failure until dead-lettering.

    Only the catastrophic-START case (the pipeline never began at all) is a retry.
    This test is what stops a future "just retry everything" edit from turning every
    errored run into `max_attempts` duplicate executions.
    """
    run_id = _seed_run(fake_repo, status=RunStatus.RECEIVED)

    invocations: list[uuid.UUID] = []

    def _stage_failure_handled_internally(rid: uuid.UUID) -> PipelineResult:
        # Mirrors the orchestrator's own error-wrap: classify and return, leaving the
        # drain's coordinator as the sole terminal persistence owner.
        invocations.append(rid)
        return PipelineResult(
            outcome=PipelineOutcome.TERMINAL,
            stage=PipelineStage.COMPUTE,
            reason=PipelineReason.UNCLASSIFIED,
        )

    monkeypatch.setattr(
        pipeline_glue, "run_pipeline_now", _stage_failure_handled_internally
    )

    job_id = fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE, dedup_key=f"run_pipeline:{run_id}:0", run_id=run_id
    )
    assert job_id is not None
    assert drain.drain_once() == DrainOutcome.DONE

    job_row = fake_repo.get_job(job_id)
    assert job_row is not None
    assert job_row["state"] == "done", (
        "a terminal stage failure is atomically persisted by the drain coordinator — "
        "the job must complete, not retry a run that already recorded ERROR"
    )
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.ERROR.value
    # EXACTLY once. Without this, a handler that invoked the pipeline twice would
    # still land the run on ERROR and the job on done, and this test would call a
    # double-executed payroll a pass.
    assert invocations == [run_id], (
        f"the pipeline must be invoked exactly once per drained job; got {invocations}"
    )


# ── drain_once: the five behaviors ──────────────────────────────────────


def test_drain_once_empty_queue_returns_false_and_dispatches_nothing(fake_repo, monkeypatch):
    calls: list[Job] = []
    monkeypatch.setattr(dispatch, "handle", calls.append)

    assert drain.drain_once() == DrainOutcome.EMPTY
    assert calls == []


def test_send_handler_uses_only_the_frozen_snapshot_before_provider_work(
    fake_repo, monkeypatch
):
    from app.email import gateway
    from app.queue.handlers import send_outbound

    run_id = _seed_run(fake_repo, status=RunStatus.APPROVED)
    snapshot = fake_repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id="<frozen@example.test>",
        from_addr="sender@example.test",
        to_addr="recipient@example.test",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Frozen payroll",
        body_text="Frozen bytes only",
        attachments=[("paystub.pdf", b"frozen-pdf")],
    )
    job = _job(run_id=run_id, kind=JobKind.SEND_OUTBOUND)
    job = dataclasses.replace(job, email_id=snapshot["email_id"])
    observed: list[dict[str, object]] = []

    def send(stored_snapshot: dict[str, object]) -> PipelineResult:
        observed.append(stored_snapshot)
        return PipelineResult(outcome=PipelineOutcome.OK, stage=PipelineStage.DELIVERY)

    monkeypatch.setattr(gateway, "send_reserved_outbound_snapshot", send)
    assert send_outbound.handle_send_outbound(job).outcome is PipelineOutcome.OK
    assert observed == [snapshot]


def test_send_handler_drops_unowned_or_stale_context_before_provider_work(
    fake_repo, monkeypatch
):
    from app.email import gateway
    from app.queue.handlers import send_outbound

    run_id = _seed_run(fake_repo, status=RunStatus.APPROVED)
    other_run_id = _seed_run(fake_repo, status=RunStatus.APPROVED)
    snapshot = fake_repo.reserve_outbound_snapshot(
        run_id=other_run_id,
        purpose="confirmation",
        round=0,
        message_id="<other@example.test>",
        from_addr="sender@example.test",
        to_addr="recipient@example.test",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Other frozen payroll",
        body_text="Other bytes only",
        attachments=[],
    )
    job = dataclasses.replace(
        _job(run_id=run_id, kind=JobKind.SEND_OUTBOUND),
        email_id=snapshot["email_id"],
    )

    monkeypatch.setattr(
        gateway,
        "send_reserved_outbound_snapshot",
        lambda *_args: pytest.fail("provider work must not run for unowned context"),
    )
    result = send_outbound.handle_send_outbound(job)
    assert result.outcome is PipelineOutcome.OK


def test_send_drain_uses_delivery_settlement_with_the_claimed_lease(
    fake_repo, monkeypatch
):
    from app.db.repo.job_settlement import SettlementOutcome

    run_id = _seed_run(fake_repo, status=RunStatus.APPROVED)
    snapshot = fake_repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id="<settled@example.test>",
        from_addr="sender@example.test",
        to_addr="recipient@example.test",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Frozen payroll",
        body_text="Frozen bytes only",
        attachments=[],
    )
    job_id = fake_repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=f"send_outbound:{snapshot['email_id']}",
        run_id=run_id,
        email_id=snapshot["email_id"],
    )
    assert job_id is not None
    expected = PipelineResult(outcome=PipelineOutcome.OK, stage=PipelineStage.DELIVERY)
    monkeypatch.setattr(dispatch, "handle", lambda _job: expected)
    observed: list[tuple[Job, PipelineResult]] = []

    def settle(job: Job, result: PipelineResult) -> SettlementOutcome:
        observed.append((job, result))
        return SettlementOutcome.DONE

    monkeypatch.setattr(repo, "settle_outbound_delivery_job", settle)
    assert drain.drain_once() is DrainOutcome.DONE
    assert observed[0][0].id == job_id
    assert observed[0][0].lease_token is not None
    assert observed[0][1] is expected


def test_send_drain_settles_a_frozen_snapshot_through_the_fake_pair(
    fake_repo, monkeypatch
):
    from app.email import gateway

    run_id = _seed_run(fake_repo, status=RunStatus.APPROVED)
    snapshot = fake_repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id="<paired@example.test>",
        from_addr="sender@example.test",
        to_addr="recipient@example.test",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Frozen payroll",
        body_text="Frozen bytes only",
        attachments=[],
    )
    job_id = fake_repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=f"send_outbound:{snapshot['email_id']}",
        run_id=run_id,
        email_id=snapshot["email_id"],
    )
    assert job_id is not None
    monkeypatch.setattr(
        gateway,
        "send_reserved_outbound_snapshot",
        lambda _snapshot: PipelineResult(
            outcome=PipelineOutcome.OK, stage=PipelineStage.DELIVERY
        ),
    )

    assert drain.drain_once() is DrainOutcome.DONE
    assert fake_repo.get_job(job_id)["state"] == "done"
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.RECONCILED.value


def test_send_handler_exception_never_reaches_generic_settlement(
    fake_repo, monkeypatch
):
    from app.db.repo.job_settlement import SettlementOutcome

    run_id = _seed_run(fake_repo, status=RunStatus.APPROVED)
    snapshot = fake_repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id="<handler-error@example.test>",
        from_addr="sender@example.test",
        to_addr="recipient@example.test",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Frozen payroll",
        body_text="Frozen bytes only",
        attachments=[],
    )
    job_id = fake_repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=f"send_outbound:{snapshot['email_id']}",
        run_id=run_id,
        email_id=snapshot["email_id"],
    )
    assert job_id is not None
    monkeypatch.setattr(
        dispatch,
        "handle",
        lambda _job: (_ for _ in ()).throw(RuntimeError("unexpected handler failure")),
    )
    observed: list[PipelineResult] = []

    def settle(_job: Job, result: PipelineResult) -> SettlementOutcome:
        observed.append(result)
        return SettlementOutcome.DONE

    monkeypatch.setattr(repo, "settle_outbound_delivery_job", settle)
    monkeypatch.setattr(
        repo,
        "settle_infrastructure_failure",
        lambda *_args, **_kwargs: pytest.fail("generic settlement must not run"),
    )

    assert drain.drain_once() is DrainOutcome.DONE
    assert observed == [PipelineResult(stage=PipelineStage.DELIVERY)]


def test_final_attempt_reap_runs_only_after_empty_claim_and_stays_truthy(
    fake_repo, monkeypatch
):
    from app.db.repo.job_settlement import SettlementOutcome

    calls: list[str] = []

    def _claim():
        calls.append("claim")
        return None

    def _reap() -> SettlementOutcome:
        calls.append("reap")
        return SettlementOutcome.REAPED_FINAL_LEASE

    monkeypatch.setattr(repo, "claim_job", _claim)
    monkeypatch.setattr(
        repo,
        "reap_expired_final_attempt",
        _reap,
    )

    outcome = drain.drain_once()
    assert outcome == DrainOutcome.REAPED_FINAL_LEASE
    assert bool(outcome)
    assert not bool(DrainOutcome.EMPTY)
    assert calls == ["claim", "reap"]


def test_normal_claim_precedes_reap_and_each_call_settles_at_most_one(
    fake_repo, monkeypatch
):
    normal_run = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    normal_id = fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"normal-before-reap:{uuid.uuid4()}",
        run_id=normal_run,
    )
    assert normal_id is not None

    reaped_run = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    reaped_id = fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"expired-final:{uuid.uuid4()}",
        run_id=reaped_run,
        max_attempts=1,
    )
    assert reaped_id is not None
    reaped_row = fake_repo.jobs[str(reaped_id)]
    reaped_row["state"] = "leased"
    reaped_row["attempts"] = reaped_row["max_attempts"]
    reaped_row["lease_token"] = uuid.uuid4()
    reaped_row["lease_expired"] = True
    reaped_row["last_error"] = "extract:provider_timeout"

    monkeypatch.setattr(
        dispatch, "handle", lambda job: PipelineResult(outcome=PipelineOutcome.OK)
    )

    assert drain.drain_once() == DrainOutcome.DONE
    assert fake_repo.get_job(normal_id)["state"] == "done"
    assert fake_repo.get_job(reaped_id)["state"] == "leased"

    assert drain.drain_once() == DrainOutcome.REAPED_FINAL_LEASE
    assert fake_repo.get_job(reaped_id)["state"] == "dead"
    run = fake_repo.runs[str(reaped_run)]
    assert run["status"] == RunStatus.ERROR.value
    assert run["error_reason"] == "FinalAttemptLeaseExpired"
    assert "provider_timeout" not in run["error_detail"]

    assert drain.drain_once() == DrainOutcome.EMPTY


@pytest.mark.parametrize(
    ("attempts", "max_attempts", "lease_expired"),
    [(1, 2, True), (2, 2, False)],
)
def test_final_attempt_reap_ignores_near_miss_rows(
    fake_repo, attempts, max_attempts, lease_expired
):
    run_id = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    job_id = fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"reap-near-miss:{uuid.uuid4()}",
        run_id=run_id,
        max_attempts=max_attempts,
    )
    assert job_id is not None
    row = fake_repo.jobs[str(job_id)]
    row["state"] = "leased"
    row["attempts"] = attempts
    row["lease_token"] = uuid.uuid4()
    row["lease_expired"] = lease_expired

    assert drain.drain_once() == DrainOutcome.EMPTY
    assert fake_repo.get_job(job_id)["state"] == "leased"
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.EXTRACTING.value


def test_null_run_ingest_expired_final_attempt_is_reaped_without_payroll_write(
    fake_repo,
    fake_conn,
    monkeypatch,
) -> None:
    from app.db.repo import job_settlement
    from app.db.repo.job_settlement import SettlementOutcome

    claimed = _claim_ingest_job(fake_repo, max_attempts=1)
    row = fake_repo.jobs[str(claimed.id)]
    row.update(
        lease_expired=True,
        leased_until="expired",
        last_error="ingest:provider_timeout",
    )
    before_runs = {run_id: dict(run) for run_id, run in fake_repo.runs.items()}
    assert repo.reap_expired_final_attempt() is SettlementOutcome.REAPED_FINAL_LEASE
    assert row["state"] == "dead"
    assert row["lease_token"] is None
    assert row["leased_until"] is None
    assert row["last_error"] == "ingest:provider_timeout"
    assert fake_repo.runs == before_runs

    production_job = _job(
        run_id=None,
        attempts=1,
        max_attempts=1,
        kind=JobKind.INGEST,
    )
    fake_conn.script_fetchone(
        (production_job.id, None, 1, 1, JobKind.INGEST.value)
    )
    fake_conn.script_fetchone((production_job.id,))

    def _fail_payroll_writer(*_args, **_kwargs):
        raise AssertionError("null-run ingest reap reached a payroll writer")

    monkeypatch.setattr(job_settlement, "_lock_run_status", _fail_payroll_writer)
    monkeypatch.setattr(job_settlement, "_set_run_error", _fail_payroll_writer)

    assert job_settlement.reap_expired_final_attempt(
        conn=fake_conn
    ) is SettlementOutcome.REAPED_FINAL_LEASE
    assert "payroll_runs" not in fake_conn.all_sql()
    update_sql, update_params = fake_conn.executed[-1]
    assert "state = 'dead'" in str(update_sql)
    assert str(production_job.id) in update_params


_FINAL_LEASE_ERROR_STATUSES = {
    RunStatus.RECEIVED,
    RunStatus.EXTRACTING,
    RunStatus.COMPUTED,
    RunStatus.APPROVED,
}
_FINAL_LEASE_PRESERVE_STATUSES = {
    RunStatus.SENT,
    RunStatus.AWAITING_REPLY,
    RunStatus.AWAITING_APPROVAL,
    RunStatus.NEEDS_OPERATOR,
    RunStatus.RECONCILED,
    RunStatus.REJECTED,
    RunStatus.ERROR,
}


def test_final_attempt_status_matrix_is_disjoint_and_exhaustive() -> None:
    from app.db.repo import job_settlement

    assert job_settlement._FINAL_LEASE_ERROR_STATUSES == _FINAL_LEASE_ERROR_STATUSES
    assert (
        job_settlement._FINAL_LEASE_PRESERVE_STATUSES
        == _FINAL_LEASE_PRESERVE_STATUSES
    )
    assert not (
        job_settlement._FINAL_LEASE_ERROR_STATUSES
        & job_settlement._FINAL_LEASE_PRESERVE_STATUSES
    )
    assert set(RunStatus) == (
        job_settlement._FINAL_LEASE_ERROR_STATUSES
        | job_settlement._FINAL_LEASE_PRESERVE_STATUSES
    )


@pytest.mark.parametrize("status", list(RunStatus))
def test_final_attempt_reap_settles_every_run_status(
    fake_repo, status: RunStatus
) -> None:
    run_id = _seed_run(fake_repo, status=status)
    run = fake_repo.runs[str(run_id)]
    run["error_reason"] = "existing_reason"
    run["error_detail"] = "existing_detail"
    job_id = fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"reap-status-matrix:{status.value}:{uuid.uuid4()}",
        run_id=run_id,
        max_attempts=1,
    )
    assert job_id is not None
    job = fake_repo.jobs[str(job_id)]
    job.update(
        state="leased",
        attempts=1,
        lease_token=uuid.uuid4(),
        lease_expired=True,
        leased_until="expired",
        last_error="extract:provider_timeout",
    )

    assert drain.drain_once() == DrainOutcome.REAPED_FINAL_LEASE
    assert job["state"] == "dead"
    assert job["lease_token"] is None
    assert job["leased_until"] is None
    assert job["last_error"] == "extract:provider_timeout"

    if status in _FINAL_LEASE_ERROR_STATUSES:
        assert run["status"] == RunStatus.ERROR.value
        assert run["error_reason"] == "FinalAttemptLeaseExpired"
        assert run["error_detail"] == (
            "unknown:final_attempt_lease_expired;attempts=1/1"
        )
    else:
        assert run["status"] == status.value
        assert run["error_reason"] == "existing_reason"
        assert run["error_detail"] == "existing_detail"


def test_final_attempt_preserved_oldest_does_not_starve_next_active_candidate(
    fake_repo,
) -> None:
    awaiting_run = _seed_run(fake_repo, status=RunStatus.AWAITING_APPROVAL)
    extracting_run = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    job_ids: list[uuid.UUID] = []
    for order, run_id in enumerate((awaiting_run, extracting_run), start=1):
        job_id = fake_repo.enqueue_job(
            kind=JobKind.RUN_PIPELINE,
            dedup_key=f"reap-starvation:{order}:{uuid.uuid4()}",
            run_id=run_id,
            max_attempts=1,
        )
        assert job_id is not None
        fake_repo.jobs[str(job_id)].update(
            state="leased",
            attempts=1,
            lease_token=uuid.uuid4(),
            lease_expired=True,
            leased_until="expired",
            leased_until_order=order,
            last_error=f"attempt-{order}",
        )
        job_ids.append(job_id)

    assert drain.drain_once() == DrainOutcome.REAPED_FINAL_LEASE
    assert fake_repo.get_job(job_ids[0])["state"] == "dead"
    assert fake_repo.get_job(job_ids[1])["state"] == "leased"
    assert fake_repo.runs[str(awaiting_run)]["status"] == RunStatus.AWAITING_APPROVAL.value

    assert drain.drain_once() == DrainOutcome.REAPED_FINAL_LEASE
    assert fake_repo.get_job(job_ids[1])["state"] == "dead"
    assert fake_repo.runs[str(extracting_run)]["status"] == RunStatus.ERROR.value

    assert drain.drain_once() == DrainOutcome.EMPTY


@pytest.mark.parametrize(
    ("result", "max_attempts", "expected_outcome", "expected_job", "expected_run"),
    [
        (
            PipelineResult(outcome=PipelineOutcome.OK),
            5,
            DrainOutcome.DONE,
            "done",
            RunStatus.EXTRACTING,
        ),
        (
            PipelineResult(
                outcome=PipelineOutcome.RETRYABLE,
                stage=PipelineStage.EXTRACT,
                reason=PipelineReason.PROVIDER_TIMEOUT,
            ),
            5,
            DrainOutcome.RETRIED,
            "pending",
            RunStatus.RECEIVED,
        ),
        (
            PipelineResult(
                outcome=PipelineOutcome.RETRYABLE,
                stage=PipelineStage.EXTRACT,
                reason=PipelineReason.PROVIDER_TIMEOUT,
            ),
            1,
            DrainOutcome.DEAD,
            "dead",
            RunStatus.ERROR,
        ),
        (
            PipelineResult(
                outcome=PipelineOutcome.TERMINAL,
                stage=PipelineStage.COMPUTE,
                reason=PipelineReason.UNCLASSIFIED,
            ),
            5,
            DrainOutcome.DONE,
            "done",
            RunStatus.ERROR,
        ),
    ],
)
def test_drain_once_maps_pipeline_results_through_atomic_settlement(
    fake_repo,
    monkeypatch,
    result,
    max_attempts,
    expected_outcome,
    expected_job,
    expected_run,
):
    run_id = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    job_id = fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"result-aware:{run_id}:{uuid.uuid4()}",
        run_id=run_id,
        max_attempts=max_attempts,
    )
    assert job_id is not None
    monkeypatch.setattr(dispatch, "handle", lambda job: result)

    assert drain.drain_once() == expected_outcome
    assert fake_repo.get_job(job_id)["state"] == expected_job
    assert fake_repo.runs[str(run_id)]["status"] == expected_run.value


def test_pipeline_handler_forwards_result_and_cas_loser_returns_ok(fake_repo, monkeypatch):
    run_id = _seed_run(fake_repo, status=RunStatus.RECEIVED)
    job = _job(run_id=run_id)
    retryable = PipelineResult(
        outcome=PipelineOutcome.RETRYABLE,
        stage=PipelineStage.EXTRACT,
        reason=PipelineReason.PROVIDER_TIMEOUT,
    )
    monkeypatch.setattr(pipeline_glue, "run_pipeline_now", lambda rid: retryable)

    assert pipeline.handle_run_pipeline(job) is retryable

    calls: list[uuid.UUID] = []
    monkeypatch.setattr(repo, "claim_status", lambda *args, **kwargs: False)
    monkeypatch.setattr(pipeline_glue, "run_pipeline_now", calls.append)
    result = pipeline.handle_run_pipeline(job)
    assert result == PipelineResult(outcome=PipelineOutcome.OK)
    assert calls == []


@pytest.mark.parametrize(
    ("max_attempts", "expected_outcome", "expected_job", "expected_run"),
    [
        (5, DrainOutcome.RETRIED, "pending", RunStatus.RECEIVED),
        (1, DrainOutcome.DEAD, "dead", RunStatus.ERROR),
    ],
)
def test_drain_once_infrastructure_exception_uses_atomic_settlement(
    fake_repo,
    monkeypatch,
    max_attempts,
    expected_outcome,
    expected_job,
    expected_run,
):
    run_id = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    job_id = fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"infrastructure:{run_id}:{uuid.uuid4()}",
        run_id=run_id,
        max_attempts=max_attempts,
    )
    assert job_id is not None

    def _raise(_job):
        raise RuntimeError("private provider detail must not persist")

    monkeypatch.setattr(dispatch, "handle", _raise)
    assert drain.drain_once() == expected_outcome
    row = fake_repo.get_job(job_id)
    assert row["state"] == expected_job
    assert row["last_error"] == "unknown:unclassified"
    assert "private provider detail" not in repr(row)
    assert fake_repo.runs[str(run_id)]["status"] == expected_run.value


def test_infrastructure_settlement_write_failure_re_raises_and_keeps_token(
    fake_repo, monkeypatch
):
    run_id = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"infrastructure-write:{run_id}:{uuid.uuid4()}",
        run_id=run_id,
    )
    claimed: list[Job] = []

    def _raise_dispatch(job):
        claimed.append(job)
        raise RuntimeError("dispatch failed")

    def _raise_settlement(*args, **kwargs):
        raise RuntimeError("settlement write failed")

    monkeypatch.setattr(dispatch, "handle", _raise_dispatch)
    monkeypatch.setattr(repo, "settle_infrastructure_failure", _raise_settlement)

    with pytest.raises(RuntimeError, match="settlement write failed"):
        drain.drain_once()
    assert drain.held_tokens() == [claimed[0].lease_token]
    drain._held_tokens.clear()


def test_drain_once_claims_dispatches_and_completes_with_the_same_token(fake_repo, monkeypatch):
    run_id = _seed_run(fake_repo, status=RunStatus.RECEIVED)
    dedup_key = f"run_pipeline:{run_id}:0"
    job_id = fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE, dedup_key=dedup_key, run_id=run_id
    )
    assert job_id is not None

    handled: list[Job] = []

    def _handle(job: Job) -> PipelineResult:
        handled.append(job)
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(dispatch, "handle", _handle)

    seen_settlement_tokens: list[uuid.UUID] = []
    orig_settle = repo.settle_pipeline_job

    def _spy_settle(job, result, *, backoff_seconds, conn=None):
        seen_settlement_tokens.append(job.lease_token)
        return orig_settle(
            job, result, backoff_seconds=backoff_seconds, conn=conn
        )

    monkeypatch.setattr(repo, "settle_pipeline_job", _spy_settle)

    assert drain.drain_once() == DrainOutcome.DONE

    assert len(handled) == 1
    claimed_job = handled[0]
    assert claimed_job.id == job_id
    # The exact lease_token object the claim returned — not merely "was called".
    assert seen_settlement_tokens == [claimed_job.lease_token]
    assert fake_repo.jobs[str(job_id)]["state"] == "done"


def test_held_tokens_populated_during_handler_and_cleared_after(fake_repo, monkeypatch):
    run_id = _seed_run(fake_repo, status=RunStatus.RECEIVED)
    dedup_key = f"run_pipeline:{run_id}:0"
    fake_repo.enqueue_job(kind=JobKind.RUN_PIPELINE, dedup_key=dedup_key, run_id=run_id)

    captured: dict[str, Any] = {}

    def _stub_handle(job: Job) -> PipelineResult:
        # Asserted FROM INSIDE the handler, not by inspection after the fact —
        # held_tokens() must be non-empty WHILE the handler is running.
        captured["token"] = job.lease_token
        captured["held_during"] = list(drain.held_tokens())
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(dispatch, "handle", _stub_handle)

    assert drain.held_tokens() == []
    assert drain.drain_once() == DrainOutcome.DONE
    assert captured["held_during"] == [captured["token"]]
    assert drain.held_tokens() == []


def test_drain_once_handler_raises_uses_infrastructure_settlement(fake_repo, monkeypatch):
    run_id = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    dedup_key = f"run_pipeline:{run_id}:0"
    job_id = fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE, dedup_key=dedup_key, run_id=run_id
    )
    assert job_id is not None

    def _raising_handle(job: Job) -> None:
        raise RuntimeError("simulated dispatch failure")

    monkeypatch.setattr(dispatch, "handle", _raising_handle)

    settlement_calls: list[dict[str, Any]] = []
    orig_settle = repo.settle_infrastructure_failure

    def _spy_settle(job, *, backoff_seconds, **kwargs):
        settlement_calls.append(
            {"job_id": job.id, "lease_token": job.lease_token, "backoff_seconds": backoff_seconds}
        )
        return orig_settle(job, backoff_seconds=backoff_seconds, **kwargs)

    monkeypatch.setattr(repo, "settle_infrastructure_failure", _spy_settle)

    assert drain.drain_once() == DrainOutcome.RETRIED

    assert len(settlement_calls) == 1
    assert settlement_calls[0]["backoff_seconds"] > 0
    assert fake_repo.jobs[str(job_id)]["state"] == "pending"  # attempts=1 < max_attempts=5


def test_drain_once_dispatch_raises_at_max_attempts_returns_dead(fake_repo, monkeypatch):
    """`fail_job`'s own MAX_ATTEMPTS CASE moves the row to `dead`, not
    `pending` — `drain_once()` must capture that specific `JobState.DEAD`
    return as `DrainOutcome.DEAD`, distinct from the backoff `RETRIED` case
    above."""
    run_id = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    dedup_key = f"run_pipeline:{run_id}:0"
    job_id = fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE, dedup_key=dedup_key, run_id=run_id, max_attempts=1
    )
    assert job_id is not None

    def _raising_handle(job: Job) -> None:
        raise RuntimeError("simulated dispatch failure")

    monkeypatch.setattr(dispatch, "handle", _raising_handle)

    assert drain.drain_once() == DrainOutcome.DEAD

    job_row = fake_repo.get_job(job_id)
    assert job_row is not None
    assert job_row["state"] == "dead", (
        "attempts (1) reached max_attempts (1) at claim — the job must "
        f"dead-letter, got {job_row['state']!r}"
    )


def test_drain_once_complete_job_fenced_out_returns_fenced(fake_repo, monkeypatch):
    """`complete_job` returning `False` means this worker's lease was
    reclaimed by someone else while it was still running the job — a
    SETTLED fence (drain.py's own docstring distinguishes this from the
    double-failure infra-outage branch, which re-raises instead). `drain_once()`
    must report the truthy `DrainOutcome.FENCED`, never raise and never
    silently report `DONE`."""
    run_id = _seed_run(fake_repo, status=RunStatus.RECEIVED)
    dedup_key = f"run_pipeline:{run_id}:0"
    job_id = fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE, dedup_key=dedup_key, run_id=run_id
    )
    assert job_id is not None

    monkeypatch.setattr(
        dispatch,
        "handle",
        lambda job: PipelineResult(outcome=PipelineOutcome.OK),
    )
    from app.db.repo.job_settlement import SettlementOutcome

    monkeypatch.setattr(
        repo,
        "settle_pipeline_job",
        lambda job, result, *, backoff_seconds, conn=None: SettlementOutcome.FENCED,
    )

    assert drain.drain_once() == DrainOutcome.FENCED


def test_backoff_seconds_exponential_capped_jittered_and_deterministic() -> None:
    assert drain.backoff_seconds(1, rand=lambda lo, hi: 1.0) == pytest.approx(
        drain._BACKOFF_BASE_SECONDS
    )
    assert drain.backoff_seconds(2, rand=lambda lo, hi: 1.0) == pytest.approx(
        drain._BACKOFF_BASE_SECONDS * 2
    )
    assert drain.backoff_seconds(3, rand=lambda lo, hi: 1.0) == pytest.approx(
        drain._BACKOFF_BASE_SECONDS * 4
    )
    # Grows past the cap, but never exceeds it.
    assert drain.backoff_seconds(20, rand=lambda lo, hi: 1.0) == pytest.approx(
        drain._BACKOFF_CAP_SECONDS
    )
    # The injected rand source's bounds are exactly (0.5, 1.5) — the jitter contract.
    seen_bounds: list[tuple[float, float]] = []

    def _recording_rand(lo: float, hi: float) -> float:
        seen_bounds.append((lo, hi))
        return 0.5

    value = drain.backoff_seconds(1, rand=_recording_rand)
    assert seen_bounds == [(0.5, 1.5)]
    assert value == pytest.approx(drain._BACKOFF_BASE_SECONDS * 0.5)


# ── the J-1 CAS-only static guard ────────────────────────────────────────

_REPO_FACADE_MODULE = "app.db.repo"


def _is_repo_reaching(module_dotted: str) -> bool:
    """True for `app`, `app.db`, `app.db.repo`, and any `app.db.repo.*` —
    every module name a dotted attribute chain could use to arrive at the
    repo facade. A plain, un-aliased `import app.db.repo` binds only the
    ROOT name `app` (that is Python's own import semantics, not a scanner
    choice), so `app` itself must be treated as repo-reaching or that whole
    import shape would walk straight through unresolved.
    """
    return module_dotted in ("app", "app.db", _REPO_FACADE_MODULE) or module_dotted.startswith(
        _REPO_FACADE_MODULE + "."
    )


def _is_first_party_module(dotted: str) -> bool:
    """Filesystem truth, not a guess: does `dotted` name a real `.py` file or
    a package (`__init__.py`) under the repository root?"""
    rel = pathlib.Path(*dotted.split("."))
    return (REPO_ROOT / rel).with_suffix(".py").is_file() or (
        REPO_ROOT / rel / "__init__.py"
    ).is_file()


def _module_bindings(tree: ast.AST) -> dict[str, str]:
    """Pass 1: resolve EVERY first-party module binding in a file — local
    name -> dotted module path — for both `ast.Import` and `ast.ImportFrom`,
    including the root-name-only binding a plain dotted `import a.b.c`
    creates."""
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bindings[alias.asname] = alias.name
                else:
                    root = alias.name.split(".")[0]
                    bindings[root] = root
        elif isinstance(node, ast.ImportFrom):
            base = node.module
            if base is None:
                continue
            for alias in node.names:
                dotted = f"{base}.{alias.name}"
                if _is_first_party_module(dotted):
                    bindings[alias.asname or alias.name] = dotted
    return bindings


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _resolve_call_chain(
    chain_attr: ast.Attribute, bindings: dict[str, str]
) -> tuple[str, str] | None:
    """Walk a fully-formed attribute chain rooted at a bound module name and
    resolve it, one hop at a time, against the filesystem. Returns
    (target_module, function_name) on success, or None when the chain
    dead-ends with attributes still left to consume — the caller must treat
    None as a resolution FAILURE, not as "nothing to see here"."""
    parts: list[str] = []
    current: ast.expr = chain_attr
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.reverse()
    current_module = bindings[current.id]
    for i, attr in enumerate(parts):
        candidate = f"{current_module}.{attr}"
        if _is_first_party_module(candidate):
            current_module = candidate
            continue
        if i != len(parts) - 1:
            return None
        return current_module, attr
    return None  # every hop resolved to a module — no terminal function name


def _scan_file(py_file: pathlib.Path) -> tuple[list[str], list[tuple[str, str, int]]]:
    """Scan one file for J-1 CAS-only violations and resolved repo-targeted
    calls. Returns (violations, resolved_calls); each resolved call is
    (target_module, function_name, lineno)."""
    source = py_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(py_file))
    bindings = _module_bindings(tree)
    parents = _parent_map(tree)

    violations: list[str] = []
    resolved: list[tuple[str, str, int]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "importlib":
                    violations.append(f"{py_file}:{node.lineno}: 'importlib' is forbidden")
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] == "importlib":
                violations.append(f"{py_file}:{node.lineno}: 'importlib' is forbidden")
        elif (
            isinstance(node, ast.Name)
            and node.id == "__import__"
            and isinstance(node.ctx, ast.Load)
        ):
            violations.append(f"{py_file}:{node.lineno}: '__import__' is forbidden")

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        base = node.module
        if base is None:
            continue
        if base != _REPO_FACADE_MODULE and not base.startswith(_REPO_FACADE_MODULE + "."):
            continue
        for alias in node.names:
            dotted = f"{base}.{alias.name}"
            if not _is_first_party_module(dotted):
                violations.append(
                    f"{py_file}:{node.lineno}: imports {alias.name!r} directly out of "
                    f"repo-reaching module {base!r} — import the module object instead"
                )

    resolved_chain_ids: set[int] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
            continue
        target = bindings.get(node.id)
        if target is None or not _is_repo_reaching(target):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Attribute) and parent.value is node:
            chain_node: ast.expr = parent
            while True:
                grandparent = parents.get(chain_node)
                if isinstance(grandparent, ast.Attribute) and grandparent.value is chain_node:
                    chain_node = grandparent
                else:
                    break
            call_parent = parents.get(chain_node)
            if isinstance(call_parent, ast.Call) and call_parent.func is chain_node:
                if id(chain_node) in resolved_chain_ids:
                    continue
                resolved_chain_ids.add(id(chain_node))
                assert isinstance(chain_node, ast.Attribute)
                result = _resolve_call_chain(chain_node, bindings)
                if result is None:
                    violations.append(
                        f"{py_file}:{call_parent.lineno}: restricted name {node.id!r} "
                        f"(bound to {target!r}) is called through an attribute chain "
                        f"that cannot be fully resolved against the filesystem"
                    )
                else:
                    target_module, func_name = result
                    resolved.append((target_module, func_name, call_parent.lineno))
                continue
            violations.append(
                f"{py_file}:{node.lineno}: restricted name {node.id!r} (bound to "
                f"{target!r}) escapes into a value outside a resolved, called "
                f"attribute chain — the chain is never invoked"
            )
            continue
        violations.append(
            f"{py_file}:{node.lineno}: restricted name {node.id!r} (bound to "
            f"{target!r}) appears outside an attribute-chain root — as an "
            f"assignment target/value, a call argument (including getattr), "
            f"a container element, or a return value"
        )

    return violations, resolved


def _scan_queue_tier() -> tuple[list[str], list[tuple[str, str, pathlib.Path, int]]]:
    violations: list[str] = []
    resolved: list[tuple[str, str, pathlib.Path, int]] = []
    for py_file in sorted(QUEUE_ROOT.rglob("*.py")):
        file_violations, file_resolved = _scan_file(py_file)
        violations.extend(file_violations)
        resolved.extend((mod, fn, py_file, line) for (mod, fn, line) in file_resolved)
    return violations, resolved


def test_queue_tier_status_writers_are_cas_only() -> None:
    """The J-1 CAS-only guard. This must run GREEN against the real,
    unmutated `app/queue/` — see this module's docstring for why `pipeline`
    living inside `dispatch.HANDLERS` and `getattr(module, name)(job)` are
    both deliberately unrestricted rather than a false positive.

    LIMITATION, stated so nobody trusts this guard further than it goes: it
    covers ONLY direct repo access from `app/queue/`. It does not, and
    cannot, see a status write performed by code the queue calls INTO —
    `pipeline_glue.run_pipeline_now` -> `orchestrator.run_pipeline`, whose own
    unconditional status write at the start of a run is explicitly permitted
    and untouched by this phase. This tier's invariant constrains the
    transport layer, not the pipeline it invokes; this guard is not, and
    must never be read as, a whole-application status-write inventory.
    """
    violations, resolved = _scan_queue_tier()
    assert not violations, "J-1 CAS-only guard violation(s):\n" + "\n".join(violations)

    func_names = {fn for (_module, fn, _file, _line) in resolved}
    status_writer_candidates = {
        "set_status",
        "claim_status",
        "record_run_error",
        "rewind_for_reclaim",
        "settle_pipeline_job",
        "settle_infrastructure_failure",
        "reap_expired_final_attempt",
    }
    observed_status_writers = func_names & status_writer_candidates
    permitted = {
        "claim_status",
        "rewind_for_reclaim",
        "settle_pipeline_job",
        "settle_infrastructure_failure",
        "reap_expired_final_attempt",
    }
    assert observed_status_writers <= permitted, (
        "payroll_runs.status may be written from app/queue/ only through the "
        f"sanctioned CAS/coordinator seams; found: {sorted(observed_status_writers)}"
    )


def test_the_guard_actually_resolves_the_queue_tiers_real_calls() -> None:
    """Anti-vacuity proof: a resolver that silently matched nothing would
    satisfy every assertion in `test_queue_tier_status_writers_are_cas_only`
    (both are negative/subset checks, true on an empty set) while inspecting
    zero calls. This is the SEPARATE, positive proof that the resolver
    actually sees the real code it is supposed to be guarding.
    """
    _violations, resolved = _scan_queue_tier()
    func_names = {fn for (_module, fn, _file, _line) in resolved}
    assert func_names, (
        "the resolver found zero repo-targeted calls under app/queue/ — it has "
        "stopped seeing the code it is supposed to guard"
    )
    assert "claim_status" in func_names
    assert "rewind_for_reclaim" in func_names
    assert "settle_pipeline_job" in func_names
    assert "settle_infrastructure_failure" in func_names
    assert "reap_expired_final_attempt" in func_names


# ── PipelineResult-only call graph guard ──────────────────────────────────


_RESULT_PRODUCER_FUNCTIONS: dict[pathlib.Path, set[str]] = {
    REPO_ROOT / "app/pipeline/orchestrator.py": {"run_pipeline", "resume_pipeline"},
    REPO_ROOT / "app/routes/pipeline_glue.py": {
        "run_pipeline_now",
        "resume_pipeline_now",
    },
    REPO_ROOT / "app/queue/handlers/pipeline.py": {"handle_run_pipeline"},
    REPO_ROOT / "app/queue/handlers/resume_reply.py": {"handle_resume_reply"},
    REPO_ROOT / "app/queue/handlers/operator_resume.py": {"handle_operator_resume"},
    REPO_ROOT / "app/queue/dispatch.py": {"handle"},
}
_RESULT_CONSUMER_FUNCTIONS: dict[pathlib.Path, set[str]] = {
    REPO_ROOT / "app/queue/drain.py": {"drain_once"},
}
_RESULT_CALL_NAMES = {
    "_run",
    "run_pipeline",
    "resume_pipeline",
    "run_pipeline_now",
    "resume_pipeline_now",
    "handler",
    "handle",
}


def _final_call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _result_contract_violations(
    source: str,
    *,
    function_names: set[str],
    strict_return_names: set[str],
) -> tuple[list[str], set[str], set[str]]:
    """Return violations, discovered functions, and result-bearing call targets."""
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in function_names
    }
    violations: list[str] = []
    observed_calls: set[str] = set()

    for name, function in functions.items():
        if name in strict_return_names:
            annotation = ast.unparse(function.returns) if function.returns else ""
            if annotation != "PipelineResult":
                violations.append(
                    f"{name}: return annotation must be PipelineResult, got {annotation!r}"
                )
            for node in ast.walk(function):
                if isinstance(node, ast.Return) and (
                    node.value is None
                    or isinstance(node.value, ast.Constant)
                    and node.value.value is None
                ):
                    violations.append(f"{name}:{node.lineno}: returns None")

        parents = _parent_map(function)
        result_assignments: set[str] = set()
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            call_name = _final_call_name(node)
            if call_name not in _RESULT_CALL_NAMES:
                continue
            observed_calls.add(call_name)

            current: ast.AST = node
            parent = parents.get(current)
            while isinstance(parent, (ast.Call, ast.Attribute, ast.keyword)):
                current = parent
                parent = parents.get(current)
            if not isinstance(parent, (ast.Return, ast.Assign, ast.AnnAssign)):
                violations.append(
                    f"{name}:{node.lineno}: result call {call_name} is discarded "
                    "or consumed without assignment/return"
                )
            if isinstance(parent, (ast.Assign, ast.AnnAssign)):
                targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
                result_assignments.update(
                    target.id for target in targets if isinstance(target, ast.Name)
                )

        for node in ast.walk(function):
            if not isinstance(node, (ast.If, ast.While)):
                continue
            test = node.test
            shortcut = (
                test.id
                if isinstance(test, ast.Name)
                else test.operand.id
                if isinstance(test, ast.UnaryOp)
                and isinstance(test.op, ast.Not)
                and isinstance(test.operand, ast.Name)
                else None
            )
            if shortcut in result_assignments:
                violations.append(
                    f"{name}:{node.lineno}: PipelineResult {shortcut} used as truthy/falsy"
                )

    return violations, set(functions), observed_calls


def test_pipeline_result_call_graph_is_exact_non_vacuous_and_has_no_sinks() -> None:
    """Every active result seam is exact, present, and mechanically consumed."""
    all_specs: dict[pathlib.Path, set[str]] = {}
    for path, names in (*_RESULT_PRODUCER_FUNCTIONS.items(), *_RESULT_CONSUMER_FUNCTIONS.items()):
        all_specs.setdefault(path, set()).update(names)

    violations: list[str] = []
    discovered: set[tuple[pathlib.Path, str]] = set()
    observed_calls: set[str] = set()
    for path, names in all_specs.items():
        file_violations, file_functions, file_calls = _result_contract_violations(
            path.read_text(encoding="utf-8"),
            function_names=names,
            strict_return_names=_RESULT_PRODUCER_FUNCTIONS.get(path, set()),
        )
        violations.extend(f"{path.relative_to(REPO_ROOT)}: {item}" for item in file_violations)
        discovered.update((path, name) for name in file_functions)
        observed_calls.update(file_calls)

    expected = {
        (path, name)
        for path, names in all_specs.items()
        for name in names
    }
    assert discovered == expected, (
        "result inventory drifted; missing="
        f"{sorted((str(p), n) for p, n in expected - discovered)}, extra="
        f"{sorted((str(p), n) for p, n in discovered - expected)}"
    )
    assert observed_calls >= {
        "_run",
        "run_pipeline",
        "resume_pipeline",
        "run_pipeline_now",
        "handler",
        "handle",
    }, f"result call inventory was vacuous or incomplete: {sorted(observed_calls)}"
    assert not violations, "PipelineResult call-graph violation(s):\n" + "\n".join(violations)

    result_source = (REPO_ROOT / "app/pipeline/result.py").read_text(encoding="utf-8")
    result_tree = ast.parse(result_source)
    normalizer = next(
        node
        for node in result_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "normalize_pipeline_result"
    )
    assert normalizer.args.args[0].annotation is not None
    assert normalizer.returns is not None
    assert ast.unparse(normalizer.args.args[0].annotation) == "PipelineResult"
    assert ast.unparse(normalizer.returns) == "PipelineResult"


def test_pipeline_result_call_graph_guard_rejects_optional_discarded_and_truthy_results() -> None:
    """Positive anti-vacuity proof: representative compatibility mutations fail closed."""
    hostile = """
def producer() -> PipelineResult | None:
    return None

def consumer() -> None:
    run_pipeline()
    result = resume_pipeline()
    if result:
        pass
"""
    violations, discovered, observed = _result_contract_violations(
        hostile,
        function_names={"producer", "consumer"},
        strict_return_names={"producer"},
    )

    assert discovered == {"producer", "consumer"}
    assert observed == {"run_pipeline", "resume_pipeline"}
    assert any("return annotation" in violation for violation in violations)
    assert any("returns None" in violation for violation in violations)
    assert any("result call run_pipeline is discarded" in violation for violation in violations)
    assert any("used as truthy/falsy" in violation for violation in violations)


def test_held_tokens_never_snapshots_a_claim_into_oblivion(monkeypatch):
    """A shutdown must not be able to look at a worker the DATABASE has already handed a
    lease to and conclude that it holds nothing.

    The window: `repo.claim_job()` RETURNS — Postgres now considers the lease held by this
    process — and the worker is descheduled before the next line records the token.
    `stop()` snapshots `held_tokens()` right there, sees an empty set, `release_leases()`
    never hands the lease back, and the app exits with a live lease outstanding. That job
    is then unclaimable for the full `lease_seconds` (900s) — on a platform that redeploys
    routinely. ROADMAP criterion 4 forbids exactly this.

    TWO THINGS THIS DELIBERATELY DOES NOT DO, both of which would make it a false proof:

    It does NOT pass `settle_timeout`. An explicit generous value would exercise an
    argument no production caller passes — `worker.stop()` calls `held_tokens()` bare — so
    shrinking the real default to something uselessly small (0.1s) would leave the test
    green while production resumed missing any claim slower than 100ms. The default is the
    thing under test, so the default is what gets used.

    It does NOT sleep-and-hope. The claim is held open for a fixed window and the drain
    signals when it is genuinely INSIDE the claim, so the snapshot provably lands in the
    window rather than probably landing there.
    """
    # Long enough that a shrunken default would time out and miss the lease; far shorter
    # than the real 2.0s default, so the honest path never comes close to its ceiling.
    claim_held_s = 0.5

    token = uuid.uuid4()
    base = _job(run_id=uuid.uuid4(), attempts=1)
    claimed_job = Job(
        id=base.id,
        kind=base.kind,
        run_id=base.run_id,
        attempts=1,
        max_attempts=5,
        lease_token=token,
    )

    claim_entered = threading.Event()
    snapshot_taken = threading.Event()

    def _slow_claim():
        # The DB is handing over the lease; the worker is descheduled right here.
        claim_entered.set()
        time.sleep(claim_held_s)
        return claimed_job

    def _blocking_handle(job) -> PipelineResult:
        # Hold the job in flight until the snapshot lands, so the drain's own
        # finally-discard cannot race the assertion.
        assert snapshot_taken.wait(timeout=5.0)
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(repo, "claim_job", _slow_claim)
    monkeypatch.setattr(dispatch, "handle", _blocking_handle)
    from app.db.repo.job_settlement import SettlementOutcome

    monkeypatch.setattr(
        repo,
        "settle_pipeline_job",
        lambda job, result, *, backoff_seconds: SettlementOutcome.DONE,
    )

    snapshot: list[list[uuid.UUID]] = []
    drainer = threading.Thread(target=drain.drain_once, name="f6-drainer")
    # NOTE: held_tokens() called BARE — exactly as worker.stop() calls it.
    snapshotter = threading.Thread(
        target=lambda: snapshot.append(drain.held_tokens()), name="f6-snapshotter"
    )

    drainer.start()
    assert claim_entered.wait(timeout=5.0), "the drain never reached the claim"

    # The worker is provably inside the claim right now. Shutdown snapshots.
    snapshotter.start()
    snapshotter.join(timeout=5.0)
    snapshot_taken.set()
    drainer.join(timeout=5.0)

    assert not snapshotter.is_alive() and not drainer.is_alive()
    assert snapshot == [[token]], (
        "held_tokens() snapshotted a lease into oblivion: the database had already "
        f"granted lease {token} to this process, but the snapshot came back {snapshot} "
        "— release_leases() would never have handed it back, and the job would sit "
        "unclaimable for the full 900s lease after the app exits"
    )


def test_run_pipeline_now_actually_runs_the_orchestrator_and_propagates(monkeypatch):
    """The retry proofs above stub `run_pipeline_now` wholesale, so NOTHING in them would
    notice if its body were replaced with a bare `return`. That mutation is catastrophic in
    production — every queued payroll would be marked `done` without the pipeline ever
    running — and it would leave the whole suite green. This is the test that dies on it.

    Two properties, both load-bearing:
      1. `run_pipeline_now` genuinely invokes `orchestrator.run_pipeline`.
      2. It does NOT swallow — the exception reaches the caller, which is the entire
         reason the queue can route infrastructure failure through fenced settlement.
    """
    import app.pipeline.orchestrator as orchestrator_mod

    calls: list[uuid.UUID] = []

    def _spy_run_pipeline(rid: uuid.UUID) -> None:
        calls.append(rid)
        raise RuntimeError("simulated catastrophic failure")

    monkeypatch.setattr(orchestrator_mod, "run_pipeline", _spy_run_pipeline)

    run_id = uuid.uuid4()
    with pytest.raises(RuntimeError, match="simulated catastrophic failure"):
        pipeline_glue.run_pipeline_now(run_id)
    assert calls == [run_id], (
        "run_pipeline_now must actually invoke the orchestrator — a body that just "
        "returns would mark every queued payroll done without running it"
    )

def test_a_failed_infrastructure_settlement_keeps_the_lease_recorded(monkeypatch):
    """When infrastructure settlement itself raises, the token stays recorded.

    The realistic failure that reaches the handler is a DATABASE OUTAGE — and settlement
    is another database write, so it fails for the same reason. The row is left `leased`
    in Postgres. An unconditional `finally: _held_tokens.discard(...)` then forgets the
    token, so a graceful shutdown can no longer discover the lease to release it, and the
    job sits unclaimable for the FULL 900s lease even though the process shut down
    cleanly. That silently undermines both the retry guarantee and ROADMAP criterion 4.

    Keeping the token is safe even if the lease is later reclaimed by another worker:
    `release_leases` is fenced on the token itself (`WHERE lease_token = ANY(...) AND
    state = 'leased'`), so handing back a token that is no longer the row's current lease
    is a no-op, not a theft.
    """
    token = uuid.uuid4()
    base = _job(run_id=uuid.uuid4(), attempts=1)
    leased_job = Job(
        id=base.id,
        kind=base.kind,
        run_id=base.run_id,
        attempts=1,
        max_attempts=5,
        lease_token=token,
    )

    def _outage(*args, **kwargs):
        raise RuntimeError("simulated database outage")

    monkeypatch.setattr(repo, "claim_job", lambda: leased_job)
    monkeypatch.setattr(dispatch, "handle", _outage)   # the handler fails: DB is down
    monkeypatch.setattr(repo, "settle_infrastructure_failure", _outage)

    try:
        # drain_once lets the outage ESCAPE by design: the double-failure is a
        # genuine infra failure, not a settled fence, so it RE-RAISES rather than
        # returning a truthy DrainOutcome.FENCED. The worker loop (worker.py:203)
        # is what catches it and survives — proved separately by the worker-loop
        # survival test in tests/test_queue_worker.py.
        with pytest.raises(RuntimeError, match="simulated database outage"):
            drain.drain_once()

        assert drain.held_tokens() == [token], (
            "settlement raised, so the row is still `leased` in the database — but the "
            "lease token was discarded anyway. A graceful shutdown can no longer hand "
            "it back, and the job is stranded for the full 900s lease."
        )
    finally:
        drain._held_tokens.clear()  # module state: never leak into the next test
