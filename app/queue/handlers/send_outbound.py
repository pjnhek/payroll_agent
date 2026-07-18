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
    # Keep this consumer structurally coupled to the bounded authority result,
    # rather than importing the repository's concrete classes into queue tier.
    # The authorizer closes the 20-hour reservation window before any handoff
    # exists. Preserve that fixed no-provider reason so settlement can enter
    # purpose-aware delivery review rather than retiring the exact lease.
    if (
        getattr(authorization, "reason", None) == "replay_window_closed"
        and getattr(authorization, "snapshot", None) is None
    ):
        return PipelineResult(
            outcome=PipelineOutcome.TERMINAL,
            stage=PipelineStage.DELIVERY,
            reason=PipelineReason.DELIVERY_AUTHORIZATION_EXPIRED,
        )
    # Only record-only authority has the exact run id without a bounded reason.
    if (
        getattr(authorization, "run_id", None) == job.run_id
        and getattr(authorization, "reason", None) is None
        and getattr(authorization, "snapshot", None) is None
    ):
        return PipelineResult(
            outcome=PipelineOutcome.OK,
            stage=PipelineStage.DELIVERY,
            reason=PipelineReason.DELIVERY_RECORD_ONLY,
        )
    snapshot = getattr(authorization, "snapshot", None)
    not_after = getattr(authorization, "not_after", None)
    if snapshot is None or not isinstance(not_after, datetime):
        return _bounded_noop()

    return normalize_pipeline_result(
        gateway.send_reserved_outbound_snapshot(
            snapshot,
            not_after=not_after,
            clock=clock,
            budget=DELIVERY_SEND_BUDGET,
        )
    )
