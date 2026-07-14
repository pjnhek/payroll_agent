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

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.models.contracts import InboundEmail
from app.pipeline.orchestrator import run_pipeline
from app.pipeline.send_guard import UnconfirmedSendError

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
    emails.get_unconfirmed_outbound(
        uuid.uuid4(), purpose="clarification", round=0, conn=fake_conn
    )
    sql_text = str(fake_conn.last()[0])

    assert "direction = 'outbound'" in sql_text
    assert "purpose = %s" in sql_text
    assert "round = %s" in sql_text
    assert "reply_epoch FROM payroll_runs" in sql_text, (
        "the epoch correlated subquery must be present -- dropping it is falsifying "
        "mutation (d)"
    )
    assert "send_state IN ('reserved', 'failed')" in sql_text, (
        "the WHERE clause must match BOTH unconfirmed states -- reverting this to "
        "send_state = 'sent' silently reopens the double-send window this guard "
        "exists to close (falsifying mutation (a))"
    )


# ---------------------------------------------------------------------------
# Section A.1 — the guard bites: a reserved row blocks the rerun and escalates
# ---------------------------------------------------------------------------


def test_a_reserved_row_blocks_the_rerun_and_escalates(fake_repo, mock_llm, monkeypatch):
    """A `reserved` clarification row at the CURRENT round + epoch must block the
    rerun's send, land the run in ERROR, and persist UnconfirmedSendError as the
    reason. All three are asserted together: a status assertion alone would pass if
    the pipeline errored for an unrelated reason, and a count assertion alone would
    pass if the pipeline never reached the send stage at all.
    """
    send_calls = _spy_gateway_send_outbound(monkeypatch)
    mock_llm.script = _extract_only_script()
    run_id = _seed_metrodeli_run(fake_repo)
    _seed_unconfirmed_row(fake_repo, run_id, send_state="reserved")

    run_pipeline(run_id)

    assert len(send_calls) == 0, (
        "the provider must never be called when an unconfirmed row exists for this "
        "run's current send slot"
    )
    run = fake_repo.load_run(run_id)
    assert run["status"] == "error", "an unconfirmed reservation must escalate to ERROR"
    assert run["error_reason"] == "UnconfirmedSendError", (
        "the persisted reason must name the guard that fired, not some other failure"
    )


# ---------------------------------------------------------------------------
# Section A.2 — THE NON-VACUITY TWIN: identical setup, no reserved row, send DOES fire
# ---------------------------------------------------------------------------


def test_no_reserved_row_means_the_send_DOES_fire(fake_repo, mock_llm, monkeypatch):
    """Byte-identical setup to the test above except the reserved row is absent.
    The send MUST actually fire exactly once and the run MUST reach AWAITING_REPLY.

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

    run_pipeline(run_id)

    assert len(send_calls) == 1, (
        "with no unconfirmed row present, clarify() must actually call "
        "gateway.send_outbound — a guard that never opens is as dangerous as one "
        "that never closes"
    )
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

    run_pipeline(run_id)

    assert len(send_calls) == 0
    run = fake_repo.load_run(run_id)
    assert run["status"] == "error"
    assert run["error_reason"] == "UnconfirmedSendError"


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

    run_pipeline(run_id)

    assert len(send_calls) == 0
    run = fake_repo.load_run(run_id)
    assert run["status"] == "awaiting_reply", (
        "a proven-sent duplicate must finalize normally, not escalate to ERROR"
    )
    assert run.get("error_reason") is None


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
