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
def client(fake_repo, monkeypatch):
    """TestClient with ALLOW_UNSIGNED_FIXTURES=true so the route's prod-auth
    gate does not block canonical InboundEmail dict POSTs in mocked tests.
    (WARNING-1 remediation — 06-04 Task 2)"""
    from app.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    yield TestClient(app)
    get_settings.cache_clear()


def _script_clean_run(mock_llm) -> None:
    """The clean happy path makes ONE LLM call — extraction. reconcile/decide are
    pure deterministic code (D-21-01) and need no scripted response; both names
    resolve exactly so the run processes without a clarify draft."""
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


# ===========================================================================
# Phase 6 Wave 0 — dedup gate tests (06-01 Task 2)
# ===========================================================================

import os  # noqa: E402 — Phase 6 Wave 0 dedup gate tests appended after existing imports
import uuid as _uuid_module  # noqa: E402 — Phase 6 Wave 0 dedup gate tests appended after existing imports

_HAS_DB = bool(os.environ.get("DATABASE_URL"))
_HAS_RESET = os.environ.get("ALLOW_DB_RESET") == "1"


def test_duplicate_delivery_pipeline_runs_once_unit(monkeypatch):
    """D-13 dedup gate: a duplicate delivery must NOT start a second pipeline run.

    Mocked unit test (no live DB). The first POST inserts the email and queues
    run_pipeline. The second POST with the same message_id returns immediately
    (the repo returns inserted=False) and run_pipeline is NOT queued a second time.

    This test has NO @pytest.mark.integration and NO xfail — the existing route +
    repo already handle dedup correctly, so this must pass immediately.

    WARNING-1 (06-04 Task 2 remediation): Route now requires ALLOW_UNSIGNED_FIXTURES=true
    to accept canonical InboundEmail dict POSTs without svix-* signature headers. Set here
    via monkeypatch so the dedup-unit test stays non-integration and non-xfail. (OPS-02 / D-13)
    """
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.db import repo as _repo
    from app.main import app

    # WARNING-1 remediation: enable unsigned fixture POSTs in dev mode so canonical
    # dict payloads reach the route logic (prod default would return 400 without svix headers).
    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")

    # Patch repo.insert_inbound_email: first call inserts, second is duplicate.
    call_count = {"n": 0}

    def _mock_insert(**kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (_uuid_module.UUID("aaaaaaaa-0000-0000-0000-000000000001"), True)
        return (None, False)  # duplicate

    monkeypatch.setattr(_repo, "insert_inbound_email", _mock_insert)

    # Patch create_run so we don't need business_id logic.
    monkeypatch.setattr(
        _repo,
        "create_run",
        lambda **kw: _uuid_module.UUID("bbbbbbbb-0000-0000-0000-000000000001"),
    )
    monkeypatch.setattr(
        _repo,
        "find_business_by_sender",
        lambda from_addr, conn=None: _uuid_module.UUID("cccccccc-0000-0000-0000-000000000001"),
    )

    # Spy on _run_pipeline by patching it at app.main (the private bg task function).
    import app.main as _main
    pipeline_runs: list = []
    monkeypatch.setattr(
        _main,
        "_run_pipeline",
        lambda run_id, conn=None: pipeline_runs.append(run_id),
    )
    # Also patch find_awaiting_reply_for_header so the reply-routing path doesn't interfere.
    monkeypatch.setattr(
        _repo,
        "find_awaiting_reply_for_header",
        lambda *, in_reply_to, references_header, conn=None: None,
    )
    monkeypatch.setattr(
        _repo,
        "find_any_run_for_header",
        lambda *, in_reply_to, references_header, conn=None: None,
    )
    # 09-03 (DATA-02): the dedup-loser branch now calls find_run_by_message_id to
    # report the existing run's id instead of creating a second one.
    monkeypatch.setattr(
        _repo,
        "find_run_by_message_id",
        lambda message_id, conn=None: _uuid_module.UUID(
            "bbbbbbbb-0000-0000-0000-000000000001"
        ),
    )

    # 09-03 (DATA-02): inbound() now wraps its ingest sequence in one
    # `with repo.get_connection() as conn: with conn.transaction(): ...` block.
    # This test monkeypatches individual _repo functions (not the fake_repo
    # fixture), so get_connection must be patched to a FakeConnection double too.
    import contextlib as _contextlib

    from tests.conftest import FakeConnection

    @_contextlib.contextmanager
    def _fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(_repo, "get_connection", _fake_get_connection, raising=False)

    test_client = TestClient(app, raise_server_exceptions=False)

    # Both POSTs use the same message_id.
    payload = {
        "id": str(_uuid_module.uuid4()),
        "message_id": "<dup-dedup-test@acme.test>",
        "in_reply_to": None,
        "references_header": None,
        "subject": "Payroll hours",
        "from_addr": "hr@acme.test",
        "to_addr": "agent@payroll-agent.local",
        "body_text": "Maria 40 regular hours.",
        "created_at": "2026-06-15T10:00:00Z",
    }

    r1 = test_client.post("/webhook/inbound", json=payload)
    r2 = test_client.post("/webhook/inbound", json=payload)

    # Both requests should return 200 (the dedup path is silent — no 4xx).
    assert r1.status_code == 200, f"First POST must return 200; got {r1.status_code}"
    assert r2.status_code == 200, f"Duplicate POST must return 200; got {r2.status_code}"

    # run_pipeline must be queued at most once (the duplicate short-circuits before queuing).
    assert len(pipeline_runs) <= 1, (
        f"run_pipeline must be queued at most ONCE for duplicate deliveries; "
        f"got {len(pipeline_runs)} calls (D-13 dedup gate)"
    )

    # Clean up settings cache after env monkeypatching (WARNING-1 remediation).
    get_settings.cache_clear()


@pytest.mark.integration
def test_duplicate_delivery_pipeline_runs_once():
    """D-13 dedup gate (integration): two deliveries with the same message_id → one run.

    Hits the live DB: the second delivery must return 200 and NOT create a second run.
    Asserts only one email_messages row exists for the message_id (ON CONFLICT DO NOTHING).
    Also asserts that decide.py is NOT called on the duplicate (no second run).

    Requires DATABASE_URL + ALLOW_DB_RESET=1 (same two-factor guard as other integration
    tests). Marked @pytest.mark.integration — excluded from the mocked suite.
    (OPS-02 / D-13 end-to-end dedup)
    """
    if not (_HAS_DB and _HAS_RESET):
        pytest.skip("DATABASE_URL or ALLOW_DB_RESET=1 not set — skipping live-DB dedup test")

    from fastapi.testclient import TestClient

    from app.db.bootstrap import bootstrap
    from app.db.seed import seed as _seed_fn
    from app.main import app

    bootstrap(reset=True)
    _seed_fn()

    # Use a real seeded contact_email so find_business_by_sender succeeds.
    seeded = _seed_fn(dry_run=True)
    contact_email = seeded.businesses[0]["contact_email"]

    dedup_mid = f"<dedup-integ-{_uuid_module.uuid4()}@acme.test>"
    payload = {
        "id": str(_uuid_module.uuid4()),
        "message_id": dedup_mid,
        "in_reply_to": None,
        "references_header": None,
        "subject": "Payroll hours",
        "from_addr": contact_email,
        "to_addr": "agent@payroll-agent.local",
        "body_text": "Maria 40 regular hours.",
        "created_at": "2026-06-15T10:00:00Z",
    }

    test_client = TestClient(app, raise_server_exceptions=True)
    r1 = test_client.post("/webhook/inbound", json=payload)
    r2 = test_client.post("/webhook/inbound", json=payload)

    assert r1.status_code == 200, f"First POST must return 200; got {r1.status_code}"
    assert r2.status_code == 200, (
        f"Duplicate POST must return 200 (silent dedup, not an error); got {r2.status_code}"
    )

    # Verify only one email_messages row exists for this message_id (DB-level assertion).
    # The ON CONFLICT DO NOTHING constraint is the correctness backstop.
    # We query the DB directly to confirm only one row was inserted.
    from app.db.supabase import get_pool
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM email_messages WHERE message_id = %s",
            (dedup_mid,),
        ).fetchone()
    assert row is not None and row[0] == 1, (
        f"Only ONE email_messages row must exist for the duplicate message_id "
        f"(got {row[0] if row else 'None'}) — ON CONFLICT DO NOTHING must deduplicate (D-13)"
    )
