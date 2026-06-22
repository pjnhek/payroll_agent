---
phase: 03-harden-the-calc
plan: "01"
subsystem: payroll-calc
tags: [federal-withholding, tax-tables, fica, pub15t, tdd, pure-function]
dependency-graph:
  requires: []
  provides:
    - app/pipeline/tax_tables_2026.py
    - app/pipeline/federal_withholding.py
  affects:
    - app/pipeline/calculate.py (FICA constants to be imported in Plan 03-03)
tech-stack:
  added: []
  patterns:
    - BracketRow NamedTuple for structured bracket data
    - _find_bracket() reversed linear scan (O(n), 8 rows max)
    - _money() local copy in federal_withholding.py (NOT imported from calculate.py)
    - _SUPPORTED_FILING_STATUSES frozenset guard (defense-in-depth reject)
key-files:
  created:
    - app/pipeline/tax_tables_2026.py
    - app/pipeline/federal_withholding.py
    - tests/test_tax_tables_2026.py
    - tests/test_federal_withholding.py
  modified: []
decisions:
  - "BracketRow NamedTuple with (lower, upper, base, rate) — rate stored as fraction not percentage"
  - "married_separately aliases single list via same object reference (not a copy)"
  - "Step-2-checkbox rows transcribed verbatim from RESEARCH.md Deliverable 1 (not halved from standard)"
  - "STEP1_STANDARD proxy amounts are $12,900 MFJ / $8,600 Single — NOT the 2026 std deduction"
  - "_money() is a local copy in federal_withholding.py — keeps eval importability clean"
  - "Option A rounding: _money() at each intermediate step, never whole-dollar mid-calc"
  - "HoH tables included in tax_tables_2026.py for completeness; engine rejects HoH via ValueError"
metrics:
  duration: "~8 minutes"
  completed: "2026-06-22"
  tasks_completed: 2
  tasks_total: 2
  files_created: 4
  files_modified: 0
  tests_added: 44
  tests_passing: 44
---

# Phase 03 Plan 01: Tax Tables and Federal Withholding Engine Summary

One-liner: Isolated Pub 15-T 2026 Worksheet 1A engine backed by a dated year-keyed constants module, implemented TDD with 44 golden/structural tests.

## What Was Built

### Task 1: app/pipeline/tax_tables_2026.py (CALC-06, D-02)

A pure constants module holding all 2026 federal tax constants. No functions, no DB, no network.

Key contents:
- `TAX_YEAR = 2026`
- `BracketRow` NamedTuple with fields `(lower, upper, base, rate)` where rate is a Decimal fraction
- `STANDARD_BRACKETS`: dict with 8-row tables for MFJ, Single, HoH under the standard (Step-2-unchecked) schedule
- `STEP2_BRACKETS`: dict with 8-row tables for MFJ, Single, HoH under the Step-2-checkbox schedule
- `married_separately` aliases the `single` list object in BOTH dicts (same Python list, not a copy — Pitfall #4 prevention)
- `STEP1_STANDARD`: `{"married_jointly": Decimal("12900"), "single": Decimal("8600"), ...}` — the Worksheet 1A line-1g withholding-proxy amounts with an inline comment distinguishing them from the 2026 standard deductions ($32,200/$16,100)
- FICA constants migrated from calculate.py: `SS_RATE = Decimal("0.062")`, `SS_WAGE_BASE = Decimal("184500")`, `MEDICARE_RATE = Decimal("0.0145")`
- Module header with source URLs (`irs.gov/pub/irs-pdf/p15t.pdf`, `ssa.gov/oact/cola/cbb.html`) and `Retrieved: 2026-06-22`

All 6 bracket tables (3 filing statuses × 2 Step-2 branches) are transcribed verbatim from RESEARCH.md Deliverable 1 (which was extracted live from the 2026 Pub 15-T PDF). Step-2-checkbox rows are NOT arithmetically derived by halving the standard schedule.

### Task 2: app/pipeline/federal_withholding.py (CALC-05, D-01 Decision 2)

An isolated pure-function Worksheet 1A engine.

Key design choices:
- Imports only `Employee` + `tax_tables_2026` — no calculate.py, no DB, no uuid/datetime
- `_money()` copied verbatim from calculate.py (local copy; keeps the module independently importable by the eval)
- `_find_bracket()`: reversed linear scan, fallback to `brackets[0]`
- `_SUPPORTED_FILING_STATUSES = frozenset({"single", "married_jointly", "married_separately"})` — defense-in-depth guard at the top of the function (review Fix 5 / STRIDE T-03-03)
- Exact 1a→4b Worksheet 1A flow with `_money()` at each money step (Option A rounding)
- `line_1i = max(0, ...)` — floors at $0 (IRS "if zero or less, enter -0-")
- `line_3c = max(0, ...)` — floors at $0 (same PDF instruction)
- `step_4c_extra_per_period` not modeled (no Employee field; all seeded employees have no extra withholding)

Smoke-test confirmed: Single/Standard/Weekly/$800 → `$54.08` (RESEARCH.md hand-computed worked example).

## Test Coverage (44 tests added)

### tests/test_tax_tables_2026.py (23 tests)
- Module import, TAX_YEAR, FICA constants
- STEP1_STANDARD values (correct proxy amounts, NOT the standard deduction)
- married_separately is/aliases single (both STANDARD and STEP2)
- 8 rows per schedule, rates as fractions (< 1), top bracket upper=None
- Source-URL and retrieval-date header check
- Spot-checks on key bracket thresholds from Deliverable 1 (MFJ standard bracket 2, Single standard bracket 2, MFJ Step-2 bracket 2, Single Step-2 bracket 2)

### tests/test_federal_withholding.py (21 tests)
14 golden-value parametrized cases (all hand-computed; none derived from the module under test):
- Single/Standard/Weekly at $800 → $54.08 (RESEARCH.md worked example)
- MFJ/Standard/Weekly at $1,200 → $60.15
- Single/Standard/Weekly at $1,000 with $2,000 Step-3 credit → $39.62
- Single/Step2/Weekly at $700 → $69.10
- MFJ/Step2/Weekly at $900 → $66.08 (covers the MFJ+Step2 schedule gap)
- MFS/Standard/Weekly at $800 → $54.08 (same as Single — uses same table)
- Single/Standard/Biweekly at $2,000 → $156.15 (26 periods)
- Below-threshold/Single/Standard at $100/week → $0.00 (line_1i floors at $0)
- Single/Standard with step_4a=$5,000 → $65.62
- Single/Standard with step_4b=$3,000 → $47.15
- Single/Standard/Monthly at $4,000 (12 periods) → $298.33
- Single/Standard/Semi-monthly at $2,000 (24 periods) → $149.17
- Zero wages → $0.00
- Step-3 floor (large $5,000 credit on $150 wages) → $0.00

7 behavioral/invariant tests:
- Withholding never negative (two scenarios: step_3 floor, low wages below threshold)
- HoH raises ValueError with "head_of_household" in message (review Fix 5)
- Unknown status raises ValueError
- Step-2 uses different table than standard (produces different result)
- MFS == Single table (identical results for same wages)
- Module importable with no DB access

## TDD Gate Compliance

### Task 1 — tax_tables_2026.py
- RED gate: commit `9a4c3a5` — 23 failing tests (ModuleNotFoundError)
- GREEN gate: commit `ef7fc01` — all 23 tests pass

### Task 2 — federal_withholding.py
- RED gate: commit `c086add` — 21 failing tests (ModuleNotFoundError at collection)
- GREEN gate: commit `2daee3c` — all 21 tests pass

Both gates committed separately as required.

## Deviations from Plan

None — plan executed exactly as written.

The 30 pre-existing test failures in `test_clarify`, `test_llm_client`, `test_orchestrator_states`, `test_threading`, and `test_webhook` are unrelated to this plan and were present at the baseline commit (`f19d46e`). Zero new test failures introduced.

## Known Stubs

None. Both modules are pure-function constants and computation — no stub patterns, no hardcoded empty values, no placeholder text.

## Threat Flags

No new security-relevant surface introduced. Both modules are pure offline arithmetic:
- No network endpoints
- No auth paths
- No file access patterns
- No schema changes

STRIDE T-03-03 (spoofing via wrong filing-status table) is mitigated by the `_SUPPORTED_FILING_STATUSES` guard in `federal_withholding_2026`, as planned.

## Self-Check: PASSED

Files created:
- [FOUND] app/pipeline/tax_tables_2026.py
- [FOUND] app/pipeline/federal_withholding.py
- [FOUND] tests/test_tax_tables_2026.py
- [FOUND] tests/test_federal_withholding.py

Commits (all present in git log):
- [FOUND] 9a4c3a5 — test(03-01): RED phase for tax_tables_2026
- [FOUND] ef7fc01 — feat(03-01): tax_tables_2026.py GREEN
- [FOUND] c086add — test(03-01): RED phase for federal_withholding
- [FOUND] 2daee3c — feat(03-01): federal_withholding.py GREEN

Test results: 44/44 pass (uv run pytest tests/test_tax_tables_2026.py tests/test_federal_withholding.py)
