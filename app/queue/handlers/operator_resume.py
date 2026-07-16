"""Durable operator-resume handler over one immutable complete mapping."""
from __future__ import annotations

import logging
import uuid

from pydantic import ValidationError

from app.db import repo
from app.models.contracts import Decision
from app.models.job import Job
from app.models.status import RunStatus
from app.pipeline import orchestrator
from app.pipeline.result import (
    PipelineReason,
    PipelineResult,
    PipelineStage,
    normalize_pipeline_result,
)

logger = logging.getLogger("payroll_agent.queue")


def _invalid_context(job: Job) -> PipelineResult:
    """Return a bounded result without logging submitted names or employee ids."""
    logger.warning(
        "operator_resume invalid durable context: run_id=%s job_id=%s "
        "resolution_id=%s code=%s",
        job.run_id,
        job.id,
        job.operator_resolution_id,
        PipelineReason.INVALID_OPERATOR_OVERRIDE_CONTEXT.value,
    )
    return PipelineResult(
        stage=PipelineStage.LOAD,
        reason=PipelineReason.INVALID_OPERATOR_OVERRIDE_CONTEXT,
    )


def _validated_mapping(
    run_id: uuid.UUID,
    operator_resolution_id: uuid.UUID,
) -> dict[str, str] | None:
    """Load and validate the complete persisted money-moving authority."""
    try:
        run = repo.load_run(run_id)
        if run is None:
            return None
        decision = Decision.model_validate(run.get("decision"))
        unresolved = decision.unresolved_names
        if not unresolved or len(unresolved) != len(set(unresolved)):
            return None

        overrides = repo.load_operator_resume_resolution(
            run_id,
            operator_resolution_id,
        )
        if set(overrides) != set(unresolved):
            return None

        roster = repo.load_roster_for_business(run["business_id"])
        roster_ids = {str(employee.id) for employee in roster.employees}
        if any(employee_id not in roster_ids for employee_id in overrides.values()):
            return None
        return overrides
    except (KeyError, TypeError, ValueError, ValidationError):
        return None


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

    overrides = _validated_mapping(run_id, operator_resolution_id)
    if overrides is None:
        return _invalid_context(job)

    if job.attempts > 1:
        rewound = repo.rewind_for_reclaim(run_id)
        logger.info(
            "operator_resume reclaim: run_id=%s job_id=%s resolution_id=%s "
            "attempts=%s rewound=%s",
            run_id,
            job.id,
            operator_resolution_id,
            job.attempts,
            rewound,
        )

    return normalize_pipeline_result(
        orchestrator.resume_pipeline(
            run_id,
            None,
            from_status=RunStatus.RECEIVED,
            overrides=overrides,
        )
    )
