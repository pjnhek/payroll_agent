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
from datetime import UTC, datetime
from typing import Any

import pytest

from app.db import repo
from app.models.job import Job, JobKind
from app.models.contracts import InboundEmail
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


# ── Phase 18 classified settlement coordinator ───────────────────────────────


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


def _reply_inbound() -> InboundEmail:
    return InboundEmail(
        id=uuid.uuid4(),
        message_id=f"<{uuid.uuid4()}@test.example>",
        in_reply_to="<asked@test.example>",
        references_header="<asked@test.example>",
        subject="Re: payroll question",
        from_addr="payroll@coastalcleaning.example",
        to_addr="agent@payroll-agent.local",
        body_text="The exact persisted reply body.",
        created_at=datetime.now(UTC),
    )


def test_initial_background_retry_enqueues_once_and_wakes_after_commit(
    fake_repo, monkeypatch
):
    from app.queue import wake

    run_id = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    retryable = PipelineResult(
        outcome=PipelineOutcome.RETRYABLE,
        stage=PipelineStage.EXTRACT,
        reason=PipelineReason.PROVIDER_TIMEOUT,
    )
    monkeypatch.setattr(pipeline_glue, "run_pipeline_now", lambda rid: retryable)
    observed: list[tuple[str, int]] = []

    def _wake_after_commit() -> None:
        observed.append((fake_repo.runs[str(run_id)]["status"], len(fake_repo.jobs)))

    monkeypatch.setattr(wake, "wake", _wake_after_commit)
    pipeline_glue.run_pipeline_bg(run_id)

    assert observed == [(RunStatus.RECEIVED.value, 1)]
    job = next(iter(fake_repo.jobs.values()))
    assert job["kind"] == JobKind.RUN_PIPELINE.value
    assert job["email_id"] is None
    assert job["last_error"] == retryable.diagnostic_code


def test_background_ok_and_terminal_create_no_retry_job(fake_repo, monkeypatch):
    ok_run = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    monkeypatch.setattr(pipeline_glue, "run_pipeline_now", lambda rid: None)
    pipeline_glue.run_pipeline_bg(ok_run)
    assert fake_repo.jobs == {}
    assert fake_repo.runs[str(ok_run)]["status"] == RunStatus.EXTRACTING.value

    terminal_run = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    terminal = PipelineResult(
        outcome=PipelineOutcome.TERMINAL,
        stage=PipelineStage.COMPUTE,
        reason=PipelineReason.UNCLASSIFIED,
    )
    monkeypatch.setattr(pipeline_glue, "run_pipeline_now", lambda rid: terminal)
    pipeline_glue.run_pipeline_bg(terminal_run)
    assert fake_repo.jobs == {}
    assert fake_repo.runs[str(terminal_run)]["status"] == RunStatus.ERROR.value
    assert fake_repo.runs[str(terminal_run)]["error_reason"] == terminal.reason.value


def test_reply_background_retry_preserves_exact_email_and_body(fake_repo, monkeypatch):
    from app.queue import wake

    run_id = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    inbound = _reply_inbound()
    seen: list[tuple[uuid.UUID, InboundEmail]] = []
    retryable = PipelineResult(
        outcome=PipelineOutcome.RETRYABLE,
        stage=PipelineStage.EXTRACT,
        reason=PipelineReason.PROVIDER_RATE_LIMIT,
    )

    def _resume_now(rid: uuid.UUID, reply: InboundEmail):
        seen.append((rid, reply))
        return retryable

    monkeypatch.setattr(pipeline_glue, "resume_pipeline_now", _resume_now, raising=False)
    wake_calls: list[bool] = []
    monkeypatch.setattr(wake, "wake", lambda: wake_calls.append(True))
    pipeline_glue.resume_pipeline_bg(run_id, inbound)

    assert seen == [(run_id, inbound)]
    assert seen[0][1].body_text == "The exact persisted reply body."
    job = next(iter(fake_repo.jobs.values()))
    assert job["kind"] == JobKind.RESUME_REPLY.value
    assert job["email_id"] == inbound.id
    assert job["operator_resolution_id"] is None
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.RECEIVED.value
    assert wake_calls == [True]


# ── handle_run_pipeline: the five behaviors ─────────────────────────────


def test_handler_attempts_1_received_cas_wins_and_pipeline_runs(fake_repo, monkeypatch):
    run_id = _seed_run(fake_repo, status=RunStatus.RECEIVED)
    calls: list[uuid.UUID] = []
    monkeypatch.setattr(pipeline_glue, "run_pipeline_now", lambda rid: calls.append(rid))

    pipeline.handle_run_pipeline(_job(run_id=run_id, attempts=1))

    assert calls == [run_id]
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.EXTRACTING.value


def test_handler_attempts_1_computed_cas_loses_no_run(fake_repo, monkeypatch):
    run_id = _seed_run(fake_repo, status=RunStatus.COMPUTED)
    calls: list[uuid.UUID] = []
    monkeypatch.setattr(pipeline_glue, "run_pipeline_now", lambda rid: calls.append(rid))

    pipeline.handle_run_pipeline(_job(run_id=run_id, attempts=1))

    assert calls == []
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.COMPUTED.value


def test_handler_attempts_2_extracting_rewinds_then_cas_wins(fake_repo, monkeypatch):
    run_id = _seed_run(fake_repo, status=RunStatus.EXTRACTING)
    calls: list[uuid.UUID] = []
    monkeypatch.setattr(pipeline_glue, "run_pipeline_now", lambda rid: calls.append(rid))

    pipeline.handle_run_pipeline(_job(run_id=run_id, attempts=2))

    assert calls == [run_id]
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.EXTRACTING.value


def test_handler_attempts_2_reconciled_rewind_is_a_noop_cas_loses(fake_repo, monkeypatch):
    run_id = _seed_run(fake_repo, status=RunStatus.RECONCILED)
    calls: list[uuid.UUID] = []
    monkeypatch.setattr(pipeline_glue, "run_pipeline_now", lambda rid: calls.append(rid))

    pipeline.handle_run_pipeline(_job(run_id=run_id, attempts=2))

    assert calls == []
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.RECONCILED.value


def test_reply_epoch_unchanged_across_every_handler_path(fake_repo, monkeypatch):
    """Neither the forward CAS nor the reclaim rewind ever bumps reply_epoch
    — only a human retrigger, through clear_reply_context, may grant the
    licence to email the client a second time."""
    monkeypatch.setattr(pipeline_glue, "run_pipeline_now", lambda rid: None)

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
    monkeypatch.setattr(pipeline_glue, "run_pipeline_now", lambda rid: None)

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
    to be retried — dead-lettering only after `max_attempts`. The one-word
    difference at the call site (`run_pipeline_now` vs `run_pipeline_bg`) is the
    whole of it: `_bg`'s swallow is right for a fire-and-forget BackgroundTask
    on a webhook that already returned 200, and fatal for a queued job.

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
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.EXTRACTING.value


def test_a_stage_failure_still_completes_the_job(fake_repo, monkeypatch):
    """The other half of the contract, and the reason the fix above is not simply
    "make every failure retry".

    A STAGE failure (the LLM refuses, the calc raises) is caught by the pipeline's
    OWN catch-all, which persists ERROR on the run and returns normally. The run is
    already visible to a human in that state, so the job has genuinely finished its
    work and must complete — retrying it would re-run a pipeline that already
    recorded its error, and would keep re-running it until it dead-lettered.

    Only the catastrophic-START case (the pipeline never began at all) is a retry.
    This test is what stops a future "just retry everything" edit from turning every
    errored run into `max_attempts` duplicate executions.
    """
    run_id = _seed_run(fake_repo, status=RunStatus.RECEIVED)

    invocations: list[uuid.UUID] = []

    def _stage_failure_handled_internally(rid: uuid.UUID) -> None:
        # Mirrors the orchestrator's own error-wrap: it persists ERROR and RETURNS.
        invocations.append(rid)
        fake_repo.set_status(rid, RunStatus.ERROR)

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
        "a stage failure is handled and persisted by the pipeline itself — the job "
        "did its work and must complete, not retry a run that already recorded ERROR"
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


def test_drain_once_claims_dispatches_and_completes_with_the_same_token(fake_repo, monkeypatch):
    run_id = _seed_run(fake_repo, status=RunStatus.RECEIVED)
    dedup_key = f"run_pipeline:{run_id}:0"
    job_id = fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE, dedup_key=dedup_key, run_id=run_id
    )
    assert job_id is not None

    handled: list[Job] = []
    monkeypatch.setattr(dispatch, "handle", handled.append)

    seen_complete_tokens: list[uuid.UUID] = []
    orig_complete = repo.complete_job

    def _spy_complete(job_id_arg: uuid.UUID, lease_token: uuid.UUID, conn: Any = None) -> bool:
        seen_complete_tokens.append(lease_token)
        result: bool = orig_complete(job_id_arg, lease_token, conn=conn)
        return result

    monkeypatch.setattr(repo, "complete_job", _spy_complete)

    assert drain.drain_once() == DrainOutcome.DONE

    assert len(handled) == 1
    claimed_job = handled[0]
    assert claimed_job.id == job_id
    # The exact lease_token object the claim returned — not merely "was called".
    assert seen_complete_tokens == [claimed_job.lease_token]
    assert fake_repo.jobs[str(job_id)]["state"] == "done"


def test_held_tokens_populated_during_handler_and_cleared_after(fake_repo, monkeypatch):
    run_id = _seed_run(fake_repo, status=RunStatus.RECEIVED)
    dedup_key = f"run_pipeline:{run_id}:0"
    fake_repo.enqueue_job(kind=JobKind.RUN_PIPELINE, dedup_key=dedup_key, run_id=run_id)

    captured: dict[str, Any] = {}

    def _stub_handle(job: Job) -> None:
        # Asserted FROM INSIDE the handler, not by inspection after the fact —
        # held_tokens() must be non-empty WHILE the handler is running.
        captured["token"] = job.lease_token
        captured["held_during"] = list(drain.held_tokens())

    monkeypatch.setattr(dispatch, "handle", _stub_handle)

    assert drain.held_tokens() == []
    assert drain.drain_once() == DrainOutcome.DONE
    assert captured["held_during"] == [captured["token"]]
    assert drain.held_tokens() == []


def test_drain_once_handler_raises_calls_fail_job_not_complete_job(fake_repo, monkeypatch):
    run_id = _seed_run(fake_repo, status=RunStatus.RECEIVED)
    dedup_key = f"run_pipeline:{run_id}:0"
    job_id = fake_repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE, dedup_key=dedup_key, run_id=run_id
    )
    assert job_id is not None

    def _raising_handle(job: Job) -> None:
        raise RuntimeError("simulated dispatch failure")

    monkeypatch.setattr(dispatch, "handle", _raising_handle)

    fail_calls: list[dict[str, Any]] = []
    complete_calls: list[Any] = []
    orig_fail = repo.fail_job
    orig_complete = repo.complete_job

    def _spy_fail(
        job_id_arg: uuid.UUID,
        lease_token: uuid.UUID,
        *,
        error: BaseException | str,
        backoff_seconds: float,
        conn: Any = None,
    ) -> Any:
        fail_calls.append(
            {"job_id": job_id_arg, "lease_token": lease_token, "backoff_seconds": backoff_seconds}
        )
        return orig_fail(
            job_id_arg, lease_token, error=error, backoff_seconds=backoff_seconds, conn=conn
        )

    def _spy_complete(*args: Any, **kwargs: Any) -> Any:
        complete_calls.append(args)
        return orig_complete(*args, **kwargs)

    monkeypatch.setattr(repo, "fail_job", _spy_fail)
    monkeypatch.setattr(repo, "complete_job", _spy_complete)

    assert drain.drain_once() == DrainOutcome.RETRIED

    assert complete_calls == []
    assert len(fail_calls) == 1
    assert fail_calls[0]["backoff_seconds"] > 0
    assert fake_repo.jobs[str(job_id)]["state"] == "pending"  # attempts=1 < max_attempts=5


def test_drain_once_dispatch_raises_at_max_attempts_returns_dead(fake_repo, monkeypatch):
    """`fail_job`'s own MAX_ATTEMPTS CASE moves the row to `dead`, not
    `pending` — `drain_once()` must capture that specific `JobState.DEAD`
    return as `DrainOutcome.DEAD`, distinct from the backoff `RETRIED` case
    above."""
    run_id = _seed_run(fake_repo, status=RunStatus.RECEIVED)
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

    monkeypatch.setattr(dispatch, "handle", lambda job: None)
    monkeypatch.setattr(
        repo, "complete_job", lambda job_id, lease_token, conn=None: False
    )

    assert drain.drain_once() == DrainOutcome.FENCED


def test_backoff_seconds_exponential_capped_jittered_and_deterministic() -> None:
    assert drain._backoff_seconds(1, rand=lambda lo, hi: 1.0) == pytest.approx(
        drain._BACKOFF_BASE_SECONDS
    )
    assert drain._backoff_seconds(2, rand=lambda lo, hi: 1.0) == pytest.approx(
        drain._BACKOFF_BASE_SECONDS * 2
    )
    assert drain._backoff_seconds(3, rand=lambda lo, hi: 1.0) == pytest.approx(
        drain._BACKOFF_BASE_SECONDS * 4
    )
    # Grows past the cap, but never exceeds it.
    assert drain._backoff_seconds(20, rand=lambda lo, hi: 1.0) == pytest.approx(
        drain._BACKOFF_CAP_SECONDS
    )
    # The injected rand source's bounds are exactly (0.5, 1.5) — the jitter contract.
    seen_bounds: list[tuple[float, float]] = []

    def _recording_rand(lo: float, hi: float) -> float:
        seen_bounds.append((lo, hi))
        return 0.5

    value = drain._backoff_seconds(1, rand=_recording_rand)
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
    `pipeline_glue.run_pipeline_bg` -> `orchestrator.run_pipeline`, whose own
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
    }
    observed_status_writers = func_names & status_writer_candidates
    permitted = {"claim_status", "rewind_for_reclaim"}
    assert observed_status_writers <= permitted, (
        "payroll_runs.status may be written from app/queue/ ONLY via "
        f"claim_status/rewind_for_reclaim; found: {sorted(observed_status_writers)}"
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

    def _blocking_handle(job):
        # Hold the job in flight until the snapshot lands, so the drain's own
        # finally-discard cannot race the assertion.
        assert snapshot_taken.wait(timeout=5.0)

    monkeypatch.setattr(repo, "claim_job", _slow_claim)
    monkeypatch.setattr(dispatch, "handle", _blocking_handle)
    monkeypatch.setattr(repo, "complete_job", lambda job_id, tok: True)

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
         reason the queue calls this instead of `run_pipeline_bg`.

    The companion assertion on `run_pipeline_bg` pins the other half of the contract: it
    MUST still swallow, because the inbound webhook schedules it as a fire-and-forget
    BackgroundTask after already returning 200 and has no caller left to raise to.
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

    # The other half: _bg still swallows, so the webhook's BackgroundTask cannot crash.
    calls.clear()
    pipeline_glue.run_pipeline_bg(run_id)  # must NOT raise
    assert calls == [run_id], "run_pipeline_bg must still invoke the orchestrator too"


def test_a_failed_fail_job_keeps_the_lease_recorded(monkeypatch):
    """When `fail_job` ITSELF raises, the lease token must stay recorded.

    The realistic failure that reaches the handler is a DATABASE OUTAGE — and `fail_job`
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
    monkeypatch.setattr(repo, "fail_job", _outage)     # ...and so does the failure write

    try:
        # drain_once lets the outage ESCAPE by design: the double-failure is a
        # genuine infra failure, not a settled fence, so it RE-RAISES rather than
        # returning a truthy DrainOutcome.FENCED. The worker loop (worker.py:203)
        # is what catches it and survives — proved separately by the worker-loop
        # survival test in tests/test_queue_worker.py.
        with pytest.raises(RuntimeError, match="simulated database outage"):
            drain.drain_once()

        assert drain.held_tokens() == [token], (
            "fail_job raised, so the row is still `leased` in the database — but the "
            "lease token was discarded anyway. A graceful shutdown can no longer hand "
            "it back, and the job is stranded for the full 900s lease."
        )
    finally:
        drain._held_tokens.clear()  # module state: never leak into the next test
