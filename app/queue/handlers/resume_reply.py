"""Lossless retry handler for one persisted clarification reply."""
from __future__ import annotations

import logging
import uuid

from pydantic import ValidationError

from app.db import repo
from app.models.job import Job
from app.models.status import RunStatus
from app.pipeline import orchestrator
from app.pipeline.result import (
    PipelineOutcome,
    PipelineResult,
    normalize_pipeline_result,
)
from app.routes.pipeline_glue import reply_sender_ok, row_to_inbound

logger = logging.getLogger("payroll_agent.queue")


def _bounded_noop() -> PipelineResult:
    """Return an intentional no-op without logging attacker-controlled context."""
    return PipelineResult(outcome=PipelineOutcome.OK)


def _canonical_row_run_id(row: dict[str, object]) -> uuid.UUID | None:
    """Return the persisted row owner as a UUID, failing closed on bad context."""
    value = row.get("run_id")
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


def handle_resume_reply(job: Job) -> PipelineResult:
    """Reload ``job.email_id`` and resume from the authoritative RECEIVED seam."""
    run_id = job.run_id
    if run_id is None:
        raise ValueError(f"handle_resume_reply: job {job.id} has no run_id")
    email_id = job.email_id
    if email_id is None:
        raise ValueError(f"handle_resume_reply: job {job.id} has no email_id")

    row = repo.get_inbound_email_by_id(email_id)
    if row is None:
        return _bounded_noop()
    if _canonical_row_run_id(row) != run_id:
        return _bounded_noop()

    run = repo.load_run(run_id)
    if run is None or not reply_sender_ok(row, run):
        return _bounded_noop()

    stored_status = run.get("status")
    if stored_status == RunStatus.AWAITING_REPLY.value:
        if not repo.claim_status(
            run_id,
            RunStatus.AWAITING_REPLY,
            RunStatus.RECEIVED,
        ):
            return _bounded_noop()
    elif stored_status == RunStatus.RECEIVED.value and job.attempts > 1:
        # A classified retry may already have atomically rewound the run and job.
        pass
    elif (
        stored_status
        in {
            RunStatus.EXTRACTING.value,
            RunStatus.COMPUTED.value,
            RunStatus.SENT.value,
        }
        and job.attempts > 1
    ):
        if not repo.rewind_for_reclaim(run_id):
            return _bounded_noop()
    else:
        return _bounded_noop()

    try:
        inbound = row_to_inbound(row)
    except (KeyError, TypeError, ValidationError):
        return _bounded_noop()

    if job.attempts > 1:
        logger.info("resume_reply reclaimed durable work")

    return normalize_pipeline_result(
        orchestrator.resume_pipeline(
            run_id,
            inbound,
            from_status=RunStatus.RECEIVED,
        )
    )
