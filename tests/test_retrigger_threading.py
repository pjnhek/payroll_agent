"""Reply threading survives a crash and an operator retrigger.

WHAT THIS FILE PROVES, AND WHAT IT DOES NOT
-------------------------------------------
It drives real code end to end: the real POST /runs/{run_id}/retrigger route, the
real background pipeline the route schedules, the real clarify stage, and the real
email gateway. The crashed state it recovers from is produced by real code too — a
one-shot failure injected at the first persistence step AFTER the clarification email
has already been sent, with the background consumer settling the producer's bounded
failure result to ERROR.

The persistence it observes, however, is the IN-MEMORY test repo: the `fake_repo`
fixture patches the whole `app.db.repo` surface, `insert_email_message` included, so
the upsert these tests watch is the fixture's hand-written Python, not the production
SQL. The claims here are therefore scoped to three seams and no more:

  * the retrigger route claims the run and resumes the pipeline,
  * the pipeline reaches the send again,
  * the gateway derives the outbound threading headers from the client's ORIGINAL
    inbound Message-ID, so the conversation stays one thread across the crash.

The production `(run_id, purpose, round, epoch)` upsert arbiter — the thing that
decides whether the retriggered send APPENDS a row or overwrites the one already
delivered — is a SQL fact and is proven against real Postgres in
tests/test_email_epoch_arbiter_integration.py. Nothing in this module is evidence
about that arbiter.

The `pytest.raises` idiom is deliberately absent: the background wrapper swallows
exceptions and the orchestrator's error boundary does not re-raise, so an exception
is not an observable here. Persisted state is the only honest oracle.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.queue import drain
from app.queue.drain import DrainOutcome

# The seeded business whose roster the run is scored against.
COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"

# The client's original inbound Message-ID. Every outbound email on this run must
# anchor its thread here — before the crash and, above all, after the retrigger.
CLIENT_THREAD_ANCHOR = "<client-inbound-thread-anchor@example.test>"

# A submitted name that matches nothing on the Coastal roster, so the deterministic
# decision is request_clarification and the clarify stage (the stage that sends) runs.
UNRESOLVED_NAME = "Marisol Chenn"

_DRAFT_BODY = "Which employee on your roster did you mean?"


@pytest.fixture
def client(fake_repo):
    from app.main import app

    return TestClient(app, raise_server_exceptions=True)


def _extraction_payload() -> str:
    """The scripted model reading of the client's email (one unresolved name)."""
    return json.dumps(
        {
            "employees": [{"submitted_name": UNRESOLVED_NAME, "hours_regular": "40"}],
            "pay_period_start": None,
            "pay_period_end": None,
        }
    )


class _FailFirstCallOnly:
    """Raise once, then delegate to the real function forever after.

    Armed on the first persistence step that runs AFTER the gateway has returned, so
    when it fires the clarification email is already recorded as sent and the run's
    status has not yet advanced. That is precisely the window a real crash between a
    delivered email and its bookkeeping opens. It fails once and only once, so the
    background consumer can still settle the producer's terminal result to ERROR, and
    the later recovery pass runs against unmodified behavior.
    """

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.fired = False

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if not self.fired:
            self.fired = True
            raise RuntimeError("persistence interrupted after the email was sent")
        return self._delegate(*args, **kwargs)


def _seed_client_email_and_run(fake_repo: Any) -> uuid.UUID:
    """Persist the client's inbound email (carrying the anchor) and a run for it."""
    email_id, inserted = fake_repo.insert_inbound_email(
        message_id=CLIENT_THREAD_ANCHOR,
        in_reply_to=None,
        references_header=None,
        subject="Payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text=f"{UNRESOLVED_NAME} worked 40 hours this week.",
    )
    assert inserted, "the client's inbound email must be a fresh row, not a duplicate"
    run_id: uuid.UUID = fake_repo.create_run(
        business_id=COASTAL_BIZ_ID, source_email_id=email_id
    )
    return run_id


def _crash_after_send_then_retrigger(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    fake_repo: Any,
    mock_llm: Any,
) -> tuple[uuid.UUID, list[dict[str, Any]], dict[str, Any]]:
    """Drive a real run to a post-send crash, then recover it through the real route.

    Returns the run id, every captured gateway send call, and a snapshot of the
    outbound row that was already delivered before the crash.
    """
    import app.db.repo as repo_mod
    import app.email.gateway as gateway_mod
    import app.pipeline.clarification as clarification_mod
    from app.routes import pipeline_glue

    run_id = _seed_client_email_and_run(fake_repo)

    # The suggestion call is advisory copy only and is the one seam that would reach a
    # real provider with real credentials — pin it to a fixed answer.
    monkeypatch.setattr(
        clarification_mod, "suggest_employees", lambda names, roster, **kw: {}
    )

    # Watch the gateway without replacing it: every call is recorded and then handed
    # to the real function, so the real threading-header derivation still executes.
    send_calls: list[dict[str, Any]] = []
    real_send_outbound = gateway_mod.send_outbound

    def _watch_send_outbound(**kwargs: Any) -> str:
        send_calls.append(kwargs)
        return real_send_outbound(**kwargs)

    monkeypatch.setattr(gateway_mod, "send_outbound", _watch_send_outbound)

    # Two passes through the pipeline: the crashed one and the recovered one. Each
    # reads the email once and drafts the clarification once.
    mock_llm.script = [
        _extraction_payload(),
        _DRAFT_BODY,
        _extraction_payload(),
        _DRAFT_BODY,
    ]

    real_snapshot_step = repo_mod.set_pre_clarify_extracted
    fail_once = _FailFirstCallOnly(real_snapshot_step)
    monkeypatch.setattr(repo_mod, "set_pre_clarify_extracted", fail_once)

    # The crash pass exercises the explicit value seam directly. The durable drain is
    # the only PipelineResult consumer; this focused threading test needs only the
    # bounded terminal value plus the persisted ERROR/thread state it already protects.
    result = pipeline_glue.run_pipeline_now(run_id)
    assert result.outcome.value == "terminal"
    repo_mod.settle_background_terminal(run_id, result)

    monkeypatch.setattr(repo_mod, "set_pre_clarify_extracted", real_snapshot_step)

    assert fail_once.fired, (
        "the injected failure never fired — the pipeline did not reach the "
        "post-send persistence step, so no crash was actually produced"
    )
    assert fake_repo.runs[str(run_id)]["status"] == "error", (
        "a failure after the clarification was sent must leave the run in error, "
        "which is the state the operator retriggers from"
    )

    delivered = fake_repo.outbound[str(run_id)]
    assert len(delivered) == 1, (
        f"exactly one clarification email should have gone out before the crash; "
        f"found {len(delivered)}"
    )
    pre_crash_row = dict(delivered[0])
    assert pre_crash_row["purpose"] == "clarification"
    assert pre_crash_row["send_state"] == "sent", (
        "the crash must land after the email was actually delivered — otherwise "
        "there is no delivered email whose thread the retrigger could break"
    )
    assert pre_crash_row["round"] == 0
    assert pre_crash_row["epoch"] == 0

    # The recovery pass: the operator's real button. QUEUE-02: retrigger no longer
    # schedules a BackgroundTask — it enqueues a durable jobs row inside the same
    # transaction as the winning claim. Workers are off in this suite, so drain the
    # queue explicitly to run the real pipeline the route enqueued — deterministic,
    # no sleeps, no flakes, and it exercises the exact function a live worker calls.
    response = client.post(f"/runs/{run_id}/retrigger", follow_redirects=False)
    assert response.status_code == 303, (
        f"the retrigger route must redirect back to the run; got {response.status_code}"
    )
    matching = [j for j in fake_repo.jobs.values() if j["run_id"] == run_id]
    assert len(matching) == 1, (
        f"retrigger must enqueue exactly one run_pipeline job for {run_id}; "
        f"found {len(matching)}"
    )
    assert matching[0]["state"] == "pending" and matching[0]["kind"] == "run_pipeline"

    assert drain.drain_once() == DrainOutcome.DONE, (
        "drain_once must claim and dispatch the job retrigger enqueued"
    )

    return run_id, send_calls, pre_crash_row


def test_retriggered_send_still_anchors_the_clients_original_thread(
    monkeypatch, client, fake_repo, mock_llm
) -> None:
    """The email sent after recovery replies to the client's ORIGINAL message.

    If the retriggered send lost the anchor, the client would receive an email that
    their mail reader files as a brand-new conversation — the question about their
    payroll would arrive detached from the payroll they emailed about.

    Asserted twice over, because the call and the record can disagree: on the
    arguments the gateway was actually invoked with, and on the outbound row the
    system persisted for that send.
    """
    run_id, send_calls, _pre_crash_row = _crash_after_send_then_retrigger(
        monkeypatch, client, fake_repo, mock_llm
    )

    assert len(send_calls) == 2, (
        "the retriggered run must send its clarification again — one send before the "
        f"crash and one after recovery; got {len(send_calls)} send(s) in total"
    )
    recovered_send = send_calls[-1]
    assert recovered_send["in_reply_to"] == CLIENT_THREAD_ANCHOR, (
        "the email sent after recovery must reply to the client's original message; "
        f"it replied to {recovered_send['in_reply_to']!r} instead"
    )
    assert CLIENT_THREAD_ANCHOR in (recovered_send["references_header"] or ""), (
        "the references chain on the recovered send must still contain the client's "
        "original message, or the thread is broken for every mail reader that walks "
        "the chain rather than the single in-reply-to header"
    )

    rows = fake_repo.outbound[str(run_id)]
    recovered_row = rows[-1]
    assert recovered_row["send_state"] == "sent"
    assert recovered_row["in_reply_to"] == CLIENT_THREAD_ANCHOR, (
        "the persisted record of the recovered send must carry the client's original "
        "message as its in-reply-to; the record is what later replies are matched "
        "against, so a wrong value here strands the client's answer"
    )
    assert CLIENT_THREAD_ANCHOR in (recovered_row["references_header"] or ""), (
        "the persisted references chain of the recovered send must contain the "
        "client's original message"
    )

    assert fake_repo.runs[str(run_id)]["status"] == "awaiting_reply", (
        "after the retrigger the run must be waiting on the client again, which is "
        "the proof the recovered pipeline ran all the way through the send"
    )


def test_retrigger_writes_a_fresh_send_and_leaves_the_delivered_one_alone(
    monkeypatch, client, fake_repo, mock_llm
) -> None:
    """Recovery adds a record of the new email; it does not rewrite the old one.

    An email that was really delivered to the client must stay in the log exactly as
    it was delivered. Rewriting that record in place would mean the system's own
    history of what it sent no longer matches what the client received.

    Scope note, stated plainly: the persistence observed here is the in-memory test
    repo, so this pins the ROUTE and the GATEWAY (a fresh send happens, and it is
    written as a new record rather than addressed to the old one). Whether the
    PRODUCTION SQL upsert appends or clobbers is a different question, answered
    against real Postgres in tests/test_email_epoch_arbiter_integration.py.
    """
    run_id, _send_calls, pre_crash_row = _crash_after_send_then_retrigger(
        monkeypatch, client, fake_repo, mock_llm
    )

    rows = fake_repo.outbound[str(run_id)]
    assert len(rows) == 2, (
        "the delivered email and the recovered one must BOTH be recorded; "
        f"found {len(rows)} outbound row(s), which means one send overwrote the other"
    )

    still_there = rows[0]
    for field in ("message_id", "round", "epoch", "send_state"):
        assert still_there[field] == pre_crash_row[field], (
            f"the record of the already-delivered email had its {field} rewritten by "
            f"the recovery pass ({pre_crash_row[field]!r} became {still_there[field]!r}); "
            "an email the client already received must never be edited after the fact"
        )

    fresh = rows[-1]
    assert fresh["epoch"] > pre_crash_row["epoch"], (
        "the recovered send must be recorded as belonging to a later conversation "
        "than the one that crashed; sharing the old conversation's key is exactly "
        "what would let it overwrite the delivered email's record"
    )
    assert fresh["message_id"] != pre_crash_row["message_id"], (
        "the recovered send is a genuinely new email and must carry its own identity"
    )
