---
phase: 11-clarification-round-machine-alias-learning
plan: 10
subsystem: security
tags: [fastapi, webhook, sender-auth, spoofing, reply-resume]

# Dependency graph
requires:
  - phase: 11-07
    provides: /resolve single-CAS fix, app/main.py post-merge baseline this plan builds directly on top of
provides:
  - shared _reply_sender_ok(row, run) predicate in app/main.py re-asserting FIX-5 sender revalidation
  - WR-04 redelivery re-schedule seam now re-checks sender before dispatching _resume_pipeline
  - D-11-05 stranded-sweep seam now re-checks sender before dispatching _resume_pipeline
affects: [phase-11-followups, any future re-schedule/re-dispatch seam touching linked-but-unconsumed replies]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Shared re-assertable security predicate: a post-commit auth check (FIX-5) performed once at first delivery must be re-derived as a standalone pure predicate and re-invoked at every OTHER seam capable of re-dispatching the same privileged action from persisted state, not assumed transitively true from earlier processing-state flags (consumed_round/status) alone."

key-files:
  created: []
  modified:
    - app/main.py
    - tests/test_reply_redelivery.py

key-decisions:
  - "_reply_sender_ok defined as a pure (row, run) -> bool predicate placed near _finish_reply_resume, calling find_business_by_sender exactly once and mirroring its exact None-check + str-equality comparison — a genuine refactor-to-shared-predicate, not a new/divergent check."
  - "Both re-schedule seams (WR-04 duplicate branch, D-11-05 stranded sweep) call _reply_sender_ok as an ADDITIONAL condition alongside their existing awaiting_reply/consumed_round checks — sender-blocked candidates are silently skipped (logged at run_id-only granularity), never raise."
  - "Stranded sweep now calls repo.load_run(reply_row['run_id']) to obtain business_id for the check; this stays inside the existing swallow-on-failure try/except so a lookup failure still cannot 500 the dashboard."
  - "Test helper _seed_awaiting_reply_run_with_reply extended with an additive reply_from_addr override (defaults to the sender-matching COASTAL_EMAIL) so all 6 pre-existing tests are untouched in behavior."

requirements-completed: [CLAR2-06]

# Metrics
duration: ~25min
completed: 2026-07-06
---

# Phase 11 Plan 10: FIX-5 Re-assertion at Redelivery/Stranded-Sweep Seams Summary

**Closed GAP-5/CR-5: added a shared `_reply_sender_ok` predicate re-asserting FIX-5 sender revalidation at both the WR-04 redelivery re-schedule and the D-11-05 stranded-sweep re-schedule, so a reply that already failed sender auth on first delivery can never drive a victim's payroll via redelivery or a later dashboard load.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-06T21:12:00Z (approx, after STEP-0 sync)
- **Completed:** 2026-07-06T21:37:27Z
- **Tasks:** 1 (single TDD task per plan)
- **Files modified:** 2

## Accomplishments
- Added `_reply_sender_ok(row, run)` in `app/main.py`, a pure predicate that calls `find_business_by_sender` exactly once and reproduces `_finish_reply_resume`'s exact FIX-5 comparison, now reusable by any seam that re-dispatches a resume from a persisted, linked-but-unconsumed reply row.
- WR-04 duplicate-branch redelivery re-schedule (`inbound()`, `outcome == "duplicate"`) now dispatches `_resume_pipeline` only if `_reply_sender_ok(reply_row, linked_run)` is also true; logs a run_id-only warning when blocked.
- D-11-05 stranded-sweep loop (`runs_list()`) now loads the candidate run per stranded reply row and dispatches `_resume_pipeline` only if `_reply_sender_ok(reply_row, candidate_run)` is also true; same swallow-on-failure try/except scope preserved; logs a run_id-only warning when blocked.
- Added 2 new regression tests to `tests/test_reply_redelivery.py`: `test_redelivery_never_resumes_fix5_failed_reply` and `test_stranded_sweep_never_resumes_fix5_failed_reply`. Both were verified to FAIL on the pre-fix code (confirmed via a temporary revert of `app/main.py` and re-run) and PASS after the fix.
- Extended `_seed_awaiting_reply_run_with_reply` with an additive `reply_from_addr` keyword override (default preserves existing sender-matching behavior) so no existing test's fixture shape changed.

## Task Commits

Each task was committed atomically:

1. **Task 1: Re-assert FIX-5 at both redelivery re-schedule seams (GAP-5)** - `a20fc73` (fix)

**Plan metadata:** (this commit, see final_commit below)

## Files Created/Modified
- `app/main.py` - Added `_reply_sender_ok` predicate; wired into WR-04 duplicate-branch redelivery re-schedule and D-11-05 stranded-sweep loop in `runs_list()`.
- `tests/test_reply_redelivery.py` - Extended `_seed_awaiting_reply_run_with_reply` with a `reply_from_addr` override; added 2 GAP-5/CR-5 regression tests.

## Decisions Made
- Mirrored `_finish_reply_resume`'s exact sender comparison rather than writing a subtly different equivalent, per the plan's explicit instruction — this keeps the security-critical logic in exactly one place, conceptually, even though it now exists as two call sites plus the original inline check in `_finish_reply_resume` (left unchanged, since it runs pre-commit-adjacent in a different control-flow shape and the plan did not ask to refactor it out).
- Chose to skip (not raise) on a sender-mismatched candidate in both seams, consistent with the existing "swallow non-actionable candidates silently, log run_id-only" style already used for `needs_operator` exclusion in the same sweep.

## Deviations from Plan

None - plan executed exactly as written. The shared predicate signature, both call-site wiring points, and the test additions match the plan's `<action>` steps precisely.

## Issues Encountered

None. STEP-0 worktree sync required a merge (worktree HEAD was 7 plans/several merge-commits behind master — 11-01 through 11-07 were missing); merge was a clean fast-forward with zero conflicts, and post-merge baseline was confirmed at exactly 591 passed / 20 skipped before Task 1 began, matching the assignment's expected baseline.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- GAP-5/CR-5 is closed: a FIX-5-failed linked reply can never be resumed via redelivery or the stranded-reply sweep.
- Full offline suite green: 593 passed, 20 skipped (591 baseline + 2 new GAP-5 regression tests), 28 deselected.
- No known blockers for subsequent gap-closure plans (11-08/11-09 if applicable) or phase close-out.

## Self-Check: PASSED

- FOUND: app/main.py
- FOUND: tests/test_reply_redelivery.py
- FOUND: .planning/phases/11-clarification-round-machine-alias-learning/11-10-SUMMARY.md
- FOUND: commit a20fc73

---
*Phase: 11-clarification-round-machine-alias-learning*
*Completed: 2026-07-06*
