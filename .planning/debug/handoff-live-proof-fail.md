---
status: resolved
trigger: "Phase 20's authorized live provider-handoff queueproof run has two failures."
created: 2026-07-18T00:00:00Z
updated: 2026-07-18T00:00:00Z
---

# Debug Session: Handoff Live Proof Fail

## Symptoms

- expected: The authorized resettable-Postgres command selects nine Phase 20 repair, expiry, and provider-handoff queueproofs; all should pass with zero skips.
- actual: The new authorization-expiry schema and expiry regressions pass live, but two existing provider-handoff proofs fail.
- error: The protected proof raises `LockNotAvailable` while locking `payroll_runs`; the control proof cannot find the expected active provider handoff to release.
- timeline: The issue was observed during Phase 20 Plan 27 Task 3 after the new live schema/expiry suite was added and run against the authorized disposable database.
- reproduction: `DATABASE_URL="$DATABASE_URL" ALLOW_DB_RESET=1 uv run pytest -q tests/test_queue_durability.py -m 'integration and queueproof' -k 'authorization_expired or deployed_schema_repair or provider_handoff' -rs` returns 2 failed, 7 passed, 49 deselected, and zero skips.

## Current Focus

- hypothesis: Each proof calls `_backend_pid(conn)` before entering its intended `conn.transaction()` block. On a default psycopg connection that `SELECT` opens an implicit outer transaction; the following `conn.transaction()` is only a savepoint, so the real handoff insert is not committed at the barrier. The worker therefore retains its `payroll_runs` lock and the control connection cannot observe the uncommitted handoff.
- next_action: Complete; live proof is green.
- reasoning_checkpoint:
  hypothesis: "The PID diagnostic query creates the uncommitted outer transaction that causes both failures."
  confirming_evidence:
    - "`_backend_pid()` executes `SELECT pg_backend_pid()` before the authorizer's explicit transaction in both worker wrappers."
    - "`clear_reply_context()` first locks `payroll_runs`; the protected proof's observed LockNotAvailable is exactly the lock retained by an uncommitted authorizer transaction."
    - "The control proof reads an authorization object in Python but cannot UPDATE the corresponding active handoff from its separate connection, which is predicted when the insert is uncommitted."
  falsification_test: "If the diagnostic SELECT is committed before the barrier and either live proof still shows a payroll_runs lock conflict or invisible handoff, this hypothesis is false."
  fix_rationale: "Move each diagnostic PID query into a complete transaction before the barrier, preserving the intended contract: authorization commits before the two-connection interleaving begins."
  blind_spots: "The live DB command must be run after the change; an offline skip cannot establish this transaction-pooling behavior."

## Evidence

- timestamp: 2026-07-18T00:00:00Z
  source: Phase 20 Plan 27 Task 3 authorized live run
  observation: The focused schema/expiry subset passes live with 7 passed and zero skips, proving the disposable database and new expiry paths work; the full required command fails only the two existing provider-handoff proofs.
- timestamp: 2026-07-18T00:00:00Z
  source: live failure output
  observation: `test_provider_handoff_blocks_epoch_bump_before_gateway` receives `LockNotAvailable` when locking `payroll_runs`, while `test_provider_handoff_race_control_observes_stale_gateway_when_fence_is_released` cannot find an active handoff expected by its release operation.
- timestamp: 2026-07-18T00:00:00Z
  source: direct source inspection
  observation: Both test wrappers execute `_backend_pid(conn)` before `with conn.transaction()`. psycopg starts a transaction for that SELECT; a later `Connection.transaction()` within it is a savepoint rather than a committing outer transaction.
- timestamp: 2026-07-18T00:00:00Z
  source: authorized disposable-Postgres verification
  observation: `pytest -q tests/test_queue_durability.py -m 'integration and queueproof' -k 'authorization_expired or deployed_schema_repair or provider_handoff' -rs` completed with `9 passed, 49 deselected in 31.68s`; no tests were skipped.

## Eliminated

- hypothesis: The guarded database configuration is unavailable or tests skipped.
  reason: The authorized run executed all nine selected tests with zero skips and seven passed.

## Resolution

- root_cause: `_backend_pid()` executed SQL before the intended outer transaction in both two-connection test wrappers. Psycopg therefore opened an implicit outer transaction, and the subsequent authorizer block only created a savepoint. The active handoff stayed invisible and its `payroll_runs` lock stayed held at the barrier.
- fix: Remove the pre-transaction SQL probe. Record distinct pooled client connection identities with `id(conn)` inside the intended transaction, so the authorizer genuinely commits before the interleaving and the test remains valid for Supavisor transaction pooling.
- verification: `uv run ruff check tests/test_queue_durability.py`; `uv run mypy tests/test_queue_durability.py`; authorized live command above: 9 passed, 49 deselected, zero skips.
- files_changed: `tests/test_queue_durability.py`; `.planning/debug/handoff-live-proof-fail.md`
- cycles: 1 investigation, 1 fix
