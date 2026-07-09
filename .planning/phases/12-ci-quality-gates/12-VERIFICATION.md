# Phase 12 Verification — CI Red-Proof (Plan 12-04)

**Date:** 2026-07-09
**Requirement coverage:** CI-01, CI-02 — ROADMAP.md Phase 12 success criterion 4
("Pushing a branch with a deliberately injected lint error shows CI going red on the
lint step, and a deliberately broken test shows CI going red on the test step — both
demonstrated, not just configured").

All three runs were observed live on GitHub Actions (`ci.yml`), driven to completion
via `gh run watch`, and visually confirmed by the human operator at the plan's
blocking human-verify checkpoint (2026-07-09).

## Run Evidence

### 1. Lint-red run (branch `ci-redproof-lint`)

- **Run URL:** https://github.com/pjnhek/payroll_agent/actions/runs/29035450139
- **Injected regression:** exactly one unused import (`import sys`) added to
  `app/main.py` — commit `ab2676e` (`test(12): inject lint error for CI red-proof (throwaway)`)
- **RED job: `Lint (ruff check)`** — failed on the `Run ruff check` step with
  `F401 'sys' imported but unused` (exit code 1)
- **GREEN job: `Test suite (hermetic)`** — passed (the lint injection touched no test
  behavior; local pre-push sanity run: 613 passed / 50 skipped, unchanged)
- Proves: the lint gate independently catches a real lint regression; the two jobs are
  genuinely independent.

### 2. Test-red run (branch `ci-redproof-test`)

- **Run URL:** https://github.com/pjnhek/payroll_agent/actions/runs/29035484150
- **Injected regression:** exactly one assertion value changed in
  `tests/test_check_schema_cli.py::test_main_exits_0_in_sync`
  (`"in_sync"` → `"deliberately-wrong-value-for-ci-redproof"`) — commit `6935e72`
  (`test(12): inject test failure for CI red-proof (throwaway)`)
- **RED job: `Test suite (hermetic)`** — failed on the `Run test suite` step
  (the one deliberately broken assertion)
- **GREEN job: `Lint (ruff check)`** — passed (local pre-push sanity run:
  `uv run ruff check .` → "All checks passed!")
- Proves: the test gate independently catches a real test regression.

### 3. Master-green run (branch `master`, HEAD `157633d`)

- **Run URL:** https://github.com/pjnhek/payroll_agent/actions/runs/29035287971
- **Trigger:** fast-forward push of master to origin (`2eaa5fc..157633d`) — the
  repo's first-ever `ci.yml` run, carrying Plan 12-01/12-02/12-03's ruff config,
  hand-fixed lint violations, and the `ci.yml` workflow itself
- **BOTH jobs GREEN:** `Lint (ruff check)` passed (11s); `Test suite (hermetic)`
  passed (1m19s — 613 passed / 50 skipped, matching the local baseline)
- Proves: the green baseline is genuine — the gate passes the clean repo and fails
  only when a real regression is injected.

## Branch Cleanup (D-14)

Both throwaway branches (`ci-redproof-lint`, `ci-redproof-test`) were deleted from
origin and locally after the run URLs above were captured. Per D-14, the red runs
themselves remain permanently visible in the repo's GitHub Actions run history
(deleting a branch does not delete its historical workflow runs) — acceptable and
expected; only the branches were cleaned up.
