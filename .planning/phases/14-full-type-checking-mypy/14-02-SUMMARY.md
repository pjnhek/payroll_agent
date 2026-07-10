---
phase: 14-full-type-checking-mypy
plan: 02
subsystem: testing
tags: [mypy, typing, pydantic, openai, psycopg, postgres]

# Dependency graph
requires:
  - phase: 14-full-type-checking-mypy
    provides: Strict mypy configuration and pydantic plugin from Plan 14-01
provides:
  - Strict annotations for config, models, LLM prompts/client, and database substrate
  - Strict annotations for all app/db/repo aggregate modules
  - TYPE-01 app substrate ready for downstream type-checking plans
affects: [14-03, 14-04, 14-05, 14-06, 14-07, 14-08, 14-09, 14-10, full-repo-mypy]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Use ChatCompletionMessageParam for OpenAI-compatible chat message boundaries."
    - "Annotate optional repository connections as psycopg.Connection | None."
    - "Keep dict[str, Any] at dynamic psycopg row and JSONB boundaries only."

key-files:
  created: []
  modified:
    - app/models/contracts.py
    - app/llm/client.py
    - app/llm/prompts/clarify.py
    - app/llm/prompts/extract.py
    - app/llm/prompts/suggest.py
    - app/db/schema_introspect.py
    - app/db/repo/_shared.py
    - app/db/repo/demo.py
    - app/db/repo/emails.py
    - app/db/repo/pipeline_state.py
    - app/db/repo/roster.py
    - app/db/repo/runs.py

key-decisions:
  - "Measured app/db/repo/ before editing: no attr-defined or facade/re-export errors were reported, so app/db/repo/__init__.py remains unchanged."
  - "Used the installed OpenAI ChatCompletionMessageParam union instead of untyped message dictionaries."
  - "Kept Any limited to dynamic database-row/JSONB mappings and used explicit casts at JSONB load boundaries."

patterns-established:
  - "Repository functions expose psycopg.Connection | None for caller-owned transaction seams."
  - "Pydantic contract mapping helpers use their concrete nested dictionary shape."

requirements-completed: [TYPE-01]

coverage:
  - id: D1
    description: "Config, models, LLM, and app/db modules pass the plan-level strict mypy scope."
    requirement: TYPE-01
    verification:
      - kind: other
        ref: "uv run mypy app/__init__.py app/config.py app/models/ app/llm/ app/db/"
        status: pass
    human_judgment: false
  - id: D2
    description: "The repository annotation changes preserve the full hermetic test suite."
    requirement: TYPE-01
    verification:
      - kind: unit
        ref: "uv run pytest -q -m 'not integration and not live_llm'"
        status: pass
    human_judgment: false

# Metrics
duration: 10 min
completed: 2026-07-10
status: complete
---

# Phase 14 Plan 02: Typed Application Substrate Summary

**Strictly typed config, Pydantic models, OpenAI message boundaries, and psycopg repository modules with a green hermetic suite**

## Performance

- **Duration:** 10 min
- **Started:** 2026-07-10T18:17:00Z
- **Completed:** 2026-07-10T18:26:34Z
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments

- Completed the config/models/LLM foundation with concrete Pydantic mapping and OpenAI chat-message types; the pydantic mypy plugin reports no errors.
- Typed the non-repository database introspection boundary, including psycopg connections and parser accumulators.
- Typed all repository aggregate functions, shared transaction context managers, DB-row/JSONB return shapes, and optional connection seams.
- Settled the facade question empirically: the isolated pre-task run reported 67 errors in six implementation files, with no `attr-defined` or `app.db.repo`/`app.db` re-export errors; `app/db/repo/__init__.py` was therefore not changed.

## Verification

- `uv run mypy app/__init__.py app/config.py app/models/ app/llm/ app/db/` — `Success: no issues found in 25 source files`.
- `uv run pytest tests/test_models_contracts.py tests/test_llm_client.py -q` — 52 passed.
- `uv run pytest tests/test_bootstrap_safe_url.py tests/test_bootstrap_timeouts.py tests/test_check_schema_cli.py tests/test_schema_introspect.py tests/test_seed_roundtrip.py -q` — 35 passed, 8 skipped.
- `uv run pytest -q -m "not integration and not live_llm"` — 615 passed, 20 skipped, 31 deselected.

## Task Commits

Each task was committed atomically:

1. **Task 1: Annotate app/__init__.py, app/config.py, app/models/, and app/llm/** — `722db3c` (feat)
2. **Task 2: Annotate app/db/ non-repository modules** — `c4d63d4` (feat)
3. **Task 3: Annotate app/db/repo/ and measure facade exports** — `af5593e` (feat)

**Plan metadata:** final metadata commit records this summary and normal GSD state/roadmap updates.

## Files Created/Modified

- `app/models/contracts.py` — Concrete nested types for clarified-field conversion helpers.
- `app/llm/client.py` and `app/llm/prompts/*.py` — Typed OpenAI-compatible chat message lists and request branches.
- `app/db/schema_introspect.py` — Typed psycopg connection parameters and parser accumulators.
- `app/db/repo/` — Typed connection context managers, aggregate parameters, DB row mappings, and JSONB boundaries.

## Decisions Made

- Followed the import graph exactly: foundation, then LLM, then database and repository modules.
- Preserved the repository facade's existing import/export style because direct measurement showed no strict re-export errors.
- Added an explicit impossible-result guard to `create_run` so the optional psycopg `fetchone()` result is narrowed without an ignore or assertion.

## Deviations from Plan

None — plan executed exactly as written. No `# type: ignore` comments, assertions, or test changes were introduced.

## Issues Encountered

- Initial sandboxed `uv run` checks could not read uv's cached `.git` metadata. The exact commands were rerun with the required elevated permission; this caused no source or dependency changes.
- One psycopg `fetchone()` optional-result narrowing was required in `create_run`; it was handled with an explicit error guard and covered by the same repository/test gates.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

TYPE-01's config/models/LLM/database substrate is ready for downstream Phase 14 plans. The full repository remains behaviorally covered by the passing hermetic suite.

---
*Phase: 14-full-type-checking-mypy*
*Completed: 2026-07-10*

## Self-Check: PASSED

- Summary file exists at `.planning/phases/14-full-type-checking-mypy/14-02-SUMMARY.md`.
- Task commits `722db3c`, `c4d63d4`, and `af5593e` are present in git history.
