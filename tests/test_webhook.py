"""Webhook ingest tests (INGEST-01/02/03, DEMO-01 clean half).

The dedupe + unknown-sender tests run offline via the in-memory `fake_repo`. The
end-to-end `test_post_fixture_reaches_pause` relies on TestClient running
BackgroundTasks SYNCHRONOUSLY (RESEARCH §Pattern 1) so it can assert the run
reached awaiting_approval immediately after POST — no server, no sleeps. It is RED
until Tasks 2-4 land the stages, the gate, the calc, and the orchestrator.
"""
from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

_FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "clean_happy_path.json"


def _fixture() -> dict:
    return json.loads(_FIXTURE.read_text())


@pytest.fixture
def client(fake_repo):
    from app.main import app

    return TestClient(app)


def _script_clean_run(mock_llm) -> None:
    """Enqueue ONLY the extraction payload for the all-deterministic happy path
    (Maria Chen + James Okafor both resolve exactly). reconcile and decide are pure
    deterministic code with no LLM call (D-21-01), so no decision response is
    scripted — the gate runs on the resolution facts."""
    extraction = json.dumps(
        {
            "employees": [
                {"submitted_name": "Maria Chen", "hours_regular": "40"},
                {"submitted_name": "James Okafor"},
            ],
            "pay_period_start": "2026-06-15",
            "pay_period_end": None,
        }
    )
    mock_llm.script = [extraction]


# ---------------------------------------------------------------------------
# INGEST-01 / FOUND-02 — duplicate delivery is idempotent (no second run)
# ---------------------------------------------------------------------------


def test_duplicate_delivery_idempotent(client, fake_repo, mock_llm):
    _script_clean_run(mock_llm)
    payload = _fixture()

    r1 = client.post("/webhook/inbound", json=payload)
    assert r1.status_code == 200

    # Re-script for any pipeline run the second POST might trigger (it must not).
    _script_clean_run(mock_llm)
    r2 = client.post("/webhook/inbound", json=payload)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"

    # Exactly one run was created despite two identical deliveries.
    assert len(fake_repo.runs) == 1


# ---------------------------------------------------------------------------
# INGEST-03 — unknown sender is logged + stopped, no run created
# ---------------------------------------------------------------------------


def test_unknown_sender_no_run(client, fake_repo, mock_llm):
    payload = _fixture()
    payload["message_id"] = "<unknown-sender-001@nowhere.test>"
    payload["from_addr"] = "stranger@nowhere.test"  # matches no businesses.contact_email

    r = client.post("/webhook/inbound", json=payload)
    assert r.status_code == 200
    assert r.json()["status"] == "unknown_sender"
    assert len(fake_repo.runs) == 0, "unknown sender must create NO run (INGEST-03)"


# ---------------------------------------------------------------------------
# INGEST-01 / HITL-01 / DEMO-01 — the marquee end-to-end pause
# ---------------------------------------------------------------------------


def test_post_fixture_reaches_pause(client, fake_repo, mock_llm):
    _script_clean_run(mock_llm)

    r = client.post("/webhook/inbound", json=_fixture())
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"

    # TestClient ran the BackgroundTask synchronously → the run is already paused.
    assert len(fake_repo.runs) == 1
    run = next(iter(fake_repo.runs.values()))
    assert run["status"] == "awaiting_approval", (
        f"clean fixture must reach awaiting_approval end-to-end, got {run['status']}"
    )
    # The clean process path persists decision + reconciliation + extracted.
    assert run["decision"] is not None
    assert run["decision"]["final_action"] == "process"
    assert run["reconciliation"] is not None
    assert run["extracted_data"] is not None
