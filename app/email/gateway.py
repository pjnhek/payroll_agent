"""The ONE EmailGateway seam (EMAIL-01) — currently backed by Resend.

Every provider detail is confined to this module, so swapping providers means rewriting
these three functions and nothing else.

    verify(raw_body, headers, signing_secret) -> None
        Verifies a Resend webhook payload via svix HMAC-SHA256. Raises ValueError on
        failure so the route can return 400.

    parse_inbound(raw) -> InboundEmail   (DUAL-PATH)
        Path A — Resend webhook envelope (has data.email_id):
            Two-step: extract email_id from the metadata webhook → call
            resend.EmailsReceiving.get(email_id) → normalize headers
            case-insensitively → return a canonical InboundEmail.
        Path B — Canonical InboundEmail dict/JSON (fixture/dev path):
            model_validate / model_validate_json, with no resend API call and no
            verify. Used by the fixture tests and the demo paths.
        Shape detection is purely STRUCTURAL (presence of the data.email_id envelope).
        Auth gating (ALLOW_UNSIGNED_FIXTURES) lives at the ROUTE layer, never here —
        this module must not be the thing deciding whether a payload is trusted.

    send_outbound(...) -> str
        Crash-safe ordering: write send_state='reserved' BEFORE the provider call, flip
        to 'failed' on exception, flip to 'sent' on success. A crash between the call
        and the DB write therefore leaves durable evidence that a send may have gone
        out, instead of a row that claims nothing was sent.

        resend.api_key is set as the FIRST line of send_outbound. The /demo/send-test
        path calls send_outbound without ever running parse_inbound, so relying on
        parse_inbound to have set the key leaves that path unauthenticated.

        Durable threading: loads the prior outbound references_header from the DB and
        appends the new in_reply_to to build the accumulated References chain. This chain
        is the ONLY thing that routes a client's reply back to its run — lose the anchor
        and the reply arrives as an unrelated first ingest.

        Reply-To topology: when resend_reply_to is non-empty, reply_to is added to the
        send dict so client replies reach the inbound webhook address rather than the
        unreachable onboarding@resend.dev From address.

        Attachments: list[tuple[str, bytes]] is base64-mapped to Resend's SDK format.
"""
from __future__ import annotations

import base64
import json
import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import Any, Protocol, cast

import psycopg
import resend

from app.config import get_settings
from app.db import repo
from app.models.contracts import InboundEmail

# Synthetic outbound Message-ID domain (RFC-shaped, collision-free via uuid4).
_OUTBOUND_DOMAIN = "payroll-agent.local"

logger = logging.getLogger(__name__)


class _ReceivedEmailLike(Protocol):
    """Runtime attribute shape returned by Resend's receiving endpoint."""

    headers: Mapping[str, str]
    message_id: str | None
    text: str | None


# ---------------------------------------------------------------------------
# Internal helper: Resend envelope shape detection
# ---------------------------------------------------------------------------


def _is_resend_envelope(data: dict[str, Any]) -> bool:
    """Return True if `data` has the Resend webhook envelope shape (data.email_id present).

    Purely structural detection — never based on headers or env flags. Auth gating
    (ALLOW_UNSIGNED_FIXTURES / svix-* headers) lives at the route layer; deciding trust
    from the payload's own shape would let a caller pick its own auth path.
    """
    return isinstance(data.get("data"), dict) and "email_id" in data["data"]


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def verify(raw_body: bytes, headers: dict[str, str], signing_secret: str) -> None:
    """Verify a Resend webhook payload using svix HMAC-SHA256.

    Calls resend.Webhooks.verify with a VerifyWebhookOptions TypedDict mapping the
    svix-id / svix-timestamp / svix-signature header values. Returns None on success.
    Raises ValueError on signature failure — the route catches this and returns 400.
    The route MUST call this before any parsing or pipeline work: verifying after a
    parse means untrusted bytes were already interpreted.

    Args:
        raw_body: The raw request body bytes (not yet JSON-parsed).
        headers: The full request headers dict (keys in any case).
        signing_secret: The WEBHOOK_SIGNING_SECRET env var value (starts with whsec_).
    """
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


# ---------------------------------------------------------------------------
# Inbound parsing — DUAL-PATH
# ---------------------------------------------------------------------------


def parse_inbound(raw: dict[str, Any] | str | bytes) -> InboundEmail:
    """Parse an inbound payload into a canonical InboundEmail — DUAL-PATH.

    Path A (Resend envelope — has data.email_id):
        1. JSON-parse if needed.
        2. Detect the Resend envelope (data.email_id present).
        3. Set resend.api_key (defensive only — send_outbound sets it independently as
           its FIRST line).
        4. resend.EmailsReceiving.get(email_id) → ReceivedEmail.
        5. Normalize headers case-insensitively.
        6. Return an InboundEmail carrying the RFC message_id, NOT Resend's internal
           email_id.
        7. Strip display names from the 'from' field via email.utils.parseaddr.

    Path B (canonical InboundEmail dict/JSON — fixture/dev path):
        model_validate_json (str/bytes) or model_validate (dict). No resend API call.
        Used by the demo paths and the fixture tests.

    Shape detection is purely structural — the route layer controls auth gating.
    """
    # --- normalize to dict if needed ---
    data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw

    # --- shape detection: Resend envelope vs canonical ---
    if _is_resend_envelope(data):
        return _parse_resend_envelope(data)

    # Path B: canonical InboundEmail dict
    return InboundEmail.model_validate(data)


def _parse_resend_envelope(data: dict[str, Any]) -> InboundEmail:
    """Path A: parse a Resend webhook envelope by fetching the full email via EmailsReceiving.get.

    The webhook carries only metadata, so this is a real two-step: webhook → fetch →
    InboundEmail. The body and the RFC headers exist only on the fetched object.
    """
    inner = data["data"]
    email_id = inner["email_id"]

    # Defensive: set api_key here in case parse_inbound runs before send_outbound in a
    # code path that starts with an inbound event. send_outbound sets it authoritatively
    # as its own first line; this is only a fallback, never the one that must work.
    resend.api_key = get_settings().resend_api_key

    # Step 4: fetch the full email (body + headers + RFC message_id)
    # Resend types this as ReceivedEmail (a TypedDict), but returns ResponseDict
    # at runtime; ResponseDict is a dict subclass with __getattr__ forwarding.
    email_obj = cast(_ReceivedEmailLike, resend.EmailsReceiving.get(email_id))

    # Step 5: normalize headers case-insensitively. Providers vary the casing of
    # In-Reply-To / References, and a case-sensitive lookup silently misses the
    # threading anchor — the reply then routes nowhere.
    headers_lower = {k.lower(): v for k, v in email_obj.headers.items()}

    # Step 7: strip display names from the 'from' field before populating from_addr, so
    # find_business_by_sender receives a bare RFC 5321 address. A raw
    # `Jane Doe <jane@x.com>` never matches a stored contact_email.
    raw_from = inner.get("from", "")
    _, from_addr_clean = parseaddr(raw_from)

    # Step 6: return the canonical InboundEmail. message_id MUST be the RFC value from
    # email_obj.message_id, NOT Resend's internal email_id: message_id is the dedup key
    # and the reply-threading anchor, and the provider's own id is neither.
    return InboundEmail(
        id=uuid.uuid4(),
        message_id=email_obj.message_id or inner.get("message_id", ""),
        in_reply_to=headers_lower.get("in-reply-to"),
        references_header=headers_lower.get("references"),
        subject=inner.get("subject", ""),
        from_addr=from_addr_clean,
        to_addr=(inner.get("to") or [""])[0],
        body_text=email_obj.text or "",
        created_at=datetime.now(tz=UTC),
    )


# ---------------------------------------------------------------------------
# Outbound sending — crash-safe ordering, auth, durable threading, Reply-To
# ---------------------------------------------------------------------------


def send_outbound(
    *,
    run_id: uuid.UUID,
    to_addr: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    references_header: str | None = None,
    from_addr: str | None = None,
    attachments: list[tuple[str, bytes]] | None = None,
    purpose: str | None = None,
    send_state: str = "sent",
    round: int = 0,
    conn: psycopg.Connection | None = None,
) -> str:
    """Send an outbound email via Resend with crash-safe ordering.

    round: the round-aware upsert key, threaded straight through to
    repo.insert_email_message. Defaults to 0 — confirmation sends never pass a round and
    stay at the default.

    resend.api_key is set on the FIRST line below so send_outbound is ALWAYS
    authenticated. The /demo/send-test path invokes send_outbound without ever running
    parse_inbound (no inbound webhook fires during a demo button press), so this set
    cannot be relocated into parse_inbound — that path would send unauthenticated.

    Crash-safe ordering:
        1. Load the prior outbound references chain from the DB (durable threading).
        2. Write send_state='reserved' BEFORE calling resend.Emails.send — intent before
           side effect. A crash between here and the send leaves the row visible as
           'reserved' rather than silently lost, so the operator can see that a send may
           have escaped.
        3. On exception: flip the row to send_state='failed', then re-raise.
        4. On success: log provider_id (deliberately NOT persisted — email_messages has
           no provider_message_id column). Flip the row to 'sent'.
        5. Return the SYNTHETIC message_id — the sole routing anchor.

    Attachments: list[tuple[str, bytes]] is base64-encoded for the Resend SDK.

    Reply-To: when resend_reply_to is non-empty, reply_to is added to the send dict so
    client replies reach the inbound .resend.app address the webhook IS connected to,
    not the unreachable onboarding@resend.dev From address. It is omitted when empty —
    an empty reply_to would emit a malformed Reply-To header.
    """
    # Set api_key here so send_outbound is always authenticated, even when called from
    # /demo/send-test with no prior parse_inbound.
    resend.api_key = get_settings().resend_api_key

    # Step 0 — durable threading: load the most-recent sent outbound references chain
    # from DB state and append the new in_reply_to token. Building the chain from DB
    # state rather than ephemeral webhook state is what lets it survive dropped or
    # duplicated deliveries; rebuild it from the request and a redelivery silently
    # breaks the client's reply threading.
    prior_chain = repo.get_outbound_references_chain(run_id, conn=conn)
    accumulated_references: str | None
    if prior_chain is not None and in_reply_to:
        accumulated_references = f"{prior_chain} {in_reply_to}"
    elif in_reply_to:
        accumulated_references = in_reply_to
    else:
        accumulated_references = references_header  # caller-passed fallback

    # Step 1: mint the synthetic message_id and write the reserved row BEFORE the send.
    # This message_id is the SOLE routing anchor for every subsequent operation — a
    # client reply is matched back to this run by it and nothing else.
    message_id = f"<{uuid.uuid4()}@{_OUTBOUND_DOMAIN}>"
    repo.insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=message_id,
        in_reply_to=in_reply_to,
        references_header=accumulated_references,
        subject=subject,
        from_addr=from_addr or get_settings().resend_from_addr,
        to_addr=to_addr,
        body_text=body,
        purpose=purpose,
        send_state="reserved",
        round=round,
        conn=conn,
    )

    # Step 2: build the send dict and call the provider. The typed locals + the direct
    # SendParams annotation (deliberately no cast) keep mypy's TypedDict structural
    # checking on every key/value of this money-adjacent literal — a cast here would
    # silence exactly the errors worth catching.
    headers: dict[str, str] = {
        k: v
        for k, v in [
            ("Message-ID", message_id),
            ("In-Reply-To", in_reply_to),
            ("References", accumulated_references),
        ]
        if v
    }
    attachments_payload: list[resend.Attachment | resend.RemoteAttachment] = []
    for name, pdf_bytes in attachments or []:
        attachment: resend.Attachment = {
            "filename": name,
            "content": base64.b64encode(pdf_bytes).decode(),
        }
        attachments_payload.append(attachment)
    send_params: resend.Emails.SendParams = {
        "from": from_addr or get_settings().resend_from_addr,
        "to": [to_addr],
        "subject": subject,
        "text": body,
        "headers": headers,
        "attachments": attachments_payload,
    }

    # resend_reply_to is the inbound .resend.app address. When set, it directs client
    # replies to the address the webhook IS connected to, rather than
    # onboarding@resend.dev, which we cannot receive at. Omitted when empty — an empty
    # reply_to would emit a malformed header.
    _reply_to = get_settings().resend_reply_to
    if _reply_to:
        send_params["reply_to"] = _reply_to
    else:
        # No Reply-To on a real send is a silent reply-loss foot-gun: the From is the
        # free-tier onboarding@resend.dev, which the app cannot receive at, so a client
        # reply goes to a dead address and never reaches the webhook. Warn loudly so a
        # misconfigured deploy (RESEND_REPLY_TO unset) is visible rather than silent.
        logger.warning(
            "OUTBOUND_SEND has no Reply-To (RESEND_REPLY_TO is empty) — client replies "
            "to %s will NOT reach the inbound webhook and will be lost. Set RESEND_REPLY_TO "
            "to the inbound .resend.app address.",
            send_params.get("from", "the from address"),
        )

    try:
        response = resend.Emails.send(send_params)
    except Exception as exc:
        # Flip the reserved row to 'failed' and re-raise. Leaving it at 'reserved' would
        # be indistinguishable from "crashed mid-send, may have escaped".
        repo.update_email_message_state(message_id, "failed", conn=conn)
        raise exc

    # Step 3 (success path): log the provider_id. It is deliberately NOT persisted —
    # email_messages has no provider_message_id column, and the synthetic message_id is
    # the routing anchor, so the provider id is diagnostic only.
    provider_id = response["id"]
    logger.info(
        "OUTBOUND_SEND synthetic_id=%s provider_id=%s", message_id, provider_id
    )

    # Flip the reserved row to 'sent'. The WHERE key must be the SYNTHETIC message_id we
    # reserved the row under — not the provider's id, which the row does not carry yet.
    repo.update_email_message_sent(message_id, conn=conn)

    return message_id
