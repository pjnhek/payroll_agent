---
phase: 01-thin-foundation
plan: 01
subsystem: contracts
tags: [pydantic, contracts, models, scaffold, tdd]
dependency_graph:
  requires: []
  provides:
    - app.models public import surface (RunStatus, InboundEmail, Extracted, ExtractedEmployee, Decision, PaystubLineItem, Roster, Employee, NameMatchResult, ValidationIssue)
    - pyproject.toml importable package declaration
    - requirements.txt pinned runtime deps
    - .env.example with pooler port 6543 placeholder
    - .gitignore with .env excluded
  affects:
    - 01-02-PLAN.md (schema.sql mirrors RunStatus 11-member CHECK constraint verbatim)
    - 01-03-PLAN.md (seed.py validates seeded employees through the same Employee contract)
    - Phase 2 (pipeline stages import these same types as pure-function I/O)
    - Phase 4 (eval imports from app.models — same types, same definitions, D-09 DRY seam)
tech_stack:
  added:
    - pydantic==2.13.4 (v2 BaseModel, ConfigDict, field_serializer, model_validator)
    - pytest (contract test runner)
  patterns:
    - ConfigDict(extra="forbid") on all internal contracts
    - Decimal | None for nullable monetary/hours fields (not float)
    - field_serializer for Decimal→str JSON serialization (D-06)
    - model_validator(mode="after") for conditional compensation invariant (D-10)
    - Literal types for all fields with known complete value sets (Finding #7)
key_files:
  created:
    - pyproject.toml
    - requirements.txt
    - .env.example
    - .gitignore
    - app/__init__.py
    - app/models/__init__.py
    - app/models/status.py
    - app/models/contracts.py
    - app/models/roster.py
    - tests/__init__.py
    - tests/test_models_contracts.py
  modified: []
decisions:
  - D-06 Decimal serialization enforced via field_serializer on each Decimal field rather than a custom json_encoders dict — explicit serializer per field is more robust in Pydantic v2
  - D-08 Decision model_action and final_action both typed as Literal["process", "request_clarification"] per Finding #7 — value sets are definitively known from REQUIREMENTS.md now
  - FIX A compensation invariant implemented via @model_validator(mode="after") on Employee — single enforcement point; every code path that constructs Employee already goes through this contract
  - Used Python 3.13 venv (system default) since Python 3.12 not available locally; pyproject.toml requires-python = ">=3.12" remains the production constraint; contracts are forward-compatible
metrics:
  duration_minutes: 22
  completed_date: "2026-06-20"
  tasks_completed: 2
  files_created: 11
  tests_passing: 15
---

# Phase 1 Plan 1: Project Scaffold + Pydantic v2 Contracts Summary

**One-liner:** Importable `app.models` package with RunStatus (11-member StrEnum), four pipeline I/O contracts (InboundEmail, Extracted, Decision, PaystubLineItem), three D-14 roster shapes (Roster, Employee, NameMatchResult, ValidationIssue), and a 15-test CI-runnable contract suite with no DB dependency.

## What Was Built

### Task 1: Project Scaffold
- `pyproject.toml` declares `payroll-agent` with `[tool.setuptools.packages.find]` targeting `app*` so `eval/` can `from app.models import ...` with a simple `pip install -e .`
- `requirements.txt` pins all 9 runtime deps at CLAUDE.md versions including `python-multipart==0.0.20`
- `.env.example` with `DATABASE_URL` pointing to Supavisor pooler port 6543 — no real secrets; demonstrates the correct connection pattern (D-04)
- `.gitignore` with `.env` on its own line (`grep -c '^\.env$' .gitignore` returns 1) — T-01-01 threat mitigation
- `app/__init__.py` and `tests/__init__.py` as empty namespace files

### Task 2: Pydantic v2 Contracts + Contract Test
- `app/models/status.py`: `RunStatus(str, enum.Enum)` with exactly 11 members in D-02 order — the canonical source Plan 02 mirrors in its CHECK constraint
- `app/models/contracts.py`: `InboundEmail`, `ExtractedEmployee`, `Extracted`, `Decision`, `PaystubLineItem` — all with `ConfigDict(extra="forbid")`
  - `ExtractedEmployee` hours fields typed `Decimal | None` (Finding #3) so missing-hours cases are representable without a parse crash; decide() sees `missing_fields`, not a ValidationError
  - `Decision` carries both `model_action` and `final_action` as `Literal["process", "request_clarification"]` — structurally separate (D-08); `final_action` is the sole branch source per LLM-07
  - All monetary/hours fields typed `Decimal` never `float` (D-05)
  - `field_serializer` on every Decimal field produces JSON strings, not floats (D-06 guard at the DB jsonb boundary)
- `app/models/roster.py`: `Employee`, `Roster`, `NameMatchResult`, `ValidationIssue` (D-14)
  - `Employee` `@model_validator(mode="after")` enforces pay_type ↔ compensation field: `hourly` without `hourly_rate` raises `ValidationError`; `salary` without `annual_salary` raises `ValidationError` (D-10/FOUND-06 FIX A)
  - All Literal-constrained value sets: `pay_type`, `filing_status`, `match_type`, `issue_type` (Finding #7)
  - Carries full FOUND-06 calc-input set: `ytd_ss_wages`, `pay_periods_per_year`, `step_2_checkbox`, `step_3_dependents`, `step_4a_other_income`, `step_4b_deductions`
- `app/models/__init__.py`: re-exports all 10 public types under `__all__`
- `tests/test_models_contracts.py`: 15 tests, 0 DB dependency, all pass

## Test Results

```
15 passed in 0.39s
```

All must-have behaviors verified:
- `from app.models import RunStatus, InboundEmail, Extracted, Decision, PaystubLineItem, Roster, Employee, NameMatchResult, ValidationIssue` exits 0
- `len(RunStatus) == 11` — exact 11-member count
- `PaystubLineItem(...).model_dump(mode='json')['gross_pay']` returns str "1234.56" not float (D-06)
- `Decision(model_action='process', final_action='request_clarification', gate_triggered=True, ...)` validates (D-08 gate case)
- `ExtractedEmployee(submitted_name='Bob', hours_regular=None, ...)` validates (Finding #3)
- `Employee(pay_type='hourly', hourly_rate=None, ...)` raises ValidationError (D-10/FIX A)
- `Employee(pay_type='salary', annual_salary=None, ...)` raises ValidationError (D-10/FIX A)
- `.gitignore` contains `.env` on its own line (T-01-01)

## Deviations from Plan

### Auto-fixed Issues

None. Plan executed exactly as written with one minor implementation detail resolved below.

### Implementation Detail (not a deviation)

**Decimal field_serializer pattern:** The plan suggested `json_encoders = {Decimal: str}` in ConfigDict. In Pydantic v2, `json_encoders` in ConfigDict is deprecated and does not reliably produce string serialization for all field access patterns. Used explicit `@field_serializer` decorators per field instead (the Pydantic v2 idiomatic approach). Functionally identical result: `model_dump(mode='json')` returns `"1234.56"` as a string. No schema or behavior change.

## Known Stubs

None. This plan creates contract types (no data-returning code), so there is no data source to wire. The contracts themselves are the output.

## Threat Surface Scan

No new network endpoints, auth paths, or file access patterns introduced. This plan creates only in-memory Pydantic models and test utilities.

T-01-01 (Information Disclosure — .env/secrets): mitigated. `.env` is in `.gitignore`; `.env.example` committed with placeholder values; `DATABASE_URL` demonstrates pooler port 6543 pattern without real credentials.
T-01-02 (Tampering — pinned deps): mitigated. All 9 runtime deps exact-pinned in `requirements.txt` per CLAUDE.md verified PyPI list (Jun 2026).
T-01-SC (Tampering — pip packages): mitigated. All packages from CLAUDE.md's verified list; no novel packages introduced.

## Self-Check: PASSED

Files exist:
- pyproject.toml: FOUND
- requirements.txt: FOUND
- .env.example: FOUND
- .gitignore: FOUND
- app/__init__.py: FOUND
- app/models/__init__.py: FOUND
- app/models/status.py: FOUND
- app/models/contracts.py: FOUND
- app/models/roster.py: FOUND
- tests/__init__.py: FOUND
- tests/test_models_contracts.py: FOUND

Commits exist:
- e3e3b3a: chore(01-01): project scaffold
- e3e3242: feat(01-01): Pydantic v2 contracts + persistent contract test
