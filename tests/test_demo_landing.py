"""Tests for 06-08: Demo landing, compose, bind, record-only delivery, thread view.

Task 1 tests: schema additions, repo helpers (bind_demo_business, find_business_by_sender
additive lookup, create_run record_only param, set_record_only, get_record_only_flag,
load_thread_messages).

Task 2 tests: orchestrator record-only branches, landing/compose/bind routes, templates.
"""
from __future__ import annotations

import uuid
from datetime import UTC
from unittest.mock import MagicMock

import pytest

from tests.conftest import FakeConnection, patch_get_connection

# ---------------------------------------------------------------------------
# Task 1: Repo helper tests
# ---------------------------------------------------------------------------


def _fake_conn():
    """Convenience factory — avoids pytest fixture dependency in helpers."""
    return FakeConnection()


# ---------------------------------------------------------------------------
# bind_demo_business tests
# ---------------------------------------------------------------------------


def test_bind_demo_business_writes_binding_table_not_businesses(fake_conn):
    """bind_demo_business writes to demo_sender_bindings; NEVER touches businesses."""
    from app.db.repo import bind_demo_business

    metro_id = uuid.UUID("b0000002-0000-0000-0000-000000000002")
    seed_ids = {"Metro Deli Group": metro_id}

    # The INSERT returns a row id — script fetchone so the helper doesn't crash
    fake_conn.script_fetchone(None)  # UPSERT INTO demo_sender_bindings (no RETURNING needed)

    result = bind_demo_business("Metro Deli Group", "pjnhek@gmail.com", seed_ids, conn=fake_conn)

    assert result is True

    all_sql = fake_conn.all_sql().upper()
    # Must touch demo_sender_bindings
    assert "DEMO_SENDER_BINDINGS" in all_sql, "Must INSERT into demo_sender_bindings"

    # Must NOT touch businesses table at all
    for sql, _params in fake_conn.executed:
        assert "UPDATE BUSINESSES" not in sql.upper(), "Must not UPDATE businesses table"
        assert "CONTACT_EMAIL" not in sql.upper(), (
            "Must not reference contact_email on businesses"
        )

    # Verify operator_email and business_id are in the params
    all_params = [str(p) for sql, params in fake_conn.executed if params for p in params]
    assert "pjnhek@gmail.com" in all_params, "operator_email must be in SQL params"
    assert str(metro_id) in all_params or metro_id in [
        p for _, params in fake_conn.executed if params for p in params
    ], "business_id must be in SQL params"


def test_bind_demo_business_returns_false_for_unknown_name(fake_conn):
    """bind_demo_business returns False for unknown business_name; no SQL emitted."""
    from app.db.repo import bind_demo_business

    seed_ids = {"Metro Deli Group": uuid.UUID("b0000002-0000-0000-0000-000000000002")}

    result = bind_demo_business("Unknown Corp", "pjnhek@gmail.com", seed_ids, conn=fake_conn)

    assert result is False

    all_sql = fake_conn.all_sql().upper()
    assert "DEMO_SENDER_BINDINGS" not in all_sql, "No SQL must be emitted for unknown name"


# ---------------------------------------------------------------------------
# find_business_by_sender additive lookup tests
# ---------------------------------------------------------------------------


def test_find_business_by_sender_additive_binding_check(fake_conn):
    """Additive fallback: if no contact_email match, checks demo_sender_bindings."""
    from app.db.repo import find_business_by_sender

    metro_id = uuid.UUID("b0000002-0000-0000-0000-000000000002")

    # First execute: contact_email match returns None
    fake_conn.script_fetchone(None)
    # Second execute: demo_sender_bindings returns the Metro UUID
    fake_conn.script_fetchone((str(metro_id),))

    result = find_business_by_sender("pjnhek@gmail.com", conn=fake_conn)

    assert result == metro_id, "Additive fallback must return Metro UUID"
    assert len(fake_conn.executed) >= 2, "Two SQL executes must be called (primary + additive)"


def test_find_business_by_sender_primary_path_unchanged(fake_conn):
    """Primary contact_email path unchanged: returns on first match, no second query."""
    from app.db.repo import find_business_by_sender

    coastal_id = uuid.UUID("b0000001-0000-0000-0000-000000000001")

    # First execute: contact_email match succeeds
    fake_conn.script_fetchone((str(coastal_id),))

    result = find_business_by_sender("payroll@coastalcleaning.example", conn=fake_conn)

    assert result == coastal_id
    assert len(fake_conn.executed) == 1, "Only one execute for primary path"


# ---------------------------------------------------------------------------
# create_run record_only parameter tests
# ---------------------------------------------------------------------------


def test_create_run_record_only_default_false(fake_conn):
    """create_run defaults record_only=False; column must appear in INSERT."""
    from app.db.repo import create_run

    # RETURNING id
    fake_conn.script_fetchone((str(uuid.uuid4()),))

    create_run(
        business_id=uuid.uuid4(),
        source_email_id=None,
        conn=fake_conn,
    )

    all_sql = fake_conn.all_sql()
    # record_only should appear in the INSERT columns
    assert "record_only" in all_sql.lower(), "record_only must be in INSERT SQL"

    # The value False must be in the params
    all_params_flat = [
        p for sql, params in fake_conn.executed if params for p in params
    ]
    assert False in all_params_flat, "record_only=False must be in VALUES params"


def test_create_run_record_only_true(fake_conn):
    """create_run with record_only=True: column in INSERT and True in params (LOW-6)."""
    from app.db.repo import create_run

    fake_conn.script_fetchone((str(uuid.uuid4()),))

    create_run(
        business_id=uuid.uuid4(),
        source_email_id=None,
        record_only=True,
        conn=fake_conn,
    )

    all_sql = fake_conn.all_sql()
    assert "record_only" in all_sql.lower(), "record_only column must be in INSERT"

    all_params_flat = [
        p for sql, params in fake_conn.executed if params for p in params
    ]
    assert True in all_params_flat, "record_only=True must be in VALUES params"


# ---------------------------------------------------------------------------
# set_record_only test
# ---------------------------------------------------------------------------


def test_set_record_only_updates_run(fake_conn):
    """set_record_only emits an UPDATE ... SET record_only = TRUE."""
    from app.db.repo import set_record_only

    run_id = uuid.uuid4()
    set_record_only(run_id, conn=fake_conn)

    all_sql = fake_conn.all_sql()
    assert "record_only" in all_sql.lower()
    # Must contain TRUE (or True as a param)
    has_true_in_sql = "TRUE" in all_sql.upper()
    has_true_in_params = any(
        p is True or p == True  # noqa: E712
        for sql, params in fake_conn.executed
        if params
        for p in params
    )
    assert has_true_in_sql or has_true_in_params, "record_only=TRUE must appear in UPDATE"

    # run_id must be in WHERE params
    all_params = [p for sql, params in fake_conn.executed if params for p in params]
    assert str(run_id) in [str(p) for p in all_params], "run_id must be in WHERE params"


# ---------------------------------------------------------------------------
# get_record_only_flag test
# ---------------------------------------------------------------------------


def test_get_record_only_flag_returns_true(fake_conn):
    """get_record_only_flag returns True when the DB row has record_only=True."""
    from app.db.repo import get_record_only_flag

    fake_conn.script_fetchone((True,))

    result = get_record_only_flag(uuid.uuid4(), conn=fake_conn)

    assert result is True


# ---------------------------------------------------------------------------
# load_thread_messages tests
# ---------------------------------------------------------------------------


def test_load_thread_messages_includes_source_inbound(fake_conn):
    """load_thread_messages uses OR clause capturing the source inbound row."""
    from app.db.repo import load_thread_messages

    run_id = uuid.uuid4()
    rows = [
        {
            "direction": "inbound",
            "purpose": None,
            "subject": "Payroll hours",
            "body_text": "Maria 40h",
            "message_id": "<src@test>",
            "from_addr": "hr@metrodeli.example",
            "to_addr": "agent@local",
            "created_at": "2026-06-24T01:00:00Z",
        },
        {
            "direction": "outbound",
            "purpose": "clarification",
            "subject": "Clarification needed",
            "body_text": "Did you mean David Reyes?",
            "message_id": "<out@demo.payroll-agent.local>",
            "from_addr": None,
            "to_addr": "hr@metrodeli.example",
            "created_at": "2026-06-24T01:01:00Z",
        },
    ]
    fake_conn.script_fetchall(rows)

    result = load_thread_messages(run_id, conn=fake_conn)

    assert len(result) == 2
    assert result[0]["direction"] == "inbound"

    # OR clause must be present in the executed SQL
    all_sql = fake_conn.all_sql()
    assert "source_email_id" in all_sql, "OR clause (source_email_id subquery) must be present"

    # Two %s placeholders for the single run_id (run_id=? and subquery ??)
    all_params = [p for sql, params in fake_conn.executed if params for p in params]
    run_id_str = str(run_id)
    assert all_params.count(run_id_str) >= 2, "run_id must appear at least twice in params"


def test_load_thread_messages_order_by_created_at(fake_conn):
    """load_thread_messages SQL must include ORDER BY created_at."""
    from app.db.repo import load_thread_messages

    fake_conn.script_fetchall([])

    load_thread_messages(uuid.uuid4(), conn=fake_conn)

    all_sql = fake_conn.all_sql().upper()
    assert "ORDER BY" in all_sql and "CREATED_AT" in all_sql, (
        "SQL must ORDER BY created_at"
    )


# ---------------------------------------------------------------------------
# Task 2: Orchestrator and route tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Orchestrator record-only tests
# ---------------------------------------------------------------------------


def _make_decision_with_unresolved(names):
    """Build a minimal Decision-like object for orchestrator tests."""
    from app.models.contracts import Decision

    return Decision(
        final_action="request_clarification",
        gate_reasons=["Unresolved name"],
        unresolved_names=names,
        missing_fields=[],
        resolutions=[],
    )


def test_orchestrator_record_only_clarify_skips_resend_but_captures_alias(monkeypatch):
    """_clarify with record_only=True: skips send_outbound; alias capture still runs.

    This is the HIGH-2 ordering test: set_alias_candidates must be called BEFORE
    the record_only branch skips the real transport.
    """
    from app.db.seed import seed
    from app.models.roster import Roster
    from app.models.status import RunStatus
    from app.pipeline import clarification

    run_id = uuid.uuid4()

    # Use Business 2's roster (Metro Deli — David Reyes, single-unresolved case)
    result = seed(dry_run=True)
    biz2_id = uuid.UUID("b0000002-0000-0000-0000-000000000002")
    employees = [e for e in result.employees if e.business_id == biz2_id]
    roster = Roster(business_id=biz2_id, employees=employees)

    # Decision: single unresolved name "Dave" (genuinely unresolved — 0 candidates)
    decision = _make_decision_with_unresolved(["Dave"])

    from datetime import datetime

    from app.models.contracts import InboundEmail

    email = InboundEmail(
        id=uuid.uuid4(),
        message_id="<src@test>",
        in_reply_to=None,
        references_header=None,
        subject="Payroll",
        from_addr="hr@metrodeli.example",
        to_addr="agent@local",
        body_text="Dave 40h",
        created_at=datetime.now(UTC),
    )

    alias_capture_calls = []
    insert_calls = []
    set_status_calls = []
    send_outbound_calls = []

    monkeypatch.setattr(
        "app.db.repo.get_outbound_message_id",
        lambda run_id, purpose, **kw: None,
    )
    monkeypatch.setattr(
        "app.db.repo.get_record_only_flag",
        lambda run_id, **kw: True,
    )
    monkeypatch.setattr(
        "app.db.repo.set_alias_candidates",
        lambda run_id, candidates, **kw: alias_capture_calls.append((run_id, candidates)),
    )
    monkeypatch.setattr(
        "app.db.repo.insert_email_message",
        lambda **kw: insert_calls.append(kw) or uuid.uuid4(),
    )
    monkeypatch.setattr(
        "app.db.repo.set_status",
        lambda run_id, status, **kw: set_status_calls.append(status),
    )
    monkeypatch.setattr(
        "app.email.gateway.send_outbound",
        lambda **kw: send_outbound_calls.append(kw),
    )
    monkeypatch.setattr("app.db.repo.set_pre_clarify_extracted", lambda *a, **kw: True)
    # 09-02: the record_only AWAITING_REPLY exit path now opens its own transaction.
    import app.db.repo as repo_mod
    patch_get_connection(monkeypatch, repo_mod)

    # Mock LLM helpers
    mock_llm = MagicMock()
    monkeypatch.setattr(
        "app.pipeline.clarification.suggest_employees",
        lambda names, roster, **kw: {},
    )
    monkeypatch.setattr(
        "app.pipeline.clarification.compose_clarification",
        lambda decision, **kw: "Clarification body",
    )

    from app.models.contracts import Extracted

    def _minimal_extracted(run_id):
        return Extracted(
            run_id=run_id,
            employees=[],
            pay_period_start=None,
            pay_period_end=None,
        )

    clarification.clarify(
        run_id, email, decision, roster, _minimal_extracted(run_id), llm=mock_llm
    )

    # Key assertions for HIGH-2
    assert len(send_outbound_calls) == 0, (
        "gateway.send_outbound must NOT be called for record_only run"
    )
    assert len(insert_calls) >= 1, "repo.insert_email_message must be called (record-only write)"
    assert len(alias_capture_calls) >= 1, (
        "repo.set_alias_candidates must be called BEFORE the record_only branch "
        "(Beat 3 guard — HIGH-2 ordering fix)"
    )
    # Check the inserted row has the right purpose
    assert any(
        kw.get("purpose") == "clarification" and kw.get("send_state") == "sent"
        for kw in insert_calls
    ), "insert_email_message must be called with purpose='clarification' and send_state='sent'"
    # set_status should be AWAITING_REPLY
    assert RunStatus.AWAITING_REPLY in set_status_calls, (
        "set_status must advance to AWAITING_REPLY"
    )


def test_orchestrator_record_only_deliver_skips_resend(monkeypatch):
    """deliver with record_only=True: skips gateway.send_outbound; writes outbound row."""
    from app.models.status import RunStatus
    from app.pipeline import delivery

    run_id = uuid.uuid4()
    biz_id = uuid.UUID("b0000001-0000-0000-0000-000000000001")

    insert_calls = []
    set_status_calls = []
    send_outbound_calls = []

    # Minimal run dict
    run = {
        "id": run_id,
        "business_id": biz_id,
        "status": "approved",
        "extracted_data": None,
        "decision": None,
        "reconciliation": None,
        "error_reason": None,
        "pay_period_start": None,
        "pay_period_end": None,
        "updated_at": None,
    }

    monkeypatch.setattr(
        "app.db.repo.get_outbound_message_id",
        lambda run_id, purpose, **kw: None,
    )
    monkeypatch.setattr(
        "app.db.repo.get_record_only_flag",
        lambda run_id, **kw: True,
    )
    monkeypatch.setattr(
        "app.db.repo.load_line_items",
        lambda run_id, **kw: [],
    )
    monkeypatch.setattr(
        "app.db.repo.load_roster_for_business",
        lambda business_id, **kw: MagicMock(employees=[]),
    )
    monkeypatch.setattr(
        "app.db.repo.load_inbound_email",
        lambda run_id, **kw: None,
    )
    monkeypatch.setattr(
        "app.db.repo.load_business_name",
        lambda business_id, **kw: "Test Business",
    )
    monkeypatch.setattr(
        "app.db.repo.insert_email_message",
        lambda **kw: insert_calls.append(kw) or uuid.uuid4(),
    )
    monkeypatch.setattr(
        "app.db.repo.set_status",
        lambda run_id, status, **kw: set_status_calls.append(status),
    )
    monkeypatch.setattr(
        "app.email.gateway.send_outbound",
        lambda **kw: send_outbound_calls.append(kw),
    )
    monkeypatch.setattr(
        "app.pipeline.delivery.compose_confirmation",
        lambda paystubs, run, **kw: "Confirmation body",
    )
    monkeypatch.setattr(
        "app.pipeline.delivery.generate_paystub_pdf",
        lambda *a, **kw: b"pdf",
    )
    monkeypatch.setattr(
        "app.pipeline.alias_learning.write_aliases_if_safe",
        lambda *a, **kw: None,
    )
    # 09-02: deliver's record_only finalize sequence now opens its own transaction.
    import app.db.repo as repo_mod
    patch_get_connection(monkeypatch, repo_mod)

    delivery.deliver(run_id, run)

    assert len(send_outbound_calls) == 0, (
        "gateway.send_outbound must NOT be called for record_only run"
    )
    assert len(insert_calls) >= 1, "repo.insert_email_message must be called"
    assert any(
        kw.get("purpose") == "confirmation" and kw.get("send_state") == "sent"
        for kw in insert_calls
    ), "insert_email_message must be called with purpose='confirmation' and send_state='sent'"
    assert RunStatus.SENT in set_status_calls, "set_status must advance to SENT"
    assert RunStatus.RECONCILED in set_status_calls, "set_status must advance to RECONCILED"


def test_orchestrator_live_run_still_calls_resend(monkeypatch):
    """clarify with record_only=False keeps calling gateway.send_outbound (no regression)."""
    from datetime import datetime

    from app.db.seed import seed
    from app.models.contracts import InboundEmail
    from app.models.roster import Roster
    from app.pipeline import clarification

    run_id = uuid.uuid4()

    result = seed(dry_run=True)
    biz2_id = uuid.UUID("b0000002-0000-0000-0000-000000000002")
    employees = [e for e in result.employees if e.business_id == biz2_id]
    roster = Roster(business_id=biz2_id, employees=employees)

    decision = _make_decision_with_unresolved(["Dave"])

    email = InboundEmail(
        id=uuid.uuid4(),
        message_id="<src@live-test>",
        in_reply_to=None,
        references_header=None,
        subject="Payroll live",
        from_addr="hr@metrodeli.example",
        to_addr="agent@local",
        body_text="Dave 40h",
        created_at=datetime.now(UTC),
    )

    send_outbound_calls = []

    monkeypatch.setattr("app.db.repo.get_outbound_message_id", lambda *a, **kw: None)
    monkeypatch.setattr("app.db.repo.get_record_only_flag", lambda *a, **kw: False)
    monkeypatch.setattr("app.db.repo.set_alias_candidates", lambda *a, **kw: None)
    monkeypatch.setattr("app.db.repo.set_status", lambda *a, **kw: None)
    monkeypatch.setattr("app.db.repo.insert_email_message", lambda **kw: uuid.uuid4())
    monkeypatch.setattr("app.db.repo.set_pre_clarify_extracted", lambda *a, **kw: True)
    monkeypatch.setattr(
        "app.email.gateway.send_outbound",
        lambda **kw: send_outbound_calls.append(kw),
    )
    monkeypatch.setattr("app.pipeline.clarification.suggest_employees", lambda *a, **kw: {})
    monkeypatch.setattr(
        "app.pipeline.clarification.compose_clarification",
        lambda *a, **kw: "body",
    )
    # 09-02: the live-gateway AWAITING_REPLY exit path now opens its own transaction.
    import app.db.repo as repo_mod
    patch_get_connection(monkeypatch, repo_mod)

    from app.models.contracts import Extracted

    def _minimal_extracted_live(run_id):
        return Extracted(
            run_id=run_id,
            employees=[],
            pay_period_start=None,
            pay_period_end=None,
        )

    mock_llm = MagicMock()
    clarification.clarify(
        run_id, email, decision, roster, _minimal_extracted_live(run_id), llm=mock_llm
    )

    assert len(send_outbound_calls) == 1, (
        "gateway.send_outbound MUST be called for a live (record_only=False) run"
    )


# ---------------------------------------------------------------------------
# Route tests (TestClient)
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    """TestClient with all DB/gateway calls patched out."""
    from fastapi.testclient import TestClient

    import app.db.repo as repo_mod

    # Patch repo helpers that the landing/compose/bind routes call
    monkeypatch.setattr(
        repo_mod,
        "list_businesses",
        lambda **kw: [
            {
                "id": str(uuid.UUID("b0000001-0000-0000-0000-000000000001")),
                "name": "Coastal Cleaning Co.",
                "contact_email": "payroll@coastalcleaning.example",
            },
            {
                "id": str(uuid.UUID("b0000002-0000-0000-0000-000000000002")),
                "name": "Metro Deli Group",
                "contact_email": "hr@metrodeli.example",
            },
            {
                "id": str(uuid.UUID("b0000003-0000-0000-0000-000000000003")),
                "name": "Summit Tech Solutions",
                "contact_email": "finance@summittech.example",
            },
        ],
        raising=False,
    )
    monkeypatch.setattr(repo_mod, "get_demo_binding", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(
        repo_mod,
        "load_roster_for_business",
        lambda *a, **kw: MagicMock(employees=[]),
        raising=False,
    )

    from app.main import app as fastapi_app
    return TestClient(fastapi_app, raise_server_exceptions=False)


def test_landing_get_returns_200_no_bind_form(client):
    """GET / returns 200 with composer form but NO /demo/bind form."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Try it live" in resp.content or b"demo/compose" in resp.content, (
        "Landing page must render composer or 'Try it live'"
    )
    assert b'action="/demo/bind"' not in resp.content, (
        "Bind form must NOT appear on landing page"
    )


def test_bind_route_not_on_landing_page(client):
    """GET / must not contain action=/demo/bind but must contain demo/compose."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'action="/demo/bind"' not in resp.content
    assert b"demo/compose" in resp.content


def test_compose_rejects_unknown_business(monkeypatch):
    """POST /demo/compose with unknown business_name is rejected; create_run not called."""
    import app.db.repo as repo_mod

    create_run_calls = []
    monkeypatch.setattr(repo_mod, "list_businesses", lambda **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "get_demo_binding", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(
        repo_mod,
        "load_roster_for_business",
        lambda *a, **kw: MagicMock(employees=[]),
        raising=False,
    )
    monkeypatch.setattr(
        repo_mod,
        "create_run",
        lambda **kw: create_run_calls.append(kw) or uuid.uuid4(),
        raising=False,
    )

    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app, raise_server_exceptions=False) as tc:
        resp = tc.post(
            "/demo/compose",
            data={"business_name": "Unknown Corp", "subject": "Test", "body": "Maria 40h"},
            follow_redirects=False,
        )

    assert resp.status_code in (302, 303)
    assert create_run_calls == [], "create_run must NOT be called for unknown business"


def test_compose_body_length_cap_rejects_over_limit(monkeypatch):
    """POST /demo/compose with body > 4000 chars is rejected; create_run not called."""
    import app.db.repo as repo_mod

    create_run_calls = []
    monkeypatch.setattr(repo_mod, "list_businesses", lambda **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "get_demo_binding", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(
        repo_mod,
        "load_roster_for_business",
        lambda *a, **kw: MagicMock(employees=[]),
        raising=False,
    )
    monkeypatch.setattr(
        repo_mod,
        "create_run",
        lambda **kw: create_run_calls.append(kw) or uuid.uuid4(),
        raising=False,
    )

    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app, raise_server_exceptions=False) as tc:
        resp = tc.post(
            "/demo/compose",
            data={
                "business_name": "Coastal Cleaning Co.",
                "subject": "x",
                "body": "y" * 4001,
            },
            follow_redirects=False,
        )

    assert resp.status_code in (302, 303)
    location = resp.headers.get("location", "")
    assert location == "/" or location.endswith("/"), "Must redirect to /"
    assert create_run_calls == [], "create_run must NOT be called when body is over limit"


def test_compose_subject_length_cap_rejects_over_limit(monkeypatch):
    """POST /demo/compose with subject > 200 chars is rejected; create_run not called."""
    import app.db.repo as repo_mod

    create_run_calls = []
    monkeypatch.setattr(repo_mod, "list_businesses", lambda **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "get_demo_binding", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(
        repo_mod,
        "load_roster_for_business",
        lambda *a, **kw: MagicMock(employees=[]),
        raising=False,
    )
    monkeypatch.setattr(
        repo_mod,
        "create_run",
        lambda **kw: create_run_calls.append(kw) or uuid.uuid4(),
        raising=False,
    )

    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app, raise_server_exceptions=False) as tc:
        resp = tc.post(
            "/demo/compose",
            data={
                "business_name": "Coastal Cleaning Co.",
                "subject": "s" * 201,
                "body": "Maria 40h",
            },
            follow_redirects=False,
        )

    assert resp.status_code in (302, 303)
    assert create_run_calls == [], "create_run must NOT be called when subject is over limit"


def test_compose_routes_by_business_id_not_find_sender(monkeypatch):
    """POST /demo/compose routes by seed UUID; NEVER calls find_business_by_sender.

    This is the load-bearing HIGH-2 test.
    """
    import app.db.repo as repo_mod

    find_sender_calls = []
    create_run_calls = []
    run_id = uuid.uuid4()
    email_id = uuid.uuid4()

    monkeypatch.setattr(
        repo_mod,
        "find_business_by_sender",
        lambda *a, **kw: find_sender_calls.append(a) or uuid.uuid4(),
        raising=False,
    )
    monkeypatch.setattr(
        repo_mod,
        "insert_inbound_email",
        lambda **kw: (email_id, True),
        raising=False,
    )
    monkeypatch.setattr(
        repo_mod,
        "create_run",
        lambda **kw: create_run_calls.append(kw) or run_id,
        raising=False,
    )
    monkeypatch.setattr(repo_mod, "list_businesses", lambda **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "get_demo_binding", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(
        repo_mod,
        "load_roster_for_business",
        lambda *a, **kw: MagicMock(employees=[]),
        raising=False,
    )
    monkeypatch.setattr(repo_mod, "load_run", lambda *a, **kw: {
        "id": run_id, "business_id": uuid.UUID("b0000002-0000-0000-0000-000000000002"),
        "status": "received", "extracted_data": None, "decision": None, "reconciliation": None,
        "error_reason": None, "pay_period_start": None, "pay_period_end": None, "updated_at": None,
    }, raising=False)
    monkeypatch.setattr(repo_mod, "load_inbound_email", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(repo_mod, "load_line_items", lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "load_outbound_emails", lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "load_thread_messages", lambda *a, **kw: [], raising=False)

    # Patch run_pipeline_bg to be a no-op. raising=True (the default) is used
    # deliberately: if run_pipeline_bg is ever renamed again, this patch must
    # fail LOUDLY (AttributeError) instead of silently becoming a no-op that
    # would let the real route call the REAL pipeline_glue.run_pipeline_bg
    # against this repo's live LLM/gateway keys (T-13-14).
    import app.routes.pipeline_glue as pipeline_glue_mod
    monkeypatch.setattr(pipeline_glue_mod, "run_pipeline_bg", lambda run_id: None)

    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app, raise_server_exceptions=False) as tc:
        resp = tc.post(
            "/demo/compose",
            data={
                "business_name": "Metro Deli Group",
                "subject": "Test payroll",
                "body": "Maria 40h",
            },
            follow_redirects=False,
        )

    # Route must redirect to the run detail
    assert resp.status_code in (302, 303)
    assert find_sender_calls == [], "find_business_by_sender must NOT be called by /demo/compose"

    # create_run must be called with Metro's seed UUID
    metro_id = uuid.UUID("b0000002-0000-0000-0000-000000000002")
    assert create_run_calls, "create_run must be called"
    assert create_run_calls[0].get("business_id") == metro_id, (
        "create_run must use Metro seed UUID directly (HIGH-2)"
    )


def test_compose_sets_record_only_via_create_run(monkeypatch):
    """POST /demo/compose passes record_only=True directly to create_run (LOW-6)."""
    import app.db.repo as repo_mod

    create_run_calls = []
    run_id = uuid.uuid4()
    email_id = uuid.uuid4()

    monkeypatch.setattr(
        repo_mod, "insert_inbound_email", lambda **kw: (email_id, True), raising=False
    )
    monkeypatch.setattr(
        repo_mod,
        "create_run",
        lambda **kw: create_run_calls.append(kw) or run_id,
        raising=False,
    )
    monkeypatch.setattr(repo_mod, "list_businesses", lambda **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "get_demo_binding", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(
        repo_mod,
        "load_roster_for_business",
        lambda *a, **kw: MagicMock(employees=[]),
        raising=False,
    )
    monkeypatch.setattr(repo_mod, "load_run", lambda *a, **kw: {
        "id": run_id, "business_id": uuid.UUID("b0000002-0000-0000-0000-000000000002"),
        "status": "received", "extracted_data": None, "decision": None, "reconciliation": None,
        "error_reason": None, "pay_period_start": None, "pay_period_end": None, "updated_at": None,
    }, raising=False)
    monkeypatch.setattr(repo_mod, "load_inbound_email", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(repo_mod, "load_line_items", lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "load_outbound_emails", lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "load_thread_messages", lambda *a, **kw: [], raising=False)

    # raising=True (the default) is used deliberately here: if run_pipeline_bg
    # is ever renamed again, this patch must fail LOUDLY instead of silently
    # becoming a no-op (T-13-14).
    import app.routes.pipeline_glue as pipeline_glue_mod
    monkeypatch.setattr(pipeline_glue_mod, "run_pipeline_bg", lambda run_id: None)

    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app, raise_server_exceptions=False) as tc:
        tc.post(
            "/demo/compose",
            data={
                "business_name": "Metro Deli Group",
                "subject": "Test payroll",
                "body": "Maria 40h",
            },
            follow_redirects=False,
        )

    assert create_run_calls, "create_run must be called"
    assert create_run_calls[0].get("record_only") is True, (
        "create_run must be called with record_only=True (LOW-6)"
    )


def test_compose_from_addr_is_seed_contact_not_operator(monkeypatch):
    """from_addr for compose runs must be the seed .example contact, not DEMO_OPERATOR_EMAIL."""
    import app.db.repo as repo_mod

    insert_calls = []
    run_id = uuid.uuid4()
    email_id = uuid.uuid4()

    monkeypatch.setattr(
        repo_mod,
        "insert_inbound_email",
        lambda **kw: insert_calls.append(kw) or (email_id, True),
        raising=False,
    )
    monkeypatch.setattr(repo_mod, "create_run", lambda **kw: run_id, raising=False)
    monkeypatch.setattr(repo_mod, "list_businesses", lambda **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "get_demo_binding", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(
        repo_mod,
        "load_roster_for_business",
        lambda *a, **kw: MagicMock(employees=[]),
        raising=False,
    )
    monkeypatch.setattr(repo_mod, "load_run", lambda *a, **kw: {
        "id": run_id, "business_id": uuid.UUID("b0000002-0000-0000-0000-000000000002"),
        "status": "received", "extracted_data": None, "decision": None, "reconciliation": None,
        "error_reason": None, "pay_period_start": None, "pay_period_end": None, "updated_at": None,
    }, raising=False)
    monkeypatch.setattr(repo_mod, "load_inbound_email", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(repo_mod, "load_line_items", lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "load_outbound_emails", lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "load_thread_messages", lambda *a, **kw: [], raising=False)

    # raising=True (the default) is used deliberately here: if run_pipeline_bg
    # is ever renamed again, this patch must fail LOUDLY instead of silently
    # becoming a no-op (T-13-14).
    import app.routes.pipeline_glue as pipeline_glue_mod
    monkeypatch.setattr(pipeline_glue_mod, "run_pipeline_bg", lambda run_id: None)

    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app, raise_server_exceptions=False) as tc:
        tc.post(
            "/demo/compose",
            data={
                "business_name": "Metro Deli Group",
                "subject": "Test payroll",
                "body": "Maria 40h",
            },
            follow_redirects=False,
        )

    assert insert_calls, "insert_inbound_email must be called"
    captured_from = insert_calls[0].get("from_addr", "")
    assert captured_from == "hr@metrodeli.example", (
        f"from_addr must be the seed .example contact (hr@metrodeli.example), got {captured_from!r}"
    )
    assert captured_from != "pjnhek@gmail.com", (
        "from_addr must NOT be DEMO_OPERATOR_EMAIL"
    )


def test_bind_route_writes_demo_sender_bindings_not_contact_email(monkeypatch):
    """POST /demo/bind calls repo.bind_demo_business; NEVER calls functions with 'contact_email'."""
    import app.db.repo as repo_mod

    bind_calls = []
    monkeypatch.setattr(
        repo_mod,
        "bind_demo_business",
        lambda name, email, seed_ids, **kw: bind_calls.append((name, email, seed_ids)) or True,
        raising=False,
    )
    monkeypatch.setattr(repo_mod, "list_businesses", lambda **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "get_demo_binding", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(
        repo_mod,
        "load_roster_for_business",
        lambda *a, **kw: MagicMock(employees=[]),
        raising=False,
    )

    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app, raise_server_exceptions=False) as tc:
        resp = tc.post(
            "/demo/bind",
            data={"business_name": "Metro Deli Group"},
            follow_redirects=False,
        )

    assert resp.status_code in (302, 303), f"Expected redirect, got {resp.status_code}"
    location = resp.headers.get("location", "")
    assert "bound=1" in location, "Must redirect to /?bound=1"

    assert len(bind_calls) == 1, "bind_demo_business must be called once"
    called_name, called_email, called_seed_ids = bind_calls[0]
    assert called_name == "Metro Deli Group"
    assert called_email == "pjnhek@gmail.com", "operator_email must be DEMO_OPERATOR_EMAIL"
    # Check Metro UUID is in the seed_ids
    metro_id = uuid.UUID("b0000002-0000-0000-0000-000000000002")
    assert called_seed_ids.get("Metro Deli Group") == metro_id


def test_run_detail_thread_includes_source_inbound(monkeypatch):
    """GET /runs/{id} renders INBOUND direction from thread_messages."""
    import app.db.repo as repo_mod

    run_id = uuid.uuid4()
    biz_id = uuid.UUID("b0000001-0000-0000-0000-000000000001")

    run = {
        "id": run_id, "business_id": biz_id,
        "status": "received", "extracted_data": None, "decision": None,
        "reconciliation": None, "error_reason": None,
        "pay_period_start": None, "pay_period_end": None, "updated_at": None,
    }

    from datetime import datetime

    thread = [
        {
            "direction": "inbound",
            "purpose": None,
            "subject": "Payroll hours",
            "body_text": "Maria 40h",
            "message_id": "<src@test>",
            "from_addr": "payroll@coastalcleaning.example",
            "to_addr": "agent@local",
            "created_at": datetime.now(UTC),
        }
    ]

    monkeypatch.setattr(repo_mod, "load_run", lambda *a, **kw: run, raising=False)
    monkeypatch.setattr(repo_mod, "load_inbound_email", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(repo_mod, "load_line_items", lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "load_outbound_emails", lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "load_thread_messages", lambda *a, **kw: thread, raising=False)

    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app, raise_server_exceptions=False) as tc:
        resp = tc.get(f"/runs/{run_id}")

    assert resp.status_code == 200
    assert b"INBOUND" in resp.content or b"inbound" in resp.content.lower(), (
        "Thread view must render INBOUND direction label"
    )


def test_run_detail_alias_rationale_rendered(monkeypatch):
    """GET /runs/{id} renders 'known nickname' for resolutions with source='alias'."""
    import app.db.repo as repo_mod

    run_id = uuid.uuid4()
    biz_id = uuid.UUID("b0000001-0000-0000-0000-000000000001")
    emp_id = uuid.UUID("e0000001-0000-0000-0000-000000000001")

    run = {
        "id": run_id, "business_id": biz_id, "status": "computed",
        "extracted_data": None,
        "decision": {
            "final_action": "process",
            "gate_reasons": [],
            "unresolved_names": [],
            "missing_fields": [],
            "resolutions": [
                {
                    "submitted_name": "Maria",
                    "matched_employee_id": str(emp_id),
                    "source": "alias",
                    "resolved": True,
                    "reason": "alias match",
                }
            ],
        },
        "reconciliation": None, "error_reason": None,
        "pay_period_start": None, "pay_period_end": None, "updated_at": None,
    }

    from decimal import Decimal

    from app.models.roster import Employee, Roster

    emp = Employee(
        id=emp_id,
        business_id=biz_id,
        full_name="Maria Chen",
        known_aliases=["Maria"],
        pay_type="hourly",
        hourly_rate=Decimal("18.50"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("12000.00"),
        pay_periods_per_year=52,
    )
    roster = Roster(business_id=biz_id, employees=[emp])

    monkeypatch.setattr(repo_mod, "load_run", lambda *a, **kw: run, raising=False)
    monkeypatch.setattr(repo_mod, "load_inbound_email", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(repo_mod, "load_line_items", lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "load_outbound_emails", lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "load_thread_messages", lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(
        repo_mod, "load_roster_for_business", lambda *a, **kw: roster, raising=False
    )

    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app, raise_server_exceptions=False) as tc:
        resp = tc.get(f"/runs/{run_id}")

    assert resp.status_code == 200
    assert b"known nickname" in resp.content, (
        "alias rationale note must contain 'known nickname'"
    )


def test_run_detail_alias_rationale_absent_for_exact(monkeypatch):
    """GET /runs/{id} must NOT render 'known nickname' for source='exact' resolutions."""
    import app.db.repo as repo_mod

    run_id = uuid.uuid4()
    biz_id = uuid.UUID("b0000001-0000-0000-0000-000000000001")
    emp_id = uuid.UUID("e0000001-0000-0000-0000-000000000001")

    run = {
        "id": run_id, "business_id": biz_id, "status": "computed",
        "extracted_data": None,
        "decision": {
            "final_action": "process",
            "gate_reasons": [],
            "unresolved_names": [],
            "missing_fields": [],
            "resolutions": [
                {
                    "submitted_name": "Maria Chen",
                    "matched_employee_id": str(emp_id),
                    "source": "exact",
                    "resolved": True,
                    "reason": "exact match",
                }
            ],
        },
        "reconciliation": None, "error_reason": None,
        "pay_period_start": None, "pay_period_end": None, "updated_at": None,
    }

    from decimal import Decimal

    from app.models.roster import Employee, Roster

    emp = Employee(
        id=emp_id,
        business_id=biz_id,
        full_name="Maria Chen",
        known_aliases=[],
        pay_type="hourly",
        hourly_rate=Decimal("18.50"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("12000.00"),
        pay_periods_per_year=52,
    )
    roster = Roster(business_id=biz_id, employees=[emp])

    monkeypatch.setattr(repo_mod, "load_run", lambda *a, **kw: run, raising=False)
    monkeypatch.setattr(repo_mod, "load_inbound_email", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(repo_mod, "load_line_items", lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "load_outbound_emails", lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(repo_mod, "load_thread_messages", lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(
        repo_mod, "load_roster_for_business", lambda *a, **kw: roster, raising=False
    )

    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app, raise_server_exceptions=False) as tc:
        resp = tc.get(f"/runs/{run_id}")

    assert resp.status_code == 200
    assert b"known nickname" not in resp.content, (
        "'known nickname' must NOT appear for source='exact' resolutions"
    )
