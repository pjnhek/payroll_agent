"""Identifier-only queue consumer for one persisted inbound receipt."""
from __future__ import annotations

from app import ingest as ingest_service
from app.models.job import Job, JobKind
from app.pipeline.result import PipelineResult, normalize_pipeline_result


def handle_ingest(job: Job) -> PipelineResult:
    """Forward one receipt identifier into the delayed ingest service."""
    if job.kind is not JobKind.INGEST:
        raise ValueError(f"handle_ingest: job {job.id} has kind {job.kind!r}")
    event_id = job.event_id
    if event_id is None:
        raise ValueError(f"handle_ingest: job {job.id} has no event_id")
    if (
        job.run_id is not None
        or job.email_id is not None
        or job.operator_resolution_id is not None
    ):
        raise ValueError(f"handle_ingest: job {job.id} has mixed identifier context")
    return normalize_pipeline_result(ingest_service.process_inbound_event(event_id))
