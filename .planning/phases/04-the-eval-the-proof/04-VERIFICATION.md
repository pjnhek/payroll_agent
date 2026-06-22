---
phase: 04-the-eval-the-proof
verified: 2026-06-22T22:00:00Z
status: passed
score: 4/4
overrides_applied: 0
re_verification: null
gaps: []
deferred: []
human_verification: []
---

# Phase 4: The Eval — The Proof — Verification Report

**Phase Goal:** A reproducible eval imports and scores the exact same production judgment functions over ~15-25 committed hand-curated fixtures, producing a legible per-category chart that proves the gated decisioning works — the credibility lever for the recruiter audience.

**Verified:** 2026-06-22T22:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | run_eval.py imports and runs the SAME production pipeline functions and scores the code-owned final_action (not the model's raw action), proving the eval tests the production path | VERIFIED | `from app.pipeline.decide import decide` at line 35 of eval/run_eval.py. PATH A feeds labeled expected extraction into reconcile/validate/decide (lines 157-160). No model_action branching anywhere. |
| 2 | ~15-25 hand-curated email+label fixtures spanning the name-resolution case taxonomy are committed; bootstrap helper named honestly; committed fixtures are source of truth | VERIFIED | 15 fixtures confirmed in eval/fixtures/ across all 9 taxonomy categories (exact, stored-alias, first-time-alias, typo, collision, unknown, missing-hours, vague-hours, buried-reply). 3 multi-employee fixtures (09, 10, 11). 7 PROCESS fixtures (above D-11 floor of 4). draft_candidate_emails.py docstring says "Throwaway bootstrap drafting aid — NOT a production generator." |
| 3 | Scoring produces extraction field accuracy, name-reconciliation accuracy (per taxonomy category), decision accuracy — broken out per category; optional secondary LLM-as-judge present | VERIFIED | summary.json contains extraction_overall_f1=0.987, extraction_overall_field_accuracy=0.989, per_category_reconciliation (6 name categories), per_category_decision (9 fixture categories), rigor_gate_struct_accuracy. eval/judge.py exists with D-16 correctness floor and tier="draft" (Kimi). |
| 4 | Eval results write to eval_results; render as one clean per-category chart; local eval is authoritative; CI scores against cached fixture outputs with NO live LLM on push | VERIFIED | eval/chart.svg committed (132KB valid SVG, 3 subplots). eval/summary.json committed with schema_version=1 and all Phase-5 required keys. eval.yml push/check job: no secrets, no ALLOW_LIVE_LLM. `--check` passes DB-free. `--db` stub skips cleanly on placeholder/absent DATABASE_URL. |

**Score:** 4/4 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `eval/fixtures/*.json` (15) | Hand-curated fixtures | VERIFIED | 15 main fixtures + 15 extraction caches = 30 JSON files. All 9 taxonomy categories covered. |
| `eval/fixtures/DIVERGENCES.md` | Documents deliberate cache divergences | VERIFIED | Table lists fixture 10 (precision miss: phantom "John Smith") and fixture 08 (field miss: guessed "40" vs null). |
| `eval/draft_candidate_emails.py` | Honest throwaway bootstrap helper | VERIFIED | Module docstring: "Throwaway bootstrap drafting aid — NOT a production generator." Uses tier="draft". Lazy imports (IN-03 fix applied). |
| `eval/run_eval.py` | Scorer with --check/--record/--chart/--db | VERIFIED | 997 lines. Imports production decide. PATH A isolation. Multiset Counter alignment. Two-level decision scoring. --check covers all metrics. --record is LIVE extraction. --db stub reads from summary.json. |
| `eval/summary.json` | Machine-readable scored output | VERIFIED | schema_version=1. All required keys present. false_process=0 (int). Both rates in confusion_matrix. 15 per_fixture entries. |
| `eval/chart.svg` | Committed recruiter-visible SVG proof | VERIFIED | 132KB valid SVG (starts with `<?xml`). 3-subplot layout. False-process headline in bold. D-13 "coverage buckets" label. Correct cell [1,2] highlighted red. |
| `tests/test_eval_wiring.py` | D-09 decide->calculate wiring smoke test | VERIFIED | Drives 12_exact_process_summit through reconcile->validate->decide->_compute_line_items. Asserts 6 golden values (gross_pay, pretax_401k, federal_withholding, fica_ss, fica_medicare, net_pay). WR-04 fix applied. |
| `.github/workflows/eval.yml` | Hermetic CI + live re-record job | VERIFIED | check job: no secrets, no ALLOW_LIVE_LLM. record job: conditional on workflow_dispatch && live_record. CR-01 fix: git-auto-commit-action commits updated caches. |
| `eval/judge.py` | Optional LLM-as-judge (D-15/D-16) | VERIFIED | Module docstring: "local-only, never runs in CI." D-16 floor at line 140: `min(raw_score, 1)`. tier="draft". Raises SystemExit without ALLOW_LIVE_LLM. No eval.yml reference. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `eval/run_eval.py` | `app.pipeline.decide` | `from app.pipeline.decide import decide` (line 35) | WIRED | Confirmed present. The DRY seam that proves eval tests production path. |
| `eval/run_eval.py` | `eval/fixtures/*_extraction.json` | `_load_extraction_cache()` reads `fixture_path.stem + "_extraction.json"` | WIRED | Lines 109-117. Both divergent caches confirmed (precision miss: fixture 10, field miss: fixture 08). |
| `tests/test_eval_wiring.py` | `app.pipeline.orchestrator._compute_line_items` | `from app.pipeline.orchestrator import _compute_line_items` (line 23) | WIRED | Makes this a wiring test, not a bare calculate() test. |
| `.github/workflows/eval.yml check job` | `eval/run_eval.py --check` | `uv run python eval/run_eval.py --check` (line 29) | WIRED | check job runs on push; no secrets in scope. |
| `eval/chart.svg` | `eval/summary.json` | `_write_svg_chart()` reads from in-memory `aggregated` which mirrors summary.json content | WIRED | Chart generated in same run as summary.json write. |
| `eval/run_eval.py _write_db_results()` | `eval/summary.json` | `SUMMARY_PATH.read_text()` at line 853 | WIRED | DB rows derived from committed file. os.environ.get("DATABASE_URL") checked before any app.config import. |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `eval/run_eval.py` (PATH A) | `decision.final_action` | `decide(expected_extracted, matches, issues)` using real production `reconcile_names`, `validate`, `decide` | Yes — production functions, no mocks | FLOWING |
| `eval/run_eval.py` (extraction) | `cached_extracted.employees` | `_load_extraction_cache()` reads committed `*_extraction.json` | Yes — real JSON files with deliberate divergences | FLOWING |
| `eval/summary.json` | All metrics | `_aggregate(fixture_results)` from 15 scored fixtures | Yes — real calculation over real fixtures | FLOWING |
| `eval/chart.svg` | Per-category bars | `aggregated["per_category_extraction"]` etc. | Yes — derived from same run that writes summary.json | FLOWING |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| --check regression gate passes DB-free | `env -u DATABASE_URL uv run python eval/run_eval.py --check` | "--check passed: no regression against committed summary.json" (exit 0) | PASS |
| D-09 wiring smoke test passes | `uv run pytest tests/test_eval_wiring.py -v` | 1 passed in 0.36s | PASS |
| Full test suite green | `uv run pytest -q` | 314 passed, 12 skipped, 1 warning | PASS |
| --db skips cleanly on placeholder | `DATABASE_URL=placeholder uv run python eval/run_eval.py --db` | "DB write skipped (DATABASE_URL unset or placeholder)" (exit 0) | PASS |
| --db skips cleanly when DATABASE_URL absent | `env -u DATABASE_URL uv run python eval/run_eval.py --db` | "DB write skipped (DATABASE_URL unset or placeholder)" (exit 0) | PASS |
| chart.svg is valid SVG | `head -c 50 eval/chart.svg` | `<?xml version="1.0" encoding="utf-8"` | PASS |
| DRY seam present | `grep "from app.pipeline.decide import decide" eval/run_eval.py` | Line 35 confirmed | PASS |
| No matplotlib at module level | `grep -nE "^import matplotlib\|^from matplotlib" eval/run_eval.py` | No matches (matplotlib only inside `_write_svg_chart`) | PASS |
| No top-level app.config import | `grep -nE "^from app.config\|^import app.config" eval/run_eval.py` | No matches | PASS |

---

## Probe Execution

No conventional `scripts/*/tests/probe-*.sh` probes defined. The eval regression gate (`uv run python eval/run_eval.py --check`) serves as the phase probe and passes (verified above in spot-checks).

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| EVAL-01 | 04-01 | Throwaway bootstrap helper named honestly as drafting aid | SATISFIED | eval/draft_candidate_emails.py docstring: "Throwaway bootstrap drafting aid — NOT a production generator." Kimi draft tier. allow_live_llm gate. Lazy imports (IN-03 fix). |
| EVAL-02 | 04-01 | ~15-25 hand-curated fixtures spanning all category taxonomy | SATISFIED | 15 fixtures committed. All 9 categories. 7 PROCESS fixtures. 3 multi-employee. 30 total JSON files (15 + 15 caches). DIVERGENCES.md documents 2 deliberate cache divergences. |
| EVAL-03 | 04-02 | run_eval.py imports SAME production functions; scores code-owned final_action | SATISFIED | `from app.pipeline.decide import decide` at module level. PATH A uses labeled expected extraction through reconcile/validate/decide. No model_action branching. --check exits 0. |
| EVAL-04 | 04-03, 04-04 | Extraction field accuracy, name-reconciliation accuracy, decision accuracy per category; optional LLM-as-judge | SATISFIED | summary.json has extraction_overall_field_accuracy=0.989, extraction_overall_f1=0.987, per_category_reconciliation (6 cats), per_category_decision (9 cats). chart.svg shows all three metrics. eval/judge.py provides optional LLM-as-judge with D-16 correctness floor. |
| EVAL-05 | 04-03, 04-04 | Results write to eval_results; render on chart; CI hermetic; manual-dispatch live eval | SATISFIED | eval/chart.svg committed (valid SVG). eval/summary.json committed. eval.yml: check job hermetic (no secrets, no live LLM on push); record job workflow_dispatch only with EXTRACTION_API_KEY. --db stub skips on placeholder (wired, not live). CR-01 fix: git-auto-commit in record job so live re-record is durable. |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | — | No TBD/FIXME/XXX/PLACEHOLDER markers in phase-modified files | — | — |

Scanned: eval/run_eval.py, eval/judge.py, eval/draft_candidate_emails.py, tests/test_eval_wiring.py, .github/workflows/eval.yml, pyproject.toml.

All 8 code review findings (CR-01, WR-01..04, IN-01..03) confirmed resolved in commit 744a203:
- CR-01: eval.yml record job now has `stefanzweifel/git-auto-commit-action@v5` commit step
- WR-01: gate_reasons_contains uses per-reason `any(s in reason ...)` not joined string
- WR-02: judge.py exception handling narrowed to `(json.JSONDecodeError, KeyError)` + logged fallback
- WR-03: numpy explicitly declared in pyproject.toml dev group (`numpy>=1.26.0`)
- WR-04: test_eval_wiring.py asserts fica_medicare=133.85 and net_pay=7439.87
- IN-01: redundant `import uuid as _uuid` removed; module-level `uuid` used
- IN-02: seed.py docstring updated to "7 employees"
- IN-03: draft_candidate_emails.py imports moved inside functions (lazy)

---

## Human Verification Required

None. All must-haves are verified programmatically. The chart's visual legibility for a recruiter audience is subjective but the chart is a committed, renderable SVG file with labeled bars, a confusion matrix, and a bold false-process headline — the structural requirements are met in code.

---

## Gaps Summary

No gaps. All four must-have truths verified, all eight plan artifacts substantively wired, all five requirements (EVAL-01..05) satisfied, full test suite green (314 passed), eval --check passes DB-free, and all code review findings confirmed resolved.

---

_Verified: 2026-06-22T22:00:00Z_
_Verifier: Claude (gsd-verifier)_
