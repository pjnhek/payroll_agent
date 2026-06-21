---
phase: 1
reviewers: [codex]
reviewed_at: 2026-06-21T05:36:25Z
review_round: 2
plans_reviewed: [01-01-PLAN.md, 01-02-PLAN.md, 01-03-PLAN.md]
prior_round_findings_resolved: [HIGH-1, HIGH-2, HIGH-3, HIGH-4, HIGH-5]
---

# Cross-AI Plan Review — Phase 1 (Round 2)

Round 1 (5 HIGH cross-plan-seam findings) was incorporated via `/gsd-plan-phase 1 --reviews`
and committed as `da615ea`. This is Codex's re-review of the revised, committed plans.

## Codex Review (Round 2)

### Prior-Findings Resolution

1. **RESOLVED** — `01-02` adds `CONSTRAINT uq_employee_business_name UNIQUE (business_id, full_name)` and `updated_at` to both `businesses` and `employees`; `01-03` upserts now target those exact columns.
2. **RESOLVED** — `01-02` declares `payroll_runs.source_email_id UUID` without inline FK, then adds `fk_payroll_runs_source_email` in a guarded post-table `DO $$ ... ALTER TABLE ... $$` block.
3. **RESOLVED** — `01-01` makes `ExtractedEmployee` hours fields `Decimal | None`, so missing-hours extraction can reach `decide()` instead of failing Pydantic first.
4. **RESOLVED** — `01-03` round-trip test explicitly bans `SELECT *` and requires `psycopg.rows.dict_row` plus an Employee-field-only column list.
5. **RESOLVED** — `01-03` cap-straddle prose now compares `per_period_gross` wages to `remaining_cap` wage base, not tax dollars to cap dollars.

### 01-01-PLAN.md

**Summary:** Strong revision. Preserves the D-07/D-08 contract seam, keeps `extra="forbid"`, adds nullable extraction hours, adds Literal tightening, and makes the missing-hours gate case testable.

**Strengths:**
- `Decision` keeps `model_action` and `final_action` structurally separate.
- Decimal serialization is covered by a persistent test.
- `Roster`, `Employee`, `NameMatchResult`, `ValidationIssue` close the D-14 eval seam.
- `.gitignore`, `.env.example`, pinned `python-multipart` address prior security/dependency gaps.

**Concerns:**
- **HIGH** — `Employee` does not specify conditional validation for `pay_type` vs compensation fields. With `hourly_rate: Decimal | None` and `annual_salary: Decimal | None` both nullable and no rule requiring hourly→hourly_rate / salary→annual_salary, the claim "missing FOUND-06 field fails at seed time" is not genuinely enforced.
- **MEDIUM** — `NameMatchResult.match_type` omits deterministic case/whitespace paths even though requirements call out exact / case / whitespace / alias. Literal list is only `"exact","alias","llm_typo","llm_nickname","unknown"`.
- **MEDIUM** — `pyproject.toml` instructions omit a `[build-system]` table while verification relies on `pip install -e .`. Add an explicit setuptools backend to avoid editable-install ambiguity.
- **LOW** — Decimal fields typed as `Decimal`, but Pydantic generally coerces JSON numbers/floats unless strict validation is added. Serialization guard is good; input-side "never float" is not fully enforced.

**Suggestions:** Add `@model_validator(mode="after")` on `Employee` for pay-type compensation completeness; add basic bounds (confidence, retirement pct, pay periods, non-negative calc inputs). Add deterministic match types (`case_insensitive`, `whitespace_normalized`) or rename `exact` to intentionally cover normalized exact.

**Risk Assessment: MEDIUM** — core contract fixes sound, but missing conditional validation weakens the seed-time failure guarantee.

### 01-02-PLAN.md

**Summary:** Schema revision resolves the prior DDL blockers and aligns with the seed upsert plan. The deferred FK block is idempotent as written.

**Strengths:**
- `CREATE EXTENSION IF NOT EXISTS pgcrypto` covers local `gen_random_uuid()`.
- `UNIQUE(message_id)` and `UNIQUE(business_id, full_name)` present.
- `prepare_threshold=None` required in both pool and bootstrap paths.
- Status drift test uses static parsing, avoids deprecated `consrc`.
- `--reset` is opt-in and uses `DROP TABLE IF EXISTS ... CASCADE`.

**Concerns:**
- **MEDIUM** — frontmatter `files_modified` omits `app/db/bootstrap.py`, even though Task 2 and artifacts require it. If tooling treats frontmatter as authoritative, the main executable for the plan can be missed (also affects worktree-overlap detection in execute-phase).
- **MEDIUM** — schema does not enforce the pay-type compensation invariant. `hourly_rate` / `annual_salary` nullable without a CHECK tying them to `pay_type`, so DB rows can be calc-incomplete.
- **LOW** — circular FK valid, but both sides default to restrictive delete behavior. Acceptable for Phase 1; future cleanup/delete flows will need explicit handling.

**Suggestions:** Add `app/db/bootstrap.py` to `files_modified`. Consider a table CHECK (hourly requires `hourly_rate IS NOT NULL`, salary requires `annual_salary IS NOT NULL`) unless the invariant is enforced only in Pydantic.

**Risk Assessment: LOW-MEDIUM** — prior schema blockers fixed; remaining risk is metadata drift and unenforced calc-input invariants.

### 01-03-PLAN.md

**Summary:** Seed plan is much stronger: transactional writes, structured dry run, stable UUIDs, containment tests, idempotent upserts, corrected SS cap math.

**Strengths:**
- `SeedResult` carries both businesses and employees.
- `seed(dry_run=True)` inspectable without DB access.
- Live test has the extra `ALLOW_DB_RESET=1` destructive guard.
- Round-trip test avoids both tuple rows and extra-column collisions.
- Hero name correctly framed as a Phase 2 candidate, not proof.

**Concerns:**
- **MEDIUM** — Business 3 is `pay_period: "biweekly"`, but Sandra Kim has `pay_periods_per_year: 52`. Conflicts with the business pay cadence; can produce wrong annualization/withholding if Summit Tech runs include her.
- **MEDIUM** — Task 2 verify command pipes pytest through `head -20` without `pipefail`, which can mask a failing pytest run.
- **LOW** — test note says Pydantic will reject floats because fields are `Decimal`; not reliable without strict validation. The explicit `isinstance(..., Decimal)` assertion is the real guard.
- **LOW** — `pytest.mark.integration` used but no marker registration planned. Usually harmless; noisy under stricter warning settings.

**Suggestions:** Set Sandra Kim's `pay_periods_per_year` to `26` (or move her to a weekly business). Remove the `| head -20` verification pipe or run with pipefail. Add a pytest marker declaration in `pyproject.toml`.

**Risk Assessment: MEDIUM** — seed mechanics solid, but the business/pay-period inconsistency can leak into later calc tests and demos.

---

## Consensus Summary (Round 2)

Single reviewer (Codex). **All 5 Round-1 HIGH findings confirmed RESOLVED; no regressions introduced by the edits.** Overall risk dropped (01-02: MEDIUM-HIGH → LOW-MEDIUM). The new findings are a *different, lower* tier — data-consistency and validation-strength items, not DDL/composition blockers.

### New Findings — triage for a possible Round-2 revision

**Worth fixing before execute (cheap, real):**
- **[01-01 HIGH + 01-02 MED] pay_type ↔ compensation invariant not enforced.** Nothing requires an hourly employee to have `hourly_rate` (or salary→`annual_salary`), so the plan's "missing calc input fails at seed time" promise (D-10/FOUND-06) isn't actually guaranteed. Fix: add an `Employee` `@model_validator(mode="after")`. (DB CHECK is optional/secondary.) This is the one genuinely thesis-relevant new finding.
- **[01-03 MED] Seed data inconsistency: Sandra Kim `pay_periods_per_year: 52` under a biweekly business.** Internal contradiction in the seed; would feed a wrong number into Phase 3 calc/demo. Fix: set to `26` (or move her). Pure data edit.
- **[01-02 MED] `files_modified` omits `app/db/bootstrap.py`.** Frontmatter drift; execute-phase uses `files_modified` for worktree-overlap detection, so this is worth correcting. One-line frontmatter add.

**Nice-to-have / defensible to defer:**
- [01-01 MED] `pyproject.toml` missing explicit `[build-system]` backend — add to de-risk `pip install -e .`.
- [01-01 MED] `match_type` Literal omits deterministic case/whitespace paths — but reconcile against CONTEXT (D-14 lists exact/alias/typo/nickname; the deterministic case/whitespace normalization may belong to the *matcher logic* in Phase 2, not the result enum). Flag for Phase 2, don't necessarily expand the enum now.
- [01-03 MED] `| head -20` without `pipefail` can mask pytest failure — trivial verify-command hardening.
- [LOW] strict-Decimal input coercion, pytest marker registration — minor.

### Divergent Views
None — single reviewer.
