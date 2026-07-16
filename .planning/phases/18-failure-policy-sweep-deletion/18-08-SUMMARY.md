---
phase: 18-failure-policy-sweep-deletion
plan: 08
subsystem: database
tags: [python, postgres, durable-queue, deletion, fake-pairing, tdd]

requires:
  - phase: 18-failure-policy-sweep-deletion
    plan: 07
    provides: "Caller-first removal of page-load recovery and preservation of supported recovery paths"
  - phase: 18-failure-policy-sweep-deletion
    plans: [02, 03, 09, 11]
    provides: "Persisted resume context, immutable operator authority, strict results, atomic settlement, and final-lease reaping"
provides:
  - "Production repositories and facade with no age-based automatic recovery APIs"
  - "Strict in-memory repository without retired recovery mirrors or patch entries"
  - "Non-vacuous source/fake negative inventory plus positive durable replacement pairing"
affects: [19-webhook-cutover-durable-ingest, durable-recovery, test-harness]

tech-stack:
  added: []
  patterns:
    - "caller-first API subtraction: remove every caller before deleting definitions, exports, and strict fakes"
    - "source-aware negative inventory paired with explicit positive replacement assertions"

key-files:
  created:
    - .planning/phases/18-failure-policy-sweep-deletion/18-08-SUMMARY.md
  modified:
    - app/db/repo/runs.py
    - app/db/repo/emails.py
    - app/db/repo/pipeline_state.py
    - app/db/repo/__init__.py
    - app/models/status.py
    - tests/conftest.py
    - tests/test_fake_repo_pairing.py
    - tests/test_stuck_run_recovery.py
    - tests/test_dashboard.py

key-decisions:
  - "The durable queue is the only automatic recovery policy; no alias, wrapper, compatibility export, fake fallback, or age-based repository scan remains."
  - "Persisted email lookup, immutable operator resolutions, classified retry coordinators, atomic settlement, and final-lease reaping stay explicitly public and fake-paired."
  - "The public run-transition API retains its two-writer invariant while narrow context-reset and fenced-settlement coordinators keep their CAS-scoped authority."

patterns-established:
  - "Deletion guards scan nonempty production Python, HTML, and SQL sources and separately inspect AST definitions/exports."
  - "Strict fake deletion is proved at class, monkeypatch tuple, facade, and raw-source levels."

requirements-completed: [FAIL-03]

coverage:
  - id: D1
    description: "Both retired repository functions, their constants, facade exports, and stale production prose are completely absent."
    requirement: FAIL-03
    verification:
      - kind: integration
        ref: "tests/test_fake_repo_pairing.py#test_retired_recovery_symbols_are_absent_from_nonempty_production_sources"
        status: pass
      - kind: other
        ref: "! grep -R -n --exclude-dir=__pycache__ --include=*.py --include=*.html --include=*.sql 'retired recovery names' app"
        status: pass
    human_judgment: false
  - id: D2
    description: "The in-memory repository and fake patch tuple contain no retired recovery mirrors, while every durable replacement remains callable and paired."
    requirement: FAIL-03
    verification:
      - kind: integration
        ref: "tests/test_fake_repo_pairing.py"
        status: pass
      - kind: other
        ref: "uv run --offline pytest -q (855 passed, 81 skipped)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Webhook redelivery, sender and consumed-reply safeguards, durable operator resume, epoch isolation, Retrigger, and bounded failure presentation remain intact."
    requirement: FAIL-03
    verification:
      - kind: integration
        ref: "tests/test_stuck_run_recovery.py tests/test_reply_redelivery.py tests/test_needs_operator.py tests/test_retrigger_epoch.py tests/test_hitl.py"
        status: pass
      - kind: integration
        ref: "tests/test_dashboard.py -k safe_failure_projection"
        status: pass
    human_judgment: false

duration: 10min
completed: 2026-07-16
status: complete
---

# Phase 18 Plan 08: Retired Recovery API Deletion Summary

**The durable queue is now the sole automatic recovery mechanism, with both legacy age-based repository scans removed across production, facade, tests, and strict fakes.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-07-16T04:23:56Z
- **Completed:** 2026-07-16T04:33:49Z
- **Tasks:** 2 TDD tasks
- **Files modified:** 9

## Accomplishments

- Deleted both retired repository definitions, scope constants, facade imports/exports, and stale status/epoch prose without adding a compatibility alias or replacement sweep.
- Deleted the matching in-memory methods, sweep-only constant, comments, and monkeypatch entries so unknown retired calls now fail strictly.
- Added non-vacuous production-source and fake inventories that detect reintroduced definitions/exports while positively pinning persisted email, operator-resolution, settlement, retry, and final-lease APIs.
- Preserved webhook redelivery, sender/consumed safeguards, late replies, durable operator replay, epoch isolation, manual Retrigger, and safe failure presentation through focused and full-suite verification.

## Task Commits

1. **Task 1 RED: Retired production recovery inventory** - `c296c1a` (test)
2. **Task 1 GREEN: Production repository and facade subtraction** - `442f130` (refactor)
3. **Task 2 RED: Retired fake surface guard** - `488e64e` (test)
4. **Task 2 GREEN: Strict fake and transitional-test subtraction** - `6d93200` (refactor)
5. **Verification fix: Preserve status-writer and lint invariants** - `ceeeb6b` (fix)

## Files Created/Modified

- `app/db/repo/runs.py` - Removes the age-based run scan and retains the public transition-writer constraint.
- `app/db/repo/emails.py` - Removes the stale-unconsumed-reply scan while retaining exact persisted inbound lookup and sender/consumption seams.
- `app/db/repo/__init__.py` - Removes retired imports and exports while retaining all durable context, retry, settlement, and reaper APIs.
- `app/db/repo/pipeline_state.py` - Documents the human epoch bump versus automatic reclaim distinction without referring to deleted readers.
- `app/models/status.py` - Preserves the canonical RECEIVED/ERROR/NEEDS_OPERATOR vocabulary with queue-owned recovery prose.
- `tests/conftest.py` - Removes both fake methods, sweep-only state, comments, and patch registrations while keeping strict stateful replacements.
- `tests/test_fake_repo_pairing.py` - Adds non-vacuous source/AST/fake negative gates and positive durable replacement pairing.
- `tests/test_stuck_run_recovery.py` - Closes the caller-first transitional assertions against the now-deleted facade surface.
- `tests/test_dashboard.py` - Removes obsolete monkeypatches from the bounded failure-projection test.

## Decisions Made

- Used one negative inventory for raw production text and a separate AST inventory for definitions, imports, assignments, and `__all__`, so neither stale prose nor a compatibility export can evade the gate.
- Kept retired literals only in tests as deliberate gate fixtures; the final literal shell scan is restricted to application Python, HTML, and SQL.
- Preserved the public two-writer transition invariant and described the already-shipped context-reset/settlement coordinators as narrow CAS owners rather than reopening an unguarded status-writer path.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed transitional references outside the plan's file list**
- **Found during:** Task 2 GREEN
- **Issue:** `tests/test_stuck_run_recovery.py` still asserted the facade functions were callable, and `tests/test_dashboard.py` patched both names. Deleting the APIs while leaving those references made the required preservation/full-suite gates fail.
- **Fix:** Inverted the transitional facade assertion to require absence, removed the deleted seams from hostile-spy setup, and removed obsolete dashboard monkeypatches.
- **Files modified:** `tests/test_stuck_run_recovery.py`, `tests/test_dashboard.py`
- **Verification:** 56 supported-recovery tests and the full 855-test hermetic suite passed.
- **Committed in:** `6d93200`

**2. [Rule 1 - Bug] Preserved the public status-writer documentation gate**
- **Found during:** Plan-wide full-suite verification
- **Issue:** Rewriting the removed scan's adjacent comment also removed the exact `two writers` invariant pinned by `tests/test_claim_status.py`.
- **Fix:** Restored the public transition API's two-writer wording and distinguished narrow CAS-scoped context/settlement coordinators from an unsafe third unguarded helper.
- **Files modified:** `app/db/repo/runs.py`
- **Verification:** `tests/test_claim_status.py` and the full hermetic suite passed; Ruff and mypy remained clean.
- **Committed in:** `ceeeb6b`

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug).
**Impact on plan:** Both fixes were required to complete the deletion without weakening existing regression gates or leaving stale test callers; no new runtime behavior or trust boundary was added.

## Issues Encountered

- `rg` is unavailable in this environment, so searches used the documented `grep` fallback.
- The first RED inventory incorrectly treated an intentionally empty `app/__init__.py` as vacuous and initially checked raw substrings as set members. Both test-construction issues were corrected before the RED commit; the committed gate fails on the actual retired symbols.
- The full suite emits one existing Starlette `httpx` deprecation warning; it is unrelated to this plan.

## User Setup Required

None - no external service configuration required.

## Verification

- Focused caller-preservation suite: 56 passed.
- Final fake/source inventory: 8 passed.
- Dashboard bounded failure projection: 1 passed.
- Full hermetic suite: 855 passed, 81 skipped.
- Ruff: passed on all changed source and test files.
- Mypy: passed on all changed production Python files.
- Final application Python/HTML/SQL literal negative gate: zero matches.
- `git diff --check`: passed.

## Next Phase Readiness

- Phase 18 now has exactly one automatic recovery policy: durable queue retry, fenced settlement, and final-lease reaping.
- Phase 19 can cut remaining producers over to durable ingest without competing dashboard recovery behavior or compatibility APIs.
- No blockers, stubs, new dependencies, migrations, environment changes, or unmitigated high-severity threats remain.

## Self-Check: PASSED

- The summary and all nine implementation/test files exist.
- All five Plan 18-08 task/fix commits are present in git history.
- Every acceptance criterion, the coverage classifier, focused preservation gates, Ruff, mypy, the literal application-source gate, and the full hermetic suite passed.
- No generated or unrelated untracked artifact remains.

---
*Phase: 18-failure-policy-sweep-deletion*
*Completed: 2026-07-16*
