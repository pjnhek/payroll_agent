---
phase: 13-module-structure-boundaries
plan: 01
subsystem: database
tags: [python, psycopg, postgres, module-split, facade-pattern, monkeypatch]

# Dependency graph
requires:
  - phase: 12-ci-quality-gates
    provides: ruff + full-suite CI gates protecting this refactor
provides:
  - "app/db/repo/ package (6 files) replacing the flat 1,734-line app/db/repo.py"
  - "Stable full-attribute-surface facade so every existing import style and monkeypatch seam keeps working unchanged"
affects: [14-full-type-checking, 15-comment-hygiene]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Package facade re-exporting a FULL live attribute surface (not just public API) to preserve monkeypatch seams across a module-boundary split"
    - "Call-time (not module-level) package self-import inside a submodule (_shared._conn_ctx) to avoid circular-import-at-init while staying patchable via the facade"
    - "Same-module bare-name call chains (record_run_error -> set_status/_scrub) require test patch targets to move to the aggregate module directly, not the facade"

key-files:
  created:
    - app/db/repo/__init__.py
    - app/db/repo/_shared.py
    - app/db/repo/runs.py
    - app/db/repo/pipeline_state.py
    - app/db/repo/emails.py
    - app/db/repo/roster.py
    - app/db/repo/demo.py
  modified:
    - tests/test_persistence.py
    - tests/test_threading.py
    - tests/test_claim_status.py
    - tests/test_gateway.py
    - tests/test_clarify.py

key-decisions:
  - "Facade re-exports RUN_COLS in addition to the plan's named surface — tests/test_cr_regressions.py imports it directly (a genuine external reference the plan's app/scripts/eval-only grep census missed, caught by running the full suite)"
  - "record_run_error's internal set_status/_scrub calls are NOT made facade-patchable; the two affected tests retarget their monkeypatch to app.db.repo.runs directly, per the plan's explicit non-negotiable guidance"
  - "No invented cross-aggregate imports: pipeline_state.py has no sibling import of runs.py (set_pre_clarify_extracted/set_clarification_round confirmed to write only their own column); create_run has no call to get_record_only_flag"

requirements-completed: [STRUCT-02, STRUCT-04]

# Metrics
duration: 55min
completed: 2026-07-10
---

# Phase 13 Plan 01: Split app/db/repo.py into a package Summary

**Split the 1,734-line `app/db/repo.py` (~55 functions) into `app/db/repo/` with five aggregate modules (runs/pipeline_state/emails/roster/demo) plus `_shared.py`, behind a facade re-exporting the full live attribute surface so every import style and monkeypatch seam keeps working unchanged.**

## Performance

- **Duration:** 55 min
- **Started:** 2026-07-10T00:20:00Z (approx, worktree init)
- **Completed:** 2026-07-10T01:16:51Z
- **Tasks:** 2/2
- **Files modified:** 13 (7 created under app/db/repo/, 1 deleted app/db/repo.py, 5 test files retargeted)

## Accomplishments
- `app/db/repo.py` deleted; replaced by `app/db/repo/` package (six files), every function body moved **verbatim** — AST-diffed function-by-function against the original for the 17 functions in `runs.py` (the most review-sensitive aggregate) and confirmed identical.
- Facade (`__init__.py`) re-exports the full live attribute surface: public API (48 names) + `get_connection` + `_conn_ctx` + `_TERMINAL_STATUSES` + `_ACCENT_CLASS_MAP` + `_pad_references` + `_scrub` + `RUN_COLS` (the last one an in-session addition — see Deviations).
- `_shared._conn_ctx` resolves `get_connection` through the package at call time (not module-level), verified live: patching `repo.get_connection` with a stub and driving `_conn_ctx(None)` yields the stub's return value — the interception path works identically to pre-split.
- Six test-coupling points retargeted per the plan's census: two `record_run_error` interception tests (facade patch -> `app.db.repo.runs` patch), two whole-repo-layer source-inspection sweeps (facade `__file__` -> concatenated `inspect.getsource()` across all five aggregates, closing the Codex Round-2 vacuous-scan risk), one `inspect.getsource(repo_mod)` -> `inspect.getsource(app.db.repo.emails)` retarget, one `__file__`-based doc-sentinel retarget to `app.db.repo.runs`.
- Full suite green at the exact pre-split baseline: 663 tests collected (matches the plan's captured figure), 612 passed, 51 skipped, 0 failures. `ruff check .` clean across the whole repo.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create the app/db/repo/ package** - `5214a64` (feat)
2. **Task 2: Migrate the full repo test-coupling census, verify full suite green** - `ab87a49` (test)

## Files Created/Modified
- `app/db/repo/__init__.py` - package facade; pure re-exports, zero function bodies (`grep -c "^def " ` = 0)
- `app/db/repo/_shared.py` - `_conn_ctx` (call-time package-import fix) + `_nulltx`
- `app/db/repo/runs.py` - ingest/lifecycle + status CAS + sweep + error/scrub aggregate (17 functions, AST-verified verbatim)
- `app/db/repo/pipeline_state.py` - JSONB persistence aggregate (extracted/decision/line-items/clarify-round)
- `app/db/repo/emails.py` - email_messages audit log + threading/header lookups
- `app/db/repo/roster.py` - roster read (`load_roster_for_business`, `EMPLOYEE_COLS`)
- `app/db/repo/demo.py` - demo bindings + dashboard list queries
- `tests/test_gateway.py` - two retargets: `record_run_error` interception patch target, and the whole-repo f-string/named-placeholder sweep broadened to five modules
- `tests/test_persistence.py` - one retarget: `record_run_error`'s `_scrub`-raises interception patch target
- `tests/test_threading.py` - one retarget: `test_references_like_is_parameterized` now inspects `app.db.repo.emails`
- `tests/test_claim_status.py` - one retarget: the "two writers" doc-sentinel now reads `app/db/repo/runs.py`
- `tests/test_clarify.py` - one retarget: the no-`clarification_message_id`-column sweep broadened to five modules

## Decisions Made
- **RUN_COLS re-export added to the facade** (not in the plan's original named list): `tests/test_cr_regressions.py` does `from app.db.repo import RUN_COLS, load_business_name, update_known_alias` — a genuine external import the plan's grep census (scoped to `app/ scripts/ eval/`) did not surface because it only lives in `tests/`. Running the full suite caught the `ImportError` immediately; added the re-export rather than loosening the test, per the plan's own acceptance-criteria spirit ("re-export ONLY if grep finds an external reference" — the reference exists, just in a file outside the censused directories).
- **No indirection added for `record_run_error`'s internal calls**: per the plan's explicit instruction, `set_status`/`_scrub` calls inside `record_run_error` stay same-module bare-name lookups against `runs.py`'s own globals — the two affected tests move their `monkeypatch.setattr` target to `app.db.repo.runs` instead of adding facade-patchability indirection to production code.
- **No cross-aggregate sibling imports invented**: verified live that `set_pre_clarify_extracted`/`set_clarification_round` write only their own column (no `set_status` call), and `create_run` writes `record_only` directly with no call to `get_record_only_flag` — both confirmed absent via `grep` acceptance criteria.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Missing `RUN_COLS` re-export broke `tests/test_cr_regressions.py` collection**
- **Found during:** Task 2 (full-suite verification after Task 1's facade was built)
- **Issue:** `tests/test_cr_regressions.py:30` does `from app.db.repo import RUN_COLS, ...` — an external reference to the module constant `RUN_COLS` that the plan's census (a grep scoped to `app/ scripts/ eval/`) did not catch because the only import site is in `tests/`. Without the re-export, test collection failed with `ImportError: cannot import name 'RUN_COLS'`.
- **Fix:** Added `RUN_COLS` to `app/db/repo/__init__.py`'s imports and `__all__` list (sourced from `app.db.repo.runs`, where it already lived per D-02's aggregate assignment).
- **Files modified:** `app/db/repo/__init__.py`
- **Verification:** `uv run python -c "from app.db.repo import RUN_COLS; print(RUN_COLS[:20])"` succeeds; `uv run pytest tests/test_cr_regressions.py -q` passes 15/15.
- **Committed in:** `ab87a49` (Task 2 commit, alongside the test-coupling retargets discovered by the same full-suite run)

**2. [Rule 1 - Bug] Unicode escape-sequence corruption during initial `Write` of `_compile_name_pattern`'s regex pattern**
- **Found during:** Task 1 (writing `runs.py`)
- **Issue:** The `Write` tool call rendered the literal regex source text `\ẁ-ͯ` (inside a raw string and a docstring) as actual Unicode characters rather than the literal escape-sequence text, corrupting both the docstring example and the live `re.compile` pattern in `_compile_name_pattern` — a silent behavior change to the PII-scrub name-matching regex (a money/security-adjacent surface per the threat model's T-13-01).
- **Fix:** Detected via byte-level inspection (`content.find(b'Anchored with lookarounds')` showed non-ASCII bytes where `\ẁ-ͯ` should be); repaired with a targeted byte-level `bytes.replace()` restoring the exact original escape-sequence text, then verified via AST-level function-body comparison against the original `repo.py`'s `_compile_name_pattern` (byte-identical match).
- **Files modified:** `app/db/repo/runs.py`
- **Verification:** `ast.dump()` comparison of `_compile_name_pattern`'s function body against the original `app/db/repo.py` returns an exact match; full suite (including the PII-scrub regression tests in `tests/test_persistence.py`) passes.
- **Committed in:** `5214a64` (Task 1 commit — fixed before commit, not a follow-up)

---

**Total deviations:** 2 auto-fixed (1 blocking import fix, 1 bug fix caught before commit)
**Impact on plan:** Both fixes were necessary for correctness (missing import breaks collection; the regex corruption would have silently narrowed PII-scrub coverage). No scope creep — no assertion values changed, no new cross-aggregate coupling introduced.

## Issues Encountered
None beyond the two deviations documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `app/db/repo.py` (flat file) fully retired; `app/db/repo/` package is the sole DB accessor layer, ready for Phase 14 (full mypy adoption) to annotate five smaller, more tractable modules instead of one 1,734-line file.
- The facade's full-attribute-surface re-export pattern (and the same-module-bare-name-call caveat for monkeypatch) is now precedent for any future god-file split in this milestone (e.g. `app/main.py` -> APIRouter modules, if still in scope for a later plan).
- No blockers.

## TDD Gate Compliance

Not applicable — this plan's tasks are `type="auto"` without `tdd="true"`; the plan-level frontmatter is `type: execute`, not `type: tdd`.

## Self-Check: PASSED

- FOUND: app/db/repo/__init__.py
- FOUND: app/db/repo/_shared.py
- FOUND: app/db/repo/runs.py
- FOUND: app/db/repo/pipeline_state.py
- FOUND: app/db/repo/emails.py
- FOUND: app/db/repo/roster.py
- FOUND: app/db/repo/demo.py
- MISSING (expected, deleted): app/db/repo.py
- FOUND commit: 5214a64
- FOUND commit: ab87a49

---
*Phase: 13-module-structure-boundaries*
*Completed: 2026-07-10*
