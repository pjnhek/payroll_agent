---
phase: 01-thin-foundation
reviewed: 2026-06-20T00:00:00Z
depth: deep
files_reviewed: 14
files_reviewed_list:
  - app/config.py
  - app/db/bootstrap.py
  - app/db/schema.sql
  - app/db/seed.py
  - app/db/supabase.py
  - app/models/__init__.py
  - app/models/contracts.py
  - app/models/roster.py
  - app/models/status.py
  - pyproject.toml
  - requirements.txt
  - tests/test_bootstrap_safe_url.py
  - tests/test_models_contracts.py
  - tests/test_seed_roundtrip.py
  - tests/test_status_drift.py
findings:
  critical: 0
  warning: 4
  info: 4
  total: 8
status: issues_found
---

# Phase 1: Code Review Report (DEEP re-review)

**Reviewed:** 2026-06-20
**Depth:** deep (cross-file: model ↔ schema ↔ seed ↔ tests)
**Files Reviewed:** 14
**Status:** issues_found

## Summary

The prior-review fixes (WR-01 through WR-07, IN-01/IN-02) all hold up under
empirical re-test. Test baseline reproduced locally: **53 passed, 8 skipped, 0
failed** (no live Postgres in env). Security surface is clean: no hardcoded
secrets, no `eval/exec/os.system`, all seed SQL is parameterized, and the only
f-string-into-SQL interpolation in `bootstrap.py` is the hardcoded `_DROP_ORDER`
constant list (no injection vector). `_safe_db_url` was stress-tested against
`@`/`:`/percent-encoded passwords and never leaks. Module imports are correctly
lazy (no `DATABASE_URL` needed for the CI/dry-run path). Employee
model ↔ seed ↔ schema column sets are in exact agreement. The status-drift guard
regex was mutation-tested and correctly anchors on `status` (not `substatus`).

**No BLOCKERS.** The fix pass was substantially correct. However, deep cross-file
analysis surfaces one **incomplete WR-01 fix** and three other defects that a
per-file pass misses — all at integration seams between the model layer, the SQL
schema, and the seed/test invariants. The unifying theme: **the bounds/CHECK
discipline that was applied to *some* fields was not applied uniformly across the
layers that share the same semantic value.**

## Warnings

### WR-01 (incomplete): `PaystubLineItem.match_confidence` has no bound — WR-01 fix missed the one confidence field that reaches the DB

**File:** `app/models/contracts.py:136`
**Issue:** WR-01 added `Field(ge=0, le=1)` to `Decision.confidence`
(`contracts.py:112`) and `NameMatchResult.confidence` (`roster.py:141`). But
`PaystubLineItem.match_confidence` — the **same 0–1 semantic** and the field that
actually maps to the `paystub_line_items.match_confidence NUMERIC(4,3)` column —
was left as bare `Decimal` with **no bound**. Empirically verified: the model
accepts `match_confidence=Decimal("42.0")`. Two concrete failures follow:

- A value `> 9.999` (e.g. `42.0`) passes the contract, then **crashes the INSERT
  with a numeric-overflow error** at the DB boundary (`NUMERIC(4,3)` max is
  `9.999`) — a runtime failure deep in the pipeline rather than at construction.
- A value in `(1, 9.999]` (e.g. a buggy `1.5` confidence) passes both the model
  *and* the DB and **silently corrupts the audit record** that the gate decision
  is supposed to make legible.

This is the exact class of bug WR-01 set out to close; it was simply applied to 2
of the 3 confidence fields and missed the one touching the DB.
**Fix:**
```python
# app/models/contracts.py — PaystubLineItem
match_confidence: Decimal = Field(ge=0, le=1)
```
Then add a contract test mirroring `test_name_match_result_rejects_confidence_above_one`
for `PaystubLineItem`.

### WR-08: W-4 / YTD dollar fields accept negatives in both the model and the schema — corrupts the SS cap and the Pub 15-T worksheet

**File:** `app/models/roster.py:56-61`, `app/db/schema.sql:39-42`
**Issue:** WR-01 added `ge=0` to *rates and hours* but not to the W-4/YTD dollar
fields. Empirically verified: `Employee(... step_3_dependents=Decimal("-5000"),
step_4a_other_income=Decimal("-1"), step_4b_deductions=Decimal("-1"),
ytd_ss_wages=Decimal("-99999"))` constructs successfully, and the schema columns
(`step_3_dependents/4a/4b NUMERIC(12,2)`, `ytd_ss_wages NUMERIC(14,2)`) carry
**no CHECK**, so the bad value writes cleanly. Concrete harm in later phases:

- A negative `ytd_ss_wages` makes `remaining_cap = 184500 - ytd_ss_wages` exceed
  the wage base, **breaking the exact SS-cap straddle logic** the Thomas Bergmann
  fixture and `test_seed_high_earner_ss_cap_straddle` are built to exercise.
- `step_3_dependents` is *subtracted* in the Pub 15-T worksheet; a negative value
  **inflates** withholding nonsensically — a silently-wrong paystub, which
  CLAUDE.md flags as the highest-bug-risk failure mode.

The project gates the calc engine behind validation precisely so a bad input
"never reaches the calc engine mid-demo" — these four fields are an unvalidated
hole in that gate.
**Fix:**
```python
# app/models/roster.py
step_3_dependents:    Decimal = Field(ge=0)
step_4a_other_income: Decimal = Field(ge=0)
step_4b_deductions:   Decimal = Field(ge=0)
ytd_ss_wages:         Decimal = Field(ge=0)
```
Optionally mirror with `CHECK (... >= 0)` in `schema.sql` as the runtime backstop
(consistent with the project's "reconciliation check as backstop" philosophy).

### WR-09: Dual-source enum constraints (`pay_type`, `filing_status`, `pay_periods_per_year`) have NO drift guard — only `status` is protected

**File:** `app/models/roster.py:42,54,65` vs `app/db/schema.sql:33,37,43`
(test gap: `tests/test_status_drift.py`)
**Issue:** `test_status_drift.py` exists *because* a value enumerated in both
Python and SQL is a known drift risk — it set-equality-checks the `status` CHECK
against `RunStatus` and fails CI on divergence. But three other fields are
enumerated in **both** the Pydantic `Literal` and a SQL `CHECK` with **no
equivalent guard**:

- `pay_type`: `Literal["hourly","salary"]` vs `CHECK (pay_type IN ('hourly','salary'))`
- `filing_status`: `Literal["single","married_jointly","married_separately"]` vs the matching CHECK
- `pay_periods_per_year`: `Literal[12,24,26,52]` vs `CHECK (... IN (12,24,26,52))`

`test_employee_rejects_invalid_pay_periods` only tests the *model* side; if the
schema CHECK and the Literal drift apart (someone adds `24` to one but not the
other, or relaxes a CHECK), nothing fails. This is a coverage gap at the model↔schema
seam and directly contradicts CLAUDE.md's "well-tested is non-negotiable" + the
DRY principle the status guard already embodies.
**Fix:** Generalize the status-drift test into a parameterized
`test_enum_check_drift` that, for each `(column, python_value_set)` pair, parses
the column's CHECK list out of `schema.sql` and asserts set-equality — the same
mechanism already proven for `status`.

### WR-10: `business.pay_period` ↔ `employee.pay_periods_per_year` consistency is enforced only by a hand-maintained comment, and tested for only 1 of 3 businesses

**File:** `app/db/seed.py:223-226` (CADENCE VERIFICATION comment),
`tests/test_seed_roundtrip.py:195-213`
**Issue:** The relationship "a `weekly` business ⇒ its employees are `52`;
`biweekly` ⇒ `26`" is a genuine cross-table invariant with **no enforcement**:
no FK-level CHECK, no model holding both sides, only the static comment block at
`seed.py:223-226` doing the mapping by hand. The only test
(`test_business3_employees_have_biweekly_cadence`) checks Business 3 and
**hardcodes `26`**; Businesses 1 and 2 (`weekly` ⇒ `52`) have their cadence
consistency **unproven**. I verified the seed data is currently consistent across
all 6 employees — but nothing locks it, so a future edit (the same class of bug
"FIX B" already corrected once for Sandra Kim) would pass CI. An invariant a
comment claims but no test proves is exactly the gap to close here.
**Fix:** Add a data-driven test that maps each `pay_period` →
expected `pay_periods_per_year` and asserts every seed employee matches its own
business — covering all three businesses, not one:
```python
EXPECT = {"weekly":52, "biweekly":26, "semi_monthly":24, "monthly":12}
biz = {str(b["id"]): b["pay_period"] for b in result.businesses}
for e in result.employees:
    assert e.pay_periods_per_year == EXPECT[biz[str(e.business_id)]]
```

## Info

### IN-06: `PaystubLineItem` computed-output fields (hours, gross_pay, net_pay) are unbounded

**File:** `app/models/contracts.py:137-149`
**Issue:** Verified the model accepts `hours_regular=Decimal("-40")` and
`gross_pay=Decimal("-1")`. These are the *computed* outputs, so a negative is a
calc-engine bug rather than bad input — but a `ge=0` floor would catch such a bug
at the contract boundary instead of letting a negative net-pay paystub render.
Lower priority than WR-01/WR-08 because nothing untrusted populates these in
Phase 1. **Fix:** Add `Field(ge=0)` to the non-nullable money/hours fields when
the calc engine lands in Phase 3.

### IN-07: `InboundEmail` marks `subject/from_addr/to_addr/body_text` non-nullable, but the `email_messages` schema columns are nullable

**File:** `app/models/contracts.py:44-47` vs `app/db/schema.sql:116-119`
**Issue:** `InboundEmail.subject/from_addr/to_addr/body_text` are required
non-Optional, while the matching `email_messages` columns have no `NOT NULL`.
Reading a row with a NULL `subject` back into `InboundEmail(**row)` would raise
`ValidationError`. Defensible under D-07 (these contracts are *parsed-input*
shapes, not 1:1 DB mirrors) and no read path exists yet in Phase 1, so this is
informational. **Fix:** When the ingest read path is built, either add `NOT NULL
DEFAULT ''` to those schema columns or make the model fields `str | None` to match.

### IN-08: Misleading comment in `seed.py` — claims `model_dump(mode="json")` is used, but it isn't

**File:** `app/db/seed.py:306`
**Issue:** The comment "model_dump(mode="json") produces JSON-safe values (D-06
pattern)" precedes code that passes **Pydantic-native** values (`emp.hourly_rate`
as `Decimal`, `emp.known_aliases` as `list`) directly to psycopg — `model_dump`
is never called here. The values adapt correctly (verified: `Decimal` → numeric,
`list[str]` → `TEXT[]`, including the empty-list case), so behavior is correct;
only the comment is wrong and could mislead a maintainer into thinking JSON
coercion happens. **Fix:** Delete or correct the comment to "psycopg adapts
Pydantic-native Decimal/list/bool values directly."

### IN-09: Dev environment runs Python 3.13.5; CLAUDE.md pins 3.12 and `pyproject` allows `>=3.12`

**File:** `pyproject.toml:4`
**Issue:** The `.venv` interpreter is 3.13.5, but CLAUDE.md mandates a `python:3.12-slim`
runtime pin "to avoid 3.13/3.14 wheel-availability edge cases for native deps."
The test suite therefore validates on a *different* interpreter than the target
runtime. No code defect — and no Dockerfile exists yet (out of Phase 1 scope) —
but worth flagging so the Docker pin lands on 3.12 and a 3.12 dev venv is used to
keep dev/prod parity. **Fix:** Recreate the dev venv on 3.12, and pin
`requires-python = ">=3.12,<3.13"` if 3.13 parity is not intended.

---

## Re-verification of prior findings (all confirmed fixed, no regressions)

Empirically re-checked; each holds:

- **WR-01** (numeric bounds) — enforced under `from __future__ import annotations`
  (verified `ExtractedEmployee` `ge=0` and `Decision`/`NameMatchResult` `le=1`
  all fire). **Incomplete only** for `PaystubLineItem.match_confidence` (see
  WR-01-incomplete) and the W-4/YTD fields (see WR-08).
- **WR-02** (`pay_periods_per_year` Literal) — `Literal[12,24,26,52]` rejects
  `0,-1,13,1`; accepts all four legal values. (Drift-guard gap only — see WR-09.)
- **WR-03** (module-level psycopg import in seed test) — present at
  `test_seed_roundtrip.py:18-20`.
- **WR-04** (`_DecimalModel`/per-field serializers removed) — gone; default
  Pydantic v2 Decimal→string serialization verified for `gross_pay`,
  `state_withholding=None`, and `Decision.confidence`.
- **WR-05** (`_safe_db_url` password-less) — verified for password-less URLs and
  stress-tested against `@`/`:`/percent-encoded passwords; no leak in any case.
- **WR-06** (businesses `ON CONFLICT (id)`) — present at `seed.py:285`, with a
  correct rationale comment for not conflicting on `contact_email`.
- **WR-07** (mutual exclusivity) — `_require_compensation_field` rejects a stray
  off-type comp field; both directions tested.
- **IN-01/IN-02** — no unused `enum` import in roster; no tautological assert.

Deferred-by-design items reconfirmed as low-harm in this phase:

- **IN-04** (pool never closed) — acceptable for a long-lived process; no leak in
  the test path (dry-run never opens the pool).
- **IN-05** (`--reset` non-atomic window: drops commit at `bootstrap.py:97`
  before the create commits at `:102`) — mitigated by `DROP ... IF EXISTS` +
  `CREATE ... IF NOT EXISTS` making a re-run self-healing; acceptable for a dev
  admin tool. No re-raise.

Confirmed clean (no finding): SQL parameterization in `seed.py`; `_DROP_ORDER`
interpolation safety; lazy config (imports work without `DATABASE_URL`);
multi-statement `schema.sql` apply (psycopg3 simple-query protocol runs it; the
deferred-FK `DO $$` block is idempotent); status-drift regex anchoring; seed
atomicity (`conn.transaction()` on a non-autocommit pooled connection); Employee
model↔seed↔schema column-set agreement; seed values fit all `NUMERIC(p,s)`
precisions.

---

_Reviewed: 2026-06-20_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
