"""The ONE EmailGateway seam (EMAIL-01, D-A4-02 forward-compat).

Two functions are the entire provider abstraction; the real provider swaps in at
P6 touching only this file:

    parse_inbound(raw) -> InboundEmail   (Phase 2: near-passthrough validation)
    send_outbound(...) -> str            (stub: synthetic Message-ID + outbound row)

In Phase 2 the webhook receives canonical InboundEmail JSON directly (fixture-
first), so parse_inbound just validates it against the contract. send_outbound is
a stub that mints an RFC-shaped synthetic Message-ID, writes an
email_messages(direction='outbound', run_id) row via repo.py, and returns the ID.
That outbound row is the single canonical anchor for the clarification Message-ID
that Plans 03/04 read back (FIX 3) — there is NO payroll_runs Message-ID column.
"""
from __future__ import annotations

import uuid

from app.db import repo
from app.models.contracts import InboundEmail

# Synthetic outbound Message-ID domain (RFC-shaped, collision-free via uuid4).
_OUTBOUND_DOMAIN = "payroll-agent.local"


def parse_inbound(raw: dict | str | bytes) -> InboundEmail:
    """Validate a canonical inbound payload into an InboundEmail.

    Phase 2 is fixture-first: the webhook posts canonical InboundEmail JSON, so
    this is a near-passthrough that validates against the contract (model_validate
    for a dict, model_validate_json for a JSON string/bytes). A real provider
    parser slots in here at P6 without touching any caller.
    """
    if isinstance(raw, (str, bytes)):
        return InboundEmail.model_validate_json(raw)
    return InboundEmail.model_validate(raw)


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
    conn=None,
) -> str:
    """Stub send: mint a synthetic Message-ID, record the outbound row, return it.

    The returned `<uuid@payroll-agent.local>` Message-ID is anchored on the
    inserted email_messages(direction='outbound', run_id) row — the single
    canonical anchor Plans 03/04 read back via repo.get_outbound_message_id
    (FIX 3). The real provider's send slots in here at P6.

    `purpose` distinguishes clarification from confirmation outbound rows
    (CLAR-04 finding #1 fix). `send_state` defaults to 'sent' for the Phase 5
    synchronous stub — Phase 6 live-provider wiring writes send_state='reserved'
    BEFORE the provider call, then flips to 'sent'/'failed' after (D-13c
    crash-safe ordering). No code change needed in this plan; the column is live.
    `attachments` carries per-employee PDF bytes for the confirmation path.

    # D-13c Phase-6-forward: send_state='reserved' before provider call, 'sent'
    # after; Phase 5 stub writes 'sent' directly (synchronous, no crash window).
    # Real D-13c encoding — purpose and send_state columns, not overloaded direction.
    """
    message_id = f"<{uuid.uuid4()}@{_OUTBOUND_DOMAIN}>"
    repo.insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=message_id,
        in_reply_to=in_reply_to,
        references_header=references_header,
        subject=subject,
        from_addr=from_addr,
        to_addr=to_addr,
        body_text=body,
        purpose=purpose,
        send_state=send_state,
        conn=conn,
    )
    return message_id
