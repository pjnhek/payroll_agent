"""Repository boundary regressions for Phase 20 review and send state."""

from __future__ import annotations

import inspect
import uuid

import pytest

from app.db.repo import emails


def test_delivery_review_projection_is_body_free_but_frozen_reader_is_not(
    fake_repo,
):
    run_id = uuid.uuid4()
    snapshot = fake_repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id="<review@payroll-agent.local>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@example.test",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Payroll confirmation",
        body_text="Frozen payroll body",
        attachments=[("paystub.pdf", b"frozen-pdf")],
    )

    review = fake_repo.load_delivery_review_snapshot(run_id, snapshot["email_id"])
    assert review is not None
    assert review["purpose"] == "confirmation"
    assert "body_text" not in review
    assert review["attachments"][0]["filename"] == "paystub.pdf"

    frozen = fake_repo.load_outbound_snapshot(run_id, snapshot["email_id"])
    assert frozen is not None
    assert frozen["body_text"] == "Frozen payroll body"

    review_source = inspect.getsource(emails.load_delivery_review_snapshot)
    assert "snapshot.body_text" not in review_source
    assert "provider payloads" in review_source
    frozen_source = inspect.getsource(emails.load_outbound_snapshot)
    assert "_load_outbound_snapshot_locked" in frozen_source


def test_retired_email_state_mutator_fails_before_sql(fake_conn):
    with pytest.raises(RuntimeError, match="retired"):
        emails.update_email_message_state(
            "<inbound-or-invalid@payroll-agent.local>",
            "sent",
            conn=fake_conn,
        )
    assert fake_conn.executed == []


def test_sent_transition_is_outbound_reserved_only_and_row_count_safe(fake_conn):
    fake_conn.script_fetchone((str(uuid.uuid4()),))
    emails.update_email_message_sent(
        "<reserved@payroll-agent.local>",
        conn=fake_conn,
    )
    sql, params = fake_conn.last()
    assert "direction = 'outbound'" in str(sql)
    assert "send_state = 'reserved'" in str(sql)
    assert "RETURNING id" in str(sql)
    assert params == ("<reserved@payroll-agent.local>",)


def test_sent_transition_rejects_inbound_or_non_reserved_rows(fake_conn):
    fake_conn.script_fetchone(None)
    with pytest.raises(ValueError, match="outbound row in the reserved state"):
        emails.update_email_message_sent(
            "<inbound@payroll-agent.local>",
            conn=fake_conn,
        )
