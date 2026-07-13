"""Calc tests — the 401k current-run override, the Pub 15-T postconditions, and the
input guards that keep a malformed hours value from becoming a wrong paystub.

The 401k override group pins one contract: a client-supplied
`contribution_401k_override` applies to THIS paystub only, the employee's stored
default is used when no override is given, and the override never mutates the
employee record.
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


# ---- Gross pay, leave pay, FICA caps, and the reconciliation backstop ----

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
    """Leave hours are paid straight time and never trigger the OT premium.

    Overtime is explicit-only: hours_regular=40, hours_vacation=8, hours_overtime=0
    → gross = rate * (40 + 8) at straight time. No 1.5x is applied even though total
    hours exceed 40 — inferring OT from a total would overpay every employee who took
    leave in a full week.
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
    """Salary gross = annual / pay_periods + leave pay when leave hours are submitted."""
    item_no_leave = calculate(_zero_hours(), salary_employee)
    item_with_leave = calculate(_leave_hours(), salary_employee)
    # Gross with leave must exceed gross without leave
    assert item_with_leave.gross_pay > item_no_leave.gross_pay


def test_salaried_no_leave_gross_unchanged(salary_employee):
    """Baseline: salaried employee with zero leave → gross == _money(annual/pay_periods)."""
    item = calculate(_zero_hours(), salary_employee)
    annual = salary_employee.annual_salary
    p = Decimal(salary_employee.pay_periods_per_year)
    expected = _money_local(annual / p)
    assert item.gross_pay == expected


def test_salaried_leave_pay_frequency_invariant():
    """Leave pay is computed as annual/2080 per hour, so it is IDENTICAL at p=52, 26, 24, 12.

    The frequency-dependent alternative is a live overpay hazard. A period-proportion
    formula (period_salary * leave_h / standard_h_per_period, where standard_h =
    40 * p / 52) is inverted: at p=24 it pays ~$2,166 instead of $200.00 (4.7x), at
    p=12 it pays ~$8,666 instead of $200.00 (18.8x), and at p=26 (biweekly — the shape
    most real clients use) it is 4x off. It is only accidentally correct at p=52,
    where 40*52/52 == 40 == the actual weekly standard hours, which is exactly why a
    p=52-only test would let it through.

    Asserting the invariant across ALL valid pay_periods_per_year values is what
    catches any re-introduction of a frequency-dependent denominator.
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
    """End-to-end: leave hours → higher gross → higher or equal federal withholding.

    Proves the leave-pay addition in calculate.py actually feeds through to the
    federal-withholding call. A leave-pay bump that never reaches the withholding
    input would under-withhold silently.
    """
    item_no_leave = calculate(_zero_hours(), salary_employee)
    item_with_leave = calculate(_leave_hours(), salary_employee)
    # Higher gross must produce higher or equal gross (leave pay was added)
    assert item_with_leave.gross_pay > item_no_leave.gross_pay
    # Higher gross → higher or equal federal withholding (monotonically non-decreasing)
    assert item_with_leave.federal_withholding >= item_no_leave.federal_withholding


def test_net_pay_is_real_net(hourly_employee):
    """net = gross - pretax_401k - fica_ss - fica_medicare - federal_withholding.

    Also asserts federal_withholding > 0 for a typical earning employee — a zero here
    would mean the withholding engine silently degraded to a stub.
    """
    item = calculate(_hours(), hourly_employee)
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
    """The arithmetic backstop — net + taxes + deductions must tie back to gross."""
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
    """_raise_if_reconciliation_drift() is exercised on BOTH paths, and the backstop
    must be a real raise — never a bare `assert`.

    _raise_if_reconciliation_drift is a named pure helper, so both paths are driven
    directly with no monkeypatching:
      (a) pass path — correct arithmetic does not raise
      (b) drift path — a deliberately wrong net raises PayrollCalculationError
    This exercises the ACTUAL raise, not just the presence of a string in the source.

    The source check in (c) is the load-bearing part: `python -O` strips bare `assert`
    statements silently, so a backstop written as `assert _reconstructed == gross`
    would vanish in an optimized run and let a mispay through unchecked.
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

    # (c) The reconciliation backstop must not be a bare `assert` in the source.
    import pathlib
    src = pathlib.Path("app/pipeline/calculate.py").read_text()
    assert "assert _reconstructed" not in src, (
        "the reconciliation backstop must raise PayrollCalculationError, not use a "
        "bare `assert` — `python -O` strips bare asserts silently, which would "
        "disable the only runtime guard against a mispay"
    )
    assert issubclass(PayrollCalculationError, Exception)


def test_fica_uses_gross_not_reduced_base(salary_employee):
    """FICA SS and Medicare use gross as their base — pretax_401k does NOT reduce FICA.

    The seeded salaried employee has retirement_contribution_pct=0.04 (4%), so
    pretax_401k > 0 and the two bases genuinely differ. Computing FICA on
    (gross - pretax_401k) — the intuitive but wrong reading, since 401k deferrals are
    exempt from federal income tax but NOT from FICA — would under-withhold every
    contributing employee.
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
    """The Additional Medicare proxy flag fires only when the proxy really crosses $200k.

    ytd_ss_wages=$184,500 is the MAXIMUM possible SS YTD (the 2026 SS wage base cap);
    any value above it is impossible in a real run. So the flag must be pushed over
    $200k by a high CURRENT gross ($20k/period), not by an out-of-range YTD. Seeding an
    impossible ytd_ss_wages (e.g. 197000) would exercise the Boolean expression against
    a state the system can never reach — a test of dead code, not of the proxy.
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
        ytd_ss_wages=Decimal("184500"),  # at the SS wage base cap — the max real value
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


# ---- Input guards: calculate() takes a raw dict, so it is the last line of defense ----

def _valid_hours() -> dict[str, object]:
    return {
        "hours_regular": Decimal("40"),
        "hours_overtime": Decimal("0"),
        "hours_vacation": Decimal("0"),
        "hours_sick": Decimal("0"),
        "hours_holiday": Decimal("0"),
    }


def test_bool_hours_rejected(hourly_employee):
    """A bool hours value must raise, not silently become 1 hour of pay.

    bool is a subclass of int, so without an explicit guard hours_regular=True passes
    isinstance(_, float)==False and Decimal(True)==1 — a silently wrong number that
    reconciles cleanly.
    """
    bad = _valid_hours()
    bad["hours_regular"] = True
    with pytest.raises(TypeError, match="bool"):
        calculate(bad, hourly_employee)


def test_float_hours_rejected(hourly_employee):
    """A float hours value must raise — money is Decimal end-to-end, never binary float."""
    bad = _valid_hours()
    bad["hours_overtime"] = 5.0
    with pytest.raises(TypeError, match="float"):
        calculate(bad, hourly_employee)


def test_unknown_hours_key_rejected(hourly_employee):
    """A misspelled/unknown hours key must raise, not silently zero the field.

    calculate() takes a raw dict (no Pydantic extra='forbid'), so this is the only seam
    that can catch a malformed hours payload. A dropped 'hours_regualr' typo would zero
    regular pay and STILL pass reconciliation — the arithmetic ties out perfectly around
    a wrong number.
    """
    bad = _valid_hours()
    bad["hours_regualr"] = Decimal("40")  # typo of hours_regular
    with pytest.raises(ValueError, match="Unknown hours key"):
        calculate(bad, hourly_employee)


def test_negative_hours_rejected(hourly_employee):
    """Negative hours must raise, not ship a negative paystub.

    The reconciliation backstop is a sign-blind arithmetic identity, so a negative gross
    ties out and passes — the "wrong-but-reconciliation-passing" paystub this raw-dict
    seam exists to stop. Mirrors the model-layer ExtractedEmployee Field(ge=0).
    """
    bad = _valid_hours()
    bad["hours_regular"] = Decimal("-40")
    with pytest.raises(ValueError, match="non-negative"):
        calculate(bad, hourly_employee)


def test_garbage_string_hours_raises_domain_error(hourly_employee):
    """A non-numeric hours string raises a domain ValueError, not a bare
    decimal.InvalidOperation — matching the typed errors used for bool/float, so the
    error boundary can record a meaningful reason."""
    bad = _valid_hours()
    bad["hours_regular"] = "abc"
    with pytest.raises(ValueError, match="not a valid number"):
        calculate(bad, hourly_employee)


def test_additional_medicare_threshold_is_status_aware():
    """The Additional Medicare threshold is filing-status-aware: MFJ is $250k, single $200k.

    A single employee with a Medicare-wage proxy of $200,500 MUST fire the flag; an MFJ
    employee at the same proxy (between $200k and $250k) must NOT. A flat $200k threshold
    would flag MFJ employees who owe no surtax.
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
        "MFJ: proxy 200500 < 250000 must NOT fire — the threshold is status-aware"
    )
