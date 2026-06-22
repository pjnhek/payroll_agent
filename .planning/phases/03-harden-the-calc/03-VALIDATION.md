---
phase: 3
slug: harden-the-calc
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-22
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

> Filled with final task IDs from the revised Phase 3 plans. Phase 3 is pure offline arithmetic (see RESEARCH.md §Security Domain), so Threat Ref is "—" throughout.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-T1 | 01 | 1 | CALC-06 | — | N/A (offline calc) | unit | `uv run python -c "from app.pipeline.tax_tables_2026 import TAX_YEAR; print('OK')"` | ❌ W0 creates | ⬜ pending |
| 03-01-T2 | 01 | 1 | CALC-05 | — | N/A | unit | `uv run python -c "from app.pipeline.federal_withholding import federal_withholding_2026; print('OK')"` | ❌ W0 creates | ⬜ pending |
| 03-02-CKP | 02 | 2 | CALC-05/06 (D-01) | — | N/A (human gate) | human-verify | Manual: usapaycheck.org + paycheckcity.com calibration + Thomas Bergmann over-ceiling | N/A | ⬜ pending |
| 03-02-T2 | 02 | 2 | CALC-03/04/05/06 | — | N/A | golden + wage-bracket | `uv run pytest tests/test_federal_withholding.py -q` | ❌ W0 creates | ⬜ pending |
| 03-03-T1 | 03 | 2 | CALC-01/02/03/04/07/08 | — | N/A | unit | `uv run pytest tests/test_calculate.py -q` | ✅ (extended) | ⬜ pending |
| 03-03-T2 | 03 | 2 | CALC-01/02/07/08 | — | N/A | unit | `uv run pytest tests/test_calculate.py -q` | ✅ (extended) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_federal_withholding.py` — NEW golden-value suite (covers CALC-03/04/05/06); created by 03-02-T2
- [x] `app/pipeline/federal_withholding.py` — NEW Worksheet 1A engine module; created by 03-01-T2
- [x] `app/pipeline/tax_tables_2026.py` — NEW dated year-keyed constants module; created by 03-01-T1
- [x] Synthetic Employee fixtures — constructed inline in test_federal_withholding.py via _make_employee() helper (no separate fixtures/ dir needed)
- [x] `uv add --dev python-taxes` — structural cross-check oracle (2023–2025; NEVER for 2026 numbers — TERTIARY structural sanity only per User Decision 2); installed at start of 03-02-T2

*Existing `tests/test_calculate.py` already covers the 401k override; Phase 3 extends it for CALC-01/02/07/08 in 03-03-T2. pytest is already installed — no framework install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Layer-B oracle method confirmation (over-ceiling only) | CALC-05/06 (D-01) | Online calculators (usapaycheck.org, paycheckcity.com) cannot be asserted in CI; their role is confirming over-ceiling fixtures (Thomas Bergmann ~$9,231 biweekly) only. Under-ceiling fixtures use the in-PDF wage-bracket PRIMARY oracle (no manual verification needed). | Calibration: Single/Standard/weekly/$800 → expected $54.08. Thomas Bergmann: biweekly/MFJ/standard, federal_taxable ≈ $8,492.31 → confirm both calculators agree (within ±$1). Disagreement > $1 triggers the Fix-3 escalation path (re-examine transcription + confirm 2026 tables in the calculator). |
| 2026 bracket-table re-verification | CALC-05/06 | Transcribed from a live PDF on 2026-06-22; a human should spot-check ≥2 bracket rows per schedule against the live PDF before shipping | Open `irs.gov/pub/irs-pdf/p15t.pdf` p.12, confirm the MFJ-standard and Single-standard rows in `tax_tables_2026.py` match column-for-column. Also spot-check 2–3 wage-bracket cells from Deliverable 5 (pp.14–27) against the rows in the test_federal_withholding.py wage-bracket fixture to confirm the independent transcription is consistent. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (03-01-T1 → 03-01-T2 → 03-02-T2 → 03-03-T1 → 03-03-T2 — each has automated verify)
- [x] Wave 0 covers all MISSING references (the 2 new modules + new test file + synthetic fixtures + python-taxes dev dep)
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
