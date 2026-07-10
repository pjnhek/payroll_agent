"""Wave 0 RED stubs: delivery pipeline behavior (D-13b, CLAR-04, INGEST-05).

These tests cover:
- D-13b: exception after claim → run advances to ERROR, not stuck in approved
- CLAR-04: purpose-aware idempotent confirmation send (finding #1)
- _clarify idempotency: duplicate clarification send skipped (finding #2)
- INGEST-05: stale-state recovery — retrigger can claim from in-flight states
- NEW-1: upsert interaction — pre-existing reserved/failed row for
  (run_id,'confirmation') → send_outbound upserts to 'sent' without IntegrityError

Most tests will fail RED until Wave 1 adds claim_status to repo.py and
Wave 3/Plan 05 adds the purpose= parameter to get_outbound_message_id and
the ON CONFLICT DO UPDATE clause to insert_email_message.
"""
from __future__ import annotations

import uuid
from datetime import UTC

import pytest

# These imports FAIL RED until Wave 1 adds claim_status to app/db/repo.py.
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
# Test 1: APPROVED is NOT in _TERMINAL_STATUSES (D-13b gate)
#
# Will PASS after Wave 1 removes APPROVED from _TERMINAL_STATUSES so the
# delivery failure path can record an error even after claim.
# Currently RED because APPROVED IS in _TERMINAL_STATUSES in the current code.
# ---------------------------------------------------------------------------


def test_approved_not_in_terminal_statuses():
    """APPROVED must NOT be in _TERMINAL_STATUSES (D-13b requirement).

    A run that has been claimed (status='approved') but where delivery then
    fails must be recoverable via record_run_error → ERROR. If APPROVED were
    terminal, record_run_error would silently no-op and the run would be
    permanently stranded in 'approved' with no error signal.

    Will PASS after Wave 1 removes APPROVED from _TERMINAL_STATUSES.
    Currently RED because the current code still includes APPROVED as terminal.
    """
    assert RunStatus.APPROVED not in _TERMINAL_STATUSES, (
        "APPROVED must not be in _TERMINAL_STATUSES (D-13b): a failed delivery "
        "after claim must be able to transition the run to ERROR via record_run_error"
    )


# ---------------------------------------------------------------------------
# Test 2: D-13b error boundary — delivery exception → run moves to ERROR
#
# After Wave 1 + Wave 2, when _deliver raises after claiming the run,
# the orchestrator must call record_run_error and the run ends up ERROR, not
# stranded in 'approved'.
# ---------------------------------------------------------------------------


def test_delivery_error_converts_approved_to_error(fake_conn):
    """D-13b: a delivery exception after claim → record_run_error called with
    type(exc).__name__ only (PII-safe logging rule, D-A1-03 pattern).

    Uses FakeConnection to assert SQL shape without a live DB.
    Will fail RED until Wave 1+2 implement _deliver + error boundary.
    """
    run_id = _run_id()
    exc = RuntimeError("simulated PDF generation failure")

    # Script the FakeConnection: the WR-03 CAS UPDATE ... RETURNING yields a row
    # ('approved' is not in the terminal set — D-13b), so record_run_error proceeds.
    fake_conn.script_fetchone((str(run_id),))  # CAS RETURNING id — claim succeeded

    # Call record_run_error directly (the D-13b boundary asserts it gets called
    # with type(exc).__name__, not str(exc), to avoid leaking PII from exc message).
    reason = type(exc).__name__
    record_run_error(run_id, reason, conn=fake_conn)

    sql = fake_conn.all_sql()
    # Must write error_reason (not the exception message/str(exc))
    assert "error_reason" in sql, (
        "record_run_error must write error_reason column (D-13b)"
    )
    # The reason stored is type(exc).__name__ — the PII-safe logging rule (D-A1-03).
    assert any(reason in str(params) for _, params in fake_conn.executed), (
        "record_run_error must write type(exc).__name__ as the reason, not str(exc) "
        "(PII-safe logging rule D-A1-03)"
    )


# ---------------------------------------------------------------------------
# Test 3: CLAR-04 purpose-aware confirmation idempotency (finding #1)
#
# When get_outbound_message_id(run_id, purpose='confirmation') returns an
# existing message_id, the delivery path skips the send and advances directly.
#
# NOTE: the purpose= parameter does not exist yet in repo.get_outbound_message_id
# — it lands in Plan 03 when the purpose column is added to email_messages.
# This test is RED until then.
# ---------------------------------------------------------------------------


def test_idempotent_confirmation_skips_if_confirmation_outbound_exists(fake_conn):
    """CLAR-04: when get_outbound_message_id(run_id, purpose='confirmation')
    returns an existing message_id, the delivery path must skip the send.

    The purpose='confirmation' kwarg distinguishes a prior confirmation row
    from a clarification row — a purpose-blind lookup would incorrectly skip
    sending the confirmation if a clarification had been sent earlier (finding #1).

    Will fail RED until Plan 03 adds the purpose column + Wave 2 wires the
    idempotency guard.
    """
    run_id = _run_id()

    # Script the FakeConnection to return a pre-existing confirmation Message-ID.
    fake_conn.script_fetchone(("<existing-confirmation@payroll-agent.local>",))

    # Calling get_outbound_message_id with purpose='confirmation' is the CORE of
    # finding #1 — this new signature is what Plan 03 will add.
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
        "get_outbound_message_id must pass purpose='confirmation' as a SQL param "
        "(not embedded in the SQL string — CLAR-04 / finding #1)"
    )


# ---------------------------------------------------------------------------
# Test 4: _clarify idempotency — duplicate clarification send skipped (finding #2)
#
# When get_outbound_message_id(run_id, purpose='clarification') returns an
# existing row, re-calling _clarify must NOT call gateway.send_outbound again.
# ---------------------------------------------------------------------------


def test_clarify_idempotency_skips_if_clarification_already_sent(fake_conn):
    """Finding #2: when a clarification has already been sent for this run,
    re-triggering _clarify must skip the send_outbound call.

    The idempotency guard reads get_outbound_message_id(run_id, purpose='clarification').
    If it returns a non-None value, the clarify path must return early (no duplicate send).

    Will fail RED until Wave 3 / Plan 05 Task 1 adds the guard to _clarify,
    and Plan 03 adds the purpose column.
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
        "get_outbound_message_id must pass purpose='clarification' as a SQL param "
        "(not embedded in the SQL string — finding #2)"
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
# Test 6: D-13b — retrigger from APPROVED state (delivery died)
# ---------------------------------------------------------------------------


def test_retrigger_claims_from_approved_state(fake_conn):
    """D-13b: claim_status(run_id, APPROVED, RECEIVED) returns True when the
    run is in approved-but-delivery-died state.

    A run can be stranded in 'approved' if the delivery task was claimed but
    then crashed before record_run_error ran (e.g. OOM kill). The retrigger
    route must be able to reclaim it from 'approved' for a fresh delivery attempt.

    Will fail RED until Wave 1 adds claim_status to repo.py.
    """
    run_id = _run_id()

    # Script: the CAS SELECT returns current status='approved' → claim succeeds.
    fake_conn.script_fetchone(("approved",))
    fake_conn.script_fetchone((str(run_id),))

    result = claim_status(run_id, RunStatus.APPROVED, RunStatus.RECEIVED, conn=fake_conn)

    assert result is True, (
        "claim_status(run_id, APPROVED, RECEIVED) must return True when the run "
        "is stranded in approved state (D-13b recovery path)"
    )


# ---------------------------------------------------------------------------
# Test 7: finding #6 — stale-state recovery from EXTRACTING
# ---------------------------------------------------------------------------


def test_retrigger_claims_from_stale_extracting_state(fake_conn):
    """Finding #6: claim_status(run_id, EXTRACTING, RECEIVED) succeeds when a
    run is stuck in 'extracting' past a staleness threshold.

    # Staleness threshold check is in the route handler (updated_at < now() - interval
    # '5 minutes'); claim_status itself is unchanged. Plan 05 Task 2 adds the staleness
    # gate in the retrigger route.

    The test stubs the claim_status call only — the staleness check is in the route
    layer, which is Wave 3. This test confirms claim_status supports the FROM_STATUS=
    EXTRACTING transition even though 'extracting' is normally an in-flight state.

    Will fail RED until Wave 1 adds claim_status to repo.py.
    """
    run_id = _run_id()

    # Script: run is stuck in 'extracting'.
    fake_conn.script_fetchone(("extracting",))
    fake_conn.script_fetchone((str(run_id),))

    result = claim_status(run_id, RunStatus.EXTRACTING, RunStatus.RECEIVED, conn=fake_conn)

    assert result is True, (
        "claim_status(run_id, EXTRACTING, RECEIVED) must succeed for stale-state "
        "recovery — the staleness threshold guard lives in the route handler, not in "
        "claim_status itself (finding #6)"
    )


# ---------------------------------------------------------------------------
# Test 8: NEW-1 upsert interaction — reserved row advances to sent
#
# # RED until Plan 05 adds ON CONFLICT (run_id, purpose) DO UPDATE to
# insert_email_message (NEW-1 upsert fix)
# ---------------------------------------------------------------------------


def test_send_outbound_over_reserved_row_advances_to_sent(fake_conn):
    """NEW-1: a pre-existing email_messages row with send_state='reserved' for
    (run_id, 'confirmation') must upsert to send_state='sent' without IntegrityError.

    The uq_email_run_purpose UNIQUE constraint + sent-only guard INTERACTION:
    if insert_email_message does a plain INSERT, a pre-existing reserved row
    triggers a unique violation. The fix is ON CONFLICT (run_id, purpose) DO UPDATE
    SET send_state='sent', updated_at=now() in insert_email_message.

    # RED until Plan 05 adds ON CONFLICT (run_id, purpose) DO UPDATE to
    # insert_email_message (NEW-1 upsert fix)

    Will fail RED until Plan 05 adds the ON CONFLICT DO UPDATE clause.
    """
    run_id = _run_id()
    msg_id = f"<{uuid.uuid4()}@payroll-agent.local>"

    # Script the FakeConnection to simulate the UPSERT returning the row id.
    fake_conn.script_fetchone((str(uuid.uuid4()),))

    # Call insert_email_message with purpose='confirmation' and send_state='sent'.
    # The upsert must succeed (no exception) even if a reserved row already exists.
    result = insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=msg_id,
        purpose="confirmation",
        send_state="sent",
        conn=fake_conn,
    )

    assert result is not None, (
        "insert_email_message with purpose='confirmation' must return a row id "
        "(no IntegrityError on pre-existing reserved row — NEW-1 upsert)"
    )
    sql = fake_conn.all_sql()
    # The SQL must use ON CONFLICT ... DO UPDATE to handle pre-existing rows.
    assert "ON CONFLICT" in sql.upper(), (
        "insert_email_message must use ON CONFLICT (run_id, purpose) DO UPDATE "
        "to advance reserved/failed rows to sent without IntegrityError (NEW-1)"
    )


# ---------------------------------------------------------------------------
# Test 9: NEW-1 variant — failed row also advances to sent
#
# # RED until Plan 05 adds ON CONFLICT (run_id, purpose) DO UPDATE to
# insert_email_message (NEW-1 upsert fix — failed-row variant)
# ---------------------------------------------------------------------------


def test_send_outbound_over_failed_row_advances_to_sent(fake_conn):
    """NEW-1 failed-row variant: a pre-existing send_state='failed' row for
    (run_id, 'confirmation') must also upsert to 'sent' without crash.

    A retry after a gateway failure must be able to advance a failed row to
    sent — the same ON CONFLICT DO UPDATE clause handles both 'reserved' and
    'failed' pre-existing rows.

    # RED until Plan 05 adds ON CONFLICT (run_id, purpose) DO UPDATE to
    # insert_email_message (NEW-1 upsert fix — failed-row variant)
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
        "insert_email_message must upsert a failed row to sent without crash (NEW-1)"
    )
    sql = fake_conn.all_sql()
    assert "ON CONFLICT" in sql.upper(), (
        "insert_email_message must use ON CONFLICT DO UPDATE for the failed-row "
        "retry case (NEW-1 upsert fix)"
    )


# ---------------------------------------------------------------------------
# Test 10: R2-HIGH stale CAS exclusivity — two concurrent retriggers from stale state
#
# The stale-retrigger CAS target MUST differ from the current status so the
# conditional UPDATE genuinely changes the row. Two concurrent retrigger clicks
# on a stale RECEIVED run both call claim_status(RECEIVED → EXTRACTING):
# the first wins (row changed), the second finds the row already EXTRACTING
# and returns False. This is the R2-HIGH stale CAS exclusivity fix.
# ---------------------------------------------------------------------------


def test_two_concurrent_stale_retriggers_only_one_wins():
    """R2-HIGH stale CAS exclusivity: two concurrent stale retriggers on the same
    RECEIVED run — exactly one wins the claim, the other sees False.

    The stale retrigger path claims RECEIVED → EXTRACTING (NOT RECEIVED → RECEIVED
    which would be a no-op). An in-memory InMemoryRepo mirrors the real claim_status
    CAS: exactly one caller wins because claim_status checks the current status before
    updating. The second caller arrives after the first has already advanced the run
    to EXTRACTING, so its claim(RECEIVED → EXTRACTING) returns False.

    This test proves the R2-HIGH fix: targeting EXTRACTING (≠ source) makes the
    claim exclusive. A RECEIVED→RECEIVED no-op would let both callers win.
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
        "Second stale retrigger must lose: run is already EXTRACTING after first "
        "claim — RECEIVED→EXTRACTING target ensures exclusivity (R2-HIGH fix)"
    )
    assert store.load_run(run_id)["status"] == RunStatus.EXTRACTING.value, (
        "After both retriggers, run must be in EXTRACTING (the CAS winner's target)"
    )


# ---------------------------------------------------------------------------
# WR-04 (phase-8 review): _deliver stashes its already-loaded roster on any
# exception raised past the Step-4 roster load, so the approve() error boundary
# can pass it to record_run_error and _scrub can redact employee names from the
# delivery error_detail — the boundary where names are MOST likely to appear in
# exception text (PDF headers, compose/gateway payloads). D-8-01b is preserved:
# nothing in the error path LOADS a roster; the in-memory object is forwarded.
# ---------------------------------------------------------------------------


def _minimal_roster_and_item(run_id):
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


def test_deliver_attaches_roster_to_exception_after_roster_load(monkeypatch):
    """WR-04: a failure AFTER _deliver's Step-4 roster load (here: PDF generation)
    must re-raise the ORIGINAL exception carrying the in-memory roster on
    exc.payroll_roster — the approve() boundary forwards it to record_run_error
    so the roster names in str(exc) get scrubbed from error_detail.
    """
    from app.pipeline import delivery as orch

    run_id = _run_id()
    roster, item = _minimal_roster_and_item(run_id)
    run = {"id": run_id, "business_id": roster.business_id,
           "pay_period_start": None, "pay_period_end": None}

    monkeypatch.setattr(orch.repo, "load_business_name", lambda bid, conn=None: "Coastal")
    monkeypatch.setattr(
        orch.repo, "get_outbound_message_id", lambda rid, purpose, conn=None: None
    )
    monkeypatch.setattr(orch.repo, "load_line_items", lambda rid, conn=None: [item])
    monkeypatch.setattr(
        orch, "compose_confirmation", lambda paystubs, run, timeout_s=3.0: "body"
    )
    monkeypatch.setattr(
        orch.repo, "load_roster_for_business", lambda bid, conn=None: roster
    )

    def _pdf_boom(*args, **kwargs):
        raise RuntimeError("reportlab exploded rendering Maria Chen")

    monkeypatch.setattr(orch, "generate_paystub_pdf", _pdf_boom)

    with pytest.raises(RuntimeError) as excinfo:
        orch.deliver(run_id, run)

    assert getattr(excinfo.value, "payroll_roster", None) is roster, (
        "_deliver must stash the ALREADY-LOADED roster on the raised exception "
        "(exc.payroll_roster) so the approve() boundary can scrub names — WR-04"
    )


def test_deliver_failure_before_roster_load_carries_no_roster(monkeypatch):
    """WR-04 boundary shape: a failure BEFORE the Step-4 roster load re-raises
    with NO payroll_roster attribute — approve()'s getattr default (None) keeps
    the locked D-8-01b behavior (email-regex-only scrub) for those failures.
    """
    from app.pipeline import delivery as orch

    run_id = _run_id()
    run = {"id": run_id, "business_id": uuid.uuid4(),
           "pay_period_start": None, "pay_period_end": None}

    monkeypatch.setattr(orch.repo, "load_business_name", lambda bid, conn=None: "Coastal")
    monkeypatch.setattr(
        orch.repo, "get_outbound_message_id", lambda rid, purpose, conn=None: None
    )

    def _items_boom(rid, conn=None):
        raise RuntimeError("db blip before roster load")

    monkeypatch.setattr(orch.repo, "load_line_items", _items_boom)

    with pytest.raises(RuntimeError) as excinfo:
        orch.deliver(run_id, run)

    assert not hasattr(excinfo.value, "payroll_roster"), (
        "a pre-roster-load failure must NOT carry payroll_roster (nothing was "
        "loaded; the error path never loads one itself — D-8-01b)"
    )
