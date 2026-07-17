"""RFC Message-ID dedup race through durable receipt and delayed ingest.

Two real OS threads commit distinct transport events carrying one RFC ``message_id``.
Two more barrier-released threads then drive the committed event identifiers through
the real delayed-ingest handler against Postgres. Exactly one email, run, and downstream
RUN_PIPELINE job may survive the RFC-identity race.

Skip-guarded on DATABASE_URL (matches test_claim_status.py's exact skip shape).
This is a SEPARATE test module from tests/test_webhook.py and does NOT inherit
that module's client fixture's env setup — pytest does not share monkeypatch
state across test modules, so this module sets ALLOW_UNSIGNED_FIXTURES=true
itself before constructing its own TestClient, or every POST would 400 on
signature rejection before ever reaching the dedup-insert logic this test exists
to prove.
"""
from __future__ import annotations

import os
import threading
import uuid
from typing import Any

import pytest


@pytest.mark.integration
def test_duplicate_webhook_delivery_creates_exactly_one_run(monkeypatch):
    """Distinct transport events with one RFC identity create exactly one run."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — skipping live-DB integration test")

    from app.config import get_settings

    get_settings.cache_clear()
    # Mirrors tests/test_webhook.py's client fixture pattern verbatim. This module does
    # NOT inherit that fixture's env setup, so every POST here would otherwise receive a
    # 400 (unsigned webhook rejected) before ever reaching the dedup-insert logic this
    # test exists to prove.
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")

    from fastapi.testclient import TestClient

    import app.main as app_main
    import app.routes.pipeline_glue as pipeline_glue_mod
    from app.db import repo
    from app.email import gateway
    from app.models.job import Job, JobKind
    from app.queue import wake
    from app.queue.handlers import ingest as ingest_handler
    from app.queue.handlers import pipeline, resume_reply

    real_parse_inbound = gateway.parse_inbound
    real_handle_ingest = ingest_handler.handle_ingest

    def _forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("webhook request executed provider or payroll work inline")

    monkeypatch.setattr(gateway, "parse_inbound", _forbidden)
    monkeypatch.setattr(pipeline_glue_mod, "run_pipeline_now", _forbidden)
    monkeypatch.setattr(pipeline_glue_mod, "resume_pipeline_now", _forbidden)
    monkeypatch.setattr(ingest_handler, "handle_ingest", _forbidden)
    monkeypatch.setattr(pipeline, "handle_run_pipeline", _forbidden)
    monkeypatch.setattr(resume_reply, "handle_resume_reply", _forbidden)
    wakes: list[str] = []
    monkeypatch.setattr(wake, "wake", lambda: wakes.append("wake"))

    client = TestClient(app_main.app)

    same_message_id = f"<race-{uuid.uuid4()}@acme.test>"
    def _payload() -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "message_id": same_message_id,
            "in_reply_to": None,
            "references_header": None,
            "subject": "Payroll hours",
            "from_addr": "payroll@coastalcleaning.example",
            "to_addr": "agent@payroll-agent.local",
            "body_text": "Maria Chen 40 regular hours.",
            "created_at": "2026-06-15T10:00:00Z",
        }

    payloads = [_payload(), _payload()]

    results: list[dict[str, Any]] = []
    lock = threading.Lock()

    request_barrier = threading.Barrier(2, timeout=30)

    def _post(payload: dict[str, Any]) -> None:
        request_barrier.wait()
        r = client.post("/webhook/inbound", json=payload)
        with lock:
            results.append({"status_code": r.status_code, **r.json()})

    t1 = threading.Thread(target=_post, args=(payloads[0],))
    t2 = threading.Thread(target=_post, args=(payloads[1],))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(results) == 2
    assert {r["status_code"] for r in results} == {200}
    assert {r["status"] for r in results} == {"accepted"}
    event_ids = {uuid.UUID(r["event_id"]) for r in results}
    assert len(event_ids) == 2, "the request race must commit two transport identities"
    assert len(wakes) == 2

    with repo.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, kind, run_id, email_id, operator_resolution_id, event_id,
                   attempts, max_attempts, lease_token, dedup_key, state
              FROM jobs
             WHERE event_id = ANY(%s)
            """,
            (list(event_ids),),
        ).fetchall()
    assert len(rows) == 2
    assert {row[1] for row in rows} == {JobKind.INGEST.value}
    assert {uuid.UUID(str(row[5])) for row in rows} == event_ids
    assert {row[9] for row in rows} == {f"ingest:{event_id}" for event_id in event_ids}
    assert {row[10] for row in rows} == {"pending"}
    assert all(row[2] is None and row[3] is None and row[4] is None for row in rows)

    monkeypatch.setattr(gateway, "parse_inbound", real_parse_inbound)
    monkeypatch.setattr(ingest_handler, "handle_ingest", real_handle_ingest)
    ingest_jobs = [
        Job(
            id=uuid.UUID(str(row[0])),
            kind=JobKind.INGEST,
            run_id=None,
            email_id=None,
            operator_resolution_id=None,
            event_id=uuid.UUID(str(row[5])),
            attempts=int(row[6]),
            max_attempts=int(row[7]),
            lease_token=(
                uuid.UUID(str(row[8])) if row[8] is not None else uuid.uuid4()
            ),
        )
        for row in rows
    ]
    ingest_barrier = threading.Barrier(2, timeout=30)
    handler_results = []

    def _process(job: Job) -> None:
        ingest_barrier.wait()
        result = real_handle_ingest(job)
        with lock:
            handler_results.append(result)

    workers = [threading.Thread(target=_process, args=(job,)) for job in ingest_jobs]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert len(handler_results) == 2
    assert {result.outcome.value for result in handler_results} == {"ok"}

    with repo.get_connection() as conn:
        email_row = conn.execute(
            "SELECT id, count(*) OVER () FROM email_messages WHERE message_id = %s",
            (same_message_id,),
        ).fetchone()
        assert email_row is not None and email_row[1] == 1
        run_rows = conn.execute(
            "SELECT id FROM payroll_runs WHERE source_email_id = %s",
            (email_row[0],),
        ).fetchall()
        pipeline_rows = conn.execute(
            """
            SELECT kind, dedup_key, run_id, email_id, operator_resolution_id, event_id
              FROM jobs
             WHERE kind = 'run_pipeline' AND run_id = ANY(%s)
            """,
            ([row[0] for row in run_rows],),
        ).fetchall()
    assert len(run_rows) == 1
    run_id = uuid.UUID(str(run_rows[0][0]))
    assert pipeline_rows == [
        (JobKind.RUN_PIPELINE.value, f"run_pipeline:{run_id}:0", run_id, None, None, None)
    ]

    get_settings.cache_clear()


@pytest.mark.integration
def test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run(
    monkeypatch,
):
    """One authenticated transport identity stays singular across a DB race."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — skipping live-DB integration test")

    from fastapi.testclient import TestClient

    import app.main as app_main
    from app.config import get_settings
    from app.db import repo
    from app.email import gateway
    from app.models.job import Job, JobKind
    from app.queue import wake
    from app.queue.handlers import ingest as ingest_handler

    get_settings.cache_clear()
    event_key = f"evt_same_svix_{uuid.uuid4()}"
    message_id = f"<same-svix-{uuid.uuid4()}@acme.test>"
    payload = {
        "id": str(uuid.uuid4()),
        "message_id": message_id,
        "in_reply_to": None,
        "references_header": None,
        "subject": "Payroll hours",
        "from_addr": "payroll@coastalcleaning.example",
        "to_addr": "agent@payroll-agent.local",
        "body_text": "Maria Chen 40 regular hours.",
        "created_at": "2026-06-15T10:00:00Z",
    }
    monkeypatch.setattr(gateway, "verify", lambda body, headers, secret: None)
    wakes: list[str] = []
    monkeypatch.setattr(wake, "wake", lambda: wakes.append("wake"))
    client = TestClient(app_main.app)
    barrier = threading.Barrier(2, timeout=30)
    results: list[dict[str, Any]] = []
    lock = threading.Lock()

    def _post() -> None:
        barrier.wait()
        response = client.post(
            "/webhook/inbound",
            json=payload,
            headers={
                "svix-id": event_key,
                "svix-timestamp": "1784160000",
                "svix-signature": "v1,test",
            },
        )
        with lock:
            results.append({"status_code": response.status_code, **response.json()})

    workers = [threading.Thread(target=_post) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert len(results) == 2
    assert {result["status_code"] for result in results} == {200}
    assert {result["status"] for result in results} == {"accepted", "duplicate"}
    assert len({result["event_id"] for result in results}) == 1
    assert wakes == ["wake"]

    event_id = uuid.UUID(results[0]["event_id"])
    with repo.get_connection() as conn:
        event_count_row = conn.execute(
            "SELECT count(*) FROM inbound_events WHERE external_event_id = %s",
            (event_key,),
        ).fetchone()
        job_rows = conn.execute(
            """
            SELECT id, attempts, max_attempts, lease_token
              FROM jobs
             WHERE kind = 'ingest' AND event_id = %s
            """,
            (str(event_id),),
        ).fetchall()
    assert event_count_row is not None
    event_count = event_count_row[0]
    assert event_count == 1
    assert len(job_rows) == 1

    job_row = job_rows[0]
    result = ingest_handler.handle_ingest(
        Job(
            id=uuid.UUID(str(job_row[0])),
            kind=JobKind.INGEST,
            run_id=None,
            event_id=event_id,
            attempts=int(job_row[1]),
            max_attempts=int(job_row[2]),
            lease_token=(
                uuid.UUID(str(job_row[3]))
                if job_row[3] is not None
                else uuid.uuid4()
            ),
        )
    )
    assert result.outcome.value == "ok"

    with repo.get_connection() as conn:
        email_row = conn.execute(
            "SELECT id, count(*) OVER () FROM email_messages WHERE message_id = %s",
            (message_id,),
        ).fetchone()
        assert email_row is not None and email_row[1] == 1
        run_count_row = conn.execute(
            "SELECT count(*) FROM payroll_runs WHERE source_email_id = %s",
            (email_row[0],),
        ).fetchone()
    assert run_count_row is not None
    run_count = run_count_row[0]
    assert run_count == 1
    get_settings.cache_clear()
