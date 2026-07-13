"""Payroll calculation — gross, FICA, federal withholding, and net for one employee.

A PURE function: typed values in, PaystubLineItem out. NO DB, NO connection.

Invariants this module exists to hold:
  - Salaried leave pay is annual / 2080 * leave_hours — frequency-independent. Any
    period-relative form silently overpays non-weekly schedules.
  - 401k reduces the FEDERAL taxable base but NOT the FICA base. Reducing the FICA base
    would under-withhold Social Security and Medicare on every contributing employee.
  - Federal withholding comes from the real IRS Pub 15-T 2026 percentage method
    (federal_withholding_2026), never a flat rate.
  - net = gross - pretax_401k - fica_ss - fica_medicare - federal_withholding.
  - Every paystub passes an arithmetic reconciliation backstop before it is returned
    (_raise_if_reconciliation_drift). It raises PayrollCalculationError rather than
    asserting: `python -O` strips asserts silently, which would delete the backstop in
    an optimized deployment.
  - The Additional Medicare 0.9% surtax is NOT modeled. It is disclaimed via the
    additional_medicare_not_modeled flag so the limitation is visible on the paystub
    rather than silently absent.

FICA constants (2026) live in tax_tables_2026.py:
  - Social Security (OASDI): 6.2% up to the $184,500 wage base, honoring ytd_ss_wages so
    only the remaining cap is taxed (the straddle case — taxing full gross past the cap
    over-withholds).
  - Medicare: 1.45%, NO wage cap.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import cast

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

# Filing-status-specific Additional Medicare 0.9% surtax thresholds (IRS).
# Used ONLY to set the additional_medicare_not_modeled DISCLAIMER flag — no surtax is
# withheld. $200k single / $250k MFJ / $125k MFS, matching README "Known Limitations".
# A single flat $200k threshold would over-flag married-jointly employees between
# $200k and $250k, disclaiming a limitation that does not apply to them.
_ADDITIONAL_MEDICARE_THRESHOLDS = {
    "single": Decimal("200000"),
    "married_jointly": Decimal("250000"),
    "married_separately": Decimal("125000"),
}


def _money(value: Decimal) -> Decimal:
    """Round a Decimal to cents using ROUND_HALF_UP (round half AWAY from zero).

    This is standard payroll rounding, NOT banker's rounding. Banker's rounding is
    ROUND_HALF_EVEN (round half to the nearest even cent); ROUND_HALF_UP always rounds a
    halfway value up in magnitude. The rounding mode is correctness-relevant for the IRS
    Pub 15-T port — every calc/FICA golden test is pinned to ROUND_HALF_UP, so switching
    to ROUND_HALF_EVEN would shift withheld cents on half-cent boundaries and break the
    reconciliation identity against the IRS worked examples. Do not "modernize" this.
    """
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _to_decimal(value: object) -> Decimal:
    """Coerce one hours value to Decimal, rejecting float.

    The project invariant is "Decimal everywhere, never float": Decimal(7.1) yields
    7.0999999999999996447… and would inject binary-float error into gross and every
    downstream amount. calculate() takes a raw dict, so the engine — not just the
    caller — must enforce this. A float is a programming error, not user input, so we
    raise loudly rather than silently coercing via str() (which would hide the bug).
    int / str / Decimal / None are all accepted (None → 0). Values must be non-negative,
    mirroring ExtractedEmployee's Field(ge=0).
    """
    if value is None:
        return Decimal("0")
    # bool is a subclass of int, so isinstance(True, float) is False and Decimal(True) == 1.
    # Without this check, hours_regular=True silently becomes 1 hour of pay — the exact
    # silent coercion this function exists to prevent.
    # Check bool BEFORE float/int since bool ⊂ int.
    if isinstance(value, bool):
        raise TypeError(
            f"hours value must not be bool (Decimal everywhere, never float): got {value!r}. "
            "Pass an int, str, or Decimal."
        )
    if isinstance(value, float):
        raise TypeError(
            f"hours value must not be float (Decimal everywhere, never float): got {value!r}. "
            "Pass an int, str, or Decimal."
        )
    # Empty string is treated as absent (preserves `or 0` coalescing for "").
    if value == "":
        return Decimal("0")
    # Surface a domain error for garbage input rather than a bare decimal.InvalidOperation,
    # matching the typed errors used above.
    try:
        result = Decimal(cast(Decimal | int | str, value))
    except InvalidOperation as exc:
        raise ValueError(f"hours value is not a valid number: got {value!r}") from exc
    # The raw-dict seam is the last line of defense against a "wrong-but-reconciliation-
    # passing" paystub. Negatives are the most consequential wrong number it must catch:
    # the reconciliation backstop is a sign-blind arithmetic identity, so a negative
    # gross/net would tie out and ship. Mirror the model-layer ExtractedEmployee Field(ge=0).
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


def _resolved_hours(resolved: dict[str, object]) -> dict[str, Decimal]:
    """Coalesce the five hours fields to Decimal('0') for any unspecified field.

    calculate() takes a raw dict (not a Pydantic model with extra="forbid"), so this is
    the only seam that can catch a malformed hours payload. Reject unknown/misspelled keys
    (e.g. "hours_regualr") rather than silently dropping them — a dropped key would zero
    that hours type and produce a wrong-but-reconciliation-passing paystub (an employee
    underpaid by their whole overtime line), violating this module's "never silently ship
    a wrong number" thesis.
    """
    unknown = set(resolved) - set(_HOURS_FIELDS)
    if unknown:
        raise ValueError(
            f"Unknown hours key(s): {sorted(unknown)}. "
            f"Expected only {list(_HOURS_FIELDS)}."
        )
    return {f: _to_decimal(resolved.get(f)) for f in _HOURS_FIELDS}


class PayrollCalculationError(Exception):
    """Raised by _raise_if_reconciliation_drift() when net + taxes + deductions
    does not tie to gross.

    This is an arithmetic backstop, NOT the correctness oracle for tax math. A
    transcription bug in tax_tables_2026.py can produce internally-consistent but wrong
    numbers — the reconciliation check does NOT catch that, because a wrong withholding
    amount still ties out against the net computed from it. The golden tests
    (test_federal_withholding.py, keyed to the IRS worked examples) are the oracle.
    """


def _raise_if_reconciliation_drift(
    gross: Decimal,
    pretax_401k: Decimal,
    fica_ss: Decimal,
    fica_medicare: Decimal,
    federal_withholding: Decimal,
    net_pay: Decimal,
) -> None:
    """Arithmetic backstop: raise PayrollCalculationError if
    net + taxes + deductions != gross.

    This is a pure arithmetic identity check, NOT a tax-correctness oracle. A
    transcription error in tax_tables_2026.py can produce a self-consistent but wrong
    paystub — this check does NOT catch that. The golden test suite is the oracle.

    CRITICAL: uses an explicit raise, NOT assert. Python -O strips assert statements
    silently, so an assert-based backstop would simply vanish in an optimized deployment
    and let an arithmetically-broken paystub ship. PayrollCalculationError cannot be
    stripped.

    state_withholding is always Decimal("0") / None today, so it is not a parameter —
    the caller reconstructs gross from these six values.
    """
    _state_wh = Decimal("0")  # state withholding is not yet modeled; always None today
    _reconstructed = _money(
        net_pay + pretax_401k + fica_ss + fica_medicare + federal_withholding + _state_wh
    )
    if _reconstructed != gross:
        raise PayrollCalculationError(
            f"Reconciliation failed: reconstructed={_reconstructed} != gross={gross}. "
            "This is an arithmetic bug in calculate(), not a tax-math error. "
            "Check the net_pay, FICA, and federal_withholding formulas."
        )


def calculate(
    resolved_hours: dict[str, object],
    employee: Employee,
    contribution_401k_override: Decimal | None = None,
) -> PaystubLineItem:
    """Compute one employee's full-fidelity paystub (gross + FICA + federal + net).

    resolved_hours: a mapping of the five hours_* fields (None/absent → 0). For a
    salaried employee the regular/overtime hours are ignored — gross is annual_salary /
    pay_periods + any leave pay (vacation/sick/holiday × implied hourly rate).
    contribution_401k_override: a current-run-only 401k rate the CLIENT specified for
    this run. When provided it overrides the employee's stored default for THIS paystub
    only — it must never mutate the stored default, or one run's ad-hoc rate would
    silently persist into every future run.
    """
    hours = _resolved_hours(resolved_hours)

    if employee.pay_type == "hourly":
        rate = employee.hourly_rate or Decimal("0")
        # Overtime at 1.5x; all other hour types at straight time.
        # OT is EXPLICIT-ONLY: hours_regular is paid straight-time even if > 40. Deriving
        # OT here from an implied 40-hour threshold would overpay every employee whose
        # client already reported OT separately (their excess regular hours would be paid
        # twice, once at 1.5x). validate.py flags the over-40-no-OT case instead so a
        # human decides. Leave hours (vacation/sick/holiday) are straight time and are
        # EXCLUDED from any OT threshold.
        straight = (
            hours["hours_regular"]
            + hours["hours_vacation"]
            + hours["hours_sick"]
            + hours["hours_holiday"]
        )
        # Round once, here — the hourly branch's single rounding point (rate * hours is
        # not otherwise quantized). Rounding each term separately would accumulate cents
        # of drift and can break the reconciliation identity.
        gross = _money(rate * straight + rate * Decimal("1.5") * hours["hours_overtime"])
    else:  # salary
        annual = employee.annual_salary or Decimal("0")
        p = Decimal(employee.pay_periods_per_year)
        period_salary = _money(annual / p)
        # Salaried leave pay uses the implied-hourly form, which is frequency-independent:
        #   implied_hourly = annual_salary / 2080   (2080 = 40h/wk * 52 wk/yr)
        #   leave_pay      = implied_hourly * leave_hours
        # It yields the identical amount for p=52, 26, 24, 12.
        # Do NOT rewrite this as period_salary * leave_h / standard_h_per_period with
        # standard_h = 40 * p / 52 — that form is frequency-dependent and OVERPAYS
        # non-weekly schedules badly (semi-monthly p=24 → ~4.7x too high; monthly p=12 →
        # ~18.8x too high). A single vacation day would balloon the paystub.
        _ANNUAL_WORK_HOURS = Decimal("2080")  # 40h/wk * 52 wk — standard work-year hours
        # _resolved_hours() always returns all five keys, so direct subscripts are safe
        # (matches the hourly branch above).
        leave_hours = (
            hours["hours_vacation"]
            + hours["hours_sick"]
            + hours["hours_holiday"]
        )
        leave_pay = _money((annual / _ANNUAL_WORK_HOURS) * leave_hours)
        # The salaried branch's single rounding point — each branch rounds exactly once.
        gross = _money(period_salary + leave_pay)

    # Pre-tax 401k: the client's current-run override if supplied, else the employee's
    # stored default rate — applied to gross. The override must be honored here; parsing
    # it and then falling through to the stored default would deduct the wrong amount.
    rate_401k = (
        contribution_401k_override
        if contribution_401k_override is not None
        else employee.retirement_contribution_pct
    )
    pretax_401k = _money(gross * rate_401k)

    # FICA — Social Security honors the remaining wage-base cap; Medicare has no cap.
    # CRITICAL: the FICA base is GROSS. 401k does NOT reduce it — only the federal taxable
    # base (below) is reduced by pretax_401k. Subtracting pretax_401k here would
    # under-withhold SS and Medicare for every contributing employee.
    remaining_cap = _SS_WAGE_BASE - employee.ytd_ss_wages
    if remaining_cap < 0:
        remaining_cap = Decimal("0")
    ss_taxable = min(gross, remaining_cap)
    fica_ss = _money(ss_taxable * _SS_RATE)
    fica_medicare = _money(gross * _MEDICARE_RATE)

    # Real IRS Pub 15-T 2026 federal withholding. 401k DOES reduce the federal taxable
    # base (and only this base — see the FICA note above).
    federal_taxable = _money(gross - pretax_401k)
    federal_withholding = federal_withholding_2026(federal_taxable, employee)
    net_pay = _money(gross - pretax_401k - fica_ss - fica_medicare - federal_withholding)

    # The Additional Medicare 0.9% surtax on high wages is NOT modeled. This flag only
    # DISCLAIMS that gap on the paystub — it withholds nothing. Silently omitting the
    # disclaimer would let a high earner receive a paystub that looks complete but under-
    # withholds; the flag makes the limitation visible instead.
    #
    # Threshold is filing-status specific per the IRS: $200k single / $250k MFJ / $125k MFS.
    #
    # ytd_ss_wages is used as a PROXY for YTD Medicare wages. It is a documented LOWER
    # BOUND: Medicare has no wage cap, so Medicare YTD >= SS YTD always. Adding current
    # gross gives a conservative Medicare-wage estimate that can cross the threshold.
    # Limitation: if an employee's true Medicare YTD already exceeds their capped SS YTD
    # (i.e. they earned above $184,500 in prior periods), the proxy UNDER-FLAGS. Accepted:
    # there is no per-employee YTD Medicare ledger in the seed model.
    # Note ytd_ss_wages can never legitimately exceed the $184,500 SS wage base, so tests
    # must use realistic values (ytd_ss_wages <= 184500).
    additional_medicare_not_modeled = (
        employee.ytd_ss_wages + gross
    ) > _ADDITIONAL_MEDICARE_THRESHOLDS[employee.filing_status]

    # Arithmetic backstop: no paystub leaves this function without tying out. The helper
    # is a pure function that raises PayrollCalculationError on drift; it is a named
    # helper (not inline) so both paths — ties-out and drift-raises — can be unit-tested
    # directly via pytest.raises without monkeypatching.
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
