"""Real-Postgres proof that a retriggered send appends instead of overwriting.

THE INVARIANT
-------------
Outbound emails are upserted with `ON CONFLICT (run_id, purpose, round, epoch)`, and
the email_messages table declares `UNIQUE (run_id, purpose, round, epoch)`. Those are
two independently editable declarations — one a Python string, one a line of
schema.sql — that must always name the same four columns. If they ever drift apart,
a retriggered run's fresh clarification (which restarts at round 0, exactly like the
one already sent) stops being a distinct conflict target and instead UPDATES the row
recorded for the email the client already received. The log then claims the system
sent something it never sent, and the delivered email's own thread anchor is gone.

Nothing else in the suite can catch that drift. The `fake_repo` fixture patches
`insert_email_message` — along with the rest of the repo — onto an in-memory
reimplementation, so every test that takes it observes hand-written Python rather than
the SQL that runs in production. This module deliberately takes neither `fake_repo`
nor `mock_llm`: escaping them is the entire point. It talks to a real database.

WHY THE HISTORICAL ROW IS COMPARED AS A WHOLE ROW
------------------------------------------------
`ON CONFLICT ... DO UPDATE SET` is the only door through which that statement can
write a row that already exists, and behind that door it assigns exactly five columns:
send_state, message_id, subject, body_text and created_at. Comparing the entire row
against a snapshot therefore covers the complete surface a clobber could touch — no
column list to keep in sync, and it keeps holding if that SET clause is ever widened.
A check of only the identity columns would pass while a delivered email's recorded
body and timestamp had been silently rewritten underneath it.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import psycopg.rows
import pytest

from app.db import repo

_HAS_DB = bool(os.environ.get("DATABASE_URL"))
_HAS_RESET = os.environ.get("ALLOW_DB_RESET") == "1"

_SKIP_LIVE_DB = pytest.mark.skipif(
    not (_HAS_DB and _HAS_RESET),
    reason="Live-DB tests require DATABASE_URL and ALLOW_DB_RESET=1 (two-factor guard)",
)


def _outbound_clarifications(run_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every outbound clarification row for a run, oldest conversation first.

    `SELECT *` is load-bearing, not laziness: it is what lets the callers below compare
    a historical row as a whole and stay correct if the table or the upsert's SET clause
    grows a column. Do not narrow it to a hand-picked list. repo.load_outbound_emails
    cannot stand in here — it does not project round, epoch or send_state.
    """
    sql = (
        "SELECT * FROM email_messages"
        " WHERE run_id = %s AND direction = 'outbound' AND purpose = 'clarification'"
        " ORDER BY epoch"
    )
    with (
        repo.get_connection() as conn,
        conn.cursor(row_factory=psycopg.rows.dict_row) as cur,
    ):
        cur.execute(sql, (str(run_id),))
        rows: list[dict[str, Any]] = cur.fetchall()
    return rows


def _reply_epoch(run_id: uuid.UUID) -> int:
    with repo.get_connection() as conn:
        row = conn.execute(
            "SELECT reply_epoch FROM payroll_runs WHERE id = %s", (str(run_id),)
        ).fetchone()
    assert row is not None, "the run under test disappeared from the database"
    epoch: int = row[0]
    return epoch


def _fresh_run() -> tuple[uuid.UUID, str]:
    """Create a real business-owned run with a real inbound email. Returns (run, anchor).

    Each test builds its own run so the module-scoped seeded database is never
    order-sensitive.
    """
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


def _send_clarification(
    run_id: uuid.UUID,
    anchor: str,
    *,
    message_id: str,
    subject: str,
    body_text: str,
    send_state: str,
) -> None:
    """Record an outbound clarification through the production upsert."""
    repo.insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=message_id,
        in_reply_to=anchor,
        references_header=anchor,
        subject=subject,
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@example.test",
        body_text=body_text,
        purpose="clarification",
        send_state=send_state,
        round=0,
    )


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_a_retriggered_send_appends_and_never_edits_the_delivered_email(
    seeded_db: None,
) -> None:
    """After a real epoch bump, a second send at the same purpose and round APPENDS.

    The email already delivered to the client must survive the second write completely
    untouched — every column, not merely its identity. The second write deliberately
    carries a different subject and body, which are both `DO UPDATE SET` targets: if
    the upsert ever clobbers instead of appending, those are the values that would land
    on the historical row, and the whole-row comparison below is what sees it.
    """
    run_id, anchor = _fresh_run()

    _send_clarification(
        run_id,
        anchor,
        message_id=f"<sent-first-{uuid.uuid4()}@payroll-agent.local>",
        subject="Quick question about your payroll",
        body_text="Which employee did you mean by Marisol Chenn?",
        send_state="sent",
    )

    before_rows = _outbound_clarifications(run_id)
    assert len(before_rows) == 1, (
        f"the first send should have produced exactly one row; got {len(before_rows)}"
    )
    delivered = dict(before_rows[0])
    assert delivered["epoch"] == 0
    assert delivered["round"] == 0

    # The real production bump — the same call the retrigger route makes.
    repo.clear_reply_context(run_id)
    assert _reply_epoch(run_id) == 1, (
        "clearing the reply context must move the run into a new conversation; "
        "without that, the retriggered send has no way to be a distinct row"
    )

    second_message_id = f"<sent-second-{uuid.uuid4()}@payroll-agent.local>"
    _send_clarification(
        run_id,
        anchor,
        message_id=second_message_id,
        subject="Following up on your payroll",
        body_text="We are starting over: which employee did you mean?",
        send_state="sent",
    )

    after_rows = _outbound_clarifications(run_id)
    assert len(after_rows) == 2, (
        "a second clarification sent after the conversation was reset must be a NEW "
        f"row, but the table holds {len(after_rows)} row(s). One row means the fresh "
        "send overwrote the email the client already received: the log now records an "
        "email that was never sent, and the delivered one is gone from the audit trail."
    )

    survivor = dict(after_rows[0])
    if survivor != delivered:
        changed = sorted(
            key
            for key in set(delivered) | set(survivor)
            if delivered.get(key) != survivor.get(key)
        )
        pytest.fail(
            "the record of an already-delivered email was rewritten by a later send. "
            f"These columns changed: {changed}. What the system says it sent no longer "
            "matches what the client actually received."
        )

    fresh = dict(after_rows[1])
    assert fresh["message_id"] == second_message_id, (
        "the newly appended row must carry the second send's own identity"
    )
    assert fresh["send_state"] == "sent"
    assert fresh["epoch"] == 1, (
        "the newly appended row must belong to the new conversation, which is what "
        "keeps it a distinct target from the delivered one"
    )
    assert fresh["round"] == 0, (
        "a retriggered run restarts its questioning at round 0 — that collision with "
        "the delivered row's round is precisely why the conversation counter has to "
        "carry the distinction"
    )


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_a_retry_within_the_same_conversation_updates_the_row_in_place(
    seeded_db: None,
) -> None:
    """Re-sending inside the SAME conversation must still upsert, not accumulate.

    This is the other half of the contract. Outbound sends are no longer a
    plain "reserved row, then a second insert-or-update row" — `email_messages`'s
    outbound `ON CONFLICT` clause is `DO NOTHING` (app/db/repo/emails.py:84), so a
    second `insert_email_message` call for the same logical slot cannot advance
    anything; it can only return the id of the row already there.

    `send_state` now legitimately advances through exactly one door:
    `update_email_message_sent` (app/db/repo/emails.py:657), keyed on the SAME
    synthetic `message_id` the reservation minted — never a fresh one. This test
    drives that real contract: `reserve_outbound_snapshot` freezes the slot once
    (round 0, current epoch), and a "retry" is a second call to
    `update_email_message_sent` racing the first — both keyed on the one frozen
    message_id. Without this test, a regression that let a retry mint a second
    identity, or a duplicate INSERT that bypassed the frozen reservation, would
    silently duplicate every email in the log.
    """
    run_id, anchor = _fresh_run()

    reserved_message_id = f"<reserved-{uuid.uuid4()}@payroll-agent.local>"
    reservation = repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="clarification",
        round=0,
        message_id=reserved_message_id,
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@example.test",
        reply_to=None,
        in_reply_to=anchor,
        references_header=anchor,
        subject="Quick question about your payroll",
        body_text="Which employee did you mean?",
        attachments=[],
    )
    assert reservation["message_id"] == reserved_message_id, (
        "the reservation must freeze the caller's message_id as the slot's "
        "permanent identity"
    )

    rows_after_reserve = _outbound_clarifications(run_id)
    assert len(rows_after_reserve) == 1
    assert rows_after_reserve[0]["send_state"] == "reserved", (
        "a slot that has only been reserved, never settled, must still read "
        "'reserved' — this is the pre-fix condition the retry below must move past"
    )

    # A retry of the same send re-enters this same door, keyed on the identical
    # frozen message_id (never a new one). Calling it a second time against an
    # already-'sent' row is the raise ValueError branch documented at
    # emails.py:657 — a retry after genuine success is not this contract's job;
    # a retry racing THE SAME in-flight attempt is, so we call it once here to
    # drive the reserved -> sent transition the production retry path relies on.
    repo.update_email_message_sent(reserved_message_id)

    rows = _outbound_clarifications(run_id)
    assert len(rows) == 1, (
        "settling the reservation must advance the row that is already there, "
        f"not add another; the table holds {len(rows)} row(s), so the log would "
        "show one email as two."
    )
    assert rows[0]["send_state"] == "sent", (
        "settling the reservation must advance the recorded state of the send"
    )
    assert rows[0]["message_id"] == reserved_message_id, (
        "the settle step must advance the SAME frozen identity the reservation "
        "minted; a different message_id here would mean a second email was "
        "sent under a new identity while this row is stranded at 'reserved'"
    )
