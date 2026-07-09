"""2026 Federal Tax Constants for Payroll Engine.

Sources:
  IRS Publication 15-T (2026): https://www.irs.gov/pub/irs-pdf/p15t.pdf
  SSA Contribution and Benefit Base: https://www.ssa.gov/oact/cola/cbb.html
Retrieved: 2026-06-22

OBBBA note: The 2026 edition of Pub 15-T incorporates P.L. 119-21 (OBBBA) changes
(permanent extension of individual tax rates, increased standard deduction, no personal
exemptions). ONLY the standard percentage method is implemented here; the OBBBA
qualified-tips and qualified-overtime deductions are disclaimed and NOT modeled.

Year-keying: this module IS the 2026 data. A future 2027 update would live in
tax_tables_2027.py — adding 2027 constants never requires editing this file.
"""
from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple

TAX_YEAR: int = 2026


class BracketRow(NamedTuple):
    """One row from the IRS Pub 15-T Worksheet 1A percentage-method table.

    Fields correspond to the PDF table columns:
      lower  — column A: "at least" (annual adjusted wage)
      upper  — column B: "but less than"; None for the top bracket (no upper bound)
      base   — column C: tentative withholding base amount (annual)
      rate   — column D: marginal rate as a FRACTION (e.g. Decimal("0.12") for 12%)
                         NOT as a percentage integer (12).
    """

    lower: Decimal
    upper: Decimal | None
    base: Decimal
    rate: Decimal


# ---------------------------------------------------------------------------
# 1A.1 STANDARD Withholding Rate Schedules (Step 2 checkbox NOT checked)
# Source: IRS Pub 15-T (2026) page 12 — Percentage Method Tables for Automated
# Payroll Systems. Transcribed verbatim from irs.gov/pub/irs-pdf/p15t.pdf,
# retrieved 2026-06-22.
# ---------------------------------------------------------------------------

_MFJ_STANDARD: list[BracketRow] = [
    # At Least    But Less Than  Base        Rate    (Excess Over == At Least)
    BracketRow(Decimal("0"),       Decimal("19300"),  Decimal("0.00"),      Decimal("0.00")),
    BracketRow(Decimal("19300"),   Decimal("44100"),  Decimal("0.00"),      Decimal("0.10")),
    BracketRow(Decimal("44100"),   Decimal("120100"), Decimal("2480.00"),   Decimal("0.12")),
    BracketRow(Decimal("120100"),  Decimal("230700"), Decimal("11600.00"),  Decimal("0.22")),
    BracketRow(Decimal("230700"),  Decimal("422850"), Decimal("35932.00"),  Decimal("0.24")),
    BracketRow(Decimal("422850"),  Decimal("531750"), Decimal("82048.00"),  Decimal("0.32")),
    BracketRow(Decimal("531750"),  Decimal("788000"), Decimal("116896.00"), Decimal("0.35")),
    BracketRow(Decimal("788000"),  None,              Decimal("206583.50"), Decimal("0.37")),
]

_SINGLE_STANDARD: list[BracketRow] = [
    # At Least    But Less Than  Base        Rate    (Excess Over == At Least)
    BracketRow(Decimal("0"),       Decimal("7500"),   Decimal("0.00"),      Decimal("0.00")),
    BracketRow(Decimal("7500"),    Decimal("19900"),  Decimal("0.00"),      Decimal("0.10")),
    BracketRow(Decimal("19900"),   Decimal("57900"),  Decimal("1240.00"),   Decimal("0.12")),
    BracketRow(Decimal("57900"),   Decimal("113200"), Decimal("5800.00"),   Decimal("0.22")),
    BracketRow(Decimal("113200"),  Decimal("209275"), Decimal("17966.00"),  Decimal("0.24")),
    BracketRow(Decimal("209275"),  Decimal("263725"), Decimal("41024.00"),  Decimal("0.32")),
    BracketRow(Decimal("263725"),  Decimal("648100"), Decimal("58448.00"),  Decimal("0.35")),
    BracketRow(Decimal("648100"),  None,              Decimal("192979.25"), Decimal("0.37")),
]

_HOH_STANDARD: list[BracketRow] = [
    # Head of Household — out of scope (no seeded HoH employees). Listed for completeness.
    # IN-01 (review round 2): UNTESTED — these rows are never reached (filing_status Literal
    # excludes HoH; federal_withholding_2026 raises ValueError before any HoH lookup) and are
    # NOT cross-checked against IRS golden/wage-bracket values. Independently verify against
    # the live PDF before enabling any HoH withholding path.
    BracketRow(Decimal("0"),       Decimal("15550"),  Decimal("0.00"),      Decimal("0.00")),
    BracketRow(Decimal("15550"),   Decimal("33250"),  Decimal("0.00"),      Decimal("0.10")),
    BracketRow(Decimal("33250"),   Decimal("83000"),  Decimal("1770.00"),   Decimal("0.12")),
    BracketRow(Decimal("83000"),   Decimal("121250"), Decimal("7740.00"),   Decimal("0.22")),
    BracketRow(Decimal("121250"),  Decimal("217300"), Decimal("16155.00"),  Decimal("0.24")),
    BracketRow(Decimal("217300"),  Decimal("271750"), Decimal("39207.00"),  Decimal("0.32")),
    BracketRow(Decimal("271750"),  Decimal("656150"), Decimal("56631.00"),  Decimal("0.35")),
    BracketRow(Decimal("656150"),  None,              Decimal("191171.00"), Decimal("0.37")),
]

STANDARD_BRACKETS: dict[str, list[BracketRow]] = {
    "married_jointly": _MFJ_STANDARD,
    "single": _SINGLE_STANDARD,
    # Per IRS Pub 15-T, "Single or Married Filing Separately" share ONE table.
    # married_separately aliases the single list — same object, not a copy.
    # (Pitfall #4: using the MFJ table for MFS would halve withholding.)
    "married_separately": _SINGLE_STANDARD,
    # out of scope — no seeded HoH employees; the engine rejects "head_of_household"
    "head_of_household": _HOH_STANDARD,
}

# ---------------------------------------------------------------------------
# 1A.2 Step 2 Checkbox Withholding Rate Schedules (Step 2 checkbox IS checked)
# Source: IRS Pub 15-T (2026) page 12.
# IMPORTANT: These rows are transcribed VERBATIM from the printed Step-2-checkbox
# schedule. They are NOT arithmetically derived by halving the standard schedule.
# The IRS rounds each row independently when printing, so halving standard rows
# produces incorrect values for some rows (review Fix 7a).
# ---------------------------------------------------------------------------

_MFJ_STEP2: list[BracketRow] = [
    # At Least    But Less Than  Base        Rate
    BracketRow(Decimal("0"),       Decimal("16100"),  Decimal("0.00"),      Decimal("0.00")),
    BracketRow(Decimal("16100"),   Decimal("28500"),  Decimal("0.00"),      Decimal("0.10")),
    BracketRow(Decimal("28500"),   Decimal("66500"),  Decimal("1240.00"),   Decimal("0.12")),
    BracketRow(Decimal("66500"),   Decimal("121800"), Decimal("5800.00"),   Decimal("0.22")),
    BracketRow(Decimal("121800"),  Decimal("217875"), Decimal("17966.00"),  Decimal("0.24")),
    BracketRow(Decimal("217875"),  Decimal("272325"), Decimal("41024.00"),  Decimal("0.32")),
    BracketRow(Decimal("272325"),  Decimal("400450"), Decimal("58448.00"),  Decimal("0.35")),
    BracketRow(Decimal("400450"),  None,              Decimal("103291.75"), Decimal("0.37")),
]

_SINGLE_STEP2: list[BracketRow] = [
    # At Least    But Less Than  Base        Rate
    BracketRow(Decimal("0"),       Decimal("8050"),   Decimal("0.00"),      Decimal("0.00")),
    BracketRow(Decimal("8050"),    Decimal("14250"),  Decimal("0.00"),      Decimal("0.10")),
    BracketRow(Decimal("14250"),   Decimal("33250"),  Decimal("620.00"),    Decimal("0.12")),
    BracketRow(Decimal("33250"),   Decimal("60900"),  Decimal("2900.00"),   Decimal("0.22")),
    BracketRow(Decimal("60900"),   Decimal("108938"), Decimal("8983.00"),   Decimal("0.24")),
    BracketRow(Decimal("108938"),  Decimal("136163"), Decimal("20512.00"),  Decimal("0.32")),
    BracketRow(Decimal("136163"),  Decimal("328350"), Decimal("29224.00"),  Decimal("0.35")),
    BracketRow(Decimal("328350"),  None,              Decimal("96489.63"),  Decimal("0.37")),
]

_HOH_STEP2: list[BracketRow] = [
    # Head of Household Step-2 — out of scope. Listed for completeness.
    # IN-01 (review round 2): UNTESTED — unreachable (HoH rejected before lookup) and not
    # cross-checked against IRS golden values. Verify against the live PDF before enabling.
    BracketRow(Decimal("0"),       Decimal("12075"),  Decimal("0.00"),      Decimal("0.00")),
    BracketRow(Decimal("12075"),   Decimal("20925"),  Decimal("0.00"),      Decimal("0.10")),
    BracketRow(Decimal("20925"),   Decimal("45800"),  Decimal("885.00"),    Decimal("0.12")),
    BracketRow(Decimal("45800"),   Decimal("64925"),  Decimal("3870.00"),   Decimal("0.22")),
    BracketRow(Decimal("64925"),   Decimal("112950"), Decimal("8077.50"),   Decimal("0.24")),
    BracketRow(Decimal("112950"),  Decimal("140175"), Decimal("19603.50"),  Decimal("0.32")),
    BracketRow(Decimal("140175"),  Decimal("332375"), Decimal("28315.50"),  Decimal("0.35")),
    BracketRow(Decimal("332375"),  None,              Decimal("95585.50"),  Decimal("0.37")),
]

STEP2_BRACKETS: dict[str, list[BracketRow]] = {
    "married_jointly": _MFJ_STEP2,
    "single": _SINGLE_STEP2,
    # Same aliasing as STANDARD_BRACKETS — MFS uses the Single/MFS table.
    "married_separately": _SINGLE_STEP2,
    # out of scope — no seeded HoH employees
    "head_of_household": _HOH_STEP2,
}

# ---------------------------------------------------------------------------
# 1A.3 Step 1 Standard Amounts (Worksheet 1A, Line 1g)
# Source: IRS Pub 15-T (2026) page 10, retrieved 2026-06-22.
# Verbatim from PDF: "If the box in Step 2 of Form W-4 is checked, enter -0-.
#   If the box is not checked, enter $12,900 if the taxpayer is married filing
#   jointly or $8,600 otherwise."
#
# IMPORTANT — These are the Worksheet 1A WITHHOLDING-PROXY amounts as written
# on Pub 15-T page 10, line 1g. They are deliberately NOT the 2026 standard-
# deduction figures ($32,200 MFJ / $16,100 Single). The line-1g amounts are the
# pre-TCJA proxy baked into the withholding tables. Replacing these with the 2026
# standard deductions would over-deduct the annualized wage and systematically
# under-withhold every employee. (See RESEARCH.md Deliverable 5, Finding 7 /
# Pitfall 2.)
# ---------------------------------------------------------------------------

STEP1_STANDARD: dict[str, Decimal] = {
    "married_jointly": Decimal("12900"),      # $12,900 — line 1g proxy, NOT $32,200 std deduction
    "single": Decimal("8600"),                # $8,600  — line 1g proxy, NOT $16,100 std deduction
    "married_separately": Decimal("8600"),    # same as single per PDF ("$8,600 otherwise")
    "head_of_household": Decimal("8600"),     # same as single per PDF ("$8,600 otherwise")
}

# ---------------------------------------------------------------------------
# FICA Constants (2026)
# Source: SSA Contribution and Benefit Base — https://www.ssa.gov/oact/cola/cbb.html
#         IRS Topic 751 — https://www.irs.gov/taxtopics/tc751
# (cbb.html returns 403 to non-browser fetch — cited here for audit, NOT scraped at runtime)
# Migrated from calculate.py per Decision D-02 (one year-keyed module holds all constants).
# ---------------------------------------------------------------------------

SS_RATE: Decimal = Decimal("0.062")          # Social Security employee rate: 6.2%
SS_WAGE_BASE: Decimal = Decimal("184500")    # 2026 SS wage base ($184,500; up from $176,100)
MEDICARE_RATE: Decimal = Decimal("0.0145")   # Medicare employee rate: 1.45% (no wage cap)
# Note: Additional Medicare 0.9% surtax over $200,000 is NOT modeled (out of scope for demo wages).
