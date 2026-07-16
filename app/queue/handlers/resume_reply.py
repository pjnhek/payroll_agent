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
    PipelineReason,
    PipelineResult,
    PipelineStage,
    normalize_pipeline_result,
)
from app.routes.pipeline_glue import row_to_inbound

logger = logging.getLogger("payroll_agent.queue")


def _invalid_context() -> PipelineResult:
    """Return and log only the bounded invalid-context classification."""
    logger.warning(
        "resume_reply invalid durable context: code=%s",
        PipelineReason.INVALID_OPERATOR_OVERRIDE_CONTEXT.value,
    )
    return PipelineResult(
        stage=PipelineStage.LOAD,
        reason=PipelineReason.INVALID_OPERATOR_OVERRIDE_CONTEXT,
    )


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
        return _invalid_context()
    if _canonical_row_run_id(row) != run_id:
        return _invalid_context()
    try:
        inbound = row_to_inbound(row)
    except (KeyError, TypeError, ValidationError):
        return _invalid_context()

    if job.attempts > 1:
        rewound = repo.rewind_for_reclaim(run_id)
        logger.info(
            "resume_reply reclaim: run_id=%s job_id=%s attempts=%s rewound=%s",
            run_id,
            job.id,
            job.attempts,
            rewound,
        )

    return normalize_pipeline_result(
        orchestrator.resume_pipeline(
            run_id,
            inbound,
            from_status=RunStatus.RECEIVED,
        )
    )
