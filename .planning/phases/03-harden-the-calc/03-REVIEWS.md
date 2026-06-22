---
phase: 3
reviewers: [codex]
reviewed_at: 
plans_reviewed: [03-01-PLAN.md, 03-02-PLAN.md, 03-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 3

## Codex Review

**Summary**

The plans are directionally strong, but I would not approve them as-is for a tax-correctness phase. The main architecture is right: isolated constants, isolated withholding engine, deterministic Decimal tests, explicit disclaimers. The weak points are material: the salaried leave formula is wrong, wave dependencies are invalid, rounding/oracle guarantees are overstated, and the Additional Medicare guard uses the wrong trigger field/condition. Those issues can ship green tests while still producing wrong pay.

**Strengths**

- Good separation: `tax_tables_2026.py`, `federal_withholding.py`, and `calculate.py` keep tax constants, withholding logic, and paystub assembly auditable.
- Correctly protects several known traps: Step-1g proxy amounts, Single/MFS mapping, checkbox tables not halved, Step-3 floor at zero.
- Using IRS wage-bracket tables as an under-ceiling cross-check is a good secondary IRS-authored oracle. Pub 15-T confirms those wage-bracket tables are limited and route over-ceiling wages back to percentage methods. ([irs.gov](https://www.irs.gov/pub/irs-pdf/p15t.pdf))
- The Additional Medicare test intent is right: assert an observable limitation, not that flat 1.45% is “correct” above $200k. IRS says employers withhold 0.9% once wages paid exceed $200,000. ([irs.gov](https://www.irs.gov/taxtopics/tc751))

**Concerns**

- **HIGH — 03-03 salaried leave pay formula is inverted.** The plan says `standard_hours = 40 * pay_periods / 52`; it should be `40 * 52 / pay_periods`, or just `annual_salary / 2080 * leave_hours`. For semi-monthly, the plan uses ~18.46 hours/period; the correct standard period hours are ~86.67. The proposed test codifies the bug.

- **HIGH — Wave 2 is not actually parallel.** `03-02` expects `calculate()` integration behavior, `additional_medicare_not_modeled`, `PaystubLineItem` changes, README edits, and FICA integration that are implemented in `03-03`. Either `03-02` must depend on `03-03`, or `03-02` must be limited to pure `federal_withholding_2026` tests.

- **HIGH — Oracle independence is weaker than claimed.** Wage-bracket checks only validate covered under-ceiling midpoint cells at whole-dollar granularity. They do not prove penny-exact Worksheet 1A behavior, Step-3/Step-4 interactions, high-earner rows, or untested intervals. For Thomas, the fallback allowing “hand trace authoritative” if calculators disagree undermines the two-calculator independence rule.

- **HIGH — Rounding plan can mask or create false results.** Pub 15-T says wage/tax whole-dollar rounding is optional and, if used, half-up. ([irs.gov](https://www.irs.gov/pub/irs-pdf/p15t.pdf)) The plan uses per-step cent quantization, which is a chosen convention, not an IRS-required step sequence. Also `round(engine_result)` is Python/Decimal half-even risk; use `quantize(Decimal("1"), rounding=ROUND_HALF_UP)`.

- **HIGH — Additional Medicare flag trigger is wrong.** `employee.ytd_ss_wages > 200000` is not the right condition. Social Security wages are capped at $184,500 for 2026, while Medicare has no wage base limit. ([ssa.gov](https://www.ssa.gov/oact/cola/cbb.html)) The flag should trigger when known Medicare/current wage proxy crosses `$200,000`, e.g. prior YTD + current gross > threshold. If no Medicare YTD field exists, name it as an approximation/limitation.

- **MEDIUM — `assert` is not a durable reconciliation guard.** Python optimization disables assertions. Use an explicit `if reconstructed != gross: raise PayrollCalculationError(...)`, and test the helper directly.

- **MEDIUM — `python-taxes` structural test is underspecified and likely not implementable.** The planned engine is hardcoded to 2026 tables. A 2024 comparison needs table injection/generalized year support, or the test should be dropped/skipped. Adding a dev dependency also modifies `pyproject.toml`/lockfiles not listed in `03-02`.

- **MEDIUM — Missing boundary tests.** Add exact bracket lower bound, `upper - $0.01`, and exact upper bound cases. `_find_bracket()` is lower-bound driven, so boundary regressions are plausible and not covered by midpoint wage-bracket checks.

- **LOW — Metadata drift.** `03-02` lists only `tests/test_federal_withholding.py` but also updates README and adds a dependency. `03-03` changes `contracts.py`; that contract change needs downstream serialization/eval audit.

**Suggestions**

- Fix salaried leave immediately: `leave_pay = _money((annual / Decimal("2080")) * leave_hours)`, or `standard_hours = Decimal("40") * Decimal("52") / p`.
- Reorder: `03-01 → 03-03 → 03-02`, or split `03-02` into engine-only golden tests and post-`03-03` integration tests.
- Make wage-bracket assertions exact whole-dollar half-up unless a specific documented PDF extraction anomaly requires `±$1`.
- Require two agreeing external calculator results for Thomas before committing the over-ceiling fixture; otherwise skip that fixture rather than blessing the hand trace.
- Add boundary tests, SS cap exhausted case, Step-4b large-deduction floor case, and explicit MFS standard/checkbox mapping tests.
- Replace the Additional Medicare bool condition with a “known limitation may apply” calculation based on current gross plus a correctly named YTD wage proxy.

**Risk Assessment**

**HIGH** as written. The plans have the right shape, but the salary-leave bug, invalid wave dependency, and overstated oracle/rounding guarantees are exactly the kind of issues that produce green tests with wrong payroll numbers. After fixing those, the phase would drop to MEDIUM risk, mostly because the 2026 oracle remains partly manual and over-ceiling verification depends on external calculators.

---

## Consensus Summary

Single reviewer (Codex). Overall verdict: **HIGH risk as written** — right architecture, but several issues that can ship green tests over wrong payroll numbers.

### Top findings (by severity)

**HIGH — must fix before execution:**
1. **Salaried leave-pay formula is INVERTED** (03-03). Plan uses `standard_hours_per_period = 40 × pay_periods / 52` → semi-monthly gives ~18.46h; correct is `40 × 52 / pay_periods` ≈ 86.67h (or simply `annual/2080 × leave_hours`). The Fix-11 semi-monthly test was written to codify the bug. **This is a real bug the planner, both plan-checker passes, and the external tax-critique all missed.**
2. **Additional-Medicare flag uses the wrong trigger field.** `employee.ytd_ss_wages > 200000` is wrong: SS wages are CAPPED at $184,500 for 2026, so they can never exceed $200k. The $200k threshold is a MEDICARE-wage concept (no cap). Trigger must use a Medicare/current-wage proxy (prior YTD + current gross), or be named explicitly as an approximation/limitation.
3. **Wave 2 is not genuinely parallel.** 03-02 still references calculate()-integration behavior / the additional_medicare flag / PaystubLineItem changes implemented in 03-03 — so a residual forward dependency remains despite the Fix-9 move.
4. **Rounding `round(...)` risk** — use `quantize(Decimal("1"), ROUND_HALF_UP)` for the whole-dollar wage-bracket comparison, not Python `round()` (banker's/half-even). And the per-step cent quantization is a CHOSEN convention, not IRS-mandated — document it as such.
5. **Oracle independence is narrower than claimed** — wage-bracket checks only validate covered under-ceiling midpoint cells at whole-dollar granularity; they do NOT prove penny-exact behavior, Step-3/4 interactions, or untested intervals. The Thomas over-ceiling fallback ("hand trace authoritative if calculators disagree") undermines the two-calculator independence rule.

**MEDIUM:**
6. `assert` for the reconciliation guard is disabled under `python -O` — use an explicit `if ... raise PayrollCalculationError`.
7. python-taxes structural test likely not implementable unless the engine accepts injectable year tables (it's hardcoded to 2026); also the dev-dep modifies pyproject/lock not listed in 03-02 files_modified.
8. Missing boundary tests — exact bracket lower bound, `upper − $0.01`, exact upper bound (since `_find_bracket()` is lower-bound driven; midpoint checks won't catch boundary regressions).

**LOW:**
9. Metadata drift — 03-02 omits README + the dev-dep/pyproject from files_modified; 03-03's contracts.py change needs a downstream serialization/eval audit.

### Agreed Strengths
- Clean separation (constants / engine / assembly); auditable.
- Known traps protected: Step-1g proxy, Single/MFS mapping, checkbox-not-halved, Step-3 floor-at-$0.
- Wage-bracket tables as an under-ceiling IRS-authored cross-check is a good secondary oracle.
- Additional-Medicare test INTENT is right (assert the limitation flag, not flat-1.45%-correctness).

### Divergent Views
N/A (single reviewer).


---

# Cross-AI Plan Review — Phase 3 (Round 2 — re-review after FIX A–H)

**Reviewer:** Codex · **Reviewed:** 2026-06-22T06:44:11Z · **Verdict:** MEDIUM risk (down from HIGH); "ready to execute? no — fix wage-bracket tolerance + the two flawed tests first, then yes-with-nits"

## Codex Re-Review

**Fix Verification**

| Fix | Status | Evidence / Gap |
|---|---|---|
| FIX A, salaried leave | CONFIRMED-FIXED | 03-03 now specifies `leave_pay = _money((annual / _ANNUAL_WORK_HOURS) * leave_hours)` with `_ANNUAL_WORK_HOURS = Decimal("2080")`, and adds `delta_52 == delta_24 == delta_12 == Decimal("200.00")`. No remaining salary leave path uses `40 * pay_periods / 52`. Add `p=26` to the invariant test, but the formula itself is correct. |
| FIX B, Additional Medicare flag | PARTIALLY-FIXED | The trigger is now `additional_medicare_not_modeled = (employee.ytd_ss_wages + gross) > ...`, and the plan honestly documents under-flagging when true Medicare YTD exceeds capped SS YTD. That matches IRS/SSA facts: Medicare has no cap, SS is capped at $184,500, and Additional Medicare withholding starts once wages paid exceed $200,000. ([irs.gov](https://www.irs.gov/taxtopics/tc751)) ([ssa.gov](https://www.ssa.gov/oact/cola/cbb.html)) Gap: tests use impossible `ytd_ss_wages=Decimal("196000")` / `197000`. If this field is SS wages, it should not exceed `$184,500`. Use capped YTD plus a large current gross. |
| FIX C, reconciliation raise | PARTIALLY-FIXED | Implementation text uses `raise PayrollCalculationError(...)`, not `assert`. But the test plan backs off to source grep: “if monkeypatching is complex, at minimum assert the class exists.” That does not test the raise path. Prior claim said it “asserts the raise on drift”; the revised plan does not guarantee that. |
| FIX D, wave order | CONFIRMED-FIXED | 03-03 is `wave: 2` and `depends_on: [03-01]`; 03-02 is `wave: 3` and `depends_on: [03-01, 03-03]`. 03-02 still imports `calculate()`/`PaystubLineItem`, but only after 03-03 ships. The graph is acyclic. |
| FIX E, rounding | PARTIALLY-FIXED | The Python `round()` risk is fixed: plan requires `quantize(Decimal("1"), rounding=ROUND_HALF_UP)`, consistent with Pub 15-T’s optional whole-dollar half-up rounding guidance. ([irs.gov](https://www.irs.gov/pub/irs-pdf/p15t.pdf)) Gap: wage-bracket assertions use `abs(cell_whole_dollar - published_cell) <= 1`, which can mask a real $1 tax-table or line-1g bug. |
| FIX F, python-taxes | CONFIRMED-FIXED, with nit | The structural test is dropped: “Do NOT add a python-taxes structural test.” That closes the non-implementable 2024/2025-vs-2026 issue. New nit: the plan still runs `uv add --dev python-taxes` even though no test uses it. That is unnecessary dependency churn. |
| FIX G, boundary tests | PARTIALLY-FIXED | The plan adds boundary cases at `B`, `B - Decimal("0.01")`, and `B + Decimal("0.01")`. Good intent. Gap: constructing weekly per-period wages via `(B + STEP1_STANDARD) / 52` may not actually land on the exact annual boundary after the engine’s `_money(line_1a * p)` rounding. Test `_find_bracket()` directly or use a frequency/boundary divisible to cents. |
| FIX H, metadata | CONFIRMED-FIXED | 03-02 now lists `pyproject.toml`, `uv.lock`, and `README.md`; 03-03 lists `contracts.py`. The prior file-list drift is fixed. |
| Over-ceiling Thomas rule | CONFIRMED-FIXED, with residual risk | The bad fallback is gone: “A lone hand trace is NOT authoritative,” and disagreement marks the fixture skipped. Good. Residual: if skipped, CI can still go green without over-ceiling/high-earner coverage, even though Pub 15-T wage-bracket tables explicitly stop around `$100k` annualized and route above-ceiling cases to percentage tables. ([irs.gov](https://www.irs.gov/pub/irs-pdf/p15t.pdf)) |

**New Concerns**

- HIGH - The `±$1` wage-bracket tolerance weakens the primary oracle. At midpoint plus whole-dollar half-up, expected cells should be exact unless a specific extraction anomaly is documented per row. A blanket `<= 1` can ship green with wrong withholding.

- MEDIUM - Additional Medicare tests use impossible SS YTD values above the 2026 SS wage base. This tests the Boolean expression, not the stated lower-bound proxy.

- MEDIUM - Reconciliation failure is not directly tested. A source grep proves “not this exact assert string,” not that arithmetic drift raises `PayrollCalculationError`.

- MEDIUM - Boundary tests may miss the boundary because the engine rounds annualized wages to cents before bracket lookup. Directly test `_find_bracket()` or choose exact cent-reachable cases.

- MEDIUM - The over-ceiling fixture skip path is safe against false certainty but unsafe as a completion signal. If Thomas is skipped, the phase should report “over-ceiling oracle unresolved,” not merely pass.

- LOW - 03-02’s acceptance criteria say wage-bracket cross-check covers “at least 4 schedule columns,” while the objective claims all 6 schedules. Make the acceptance match the requirement.

- LOW - Installing unused `python-taxes` adds lockfile churn and supply-chain surface without verification value.

**Residual Concerns**

Oracle independence is much better, but still not airtight: under-ceiling wage-bracket checks are whole-dollar, high-earner coverage may be skipped, and some penny-exact hand traces can still be derived from the same percentage tables unless the expected values are hardcoded from an independent trace.

Rounding is documented as a chosen convention, which is acceptable, but the suite must stop implying that per-step cent quantization is IRS-mandated.

**Suggestions**

1. Change wage-bracket checks to exact equality after `quantize(Decimal("1"), ROUND_HALF_UP)`. Allow `±$1` only on a named fixture with a documented extraction reason.

2. Fix Additional Medicare tests to use realistic capped SS YTD, for example `ytd_ss_wages=184500` and current gross `>15500`, then assert the flag.

3. Extract reconciliation into a tiny helper, e.g. `_raise_if_reconciliation_drift(...)`, and unit-test both pass and fail paths.

4. Test `_find_bracket()` directly with annual adjusted wages `B - 0.01`, `B`, and `B + 0.01`, or use exact monthly cases.

5. Remove `python-taxes` from this phase unless a real year-injection structural test is added later.

6. If Thomas is skipped, make the phase summary and success gate explicitly say over-ceiling coverage is unresolved.

**Risk Assessment**

Overall risk: MEDIUM, down from HIGH. The salary formula, wave order, metadata, and over-ceiling fallback are materially improved. I would not execute as-is because the primary oracle now tolerates `$1` discrepancies and the Additional Medicare/reconciliation verification still has holes.

Ready to execute? no. Fix the blanket wage-bracket tolerance and the flawed tests first; after that, yes-with-nits.

---

## Round-2 Consensus Summary

Codex re-reviewed the 8 fixes. The two HIGH money-moving bugs from round 1 are **CONFIRMED-FIXED** (inverted leave formula → /2080; plus wave order, metadata, over-ceiling fallback). Remaining items are mostly MEDIUM test-rigor gaps + one HIGH about the primary oracle's tolerance.

### Fix verification (Codex)
| Fix | Round-2 status |
|-----|----------------|
| A — leave /2080 + invariance test | CONFIRMED-FIXED (suggest adding p=26 to the invariance test) |
| B — Medicare proxy trigger | PARTIALLY — trigger logic + documented under-flagging are sound, but the TEST uses impossible `ytd_ss_wages=196000/197000` (SS capped at 184,500) |
| C — raise-not-assert | PARTIALLY — impl is a real raise, but the test backs off to a source-grep ("assert class exists") and does NOT actually exercise the drift→raise path |
| D — wave order | CONFIRMED-FIXED (acyclic; 03-02 imports calculate() only at wave 3) |
| E — quantize-not-round | PARTIALLY — `round()` risk fixed, but the wage-bracket assertion uses `abs(cell - published) <= 1` blanket ±$1 tolerance |
| F — python-taxes dropped | CONFIRMED-FIXED (nit: still `uv add --dev python-taxes` though nothing uses it → unused dep churn) |
| G — boundary tests | PARTIALLY — good intent, but constructing the boundary via `(B + STEP1_STANDARD)/52` may not land on the exact annual boundary after `_money(line_1a * p)` cents-rounding; test `_find_bracket()` directly |
| H — metadata | CONFIRMED-FIXED |
| Over-ceiling Thomas rule | CONFIRMED-FIXED, residual: a skipped fixture lets CI go green with NO over-ceiling/high-earner coverage — should surface as "over-ceiling oracle unresolved," not silent pass |

### Round-2 findings to act on
- **HIGH — blanket ±$1 wage-bracket tolerance weakens the PRIMARY oracle.** At midpoint + whole-dollar half-up, expected cells should be EXACT (`==` after quantize). A blanket `<= 1` can ship green over a real $1 table/line-1g bug. Allow ±$1 only on a NAMED fixture with a documented extraction reason.
- **MEDIUM — Additional-Medicare tests use impossible SS-YTD values** (196k/197k > 184.5k cap). Use realistic capped YTD (e.g. `ytd_ss_wages=184500` + current gross `>15500`) then assert the flag fires.
- **MEDIUM — reconciliation drift→raise is not directly tested** (source grep only). Extract a tiny `_raise_if_reconciliation_drift(...)` helper and unit-test BOTH pass and fail paths.
- **MEDIUM — boundary tests may miss the boundary** due to annualization cents-rounding; test `_find_bracket()` directly or use exact cent-reachable cases.
- **MEDIUM — skipped over-ceiling fixture should report "unresolved," not pass silently.**
- **LOW — acceptance says wage-bracket covers "≥4 schedule columns" but objective claims all 6** — reconcile.
- **LOW — remove unused `python-taxes` dev dep** (supply-chain/lockfile churn with no verification value now).

### Net
Architecture and the money-moving fixes are solid. The blocker for "ready to execute" is the test suite's own rigor — exactly the unit this phase is meant to make bulletproof: tighten the oracle to exact-equality, fix the two impossible/weak tests, and make boundary + reconciliation tests actually exercise their paths.
