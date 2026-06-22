# Phase 3: Harden the Calc - Context

**Gathered:** 2026-06-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 3 deepens the existing thin pure calc (`app/pipeline/calculate.py` — currently gross + FICA only, federal = `Decimal("0")`, net labeled "pre-federal") into payroll math that is **trustworthy to the penny**: real IRS Pub 15-T **2026** federal withholding plus full-fidelity gross / FICA / 401k / net, asserted by **golden-value tests** against an independent oracle — landing BEFORE the eval (Phase 4) or dashboard (Phase 5) ever presents a number as correct.

**The 8 Phase 3 requirements (authoritative, per ROADMAP.md / REQUIREMENTS.md):** CALC-01, CALC-02, CALC-03, CALC-04, CALC-05, CALC-06, CALC-07, CALC-08.

**In scope:**
- Federal withholding via the **real Pub 15-T 2026 percentage method** (Worksheet 1A, all 3 filing statuses + the Step-2-checkbox branch), standard method only — OBBBA disclaimed (CALC-05). After this, the run's net becomes a **real net** (gross − pre-tax − FICA − federal); the "pre-federal" label is retired.
- Full-fidelity **gross**: hourly with FLSA overtime at 1.5× (CALC-01), salary proration = annual ÷ pay periods + added leave pay (CALC-02).
- **401k** pre-tax deduction as a percent of gross that reduces the **federal taxable base but NOT the FICA base** (CALC-03).
- **FICA**: SS 6.2% up to the 2026 $184,500 wage base honoring static YTD SS wages; Medicare 1.45% no cap (CALC-04). (Already implemented in the thin calc — Phase 3 keeps it correct and migrates its constants, see D-02.)
- **Net** = gross − pre-tax − FICA − federal (CALC-07).
- A dated, **year-keyed tax-constants module** (source URL + retrieval date in header) (CALC-06, see D-02).
- A **golden-value test suite** asserting hand-/IRS-sourced 2026 paystubs to the penny with `Decimal` (CALC-06, see D-04).
- The **reconciliation check** (CALC-08) — an arithmetic backstop only (net + taxes + deductions ties to the run total), explicitly **NOT** the correctness oracle for the tax math (the golden tests are the oracle).

**Out of scope (later phases / never):**
- **State withholding** — `state_withholding` column stays nullable; flat-rate line is v2 (CALC-V2-01).
- **OBBBA tax provisions** (qualified-tips/overtime above-the-line deductions, the expanded 15-line W-4 Step-4(b) worksheet) — disclaimed in the README; standard percentage method only.
- **Additional Medicare 0.9%** over $200k YTD — never triggers at demo wage levels; disclaimed, NOT modeled.
- **Per-employee YTD tax ledger** — v2 (CALC-V2-02); Phase 3 uses the static seeded `ytd_ss_wages` only.
- The eval that scores these functions (Phase 4), the dashboard that renders the paystubs (Phase 5), PDFs (Phase 5).

**Nature of the work:** This is a **pure-function calc deepening** — no LLM, no DB, no webhook, no UI. The judgment spine (extract → reconcile → validate → decide) already works (Phase 2 + 2.1, 195 mocked tests green). Phase 3 touches `calculate.py`, adds a tax-constants module, and adds golden tests. Per STATE.md build-time guidance, **Phase 3 is the designated slack-absorber**: the three core eval metrics don't depend on it, so a slip here doesn't threaten the spine.

</domain>

<decisions>
## Implementation Decisions

### Area 1 — Golden-oracle sourcing (the load-bearing decision)
- **D-01:** The federal-withholding golden values come from **the IRS Pub 15-T's OWN worked examples as the primary independent oracle**, backed by an **independent online payroll calculator** spot-check.
  - **Why this is load-bearing (STATE.md build-time guidance, CALC-08 trap recreated in the oracle):** the golden values MUST be independent of the 2026 tables the code transcribes. If the oracle were derived from the same transcribed `tax_tables_2026` module, a transcription typo would make code AND test wrong in the same direction and they would falsely tie out. The IRS worked examples are authored by the IRS — fully independent of your table transcription — so they are the most defensible oracle (the oracle is the IRS itself).
  - **Two-layer fixture structure (flagged for the planner):** the IRS worked-example wage figures will NOT match the seeded employees. So the golden suite needs **(layer A)** IRS-example fixtures — verbatim inputs and expected outputs transcribed from the PDF's worked Worksheet 1A examples (this is the true independence guarantee), and **(layer B)** a few seeded-employee fixtures whose expected values are cross-checked against an independent calculator (proves YOUR code correctly feeds YOUR employees into the worksheet). Both layers required.
  - **Layer-B oracle MUST be the right KIND of calculator, and TWO of them for uncovered cells (review hardening — critical):** Pub 15-T ships only a couple of worked examples, so layer A realistically verifies only one or two filing-status / bracket cells; the rest of the D-04 matrix leans on layer B. Two hazards:
    1. **Wrong method = false mismatch.** Most consumer take-home-pay / paycheck estimators compute *annual liability* or use simplified formulas, NOT the per-period **Pub 15-T employer percentage method**. Such a calculator disagrees with the engine to the penny *even when both are correct*, and a methodology delta is indistinguishable from a transcription bug — which defeats the whole point of an independent oracle. Layer B MUST use a calculator that **explicitly implements the Pub 15-T withholding percentage method** (e.g. PaycheckCity in IRS-percentage-method mode, or equivalent — the **researcher confirms which tools actually expose that method**), not a generic paycheck estimator.
    2. **One source is not verification.** For any matrix cell the IRS examples (layer A) do NOT reach, **two independent percentage-method calculators must agree** before that cell's golden value is trusted; a single source is a coin flip you cannot audit. The researcher's job includes identifying ≥2 such tools.
  - **python-taxes (the research-referenced ref lib) is NOT the 2026 oracle:** it ships 2023–2025 tables only, so it cannot produce 2026 ground truth. Usable at most as a *method/structure* sanity check against an older year, not as a 2026 penny oracle. Do not depend on it for golden values. (It *does* implement the percentage method, so it is a legitimate *structure* cross-check — just never for 2026 numbers.)

### Area 2 — Tax-constants module shape
- **D-02:** **ONE year-keyed module holds ALL year-specific tax constants** — the Pub 15-T 2026 percentage-method bracket tables + the per-status Step-1 standard amounts AND the FICA constants (SS rate / $184,500 wage base, Medicare 1.45% rate). The FICA constants currently **inline in `calculate.py`** (`_SS_RATE`, `_SS_WAGE_BASE`, `_MEDICARE_RATE`) are **migrated out** into this module.
  - **Why:** DRY + a single audit point for year-over-year updates. CALC-06 wants a dated source-of-record header; putting SSA-sourced and IRS-sourced numbers in one dated module means one header (covering both the SSA Contribution & Benefit Base URL and the IRS Pub 15-T URL + retrieval date) and one place to bump for a future 2027.
  - **Header requirement (CALC-06):** the module header MUST carry the source URLs (`irs.gov/pub/irs-pdf/p15t.pdf` 2026 edition; `ssa.gov/oact/cola/cbb.html` for the wage base) and the **retrieval date**.
  - **Year-keying:** structured so a future tax year is an additive change, not a rewrite (planner's discretion on exact shape — e.g. keyed by `tax_year`, or a `_2026`-suffixed module that a thin selector picks; the constraint is "adding 2027 doesn't edit 2026").
  - **Migration constraint (flagged for the planner):** the existing FICA tests (`test_calculate.py` and any FICA golden) currently pin the inline values — the constants MOVE, the VALUES do not change, so those tests must stay green through the migration.

### Area 3 — Calc edge cases
- **D-03:** **Overtime is paid from an EXPLICIT `hours_overtime` field only** — the calc trusts the submitted split and NEVER auto-derives OT by splitting `hours_regular` over 40. `hours_regular` is paid straight-time even if it exceeds 40.
  - **Why:** payroll emails arrive with the split already stated ("45 hrs, 5 OT"); and crucially, **biweekly / semi-monthly employees submit PERIOD totals, not single-workweek hours** — auto-splitting a period total at a 40-hour boundary would over-pay OT. The calc has no workweek concept and must not guess one. Keeping OT explicit keeps `calculate` a pure function of submitted fields. Demo/golden fixtures control the split.
  - **CALC-01 threshold note (already settled by the success criterion, restated for clarity):** "1.5× over 40 hours WORKED, paid-leave hours EXCLUDED from the 40-hour threshold" — vacation/sick/holiday hours do NOT count toward the 40 that triggers OT. With explicit-OT-only (D-03), this manifests as: leave hours are paid at straight time and never enter any OT calculation.
- **Confirmed-not-gray (pinned by the success criteria, NOT re-opened):**
  - **Salaried leave pay:** salary gross = annual ÷ pay_periods **PLUS** added vacation/sick/holiday pay (CALC-02). (The current thin calc ignores leave for salaried employees — Phase 3 adds it.)
  - **401k base:** 401k is a percent **of gross** (CALC-03), and it reduces the **federal taxable base but NOT the FICA base** — this federal-vs-FICA base distinction is the highest-bug-risk 401k interaction and gets a dedicated golden case (see D-04).
  - **Rounding:** `Decimal` everywhere, **ROUND_HALF_UP** (round half away from zero) — the pinned payroll convention (WR-06). Banker's rounding is explicitly NOT used. Phase 3 must preserve this; rounding mode is correctness-relevant for the Pub 15-T port.
    - **Rounding granularity + step locations MUST match the IRS worked examples, or the penny test fails on rounding not logic (review hardening):** ROUND_HALF_UP pins the *direction* but NOT the *granularity* (cents vs whole-dollar) or the *step locations*. Worksheet 1A has specific rounding points, and the employer percentage method permits **rounding withholding to the whole dollar**. If the layer-A IRS-example fixtures round to dollars while the engine carries cents, or the two round at different worksheet steps, the golden test fails for a reason that is NOT a bug — the worst failure mode because it masquerades as one. **The rounding convention, granularity, and step locations must be transcribed from the SAME live 2026 PDF as the brackets (see the research-pass note in `<specifics>`), and the engine must round where and how the worked examples do.**

### Cross-phase risk created by D-03 — the silent OT under-pay hole (its own focused insertion, NOT Phase 3, NOT Phase 5)
- **D-05 [cross-phase, NOT a Phase 3 deliverable] [informational — deferred to Phase 3.1, intentionally not covered by any Phase 3 plan; tracked in `<deferred>` + `.planning/backlog.md`]:** Explicit-OT-only (D-03) is the correct *calc* rule, but it opens a **silent under-payment** path: a weekly employee who writes "45 hours" with no OT field gets 45 straight-time hours and **loses the OT premium**. Under-paying is worse than over-paying in a system whose whole pitch is *never wrong on a money-moving number*, so this must be caught — but **upstream in validation**, not in the calc (the calc must stay workweek-agnostic per D-03).
  - **Timing — its OWN small focused insertion, landing BEFORE this slips:** do NOT bundle it into Phase 3's penny-tax work (keep Phase 3 pure for the hard part), and do NOT park it in Phase 5. There is no technical reason it waits for Phase 5 — the rule just emits a `ValidationIssue` into the **clarification gate already built and tested in Phase 2**, so it can land the moment there's a clean hour. Deferred money-guards are exactly what slips or gets under-specified when a later phase's context loads; the fix is small and additive to already-tested code, so it earns an early, dedicated slot (suggest a decimal insertion, e.g. Phase 3.1, or a quick task — sequencing is the planner/manager's call, but **before Phase 5**).
  - **The rule is per-WORKWEEK, NOT a flat ">40" (the part that's easy to get wrong):** FLSA overtime is defined per workweek, and only **weekly and biweekly** periods map cleanly onto whole workweeks. The rule is: **flag when `hours_regular` exceeds 40 × (whole workweeks in the period) with no `hours_overtime` field → emit a `ValidationIssue` that gates the run to clarification.**
    - **Weekly (52 → 1 workweek):** `hours_regular > 40`, no OT → clarify.
    - **Biweekly (26 → 2 workweeks):** `hours_regular > 80`, no OT → clarify. (>80 *guarantees* at least one week passed 40, so OT must exist even though the period total can't tell you the amount — which is precisely what the clarification asks.)
    - **Semi-monthly (24) / Monthly (12):** period boundaries cut across workweeks, so the period total genuinely **cannot** reveal whether OT happened → **nothing to validate**; this is a **documented limitation**, not a flag. (This is the ONLY place the "client must state OT explicitly" README line is correct — for the slice that's genuinely undetectable, never as a blanket substitute for catching the detectable slice.)
  - **Convenient alignment:** the detectable frequencies (52, 26) are exactly the two the seed already covers — so the rule is testable against seeded employees immediately.
  - **It's a demo beat, not just a hole-plug:** weekly "Bob worked 45 hours" with no OT field → "is that 40 regular + 5 overtime, or 45 straight?" puts the *never-wrong-on-money* thesis on camera (catching a money-affecting ambiguity instead of silently under-paying) — so it earns its place rather than reading as cleanup.

### Area 4 — Test taxonomy & coverage
- **D-04:** The golden-value suite hits the **full matrix + edge cases** bar (CLAUDE.md: the Pub 15-T engine MUST be the most-tested unit in the repo):
  - **The 6 Worksheet 1A schedules** — 3 filing statuses (`single`, `married_jointly`, `married_separately`) × both Step-2 branches (standard + checkbox) — each asserted **to the penny**.
  - **Targeted edge cases:** the **SS wage-base straddle** (YTD `ytd_ss_wages` near $184,500 so only part of gross is SS-taxable); **401k-reduces-federal-but-not-FICA** (the federal base shrinks, the FICA base does not); a **multi-bracket high earner** (crosses ≥2 Pub 15-T brackets); a **below-threshold zero-withholding** case (low wage → $0 federal); **hourly-with-explicit-OT** gross; **salaried-with-leave** gross.
  - **Step-3/Step-4 W-4 paths (review hardening — the engine USES these, so they MUST be tested):** FOUND-06 seeds assumed `step_3_dependents` / `step_4a_other_income` / `step_4b_deductions` values, so the worksheet consumes them every run — an untested path the engine exercises is exactly where a bug hides. Add: a **partial Step-3 dependent-credit** case (credit reduces withholding by a known amount); a **credit-exceeds-tentative-withholding** case (proves the result **floors at $0, never goes negative**); a **Step-4a addition** case (other income raises the annualized wage); a **Step-4b deduction** case (deductions lower it).
  - **Multiple pay frequencies (review hardening — a SEPARATE error surface from bracket math):** annualization (× `pay_periods_per_year`, withhold, ÷ back) is its own bug surface; if every golden case is weekly, a biweekly/semi-monthly annualization bug passes clean. Put **at least two distinct frequencies** in the penny matrix. **Seed nuance (from `app/db/seed.py`):** the seeded employees cover only **52 (weekly)** and **26 (biweekly)** — so layer-B seeded fixtures naturally hit those two; covering **24 (semi-monthly)** and **12 (monthly)** in the matrix requires **synthetic Employee fixtures** (constructed in the test, not seeded). At minimum 52 + 26 from the seed; ideally one of 24/12 synthetic too.
  - **Negative / disclaimer assertions:** OBBBA provisions are NOT applied; the Additional Medicare 0.9% over $200k YTD is NOT modeled — asserted (e.g. a $200k+ YTD case shows Medicare still flat 1.45%, no surtax) so the disclaimer is backed by a test, not just prose.

### Claude's Discretion
- Exact file path / module name for the tax-constants module (`app/pipeline/tax_tables_2026.py`, `app/tax/`, etc.) and its internal data structure for year-keying — D-02 fixes the scope (all constants, one dated header, additive year extension) and the migration constraint; the layout is the planner's call.
- Whether the Pub 15-T engine is a new standalone module (e.g. `app/pipeline/federal_withholding.py`) imported by `calculate.py`, or functions inside `calculate.py` — CLAUDE.md/research recommend an **isolated, pure-function module keyed by tax_year** (highest-bug-risk unit), which biases toward a separate module, but the exact split is the planner's call.
- Exact count of golden fixtures beyond the required matrix + named edge cases, and the fixture file format (inline Python table vs JSON), provided every D-04 case is covered.
- How the "pre-federal" label retirement is handled in code (`PRE_FEDERAL_NET_LABEL` constant removal/repurposing in `calculate.py` and the README stub update) — mechanical, planner's discretion.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` §Payroll Calculation — CALC-01 through CALC-08 (full text + the CALC-04 wage-base/Additional-Medicare detail, the CALC-06 dated-module + golden-test requirement, the CALC-08 "backstop not oracle" framing). Also §v2 (CALC-V2-01 state withholding, CALC-V2-02 YTD ledger — explicitly deferred) and §Out of Scope (OBBBA).
- `.planning/ROADMAP.md` §Phase 3 — goal + the 5 success criteria (these pin the OT-threshold/leave-exclusion, salary-proration-plus-leave, 401k-federal-not-FICA-base, the 6-schedule federal method, and the golden-test + reconciliation-backstop requirements).
- `.planning/PROJECT.md` — Key Decisions table (tax basis = 2026 Pub 15-T standard method, OBBBA disclaimed; the reconciliation check as runtime backstop); Out of Scope (state withholding, OBBBA, Additional Medicare).
- `./CLAUDE.md` §6 (IRS Pub 15-T — the highest-bug-risk unit) + §5 (FICA constants) + the Confidence Summary flags — **the 2026 numbers MUST be transcribed from the live IRS PDF, never from memory; the golden suite is the most-tested unit; ROUND_HALF_UP**. Also the **uv** tooling rule (`uv run pytest -q`, never pip).

### Authoritative external sources (CALC-05/06 — the numbers MUST be transcribed from these, not from memory)
- IRS Pub 15-T 2026 — `https://www.irs.gov/pub/irs-pdf/p15t.pdf` (2026 edition). Source-of-record for: Worksheet 1A percentage-method **bracket tables**, the per-status **Step-1 standard amounts**, the standard vs Step-2-checkbox schedules, AND the **worked examples** that are the golden oracle (D-01). ⚠ 2026 edition incorporates OBBBA changes — transcribe the standard-method rows only; any 2026 number from training data is stale (STATE.md blocker, LOW confidence until transcribed).
- IRS Pub 15-T landing — `https://www.irs.gov/publications/p15t` (HTML companion to the PDF).
- SSA Contribution & Benefit Base — `https://www.ssa.gov/oact/cola/cbb.html` (2026 SS wage base **$184,500**; employee SS max $11,439). ⚠ cbb.html returns 403 to non-browser fetch — cite in the module header, do NOT scrape at runtime. Already corroborated and used in the thin calc.
- IRS Topic 751 — `https://www.irs.gov/taxtopics/tc751` (FICA rates: SS 6.2%, Medicare 1.45%, Additional Medicare 0.9% thresholds).

### Reference implementations (mine for STRUCTURE only — NOT a 2026 dependency or oracle)
- `python-taxes` (PyPI 0.7.0, MIT) — implements the §1 percentage method in Pydantic for **2023–2025 only**. Use its structure/worksheet shape as a method cross-check against an older year; it CANNOT produce 2026 ground truth (D-01).
- `IRS-Public/tax-withholding-estimator` (GitHub, official, Feb 2026) — authoritative model of HOW the IRS computes withholding; heavy/disclaimer-laden, use as a correctness oracle for the method, not a dependency.

### Phase 1/2 artifacts this phase builds on
- `app/pipeline/calculate.py` — the thin calc being deepened (the `_money` ROUND_HALF_UP helper, `_resolved_hours`, the gross/FICA logic, the `PRE_FEDERAL_NET_LABEL` to retire, the inline FICA constants to migrate per D-02, the `contribution_401k_override` current-run-only param).
- `app/models/roster.py` — `Employee` ALREADY carries every Pub 15-T input: `filing_status` (3 Literal values), `step_2_checkbox`, `step_3_dependents`/`step_4a_other_income`/`step_4b_deductions` (Decimal dollar amounts, `ge=0`), `ytd_ss_wages`, `pay_periods_per_year` (12/24/26/52), `retirement_contribution_pct`. **No Employee contract change is needed** for federal withholding.
- `app/models/contracts.py` — `PaystubLineItem` ALREADY has `federal_withholding: Decimal` and `state_withholding: Decimal | None` (`extra="forbid"`). **No PaystubLineItem contract change is needed** — Phase 3 fills `federal_withholding` with a real number and `net_pay` becomes real net.
- `tests/test_calculate.py` — the existing 401k-override golden tests (must stay green; new golden suite extends, not replaces).
- `app/db/seed.py` — seeded employees spanning mixed hourly/salary, filing statuses, Step-2 flags, and static YTD SS wages — the layer-B golden fixtures (D-01) ride these real seeded rows.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`calculate.py` is the single deepening target** — a PURE function (typed values in, `PaystubLineItem` out, no DB/conn). The `_money()` ROUND_HALF_UP helper and `_resolved_hours()` coalescer are reused as-is; the gross/FICA bodies are extended (salary leave pay, the migrated constants) and the `federal_withholding = Decimal("0")` line is replaced by the real Pub 15-T call.
- **`Employee` and `PaystubLineItem` need NO changes** — every W-4 input and the `federal_withholding` output field already exist (Phase 1 FOUND-06 deliberately front-loaded the full calc-input set). This phase is calc logic + constants + tests, not contract work.
- **Seeded employees** already span the filing statuses / Step-2 flags / YTD straddle inputs the golden suite needs for its layer-B fixtures.

### Established Patterns
- **Pure-function judgment/calc stages** (D-14) — data in, data out, the eval imports and scores the SAME function. Phase 3 keeps `calculate` (and any new federal-withholding function) a pure importable unit so Phase 4's eval and the golden tests both ride it.
- **`Decimal` everywhere + ROUND_HALF_UP** (D-05 / WR-06) — never float; rounding mode is pinned and correctness-relevant for the Pub 15-T port.
- **Two-factor env-gated live tests** for anything needing network — irrelevant here (the calc and golden tests are fully offline/deterministic, which is exactly why Phase 3 is the safe slack-absorber).
- **`uv run pytest -q`** for the suite (CLAUDE.md tooling rule — never pip/venv).

### Integration Points
- New tax-constants module (D-02) imported by `calculate.py`; an isolated Pub 15-T federal-withholding pure function (planner's discretion on standalone module vs in-file) called from `calculate.py` where `federal_withholding = Decimal("0")` is today.
- The **reconciliation check (CALC-08)** ties net + taxes + deductions to the run total — where it lives (in `calculate` per-line, or a run-level check in the orchestrator/repo) is a planner call; the existing `payroll_runs.reconciliation` JSONB column (D-A3-05, added Phase 2) is its persistence home if it's a run-level check.
- The **"pre-federal" retirement** touches `calculate.py` (`PRE_FEDERAL_NET_LABEL`) and the Phase 2 README stub disclaimer (D-A6-01) — net is now real.

</code_context>

<specifics>
## Specific Ideas

- The golden oracle's independence is the whole point: **transcribe the IRS PDF's own worked Worksheet 1A examples verbatim** as fixtures (layer A), so a transcription bug in YOUR bracket tables can't hide behind a self-derived oracle. Cross-check the seeded-employee fixtures (layer B) against a **separate online payroll calculator**.
- Back the disclaimers with tests, not just README prose: a $200k+ YTD case asserting Medicare stays flat 1.45% (no 0.9% surtax) makes "Additional Medicare not modeled" a *verified* claim.
- "Net is pre-federal" must be **retired everywhere** it appears once real federal lands — the label constant in `calculate.py` and the README stub note from Phase 2 (D-A6-01).

### Research-pass note (the single transcription pass that feeds the oracle — MANDATORY before planning the golden suite)
The researcher's transcription pass against the **live 2026 Pub 15-T PDF** (`irs.gov/pub/irs-pdf/p15t.pdf`) must pull, in ONE pass, all four things that feed correctness — not just the brackets (STATE.md blocker: any 2026 number from memory is stale):
1. **The Worksheet 1A bracket tables + per-status Step-1 standard amounts** (the constants for D-02).
2. **The rounding convention, granularity (cents vs whole-dollar), and step locations** (so the golden suite's penny comparison fails only on real logic bugs — see D-03 rounding bullet).
3. **An inventory of which worked examples actually exist in the 2026 PDF** (filing statuses / Step-2 branch / bracket cells they cover) — this tells the planner exactly how much of the D-04 matrix layer A reaches and which cells fall to layer B's two-calculator agreement (D-01).
4. **Confirmation of ≥2 online calculators that explicitly implement the Pub 15-T percentage method** for the layer-B oracle (D-01) — NOT generic paycheck estimators.

</specifics>

<deferred>
## Deferred Ideas

- **State withholding** (flat-rate or per-state line) → **v2 (CALC-V2-01)**. The `state_withholding` column stays nullable; Phase 3 always writes `None`.
- **Per-employee YTD tax ledger / running YTD tracking** → **v2 (CALC-V2-02)**. Phase 3 uses the static seeded `ytd_ss_wages` only (enough for the SS-cap straddle golden case).
- **OBBBA provisions** (qualified-tips/overtime above-the-line deductions, the expanded 15-line W-4 Step-4(b) worksheet) → **never (out of scope, disclaimed)**. Standard percentage method only.
- **Additional Medicare 0.9%** over $200k YTD → **not modeled (disclaimed)**; only asserted-as-absent by a golden negative case.
- **The eval that scores these calc functions** → **Phase 4**. Phase 3 only makes the numbers correct and golden-tested; scoring/charting is later.
- **Paystub PDFs + confirmation email rendering the real net** → **Phase 5**. Phase 3 produces the correct `PaystubLineItem`; rendering is later.
- **Over-40-no-OT validation rule (D-05)** → its **OWN small focused insertion BEFORE Phase 5** (suggest Phase 3.1 or a quick task — NOT bundled into Phase 3's calc, NOT parked in Phase 5). Per-workweek rule (>40×whole-workweeks, no OT → clarify) for the detectable frequencies (52/26) + a documented limitation for 24/12. Emits a `ValidationIssue` into the Phase 2 clarification gate. **Also captured in `.planning/backlog.md`.** It is NOT a Phase 3 deliverable, but it is the direct safety consequence of D-03, so the planner/manager must schedule it early.

### Reviewed Todos (not folded)
None — STATE.md "Pending Todos" is empty; no todos matched this phase.

</deferred>

---

*Phase: 3-Harden the Calc*
*Context gathered: 2026-06-22*
