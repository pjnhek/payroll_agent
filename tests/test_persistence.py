"""Calc + persistence round-trip tests (LLM-08, D-A3-05; FIX 2).

Section 1 (always run, DB-free): the full-fidelity gross+FICA+federal calc (Phase 3) —
federal is real (not zero), SS honors the wage-base cap.

NOTE: PRE_FEDERAL_NET_LABEL was removed in Phase 3 (Plan 03-03) — the net is now real.
The Phase 2 tests that asserted federal_withholding == 0 and tested PRE_FEDERAL_NET_LABEL
have been updated to reflect Phase 3 behavior. (Rule 1 auto-fix — Phase 3 retired the
label and replaced the Decimal("0") federal stub with real Pub 15-T withholding.)

Section 2 (live-DB, two-factor guard): a clean run persisted to payroll_runs
round-trips BOTH decision AND reconciliation — mirrors tests/test_seed_roundtrip.py
§2.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.contracts import Decision, Extracted, ExtractedEmployee, PaystubLineItem
from app.models.roster import Employee, NameMatchResult
from app.pipeline.calculate import calculate

_HAS_DB = bool(os.environ.get("DATABASE_URL"))
_HAS_RESET = os.environ.get("ALLOW_DB_RESET") == "1"

_SKIP_LIVE_DB = pytest.mark.skipif(
    not (_HAS_DB and _HAS_RESET),
    reason="Live-DB tests require DATABASE_URL and ALLOW_DB_RESET=1 (two-factor guard)",
)


# ===========================================================================
# Section 1 — thin calc (always run, DB-free)
# ===========================================================================


def _hourly_employee(ytd_ss="12000.00", rate="18.50", pct="0.00") -> Employee:
    return Employee(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        full_name="Maria Chen",
        known_aliases=[],
        pay_type="hourly",
        hourly_rate=Decimal(rate),
        annual_salary=None,
        retirement_contribution_pct=Decimal(pct),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal(ytd_ss),
        pay_periods_per_year=52,
    )


def test_calc_federal_is_real_in_phase3():
    """Phase 3: federal_withholding is real (non-zero) for a typical earning employee.

    Phase 2 asserted federal_withholding == Decimal("0") (thin calc, no federal).
    Phase 3 (Plan 03-03) replaces that stub with real IRS Pub 15-T withholding.
    This test is updated to reflect Phase 3 behavior (Rule 1 auto-fix).
    """
    item = calculate({"hours_regular": Decimal("40")}, _hourly_employee())
    assert isinstance(item, PaystubLineItem)
    # Phase 3: federal_withholding is real for a typical employee (non-zero)
    assert item.federal_withholding > Decimal("0"), "Phase 3 calc has REAL federal withholding"


def test_no_net_pay_label_field_on_paystub():
    """FIX 2 (updated for Phase 3): PaystubLineItem must NOT gain a label field.

    The Phase 2 'pre-federal' label constant has been retired in Phase 3 (Plan 03-03).
    This test retains the critical invariant: no net_pay_label field on PaystubLineItem
    (which is extra='forbid' — such a field would break existing callers).
    """
    assert "net_pay_label" not in PaystubLineItem.model_fields, (
        "PaystubLineItem must NOT gain a label field (FIX 2)"
    )


def test_calc_gross_and_net_hourly():
    """Phase 3 update: net_pay now includes real federal withholding (Rule 1 auto-fix).

    Phase 2 asserted net_pay == 683.39 (gross - FICA, no federal).
    Phase 3 adds real Pub 15-T withholding, so net_pay = gross - FICA - federal.
    The gross and FICA assertions remain unchanged; net_pay is now computed from the item.
    """
    item = calculate({"hours_regular": Decimal("40")}, _hourly_employee(rate="18.50"))
    assert item.gross_pay == Decimal("740.00")  # 40 * 18.50
    # FICA: SS 6.2% (under cap) + Medicare 1.45%; no 401k
    assert item.fica_ss == Decimal("45.88")  # 740 * 0.062
    assert item.fica_medicare == Decimal("10.73")  # 740 * 0.0145
    # Phase 3: net_pay = gross - fica_ss - fica_medicare - federal_withholding (real)
    expected_net = (item.gross_pay - item.fica_ss - item.fica_medicare - item.federal_withholding).quantize(Decimal("0.01"))
    assert item.net_pay == expected_net  # net is now real (includes federal withholding)


def test_ss_honors_wage_base_cap_straddle():
    """Mirror the seed straddle case (Thomas Bergmann): ytd_ss_wages 183,900,
    remaining cap 600 < per-period gross → only $600 is SS-taxable."""
    emp = Employee(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        full_name="Thomas Bergmann",
        known_aliases=[],
        pay_type="salary",
        hourly_rate=None,
        annual_salary=Decimal("240000.00"),
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="married_jointly",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("183900.00"),
        pay_periods_per_year=26,
    )
    item = calculate({}, emp)
    # Only the remaining $600 of wage base is SS-taxable: 600 * 0.062 = 37.20.
    assert item.fica_ss == Decimal("37.20"), "SS must honor the remaining wage-base cap"


def test_absent_hours_treated_as_zero_in_calc():
    item = calculate({"hours_regular": None}, _hourly_employee())
    assert item.gross_pay == Decimal("0.00")


# ===========================================================================
# Section 1b — record_run_error must not clobber a terminal run (WR-04, DB-free)
# ===========================================================================


def test_record_run_error_skips_terminal_run(fake_conn):
    """WR-04 — record_run_error must NOT overwrite a run that is already terminal.

    The FakeConnection replays the status SELECT as 'approved'; record_run_error must
    then make NO error_reason UPDATE and NO status write (it would otherwise flip an
    approved/human-finalized run to ERROR, destroying the approval audit trail)."""
    from app.db import repo

    fake_conn.script_fetchone(("approved",))  # the run is terminal
    repo.record_run_error(uuid.uuid4(), "boom: a late resume hit an exception", conn=fake_conn)

    sql = fake_conn.all_sql()
    assert "SELECT status" in sql, "must read the current status before mutating"
    assert "SET error_reason" not in sql, (
        "a terminal run's error_reason must NOT be overwritten (WR-04)"
    )
    assert "SET status" not in sql, "a terminal run must NOT be flipped to ERROR (WR-04)"


def test_record_run_error_writes_for_non_terminal_run(fake_conn):
    """WR-04 — a NON-terminal run still records the error and advances to ERROR (the
    original behavior is preserved for in-flight runs)."""
    from app.db import repo

    fake_conn.script_fetchone(("extracting",))  # the run is mid-pipeline (non-terminal)
    repo.record_run_error(uuid.uuid4(), "boom: a real stage failure", conn=fake_conn)

    sql = fake_conn.all_sql()
    assert "SET error_reason" in sql, "a non-terminal run must persist the error_reason"
    assert "SET status" in sql, "a non-terminal run must advance to ERROR via set_status"


# ===========================================================================
# Section 2 — live-DB decision + reconciliation round-trip (two-factor guard)
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
def test_decision_roundtrip(seeded_db):
    """A clean run round-trips BOTH decision AND reconciliation from payroll_runs
    (LLM-08, D-A3-05)."""
    from app.db import repo
    from app.db.seed import seed as _seed

    result = _seed(dry_run=True)
    business_id = result.businesses[0]["id"]

    msg_id = f"<{uuid.uuid4()}@coastalcleaning.example>"
    email_id, _ = repo.insert_inbound_email(
        message_id=msg_id,
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="payroll@coastalcleaning.example",
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular.",
        run_id=None,
    )
    run_id = repo.create_run(business_id=business_id, source_email_id=email_id)

    maria = next(e for e in result.employees if e.full_name == "Maria Chen")
    matches = [
        NameMatchResult(
            submitted_name="Maria Chen",
            matched_employee_id=maria.id,
            source="exact",
            resolved=True,
            reason="exact match",
        )
    ]
    extracted = Extracted(
        run_id=run_id,
        employees=[ExtractedEmployee(submitted_name="Maria Chen", hours_regular=Decimal("40"))],
        pay_period_start="2026-06-15",
    )
    decision = Decision(
        final_action="process",
        gate_reasons=[],
        unresolved_names=[],
        missing_fields=[],
        resolutions=matches,
    )

    repo.persist_extracted(run_id, extracted)
    repo.persist_decision(run_id, decision)
    repo.persist_reconciliation(run_id, matches)

    run = repo.load_run(run_id)
    assert run["decision"] is not None
    assert run["decision"]["final_action"] == "process"
    assert run["reconciliation"] is not None, "reconciliation must NOT be NULL (D-A3-05)"
    assert run["reconciliation"][0]["submitted_name"] == "Maria Chen"
    # The deterministic resolution carries source/resolved, NOT a confidence score.
    assert run["reconciliation"][0]["source"] == "exact"
    assert run["reconciliation"][0]["resolved"] is True
    assert "confidence" not in run["reconciliation"][0], (
        "the deterministic reconciliation JSONB must be confidence-free (D-21-01)"
    )
