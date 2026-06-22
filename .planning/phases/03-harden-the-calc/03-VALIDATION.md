---
phase: 3
slug: harden-the-calc
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-22
revised: 2026-06-22
revision_reason: "FIX D (Codex review): 03-02 moved from wave 2 to wave 3 (depends on 03-03). 03-02 calls calculate() for the 401k-base and Additional Medicare flag cases — those require 03-03 to be complete first. FIX A: 03-03 Task 2 now includes the frequency-invariance test (FIX A regression guard) replacing the semi-monthly-branch test. FIX C: reconciliation guard updated from assert to PayrollCalculationError raise."
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

> Filled with final task IDs from the revised Phase 3 plans.
> **FIX D (Codex review):** 03-02 is now wave 3 (depends on 03-01 AND 03-03) because 03-02's Task 2 calls calculate() for the 401k-base and Additional Medicare flag cases — those behaviors are implemented in 03-03.
> Phase 3 is pure offline arithmetic (see RESEARCH.md §Security Domain), so Threat Ref is "—" throughout.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-T1 | 01 | 1 | CALC-06 | — | N/A (offline calc) | unit | `uv run python -c "from app.pipeline.tax_tables_2026 import TAX_YEAR; print('OK')"` | ❌ W0 creates | ⬜ pending |
| 03-01-T2 | 01 | 1 | CALC-05 | — | N/A | unit | `uv run python -c "from app.pipeline.federal_withholding import federal_withholding_2026; print('OK')"` | ❌ W0 creates | ⬜ pending |
| 03-03-T1 | 03 | 2 | CALC-01/02/03/04/07/08 | — | N/A | unit | `uv run pytest tests/test_calculate.py -q` | ✅ (extended) | ⬜ pending |
| 03-03-T2 | 03 | 2 | CALC-01/02/07/08 | — | N/A | unit + FIX A invariance | `uv run pytest tests/test_calculate.py -q` | ✅ (extended) | ⬜ pending |
| 03-02-CKP | 02 | 3 | CALC-05/06 (D-01) | — | N/A (human gate) | human-verify | Manual: usapaycheck.org + paycheckcity.com calibration + Thomas Bergmann over-ceiling (two-calculator agreement required) | N/A | ⬜ pending |
| 03-02-T2 | 02 | 3 | CALC-03/04/05/06 | — | N/A | golden + wage-bracket + boundary | `uv run pytest tests/test_federal_withholding.py -q` | ❌ W0 creates | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Execution Wave Order

```
Wave 1: 03-01 (tax_tables_2026.py + federal_withholding.py)
Wave 2: 03-03 (calculate.py deepening + contracts.py + test_calculate.py extension)
Wave 3: 03-02 (test_federal_withholding.py golden suite — depends on 03-01 AND 03-03)
```

**Why 03-03 before 03-02 (FIX D):**
03-02's Task 2 calls `calculate()` for the 401k-base-split case (CALC-03), the Step-4b FICA-base assertion (Fix 7b), and the Additional Medicare flag test (User Decision 1, FIX B). All of these behaviors — `PaystubLineItem.additional_medicare_not_modeled`, the deepened `calculate()` function, and the `PayrollCalculationError` class — are implemented in 03-03. Running 03-02 before 03-03 would require either (a) forward references to unshipped code, or (b) removing calculate() integration cases from 03-02 and pushing them to 03-03 (which is where they now live, per Fix 9). The cleaner solution is wave ordering: 03-03 ships first, then 03-02 can import and test the complete calculate() without any forward dependency.

---

## Wave 0 Requirements

- [x] `tests/test_federal_withholding.py` — NEW golden-value suite (covers CALC-03/04/05/06); created by 03-02-T2
- [x] `app/pipeline/federal_withholding.py` — NEW Worksheet 1A engine module; created by 03-01-T2
- [x] `app/pipeline/tax_tables_2026.py` — NEW dated year-keyed constants module; created by 03-01-T1
- [x] Synthetic Employee fixtures — constructed inline in test_federal_withholding.py via _make_employee() helper (no separate fixtures/ dir needed)
- [x] `uv add --dev python-taxes` — dev dep, audited (PyPI, MIT); installed at start of 03-02-T2 but NOT used in a structural test (FIX F — engine is 2026-keyed; python-taxes ships 2023–2025; independence for 2026 fixtures is already provided by the wage-bracket PRIMARY oracle)
- [x] `PayrollCalculationError` exception class — defined in calculate.py by 03-03-T1 (FIX C — replaces bare assert that is stripped by python -O)
- [x] `additional_medicare_not_modeled: bool = False` field — added to PaystubLineItem in contracts.py by 03-03-T1 (FIX B — proxy-based trigger)

*Existing `tests/test_calculate.py` already covers the 401k override; Phase 3 extends it for CALC-01/02/07/08 in 03-03-T2, including the frequency-invariance test (FIX A regression guard). pytest is already installed — no framework install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Layer-B oracle method confirmation (over-ceiling only) | CALC-05/06 (D-01) | Online calculators (usapaycheck.org, paycheckcity.com) cannot be asserted in CI; their role is confirming over-ceiling fixtures (Thomas Bergmann ~$9,231 biweekly) only. Under-ceiling fixtures use the in-PDF wage-bracket PRIMARY oracle (no manual verification needed). | Calibration: Single/Standard/weekly/$800 → expected $54.08. Thomas Bergmann: biweekly/MFJ/standard, federal_taxable ≈ $8,492.31 → BOTH calculators must agree within ±$1. If they disagree by more than $1, the Thomas Bergmann fixture is marked @pytest.mark.skip — no lone-hand-trace fallback (FIX: removes prior "hand trace authoritative if calculators disagree" language). |
| 2026 bracket-table re-verification | CALC-05/06 | Transcribed from a live PDF on 2026-06-22; a human should spot-check ≥2 bracket rows per schedule against the live PDF before shipping | Open `irs.gov/pub/irs-pdf/p15t.pdf` p.12, confirm the MFJ-standard and Single-standard rows in `tax_tables_2026.py` match column-for-column. Also spot-check 2–3 wage-bracket cells from Deliverable 5 (pp.14–27) against the rows in the test_federal_withholding.py wage-bracket fixture to confirm the independent transcription is consistent. |

---

## Key Revisions from Codex Review (2026-06-22)

| Fix | Plan | Description |
|-----|------|-------------|
| FIX A | 03-03 | Leave-pay formula changed from period-proportion (invertible) to annual/2080 × leave_hours (frequency-independent). test_salaried_leave_pay_semimonthly_branch replaced by test_salaried_leave_pay_frequency_invariant asserting delta is identical at p=52, p=24, p=12 and equals Decimal("200.00") for a $52k employee with 8 leave hours. |
| FIX B | 03-03 | Additional Medicare flag trigger changed from ytd_ss_wages alone (dead code — capped at $184,500, never reaches $200k) to (ytd_ss_wages + gross) proxy. Documented as lower-bound proxy with accepted limitation. |
| FIX C | 03-03 | Reconciliation backstop changed from bare assert (stripped by python -O) to raise PayrollCalculationError. test_reconciliation_raises_on_drift confirms no bare assert in source. |
| FIX D | 03-02 | Wave 2 → Wave 3; depends_on now includes 03-03. Eliminates the residual forward dependency where 03-02 referenced calculate() behaviors not yet shipped by 03-03. |
| FIX E | 03-02 | Whole-dollar comparison in wage-bracket cross-check: quantize(Decimal("1"), ROUND_HALF_UP) replaces Python round() (half-even). Per-step cent quantization documented as a CHOSEN engine convention, not IRS-mandated. |
| FIX F | 03-02 | python-taxes structural test dropped. Engine is 2026-keyed; python-taxes ships 2023–2025. The wage-bracket PRIMARY oracle already provides the structural independence. python-taxes is still installed as a dev dep but no test references it; a comment explains the absence. |
| FIX G | 03-02 | Bracket boundary tests added: exact lower bound, upper-bound minus $0.01, and exact upper bound for at least one schedule. Catches >= vs > regressions in _find_bracket() that midpoint sweeps miss. |
| FIX H | 03-02 | files_modified updated: pyproject.toml, uv.lock, README.md added. Over-ceiling criterion updated: both calculators must agree or fixture is skipped (no lone-hand-trace fallback). |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (03-01-T1 → 03-01-T2 → 03-03-T1 → 03-03-T2 → 03-02-T2 — each has automated verify)
- [x] Wave 0 covers all MISSING references (the 2 new modules + new test file + synthetic fixtures + python-taxes dev dep + PayrollCalculationError class + additional_medicare_not_modeled field)
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter
- [x] Wave ordering consistent with depends_on: Wave 1 (03-01), Wave 2 (03-03), Wave 3 (03-02)

**Approval:** pending
