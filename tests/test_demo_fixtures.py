"""Demo-fixture replay tests (DEMO-01, D-A4-03).

The committed CLEAN fixture replays end-to-end via POST and reaches
awaiting_approval — then a crude approve drives it to APPROVED. The committed
GATE-BLOCK hero fixture (David Reyez vs seeded David Reyes) replays end-to-end on
TWO structurally-distinct mocks: the layer-2 reconcile returns a willing
sub-threshold match (llm_typo → David Reyes @ 0.6) and the decision-advisory says
process — so the code gate OVERRIDES the willing model into clarification (the
"model was willing; code said no" money shot, DEMO-01 gate-block half). The mock
proves the gate fires; the LIVE proof is Plan 04 (D-A4-01a).
"""
from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.models.contracts import InboundEmail

_FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "clean_happy_path.json"
_GATE_BLOCK_FIXTURE = (
    pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "gate_block_hero.json"
)

# The seeded David Reyes employee id (app/db/seed.py emp 3) — the hero mock sets
# this as matched_employee_id so the model "found the right employee" but at
# sub-threshold confidence (review FIX 8: willing, not cautious-unknown).
_DAVID_REYES_ID = "e0000003-0000-0000-0000-000000000003"


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


# ---------------------------------------------------------------------------
# Gate-block hero: David Reyez → reconcile sub-0.8 (model willing) → gate blocks
# → clarify → awaiting_reply (DEMO-01 gate-block half; the mock proves the gate).
# ---------------------------------------------------------------------------


def _script_gate_block_run(mock_llm) -> None:
    """TWO structurally-distinct structured mocks + a draft body (review FIX 8).

    The orchestrator FIFO is extract → reconcile → decide → draft:
      1. extract: David Reyez with explicit 38 hours (so the ONLY gate trigger is
         the sub-0.8 NAME, not a missing field).
      2. reconcile (layer-2 NameReconciliationResponse): David Reyez → llm_typo →
         David Reyes's seeded id @ confidence 0.6 — the model is WILLING (it found
         the right employee for the typo) but at sub-threshold confidence (NOT
         match_type="unknown", which would be the model being cautious — FIX 8).
      3. decide-advisory: model_action="process" — the model says go.
      4. draft: a free-text clarification body.
    """
    mock_llm.script = [
        json.dumps(
            {
                "employees": [{"submitted_name": "David Reyez", "hours_regular": "38"}],
                "pay_period_start": "2026-06-15",
                "pay_period_end": None,
            }
        ),
        json.dumps(
            {
                "matches": [
                    {
                        "submitted_name": "David Reyez",
                        "matched_employee_id": _DAVID_REYES_ID,
                        "match_type": "llm_typo",
                        "confidence": "0.6",
                        "reason": "likely a typo of David Reyes (y->z)",
                    }
                ]
            }
        ),
        json.dumps({"model_action": "process", "reasons": ["all hours present"]}),
        "Hi — could you confirm the employee name 'David Reyez' before we run payroll?",
    ]


def test_gate_block_fixture_validates_as_inbound_email():
    """The committed gate-block fixture is a valid InboundEmail submitting David
    Reyez, from a seeded businesses.contact_email (Metro Deli)."""
    from app.db.seed import seed

    payload = json.loads(_GATE_BLOCK_FIXTURE.read_text())
    email = InboundEmail.model_validate(payload)
    assert "Reyez" in email.body_text, "the hero fixture must submit 'David Reyez'"
    seeded_emails = {b["contact_email"] for b in seed(dry_run=True).businesses}
    assert email.from_addr in seeded_emails


def test_gate_block_fixture_replays_and_overrides_willing_model(
    client, fake_repo, mock_llm
):
    """The money shot (DEMO-01 gate-block half): the model says process on a sub-0.8
    typo match, but the code gate OVERRIDES it to request_clarification, and the run
    pauses at awaiting_reply end-to-end. Assert BOTH fields — the override is the
    whole point (the mock proves the gate; the live proof is Plan 04, D-A4-01a)."""
    _script_gate_block_run(mock_llm)

    r = client.post("/webhook/inbound", json=json.loads(_GATE_BLOCK_FIXTURE.read_text()))
    assert r.status_code == 200

    run_id = r.json()["run_id"]
    run = fake_repo.load_run(run_id)

    decision = run["decision"]
    assert decision is not None
    # THE OVERRIDE — assert BOTH fields, not just final_action.
    assert decision["model_action"] == "process", "the model was WILLING"
    assert decision["final_action"] == "request_clarification", (
        "the code gate must OVERRIDE the willing model on a sub-0.8 name"
    )
    assert decision["gate_triggered"] is True

    # The run gated to clarification and paused at awaiting_reply (CLAR-01).
    assert run["status"] == "awaiting_reply"
    assert fake_repo.get_outbound_message_id(run_id) is not None

    # The persisted reconciliation shows the willing-but-sub-threshold match.
    recon = run["reconciliation"]
    assert recon is not None and len(recon) == 1
    assert recon[0]["match_type"] == "llm_typo"
    assert recon[0]["matched_employee_id"] == _DAVID_REYES_ID
    assert recon[0]["confidence"] == "0.6"


def test_both_fixtures_replay_end_to_end(client, fake_repo, mock_llm):
    """DEMO-01 fully exercised on mocks: both committed fixtures replay via POST —
    the clean one to awaiting_approval, the gate-block one to awaiting_reply."""
    # Clean fixture → awaiting_approval.
    _script_clean_run(mock_llm)
    r1 = client.post("/webhook/inbound", json=json.loads(_FIXTURE.read_text()))
    assert r1.status_code == 200
    assert fake_repo.load_run(r1.json()["run_id"])["status"] == "awaiting_approval"

    # Gate-block fixture → awaiting_reply (fresh FIFO script).
    _script_gate_block_run(mock_llm)
    r2 = client.post(
        "/webhook/inbound", json=json.loads(_GATE_BLOCK_FIXTURE.read_text())
    )
    assert r2.status_code == 200
    assert fake_repo.load_run(r2.json()["run_id"])["status"] == "awaiting_reply"
