"""Golden-value tests for the Pub 15-T 2026 Worksheet 1A federal withholding engine.

ALL expected values were hand-computed from the 2026 Pub 15-T bracket tables
(RESEARCH.md Deliverable 1, sourced from irs.gov/pub/irs-pdf/p15t.pdf, retrieved 2026-06-22)
and cross-checked against usapaycheck.org and paycheckcity.com before being written here.
NO expected value was derived from the tax_tables_2026.py module under test.

Hand-computation methodology (RESEARCH.md §"Worksheet 1A Computation Flow"):
  1. Annualize: line_1c = wages * pay_periods; subtract STEP1_STANDARD (if step_2=False)
  2. Bracket lookup: find row where line_1i >= row.lower (Single/Standard $33,000 → 12% bracket)
  3. Compute tentative annual: base + rate * (line_1i - bracket_lower)
  4. De-annualize: ÷ pay_periods
  5. Subtract Step-3 credit (per-period), floor at $0
  6. Return (no step_4c for seeded employees)

Oracle sources:
  Layer A: RESEARCH.md Deliverable 1 hand computations (independent of code module)
  Layer B: usapaycheck.org, paycheckcity.com (secondary corroboration)
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.pipeline.federal_withholding import federal_withholding_2026
from app.models.roster import Employee


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
# Golden-value parametrized tests
# ---------------------------------------------------------------------------
# All expected values hand-computed per RESEARCH.md Worksheet 1A flow and
# verified against layer-B calculators before being written here.
#
# Hand-computation key examples:
#
# (1) Single/Standard/Weekly/$800 (RESEARCH.md §"Hand-Computation Worked Example"):
#   1c = $800 × 52 = $41,600
#   1g = $8,600 (Single standard)
#   1i = $41,600 - $8,600 = $33,000
#   bracket: $19,900–$57,900, base=$1,240, rate=12%
#   2e = $33,000 - $19,900 = $13,100
#   2f = $13,100 × 0.12 = $1,572.00
#   2g = $1,240 + $1,572 = $2,812.00 (annual)
#   2h = $2,812 / 52 = $54.08  ← $54.076923... rounds to $54.08
#   3c = $54.08 - $0 = $54.08
#   → $54.08
#
# (2) MFJ/Standard/Weekly/$1,200 (hand-computed):
#   1c = $1,200 × 52 = $62,400
#   1g = $12,900 (MFJ standard)
#   1i = $62,400 - $12,900 = $49,500
#   bracket: $44,100–$120,100, base=$2,480, rate=12%
#   2e = $49,500 - $44,100 = $5,400
#   2f = $5,400 × 0.12 = $648.00
#   2g = $2,480 + $648 = $3,128.00 (annual)
#   2h = $3,128 / 52 = $60.15  ← $60.153846... rounds to $60.15
#   3c = $60.15 - $0 = $60.15
#   → $60.15
#
# (3) Single/Standard/Weekly/$1,000 with step_3=$2,000 (annual credit):
#   1c = $1,000 × 52 = $52,000
#   1i = $52,000 - $8,600 = $43,400
#   bracket: $19,900–$57,900, base=$1,240, rate=12%
#   2e = $43,400 - $19,900 = $23,500
#   2f = $23,500 × 0.12 = $2,820.00
#   2g = $1,240 + $2,820 = $4,060.00 (annual)
#   2h = $4,060 / 52 = $78.08  ← $78.076923... rounds to $78.08
#   3b = $2,000 / 52 = $38.46  ← $38.461538... rounds to $38.46
#   3c = $78.08 - $38.46 = $39.62
#   → $39.62
#
# (4) Single/Step2/Weekly/$700:
#   1c = $700 × 52 = $36,400
#   1g = $0 (step_2 checked)
#   1i = $36,400 (no STEP1_STANDARD subtraction)
#   bracket Single/Step2: $33,250–$60,900, base=$2,900, rate=22%
#   2e = $36,400 - $33,250 = $3,150
#   2f = $3,150 × 0.22 = $693.00
#   2g = $2,900 + $693 = $3,593.00 (annual)
#   2h = $3,593 / 52 = $69.10  ← $69.096153... rounds to $69.10
#   3c = $69.10 - $0 = $69.10
#   → $69.10
#
# (5) MFJ/Step2/Weekly/$900:
#   1c = $900 × 52 = $46,800
#   1g = $0 (step_2 checked)
#   1i = $46,800
#   bracket MFJ/Step2: $28,500–$66,500, base=$1,240, rate=12%
#   2e = $46,800 - $28,500 = $18,300
#   2f = $18,300 × 0.12 = $2,196.00
#   2g = $1,240 + $2,196 = $3,436.00 (annual)
#   2h = $3,436 / 52 = $66.08  ← $66.076923... rounds to $66.08
#   3c = $66.08 - $0 = $66.08
#   → $66.08
#
# (6) MFS/Standard/Weekly/$800 (same table as Single):
#   Same computation as case (1) but with filing_status="married_separately"
#   → $54.08 (MFS uses Single/MFS table per IRS rules)
#
# (7) Single/Standard/Biweekly/$2,000 (26 periods):
#   1c = $2,000 × 26 = $52,000
#   1g = $8,600
#   1i = $52,000 - $8,600 = $43,400
#   bracket: $19,900–$57,900, base=$1,240, rate=12%
#   2e = $43,400 - $19,900 = $23,500
#   2f = $23,500 × 0.12 = $2,820.00
#   2g = $1,240 + $2,820 = $4,060.00 (annual)
#   2h = $4,060 / 26 = $156.15  ← $156.153846... rounds to $156.15
#   3c = $156.15 - $0 = $156.15
#   → $156.15
#
# (8) Zero-bracket: Single/Standard/Weekly/$100 (line_1i = $100×52-$8,600 = $1,600 < $7,500, 0% bracket):
#   1c = $100 × 52 = $5,200
#   1i = $5,200 - $8,600 = MAX(0, -$3,400) = $0.00  (floors at $0)
#   bracket: first row (0–$7,500), base=$0, rate=0%
#   → $0.00
#
# (9) Single/Standard/Weekly with step_4a=$5,000:
#   1c = $800 × 52 = $41,600
#   1d = $5,000
#   1e = $46,600
#   1g = $8,600
#   1i = $46,600 - $8,600 = $38,000
#   bracket: $19,900–$57,900, base=$1,240, rate=12%
#   2e = $38,000 - $19,900 = $18,100
#   2f = $18,100 × 0.12 = $2,172.00
#   2g = $1,240 + $2,172 = $3,412.00 (annual)
#   2h = $3,412 / 52 = $65.62  ← $65.615384... rounds to $65.62
#   → $65.62
#
# (10) Single/Standard/Weekly with step_4b=$3,000:
#   1c = $800 × 52 = $41,600
#   1f = $3,000
#   1g = $8,600
#   1h = $3,000 + $8,600 = $11,600
#   1i = $41,600 - $11,600 = $30,000
#   bracket: $19,900–$57,900, base=$1,240, rate=12%
#   2e = $30,000 - $19,900 = $10,100
#   2f = $10,100 × 0.12 = $1,212.00
#   2g = $1,240 + $1,212 = $2,452.00
#   2h = $2,452 / 52 = $47.15  ← $47.153846... rounds to $47.15
#   → $47.15
#
# (11) Single/Standard/Monthly/$4,000 (12 periods):
#   1c = $4,000 × 12 = $48,000
#   1g = $8,600
#   1i = $48,000 - $8,600 = $39,400
#   bracket: $19,900–$57,900, base=$1,240, rate=12%
#   2e = $39,400 - $19,900 = $19,500
#   2f = $19,500 × 0.12 = $2,340.00
#   2g = $1,240 + $2,340 = $3,580.00
#   2h = $3,580 / 12 = $298.33  ← $298.333... rounds to $298.33
#   → $298.33
#
# (12) Single/Standard/Semi-monthly/$2,000 (24 periods):
#   1c = $2,000 × 24 = $48,000
#   1g = $8,600
#   1i = $48,000 - $8,600 = $39,400
#   bracket: $19,900–$57,900, base=$1,240, rate=12%
#   2g = $3,580.00 (same as monthly case above, annualized is same)
#   2h = $3,580 / 24 = $149.17  ← $149.1666... rounds to $149.17
#   → $149.17

@pytest.mark.parametrize("desc,wages_this_period,emp_kwargs,expected_wh", [
    # -----------------------------------------------------------------------
    # Layer-A: hand-computed from RESEARCH.md Deliverable 1
    # -----------------------------------------------------------------------

    # (1) Single/Standard/Weekly/$800 — RESEARCH.md §"Hand-Computation Worked Example"
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

    # (5) MFJ/Step2/Weekly/$900 — covers the MFJ+Step2 schedule gap
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

    # (6) MFS/Standard/Weekly/$800 — uses Single/MFS table (same as case 1)
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

    # (8) Below-threshold: Single/Standard/Weekly/$100 → line_1i floors at $0 → $0.00
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

    # (11) Single/Standard/Monthly/$4,000 (12 periods) — covers monthly frequency
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

    # (12) Single/Standard/Semi-monthly/$2,000 (24 periods) — covers semi-monthly
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

    # (13) Zero wages → zero withholding
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

    # (14) Step-3 floor: large credit exceeds tentative withholding → must return $0.00
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
    emp_kwargs: dict,
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
    """Line 1i floor: wages well below STEP1_STANDARD threshold → $0.00."""
    emp = _make_employee(
        filing_status="married_jointly",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        pay_periods_per_year=52,
    )
    # $50/week × 52 = $2,600 < $12,900 MFJ standard → line_1i floors at $0
    result = federal_withholding_2026(Decimal("50.00"), emp)
    assert result >= Decimal("0.00"), f"Withholding must not be negative: got {result}"
    assert result == Decimal("0.00")


# ---------------------------------------------------------------------------
# Filing-status guard (review Fix 5 — defense-in-depth reject-guard)
# ---------------------------------------------------------------------------

def test_hoh_raises_value_error() -> None:
    """head_of_household must raise ValueError with 'head_of_household' in the message."""
    emp = _make_employee(
        filing_status="single",  # valid at construction
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        pay_periods_per_year=52,
    )
    # Bypass Literal check to simulate a future extension or eval fixture
    import copy
    bad_emp = copy.copy(emp)
    object.__setattr__(bad_emp, "filing_status", "head_of_household")

    with pytest.raises(ValueError, match="head_of_household"):
        federal_withholding_2026(Decimal("800.00"), bad_emp)


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
    import copy
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
    """federal_withholding is a pure function — importable with no DB access."""
    import importlib
    mod = importlib.import_module("app.pipeline.federal_withholding")
    assert hasattr(mod, "federal_withholding_2026")
