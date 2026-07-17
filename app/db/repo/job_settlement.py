"""Atomic failure-policy coordination across queue and payroll-run state.

Transport rows and business status remain separate authorities, but retry/final
settlement must commit together.  This module is the only repository seam allowed
to update both aggregates in one transaction.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

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
    next_delivery_attempt_at,
)


class SettlementOutcome(enum.StrEnum):
    """Bounded result of one cross-aggregate settlement operation."""

    DONE = "done"
    RETRIED = "retried"
    DEAD = "dead"
    FENCED = "fenced"
    REAPED_FINAL_LEASE = "reaped_final_lease"


_FINAL_LEASE_ERROR_STATUSES = frozenset(
    {
        RunStatus.RECEIVED,
        RunStatus.EXTRACTING,
        RunStatus.COMPUTED,
        RunStatus.APPROVED,
    }
)
_FINAL_LEASE_PRESERVE_STATUSES = frozenset(
    {
        RunStatus.SENT,
        RunStatus.AWAITING_REPLY,
        RunStatus.AWAITING_APPROVAL,
        RunStatus.NEEDS_OPERATOR,
        RunStatus.RECONCILED,
        RunStatus.REJECTED,
        RunStatus.ERROR,
    }
)
assert not (_FINAL_LEASE_ERROR_STATUSES & _FINAL_LEASE_PRESERVE_STATUSES)
assert frozenset(RunStatus) == (
    _FINAL_LEASE_ERROR_STATUSES | _FINAL_LEASE_PRESERVE_STATUSES
)


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
) -> tuple[int, int, uuid.UUID | None, JobKind] | None:
    row = conn.execute(
        "SELECT attempts, max_attempts, run_id, kind FROM jobs"
        " WHERE id = %s AND state = 'leased' AND lease_token = %s"
        " FOR UPDATE",
        (str(job.id), str(job.lease_token)),
    ).fetchone()
    if row is None:
        return None
    run_id = uuid.UUID(str(row[2])) if row[2] is not None else None
    return int(row[0]), int(row[1]), run_id, JobKind(str(row[3]))


def _delivery_failure_category(result: PipelineResult) -> str:
    """Map a bounded delivery result to the fixed attempt-ledger vocabulary."""
    reason = result.reason
    if reason in {
        PipelineReason.DELIVERY_TIMEOUT,
        PipelineReason.DELIVERY_CONNECTION_FAILURE,
    }:
        return "transport"
    if reason is PipelineReason.DELIVERY_SERVER_FAILURE:
        return "provider_5xx"
    if reason is PipelineReason.DELIVERY_RATE_LIMIT:
        return "rate_limited"
    if reason is PipelineReason.DELIVERY_IDEMPOTENCY_PAYLOAD_MISMATCH:
        return "payload_mismatch"
    if reason in {
        PipelineReason.DELIVERY_AUTHENTICATION_FAILURE,
        PipelineReason.DELIVERY_AUTHORIZATION_FAILURE,
    }:
        return "authorization"
    if reason is PipelineReason.DELIVERY_VALIDATION_FAILURE:
        return "validation"
    if reason is PipelineReason.DELIVERY_CONFIGURATION_FAILURE:
        return "configuration"
    return "unknown"


def _append_delivery_attempt(
    conn: psycopg.Connection,
    *,
    snapshot_id: uuid.UUID,
    attempt_state: str,
    failure_category: str,
) -> None:
    """Append one bounded fact without retaining a provider payload or error message."""
    row = conn.execute(
        "INSERT INTO outbound_delivery_attempts "
        "(snapshot_id, attempt_state, failure_category) VALUES (%s, %s, %s) "
        "RETURNING id",
        (str(snapshot_id), attempt_state, failure_category),
    ).fetchone()
    if row is None:
        raise RuntimeError("delivery attempt append did not return an id")


def _lock_outbound_reservation(
    conn: psycopg.Connection,
    *,
    run_id: uuid.UUID,
    email_id: uuid.UUID,
) -> tuple[uuid.UUID, datetime, str, str, bool] | None:
    """Lock one immutable outbound slot and return its delivery-safe facts."""
    row = conn.execute(
        "SELECT snapshot.id, snapshot.reserved_at, message.purpose, message.round, "
        "message.epoch, message.send_state, "
        "snapshot.reserved_at + interval '20 hours' > now() "
        "FROM outbound_email_snapshots AS snapshot "
        "JOIN email_messages AS message ON message.id = snapshot.email_id "
        "WHERE message.id = %s AND message.run_id = %s "
        "AND message.direction = 'outbound' FOR UPDATE OF snapshot, message",
        (str(email_id), str(run_id)),
    ).fetchone()
    if row is None:
        return None
    reserved_at = row[1]
    if not isinstance(reserved_at, datetime):
        raise RuntimeError("outbound reservation timestamp is not a datetime")
    return (
        uuid.UUID(str(row[0])),
        reserved_at,
        str(row[2]),
        str(row[5]),
        bool(row[6]),
    )


def settle_outbound_delivery_job(
    job: Job,
    result: PipelineResult,
    *,
    conn: psycopg.Connection | None = None,
) -> SettlementOutcome:
    """Settle one snapshot-backed delivery job under its exact lease token.

    The provider call happens before this function.  Every resulting database write is
    therefore made only after the leased queue row, immutable reservation, and expected
    run state have been locked together in one transaction.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        locked = _locked_job(c, job)
        if locked is None:
            return SettlementOutcome.FENCED
        attempts, _max_attempts, stored_run_id, stored_kind = locked
        if (
            stored_kind is not JobKind.SEND_OUTBOUND
            or job.kind is not JobKind.SEND_OUTBOUND
            or stored_run_id is None
            or stored_run_id != job.run_id
            or job.email_id is None
        ):
            return SettlementOutcome.FENCED

        reservation = _lock_outbound_reservation(
            c, run_id=stored_run_id, email_id=job.email_id
        )
        if reservation is None:
            return SettlementOutcome.FENCED
        snapshot_id, reserved_at, purpose, send_state, replay_window_open = reservation
        if purpose not in {
            "confirmation",
            "clarification",
            "clarification_field_regression",
        } or send_state != "reserved":
            return SettlementOutcome.FENCED

        run_status = _lock_run_status(c, stored_run_id)
        expected_status = (
            RunStatus.APPROVED
            if purpose == "confirmation"
            else RunStatus.AWAITING_REPLY
        )
        if run_status is not expected_status:
            return SettlementOutcome.FENCED

        if result.outcome is PipelineOutcome.OK:
            _append_delivery_attempt(
                c,
                snapshot_id=snapshot_id,
                attempt_state="sent",
                failure_category="none",
            )
            sent = c.execute(
                "UPDATE email_messages SET send_state = 'sent' "
                "WHERE id = %s AND run_id = %s AND direction = 'outbound' "
                "AND send_state = 'reserved' RETURNING id",
                (str(job.email_id), str(stored_run_id)),
            ).fetchone()
            if sent is None:
                raise RuntimeError("locked delivery success lost its reservation")
            if purpose == "confirmation":
                advanced = c.execute(
                    "UPDATE payroll_runs SET status = 'sent', updated_at = now() "
                    "WHERE id = %s AND status = 'approved' RETURNING id",
                    (str(stored_run_id),),
                ).fetchone()
                if advanced is None:
                    raise RuntimeError("locked confirmation success lost its run state")
            completed = c.execute(
                "UPDATE jobs SET state = 'done', lease_token = NULL, leased_until = NULL, "
                "updated_at = now() WHERE id = %s AND state = 'leased' "
                "AND lease_token = %s RETURNING id",
                (str(job.id), str(job.lease_token)),
            ).fetchone()
            if completed is None:
                raise RuntimeError("locked delivery success lost its lease")
            return SettlementOutcome.DONE

        next_attempt = None
        if result.outcome is PipelineOutcome.RETRYABLE and replay_window_open:
            next_attempt = next_delivery_attempt_at(
                reserved_at, completed_attempts=attempts
            )
        category = _delivery_failure_category(result)
        if next_attempt is not None:
            _append_delivery_attempt(
                c,
                snapshot_id=snapshot_id,
                attempt_state="retry_scheduled",
                failure_category=category,
            )
            rescheduled = c.execute(
                "UPDATE jobs SET state = 'pending', available_at = %s, last_error = %s, "
                "lease_token = NULL, leased_until = NULL, updated_at = now() "
                "WHERE id = %s AND state = 'leased' AND lease_token = %s RETURNING id",
                (next_attempt, result.diagnostic_code, str(job.id), str(job.lease_token)),
            ).fetchone()
            if rescheduled is None:
                raise RuntimeError("locked delivery retry lost its lease")
            return SettlementOutcome.RETRIED

        _append_delivery_attempt(
            c,
            snapshot_id=snapshot_id,
            attempt_state="needs_operator",
            failure_category=category,
        )
        review_reason = (
            "DeliveryReview"
            if purpose == "confirmation"
            else "ClarificationDeliveryReview"
        )
        reviewed = c.execute(
            "UPDATE payroll_runs SET status = 'needs_operator', error_reason = %s, "
            "error_detail = %s, updated_at = now() WHERE id = %s AND status = %s "
            "RETURNING id",
            (
                review_reason,
                f"delivery_review:{category}",
                str(stored_run_id),
                expected_status.value,
            ),
        ).fetchone()
        if reviewed is None:
            raise RuntimeError("locked delivery review lost its run state")
        completed = c.execute(
            "UPDATE jobs SET state = 'done', last_error = %s, lease_token = NULL, "
            "leased_until = NULL, updated_at = now() WHERE id = %s "
            "AND state = 'leased' AND lease_token = %s RETURNING id",
            (result.diagnostic_code, str(job.id), str(job.lease_token)),
        ).fetchone()
        if completed is None:
            raise RuntimeError("locked delivery review lost its lease")
        return SettlementOutcome.DONE


def _settle_ingest_job(
    conn: psycopg.Connection,
    job: Job,
    result: PipelineResult,
    *,
    attempts: int,
    max_attempts: int,
    backoff_seconds: float,
) -> SettlementOutcome:
    """Settle one fenced ingest lease without touching payroll business state."""
    if result.outcome is PipelineOutcome.RETRYABLE and attempts < max_attempts:
        target_state = "pending"
        outcome = SettlementOutcome.RETRIED
    elif result.outcome is PipelineOutcome.RETRYABLE:
        target_state = "dead"
        outcome = SettlementOutcome.DEAD
    else:
        target_state = "done"
        outcome = SettlementOutcome.DONE

    row = conn.execute(
        "UPDATE jobs SET state = %s,"
        " available_at = CASE WHEN %s = 'pending'"
        " THEN now() + (%s || ' seconds')::interval ELSE available_at END,"
        " last_error = CASE WHEN %s = 'ok' THEN last_error ELSE %s END,"
        " lease_token = NULL, leased_until = NULL, updated_at = now()"
        " WHERE id = %s AND state = 'leased' AND lease_token = %s"
        " RETURNING id",
        (
            target_state,
            target_state,
            backoff_seconds,
            result.outcome.value,
            result.diagnostic_code,
            str(job.id),
            str(job.lease_token),
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError("locked ingest settlement lost its lease")
    return outcome


def _set_run_error(
    conn: psycopg.Connection,
    run_id: uuid.UUID,
    *,
    reason: str,
    detail: str,
    expected_status: RunStatus = RunStatus.EXTRACTING,
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
            expected_status.value,
        ),
    ).fetchone()
    return row is not None


def _lock_run_status(
    conn: psycopg.Connection, run_id: uuid.UUID
) -> RunStatus | None:
    row = conn.execute(
        "SELECT status FROM payroll_runs WHERE id = %s FOR UPDATE",
        (str(run_id),),
    ).fetchone()
    return RunStatus(str(row[0])) if row is not None else None


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
        attempts, max_attempts, stored_run_id, stored_kind = locked
        if stored_kind is not job.kind:
            return SettlementOutcome.FENCED
        if stored_kind is JobKind.INGEST:
            if stored_run_id is not None or job.run_id is not None:
                return SettlementOutcome.FENCED
            return _settle_ingest_job(
                c,
                job,
                result,
                attempts=attempts,
                max_attempts=max_attempts,
                backoff_seconds=backoff_seconds,
            )
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
    expected_status: RunStatus = RunStatus.EXTRACTING,
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
            expected_status=expected_status,
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
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute(
            "SELECT id, run_id, attempts, max_attempts, kind FROM jobs"
            " WHERE state = 'leased' AND attempts = max_attempts"
            " AND leased_until < now() ORDER BY leased_until"
            " FOR UPDATE SKIP LOCKED LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        job_id = uuid.UUID(str(row[0]))
        run_id = uuid.UUID(str(row[1])) if row[1] is not None else None
        attempts, max_attempts = int(row[2]), int(row[3])
        kind = JobKind(str(row[4]))
        if kind is JobKind.INGEST:
            if run_id is not None:
                return SettlementOutcome.FENCED
        else:
            if run_id is None:
                return SettlementOutcome.FENCED
            run_status = _lock_run_status(c, run_id)
            if run_status is None:
                return SettlementOutcome.FENCED
            if run_status in _FINAL_LEASE_ERROR_STATUSES and not _set_run_error(
                c,
                run_id,
                reason="FinalAttemptLeaseExpired",
                detail=(
                    "unknown:final_attempt_lease_expired;"
                    f"attempts={attempts}/{max_attempts}"
                )[:200],
                expected_status=run_status,
            ):
                raise RuntimeError("locked final-attempt reap lost its run status")
        updated = c.execute(
            "UPDATE jobs SET state = 'dead',"
            " lease_token = NULL, leased_until = NULL, updated_at = now()"
            " WHERE id = %s AND state = 'leased' AND attempts = max_attempts"
            " RETURNING id",
            (str(job_id),),
        ).fetchone()
        if updated is None:
            raise RuntimeError("locked final-attempt reap lost its row")
        return SettlementOutcome.REAPED_FINAL_LEASE
