---
phase: 20-exactly-once-send
plan: "01"
subsystem: database
tags: [postgres, outbound-email, immutable-snapshot, idempotency, tdd]

# Dependency graph
requires:
  - phase: 18-failure-policy-sweep-deletion
    provides: "durable retry and fenced settlement conventions"
  - phase: 19-webhook-cutover-durable-ingest
    provides: "identifier-only durable queue conventions"
provides:
  - "Append-only provider-ready outbound snapshots, ordered attachment bytes, and bounded delivery-attempt evidence"
  - "Read-or-reserve repository APIs that return a stored envelope byte-identically on a same-slot retry"
  - "Explicit, owner-scoped provider, review, and attachment projections with matching in-memory fake APIs"
affects: [20-02, 20-03, gateway, delivery-review, durable-send-handler]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Freeze provider-visible envelope and ordered attachment bytes in append-only tables before provider work"
    - "Read-or-reserve locks a logical outbound slot and ignores retry caller content on conflict"
    - "Expose raw attachment bytes only through an owner-scoped record reader; review projections omit provider diagnostics"

key-files:
  created: []
  modified:
    - app/db/schema.sql
    - app/db/repo/emails.py
    - app/db/repo/__init__.py
    - tests/conftest.py
    - tests/test_send_idempotency.py
    - tests/test_delivery.py

key-decisions:
  - "The immutable snapshot repeats the RFC Message-ID alongside the email audit row, so provider replay can build from one frozen record."
  - "The previous outbound conflict update now does nothing and returns the existing audit row; send-state changes remain separate from payload reservation."
  - "Attempt evidence is limited to CHECK-backed state/category values and intentionally has no provider body or exception-text column."

patterns-established:
  - "D-12/D-13 reservation: caller-owned transaction -> lock/read logical slot -> insert email, snapshot, and ordered bytes once -> replay the persisted record"
  - "Immutable-evidence enforcement: deployed-schema triggers reject every UPDATE or DELETE on snapshot, attachment, and attempt rows"

requirements-completed: [SEND-01, SEND-02]

coverage:
  - id: D1
    description: "Immutable outbound envelope, ordered byte attachment, and bounded delivery-attempt storage are installed with deployed-schema append-only enforcement."
    requirement: "SEND-01"
    verification:
      - kind: unit
        ref: "tests/test_send_idempotency.py#test_outbound_snapshot_schema_declares_append_only_evidence"
        status: pass
      - kind: integration
        ref: "tests/test_send_idempotency.py#test_outbound_snapshot_evidence_rejects_direct_mutation"
        status: unknown
    human_judgment: false
  - id: D2
    description: "A same-slot retry receives the original Message-ID, envelope, headers, and attachment bytes while review and attachment reads remain owner-scoped."
    requirement: "SEND-02"
    verification:
      - kind: unit
        ref: "tests/test_send_idempotency.py#test_fake_reservation_reuses_the_original_provider_snapshot"
        status: pass
      - kind: unit
        ref: "tests/test_send_idempotency.py#test_reservation_sql_locks_then_never_applies_conflicting_caller_content"
        status: pass
    human_judgment: false

duration: 10min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 01: Immutable Outbound Reservation Summary

**Outbound send slots now persist one append-only provider-ready envelope and ordered attachment bytes, with read-or-reserve APIs that return the original record unchanged on retry.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-07-17T18:17:36Z
- **Completed:** 2026-07-17T18:26:49Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- Added immutable snapshot, attachment, and PII-safe delivery-attempt tables plus deployed-schema triggers rejecting direct mutation.
- Replaced outbound caller-content conflict updates with read-or-reserve APIs that lock a logical slot and preserve the original Message-ID, headers, body, recipient, and exact attachment bytes.
- Added explicit owner-scoped provider/review/attachment readers and mirrored all APIs in `InMemoryRepo` with pairing coverage.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add append-only outbound snapshot, attachment, and attempt storage** - `aa4289a` (feat)
2. **Task 2: Replace outbound conflict overwrite with read-or-reserve repository APIs** - `4f28cb9` (feat)
3. **Post-plan correction: Remove prohibited planning provenance from source comments and docstrings** - `526d90a` (fix)

## Files Created/Modified

- `app/db/schema.sql` - Adds immutable snapshot, ordered attachment, and bounded attempt persistence with append-only triggers.
- `app/db/repo/emails.py` - Adds D-12/D-13 read-or-reserve and owner-scoped loading APIs; removes payload overwrites on logical-slot conflicts.
- `app/db/repo/__init__.py` - Re-exports the new repository surface.
- `tests/conftest.py` - Mirrors reservation and scoped readers in the fake repository and wires them through the pairing tuple.
- `tests/test_send_idempotency.py` - Proves schema shape, immutable retry behavior, SQL locking, and guarded live mutation rejection.
- `tests/test_delivery.py` - Pins the legacy audit helper's conflict path against caller-content overwrite.

## Decisions Made

- Persisted the RFC Message-ID in the immutable snapshot as well as the logical email audit row so a future provider call can rehydrate one frozen record.
- Kept `email_messages.send_state` mutable through its existing state-transition API; snapshot, bytes, and attempt evidence are separate append-only records.
- Made delivery-review projections expose bounded snapshot facts and attachment metadata, while raw bytes require an explicitly owner-scoped attachment lookup.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Source-comment provenance guard rejected planning labels**
- **Found during:** Post-wave integration gate
- **Issue:** New comments and docstrings cited planning decision and phase labels, which the repository guard prohibits in production and test source.
- **Fix:** Replaced only the labels with plain-language explanations of immutable reservation, byte preservation, and bounded review behavior.
- **Files modified:** `app/db/repo/emails.py`, `app/db/schema.sql`, `tests/conftest.py`, `tests/test_delivery.py`, `tests/test_send_idempotency.py`
- **Verification:** Provenance guard, focused Plan 01 tests, Ruff, and mypy all passed.
- **Committed in:** `526d90a`

**Total deviations:** 1 auto-fixed (1 Rule 3 blocking issue). **Impact:** Commentary-only correction; no runtime or schema behavior changed.

## Issues Encountered

- The focused live-Postgres mutation-rejection proof is correctly guarded and skipped because `DATABASE_URL` and `ALLOW_DB_RESET=1` are not configured. The hermetic schema guard and all non-DB reservation proofs passed.
- The sandbox initially blocked uv's existing package cache and the git index; the required checks and commits completed after the approved scoped access was granted.

## User Setup Required

None - no external service configuration required. A configured test Postgres database is only needed to exercise the already-guarded direct-SQL trigger proof locally.

## Next Phase Readiness

- Plan 20-02 can route the gateway and durable send handler through `reserve_outbound_snapshot` / `load_outbound_snapshot` without regenerating provider-visible content.
- The remaining Phase 20 plans must append attempt facts and connect provider, queue, and delivery-review behavior; no provider call changed in this plan.

## Verification

- `uv run pytest tests/test_send_idempotency.py tests/test_delivery.py -q` — 22 passed, 3 skipped.
- `uv run pytest tests/test_comment_provenance_guard.py -q` — 5 passed.
- `uv run pytest tests/test_fake_repo_pairing.py -q` — 10 passed, 1 unchanged Starlette/httpx deprecation warning.
- `uv run mypy app/db/repo/emails.py tests/conftest.py` — passed.
- `uv run ruff check app/db/repo/emails.py app/db/repo/__init__.py tests/conftest.py tests/test_send_idempotency.py tests/test_delivery.py` — passed.
- `git diff --check` — passed.

## Self-Check: PASSED

- The summary and all six listed files exist.
- Task commits `aa4289a`, `4f28cb9`, and correction `526d90a` are present in history.
- Focused tests, fake-pairing guard, lint, mypy, and diff checks passed; the guarded live-Postgres test is explicitly reported as unavailable evidence.

---
*Phase: 20-exactly-once-send*
*Completed: 2026-07-17*
