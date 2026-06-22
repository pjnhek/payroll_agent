"""Pydantic-contract-driven seed loader for the payroll agent.

Populates 3 businesses and 7 employees covering every calc path and name-match case.
Every Employee record is validated through the Employee Pydantic contract before any
DB write — missing FOUND-06 fields fail at seed time, not mid-demo (D-10).

All UUIDs are fixed/stable literals so FK references in later fixture files remain
stable across runs (D-11).

D-11 containment: seed() is explicitly forbidden from touching payroll_runs or
email_messages. This file has no INSERT INTO payroll_runs or email_messages.

Usage:
    # Dry-run (no DB access — validates all Employee models and returns SeedResult):
    python -c "from app.db.seed import seed; r = seed(dry_run=True); print(r)"

    # Live seed (requires DATABASE_URL):
    python -m app.db.seed
"""

import dataclasses
import uuid
from decimal import Decimal
from typing import Any

from app.models.roster import Employee

# ---------------------------------------------------------------------------
# SeedResult — structured return type (Finding #10)
# dry_run=True and live path both return this so callers can inspect the data.
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SeedResult:
    """Structured result returned by seed().

    .businesses: list of raw business dicts (the data to be / that was upserted)
    .employees: list of validated Employee Pydantic objects
    """

    businesses: list[dict[str, Any]]
    employees: list[Employee]


# ---------------------------------------------------------------------------
# Seed data — declared as Python literals; fixed UUIDs throughout (D-11)
# ---------------------------------------------------------------------------

_BUSINESSES: list[dict[str, Any]] = [
    {
        "id": uuid.UUID("b0000001-0000-0000-0000-000000000001"),
        "name": "Coastal Cleaning Co.",
        "contact_email": "payroll@coastalcleaning.example",
        "pay_period": "weekly",
    },
    {
        "id": uuid.UUID("b0000002-0000-0000-0000-000000000002"),
        "name": "Metro Deli Group",
        "contact_email": "hr@metrodeli.example",
        "pay_period": "weekly",
    },
    {
        "id": uuid.UUID("b0000003-0000-0000-0000-000000000003"),
        "name": "Summit Tech Solutions",
        "contact_email": "finance@summittech.example",
        "pay_period": "biweekly",
    },
]

# Each Employee is constructed immediately at module load time for Pydantic validation.
# Construction raises ValidationError if any FOUND-06 field is missing or wrong (D-10).
# This means import errors surface at import time — even before seed() is called.
_EMPLOYEES: list[Employee] = [
    # -------------------------------------------------------------------
    # Employee 1 — Maria Chen (Business 1, hourly, single, aliases)
    # Alias fast-path coverage per D-13.
    # -------------------------------------------------------------------
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
        pay_periods_per_year=52,  # Business 1 is weekly
    ),
    # -------------------------------------------------------------------
    # Employee 2 — James Okafor (Business 1, salary, married_jointly, 401k)
    # -------------------------------------------------------------------
    Employee(
        id=uuid.UUID("e0000002-0000-0000-0000-000000000002"),
        business_id=uuid.UUID("b0000001-0000-0000-0000-000000000001"),
        full_name="James Okafor",
        known_aliases=[],
        pay_type="salary",
        hourly_rate=None,
        annual_salary=Decimal("62400.00"),
        retirement_contribution_pct=Decimal("0.04"),
        filing_status="married_jointly",
        step_2_checkbox=False,
        step_3_dependents=Decimal("4000.00"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("24000.00"),
        pay_periods_per_year=52,  # Business 1 is weekly
    ),
    # -------------------------------------------------------------------
    # Employee 3 — David Reyes (Business 2, hourly, single)
    # DETERMINISTIC HERO (D-21 reframe): the gate_block_hero fixture submits the
    # unknown shorthand "David Reyez" (one-letter transposition y→z). The
    # deterministic resolver finds NO unique exact/alias match for it, so it
    # resolves to source="none"/resolved=False (no model, no confidence) and decide
    # gates the run to request_clarification — the system never guesses on a
    # money-moving decision (D-21-01). The clarification-suggestion call (D-21-05)
    # then names this employee in the email ("did you mean David Reyes?").
    #
    # COLLISION PAIR (D-21-02): David Reyes shares the known_alias "D. Reyes" with
    # Daniel Reyes (Employee 7, same business). A submission of "D. Reyes" therefore
    # matches 2+ employees, so the resolver refuses to pick either (source="none") and
    # the run gates to clarification. The collision_safety fixture proves this:
    # two plausible matches → always clarify, never guess. The UNIQUE(business_id,
    # full_name) constraint is NOT violated — the collision is on a SHARED ALIAS,
    # not a duplicate full_name (the constraint-safe construction, D-21-02).
    # -------------------------------------------------------------------
    Employee(
        id=uuid.UUID("e0000003-0000-0000-0000-000000000003"),
        business_id=uuid.UUID("b0000002-0000-0000-0000-000000000002"),
        full_name="David Reyes",
        known_aliases=["D. Reyes"],  # SHARED with Daniel Reyes → collision (D-21-02)
        pay_type="hourly",
        hourly_rate=Decimal("22.00"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("8000.00"),
        pay_periods_per_year=52,  # Business 2 is weekly
    ),
    # -------------------------------------------------------------------
    # Employee 4 — Priya Nair (Business 2, salary, married_separately, Step-2)
    # step_2_checkbox=True for Pub 15-T Step-2-checkbox branch coverage in Phase 3.
    # known_aliases for alias fast-path coverage.
    # -------------------------------------------------------------------
    Employee(
        id=uuid.UUID("e0000004-0000-0000-0000-000000000004"),
        business_id=uuid.UUID("b0000002-0000-0000-0000-000000000002"),
        full_name="Priya Nair",
        known_aliases=["P. Nair"],
        pay_type="salary",
        hourly_rate=None,
        annual_salary=Decimal("72800.00"),
        retirement_contribution_pct=Decimal("0.06"),
        filing_status="married_separately",
        step_2_checkbox=True,  # Step-2-checkbox branch for Pub 15-T Phase 3 coverage
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("2000.00"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("35000.00"),
        pay_periods_per_year=52,  # Business 2 is weekly
    ),
    # -------------------------------------------------------------------
    # Employee 5 — Thomas Bergmann (Business 3, salary, married_jointly, biweekly)
    # HIGH-EARNER SS CAP STRADDLE (D-13 corrected per Finding #5):
    #
    #   ytd_ss_wages    = $183,900
    #   annual_salary   = $240,000
    #   pay_periods     = 26 (biweekly)
    #   per_period_gross = $240,000 / 26 = $9,230.769...
    #   remaining_cap   = $184,500 - $183,900 = $600
    #
    #   Straddle condition: remaining_cap ($600) > 0
    #                   AND per_period_gross ($9,230.77) > remaining_cap ($600) → TRUE
    #
    #   The straddle condition compares per-period WAGES to the remaining WAGE BASE
    #   (NOT a tax dollar amount to the wage base — that was the corrected Finding #5).
    #
    #   Partial SS tax = $600 × 0.062 = $37.20
    #   (only the remaining $600 of wages is SS-taxable; wages above $184,500 exempt)
    # -------------------------------------------------------------------
    Employee(
        id=uuid.UUID("e0000005-0000-0000-0000-000000000005"),
        business_id=uuid.UUID("b0000003-0000-0000-0000-000000000003"),
        full_name="Thomas Bergmann",
        known_aliases=["Tom Bergmann", "Tom"],
        pay_type="salary",
        hourly_rate=None,
        annual_salary=Decimal("240000.00"),
        retirement_contribution_pct=Decimal("0.08"),
        filing_status="married_jointly",
        step_2_checkbox=False,
        step_3_dependents=Decimal("8000.00"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        # $600 below $184,500 cap; per-period gross ($9,230.77) exceeds remaining cap
        # ($600) → partial-cap branch fires in Phase 3
        ytd_ss_wages=Decimal("183900.00"),
        pay_periods_per_year=26,  # Business 3 is biweekly
    ),
    # -------------------------------------------------------------------
    # Employee 6 — Sandra Kim (Business 3, hourly, single, 401k, biweekly)
    # FIX B: pay_periods_per_year=26 to match Business 3's biweekly cadence.
    # (An earlier draft erroneously had 52 — corrected per CADENCE VERIFICATION.)
    # -------------------------------------------------------------------
    Employee(
        id=uuid.UUID("e0000006-0000-0000-0000-000000000006"),
        business_id=uuid.UUID("b0000003-0000-0000-0000-000000000003"),
        full_name="Sandra Kim",
        known_aliases=[],
        pay_type="hourly",
        hourly_rate=Decimal("45.00"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0.05"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("52000.00"),
        pay_periods_per_year=26,  # Business 3 is biweekly (FIX B: corrected from 52)
    ),
    # -------------------------------------------------------------------
    # Employee 7 — Daniel Reyes (Business 2, hourly, single — COLLISION PAIR)
    # The other half of the deterministic collision-safety pair (D-21-02). Daniel
    # Reyes shares the known_alias "D. Reyes" with David Reyes (Employee 3, same
    # business), so a submission of the shorthand "D. Reyes" matches BOTH employees.
    # The deterministic resolver refuses to pick either (alias matches 2+ employees
    # → source="none", resolved=False — reconcile_names.deterministic_match), and
    # decide gates the run to request_clarification. This is the constraint-safe
    # collision construction: the two employees have DISTINCT full_names (so the
    # UNIQUE(business_id, full_name) constraint holds) but a SHARED alias.
    # Carries the full FOUND-06 calc-input set so the Employee validator passes.
    # -------------------------------------------------------------------
    Employee(
        id=uuid.UUID("e0000007-0000-0000-0000-000000000007"),
        business_id=uuid.UUID("b0000002-0000-0000-0000-000000000002"),
        full_name="Daniel Reyes",
        known_aliases=["D. Reyes"],  # SHARED with David Reyes → collision (D-21-02)
        pay_type="hourly",
        hourly_rate=Decimal("20.00"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("6000.00"),
        pay_periods_per_year=52,  # Business 2 is weekly
    ),
]

# CADENCE VERIFICATION (static, documentational):
#   Business 1 weekly  (52): Maria Chen 52 ✓, James Okafor 52 ✓
#   Business 2 weekly  (52): David Reyes 52 ✓, Priya Nair 52 ✓, Daniel Reyes 52 ✓
#   Business 3 biweekly (26): Thomas Bergmann 26 ✓, Sandra Kim 26 ✓ (FIX B)


# ---------------------------------------------------------------------------
# seed() — the public entry point
# ---------------------------------------------------------------------------


def seed(dry_run: bool = False) -> SeedResult:
    """Seed 3 businesses and 6 employees into the live DB.

    Every Employee is validated through the Pydantic contract before any DB
    write — construction already ran at module import time, so if we reach
    this point the models are valid.

    Args:
        dry_run: When True, returns a SeedResult without any DB access (Finding
                 #10 — structured dry-run for behavior inspection and testing).

    Returns:
        SeedResult with .businesses (list of business dicts) and .employees
        (list of validated Employee objects).

    Raises:
        pydantic.ValidationError: Already caught at module-load if any Employee
            construction fails — this never reaches seed() in that case.
        psycopg.Error: If DB connection or insert fails (live path only).
    """
    # D-11: seed() is explicitly forbidden from touching payroll_runs or email_messages.
    # There is intentionally no INSERT INTO payroll_runs or email_messages below.

    result = SeedResult(businesses=list(_BUSINESSES), employees=list(_EMPLOYEES))

    if dry_run:
        # Return structured result without any DB interaction (Finding #10)
        return result

    # Live path — requires DATABASE_URL to be set in the environment
    from app.db.supabase import get_connection

    with get_connection() as conn:
        # All writes in a SINGLE explicit transaction (Finding #10 — atomic; no
        # orphaned rows on partial failure)
        with conn.transaction():
            # ----------------------------------------------------------------
            # 1. Upsert businesses on the PRIMARY KEY id (WR-06).
            #    The fixed b0000001-… literals are the stable identity that
            #    employees.business_id references, so conflicting on id keeps
            #    that FK intact on re-seed.  contact_email is treated as a
            #    plain updatable column (it has its own UNIQUE constraint in
            #    schema.sql).  Conflicting on contact_email instead would let a
            #    pre-existing row with the same email but a different id keep
            #    its old id, breaking the subsequent employee FK insert.
            # ----------------------------------------------------------------
            for biz in _BUSINESSES:
                conn.execute(
                    """
                    INSERT INTO businesses (id, name, contact_email, pay_period)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                      SET name          = EXCLUDED.name,
                          contact_email = EXCLUDED.contact_email,
                          pay_period    = EXCLUDED.pay_period,
                          updated_at    = now()
                    """,
                    (
                        str(biz["id"]),
                        biz["name"],
                        biz["contact_email"],
                        biz["pay_period"],
                    ),
                )

            # ----------------------------------------------------------------
            # 2. Upsert employees via (business_id, full_name) natural key (D-11)
            #    UNIQUE(business_id, full_name) constraint is named
            #    uq_employee_business_name in schema.sql (Plan 02 Finding #1).
            #    ON CONFLICT updates every mutable field + updated_at.
            # ----------------------------------------------------------------
            for emp in _EMPLOYEES:
                # psycopg adapts Pydantic-native Decimal/list/bool values directly
                # (IN-08): no model_dump is called here. Decimal -> numeric,
                # list[str] -> TEXT[] (including the empty-list case), bool -> boolean.
                conn.execute(
                    """
                    INSERT INTO employees (
                        id, business_id, full_name, known_aliases,
                        pay_type, hourly_rate, annual_salary,
                        retirement_contribution_pct,
                        filing_status, step_2_checkbox,
                        step_3_dependents, step_4a_other_income, step_4b_deductions,
                        ytd_ss_wages, pay_periods_per_year
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s
                    )
                    ON CONFLICT ON CONSTRAINT uq_employee_business_name DO UPDATE
                      SET known_aliases               = EXCLUDED.known_aliases,
                          pay_type                    = EXCLUDED.pay_type,
                          hourly_rate                 = EXCLUDED.hourly_rate,
                          annual_salary               = EXCLUDED.annual_salary,
                          retirement_contribution_pct = EXCLUDED.retirement_contribution_pct,
                          filing_status               = EXCLUDED.filing_status,
                          step_2_checkbox             = EXCLUDED.step_2_checkbox,
                          step_3_dependents           = EXCLUDED.step_3_dependents,
                          step_4a_other_income        = EXCLUDED.step_4a_other_income,
                          step_4b_deductions          = EXCLUDED.step_4b_deductions,
                          ytd_ss_wages                = EXCLUDED.ytd_ss_wages,
                          pay_periods_per_year        = EXCLUDED.pay_periods_per_year,
                          updated_at                  = now()
                    """,
                    (
                        str(emp.id),
                        str(emp.business_id),
                        emp.full_name,
                        emp.known_aliases,  # psycopg maps list[str] to TEXT[]
                        emp.pay_type,
                        emp.hourly_rate,
                        emp.annual_salary,
                        emp.retirement_contribution_pct,
                        emp.filing_status,
                        emp.step_2_checkbox,
                        emp.step_3_dependents,
                        emp.step_4a_other_income,
                        emp.step_4b_deductions,
                        emp.ytd_ss_wages,
                        emp.pay_periods_per_year,
                    ),
                )

    print(f"Seeded {len(_BUSINESSES)} businesses, {len(_EMPLOYEES)} employees.")
    return result


if __name__ == "__main__":
    try:
        seed()
    finally:
        from app.db.supabase import close_pool
        close_pool()
