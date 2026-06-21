---
phase: 01-thin-foundation
reviewed: 2026-06-21T06:24:17Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - app/config.py
  - app/db/bootstrap.py
  - app/db/schema.sql
  - app/db/seed.py
  - app/db/supabase.py
  - app/models/contracts.py
  - app/models/roster.py
  - app/models/status.py
  - pyproject.toml
  - requirements.txt
  - tests/test_models_contracts.py
  - tests/test_seed_roundtrip.py
  - tests/test_status_drift.py
findings:
  critical: 0
  warning: 7
  info: 5
  total: 12
status: issues_found
---

# Phase 1: Code Review Report

**Reviewed:** 2026-06-21T06:24:17Z
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

Phase 1 (Thin Foundation) delivers the shared Pydantic v2 contracts, the Postgres
schema + idempotent bootstrap, and a fixed-UUID seed loader. The core mechanics
are sound: parameterized SQL is used everywhere user-shaped data flows
(no injection surface — the only f-string DDL uses a hardcoded allow-list of
table names), `prepare_threshold=None` is correctly set on both the pool and the
bootstrap connection per the Supavisor gotcha, and the status-drift guard's regex
was verified to extract exactly the 11 `payroll_runs.status` values without being
fooled by the sibling `pay_period`/`pay_periods_per_year` CHECK constraints. No
hardcoded secrets; `.env` is gitignored and untracked.

There are no BLOCKERs, but there are seven WARNINGs that matter for a system whose
stated thesis is "a low-confidence match can never reach a real payroll
calculation." The two most important: **(1) the Pydantic contracts accept clearly
invalid payroll data** — negative pay rates, negative hours, `retirement_pct=50`
(5000%), and `confidence` outside `[0,1]` despite docstrings and the 0.8 gate
depending on that range; and **(2) two of the live-DB integration tests reference
`psycopg` without importing it and will raise `NameError` the moment they run**,
giving false confidence in the round-trip layer. There is also a notable
dead-code / DRY problem: the `_DecimalModel` base class and all three
`field_serializer` decorators are redundant — Pydantic v2 already serializes
`Decimal` to a JSON string by default (verified empirically), so the D-06 guard is
load-bearing in intent only.

## Warnings

### WR-01: Pydantic contracts accept invalid payroll values (no numeric bounds)

**File:** `app/models/roster.py:43-60`, `app/models/contracts.py:78-83,120`
**Issue:** Across the contracts there are zero numeric constraints. All of the
following were confirmed to construct successfully:
- `Employee(hourly_rate=Decimal("-50.00"))` — negative wage rate accepted.
- `Employee(retirement_contribution_pct=Decimal("50"))` — 5000% 401k accepted.
- `ExtractedEmployee(hours_regular=Decimal("-10"))` — negative hours accepted.
- `NameMatchResult(confidence=Decimal("5.0"))` and `Decision(confidence=Decimal("-1"))`
  — confidence outside `[0,1]` accepted, even though both docstrings state
  "0.0–1.0" and the entire design gates on `confidence < 0.8`.

For a payroll engine whose core value is a code-gated confidence threshold, these
are exactly the inputs the contracts should reject at construction. Garbage that
parses here flows straight into the calc/gate stages in Phase 2/3.
**Fix:** Add Pydantic field constraints. Example:
```python
from pydantic import Field

# roster.py — Employee
hourly_rate: Decimal | None = Field(default=None, ge=0)
annual_salary: Decimal | None = Field(default=None, ge=0)
retirement_contribution_pct: Decimal = Field(ge=0, le=1)
confidence: Decimal = Field(ge=0, le=1)   # NameMatchResult

# contracts.py — ExtractedEmployee hours
hours_regular: Decimal | None = Field(default=None, ge=0)
# ... same ge=0 on the other four hours fields
confidence: Decimal = Field(ge=0, le=1)   # Decision
```

### WR-02: `pay_periods_per_year` is unconstrained at the model layer — silent model/SQL drift

**File:** `app/models/roster.py:60`
**Issue:** `pay_periods_per_year: int` accepts any integer (`13`, `0`, `-1` all
construct), but `schema.sql:43` constrains it to `CHECK (pay_periods_per_year IN
(12,24,26,52))`. The model is meant to be a pure value usable by the eval with
"zero DB access" (D-14), so an eval fixture or LLM-produced value of `13` passes
the contract and only blows up at the DB boundary — or never, if it never reaches
the DB. This is the same drift class the project explicitly guards for `status`
(via `test_status_drift.py`) but leaves unguarded here.
**Fix:** Mirror the SQL CHECK in the type:
```python
from typing import Literal
pay_periods_per_year: Literal[12, 24, 26, 52]
```
Or, if a CI guard is preferred over a Literal, add a `test_pay_periods_drift`
analogous to the existing status-drift test.

### WR-03: Live-DB tests reference `psycopg` without importing it — guaranteed `NameError`

**File:** `tests/test_seed_roundtrip.py:298,339`
**Issue:** `test_high_earner_fields` and `test_employee_roundtrip` both call
`conn.cursor(row_factory=psycopg.rows.dict_row)` but `psycopg` is **not imported**
at module level (module imports are only `os`, `Decimal`, `pytest`) and is **not**
imported locally inside those two functions — only `test_alias_exists` imports it
locally (lines 412-413). The `# noqa: F821` annotations suppress the linter's
"undefined name" warning but do not fix the runtime: both tests will raise
`NameError: name 'psycopg' is not defined` the moment they execute against a live
DB. They are skipped in CI (no `DATABASE_URL`), so the defect is latent and
surfaces precisely when the integration round-trip is being trusted. This violates
the project's "well-tested is non-negotiable" rule — these tests cannot pass.
**Fix:** Add the import at module level (also lets you drop the three `# noqa: F821`):
```python
import psycopg
import psycopg.rows
```
Then change `psycopg.rows.dict_row  # noqa: F821` to `psycopg.rows.dict_row`.

### WR-04: Redundant Decimal serialization machinery — `_DecimalModel` is dead, serializers are no-ops

**File:** `app/models/contracts.py:21-31,123-125,163-182`
**Issue:** `_DecimalModel` (lines 21-31) defines a universal
`@field_serializer("*")` to turn `Decimal` into a string for D-06, but **no model
in the codebase inherits from it** (`grep` confirms the only reference is its own
definition; every model subclasses `BaseModel` directly). Separately,
`Decision._serialize_confidence` (123-125) and `PaystubLineItem._serialize_decimal`
(163-182) hand-roll the same conversion per field. All of this is redundant:
Pydantic v2 already serializes `Decimal` to a JSON string in `model_dump(mode="json")`
by default — verified empirically that `ExtractedEmployee` (which has *no*
serializer at all) still emits `"40.25"`, and a plain `BaseModel` with a bare
`Decimal` field emits `"1234.56"`. So `_DecimalModel` is pure dead code and the two
explicit serializers add maintenance surface and reader confusion for zero behavior
change. CLAUDE.md: "DRY is critical. Flag repetition aggressively."
**Fix:** Delete `_DecimalModel` (21-31), delete `Decision._serialize_confidence`
(123-125), delete `PaystubLineItem._serialize_decimal` (163-182), and drop the now-
unused `field_serializer` import. Keep a single test (you already have
`test_decimal_json_serialization`) as the behavioral guard that Pydantic's default
holds — that test is the right place to lock the contract, not three copies of a
serializer.

### WR-05: `_safe_db_url` reports valid password-less URLs as `<unparseable url>`

**File:** `app/db/bootstrap.py:45-61`
**Issue:** The function only returns a reconstructed URL inside the `if
parsed.password:` branch. For a perfectly valid URL with no password
(e.g. `postgresql://user@host:6543/db`, or any URL where psycopg auth comes from
`PGPASSWORD`/`.pgpass`/IAM), `parsed.password` is `None`, the `if` is skipped, and
control falls through to `return "<unparseable url>"`. Confirmed: input
`postgresql://user@host:6543/db` returns `<unparseable url>`. The bootstrap then
prints a misleading "Bootstrap target: <unparseable url>" for a URL that is fully
parseable and safe. Empty string also yields `<unparseable url>`, conflating "no
URL" with "has-secret-stripped". This is a diagnostic-quality bug, not a leak (it
fails closed), but it will mislead an operator during exactly the kind of
connection-troubleshooting this redaction exists to support.
**Fix:** Return the reconstructed URL in all parseable cases; reserve the fallback
for genuine parse failures:
```python
try:
    parsed = urllib.parse.urlparse(raw_url)
    if not parsed.scheme:           # genuinely not a URL
        return "<unparseable url>"
    if parsed.password:
        safe_netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@", 1)
        parsed = parsed._replace(netloc=safe_netloc)
    return urllib.parse.urlunparse(parsed)
except Exception:
    return "<unparseable url>"
```

### WR-06: Business upsert can desync `id` from the fixed seed literal → FK failure on re-seed

**File:** `app/db/seed.py:275-291` (and the employee FK at `schema.sql:30`)
**Issue:** Businesses upsert on the natural key `ON CONFLICT (contact_email)` but
the seed also carries fixed `id` literals (`b0000001-…`) that employees reference
via `business_id`. If a `businesses` row already exists with a matching
`contact_email` but a **different** `id` (an older seed run with different UUIDs, a
manual insert, a restored backup), the `ON CONFLICT ... DO UPDATE` clause does not
touch `id`, so the row keeps its old id. The subsequent employee inserts then use
`business_id = b0000001-…`, which no longer exists, and the FK
(`employees.business_id REFERENCES businesses(id)`) aborts the entire transaction.
`test_idempotent_reseed` only covers the clean case where seed itself inserted the
ids, so this path is untested. For a demo seed with stable conventions this is
unlikely day-to-day, but it makes "idempotent" a conditional claim.
**Fix:** Either upsert businesses on the primary key `id` (the truly stable
identity) and treat `contact_email` as a plain updatable column with its own UNIQUE
constraint, or explicitly document that seed assumes a clean/owned `businesses`
table. Recommended:
```sql
INSERT INTO businesses (id, name, contact_email, pay_period)
VALUES (%s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE
  SET name = EXCLUDED.name,
      contact_email = EXCLUDED.contact_email,
      pay_period = EXCLUDED.pay_period,
      updated_at = now()
```

### WR-07: `Employee` compensation invariant checks presence but not mutual exclusivity

**File:** `app/models/roster.py:65-82`
**Issue:** The docstring (lines 41-44) and class comment state the compensation
fields are "mutually exclusive per pay_type," but `_require_compensation_field`
only validates *presence* of the matching field. An hourly employee with both
`hourly_rate` and a stray `annual_salary` validates cleanly (confirmed:
`pay_type="hourly", hourly_rate=18.50, annual_salary=99999` is accepted). The
unused/contradictory comp field then sits in the row and could be silently picked
up by a future calc path or confuse the eval. The contract claims an invariant it
does not enforce.
**Fix:** Enforce exclusivity in the same validator:
```python
if self.pay_type == "hourly":
    if self.hourly_rate is None:
        raise ValueError("hourly_rate is required when pay_type is 'hourly'")
    if self.annual_salary is not None:
        raise ValueError("annual_salary must be None when pay_type is 'hourly'")
if self.pay_type == "salary":
    if self.annual_salary is None:
        raise ValueError("annual_salary is required when pay_type is 'salary'")
    if self.hourly_rate is not None:
        raise ValueError("hourly_rate must be None when pay_type is 'salary'")
```

## Info

### IN-01: Unused `import enum` in contracts.py

**File:** `app/models/contracts.py:12`
**Issue:** `import enum` is never referenced (`enum` has 0 name-uses and 0
attribute-uses in the module — confirmed via AST). Leftover from an earlier draft;
the `RunStatus` enum lives in `status.py`.
**Fix:** Delete line 12. (`ruff` is in the dev stack and would flag this as `F401`.)

### IN-02: Tautological assertion provides no coverage

**File:** `tests/test_status_drift.py:89`
**Issue:** `assert "psycopg" not in sys.modules or True` is `True` unconditionally
(`X or True` is always `True`), so it asserts nothing. The meaningful assertion is
the next one (line 91, `app.db.supabase` not imported). The dead line reads as if
it guards something.
**Fix:** Remove line 89, or replace with the intended guard
`assert "app.db.supabase" not in sys.modules` (already present at 91) — i.e. just
delete the no-op.

### IN-03: `NameMatchResult.matched_employee_id` not constrained against `match_type`

**File:** `app/models/roster.py:108-122`
**Issue:** The docstring says `matched_employee_id` is "None when match_type ==
'unknown'", but nothing enforces the relationship: an `unknown` match can carry a
non-None id, and an `exact` match can carry `None`. This is a softer cousin of
WR-07 — a documented invariant the type does not hold. Lower severity because this
type is produced by code in a later phase, not by external input.
**Fix:** Add a `@model_validator(mode="after")` tying `matched_employee_id is None`
to `match_type == "unknown"`, or downgrade the docstring to a non-binding note.

### IN-04: `get_pool()` singleton is never closed

**File:** `app/db/supabase.py:24-46`
**Issue:** The module-level pool is created lazily and never `.close()`d. For the
long-lived Render web service this is acceptable (process lifetime == pool
lifetime). It is noted only because the test suite imports the same module and the
pool persists across the pytest process; if a future fixture opens it, nothing
tears it down. Not a leak in the deployed app.
**Fix:** Optional — expose a `close_pool()` for test teardown / graceful shutdown
and call it from a FastAPI `lifespan` shutdown handler when the app is wired up.

### IN-05: `--reset` commits drops before applying schema (non-atomic window)

**File:** `app/db/bootstrap.py:84-98`
**Issue:** Under `--reset`, the drop loop runs then `conn.commit()` (line 93)
*before* `schema_sql` is applied and committed (97-98). If `schema.sql` application
fails, the database is left with all tables dropped and not recreated — a
half-applied state. The module docstring frames reset as "drops … then recreates";
the intermediate commit means a failure between the two steps is not recoverable by
re-running without manual intervention. Low severity: `--reset` is opt-in and
operator-driven, and the dropped state is itself re-runnable. Worth a one-line
docstring note or folding both steps into a single committed unit.
**Fix:** Drop the early `conn.commit()` (line 93) so the DROPs and the CREATE
DDL commit together as one unit:
```python
if reset:
    for table in _DROP_ORDER:
        conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
# fall through to schema apply; single commit at the end
schema_sql = _SCHEMA_SQL.read_text()
conn.execute(schema_sql)
conn.commit()
```
(Note: the schema's `DO $$…$$` block and `CREATE EXTENSION` are fine inside the
same transaction in Postgres.)

---

_Reviewed: 2026-06-21T06:24:17Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
