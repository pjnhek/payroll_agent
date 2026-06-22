"""Thin payroll calc — gross + FICA only, net labeled "pre-federal" (D-A6-01).

A PURE function: typed values in, PaystubLineItem out. NO DB, NO connection.

Phase 2 calc is DELIBERATELY thin (ROADMAP): gross + FICA only. There is NO
federal withholding here — federal_withholding is Decimal("0") and no fabricated
federal figure appears anywhere. Real IRS Pub 15-T federal withholding lands in
Phase 3, before any correctness claim.

FIX 2 — "pre-federal" is a DISPLAY/SERIALIZATION concern, NOT a contract field:
  PaystubLineItem is extra="forbid" with fields net_pay + federal_withholding; the
  (net_pay, federal_withholding=Decimal("0")) PAIR IS the pre-federal semantic. The
  human-readable label is the module constant PRE_FEDERAL_NET_LABEL below — reused
  by the README and any run rendering — so "net is pre-federal" is asserted
  everywhere WITHOUT inventing a PaystubLineItem field (which would raise on the
  forbid contract).

FICA constants (2026, RESEARCH §5; transcribed from SSA/IRS):
  - Social Security (OASDI): 6.2% on wages up to the $184,500 wage base, honoring
    ytd_ss_wages so only the remaining cap is taxed (straddle case).
  - Medicare: 1.45%, NO wage cap. (The 0.9% additional-Medicare surtax is out of
    scope for the demo's wage levels — Phase 3+.)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from app.models.contracts import PaystubLineItem
from app.models.roster import Employee

# FIX 2: the human-readable "pre-federal" label (NOT a PaystubLineItem field).
# The README and run rendering reuse this exact wording so the disclaimer and the
# computed value always agree.
PRE_FEDERAL_NET_LABEL = (
    "Net pay (pre-federal — real federal withholding lands in Phase 3)"
)

# 2026 FICA constants (RESEARCH §5).
_SS_RATE = Decimal("0.062")
_SS_WAGE_BASE = Decimal("184500")
_MEDICARE_RATE = Decimal("0.0145")

_CENTS = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    """Round a Decimal to cents using ROUND_HALF_UP (round half AWAY from zero).

    WR-06: this is standard payroll rounding, NOT banker's rounding. Banker's rounding
    is ROUND_HALF_EVEN (round half to the nearest even cent); ROUND_HALF_UP always
    rounds a halfway value up in magnitude. The behavior is deliberately UNCHANGED
    here — ROUND_HALF_UP is the defensible payroll convention and every calc/FICA test
    is pinned to it. Only the previous "banker-safe" comment was wrong and is corrected
    (rounding mode is correctness-relevant for the Phase 3 IRS Pub 15-T port).
    """
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _resolved_hours(resolved: dict) -> dict[str, Decimal]:
    """Coalesce the five hours fields to Decimal('0') for any unspecified field."""
    fields = (
        "hours_regular",
        "hours_overtime",
        "hours_vacation",
        "hours_sick",
        "hours_holiday",
    )
    return {f: Decimal(resolved.get(f) or 0) for f in fields}


def calculate(resolved_hours: dict, employee: Employee) -> PaystubLineItem:
    """Compute one employee's thin paystub (gross + FICA, net pre-federal).

    resolved_hours: a mapping of the five hours_* fields (None/absent → 0). For a
    salaried employee hours are ignored — gross is annual_salary / pay_periods.
    """
    hours = _resolved_hours(resolved_hours)

    if employee.pay_type == "hourly":
        rate = employee.hourly_rate or Decimal("0")
        # Overtime at 1.5x; all other hour types at straight time (thin Phase 2).
        straight = (
            hours["hours_regular"]
            + hours["hours_vacation"]
            + hours["hours_sick"]
            + hours["hours_holiday"]
        )
        gross = rate * straight + rate * Decimal("1.5") * hours["hours_overtime"]
    else:  # salary
        annual = employee.annual_salary or Decimal("0")
        gross = annual / Decimal(employee.pay_periods_per_year)

    gross = _money(gross)

    # Pre-tax 401k: the employee's stored default rate applied to gross.
    pretax_401k = _money(gross * employee.retirement_contribution_pct)

    # FICA — SS honors the remaining wage-base cap; Medicare has no cap.
    remaining_cap = _SS_WAGE_BASE - employee.ytd_ss_wages
    if remaining_cap < 0:
        remaining_cap = Decimal("0")
    ss_taxable = min(gross, remaining_cap)
    fica_ss = _money(ss_taxable * _SS_RATE)
    fica_medicare = _money(gross * _MEDICARE_RATE)

    # Phase 2: NO federal withholding (no fabricated figure). The pre-federal net.
    federal_withholding = Decimal("0")
    net_pay = _money(gross - pretax_401k - fica_ss - fica_medicare)

    return PaystubLineItem(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),  # the orchestrator overwrites with the real run_id
        employee_id=employee.id,
        submitted_name=employee.full_name,
        hours_regular=hours["hours_regular"],
        hours_overtime=hours["hours_overtime"],
        hours_vacation=hours["hours_vacation"],
        hours_sick=hours["hours_sick"],
        hours_holiday=hours["hours_holiday"],
        gross_pay=gross,
        pretax_401k=pretax_401k,
        fica_ss=fica_ss,
        fica_medicare=fica_medicare,
        federal_withholding=federal_withholding,
        state_withholding=None,
        net_pay=net_pay,
        created_at=datetime.now(timezone.utc),
    )
