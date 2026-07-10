"""Webhook ingest tests (INGEST-01/02/03, DEMO-01 clean half).

The dedupe + unknown-sender tests run offline via the in-memory `fake_repo`. The
end-to-end `test_post_fixture_reaches_pause` relies on TestClient running
BackgroundTasks SYNCHRONOUSLY (RESEARCH §Pattern 1) so it can assert the run
reached awaiting_approval immediately after POST — no server, no sleeps. It is RED
until Tasks 2-4 land the stages, the gate, the calc, and the orchestrator.
"""
from __future__ import annotations

import json
import pathlib
import uuid
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

_FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "clean_happy_path.json"


def _fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_FIXTURE.read_text()))


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
    """Enqueue ONLY the extraction payload for the all-deterministic happy path
    (Maria Chen + James Okafor both resolve exactly). reconcile and decide are pure
    deterministic code with no LLM call (D-21-01), so no decision response is
    scripted — the gate runs on the resolution facts."""
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


# ---------------------------------------------------------------------------
# INGEST-01 / FOUND-02 — duplicate delivery is idempotent (no second run)
# ---------------------------------------------------------------------------


def test_duplicate_delivery_idempotent(client, fake_repo, mock_llm):
    _script_clean_run(mock_llm)
    payload = _fixture()

    r1 = client.post("/webhook/inbound", json=payload)
    assert r1.status_code == 200

    # Re-script for any pipeline run the second POST might trigger (it must not).
    _script_clean_run(mock_llm)
    r2 = client.post("/webhook/inbound", json=payload)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"

    # Exactly one run was created despite two identical deliveries.
    assert len(fake_repo.runs) == 1


# ---------------------------------------------------------------------------
# INGEST-03 — unknown sender is logged + stopped, no run created
# ---------------------------------------------------------------------------


def test_unknown_sender_no_run(client, fake_repo, mock_llm):
    payload = _fixture()
    payload["message_id"] = "<unknown-sender-001@nowhere.test>"
    payload["from_addr"] = "stranger@nowhere.test"  # matches no businesses.contact_email

    r = client.post("/webhook/inbound", json=payload)
    assert r.status_code == 200
    assert r.json()["status"] == "unknown_sender"
    assert len(fake_repo.runs) == 0, "unknown sender must create NO run (INGEST-03)"


# ---------------------------------------------------------------------------
# DATA-02 (D-9-09) — the duplicate-response body reports the existing run_id
# ---------------------------------------------------------------------------


def test_duplicate_delivery_reports_existing_run_id(client, fake_repo, mock_llm):
    """The loser attaches to the existing run: report, never create (D-9-09)."""
    _script_clean_run(mock_llm)
    payload = _fixture()

    r1 = client.post("/webhook/inbound", json=payload)
    assert r1.status_code == 200
    run_id = r1.json()["run_id"]

    _script_clean_run(mock_llm)
    r2 = client.post("/webhook/inbound", json=payload)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"
    assert r2.json()["run_id"] == run_id, (
        "duplicate response must report the EXISTING run's id (D-9-09) — the "
        "loser attaches to the winner's run instead of creating a second one"
    )
    assert len(fake_repo.runs) == 1


# ---------------------------------------------------------------------------
# Codex HIGH-1 regression guard — a header-bearing reply NEVER spuriously
# creates a second run under the restructured transactional ingest (09-03)
# ---------------------------------------------------------------------------


def test_reply_never_creates_second_run(client, fake_repo, mock_llm):
    """A clarification reply resumes its run — it must NEVER open a second one.

    Seeds a run directly at awaiting_reply with a stored outbound clarification
    Message-ID (bypassing the normal pipeline, mirroring
    tests/test_resume_pipeline.py's _seed_run/_set_run_awaiting_reply helpers),
    then POSTs a reply carrying matching In-Reply-To/References headers. The
    restructured ingest transaction must classify this as a reply-resume
    candidate BEFORE create_run is ever reachable — proving Codex HIGH-1 is closed.
    """
    from app.models.status import RunStatus

    coastal_email = "payroll@coastalcleaning.example"

    # Seed the original inbound + run directly in the fake repo.
    orig_eid, _ = fake_repo.insert_inbound_email(
        message_id="<orig-001@acme.test>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=coastal_email,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular hours.",
    )
    business_id = fake_repo.find_business_by_sender(coastal_email)
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=orig_eid)

    # Stash a stored outbound clarification Message-ID + park the run at
    # awaiting_reply (mirrors _set_run_awaiting_reply in test_resume_pipeline.py).
    clar_message_id = "<clarify-001@payroll-agent.local>"
    fake_repo.insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=clar_message_id,
        purpose="clarification",
        send_state="sent",
    )
    fake_repo.runs[str(run_id)]["status"] = RunStatus.AWAITING_REPLY.value

    assert len(fake_repo.runs) == 1

    # POST a reply carrying headers that match the stored outbound Message-ID.
    reply_payload = {
        "id": str(uuid.uuid4()),
        "message_id": "<reply-001@acme.test>",
        "in_reply_to": clar_message_id,
        "references_header": clar_message_id,
        "subject": "Re: payroll hours",
        "from_addr": coastal_email,
        "to_addr": "agent@payroll-agent.local",
        "body_text": "Maria Chen actually worked 42 hours.",
        "created_at": "2026-06-16T09:30:00Z",
    }
    r = client.post("/webhook/inbound", json=reply_payload)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "resumed"
    assert body["run_id"] == str(run_id)

    # EXACTLY ONE run total — the reply must NEVER spuriously create a second
    # run (Codex HIGH-1, closed by classifying reply-vs-new-run INSIDE the
    # ingest transaction, strictly before create_run is reachable).
    assert len(fake_repo.runs) == 1, (
        "a header-bearing reply must NEVER create a second run — the reply-"
        "classification-before-create_run ordering must hold (Codex HIGH-1)"
    )


# ---------------------------------------------------------------------------
# Late-reply regression guard — header match to a non-awaiting_reply run
# ---------------------------------------------------------------------------


def test_late_reply_no_new_run_no_background_task(client, fake_repo, mock_llm, monkeypatch):
    """A header match to a run NOT in awaiting_reply is a late reply: no new run,
    no background task scheduled (FIX 10, Codex HIGH-1 regression guard)."""
    from app.models.status import RunStatus

    coastal_email = "payroll@coastalcleaning.example"

    orig_eid, _ = fake_repo.insert_inbound_email(
        message_id="<orig-002@acme.test>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=coastal_email,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular hours.",
    )
    business_id = fake_repo.find_business_by_sender(coastal_email)
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=orig_eid)

    clar_message_id = "<clarify-002@payroll-agent.local>"
    fake_repo.insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=clar_message_id,
        purpose="clarification",
        send_state="sent",
    )
    # Run has already ADVANCED past awaiting_reply (e.g. sent) — a header match
    # here is a LATE reply, not a resume candidate.
    fake_repo.runs[str(run_id)]["status"] = RunStatus.SENT.value

    called = {"resume": False, "run": False}
    monkeypatch.setattr(
        "app.routes.pipeline_glue.resume_pipeline_bg",
        lambda *a, **k: called.__setitem__("resume", True),
    )
    monkeypatch.setattr(
        "app.routes.pipeline_glue.run_pipeline_bg",
        lambda *a, **k: called.__setitem__("run", True),
    )

    reply_payload = {
        "id": str(uuid.uuid4()),
        "message_id": "<reply-002@acme.test>",
        "in_reply_to": clar_message_id,
        "references_header": clar_message_id,
        "subject": "Re: payroll hours",
        "from_addr": coastal_email,
        "to_addr": "agent@payroll-agent.local",
        "body_text": "Maria Chen actually worked 42 hours.",
        "created_at": "2026-06-16T09:30:00Z",
    }
    r = client.post("/webhook/inbound", json=reply_payload)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "late_reply"
    assert body["run_id"] == str(run_id)

    # No new run created (only the original one exists).
    assert len(fake_repo.runs) == 1
    # No background task scheduled (neither resume nor a fresh run pipeline).
    assert called["resume"] is False
    assert called["run"] is False


# ---------------------------------------------------------------------------
# WR-03 (phase-9 review) — real reply/late-reply rows are LINKED to their run
# inside the ingest transaction, so the run-detail thread view shows them
# ---------------------------------------------------------------------------


def test_reply_and_late_reply_rows_linked_to_run(client, fake_repo, mock_llm, monkeypatch):
    """The ingest transaction back-fills run_id on classified reply rows (WR-03).

    Before the fix, every real inbound reply row kept run_id=NULL forever (only
    the simulate-reply demo path passed run_id), so real client replies were
    invisible in load_thread_messages' run-detail thread view. Both classified
    outcomes must link: reply_candidate AND late_reply.
    """
    from app.models.status import RunStatus

    coastal_email = "payroll@coastalcleaning.example"

    orig_eid, _ = fake_repo.insert_inbound_email(
        message_id="<orig-003@acme.test>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=coastal_email,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular hours.",
    )
    business_id = fake_repo.find_business_by_sender(coastal_email)
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=orig_eid)

    clar_message_id = "<clarify-003@payroll-agent.local>"
    fake_repo.insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=clar_message_id,
        purpose="clarification",
        send_state="sent",
    )
    # Keep the resume out of the way — this test asserts the LINK, not the resume.
    monkeypatch.setattr("app.routes.pipeline_glue.resume_pipeline_bg", lambda *a, **k: None)

    # 1) reply_candidate: run parked at awaiting_reply → reply row must link.
    fake_repo.runs[str(run_id)]["status"] = RunStatus.AWAITING_REPLY.value
    reply_mid = "<reply-003@acme.test>"
    r = client.post(
        "/webhook/inbound",
        json={
            "id": str(uuid.uuid4()),
            "message_id": reply_mid,
            "in_reply_to": clar_message_id,
            "references_header": clar_message_id,
            "subject": "Re: payroll hours",
            "from_addr": coastal_email,
            "to_addr": "agent@payroll-agent.local",
            "body_text": "Maria Chen actually worked 42 hours.",
            "created_at": "2026-06-16T09:30:00Z",
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "resumed"
    assert str(fake_repo.emails[reply_mid].get("run_id")) == str(run_id), (
        "a reply_candidate row must be back-filled with its run_id inside the "
        "ingest transaction (WR-03) — otherwise real replies never appear in "
        "the run-detail thread view"
    )

    # 2) late_reply: run already advanced → the late row must ALSO link.
    fake_repo.runs[str(run_id)]["status"] = RunStatus.SENT.value
    late_mid = "<reply-004@acme.test>"
    r = client.post(
        "/webhook/inbound",
        json={
            "id": str(uuid.uuid4()),
            "message_id": late_mid,
            "in_reply_to": clar_message_id,
            "references_header": clar_message_id,
            "subject": "Re: payroll hours",
            "from_addr": coastal_email,
            "to_addr": "agent@payroll-agent.local",
            "body_text": "One more thing — add 2 vacation hours for Maria.",
            "created_at": "2026-06-17T09:30:00Z",
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "late_reply"
    assert str(fake_repo.emails[late_mid].get("run_id")) == str(run_id), (
        "a late_reply row must be back-filled with its run_id inside the "
        "ingest transaction (WR-03) — join-based audits must see it"
    )


# ---------------------------------------------------------------------------
# INGEST-01 / HITL-01 / DEMO-01 — the marquee end-to-end pause
# ---------------------------------------------------------------------------


def test_post_fixture_reaches_pause(client, fake_repo, mock_llm):
    _script_clean_run(mock_llm)

    r = client.post("/webhook/inbound", json=_fixture())
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"

    # TestClient ran the BackgroundTask synchronously → the run is already paused.
    assert len(fake_repo.runs) == 1
    run = next(iter(fake_repo.runs.values()))
    assert run["status"] == "awaiting_approval", (
        f"clean fixture must reach awaiting_approval end-to-end, got {run['status']}"
    )
    # The clean process path persists decision + reconciliation + extracted.
    assert run["decision"] is not None
    assert run["decision"]["final_action"] == "process"
    assert run["reconciliation"] is not None
    assert run["extracted_data"] is not None
