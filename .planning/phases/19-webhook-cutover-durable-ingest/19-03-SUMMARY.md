---
phase: 19-webhook-cutover-durable-ingest
plan: 03
subsystem: durable-ingest
tags: [postgres, webhook, idempotency, transactional-queue, tdd]

requires:
  - phase: 19-01
    provides: "Durable inbound_events schema, stable external transport identity, and jobs.event_id storage"
  - phase: 18-09
    provides: "Identifier-only RUN_PIPELINE and RESUME_REPLY queue producers"
provides:
  - "Bounded inbound-event insert/load repository with stable duplicate identity"
  - "Worker-facing delayed provider fetch and preserved five-outcome business ingest"
  - "Atomic identifier-only RUN_PIPELINE and RESUME_REPLY creation with two-layer deduplication"
affects: [19-04, 19-05, 19-06, webhook-cutover, durable-reply-resume]

tech-stack:
  added: []
  patterns:
    - "two-layer dedup: transport delivery identity and RFC message identity remain independent"
    - "owed-work transaction: domain rows and downstream identifier-only jobs commit together"
    - "bounded worker result: normal business outcomes collapse to PipelineResult OK without payload projection"

key-files:
  created:
    - app/db/repo/inbound_events.py
    - app/ingest.py
    - tests/test_durable_ingest.py
  modified:
    - app/db/repo/__init__.py

key-decisions:
  - "The public process_inbound_event boundary returns only a bounded PipelineResult; its internal IngestOutcome enum records the five normal business classifications without exposing message data."
  - "New-run work uses run_pipeline:{run_id}:0 and reply work uses resume_reply:{run_id}:{email_id}, so every dedup key is derived only from persisted identifiers."
  - "A duplicate RFC reply rehydrates the stored inbound row and revalidates unconsumed state, same-run ownership, awaiting-reply state, and sender ownership before ensuring the same resume job."

patterns-established:
  - "Inbound-event repository reads expose only id and payload; external transport identity is used only for conflict arbitration."
  - "Provider/database failures propagate to queue infrastructure settlement, while duplicate, late-reply, unknown-sender, authorized-reply, and new-run classifications are successful transport outcomes."

requirements-completed: [QUEUE-04]

coverage:
  - id: D1
    description: "Transport receipt insertion returns one stable internal event UUID across duplicate external delivery keys and loads only the bounded persisted envelope."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_durable_ingest.py -k 'event_repository or stable_event or conflict'"
        status: pass
      - kind: other
        ref: "uv run mypy app/ingest.py app/db/repo/inbound_events.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Delayed ingest fetches from the persisted event, preserves all five business outcomes, and atomically creates identifier-only downstream work."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_durable_ingest.py#test_delayed_processing_fetches_only_from_persisted_event"
        status: pass
      - kind: unit
        ref: "tests/test_durable_ingest.py#test_downstream_enqueue_failure_rolls_back_domain_rows"
        status: pass
      - kind: integration
        ref: "tests/test_webhook.py and tests/test_reply_redelivery.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "RFC duplicate replies remain independent of transport dedup and can enqueue only after same-run, state, consumption, and sender authorization checks."
    requirement: QUEUE-04
    verification:
      - kind: unit
        ref: "tests/test_durable_ingest.py#test_authorized_reply_and_redelivery_ensure_one_identifier_only_resume_job"
        status: pass
      - kind: unit
        ref: "tests/test_durable_ingest.py#test_sender_mismatch_never_enqueues_or_invokes_orchestration"
        status: pass
      - kind: other
        ref: "uv run --offline --no-sync pytest -q (944 passed, 70 skipped)"
        status: pass
    human_judgment: false

duration: 13min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 03: Transactional Delayed Ingest Summary

**Persisted transport receipts now drive a delayed five-outcome ingest service that keeps Svix and RFC deduplication independent and commits every owed pipeline or reply job beside its domain state.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-07-17T00:28:00Z
- **Completed:** 2026-07-17T00:40:35Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Added caller-transaction-aware receipt insertion with exact duplicate-loser lookup, stable internal UUIDs, parameterized SQL, JSONB adaptation, and a bounded `id`/`payload` read projection.
- Added delayed event processing that performs the provider fetch and body cleaning only after loading a persisted receipt, then enters the preserved duplicate, reply-candidate, late-reply, unknown-sender, or new-run transaction.
- Added atomic `RUN_PIPELINE` creation for a new run and `RESUME_REPLY` creation for an authorized first-delivery or duplicate reply, carrying persisted identifiers only.
- Preserved sender authorization and same-run ownership before reply enqueue; sender-mismatched, consumed, advanced, late, and unknown-sender inputs remain bounded no-ops against payroll execution.
- Added executable rollback, two-layer dedup, repository conflict, delayed-fetch, reply-redelivery, and spoof-guard proofs.

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Freeze delayed-ingest and two-layer-dedup behavior** - `6fe1be6` (test)
2. **Task 2 GREEN: Build the bounded inbound-event repository** - `7f36ba4` (feat)
3. **Task 3 GREEN: Move DATA-02 into the delayed ingest service** - `b19f227` (feat)
4. **Regression fix: Remove a prohibited test provenance label** - `b8f167a` (fix)

## Files Created/Modified

- `app/db/repo/inbound_events.py` - Idempotent event insert/conflict lookup and bounded envelope loading.
- `app/db/repo/__init__.py` - Public receipt repository exports.
- `app/ingest.py` - Delayed provider fetch, five-outcome transaction, sender authorization, and atomic downstream enqueue.
- `tests/test_durable_ingest.py` - Repository, delayed-fetch, two-layer dedup, rollback, authorization, and identifier-only job contracts.

## Decisions Made

- `process_inbound_event` returns `PipelineResult(outcome=OK)` for every normal business classification; provider, missing-event, corrupt-payload, and database failures propagate to the queue infrastructure policy rather than being mistaken for settled business outcomes.
- A new run's initial durable cause is keyed as `run_pipeline:{run_id}:0`; a reply's durable cause is keyed as `resume_reply:{run_id}:{email_id}`. No body, mapping, sender, or target status crosses into the job row.
- Duplicate replies are evaluated from the already-cleaned persisted inbound row. They never reconstruct authority from the retried provider body.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed a test provenance label rejected by the permanent source gate**
- **Found during:** Overall regression verification
- **Issue:** The new test module docstring named the project phase, which violated the repository's source-provenance policy even though the behavior tests passed.
- **Fix:** Reworded the docstring to describe the delayed-ingest contract without historical ticket provenance.
- **Files modified:** `tests/test_durable_ingest.py`
- **Verification:** The provenance suite passed and the full offline suite completed with 944 passed and 70 guarded skips.
- **Committed in:** `b8f167a`

---

**Total deviations:** 1 auto-fixed bug.
**Impact on plan:** The adjustment was editorial only and restored the repository-wide permanent gate without changing coverage or behavior.

## Issues Encountered

- The full offline suite emits the existing Starlette/httpx deprecation warning.
- Guarded live-database tests remained unavailable and were reported as skips; this plan's transaction rollback and SQL-shape evidence is hermetic, so no live-Postgres concurrency result is claimed.

## User Setup Required

None - no external service configuration required.

## Verification

- Focused event/service/outcome suites: 20 passed.
- Receipt repository gate: 2 passed.
- Ruff: passed for all modified production and test files.
- Mypy: passed for `app/ingest.py` and `app/db/repo/inbound_events.py`.
- Comment-provenance gate: 5 passed.
- Full offline suite: 944 passed, 70 guarded skips.
- `git diff --check`: passed.

## Next Phase Readiness

- Plan 19-04 can add the exact `INGEST` enum/model/SQL/claim/dispatch contract and forward `process_inbound_event`'s bounded result from its queue handler.
- Plan 19-05 can then add null-run ingest settlement and complete fake-repository pairing before any HTTP producer exists.
- Plan 19-06 remains the only owner of the public webhook receipt cutover.

---
*Phase: 19-webhook-cutover-durable-ingest*
*Completed: 2026-07-16*

## Self-Check: PASSED

All four modified files and this summary exist; task commits `6fe1be6`, `7f36ba4`,
`b19f227`, and `b8f167a` are present; focused, Ruff, mypy, provenance, full-suite,
and diff-check gates are green. No generated artifact remains untracked.
