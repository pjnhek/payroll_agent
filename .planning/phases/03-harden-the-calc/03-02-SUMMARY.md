---
phase: 03-harden-the-calc
plan: "02"
subsystem: federal-withholding-test
tags: [tdd, tests, pub-15-t, golden-suite, fica, oracle]
dependency_graph:
  requires: [03-01, 03-03]
  provides: [D-04-golden-matrix, wage-bracket-cross-check, ss-straddle-assertion]
  affects: [tests/test_federal_withholding.py]
tech_stack:
  added: []
  patterns: [wage-bracket-PRIMARY-oracle, R2-1-exact-equality, R2-4-direct-bracket-test, R2-8-six-columns]
key_files:
  created: []
  modified:
    - tests/test_federal_withholding.py
    - README.md
decisions:
  - "Thomas Bergmann over-ceiling federal withholding deferred: @pytest.mark.skip(reason='OVER-CEILING ORACLE UNRESOLVED -- high-earner withholding not independently verified') per pre-authorized CHECKPOINT_RESOLUTION"
  - "Wage-bracket PRIMARY oracle cross-check uses exact equality (==) per R2-1 -- no blanket +-$1 tolerance"
  - "R2-4 boundary tests call _find_bracket() directly with adjusted-annual-wage inputs to bypass annualization rounding confound"
  - "R2-2 Additional Medicare flag tests use ytd_ss_wages=184500 (SS cap, max realistic value), NOT impossible 196000"
  - "python-taxes not installed per R2-7 -- 2026 tables not in scope; wage-bracket Deliverable 5 provides structural independence"
metrics:
  duration: "~45 minutes"
  completed: "2026-06-22T07:43:55Z"
  tasks_completed: 2
  files_modified: 2
---

# Phase 03 Plan 02: Pub 15-T 2026 Golden Test Suite Summary

**One-liner:** Full D-04 golden matrix with wage-bracket PRIMARY oracle cross-check (all 6 schedule columns), direct `_find_bracket()` boundary tests (R2-4), Additional Medicare flag (R2-2 realistic SS-cap YTD), Thomas Bergmann SS straddle (CALC-04), and over-ceiling skip per pre-authorized checkpoint.

## What Was Built

Extended `tests/test_federal_withholding.py` (159 lines → 805 lines) with the complete D-04 golden test matrix:

**Task 1 (pre-authorized skip via CHECKPOINT_RESOLUTION):**
- Thomas Bergmann over-ceiling federal withholding fixture marked `@pytest.mark.skip(reason="OVER-CEILING ORACLE UNRESOLVED — high-earner withholding not independently verified")` per operator pre-authorization.
- No golden value implemented — oracle deferred.

**Task 2 (full golden suite extension):**
- `WAGE_BRACKET_CEILINGS` constant (weekly=$1925, biweekly=$3875, semimonthly=$4185, monthly=$8395)
- `test_wage_bracket_cross_check` — 36 parametrized rows spanning all 6 schedule columns (MFJ Std, MFJ Step-2, Single/MFS Std, Single/MFS Step-2, biweekly Single/MFS Std, monthly Single/MFS Std), exact equality (==) per R2-1
- `test_bracket_boundary_at_B`, `test_bracket_boundary_below_B`, `test_bracket_boundary_above_B` — direct `_find_bracket()` tests at B=$19,900 (Single/Standard 10%→12% boundary) per R2-4
- `test_additional_medicare_limitation_is_flagged` — fires with ytd_ss_wages=184500 (R2-2 SS-cap max)
- `test_additional_medicare_flag_does_not_fire_for_normal_employee` — does NOT fire at ytd=0
- `test_ss_straddle_thomas_bergmann` — asserts fica_ss=$37.20 (remaining_cap=$600, CALC-04)
- `test_401k_reduces_federal_not_fica` — FICA uses gross, federal uses gross-401k (CALC-03)
- `test_step4b_does_not_reduce_fica_base` — step_4b reduces federal base only (Fix 7b)
- `test_federal_withholding_thomas_bergmann_over_ceiling` — `@pytest.mark.skip` (over-ceiling oracle unresolved)
- README.md "Known Limitations" section documenting Additional Medicare 0.9% not modeled

## OVER-CEILING COVERAGE: UNRESOLVED

> **OVER-CEILING COVERAGE: UNRESOLVED** — Thomas Bergmann fixture marked `@pytest.mark.skip(reason='OVER-CEILING ORACLE UNRESOLVED — high-earner withholding not independently verified')`. CI passing without this fixture does NOT constitute over-ceiling verification. This must be resolved before any claim of full D-04 matrix coverage.

2026-06-22: Over-ceiling layer-B calculator verification deferred (operator asleep, pre-authorized skip). Thomas Bergmann over-ceiling fixture marked skip — over-ceiling coverage UNRESOLVED.

## Test Results

```
uv run pytest tests/test_federal_withholding.py tests/test_calculate.py -q
79 passed, 1 skipped in 0.04s
```

The 1 skipped is the Thomas Bergmann over-ceiling federal withholding fixture (intentional, pre-authorized).

Full suite (pre-existing failures in test_llm_client, test_orchestrator_states, test_threading, test_webhook are out of scope for this plan — those files were not modified):
```
272 passed, 13 skipped, 30 failed (pre-existing, out of scope)
```

**N1 gate: PASSED** — no unnamed ±1 tolerances, no impossible ytd_ss_wages > 184500, no python-taxes in pyproject.toml.

## Commits

| Task | Commit | Files | Description |
|------|--------|-------|-------------|
| Task 2 (golden suite + README) | 8bc94f9 | tests/test_federal_withholding.py, README.md | feat(03-02): Pub 15-T 2026 golden test suite + README limitations |

## Deviations from Plan

None — plan executed exactly as written. Thomas Bergmann over-ceiling skip was pre-authorized via CHECKPOINT_RESOLUTION block in the executor prompt.

## Key Decisions

1. **Over-ceiling oracle deferred**: Thomas Bergmann biweekly MFJ (~$9,230/period, above $3,875 ceiling) requires layer-B calculator verification that was not available. Fixture marked skip per pre-authorization. The SS straddle FICA assertion (separate, under-ceiling) was implemented normally.
2. **Exact equality everywhere**: R2-1 enforced — no blanket ±1 tolerance. All 36 wage-bracket cross-check rows use `==`. The only skip is the oracle-unresolved over-ceiling fixture.
3. **R2-4 direct boundary tests**: `_find_bracket()` tested at B=$19,900 exactly (Single/Standard 10%→12% boundary), B-$0.01, and B+$0.01 via direct function call — no annualization confound.
4. **R2-2 realistic SS-cap YTD**: Additional Medicare flag test uses ytd_ss_wages=184500 (the 2026 SS wage base cap, maximum realistic value). No impossible value above cap used.
5. **python-taxes absent**: R2-7 enforced — library not installed. Wage-bracket Deliverable 5 provides the structural independence already.

## Known Stubs

None — all tests use live engine calls; no mock data stubs that would affect correctness claims.

## Threat Flags

None — this plan adds tests only; no new network endpoints, auth paths, or schema changes.

## Self-Check: PASSED

- [x] `tests/test_federal_withholding.py` — exists and is 805+ lines
- [x] `README.md` — "Known Limitations" section added
- [x] Commit `8bc94f9` — verified via `git log --oneline`
- [x] 79 tests pass (1 skipped intentionally)
- [x] N1 gate prints "N1 gate OK"
