"""The Resend gateway: inbound parsing and immutable outbound snapshot delivery."""
from __future__ import annotations

import base64
import json
import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import Any, Protocol, cast

import resend

from app.config import get_settings
from app.models.contracts import InboundEmail
from app.pipeline.result import (
    PipelineOutcome,
    PipelineResult,
    PipelineStage,
    classify_pipeline_exception,
)

logger = logging.getLogger(__name__)


class _ReceivedEmailLike(Protocol):
    """Runtime attribute shape returned by Resend's receiving endpoint."""

    headers: Mapping[str, str]
    message_id: str | None
    text: str | None


def _is_resend_envelope(data: dict[str, Any]) -> bool:
    """Return whether ``data`` has the Resend inbound webhook shape."""
    return isinstance(data.get("data"), dict) and "email_id" in data["data"]


def verify(raw_body: bytes, headers: dict[str, str], signing_secret: str) -> None:
    """Verify a Resend webhook payload using svix HMAC-SHA256."""
    resend.Webhooks.verify(
        {
            "payload": raw_body.decode("utf-8"),
            "headers": {
                "id": headers.get("svix-id", ""),
                "timestamp": headers.get("svix-timestamp", ""),
                "signature": headers.get("svix-signature", ""),
            },
            "webhook_secret": signing_secret,
        }
    )


def parse_inbound(raw: dict[str, Any] | str | bytes) -> InboundEmail:
    """Normalize either a Resend envelope or a canonical fixture payload."""
    data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    if _is_resend_envelope(data):
        return _parse_resend_envelope(data)
    return InboundEmail.model_validate(data)


def _parse_resend_envelope(data: dict[str, Any]) -> InboundEmail:
    """Fetch and normalize a Resend inbound message."""
    inner = data["data"]
    resend.api_key = get_settings().resend_api_key
    email_obj = cast(_ReceivedEmailLike, resend.EmailsReceiving.get(inner["email_id"]))
    headers_lower = {key.lower(): value for key, value in email_obj.headers.items()}
    _, from_addr = parseaddr(inner.get("from", ""))
    return InboundEmail(
        id=uuid.uuid4(),
        message_id=email_obj.message_id or inner.get("message_id", ""),
        in_reply_to=headers_lower.get("in-reply-to"),
        references_header=headers_lower.get("references"),
        subject=inner.get("subject", ""),
        from_addr=from_addr,
        to_addr=(inner.get("to") or [""])[0],
        body_text=email_obj.text or "",
        created_at=datetime.now(tz=UTC),
    )


def send_outbound(*args: object, **kwargs: object) -> None:
    """Reject caller-supplied outbound sends before any provider or state effect."""
    del args, kwargs
    raise RuntimeError(
        "direct outbound sending is disabled; use a durable outbound reservation and "
        "identifier-only send job"
    )


def send_reserved_outbound_snapshot(snapshot: Mapping[str, Any]) -> PipelineResult:
    """Send one already-reserved provider payload without changing local delivery state."""
    resend.api_key = get_settings().resend_api_key

    message_id = _snapshot_required_text(snapshot, "message_id")
    attachments_payload: list[resend.Attachment | resend.RemoteAttachment] = []
    attachments = snapshot.get("attachments", [])
    if not isinstance(attachments, list):
        return PipelineResult(stage=PipelineStage.DELIVERY)
    for attachment_row in attachments:
        if not isinstance(attachment_row, Mapping):
            return PipelineResult(stage=PipelineStage.DELIVERY)
        filename = _snapshot_required_text(attachment_row, "filename")
        content = attachment_row.get("content")
        if not isinstance(content, (bytes, bytearray, memoryview)):
            return PipelineResult(stage=PipelineStage.DELIVERY)
        attachments_payload.append(
            {
                "filename": filename,
                "content": base64.b64encode(bytes(content)).decode(),
            }
        )

    headers: dict[str, str] = {"Message-ID": message_id}
    in_reply_to = _snapshot_optional_text(snapshot, "in_reply_to")
    references_header = _snapshot_optional_text(snapshot, "references_header")
    if in_reply_to is not None:
        headers["In-Reply-To"] = in_reply_to
    if references_header is not None:
        headers["References"] = references_header

    send_params: resend.Emails.SendParams = {
        "from": _snapshot_required_text(snapshot, "from_addr"),
        "to": [_snapshot_required_text(snapshot, "to_addr")],
        "subject": _snapshot_required_text(snapshot, "subject"),
        "text": _snapshot_required_text(snapshot, "body_text"),
        "headers": headers,
        "attachments": attachments_payload,
    }
    reply_to = _snapshot_optional_text(snapshot, "reply_to")
    if reply_to is not None:
        send_params["reply_to"] = reply_to

    try:
        resend.Emails.send(send_params, {"idempotency_key": message_id})
    except Exception as exc:
        result = classify_pipeline_exception(PipelineStage.DELIVERY, exc)
        logger.info(
            "OUTBOUND_SNAPSHOT_SEND failed email_id=%s category=%s",
            snapshot.get("email_id"),
            result.diagnostic_code,
        )
        return result

    logger.info("OUTBOUND_SNAPSHOT_SEND sent email_id=%s", snapshot.get("email_id"))
    return PipelineResult(outcome=PipelineOutcome.OK, stage=PipelineStage.DELIVERY)


def _snapshot_required_text(snapshot: Mapping[str, Any], key: str) -> str:
    value = snapshot.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"reserved outbound snapshot has no {key}")
    return value


def _snapshot_optional_text(snapshot: Mapping[str, Any], key: str) -> str | None:
    value = snapshot.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"reserved outbound snapshot has invalid {key}")
    return value
