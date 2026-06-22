---
phase: 04-the-eval-the-proof
plan: "03"
subsystem: eval
tags: [eval, chart, svg, matplotlib, ci, github-actions, false-process-rate]

requires:
  - phase: 04-the-eval-the-proof
    plan: "02"
    provides: "eval/run_eval.py scorer + eval/summary.json committed output"

provides:
  - "eval/chart.svg -- committed recruiter-visible SVG proof: extraction field accuracy + F1 per category, reconciliation k/n bars, confusion matrix with false_process_rate headline (D-08, D-11, D-12, D-13)"
  - ".github/workflows/eval.yml -- project's first CI workflow: hermetic push job (--check, no secrets, no live LLM) + workflow_dispatch record job (EXTRACTION_API_KEY gated)"
  - "eval/run_eval.py (modified): _write_svg_chart() added + --chart CLI flag; --chart calls _write_svg_chart after _write_summary_json (3-arg call unchanged from 04-02)"
  - "pyproject.toml + uv.lock -- matplotlib added to [dependency-groups].dev only (never runtime)"

affects:
  - "04-04 (dashboard eval view reads eval/summary.json and eval/chart.svg produced here)"
  - "Phase 5 DASH-04 (summary.json schema_version=1, all Phase-5 required keys present)"

tech-stack:
  added:
    - "matplotlib>=3.11.0 (dev group only; uv.lock pinned)"
  patterns:
    - "matplotlib.use('Agg') inside chart function only -- non-interactive backend, never at module level (T-04-11)"
    - "Local matplotlib import inside _write_svg_chart() -- keeps off --check/scoring import path"
    - "Hermetic CI: push job references no secrets and does not set ALLOW_LIVE_LLM (D-17)"
    - "workflow_dispatch + inputs.live_record condition gates the live record job"
    - "astral-sh/setup-uv@v5 + uv sync for GitHub Actions (uv tooling rule per CLAUDE.md)"

key-files:
  created:
    - "eval/chart.svg -- committed SVG chart, 132525 bytes (valid <?xml + <svg)"
    - ".github/workflows/eval.yml -- project's first CI workflow (54 lines)"
  modified:
    - "eval/run_eval.py -- _write_svg_chart() + --chart flag added (lines 660-845)"
    - "pyproject.toml -- matplotlib added to dev dependency group"
    - "uv.lock -- updated by uv add --dev matplotlib"

key-decisions:
  - "matplotlib imported inside _write_svg_chart only (not module-level) to keep scoring/--check path free of the dep"
  - "Subplot 2 title uses exact D-13 taxonomy-honesty wording: 'coverage buckets, not classes'"
  - "false_process table cell [1,2] highlighted red (the dangerous error cell, not true-clarify at [2,2])"
  - "Honesty caption at chart bottom: extraction bars are replayed caches, not live model run (Codex fix)"
  - "DATABASE_URL=placeholder in both CI jobs: check job doesn't require it (belt-and-suspenders); record job needs it for app.config"
  - "secrets.EXTRACTION_API_KEY referenced only in record job (workflow_dispatch only), never in check job"

requirements-completed: [EVAL-04, EVAL-05]

duration: 20min
completed: 2026-06-22
---

# Phase 04 Plan 03: SVG Chart + GitHub Actions eval.yml Summary

**SVG chart (132KB, 3-subplot) committed to repo with false-process-rate headline + per-category bars; project's first CI workflow adds hermetic --check gate on push and workflow_dispatch live-record job.**

## Performance

- **Duration:** 20 min
- **Started:** 2026-06-22T20:45:00Z
- **Completed:** 2026-06-22T21:05:00Z
- **Tasks:** 2 / 2
- **Files modified:** 5

## Accomplishments

### Task 1: matplotlib dev dep + _write_svg_chart() + --chart flag

Added `matplotlib>=3.11.0` to `[dependency-groups].dev` via `uv add --dev matplotlib` (updates both `pyproject.toml` and `uv.lock`). Added `_write_svg_chart(fixture_results, aggregated)` to `eval/run_eval.py` with:

- **Subplot 1 (Extraction):** Grouped horizontal bars per fixture category -- field accuracy (steelblue) + employee-set F1 (#9ecae1). Annotated to 3 decimal places. Title includes overall field_accuracy + F1 numbers.
- **Subplot 2 (Reconciliation):** Per-NAME-category horizontal bars with `k/n` fraction annotations (not %). D-13 taxonomy-honesty label: "Accuracy on fixtures of category X". Title includes "coverage buckets" disclaimer.
- **Subplot 3 (Confusion matrix):** 2×2 table via `ax.table()`; false-process cell `[1,2]` highlighted #FFCCCC (the dangerous error -- Codex HIGH fix: prior `[2,2]` was the safe true-clarify cell). Bold title with false-process count and rate as headline (D-11).
- **Honesty caption:** `fig.text()` at bottom noting extraction bars are replayed caches, not live model run; includes model ID from `_extraction_model_id()` (env-resolved, no app.config).
- `--chart` CLI flag wired: `if args.chart: _write_svg_chart(fixture_results, aggregated)` called after `_write_summary_json(fixture_results, aggregated, suite_run_id)` (3-arg signature from 04-02 unchanged).

Generated and committed `eval/chart.svg` (132525 bytes, valid SVG starting with `<?xml version="1.0" encoding="utf-8"`). `env -u DATABASE_URL uv run python eval/run_eval.py --check` still exits 0 (regression gate unaffected).

### Task 2: .github/workflows/eval.yml

Created the project's first CI workflow with two jobs:

**check job (hermetic push regression gate):**
- Runs on every push to `master` and every `workflow_dispatch`
- Uses `astral-sh/setup-uv@v5` + Python 3.12 + `uv sync` + `uv run python eval/run_eval.py --check`
- Zero secret references; `ALLOW_LIVE_LLM` intentionally absent (keeps gate hermetic)
- `DATABASE_URL: "placeholder"` as belt-and-suspenders (eval is DB-free; the value is not required)

**record job (live re-record, workflow_dispatch only):**
- Conditional on `github.event_name == 'workflow_dispatch' && inputs.live_record`
- `workflow_dispatch` input `live_record` (boolean, default false) controls whether this job runs
- References `secrets.EXTRACTION_API_KEY` (only this job, never check)
- `DATABASE_URL: "placeholder"` + `ALLOW_LIVE_LLM: "true"`

No `pip install` anywhere; uv-only per CLAUDE.md tooling rule.

## Task Commits

1. **Task 1: matplotlib dev dep + SVG chart writer** - `7d6c904` (feat)
2. **Task 2: .github/workflows/eval.yml** - `b39d72c` (feat)

## Files Created/Modified

- `eval/chart.svg` -- committed SVG chart (132525 bytes); 3-subplot layout with false-process headline
- `.github/workflows/eval.yml` -- project's first CI workflow (54 lines)
- `eval/run_eval.py` -- _write_svg_chart() + --chart flag added (185 new lines)
- `pyproject.toml` -- matplotlib>=3.11.0 added to [dependency-groups].dev
- `uv.lock` -- updated by uv add --dev matplotlib
- `eval/summary.json` -- regenerated in the same run that produces the chart (unchanged scores)

## Decisions Made

- matplotlib imported inside `_write_svg_chart()` only (local import, never module-level) to prevent the dep from being required on the scoring/`--check` path.
- `table[1, 2].set_facecolor("#FFCCCC")` highlights the false-process cell -- the "Actual: process / Expected: clarify" cell, i.e., the case that pays the wrong person. (Codex HIGH fix: the prior design referenced `[2,2]` which is the safe true-clarify cell.)
- D-13 exact wording preserved: "Accuracy on fixtures of category X" as `ax2.set_xlabel()`; "coverage buckets" in subplot 2 title.
- `DATABASE_URL=placeholder` in both CI jobs: the check job doesn't need it (run_eval.py is DB-free on the `--check` path), but it's set as a harmless safety net in case any future import is added. The record job uses it for `app.config` (needed by `_require_live_llm`).

## Deviations from Plan

None -- plan executed exactly as written.

- matplotlib placement: dev group only (never in [project.dependencies]) -- as specified
- `_write_svg_chart()` signature: `(fixture_results, aggregated)` -- as specified (no suite_run_id needed)
- `_write_summary_json()` call unchanged: 3 args (`fixture_results, aggregated, suite_run_id`) -- as specified
- eval.yml check job: zero secrets, no ALLOW_LIVE_LLM -- as specified
- eval.yml record job: conditional on `workflow_dispatch && inputs.live_record` -- as specified

## Known Stubs

None. `eval/chart.svg` is a real scored chart over real fixture data. `eval/summary.json` has real scores. `.github/workflows/eval.yml` is a real CI workflow. No placeholder values.

## Threat Flags

No new threat surface beyond what is documented in the plan's threat model (T-04-08 through T-04-SC). The `secrets.EXTRACTION_API_KEY` reference in the record job matches T-04-08 mitigation (GitHub Secrets vault, workflow_dispatch only). The check job has zero secret references per T-04-09.

## Self-Check

- [x] eval/chart.svg exists (132525 bytes)
- [x] head -1 eval/chart.svg starts with `<?xml` (valid SVG)
- [x] `<svg` present in chart.svg content
- [x] .github/workflows/eval.yml exists (54 lines)
- [x] eval.yml check job: no `secrets.` reference
- [x] eval.yml check job: no `ALLOW_LIVE_LLM`
- [x] eval.yml record job: `workflow_dispatch && inputs.live_record` condition
- [x] eval.yml record job: `secrets.EXTRACTION_API_KEY` reference
- [x] `actions/checkout@v4` appears 2 times (one per job)
- [x] No `pip install` in eval.yml
- [x] matplotlib in [dependency-groups].dev, NOT in [project.dependencies]
- [x] matplotlib imported inside `_write_svg_chart` only (not at module top level)
- [x] subplot 2 title contains "coverage buckets" (D-13)
- [x] `FALSE-PROCESS` appears in subplot 3 title in bold
- [x] Commit 7d6c904 exists (Task 1)
- [x] Commit b39d72c exists (Task 2)
- [x] `env -u DATABASE_URL uv run python eval/run_eval.py --check` exits 0
- [x] `env -u DATABASE_URL uv run python eval/run_eval.py --chart` exits 0

## Self-Check: PASSED
