"""Snapshot-only durable consumer for one frozen outbound email."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.db import repo
from app.email import gateway
from app.models.job import Job, JobKind
from app.models.status import RunStatus
from app.pipeline.result import (
    PipelineOutcome,
    PipelineResult,
    PipelineStage,
    delivery_replay_allowed,
    normalize_pipeline_result,
)

_CLARIFICATION_PURPOSES = {"clarification", "clarification_field_regression"}
_OUTBOUND_PURPOSES = {"confirmation", *_CLARIFICATION_PURPOSES}


def _bounded_noop() -> PipelineResult:
    """Return an intentional no-op without exposing persisted email fields."""
    return PipelineResult(outcome=PipelineOutcome.OK)


def _snapshot_matches_job(snapshot: dict[str, Any], job: Job) -> bool:
    """Validate immutable identifier and slot facts before a provider call."""
    run_id = job.run_id
    email_id = job.email_id
    if run_id is None or email_id is None:
        return False
    if snapshot.get("run_id") != run_id or snapshot.get("email_id") != email_id:
        return False
    purpose = snapshot.get("purpose")
    if purpose not in _OUTBOUND_PURPOSES:
        return False
    for field in ("round", "epoch"):
        value = snapshot.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return False
    return True


def _authorized_status(snapshot: dict[str, Any]) -> RunStatus:
    purpose = snapshot["purpose"]
    return (
        RunStatus.APPROVED
        if purpose == "confirmation"
        else RunStatus.AWAITING_REPLY
    )


def handle_send_outbound(job: Job) -> PipelineResult:
    """Send exactly one valid frozen envelope, never compose fresh content."""
    if job.kind is not JobKind.SEND_OUTBOUND:
        raise ValueError(f"handle_send_outbound: job {job.id} has kind {job.kind!r}")
    run_id = job.run_id
    email_id = job.email_id
    if run_id is None or email_id is None:
        raise ValueError(f"handle_send_outbound: job {job.id} lacks frozen context")
    if job.operator_resolution_id is not None or job.event_id is not None:
        raise ValueError(f"handle_send_outbound: job {job.id} has mixed identifier context")

    snapshot = repo.load_outbound_snapshot(run_id, email_id)
    if snapshot is None or not _snapshot_matches_job(snapshot, job):
        return _bounded_noop()

    run = repo.load_run(run_id)
    if run is None or run.get("status") != _authorized_status(snapshot).value:
        return _bounded_noop()

    reserved_at = snapshot.get("reserved_at")
    if not isinstance(reserved_at, datetime) or reserved_at.tzinfo is None:
        return _bounded_noop()
    if not delivery_replay_allowed(reserved_at, datetime.now(UTC)):
        return PipelineResult(stage=PipelineStage.DELIVERY)

    return normalize_pipeline_result(gateway.send_reserved_outbound_snapshot(snapshot))
