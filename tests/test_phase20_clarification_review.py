"""Safety regressions for purpose-aware clarification delivery review."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.job import JobKind
from app.models.status import RunStatus

client = TestClient(app, raise_server_exceptions=False)


def _clarification_review_run(fake_repo: Any) -> tuple[uuid.UUID, dict[str, Any]]:
    business_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.AWAITING_REPLY)
    fake_repo.runs[str(run_id)]["error_reason"] = "ClarificationDeliveryReview"
    fake_repo.runs[str(run_id)]["error_detail"] = (
        "delivery_review:final_attempt_lease_expired"
    )
    fake_repo.set_status(run_id, RunStatus.NEEDS_OPERATOR)
    snapshot = fake_repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="clarification",
        round=0,
        message_id="<frozen-question@payroll-agent.local>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@example.test",
        reply_to="replies@payroll-agent.local",
        in_reply_to="<source@payroll-agent.local>",
        references_header="<prior@payroll-agent.local> <source@payroll-agent.local>",
        subject="One payroll name needs clarification",
        body_text="Which employee did you mean by D. Reyes?",
        attachments=[("frozen-question.pdf", b"frozen-question-bytes")],
    )
    fake_repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=f"send_outbound:{snapshot['email_id']}",
        run_id=run_id,
        email_id=snapshot["email_id"],
    )
    return run_id, snapshot


def test_clarification_review_loads_frozen_question_and_not_confirmation(fake_repo):
    import app.routes.runs as runs_mod

    run_id, snapshot = _clarification_review_run(fake_repo)

    loaded = runs_mod._load_delivery_review(run_id)
    assert loaded is not None
    assert loaded["review"]["purpose"] == "clarification"

    email = client.get(f"/runs/{run_id}/delivery-review/email")
    assert email.status_code == 200
    assert "One payroll name needs clarification" in email.text
    assert "Which employee did you mean by D. Reyes?" in email.text
    assert "In-Reply-To: <source@payroll-agent.local>" in email.text
    assert "References: <prior@payroll-agent.local> <source@payroll-agent.local>" in email.text
    assert snapshot["message_id"] in email.text

    fake_repo.runs[str(run_id)]["error_reason"] = "DeliveryReview"
    assert runs_mod._load_delivery_review(run_id) is None


def test_confirmation_review_does_not_load_clarification_marker(fake_repo):
    import app.routes.runs as runs_mod

    run_id, snapshot = _clarification_review_run(fake_repo)
    fake_repo.runs[str(run_id)]["error_reason"] = "DeliveryReview"
    fake_repo.runs[str(run_id)]["error_detail"] = "delivery_review:transport"
    fake_repo.outbound_snapshots[str(snapshot["email_id"])]["payload"]["purpose"] = (
        "confirmation"
    )
    fake_repo.outbound[str(run_id)][0]["purpose"] = "confirmation"
    assert runs_mod._load_delivery_review(run_id) is not None

    fake_repo.runs[str(run_id)]["error_reason"] = "ClarificationDeliveryReview"
    assert runs_mod._load_delivery_review(run_id) is None


def test_clarification_retry_uses_exact_same_row_facade_and_wakes_after_commit(
    fake_repo, monkeypatch
):
    import app.routes.runs as runs_mod

    run_id, snapshot = _clarification_review_run(fake_repo)
    job_count = len(fake_repo.jobs)
    calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    def advance(run: uuid.UUID, email: uuid.UUID, *, conn: Any = None):
        calls.append((run, email))
        return runs_mod.repo.AdvanceSendJobOutcome.ADVANCED

    monkeypatch.setattr(
        runs_mod.repo,
        "advance_existing_clarification_delivery_review_job_due_now",
        advance,
    )
    monkeypatch.setattr(
        runs_mod.repo,
        "advance_existing_send_job_due_now",
        lambda **_: pytest.fail("confirmation retry facade was used"),
    )
    wake_calls: list[None] = []
    monkeypatch.setattr(runs_mod.wake, "wake", lambda: wake_calls.append(None))

    response = client.post(
        f"/runs/{run_id}/delivery-review/clarification/retry-now",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert calls == [(run_id, snapshot["email_id"])]
    assert len(fake_repo.jobs) == job_count
    assert wake_calls == [None]


def test_clarification_retry_expired_is_a_noop(fake_repo, monkeypatch):
    import app.routes.runs as runs_mod

    run_id, snapshot = _clarification_review_run(fake_repo)
    fake_repo.outbound_snapshots[str(snapshot["email_id"])]["payload"][
        "reserved_at"
    ] = datetime.now(UTC) - timedelta(hours=21)
    wake_calls: list[None] = []
    monkeypatch.setattr(runs_mod.wake, "wake", lambda: wake_calls.append(None))

    response = client.post(
        f"/runs/{run_id}/delivery-review/clarification/retry-now",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert wake_calls == []
    assert next(iter(fake_repo.jobs.values()))["available_in_seconds"] == 0.0


def test_confirmation_retry_now_rejects_clarification_review(fake_repo, monkeypatch):
    import app.routes.runs as runs_mod

    run_id, snapshot = _clarification_review_run(fake_repo)
    job = next(iter(fake_repo.jobs.values()))
    job["available_in_seconds"] = 45.0
    before_run = dict(fake_repo.load_run(run_id))
    before_snapshot = dict(fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"]))
    before_job_count = len(fake_repo.jobs)
    generic_calls: list[tuple[uuid.UUID, uuid.UUID]] = []
    wake_calls: list[None] = []
    monkeypatch.setattr(
        runs_mod.repo,
        "advance_existing_send_job_due_now",
        lambda run, email, **_: generic_calls.append((run, email)),
    )
    monkeypatch.setattr(runs_mod.wake, "wake", lambda: wake_calls.append(None))
    monkeypatch.setattr(
        runs_mod.gateway,
        "send_outbound",
        lambda **_: pytest.fail("confirmation retry called provider"),
    )

    response = client.post(
        f"/runs/{run_id}/delivery-review/retry-now", follow_redirects=False
    )

    assert response.status_code == 303
    assert generic_calls == []
    assert wake_calls == []
    assert fake_repo.load_run(run_id) == before_run
    assert fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"]) == before_snapshot
    assert len(fake_repo.jobs) == before_job_count
    assert job["available_in_seconds"] == 45.0


def test_mark_delivery_delivered_rejects_clarification_review_without_mutation(
    fake_repo, monkeypatch
):
    import app.routes.runs as runs_mod

    run_id, snapshot = _clarification_review_run(fake_repo)
    before_run = dict(fake_repo.load_run(run_id))
    before_snapshot = dict(fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"]))
    before_job_count = len(fake_repo.jobs)
    claim_calls: list[object] = []
    wake_calls: list[None] = []
    monkeypatch.setattr(
        runs_mod.repo,
        "claim_status",
        lambda *args, **kwargs: claim_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(runs_mod.wake, "wake", lambda: wake_calls.append(None))
    monkeypatch.setattr(
        runs_mod.gateway,
        "send_outbound",
        lambda **_: pytest.fail("mark delivered called provider"),
    )

    response = client.post(
        f"/runs/{run_id}/delivery-review/mark-delivered", follow_redirects=False
    )

    assert response.status_code == 303
    assert claim_calls == []
    assert wake_calls == []
    assert fake_repo.load_run(run_id) == before_run
    assert fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"]) == before_snapshot
    assert len(fake_repo.jobs) == before_job_count


def test_authorize_new_confirmation_rejects_clarification_review_without_mutation(
    fake_repo, monkeypatch
):
    import app.routes.runs as runs_mod

    run_id, snapshot = _clarification_review_run(fake_repo)
    before_run = dict(fake_repo.load_run(run_id))
    before_snapshot = dict(fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"]))
    before_job_count = len(fake_repo.jobs)
    claim_calls: list[object] = []
    wake_calls: list[None] = []
    monkeypatch.setattr(
        runs_mod.repo,
        "claim_status",
        lambda *args, **kwargs: claim_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(runs_mod.wake, "wake", lambda: wake_calls.append(None))
    monkeypatch.setattr(
        runs_mod.gateway,
        "send_outbound",
        lambda **_: pytest.fail("authorize confirmation called provider"),
    )

    response = client.post(
        f"/runs/{run_id}/delivery-review/authorize",
        data={"acknowledgement": "AUTHORIZE A NEW CONFIRMATION"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert claim_calls == []
    assert wake_calls == []
    assert fake_repo.load_run(run_id) == before_run
    assert fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"]) == before_snapshot
    assert len(fake_repo.jobs) == before_job_count


def test_clarification_handled_and_reject_are_provider_and_alias_free(
    fake_repo, monkeypatch
):
    import app.routes.runs as runs_mod
    from app.email import gateway

    run_id, _snapshot = _clarification_review_run(fake_repo)
    monkeypatch.setattr(
        gateway,
        "send_outbound",
        lambda **_: pytest.fail("clarification review action called provider"),
    )
    monkeypatch.setattr(
        runs_mod.repo,
        "update_known_alias",
        lambda *_, **__: pytest.fail("clarification review wrote an alias"),
    )
    handled = client.post(
        f"/runs/{run_id}/delivery-review/clarification/mark-handled",
        follow_redirects=False,
    )
    assert handled.status_code == 303
    assert fake_repo.load_run(run_id)["status"] == RunStatus.AWAITING_REPLY.value

    run_id, _snapshot = _clarification_review_run(fake_repo)
    rejected = client.post(
        f"/runs/{run_id}/delivery-review/clarification/reject",
        follow_redirects=False,
    )
    assert rejected.status_code == 303
    assert fake_repo.load_run(run_id)["status"] == RunStatus.REJECTED.value


def test_delivery_review_marker_blocks_resolve_before_roster_or_alias_work(
    fake_repo, monkeypatch
):
    import app.routes.runs as runs_mod

    run_id, _snapshot = _clarification_review_run(fake_repo)
    fake_repo.runs[str(run_id)]["decision"] = {"unresolved_names": ["D. Reyes"]}
    monkeypatch.setattr(
        runs_mod.repo,
        "load_roster_for_business",
        lambda *_: pytest.fail("delivery review entered alias resolution"),
    )
    monkeypatch.setattr(
        runs_mod.repo,
        "commit_operator_resume_resolution",
        lambda *_args, **_kwargs: pytest.fail("delivery review wrote a resolution"),
    )

    response = client.post(
        f"/runs/{run_id}/resolve",
        data={"employee_id_0": "e0000001-0000-0000-0000-000000000001"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert fake_repo.load_run(run_id)["status"] == RunStatus.NEEDS_OPERATOR.value


def test_delivery_review_marker_blocks_retrigger_before_context_clear_or_enqueue(
    fake_repo, monkeypatch
):
    import app.routes.runs as runs_mod

    run_id, _snapshot = _clarification_review_run(fake_repo)
    monkeypatch.setattr(
        runs_mod.repo,
        "clear_reply_context",
        lambda *_args, **_kwargs: pytest.fail("delivery review cleared reply context"),
    )
    monkeypatch.setattr(
        runs_mod.repo,
        "enqueue_job",
        lambda *_args, **_kwargs: pytest.fail("delivery review enqueued pipeline work"),
    )
    monkeypatch.setattr(
        runs_mod.repo,
        "claim_status",
        lambda *_args, **_kwargs: pytest.fail("delivery review claimed generic recovery"),
    )

    response = client.post(f"/runs/{run_id}/retrigger", follow_redirects=False)
    assert response.status_code == 303
    assert fake_repo.load_run(run_id)["status"] == RunStatus.NEEDS_OPERATOR.value
