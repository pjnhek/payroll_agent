"""Pydantic-contract-driven seed loader for the payroll agent.

Populates 3 businesses and 7 employees covering every calc path and name-match case.
Every Employee record is validated through the Employee Pydantic contract before any
DB write, so a record missing a calc-input field fails at seed time rather than
mid-demo — where it would surface as a wrong paystub, not an obvious error.

All UUIDs are fixed/stable literals so FK references from fixture files stay valid
across re-seeds.

CONTAINMENT: seed() must never touch payroll_runs or email_messages — it seeds
reference data only. There is deliberately no INSERT INTO either table in this file;
seeding run state would fabricate payroll history that no client ever submitted.

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
# SeedResult — structured return type.
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
# Seed data — declared as Python literals; fixed UUIDs throughout
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

# Each Employee is constructed at module load time so Pydantic validates it there:
# a missing or wrong calc-input field raises ValidationError at IMPORT, before seed()
# is ever called, rather than producing a silently miscalculated paystub later.
_EMPLOYEES: list[Employee] = [
    # -------------------------------------------------------------------
    # Employee 1 — Maria Chen (Business 1, hourly, single, aliases)
    # Covers the stored-alias resolution path.
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
    # DETERMINISTIC HERO: the gate_block_hero fixture submits the unknown shorthand
    # "David Reyez" (one-letter transposition y→z). The deterministic resolver finds
    # NO unique exact/alias match, so the name resolves to source="none" /
    # resolved=False — no model, no confidence score — and decide gates the run to
    # request_clarification. The system never guesses on a money-moving decision. The
    # clarification-suggestion LLM call then names this employee in the email ("did
    # you mean David Reyes?"), strictly AFTER the gate, never feeding the decision.
    #
    # COLLISION PAIR: David Reyes shares the known_alias "D. Reyes" with Daniel Reyes
    # (Employee 7, same business). A submission of "D. Reyes" therefore matches 2+
    # employees, so the resolver refuses to pick either (source="none") and the run
    # gates to clarification — two plausible matches always clarify, never guess.
    # This does NOT violate UNIQUE(business_id, full_name): the collision is on a
    # SHARED ALIAS, and the two full_names stay distinct. That is what makes the
    # construction possible at all — do not "fix" it by de-duplicating the alias, or
    # the collision-safety fixture stops testing anything.
    # -------------------------------------------------------------------
    Employee(
        id=uuid.UUID("e0000003-0000-0000-0000-000000000003"),
        business_id=uuid.UUID("b0000002-0000-0000-0000-000000000002"),
        full_name="David Reyes",
        known_aliases=["D. Reyes"],  # SHARED with Daniel Reyes → always clarifies
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
    # step_2_checkbox=True so the Pub 15-T Step-2-checkbox withholding schedule (the
    # alternate bracket table) is exercised, not just the standard one.
    # known_aliases give this employee stored-alias resolution coverage too.
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
        step_2_checkbox=True,  # exercises the Pub 15-T Step-2-checkbox schedule
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("2000.00"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("35000.00"),
        pay_periods_per_year=52,  # Business 2 is weekly
    ),
    # -------------------------------------------------------------------
    # Employee 5 — Thomas Bergmann (Business 3, salary, married_jointly, biweekly)
    # HIGH-EARNER SS CAP STRADDLE — this employee's numbers are chosen so the
    # partial-cap branch of the Social Security calc is the ONLY one that produces the
    # right answer. Do not round them off:
    #
    #   ytd_ss_wages     = $183,900
    #   annual_salary    = $240,000
    #   pay_periods      = 26 (biweekly)
    #   per_period_gross = $240,000 / 26 = $9,230.769...
    #   remaining_cap    = $184,500 - $183,900 = $600
    #
    #   Straddle condition: remaining_cap ($600) > 0
    #                   AND per_period_gross ($9,230.77) > remaining_cap ($600) → TRUE
    #
    #   The condition compares per-period WAGES against the remaining WAGE BASE — NOT
    #   a tax dollar amount against the wage base. Comparing a tax figure to a wage
    #   figure is the natural-looking mistake here, and it silently mis-taxes every
    #   high earner who crosses the cap mid-year.
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
        # $600 below the $184,500 cap; per-period gross ($9,230.77) exceeds that
        # remaining $600 → the partial-cap branch of the SS calc fires
        ytd_ss_wages=Decimal("183900.00"),
        pay_periods_per_year=26,  # Business 3 is biweekly
    ),
    # -------------------------------------------------------------------
    # Employee 6 — Sandra Kim (Business 3, hourly, single, 401k, biweekly)
    # pay_periods_per_year MUST match the employee's business cadence (26 here, for
    # Business 3's biweekly schedule). A mismatch does not error — it silently skews
    # the annualization inside the Pub 15-T withholding calc.
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
        pay_periods_per_year=26,  # Business 3 is biweekly
    ),
    # -------------------------------------------------------------------
    # Employee 7 — Daniel Reyes (Business 2, hourly, single — COLLISION PAIR)
    # The other half of the collision-safety pair. Daniel Reyes shares the
    # known_alias "D. Reyes" with David Reyes (Employee 3, same business), so a
    # submission of the shorthand "D. Reyes" matches BOTH employees. The
    # deterministic resolver refuses to pick either (an alias matching 2+ employees
    # yields source="none", resolved=False in reconcile_names.deterministic_match)
    # and decide gates the run to request_clarification — the run cannot pay the
    # wrong person. The two employees keep DISTINCT full_names, so
    # UNIQUE(business_id, full_name) still holds; only the ALIAS is shared.
    # Carries the full calc-input set so the Employee validator passes.
    # -------------------------------------------------------------------
    Employee(
        id=uuid.UUID("e0000007-0000-0000-0000-000000000007"),
        business_id=uuid.UUID("b0000002-0000-0000-0000-000000000002"),
        full_name="Daniel Reyes",
        known_aliases=["D. Reyes"],  # SHARED with David Reyes → always clarifies
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
#   Business 3 biweekly (26): Thomas Bergmann 26 ✓, Sandra Kim 26 ✓


# ---------------------------------------------------------------------------
# seed() — the public entry point
# ---------------------------------------------------------------------------


def seed(dry_run: bool = False) -> SeedResult:
    """Seed 3 businesses and 7 employees into the live DB.

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
    # seed() is forbidden from touching payroll_runs or email_messages — it seeds
    # reference data only. There is intentionally no INSERT INTO either table below.

    result = SeedResult(businesses=list(_BUSINESSES), employees=list(_EMPLOYEES))

    if dry_run:
        # Return the structured result without any DB interaction.
        return result

    # Live path — requires DATABASE_URL to be set in the environment
    from app.db.supabase import get_connection

    # All writes go in a SINGLE explicit transaction: the seed must be atomic, or a
    # partial failure leaves orphaned businesses with no employees.
    with get_connection() as conn, conn.transaction():
        # ----------------------------------------------------------------
        # 1. Upsert businesses on the PRIMARY KEY id.
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
        # 2. Upsert employees via the (business_id, full_name) natural key, whose
        #    UNIQUE constraint is named uq_employee_business_name in schema.sql.
        #    ON CONFLICT updates every mutable field + updated_at.
        # ----------------------------------------------------------------
        for emp in _EMPLOYEES:
            # psycopg adapts Pydantic-native Decimal/list/bool values directly, so no
            # model_dump is called here. Decimal -> numeric, list[str] -> TEXT[]
            # (including the empty-list case), bool -> boolean.
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
