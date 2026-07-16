# Phase 19: Webhook Cutover & Durable Ingest - Context

**Gathered:** 2026-07-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 19 makes accepted inbound work durable before the webhook returns `200`. The
request path verifies the Svix signature, validates only the minimal Resend transport
envelope, and atomically persists the inbound event plus an `ingest` job. The Resend
body fetch and the existing five-outcome ingest-decision transaction execute later in a
durable worker. A crash, restart, or sleeping instance after acceptance cannot lose the
email.

The phase also removes every remaining process-memory `BackgroundTasks` producer by
moving the webhook, both demo triggers, clarification reply paths, operator resolution,
and the remaining runs-route producers onto the existing queue. The queue remains
transport state only; `payroll_runs.status` remains the sole payroll business state.

The phase must preserve the current sender-revalidation guard for clarification replies,
the DATA-02 five-outcome transaction, message-level deduplication, deterministic money
decisions, and the one human approval gate.

**Out of scope:** provider-side exactly-once outbound send (Phase 20), the queue-health
and dead-letter operations surface (Phase 21), new payroll statuses, new business
capabilities, and the legacy UI/paystub/eval polish todos.

**Requirement:** QUEUE-04.

</domain>

<decisions>
## Implementation Decisions

### Webhook acceptance and response contract

- **D-01: Distinguish a new event from a transport redelivery without exposing queue internals.** A newly persisted event returns `200` with `status=accepted` and its
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and current state

- `.planning/ROADMAP.md` — Phase 19 goal, dependency order, and four success criteria;
  QUEUE-04 owns the complete producer cutover.
- `.planning/REQUIREMENTS.md` — QUEUE-04 and the milestone proof requirements that depend
  on transport- and message-level deduplication.
- `.planning/PROJECT.md` — v4 Durable Execution boundary and recruiter-first product
  priorities.
- `.planning/STATE.md` — current verified Phase 18 closeout and active milestone
  decisions.

### Approved durable-execution design

- `docs/superpowers/specs/2026-07-13-durable-execution-design.md` — authoritative claim,
  build order, jobs-table intent, webhook cutover, failure policy, and proof model.
- `.planning/research/ARCHITECTURE.md` — especially §2 job granularity, §3 enqueue
  atomicity and dedup keys, §6 two-layer ingest re-keying, and the NEW/MODIFIED inventory.
- `.planning/research/SUMMARY.md` — adversarial design corrections, including the complete
  producer count, raw-inbox retention executor, and non-vacuous proof requirements.
- `.planning/research/PITFALLS.md` — webhook body-size, PII, transport-payload, and
  durability failure modes.

### Upstream queue and failure-policy contracts

- `.planning/phases/18-failure-policy-sweep-deletion/18-CONTEXT.md` — explicit pipeline
  result contract, safe retry/dead-letter settlement, immutable operator generations,
  and queue-owned recovery.
- `.planning/phases/17-the-pump/17-CONTEXT.md` — shared drain/pump accounting and external
  wake path that must already exist before webhook cutover.
- `.planning/phases/16-queue-substrate-unblocked-webhook/16-CONTEXT.md` — queue invariants,
  identifiers-only job rows, fencing, CAS ownership, worker lifecycle, and the Phase 19
  producer-cutover deferrals.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `app/db/repo/jobs.py::enqueue_job` — caller-owned `conn=` support and dedup-key
  `ON CONFLICT DO NOTHING` contract; extend it atomically for `ingest` rather than
  inventing a second queue API.
- `app/queue/dispatch.py` and `app/queue/handlers/` — module-and-function-name dispatch,
  runtime result normalization, and exact `JobKind` handler equality. Add `ingest`
  atomically with its handler and SQL/Python constraints.
- `app/routes/webhook.py::_parse_and_ingest_sync` — the existing DATA-02 five-outcome unit
  to move into the durable ingest handler with behavior/evidence preserved.
- `app/routes/pipeline_glue.py::row_to_inbound` and `reply_sender_ok` — existing durable
  reply rehydration and sender-authorization controls.
- `app/db/repo/operator_resume_resolutions.py` — immutable operator-generation authority
  shipped in Phase 18; extend its ordering/supersession contract rather than returning to
  transient override dictionaries.
- `app/templates/run_detail.html` and `app/templates/runs_list.html` — existing two-second
  polling and secondary failure-badge patterns that can carry the bounded queue feedback.

### Established Patterns

- **Invariant J-1:** queue state is transport-only and `payroll_runs.status` is the sole
  business state machine. A failed handler CAS is a successful no-op, not a retry.
- **Atomic owed-work creation:** the state change and its job enqueue share one
  transaction; `wake.wake()` fires only after commit.
- **Two independent idempotency layers:** Svix event delivery and RFC message identity are
  different causes and require different uniqueness constraints.
- **Identifiers-only queue records:** reply bodies and operator mappings are rehydrated
  from durable domain tables; `jobs` carries no business payload.
- **PII-safe browser boundary:** templates receive bounded safe projections, never raw
  queue/provider/database diagnostics.
- **Module-object monkeypatch seams and fake parity:** route/handler dependencies resolve
  through module attributes, and every new facade function must be paired in the fake
  repository patch inventories.

### Integration Points

- `app/routes/webhook.py::inbound` — reduce to request-body cap, signature verification,
  minimal envelope validation, atomic event/job persistence, bounded response shaping,
  and post-commit wake.
- `app/db/schema.sql` and schema-introspection tests — add `inbound_events`, the job-to-event
  identifier, `ingest` kind constraints, retention-supporting index/fields, and any
  first-commit operator-authority constraint.
- `app/models/job.py`, `app/db/repo/jobs.py`, `app/queue/dispatch.py`, and
  `app/queue/handlers/ingest.py` — widen the queue contract as one drift-safe unit.
- `app/routes/demo.py` — place `create_run` and `enqueue_job(RUN_PIPELINE)` in the same
  transaction and redirect both demo routes to run detail.
- `app/routes/runs.py` and `app/routes/pipeline_glue.py` — remove remaining
  `BackgroundTasks` parameters/producers, enqueue durable reply/operator work, preserve
  authorization, and implement deterministic operator-generation supersession.
- `app/db/repo/runs.py` list/detail projections plus `app/templates/runs_list.html` and
  `app/templates/run_detail.html` — expose only bounded open-job presentation and the
  two-minute demo polling contract.
- `tests/test_webhook_unblocked.py`, webhook/dedup/concurrency tests, queue durability
  tests, route tests, fake-repo inventories, and job-kind drift tests — prove post-200
  durability, two-layer dedup, sender revalidation, complete producer deletion, and
  first-commit operator authority without vacuous mocks.

</code_context>

<specifics>
## Specific Ideas

- The webhook's accepted response is intentionally an **event receipt**, not a payroll-run
  receipt. The worker may create a run later or may classify the event as duplicate,
  late-reply, or unknown-sender.
- The recruiter demo should feel one-click: either demo trigger opens the real run detail,
  which visibly advances without requiring the recruiter to find the new row first.
- The exact durability explanation selected for run detail is: **“This action is durably
  saved; you can safely leave this page.”**
- The two-layer dedup explanation should survive into planning and eventual PR copy:
  **Svix ID deduplicates the delivery; RFC Message-ID deduplicates the message. An ingest
  job retry is the case that requires both.**
- Competing operator mappings are not last-writer-wins and not worker-race-wins. The
  earliest committed complete generation is durable money-moving authority.

</specifics>

<deferred>
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

</deferred>

---

*Phase: 19-Webhook Cutover & Durable Ingest*
*Context gathered: 2026-07-16*
