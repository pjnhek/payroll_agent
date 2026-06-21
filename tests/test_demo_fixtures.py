"""Demo-fixture replay tests (DEMO-01 clean half, D-A4-03).

The committed clean fixture replays end-to-end via POST and reaches
awaiting_approval — then a crude approve drives it to APPROVED. The gate-block
fixture replay lands in Plan 03.
"""
from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.models.contracts import InboundEmail

_FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "clean_happy_path.json"


@pytest.fixture
def client(fake_repo):
    from app.main import app

    return TestClient(app)


def _script_clean_run(mock_llm) -> None:
    mock_llm.script = [
        json.dumps(
            {
                "employees": [
                    {"submitted_name": "Maria Chen", "hours_regular": "40"},
                    {"submitted_name": "James Okafor"},
                ],
                "pay_period_start": "2026-06-15",
                "pay_period_end": None,
            }
        ),
        json.dumps({"model_action": "process", "reasons": ["clean"]}),
    ]


def test_clean_fixture_validates_as_inbound_email():
    """The committed fixture is a valid canonical InboundEmail and its from_addr is
    a seeded businesses.contact_email."""
    from app.db.seed import seed

    payload = json.loads(_FIXTURE.read_text())
    email = InboundEmail.model_validate(payload)
    seeded_emails = {b["contact_email"] for b in seed(dry_run=True).businesses}
    assert email.from_addr in seeded_emails, "fixture from_addr must match a seed contact_email"


def test_clean_fixture_replays_to_pause_and_approves(client, fake_repo, mock_llm):
    _script_clean_run(mock_llm)

    r = client.post("/webhook/inbound", json=json.loads(_FIXTURE.read_text()))
    assert r.status_code == 200

    run_id = r.json()["run_id"]
    run = fake_repo.load_run(run_id)
    assert run["status"] == "awaiting_approval", "clean fixture must reach the pause"

    # Crude operator approve drives it to terminal APPROVED (HITL-01).
    approve = client.post(f"/runs/{run_id}/approve")
    assert approve.status_code == 200
    assert fake_repo.load_run(run_id)["status"] == "approved"
