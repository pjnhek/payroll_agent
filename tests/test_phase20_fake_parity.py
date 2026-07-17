"""Default-running regressions for the in-memory SEND_OUTBOUND repository mirror."""

from __future__ import annotations

import uuid

import pytest

from app.models.job import JobKind


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
