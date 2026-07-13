"""IRS Pub 15-T 2026 Worksheet 1A federal withholding engine.

A PURE function: typed values in, Decimal out.  NO DB, NO network, NO side effects.
The eval harness imports it directly, so it must stay free of I/O dependencies.

Rounding convention: carry full cents via _money() (ROUND_HALF_UP) at each intermediate
step; never round to whole dollars mid-calculation.  The final per-period withholding is
in cents.  This is IRS-compliant (cents are legal; whole-dollar rounding is optional per
Pub 15-T page 9) and avoids introducing a rounding boundary that cross-check calculators
may or may not match — the golden tests are pinned to this convention.

Source: https://www.irs.gov/pub/irs-pdf/p15t.pdf (2026 edition, Worksheet 1A, page 10)
Transcription date: 2026-06-22
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.models.roster import Employee
from app.pipeline.tax_tables_2026 import (
    STANDARD_BRACKETS,
    STEP1_STANDARD,
    STEP2_BRACKETS,
    TAX_YEAR,  # noqa: F401 — imported for module-level traceability
    BracketRow,
)

# Local copy of _money() — deliberately NOT imported from calculate.py, so this module
# stays independently importable by the eval without pulling in calculate.py's uuid /
# datetime / model imports. Both copies MUST use the same rounding mode; if they ever
# diverge, withholding and net pay would round differently and reconciliation would drift.
_CENTS = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    """Round a Decimal to cents using ROUND_HALF_UP (round half AWAY from zero).

    This is standard payroll rounding, NOT banker's rounding. Banker's rounding is
    ROUND_HALF_EVEN (round half to the nearest even cent); ROUND_HALF_UP always rounds a
    halfway value up in magnitude. Every calc/FICA golden test is pinned to ROUND_HALF_UP,
    and it must match calculate._money() exactly — switching modes here would shift
    withheld cents and break the reconciliation identity.
    """
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _find_bracket(annual_wage: Decimal, brackets: list[BracketRow]) -> BracketRow:
    """Find the matching Pub 15-T bracket row via linear scan (O(n), 8 rows max).

    Returns the first row (scanning in reverse) where annual_wage >= row.lower.
    Falls back to brackets[0] for wages below the first row's lower bound (the
    zero bracket catches sub-threshold wages, since lower=0 for all first rows).
    """
    for row in reversed(brackets):
        if annual_wage >= row.lower:
            return row
    # Unreachable for all shipped tables: every first row has lower == 0 and line_1i floors
    # at 0, so annual_wage >= brackets[0].lower always matches on the reverse scan. The
    # first-bracket-lower-is-zero tests pin that invariant. If a future table set a non-zero
    # first lower, this fallback would silently return the zero-rate row for sub-threshold
    # wages (withholding $0 from someone who owes tax) — keep the first row at lower == 0.
    return brackets[0]


# ---------------------------------------------------------------------------
# Defense-in-depth filing-status guard.
#
# Employee.filing_status is already constrained by Literal["single", "married_jointly",
# "married_separately"] — "head_of_household" is NOT a valid Literal value today. This
# guard exists for any future extension, eval fixture, or caller that constructs an
# Employee against a widened Literal: it turns a silent mis-withholding (a wrong or
# missing table lookup) into an immediate, loud ValueError.
# ---------------------------------------------------------------------------
_SUPPORTED_FILING_STATUSES = frozenset({"single", "married_jointly", "married_separately"})


def federal_withholding_2026(
    federal_taxable_wages_this_period: Decimal,
    employee: Employee,
) -> Decimal:
    """Compute per-period federal income tax withholding via Pub 15-T 2026 Worksheet 1A.

    federal_taxable_wages_this_period:
        Gross pay MINUS pre-tax 401k for this period (NOT raw gross).
        The caller (calculate.py) computes: federal_taxable = gross - pretax_401k.

    Returns:
        Per-period withholding as a Decimal rounded to cents (ROUND_HALF_UP).
        NEVER returns a negative Decimal — line_1i and line_3c both floor at $0.

    Supported filing statuses:
        "single", "married_jointly", "married_separately".
        "head_of_household" and any other value raises ValueError (defense-in-depth
        guard — see _SUPPORTED_FILING_STATUSES above).

    Rounding:
        _money() (ROUND_HALF_UP to cents) applied at each intermediate step.
        No whole-dollar rounding mid-calculation.

    Source: IRS Pub 15-T (2026) Worksheet 1A, page 10.
            https://www.irs.gov/pub/irs-pdf/p15t.pdf, retrieved 2026-06-22.
    """
    # ------------------------------------------------------------------
    # Guard: reject unsupported filing statuses immediately rather than
    # falling through to a wrong table.
    # ------------------------------------------------------------------
    if employee.filing_status not in _SUPPORTED_FILING_STATUSES:
        raise ValueError(
            f"Unsupported filing_status {employee.filing_status!r}. "
            "Only 'single', 'married_jointly', and 'married_separately' are supported. "
            "'head_of_household' withholding tables are transcribed in tax_tables_2026.py "
            "but the engine does not map them (no seeded HoH employees). "
            "Add HoH table mapping before enabling this path."
        )

    p = Decimal(employee.pay_periods_per_year)
    status = employee.filing_status
    checkbox = employee.step_2_checkbox

    # ------------------------------------------------------------------
    # Step 1 — Adjust the employee's payment amount (annualize wages)
    # Source: Pub 15-T page 10, Worksheet 1A Step 1.
    # ------------------------------------------------------------------
    line_1a = federal_taxable_wages_this_period  # taxable wages this period
    line_1c = _money(line_1a * p)                # annualize (× pay periods)
    line_1d = employee.step_4a_other_income      # W-4 Step 4a: other annual income
    line_1e = _money(line_1c + line_1d)
    line_1f = employee.step_4b_deductions        # W-4 Step 4b: additional deductions
    # line_1g: $12,900 (MFJ) or $8,600 (Single/MFS/HoH) if step_2 NOT checked; else $0.
    # These are the Worksheet 1A withholding-proxy amounts (NOT the 2026 standard deduction).
    line_1g = Decimal("0") if checkbox else STEP1_STANDARD[status]
    line_1h = _money(line_1f + line_1g)
    # Adjusted Annual Wage Amount — floors at $0 per PDF ("if zero or less, enter -0-")
    line_1i = max(Decimal("0"), _money(line_1e - line_1h))

    # ------------------------------------------------------------------
    # Step 2 — Figure the Tentative Withholding Amount (bracket lookup)
    # ------------------------------------------------------------------
    brackets = STEP2_BRACKETS[status] if checkbox else STANDARD_BRACKETS[status]
    row = _find_bracket(line_1i, brackets)
    line_2e = _money(line_1i - row.lower)         # excess over bracket lower bound
    line_2f = _money(line_2e * row.rate)           # marginal tax on the excess
    line_2g = _money(row.base + line_2f)           # annual tentative withholding
    line_2h = _money(line_2g / p)                  # per-period tentative withholding

    # ------------------------------------------------------------------
    # Step 3 — Account for tax credits (W-4 Step 3), floor at $0
    # Per PDF: "if zero or less, enter -0-" (line 3c)
    # ------------------------------------------------------------------
    line_3b = _money(employee.step_3_dependents / p)  # per-period credit amount
    line_3c = max(Decimal("0"), _money(line_2h - line_3b))

    # ------------------------------------------------------------------
    # Step 4 — Figure the final amount to withhold
    # W-4 Step 4c (extra per-period withholding) is NOT modeled: Employee has no such
    # field and no seeded employee requests extra withholding. To support it, add
    # employee.step_4c_extra_per_period and use the line below — omitting it once the
    # field exists would silently under-withhold anyone who asked for extra.
    # line_4b = _money(line_3c + employee.step_4c_extra_per_period)
    # ------------------------------------------------------------------
    line_4b = line_3c  # step_4c = $0 for all seeded employees

    return line_4b
