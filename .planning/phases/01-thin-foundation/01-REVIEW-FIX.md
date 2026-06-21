---
phase: 01-thin-foundation
fixed_at: 2026-06-21
review_path: .planning/phases/01-thin-foundation/01-REVIEW.md
findings_in_scope: 9
fixed: 9
skipped: 0
status: all_fixed
---

# Phase 1: Code Review Fix Report

**Source review:** `.planning/phases/01-thin-foundation/01-REVIEW.md`

Applied all 7 WARNINGs plus the two trivial INFO items (IN-01, IN-02). IN-03,
IN-04, IN-05 were intentionally left as documented tradeoffs/deferrals.

## Summary

- Findings in scope: 9 (WR-01..WR-07, IN-01, IN-02)
- Fixed: 9
- Skipped: 0
- Test suite: **53 passed, 8 skipped, 0 failed** (baseline was 33 passed,
  8 skipped; +20 from new constraint/serializer/URL tests). The 8 skips are the
  live-DB integration tests, still correctly skipped on a missing `DATABASE_URL`.

## Fixed Issues

### WR-01: Pydantic contracts accept invalid payroll values (no numeric bounds)
**Files:** `app/models/roster.py`, `app/models/contracts.py`, `tests/test_models_contracts.py`
**Commit:** `7da8063`
Added `pydantic.Field` constraints:
- `Employee.hourly_rate` / `annual_salary`: `Field(default=None, ge=0)`
- `Employee.retirement_contribution_pct`: `Field(ge=0, le=1)`
- `NameMatchResult.confidence`: `Field(ge=0, le=1)`
- `ExtractedEmployee` all five hours fields + `contribution_401k_override`: `Field(default=None, ge=0)`
- `Decision.confidence`: `Field(ge=0, le=1)`

Negative rates/hours, retirement pct of 50 (5000%), and confidence outside
`[0,1]` now raise `ValidationError` at construction. Added 9 tests (negative
rate/salary, retirement pct over/under bounds + inclusive 0/1, confidence out
of range for `NameMatchResult`/`Decision`, negative hours).

### WR-02: `pay_periods_per_year` unconstrained at the model layer
**File:** `app/models/roster.py`, `tests/test_models_contracts.py`
**Commit:** `7da8063`
Changed `pay_periods_per_year: int` to `Literal[12, 24, 26, 52]`, mirroring the
`schema.sql` `CHECK (pay_periods_per_year IN (12,24,26,52))`. Verified the seed
only uses 52/26, so seeding still validates. Added two tests (rejects 0/-1/13/1;
accepts all four legal values).

### WR-03: Live-DB tests reference `psycopg` without importing it
**File:** `tests/test_seed_roundtrip.py`
**Commit:** `a7d85e7`
Added module-level `import psycopg` / `import psycopg.rows`, removed the three
`# noqa: F821` annotations on `psycopg.rows.dict_row`, and removed the now-
redundant local `import psycopg` block inside `test_alias_exists`. The two
live-DB tests would have raised `NameError` the moment they ran against a real
DB; they now resolve `psycopg` correctly.

### WR-04: Redundant Decimal serialization machinery
**File:** `app/models/contracts.py`, `tests/test_models_contracts.py`
**Commit:** `cb29d95`
Deleted the dead `_DecimalModel` base class (no model inherited it),
`Decision._serialize_confidence`, and `PaystubLineItem._serialize_decimal`, and
dropped the now-unused `field_serializer` import. Pydantic v2 serializes
`Decimal` to a JSON string by default in `model_dump(mode="json")` (verified
empirically). Strengthened the existing `test_decimal_json_serialization` to
lock the default across a monetary field, a nullable Decimal
(`state_withholding=None` → `null`), and `Decision.confidence`.

### WR-05: `_safe_db_url` reports valid password-less URLs as `<unparseable url>`
**File:** `app/db/bootstrap.py`, `tests/test_bootstrap_safe_url.py` (new)
**Commit:** `f483286`
Rewrote `_safe_db_url` to return the reconstructed URL in all parseable cases
(including valid password-less URLs), reserving `<unparseable url>` for
scheme-less/empty/unparseable input. Added a new DB-free test file with 7 cases
(strips password, returns password-less URLs verbatim with and without user,
sentinel for empty/garbage/whitespace, password never leaked).

### WR-06: Business upsert can desync `id` from the fixed seed literal → FK failure
**File:** `app/db/seed.py`
**Commit:** `ac6df60`
Switched the businesses upsert from `ON CONFLICT (contact_email)` to
`ON CONFLICT (id)` (the stable identity `employees.business_id` references) and
made `contact_email` an updatable column in the `DO UPDATE` set. A pre-existing
row with a matching email but a different id no longer leaves the FK target
missing on re-seed. **No schema change was required:** `schema.sql` already
declares `contact_email TEXT NOT NULL UNIQUE` (the constraint the review asked
to ensure exists) and `id` is already `PRIMARY KEY`, so `ON CONFLICT (id)`
infers cleanly. `test_status_drift.py` does not parse business constraints, so
it was untouched and remains green.

### WR-07: `Employee` compensation invariant checks presence but not exclusivity
**File:** `app/models/roster.py`, `tests/test_models_contracts.py`
**Commit:** `7da8063`
Extended `_require_compensation_field` to also reject a stray off-type comp
field: `hourly` requires `annual_salary is None`; `salary` requires
`hourly_rate is None`. Verified all 6 seed employees set the non-applicable
field to `None`, so the seed still validates at import time. Added two tests
(hourly rejects stray salary; salary rejects stray hourly rate).

### IN-01: Unused `import enum` in contracts.py
**File:** `app/models/contracts.py`
**Commit:** `7da8063`
Deleted the unreferenced `import enum` (folded into the contract-constraints
commit).

### IN-02: Tautological assertion provides no coverage
**File:** `tests/test_status_drift.py`
**Commit:** `a7d85e7`
Removed `assert "psycopg" not in sys.modules or True` (always `True`). The
meaningful `assert "app.db.supabase" not in sys.modules` guard remains.

## Not Applied (intentional, per scope)

- **IN-03** (`NameMatchResult.matched_employee_id` vs `match_type`): deferred —
  type is produced by later-phase code, not external input.
- **IN-04** (`get_pool()` never closed): acceptable for the long-lived Render
  process; noted only for future test teardown.
- **IN-05** (`--reset` non-atomic commit window): opt-in, operator-driven, and
  re-runnable; left as documented tradeoff.

---

## Deep Re-Review Fixes (round 2)

Second fix pass against the DEEP re-review (`01-REVIEW.md`). Applied all 4
warnings plus the two trivial info items the user selected. IN-06 and IN-07 were
explicitly deferred (Phase 3 / ingest-read path) and left untouched.

**Source review:** `.planning/phases/01-thin-foundation/01-REVIEW.md` (deep)

### WR-01-incomplete: `PaystubLineItem.match_confidence` had no bound
**Files:** `app/models/contracts.py`, `tests/test_models_contracts.py`
**Commit:** `dab8627`
Added `Field(ge=0, le=1)` to `PaystubLineItem.match_confidence` — the one
confidence field that maps to the DB (`paystub_line_items.match_confidence
NUMERIC(4,3)`). Unbounded, a value >9.999 crashed the INSERT and a value in
(1, 9.999] silently corrupted the audit record. Added two tests mirroring
`test_name_match_result_rejects_confidence_above_one` (rejects >1 and <0).

### WR-08: W-4 / YTD dollar fields accepted negatives in both model and schema
**Files:** `app/models/roster.py`, `app/db/schema.sql`, `tests/test_models_contracts.py`
**Commit:** `dab8627`
Added `Field(ge=0)` to `Employee.step_3_dependents`, `step_4a_other_income`,
`step_4b_deductions`, and `ytd_ss_wages`, and mirrored each with a
`CHECK (col >= 0)` in `schema.sql` (runtime backstop, per the project's
reconciliation-check philosophy). A negative `step_3_dependents` (subtracted in
the Pub 15-T worksheet) inflates withholding; a negative `ytd_ss_wages` breaks
the SS-cap straddle. Added 4 tests (negative `ytd_ss_wages` + each of the three
W-4 dollar fields). Confirmed all 6 seed employees use non-negative values via
`seed(dry_run=True)` import — seed still validates.

### WR-09: only `status` had a dual-source enum drift guard
**File:** `tests/test_status_drift.py`
**Commit:** `c581933`
Refactored the status-only guard into a parameterized
`test_check_values_match_python` covering all four dual-sourced enums:
`payroll_runs.status` ↔ `RunStatus`, and `employees.pay_type` /
`filing_status` / `pay_periods_per_year` ↔ their `Employee` `Literal`
annotations. The CHECK parser is now column-anchored with `re.escape` so a
sibling constraint such as the new `CHECK (step_3_dependents >= 0)` cannot be
matched by accident; the Python side is read live via `typing.get_args` so a
`Literal` change with no matching CHECK edit fails CI. Status count sanity check
retained — status coverage was not weakened.

### WR-10: cadence invariant tested for only 1 of 3 businesses
**File:** `tests/test_seed_roundtrip.py`
**Commit:** `c581933`
Replaced `test_business3_employees_have_biweekly_cadence` (single business,
hardcoded `26`) with `test_every_employee_cadence_matches_its_business`, a
data-driven check that maps each business `pay_period` → expected
`pay_periods_per_year` (`{weekly:52, biweekly:26, semi_monthly:24, monthly:12}`)
and asserts every seed employee matches its own business across all three
businesses. Locks the cross-table invariant that only a `seed.py` comment
enforced. Confirmed the current seed satisfies it.

### IN-08: misleading `model_dump(mode="json")` comment in `seed.py`
**File:** `app/db/seed.py`
**Commit:** `c8769a2`
Corrected the employee-loop comment — the code passes Pydantic-native
`Decimal`/`list`/`bool` values directly to psycopg; `model_dump` is never called
here. Comment now reads "psycopg adapts Pydantic-native Decimal/list/bool values
directly." No behavior change.

### IN-09: python pin looser than CLAUDE.md's 3.12 mandate
**File:** `pyproject.toml`
**Commit:** `c8769a2`
Tightened `requires-python` from `">=3.12"` to `">=3.12,<3.13"` with a comment
noting the `python:3.12-slim` runtime target. Forward guidance only; the dev
venv (3.13.5) was left untouched and the suite still runs on it.

### Round-2 test result

`.venv/bin/python -m pytest -q` → **62 passed, 8 skipped, 0 failed**
(baseline was 53 passed / 8 skipped; +9 from the new bound, drift, and cadence
tests). The 8 skips remain the live-DB integration tests (no `DATABASE_URL` /
`ALLOW_DB_RESET` in this env) — still skipped, never failed.

---

_Fixer: Claude (gsd-code-fixer)_
