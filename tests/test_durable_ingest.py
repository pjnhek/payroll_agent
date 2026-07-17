"""Delayed durable-ingest contracts.

The transport receipt and RFC message are deliberately separate idempotency
layers: an ingest retry may process a different persisted transport event that
fetches the same RFC Message-ID.  These tests exercise the worker-facing
service directly; the HTTP producer is cut over only after the ingest job kind
and null-run settlement exist.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib
import importlib.util
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import repo
from app.email import gateway
from app.main import app
from app.models.contracts import InboundEmail
from app.models.job import JobKind
from app.models.status import RunStatus
from app.pipeline.result import PipelineOutcome, PipelineResult
from app.queue import wake

COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"


def _ingest_module():
    spec = importlib.util.find_spec("app.ingest")
    assert spec is not None, "the delayed app.ingest service boundary is missing"
    return importlib.import_module("app.ingest")


def _email(
    message_id: str,
    *,
    from_addr: str = COASTAL_EMAIL,
    in_reply_to: str | None = None,
) -> InboundEmail:
    return InboundEmail(
        id=uuid.uuid4(),
        message_id=message_id,
        in_reply_to=in_reply_to,
        references_header=in_reply_to,
        subject="Payroll hours",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen worked 40 regular hours.",
        created_at=datetime.now(UTC),
    )


def _event_loader(monkeypatch: pytest.MonkeyPatch, events: dict[uuid.UUID, dict[str, Any]]):
    monkeypatch.setattr(
        repo,
        "load_inbound_event",
        lambda event_id, conn=None: events.get(event_id),
        raising=False,
    )


def test_event_repository_boundary_and_stable_conflict_identity(fake_conn) -> None:
    assert hasattr(repo, "insert_or_get_inbound_event"), (
        "durable receipt repository boundary is missing"
    )
    event_id = uuid.uuid4()
    payload = {"data": {"email_id": "em_transport_only"}}
    fake_conn.script_fetchone(None)
    fake_conn.script_fetchone((event_id,))

    returned_id, inserted = repo.insert_or_get_inbound_event(
        external_event_id="evt_123",
        payload=payload,
        conn=fake_conn,
    )

    assert (returned_id, inserted) == (event_id, False)
    assert len(fake_conn.executed) == 2
    assert "ON CONFLICT (external_event_id) DO NOTHING" in fake_conn.all_sql()
    assert "WHERE external_event_id = %s" in fake_conn.all_sql()
    assert fake_conn.executed[0][1][0] == "evt_123"
    assert fake_conn.executed[0][1][1].obj == payload
    assert fake_conn.executed[1][1] == ("evt_123",)


def test_event_repository_insert_and_load_are_bounded(fake_conn) -> None:
    assert hasattr(repo, "insert_or_get_inbound_event")
    assert hasattr(repo, "load_inbound_event")
    event_id = uuid.uuid4()
    payload = {"data": {"email_id": "em_456"}}
    fake_conn.script_fetchone((event_id,))

    returned_id, inserted = repo.insert_or_get_inbound_event(
        external_event_id="evt_456", payload=payload, conn=fake_conn
    )
    assert (returned_id, inserted) == (event_id, True)

    fake_conn.script_fetchone((event_id, payload))
    loaded = repo.load_inbound_event(event_id, conn=fake_conn)
    assert loaded == {"id": event_id, "payload": payload}
    assert "SELECT id, payload" in fake_conn.executed[-1][0]
    assert "external_event_id" not in fake_conn.executed[-1][0].split("FROM", 1)[0]


def test_purge_retention_is_terminal_only_age_bounded_and_batch_bounded(
    fake_conn,
) -> None:
    """Retention may remove old terminal envelopes, never open transport work."""
    deleted = [uuid.uuid4(), uuid.uuid4()]
    fake_conn.script_fetchall([(event_id,) for event_id in deleted])

    count = repo.purge_terminal_inbound_events(
        older_than_days=30,
        batch_size=2,
        conn=fake_conn,
    )

    assert count == 2
    sql = " ".join(fake_conn.all_sql().split())
    assert "DELETE FROM inbound_events" in sql
    assert "j.kind = 'ingest'" in sql
    assert "j.state IN ('done', 'dead')" in sql
    assert "open_job.state IN ('pending', 'leased')" in sql
    assert "LIMIT %(batch_size)s" in sql
    assert fake_conn.last()[1] == {"older_than_days": 30, "batch_size": 2}


@pytest.mark.parametrize(
    ("older_than_days", "batch_size"),
    [(29, 100), (30, 0), (30, 101), (True, 100), (30, True)],
)
def test_purge_retention_rejects_unsafe_age_or_batch_bounds(
    fake_conn,
    older_than_days: int,
    batch_size: int,
) -> None:
    with pytest.raises(ValueError):
        repo.purge_terminal_inbound_events(
            older_than_days=older_than_days,
            batch_size=batch_size,
            conn=fake_conn,
        )
    assert fake_conn.executed == []


def test_delayed_processing_fetches_only_from_persisted_event(
    fake_repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest = _ingest_module()
    event_id = uuid.uuid4()
    envelope = {"data": {"email_id": "em_delayed"}}
    _event_loader(monkeypatch, {event_id: {"id": event_id, "payload": envelope}})
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        gateway,
        "parse_inbound",
        lambda raw: calls.append(raw) or _email("<delayed@example.test>"),
    )

    result = ingest.process_inbound_event(event_id)

    assert result == PipelineResult(outcome=PipelineOutcome.OK)
    assert calls == [envelope]
    assert len(fake_repo.runs) == 1
    job = next(iter(fake_repo.jobs.values()))
    run_id = next(iter(fake_repo.runs.values()))["id"]
    assert job["kind"] == JobKind.RUN_PIPELINE.value
    assert job["dedup_key"] == f"run_pipeline:{run_id}:0"
    assert job["run_id"] == run_id
    assert job["email_id"] is None
    assert job["operator_resolution_id"] is None


def test_rfc_duplicate_is_independent_of_transport_event_identity(
    fake_repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest = _ingest_module()
    event_a, event_b = uuid.uuid4(), uuid.uuid4()
    envelope_a = {"data": {"email_id": "em_a"}}
    envelope_b = {"data": {"email_id": "em_b"}}
    _event_loader(
        monkeypatch,
        {
            event_a: {"id": event_a, "payload": envelope_a},
            event_b: {"id": event_b, "payload": envelope_b},
        },
    )
    shared = _email("<same-rfc-message@example.test>")
    monkeypatch.setattr(gateway, "parse_inbound", lambda raw: shared)

    assert ingest.process_inbound_event(event_a).outcome is PipelineOutcome.OK
    assert ingest.process_inbound_event(event_b).outcome is PipelineOutcome.OK

    assert len(fake_repo.emails) == 1
    assert len(fake_repo.runs) == 1
    assert len(fake_repo.jobs) == 1


def _seed_reply_target(fake_repo, *, status: RunStatus = RunStatus.AWAITING_REPLY):
    source_id, _ = fake_repo.insert_inbound_email(
        message_id=f"<source-{uuid.uuid4()}@example.test>",
        in_reply_to=None,
        references_header=None,
        subject="Payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular",
    )
    run_id = fake_repo.create_run(
        business_id=COASTAL_BIZ_ID, source_email_id=source_id
    )
    clarification_id = f"<clarify-{uuid.uuid4()}@payroll-agent.local>"
    fake_repo.insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=clarification_id,
        purpose="clarification",
        send_state="sent",
    )
    fake_repo.set_status(run_id, status)
    return run_id, clarification_id


def test_authorized_reply_and_redelivery_ensure_one_identifier_only_resume_job(
    fake_repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest = _ingest_module()
    run_id, clarification_id = _seed_reply_target(fake_repo)
    first_event, retry_event = uuid.uuid4(), uuid.uuid4()
    _event_loader(
        monkeypatch,
        {
            first_event: {"id": first_event, "payload": {"data": {"email_id": "a"}}},
            retry_event: {"id": retry_event, "payload": {"data": {"email_id": "b"}}},
        },
    )
    reply = _email("<reply@example.test>", in_reply_to=clarification_id)
    monkeypatch.setattr(gateway, "parse_inbound", lambda raw: reply)

    assert ingest.process_inbound_event(first_event).outcome is PipelineOutcome.OK
    assert ingest.process_inbound_event(retry_event).outcome is PipelineOutcome.OK

    matching = [
        job
        for job in fake_repo.jobs.values()
        if job["kind"] == JobKind.RESUME_REPLY.value
    ]
    assert len(matching) == 1
    persisted_reply = fake_repo.emails[reply.message_id]
    assert matching[0]["dedup_key"] == (
        f"resume_reply:{run_id}:{persisted_reply['id']}"
    )
    assert matching[0]["run_id"] == run_id
    assert matching[0]["email_id"] == persisted_reply["id"]
    assert matching[0]["operator_resolution_id"] is None


def test_sender_mismatch_never_enqueues_or_invokes_orchestration(
    fake_repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest = _ingest_module()
    run_id, clarification_id = _seed_reply_target(fake_repo)
    event_id = uuid.uuid4()
    _event_loader(
        monkeypatch,
        {event_id: {"id": event_id, "payload": {"data": {"email_id": "spoof"}}}},
    )
    monkeypatch.setattr(
        gateway,
        "parse_inbound",
        lambda raw: _email(
            "<spoof@example.test>",
            from_addr="attacker@evil.example",
            in_reply_to=clarification_id,
        ),
    )
    monkeypatch.setattr(
        repo,
        "enqueue_job",
        lambda **kwargs: pytest.fail("sender mismatch must not enqueue"),
    )
    from app.routes import pipeline_glue

    monkeypatch.setattr(
        pipeline_glue,
        "row_to_inbound",
        lambda row: pytest.fail("sender mismatch must not convert reply content"),
    )
    monkeypatch.setattr(
        pipeline_glue,
        "resume_pipeline_now",
        lambda *args, **kwargs: pytest.fail("sender mismatch must not orchestrate"),
        raising=False,
    )

    result = ingest.process_inbound_event(event_id)

    assert result.outcome is PipelineOutcome.OK
    assert fake_repo.runs[str(run_id)]["status"] == RunStatus.AWAITING_REPLY.value


def test_late_reply_and_unknown_sender_owe_no_job(
    fake_repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest = _ingest_module()
    late_run_id, clarification_id = _seed_reply_target(
        fake_repo, status=RunStatus.SENT
    )
    late_event, unknown_event = uuid.uuid4(), uuid.uuid4()
    _event_loader(
        monkeypatch,
        {
            late_event: {"id": late_event, "payload": {"data": {"email_id": "late"}}},
            unknown_event: {
                "id": unknown_event,
                "payload": {"data": {"email_id": "unknown"}},
            },
        },
    )
    messages = iter(
        [
            _email("<late@example.test>", in_reply_to=clarification_id),
            _email("<unknown@example.test>", from_addr="nobody@example.test"),
        ]
    )
    monkeypatch.setattr(gateway, "parse_inbound", lambda raw: next(messages))

    assert ingest.process_inbound_event(late_event).outcome is PipelineOutcome.OK
    assert ingest.process_inbound_event(unknown_event).outcome is PipelineOutcome.OK

    assert fake_repo.jobs == {}
    assert fake_repo.runs[str(late_run_id)]["status"] == RunStatus.SENT.value
    assert len(fake_repo.runs) == 1


class _RollbackConnection:
    def __init__(self, store) -> None:
        self.store = store

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        snapshot = copy.deepcopy(
            (self.store.emails, self.store.email_by_id, self.store.runs, self.store.jobs)
        )
        try:
            yield
        except BaseException:
            (
                self.store.emails,
                self.store.email_by_id,
                self.store.runs,
                self.store.jobs,
            ) = snapshot
            raise


def test_downstream_enqueue_failure_rolls_back_domain_rows(
    fake_repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest = _ingest_module()
    event_id = uuid.uuid4()
    _event_loader(
        monkeypatch,
        {event_id: {"id": event_id, "payload": {"data": {"email_id": "rollback"}}}},
    )
    monkeypatch.setattr(
        gateway,
        "parse_inbound",
        lambda raw: _email("<rollback@example.test>"),
    )

    @contextlib.contextmanager
    def _connection():
        yield _RollbackConnection(fake_repo)

    monkeypatch.setattr(repo, "get_connection", _connection)
    monkeypatch.setattr(
        repo,
        "enqueue_job",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("queue unavailable")),
    )

    with pytest.raises(RuntimeError, match="queue unavailable"):
        ingest.process_inbound_event(event_id)

    assert fake_repo.emails == {}
    assert fake_repo.runs == {}
    assert fake_repo.jobs == {}


class _ReceiptStore:
    def __init__(self) -> None:
        self.events: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.fail_enqueue = False
        self.fail_commit = False


class _ReceiptConnection:
    def __init__(self, store: _ReceiptStore) -> None:
        self.store = store

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        events_before = copy.deepcopy(self.store.events)
        jobs_before = copy.deepcopy(self.store.jobs)
        self.store.order.append("transaction_open")
        try:
            yield
            if self.store.fail_commit:
                raise RuntimeError("commit failed with private diagnostics")
        except BaseException:
            self.store.events = events_before
            self.store.jobs = jobs_before
            self.store.order.append("rollback")
            raise
        self.store.order.append("commit")


def _install_receipt_repository(
    monkeypatch: pytest.MonkeyPatch, store: _ReceiptStore
) -> None:
    @contextlib.contextmanager
    def _connection() -> Iterator[_ReceiptConnection]:
        yield _ReceiptConnection(store)

    def _insert_or_get(
        *, external_event_id: str, payload: dict[str, Any], conn: Any = None
    ) -> tuple[uuid.UUID, bool]:
        assert isinstance(conn, _ReceiptConnection)
        existing = store.events.get(external_event_id)
        if existing is not None:
            return existing["id"], False
        event_id = uuid.uuid4()
        store.events[external_event_id] = {"id": event_id, "payload": payload}
        store.order.append("event")
        return event_id, True

    def _enqueue(
        *,
        kind: JobKind,
        dedup_key: str,
        event_id: uuid.UUID | None = None,
        conn: Any = None,
        **identifiers: Any,
    ) -> uuid.UUID | None:
        assert isinstance(conn, _ReceiptConnection)
        assert kind is JobKind.INGEST
        assert event_id is not None
        assert dedup_key == f"ingest:{event_id}"
        assert not any(value is not None for value in identifiers.values())
        if store.fail_enqueue:
            raise RuntimeError("enqueue failed with private diagnostics")
        if dedup_key in store.jobs:
            return None
        job_id = uuid.uuid4()
        store.jobs[dedup_key] = {"id": job_id, "event_id": event_id}
        store.order.append("job")
        return job_id

    monkeypatch.setattr(repo, "get_connection", _connection)
    monkeypatch.setattr(repo, "insert_or_get_inbound_event", _insert_or_get)
    monkeypatch.setattr(repo, "enqueue_job", _enqueue)


@pytest.fixture
def receipt_client(monkeypatch: pytest.MonkeyPatch, fake_repo) -> Iterator[TestClient]:
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    yield TestClient(app)
    get_settings.cache_clear()


def _receipt_fixture() -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "message_id": "<receipt-only@example.test>",
        "in_reply_to": None,
        "references_header": None,
        "subject": "Payroll hours",
        "from_addr": COASTAL_EMAIL,
        "to_addr": "agent@payroll-agent.local",
        "body_text": "Maria Chen worked 40 regular hours.",
        "created_at": "2026-06-16T09:30:00Z",
    }


def test_acceptance_commits_event_and_identifier_only_job_before_wake_and_response(
    receipt_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _ReceiptStore()
    _install_receipt_repository(monkeypatch, store)
    monkeypatch.setattr(
        gateway,
        "parse_inbound",
        lambda raw: pytest.fail("request receipt must not fetch or parse provider body"),
    )
    monkeypatch.setattr(wake, "wake", lambda: store.order.append("wake"))

    payload = _receipt_fixture()
    response = receipt_client.post("/webhook/inbound", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "accepted",
        "event_id": str(next(iter(store.events.values()))["id"]),
    }
    assert "run_id" not in body
    assert "job_id" not in body
    assert len(store.events) == 1
    assert len(store.jobs) == 1
    assert store.order == ["transaction_open", "event", "job", "commit", "wake"]
    raw = json.dumps(payload, separators=(",", ":")).encode()
    expected_key = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    assert set(store.events) == {expected_key}


def test_duplicate_redelivery_returns_stable_event_receipt_and_creates_no_second_job(
    receipt_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _ReceiptStore()
    _install_receipt_repository(monkeypatch, store)
    wakes: list[str] = []
    monkeypatch.setattr(wake, "wake", lambda: wakes.append("wake"))
    payload = _receipt_fixture()

    first = receipt_client.post("/webhook/inbound", json=payload)
    second = receipt_client.post("/webhook/inbound", json=payload)

    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == "accepted"
    assert second.json() == {
        "status": "duplicate",
        "event_id": first.json()["event_id"],
    }
    assert len(store.events) == 1
    assert len(store.jobs) == 1
    assert wakes == ["wake"]


@pytest.mark.parametrize("failure", ["enqueue", "commit"])
def test_receipt_transaction_rollback_returns_bounded_503(
    receipt_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    store = _ReceiptStore()
    store.fail_enqueue = failure == "enqueue"
    store.fail_commit = failure == "commit"
    _install_receipt_repository(monkeypatch, store)
    monkeypatch.setattr(
        wake,
        "wake",
        lambda: pytest.fail("a rolled-back receipt must never wake the queue"),
    )

    response = receipt_client.post("/webhook/inbound", json=_receipt_fixture())

    assert response.status_code == 503
    assert response.json() == {"error": "temporarily unavailable"}
    assert store.events == {}
    assert store.jobs == {}
    assert "private diagnostics" not in response.text


def test_signed_receipt_verifies_exact_bytes_before_minimal_envelope_processing(
    receipt_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _ReceiptStore()
    _install_receipt_repository(monkeypatch, store)
    monkeypatch.setattr(wake, "wake", lambda: None)
    raw = b'{"data":{"email_id":"em_transport_123"}}'
    verified: list[bytes] = []
    monkeypatch.setattr(
        gateway,
        "verify",
        lambda body, headers, secret: verified.append(body),
    )

    response = receipt_client.post(
        "/webhook/inbound",
        content=raw,
        headers={
            "content-type": "application/json",
            "svix-id": "evt_transport_123",
            "svix-timestamp": "1784160000",
            "svix-signature": "v1,test",
        },
    )

    assert response.status_code == 200
    assert verified == [raw]
    assert set(store.events) == {"evt_transport_123"}
    assert next(iter(store.events.values()))["payload"] == {
        "data": {"email_id": "em_transport_123"}
    }


def test_authenticated_malformed_envelope_is_bounded_and_never_persisted(
    receipt_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _ReceiptStore()
    _install_receipt_repository(monkeypatch, store)
    calls: list[str] = []
    monkeypatch.setattr(
        gateway,
        "verify",
        lambda body, headers, secret: calls.append("verified"),
    )

    response = receipt_client.post(
        "/webhook/inbound",
        content=b'{"data":{}}',
        headers={
            "content-type": "application/json",
            "svix-id": "evt_bad",
            "svix-timestamp": "1784160000",
            "svix-signature": "v1,test",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid inbound envelope"}
    assert calls == ["verified"]
    assert store.events == {}
    assert store.jobs == {}
