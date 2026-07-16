---
phase: 18-failure-policy-sweep-deletion
plan: 14
subsystem: durable-queue
tags: [python, postgres, reply-ownership, pii-safe-logging, tdd]

requires:
  - phase: 18-09
    provides: identifier-only resume-reply jobs and persisted-email reconstruction
  - phase: 18-11
    provides: strict PipelineResult-only producer and consumer graph
  - phase: 18-13
    provides: complete final-attempt lease settlement and starvation closure
provides:
  - canonical same-run ownership validation before persisted reply conversion or replay
  - identifier-free bounded diagnostics for invalid durable reply context
  - unconditional hermetic resume-handler regressions and guarded Postgres association proofs
affects: [19-webhook-cutover-durable-ingest, 21-durability-proofs-ops-view]

tech-stack:
  added: []
  patterns:
    - canonicalize independently persisted foreign keys and require exact ownership before replay
    - fail closed before content conversion while logging only a bounded reason code

key-files:
  created:
    - .planning/phases/18-failure-policy-sweep-deletion/18-14-SUMMARY.md
  modified:
    - app/queue/handlers/resume_reply.py
    - tests/test_resume_pipeline.py
    - tests/test_queue_durability.py

key-decisions:
  - "Persisted reply ownership is proven by canonical row.run_id equality with job.run_id before row_to_inbound, reclaim, or orchestration."
  - "Invalid reply context logs only the bounded invalid_operator_override_context reason and no correlation identifiers or stored content."

patterns-established:
  - "Cross-row durable authority: independent foreign keys are inputs, not proof of same-run ownership."
  - "Hermetic regression modules run independently of DATABASE_URL; live Postgres evidence remains separately guarded."

requirements-completed: [FAIL-01, FAIL-02]

coverage:
  - id: D1
    description: "A persisted reply reaches RECEIVED orchestration only when its canonical row owner equals the job run; null, malformed, same-business wrong-run, and cross-business owners fail before conversion."
    requirement: FAIL-02
    verification:
      - kind: unit
        ref: "tests/test_resume_pipeline.py -k 'resume_reply_handler or persisted or reclaim' (7 passed with DATABASE_URL unset and 7 passed with a stub)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Invalid durable reply context emits one bounded reason code without UUIDs, business or email identifiers, addresses, subject, body, or names."
    requirement: FAIL-02
    verification:
      - kind: unit
        ref: "tests/test_resume_pipeline.py#test_resume_reply_handler_rejects_unowned_persisted_context_before_conversion"
        status: pass
    human_judgment: false
  - id: D3
    description: "The complete hermetic resume module runs in both environment states and reclaim requires explicit PipelineOutcome.OK without advancing reply_epoch."
    requirement: FAIL-01
    verification:
      - kind: integration
        ref: "env -u DATABASE_URL ... pytest -q tests/test_resume_pipeline.py (31 passed)"
        status: pass
      - kind: integration
        ref: "DATABASE_URL=postgresql://stub:stub@localhost/stub ... pytest -q tests/test_resume_pipeline.py (31 passed)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Real Postgres rejects same-business and cross-business reply mismatches and retains a same-run positive control."
    requirement: FAIL-02
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py -m queueproof -k 'resume_reply and association' (3 selected, 3 skipped by two-factor database guard)"
        status: unknown
    human_judgment: true
    rationale: "DATABASE_URL and ALLOW_DB_RESET=1 were unavailable, so the guarded live proof is recorded as unavailable rather than passed."

duration: 9min
completed: 2026-07-16
status: complete
---

# Phase 18 Plan 14: Same-Run Persisted Reply Ownership Summary

**Durable reply replay now proves exact same-run ownership before reading money-moving content, with bounded identifier-free rejection and unconditional hermetic regression evidence.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-16T16:15:20Z
- **Completed:** 2026-07-16T16:24:15Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Added a fail-closed canonical UUID ownership check before `row_to_inbound`, reclaim, or `resume_pipeline`, closing null, malformed, same-business wrong-run, and cross-business replay paths.
- Reduced invalid-context logging to one static event plus the bounded reason code, with hostile absence assertions covering every injected UUID and sensitive subject/body/name/address token.
- Removed the inappropriate module-wide database guard, required explicit `PipelineOutcome.OK` on reclaim, and added a guarded real-Postgres mismatch matrix plus a positive same-run control.

## Task Commits

1. **Task 1 RED: Failing reply-ownership and unconditional-regression proofs** - `11a0bc7` (test)
2. **Task 1 GREEN: Canonical same-run validation and bounded logs** - `91e56bb` (fix)
3. **Task 2: Guarded Postgres association counterexamples and control** - `923d2f6` (test)

## Files Created/Modified

- `app/queue/handlers/resume_reply.py` - Canonicalizes persisted row ownership and rejects invalid context before content conversion or replay.
- `tests/test_resume_pipeline.py` - Runs unconditionally and proves wrong-run ordering, PII-free logs, valid same-run replay, and explicit OK reclaim.
- `tests/test_queue_durability.py` - Adds guarded real-Postgres same-business/cross-business mismatch cases and a same-run control.
- `.planning/phases/18-failure-policy-sweep-deletion/18-14-SUMMARY.md` - Records plan evidence and closure.

## Decisions Made

- Ownership comparison uses `UUID(str(row["run_id"]))` and exact equality with the already-validated `job.run_id`; absent or unparsable values fail closed.
- Invalid-context diagnostics deliberately sacrifice correlation identifiers at this boundary to guarantee stored email content and cross-tenant identifiers cannot escape through the failure log.

## Deviations from Plan

None - plan executed as specified.

## Issues Encountered

- The first exact offline `uv run` command hit the known macOS uv system-configuration panic. Re-running through uv with an isolated cache and `--no-sync` used the existing lock-synchronized environment and completed every requested check.
- The reset-enabled live Postgres environment was unavailable. All three association queueproof cases collected and skipped under the existing two-factor guard; no live pass is claimed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- CR-02 and WR-01 are closed by always-run behavior and strict result assertions.
- Phase 18 is ready for centralized re-verification; the guarded Postgres association proof remains useful evidence when a reset-enabled database is available.

## Self-Check: PASSED

- Task 1 RED proof: 4 failed and 3 passed before production changes.
- Focused handler suite: 7 passed with DATABASE_URL unset and 7 passed with a harmless stub.
- Complete resume module: 31 passed in each environment state.
- Guarded live queueproof: 3 selected and 3 skipped by the two-factor database guard.
- Full suite: 899 passed, 69 skipped.
- Ruff passed for all three plan-owned source/test files; mypy passed for the production handler; `git diff --check` passed.
- Commits `11a0bc7`, `91e56bb`, and `923d2f6` exist in history.
- The authoritative untracked `18-VERIFICATION.md` remains unstaged and unchanged by this plan.

---
*Phase: 18-failure-policy-sweep-deletion*
*Completed: 2026-07-16*
