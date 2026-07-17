"""Durable operator-resume handler over one immutable complete mapping."""
from __future__ import annotations

import logging

from app.db import repo
from app.models.job import Job
from app.models.status import RunStatus
from app.pipeline import orchestrator
from app.pipeline.result import (
    PipelineOutcome,
    PipelineReason,
    PipelineResult,
    PipelineStage,
    normalize_pipeline_result,
)

logger = logging.getLogger("payroll_agent.queue")


def _invalid_context() -> PipelineResult:
    """Return a bounded result without logging submitted names or employee ids."""
    logger.warning(
        "operator_resume invalid durable context code=%s",
        PipelineReason.INVALID_OPERATOR_OVERRIDE_CONTEXT.value,
    )
    return PipelineResult(
        stage=PipelineStage.LOAD,
        reason=PipelineReason.INVALID_OPERATOR_OVERRIDE_CONTEXT,
    )


def _bounded_noop() -> PipelineResult:
    """A successful no-op with no attacker-controlled diagnostic content."""
    return PipelineResult(outcome=PipelineOutcome.OK)


def handle_operator_resume(job: Job) -> PipelineResult:
    """Reload, validate, and replay one immutable operator-resolution generation."""
    run_id = job.run_id
    if run_id is None:
        raise ValueError(f"handle_operator_resume: job {job.id} has no run_id")
    operator_resolution_id = job.operator_resolution_id
    if operator_resolution_id is None:
        raise ValueError(
            f"handle_operator_resume: job {job.id} has no operator_resolution_id"
        )

    try:
        preparation = repo.prepare_authoritative_operator_resume(
            run_id, operator_resolution_id
        )
    except (KeyError, TypeError, ValueError):
        return _invalid_context()

    # Worker order can never choose authority. A superseded generation is retained
    # and drained successfully, but it cannot load money-moving data, claim run state,
    # project aliases, or invoke orchestration.
    if not preparation.authoritative:
        logger.info("operator_resume superseded generation drained")
        return _bounded_noop()

    try:
        overrides = repo.load_operator_resume_resolution(
            run_id, operator_resolution_id
        )
        run = repo.load_run(run_id)
    except (KeyError, TypeError, ValueError):
        return _invalid_context()
    if run is None:
        return _invalid_context()

    status = run.get("status")
    if status == RunStatus.NEEDS_OPERATOR.value:
        if not repo.claim_status(
            run_id, RunStatus.NEEDS_OPERATOR, RunStatus.RECEIVED
        ):
            return _bounded_noop()
    elif job.attempts > 1 and status == RunStatus.RECEIVED.value:
        # The prior lease committed the claim but died before orchestration.
        pass
    elif job.attempts > 1 and status in {
        RunStatus.EXTRACTING.value,
        RunStatus.COMPUTED.value,
        RunStatus.SENT.value,
    }:
        if not repo.rewind_for_reclaim(run_id):
            return _bounded_noop()
        logger.info("operator_resume reclaimed durable work")
    else:
        return _bounded_noop()

    return normalize_pipeline_result(
        orchestrator.resume_pipeline(
            run_id,
            None,
            from_status=RunStatus.RECEIVED,
            overrides=overrides,
        )
    )
