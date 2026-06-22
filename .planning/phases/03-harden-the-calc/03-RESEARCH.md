# Phase 3: Harden the Calc — Research

**Researched:** 2026-06-22
**Domain:** IRS Pub 15-T 2026 federal withholding (Worksheet 1A), FICA, gross/net payroll calc hardening
**Confidence:** HIGH (live PDF transcription), MEDIUM (oracle tools)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01 — Golden oracle sourcing:**
Federal-withholding golden values come from the IRS Pub 15-T's own worked examples as the primary independent oracle (layer A), backed by an independent online payroll calculator spot-check (layer B). The oracle must be independent of the transcribed `tax_tables_2026` module — if golden values derive from the same table, a transcription bug makes code AND test wrong in the same direction. Two-layer fixture structure: layer A uses IRS-example verbatim inputs/outputs; layer B uses seeded-employee fixtures cross-checked against an independent percentage-method calculator. For any matrix cell layer A doesn't reach, TWO independent percentage-method calculators must agree. `python-taxes` is NOT a 2026 oracle (ships 2023–2025 only).

**D-02 — Tax-constants module:**
ONE year-keyed module holds ALL year-specific tax constants: Pub 15-T 2026 bracket tables + per-status Step-1 standard amounts AND the FICA constants (SS rate / $184,500 wage base, Medicare 1.45% rate). The inline `_SS_RATE`, `_SS_WAGE_BASE`, `_MEDICARE_RATE` constants in `calculate.py` are MIGRATED out. Module header MUST carry source URLs (irs.gov/pub/irs-pdf/p15t.pdf 2026 edition; ssa.gov/oact/cola/cbb.html) and retrieval date. Year-keying: additive, not rewrite (adding 2027 doesn't edit 2026 constants).

**D-03 — OT calc edge cases:**
Overtime is paid from an EXPLICIT `hours_overtime` field only. The calc trusts the submitted split and NEVER auto-derives OT by splitting `hours_regular` over 40. Leave hours (vacation/sick/holiday) are paid at straight time only and never enter OT. ROUND_HALF_UP is pinned for ALL monetary values. Rounding granularity and step locations MUST match the IRS worked examples (see Mandatory Deliverable 2 below).

**D-04 — Test taxonomy and coverage:**
The golden suite covers the full matrix: 6 Worksheet 1A schedules (3 filing statuses × 2 Step-2 branches), each asserted to the penny. Plus targeted edge cases: SS wage-base straddle; 401k-reduces-federal-not-FICA; multi-bracket high earner; below-threshold $0 withholding; partial Step-3 credit; credit-exceeds-tentative (floors at $0); Step-4a addition; Step-4b deduction; hourly-with-OT gross; salaried-with-leave gross. At least two distinct pay frequencies in the matrix.

**D-05 [cross-phase, NOT Phase 3]:**
Over-40-no-OT validation rule (weekly/biweekly frequencies) emits a ValidationIssue into the clarification gate — scheduled as a focused insertion BEFORE Phase 5 (suggest Phase 3.1), not bundled into Phase 3.

### Claude's Discretion
- Exact file path/module name for the tax-constants module (e.g., `app/pipeline/tax_tables_2026.py`) and its year-keying data structure.
- Whether the Pub 15-T engine is a standalone module (`app/pipeline/federal_withholding.py`) imported by `calculate.py` or functions inside `calculate.py` — research recommends isolated pure-function module (CLAUDE.md §6 bias), exact split is planner's call.
- Exact count of golden fixtures beyond the required matrix + named edge cases, and fixture file format (inline Python table vs JSON).
- How the "pre-federal" label retirement is handled (`PRE_FEDERAL_NET_LABEL` constant removal/repurposing in `calculate.py` and README stub update).

### Deferred Ideas (OUT OF SCOPE)
- State withholding (CALC-V2-01) — `state_withholding` stays nullable.
- Per-employee YTD tax ledger (CALC-V2-02) — static seeded `ytd_ss_wages` only in Phase 3.
- OBBBA provisions (qualified-tips/overtime above-the-line deductions, expanded 15-line W-4 Step-4(b)) — standard method only, disclaimed in README.
- Additional Medicare 0.9% over $200k YTD — not modeled; asserted-as-absent by a golden negative case.
- Eval (Phase 4), dashboard/PDFs (Phase 5).
- D-05 OT-under-pay guard — its own focused Phase 3.1 insertion.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CALC-01 | Gross pay: hourly × rate with FLSA OT at 1.5× for hours worked over 40 (paid-leave excluded), using explicit `hours_overtime` field (D-03) | Deliverable 4 + D-03 lock; existing `_resolved_hours` reusable; salary-leave pay addition documented below |
| CALC-02 | Salary gross = annual ÷ pay_periods PLUS added vacation/sick/holiday pay | Section "Gross Calc Engine" below; current `calculate.py` omits leave for salaried; Phase 3 adds it |
| CALC-03 | 401k = percent of gross, reduces federal taxable base NOT FICA base | Section "401k Interaction" below; existing `pretax_401k` logic correct; federal base = `gross - pretax_401k`; FICA base = `gross` |
| CALC-04 | FICA: SS 6.2% to $184,500 wage base (honor static YTD); Medicare 1.45% no cap | Section "FICA Constants" below; existing logic correct but constants migrate to D-02 module |
| CALC-05 | Federal withholding via real IRS Pub 15-T 2026 Worksheet 1A (all 3 filing statuses + Step-2-checkbox branch), standard method only, OBBBA disclaimed | Mandatory Deliverables 1–4 below — ALL numbers transcribed from live PDF |
| CALC-06 | Tax constants in dated year-keyed module (source URL + date in header); golden-value test suite asserts to penny with `Decimal` | D-02 module design; Deliverables 1–3 are the constants + oracle inventory |
| CALC-07 | Net = gross − pre-tax − FICA − federal; retire "pre-federal" label | Section "Net Pay Formula"; `PRE_FEDERAL_NET_LABEL` constant retirement documented |
| CALC-08 | Reconciliation check: net + taxes + deductions ties to run total — arithmetic backstop only, NOT the correctness oracle | Section "Reconciliation Backstop"; location is planner's call (per-line in `calculate` or run-level in orchestrator) |
</phase_requirements>

---

## Summary

Phase 3 deepens the existing thin pure calc in `app/pipeline/calculate.py` from "gross + FICA + fake zero federal" into fully correct payroll math: real Pub 15-T 2026 federal withholding, full-fidelity gross (FLSA OT, salary leave pay), 401k reducing federal-not-FICA base, and a real net. All of this is locked behind a golden-value test suite sourced from an oracle that is independent of the code being tested.

The most critical research output is the live transcription of the 2026 IRS Pub 15-T PDF — retrieved 2026-06-22 from `https://www.irs.gov/pub/irs-pdf/p15t.pdf`. The 2026 edition incorporates OBBBA changes (permanent extension of individual tax rates, increased standard deduction, no personal exemptions). Every number in Mandatory Deliverables 1–5 below was extracted directly from that PDF binary using `pdfplumber`.

The 2026 Pub 15-T contains NO worked *Worksheet 1A* examples (Deliverable 3) — the only narrative "Example" is a nonresident-alien Wage Bracket case on page 7. **However, the IRS-published Wage Bracket Method tables (Section 2, pages 13–27) ARE the in-PDF answer key** (Deliverable 5): each wage-bracket cell is the IRS's own percentage-method result, transcribed SEPARATELY from our percentage-method bracket rows, so a transcription typo in our tables cannot hide behind a wage-bracket cell. This restores the D-01 "the oracle is the IRS itself" independence guarantee for every fixture whose adjusted per-period wage falls under the table ceiling (≈$1,925 weekly / $3,875 biweekly / $4,185 semimonthly / $8,395 monthly — all ~$100k annualized). The wage-bracket oracle is the PRIMARY golden-suite oracle; the online percentage-method calculators (Deliverable 4) drop to secondary corroboration behind a manual human-verify checkpoint, used only for over-ceiling high earners (Thomas Bergmann). See Mandatory Deliverable 5 for the full structure, ceilings, the midpoint cross-check rule, and a verbatim sample block.

**Primary recommendation:** Implement the Pub 15-T engine as an isolated pure-function module `app/pipeline/federal_withholding.py` (see Architecture Patterns); migrate all year-specific constants into `app/pipeline/tax_tables_2026.py`; write the golden suite as table-driven pytest parametrize covering the D-04 matrix; use the **in-PDF Wage Bracket Method tables (Deliverable 5) as the primary oracle** for under-ceiling fixtures (evaluate the engine at the interval midpoint, round to whole dollars, assert `==` the published cell), and the online percentage-method calculators (`usapaycheck.org`, `paycheckcity.com/calculator/salary`) as **secondary corroboration behind a human-verify checkpoint** for the few over-ceiling high earners.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Federal withholding computation (Worksheet 1A) | Pure Python function (no tier boundary) | — | Must be importable by both the main pipeline and the eval (D-14); belongs in `app/pipeline/` |
| Tax constant storage | Flat Python module | — | Year-keyed in-memory constants; no DB, no network at runtime |
| FICA computation | Pure Python function | — | Already in `calculate.py`; migrates to same pure module; importable for eval |
| Reconciliation check | Per-line in `calculate()` OR run-level in orchestrator | `payroll_runs.reconciliation` JSONB | Planner's call per D-02 context; arithmetic backstop only |
| OT guard (D-05) | Validation stage (`validate.py`) | — | Emits `ValidationIssue` into existing Phase 2 clarification gate; NOT Phase 3 |

---

## MANDATORY DELIVERABLE 1: Worksheet 1A Bracket Tables (Transcribed from Live 2026 PDF)

**Source:** `https://www.irs.gov/pub/irs-pdf/p15t.pdf` — Publication 15-T (2026), page 12 of 71
**Retrieved:** 2026-06-22 via pdfplumber PDF text extraction
**Confidence:** [VERIFIED: irs.gov/pub/irs-pdf/p15t.pdf, retrieved 2026-06-22]

These are the **Percentage Method Tables for Automated Payroll Systems** (Worksheet 1A tables). All figures are ANNUAL (applied to the Adjusted Annual Wage Amount computed in Step 1). Columns: A = at-least lower bound, B = but-less-than upper bound, C = base withholding amount, D = marginal rate %, E = "of the amount that exceeds" (same as column A, i.e. the excess over).

### 1A.1 STANDARD Withholding Rate Schedules (Step 2 checkbox NOT checked)

Use when: Form W-4 is from 2019 or earlier, OR Form W-4 from 2020+ with Step 2 box NOT checked. Also for Form W-4P (any year).

**Married Filing Jointly — STANDARD:**

| At Least (A) | But Less Than (B) | Base Amount (C) | Plus % (D) | Excess Over (E) |
|-------------|------------------|-----------------|------------|-----------------|
| $0 | $19,300 | $0.00 | 0% | $0 |
| $19,300 | $44,100 | $0.00 | 10% | $19,300 |
| $44,100 | $120,100 | $2,480.00 | 12% | $44,100 |
| $120,100 | $230,700 | $11,600.00 | 22% | $120,100 |
| $230,700 | $422,850 | $35,932.00 | 24% | $230,700 |
| $422,850 | $531,750 | $82,048.00 | 32% | $422,850 |
| $531,750 | $788,000 | $116,896.00 | 35% | $531,750 |
| $788,000 | (no upper bound) | $206,583.50 | 37% | $788,000 |

**Single or Married Filing Separately — STANDARD:**

| At Least (A) | But Less Than (B) | Base Amount (C) | Plus % (D) | Excess Over (E) |
|-------------|------------------|-----------------|------------|-----------------|
| $0 | $7,500 | $0.00 | 0% | $0 |
| $7,500 | $19,900 | $0.00 | 10% | $7,500 |
| $19,900 | $57,900 | $1,240.00 | 12% | $19,900 |
| $57,900 | $113,200 | $5,800.00 | 22% | $57,900 |
| $113,200 | $209,275 | $17,966.00 | 24% | $113,200 |
| $209,275 | $263,725 | $41,024.00 | 32% | $209,275 |
| $263,725 | $648,100 | $58,448.00 | 35% | $263,725 |
| $648,100 | (no upper bound) | $192,979.25 | 37% | $648,100 |

**Head of Household — STANDARD:**
*(Note: out of scope for this project — seed has no HoH employees. Listed for completeness.)*

| At Least (A) | But Less Than (B) | Base Amount (C) | Plus % (D) | Excess Over (E) |
|-------------|------------------|-----------------|------------|-----------------|
| $0 | $15,550 | $0.00 | 0% | $0 |
| $15,550 | $33,250 | $0.00 | 10% | $15,550 |
| $33,250 | $83,000 | $1,770.00 | 12% | $33,250 |
| $83,000 | $121,250 | $7,740.00 | 22% | $83,000 |
| $121,250 | $217,300 | $16,155.00 | 24% | $121,250 |
| $217,300 | $271,750 | $39,207.00 | 32% | $217,300 |
| $271,750 | $656,150 | $56,631.00 | 35% | $271,750 |
| $656,150 | (no upper bound) | $191,171.00 | 37% | $656,150 |

---

### 1A.2 Step 2 Checkbox Withholding Rate Schedules (Step 2 checkbox IS checked)

Use when: Form W-4 from 2020+ AND the box in Step 2 IS checked.

**Married Filing Jointly — STEP 2 CHECKBOX:**

| At Least (A) | But Less Than (B) | Base Amount (C) | Plus % (D) | Excess Over (E) |
|-------------|------------------|-----------------|------------|-----------------|
| $0 | $16,100 | $0.00 | 0% | $0 |
| $16,100 | $28,500 | $0.00 | 10% | $16,100 |
| $28,500 | $66,500 | $1,240.00 | 12% | $28,500 |
| $66,500 | $121,800 | $5,800.00 | 22% | $66,500 |
| $121,800 | $217,875 | $17,966.00 | 24% | $121,800 |
| $217,875 | $272,325 | $41,024.00 | 32% | $217,875 |
| $272,325 | $400,450 | $58,448.00 | 35% | $272,325 |
| $400,450 | (no upper bound) | $103,291.75 | 37% | $400,450 |

**Single or Married Filing Separately — STEP 2 CHECKBOX:**

| At Least (A) | But Less Than (B) | Base Amount (C) | Plus % (D) | Excess Over (E) |
|-------------|------------------|-----------------|------------|-----------------|
| $0 | $8,050 | $0.00 | 0% | $0 |
| $8,050 | $14,250 | $0.00 | 10% | $8,050 |
| $14,250 | $33,250 | $620.00 | 12% | $14,250 |
| $33,250 | $60,900 | $2,900.00 | 22% | $33,250 |
| $60,900 | $108,938 | $8,983.00 | 24% | $60,900 |
| $108,938 | $136,163 | $20,512.00 | 32% | $108,938 |
| $136,163 | $328,350 | $29,224.00 | 35% | $136,163 |
| $328,350 | (no upper bound) | $96,489.63 | 37% | $328,350 |

**Head of Household — STEP 2 CHECKBOX:**
*(Out of scope for this project. Listed for completeness.)*

| At Least (A) | But Less Than (B) | Base Amount (C) | Plus % (D) | Excess Over (E) |
|-------------|------------------|-----------------|------------|-----------------|
| $0 | $12,075 | $0.00 | 0% | $0 |
| $12,075 | $20,925 | $0.00 | 10% | $12,075 |
| $20,925 | $45,800 | $885.00 | 12% | $20,925 |
| $45,800 | $64,925 | $3,870.00 | 22% | $45,800 |
| $64,925 | $112,950 | $8,077.50 | 24% | $64,925 |
| $112,950 | $140,175 | $19,603.50 | 32% | $112,950 |
| $140,175 | $332,375 | $28,315.50 | 35% | $140,175 |
| $332,375 | (no upper bound) | $95,585.50 | 37% | $332,375 |

---

### 1A.3 Step 1 Standard Amounts (Worksheet 1A, Line 1g)

[VERIFIED: irs.gov/pub/irs-pdf/p15t.pdf page 10, retrieved 2026-06-22]

These amounts are used at **Worksheet 1A Line 1g**: entered when Step 2 box is NOT checked. When Step 2 IS checked, line 1g = $0 (entered as `-0-`).

| Filing Status | Standard Amount (Line 1g when Step 2 NOT checked) |
|---------------|--------------------------------------------------|
| Married Filing Jointly | **$12,900** |
| Single or Married Filing Separately | **$8,600** |
| Head of Household | **$8,600** |

Exact text from PDF page 10: *"If the box in Step 2 of Form W-4 is checked, enter -0-. If the box is not checked, enter $12,900 if the taxpayer is married filing jointly or $8,600 otherwise."*

---

## MANDATORY DELIVERABLE 2: Rounding Convention, Granularity, and Step Locations

**Source:** `https://www.irs.gov/pub/irs-pdf/p15t.pdf` — page 9 of 71 (Rounding section, just before Section 1)
**Retrieved:** 2026-06-22
**Confidence:** [VERIFIED: irs.gov/pub/irs-pdf/p15t.pdf page 9, retrieved 2026-06-22]

### Official Rounding Text (Verbatim from PDF Page 9)

> "To figure the income tax to withhold, you may reduce the last digit of the wages to zero, or figure the wages to the nearest dollar. You may also round the tax for the pay period to the nearest dollar. If rounding is used, it must be used consistently. Withheld tax amounts should be rounded to the nearest whole dollar by dropping amounts under 50 cents and increasing amounts from 50 to 99 cents to the next dollar. For example, $2.30 becomes $2 and $2.50 becomes $3."

### Critical Analysis for Implementation

**What this means for the engine:**

1. **Rounding is OPTIONAL, not mandatory.** The employer "may" round — it is a permitted simplification, not a requirement. The IRS does not mandate whole-dollar rounding for the employer percentage method.

2. **Two permitted rounding approaches:**
   - Round wages to the nearest dollar (or drop the last digit to zero) before the bracket lookup
   - Round the final per-period withholding to the nearest dollar

3. **The IRS uses conventional half-up rounding (nearest dollar):** "$2.30 becomes $2 and $2.50 becomes $3." This is ROUND_HALF_UP applied to the dollar boundary — consistent with the project's existing ROUND_HALF_UP convention.

4. **The golden test precision decision:** Because rounding is OPTIONAL in the IRS method, the engine has two valid choices:
   - **Option A (carry full cents):** Do NOT round mid-calculation; only apply ROUND_HALF_UP to cents (the existing `_money()` helper) at each money output step. The per-period withholding will be in cents. Golden fixtures must match to the cent.
   - **Option B (round to whole dollars):** Apply ROUND_HALF_UP to the whole dollar at the final per-period withholding step (line 4b). Golden fixtures are whole-dollar integers.

5. **Recommended approach for this project:** Use **Option A (carry cents, round to cents via existing `_money()`)** — this is the most defensible implementation because (a) it is IRS-compliant (cents are legal), (b) it avoids introducing a rounding boundary that layer-B calculators may or may not match, and (c) the `_money()` helper already handles it. If layer-B calculator cross-checks produce whole-dollar figures, allow a $0.50 tolerance or round to whole dollars in the golden fixture comparison. Document the choice in the module header.

6. **No worksheet step requires rounding mid-calculation.** Worksheet 1A is arithmetic-only at each step; there is no instruction like "round line 2g to the nearest dollar before proceeding." The only rounding permission is for the wages input (line 1a) and the final output (line 4b).

### Step Locations Where Rounding May Occur

| Step | Description | Rounding Permitted? | Notes |
|------|-------------|---------------------|-------|
| Line 1a | Taxable wages input | YES (round wages to nearest $1) | Optional |
| Lines 1c–1i | Arithmetic steps | NO explicit instruction | Carry full precision |
| Line 2g | Annual tentative withholding | NO explicit instruction | Carry full precision |
| Line 2h | Per-period tentative withholding (÷ pay periods) | NO explicit instruction | Carry full precision; division may produce cents |
| Line 3c | After Step-3 credit subtraction | NO explicit instruction | Carry full precision |
| Line 4b | FINAL per-period withholding to withhold | YES (round to nearest $1) | Optional; this is the output |

**Bottom line for the planner:** The engine should apply `_money()` (ROUND_HALF_UP to cents) at each intermediate step that produces a dollar amount, and apply `_money()` to the final per-period result. Do NOT round to whole dollars unless the project explicitly decides to do so; document the decision.

---

## MANDATORY DELIVERABLE 3: Worked Example Inventory in the 2026 Pub 15-T PDF

**Source:** `https://www.irs.gov/pub/irs-pdf/p15t.pdf` — all 71 pages searched
**Retrieved:** 2026-06-22 via full PDF text extraction
**Confidence:** [VERIFIED: irs.gov/pub/irs-pdf/p15t.pdf, retrieved 2026-06-22]

### CRITICAL FINDING: NO Worksheet 1A Worked Examples Exist in the 2026 PDF

After searching all 71 pages for the words "example", "rounding", and "figure", the 2026 Pub 15-T contains exactly **ONE** worked example, and it is for a **nonresident alien employee** using the Wage Bracket Method (Worksheet 3 / Section 3), NOT Worksheet 1A.

**The nonresident alien example (PDF page 7) — NOT usable for Worksheet 1A layer-A oracle:**

> "An employer pays wages of $300 for a weekly payroll period to a married nonresident alien employee... The employer would withhold $31 in federal income tax from the weekly wages of the nonresident alien employee."

This example uses a different worksheet (Section 3 Wage Bracket tables for 2019-or-earlier Forms W-4 with a nonresident alien adjustment). It is categorically NOT a Worksheet 1A example and cannot serve as a layer-A oracle for the golden suite.

The Section 6 (Alternative Methods) also contains an example for Indian gaming distributions — irrelevant.

**Section 4 (Manual Payroll Percentage Method for 2020+ W-4) and Section 5 (Manual Payroll Percentage Method for 2019 W-4)** also contain no worked examples.

### Oracle Strategy Revision (D-01 Adaptation)

Since the 2026 Pub 15-T ships zero Worksheet 1A worked examples, the two-layer oracle structure from D-01 must be adapted:

**Revised Layer A (Hand-computed, verified by two independent layer-B calculators):**
Hand-compute each golden fixture by manually tracing Worksheet 1A steps using the transcribed bracket tables and Step-1 standard amounts from Deliverable 1. These hand-computed values ARE the layer-A fixtures. Their independence from the code comes from being computed by the researcher independently of the `tax_tables_2026.py` module the code will use — a transcription bug in the module does NOT corrupt the hand computation.

**Layer B (Independent online calculator cross-check):**
Hand-computed layer-A fixture values are cross-checked against the layer-B calculators identified in Deliverable 4. For the golden suite to trust a fixture, the hand computation AND both layer-B calculators must agree (subject to the rounding tolerance noted in Deliverable 2).

**Independence guarantee:** The hand computation uses the RESEARCH.md bracket table transcription (not the code module); the two calculators use their own independent implementations. A transcription bug would show up as a disagreement between at least one source, so the cross-check provides genuine independence.

---

## MANDATORY DELIVERABLE 4: Layer-B Oracle Tool Verification

**Source:** Web research 2026-06-22; tool websites accessed directly
**Confidence:** MEDIUM [CITED: usapaycheck.org; paycheckcity.com; verified method claims]

### Oracle Tool 1 (Primary): usapaycheck.org Biweekly Paycheck Calculator

**URL:** `https://usapaycheck.org/biweekly-paycheck-calculator/`
**Method:** Explicitly claims to use "the official IRS Publication 15-T Percentage Method withholding tables — updated for OBBBA 2026 tax law"
**W-4 Inputs accepted:** Filing status, Step 2 checkbox (explicitly: "W-4 Step 2 Checkbox (Multiple Jobs) Not Checked / Checked"), Step 3 dependent/other credits (annual dollar amount), Step 4(c) extra withholding per paycheck, Step 4(a) other income (per web search confirmation), Step 4(b) deductions
**Step-by-step disclosure:** Yes — provides a 7-step breakdown of the IRS calculation process
**Limitation:** Pay frequency appears to be biweekly-only in the primary interface; also may not support all custom Step-4a/4b values directly — verify on the tool before using
**Suitability:** HIGH for biweekly fixtures; confirm weekly frequency at `https://usapaycheck.org/weekly-paycheck-calculator/` (weekly variant likely exists given the biweekly URL pattern)

### Oracle Tool 2 (Secondary): PaycheckCity Salary / Hourly Calculator

**URL:** `https://www.paycheckcity.com/calculator/salary` (salary); `https://www.paycheckcity.com/calculator/hourly` (hourly)
**Method:** References "IRS Publication 15-T" tables. Accepts W-4 inputs including Step 2 checkbox, Step 3 dependents, Step 4(c) extra withholding. Pay frequency selectable.
**Explicit method disclosure:** References Pub 15-T but does not explicitly state "employer percentage method Worksheet 1A" vs another method. The brackets used (10%/12%/22%/24%/32%/35%/37%) align with the Worksheet 1A tables transcribed in Deliverable 1.
**Disclaimer:** "These calculators should not be relied upon for accuracy, such as to calculate exact taxes, payroll or other financial data." — use as a CORROBORATING source, not a single source of truth.
**Suitability:** MEDIUM — good enough for corroboration when both layer-B tools agree with hand computation

### Oracle Tool 3 (Tertiary/Backup): python-taxes (PyPI 0.7.0, MIT) — 2023–2025 ONLY

**NOT a 2026 oracle.** Use for STRUCTURE verification only:
- Implements IRS Pub 15-T §1 percentage method in Pydantic
- Key function: `employer_withholding()` in the `income` module
- Covers tax years 2023–2025; `CURRENT_TAX_YEAR` = 2024
- Can sanity-check that the calculation STRUCTURE (annualize → lookup → de-annualize → Step-3 subtract → Step-4c add) is implemented correctly by comparing 2024/2025 results to the same inputs run through the engine with 2024/2025 tables

### Oracle Decision Rule

For any golden fixture:
1. Hand-compute the expected value tracing Worksheet 1A steps using Deliverable 1 tables
2. Verify against usapaycheck.org (Tool 1) — biweekly or weekly
3. Corroborate against paycheckcity.com (Tool 2) with same inputs
4. If all three agree (within $0.01–$1.00 per rounding differences): mark as TRUSTED, write as golden fixture
5. If any disagreement: investigate the source before writing a fixture

---


---

## MANDATORY DELIVERABLE 5: Wage Bracket Method Tables (Independent In-PDF Oracle)

**Source:** `https://www.irs.gov/pub/irs-pdf/p15t.pdf` — Section 2, "Wage Bracket Method Tables for Manual Payroll Systems With Forms W-4 From 2020 or Later," pages 13–27 of 71
**Retrieved:** 2026-06-22 via pdfplumber (same PDF binary as Deliverables 1–4)
**Confidence:** [VERIFIED: irs.gov/pub/irs-pdf/p15t.pdf pages 13–27, retrieved 2026-06-22]
**Status:** CONFIRMED — the wage-bracket tables EXIST and are usable as an independent in-PDF oracle for the bulk of this project's wage range.

### Why This Is the "IRS Answer Key" Deliverable 3 Said Didn't Exist

Deliverable 3 correctly found ZERO worked *Worksheet 1A* examples. But the external review is right: the **Wage Bracket Method tables are themselves an IRS-published answer key derived from the percentage method.** The IRS builds each wage-bracket cell by running the percentage method on the wage interval and publishing the result. Because we transcribe the wage-bracket cell **separately** from the percentage-method bracket rows (Deliverable 1), a transcription typo in our percentage tables cannot hide behind a wage-bracket cell — the two are independent transcriptions of the same underlying IRS math. This restores the layer-A "oracle is the IRS itself" independence guarantee (D-01) for every fixture whose adjusted wage falls under the table ceiling.

### Finding 1 — Do the 2026 Wage Bracket tables exist? YES.

Section 2 ("Wage Bracket Method Tables for Manual Payroll Systems With Forms W-4 From 2020 or Later") exists at **pages 13–27**. Page 13 is Worksheet 2 (the adjust-wage worksheet); pages 14–27 are the actual lookup tables. This is the **2020+ Form W-4 vintage** — the SAME vintage the project's employees use (FOUND-06 uses 2020+ W-4 fields). [VERIFIED: page 13]

### Finding 2 — Structure

- **Row granularity:** Fixed-width wage intervals. Width varies by frequency: **weekly = $10-wide** rows (e.g. `$155–$165`), **biweekly = $15–$20-wide**, **semimonthly = $15–$20-wide**, **monthly = $30–$70-wide**, **daily = $5-wide**. Each table opens with a wide `$0–$<first>` row (e.g. weekly `$0–$155 → all $0`). [VERIFIED: pages 14, 17, 20, 23, 26]
- **Lookup key:** the **Adjusted Wage Amount (Worksheet 2 line 1h)** — NOT raw gross. Line 1h already folds in Step-4a (line 1c/1d) and Step-4b (line 1f/1g) per-period adjustments. So Step-4a/4b are handled BEFORE the table lookup; the table itself is keyed purely by adjusted wage. [VERIFIED: page 13 Worksheet 2]
- **Column layout:** filing status × Step-2 branch. Six tentative-withholding columns per row: `MFJ Standard | MFJ Step-2 Checkbox | HoH Standard | HoH Step-2 Checkbox | Single-or-MFS Standard | Single-or-MFS Step-2 Checkbox`. [VERIFIED: page 14 header]
- **Pay frequencies covered:** Weekly (pp.14–16), Biweekly (pp.17–19), Semimonthly (pp.20–22), Monthly (pp.23–25), Daily (pp.26–27). **All four of the project's frequencies (52/26/24/12) are present**, plus Daily. [VERIFIED: page headers]
- **Step-3 dependents:** NOT a table dimension. Step-3 credits are subtracted per-period AFTER the table lookup (Worksheet 2 Step 3, lines 3a–3c) exactly as in Worksheet 1A. The table gives the *tentative* withholding only. [VERIFIED: page 13 Worksheet 2 Step 3]

### Finding 3 — Wage range ceiling (the critic's ~$100k estimate, CONFIRMED)

Page 13 intro, verbatim: *"These Wage Bracket Method tables cover a limited amount of annual wages (generally, less than $100,000). If you can't use the Wage Bracket Method tables because taxable wages exceed the amount from the last bracket of the table (based on filing status and pay period), use the Percentage Method tables in section 4."*

Confirmed last-row ceilings (the highest "But less than" value per frequency):

| Frequency | Last bracket "but less than" | Annualized | Pages |
|-----------|------------------------------|-----------|-------|
| Weekly (52) | **$1,925** | ≈ $100,100 | 14–16 |
| Biweekly (26) | **$3,875** | ≈ $100,750 | 17–19 |
| Semimonthly (24) | **$4,185** | ≈ $100,440 | 20–22 |
| Monthly (12) | **$8,395** | ≈ $100,740 | 23–25 |
| Daily (260) | **$400/day** | ≈ $104,000 | 26–27 |

The tables do **NOT** have a terminal "$X or more" catch-all row — they simply stop at the last interval, and the intro instructs you to switch to the percentage method above it. So the wage-bracket oracle covers any employee with an **adjusted per-period wage under ~$1,925 weekly / $3,875 biweekly / $4,185 semimonthly / $8,395 monthly**. Above that, fall back to the percentage-method hand computation + online layer-B calculators (Deliverable 4). [VERIFIED: pages 13–25]

### Finding 4 — Step-2-checkbox variant and all 3 filing statuses? YES to both.

Every wage-bracket row carries BOTH a Standard and a Step-2-Checkbox column for **all three** filing statuses (Married Filing Jointly, Head of Household, Single or Married Filing Separately). The project only needs MFJ and Single/MFS, but HoH is present too. [VERIFIED: page 14 header — six columns: MFJ Standard, MFJ Checkbox, HoH Standard, HoH Checkbox, Single/MFS Standard, Single/MFS Checkbox]

This DIRECTLY resolves the Seed-Coverage gap: the **MFJ + Step-2-checkbox** schedule (which no seeded employee covers and Deliverable 3 had no IRS example for) now has an IRS-published answer-key column. A synthetic MFJ + Step-2 employee under the ceiling can be verified to the published cell.

### Finding 5 — Construction / midpoint / rounding convention: NO EXPLICIT NOTE IN PDF

A full-PDF search for "midpoint", "mid-point", "middle of", "computed at the", and "derived from the percentage" returned **NO construction note** in the 2026 Pub 15-T. The IRS does not document, inside this publication, the exact midpoint convention it uses to build a wage-bracket cell from the percentage method.

**Established (un-cited, ASSUMED) convention from IRS practice:** historically the IRS computes the wage-bracket cell by applying the percentage method to the **midpoint** of each wage interval and rounding to the whole dollar. This is NOT stated in the 2026 PDF, so treat it as `[ASSUMED]`.

**Tolerance implication for the cross-check assertion:** Because (a) the wage-bracket cell is a whole-dollar figure computed at the interval midpoint, while (b) our percentage-method engine computes at the *exact* per-period adjusted wage carried to cents, the two will NOT match to the penny in general. The correct cross-check is:

> Compute the engine's percentage-method withholding at the **midpoint** of the chosen wage-bracket interval, round to the whole dollar, and assert it **equals the published wage-bracket cell exactly** (whole-dollar `==`). Equivalently, assert the engine's exact-wage result is **within ±$X of the cell** where the tolerance covers the half-interval slope. For the safest, unambiguous fixture: feed the engine the **interval midpoint wage** and assert `round(engine_result) == published_cell` (exact whole-dollar equality). Do NOT assert penny-equality between a cents-carrying engine result and a whole-dollar wage-bracket cell — that fails for a non-bug reason (the Deliverable 2 rounding trap, restated here for the wage-bracket oracle).

Recommended fixture rule: **evaluate the engine at the interval midpoint, round to whole dollars, assert `==` the published cell.** This gives an exact, auditable, IRS-sourced golden assertion with zero tolerance ambiguity.

### Finding 6 — Verbatim sample block (hard-codeable fixture anchor)

**WEEKLY Payroll Period, Single or Married Filing Separately, Standard column (Step-2 unchecked)** — transcribed verbatim from **page 14**. Format: `[at_least, but_less_than] → Single/MFS Standard tentative withholding`.

| At least | But less than | Single/MFS Standard withholding |
|----------|--------------|-------------------------------|
| $625 | $635 | $34 |
| $635 | $645 | $35 |
| $645 | $655 | $36 |
| $655 | $665 | $37 |
| $665 | $675 | $38 |
| $675 | $685 | $40 |
| $685 | $695 | $41 |
| $695 | $705 | $42 |
| $705 | $715 | $43 |
| $715 | $725 | $44 |

[VERIFIED: irs.gov/pub/irs-pdf/p15t.pdf page 14, retrieved 2026-06-22]

**Cross-check worked anchor (ties Deliverable 5 to Deliverable 1):** Take the `$665–$675` interval, midpoint = $670/week, Single/Standard. Run the Deliverable 1 percentage method: annualize `$670 × 52 = $34,840`; subtract line-1g `$8,600` → adjusted annual `$26,240`; Single/Standard bracket `$19,900–$57,900` → base `$1,240` + 12% × (`$26,240 − $19,900` = `$6,340`) = `$1,240 + $760.80 = $2,000.80` annual; ÷ 52 = `$38.48`/week; `round($38.48) = $38`. **Published wage-bracket cell = $38. MATCH.** This demonstrates the oracle works and confirms the Deliverable 1 Single/MFS Standard transcription is internally consistent with the independently-transcribed Deliverable 5 cell.

### Finding 7 — Step-1g standard amounts RE-CONFIRMED ($12,900 / $8,600) — DO NOT "FIX"

[VERIFIED: irs.gov/pub/irs-pdf/p15t.pdf page 10, line 1g, retrieved 2026-06-22]

Worksheet 1A line 1g (page 10) verbatim: *"If the box in Step 2 of Form W-4 is checked, enter -0-. If the box is not checked, enter **$12,900** if the taxpayer is married filing jointly or **$8,600** otherwise."* This is the Worksheet 1A withholding-proxy amount and is **CORRECT as-is for 2026**.

⚠️ **TRAP — do NOT "fix" these to the 2026 standard-deduction figures.** The 2026 *standard deduction* is $32,200 (MFJ) / $16,100 (Single) — those are the figures a taxpayer uses on their 1040, NOT the Worksheet 1A line-1g proxy. The line-1g amounts ($12,900 / $8,600) are deliberately different (they are roughly the pre-TCJA standard deduction baked into the withholding tables). Replacing $12,900/$8,600 with $32,200/$16,100 would over-deduct the annualized wage and systematically UNDER-withhold every employee. The $12,900/$8,600 values are verified directly from the live 2026 PDF and must be transcribed exactly. (See Pitfall 2.)

### Deliverable 5 Impact on the Golden Suite (planner guidance)

- **Primary oracle for under-ceiling fixtures (the bulk):** wage-bracket cells (in-PDF, IRS-authored, independent of Deliverable 1 transcription). Evaluate engine at interval midpoint, `round()`, assert `==` cell.
- **Secondary oracle for over-ceiling fixtures (high earners):** percentage-method hand computation + the Deliverable 4 online calculators behind a manual human-verify checkpoint. Only Thomas Bergmann (~$9,231/period biweekly, above the $3,875 ceiling) needs this path.
- **MFJ + Step-2-checkbox schedule:** now covered by the in-PDF wage-bracket column — no longer a gap.
- **All four project frequencies (52/26/24/12):** covered by the in-PDF tables (synthetic 24/12 fixtures verify against the semimonthly/monthly tables).

---

## Worksheet 1A Computation Flow (End-to-End)

**Source:** `https://www.irs.gov/pub/irs-pdf/p15t.pdf` page 10 (Worksheet 1A)
**Confidence:** [VERIFIED: irs.gov/pub/irs-pdf/p15t.pdf page 10, retrieved 2026-06-22]

All inputs reference the employee's 2020+ Form W-4 fields (the project uses 2020+ form structure per FOUND-06).

```
STEP 1 — Adjust the employee's payment amount (annualize wages)
  1a = taxable_wages_this_period          (gross after pre-tax deductions, e.g. gross - 401k)
  1b = pay_periods_per_year              (12/24/26/52 from Employee.pay_periods_per_year)
  1c = 1a × 1b                           (annualize the wage)
  1d = step_4a_other_income              (from W-4 Step 4a — adds other income to withholding base)
  1e = 1c + 1d
  1f = step_4b_deductions               (from W-4 Step 4b — reduces withholding base)
  1g = $12,900 (MFJ) or $8,600 (other)  IF step_2_checkbox is False; else $0
       [standard deduction proxy — NOT the actual standard deduction; see note below]
  1h = 1f + 1g
  1i = max(0, 1e - 1h)                   <- ADJUSTED ANNUAL WAGE AMOUNT

STEP 2 — Figure the Tentative Withholding Amount (look up in bracket table)
  2a = 1i  (the Adjusted Annual Wage Amount)
  2b = column A of the matching bracket row (lower bound of the bracket)
  2c = column C of the matching bracket row (base withholding amount)
  2d = column D of the matching bracket row (marginal rate as a percent)
  2e = 2a - 2b                           (excess over the bracket lower bound)
  2f = 2e × (2d / 100)                   (marginal tax on the excess)
  2g = 2c + 2f                           (annual tentative withholding)
  2h = 2g / 1b                           (per-period tentative withholding)

STEP 3 — Account for tax credits (W-4 Step 3 dependents/other credits)
  3a = step_3_dependents                 (annual dollar amount from W-4 Step 3)
  3b = 3a / 1b                           (per-period credit)
  3c = max(0, 2h - 3b)                   <- FLOOR AT $0, NEVER NEGATIVE

STEP 4 — Figure the final amount to withhold
  4a = additional_withholding_per_period (from W-4 Step 4c — added flat amount)
  4b = 3c + 4a                           <- FINAL WITHHOLDING THIS PERIOD
```

**Key notes:**
- Line 1g is NOT the actual standard deduction ($30,000 MFJ / $15,000 single for 2026); it is the IRS's Worksheet 1A proxy amount used to convert the W-4's pre-tax structure. [VERIFIED: PDF page 10]
- Line 3c floors at $0 — withholding cannot go negative. This is an explicit "if zero or less, enter -0-" instruction from the PDF. [VERIFIED: PDF page 10]
- Line 1i also floors at $0 ("if zero or less, enter -0-"). [VERIFIED: PDF page 10]
- The project's employees have `step_4b_deductions` (line 1f) and no `step_4c_extra` per-period withholding. Line 4a is typically $0 for the seeded employees unless an employee carries an extra withholding amount (not in the current seed).
- **Table to use:** Single filing status maps to "Single or Married Filing Separately" table; `married_separately` also uses the same table. `married_jointly` uses the MFJ table. See Employee.filing_status Literal values.

---

## Standard Stack

### Core (No New Runtime Deps Required — Phase 3 is Pure Python)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python `decimal` | stdlib | All monetary arithmetic | Already used via `Decimal` + ROUND_HALF_UP; no float anywhere |
| `pytest` | latest | Golden-value test suite (most-tested unit in the repo) | Already installed; CLAUDE.md §6 mandates it |
| `pydantic` v2 | 2.13.4 | Employee/PaystubLineItem contracts (already present) | No change; Phase 3 adds no new contracts |

**No new runtime dependencies are required for Phase 3.** The withholding engine and constants module are pure Python. The `python-taxes` reference library is dev-only if used at all.

### Supporting (Dev / Eval Only)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `python-taxes` | 0.7.0 (PyPI, MIT) | Structure cross-check for 2023–2025 bracket method | Use ONLY to verify that the Worksheet 1A computation structure is correct; NOT for 2026 numbers |

**Installation (uv, as required by CLAUDE.md):**
```bash
uv run pytest -q              # run the test suite
uv add --dev python-taxes     # if using as a structure reference (optional)
```

---

## Package Legitimacy Audit

Phase 3 installs NO new external packages. This section is N/A.

All existing runtime packages (`fastapi`, `pydantic`, `psycopg`, `openai`, `reportlab`, etc.) were audited in Phase 2 research. No new packages are added by Phase 3.

---

## Architecture Patterns

### System Architecture Diagram

```
Employee (W-4 fields + pay data)
  + resolved_hours (5 fields)
  + contribution_401k_override (optional)
         |
         v
   calculate() [calculate.py — the deepened pure function]
         |
         +---> gross_pay  [hourly: rate×straight + 1.5×OT; salary: annual/periods + leave pay]
         |
         +---> pretax_401k = gross × rate_401k
         |
         +---> FICA base = gross (NOT reduced by 401k)
         |     fica_ss = min(gross, remaining_cap) × 0.062
         |     fica_medicare = gross × 0.0145
         |
         +---> federal_taxable_base = gross - pretax_401k  (federal base IS reduced by 401k)
         |     calls: federal_withholding(federal_taxable_base, employee) → Decimal
         |         |
         |         v
         |     federal_withholding() [federal_withholding.py — isolated pure function]
         |         imports: tax_tables_2026.BRACKETS_2026, STEP1_STANDARD_AMOUNTS_2026
         |         Worksheet 1A: Step 1 → Step 2 → Step 3 → Step 4
         |         returns: per-period withholding as Decimal (cents)
         |
         +---> net_pay = gross - pretax_401k - fica_ss - fica_medicare - federal_withholding
         |
         v
   PaystubLineItem (all fields filled; federal_withholding is a real number; net_pay is real net)

tax_tables_2026.py [pure constants module — dated, year-keyed]
  Header: source URLs (irs.gov/pub/irs-pdf/p15t.pdf; ssa.gov/oact/cola/cbb.html) + retrieval date
  BRACKETS_2026: dict keyed by (filing_status, step_2_checkbox) → list of bracket rows
  STEP1_STANDARD_AMOUNTS_2026: dict keyed by (filing_status, step_2_checkbox) → Decimal
  FICA_2026: SS_RATE, SS_WAGE_BASE, MEDICARE_RATE (migrated from calculate.py)
```

### Recommended Project Structure

```
app/pipeline/
├── calculate.py          # deepened: salary leave pay, federal_withholding() call, real net
├── federal_withholding.py  # NEW: isolated pure Worksheet 1A engine, keyed by tax_year
└── tax_tables_2026.py    # NEW: all 2026 constants (brackets + FICA) with dated header

tests/
├── test_calculate.py     # existing 401k override tests (must stay green)
└── test_federal_withholding.py  # NEW: golden-value test suite (most-tested unit in the repo)
```

### Pattern 1: Year-Keyed Tax Constants Module (D-02)

```python
# app/pipeline/tax_tables_2026.py
"""
2026 Federal Tax Constants for Payroll Engine.

Sources:
  IRS Publication 15-T (2026): https://www.irs.gov/pub/irs-pdf/p15t.pdf
  SSA Contribution and Benefit Base: https://www.ssa.gov/oact/cola/cbb.html
Retrieved: 2026-06-22

OBBBA note: The 2026 edition of Pub 15-T incorporates P.L. 119-21 (OBBBA) changes
(permanent extension of individual tax rates, increased standard deduction, no personal
exemptions). ONLY the standard percentage method is implemented here; the OBBBA
qualified-tips and qualified-overtime deductions are disclaimed and NOT modeled.
"""
from decimal import Decimal
from typing import NamedTuple

TAX_YEAR = 2026

class BracketRow(NamedTuple):
    lower: Decimal   # column A (at least)
    upper: Decimal   # column B (but less than); None for the top bracket
    base: Decimal    # column C (tentative amount to withhold)
    rate: Decimal    # column D as a fraction (e.g. Decimal("0.12") for 12%)

# STANDARD Withholding Rate Schedules (step_2_checkbox=False)
# Key: filing_status string matching Employee.filing_status Literal values
STANDARD_BRACKETS: dict[str, list[BracketRow]] = {
    "married_jointly": [...],          # from Deliverable 1, table 1A.1
    "single": [...],                   # from Deliverable 1, table 1A.1
    "married_separately": [...],       # same as "single" table
}

# Step 2 Checkbox Schedules (step_2_checkbox=True)
STEP2_BRACKETS: dict[str, list[BracketRow]] = {
    "married_jointly": [...],
    "single": [...],
    "married_separately": [...],
}

# Step 1 Line 1g standard amounts (used when step_2_checkbox=False)
STEP1_STANDARD: dict[str, Decimal] = {
    "married_jointly": Decimal("12900"),
    "single":          Decimal("8600"),
    "married_separately": Decimal("8600"),
}

# FICA constants (migrated from calculate.py per D-02)
SS_RATE      = Decimal("0.062")
SS_WAGE_BASE = Decimal("184500")   # SSA 2026 Contribution and Benefit Base
MEDICARE_RATE = Decimal("0.0145")
```

### Pattern 2: Isolated Worksheet 1A Pure Function

```python
# app/pipeline/federal_withholding.py
from decimal import Decimal, ROUND_HALF_UP
from app.models.roster import Employee
from app.pipeline.tax_tables_2026 import (
    STANDARD_BRACKETS, STEP2_BRACKETS, STEP1_STANDARD, TAX_YEAR
)

_CENTS = Decimal("0.01")

def _money(v: Decimal) -> Decimal:
    return v.quantize(_CENTS, rounding=ROUND_HALF_UP)

def federal_withholding_2026(
    federal_taxable_wages_this_period: Decimal,
    employee: Employee,
) -> Decimal:
    """Compute per-period federal withholding via Worksheet 1A (Pub 15-T 2026).

    federal_taxable_wages_this_period: gross - pretax_401k (NOT raw gross).
    Returns per-period withholding in cents (ROUND_HALF_UP).
    """
    p = Decimal(employee.pay_periods_per_year)
    status = employee.filing_status
    checkbox = employee.step_2_checkbox

    # Step 1 — annualize
    line_1a = federal_taxable_wages_this_period
    line_1c = _money(line_1a * p)                            # annualize
    line_1d = employee.step_4a_other_income                  # W-4 Step 4a
    line_1e = _money(line_1c + line_1d)
    line_1f = employee.step_4b_deductions                    # W-4 Step 4b
    line_1g = Decimal("0") if checkbox else STEP1_STANDARD[status]
    line_1h = _money(line_1f + line_1g)
    line_1i = max(Decimal("0"), _money(line_1e - line_1h))  # adjusted annual wage

    # Step 2 — tentative withholding from bracket table
    brackets = STEP2_BRACKETS[status] if checkbox else STANDARD_BRACKETS[status]
    row = _find_bracket(line_1i, brackets)
    line_2e = _money(line_1i - row.lower)
    line_2f = _money(line_2e * row.rate)
    line_2g = _money(row.base + line_2f)                    # annual tentative withholding
    line_2h = _money(line_2g / p)                           # per-period tentative withholding

    # Step 3 — subtract tax credits (W-4 Step 3), floor at $0
    line_3b = _money(employee.step_3_dependents / p)
    line_3c = max(Decimal("0"), _money(line_2h - line_3b))

    # Step 4 — add extra withholding per period (W-4 Step 4c, typically $0)
    # Project employees carry no Step 4c extra withholding in the seed.
    # When needed: line_4a = employee.step_4c_extra_per_period (not yet a field)
    line_4b = line_3c  # + step_4c when added

    return line_4b
```

### Anti-Patterns to Avoid

- **Float arithmetic anywhere in the calc:** All amounts must be `Decimal`. Python `float` has binary precision errors that produce wrong cents. (`_money()` doesn't fix floats — you must never use `float`.)
- **Using the tax-constants module as its own oracle:** The golden suite must use hand-computed expected values or layer-B calculator values — NEVER derive expected values from calling the same `tax_tables_2026.py` the engine uses.
- **Negative withholding:** Line 3c and line 1i both floor at $0 (explicit "if zero or less, enter -0-" in the PDF). The engine must clamp at $0, not allow negative withholding.
- **401k reducing the FICA base:** The FICA base is gross pay, NOT gross minus 401k. Only the federal withholding base is reduced by 401k. This is the highest-bug-risk 401k interaction (D-04).
- **Auto-deriving OT from hours_regular > 40:** Forbidden by D-03. The calc accepts `hours_overtime` as given.
- **Hardcoding leave hours into OT threshold for salaried employees:** Salaried employees get `annual / periods + leave pay`; leave hours are added at straight time, not triggering OT.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Decimal arithmetic | Custom fixed-point type | Python `decimal.Decimal` with ROUND_HALF_UP | Stdlib; battle-tested; the project already uses it |
| Worksheet 1A bracket lookup | Binary search or dict lookup hand-written per bracket | Simple linear scan of `BracketRow` list (8 rows max) | 8 rows; O(n) is fine; readability > performance here |
| 2026 bracket tables | Scraping or formula-generating them at runtime | Static constants in `tax_tables_2026.py` | Tables change once per year; static is auditable, runtime fetch is fragile |

---

## 401k Interaction — Federal vs FICA Base (CALC-03)

**Confidence:** [VERIFIED: IRS Topic 751; established payroll accounting; verified against CLAUDE.md §5]

Traditional (pre-tax) 401k contributions:
- **REDUCE the federal income tax withholding base** — the IRS withholds on wages AFTER the 401k deduction
- **Do NOT reduce the FICA (SS + Medicare) base** — FICA taxes are assessed on gross wages before the 401k deduction

Implementation in `calculate.py`:
```python
# FICA base = gross (no 401k reduction):
ss_taxable = min(gross, remaining_cap)         # uses gross directly
fica_ss = _money(ss_taxable * SS_RATE)
fica_medicare = _money(gross * MEDICARE_RATE)

# Federal base = gross - pretax_401k:
federal_taxable = gross - pretax_401k           # 401k reduces only the federal base
federal_wh = federal_withholding_2026(federal_taxable, employee)
```

**Golden test requirement:** At least one D-04 case must assert a scenario where `pretax_401k > 0`, verify that `fica_ss` uses the gross base (not the reduced federal base), AND verify that `federal_withholding` uses the reduced base. This is the highest-risk interaction for the test suite.

---

## FICA Constants (2026) — Confirmed

**Source:** SSA Contribution & Benefit Base (`https://www.ssa.gov/oact/cola/cbb.html`); IRS Topic 751 (`https://www.irs.gov/taxtopics/tc751`)
**Confidence:** HIGH [CITED: SSA and IRS sources; corroborated by CLAUDE.md §5 and multiple payroll sources]

Note: `cbb.html` returns 403 to non-browser fetch — cite in the module header, do NOT scrape at runtime.

| Constant | 2026 Value | Notes |
|----------|-----------|-------|
| SS Rate (employee share) | **6.2%** | Unchanged from 2025 |
| SS Wage Base | **$184,500** | Up from $176,100 in 2025; SSA COLA 2026 |
| Employee SS max | **$11,439.00** | $184,500 × 6.2% |
| Medicare Rate | **1.45%** | No wage cap |
| Additional Medicare | **0.9% over $200,000** YTD | NOT MODELED — disclaimed; demo wages never reach this threshold |

These constants are currently inline in `calculate.py` (`_SS_RATE`, `_SS_WAGE_BASE`, `_MEDICARE_RATE`). They **migrate to `tax_tables_2026.py`** per D-02. The values do NOT change; only the location changes.

---

## Gross Calc Engine — Phase 3 Additions

### Hourly Gross (CALC-01) — Existing Logic + Phase 3 Verification

The current `calculate.py` already implements:
```python
gross = rate * straight + rate * Decimal("1.5") * hours["hours_overtime"]
```
Where `straight = hours_regular + hours_vacation + hours_sick + hours_holiday`.

Phase 3 confirms this is correct per D-03 (OT is explicit-only) and CALC-01 (1.5× for hours_overtime field; leave at straight time). No change needed to the hourly gross logic.

### Salaried Gross (CALC-02) — Phase 3 Adds Leave Pay

The current `calculate.py` computes:
```python
gross = annual / Decimal(employee.pay_periods_per_year)
```
This IGNORES leave hours for salaried employees. CALC-02 requires:
```
salary_gross = (annual / pay_periods_per_year) + leave_pay
```
Where `leave_pay = salaried_rate_per_hour * (vacation + sick + holiday hours)`.

**Problem:** The `Employee` model carries `annual_salary` but no per-hour rate for salaried employees (that would require `annual / 52 / 40` or similar). CALC-02 says "plus added vacation/sick/holiday pay" but doesn't specify the rate. Options:
1. Use `annual_salary / (52 * 40)` as an implied hourly rate for salaried leave pay
2. Treat leave pay as pro-rated salary: `(leave_hours / hours_per_period) × (annual / periods)`
3. Store a separate `leave_rate` on Employee (not in the current model — a schema change)

**Recommendation for planner:** Option 2 (pro-rated salary) is the simplest and requires no model change. Formula: `leave_pay = (annual / pay_periods_per_year) * (leave_hours / standard_hours_per_period)`. The planner must decide the `standard_hours_per_period` assumption (e.g. 40 for weekly, 80 for biweekly) — this is a Claude's Discretion item.

---

## Net Pay Formula (CALC-07)

```
net_pay = gross - pretax_401k - fica_ss - fica_medicare - federal_withholding
```

Phase 3 retires the `PRE_FEDERAL_NET_LABEL` constant by replacing `federal_withholding = Decimal("0")` with the real computed value. The label constant can be removed from `calculate.py` and the Phase 2 README disclaimer stub updated.

---

## Reconciliation Backstop (CALC-08)

**Source:** CONTEXT.md D-01 framing; CALC-08 requirement text
**Confidence:** HIGH — this is a pure arithmetic identity, not a tax computation

The reconciliation check asserts:
```
gross - pretax_401k - fica_ss - fica_medicare - federal_withholding - state_withholding == net_pay
```
(With `state_withholding` always `None` in Phase 3, so it simplifies to the 5-term formula.)

This is an arithmetic backstop only. It will pass even if the tax tables are wrong (as long as the code internally uses those wrong tables consistently). It does NOT replace the golden-value test suite.

**Location:** Planner's call per CONTEXT.md. Options:
- Per-line in `calculate()` raising an assertion if the identity fails (fails loudly at compute time)
- Run-level check in the orchestrator storing the result in `payroll_runs.reconciliation` JSONB (the column added in Phase 2 per D-A3-05)

---

## Common Pitfalls

### Pitfall 1: 401k Reduces Both Bases (Wrong)
**What goes wrong:** The FICA SS and Medicare are computed on `gross - pretax_401k` instead of `gross`.
**Why it happens:** The 401k "pre-tax" label implies it reduces all taxes, but FICA operates on gross wages.
**How to avoid:** Separate the FICA base (always `gross`) from the federal withholding base (`gross - pretax_401k`).
**Warning signs:** In the golden test, FICA amounts differ by `pretax_401k * SS_RATE` from the correct values.

### Pitfall 2: Wrong Line 1g Standard Amount
**What goes wrong:** Using the actual 2026 standard deduction ($30,000 MFJ) instead of the Worksheet 1A proxy ($12,900 MFJ / $8,600 Single).
**Why it happens:** The standard deduction is a well-known figure; the Worksheet 1A proxy is specific to the withholding calculation.
**How to avoid:** Use ONLY the amounts from Deliverable 1, Section 1A.3 above.
**Warning signs:** Withholding is dramatically underestimated for most employees (too large a deduction proxy reduces the annualized wage too far).

### Pitfall 3: Step 3 Credit Goes Negative (Wrong)
**What goes wrong:** A large Step-3 dependent credit ($8,000+) produces negative per-period withholding.
**Why it happens:** Line 3b (per-period credit) exceeds Line 2h (tentative withholding).
**How to avoid:** Line 3c = `max(0, 2h - 3b)` — floor at $0. Thomas Bergmann (seed employee, $8,000 Step 3 credit) may trigger this case.
**Warning signs:** Negative number in the `federal_withholding` field.

### Pitfall 4: Filing Status Mapping Mismatch
**What goes wrong:** `"married_separately"` employees use the MFJ table instead of the Single/MFS table.
**Why it happens:** The IRS table header says "Single or Married Filing Separately" — the combined heading is easy to miss.
**How to avoid:** Map both `"single"` AND `"married_separately"` to the same bracket table. Employee `"married_jointly"` gets the MFJ table.
**Warning signs:** `married_separately` withholding is half what it should be (MFJ bracket bounds are roughly double the Single/MFS bounds).

### Pitfall 5: Annualization Rounding Accumulates Error
**What goes wrong:** Rounding at line 1c (annualize) and then de-annualizing at line 2h accumulates a rounding error that breaks a penny-level test.
**Why it happens:** `round(round(x × 52) / 52) ≠ round(x)` for all x.
**How to avoid:** Apply `_money()` (cents) at each step to stay in exact Decimal arithmetic; do not round to whole dollars mid-computation. Accept that the final per-period result may differ from `annual_withholding / 52` by $0.01 or less — this is mathematically correct behavior.
**Warning signs:** A test expects `$X.00` but gets `$X.01` or `$X.99`.

### Pitfall 6: Self-Derived Oracle (the D-01 Trap)
**What goes wrong:** Golden expected values are computed by calling the engine code being tested.
**Why it happens:** It is the easiest way to produce "expected" values during test writing.
**How to avoid:** All golden expected values MUST be hand-computed using the Deliverable 1 tables directly, then cross-checked against layer-B calculators BEFORE writing the test.
**Warning signs:** A transcription bug in `tax_tables_2026.py` makes the golden test still pass.

### Pitfall 7: Using python-taxes for 2026 Numbers
**What goes wrong:** `python-taxes 0.7.0` produces a 2026 expected value (the library returns results for tax_year parameter but only ships 2023–2025 tables).
**Why it happens:** The library has a nice API that looks authoritative.
**How to avoid:** `python-taxes` is explicitly a structure reference ONLY. Never pass `tax_year=2026` to it as a source of golden truth — 2026 tables are not in it.

---

## Seed Employee Coverage for Layer-B Fixtures

**Source:** `app/db/seed.py` — reviewed 2026-06-22
**Confidence:** [VERIFIED: codebase read 2026-06-22]

The 7 seeded employees cover the following D-04 matrix cells for layer-B fixtures:

| Employee | Filing Status | Step-2 | Pay Freq | Key Coverage |
|----------|--------------|--------|----------|--------------|
| Maria Chen (e1) | single | False | 52 (weekly) | Single standard, weekly, no 401k, no Step-3 |
| James Okafor (e2) | married_jointly | False | 52 (weekly) | MFJ standard, 401k=4%, Step-3=$4,000 |
| David Reyes (e3) | single | False | 52 (weekly) | Single standard, low wages |
| Priya Nair (e4) | married_separately | True | 52 (weekly) | MFS + Step-2 checkbox, 401k=6%, Step-4a=$2,000 |
| Thomas Bergmann (e5) | married_jointly | False | 26 (biweekly) | MFJ, high earner ($240k annual), SS straddle, Step-3=$8,000 |
| Sandra Kim (e6) | single | False | 26 (biweekly) | Single, hourly, 401k=5%, biweekly |
| Daniel Reyes (e7) | single | False | 52 (weekly) | Single standard, low wages |

**D-04 matrix coverage from seed alone (6 schedules):**
- Single/MFS + Standard: Maria Chen, David Reyes, Sandra Kim, Daniel Reyes — COVERED
- Single/MFS + Step-2 checkbox: Priya Nair (married_separately maps to this table) — COVERED
- MFJ + Standard: James Okafor, Thomas Bergmann — COVERED
- MFJ + Step-2 checkbox: **NOT covered by any seeded employee** — requires SYNTHETIC fixture

**Missing schedule from seed:** MFJ + Step-2 checkbox requires a synthetic Employee fixture constructed in the test module.

**Missing pay frequencies:** Only 52 (weekly) and 26 (biweekly) are covered by seed. Semi-monthly (24) and monthly (12) require SYNTHETIC Employee fixtures per CONTEXT.md D-04 note.

**Minimum synthetic fixtures needed:**
1. MFJ + Step-2 checkbox (any pay frequency)
2. At least one of 24 (semi-monthly) or 12 (monthly) frequency

---

## Code Examples

### Golden Test Pattern (table-driven pytest parametrize)

```python
# tests/test_federal_withholding.py
"""Golden-value tests for the Pub 15-T 2026 Worksheet 1A federal withholding engine.

ALL expected values were hand-computed from the 2026 Pub 15-T bracket tables
(RESEARCH.md Deliverable 1, sourced from irs.gov/pub/irs-pdf/p15t.pdf, retrieved 2026-06-22)
and cross-checked against usapaycheck.org and paycheckcity.com before being written here.
NO expected value was derived from the tax_tables_2026.py module under test.
"""
import pytest
from decimal import Decimal
from app.pipeline.federal_withholding import federal_withholding_2026
from tests.fixtures.synthetic_employees import make_employee  # helper

@pytest.mark.parametrize("desc,wages_this_period,emp_kwargs,expected_wh", [
    # Layer-B seeded employee fixtures (cross-checked against layer-B calculators)
    # ... (planner fills these in using Deliverable 1 hand computations)

    # Edge case: Step-3 credit exceeds tentative withholding → $0.00
    ("step3_floor_at_zero", Decimal("150.00"), {
        "filing_status": "single", "step_2_checkbox": False,
        "step_3_dependents": Decimal("5000.00"),
        "step_4a_other_income": Decimal("0"), "step_4b_deductions": Decimal("0"),
        "pay_periods_per_year": 52,
    }, Decimal("0.00")),
])
def test_federal_withholding_golden(desc, wages_this_period, emp_kwargs, expected_wh):
    emp = make_employee(**emp_kwargs)
    result = federal_withholding_2026(wages_this_period, emp)
    assert result == expected_wh, (
        f"[{desc}] expected {expected_wh}, got {result}. "
        "If this fails, re-verify the hand computation and layer-B cross-check before changing the expected value."
    )
```

### Hand-Computation Worked Example (Single/Standard, Weekly $800)

This demonstrates the Worksheet 1A steps using the live transcribed tables, and shows how to produce a layer-A golden fixture. All numbers derived from Deliverable 1.

```
Employee: Single, step_2_checkbox=False, step_3_dependents=$0, step_4a=$0, step_4b=$0
Federal taxable wages this period: $800.00 (gross - pretax_401k)
Pay periods per year: 52 (weekly)

Step 1 — Annualize:
  1a = $800.00
  1b = 52
  1c = $800.00 × 52 = $41,600.00
  1d = $0.00  (step_4a_other_income)
  1e = $41,600.00
  1f = $0.00  (step_4b_deductions)
  1g = $8,600  (Single, step_2 not checked)
  1h = $0 + $8,600 = $8,600.00
  1i = max(0, $41,600 - $8,600) = $33,000.00  (Adjusted Annual Wage)

Step 2 — Bracket lookup (Single/Standard table, $33,000):
  Row: At least $19,900 but less than $57,900 → base $1,240.00 + 12% × excess
  2b = $19,900.00
  2c = $1,240.00
  2d = 12%
  2e = $33,000.00 - $19,900.00 = $13,100.00
  2f = $13,100.00 × 0.12 = $1,572.00
  2g = $1,240.00 + $1,572.00 = $2,812.00  (annual tentative)
  2h = $2,812.00 / 52 = $54.08 (per-period tentative, ROUND_HALF_UP to cents)

Step 3 — Step-3 credits:
  3a = $0.00
  3b = $0.00
  3c = max(0, $54.08 - $0.00) = $54.08

Step 4 — Final:
  4a = $0.00  (no extra withholding)
  4b = $54.08

→ Expected per-period withholding = $54.08
  [Verify against usapaycheck.org and paycheckcity.com before writing as golden fixture]
```

### Constants Migration Pattern (D-02)

In `calculate.py`, the three inline constants:
```python
_SS_RATE = Decimal("0.062")
_SS_WAGE_BASE = Decimal("184500")
_MEDICARE_RATE = Decimal("0.0145")
```
Become imports after migration:
```python
from app.pipeline.tax_tables_2026 import SS_RATE, SS_WAGE_BASE, MEDICARE_RATE
```
The values are IDENTICAL — only the location changes. Existing tests that implicitly test these values (via FICA output assertions) must remain green through the migration.

---

## State of the Art

| Old Approach (Phase 2) | Current Approach (Phase 3) | Impact |
|------------------------|---------------------------|--------|
| `federal_withholding = Decimal("0")` | Real Pub 15-T 2026 Worksheet 1A computation | Net pay is now real net, not pre-federal |
| Net labeled "pre-federal" | Real net: gross - pretax - FICA - federal | `PRE_FEDERAL_NET_LABEL` constant retired |
| FICA constants inline in calculate.py | Constants in dated year-keyed module (D-02) | One audit point, additive year-over-year updates |
| Salary gross = annual / periods only | Salary gross = annual / periods + leave pay | CALC-02 fulfilled |
| No reconciliation check | Arithmetic backstop: net + taxes + deductions = gross | CALC-08; does NOT guarantee tax correctness |
| No Pub 15-T tables in the codebase | `tax_tables_2026.py` with dated source header | Auditable, year-keyed |

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (already installed) |
| Config file | `pyproject.toml` (uv-managed) or `pytest.ini` — check project root |
| Quick run command | `uv run pytest tests/test_federal_withholding.py -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | Notes |
|--------|----------|-----------|-------------------|-------|
| CALC-01 | OT at 1.5×; leave excluded from OT base | unit | `uv run pytest tests/test_calculate.py -k "hourly" -q` | Extend existing test_calculate.py |
| CALC-02 | Salaried + leave pay | unit | `uv run pytest tests/test_calculate.py -k "salary" -q` | New case in existing file |
| CALC-03 | 401k reduces federal not FICA | unit/golden | `uv run pytest tests/test_federal_withholding.py -k "401k" -q` | Critical: verify FICA uses gross base |
| CALC-04 | FICA SS straddle + Medicare flat | unit/golden | `uv run pytest tests/test_federal_withholding.py -k "fica" -q` | SS straddle edge case; Thomas Bergmann |
| CALC-05 | All 6 Worksheet 1A schedules | golden | `uv run pytest tests/test_federal_withholding.py -q` | The primary golden suite |
| CALC-06 | Tax constants module dated header + Decimal penny tests | unit | `uv run pytest tests/test_federal_withholding.py -q` | All golden tests satisfy this |
| CALC-07 | Net = gross - pretax - FICA - federal | unit | `uv run pytest tests/test_calculate.py -k "net" -q` | Integration assertion in calculate test |
| CALC-08 | Reconciliation check identity | unit | `uv run pytest tests/test_calculate.py -k "reconciliation" -q` | Arithmetic identity; does NOT verify tax math |

### Wave 0 Gaps

- [ ] `tests/test_federal_withholding.py` — covers CALC-01/02/03/04/05/06 (new file; planner creates in Wave 1)
- [ ] `app/pipeline/federal_withholding.py` — new Worksheet 1A engine module
- [ ] `app/pipeline/tax_tables_2026.py` — new constants module

*(Existing `tests/test_calculate.py` already covers 401k override; Phase 3 extends it for CALC-01/02/07/08. No new framework install needed.)*

---

## Security Domain

This phase implements no authentication, no user input processing, no network calls, and no persistent state changes. It is pure offline arithmetic. ASVS categories V2, V3, V4 do not apply. V5 (input validation) is handled by the existing Pydantic contracts (`Employee` with `ge=0` constraints on all W-4 fields). V6 (cryptography) is not applicable.

**One security-adjacent note:** The tax constants module embeds numbers transcribed from a public government document. There is no attack surface; the concern is transcription accuracy, not security. Golden tests are the integrity control.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | usapaycheck.org implements Pub 15-T Worksheet 1A (employer percentage method) and accepts Step 4a/4b inputs | Deliverable 4 | Layer-B oracle produces wrong-method results; false disagreements with hand computation; must manually verify the tool before using it |
| A2 | paycheckcity.com uses the employer percentage method (not annual liability or another method) | Deliverable 4 | Same as A1; the tool's disclaimer says "not for accuracy" |
| A3 | Traditional 401k reduces the federal withholding base but NOT the FICA base | 401k Interaction | Wrong FICA or federal amounts; golden tests would catch this if the oracle is independent |
| A4 | The salaried leave pay addition (CALC-02) should use pro-rated salary, not a separate hourly rate | Gross Calc Engine | Minor pay discrepancy for salaried employees with leave; the planner should clarify the leave rate convention and document it |
| A5 | `step_4c_extra_per_period` is not a field on `Employee` (Step 4c extra withholding is not in the current seed) | Worksheet 1A flow | If a seeded employee has extra withholding, the engine will silently ignore it; verify against seed data |
| A6 | The IRS builds each wage-bracket cell by applying the percentage method at the interval MIDPOINT, rounded to the whole dollar (undocumented in the 2026 PDF) | Deliverable 5 | If the convention differs, the midpoint-evaluate-then-round cross-check could be off by $1; mitigated by asserting whole-dollar equality at the midpoint, not penny equality at exact wage |

---

## Open Questions (RESOLVED)

> All four questions are resolved below. The Q2 and Q4 resolutions were proposed via the
> coordinator and happen to align with this research's own recommendations (assumption A4 and
> the Reconciliation Backstop section). They remain **Claude's Discretion** items per CONTEXT.md
> — the planner may adjust — but the resolutions below are the recommended defaults. (Coordinator
> relay carries no user authority; these are recorded as engineering recommendations, not user
> decisions.)

1. **Layer-B calculator Step 4a/4b coverage — RESOLVED**
   - Resolution: The new **Deliverable 5 wage-bracket in-PDF oracle** is now the PRIMARY independent oracle for any fixture whose adjusted per-period wage falls under the ~$100k-annualized ceiling — and it does NOT depend on any online calculator being reachable or exposing Step-4a/4b inputs. Step-4a/4b are folded into the Adjusted Wage Amount (Worksheet 2 line 1h) BEFORE the table lookup, so the table needs no Step-4a/4b input surface. The online layer-B calculators (usapaycheck.org, paycheckcity.com) drop to **secondary corroboration + a manual human-verify checkpoint** in the plan, used only for over-ceiling cells (high earners like Thomas Bergmann). Step-4a/4b coverage is no longer blocked on a third-party tool.

2. **Salaried leave pay rate (CALC-02) — RESOLVED**
   - Resolution: **`leave_pay = (annual_salary / 2080) × leave_hours`**, where 2080 = 52 × 40 (standard full-time annual hours) and `leave_hours = hours_vacation + hours_sick + hours_holiday`. Salaried gross = `(annual_salary / pay_periods_per_year) + leave_pay`. Frequency-independent (no per-frequency `standard_hours_per_period` assumption needed). Matches assumption A4. Still a Claude's Discretion item — document the `/2080` divisor in the calc and add a salaried-with-leave golden test.

3. **MFJ + Step-2 checkbox synthetic fixture oracle — RESOLVED**
   - Resolution: Use the **Deliverable 5 wage-bracket tables** as the in-PDF oracle. They include an explicit MFJ → Step-2-Checkbox column for every pay frequency (pages 14–25). A synthetic MFJ + Step-2 employee under the ceiling is verified to the IRS-published cell (evaluate engine at the interval midpoint, round to whole dollars, assert `==` the cell). No online calculator and no self-derived value needed — the strongest independence available for that schedule.

4. **Reconciliation check location — RESOLVED**
   - Resolution: **Per-line `AssertionError` raised inside `calculate()`** — assert `gross - pretax_401k - fica_ss - fica_medicare - federal_withholding - (state_withholding or 0) == net_pay` before returning the `PaystubLineItem` (fails loudly at compute time; CALC-08 arithmetic backstop). The pass/fail result MAY also persist to `payroll_runs.reconciliation` JSONB at the run level for the Phase 5 dashboard, but the load-bearing check is the per-line assertion. Matches the Reconciliation Backstop section.

---

## Environment Availability

This phase is entirely offline. No external tools, services, or runtimes beyond the existing Python 3.12 + uv environment are required.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | All calc code | ✓ | 3.12 (pinned via .python-version) | — |
| pytest | Golden test suite | ✓ | Latest (uv dev dep) | — |
| pydantic v2 | Employee/PaystubLineItem contracts | ✓ | 2.13.4 | — |
| Python `decimal` module | All monetary arithmetic | ✓ | stdlib | — |

**Missing dependencies with no fallback:** None.

---

## Sources

### Primary (HIGH confidence — live PDF transcription)
- `https://www.irs.gov/pub/irs-pdf/p15t.pdf` — IRS Publication 15-T (2026), 71 pages, retrieved 2026-06-22 via pdfplumber. Sourced: Worksheet 1A (page 10), bracket tables (page 12), rounding guidance (page 9), OBBBA What's New (pages 1–2), all table pairs (standard and Step-2 checkbox).
- `https://www.irs.gov/publications/p15t` — Landing page confirming 2026 publication and OBBBA inclusion.
- `https://www.irs.gov/pub/irs-pdf/p15t.pdf` (Section 2, pages 13–27) — 2026 Wage Bracket Method Tables for Manual Payroll Systems With Forms W-4 From 2020 or Later. The in-PDF independent oracle (Deliverable 5): all 6 schedules (3 statuses × Standard/Step-2-Checkbox), frequencies weekly/biweekly/semimonthly/monthly/daily, ceilings ≈$100k annualized.

### Secondary (HIGH confidence — corroborated official sources)
- SSA `https://www.ssa.gov/oact/cola/cbb.html` — SS wage base $184,500 (2026). Cannot be scraped at runtime (403); cited in module header only.
- IRS Topic 751 `https://www.irs.gov/taxtopics/tc751` — FICA rates: SS 6.2%, Medicare 1.45%, Additional Medicare 0.9% thresholds.
- `https://payroll.org/news-resources/news/news-detail/2025/12/12/irs-releases-2026-publication-15-t-includes-obbba-information` — Confirms 2026 Pub 15-T includes OBBBA changes.

### Tertiary (MEDIUM confidence — tool claims, not officially verified)
- `https://usapaycheck.org/biweekly-paycheck-calculator/` — Claims to use IRS Pub 15-T Percentage Method for 2026; accepts Step 2/3/4 inputs. Use as layer-B oracle with cross-check.
- `https://www.paycheckcity.com/calculator/salary` and `/hourly` — References Pub 15-T; use as secondary layer-B oracle with cross-check. Carries "not for accuracy" disclaimer.
- `https://pypi.org/project/python-taxes/` — python-taxes 0.7.0, MIT, covers 2023–2025 only. Structure reference, NOT a 2026 oracle.

---

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — no new deps; all existing libraries already proven
- Architecture (module structure): HIGH — directly mirrors existing pure-function pattern; CLAUDE.md and CONTEXT.md both recommend isolated module
- Pub 15-T bracket tables (Deliverable 1): HIGH — transcribed live from irs.gov/pub/irs-pdf/p15t.pdf, 2026-06-22
- Rounding guidance (Deliverable 2): HIGH — verbatim from live PDF page 9
- Worked example inventory (Deliverable 3): HIGH — confirmed by full-PDF search; zero Worksheet 1A worked examples found (the wage-bracket tables, Deliverable 5, are the in-PDF answer key instead)
- Oracle tool identification (Deliverable 4): MEDIUM — online tool method claims verified at surface level; now a secondary corroboration role behind a human-verify checkpoint (Deliverable 5 is the primary oracle)
- Wage-bracket in-PDF oracle (Deliverable 5): HIGH — tables transcribed live from pages 13–27; the only ASSUMED element is the undocumented midpoint construction convention (handled by the midpoint-evaluate-then-round assertion rule)
- FICA constants: HIGH — SSA + IRS Topic 751 + CLAUDE.md §5 corroboration
- 401k federal/FICA base distinction: HIGH — established payroll accounting, verified against multiple sources

**Research date:** 2026-06-22
**Valid until:** 2027-01-01 for 2026 constants (IRS releases new Pub 15-T for 2027 in December 2026); 30 days for oracle tool availability
