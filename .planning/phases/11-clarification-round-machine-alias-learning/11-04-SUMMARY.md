---
phase: 11-clarification-round-machine-alias-learning
plan: 04
subsystem: orchestrator
tags: [python, pytest, alias-learning, name-resolution, hermetic-tests, security]

# Dependency graph
requires:
  - phase: 11
    plan: 01
    provides: "clarification_round/round/consumed_round columns, needs_operator status, InMemoryRepo mirrors"
  - phase: 11
    plan: 02
    provides: "MAX_CLARIFICATION_ROUNDS cap + needs_operator escalation"
  - phase: 11
    plan: 03
    provides: "resume_pipeline consumed-marker seam, _combined_context_email accumulation, question-anchored attribution"
provides:
  - "D-11-14 nested alias_candidates persistence: {token: {suggested: employee_id|None, bound: employee_id|None}}"
  - "_normalize_candidate() legacy-shape tolerance helper (None / bare id string / already-nested dict)"
  - "D-11-15 bind-on-confirmation: deterministic bind against the persisted SUGGESTED employee, replacing the unreachable NEW-2 pre-vs-post count-diff bind"
  - "reconcile_names(overrides=) — an optional per-run operator override map, source='operator' tagged, wins before exact/alias"
  - "resume_pipeline generalized: inbound=None + from_status=NEEDS_OPERATOR supports the operator-resume path with one shared resume code path"
  - "POST /runs/{run_id}/resolve — server-side roster validation (Security V4), remember-checkbox bind (D-11-16), claim + background resume dispatch"
  - "needs_operator resolve form + banner in run_detail.html; reject() widened to accept NEEDS_OPERATOR -> REJECTED"
  - "tests/test_alias_full_loop.py — the D-11-17 full-loop stops-asking proof with REAL reconcile_names + REAL _write_aliases_if_safe"
  - "InMemoryRepo.update_known_alias mirror (tests/conftest.py) — the missing seam that makes alias-learning writes observable offline"
affects: [11-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Normalize-on-read for JSONB shape migrations: _normalize_candidate() is called at every read site (bind check + write side) so a legacy flat row and the new nested shape are handled by ONE helper, never duplicated shape-branching logic"
    - "Deterministic evidence-based bind: bind fires only when the SPECIFIC persisted suggestion is confirmed by real post-resume reconciliation facts (suggested id newly resolved AND token gone from unresolved) — no count heuristics, no LLM call, no confidence number"
    - "One resume path, absent-section generalization: resume_pipeline accepts inbound=None for the operator-resume case, substituting a synthetic empty-body InboundEmail so every downstream line (consumed-marker write, accumulation) runs unmodified for both callers"
    - "Reject-whole-POST-on-any-invalid-id: the resolve route validates every posted employee_id before applying ANY of them — no partial apply, matching the run's own business roster exactly (Security V4)"

key-files:
  created:
    - tests/test_alias_full_loop.py
  modified:
    - app/pipeline/orchestrator.py
    - app/pipeline/reconcile_names.py
    - app/models/roster.py
    - app/main.py
    - app/templates/run_detail.html
    - tests/test_alias_write.py
    - tests/test_needs_operator.py
    - tests/conftest.py

key-decisions:
  - "_normalize_candidate treats a legacy bare employee_id string as ALREADY BOUND ({'suggested': None, 'bound': value}) rather than unresolved — a pre-Phase-11 row that the OLD bind logic already wrote keeps behaving as learned, so no live alias silently stops working after this plan deploys"
  - "The nested suggestion write is split into two steps inside _clarify: capture the token first (unchanged single-token-only + collision gate sequence), then persist {token: {suggested, bound: None}} AFTER suggest_employees runs — because the suggested employee id can only be computed once the suggestion (a NAME, not an id) is mapped against the already-loaded roster (Pitfall #5)"
  - "reconcile_names(overrides=) validates the override id against the PASSED roster and silently falls through to normal exact/alias/none resolution on an invalid id, rather than trusting a bad id blindly — the HTTP-boundary validation (Security V4) is the real gate; this is defense in depth inside the pure function"
  - "resume_pipeline's operator-resume path is a generalization (inbound=None, from_status=NEEDS_OPERATOR) rather than a parallel _operator_resume function — per RESEARCH Open Question #1's resolution (i), avoiding two divergent resume implementations"
  - "InMemoryRepo.update_known_alias was ADDED (Rule 3 deviation) — this mirror never existed in any prior phase; without it, the full-loop test's write step and stops-asking assertion cannot be observed offline (the real repo call would silently fall through to a live DB connection attempt)"

requirements-completed: [CLAR2-04]

# Metrics
duration: ~90min
completed: 2026-07-06
---

# Phase 11 Plan 04: Alias-Learning WRITE Side Reachable — Bind-on-Confirmation + Operator Resolve Summary

**Replaced the unreachable NEW-2 pre-vs-post count-diff alias bind with deterministic bind-on-confirmation against a persisted, nested `{suggested, bound}` candidate shape, added the `needs_operator` operator resolve+resume surface with server-side roster validation, and proved the alias-learning loop actually stops asking with a full-loop hermetic test that drives REAL name resolution end to end.**

## Performance

- **Duration:** ~90 min
- **Completed:** 2026-07-06T03:15:00Z
- **Tasks:** 3
- **Files modified:** 8 (1 created, 7 modified)

## Accomplishments

- **D-11-14 nested persistence.** `_clarify`'s alias-candidate capture now persists `{token: {"suggested": employee_id|None, "bound": None}}` instead of a flat `{token: None}`. The suggestion write happens AFTER `suggest_employees` runs (it returns a roster full_name, never an id — Pitfall #5), mapped against the already-loaded roster.
- **D-11-15 bind-on-confirmation replaces the unreachable bind.** `resume_pipeline`'s old bind required the newly-resolved employee's id to equal the pending CANDIDATE TOKEN itself — a condition that can never fire when a client only restates a canonical name (the reply resolves to the SUGGESTED employee, not the original unresolved token). The new bind fires iff the persisted SUGGESTED id newly resolves in post-resume reconciliation AND the token is gone from unresolved submitted names — both deterministic facts read directly off persisted state, no LLM call, no confidence number.
- **Misname guard preserved verbatim.** A reply that resolves a DIFFERENT, non-suggested employee (e.g. "no, I meant James" when Priya was suggested) never binds — the newly-resolved id must equal the SPECIFIC persisted suggestion, not merely "some employee resolved."
- **`_normalize_candidate()`** tolerates every legacy shape (`None`, a bare employee_id string from the old flat-bound logic, or an already-nested dict) so a pre-Phase-11 production row never raises `AttributeError` at the bind check or the write side (Pitfall #6).
- **`_write_aliases_if_safe`** reads the nested shape via `_normalize_candidate`, skips a candidate whose `bound` is `None`, and preserves the D-01b `_safe_to_learn_alias` collision re-check and the batch roster refresh verbatim.
- **`reconcile_names(overrides=)`** — an optional per-run operator override map (`submitted_name -> employee_id_str`). An override wins BEFORE exact/stored-alias resolution and produces `source="operator"` (still not a guess — a human stated it). `NameMatchResult.source` widened to include `"operator"`. Default `None` keeps every pre-existing caller behavior-identical.
- **`resume_pipeline` generalized** (RESEARCH Open Question #1, resolved (i)): `inbound=None` + `from_status=RunStatus.NEEDS_OPERATOR` lets the operator-resume path re-enter with no new reply — a synthetic empty-body `InboundEmail` keeps every downstream line (the consumed-marker write, the combined-context accumulation) on the identical code path as the reply-driven resume. One resume path, no drift.
- **`POST /runs/{run_id}/resolve`**: validates every posted `employee_id` against `load_roster_for_business(run.business_id)` and rejects the WHOLE POST on any invalid/unknown/cross-business id (Security V4, no partial apply). Applies the validated mapping as the per-run override; for each remember-checked token, pre-sets the candidate's `bound` field so the existing single-human-gate write path (`_write_aliases_if_safe` at approval) persists it — unchecked means override-only, nothing learned (D-11-16). Claims `NEEDS_OPERATOR -> EXTRACTING` then dispatches the operator-resume in the background.
- **`run_detail.html`** gained the `needs_operator` banner + resolve form (per-name roster dropdown with the LLM suggestion pre-selected, remember-alias checkbox default-checked) + Reject. `needs_operator` remains absent from the retrigger-form status list. `reject()` widened to accept a `NEEDS_OPERATOR -> REJECTED` claim as the escalation's second exit.
- **`tests/test_alias_full_loop.py`** (NEW, 356 lines, unguarded/hermetic): drives REAL `reconcile_names` and REAL `_write_aliases_if_safe` throughout — `mock_llm` is used ONLY for extraction/suggestion/draft TEXT, never for name resolution or a faked post-reconciliation state. Proves the exact D-11-17 gap is closed: nickname capture -> suggestion persist with a real employee id -> confirming reply -> real bind-on-confirmation -> operator approval -> `known_aliases` actually written -> a SECOND, independent submission with the same nickname resolves via the stored alias with ZERO clarification and produces a real paystub (asserted on the PAID VALUE, not a status label — Phase 7.5 lesson). A companion test pins the misname guard at the full-loop level.

## Task Commits

Each task was committed atomically:

1. **Task 1: Nested suggestion persistence + bind-on-confirmation rewrite + nested-shape write side (D-11-14, D-11-15)** - `6ddfe68` (feat)
2. **Task 2: Operator resolve form + resume route with server-side roster validation and per-run override (D-11-08, D-11-16, Security V4)** - `c05b771` (feat)
3. **Task 3: Update tests/test_alias_write.py to the nested shape + real resolution; land tests/test_alias_full_loop.py (D-11-17)** - `c06e315` (test)

**Plan metadata:** (this commit, immediately following)

## Files Created/Modified

- `app/pipeline/orchestrator.py` - `_normalize_candidate` helper; `_clarify`'s alias capture split into two steps (capture then persist-after-suggest); the STEP C/D bind block rewritten to D-11-15's deterministic bind-on-confirmation; `_write_aliases_if_safe` reads the nested shape; `resume_pipeline` generalized with `inbound=None`/`from_status`/`overrides` params; `_run_stages` gained an `overrides` passthrough to `reconcile_names`
- `app/pipeline/reconcile_names.py` - `reconcile_names(overrides=)` optional per-run operator override, `source="operator"` tagged
- `app/models/roster.py` - `NameMatchResult.source` widened to `Literal["exact", "alias", "none", "operator"]`
- `app/main.py` - `POST /runs/{run_id}/resolve` route (Security V4 validation, D-11-16 remember-checkbox), `_operator_resume` background wrapper, `reject()` widened, `run_detail()` route enriched with roster employees + persisted suggestions for the resolve form
- `app/templates/run_detail.html` - `needs_operator` banner + resolve form + Reject
- `tests/test_alias_write.py` - every faked-state binding test updated to the nested shape; misname-guard test rebuilt around a distinct suggested-vs-resolved employee pair; new `_normalize_candidate` legacy-shape tests + a `_write_aliases_if_safe` legacy-flat-row test
- `tests/test_alias_full_loop.py` (NEW) - the D-11-17 full-loop stops-asking proof + a full-loop misname-guard companion test
- `tests/test_needs_operator.py` - added `POST /runs/{run_id}/resolve` coverage (Security V4 rejection, valid-POST claim+override+bind, checkbox-off no-bind)
- `tests/conftest.py` - `InMemoryRepo.update_known_alias` mirror (NEW — never existed before this plan)

## Decisions Made

- `_normalize_candidate` treats a legacy bare employee_id string as ALREADY BOUND, not unresolved — a live pre-Phase-11 row that the old bind logic wrote keeps behaving as learned after this plan deploys, rather than silently losing its confirmed status.
- The nested suggestion write is deliberately split into two steps in `_clarify`: capture the token first (unchanged gate sequence, unaffected by suggest timing), then persist the nested value once `suggest_employees` has run and its name output can be mapped to an employee id.
- `reconcile_names(overrides=)` re-validates the override id against the passed roster and falls through to normal resolution on an invalid id — defense in depth inside the pure function, even though the real gate is the HTTP-boundary validation in the `/resolve` route (Security V4).
- `resume_pipeline`'s operator-resume path is a generalization of the existing function (not a parallel `_operator_resume`), per RESEARCH Open Question #1's resolved recommendation — one resume path, the "current reply" section is simply absent.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `InMemoryRepo` had no `update_known_alias` mirror**
- **Found during:** Task 3, writing `tests/test_alias_full_loop.py`'s write-side assertion
- **Issue:** No prior phase ever added an `update_known_alias` mirror to `InMemoryRepo` (verified via `grep` — the name did not exist in `tests/conftest.py` before this plan). Without it, `_write_aliases_if_safe`'s call to `repo.update_known_alias` would fall through to the real, DB-backed `app.db.repo.update_known_alias`, which either errors or silently no-ops offline — making the D-11-17 full-loop test's central claim (the write side actually persists the alias) unobservable hermetically.
- **Fix:** Added `InMemoryRepo.update_known_alias(employee_id, new_alias, conn=None)`, mutating the SAME seeded `Employee` objects held in `self.business_employees` (an idempotent list-append, mirroring the real repo's `NOT (%s = ANY(known_aliases))` guard), and registered it in the `fake_repo` fixture's patch list.
- **Files modified:** `tests/conftest.py`
- **Verification:** `uv run pytest -q tests/test_alias_full_loop.py` (2 passed); full offline suite unaffected (579 passed, 20 skipped).
- **Committed in:** `c06e315` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 — a blocking test-infrastructure gap, not a production-code issue)
**Impact:** The fix was necessary to make the plan's own D-11-17 requirement (prove the write side with real resolution, not faked state) actually provable offline. No production code path was touched; the fix is confined to the hermetic test double.

## Issues Encountered

None beyond the deviation above.

## User Setup Required

None — no external service configuration required. This plan is pure application code (orchestrator logic, a new route, a template, and tests) with no new environment variables or schema changes.

## Next Phase Readiness

- The alias-learning WRITE side is reachable and proven end-to-end: a nickname is captured, a suggestion is persisted with a real employee id, a confirming reply binds deterministically, an operator approval writes `known_aliases`, and a second submission stops asking — all driven with REAL `reconcile_names` resolution, not seeded fakes.
- The misname guard (never learn from inference, only from confirmed suggestion evidence) is pinned both in the unit-level `test_alias_write.py` tests and at the full-loop level in `test_alias_full_loop.py`.
- The `needs_operator` escalation now has both of its exits fully wired: resolve+resume (server-validated, D-11-16 checkbox) or reject.
- Full offline suite: 579 passed (570 baseline + 9 new: 4 in `test_alias_write.py`, 2 in `test_alias_full_loop.py`, 3 in `test_needs_operator.py`), 20 skipped, 28 deselected — no regressions.
- No blockers. Ready for Plan 11-05 per the phase's dependency ordering.

---
*Phase: 11-clarification-round-machine-alias-learning*
*Completed: 2026-07-06*

## Self-Check: PASSED

- `app/pipeline/orchestrator.py` — FOUND
- `app/pipeline/reconcile_names.py` — FOUND
- `app/models/roster.py` — FOUND
- `app/main.py` — FOUND
- `app/templates/run_detail.html` — FOUND
- `tests/test_alias_write.py` — FOUND
- `tests/test_alias_full_loop.py` — FOUND
- `tests/test_needs_operator.py` — FOUND
- `tests/conftest.py` — FOUND
- Commit `6ddfe68` (Task 1) — FOUND in `git log --oneline --all`
- Commit `c05b771` (Task 2) — FOUND in `git log --oneline --all`
- Commit `c06e315` (Task 3) — FOUND in `git log --oneline --all`
- `uv run pytest -q tests/test_alias_full_loop.py tests/test_alias_write.py` — 18 passed
- `uv run pytest -q tests/test_dashboard.py tests/test_needs_operator.py` — 35 passed, 2 skipped
- `uv run pytest -q -m "not integration and not live_llm"` — 579 passed, 20 skipped, 28 deselected (re-run immediately before this self-check)
- `grep -q "overrides" app/pipeline/reconcile_names.py` — PASS
- `grep -q "/resolve" app/main.py` — PASS
- `grep -q "\"bound\"" app/pipeline/orchestrator.py` — PASS
- All plan `<acceptance_criteria>` for Tasks 1-3 re-verified via grep/pytest — PASS
