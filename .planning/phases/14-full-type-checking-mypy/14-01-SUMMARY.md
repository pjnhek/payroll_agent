---
phase: 14-full-type-checking-mypy
plan: 01
subsystem: testing
tags: [mypy, typing, pydantic, uv, pytest]

# Dependency graph
requires:
  - phase: 13-module-structure-boundaries
    provides: final module layout and module-object import conventions
provides:
  - committed strict mypy configuration covering app, eval, scripts, and tests
  - mypy 2.2.0 dev dependency locked through uv
  - regression coverage and fix for the eval live-record client import
  - narrow Protocol/cast typing seam for Resend's runtime ResponseDict shape
  - concrete BracketRow return type for the federal withholding bracket lookup
affects: [14-02, 14-03, 14-04, full-type-checking, CI typecheck]

# Tech tracking
tech-stack:
  added: [mypy 2.2.0]
  patterns: [strict mypy config with scoped tests and untyped-dependency overrides, narrow Protocol at SDK typing boundary]

key-files:
  created: []
  modified:
    - pyproject.toml
    - uv.lock
    - eval/run_eval.py
    - tests/test_eval_wiring.py
    - app/email/gateway.py
    - app/pipeline/federal_withholding.py

key-decisions:
  - "Keep mypy scope and strictness in committed pyproject.toml config so bare local and CI commands have identical coverage."
  - "Use a narrow _ReceivedEmailLike Protocol plus cast for Resend's ResponseDict runtime attributes; preserve existing attribute access and avoid Any."
  - "Keep the eval import regression fix separate from its RED test, and keep the BracketRow annotation separate from the gateway change."

patterns-established:
  - "Runtime app/eval/scripts code uses strict=true; tests relax annotation requirements while retaining check_untyped_defs=true."
  - "Untyped third-party dependencies receive only scoped [[tool.mypy.overrides]] entries with an inline justification, never a global ignore_missing_imports."

requirements-completed: [TYPE-01, TYPE-02]

coverage:
  - id: D1
    description: "Committed mypy 2.2.0 configuration and uv lockfile cover app, eval, scripts, and tests with strict runtime checking and documented scoped overrides."
    requirement: TYPE-01
    verification:
      - kind: other
        ref: "uv run mypy --version"
        status: pass
      - kind: other
        ref: "uv run mypy app/config.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Eval --record lazy import resolves the client module without ImportError."
    requirement: TYPE-02
    verification:
      - kind: unit
        ref: "tests/test_eval_wiring.py::test_record_extraction_llm_client_import_resolves"
        status: pass
      - kind: unit
        ref: "uv run pytest tests/test_eval_wiring.py -q"
        status: pass
    human_judgment: false
  - id: D3
    description: "Gateway runtime behavior remains unchanged while the Resend response shape and withholding bracket return are typed concretely."
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_gateway.py tests/test_federal_withholding.py tests/test_tax_tables_2026.py -q"
        status: pass
      - kind: other
        ref: "uv run mypy app/email/gateway.py; assert no gateway [attr-defined] lines"
        status: pass
    human_judgment: false

# Metrics
duration: 4min
completed: 2026-07-10
status: complete
---

# Phase 14 Plan 01: Strict mypy baseline and targeted type fixes Summary

**Strict mypy 2.2.0 baseline with scoped overrides, a test-first eval import fix, and behavior-neutral gateway/withholding type corrections**

## Performance

- **Duration:** 4 min
- **Started:** 2026-07-10T18:09:49Z
- **Completed:** 2026-07-10T18:13:31Z
- **Tasks:** 3 completed
- **Files modified:** 6

## Accomplishments

- Added mypy 2.2.0 through `uv add --dev mypy`, with the committed strict configuration, pydantic plugin, full phase scope, and narrowly documented `tests.*`/`reportlab.*` overrides.
- Added and committed a RED regression test, then fixed the `_record_extraction` lazy import to bind `app.llm.client` as a module object.
- Preserved gateway runtime attribute access with a three-member Protocol and cast, and corrected `_find_bracket` to return the concrete `BracketRow` type.

## Task Commits

Each task was committed atomically:

1. **Task 1: Author [tool.mypy] config and add mypy as a dev dependency** - `6c48d7b` (chore)
2. **Task 2 RED: Fix eval/run_eval.py's undefined llm_client import** - `e8b93f2` (test)
3. **Task 2 GREEN: Fix eval/run_eval.py's undefined llm_client import** - `8d21737` (fix)
4. **Task 3 gateway: Resolve ReceivedEmail response typing** - `cd7c53b` (fix)
5. **Task 3 withholding: Type the concrete bracket lookup result** - `2481483` (fix)

## Files Created/Modified

- `pyproject.toml` - Adds mypy 2.2.0 and the committed strict configuration.
- `uv.lock` - Locks mypy and its transitive dependencies.
- `eval/run_eval.py` - Uses the module-object client import on the live record path.
- `tests/test_eval_wiring.py` - Regression test for the lazy import path.
- `app/email/gateway.py` - Adds `_ReceivedEmailLike` and a narrow `cast`; runtime attribute access is unchanged.
- `app/pipeline/federal_withholding.py` - Imports `BracketRow` and annotates `_find_bracket` precisely.

## Decisions Made

- Runtime type checking is strict by default; only test annotation requirements are relaxed, while test bodies remain checked.
- The Resend mismatch is handled at the SDK boundary with a Protocol/cast rather than changing field access or widening to `Any`.
- Task 2 follows D-08's test-first protocol with distinct RED and GREEN commits.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The sandbox initially denied uv cache access and Git index-lock creation. Both required commands succeeded after the environment's approved elevated access path was used; no package or implementation substitutions were made.
- The targeted `uv run mypy app/email/gateway.py` command exits nonzero because later Phase 14 plans still own unrelated strict errors in imported/remainder gateway code. The required assertion passed: zero `app/email/gateway.py` `[attr-defined]` errors remained. The full gateway tests passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 14-02 can continue from the committed mypy configuration and use bare `uv run mypy` for ground-truth error counts.
- The gateway Protocol fix intentionally leaves other gateway strict-mode categories for Plan 14-03 Task 2.

---
*Phase: 14-full-type-checking-mypy*
*Completed: 2026-07-10*

## Self-Check: PASSED

- Summary file exists at the required phase path.
- All five production/task commits are present in Git history.
- Required summary frontmatter fields, completed status, requirements, and verification evidence are present.
