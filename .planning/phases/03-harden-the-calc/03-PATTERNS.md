# Phase 3: Harden the Calc - Pattern Map

**Mapped:** 2026-06-22
**Files analyzed:** 5 (2 new, 2 modified + 1 synthetic fixture set)
**Analogs found:** 5 / 5

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `app/pipeline/tax_tables_2026.py` | config/constants | transform (data-in-none, constants-out) | `app/pipeline/calculate.py` inline `_SS_RATE`/`_SS_WAGE_BASE`/`_MEDICARE_RATE` | partial-match (same domain, constants extracted out) |
| `app/pipeline/federal_withholding.py` | utility/pure-function | transform (typed-in → Decimal out) | `app/pipeline/calculate.py` | exact (same pure-function, Decimal+ROUND_HALF_UP pattern) |
| `tests/test_federal_withholding.py` | test | batch/parametrize | `tests/test_calculate.py` | exact (same Decimal-assertion + Employee-fixture pattern) |
| Synthetic `Employee` fixtures | test-fixture | N/A | `app/db/seed.py` `Employee(...)` construction blocks | exact (same Pydantic constructor pattern) |
| `app/pipeline/calculate.py` (modified) | utility/pure-function | transform (typed-in → PaystubLineItem out) | itself (deepening, not replacement) | self-analog |
| `tests/test_calculate.py` (extended) | test | request-response | itself (extension, not replacement) | self-analog |

---

## Pattern Assignments

---

### `app/pipeline/tax_tables_2026.py` (config/constants, no data flow)

**Analog:** `app/pipeline/calculate.py` (lines 41–43) — the three inline FICA constants being migrated OUT of this file

**Imports pattern** (`calculate.py` lines 24–32 — replicate for the constants module):
```python
from __future__ import annotations

from decimal import Decimal
```
No other imports needed — the constants module is stdlib-only (`decimal`). Optionally add `from typing import NamedTuple` for the `BracketRow` typed structure.

**Existing inline constants being migrated** (`calculate.py` lines 41–43 — EXACT text the executor moves):
```python
_SS_RATE = Decimal("0.062")
_SS_WAGE_BASE = Decimal("184500")
_MEDICARE_RATE = Decimal("0.0145")
```
These three names move verbatim into `tax_tables_2026.py` as module-level public names (drop the leading underscore to make them importable: `SS_RATE`, `SS_WAGE_BASE`, `MEDICARE_RATE`). Values do not change.

**Module-level docstring pattern** (from `calculate.py` lines 1–23 — replicate the block-comment convention, not the content):
```python
"""2026 Federal Tax Constants for Payroll Engine.

Sources:
  IRS Publication 15-T (2026): https://www.irs.gov/pub/irs-pdf/p15t.pdf
  SSA Contribution and Benefit Base: https://www.ssa.gov/oact/cola/cbb.html
Retrieved: 2026-06-22

OBBBA note: The 2026 edition of Pub 15-T incorporates P.L. 119-21 (OBBBA) changes
(permanent extension of individual tax rates, increased standard deduction, no personal
exemptions). ONLY the standard percentage method is implemented here; the OBBBA
qualified-tips and qualified-overtime deductions are disclaimed and NOT modeled.
"""
```
The dated source-URL header is a CALC-06 deliverable, not optional.

**Year-keying pattern** (planner's call on exact shape, but must be additive — adding 2027 must not touch 2026 constants):
```python
TAX_YEAR = 2026

# FICA constants (migrated from calculate.py per D-02)
SS_RATE       = Decimal("0.062")
SS_WAGE_BASE  = Decimal("184500")   # SSA 2026 Contribution and Benefit Base
MEDICARE_RATE = Decimal("0.0145")

# Pub 15-T Worksheet 1A — standard deduction proxy amounts (Line 1g)
# Source: irs.gov/pub/irs-pdf/p15t.pdf page 10, retrieved 2026-06-22
STEP1_STANDARD: dict[str, Decimal] = {
    "married_jointly":     Decimal("12900"),
    "single":              Decimal("8600"),
    "married_separately":  Decimal("8600"),
}

# Bracket tables: BracketRow(lower, upper, base, rate)
# upper=None means "no upper bound" (top bracket)
class BracketRow(NamedTuple):
    lower: Decimal   # column A (at least)
    upper: Decimal | None  # column B (but less than); None for top bracket
    base:  Decimal   # column C (tentative base withholding)
    rate:  Decimal   # column D as fraction (e.g. Decimal("0.12") for 12%)

STANDARD_BRACKETS: dict[str, list[BracketRow]] = {
    "married_jointly":    [...],   # 8 rows from RESEARCH.md Deliverable 1, Table 1A.1
    "single":             [...],   # 8 rows from RESEARCH.md Deliverable 1, Table 1A.1
    "married_separately": [...],   # same as "single" — MFS uses Single/MFS table
}

STEP2_BRACKETS: dict[str, list[BracketRow]] = {
    "married_jointly":    [...],   # 8 rows from RESEARCH.md Deliverable 1, Table 1A.2
    "single":             [...],   # 8 rows from RESEARCH.md Deliverable 1, Table 1A.2
    "married_separately": [...],   # same as "single" — MFS uses Single/MFS Step-2 table
}
```
All bracket numbers come from RESEARCH.md Mandatory Deliverable 1 (transcribed from `irs.gov/pub/irs-pdf/p15t.pdf`, 2026-06-22). Do NOT derive from memory or training data.

---

### `app/pipeline/federal_withholding.py` (utility/pure-function, transform)

**Analog:** `app/pipeline/calculate.py` (entire file, 145 lines) — the only existing pure-function pipeline module

**Imports pattern** (`calculate.py` lines 24–32 — near-exact replication):
```python
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.models.roster import Employee
from app.pipeline.tax_tables_2026 import (
    STANDARD_BRACKETS,
    STEP2_BRACKETS,
    STEP1_STANDARD,
    TAX_YEAR,
)
```
Note: no `uuid`, no `datetime`, no `contracts` import — the withholding function takes `Decimal` + `Employee` and returns `Decimal`. It does not construct a `PaystubLineItem`.

**`_money()` helper pattern** (`calculate.py` lines 48–58 — COPY VERBATIM, same sentinel `_CENTS`):
```python
_CENTS = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    """Round a Decimal to cents using ROUND_HALF_UP (round half AWAY from zero).

    WR-06: this is standard payroll rounding, NOT banker's rounding. Banker's rounding
    is ROUND_HALF_EVEN (round half to the nearest even cent); ROUND_HALF_UP always
    rounds a halfway value up in magnitude. The behavior is deliberately UNCHANGED
    here — ROUND_HALF_UP is the defensible payroll convention and every calc/FICA test
    is pinned to it.
    """
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)
```
The `_money()` helper in `federal_withholding.py` is a LOCAL copy, not an import from `calculate.py` — keeping the modules independently importable by the eval (D-14).

**Pure-function signature convention** (`calculate.py` lines 73–86 — replication pattern for typed-in/typed-out):
```python
# calculate.py pattern:
def calculate(
    resolved_hours: dict,
    employee: Employee,
    contribution_401k_override: Decimal | None = None,
) -> PaystubLineItem:
```
The `federal_withholding_2026` function follows the same convention — typed inputs, typed return, no side effects, no DB/conn:
```python
def federal_withholding_2026(
    federal_taxable_wages_this_period: Decimal,
    employee: Employee,
) -> Decimal:
    """Compute per-period federal withholding via Worksheet 1A (Pub 15-T 2026).

    federal_taxable_wages_this_period: gross - pretax_401k (NOT raw gross).
    Returns per-period withholding in Decimal cents (ROUND_HALF_UP).
    Never returns a negative number (line 3c and line 1i both floor at $0).
    """
```

**How `calculate.py` reads `Employee` fields** (`calculate.py` lines 89–101 — naming pattern to replicate):
```python
# Hourly branch:
rate = employee.hourly_rate or Decimal("0")

# Salary branch:
annual = employee.annual_salary or Decimal("0")
gross = annual / Decimal(employee.pay_periods_per_year)

# 401k:
rate_401k = (
    contribution_401k_override
    if contribution_401k_override is not None
    else employee.retirement_contribution_pct
)

# FICA — uses employee.ytd_ss_wages directly:
remaining_cap = _SS_WAGE_BASE - employee.ytd_ss_wages
```
The withholding engine reads these `Employee` fields — confirmed exact names from `app/models/roster.py`:
- `employee.filing_status` — `Literal["single", "married_jointly", "married_separately"]`
- `employee.step_2_checkbox` — `bool`
- `employee.step_3_dependents` — `Decimal`, `ge=0`
- `employee.step_4a_other_income` — `Decimal`, `ge=0`
- `employee.step_4b_deductions` — `Decimal`, `ge=0`
- `employee.pay_periods_per_year` — `Literal[12, 24, 26, 52]`
- (NOT `employee.ytd_ss_wages` — that's FICA-only, stays in `calculate.py`)

**Filing-status table mapping** (critical — `married_separately` uses the Single/MFS table, NOT the MFJ table):
```python
# Both "single" and "married_separately" map to the same bracket tables:
brackets = STEP2_BRACKETS[status] if checkbox else STANDARD_BRACKETS[status]
# The dict keys must include "married_separately" pointing to the Single/MFS rows.
```

**Bracket lookup helper** (`calculate.py` has no equivalent — new private function):
```python
def _find_bracket(annual_wage: Decimal, brackets: list) -> "BracketRow":
    """Linear scan of 8 bracket rows (O(n), no performance concern)."""
    for row in reversed(brackets):
        if annual_wage >= row.lower:
            return row
    return brackets[0]  # zero-bracket fallback for annual_wage < first lower bound
```

---

### `tests/test_federal_withholding.py` (test, batch/parametrize)

**Analog:** `tests/test_calculate.py` (entire file, 66 lines) — the existing golden-value calc test

**File header / docstring pattern** (`test_calculate.py` lines 1–7 — replicate with golden-oracle sourcing note):
```python
"""Golden-value tests for the Pub 15-T 2026 Worksheet 1A federal withholding engine.

ALL expected values were hand-computed from the 2026 Pub 15-T bracket tables
(RESEARCH.md Deliverable 1, sourced from irs.gov/pub/irs-pdf/p15t.pdf, retrieved 2026-06-22)
and cross-checked against usapaycheck.org and paycheckcity.com before being written here.
NO expected value was derived from the tax_tables_2026.py module under test.
"""
```

**Imports pattern** (`test_calculate.py` lines 1–16 — adapt):
```python
from __future__ import annotations

from decimal import Decimal

import pytest

from app.pipeline.federal_withholding import federal_withholding_2026
# Seeded employees for layer-B fixtures:
from app.db.seed import seed
```
No `conftest.py` fixtures needed — the golden suite constructs its own `Employee` instances inline or via a local `make_employee()` helper (see synthetic fixtures section below).

**`_hours()` helper pattern** (`test_calculate.py` lines 29–36 — project convention for hour dicts in tests):
```python
def _hours(regular="40"):
    return {
        "hours_regular": Decimal(regular),
        "hours_overtime": Decimal("0"),
        "hours_vacation": Decimal("0"),
        "hours_sick": Decimal("0"),
        "hours_holiday": Decimal("0"),
    }
```
The golden withholding tests do NOT need `_hours()` (the withholding function takes `federal_taxable_wages_this_period: Decimal` directly). But the CALC-01/02 extensions to `test_calculate.py` DO use it — do not remove it.

**pytest fixture pattern** (`test_calculate.py` lines 18–26 — reuse the seeded-employee fixture approach):
```python
@pytest.fixture()
def hourly_employee():
    """A seeded HOURLY employee with a known stored 401k rate."""
    seeded = seed(dry_run=True)
    emp = next(
        e for e in seeded.employees
        if e.pay_type == "hourly" and e.hourly_rate
    )
    return emp
```
For layer-B seeded fixtures in the withholding suite, fetch specific employees by known field values (filing_status, step_2_checkbox) rather than index — the seed order is stable (7 employees, fixed UUIDs) but matching by field is more robust.

**`@pytest.mark.parametrize` golden-value pattern** (replicate the exact assertion style from `test_calculate.py` lines 47–54 and extend it):

`test_calculate.py` uses simple per-test functions with single-value assertions:
```python
def test_override_replaces_stored_rate_for_this_run(hourly_employee):
    override = Decimal("0.10")
    assert override != hourly_employee.retirement_contribution_pct  # meaningful test
    item = calculate(_hours(), hourly_employee, override)
    expected = (item.gross_pay * override).quantize(Decimal("0.01"))
    assert item.pretax_401k == expected
```

For the golden withholding suite use `@pytest.mark.parametrize` with a table-driven shape — the most concise form for a matrix of 15+ cases:
```python
@pytest.mark.parametrize("desc,wages_this_period,emp_kwargs,expected_wh", [
    # --- Layer-A: hand-computed from RESEARCH.md Deliverable 1 ---
    # Single/Standard/Weekly, $800 wages (hand-computed example from RESEARCH.md):
    ("single_std_weekly_800", Decimal("800.00"), {
        "filing_status": "single", "step_2_checkbox": False,
        "step_3_dependents": Decimal("0"), "step_4a_other_income": Decimal("0"),
        "step_4b_deductions": Decimal("0"), "pay_periods_per_year": 52,
    }, Decimal("54.08")),

    # Edge case: credit exceeds tentative → floor at $0.00
    ("step3_floor_at_zero", Decimal("150.00"), {
        "filing_status": "single", "step_2_checkbox": False,
        "step_3_dependents": Decimal("5000.00"),
        "step_4a_other_income": Decimal("0"), "step_4b_deductions": Decimal("0"),
        "pay_periods_per_year": 52,
    }, Decimal("0.00")),
    # ... (planner fills all D-04 cases using hand-computation + layer-B cross-check)
])
def test_federal_withholding_golden(desc, wages_this_period, emp_kwargs, expected_wh):
    emp = _make_employee(**emp_kwargs)
    result = federal_withholding_2026(wages_this_period, emp)
    assert result == expected_wh, (
        f"[{desc}] expected {expected_wh}, got {result}. "
        "Re-verify hand computation and layer-B cross-check before changing the expected value."
    )
```

**Decimal assertion style** — always compare `Decimal` to `Decimal` directly (`assert result == Decimal("54.08")`), never to a float. This is the existing pattern in `test_calculate.py` lines 42–44:
```python
expected = (item.gross_pay * hourly_employee.retirement_contribution_pct).quantize(
    Decimal("0.01")
)
assert item.pretax_401k == expected
```

---

### Synthetic `Employee` Fixtures (test-fixture, for `test_federal_withholding.py`)

**Analog:** `app/db/seed.py` `Employee(...)` construction blocks (lines 79–261) — the only place `Employee` objects are constructed in the project

**Seeded employee construction pattern** (`seed.py` lines 79–95 — replicate exactly):
```python
Employee(
    id=uuid.UUID("e0000001-0000-0000-0000-000000000001"),
    business_id=uuid.UUID("b0000001-0000-0000-0000-000000000001"),
    full_name="Maria Chen",
    known_aliases=["Maria", "M. Chen"],
    pay_type="hourly",
    hourly_rate=Decimal("18.50"),
    annual_salary=None,
    retirement_contribution_pct=Decimal("0.00"),
    filing_status="single",
    step_2_checkbox=False,
    step_3_dependents=Decimal("0"),
    step_4a_other_income=Decimal("0"),
    step_4b_deductions=Decimal("0"),
    ytd_ss_wages=Decimal("12000.00"),
    pay_periods_per_year=52,
)
```
Every field is positional-keyword. `Employee` is `extra="forbid"` (`app/models/roster.py` line 34), so every field must be passed — no kwargs omission is safe. The `@model_validator` on lines 75–107 enforces `pay_type ↔ compensation field` invariant at construction time.

**`_make_employee()` helper for the test module** (inline factory, NOT a conftest fixture — keeps golden tests self-contained):
```python
import uuid
from decimal import Decimal
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

    Defaults: hourly @ $100/hr, no YTD SS wages, no 401k — override only the fields
    relevant to the specific test case. UUIDs are random (uuid4) since identity does
    not matter for pure withholding calculation.
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
```

**Minimum synthetic fixtures required** (from RESEARCH.md "Seed Employee Coverage"):
- **MFJ + Step-2 checkbox** — no seeded employee covers this schedule. Construct with `filing_status="married_jointly", step_2_checkbox=True`.
- **Semi-monthly (24) or monthly (12) frequency** — seeded employees cover only 52 and 26. Construct with `pay_periods_per_year=24` or `pay_periods_per_year=12`.

All `Employee` field names confirmed from `app/models/roster.py` lines 57–70:
```python
filing_status: Literal["single", "married_jointly", "married_separately"]
step_2_checkbox: bool
step_3_dependents: Decimal = Field(ge=0)
step_4a_other_income: Decimal = Field(ge=0)
step_4b_deductions: Decimal = Field(ge=0)
ytd_ss_wages: Decimal = Field(ge=0)
pay_periods_per_year: Literal[12, 24, 26, 52]
retirement_contribution_pct: Decimal = Field(ge=0, le=1)
```

---

### `app/pipeline/calculate.py` (modified — exact current lines for in-place editing)

**Analog:** itself — the executor edits this file in place. These are the EXACT current lines that change.

**Line 1 — module docstring first line** (current — retire after Phase 3):
```python
"""Thin payroll calc — gross + FICA only, net labeled "pre-federal" (D-A6-01).
```
Replace with a Phase 3 docstring removing "thin", "pre-federal", and the D-A6-01 reference.

**Lines 33–38 — `PRE_FEDERAL_NET_LABEL` constant** (current — retire entirely):
```python
# FIX 2: the human-readable "pre-federal" label (NOT a PaystubLineItem field).
# The README and run rendering reuse this exact wording so the disclaimer and the
# computed value always agree.
PRE_FEDERAL_NET_LABEL = (
    "Net pay (pre-federal — real federal withholding lands in Phase 3)"
)
```
Remove this block. Also remove any README reference to `PRE_FEDERAL_NET_LABEL`.

**Lines 41–43 — inline FICA constants** (current — migrate out to `tax_tables_2026.py`):
```python
_SS_RATE = Decimal("0.062")
_SS_WAGE_BASE = Decimal("184500")
_MEDICARE_RATE = Decimal("0.0145")
```
Replace with import from the new constants module:
```python
from app.pipeline.tax_tables_2026 import SS_RATE as _SS_RATE, SS_WAGE_BASE as _SS_WAGE_BASE, MEDICARE_RATE as _MEDICARE_RATE
```
Or rename the usages in the function body — either way, existing tests that assert FICA output values must stay green (the VALUES do not change, only where they live).

**Lines 99–101 — salary gross (salaried, no leave pay)** (current — Phase 3 adds CALC-02):
```python
    else:  # salary
        annual = employee.annual_salary or Decimal("0")
        gross = annual / Decimal(employee.pay_periods_per_year)
```
Phase 3 adds leave pay for salaried employees. The leave pay formula (`annual / pay_periods × leave_hours / standard_hours_per_period`, using existing `hours["hours_vacation"] + hours["hours_sick"] + hours["hours_holiday"]`) is the planner's call per RESEARCH.md open question #2.

**Lines 122–124 — `federal_withholding = Decimal("0")` and net** (current — THE key Phase 3 replacement):
```python
    # Phase 2: NO federal withholding (no fabricated figure). The pre-federal net.
    federal_withholding = Decimal("0")
    net_pay = _money(gross - pretax_401k - fica_ss - fica_medicare)
```
Replace with:
```python
    # Phase 3: real IRS Pub 15-T 2026 federal withholding.
    federal_taxable = _money(gross - pretax_401k)  # 401k reduces federal base, NOT FICA base
    federal_withholding = federal_withholding_2026(federal_taxable, employee)
    net_pay = _money(gross - pretax_401k - fica_ss - fica_medicare - federal_withholding)
```
This requires adding `from app.pipeline.federal_withholding import federal_withholding_2026` to the imports at the top of `calculate.py`.

**Lines 105–112 — 401k / FICA base interaction** (current — FICA base is correctly `gross`, not `gross - pretax_401k`):
```python
    # FICA — SS honors the remaining wage-base cap; Medicare has no cap.
    remaining_cap = _SS_WAGE_BASE - employee.ytd_ss_wages
    if remaining_cap < 0:
        remaining_cap = Decimal("0")
    ss_taxable = min(gross, remaining_cap)
    fica_ss = _money(ss_taxable * _SS_RATE)
    fica_medicare = _money(gross * _MEDICARE_RATE)
```
This block is CORRECT and does NOT change — FICA base is `gross` (not reduced by 401k). This must remain unchanged in Phase 3. The phase's 401k handling only affects `federal_withholding_2026(federal_taxable, ...)` where `federal_taxable = gross - pretax_401k`.

**Lines 73–86 — function signature** (current — `contribution_401k_override` param stays):
```python
def calculate(
    resolved_hours: dict,
    employee: Employee,
    contribution_401k_override: Decimal | None = None,
) -> PaystubLineItem:
```
Signature does not change. The `contribution_401k_override` override stays (D-A3-04).

---

### `tests/test_calculate.py` (extended — existing tests must stay green)

**Analog:** itself — extension only, the four existing tests are untouched

**Existing tests that must stay green** (lines 39–66, all four):
```python
def test_uses_stored_default_when_no_override(hourly_employee): ...
def test_override_replaces_stored_rate_for_this_run(hourly_employee): ...
def test_override_does_not_mutate_employee(hourly_employee): ...
def test_zero_override_is_honored_not_treated_as_absent(hourly_employee): ...
```
All four assert `item.pretax_401k` behavior. They will continue to pass because:
1. `pretax_401k` computation does not change in Phase 3.
2. The FICA constants migration (values unchanged) does not affect these assertions.

**Extension pattern — new tests go below the existing four** (CALC-01, CALC-02, CALC-07, CALC-08):

CALC-01 (hourly OT at 1.5× with explicit hours_overtime):
```python
def test_hourly_overtime_at_1_5x(hourly_employee):
    """CALC-01: hours_overtime at 1.5x, leave hours at straight time."""
    item = calculate({
        "hours_regular": Decimal("40"),
        "hours_overtime": Decimal("5"),
        "hours_vacation": Decimal("0"),
        "hours_sick": Decimal("0"),
        "hours_holiday": Decimal("0"),
    }, hourly_employee)
    rate = hourly_employee.hourly_rate
    expected_gross = _money(rate * Decimal("40") + rate * Decimal("1.5") * Decimal("5"))
    assert item.gross_pay == expected_gross
```

CALC-02 (salaried leave pay):
```python
def test_salaried_leave_pay_added_to_gross():
    """CALC-02: salary gross = annual / pay_periods + leave pay."""
    # Uses a salary employee from seed — James Okafor (e2) or Priya Nair (e4)
    seeded = seed(dry_run=True)
    emp = next(e for e in seeded.employees if e.pay_type == "salary")
    item_no_leave = calculate(_hours("0"), emp)
    item_with_leave = calculate({
        "hours_regular": Decimal("0"),
        "hours_overtime": Decimal("0"),
        "hours_vacation": Decimal("8"),  # 8 hours vacation
        "hours_sick": Decimal("0"),
        "hours_holiday": Decimal("0"),
    }, emp)
    # Gross with leave must exceed gross without leave
    assert item_with_leave.gross_pay > item_no_leave.gross_pay
```

CALC-07 (net = gross - pretax - FICA - federal):
```python
def test_net_pay_is_real_net(hourly_employee):
    """CALC-07: net = gross - pretax_401k - fica_ss - fica_medicare - federal_withholding."""
    item = calculate(_hours(), hourly_employee)
    expected_net = _money(
        item.gross_pay
        - item.pretax_401k
        - item.fica_ss
        - item.fica_medicare
        - item.federal_withholding
    )
    assert item.net_pay == expected_net
    # After Phase 3, federal_withholding must be non-zero for a typical employee
    # (unless wages are too low — use a high enough wage in the fixture)
```

CALC-08 (reconciliation check identity):
```python
def test_reconciliation_identity(hourly_employee):
    """CALC-08: the arithmetic backstop — net + taxes + deductions ties back to gross."""
    item = calculate(_hours(), hourly_employee)
    reconstructed = _money(
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
```

**`_hours()` helper** (`test_calculate.py` lines 29–36 — existing, do not duplicate):
```python
def _hours(regular="40"):
    return {
        "hours_regular": Decimal(regular),
        "hours_overtime": Decimal("0"),
        "hours_vacation": Decimal("0"),
        "hours_sick": Decimal("0"),
        "hours_holiday": Decimal("0"),
    }
```
New tests in this file REUSE `_hours()` — do not add a second definition.

---

## Shared Patterns

### Decimal + `_money()` (ROUND_HALF_UP)
**Source:** `app/pipeline/calculate.py` lines 45–58
**Apply to:** `federal_withholding.py` (local copy), `calculate.py` (existing), all new test assertions
```python
_CENTS = Decimal("0.01")

def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)
```
Every intermediate Worksheet 1A step that produces a dollar value calls `_money()`. The final `line_4b` (per-period withholding output) also calls `_money()`. Never use `float`.

### `Employee` construction (full-field, `extra="forbid"`)
**Source:** `app/db/seed.py` lines 79–261; `app/models/roster.py` lines 26–107
**Apply to:** all synthetic test fixtures in `test_federal_withholding.py`

All 15 `Employee` fields must be passed at construction — no field can be omitted. The `@model_validator` enforces `pay_type ↔ compensation` invariant: if `pay_type="hourly"` then `hourly_rate` must be set and `annual_salary` must be `None`, and vice versa.

### Pure-function isolation (D-14)
**Source:** `app/pipeline/calculate.py` lines 1–8, 73
**Apply to:** `federal_withholding.py`, `tax_tables_2026.py`

Both new modules must be importable with no DB access, no network, no side effects. The eval (Phase 4) imports and calls them directly. Never put `get_connection()`, `get_settings()`, or any I/O in these modules.

### Seeded-employee access pattern in tests
**Source:** `tests/test_calculate.py` lines 18–26
**Apply to:** layer-B seeded fixtures in `test_federal_withholding.py`
```python
@pytest.fixture()
def some_employee():
    seeded = seed(dry_run=True)
    emp = next(e for e in seeded.employees if <field predicate>)
    return emp
```
`seed(dry_run=True)` returns a `SeedResult` with `.employees` list — no DB needed. Filter by field (e.g. `e.filing_status == "married_jointly" and not e.step_2_checkbox`) rather than by index.

### `PaystubLineItem` field names (confirmed from `app/models/contracts.py` lines 149–179)
**Apply to:** all tests in `test_calculate.py` that assert on the output
```python
item.gross_pay          # Decimal
item.pretax_401k        # Decimal
item.fica_ss            # Decimal
item.fica_medicare      # Decimal
item.federal_withholding  # Decimal — Phase 3 fills with real value
item.state_withholding    # Decimal | None — always None in Phase 3
item.net_pay            # Decimal — Phase 3: real net (not pre-federal)
```

---

## No Analog Found

All Phase 3 files have a close analog in the codebase. The only structural novelty is the bracket-lookup function (`_find_bracket`) inside `federal_withholding.py` — it has no existing analog (no lookup tables anywhere in the project). The planner should use the linear-scan O(n) approach from RESEARCH.md Architecture Patterns (8 rows max, no performance concern).

| File | Novel Aspect | Guidance |
|------|-------------|----------|
| `federal_withholding.py` — `_find_bracket()` | No existing bracket-lookup in codebase | Linear scan reversed list: `for row in reversed(brackets): if annual_wage >= row.lower: return row` |
| `tax_tables_2026.py` — bracket table data | No existing constant tables in codebase | Transcribe directly from RESEARCH.md Deliverable 1 (which was transcribed from the live 2026 PDF) |

---

## Metadata

**Analog search scope:** `app/pipeline/`, `app/models/`, `app/db/`, `tests/`
**Files read:** `calculate.py`, `roster.py`, `contracts.py`, `test_calculate.py`, `seed.py`, `config.py`, `conftest.py`
**Pattern extraction date:** 2026-06-22
