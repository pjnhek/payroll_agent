---
phase: 19-webhook-cutover-durable-ingest
plan: 02
subsystem: database
tags: [postgres, concurrency, operator-authority, immutable-generations, tdd]

requires:
  - phase: 19-01
    provides: "Authority, supersession, remember, partial uniqueness, and writer-fence schema"
  - phase: 18-02
    provides: "Immutable typed operator-resolution parent and child persistence"
provides:
  - "Run-lock serialized first-commit authority with PII-bounded submission results"
  - "Immutable superseded generations, exact replay idempotency, and generation-specific dedup keys"
  - "Winner-only alias-candidate preparation from persisted remember intent"
affects: [19-08, operator-resume, alias-learning, durable-queue]

tech-stack:
  added: []
  patterns:
    - "commit-selected authority: SELECT FOR UPDATE serializes money-moving generations before worker scheduling"
    - "bounded repository results: authority classifications expose UUIDs and booleans, never submitted mappings"
    - "winner-only preparation: superseded generations validate then return without payroll or alias mutation"

key-files:
  created: []
  modified:
    - app/db/repo/operator_resume_resolutions.py
    - tests/test_needs_operator.py

key-decisions:
  - "Exact replay of a committed resolution UUID remains idempotent even after the run advances, but any mapping or remember mismatch fails closed."
  - "Every new valid generation validates the current deterministic unresolved-name set and employee ownership under the target run lock before insertion."
  - "Alias candidates are merged only by authoritative preparation and only for overrides whose persisted remember choice is true."

patterns-established:
  - "Operator resume dedup keys include both run ID and immutable resolution ID."
  - "Loser generations carry an explicit superseded_by winner and remain bounded successful no-ops when prepared first."

requirements-completed: [QUEUE-04]

coverage:
  - id: D1
    description: "The first valid complete operator generation committed under the run lock becomes the sole payroll authority."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_needs_operator.py -k 'generation or authority or superseded or remember or mapping'"
        status: pass
      - kind: integration
        ref: "tests/test_needs_operator.py#test_operator_authority_real_threads_commit_order_beats_worker_order"
        status: unknown
    human_judgment: true
    rationale: "Hermetic lock-order and one-winner contracts pass, but the guarded real-Postgres thread proof was unavailable without DATABASE_URL and ALLOW_DB_RESET=1."
  - id: D2
    description: "Later valid generations remain immutable superseded audit history with exact replay and generation-specific enqueue deduplication."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_needs_operator.py#test_commit_operator_resolution_retains_later_generation_as_superseded"
        status: pass
      - kind: unit
        ref: "tests/test_needs_operator.py#test_operator_resolution_generation_exact_replay_is_idempotent_but_conflict_fails"
        status: pass
    human_judgment: false
  - id: D3
    description: "Only the authoritative generation can project remembered aliases; a superseded generation validates and returns without mutation."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_needs_operator.py#test_prepare_operator_resolution_keeps_loser_noop_and_projects_only_winner_remember"
        status: pass
      - kind: other
        ref: "uv run --offline --no-sync pytest -q (936 passed, 70 skipped)"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 02: Commit-Serialized Operator Authority Summary

**Operator mappings now acquire payroll authority under the target run lock, preserving every later generation as immutable audit history while only the committed winner can project alias-learning intent.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-17T00:12:47Z
- **Completed:** 2026-07-17T00:25:10Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added a frozen, PII-bounded `OperatorResolutionSubmission` plus the exact `operator_resume:{run_id}:{resolution_id}` dedup convention consumed by the durable producer cutover.
- Added a caller-transaction-aware commit primitive that locks the run, validates deterministic unresolved-name completeness and business-roster ownership, classifies the first valid generation as authoritative, and persists later generations with explicit winner references.
- Added exact UUID replay idempotency across later run states while rejecting conflicting mappings, remember choices, cross-run ownership, corrupt authority state, and incomplete or cross-business input.
- Added winner preparation that validates the immutable generation and merges only `remember=true` candidates; superseded preparation returns a bounded no-op before any alias or payroll mutation.
- Added hermetic SQL/behavior counterexamples and a guarded genuine two-thread Postgres proof whose skip states that live concurrency evidence is unavailable in this environment.

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Prove commit order rather than worker order selects authority** - `c6c6aff` (test)
2. **Task 2 GREEN: Implement commit-serialized authority and winner preparation** - `94ea6ee` (feat)

## Files Created/Modified

- `app/db/repo/operator_resume_resolutions.py` - Bounded authority result, generation dedup key, run-lock submission, exact replay, supersession, roster validation, and winner-only preparation.
- `tests/test_needs_operator.py` - Repository-shape, replay, mapping, supersession, PII-boundary, remember-isolation, and guarded real-thread authority proofs.

## Decisions Made

- Exact replay checks persisted mapping and per-override remember intent before accepting an existing resolution UUID; a mismatch is a conflict even if employee IDs are unchanged.
- New generations validate against the run's current deterministic `Decision.unresolved_names` and current business roster while holding the run row lock, so stale forms and cross-business IDs fail before insertion.
- Preparation merges only the remembered winner subset into `alias_candidates`, preserving unrelated existing candidates through JSONB merge semantics.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Preserved the pre-cutover legacy generation reader**
- **Found during:** Task 2 regression verification
- **Issue:** Reusing the new six-column authority reader inside the legacy create/load API broke its established three-column FakeConnection contract and would reject unfenced pre-cutover generations.
- **Fix:** Kept the new authority reader private to commit/preparation and restored a dedicated three-column mapping reader for the legacy API until Plan 19-08 cuts consumers over and the deployment fence retires old writes.
- **Files modified:** `app/db/repo/operator_resume_resolutions.py`
- **Verification:** All 56 repository SQL tests and the 936-test offline suite passed.
- **Committed in:** `94ea6ee`

---

**Total deviations:** 1 auto-fixed bug.
**Impact on plan:** The fix preserves current production compatibility without weakening the new authority path or adding scope.

## Issues Encountered

- The guarded real-Postgres authority proof was collected but skipped because this environment does not provide both `DATABASE_URL` and `ALLOW_DB_RESET=1`; no live concurrency result is claimed.
- A repository-boundary spot-check referenced a nonexistent historical test filename; the actual full offline suite subsequently passed and includes the active permanent gates.
- The full suite emitted the existing Starlette/httpx deprecation warning.

## User Setup Required

None - no external service configuration required.

## Verification

- Focused authority/mapping gate: 8 passed, 1 guarded live-DB skip.
- Complete `tests/test_needs_operator.py`: 32 passed, 1 guarded live-DB skip.
- Complete `tests/test_repo_jobs_sql.py`: 56 passed.
- Ruff: passed for both modified files.
- Mypy: passed for `app/db/repo/operator_resume_resolutions.py`.
- Full offline suite: 936 passed, 70 guarded skips.
- `git diff --check`: passed.

## Next Phase Readiness

- Plan 19-08 can atomically pair `commit_operator_resume_resolution` with the generation-specific `OPERATOR_RESUME` enqueue and bounded superseded redirect flag.
- Its operator handler can call `prepare_authoritative_operator_resume`; a losing worker may run first and still cannot affect payroll or alias learning.
- The guarded deployment fence and live authority migration remain owned by Plan 19-10.

---
*Phase: 19-webhook-cutover-durable-ingest*
*Completed: 2026-07-16*

## Self-Check: PASSED

Both modified files and this summary exist; task commits `c6c6aff` and `94ea6ee`
are present; coverage metadata classifies cleanly; focused, repository, Ruff, mypy,
full-suite, and diff-check gates are green. No tracked file was deleted and no
generated artifact remains untracked.
