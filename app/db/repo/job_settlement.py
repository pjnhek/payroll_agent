"""Atomic failure-policy coordination across queue and payroll-run state.

Transport rows and business status remain separate authorities, but retry/final
settlement must commit together.  This module is the only repository seam allowed
to update both aggregates in one transaction.
"""
from __future__ import annotations

import enum
import logging
import uuid
from datetime import datetime
from typing import Any

import psycopg
import psycopg.rows

from app.db.repo._shared import _conn_ctx, _nulltx
from app.db.repo.jobs import enqueue_job
from app.db.repo.operator_resume_resolutions import load_operator_resume_resolution
from app.db.repo.outbound_handoffs import (
    ProviderHandoffAuthorization,
    finalize_outbound_provider_handoff,
    release_outbound_provider_handoff_for_retry,
    release_outbound_provider_handoff_to_delivery_review,
)
from app.db.repo.roster import load_roster_for_business
from app.db.repo.runs import load_run
from app.models.job import Job, JobKind
from app.models.status import RunStatus
from app.pipeline.result import (
    PipelineOutcome,
    PipelineReason,
    PipelineResult,
    PipelineStage,
    next_delivery_attempt_at,
)

logger = logging.getLogger("payroll_agent.orchestrator")


class SettlementOutcome(enum.StrEnum):
    """Bounded result of one cross-aggregate settlement operation."""

    DONE = "done"
    RETRIED = "retried"
    DEAD = "dead"
    FENCED = "fenced"
    LOST_LEASE = "lost_lease"
    INVALID_CONTEXT = "invalid_context"
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

_REPLAYABLE_DELIVERY_REASONS = frozenset(
    {
        PipelineReason.DELIVERY_TIMEOUT,
        PipelineReason.DELIVERY_CONNECTION_FAILURE,
        PipelineReason.DELIVERY_RATE_LIMIT,
        PipelineReason.DELIVERY_SERVER_FAILURE,
    }
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
) -> tuple[int, int, uuid.UUID | None, JobKind, uuid.UUID | None] | None:
    row = conn.execute(
        "SELECT attempts, max_attempts, run_id, kind, email_id FROM jobs"
        " WHERE id = %s AND state = 'leased' AND lease_token = %s"
        " FOR UPDATE",
        (str(job.id), str(job.lease_token)),
    ).fetchone()
    if row is None:
        return None
    run_id = uuid.UUID(str(row[2])) if row[2] is not None else None
    email_id = uuid.UUID(str(row[4])) if row[4] is not None else None
    return int(row[0]), int(row[1]), run_id, JobKind(str(row[3])), email_id


def _retire_invalid_outbound_lease(
    conn: psycopg.Connection,
    *,
    job_id: uuid.UUID,
    lease_token: uuid.UUID,
    target_state: str,
) -> None:
    """Retire an obsolete held outbound lease without touching delivery state."""
    retired = conn.execute(
        "UPDATE jobs SET state = %s, last_error = %s, lease_token = NULL, "
        "leased_until = NULL, updated_at = now() WHERE id = %s "
        "AND state = 'leased' AND lease_token = %s RETURNING id",
        (
            target_state,
            "delivery:invalid_context",
            str(job_id),
            str(lease_token),
        ),
    ).fetchone()
    if retired is None:
        raise RuntimeError("locked invalid delivery context lost its lease")


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
    if reason is PipelineReason.DELIVERY_AUTHORIZATION_EXPIRED:
        return "authorization_expired"
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
) -> tuple[uuid.UUID, datetime, str, int, str, bool] | None:
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
        int(row[4]),
        str(row[5]),
        bool(row[6]),
    )


def _lock_current_provider_handoff(
    conn: psycopg.Connection,
    *,
    job: Job,
    run_id: uuid.UUID,
    email_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    epoch: int,
) -> ProviderHandoffAuthorization | None:
    """Lock authority owned by this exact leased delivery job, never adopt it.

    Provider authority may only be transferred by the pre-provider authorizer.  A
    post-provider result is therefore allowed to release/finalize the fence it
    already owns, but never to turn an expired predecessor into its own authority.
    """
    row = conn.execute(
        "SELECT id, not_after FROM outbound_provider_handoffs "
        "WHERE run_id = %s AND email_id = %s AND snapshot_id = %s "
        "AND job_id = %s AND epoch = %s AND lease_token = %s "
        "AND released_at IS NULL FOR UPDATE",
        (
            str(run_id),
            str(email_id),
            str(snapshot_id),
            str(job.id),
            epoch,
            str(job.lease_token),
        ),
    ).fetchone()
    if row is None:
        return None
    not_after = row[1]
    if not isinstance(not_after, datetime):
        raise RuntimeError("locked provider handoff has no replay deadline")
    return ProviderHandoffAuthorization(
        handoff_id=uuid.UUID(str(row[0])),
        run_id=run_id,
        email_id=email_id,
        snapshot_id=snapshot_id,
        job_id=job.id,
        lease_token=job.lease_token,
        epoch=epoch,
        snapshot={},
        not_after=not_after,
    )


def _lock_any_active_provider_handoff(
    conn: psycopg.Connection, run_id: uuid.UUID
) -> bool:
    """Lock the one active handoff, if any, before a no-handoff settlement.

    The partial unique index permits at most one active handoff per run.  A
    pre-provider expiry may write review evidence only when that slot is empty;
    otherwise the regular exact-owner handoff path below remains authoritative.
    """
    row = conn.execute(
        "SELECT id FROM outbound_provider_handoffs WHERE run_id = %s "
        "AND released_at IS NULL FOR UPDATE",
        (str(run_id),),
    ).fetchone()
    return row is not None


def _settle_delivery_review(
    conn: psycopg.Connection,
    *,
    job: Job,
    result: PipelineResult,
    run_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    purpose: str,
    expected_status: RunStatus,
) -> SettlementOutcome:
    """Append bounded review evidence and complete the exact leased delivery job."""
    category = _delivery_failure_category(result)
    _append_delivery_attempt(
        conn,
        snapshot_id=snapshot_id,
        attempt_state="needs_operator",
        failure_category=category,
    )
    review_reason = (
        "DeliveryReview" if purpose == "confirmation" else "ClarificationDeliveryReview"
    )
    reviewed = conn.execute(
        "UPDATE payroll_runs SET status = 'needs_operator', error_reason = %s, "
        "error_detail = %s, updated_at = now() WHERE id = %s AND status = %s "
        "RETURNING id",
        (
            review_reason,
            f"delivery_review:{category}",
            str(run_id),
            expected_status.value,
        ),
    ).fetchone()
    if reviewed is None:
        raise RuntimeError("locked delivery review lost its run state")
    completed = conn.execute(
        "UPDATE jobs SET state = 'done', last_error = %s, lease_token = NULL, "
        "leased_until = NULL, updated_at = now() WHERE id = %s "
        "AND state = 'leased' AND lease_token = %s RETURNING id",
        (result.diagnostic_code, str(job.id), str(job.lease_token)),
    ).fetchone()
    if completed is None:
        raise RuntimeError("locked delivery review lost its lease")
    return SettlementOutcome.DONE


def _complete_confirmation_after_send(
    conn: psycopg.Connection,
    run_id: uuid.UUID,
) -> None:
    """Apply post-send alias learning and reconciliation inside the delivery fence."""
    from app.pipeline import alias_learning

    run = load_run(run_id, conn=conn)
    if run is None:
        raise RuntimeError("locked confirmation success lost its run")
    roster = load_roster_for_business(run["business_id"], conn=conn)
    try:
        with conn.transaction():
            alias_learning.write_aliases_if_safe(run_id, run, roster, conn=conn)
    except Exception as alias_exc:  # noqa: BLE001
        logger.warning("alias write skipped for run %s: %s", run_id, type(alias_exc).__name__)
    reconciled = conn.execute(
        "UPDATE payroll_runs SET status = 'reconciled', updated_at = now() "
        "WHERE id = %s AND status = 'sent' RETURNING id",
        (str(run_id),),
    ).fetchone()
    if reconciled is None:
        raise RuntimeError("locked confirmation success lost its sent run state")


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
            return SettlementOutcome.LOST_LEASE
        attempts, _max_attempts, stored_run_id, stored_kind, stored_email_id = locked
        if (
            stored_kind is not JobKind.SEND_OUTBOUND
            or job.kind is not JobKind.SEND_OUTBOUND
            or stored_run_id is None
            or stored_run_id != job.run_id
            or job.email_id is None
            or stored_email_id is None
            or stored_email_id != job.email_id
        ):
            _retire_invalid_outbound_lease(
                c, job_id=job.id, lease_token=job.lease_token, target_state="done"
            )
            return SettlementOutcome.INVALID_CONTEXT

        reservation = _lock_outbound_reservation(
            c, run_id=stored_run_id, email_id=job.email_id
        )
        if reservation is None:
            _retire_invalid_outbound_lease(
                c, job_id=job.id, lease_token=job.lease_token, target_state="done"
            )
            return SettlementOutcome.INVALID_CONTEXT
        (
            snapshot_id,
            reserved_at,
            purpose,
            message_epoch,
            send_state,
            replay_window_open,
        ) = reservation
        if purpose not in {
            "confirmation",
            "clarification",
            "clarification_field_regression",
        } or send_state != "reserved":
            _retire_invalid_outbound_lease(
                c, job_id=job.id, lease_token=job.lease_token, target_state="done"
            )
            return SettlementOutcome.INVALID_CONTEXT

        run_generation = _lock_run_status(c, stored_run_id)
        if run_generation is None:
            _retire_invalid_outbound_lease(
                c, job_id=job.id, lease_token=job.lease_token, target_state="done"
            )
            return SettlementOutcome.INVALID_CONTEXT
        run_status, run_epoch, record_only = run_generation
        if run_epoch is not None and message_epoch != run_epoch:
            _retire_invalid_outbound_lease(
                c, job_id=job.id, lease_token=job.lease_token, target_state="done"
            )
            return SettlementOutcome.INVALID_CONTEXT
        expected_status = (
            RunStatus.APPROVED
            if purpose == "confirmation"
            else RunStatus.AWAITING_REPLY
        )
        if run_status is not expected_status:
            _retire_invalid_outbound_lease(
                c, job_id=job.id, lease_token=job.lease_token, target_state="done"
            )
            return SettlementOutcome.INVALID_CONTEXT

        if result.reason is PipelineReason.DELIVERY_RECORD_ONLY:
            if not record_only:
                _retire_invalid_outbound_lease(
                    c, job_id=job.id, lease_token=job.lease_token, target_state="done"
                )
                return SettlementOutcome.INVALID_CONTEXT
            sent = c.execute(
                "UPDATE email_messages SET send_state = 'sent' "
                "WHERE id = %s AND run_id = %s AND direction = 'outbound' "
                "AND send_state = 'reserved' RETURNING id",
                (str(job.email_id), str(stored_run_id)),
            ).fetchone()
            if sent is None:
                raise RuntimeError("locked record-only delivery lost its reservation")
            if purpose == "confirmation":
                advanced = c.execute(
                    "UPDATE payroll_runs SET status = 'sent', updated_at = now() "
                    "WHERE id = %s AND status = 'approved' RETURNING id",
                    (str(stored_run_id),),
                ).fetchone()
                if advanced is None:
                    raise RuntimeError("locked record-only confirmation lost its run state")
                _complete_confirmation_after_send(c, stored_run_id)
            completed = c.execute(
                "UPDATE jobs SET state = 'done', lease_token = NULL, leased_until = NULL, "
                "updated_at = now() WHERE id = %s AND state = 'leased' "
                "AND lease_token = %s RETURNING id",
                (str(job.id), str(job.lease_token)),
            ).fetchone()
            if completed is None:
                raise RuntimeError("locked record-only delivery lost its lease")
            return SettlementOutcome.DONE

        pre_provider_expiry = (
            result.outcome is PipelineOutcome.TERMINAL
            and result.stage is PipelineStage.DELIVERY
            and result.reason is PipelineReason.DELIVERY_AUTHORIZATION_EXPIRED
            and not record_only
            and not replay_window_open
        )
        if pre_provider_expiry and not _lock_any_active_provider_handoff(c, stored_run_id):
            return _settle_delivery_review(
                c,
                job=job,
                result=result,
                run_id=stored_run_id,
                snapshot_id=snapshot_id,
                purpose=purpose,
                expected_status=expected_status,
            )

        authorization = _lock_current_provider_handoff(
            c,
            job=job,
            run_id=stored_run_id,
            email_id=job.email_id,
            snapshot_id=snapshot_id,
            epoch=message_epoch,
        )
        if authorization is None:
            _retire_invalid_outbound_lease(
                c, job_id=job.id, lease_token=job.lease_token, target_state="done"
            )
            return SettlementOutcome.INVALID_CONTEXT

        if result.outcome is PipelineOutcome.OK:
            if not finalize_outbound_provider_handoff(authorization, conn=c):
                raise RuntimeError("locked delivery success lost its provider handoff")
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
                _complete_confirmation_after_send(c, stored_run_id)
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
        if (
            result.outcome is PipelineOutcome.RETRYABLE
            and result.reason in _REPLAYABLE_DELIVERY_REASONS
            and replay_window_open
        ):
            next_attempt = next_delivery_attempt_at(
                reserved_at, completed_attempts=attempts
            )
        category = _delivery_failure_category(result)
        if next_attempt is not None:
            if not release_outbound_provider_handoff_for_retry(authorization, conn=c):
                raise RuntimeError("locked delivery retry lost its provider handoff")
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

        if not release_outbound_provider_handoff_to_delivery_review(authorization, conn=c):
            raise RuntimeError("locked delivery review lost its provider handoff")
        return _settle_delivery_review(
            c,
            job=job,
            result=result,
            run_id=stored_run_id,
            snapshot_id=snapshot_id,
            purpose=purpose,
            expected_status=expected_status,
        )


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
) -> tuple[RunStatus, int | None, bool] | None:
    row = conn.execute(
        "SELECT status, reply_epoch, record_only FROM payroll_runs WHERE id = %s FOR UPDATE",
        (str(run_id),),
    ).fetchone()
    if row is None:
        return None
    # The one-column fallback keeps old FakeConnection contract tests useful; a
    # real payroll_runs row always returns the locked reply_epoch column.
    run_epoch = int(row[1]) if len(row) > 1 and row[1] is not None else None
    record_only = bool(row[2]) if len(row) > 2 and row[2] is not None else False
    return RunStatus(str(row[0])), run_epoch, record_only


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
        attempts, max_attempts, stored_run_id, stored_kind, _stored_email_id = locked
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
            "SELECT id, run_id, email_id, attempts, max_attempts, kind, lease_token FROM jobs"
            " WHERE state = 'leased' AND attempts = max_attempts"
            " AND leased_until < now() ORDER BY leased_until"
            " FOR UPDATE SKIP LOCKED LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        job_id = uuid.UUID(str(row[0]))
        run_id = uuid.UUID(str(row[1])) if row[1] is not None else None
        email_id = uuid.UUID(str(row[2])) if row[2] is not None else None
        attempts, max_attempts = int(row[3]), int(row[4])
        kind = JobKind(str(row[5]))
        lease_token = uuid.UUID(str(row[6]))
        if kind is JobKind.INGEST:
            if run_id is not None:
                return SettlementOutcome.FENCED
        elif kind is JobKind.SEND_OUTBOUND:
            if run_id is None or email_id is None:
                _retire_invalid_outbound_lease(
                    c,
                    job_id=job_id,
                    lease_token=lease_token,
                    target_state="dead",
                )
                return SettlementOutcome.INVALID_CONTEXT
            reservation = _lock_outbound_reservation(
                c, run_id=run_id, email_id=email_id
            )
            if reservation is None:
                _retire_invalid_outbound_lease(
                    c,
                    job_id=job_id,
                    lease_token=lease_token,
                    target_state="dead",
                )
                return SettlementOutcome.INVALID_CONTEXT
            (
                snapshot_id,
                _reserved_at,
                purpose,
                message_epoch,
                send_state,
                _replay_window_open,
            ) = reservation
            if purpose not in {
                "confirmation",
                "clarification",
                "clarification_field_regression",
            } or send_state != "reserved":
                _retire_invalid_outbound_lease(
                    c,
                    job_id=job_id,
                    lease_token=lease_token,
                    target_state="dead",
                )
                return SettlementOutcome.INVALID_CONTEXT
            run_generation = _lock_run_status(c, run_id)
            if run_generation is None:
                _retire_invalid_outbound_lease(
                    c,
                    job_id=job_id,
                    lease_token=lease_token,
                    target_state="dead",
                )
                return SettlementOutcome.INVALID_CONTEXT
            run_status, run_epoch, _record_only = run_generation
            if run_epoch is not None and message_epoch != run_epoch:
                _retire_invalid_outbound_lease(
                    c,
                    job_id=job_id,
                    lease_token=lease_token,
                    target_state="dead",
                )
                return SettlementOutcome.INVALID_CONTEXT
            expected_status = (
                RunStatus.APPROVED
                if purpose == "confirmation"
                else RunStatus.AWAITING_REPLY
            )
            if run_status is not expected_status:
                _retire_invalid_outbound_lease(
                    c,
                    job_id=job_id,
                    lease_token=lease_token,
                    target_state="dead",
                )
                return SettlementOutcome.INVALID_CONTEXT
            reaper_job = Job(
                id=job_id,
                kind=kind,
                run_id=run_id,
                email_id=email_id,
                attempts=attempts,
                max_attempts=max_attempts,
                lease_token=lease_token,
            )
            authorization = _lock_current_provider_handoff(
                c,
                job=reaper_job,
                run_id=run_id,
                email_id=email_id,
                snapshot_id=snapshot_id,
                epoch=message_epoch,
            )
            if authorization is None:
                _retire_invalid_outbound_lease(
                    c,
                    job_id=job_id,
                    lease_token=lease_token,
                    target_state="dead",
                )
                return SettlementOutcome.INVALID_CONTEXT
            if not release_outbound_provider_handoff_to_delivery_review(authorization, conn=c):
                raise RuntimeError("locked final delivery reap lost its provider handoff")
            _append_delivery_attempt(
                c,
                snapshot_id=snapshot_id,
                attempt_state="needs_operator",
                failure_category="final_attempt_lease_expired",
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
                    "delivery_review:final_attempt_lease_expired",
                    str(run_id),
                    expected_status.value,
                ),
            ).fetchone()
            if reviewed is None:
                raise RuntimeError("locked final delivery reap lost its run status")
        else:
            if run_id is None:
                return SettlementOutcome.FENCED
            run_generation = _lock_run_status(c, run_id)
            if run_generation is None:
                return SettlementOutcome.FENCED
            run_status, _run_epoch, _record_only = run_generation
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
            " AND leased_until < now()"
            " RETURNING id",
            (str(job_id),),
        ).fetchone()
        if updated is None:
            raise RuntimeError("locked final-attempt reap lost its row")
        return SettlementOutcome.REAPED_FINAL_LEASE


def list_unaccounted_error_runs(
    limit: int = 50, conn: psycopg.Connection | None = None
) -> list[dict[str, Any]]:
    """The alarm predicate: runs in ERROR that no job ever settled for.

    Side-effect-free read — a plain SELECT, no mutation, no fencing. Projects
    ONLY `id`, `error_reason`, `updated_at`. `error_detail` is deliberately
    excluded from this projection: the alarm needs to make a problem
    FINDABLE, not reproduce a diagnostic — the operator follows the run's own
    detail link for that. Ordered by the run's `updated_at DESC` and bounded
    by `limit` (default 50), so this can never hand an unauthenticated
    caller an unbounded result set.

    A naive "job success rate vs. error-run count" ratio is a FALSE-POSITIVE
    GENERATOR now that "job `done` + run `error`" is the normal, correct
    shape of a legitimately-classified terminal failure — every ordinary
    stage failure ends up exactly there. This function replaces that literal
    ratio: fire only on a run in `error` with NO corresponding terminal/dead
    job settlement — an error state no job ever claimed responsibility for.
    This is an ANTI-JOIN, not a ratio.

    THE CORRELATION IS TRANSACTION-TIMESTAMP EQUALITY, and that is the whole
    discriminating power of this query:

    - A bare `NOT EXISTS (job in done/dead for this run)` would let a run's
      OLDER, unrelated completed job (the one that carried it all the way to
      `approved`, say) vouch for a LATER, genuinely unaccounted error — the
      alarm would then never fire at all. Correlating the settling job with
      the SPECIFIC error transition, not merely its existence, is what makes
      this predicate discriminate a settled failure from a swallowed one.
    - Every LEGITIMATE settlement (`settle_pipeline_job`'s terminal and
      retry-exhausted branches, and `reap_expired_final_attempt`'s
      final-lease-expiry branch) writes the run's `error` status and the
      settling job's terminal state inside ONE transaction. Postgres
      evaluates `now()` as the TRANSACTION START time, so both rows receive
      the IDENTICAL timestamp and the equality holds EXACTLY — that "job
      done/dead + run error" shape is therefore silent here, which is
      precisely the false-positive class the naive ratio above would have
      generated on every correctly-handled terminal failure.

    - EQUALITY, NOT `>=` — IN BOTH DIRECTIONS, and relaxing this is
      forbidden. An earlier terminal job is a stale success and must not
      vouch for a later error; equality already excludes it (so does `>=`).
      The direction that actually separates the two operators is a
      STRICTLY LATER terminal job, and it is a real, reachable sequence, not
      a hypothetical: `record_run_error()` (`app/db/repo/runs.py`) can drive
      a run to `error` entirely on its own (the approve route's delivery
      error boundary is the one production caller reachable today — see
      below); a previously-leased pipeline job can independently lose its
      forward `claim_status(RECEIVED -> EXTRACTING)` CAS
      (`app/queue/handlers/pipeline.py`), return `PipelineOutcome.OK`
      without writing anything to the run, and be settled `done` afterwards
      with a strictly LATER `updated_at`
      (`settle_pipeline_job`'s OK branch). Under `>=` that unrelated LATER
      settlement would silently vouch for the EARLIER, genuinely unaccounted
      error, and the alarm would stay quiet on exactly the swallowing
      pathology this predicate exists to catch. Equality still fires there,
      correctly. This trades a POSSIBLE false positive (a legitimate
      settlement whose timestamps happen to diverge for some reason not
      enumerated below) for the ELIMINATION of a real false negative — and
      for an alarm that is the correct direction: a false positive costs an
      operator one look at a run that turns out fine; a false negative is
      the swallowing bug persisting completely undetected, which is the
      entire failure mode this predicate exists to surface.

    - `settle_background_terminal()` writes a run's `error` status with NO
      JOB AT ALL, and has no production caller today. It is classified here
      DELIBERATELY, not by accident: a run errored through it is reported —
      no job took responsibility for that error, which is exactly this
      predicate's definition of unaccounted — so a future caller inherits a
      decided semantics rather than a silent gap.

    - A KNOWN, REACHABLE production path this predicate correctly fires on,
      and this is a TRUE POSITIVE, not a bug: the approve route's delivery
      error boundary (`app/routes/runs.py`) calls `record_run_error()` while
      its enclosing transaction — including any send job it had enqueued —
      has already rolled back. No job settles for that run. By definition
      this is an error the transport layer never recorded anywhere else, so
      the run is reported. Do not widen this predicate to silence it.

    - NO MUTE, NO ACKNOWLEDGE, NO TIME-BOXED AUTO-CLEAR. The result is
      purely derived from current state: once the run is retriggered (moved
      out of `error`) or settled by a later legitimate write, this query
      returns empty on its own and the alarm goes quiet without any operator
      action. A lookback window was considered and rejected here
      deliberately — a window is a time-boxed auto-clear by another name.

    EQUALITY SAFETY — every writer of `payroll_runs.updated_at` was
    enumerated against the live source before finalizing this predicate,
    checking specifically for one failure mode: could ANY of them bump a
    run's `updated_at` WHILE its `status` stays `error`, breaking the
    equality match on an already-correctly-settled run (a false positive)?
    The full enumeration is recorded alongside this plan's execution record
    rather than only here, because the predicate's safety rests on it and it
    must be checked, not assumed. Short version: every DIRECT status writer
    either no-ops once a run is already `error` (`record_run_error`'s own
    `_TERMINAL_STATUSES` CAS), is itself CAS'd to a specific expected prior
    status that is never `error` (`_set_run_error`'s `expected_status`,
    always the one queue/repo module allowed to WRITE `error`), or
    explicitly excludes `error` from its scope (`rewind_for_reclaim`'s
    `WHERE status IN ('extracting', 'computed', 'sent')`). The JSONB-only
    writers in `pipeline_state.py` carry no status gate at all, but every
    reachable single-execution call path only invokes them while a run is
    `extracting` (they run inside `_run_stages`, which only starts after
    `set_status(EXTRACTING)`); the sole theoretical exception is the
    pre-existing, independently documented reclaimed-job double-execution
    hazard (a lease-expired worker's zombie predecessor still mid-flight)
    that this queue design already accepts elsewhere as a residual risk —
    not a new hazard introduced by this predicate, and consistent with the
    equality-over-`>=` tradeoff already made above.
    """
    sql = (
        "SELECT id, error_reason, updated_at FROM payroll_runs"
        " WHERE status = 'error' AND NOT EXISTS ("
        "SELECT 1 FROM jobs"
        " WHERE jobs.run_id = payroll_runs.id"
        " AND jobs.state IN ('done', 'dead')"
        " AND jobs.updated_at = payroll_runs.updated_at"
        ") ORDER BY payroll_runs.updated_at DESC LIMIT %s"
    )
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, (limit,))
        return cur.fetchall()
