---
phase: 20-exactly-once-send
plan: "08"
subsystem: testing
tags: [evaluation, svg, matplotlib, dashboard, offline]

# Dependency graph
requires:
  - phase: 20-exactly-once-send
    provides: "Completed outbound-delivery safety path and frozen snapshot consumer"
provides:
  - "Dashboard-aligned offline evaluation chart"
  - "Deterministic SVG style, aggregate-only, and delivery-boundary regression checks"
affects: [evaluation, dashboard, phase-21-durability-proofs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Keep chart presentation tokens separate from scoring and fixture interpretation"
    - "Verify offline eval artifacts cannot import delivery or persistence writers"

key-files:
  created:
    - tests/test_eval.py
  modified:
    - eval/run_eval.py
    - eval/chart.svg

key-decisions:
  - "Use the dashboard's navy, indigo, neutral, and semantic-danger tokens while preserving every scoring and --check path."
  - "Render the committed SVG from aggregate scoring output only; D-04/D-13 boundary tests forbid delivery, queue, gateway, snapshot, and persistence-writer imports."

patterns-established:
  - "The offline chart generator owns explicit palette and typography metadata so visual regressions are testable without byte-pinning Matplotlib output."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "Offline eval chart uses dashboard-aligned palette, typography, restrained chrome, and stable aggregate labels."
    requirement: SEND-01
    verification:
      - kind: unit
        ref: tests/test_eval.py#test_chart_style_metadata_matches_dashboard_tokens
        status: pass
      - kind: unit
        ref: tests/test_eval.py#test_committed_chart_is_the_styled_aggregate_artifact
        status: pass
    human_judgment: false
  - id: D2
    description: "Chart polish leaves evaluation scores and regression semantics unchanged."
    requirement: SEND-02
    verification:
      - kind: other
        ref: uv run python eval/run_eval.py --check
        status: pass
      - kind: unit
        ref: tests/test_eval.py#test_chart_svg_is_styled_aggregate_only_and_does_not_mutate_summary
        status: pass
    human_judgment: false
  - id: D3
    description: "The eval chart remains isolated from provider delivery, queue, snapshot, and database mutation code."
    requirement: SEND-03
    verification:
      - kind: unit
        ref: tests/test_eval.py#test_eval_chart_module_boundary_excludes_delivery_and_mutation_code
        status: pass
      - kind: integration
        ref: uv run pytest tests/test_send_idempotency.py tests/test_delivery.py -q
        status: pass
    human_judgment: false

# Metrics
duration: 4 min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 08: Eval Chart Restyle Summary

**Dashboard-aligned offline evaluation SVG with aggregate-only rendering and delivery-safety boundary regression checks.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-07-17T21:26:04Z
- **Completed:** 2026-07-17T21:30:13Z
- **Tasks:** 2
- **Files modified:** 3 (plus this summary)

## Accomplishments

- Added explicit dashboard palette and sans-serif style tokens to the offline Matplotlib generator, with lighter gridlines/spines, readable labels, and a styled decision safety table.
- Regenerated `eval/chart.svg` through the repository's standard `uv`-managed chart command; the chart contains aggregate metrics and labels only, with no fixture employee text.
- Added regression tests for style metadata, generated-artifact structure, summary immutability, and the D-04/D-13 module boundary.

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Add eval chart style regression boundary** - `c7045d7` (test)
2. **Task 1 GREEN: Align eval chart with dashboard styling** - `1159b6a` (feat)
3. **Task 2: Regenerate dashboard-aligned eval chart** - `fe53d46` (chore)

## Files Created/Modified

- `eval/run_eval.py` - Dashboard-aligned presentation tokens and restrained SVG styling; scoring, fixture loading, and check semantics unchanged.
- `eval/chart.svg` - Regenerated committed chart artifact.
- `tests/test_eval.py` - Style, aggregate-only rendering, artifact, summary immutability, and delivery-boundary regression checks.

## Decisions Made

- Kept the existing Matplotlib/SVG approach and changed presentation tokens only, preserving the offline command and all reported metric values.
- Used the selected todo's navy/neutral direction (`#1E3A5F` / `#6B7280`) alongside the dashboard indigo and semantic colors.
- Kept `app.db.seed` as the allowed in-memory fixture source while forbidding queue, gateway, delivery, snapshot, and persistence-writer imports.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Matplotlib rcParams mapping failed strict mypy**

- **Found during:** Task 1 verification
- **Issue:** Matplotlib's typed `rcParams.update()` rejected the heterogeneous chart-style mapping.
- **Fix:** Added a narrow `cast(Any, CHART_STYLE)` at the local Matplotlib boundary; no runtime behavior or scoring path changed.
- **Files modified:** `eval/run_eval.py`
- **Verification:** `uv run mypy eval/run_eval.py tests/test_eval.py` passed.
- **Committed in:** `1159b6a`

**Total deviations:** 1 auto-fixed (1 Rule 3 blocking type issue).
**Impact on plan:** The fix was local to the chart-only Matplotlib boundary and did not expand scope or alter evaluation semantics.

## Issues Encountered

- The plan-listed `tests/test_eval.py` did not exist on the clean baseline, so it was created as the requested regression test module; the existing `tests/test_eval_wiring.py` was left unchanged.
- The normal chart command also rewrote the generated timestamp/UUID in `eval/summary.json`; that out-of-scope incidental change was restored, leaving only the plan-authorized files changed.
- `git diff --check` reports trailing whitespace in Matplotlib-generated SVG path lines; this is generator output and does not affect SVG validity or source/test formatting.

## Known Stubs

The modified `run_eval.py` retains its pre-existing `DATABASE_URL="placeholder"` optional-DB sentinel. It is an intentional configuration guard, not a UI/evaluation stub, and was not changed by this plan.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SEND-01 through SEND-03 safety remains green after chart regeneration.
- The committed chart is reproducible from the existing offline fixtures and remains isolated from outbound delivery state.

## Verification

- `uv run python eval/run_eval.py --check` - passed.
- `uv run pytest tests/test_eval.py -q` - 4 passed.
- `uv run pytest tests/test_send_idempotency.py tests/test_delivery.py -q` - 32 passed, 3 skipped by guarded live-DB conditions.
- `uv run pytest tests/test_eval_wiring.py -q` - 3 passed.
- `uv run ruff check eval/run_eval.py tests/test_eval.py` - passed.
- `uv run mypy eval/run_eval.py tests/test_eval.py` - passed.

---
*Phase: 20-exactly-once-send*
*Completed: 2026-07-17*

## Self-Check: PASSED

- Summary, generator, committed SVG, and regression test files exist.
- Task commits `c7045d7`, `1159b6a`, and `fe53d46` are present in history.
- Final plan-level eval, delivery safety, lint, type, and wiring verification passed.
