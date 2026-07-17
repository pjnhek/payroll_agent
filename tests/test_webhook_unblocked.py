"""Behavioral proof that durable receipt persistence remains off the event loop."""
from __future__ import annotations

import asyncio
import threading
import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routes import webhook


@pytest.fixture
def unsigned_fixtures_env(monkeypatch):
    """ALLOW_UNSIGNED_FIXTURES=true so canonical dict POSTs succeed (matches the
    `client` fixture convention in tests/test_webhook.py / test_reply_redelivery.py),
    with the lru_cache discipline mock_llm already establishes elsewhere in this
    suite: clear before AND after so per-test env edits never leak."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    yield
    get_settings.cache_clear()


def test_slow_database_receipt_does_not_block_unrelated_event_loop_work(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo,
    unsigned_fixtures_env,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    event_id = uuid.uuid4()

    def _blocked_receipt(
        raw_body: bytes, external_event_id: str, allow_unsigned_fixture: bool
    ) -> SimpleNamespace:
        assert raw_body
        assert external_event_id.startswith("sha256:")
        assert allow_unsigned_fixture is True
        entered.set()
        assert release.wait(timeout=2), "test did not release blocked persistence"
        return SimpleNamespace(event_id=event_id, inserted=True)

    monkeypatch.setattr(
        webhook,
        "_persist_verified_receipt_sync",
        _blocked_receipt,
        raising=False,
    )
    monkeypatch.setattr(webhook.wake, "wake", lambda: None, raising=False)

    async def _exercise() -> tuple[bool, int, dict[str, str]]:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            request_task = asyncio.create_task(
                client.post(
                    "/webhook/inbound",
                    json={"message_id": "<off-loop@example.test>"},
                )
            )
            entered_seen = await asyncio.to_thread(entered.wait, 1)
            sentinel_reached = False

            async def _unrelated() -> None:
                nonlocal sentinel_reached
                await asyncio.sleep(0)
                sentinel_reached = True

            await _unrelated()
            assert sentinel_reached, (
                "unrelated event-loop work must progress while sync persistence waits"
            )
            assert not request_task.done(), "request must still be waiting on persistence"
            release.set()
            response = await request_task
            return entered_seen, response.status_code, response.json()

    entered_seen, status_code, body = asyncio.run(_exercise())

    assert entered_seen, "the synchronous receipt seam was never entered"
    assert status_code == 200
    assert body == {"status": "accepted", "event_id": str(event_id)}


def test_route_source_awaits_receipt_threadpool_boundary() -> None:
    source = __import__("inspect").getsource(webhook.inbound)
    assert "await run_in_threadpool" in source
    assert "_persist_verified_receipt_sync" in source
    assert "request.body()" not in source
    assert "repo.get_connection" not in source
