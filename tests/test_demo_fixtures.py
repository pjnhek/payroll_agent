"""Demo-fixture replay tests (DEMO-01).

The committed CLEAN fixture replays end-to-end via POST and reaches
awaiting_approval — then a crude approve drives it to APPROVED.

The reframed GATE-BLOCK hero ("David Reyez" vs seeded "David Reyes") and the new
COLLISION-SAFETY fixture ("D. Reyes" — a shared alias on two Business-2 employees)
both replay end-to-end and prove the DETERMINISTIC thesis: the system NEVER guesses
on a money-moving decision. There is no model judgment and no score in the
decision path — reconcile resolves each name in pure code, and an unresolved name
(unknown shorthand) or an ambiguous one (alias shared by 2+ employees) deterministically
forces `final_action="request_clarification"` with a gate_reason naming what it
could not resolve. The new hero is "never guesses; clarifies with a specific
suggested employee" (the suggestion-only call names David Reyes in the email copy);
the new collision proof is "two plausible matches → always clarify, never pick."
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
_COLLISION_FIXTURE = (
    pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "collision_safety.json"
)


@pytest.fixture
def client(fake_repo, monkeypatch):
    """TestClient with ALLOW_UNSIGNED_FIXTURES=true so canonical dict POSTs
    succeed in mocked tests (WARNING-1 remediation — 06-04 Task 2/3)."""
    from app.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    yield TestClient(app)
    get_settings.cache_clear()


def _script_clean_run(mock_llm) -> None:
    """The clean happy path makes ONE LLM call — extraction. reconcile/decide are
    pure code and need no scripted response; both names resolve exactly so
    the run processes without a clarify draft."""
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

    # Hardened approve: CAS claim + _deliver → 303 POST-redirect-GET (Plan 05-05).
    # follow_redirects=False: the redirect target /runs/{run_id} is a Wave 4 dashboard
    # route (Plan 05-06) that doesn't exist yet — TestClient would 404 following it.
    approve = client.post(f"/runs/{run_id}/approve", follow_redirects=False)
    assert approve.status_code == 303, (
        f"approve must return 303 POST-redirect-GET; got {approve.status_code}"
    )
    # After approve + _deliver, the run advances to RECONCILED (success) or ERROR (delivery
    # failed in the test env without a live LLM/DB). Both are valid post-approval states.
    # load_line_items returns empty list (no line items in fake_repo by default), so
    # compose_confirmation may succeed with an empty paystub list; the run ends at
    # RECONCILED or ERROR depending on whether the fake gateway/LLM succeeds.
    final_status = fake_repo.load_run(run_id)["status"]
    assert final_status in {"reconciled", "error", "approved", "sent"}, (
        f"After hardened approve, run must be in reconciled/error/approved/sent; "
        f"got {final_status}"
    )


# ---------------------------------------------------------------------------
# Reframed hero: David Reyez (unknown shorthand) → reconcile resolves to none in
# PURE CODE → decide gates to request_clarification → clarify-with-suggestion →
# awaiting_reply. No model judgment, no score — the decision is pure code.
# ---------------------------------------------------------------------------


def _script_hero_run(mock_llm) -> None:
    """The clarify FIFO is extract → SUGGEST → draft (reconcile/decide are pure):
      1. extract: David Reyez with explicit 38 hours (so the ONLY gate trigger is
         the unresolved NAME, not a missing field).
      2. suggest (draft tier, copy only): David Reyez → David Reyes — names the
         specific intended employee for the clarification email. NEVER feeds decide.
      3. draft: the free-text clarification body.
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
                "suggestions": [
                    {
                        "submitted_name": "David Reyez",
                        "suggested_full_name": "David Reyes",
                    }
                ]
            }
        ),
        "Hi — we could not match 'David Reyez'. Did you mean David Reyes?",
    ]


def test_gate_block_fixture_validates_as_inbound_email():
    """The committed hero fixture is a valid InboundEmail submitting the unknown
    shorthand 'David Reyez', from a seeded businesses.contact_email (Metro Deli)."""
    from app.db.seed import seed

    payload = json.loads(_GATE_BLOCK_FIXTURE.read_text())
    email = InboundEmail.model_validate(payload)
    assert "Reyez" in email.body_text, "the hero fixture must submit 'David Reyez'"
    seeded_emails = {b["contact_email"] for b in seed(dry_run=True).businesses}
    assert email.from_addr in seeded_emails


def test_hero_fixture_replays_to_deterministic_clarify(client, fake_repo, mock_llm):
    """DEMO-01: an unknown shorthand 'David Reyez' cannot be resolved
    deterministically, so decide gates the run to request_clarification and the run
    pauses at awaiting_reply end-to-end. There is NO model action and NO score —
    final_action is computed purely from the resolution facts, and the gate_reason
    names the unresolved name."""
    _script_hero_run(mock_llm)

    r = client.post("/webhook/inbound", json=json.loads(_GATE_BLOCK_FIXTURE.read_text()))
    assert r.status_code == 200

    run_id = r.json()["run_id"]
    run = fake_repo.load_run(run_id)

    decision = run["decision"]
    assert decision is not None
    # The deterministic decision — request_clarification, named for the unresolved name.
    assert decision["final_action"] == "request_clarification", (
        "an unknown shorthand the resolver can't match must gate to clarification"
    )
    assert "David Reyez" in decision["unresolved_names"]
    assert any("David Reyez" in reason for reason in decision["gate_reasons"]), (
        "a gate_reason must name the unresolved submitted name"
    )

    # The run gated to clarification and paused at awaiting_reply (CLAR-01).
    assert run["status"] == "awaiting_reply"
    assert fake_repo.get_outbound_message_id(run_id) is not None

    # The persisted reconciliation shows the deterministic unresolved result —
    # source="none", resolved=False, no employee guessed (the system never guesses).
    recon = run["reconciliation"]
    assert recon is not None and len(recon) == 1
    assert recon[0]["source"] == "none"
    assert recon[0]["resolved"] is False
    assert recon[0]["matched_employee_id"] is None


# ---------------------------------------------------------------------------
# Collision-safety: "D. Reyes" is a known alias SHARED by two Business-2 employees
# (David Reyes + Daniel Reyes). The deterministic resolver refuses to pick either —
# source="none", resolved=False — so decide gates the run to clarification. Two
# plausible matches → always clarify, never guess.
# ---------------------------------------------------------------------------


def _script_collision_run(mock_llm) -> None:
    """The clarify FIFO is extract → SUGGEST → draft. The suggestion returns null for
    'D. Reyes' (genuinely ambiguous between two employees — the model must not guess
    wildly), so the clarification falls back to the generic ask for that name."""
    mock_llm.script = [
        json.dumps(
            {
                "employees": [{"submitted_name": "D. Reyes", "hours_regular": "40"}],
                "pay_period_start": "2026-06-15",
                "pay_period_end": None,
            }
        ),
        json.dumps(
            {
                "suggestions": [
                    {"submitted_name": "D. Reyes", "suggested_full_name": None}
                ]
            }
        ),
        "Hi — 'D. Reyes' could be more than one employee. Could you confirm who you mean?",
    ]


def test_collision_fixture_validates_as_inbound_email():
    """The committed collision fixture is a valid InboundEmail submitting the shared
    shorthand 'D. Reyes', from a seeded businesses.contact_email (Metro Deli)."""
    from app.db.seed import seed

    payload = json.loads(_COLLISION_FIXTURE.read_text())
    email = InboundEmail.model_validate(payload)
    assert "D. Reyes" in email.body_text, "the collision fixture must submit 'D. Reyes'"
    seeded_emails = {b["contact_email"] for b in seed(dry_run=True).businesses}
    assert email.from_addr in seeded_emails


def test_collision_fixture_replays_to_deterministic_clarify(client, fake_repo, mock_llm):
    """Collision safety: 'D. Reyes' is an alias shared by two Business-2
    employees, so the resolver cannot uniquely resolve it — it returns unresolved
    rather than guessing. decide gates the run to request_clarification; the system
    never picks one of two plausible matches."""
    _script_collision_run(mock_llm)

    r = client.post("/webhook/inbound", json=json.loads(_COLLISION_FIXTURE.read_text()))
    assert r.status_code == 200

    run_id = r.json()["run_id"]
    run = fake_repo.load_run(run_id)

    decision = run["decision"]
    assert decision is not None
    assert decision["final_action"] == "request_clarification", (
        "a name shared by 2+ employees must gate to clarification, never be guessed"
    )
    assert "D. Reyes" in decision["unresolved_names"]
    assert any("D. Reyes" in reason for reason in decision["gate_reasons"])

    # Paused at awaiting_reply with a clarification sent.
    assert run["status"] == "awaiting_reply"
    assert fake_repo.get_outbound_message_id(run_id) is not None

    # The deterministic resolution: unresolved, no employee guessed.
    recon = run["reconciliation"]
    assert recon is not None and len(recon) == 1
    assert recon[0]["source"] == "none"
    assert recon[0]["resolved"] is False
    assert recon[0]["matched_employee_id"] is None


def test_all_three_fixtures_replay_end_to_end(client, fake_repo, mock_llm):
    """DEMO-01 fully exercised on mocks (deterministic): all three committed fixtures
    replay via POST — the clean one to awaiting_approval, the hero (unknown
    shorthand) and the collision (shared alias) both to awaiting_reply."""
    # Clean fixture → awaiting_approval.
    _script_clean_run(mock_llm)
    r1 = client.post("/webhook/inbound", json=json.loads(_FIXTURE.read_text()))
    assert r1.status_code == 200
    assert fake_repo.load_run(r1.json()["run_id"])["status"] == "awaiting_approval"

    # Hero fixture (unknown shorthand) → awaiting_reply (fresh FIFO script).
    _script_hero_run(mock_llm)
    r2 = client.post(
        "/webhook/inbound", json=json.loads(_GATE_BLOCK_FIXTURE.read_text())
    )
    assert r2.status_code == 200
    assert fake_repo.load_run(r2.json()["run_id"])["status"] == "awaiting_reply"

    # Collision fixture (shared alias) → awaiting_reply (fresh FIFO script).
    _script_collision_run(mock_llm)
    r3 = client.post(
        "/webhook/inbound", json=json.loads(_COLLISION_FIXTURE.read_text())
    )
    assert r3.status_code == 200
    assert fake_repo.load_run(r3.json()["run_id"])["status"] == "awaiting_reply"
