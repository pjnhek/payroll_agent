---
phase: 12-ci-quality-gates
plan: 03
subsystem: infra
tags: [github-actions, ci, ruff, pytest, uv, badge]

# Dependency graph
requires:
  - phase: 12-ci-quality-gates (12-01, 12-02)
    provides: committed pyproject.toml [tool.ruff] config + a fully-clean ruff diff (zero violations) so the very first ci.yml run on master is green
provides:
  - .github/workflows/ci.yml — push-triggered (every branch) lint + test CI gate with per-branch cancellable concurrency
  - README.md CI status badge linking to the ci.yml Actions runs page
affects: [12-04 (red-proof demonstration), any future phase touching CI or README]

# Tech tracking
tech-stack:
  added: []
  patterns: ["GitHub Actions workflow with two independent unconditional jobs (lint, test), each its own named check", "concurrency group keyed per-branch (ci-${{ github.ref }}) with cancel-in-progress: true for safely-cancellable CI runs, contrasted with deploy-migrate's cancel-in-progress: false for non-cancellable DDL"]

key-files:
  created: [.github/workflows/ci.yml]
  modified: [README.md]

key-decisions:
  - "on: push with no branches: filter (D-07) — 'every push to every branch,' deliberately deviating from the master-only norm in the 4 existing workflows"
  - "concurrency group ci-${{ github.ref }} + cancel-in-progress: true (D-09) — lint/test are safely cancellable, unlike deploy-migrate's non-cancellable DDL"
  - "jobs.test has no env: block at all (D-11) — DATABASE_URL/ALLOW_DB_RESET/ALLOW_LIVE_LLM all unset, relying on tests/conftest.py's two-factor guards for hermetic skip behavior"
  - "no ruff format --check step/job (D-05) — formatter adoption explicitly deferred; ci.yml is lint-only"
  - "no coverage gate or minimum-passed-test-count assertion (D-12/D-13) — bare pytest -q exit code is the only signal"
  - "single CI badge only (D-15) — no eval or coverage badge added"
  - "no branch-protection / required-status-check config added (D-16) — CI stays an after-the-fact signal, master pushes remain unblocked"

requirements-completed: [CI-01, CI-02, CI-03]

# Metrics
duration: 12min
completed: 2026-07-09
---

# Phase 12 Plan 03: CI Workflow + README Badge Summary

**New `ci.yml` GitHub Actions workflow running bare `uv run ruff check .` and `uv run pytest -q` as two independent unconditional jobs on every branch push, plus a README CI badge — both verified green locally against this worktree before commit.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-09T16:41:00Z
- **Completed:** 2026-07-09T16:53:00Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- `.github/workflows/ci.yml` created: `name: ci`, triggers on `push` (no `branches:` filter — all branches) plus `workflow_dispatch`, with a per-branch cancellable `concurrency` group
- Two independent, unconditional jobs — `lint` ("Lint (ruff check)") and `test` ("Test suite (hermetic)") — each its own named GitHub check, neither gated by `if:`
- Both jobs run the exact bare commands a developer runs locally (`uv run ruff check .`, `uv run pytest -q`), with the test job carrying zero `env:` block so `tests/conftest.py`'s two-factor guards keep it hermetic
- README.md now displays a CI status badge directly under the H1 title, linking to `https://github.com/pjnhek/payroll_agent/actions/workflows/ci.yml`
- Locally verified both jobs would pass exactly as CI runs them: `uv run ruff check .` → "All checks passed!"; `uv run pytest -q` → 612 passed, 51 skipped (worktree variance from the missing untracked `.env`, per the environment note — main tree reports 613/50)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create .github/workflows/ci.yml with lint + test jobs** - `925de84` (feat)
2. **Task 2: Add CI status badge to README.md** - `1a87879` (docs)

_Note: the plan's Task 2 instructions suggested committing both files together in one commit; this executor instead kept the two tasks as separate atomic commits (ci.yml already landed in Task 1's commit), consistent with the per-task atomic-commit protocol governing this execution. Both files are still present together in `git log`/`git show --stat` across the two consecutive commits, satisfying the underlying intent (both changes shipped, staged only via explicit pathspecs, no unrelated files swept in)._

**Plan metadata:** (this SUMMARY.md commit, made separately per plan)

## Files Created/Modified
- `.github/workflows/ci.yml` - New workflow: `lint` job (`uv run ruff check .`) + `test` job (`uv run pytest -q`), triggered on every branch push + workflow_dispatch, per-branch cancellable concurrency group
- `README.md` - Added one CI badge line under the H1 title, above the "Live App" line

## Decisions Made
- Kept Task 1 and Task 2 as two separate atomic commits (each individually verified and staged by explicit pathspec) rather than the plan's suggested single combined commit — matches the executor's per-task commit protocol; no functional difference since both land consecutively on the same branch before this SUMMARY.
- No other deviations from the plan's explicit content (job names, step names, trigger shape, concurrency group, env omission, badge URL) — all copied exactly as specified.

## Deviations from Plan

None - plan executed exactly as written (aside from the commit-granularity note above, which is a process detail, not a content deviation).

## Issues Encountered

None. Both `git status --short` preflight checks (before Task 1's file creation and before Task 2's edit) confirmed a clean working tree with no unrelated dirty files to accidentally sweep in — both commits staged only their own explicit paths (`.github/workflows/ci.yml`, then `README.md`), never `git add -A`/`git commit -a`.

## User Setup Required

None - no external service configuration required. The badge will render live once this branch's commits reach a branch that GitHub Actions runs on and produces at least one `ci.yml` run (the live red-proof demonstration is explicitly Plan 12-04's job, not this plan's).

## Next Phase Readiness

`ci.yml` is authored, valid YAML, and both its jobs run green locally against the exact commands they'll run in CI. This lands after 12-01 and 12-02 (wave 3, `depends_on: ["12-01", "12-02"]`), so master's own `ci.yml` history will start green once merged. Plan 12-04 can now push a branch and observe the live gate (including the red-proof demonstration) — nothing was pushed to origin by this plan, per its explicit scope boundary.

## Self-Check: PASSED

- FOUND: .github/workflows/ci.yml
- FOUND: README.md
- FOUND: commit 925de84 (Task 1)
- FOUND: commit 1a87879 (Task 2)

---
*Phase: 12-ci-quality-gates*
*Completed: 2026-07-09*
