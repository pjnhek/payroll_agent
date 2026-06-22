"""Calc tests — focus on the 401k current-run override (review fix, D-A3-04).

`calculate` was ignoring the client-supplied `contribution_401k_override` and always
using the employee's stored default. These tests pin the corrected behavior: the
override applies to THIS paystub only, the stored default is used when no override is
given, and the override never mutates the employee.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.db.seed import seed
from app.pipeline.calculate import calculate


@pytest.fixture()
def hourly_employee():
    """A seeded HOURLY employee with a known stored 401k rate."""
    seeded = seed(dry_run=True)
    emp = next(
        e for e in seeded.employees
        if e.pay_type == "hourly" and e.hourly_rate
    )
    return emp


def _hours(regular="40"):
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
