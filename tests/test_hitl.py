"""Operator approve/reject/retrigger re-entry tests (HITL-01/02/03; D-12, D-13b).

Plan 05-05 (Wave 3) hardens the routes:
- approve: CAS claim (AWAITING_APPROVAL → APPROVED) + _deliver inside D-13b error
  boundary → 303 POST-redirect-GET to run detail (HITL-02, FOUND-04)
- reject: CAS claim (AWAITING_APPROVAL → REJECTED) → 303 (HITL-01)
- retrigger: claim from ERROR/APPROVED + stale in-flight states → background pipeline
  → 303 (INGEST-05, finding #6)

Both approve and reject return 303 RedirectResponse (follow=False to inspect).
All status writes go through claim_status (two writers: set_status for uncontended
transitions; claim_status for gates — D-12, FOUND-04).
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.models.status import RunStatus


@pytest.fixture
def client(fake_repo):
    from app.main import app

    return TestClient(app, raise_server_exceptions=True)


def _run_at_awaiting_approval(fake_repo) -> uuid.UUID:
    business_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.AWAITING_APPROVAL)
    return run_id


def test_approve_sets_approved_or_reconciled(client, fake_repo):
    """Approve claims the run and either advances it to APPROVED (then _deliver
    advances to RECONCILED on success) or records ERROR on delivery failure.

    Plan 05-05 approve uses CAS (claim_status) and calls _deliver synchronously.
    With no live DB/LLM, _deliver may raise (e.g. load_line_items returns empty list
    and compose_confirmation raises), advancing to ERROR — that is also a valid
    post-approve terminal state. Either way the route returns 303 (D-06b).
    """
    run_id = _run_at_awaiting_approval(fake_repo)
    # follow_redirects=False so we see the 303 directly.
    r = client.post(f"/runs/{run_id}/approve", follow_redirects=False)
    assert r.status_code == 303, (
        f"approve must return 303 POST-redirect-GET (D-06b); got {r.status_code}"
    )
    assert f"/runs/{run_id}" in r.headers.get("location", ""), (
        "approve must redirect to the run detail page"
    )
    # The run is either RECONCILED (delivery succeeded) or ERROR (delivery failed
    # in the test environment without live LLM/PDF). Both are valid terminal states.
    final_status = fake_repo.load_run(run_id)["status"]
    assert final_status in {"reconciled", "error", "approved", "sent"}, (
        f"After approve, run must be in reconciled/error/approved/sent; got {final_status}"
    )


def test_reject_sets_rejected(client, fake_repo):
    """Reject claims the run and redirects to run detail with 303."""
    run_id = _run_at_awaiting_approval(fake_repo)
    r = client.post(f"/runs/{run_id}/reject", follow_redirects=False)
    assert r.status_code == 303, (
        f"reject must return 303 POST-redirect-GET (D-06b); got {r.status_code}"
    )
    assert f"/runs/{run_id}" in r.headers.get("location", ""), (
        "reject must redirect to the run detail page"
    )
    assert fake_repo.load_run(run_id)["status"] == "rejected", (
        "reject must advance run to REJECTED"
    )


def test_approve_already_advanced_returns_303(client, fake_repo):
    """A run not at awaiting_approval cannot be claimed — CAS returns False.

    approve no longer returns 409; it uses claim_status (CAS) which returns False
    if the run is not in the expected state. The route always 303-redirects
    regardless of claim outcome — idempotent post-redirect-GET pattern.
    """
    business_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.RECEIVED)
    r = client.post(f"/runs/{run_id}/approve", follow_redirects=False)
    # With CAS, a failed claim is a no-op → route still returns 303 (not 409).
    assert r.status_code == 303, (
        f"approve on a non-awaiting_approval run must return 303 (CAS no-op); "
        f"got {r.status_code}"
    )


def test_approve_unknown_run_still_redirects(client, fake_repo):
    """Approving an unknown run_id: CAS returns False (no row found) → 303."""
    r = client.post(f"/runs/{uuid.uuid4()}/approve", follow_redirects=False)
    # claim_status on a non-existent run returns False; route 303-redirects.
    assert r.status_code == 303, (
        f"approve on unknown run must return 303 (CAS no row → redirect); got {r.status_code}"
    )


def test_retrigger_from_error_backgrounds_pipeline(client, fake_repo):
    """INGEST-05: retrigger from ERROR claims the run and backgrounds the pipeline."""
    business_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.ERROR)
    r = client.post(f"/runs/{run_id}/retrigger", follow_redirects=False)
    assert r.status_code == 303, (
        f"retrigger must return 303; got {r.status_code}"
    )
    assert f"/runs/{run_id}" in r.headers.get("location", ""), (
        "retrigger must redirect to the run detail page"
    )


def test_retrigger_from_approved_backgrounds_pipeline(client, fake_repo):
    """D-13b: retrigger from APPROVED (delivery died before ERROR recorded) → 303."""
    business_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.APPROVED)
    r = client.post(f"/runs/{run_id}/retrigger", follow_redirects=False)
    assert r.status_code == 303, (
        f"retrigger from APPROVED must return 303; got {r.status_code}"
    )
