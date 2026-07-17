# Phase 20: Exactly-Once Send - Pattern Map

**Mapped:** 2026-07-17
**Files analyzed:** 18 likely modified/created files
**Analogs found:** 17 / 18 (the immutable snapshot/attempt-event schema is genuinely new)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match quality |
|---|---|---|---|---|
| `app/db/schema.sql` | schema/migration | transactional event-driven | existing `email_messages` and `jobs` definitions | extension |
| `app/db/repo/emails.py` | repository | transactional CRUD | `insert_email_message`, `get_unconfirmed_outbound` | exact seam |
| `app/db/repo/jobs.py` | repository | durable queue CRUD | `enqueue_job` validation | exact |
| `app/db/repo/job_settlement.py` | repository coordinator | fenced retry/settlement | `settle_pipeline_job` | close, requires delivery-specific branch |
| `app/models/job.py` | model/config | durable queue vocabulary | `JobKind`/`Job` | exact |
| `app/pipeline/result.py` | outcome classifier | transform | `classify_pipeline_exception` | exact |
| `app/email/gateway.py` | provider gateway | external side effect | `send_outbound` | exact seam |
| `app/pipeline/delivery.py` | service/orchestration | approval-to-event | existing `deliver` composition path | split at new reservation seam |
| `app/pipeline/send_guard.py` | policy utility | safe decision | `assert_no_unconfirmed_send` | exact detection, changed action |
| `app/queue/handlers/send_outbound.py` (new) | worker handler | identifier-only event-driven | `handlers/resume_reply.py` | close |
| `app/queue/dispatch.py` | dispatcher | event-driven | `HANDLERS` late-bound table | exact |
| `app/routes/runs.py` | route/controller | request-response | `resolve`, `retrigger`, `_safe_run_for_browser` | close |
| `app/templates/run_detail.html` | server component | request-response/presentation | `needs_operator` banner and queue badge | close |
| `app/static/style.css` | presentation | static | existing banner/card/button rules | close |
| `tests/conftest.py` | test fake | CRUD/queue simulation | `InMemoryRepo` email and job methods | exact mirror required |
| `tests/test_send_idempotency.py` | safety/integration tests | provider/repository event flow | existing falsifying-mutation twins and live-DB epoch proof | exact base |
| `tests/test_queue_durability.py`, `tests/test_queue_drain.py`, `tests/test_job_kind_drift.py`, `tests/test_repo_jobs_sql.py` | queue contract tests | fenced event-driven | current kind/SQL/dispatch proof suite | exact extension |
| `tests/test_delivery.py` and route/template tests | service/controller tests | approval-to-delivery | current delivery guard/error-boundary tests | close |

## Pattern Assignments

### `app/db/schema.sql` (schema/migration, transactional event-driven)

**Analogs:** `app/db/schema.sql:225-295` (`email_messages` identity/lifecycle) and `app/db/schema.sql:500-572,694-726` (`jobs` constraints plus idempotent live-schema repair).

Copy the existing migration discipline: define current-install columns/constraints in `CREATE TABLE IF NOT EXISTS`, then add idempotent `ALTER ... ADD COLUMN IF NOT EXISTS` and atomic/drop-readd constraint repairs for deployed databases. The existing logical send-slot is already an immutable historical identity:

```sql
-- app/db/schema.sql:275-280
CONSTRAINT uq_email_run_purpose_round_epoch UNIQUE (run_id, purpose, round, epoch)
```

Phase 20 should extend this record with a separate append-only snapshot/attachment/attempt model (or equivalent immutable child rows), rather than turning the row's retry fields into mutable payload. Attachments must be byte columns/rows, not JSON/base64 stored in a job. `jobs` continues to contain only identifiers; its constraints explicitly prohibit payload-like context (`app/db/schema.sql:550-572`).

**New pattern:** no present table captures a provider-ready envelope plus ordered raw bytes and PII-safe delivery attempt events. Model it as a parent reservation keyed to the existing email row plus append-only child attachments/events; preserve `email_messages` as the logical send audit and do not update snapshot columns during replay.

### `app/db/repo/emails.py` (repository, transactional CRUD)

**Analog:** `insert_email_message` at `app/db/repo/emails.py:16-137` and `get_unconfirmed_outbound` at `app/db/repo/emails.py:221-298`.

Use `_conn_ctx(conn)` and the owned-transaction conditional exactly as the repo does:

```python
# app/db/repo/emails.py:69-76
with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
    if purpose is not None:
        row = c.execute(...).fetchone()
```

Replace the caller-argument overwrite semantics in the outbound conflict branch (`lines 84-90`) with an explicit read-or-reserve API. It must lock/select the existing `(run_id, purpose, round, epoch)` slot and return the stored snapshot unchanged, or insert the message id/envelope/attachments exactly once in the absent-row branch. Keep the four-column identity synchronized with the schema; the local docstring at `lines 34-64` explains why epochs make a human-authorized new slot distinct.

`get_unconfirmed_outbound` is deliberately only the detection predicate. Its comment already permits safely widening the response while retaining its scope: `app/db/repo/emails.py:268-272`. Evolve it to surface only safe reservation facts required for eligibility/review (including DB reservation time and bounded classification), not body bytes or raw provider data in a browser projection.

For browser display, follow `load_outbound_emails` (`lines 448-467`): explicit column lists, `dict_row`, parameterized SQL, and a separate purpose-built safe projection. Do not reuse a broad `SELECT *` loader for snapshot/attempt diagnostics.

### `app/db/repo/jobs.py`, `app/models/job.py`, and `app/queue/dispatch.py` (durable transport vocabulary)

**Analogs:** `JobKind`/`Job` at `app/models/job.py:25-88`, enqueue validation at `app/db/repo/jobs.py:57-150`, and dispatch at `app/queue/dispatch.py:25-51`.

Add `send_outbound` atomically across all three layers. It should use `Job.email_id` as its sole business context, matching the existing identifier-only convention:

```python
# app/db/repo/jobs.py:116-124
if kind_value == "resume_reply" and (
    run_id is None or email_id is None or operator_resolution_id is not None
    or event_id is not None
):
    raise ValueError("enqueue_job: kind='resume_reply' requires run_id and email_id only")
```

The send job should similarly require `run_id` and the persisted email/snapshot UUID, reject every other context id, and use a dedup key derived from the immutable send slot. Do not add job payload fields: `app/models/job.py:63-77` and `app/db/repo/jobs.py:12-16` make that a queue invariant.

Register by module/name, not a bound callable:

```python
# app/queue/dispatch.py:29-34
HANDLERS: dict[JobKind, tuple[ModuleType, str]] = {
    JobKind.RUN_PIPELINE: (pipeline, "handle_run_pipeline"),
    ...
}
```

The late lookup in `dispatch.handle` (`lines 42-51`) is necessary for monkeypatchable tests. Mirror the SQL `jobs.kind` check and context check in both initial table definition and repair block (`app/db/schema.sql:550-572,694-726`).

### `app/db/repo/job_settlement.py` (fenced delivery retry coordinator)

**Analog:** `settle_pipeline_job` at `app/db/repo/job_settlement.py:338-429`, especially its lock:

```python
# app/db/repo/job_settlement.py:74-87
SELECT attempts, max_attempts, run_id, kind FROM jobs
 WHERE id = %s AND state = 'leased' AND lease_token = %s
 FOR UPDATE
```

and the fenced reschedule update at `lines 377-395`.

Do **not** route the send job through the current generic retry branch: it calls `_rewind_run` (`lines 377-379`), which assumes `EXTRACTING -> RECEIVED` and violates D-05. Add a narrow send-specific settlement/helper that locks the job and reservation under the lease token, appends a bounded attempt event, and either:

- marks this logical reservation sent and job done;
- returns the same job to `pending` at the delivery schedule while the DB reservation age is below 20h, with run status left `approved`; or
- atomically moves `approved -> needs_operator`, stores only a fixed failure category, and completes/deads the job when replay is unsafe.

Fenced losers return `SettlementOutcome.FENCED` and make no reservation/attempt/run write. This is the established zombie-worker rule in `app/db/repo/jobs.py:268-287` and the shared drain coordinator.

### `app/pipeline/result.py` (provider classification)

**Analog:** `PipelineResult` and `classify_pipeline_exception` at `app/pipeline/result.py:16-118`.

Keep diagnostics as enum-only `stage:reason` strings:

```python
# app/pipeline/result.py:50-62
@dataclasses.dataclass(frozen=True)
class PipelineResult:
    outcome: PipelineOutcome = PipelineOutcome.TERMINAL
    stage: PipelineStage = PipelineStage.UNKNOWN
    reason: PipelineReason = PipelineReason.UNCLASSIFIED
```

Extend the existing delivery exception policy instead of persisting exception text. Today send-stage provider exceptions intentionally become `AMBIGUOUS_SEND_FAILURE` (`lines 79-85`). Phase 20 should classify retryable timeout/connection/5xx/rate-limit and terminal payload mismatch/auth/config/validation into bounded values, with a deliberate quota distinction if provider data supports it. Never stringify Resend errors into `last_error`, attempt history, routes, or logs.

### `app/email/gateway.py` (provider gateway, external side effect)

**Analog:** `send_outbound` at `app/email/gateway.py:209-359`.

The current defect is visible in its sequence: it builds headers from caller args (`lines 257-303`), mints a UUID before it knows whether the send slot exists (`lines 271-289`), and re-encodes caller attachment bytes (`lines 304-318`). Move the provider call to a method that accepts only a persisted reservation/snapshot object. The Message-ID header must be the stored id, and `resend.Emails.send` must receive the stored payload plus the SDK's idempotency option every time.

Retain the strong local conventions: set `resend.api_key` before use (`lines 253-255`), send no database transaction across the provider call, encode bytes at the gateway boundary, and keep logs to ids/type/categories only (`lines 339-357`). Replace the direct state flip on exception with returned/classified outcome suitable for the fenced queue settlement; a provider call may be accepted before an exception is observed.

### `app/pipeline/delivery.py` and `app/pipeline/send_guard.py` (approval service and safe decision)

**Analogs:** `delivery.deliver` at `app/pipeline/delivery.py:39-262`; `assert_no_unconfirmed_send` at `app/pipeline/send_guard.py:40-80`.

The existing delivery function is the only place that composes confirmation text and creates ReportLab PDFs (`delivery.py:130-210`). Refactor it so that work happens once before an atomic reserve/enqueue transaction; replay must call neither `compose_confirmation` nor `generate_paystub_pdf`. The current already-sent early path (`lines 89-114`) remains the proof-of-delivery path, but an unconfirmed slot must now choose bounded replay eligibility rather than raise unconditionally.

Keep the detector central and purpose/round/epoch scoped. The guard's PII-safe logging rule (`send_guard.py:55-80`) is the right model for all replay/review diagnostics. The *new* policy is a result/decision object (safe replay vs review), not a loosened lookup that treats `reserved` as sent or silently mints a new ID.

The initial approve request must schedule durable work and return; it must not offer a second synchronous provider path. Its current `approve` route is synchronous (`app/routes/runs.py:244-294`), so planner should explicitly include the approve/delivery handoff with commit-before-`wake.wake()` as shown in `runs.py:395-423`.

### `app/queue/handlers/send_outbound.py` (new handler, identifier-only event-driven)

**Closest analog:** `app/queue/handlers/resume_reply.py:39-97`, with no-op behavior from `operator_resume.py:33-61`.

Follow the handler shape: validate the job's identifiers, reload the durable record, return a bounded `PipelineResult` on invalid/stale/superseded context, and call no provider before ownership/policy checks. In particular:

```python
# app/queue/handlers/resume_reply.py:39-56
run_id = job.run_id
if run_id is None:
    raise ValueError(...)
email_id = job.email_id
if email_id is None:
    raise ValueError(...)
row = repo.get_inbound_email_by_id(email_id)
if row is None:
    return _bounded_noop()
```

For sends, load the immutable reservation by `email_id`, ensure it belongs to `job.run_id`, calculate the 20-hour cutoff from the DB reservation timestamp, then invoke the gateway with snapshot fields only. Its return result must be settled through the delivery-specific fenced coordinator above. It must not call `delivery.deliver`, re-load line items, draft, or generate PDFs.

### `app/routes/runs.py`, `app/templates/run_detail.html`, and `app/static/style.css` (delivery-review UI)

**Analogs:** safe browser projection in `app/routes/runs.py:144-241`, `resolve` at `lines 318-423`, run-detail loading at `lines 706-805`, and the existing `needs_operator` banner/form at `app/templates/run_detail.html:110-142`.

Follow the route safety boundary: pull raw DB fields into a separate review projection, whitelist fixed status/category values, then delete raw diagnostics before rendering. `_safe_run_for_browser` currently removes `error_reason`, `error_detail`, `last_error`, attempts and raw job fields (`runs.py:204-228`); do not bypass that by passing provider raw responses into the template.

For actions, use the `resolve` pattern: validate all input before write, use an atomic transaction for state/action/enqueue, 303 redirect regardless of a losing/stale double submit, and call `wake.wake()` only after commit (`runs.py:395-423`). The new `retry now` only advances the existing job; it cannot directly call the gateway. `Mark delivered` has no provider call. `Authorize a new confirmation` must validate the exact typed acknowledgement server-side, clone the original persisted snapshot into a distinct human-authorized send slot, enqueue it in the same transaction, then wake.

Template structure should extend the focused banner/card model, not the generic `error` message. The current outbound card (`run_detail.html:314-339`) is the closest artifact display shape, while the existing needs-operator form supplies the POST/explicit operator-gate shape. Add compact CSS beside `.sent-email-card` (`app/static/style.css:679+`) and existing button/banner classes; no SPA or raw-data debug panel.

### Tests and fakes (safety-critical event flow)

**Primary analog:** `tests/test_send_idempotency.py:181-211,219-334,434-514`.

Preserve its proof design: a hermetic SQL-shape test that fails if the real query loses the safety predicate, a non-vacuity twin where the safe path actually sends, and real-Postgres proofs for identity/epoch semantics. Phase 20 must add tests that falsify:

- retry receiving a newly minted Message-ID or changed payload;
- an upsert overwriting stored subject/body/recipient/thread headers/attachments;
- replay invoking LLM/PDF generation;
- an automatic send after 20h or an automatic new key after payload mismatch;
- a stale or losing lease appending an attempt event, rescheduling, or transitioning to review;
- concurrent scheduled/manual retry creating two active jobs or provider attempts;
- an approval/restart continuation that loses its reservation/schedule;
- `Mark delivered` calling the provider and typed authorization failing to create a visibly distinct slot.

Extend `tests/conftest.py`'s `InMemoryRepo` in lockstep with the production read-or-reserve, snapshot, attempt, and send-job APIs (`tests/conftest.py:1244-1340,1655-1663,786-873`). A fake alone cannot prove SQL conflict/epoch constraints; put those in a `@pytest.mark.integration` + `@pytest.mark.queueproof` live-DB test modeled after `test_the_unconfirmed_guard_is_epoch_scoped`.

For queue widening, update the existing equality and SQL tests rather than adding an unconnected handler test: `tests/test_job_kind_drift.py` enforces enum/SQL/dispatch equality, `tests/test_repo_jobs_sql.py` pins enqueue/claim shapes, and `tests/test_queue_drain.py`/`tests/test_queue_durability.py` exercise lease reclamation and fenced settlement.

## Shared Patterns

### Transaction boundary and wake ordering

**Sources:** `app/routes/runs.py:395-423`, `app/db/repo/jobs.py:154-188`, `app/queue/wake.py:16-29`.

Persist reservation/snapshot and enqueue in one caller-owned transaction. Call `wake.wake()` only after it commits. Never hold any transaction around the Resend request.

### Fencing is wider than job completion

**Sources:** `app/db/repo/jobs.py:268-306`, `app/db/repo/job_settlement.py:338-429`, `app/queue/drain.py:185-235`.

Every delivery side effect *after a job is leased* (attempt-event append, reschedule, sent mark, run review transition) must validate that exact `lease_token`. A fenced-out worker logs and drops; it does not retry or mutate business state.

### Business state is separate from queue state

**Sources:** `app/models/job.py:1-16`, `app/routes/runs.py:231-241`, `app/templates/run_detail.html:4-15`.

Keep `payroll_runs.status` as the business state machine. A safe retry remains `approved` and projects the existing secondary `Retry queued` label; it does not introduce a send-specific run status. Only non-replayable ambiguity transitions to `needs_operator`.

### Safe data projection

**Sources:** `app/pipeline/result.py:1-6`, `app/routes/runs.py:144-228`, `app/pipeline/send_guard.py:55-80`.

Persist/render bounded categories and identifiers, not provider request/response bodies or exception strings. The explicitly requested frozen email/PDF review artifact must be served from persisted snapshot data through a dedicated, authorization-free but bounded route/template projection, not reconstructed from mutable payroll data and not mixed with raw diagnostics.

### Existing constraints to retain

- All Python commands/tests use `uv run`; no dependency install or hand-maintained requirements file.
- Keep `message_id` as RFC threading anchor and retain `reply_to`/References fields (`app/email/gateway.py:257-326`).
- Do not treat a provider result as proof before fenced DB settlement; do not reset the 20-hour clock from retry state, job attempts, or restart time.
- Human-authorized repeat uses a distinct slot/epoch but copies original frozen bytes exactly; automatic replay always uses the original slot/key.

## Planning Notes

The natural execution order is: (1) schema/repository snapshot and queue vocabulary, (2) gateway/handler/result/settlement behavior with tests, (3) approval/review routes and UI, then (4) secondary YTD/eval/progressive-enhancement work only after SEND-01 through SEND-03 proofs are green. Avoid combining the unrelated polish changes with the safety-critical migration in the same implementation plan or test target.
