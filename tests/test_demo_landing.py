"""Tests for 06-08: Demo landing, compose, bind, record-only delivery, thread view.

Task 1 tests: schema additions, repo helpers (bind_demo_business, find_business_by_sender
additive lookup, create_run record_only param, set_record_only, get_record_only_flag,
load_thread_messages).

Task 2 tests: orchestrator record-only branches, landing/compose/bind routes, templates.
"""
from __future__ import annotations

import contextlib
import inspect
import uuid
from datetime import UTC
from typing import Any, Literal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.models.contracts import Decision, Extracted
from tests.conftest import FakeConnection, patch_get_connection

# ---------------------------------------------------------------------------
# Task 1: Repo helper tests
# ---------------------------------------------------------------------------


def _fake_conn():
    """Convenience factory — avoids pytest fixture dependency in helpers."""
    return FakeConnection()


def _record_call(calls: list[Any], value: Any) -> None:
    calls.append(value)


def _record_and_return(calls: list[Any], value: Any, result: Any) -> Any:
    calls.append(value)
    return result


class _AtomicDemoTransaction:
    """Rollback-capable transaction recorder for the demo producer contract."""

    def __init__(self, store: _AtomicDemoStore) -> None:
        self.store = store
        self.snapshot: tuple[list[Any], list[Any], list[Any]] | None = None

    def __enter__(self) -> _AtomicDemoTransaction:
        self.snapshot = (
            list(self.store.emails),
            list(self.store.runs),
            list(self.store.jobs),
        )
        self.store.events.append("transaction:enter")
        return self

    def __exit__(self, exc_type, _exc, _tb) -> Literal[False]:
        assert self.snapshot is not None
        if exc_type is None:
            self.store.events.append("transaction:commit")
        else:
            self.store.emails[:], self.store.runs[:], self.store.jobs[:] = self.snapshot
            self.store.events.append("transaction:rollback")
        return False


class _AtomicDemoConnection:
    def __init__(self, store: _AtomicDemoStore) -> None:
        self.store = store

    def transaction(self) -> _AtomicDemoTransaction:
        return _AtomicDemoTransaction(self.store)


class _AtomicDemoStore:
    """Records the three owed writes and can fail any one of them."""

    def __init__(self, fail_at: str | None = None) -> None:
        self.fail_at = fail_at
        self.conn = _AtomicDemoConnection(self)
        self.emails: list[dict[str, Any]] = []
        self.runs: list[dict[str, Any]] = []
        self.jobs: list[dict[str, Any]] = []
        self.events: list[str] = []

    @contextlib.contextmanager
    def get_connection(self):
        yield self.conn

    def insert_inbound_email(self, *, conn=None, **kwargs):
        assert conn is self.conn
        if self.fail_at == "email":
            raise RuntimeError("secret email insert failure <message-id@example>")
        email_id = uuid.uuid4()
        self.emails.append({"id": email_id, **kwargs})
        if self.fail_at == "email_duplicate":
            return email_id, False
        return email_id, True

    def create_run(self, *, conn=None, **kwargs):
        assert conn is self.conn
        if self.fail_at == "run":
            raise RuntimeError("secret run insert failure submitted body")
        run_id = uuid.uuid4()
        self.runs.append({"id": run_id, **kwargs})
        return run_id

    def enqueue_job(self, *, conn=None, **kwargs):
        assert conn is self.conn
        if self.fail_at == "job":
            raise RuntimeError("secret enqueue failure job-123")
        job_id = uuid.uuid4()
        self.jobs.append({"id": job_id, **kwargs})
        if self.fail_at == "job_duplicate":
            return None
        return job_id

    def wake(self) -> None:
        self.events.append("wake")


def _patch_atomic_demo_store(monkeypatch, store: _AtomicDemoStore) -> None:
    import app.db.repo as repo_mod
    from app.queue import wake as wake_mod

    monkeypatch.setattr(repo_mod, "get_connection", store.get_connection)
    monkeypatch.setattr(repo_mod, "insert_inbound_email", store.insert_inbound_email)
    monkeypatch.setattr(repo_mod, "create_run", store.create_run)
    monkeypatch.setattr(repo_mod, "enqueue_job", store.enqueue_job, raising=False)
    monkeypatch.setattr(repo_mod, "list_businesses", lambda: [])
    monkeypatch.setattr(repo_mod, "get_demo_binding", lambda *_args: None)
    monkeypatch.setattr(
        repo_mod,
        "load_roster_for_business",
        lambda *_args: MagicMock(employees=[]),
    )
    monkeypatch.setattr(wake_mod, "wake", store.wake)


def _patch_demo_queue_dependencies(monkeypatch, repo_mod) -> None:
    """Give older focused route tests a transaction and durable enqueue seam."""
    from app.queue import wake as wake_mod

    store = _AtomicDemoStore()
    monkeypatch.setattr(repo_mod, "get_connection", store.get_connection)
    monkeypatch.setattr(repo_mod, "enqueue_job", lambda **_kwargs: uuid.uuid4())
    monkeypatch.setattr(wake_mod, "wake", lambda: None)


def _demo_client() -> TestClient:
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


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
    """create_run with record_only=True: column in INSERT and True in params."""
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


def _make_decision_with_unresolved(names: list[str]) -> Decision:
    """Build a minimal Decision-like object for orchestrator tests."""
    return Decision(
        final_action="request_clarification",
        gate_reasons=["Unresolved name"],
        unresolved_names=names,
        missing_fields=[],
        resolutions=[],
    )


def test_orchestrator_record_only_clarify_skips_resend_but_captures_alias(monkeypatch):
    """_clarify with record_only=True skips send_outbound, but alias capture STILL runs.

    Ordering test: set_alias_candidates must be called BEFORE the record_only branch
    short-circuits the transport. If the capture sat after the branch, the demo path
    would silently stop recording alias candidates — and the learning loop would look
    broken in exactly the flow a viewer is watching.
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

    alias_capture_calls: list[Any] = []
    insert_calls: list[Any] = []
    set_status_calls: list[Any] = []
    send_outbound_calls: list[Any] = []

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
        lambda run_id, candidates, **kw: _record_call(
            alias_capture_calls, (run_id, candidates)
        ),
    )
    monkeypatch.setattr(
        "app.db.repo.insert_email_message",
        lambda **kw: _record_and_return(insert_calls, kw, uuid.uuid4()),
    )
    monkeypatch.setattr(
        "app.db.repo.set_status",
        lambda run_id, status, **kw: _record_call(set_status_calls, status),
    )
    monkeypatch.setattr(
        "app.email.gateway.send_outbound",
        lambda **kw: _record_call(send_outbound_calls, kw),
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

    def _minimal_extracted(run_id: uuid.UUID) -> Extracted:
        return Extracted(
            run_id=run_id,
            employees=[],
            pay_period_start=None,
            pay_period_end=None,
        )

    clarification.clarify(
        run_id, email, decision, roster, _minimal_extracted(run_id), llm=mock_llm
    )

    # The ordering assertions: no transport, but the alias capture still happened.
    assert len(send_outbound_calls) == 0, (
        "gateway.send_outbound must NOT be called for record_only run"
    )
    assert len(insert_calls) >= 1, "repo.insert_email_message must be called (record-only write)"
    assert len(alias_capture_calls) >= 1, (
        "repo.set_alias_candidates must be called BEFORE the record_only branch "
        "short-circuits, or the demo path silently stops capturing alias candidates"
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
    """deliver with record_only=True freezes and queues, without direct transport."""
    from app.pipeline import delivery

    run_id = uuid.uuid4()
    biz_id = uuid.UUID("b0000001-0000-0000-0000-000000000001")

    snapshot_calls: list[Any] = []
    enqueue_calls: list[Any] = []
    send_outbound_calls: list[Any] = []

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
        "app.db.repo.get_unconfirmed_outbound",
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
        "app.db.repo.reserve_outbound_snapshot",
        lambda **kw: _record_and_return(snapshot_calls, kw, {"email_id": uuid.uuid4()}),
    )
    monkeypatch.setattr(
        "app.db.repo.enqueue_job",
        lambda **kw: _record_and_return(enqueue_calls, kw, uuid.uuid4()),
    )
    monkeypatch.setattr(
        "app.email.gateway.send_outbound",
        lambda **kw: _record_call(send_outbound_calls, kw),
    )
    monkeypatch.setattr(
        "app.pipeline.delivery.compose_confirmation",
        lambda paystubs, run, **kw: "Confirmation body",
    )
    monkeypatch.setattr(
        "app.pipeline.delivery.generate_paystub_pdf",
        lambda *a, **kw: b"pdf",
    )
    # Keep the producer path hermetic; record-only side effects occur in the worker.
    import app.db.repo as repo_mod
    patch_get_connection(monkeypatch, repo_mod)

    delivery.deliver(run_id, run)

    assert len(send_outbound_calls) == 0, (
        "gateway.send_outbound must NOT be called for record_only run"
    )
    assert len(snapshot_calls) == 1, "repo.reserve_outbound_snapshot must be called once"
    assert any(
        kw.get("purpose") == "confirmation" for kw in snapshot_calls
    ), "record-only work must still freeze a confirmation snapshot"
    assert len(enqueue_calls) == 1, "record-only work must enqueue one delivery job"


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

    send_outbound_calls: list[Any] = []

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

    def _minimal_extracted_live(run_id: uuid.UUID) -> Extracted:
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


@pytest.fixture(autouse=True)
def _lifespan_database_url(monkeypatch):
    """Every `with TestClient(...) as tc:` in this module now runs the app's
    FastAPI lifespan on entry, and the worker pool's boot-time budget guard
    reads `Settings()` eagerly — `database_url` has no default, so a process
    with no DATABASE_URL set anywhere fails validation before any route even
    runs. None of these tests exercise a real database (every DB call is
    monkeypatched), so a stub value is enough for `Settings()` to validate.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    yield
    get_settings.cache_clear()


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

    create_run_calls: list[Any] = []
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
        lambda **kw: _record_and_return(create_run_calls, kw, uuid.uuid4()),
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

    create_run_calls: list[Any] = []
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
        lambda **kw: _record_and_return(create_run_calls, kw, uuid.uuid4()),
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

    create_run_calls: list[Any] = []
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
        lambda **kw: _record_and_return(create_run_calls, kw, uuid.uuid4()),
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
    """POST /demo/compose routes by seed UUID and NEVER calls find_business_by_sender.

    The demo composer already KNOWS which seeded business it is driving, so resolving the
    business by sender address would be a second, fallible path to an answer it was
    handed — and one that breaks the moment a demo email is sent from any other address.
    """
    import app.db.repo as repo_mod

    find_sender_calls: list[Any] = []
    create_run_calls: list[Any] = []
    run_id = uuid.uuid4()
    email_id = uuid.uuid4()

    monkeypatch.setattr(
        repo_mod,
        "find_business_by_sender",
        lambda *a, **kw: _record_and_return(find_sender_calls, a, uuid.uuid4()),
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
        lambda **kw: _record_and_return(create_run_calls, kw, run_id),
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

    _patch_demo_queue_dependencies(monkeypatch, repo_mod)

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
        "create_run must use the Metro seed UUID directly, not a sender lookup"
    )


def test_compose_sets_record_only_via_create_run(monkeypatch):
    """POST /demo/compose passes record_only=True directly to create_run."""
    import app.db.repo as repo_mod

    create_run_calls: list[Any] = []
    run_id = uuid.uuid4()
    email_id = uuid.uuid4()

    monkeypatch.setattr(
        repo_mod, "insert_inbound_email", lambda **kw: (email_id, True), raising=False
    )
    monkeypatch.setattr(
        repo_mod,
        "create_run",
        lambda **kw: _record_and_return(create_run_calls, kw, run_id),
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

    _patch_demo_queue_dependencies(monkeypatch, repo_mod)

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
        "create_run must be called with record_only=True — a demo-composed run must "
        "never be delivered to the client"
    )


def test_compose_from_addr_is_seed_contact_not_operator(monkeypatch):
    """from_addr for compose runs must be the seed .example contact, not DEMO_OPERATOR_EMAIL."""
    import app.db.repo as repo_mod

    insert_calls: list[Any] = []
    run_id = uuid.uuid4()
    email_id = uuid.uuid4()

    monkeypatch.setattr(
        repo_mod,
        "insert_inbound_email",
        lambda **kw: _record_and_return(insert_calls, kw, (email_id, True)),
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

    _patch_demo_queue_dependencies(monkeypatch, repo_mod)

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

    bind_calls: list[Any] = []
    monkeypatch.setattr(
        repo_mod,
        "bind_demo_business",
        lambda name, email, seed_ids, **kw: _record_and_return(
            bind_calls, (name, email, seed_ids), True
        ),
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


# ---------------------------------------------------------------------------
# Durable composer producer
# ---------------------------------------------------------------------------


def test_demo_compose_commits_email_run_and_job_before_wake(monkeypatch):
    from app.models.job import JobKind

    store = _AtomicDemoStore()
    _patch_atomic_demo_store(monkeypatch, store)

    with _demo_client() as tc:
        response = tc.post(
            "/demo/compose",
            data={
                "business_name": "Metro Deli Group",
                "subject": "Payroll submission",
                "body": "Maria Chen worked 40 hours.",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert len(store.emails) == len(store.runs) == len(store.jobs) == 1
    run_id = store.runs[0]["id"]
    assert response.headers["location"] == f"/runs/{run_id}"
    assert store.runs[0]["record_only"] is True
    assert store.jobs[0]["kind"] is JobKind.RUN_PIPELINE
    assert store.jobs[0]["run_id"] == run_id
    assert store.jobs[0]["business_id"] == store.runs[0]["business_id"]
    assert store.jobs[0]["dedup_key"] == f"demo_run:{run_id}"
    assert store.events == ["transaction:enter", "transaction:commit", "wake"]


@pytest.mark.parametrize(
    "fail_at",
    ["email", "email_duplicate", "run", "job", "job_duplicate"],
)
def test_demo_compose_rolls_back_every_write_failure_and_renders_bounded_notice(
    monkeypatch, fail_at
):
    store = _AtomicDemoStore(fail_at)
    _patch_atomic_demo_store(monkeypatch, store)

    with _demo_client() as tc:
        response = tc.post(
            "/demo/compose",
            data={
                "business_name": "Coastal Cleaning Co.",
                "subject": "PII subject",
                "body": "submitted body Maria Chen <message-id@example>",
            },
            follow_redirects=False,
        )
        notice = tc.get(response.headers["location"])

    assert response.status_code == 303
    assert response.headers["location"] == "/?demo_queue_error=1"
    assert store.emails == store.runs == store.jobs == []
    assert store.events[-1] == "transaction:rollback"
    assert "wake" not in store.events
    assert notice.status_code == 200
    assert notice.text.count("We couldn't queue this demo run. Please try again.") == 1
    for forbidden in (
        "secret email insert failure",
        "secret run insert failure",
        "secret enqueue failure",
        "job-123",
        "message-id@example",
        "submitted body Maria Chen",
    ):
        assert forbidden not in notice.text


def test_demo_routes_have_no_process_memory_pipeline_handoff():
    from app.routes import demo

    for route in (demo.demo_compose, demo.demo_send_test):
        assert "background_tasks" not in inspect.signature(route).parameters
    source = inspect.getsource(demo)
    assert "BackgroundTasks" not in source
    assert ".add_task(" not in source
