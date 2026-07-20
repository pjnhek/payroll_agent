---
phase: 21-durability-proofs-ops-view
plan: 13
subsystem: testing
tags: [pytest, postgres, queue, ast-guard, schema-migration, append-only]

requires:
  - phase: 20-exactly-once-send
    provides: mandatory authorize_outbound_provider_handoff before every SEND_OUTBOUND handoff
provides:
  - "tests/test_queue_durability.py's -m queueproof selection green (63 passed, 0 skipped) again after four independent test-side regressions"
  - "a structurally leak-proof schema-repair test (try/finally CHECK restoration, proven under a forced-exception mutation)"
  - "an unbroken worker.start() AST guard proven to still red on a genuine violation"
affects: [21-03, 21-08]

tech-stack:
  added: []
  patterns:
    - "reserve->enqueue->claim->authorize->settle is the sanctioned test idiom for any test that calls settle_outbound_delivery_job or reap_expired_final_attempt directly (bypassing handle_send_outbound), matching Phase 20's mandatory-authorization contract"
    - "schema-mutating tests that install a temporary constraint must wrap the mutation + repair-triggering call in try/finally so a mid-migration exception cannot leak state into later tests in the same module-scoped fixture"
    - "TRUNCATE (not DELETE) is required to clear DB-enforced append-only tables (BEFORE UPDATE OR DELETE triggers) from test code; must list every FK-linked table in one TRUNCATE statement"

key-files:
  created: []
  modified:
    - tests/test_queue_durability.py

key-decisions:
  - "B4: renamed the two plain threading.Thread locals literally named `worker` to `handler_thread` rather than weakening the AST guard's match predicate — the guard's teeth were re-proven with a scratch-only genuine violation before landing the fix"
  - "B1 cutoff-job case: rather than forcing a spurious authorize call that would return ProviderHandoffActive('replay_window_closed') and never create a handoff row, changed the settle call's PipelineResult to the TERMINAL DELIVERY_AUTHORIZATION_EXPIRED result production actually produces for an already-expired reservation, which is what settlement's pre-provider-expiry review path requires"
  - "B3: chose to isolate this test's own data (TRUNCATE + DELETE the accumulated outbound audit trail before the widening migration runs) over weakening app/db/schema.sql's widening migration or the test's own assertions"

requirements-completed: [PROOF-01, PROOF-04, PROOF-05]

coverage:
  - id: D1
    description: "worker.start() AST guard (B4) no longer false-positives on the two already-joined threading.Thread locals in the handoff race/control tests, and still reds on a genuine direct worker.start() violation"
    requirement: PROOF-05
    verification:
      - kind: unit
        ref: "tests/test_queue_durability.py::test_every_worker_start_call_goes_through_the_live_worker_wrapper"
        status: pass
    human_judgment: false
  - id: D2
    description: "7-column settlement fake row (B2) matches the production _lock_outbound_reservation SELECT shape (epoch element restored at index 4)"
    requirement: PROOF-01
    verification:
      - kind: unit
        ref: "tests/test_queue_durability.py::test_invalid_context_settlement_retires_exact_leased_row"
        status: pass
    human_judgment: false
  - id: D3
    description: "Four settlement/reaper tests (B1) authorize the provider handoff before calling settle_outbound_delivery_job / reap_expired_final_attempt directly, matching Phase 20's mandatory-authorization contract"
    requirement: PROOF-01
    verification:
      - kind: unit
        ref: "tests/test_queue_durability.py::test_outbound_delivery_settlement_proves_retry_cutoff_and_zombie_fence"
        status: pass
      - kind: unit
        ref: "tests/test_queue_durability.py::test_final_send_lease_reap_preserves_snapshot_and_enters_purpose_review[confirmation-approved-DeliveryReview]"
        status: pass
      - kind: unit
        ref: "tests/test_queue_durability.py::test_final_send_lease_reap_preserves_snapshot_and_enters_purpose_review[clarification-awaiting_reply-ClarificationDeliveryReview]"
        status: pass
      - kind: unit
        ref: "tests/test_queue_durability.py::test_final_send_lease_reap_preserves_snapshot_and_enters_purpose_review[clarification_field_regression-awaiting_reply-ClarificationDeliveryReview]"
        status: pass
    human_judgment: false
  - id: D4
    description: "Schema-mutating test (B3) restores the modern failure_category CHECK unconditionally, including on a raising bootstrap(reset=False) -- proven by forcing a failure inside it and confirming the six downstream tests still pass"
    requirement: PROOF-04
    verification:
      - kind: unit
        ref: "tests/test_queue_durability.py::test_deployed_schema_repair_accepts_authorization_expired"
        status: pass
      - kind: integration
        ref: "manual forced-exception teardown proof: RuntimeError injected after legacy CHECK install, before bootstrap(reset=False) -- full -m queueproof rerun: 62 passed / 1 failed (only the deliberately-broken test), 0 collateral failures"
        status: pass
    human_judgment: false
  - id: D5
    description: "Full -m queueproof selection is green with an empty skip report; no production source under app/ modified"
    requirement: PROOF-01
    verification:
      - kind: unit
        ref: "ALLOW_DB_RESET=1 uv run pytest tests/ -m queueproof -v -rs -> 63 passed, 1222 deselected, 0 skipped"
        status: pass
      - kind: other
        ref: "git status --porcelain app/ -> empty"
        status: pass
    human_judgment: false

duration: ~35min
completed: 2026-07-20
status: complete
---

# Phase 21 Plan 13: Repair Four Independent Test-Side Regressions in test_queue_durability.py Summary

**Fixed a false-positive AST guard, a 6-column fake row shifted by a missing epoch column, four tests bypassing Phase 20's now-mandatory provider-handoff authorization, and a leaking un-restored schema mutation — `-m queueproof` goes from 13 failed/50 passed to 63 passed/0 skipped.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3
- **Files modified:** 1 (`tests/test_queue_durability.py`)

## Accomplishments

- **B4 (AST guard false positive):** renamed the two plain `threading.Thread` locals literally named `worker` in the handoff race/control tests to `handler_thread`, so `test_every_worker_start_call_goes_through_the_live_worker_wrapper`'s name-matching guard stops flagging already-joined, asserted-not-alive threads unrelated to the sanctioned `_LiveWorkerHandle.start` wrapper. Re-proved the guard still reds: on a scratch (never-committed) copy, reintroduced a genuine direct `worker.start()` call and confirmed the guard failed with `worker.start(...) called directly outside _LiveWorkerHandle.start at line(s) [2078]`, then reverted.
- **B2 (7-column settlement fake row):** verified `app/db/repo/job_settlement.py:191-199`'s `_lock_outbound_reservation` SELECT against live source (7 columns: `snapshot.id, reserved_at, purpose, round, epoch, send_state, replay_window_open`) and inserted the missing integer `epoch` element into the scripted 6-tuple fake row at `test_invalid_context_settlement_retires_exact_leased_row`, which had been silently shifting `int(row[4])` onto the `send_state` string. Falsifying mutation (removed the epoch element, confirmed the test failed again) run and reverted.
- **B1 (four tests missing the now-mandatory provider-handoff authorization):** Phase 20 made `handle_send_outbound` always call `repo.authorize_outbound_provider_handoff(job)` before delivery, and `settle_outbound_delivery_job`/`reap_expired_final_attempt` both now require a matching `outbound_provider_handoffs` row via `_lock_current_provider_handoff`. Four tests called the settlement/reaper functions directly (bypassing `handle_send_outbound`) and never created that row, landing in `INVALID_CONTEXT` instead of their intended outcome. Fixed by inserting `repo.authorize_outbound_provider_handoff(job)` after claim, before settling — the same idiom an existing passing test in this file already uses. One sub-case (the retry-cutoff test's second, already-expired reservation) needed a semantic correction rather than a bare authorize call: since the reservation's 20-hour replay window was already closed at both authorize-time and settle-time, `authorize_outbound_provider_handoff` correctly returns `ProviderHandoffActive('replay_window_closed')` without ever creating a handoff row — that's real production behavior, not a bug. The fix changed the settle call's `PipelineResult` from the generic `RETRYABLE`/`DELIVERY_TIMEOUT` to the `TERMINAL`/`DELIVERY_AUTHORIZATION_EXPIRED` result production actually produces for this case, which is what settlement's `pre_provider_expiry` review path (added in commit `0c48c2c`) is designed for. Falsifying mutation (removed the added authorize call from the retry-cutoff test, confirmed it returned to `INVALID_CONTEXT`) run and reverted.
- **B3 (leaking schema mutation):** `test_deployed_schema_repair_accepts_authorization_expired` installed a legacy `outbound_delivery_attempts` CHECK constraint, then called `bootstrap(reset=False)` with no `try/finally`. That call raises `UniqueViolation: uq_email_run_purpose_round` because the widening migration in `app/db/schema.sql:325-348` cannot re-add the narrow 3-column unique once other tests in the same module-scoped `seeded_db` fixture have left epoch-distinct `email_messages` rows behind for the same `(run_id, purpose, round)`. Because that migration statement runs *before* the `failure_category` CHECK repair block later in `schema.sql`, the raise prevents the repair from ever running, leaking the legacy CHECK into six later tests. Fixed two ways: (1) wrapped the test body in `try/finally`, with the `finally` unconditionally restoring the modern CHECK via a new idempotent helper, `_restore_modern_failure_category_check`; (2) addressed the root `UniqueViolation` itself (per the plan's "isolate this test's data" instruction) via `_isolate_outbound_history_before_widening_migration`, which clears the module's accumulated outbound audit trail before the migration runs. Because `outbound_email_snapshots`/`outbound_email_attachments`/`outbound_delivery_attempts` are DB-enforced append-only (`BEFORE UPDATE OR DELETE` triggers raising `RaiseException: ... is append-only`), this uses `TRUNCATE` — which does not fire row-level triggers — across all FK-linked tables in one statement, plus a plain `DELETE FROM email_messages WHERE direction = 'outbound'` (no such trigger on `email_messages`). No production code touched; the append-only guarantee is honored, not routed around.

## Task Commits

Each task was committed atomically:

1. **Task 1: B4 + B2 — two single-line repairs** - `2c2bb94` (fix)
2. **Task 2: B1 — restore the mandatory provider-handoff authorization in four tests** - `fbb5011` (fix)
3. **Task 3: B3 — make the schema mutation self-restoring** - `ff00922` (fix)

## Files Created/Modified
- `tests/test_queue_durability.py` - four independent test-side repairs (B4 AST-guard rename, B2 fake-row column fix, B1 four missing-authorization fixes, B3 try/finally + isolation helpers)

## Decisions Made
- B4: fixed the false positive by renaming the offending locals rather than weakening the AST guard's match predicate, and re-proved the guard's teeth on a scratch (never-committed) genuine violation before landing.
- B1 cutoff-job case: rather than forcing a spurious authorize call, changed the settle call's `PipelineResult` to the `TERMINAL`/`DELIVERY_AUTHORIZATION_EXPIRED` result production actually produces when a reservation's replay window has already closed — this is what routes through settlement's `pre_provider_expiry` review path; a bare authorize call there would never create a handoff row (real, correct behavior) and the original `RETRYABLE` result would have kept returning `INVALID_CONTEXT`.
- B3: chose to isolate this test's own data (clear the accumulated outbound audit trail via `TRUNCATE`+`DELETE` before the widening migration runs) over weakening `app/db/schema.sql`'s widening migration or the test's own assertions, per the plan's explicit preference. Confirmed `outbound_email_snapshots`/`outbound_email_attachments`/`outbound_delivery_attempts` are DB-enforced append-only and used `TRUNCATE` (which does not fire row-level triggers) rather than attempting per-row `DELETE`, which the append-only triggers correctly reject.

## Deviations from Plan

None — plan executed exactly as written. The B1 cutoff-job semantic correction (using the `TERMINAL`/`DELIVERY_AUTHORIZATION_EXPIRED` result instead of a bare authorize call) and the B3 append-only-aware `TRUNCATE` isolation strategy were both implementation decisions made *within* the plan's own explicit guidance ("Confirm each test still asserts what its name claims"; "Prefer isolating this test's data... over weakening the migration or the test") rather than deviations from it — no Rule 1-4 auto-fix or architectural-change was needed; no scope creep into `app/`.

## Issues Encountered

- Initial attempt at B3's data-isolation used targeted per-row `DELETE` statements against duplicate-epoch rows, which failed against the DB-enforced append-only triggers on `outbound_email_snapshots`/`outbound_email_attachments`/`outbound_delivery_attempts` (`RaiseException: outbound_email_snapshots is append-only`). Resolved by switching to `TRUNCATE` (which the schema's own append-only design does not — and by definition cannot — block, since it does not fire row-level triggers), scoped to clearing the whole outbound audit trail rather than surgical per-row deletes, which is both simpler and correctly respects the append-only invariant instead of working around it.
- `TRUNCATE` initially failed with `FeatureNotSupported: cannot truncate a table referenced in a foreign key constraint` because `outbound_provider_handoffs` FK-references `outbound_email_snapshots` and Postgres requires all FK-referencing tables in the same `TRUNCATE` statement even when empty. Resolved by adding `outbound_provider_handoffs` to the `TRUNCATE` list (harmless — it is already emptied around every test by the module's `_isolated_jobs` autouse fixture).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `tests/test_queue_durability.py`'s `-m queueproof` selection is green (63 passed, 0 skipped) again, unblocking plans 21-03 and 21-08, which both edit this same file and both carry "`-m queueproof` is green with an empty skip report" as an acceptance criterion.
- No regressions introduced: `uv run pytest tests/ -m "not integration and not live_llm" -q` shows the same 16 pre-existing failures (confirmed via `git stash` A/B comparison) in `test_alias_write.py`, `test_gateway.py`, `test_delivery.py`, `test_multi_employee_delivery.py`, and `test_alias_and_run_column_regressions.py` — none in files this plan touched, none newly introduced.
- `git status --porcelain app/` is empty: no production source was modified. All four causes were confirmed test-side drift against a coherent production contract, per the plan's `<critical_context>`.

## Self-Check: PASSED

- FOUND: tests/test_queue_durability.py
- FOUND: commit 2c2bb94
- FOUND: commit fbb5011
- FOUND: commit ff00922

---
*Phase: 21-durability-proofs-ops-view*
*Completed: 2026-07-20*
