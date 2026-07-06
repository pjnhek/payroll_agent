"""The ONE EmailGateway seam (EMAIL-01, D-A4-02 forward-compat) — Phase 6 Resend provider.

Three public functions form the entire provider abstraction:

    verify(raw_body, headers, signing_secret) -> None
        Verifies a Resend webhook payload via svix HMAC-SHA256. Raises ValueError on
        failure so the route can return 400. (D-17 / OPS-02)

    parse_inbound(raw) -> InboundEmail   (DUAL-PATH — HIGH-2 fix)
        Path A — Resend webhook envelope (has data.email_id):
            Two-step: extract email_id from the metadata webhook → call
            resend.EmailsReceiving.get(email_id) → normalize headers case-insensitively →
            return canonical InboundEmail. (D-01a / OPS-02)
        Path B — Canonical InboundEmail dict/JSON (fixture/dev path):
            The Phase-2 near-passthrough: model_validate or model_validate_json.
            No resend API call, no verify. Used for fixture tests and the demo paths.
        Shape detection is purely structural (presence of data.email_id envelope).
        Auth gating (ALLOW_UNSIGNED_FIXTURES) lives at the ROUTE layer, not here.

    send_outbound(...) -> str
        D-13c crash-safe ordering: write send_state='reserved' BEFORE the provider call,
        flip to 'failed' on exception (HIGH-3), flip to 'sent' on success.
        HIGH-1-AUTH: resend.api_key is set as the FIRST line of send_outbound so the
        /demo/send-test path (which calls send_outbound without running parse_inbound)
        is always authenticated. (D-13c / HIGH-1-AUTH)
        D-14 durable threading: loads the prior outbound references_header from DB and
        appends the new in_reply_to to build the accumulated References chain.
        REPLY-TO TOPOLOGY (Pass-6): when resend_reply_to is non-empty, adds reply_to to
        the send dict so client replies reach the inbound webhook address rather than the
        unreachable onboarding@resend.dev From address.
        HIGH-3 attachments: list[tuple[str, bytes]] is base64-mapped to Resend's SDK format.

"""
from __future__ import annotations

import base64
import json
import logging
import uuid
from datetime import datetime, timezone
from email.utils import parseaddr

import resend

from app.config import get_settings
from app.db import repo
from app.models.contracts import InboundEmail

# Synthetic outbound Message-ID domain (RFC-shaped, collision-free via uuid4).
_OUTBOUND_DOMAIN = "payroll-agent.local"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helper: Resend envelope shape detection (HIGH-2)
# ---------------------------------------------------------------------------


def _is_resend_envelope(data: dict) -> bool:
    """Return True if `data` has the Resend webhook envelope shape (data.email_id present).

    This is purely structural detection — not based on headers or env flags.
    Auth gating (ALLOW_UNSIGNED_FIXTURES / svix-* headers) lives at the route layer.
    """
    return isinstance(data.get("data"), dict) and "email_id" in data["data"]


# ---------------------------------------------------------------------------
# Signature verification (D-17 / OPS-02)
# ---------------------------------------------------------------------------


def verify(raw_body: bytes, headers: dict[str, str], signing_secret: str) -> None:
    """Verify a Resend webhook payload using svix HMAC-SHA256.

    Calls resend.Webhooks.verify with a VerifyWebhookOptions TypedDict mapping the
    svix-id / svix-timestamp / svix-signature header values. Returns None on success.
    Raises ValueError on signature failure — the route catches this and returns 400
    (D-17: verification happens BEFORE any parsing or pipeline work).

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
# Inbound parsing — DUAL-PATH (HIGH-2 fix)
# ---------------------------------------------------------------------------


def parse_inbound(raw: dict | str | bytes) -> InboundEmail:
    """Parse an inbound payload into a canonical InboundEmail — DUAL-PATH.

    Path A (Resend envelope — has data.email_id):
        1. JSON-parse if needed.
        2. Detect Resend envelope (data.email_id present).
        3. Set resend.api_key (defensive belt-and-suspenders — send_outbound sets it
           independently as its FIRST line per HIGH-1-AUTH).
        4. resend.EmailsReceiving.get(email_id) → ReceivedEmail.
        5. Normalize headers case-insensitively.
        6. Return InboundEmail with RFC message_id (NOT Resend internal email_id).
        7. LOW-9: strip display names from 'from' field via email.utils.parseaddr.

    Path B (canonical InboundEmail dict/JSON — fixture/dev path):
        model_validate_json (str/bytes) or model_validate (dict). No resend API call.
        This is the exact Phase-2 behavior; callers (demo paths, fixture tests) use it.

    Shape detection is purely structural — the route layer controls auth gating.
    """
    # --- normalize to dict if needed ---
    if isinstance(raw, (str, bytes)):
        data = json.loads(raw)
    else:
        data = raw

    # --- shape detection: Resend envelope vs canonical ---
    if _is_resend_envelope(data):
        return _parse_resend_envelope(data)

    # Path B: canonical InboundEmail dict
    return InboundEmail.model_validate(data)


def _parse_resend_envelope(data: dict) -> InboundEmail:
    """Path A: parse a Resend webhook envelope by fetching the full email via EmailsReceiving.get.

    This is the real two-step: metadata webhook → fetch → InboundEmail (D-01a).
    """
    inner = data["data"]
    email_id = inner["email_id"]

    # Belt-and-suspenders: set api_key here in case parse_inbound is called before
    # send_outbound in a code path that starts with an inbound event. The authoritative
    # api_key set is the FIRST line of send_outbound (HIGH-1-AUTH) — this is a fallback.
    resend.api_key = get_settings().resend_api_key

    # Step 4: fetch the full email (body + headers + RFC message_id)
    email_obj = resend.EmailsReceiving.get(email_id)

    # Step 5: normalize headers case-insensitively (Pitfall 4 / D-18)
    headers_lower = {k.lower(): v for k, v in email_obj.headers.items()}

    # Step 7 (LOW-9): strip display names from the 'from' field before populating
    # from_addr so find_business_by_sender receives a bare RFC 5321 address.
    raw_from = inner.get("from", "")
    _, from_addr_clean = parseaddr(raw_from)

    # Step 6: return canonical InboundEmail — message_id is the RFC value from
    # email_obj.message_id, NOT the Resend internal email_id (D-13 dedup key correctness).
    return InboundEmail(
        id=uuid.uuid4(),
        message_id=email_obj.message_id or inner.get("message_id", ""),
        in_reply_to=headers_lower.get("in-reply-to"),
        references_header=headers_lower.get("references"),
        subject=inner.get("subject", ""),
        from_addr=from_addr_clean,
        to_addr=(inner.get("to") or [""])[0],
        body_text=email_obj.text or "",
        created_at=datetime.now(tz=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Outbound sending — D-13c + HIGH-1-AUTH + HIGH-3 + D-14 + REPLY-TO TOPOLOGY
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
    conn=None,
) -> str:
    """Send an outbound email via Resend with D-13c crash-safe ordering.

    round: D-11-01 round-aware upsert key, threaded straight through to
    repo.insert_email_message (defaults to 0 — confirmation sends never pass a
    round and stay at the default, matching pre-Phase-11 behavior exactly).

    HIGH-1-AUTH (R5): resend.api_key is set here so send_outbound is always
    authenticated, even when called from /demo/send-test without prior parse_inbound.
    The /demo/send-test path invokes send_outbound without running parse_inbound (no
    inbound webhook fires during a demo button press), so this set is mandatory here
    and cannot be moved into parse_inbound only.

    D-13c crash-safe ordering:
        1. Load prior outbound references chain from DB (D-14 durable threading).
        2. Write send_state='reserved' BEFORE calling resend.Emails.send (intent-before-
           side-effect: a crash between here and the send leaves the row visible as
           'reserved', not silently lost).
        3. On exception: flip row to send_state='failed', then re-raise (HIGH-3).
        4. On success: log provider_id (NOT persisted — email_messages has no
           provider_message_id column; HIGH-1 waive path). Flip row to 'sent'.
        5. Return the SYNTHETIC message_id (the sole routing anchor).

    HIGH-3 attachments: list[tuple[str, bytes]] is base64-encoded for the Resend SDK.

    REPLY-TO TOPOLOGY (Pass-6): when resend_reply_to is non-empty, adds reply_to to
    the send dict so client replies reach the inbound .resend.app address the webhook
    IS connected to (not the unreachable onboarding@resend.dev From address). Omitted
    when empty — empty reply_to would send a malformed Reply-To header.
    """
    # HIGH-1-AUTH (R5): set api_key here so send_outbound is always authenticated,
    # even when called from /demo/send-test without prior parse_inbound.
    resend.api_key = get_settings().resend_api_key

    # Step 0 (D-14 durable threading): load the most-recent sent outbound references
    # chain from DB state and append the new in_reply_to token. Building from DB state
    # (not ephemeral webhook state) means the chain survives dropped/duplicated deliveries.
    prior_chain = repo.get_outbound_references_chain(run_id, conn=conn)
    if prior_chain is not None and in_reply_to:
        accumulated_references = f"{prior_chain} {in_reply_to}"
    elif in_reply_to:
        accumulated_references = in_reply_to
    else:
        accumulated_references = references_header  # caller-passed fallback

    # Step 1 (D-13c): mint synthetic message_id and write the reserved row BEFORE send.
    # The synthetic message_id is the SOLE routing anchor for all subsequent operations.
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

    # Step 2 (HIGH-3 + REPLY-TO TOPOLOGY): build the send dict and call the provider.
    send_params: dict = {
        "from": from_addr or get_settings().resend_from_addr,
        "to": [to_addr],
        "subject": subject,
        "text": body,
        "headers": {
            k: v
            for k, v in [
                ("Message-ID", message_id),
                ("In-Reply-To", in_reply_to),
                ("References", accumulated_references),
            ]
            if v
        },
        "attachments": [
            {"filename": name, "content": base64.b64encode(pdf_bytes).decode()}
            for name, pdf_bytes in (attachments or [])
        ],
    }

    # REPLY-TO TOPOLOGY (P6): resend_reply_to is the inbound .resend.app address
    # (owned by 06-02); when set, directs client replies to the address the webhook
    # IS connected to (not onboarding@resend.dev which we cannot receive at).
    # Omitted when empty — empty reply_to would be malformed.
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
        # HIGH-3: flip the reserved row to 'failed' and re-raise.
        repo.update_email_message_state(message_id, "failed", conn=conn)
        raise exc

    # Step 3 (success path, HIGH-1 waive): log provider_id — NOT persisted to DB
    # (email_messages has no provider_message_id column — HIGH-1 waive path).
    provider_id = response["id"]
    logger.info(
        "OUTBOUND_SEND synthetic_id=%s provider_id=%s", message_id, provider_id
    )

    # Flip the reserved row to 'sent'. WHERE key is the SYNTHETIC message_id (BLOCKER-3).
    repo.update_email_message_sent(message_id, conn=conn)

    return message_id
