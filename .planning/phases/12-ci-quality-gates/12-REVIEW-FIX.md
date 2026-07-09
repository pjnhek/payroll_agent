---
phase: 12-ci-quality-gates
fixed_at: 2026-07-09T19:20:00Z
review_path: .planning/phases/12-ci-quality-gates/12-REVIEW.md
iteration: 1
findings_in_scope: 3
fixed: 3
skipped: 0
status: all_fixed
---

# Phase 12: Code Review Fix Report

**Fixed at:** 2026-07-09T19:20:00Z
**Source review:** .planning/phases/12-ci-quality-gates/12-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 3 (fix_scope: critical_warning — WR-01, WR-02, WR-03; IN-01..IN-05 out of scope)
- Fixed: 3
- Skipped: 0

## Fixed Issues

### WR-01: ci.yml has no `permissions:` block — GITHUB_TOKEN runs with default (potentially write) scope

**Files modified:** `.github/workflows/ci.yml`
**Commit:** 7ad2177
**Applied fix:** Added a workflow-level least-privilege block (`permissions: contents: read`)
above the `on:` trigger, with a one-line rationale comment. Verified via YAML parse that
`permissions == {contents: read}`.

### WR-02: Third-party actions pinned to mutable tags, not commit SHAs

**Files modified:** `.github/workflows/ci.yml`
**Commit:** c0d8de4
**Applied fix:** Resolved the CURRENT SHAs for the exact tags in use via `git ls-remote`
against each upstream repo and replaced all 4 `uses:` lines:
- `actions/checkout@v4` → `actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4.3.1 (v4)`
  (lightweight `v4` tag points directly at the v4.3.1 commit)
- `astral-sh/setup-uv@v5` → `astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86  # v5.4.2 (v5)`
  (annotated `v5` tag; SHA is the peeled `v5^{}` commit, == v5.4.2)

Verified via YAML parse that all 4 `uses:` entries carry the full 40-char SHAs with tag
comments. Review's suggestion to add Dependabot `github-actions` ecosystem coverage was
noted but not applied (no `.github/dependabot.yml` exists; creating a new file is beyond
the finding's cited scope — flag as follow-up if desired).

### WR-03: CI does not enforce the committed lockfile (Cross-AI, Codex)

**Files modified:** `.github/workflows/ci.yml`
**Commit:** c4ad877
**Applied fix:** Changed both `run: uv sync` invocations (lint + test jobs) to
`run: uv sync --locked` with a rationale comment. Sanity-checked locally: `uv sync --locked`
succeeds against the committed `uv.lock` (Resolved 58 packages / Audited 56 packages), so CI
will not break on a stale lockfile.

## Verification

- YAML parse of `.github/workflows/ci.yml` passes after each fix (Tier 2).
- The two gate commands remain byte-for-byte `uv run ruff check .` and `uv run pytest -q`
  (success criterion 3 preserved; asserted programmatically against the parsed YAML).
- `uv run ruff check .` → All checks passed (post-fix).
- `uv sync --locked` → succeeds against committed lockfile.

All fixes were applied in an isolated git worktree on a temp branch and fast-forwarded into
`master` (385c01f → c4ad877); worktree, temp branch, and recovery sentinel cleaned up.

---

_Fixed: 2026-07-09T19:20:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
