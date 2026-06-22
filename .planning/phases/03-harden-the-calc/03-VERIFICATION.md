---
phase: 03-harden-the-calc
verified: 2026-06-22T08:12:54Z
status: human_needed
score: 8/8 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Resolve the Thomas Bergmann over-ceiling federal withholding fixture"
    expected: >
      Both usapaycheck.org (biweekly) and paycheckcity.com agree within +-$1 on Thomas
      Bergmann's federal withholding (~$9,230.77 biweekly, MFJ standard, 401k=8%,
      step_3=$8,000, federal_taxable ~$8,492.31). If they agree: write the fixture with
      the agreed golden value and remove the @pytest.mark.skip. If they disagree by >$1:
      leave the skip in place, the coverage gap stands as documented.
    why_human: >
      The over-ceiling fixture requires two independent layer-B online calculators to
      agree within +-$1. This is a blocking human checkpoint per the plan (autonomous:
      false for 03-02). The operator pre-authorized the skip for the initial run (operator
      asleep), so the fixture carries @pytest.mark.skip(reason="OVER-CEILING ORACLE
      UNRESOLVED"). Under-ceiling fixtures are fully verified by the in-PDF wage-bracket
      PRIMARY oracle and need no human verification.
  - test: "Verify MFJ Standard wage-bracket independent cross-check"
    expected: >
      Transcribe the MFJ Standard wage-bracket cells verbatim from Pub 15-T 2026 p.14
      (the MFJ Standard column), add them to _WAGE_BRACKET_FIXTURES, and confirm that
      test_mfj_standard_wage_bracket_oracle_unresolved (currently strict xfail) is
      replaced with a real cross-check that passes. The MFJ Standard percentage path
      IS covered for correctness by the D-04 golden matrix (James Okafor, weekly MFJ
      Standard, penny-exact), so this is an independence gap, not a correctness gap.
    why_human: >
      The removed Column-2 MFJ Standard wage-bracket cells were engine-computed (circular
      oracle). Until the published cells are transcribed verbatim from Pub 15-T p.14, there
      is no independent wage-bracket oracle for MFJ Standard. This is recorded as a strict
      xfail (test_mfj_standard_wage_bracket_oracle_unresolved) so the gap is visible.
      Transcription requires reading the physical PDF table -- not automatable at CI time.
---

# Phase 03: Harden the Calc — Verification Report

**Phase Goal:** The payroll math becomes trustworthy to the penny — real IRS Pub 15-T 2026 federal withholding plus full-fidelity gross/FICA/401k/net, asserted by golden-value tests against hand-computed 2026 paystubs — landing BEFORE the eval or dashboard ever present a number as correct.

**Verified:** 2026-06-22T08:12:54Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

All 8 CALC requirements are verified by codebase inspection and live test execution.

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Real Pub 15-T 2026 federal withholding (CALC-05) — not Decimal("0") for a typical earning employee | VERIFIED | `federal_withholding_2026()` in `app/pipeline/federal_withholding.py`, called from `calculate.py` line 256. `test_net_pay_is_real_net` asserts `federal_withholding > Decimal("0")`. Run confirmed: 307 passed. |
| 2 | All 6 Worksheet 1A bracket schedules present (3 statuses × 2 Step-2 branches) | VERIFIED | `tax_tables_2026.py`: `_MFJ_STANDARD`, `_SINGLE_STANDARD`, `_HOH_STANDARD`, `_MFJ_STEP2`, `_SINGLE_STEP2`, `_HOH_STEP2` — all 8 rows each. `STANDARD_BRACKETS` and `STEP2_BRACKETS` dicts expose all 6 keys including `married_separately` aliased to `single`. |
| 3 | `married_separately` maps to Single/MFS table, never MFJ | VERIFIED | `STANDARD_BRACKETS["married_separately"] is STANDARD_BRACKETS["single"]` — same list object (identity check). Confirmed programmatically. `test_mfs_uses_same_table_as_single` passes. |
| 4 | FICA constants live in `tax_tables_2026.py`, not inline in `calculate.py` | VERIFIED | `calculate.py` imports `SS_RATE as _SS_RATE`, `SS_WAGE_BASE as _SS_WAGE_BASE`, `MEDICARE_RATE as _MEDICARE_RATE` from `tax_tables_2026`. `grep -n "_SS_RATE = Decimal"` returns 0 lines in `calculate.py`. |
| 5 | `net_pay == gross - pretax_401k - fica_ss - fica_medicare - federal_withholding` (CALC-07) | VERIFIED | `calculate.py` line 257: `net_pay = _money(gross - pretax_401k - fica_ss - fica_medicare - federal_withholding)`. `test_net_pay_is_real_net` and `test_reconciliation_identity` both pass. |
| 6 | 401k reduces federal base, not FICA base (CALC-03) | VERIFIED | `calculate.py`: `federal_taxable = _money(gross - pretax_401k)` feeds `federal_withholding_2026()`; FICA block uses raw `gross`. `test_fica_uses_gross_not_reduced_base`, `test_401k_reduces_federal_not_fica`, and `test_step4b_does_not_reduce_fica_base` all pass. |
| 7 | Arithmetic reconciliation backstop raises `PayrollCalculationError` on drift (CALC-08) | VERIFIED | `_raise_if_reconciliation_drift()` is a named module-level helper in `calculate.py` (line 149). Uses explicit `raise PayrollCalculationError(...)` — not a bare assert. `test_reconciliation_raises_on_drift` exercises both pass path (no raise) and drift path (`pytest.raises(PayrollCalculationError)`). |
| 8 | Tax constants in a dated, year-keyed module with source URLs; golden-value tests assert hand-computed 2026 paystubs to the penny (CALC-06) | VERIFIED | `tax_tables_2026.py` module docstring contains `irs.gov/pub/irs-pdf/p15t.pdf` and `Retrieved: 2026-06-22`. `test_federal_withholding_golden` parametrize sweeps 14 hand-computed penny-exact cases. `test_wage_bracket_cross_check` parametrize sweeps 24 independently-transcribed wage-bracket cells with exact equality. All pass. |

**Score:** 8/8 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/pipeline/tax_tables_2026.py` | All 2026 year-keyed federal + FICA constants | VERIFIED | 190 lines. `TAX_YEAR=2026`, all 6 bracket schedule dicts, `STEP1_STANDARD` with $12,900/$8,600 proxy amounts (explicitly NOT the $32,200/$16,100 standard deductions), `SS_RATE`, `SS_WAGE_BASE`, `MEDICARE_RATE`. Dated source-URL header. `married_separately` aliases `single` (identity, not copy). |
| `app/pipeline/federal_withholding.py` | Isolated Worksheet 1A pure function | VERIFIED | 161 lines. `federal_withholding_2026()` exports confirmed. Pure function: no DB, no network. HoH reject-guard at top. `_find_bracket()` exported (used by tests). All floors at $0.00 implemented. |
| `app/pipeline/calculate.py` | Full-fidelity payroll calc with real federal withholding | VERIFIED | 306 lines. Phase 3 docstring. `PRE_FEDERAL_NET_LABEL` gone (grep returns 0). FICA constants imported from `tax_tables_2026`. `federal_withholding_2026` called. `_raise_if_reconciliation_drift()` named helper. `additional_medicare_not_modeled` flag with filing-status-aware thresholds (WR-03). |
| `app/models/contracts.py` | `PaystubLineItem` with `additional_medicare_not_modeled: bool = False` | VERIFIED | Line 179: `additional_medicare_not_modeled: bool = False` with inline comment explaining User Decision 1 / FIX B. Additive field, default=False, non-breaking. |
| `tests/test_federal_withholding.py` | Golden suite for Pub 15-T 2026 Worksheet 1A engine | VERIFIED | 1238 lines. `test_wage_bracket_cross_check` (24 fixtures, 6 schedule columns, exact equality), `test_federal_withholding_golden` (14 hand-computed cases), `test_bracket_boundary_*` (3 direct `_find_bracket()` tests), `test_additional_medicare_limitation_is_flagged`, `test_hoh_reject_guard`, Thomas Bergmann SS straddle, 401k/step4b FICA-base assertions. 59 passed, 1 skipped (over-ceiling), 1 xfailed (MFJ Standard independence gap). |
| `tests/test_calculate.py` | Extended suite: CALC-01/02/07/08 cases | VERIFIED | 519 lines. All 4 original 401k-override tests preserved. Phase 3 additions include frequency-invariant test (p=52/26/24/12), `test_reconciliation_raises_on_drift` with `pytest.raises`, `test_salaried_with_leave_gross_integration`, `test_additional_medicare_flag_present` (realistic capped YTD), and input-guard tests (bool/float/unknown-key/negative). 21 passed. |
| `README.md` | "Known Limitations" with Additional Medicare disclaimer | VERIFIED | Lines 25-36: "Known Limitations" section present with exact disclaimer: "Additional Medicare surtax (0.9% over $200k YTD) is not modeled" and `additional_medicare_not_modeled = True` flag described. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `app/pipeline/calculate.py` | `app/pipeline/federal_withholding.py` | `from app.pipeline.federal_withholding import federal_withholding_2026` | VERIFIED | Line 31 import + line 256 call site. Called with `federal_taxable = _money(gross - pretax_401k)`. |
| `app/pipeline/calculate.py` | `app/pipeline/tax_tables_2026.py` | `from app.pipeline.tax_tables_2026 import SS_RATE as _SS_RATE, SS_WAGE_BASE as _SS_WAGE_BASE, MEDICARE_RATE as _MEDICARE_RATE` | VERIFIED | Lines 32-36. Aliased for backward-compat with FICA block. |
| `app/pipeline/federal_withholding.py` | `app/pipeline/tax_tables_2026.py` | `from app.pipeline.tax_tables_2026 import STANDARD_BRACKETS, STEP2_BRACKETS, STEP1_STANDARD, TAX_YEAR` | VERIFIED | Lines 20-25. All four names imported and used in the Worksheet 1A implementation. |
| `tests/test_federal_withholding.py` | `app/pipeline/federal_withholding.py` | `from app.pipeline.federal_withholding import _find_bracket, federal_withholding_2026` | VERIFIED | Line 83. Both names exercised: `federal_withholding_2026` in golden parametrize, `_find_bracket` in bracket boundary tests. |
| `tests/test_federal_withholding.py` | `app/pipeline/calculate.py` | `from app.pipeline.calculate import calculate` | VERIFIED | Line 82. Used for Additional Medicare flag tests, SS straddle, 401k interaction, and step4b tests. |
| `tests/test_calculate.py` | `app/pipeline/calculate.py` | `from app.pipeline.calculate import PayrollCalculationError, _raise_if_reconciliation_drift` | VERIFIED | Line 74. Both imported and exercised in `test_reconciliation_raises_on_drift`. |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `calculate.py` → `federal_withholding` | `federal_withholding` | `federal_withholding_2026(federal_taxable, employee)` | Yes — full Worksheet 1A engine | FLOWING |
| `calculate.py` → `net_pay` | `net_pay` | `_money(gross - pretax_401k - fica_ss - fica_medicare - federal_withholding)` | Yes — real components | FLOWING |
| `calculate.py` → `additional_medicare_not_modeled` | `additional_medicare_not_modeled` | `(employee.ytd_ss_wages + gross) > _ADDITIONAL_MEDICARE_THRESHOLDS[...]` | Yes — filing-status-aware proxy | FLOWING |
| `federal_withholding.py` → bracket lookup | `row` | `_find_bracket(line_1i, brackets)` where `brackets` is from `tax_tables_2026` | Yes — real bracket table scan | FLOWING |

All wired artifacts produce real data. No static returns or hollow props found.

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| $54.08 hand-computation (Single/Standard/Weekly/$800) | `uv run python -c "...federal_withholding_2026(Decimal('800.00'), maria)..."` | Decimal('54.08') | PASS |
| Zero wages → zero withholding | Same session | Decimal('0.00') | PASS |
| Step-3 floor → $0.00 not negative | Same session | Decimal('0.00') | PASS |
| HoH raises ValueError with "head_of_household" in message | Same session | ValueError raised, message confirmed | PASS |
| `PRE_FEDERAL_NET_LABEL` is gone | `grep -n "PRE_FEDERAL_NET_LABEL" app/pipeline/calculate.py` | 0 lines | PASS |
| No inline FICA literals in `calculate.py` | `grep -n "_SS_RATE = Decimal"` | 0 lines | PASS |
| N1 gate: no unnamed +-$1 tolerance, no impossible YTD values, no python-taxes | Python script | All 3 checks OK | PASS |

---

### Probe Execution

No `scripts/*/tests/probe-*.sh` probes defined or referenced in this phase. Step 7c: SKIPPED (no probe files; phase is a pure-computation library with no runnable service entry points separate from the test suite).

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CALC-01 | 03-03 | Gross pay: hourly × rate with FLSA OT at 1.5× for hours > 40 (paid-leave excluded from threshold) | SATISFIED | `calculate.py` lines 203-211. `test_hourly_overtime_at_1_5x` and `test_leave_hours_excluded_from_ot_threshold` both pass. |
| CALC-02 | 03-03 | Salary gross = annual ÷ pay periods + vacation/sick/holiday pay | SATISFIED | `calculate.py` lines 213-232 using `/2080` form (frequency-independent). `test_salaried_leave_pay_frequency_invariant` asserts p=52/26/24/12 all produce $200.00 delta. |
| CALC-03 | 03-03 | 401k reduces federal base, not FICA base | SATISFIED | `calculate.py`: `federal_taxable = _money(gross - pretax_401k)`, FICA block uses `gross`. `test_fica_uses_gross_not_reduced_base` and `test_401k_reduces_federal_not_fica` pass. |
| CALC-04 | 03-01/03-02/03-03 | FICA: SS at 6.2% up to $184,500 cap (honoring YTD), Medicare at 1.45%. Additional Medicare disclaimed. | SATISFIED | FICA straddle via `remaining_cap = _SS_WAGE_BASE - employee.ytd_ss_wages`. `test_ss_straddle_thomas_bergmann` asserts $37.20. README disclaimer present. |
| CALC-05 | 03-01/03-03 | Federal withholding via real IRS Pub 15-T 2026 percentage method (Worksheet 1A, all 3 filing statuses + Step-2 branch) | SATISFIED | `federal_withholding.py` implements full 1a→4b flow. `test_federal_withholding_golden` (14 cases), `test_wage_bracket_cross_check` (24 cases) all pass with exact equality. |
| CALC-06 | 03-01/03-02 | Tax constants in a dated, year-keyed module; golden-value tests assert hand-computed 2026 paystubs to the penny | SATISFIED | `tax_tables_2026.py` with dated source-URL header. Golden suite in `test_federal_withholding.py`. All 14 penny-exact cases + 24 wage-bracket cross-check rows pass. |
| CALC-07 | 03-03 | Net pay = gross − pre-tax − FICA − federal withholding | SATISFIED | `calculate.py` line 257. `test_net_pay_is_real_net` confirms `federal_withholding > 0` and `net_pay == expected`. |
| CALC-08 | 03-03 | Reconciliation backstop confirms net + taxes + deductions ties to gross; arithmetic backstop only | SATISFIED | `_raise_if_reconciliation_drift()` named helper (not bare assert). `test_reconciliation_raises_on_drift` exercises both pass and drift paths via `pytest.raises(PayrollCalculationError)`. |

All 8 CALC requirements are SATISFIED.

**Orphaned requirements check:** No CALC requirements mapped to Phase 3 in REQUIREMENTS.md are absent from the plans' `requirements:` fields. Coverage complete.

---

### Anti-Patterns Found

Anti-pattern scan on phase-modified files:

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `tests/test_federal_withholding.py` | 1087-1100 | `@pytest.mark.skip(reason="OVER-CEILING ORACLE UNRESOLVED...")` + `pass` body | INFO — intentional, documented | Over-ceiling federal withholding for Thomas Bergmann is unverified. Not a defect: operator pre-authorized the skip per the blocking human checkpoint in 03-02. CI passing without this fixture does NOT constitute over-ceiling coverage. |
| `tests/test_federal_withholding.py` | 404-424 | `@pytest.mark.xfail(strict=True)` on `test_mfj_standard_wage_bracket_oracle_unresolved` | INFO — intentional, documented | MFJ Standard wage-bracket cells not independently transcribed (were engine-computed and removed). MFJ Standard correctness is still covered by the D-04 golden matrix (James Okafor, penny-exact). Gap is an independence gap, not a correctness gap. |
| `app/pipeline/tax_tables_2026.py` | 73-86, 132-144 | HoH bracket tables with comment "UNTESTED — unreachable" | INFO — intentional, documented | HoH rows are present for completeness but are never reached (engine raises ValueError for HoH before any lookup). IN-01 comment explicitly notes this. No defect. |

**Debt markers:** `grep -n "TBD|FIXME|XXX"` across all phase-modified files returned 0 matches. No unresolved debt markers.

**Stub classification:** The `pass` body in `test_federal_withholding_thomas_bergmann_over_ceiling` is an intentional placeholder for a fixture blocked by an unresolved human checkpoint, not a functional stub. It does not render dynamic data and does not affect any calculation path.

---

### Human Verification Required

Two items require human action before this phase can be considered fully closed. Both are documented operator-pending gaps, not defects in the core calculation logic.

#### 1. Thomas Bergmann Over-Ceiling Federal Withholding Fixture

**Test:** Open usapaycheck.org (biweekly variant) and paycheckcity.com. Enter: gross $9,230.77, biweekly, MFJ standard (Step-2 NOT checked), Step-3 $8,000, 401k=8% (federal taxable ≈ $8,492.31). Record both tools' results.

**Expected:** Both calculators agree within +-$1 of each other, AND with the hand-traced expected value. Operator types "approved: [usapaycheck result], [paycheckcity result]" and the executor writes the golden fixture, replacing the skip.

**Why human:** Over-ceiling wages (above the $3,875 biweekly wage-bracket ceiling) cannot use the in-PDF Wage Bracket Method as the PRIMARY oracle — that table ends at $3,875. The plan's D-01 Decision 2 requires two independent external calculators for over-ceiling fixtures. If the calculators disagree by >$1, the skip stays and coverage remains UNRESOLVED. No programmatic substitute exists.

**Current state:** `@pytest.mark.skip(reason="OVER-CEILING ORACLE UNRESOLVED — high-earner withholding not independently verified")` on `test_federal_withholding_thomas_bergmann_over_ceiling`. The SS-straddle FICA assertion for Thomas Bergmann (`test_ss_straddle_thomas_bergmann`) is a SEPARATE under-ceiling test and IS verified (passes).

---

#### 2. MFJ Standard Wage-Bracket Independent Cross-Check

**Test:** Open IRS Pub 15-T 2026 PDF at `irs.gov/pub/irs-pdf/p15t.pdf`, go to pages 14-16 (weekly wage-bracket tables), find the MFJ Standard column. Transcribe 4-6 cell values verbatim (interval_lower, interval_upper, withholding_cell) for rows in the 10%-12% bracket range (wages ~$750-$1,100/week). Add them to `_WAGE_BRACKET_FIXTURES` in `test_federal_withholding.py` with `filing_status="married_jointly", step2=False`. Remove or replace `test_mfj_standard_wage_bracket_oracle_unresolved` with the real cross-check.

**Expected:** The new `test_wage_bracket_cross_check` rows for MFJ Standard all pass with exact equality. The strict xfail is no longer needed. All existing tests remain green.

**Why human:** The previously included MFJ Standard wage-bracket cells were engine-computed (circular oracle — violated D-01 Decision 2's self-derivation ban). They were removed rather than left as a fake oracle. Correct transcription requires a human reading the physical PDF table cells — these cannot be generated from code without re-introducing circularity. MFJ Standard correctness IS still guarded by the D-04 golden matrix (James Okafor, penny-exact), so this is an independence gap, not a correctness risk.

---

### Gaps Summary

No functional gaps exist. The two items above are intentional, documented operator-pending coverage gaps, not defects in the phase deliverable:

- The core goal is fully achieved: penny-trustworthy under-ceiling payroll calculation with real Pub 15-T 2026 federal withholding, asserted by 307 passing tests (8 CALC requirements satisfied).
- The Thomas Bergmann over-ceiling skip is not a defect — it is the correct behavior under the plan's human-checkpoint protocol when two calculators have not yet confirmed the value.
- The MFJ Standard independence gap is not a correctness gap — the percentage path is covered by the golden matrix; only the independent wage-bracket oracle is deferred.

Both items resolve to `status: human_needed` rather than `status: gaps_found` per the verification instructions: "if the only outstanding items are the two intentional operator-pending coverage gaps, prefer status: human_needed over gaps_found."

---

### Full Test Suite Run

```
uv run pytest -q
307 passed, 13 skipped, 1 xfailed, 0 failed, 1 warning in 0.64s
```

The 13 skips and 1 xfailed are all from other test files (Phase 2 integration tests requiring live DB/API keys, and the Thomas Bergmann over-ceiling fixture). Zero failures.

---

_Verified: 2026-06-22T08:12:54Z_
_Verifier: Claude (gsd-verifier)_
