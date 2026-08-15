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


def _confirmation_review_run(fake_repo: Any) -> tuple[uuid.UUID, dict[str, Any]]:
    business_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.APPROVED)
    fake_repo.runs[str(run_id)]["error_reason"] = "DeliveryReview"
    fake_repo.runs[str(run_id)]["error_detail"] = "delivery_review:transport"
    fake_repo.set_status(run_id, RunStatus.NEEDS_OPERATOR)
    snapshot = fake_repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id="<frozen-confirmation@payroll-agent.local>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@example.test",
        reply_to="replies@payroll-agent.local",
        in_reply_to="<source@payroll-agent.local>",
        references_header="<prior@payroll-agent.local> <source@payroll-agent.local>",
        subject="Payroll confirmation",
        body_text="Frozen confirmation body",
        attachments=[("frozen-confirmation.pdf", b"frozen-confirmation-bytes")],
    )
    fake_repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=f"send_outbound:{snapshot['email_id']}",
        run_id=run_id,
        email_id=snapshot["email_id"],
    )
    return run_id, snapshot


def _attach_active_handoff(fake_repo: Any, run_id: uuid.UUID, snapshot: dict[str, Any]):
    handoff = {
        "id": uuid.uuid4(),
        "run_id": run_id,
        "email_id": snapshot["email_id"],
        "snapshot_id": snapshot["snapshot_id"],
        "released_at": None,
        "release_reason": None,
    }
    fake_repo.outbound_provider_handoffs[str(handoff["id"])] = handoff
    return handoff


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
    from app.email import gateway

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
        gateway,
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
    from app.email import gateway

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
        gateway,
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
    from app.email import gateway

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
        gateway,
        "send_outbound",
        lambda **_: pytest.fail("authorize confirmation called provider"),
    )

    response = client.post(
        f"/runs/{run_id}/delivery-review/authorize",
        data={"acknowledgement": "AUTHORIZE A NEW CONFIRMATION"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/runs/{run_id}?notice=review_unavailable"
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


def test_mark_handled_then_simulate_reply_does_not_dead_end(fake_repo, monkeypatch):
    """Reproduces the mark-handled dead end (debug session mark-handled-dead-end).

    The frozen clarification row never becomes send_state='sent' — mark-handled
    is explicitly provider-free (see _finish_clarification_delivery_review's
    docstring) — so simulate_reply's proof-of-delivery guard
    (get_outbound_message_id, filtered to send_state='sent') can never see it.
    Before the fix, this leaves AWAITING_REPLY with no working forward path: the
    operator clicks "Mark handled", then "Simulate client reply" silently 303s
    with no reply persisted and no job enqueued. This test drives both requests
    through the real routes against a hermetic fake_repo and asserts the reply
    actually lands, not just that the response redirected.
    """
    from app.email import gateway
    from app.models.job import JobKind

    run_id, snapshot = _clarification_review_run(fake_repo)

    # simulate_reply needs the run's source inbound email to build the synthetic
    # reply's from_addr/to_addr/subject.
    source_id, inserted = fake_repo.insert_inbound_email(
        message_id=f"<source-{run_id}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr="payroll@coastalcleaning.example",
        to_addr="agent@payroll-agent.local",
        body_text="D. Reyes 40 regular",
    )
    assert inserted and source_id is not None
    fake_repo.runs[str(run_id)]["source_email_id"] = source_id

    monkeypatch.setattr(
        gateway,
        "send_outbound",
        lambda **_: pytest.fail("mark-handled + simulate-reply called the provider"),
    )

    handled = client.post(
        f"/runs/{run_id}/delivery-review/clarification/mark-handled",
        follow_redirects=False,
    )
    assert handled.status_code == 303
    assert fake_repo.load_run(run_id)["status"] == RunStatus.AWAITING_REPLY.value
    # The frozen row is still unproven — mark-handled must NOT fabricate a
    # provider-confirmed send. This is the invariant the fix must not weaken.
    reserved_row = next(
        r for r in fake_repo.outbound[str(run_id)] if r["message_id"] == snapshot["message_id"]
    )
    assert reserved_row["send_state"] != "sent"

    replied = client.post(
        f"/runs/{run_id}/simulate-reply",
        data={"reply_body": "I meant David Reyes"},
        follow_redirects=False,
    )
    assert replied.status_code == 303

    resume_jobs = [
        job
        for job in fake_repo.jobs.values()
        if job["kind"] == JobKind.RESUME_REPLY.value and job["run_id"] == run_id
    ]
    assert len(resume_jobs) == 1, (
        "simulate-reply after mark-handled must persist and enqueue the reply "
        "instead of silently 303-ing with nothing recorded"
    )


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


def test_mark_delivered_releases_only_its_active_confirmation_handoff(
    fake_repo, monkeypatch
):
    """An explicit no-send resolution may settle the matching
    ambiguous handoff but cannot queue or wake another confirmation."""
    import app.routes.runs as runs_mod

    run_id, snapshot = _confirmation_review_run(fake_repo)
    handoff = _attach_active_handoff(fake_repo, run_id, snapshot)
    wake_calls: list[None] = []
    monkeypatch.setattr(runs_mod.wake, "wake", lambda: wake_calls.append(None))

    response = client.post(
        f"/runs/{run_id}/delivery-review/mark-delivered", follow_redirects=False
    )

    assert response.status_code == 303
    assert fake_repo.load_run(run_id)["status"] == RunStatus.RECONCILED.value
    assert handoff["released_at"] is not None
    assert handoff["release_reason"] == "finalized"
    assert len(fake_repo.jobs) == 1
    assert wake_calls == []


def test_typed_confirmation_authorization_releases_handoff_and_clones_frozen_bytes(
    fake_repo, monkeypatch
):
    """A typed confirmation can supersede an ambiguous handoff, and its replacement is a
    new slot containing the original immutable envelope and attachment bytes."""
    import app.routes.runs as runs_mod

    run_id, original = _confirmation_review_run(fake_repo)
    handoff = _attach_active_handoff(fake_repo, run_id, original)
    wake_calls: list[None] = []
    monkeypatch.setattr(runs_mod.wake, "wake", lambda: wake_calls.append(None))

    rejected = client.post(
        f"/runs/{run_id}/delivery-review/authorize",
        data={"acknowledgement": "send it"},
        follow_redirects=False,
    )
    assert rejected.status_code == 303
    assert handoff["released_at"] is None
    assert len(fake_repo.outbound_snapshots) == 1

    accepted = client.post(
        f"/runs/{run_id}/delivery-review/authorize",
        data={"acknowledgement": "AUTHORIZE A NEW CONFIRMATION"},
        follow_redirects=False,
    )

    assert accepted.status_code == 303
    assert handoff["released_at"] is not None
    assert handoff["release_reason"] == "delivery_review"
    assert fake_repo.load_run(run_id)["status"] == RunStatus.APPROVED.value
    replacements = [
        stored["payload"]
        for stored in fake_repo.outbound_snapshots.values()
        if stored["payload"]["email_id"] != original["email_id"]
    ]
    assert len(replacements) == 1
    replacement = replacements[0]
    assert replacement["epoch"] == 1
    for field in (
        "from_addr",
        "to_addr",
        "reply_to",
        "in_reply_to",
        "references_header",
        "subject",
        "body_text",
    ):
        assert replacement[field] == original[field]
    assert [
        (attachment["ordinal"], attachment["filename"], attachment["content"])
        for attachment in replacement["attachments"]
    ] == [
        (attachment["ordinal"], attachment["filename"], attachment["content"])
        for attachment in original["attachments"]
    ]
    assert wake_calls == [None]


# ---------------------------------------------------------------------------
# BUG-7/8/9: every non-silent outcome of a delivery-review outcome handler
# attaches a fixed notice code -- one per AdvanceSendJobOutcome member plus
# the shared review_unavailable / review_state_changed codes.
# ---------------------------------------------------------------------------


def test_retry_now_missing_outcome_explains_why(fake_repo, monkeypatch):
    import app.routes.runs as runs_mod

    run_id, snapshot = _confirmation_review_run(fake_repo)
    monkeypatch.setattr(
        runs_mod.repo,
        "advance_existing_send_job_due_now",
        lambda run, email, **_: runs_mod.repo.AdvanceSendJobOutcome.MISSING,
    )

    response = client.post(
        f"/runs/{run_id}/delivery-review/retry-now", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/runs/{run_id}?notice=retry_missing"
    assert fake_repo.load_run(run_id)["status"] == RunStatus.NEEDS_OPERATOR.value


def test_retry_now_expired_outcome_explains_why(fake_repo):
    """Mirrors test_clarification_retry_expired_is_a_noop, but on the confirmation
    facade and asserting the notice code instead of only the no-op."""
    import app.routes.runs as runs_mod  # noqa: F401 -- imported for parity with siblings

    run_id, snapshot = _confirmation_review_run(fake_repo)
    fake_repo.outbound_snapshots[str(snapshot["email_id"])]["payload"][
        "reserved_at"
    ] = datetime.now(UTC) - timedelta(hours=21)

    response = client.post(
        f"/runs/{run_id}/delivery-review/retry-now", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/runs/{run_id}?notice=retry_expired"
    assert fake_repo.load_run(run_id)["status"] == RunStatus.NEEDS_OPERATOR.value


def test_retry_now_not_pending_outcome_explains_why(fake_repo, monkeypatch):
    import app.routes.runs as runs_mod

    run_id, snapshot = _confirmation_review_run(fake_repo)
    monkeypatch.setattr(
        runs_mod.repo,
        "advance_existing_send_job_due_now",
        lambda run, email, **_: runs_mod.repo.AdvanceSendJobOutcome.NOT_PENDING,
    )

    response = client.post(
        f"/runs/{run_id}/delivery-review/retry-now", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/runs/{run_id}?notice=retry_not_pending"
    assert fake_repo.load_run(run_id)["status"] == RunStatus.NEEDS_OPERATOR.value


def test_retry_now_db_exception_explains_why(fake_repo, monkeypatch):
    import app.routes.runs as runs_mod

    run_id, _snapshot = _confirmation_review_run(fake_repo)

    def raise_connection(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(runs_mod.repo, "get_connection", raise_connection)

    response = client.post(
        f"/runs/{run_id}/delivery-review/retry-now", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/runs/{run_id}?notice=retry_unavailable"
    assert fake_repo.load_run(run_id)["status"] == RunStatus.NEEDS_OPERATOR.value


def test_mark_delivery_delivered_lost_cas_explains_why(fake_repo, monkeypatch):
    """A concurrent actor already moved the run off needs_operator by the time
    this transaction's claim_status runs -- the operator sees why "Mark
    delivered" appeared to do nothing, instead of a silent reload."""
    import app.routes.runs as runs_mod

    run_id, snapshot = _confirmation_review_run(fake_repo)
    monkeypatch.setattr(runs_mod.repo, "claim_status", lambda *args, **kwargs: False)

    response = client.post(
        f"/runs/{run_id}/delivery-review/mark-delivered", follow_redirects=False
    )

    assert response.status_code == 303
    assert (
        response.headers["location"] == f"/runs/{run_id}?notice=review_state_changed"
    )
    assert fake_repo.load_run(run_id)["status"] == RunStatus.NEEDS_OPERATOR.value


def test_finish_clarification_review_lost_cas_explains_why(fake_repo, monkeypatch):
    """The same lost-CAS race for BOTH clarification outcome handlers (mark-handled
    and reject) funnels through _finish_clarification_delivery_review."""
    import app.routes.runs as runs_mod

    run_id, _snapshot = _clarification_review_run(fake_repo)
    monkeypatch.setattr(runs_mod.repo, "claim_status", lambda *args, **kwargs: False)

    response = client.post(
        f"/runs/{run_id}/delivery-review/clarification/mark-handled",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert (
        response.headers["location"] == f"/runs/{run_id}?notice=review_state_changed"
    )
    assert fake_repo.load_run(run_id)["status"] == RunStatus.NEEDS_OPERATOR.value


def test_review_unavailable_notice_on_wrong_kind(fake_repo):
    """A confirmation-only route hit against a clarification review is exactly
    the wrong-kind case review_unavailable exists to explain."""
    run_id, _snapshot = _clarification_review_run(fake_repo)

    response = client.post(
        f"/runs/{run_id}/delivery-review/mark-delivered", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/runs/{run_id}?notice=review_unavailable"
    assert fake_repo.load_run(run_id)["status"] == RunStatus.NEEDS_OPERATOR.value


# ---------------------------------------------------------------------------
# BUG-4: authorize_new_confirmation guards a client-facing SECOND email, so
# every refusal attaches a fixed notice code -- highest-value being a
# mistyped acknowledgement phrase, which used to look like a broken button.
# ---------------------------------------------------------------------------


def test_authorize_bad_ack_explains_why(fake_repo):
    run_id, snapshot = _confirmation_review_run(fake_repo)
    before_run = dict(fake_repo.load_run(run_id))

    response = client.post(
        f"/runs/{run_id}/delivery-review/authorize",
        data={"acknowledgement": "authorize a new confirmation"},  # wrong case
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/runs/{run_id}?notice=authorize_bad_ack"
    assert fake_repo.load_run(run_id) == before_run

    page = client.get(f"/runs/{run_id}?notice=authorize_bad_ack")
    assert page.status_code == 200
    assert "AUTHORIZE A NEW CONFIRMATION" in page.text


def test_authorize_lost_cas_explains_why(fake_repo, monkeypatch):
    import app.routes.runs as runs_mod

    run_id, snapshot = _confirmation_review_run(fake_repo)
    monkeypatch.setattr(runs_mod.repo, "claim_status", lambda *args, **kwargs: False)

    response = client.post(
        f"/runs/{run_id}/delivery-review/authorize",
        data={"acknowledgement": "AUTHORIZE A NEW CONFIRMATION"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert (
        response.headers["location"] == f"/runs/{run_id}?notice=review_state_changed"
    )
    assert fake_repo.load_run(run_id)["status"] == RunStatus.NEEDS_OPERATOR.value
    assert len(fake_repo.outbound_snapshots) == 1, (
        "a lost CAS must not mint a replacement confirmation slot"
    )


# ---------------------------------------------------------------------------
# T9 (BUG-2 half 2 + BUG-11): the two delivery-review cards consume the
# classification -- naming the uncertainty and hiding actions that cannot
# succeed, instead of rendering both Retry buttons unconditionally.
# ---------------------------------------------------------------------------

_CLARIFICATION_RETRY_ACTION = "/delivery-review/clarification/retry-now"
_AUTHORIZE_ACTION = "/delivery-review/authorize"
_MARK_DELIVERED_ACTION = "/delivery-review/mark-delivered"
_MARK_HANDLED_ACTION = "/delivery-review/clarification/mark-handled"
_CLARIFICATION_REJECT_ACTION = "/delivery-review/clarification/reject"


def test_validation_confirmation_card_hides_both_actions_and_shows_blocker(
    fake_repo,
) -> None:
    """BUG-2: validation (the live-proven Resend 403 on a .example recipient)
    can never succeed either way -- neither action is offered, and the
    blocker sentence explains why the space is not silently empty."""
    run_id, _snapshot = _confirmation_review_run(fake_repo)
    fake_repo.runs[str(run_id)]["error_detail"] = "delivery_review:validation"

    page = client.get(f"/runs/{run_id}")

    assert page.status_code == 200
    assert _AUTHORIZE_ACTION not in page.text
    assert "the recipient or sender configuration must change first" in page.text
    # The provider-free escape stays unconditional -- the anti-BUG-1 pin.
    assert _MARK_DELIVERED_ACTION in page.text


def test_validation_clarification_card_hides_retry_and_shows_blocker(fake_repo) -> None:
    run_id, _snapshot = _clarification_review_run(fake_repo)
    fake_repo.runs[str(run_id)]["error_detail"] = "delivery_review:validation"

    page = client.get(f"/runs/{run_id}")

    assert page.status_code == 200
    assert _CLARIFICATION_RETRY_ACTION not in page.text
    assert "the recipient or sender configuration must change first" in page.text
    # "Mark handled" and "Reject" stay unconditional -- provider-free, must
    # always be available, or this recreates BUG-1.
    assert _MARK_HANDLED_ACTION in page.text
    assert _CLARIFICATION_REJECT_ACTION in page.text


def test_transport_confirmation_card_offers_both_actions(fake_repo) -> None:
    run_id, _snapshot = _confirmation_review_run(fake_repo)
    fake_repo.runs[str(run_id)]["error_detail"] = "delivery_review:transport"

    page = client.get(f"/runs/{run_id}")

    assert page.status_code == 200
    assert _AUTHORIZE_ACTION in page.text
    assert _MARK_DELIVERED_ACTION in page.text


def test_payload_mismatch_confirmation_card_offers_authorize_not_retry(
    fake_repo,
) -> None:
    """The case a single `retryable: bool` gets backwards: payload_mismatch
    cannot be replayed under its existing key, but a fresh slot can."""
    run_id, _snapshot = _confirmation_review_run(fake_repo)
    fake_repo.runs[str(run_id)]["error_detail"] = "delivery_review:payload_mismatch"

    page = client.get(f"/runs/{run_id}")

    assert page.status_code == 200
    assert _AUTHORIZE_ACTION in page.text
    assert _MARK_DELIVERED_ACTION in page.text


def test_payload_mismatch_clarification_card_hides_retry(fake_repo) -> None:
    run_id, _snapshot = _clarification_review_run(fake_repo)
    fake_repo.runs[str(run_id)]["error_detail"] = "delivery_review:payload_mismatch"

    page = client.get(f"/runs/{run_id}")

    assert page.status_code == 200
    assert _CLARIFICATION_RETRY_ACTION not in page.text
    assert _MARK_HANDLED_ACTION in page.text
    assert _CLARIFICATION_REJECT_ACTION in page.text


@pytest.mark.parametrize(
    "category",
    [
        "transport",
        "provider_5xx",
        "rate_limited",
        "authorization_expired",
        "unknown",
        "payload_mismatch",
        "final_attempt_lease_expired",
        "authorization",
        "validation",
        "configuration",
    ],
)
def test_every_category_renders_its_own_uncertainty_sentence(
    fake_repo, category: str
) -> None:
    from app.models.delivery_review import DELIVERY_REVIEW_CATEGORIES

    run_id, _snapshot = _confirmation_review_run(fake_repo)
    fake_repo.runs[str(run_id)]["error_detail"] = f"delivery_review:{category}"

    page = client.get(f"/runs/{run_id}")

    assert page.status_code == 200
    assert DELIVERY_REVIEW_CATEGORIES[category].uncertainty in page.text


# ---------------------------------------------------------------------------
# T10 (BUG-1): the "Delivery review unavailable" card gets a working Reject
# escape. Per Design flag 4, Reject is the ONLY escape offered -- resolve()
# and retrigger() both guard the delivery-review marker and would silently
# no-op (:546 / :736), which would convert this into a fresh BUG-5.
# ---------------------------------------------------------------------------


def test_unavailable_delivery_review_card_offers_only_reject(
    fake_repo, monkeypatch
) -> None:
    import app.routes.runs as runs_mod

    run_id, _snapshot = _confirmation_review_run(fake_repo)
    # Break the load: the marker is still True (error_reason/status intact),
    # but the frozen snapshot itself cannot be loaded -- the None-cause BUG-1
    # is actually about (snapshot row gone, purpose mismatch, etc).
    monkeypatch.setattr(
        runs_mod.repo, "load_delivery_review_snapshot", lambda *a, **kw: None
    )

    page = client.get(f"/runs/{run_id}")

    assert page.status_code == 200
    assert "Delivery review unavailable" in page.text
    assert "Action required" in page.text
    assert f'action="/runs/{run_id}/reject"' in page.text
    assert f'action="/runs/{run_id}/resolve"' not in page.text
    assert f'action="/runs/{run_id}/retrigger"' not in page.text

    rejected = client.post(f"/runs/{run_id}/reject", follow_redirects=False)

    assert rejected.status_code == 303
    assert fake_repo.load_run(run_id)["status"] == RunStatus.REJECTED.value
