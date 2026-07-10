---
phase: 13-module-structure-boundaries
plan: 04
subsystem: testing
tags: [python, ast, static-analysis, regression-guard, module-boundaries]

# Dependency graph
requires:
  - phase: 13-module-structure-boundaries (plan 01)
    provides: app/db/repo/ package facade (D-01/D-03 declared internal-plumbing
      pattern this guard's exemption logic is scoped against)
  - phase: 13-module-structure-boundaries (plan 02)
    provides: app/pipeline/{alias_learning,clarification,delivery}.py split,
      including clarification.py's TYPE_CHECKING-guarded _RunStagesResult import
  - phase: 13-module-structure-boundaries (plan 03)
    provides: app/routes/ package split (this plan found and fixed one new
      BOUND-01 violation introduced by that split — see Deviations)
provides:
  - "tests/test_bound01_private_imports.py — permanent AST-walking CI gate
    catching cross-module private-name coupling (ImportFrom absolute +
    resolved-relative, and module._private attribute access)"
  - "Phase 13 closing full-suite + full-repo-lint sign-off (STRUCT-04)"
affects: [14-full-type-checking, 15-comment-hygiene]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "AST-walking static scanner (ast.parse + ast.walk) as a permanent pytest
      test, not a ruff rule — ruff's PLC2701 has a same-package exemption and
      does not inspect function bodies, so it misses this codebase's actual
      violation shapes (confirmed in 13-RESEARCH.md)"
    - "TYPE_CHECKING-guarded ImportFrom nodes are exempted from the scan —
      never executed at runtime, so they cannot break a monkeypatch seam,
      which is this guard's actual threat model (T-13-13)"
    - "A single, narrowly-scoped declared-exemption constant
      (_DECLARED_INTERNAL_PLUMBING_PACKAGE = 'app.db.repo') encodes D-01/D-03's
      documented intra-package facade/plumbing re-export pattern, rather than
      a general 'same top-level package is fine' rule that would have masked
      the genuine app.routes.runs -> app.routes.templating violation found
      during this plan's own execution"

key-files:
  created:
    - tests/test_bound01_private_imports.py
  modified:
    - app/routes/templating.py
    - app/routes/runs.py

key-decisions:
  - "Facade-boundary exemption applied to BOTH the ImportFrom check (new,
    this plan) and the attribute-access check (as originally specified) —
    the plan's task text only specified the attribute-access exemption, but
    running the guard against the live, fully-split codebase surfaced that
    app/db/repo/__init__.py's own declared facade re-export (D-01) and its
    aggregate modules' declared _shared.py sibling imports (D-03) are BOTH
    ImportFrom-shaped, not attribute-access-shaped, and would have false-
    positived without an equivalent, narrowly-scoped exemption"
  - "TYPE_CHECKING-guarded imports are exempted globally (not just for
    clarification.py's specific case) since a node inside `if TYPE_CHECKING:`
    is provably dead at runtime for any file, not a per-file carve-out"
  - "app/routes/runs.py's import of templating._badge_class_filter/
    _badge_label_filter is a genuine BOUND-01 violation (not exempted) —
    fixed by promoting both to public names (badge_class_filter/
    badge_label_filter), the same BOUND-01 rename pattern established in
    13-02 for validate.HOURS_FIELDS/is_paid and reconcile_names.normalize_name"

requirements-completed: [BOUND-01, STRUCT-04]

# Metrics
duration: 50min
completed: 2026-07-10
---

# Phase 13 Plan 04: BOUND-01 AST-walking regression guard + phase-closing verification sweep Summary

**Added `tests/test_bound01_private_imports.py`, an AST-walking scanner (ImportFrom absolute + resolved-relative, plus module._private attribute access) that is the permanent BOUND-01 CI gate; running it against the fully-split codebase surfaced and fixed one genuine violation the 13-03 router split introduced (badge filter functions), and required extending the plan's facade-boundary exemption from attribute-access-only to also cover the repo package's own declared ImportFrom re-export pattern (D-01/D-03) — full suite green at 614 passed (612 baseline + 2 new tests), ruff clean.**

## Performance

- **Duration:** 50 min
- **Started:** 2026-07-10T01:25:00Z (approx, worktree init/merge)
- **Completed:** 2026-07-10T02:16:11Z
- **Tasks:** 1/1
- **Files modified:** 3 (1 created, 2 fixed)

## Accomplishments

- `tests/test_bound01_private_imports.py` created with the scanner's detection
  logic factored into plain, directly-testable helper functions
  (`_module_name_and_is_package`, `_resolve_import_from_target`,
  `_scan_import_from_violations`, `_scan_attribute_violations`,
  `scan_tree_for_violations`) plus two pytest entry points.
- Module-name/`is_package` computation strips `__init__` correctly
  (`app/routes/__init__.py` -> `app.routes`, `is_package=True`).
- Relative-import resolution (`node.level > 0`) walks up from the importing
  file's own module name, honoring `is_package` per the Codex Round 2 fix:
  a `level=1` import inside a package's own `__init__.py` resolves relative to
  that same package name, not one level further up.
- Both resolution branches (absolute `node.level == 0`, resolved-relative
  `node.level > 0`) converge on ONE shared underscore-flagging step — no
  separate, weaker check for the relative case.
- Attribute-access check scoped to names bound by a module-level `ast.Import`
  of a first-party module, with the facade-boundary exemption keyed off
  whether the imported target is itself a package (`__init__.py`), not a
  hardcoded name list.
- `test_scanner_detects_synthetic_violation` proves the scanner against a
  constructed `tmp_path` tree covering all three violation shapes (function-body
  absolute ImportFrom, module-attribute-access, and a level-2 relative import
  crossing a real package boundary out of a nested `sub/` subpackage) and all
  legitimate-pattern exemptions (same-module reference, bare relative module
  import, and a level-1 relative import inside a package's own `__init__.py`).
- `test_no_cross_module_private_imports` — the live CI gate — passes clean
  against the fully-split `app/`, `eval/`, `scripts/` trees after the one fix
  documented below.
- Full suite: 614 passed, 51 skipped, 665 collected (baseline 612/51/663 plus
  exactly the 2 new guard tests). `uv run ruff check .` reports zero
  violations repository-wide.
- `grep -rn "repo\._conn_ctx" scripts/` confirms 5 live call sites; the guard
  correctly does not flag any of them (facade-boundary exemption verified
  against the real, pre-existing pattern, not just the synthetic fixture).

## Task Commits

Each task was committed atomically:

1. **Task 1: Write and validate the AST-walking BOUND-01 guard, fix the one violation it surfaced, run the full phase-closing verification sweep** - `262888d` (test)

## Files Created/Modified

- `tests/test_bound01_private_imports.py` (created) — the BOUND-01 regression guard + its own synthetic-fixture unit test
- `app/routes/templating.py` (modified) — `_badge_class_filter`/`_badge_label_filter` promoted to `badge_class_filter`/`badge_label_filter` (BOUND-01 rename; Jinja filter registration updated to match)
- `app/routes/runs.py` (modified) — import + two call sites in `run_status` retargeted to the promoted public names

## Decisions Made

- **Extended the facade-boundary exemption to the ImportFrom check, not just attribute-access as the plan literally specified.** Running the scanner against the live, fully-split codebase (not just the synthetic fixture) surfaced that `app/db/repo/__init__.py`'s own facade re-export (`from app.db.repo.runs import _scrub, _TERMINAL_STATUSES, ...`) and its aggregate modules' `_shared.py` sibling imports (`from app.db.repo._shared import _conn_ctx`) are BOTH `ImportFrom`-shaped — the exact declared, deliberate D-01/D-03 pattern from 13-01, not an oversight. The plan's task text only described a facade exemption for the attribute-access form (step 5); a literal implementation of step 3 with no equivalent exemption would have permanently broken the guard against the repo package's own documented compatibility surface. Added a narrowly-scoped `_DECLARED_INTERNAL_PLUMBING_PACKAGE = "app.db.repo"` constant + `_in_declared_plumbing_package()` helper, deliberately NOT a general "same top-level package" rule (verified against the counter-example below, which is also same-package but a genuine violation).
- **TYPE_CHECKING-guarded ImportFrom nodes are exempted.** `app/pipeline/clarification.py`'s `if TYPE_CHECKING: from app.pipeline.orchestrator import _RunStagesResult` (13-02, reviewed and approved by Codex Round 2 as "the `TYPE_CHECKING` plan is appropriate") is never executed at runtime — this guard's threat model (T-13-13) is about runtime coupling that could break a monkeypatch seam, which cannot happen for code that never runs. Implemented as a general `_type_checking_only_nodes()` helper (any `if TYPE_CHECKING:` block's body), not a clarification.py-specific carve-out.
- **`app/routes/runs.py` importing `templating._badge_class_filter`/`_badge_label_filter` is a genuine violation, not exempted.** Both functions are same-package (`app.routes`) as the facade-exemption counter-example proves same-package alone isn't sufficient grounds for exemption — `runs.py`'s `run_status` JSON endpoint calls both directly, a real cross-module private-name dependency introduced by the 13-03 split (these two functions didn't exist pre-split; RESEARCH.md's own illustrative pattern for this exact file only imports `templates`, not the filter functions). Fixed via the same BOUND-01 promotion pattern used throughout 13-02/13-03: renamed both to public names, updated the Jinja filter registration and both call sites.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Scanner's ImportFrom check needed a facade exemption the plan only specified for attribute-access**
- **Found during:** Task 1, first run of `test_no_cross_module_private_imports` against the live tree
- **Issue:** A literal implementation of the plan's step 3 (ImportFrom resolution + flagging, with no exemption clause) produced 17 false-positive violations — all against `app/db/repo/__init__.py`'s own declared facade re-export and its aggregate modules' declared `_shared.py` sibling imports, both explicitly documented as deliberate design in `.planning/phases/13-module-structure-boundaries/13-CONTEXT.md` (D-01, D-03) and confirmed built exactly this way in `13-01-SUMMARY.md`. Trusting the guard as literally spec'd would have made it impossible to keep the repo package's own compatibility-surface facade, defeating BOUND-01's actual purpose (catching *unintended* internals coupling, not flagging a documented, tested, intentional pattern).
- **Fix:** Added a narrowly-scoped `_in_declared_plumbing_package()` check (keyed to the single package `app.db.repo`, not a general same-package rule) applied identically to the ImportFrom resolution step, alongside the existing attribute-access facade exemption.
- **Files modified:** `tests/test_bound01_private_imports.py`
- **Verification:** `uv run pytest tests/test_bound01_private_imports.py -q -v` — both tests pass; `test_no_cross_module_private_imports` correctly finds zero violations in `app/db/repo/` while `test_scanner_detects_synthetic_violation`'s own assertions confirm the scanner still detects out-of-package violations.
- **Committed in:** `262888d` (single task commit — fixed before commit, not a follow-up)

**2. [Rule 2 - Missing critical functionality] TYPE_CHECKING-guarded import needed an explicit exemption**
- **Found during:** Task 1, same first run
- **Issue:** `app/pipeline/clarification.py`'s `if TYPE_CHECKING: from app.pipeline.orchestrator import _RunStagesResult` (a deliberate, Codex-Round-2-approved design from 13-02, existing specifically to avoid a runtime circular import while keeping the type hint accurate) was flagged as a violation. This code path never executes — it exists only for static type checkers — so it cannot break a monkeypatch seam, the guard's stated threat model.
- **Fix:** Added `_type_checking_only_nodes()`, walking every `if TYPE_CHECKING:` block's body and excluding those nodes from the ImportFrom scan.
- **Files modified:** `tests/test_bound01_private_imports.py`
- **Verification:** Same full-suite + targeted guard run as above.
- **Committed in:** `262888d`

**3. [Rule 1 - Bug] Genuine BOUND-01 violation found: `app/routes/runs.py` importing private badge-filter functions from `app/routes/templating.py`**
- **Found during:** Task 1, same first run
- **Issue:** `app/routes/runs.py`'s `run_status` JSON polling endpoint calls `_badge_class_filter(status)`/`_badge_label_filter(status)` directly — a genuine cross-module private-name reference the 13-03 split introduced (these functions did not exist before that split; the original `app/main.py`'s badge-mapping logic was inlined differently). This is exactly the class of bug BOUND-01 exists to catch: an unintended internals dependency across a module boundary, distinct from the two declared-design cases above.
- **Fix:** Promoted both functions to public names (`badge_class_filter`, `badge_label_filter`) in `templating.py`, matching the established BOUND-01 rename pattern from 13-02 (`validate.HOURS_FIELDS`/`is_paid`, `reconcile_names.normalize_name`); updated the Jinja filter registration lines and both call sites in `runs.py`. Confirmed zero remaining references to the old private names anywhere in the repo (`grep -rn "_badge_class_filter\|_badge_label_filter"` after the fix returns only the (removed) definitions — none).
- **Files modified:** `app/routes/templating.py`, `app/routes/runs.py`
- **Verification:** Full suite still green (614 passed) after the rename; `uv run ruff check .` clean; `test_no_cross_module_private_imports` passes.
- **Committed in:** `262888d`

---

**Total deviations:** 3 auto-fixed (2 Rule 2 — extending the plan's facade exemption to a second violation form + exempting dead-at-runtime TYPE_CHECKING code; 1 Rule 1 — a genuine pre-existing bug the guard itself caught and this plan's task text explicitly anticipates fixing as part of validating the guard against the live tree).
**Impact on plan:** No scope creep. All three fixes are either (a) closing a gap in the plan's own exemption design so the guard doesn't false-positive against this codebase's own declared, tested facade pattern, or (b) fixing a genuine BOUND-01 violation using the exact promotion technique already established by 13-02/13-03 — precisely the guard doing its job. No assertion-value changes, no behavior changes beyond the two renamed (never externally imported) private functions.

## Issues Encountered

None beyond the three deviations documented above — all found and fixed during the guard's own first live-tree run, before the task commit.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Phase 13 is now fully closed: all three god-file splits (13-01 repo package, 13-02 pipeline modules, 13-03 routes package) are merged, and this plan's permanent CI gate (`tests/test_bound01_private_imports.py`) runs on every future `uv run pytest -q` invocation (already wired into Phase 12's `ci.yml`), preventing regression of any of the phase's BOUND-01 promotions.
- All five ROADMAP.md Phase 13 success criteria are independently verifiable: `app/main.py` is thin assembly (16 lines) with routers split by concern; `app/db/repo.py` is a per-aggregate package behind a stable facade; alias-learning helpers are their own module (`app/pipeline/alias_learning.py`); the full suite passed throughout with import-path-only changes; the AST-based guard confirms zero cross-module `_private` references remain outside the one documented, narrow package-facade exemption.
- Ready for Phase 14 (full mypy adoption) — all god-files are now right-sized modules, and BOUND-01's promoted public names give mypy cleaner, more stable cross-module signatures to annotate.
- No blockers.

## TDD Gate Compliance

Not applicable — this plan's task is `type="auto"` without `tdd="true"`; the plan-level frontmatter is `type: execute`, not `type: tdd`.

## Self-Check: PASSED

- FOUND: tests/test_bound01_private_imports.py
- FOUND: app/routes/templating.py (modified)
- FOUND: app/routes/runs.py (modified)
- FOUND commit: 262888d

---
*Phase: 13-module-structure-boundaries*
*Completed: 2026-07-10*
