---
phase: "07-money-correctness-deepening"
plan: "02"
subsystem: "pipeline, eval"
tags: ["money-correctness", "tdd", "green-tests", "money-01", "money-02", "unicode", "zero-hours"]
dependency_graph:
  requires:
    - "07-01 (RED tests planted for MONEY-01 and MONEY-02)"
  provides:
    - "_is_paid predicate at module scope in validate.py (D-09 shared predicate)"
    - "any_hours uses _is_paid -- zero-hours hourly employees gate correctly (MONEY-01 SC1)"
    - "NFC-hardened _norm: NFC(casefold(NFC(s))) in reconcile_names.py (MONEY-02 SC2)"
    - "eval/run_eval.py:_normalize is import alias of _norm (C-4 parity)"
  affects:
    - "app/pipeline/validate.py (_is_paid added, any_hours fixed)"
    - "app/pipeline/reconcile_names.py (_norm hardened to double-NFC)"
    - "eval/run_eval.py (local _normalize removed, import alias added)"
tech_stack:
  added:
    - "unicodedata (Python 3.12 stdlib) -- NFC normalization in reconcile_names._norm"
  patterns:
    - "TDD GREEN: flip RED tests from 07-01 to GREEN via minimal targeted fixes"
    - "Module-scope shared predicate (_is_paid) for reuse by Phase 7.5 detect_field_regression"
    - "Double-NFC normalization: NFC(casefold(NFC(s))) per D-05 (casefold can de-normalize)"
    - "Import alias (_norm as _normalize) as single source of truth for eval scorer"
key_files:
  created: []
  modified:
    - app/pipeline/validate.py
    - app/pipeline/reconcile_names.py
    - eval/run_eval.py
decisions:
  - "D-09 _is_paid predicate added at module scope (not inline lambda) for Phase 7.5 reuse at detect_field_regression call site"
  - "Double-NFC form NFC(casefold(NFC(s))) chosen per D-05 -- single NFC-then-casefold is insufficient because casefold can de-normalize its output on some Unicode sequences"
  - "NFC chosen over NFKC (D-06 locked: NFKC over-folds compatibility characters for real names)"
  - "Local _normalize def removed from run_eval.py entirely -- import alias is the canonical single source, not a copy (C-4)"
  - "OT guard (ot_missing = ot is None or ot == 0) left unchanged -- it is a separate guard, not a call site for _is_paid (D-05 independent)"
metrics:
  duration_mins: 6
  completed_date: "2026-06-28"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 3
---

# Phase 07 Plan 02: MONEY-01 + MONEY-02 GREEN Implementation Summary

**One-liner:** _is_paid shared predicate fixes the zero-hours gate (MONEY-01) and NFC(casefold(NFC(s))) hardening closes the Unicode name-match gap (MONEY-02), flipping all four RED tests from 07-01 to GREEN.

## What Was Built

### Task 1: _is_paid predicate + any_hours MONEY-01 fix (validate.py)

- **`app/pipeline/validate.py`:**
  - Added `from decimal import Decimal` to imports (required for typed predicate signature).
  - Added `_is_paid(v: Decimal | None) -> bool` at module scope after `_HOURS_FIELDS` (D-09). Returns `v is not None and v > 0` -- treats `Decimal('0')` identically to `None`. Docstring documents Phase 7.5 `detect_field_regression` as the second call site.
  - Replaced `getattr(emp, f) is not None for f in _HOURS_FIELDS` in `any_hours` with `_is_paid(getattr(emp, f)) for f in _HOURS_FIELDS` (D-02 fix).
  - No other logic touched: OT guard (`ot_missing = ot is None or ot == 0`) is independent and was not modified.

**MONEY-01 tests flipped:**

| Test | Before | After |
|------|--------|-------|
| `test_zero_hours_hourly_gates` | RED (Decimal('0') passed is-not-None gate, $0 paystub shipped) | GREEN |
| `test_predicate_consistency` | RED (hours_overtime=0 treated differently than None) | GREEN |
| `test_partial_week_not_gated` | GREEN (regression guard -- stayed green) | GREEN |
| `test_salaried_not_gated_regression_guard` | GREEN (regression guard -- stayed green) | GREEN |

### Task 2: NFC _norm fix (reconcile_names.py) + eval _normalize parity (run_eval.py)

- **`app/pipeline/reconcile_names.py`:**
  - Added `import unicodedata` to stdlib imports.
  - Replaced `_norm` body with NFC-hardened form. Step 1: `nfc = unicodedata.normalize("NFC", name)`. Step 2: `casefolded = nfc.casefold()`. Step 3: `renfc = unicodedata.normalize("NFC", casefolded)`. Step 4: `return " ".join(renfc.split())`. Docstring updated to document the double-NFC rationale (D-05) and NFC vs NFKC choice (D-06).

- **`eval/run_eval.py`:**
  - Added `_norm as _normalize` to the existing `reconcile_names` import line.
  - Removed the local `_normalize` function definition (was `" ".join(name.casefold().split())` -- casefold-only without NFC).
  - All six `_normalize` call sites in the file are satisfied by the import alias; no call site changes needed.

**MONEY-02 + C-4 tests flipped:**

| Test | Before | After |
|------|--------|-------|
| `test_nfd_name_resolves_same_as_nfc` | RED (NFD casefold diverged from NFC casefold without pre-NFC) | GREEN |
| `test_eval_normalize_nfd_matches_nfc` | RED (local _normalize was casefold-only) | GREEN |

## Verification Results

All plan verifications passed:

1. `uv run pytest tests/test_validate.py -k "zero_hours" -x -q` -- 1 passed (MONEY-01 SC1)
2. `uv run pytest tests/test_validate.py -k "partial_week" -x -q` -- 1 passed (D-03 edge stays correct)
3. `uv run pytest tests/test_validate.py -k "predicate_consistency" -x -q` -- 1 passed (D-25)
4. `uv run pytest tests/test_reconcile.py -k "nfd" -x -q` -- 1 passed (MONEY-02 SC2)
5. `uv run pytest tests/test_eval_wiring.py -k "nfd" -x -q` -- 1 passed (C-4 parity)
6. `uv run pytest tests/test_validate.py tests/test_reconcile.py tests/test_eval_wiring.py -q` -- 29 passed (no regressions)
7. `grep "def _is_paid" app/pipeline/validate.py` -- exits 0
8. `grep -c "unicodedata.normalize" app/pipeline/reconcile_names.py` -- 2 occurrences
9. `grep "_norm as _normalize" eval/run_eval.py` -- exits 0
10. `grep "def _normalize" eval/run_eval.py` -- exits 1 (local def absent)

## Deviations from Plan

None. Plan executed exactly as written.

- Three file edits only (validate.py, reconcile_names.py, run_eval.py) -- scope fence maintained.
- No MONEY-03 work: no `detect_field_regression`, no `prior=None` kwarg, no `schema.sql` changes, no `test_decide.py`/`test_resume_pipeline.py`, no xfail stubs.
- OT guard left untouched as specified: `ot_missing = ot is None or ot == 0` is a separate guard (D-05), not a `_is_paid` call site.
- `from decimal import Decimal` was absent in validate.py -- added as a Rule 3 (blocking) fix required for the typed predicate signature.

## Known Stubs

None. All three file changes are production logic fixes with no UI rendering, no placeholder data, no deferred wiring.

## Threat Flags

None. Changes are confined to:
- Pure predicate logic over already-typed `Decimal | None` values (T-07-03: accept, same pattern as existing ValidationIssue fields)
- `unicodedata.normalize` on LLM extraction output strings (T-07-04: accept, stdlib; no code injection risk)
- Import alias wiring (T-07-05: accept, intentional invariant -- eval scorer agrees with production normalizer by construction)

## Self-Check: PASSED

- FOUND: app/pipeline/validate.py
- FOUND: app/pipeline/reconcile_names.py
- FOUND: eval/run_eval.py
- FOUND: 07-02-SUMMARY.md
- FOUND commit 34f950b (Task 1: _is_paid + any_hours fix)
- FOUND commit d632cf0 (Task 2: _norm NFC hardening + _normalize import alias)
