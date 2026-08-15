"""Demo outbound recipient override -- one pure function, two call sites.

Resend's free tier, sending `from=onboarding@resend.dev`, only delivers to the
account owner's own address. The seeded demo contacts are RFC 2606 `.example`
addresses, so every clarification/confirmation send fails identically and the
landing-page gate demo always escalates to delivery review instead of
completing the clarify -> reply -> resume loop. See app.config.Settings.
demo_outbound_to for the full root-cause note.

This module intentionally does nothing else: no DB write, no businesses.
contact_email mutation, no interaction with the reserved-message_id /
Idempotency-Key path. Both call sites resolve the recipient at snapshot
RESERVATION time (before enqueue_job, before any provider key is minted), so
every replay of a given reservation is byte-identical regardless of when
DEMO_OUTBOUND_TO changes -- see app/pipeline/delivery.py and
app/pipeline/clarification.py.
"""
from __future__ import annotations

from app.config import get_settings


def resolve_outbound_recipient(client_addr: str) -> str:
    """Return the address an outbound client email is actually addressed to.

    A whitespace-only DEMO_OUTBOUND_TO is treated as unset (matches the
    empty-string default's "off" meaning) so a stray env var with only
    spaces cannot silently redirect every send.
    """
    override = get_settings().demo_outbound_to.strip()
    return override or client_addr
