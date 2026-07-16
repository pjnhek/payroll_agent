"""Atomic failure-policy coordination across queue and payroll-run state.

Transport rows and business status remain separate authorities, but retry/final
settlement must commit together.  This module is the only repository seam allowed
to update both aggregates in one transaction.
"""
from __future__ import annotations

import enum
import uuid

import psycopg

from app.db.repo._shared import _conn_ctx, _nulltx
from app.db.repo.jobs import enqueue_job
from app.db.repo.operator_resume_resolutions import load_operator_resume_resolution
from app.models.job import Job, JobKind
from app.models.status import RunStatus
from app.pipeline.result import (
    PipelineOutcome,
    PipelineReason,
    PipelineResult,
    PipelineStage,
)


class SettlementOutcome(enum.StrEnum):
    """Bounded result of one cross-aggregate settlement operation."""

    DONE = "done"
    RETRIED = "retried"
    DEAD = "dead"
    FENCED = "fenced"
    REAPED_FINAL_LEASE = "reaped_final_lease"


def _bounded_detail(
    result: PipelineResult,
    *,
    attempts: int | None = None,
    max_attempts: int | None = None,
) -> str:
    detail = result.diagnostic_code
    if attempts is not None and max_attempts is not None:
        detail = f"{detail};attempts={attempts}/{max_attempts}"
    return detail[:200]


def _locked_job(
    conn: psycopg.Connection,
    job: Job,
) -> tuple[int, int, uuid.UUID | None] | None:
    row = conn.execute(
        "SELECT attempts, max_attempts, run_id FROM jobs"
        " WHERE id = %s AND state = 'leased' AND lease_token = %s"
        " FOR UPDATE",
        (str(job.id), str(job.lease_token)),
    ).fetchone()
    if row is None:
        return None
    run_id = uuid.UUID(str(row[2])) if row[2] is not None else None
    return int(row[0]), int(row[1]), run_id


def _set_run_error(
    conn: psycopg.Connection,
    run_id: uuid.UUID,
    *,
    reason: str,
    detail: str,
) -> bool:
    row = conn.execute(
        "UPDATE payroll_runs SET status = %s, error_reason = %s,"
        " error_detail = %s, updated_at = now()"
        " WHERE id = %s AND status = %s RETURNING id",
        (
            RunStatus.ERROR.value,
            reason,
            detail,
            str(run_id),
            RunStatus.EXTRACTING.value,
        ),
    ).fetchone()
    return row is not None


def _rewind_run(conn: psycopg.Connection, run_id: uuid.UUID) -> bool:
    row = conn.execute(
        "UPDATE payroll_runs SET status = %s, updated_at = now()"
        " WHERE id = %s AND status = %s RETURNING id",
        (RunStatus.RECEIVED.value, str(run_id), RunStatus.EXTRACTING.value),
    ).fetchone()
    return row is not None


def _existing_job_matches(
    conn: psycopg.Connection,
    *,
    dedup_key: str,
    kind: JobKind,
    run_id: uuid.UUID,
    email_id: uuid.UUID | None,
    operator_resolution_id: uuid.UUID | None,
) -> bool:
    row = conn.execute(
        "SELECT kind, run_id, email_id, operator_resolution_id FROM jobs"
        " WHERE dedup_key = %s",
        (dedup_key,),
    ).fetchone()
    if row is None:
        return False
    return (
        row[0] == kind.value
        and str(row[1]) == str(run_id)
        and (str(row[2]) if row[2] is not None else None)
        == (str(email_id) if email_id is not None else None)
        and (str(row[3]) if row[3] is not None else None)
        == (
            str(operator_resolution_id)
            if operator_resolution_id is not None
            else None
        )
    )


def _run_generation(
    conn: psycopg.Connection, run_id: uuid.UUID
) -> tuple[str, int] | None:
    row = conn.execute(
        "SELECT status, reply_epoch FROM payroll_runs WHERE id = %s FOR UPDATE",
        (str(run_id),),
    ).fetchone()
    if row is None:
        return None
    return str(row[0]), int(row[1])


def enqueue_classified_retry(
    run_id: uuid.UUID,
    result: PipelineResult,
    *,
    kind: JobKind,
    email_id: uuid.UUID | None = None,
    available_in_seconds: float,
    conn: psycopg.Connection | None = None,
) -> SettlementOutcome:
    """Atomically rewind a first attempt and enqueue one durable retry."""
    if result.outcome is not PipelineOutcome.RETRYABLE:
        raise ValueError("enqueue_classified_retry requires a retryable result")
    if kind not in (JobKind.RUN_PIPELINE, JobKind.RESUME_REPLY):
        raise ValueError("classified retry kind must be run_pipeline or resume_reply")
    if kind is JobKind.RESUME_REPLY and email_id is None:
        raise ValueError("resume_reply retry requires email_id")
    if kind is JobKind.RUN_PIPELINE and email_id is not None:
        raise ValueError("run_pipeline retry cannot carry email_id")

    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        generation = _run_generation(c, run_id)
        if generation is None:
            return SettlementOutcome.FENCED
        status, reply_epoch = generation
        suffix = f":{email_id}" if email_id is not None else ""
        dedup_key = f"{kind.value}:{run_id}:{reply_epoch}{suffix}"
        if status == RunStatus.RECEIVED.value:
            return (
                SettlementOutcome.RETRIED
                if _existing_job_matches(
                    c,
                    dedup_key=dedup_key,
                    kind=kind,
                    run_id=run_id,
                    email_id=email_id,
                    operator_resolution_id=None,
                )
                else SettlementOutcome.FENCED
            )
        if status != RunStatus.EXTRACTING.value or not _rewind_run(c, run_id):
            return SettlementOutcome.FENCED
        enqueue_job(
            kind=kind,
            dedup_key=dedup_key,
            run_id=run_id,
            email_id=email_id,
            available_in_seconds=available_in_seconds,
            safe_last_error=result.diagnostic_code,
            conn=c,
        )
        if not _existing_job_matches(
            c,
            dedup_key=dedup_key,
            kind=kind,
            run_id=run_id,
            email_id=email_id,
            operator_resolution_id=None,
        ):
            raise RuntimeError("classified retry enqueue did not persist")
        return SettlementOutcome.RETRIED


def enqueue_operator_resume_retry(
    run_id: uuid.UUID,
    operator_resolution_id: uuid.UUID,
    result: PipelineResult,
    *,
    available_in_seconds: float,
    conn: psycopg.Connection | None = None,
) -> SettlementOutcome:
    """Rewind and enqueue one resolution-scoped operator retry atomically."""
    if result.outcome is not PipelineOutcome.RETRYABLE:
        raise ValueError("enqueue_operator_resume_retry requires a retryable result")
    dedup_key = f"operator_resume:{run_id}:{operator_resolution_id}"
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        try:
            load_operator_resume_resolution(
                run_id, operator_resolution_id, conn=c
            )
        except ValueError:
            return SettlementOutcome.FENCED
        generation = _run_generation(c, run_id)
        if generation is None:
            return SettlementOutcome.FENCED
        status, _reply_epoch = generation
        if status == RunStatus.RECEIVED.value:
            return (
                SettlementOutcome.RETRIED
                if _existing_job_matches(
                    c,
                    dedup_key=dedup_key,
                    kind=JobKind.OPERATOR_RESUME,
                    run_id=run_id,
                    email_id=None,
                    operator_resolution_id=operator_resolution_id,
                )
                else SettlementOutcome.FENCED
            )
        if status != RunStatus.EXTRACTING.value or not _rewind_run(c, run_id):
            return SettlementOutcome.FENCED
        enqueue_job(
            kind=JobKind.OPERATOR_RESUME,
            dedup_key=dedup_key,
            run_id=run_id,
            operator_resolution_id=operator_resolution_id,
            available_in_seconds=available_in_seconds,
            safe_last_error=result.diagnostic_code,
            conn=c,
        )
        if not _existing_job_matches(
            c,
            dedup_key=dedup_key,
            kind=JobKind.OPERATOR_RESUME,
            run_id=run_id,
            email_id=None,
            operator_resolution_id=operator_resolution_id,
        ):
            raise RuntimeError("operator retry enqueue did not persist")
        return SettlementOutcome.RETRIED


def settle_pipeline_job(
    job: Job,
    result: PipelineResult,
    *,
    backoff_seconds: float,
    conn: psycopg.Connection | None = None,
) -> SettlementOutcome:
    """Settle a classified leased job and its run under one exact fence."""
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        locked = _locked_job(c, job)
        if locked is None:
            return SettlementOutcome.FENCED
        attempts, max_attempts, stored_run_id = locked
        if stored_run_id is None or stored_run_id != job.run_id:
            return SettlementOutcome.FENCED

        if result.outcome is PipelineOutcome.OK:
            row = c.execute(
                "UPDATE jobs SET state = 'done', lease_token = NULL,"
                " leased_until = NULL, updated_at = now()"
                " WHERE id = %s AND state = 'leased' AND lease_token = %s"
                " RETURNING id",
                (str(job.id), str(job.lease_token)),
            ).fetchone()
            return SettlementOutcome.DONE if row else SettlementOutcome.FENCED

        if result.outcome is PipelineOutcome.RETRYABLE and attempts < max_attempts:
            if not _rewind_run(c, stored_run_id):
                return SettlementOutcome.FENCED
            row = c.execute(
                "UPDATE jobs SET state = 'pending',"
                " available_at = now() + (%s || ' seconds')::interval,"
                " last_error = %s, lease_token = NULL, leased_until = NULL,"
                " updated_at = now() WHERE id = %s AND state = 'leased'"
                " AND lease_token = %s RETURNING id",
                (
                    backoff_seconds,
                    result.diagnostic_code,
                    str(job.id),
                    str(job.lease_token),
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("locked retry settlement lost its lease")
            return SettlementOutcome.RETRIED

        if result.outcome is PipelineOutcome.RETRYABLE:
            reason = "RetryExhausted"
            target_state = "dead"
            outcome = SettlementOutcome.DEAD
        else:
            reason = result.reason.value
            target_state = "done"
            outcome = SettlementOutcome.DONE
        if not _set_run_error(
            c,
            stored_run_id,
            reason=reason,
            detail=_bounded_detail(
                result,
                attempts=attempts if outcome is SettlementOutcome.DEAD else None,
                max_attempts=max_attempts if outcome is SettlementOutcome.DEAD else None,
            ),
        ):
            return SettlementOutcome.FENCED
        row = c.execute(
            "UPDATE jobs SET state = %s, last_error = %s, lease_token = NULL,"
            " leased_until = NULL, updated_at = now() WHERE id = %s"
            " AND state = 'leased' AND lease_token = %s RETURNING id",
            (
                target_state,
                result.diagnostic_code,
                str(job.id),
                str(job.lease_token),
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("locked final settlement lost its lease")
        return outcome


def settle_background_terminal(
    run_id: uuid.UUID,
    result: PipelineResult,
    *,
    conn: psycopg.Connection | None = None,
) -> SettlementOutcome:
    """Apply a terminal first-attempt result when no leased job exists."""
    if result.outcome is not PipelineOutcome.TERMINAL:
        raise ValueError("settle_background_terminal requires a terminal result")
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        if not _set_run_error(
            c,
            run_id,
            reason=result.reason.value,
            detail=_bounded_detail(result),
        ):
            return SettlementOutcome.FENCED
        return SettlementOutcome.DONE


def settle_infrastructure_failure(
    job: Job,
    *,
    backoff_seconds: float,
    stage: PipelineStage = PipelineStage.UNKNOWN,
    reason: PipelineReason = PipelineReason.UNCLASSIFIED,
    conn: psycopg.Connection | None = None,
) -> SettlementOutcome:
    """Settle an escaped infrastructure failure without persisting exception text."""
    return settle_pipeline_job(
        job,
        PipelineResult(
            outcome=PipelineOutcome.RETRYABLE,
            stage=stage,
            reason=reason,
        ),
        backoff_seconds=backoff_seconds,
        conn=conn,
    )


def reap_expired_final_attempt(
    *, conn: psycopg.Connection | None = None
) -> SettlementOutcome | None:
    """Atomically dead-letter one exact expired final-attempt lease."""
    result = PipelineResult(
        outcome=PipelineOutcome.RETRYABLE,
        stage=PipelineStage.UNKNOWN,
        reason=PipelineReason.UNCLASSIFIED,
    )
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute(
            "SELECT id, run_id, attempts, max_attempts FROM jobs"
            " WHERE state = 'leased' AND attempts = max_attempts"
            " AND leased_until < now() ORDER BY leased_until"
            " FOR UPDATE SKIP LOCKED LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        job_id = uuid.UUID(str(row[0]))
        run_id = uuid.UUID(str(row[1])) if row[1] is not None else None
        attempts, max_attempts = int(row[2]), int(row[3])
        if run_id is None or not _set_run_error(
            c,
            run_id,
            reason="FinalAttemptLeaseExpired",
            detail=f"unknown:final_attempt_lease_expired;attempts={attempts}/{max_attempts}"[:200],
        ):
            return SettlementOutcome.FENCED
        updated = c.execute(
            "UPDATE jobs SET state = 'dead', last_error = %s,"
            " lease_token = NULL, leased_until = NULL, updated_at = now()"
            " WHERE id = %s AND state = 'leased' AND attempts = max_attempts"
            " RETURNING id",
            (result.diagnostic_code, str(job_id)),
        ).fetchone()
        if updated is None:
            raise RuntimeError("locked final-attempt reap lost its row")
        return SettlementOutcome.REAPED_FINAL_LEASE
