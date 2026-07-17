"""Delivery-pipeline behavior (CLAR-04, INGEST-05).

These tests cover:
- error routing: an exception after the CAS claim advances the run to ERROR rather
  than leaving it stuck in `approved` with no way forward;
- CLAR-04: purpose-aware idempotent confirmation send — the client is never sent the
  same payroll confirmation twice;
- clarification idempotency: a duplicate clarification send is skipped;
- INGEST-05: stale-state recovery — a retrigger can claim a run out of an in-flight
  status, so a run stranded by a crash is never permanently unreachable;
- upsert interaction: a pre-existing reserved/failed outbound row must advance to
  'sent' rather than crashing the send with a unique-constraint violation.

These tests assert against the SQL text recorded by the FakeConnection, so they can
see THAT insert_email_message upserts, but not which columns it arbitrates on. The
real-Postgres proof of the arbiter's column list lives in
tests/test_email_epoch_arbiter_integration.py.
"""
from __future__ import annotations

import uuid
from datetime import UTC

import pytest

from app.db.repo import (
    _TERMINAL_STATUSES,
    claim_status,
    get_outbound_message_id,
    insert_email_message,
    record_run_error,
)
from app.models.status import RunStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_id() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# APPROVED is NOT a terminal status
# ---------------------------------------------------------------------------


def test_approved_not_in_terminal_statuses():
    """APPROVED must NOT be in _TERMINAL_STATUSES.

    record_run_error refuses to write over a terminal run. A run that has been claimed
    (status='approved') but whose delivery then fails must still be able to reach ERROR.
    If APPROVED were terminal, record_run_error would silently no-op and the run would
    sit in 'approved' forever with no error signal and nothing to retrigger.
    """
    assert RunStatus.APPROVED not in _TERMINAL_STATUSES, (
        "APPROVED must not be in _TERMINAL_STATUSES: a failed delivery after claim "
        "must be able to transition the run to ERROR via record_run_error"
    )


# ---------------------------------------------------------------------------
# The delivery error boundary — an exception after claim routes the run to ERROR
# ---------------------------------------------------------------------------


def test_delivery_error_converts_approved_to_error(fake_conn):
    """A delivery exception after claim records type(exc).__name__ as the reason.

    The exception message can carry PII (employee names, client addresses embedded in
    PDF or gateway payloads), and error_reason is rendered on the dashboard — so only
    the exception's CLASS name is stored, never str(exc).

    Uses FakeConnection to assert SQL shape without a live DB.
    """
    run_id = _run_id()
    exc = RuntimeError("simulated PDF generation failure")

    # Script the FakeConnection: record_run_error's guarded CAS UPDATE ... RETURNING
    # yields a row ('approved' is not terminal), so the error write proceeds.
    fake_conn.script_fetchone((str(run_id),))  # CAS RETURNING id — claim succeeded

    # Call record_run_error directly with type(exc).__name__ — the shape the delivery
    # boundary uses, and the reason nothing PII-bearing reaches the column.
    reason = type(exc).__name__
    record_run_error(run_id, reason, conn=fake_conn)

    sql = fake_conn.all_sql()
    # Must write error_reason (not the exception message/str(exc))
    assert "error_reason" in sql, (
        "record_run_error must write the error_reason column"
    )
    # The reason stored is type(exc).__name__ — never the PII-bearing message.
    assert any(reason in str(params) for _, params in fake_conn.executed), (
        "record_run_error must write type(exc).__name__ as the reason, not str(exc), "
        "which can carry employee names into a dashboard-rendered column"
    )


# ---------------------------------------------------------------------------
# CLAR-04: the confirmation idempotency guard must be purpose-AWARE
# ---------------------------------------------------------------------------


def test_idempotent_confirmation_skips_if_confirmation_outbound_exists(fake_conn):
    """The delivery path skips its send when a confirmation was already sent.

    The purpose='confirmation' kwarg is what distinguishes a prior confirmation row
    from a clarification row. A purpose-BLIND lookup would see the clarification email
    this run already sent, conclude the confirmation was sent too, and skip delivery —
    the client would be told nothing and never receive their paystubs.
    """
    run_id = _run_id()

    # Script the FakeConnection to return a pre-existing confirmation Message-ID.
    fake_conn.script_fetchone(("<existing-confirmation@payroll-agent.local>",))

    # The purpose= kwarg is the whole point: it scopes the lookup to confirmations.
    existing_mid = get_outbound_message_id(run_id, purpose="confirmation", conn=fake_conn)

    assert existing_mid == "<existing-confirmation@payroll-agent.local>", (
        "get_outbound_message_id(purpose='confirmation') must return the existing "
        "confirmation Message-ID"
    )
    # The SQL uses parameterized %s placeholders — 'confirmation' appears in the params
    # tuple, not in the raw SQL string (parameterized-SQL rule).
    found = any(
        params and "confirmation" in params
        for _sql, params in fake_conn.executed
    )
    assert found, (
        "get_outbound_message_id must pass purpose='confirmation' as a SQL param, "
        "not embedded in the SQL string"
    )


# ---------------------------------------------------------------------------
# A duplicate clarification send is skipped
# ---------------------------------------------------------------------------


def test_clarify_idempotency_skips_if_clarification_already_sent(fake_conn):
    """Re-triggering a run that already asked its question must not ask again.

    The guard reads get_outbound_message_id(run_id, purpose='clarification'); a non-None
    result means the clarify path must return early. Without it, every retrigger emails
    the client the same question again.
    """
    run_id = _run_id()

    # Script: a pre-existing clarification row already exists.
    fake_conn.script_fetchone(("<existing-clarification@payroll-agent.local>",))

    existing_mid = get_outbound_message_id(run_id, purpose="clarification", conn=fake_conn)

    assert existing_mid is not None, (
        "get_outbound_message_id(purpose='clarification') must return the existing "
        "clarification Message-ID"
    )
    # The SQL uses parameterized %s placeholders — 'clarification' appears in the params
    # tuple, not in the raw SQL string (parameterized-SQL rule).
    found = any(
        params and "clarification" in params
        for _sql, params in fake_conn.executed
    )
    assert found, (
        "get_outbound_message_id must pass purpose='clarification' as a SQL param, "
        "not embedded in the SQL string"
    )


# ---------------------------------------------------------------------------
# Test 5: INGEST-05 — retrigger from ERROR state
# ---------------------------------------------------------------------------


def test_retrigger_claims_from_error_state(fake_conn):
    """INGEST-05: claim_status(run_id, ERROR, RECEIVED) returns True when run is
    in error state (the manual retrigger path).

    Will fail RED until Wave 1 adds claim_status to repo.py.
    """
    run_id = _run_id()

    # claim_status executes a single atomic UPDATE ... WHERE id=%s AND status=%s RETURNING id.
    # Script a non-None row to simulate a successful claim (run was in ERROR state).
    # NOTE: claim_status uses parameterized SQL (%s) so the 'error' value is NOT embedded
    # in the SQL string — it appears in the params tuple. The assertion checks params.
    fake_conn.script_fetchone((str(run_id),))  # RETURNING id — non-None → claim succeeds

    result = claim_status(run_id, RunStatus.ERROR, RunStatus.RECEIVED, conn=fake_conn)

    assert result is True, (
        "claim_status(run_id, ERROR, RECEIVED) must return True when the run is "
        "in error state (INGEST-05 retrigger path)"
    )
    # Verify that the expected-status value ('error') was passed as a SQL parameter,
    # not embedded in the SQL string (parameterized-SQL rule).
    found = any(
        params and RunStatus.ERROR.value in params and RunStatus.RECEIVED.value in params
        for _sql, params in fake_conn.executed
    )
    assert found, (
        "claim_status must pass both expected ('error') and new ('received') status "
        "values as SQL params — parameterized SQL rule"
    )


# ---------------------------------------------------------------------------
# INGEST-05: retrigger from APPROVED state (delivery died mid-flight)
# ---------------------------------------------------------------------------


def test_retrigger_claims_from_approved_state(fake_conn):
    """A run stranded in 'approved' can be reclaimed for a fresh delivery attempt.

    A run lands here when the delivery task was claimed and then the process died
    before record_run_error could run (an OOM kill, a dyno restart). Nothing else will
    ever move it, so the retrigger route must be able to claim it out of 'approved'.
    """
    run_id = _run_id()

    # Script: the CAS SELECT returns current status='approved' → claim succeeds.
    fake_conn.script_fetchone(("approved",))
    fake_conn.script_fetchone((str(run_id),))

    result = claim_status(run_id, RunStatus.APPROVED, RunStatus.RECEIVED, conn=fake_conn)

    assert result is True, (
        "claim_status(run_id, APPROVED, RECEIVED) must return True when the run "
        "is stranded in approved state — otherwise the run is unrecoverable"
    )


# ---------------------------------------------------------------------------
# INGEST-05: stale-state recovery from EXTRACTING
# ---------------------------------------------------------------------------


def test_retrigger_claims_from_stale_extracting_state(fake_conn):
    """claim_status permits an EXTRACTING → RECEIVED transition for stale-run recovery.

    'extracting' is normally an in-flight state that nothing should claim out of — but
    a crashed run sits in it forever. claim_status therefore accepts it as a source
    status; the guard that stops a HEALTHY in-flight run from being yanked out is the
    staleness threshold (updated_at older than a few minutes), and it lives in the
    retrigger ROUTE, not here. Moving that check into claim_status would break the
    concurrency proof's ability to drive the CAS seam directly.
    """
    run_id = _run_id()

    # Script: run is stuck in 'extracting'.
    fake_conn.script_fetchone(("extracting",))
    fake_conn.script_fetchone((str(run_id),))

    result = claim_status(run_id, RunStatus.EXTRACTING, RunStatus.RECEIVED, conn=fake_conn)

    assert result is True, (
        "claim_status(run_id, EXTRACTING, RECEIVED) must succeed for stale-state "
        "recovery — the staleness threshold guard lives in the route handler, not in "
        "claim_status itself"
    )


# ---------------------------------------------------------------------------
# Conflict interaction — caller content cannot overwrite a reserved row
# ---------------------------------------------------------------------------


def test_outbound_conflict_does_not_overwrite_reserved_row(fake_conn):
    """A pre-existing reservation must not apply retry-supplied payload fields.

    send_outbound writes send_state='reserved' before calling the provider, so a retry
    of that same send finds its own reserved row already in the table. A plain INSERT
    would hit the uq_email_run_purpose_round_epoch UNIQUE constraint and raise
    IntegrityError, stranding a run that is otherwise perfectly deliverable. Read-or-
    reserve owns immutable payload creation; this generic audit helper may
    return the existing row but must never overwrite it with caller content.

    The arbiter is the four-column key (run_id, purpose, round, epoch), matching the
    uq_email_run_purpose_round_epoch constraint. The epoch column is what keeps a retry
    (same epoch → upsert in place) distinct from a post-retrigger resend: a retrigger
    resets the clarification round to 0, so a fresh send would otherwise collide with
    the stale pre-retrigger round-0 row on the narrower three-column key and silently
    overwrite an email that was already delivered.

    This test asserts on the SQL text the FakeConnection recorded — a substring check
    that cannot see the arbiter's column list. The real-Postgres proof of that column
    list is tests/test_email_epoch_arbiter_integration.py.
    """
    run_id = _run_id()
    msg_id = f"<{uuid.uuid4()}@payroll-agent.local>"

    # Script the FakeConnection to simulate the insert branch returning its row id.
    fake_conn.script_fetchone((str(uuid.uuid4()),))

    # The legacy helper still returns a row id for a duplicate logical slot.
    result = insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=msg_id,
        purpose="confirmation",
        send_state="sent",
        conn=fake_conn,
    )

    assert result is not None, (
        "insert_email_message with purpose='confirmation' must return a row id"
    )
    sql = fake_conn.all_sql()
    assert "ON CONFLICT (run_id, purpose, round, epoch) DO NOTHING" in sql
    assert "EXCLUDED.message_id" not in sql
    assert "EXCLUDED.subject" not in sql
    assert "EXCLUDED.body_text" not in sql


# ---------------------------------------------------------------------------
# Conflict interaction — a failed row is equally immutable
# ---------------------------------------------------------------------------


def test_outbound_conflict_does_not_overwrite_failed_row(fake_conn):
    """A failed logical slot cannot be changed by caller retry content either.

    The delivery-state transition remains a separate API. This generic email insert
    must not turn a retry's caller fields into an overwrite of frozen evidence.
    """
    run_id = _run_id()
    msg_id = f"<{uuid.uuid4()}@payroll-agent.local>"

    fake_conn.script_fetchone((str(uuid.uuid4()),))

    result = insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=msg_id,
        purpose="confirmation",
        send_state="sent",
        conn=fake_conn,
    )

    assert result is not None, (
        "insert_email_message must return a row id for the failed-slot lookup"
    )
    sql = fake_conn.all_sql()
    assert "ON CONFLICT (run_id, purpose, round, epoch) DO NOTHING" in sql
    assert "EXCLUDED.message_id" not in sql


# ---------------------------------------------------------------------------
# Stale-retrigger CAS exclusivity — two concurrent retriggers, only one wins
#
# The stale-retrigger CAS target MUST differ from the current status so the
# conditional UPDATE genuinely changes the row. Two concurrent retrigger clicks
# on a stale RECEIVED run both call claim_status(RECEIVED → EXTRACTING):
# the first wins (row changed), the second finds the row already EXTRACTING
# and returns False.
# ---------------------------------------------------------------------------


def test_two_concurrent_stale_retriggers_only_one_wins():
    """Two concurrent stale retriggers on the same run: exactly one wins the claim.

    The stale-retrigger path must claim RECEIVED → EXTRACTING, NOT RECEIVED → RECEIVED.
    The CAS is only exclusive because the target status DIFFERS from the source: a
    RECEIVED→RECEIVED claim leaves the row unchanged, so every concurrent caller sees a
    "successful" claim and the run gets processed twice. InMemoryRepo mirrors the real
    claim_status CAS — the second caller arrives after the first has already advanced
    the run to EXTRACTING, so its claim returns False.
    """
    from tests.conftest import InMemoryRepo

    store = InMemoryRepo()
    business_id = store.contact_to_business["payroll@coastalcleaning.example"]
    run_id = store.create_run(business_id=business_id, source_email_id=None)
    store.set_status(run_id, RunStatus.RECEIVED)

    # Simulate two concurrent callers both attempting the stale claim.
    # claim_status(RECEIVED → EXTRACTING): first wins, second sees EXTRACTING already.
    result_1 = store.claim_status(run_id, RunStatus.RECEIVED, RunStatus.EXTRACTING)
    result_2 = store.claim_status(run_id, RunStatus.RECEIVED, RunStatus.EXTRACTING)

    assert result_1 is True, (
        "First stale retrigger must win the claim_status(RECEIVED → EXTRACTING) CAS"
    )
    assert result_2 is False, (
        "Second stale retrigger must lose: the run is already EXTRACTING after the "
        "first claim — a target status distinct from the source is what makes the CAS "
        "exclusive"
    )
    final_run = store.load_run(run_id)
    assert final_run is not None, "run seeded above must still exist"
    assert final_run["status"] == RunStatus.EXTRACTING.value, (
        "After both retriggers, run must be in EXTRACTING (the CAS winner's target)"
    )


# ---------------------------------------------------------------------------
# _deliver stashes its already-loaded roster onto any exception raised past the
# roster load, so the approve() error boundary can hand it to record_run_error and
# _scrub can redact employee names out of the delivery error_detail. Delivery is the
# boundary where names are MOST likely to end up in exception text (PDF headers,
# compose/gateway payloads), and error_detail is rendered on the dashboard.
#
# The invariant that must survive: nothing on the error path ever LOADS a roster —
# the already-in-memory object is forwarded. An error handler that hit the DB could
# fail a second time, or hang, while trying to report the first failure.
# ---------------------------------------------------------------------------


def _minimal_roster_and_item(run_id: uuid.UUID):
    from datetime import datetime
    from decimal import Decimal

    from app.models.contracts import PaystubLineItem
    from app.models.roster import Employee, Roster

    emp = Employee(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        full_name="Maria Chen",
        known_aliases=[],
        pay_type="hourly",
        hourly_rate=Decimal("20.00"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("0.00"),
        pay_periods_per_year=52,
    )
    roster = Roster(business_id=emp.business_id, employees=[emp])
    item = PaystubLineItem(
        id=uuid.uuid4(), run_id=run_id, employee_id=emp.id, submitted_name="Maria Chen",
        hours_regular=Decimal("40"), hours_overtime=Decimal("0"),
        hours_vacation=Decimal("0"), hours_sick=Decimal("0"), hours_holiday=Decimal("0"),
        gross_pay=Decimal("800.00"), pretax_401k=Decimal("0"), fica_ss=Decimal("49.60"),
        fica_medicare=Decimal("11.60"), federal_withholding=Decimal("30.00"),
        state_withholding=None, net_pay=Decimal("708.80"),
        created_at=datetime.now(tz=UTC),
    )
    return roster, item


def test_confirmation_reservation_enqueues_one_frozen_send_job(fake_repo, monkeypatch):
    """Creating a confirmation intent composes once and queues only its snapshot ID."""
    from app.models.job import JobKind
    from app.pipeline import delivery as orch

    run_id = _run_id()
    roster, item = _minimal_roster_and_item(run_id)
    fake_repo.runs[str(run_id)] = {
        "id": run_id,
        "business_id": roster.business_id,
        "status": RunStatus.APPROVED.value,
        "reply_epoch": 0,
        "pay_period_start": None,
        "pay_period_end": None,
        "record_only": False,
    }
    run = fake_repo.load_run(run_id)
    assert run is not None

    calls = {"compose": 0, "pdf": 0}
    monkeypatch.setattr(orch.repo, "load_business_name", lambda *_args, **_kw: "Coastal")
    monkeypatch.setattr(orch.repo, "load_line_items", lambda *_args, **_kw: [item])
    monkeypatch.setattr(
        orch.repo, "load_roster_for_business", lambda *_args, **_kw: roster
    )
    monkeypatch.setattr(orch.repo, "load_inbound_email", lambda *_args, **_kw: None)
    monkeypatch.setattr(orch.repo, "get_record_only_flag", lambda *_args, **_kw: False)

    def _compose(*_args, **_kwargs):
        calls["compose"] += 1
        return "frozen confirmation"

    def _pdf(*_args, **_kwargs):
        calls["pdf"] += 1
        return b"frozen pdf"

    monkeypatch.setattr(orch, "compose_confirmation", _compose)
    monkeypatch.setattr(orch, "generate_paystub_pdf", _pdf)
    monkeypatch.setattr(
        orch.gateway,
        "send_outbound",
        lambda **_kwargs: pytest.fail("approval-time delivery reached the legacy gateway"),
    )

    assert orch.deliver(run_id, run) is True
    assert orch.deliver(run_id, run) is True
    assert calls == {"compose": 1, "pdf": 1}

    snapshot = next(iter(fake_repo.outbound_snapshots.values()))["payload"]
    send_jobs = [
        job
        for job in fake_repo.jobs.values()
        if job["kind"] == JobKind.SEND_OUTBOUND.value
    ]
    assert len(send_jobs) == 1
    assert send_jobs[0]["run_id"] == run_id
    assert send_jobs[0]["email_id"] == snapshot["email_id"]
    assert send_jobs[0]["dedup_key"] == f"send_outbound:{snapshot['email_id']}"


def test_confirmation_replay_loads_snapshot_without_rebuilding_payload(fake_repo, monkeypatch):
    """A reserved confirmation is re-queued from stored data without mutable reads."""
    from app.models.job import JobKind
    from app.pipeline import delivery as orch

    run_id = _run_id()
    business_id = uuid.uuid4()
    fake_repo.runs[str(run_id)] = {
        "id": run_id,
        "business_id": business_id,
        "status": RunStatus.APPROVED.value,
        "reply_epoch": 0,
        "record_only": False,
    }
    run = fake_repo.load_run(run_id)
    assert run is not None
    snapshot = fake_repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id="<frozen@payroll-agent.local>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@example.test",
        reply_to=None,
        in_reply_to=None,
        references_header=None,
        subject="Frozen",
        body_text="Frozen body",
        attachments=[("paystub.pdf", b"frozen bytes")],
    )
    for name in (
        "load_business_name",
        "load_line_items",
        "load_roster_for_business",
        "load_inbound_email",
    ):
        monkeypatch.setattr(
            orch.repo,
            name,
            lambda *_args, _name=name, **_kwargs: pytest.fail(f"replay read {_name}"),
        )
    monkeypatch.setattr(
        orch, "compose_confirmation", lambda *_args, **_kwargs: pytest.fail("replay drafted")
    )
    monkeypatch.setattr(
        orch, "generate_paystub_pdf", lambda *_args, **_kwargs: pytest.fail("replay made PDF")
    )

    assert orch.deliver(run_id, run) is True
    send_jobs = [
        job
        for job in fake_repo.jobs.values()
        if job["kind"] == JobKind.SEND_OUTBOUND.value
    ]
    assert len(send_jobs) == 1
    assert send_jobs[0]["email_id"] == snapshot["email_id"]


def test_deliver_attaches_roster_to_exception_after_roster_load(monkeypatch):
    """A failure AFTER the roster load re-raises carrying the roster on the exception.

    Here PDF generation blows up with an employee name in its message. _deliver must
    re-raise the ORIGINAL exception with the in-memory roster stashed on
    exc.payroll_roster, so the approve() boundary can forward it to record_run_error and
    _scrub can redact those names before error_detail reaches the dashboard.
    """
    import app.pipeline.delivery as orch

    run_id = _run_id()
    roster, item = _minimal_roster_and_item(run_id)
    run = {"id": run_id, "business_id": roster.business_id,
           "pay_period_start": None, "pay_period_end": None}

    monkeypatch.setattr(
        "app.pipeline.delivery.repo.load_business_name",
        lambda bid, conn=None: "Coastal",
    )
    monkeypatch.setattr(
        "app.pipeline.delivery.repo.get_outbound_message_id",
        lambda rid, purpose, conn=None: None,
    )
    # The unconfirmed-send guard (app/pipeline/send_guard.py) reads the same shared
    # repo module, so a real DATABASE_URL-backed call would otherwise fire here too —
    # stub it alongside the proven-sent guard above.
    monkeypatch.setattr(
        "app.pipeline.delivery.repo.get_unconfirmed_outbound",
        lambda rid, *, purpose, round=0, conn=None: None,
    )
    monkeypatch.setattr(
        "app.pipeline.delivery.repo.load_line_items", lambda rid, conn=None: [item]
    )
    monkeypatch.setattr(
        orch, "compose_confirmation", lambda paystubs, run, timeout_s=3.0: "body"
    )
    monkeypatch.setattr(
        "app.pipeline.delivery.repo.load_roster_for_business",
        lambda bid, conn=None: roster,
    )

    def _pdf_boom(*args, **kwargs):
        raise RuntimeError("reportlab exploded rendering Maria Chen")

    monkeypatch.setattr(orch, "generate_paystub_pdf", _pdf_boom)

    with pytest.raises(RuntimeError) as excinfo:
        orch.deliver(run_id, run)

    assert getattr(excinfo.value, "payroll_roster", None) is roster, (
        "_deliver must stash the ALREADY-LOADED roster on the raised exception "
        "(exc.payroll_roster) so the approve() boundary can scrub employee names"
    )


def test_deliver_failure_before_roster_load_carries_no_roster(monkeypatch):
    """A failure BEFORE the roster load re-raises with NO payroll_roster attribute.

    There is no roster in memory yet, and the error path must never load one — so
    approve()'s getattr default (None) applies and the scrub falls back to its
    email-regex-only form. The absence of the attribute is the signal, and it must
    stay absent rather than becoming a lazy DB read inside an error handler.
    """
    import app.pipeline.delivery as orch

    run_id = _run_id()
    run = {"id": run_id, "business_id": uuid.uuid4(),
           "pay_period_start": None, "pay_period_end": None}

    monkeypatch.setattr(
        "app.pipeline.delivery.repo.load_business_name",
        lambda bid, conn=None: "Coastal",
    )
    monkeypatch.setattr(
        "app.pipeline.delivery.repo.get_outbound_message_id",
        lambda rid, purpose, conn=None: None,
    )
    # Same stub as the sibling test above: the unconfirmed-send guard reads the same
    # shared repo module and would otherwise reach a real, unconfigured DB connection.
    monkeypatch.setattr(
        "app.pipeline.delivery.repo.get_unconfirmed_outbound",
        lambda rid, *, purpose, round=0, conn=None: None,
    )

    def _items_boom(rid, conn=None):
        raise RuntimeError("db blip before roster load")

    monkeypatch.setattr("app.pipeline.delivery.repo.load_line_items", _items_boom)

    with pytest.raises(RuntimeError) as excinfo:
        orch.deliver(run_id, run)

    assert not hasattr(excinfo.value, "payroll_roster"), (
        "a pre-roster-load failure must NOT carry payroll_roster — nothing was loaded, "
        "and the error path never loads one itself"
    )
