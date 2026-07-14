"""Operator approve/reject/retrigger re-entry tests (HITL-01/02/03).

The operator gate is the ONE human gate in the system, so its routes must be safe
against a double-click, a crash mid-delivery, and a transient DB blip:

- approve: CAS claim (AWAITING_APPROVAL → APPROVED), then delivery inside the error
  boundary → 303 POST-redirect-GET to run detail (HITL-02, FOUND-04);
- reject: CAS claim (AWAITING_APPROVAL → REJECTED) → 303 (HITL-01);
- retrigger: claim from ERROR/APPROVED and from stale in-flight states → background
  pipeline → 303 (INGEST-05).

Both approve and reject return a 303 redirect (the tests pass follow_redirects=False so
they can inspect it): a POST-redirect-GET means a browser refresh re-GETs the detail
page instead of re-POSTing the approval.

There are exactly TWO status writers — set_status for uncontended transitions, and
claim_status for the gates (FOUND-04). Every gate write goes through the CAS, so two
concurrent approvals cannot both win.
"""
from __future__ import annotations

# Route/repository monkeypatches intentionally use dynamic test seams.
import uuid
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.models.status import RunStatus
from app.queue import drain


@pytest.fixture
def client(fake_repo):
    from app.main import app

    return TestClient(app, raise_server_exceptions=True)


def _assert_run_pipeline_job_enqueued(fake_repo, run_id: uuid.UUID) -> dict[str, Any]:
    """QUEUE-02: assert retrigger enqueued a durable `jobs` row for this run BEFORE
    any drain happens — this is new coverage for the durable-enqueue half of
    ROADMAP criterion #2, not a workaround for the BackgroundTasks-synchronicity
    assumption these tests used to rely on.

    Returns the matching job row so a caller can additionally assert on its
    dedup_key (the epoch discriminator).
    """
    run = fake_repo.load_run(run_id)
    matching = [j for j in fake_repo.jobs.values() if j["run_id"] == run_id]
    assert len(matching) == 1, (
        f"retrigger must enqueue exactly one run_pipeline job for {run_id}; "
        f"found {len(matching)}"
    )
    job = matching[0]
    assert job["state"] == "pending" and job["kind"] == "run_pipeline", (
        f"expected a pending run_pipeline job; got state={job['state']!r} "
        f"kind={job['kind']!r}"
    )
    expected_dedup_key = f"run_pipeline:{run_id}:{run.get('reply_epoch', 0)}"
    assert job["dedup_key"] == expected_dedup_key, (
        f"the enqueued job's dedup_key must carry the run's CURRENT reply_epoch; "
        f"got {job['dedup_key']!r}, expected {expected_dedup_key!r}"
    )
    return cast(dict[str, Any], job)


def _run_at_awaiting_approval(fake_repo) -> uuid.UUID:
    business_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    run_id: uuid.UUID = fake_repo.create_run(business_id=business_id, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.AWAITING_APPROVAL)
    return run_id


def test_approve_sets_approved_or_reconciled(client, fake_repo):
    """Approve claims the run and either advances it to APPROVED (then _deliver
    advances to RECONCILED on success) or records ERROR on delivery failure.

    Approve claims via CAS (claim_status) and runs delivery synchronously. With no live
    DB/LLM, delivery may legitimately raise here (load_line_items returns an empty list,
    compose_confirmation then raises), which advances the run to ERROR — also a valid
    post-approve terminal state. Either way the route must return 303, never a 500.
    """
    run_id = _run_at_awaiting_approval(fake_repo)
    # follow_redirects=False so we see the 303 directly.
    r = client.post(f"/runs/{run_id}/approve", follow_redirects=False)
    assert r.status_code == 303, (
        f"approve must return 303 POST-redirect-GET; got {r.status_code}"
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


def test_approve_load_run_failure_routes_to_error_not_500(client, fake_repo, monkeypatch):
    """A load_run failure AFTER the CAS claim routes to ERROR, not a raw 500.

    A transient DB/pooler blip between the claim and the delivery leaves the run already
    flipped to APPROVED. If load_run raises OUTSIDE the error boundary, the route 500s
    and the run sits at APPROVED forever with no error_reason and nothing to retrigger —
    exactly the silent hang INGEST-05 forbids. load_run must therefore sit INSIDE the
    try/except that records the error.
    """
    import app.routes.runs as runs_mod

    run_id = _run_at_awaiting_approval(fake_repo)

    # After the claim flips status to APPROVED, the next load_run (inside _deliver's boundary)
    # raises. Let the claim's own status write happen via fake_repo; only the route's load_run
    # raises. Simplest faithful simulation: make load_run raise unconditionally for this test —
    # the claim_status CAS does not depend on load_run, so the claim still succeeds first.
    def _boom(rid, conn=None):
        raise RuntimeError("simulated transient DB failure during load_run")

    monkeypatch.setattr(runs_mod.repo, "load_run", _boom)  # type: ignore[attr-defined]  # patch the route module's own `repo` import binding -- the exact seam approve() calls; mypy cannot see the module attribute

    r = client.post(f"/runs/{run_id}/approve", follow_redirects=False)
    assert r.status_code == 303, (
        f"approve must still 303 (not 500) when load_run fails after claim; got {r.status_code}"
    )
    # Restore load_run so we can inspect the recorded state.
    monkeypatch.undo()
    final = fake_repo.load_run(run_id)
    assert final["status"] == "error", (
        f"a load_run failure after claim must route to ERROR, not stay at APPROVED; "
        f"got {final['status']}"
    )
    assert final.get("error_reason"), "ERROR must carry an error_reason (PII-safe exception type)"


def test_reject_sets_rejected(client, fake_repo):
    """Reject claims the run and redirects to run detail with 303."""
    run_id = _run_at_awaiting_approval(fake_repo)
    r = client.post(f"/runs/{run_id}/reject", follow_redirects=False)
    assert r.status_code == 303, (
        f"reject must return 303 POST-redirect-GET; got {r.status_code}"
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
    """INGEST-05/QUEUE-02: retrigger from ERROR claims the run, enqueues a durable
    job (asserted BEFORE any drain), and the pipeline runs once that job is drained."""
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
    # New coverage: a jobs row exists, and the pipeline has NOT yet run.
    job = _assert_run_pipeline_job_enqueued(fake_repo, run_id)
    assert fake_repo.load_run(run_id)["status"] == "received", (
        "before draining, the run must sit at the claimed status (received), "
        "not have already advanced — proving the enqueue, not an inline run, "
        "is what the route did"
    )
    assert drain.drain_once() is True, (
        "drain_once must claim and dispatch the job retrigger enqueued"
    )
    assert fake_repo.jobs[str(job["id"])]["state"] == "done", (
        "after drain, the drained job must be marked done — the pipeline has run "
        "(no mock_llm fixture here, so the run's own error boundary is free to "
        "land it wherever it lands; the job's completion is what this test pins)"
    )
    assert fake_repo.load_run(run_id)["status"] != "received", (
        "after drain, the handler's forward CAS must have advanced the run off "
        "its claimed RECEIVED status"
    )


def test_retrigger_from_approved_backgrounds_pipeline(client, fake_repo):
    """Retrigger from APPROVED — where a run lands if delivery died before recording
    an error — must be accepted, or the run is unrecoverable. QUEUE-02: the enqueued
    job is asserted before drain, then drained to prove the pipeline actually runs."""
    business_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.APPROVED)
    r = client.post(f"/runs/{run_id}/retrigger", follow_redirects=False)
    assert r.status_code == 303, (
        f"retrigger from APPROVED must return 303; got {r.status_code}"
    )
    _assert_run_pipeline_job_enqueued(fake_repo, run_id)
    assert drain.drain_once() is True, (
        "drain_once must claim and dispatch the job retrigger enqueued"
    )


def test_second_retrigger_enqueues_a_second_job(client, fake_repo, monkeypatch):
    """QUEUE-02: the dedup_key's epoch is what lets a SECOND, later retrigger enqueue
    a SECOND job rather than being silently swallowed by ON CONFLICT DO NOTHING
    against the first retrigger's now-done job row.

    This is the falsifying-mutation target for the dedup_key's epoch: strip the epoch
    from retrigger's dedup_key and this test must go red (see the SUMMARY for the
    captured red run).
    """
    import app.routes.pipeline_glue as app_main

    monkeypatch.setattr(app_main, "run_pipeline_bg", lambda rid: None)

    business_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.ERROR)

    # First retrigger: enqueue + drain to done.
    r1 = client.post(f"/runs/{run_id}/retrigger", follow_redirects=False)
    assert r1.status_code == 303
    first_job = _assert_run_pipeline_job_enqueued(fake_repo, run_id)
    assert drain.drain_once() is True
    assert fake_repo.jobs[str(first_job["id"])]["state"] == "done", (
        "sanity: the first job must be done before the second retrigger fires, or "
        "this test cannot distinguish 'a second job was enqueued' from 'the first "
        "job was still pending'"
    )

    # Put the run back in ERROR (as a real second failure would) and retrigger again.
    fake_repo.set_status(run_id, RunStatus.ERROR)
    r2 = client.post(f"/runs/{run_id}/retrigger", follow_redirects=False)
    assert r2.status_code == 303

    matching = [j for j in fake_repo.jobs.values() if j["run_id"] == run_id]
    assert len(matching) == 2, (
        f"a second retrigger must enqueue a SECOND run_pipeline job for {run_id} — "
        f"found {len(matching)} job(s) total. If this is 1, the second enqueue was "
        "silently swallowed by ON CONFLICT DO NOTHING against the first retrigger's "
        "now-done job row (the epoch-less dedup_key bug)"
    )
    second_job = next(j for j in matching if j["id"] != first_job["id"])
    assert second_job["dedup_key"] != first_job["dedup_key"], (
        f"the second job's dedup_key must differ from the first's; both were "
        f"{first_job['dedup_key']!r}"
    )
    assert second_job["state"] == "pending"


def test_approve_forwards_deliver_roster_to_record_run_error(client, fake_repo, monkeypatch):
    """approve() forwards the delivery exception's stashed roster to record_run_error.

    When delivery raises an exception carrying the roster it had already loaded
    (exc.payroll_roster), the approve() error boundary must pass that roster through to
    record_run_error, or _scrub has no names to redact and employee names land in a
    dashboard-rendered error_detail.

    This traces the ARGUMENT FLOW across the boundary via an identity check on a
    sentinel — asserting merely that record_run_error was CALLED would pass even if the
    roster were dropped on the way.
    """
    import app.db.repo as repo_mod
    from app.pipeline import delivery as orch

    run_id = _run_at_awaiting_approval(fake_repo)
    sentinel_roster = object()  # identity check — must arrive unchanged

    def _deliver_boom(rid, run):
        exc = RuntimeError("gateway exploded sending Maria Chen's paystub")
        exc.payroll_roster = sentinel_roster  # type: ignore[attr-defined]  # mirrors delivery.py stashing the loaded roster onto an arbitrary exception; RuntimeError has no such attribute declared
        raise exc

    monkeypatch.setattr(orch, "deliver", _deliver_boom)

    captured = {}

    def _spy(rid, reason, conn=None, *, detail_exc=None, stage=None, roster=None):
        captured["roster"] = roster
        captured["stage"] = stage
        captured["reason"] = reason

    monkeypatch.setattr(repo_mod, "record_run_error", _spy)

    r = client.post(f"/runs/{run_id}/approve", follow_redirects=False)
    assert r.status_code == 303

    assert captured.get("roster") is sentinel_roster, (
        "approve() must forward exc.payroll_roster (the roster delivery already loaded) "
        "to record_run_error's roster= kwarg, or employee names cannot be scrubbed"
    )
    assert captured.get("stage") == "delivery"
    assert captured.get("reason") == "RuntimeError"


def test_approve_without_roster_on_exception_passes_none(client, fake_repo, monkeypatch):
    """An exception WITHOUT payroll_roster must pass roster=None.

    This is the shape of a failure that happened before delivery loaded a roster (or of
    load_run itself failing). The boundary must pass None rather than fetching a roster
    of its own: an error handler that hits the DB can fail a second time — or hang —
    while trying to report the first failure.
    """
    import app.db.repo as repo_mod
    from app.pipeline import delivery as orch

    run_id = _run_at_awaiting_approval(fake_repo)

    def _deliver_boom(rid, run):
        raise RuntimeError("failure before the roster load")

    monkeypatch.setattr(orch, "deliver", _deliver_boom)

    captured = {}

    def _spy(rid, reason, conn=None, *, detail_exc=None, stage=None, roster=None):
        captured["roster"] = roster

    monkeypatch.setattr(repo_mod, "record_run_error", _spy)

    r = client.post(f"/runs/{run_id}/approve", follow_redirects=False)
    assert r.status_code == 303
    assert captured.get("roster") is None, (
        "with no payroll_roster on the exception, approve() must pass "
        "roster=None — the error path never loads a roster itself"
    )
