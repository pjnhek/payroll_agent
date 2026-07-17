---
phase: 19-webhook-cutover-durable-ingest
plan: 08
subsystem: durable-reply-operator-resume
tags: [python, fastapi, postgres, durable-queue, sender-authorization, first-commit-authority]

requires:
  - phase: 19-webhook-cutover-durable-ingest
    provides: persisted reply context, identifier-only job vocabulary, and first-commit operator authority API
  - phase: 18-failure-policy-sweep-deletion
    provides: retry-safe resume handlers and bounded PipelineResult settlement
provides:
  - atomic persisted reply plus RESUME_REPLY scheduling for real and simulated replies
  - sender and same-run authorization before every durable reply conversion or orchestration
  - atomic immutable operator generation plus generation-specific OPERATOR_RESUME scheduling
  - winner-only alias projection and payroll resume with bounded superseded no-op handling
affects: [19-09-queue-ui, 19-11-stale-consumer-migration, 19-12-producer-cutover-guards, 21-durability-proofs]

tech-stack:
  added: []
  patterns:
    - caller-owned transaction around persisted context and the exact owed job
    - post-commit wake with identifier-only queue records
    - commit-selected operator authority consumed before mapping or business-state access

key-files:
  created: []
  modified:
    - app/routes/runs.py
    - app/routes/pipeline_glue.py
    - app/queue/handlers/resume_reply.py
    - app/queue/handlers/operator_resume.py
    - app/db/repo/__init__.py
    - tests/conftest.py
    - tests/test_resume_pipeline.py
    - tests/test_reply_redelivery.py
    - tests/test_needs_operator.py

key-decisions:
  - "Reply handlers prove persisted same-run ownership and sender authorization before row conversion, then use stored status and CAS outcomes rather than job attempts as authority."
  - "Every valid operator submission receives an immutable generation and generation-specific job in the same transaction; the repository's first commit, never worker order, selects authority."
  - "Superseded operator jobs return explicit OK before loading mappings, claiming run state, projecting aliases, or invoking orchestration; only winner preparation may project remember intent."

patterns-established:
  - "Reply owed-work invariant: persisted/linkable reply context and resume_reply:{run_id}:{email_id} commit together, then wake after commit."
  - "Operator owed-work invariant: immutable generation and operator_resume:{run_id}:{resolution_id} job commit together for winner and loser alike."
  - "Bounded no-op boundaries exclude sender, submitted-name, employee, run, email, job, and resolution identifiers from logs and redirect notice selection."

requirements-completed: [QUEUE-04]

coverage:
  - id: D1
    description: "Real and simulated replies atomically persist/link reply context with one deduplicated RESUME_REPLY job, and duplicates ensure the same job without creating another."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_reply_redelivery.py#test_simulated_reply_commits_persisted_email_and_durable_job"
        status: pass
      - kind: unit
        ref: "tests/test_reply_redelivery.py#test_duplicate_persisted_reply_ensures_same_durable_job"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every durable reply attempt checks persisted same-run ownership and sender authorization before conversion or orchestration, while late and advanced states are bounded no-ops."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_resume_pipeline.py#test_resume_reply_revalidates_sender_before_conversion_or_orchestration"
        status: pass
      - kind: unit
        ref: "tests/test_resume_pipeline.py#test_resume_reply_advanced_state_is_bounded_noop_before_conversion"
        status: pass
    human_judgment: false
  - id: D3
    description: "Each valid operator generation commits with its generation-specific job in one transaction, and superseded submissions receive only the fixed resolution_superseded flag."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_needs_operator.py#test_resolve_commits_generation_and_job_in_same_transaction"
        status: pass
      - kind: unit
        ref: "tests/test_needs_operator.py#test_resolve_superseded_generation_keeps_job_and_uses_fixed_notice"
        status: pass
    human_judgment: false
  - id: D4
    description: "A superseded operator handler returns OK before side effects, while the authoritative handler prepares remember intent, claims NEEDS_OPERATOR, and resumes with the immutable mapping."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_needs_operator.py#test_operator_resume_superseded_generation_is_bounded_ok_before_side_effects"
        status: pass
      - kind: unit
        ref: "tests/test_needs_operator.py#test_operator_resume_authoritative_generation_prepares_claims_then_resumes"
        status: pass
    human_judgment: false

duration: 23min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 08: Durable Reply and Operator Authority Summary

**Reply and operator continuations now commit their persisted authority with identifier-only durable jobs, while sender checks and first-commit winner selection remain mandatory on every worker attempt.**

## Performance

- **Duration:** 23 min
- **Started:** 2026-07-17T01:30:00Z
- **Completed:** 2026-07-17T01:52:50Z
- **Tasks:** 2 TDD tasks
- **Files modified:** 9

## Accomplishments

- Replaced real and simulated reply process-memory handoffs with one caller-owned transaction that persists or rehydrates the reply, links it to the exact run, and enqueues `resume_reply:{run_id}:{email_id}` before a post-commit wake.
- Hardened `RESUME_REPLY` so persisted row ownership, canonical run equality, run load, and sender authorization all precede conversion or orchestration; stored status/CAS controls first work, reclaim, and bounded advanced-state no-ops.
- Replaced `/resolve` background dispatch with immutable generation commit plus `operator_resume:{run_id}:{resolution_id}` enqueue in one transaction for both winners and superseded submissions.
- Made `OPERATOR_RESUME` consume commit-selected authority first: losers drain as explicit OK before side effects, while only the winner projects remember intent, claims `NEEDS_OPERATOR -> RECEIVED`, and resumes payroll.

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Pin durable reply producer authorization** - `7e411d0` (test)
2. **Task 1 GREEN: Make reply continuations durable** - `1323f55` (feat)
3. **Task 2 RED: Pin operator generation authority** - `afcace3` (test)
4. **Task 2 GREEN: Enforce durable operator authority** - `d654866` (feat)

## Files Created/Modified

- `app/routes/runs.py` - Uses the durable reply classifier for simulated replies and atomically commits every operator generation with its exact job and bounded redirect flag.
- `app/routes/pipeline_glue.py` - Persists, rehydrates, authorizes, links, and transactionally enqueues reply continuations with bounded outcomes.
- `app/queue/handlers/resume_reply.py` - Revalidates persisted ownership and sender authorization before conversion and uses stored business status for claim/reclaim decisions.
- `app/queue/handlers/operator_resume.py` - Prepares commit-selected authority, drains losers before side effects, and resumes only the authoritative generation.
- `app/db/repo/__init__.py` - Exposes the Plan 19-02 operator authority API through the repository facade.
- `tests/conftest.py` - Mirrors immutable generation authority and winner-only remember projection in the in-memory repository double.
- `tests/test_resume_pipeline.py` - Proves authorization-before-conversion, status claim, and advanced-state no-op behavior.
- `tests/test_reply_redelivery.py` - Proves simulated/duplicate reply durability and updates the supported durable operator entry-point guard.
- `tests/test_needs_operator.py` - Proves atomic generation/job commits, bounded loser redirects, winner-only handling, and durable end-to-end resume.

## Decisions Made

- The reply classifier returns payload-free bounded outcomes; only a fully authorized persisted row can request a post-commit wake.
- A duplicate reply rehydrates the original persisted row and body, then ensures the same deduplicated job rather than trusting the redelivered request payload.
- The operator route never projects aliases or claims payroll state. The authority repository classifies the generation under lock, and the durable winner handler owns remember projection plus the forward claim.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Exported authority seams and preserved fake-repository parity**
- **Found during:** Task 2 (Enqueue every operator generation and apply only the winner)
- **Issue:** Plan 19-02's authority functions existed in their aggregate module but were not available through the project's required `from app.db import repo` facade, and the in-memory repo had only the legacy unclassified mapping API.
- **Fix:** Re-exported the typed authority APIs and added first-commit generation metadata, winner-only remember projection, and fixture patch wiring to `InMemoryRepo`.
- **Files modified:** `app/db/repo/__init__.py`, `tests/conftest.py`
- **Verification:** Repo/fake pairing guard, focused operator gate, Ruff, and mypy passed.
- **Committed in:** `d654866`

---

**Total deviations:** 1 auto-fixed (1 Rule 3 blocking issue)
**Impact on plan:** The extra facade and fake changes were required to call the planned authority contract through the established data-layer boundary and test the production semantics hermetically; no business scope was added.

## Issues Encountered

- The repository-wide offline suite reached **990 passed, 74 skipped, 3 failed**. The failures are outside this plan's verification gates: one intentionally stale simulated-reply wrapper consumer assigned to Plan 19-11, one live-DB demo integration lacking its reset-authorized environment, and one pre-existing runs-list AST expectation that does not account for Plan 19-07's bounded query flag. The exact Plan 19-08 gates and the combined modified-surface suite are green.
- The existing Starlette/httpx deprecation warning remains unchanged.

## User Setup Required

None - no external service configuration required.

## Verification

- Task 1 RED gate: 4 expected failures before implementation.
- Task 1 final plan gate: 10 passed, 39 deselected.
- Task 2 RED gate: 4 expected failures before implementation.
- Task 2 final plan gate: 21 passed, 3 skipped, 54 deselected.
- Combined modified-surface suite: 94 passed, 42 skipped.
- Full `tests/test_needs_operator.py`: 36 passed, 1 skipped.
- Ruff: passed for every modified Python production and test file.
- Mypy: passed for all five modified production modules.
- `git diff --check`: passed.

## Next Phase Readiness

- Plan 19-09 can consume the fixed `resolution_superseded=1` flag without handling submitted names, employee ids, mappings, or competing generation identifiers.
- Plan 19-11 can migrate the intentionally retained stale wrapper-test consumers to these explicit durable seams.
- Plan 19-12 can delete compatibility wrappers and install the permanent non-vacuous producer guard after those consumers move.
- No schema, dependency, endpoint, new business status, or LLM decision was introduced.

## Known Stubs

None.

## Self-Check: PASSED

- All nine modified production/test files and this summary exist.
- TDD commits `7e411d0`, `1323f55`, `afcace3`, and `d654866` are present in history.
- Exact plan verification, combined surface tests, static analysis, and diff-check gates are green.
- Full-suite exceptions are explicitly bounded to follow-on or environment-owned consumers; no Plan 19-08 gate is red.

---
*Phase: 19-webhook-cutover-durable-ingest*
*Completed: 2026-07-16*
