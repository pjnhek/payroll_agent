"""Authenticated durable receipt boundary for inbound email webhooks.

The public request owns transport work only: bounded streaming, exact-byte
signature verification, and one off-loop transaction that persists the event
plus its identifier-only ingest job. Provider fetches and payroll work begin
later in the durable ingest worker.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.db import repo
from app.email import gateway
from app.models.job import JobKind
from app.queue import wake

logger = logging.getLogger("payroll_agent.webhook")

router = APIRouter()

_MAX_INBOUND_BYTES = 256 * 1024


class _InvalidInboundEnvelope(ValueError):
    """Authenticated bytes do not contain the required transport identity."""


@dataclass(frozen=True)
class ReceiptResult:
    """Bounded result returned across the worker-thread boundary."""

    event_id: uuid.UUID
    inserted: bool


async def _read_bounded_body(request: Request) -> bytes:
    """Stream at most the configured transport-envelope cap into memory."""
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > _MAX_INBOUND_BYTES:
            raise _InvalidInboundEnvelope("request_too_large")
        raw.extend(chunk)
    return bytes(raw)


def _validated_payload(raw_body: bytes, allow_unsigned_fixture: bool) -> dict[str, Any]:
    """Parse only the minimal authenticated envelope needed by delayed ingest.

    Signed provider traffic must carry ``data.email_id``. Explicitly enabled
    fixture traffic may instead carry the canonical fixture's ``message_id``;
    its complete domain validation still belongs to the delayed ingest worker.
    """
    try:
        decoded = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _InvalidInboundEnvelope("invalid_json") from exc
    if not isinstance(decoded, dict):
        raise _InvalidInboundEnvelope("invalid_object")

    data = decoded.get("data")
    provider_id = data.get("email_id") if isinstance(data, dict) else None
    has_provider_id = isinstance(provider_id, str) and bool(provider_id.strip())
    fixture_message_id = decoded.get("message_id")
    has_fixture_id = (
        allow_unsigned_fixture
        and isinstance(fixture_message_id, str)
        and bool(fixture_message_id.strip())
    )
    if not has_provider_id and not has_fixture_id:
        raise _InvalidInboundEnvelope("missing_transport_identifier")
    return decoded


def _persist_verified_receipt_sync(
    raw_body: bytes,
    external_event_id: str,
    allow_unsigned_fixture: bool,
) -> ReceiptResult:
    """Commit one verified event and its ingest job in one blocking transaction."""
    payload = _validated_payload(raw_body, allow_unsigned_fixture)

    with repo.get_connection() as conn, conn.transaction():
        event_id, inserted = repo.insert_or_get_inbound_event(
            external_event_id=external_event_id,
            payload=payload,
            conn=conn,
        )
        if inserted:
            job_id = repo.enqueue_job(
                kind=JobKind.INGEST,
                dedup_key=f"ingest:{event_id}",
                event_id=event_id,
                conn=conn,
            )
            if job_id is None:
                raise RuntimeError("new inbound event has no ingest job")

    return ReceiptResult(event_id=event_id, inserted=inserted)


@router.post("/webhook/inbound")
async def inbound(request: Request) -> JSONResponse:
    """Authenticate and durably accept one bounded transport event."""
    try:
        raw_body = await _read_bounded_body(request)
    except _InvalidInboundEnvelope:
        return JSONResponse(
            status_code=413,
            content={"error": "request too large"},
        )

    settings = get_settings()
    is_signed = all(
        header in request.headers
        for header in ("svix-id", "svix-timestamp", "svix-signature")
    )

    if is_signed:
        try:
            gateway.verify(
                raw_body,
                dict(request.headers),
                settings.webhook_signing_secret,
            )
        except Exception as exc:  # noqa: BLE001 - public authentication boundary
            logger.warning(
                "webhook signature verification failed: %s", type(exc).__name__
            )
            return JSONResponse(
                status_code=400,
                content={"error": "invalid signature"},
            )
        external_event_id = request.headers["svix-id"]
        fixture_payload = False
    elif settings.allow_unsigned_fixtures:
        external_event_id = f"sha256:{hashlib.sha256(raw_body).hexdigest()}"
        fixture_payload = True
    else:
        logger.warning("unsigned webhook rejected")
        return JSONResponse(
            status_code=400,
            content={"error": "unsigned webhook not allowed"},
        )

    try:
        result = await run_in_threadpool(
            _persist_verified_receipt_sync,
            raw_body,
            external_event_id,
            fixture_payload,
        )
    except _InvalidInboundEnvelope:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid inbound envelope"},
        )
    except Exception as exc:  # noqa: BLE001 - durable boundary must invite retry
        logger.error("durable webhook receipt failed: %s", type(exc).__name__)
        return JSONResponse(
            status_code=503,
            content={"error": "temporarily unavailable"},
        )

    if result.inserted:
        wake.wake()
    return JSONResponse(
        status_code=200,
        content={
            "status": "accepted" if result.inserted else "duplicate",
            "event_id": str(result.event_id),
        },
    )
