"""Inbound body-cleaning tests (INGEST-02, review FIX C, threat T-02-10).

The webhook cleans the inbound body via the in-house clean_body() code-strip
BEFORE the email_messages insert, so the persisted body_text is the cleaned text
(the single cleaned-body source of truth load_source_email returns unchanged for
the Plan 04 resume). No third-party reply-parser is involved — no new dependency.
"""
from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.email.clean import clean_body

_FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "clean_happy_path.json"


# ---------------------------------------------------------------------------
# clean_body unit behavior — quoted history + signature stripping
# ---------------------------------------------------------------------------


def test_clean_strips_quoted_reply_block():
    raw = (
        "Maria 40 regular hours.\n"
        "\n"
        "On Mon, Jun 8, 2026 at 9:14 AM Dana <p@x.test> wrote:\n"
        "> Last week's hours were Maria 38.\n"
        "> Thanks!\n"
    )
    cleaned = clean_body(raw)
    assert "Maria 40 regular hours." in cleaned
    assert "Last week" not in cleaned, "quoted history must be stripped"
    assert "wrote:" not in cleaned


def test_clean_strips_leading_quote_marker_block():
    raw = "This week: Maria 40.\n> quoted line one\n> quoted line two\n"
    cleaned = clean_body(raw)
    assert "This week: Maria 40." in cleaned
    assert "quoted line" not in cleaned


def test_clean_strips_signature_block():
    raw = "James salaried, no changes.\n\n-- \nDana Whitfield\nOffice Manager\n"
    cleaned = clean_body(raw)
    assert "James salaried, no changes." in cleaned
    assert "Office Manager" not in cleaned, "signature must be stripped"


def test_clean_is_idempotent():
    raw = "Maria 40 regular hours."
    assert clean_body(clean_body(raw)) == clean_body(raw)


# ---------------------------------------------------------------------------
# INGEST-02 / FIX C — the webhook persists the CLEANED body to body_text
# ---------------------------------------------------------------------------


@pytest.fixture
def client(fake_repo):
    from app.main import app

    return TestClient(app)


def _script_clean_run(mock_llm) -> None:
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
    decision = json.dumps({"model_action": "process", "reasons": ["clean"]})
    mock_llm.script = [extraction, decision]


def test_body_cleaned(client, fake_repo, mock_llm):
    """The fixture carries a quoted reply block + a signature; the row persisted to
    email_messages.body_text is the CLEANED text (FIX C)."""
    _script_clean_run(mock_llm)
    payload = json.loads(_FIXTURE.read_text())

    r = client.post("/webhook/inbound", json=payload)
    assert r.status_code == 200

    # Exactly one inbound email stored; its body_text is the cleaned body.
    assert len(fake_repo.emails) == 1
    stored = next(iter(fake_repo.emails.values()))
    body = stored["body_text"]

    assert "Maria Chen - 40 regular hours" in body
    # The fixture's quoted history + signature are gone.
    assert "wrote:" not in body, "quoted attribution must be stripped before insert"
    assert "Last week's hours" not in body, "quoted history must be stripped"
    assert "Office Manager" not in body, "signature must be stripped"

    # And load_source_email returns that SAME cleaned body unchanged (no re-clean).
    run_id = next(iter(fake_repo.runs))
    assert fake_repo.load_source_email(run_id) == body
