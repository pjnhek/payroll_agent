"""Webhook reply redelivery remains deterministic without page-load recovery.

WHY THIS LIVES IN ITS OWN MODULE (NOT tests/test_resume_pipeline.py):
tests/test_resume_pipeline.py carries a MODULE-LEVEL conditional-skip marker
gated on `os.environ.get("DATABASE_URL")` being unset. That marker silently skips
the ENTIRE module offline. This module is genuinely hermetic (fake_repo + a
monkeypatched resume spy only, no live DB/LLM) and must run unconditionally
offline, so it carries NO module-level conditional-skip marker of any kind.

WHAT THIS MODULE PROVES (assert REAL re-schedule facts, never a log string):
  1. unconsumed redelivery reschedules: a redelivered webhook whose persisted
     reply row is still unconsumed AND whose run is still awaiting_reply
     re-schedules the resume with the run_id and a reply whose body_text equals
     the PERSISTED (already-cleaned) body — never re-cleaned from the redelivered
     request, which would double-strip the quoted section.
  2. consumed redelivery no-ops: the same seed, but consumed_round is already
     set — NO re-schedule; the duplicate JSONResponse is still returned.
  3. redelivery to a non-awaiting_reply run no-ops: the reply row is unconsumed
     but the run already advanced (e.g. reconciled) — NO re-schedule.
  4. a sender-mismatched reply is never resumed by webhook redelivery. A reply
     linked by the RFC header chain but sent from an
     address that does not belong to the run's business must stay unconsumed
     forever: resuming it would let an outsider drive another business's payroll.
"""
from __future__ import annotations

import ast
import copy
import inspect
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import repo
from app.models.contracts import InboundEmail
from app.models.job import JobKind
from app.models.status import RunStatus
from app.queue import drain
from app.queue.drain import DrainOutcome

COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"


def test_supported_recovery_entry_points_exclude_runs_list() -> None:
    """Recovery remains explicit and durable; no test preserves list-page recovery."""
    import app.ingest as ingest_service
    import app.queue.handlers.operator_resume as operator_resume
    import app.queue.handlers.resume_reply as resume_reply
    import app.routes.runs as runs_module
    import app.routes.webhook as webhook_module

    test_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    test_names = {
        node.name for node in ast.walk(test_tree) if isinstance(node, ast.FunctionDef)
    }
    assert not any(name.startswith("test_runs_list_") for name in test_names)

    supported_sources = {
        "durable_receipt": inspect.getsource(webhook_module),
        "delayed_redelivery": inspect.getsource(ingest_service),
        "durable_reply_resume": inspect.getsource(resume_reply.handle_resume_reply),
        "durable_operator_resume": inspect.getsource(
            operator_resume.handle_operator_resume
        ),
    }
    assert "JobKind.INGEST" in supported_sources["durable_receipt"]
    assert "JobKind.RESUME_REPLY" in supported_sources["delayed_redelivery"]
    assert "row_to_inbound" in supported_sources["durable_reply_resume"]
    assert (
        "prepare_authoritative_operator_resume"
        in supported_sources["durable_operator_resume"]
    )
    assert "enqueue_job" not in inspect.getsource(runs_module.runs_list)


@pytest.fixture
def client(fake_repo, monkeypatch):
    """TestClient with ALLOW_UNSIGNED_FIXTURES=true so canonical dict POSTs
    succeed in mocked tests (matches tests/test_threading.py's client fixture)."""
    from app.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    events = {}

    def _insert_or_get(*, external_event_id, payload, conn=None):
        for event in events.values():
            if event["external_event_id"] == external_event_id:
                return event["id"], False
        event_id = uuid.uuid4()
        events[event_id] = {
            "id": event_id,
            "external_event_id": external_event_id,
            "payload": payload,
        }
        return event_id, True

    def _load(event_id, conn=None):
        event = events.get(event_id)
        return None if event is None else {"id": event["id"], "payload": event["payload"]}

    monkeypatch.setattr(repo, "insert_or_get_inbound_event", _insert_or_get)
    monkeypatch.setattr(repo, "load_inbound_event", _load)
    yield TestClient(app)
    get_settings.cache_clear()


@pytest.fixture
def resume_spy(monkeypatch):
    """Fail closed if a request crosses an explicit pipeline value seam inline."""
    import app.routes.pipeline_glue as pipeline_glue_mod

    calls: list[tuple[object, ...]] = []

    def _spy(*args, **kwargs):
        calls.append(args)
        pytest.fail("request executed a pipeline value seam inline")

    monkeypatch.setattr(pipeline_glue_mod, "resume_pipeline_now", _spy)
    monkeypatch.setattr(pipeline_glue_mod, "run_pipeline_now", _spy)
    return calls


def _pending_resume_jobs(fake_repo) -> list[dict[str, Any]]:
    return [
        job
        for job in fake_repo.jobs.values()
        if job["kind"] == JobKind.RESUME_REPLY.value and job["state"] == "pending"
    ]


def _seed_awaiting_reply_run_with_reply(
    fake_repo,
    *,
    message_id: str,
    consumed: bool = False,
    run_status: str = "awaiting_reply",
    reply_from_addr: str | None = None,
) -> tuple[uuid.UUID, dict[str, Any]]:
    """Seed a run + a persisted, LINKED inbound reply row against it.

    Mirrors the real webhook's insert_inbound_email + link_email_to_run sequence and
    the exact shape get_inbound_by_message_id reads at runtime. Returns (run_id, row).

    `reply_from_addr` overrides the LINKED REPLY row's from_addr only — the run's
    owning business is still seeded via COASTAL_EMAIL/COASTAL_BIZ_ID, which is
    what lets a caller construct a sender-MISMATCHED reply. It defaults to
    COASTAL_EMAIL (sender-matching), so callers that omit it get the ordinary
    same-sender reply.
    """
    src_eid, _ = fake_repo.insert_inbound_email(
        message_id=f"<{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular",
    )
    run_id = fake_repo.create_run(business_id=COASTAL_BIZ_ID, source_email_id=src_eid)
    fake_repo.set_status(run_id, RunStatus(run_status))

    reply_eid, _ = fake_repo.insert_inbound_email(
        message_id=message_id,
        in_reply_to="<clarify-msg@payroll-agent.local>",
        references_header="<clarify-msg@payroll-agent.local>",
        subject="Re: payroll hours",
        from_addr=reply_from_addr if reply_from_addr is not None else COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen, correct spelling, 40 regular",
    )
    fake_repo.link_email_to_run(reply_eid, run_id)
    row = fake_repo.emails[message_id]
    if consumed:
        fake_repo.mark_reply_consumed(message_id, round=0)
    return run_id, row


# ---------------------------------------------------------------------------
# 1. unconsumed redelivery reschedules
# ---------------------------------------------------------------------------


def test_unconsumed_redelivery_reschedules(client, fake_repo, resume_spy):
    """A redelivered webhook for a reply message_id whose persisted row is
    still unconsumed AND whose run is still awaiting_reply must re-schedule
    _resume_pipeline with the run_id and a reply whose body_text equals the
    PERSISTED (already-cleaned) body — never re-cleaned from this request."""
    message_id = f"<redeliver-{uuid.uuid4()}@metrodeli.example>"
    run_id, row = _seed_awaiting_reply_run_with_reply(
        fake_repo, message_id=message_id, consumed=False
    )

    # A redelivery: the SAME message_id arrives again. insert_inbound_email's
    # ON CONFLICT DO NOTHING means this is classified "duplicate" by the
    # webhook (mirrors the real DB's uq_message_id behavior — InMemoryRepo's
    # insert_inbound_email already returns (None, False) on a seen message_id).
    redelivered_payload = InboundEmail(
        id=uuid.uuid4(),
        message_id=message_id,
        in_reply_to="<clarify-msg@payroll-agent.local>",
        references_header="<clarify-msg@payroll-agent.local>",
        subject="Re: payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        # Deliberately DIFFERENT body text than what was persisted — proves the
        # re-schedule uses the PERSISTED row, never re-cleans this request body.
        body_text="a completely different redelivered body — must be ignored",
        created_at=datetime.now(UTC),
    ).model_dump(mode="json")

    r = client.post("/webhook/inbound", json=redelivered_payload)
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    assert resume_spy == []
    assert drain.drain_once() is DrainOutcome.DONE

    jobs = _pending_resume_jobs(fake_repo)
    assert len(jobs) == 1
    assert jobs[0]["run_id"] == run_id
    assert jobs[0]["email_id"] == row["id"]
    assert jobs[0]["operator_resolution_id"] is None
    assert jobs[0]["dedup_key"] == f"resume_reply:{run_id}:{row['id']}"
    persisted = fake_repo.get_inbound_email_by_id(jobs[0]["email_id"])
    assert persisted is not None and persisted["body_text"] == row["body_text"]
    assert persisted["body_text"] != redelivered_payload["body_text"]


# ---------------------------------------------------------------------------
# 2. consumed redelivery no-ops
# ---------------------------------------------------------------------------


def test_consumed_redelivery_no_ops(client, fake_repo, resume_spy):
    """A redelivery of an ALREADY-consumed reply must NOT re-schedule — the
    duplicate JSONResponse is still returned unchanged."""
    message_id = f"<redeliver-consumed-{uuid.uuid4()}@metrodeli.example>"
    run_id, _row = _seed_awaiting_reply_run_with_reply(
        fake_repo, message_id=message_id, consumed=True
    )

    redelivered_payload = InboundEmail(
        id=uuid.uuid4(),
        message_id=message_id,
        in_reply_to="<clarify-msg@payroll-agent.local>",
        references_header="<clarify-msg@payroll-agent.local>",
        subject="Re: payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="redelivered body",
        created_at=datetime.now(UTC),
    ).model_dump(mode="json")

    r = client.post("/webhook/inbound", json=redelivered_payload)
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    assert drain.drain_once() is DrainOutcome.DONE

    assert resume_spy == [], (
        "a redelivery of an ALREADY-consumed reply must stay a no-op — "
        f"got {len(resume_spy)} unexpected re-schedule(s)"
    )
    assert _pending_resume_jobs(fake_repo) == []


# ---------------------------------------------------------------------------
# 3. redelivery to a non-awaiting_reply run no-ops
# ---------------------------------------------------------------------------


def test_redelivery_to_non_awaiting_reply_run_no_ops(client, fake_repo, resume_spy):
    """An unconsumed reply row whose run has already advanced (e.g.
    reconciled) must NOT be re-scheduled on redelivery."""
    message_id = f"<redeliver-advanced-{uuid.uuid4()}@metrodeli.example>"
    run_id, _row = _seed_awaiting_reply_run_with_reply(
        fake_repo, message_id=message_id, consumed=False, run_status="reconciled"
    )

    redelivered_payload = InboundEmail(
        id=uuid.uuid4(),
        message_id=message_id,
        in_reply_to="<clarify-msg@payroll-agent.local>",
        references_header="<clarify-msg@payroll-agent.local>",
        subject="Re: payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="redelivered body",
        created_at=datetime.now(UTC),
    ).model_dump(mode="json")

    r = client.post("/webhook/inbound", json=redelivered_payload)
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    assert drain.drain_once() is DrainOutcome.DONE

    assert resume_spy == [], (
        "a redelivery whose linked run is NOT awaiting_reply must NOT "
        f"re-schedule; got {len(resume_spy)} unexpected re-schedule(s)"
    )
    assert _pending_resume_jobs(fake_repo) == []


# ---------------------------------------------------------------------------
# 4. A sender-mismatched linked reply is NEVER resumed by redelivery
# ---------------------------------------------------------------------------

SPOOFED_FROM_ADDR = "attacker@evil.example"


def test_redelivery_never_resumes_sender_mismatched_reply(client, fake_repo, resume_spy):
    """A reply linked to a run via the RFC header chain, but whose from_addr does
    NOT belong to the run's business, must NEVER be resumed by a subsequent
    redelivery of the same message_id.

    Such a reply failed sender revalidation on first delivery and was left linked
    but unconsumed. The redelivery path must re-assert the sender check, not just
    consumed_round/status: checking only those would let an outsider who can guess
    or observe a message_id drive another business's payroll on the retry."""
    message_id = f"<redeliver-spoofed-{uuid.uuid4()}@metrodeli.example>"
    run_id, _row = _seed_awaiting_reply_run_with_reply(
        fake_repo,
        message_id=message_id,
        consumed=False,
        reply_from_addr=SPOOFED_FROM_ADDR,
    )

    redelivered_payload = InboundEmail(
        id=uuid.uuid4(),
        message_id=message_id,
        in_reply_to="<clarify-msg@payroll-agent.local>",
        references_header="<clarify-msg@payroll-agent.local>",
        subject="Re: payroll hours",
        from_addr=SPOOFED_FROM_ADDR,
        to_addr="agent@payroll-agent.local",
        body_text="redelivered body",
        created_at=datetime.now(UTC),
    ).model_dump(mode="json")

    r = client.post("/webhook/inbound", json=redelivered_payload)
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    assert drain.drain_once() is DrainOutcome.DONE

    assert resume_spy == [], (
        "a reply that failed sender revalidation must NEVER be resumed via "
        f"redelivery; got {len(resume_spy)} unexpected re-schedule(s)"
    )
    assert _pending_resume_jobs(fake_repo) == []
    assert str(run_id) in fake_repo.runs, "sanity: run must exist and be untouched"


def test_simulated_reply_persists_one_identifier_only_job_and_never_runs_inline(
    client, fake_repo, resume_spy, monkeypatch
) -> None:
    """The demo affordance uses the same durable reply producer as real mail."""
    from app.models.job import JobKind
    from app.queue import wake

    source_id, inserted = fake_repo.insert_inbound_email(
        message_id=f"<source-{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular",
    )
    assert inserted and source_id is not None
    run_id = fake_repo.create_run(
        business_id=COASTAL_BIZ_ID,
        source_email_id=source_id,
    )
    fake_repo.set_status(run_id, RunStatus.AWAITING_REPLY)
    clarification_id = "<clarify@payroll-agent.local>"
    fake_repo.outbound[str(run_id)] = [
        {
            "message_id": clarification_id,
            "direction": "outbound",
            "purpose": "clarification",
            "send_state": "sent",
            "round": 0,
        }
    ]
    wakes: list[str] = []
    monkeypatch.setattr(wake, "wake", lambda: wakes.append("wake"))

    response = client.post(
        f"/runs/{run_id}/simulate-reply",
        data={"reply_body": "Maria Chen 40 regular, confirmed"},
    )

    assert response.status_code in (200, 303)
    assert resume_spy == []
    assert wakes == ["wake"]
    jobs = [
        job
        for job in fake_repo.jobs.values()
        if job["kind"] == JobKind.RESUME_REPLY.value
    ]
    assert len(jobs) == 1
    job = jobs[0]
    assert job["run_id"] == run_id
    assert job["email_id"] is not None
    assert job["operator_resolution_id"] is None
    assert job["event_id"] is None
    assert job["dedup_key"] == f"resume_reply:{run_id}:{job['email_id']}"
    assert "Maria Chen" not in repr(job)


def test_persisted_reply_redelivery_ensures_the_same_deduplicated_job(
    fake_repo,
) -> None:
    """RFC redelivery rehydrates the row and cannot create a second resume job."""
    from app.routes import pipeline_glue

    source_id, inserted = fake_repo.insert_inbound_email(
        message_id=f"<source-{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular",
    )
    assert inserted and source_id is not None
    run_id = fake_repo.create_run(
        business_id=COASTAL_BIZ_ID,
        source_email_id=source_id,
    )
    fake_repo.set_status(run_id, RunStatus.AWAITING_REPLY)
    clarification_id = "<clarify-redelivery@payroll-agent.local>"
    fake_repo.outbound[str(run_id)] = [
        {
            "message_id": clarification_id,
            "direction": "outbound",
            "purpose": "clarification",
            "send_state": "sent",
            "round": 0,
        }
    ]
    message_id = f"<reply-{uuid.uuid4()}@test.example>"
    reply = InboundEmail(
        id=uuid.uuid4(),
        message_id=message_id,
        in_reply_to=clarification_id,
        references_header=clarification_id,
        subject="Re: payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular, confirmed",
        created_at=datetime.now(UTC),
    )

    first = pipeline_glue.persist_and_enqueue_reply(
        reply, reply.body_text, conn=object()
    )
    duplicate = pipeline_glue.persist_and_enqueue_reply(
        reply, "hostile redelivery body must be ignored", conn=object()
    )

    assert first.should_wake is True
    assert duplicate.should_wake is True
    assert len(fake_repo.jobs) == 1
    job = next(iter(fake_repo.jobs.values()))
    persisted = fake_repo.emails[message_id]
    assert job["dedup_key"] == f"resume_reply:{run_id}:{persisted['id']}"
    assert persisted["body_text"] == reply.body_text


def test_simulated_reply_enqueue_failure_rolls_back_email_and_never_wakes(
    client, fake_repo, monkeypatch
) -> None:
    """The reply row and owed job share one rollback boundary."""
    import app.db.repo as repo_module
    from app.queue import wake

    source_id, inserted = fake_repo.insert_inbound_email(
        message_id=f"<source-{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular",
    )
    assert inserted and source_id is not None
    run_id = fake_repo.create_run(
        business_id=COASTAL_BIZ_ID,
        source_email_id=source_id,
    )
    fake_repo.set_status(run_id, RunStatus.AWAITING_REPLY)
    clarification_id = "<clarify-rollback@payroll-agent.local>"
    fake_repo.outbound[str(run_id)] = [
        {
            "message_id": clarification_id,
            "direction": "outbound",
            "purpose": "clarification",
            "send_state": "sent",
            "round": 0,
        }
    ]
    before_email_ids = set(fake_repo.email_by_id)

    class _SnapshotTransaction:
        def __enter__(self):
            self.snapshot = copy.deepcopy(
                (
                    fake_repo.emails,
                    fake_repo.email_by_id,
                    fake_repo.jobs,
                    fake_repo._job_dedup_keys,
                )
            )
            return self

        def __exit__(self, exc_type, _exc, _tb):
            if exc_type is not None:
                (
                    fake_repo.emails,
                    fake_repo.email_by_id,
                    fake_repo.jobs,
                    fake_repo._job_dedup_keys,
                ) = self.snapshot
            return False

    class _SnapshotConnection:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def transaction(self):
            return _SnapshotTransaction()

    monkeypatch.setattr(
        repo_module,
        "get_connection",
        lambda: _SnapshotConnection(),
    )
    monkeypatch.setattr(
        repo_module,
        "enqueue_job",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("injected")),
    )
    wakes: list[str] = []
    monkeypatch.setattr(wake, "wake", lambda: wakes.append("wake"))

    response = client.post(
        f"/runs/{run_id}/simulate-reply",
        data={"reply_body": "Maria Chen 40 regular, confirmed"},
    )

    assert response.status_code in (200, 303)
    assert set(fake_repo.email_by_id) == before_email_ids
    assert fake_repo.jobs == {}
    assert wakes == []
