"""WR-04 redelivery + D-11-05 stranded auto-resume tests (CLAR2-06, Plan 11-05).

WHY THIS LIVES IN ITS OWN MODULE (NOT tests/test_resume_pipeline.py):
tests/test_resume_pipeline.py carries a MODULE-LEVEL conditional-skip marker
gated on `os.environ.get("DATABASE_URL")` being unset (see
tests/test_multiround_context_edge.py's docstring for the verified detail).
That marker silently skips the ENTIRE module offline. This module is genuinely
hermetic (fake_repo + a monkeypatched _resume_pipeline spy only, no live DB/
LLM) and must run unconditionally offline, so it carries NO module-level
conditional-skip marker of any kind.

WHAT THIS MODULE PROVES (assert REAL re-schedule facts, never a log string):
  1. unconsumed redelivery reschedules: a redelivered webhook whose persisted
     reply row is still unconsumed AND whose run is still awaiting_reply
     re-schedules _resume_pipeline with the run_id and a _row_to_inbound-built
     reply whose body_text equals the PERSISTED (already-cleaned) body — never
     re-cleaned from the redelivered request (D-11-03, Pitfall #11a).
  2. consumed redelivery no-ops: the same seed, but consumed_round is already
     set — NO re-schedule; the duplicate JSONResponse is still returned.
  3. redelivery to a non-awaiting_reply run no-ops: reply row unconsumed but
     the run already advanced (e.g. reconciled) — NO re-schedule.
  4. runs-list stranded auto-resume: GET /runs re-schedules _resume_pipeline
     for a stale unconsumed reply against an awaiting_reply run; a FRESH
     unconsumed reply (not past the stale threshold) is NOT scheduled (D-11-05).
  5. needs_operator excluded (D-11-06): a needs_operator run with a stale
     unconsumed reply is NEVER re-scheduled by the runs-list load — the query
     scope structurally excludes it.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models.contracts import InboundEmail
from app.models.status import RunStatus

COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"


@pytest.fixture
def client(fake_repo, monkeypatch):
    """TestClient with ALLOW_UNSIGNED_FIXTURES=true so canonical dict POSTs
    succeed in mocked tests (matches tests/test_threading.py's client fixture)."""
    from app.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    yield TestClient(app)
    get_settings.cache_clear()


@pytest.fixture
def resume_spy(monkeypatch):
    """Monkeypatch app.routes.pipeline_glue.resume_pipeline_bg to a spy that
    records calls instead of driving the real orchestrator — this module
    only needs to prove WHETHER/WITH-WHAT a re-schedule happened, not
    exercise the full resume pipeline (that is test_combined_context.py's
    job)."""
    import app.routes.pipeline_glue as pipeline_glue_mod

    calls: list[tuple[uuid.UUID, InboundEmail]] = []

    def _spy(run_id, inbound):
        calls.append((run_id, inbound))

    monkeypatch.setattr(pipeline_glue_mod, "resume_pipeline_bg", _spy)
    return calls


def _seed_awaiting_reply_run_with_reply(
    fake_repo,
    *,
    message_id: str,
    consumed: bool = False,
    run_status: str = "awaiting_reply",
    created_at: datetime | None = None,
    reply_from_addr: str | None = None,
) -> tuple[uuid.UUID, dict[str, Any]]:
    """Seed a run + a persisted, LINKED inbound reply row against it.

    Mirrors the real webhook's insert_inbound_email + link_email_to_run
    sequence (WR-03) — the exact shape get_inbound_by_message_id/
    find_stranded_unconsumed_replies read at runtime. Returns (run_id, row).

    `reply_from_addr` (GAP-5/CR-5): override for the LINKED REPLY row's
    from_addr only — the run's owning business is still seeded via
    COASTAL_EMAIL/COASTAL_BIZ_ID. Defaults to COASTAL_EMAIL (sender-matching,
    the pre-existing behavior every pre-Plan-11-10 test in this file relies
    on) so this override is purely additive — no existing call site changes
    shape or behavior.
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
    if created_at is not None:
        row["created_at"] = created_at
    if consumed:
        fake_repo.mark_reply_consumed(message_id, round=0)
    return run_id, row


# ---------------------------------------------------------------------------
# 1. unconsumed redelivery reschedules (D-11-03)
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
    assert r.json()["status"] == "duplicate"

    assert len(resume_spy) == 1, (
        "an unconsumed redelivery to an awaiting_reply run must re-schedule "
        f"_resume_pipeline exactly once; got {len(resume_spy)} calls"
    )
    scheduled_run_id, scheduled_inbound = resume_spy[0]
    assert str(scheduled_run_id) == str(run_id)
    assert scheduled_inbound.body_text == row["body_text"], (
        "the scheduled reply's body_text must equal the PERSISTED (already-"
        "cleaned) body, never a re-cleaned copy of the redelivered request "
        f"body (Pitfall #11a); got {scheduled_inbound.body_text!r}"
    )
    assert (
        scheduled_inbound.body_text
        != "a completely different redelivered body — must be ignored"
    )


# ---------------------------------------------------------------------------
# 2. consumed redelivery no-ops (D-11-03)
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
    assert r.json()["status"] == "duplicate"

    assert resume_spy == [], (
        "a redelivery of an ALREADY-consumed reply must stay a no-op — "
        f"got {len(resume_spy)} unexpected re-schedule(s)"
    )


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
    assert r.json()["status"] == "duplicate"

    assert resume_spy == [], (
        "a redelivery whose linked run is NOT awaiting_reply must NOT "
        f"re-schedule; got {len(resume_spy)} unexpected re-schedule(s)"
    )


# ---------------------------------------------------------------------------
# 4. runs-list stranded auto-resume (D-11-05)
# ---------------------------------------------------------------------------


def test_runs_list_reschedules_stale_unconsumed_reply(client, fake_repo, resume_spy):
    """GET /runs re-schedules _resume_pipeline for a stale unconsumed reply
    against an awaiting_reply run (D-11-05)."""
    from app.routes.runs import STALE_THRESHOLD_SECONDS

    message_id = f"<stranded-{uuid.uuid4()}@metrodeli.example>"
    old_created_at = datetime.now(UTC) - timedelta(
        seconds=STALE_THRESHOLD_SECONDS + 60
    )
    run_id, row = _seed_awaiting_reply_run_with_reply(
        fake_repo,
        message_id=message_id,
        consumed=False,
        created_at=old_created_at,
    )

    r = client.get("/runs")
    assert r.status_code == 200

    assert len(resume_spy) == 1, (
        "a stale unconsumed reply against an awaiting_reply run must be "
        f"re-scheduled on the runs-list load; got {len(resume_spy)} calls"
    )
    scheduled_run_id, scheduled_inbound = resume_spy[0]
    assert str(scheduled_run_id) == str(run_id)
    assert scheduled_inbound.body_text == row["body_text"]


def test_runs_list_does_not_reschedule_fresh_unconsumed_reply(
    client, fake_repo, resume_spy
):
    """A FRESH unconsumed reply (not past the stale threshold) must NOT be
    re-scheduled — only genuinely stranded replies qualify (D-11-05)."""
    message_id = f"<fresh-{uuid.uuid4()}@metrodeli.example>"
    _run_id, _row = _seed_awaiting_reply_run_with_reply(
        fake_repo,
        message_id=message_id,
        consumed=False,
        created_at=datetime.now(UTC),
    )

    r = client.get("/runs")
    assert r.status_code == 200

    assert resume_spy == [], (
        "a FRESH (not-yet-stale) unconsumed reply must NOT be re-scheduled "
        f"by the runs-list load; got {len(resume_spy)} unexpected re-schedule(s)"
    )


# ---------------------------------------------------------------------------
# 5. needs_operator excluded (D-11-06)
# ---------------------------------------------------------------------------


def test_runs_list_never_reschedules_needs_operator_run(client, fake_repo, resume_spy):
    """A needs_operator run with a stale unconsumed reply must NEVER be
    re-scheduled by the runs-list load — the query scope structurally
    excludes it (D-11-06: needs_operator exits only via /resolve or reject)."""
    from app.routes.runs import STALE_THRESHOLD_SECONDS

    message_id = f"<needs-operator-{uuid.uuid4()}@metrodeli.example>"
    old_created_at = datetime.now(UTC) - timedelta(
        seconds=STALE_THRESHOLD_SECONDS + 60
    )
    _run_id, _row = _seed_awaiting_reply_run_with_reply(
        fake_repo,
        message_id=message_id,
        consumed=False,
        run_status="needs_operator",
        created_at=old_created_at,
    )

    r = client.get("/runs")
    assert r.status_code == 200

    assert resume_spy == [], (
        "a needs_operator run must NEVER be auto-resumed by the runs-list "
        f"load (D-11-06); got {len(resume_spy)} unexpected re-schedule(s)"
    )


# ---------------------------------------------------------------------------
# 6. GAP-5/CR-5: a FIX-5-failed linked reply is NEVER re-resumed by either seam
# ---------------------------------------------------------------------------

SPOOFED_FROM_ADDR = "attacker@evil.example"


def test_redelivery_never_resumes_sender_mismatched_reply(client, fake_repo, resume_spy):
    """GAP-5/CR-5 regression: a reply linked to a run via the RFC header chain,
    whose from_addr does NOT match the run's business (i.e. it already failed
    FIX-5 sender revalidation on first delivery and was left linked+unconsumed),
    must NEVER be re-resumed by a subsequent redelivery of the same message_id.

    MUST FAIL before the fix (the WR-04 branch only checked consumed_round/
    status, never the sender) and MUST PASS after (_reply_sender_ok re-asserted
    before the redelivery dispatch)."""
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
    assert r.json()["status"] == "duplicate"

    assert resume_spy == [], (
        "a reply that already failed FIX-5 sender revalidation must NEVER be "
        f"resumed via redelivery (GAP-5/CR-5); got {len(resume_spy)} unexpected "
        "re-schedule(s)"
    )
    assert str(run_id) in fake_repo.runs, "sanity: run must exist and be untouched"


def test_stranded_sweep_never_resumes_sender_mismatched_reply(client, fake_repo, resume_spy):
    """GAP-5/CR-5 regression: the SAME mismatched-sender, unconsumed,
    awaiting_reply, STALE reply must NEVER be auto-resumed by the D-11-05
    stranded-reply sweep on a GET /runs dashboard load either.

    MUST FAIL before the fix (the sweep loop only checked consumed_round/
    run_id/status, never the sender) and MUST PASS after."""
    from app.routes.runs import STALE_THRESHOLD_SECONDS

    message_id = f"<stranded-spoofed-{uuid.uuid4()}@metrodeli.example>"
    old_created_at = datetime.now(UTC) - timedelta(
        seconds=STALE_THRESHOLD_SECONDS + 60
    )
    run_id, _row = _seed_awaiting_reply_run_with_reply(
        fake_repo,
        message_id=message_id,
        consumed=False,
        created_at=old_created_at,
        reply_from_addr=SPOOFED_FROM_ADDR,
    )

    r = client.get("/runs")
    assert r.status_code == 200

    assert resume_spy == [], (
        "a reply that already failed FIX-5 sender revalidation must NEVER be "
        f"auto-resumed by the stranded-reply sweep (GAP-5/CR-5); got "
        f"{len(resume_spy)} unexpected re-schedule(s)"
    )
    assert str(run_id) in fake_repo.runs, "sanity: run must exist and be untouched"
