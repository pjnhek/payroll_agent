---
phase: 3
slug: harden-the-calc
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-22
revised: 2026-06-22
revision_reason: |
  Round 1 (Codex review FIX A–H): 03-02 moved wave 2→3 (depends on 03-03); leave formula /2080;
  Additional Medicare proxy trigger; reconciliation assert→raise; wave order; rounding; boundary tests;
  metadata. Round 2 (R2-1 through R2-8):
    R2-1: wage-bracket tolerance changed from blanket ±$1 to exact equality (== default); ±$1 only on named-exception rows with documented reason.
    R2-2: Additional Medicare test fixtures changed to REALISTIC capped SS YTD values (ytd_ss_wages=184500 max, not impossible 196000/197000).
    R2-3: reconciliation check extracted into named helper _raise_if_reconciliation_drift(); test_reconciliation_raises_on_drift now exercises ACTUAL raise path via pytest.raises.
    R2-4: bracket boundary tests changed from (B+STEP1)/52 construction to DIRECT _find_bracket() calls with adjusted-annual-wage inputs.
    R2-5: skipped Thomas Bergmann fixture now reports "OVER-CEILING ORACLE UNRESOLVED" in skip reason and SUMMARY.md — a skip is not coverage.
    R2-6: p=26 (biweekly) added to frequency-invariance test (delta_52==delta_26==delta_24==delta_12).
    R2-7: python-taxes dev dep REMOVED from 03-02; pyproject.toml + uv.lock removed from 03-02 files_modified.
    R2-8: wage-bracket acceptance criteria updated from "at least 4 schedule columns" to "all 6 schedule columns" — matches the objective.
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> The Pub 15-T engine is the highest-bug-risk unit in the repo (CLAUDE.md §6) — it MUST be the most-tested. The golden suite is the correctness oracle; the reconciliation check (CALC-08) is an arithmetic backstop only, NOT the oracle.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (already installed; uv-managed dev dep) |
| **Config file** | `pyproject.toml` (uv-managed) — check `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest tests/test_federal_withholding.py -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~5–10 seconds (pure offline Decimal arithmetic; no DB, no network) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_federal_withholding.py -q` (or the touched test file)
- **After every plan wave:** Run `uv run pytest -q` (full suite — 195+ existing tests must stay green through the constants migration)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~10 seconds

---

## Per-Task Verification Map

> Filled with final task IDs from the revised Phase 3 plans (Round 2 revisions applied).
> **FIX D (Codex review):** 03-02 is now wave 3 (depends on 03-01 AND 03-03) because 03-02's Task 2 calls calculate() for the 401k-base and Additional Medicare flag cases — those behaviors are implemented in 03-03.
> Phase 3 is pure offline arithmetic (see RESEARCH.md §Security Domain), so Threat Ref is "—" throughout.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-T1 | 01 | 1 | CALC-06 | — | N/A (offline calc) | unit | `uv run python -c "from app.pipeline.tax_tables_2026 import TAX_YEAR; print('OK')"` | ❌ W0 creates | ⬜ pending |
| 03-01-T2 | 01 | 1 | CALC-05 | — | N/A | unit | `uv run python -c "from app.pipeline.federal_withholding import federal_withholding_2026; print('OK')"` | ❌ W0 creates | ⬜ pending |
| 03-03-T1 | 03 | 2 | CALC-01/02/03/04/07/08 | — | N/A | unit | `uv run pytest tests/test_calculate.py -q` | ✅ (extended) | ⬜ pending |
| 03-03-T2 | 03 | 2 | CALC-01/02/07/08 | — | N/A | unit + FIX A invariance + R2-3 raise + R2-6 p=26 | `uv run pytest tests/test_calculate.py -q` | ✅ (extended) | ⬜ pending |
| 03-02-CKP | 02 | 3 | CALC-05/06 (D-01) | — | N/A (human gate) | human-verify | Manual: usapaycheck.org + paycheckcity.com calibration + Thomas Bergmann over-ceiling (two-calculator agreement required; if skip → "OVER-CEILING ORACLE UNRESOLVED" in SUMMARY.md) | N/A | ⬜ pending |
| 03-02-T2 | 02 | 3 | CALC-03/04/05/06 | — | N/A | golden + wage-bracket (exact ==, R2-1) + _find_bracket() direct boundary (R2-4) | `uv run pytest tests/test_federal_withholding.py -q` | ❌ W0 creates | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Execution Wave Order

```
Wave 1: 03-01 (tax_tables_2026.py + federal_withholding.py)
Wave 2: 03-03 (calculate.py deepening + contracts.py + test_calculate.py extension)
Wave 3: 03-02 (test_federal_withholding.py golden suite — depends on 03-01 AND 03-03)
```

**Why 03-03 before 03-02 (FIX D):**
03-02's Task 2 calls `calculate()` for the 401k-base-split case (CALC-03), the Step-4b FICA-base assertion (Fix 7b), and the Additional Medicare flag test (User Decision 1, FIX B). All of these behaviors — `PaystubLineItem.additional_medicare_not_modeled`, the deepened `calculate()` function, `_raise_if_reconciliation_drift()`, and the `PayrollCalculationError` class — are implemented in 03-03. Running 03-02 before 03-03 would require either (a) forward references to unshipped code, or (b) removing calculate() integration cases from 03-02 and pushing them to 03-03 (which is where they now live, per Fix 9). The cleaner solution is wave ordering: 03-03 ships first, then 03-02 can import and test the complete calculate() without any forward dependency.

---

## Wave 0 Requirements

- [x] `tests/test_federal_withholding.py` — NEW golden-value suite (covers CALC-03/04/05/06); created by 03-02-T2
- [x] `app/pipeline/federal_withholding.py` — NEW Worksheet 1A engine module; created by 03-01-T2
- [x] `app/pipeline/tax_tables_2026.py` — NEW dated year-keyed constants module; created by 03-01-T1
- [x] Synthetic Employee fixtures — constructed inline in test_federal_withholding.py via _make_employee() helper (no separate fixtures/ dir needed)
- [ ] ~~`uv add --dev python-taxes`~~ — REMOVED (R2-7): python-taxes was considered but NOT installed. The structural test was dropped (FIX F — engine is 2026-keyed; python-taxes ships 2023–2025). Installing with no test using it adds supply-chain/lockfile churn with zero verification value. The wave-bracket PRIMARY oracle already provides the structural independence. pyproject.toml and uv.lock are NOT modified by any Phase 3 plan.
- [x] `PayrollCalculationError` exception class — defined in calculate.py by 03-03-T1 (FIX C / R2-3)
- [x] `_raise_if_reconciliation_drift()` named helper — defined as a module-level pure function in calculate.py by 03-03-T1 (R2-3: extracted so both pass and drift-raises paths can be directly unit-tested without monkeypatching)
- [x] `additional_medicare_not_modeled: bool = False` field — added to PaystubLineItem in contracts.py by 03-03-T1 (FIX B — proxy-based trigger; R2-2: tests use realistic capped SS YTD values)

*Existing `tests/test_calculate.py` already covers the 401k override; Phase 3 extends it for CALC-01/02/07/08 in 03-03-T2, including the 4-frequency-invariance test (FIX A + R2-6 adding p=26) and the reconciliation raise test (R2-3 — pytest.raises on the actual drift path). pytest is already installed — no framework install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Layer-B oracle method confirmation (over-ceiling only) | CALC-05/06 (D-01) | Online calculators (usapaycheck.org, paycheckcity.com) cannot be asserted in CI; their role is confirming over-ceiling fixtures (Thomas Bergmann ~$9,231 biweekly) only. Under-ceiling fixtures use the in-PDF wage-bracket PRIMARY oracle (no manual verification needed). | Calibration: Single/Standard/weekly/$800 → expected $54.08. Thomas Bergmann: biweekly/MFJ/standard, federal_taxable ≈ $8,492.31 → BOTH calculators must agree within ±$1. If they disagree by more than $1, the Thomas Bergmann fixture is marked @pytest.mark.skip(reason="OVER-CEILING ORACLE UNRESOLVED — high-earner withholding not independently verified"). SUMMARY.md must state "OVER-CEILING COVERAGE: UNRESOLVED" if skipped (R2-5). |
| 2026 bracket-table re-verification | CALC-05/06 | Transcribed from a live PDF on 2026-06-22; a human should spot-check ≥2 bracket rows per schedule against the live PDF before shipping | Open `irs.gov/pub/irs-pdf/p15t.pdf` p.12, confirm the MFJ-standard and Single-standard rows in `tax_tables_2026.py` match column-for-column. Also spot-check 2–3 wage-bracket cells from Deliverable 5 (pp.14–27) against the rows in the test_federal_withholding.py wage-bracket fixture to confirm the independent transcription is consistent. |

---

## Key Revisions from Codex Review (2026-06-22)

### Round 1 Fixes (confirmed in Round 2)

| Fix | Plan | Description |
|-----|------|-------------|
| FIX A | 03-03 | Leave-pay formula changed from period-proportion (invertible) to annual/2080 × leave_hours (frequency-independent). test_salaried_leave_pay_semimonthly_branch replaced by test_salaried_leave_pay_frequency_invariant. |
| FIX B | 03-03 | Additional Medicare flag trigger changed from ytd_ss_wages alone (dead code — capped at $184,500, never reaches $200k) to (ytd_ss_wages + gross) proxy. Documented as lower-bound proxy with accepted limitation. |
| FIX C | 03-03 | Reconciliation backstop changed from bare assert to raise PayrollCalculationError. |
| FIX D | 03-02 | Wave 2 → Wave 3; depends_on now includes 03-03. Eliminates the residual forward dependency. |
| FIX E | 03-02 | Whole-dollar comparison in wage-bracket cross-check: quantize(Decimal("1"), ROUND_HALF_UP) replaces Python round() (half-even). Per-step cent quantization documented as a CHOSEN engine convention. |
| FIX F | 03-02 | python-taxes structural test dropped. Engine is 2026-keyed; python-taxes ships 2023–2025. The wave-bracket PRIMARY oracle already provides structural independence. |
| FIX G | 03-02 | Bracket boundary tests added (initially via per-period wage construction — R2-4 supersedes this with direct _find_bracket() calls). |
| FIX H | 03-02 | files_modified updated; over-ceiling criterion updated (no lone-hand-trace fallback). |

### Round 2 Revisions (R2-1 through R2-8)

| Revision | Plan(s) | Description |
|----------|---------|-------------|
| R2-1 | 03-02 | Wage-bracket tolerance changed from blanket `abs(cell - published) <= 1` to EXACT EQUALITY `==` by default. ±$1 only on a SPECIFICALLY-NAMED fixture row with a documented inline extraction/rounding-anomaly reason. Reason: the IRS constructs wage-bracket cells by applying the percentage method to the interval midpoint + ROUND_HALF_UP — the same operation the test performs. A blanket ±$1 tolerance masks a real $1 transcription bug in the PRIMARY oracle, defeating independence. |
| R2-2 | 03-02, 03-03 | Additional Medicare test fixtures changed to REALISTIC capped SS YTD values. SS wages are capped at $184,500 — ytd_ss_wages CANNOT exceed the SS wage base in a real run. Fires case: ytd_ss_wages=Decimal("184500") (at the cap) + high current gross ($500/hr × 40h = $20k → proxy = $204,500 > $200k). Does-not-fire case: ytd_ss_wages=Decimal("0") + normal gross. The prior ytd_ss_wages=196000/197000 was impossible above-cap dead code. |
| R2-3 | 03-03 | Reconciliation check extracted into a NAMED PURE HELPER `_raise_if_reconciliation_drift(gross, pretax_401k, fica_ss, fica_medicare, federal_withholding, net_pay) -> None`. Called from calculate() before the return. test_reconciliation_raises_on_drift now exercises BOTH paths directly: (a) passing path — correct values do not raise; (b) drift path — pytest.raises(PayrollCalculationError) on deliberately wrong net_pay. Source grep is kept as a secondary check only. |
| R2-4 | 03-02 | Bracket boundary tests changed to call _find_bracket() DIRECTLY with adjusted-annual-wage inputs at exactly B, B-$0.01, B+$0.01. The prior approach constructing per-period wages via (B + STEP1_STANDARD) / 52 may not land on the exact annual boundary B after _money(line_1a * p) annualization rounding — the boundary test could silently test the wrong bracket. Direct _find_bracket() calls eliminate the rounding confound entirely. |
| R2-5 | 03-02 | Skipped Thomas Bergmann over-ceiling fixture now explicitly reports "OVER-CEILING ORACLE UNRESOLVED" via: (a) skip reason string "OVER-CEILING ORACLE UNRESOLVED — high-earner withholding not independently verified"; (b) SUMMARY.md line "OVER-CEILING COVERAGE: UNRESOLVED — Thomas Bergmann fixture skipped. CI passing without this fixture does NOT constitute over-ceiling verification." A skip is NOT coverage; CI going green with a skipped Thomas fixture must be visibly distinguished from verified coverage. |
| R2-6 | 03-03 | p=26 (biweekly) added to the frequency-invariance test. Round 1 added p=52/24/12; biweekly (26) is where the original inverted-formula bug was reported (4× off). The invariant now asserts delta_52 == delta_26 == delta_24 == delta_12 == Decimal("200.00"). |
| R2-7 | 03-02 | python-taxes dev dep REMOVED from Phase 3 entirely. The structural test was dropped (FIX F); installing the package with no test using it adds supply-chain/lockfile churn with zero verification value. pyproject.toml and uv.lock are removed from 03-02's files_modified. A one-line comment in test_federal_withholding.py explains the absence. |
| R2-8 | 03-02 | Wage-bracket coverage requirement updated from "at least 4 schedule columns" to "all 6 schedule columns" (MFJ Std, MFJ Chk, Single/MFS Std, Single/MFS Chk — the 4 project-relevant filing-status × checkbox combinations, plus frequency variants). Objective and acceptance criteria now agree. HoH columns are excluded (reject-guard; documented). |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (03-01-T1 → 03-01-T2 → 03-03-T1 → 03-03-T2 → 03-02-T2 — each has automated verify)
- [x] Wave 0 covers all MISSING references (the 2 new modules + new test file + synthetic fixtures + PayrollCalculationError class + _raise_if_reconciliation_drift helper + additional_medicare_not_modeled field)
- [x] python-taxes dev dep REMOVED from Wave 0 (R2-7 — no test uses it; supply-chain surface eliminated)
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter
- [x] Wave ordering consistent with depends_on: Wave 1 (03-01), Wave 2 (03-03), Wave 3 (03-02)
- [x] R2-5: over-ceiling unresolved tracking added (skip reason + SUMMARY.md requirement)
- [x] R2-6: p=26 in frequency-invariance test
- [x] R2-7: pyproject.toml + uv.lock removed from 03-02 files_modified
- [x] R2-8: "all 6 schedule columns" now consistent between objective, behavior, and acceptance criteria in 03-02

**Approval:** pending
