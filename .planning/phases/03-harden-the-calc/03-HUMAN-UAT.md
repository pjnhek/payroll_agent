---
status: partial
phase: 03-harden-the-calc
source: [03-VERIFICATION.md]
started: 2026-06-22T08:15:30Z
updated: 2026-06-22T08:15:30Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Thomas Bergmann over-ceiling federal-withholding fixture (layer-B oracle)
expected: Both usapaycheck.org (biweekly variant) AND paycheckcity.com, in IRS Pub 15-T
2026 percentage-method mode, return the same federal withholding (within ±$1) for Thomas
Bergmann: biweekly, married_jointly, Step-2 NOT checked, gross ≈ $9,230.77 ($240,000 / 26),
401k = 8% (federal taxable ≈ $8,492.31), step_3_dependents = $8,000. Calibrate each tool
first on the under-ceiling case ($800/week, Single, no Step-2 → $54.08). If both agree,
write the value into the fixture at `test_federal_withholding_thomas_bergmann_over_ceiling`
in tests/test_federal_withholding.py and remove the `@pytest.mark.skip`. If they disagree
by > $1, leave the skip (over-ceiling coverage stays UNRESOLVED).
result: [pending]

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
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
