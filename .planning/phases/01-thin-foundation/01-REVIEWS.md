---
phase: 1
reviewers: [codex]
reviewed_at: 2026-06-21T05:15:22Z
plans_reviewed: [01-01-PLAN.md, 01-02-PLAN.md, 01-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 1

## Codex Review

**Overall Summary**

The plans are strong on phase boundaries and correctly internalize most of the documented gotchas: `prepare_threshold=None`, `--reset`, Decimal JSON serialization, D-14 pure contract shapes, and the SS wage-base straddle. The main risks are not conceptual; they are execution seams between plans: schema constraints needed by seed are missing from Plan 02, Plan 03 assumes columns Plan 02 does not create, and the contracts may be too strict to represent "missing field" extraction cases that later phases need to gate cleanly.

**01-01 Plan Review**

**Strengths**
- Correctly expands FOUND-03 beyond the four named models to include `Roster`, `Employee`, `NameMatchResult`, and `ValidationIssue`.
- Encodes the key thesis well: `Decision.model_action` and `Decision.final_action` are structurally separate.
- Uses Decimal from the contract layer onward, which supports both DB JSONB persistence and later penny-level calc tests.
- Keeps contracts as pipeline values rather than DB row mirrors, matching D-07/D-14.

**Concerns**
- **HIGH:** `ExtractedEmployee` requires every hours field as `Decimal`. That makes missing-hour cases fail Pydantic validation before deterministic field validation can produce `missing_fields` and a gated clarification. The system needs to represent incomplete extraction output.
- **MEDIUM:** Action-like fields are plain `str`: `model_action`, `final_action`, `pay_type`, `filing_status`, `match_type`, `issue_type`. This weakens the shared contract and lets invalid values pass.
- **MEDIUM:** No persistent contract tests are planned. The plan uses inline verification commands, but regressions in Decimal serialization, gate-shape validation, and enum membership should be CI tests.
- **MEDIUM:** `.gitignore` is not in `files_modified`, but verification requires `.env` not be committed and `.gitignore` contain `.env`.
- **LOW:** `python-multipart` is unpinned despite the threat model saying runtime deps are exact-pinned.

**Suggestions**
- Make extraction fields that can be missing `Decimal | None`, or introduce a raw extraction model that allows missing values before validation.
- Use `Literal[...]` or small enums for action/status/type fields.
- Add `tests/test_models_contracts.py` covering imports, Decimal JSON strings, `model_action != final_action`, and invalid enum-like values.
- Add `.gitignore` with `.env`.
- Pin `python-multipart`.

**Risk Assessment: MEDIUM**

The contract direction is right, but the required-hours issue can distort later LLM/error handling by turning clarification cases into parse failures.

**01-02 Plan Review**

**Strengths**
- Correctly uses `TEXT + CHECK` for status rather than a native Postgres enum.
- Includes the D-03 drift guard between `RunStatus` and SQL.
- Correctly calls out `prepare_threshold=None` for Supavisor transaction pooling.
- Adds an opt-in `--reset` path while keeping the default bootstrap non-destructive.
- Includes live-DB verification for duplicate `message_id`, which directly proves FOUND-02.

**Concerns**
- **HIGH:** `email_messages` and `payroll_runs` have circular FKs, but the plan does not settle the exact implementation. Inline `email_messages.run_id REFERENCES payroll_runs(id)` before `payroll_runs` exists will fail.
- **HIGH:** Plan 03 depends on `UNIQUE (business_id, full_name)` for employee upserts, but Plan 02 does not create it. That constraint belongs in `schema.sql` now.
- **HIGH:** Plan 03 upserts businesses with `updated_at=now()`, but the Plan 02 `businesses` schema only has `created_at`. This will break seed execution unless schema or seed is changed.
- **MEDIUM:** The reset drop order is fragile if circular FKs exist. It should explicitly use `DROP TABLE IF EXISTS ... CASCADE` in reverse dependency order.
- **MEDIUM:** The live verification says "exactly 6 tables"; that may be brittle on Supabase or reused DBs. Better assert the required six exist in `public`.
- **LOW:** Must-haves mention `consrc`, which is obsolete. Later verification uses `pg_get_constraintdef(oid)`, which is the right form.

**Suggestions**
- Define `email_messages.run_id UUID` without inline FK, then add the FK after `payroll_runs` using an idempotent `DO $$ IF NOT EXISTS ... ALTER TABLE ... $$` block, or defer that FK.
- Add `UNIQUE (business_id, full_name)` to `employees` in Plan 02.
- Either add `updated_at` to `businesses` and `employees`, or remove `updated_at=now()` from Plan 03 seed upserts.
- Add `CREATE EXTENSION IF NOT EXISTS pgcrypto;` if relying on `gen_random_uuid()` for local Postgres compatibility.
- Consider a DB integration test for duplicate `message_id`, skipped when `DATABASE_URL` is absent.

**Risk Assessment: MEDIUM-HIGH**

The schema intent is solid, but unresolved circular FK handling and missing seed-required constraints are likely to cause immediate implementation failures.

**01-03 Plan Review**

**Strengths**
- Good coverage-driven seed design: 3 businesses, mixed hourly/salary, aliases, all filing statuses, Step-2 coverage, and a Phase 2 hero candidate.
- Correctly treats the name-mismatch case as a candidate, not final proof.
- Strong use of `dry_run=True` to validate seed data without DB access.
- Correctly includes a high earner whose period wages straddle the 2026 SS wage base.
- Integration tests skip when no live DB is configured.

**Concerns**
- **HIGH:** The prose cap-straddle math for the hourly example is wrong: it compares the remaining wage cap `$600` to the tax amount `$250.33`. The correct condition is period SS wages/gross exceeding the remaining wage base. The Thomas salary case and test code use the right condition.
- **HIGH:** `test_employee_roundtrip` says `SELECT * FROM employees` then `Employee(**row)`, but `Employee` has `extra="forbid"` and the DB row includes `created_at`. Also psycopg returns tuples unless a dict row factory is used.
- **HIGH:** Seed upsert depends on Plan 02 schema changes that are not guaranteed: `UNIQUE (business_id, full_name)` and possibly `updated_at`.
- **MEDIUM:** `bootstrap(reset=True)` in integration tests is dangerous with only `DATABASE_URL` as the guard. A second guard like `ALLOW_DB_RESET=1` or requiring a test/local DB name would reduce accidental destructive resets.
- **MEDIUM:** `seed(dry_run=True)` returns only employees, but the behavior checks distinct business contact emails. Return a small structured result containing both businesses and employees.
- **LOW:** The Plan 3 text sounds a little too confident that David Reyez will produce model-process + low confidence. Keep it explicitly as a candidate until Phase 2 proves it.

**Suggestions**
- Fix the cap-straddle explanation to: `remaining_cap > 0 and period_gross > remaining_cap`.
- In round-trip tests, select only Employee fields and use `psycopg.rows.dict_row`, or explicitly map tuple rows to model fields.
- Move all seed-required constraints into Plan 02 schema.
- Add a destructive-test guard beyond `DATABASE_URL`, especially because `bootstrap(reset=True)` is in a fixture.
- Wrap seed writes in an explicit transaction.

**Risk Assessment: MEDIUM**

The seed content is well chosen, but the integration details need tightening or the live round-trip tests will fail for schema/test-shape reasons rather than meaningful requirement failures.

---

## Consensus Summary

Single external reviewer (Codex). No cross-reviewer consensus to synthesize; the items below are Codex's findings, triaged by severity. The plans are conceptually sound and internalize the documented gotchas — every HIGH finding is a **cross-plan execution seam**, not a design flaw, and each is concrete and verifiable.

### Agreed Strengths
- Contract layer correctly expands beyond the four FOUND-03 names to the full D-14 set; `model_action`/`final_action` separation is encoded in the type.
- Schema correctly uses `TEXT + CHECK` (not native enum) with the D-03 drift guard; `prepare_threshold=None` and the opt-in `--reset` are present.
- Seed design is genuinely coverage-driven, treats the hero name-mismatch as a Phase 2 candidate (not locked proof), and seeds the SS wage-base straddle.

### Agreed Concerns (HIGH — fix before execution)
1. **Cross-plan schema/seed mismatch (01-02 ↔ 01-03):** 01-03's employee upsert needs `UNIQUE (business_id, full_name)`, which 01-02 never creates; 01-03 upserts businesses with `updated_at=now()` but 01-02's `businesses` has only `created_at`. Both break seed execution at runtime. → Move all seed-required constraints/columns into 01-02's `schema.sql`.
2. **Circular FK ordering (01-02):** `email_messages.run_id → payroll_runs(id)` declared inline before `payroll_runs` exists will fail. → Define `run_id UUID` first, add the FK via an idempotent `ALTER TABLE` after both tables exist (or defer the FK).
3. **Over-strict extraction contract (01-01):** required-`Decimal` hours fields make a *missing hours* case fail Pydantic validation before `validate`/`decide` can produce `missing_fields` + a gated clarification — turning a clarify case into a parse crash. → Allow `Decimal | None` (or a separate raw-extraction model) so incomplete extraction is representable.
4. **Round-trip test shape (01-03):** `SELECT *` + `Employee(**row)` collides with `extra="forbid"` (row includes `created_at`) and psycopg's default tuple rows. → Select only Employee fields and use `psycopg.rows.dict_row`.
5. **Wrong cap-straddle prose (01-03):** the hourly example compares the `$600` remaining wage cap against a `$250.33` tax amount; correct condition is `remaining_cap > 0 and period_gross > remaining_cap` (the Thomas salary case + test code are already correct). → Fix the explanatory text.

### Divergent Views
None — single reviewer.

### MEDIUM/LOW worth folding in
- Use `Literal[...]`/enums for action/status/type string fields (01-01).
- Add a persistent `tests/test_models_contracts.py` rather than inline-only checks (01-01).
- Add `.gitignore` (with `.env`) to `files_modified`; pin `python-multipart` (01-01).
- `DROP ... CASCADE` in reverse-dependency order for `--reset`; `CREATE EXTENSION IF NOT EXISTS pgcrypto;` for `gen_random_uuid()` on local PG; assert the six required tables exist in `public` rather than "exactly 6" (01-02).
- Second destructive-reset guard beyond `DATABASE_URL` (e.g. `ALLOW_DB_RESET=1`); wrap seed writes in one transaction; `seed(dry_run=True)` should return businesses + employees (01-03).
- Keep the David Reyez hero case explicitly a Phase 2-proven candidate (01-03, LOW).
