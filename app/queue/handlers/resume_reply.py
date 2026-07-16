"""Lossless retry handler for one persisted clarification reply."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import cast

from pydantic import ValidationError

from app.db import repo
from app.models.job import Job
from app.models.status import RunStatus
from app.pipeline import orchestrator
from app.pipeline.result import PipelineReason, PipelineResult, PipelineStage
from app.routes.pipeline_glue import row_to_inbound

logger = logging.getLogger("payroll_agent.queue")


def _invalid_context(job: Job) -> PipelineResult:
    """Return a bounded result and log correlation identifiers only."""
    logger.warning(
        "resume_reply invalid durable context: run_id=%s job_id=%s email_id=%s "
        "code=%s",
        job.run_id,
        job.id,
        job.email_id,
        PipelineReason.INVALID_OPERATOR_OVERRIDE_CONTEXT.value,
    )
    return PipelineResult(
        stage=PipelineStage.LOAD,
        reason=PipelineReason.INVALID_OPERATOR_OVERRIDE_CONTEXT,
    )


def handle_resume_reply(job: Job) -> PipelineResult | None:
    """Reload ``job.email_id`` and resume from the authoritative RECEIVED seam."""
    run_id = job.run_id
    if run_id is None:
        raise ValueError(f"handle_resume_reply: job {job.id} has no run_id")
    email_id = job.email_id
    if email_id is None:
        raise ValueError(f"handle_resume_reply: job {job.id} has no email_id")

    row = repo.get_inbound_email_by_id(email_id)
    if row is None:
        return _invalid_context(job)
    try:
        inbound = row_to_inbound(row)
    except (KeyError, TypeError, ValidationError):
        return _invalid_context(job)

    if job.attempts > 1:
        rewound = repo.rewind_for_reclaim(run_id)
        logger.info(
            "resume_reply reclaim: run_id=%s job_id=%s attempts=%s rewound=%s",
            run_id,
            job.id,
            job.attempts,
            rewound,
        )

    resume = cast(
        Callable[..., PipelineResult | None],
        orchestrator.resume_pipeline,
    )
    return resume(
        run_id,
        inbound,
        from_status=RunStatus.RECEIVED,
    )
