"""Stub email gateway + DB repo surface tests.

Two tiers (mirroring tests/test_seed_roundtrip.py):
- Always-run, DB-free: a FakeConnection (tests/conftest.py) records the SQL +
  params each repo helper executes, so we can assert the parameterized-SQL
  discipline, the synthetic Message-ID shape, model_dump serialization, the
  set_status-only-writes-status rule, the record_run_error single-path routing,
  and the cleaned-body round-trip — all offline.
- Live-DB round-trips behind @pytest.mark.integration + the two-factor guard
  (DATABASE_URL + ALLOW_DB_RESET=1).
"""
from __future__ import annotations

import os
import re
import uuid
from decimal import Decimal

import pytest

from app.db import repo
from app.email import gateway
from app.models.contracts import Decision
from app.models.roster import NameMatchResult
from app.models.status import RunStatus

_HAS_DB = bool(os.environ.get("DATABASE_URL"))
_HAS_RESET = os.environ.get("ALLOW_DB_RESET") == "1"

_SKIP_LIVE_DB = pytest.mark.skipif(
    not (_HAS_DB and _HAS_RESET),
    reason="Live-DB tests require DATABASE_URL and ALLOW_DB_RESET=1 (two-factor guard)",
)

_MSG_ID_RE = re.compile(r"^<[0-9a-f-]{36}@payroll-agent\.local>$")


def _decision(action="process") -> Decision:
    return Decision(
        model_action=action,
        gate_triggered=False,
        gate_reasons=[],
        final_action=action,
        unresolved_names=[],
        missing_fields=[],
        confidence=Decimal("0.95"),
        reasons=["clean run"],
    )


# ---------------------------------------------------------------------------
# Gateway — synthetic Message-ID shape + outbound row anchored on email_messages
# ---------------------------------------------------------------------------


def test_send_outbound_generates_rfc_shaped_message_id(fake_conn):
    run_id = uuid.uuid4()
    msg_id = gateway.send_outbound(
        run_id=run_id,
        to_addr="client@acme.test",
        subject="We need a clarification",
        body="Could you confirm David's hours?",
        conn=fake_conn,
    )
    assert _MSG_ID_RE.match(msg_id), f"Message-ID not RFC-shaped: {msg_id}"


def test_send_outbound_inserts_outbound_email_messages_row(fake_conn):
    run_id = uuid.uuid4()
    msg_id = gateway.send_outbound(
        run_id=run_id,
        to_addr="client@acme.test",
        subject="Clarify",
        body="body",
        conn=fake_conn,
    )
    sql, params = fake_conn.last()
    assert "email_messages" in str(sql)
    assert "outbound" in str(params)  # direction='outbound'
    assert str(run_id) in str(params)
    assert msg_id in str(params)  # the synthetic anchor lives ON the row


def test_send_outbound_uses_parameterized_sql_no_fstring(fake_conn):
    gateway.send_outbound(
        run_id=uuid.uuid4(),
        to_addr="c@acme.test",
        subject="s",
        body="b",
        conn=fake_conn,
    )
    sql = str(fake_conn.last()[0])
    assert "%s" in sql, "outbound insert must use %s placeholders"


def test_parse_inbound_validates_canonical_payload():
    raw = {
        "id": str(uuid.uuid4()),
        "message_id": "<a@acme.test>",
        "in_reply_to": None,
        "references_header": None,
        "subject": "hours",
        "from_addr": "p@acme.test",
        "to_addr": "agent@payroll-agent.local",
        "body_text": "Maria 40",
        "created_at": "2026-06-15T10:00:00Z",
    }
    email = gateway.parse_inbound(raw)
    assert email.message_id == "<a@acme.test>"
    assert email.from_addr == "p@acme.test"


# ---------------------------------------------------------------------------
# set_status — the SOLE status writer; writes the enum .value, not a bare string
# ---------------------------------------------------------------------------


def test_set_status_writes_enum_value(fake_conn):
    run_id = uuid.uuid4()
    repo.set_status(run_id, RunStatus.AWAITING_APPROVAL, conn=fake_conn)
    sql, params = fake_conn.last()
    assert "status" in str(sql).lower()
    assert RunStatus.AWAITING_APPROVAL.value in str(params)
    assert "RunStatus." not in str(params), "must write .value, not the enum repr"


# ---------------------------------------------------------------------------
# persist_decision — writes the decision JSONB ONLY, never status (FIX B)
# ---------------------------------------------------------------------------


def test_persist_decision_serializes_via_model_dump_json(fake_conn):
    run_id = uuid.uuid4()
    repo.persist_decision(run_id, _decision(), conn=fake_conn)
    sql, params = fake_conn.last()
    assert "decision" in str(sql).lower()
    # Decimal confidence must round-trip as a JSON string (model_dump(mode="json")).
    assert '"0.95"' in str(params), "confidence must serialize as a JSON string"


def test_persist_decision_never_writes_status(fake_conn):
    repo.persist_decision(uuid.uuid4(), _decision(), conn=fake_conn)
    assert "status" not in fake_conn.all_sql().lower(), (
        "persist_decision must NOT touch status (FIX B); the orchestrator calls "
        "set_status separately to advance state"
    )


def test_persist_decision_signature_has_no_final_status():
    import inspect

    sig = inspect.signature(repo.persist_decision)
    assert "final_status" not in sig.parameters, (
        "persist_decision must take NO final_status argument (FIX B)"
    )


# ---------------------------------------------------------------------------
# record_run_error — writes error_reason AND routes ERROR THROUGH set_status (FIX B)
# ---------------------------------------------------------------------------


def test_record_run_error_writes_reason_and_routes_through_set_status(fake_conn, monkeypatch):
    calls = {"set_status": []}
    real_set_status = repo.set_status

    def _spy(run_id, status, conn=None):
        calls["set_status"].append(status)
        return real_set_status(run_id, status, conn=conn)

    monkeypatch.setattr(repo, "set_status", _spy)

    run_id = uuid.uuid4()
    repo.record_run_error(run_id, "extraction failed twice", conn=fake_conn)

    # error_reason was written
    assert "error_reason" in fake_conn.all_sql().lower()
    assert "extraction failed twice" in str(fake_conn.executed)
    # and the ERROR transition went THROUGH set_status (single status-write path)
    assert RunStatus.ERROR in calls["set_status"], (
        "record_run_error must route its ERROR transition through set_status (FIX B)"
    )


# ---------------------------------------------------------------------------
# persist_reconciliation — list[NameMatchResult] via model_dump(mode="json")
# ---------------------------------------------------------------------------


def test_persist_reconciliation_serializes_each_name(fake_conn):
    run_id = uuid.uuid4()
    matches = [
        NameMatchResult(
            submitted_name="David Reyez",
            matched_employee_id=uuid.uuid4(),
            match_type="llm_typo",
            confidence=Decimal("0.6"),
            reason="one-letter transposition",
        )
    ]
    repo.persist_reconciliation(run_id, matches, conn=fake_conn)
    sql, params = fake_conn.last()
    assert "reconciliation" in str(sql).lower()
    assert "David Reyez" in str(params)
    assert '"0.6"' in str(params), "per-name confidence must serialize as JSON string"


# ---------------------------------------------------------------------------
# Parameterized-SQL discipline across the whole repo module (T-injection)
# ---------------------------------------------------------------------------


def test_repo_has_no_fstring_sql():
    import pathlib

    src = pathlib.Path(repo.__file__).read_text()
    # No execute(f"...") f-string SQL, and no %-interpolated execute(...).
    assert not re.search(r"execute\(\s*f[\"']", src), "no f-string SQL in repo.py"
    # The references LIKE must be a named placeholder, never interpolated.
    assert "%(references)s" in src or "%(references_header)s" in src, (
        "header-chain references LIKE must use a named placeholder"
    )


def test_repo_exposes_full_named_surface():
    for name in (
        "find_business_by_sender",
        "load_run",
        "load_source_email",
        "record_run_error",
        "get_outbound_message_id",
        "find_awaiting_reply_for_header",
        "find_any_run_for_header",
        "insert_inbound_email",
        "create_run",
        "set_status",
        "persist_extracted",
        "persist_decision",
        "persist_reconciliation",
        "replace_line_items",
        "insert_email_message",
        "load_roster_for_business",
    ):
        assert hasattr(repo, name), f"repo.py is missing required helper: {name}"


# ---------------------------------------------------------------------------
# Header-chain lookups — named placeholders, awaiting_reply-only vs any-status
# ---------------------------------------------------------------------------


def test_find_awaiting_reply_restricts_to_awaiting_reply_status(fake_conn):
    fake_conn.script_fetchone((str(uuid.uuid4()),))
    repo.find_awaiting_reply_for_header(
        in_reply_to="<out@payroll-agent.local>",
        references_header="<out@payroll-agent.local>",
        conn=fake_conn,
    )
    sql = str(fake_conn.last()[0])
    assert "awaiting_reply" in sql, "must restrict to status='awaiting_reply'"
    assert "%(references)s" in sql or "%(in_reply_to)s" in sql


def test_find_any_run_for_header_matches_across_any_status(fake_conn):
    fake_conn.script_fetchone((str(uuid.uuid4()),))
    repo.find_any_run_for_header(
        in_reply_to="<out@payroll-agent.local>",
        references_header="<out@payroll-agent.local>",
        conn=fake_conn,
    )
    sql = str(fake_conn.last()[0])
    assert "awaiting_reply" not in sql, (
        "any-status lookup must NOT restrict by status (late-reply observability, FIX 10)"
    )


def test_find_business_by_sender_uses_contact_email(fake_conn):
    fake_conn.script_fetchone((str(uuid.uuid4()),))
    repo.find_business_by_sender("payroll@acme.test", conn=fake_conn)
    sql, params = fake_conn.last()
    assert "contact_email" in str(sql)
    assert "payroll@acme.test" in str(params)


def test_find_business_by_sender_returns_none_for_unknown(fake_conn):
    # no scripted row → fetchone returns None
    result = repo.find_business_by_sender("stranger@nowhere.test", conn=fake_conn)
    assert result is None, "unknown sender returns None (INGEST-03 — webhook stops)"


def test_insert_inbound_email_uses_on_conflict_do_nothing(fake_conn):
    fake_conn.script_fetchone((str(uuid.uuid4()),))  # RETURNING id → inserted
    repo.insert_inbound_email(
        message_id="<dup@acme.test>",
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="p@acme.test",
        to_addr="agent@payroll-agent.local",
        body_text="cleaned body",
        run_id=None,
        conn=fake_conn,
    )
    sql, params = fake_conn.last()
    assert "ON CONFLICT" in str(sql).upper()
    assert "DO NOTHING" in str(sql).upper()
    # the body it is GIVEN (already cleaned) is what gets persisted
    assert "cleaned body" in str(params)


# ===========================================================================
# Live-DB round-trips (two-factor guard)
# ===========================================================================


@pytest.fixture(scope="module")
def seeded_db():
    if not (_HAS_DB and _HAS_RESET):
        pytest.skip("DATABASE_URL or ALLOW_DB_RESET=1 not set — skipping live-DB fixture")
    from app.db.bootstrap import bootstrap
    from app.db.seed import seed as _seed

    bootstrap(reset=True)
    _seed()
    yield


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_inbound_body_roundtrip_is_not_recleaned(seeded_db):
    """insert_inbound_email persists the cleaned body; load_source_email returns it
    unchanged — no re-cleaning on read (FIX C)."""
    from app.db.seed import seed as _seed

    result = _seed(dry_run=True)
    business_id = result.businesses[0]["id"]

    cleaned = "Maria 40 regular hours. (signature + quoted history already stripped)"
    msg_id = f"<{uuid.uuid4()}@acme.test>"
    email_id, inserted = repo.insert_inbound_email(
        message_id=msg_id,
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="p@acme.test",
        to_addr="agent@payroll-agent.local",
        body_text=cleaned,
        run_id=None,
    )
    assert inserted is True
    run_id = repo.create_run(
        business_id=business_id,
        source_email_id=email_id,
        pay_period_start="2026-06-15",
        pay_period_end="2026-06-21",
    )
    body = repo.load_source_email(run_id)
    assert body == cleaned, "load_source_email must return the cleaned body unchanged (FIX C)"


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_record_run_error_persists_reason_and_error_status(seeded_db):
    from app.db.seed import seed as _seed

    result = _seed(dry_run=True)
    business_id = result.businesses[0]["id"]
    msg_id = f"<{uuid.uuid4()}@acme.test>"
    email_id, _ = repo.insert_inbound_email(
        message_id=msg_id,
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="p@acme.test",
        to_addr="agent@payroll-agent.local",
        body_text="body",
        run_id=None,
    )
    run_id = repo.create_run(
        business_id=business_id,
        source_email_id=email_id,
        pay_period_start="2026-06-15",
        pay_period_end=None,
    )
    repo.record_run_error(run_id, "extraction failed twice")
    run = repo.load_run(run_id)
    assert run["status"] == RunStatus.ERROR.value
    assert run["error_reason"] == "extraction failed twice"
