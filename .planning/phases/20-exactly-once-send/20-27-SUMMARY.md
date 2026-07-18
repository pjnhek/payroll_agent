---
phase: 20-exactly-once-send
plan: 27
subsystem: outbound-delivery
tags: [postgres, schema-repair, delivery-review, queueproof, concurrency]

# Dependency graph
requires:
  - phase: 20-exactly-once-send
    provides: immutable outbound snapshots, replay-window expiry handling, and provider-handoff fencing
provides:
  - identical fresh-install and deployed-repair vocabulary for bounded outbound attempt failures
  - real-Postgres repair evidence for a legacy attempt-category constraint
  - zero-skip live evidence for expiry review paths and the two-connection provider-handoff proof
affects: [outbound delivery, schema bootstrap, delivery review, phase-21 durability proofs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - fresh DDL and deployed repair enumerate one identical bounded failure-category vocabulary
    - two-connection proofs must not issue SQL before their intended outer transaction

key-files:
  created: []
  modified:
    - app/db/schema.sql
    - tests/test_send_idempotency.py
    - tests/test_queue_durability.py
    - .planning/debug/handoff-live-proof-fail.md

key-decisions:
  - "authorization_expired is a fixed, PII-safe ledger category accepted by both a fresh schema and the idempotent deployed-schema repair."
  - "Provider-handoff tests record distinct client connection identities inside their explicit transactions, avoiding an implicit psycopg transaction that would invalidate the real concurrency schedule."

patterns-established:
  - "A deployed-schema repair proof must inspect pg_constraint and perform a real constrained INSERT; schema text alone is insufficient."
  - "A recorded zero-skip guarded database result remains evidence when a later local process lacks the destructive-test credentials; the unavailable rerun is not represented as a pass."

requirements-completed: [SEND-01, SEND-02, SEND-03]

coverage:
  - id: D1
    description: "Fresh installs and the non-reset deployed-schema repair accept the exact bounded authorization_expired attempt category."
    requirement: SEND-03
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py#test_deployed_schema_repair_accepts_authorization_expired"
        status: pass
      - kind: unit
        ref: "tests/test_send_idempotency.py#schema category parity guards"
        status: pass
    human_judgment: false
  - id: D2
    description: "Pre-provider and gateway-boundary replay expiry write delivery-review evidence without provider I/O or regenerated frozen content."
    requirement: SEND-03
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py#authorization_expired expiry regressions"
        status: pass
    human_judgment: false
  - id: D3
    description: "The protected and intentionally unsafe control schedules both run against real PostgreSQL, proving the provider handoff fence blocks the dangerous epoch bump and exposes its release."
    requirement: SEND-01
    verification:
      - kind: integration
        ref: "tests/test_queue_durability.py#test_provider_handoff_blocks_epoch_bump_before_gateway"
        status: pass
      - kind: integration
        ref: "tests/test_queue_durability.py#test_provider_handoff_race_control_observes_stale_gateway_when_fence_is_released"
        status: pass
    human_judgment: false

# Metrics
duration: ~8h 32m
completed: 2026-07-18
status: complete
---

# Phase 20 Plan 27: Live Schema and Expiry Evidence Summary

**Fresh and repaired Postgres schemas now accept bounded authorization-expiry evidence, while real guarded proofs verify review settlement and the two-connection provider-handoff fence.**

## Performance

- **Started:** 2026-07-18T16:01:00Z
- **Completed:** 2026-07-18T17:32:31Z
- **Tasks:** 3/3
- **Files modified:** 4

## Accomplishments

- Added one static parity guard so fresh schema DDL and deployed constraint repair cannot diverge from the `authorization_expired` settlement category.
- Added guarded real-Postgres tests that repair an emulated legacy CHECK through `bootstrap(reset=False)`, prove the catalog vocabulary, execute the constrained INSERT, and verify both replay-expiry boundaries reach purpose-aware review without provider I/O.
- Fixed the two existing handoff proofs: their PID diagnostic SQL opened an implicit outer psycopg transaction, so the intended authorization transaction was only a savepoint. Moving the connection-identity observation inside the explicit transaction restored the committed two-connection schedule.

## Task Commits

1. **Task 1: Make fresh and deployed attempt-ledger constraints accept authorization expiry** — `013b6f5`, `38003df`
2. **Task 2: Add guarded real-Postgres deployed-schema repair and expiry regressions** — `6f317fe`, `837e01a`, `cda23e3`, `6e4c2a6`
3. **Task 3: Apply and verify the resettable production-schema evidence** — `c5e6851` (Rule 1 concurrency-harness fix and recorded live evidence)

## Files Created/Modified

- `app/db/schema.sql` — aligns fresh and idempotent-repair failure-category checks.
- `tests/test_send_idempotency.py` — asserts fresh/repair vocabulary parity with the emitted settlement category.
- `tests/test_queue_durability.py` — adds deployed-schema and expiry-boundary proofs; corrects the provider-handoff transaction boundary.
- `.planning/debug/handoff-live-proof-fail.md` — preserves the failure, diagnosis, repair, and zero-skip live result.

## Decisions Made

- A legacy deployed category constraint is proven through the production non-reset bootstrap, PostgreSQL catalog inspection, and a real INSERT rather than inferred from SQL text.
- Distinct Python connection identities are sufficient for the test's two-client schedule and remain compatible with Supavisor transaction pooling; querying backend PID before the explicit transaction is unsafe.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed pre-transaction SQL from the handoff proof wrappers.**

- **Found during:** Task 3 live provider-handoff verification.
- **Issue:** `_backend_pid()` began an implicit psycopg transaction, making the following authorization `conn.transaction()` a savepoint; the active handoff was invisible and held the run lock at the barrier.
- **Fix:** Record `id(conn)` inside the intended explicit transaction and remove the SQL probe.
- **Files modified:** `tests/test_queue_durability.py`, `.planning/debug/handoff-live-proof-fail.md`.
- **Verification:** Authorized live suite passed 9 selected tests with zero skips after the fix.
- **Committed in:** `c5e6851`.

**Total deviations:** 1 auto-fixed (Rule 1 correctness).
**Impact on plan:** The fix restores, rather than changes, the plan's required committed authorization-before-barrier schedule.

## Issues Encountered

- The initial authorized full live run failed only the two existing provider-handoff tests (2 failed, 7 passed, zero skips). The transaction-boundary defect above was diagnosed and fixed; the next authorized run passed **9 passed, 49 deselected** with zero skips.
- A later close-out rerun could not inherit `DATABASE_URL`, so the guarded command reported **9 skipped, 49 deselected**. This unavailable local rerun is not treated as passing; the post-fix zero-skip result above is the recorded live evidence.
- The plan's `ruff check app/db/schema.sql ...` command is not executable because Ruff parses Python rather than PostgreSQL DDL (5,172 parser errors). The valid Python-file Ruff scope passed; the live bootstrap/repair test is the schema verification.

## User Setup Required

None - the user already authorized the disposable database reset used for the recorded live proof.

## Next Phase Readiness

Phase 20 is complete. Phase 21 can rely on the repaired, zero-skip provider-handoff queueproof and on `authorization_expired` as a durable bounded attempt fact.

## Evidence

- `uv run pytest -q tests/test_send_idempotency.py tests/test_gateway.py tests/test_phase20_fake_parity.py` — **126 passed, 6 skipped**.
- `uv run pytest tests/ -m queueproof --collect-only -q | rg 'authorization_expired|deployed_schema_repair|test_provider_handoff_(blocks_epoch_bump_before_gateway|race_control_observes_stale_gateway_when_fence_is_released)'` — **9 required live tests collected**.
- Authorized live command: `DATABASE_URL="$DATABASE_URL" ALLOW_DB_RESET=1 uv run pytest -q tests/test_queue_durability.py -m 'integration and queueproof' -k 'authorization_expired or deployed_schema_repair or provider_handoff' -rs` — **9 passed, 49 deselected, zero skips** (post-fix; recorded in `.planning/debug/handoff-live-proof-fail.md`).
- Close-out rerun of the same command without credentials in the current process — **9 skipped, 49 deselected**; recorded as unavailable, not passing.
- `uv run ruff check tests/test_send_idempotency.py tests/test_queue_durability.py` — **passed**.
- `uv run mypy` — **Success: no issues found in 161 source files**.

## Self-Check: PASSED

---
*Plan: 20-27*
*Completed: 2026-07-18*
