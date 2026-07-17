"""The fail-closed guard against re-sending a client email whose outcome is unknown.

Both app/pipeline/clarification.py and app/pipeline/delivery.py call
`assert_no_unconfirmed_send` immediately after their own existing proven-sent
idempotency guard and strictly before any drafting, suggestion, or provider call. A
duplicated money-facing send is a DRY violation this project treats as a defect, so the
check lives in its own module once, rather than being copied into each call site.

The rule this module enforces: an outbound row for the current run's send slot that is
neither absent nor proven 'sent' means the provider MAY already hold the message. The
pipeline does not send again — it raises, and the caller's existing error boundary
routes the run to a status the automatic reclaim path can never walk it back out of.
Only a human, acting deliberately, can re-open that send slot.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import psycopg

from app.db import repo

logger = logging.getLogger("payroll_agent.orchestrator")


@dataclass(frozen=True)
class OutboundReplayPolicy:
    """Describe whether a logical send slot is new or has frozen work to replay."""

    email_id: uuid.UUID | None

    @property
    def has_existing_snapshot(self) -> bool:
        """Return whether the caller must load stored provider-visible data."""
        return self.email_id is not None


class UnconfirmedSendError(RuntimeError):
    """A previous send attempt for this run reserved an outbound row and never
    confirmed delivery — the message may already have reached the client, so the
    system refused to send it again.

    This class's NAME is what the pipeline's error-recording path persists as the run's
    error reason and renders to the operator, so it has to read as an instruction on its
    own: inspect the outbound row this run's most recent send reserved and, if a re-send
    is genuinely wanted, use the run's retrigger action — which opens a new send slot
    and thereby authorises a new send.
    """


def outbound_replay_policy(
    run_id: uuid.UUID,
    *,
    purpose: str,
    round: int = 0,
    conn: psycopg.Connection | None = None,
) -> OutboundReplayPolicy:
    """Return the frozen slot that durable work may replay, if one exists.

    The lookup remains purpose, round, and epoch scoped.  This function only decides
    whether a producer must use an existing immutable snapshot; the queued handler
    remains responsible for the bounded provider replay decision.
    """
    row = repo.get_unconfirmed_outbound(run_id, purpose=purpose, round=round, conn=conn)
    if row is None:
        return OutboundReplayPolicy(email_id=None)
    email_id = row.get("email_id")
    try:
        return OutboundReplayPolicy(email_id=uuid.UUID(str(email_id)))
    except (TypeError, ValueError) as exc:
        raise UnconfirmedSendError(
            f"run {run_id}: an unconfirmed {purpose!r} send exists at round {round} "
            "without an immutable snapshot id; refusing to send again"
        ) from exc


def assert_no_unconfirmed_send(
    run_id: uuid.UUID,
    *,
    purpose: str,
    round: int = 0,
    conn: psycopg.Connection | None = None,
) -> None:
    """Raise UnconfirmedSendError when this run's current send slot already holds an
    unconfirmed (reserved or failed) outbound row; otherwise return None and let the
    caller's send proceed.

    Reads through `repo.get_unconfirmed_outbound` as a module attribute on `repo`
    (never imported by name), so a caller can substitute the whole data layer without
    this module noticing.

    Logs at WARNING, before raising, exactly the identifiers an operator needs to act:
    run_id, purpose, round, the offending message_id, and its send_state. Neither the
    log line nor the exception message interpolates anything beyond those identifiers —
    never a subject line, body text, or an employee name. The pipeline's own
    error-recording path persists only the exception's type name as the reason, but this
    message must be safe to read on its own terms, not merely because something
    downstream happens to scrub it.
    """
    row = repo.get_unconfirmed_outbound(run_id, purpose=purpose, round=round, conn=conn)
    if row is None:
        return
    logger.warning(
        "run %s: unconfirmed outbound send blocks a resend "
        "(purpose=%r round=%d message_id=%s send_state=%s) — escalating instead of "
        "sending again",
        run_id,
        purpose,
        round,
        row.get("message_id"),
        row.get("send_state"),
    )
    raise UnconfirmedSendError(
        f"run {run_id}: an unconfirmed {purpose!r} send exists at round {round} "
        f"(message_id={row.get('message_id')}, send_state={row.get('send_state')}); "
        "refusing to send again"
    )
