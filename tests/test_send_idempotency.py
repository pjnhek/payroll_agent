"""The fail-closed unconfirmed-send guard: proven to bite, proven not to bite on the
happy path, proven epoch-scoped against real SQL, and proven decorative-guard-proof.

WHY THIS FILE EXISTS
---------------------
`gateway.send_outbound` commits a `reserved` outbound row BEFORE calling the email
provider and only flips it to `sent` AFTER the provider call returns. A worker killed
in that window leaves no `sent` row while the client already has the email. Every
PRE-EXISTING duplicate guard (`get_outbound_message_id`, `get_outbound_for_round`)
counts only `sent` rows, so a naive rerun of a rewound run would silently email the
client a second time. `app/pipeline/send_guard.py` closes that window: an unconfirmed
(`reserved`/`failed`) row in the run's CURRENT epoch means the provider MAY already hold
the message, so the pipeline refuses to send again and escalates instead.

TWO SECTIONS
------------
Section A is hermetic (fake_repo + mock_llm, no DB, no marker) — the fast feedback loop
and the falsifying-mutation target. Section B drives the SAME predicate against real SQL
(`@pytest.mark.integration` + `@pytest.mark.queueproof`, `seeded_db`), because the epoch
scoping is a safety property a hand-written fake will happily mimic whatever it is told
and cannot itself prove.

NO LIVE PROVIDER CALL ANYWHERE IN THIS FILE. This repo's `.env` carries live Resend and
LLM keys; every send in every test here is spied or stubbed.
"""

from __future__ import annotations

import inspect
import json
import os
import pathlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.db import repo
from app.models.contracts import InboundEmail
from app.pipeline.result import PipelineReason
from app.pipeline.send_guard import UnconfirmedSendError
from app.routes import pipeline_glue

_HAS_DB = bool(os.environ.get("DATABASE_URL"))
_HAS_RESET = os.environ.get("ALLOW_DB_RESET") == "1"

_SKIP_LIVE_DB = pytest.mark.skipif(
    not (_HAS_DB and _HAS_RESET),
    reason="Live-DB tests require DATABASE_URL and ALLOW_DB_RESET=1 (two-factor guard)",
)


# ---------------------------------------------------------------------------
# Section A helpers — hermetic (fake_repo + mock_llm)
# ---------------------------------------------------------------------------


def _metrodeli_business_id(fake_repo: Any) -> uuid.UUID:
    business_id: uuid.UUID = fake_repo.contact_to_business["hr@metrodeli.example"]
    return business_id


def _seed_metrodeli_run(
    fake_repo: Any, *, body: str = "David Reyez 38 regular hours."
) -> uuid.UUID:
    """Seed a Metro Deli inbound email + received run whose extraction gates to
    request_clarification: 'David Reyez' matches no roster name or stored alias
    (the real employee is 'David Reyes'), so the deterministic resolver leaves it
    unresolved and the run always reaches clarify().
    """
    email = InboundEmail(
        id=uuid.uuid4(),
        message_id=f"<{uuid.uuid4()}@metrodeli.example>",
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="hr@metrodeli.example",
        to_addr="agent@payroll-agent.local",
        body_text=body,
        created_at=datetime.now(UTC),
    )
    email_id, _ = fake_repo.insert_inbound_email(
        message_id=email.message_id,
        in_reply_to=None,
        references_header=None,
        subject=email.subject,
        from_addr=email.from_addr,
        to_addr=email.to_addr,
        body_text=email.body_text,
    )
    return uuid.UUID(
        str(
            fake_repo.create_run(
                business_id=_metrodeli_business_id(fake_repo), source_email_id=email_id
            )
        )
    )


def _extract_only_script() -> list[str]:
    """The FIFO for a gated run whose clarify() call is expected to raise BEFORE the
    suggestion or draft LLM calls ever happen — the unconfirmed-send guard sits before
    both, so only the extract response is ever consumed. An unconsumed leftover script
    entry is harmless; the tests that need the full FIFO use _full_gate_script below.
    """
    return [
        json.dumps(
            {
                "employees": [{"submitted_name": "David Reyez", "hours_regular": "38"}],
                "pay_period_start": "2026-06-15",
                "pay_period_end": None,
            }
        ),
    ]


def _full_gate_script() -> list[str]:
    """The FIFO for a gated run that actually reaches the send: extract (structured)
    -> suggestion (structured, advisory copy only) -> draft (free text). Used only by
    the non-vacuity twin, where no guard fires and clarify() runs to completion.
    """
    return [
        *_extract_only_script(),
        json.dumps(
            {
                "suggestions": [
                    {
                        "submitted_name": "David Reyez",
                        "suggested_full_name": "David Reyes",
                    }
                ]
            }
        ),
        "We could not match David Reyez. Did you mean David Reyes?",
    ]


def _seed_unconfirmed_row(
    fake_repo: Any,
    run_id: uuid.UUID,
    *,
    purpose: str = "clarification",
    round: int = 0,
    send_state: str = "reserved",
) -> None:
    """Seed the row the guard must see: an outbound row at this run's CURRENT round
    and epoch (both 0 for a fresh run), with the send_state under test.
    """
    fake_repo.outbound[str(run_id)] = [
        {
            "run_id": run_id,
            "purpose": purpose,
            "round": round,
            "epoch": 0,
            "send_state": send_state,
            "message_id": "<crashed-mid-send@test.example>",
        }
    ]


def _spy_gateway_send_outbound(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Patch app.email.gateway.send_outbound to a recording no-op and return the
    list it appends to. Patched on the gateway module itself (not a per-caller
    dotted path) so both clarification.py's and delivery.py's `gateway.send_outbound`
    attribute lookups see it — they both resolve against this same module object.
    """
    calls: list[dict[str, Any]] = []

    def _spy(**kw: Any) -> str:
        calls.append(kw)
        return f"<spy-sent-{uuid.uuid4()}@test.example>"

    import app.email.gateway as gateway_mod

    monkeypatch.setattr(gateway_mod, "send_outbound", _spy)
    return calls


# ---------------------------------------------------------------------------
# Section A.0 — hermetic SQL-shape proof (FakeConnection, no fake_repo)
# ---------------------------------------------------------------------------


def test_get_unconfirmed_outbound_sql_shape(fake_conn):
    """Hermetic SQL-shape proof for get_unconfirmed_outbound's WHERE clause, in the
    style of tests/test_repo_jobs_sql.py: no live DB, asserting against the literal
    SQL text a FakeConnection records.

    This is the FAST, hermetic half of proving the review's falsifying mutation --
    reverting the WHERE clause to match only send_state = 'sent' -- breaks the
    function. Every other hermetic test in this file drives the pipeline through
    fake_repo's InMemoryRepo, a hand-written Python mirror that cannot see a change
    to the REAL SQL text; only this test and the live-DB proofs in Section B can.
    """
    from app.db.repo import emails

    fake_conn.script_fetchone(None)
    emails.get_unconfirmed_outbound(uuid.uuid4(), purpose="clarification", round=0, conn=fake_conn)
    sql_text = str(fake_conn.last()[0])

    assert "direction = 'outbound'" in sql_text
    assert "purpose = %s" in sql_text
    assert "round = %s" in sql_text
    assert "reply_epoch FROM payroll_runs" in sql_text, (
        "the epoch correlated subquery must be present -- dropping it is falsifying mutation (d)"
    )
    assert "send_state IN ('reserved', 'failed')" in sql_text, (
        "the WHERE clause must match BOTH unconfirmed states -- reverting this to "
        "send_state = 'sent' silently reopens the double-send window this guard "
        "exists to close (falsifying mutation (a))"
    )


def test_get_outbound_message_id_sql_shape_requires_current_epoch(fake_conn):
    """A sent proof must be correlated to the run's current reply epoch."""
    run_id = uuid.uuid4()
    fake_conn.script_fetchone(None)

    repo.get_outbound_message_id(run_id, purpose="confirmation", conn=fake_conn)

    sql_text, params = fake_conn.last()
    assert "direction = 'outbound'" in sql_text
    assert "purpose = %s" in sql_text
    assert "send_state = 'sent'" in sql_text
    assert "epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s)" in sql_text
    assert params == (str(run_id), "confirmation", str(run_id))


# ---------------------------------------------------------------------------
# Section A.1 — the guard bites: a reserved row blocks the rerun and escalates
# ---------------------------------------------------------------------------


def test_a_reserved_row_blocks_the_rerun_and_escalates(fake_repo, mock_llm, monkeypatch):
    """A `reserved` clarification row at the CURRENT round + epoch must block the
    rerun's send, land the run in ERROR, and persist the bounded terminal diagnostic.
    These are asserted together: a status assertion alone would pass if the pipeline
    errored for an unrelated reason, and a count assertion alone would pass if the
    pipeline never reached the send stage at all. The direct guard tests below prove
    that the underlying exception is specifically UnconfirmedSendError.
    """
    send_calls = _spy_gateway_send_outbound(monkeypatch)
    mock_llm.script = _extract_only_script()
    run_id = _seed_metrodeli_run(fake_repo)
    _seed_unconfirmed_row(fake_repo, run_id, send_state="reserved")

    result = pipeline_glue.run_pipeline_now(run_id)
    assert result.outcome.value == "terminal"
    repo.settle_background_terminal(run_id, result)

    assert len(send_calls) == 0, (
        "the provider must never be called when an unconfirmed row exists for this "
        "run's current send slot"
    )
    run = fake_repo.load_run(run_id)
    assert run["status"] == "error", "an unconfirmed reservation must escalate to ERROR"
    assert run["error_reason"] == "unclassified", (
        "unclassified guard failures must persist only the bounded reason code"
    )
    assert run["error_detail"] == "clarification:unclassified"


# ---------------------------------------------------------------------------
# Section A.2 — THE NON-VACUITY TWIN: identical setup, no reserved row, work is queued
# ---------------------------------------------------------------------------


def test_no_reserved_row_means_the_send_is_queued(fake_repo, mock_llm, monkeypatch):
    """Byte-identical setup to the test above except the reserved row is absent.
    One immutable send job MUST be queued and the run MUST reach AWAITING_REPLY.

    Without this test, every "no second send" assertion in this file proves nothing
    but "the pipeline stopped somewhere" — this repo has already shipped a
    concurrency proof that passed while proving nothing, and this is the guard
    against doing that a second time.
    """
    send_calls = _spy_gateway_send_outbound(monkeypatch)
    mock_llm.script = _full_gate_script()
    run_id = _seed_metrodeli_run(fake_repo)
    # Deliberately NOT seeding an unconfirmed row — this is the only difference from
    # test_a_reserved_row_blocks_the_rerun_and_escalates.

    result = pipeline_glue.run_pipeline_now(run_id)
    assert result.outcome.value == "ok"

    assert len(send_calls) == 0, "the clarification producer must not call the provider"
    outbound = fake_repo.outbound[str(run_id)]
    assert len(outbound) == 1 and outbound[0]["send_state"] == "reserved"
    jobs = [job for job in fake_repo.jobs.values() if job["kind"] == "send_outbound"]
    assert len(jobs) == 1 and jobs[0]["email_id"] == outbound[0]["id"]
    run = fake_repo.load_run(run_id)
    assert run["status"] == "awaiting_reply"
    assert run.get("error_reason") is None


# ---------------------------------------------------------------------------
# Section A.3 — a failed row is treated exactly like a reserved one
# ---------------------------------------------------------------------------


def test_a_failed_row_blocks_the_rerun_too(fake_repo, mock_llm, monkeypatch):
    """`failed` means the send raised any exception, including a timeout AFTER the
    provider already accepted the mail — it is not proof of non-delivery, so the
    guard must treat it exactly like `reserved`.
    """
    send_calls = _spy_gateway_send_outbound(monkeypatch)
    mock_llm.script = _extract_only_script()
    run_id = _seed_metrodeli_run(fake_repo)
    _seed_unconfirmed_row(fake_repo, run_id, send_state="failed")

    result = pipeline_glue.run_pipeline_now(run_id)
    assert result.outcome.value == "terminal"
    repo.settle_background_terminal(run_id, result)

    assert len(send_calls) == 0
    run = fake_repo.load_run(run_id)
    assert run["status"] == "error"
    assert run["error_reason"] == "unclassified"
    assert run["error_detail"] == "clarification:unclassified"


# ---------------------------------------------------------------------------
# Section A.4 — a proven-sent row takes the EXISTING guard, never this one
# ---------------------------------------------------------------------------


def test_a_sent_row_takes_the_EXISTING_guard_not_this_one(fake_repo, mock_llm, monkeypatch):
    """A `sent` row at the current round is a TRUE duplicate — the pre-existing
    round-idempotency guard must take its early-return path (AWAITING_REPLY, no
    send), and the run must NOT be escalated to ERROR by the new guard.

    This is the test that proves the two guards are complementary rather than
    overlapping: the new one must never hijack the proven-sent path and turn a
    clean idempotent skip into an operator escalation.
    """
    send_calls = _spy_gateway_send_outbound(monkeypatch)
    mock_llm.script = _extract_only_script()
    run_id = _seed_metrodeli_run(fake_repo)
    _seed_unconfirmed_row(fake_repo, run_id, send_state="sent")

    result = pipeline_glue.run_pipeline_now(run_id)
    assert result.outcome.value == "ok"

    assert len(send_calls) == 0
    run = fake_repo.load_run(run_id)
    assert run["status"] == "awaiting_reply", (
        "a proven-sent duplicate must finalize normally, not escalate to ERROR"
    )
    assert run.get("error_reason") is None


def test_delivery_confirmation_uses_current_epoch_sent_proof(fake_repo, monkeypatch):
    """Delivery consumes only the proof for the current epoch.

    A stale sent row must leave the epoch-1 slot eligible; the current epoch's
    sent proof must take the already-delivered branch. This exercises the same
    purpose-aware repository seam used by delivery, without redrafting,
    regenerating a PDF, minting a key, or changing the immutable snapshot.
    """
    from types import SimpleNamespace

    from app.pipeline import delivery

    run_id = uuid.uuid4()
    run = {
        "id": run_id,
        "business_id": uuid.uuid4(),
        "status": "approved",
        "reply_epoch": 1,
    }
    stale_mid = "<epoch-0@payroll-agent.local>"
    current_mid = "<epoch-1@payroll-agent.local>"
    rows = [{"epoch": 0, "send_state": "sent", "message_id": stale_mid}]
    proof_calls: list[tuple[uuid.UUID, str]] = []
    enqueued: list[uuid.UUID] = []
    completed: list[uuid.UUID] = []

    def _proof(rid, *, purpose, conn=None):
        proof_calls.append((rid, purpose))
        current_epoch = run["reply_epoch"]
        matching = [
            row
            for row in rows
            if row["epoch"] == current_epoch
            and row["send_state"] == "sent"
            and purpose == "confirmation"
        ]
        return matching[-1]["message_id"] if matching else None

    monkeypatch.setattr(delivery.repo, "get_outbound_message_id", _proof)
    monkeypatch.setattr(
        delivery.repo,
        "get_outbound_for_round",
        lambda *_args, **_kwargs: pytest.fail(
            "confirmation delivery must use the current-epoch proof seam directly"
        ),
    )
    from app.pipeline import send_guard

    monkeypatch.setattr(
        send_guard,
        "outbound_replay_policy",
        lambda *_args, **_kwargs: SimpleNamespace(
            has_existing_snapshot=True, email_id=uuid.uuid4()
        ),
    )
    monkeypatch.setattr(
        delivery, "_enqueue_confirmation", lambda rid, email_id, *, conn: enqueued.append(rid)
    )
    monkeypatch.setattr(
        delivery,
        "_complete_sent_confirmation",
        lambda rid, _run, *, conn: completed.append(rid),
    )

    assert delivery.deliver(run_id, run) is True
    assert enqueued == [run_id]
    assert completed == []

    rows.append({"epoch": 1, "send_state": "sent", "message_id": current_mid})
    assert delivery.deliver(run_id, run) is False
    assert completed == [run_id]
    assert proof_calls == [(run_id, "confirmation"), (run_id, "confirmation")]


# ---------------------------------------------------------------------------
# Section A.5 — the confirmation call site: deliver() refuses over a reserved row
# ---------------------------------------------------------------------------


def test_a_reserved_confirmation_blocks_deliver(fake_repo, monkeypatch):
    """A `reserved` confirmation row must stop deliver() before it ever calls the
    provider or advances the run past APPROVED.
    """
    from app.pipeline.delivery import deliver as _deliver

    send_calls = _spy_gateway_send_outbound(monkeypatch)
    biz_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    email_id, _ = fake_repo.insert_inbound_email(
        message_id=f"<{uuid.uuid4()}@coastalcleaning.example>",
        from_addr="payroll@coastalcleaning.example",
        to_addr="agent@payroll-agent.local",
        subject="hours",
        body_text="Maria Chen 40h",
        in_reply_to=None,
        references_header=None,
    )
    run_id = fake_repo.create_run(business_id=biz_id, source_email_id=email_id)
    fake_repo.set_status(run_id, "approved")
    _seed_unconfirmed_row(fake_repo, run_id, purpose="confirmation", send_state="reserved")

    run_dict = fake_repo.load_run(run_id)
    with pytest.raises(UnconfirmedSendError):
        _deliver(run_id, run_dict)

    assert len(send_calls) == 0, "deliver() must not call the provider over a reserved row"
    run = fake_repo.load_run(run_id)
    assert run["status"] == "approved", (
        "deliver() must not advance the run past APPROVED when it refuses to send"
    )


# ---------------------------------------------------------------------------
# Section A.6 — an escalated (ERROR) run is not rewound by an automatic reclaim
# ---------------------------------------------------------------------------


def test_an_escalated_run_is_not_rewound_by_a_reclaim(fake_repo):
    """The property the whole escalation rests on: `error` sits outside
    rewind_for_reclaim's scope, so a reclaim of an escalated run cannot walk it back
    into a re-send. If a future change widens that scope to include `error`, this
    guard becomes an infinite escalate -> rewind -> escalate loop, and this test is
    what stops that landing silently.
    """
    from app.db import repo

    run_id = uuid.uuid4()
    fake_repo.runs[str(run_id)] = {
        "id": run_id,
        "status": "error",
        "business_id": uuid.uuid4(),
        "clarification_round": 0,
    }

    rewound = repo.rewind_for_reclaim(run_id)

    assert rewound is False, "a reclaim must never rewind a run parked in ERROR"
    assert fake_repo.runs[str(run_id)]["status"] == "error"


# ---------------------------------------------------------------------------
# Section B — live DB: the epoch scoping proven against real SQL
# ---------------------------------------------------------------------------


def _fresh_run() -> tuple[uuid.UUID, str]:
    """Create a real business-owned run with a real inbound email (mirrors
    tests/test_email_epoch_arbiter_integration.py's own helper of the same name).
    """
    from app.db import repo
    from app.db.seed import seed

    business_id = seed(dry_run=True).businesses[0]["id"]
    anchor = f"<client-{uuid.uuid4()}@example.test>"
    email_id, inserted = repo.insert_inbound_email(
        message_id=anchor,
        in_reply_to=None,
        references_header=None,
        subject="Payroll hours",
        from_addr="payroll@example.test",
        to_addr="agent@payroll-agent.local",
        body_text="Someone worked some hours.",
        run_id=None,
    )
    assert inserted, "the inbound email for this test must be a genuinely new row"
    run_id = repo.create_run(business_id=business_id, source_email_id=email_id)
    return run_id, anchor


@_SKIP_LIVE_DB
@pytest.mark.integration
@pytest.mark.queueproof
def test_the_unconfirmed_guard_is_epoch_scoped(seeded_db: None) -> None:
    """The exact pair the review found: a reserved row is invisible to the
    proven-sent guard and visible to the unconfirmed guard, and a human epoch bump
    (clear_reply_context) makes it invisible to the unconfirmed guard too.
    """
    from app.db import repo

    run_id, anchor = _fresh_run()
    reserved_mid = f"<reserved-{uuid.uuid4()}@payroll-agent.local>"
    repo.insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=reserved_mid,
        in_reply_to=anchor,
        references_header=anchor,
        subject="Quick question about your payroll",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@example.test",
        body_text="Which employee did you mean?",
        purpose="clarification",
        send_state="reserved",
        round=0,
    )

    unconfirmed = repo.get_unconfirmed_outbound(run_id, purpose="clarification", round=0)
    assert unconfirmed is not None, "the reserved row must be visible to the new guard"
    assert unconfirmed["message_id"] == reserved_mid
    assert unconfirmed["send_state"] == "reserved"

    proven_sent = repo.get_outbound_for_round(run_id, purpose="clarification", round=0)
    assert proven_sent is None, (
        "the SAME reserved row must be INVISIBLE to the proven-sent guard -- that "
        "single pair of assertions IS the bug the review found: the old guard was "
        "blind to exactly the row the new one now catches"
    )

    new_epoch = repo.clear_reply_context(run_id)
    assert new_epoch == 1, "a human retrigger must bump the run into a new epoch"

    after_bump = repo.get_unconfirmed_outbound(run_id, purpose="clarification", round=0)
    assert after_bump is None, (
        "after a human epoch bump the stale reservation must no longer be visible -- "
        "this is the operator's licence to recover an escalated run being restored"
    )


@_SKIP_LIVE_DB
@pytest.mark.integration
@pytest.mark.queueproof
def test_a_human_epoch_bump_clears_the_guard(seeded_db: None) -> None:
    """The end-to-end operator escape hatch, driven through the guard function
    itself rather than the raw repo read: reserved row -> guard raises -> a human
    epoch bump -> the guard passes. Without this, an escalated run would be a dead
    end and the accepted residual risk (a human MAY authorise a second send) would
    be unreachable in practice.
    """
    from app.db import repo
    from app.pipeline import send_guard

    run_id, anchor = _fresh_run()
    repo.insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=f"<reserved-{uuid.uuid4()}@payroll-agent.local>",
        in_reply_to=anchor,
        references_header=anchor,
        subject="Quick question about your payroll",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@example.test",
        body_text="Which employee did you mean?",
        purpose="clarification",
        send_state="reserved",
        round=0,
    )

    with pytest.raises(UnconfirmedSendError):
        send_guard.assert_no_unconfirmed_send(run_id, purpose="clarification", round=0)

    repo.clear_reply_context(run_id)

    # Must not raise now that the epoch has moved on.
    send_guard.assert_no_unconfirmed_send(run_id, purpose="clarification", round=0)


# ---------------------------------------------------------------------------
# Section C — immutable snapshot storage
# ---------------------------------------------------------------------------


def test_provider_handoff_schema_is_identifier_only_and_has_one_active_run_fence() -> None:
    """The provider fence may identify a frozen snapshot, never duplicate its PII.

    This is deliberately a schema-shape tripwire.  A fake repository cannot prove
    that a future migration kept the one-active-handoff fence or resisted adding a
    provider payload/diagnostic blob to this mutable authorization row.
    """
    schema = pathlib.Path("app/db/schema.sql").read_text()
    handoffs = schema.split("CREATE TABLE IF NOT EXISTS outbound_provider_handoffs", 1)[1].split(
        ");", 1
    )[0]

    for column in (
        "run_id",
        "email_id",
        "snapshot_id",
        "job_id",
        "lease_token",
        "owner_leased_until",
        "epoch",
        "authorized_at",
        "not_after",
        "released_at",
        "release_reason",
    ):
        assert column in handoffs
    assert "REFERENCES payroll_runs(id)" in handoffs
    assert "REFERENCES email_messages(id)" in handoffs
    assert "REFERENCES outbound_email_snapshots(id)" in handoffs
    assert "REFERENCES jobs(id)" in handoffs
    assert "retry_scheduled" in handoffs
    assert "delivery_review" in handoffs
    assert "provider_request" not in handoffs
    assert "provider_response" not in handoffs
    assert "exception" not in handoffs
    assert "BYTEA" not in handoffs

    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_outbound_provider_handoffs_active_run" in schema
    assert "ON outbound_provider_handoffs (run_id)" in schema
    assert "WHERE released_at IS NULL" in schema


def test_provider_handoff_schema_repairs_deployed_database_with_bounded_vocabulary() -> None:
    schema = pathlib.Path("app/db/schema.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS outbound_provider_handoffs" in schema
    assert "not_after > authorized_at" in schema
    assert "release_reason IN ('retry_scheduled', 'finalized', 'delivery_review')" in schema
    assert "reserved_at + interval '20 hours'" in schema


def test_outbound_snapshot_schema_declares_append_only_evidence() -> None:
    """Provider-ready sends need durable bytes before a provider request, with database
    enforcement rather than a repository convention that a future caller could skip.

    This hermetic shape guard deliberately names the parent/child/attempt tables,
    attachment ordinal uniqueness, bounded PII-safe attempt vocabulary, and every
    deployed-schema trigger. Removing any one reopens either payload drift or direct
    SQL mutation of immutable evidence.
    """
    schema = pathlib.Path("app/db/schema.sql").read_text()

    for table in (
        "outbound_email_snapshots",
        "outbound_email_attachments",
        "outbound_delivery_attempts",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema

    assert "email_id UUID NOT NULL UNIQUE REFERENCES email_messages(id)" in schema
    assert "UNIQUE (snapshot_id, ordinal)" in schema
    assert "content BYTEA NOT NULL" in schema
    assert "attempt_state IN ('attempting', 'retry_scheduled', 'sent', 'needs_operator')" in schema
    assert (
        "failure_category IN ('none', 'transport', 'provider_5xx', 'rate_limited', "
        "'payload_mismatch', 'authorization', 'validation', 'configuration', 'unknown', "
        "'final_attempt_lease_expired')" in schema
    )

    for trigger in (
        "trg_outbound_email_snapshots_append_only",
        "trg_outbound_email_attachments_append_only",
        "trg_outbound_delivery_attempts_append_only",
    ):
        assert f"DROP TRIGGER IF EXISTS {trigger}" in schema
        assert f"CREATE TRIGGER {trigger}" in schema


def test_delivery_settlement_uses_an_exact_lease_and_pii_safe_attempt_facts(
    fake_conn: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The delivery coordinator must fence every write before it records an outcome."""
    import app.db.repo.job_settlement as job_settlement
    from app.models.job import Job, JobKind
    from app.models.roster import Roster
    from app.pipeline.result import PipelineOutcome, PipelineReason, PipelineResult, PipelineStage

    run_id = uuid.uuid4()
    email_id = uuid.uuid4()
    business_id = uuid.uuid4()
    monkeypatch.setattr(
        job_settlement,
        "load_run",
        lambda run_id, **kwargs: {"business_id": business_id},
    )
    monkeypatch.setattr(
        job_settlement,
        "load_roster_for_business",
        lambda business_id, **kwargs: Roster(business_id=business_id, employees=[]),
    )
    monkeypatch.setattr(
        "app.pipeline.alias_learning.write_aliases_if_safe",
        lambda *args, **kwargs: None,
    )
    job = Job(
        id=uuid.uuid4(),
        kind=JobKind.SEND_OUTBOUND,
        run_id=run_id,
        email_id=email_id,
        attempts=1,
        max_attempts=8,
        lease_token=uuid.uuid4(),
    )
    fake_conn.script_fetchone((1, 8, run_id, "send_outbound", email_id))
    fake_conn.script_fetchone(
        (uuid.uuid4(), datetime.now(UTC), "confirmation", 0, 0, "reserved", True)
    )
    fake_conn.script_fetchone(("approved",))
    fake_conn.script_fetchone((uuid.uuid4(),))
    fake_conn.script_fetchone((uuid.uuid4(),))
    fake_conn.script_fetchone((uuid.uuid4(),))
    fake_conn.script_fetchone((uuid.uuid4(),))
    fake_conn.script_fetchone((uuid.uuid4(),))

    outcome = job_settlement.settle_outbound_delivery_job(
        job,
        PipelineResult(
            outcome=PipelineOutcome.OK,
            stage=PipelineStage.DELIVERY,
            reason=PipelineReason.UNCLASSIFIED,
        ),
        conn=fake_conn,
    )

    assert outcome.value == "done"
    sql = fake_conn.all_sql()
    assert "state = 'leased' AND lease_token = %s" in sql
    assert "FOR UPDATE" in sql
    assert "INSERT INTO outbound_delivery_attempts" in sql
    assert "attempt_state" in sql and "failure_category" in sql
    assert "status = 'approved'" in sql
    assert "status = 'sent'" in sql
    assert "status = 'reconciled'" in sql


def test_delivery_settlement_reschedules_the_same_job_without_rewinding_approval(
    fake_conn: Any,
) -> None:
    """A transient delivery result keeps approval intact and reuses the leased job."""
    from app.db.repo.job_settlement import SettlementOutcome, settle_outbound_delivery_job
    from app.models.job import Job, JobKind
    from app.pipeline.result import PipelineOutcome, PipelineReason, PipelineResult, PipelineStage

    run_id = uuid.uuid4()
    email_id = uuid.uuid4()
    job = Job(
        id=uuid.uuid4(),
        kind=JobKind.SEND_OUTBOUND,
        run_id=run_id,
        email_id=email_id,
        attempts=1,
        max_attempts=8,
        lease_token=uuid.uuid4(),
    )
    fake_conn.script_fetchone((1, 8, run_id, "send_outbound", email_id))
    fake_conn.script_fetchone(
        (uuid.uuid4(), datetime.now(UTC), "confirmation", 0, 0, "reserved", True)
    )
    fake_conn.script_fetchone(("approved",))
    fake_conn.script_fetchone((uuid.uuid4(),))
    fake_conn.script_fetchone((uuid.uuid4(),))

    outcome = settle_outbound_delivery_job(
        job,
        PipelineResult(
            outcome=PipelineOutcome.RETRYABLE,
            stage=PipelineStage.DELIVERY,
            reason=PipelineReason.DELIVERY_TIMEOUT,
        ),
        conn=fake_conn,
    )

    assert outcome is SettlementOutcome.RETRIED
    sql = fake_conn.all_sql()
    assert "INSERT INTO outbound_delivery_attempts" in sql
    assert "'retry_scheduled'" not in sql  # values stay parameterized
    assert "state = 'pending', available_at = %s" in sql
    assert "UPDATE payroll_runs SET status = 'sent'" not in sql
    assert "UPDATE payroll_runs SET status = 'needs_operator'" not in sql


def test_delivery_settlement_moves_expired_or_terminal_delivery_to_review(
    fake_conn: Any,
) -> None:
    """No automatic path may continue past the fixed provider-deduplication window."""
    from app.db.repo.job_settlement import SettlementOutcome, settle_outbound_delivery_job
    from app.models.job import Job, JobKind
    from app.pipeline.result import PipelineOutcome, PipelineReason, PipelineResult, PipelineStage

    run_id = uuid.uuid4()
    email_id = uuid.uuid4()
    job = Job(
        id=uuid.uuid4(),
        kind=JobKind.SEND_OUTBOUND,
        run_id=run_id,
        email_id=email_id,
        attempts=1,
        max_attempts=8,
        lease_token=uuid.uuid4(),
    )
    fake_conn.script_fetchone((1, 8, run_id, "send_outbound", email_id))
    fake_conn.script_fetchone(
        (
            uuid.uuid4(),
            datetime.now(UTC) - timedelta(hours=20),
            "confirmation",
            0,
            0,
            "reserved",
            False,
        )
    )
    fake_conn.script_fetchone(("approved",))
    fake_conn.script_fetchone((uuid.uuid4(),))
    fake_conn.script_fetchone((uuid.uuid4(),))
    fake_conn.script_fetchone((uuid.uuid4(),))

    outcome = settle_outbound_delivery_job(
        job,
        PipelineResult(
            outcome=PipelineOutcome.RETRYABLE,
            stage=PipelineStage.DELIVERY,
            reason=PipelineReason.DELIVERY_TIMEOUT,
        ),
        conn=fake_conn,
    )

    assert outcome is SettlementOutcome.DONE
    sql = fake_conn.all_sql()
    assert "attempt_state, failure_category" in sql
    assert "status = 'needs_operator'" in sql
    assert "delivery_review:%s" not in sql
    assert "state = 'done', last_error = %s" in sql


def test_delivery_settlement_rejects_a_lost_lease_before_any_attempt_write(fake_conn: Any) -> None:
    """A reclaimed worker cannot append evidence, change a run, or settle the replacement lease."""
    from app.db.repo.job_settlement import SettlementOutcome, settle_outbound_delivery_job
    from app.models.job import Job, JobKind
    from app.pipeline.result import PipelineResult

    job = Job(
        id=uuid.uuid4(),
        kind=JobKind.SEND_OUTBOUND,
        run_id=uuid.uuid4(),
        email_id=uuid.uuid4(),
        attempts=1,
        max_attempts=8,
        lease_token=uuid.uuid4(),
    )
    fake_conn.script_fetchone(None)

    assert (
        settle_outbound_delivery_job(job, PipelineResult(), conn=fake_conn)
        is SettlementOutcome.LOST_LEASE
    )
    sql = fake_conn.all_sql()
    assert "INSERT INTO outbound_delivery_attempts" not in sql
    assert "UPDATE jobs" not in sql
    assert "UPDATE payroll_runs" not in sql


def test_delivery_settlement_fences_a_claimed_email_id_against_the_persisted_job(
    fake_conn: Any,
) -> None:
    """A valid lease token cannot settle a different frozen email slot."""
    from app.db.repo.job_settlement import SettlementOutcome, settle_outbound_delivery_job
    from app.models.job import Job, JobKind
    from app.pipeline.result import PipelineResult

    run_id = uuid.uuid4()
    claimed_email_id = uuid.uuid4()
    persisted_email_id = uuid.uuid4()
    job = Job(
        id=uuid.uuid4(),
        kind=JobKind.SEND_OUTBOUND,
        run_id=run_id,
        email_id=claimed_email_id,
        attempts=1,
        max_attempts=8,
        lease_token=uuid.uuid4(),
    )
    fake_conn.script_fetchone((1, 8, run_id, "send_outbound", persisted_email_id))
    fake_conn.script_fetchone((job.id,))

    assert (
        settle_outbound_delivery_job(job, PipelineResult(), conn=fake_conn)
        is SettlementOutcome.INVALID_CONTEXT
    )
    sql = fake_conn.all_sql()
    assert "email_id" in sql
    assert "outbound_email_snapshots" not in sql
    assert "outbound_delivery_attempts" not in sql
    assert "UPDATE email_messages" not in sql
    assert "UPDATE payroll_runs" not in sql
    assert "UPDATE jobs" in sql


@pytest.mark.parametrize(
    "reason",
    [
        PipelineReason.DELIVERY_IDEMPOTENCY_PAYLOAD_MISMATCH,
        PipelineReason.DELIVERY_QUOTA_EXHAUSTED,
        PipelineReason.DELIVERY_VALIDATION_FAILURE,
        PipelineReason.DELIVERY_AUTHENTICATION_FAILURE,
        PipelineReason.DELIVERY_AUTHORIZATION_FAILURE,
        PipelineReason.DELIVERY_CONFIGURATION_FAILURE,
        PipelineReason.DELIVERY_PROVIDER_FAILURE,
        PipelineReason.UNCLASSIFIED,
    ],
)
def test_retryable_non_replayable_delivery_reason_goes_to_review(
    fake_conn: Any, reason: PipelineReason
) -> None:
    """Retryability alone never grants an automatic replay."""
    from app.db.repo.job_settlement import SettlementOutcome, settle_outbound_delivery_job
    from app.models.job import Job, JobKind
    from app.pipeline.result import PipelineOutcome, PipelineResult, PipelineStage

    run_id = uuid.uuid4()
    email_id = uuid.uuid4()
    job = Job(
        id=uuid.uuid4(),
        kind=JobKind.SEND_OUTBOUND,
        run_id=run_id,
        email_id=email_id,
        attempts=1,
        max_attempts=8,
        lease_token=uuid.uuid4(),
    )
    fake_conn.script_fetchone((1, 8, run_id, "send_outbound", email_id))
    fake_conn.script_fetchone(
        (uuid.uuid4(), datetime.now(UTC), "confirmation", 0, 0, "reserved", True)
    )
    fake_conn.script_fetchone(("approved",))
    fake_conn.script_fetchone((uuid.uuid4(),))
    fake_conn.script_fetchone((uuid.uuid4(),))
    fake_conn.script_fetchone((uuid.uuid4(),))

    outcome = settle_outbound_delivery_job(
        job,
        PipelineResult(
            outcome=PipelineOutcome.RETRYABLE,
            stage=PipelineStage.DELIVERY,
            reason=reason,
        ),
        conn=fake_conn,
    )

    assert outcome is SettlementOutcome.DONE
    sql = fake_conn.all_sql()
    assert "status = 'needs_operator'" in sql
    assert "state = 'pending'" not in sql
    assert "delivery_review" not in sql.split("UPDATE payroll_runs", 1)[0]


def test_retry_now_locks_the_job_before_its_owned_snapshot(fake_conn: Any) -> None:
    """Operator acceleration shares settlement's job-first lock order."""
    from app.db.repo.jobs import advance_existing_send_job_due_now

    run_id, email_id, job_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fake_conn.script_fetchone((job_id, "pending"))
    fake_conn.script_fetchone((True,))
    fake_conn.script_fetchone((run_id,))
    fake_conn.script_fetchone((job_id,))

    assert (
        advance_existing_send_job_due_now(run_id, email_id, conn=fake_conn).value
        == "advanced"
    )
    sql_statements = [str(statement) for statement, _ in fake_conn.executed]
    assert "FROM jobs" in sql_statements[0]
    assert "outbound_email_snapshots" in sql_statements[1]
    assert "payroll_runs" in sql_statements[2]


def test_clarification_delivery_review_retry_reopens_the_same_row(fake_conn: Any) -> None:
    """Explicit clarification retry advances only the existing durable send row."""
    from app.db.repo.jobs import (
        AdvanceSendJobOutcome,
        advance_existing_clarification_delivery_review_job_due_now,
    )

    run_id, email_id, job_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fake_conn.script_fetchone((job_id, "pending"))
    fake_conn.script_fetchone((True, "clarification", "reserved"))
    fake_conn.script_fetchone(("needs_operator", "ClarificationDeliveryReview"))
    fake_conn.script_fetchone((job_id,))

    assert (
        advance_existing_clarification_delivery_review_job_due_now(
            run_id, email_id, conn=fake_conn
        )
        is AdvanceSendJobOutcome.ADVANCED
    )
    sql_statements = [str(statement) for statement, _ in fake_conn.executed]
    assert "FROM jobs" in sql_statements[0]
    assert "outbound_email_snapshots" in sql_statements[1]
    assert "UPDATE jobs" in sql_statements[-1]
    assert "INSERT INTO jobs" not in fake_conn.all_sql()
    assert "INSERT INTO email_messages" not in fake_conn.all_sql()


def test_clarification_delivery_review_retry_expiry_is_a_bounded_noop(fake_conn: Any) -> None:
    from app.db import repo
    from app.db.repo.jobs import AdvanceSendJobOutcome

    run_id, email_id, job_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fake_conn.script_fetchone((job_id, "pending"))
    fake_conn.script_fetchone((False, "clarification", "reserved"))

    assert (
        repo.advance_existing_clarification_delivery_review_job_due_now(
            run_id, email_id, conn=fake_conn
        )
        is AdvanceSendJobOutcome.EXPIRED
    )
    assert "UPDATE jobs" not in fake_conn.all_sql()
    assert "INSERT INTO" not in fake_conn.all_sql()


def test_clarification_delivery_review_retry_rejects_confirmation_purpose(
    fake_conn: Any,
) -> None:
    from app.db.repo.jobs import (
        AdvanceSendJobOutcome,
        advance_existing_clarification_delivery_review_job_due_now,
    )

    run_id, email_id, job_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fake_conn.script_fetchone((job_id, "pending"))
    fake_conn.script_fetchone((True, "confirmation", "reserved"))

    assert (
        advance_existing_clarification_delivery_review_job_due_now(
            run_id, email_id, conn=fake_conn
        )
        is AdvanceSendJobOutcome.MISSING
    )
    assert "UPDATE jobs" not in fake_conn.all_sql()


@_SKIP_LIVE_DB
@pytest.mark.integration
@pytest.mark.queueproof
def test_outbound_snapshot_evidence_rejects_direct_mutation(seeded_db: None) -> None:
    """The deployed schema, not only repository code, rejects direct UPDATE/DELETE
    of the frozen snapshot, its byte attachments, and append-only attempt facts.
    """
    import psycopg

    from app.db import repo

    run_id, anchor = _fresh_run()
    message_id = f"<snapshot-{uuid.uuid4()}@payroll-agent.local>"
    with repo.get_connection() as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO email_messages (
                run_id, direction, message_id, in_reply_to, references_header,
                subject, from_addr, to_addr, body_text, purpose, send_state, round, epoch
            ) VALUES (%s, 'outbound', %s, %s, %s, 'Payroll confirmation',
                      'agent@payroll-agent.local', 'payroll@example.test', 'Frozen body',
                      'confirmation', 'reserved', 0, 0)
            RETURNING id
            """,
            (run_id, message_id, anchor, anchor),
        )
        email_row = cur.fetchone()
        assert email_row is not None
        email_id = email_row[0]
        cur.execute(
            """
            INSERT INTO outbound_email_snapshots (
                email_id, message_id, from_addr, to_addr, reply_to, in_reply_to,
                references_header, subject, body_text
            ) VALUES (%s, %s, 'agent@payroll-agent.local', 'payroll@example.test',
                      'reply@payroll-agent.local', %s, %s, 'Payroll confirmation',
                      'Frozen body') RETURNING id
            """,
            (email_id, message_id, anchor, anchor),
        )
        snapshot_row = cur.fetchone()
        assert snapshot_row is not None
        snapshot_id = snapshot_row[0]
        cur.execute(
            """
            INSERT INTO outbound_email_attachments (snapshot_id, ordinal, filename, content)
            VALUES (%s, 0, 'paystub.pdf', %s)
            """,
            (snapshot_id, b"exact-pdf-bytes"),
        )
        cur.execute(
            """
            INSERT INTO outbound_delivery_attempts (snapshot_id, attempt_state, failure_category)
            VALUES (%s, 'attempting', 'none') RETURNING id
            """,
            (snapshot_id,),
        )
        attempt_row = cur.fetchone()
        assert attempt_row is not None
        attempt_id = attempt_row[0]

    mutation_cases = (
        ("UPDATE outbound_email_snapshots SET subject = 'changed' WHERE id = %s", snapshot_id),
        ("DELETE FROM outbound_email_snapshots WHERE id = %s", snapshot_id),
        (
            "UPDATE outbound_email_attachments SET filename = 'changed.pdf' WHERE snapshot_id = %s",
            snapshot_id,
        ),
        ("DELETE FROM outbound_email_attachments WHERE snapshot_id = %s", snapshot_id),
        ("UPDATE outbound_delivery_attempts SET attempt_state = 'sent' WHERE id = %s", attempt_id),
        ("DELETE FROM outbound_delivery_attempts WHERE id = %s", attempt_id),
    )
    for statement, identifier in mutation_cases:
        with (
            repo.get_connection() as conn,
            pytest.raises(psycopg.errors.RaiseException),
            conn.transaction(),
            conn.cursor() as cur,
        ):
            cur.execute(statement, (identifier,))


def test_fake_reservation_reuses_the_original_provider_snapshot(fake_repo: Any) -> None:
    """A same-slot retry gets the stored envelope and bytes, not its
    own caller values.  The fake mirrors the production read-or-reserve contract so
    offline delivery tests cannot accidentally exercise an obsolete upsert behavior.
    """
    run_id = uuid.uuid4()
    fake_repo.runs[str(run_id)] = {"id": run_id, "reply_epoch": 0}

    original = fake_repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id="<original@payroll-agent.local>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@example.test",
        reply_to="reply@payroll-agent.local",
        in_reply_to="<inbound@example.test>",
        references_header="<inbound@example.test>",
        subject="Original payroll confirmation",
        body_text="Original frozen body",
        attachments=[("paystub.pdf", b"original-pdf-bytes")],
    )
    replay = fake_repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id="<replacement@payroll-agent.local>",
        from_addr="attacker@example.test",
        to_addr="replacement@example.test",
        reply_to=None,
        in_reply_to="<replacement-inbound@example.test>",
        references_header="<replacement-inbound@example.test>",
        subject="Replacement subject",
        body_text="Replacement body",
        attachments=[("replacement.pdf", b"replacement-bytes")],
    )

    assert replay == original
    assert replay["message_id"] == "<original@payroll-agent.local>"
    assert replay["to_addr"] == "payroll@example.test"
    assert replay["subject"] == "Original payroll confirmation"
    assert [
        (attachment["ordinal"], attachment["filename"], attachment["content"])
        for attachment in replay["attachments"]
    ] == [(0, "paystub.pdf", b"original-pdf-bytes")]

    review = fake_repo.load_delivery_review_snapshot(run_id, original["email_id"])
    assert review == {
        "email_id": original["email_id"],
        "snapshot_id": original["snapshot_id"],
        "purpose": "confirmation",
        "message_id": "<original@payroll-agent.local>",
        "to_addr": "payroll@example.test",
        "subject": "Original payroll confirmation",
        "reserved_at": original["reserved_at"],
        "attempt_count": 0,
        "attachments": [
            {"id": original["attachments"][0]["id"], "ordinal": 0, "filename": "paystub.pdf"}
        ],
    }
    assert "body_text" not in review
    attachment = fake_repo.load_snapshot_attachment(
        run_id, original["snapshot_id"], original["attachments"][0]["id"]
    )
    assert attachment == {"filename": "paystub.pdf", "content": b"original-pdf-bytes"}


def test_reservation_sql_locks_then_never_applies_conflicting_caller_content() -> None:
    """The real repository must preserve immutable retry behavior independently of fakes."""
    from app.db.repo import emails

    reserve_source = inspect.getsource(emails.reserve_outbound_snapshot)
    legacy_source = inspect.getsource(emails.insert_email_message)

    assert "FOR UPDATE" in reserve_source
    assert "INSERT INTO outbound_email_snapshots" in reserve_source
    assert "INSERT INTO outbound_email_attachments" in reserve_source
    assert "ON CONFLICT (run_id, purpose, round, epoch) DO NOTHING" in reserve_source
    assert "SET message_id = EXCLUDED.message_id" not in legacy_source
    assert "SET subject = EXCLUDED.subject" not in legacy_source
    assert "SET body_text = EXCLUDED.body_text" not in legacy_source
