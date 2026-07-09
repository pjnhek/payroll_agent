---
phase: 12-ci-quality-gates
plan: 02
subsystem: testing
tags: [ruff, lint, ci, sim117, e501, type-checking, python312]

# Dependency graph
requires:
  - phase: 12-ci-quality-gates (Plan 01)
    provides: committed ruff config (curated ruleset E/F/I/B/UP/SIM at line-length 100) + mechanical autofix (imports, datetime.UTC), with SIM117 excluded via --unfixable
provides:
  - "uv run ruff check . exits 0 with zero violations under the committed ruleset"
  - "Zero blanket ignores in pyproject.toml; zero # ruff: noqa: SIM117 directives anywhere in the repo"
  - "All 46 SIM117 nested-with sites structurally collapsed into single combined with-statements"
  - "133 E501 long-line violations hand-wrapped (docstrings/comments/monkeypatch calls/f-strings/signatures)"
  - "12 non-E501/non-SIM117 rule categories hand-fixed: F821 (TYPE_CHECKING), B904 (exception chaining), B007 (unused loop vars), B905 (zip strict=), B017 (narrowed exception), SIM108 (ternary), SIM115 (context managers), UP042 (StrEnum), UP047 (PEP 695 generics), E402 (justified noqa), F841 (unused vars)"
affects: [13-module-structure-boundaries, 14-full-type-checking, 15-comment-hygiene-polish]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "enum.StrEnum (PEP 663, Python 3.11+) for str-valued enums instead of class Foo(str, enum.Enum) — verified no str()-formatting call site relied on the qualified-name form before switching"
    - "PEP 695 bounded generic function syntax (def f[T: Bound](...)) replacing standalone TypeVar declarations, Python 3.12+"
    - "if TYPE_CHECKING: guarded imports for quoted forward-reference type annotations in test helper functions (avoids runtime import cost, satisfies F821)"
    - "Single combined with-statement (with a() as x, b():) replacing nested with blocks — the repo-wide SIM117 idiom for connection+transaction / connection+transaction+cursor scoping"

key-files:
  created: []
  modified:
    - app/main.py
    - app/llm/client.py
    - app/email/gateway.py
    - app/models/status.py
    - app/models/roster.py
    - app/pipeline/decide.py
    - app/pipeline/validate.py
    - app/pipeline/calculate.py
    - app/pipeline/orchestrator.py
    - app/pipeline/tax_tables_2026.py
    - app/db/repo.py
    - app/db/seed.py
    - app/db/bootstrap.py
    - eval/run_eval.py
    - scripts/show_confirmation_subject.py
    - scripts/reset_stuck_runs.py
    - tests/conftest.py
    - tests/test_calculate.py
    - tests/test_detect_field_regression.py
    - tests/test_validate.py
    - tests/test_atomic_persist.py
    - tests/test_clarify_rounds.py
    - tests/test_needs_operator.py
    - tests/test_demo_landing.py
    - tests/test_gateway.py
    - tests/test_ingest.py
    - tests/test_live_llm.py
    - tests/test_resume_pipeline.py
    - tests/test_dashboard.py
    - tests/test_alias_write.py
    - tests/test_federal_withholding.py
    - tests/test_compose_email_field_regression.py
    - tests/test_alias_full_loop.py
    - tests/test_threading.py
    - tests/test_stuck_run_recovery.py
    - tests/test_cr_regressions.py
    - tests/test_combined_context.py
    - tests/test_concurrency_proof.py
    - tests/test_cr01_classify_union.py
    - tests/test_hitl.py
    - tests/test_multiround_context_edge.py
    - tests/test_persistence.py
    - tests/test_reply_redelivery.py

key-decisions:
  - "UP042 RunStatus(str, enum.Enum) -> enum.StrEnum: confirmed no call site relies on str()'s qualified-name form (RunStatus.X) — the two app/main.py sites that call str(status) operate on plain DB TEXT scalars from repo rows, never RunStatus instances; templates render run.status (a raw string) not RunStatus members. Behavior-neutral."
  - "UP047 call_structured now uses PEP 695 bounded generic def call_structured[T: BaseModel](...), removing the standalone TypeVar('T', bound=BaseModel) declaration after confirming T had no other usages in app/llm/client.py."
  - "SIM117: all 46 sites structurally collapsed (not suppressed) per the user decision superseding the original per-file-noqa approach — 45 via ruff's own --select SIM117 --fix (safe fix, inspected diff), 1 hand-collapsed (app/db/seed.py:307, the only non-auto-fixable site) following the identical shape-2 pattern."
  - "E501: pure re-wrapping only — no string literal contents, log message text, comment meaning, or code semantics changed at any of the 133 sites."

patterns-established:
  - "SQL string literal contents are never re-indented during a with-statement collapse — only the surrounding code/with structure changes, matching the exact behavior ruff's own SIM117 autofix applied to eval/run_eval.py's 3-clause site."

requirements-completed: [CI-01, CI-03]

# Metrics
duration: ~75min
completed: 2026-07-09
---

# Phase 12 Plan 02: Hand-Fix Remaining Ruff Violations Summary

**Every one of the 222 post-autofix ruff violations (134 E501, 46 SIM117, 42 across 10 other rule codes) resolved by structural fix or individually-justified noqa — `uv run ruff check .` now exits 0 with zero blanket ignores and zero `# ruff: noqa: SIM117` directives anywhere in the repo, 613/50 test suite unchanged.**

## Performance

- **Duration:** ~75 min
- **Started:** 2026-07-09T15:30:00Z (approx, worktree setup)
- **Completed:** 2026-07-09T16:47:16Z
- **Tasks:** 2
- **Files modified:** 41

## Accomplishments

- Resolved all 12 non-E501/non-SIM117 violation categories from the post-12-01-autofix baseline (F821, B904, B007, B905, B017, SIM108, SIM115, UP042, UP047, E402, F841) via structural fixes (TYPE_CHECKING imports, exception chaining, context managers, `strict=` kwarg, `StrEnum`, PEP 695 generics, ternary) — zero suppressions of convenience.
- Collapsed all 46 SIM117 nested-`with` sites across 6 files into single combined with-statements — 45 via ruff's own safe autofix (diff-inspected), 1 hand-collapsed (`app/db/seed.py:307`) following the identical pattern. Zero `# ruff: noqa: SIM117` anywhere.
- Hand-wrapped 133 E501 long-line violations across ~30 files using standard Python continuation (parenthesized expressions, argument-boundary wraps, comment re-wraps) — zero changes to string content, log messages, or code semantics.
- `uv run ruff check .` (config-driven, no flags) now exits 0, "All checks passed!" — the curated ruleset (E, F, I, B, UP, SIM at line-length 100) is fully clean repo-wide with zero `pyproject.toml`-level ignores.
- 613/50 test suite unchanged throughout both tasks (612/51 in this worktree per the documented `.env` variance — see Environment Note below).

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix F821/B904/B007/B905/B017/SIM108/SIM115/UP042/UP047/E402/F841** - `c2268cb` (style)
2. **Task 2: Collapse SIM117 + fix E501 repo-wide** - `36a9f5d` (style)

_No TDD tasks in this plan — pure lint-remediation, guarded by the existing 613/50 test suite re-run after each commit._

## Files Created/Modified

- `app/models/status.py` — `RunStatus(str, enum.Enum)` → `enum.StrEnum` (UP042)
- `app/llm/client.py` — PEP 695 bounded generic `call_structured[T: BaseModel]`, removed standalone `TypeVar`; `raise last_error from exc` (B904)
- `app/main.py` — 6× `except Exception as exc: ... raise ... from exc` (B904); E501 wraps
- `app/email/gateway.py` — ternary collapse for inbound-payload normalization (SIM108)
- `app/pipeline/decide.py` — `_emp_id` unused-loop-var rename (B007)
- `app/pipeline/validate.py` — E501 wraps around field-regression message + OT-missing comment
- `app/pipeline/calculate.py` — E501 wraps in docstrings + reconciliation-drift arithmetic
- `app/pipeline/orchestrator.py` — 9 SIM117 collapses (autofix) + E501 wraps
- `app/pipeline/tax_tables_2026.py` — E501 wrap on `SS_WAGE_BASE` comment
- `app/db/repo.py` — 33 SIM117 collapses (autofix) + E501 wraps (purpose-error-message wrap)
- `app/db/seed.py` — 1 SIM117 hand-collapse (the only non-autofixable site), verified pure structural change (no SQL string content altered)
- `app/db/bootstrap.py` — E501 wraps (print + ALTER TABLE statements)
- `app/models/roster.py` — E501 wrap on `pay_periods_per_year` field comment
- `eval/run_eval.py` — 3 B905 `strict=False` zip calls, 1 B904 exception chain, 1 SIM117 collapse (autofix, inspected: SQL string content untouched, only `with` structure changed), E501 wraps
- `scripts/show_confirmation_subject.py` — B007 unused-loop-var renames
- `scripts/reset_stuck_runs.py` — E501 wraps on destructive-confirmation prompts
- 20 test files — TYPE_CHECKING imports (F821), SIM115 context managers, B007 renames, B017 narrowed exception, E402 justified noqas, F841 underscore-prefixed vars, and E501 wraps across monkeypatch calls, f-string assertions, and multi-line function signatures

## Decisions Made

- **UP042 safety check performed before applying:** grepped every `RunStatus`/`str(status)` call site in `app/` and `templates/` to confirm the `StrEnum` switch is behavior-neutral. The two `str(status)` call sites in `app/main.py` (`_badge_class_filter`/`_badge_label_filter`) operate on plain `str` values already sourced from `RUN_COLS` (raw DB TEXT scalars), never `RunStatus` enum instances — templates render `run.status` (a dict/row value), not an enum member. Confirmed behavior-neutral before committing.
- **UP047 TypeVar removal safety check:** grepped all `T` usages in `app/llm/client.py` before deleting the standalone `TypeVar("T", bound=BaseModel)` declaration — confirmed `T` was used only at the `call_structured` signature (now the PEP 695 bound param) and had no other reuse in the file.
- **SIM117 structural collapse over suppression:** per the user decision recorded in the plan (superseding the original per-file-noqa approach), all 46 sites were genuinely fixed — none suppressed. The one non-autofixable site (`app/db/seed.py:307`) required manual re-indentation; the SQL string literal contents were deliberately left untouched (matching the exact pattern ruff's own autofix applied to the structurally similar `eval/run_eval.py` site), confirmed via `git diff` grep for `INSERT INTO`/`VALUES` lines showing zero content changes.
- **E501 wrap style chosen per site:** prefer wrapping at existing argument/kwarg boundaries (monkeypatch calls, function signatures) over introducing backslash continuations; multi-line f-string assertions split at natural sentence boundaries; long inline comments moved to standalone comment lines above the code when the code itself was already at the line-length limit.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Two extra E402 noqa sites in test_gateway.py/test_ingest.py were pre-existing but the plan's exact acceptance-criteria grep pattern (`grep -n "noqa: E402"`) doesn't match `# noqa: F401, E402` (comma-separated codes) at test_gateway.py:460**
- **Found during:** Task 1 acceptance-criteria verification
- **Issue:** The plan's acceptance criterion greps for the literal substring `"noqa: E402"`, but ruff's own multi-code noqa syntax puts `E402` second in a comma-separated list (`# noqa: F401, E402`), so a naive grep for `"noqa: E402"` doesn't match `"noqa: F401, E402"`.
- **Fix:** Verified via `uv run ruff check --select E402` (0 violations) that the noqa is functionally correct — ruff parses comma-separated codes regardless of order. No code change needed; documented here as a cosmetic acceptance-criteria mismatch, not a real gap.
- **Files affected:** tests/test_gateway.py (no fix needed, already correct)
- **Committed in:** c2268cb (Task 1 commit, pre-existing correct state)

**2. [Rule 1 - Bug] `test_cr_regressions.py:67` and `test_gateway.py:508` F841 sites were discovered during targeted `--select F821,...,F841` scan, not pre-identified in the plan's read_first list**
- **Found during:** Task 1, running the acceptance-criteria automated check
- **Issue:** The plan said "find via `uv run ruff check --select F841` since exact sites were not read during planning" — both sites were genuinely dead/documentation-only variables (`result` capturing a return value the test explicitly doesn't check; `send_params_hints` superseded by `all_hints`).
- **Fix:** Prefixed both with `_` per the plan's own F841 guidance (documentation/readability-purposed, not deleted).
- **Files modified:** tests/test_cr_regressions.py, tests/test_gateway.py
- **Committed in:** c2268cb (Task 1 commit)

**3. [Rule 1 - Bug] E501 violation count and file distribution shifted slightly from the plan's pre-estimate after Task 1's own edits**
- **Found during:** Task 2, initial `--select E501` scan
- **Issue:** The plan estimated 134 E501 lines across ~19 files; the actual post-Task-1 count was 133 across ~30 files (Task 1's TYPE_CHECKING/noqa/exception-chaining edits shifted a handful of lines over/under the 100-char threshold in ways not present in the original planning-time snapshot).
- **Fix:** Re-ran `--select E501` fresh after Task 1's commit and worked the actual current list rather than the plan's static estimate — same category of fix (pure re-wrapping), just a slightly different file/line set.
- **Files modified:** see Files Created/Modified above (superset of the plan's estimated list)
- **Committed in:** 36a9f5d (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (all Rule 1 — pre-existing/discovered-during-execution items handled per the plan's own stated fallback procedures; no scope creep, no architectural changes)
**Impact on plan:** None of these affected the plan's success criteria — `uv run ruff check .` is fully green, zero blanket ignores, zero SIM117 noqa, 613/50 suite unchanged.

## Issues Encountered

None beyond the deviations documented above.

## Environment Note

This worktree does not contain the repo's untracked `.env` file, so the hermetic suite reports **612 passed / 51 skipped** (one live-DB-dependent test in `tests/test_dashboard.py` skips without `.env`). This matches the documented baseline from Plan 12-01 and the executor's environment note — on the main tree with `.env` the same suite reports 613 passed / 50 skipped. Both numbers represent the same green state; the plan's stated acceptance criterion of "613 passed, 50 skipped" is satisfied modulo this known, pre-documented off-by-one.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `uv run ruff check .` is a clean, enforceable baseline — Phase 12's remaining plans (CI workflow wiring) have a genuine gate to enforce, satisfying CI-01 and CI-03.
- No blanket ignores or per-file-ignores exist in `pyproject.toml` to erode over time; the only individually-justified noqas are the 5 E402 late-import sites, each carrying an inline reason.
- Ready for Phase 13 (Module Structure & Boundaries) — the god-file splits (`app/main.py`, `app/db/repo.py`, `app/pipeline/orchestrator.py`) will inherit a fully-linted baseline, so post-split diffs will be pure structural moves, not lint-noise-obscured.

---
*Phase: 12-ci-quality-gates*
*Completed: 2026-07-09*

## Self-Check: PASSED

- FOUND: .planning/phases/12-ci-quality-gates/12-02-SUMMARY.md
- FOUND: commit c2268cb (Task 1)
- FOUND: commit 36a9f5d (Task 2)
