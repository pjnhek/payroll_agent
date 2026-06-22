---
phase: 3
slug: harden-the-calc
status: draft
nyquist_compliant: false
wave_0_complete: false
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

> Filled by the planner against the final task IDs. Phase 3 has no threat model (pure offline arithmetic — see RESEARCH.md §Security Domain), so Threat Ref is "—" throughout.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 3-01-xx | 01 | 1 | CALC-06 | — | N/A (offline calc) | unit | `uv run pytest tests/test_federal_withholding.py -q` | ❌ W0 | ⬜ pending |
| 3-0x-xx | 0x | 1 | CALC-05 | — | N/A | golden | `uv run pytest tests/test_federal_withholding.py -q` | ❌ W0 | ⬜ pending |
| 3-0x-xx | 0x | 2 | CALC-01/02/03/04/07 | — | N/A | unit/golden | `uv run pytest tests/test_calculate.py -q` | ✅ | ⬜ pending |
| 3-0x-xx | 0x | 2 | CALC-08 | — | N/A | unit | `uv run pytest tests/test_calculate.py -k reconciliation -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_federal_withholding.py` — NEW golden-value suite (covers CALC-01/02/03/04/05/06); the most-tested unit in the repo
- [ ] `app/pipeline/federal_withholding.py` — NEW Worksheet 1A engine module (the unit under test)
- [ ] `app/pipeline/tax_tables_2026.py` — NEW dated year-keyed constants module
- [ ] `tests/fixtures/` (or inline) — synthetic Employee fixtures for the matrix cells the seed does not cover (MFJ + Step-2 checkbox; semi-monthly/monthly frequencies)
- [ ] `uv add --dev python-taxes` — structural cross-check oracle (2023–2025; NEVER for 2026 numbers — structure independence only)

*Existing `tests/test_calculate.py` already covers the 401k override; Phase 3 extends it for CALC-01/02/07/08. pytest is already installed — no framework install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Layer-B oracle method confirmation | CALC-06 (D-01) | Online calculators (usapaycheck.org, paycheckcity.com) cannot be asserted in CI; their "percentage-method vs annual-liability" mode must be confirmed by a human against a known input BEFORE any golden value derived from them is trusted | For one known input (e.g. Single/Standard/weekly/$800 → hand-computed $54.08 in RESEARCH.md §Hand-Computation), confirm each calculator returns the same figure in IRS-percentage-method mode; record the confirmation + retrieval date in the test module docstring. Treat a mismatch as a method-delta to investigate, NOT a code bug. |
| 2026 bracket-table re-verification | CALC-05/06 | Transcribed from a live PDF on 2026-06-22; a human should spot-check ≥2 bracket rows per schedule against the live PDF before shipping | Open `irs.gov/pub/irs-pdf/p15t.pdf` p.12, confirm the MFJ-standard and Single-standard rows in `tax_tables_2026.py` match column-for-column |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (the 2 new modules + new test file + synthetic fixtures + python-taxes dev dep)
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
