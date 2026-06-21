"""Operator approve/reject re-entry tests (HITL-01; FIX B).

A run at awaiting_approval → crude approve sets APPROVED via repo.set_status;
reject sets REJECTED. This proves the gate PAUSES and RESUMES — the operator pause.
No confirmation email / PDF / FOR-UPDATE guard (HITL-02/03 / FOUND-04 = Phase 5).
All status writes go through the sole set_status writer (FIX B).
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.models.status import RunStatus


@pytest.fixture
def client(fake_repo):
    from app.main import app

    return TestClient(app)


def _run_at_awaiting_approval(fake_repo) -> uuid.UUID:
    business_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.AWAITING_APPROVAL)
    return run_id


def test_approve_sets_approved(client, fake_repo):
    run_id = _run_at_awaiting_approval(fake_repo)
    r = client.post(f"/runs/{run_id}/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert fake_repo.load_run(run_id)["status"] == "approved"


def test_reject_sets_rejected(client, fake_repo):
    run_id = _run_at_awaiting_approval(fake_repo)
    r = client.post(f"/runs/{run_id}/reject")
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert fake_repo.load_run(run_id)["status"] == "rejected"


def test_approve_requires_awaiting_approval(client, fake_repo):
    """A run not at awaiting_approval cannot be approved (crude guard)."""
    business_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.RECEIVED)
    r = client.post(f"/runs/{run_id}/approve")
    assert r.status_code == 409


def test_approve_unknown_run_404(client, fake_repo):
    r = client.post(f"/runs/{uuid.uuid4()}/approve")
    assert r.status_code == 404
