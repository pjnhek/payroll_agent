"""Payroll calc — full-fidelity gross / FICA / federal / net (Phase 3).

A PURE function: typed values in, PaystubLineItem out. NO DB, NO connection.

Phase 3 delivers the complete payroll math:
  - Salaried leave pay: annual / 2080 * leave_hours (frequency-independent, FIX A).
  - Real IRS Pub 15-T 2026 federal withholding via federal_withholding_2026() (CALC-05).
  - 401k reduces the FEDERAL taxable base but NOT the FICA base (CALC-03).
  - Real net: gross - pretax_401k - fica_ss - fica_medicare - federal_withholding (CALC-07).
  - Additional Medicare 0.9% surtax over $200k YTD is NOT modeled (User Decision 1, FIX B).
    The additional_medicare_not_modeled flag on PaystubLineItem fires when the
    ytd_ss_wages proxy + current gross exceeds $200,000, making the limitation visible.
  - Arithmetic reconciliation backstop via _raise_if_reconciliation_drift() named helper
    (CALC-08, R2-3). Uses an explicit PayrollCalculationError raise — not a bare assert
    (python -O strips asserts silently; PayrollCalculationError cannot be stripped).

FICA constants (2026) — migrated to tax_tables_2026.py per D-02:
  - Social Security (OASDI): 6.2% on wages up to the $184,500 wage base, honoring
    ytd_ss_wages so only the remaining cap is taxed (straddle case).
  - Medicare: 1.45%, NO wage cap. (The 0.9% additional-Medicare surtax is disclaimed
    and NOT modeled — see User Decision 1 / FIX B above.)
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.models.contracts import PaystubLineItem
from app.models.roster import Employee
from app.pipeline.federal_withholding import federal_withholding_2026
from app.pipeline.tax_tables_2026 import (
    MEDICARE_RATE as _MEDICARE_RATE,
)
from app.pipeline.tax_tables_2026 import (
    SS_RATE as _SS_RATE,
)
from app.pipeline.tax_tables_2026 import (
    SS_WAGE_BASE as _SS_WAGE_BASE,
)

_CENTS = Decimal("0.01")

# WR-03: filing-status-specific Additional Medicare 0.9% surtax thresholds (IRS).
# Used only to set the additional_medicare_not_modeled DISCLAIMER flag — no surtax is
# withheld. $200k single / $250k MFJ / $125k MFS, matching README "Known Limitations".
_ADDITIONAL_MEDICARE_THRESHOLDS = {
    "single": Decimal("200000"),
    "married_jointly": Decimal("250000"),
    "married_separately": Decimal("125000"),
}


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


def _to_decimal(value: object) -> Decimal:
    """Coerce one hours value to Decimal, rejecting float (WR-02 / D-05).

    The project invariant is "Decimal everywhere, never float": Decimal(7.1) yields
    7.0999999999999996447… and would inject binary-float error into gross and every
    downstream amount. calculate() takes a raw dict, so the engine — not just the
    caller — must enforce this. A float is a programming error, not user input, so we
    raise loudly rather than silently coercing via str() (which would hide the bug).
    int / str / Decimal / None are all accepted (None → 0). Values must be non-negative
    (mirrors ExtractedEmployee Field(ge=0) — review round 3 WR-01).
    """
    if value is None:
        return Decimal("0")
    # WR-01 (review round 2): bool is a subclass of int, so isinstance(True, float) is
    # False and Decimal(True) == 1. Without this check, hours_regular=True silently
    # becomes 1 hour of pay — the exact silent-coercion this function exists to prevent.
    # Check bool BEFORE float/int since bool ⊂ int.
    if isinstance(value, bool):
        raise TypeError(
            f"hours value must not be bool (D-05: Decimal everywhere): got {value!r}. "
            "Pass an int, str, or Decimal."
        )
    if isinstance(value, float):
        raise TypeError(
            f"hours value must not be float (D-05: Decimal everywhere): got {value!r}. "
            "Pass an int, str, or Decimal."
        )
    # Empty string is treated as absent (preserves the prior `or 0` coalescing for "").
    if value == "":
        return Decimal("0")
    # IN-01 (review round 3): surface a domain error for garbage input rather than a bare
    # decimal.InvalidOperation, matching the typed errors used above.
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"hours value is not a valid number: got {value!r}") from exc
    # WR-01 (review round 3): the raw-dict seam is the last-line defense against a
    # "wrong-but-reconciliation-passing" paystub. Negatives are the single most
    # consequential wrong number it must catch — the reconciliation backstop is a
    # sign-blind arithmetic identity, so a negative gross/net would tie out and ship.
    # Mirror the model-layer ExtractedEmployee Field(ge=0) here.
    if result < 0:
        raise ValueError(
            f"hours value must be non-negative (matches ExtractedEmployee Field ge=0): "
            f"got {result}."
        )
    return result


_HOURS_FIELDS = (
    "hours_regular",
    "hours_overtime",
    "hours_vacation",
    "hours_sick",
    "hours_holiday",
)


def _resolved_hours(resolved: dict) -> dict[str, Decimal]:
    """Coalesce the five hours fields to Decimal('0') for any unspecified field.

    WR-02 (review round 2): calculate() takes a raw dict (not a Pydantic model with
    extra="forbid"), so this is the only seam that can catch a malformed hours payload.
    Reject unknown/misspelled keys (e.g. "hours_regualr") rather than silently dropping
    them — a dropped key would zero that hours type and produce a wrong-but-reconciliation-
    passing paystub, violating the module's "never silently ship a wrong number" thesis.
    """
    unknown = set(resolved) - set(_HOURS_FIELDS)
    if unknown:
        raise ValueError(
            f"Unknown hours key(s): {sorted(unknown)}. "
            f"Expected only {list(_HOURS_FIELDS)}."
        )
    return {f: _to_decimal(resolved.get(f)) for f in _HOURS_FIELDS}


class PayrollCalculationError(Exception):
    """Raised by _raise_if_reconciliation_drift() when net + taxes + deductions does not tie to gross.

    This is an arithmetic backstop (CALC-08), NOT the correctness oracle for tax math.
    A transcription bug in tax_tables_2026.py can produce internally-consistent but
    wrong numbers — the reconciliation check does NOT catch that. The golden tests
    (test_federal_withholding.py) are the correctness oracle.
    """


def _raise_if_reconciliation_drift(
    gross: Decimal,
    pretax_401k: Decimal,
    fica_ss: Decimal,
    fica_medicare: Decimal,
    federal_withholding: Decimal,
    net_pay: Decimal,
) -> None:
    """Arithmetic backstop (CALC-08): raise PayrollCalculationError if net + taxes + deductions != gross.

    This is a pure arithmetic identity check, NOT a tax-correctness oracle.
    A transcription error in tax_tables_2026.py can produce a self-consistent but
    wrong paystub — this check does NOT catch that. The golden test suite is the oracle.

    CRITICAL (FIX C / R2-3): uses an explicit raise, NOT assert. Python -O strips assert
    statements silently, so the backstop would disappear in optimized deployments.
    PayrollCalculationError is a real exception that cannot be stripped.

    Call signature note: state_withholding is always Decimal("0") / None in Phase 3,
    so it is not included in the parameters — the caller reconstructs from these six values.
    """
    _state_wh = Decimal("0")  # state_withholding is always None in Phase 3
    _reconstructed = _money(net_pay + pretax_401k + fica_ss + fica_medicare + federal_withholding + _state_wh)
    if _reconstructed != gross:
        raise PayrollCalculationError(
            f"Reconciliation failed: reconstructed={_reconstructed} != gross={gross}. "
            "This is an arithmetic bug in calculate(), not a tax-math error. "
            "Check the net_pay, FICA, and federal_withholding formulas."
        )


def calculate(
    resolved_hours: dict,
    employee: Employee,
    contribution_401k_override: Decimal | None = None,
) -> PaystubLineItem:
    """Compute one employee's full-fidelity paystub (gross + FICA + federal + net).

    resolved_hours: a mapping of the five hours_* fields (None/absent → 0). For a
    salaried employee the regular/overtime hours are ignored — gross is annual_salary /
    pay_periods + any leave pay (vacation/sick/holiday × implied hourly rate).
    contribution_401k_override: a current-run-only 401k rate the CLIENT specified for
    this run (D-A3-04 / LLM-03). When provided it overrides the employee's stored
    default for THIS paystub only — it never mutates the stored default. (review fix:
    the override was parsed but silently ignored before.)
    """
    hours = _resolved_hours(resolved_hours)

    if employee.pay_type == "hourly":
        rate = employee.hourly_rate or Decimal("0")
        # Overtime at 1.5x; all other hour types at straight time (D-03).
        # D-03: OT is EXPLICIT-ONLY. hours_regular is paid straight-time even if > 40.
        # Leave hours (vacation/sick/holiday) count as straight time and are EXCLUDED
        # from any OT threshold — the 40-hour OT trigger is never applied here.
        straight = (
            hours["hours_regular"]
            + hours["hours_vacation"]
            + hours["hours_sick"]
            + hours["hours_holiday"]
        )
        # IN-04: round once, here — this is the hourly branch's single rounding point
        # (rate * hours is not otherwise quantized).
        gross = _money(rate * straight + rate * Decimal("1.5") * hours["hours_overtime"])
    else:  # salary
        annual = employee.annual_salary or Decimal("0")
        p = Decimal(employee.pay_periods_per_year)
        period_salary = _money(annual / p)
        # CALC-02: salaried leave pay uses the implied-hourly form (FIX A — frequency-independent).
        # implied_hourly = annual_salary / 2080  (where 2080 = 40h/wk * 52 wk/yr).
        # leave_pay = implied_hourly * leave_hours  — identical result for p=52, p=26, p=24, p=12.
        # Do NOT use period_salary * leave_h / standard_h_per_period where
        # standard_h = 40 * p / 52 — that expression is frequency-dependent and WRONG
        # for non-weekly schedules (e.g. p=24 → 4.7x too high, p=12 → 18.8x too high).
        _ANNUAL_WORK_HOURS = Decimal("2080")  # 40h/wk * 52 wk — standard work-year hours
        # IN-02: _resolved_hours() always returns all five keys, so direct subscripts
        # are safe (matches the hourly branch above); the prior .get() defaults were dead.
        leave_hours = (
            hours["hours_vacation"]
            + hours["hours_sick"]
            + hours["hours_holiday"]
        )
        leave_pay = _money((annual / _ANNUAL_WORK_HOURS) * leave_hours)
        # Salaried branch's single rounding point (IN-04: each branch now rounds once).
        gross = _money(period_salary + leave_pay)

    # Pre-tax 401k: the client's current-run override if supplied, else the
    # employee's stored default rate — applied to gross (review fix: D-A3-04).
    rate_401k = (
        contribution_401k_override
        if contribution_401k_override is not None
        else employee.retirement_contribution_pct
    )
    pretax_401k = _money(gross * rate_401k)

    # FICA — SS honors the remaining wage-base cap; Medicare has no cap.
    # CRITICAL (CALC-03): FICA base is GROSS — 401k does NOT reduce the FICA base.
    # Only the federal taxable base (below) is reduced by pretax_401k.
    remaining_cap = _SS_WAGE_BASE - employee.ytd_ss_wages
    if remaining_cap < 0:
        remaining_cap = Decimal("0")
    ss_taxable = min(gross, remaining_cap)
    fica_ss = _money(ss_taxable * _SS_RATE)
    fica_medicare = _money(gross * _MEDICARE_RATE)

    # Phase 3: real IRS Pub 15-T 2026 federal withholding (CALC-05).
    # 401k reduces the federal taxable base but NOT the FICA base (CALC-03).
    federal_taxable = _money(gross - pretax_401k)
    federal_withholding = federal_withholding_2026(federal_taxable, employee)
    net_pay = _money(gross - pretax_401k - fica_ss - fica_medicare - federal_withholding)

    # User Decision 1 (FIX B): Additional Medicare 0.9% on wages over $200k YTD is NOT modeled.
    # Trigger: (ytd_ss_wages_as_medicare_proxy + current_gross) > $200,000.
    # Why ytd_ss_wages as proxy: it is a DOCUMENTED LOWER BOUND for YTD Medicare wages
    # (Medicare has no wage cap, so Medicare YTD >= SS YTD always). Adding current gross
    # gives a conservative Medicare-wage estimate that CAN cross $200k.
    # Limitation: if an employee's true Medicare YTD already exceeds their capped SS YTD
    # (wages above $184,500 in prior periods), this proxy UNDER-FLAGS — accepted limitation
    # of the static-seed model (no per-employee YTD Medicare ledger in Phase 3).
    # R2-2 note: ytd_ss_wages is capped at $184,500 (the SS wage base) in any real run —
    # it CANNOT legitimately exceed that cap. Tests must use realistic values (ytd_ss_wages <= 184500).
    # WR-03 (review round 2): the Additional Medicare 0.9% surtax threshold is filing-status
    # specific per the IRS — $200k (single), $250k (MFJ), $125k (MFS). The flag is now
    # status-aware so it matches the documented thresholds (the prior flat $200k over-flagged
    # MFJ between $200k–$250k). The flag only DISCLAIMS a non-modeled feature (withholds
    # nothing), so this is an accuracy/consistency fix, not a withholding change.
    additional_medicare_not_modeled = (
        employee.ytd_ss_wages + gross
    ) > _ADDITIONAL_MEDICARE_THRESHOLDS[employee.filing_status]

    # CALC-08: arithmetic backstop — call the named helper (R2-3).
    # The helper is a pure function that raises PayrollCalculationError on drift.
    # Extracted as a named helper so both paths (pass and drift-raises) can be
    # directly unit-tested via pytest.raises without monkeypatching.
    _raise_if_reconciliation_drift(
        gross, pretax_401k, fica_ss, fica_medicare, federal_withholding, net_pay
    )

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
        created_at=datetime.now(UTC),
        additional_medicare_not_modeled=additional_medicare_not_modeled,
    )
