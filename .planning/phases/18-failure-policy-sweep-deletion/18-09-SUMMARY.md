---
phase: 18-failure-policy-sweep-deletion
plan: 09
subsystem: durable-queue
tags: [python, postgres, resume-retry, operator-validation, tdd]

# Dependency graph
requires:
  - phase: 18-failure-policy-sweep-deletion
    plan: 02
    provides: "Eight-field jobs plus persisted email and immutable operator-resolution repositories"
  - phase: 18-failure-policy-sweep-deletion
    plan: 12
    provides: "Deployment schema-health proof for typed operator-resolution persistence"
provides:
  - "Lossless resume_reply handler that reloads the exact persisted inbound email"
  - "Validated operator_resume handler over complete immutable resolution mappings"
  - "Exactly set-equal three-kind Python, SQL, and module/name dispatch contracts"
  - "Strict in-memory mirrors for every new identifier and durable-context seam"
affects: [18-03, 18-04, 18-10, durable-retry, queue-dispatch]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "identifier-only retry handlers reconstruct authority from persisted repositories"
    - "durable operator mappings are validated against decision keys and business roster membership before replay"
    - "compatibility dispatch forwards PipelineResult or legacy None without normalizing"

key-files:
  created:
    - app/queue/handlers/resume_reply.py
    - app/queue/handlers/operator_resume.py
  modified:
    - app/models/job.py
    - app/db/schema.sql
    - app/queue/dispatch.py
    - tests/conftest.py
    - tests/test_job_kind_drift.py
    - tests/test_resume_pipeline.py
    - tests/test_needs_operator.py
    - tests/test_repo_jobs_sql.py

key-decisions:
  - "Both retry handlers re-enter resume_pipeline from RECEIVED; only attempts greater than one invoke rewind_for_reclaim, which never advances reply_epoch."
  - "Operator retry authority comes only from the immutable resolution rows, exact decision.unresolved_names equality, and roster membership; alias_candidates is never consulted."
  - "Dispatch preserves module/name late binding and forwards PipelineResult or legacy None unchanged until the central normalization wave."

patterns-established:
  - "Malformed durable context returns one bounded load-stage terminal result and logs correlation identifiers only."
  - "Fresh and deployed jobs kind/context constraints widen in the same commit as each real handler."

requirements-completed: [FAIL-01, FAIL-02]

coverage:
  - id: D1
    description: "Clarification retries reload the exact persisted inbound email and resume from RECEIVED without falling back to the original pipeline entrypoint."
    requirement: "FAIL-01"
    verification:
      - kind: integration
        ref: "tests/test_resume_pipeline.py -k 'resume_reply or persisted or received or reclaim'"
        status: pass
      - kind: integration
        ref: "tests/test_job_kind_drift.py#test_resume_reply_sql_requires_exact_identifier_context"
        status: pass
    human_judgment: false
  - id: D2
    description: "Operator retries reconstruct complete immutable mappings, reject malformed or cross-business authority, and preserve resolution-scoped idempotency."
    requirement: "FAIL-02"
    verification:
      - kind: integration
        ref: "tests/test_needs_operator.py -k 'operator_resume or override or reclaim'"
        status: pass
      - kind: integration
        ref: "tests/test_job_kind_drift.py#test_operator_resume_sql_requires_exact_identifier_context"
        status: pass
    human_judgment: false
  - id: D3
    description: "Python JobKind, deployed SQL checks, dispatch handlers, and strict in-memory repository seams stay exactly paired."
    requirement: "FAIL-02"
    verification:
      - kind: integration
        ref: "tests/test_job_kind_drift.py tests/test_fake_repo_pairing.py"
        status: pass
      - kind: other
        ref: "UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q (821 passed, 76 skipped)"
        status: pass
    human_judgment: false

duration: 17min
completed: 2026-07-16
status: complete
---

# Phase 18 Plan 09: Lossless Resume Handlers Summary

**Identifier-only retry jobs now reconstruct exact persisted reply or operator authority, validate it at the durable boundary, and re-enter one shared RECEIVED resume state machine.**

## Performance

- **Duration:** 17 min
- **Started:** 2026-07-16T01:07:52Z
- **Completed:** 2026-07-16T01:24:59Z
- **Tasks:** 3 TDD tasks
- **Files modified:** 10

## Accomplishments

- Added `resume_reply` as an atomic Python/SQL/dispatch expansion with exact email-id reconstruction, bounded invalid-context handling, result forwarding, and reclaim without an epoch bump.
- Added `operator_resume` as the final three-kind expansion, validating immutable resolution rows against the complete unresolved-name set and the run business roster before forwarding the complete override mapping.
- Tightened the in-memory queue and context repositories to the same three kind-specific identifier contracts, defensive-copy behavior, exact generation idempotency, call recording, and unchanged reflection-based patch pairing.

## Task Commits

Each TDD gate was committed atomically:

1. **Task 1 RED: Persisted reply handler and two-kind drift proofs** - `74cdb11` (test)
2. **Task 1 GREEN: Lossless persisted reply retries** - `c66d522` (feat)
3. **Task 2 RED: Durable operator mapping and final kind-boundary proofs** - `490a0bd` (test)
4. **Task 2 GREEN: Validated durable operator retries** - `44e5f68` (feat)
5. **Task 3 RED: Strict three-kind fake parity proofs** - `e0414cf` (test)
6. **Task 3 GREEN: Strict resume fake parity** - `567e209` (test)

## Files Created/Modified

- `app/queue/handlers/resume_reply.py` - Reloads one exact inbound email and forwards the shared resume result from RECEIVED.
- `app/queue/handlers/operator_resume.py` - Loads and validates one complete immutable operator mapping before replay.
- `app/models/job.py` - Declares exactly the three kinds with real handlers.
- `app/db/schema.sql` - Widens fresh/deployed kind checks and installs exact per-kind identifier constraints.
- `app/queue/dispatch.py` - Registers both resume handlers through late-bound module/name pairs and forwards their result.
- `tests/conftest.py` - Enforces three strict queue contracts, defensive context reads, and repository call recording.
- `tests/test_job_kind_drift.py` - Proves the final Python/SQL/dispatch equality and both context constraints.
- `tests/test_resume_pipeline.py` - Proves exact persisted reply reconstruction, reclaim, bounded failures, dispatch forwarding, and fake parity.
- `tests/test_needs_operator.py` - Proves complete operator authority, invalid-context rejection, idempotency, PII absence, reclaim, and fake parity.
- `tests/test_repo_jobs_sql.py` - Retires the intentionally temporary pre-handler kind assertion at the designated Plan 18-09 boundary.

## Decisions Made

- Reused `PipelineReason.INVALID_OPERATOR_OVERRIDE_CONTEXT` as the bounded terminal durable-context code during this compatibility wave; no exception text, submitted name, employee id, provider body, or mapping enters the result.
- Kept status ownership inside `resume_pipeline`: first attempts call the RECEIVED seam directly, while reclaimed attempts first use the established backward CAS and then call the same seam.
- Preserved module/name dispatch so monkeypatches remain live and cast only at the temporary producer return boundary; Plan 18-10 can remove the compatibility cast when producers return explicit results everywhere.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Retired the temporary Plan 18-02 one-kind schema assertion**
- **Found during:** Task 1 broader queue/schema verification
- **Issue:** `tests/test_repo_jobs_sql.py` intentionally pinned the pre-handler schema to `run_pipeline` only, which became stale at the exact Plan 18-09 widening boundary and failed the regression suite.
- **Fix:** Advanced the assertion first to the two-kind Task 1 boundary and then to the final three-kind Task 2 boundary while retaining exact textual equality.
- **Files modified:** `tests/test_repo_jobs_sql.py`
- **Verification:** 114 queue/repository/schema/fake-pairing tests passed; the full offline suite passed.
- **Committed in:** `c66d522`, `44e5f68`

---

**Total deviations:** 1 auto-fixed (1 blocking).
**Impact on plan:** The extra test file was a temporary predecessor guard whose own contract named Plan 18-09 as the future widening point; updating it preserved rather than expanded scope.

## Issues Encountered

- `rg` was unavailable, so repository searches used the documented `grep` fallback.
- The full suite emitted the existing Starlette `httpx` deprecation warning; no Phase 18 behavior is affected.

## User Setup Required

None - no external service configuration required.

## Verification

- `DATABASE_URL=postgresql://stub:stub@localhost/stub UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q tests/test_job_kind_drift.py tests/test_fake_repo_pairing.py tests/test_resume_pipeline.py tests/test_needs_operator.py` - 60 passed.
- `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline ruff check app/queue/handlers/resume_reply.py app/queue/handlers/operator_resume.py app/queue/dispatch.py tests/conftest.py` - passed.
- `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline mypy app/queue/handlers/resume_reply.py app/queue/handlers/operator_resume.py app/queue/dispatch.py` - passed.
- `UV_CACHE_DIR=/tmp/payroll-agent-uv-cache uv run --offline pytest -q` - 821 passed, 76 skipped.
- `git diff --check` - passed.

## Next Phase Readiness

- Plan 18-03 can persist validated route mappings and enqueue only run/resolution identifiers against the now-real operator handler.
- Plan 18-04 can normalize the forwarded compatibility result centrally in the drain.
- Plan 18-10 can cut both producers over from legacy `None` to explicit `PipelineResult` and remove compatibility casts.
- No blockers or unmitigated high-severity threats remain for this plan.

## Self-Check: PASSED

- Both created handlers and all eight modified implementation/test files exist.
- All six RED/GREEN task commits are present in git history.
- The 60-test plan gate, unchanged fake-pairing oracle, Ruff, mypy, `git diff --check`, and the full offline suite (821 passed, 76 skipped) are green.
- No tracked file was deleted, no generated artifact remains untracked, and no blocking stub or unplanned trust-boundary surface was introduced.

---
*Phase: 18-failure-policy-sweep-deletion*
*Completed: 2026-07-16*
