"""Worker-facing delayed business ingest for persisted transport receipts.

The HTTP receipt path persists only a verified bounded envelope.  This module
later fetches/parses the email and moves the existing DATA-02 five-outcome
transaction intact, with one deliberate durability extension: any downstream
queue work owed by a new run or authorized reply is inserted in that same
transaction.
"""
from __future__ import annotations

import enum
import logging
import uuid
from typing import Any

from app.db import repo
from app.email import gateway
from app.email.clean import clean_body
from app.models.contracts import InboundEmail
from app.models.job import JobKind
from app.models.status import RunStatus
from app.pipeline.result import PipelineOutcome, PipelineResult
from app.routes import pipeline_glue

logger = logging.getLogger("payroll_agent.ingest")


class IngestOutcome(enum.StrEnum):
    """Bounded business classifications emitted by delayed ingest."""

    DUPLICATE = "duplicate"
    REPLY_CANDIDATE = "reply_candidate"
    LATE_REPLY = "late_reply"
    UNKNOWN_SENDER = "unknown_sender"
    NEW_RUN = "new_run"


def _authorized_reply_job(
    *,
    reply_row: dict[str, Any],
    run_id: uuid.UUID,
    email_id: uuid.UUID,
    conn: Any,
) -> bool:
    """Enqueue one same-run, sender-authorized reply job, or intentionally no-op."""
    row_run_id = reply_row.get("run_id")
    if row_run_id is None or str(row_run_id) != str(run_id):
        return False
    run = repo.load_run(run_id, conn=conn)
    if run is None or run.get("status") != RunStatus.AWAITING_REPLY.value:
        return False
    if not pipeline_glue.reply_sender_ok(reply_row, run):
        return False
    repo.enqueue_job(
        kind=JobKind.RESUME_REPLY,
        dedup_key=f"resume_reply:{run_id}:{email_id}",
        run_id=run_id,
        email_id=email_id,
        conn=conn,
    )
    return True


def _ingest_email(email: InboundEmail, cleaned: str) -> IngestOutcome:
    """Commit exactly one DATA-02 outcome and all downstream work it owes."""
    with repo.get_connection() as conn, conn.transaction():
        email_id, inserted = repo.insert_inbound_email(
            message_id=email.message_id,
            in_reply_to=email.in_reply_to,
            references_header=email.references_header,
            subject=email.subject,
            from_addr=email.from_addr,
            to_addr=email.to_addr,
            body_text=cleaned,
            run_id=None,
            conn=conn,
        )

        if not inserted:
            persisted = repo.get_inbound_by_message_id(email.message_id, conn=conn)
            if (
                persisted is not None
                and persisted.get("consumed_round") is None
                and persisted.get("run_id") is not None
            ):
                persisted_email_id = uuid.UUID(str(persisted["id"]))
                persisted_run_id = uuid.UUID(str(persisted["run_id"]))
                _authorized_reply_job(
                    reply_row=persisted,
                    run_id=persisted_run_id,
                    email_id=persisted_email_id,
                    conn=conn,
                )
            return IngestOutcome.DUPLICATE

        assert email_id is not None
        if email.in_reply_to or email.references_header:
            reply_run_id = repo.find_awaiting_reply_for_header(
                in_reply_to=email.in_reply_to,
                references_header=email.references_header,
                conn=conn,
            )
            if reply_run_id is not None:
                repo.link_email_to_run(email_id, reply_run_id, conn=conn)
                _authorized_reply_job(
                    reply_row={
                        "id": email_id,
                        "run_id": reply_run_id,
                        "from_addr": email.from_addr,
                    },
                    run_id=reply_run_id,
                    email_id=email_id,
                    conn=conn,
                )
                return IngestOutcome.REPLY_CANDIDATE

            late_run_id = repo.find_any_run_for_header(
                in_reply_to=email.in_reply_to,
                references_header=email.references_header,
                conn=conn,
            )
            if late_run_id is not None:
                repo.link_email_to_run(email_id, late_run_id, conn=conn)
                return IngestOutcome.LATE_REPLY

        business_id = repo.find_business_by_sender(email.from_addr, conn=conn)
        if business_id is None:
            return IngestOutcome.UNKNOWN_SENDER

        run_id = repo.create_run(
            business_id=business_id,
            source_email_id=email_id,
            conn=conn,
        )
        repo.enqueue_job(
            kind=JobKind.RUN_PIPELINE,
            dedup_key=f"run_pipeline:{run_id}:0",
            run_id=run_id,
            conn=conn,
        )
        return IngestOutcome.NEW_RUN


def process_inbound_event(event_id: uuid.UUID) -> PipelineResult:
    """Fetch and transactionally ingest one persisted transport event.

    Provider and database failures propagate to the queue's infrastructure
    settlement policy.  Every normal business classification is a successful
    transport outcome, including duplicate, late reply, and unknown sender.
    """
    event = repo.load_inbound_event(event_id)
    if event is None:
        raise RuntimeError("durable inbound event unavailable")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("durable inbound event payload unavailable")

    email = gateway.parse_inbound(payload)
    cleaned = clean_body(email.body_text)
    outcome = _ingest_email(email, cleaned)
    logger.info("event_id=%s ingest_outcome=%s", event_id, outcome.value)
    return PipelineResult(outcome=PipelineOutcome.OK)
