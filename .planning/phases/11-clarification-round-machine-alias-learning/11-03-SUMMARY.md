---
phase: 11-clarification-round-machine-alias-learning
plan: 03
subsystem: orchestrator
tags: [python, pytest, state-machine, round-machine, multi-round-context, llm-prompts]

# Dependency graph
requires:
  - phase: 11
    plan: 01
    provides: "clarification_round/round/consumed_round columns, mark_reply_consumed/get_clarification_round/load_consumed_replies/get_inbound_by_message_id repo primitives, InMemoryRepo mirrors"
  - phase: 11
    plan: 02
    provides: "MAX_CLARIFICATION_ROUNDS cap + needs_operator escalation, (purpose, round)-keyed _clarify guard, idempotent round advance"
provides:
  - "resume_pipeline writes the D-11-02 consumed marker (repo.mark_reply_consumed) immediately after the successful AWAITING_REPLY -> EXTRACTING CAS claim — the load-bearing seam that makes load_consumed_replies return real rows at runtime"
  - "_combined_context_email rewritten as a pure function (reply, original_body, *, asked_summary_lines, prior_replies) -> InboundEmail: ORIGINAL body + code-owned 'QUESTIONS WE ASKED' anchor + all consumed prior replies in round order + the current reply"
  - "New _render_asked_summary(decision, clarified_fields) module-level helper: renders asked-anchor lines from PERSISTED decision.unresolved_names + clarified_fields 'asked' entries only, never the LLM-drafted body"
  - "resume_pipeline wired to load repo.load_consumed_replies(run_id) and render asked_summary_lines before calling _combined_context_email, excluding the currently-being-consumed reply by message_id"
  - "Absent-if-unaddressed no-guess instruction added to app/llm/prompts/extract.py's _SYSTEM policy (D-11-11) — prompt-only nudge, backstop is the deterministic decide-gate re-ask"
  - "tests/test_combined_context.py (NEW, 8 tests): anchor string, no-anchor, accumulation order, purity, asked-summary source-pinning, deterministic re-ask backstop, and the consumed-marker-drives-accumulation test against REAL (not seeded) rows"
  - "tests/test_multiround_context_edge.py's known-edge fixture flipped: renamed test_multi_round_context_loss_known_edge -> test_multi_round_context_preserves_round1_correction, terminal assertion flipped hours_regular 40 -> 30 (CX-01 closed)"
affects: [11-04, 11-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Consume-at-claim seam: the D-11-02 write (repo.mark_reply_consumed) sits immediately after the winning CAS claim, outside any LLM/provider transaction — a single post-claim UPDATE, write-once via the 11-01 consumed_round IS NULL guard"
    - "Code-owned context anchor: _render_asked_summary reads ONLY persisted decision/clarified_fields facts — its signature has no LLM-draft parameter, so the anti-pattern (anchor derived from the model's own drafted email) is structurally impossible, not just avoided by convention"
    - "Round-ordered accumulation via consumed rows, not thread-quoting: prior_replies comes from repo.load_consumed_replies (ordered by consumed_round), never from re-parsing quoted email history, which clean_body already strips at ingest"
    - "Test-harness realism for money-path fixtures: a reply used to drive multi-round accumulation must be persisted via insert_inbound_email + link_email_to_run (not just constructed as a bare InboundEmail) or the consumed-marker seam is silently bypassed and the test passes for the wrong reason — added _inbound_persisted helpers in both test_combined_context.py and test_multiround_context_edge.py"

key-files:
  created:
    - tests/test_combined_context.py
  modified:
    - app/pipeline/orchestrator.py
    - app/llm/prompts/extract.py
    - tests/test_multiround_context_edge.py
    - tests/test_alias_write.py
    - tests/test_threading.py

key-decisions:
  - "mark_reply_consumed(inbound.message_id, round=repo.get_clarification_round(run_id)) is called by resume_pipeline (this plan), never by _clarify (11-02) — _clarify owns the send-side round counter; resume_pipeline owns consumption, the read side. Placed immediately after the CAS claim, before load_run, so it is the very first thing that happens once processing genuinely starts."
  - "_combined_context_email's signature changed to keyword-only asked_summary_lines/prior_replies (breaking change, no back-compat shim) since it has exactly one caller (resume_pipeline) and the plan explicitly authorizes the rewrite — no deprecation period needed for an internal helper."
  - "asked_summary_lines and prior_replies are computed AFTER pre_run_data/clarified are loaded (moved the _combined_context_email call site later in resume_pipeline) rather than duplicating a second load_run/load_clarified_fields call — reuses data already being loaded for the alias-diff and classify-first logic."
  - "The consumed-marker-drives-accumulation test (test_combined_context.py #7) deliberately does NOT pre-seed consumed_round by hand — it drives two real resume_pipeline calls and asserts the second one's extraction context contains the first reply's literal text, so it fails if Task 1's mark_reply_consumed call is ever removed (the plan's explicit BLOCKER-3 anti-regression requirement)."
  - "The flipped test_multiround_context_edge.py fixture's Round-1 reply is now persisted via a new _inbound_persisted helper (insert_inbound_email + link_email_to_run) instead of the module's pre-existing bare _inbound() builder — verified during authoring (via a throwaway monkeypatch check, not committed) that using the bare builder would make the flipped assertion pass for the WRONG reason (a hardcoded mock response), not because accumulation was genuinely exercised."

requirements-completed: [CLAR2-03, CLAR2-05]

# Metrics
duration: ~55min
completed: 2026-07-06
---

# Phase 11 Plan 03: Multi-Round Context Accumulation & Question-Anchored Attribution Summary

**resume_pipeline now writes the D-11-02 consumed marker at its own CAS claim, `_combined_context_email` accumulates every consumed reply in round order behind a code-owned "QUESTIONS WE ASKED" anchor, and the known-edge fixture flips from documenting a silent-mispay gap to asserting it's closed (Round-1 "30, not 40" now pays 30).**

## Performance

- **Duration:** ~55 min
- **Started:** 2026-07-06T01:02:00Z
- **Completed:** 2026-07-06T01:57:34Z
- **Tasks:** 4
- **Files modified:** 6 (1 created, 5 modified)

## Accomplishments
- `resume_pipeline` calls `repo.mark_reply_consumed(inbound.message_id, round=repo.get_clarification_round(run_id))` immediately after the successful `AWAITING_REPLY → EXTRACTING` CAS claim — the load-bearing seam that makes `load_consumed_replies` return real rows at runtime (D-11-02). Without this write, the round-ordered accumulation built in Task 2 would be a silent no-op in production even though hermetic tests seeded with fake consumed rows would still pass.
- `_combined_context_email` rewritten as a pure function `(reply, original_body, *, asked_summary_lines, prior_replies) -> InboundEmail`: assembles ORIGINAL body → (if any) a "QUESTIONS WE ASKED:" section → every consumed prior reply under a round-numbered "CLARIFICATION REPLY N FROM CLIENT:" delimiter, in order → the current reply under "... (CURRENT)". Still returns `reply.model_copy(update=...)` with zero DB I/O.
- New `_render_asked_summary(decision, clarified_fields)` module-level helper renders the anchor's lines from `decision.unresolved_names` + `clarified_fields` entries currently `'asked'` — deliberately has no LLM-draft parameter, so the D-11-10 anti-pattern (deriving the anchor from the model's own drafted clarification email) is structurally impossible, not merely avoided by convention.
- `resume_pipeline` now loads `repo.load_consumed_replies(run_id)` and renders `asked_summary_lines` from the pre-resume persisted `decision` + `clarified_fields` before calling `_combined_context_email`, excluding the currently-being-consumed reply by `message_id` so it is never duplicated as both a prior entry and the current reply.
- `app/llm/prompts/extract.py`'s `_SYSTEM` policy gained an absent-if-unaddressed instruction (D-11-11): an asked field may only be filled from a reply if it attributably answers it (names the employee, or exactly one question was asked). This is a prompt-only nudge — the real guarantee is the deterministic `decide()` gate re-asking on a still-absent field, proven by a dedicated backstop test that asserts a SEND, never LLM behavior.
- New `tests/test_combined_context.py` (8 tests, unguarded/hermetic): the anchor string test, the no-anchor test, the round-order accumulation test, the purity test, the asked-summary source-pinning test, the deterministic re-ask backstop test, and the consumed-marker-drives-accumulation test that drives TWO real `resume_pipeline` calls and asserts the second one's extraction context contains the first reply's literal text (fails if Task 1's marker write is ever removed).
- `tests/test_multiround_context_edge.py`'s known-edge fixture renamed and flipped: `test_multi_round_context_loss_known_edge` → `test_multi_round_context_preserves_round1_correction`, terminal assertion `hours_regular == Decimal("40")` → `== Decimal("30")`, module and test docstrings rewritten from "documents current broken behavior" to "regression guard: CX-01 closed (D-11-12)". The scenario is byte-identical; only the Round-1 reply's construction changed (see Deviations) and the terminal assertion flipped.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write the D-11-02 consumed marker at the resume CAS claim** - `939b52c` (feat)
2. **Task 2: Rewrite `_combined_context_email` as a pure function; wire accumulation + asked-anchor at resume** - `83890a8` (feat)
3. **Task 3: No-guess extraction instruction (absent-if-unaddressed) for the reply-context prompt** - `abbeb1f` (feat)
4. **Task 4: New `tests/test_combined_context.py` + flip the known-edge fixture** - `f3871b7` (test)

**Plan metadata:** (this commit, immediately following)

## Files Created/Modified
- `app/pipeline/orchestrator.py` - `mark_reply_consumed` call at the resume CAS claim; `_combined_context_email` rewritten to the new pure-function signature; new `_render_asked_summary` helper; `resume_pipeline` wired to load consumed replies + render the asked summary before the combined-context call
- `app/llm/prompts/extract.py` - absent-if-unaddressed no-guess instruction added to `_SYSTEM`; existing "record exactly as written" grounding instruction unchanged; `extract()`'s purity contract preserved (no new required argument)
- `tests/test_combined_context.py` (NEW) - 8 hermetic pure-function + `resume_pipeline`-driving tests covering the anchor, accumulation, purity, asked-summary source-pinning, the re-ask backstop, and the consumed-marker-drives-accumulation proof against real rows
- `tests/test_multiround_context_edge.py` - the known-edge fixture renamed/flipped (CX-01 closure); a new `_inbound_persisted` helper added so the fixture's Round-1 reply genuinely exercises the consumed-marker seam
- `tests/test_alias_write.py` - 3 `resume_pipeline`-driving tests updated to monkeypatch `get_clarification_round`/`mark_reply_consumed`/`load_consumed_replies` (Task 1/2 deviation fix)
- `tests/test_threading.py` - `_MiniStore` gained `get_clarification_round`/`mark_reply_consumed`/`load_consumed_replies` mirrors; both monkeypatch-loop call sites extended to intercept the two new repo calls (Task 1/2 deviation fix)

## Decisions Made
- `mark_reply_consumed` is called by `resume_pipeline`, never by `_clarify` — consumption is the read side (this plan), the send-side round counter is `_clarify`'s (11-02). Placed immediately after the CAS claim, before `load_run`, so it fires the instant processing genuinely starts.
- `_combined_context_email`'s signature changed to keyword-only `asked_summary_lines`/`prior_replies` with no back-compat shim — it has exactly one caller (`resume_pipeline`) and the plan explicitly authorized the rewrite.
- `asked_summary_lines`/`prior_replies` are computed after `pre_run_data`/`clarified` are already loaded (the `_combined_context_email` call site moved later in `resume_pipeline`) rather than issuing a second `load_run`/`load_clarified_fields` — reuses data the alias-diff and classify-first logic already load.
- The consumed-marker-drives-accumulation test (`test_combined_context.py` test 7) deliberately does not pre-seed `consumed_round` by hand — it drives two real `resume_pipeline` calls so the test fails if Task 1's `mark_reply_consumed` call is ever removed (the plan's explicit BLOCKER-3 requirement).
- The flipped `test_multiround_context_edge.py` fixture's Round-1 reply is now persisted via a new `_inbound_persisted` helper (mirroring the real webhook's `insert_inbound_email` + `link_email_to_run`) instead of the module's pre-existing bare `_inbound()` builder — verified during authoring, via a throwaway (uncommitted) monkeypatch check, that using the bare builder would make the flipped assertion pass for the WRONG reason (a hardcoded mock LLM response) rather than because accumulation was genuinely exercised at runtime.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Pre-existing `resume_pipeline`-driving tests fell through to the real (DB-backed) repo after Task 1's new calls**
- **Found during:** Task 1 (adding `mark_reply_consumed`/`get_clarification_round` calls to `resume_pipeline`)
- **Issue:** `tests/test_alias_write.py` (3 tests: `test_resume_binding_uses_pre_vs_post_diff_not_single_resolved_count`, `test_resume_binding_skips_when_no_newly_resolved_employee`, `test_resume_binding_does_not_learn_misname_as_alias`) monkeypatch bare `app.db.repo` functions directly (not the full `InMemoryRepo`/`fake_repo` fixture) and did not intercept `get_clarification_round`/`mark_reply_consumed`. `tests/test_threading.py`'s `_MiniStore` class (used by `test_partial_reply_preserves_hours` and `test_resume_on_non_awaiting_reply_run_does_not_mutate`) likewise lacked these methods. Both cases fell through to the real, DB-backed `app.db.repo` functions, causing `PoolTimeout`/connection errors.
- **Fix:** Added `get_clarification_round`/`mark_reply_consumed` mocks (or `_MiniStore` mirror methods) to all 5 affected test call sites.
- **Files modified:** `tests/test_alias_write.py`, `tests/test_threading.py`
- **Verification:** `uv run pytest -q -m "not integration and not live_llm"` — 562 passed (baseline), 20 skipped, 28 deselected, immediately after the fix.
- **Committed in:** `939b52c` (Task 1 commit)

**2. [Rule 1 - Bug] The same test call sites also needed `load_consumed_replies` mocked after Task 2's wiring**
- **Found during:** Task 2 (wiring `resume_pipeline` to call `repo.load_consumed_replies(run_id)` before `_combined_context_email`)
- **Issue:** The same 5 test call sites fixed in deviation #1 also lacked `load_consumed_replies`, which Task 2 added as a new call in `resume_pipeline`. Same fall-through-to-real-repo failure mode.
- **Fix:** Added `load_consumed_replies` mocks (returning `[]`/no-op) alongside the deviation-#1 fixes at the same 5 call sites.
- **Files modified:** `tests/test_alias_write.py`, `tests/test_threading.py`
- **Verification:** `uv run pytest -q -m "not integration and not live_llm"` — 562 passed, 20 skipped, 28 deselected, immediately after the fix.
- **Committed in:** `83890a8` (Task 2 commit)

**3. [Rule 1 - Bug] The flipped known-edge fixture would have passed for the wrong reason without a real consumed row**
- **Found during:** Task 4 (writing the consumed-marker-drives-accumulation test in `test_combined_context.py` and flipping `test_multiround_context_edge.py`)
- **Issue:** `test_multiround_context_edge.py`'s existing `_inbound()` helper builds a bare `InboundEmail` never persisted via `insert_inbound_email`. Using it for the Round-1 reply meant `resume_pipeline`'s `mark_reply_consumed` call found no matching row (no-op), so `load_consumed_replies` would return `[]` for Round 2 — the flipped assertion (`hours_regular == 30`) would then only pass because the test's Round-2 mock LLM script was hardcoded to return `30`, not because accumulation was genuinely exercised. Verified via a throwaway (uncommitted) monkeypatch check during authoring.
- **Fix:** Added a new `_inbound_persisted` helper to `tests/test_multiround_context_edge.py` (mirrors `insert_inbound_email` + `link_email_to_run`, matching real webhook behavior) and switched the Round-1 reply construction to use it.
- **Files modified:** `tests/test_multiround_context_edge.py`
- **Verification:** `uv run pytest -q tests/test_multiround_context_edge.py` — 2 passed; cross-checked against `test_combined_context.py`'s dedicated consumed-marker test (which does the same real-row proof directly).
- **Committed in:** `f3871b7` (Task 4 commit)

---

**Total deviations:** 3 auto-fixed (all Rule 1 — bugs directly caused by this plan's own new `resume_pipeline` calls surfacing gaps in pre-existing test doubles)
**Impact on plan:** All three fixes were necessary corrections so the plan's own new repo calls (`mark_reply_consumed`, `get_clarification_round`, `load_consumed_replies`) work correctly against every test double that drives `resume_pipeline`, and so the flipped money-path fixture proves the real fix rather than passing coincidentally. No scope creep — none of the fixes touch unrelated production code paths.

## Issues Encountered
None beyond the deviations above.

## User Setup Required
None - no external service configuration required. This plan is pure application code (orchestrator logic, prompt text, tests) with no new environment variables or schema changes (schema changes landed in Plan 11-01).

## Next Phase Readiness
- CX-01/T-09-21 is closed: a Round-1 correction now survives into every later round's extraction context and is paid, proven by both a targeted pure-function/accumulation test suite and the flipped known-edge fixture (verified to fail if the seam is removed, not merely asserting a hardcoded value).
- The consumed-marker seam (D-11-02) is load-bearing and now proven against real rows, not just seeded fakes — this directly unblocks Plan 11-05's stranded/redelivery detection, which depends on `load_consumed_replies`/`consumed_round` being genuinely populated at runtime.
- The no-guess extraction policy (D-11-11) is in place as a prompt instruction with its deterministic backstop (the decide-gate re-ask) pinned by a dedicated test that asserts a SEND, never LLM attribution behavior.
- The 7.5 four-outcome machine and `is_round_2 = bool(clarified)` are untouched (verified byte-identical logic, only its line position shifted).
- Full offline suite: 570 passed (562 baseline + 8 new), 20 skipped, 28 deselected — no regressions.
- No blockers. Ready for Plan 11-04 (operator resolve/resume form for `needs_operator`, and/or alias bind-on-confirmation work per the ROADMAP dependency ordering).

---
*Phase: 11-clarification-round-machine-alias-learning*
*Completed: 2026-07-06*

## Self-Check: PASSED

- `app/pipeline/orchestrator.py` — FOUND
- `app/llm/prompts/extract.py` — FOUND
- `tests/test_combined_context.py` — FOUND
- `tests/test_multiround_context_edge.py` — FOUND
- `tests/test_alias_write.py` — FOUND
- `tests/test_threading.py` — FOUND
- Commit `939b52c` (Task 1) — FOUND in `git log --oneline --all`
- Commit `83890a8` (Task 2) — FOUND in `git log --oneline --all`
- Commit `abbeb1f` (Task 3) — FOUND in `git log --oneline --all`
- Commit `f3871b7` (Task 4) — FOUND in `git log --oneline --all`
- `uv run pytest -q tests/test_combined_context.py tests/test_multiround_context_edge.py` — 10 passed
- `uv run pytest -q -m "not integration and not live_llm"` — 570 passed, 20 skipped, 28 deselected (re-run immediately before this self-check)
- `grep -q "mark_reply_consumed" app/pipeline/orchestrator.py` — PASS
- `grep -q "asked_summary_lines" app/pipeline/orchestrator.py` — PASS
- `grep -q "load_consumed_replies" app/pipeline/orchestrator.py` — PASS
- `grep -qi "attribut" app/llm/prompts/extract.py` — PASS
- `grep -q 'Decimal("30")' tests/test_multiround_context_edge.py` — PASS
- `grep -q "known_edge\|KNOWN EDGE" tests/test_multiround_context_edge.py` — PASS (absent, as required)
- All plan `<acceptance_criteria>` for Tasks 1-4 re-verified via grep/pytest — PASS
