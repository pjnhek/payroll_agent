---
phase: 04-the-eval-the-proof
plan: "02"
subsystem: eval
tags: [eval, scorer, decision-accuracy, extraction-f1, reconciliation, confusion-matrix, tdd]

requires:
  - phase: 04-the-eval-the-proof
    plan: "01"
    provides: "15 hand-labeled fixtures + 15 stubbed _extraction.json caches in eval/fixtures/"
  - phase: 02.1-deterministic-decisioning
    provides: "reconcile_names + decide as pure deterministic code"
  - phase: 03-harden-the-calc
    provides: "calculate() with Phase-3 golden values (Thomas Bergmann penny-exact)"

provides:
  - "eval/run_eval.py — scorer with --check regression gate + --record LIVE extraction, summary.json writer"
  - "eval/summary.json — committed scored output (15 fixtures, schema_version=1)"
  - "tests/test_eval_wiring.py — D-09 decide->calculate WIRING smoke test: fixture->reconcile/validate/decide->_compute_line_items == Phase-3 golden"

affects:
  - "04-03 (chart emitter reads summary.json produced here)"
  - "04-04 (CI workflow runs run_eval.py --check over committed summary.json)"

tech-stack:
  added: []
  patterns:
    - "DB-free eval: no app.config import on scoring/--check paths; model ID from EXTRACTION_MODEL env var"
    - "PATH A isolation (D-07): labeled expected extraction feeds deterministic stages, cache feeds extraction scoring only"
    - "Multiset Counter alignment for extraction F1 so duplicate extracted employees count as false positives (D-06)"
    - "Two-level decision scoring: action_correct + gate_struct_ok (D-10)"
    - "Confusion matrix: false_process_count as HEADLINE int, two rates (primary risk + secondary precision) clearly distinguished (D-11)"
    - "Per-NAME reconciliation with matched_employee_id enforcement: wrong-but-real match is FAIL (D-02, D-03)"
    - "Lazy imports for --record path: extract/llm_client imported inside _record_extraction() only (T-04-07)"
    - "D-09 wiring test: production _compute_line_items imported (not reimplemented) to prove the decide->calculate join"

key-files:
  created:
    - "tests/test_eval_wiring.py"
    - "eval/run_eval.py"
    - "eval/summary.json"
  modified: []

key-decisions:
  - "PATH A (labeled extraction) always feeds deterministic stages; CACHE feeds extraction scoring only -- the thesis is unconfounded by extraction noise (D-07)"
  - "false_process_count=0 is the headline integer; two rates (risk + precision-style) distinguished in summary.json and --check coverage to prevent confusion-matrix framing (D-11, D-12)"
  - "No matplotlib in run_eval.py; chart emission belongs in 04-03 only"
  - "suite_run_id generated once in main() and threaded into _write_summary_json() so 04-04 can reuse the same id for DB write"
  - "Reconciliation correctness enforces matched_employee_id equality against the labeled intended employee (D-02); a wrong-but-real match fails"

metrics:
  duration: 18min
  completed: 2026-06-22
  tasks: 2 / 2
  files_modified: 3
---

# Phase 04 Plan 02: Eval Scorer (run_eval.py + D-09 Wiring Test) Summary

**eval/run_eval.py scores 15 fixtures DB-free: extraction F1=0.987/field_accuracy=0.989, perfect per-NAME reconciliation (all categories 100%), 0 false_process decisions (7/7 PROCESS correct, 8/8 CLARIFY correct) with committed summary.json and --check regression gate.**

## Performance

- **Duration:** 18 min
- **Started:** 2026-06-22T20:20:00Z
- **Completed:** 2026-06-22T20:38:00Z
- **Tasks:** 2 / 2
- **Files modified:** 3

## Accomplishments

### Task 1: D-09 decide->calculate WIRING smoke test (tests/test_eval_wiring.py)

Created `tests/test_eval_wiring.py` with one test: `test_decide_to_calculate_wiring_thomas_bergmann`. The test drives the `12_exact_process_summit` fixture through the FULL production spine -- `reconcile_names -> validate -> decide -> _compute_line_items` -- and asserts the Thomas Bergmann paystub equals the Phase-3 golden values penny-exact:

- `gross_pay = Decimal("9230.77")`
- `pretax_401k = Decimal("738.46")`
- `federal_withholding = Decimal("881.39")`
- `fica_ss = Decimal("37.20")`

This closes the gap between the eval (which otherwise stops at `decide`) and the "computes payroll" headline without building a second net_pay oracle. It imports the production `_compute_line_items` (the decide->calculate join) -- NOT a bare `calculate()` call.

### Task 2: eval/run_eval.py -- core scorer with --check and --record

Created `eval/run_eval.py` as a standalone executable scorer. Key design choices:

**DB-free by design:** No `app.config` import on the scoring/`--check` paths. `_extraction_model_id()` reads `EXTRACTION_MODEL` env var directly. Only `_require_live_llm()` (the `--record` gate) imports `app.config` lazily. `env -u DATABASE_URL uv run python eval/run_eval.py` exits 0.

**PATH A isolation (D-07):** `_expected_to_extracted()` builds the labeled expected extraction; only this feeds `reconcile_names -> validate -> decide`. The committed cache feeds extraction scoring ONLY -- the deterministic thesis is unconfounded by extraction noise.

**Extraction F1 with multiset alignment (D-06):** `Counter` alignment so a duplicate extracted employee counts as a false positive (not collapsed). Overall F1=0.987 (the 2 deliberate cache divergences from 04-01 are visible: fixture 10 phantom employee drops "exact" category F1; fixture 08 wrong hours drops "vague-hours" field_accuracy to 0.833).

**Per-NAME reconciliation (D-03, D-02):** Scored against PATH A matches. `matched_employee_id` must equal the labeled intended employee id -- a wrong-but-real match fails. All categories score 100% correct (11/11 exact, 2/2 stored-alias, 2/2 collision, 1/1 unknown, 2/2 typo, 1/1 first-time-alias).

**Two-level decision (D-10) + confusion matrix (D-11):** `action_correct` + `gate_struct_ok` (gate_reasons/unresolved_names/missing_fields set-match). Confusion matrix: `false_process=0` (HEADLINE -- the asymmetric risk number), `true_process=7`, `true_clarify=8`, `false_clarify=0`. Both `false_process_rate` and `false_process_precision_rate` in `summary.json` to prevent the precision-style rate from masquerading as the risk number.

**--check covers ALL metrics (D-17):** Compares parsed+rounded values for all four confusion counts, both rates, F1, field_accuracy, per-category extraction/reconciliation/decision, and `rigor_gate_struct_accuracy`. No metric subset can regress past CI.

**--record is LIVE extraction (D-05):** `_record_extraction()` imports `extract` and `llm_client` lazily (inside the function only, keeps them off the scoring path). Calls the production `extract(email, roster, run_id=run_id, llm=llm_client)` once per fixture and overwrites the `*_extraction.json` caches.

## Scored Metrics (committed eval/summary.json)

| Metric | Value |
|--------|-------|
| Extraction overall F1 | 0.9867 |
| Extraction overall field_accuracy | 0.9889 |
| Decision false_process count | 0 (HEADLINE) |
| Decision false_process_rate | 0.0000 |
| Decision false_process_precision_rate | 0.0000 |
| Rigor gate_struct_accuracy | 1.0000 |

## Task Commits

1. **Task 1: D-09 wiring smoke test** - `70e784a` (test)
2. **Task 2: eval/run_eval.py scorer + summary.json** - `f9d4402` (feat)

## Files Created

- `tests/test_eval_wiring.py` -- D-09 wiring smoke test (109 lines)
- `eval/run_eval.py` -- core scorer, --check gate, --record live extraction (369 lines)
- `eval/summary.json` -- committed scored output (schema_version=1, 15 fixtures)

## Deviations from Plan

None -- plan executed exactly as written.

- PATH A isolation implemented exactly per D-07
- Multiset Counter alignment for extraction precision/recall (D-06)
- `matched_employee_id` enforcement in reconciliation (D-02)
- Both rates (risk + precision) in confusion_matrix (D-11)
- Lazy imports for `--record` path (T-04-07)
- No matplotlib in run_eval.py
- `_compute_line_items` imported directly (not reimplemented) for D-09

## Known Stubs

None. `eval/run_eval.py` produces real scored metrics over real pipeline stages. `eval/summary.json` contains real scores. No placeholder values that prevent the plan's goal.

## Threat Flags

No new threat surface beyond what is documented in the plan's threat model (T-04-04 through T-04-SC). The one `os.environ.get("EXTRACTION_MODEL", ...)` call reads only the model ID string, not a secret; this is the deliberate DB-free design (T-04-07).

## Self-Check

- [x] tests/test_eval_wiring.py exists
- [x] eval/run_eval.py exists
- [x] eval/summary.json exists
- [x] Commit 70e784a exists (Task 1)
- [x] Commit f9d4402 exists (Task 2)
- [x] `uv run pytest tests/test_eval_wiring.py -v` exits 0 (PASSED)
- [x] `env -u DATABASE_URL uv run python eval/run_eval.py` exits 0 and writes summary.json
- [x] `env -u DATABASE_URL uv run python eval/run_eval.py --check` exits 0 with "--check passed"
- [x] `grep "from app.pipeline.decide import decide" eval/run_eval.py` returns the import line
- [x] No matplotlib in run_eval.py (AST verified)
- [x] No top-level app.config import in run_eval.py
- [x] summary.json has all required keys including both false_process_rate and false_process_precision_rate
- [x] confusion_matrix.false_process is int 0 (the headline count)
- [x] No stubs in created files

## Self-Check: PASSED
