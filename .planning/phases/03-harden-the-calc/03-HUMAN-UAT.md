---
status: passed
phase: 03-harden-the-calc
source: [03-VERIFICATION.md]
started: 2026-06-22T08:15:30Z
updated: 2026-06-22T08:55:00Z
---

## Current Test

[all items resolved]

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
cells transcribed VERBATIM from the published IRS Pub 15-T 2026 MFJ Standard column
(NOT computed from the engine), added to `_WAGE_BRACKET_FIXTURES`, xfail placeholder removed.
result: RESOLVED 2026-06-22 — operator transcribed 5 cells from the published weekly MFJ
Standard wage-bracket table: [795-805]→$18, [1005-1015]→$39, [1705-1715]→$121,
[1865-1875]→$141, [1915-1925]→$147. All 5 cross-check against the engine to the whole
dollar (ROUND_HALF_UP). Added to Column 2 of `_WAGE_BRACKET_FIXTURES`; strict-xfail
placeholder removed. MFJ Standard now has a genuine independent oracle.

## Summary

total: 2
passed: 2
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
