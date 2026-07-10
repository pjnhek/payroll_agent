"""Calc tests — focus on the 401k current-run override (review fix, D-A3-04).

`calculate` was ignoring the client-supplied `contribution_401k_override` and always
using the employee's stored default. These tests pin the corrected behavior: the
override applies to THIS paystub only, the stored default is used when no override is
given, and the override never mutates the employee.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from app.db.seed import seed
from app.pipeline.calculate import calculate

if TYPE_CHECKING:
    from app.models.roster import Employee


@pytest.fixture()
def hourly_employee():
    """A seeded HOURLY employee with a known stored 401k rate."""
    seeded = seed(dry_run=True)
    emp = next(
        e for e in seeded.employees
        if e.pay_type == "hourly" and e.hourly_rate
    )
    return emp


def _hours(regular: str = "40") -> dict[str, object]:
    return {
        "hours_regular": Decimal(regular),
        "hours_overtime": Decimal("0"),
        "hours_vacation": Decimal("0"),
        "hours_sick": Decimal("0"),
        "hours_holiday": Decimal("0"),
    }


def test_uses_stored_default_when_no_override(hourly_employee):
    item = calculate(_hours(), hourly_employee)
    expected = (item.gross_pay * hourly_employee.retirement_contribution_pct).quantize(
        Decimal("0.01")
    )
    assert item.pretax_401k == expected


def test_override_replaces_stored_rate_for_this_run(hourly_employee):
    """A client-supplied override drives pretax_401k, NOT the stored default."""
    override = Decimal("0.10")
    assert override != hourly_employee.retirement_contribution_pct  # meaningful test
    item = calculate(_hours(), hourly_employee, override)
    expected = (item.gross_pay * override).quantize(Decimal("0.01"))
    assert item.pretax_401k == expected


def test_override_does_not_mutate_employee(hourly_employee):
    before = hourly_employee.retirement_contribution_pct
    calculate(_hours(), hourly_employee, Decimal("0.15"))
    assert hourly_employee.retirement_contribution_pct == before


def test_zero_override_is_honored_not_treated_as_absent(hourly_employee):
    """0.0 is a real override (no 401k this run), distinct from None (use default)."""
    item = calculate(_hours(), hourly_employee, Decimal("0"))
    assert item.pretax_401k == Decimal("0.00")


# ---- Phase 3 additions: CALC-01 / CALC-02 / CALC-07 / CALC-08 / Fix-A / R2-3 / R2-6 / Fix-9 ----

import uuid  # noqa: E402 — appended after existing imports; uuid is stdlib

import pytest  # noqa: E402 — already in requirements, safe to re-import

from app.pipeline.calculate import (  # noqa: E402
    PayrollCalculationError,
    _raise_if_reconciliation_drift,
)
from app.pipeline.tax_tables_2026 import (  # noqa: E402
    MEDICARE_RATE as _MEDICARE_RATE_REF,
)
from app.pipeline.tax_tables_2026 import (  # noqa: E402 — appended after existing imports; uuid is stdlib
    SS_RATE as _SS_RATE_REF,
)
from app.pipeline.tax_tables_2026 import (  # noqa: E402 — appended after existing imports; uuid is stdlib
    SS_WAGE_BASE as _SS_WAGE_BASE_REF,
)


@pytest.fixture()
def salary_employee():
    """A seeded SALARY employee (James Okafor, weekly, pay_periods_per_year=52)."""
    seeded = seed(dry_run=True)
    return next(
        e for e in seeded.employees if e.pay_type == "salary" and e.pay_periods_per_year == 52
    )


def _make_salary_employee(
    *,
    annual_salary: Decimal,
    pay_periods_per_year: int,
    filing_status: str = "single",
) -> Employee:
    """Construct a minimal salaried Employee for frequency-invariance tests.

    All W-4 fields default to zero/False. UUIDs are random since identity does
    not matter for pure calc testing.
    """
    from app.models.roster import Employee

    return Employee(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        full_name="SalTest",
        known_aliases=[],
        pay_type="salary",
        hourly_rate=None,
        annual_salary=annual_salary,
        retirement_contribution_pct=Decimal("0"),
        filing_status=filing_status,
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("0"),
        pay_periods_per_year=pay_periods_per_year,
    )


def _zero_hours() -> dict[str, object]:
    """Return a zero-hours dict for use in salaried employee tests."""
    return {
        "hours_regular": Decimal("0"),
        "hours_overtime": Decimal("0"),
        "hours_vacation": Decimal("0"),
        "hours_sick": Decimal("0"),
        "hours_holiday": Decimal("0"),
    }


def _leave_hours() -> dict[str, object]:
    """Return a dict with 8 hours_vacation and all other hours zero."""
    return {
        "hours_regular": Decimal("0"),
        "hours_overtime": Decimal("0"),
        "hours_vacation": Decimal("8"),
        "hours_sick": Decimal("0"),
        "hours_holiday": Decimal("0"),
    }


def _money_local(value: Decimal) -> Decimal:
    """Local ROUND_HALF_UP helper for test-side arithmetic (mirrors calculate.py)."""
    from decimal import ROUND_HALF_UP
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def test_hourly_overtime_at_1_5x(hourly_employee):
    """CALC-01: hours_overtime paid at 1.5x rate; regular hours at straight time."""
    item = calculate(
        {
            "hours_regular": Decimal("40"),
            "hours_overtime": Decimal("5"),
            "hours_vacation": Decimal("0"),
            "hours_sick": Decimal("0"),
            "hours_holiday": Decimal("0"),
        },
        hourly_employee,
    )
    rate = hourly_employee.hourly_rate
    expected_gross = _money_local(rate * Decimal("40") + rate * Decimal("1.5") * Decimal("5"))
    assert item.gross_pay == expected_gross


def test_leave_hours_excluded_from_ot_threshold(hourly_employee):
    """CALC-01 + D-03: leave hours are paid straight time, never trigger OT premium.

    D-03: OT is explicit-only. hours_regular=40, hours_vacation=8, hours_overtime=0
    → gross = rate * (40 + 8) straight time. No 1.5x applied even though total hours > 40.
    """
    item = calculate(
        {
            "hours_regular": Decimal("40"),
            "hours_overtime": Decimal("0"),
            "hours_vacation": Decimal("8"),
            "hours_sick": Decimal("0"),
            "hours_holiday": Decimal("0"),
        },
        hourly_employee,
    )
    rate = hourly_employee.hourly_rate
    # All hours straight time: 40 regular + 8 vacation
    expected_gross = _money_local(rate * Decimal("48"))
    assert item.gross_pay == expected_gross


def test_salaried_leave_pay_added_to_gross(salary_employee):
    """CALC-02: salary gross = annual / pay_periods + leave pay when leave hours are submitted."""
    item_no_leave = calculate(_zero_hours(), salary_employee)
    item_with_leave = calculate(_leave_hours(), salary_employee)
    # Gross with leave must exceed gross without leave
    assert item_with_leave.gross_pay > item_no_leave.gross_pay


def test_salaried_no_leave_gross_unchanged(salary_employee):
    """CALC-02 baseline: salaried employee with zero leave → gross == _money(annual/pay_periods)."""
    item = calculate(_zero_hours(), salary_employee)
    annual = salary_employee.annual_salary
    p = Decimal(salary_employee.pay_periods_per_year)
    expected = _money_local(annual / p)
    assert item.gross_pay == expected


def test_salaried_leave_pay_frequency_invariant():
    """FIX A + R2-6 regression guard: /2080 leave pay is identical at p=52, p=26, p=24, p=12.

    # FIX A + R2-6 regression guard: the prior period-proportion formula (period_salary * leave_h /
    # standard_h_per_period, where standard_h = 40 * p / 52) was INVERTED. For p=24 it produced
    # ~$2,166 instead of $200.00 (4.7x). For p=12 it produced ~$8,666 instead of $200.00 (18.8x).
    # For p=52 it was accidentally correct (40*52/52 = 40 = actual weekly standard hours).
    # R2-6 ADDS p=26 (biweekly): the formula was also wrong at p=26 (40*26/52=20h/period, but
    # the real biweekly standard is 80h/2wks = the /2080 form is also correct at p=26).
    # p=26 was the original reported bug context (4x off) — always include it in the invariant test.
    # This test catches any re-introduction of a frequency-dependent denominator by asserting
    # the invariant: leave_pay is identical across ALL valid pay_periods_per_year values.
    """
    emp_52 = _make_salary_employee(annual_salary=Decimal("52000"), pay_periods_per_year=52)
    emp_26 = _make_salary_employee(annual_salary=Decimal("52000"), pay_periods_per_year=26)
    emp_24 = _make_salary_employee(annual_salary=Decimal("52000"), pay_periods_per_year=24)
    emp_12 = _make_salary_employee(annual_salary=Decimal("52000"), pay_periods_per_year=12)

    delta_52 = (
        calculate(_leave_hours(), emp_52).gross_pay - calculate(_zero_hours(), emp_52).gross_pay
    )
    delta_26 = (
        calculate(_leave_hours(), emp_26).gross_pay - calculate(_zero_hours(), emp_26).gross_pay
    )
    delta_24 = (
        calculate(_leave_hours(), emp_24).gross_pay - calculate(_zero_hours(), emp_24).gross_pay
    )
    delta_12 = (
        calculate(_leave_hours(), emp_12).gross_pay - calculate(_zero_hours(), emp_12).gross_pay
    )

    assert delta_52 == delta_26 == delta_24 == delta_12, (
        f"Leave pay NOT frequency-independent: "
        f"p=52:{delta_52} p=26:{delta_26} p=24:{delta_24} p=12:{delta_12}"
    )
    assert delta_52 == Decimal("200.00"), (
        f"Expected 200.00 (52000/2080*8), got {delta_52}"
    )


def test_salaried_with_leave_gross_integration(salary_employee):
    """Fix 9 — end-to-end integration: leave hours → higher gross → higher or equal withholding.

    Fix 9: the salaried-with-leave integration case is tested here in test_calculate.py
    (not test_federal_withholding.py) per the plan wave-ordering note. This proves that
    the leave pay addition in calculate.py correctly feeds through to the federal
    withholding call — higher gross → higher or equal federal withholding.
    """
    item_no_leave = calculate(_zero_hours(), salary_employee)
    item_with_leave = calculate(_leave_hours(), salary_employee)
    # Higher gross must produce higher or equal gross (leave pay was added)
    assert item_with_leave.gross_pay > item_no_leave.gross_pay
    # Higher gross → higher or equal federal withholding (monotonically non-decreasing)
    assert item_with_leave.federal_withholding >= item_no_leave.federal_withholding


def test_net_pay_is_real_net(hourly_employee):
    """CALC-07: net = gross - pretax_401k - fica_ss - fica_medicare - federal_withholding.

    Also asserts that federal_withholding > 0 for a typical earning employee
    (Phase 3 postcondition).
    """
    item = calculate(_hours(), hourly_employee)
    # Federal withholding must be real in Phase 3
    assert item.federal_withholding > Decimal("0"), (
        f"federal_withholding should be > 0 for a typical employee, got {item.federal_withholding}"
    )
    expected_net = _money_local(
        item.gross_pay
        - item.pretax_401k
        - item.fica_ss
        - item.fica_medicare
        - item.federal_withholding
    )
    assert item.net_pay == expected_net, (
        f"net_pay {item.net_pay} != expected {expected_net}"
    )


def test_reconciliation_identity(hourly_employee):
    """CALC-08: arithmetic backstop — net + taxes + deductions ties back to gross."""
    item = calculate(_hours(), hourly_employee)
    reconstructed = _money_local(
        item.net_pay
        + item.pretax_401k
        + item.fica_ss
        + item.fica_medicare
        + item.federal_withholding
        + (item.state_withholding or Decimal("0"))
    )
    assert reconstructed == item.gross_pay, (
        f"Reconciliation failed: {reconstructed} != {item.gross_pay}"
    )


def test_reconciliation_raises_on_drift():
    """R2-3: _raise_if_reconciliation_drift() directly tests both pass and drift paths.

    # R2-3: _raise_if_reconciliation_drift() is a named pure helper (no monkeypatching needed).
    # Both paths are tested directly:
    # (a) pass path — correct arithmetic does not raise
    # (b) drift path — deliberately wrong net triggers pytest.raises(PayrollCalculationError)
    # This exercises the ACTUAL raise, not just a string in source code.
    # FIX C secondary check: source grep confirms no bare 'assert _reconstructed' remains.
    """
    # (a) Passing path — consistent values must NOT raise
    gross = Decimal("1000.00")
    pretax_401k = Decimal("40.00")
    fica_ss = Decimal("62.00")
    fica_medicare = Decimal("14.50")
    federal_wh = Decimal("54.08")
    net = gross - pretax_401k - fica_ss - fica_medicare - federal_wh  # correct net = 829.42
    _raise_if_reconciliation_drift(gross, pretax_401k, fica_ss, fica_medicare, federal_wh, net)
    # No exception raised — passes by reaching this line

    # (b) Drift path — deliberately wrong net MUST raise PayrollCalculationError
    with pytest.raises(PayrollCalculationError):
        _raise_if_reconciliation_drift(
            Decimal("1000.00"),
            Decimal("40.00"),
            Decimal("62.00"),
            Decimal("14.50"),
            Decimal("54.08"),
            Decimal("999.99"),  # deliberately wrong net — drift of ~$170.57
        )

    # (c) Secondary FIX C source-grep check: no bare 'assert _reconstructed' in source
    import pathlib
    src = pathlib.Path("app/pipeline/calculate.py").read_text()
    assert "assert _reconstructed" not in src, (
        "FIX C: bare assert must not remain in calculate.py source "
        "(python -O strips bare asserts silently)"
    )
    assert issubclass(PayrollCalculationError, Exception)


def test_fica_uses_gross_not_reduced_base(salary_employee):
    """CALC-03: FICA SS and Medicare use gross as base — pretax_401k does NOT reduce FICA.

    James Okafor has retirement_contribution_pct=0.04 (4%), so pretax_401k > 0.
    FICA must be computed on gross, not (gross - pretax_401k).
    """
    item = calculate(_zero_hours(), salary_employee)
    remaining_cap = _SS_WAGE_BASE_REF - salary_employee.ytd_ss_wages
    if remaining_cap < Decimal("0"):
        remaining_cap = Decimal("0")
    expected_fica_ss = _money_local(min(item.gross_pay, remaining_cap) * _SS_RATE_REF)
    expected_fica_medicare = _money_local(item.gross_pay * _MEDICARE_RATE_REF)
    # Both use gross_pay, not (gross_pay - pretax_401k)
    assert item.fica_ss == expected_fica_ss, (
        f"fica_ss {item.fica_ss} != {expected_fica_ss} — FICA must use gross, not gross-401k"
    )
    assert item.fica_medicare == expected_fica_medicare, (
        f"fica_medicare {item.fica_medicare} != {expected_fica_medicare} — Medicare must use gross"
    )


def test_additional_medicare_flag_present():
    """User Decision 1 + FIX B + R2-2: Additional Medicare proxy flag.

    # R2-2: ytd_ss_wages=$184,500 is the MAXIMUM possible SS YTD (2026 SS wage base cap).
    # Values above $184,500 are IMPOSSIBLE in a real run. A high current gross ($20k/period)
    # is used to push (ytd + gross) above $200k, testing the real proxy semantics.
    # The prior plan used ytd_ss_wages=197000 (impossible — above the cap). That tested
    # the Boolean expression without testing the real proxy: an employee can NEVER have
    # ytd_ss_wages=197000 in a real run, so the test was exercising dead code.
    """
    from app.models.roster import Employee

    # Flag-fires case: ytd_ss_wages=184500 (at SS cap — max real value)
    # + gross=$20,000 → $204,500 > $200k
    emp_at_cap = Employee(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        full_name="AtCap",
        known_aliases=[],
        pay_type="hourly",
        hourly_rate=Decimal("500.00"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("184500"),  # at SS wage base cap — maximum realistic value (R2-2)
        pay_periods_per_year=52,
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
    # 184500 + 20000 = 204500 > 200000 — MUST fire
    assert item_cap.additional_medicare_not_modeled is True, (
        f"Flag must fire when (ytd_ss_wages={emp_at_cap.ytd_ss_wages} + "
        f"gross={item_cap.gross_pay}) > 200000"
    )

    # Flag-does-not-fire case: ytd_ss_wages=0, normal gross ($4,000) → $4,000 << $200k
    emp_normal = Employee(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        full_name="Normal",
        known_aliases=[],
        pay_type="hourly",
        hourly_rate=Decimal("100.00"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("0"),
        pay_periods_per_year=52,
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
    # 0 + 4000 = 4000 << 200000 — must NOT fire
    assert item_normal.additional_medicare_not_modeled is False, (
        "Flag must not fire for a normal employee with low YTD and normal gross"
    )


# ---- Code review round 2: input-guard hardening (WR-01 bool, WR-02 unknown keys, WR-03) ----

def _valid_hours() -> dict[str, object]:
    return {
        "hours_regular": Decimal("40"),
        "hours_overtime": Decimal("0"),
        "hours_vacation": Decimal("0"),
        "hours_sick": Decimal("0"),
        "hours_holiday": Decimal("0"),
    }


def test_bool_hours_rejected(hourly_employee):
    """WR-01: a bool hours value must raise, not silently become 1 hour of pay.

    bool is a subclass of int, so without an explicit guard hours_regular=True would
    pass isinstance(_, float)==False and Decimal(True)==1 — a silent wrong number.
    """
    bad = _valid_hours()
    bad["hours_regular"] = True
    with pytest.raises(TypeError, match="bool"):
        calculate(bad, hourly_employee)


def test_float_hours_rejected(hourly_employee):
    """Round-1 WR-02: a float hours value must raise (D-05 Decimal-everywhere)."""
    bad = _valid_hours()
    bad["hours_overtime"] = 5.0
    with pytest.raises(TypeError, match="float"):
        calculate(bad, hourly_employee)


def test_unknown_hours_key_rejected(hourly_employee):
    """WR-02: a misspelled/unknown hours key must raise, not silently zero the field.

    calculate() takes a raw dict (no Pydantic extra='forbid'), so this is the only seam
    that can catch a malformed hours payload. A dropped 'hours_regualr' typo would zero
    regular pay and still pass reconciliation — exactly the silent wrong number to prevent.
    """
    bad = _valid_hours()
    bad["hours_regualr"] = Decimal("40")  # typo of hours_regular
    with pytest.raises(ValueError, match="Unknown hours key"):
        calculate(bad, hourly_employee)


def test_negative_hours_rejected(hourly_employee):
    """WR-01 (round 3): negative hours must raise, not ship a negative paystub.

    The reconciliation backstop is a sign-blind arithmetic identity, so a negative gross
    ties out and would pass — exactly the "wrong-but-reconciliation-passing" paystub the
    raw-dict seam documents itself as the last-line defense against. Mirrors the model-layer
    ExtractedEmployee Field(ge=0).
    """
    bad = _valid_hours()
    bad["hours_regular"] = Decimal("-40")
    with pytest.raises(ValueError, match="non-negative"):
        calculate(bad, hourly_employee)


def test_garbage_string_hours_raises_domain_error(hourly_employee):
    """IN-01 (round 3): a non-numeric hours string raises a domain ValueError, not a
    bare decimal.InvalidOperation, matching the typed errors used for bool/float."""
    bad = _valid_hours()
    bad["hours_regular"] = "abc"
    with pytest.raises(ValueError, match="not a valid number"):
        calculate(bad, hourly_employee)


def test_additional_medicare_threshold_is_status_aware():
    """WR-03: MFJ threshold ($250k) differs from single ($200k); flag must respect status.

    A single employee with a Medicare-wage proxy of $200,500 MUST fire the flag; an MFJ
    employee at the same proxy (between $200k and $250k) must NOT — proving the threshold
    is filing-status-aware rather than a flat $200k.
    """
    from app.models.roster import Employee

    def mk(status: str) -> Employee:
        return Employee(
            id=uuid.uuid4(), business_id=uuid.uuid4(), full_name="T", known_aliases=[],
            pay_type="hourly", hourly_rate=Decimal("500.00"), annual_salary=None,
            retirement_contribution_pct=Decimal("0"),
            filing_status=status, step_2_checkbox=False,
            step_3_dependents=Decimal("0"), step_4a_other_income=Decimal("0"),
            step_4b_deductions=Decimal("0"),
            ytd_ss_wages=Decimal("180000"), pay_periods_per_year=52,
        )
    hrs = _valid_hours()
    hrs["hours_regular"] = Decimal("41")  # gross 20500 -> proxy 180000+20500 = 200500
    single_item = calculate(hrs, mk("single"))
    mfj_item = calculate(hrs, mk("married_jointly"))
    assert single_item.additional_medicare_not_modeled is True, (
        "single: proxy 200500 > 200000 must fire"
    )
    assert mfj_item.additional_medicare_not_modeled is False, (
        "MFJ: proxy 200500 < 250000 must NOT fire (status-aware threshold, WR-03)"
    )
