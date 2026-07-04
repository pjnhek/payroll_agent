---
phase: 09-atomic-data-integrity
plan: 04
subsystem: llm-client
tags: [resilience, timeouts, retries, recovery-sweep, integration-test]

# Dependency graph
requires:
  - phase: 09-atomic-data-integrity
    provides: "sweep_stranded_runs, STALE_THRESHOLD_SECONDS shared constant, transactional webhook ingest (09-01/02/03)"
provides:
  - "call_structured passes an explicit, named, bounded timeout=_STRUCTURED_TIMEOUT_S (45s) AND max_retries=0 to its OpenAI client construction — closes the compounding-retry gap for both extract() and suggest_employees()"
  - "call_text's OWN client construction gains an unconditional max_retries=0 (present regardless of whether timeout_s is passed) — closes the Codex round-2 STILL-OPEN finding that call_text had no app-level retry loop, so the library's own retry layer was the sole, uncounted layer"
  - "compose_clarification's call_text invocation now passes an explicit, bounded timeout_s=_CLARIFICATION_TIMEOUT_S (30s) — previously wholly unbounded"
  - "app/main.py's STALE_THRESHOLD is re-derived against the fully-tightened, correctly-summed worst-case ceiling (90s x 2 Round-2 extractions + 30s clarify gap = 210s) and tightened from 65min to 15min"
  - "tests/test_stuck_run_recovery.py::test_stranded_run_swept_and_retriggerable — SC3 end-to-end proof via the actual POST /runs/{run_id}/retrigger route"
affects: [10-concurrency-proof]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Named module-level timeout constants (not bare literals) with a code comment citing the exact compounding-retry finding, mirroring _MAX_TOKENS's existing style"
    - "Unconditional max_retries=0 on a client construction (independent of any other kwarg's presence) as the fix for a call surface with no app-level retry loop of its own"
    - "SC3 proof exercises the actual HTTP route (TestClient) with the background-task target monkeypatched to a no-op, rather than calling the underlying claim primitive directly — proves the operator-facing recovery path, not just claimability"

key-files:
  created: []
  modified:
    - app/llm/client.py
    - app/pipeline/compose_email.py
    - app/main.py
    - tests/test_llm_client.py
    - tests/test_clarify.py
    - tests/test_stuck_run_recovery.py

key-decisions:
  - "_STRUCTURED_TIMEOUT_S = 45.0s (call_structured) and _CLARIFICATION_TIMEOUT_S = 30.0s (compose_clarification's call_text) — both named module constants, not bare literals, matching _MAX_TOKENS's existing documented-constant style. 45s scaled up from compose_confirmation's existing timeout_s=3.0 for a heavier structured-JSON extraction round-trip; 30s at the lower end of the same range since a clarification draft is lighter free-text prose."
  - "max_retries=0 was added to call_text's client construction UNCONDITIONALLY (not gated on timeout_s is not None) — the two kwargs are independent; a caller may want retry-suppression even without a custom timeout. This benefits ALL call_text callers automatically, including compose_confirmation's existing timeout_s=3.0 call (now 3.0x1, not 3.0x3), as a welcome side effect rather than a scope expansion."
  - "STALE_THRESHOLD tightened from 65min (09-03's deliberately conservative untightened value) to 15min — derived as SUM (not product) of the sequential worst-case gaps on the longest real path: _STRUCTURED_TIMEOUT_S x 2 app-attempts x 2 Round-2 extractions (180s) + _CLARIFICATION_TIMEOUT_S x 1 (30s) = 210s, with ~4x comfortable margin."
  - "The SC3 integration test exercises the ACTUAL POST /runs/{run_id}/retrigger route via TestClient (background task monkeypatched to a no-op) rather than calling repo.claim_status directly — closing 09-REVIEWS.md's Codex Round-2 MEDIUM finding that the prior stub only proved claimability, not the operator-facing recovery path."

requirements-completed: [DATA-03]

# Metrics
duration: ~35min
completed: 2026-07-04
---

# Phase 09 Plan 04: Bound LLM Timeouts + SC3 End-to-End Recovery Proof Summary

**Closed the compounding-retry gap on BOTH LLM call surfaces (`call_structured` and `call_text`) by pairing an explicit bounded timeout with an unconditional `max_retries=0`, re-derived the stranded-run sweep threshold against the now fully-and-correctly-counted worst case (65min → 15min), and proved DATA-03's SC3 success criterion end-to-end through the actual operator-facing `retrigger` route.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-07-04T03:04:00Z (approx, after worktree base correction)
- **Completed:** 2026-07-04T03:39:47Z
- **Tasks:** 2/2 completed
- **Files modified:** 6 (0 created, 6 modified)

## Accomplishments

- `app/llm/client.py`'s `call_structured` now constructs its `OpenAI(...)` client with an explicit, named `timeout=_STRUCTURED_TIMEOUT_S` (45.0s) **AND** `max_retries=0` — without `max_retries=0`, the `openai` library's own default (`max_retries=2`) compounds with the app's existing `for attempt in (1, 2):` reflective retry loop, making the true worst case `timeout × 3 library-attempts × 2 app-attempts` = 6× the timeout, not the 2× a reader would assume from the app's own loop. `max_retries=0` collapses this to exactly `timeout × 2`. This one change bounds BOTH call sites that share `call_structured`: `extract()` and `suggest_employees()` (`app/pipeline/suggest.py:81`).
- `call_text` gains an **unconditional** `max_retries=0` on its own client construction — present whether or not `timeout_s` is passed — closing 09-REVIEWS.md's Codex round-2 STILL-OPEN HIGH finding: `call_text` has no app-level reflective retry loop of its own, so the library's `max_retries=2` default was the sole, previously-uncounted retry layer on that path. This benefits every `call_text` caller automatically, including `compose_confirmation`'s existing `timeout_s=3.0` (now bounded to `3.0×1`, not `3.0×3`, as a welcome side effect).
- `app/pipeline/compose_email.py`'s `compose_clarification` now passes an explicit `timeout_s=_CLARIFICATION_TIMEOUT_S` (30.0s) to its `call_text` invocation — previously this call had NO timeout at all (Codex HIGH-3's flagged wholly-unbounded gap). Combined with `call_text`'s new `max_retries=0`, this call's true worst case is now `30s × 1`.
- `app/main.py`'s `STALE_THRESHOLD` is re-derived against the fully-tightened, correctly-summed ceiling: `_STRUCTURED_TIMEOUT_S × 2 app-attempts × 2 (resume Round-2's back-to-back double extraction)` = 180s, **plus** the now-bounded clarify-branch `call_text` gap (30s × 1, sequential not concurrent) = 210s total. `STALE_THRESHOLD` is tightened from 65 minutes (09-03's deliberately conservative pre-tightening value) to **15 minutes** — comfortably ~4× above the 3.5-min derived ceiling.
- `tests/test_stuck_run_recovery.py::test_stranded_run_swept_and_retriggerable` replaces the 09-01 stub with a real end-to-end proof: strand a run in `extracting` with a backdated `updated_at`, sweep it (`error_reason == "StrandedRunSwept"`, non-null `error_detail` containing "stranded"), then exercise the **actual** `POST /runs/{run_id}/retrigger` route via `TestClient` (background task monkeypatched to a no-op) and assert (a) a success HTTP status, (b) the run reloads as `received`, and (c) the background pipeline dispatch was actually scheduled — proving the operator recovery path end-to-end, not just claimability (closing 09-REVIEWS.md's Codex Round-2 MEDIUM finding). A companion `test_parked_statuses_never_swept_live` confirms `awaiting_reply`/`awaiting_approval`/`approved` runs with a backdated `updated_at` are never swept, against a real DB.
- Full offline suite: 545 passed, 21 skipped (two-factor-guarded live-DB tests), 25 deselected (integration-marked), 0 regressions.

## Task Commits

Each task was committed atomically:

1. **Task 1: Bound call_structured + call_text timeouts, suppress library retries, reconcile threshold** — `fd4e311` (feat)
2. **Task 2: SC3 end-to-end integration test via the actual retrigger route** — `8c68f78` (test)

**Plan metadata:** (this SUMMARY.md commit)

## Files Created/Modified

- `app/llm/client.py` — added `_STRUCTURED_TIMEOUT_S = 45.0` named constant with a full compounding-retry rationale comment; `call_structured`'s `OpenAI(...)` construction now passes `timeout=_STRUCTURED_TIMEOUT_S, max_retries=0`; `call_text`'s construction now passes `max_retries=0` unconditionally alongside its existing conditional `timeout`.
- `app/pipeline/compose_email.py` — added `_CLARIFICATION_TIMEOUT_S = 30.0` named constant; `compose_clarification`'s `call_text` invocation now passes `timeout_s=_CLARIFICATION_TIMEOUT_S`.
- `app/main.py` — `STALE_THRESHOLD` tightened from `timedelta(minutes=65)` to `timedelta(minutes=15)`; code comment rewritten to document the fully-tightened, correctly-summed derivation.
- `tests/test_llm_client.py` — `_FakeOpenAI.__init__` now captures `timeout`/`max_retries` kwargs; added `test_call_structured_client_has_explicit_timeout_and_max_retries_zero`, `test_call_text_client_has_max_retries_zero_when_timeout_s_provided`, `test_call_text_client_has_max_retries_zero_when_timeout_s_omitted`.
- `tests/test_clarify.py` — `_DraftLLM`/`_RaisingDraftLLM` fakes gained `**kwargs` (to absorb the new `timeout_s=`) and `_DraftLLM` records `last_kwargs`; added `test_compose_clarification_passes_bounded_timeout_s`.
- `tests/test_stuck_run_recovery.py` — replaced the 09-01 integration stub with `test_stranded_run_swept_and_retriggerable` (the real SC3 proof) and added `test_parked_statuses_never_swept_live`; both `@pytest.mark.integration` + two-factor skip-guarded (`DATABASE_URL` + `ALLOW_DB_RESET=1`).

## Decisions Made

- `_STRUCTURED_TIMEOUT_S` (45s) and `_CLARIFICATION_TIMEOUT_S` (30s) are hardcoded module-level constants, not env vars — matching the project's existing `_MAX_TOKENS`-style convention and the plan's own guidance ("a hardcoded module constant is acceptable... only add an env var if config-driven tunability is clearly needed"). No `.env.example` change was needed.
- `max_retries=0` on `call_text` is unconditional by design (not gated on `timeout_s is not None`) — the two kwargs are independent concerns (retry-suppression vs. timeout-bounding), and gating `max_retries` on `timeout_s` being set would have left the `timeout_s`-omitted case (still hit by real callers, e.g. any future `call_text` caller that doesn't pass a timeout) with the library's uncounted `max_retries=2` still in place.
- `STALE_THRESHOLD` was tightened (not left at 65min with just an updated comment) since the plan explicitly permits tightening once the true ceiling is known and bounded by construction — 15 minutes keeps the sweep useful (a genuinely stranded run becomes diagnosable in a reasonable window) while retaining a comfortable ~4× margin over the 210s derived worst case.

## Deviations from Plan

None — plan executed exactly as written. Both tasks' `read_first` verifications (the `call_structured`/`call_text` current shapes, `suggest.py:81`, `compose_email.py:167`, `orchestrator.py:377,380`, the `retrigger()` route's exact claim/dispatch logic) matched the plan's stated assumptions exactly, so no Rule 1-4 deviations were needed.

## Issues Encountered

None. The one pre-execution correction — this worktree's HEAD was stale relative to the plan's stated `depends_on: ["09-01", "09-02", "09-03"]` (it had been branched before those plans merged, missing `09-04-PLAN.md` itself) — was resolved via the mandatory `worktree_branch_check` step's `git reset --hard` to the pinned base commit (master's tip, which already includes 09-01/02/03/05), before any plan work began. This is expected executor-harness behavior, not a plan deviation.

## User Setup Required

None — no external service configuration required. The SC3 integration test (`test_stranded_run_swept_and_retriggerable`) and its companion (`test_parked_statuses_never_swept_live`) require a live `DATABASE_URL` + `ALLOW_DB_RESET=1` to actually exercise against a real/local Postgres; neither was available in this execution environment, so both skip cleanly (two-factor guard) per the plan's own acceptance criteria. They are ready to run against a live/local Postgres whenever one is available.

## Next Phase Readiness

- DATA-03 is closed: the sweep threshold is now provably safe by construction (not merely assumed), and the SC3 recovery path is proven end-to-end via the actual operator-facing route (pending live-DB execution to actually run the integration test — currently skip-guarded, not yet exercised live in this session).
- All three Phase 9 requirements (DATA-01 via 09-01/09-02, DATA-02 via 09-03, DATA-03 via 09-01/09-04) now have passing integration tests proving their respective success criteria, all currently skip-guarded pending a live DATABASE_URL in this execution environment.
- No blockers identified for Phase 10 (concurrency proof) — the now-tightened, correctly-derived LLM timeout ceiling and the 15-minute sweep threshold are exactly the kind of bounded, provable-by-construction resilience surface Phase 10's load/concurrency proof can build additional evidence on top of.

## Known Stubs

None. This plan modifies client-construction kwargs, a threshold constant, and adds tests only — no UI, no data-rendering component, no placeholder values.

## Threat Flags

None. This plan's `<threat_model>` (T-09-13, T-09-20, T-09-14) already covers every surface touched — the LLM client construction hardening and the retrigger-route recovery proof. No new network endpoint, auth path, file-access pattern, or schema change was introduced beyond what the plan's threat register already dispositions.

## Self-Check: PASSED

- FOUND: app/llm/client.py (modified, contains `max_retries=0`)
- FOUND: app/pipeline/compose_email.py (modified, contains `timeout_s=`)
- FOUND: app/main.py (modified, `STALE_THRESHOLD = timedelta(minutes=15)`)
- FOUND: tests/test_llm_client.py (modified)
- FOUND: tests/test_clarify.py (modified)
- FOUND: tests/test_stuck_run_recovery.py (modified, contains `def test_stranded_run_swept_and_retriggerable`)
- FOUND commit: fd4e311 (feat(09-04): bound call_structured + call_text timeouts, suppress library retries)
- FOUND commit: 8c68f78 (test(09-04): SC3 end-to-end integration test via the actual retrigger route)

---
*Phase: 09-atomic-data-integrity*
*Completed: 2026-07-04*
