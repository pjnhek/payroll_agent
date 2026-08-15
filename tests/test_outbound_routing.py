"""Unit tests for the demo outbound recipient override.

Pure-function coverage of app/email/routing.py. Integration-shaped-but-hermetic
coverage of the two call sites (snapshot to_addr pinned, simulate_reply threading
preserved) lives in tests/test_delivery.py and tests/test_clarify.py respectively.
"""
from __future__ import annotations

from app.config import get_settings
from app.email.routing import resolve_outbound_recipient


def test_returns_client_address_when_unset(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.delenv("DEMO_OUTBOUND_TO", raising=False)

    assert resolve_outbound_recipient("hr@metrodeli.example") == "hr@metrodeli.example"


def test_returns_override_when_set(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("DEMO_OUTBOUND_TO", "operator@example.com")

    assert resolve_outbound_recipient("hr@metrodeli.example") == "operator@example.com"


def test_whitespace_only_override_is_treated_as_unset(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("DEMO_OUTBOUND_TO", "   ")

    assert resolve_outbound_recipient("hr@metrodeli.example") == "hr@metrodeli.example"
