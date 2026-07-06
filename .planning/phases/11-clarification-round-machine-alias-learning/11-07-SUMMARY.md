---
phase: 11-clarification-round-machine-alias-learning
plan: 07
subsystem: api
tags: [fastapi, state-machine, cas, operator-resume, gap-closure]

# Dependency graph
requires:
  - phase: 11-clarification-round-machine-alias-learning
    provides: resume_pipeline's from_status-parameterized single-CAS design (11-04), the /resolve route (11-04), and the cross-AI code review that found GAP-1/CR-1 (11-REVIEW.md)
provides:
  - "/resolve no longer pre-claims NEEDS_OPERATOR -> EXTRACTING; resume_pipeline's own claim_status CAS is the SOLE claim in the operator-resume path"
  - "A real end-to-end regression test proving a needs_operator run resolved via /resolve reaches awaiting_approval, driven through the REAL resume_pipeline (never mocked)"
affects: [11-clarification-round-machine-alias-learning verification/re-review, any future work touching /resolve or resume_pipeline's claim semantics]

# Tech tracking
tech-stack:
  added: []
  patterns: ["route validates + applies overrides, then unconditionally schedules the background resume — the callee (resume_pipeline) owns the sole atomic CAS, never the caller"]

key-files:
  created: []
  modified: [app/main.py, tests/test_needs_operator.py]

key-decisions:
  - "Deleted the route-level claim_status(NEEDS_OPERATOR, EXTRACTING) call entirely rather than adding a from_status=EXTRACTING-aware branch in resume_pipeline — the webhook's reply-resume path already proves the no-pre-claim pattern works, so /resolve now matches it exactly instead of introducing a second claim-ownership model."
  - "Kept test_resolve_applies_override_and_claims_on_valid_post as a narrow unit test (resume_pipeline still mocked) but flipped its assertion polarity: it now proves the route does NOT claim (status stays needs_operator) instead of asserting the route's own now-removed claim — this is the exact assertion that would have caught the original bug."

requirements-completed: [CLAR2-02]

# Metrics
duration: 35min
completed: 2026-07-06
---

# Phase 11 Plan 07: GAP-1/CR-1 Double-CAS Fix Summary

**Removed `/resolve`'s route-level `claim_status(NEEDS_OPERATOR, EXTRACTING)` pre-claim so `resume_pipeline`'s own CAS is the sole claimer, closing the silent-strand bug where every valid operator resolution was dropped and the run stuck forever in `EXTRACTING`.**

## Performance

- **Duration:** 35 min
- **Started:** 2026-07-06T20:44:00Z (approx, after STEP-0 sync)
- **Completed:** 2026-07-06T21:19:49Z
- **Tasks:** 1 (single-task plan)
- **Files modified:** 2

## Accomplishments
- Closed GAP-1 (CR-1) from `11-REVIEW.md`: `/resolve` no longer races `resume_pipeline`'s own atomic claim — deleted the pre-claim and its `if claimed:` gate, replaced with an unconditional `background_tasks.add_task(_operator_resume, ...)`.
- Added `test_resolve_drives_real_resume_pipeline_to_awaiting_approval`, a genuinely end-to-end regression test that seeds a real `needs_operator` run (via `create_run` + a legitimately-reachable direct state mutation matching exactly what `_clarify`'s round-cap branch leaves behind), POSTs to the real `/resolve` HTTP route, and asserts the run reaches `awaiting_approval` with a real computed paystub line item for James Okafor — driven through the REAL `resume_pipeline` (no monkeypatch of `resume_pipeline` or `_operator_resume`). Confirmed this test FAILS against the pre-fix code (`status == 'extracting'`) and PASSES after the fix.
- Updated `test_resolve_applies_override_and_claims_on_valid_post` (the existing test that had hidden the bug by mocking `resume_pipeline` and asserting the route's own now-removed claim) to instead assert the run's status is UNCHANGED at `needs_operator` immediately after the route call, plus asserts `resume_pipeline` was invoked exactly once with the correct `run_id`, `from_status=NEEDS_OPERATOR`, and the validated `overrides` mapping.

## Task Commits

1. **Task 1: Remove /resolve's pre-claim; let resume_pipeline own the sole CAS (GAP-1)** - `6d5ad0b` (fix)

**Plan metadata:** (this commit, following SUMMARY + state updates)

## Files Created/Modified
- `app/main.py` - `resolve()` route: deleted `claim_status(run_id, RunStatus.NEEDS_OPERATOR, RunStatus.EXTRACTING)` and its `if claimed:` guard; unconditionally calls `background_tasks.add_task(_operator_resume, run_id, overrides)`; docstring rewritten to describe the single-claim-owner model.
- `tests/test_needs_operator.py` - Added `_seed_needs_operator_run_real` helper + `test_resolve_drives_real_resume_pipeline_to_awaiting_approval` (real end-to-end proof); rewrote `test_resolve_applies_override_and_claims_on_valid_post`'s core assertion and docstring.

## Decisions Made
- The route's docstring previously described "THEN claim_status(...); on a successful claim, dispatch..." — rewritten to explain the route never claims and `resume_pipeline`'s CAS is the sole gate, matching the webhook path's established pattern (no second claim-ownership model introduced).
- Chose to keep the existing mocked unit test rather than delete it, since it still usefully isolates the route's Security V4 validation / override-application / remember-checkbox logic from the (separately, now really tested) resume-and-advance behavior — but flipped its assertion to prove the absence of a route-level claim, since the old assertion was itself the blind spot that hid CR-1.

## Deviations from Plan

None - plan executed exactly as written. The task's `<action>` steps (delete pre-claim, unconditional dispatch, docstring rewrite) and `<behavior>` (new real end-to-end test + updated mocked test) were followed precisely; all `<acceptance_criteria>` and `<verify>` commands pass as specified.

## Issues Encountered

**STEP-0 worktree sync:** This worktree's branch (`worktree-agent-a016a1443655050e8`) was forked from a stale point (`4318c3e`) — a sibling worktree (`agent-a4821321c52151e30`) had already advanced `master` to `aafff89` with phase 11 plans 01-06/09/10, `11-REVIEW.md`, and `11-07-PLAN.md` itself (none of which existed yet in this worktree). Ran `git merge master` (clean fast-forward, no conflicts) before Task 1, per the assignment's STEP-0 instructions. Post-merge baseline confirmed at exactly **588 passed, 20 skipped, 28 deselected** as expected.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- GAP-1/CR-1 is closed. The `/resolve` -> `resume_pipeline` seam now has a single claim owner, matching the webhook's reply-resume path.
- `11-REVIEW.md` still lists CR-2, CR-3, CR-4, CR-5, and WR-1/WR-2 as open findings for future gap-closure plans (11-09, 11-10, and any others) — this plan closed CR-1/GAP-1 only, per its explicit scope.
- Full offline suite green at 589 passed (588 baseline + 1 new test), 20 skipped, 28 deselected (integration/live_llm, correctly excluded).

---
*Phase: 11-clarification-round-machine-alias-learning*
*Completed: 2026-07-06*

## Self-Check: PASSED

- FOUND: `.planning/phases/11-clarification-round-machine-alias-learning/11-07-SUMMARY.md`
- FOUND: `app/main.py`
- FOUND: `tests/test_needs_operator.py`
- FOUND commit: `6d5ad0b`
