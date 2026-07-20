---
phase: 21-durability-proofs-ops-view
plan: 12
subsystem: testing
tags: [pytest, pydantic-settings, ci, github-actions, poppler-utils]

# Dependency graph
requires: []
provides:
  - "Suite-wide autouse tests/conftest.py fixture that stubs DATABASE_URL only when absent, so get_settings() never raises in a bare checkout (worktree or CI) with no .env"
  - "tests/test_webhook_dedup_race.py's live-DB skip guard converted from a runtime os.environ check to the import-time frozen _HAS_DB pattern, closing the un-skip hazard the new autouse fixture would otherwise create"
  - ".github/workflows/ci.yml's hermetic test job now installs poppler-utils so tests/test_pdf.py's pdftotext-based assertion executes on ubuntu-latest instead of erroring"
affects: [ci, tests]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Autouse pytest fixtures that mutate shared env state (DATABASE_URL) must account for BOTH collection-time skipif guards (safe, frozen before any fixture runs) and any test that re-reads os.environ inside its own body at runtime (unsafe unless that check is also frozen at import time)"

key-files:
  created: []
  modified:
    - tests/conftest.py
    - tests/test_webhook_dedup_race.py
    - .github/workflows/ci.yml

key-decisions:
  - "Autouse DATABASE_URL stub leaves the sentinel SET in os.environ for the whole test (mirrors mock_llm's existing precedent) rather than priming get_settings()'s lru_cache and then deleting the var — several existing tests (test_gateway.py) call get_settings.cache_clear() themselves mid-test and expect DATABASE_URL to still be resolvable from the environment afterward; a prime-then-delete design broke that pattern."
  - "Converted tests/test_webhook_dedup_race.py's two runtime os.environ.get(\"DATABASE_URL\") skip checks to an import-time frozen _HAS_DB constant (the exact pattern ~8 other test modules already use) instead of leaving DATABASE_URL out of the autouse stub for that one file — this is the surgical fix for the one file where a runtime check would otherwise be un-skipped by the new suite-wide stub."

requirements-completed: [PROOF-05]

coverage:
  - id: D1
    description: "Hermetic suite (no DATABASE_URL, no .env) is green: 1190 passed, 95 skipped, 0 failed"
    requirement: PROOF-05
    verification:
      - kind: unit
        ref: "uv run pytest -q (DATABASE_URL unset, no .env in worktree)"
        status: pass
    human_judgment: false
  - id: D2
    description: "-m integration and -m queueproof collection counts are unchanged by the stub (truth #3)"
    requirement: PROOF-05
    verification:
      - kind: unit
        ref: "uv run pytest tests/ -m integration --collect-only -q (94/1285 before and after)"
        status: pass
      - kind: unit
        ref: "uv run pytest tests/ -m queueproof --collect-only -q (63/1285 before and after)"
        status: pass
    human_judgment: false
  - id: D3
    description: "The DATABASE_URL stub is inert when a real DSN is present — live-DB tests still connect to the real database, not the sentinel"
    requirement: PROOF-05
    verification:
      - kind: integration
        ref: "DATABASE_URL=postgresql://pnhek@localhost:5432/pa_p21_12 ALLOW_DB_RESET=1 uv run pytest tests/test_send_idempotency.py -k test_the_unconfirmed_guard_is_epoch_scoped -q (real repo.create_run/seeded_db round-trip)"
        status: pass
      - kind: unit
        ref: "DATABASE_URL=postgresql://pnhek@localhost:5432/pa_p21_12 ALLOW_DB_RESET=1 uv run pytest tests/test_repo_jobs_sql.py -q (plan's specified target file — turned out to be entirely hermetic, see Deviations)"
        status: pass
    human_judgment: false
  - id: D4
    description: "tests/test_pdf.py renders and asserts real extracted PDF text — not skipped or weakened; .github/workflows/ci.yml's hermetic job installs poppler-utils so it also runs on ubuntu-latest"
    requirement: PROOF-05
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_pdf.py -q (green locally on macOS, which already has pdftotext)"
        status: pass
      - kind: other
        ref: "grep -n poppler-utils .github/workflows/ci.yml (exactly one match, in the test job, before 'Run test suite')"
        status: pass
    human_judgment: true
    rationale: "The apt-get install step itself cannot be verified locally (macOS already has pdftotext) — it is CI-confirmed-pending. A human must confirm the next CI run on ubuntu-latest passes tests/test_pdf.py."

# Metrics
duration: 35min
completed: 2026-07-20
status: complete
---

# Phase 21 Plan 12: Restore CI to green — DATABASE_URL settings stub + poppler-utils Summary

**Suite-wide autouse `tests/conftest.py` fixture stubs `DATABASE_URL` when absent (never overriding a real DSN), fixed the one test file whose runtime skip-check that stub would otherwise have un-skipped against the sentinel, and installed `poppler-utils` in CI's hermetic job so `tests/test_pdf.py` actually executes instead of erroring on `ubuntu-latest`.**

## Performance

- **Duration:** 35 min
- **Started:** 2026-07-20T15:34:00Z (approx, wave start)
- **Completed:** 2026-07-20T16:10:00Z (approx)
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Hermetic full suite (`DATABASE_URL` unset, no `.env`, exactly the condition `.github/workflows/ci.yml` runs) went from `16 failed, 1174 passed, 95 skipped` to `0 failed, 1190 passed, 95 skipped`.
- Proved (not assumed) that the stub cannot un-skip a live-DB test: `-m integration`/`-m queueproof` `--collect-only` counts are byte-identical before and after (`94/1285`, `63/1285`), and a genuine live-DB round-trip test (`test_send_idempotency.py::test_the_unconfirmed_guard_is_epoch_scoped`) still connects to the real throwaway Postgres, not the sentinel.
- `.github/workflows/ci.yml`'s `test` job now installs `poppler-utils` before running the suite, closing the second, independent root cause (`FileNotFoundError: 'pdftotext'` on `ubuntu-latest`).

## Task Commits

1. **Task 1: Suite-wide settings stub, inert when a real DATABASE_URL exists** - `712e9fb` (fix)
2. **Task 2: Provision poppler-utils for the hermetic CI job** - `21a59bf` (ci)

**Plan metadata:** (this commit)

## Files Created/Modified
- `tests/conftest.py` - New autouse `_stub_database_url_when_absent` fixture; sets `DATABASE_URL` to the existing `postgresql://mock-test-stub/mockdb` sentinel only when `os.environ.get("DATABASE_URL")` is falsy, clears `get_settings()`'s `lru_cache` before and after regardless.
- `tests/test_webhook_dedup_race.py` - Added a module-level `_HAS_DB = bool(os.environ.get("DATABASE_URL"))` constant (evaluated at import time, matching ~8 other test modules' established pattern) and changed both of the module's runtime `if not os.environ.get("DATABASE_URL"): pytest.skip(...)` checks to `if not _HAS_DB:`.
- `.github/workflows/ci.yml` - Added an `apt-get install -y -qq poppler-utils` step to the `test` job, between "Install deps" and "Run test suite", with a comment naming `tests/test_pdf.py` as the reason.

## Decisions Made

- **Stub leaves `DATABASE_URL` set in `os.environ` for the whole test, not just briefly.** The first design attempted to prime `get_settings()`'s `lru_cache` with a stub `Settings` instance and then immediately delete the sentinel from `os.environ`, so any test that checks the raw environment variable directly would still see it as absent. This broke `tests/test_gateway.py::test_send_reserved_snapshot_replays_fixed_payload_and_idempotency_key`, which calls `get_settings.cache_clear()` itself mid-test (to pick up its own `RESEND_API_KEY`/`RESEND_REPLY_TO` monkeypatches) and expects `DATABASE_URL` to still be resolvable from the environment afterward — clearing the cache wiped the primed stub, and the deleted sentinel meant the next real `Settings()` construction raised `ValidationError` again. Reverted to the simpler design that mirrors `mock_llm`'s existing precedent exactly: leave the sentinel set in `os.environ` whenever it applies one.
- **Fixed `tests/test_webhook_dedup_race.py` instead of trying to avoid touching `os.environ["DATABASE_URL"]` at all.** With the sentinel left set for the whole test, `tests/test_webhook_dedup_race.py::test_duplicate_webhook_delivery_creates_exactly_one_run`'s own runtime check (`if not os.environ.get("DATABASE_URL"): pytest.skip(...)`) — evaluated inside the test body, AFTER the new autouse fixture's setup already ran — would see the sentinel as present and proceed to fire two real HTTP threads at a `TestClient` and then open a genuine `repo.get_connection()` against `postgresql://mock-test-stub/mockdb`, which does not exist. This is exactly the T-21-12-01 hazard (tampering: the stub un-skips live-DB tests) the plan's own threat model names. This file was NOT among the plan's 5 forbidden files (`test_gateway.py`, `test_delivery.py`, `test_alias_write.py`, `test_alias_and_run_column_regressions.py`, `test_multi_employee_delivery.py`) and was not part of the original 16 failing tests, so editing it does not violate the plan's "do not touch the 16 failing test files" constraint. Converted its `os.environ.get(...)` runtime checks to an import-time-frozen `_HAS_DB` constant — the exact pattern already used successfully by ~8 other modules in this suite (`test_send_idempotency.py`, `test_seed_roundtrip.py`, `test_gateway.py`, `test_threading.py`, `test_atomic_persist.py`, `test_persistence.py`, `test_ingest.py`, `test_email_epoch_arbiter_integration.py`) and by the module-level `_HAS_DB`/`_SKIP_LIVE_DB` guard already in `tests/conftest.py` itself. `tests/test_claim_status.py:170` has the identical runtime-check shape, but its very next line is an *unconditional* `pytest.skip("Integration test stub...")`, so the runtime check being un-skipped there is a no-op (it still hits the unconditional skip immediately after) — left untouched, no fix needed.
- **Second live-DB verification target used instead of the plan's specified file.** The plan's task-1 verification block names `tests/test_repo_jobs_sql.py` for the "stub is inert against a real DSN" proof. That file turned out to be entirely hermetic (`FakeConnection`-only, zero `@pytest.mark.integration` or `_SKIP_LIVE_DB` tests) — running it against the real throwaway DB proves nothing about live-DB connectivity, only that it still passes. Ran it as specified (passed, `76 passed in 0.25s`) AND additionally ran a genuine live-DB test (`test_send_idempotency.py::test_the_unconfirmed_guard_is_epoch_scoped`, which uses the `seeded_db` fixture and calls `repo.create_run`/`repo.insert_email_message`/`repo.clear_reply_context` against a real connection) to actually exercise the real-DB path this truth is meant to prove.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed comment-provenance guard violation in the new conftest fixture's docstring**
- **Found during:** Task 1
- **Issue:** The first draft of the new fixture's comment block cited `T-21-12-01` / `T-21-12-02` (this plan's own threat-model IDs) as justification, which `tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree` flags — a comment must state the constraint, not the ticket that produced it.
- **Fix:** Rewrote the comment to describe the safety argument in prose (what the guard prevents and why) without citing the ticket IDs.
- **Files modified:** tests/conftest.py
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py -q` — 5 passed.
- **Committed in:** 712e9fb (Task 1 commit)

**2. [Rule 1 - Bug] Fixed the un-skip hazard in tests/test_webhook_dedup_race.py caused by the new autouse fixture**
- **Found during:** Task 1's mandated verification (`uv run pytest -q`), which is exactly how this was supposed to be caught rather than assumed away.
- **Issue:** See "Decisions Made" above — the naive autouse stub un-skipped `test_duplicate_webhook_delivery_creates_exactly_one_run`, which then failed trying to open a real Postgres connection against the sentinel DSN.
- **Fix:** Converted the file's two runtime `os.environ.get("DATABASE_URL")` checks to an import-time frozen `_HAS_DB` constant, matching the established codebase pattern.
- **Files modified:** tests/test_webhook_dedup_race.py
- **Verification:** Full hermetic suite green (`1190 passed, 95 skipped, 0 failed`); `-m integration`/`-m queueproof` collection counts unchanged.
- **Committed in:** 712e9fb (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — bugs in the new code introduced by this plan's own Task 1, caught by the plan's own mandated verification steps).
**Impact on plan:** Both fixes were necessary to make Task 1's stated truths (hermetic-green, collection-counts-unchanged, stub-inert-against-real-DSN) actually hold rather than merely appear to hold on a shallow rerun. No scope creep — no production code (`app/`) touched, and neither of the 2 extra files touched is among the plan's 5 explicitly forbidden files.

## Issues Encountered

The plan's stated baseline ("Before your changes, in a no-DATABASE_URL run the suite is `17 failed, 1173 passed, 95 skipped`") did not match the measured baseline in this worktree (`16 failed, 1174 passed, 95 skipped` — one fewer failure). The list of 16 failing tests matched the plan's named 5 files exactly (`test_gateway.py`, `test_delivery.py`, `test_alias_write.py`, `test_alias_and_run_column_regressions.py`, `test_multi_employee_delivery.py`); the plan's task-1 verification block also predicted a post-fix state of `1 failed, 1189 passed` (with only `test_pdf.py` failing on `pdftotext`), which did not hold locally because macOS already has `pdftotext` installed (`/opt/homebrew/bin/pdftotext`) — task 1 alone produced a fully green `0 failed, 1190 passed` locally, and task 2's `pdftotext` gap is real but only observable on `ubuntu-latest` in CI, exactly as the plan's own task-2 verification block anticipated ("CI-confirmed-pending, do NOT claim it verified from a local pass"). Neither discrepancy changed the required fix; both are noted here for the record rather than treated as a blocker, per instruction to report actual measured results rather than the plan's assumed numbers.

An earlier, more complex fixture design (priming `get_settings()`'s `lru_cache` and then deleting the sentinel from `os.environ`, intended to avoid touching the raw env var at all) was tried and abandoned in favor of the simpler design described above — see "Decisions Made."

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `.github/workflows/ci.yml` should go green on `master` after this plan merges: task 1 is fully verified locally (exact CI condition reproduced: no `.env`, `DATABASE_URL` unset); task 2's `apt-get install poppler-utils` step is CI-confirmed-pending — a human/CI run must confirm `tests/test_pdf.py` passes on `ubuntu-latest` after merge.
- No blockers for the rest of Phase 21's durability-proofs plans; this plan only touched `tests/conftest.py`, `tests/test_webhook_dedup_race.py`, and `.github/workflows/ci.yml`.

---
*Phase: 21-durability-proofs-ops-view*
*Completed: 2026-07-20*

## Self-Check: PASSED

- FOUND: tests/conftest.py
- FOUND: tests/test_webhook_dedup_race.py
- FOUND: .github/workflows/ci.yml
- FOUND: .planning/phases/21-durability-proofs-ops-view/21-12-SUMMARY.md
- FOUND commit: 712e9fb (task 1)
- FOUND commit: 21a59bf (task 2)
- FOUND commit: 71e98ab (plan metadata)
