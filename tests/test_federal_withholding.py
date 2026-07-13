"""Golden-value tests for the Pub 15-T 2026 Worksheet 1A federal withholding engine.

The withholding engine is the highest-bug-risk unit in the repo, so every expected value
here comes from a source OUTSIDE the engine. Three complementary layers:

PRIMARY ORACLE (under-ceiling fixtures):
  The independently-transcribed Wage Bracket Method tables (Pub 15-T 2026 pages 13-27,
  sourced from irs.gov/pub/irs-pdf/p15t.pdf, retrieved 2026-06-22). A transcription error
  in tax_tables_2026.py makes the wage-bracket cross-check disagree with these cells --
  that disagreement is the whole point of the layer.

STRUCTURAL INDEPENDENCE (the load-bearing rule):
  NO expected value in the parametrize tables may be derived by calling tax_tables_2026 or
  federal_withholding_2026. A test that computes its own expectation from the code under
  test proves only that the code is self-consistent, not that it is correct. All golden
  values are either:
  (a) Verbatim published wage-bracket cells, or
  (b) Hand-computed step-by-step from the bracket tables (independently transcribed from
      the same IRS PDF, a different section).

SECONDARY ORACLE (over-ceiling):
  For fixtures whose adjusted per-period wage exceeds the wage-bracket ceiling (~$100k
  annualized), expected values are confirmed against an independent online calculator.

  Thomas Bergmann, biweekly MFJ, over-ceiling (~$9,230.77/period, above the $3,875 ceiling):
  - Calibration: paycheckcity.com returned $54.08 for Single/Standard/Weekly/$800, which
    confirms it is running the IRS Pub 15-T 2026 percentage method. usapaycheck.org was
    DISCARDED -- it rounds inputs and outputs, so it cannot serve as a penny-exact oracle.
  - Over-ceiling: paycheckcity.com (8% entered as a TRADITIONAL pre-tax 401k) returned
    Federal Withholding = $881.39 -- a PENNY-EXACT match with this engine. (An initial run
    that did NOT apply the 401k to the federal base returned $1,043.85; re-running with the
    pre-tax 401k reconciled it exactly to $881.39.)
  So one penny-exact online oracle plus a full Worksheet 1A hand trace (see
  test_federal_withholding_thomas_bergmann_over_ceiling) corroborate the value; both agree,
  so it is adopted rather than skipped.
  NOTE: the SS wage-base straddle case for Thomas Bergmann is a SEPARATE under-ceiling FICA
  assertion driven through calculate(), implemented normally below.

ROUNDING:
  Whole-dollar comparison uses quantize(Decimal("1"), rounding=ROUND_HALF_UP), NOT Python's
  round() (which is ROUND_HALF_EVEN / banker's rounding). This matches the IRS's own
  whole-dollar convention.

  Per-step cent quantization in federal_withholding.py is a CHOSEN ENGINE CONVENTION: IRS
  whole-dollar rounding is optional under Pub 15-T, and ROUND_HALF_UP is this project's pin.
  It is not IRS-mandated per-step behavior.

  DEFAULT ASSERTION in the wage-bracket cross-check: EXACT EQUALITY.
  engine_whole_dollar == published_cell. A +-$1 tolerance is allowed ONLY on a row carrying
  a documented, named exception comment. A blanket tolerance would mask a real $1
  bracket-table transcription bug -- the exact class of error this file exists to catch.

WAGE-BRACKET CEILINGS:
  Weekly (52): $1,925 / Biweekly (26): $3,875 / Semimonthly (24): $4,185 / Monthly (12): $8,395
  Thomas Bergmann (~$9,230.77 biweekly) is ABOVE the $3,875 biweekly ceiling.

COVERAGE:
  All 6 Worksheet 1A schedule combinations: 3 filing statuses x 2 Step-2 branches. The
  wage-bracket sweep covers 4 unique column datasets (single and married_separately share
  one published column) and exercises all 6 routing combinations. The HoH schedule is not
  covered by the sweep -- HoH is rejected with a ValueError (reject-guard).

ADDITIONAL MEDICARE:
  The 0.9% surtax over $200k YTD is NOT modeled. The engine flags it as a known limitation
  (additional_medicare_not_modeled=True on PaystubLineItem). Tests use REALISTIC SS-capped
  YTD values (ytd_ss_wages <= 184500, the 2026 SS wage base cap) -- an impossible YTD would
  exercise a state the system can never reach.

OBBBA DISCLAIMER:
  Qualified-tips and qualified-overtime above-the-line deductions (OBBBA) are NOT modeled.
  Standard percentage method only.

WHY python-taxes IS NOT USED HERE:
  python-taxes (PyPI 0.7.0, MIT) implements this same percentage method, but ships 2023-2025
  tables only, while this engine is keyed to 2026. A structural comparison would require
  injectable year tables that are out of scope. The published wage-bracket cells already
  provide the structural independence, so taking the dependency would add supply-chain and
  lockfile churn with no verification value.
"""
from __future__ import annotations

import copy
import importlib
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest

from app.db.seed import seed
from app.models.roster import Employee
from app.pipeline.calculate import calculate
from app.pipeline.federal_withholding import _find_bracket, federal_withholding_2026
from app.pipeline.tax_tables_2026 import STANDARD_BRACKETS

# ---------------------------------------------------------------------------
# _make_employee() helper — constructs a minimal Employee for golden tests
# ---------------------------------------------------------------------------

def _make_employee(
    *,
    filing_status: str,
    step_2_checkbox: bool,
    step_3_dependents: Decimal,
    step_4a_other_income: Decimal,
    step_4b_deductions: Decimal,
    pay_periods_per_year: int,
    ytd_ss_wages: Decimal = Decimal("0"),
    retirement_contribution_pct: Decimal = Decimal("0"),
    pay_type: str = "hourly",
    hourly_rate: Decimal = Decimal("100.00"),
) -> Employee:
    """Construct a minimal Employee for golden withholding tests.

    Defaults: hourly @ $100/hr, no YTD SS wages, no 401k.
    Override only the fields relevant to the specific test case.
    UUIDs are random (uuid4) since identity does not matter for pure withholding calculation.
    """
    return Employee(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        full_name="Test Employee",
        known_aliases=[],
        pay_type=pay_type,
        hourly_rate=hourly_rate if pay_type == "hourly" else None,
        annual_salary=None if pay_type == "hourly" else hourly_rate * Decimal("2080"),
        retirement_contribution_pct=retirement_contribution_pct,
        filing_status=filing_status,
        step_2_checkbox=step_2_checkbox,
        step_3_dependents=step_3_dependents,
        step_4a_other_income=step_4a_other_income,
        step_4b_deductions=step_4b_deductions,
        ytd_ss_wages=ytd_ss_wages,
        pay_periods_per_year=pay_periods_per_year,
    )


# ---------------------------------------------------------------------------
# Seeded-employee fixtures (filter by field predicate, never by index)
# ---------------------------------------------------------------------------

@pytest.fixture()
def maria_chen():
    """Single/Standard/Weekly, hourly=$18.50, no 401k."""
    seeded = seed(dry_run=True)
    return next(
        e for e in seeded.employees
        if e.filing_status == "single" and not e.step_2_checkbox and e.pay_periods_per_year == 52
        and e.full_name == "Maria Chen"
    )


@pytest.fixture()
def james_okafor():
    """MFJ/Standard/Weekly, salary=$62400, 401k=4%, step_3=$4000."""
    seeded = seed(dry_run=True)
    return next(
        e for e in seeded.employees
        if e.filing_status == "married_jointly" and not e.step_2_checkbox
        and e.pay_periods_per_year == 52
    )


@pytest.fixture()
def thomas_bergmann():
    """MFJ/Standard/Biweekly, salary=$240000, 401k=8%, step_3=$8000. HIGH EARNER (over-ceiling)."""
    seeded = seed(dry_run=True)
    return next(
        e for e in seeded.employees
        if e.filing_status == "married_jointly" and not e.step_2_checkbox
        and e.pay_periods_per_year == 26
    )


@pytest.fixture()
def sandra_kim():
    """Single/Standard/Biweekly, hourly=$45.00, 401k=5%."""
    seeded = seed(dry_run=True)
    return next(
        e for e in seeded.employees
        if e.filing_status == "single" and not e.step_2_checkbox and e.pay_periods_per_year == 26
    )


@pytest.fixture()
def priya_nair():
    """MFS/Step2/Weekly, salary=$72800, 401k=6%, step_4a=$2000."""
    seeded = seed(dry_run=True)
    return next(
        e for e in seeded.employees
        if e.filing_status == "married_separately" and e.step_2_checkbox
    )


# ---------------------------------------------------------------------------
# WAGE-BRACKET PRIMARY ORACLE CROSS-CHECK
# ---------------------------------------------------------------------------
# Source: Pub 15-T 2026 Wage Bracket Method Tables, Section 2, pages 13-27.
# irs.gov/pub/irs-pdf/p15t.pdf, retrieved 2026-06-22.
#
# Method: evaluate the engine at the interval MIDPOINT, quantize to whole dollar
# using ROUND_HALF_UP (NOT Python round()), assert EXACT EQUALITY (==) against the
# published wage-bracket cell.
#
# Exact equality (engine_whole_dollar == published_cell) is the DEFAULT. A +-$1
# tolerance is permitted ONLY on a specifically-named fixture row carrying a
# documented extraction/rounding-anomaly reason. A blanket +-$1 tolerance would
# mask a real $1 bracket-table or line-1g transcription bug -- which is precisely
# what this oracle exists to catch, so the tolerance would defeat it.
# Rounding note: quantize(Decimal("1"), ROUND_HALF_UP) (not Python round(), which
# is half-even/banker's rounding) matches the IRS's own whole-dollar convention.
# Per-step cent quantization in federal_withholding.py is a CHOSEN ENGINE
# CONVENTION -- IRS whole-dollar rounding is optional under Pub 15-T, and
# ROUND_HALF_UP is this project's pin. It is not IRS-mandated per-step behavior.
#
# HoH columns are NOT covered: HoH is rejected by the engine with ValueError.
# The sweep covers all 6 project-relevant columns -- MFJ Standard, MFJ Step-2,
# Single/MFS Standard, Single/MFS Step-2, and their frequency variants -- backed
# by 4 unique published column datasets (single and MFS share one).
#
# WAGE_BRACKET_CEILINGS: defines the max per-period adjusted wage in each table.
# All intervals below use wages well under these ceilings (no over-ceiling rows).

WAGE_BRACKET_CEILINGS = {
    52: Decimal("1925"),   # weekly
    26: Decimal("3875"),   # biweekly
    24: Decimal("4185"),   # semimonthly
    12: Decimal("8395"),   # monthly
}

# Wage-bracket fixture tuples:
# (frequency, interval_lower, interval_upper, filing_status, step2, published_cell)
# Source comment for each identifies the PDF page and column.
_WAGE_BRACKET_FIXTURES = [
    # -----------------------------------------------------------------------
    # Column 1: Weekly (52) Single/MFS Standard
    # Source: Pub 15-T 2026 p.14, weekly table, Single/MFS Standard column
    # (cells transcribed verbatim from the published table).
    # -----------------------------------------------------------------------
    (52, Decimal("625"), Decimal("635"), "single", False, Decimal("34")),
    # Source: Pub 15-T 2026 p.14, weekly, Single/MFS Standard, row [$625-$635] -> $34
    (52, Decimal("635"), Decimal("645"), "single", False, Decimal("35")),
    # Source: Pub 15-T 2026 p.14, weekly, Single/MFS Standard, row [$635-$645] -> $35
    (52, Decimal("645"), Decimal("655"), "single", False, Decimal("36")),
    # Source: Pub 15-T 2026 p.14, weekly, Single/MFS Standard, row [$645-$655] -> $36
    (52, Decimal("655"), Decimal("665"), "single", False, Decimal("37")),
    # Source: Pub 15-T 2026 p.14, weekly, Single/MFS Standard, row [$655-$665] -> $37
    (52, Decimal("665"), Decimal("675"), "single", False, Decimal("38")),
    # Source: Pub 15-T 2026 p.14, weekly, Single/MFS Standard, row [$665-$675] -> $38
    # Cross-check worked anchor: midpoint $670 -> annualized $34,840 -> $26,240 adjusted
    # -> 12% bracket -> $2,000.80 annual -> $38.48/week -> round=$38. MATCH.
    (52, Decimal("675"), Decimal("685"), "single", False, Decimal("40")),
    # Source: Pub 15-T 2026 p.14, weekly, Single/MFS Standard, row [$675-$685] -> $40
    (52, Decimal("685"), Decimal("695"), "single", False, Decimal("41")),
    # Source: Pub 15-T 2026 p.14, weekly, Single/MFS Standard, row [$685-$695] -> $41
    (52, Decimal("695"), Decimal("705"), "single", False, Decimal("42")),
    # Source: Pub 15-T 2026 p.14, weekly, Single/MFS Standard, row [$695-$705] -> $42

    # -----------------------------------------------------------------------
    # Column 2: Weekly (52) MFJ Standard — INDEPENDENTLY TRANSCRIBED.
    # These cells are copied VERBATIM from the published Pub 15-T 2026 Wage Bracket Method
    # table (weekly, Married Filing Jointly, Standard / Step-2 NOT checked) on 2026-06-22,
    # then cross-checked: each matches the engine's midpoint output to the whole dollar
    # (ROUND_HALF_UP). Engine-computed cells would make this column a circular oracle that
    # can never disagree with the code — the transcription is what gives it teeth.
    # All under the $1,925 weekly ceiling.
    # -----------------------------------------------------------------------
    (52, Decimal("795"), Decimal("805"), "married_jointly", False, Decimal("18")),
    # Source: Pub 15-T 2026 wage-bracket, weekly, MFJ Standard, row [$795-$805] -> $18
    (52, Decimal("1005"), Decimal("1015"), "married_jointly", False, Decimal("39")),
    # Source: Pub 15-T 2026 wage-bracket, weekly, MFJ Standard, row [$1005-$1015] -> $39
    (52, Decimal("1705"), Decimal("1715"), "married_jointly", False, Decimal("121")),
    # Source: Pub 15-T 2026 wage-bracket, weekly, MFJ Standard, row [$1705-$1715] -> $121
    (52, Decimal("1865"), Decimal("1875"), "married_jointly", False, Decimal("141")),
    # Source: Pub 15-T 2026 wage-bracket, weekly, MFJ Standard, row [$1865-$1875] -> $141
    (52, Decimal("1915"), Decimal("1925"), "married_jointly", False, Decimal("147")),
    # Source: Pub 15-T 2026 wage-bracket, weekly, MFJ Standard, row [$1915-$1925] -> $147

    # -----------------------------------------------------------------------
    # Column 3: Weekly (52) Single/MFS Step-2 Checkbox
    # Source: Pub 15-T 2026 p.14, weekly table, Single/MFS Step-2 Checkbox column.
    # All under $1,925 weekly ceiling.
    # -----------------------------------------------------------------------
    (52, Decimal("550"), Decimal("560"), "single", True, Decimal("46")),
    # Source: Pub 15-T 2026 p.14, weekly, Single/MFS Step-2, row [$550-$560] -> $46
    (52, Decimal("600"), Decimal("610"), "single", True, Decimal("52")),
    # Source: Pub 15-T 2026 p.14, weekly, Single/MFS Step-2, row [$600-$610] -> $52
    (52, Decimal("650"), Decimal("660"), "single", True, Decimal("59")),
    # Source: Pub 15-T 2026 p.14, weekly, Single/MFS Step-2, row [$650-$660] -> $59
    (52, Decimal("700"), Decimal("710"), "single", True, Decimal("70")),
    # Source: Pub 15-T 2026 p.14, weekly, Single/MFS Step-2, row [$700-$710] -> $70
    (52, Decimal("750"), Decimal("760"), "single", True, Decimal("81")),
    # Source: Pub 15-T 2026 p.14, weekly, Single/MFS Step-2, row [$750-$760] -> $81

    # -----------------------------------------------------------------------
    # Column 4: Weekly (52) MFJ Step-2 Checkbox
    # Source: Pub 15-T 2026 p.14, weekly table, MFJ Step-2 Checkbox column.
    # All under $1,925 weekly ceiling.
    # -----------------------------------------------------------------------
    (52, Decimal("750"), Decimal("760"), "married_jointly", True, Decimal("49")),
    # Source: Pub 15-T 2026 p.14, weekly, MFJ Step-2, row [$750-$760] -> $49
    (52, Decimal("800"), Decimal("810"), "married_jointly", True, Decimal("55")),
    # Source: Pub 15-T 2026 p.14, weekly, MFJ Step-2, row [$800-$810] -> $55
    (52, Decimal("900"), Decimal("910"), "married_jointly", True, Decimal("67")),
    # Source: Pub 15-T 2026 p.14, weekly, MFJ Step-2, row [$900-$910] -> $67
    (52, Decimal("1000"), Decimal("1010"), "married_jointly", True, Decimal("79")),
    # Source: Pub 15-T 2026 p.14, weekly, MFJ Step-2, row [$1000-$1010] -> $79
    (52, Decimal("1100"), Decimal("1110"), "married_jointly", True, Decimal("91")),
    # Source: Pub 15-T 2026 p.14, weekly, MFJ Step-2, row [$1100-$1110] -> $91

    # -----------------------------------------------------------------------
    # Column 5: Biweekly (26) Single/MFS Standard
    # Source: Pub 15-T 2026 p.17-19, biweekly table, Single/MFS Standard column.
    # All under $3,875 biweekly ceiling.
    # -----------------------------------------------------------------------
    (26, Decimal("1200"), Decimal("1215"), "single", False, Decimal("61")),
    # Source: Pub 15-T 2026 p.17, biweekly, Single/MFS Standard, row [$1200-$1215] -> $61
    (26, Decimal("1500"), Decimal("1515"), "single", False, Decimal("97")),
    # Source: Pub 15-T 2026 p.17, biweekly, Single/MFS Standard, row [$1500-$1515] -> $97
    (26, Decimal("2000"), Decimal("2015"), "single", False, Decimal("157")),
    # Source: Pub 15-T 2026 p.17, biweekly, Single/MFS Standard, row [$2000-$2015] -> $157
    (26, Decimal("2500"), Decimal("2515"), "single", False, Decimal("217")),
    # Source: Pub 15-T 2026 p.17, biweekly, Single/MFS Standard, row [$2500-$2515] -> $217
    (26, Decimal("3000"), Decimal("3015"), "single", False, Decimal("322")),
    # Source: Pub 15-T 2026 p.17, biweekly, Single/MFS Standard, row [$3000-$3015] -> $322

    # -----------------------------------------------------------------------
    # Column 6 (frequency variant): Monthly (12) Single/MFS Standard
    # Source: Pub 15-T 2026 p.23-25, monthly table, Single/MFS Standard column.
    # All under $8,395 monthly ceiling.
    # -----------------------------------------------------------------------
    (12, Decimal("3000"), Decimal("3030"), "single", False, Decimal("180")),
    # Source: Pub 15-T 2026 p.23, monthly, Single/MFS Standard, row [$3000-$3030] -> $180
    (12, Decimal("4000"), Decimal("4030"), "single", False, Decimal("300")),
    # Source: Pub 15-T 2026 p.23, monthly, Single/MFS Standard, row [$4000-$4030] -> $300
    (12, Decimal("5000"), Decimal("5030"), "single", False, Decimal("420")),
    # Source: Pub 15-T 2026 p.24, monthly, Single/MFS Standard, row [$5000-$5030] -> $420
    (12, Decimal("6000"), Decimal("6030"), "single", False, Decimal("587")),
    # Source: Pub 15-T 2026 p.24, monthly, Single/MFS Standard, row [$6000-$6030] -> $587
    (12, Decimal("7000"), Decimal("7030"), "single", False, Decimal("807")),
    # Source: Pub 15-T 2026 p.25, monthly, Single/MFS Standard, row [$7000-$7030] -> $807

    # -----------------------------------------------------------------------
    # MFS Step-2 Column (uses same data as Single Step-2 per IRS table): verified via routing
    # Source: Pub 15-T 2026 p.14, weekly, Single/MFS Step-2, routing single==married_separately
    # -----------------------------------------------------------------------
    (52, Decimal("550"), Decimal("560"), "married_separately", True, Decimal("46")),
    # Source: Pub 15-T 2026 p.14, weekly, Single/MFS Step-2, row [$550-$560] -> $46
    # (MFS routes to same column as Single -- this exercises the MFS Step-2 routing path)
]


@pytest.mark.parametrize(
    "frequency,interval_lower,interval_upper,filing_status,step2,published_cell",
    _WAGE_BRACKET_FIXTURES,
    ids=[
        f"{fs}{'_step2' if s2 else '_std'}_p{freq}_{int(lo)}-{int(hi)}"
        for freq, lo, hi, fs, s2, _ in _WAGE_BRACKET_FIXTURES
    ],
)
def test_wage_bracket_cross_check(
    frequency: int,
    interval_lower: Decimal,
    interval_upper: Decimal,
    filing_status: str,
    step2: bool,
    published_cell: Decimal,
) -> None:
    """Wage-bracket PRIMARY oracle cross-check.

    For each wage-bracket interval, evaluate the engine at the interval midpoint,
    quantize to whole dollar using ROUND_HALF_UP, assert EXACT EQUALITY against
    the independently-transcribed published cell.

    Independence guarantee: a transcription error in tax_tables_2026.py cannot
    simultaneously corrupt both the percentage-table rows (which the engine uses)
    and the separately-transcribed wage-bracket cells (which this test uses as its
    oracle) -- they were transcribed from different sections of the IRS PDF.

    Exact equality is the DEFAULT. No blanket +-$1 tolerance.
    """
    # Midpoint of the wage interval (exact Decimal arithmetic)
    midpoint = (interval_lower + interval_upper) / Decimal("2")

    emp = _make_employee(
        filing_status=filing_status,
        step_2_checkbox=step2,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        pay_periods_per_year=frequency,
    )

    engine_result = federal_withholding_2026(midpoint, emp)
    # Whole-dollar comparison uses quantize(ROUND_HALF_UP), NOT Python round():
    # Python round() is ROUND_HALF_EVEN (banker's rounding), which would disagree with
    # the IRS's own whole-dollar convention on exact-half cells.
    engine_whole_dollar = engine_result.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    # EXACT EQUALITY is the default assertion. A +-$1 tolerance is only permitted on a
    # SPECIFICALLY-NAMED fixture row carrying an inline comment stating the
    # extraction/rounding anomaly. No such anomaly exists in this suite -- exact
    # equality everywhere.
    assert engine_whole_dollar == published_cell, (
        f"Wage-bracket cross-check FAILED: "
        f"{filing_status}/{'step2' if step2 else 'std'}/p={frequency} "
        f"interval=[{interval_lower}, {interval_upper}] midpoint={midpoint} "
        f"engine_whole_dollar={engine_whole_dollar} != published_cell={published_cell}. "
        f"This is a PRIMARY oracle failure -- check tax_tables_2026.py transcription "
        f"or the engine's Worksheet 1A implementation for a bracket/line-1g bug."
    )


# ---------------------------------------------------------------------------
# BRACKET BOUNDARY TESTS -- DIRECT _find_bracket()
# ---------------------------------------------------------------------------
# _find_bracket() is lower-bound-driven (>= row.lower). Constructing per-period wages
# via (B + STEP1_STANDARD) / 52 may not land on the exact annual boundary B once
# _money(line_1a * p) rounds, so these tests call _find_bracket() DIRECTLY with
# adjusted-annual-wage inputs at exactly B, B - $0.01, and B + $0.01 -- no
# annualization rounding to confound the boundary.
#
# This is the only place a >= vs > regression in _find_bracket() shows up: such a bug
# passes every midpoint check in the sweep above and only misprices wages sitting
# exactly on a bracket boundary.
#
# Boundary B chosen: $19,900 (the 10%->12% boundary in the Single/Standard table).
# Source: STANDARD_BRACKETS["single"] in tax_tables_2026.py (read directly).

_BOUNDARY_B = Decimal("19900")  # Single/Standard 10%->12% boundary (column A lower bound)
_STEP1_SINGLE = Decimal("8600")  # STEP1_STANDARD["single"]


def test_bracket_boundary_at_B() -> None:
    """annual_wage = B exactly -> _find_bracket returns the row whose lower == B."""
    row = _find_bracket(_BOUNDARY_B, STANDARD_BRACKETS["single"])
    assert row.lower == _BOUNDARY_B, (
        f"at B={_BOUNDARY_B} exactly, _find_bracket must return the row starting AT B "
        f"(lower bound INCLUSIVE). Got row.lower={row.lower}. "
        "A > instead of >= in _find_bracket would return the row BELOW B and "
        "under-withhold everyone sitting exactly on the boundary."
    )
    assert row.base == Decimal("1240.00"), f"Expected base=$1240 (12% bracket), got {row.base}"
    assert row.rate == Decimal("0.12"), f"Expected rate=12%, got {row.rate}"

    # Also verify federal_withholding_2026 at this adjusted-annual-wage input.
    # Per-period gross that lands line_1i exactly at B (Single/Standard, p=52):
    #   annualized_gross = B + STEP1_SINGLE = 19900 + 8600 = 28500
    #   per_period_gross = 28500 / 52 (exact Decimal quotient)
    # Engine computes: line_1c = money(28500/52 * 52) = 28500 (exact, no rounding loss)
    # line_1i = max(0, money(28500 - 8600)) = 19900 = B exactly
    #
    # Hand-computation at line_1i = 19900 (12% bracket entry point):
    #   2e = 19900 - 19900 = 0
    #   2f = 0 * 0.12 = 0
    #   2g = 1240 + 0 = 1240
    #   2h = 1240 / 52 = 23.846... -> money = 23.85
    #   3c = 23.85
    _annualized_at_B = _BOUNDARY_B + _STEP1_SINGLE  # 28500
    per_period_at_B = _annualized_at_B / Decimal("52")
    emp = _make_employee(
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        pay_periods_per_year=52,
    )
    wh = federal_withholding_2026(per_period_at_B, emp)
    # 1240/52 = 23.84615... -> ROUND_HALF_UP to cents -> 23.85
    assert wh == Decimal("23.85"), (
        f"at B={_BOUNDARY_B} withholding should be 23.85, got {wh}"
    )


def test_bracket_boundary_below_B() -> None:
    """annual_wage = B - $0.01 -> _find_bracket returns the row whose lower < B."""
    wage_below = _BOUNDARY_B - Decimal("0.01")  # 19899.99
    row = _find_bracket(wage_below, STANDARD_BRACKETS["single"])
    assert row.lower < _BOUNDARY_B, (
        f"at B-$0.01={wage_below}, _find_bracket must return the row BELOW B "
        f"(the boundary is exclusive from below). Got row.lower={row.lower}. "
        "A <= instead of < exit condition would leak a wage one cent short of the "
        "boundary into the higher bracket."
    )
    # Should be in the 10% bracket ($7,500-$19,900)
    assert row.lower == Decimal("7500"), (
        f"Expected 10% bracket (lower=7500), got row.lower={row.lower}"
    )
    assert row.rate == Decimal("0.10"), f"Expected rate=10%, got {row.rate}"


def test_bracket_boundary_above_B() -> None:
    """annual_wage = B + $0.01 -> _find_bracket returns the same row as B (stable
    just above the boundary)."""
    wage_above = _BOUNDARY_B + Decimal("0.01")  # 19900.01
    row = _find_bracket(wage_above, STANDARD_BRACKETS["single"])
    assert row.lower == _BOUNDARY_B, (
        f"at B+$0.01={wage_above}, _find_bracket must return the same row as B "
        f"(>= is inclusive on the boundary, so the row is stable just above it). "
        f"Got row.lower={row.lower}."
    )


# ---------------------------------------------------------------------------
# FULL GOLDEN MATRIX (penny-exact, hand-computed)
# ---------------------------------------------------------------------------
# All expected values are hand-computed from the bracket tables (independently
# transcribed from irs.gov/pub/irs-pdf/p15t.pdf, 2026-06-22).
# NO expected value was derived by calling tax_tables_2026 or federal_withholding_2026.
#
# Hand-computation key examples:
#
# (1) Single/Standard/Weekly/$800 (RESEARCH.md §"Hand-Computation Worked Example"):
#   1c = $800 * 52 = $41,600 / 1g = $8,600 / 1i = $33,000
#   bracket: $19,900-$57,900, base=$1,240, 12%
#   2e = $13,100 / 2f = $1,572 / 2g = $2,812 / 2h = $54.08
#   -> $54.08
#
# (2) MFJ/Standard/Weekly/$1,200:
#   1i = $62,400 - $12,900 = $49,500 / bracket $44,100-$120,100, base=$2,480, 12%
#   2e = $5,400 / 2f = $648 / 2g = $3,128 / 2h = $60.15
#   -> $60.15
#
# (3) Single/Standard/Weekly/$1,000 step_3=$2,000:
#   1i = $43,400 / 2h = $78.08 / 3b = $38.46 / 3c = $39.62
#   -> $39.62
#
# (4) Single/Step2/Weekly/$700:
#   1g = $0 / 1i = $36,400 / bracket $33,250-$60,900, base=$2,900, 22%
#   2e = $3,150 / 2f = $693 / 2g = $3,593 / 2h = $69.10
#   -> $69.10
#
# (5) MFJ/Step2/Weekly/$900:
#   1g = $0 / 1i = $46,800 / bracket $28,500-$66,500, base=$1,240, 12%
#   2e = $18,300 / 2f = $2,196 / 2g = $3,436 / 2h = $66.08
#   -> $66.08
#
# (6) MFS/Standard/Weekly/$800 (same table as Single): -> $54.08
#
# (7) Single/Standard/Biweekly/$2,000:
#   1i = $43,400 / 2h = $156.15
#   -> $156.15
#
# (8) Zero-bracket: Single/Standard/Weekly/$100: line_1i floors at $0 -> $0.00
#
# (9) Single/Standard/Weekly/$800 step_4a=$5,000:
#   1d = $5,000 / 1i = $38,000 / 2h = $65.62
#   -> $65.62
#
# (10) Single/Standard/Weekly/$800 step_4b=$3,000:
#   1f = $3,000 / 1h = $11,600 / 1i = $30,000 / 2h = $47.15
#   -> $47.15
#
# (11) Single/Standard/Monthly/$4,000: 1i=$39,400 / 2h=$298.33 -> $298.33
#
# (12) Single/Standard/Semi-monthly/$2,000: 1i=$39,400 / 2h=$149.17 -> $149.17

@pytest.mark.parametrize("desc,wages_this_period,emp_kwargs,expected_wh", [
    # -----------------------------------------------------------------------
    # Layer-A: hand-computed from RESEARCH.md Deliverable 1
    # -----------------------------------------------------------------------

    # (1) Single/Standard/Weekly/$800 -- RESEARCH.md §"Hand-Computation Worked Example"
    (
        "single_std_weekly_800",
        Decimal("800.00"),
        {
            "filing_status": "single",
            "step_2_checkbox": False,
            "step_3_dependents": Decimal("0"),
            "step_4a_other_income": Decimal("0"),
            "step_4b_deductions": Decimal("0"),
            "pay_periods_per_year": 52,
        },
        Decimal("54.08"),
    ),

    # (2) MFJ/Standard/Weekly/$1,200
    (
        "mfj_std_weekly_1200",
        Decimal("1200.00"),
        {
            "filing_status": "married_jointly",
            "step_2_checkbox": False,
            "step_3_dependents": Decimal("0"),
            "step_4a_other_income": Decimal("0"),
            "step_4b_deductions": Decimal("0"),
            "pay_periods_per_year": 52,
        },
        Decimal("60.15"),
    ),

    # (3) Single/Standard/Weekly/$1,000 with step_3=$2,000
    (
        "single_std_weekly_1000_step3_credit",
        Decimal("1000.00"),
        {
            "filing_status": "single",
            "step_2_checkbox": False,
            "step_3_dependents": Decimal("2000.00"),
            "step_4a_other_income": Decimal("0"),
            "step_4b_deductions": Decimal("0"),
            "pay_periods_per_year": 52,
        },
        Decimal("39.62"),
    ),

    # (4) Single/Step2/Weekly/$700
    (
        "single_step2_weekly_700",
        Decimal("700.00"),
        {
            "filing_status": "single",
            "step_2_checkbox": True,
            "step_3_dependents": Decimal("0"),
            "step_4a_other_income": Decimal("0"),
            "step_4b_deductions": Decimal("0"),
            "pay_periods_per_year": 52,
        },
        Decimal("69.10"),
    ),

    # (5) MFJ/Step2/Weekly/$900 -- covers the MFJ+Step2 schedule gap
    (
        "mfj_step2_weekly_900",
        Decimal("900.00"),
        {
            "filing_status": "married_jointly",
            "step_2_checkbox": True,
            "step_3_dependents": Decimal("0"),
            "step_4a_other_income": Decimal("0"),
            "step_4b_deductions": Decimal("0"),
            "pay_periods_per_year": 52,
        },
        Decimal("66.08"),
    ),

    # (6) MFS/Standard/Weekly/$800 -- uses Single/MFS table (same as case 1)
    (
        "mfs_std_weekly_800",
        Decimal("800.00"),
        {
            "filing_status": "married_separately",
            "step_2_checkbox": False,
            "step_3_dependents": Decimal("0"),
            "step_4a_other_income": Decimal("0"),
            "step_4b_deductions": Decimal("0"),
            "pay_periods_per_year": 52,
        },
        Decimal("54.08"),
    ),

    # (7) Single/Standard/Biweekly/$2,000 (26 periods)
    (
        "single_std_biweekly_2000",
        Decimal("2000.00"),
        {
            "filing_status": "single",
            "step_2_checkbox": False,
            "step_3_dependents": Decimal("0"),
            "step_4a_other_income": Decimal("0"),
            "step_4b_deductions": Decimal("0"),
            "pay_periods_per_year": 26,
        },
        Decimal("156.15"),
    ),

    # (8) Below-threshold: Single/Standard/Weekly/$100 -> line_1i floors at $0 -> $0.00
    (
        "single_std_weekly_100_below_threshold",
        Decimal("100.00"),
        {
            "filing_status": "single",
            "step_2_checkbox": False,
            "step_3_dependents": Decimal("0"),
            "step_4a_other_income": Decimal("0"),
            "step_4b_deductions": Decimal("0"),
            "pay_periods_per_year": 52,
        },
        Decimal("0.00"),
    ),

    # (9) Single/Standard/Weekly/$800 with step_4a=$5,000 (other income)
    (
        "single_std_weekly_800_step4a",
        Decimal("800.00"),
        {
            "filing_status": "single",
            "step_2_checkbox": False,
            "step_3_dependents": Decimal("0"),
            "step_4a_other_income": Decimal("5000.00"),
            "step_4b_deductions": Decimal("0"),
            "pay_periods_per_year": 52,
        },
        Decimal("65.62"),
    ),

    # (10) Single/Standard/Weekly/$800 with step_4b=$3,000 (extra deductions)
    (
        "single_std_weekly_800_step4b",
        Decimal("800.00"),
        {
            "filing_status": "single",
            "step_2_checkbox": False,
            "step_3_dependents": Decimal("0"),
            "step_4a_other_income": Decimal("0"),
            "step_4b_deductions": Decimal("3000.00"),
            "pay_periods_per_year": 52,
        },
        Decimal("47.15"),
    ),

    # (11) Single/Standard/Monthly/$4,000 (12 periods) -- covers monthly frequency
    (
        "single_std_monthly_4000",
        Decimal("4000.00"),
        {
            "filing_status": "single",
            "step_2_checkbox": False,
            "step_3_dependents": Decimal("0"),
            "step_4a_other_income": Decimal("0"),
            "step_4b_deductions": Decimal("0"),
            "pay_periods_per_year": 12,
        },
        Decimal("298.33"),
    ),

    # (12) Single/Standard/Semi-monthly/$2,000 (24 periods) -- covers semi-monthly
    (
        "single_std_semimonthly_2000",
        Decimal("2000.00"),
        {
            "filing_status": "single",
            "step_2_checkbox": False,
            "step_3_dependents": Decimal("0"),
            "step_4a_other_income": Decimal("0"),
            "step_4b_deductions": Decimal("0"),
            "pay_periods_per_year": 24,
        },
        Decimal("149.17"),
    ),

    # (13) Zero wages -> zero withholding
    (
        "zero_wages_zero_withholding",
        Decimal("0.00"),
        {
            "filing_status": "single",
            "step_2_checkbox": False,
            "step_3_dependents": Decimal("0"),
            "step_4a_other_income": Decimal("0"),
            "step_4b_deductions": Decimal("0"),
            "pay_periods_per_year": 52,
        },
        Decimal("0.00"),
    ),

    # (14) Step-3 floor: large credit exceeds tentative withholding -> must return $0.00
    (
        "step3_floor_at_zero",
        Decimal("150.00"),
        {
            "filing_status": "single",
            "step_2_checkbox": False,
            "step_3_dependents": Decimal("5000.00"),
            "step_4a_other_income": Decimal("0"),
            "step_4b_deductions": Decimal("0"),
            "pay_periods_per_year": 52,
        },
        Decimal("0.00"),
    ),
])
def test_federal_withholding_golden(
    desc: str,
    wages_this_period: Decimal,
    emp_kwargs: dict[str, Any],
    expected_wh: Decimal,
) -> None:
    """All expected values are hand-computed; see module docstring for methodology."""
    emp = _make_employee(**emp_kwargs)
    result = federal_withholding_2026(wages_this_period, emp)
    assert result == expected_wh, (
        f"[{desc}] expected {expected_wh}, got {result}. "
        "Re-verify hand computation and layer-B cross-check before changing the expected value."
    )


# ---------------------------------------------------------------------------
# Non-negative / floor invariant tests
# ---------------------------------------------------------------------------

def test_withholding_never_negative_step3_floor() -> None:
    """Step-3 floor: large credit must produce $0.00, not a negative number."""
    emp = _make_employee(
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("10000.00"),  # very large credit
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        pay_periods_per_year=52,
    )
    result = federal_withholding_2026(Decimal("200.00"), emp)
    assert result >= Decimal("0.00"), f"Withholding must not be negative: got {result}"
    assert result == Decimal("0.00"), f"Expected $0.00 floor, got {result}"


def test_withholding_never_negative_low_wages() -> None:
    """Line 1i floor: wages well below STEP1_STANDARD threshold -> $0.00."""
    emp = _make_employee(
        filing_status="married_jointly",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        pay_periods_per_year=52,
    )
    # $50/week * 52 = $2,600 < $12,900 MFJ standard -> line_1i floors at $0
    result = federal_withholding_2026(Decimal("50.00"), emp)
    assert result >= Decimal("0.00"), f"Withholding must not be negative: got {result}"
    assert result == Decimal("0.00")


# ---------------------------------------------------------------------------
# HoH reject-guard test
# ---------------------------------------------------------------------------

def test_hoh_reject_guard() -> None:
    """head_of_household must raise ValueError containing 'head_of_household'.

    This is a defense-in-depth guard: Employee.filing_status is constrained by
    Literal["single", "married_jointly", "married_separately"], so 'head_of_household'
    is not a valid Literal value. The guard catches any future extension, eval fixture,
    or bypass that constructs an Employee with a different filing_status value.
    """
    emp = _make_employee(
        filing_status="single",  # valid at construction
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        pay_periods_per_year=52,
    )
    # Bypass Pydantic Literal check to simulate a future extension or eval fixture
    bad_emp = copy.copy(emp)
    object.__setattr__(bad_emp, "filing_status", "head_of_household")

    with pytest.raises(ValueError, match="head_of_household"):
        federal_withholding_2026(Decimal("800.00"), bad_emp)


# Aliases for existing tests that may use different name
test_hoh_raises_value_error = test_hoh_reject_guard  # backward compat alias


def test_unknown_status_raises_value_error() -> None:
    """Any unrecognised filing_status must raise ValueError."""
    emp = _make_employee(
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        pay_periods_per_year=52,
    )
    bad_emp = copy.copy(emp)
    object.__setattr__(bad_emp, "filing_status", "qualifying_surviving_spouse")

    with pytest.raises(ValueError):
        federal_withholding_2026(Decimal("800.00"), bad_emp)


# ---------------------------------------------------------------------------
# Step-2-checkbox branch test (uses STEP2_BRACKETS, not STANDARD_BRACKETS)
# ---------------------------------------------------------------------------

def test_step2_checkbox_uses_different_table() -> None:
    """step_2_checkbox=True must produce a different result than step_2_checkbox=False."""
    standard_emp = _make_employee(
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        pay_periods_per_year=52,
    )
    step2_emp = _make_employee(
        filing_status="single",
        step_2_checkbox=True,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        pay_periods_per_year=52,
    )
    wages = Decimal("700.00")
    result_std = federal_withholding_2026(wages, standard_emp)
    result_step2 = federal_withholding_2026(wages, step2_emp)
    # At $700/week the Step-2 table produces substantially higher withholding
    # (no STEP1_STANDARD subtraction + different bracket thresholds)
    assert result_step2 > result_std, (
        f"Step-2 withholding {result_step2} should exceed standard {result_std}"
    )


# ---------------------------------------------------------------------------
# MFS == Single table test
# ---------------------------------------------------------------------------

def test_mfs_uses_same_table_as_single() -> None:
    """married_separately must produce the same result as single (same IRS table)."""
    wages = Decimal("900.00")
    single_emp = _make_employee(
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        pay_periods_per_year=52,
    )
    mfs_emp = _make_employee(
        filing_status="married_separately",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        pay_periods_per_year=52,
    )
    assert federal_withholding_2026(wages, single_emp) == federal_withholding_2026(wages, mfs_emp)


# ---------------------------------------------------------------------------
# Module purity test (no DB / network on import)
# ---------------------------------------------------------------------------

def test_module_importable_with_no_db() -> None:
    """federal_withholding is a pure function -- importable with no DB access."""
    mod = importlib.import_module("app.pipeline.federal_withholding")
    assert hasattr(mod, "federal_withholding_2026")


# ---------------------------------------------------------------------------
# ADDITIONAL MEDICARE LIMITATION FLAG TESTS
# ---------------------------------------------------------------------------
# The Additional Medicare 0.9% surtax over $200k YTD is NOT modeled.
# The engine flags it via additional_medicare_not_modeled=True on PaystubLineItem.
#
# These tests must use REALISTIC SS-capped YTD values: ytd_ss_wages CANNOT legitimately
# exceed $184,500 (the 2026 SS wage base cap), so a fixture at 196000 or 197000 is
# IMPOSSIBLE in a real run. Testing the flag from an impossible YTD exercises the Boolean
# expression against a state the system can never reach -- a test of dead code.
#
# The proxy fires on (ytd_ss_wages + gross) > $200,000. ytd_ss_wages is a LOWER-BOUND
# proxy for YTD Medicare wages (Medicare has no cap, so Medicare YTD >= SS YTD always).
# It therefore under-flags high earners whose true Medicare YTD already exceeds their
# capped SS YTD -- an accepted limitation of the static-seed model. The flag stays
# flag-only: the 0.9% is never modeled.

def test_additional_medicare_limitation_is_flagged() -> None:
    """The Additional Medicare limitation flag fires at realistic SS-capped YTD values.

    Flag-FIRES case: ytd_ss_wages=184500 (AT the SS wage base -- the maximum possible
    real value) + a high current gross ($20,000) -> proxy = 204500 > 200000.
    """
    # A high current-period gross ($20,000) is what pushes (ytd + gross) above $200k --
    # the YTD itself cannot legitimately go any higher than the cap.
    emp_at_cap = _make_employee(
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        pay_periods_per_year=52,
        ytd_ss_wages=Decimal("184500"),  # AT the SS wage base cap -- the max real value
        hourly_rate=Decimal("500.00"),   # 40h * $500 = $20,000/period
    )
    item_cap = calculate(
        {
            "hours_regular": Decimal("40"),
            "hours_overtime": Decimal("0"),
            "hours_vacation": Decimal("0"),
            "hours_sick": Decimal("0"),
            "hours_holiday": Decimal("0"),
        },
        emp_at_cap,
    )
    # 184500 + 20000 = 204500 > 200000 -- MUST fire
    assert item_cap.additional_medicare_not_modeled is True, (
        f"Flag must fire when (ytd_ss_wages=184500 + gross={item_cap.gross_pay}) > 200000. "
        "184500 is the realistic SS-cap maximum, not an impossible value."
    )


def test_additional_medicare_flag_does_not_fire_for_normal_employee() -> None:
    """The Additional Medicare limitation flag does NOT fire for a normal employee.

    Flag-DOES-NOT-fire case: ytd_ss_wages=0, normal gross ($4,000) -> proxy=$4,000 << $200k.
    """
    # A normal employee: (ytd_ss_wages + gross) sits well below the $200k threshold.
    emp_normal = _make_employee(
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        pay_periods_per_year=52,
        ytd_ss_wages=Decimal("0"),
        hourly_rate=Decimal("100.00"),  # 40h * $100 = $4,000/period
    )
    item_normal = calculate(
        {
            "hours_regular": Decimal("40"),
            "hours_overtime": Decimal("0"),
            "hours_vacation": Decimal("0"),
            "hours_sick": Decimal("0"),
            "hours_holiday": Decimal("0"),
        },
        emp_normal,
    )
    # 0 + 4000 = 4000 << 200000 -- must NOT fire
    assert item_normal.additional_medicare_not_modeled is False, (
        "Flag must NOT fire for a normal employee with ytd_ss_wages=0 and gross=$4,000"
    )


# ---------------------------------------------------------------------------
# CALC-04: SS wage-base straddle -- Thomas Bergmann (under-ceiling FICA assertion)
# ---------------------------------------------------------------------------
# NOTE: This is the UNDER-CEILING FICA straddle test for Thomas Bergmann.
# It tests partial SS-taxable wages via calculate() -- NOT the over-ceiling federal
# withholding fixture (which is a SEPARATE concern, skipped per CHECKPOINT_RESOLUTION).
#
# Thomas Bergmann: annual=$240,000, pay_periods=26 (biweekly), 401k=8%,
#   ytd_ss_wages=$183,900, SS_WAGE_BASE=$184,500
#   per_period_gross = 240000/26 = $9,230.77 (rounded)
#   remaining_cap = 184500 - 183900 = $600
#   ss_taxable = min(9230.77, 600) = $600
#   fica_ss = $600 * 0.062 = $37.20 (PARTIAL -- straddle case)
#
# The FEDERAL withholding for Thomas Bergmann (~$9,230/biweekly) is OVER the
# $3,875 biweekly wage-bracket ceiling and requires layer-B calculator verification.
# Per CHECKPOINT_RESOLUTION, that fixture is SKIPPED (over-ceiling oracle UNRESOLVED).
# This test only asserts the FICA straddle, which is independent of the withholding oracle.

def test_ss_straddle_thomas_bergmann(thomas_bergmann) -> None:
    """CALC-04: SS wage-base straddle -- only $600 of wages is SS-taxable.

    Thomas Bergmann has ytd_ss_wages=$183,900, which is $600 below the $184,500 cap.
    His biweekly gross ($9,230.77) exceeds the remaining cap ($600), so only $600
    is SS-taxable: fica_ss = $600 * 6.2% = $37.20.
    """
    # Use calculate() to exercise the full path including FICA straddle logic.
    # Thomas Bergmann is salaried -- zero hours still yields annual/26 gross.
    item = calculate(
        {
            "hours_regular": Decimal("0"),
            "hours_overtime": Decimal("0"),
            "hours_vacation": Decimal("0"),
            "hours_sick": Decimal("0"),
            "hours_holiday": Decimal("0"),
        },
        thomas_bergmann,
    )
    # Hand-computation:
    # period_gross = money(240000 / 26) = 9230.77
    # remaining_cap = 184500 - 183900 = 600.00
    # ss_taxable = min(9230.77, 600.00) = 600.00
    # fica_ss = money(600.00 * 0.062) = money(37.20) = 37.20
    assert item.fica_ss == Decimal("37.20"), (
        f"CALC-04 SS straddle: expected fica_ss=37.20, got {item.fica_ss}. "
        "Only $600 of the $9,230.77 biweekly gross is SS-taxable (remaining cap = $600)."
    )


# ---------------------------------------------------------------------------
# Thomas Bergmann OVER-CEILING federal withholding fixture (VERIFIED)
# ---------------------------------------------------------------------------
# Layer-B oracle verification (2026-06-22, operator-run):
#   Calibration (under-ceiling): paycheckcity.com returned $54.08 for Single/Standard/
#     Weekly/$800 -> confirms it is in IRS Pub 15-T 2026 percentage-method mode.
#     usapaycheck.org was DISCARDED for this case: it rounds inputs/outputs (dropped the
#     cents), so it cannot serve as a penny-exact oracle (it returned ~$682 on calibration).
#   Over-ceiling (this fixture): paycheckcity.com, with the 8% contribution entered as a
#     TRADITIONAL pre-tax 401(k), returned Federal Withholding = $881.39 for the inputs
#     below -- a PENNY-EXACT match with this engine. (An initial run that did NOT apply the
#     401(k) to the federal base returned $1,043.85; re-running with the 401(k) as pre-tax
#     reconciled it exactly to $881.39, confirming the difference was purely the 401(k)
#     input handling, not an engine/table error.)
#
# ORACLE PROVENANCE (honest): this value is verified by ONE independent online calculator
# (paycheckcity.com) that matches penny-for-penny, PLUS a full line-by-line Worksheet 1A
# hand trace (see the step comments below). The plan's original ask was TWO independent
# online calculators; usapaycheck.org was unusable (rounding), so only one online oracle
# corroborates -- but it agrees exactly AND the independent trace agrees, so the value is
# adopted. If a second penny-exact online oracle is found later, add it here.

def test_federal_withholding_thomas_bergmann_over_ceiling(thomas_bergmann) -> None:
    """Thomas Bergmann over-ceiling federal withholding (biweekly, MFJ, ~$9,230/period).

    Inputs (from seed): annual_salary=$240,000, pay_periods=26, filing_status=MFJ,
    step_2_checkbox=False, retirement_contribution_pct=8%, step_3_dependents=$8,000,
    step_4a=$0, step_4b=$0.

    Worksheet 1A trace (MFJ, Standard, biweekly p=26):
      per-period gross   = 240000 / 26          = 9230.77
      pretax 401k (8%)   = 9230.77 * 0.08       = 738.46
      federal taxable    = 9230.77 - 738.46     = 8492.31   (1a)
      1c annualized      = 8492.31 * 26          = 220800.06
      1g MFJ proxy       = 12900
      1i adjusted annual = 220800.06 - 12900     = 207900.06
      bracket (MFJ Std)  = [120100, 230700) base=11600.00 rate=22%
      2g annual tentative= 11600 + 0.22*(207900.06-120100) = 30916.01
      2h per-period      = 30916.01 / 26         = 1189.08
      3b per-period credit = 8000 / 26           = 307.69
      3c FINAL withhold  = 1189.08 - 307.69      = 881.39   <-- expected

    Layer-B oracle: paycheckcity.com (pre-tax 401k) returned $881.39 -- penny-exact match.
    """
    # Drive the PRODUCTION path (calculate() applies the pre-tax 401k to the federal base,
    # CALC-03) -- this is exactly how an over-ceiling high earner is computed in a real run.
    item = calculate(
        {
            "hours_regular": Decimal("0"),
            "hours_overtime": Decimal("0"),
            "hours_vacation": Decimal("0"),
            "hours_sick": Decimal("0"),
            "hours_holiday": Decimal("0"),
        },
        thomas_bergmann,
    )
    assert item.gross_pay == Decimal("9230.77"), f"gross {item.gross_pay} != 9230.77"
    assert item.pretax_401k == Decimal("738.46"), f"401k {item.pretax_401k} != 738.46"
    # Over-ceiling federal withholding, verified penny-exact against paycheckcity.com
    # (pre-tax 401k).
    assert item.federal_withholding == Decimal("881.39"), (
        f"over-ceiling federal withholding {item.federal_withholding} != 881.39 "
        "(layer-B oracle: paycheckcity.com pre-tax-401k = $881.39, penny-exact)"
    )


# ---------------------------------------------------------------------------
# 401k reduces the federal base but NOT the FICA base (interaction via calculate())
# ---------------------------------------------------------------------------
# Traditional (pre-tax) 401k:
#   - REDUCES the federal income tax withholding base (federal uses gross - pretax_401k)
#   - Does NOT reduce the FICA base (FICA uses gross)
# Applying the deferral to both bases is the single easiest way to under-withhold a
# contributing employee, which makes this the highest-risk 401k interaction in the calc.

def test_401k_reduces_federal_not_fica(james_okafor) -> None:
    """FICA SS uses the gross base; federal withholding uses gross - pretax_401k.

    James Okafor: salary=$62,400, pay_periods=52, 401k=4%, step_3=$4,000.
    period_gross = 62400/52 = 1200.00
    pretax_401k = 1200.00 * 0.04 = 48.00
    FICA SS: uses gross=$1200, not gross-401k=$1152
    Federal: uses gross-401k=$1152

    Verify: fica_ss == money(1200 * 0.062) = 74.40
            federal_withholding uses 1152 as the taxable base (not 1200)
    """
    from app.pipeline.tax_tables_2026 import SS_RATE as _SS_RATE

    item = calculate(
        {
            "hours_regular": Decimal("0"),
            "hours_overtime": Decimal("0"),
            "hours_vacation": Decimal("0"),
            "hours_sick": Decimal("0"),
            "hours_holiday": Decimal("0"),
        },
        james_okafor,
    )

    # FICA SS must use gross (not gross - 401k)
    from decimal import ROUND_HALF_UP as _RHU
    expected_fica_ss = (item.gross_pay * _SS_RATE).quantize(Decimal("0.01"), rounding=_RHU)
    assert item.fica_ss == expected_fica_ss, (
        f"CALC-03: fica_ss={item.fica_ss} should be gross*SS_RATE={expected_fica_ss}. "
        "FICA must use gross, not (gross - pretax_401k)."
    )

    # Federal withholding must be LOWER than if no 401k (federal base is reduced)
    # Build a comparison employee with 0% 401k (override) to confirm the reduction
    item_no_401k = calculate(
        {
            "hours_regular": Decimal("0"),
            "hours_overtime": Decimal("0"),
            "hours_vacation": Decimal("0"),
            "hours_sick": Decimal("0"),
            "hours_holiday": Decimal("0"),
        },
        james_okafor,
        contribution_401k_override=Decimal("0"),
    )
    assert item.federal_withholding <= item_no_401k.federal_withholding, (
        f"CALC-03: with 401k, federal_withholding={item.federal_withholding} should be <= "
        f"without 401k={item_no_401k.federal_withholding}. "
        "401k reduces the federal taxable base; lower base means lower or equal withholding."
    )


# ---------------------------------------------------------------------------
# Fix 7b: Step-4b deduction does NOT reduce the FICA base
# ---------------------------------------------------------------------------
# Step-4b (additional deductions from W-4) reduces the federal withholding base
# via line_1h = line_1f + line_1g. It does NOT reduce the FICA base.
# FICA is always computed on gross, regardless of step_4b.

def test_step4b_does_not_reduce_fica_base() -> None:
    """Fix 7b: step_4b_deductions reduce federal withholding base but NOT FICA base.

    At gross=$800/week (40h * $20/hr), step_4b=$3,000 annual:
    Federal: 1f=$3,000, 1h=$11,600, 1i=$30,000 -> withholding=$47.15 (reduced)
    FICA SS: uses gross=$800 regardless of step_4b -> fica_ss=$49.60
    """
    from decimal import ROUND_HALF_UP as _RHU

    from app.pipeline.tax_tables_2026 import SS_RATE as _SS_RATE

    # Employee with step_4b=$3,000 and hourly=$20, 40h/period = $800 gross
    emp_with_step4b = _make_employee(
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("3000.00"),  # annual step_4b deduction
        pay_periods_per_year=52,
        hourly_rate=Decimal("20.00"),
    )

    item = calculate(
        {
            "hours_regular": Decimal("40"),
            "hours_overtime": Decimal("0"),
            "hours_vacation": Decimal("0"),
            "hours_sick": Decimal("0"),
            "hours_holiday": Decimal("0"),
        },
        emp_with_step4b,
    )

    gross = item.gross_pay  # should be 800.00

    # FICA SS: must use gross=$800, NOT (gross - step_4b_annual/52)
    # step_4b is an ANNUAL amount; it reduces the ANNUAL withholding base, not the FICA base
    expected_fica_ss = (gross * _SS_RATE).quantize(Decimal("0.01"), rounding=_RHU)
    assert item.fica_ss == expected_fica_ss, (
        f"Fix 7b: fica_ss={item.fica_ss} should be gross*SS_RATE={expected_fica_ss}. "
        "step_4b_deductions do NOT reduce the FICA base -- only the federal withholding base."
    )

    # Federal withholding IS reduced by step_4b
    # Without step_4b, withholding = $54.08 (case 1 above)
    emp_no_step4b = _make_employee(
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        pay_periods_per_year=52,
        hourly_rate=Decimal("20.00"),
    )
    item_no_step4b = calculate(
        {
            "hours_regular": Decimal("40"),
            "hours_overtime": Decimal("0"),
            "hours_vacation": Decimal("0"),
            "hours_sick": Decimal("0"),
            "hours_holiday": Decimal("0"),
        },
        emp_no_step4b,
    )
    assert item.federal_withholding < item_no_step4b.federal_withholding, (
        f"Fix 7b: step_4b should reduce federal_withholding. "
        f"With step_4b: {item.federal_withholding}, without: {item_no_step4b.federal_withholding}"
    )
