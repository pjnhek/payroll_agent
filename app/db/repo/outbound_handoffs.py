"""Durable provider authority for one frozen outbound delivery generation.

The provider request deliberately happens *after* this module commits.  The short
transaction locks jobs -> frozen snapshot/email -> run -> active handoff; an operator
retrigger locks its run and then reads only the active handoff.  That order avoids a
cycle and leaves no transaction open across provider I/O.
"""
from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime
from typing import Any, Literal

import psycopg
import psycopg.rows

from app.db.repo._shared import _conn_ctx, _nulltx
from app.models.job import Job, JobKind
from app.models.status import RunStatus

_HANDOFF_RELEASE_REASONS = frozenset(
    {"retry_scheduled", "finalized", "delivery_review"}
)


@dataclasses.dataclass(frozen=True)
class ProviderHandoffAuthorization:
    """The sole authority to issue one provider request from a frozen snapshot."""

    handoff_id: uuid.UUID
    run_id: uuid.UUID
    email_id: uuid.UUID
    snapshot_id: uuid.UUID
    job_id: uuid.UUID
    lease_token: uuid.UUID
    epoch: int
    snapshot: dict[str, Any]
    not_after: datetime


@dataclasses.dataclass(frozen=True)
class ProviderHandoffRecordOnly:
    """A locked record-only run: valid queue work with no provider authority."""

    run_id: uuid.UUID


@dataclasses.dataclass(frozen=True)
class ProviderHandoffActive:
    """Bounded no-provider result for invalid, expired, or already-held authority."""

    reason: Literal[
        "invalid_context",
        "replay_window_closed",
        "foreign_active_handoff",
        "active_handoff_unexpired",
    ]
    handoff_id: uuid.UUID | None = None


type ProviderHandoffOutcome = (
    ProviderHandoffAuthorization | ProviderHandoffRecordOnly | ProviderHandoffActive
)


class ActiveOutboundProviderHandoffError(RuntimeError):
    """Raised when an epoch-changing operation meets an active provider fence."""

    def __init__(self, run_id: uuid.UUID) -> None:
        super().__init__(f"active outbound provider handoff for run {run_id}")
        self.run_id = run_id


def _as_uuid(value: object) -> uuid.UUID:
    return uuid.UUID(str(value))


def _locked_send_job(
    conn: psycopg.Connection, job: Job
) -> tuple[JobKind, uuid.UUID | None, uuid.UUID | None, datetime] | None:
    row = conn.execute(
        "SELECT kind, run_id, email_id, leased_until FROM jobs "
        "WHERE id = %s AND state = 'leased' AND lease_token = %s FOR UPDATE",
        (str(job.id), str(job.lease_token)),
    ).fetchone()
    if row is None:
        return None
    leased_until = row[3]
    if not isinstance(leased_until, datetime):
        raise RuntimeError("locked outbound job has no lease expiry")
    return (
        JobKind(str(row[0])),
        _as_uuid(row[1]) if row[1] is not None else None,
        _as_uuid(row[2]) if row[2] is not None else None,
        leased_until,
    )


def _lock_frozen_snapshot(
    conn: psycopg.Connection, *, run_id: uuid.UUID, email_id: uuid.UUID
) -> dict[str, Any] | None:
    """Lock and return only the existing immutable provider-ready evidence."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT snapshot.id AS snapshot_id, message.id AS email_id, message.run_id,
                   message.purpose, message.epoch, message.send_state,
                   snapshot.message_id, snapshot.from_addr, snapshot.to_addr,
                   snapshot.reply_to, snapshot.in_reply_to, snapshot.references_header,
                   snapshot.subject, snapshot.body_text, snapshot.reserved_at,
                   snapshot.reserved_at + interval '20 hours' AS not_after,
                   snapshot.reserved_at + interval '20 hours' > now() AS replay_window_open
              FROM outbound_email_snapshots AS snapshot
              JOIN email_messages AS message ON message.id = snapshot.email_id
             WHERE message.id = %s AND message.run_id = %s
               AND message.direction = 'outbound'
             FOR UPDATE OF snapshot, message
            """,
            (str(email_id), str(run_id)),
        )
        snapshot = cur.fetchone()
        if snapshot is None:
            return None
        cur.execute(
            """
            SELECT id, ordinal, filename, content
              FROM outbound_email_attachments
             WHERE snapshot_id = %s
             ORDER BY ordinal ASC
            """,
            (str(snapshot["snapshot_id"]),),
        )
        snapshot["attachments"] = cur.fetchall() or []
    return snapshot


def _lock_run_generation(
    conn: psycopg.Connection, run_id: uuid.UUID
) -> tuple[RunStatus, int, bool] | None:
    row = conn.execute(
        "SELECT status, reply_epoch, record_only FROM payroll_runs "
        "WHERE id = %s FOR UPDATE",
        (str(run_id),),
    ).fetchone()
    if row is None:
        return None
    return RunStatus(str(row[0])), int(row[1]), bool(row[2])


def _expected_run_status(purpose: object) -> RunStatus | None:
    if purpose == "confirmation":
        return RunStatus.APPROVED
    if purpose in {"clarification", "clarification_field_regression"}:
        return RunStatus.AWAITING_REPLY
    return None


def _active_handoff(
    conn: psycopg.Connection, run_id: uuid.UUID
) -> (
    tuple[
        uuid.UUID,
        uuid.UUID,
        uuid.UUID,
        uuid.UUID,
        uuid.UUID,
        int,
        uuid.UUID,
        datetime,
        datetime,
        datetime,
        bool,
    ]
    | None
):
    row = conn.execute(
        """
        SELECT id, run_id, email_id, snapshot_id, job_id, epoch, lease_token,
               owner_leased_until, authorized_at, not_after,
               owner_leased_until < now() AS owner_expired
          FROM outbound_provider_handoffs
         WHERE run_id = %s AND released_at IS NULL
         FOR UPDATE
        """,
        (str(run_id),),
    ).fetchone()
    if row is None:
        return None
    return (
        _as_uuid(row[0]),
        _as_uuid(row[1]),
        _as_uuid(row[2]),
        _as_uuid(row[3]),
        _as_uuid(row[4]),
        int(row[5]),
        _as_uuid(row[6]),
        row[7],
        row[8],
        row[9],
        bool(row[10]),
    )


def _authorization(
    *,
    handoff_id: uuid.UUID,
    job: Job,
    snapshot: dict[str, Any],
    not_after: datetime,
) -> ProviderHandoffAuthorization:
    if job.run_id is None or job.email_id is None:
        raise RuntimeError("provider handoff authorization lacks exact job context")
    return ProviderHandoffAuthorization(
        handoff_id=handoff_id,
        run_id=job.run_id,
        email_id=job.email_id,
        snapshot_id=_as_uuid(snapshot["snapshot_id"]),
        job_id=job.id,
        lease_token=job.lease_token,
        epoch=int(snapshot["epoch"]),
        snapshot=snapshot,
        not_after=not_after,
    )


def authorize_outbound_provider_handoff(
    job: Job, *, conn: psycopg.Connection | None = None
) -> ProviderHandoffOutcome:
    """Atomically grant provider authority for one exact leased SEND_OUTBOUND job.

    It never drafts or calls the provider.  The database's locked reservation derives
    the immutable deadline; caller scheduling time and wall-clock reads cannot extend it.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        locked_job = _locked_send_job(c, job)
        if locked_job is None:
            return ProviderHandoffActive("invalid_context")
        kind, stored_run_id, stored_email_id, leased_until = locked_job
        if (
            kind is not JobKind.SEND_OUTBOUND
            or job.kind is not JobKind.SEND_OUTBOUND
            or stored_run_id is None
            or job.run_id is None
            or stored_run_id != job.run_id
            or stored_email_id is None
            or job.email_id is None
            or stored_email_id != job.email_id
        ):
            return ProviderHandoffActive("invalid_context")

        snapshot = _lock_frozen_snapshot(c, run_id=stored_run_id, email_id=stored_email_id)
        if snapshot is None:
            return ProviderHandoffActive("invalid_context")
        if (
            _as_uuid(snapshot["email_id"]) != stored_email_id
            or _as_uuid(snapshot["run_id"]) != stored_run_id
            or snapshot["send_state"] != "reserved"
        ):
            return ProviderHandoffActive("invalid_context")

        run = _lock_run_generation(c, stored_run_id)
        if run is None:
            return ProviderHandoffActive("invalid_context")
        status, reply_epoch, record_only = run
        if record_only:
            return ProviderHandoffRecordOnly(stored_run_id)
        expected_status = _expected_run_status(snapshot["purpose"])
        if (
            expected_status is None
            or status is not expected_status
            or int(snapshot["epoch"]) != reply_epoch
        ):
            return ProviderHandoffActive("invalid_context")
        if not bool(snapshot["replay_window_open"]):
            return ProviderHandoffActive("replay_window_closed")
        not_after = snapshot["not_after"]
        if not isinstance(not_after, datetime):
            raise RuntimeError("locked outbound snapshot has no replay deadline")

        active = _active_handoff(c, stored_run_id)
        if active is None:
            created = c.execute(
                """
                INSERT INTO outbound_provider_handoffs (
                    run_id, email_id, snapshot_id, job_id, lease_token,
                    owner_leased_until, epoch, authorized_at, not_after
                )
                SELECT %s, %s, snapshot.id, %s, %s, %s, %s, now(),
                       snapshot.reserved_at + interval '20 hours'
                  FROM outbound_email_snapshots AS snapshot
                 WHERE snapshot.id = %s
                RETURNING id, authorized_at, not_after
                """,
                (
                    str(stored_run_id),
                    str(stored_email_id),
                    str(job.id),
                    str(job.lease_token),
                    leased_until,
                    reply_epoch,
                    str(snapshot["snapshot_id"]),
                ),
            ).fetchone()
            if created is None:
                raise RuntimeError("provider handoff insert did not return an id")
            return _authorization(
                handoff_id=_as_uuid(created[0]), job=job, snapshot=snapshot, not_after=created[2]
            )

        (
            handoff_id,
            handoff_run_id,
            handoff_email_id,
            handoff_snapshot_id,
            handoff_job_id,
            handoff_epoch,
            owner_token,
            _owner_until,
            _authorized_at,
            active_not_after,
            owner_expired,
        ) = active
        if (
            handoff_run_id != stored_run_id
            or handoff_email_id != stored_email_id
            or handoff_snapshot_id != _as_uuid(snapshot["snapshot_id"])
            or handoff_job_id != job.id
            or handoff_epoch != reply_epoch
        ):
            return ProviderHandoffActive("foreign_active_handoff", handoff_id)
        if owner_token == job.lease_token:
            return _authorization(
                handoff_id=handoff_id, job=job, snapshot=snapshot, not_after=active_not_after
            )
        if not owner_expired:
            return ProviderHandoffActive("active_handoff_unexpired", handoff_id)

        adopted = c.execute(
            """
            UPDATE outbound_provider_handoffs
               SET lease_token = %s, owner_leased_until = %s
             WHERE id = %s AND run_id = %s AND email_id = %s AND snapshot_id = %s
               AND job_id = %s AND epoch = %s AND lease_token = %s
               AND released_at IS NULL AND owner_leased_until < now()
            RETURNING id, not_after
            """,
            (
                str(job.lease_token),
                leased_until,
                str(handoff_id),
                str(stored_run_id),
                str(stored_email_id),
                str(snapshot["snapshot_id"]),
                str(job.id),
                reply_epoch,
                str(owner_token),
            ),
        ).fetchone()
        if adopted is None:
            return ProviderHandoffActive("active_handoff_unexpired", handoff_id)
        return _authorization(
            handoff_id=_as_uuid(adopted[0]), job=job, snapshot=snapshot, not_after=adopted[1]
        )


def adopt_outbound_provider_handoff(
    job: Job, *, conn: psycopg.Connection | None = None
) -> ProviderHandoffAuthorization | ProviderHandoffActive:
    """Request exact-owner adoption; record-only work remains a no-provider outcome."""
    outcome = authorize_outbound_provider_handoff(job, conn=conn)
    if isinstance(outcome, ProviderHandoffRecordOnly):
        return ProviderHandoffActive("invalid_context")
    return outcome


def _release_exact_handoff(
    authorization: ProviderHandoffAuthorization,
    *,
    reason: Literal["retry_scheduled", "finalized", "delivery_review"],
    conn: psycopg.Connection,
) -> bool:
    if reason not in _HANDOFF_RELEASE_REASONS:
        raise ValueError("unsupported outbound handoff release reason")
    released = conn.execute(
        """
        UPDATE outbound_provider_handoffs
           SET released_at = now(), release_reason = %s
         WHERE id = %s AND run_id = %s AND email_id = %s AND snapshot_id = %s
           AND job_id = %s AND epoch = %s AND lease_token = %s
           AND released_at IS NULL
        RETURNING id
        """,
        (
            reason,
            str(authorization.handoff_id),
            str(authorization.run_id),
            str(authorization.email_id),
            str(authorization.snapshot_id),
            str(authorization.job_id),
            authorization.epoch,
            str(authorization.lease_token),
        ),
    ).fetchone()
    return released is not None


def finalize_outbound_provider_handoff(
    authorization: ProviderHandoffAuthorization, *, conn: psycopg.Connection | None = None
) -> bool:
    """Release only the exact current owner after delivery settlement."""
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        return _release_exact_handoff(authorization, reason="finalized", conn=c)


def release_outbound_provider_handoff_for_retry(
    authorization: ProviderHandoffAuthorization, *, conn: psycopg.Connection | None = None
) -> bool:
    """Release the exact fence before its owner clears the matching job lease."""
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        return _release_exact_handoff(authorization, reason="retry_scheduled", conn=c)


def release_outbound_provider_handoff_to_delivery_review(
    authorization: ProviderHandoffAuthorization, *, conn: psycopg.Connection | None = None
) -> bool:
    """Explicit-review seam for expiry before provider entry; consumers wire it later."""
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        return _release_exact_handoff(authorization, reason="delivery_review", conn=c)


def resolve_outbound_provider_handoff_for_delivery_review(
    run_id: uuid.UUID,
    email_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    *,
    resolution: Literal["finalized", "delivery_review"],
    conn: psycopg.Connection | None = None,
) -> bool:
    """Release only the active handoff owned by one explicit delivery review.

    D-09 and D-11 are deliberate human overrides of uncertain provider delivery;
    unlike worker settlement they do not possess a leased-job authorization.  They
    still cannot release an arbitrary active row: the review's frozen email and
    snapshot must match the sole active handoff for the locked run.  No active row
    is also safe -- settlement may already have released it before the operator
    acts -- but a different active generation fails closed.
    """
    if resolution not in {"finalized", "delivery_review"}:
        raise ValueError("unsupported delivery-review handoff resolution")
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        active = c.execute(
            """
            SELECT id, email_id, snapshot_id FROM outbound_provider_handoffs
             WHERE run_id = %s AND released_at IS NULL
             FOR UPDATE
            """,
            (str(run_id),),
        ).fetchone()
        if active is None:
            return True
        active_id, active_email_id, active_snapshot_id = active
        if (
            _as_uuid(active_email_id) != email_id
            or _as_uuid(active_snapshot_id) != snapshot_id
        ):
            return False
        released = c.execute(
            """
            UPDATE outbound_provider_handoffs
               SET released_at = now(), release_reason = %s
             WHERE id = %s AND run_id = %s AND email_id = %s AND snapshot_id = %s
               AND released_at IS NULL
            RETURNING id
            """,
            (
                resolution,
                str(active_id),
                str(run_id),
                str(email_id),
                str(snapshot_id),
            ),
        ).fetchone()
        return released is not None


def assert_no_active_outbound_provider_handoff(
    run_id: uuid.UUID, *, conn: psycopg.Connection | None = None
) -> None:
    """Reject an epoch-changing operation while an external-call fence is active."""
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        active = c.execute(
            """
            SELECT id FROM outbound_provider_handoffs
             WHERE run_id = %s AND released_at IS NULL
             FOR UPDATE
            """,
            (str(run_id),),
        ).fetchone()
        if active is not None:
            raise ActiveOutboundProviderHandoffError(run_id)
