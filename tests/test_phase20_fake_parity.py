"""Default-running regressions for the in-memory SEND_OUTBOUND repository mirror."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import psycopg
import pytest

from app.models.job import JobKind
from app.models.status import RunStatus
from app.pipeline.result import (
    PipelineOutcome,
    PipelineReason,
    PipelineResult,
    PipelineStage,
)

_REPLAYABLE_DELIVERY_REASONS = (
    PipelineReason.DELIVERY_TIMEOUT,
    PipelineReason.DELIVERY_CONNECTION_FAILURE,
    PipelineReason.DELIVERY_RATE_LIMIT,
    PipelineReason.DELIVERY_SERVER_FAILURE,
)


def _seed_send_job(
    fake_repo,
    *,
    purpose: str = "confirmation",
    authorize: bool = True,
    record_only: bool = False,
):
    run_id = fake_repo.create_run(
        business_id=fake_repo.contact_to_business["payroll@coastalcleaning.example"],
        source_email_id=None,
        record_only=record_only,
    )
    fake_repo.set_status(
        run_id,
        RunStatus.APPROVED if purpose == "confirmation" else RunStatus.AWAITING_REPLY,
    )
    snapshot = fake_repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose=purpose,
        round=0,
        message_id=f"<{uuid.uuid4()}@payroll-agent.local>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@coastalcleaning.example",
        reply_to="reply@payroll-agent.local",
        in_reply_to=None,
        references_header=None,
        subject="Frozen delivery",
        body_text="Frozen body",
        attachments=[("frozen.pdf", b"frozen-bytes")],
    )
    job_id = fake_repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=f"send_outbound:{snapshot['email_id']}",
        run_id=run_id,
        email_id=snapshot["email_id"],
    )
    assert job_id is not None
    claimed = fake_repo.claim_job()
    assert claimed is not None and claimed.id == job_id
    if authorize:
        authorization = fake_repo.authorize_outbound_provider_handoff(claimed)
        if record_only:
            assert getattr(authorization, "run_id", None) == run_id
        else:
            assert getattr(authorization, "job_id", None) == claimed.id
    return run_id, snapshot, claimed


def _delivery_result(reason: PipelineReason, outcome: PipelineOutcome) -> PipelineResult:
    return PipelineResult(outcome=outcome, stage=PipelineStage.DELIVERY, reason=reason)


def _reserve_current_epoch_snapshot(fake_repo, run_id: uuid.UUID, *, purpose: str):
    return fake_repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose=purpose,
        round=0,
        message_id=f"<current-{purpose}-{uuid.uuid4()}@test.example>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@coastalcleaning.example",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Current frozen delivery",
        body_text="Current frozen body",
        attachments=[("frozen.pdf", b"frozen-bytes")],
    )


def _failure_category(reason: PipelineReason) -> str:
    if reason in {
        PipelineReason.DELIVERY_TIMEOUT,
        PipelineReason.DELIVERY_CONNECTION_FAILURE,
    }:
        return "transport"
    if reason is PipelineReason.DELIVERY_SERVER_FAILURE:
        return "provider_5xx"
    if reason is PipelineReason.DELIVERY_RATE_LIMIT:
        return "rate_limited"
    if reason is PipelineReason.DELIVERY_IDEMPOTENCY_PAYLOAD_MISMATCH:
        return "payload_mismatch"
    if reason in {
        PipelineReason.DELIVERY_AUTHENTICATION_FAILURE,
        PipelineReason.DELIVERY_AUTHORIZATION_FAILURE,
    }:
        return "authorization"
    if reason is PipelineReason.DELIVERY_VALIDATION_FAILURE:
        return "validation"
    if reason is PipelineReason.DELIVERY_CONFIGURATION_FAILURE:
        return "configuration"
    return "unknown"


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"dedup_key": "send_outbound:not-the-email"}, "send_outbound"),
        ({"run_id": None}, "send_outbound"),
        ({"email_id": None}, "send_outbound"),
        ({"operator_resolution_id": uuid.uuid4()}, "send_outbound"),
        ({"event_id": uuid.uuid4()}, "send_outbound"),
        ({"business_id": uuid.uuid4()}, "send_outbound"),
        ({"max_attempts": 7}, "fixed replay-attempt ladder"),
    ],
)
def test_fake_send_enqueue_rejects_malformed_context_before_mutation(
    fake_repo, overrides, expected_message
) -> None:
    run_id = uuid.uuid4()
    email_id = uuid.uuid4()
    kwargs = {
        "kind": JobKind.SEND_OUTBOUND,
        "dedup_key": f"send_outbound:{email_id}",
        "run_id": run_id,
        "email_id": email_id,
    }
    kwargs.update(overrides)

    before_jobs = dict(fake_repo.jobs)
    with pytest.raises(ValueError, match=expected_message):
        fake_repo.enqueue_job(**kwargs)

    assert fake_repo.jobs == before_jobs
    assert fake_repo._job_dedup_keys == {}


def test_fake_send_enqueue_deduplicates_and_forces_eight_attempts(fake_repo) -> None:
    run_id = uuid.uuid4()
    email_id = uuid.uuid4()
    kwargs = {
        "kind": JobKind.SEND_OUTBOUND,
        "dedup_key": f"send_outbound:{email_id}",
        "run_id": run_id,
        "email_id": email_id,
    }

    first_id = fake_repo.enqueue_job(**kwargs)
    duplicate_id = fake_repo.enqueue_job(**kwargs)

    assert first_id is not None
    assert duplicate_id is None
    assert len(fake_repo.jobs) == 1
    stored = fake_repo.jobs[str(first_id)]
    assert stored["run_id"] == run_id
    assert stored["email_id"] == email_id
    assert stored["max_attempts"] == 8
    assert set(stored) >= {
        "id",
        "kind",
        "dedup_key",
        "run_id",
        "email_id",
        "attempts",
        "max_attempts",
    }


def test_fake_send_claim_increments_the_eight_attempt_budget(fake_repo) -> None:
    run_id = uuid.uuid4()
    email_id = uuid.uuid4()
    job_id = fake_repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=f"send_outbound:{email_id}",
        run_id=run_id,
        email_id=email_id,
    )
    assert job_id is not None

    claimed = fake_repo.claim_job()

    assert claimed is not None
    assert claimed.attempts == 1
    assert claimed.max_attempts == 8
    assert fake_repo.jobs[str(job_id)]["attempts"] == 1


@pytest.mark.parametrize("reason", _REPLAYABLE_DELIVERY_REASONS)
def test_fake_outbound_settlement_replays_only_the_four_allowed_reasons(
    fake_repo, reason
) -> None:
    from app.db.repo.job_settlement import SettlementOutcome

    run_id, snapshot, claimed = _seed_send_job(fake_repo)

    outcome = fake_repo.settle_outbound_delivery_job(
        claimed, _delivery_result(reason, PipelineOutcome.RETRYABLE)
    )

    assert outcome is SettlementOutcome.RETRIED
    job = fake_repo.get_job(claimed.id)
    assert job is not None and job["state"] == "pending"
    assert fake_repo.load_run(run_id)["status"] == RunStatus.APPROVED.value
    assert fake_repo.delivery_attempts == [
        {
            "snapshot_id": snapshot["snapshot_id"],
            "attempt_state": "retry_scheduled",
            "failure_category": {
                PipelineReason.DELIVERY_TIMEOUT: "transport",
                PipelineReason.DELIVERY_CONNECTION_FAILURE: "transport",
                PipelineReason.DELIVERY_RATE_LIMIT: "rate_limited",
                PipelineReason.DELIVERY_SERVER_FAILURE: "provider_5xx",
            }[reason],
        }
    ]


@pytest.mark.parametrize(
    "reason",
    [
        reason
        for reason in PipelineReason
        if reason
        not in {
            *_REPLAYABLE_DELIVERY_REASONS,
            PipelineReason.DELIVERY_RECORD_ONLY,
            PipelineReason.DELIVERY_AUTHORIZATION_EXPIRED,
        }
    ],
)
def test_fake_outbound_settlement_direct_reviews_every_other_retryable_reason(
    fake_repo, reason
) -> None:
    from app.db.repo.job_settlement import SettlementOutcome

    run_id, snapshot, claimed = _seed_send_job(fake_repo)

    outcome = fake_repo.settle_outbound_delivery_job(
        claimed, _delivery_result(reason, PipelineOutcome.RETRYABLE)
    )

    assert outcome is SettlementOutcome.DONE
    job = fake_repo.get_job(claimed.id)
    run = fake_repo.load_run(run_id)
    assert job is not None and job["state"] == "done"
    assert run["status"] == RunStatus.NEEDS_OPERATOR.value
    assert run["error_reason"] == "DeliveryReview"
    assert run["error_detail"] == f"delivery_review:{_failure_category(reason)}"
    assert fake_repo.delivery_attempts[-1] == {
        "snapshot_id": snapshot["snapshot_id"],
        "attempt_state": "needs_operator",
        "failure_category": _failure_category(reason),
    }


def test_fake_record_only_settlement_completes_without_attempt_or_handoff(fake_repo) -> None:
    from app.db.repo.job_settlement import SettlementOutcome

    run_id, snapshot, claimed = _seed_send_job(fake_repo, record_only=True)
    assert fake_repo.outbound_provider_handoffs == {}

    outcome = fake_repo.settle_outbound_delivery_job(
        claimed,
        _delivery_result(PipelineReason.DELIVERY_RECORD_ONLY, PipelineOutcome.OK),
    )

    assert outcome is SettlementOutcome.DONE
    assert fake_repo.delivery_attempts == []
    assert fake_repo.outbound_provider_handoffs == {}
    assert fake_repo.get_job(claimed.id)["state"] == "done"
    assert fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"]) is not None
    assert fake_repo.outbound[str(run_id)][0]["send_state"] == "sent"


def test_fake_expired_authorization_releases_exact_handoff_to_review(fake_repo) -> None:
    from app.db.repo.job_settlement import SettlementOutcome

    run_id, snapshot, claimed = _seed_send_job(fake_repo)
    authorization = fake_repo.authorize_outbound_provider_handoff(claimed)

    outcome = fake_repo.settle_outbound_delivery_job(
        claimed,
        _delivery_result(
            PipelineReason.DELIVERY_AUTHORIZATION_EXPIRED, PipelineOutcome.TERMINAL
        ),
    )

    assert outcome is SettlementOutcome.DONE
    handoff = fake_repo.outbound_provider_handoffs[str(authorization.handoff_id)]
    assert handoff["release_reason"] == "delivery_review"
    assert handoff["released_at"] is not None
    assert fake_repo.get_job(claimed.id)["state"] == "done"
    assert fake_repo.load_run(run_id)["status"] == RunStatus.NEEDS_OPERATOR.value
    assert fake_repo.load_run(run_id)["error_detail"] == "delivery_review:authorization_expired"
    assert fake_repo.delivery_attempts[-1] == {
        "snapshot_id": snapshot["snapshot_id"],
        "attempt_state": "needs_operator",
        "failure_category": "authorization_expired",
    }


@pytest.mark.parametrize(
    ("purpose", "review_reason"),
    [
        ("confirmation", "DeliveryReview"),
        ("clarification", "ClarificationDeliveryReview"),
    ],
)
def test_fake_pre_provider_expiry_enters_purpose_review_without_handoff(
    fake_repo, purpose, review_reason
) -> None:
    """A closed authorizer window has no provider authority to release."""
    from app.db.repo.job_settlement import SettlementOutcome

    run_id, snapshot, claimed = _seed_send_job(fake_repo, purpose=purpose, authorize=False)
    fake_repo.outbound_snapshots[str(snapshot["email_id"])]["payload"]["reserved_at"] = (
        datetime.now(UTC) - timedelta(hours=20)
    )
    before_snapshot = fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"])

    assert (
        fake_repo.settle_outbound_delivery_job(
            claimed,
            _delivery_result(
                PipelineReason.DELIVERY_AUTHORIZATION_EXPIRED, PipelineOutcome.TERMINAL
            ),
        )
        is SettlementOutcome.DONE
    )

    job = fake_repo.get_job(claimed.id)
    run = fake_repo.load_run(run_id)
    assert fake_repo.outbound_provider_handoffs == {}
    assert job is not None and job["state"] == "done"
    assert job["lease_token"] is None and job["leased_until"] is None
    assert run["status"] == RunStatus.NEEDS_OPERATOR.value
    assert run["error_reason"] == review_reason
    assert run["error_detail"] == "delivery_review:authorization_expired"
    assert fake_repo.delivery_attempts == [
        {
            "snapshot_id": snapshot["snapshot_id"],
            "attempt_state": "needs_operator",
            "failure_category": "authorization_expired",
        }
    ]
    assert fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"]) == before_snapshot
    assert fake_repo.outbound[str(run_id)][0]["send_state"] == "reserved"


def test_fake_pre_provider_branch_rejects_other_no_handoff_terminal_results(fake_repo) -> None:
    """Missing provider authority does not grant arbitrary terminal review writes."""
    from app.db.repo.job_settlement import SettlementOutcome

    run_id, snapshot, claimed = _seed_send_job(fake_repo, authorize=False)
    before_run = dict(fake_repo.load_run(run_id))

    assert (
        fake_repo.settle_outbound_delivery_job(
            claimed,
            _delivery_result(
                PipelineReason.DELIVERY_VALIDATION_FAILURE, PipelineOutcome.TERMINAL
            ),
        )
        is SettlementOutcome.INVALID_CONTEXT
    )

    assert fake_repo.delivery_attempts == []
    assert fake_repo.load_run(run_id) == before_run
    assert fake_repo.outbound_provider_handoffs == {}
    assert fake_repo.get_job(claimed.id)["state"] == "done"
    assert fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"]) is not None


def test_fake_pre_provider_expiry_rejects_a_foreign_active_handoff(fake_repo) -> None:
    """The no-handoff branch cannot write review evidence around another authority."""
    from app.db.repo.job_settlement import SettlementOutcome

    run_id, snapshot, claimed = _seed_send_job(fake_repo, authorize=False)
    authorization = fake_repo.authorize_outbound_provider_handoff(claimed)
    foreign = fake_repo.outbound_provider_handoffs[str(authorization.handoff_id)]
    foreign["email_id"] = uuid.uuid4()
    fake_repo.outbound_snapshots[str(snapshot["email_id"])]["payload"]["reserved_at"] = (
        datetime.now(UTC) - timedelta(hours=20)
    )
    before_run = dict(fake_repo.load_run(run_id))

    assert (
        fake_repo.settle_outbound_delivery_job(
            claimed,
            _delivery_result(
                PipelineReason.DELIVERY_AUTHORIZATION_EXPIRED, PipelineOutcome.TERMINAL
            ),
        )
        is SettlementOutcome.INVALID_CONTEXT
    )

    assert fake_repo.delivery_attempts == []
    assert fake_repo.load_run(run_id) == before_run
    assert fake_repo.get_job(claimed.id)["state"] == "done"
    assert foreign["released_at"] is None


def test_fake_pre_provider_expiry_lost_lease_writes_no_review_evidence(fake_repo) -> None:
    """A stale worker cannot settle the replacement lease's expired reservation."""
    from app.db.repo.job_settlement import SettlementOutcome

    run_id, snapshot, claimed = _seed_send_job(fake_repo, authorize=False)
    fake_repo.outbound_snapshots[str(snapshot["email_id"])]["payload"]["reserved_at"] = (
        datetime.now(UTC) - timedelta(hours=20)
    )
    fake_repo.jobs[str(claimed.id)]["lease_token"] = uuid.uuid4()
    before_run = dict(fake_repo.load_run(run_id))

    assert (
        fake_repo.settle_outbound_delivery_job(
            claimed,
            _delivery_result(
                PipelineReason.DELIVERY_AUTHORIZATION_EXPIRED, PipelineOutcome.TERMINAL
            ),
        )
        is SettlementOutcome.LOST_LEASE
    )

    assert fake_repo.delivery_attempts == []
    assert fake_repo.load_run(run_id) == before_run
    assert fake_repo.get_job(claimed.id)["state"] == "leased"


@pytest.mark.parametrize(
    "reason",
    [PipelineReason.DELIVERY_TIMEOUT, PipelineReason.DELIVERY_SERVER_FAILURE],
)
def test_fake_retry_releases_exact_handoff_then_reauthorizes_frozen_slot(
    fake_repo, reason
) -> None:
    from app.db.repo.job_settlement import SettlementOutcome

    _run_id, snapshot, first_claim = _seed_send_job(fake_repo)
    first_authorization = fake_repo.authorize_outbound_provider_handoff(first_claim)

    assert (
        fake_repo.settle_outbound_delivery_job(
            first_claim, _delivery_result(reason, PipelineOutcome.RETRYABLE)
        )
        is SettlementOutcome.RETRIED
    )
    first_handoff = fake_repo.outbound_provider_handoffs[str(first_authorization.handoff_id)]
    assert first_handoff["release_reason"] == "retry_scheduled"
    assert fake_repo.get_job(first_claim.id)["state"] == "pending"

    second_claim = fake_repo.claim_job()
    assert second_claim is not None and second_claim.id == first_claim.id
    second_authorization = fake_repo.authorize_outbound_provider_handoff(second_claim)
    assert second_authorization.handoff_id != first_authorization.handoff_id
    assert second_authorization.snapshot["message_id"] == snapshot["message_id"]
    assert second_authorization.snapshot_id == snapshot["snapshot_id"]
    assert second_authorization.not_after == first_authorization.not_after
    assert not fake_repo.release_outbound_provider_handoff_for_retry(first_authorization)
    assert (
        fake_repo.settle_outbound_delivery_job(
            second_claim, _delivery_result(PipelineReason.UNCLASSIFIED, PipelineOutcome.OK)
        )
        is SettlementOutcome.DONE
    )
    assert (
        fake_repo.outbound_provider_handoffs[str(second_authorization.handoff_id)][
            "release_reason"
        ]
        == "finalized"
    )


def test_fake_crash_reclaim_adopts_only_expired_exact_handoff(fake_repo, monkeypatch) -> None:
    from app.email import gateway
    from app.queue.handlers import send_outbound

    _run_id, snapshot, first_claim = _seed_send_job(fake_repo)
    first_authorization = fake_repo.authorize_outbound_provider_handoff(first_claim)
    original = fake_repo.outbound_provider_handoffs[str(first_authorization.handoff_id)]
    original_authorized_at = original["authorized_at"]
    fake_repo.jobs[str(first_claim.id)].update(
        state="pending",
        lease_token=None,
        leased_until=None,
    )
    original["owner_leased_until"] = datetime.now(UTC) - timedelta(seconds=1)

    reclaimed = fake_repo.claim_job()
    assert reclaimed is not None and reclaimed.id == first_claim.id
    adopted = fake_repo.authorize_outbound_provider_handoff(reclaimed)
    assert adopted.handoff_id == first_authorization.handoff_id
    assert adopted.snapshot_id == snapshot["snapshot_id"]
    assert adopted.snapshot["message_id"] == snapshot["message_id"]
    assert adopted.not_after == first_authorization.not_after
    assert original["authorized_at"] == original_authorized_at
    assert not fake_repo.finalize_outbound_provider_handoff(first_authorization)

    calls: list[object] = []

    def _provider_spy(stored, **_kwargs) -> PipelineResult:
        calls.append(stored)
        return PipelineResult(outcome=PipelineOutcome.OK, stage=PipelineStage.DELIVERY)

    monkeypatch.setattr(
        gateway,
        "send_reserved_outbound_snapshot",
        _provider_spy,
    )
    assert send_outbound.handle_send_outbound(reclaimed).outcome is PipelineOutcome.OK
    assert calls == [adopted.snapshot]


def test_fake_review_projection_counts_append_only_attempt_facts_and_hides_body(
    fake_repo,
) -> None:
    run_id, snapshot, claimed = _seed_send_job(fake_repo)
    fake_repo.settle_outbound_delivery_job(
        claimed,
        _delivery_result(PipelineReason.DELIVERY_TIMEOUT, PipelineOutcome.RETRYABLE),
    )
    second_claim = fake_repo.claim_job()
    assert second_claim is not None
    second_authorization = fake_repo.authorize_outbound_provider_handoff(second_claim)
    assert getattr(second_authorization, "job_id", None) == second_claim.id
    fake_repo.settle_outbound_delivery_job(
        second_claim,
        _delivery_result(
            PipelineReason.DELIVERY_VALIDATION_FAILURE, PipelineOutcome.RETRYABLE
        ),
    )

    review = fake_repo.load_delivery_review_snapshot(run_id, snapshot["email_id"])
    frozen = fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"])
    assert review is not None and review["attempt_count"] == 2
    assert "body_text" not in review
    assert frozen is not None and frozen["body_text"] == "Frozen body"
    assert len(
        [
            attempt
            for attempt in fake_repo.delivery_attempts
            if attempt["snapshot_id"] == snapshot["snapshot_id"]
        ]
    ) == 2


@pytest.mark.parametrize(
    ("purpose", "run_status", "review_reason"),
    [
        ("confirmation", RunStatus.APPROVED, "DeliveryReview"),
        ("clarification", RunStatus.AWAITING_REPLY, "ClarificationDeliveryReview"),
        (
            "clarification_field_regression",
            RunStatus.AWAITING_REPLY,
            "ClarificationDeliveryReview",
        ),
    ],
)
def test_fake_final_send_lease_reap_preserves_snapshot_and_enters_purpose_review(
    fake_repo, purpose, run_status, review_reason
) -> None:
    from app.db.repo.job_settlement import SettlementOutcome

    run_id, snapshot, claimed = _seed_send_job(fake_repo, purpose=purpose)
    fake_repo.jobs[str(claimed.id)].update(
        attempts=claimed.max_attempts,
        lease_expired=True,
    )

    assert fake_repo.reap_expired_final_attempt() is SettlementOutcome.REAPED_FINAL_LEASE
    run = fake_repo.load_run(run_id)
    job = fake_repo.get_job(claimed.id)
    frozen = fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"])
    assert run["status"] == RunStatus.NEEDS_OPERATOR.value
    assert run["error_reason"] == review_reason
    assert run["error_detail"] == "delivery_review:final_attempt_lease_expired"
    assert job is not None and job["state"] == "dead"
    assert frozen is not None and frozen["message_id"] == snapshot["message_id"]
    assert frozen["body_text"] == "Frozen body"
    assert fake_repo.delivery_attempts[-1] == {
        "snapshot_id": snapshot["snapshot_id"],
        "attempt_state": "needs_operator",
        "failure_category": "final_attempt_lease_expired",
    }


def test_fake_stale_epoch_send_settlement_retires_invalid_lease_without_mutation(
    fake_repo,
) -> None:
    from app.db.repo.job_settlement import SettlementOutcome

    run_id, old_snapshot, claimed = _seed_send_job(fake_repo, authorize=False)
    assert fake_repo.clear_reply_context(run_id) == 1
    current_snapshot = _reserve_current_epoch_snapshot(
        fake_repo, run_id, purpose="confirmation"
    )
    before_run = dict(fake_repo.load_run(run_id))
    before_attempts = list(fake_repo.delivery_attempts)
    assert (
        fake_repo.settle_outbound_delivery_job(
            claimed, PipelineResult(outcome=PipelineOutcome.OK)
        )
        is SettlementOutcome.INVALID_CONTEXT
    )

    assert fake_repo.delivery_attempts == before_attempts
    assert fake_repo.load_run(run_id) == before_run
    old_job = fake_repo.get_job(claimed.id)
    assert old_job is not None
    assert old_job["state"] == "done"
    assert old_job["lease_token"] is None
    assert old_job["leased_until"] is None
    assert old_job["last_error"] == "delivery:invalid_context"
    old_frozen = fake_repo.load_outbound_snapshot(run_id, old_snapshot["email_id"])
    current_frozen = fake_repo.load_outbound_snapshot(
        run_id, current_snapshot["email_id"]
    )
    assert old_frozen is not None and old_frozen["message_id"] == old_snapshot["message_id"]
    assert current_frozen is not None
    assert current_frozen["message_id"] == current_snapshot["message_id"]
    assert all(
        message["send_state"] == "reserved"
        for message in fake_repo.outbound[str(run_id)]
    )


def test_fake_stale_epoch_final_lease_retires_invalid_lease_without_mutation(
    fake_repo,
) -> None:
    from app.db.repo.job_settlement import SettlementOutcome

    run_id, old_snapshot, claimed = _seed_send_job(fake_repo, authorize=False)
    assert fake_repo.clear_reply_context(run_id) == 1
    current_snapshot = _reserve_current_epoch_snapshot(
        fake_repo, run_id, purpose="confirmation"
    )
    fake_repo.jobs[str(claimed.id)].update(
        attempts=claimed.max_attempts,
        lease_expired=True,
    )
    before_run = dict(fake_repo.load_run(run_id))
    before_attempts = list(fake_repo.delivery_attempts)
    assert fake_repo.reap_expired_final_attempt() is SettlementOutcome.INVALID_CONTEXT

    assert fake_repo.delivery_attempts == before_attempts
    assert fake_repo.load_run(run_id) == before_run
    old_job = fake_repo.get_job(claimed.id)
    assert old_job is not None
    assert old_job["state"] == "dead"
    assert old_job["lease_token"] is None
    assert old_job["leased_until"] is None
    assert old_job["last_error"] == "delivery:invalid_context"
    old_frozen = fake_repo.load_outbound_snapshot(run_id, old_snapshot["email_id"])
    current_frozen = fake_repo.load_outbound_snapshot(
        run_id, current_snapshot["email_id"]
    )
    assert old_frozen is not None and old_frozen["message_id"] == old_snapshot["message_id"]
    assert current_frozen is not None
    assert current_frozen["message_id"] == current_snapshot["message_id"]
    assert all(
        message["send_state"] == "reserved"
        for message in fake_repo.outbound[str(run_id)]
    )


def test_fake_stale_epoch_handler_is_provider_free(fake_repo, monkeypatch) -> None:
    from app.email import gateway
    from app.queue.handlers import send_outbound

    run_id, old_snapshot, claimed = _seed_send_job(fake_repo, authorize=False)
    assert fake_repo.clear_reply_context(run_id) == 1
    current_snapshot = _reserve_current_epoch_snapshot(
        fake_repo, run_id, purpose="confirmation"
    )
    provider_calls = []

    def provider_spy(snapshot):
        provider_calls.append(snapshot)
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(
        gateway,
        "send_reserved_outbound_snapshot",
        provider_spy,
    )

    assert send_outbound.handle_send_outbound(claimed).outcome is PipelineOutcome.OK
    assert provider_calls == []
    assert fake_repo.load_outbound_snapshot(
        run_id, current_snapshot["email_id"]
    )["message_id"] == current_snapshot["message_id"]


def test_fake_clarification_review_retry_advances_the_same_row_only(fake_repo) -> None:
    from app.db import repo
    from app.db.repo.jobs import AdvanceSendJobOutcome

    run_id, snapshot, claimed = _seed_send_job(fake_repo, purpose="clarification")
    job = fake_repo.get_job(claimed.id)
    assert job is not None
    job.update(state="pending", lease_token=None)
    fake_repo.runs[str(run_id)]["status"] = RunStatus.NEEDS_OPERATOR.value
    fake_repo.runs[str(run_id)]["error_reason"] = "ClarificationDeliveryReview"

    original = {
        "message_id": snapshot["message_id"],
        "snapshot_id": snapshot["snapshot_id"],
        "reserved_at": snapshot["reserved_at"],
    }
    assert hasattr(repo, "advance_existing_clarification_delivery_review_job_due_now")
    fake_connection = cast(psycopg.Connection[Any], object())
    assert (
        repo.advance_existing_clarification_delivery_review_job_due_now(
            run_id, snapshot["email_id"], conn=fake_connection
        )
        is AdvanceSendJobOutcome.ADVANCED
    )
    assert fake_repo.get_job(claimed.id)["available_in_seconds"] == 0.0
    assert len(fake_repo.jobs) == 1
    assert (
        fake_repo.outbound_snapshots[str(snapshot["email_id"])]
        ["payload"]["body_text"]
        == "Frozen body"
    )
    assert {
        key: fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"])[key]
        for key in original
    } == original


def test_fake_confirmation_retry_rejects_clarification_review(fake_repo) -> None:
    from app.db.repo.jobs import AdvanceSendJobOutcome

    run_id, snapshot, claimed = _seed_send_job(fake_repo, purpose="clarification")
    job = fake_repo.get_job(claimed.id)
    assert job is not None
    job.update(state="pending", lease_token=None, available_in_seconds=45.0)
    fake_repo.runs[str(run_id)]["status"] = RunStatus.NEEDS_OPERATOR.value
    fake_repo.runs[str(run_id)]["error_reason"] = "ClarificationDeliveryReview"
    before_run = dict(fake_repo.load_run(run_id))
    before_snapshot = fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"])
    assert before_snapshot is not None
    before_message_id = before_snapshot["message_id"]
    fake_connection = cast(psycopg.Connection[Any], object())

    assert (
        fake_repo.advance_existing_send_job_due_now(
            run_id, snapshot["email_id"], conn=fake_connection
        )
        is AdvanceSendJobOutcome.MISSING
    )

    assert fake_repo.get_job(claimed.id)["available_in_seconds"] == 45.0
    assert fake_repo.load_run(run_id) == before_run
    after_snapshot = fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"])
    assert after_snapshot == before_snapshot
    assert after_snapshot["message_id"] == before_message_id


def test_fake_header_routing_rejects_stale_epoch_but_keeps_late_observability(fake_repo):
    run_id, snapshot, _claimed = _seed_send_job(
        fake_repo, purpose="clarification", authorize=False
    )
    fake_repo.runs[str(run_id)]["status"] = RunStatus.AWAITING_REPLY.value

    assert (
        fake_repo.find_awaiting_reply_for_header(
            in_reply_to=snapshot["message_id"], references_header=None
        )
        == run_id
    )
    fake_repo.clear_reply_context(run_id)
    assert (
        fake_repo.find_awaiting_reply_for_header(
            in_reply_to=snapshot["message_id"], references_header=None
        )
        is None
    )
    assert (
        fake_repo.find_any_run_for_header(
            in_reply_to=snapshot["message_id"], references_header=None
        )
        == run_id
    )


def test_fake_legacy_email_state_mutation_is_fail_closed(fake_repo):
    with pytest.raises(RuntimeError, match="retired"):
        fake_repo.update_email_message_state("<anything@example.test>", "sent")

    inbound_id, inserted = fake_repo.insert_inbound_email(
        message_id="<inbound@example.test>",
        from_addr="payroll@coastalcleaning.example",
        to_addr="agent@payroll-agent.local",
        subject="Hours",
        body_text="40 hours",
    )
    assert inserted and inbound_id is not None
    with pytest.raises(ValueError, match="outbound"):
        fake_repo.update_email_message_sent("<inbound@example.test>")
