---
phase: 03-harden-the-calc
reviewed: 2026-06-22T00:00:00Z
depth: deep
files_reviewed: 9
files_reviewed_list:
  - app/models/contracts.py
  - app/pipeline/calculate.py
  - app/pipeline/federal_withholding.py
  - app/pipeline/tax_tables_2026.py
  - tests/test_calculate.py
  - tests/test_federal_withholding.py
  - tests/test_persistence.py
  - tests/test_tax_tables_2026.py
  - README.md
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: issues_found
---

# Phase 3: Code Review Report (Round 3 — Convergence Check)

**Reviewed:** 2026-06-22
**Depth:** deep
**Files Reviewed:** 9
**Status:** issues_found (1 WARNING, 2 INFO — no BLOCKERs)

## Summary

This is the round-3 convergence check on the Pub 15-T 2026 federal-withholding calc,
the highest-bug-risk money-moving unit in the repo. I re-verified every round-2 fix,
ran the full suite, traced the cross-module call chain (orchestrator → calculate →
federal_withholding → tax_tables_2026), and probed for new defects.

**Round-2 fixes are correct and introduced NO regressions.** Full suite: 305 passed,
13 skipped, 1 xfailed (matches the stated baseline exactly). The four phase test files
pass 112/2-skip/1-xfail. Specifically verified:

- **bool/float/unknown-key guards** (`_to_decimal`, `_resolved_hours`): bool rejected
  before float/int (correct ordering for `bool ⊂ int`), float rejected, unknown keys
  rejected with a clear `ValueError`. All three behaviors confirmed live.
- **Unknown-key rejection cannot break the orchestrator.** The single production call
  site (`orchestrator.py:271-280`) builds `resolved_hours` from exactly the five
  canonical keys (`hours_regular/overtime/vacation/sick/holiday`). No legitimate caller
  (orchestrator, eval, tests) passes extra keys. Verified by reading the call site.
- **Status-aware Medicare threshold dict is complete.** `_ADDITIONAL_MEDICARE_THRESHOLDS`
  has all three valid `filing_status` Literal values (`single`/`married_jointly`/
  `married_separately`). **No KeyError risk:** I confirmed by set difference that the dict
  covers the Literal exactly, AND that even a Pydantic-bypassed `head_of_household` cannot
  reach the dict lookup because `federal_withholding_2026()` raises `ValueError` at
  `calculate.py:239` BEFORE the threshold lookup at `calculate.py:257-259`.
- **Single-round-per-branch gross** (IN-04): hourly and salary branches each round once.
  Verified arithmetically (James Okafor gross=1200.00, reconciliation ties).
- **New tests** (`test_bracket_upper_ties_to_next_lower`, `test_money_helpers_agree`,
  `test_additional_medicare_threshold_is_status_aware`) are sound and meaningfully assert.
- **Core invariants re-verified live:** FICA-on-gross vs federal-on-(gross−401k) (74.40 SS
  on gross, federal on 1152); /2080 leave pay (frequency-invariant, delta=200.00 at
  p=52/26/24/12); $0 floors (line_1i, line_3c); HoH `ValueError`; SS straddle (37.20);
  reconciliation identity.
- **Medicare flag boundary** uses strict `>`, matching the README "exceeds/over" wording
  (proxy exactly == threshold does NOT fire). Correct.

The Round-1 CR-01 (Single/MFS Step-2 $328,350 boundary) and the sub-dollar continuity
artifact are NOT re-raised — they were verified against the live IRS source and are
correct, with pin tests locking them.

One genuine consistency gap remains (WR-01 below): the raw-dict input seam guards bool,
float, and unknown-keys but NOT negative values — even though the module documents itself
as the last-line defense against "wrong numbers" on the raw-dict path. It is not reachable
through the current production orchestrator (model-layer `ge=0` blocks negatives upstream),
so it is a WARNING, not a BLOCKER.

## Warnings

### WR-01: Negative hours bypass the `_resolved_hours`/`_to_decimal` defensive seam, producing a negative paystub that passes reconciliation

**File:** `app/pipeline/calculate.py:63-92` (`_to_decimal`), `app/pipeline/calculate.py:104-119` (`_resolved_hours`)

**Issue:**
`_to_decimal` and `_resolved_hours` are explicitly documented as the defensive seam for
the raw-dict path that bypasses Pydantic validation:

- Line 67-69: *"calculate() takes a raw dict, so the engine — not just the caller — must enforce this."*
- Line 107-111: *"calculate() takes a raw dict (not a Pydantic model with extra="forbid"), so this is the only seam that can catch a malformed hours payload … a dropped key would zero that hours type and produce a wrong-but-reconciliation-passing paystub, violating the module's 'never silently ship a wrong number' thesis."*

The seam catches `bool`, `float`, and unknown keys — but it does **not** reject negative
values. `_to_decimal("-40")` returns `Decimal("-40")`, and the resulting paystub ships a
negative gross/net that passes the reconciliation backstop (a pure arithmetic identity that
cannot detect a wrong sign). Confirmed live:

```
calculate({"hours_regular": Decimal("-40")}, emp)
  -> gross_pay = -4000.00
  -> net_pay   = -3694.00
  -> reconciliation passes (no raise)  # exactly the "wrong-but-reconciliation-passing" failure the docstring names
```

A negative is the single most consequential "wrong number" this seam claims to guard, yet
it is the one omitted. The bool/float/unknown-key guards exist *precisely because* the raw
dict bypasses the model's `Field(ge=0)`; leaving negatives unguarded is internally
inconsistent with that rationale.

**Severity rationale (WARNING, not BLOCKER):** The only production caller, `orchestrator.py:271-280`,
sources hours from `ExtractedEmployee.hours_*`, which carry `Field(default=None, ge=0)`
(`contracts.py:75-79`) and are model-validated at extraction time
(`test_models_contracts.py:525`). So a negative cannot reach `calculate()` through the
current orchestrator. The gap is in the *documented defensive contract* of the raw-dict
seam, not in a live exploit path. It becomes a real defect the moment any future caller
(a new orchestrator path, an eval fixture, a script) passes hours through the raw dict
without going through `ExtractedEmployee` — which is exactly the scenario the seam exists for.

**Fix:** Reject negatives in `_to_decimal` (the same place bool/float are rejected), so the
guard is complete and matches the model-layer `ge=0`:

```python
def _to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, bool):
        raise TypeError(...)  # unchanged
    if isinstance(value, float):
        raise TypeError(...)  # unchanged
    if value == "":
        return Decimal("0")
    result = Decimal(value)
    if result < 0:
        raise ValueError(
            f"hours value must be non-negative (matches ExtractedEmployee Field ge=0): got {result}"
        )
    return result
```

Add a test mirroring the bool/float/unknown-key tests, e.g.:

```python
def test_negative_hours_rejected(hourly_employee):
    bad = _valid_hours()
    bad["hours_regular"] = Decimal("-40")
    with pytest.raises(ValueError, match="non-negative"):
        calculate(bad, hourly_employee)
```

## Info

### IN-01: `_to_decimal` raises `InvalidOperation` (not a domain error) for non-numeric strings

**File:** `app/pipeline/calculate.py:92`

**Issue:** `_to_decimal("abc")` raises `decimal.InvalidOperation` (a subclass of
`ArithmeticError`), not a `TypeError`/`ValueError` with a domain message. The function
deliberately raises *loud, typed* errors for bool/float ("hours value must not be …") but
falls through to a bare `Decimal(value)` for a garbage string, surfacing a low-level decimal
exception with no context about which field or why. This is a minor legibility gap relative
to the explicit messages the function uses elsewhere; it does not affect correctness
(it still fails loudly rather than silently coercing).

**Fix:** Optionally wrap the final coercion to attach context:

```python
try:
    result = Decimal(value)
except InvalidOperation as e:
    raise ValueError(f"hours value is not a valid number: got {value!r}") from e
```

Low priority — any failure here is already loud and only reachable from the raw-dict path.

### IN-02: `_HOH_STANDARD` / `_HOH_STEP2` tables are present but unreachable and untested

**File:** `app/pipeline/tax_tables_2026.py:72-86, 132-144` (and the `head_of_household`
entries at lines 96, 152, 175)

**Issue:** The Head-of-Household bracket tables and `STEP1_STANDARD["head_of_household"]`
are transcribed but unreachable: `filing_status` is Literal-constrained to exclude HoH
(`roster.py:57`), and `federal_withholding_2026()` raises `ValueError` for any non-supported
status before a lookup. They are explicitly marked `UNTESTED` in-code (IN-01 round 2). This
is already documented as an accepted state and is not a regression — recorded here only for
completeness so a future maintainer who enables the HoH path knows these rows have never been
cross-checked against the IRS golden/wage-bracket values. No action required this phase;
the existing `UNTESTED` comments and the reject-guard are the correct interim treatment.

**Fix:** None required now. Before enabling any HoH withholding path, transcribe and
cross-check the HoH wage-bracket cells against the live PDF (as the existing comment already
instructs), then add HoH to the golden matrix.

---

## Round 3 — Disposition (orchestrator, 2026-06-22) — FINAL

| ID | Verdict | Action taken |
|----|---------|--------------|
| **WR-01** | **VALID** | `_to_decimal()` now rejects negative values (mirrors ExtractedEmployee `Field(ge=0)`), completing the raw-dict defensive seam. Confirmed live the old behavior shipped a negative paystub that passed reconciliation. Regression test `test_negative_hours_rejected`. |
| **IN-01** | **VALID** | Non-numeric hours strings now raise a domain `ValueError("hours value is not a valid number")` instead of a bare `decimal.InvalidOperation`, matching the typed errors used for bool/float. Regression test `test_garbage_string_hours_raises_domain_error`. |
| **IN-02** | **No action (correct as-is)** | HoH tables already marked `UNTESTED` in round 2; reviewer confirmed "No action required this phase." |

**Round-2 fixes confirmed correct with NO regressions** (reviewer re-verified all guards, the orchestrator call-site safety, the complete status-aware threshold dict, and all core invariants live).

**Net:** 1 warning + 1 info fixed; 2 new regression tests; 1 info correctly closed with no action. Full suite: 307 passed, 13 skipped, 1 xfailed, 0 failed. N1 gate passes.

## Code-review loop outcome (3 rounds)

- **Round 1** (deep): 1 blocker + 4 warnings + 3 info. Blocker CR-01 **verified against the live IRS publication and refuted** (the bracket table is correct; changing it would have introduced a real under-withholding bug). 6 fixed, 1 deferred (out of phase scope), 2 structural guard tests added.
- **Round 2** (deep): 0 blockers, 4 warnings + 4 info — input-guard hardening + status-aware Medicare flag. All fixed, 6 guard tests added.
- **Round 3** (deep): 0 blockers, 1 warning + 2 info — negative-hours guard completion. Fixed, 2 tests added.

The trend converged: blocker → 0 blockers → 0 blockers, severity strictly decreasing each round, all findings either fixed or refuted-with-evidence. No outstanding correctness defects. Two intentional, documented coverage gaps remain for the operator: the Thomas Bergmann over-ceiling fixture (skipped, pending two-calculator verification) and the MFJ Standard wage-bracket independent oracle (strict xfail, pending transcription).

---

_Reviewed: 2026-06-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
