---
phase: 11-clarification-round-machine-alias-learning
plan: 09
subsystem: alias-learning
tags: [orchestrator, jsonb, postgres, alias-write, money-safety]

# Dependency graph
requires:
  - phase: 11-06
    provides: retrigger epoch mechanism (file-overlap sequencing only, no functional dependency)
provides:
  - _bind_evidence_for_token same-record tie for alias bind-on-confirmation (GAP-4/CR-4 closed)
  - JSONB merge write for set_alias_candidates, real repo + InMemoryRepo mirror (WR-1 closed)
affects: [alias-learning, orchestrator-resume-pipeline, repo-alias-candidates]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "same-record evidence tie: bind decisions must resolve from ONE reconciliation entry's own fields, never two independently-computed whole-run set memberships"
    - "JSONB read-modify-write via COALESCE(...) || %s::jsonb for additive per-key column writes shared by multiple callers"

key-files:
  created: []
  modified:
    - app/pipeline/orchestrator.py
    - app/db/repo.py
    - tests/conftest.py
    - tests/test_alias_write.py

key-decisions:
  - "Bind-on-confirmation now requires a SINGLE post-resume reconciliation entry whose submitted_name (normalized) equals either the token's own text or the suggested employee's own canonical full_name, AND resolved=True, AND matched_employee_id == suggested_id — never two independently-satisfied whole-run facts."
  - "set_alias_candidates changed from a full-column overwrite to a JSONB || merge (COALESCE-wrapped for NULL-safety), mirrored in InMemoryRepo as a dict merge, so multiple tokens across multiple rounds coexist correctly."
  - "Removed the now-dead _pre_resolved_ids whole-run diff computation (STEP A) since STEP C no longer diffs against it; _pre_reconciliation itself is retained (still used by Step E0's prior_matches deserialization)."
  - "Fixed test_resume_binding_uses_pre_vs_post_diff_not_single_resolved_count's empty-roster fixture to seed a real David Reyes employee via the existing _make_roster() helper — required because the new same-record tie needs the suggested employee's own full_name to resolve from the roster, which an empty roster cannot provide."

requirements-completed: [CLAR2-04]

# Metrics
duration: 45min
completed: 2026-07-06
---

# Phase 11 Plan 09: Close GAP-4/CR-4 (bind-on-inference) + WR-1 (alias-candidates clobber) Summary

**Bind-on-confirmation now requires same-record evidence via a new `_bind_evidence_for_token` helper, and `set_alias_candidates` is a JSONB merge write instead of a full-column overwrite — closing the exact "Dave/David worked separately" silent-misroute exploit and the multi-token clobber defect from the phase-11 code review.**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-07-06 (post STEP-0 worktree sync)
- **Completed:** 2026-07-06
- **Tasks:** 2 completed
- **Files modified:** 4 (app/pipeline/orchestrator.py, app/db/repo.py, tests/conftest.py, tests/test_alias_write.py)

## Accomplishments

- Closed GAP-4/CR-4: the bind-on-confirmation check in `resume_pipeline`'s STEP C no longer computes "suggested id newly resolved SOMEWHERE" and "token gone from unresolved SOMEWHERE" as two independent whole-run facts. A new `_bind_evidence_for_token(token, suggested_id, suggested_full_name, post_reconciliation)` helper requires ONE reconciliation entry to carry all the evidence: its `submitted_name` (normalized) must equal the token's own text or the suggested employee's own canonical `full_name`, AND that same entry must be `resolved=True` with `matched_employee_id == suggested_id`.
- Closed WR-1: `set_alias_candidates` in `app/db/repo.py` now executes `UPDATE payroll_runs SET alias_candidates = COALESCE(alias_candidates, '{}'::jsonb) || %s::jsonb, ... WHERE id = %s` instead of a blind column overwrite. `tests/conftest.py`'s `InMemoryRepo.set_alias_candidates` mirrors this as a dict merge.
- Added and verified a new exploit regression test (`test_resume_binding_exploit_unrelated_resolution_binds_nothing`) that reproduces the exact "No, Dave didn't work this period; David worked 5 hours separately" scenario from 11-REVIEW.md CR-4 — confirmed it fails against the pre-fix orchestrator.py (binds Dave→David) and passes after the fix.
- Added and verified a new WR-1 regression test (`test_set_alias_candidates_merges_across_two_tokens_two_rounds`) proving a confirmed bind for TokenA in round 1 survives an unrelated write for TokenB in round 2 — confirmed it fails against the pre-fix InMemoryRepo overwrite and passes after the fix.
- Fixed the one required fixture correction the plan flagged: `test_resume_binding_uses_pre_vs_post_diff_not_single_resolved_count` used an EMPTY roster, which would make the new same-record tie's `suggested_full_name` lookup resolve to `None` and break the legitimate confirmation bind (since "Dave Reyez" != "David Reyes" as raw token text). Seeded the real David Reyes employee via the file's existing `_make_roster()` helper instead.
- Confirmed both full-loop anchor tests (`test_full_loop_learns_alias_and_stops_asking`, `test_misname_reply_binds_nothing_end_to_end`) pass with ZERO changes — the real resolution chain already produces a reconciliation entry whose `submitted_name` equals the suggested employee's own `full_name`, satisfying the new same-record tie naturally.

## Task Commits

Each task was committed atomically:

1. **Task 1: Tie bind-on-confirmation to the token's OWN reconciliation record (GAP-4)** - `64be80f` (fix)
2. **Task 2: set_alias_candidates becomes a merge write, not an overwrite (WR-1)** - `8650d40` (fix)

**Plan metadata:** (this commit, docs: complete 11-09 plan)

## Files Created/Modified

- `app/pipeline/orchestrator.py` - Added `_bind_evidence_for_token` helper; rewrote STEP C's bind block to call it per pending token (resolving the suggested employee's own `full_name` from the already-loaded `roster`); removed the now-dead `_pre_resolved_ids` whole-run-diff computation from STEP A.
- `app/db/repo.py` - `set_alias_candidates` SQL changed from `alias_candidates = %s` to `alias_candidates = COALESCE(alias_candidates, '{}'::jsonb) || %s::jsonb`.
- `tests/conftest.py` - `InMemoryRepo.set_alias_candidates` changed from overwrite to dict-merge (`{**existing, **new}`), mirroring the real repo's JSONB `||`.
- `tests/test_alias_write.py` - Added `test_resume_binding_exploit_unrelated_resolution_binds_nothing` (GAP-4 exploit, proven RED-then-GREEN), `test_set_alias_candidates_merges_across_two_tokens_two_rounds` (WR-1 clobber, proven RED-then-GREEN), `test_repo_set_alias_candidates_sql_uses_jsonb_merge_not_overwrite` (static SQL-string pin); fixed the `_empty_roster` fixture in `test_resume_binding_uses_pre_vs_post_diff_not_single_resolved_count` to seed a real David Reyes employee via `_make_roster()`.

## Decisions Made

- **Same-record tie over pre/post set diffing:** the fix intentionally does NOT try to patch the old set-diff logic with an extra condition — it replaces the whole evidence model with a single-record lookup, because any set-based approach re-introduces the same class of bug (two unrelated facts both being individually true). This is a structural fix, not a narrower guard bolted onto the old shape.
- **Fail-closed on missing suggested_full_name:** if the suggested employee's id can't be found in the currently-loaded roster (should not happen — the id was persisted from this same roster at capture time), the helper falls back to matching only the token's own text. This can only narrow what matches (fail-closed), never widen it (fail-open) — preserving the never-learn-from-inference guarantee even in a degraded/unexpected state.
- **Removed dead code (`_pre_resolved_ids`) rather than leaving it unused:** grepped the whole `resume_pipeline` function first to confirm `_pre_resolved_ids` had no other reader after STEP C's rewrite; `_pre_reconciliation` itself is still read by Step E0 (prior_matches deserialization) so it was kept.
- **COALESCE-wrapped JSONB merge, not a bare `||`:** `NULL || jsonb` errors in Postgres, and a run that has never captured any alias candidate yet has `alias_candidates IS NULL` — `COALESCE(alias_candidates, '{}'::jsonb)` makes the merge NULL-safe on a fresh run without a separate initialization step.

## Deviations from Plan

None - plan executed exactly as written, including the one fixture correction the plan explicitly required (Task 1, action step 5's caveat about the empty-roster fixture) — that was anticipated and mandated by the plan itself, not an unplanned deviation.

**Total deviations:** 0
**Impact on plan:** None — implementation matches the plan's action steps and acceptance criteria directly.

## Issues Encountered

None. STEP-0 worktree sync (merge master, fast-forward 4318c3e..07f5976) completed cleanly with no conflicts before Task 1 began, confirming the 591-passed/20-skipped baseline.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- GAP-4/CR-4 and WR-1 are both closed; CLAR2-04 requirement satisfied.
- Full offline suite green: 594 passed, 20 skipped (591 baseline + 3 new regression tests across both tasks).
- No known stubs or threat flags introduced — this plan is a pure bug-fix on an existing write surface, adding stricter evidence requirements and a safer write primitive, with zero new external surface.
- Ready for the next Wave-2 gap-closure plan (11-10) or phase completion review.

---
*Phase: 11-clarification-round-machine-alias-learning*
*Completed: 2026-07-06*

## Self-Check: PASSED

- `app/pipeline/orchestrator.py` — FOUND
- `app/db/repo.py` — FOUND
- `tests/conftest.py` — FOUND
- `tests/test_alias_write.py` — FOUND
- Task 1 commit `64be80f` — FOUND in git log
- Task 2 commit `8650d40` — FOUND in git log
- Full offline suite: 594 passed, 20 skipped, 28 deselected (baseline 591 + 3 new tests)
