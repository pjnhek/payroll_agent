---
phase: 19-webhook-cutover-durable-ingest
plan: 10
subsystem: durable-ingest-deployment
tags: [python, postgres, durable-queue, retention, render, deployment-fence]

requires:
  - phase: 19-webhook-cutover-durable-ingest
    provides: durable receipt/job producers, delayed ingest, queue settlement, and retired-wrapper deletion
provides:
  - bounded terminal-only 30-day inbound-event retention invoked by the authenticated pump
  - post-200 recovery and separate Svix/RFC dedup evidence across hermetic and real-Postgres boundaries
  - fail-closed writer fencing, additive live schema migration, exact-revision activation proof, and verified reopen
affects: [QUEUE-04, phase-20-send-idempotency, phase-21-durability-proofs]

tech-stack:
  added: []
  patterns:
    - terminal payload retention runs in bounded batches without deleting open work or job audit
    - live cutovers close a persistent database fence before inventory and reopen only after exact-revision postflight

key-files:
  created:
    - tests/test_durable_ingest.py
  modified:
    - app/db/repo/inbound_events.py
    - app/routes/pump.py
    - scripts/migrate_operator_resolution_authority.py
    - tests/test_operator_resolution_migration.py
    - tests/test_queue_durability.py
    - tests/test_webhook_dedup_race.py

key-decisions:
  - "Retention ages inbound receipts by received_at, deletes only events whose ingest work is terminal, excludes pending/leased work, and relies on ON DELETE SET NULL to preserve job audit."
  - "The fence command installs only its singleton prerequisite table while holding ACCESS EXCLUSIVE on the legacy writer table; the complete additive schema remains a later gate."
  - "Wrong-run or unauthorized durable replies are canonical bounded no-ops, while a valid first delivery owns the AWAITING_REPLY to RECEIVED CAS before orchestration."
  - "Operator-resolution writes reopened only for verified live revision dad22b3f0fdd76813a0a934f7f3bba930ba7ca36 after repeated zero-ambiguity authority, schema, health, and closed-fence postflight."

patterns-established:
  - "Cutover prerequisite: install and close the writer fence under the legacy table lock before accepting any historical inventory."
  - "Deployment evidence: bind database mutation authority to an exact live revision, deployment identifier, replaced prior instance, and repeated postflight."

requirements-completed: [QUEUE-04]

coverage:
  - id: D1
    description: "The authenticated pump executes a bounded 30-day purge that removes only old terminal inbound envelopes and preserves open work plus terminal job audit."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_durable_ingest.py and tests/test_pump_route.py retention gate: 20 passed"
        status: pass
      - kind: integration
        ref: "GitHub CI run 29555992843"
        status: pass
    human_judgment: false
  - id: D2
    description: "An accepted event/job survives a zero-worker response boundary and later drain, while Svix-event and RFC Message-ID dedup remain separate exact contracts."
    requirement: QUEUE-04
    verification:
      - kind: integration
        ref: "GitHub concurrency-proof run 29555992838: 43/43 real-Postgres proofs"
        status: pass
      - kind: integration
        ref: "No-dotenv full suite: 1012 passed, 76 skipped"
        status: pass
    human_judgment: false
  - id: D3
    description: "The legacy writer stayed fenced from accepted inventory through additive migration and exact Render activation, then reopened only after repeated clean postflight."
    requirement: QUEUE-04
    verification:
      - kind: manual_procedural
        ref: "Render deployment dep-d9crb68k1i2s73bsg4t0 LIVE on service srv-d8tjkl77f7vs73f6ebu0 for exact revision dad22b3f0fdd76813a0a934f7f3bba930ba7ca36"
        status: pass
      - kind: manual_procedural
        ref: "Final inventory 0/0/0; authority affected/ambiguous/winnerless/multiple/unclassified 0/0/0/0/0; schema and public health in sync"
        status: pass
      - kind: manual_procedural
        ref: "Transactional reopen recorded writer_fence=open and deployed_revision=dad22b3f0fdd76813a0a934f7f3bba930ba7ca36"
        status: pass
    human_judgment: false
  - id: D4
    description: "The final code revision passes hermetic CI, evaluation, live migration, type, lint, and real-Postgres concurrency gates."
    requirement: QUEUE-04
    verification:
      - kind: integration
        ref: "GitHub CI 29555992843, eval 29555992868, deploy-migrate 29555992877: success"
        status: pass
      - kind: other
        ref: "mypy 155 files; ruff; git diff --check"
        status: pass
    human_judgment: false

duration: 53min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 10: Durable Ingest Evidence and Live Cutover Summary

**Pump-driven terminal retention, crash-safe post-200 recovery, exact two-layer dedup, and a fail-closed live writer cutover activated on a proven Render revision.**

## Performance

- **Duration:** 53 min
- **Started:** 2026-07-17T04:08:42Z
- **Completed:** 2026-07-17T05:01:07Z
- **Tasks:** 3
- **Files modified:** 21 including this summary

## Accomplishments

- Added an invoked 30-day retention executor that deletes only bounded batches of old events with terminal ingest work, excludes pending/leased work, and leaves job history intact.
- Proved that webhook acceptance commits the event/job before any payroll work, a later drain completes the owed run after process-local wake state is discarded, and Svix/RFC dedup stay separate.
- Closed the live legacy-writer fence before accepting inventory, applied the additive schema without reset, migrated authority with zero ambiguity, and kept the fence closed through exact revision activation.
- Verified Render deployment `dep-d9crb68k1i2s73bsg4t0` is Live for `dad22b3f0fdd76813a0a934f7f3bba930ba7ca36`, with prior deployments replaced, then repeated clean database/health postflight before reopening writes.
- Closed the final CI regressions: hermetic suite 1,012 passed/76 skipped and the real-Postgres concurrency workflow passed all 43 proofs.

## Task Commits

Each task and repair was committed atomically:

1. **Task 1 RED: retention execution proofs** - `bd475ef` (test)
2. **Task 1 GREEN: bounded terminal retention** - `0ce75c4` (feat)
3. **Task 2: post-200 recovery and two-layer dedup** - `c20bcfa` (test)
4. **Task 2 repair: typed local durability seams** - `a535c9d` (fix)
5. **Plan gate repair: phase-wide mypy gaps** - `9ce31ff` (fix)
6. **Task 3 repair: install fence table before cutover** - `09b6868` (fix)
7. **Task 3 repair: CI and real-Postgres proof alignment** - `23782e7` (fix)
8. **Task 3 repair: provenance and canonical no-op proof** - `dad22b3` (fix)

## Files Created/Modified

- `app/db/repo/inbound_events.py` - Implements bounded terminal-only purge using the declared `received_at` age column.
- `app/routes/pump.py` - Invokes retention after bounded drain without expanding the response or operations surface.
- `scripts/migrate_operator_resolution_authority.py` - Installs the fence prerequisite under lock, performs fail-closed authority checks, and gates exact-revision reopen.
- `tests/test_durable_ingest.py` - Pins retention bounds, post-200 durability, later drain, and persisted event/job evidence.
- `tests/test_webhook_dedup_race.py` - Extends separate Svix and RFC dedup evidence at the real-Postgres boundary.
- `tests/test_operator_resolution_migration.py` - Pins lock/table/function/trigger/closed-row ordering and rollback silence.
- `tests/test_queue_durability.py` - Aligns real reply association with canonical bounded no-op and first-delivery CAS contracts.
- `tests/test_demo_fixtures.py` - Keeps imported TestClient lifespan tests hermetic without relying on a developer `.env`.
- Supporting test modules - Close strict typing gaps exposed by the phase-wide bare mypy gate.

## Decisions Made

- Retention is payload lifecycle, not job-history lifecycle: only the inbound envelope expires; terminal job audit remains.
- Historical authority is never inferred. The accepted inventory contained zero unresolved, single-generation, and ambiguous runs, so no row-order judgment was needed.
- The writer fence prerequisite is the only schema object installed before accepted inventory. Full additive bootstrap remained behind explicit approval and never used `--reset`.
- The exact code revision for reopening was the proven Render revision `dad22b3f0fdd76813a0a934f7f3bba930ba7ca36`. The later summary-only commit does not change runtime code and is not a replacement activation claim.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Installed the missing fence prerequisite before inventory**
- **Found during:** Task 3 live fence close
- **Issue:** The close command referenced the singleton fence table before additive bootstrap, but did not create it; the first live command exited fail-closed.
- **Fix:** Under the existing ACCESS EXCLUSIVE lock, create only the exact singleton fence table before function/trigger installation and close-row mutation. Added ordering and rollback tests.
- **Files modified:** `scripts/migrate_operator_resolution_authority.py`, `tests/test_operator_resolution_migration.py`
- **Verification:** 49 migration/schema tests passed; the retried live close and immediate check both reported closed.
- **Committed in:** `09b6868`

**2. [Rule 1 - Bug] Used the declared inbound-event age column**
- **Found during:** Task 3 real-Postgres CI proof
- **Issue:** Retention queried `created_at`, but `inbound_events` declares `received_at`, causing the live pump to return 503.
- **Fix:** Query/order by `received_at` and pin the exact column in the retention test.
- **Files modified:** `app/db/repo/inbound_events.py`, `tests/test_durable_ingest.py`
- **Verification:** Retention/pump gate passed 20 tests; real-Postgres pump proofs passed.
- **Committed in:** `23782e7`

**3. [Rule 3 - Blocking] Made imported demo lifespan tests independent of local dotenv state**
- **Found during:** Task 3 hermetic CI gate
- **Issue:** An imported `_demo_client` started application lifespan without the source module's autouse fixture, so CI lacked the required settings stub.
- **Fix:** Added a local autouse fixture that clears settings and supplies only a mock database URL.
- **Files modified:** `tests/test_demo_fixtures.py`
- **Verification:** Five rollback cases passed from a no-dotenv working directory; final hermetic CI passed.
- **Committed in:** `23782e7`

**4. [Rule 1 - Bug] Aligned live reply proofs with the locked durable contract**
- **Found during:** Task 3 real-Postgres CI proof
- **Issue:** Wrong-run tests expected a terminal result instead of the bounded no-op contract, and the valid first-delivery control seeded `RECEIVED` rather than `AWAITING_REPLY`.
- **Fix:** Assert canonical `unknown:unclassified` OK/no-op and seed the valid control at the state owned by the first-delivery CAS.
- **Files modified:** `tests/test_queue_durability.py`
- **Verification:** All 43 real-Postgres concurrency proofs passed.
- **Committed in:** `23782e7`, `dad22b3`

**5. [Rule 3 - Blocking] Closed phase-wide strict typing and provenance gates**
- **Found during:** plan-level verification and hermetic CI
- **Issue:** Existing test doubles exposed by the new paths failed bare mypy, and one cutover rationale used forbidden phase provenance in a source comment.
- **Fix:** Typed the affected local seams and rewrote the comment in current-schema terms.
- **Files modified:** affected test seams and `scripts/migrate_operator_resolution_authority.py`
- **Verification:** Bare mypy passed 155 files; provenance guard passed 5 tests; Ruff and diff checks passed.
- **Committed in:** `a535c9d`, `9ce31ff`, `dad22b3`

---

**Total deviations:** 5 auto-fixed (3 Rule 1 bugs, 2 Rule 3 blocking issues)
**Impact on plan:** All repairs were necessary to make the planned retention, deployment fence, and proof contracts executable. No new dependency, endpoint, queue metric, manual recovery control, Phase 20 send behavior, or Phase 21 ops surface was added.

## Issues Encountered

- The initial live fence close exited safely because its prerequisite table was absent. No inventory or schema mutation was accepted until the narrow repair passed tests and the fence was confirmed closed.
- Render identity verification paused until authorized deployment evidence was available. Writes remained fenced while waiting.
- Two CI repair cycles were required: the first closed the live schema/test mismatches; the second closed comment provenance and canonical bounded-no-op assertions.
- The unchanged Starlette/httpx deprecation warning remains present.

## Live Cutover Evidence

- **Accepted preflight inventory:** unresolved `0`, single-generation `0`, ambiguous `0`.
- **Authority migration/postflight:** affected `0`, ambiguous `0`, winnerless `0`, multiple-winner `0`, unclassified-generation `0`.
- **Schema before deployment:** `in_sync`; fence: `closed`.
- **Render service/deployment:** `srv-d8tjkl77f7vs73f6ebu0` / `dep-d9crb68k1i2s73bsg4t0`.
- **Exact activated revision:** `dad22b3f0fdd76813a0a934f7f3bba930ba7ca36`; previous `23782e7` and `09b6868` entries are historical/rollback entries.
- **GitHub exact-SHA gates:** CI `29555992843`, concurrency `29555992838`, eval `29555992868`, deploy-migrate `29555992877` all succeeded.
- **Repeated postflight:** inventory `0/0/0`; authority `0/0/0/0/0`; local schema `in_sync`; public readiness `ready`; public schema `in_sync`; fence `closed` immediately before reopen.
- **Reopen:** transactional command reported `writer_fence=open` and recorded deployed revision `dad22b3f0fdd76813a0a934f7f3bba930ba7ca36`.

## Verification

- No-dotenv full suite: 1,012 passed, 76 skipped, 1 unchanged deprecation warning.
- GitHub real-Postgres concurrency proof: 43/43 passed.
- Focused operator migration/schema gate: 49 passed.
- Retention/pump gate: 20 passed.
- Resume-reply unit gate: 10 passed.
- Comment provenance guard: 5 passed.
- Bare mypy: 155 files passed.
- Ruff: passed.
- `git diff --check`: passed.

## User Setup Required

None. Live database and Render cutover authorization were supplied and the ordered cutover completed.

## Next Phase Readiness

- Phase 19 implementation and live activation evidence are complete; authoritative phase completion remains controlled by the phase verifier.
- Phase 20 can build send idempotency on the durable producer/handler substrate without reopening Phase 19 compatibility paths.
- Phase 21 can consume the passing real-Postgres proof registration and add mutation/red-run packaging plus the operations view.

## Known Stubs

None introduced.

## Self-Check: PASSED

- All listed task/repair commits exist in history.
- The retention, cutover script, proof tests, and this summary exist.
- Hermetic, live-Postgres, schema, deployment, health, lint, type, provenance, and diff checks are green.
- The exact-revision reopen completed only after every required repeated postflight gate passed.

---
*Phase: 19-webhook-cutover-durable-ingest*
*Completed: 2026-07-16*
