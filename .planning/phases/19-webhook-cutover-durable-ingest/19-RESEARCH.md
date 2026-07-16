# Phase 19: Webhook Cutover & Durable Ingest - Research

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

## Implementation Decisions

### Webhook acceptance and response contract

- **D-01: Distinguish a new event from a transport redelivery without exposing queue
  internals.** A newly persisted event returns `200` with `status=accepted` and its
  durable event identifier. Re-delivery of the same Svix event returns `200` with
  `status=duplicate` and that same event identifier.
- **D-02: Return neither a run ID nor a queue job ID.** A run does not exist at the
  acceptance boundary, and `jobs.id` is an internal transport implementation detail.
- **D-03: Durability failure is a bounded `503`.** If the event-plus-ingest-job
  transaction does not commit, return `503 Service Unavailable` so Resend retries. Never
  expose database errors or other internal diagnostics in the response.
- **D-04: Validate only the transport envelope before acceptance.** After signature
  verification, require valid JSON and the minimal Resend identifier needed for the
  worker's body fetch. Do not fetch the body, route the sender, create a payroll run, or
  perform business processing before returning `200`.
- **D-05: Preserve the approved two-layer dedup contract.** Svix `event_id` deduplicates
  webhook delivery at ingress; `email_messages.message_id` continues to deduplicate the
  fetched RFC message inside the moved ingest transaction. Neither layer replaces the
  other.
- **D-06: Keep the durable inbox bounded.** Carry forward the approved 256 KiB request
  body cap and 30-day `inbound_events` retention policy.

### Recruiter demo navigation

- **D-07: Both demo triggers land on the new run's detail page.** The composer and curated
  fixture routes still create the inbound email, run, and `run_pipeline` job atomically,
  then redirect directly to `/runs/{run_id}`.
- **D-08: Follow a queued demo for up to two minutes.** Run detail polls every two seconds
  and reloads when the run reaches a meaningful next state. The polling cap is 120
  seconds, not the current 60 seconds.
- **D-09: A polling timeout never causes automatic recovery.** When the two-minute window
  expires, stop polling and remain on the refreshable run-detail page. Do not enqueue a
  second job or automatically invoke Retrigger; the existing durable job remains owed.
- **D-10: Demo enqueue failure is visible but bounded.** If the route cannot atomically
  persist the email, run, and job, redirect back to the demo/runs surface with a simple
  retry message. Do not silently redirect and do not show internal error details.

### Competing operator resolutions

- **D-11: The first valid committed resolution generation wins deterministically.** If
  multiple complete operator mappings are committed while the run remains
  `needs_operator`, the earliest committed immutable generation is the sole authority for
  payroll. Worker scheduling order must not decide which mapping wins.
- **D-12: Later valid generations remain immutable audit records.** A losing generation
  and its durable job history are preserved and identified as superseded, but the job is
  an intentional no-op against payroll state.
- **D-13: Alias learning follows the payroll authority.** Store each generation's
  `remember` intent with that generation. Only the winning generation may project alias
  candidates for the approval-gate learning path; losing generations may not mutate
  aliases or candidate state.
- **D-14: A losing submitter gets bounded feedback.** Redirect to run detail with a notice
  equivalent to: “An earlier resolution was already accepted. This submission was
  recorded but not applied.” The notice contains no submitted names, mappings, or other
  PII.

### Queued-state presentation

- **D-15: Queue state is secondary presentation, never a payroll status.** Keep the
  primary `payroll_runs.status` unchanged and derive a separate indicator from
  authoritative open-job state. Do not introduce a `queued` `RunStatus` or interpret
  `jobs.state` as a business outcome.
- **D-16: Show the secondary indicator on both runs list and run detail.** This gives the
  operator immediate confirmation without pulling the Phase 21 operations page forward.
- **D-17: Use bounded state-aware labels.** Show `Queued` for immediately available
  pending work, `Retry queued` for delayed pending work, and `Running` for leased work.
  Do not put job IDs, attempt counts, or raw diagnostics in these badges.
- **D-18: Explain durability briefly on run detail.** While an open job exists, show:
  “This action is durably saved; you can safely leave this page.” Hide the copy and queue
  badge when no pending/leased job remains; existing success or safe failure presentation
  then takes over.

### Locked implementation constraints carried forward

- **D-19: Move the five-outcome ingest-decision transaction; do not redesign it.** The
  existing duplicate / reply-candidate / late-reply / unknown-sender / new-run unit is
  DATA-02 evidence and must retain its atomicity and ordering in the ingest handler.
- **D-20: Preserve sender authorization at every durable resume seam.** The
  `reply_sender_ok` comparison remains mandatory for both first delivery and redelivery;
  moving work into a worker cannot weaken it.
- **D-21: Enqueues are co-tenants of the transactions that owe them.** Event plus ingest
  job, demo email/run plus pipeline job, reply classification plus resume job, and
  operator authority plus operator-resume job must commit atomically.
- **D-22: Jobs carry identifiers, never business payloads or next statuses.** Rehydrate
  reply input from the persisted email row and operator authority from the immutable
  resolution generation. Preserve invariant J-1 and the exact handler/enum/SQL drift
  guards.
- **D-23: Complete the producer cutover.** No route may retain a
  `background_tasks.add_task(...)` pipeline producer after this phase; route signatures,
  helpers, tests, fakes, and comments must reflect the durable-only path.

### the agent's Discretion

- Exact JSON field spelling and serialization for the bounded webhook response, provided
  D-01 through D-04 hold and the durable event identifier is stable across redelivery.
- The schema/constraint/query mechanism that makes D-11 first-commit authority
  deterministic and marks later generations superseded, provided concurrency cannot make
  worker timing authoritative.
- The implementation of bounded redirect notices (query flag or equivalent), their exact
  styling, and the secondary badge styling.
- The exact shared polling helper or JavaScript refactor used to apply the two-minute
  behavior without duplicating list/detail logic.
- SQL composition and repository function boundaries for the raw inbox and queue
  projections, provided caller-owned transaction, fencing, safe-diagnostic, and fake-repo
  conventions are preserved.

### Deferred Ideas (OUT OF SCOPE)

## Deferred Ideas

- Provider-side exactly-once confirmation send and its retry-window proof — Phase 20.
- Queue-health/dead-letter operations page, alarms, job-level diagnostics, and manual job
  retry controls — Phase 21.

### Reviewed Todos (not folded)

- `.planning/todos/pending/260623-02-frontend-progressive-enhancement.md` — frontend
  progressive enhancement remains post-demo polish and does not clarify durable ingest.
- `.planning/todos/pending/260623-03-paystub-ytd-v2.md` — paystub YTD columns are a separate
  payroll-document feature.
- `.planning/todos/pending/260623-04-eval-chart-restyle-v2.md` — eval-chart styling is a
  separate evidence-presentation task.

</user_constraints>

## Research Metadata

**Researched:** 2026-07-16  
**Domain:** transactional inbox/outbox-style ingest, Postgres job queue, FastAPI request boundary, deterministic concurrent authority  
**Overall confidence:** HIGH for repository findings; MEDIUM for external API/framework details verified through primary-source web fallback  
**Research mode:** codebase-first with official-document fallback; Context7 was selected by the research seam but unavailable in this runtime. [VERIFIED: `.research-plan-input.json` routing output and available-tool inventory]

<phase_requirements>
## Phase Requirements

| ID | Requirement | Research support |
|---|---|---|
| QUEUE-04 | Every producer is migrated—all 8 `BackgroundTasks` route-signature producers across `webhook.py`, `demo.py` (x2), and `runs.py` (x5, including one hiding inside `runs_list()` page render). No pipeline work is ever again scheduled into process memory. | Producer ledger, transaction boundaries, negative source guard, durable handler/settlement design, and validation matrix below. [VERIFIED: `.planning/REQUIREMENTS.md:39-41`; current source inventory] |

</phase_requirements>

## Summary

Phase 19 should be implemented as one coordinated durability migration, not as a route-by-route substitution. The webhook must persist a signed, minimally validated transport event and identifier-only `ingest` job in one transaction before `200`; the worker must then perform the current Resend fetch and move the existing five-outcome DATA-02 transaction without changing its ordering or semantics. Every downstream action that becomes owed during that transaction must be enqueued in that same transaction. [VERIFIED: `19-CONTEXT.md` D-01–D-06, D-19–D-23; `app/routes/webhook.py`]

The highest-risk hidden seam is queue settlement: the current settlement and final-attempt reaper assume every job has a `run_id`. A correct `ingest` handler can still strand or fence every null-run job unless Phase 19 adds a transport-only settlement branch for success, retry/dead-letter, and final expired lease. The other high-risk seam is competing operator resolutions: the current worker race decides which generation advances payroll and the route projects alias candidates before authority is known. Authority must instead be selected while submissions serialize on the existing run row, and only the authoritative generation may project remembered aliases. [VERIFIED: `app/db/repo/jobs.py`; `app/queue/worker.py`; `app/routes/runs.py`; `app/db/repo/operator_resume_resolutions.py`]

No new dependency is needed. The existing FastAPI/Starlette, psycopg, Pydantic, Resend, queue, pump, wake, and server-rendered UI stack is sufficient. [VERIFIED: `pyproject.toml`; current imports]

**Primary recommendation:** Treat Phase 19 as a transaction-boundary migration: land the event/schema/job/settlement contract first, move DATA-02 intact, then cut all producers over and close with concurrency plus negative-source proofs. [VERIFIED: repository seam analysis]

## Architectural Responsibility Map

| Capability | Primary tier | Secondary tier | Rationale |
|---|---|---|---|
| Webhook authentication and bounded receipt | FastAPI route / gateway | Postgres event repository | The route owns transport validation; the database owns durable acceptance. [VERIFIED: existing layering and D-01–D-06] |
| Delayed body fetch and ingest classification | Queue ingest handler | Existing ingest repository/service | The handler owns retries; the existing transaction owns the five outcomes. [VERIFIED: D-19 and handler conventions] |
| Owed-work creation | Caller-owned Postgres transaction | Queue wake | State and job commit together; wake only accelerates already-durable work. [VERIFIED: D-21 and Phase 16–18 pattern] |
| Reply/operator continuation | Identifier-only queue handlers | Durable email/resolution repositories | Handlers rehydrate authoritative inputs and apply CAS/no-op semantics. [VERIFIED: D-20, D-22] |
| Operator authority | Run-row locked repository transaction | Operator handler | Commit serialization selects authority; workers only consume it. [VERIFIED/CITED: D-11; PostgreSQL locking] |
| Queue presentation | Bounded run repository projection | Jinja templates/status JSON | Jobs remain transport state and UI receives only labels. [VERIFIED: D-15–D-18] |

## Standard Stack

### Core

| Library | Pinned version | Purpose in this phase | Why standard here |
|---|---:|---|---|
| FastAPI | 0.138.0 | Webhook/demo/run routes | Existing route framework; no migration needed. [VERIFIED: `pyproject.toml`] |
| Starlette (FastAPI dependency) | lock-resolved | `Request.stream()` and responses | Existing ASGI request primitive supports bounded streaming. [VERIFIED: `uv.lock`; CITED: Starlette requests docs] |
| psycopg | 3.3.4 | Caller-owned transactions, locks, queue/event SQL | Existing direct-Postgres durability substrate. [VERIFIED: `pyproject.toml`] |
| Pydantic | 2.13.4 | Minimal envelope and fetched-message validation | Existing typed validation boundary. [VERIFIED: `pyproject.toml`] |
| Resend | 2.32.2 | Svix verification and delayed body fetch | Existing provider integration; avoids custom crypto/API code. [VERIFIED: `pyproject.toml` and gateway source] |

### Supporting

| Library/tool | Version | Purpose | When to use |
|---|---:|---|---|
| Jinja2 | 3.1.6 | Queue badges, durability copy, bounded notices | Existing server-rendered list/detail views. [VERIFIED: `pyproject.toml`] |
| pytest | lock-resolved | Hermetic and guarded Postgres proofs | Every transaction/concurrency/negative-guard seam. [VERIFIED: `pyproject.toml`, `uv.lock`] |
| `hashlib` | Python 3.12 stdlib | Unsigned-fixture fallback event key | Only behind the existing fixture flag; never authentication. [VERIFIED: Python stdlib and design constraint] |

### Alternatives Considered

| Instead of | Could use | Tradeoff |
|---|---|---|
| Existing Postgres queue | Redis/Celery | Adds service/dependency/runtime state and weakens the locked Postgres checkpoint architecture. [VERIFIED: project constraints] |
| Raw envelope table | Put payload on `jobs` | Violates identifiers-only jobs and couples retention to transport execution history. [VERIFIED: D-22] |
| Run-row authority lock | Worker-first-wins or timestamp ordering | Lets scheduling or transaction-start time determine money-moving authority. [VERIFIED/CITED: D-11 and PostgreSQL docs] |

**Installation:** none. Do not modify project dependencies for Phase 19. [VERIFIED: package audit]

## Project Constraints from AGENTS.md

- Use Python 3.12 through `uv`; do not introduce pip, Poetry, venv activation, or a hand-maintained `requirements.txt`. [VERIFIED: `AGENTS.md` tooling rule]
- Keep deterministic name resolution and process-vs-clarify decisions in code; the LLM may extract or suggest but must not decide money-moving outcomes. [VERIFIED: `AGENTS.md` project constraints]
- Preserve the one human approval gate, Postgres as the state/checkpoint store, plain-Python orchestration, Pydantic structured-output validation, and config-driven model routing. [VERIFIED: `AGENTS.md` project constraints]
- Follow caller-owned transactions, parameterized SQL, fake-repository parity, and existing architecture patterns. [VERIFIED: `AGENTS.md`; Phase 16–18 code and tests]

## Current-State Responsibility Map

| Surface | Current behavior | Phase 19 responsibility |
|---|---|---|
| `app/routes/webhook.py` | Verifies signature, fetches the Resend body and performs DATA-02 synchronously in a thread, then schedules run/reply work with `BackgroundTasks`. [VERIFIED: source] | Bound raw body, verify before parsing, minimally validate envelope, atomically persist event+ingest job, wake after commit, and return bounded receipt. Move fetch and DATA-02 into handler. |
| `app/routes/demo.py` | Two demo producers create email/run in separate transactions and schedule memory tasks; one redirects to list. [VERIFIED: source] | Make email+run+job one transaction, wake post-commit, redirect both to detail, bound failure notice. |
| `app/routes/runs.py` | Resolution and simulated reply paths schedule memory work; `approve` still has an unused `BackgroundTasks` signature. Retrigger is already durable and list sweep was removed earlier. [VERIFIED: source; Phase 16/18 artifacts] | Enqueue reply/operator work transactionally, remove all route signatures/imports, make operator authority commit-ordered, preserve retrigger/read-only list. |
| `app/routes/pipeline_glue.py` | Rehydrates persisted replies and revalidates sender, but routes into `_bg` wrappers. [VERIFIED: source] | Keep rehydration and sender guard; delete durable-path dependence on all `_bg` wrappers. |
| `app/models/job.py`, `app/db/repo/jobs.py`, `app/queue/dispatch.py` | Exact three-kind contract: `run_pipeline`, `resume_reply`, `operator_resume`; jobs have no event identifier. [VERIFIED: source/schema/drift tests] | Add `ingest` and `event_id` as one enum/model/SQL/dispatch/fake/introspection change. |
| queue settlement/reaper | Run-associated result settlement rejects or fences null-`run_id` work. [VERIFIED: `settle_pipeline_job`, `settle_infrastructure_failure`, `reap_expired_final_attempt`] | Add explicit ingest transport settlement; never write a payroll status for ingest failure. |
| operator generations | Immutable generation and child overrides exist, but no authority/supersession/remember contract exists. Alias candidates are projected by the route. [VERIFIED: schema and repository] | Persist authority, supersession, and per-mapping remember intent; enqueue every committed valid generation; only winner mutates payroll/alias-candidate state. |
| run list/detail/status | Business status is projected; current polling is about 60 seconds; no bounded open-job projection exists. [VERIFIED: repositories/templates/routes] | Add safe secondary queue label, exact durability copy, and 2-second/120-second no-recovery polling. |

### Producer ledger interpretation

The roadmap's “all 8” is a historical completeness requirement, not the count of producers still active after Phases 16 and 18. Retrigger has already moved to the queue and the runs-list sweep producer has already been deleted. Phase 19 must finish every remaining producer and add a structural guard that prevents `BackgroundTasks`, route parameters, or `.add_task()` pipeline producers from returning in `app/routes` and `app/pipeline`. [VERIFIED: `.planning/REQUIREMENTS.md`; `.planning/research/PITFALLS.md`; current source; Phase 16/18 summaries]

## Recommended Architecture

```text
Resend/Svix request
  -> bounded stream (<=256 KiB)
  -> signature verification over exact bytes
  -> minimal transport-envelope validation
  -> one transaction: inbound_events + ingest job
  -> commit -> wake -> 200 event receipt

ingest worker
  -> load exact inbound_event by jobs.event_id
  -> Resend body fetch / canonical fixture parse
  -> one DATA-02 transaction (unchanged five outcomes)
       -> email/run rows
       -> downstream identifier-only job when owed
  -> transport-only fenced settlement of ingest job
```

[VERIFIED: locked context plus existing queue/pump interfaces]

### Recommended project structure

```text
app/
├── db/repo/inbound_events.py                 # durable receipt and retention
├── db/repo/operator_resume_resolutions.py    # authority/supersession/remember
├── queue/handlers/ingest.py                  # delayed fetch + DATA-02 consumer
├── queue/worker.py                           # kind-aware settlement/reaping
├── routes/webhook.py                         # bounded receipt only
├── routes/demo.py                            # atomic demo producers
├── routes/runs.py                            # durable reply/operator producers
└── templates/                                # bounded secondary queue state
```

[VERIFIED: current repository structure; exact file split remains planner discretion]

### 1. Durable event receipt

Use an `inbound_events` table with an internal UUID primary key, unique external transport key, raw verified envelope as JSONB, and `received_at`. For signed Resend traffic, the external key is the Svix event ID. In explicitly enabled unsigned-fixture mode only, derive a stable `sha256:<hex>` key from the exact bounded raw bytes so fixture retries remain deterministic without pretending that digest is provider authentication. [VERIFIED: current signature/fixture modes; D-01, D-05; repository design precedent]

The route should consume `request.stream()` and abort once accumulated bytes exceed 256 KiB; Starlette documents that streaming yields chunks without first buffering the entire body. Verify the signature over those exact bytes before JSON parsing. Do not call `gateway.parse_inbound`, access Resend, route a sender, or create a run before the persistence commit. [CITED: https://www.starlette.io/requests/; VERIFIED: D-04 and current gateway behavior]

Recommended bounded response shape:

```json
{"status":"accepted","event_id":"<internal-uuid>"}
```

or, for the same transport key:

```json
{"status":"duplicate","event_id":"<same-internal-uuid>"}
```

This meets D-01–D-03 while keeping `jobs.id`, `run_id`, provider diagnostics, and database diagnostics private. [VERIFIED: context]

### 2. Two independent deduplication layers

Svix delivery dedup belongs at `inbound_events.external_event_id UNIQUE`; RFC `Message-ID` dedup remains at `email_messages.message_id` inside the moved five-outcome worker transaction. An ingest job retry may repeat the body fetch and business ingest even though the webhook delivery itself was accepted once, which is exactly why both constraints are required. [VERIFIED: D-05; existing `insert_email_or_get_existing` flow; research architecture]

On a repeated Svix key, select and return the existing internal event ID and do not create another ingest job. On a repeated RFC message, preserve the current duplicate outcome; if that stored message still represents an unconsumed valid clarification reply, transactionally ensure the same deduplicated `resume_reply` job is owed rather than relying on process memory. [VERIFIED: current `_duplicate_redelivery_sync`; D-19–D-21]

### 3. Schema and job-contract change

Recommended schema shape:

```sql
CREATE TABLE inbound_events (
    id UUID PRIMARY KEY,
    external_event_id TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_inbound_events_received_at ON inbound_events(received_at);

ALTER TABLE jobs ADD COLUMN event_id UUID NULL
    REFERENCES inbound_events(id) ON DELETE SET NULL;
```

Widen the `jobs.kind` check to include `ingest`; add an ingest context check that requires `event_id` and forbids run/email/operator identifiers while pending or leased, but permits a terminal ingest audit row to retain `event_id=NULL` after retention. Update the Python enum/model, enqueue validation, SQL live checks, dispatch equality, schema introspection, fake methods, pairing inventories, and drift tests atomically. [VERIFIED: current exact-kind and context-check pattern; Cited support for `SET NULL`: https://www.postgresql.org/docs/15/ddl-constraints.html]

Retention should delete only inbox events older than 30 days whose ingest job is terminal. `ON DELETE SET NULL` preserves job history while allowing payload deletion; immediate checks mean the context constraint must explicitly allow a null event only for terminal ingest jobs. A provider retry after the retention horizon may be accepted as new; that is the consequence of the locked bounded-retention horizon and should be documented, not hidden. [CITED: https://www.postgresql.org/docs/15/sql-set-constraints.html; VERIFIED: D-06 and research architecture]

### 4. Null-run ingest settlement is mandatory

Do not route `ingest` through the existing run-associated settlement path unchanged. Introduce a kind-aware transport settlement path with these outcomes: [VERIFIED: current settlement/reaper code]

| Condition | Required ingest settlement | Payroll mutation |
|---|---|---|
| Handler returns OK/no-op | Fenced `mark_done` | None |
| Fetch/DB infrastructure failure and attempts remain | Fenced reschedule with safe class/code only | None |
| Retry cap reached | Fenced dead-letter | None |
| Final-attempt lease expires | Reaper marks null-run ingest job dead | None |

The run-associated policy for the existing three kinds must remain unchanged. Add non-vacuous tests for all rows above; especially assert an expired final-attempt ingest lease with `run_id IS NULL` is dead-lettered rather than fenced forever. [VERIFIED: Phase 18 failure policy and identified code seam]

### 5. Move DATA-02, do not redesign it

Extract the existing `_parse_and_ingest_sync` business transaction into a repository/service callable used by `app/queue/handlers/ingest.py`. Preserve outcome ordering: duplicate, reply candidate, late reply, unknown sender, new run. Preserve sender lookup, message cleaning, RFC-message insert/dedup, thread classification, and run creation semantics. The only architectural change inside that transaction is that owed downstream work is now an identifier-only job committed beside the domain rows. [VERIFIED: `app/routes/webhook.py`; D-19, D-21, D-22]

The handler loads the exact persisted event using `job.event_id`; then `gateway.parse_inbound(event.payload)` performs the delayed Resend fetch or fixture validation. Do not copy fetched bodies into `jobs.payload`, log them, or project them to UI. [VERIFIED: current gateway behavior; invariant J-1; PII boundary]

### 6. Durable reply resume must revalidate authorization and actual state

The reply handler must load the exact persisted email and claimed run, assert the email belongs to that run/thread, and call `reply_sender_ok` before converting content or invoking the orchestrator. Unauthorized or cross-run input is an intentional OK/no-op that leaves the run awaiting reply and emits no sender PII. [VERIFIED: Phase 18 18-14 binding; D-20]

Do not infer first delivery solely from `job.attempts`: a worker may die before claiming payroll state, so a later attempt can still see `AWAITING_REPLY`. Branch on authoritative stored status under CAS/lock: first delivery claims `AWAITING_REPLY -> RECEIVED`; already-prepared work may continue from `RECEIVED`; reclaim from `EXTRACTING` uses the established rewind policy; any advanced/incompatible state is a successful no-op. [VERIFIED: current handler and Phase 18 retry semantics]

### 7. First-commit operator authority

Serialize resolution submissions with `SELECT ... FOR UPDATE` on the target `payroll_runs` row. PostgreSQL holds that row lock until transaction end and a competing locker waits, so the first valid transaction to obtain/commit the authority can be observed deterministically by the next submitter. Do not use `created_at`, UUID order, sequence order, or worker order as commit order; `current_timestamp` is transaction-start time. [CITED: https://www.postgresql.org/docs/15/explicit-locking.html and https://www.postgresql.org/docs/15/functions-datetime.html]

Recommended extension:

- Add per-generation authority/supersession fields, enforce at most one authoritative generation per run with a partial unique index, and keep every later complete generation immutable. [VERIFIED: D-11, D-12]
- Add `remember BOOLEAN NOT NULL DEFAULT false` to each persisted override row. [VERIFIED: D-13; current form field]
- Under the run lock, validate the whole generation; if no authority exists, mark it authoritative, otherwise mark it superseded by the winner. Enqueue an `operator_resume` job for every valid committed generation with `operator_resume:{run_id}:{resolution_id}`. [VERIFIED: D-11, D-12, D-21 and STATE open item]
- Return a bounded loser flag for redirect messaging; never echo names or mappings. [VERIFIED: D-14]
- Move winner-only alias-candidate projection out of the route. A transactionally safe `prepare_operator_resume` repository operation should verify authority, project only the winner's `remember=true` candidates, and claim/restore the actual run state before orchestration. A superseded generation returns intentional OK/no-op before any payroll or alias mutation. [VERIFIED: D-13; current alias projection race]

### 8. Demo producers

Both demo routes should use one caller-owned transaction for inbound email insertion, run creation, and `run_pipeline` enqueue. Call `wake.wake()` only after successful commit. Redirect success to `/runs/{run_id}`; on transaction failure, roll back every row and redirect with one bounded retry notice. [VERIFIED: D-07, D-10, D-21; current route separation]

### 9. Secondary queue presentation

Derive one safe open-job projection per run: `Running` if any open job is leased, otherwise `Queued` if any pending job is due, otherwise `Retry queued` if pending work is delayed. Do not expose identifiers, attempts, timestamps, error strings, or job diagnostics. Add the projection to list, detail, and `/status` repository boundaries. [VERIFIED: D-15–D-17]

Poll every two seconds while either the payroll status is in-flight or an open-job projection exists. Stop after 60 polls (120 seconds) without enqueueing, retriggering, or changing state. Detail reloads on meaningful state change; the badge/copy hides when no open work remains. [VERIFIED: D-08, D-09, D-18; current template polling]

## Recommended File/Plan Decomposition

The planner should preserve atomic seams and order implementation so each wave leaves the enum/SQL/handler contract internally coherent. [VERIFIED: Phase 16–18 drift-guard practice]

1. **Schema and contract foundation:** `schema.sql`, `JobKind`, `Job`, enqueue SQL, event repository, operator authority fields, introspection, drift/fake tests.
2. **Transport handler and settlement:** ingest handler/dispatch, moved DATA-02 service, transport settlement/reaper, two-layer dedup tests.
3. **Producer cutover:** webhook receipt, demo transactions, durable reply/operator/simulated-reply producers, post-commit wake, delete `_bg` usage.
4. **Concurrency authority:** first-commit resolution path, loser audit/no-op, remember isolation, concurrent proof.
5. **Safe UI projection:** run list/detail/status queue projection, two-minute polling, bounded notices.
6. **Closeout guard:** AST/source negative guard, focused suite, full suite, guarded Postgres tests where environment allows.

Avoid splitting event schema from ingest settlement or operator authority from alias projection: those are correctness units, not optional polish. [VERIFIED: identified failure seams]

## What Not to Hand-Roll

- Do not invent signature cryptography; keep the existing Resend/Svix verification library over exact raw bytes. [VERIFIED: current gateway]
- Do not invent a second queue API; extend `enqueue_job(conn=...)`, dispatch, leasing, fencing, wake, and pump. [VERIFIED: Phase 16–18 architecture]
- Do not put business payloads or next statuses in `jobs`; rehydrate from `inbound_events`, `email_messages`, and immutable operator generations. [VERIFIED: J-1 and D-22]
- Do not replace the five-outcome ingest decision with a new state machine. [VERIFIED: D-19]
- Do not use timestamps or IDs as a commit-order proxy for operator authority. [CITED: PostgreSQL transaction timestamp behavior; VERIFIED: D-11]
- Do not build a Phase 21 queue-operations surface or Phase 20 send idempotency here. [VERIFIED: deferred scope]

## Code Examples

### Bounded request stream

```python
# Source: https://www.starlette.io/requests/
raw = bytearray()
async for chunk in request.stream():
    raw.extend(chunk)
    if len(raw) > MAX_INBOUND_BYTES:
        raise HTTPException(status_code=413, detail="request too large")
```

Verify the exact `bytes(raw)` only after the cap check, then parse JSON from the same bytes after authentication. [CITED: Starlette request-stream contract; VERIFIED: D-04, D-06]

### Transaction-serialized operator authority

```sql
-- Source: https://www.postgresql.org/docs/15/explicit-locking.html
SELECT id, status
FROM payroll_runs
WHERE id = %(run_id)s
FOR UPDATE;
```

Within the same transaction, insert the immutable generation, select or establish the one authority, classify later generations as superseded, and enqueue the generation-specific job. [VERIFIED: D-11, D-12, D-21]

### Retention-safe event reference

```sql
-- Source: https://www.postgresql.org/docs/15/ddl-constraints.html
event_id UUID REFERENCES inbound_events(id) ON DELETE SET NULL
```

Pair this with a context check that allows null only for terminal ingest jobs and a purge predicate that excludes open ingest work. [CITED: PostgreSQL FK/check behavior; VERIFIED: D-06]

## State of the Art

| Old approach in this checkout | Phase 19 approach | Impact |
|---|---|---|
| Request path fetches Resend body and performs business ingest before response. [VERIFIED: source] | Accept signed minimal envelope durably, fetch in retryable worker. | A post-200 process death cannot lose accepted input. [VERIFIED: phase goal] |
| `BackgroundTasks` carries continuation in process memory. [VERIFIED: source] | Postgres job is committed with the state that owes it. | Restart/sleep no longer erases owed work. [VERIFIED: QUEUE-04] |
| Worker/CAS race effectively selects operator generation. [VERIFIED: source] | Commit-serialized immutable authority; workers consume/no-op. | Money-moving mapping is deterministic before scheduling. [VERIFIED: D-11] |
| UI shows only business status while durable work may be open. [VERIFIED: templates] | Bounded secondary queue label plus durability copy. | Recruiter/operator gets safe feedback without a new payroll status. [VERIFIED: D-15–D-18] |

**Deprecated after this phase:** route `BackgroundTasks` parameters for pipeline work, `.add_task()` producers, and pipeline `_bg` wrappers. The closeout guard should make reintroduction a CI failure. [VERIFIED: D-23]

## Runtime State Inventory

| State class | Current/required state | Migration or preservation action |
|---|---|---|
| Postgres schema | Existing `jobs`, emails, runs, operator generations; no `inbound_events`/`jobs.event_id`; no authority/remember columns. [VERIFIED: `app/db/schema.sql`] | Apply live-safe additive DDL before deploying code; update inline checks and DO-block live checks together. No old inbound-event backfill is possible or required. |
| Existing jobs | Three kinds may be pending/leased/done/dead. [VERIFIED: schema] | Preserve rows and existing kind semantics; new nullable `event_id` must not invalidate them. |
| Existing operator generations | Runtime count is unknown because `DATABASE_URL` is unset in this research environment. [VERIFIED: environment probe] | Pre-deploy query counts per run. Single legacy generation may be explicitly migrated with `remember=false`; multiple legacy generations must not be ordered by timestamp—fail closed or require a fresh operator submission. Record the chosen deploy procedure in the plan. |
| Raw inbound payload | Currently not durably stored before fetch/ingest. [VERIFIED: webhook source] | Store only verified bounded envelope, retain 30 days, purge only when associated ingest work is terminal. |
| Service configuration/secrets | Existing Resend signing/fetch config, DB URL, pump auth, and unsigned-fixture switch are sufficient. [VERIFIED: settings/source] | No new secret is required. Keep unsigned fixtures explicitly gated. |
| External services | Supabase/Postgres, Resend/Svix, Render service/pump. [VERIFIED: project config/docs] | Deploy schema before app. Pre-warm/demo behavior remains operational, not a new code capability. |
| OS/build state | Python 3.12/uv project and Docker image. [VERIFIED: `.python-version`, Dockerfile, environment probe] | No dependency or OS package change; rebuild/redeploy after schema. |

## Environment Availability

- `uv 0.9.9` and Python `3.12.12` are available. The default uv cache is sandbox-restricted, but `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync ...` works. [VERIFIED: 2026-07-16 probe]
- `psql`, `pg_isready`, and Docker 28.4.0 are installed. `DATABASE_URL` is unset, so no live schema/runtime-data assertion was made. [VERIFIED: 2026-07-16 probe]
- Context7 tools were not available; official Starlette and PostgreSQL documentation was retrieved via web fallback and classified MEDIUM by the GSD confidence helper. [VERIFIED: research seam and helper output]

## Validation Architecture

### Framework and execution

Use pytest via `uv run`; preserve the current hermetic fake-repository style and guarded real-Postgres tests. Phase 18's recorded baseline is 899 passed and 69 skipped; this is upstream evidence, not a fresh Phase 19 run. [VERIFIED: `pyproject.toml`; `18-VERIFICATION.md`]

| Property | Value |
|---|---|
| Framework | pytest, lock-resolved through `uv.lock` [VERIFIED: project files] |
| Config | `[tool.pytest.ini_options]` in `pyproject.toml` [VERIFIED: project file] |
| Quick run | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q <focused files>` |
| Full suite | `UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q` |

When the sandbox restricts the default uv cache, use the task-specific cache override shown above. Do not bypass uv by calling `.venv/bin/python`. [VERIFIED: AGENTS tooling rule and environment probe]

### Wave 0 / test-first gaps

Create or extend focused tests before implementation for: event receipt transaction rollback, stable Svix redelivery ID, no body fetch before acceptance, null-run ingest settlement/reaper, first-commit operator authority, and the negative `BackgroundTasks` guard. Existing tests cover the prior behavior but do not encode those new seams. [VERIFIED: tests inventory and source inspection]

### Requirement-to-test matrix

| Behavior | Minimum proof | Suggested location |
|---|---|---|
| Acceptance durability | Transaction failure returns bounded 503 and leaves neither event nor job; success commits both before wake/200. | New `tests/test_durable_ingest.py`; guarded SQL companion |
| No request-path fetch | Slow/raising Resend fetch spy is never invoked by webhook route; response is event receipt only. | `tests/test_webhook_unblocked.py` / `test_durable_ingest.py` |
| Svix dedup | Same transport ID returns same internal event ID and exactly one ingest job. | Hermetic fake plus guarded Postgres unique-race test |
| RFC dedup | Retried ingest fetch creates one message/run and preserves five outcomes. | Extend webhook/dedup/reply-redelivery tests |
| Crash after 200 | Accept with zero workers, then later drain produces the owed outcome. | Guarded queueproof-style test; Phase 21 will own final CI registration/red-run evidence |
| Unauthorized reply | Exact same-run binding and sender revalidation occur before content conversion/orchestration. | Extend `test_resume_pipeline.py` and `test_reply_redelivery.py` |
| Null-run settlement | OK, retry, terminal, and final expired lease settle without payroll write. | Queue durability/reaper tests |
| Demo atomicity | Any insert/enqueue failure rolls back all; wake is post-commit; both redirect to detail. | Demo route tests |
| Operator authority | Real concurrent submitters yield one first-commit winner; loser row/job retained; loser handler no-op; only winner remember intent projects aliases. | `test_needs_operator.py` plus guarded real-thread DB test |
| Complete cutover | AST/source test rejects `BackgroundTasks` imports/parameters and `.add_task()` pipeline producers under route/pipeline surfaces. | New or existing architecture guard test |
| Safe queue UI | Exact three labels only; no IDs/attempts/diagnostics; copy visible only while open; polling stops at 120 seconds and causes no recovery. | `test_dashboard.py` plus template/static checks |
| Drift/fake parity | Enum, SQL CHECKs, handler map, model context, introspection, and fake inventories match exactly. | Existing drift/introspection/fake-pairing suites |

### Focused verification commands

```bash
UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_durable_ingest.py tests/test_webhook_unblocked.py tests/test_webhook.py
UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_queue_durability.py tests/test_queue_drain.py tests/test_resume_pipeline.py tests/test_needs_operator.py
UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q tests/test_job_kind_drift.py tests/test_schema_introspect.py tests/test_repo_jobs_sql.py tests/test_dashboard.py
UV_CACHE_DIR=/tmp/gsd-phase19-uv-cache uv run --offline --no-sync pytest -q
```

These are planning targets; `tests/test_durable_ingest.py` does not yet exist. Guarded live-DB tests must report skipped honestly when `DATABASE_URL`/reset authority is absent. [VERIFIED: current test/config conventions]

### Sampling rate

- **Per task commit:** focused tests for the touched transaction/route/handler seam. [VERIFIED: GSD validation practice]
- **Per wave merge:** all Phase 19 focused files plus drift/fake/schema tests. [VERIFIED: identified cross-file contract]
- **Phase gate:** full pytest suite green; guarded Postgres proofs either pass with configured DB or are reported as skipped without claiming live evidence. [VERIFIED: existing test policy]

### Wave 0 gaps

- [ ] `tests/test_durable_ingest.py` — durable receipt, delayed fetch, two-layer dedup, and crash-before-drain coverage for QUEUE-04.
- [ ] A null-run settlement/reaper case in the existing queue durability suite — prevents vacuous ingest handler success.
- [ ] A complete producer-cutover AST/source guard — prevents `BackgroundTasks` regression.
- [ ] A real-thread operator authority test, guarded if it needs Postgres — proves first-commit authority rather than sequential mock behavior.

## Security Domain

### ASVS-focused controls

| ASVS category | Applies | Standard control |
|---|---|---|
| V2 Authentication | Yes | Existing provider/Svix signature verification before parse/persist. [VERIFIED: source] |
| V3 Session Management | No new scope | No session/auth redesign in Phase 19. [VERIFIED: boundary] |
| V4 Access Control | Yes | Sender/business/run/employee ownership checks at durable seams. [VERIFIED: guards] |
| V5 Input Validation | Yes | Streaming cap, JSON/envelope allowlist, Pydantic, parameterized SQL. [VERIFIED/CITED] |
| V6 Cryptography | Yes | Provider library verification; no custom HMAC. [VERIFIED: gateway] |

- **V2 / service authentication:** Preserve Svix signature verification before parsing or persistence. Unsigned fixture acceptance stays behind the explicit development flag. [VERIFIED: current route/settings; D-04]
- **V4 / access control:** Preserve sender-to-business lookup, same-run reply ownership, and `reply_sender_ok` at every first/retry resume seam. Preserve employee-to-run/business mapping validation for operator overrides. [VERIFIED: current guards; D-20]
- **V5 / validation and encoding:** Enforce the 256 KiB streaming cap, JSON object/envelope allowlist, nonblank external identifier, Pydantic validation of fetched email, parameterized SQL, and bounded response/notice projections. [VERIFIED: D-03, D-04, D-06; established repo patterns]
- **V6 / cryptography:** Use the provider library for webhook verification; use SHA-256 only as a deterministic fixture dedup key, never as authentication. [VERIFIED: current gateway/fixture mode]
- **V7 / logging:** Do not log raw event payloads, sender addresses, submitted names/mappings, database exceptions, or provider bodies. Store safe diagnostic class/code only where existing queue policy requires it. [VERIFIED: PII-safe boundary and Phase 18 diagnostics]

### Threat model

| Threat | Control |
|---|---|
| Spoofed or tampered webhook | Exact-byte provider verification before parsing/persisting. [VERIFIED/CITED: current library boundary] |
| Oversized request memory/DB abuse | Streaming 256 KiB cap and 30-day terminal-only retention. [VERIFIED: D-06; Starlette docs] |
| Replay creates duplicate work | Unique transport event plus RFC Message-ID dedup and stable downstream dedup keys. [VERIFIED: D-05] |
| Forged/cross-run clarification resume | Exact email/run ownership plus sender revalidation before orchestration on every attempt. [VERIFIED: D-20; Phase 18 binding] |
| Concurrent operator mapping changes payroll | Run-row serialization, one authoritative-generation constraint, loser no-op, winner-only remember projection. [VERIFIED/CITED: D-11–D-13; PostgreSQL locks] |
| PII exposure through queue/UI/errors | Identifiers-only jobs, bounded event receipt/notices, safe queue labels, no raw diagnostics. [VERIFIED: D-02, D-03, D-14, D-17, D-22] |
| Transport failure mutates business state | Kind-aware ingest settlement never writes `payroll_runs.status`. [VERIFIED: J-1 and recommended seam] |

No new operator authentication is introduced in this phase; the existing dashboard trust boundary remains an accepted project limitation and must not be silently broadened into Phase 19. [VERIFIED: phase boundary and current app]

## Common Pitfalls

1. **Adding `ingest` only to dispatch.** This passes handler tests but null-run settlement/reaping still strands jobs. [VERIFIED: current settlement guards]
2. **Returning 200 before the transaction commits.** A post-response insert recreates the exact loss window Phase 19 exists to close. [VERIFIED: phase goal]
3. **Using RFC Message-ID at webhook acceptance.** It is unavailable until the delayed body fetch; using it erases transport-redelivery dedup. [VERIFIED: gateway envelope/fetch split]
4. **Letting worker timing select operator authority.** This violates D-11 and lets retry scheduling become money-moving logic. [VERIFIED: current race and context]
5. **Projecting alias candidates in the route.** A losing generation can mutate approval-gate learning before its job no-ops. [VERIFIED: current route and D-13]
6. **Using attempts to detect first resume.** A crash before payroll CAS means a later attempt can still see the original business state. [VERIFIED: lease/retry model]
7. **Deleting events with cascade or restrictive FK.** Cascade loses queue audit; restrict defeats retention. Use terminal-only purge plus `SET NULL`-compatible checks. [CITED: PostgreSQL FK behavior; VERIFIED: retention goal]
8. **Treating queue state as payroll status.** The UI projection must remain secondary and bounded. [VERIFIED: D-15]
9. **Counting only current `.add_task()` calls.** QUEUE-04 requires a permanent negative guard across all historically identified producer seams, including unused signatures and helper wrappers. [VERIFIED: requirement wording and current source]
10. **Overclaiming Phase 21 proof.** Phase 19 must create reliable tests and guarded concurrency coverage, but final red-run evidence and CI registration belong to Phase 21. [VERIFIED: roadmap boundary]

## Package Legitimacy Audit

No package is proposed. This phase should use only already-pinned project dependencies and standard-library `hashlib`; therefore no registry, maintainer, typo-squatting, or install-time audit is required. [VERIFIED: `pyproject.toml` and recommended design]

## Assumptions and Open Runtime Checks

No product decision remains open: the context locks the acceptance contract, dedup layers, concurrency authority, presentation, and scope. [VERIFIED: `19-CONTEXT.md`]

One deployment-state fact is unknown: whether live `operator_resume_resolutions` already contains one or multiple generations per unresolved run. The implementation plan must include a read-only pre-deploy query and a fail-closed migration rule; it must not infer commit order from historical timestamps. [VERIFIED: `DATABASE_URL` absent; PostgreSQL timestamp semantics]

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|---|---|---|
| — | None. All design claims are repository-verified or primary-source cited; unknown live data is explicitly a pre-deploy check, not an assumed fact. | — | — |

## Open Questions

1. **Does the live database contain unresolved legacy operator generations?**
   - What we know: the schema supports generations and Phase 18 shipped their write path. [VERIFIED: schema/source]
   - What is unclear: live row counts are unavailable because `DATABASE_URL` is unset. [VERIFIED: environment probe]
   - Recommendation: add a read-only pre-deploy count grouped by run; never infer multi-generation authority from `created_at`. [CITED: PostgreSQL timestamp semantics]

## Sources

### Primary repository evidence (HIGH)

- `AGENTS.md`; `.planning/ROADMAP.md`; `.planning/REQUIREMENTS.md`; `.planning/STATE.md`; Phase 16–18 contexts, summaries, research, and verification artifacts.
- `app/routes/webhook.py`, `demo.py`, `runs.py`, `pipeline_glue.py`; `app/gateway.py` and gateway implementation.
- `app/models/job.py`; `app/db/schema.sql`; `app/db/repo/jobs.py`, run/email/operator repositories; `app/queue/dispatch.py`, handlers, worker, wake, and pump.
- Existing webhook, dedup, queue, resume, operator, schema, fake-parity, and dashboard tests.

### External primary documentation (MEDIUM after fallback classification)

- Starlette Requests: https://www.starlette.io/requests/ — request streaming behavior.
- PostgreSQL 15 Explicit Locking: https://www.postgresql.org/docs/15/explicit-locking.html — row-lock blocking and transaction lifetime.
- PostgreSQL 15 Date/Time Functions: https://www.postgresql.org/docs/15/functions-datetime.html — transaction-start timestamp semantics.
- PostgreSQL 15 Constraints: https://www.postgresql.org/docs/15/ddl-constraints.html — foreign-key actions and checks.
- PostgreSQL 15 SET CONSTRAINTS: https://www.postgresql.org/docs/15/sql-set-constraints.html — immediate CHECK behavior.

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — exact pins and usages are present in the checkout; no package is added. [VERIFIED: `pyproject.toml`]
- Architecture: HIGH — recommendations follow locked context and concrete Phase 16–18 interfaces; external SQL/stream semantics are primary-source cited. [VERIFIED/CITED]
- Pitfalls: HIGH for code seams, MEDIUM for framework/database behavior obtained through web fallback rather than Context7. [VERIFIED: research helper classification]

**Research date:** 2026-07-16  
**Valid until:** 2026-08-15 for repository architecture; recheck only if Phase 16–18 contracts or provider envelope shape changes. [VERIFIED: stable-phase assumption scoped to explicit change triggers]

## Operational Notes

The requested typed `gsd-phase-researcher` agent was unavailable in this runtime, so the parent used a generic-agent workaround and bound this task to the complete `/Users/pnhek/.codex/agents/gsd-phase-researcher.toml` role plus all mandatory references. This affects orchestration metadata only; the artifact follows the required constraint-first structure, verification protocol, runtime inventory, validation architecture, and security analysis. [VERIFIED: agent launch context and role reads]

---

*Phase: 19-webhook-cutover-durable-ingest*  
*Research completed: 2026-07-16*
