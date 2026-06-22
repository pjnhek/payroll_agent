---
status: partial
phase: 03-harden-the-calc
source: [03-VERIFICATION.md]
started: 2026-06-22T08:15:30Z
updated: 2026-06-22T08:40:00Z
---

## Current Test

[Item 2 awaiting human testing]

## Tests

### 1. Thomas Bergmann over-ceiling federal-withholding fixture (layer-B oracle)
expected: An independent IRS-percentage-method calculator confirms the over-ceiling
federal withholding for Thomas Bergmann (biweekly, MFJ, Step-2 unchecked, gross $9,230.77,
pre-tax 401k 8% → federal taxable $8,492.31, step_3 $8,000).
result: RESOLVED 2026-06-22 — paycheckcity.com (calibrated to $54.08 on the under-ceiling
case) returned Federal Withholding = $881.39 with the 401k entered as TRADITIONAL pre-tax,
a PENNY-EXACT match with the engine. (An initial run without the 401k applied to the
federal base gave $1,043.85; re-running with pre-tax 401k reconciled it exactly to $881.39,
confirming the difference was 401k input handling, not an engine/table error.) usapaycheck.org
was discarded (rounds inputs/outputs, not penny-exact). Fixture
`test_federal_withholding_thomas_bergmann_over_ceiling` now asserts $881.39 via calculate();
skip removed. Provenance: one penny-exact online oracle + full Worksheet 1A hand trace.

### 2. MFJ Standard wage-bracket independent cross-check
expected: 4–6 "Married Filing Jointly, Standard (Step-2 unchecked)" weekly wage-bracket
cells transcribed VERBATIM from the published IRS Pub 15-T 2026 p.14 MFJ Standard column
(NOT computed from the engine). Add them to `_WAGE_BRACKET_FIXTURES` in
tests/test_federal_withholding.py and delete the strict-xfail placeholder
`test_mfj_standard_wage_bracket_oracle_unresolved`. This restores an independent oracle
for the MFJ Standard column (currently covered only by the D-04 golden matrix / James Okafor).
result: [pending]

## Summary

total: 2
passed: 1
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
