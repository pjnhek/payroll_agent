---
phase: 09-atomic-data-integrity
plan: 05
subsystem: testing
tags: [pytest, resume_pipeline, orchestrator, clarification-rounds, known-edge, regression-fixture]

# Dependency graph
requires:
  - phase: 07.5-clarification-reply-field-regression
    provides: resume_pipeline Round-1/Round-2 classify-first machinery, fake_repo/mock_llm conventions
provides:
  - A hermetic, unguarded (no DATABASE_URL skip) known-edge fixture proving the current
    multi-round context-loss behavior in resume_pipeline's combined-extraction path
  - An explicit, traceable deferred-finding entry in 09-CONTEXT.md for a future
    MONEY-class phase to consume
affects: [future MONEY-class phase touching resume_pipeline/_combined_context_email]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Known-edge / red-flag fixture: a test that asserts CURRENT (not desired)
      behavior, explicitly labeled so a future fix intentionally flips its
      assertion rather than being treated as a regression to chase back to green"
    - "Dedicated hermetic test module used specifically to avoid an existing
      module-level DATABASE_URL skip guard silently hiding a fixture offline"

key-files:
  created:
    - tests/test_multiround_context_edge.py
  modified:
    - .planning/phases/09-atomic-data-integrity/09-CONTEXT.md

key-decisions:
  - "Fixture placed in a NEW module (tests/test_multiround_context_edge.py), not
    tests/test_resume_pipeline.py, because that module's module-level DATABASE_URL
    skipif guard would silently skip this fixture in any offline environment"
  - "No production code changed — disposition (c) only; the actual fix (accumulate
    reply bodies, or diff against last-persisted extraction) is deferred to a
    future MONEY-class phase per 09-CONTEXT.md"

patterns-established:
  - "Known-edge fixture convention: docstring states plainly the test documents
    current-not-desired behavior; a future fix is expected to flip the assertion"

requirements-completed: [DATA-01]

# Metrics
duration: 12min
completed: 2026-07-04
---

# Phase 9 Plan 5: Multi-round context-loss known-edge fixture Summary

**A hermetic, unguarded regression fixture (`tests/test_multiround_context_edge.py`) proves the current silent-discard bug where a Round-1 clarification correction is reverted by Round-2's combined-context re-extraction — recorded as an explicit deferred finding in 09-CONTEXT.md, no production code touched.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-04T02:48:00Z
- **Completed:** 2026-07-04T03:00:34Z
- **Tasks:** 1
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- Added `tests/test_multiround_context_edge.py`, a new hermetic test module (fake_repo + mock_llm only, no live DB/LLM, no module-level skip guard) containing `test_multi_round_context_loss_known_edge`
- The fixture drives `resume_pipeline` through two real clarification rounds and proves the exact silent-discard chain 09-REVIEWS.md's Claude in-session review traced live: a Round-1 genuine correction (hours_regular 40→30) that is never restated in Round-2 is silently reverted to the ORIGINAL value (40) by `_combined_context_email`'s original-body + latest-reply-only context
- Updated `09-CONTEXT.md`'s Deferred Ideas entry to point at the correct (new) test module and record the Codex Round-2 revision rationale, so the finding stays traceable back to 09-REVIEWS.md for whichever future MONEY-class phase picks up dispositions (a) or (b)
- Verified `uv run pytest -q -m "not integration"` (full offline suite, 526 tests) passes with `DATABASE_URL` unset — no production code changed, zero regression risk

## Task Commits

Each task was committed atomically:

1. **Task 1: Fixture proving the multi-round context-loss known-edge (own hermetic module); record the deferral in 09-CONTEXT.md** - `8219b3a` (test)

**Plan metadata:** (this SUMMARY.md commit, made by the orchestrator per worktree convention)

_Note: this task was `tdd="true"` in the plan frontmatter, but its behavior is "prove existing behavior is unchanged" — the fixture passed on first write with no RED phase needed (there is no new implementation to drive to GREEN; the test documents current code, and current code is not touched by this plan). See "TDD Gate Compliance" below._

## Files Created/Modified
- `tests/test_multiround_context_edge.py` - New hermetic test module; `test_multi_round_context_loss_known_edge` proves the current multi-round context-loss silent-discard behavior (KNOWN EDGE / RED-FLAG fixture, not a "this is fine" green check)
- `.planning/phases/09-atomic-data-integrity/09-CONTEXT.md` - Updated the existing Deferred Ideas entry ("Multi-round context loss") to reference the correct new test module path and record the Codex Round-2 revision rationale (module-level skip guard issue)

## Decisions Made
- Followed the plan's revision note exactly: placed the fixture in a brand-new module rather than `tests/test_resume_pipeline.py`, since that module's `pytest.mark.skipif(not os.environ.get("DATABASE_URL"), ...)` guard (lines 41-48) would silently skip any test added to it whenever `DATABASE_URL` is unset — contradicting the "hermetic, runs with `-m not integration`" claim this fixture must satisfy.
- Reused (by copying, not importing) `tests/test_resume_pipeline.py`'s helper functions (`_mk_extracted`, `_mk_match`, `_seed_run`, `_inbound`, `_extraction_json`, `_suggestion_json`, `_set_run_awaiting_reply`) verbatim to keep the new module import-independent of the guarded one, per the plan's `read_first` guidance.
- Read persisted Round-1 extraction data directly from `fake_repo.load_run(run_id)["extracted_data"]` (not `load_pre_clarify_extracted`, which is the never-overwritten pre-clarify snapshot, a distinct baseline per D-19/D-28) — verified against `InMemoryRepo.persist_extracted`'s actual storage shape in `tests/conftest.py`.
- Kept the docstrings' explanation of *why* the fixture avoids `tests/test_resume_pipeline.py`'s skip guard phrased without the literal strings `pytestmark`/`skipif` in prose, so the plan's own verification grep (`grep -n "pytestmark\|skipif" tests/test_multiround_context_edge.py` must return nothing) passes cleanly — the explanation is preserved via "module-level conditional-skip marker" language instead.

## Deviations from Plan

None - plan executed exactly as written. The one adjustment (rewording the docstring's guard explanation to avoid literal `pytestmark`/`skipif` substrings) was made proactively during authoring to satisfy the plan's own manual verification command, not a deviation rule fix after the fact — no incorrect code was written and reverted.

## TDD Gate Compliance

This plan's single task carries `tdd="true"` in its frontmatter, but its `<behavior>` is "prove CURRENT, already-existing behavior is unchanged" rather than "drive new behavior into existence." There is no RED phase in the conventional sense (no implementation is being added for this test to fail against first) — the fixture is expected to (and did) pass on first run, because it documents pre-existing orchestrator behavior. No production code was written or is expected to change as a result of this task, so a `feat(...)` GREEN commit does not apply. The single `test(09-05): ...` commit is the complete and correct commit shape for a known-edge documentation fixture; this is intentional per the plan's disposition (c) and not a gate-compliance gap.

## Known Stubs

None. This plan introduces a test file and a documentation update only — no UI, no data-rendering component, no placeholder values.

## Threat Flags

None. The plan's own `<threat_model>` disposition ("accept, documented, deferred") already covers the one relevant surface (T-09-21, the multi-round context-loss data-integrity gap); this plan adds no new network endpoint, auth path, file-access pattern, or schema change.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- The finding is now fully traceable: 09-REVIEWS.md → 09-CONTEXT.md's Deferred Ideas ("Multi-round context loss" entry, revised to point at `tests/test_multiround_context_edge.py`) → this concrete, already-passing regression fixture.
- Nothing in this plan blocks Phase 9's DATA-01/02/03 requirements; no production code was changed.
- A future MONEY-class phase (same family as Phase 7.5's field-regression work) has a ready-made regression target: when disposition (a) (accumulate reply bodies) or (b) (diff against last-persisted extraction) is implemented, `test_multi_round_context_loss_known_edge`'s final assertion (`hours_regular == 40`) is expected to flip to fail — at which point the test should be updated to assert the corrected value (30) or retired, per its own docstring guidance.

## Self-Check: PASSED

- FOUND: tests/test_multiround_context_edge.py
- FOUND: .planning/phases/09-atomic-data-integrity/09-05-SUMMARY.md
- FOUND commit: 8219b3a (test(09-05): known-edge fixture for multi-round context loss)

---
*Phase: 09-atomic-data-integrity*
*Completed: 2026-07-04*
