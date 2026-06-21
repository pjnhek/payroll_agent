"""Calc + persistence round-trip tests (LLM-08, D-A3-05; FIX 2).

Section 1 (always run, DB-free): the thin gross+FICA calc — federal=0, the
pre-federal label is a module constant (not a contract field), SS honors the
wage-base cap.

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
from app.pipeline.calculate import PRE_FEDERAL_NET_LABEL, calculate

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


def test_calc_federal_is_zero_and_no_fabricated_figure():
    item = calculate({"hours_regular": Decimal("40")}, _hourly_employee())
    assert isinstance(item, PaystubLineItem)
    assert item.federal_withholding == Decimal("0"), "Phase 2 calc has NO federal"


def test_pre_federal_label_is_a_module_constant_not_a_contract_field():
    """FIX 2: the pre-federal label lives in calculate.py, NOT on PaystubLineItem
    (which is extra='forbid' — a net_pay_label field would raise)."""
    assert "pre-federal" in PRE_FEDERAL_NET_LABEL.lower()
    assert "net_pay_label" not in PaystubLineItem.model_fields, (
        "PaystubLineItem must NOT gain a label field (FIX 2)"
    )


def test_calc_gross_and_net_hourly():
    item = calculate({"hours_regular": Decimal("40")}, _hourly_employee(rate="18.50"))
    assert item.gross_pay == Decimal("740.00")  # 40 * 18.50
    # FICA: SS 6.2% (under cap) + Medicare 1.45%; no 401k; no federal.
    assert item.fica_ss == Decimal("45.88")  # 740 * 0.062
    assert item.fica_medicare == Decimal("10.73")  # 740 * 0.0145
    assert item.net_pay == Decimal("683.39")  # 740 - 45.88 - 10.73


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
            match_type="exact",
            confidence=Decimal("1.0"),
            reason="exact match",
        )
    ]
    extracted = Extracted(
        run_id=run_id,
        employees=[ExtractedEmployee(submitted_name="Maria Chen", hours_regular=Decimal("40"))],
        pay_period_start="2026-06-15",
    )
    decision = Decision(
        model_action="process",
        gate_triggered=False,
        gate_reasons=[],
        final_action="process",
        unresolved_names=[],
        missing_fields=[],
        confidence=Decimal("1.0"),
        reasons=["clean run"],
    )

    repo.persist_extracted(run_id, extracted)
    repo.persist_decision(run_id, decision)
    repo.persist_reconciliation(run_id, matches)

    run = repo.load_run(run_id)
    assert run["decision"] is not None
    assert run["decision"]["final_action"] == "process"
    assert run["reconciliation"] is not None, "reconciliation must NOT be NULL (D-A3-05)"
    assert run["reconciliation"][0]["submitted_name"] == "Maria Chen"
    assert run["reconciliation"][0]["confidence"] == "1.0"
