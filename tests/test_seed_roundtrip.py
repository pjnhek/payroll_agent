"""Seed round-trip tests.

Two sections:
1. DB-INDEPENDENT (always run): Validates the seed dataset in-memory — every
   Employee record passes Pydantic validation; coverage invariants hold
   (3+ businesses, 7 employees, hourly/salary, all 3 filing statuses, at
   least 1 Step-2 employee, the happy-path business, the name-mismatch
   hero, the alias-collision pair, the SS cap straddle case).

2. LIVE-DB (requires DATABASE_URL + ALLOW_DB_RESET=1): Integration round-trip —
   seed then read back through Employee contract using explicit column select +
   dict_row (Finding #4 — no SELECT *, no extra-column collision with
   extra="forbid").  Two-factor guard per Finding #10: both env vars must be
   set or the live-DB tests skip individually.
"""
import os
from decimal import Decimal

import psycopg
import psycopg.rows
import pytest

# ---------------------------------------------------------------------------
# Guards — used by the live-DB section below (not module-level skips)
# ---------------------------------------------------------------------------
_HAS_DB = bool(os.environ.get("DATABASE_URL"))
_HAS_RESET = os.environ.get("ALLOW_DB_RESET") == "1"

# ---------------------------------------------------------------------------
# Section 1 — DB-independent in-memory validation (always runs)
# ---------------------------------------------------------------------------


def test_seed_dry_run_returns_seed_result() -> None:
    """seed(dry_run=True) returns a SeedResult with .businesses and .employees."""
    from app.db.seed import SeedResult, seed

    result = seed(dry_run=True)
    assert isinstance(result, SeedResult), f"Expected SeedResult, got {type(result)}"


def test_seed_has_three_businesses() -> None:
    """Seed contains exactly 3 businesses."""
    from app.db.seed import seed

    result = seed(dry_run=True)
    assert len(result.businesses) == 3, (
        f"Expected 3 businesses, got {len(result.businesses)}"
    )


def test_seed_has_seven_employees() -> None:
    """Seed contains exactly 7 employees (6 base + Daniel Reyes, the alias-collision
    pair half added in Phase 2.1 for the deterministic collision-safety proof)."""
    from app.db.seed import seed

    result = seed(dry_run=True)
    assert len(result.employees) == 7, (
        f"Expected 7 employees, got {len(result.employees)}"
    )


def test_seed_distinct_contact_emails() -> None:
    """Three businesses have three distinct contact_email values (natural upsert key)."""
    from app.db.seed import seed

    result = seed(dry_run=True)
    emails = {b["contact_email"] for b in result.businesses}
    assert len(emails) == 3, f"Expected 3 distinct contact_emails, got {emails}"


def test_all_employees_pass_pydantic_validation() -> None:
    """Every Employee in the seed validates through the Pydantic contract (FOUND-06)."""
    from app.db.seed import seed
    from app.models.roster import Employee

    result = seed(dry_run=True)
    for emp in result.employees:
        # Should already be Employee objects; this verifies the contract was applied
        assert isinstance(emp, Employee), f"{emp} is not an Employee instance"


def test_seed_has_hourly_and_salary_employees() -> None:
    """Seed contains at least one hourly and at least one salary employee."""
    from app.db.seed import seed

    result = seed(dry_run=True)
    pay_types = {e.pay_type for e in result.employees}
    assert "hourly" in pay_types, "No hourly employee in seed"
    assert "salary" in pay_types, "No salary employee in seed"


def test_seed_covers_all_three_filing_statuses() -> None:
    """Seed contains all three W-4 filing statuses."""
    from app.db.seed import seed

    result = seed(dry_run=True)
    statuses = {e.filing_status for e in result.employees}
    assert "single" in statuses, "No single filer in seed"
    assert "married_jointly" in statuses, "No married_jointly filer in seed"
    assert "married_separately" in statuses, "No married_separately filer in seed"


def test_seed_has_step2_checkbox_employee() -> None:
    """At least one seed employee has step_2_checkbox=True (Pub 15-T branch coverage)."""
    from app.db.seed import seed

    result = seed(dry_run=True)
    has_step2 = any(e.step_2_checkbox for e in result.employees)
    assert has_step2, "No employee with step_2_checkbox=True in seed"


def test_seed_has_employee_with_known_aliases() -> None:
    """At least one seed employee has known_aliases (alias fast-path coverage, D-13)."""
    from app.db.seed import seed

    result = seed(dry_run=True)
    has_alias = any(len(e.known_aliases) > 0 for e in result.employees)
    assert has_alias, "No employee with known_aliases in seed"


def test_seed_has_happy_path_business() -> None:
    """The happy-path business (Coastal Cleaning Co.) is in the seed."""
    from app.db.seed import seed

    result = seed(dry_run=True)
    emails = {b["contact_email"] for b in result.businesses}
    assert "payroll@coastalcleaning.example" in emails, (
        "Happy-path business (Coastal Cleaning Co.) missing from seed"
    )


def test_seed_has_name_mismatch_hero() -> None:
    """David Reyes — the deterministic name-mismatch hero — is in the seed.

    The gate_block_hero fixture submits the unknown shorthand 'David Reyez'. The
    deterministic resolver finds no unique exact/alias match, so it resolves to
    source='none' and decide gates the run to request_clarification — no model
    judgment, no score (D-21-01). The suggestion-only call then names this employee
    in the clarification email. Phase 1 seeds the clean name; Phase 2.1 proves it.
    """
    from app.db.seed import seed

    result = seed(dry_run=True)
    names = {e.full_name for e in result.employees}
    assert "David Reyes" in names, (
        "Name-mismatch hero 'David Reyes' missing from seed"
    )


def test_seed_has_alias_collision_pair() -> None:
    """Two Business-2 employees share the known_alias 'D. Reyes' — the deterministic
    collision-safety pair (D-21-02). A submitted 'D. Reyes' matches BOTH, so the
    resolver refuses to pick either and the run gates to clarification. This is the
    CONSTRAINT-SAFE construction: the two employees have DISTINCT full_names (so
    UNIQUE(business_id, full_name) holds) but a SHARED alias.
    """
    from app.db.seed import seed

    result = seed(dry_run=True)
    sharing = [
        e for e in result.employees if "D. Reyes" in e.known_aliases
    ]
    assert len(sharing) >= 2, (
        "the collision-safety pair must share the 'D. Reyes' alias on 2+ employees"
    )
    # Same business (the in-business collision per D-21-02).
    assert len({e.business_id for e in sharing}) == 1, (
        "the shared-alias collision pair must be in the same business"
    )
    # Distinct full_names — the UNIQUE(business_id, full_name) constraint is NOT violated.
    assert len({e.full_name for e in sharing}) == len(sharing), (
        "the collision pair must have distinct full_names (constraint-safe)"
    )


def test_seed_high_earner_ss_cap_straddle() -> None:
    """Thomas Bergmann's ytd_ss_wages + per-period gross straddles the $184,500 SS cap.

    Straddle condition (Finding #5 / D-13 corrected):
        remaining_cap > 0 AND per_period_gross > remaining_cap
    where remaining_cap is the remaining SS WAGE BASE (not a tax amount).
    This fires the partial-cap branch in Phase 3.

    Expected math:
        ytd_ss_wages    = $183,900
        annual_salary   = $240,000
        pay_periods     = 26 (biweekly)
        per_period_gross = $240,000 / 26 = $9,230.769...
        remaining_cap   = $184,500 - $183,900 = $600
        Straddle: $9,230.77 > $600 → TRUE
        partial SS tax  = $600 × 0.062 = $37.20
    """
    from app.db.seed import seed

    result = seed(dry_run=True)
    high_earner = next(
        (e for e in result.employees if e.full_name == "Thomas Bergmann"), None
    )
    assert high_earner is not None, "Thomas Bergmann missing from seed"
    assert high_earner.ytd_ss_wages == Decimal("183900.00"), (
        f"Thomas Bergmann ytd_ss_wages={high_earner.ytd_ss_wages}, expected 183900.00"
    )
    assert high_earner.pay_periods_per_year == 26, (
        f"Thomas Bergmann pay_periods_per_year={high_earner.pay_periods_per_year},"
        " expected 26"
    )
    per_period_gross = high_earner.annual_salary / high_earner.pay_periods_per_year
    remaining_cap = Decimal("184500.00") - high_earner.ytd_ss_wages
    assert remaining_cap > 0, (
        "ytd_ss_wages at or above $184,500 cap — no partial-cap case possible"
    )
    # Straddle condition: per-period WAGES exceed remaining WAGE BASE
    assert per_period_gross > remaining_cap, (
        f"per_period_gross ({per_period_gross:.2f}) must exceed"
        f" remaining_cap ({remaining_cap:.2f}) for the partial-cap branch to fire"
    )
    # Confirm the expected partial SS tax
    partial_ss_tax = remaining_cap * Decimal("0.062")
    assert partial_ss_tax == Decimal("37.20"), (
        f"Partial SS tax should be $37.20, got ${partial_ss_tax:.2f}"
    )


# Cross-table invariant: a business's pay_period dictates its employees'
# pay_periods_per_year.  Only a comment in seed.py enforces this by hand
# (no FK-level CHECK, no model holding both sides), so the test is the lock.
_PERIODS_PER_YEAR = {
    "weekly": 52,
    "biweekly": 26,
    "semi_monthly": 24,
    "monthly": 12,
}


def test_every_employee_cadence_matches_its_business() -> None:
    """Every seed employee's pay_periods_per_year matches its business's pay_period.

    WR-10: generalizes the old single-business (Business 3, hardcoded 26) check to
    all three businesses.  The relationship "weekly business ⇒ employees are 52,
    biweekly ⇒ 26" has no DB-level enforcement — only the static CADENCE
    VERIFICATION comment in seed.py — so this data-driven test is the only thing
    that locks it.  A future edit reintroducing the FIX B class of bug (Sandra Kim
    set to 52 under a biweekly business) would fail here.
    """
    from app.db.seed import seed

    result = seed(dry_run=True)

    business_period = {
        str(b["id"]): b["pay_period"] for b in result.businesses
    }
    # Guard: every business pay_period must be one we know how to map.
    for biz_id, period in business_period.items():
        assert period in _PERIODS_PER_YEAR, (
            f"Business {biz_id} has unmapped pay_period {period!r}"
        )

    # Guard: every employee's business must be present (no orphan business_id).
    assert len(result.employees) == 7, (
        f"Expected 7 employees, got {len(result.employees)}"
    )
    for emp in result.employees:
        biz_id = str(emp.business_id)
        assert biz_id in business_period, (
            f"{emp.full_name} references unknown business_id {biz_id}"
        )
        expected = _PERIODS_PER_YEAR[business_period[biz_id]]
        assert emp.pay_periods_per_year == expected, (
            f"{emp.full_name} (business {business_period[biz_id]}) has"
            f" pay_periods_per_year={emp.pay_periods_per_year}, expected {expected}"
        )


def test_seed_employees_have_stable_fixed_uuids() -> None:
    """All employee UUIDs are stable fixed literals (not random uuid4()) per D-11."""
    from uuid import UUID

    from app.db.seed import seed

    result = seed(dry_run=True)
    expected_ids = {
        UUID("e0000001-0000-0000-0000-000000000001"),
        UUID("e0000002-0000-0000-0000-000000000002"),
        UUID("e0000003-0000-0000-0000-000000000003"),
        UUID("e0000004-0000-0000-0000-000000000004"),
        UUID("e0000005-0000-0000-0000-000000000005"),
        UUID("e0000006-0000-0000-0000-000000000006"),
        UUID("e0000007-0000-0000-0000-000000000007"),  # Daniel Reyes (collision pair)
    }
    actual_ids = {e.id for e in result.employees}
    assert actual_ids == expected_ids, (
        f"Employee UUIDs mismatch. Expected {expected_ids}, got {actual_ids}"
    )


# ---------------------------------------------------------------------------
# Section 2 — Live-DB integration tests
# Two-factor skip guard (Finding #10): require DATABASE_URL + ALLOW_DB_RESET=1
# ---------------------------------------------------------------------------

_SKIP_LIVE_DB = pytest.mark.skipif(
    not (_HAS_DB and _HAS_RESET),
    reason=(
        "Live-DB tests require DATABASE_URL and ALLOW_DB_RESET=1 "
        "(Finding #10 two-factor guard)"
    ),
)


@pytest.fixture(scope="module")
def seeded_db():
    """Module-scoped fixture: reset DB, apply schema, seed once.

    Only executes when both DATABASE_URL and ALLOW_DB_RESET=1 are set —
    the _SKIP_LIVE_DB mark on every test prevents this fixture from running
    on test skips, but we also guard explicitly here.
    """
    if not (_HAS_DB and _HAS_RESET):
        pytest.skip(
            "DATABASE_URL or ALLOW_DB_RESET=1 not set — skipping live-DB fixture"
        )
    from app.db.bootstrap import bootstrap
    from app.db.seed import seed as _seed

    bootstrap(reset=True)
    _seed()
    yield


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_business_count(seeded_db) -> None:
    """SELECT COUNT(*) FROM businesses returns 3 after seed."""
    from app.db.supabase import get_connection

    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM businesses").fetchone()
    assert row[0] == 3, f"Expected 3 businesses, got {row[0]}"


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_employee_count(seeded_db) -> None:
    """SELECT COUNT(*) FROM employees returns 7 after seed."""
    from app.db.supabase import get_connection

    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM employees").fetchone()
    assert row[0] == 7, f"Expected 7 employees, got {row[0]}"


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_high_earner_fields(seeded_db) -> None:
    """Thomas Bergmann has ytd_ss_wages=183900.00, pay_periods_per_year=26, as Decimal."""
    from app.db.supabase import get_connection

    with get_connection() as conn, conn.cursor(
        row_factory=psycopg.rows.dict_row
    ) as cur:
        cur.execute(
            "SELECT ytd_ss_wages, pay_periods_per_year"
            " FROM employees WHERE full_name = 'Thomas Bergmann'"
        )
        row = cur.fetchone()

    assert row is not None, "Thomas Bergmann not found in employees"
    assert row["ytd_ss_wages"] == Decimal("183900.00"), (
        f"ytd_ss_wages={row['ytd_ss_wages']}, expected 183900.00"
    )
    assert isinstance(row["ytd_ss_wages"], Decimal), (
        f"ytd_ss_wages must be Decimal, got {type(row['ytd_ss_wages'])}"
    )
    assert row["pay_periods_per_year"] == 26, (
        f"pay_periods_per_year={row['pay_periods_per_year']}, expected 26"
    )


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_employee_roundtrip(seeded_db) -> None:
    """Every employee row round-trips through Employee(**row) without ValidationError.

    Uses explicit column list (NOT SELECT *) + dict_row factory (Finding #4).
    Employee has extra='forbid' — SELECT * would pass created_at/updated_at
    which are not Employee fields, causing ValidationError.
    """
    from app.db.supabase import get_connection
    from app.models.roster import Employee

    # Explicit column list — only Employee model fields, no extra DB-only columns
    EMPLOYEE_COLS = (
        "id, business_id, full_name, known_aliases, pay_type, hourly_rate,"
        " annual_salary, retirement_contribution_pct, filing_status,"
        " step_2_checkbox, step_3_dependents, step_4a_other_income,"
        " step_4b_deductions, ytd_ss_wages, pay_periods_per_year"
    )

    with get_connection() as conn, conn.cursor(
        row_factory=psycopg.rows.dict_row
    ) as cur:
        cur.execute(f"SELECT {EMPLOYEE_COLS} FROM employees")
        rows = cur.fetchall()

    assert len(rows) == 7, f"Expected 7 employee rows, got {len(rows)}"
    for row in rows:
        # Pydantic will raise ValidationError if any FOUND-06 field is wrong
        emp = Employee(**row)
        assert isinstance(emp, Employee)
        # D-06: numeric fields arrive as Decimal via psycopg binary extension
        assert isinstance(emp.ytd_ss_wages, Decimal), (
            f"ytd_ss_wages for {emp.full_name} must be Decimal,"
            f" got {type(emp.ytd_ss_wages)}"
        )


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_idempotent_reseed(seeded_db) -> None:
    """Second call to seed() leaves row counts unchanged (upsert idempotency)."""
    from app.db.seed import seed as _seed
    from app.db.supabase import get_connection

    _seed()  # Re-seed

    with get_connection() as conn:
        biz_count = conn.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
        emp_count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]

    assert biz_count == 3, f"After re-seed: expected 3 businesses, got {biz_count}"
    assert emp_count == 7, f"After re-seed: expected 7 employees, got {emp_count}"


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_seed_containment(seeded_db) -> None:
    """D-11: seed() never inserts into payroll_runs or email_messages."""
    from app.db.supabase import get_connection

    with get_connection() as conn:
        runs = conn.execute("SELECT COUNT(*) FROM payroll_runs").fetchone()[0]
        msgs = conn.execute("SELECT COUNT(*) FROM email_messages").fetchone()[0]

    assert runs == 0, f"Expected 0 payroll_runs after seed, got {runs}"
    assert msgs == 0, f"Expected 0 email_messages after seed, got {msgs}"


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_hero_case_exists(seeded_db) -> None:
    """David Reyes (the deterministic name-mismatch hero) has exactly 1 row.

    NOTE: This confirms the clean name is seeded. Phase 2.1 proves the behaviour —
    that 'David Reyez' (the unknown shorthand) resolves to source='none'
    deterministically and decide gates the run to request_clarification (no model,
    no score, D-21-01). Phase 1 owns only seeding.
    """
    from app.db.supabase import get_connection

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT full_name FROM employees WHERE full_name = 'David Reyes'"
        ).fetchall()

    assert len(rows) == 1, (
        f"Expected exactly 1 row for 'David Reyes', got {len(rows)}"
    )


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_alias_exists(seeded_db) -> None:
    """Maria Chen's known_aliases contains 'Maria' (alias fast-path coverage, D-13)."""
    from app.db.supabase import get_connection

    with get_connection() as conn, conn.cursor(
        row_factory=psycopg.rows.dict_row
    ) as cur:
        cur.execute(
            "SELECT known_aliases FROM employees WHERE full_name = 'Maria Chen'"
        )
        row = cur.fetchone()

    assert row is not None, "Maria Chen not found in employees"
    assert "Maria" in row["known_aliases"], (
        f"'Maria' not in Maria Chen's known_aliases: {row['known_aliases']}"
    )
