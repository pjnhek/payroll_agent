"""Authentication, streaming-cap, and request-boundary webhook guards."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.email import gateway
from app.main import app
from app.routes import webhook


@pytest.fixture
def client(fake_repo, monkeypatch: pytest.MonkeyPatch):
    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    yield TestClient(app)
    get_settings.cache_clear()


def _signed_headers(event_id: str = "evt_signed") -> dict[str, str]:
    return {
        "content-type": "application/json",
        "svix-id": event_id,
        "svix-timestamp": "1784160000",
        "svix-signature": "v1,test",
    }


def test_signature_failure_happens_before_parse_or_persistence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        gateway,
        "verify",
        lambda *args: (_ for _ in ()).throw(ValueError("bad signature")),
    )
    monkeypatch.setattr(
        webhook,
        "_persist_verified_receipt_sync",
        lambda *args: pytest.fail("unverified bytes must never be persisted"),
        raising=False,
    )
    monkeypatch.setattr(
        gateway,
        "parse_inbound",
        lambda *args: pytest.fail("unverified bytes must never be parsed"),
    )

    response = client.post(
        "/webhook/inbound", content=b"not-json", headers=_signed_headers()
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid signature"}


def test_unsigned_production_request_is_rejected_before_persistence(
    fake_repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "false")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setattr(
        webhook,
        "_persist_verified_receipt_sync",
        lambda *args: pytest.fail("unsigned production bytes must not persist"),
        raising=False,
    )
    try:
        with TestClient(app) as test_client:
            response = test_client.post("/webhook/inbound", content=b"not-json")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 400
    assert response.json() == {"error": "unsigned webhook not allowed"}


def test_streaming_cap_rejects_oversize_before_auth_or_persistence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        gateway,
        "verify",
        lambda *args: pytest.fail("oversize body must be rejected before verification"),
    )
    monkeypatch.setattr(
        webhook,
        "_persist_verified_receipt_sync",
        lambda *args: pytest.fail("oversize body must never persist"),
        raising=False,
    )

    response = client.post(
        "/webhook/inbound",
        content=b"x" * (256 * 1024 + 1),
        headers=_signed_headers("evt_oversize"),
    )

    assert response.status_code == 413
    assert response.json() == {"error": "request too large"}


def test_request_route_never_fetches_body_or_runs_business_processing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_id = uuid.uuid4()
    calls: list[tuple[bytes, str, bool]] = []

    def _receipt(raw: bytes, key: str, fixture: bool) -> SimpleNamespace:
        calls.append((raw, key, fixture))
        return SimpleNamespace(event_id=event_id, inserted=False)

    monkeypatch.setattr(
        webhook, "_persist_verified_receipt_sync", _receipt, raising=False
    )
    monkeypatch.setattr(
        gateway,
        "parse_inbound",
        lambda *args: pytest.fail("request route must not fetch provider body"),
    )
    monkeypatch.setattr(
        webhook,
        "pipeline_glue",
        SimpleNamespace(
            run_pipeline_bg=lambda *args: pytest.fail("request must not run pipeline"),
            resume_pipeline_bg=lambda *args: pytest.fail("request must not resume pipeline"),
        ),
        raising=False,
    )

    response = client.post(
        "/webhook/inbound", json={"message_id": "<fixture@example.test>"}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "duplicate", "event_id": str(event_id)}
    assert len(calls) == 1
