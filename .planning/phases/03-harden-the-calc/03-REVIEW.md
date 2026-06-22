---
phase: 03-harden-the-calc
reviewed: 2026-06-22T07:49:31Z
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
  critical: 1
  warning: 4
  info: 3
  total: 8
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-06-22T07:49:31Z
**Depth:** deep
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Reviewed the Phase 3 "harden-the-calc" engine at deep depth, with cross-file tracing
of the calc → federal-withholding → tax-tables chain and the test suite that guards it.
The phase-context invariants were verified one by one against the code: FICA-on-gross vs
federal-on-(gross − 401k) base split is **correct**; salaried leave pay uses the
frequency-independent `annual/2080 * leave_hours` form and a regression test pins it;
the reconciliation backstop correctly uses an explicit `PayrollCalculationError` raise,
not a strippable `assert`; the HoH reject-guard and the line-1i / line-3c $0 floors are
correct; Decimal is used throughout the production money path; per-step `ROUND_HALF_UP`
rounding is consistent and pinned. The full suite passes (102 passed, 1 skipped).

However, the single most important deliverable of this phase — the correctness of the
transcribed 2026 Pub 15-T bracket tables — has a **provable transcription defect in the
Single/MFS Step-2 schedule** that the test suite does not catch, and that silently
under-withholds high earners by up to ~$2,000/year. There is also a test-independence
violation in the "primary oracle" cross-check for one column, which is exactly the kind
of circularity the phase's golden-test design was supposed to forbid. Because the calc
engine is the explicitly-designated highest-bug-risk, money-moving unit, these rise to
blocker / high-warning severity despite the otherwise strong implementation.

## Critical Issues

### CR-01: Single/MFS Step-2 bracket table is internally inconsistent — top bracket boundary/base is wrong, silently under-withholds high earners

**File:** `app/pipeline/tax_tables_2026.py:116-126` (`_SINGLE_STEP2`)

**Issue:**
The `_SINGLE_STEP2` schedule fails an internal base/rate continuity check at two rows,
and the top-bracket boundary is provably wrong. For a percentage-method table, each
row's `base` must equal `prev.base + (this.lower − prev.lower) * prev.rate`. All other
five tables pass this check exactly. `_SINGLE_STEP2` does not:

```
row lower=108938: transcribed base=20512.00  derived=20512.12   (diff -0.12)
row lower=328350: transcribed base=96489.63  derived=96489.45   (diff +0.18)
```

Cross-checking against `_MFJ_STEP2` (which IS internally consistent) confirms the
defect. The IRS Step-2 schedules are built so MFJ boundaries are exactly 2× the
Single/MFS boundaries. That holds for the first seven rows of `_SINGLE_STEP2`
(`108938 ≈ 217875/2`, `136163 ≈ 272325/2`), but **breaks at the top bracket**:

```
MFJ Step-2 top lower = 400450  →  expected Single Step-2 top lower = 200225
transcribed Single Step-2 top lower = 328350   ← WRONG
```

The transcribed top base `96489.63` is also inconsistent with both the transcribed
`328350` (would need `96489.45`) and the structurally-expected `200225` (would need
`51645.70`), indicating the top row carries an intertwined boundary + base error.

Impact (money-moving): a single / married-filing-separately employee who checks the W-4
Step-2 box and whose **adjusted annual wage falls in `[200225, 328350)`** is taxed at
the 35% bracket instead of the correct 37% bracket. Concrete annual under-withholding:

```
adjusted annual wage 250000:  under-withheld ~$996/yr
adjusted annual wage 300000:  under-withheld ~$1,996/yr
```

This is exactly the class of bug the phase calls out as catastrophic ("silently wrong
paystubs"). The reconciliation backstop does NOT catch it (it only checks arithmetic
identity, not tax correctness — see `calculate.py:84-104`), and **no test exercises
this region**: the only Single/MFS Step-2 cross-check fixtures are weekly $550–$760
(`test_federal_withholding.py:275-284`), whose adjusted annual wage is far below
$200,225, so the wage-bracket oracle never touches the broken rows.

**Fix:**
Re-transcribe the Single/MFS Step-2 schedule's top brackets directly from the 2026
Pub 15-T PDF. Based on the MFJ-Step-2 = 2×Single-Step-2 structural relationship the
corrected top two rows are almost certainly:

```python
_SINGLE_STEP2: list[BracketRow] = [
    ...
    BracketRow(Decimal("108938"), Decimal("136163"), Decimal("20512.00"), Decimal("0.32")),
    BracketRow(Decimal("136163"), Decimal("200225"), Decimal("29224.00"), Decimal("0.35")),
    BracketRow(Decimal("200225"), None,              Decimal("51645.88"), Decimal("0.37")),
]
```

(Confirm `200225` and the top base against the printed PDF, then re-derive the base by
continuity.) Additionally, add a **structural continuity test** to
`tests/test_tax_tables_2026.py` so this class of error can never ship uncaught again:

```python
def test_bracket_base_continuity() -> None:
    """Each row's base must equal prev.base + (this.lower - prev.lower) * prev.rate."""
    from app.pipeline.tax_tables_2026 import STANDARD_BRACKETS, STEP2_BRACKETS
    for table in (STANDARD_BRACKETS, STEP2_BRACKETS):
        seen = set()
        for status, rows in table.items():
            if id(rows) in seen:  # skip the MFS alias of single
                continue
            seen.add(id(rows))
            for i in range(1, len(rows)):
                p, c = rows[i - 1], rows[i]
                expected = p.base + (c.lower - p.lower) * p.rate
                assert c.base == expected, (
                    f"[{status}] row {i}: base {c.base} != continuity-derived {expected}"
                )
```

## Warnings

### WR-01: Wage-bracket "primary oracle" for MFJ Standard is engine-derived, not independent — defeats the cross-check guarantee

**File:** `tests/test_federal_withholding.py:254-268` (Column 2 fixtures), comment at line 257

**Issue:**
The module docstring (lines 12-18) and the parametrized test (lines 360-371) assert that
NO expected value in the wage-bracket cross-check is derived from the engine, and that
this independence is what lets the cross-check catch a transcription error in
`tax_tables_2026.py`. But the "Column 2: Weekly MFJ Standard" fixtures carry the inline
admission `# Engine-computed at midpoint` (line 257). I verified every Column-2 cell
(`$15, $19, $29, $39, $49`) reproduces the engine output exactly at the interval
midpoint. These cells are therefore circular: they will always agree with the engine
even if both the engine and the MFJ Standard table are wrong, so this column provides
**zero** transcription-error detection — contradicting the stated D-01 self-derivation
ban for the very table they claim to guard.

**Fix:**
Replace the five MFJ Standard cells with values transcribed directly from the published
2026 Pub 15-T Wage Bracket Method MFJ weekly column (the same independent source used
for the Single/MFS Standard column, which I verified IS legitimately independent), and
delete the `# Engine-computed at midpoint` comment. If an independent transcription is
not available, mark the column `@pytest.mark.skip(reason="MFJ Standard wage-bracket
cells not independently transcribed")` rather than presenting engine output as an
oracle.

### WR-02: `calculate()` accepts an untyped `dict` of hours — float inputs silently contaminate Decimal money math

**File:** `app/pipeline/calculate.py:54-63` (`_resolved_hours`) and `:107-108` (signature)

**Issue:**
`calculate(resolved_hours: dict, ...)` takes a raw, unvalidated dict, and
`_resolved_hours` coerces each value with `Decimal(resolved.get(f) or 0)`. If any caller
passes an hours value as a Python `float` (e.g. `7.1`), `Decimal(7.1)` yields
`7.0999999999999996447...`, injecting float-representation error into gross and every
downstream amount — directly violating the project-wide D-05 "Decimal everywhere, never
float" invariant. The production orchestrator path is currently safe only because it
passes `ExtractedEmployee` fields that Pydantic has already coerced to `Decimal`
(`orchestrator.py:271-280`); nothing in `calculate()` itself enforces this, so the
invariant rests on a caller convention rather than the engine.

**Fix:**
Coerce defensively through `str()` so floats cannot leak, or assert the type:

```python
def _to_decimal(v) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, float):
        raise TypeError(f"hours must not be float (D-05): got {v!r}")
    return Decimal(v)

return {f: _to_decimal(resolved.get(f)) for f in fields}
```

(`Decimal(str(v))` is the softer alternative if you prefer coercion over rejection.)

### WR-03: `ExtractedEmployee` hours accept negative-free but unbounded fractional/huge values; `calculate()` does no sanity bound

**File:** `app/models/contracts.py:75-79` and `app/pipeline/calculate.py:122-136`

**Issue:**
`ExtractedEmployee` constrains hours to `ge=0` but places no upper bound, and
`calculate()` applies no plausibility check. An extraction LLM hallucinating
`hours_regular = 4000` (or a misparsed `40.00` as `4000`) produces a multi-thousand-hour
gross that sails through the engine and the reconciliation backstop (which only checks
arithmetic identity), reaching the operator as a "clean" computed payroll. For a
money-moving pipeline whose thesis is "never silently ship a wrong number," an absent
upper bound on the single most LLM-influenced input is a real robustness gap.

**Fix:**
Add a defensible per-period upper bound (e.g. `le=Decimal("744")`, the hours in the
longest month) on each hours field in `ExtractedEmployee`, or add a validation issue in
the validate stage so an implausible hours value gates to clarification rather than
computing silently. Document the chosen ceiling.

### WR-04: Over-ceiling federal withholding has zero passing coverage — the high-earner path ships unverified

**File:** `tests/test_federal_withholding.py:1065-1078` (skipped) and module docstring lines 19-32

**Issue:**
The only test covering an adjusted per-period wage above the wage-bracket ceiling
(~$100k annualized) is `test_federal_withholding_thomas_bergmann_over_ceiling`, which is
`@pytest.mark.skip` with reason "OVER-CEILING ORACLE UNRESOLVED ... operator asleep,
pre-authorized skip." Every golden and cross-check fixture that actually runs is
below-ceiling. The engine's high-earner percentage-method path (top 35% / 37% brackets,
including the CR-01 region) is therefore exercised by no passing assertion. The skip is
honestly labeled, but it means a transcription error in any top bracket — exactly where
CR-01 lives — has no test that would fail. This is a coverage hole in the
highest-consequence region of the highest-bug-risk unit.

**Fix:**
Resolve the layer-B oracle (the two independent calculators the docstring requires) and
unskip at least one over-ceiling fixture per filing status, OR add an independent
hand-computed over-ceiling golden value with a documented derivation. At minimum, the
structural continuity test from CR-01 should be added now, since it catches top-bracket
transcription errors without needing an external calculator.

## Info

### IN-01: Redundant second `_money(gross)` on the salaried path

**File:** `app/pipeline/calculate.py:154` and `:156`

**Issue:**
On the salaried branch `gross` is already cent-quantized at line 154
(`gross = _money(period_salary + leave_pay)`), then re-quantized at line 156
(`gross = _money(gross)`). The second call is a no-op for the salaried path. Harmless,
but mildly misleading about where rounding happens.

**Fix:**
Leave line 156 as the single rounding point and drop the inner `_money()` at line 154
(quantize once, after the branch), or add a comment noting the hourly branch is the one
that needs line 156.

### IN-02: Dead default arguments in salaried leave-hours summation

**File:** `app/pipeline/calculate.py:149-151`

**Issue:**
`hours.get("hours_vacation", Decimal("0"))` (and sick/holiday) supply a default that can
never be reached: `_resolved_hours` always returns all five keys populated. The
defensive default is dead code that implies the keys might be absent.

**Fix:**
Use direct subscripts (`hours["hours_vacation"]`) for consistency with the hourly branch
(lines 131-135), which already assumes the keys exist.

### IN-03: README "all filing statuses" overstates supported coverage

**File:** `README.md:20`

**Issue:**
The README states net pay includes withholding "(Worksheet 1A percentage method, **all
filing statuses**)." The engine supports only single / married_jointly /
married_separately and explicitly raises `ValueError` for head_of_household
(`federal_withholding.py:100-107`). "All filing statuses" is inaccurate for a
recruiter-facing artifact.

**Fix:**
Change to "(Worksheet 1A percentage method; single, married-filing-jointly, and
married-filing-separately. Head-of-household is intentionally out of scope and rejected.)"

---

## Round 1 — Disposition (orchestrator, 2026-06-22)

Each finding was verified before action (money-moving code — verify, don't blindly implement).

| ID | Verdict | Action taken |
|----|---------|--------------|
| **CR-01** | **REFUTED (boundary) / cent-artifact (base)** | The headline claim — Single/MFS Step-2 37% should begin at $200,225 — is **wrong**. Verified against the live IRS source (irs.gov/publications/p15t, 2026, retrieved 2026-06-22): the 37% bracket begins at **$328,350** with base **$96,489.63**, exactly as transcribed. The "MFJ = 2× Single" heuristic does NOT hold for IRS Step-2 schedules. The base-continuity "mismatches" ($0.12, $0.18) are the IRS's own inherent boundary-rounding artifacts (IRS prints $20,512.00 where pure continuity gives $20,512.12 — both correct). **Did NOT change any tax constant.** Added two guards instead: `test_single_step2_top_bracket_boundary_verified_against_irs` (pins the IRS-verified values so the refuted "fix" can't be applied) and `test_bracket_base_continuity_smoke` (catches *dollar-scale* transcription errors across all six schedules, with sub-dollar tolerance for IRS rounding). |
| **WR-01** | **VALID** | Confirmed circular: the MFJ Standard cross-check cells were engine-computed (line 257). Removed them rather than present engine output as an independent oracle. Could not fetch reliable independent MFJ Standard cells (PDF table extraction unreliable; this is exactly why layer-B is a human checkpoint). Added `test_mfj_standard_wage_bracket_oracle_unresolved` (strict xfail) to keep the gap visible. MFJ Standard correctness is still covered by the D-04 golden matrix (James Okafor). |
| **WR-02** | **VALID** | Added `_to_decimal()` in calculate.py: rejects float hours with a `TypeError` (D-05 "Decimal everywhere"). Verified no production/test path passes floats (hours are Pydantic `Decimal` throughout) — purely defensive. |
| **WR-03** | **VALID, deferred (out of phase scope)** | Unbounded hours is real, but input validation belongs in the validate stage and `ExtractedEmployee` is not a Phase 3 calc file. Logged for a future validation pass; not a calc-engine defect. |
| **WR-04** | **VALID, known** | This is the pre-authorized Thomas Bergmann over-ceiling skip (operator decision pending). Mitigated the top-bracket *transcription* risk via the new continuity smoke-test (catches a wrong top base/boundary without an external calculator). The over-ceiling *withholding value* still awaits the two-calculator human verification. |
| **IN-01** | **VALID** | Dropped the redundant inner `_money()` rationale into a clarifying comment (the salaried branch quantizes once; the final `_money()` is for the hourly branch). |
| **IN-02** | **VALID** | Replaced dead `.get(..., Decimal("0"))` defaults with direct subscripts (keys always present). |
| **IN-03** | **VALID** | README "all filing statuses" → "single, MFJ, MFS; head-of-household intentionally out of scope and rejected." |

**Net:** 1 blocker refuted with authoritative-source evidence (no tax constant changed — changing it would have *introduced* a bug); 3 warnings + 3 info fixed; 1 warning deferred with rationale; 2 new structural guards added. Full suite: 299 passed, 13 skipped, 1 xfailed, 0 failed. N1 gate passes.

---

_Reviewed: 2026-06-22T07:49:31Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
