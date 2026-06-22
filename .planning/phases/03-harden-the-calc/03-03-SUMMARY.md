---
phase: 03-harden-the-calc
plan: "03"
subsystem: payroll-calc
tags: [calc, federal-withholding, fica, net-pay, reconciliation, tdd]
dependency_graph:
  requires: [03-01]
  provides: [CALC-01, CALC-02, CALC-03, CALC-04, CALC-07, CALC-08]
  affects: [app/pipeline/calculate.py, app/models/contracts.py, tests/test_calculate.py]
tech_stack:
  added: []
  patterns:
    - "Named helper pattern for unit-testable reconciliation: _raise_if_reconciliation_drift() extracted as a module-level pure function"
    - "Frequency-independent salaried leave pay: annual / 2080 * leave_hours (not period_salary / standard_hours)"
    - "Phase 3 real federal withholding: federal_taxable = gross - pretax_401k; FICA base unchanged (gross)"
key_files:
  created: []
  modified:
    - app/pipeline/calculate.py
    - app/models/contracts.py
    - tests/test_calculate.py
    - tests/test_persistence.py
decisions:
  - "CALC-03: 401k reduces federal taxable base but NOT the FICA base — FICA always uses gross"
  - "R2-3: reconciliation backstop is a named helper (_raise_if_reconciliation_drift) raising PayrollCalculationError — never a bare assert (python -O strips asserts)"
  - "FIX A: salaried leave pay uses annual/2080 implied-hourly form — frequency-independent for p=52/26/24/12"
  - "User Decision 1 / FIX B: Additional Medicare 0.9% not modeled; proxy flag fires on (ytd_ss_wages + gross) > $200k with realistic ytd_ss_wages <= $184,500 (R2-2)"
  - "Rule 1 auto-fix: test_persistence.py updated to remove PRE_FEDERAL_NET_LABEL import and update Phase 2 assertions to Phase 3 behavior"
metrics:
  duration: "~20 minutes"
  completed: "2026-06-22T07:29:00Z"
  tasks: 2
  files: 4
---

# Phase 3 Plan 03: Calculate.py Phase 3 Deepening Summary

**One-liner:** Full-fidelity payroll calc with real Pub 15-T federal withholding, frequency-independent salaried leave pay, Additional Medicare proxy flag, and named reconciliation helper tested via pytest.raises.

## What Was Built

### Task 1: Deepen calculate.py + contracts.py

**`app/pipeline/calculate.py`** was transformed from the Phase 2 thin calc (federal=Decimal("0"), net pre-federal) into a full-fidelity Phase 3 calc:

1. **FICA constants migrated** from inline literals to imports from `tax_tables_2026.py` (D-02). Values identical; only the source changed.

2. **`federal_withholding_2026` imported** from `app/pipeline/federal_withholding.py` (the Wave 1 engine).

3. **`PRE_FEDERAL_NET_LABEL` removed** — net is now real; the Phase 2 pre-federal label is retired.

4. **`PayrollCalculationError` exception class added** — the canonical exception for arithmetic backstop failures (CALC-08, R2-3).

5. **`_raise_if_reconciliation_drift()` named helper added** — module-level pure function that raises `PayrollCalculationError` when `net + pretax_401k + fica_ss + fica_medicare + federal_withholding != gross`. Extracted as a named helper specifically so both the pass path and drift-raises path can be unit-tested via `pytest.raises` without monkeypatching (R2-3). Never uses a bare `assert` (which `python -O` would strip).

6. **Salaried leave pay added (CALC-02, FIX A):** uses the frequency-independent `/2080` implied-hourly form: `leave_pay = _money((annual / 2080) * leave_hours)`. This produces identical leave pay at p=52, p=26, p=24, p=12 for the same `annual_salary + leave_hours`. The prior period-proportion formula `(period_salary / standard_h_per_period * leave_h)` where `standard_h = 40 * p / 52` was frequency-dependent and wrong for non-weekly schedules (4.7x at p=24, 18.8x at p=12).

7. **Real federal withholding (CALC-05):** `federal_taxable = _money(gross - pretax_401k)`, then `federal_withholding = federal_withholding_2026(federal_taxable, employee)`. The 401k reduces the federal taxable base but NOT the FICA base (CALC-03).

8. **Real net pay (CALC-07):** `net_pay = _money(gross - pretax_401k - fica_ss - fica_medicare - federal_withholding)`.

9. **Additional Medicare proxy flag (User Decision 1, FIX B, R2-2):** `additional_medicare_not_modeled = (employee.ytd_ss_wages + gross) > Decimal("200000")`. Uses `ytd_ss_wages` as a documented lower bound for Medicare YTD wages (Medicare has no cap, so Medicare YTD >= SS YTD). Fires only when proxy crosses $200k. Realistic fixture: `ytd_ss_wages=184500` (the SS wage base cap — maximum real value) + `gross=$20,000` → `$204,500 > $200,000` — fires.

10. **`_raise_if_reconciliation_drift()` called** near the end of `calculate()` before the return (CALC-08).

**`app/models/contracts.py`** — `PaystubLineItem` gains one additive, non-breaking field:
```python
additional_medicare_not_modeled: bool = False
```
Default `False` ensures existing callers that don't pass this field are unbroken.

### Task 2: Extend tests/test_calculate.py

11 new test functions appended below the 4 existing tests (all 4 existing tests remain green):

| Test | Covers |
|------|--------|
| `test_hourly_overtime_at_1_5x` | CALC-01: OT at 1.5x rate |
| `test_leave_hours_excluded_from_ot_threshold` | D-03: leave hours are straight-time, never trigger OT |
| `test_salaried_leave_pay_added_to_gross` | CALC-02: James Okafor leave pay |
| `test_salaried_no_leave_gross_unchanged` | CALC-02 baseline |
| `test_salaried_leave_pay_frequency_invariant` | FIX A + R2-6: delta=Decimal("200.00") at p=52/26/24/12 |
| `test_salaried_with_leave_gross_integration` | Fix 9: leave → higher gross → higher or equal withholding |
| `test_net_pay_is_real_net` | CALC-07: federal_withholding > 0, real net formula |
| `test_reconciliation_identity` | CALC-08: reconstructed sum equals gross |
| `test_reconciliation_raises_on_drift` | R2-3: pytest.raises on BOTH pass and drift paths |
| `test_fica_uses_gross_not_reduced_base` | CALC-03: FICA base is gross, not gross-pretax_401k |
| `test_additional_medicare_flag_present` | R2-2: realistic capped SS YTD (ytd_ss_wages=184500 max) |

**Result:** 15/15 tests pass in `test_calculate.py` (4 original + 11 new).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_persistence.py import failure after PRE_FEDERAL_NET_LABEL removal**
- **Found during:** Task 2 (full suite run after extending test_calculate.py)
- **Issue:** `test_persistence.py` imported `PRE_FEDERAL_NET_LABEL` from `calculate.py` and had Phase 2 tests asserting `federal_withholding == Decimal("0")` and the pre-federal label. These became broken by Task 1's intentional removal of `PRE_FEDERAL_NET_LABEL`.
- **Fix:** Updated `test_persistence.py` to:
  - Remove `PRE_FEDERAL_NET_LABEL` from the import line
  - Replace `test_calc_federal_is_zero_and_no_fabricated_figure` → `test_calc_federal_is_real_in_phase3` (asserts `federal_withholding > 0`)
  - Replace `test_pre_federal_label_is_a_module_constant_not_a_contract_field` → `test_no_net_pay_label_field_on_paystub` (retains the critical invariant: no `net_pay_label` field on `PaystubLineItem`)
  - Updated `test_calc_gross_and_net_hourly` to compute `expected_net` from the item's actual withholding instead of the Phase 2 hardcoded `683.39`
- **Files modified:** `tests/test_persistence.py`
- **Commit:** dbce0db (included in Task 2 commit)

### Pre-existing Worktree Failures (Not My Changes)

30 tests in `test_clarify.py`, `test_llm_client.py`, `test_extract.py`, `test_orchestrator_states.py`, `test_threading.py`, and `test_webhook.py` fail with `Settings.database_url required` (credential issue) or `MockOpenAI` configuration issues. These are the same failures noted in the critical reminders: "this project's test_clarify/test_llm_client/test_threading tests pass in the main checkout but MAY appear to fail inside an isolated worktree if they need .env/credentials. The 03-01 executor saw this." These failures are pre-existing and not caused by Plan 03-03 changes.

**Verification scope:** `uv run pytest tests/test_calculate.py tests/test_federal_withholding.py tests/test_persistence.py -q` → 43 passed, 1 skipped.

## Known Stubs

None — all payroll fields are computed from real data. `additional_medicare_not_modeled` is a flag (not a stub) that transparently documents a known modeling limitation.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes were introduced. `calculate.py` and `contracts.py` are pure offline functions. The `additional_medicare_not_modeled` field is a boolean annotation on the `PaystubLineItem` — no trust boundary crossed. Threat register items T-03-03-01 through T-03-03-SC are all mitigated as planned.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| `app/pipeline/calculate.py` exists | FOUND |
| `app/models/contracts.py` exists | FOUND |
| `tests/test_calculate.py` exists | FOUND |
| `tests/test_persistence.py` exists | FOUND |
| `03-03-SUMMARY.md` exists | FOUND |
| Commit f99bce0 (Task 1) exists | FOUND |
| Commit dbce0db (Task 2) exists | FOUND |
| `uv run pytest tests/test_calculate.py -q` | 15 passed |
