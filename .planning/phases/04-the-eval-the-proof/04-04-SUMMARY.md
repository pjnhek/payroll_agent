---
phase: 04-the-eval-the-proof
plan: "04"
subsystem: eval
tags: [eval, db-write, llm-judge, judge, optional, if-time, D-14, D-15, D-16]

requires:
  - phase: 04-the-eval-the-proof
    plan: "03"
    provides: "eval/run_eval.py with --check gate + eval/summary.json committed output"

provides:
  - "eval/run_eval.py (modified): _write_db_results() + --db flag -- optional DB write from summary.json"
  - "eval/judge.py -- optional LLM-as-judge email quality scorer (D-15/D-16), local-only, never CI"

affects:
  - "Phase 5 DASH-04 (eval_results rows written by --db feed the dashboard eval view)"

tech-stack:
  added: []
  patterns:
    - "os.environ.get('DATABASE_URL') checked BEFORE any app.config import to avoid required-field fail-fast"
    - "psycopg imported inside _write_db_results() only -- keeps it off scoring/--check path"
    - "ALLOW_LIVE_LLM checked via os.environ in judge_draft() -- same fail-fast avoidance pattern"
    - "D-16 correctness floor: wrong real employee in draft caps score at 1 (deterministic post-LLM check)"
    - "Summary.json is authoritative: _write_db_results reads SUMMARY_PATH.read_text(), not in-memory state"

key-files:
  created:
    - "eval/judge.py -- standalone LLM-as-judge scorer (263 lines, local-only)"
  modified:
    - "eval/run_eval.py -- _write_db_results() + --db flag added (97 new lines)"
    - "eval/summary.json -- regenerated (scores unchanged, new suite_run_id)"

key-decisions:
  - "os.environ.get('DATABASE_URL') read before app.config import to avoid ValidationError fail-fast (Codex R4 LOW fix)"
  - "ALLOW_LIVE_LLM checked via os.environ in judge_draft() for same reason -- app.config requires DATABASE_URL"
  - "_write_db_results() derives ALL rows from eval/summary.json (SUMMARY_PATH.read_text()); not in-memory state"
  - "judge_draft() uses tier='draft' (Kimi), NOT tier='extraction' (DeepSeek) per D-15 and anti-leakage D-19"
  - "D-16 floor: min(raw_score, 1) applied deterministically after LLM response -- LLM cannot reward confident-wrong"

metrics:
  duration: 22min
  completed: 2026-06-22
  tasks: 2 / 2
  files_modified: 3
---

# Phase 04 Plan 04: Optional DB Write Stub + LLM-as-Judge Summary

**D-14 DB write stub skips cleanly on placeholder/absent DATABASE_URL (os.environ checked before app.config); D-15/D-16 LLM judge is local-only standalone script with correctness floor, never referenced in CI.**

## Performance

- **Duration:** 22 min
- **Started:** 2026-06-22T21:10:00Z
- **Completed:** 2026-06-22T21:32:00Z
- **Tasks:** 2 / 2
- **Files modified:** 3

## Accomplishments

### Task 1: D-14 DB write stub -- _write_db_results() + --db flag (eval/run_eval.py)

Added `_write_db_results()` to `eval/run_eval.py` and a `--db` argparse flag. Key design:

**os.environ-first pattern (Codex R4 LOW fix):** `_write_db_results()` reads `os.environ.get("DATABASE_URL")` BEFORE any `app.config` import. `Settings.database_url` is a REQUIRED field with no default; calling `get_settings()` when `DATABASE_URL` is absent raises `ValidationError` -- the "skip silently" path would crash. Reading `os.environ` avoids that entirely.

**Skip cases:** When `DATABASE_URL` is absent (empty/unset) OR equals the literal `"placeholder"` (the CI/dev sentinel), the function prints "DB write skipped (DATABASE_URL unset or placeholder)" and returns cleanly (exit 0). Only a real DSN proceeds.

**summary.json as authoritative source:** `_write_db_results()` reads `SUMMARY_PATH.read_text()` (the committed `eval/summary.json`) -- NOT in-memory `fixture_results`/`aggregated` state. This guarantees the DB rows and the published artifact carry the identical `suite_run_id` and metric values by construction.

**5 metrics per fixture inserted:** `extraction_f1`, `extraction_field_accuracy`, `reconciliation_accuracy` (derived scalar from the reconciliation list), `decision_action_correct`, `decision_gate_struct_ok`. Uses `schema.sql:144` column names (`suite_run_id`, `fixture_id`, `metric_name`, `value`, `details`). psycopg imported inside function only.

**--db not added to eval.yml** -- DB write is local/dev only. Regression gate unaffected.

### Task 2: D-15/D-16 LLM-as-judge email quality scorer -- eval/judge.py

Created `eval/judge.py` as a **standalone local-only script**. Key design:

**Module docstring** explicitly states: "local-only, never runs in CI, first to drop under time pressure." No `eval.yml` reference anywhere in the file.

**ALLOW_LIVE_LLM gate (os.environ pattern):** `judge_draft()` checks `os.environ.get("ALLOW_LIVE_LLM")` before any `app.config` import -- avoids the `Settings.database_url` required-field fail-fast. Raises `SystemExit` with a clear message if the flag is not set.

**call_text(tier="draft"):** Uses the Kimi draft tier (not DeepSeek extraction tier), per D-15 and the D-19 anti-leakage rule. Temperature 0.3 (slightly warmer than extraction but constrained for reproducibility).

**RUBRIC constant:** One-line 1-5 scale with 3 calibration anchors: `1=generic/names no specific employee; 3=names the suggested employee and asks the precise question; 5=specific+warm+actionable`. Correctness floor instruction baked into the rubric prompt.

**D-16 correctness floor (deterministic post-LLM check):** After getting a raw score, `judge_draft()` loads all roster `full_name` values via `seed(dry_run=True)`, checks if any name OTHER than the expected employee appears (case-insensitive) in the draft text, and applies `final_score = min(raw_score, 1)` if so. This ensures a warm, specific email confidently naming the WRONG employee cannot escape a low score -- "confident-LLM-wrongness" is exactly what the architecture exists to prevent.

**Standalone __main__:** Scores `*_draft.txt` files from `eval/drafts/`, prints a results table. No CI integration. Not called from `run_eval.py`. 

## Task Commits

1. **Task 1: D-14 DB write stub** - `ada4f23` (feat)
2. **Task 2: D-15/D-16 LLM judge** - `d728e6e` (feat)

## Files Created/Modified

- `eval/judge.py` -- standalone LLM-as-judge scorer (263 lines)
- `eval/run_eval.py` -- `_write_db_results()` + `--db` flag (97 new lines)
- `eval/summary.json` -- regenerated (unchanged metric scores, new suite_run_id)

## Decisions Made

- Read `os.environ.get("DATABASE_URL")` and `os.environ.get("ALLOW_LIVE_LLM")` BEFORE any `app.config` import in both new functions. `Settings.database_url` is a REQUIRED field; `get_settings()` raises `ValidationError` when the key is absent. The "skip" paths would otherwise crash on startup in a CI/dev environment without a real DSN. This pattern is consistent with D-14's Codex R4 LOW fix specification.
- `judge_draft()` does NOT import `app.config` at all for the gate check -- `os.environ` is authoritative for the allow flag. The `get_settings()` call is only reached if `ALLOW_LIVE_LLM=true`, at which point a real `DATABASE_URL` is expected to be set as well.
- D-16 floor applies a deterministic post-LLM clamp rather than modifying the prompt to "always give wrong employees a 1" -- the floor is audit-visible in the returned `floor_applied` field.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed app.config fail-fast in judge_draft() gate check**
- **Found during:** Task 2 verification
- **Issue:** `judge_draft()` initially called `get_settings()` to check `allow_live_llm`. `Settings.database_url` is a REQUIRED field with no default; when `DATABASE_URL` is absent (test environment), `get_settings()` raised `ValidationError` instead of `SystemExit`. The plan's verification test `except SystemExit` clause caught the validation error as a different exception type, failing the test.
- **Fix:** Changed gate check to read `os.environ.get("ALLOW_LIVE_LLM")` directly, consistent with the D-14 Codex R4 LOW fix pattern. `allow_live_llm` is a boolean env var that can be read without `app.config`; only the live-call path (after the gate passes) needs the full settings object.
- **Files modified:** `eval/judge.py`
- **Commit:** d728e6e (included in Task 2 commit)

## Known Stubs

None. Both deliverables are functional:
- `_write_db_results()` is a real DB write stub (D-14 explicitly calls it a "stub acceptable" item; the skip path is by design, not a placeholder)
- `eval/judge.py` is a real runnable scorer with correctness floor logic (untested live since ALLOW_LIVE_LLM is not set, which is expected)

## Threat Flags

No new threat surface beyond what is documented in the plan's threat model:
- T-04-13: `judge.py` live LLM call gated by `allow_live_llm` two-factor check (SystemExit if false) -- implemented
- T-04-14: DB write from eval results is optional and error-tolerant (psycopg.Error caught, warns and returns) -- implemented

## Self-Check

- [x] eval/judge.py exists
- [x] eval/run_eval.py modified with _write_db_results() + --db flag
- [x] `uv run python -c "import ast,pathlib; ast.parse(pathlib.Path('eval/judge.py').read_text()); print('OK')"` passes
- [x] `DATABASE_URL=placeholder uv run python eval/run_eval.py --db` prints "DB write skipped" and exits 0
- [x] `env -u DATABASE_URL uv run python eval/run_eval.py --db` prints "DB write skipped" and exits 0
- [x] `grep -q 'os.environ.get("DATABASE_URL")' eval/run_eval.py` passes
- [x] `grep -q "SUMMARY_PATH.read_text" eval/run_eval.py` passes
- [x] `grep -q 'summary["suite_run_id"]' eval/run_eval.py` passes
- [x] judge_draft raises SystemExit when ALLOW_LIVE_LLM is not set (verified with exact SystemExit catch)
- [x] Module docstring contains "local-only" and "never runs in CI"
- [x] D-16 floor: `min(raw_score, 1)` code path present
- [x] `tier="draft"` in call_text call
- [x] `grep "eval.yml" eval/judge.py` returns nothing
- [x] `DATABASE_URL=placeholder uv run python eval/run_eval.py --check` exits 0
- [x] 115 core tests pass (test_eval_wiring, test_calculate, test_reconcile, test_gate, test_federal_withholding)
- [x] Commit ada4f23 exists (Task 1)
- [x] Commit d728e6e exists (Task 2)

## Self-Check: PASSED
