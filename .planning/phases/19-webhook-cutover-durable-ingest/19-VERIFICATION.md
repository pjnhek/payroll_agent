---
phase: 19-webhook-cutover-durable-ingest
verified: 2026-07-17T05:54:36Z
status: human_needed
score: 39/40 must-haves verified
behavior_unverified: 1
overrides_applied: 0
behavior_unverified_items:
  - truth: "Same-Svix redelivery yields one event, one ingest job, and one run across a real Postgres boundary when available."
    test: "Run tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run against an isolated seeded Postgres database with DATABASE_URL configured."
    expected: "Two concurrent deliveries of one Svix ID return accepted plus duplicate with one stable event ID, and the database contains exactly one inbound event, one INGEST job, and one payroll run after delayed ingest."
    why_human: "The test is present but only integration-marked. The current real-Postgres workflow selects two named integration files plus queueproof-marked tests, so this module is not collected; local verification has no DATABASE_URL and the test skips."
human_verification:
  - test: "Execute the existing concurrent same-Svix test against an isolated seeded Postgres database, or wire an isolated equivalent into the real-Postgres CI gate and observe it pass without skips."
    expected: "Exactly one durable event, one INGEST job, and one run survive the concurrent transport-redelivery race."
    why_human: "Current green CI does not execute this specific guarded real-Postgres test, and production data must not be used as a destructive test target."
---

# Phase 19: Webhook Cutover & Durable Ingest Verification Report

**Phase Goal:** An accepted inbound email is durable the instant the webhook returns 200 — no client email is ever lost to a restart, a crash, or a sleeping instance again.
**Verified:** 2026-07-17T05:54:36Z
**Status:** human_needed
**Re-verification:** No — initial canonical verification

## Goal Achievement

### Observable Truths

The four ROADMAP success criteria are preserved verbatim at the top of this merged list. Plan truths that restated them were deduplicated; plan-specific storage, settlement, authority, UI, retention, and deployment contracts remain additive.

| # | Truth | Status | Evidence |
|---:|---|---|---|
| 1 | All 8 historical background-task producers are migrated; none schedule payroll work in process memory. | ✓ VERIFIED | `tests/test_background_task_cutover.py` inventories exactly 8 producer functions, 9 former consumers, retired wrappers, and synthetic regressions. Named verifier run passed. Source scan found no production `BackgroundTasks`/`.add_task()` payroll producer. |
| 2 | Redelivering one Svix event does not create a second job or run after body fetch moves to delayed ingest. | ✓ VERIFIED | `test_duplicate_redelivery_returns_stable_event_receipt_and_creates_no_second_job` passed. `insert_or_get_inbound_event` arbitrates on unique external identity, and only the insert winner enqueues `ingest:{event_id}`; one owed INGEST job can create at most the one downstream run exercised by the drain proof. |
| 3 | Losing the process immediately after 200 does not lose the accepted email; later durable execution completes it. | ✓ VERIFIED | `test_accepted_receipt_survives_lost_wake_and_later_shared_drain` passed: wake state is cleared after 200, committed INGEST remains pending, later shared drain creates the run and completes pipeline work. |
| 4 | An unauthorized clarification reply remains rejected after delayed ingest. | ✓ VERIFIED | `test_sender_mismatch_never_enqueues_or_invokes_orchestration` passed. `app/ingest.py`, `pipeline_glue.py`, and `resume_reply.py` check same-run ownership and `reply_sender_ok` before enqueue/conversion/orchestration. |
| 5 | Live-safe schema stores a bounded verified envelope before a payroll run exists. | ✓ VERIFIED | `inbound_events` and nullable `jobs.event_id` exist in fresh/additive DDL and exact introspection; webhook accepts event-only work. |
| 6 | Operator generations store one winner, supersession, and per-override remember intent. | ✓ VERIFIED | Exact schema/index constraints plus repository model and schema tests; no historical timestamp/UUID ordering is used. |
| 7 | Read-only legacy inventory fails closed on ambiguous unresolved generations. | ✓ VERIFIED | `scripts/check_operator_resolution_inventory.py` executes grouped aggregate-only SELECT logic and returns nonzero on ambiguity; output is limited to three counts. |
| 8 | Unambiguous sole legacy generations migrate to one winner with `remember=false`. | ✓ VERIFIED | Migration performs in-transaction ambiguity recheck before updates; postflight tests cover winnerless/multiple/malformed states. |
| 9 | A persistent writer fence blocks legacy resolution writes until verified activation. | ✓ VERIFIED | Trigger/fence schema, ACCESS EXCLUSIVE protocol, fail-closed reopen logic, and named fence/schema tests passed. Exact current deploy-migrate workflow is green. |
| 10 | First valid operator generation committed under the run lock becomes authority. | ✓ VERIFIED | `test_commit_operator_resolution_locks_before_selecting_first_authority` passed; repository executes `SELECT ... FOR UPDATE` before winner lookup/insertion. |
| 11 | Later valid generations remain immutable superseded history and are safe no-ops. | ✓ VERIFIED | `test_commit_operator_resolution_retains_later_generation_as_superseded` passed; handler returns bounded OK before payroll or alias side effects. |
| 12 | Only the winner's remember intent can become alias-candidate state. | ✓ VERIFIED | `test_prepare_operator_resolution_keeps_loser_noop_and_projects_only_winner_remember` passed. |
| 13 | Delayed ingest preserves DATA-02 outcome ordering and atomically creates downstream owed jobs. | ✓ VERIFIED | `app/ingest.py::_ingest_email` owns one caller transaction over email classification, run/reply persistence, and identifier-only enqueue; rollback tests exist and current CI is green. |
| 14 | Svix transport identity and RFC Message-ID identity remain independent dedup layers. | ✓ VERIFIED | Transport key lives on `inbound_events`; RFC identity remains `email_messages.message_id` after provider fetch. Hermetic duplicate/RFC tests pass. |
| 15 | INGEST is exact across enum, SQL, model, claim, dispatch, and handler. | ✓ VERIFIED | `JobKind.INGEST`, exact CHECK/introspection, event-only model, late-bound dispatch, and `handle_ingest` are wired; drift tests are green. |
| 16 | Open INGEST jobs carry event ID only; run-associated kinds retain bounded contexts. | ✓ VERIFIED | `Job` has identifier fields only; enqueue validation and claim bijection tests pin the contract. |
| 17 | No request could enqueue INGEST before null-run settlement was complete. | ✓ VERIFIED | Current final architecture exposes INGEST production only from the durable webhook receipt after kind-aware settlement landed; source guard rejects alternate HTTP producers. |
| 18 | Null-run INGEST success/retry/dead/terminal/fencing settle without payroll mutation. | ✓ VERIFIED | Kind-aware branch precedes run requirement; named fake/coordinator tests and current 43-test real-Postgres queueproof gate pass. |
| 19 | Expired final-attempt INGEST leases are reaped without payroll writes. | ✓ VERIFIED | Named verifier run `test_null_run_ingest_expired_final_attempt_is_reaped_without_payroll_write` passed. |
| 20 | Fake repository/facade settlement seams preserve ingest parity and lease fencing. | ✓ VERIFIED | Pairing guard is non-vacuous and current exact CI is green. |
| 21 | Webhook returns 200 only after authenticated event and INGEST job commit atomically. | ✓ VERIFIED | Direct code trace confirms transaction exit precedes return/wake; acceptance and rollback named tests passed. |
| 22 | Blocking receipt persistence is awaited through `run_in_threadpool`. | ✓ VERIFIED | `app/routes/webhook.py:156` awaits `_persist_verified_receipt_sync`; blocked-database responsiveness test is present and exact CI is green. |
| 23 | Request path does not fetch provider body, route sender, create run, or expose run/job IDs. | ✓ VERIFIED | Route performs bounded stream, signature check, minimal envelope validation, and event receipt only; no provider parse/fetch or payroll orchestration call appears in the route. |
| 24 | Both demo triggers atomically commit email, run, and pipeline job. | ✓ VERIFIED | Named composer and fixture transaction-order tests passed. |
| 25 | Successful demos wake after commit and redirect to exact run detail. | ✓ VERIFIED | Both route implementations call wake after transaction exit and return `/runs/{run_id}`. |
| 26 | Demo enqueue failure rolls back and shows fixed bounded retry copy. | ✓ VERIFIED | Route failure branches expose only allowlisted query flags; actual templates are `index.html` and `runs_list.html`, with tests covering rollback/copy. |
| 27 | Real/simulated replies commit persisted reply context and RESUME_REPLY job atomically. | ✓ VERIFIED | `persist_and_enqueue_reply` is caller-transaction owned; duplicate context ensures the same identifier-only job. |
| 28 | Every valid operator generation gets a durable job, while only the winner advances payroll/aliases. | ✓ VERIFIED | `/resolve` commits generation plus generation-specific job in one transaction; winner-only handler ordering is test-pinned. |
| 29 | List/detail expose one bounded secondary open-job label without changing payroll status. | ✓ VERIFIED | Repository projection emits fixed labels; templates render separate badges and keep `RunStatus` primary. |
| 30 | Durability copy is visible only while pending/leased work exists. | ✓ VERIFIED | Named queued-detail test passed; template conditional uses bounded `has_open_job` projection. |
| 31 | Polling runs every 2 seconds for at most 120 seconds and never performs recovery. | ✓ VERIFIED | `MAX_ATTEMPTS=60`, 2000 ms interval, read-only status fetch, and no enqueue/retrigger mutation path. |
| 32 | Superseded/demo notices are fixed, bounded, PII-safe, and subordinate. | ✓ VERIFIED | Query values become booleans; templates select fixed copy rather than rendering query text. |
| 33 | Pump enforces bounded 30-day terminal-only inbound-event retention. | ✓ VERIFIED | `purge_terminal_inbound_events` requires age ≥30 and batch ≤100, excludes open work, preserves job audit through `SET NULL`; named retention and pump tests passed. |
| 34 | Same-Svix redelivery yields one event, one ingest job, and one run across real Postgres when available. | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | The exact guarded test exists but is not collected by current DB-backed CI; local environment lacks DATABASE_URL and the named test skips. Code and hermetic behavior are present, but this specific real-Postgres race has no observed passing execution. |
| 35 | Writer fence remains closed through schema, authority migration, activation, and final postflight. | ✓ VERIFIED | Migration/reopen tests passed; cutover checkpoint recorded closed fence through exact activation and verified reopen. |
| 36 | Live activation requires unambiguous inventory, sole-winner migration, exact revision, and schema/authority/fence assertions. | ✓ VERIFIED | Reopen CLI validates canonical 40-character SHA and fail-closed schema/authority catalogs. Current exact revision `93a643615bf5705474c36ae50b110cf52a3c5ebe` has green CI, concurrency-proof, eval, and deploy-migrate; orchestrator confirmed matching Render deployment and all three health endpoints. |
| 37 | Nine stale wrapper consumers use durable handler/job/value seams. | ✓ VERIFIED | Permanent exact consumer inventory passes; retired names are absent from those consumers. |
| 38 | Request/read route tests fail if payroll execution occurs inline while asserting owed jobs. | ✓ VERIFIED | Migrated tests install fail-if-called seams at HTTP boundaries and assert persisted identifier-only work. |
| 39 | Compatibility wrappers were deleted after consumers migrated. | ✓ VERIFIED | Retired definitions/references are absent; the cutover inventory checks all prerequisite consumers. |
| 40 | A non-vacuous architecture guard rejects reintroduced producer or wrapper symbols. | ✓ VERIFIED | Both synthetic mutation tests and exact real inventory pass. |

**Score:** 39/40 truths verified (1 present, behavior-unverified)

## Required Artifacts

| Artifact group | Expected | Status | Details |
|---|---|---|---|
| `app/db/schema.sql`, `schema_introspect.py`, bootstrap | Durable receipt, INGEST, authority, fence, exact live catalog | ✓ VERIFIED | Exist, substantive, schema/introspection tests green; review fixes make malformed/multiple CHECK catalogs fail closed. |
| `app/db/repo/inbound_events.py`, `jobs.py`, `job_settlement.py`, `operator_resume_resolutions.py` | Durable receipt/dedup, exact identifier jobs, transport settlement, serialized authority | ✓ VERIFIED | Imported through repo facade and exercised by routes/handlers/tests. |
| `app/ingest.py`, queue dispatch/handlers | Delayed DATA-02 execution and kind-aware durable consumers | ✓ VERIFIED | Late-bound dispatch and exact enum/handler equality are test-pinned. |
| `app/routes/webhook.py`, `demo.py`, `runs.py`, `pipeline_glue.py`, `pump.py` | All producers durable, sender guard preserved, retention invoked | ✓ VERIFIED | Direct call/transaction traces and named behavioral tests pass. |
| `app/templates/index.html`, `runs_list.html`, `run_detail.html`, `style.css` | Bounded demo/queue notices and polling | ✓ VERIFIED | Plan 19-07 named nonexistent `dashboard.html`; execution correctly substituted the actual composer owner `index.html`, documented in 19-07-SUMMARY, with route/template tests. |
| Migration/inventory scripts | Fail-closed legacy cutover and reopen | ✓ VERIFIED | Exact bounded outputs, lock/recheck protocol, and full-SHA reopen checks are present and tested. |
| Phase test surface | Behavioral, architecture, and real-DB proofs | ⚠️ PARTIAL | Hermetic and queueproof coverage is strong; concurrent same-Svix real-DB test is present but not currently executed by DB-backed CI. |

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| webhook route | inbound event repository + INGEST enqueue | awaited threadpool helper and caller transaction | ✓ WIRED | Event insert and enqueue share `conn`; wake follows transaction exit. |
| INGEST handler | delayed ingest service | event ID only | ✓ WIRED | Handler validates no mixed context and calls `process_inbound_event(event_id)`. |
| delayed ingest | email/run/reply repositories + jobs | one DATA-02 transaction | ✓ WIRED | Both downstream enqueue sites receive the caller connection. |
| demo routes | email/run/job repositories | `_write_demo_run(..., conn=conn)` | ✓ WIRED | Both routes transact and wake post-commit. |
| reply producers/handler | persisted email + sender authorization | same-run check then `reply_sender_ok` | ✓ WIRED | Authorization precedes content conversion and orchestration. |
| operator route/handler | commit-serialized resolution repository | run lock, immutable job context, winner-only preparation | ✓ WIRED | Worker order cannot establish authority. |
| pump | retention repository | bounded maintenance after drain | ✓ WIRED | Maintenance response remains excluded from public pump fields. |
| templates/status JSON | bounded job projection | fixed labels/boolean only | ✓ WIRED | No raw identifiers, attempts, timestamps, payloads, or diagnostics cross the browser boundary. |
| architecture guard | historical producers/consumers | AST exact inventory + synthetic mutations | ✓ WIRED | Guard is nonempty and demonstrably bites. |

The automated key-link query reported four syntax-only false negatives: multiline SQL/calls did not match single-line regexes, and two `from:` fields included `::symbol` suffixes that the helper expects to be plain file paths. Direct source inspection above confirms all four links are wired.

## Data-Flow Trace (Level 4)

| Artifact | Data | Source | Produces real data | Status |
|---|---|---|---|---|
| `runs_list.html` / `run_detail.html` | queue label, badge class, open-work boolean | bounded `jobs` SQL projection through runs route | Yes — real pending/leased rows reduced to allowlist | ✓ FLOWING |
| `index.html` / `runs_list.html` | demo failure notice | fixed route query-flag projection | Yes — boolean derived from exact `=1`, no raw query text | ✓ FLOWING |
| webhook receipt | status + stable event UUID | committed event insert/conflict result | Yes — DB identity, not hardcoded | ✓ FLOWING |

## Behavioral Spot-Checks

| Behavior | Command/result | Status |
|---|---|---|
| Exact 8-producer durable cutover | named AST inventory test: `1 passed` | ✓ PASS |
| Stable duplicate receipt / no second job | named durable-ingest test: `1 passed` | ✓ PASS |
| Lost wake/process memory followed by later drain | named durable-ingest test: `1 passed` | ✓ PASS |
| Unauthorized sender no enqueue/orchestration | named durable-ingest test: `1 passed` | ✓ PASS |
| Operator lock/supersession/winner-only remember | three named tests: `3 passed` | ✓ PASS |
| Null-run reaper, both demos, queue UI, retention, fence/schema | eight named tests: `7 passed, 1 skipped`; only guarded real-thread operator test skipped locally | ✓ PASS for seven runnable checks |
| Concurrent same-Svix real Postgres | exact named test skipped locally; not collected by current DB-backed CI | ? HUMAN REQUIRED |
| Current exact GitHub revision | CI `29557925404`, concurrency-proof `29557925347`, eval `29557925408`, deploy-migrate `29557925445`: all success on `93a6436...` | ✓ PASS |

Current CI reports `1028 passed, 76 skipped`; current real-Postgres concurrency workflow reports `5 passed` plus `43 passed` with skip-fail guards. Inspection of workflow selection confirms those green runs do not collect `test_webhook_dedup_race.py`.

## Probe Execution

Step 7c: **SKIPPED — no Phase 19 probe scripts are declared and no conventional `scripts/**/tests/probe-*.sh` files exist.**

## Requirements Coverage

| Requirement | Source plans | Description | Status | Evidence |
|---|---|---|---|---|
| QUEUE-04 | 19-01 through 19-12 | All eight historical process-memory payroll producers are durably migrated | ✓ SATISFIED | Exact non-vacuous architecture inventory passes; every final producer commits owed jobs with state before post-commit wake. |

No additional Phase 19 requirement is orphaned in `REQUIREMENTS.md`.

## Anti-Patterns Found

| File | Pattern | Severity | Impact |
|---|---|---|---|
| Phase scope | `TBD` / `FIXME` / `XXX` | None | No debt-marker blocker found across the 56-file persisted Phase 19 review scope. |
| Several files/tests | Word `placeholder` | ℹ️ Info | Matches are intentional missing-preview UI labels, SQL parameter terminology, or test fixture tokens; none are implementation stubs or user-visible fake data paths. |

## Disconfirmation Pass

1. **Partially met requirement sought:** the real-Postgres same-Svix race is implemented but lacks an observed execution in current DB-backed CI; this remains the sole human item.
2. **Misleading passing test sought:** green `concurrency-proof` cannot be used as evidence for `test_webhook_dedup_race.py`, because its workflow selects two named integration files and then only `queueproof` tests; the target is only `integration`-marked.
3. **Uncovered error path sought:** receipt enqueue/commit rollback, malformed envelope, sender mismatch, null-run final lease, migration ambiguity, malformed authority postflight, and multiple schema CHECK catalogs all have explicit tests. No additional uncovered goal-blocking error path was found.

## Human Verification Required

### 1. Concurrent same-Svix race on isolated Postgres

**Test:** Run `tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run` against an isolated, seeded Postgres database, or wire an isolated equivalent into the real-Postgres CI gate.

**Expected:** Two barrier-released deliveries of the same Svix event produce one accepted and one duplicate response with the same event UUID, exactly one event row, exactly one INGEST job, and exactly one run after delayed ingest.

**Why human:** Local verification has no database/reset authority. Current CI and concurrency-proof runs are green but do not collect this module, so they cannot certify this race.

## Gaps Summary

No implementation blocker was found. The phase goal and all four ROADMAP success criteria have passing hermetic behavioral evidence, all key links are wired, current exact-revision CI/deploy health is green, and the complete process-memory producer surface is structurally absent.

One plan-specific stronger proof remains behavior-unverified: concurrent same-Svix dedup across real Postgres. Per the canonical verifier decision tree, that nonempty human-verification item makes the overall status `human_needed`, not `passed` and not `gaps_found`.

Later Phase 20/21 items do not cover or erase this item: Phase 20 owns exactly-once outbound send, and Phase 21 owns proof packaging/ops visibility. No current implementation gap was deferred to those phases.

---

_Verified: 2026-07-17T05:54:36Z_
_Verifier: the agent (gsd-verifier)_
