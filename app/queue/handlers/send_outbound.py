"""Identifier-only consumer for a durably authorized frozen outbound email."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from app.db import repo
from app.email import gateway
from app.models.job import Job, JobKind
from app.pipeline.result import (
    DELIVERY_SEND_BUDGET,
    PipelineOutcome,
    PipelineReason,
    PipelineResult,
    PipelineStage,
    normalize_pipeline_result,
)


def _utc_now() -> datetime:
    """Return UTC through a named seam used by the provider boundary."""
    return datetime.now(UTC)


def _bounded_noop() -> PipelineResult:
    """Return an intentional no-op without exposing persisted email fields."""
    return PipelineResult(outcome=PipelineOutcome.OK)


def handle_send_outbound(
    job: Job, *, clock: Callable[[], datetime] = _utc_now
) -> PipelineResult:
    """Send only the exact frozen envelope granted by durable handoff authority."""
    if job.kind is not JobKind.SEND_OUTBOUND:
        raise ValueError(f"handle_send_outbound: job {job.id} has kind {job.kind!r}")
    if job.run_id is None or job.email_id is None:
        raise ValueError(f"handle_send_outbound: job {job.id} lacks frozen context")
    if job.operator_resolution_id is not None or job.event_id is not None:
        raise ValueError(f"handle_send_outbound: job {job.id} has mixed identifier context")

    authorization = repo.authorize_outbound_provider_handoff(job)
    if isinstance(authorization, repo.ProviderHandoffRecordOnly):
        return PipelineResult(
            outcome=PipelineOutcome.OK,
            stage=PipelineStage.DELIVERY,
            reason=PipelineReason.DELIVERY_RECORD_ONLY,
        )
    if not isinstance(authorization, repo.ProviderHandoffAuthorization):
        return _bounded_noop()

    return normalize_pipeline_result(
        gateway.send_reserved_outbound_snapshot(
            authorization.snapshot,
            not_after=authorization.not_after,
            clock=clock,
            budget=DELIVERY_SEND_BUDGET,
        )
    )
