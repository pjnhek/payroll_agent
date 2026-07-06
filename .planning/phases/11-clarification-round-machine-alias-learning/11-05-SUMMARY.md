---
phase: 11-clarification-round-machine-alias-learning
plan: 05
subsystem: api
tags: [fastapi, webhook, postgres, background-tasks, round-machine, redelivery, retrigger]

# Dependency graph
requires:
  - phase: 11
    plan: 01
    provides: "clarification_round/round/consumed_round columns, mark_reply_consumed/get_inbound_by_message_id/clear_reply_context/find_stranded_unconsumed_replies repo primitives, InMemoryRepo mirrors"
  - phase: 11
    plan: 03
    provides: "resume_pipeline writes the D-11-02 consumed marker at its own CAS claim — the load-bearing seam that makes a redelivered/stranded reply's consumed_round genuinely reflect runtime state"
provides:
  - "WR-04 redelivery re-schedule (D-11-03): a redelivered webhook whose persisted reply row is unconsumed AND whose run is still awaiting_reply re-schedules _resume_pipeline; a consumed reply's redelivery, or a redelivery to a non-awaiting_reply run, stays a no-op duplicate"
  - "D-11-05 stranded-unconsumed-reply auto-resume beside the existing D-9-11 sweep on every runs-list load; needs_operator runs are structurally excluded (D-11-06)"
  - "WR-06 retrigger clears ALL reply context (clarified_fields + pre_clarify_extracted + clarification_round + alias_candidates) at the single post-claim convergence point reached by both retrigger CAS branches, before _run_pipeline is scheduled (D-11-04)"
  - "app.main._row_to_inbound(row) -> InboundEmail — the single pure conversion point both re-schedule seams reuse, using the persisted (already-cleaned) body_text verbatim, never re-cleaning a redelivered request body"
  - "repo.get_inbound_by_message_id / repo.find_stranded_unconsumed_replies widened to SELECT the full InboundEmail field set (id, in_reply_to, references_header, created_at)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single conversion-point bridge (_row_to_inbound): both runtime re-schedule seams (webhook duplicate branch, runs-list sweep) build their InboundEmail through one pure function reading a persisted row — never re-parsing/re-cleaning a request body a second time"
    - "CAS-gated double-schedule safety: both new re-schedule triggers rely entirely on resume_pipeline's existing AWAITING_REPLY->EXTRACTING claim to collapse N schedules into one; no new locking primitive introduced"
    - "Single post-claim convergence point for context-clearing: rather than duplicating a clear_reply_context call inside each of retrigger's two winning branches, the clear sits once at the point both branches already share (`if claimed: ...`)"

key-files:
  created:
    - tests/test_reply_redelivery.py
  modified:
    - app/main.py
    - app/db/repo.py
    - tests/test_cr_regressions.py

key-decisions:
  - "_row_to_inbound lives in app/main.py (not repo.py) since it builds a Pydantic contract object, not a DB row — repo.py stays SQL-only; main.py is the one place that owns the row->InboundEmail bridge for both re-schedule seams"
  - "WR-04's re-schedule check reads the run's status via a SEPARATE repo.load_run call (not embedded in get_inbound_by_message_id's own row) — get_inbound_by_message_id returns the run_id but not the run's live status, and the plan's truths require checking AWAITING_REPLY at the moment of redelivery, not at the moment the reply was first persisted"
  - "The D-11-05 stranded auto-resume is added to the SAME try/except that already wraps repo.sweep_stranded_runs in runs_list — not a new try block — so a recovery-sweep failure (either the existing sweep or the new stranded-reply scan) never 500s the dashboard, matching the plan's Task 2 instruction precisely"
  - "clear_reply_context is called ONCE at the retrigger route's single `if claimed:` convergence point (not duplicated inside the ERROR/APPROVED branch and the stale in-flight branch separately) — both winning paths already funnel through this one guard before dispatching _run_pipeline, so one call site satisfies 'both branches' with no duplication"

requirements-completed: [CLAR2-06, CLAR2-07]

# Metrics
duration: ~50min
completed: 2026-07-06
---

# Phase 11 Plan 05: Redelivery, Stranded-Reply Recovery & Retrigger Context-Clear Summary

**Three main.py runtime seams wired to the Phase 11 round/consumed state: a redelivered or stranded unconsumed reply now re-drives the CAS-gated resume instead of being permanently dropped, and a retrigger wipes all reply-round context so no provenance badge can outlive its data.**

## Performance

- **Duration:** ~50 min
- **Started:** 2026-07-06T02:07:00Z
- **Completed:** 2026-07-06T02:57:13Z
- **Tasks:** 4
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments
- `app.main._row_to_inbound(row) -> InboundEmail` — the single pure bridge both new re-schedule seams share, built from a persisted `email_messages` row and reusing `body_text` verbatim (never re-cleaning a redelivered request's body — Pitfall #11a).
- `repo.get_inbound_by_message_id` and `repo.find_stranded_unconsumed_replies` SELECT column lists widened to the full `InboundEmail` field set (`id`, `in_reply_to`, `references_header`, `created_at`), with zero change to either function's filter/scope logic.
- WR-04 (D-11-03): the webhook's `outcome == "duplicate"` branch now loads the persisted reply row by `message_id`, and — iff `consumed_round IS NULL` AND the linked run is still `awaiting_reply` — re-schedules `_resume_pipeline` post-commit. A consumed reply's redelivery, or a redelivery whose run already advanced, stays the original no-op duplicate response.
- D-11-05: `runs_list` gains a `BackgroundTasks` parameter and, inside the SAME try/except that already wraps `repo.sweep_stranded_runs`, iterates `repo.find_stranded_unconsumed_replies` and re-schedules `_resume_pipeline` for each stale unconsumed reply. The query's own scope (11-01) already excludes `needs_operator` runs by construction — no new exclusion logic was needed (D-11-06).
- WR-06 (D-11-04): the retrigger route's single `if claimed:` convergence point — reached by both the ERROR/APPROVED core CAS and the stale in-flight CAS branches — now calls `repo.clear_reply_context(run_id)` before `background_tasks.add_task(_run_pipeline, run_id)`. Nulls `clarified_fields`, `pre_clarify_extracted`, `clarification_round`, and `alias_candidates` in one durable transaction that does not span the LLM-heavy pipeline task.
- `tests/test_reply_redelivery.py` (NEW, 6 tests, unguarded/hermetic): unconsumed redelivery reschedules with the persisted (not re-cleaned) body; consumed redelivery no-ops; redelivery to a non-awaiting_reply run no-ops; runs-list reschedules a stale unconsumed reply and does NOT reschedule a fresh one; a `needs_operator` run's stale unconsumed reply is never rescheduled.
- `tests/test_cr_regressions.py` extended with 3 CLAR2-07 tests: retrigger clears all four reply-context columns via both winning CAS branches and still dispatches `_run_pipeline`; a stale provenance badge cannot reproduce (`clarified_fields` is empty/falsy after retrigger, asserted on the persisted column).

## Task Commits

Each task was committed atomically:

1. **Task 1: repo select widening + `_row_to_inbound` helper** - `16d0bd8` (feat)
2. **Task 2: WR-04 redelivery re-schedule + D-11-05 stranded auto-resume** - `9858b44` (feat)
3. **Task 3: WR-06 retrigger-clears-all-reply-context** - `f018a56` (feat)
4. **Task 4: `tests/test_reply_redelivery.py` + extend `tests/test_cr_regressions.py`** - `81fb261` (test)

**Plan metadata:** (this commit, immediately following)

## Files Created/Modified
- `app/main.py` — `_row_to_inbound` helper; WR-04 re-schedule in the webhook duplicate branch; D-11-05 stranded auto-resume in `runs_list` (gained a `BackgroundTasks` param); WR-06 `clear_reply_context` call at the retrigger convergence point
- `app/db/repo.py` — `get_inbound_by_message_id` and `find_stranded_unconsumed_replies` SELECT lists widened to the full `InboundEmail` field set
- `tests/test_reply_redelivery.py` (NEW) — CLAR2-06 matrix: 6 hermetic tests covering unconsumed/consumed redelivery, non-awaiting-reply redelivery, stranded auto-resume, fresh-reply exclusion, and needs_operator exclusion
- `tests/test_cr_regressions.py` — 3 new CLAR2-07 tests asserting all four reply-context columns clear on retrigger (both CAS branches) and that a stale provenance badge cannot reproduce

## Decisions Made
- `_row_to_inbound` is a pure function in `app/main.py` (not `repo.py`) — it builds a Pydantic model, not SQL; `repo.py` stays exclusively the SQL layer.
- WR-04's redelivery check reads the linked run's live status via a fresh `repo.load_run` call rather than trying to derive it from the reply row alone — the reply row only carries `run_id`; the run's CURRENT status (must be `awaiting_reply` at the moment of redelivery) requires its own lookup.
- The D-11-05 stranded scan was added inside the EXISTING `try/except` around `sweep_stranded_runs` (not a new one) per the plan's explicit Task 2 instruction — one swallow-on-failure boundary, matching the sweep's own philosophy that a recovery-sweep failure must never 500 the dashboard.
- `clear_reply_context` is called exactly once, at the retrigger route's single `if claimed:` guard, which both winning branches (core CAS and stale in-flight CAS) already funnel through before dispatching `_run_pipeline` — avoids duplicating the clear call inside each branch separately while still satisfying "both branches" from the plan's truths.

## Deviations from Plan

None — plan executed exactly as written. All three main.py seams were wired using the sketches in `11-RESEARCH.md` (adapted only for the current, post-11-04 line positions in `app/main.py`, since the plan's own line-number pointers referenced pre-11-04/11-05 code and the file had moved on). No architectural changes, no new tables/columns, no package installs.

## Issues Encountered
None.

## User Setup Required
None — no external service configuration required. No schema changes in this plan (schema landed in Plan 11-01); this plan is pure application-code wiring + tests.

## Next Phase Readiness
- CLAR2-06 closed: an unconsumed redelivery and a stranded unconsumed reply both re-drive the CAS-gated resume; a consumed redelivery and a `needs_operator` run stay untouched — no permanently-dropped replies.
- CLAR2-07 closed: retrigger clears `clarified_fields` + `pre_clarify_extracted` + the round counter + `alias_candidates` after the winning claim and before re-run, so `is_round_2 = bool(clarified)` sees a fresh run and provenance badges cannot outlive their data.
- This was the final plan (11-05) in Phase 11 (Clarification Round Machine & Alias Learning) per `.planning/STATE.md`'s plan list — all five plans (11-01 through 11-05) are now complete.
- Full offline suite: 588 passed (579 baseline + 9 new), 20 skipped, 28 deselected — no regressions across the whole phase's cumulative work.
- No blockers.

---
*Phase: 11-clarification-round-machine-alias-learning*
*Completed: 2026-07-06*

## Self-Check: PASSED

- `app/main.py` — FOUND
- `app/db/repo.py` — FOUND
- `tests/test_reply_redelivery.py` — FOUND
- `tests/test_cr_regressions.py` — FOUND
- Commit `16d0bd8` (Task 1) — FOUND in `git log --oneline --all`
- Commit `9858b44` (Task 2) — FOUND in `git log --oneline --all`
- Commit `f018a56` (Task 3) — FOUND in `git log --oneline --all`
- Commit `81fb261` (Task 4) — FOUND in `git log --oneline --all`
- `uv run pytest -q tests/test_reply_redelivery.py tests/test_cr_regressions.py` — 21 passed
- `uv run pytest -q -m "not integration and not live_llm"` — 588 passed, 20 skipped, 28 deselected (re-run immediately before this self-check)
- `grep -q "def _row_to_inbound" app/main.py` — PASS
- `grep -q "get_inbound_by_message_id" app/main.py` — PASS
- `grep -q "find_stranded_unconsumed_replies" app/main.py` — PASS
- `grep -q "clear_reply_context" app/main.py` — PASS
- All plan `<acceptance_criteria>` for Tasks 1-4 re-verified via grep/pytest — PASS
