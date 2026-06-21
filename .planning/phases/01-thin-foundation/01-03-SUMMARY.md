---
phase: 01-thin-foundation
plan: 03
subsystem: seed-data
tags: [seed, pydantic, tdd, postgres, psycopg, fixtures]

dependency_graph:
  requires:
    - phase: 01-01
      provides: Employee Pydantic contract (D-10/FOUND-06 validation at seed time)
    - phase: 01-02
      provides: schema.sql (UNIQUE(business_id,full_name) for upsert), supabase.py (get_connection()), bootstrap.py (reset for integration tests)
  provides:
    - app/db/seed.py — SeedResult dataclass + seed() function: 3 businesses, 6 employees, Pydantic-validated, transactional, idempotent upsert
    - tests/test_seed_roundtrip.py — 14 DB-independent in-memory coverage tests (always pass) + 8 live-DB integration tests (skip without DATABASE_URL + ALLOW_DB_RESET=1)
  affects:
    - Phase 2 (name-reconciliation: David Reyes is the hero gate CANDIDATE; Maria Chen has known_aliases for alias fast-path)
    - Phase 3 (calc engine: Thomas Bergmann's ytd_ss_wages=$183,900 straddles $184,500 SS cap; Priya Nair step_2_checkbox=True for Pub 15-T branch coverage)
    - Phase 4 (eval: stable fixed UUIDs ensure FK references in fixture files remain stable)

tech_stack:
  added: []
  patterns:
    - Pydantic validation at module import time (D-10): Employee models constructed as module-level constants; ValidationError on import if any FOUND-06 field is wrong
    - SeedResult dataclass (Finding #10): dry_run returns structured result with both .businesses and .employees for behavior inspection
    - Single conn.transaction() wrapping all INSERTs (Finding #10 — atomic: all or nothing)
    - ON CONFLICT upsert via natural keys: (contact_email) for businesses, uq_employee_business_name (business_id, full_name) for employees (D-11)
    - Fixed UUID literals (D-11): never uuid4() — stable across runs for FK stability in later fixtures
    - Live-DB test skip guards (Finding #10): skipif on DATABASE_URL + ALLOW_DB_RESET=1; two-factor guard prevents destructive reset against non-test DB
    - Explicit column select + dict_row (Finding #4): no SELECT *, prevents extra-column ValidationError with Employee extra="forbid"
    - pytest integration marker registered in pyproject.toml (Rule 2 auto-fix: eliminates PytestUnknownMarkWarning)

key_files:
  created:
    - app/db/seed.py
    - tests/test_seed_roundtrip.py
  modified:
    - pyproject.toml

decisions:
  - D-10 applied: Employee models constructed at module-load time so ValidationError on any FOUND-06 field fires at import/seed time, never mid-demo
  - D-11 applied: fixed UUID literals for all 9 records; no uuid4() calls; ON CONFLICT on contact_email (businesses) and uq_employee_business_name (employees)
  - D-13 / Finding #5 applied: SS cap straddle condition is per-period WAGES vs remaining WAGE BASE ($600), not tax amount vs wage base — Thomas Bergmann per_period_gross=$9,230.77 > remaining_cap=$600, partial SS=$37.20
  - FIX B applied: Sandra Kim pay_periods_per_year=26 (matches Business 3 biweekly cadence; earlier draft had 52)
  - Finding #10 applied: SeedResult carries both .businesses and .employees; dry_run never opens DB connection; transaction wraps all writes
  - Finding #4 applied: test_employee_roundtrip uses explicit column list (not SELECT *) + dict_row so Employee(**row) never receives created_at/updated_at extra columns

metrics:
  duration_minutes: 5
  completed_date: "2026-06-21"
  tasks_completed: 2
  files_created: 2
  files_modified: 1
  tests_passing: 33
  tests_skipped: 8
---

# Phase 1 Plan 3: Seed Loader + Round-Trip Tests Summary

**One-liner:** Pydantic-contract-driven seed loader with fixed UUIDs, transactional upserts, and structured dry_run result; 14 DB-independent in-memory tests always pass and 8 live-DB integration tests skip cleanly without DATABASE_URL + ALLOW_DB_RESET=1.

## What Was Built

### Task 1: app/db/seed.py — seed loader

- `SeedResult` dataclass: `businesses: list[dict]` + `employees: list[Employee]` — both populated in dry_run and live paths (Finding #10)
- `seed(dry_run=False) -> SeedResult`: constructs all 6 Employee Pydantic objects at module import time (D-10) — validation errors on any FOUND-06 field fire at import, not mid-demo
- Dry-run path: returns `SeedResult` immediately, zero DB calls (Finding #10)
- Live path: opens `get_connection()` from `app.db.supabase`, wraps all INSERTs in a single `with conn.transaction():` (Finding #10 atomicity)
- Business upsert: `ON CONFLICT (contact_email) DO UPDATE SET name, pay_period, updated_at=now()` (D-11 natural key)
- Employee upsert: `ON CONFLICT ON CONSTRAINT uq_employee_business_name DO UPDATE SET <all mutable fields>, updated_at=now()` (D-11 / Finding #1)
- No INSERT into `payroll_runs` or `email_messages` — D-11 containment enforced by absence

#### 3-Business Roster

| Business | contact_email | pay_period |
|----------|--------------|------------|
| Coastal Cleaning Co. | payroll@coastalcleaning.example | weekly |
| Metro Deli Group | hr@metrodeli.example | weekly |
| Summit Tech Solutions | finance@summittech.example | biweekly |

#### 6-Employee Roster (coverage-driven)

| Employee | Business | pay_type | filing_status | pay_periods | Notes |
|----------|----------|----------|--------------|-------------|-------|
| Maria Chen | Coastal Cleaning | hourly | single | 52 | known_aliases=["Maria","M. Chen"] — alias fast-path |
| James Okafor | Coastal Cleaning | salary | married_jointly | 52 | 401k 4% |
| David Reyes | Metro Deli | hourly | single | 52 | Hero gate CANDIDATE (D-12): Phase 2 submits "David Reyez" |
| Priya Nair | Metro Deli | salary | married_separately | 52 | step_2_checkbox=True — Pub 15-T branch |
| Thomas Bergmann | Summit Tech | salary | married_jointly | 26 | ytd_ss_wages=183900 — SS cap straddle |
| Sandra Kim | Summit Tech | hourly | single | 26 | FIX B: corrected from 52 to 26 |

#### SS Cap Straddle (D-13 / Finding #5)

Thomas Bergmann straddle math (straddle condition: per-period WAGES > remaining WAGE BASE):
- ytd_ss_wages = $183,900
- annual_salary = $240,000 / 26 periods = $9,230.77 per period
- remaining_cap = $184,500 - $183,900 = $600
- Straddle: $9,230.77 > $600 → TRUE
- Partial SS tax = $600 × 6.2% = **$37.20** (only remaining $600 is SS-taxable)

### Task 2: tests/test_seed_roundtrip.py — test suite

**DB-independent tests (14, always run):**
- `test_seed_dry_run_returns_seed_result` — SeedResult type check
- `test_seed_has_three_businesses` — count=3
- `test_seed_has_six_employees` — count=6
- `test_seed_distinct_contact_emails` — 3 unique natural keys
- `test_all_employees_pass_pydantic_validation` — all 6 are Employee instances (FOUND-06)
- `test_seed_has_hourly_and_salary_employees` — both pay_types present
- `test_seed_covers_all_three_filing_statuses` — single/married_jointly/married_separately
- `test_seed_has_step2_checkbox_employee` — Priya Nair step_2_checkbox=True
- `test_seed_has_employee_with_known_aliases` — Maria Chen, Thomas Bergmann, Priya Nair
- `test_seed_has_happy_path_business` — Coastal Cleaning Co. present
- `test_seed_has_name_mismatch_candidate` — David Reyes present
- `test_seed_high_earner_ss_cap_straddle` — straddle math verified (partial SS=$37.20)
- `test_business3_employees_have_biweekly_cadence` — both Summit Tech employees have pay_periods_per_year=26 (FIX B)
- `test_seed_employees_have_stable_fixed_uuids` — all 6 fixed UUID literals (D-11)

**Live-DB integration tests (8, skip without DATABASE_URL + ALLOW_DB_RESET=1):**
- `test_business_count` / `test_employee_count` — row counts post-seed
- `test_high_earner_fields` — Thomas Bergmann ytd_ss_wages=183900.00 as Decimal, pay_periods=26
- `test_employee_roundtrip` — explicit column select + dict_row → Employee(**row) for all 6
- `test_idempotent_reseed` — second seed() call leaves counts unchanged
- `test_seed_containment` — 0 rows in payroll_runs + email_messages (D-11)
- `test_hero_case_exists` — exactly 1 row for "David Reyes"
- `test_alias_exists` — "Maria" in Maria Chen's known_aliases

## Test Results

```
33 passed, 8 skipped in 0.10s
```

- 19 original tests (contracts + drift guard): all passing
- 14 new DB-independent seed tests: all passing
- 8 new live-DB integration tests: all skipping (DATABASE_URL not set in this environment)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing] Registered `integration` pytest marker in pyproject.toml**
- **Found during:** Task 2 test execution
- **Issue:** `@pytest.mark.integration` on live-DB tests produced `PytestUnknownMarkWarning` in pytest output — noisy and looks like a test configuration error
- **Fix:** Added `[tool.pytest.ini_options]` section to `pyproject.toml` with `markers = ["integration: ..."]` registration
- **Files modified:** `pyproject.toml`
- **Commit:** 16c1e13 (bundled with feat commit)

### Plan Structural Note

The plan specified "two module-level skip guards" at module top for the integration tests. Applied instead as `pytest.mark.skipif` on each integration test function + a fixture guard. Reasoning: module-level `pytest.skip(allow_module_level=True)` skips ALL tests in the file — it would kill the 14 DB-independent in-memory tests when DATABASE_URL is absent, contradicting the prior_wave_context requirement that "at least one DB-independent test validates the seed dataset purely in-memory" and always passes. The `skipif` approach correctly separates the two test sections: in-memory always runs; live-DB skips based on env vars.

## Known Stubs

None. The seed data is fully wired: all Employee fields populated, all Pydantic validation passes, straddle math confirmed.

## Threat Surface Scan

No new network endpoints, auth paths, or file access patterns introduced. `seed.py` opens a DB connection when run live, but this is gated by `DATABASE_URL` being set (same as all other DB-touching code in the project).

T-03-01 (Tampering — seed writing to payroll_runs/email_messages): mitigated. `seed.py` has no INSERT INTO payroll_runs or email_messages. `test_seed_containment` provides the live-DB proof.
T-03-02 (Tampering — bootstrap(reset=True) against production DB): mitigated. Both env guards (`DATABASE_URL` + `ALLOW_DB_RESET=1`) must be set for the integration fixture to call `bootstrap(reset=True)` — enforced by `_HAS_DB and _HAS_RESET` check in the fixture.
T-03-03 (Information Disclosure — Fixed UUIDs): accepted. Seed UUIDs are stable identifiers for a demo dataset, not credentials; committing them is correct per D-11.
T-03-SC (Tampering — no new pip packages): accepted. No new dependencies added.

## Self-Check: PASSED

Files exist:
- app/db/seed.py: FOUND
- tests/test_seed_roundtrip.py: FOUND
- pyproject.toml (modified): FOUND

Commits exist:
- 7d662de: test(01-03): add seed coverage tests
- 16c1e13: feat(01-03): seed loader — Pydantic-validated, transactional, idempotent upsert
