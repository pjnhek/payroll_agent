---
phase: "07-money-correctness-deepening"
plan: "01"
subsystem: "models, tests"
tags: ["money-correctness", "tdd", "red-tests", "forward-compat", "money-01", "money-02"]
dependency_graph:
  requires: []
  provides:
    - "ValidationIssue.issue_type Literal includes field_regression (forward-compat D-17)"
    - "FieldDrop Pydantic model in contracts.py (forward-compat D-13/D-14)"
    - "MONEY-01 RED test baseline in test_validate.py (D-01/D-02/D-25)"
    - "MONEY-02 RED test baseline in test_reconcile.py (D-04/D-07)"
    - "eval _normalize parity RED test in test_eval_wiring.py (C-4)"
  affects:
    - "app/models/roster.py (ValidationIssue Literal widened)"
    - "app/models/contracts.py (FieldDrop added)"
    - "tests/test_validate.py (MONEY-01 RED tests appended)"
    - "tests/test_reconcile.py (MONEY-02 RED test appended)"
    - "tests/test_eval_wiring.py (C-4 RED test appended)"
tech_stack:
  added: []
  patterns:
    - "TDD RED baseline before implementation"
    - "Forward-compat Literal widening (no-op scaffolding)"
    - "Pydantic model_copy for minimal test roster construction"
    - "unicodedata.normalize for NFD/NFC Unicode test cases"
key_files:
  created: []
  modified:
    - app/models/roster.py
    - app/models/contracts.py
    - tests/test_validate.py
    - tests/test_reconcile.py
    - tests/test_eval_wiring.py
decisions:
  - "ValidationIssue.issue_type Literal widened to include field_regression for Phase 7.5 forward-compat (D-17); nothing in Phase 7 emits it"
  - "FieldDrop added to contracts.py (not roster.py) following existing pipeline I/O contract pattern; UUID and Decimal already imported"
  - "RawFieldDrop NOT added — it is a Phase 7.5 internal implementation detail that belongs alongside detect_field_regression"
  - "test_partial_week_not_gated and test_salaried_not_gated_regression_guard written as PASS guards (D-03 regression guards)"
  - "NFD test uses model_copy on Maria Chen with NFC name override — avoids seeding new employees"
  - "Scope fence: zero MONEY-03 tests — no detect_field_regression, no test_resume_pipeline.py, no xfail stubs"
metrics:
  duration_mins: 8
  completed_date: "2026-06-28"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 5
---

# Phase 07 Plan 01: Contract Foundation + RED Tests Summary

**One-liner:** Forward-compat scaffolding (ValidationIssue Literal + FieldDrop model) and TDD RED test baseline for MONEY-01 zero-hours gate and MONEY-02 Unicode NFC normalization.

## What Was Built

### Task 1: Widen ValidationIssue Literal + Add FieldDrop Model

- **`app/models/roster.py`:** `ValidationIssue.issue_type` Literal widened from `["missing", "out_of_bounds", "non_numeric"]` to include `"field_regression"`. Docstring updated to document it as Phase 7.5 forward-compat scaffolding (D-17). Nothing in Phase 7 emits this value.

- **`app/models/contracts.py`:** `FieldDrop` Pydantic model added between `Extracted` and `Decision` with `extra="forbid"`, fields `employee_id: UUID`, `field: str`, `original_value: Decimal`, `resumed_value: Decimal | None`. D-13/D-14 semantics documented in docstring (`None` = carried_forward, `Decimal('0')` = confirmed_dropped). `RawFieldDrop` deliberately NOT added (Phase 7.5 internal detail).

### Task 2: RED Tests for MONEY-01 and MONEY-02

**`tests/test_validate.py`** — four MONEY-01 tests appended:

| Test | Expected State | Why |
|------|---------------|-----|
| `test_zero_hours_hourly_gates` | FAILS RED | D-01: `is not None` lets `Decimal('0')` pass the gate |
| `test_predicate_consistency` | FAILS RED | D-25: `hours_overtime=0` treated differently than `hours_overtime=None` |
| `test_partial_week_not_gated` | PASSES | D-03 guard: `hours_holiday=8` is paid, so no missing issue |
| `test_salaried_not_gated_regression_guard` | PASSES | D-03: salaried employees never reach the hours gate |

**`tests/test_reconcile.py`** — one MONEY-02 test appended:

| Test | Expected State | Why |
|------|---------------|-----|
| `test_nfd_name_resolves_same_as_nfc` | FAILS RED | D-04: `_norm` does `casefold()` without NFC; NFD and NFC diverge |

**`tests/test_eval_wiring.py`** — one C-4 eval parity test appended:

| Test | Expected State | Why |
|------|---------------|-----|
| `test_eval_normalize_nfd_matches_nfc` | FAILS RED | C-4: `run_eval.py:_normalize` is casefold-only, separate from `_norm` |

## Verification Results

All plan verifications passed:

1. `ValidationIssue(issue_type='field_regression', ...)` — constructs OK (Literal widened)
2. `FieldDrop(employee_id=..., resumed_value=None)` — constructs OK; extra field raises ValidationError
3. `test_zero_hours_hourly_gates` — FAILS RED (expected, D-01 bug confirmed present)
4. `test_partial_week_not_gated` + `test_salaried_not_gated_regression_guard` — PASS (D-03 guards)
5. `test_nfd_name_resolves_same_as_nfc` — FAILS RED (expected, D-04 bug confirmed present)
6. `test_eval_normalize_nfd_matches_nfc` — FAILS RED (expected, C-4 gap confirmed present)
7. `test_models_contracts.py` — 38 passed (no regressions from Literal widening)
8. Full collection — 482 tests collected, 0 collection errors

## Deviations from Plan

None. Plan executed exactly as written.

- Scope fence maintained: zero MONEY-03 work. No `detect_field_regression`, no `test_resume_pipeline.py`, no `RawFieldDrop`, no xfail stubs.
- Task sequence matched plan: Task 1 (models) before Task 2 (tests), as tests depend on the widened Literal for import.
- The `model_copy` approach for the NFD roster test (using Maria Chen as base with NFC name override) was the simplest way to build a minimal test roster with combining-character names without seeding new employees.

## Known Stubs

None. This plan is pure scaffolding and RED tests — no UI rendering, no data flows, no stub values. The FieldDrop model is intentionally a harmless no-op; Plan 07-02 implements the code that uses it.

## Threat Flags

None. Changes are confined to:
- A Literal value addition in a constrained enum (backward-compatible, no new network/auth surface)
- A new Pydantic model with `extra="forbid"` (T-07-01 mitigation applied as planned)
- Pure test files (no production I/O)

## Self-Check

Checking key artifacts exist and commits are present.
