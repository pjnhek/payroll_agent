# Phase 18: Failure Policy & Sweep Deletion - Pattern Map

**Mapped:** 2026-07-15
**Files analyzed:** 39 new/modified/deleted files or test surfaces
**Analogs found:** 39 / 39
**Dispatch note:** Produced via the generic-agent workaround for `gsd-pattern-mapper`; typed GSD agent dispatch was unavailable.

## File Classification

| New/Modified File | Role | Data Flow | Closest Current Analog | Match Quality |
|---|---|---|---|---|
| `app/pipeline/result.py` (new) | model / utility | transform | `app/models/status.py`; `app/models/job.py` | exact composition |
| `app/pipeline/orchestrator.py` | service / orchestrator | request-response + side effects | its current `_run()` / `resume_pipeline()` boundaries | exact, behavior changes |
| `app/routes/pipeline_glue.py` | adapter / bridge | event-driven | current background wrappers + `row_to_inbound()` | exact |
| `app/models/job.py` | transport model | event-driven | current `JobKind` / frozen `Job` | exact |
| `app/db/schema.sql` | migration / config | DDL | `email_messages.purpose` CHECK widening block | exact |
| `app/queue/handlers/resume_reply.py` (new, or equivalent handler in `pipeline.py`) | queue handler | event-driven | `app/queue/handlers/pipeline.py` | role/data-flow exact |
| `app/queue/handlers/operator_resume.py` (new) | queue handler | event-driven | `app/queue/handlers/pipeline.py` + current operator wrapper | role/data-flow exact |
| `app/queue/handlers/pipeline.py` | queue handler | event-driven | current CAS-only handler | exact, result-aware extension |
| `app/queue/dispatch.py` | dispatcher | event-driven | current module/name dispatch table | exact |
| `app/db/repo/job_settlement.py` (new, or equivalent focused module) | repository / service | transactional CRUD | orchestrator persist transaction + retrigger transaction | exact composition |
| `app/db/repo/operator_resume_resolutions.py` (new) | repository | transactional CRUD | immutable parent plus explicit child-row repositories + caller-owned route transaction | exact composition |
| `app/db/schema_introspect.py` | schema health | read-only catalog diff | current expected/live table-column and constraint inventory | exact extension |
| `tests/test_schema_introspect.py` | schema drift test | scripted catalog reads | current per-table query-order and missing-object cases | exact extension |
| `app/db/repo/jobs.py` | repository | transactional CRUD / batch | current claim/complete/fail primitives | exact |
| `app/db/repo/__init__.py` | facade | imports/exports | current explicit facade and `__all__` | exact |
| `app/queue/drain.py` | queue service | batch / event-driven | current `DrainOutcome` + `drain_once()` | exact |
| `app/routes/pump.py` | controller | request-response + batch | current count loop | exact |
| `app/db/repo/demo.py` | repository | read-only CRUD | current explicit runs-list projection | exact |
| `app/routes/runs.py` | controller | request-response | current retrigger transaction, list read, status poll | exact |
| `app/templates/runs_list.html` | component | request-response/polling | current status badge + polling DOM update | exact |
| `app/templates/run_detail.html` | component | request-response/polling | current error banner + Retrigger | exact |
| `app/db/repo/runs.py` | repository / deletion target | CRUD | `claim_status()` and `record_run_error()`; delete current sweep | exact |
| `app/db/repo/emails.py` | repository / deletion target | CRUD | `get_inbound_by_message_id()`; delete current stranded-reply scan | exact |
| `app/db/repo/pipeline_state.py` | repository / reclaim invariant | transactional CRUD | current `rewind_for_reclaim()` versus `clear_reply_context()` epoch boundary | exact preservation target |
| `app/models/status.py` | business-state model | state machine | current canonical `RunStatus` mirrored by SQL drift tests | exact preservation target |
| `tests/test_orchestrator_states.py` | unit test | transform/state | current success/error/clarification tests | exact |
| `tests/test_resume_pipeline.py` | unit test | stateful request-response | current resume ordering and exactly-once call tests | exact |
| `tests/test_job_kind_drift.py` | static drift test | file-I/O / AST/text | current enum/SQL/dispatch equality guards | exact |
| `tests/test_repo_jobs_sql.py` | hermetic repository test | SQL-shape | current claim projection and fence tests | exact |
| `tests/test_queue_drain.py` | hermetic service test | event-driven | current per-outcome and CAS-only tests | exact |
| `tests/test_queue_durability.py` | integration test | concurrent transactional CRUD | current reclaim/zombie/retrigger proofs | exact |
| `tests/test_pump_route.py` | route test | request-response + batch | current count invariant tests | exact |
| `tests/test_dashboard.py` | route/template test | request-response/polling | current DB-to-template error-detail proof | exact |
| `tests/test_stuck_run_recovery.py` | deletion/route test | request-response | current sweep wiring tests, inverted into negative gates | exact target |
| `tests/test_reply_redelivery.py` | safety regression test | event-driven | current webhook redelivery vs runs-list auto-resume split | exact target |
| `tests/test_needs_operator.py` | safety regression test | request-response | current human-gate exclusion tests | exact target |
| `tests/test_alias_and_run_column_regressions.py` | repository/route regression test | SQL-shape + request-response | current reply-context clearing and stale-provenance retrigger tests | exact preservation target |
| `tests/test_hitl.py` | route/queue regression test | request-response + event-driven | current retrigger enqueue, drain, epoch, and second-generation tests | exact preservation target |
| `tests/test_retrigger_epoch.py` | state-machine regression test | event-driven | current real-seam epoch-scoped outbound/consumed-reply proofs | exact preservation target |
| `tests/conftest.py` | test provider / fake store | in-memory CRUD | current `InMemoryRepo` queue mirrors and patch tuple | exact |
| `tests/test_fake_repo_pairing.py` | harness guard | AST/reflection | current fake-method pairing assertion | exact |

No separate migrations directory exists. The established deployed-database migration path is idempotent DDL inside `app/db/schema.sql`, applied atomically by `app/db/bootstrap.py`; do not invent an Alembic-style tree for this phase.

## Pattern Assignments

### `app/pipeline/result.py` (model / transform)

**Analogs:** `app/models/status.py:12-29` for bounded `StrEnum`; `app/models/job.py:64-87` for a frozen transport dataclass.

```python
class RunStatus(enum.StrEnum):
    RECEIVED = "received"
    EXTRACTING = "extracting"
    ...

@dataclasses.dataclass(frozen=True)
class Job:
    id: uuid.UUID
    kind: JobKind
    run_id: uuid.UUID | None
    attempts: int
    max_attempts: int
    lease_token: uuid.UUID
```

Copy the bounded-enum plus frozen-dataclass shape for `PipelineOutcome`, stage, reason, and `PipelineResult`. The safe constructor default must be `terminal`/unknown/unclassified. Do **not** copy exception text into the result: D-02 requires every field to come from a bounded code set.

### `app/pipeline/orchestrator.py` (service / request-response)

**Current boundary to replace:** `app/pipeline/orchestrator.py:195-247` and `:850-859`.

```python
def run_pipeline(run_id: uuid.UUID, *, llm: Any = None) -> None:
    _run(run_id, llm=llm)

def _run(run_id: uuid.UUID, *, llm: Any) -> None:
    roster = None
    try:
        ...
        _ = _run_stages(run_id, email, roster, llm=llm)
    except Exception as exc:
        reason = type(exc).__name__
        logger.warning("run %s failed: %s", run_id, reason)
        repo.record_run_error(...)
```

Both entry points currently swallow and persist every exception. Preserve the single catch boundary and roster-aware PII discipline, but return the shared result instead of `None`. Classification must be stage-aware: update the active bounded stage immediately before load/extract/persist/clarification/compute/delivery operations. Unclassified failures and ambiguous sends remain terminal.

**Clarification-as-success seam:** `app/pipeline/orchestrator.py:1020-1046`.

```python
if decision.final_action == "process":
    clarify_deferred = False
else:  # request_clarification
    ...
    clarification.clarify(...)
return _RunStagesResult(...)
```

The business action is not the transport outcome. A completed clarification branch returns `PipelineOutcome.OK`; never infer retryability from `Decision.final_action`.

### `app/routes/pipeline_glue.py` (temporary durable retry bridge)

**Background-wrapper pattern:** `app/routes/pipeline_glue.py:195-259`.

```python
def resume_pipeline_bg(run_id: uuid.UUID, inbound: InboundEmail) -> None:
    try:
        from app.pipeline.orchestrator import resume_pipeline
        resume_pipeline(run_id, inbound)
    except Exception:
        logger.exception("resume failed to start for run_id=%s", run_id)

def run_pipeline_bg(run_id: uuid.UUID) -> None:
    try:
        run_pipeline_now(run_id)
    except Exception:
        logger.exception("pipeline failed to start for run_id=%s", run_id)
```

Interpret the returned contract in all three background wrappers. `ok` and `terminal` do not loop in memory. `retryable` must atomically rewind the run to `received` and enqueue durable work. The initial wrapper enqueues `RUN_PIPELINE`; the reply wrapper enqueues `RESUME_REPLY` with persisted `email_id`; the operator wrapper accepts only `run_id + operator_resolution_id`, reloads the already committed complete mapping, and enqueues `OPERATOR_RESUME` deduped by that resolution UUID. The valid `/resolve` route creates the immutable UUID parent plus typed mapping rows before scheduling. Never key operator generations only by `reply_epoch`, reclassify the retry as terminal, or reconstruct it from partial `alias_candidates`.

**Persisted-email reconstruction pattern:** `app/routes/pipeline_glue.py:25-52` plus `app/db/repo/emails.py:351-372`.

```python
def row_to_inbound(row: dict[str, Any]) -> InboundEmail:
    return InboundEmail(
        id=row["id"],
        message_id=row["message_id"],
        ...
        body_text=row["body_text"],
        created_at=row["created_at"],
    )
```

Reuse persisted cleaned `body_text`; never reconstruct a resume retry from the original inbound or a redelivered request body. Update this helper's docstring to remove the deleted sweep caller while retaining webhook redelivery and the new durable resume handler.

### `app/models/job.py`, resume handlers, and `app/queue/dispatch.py`

**Kind/claim-projection contract:** `app/models/job.py:25-40` and `:64-87`.

Add `resume_reply` and `operator_resume` only with their real handlers and SQL CHECK values. Add `email_id` and `operator_resolution_id` to `Job` in the exact positions used by `claim_job ... RETURNING`; preserve the ordered bijection asserted by tests. Keep `Job` identifier-only: the durable resolution UUID selects typed authority, so no mapping/JSON payload belongs on the transport row.

**Handler pattern:** `app/queue/handlers/pipeline.py:109-159`.

```python
run_id = job.run_id
if run_id is None:
    raise ValueError(...)
if job.attempts > 1:
    rewound = repo.rewind_for_reclaim(run_id)
if not repo.claim_status(run_id, RunStatus.RECEIVED, RunStatus.EXTRACTING):
    return
pipeline_glue.run_pipeline_now(run_id)
```

Preserve missing-identifier loud failures and CAS-loser clean drops. The initial handler should return/propagate the `PipelineResult` to `drain_once()`. The reply handler requires `run_id` and `email_id`, loads the persisted inbound row, and calls `resume_pipeline(..., from_status=RECEIVED)`. The operator handler loads the immutable typed resolution by `(job.operator_resolution_id, run_id)`, proves exact key equality with `decision.unresolved_names` and employee membership in the run roster, and calls the same RECEIVED seam with the complete overrides. On attempts greater than one, both handlers use `rewind_for_reclaim` first without bumping `reply_epoch`.

**Dispatch pattern:** `app/queue/dispatch.py:21-44`.

```python
HANDLERS: dict[JobKind, tuple[ModuleType, str]] = {
    JobKind.RUN_PIPELINE: (pipeline, "handle_run_pipeline"),
}
...
module, name = entry
getattr(module, name)(job)
```

Keep module/name pairs rather than bound functions so monkeypatch seams stay live. Change `handle()`'s return annotation/forwarding if needed so the result reaches the drain; do not recreate a second classifier in dispatch.

### `app/db/schema.sql` (deployed CHECK widening)

**Inline jobs definition:** `app/db/schema.sql:464-492` currently accepts only `run_pipeline` and already reserves `email_id`.

**Idempotent CHECK replacement analog:** `app/db/schema.sql:297-323`.

```sql
DO $$
DECLARE
    _con RECORD;
BEGIN
    FOR _con IN
        SELECT c.conname
        FROM pg_constraint c
        WHERE c.contype = 'c'
          AND c.conrelid = 'email_messages'::regclass
          AND (...) = ARRAY['purpose']
    LOOP
        EXECUTE 'ALTER TABLE email_messages DROP CONSTRAINT ' || quote_ident(_con.conname);
    END LOOP;
    ALTER TABLE email_messages ADD CONSTRAINT email_messages_purpose_check
        CHECK (...);
END;
$$;
```

Use the same column-anchored, atomic drop-and-re-add pattern for `jobs.kind`; editing only the `CREATE TABLE IF NOT EXISTS` inline CHECK does not migrate deployed databases. Keep the Python enum canonical and SQL values set-equal. Extend per-kind constraints so `resume_reply` requires `run_id` plus `email_id` and `operator_resume` requires `run_id` plus `operator_resolution_id`.

Create `operator_resume_resolutions(id, run_id, created_at)` plus child `operator_resume_overrides(operator_resolution_id, submitted_name, employee_id, created_at)` after `jobs`, with history-preserving FKs and named indexes/constraints. The valid route inserts parent and all mapping rows before scheduling. Same resolution UUID plus identical mapping is idempotent; a later valid resolution gets a fresh UUID even in the same reply epoch. The handler loads by resolution/run and rejects missing/partial/extra/cross-business context with a bounded terminal context code.

### `app/db/schema_introspect.py` and `tests/test_schema_introspect.py`

Extend the existing explicit `ExpectedSchema.tables` and scripted live-query-order pattern for both operator-resolution tables and `jobs.operator_resolution_id`. Add named critical index/constraint inventory so an absent parent/child table, malformed key relationship, or missing parent run lookup reports `is_in_sync=False`. Plan 18-12 owns these files and must complete before handler/use Plans 18-09 and 18-03; Plan 18-03 atomically moves the valid `/resolve` persistence and identifier-only handoff with the wrapper signature change so no incompatible caller survives its task boundary.

### `app/db/repo/job_settlement.py` and `app/db/repo/jobs.py` (atomic settlement)

**Caller-owned transaction convention:** `app/db/repo/jobs.py:1-9`, `app/db/repo/_shared.py:19-48`.

```python
with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
    ...
```

Every lower-level write accepts `conn=None`; when the settlement coordinator passes a connection, it owns the single outer transaction. Do not call two helpers that each open unrelated transactions.

**Cross-aggregate atomic analog:** `app/routes/runs.py:392-420`.

```python
with repo.get_connection() as conn, conn.transaction():
    claimed = repo.claim_status(..., conn=conn) or ...
    if claimed:
        epoch = repo.clear_reply_context(run_id, conn=conn)
        repo.enqueue_job(..., conn=conn)
```

The new settlement seam must similarly commit job state plus run state together. Keep `jobs.py` transport-focused; put cross-aggregate policy in a focused coordinator module and export it through the facade. Its operator bridge reloads the already committed resolution, CASes the run back to `received`, and inserts identifier-only `OPERATOR_RESUME` deduped by resolution UUID. Duplicate same-resolution handling yields one job; two same-epoch resolution UUIDs yield two jobs.

**Fenced transport writes:** `app/db/repo/jobs.py:183-250`.

```sql
WHERE id = %s AND state = 'leased' AND lease_token = %s
RETURNING id
```

Worker settlement always fences on the exact token. For retryable results: fenced job `pending` + safe `last_error` + `available_at`, and CAS run `extracting -> received`, in one transaction. At cap: fenced job `dead` + CAS run to `error`, in one transaction. Terminal result: fenced job `done` + CAS run to `error` (not `dead`). A lost job fence or lost run CAS must become an explicit no-op/fenced result, not a partial commit.

**Run CAS analog:** `app/db/repo/runs.py:356-381`.

```sql
UPDATE payroll_runs SET status = %s, updated_at = now()
WHERE id = %s AND status = %s RETURNING id
```

Use a bounded terminal diagnostic, not raw exception/model text. Existing `_build_error_detail()` (`app/db/repo/runs.py:557-571`) is a scrubbed legacy analog, but D-02/D-08/D-11 are stricter: Phase 18 reason/stage/attempt fields should be formatted from enums and integers only.

### Final-attempt lease reaper and `app/queue/drain.py`

**Claim locking analog:** `app/db/repo/jobs.py:146-180` uses one `UPDATE`, a `FOR UPDATE SKIP LOCKED` selector, attempts-at-claim, and a returned typed job.

The reaper should follow that locking style but use the exact separate predicate:

```sql
state = 'leased'
AND attempts = max_attempts
AND leased_until < now()
```

It must lock/select one candidate, set the job dead, and CAS the associated run to error inside the same transaction. It does not require a current worker token: expiry plus row lock is its authority. Return a distinct typed settlement/reap result.

**Drain enum and loop seam:** `app/queue/drain.py:119-214`.

```python
class DrainOutcome(enum.StrEnum):
    EMPTY = "empty"
    DONE = "done"
    RETRIED = "retried"
    DEAD = "dead"
    FENCED = "fenced"

    def __bool__(self) -> bool:
        return self is not DrainOutcome.EMPTY
```

Add `REAPED_FINAL_LEASE` as truthy. Keep normal claim first; only when `claim_job()` returns `None`, attempt one reaper before returning `EMPTY`. That preserves worker draining and settles at most one abandoned row per call. Map handler `PipelineResult` through the atomic settlement seam; exceptions that escape dispatch still use the fenced infrastructure-failure path.

### `app/routes/pump.py` (truthful accounting)

**Current loop:** `app/routes/pump.py:92-115`.

```python
counts = dict.fromkeys(("done", "retried", "dead", "fenced"), 0)
claimed = 0
...
outcome = drain_once()
if outcome is DrainOutcome.EMPTY:
    break
claimed += 1
counts[outcome.value] += 1
```

The current unconditional `claimed += 1` is the exact line to change. For `REAPED_FINAL_LEASE`: increment `dead` and `reaped_final_lease`, but not `claimed`. Preserve the bounded loop and return:

```text
claimed == done + retried + (dead - reaped_final_lease) + fenced
```

### Runs list/detail and Retrigger

**Immutable-history/new-generation analog:** `app/routes/runs.py:392-426`.

Retrigger already claims the run to `received`, bumps `reply_epoch`, enqueues `run_pipeline:{run_id}:{epoch}` in the same transaction, commits, then wakes. Preserve that structure: never reopen a dead job row. Update stale comments that still describe the sweep or BackgroundTask-only recovery.

**List projection:** `app/db/repo/demo.py:142-174`.

```python
sql = (
    "SELECT pr.id, pr.business_id, pr.status, pr.created_at, pr.updated_at,"
    " b.name AS business_name,"
    ...
)
```

Add `pr.error_reason` (and only bounded fields needed for the secondary label) to this explicit projection. Mirror the same field in `InMemoryRepo.load_all_runs()` (`tests/conftest.py:571-600`).

**Status poll shaping:** `app/routes/runs.py:557-579` currently returns status/class/label. Add the bounded secondary exhaustion label so AJAX polling and initial rendering agree.

**List DOM update:** `app/templates/runs_list.html:19-31` and `:55-73`. Reuse the existing per-row badge update; add a dedicated secondary-label element/data field rather than replacing the real `error` status badge.

**Detail error/retrigger:** `app/templates/run_detail.html:66-71` and `:368-374`.

```html
{% if run.status == 'error' %}
<div class="banner banner-error banner-mb">
  <strong>Error</strong> — {{ run.error_reason }}.
  {% if run.error_detail %}<div class="banner-divider">{{ run.error_detail }}</div>{% endif %}
</div>
...
<form method="post" action="/runs/{{ run.id }}/retrigger">
```

Keep `error` as the real status and retain Retrigger. Add `Retries exhausted` as secondary bounded copy for ordinary exhaustion and `FinalAttemptLeaseExpired`, never as a new `RunStatus`.

### Sweep deletion: exact subtraction targets

**Reclaim/status preservation analogs:** `app/db/repo/pipeline_state.py::rewind_for_reclaim()` is the automatic-retry analog: it CASes eligible in-flight states back to RECEIVED while deliberately not bumping `reply_epoch`; `clear_reply_context()` is the human Retrigger analog and does bump the epoch. `app/models/status.py::RunStatus` remains the canonical business vocabulary: preserve ERROR/RECEIVED/NEEDS_OPERATOR and do not add a queue-derived status while deleting stale sweep prose.

**Retrigger regression analogs:** `tests/test_hitl.py` proves same-run durable enqueue, drain, epoch-keyed dedup, and a second fresh job generation. `tests/test_alias_and_run_column_regressions.py` proves all reply context is cleared and stale provenance cannot survive. `tests/test_retrigger_epoch.py` drives real clear/read seams to prove append-only email history is hidden by current-epoch reads rather than deleted. Plans 18-06 through 18-08 must preserve these behavioral analogs while narrowing only sweep-specific prose/cases.

Delete, do not rename or wrap:

- `app/db/repo/runs.py:384-436`: `_STRANDED_SCOPE_STATUSES` and `sweep_stranded_runs()`.
- `app/db/repo/emails.py:375-422`: `_STRANDED_REPLY_SCOPE_STATUS` and `find_stranded_unconsumed_replies()`.
- `app/db/repo/__init__.py:27-45,73-91,94-162`: both imports and both `__all__` entries; add any new settlement/reaper exports explicitly.
- `app/routes/runs.py:490-540`: remove the entire page-load mutation/scheduling block. `runs_list()` should retain only the guarded `load_all_runs()` read and render. Its `BackgroundTasks` parameter becomes unnecessary.
- `app/routes/pipeline_glue.py:25-40`: remove sweep-specific caller wording, not `row_to_inbound()` itself.
- `tests/conftest.py:511-533,1121-1150,1281-1307`: delete sweep fakes and patch names; retain/extend queue fakes.
- `tests/test_stuck_run_recovery.py:40-126,187-245,287-412`: delete sweep-preservation tests; keep unrelated `find_run_by_message_id` coverage or relocate it.
- `tests/test_reply_redelivery.py:255-335,392-421`: delete runs-list auto-resume cases; preserve webhook redelivery, sender validation, consumed-reply, and late-reply tests.
- `tests/test_needs_operator.py`: remove only assertions coupled to sweep symbol/scope; preserve the human-gate and route behavior.

`STALE_THRESHOLD` remains used by manual Retrigger (`app/routes/runs.py:269-350`); delete `STALE_THRESHOLD_SECONDS` if no caller remains, but do not remove the manual stale-in-flight policy.

## Test Pattern Assignments

### Contract/classification tests

Use the existing state-test structure in `tests/test_orchestrator_states.py:85-125` and clarification proof at `:198-225`: seed a fake run, drive the real entry point, assert both `PipelineResult` and authoritative run state. Replace the old assertion “stage raise sets error” with a matrix covering retryable SDK connection/timeout/429/5xx extraction failures, terminal schema/parse/4xx/unclassified/send failures, and `request_clarification -> ok` with one send.

For resume, follow `tests/test_resume_pipeline.py:244-282`: spy on the real seam and assert exactly one invocation. Add return-contract parity and persisted-reply-context assertions; a resume retry that reaches initial `run_pipeline` must fail.

### Static drift and SQL-shape tests

`tests/test_job_kind_drift.py:47-69,100-129,202-222` provides the set-equality pattern for Python kind ↔ SQL kind ↔ dispatch handler. Update its CHECK parser for the new deployed DO-block rather than leaving it pinned to an inline-only CHECK.

`tests/test_repo_jobs_sql.py:46-64` enforces ordered `RETURNING` ↔ dataclass equality; extend scripted rows and expected fields for `email_id` and `operator_resolution_id`. Its fence test (`:89-120`) demonstrates checking the `WHERE` clause specifically, not a vacuous substring in `SET lease_token = NULL`.

Use the AST/static guard style from `tests/test_queue_drain.py:678-725` for the negative sweep-symbol gate and queue status-writer inventory. Include a positive anti-vacuity assertion so a search that sees no files cannot pass.

### Hermetic drain/pump tests

Follow `tests/test_queue_drain.py:305-430`: seed one job, monkeypatch module-object seams, assert the exact `DrainOutcome`, exact token, job state, run state, and call count. Add cases for each pipeline result, below/at-cap retry settlement, lost job token, lost run CAS, and `REAPED_FINAL_LEASE` when normal claim returns empty.

Follow `tests/test_pump_route.py:89-104` for response-key and accounting assertions. Add `reaped_final_lease`; explicitly prove a reap increments `dead` and the subcount while `claimed` remains zero.

### Live transaction/fencing tests

Use `tests/test_queue_durability.py:415-490` as the lease-expiry and zombie-fence pattern: manipulate `leased_until` directly (no sleeps), claim/reap through real Postgres, and assert the exact persisted row. Add live proofs for:

1. retry settlement commits job `pending` and run `received` together;
2. at-cap settlement commits job `dead` and run `error` together;
3. an injected half-failure rolls both writes back;
4. stale lease-token settlement cannot clobber either aggregate;
5. exact final-attempt expiry is reaped, while attempts-below-cap and unexpired final leases are not;
6. lost run CAS is a deliberate fenced/no-op outcome;
7. terminal result settles job `done` and run `error`.
8. valid route persistence commits an immutable resolution parent plus complete mapping before scheduling; operator retry commits run `received` plus identifier-only job referencing it, duplicate same-resolution handling yields one job, and two same-epoch resolutions yield distinct jobs.

Keep these under the existing queueproof/integration markers and never call a real LLM/provider.

### UI and deletion gates

Follow the end-to-end key-link test in `tests/test_dashboard.py:396-442`: prove the explicit list/detail query carries the bounded exhaustion data and that the rendered HTML displays the secondary label plus Retrigger.

Invert the old sweep-wiring test (`tests/test_stuck_run_recovery.py:187-223`). Patch every mutating/scheduling repo or queue seam to raise if called, patch `load_all_runs()` to return rows, request `GET /runs`, and assert 200 plus the expected render. This directly proves side-effect-free GET.

Delete runs-list auto-resume tests (`tests/test_reply_redelivery.py:260-335`) but retain webhook redelivery tests. Keep `tests/test_fake_repo_pairing.py:28-55` green by adding every new fake settlement/reaper method to the patch tuple and deleting removed sweep mirrors from both places.

## Shared Patterns

### Transaction ownership

One top-level operation owns one transaction and passes `conn` through every participating repository call. `_conn_ctx(conn)` plus `_nulltx()` is the project-wide joinable helper convention. Never hold that transaction across LLM/provider execution.

### Fencing and CAS

- Worker job writes: exact `lease_token` fence.
- Run writes: one-statement status CAS with `RETURNING`.
- Reaper authority: expired final-attempt predicate plus `FOR UPDATE SKIP LOCKED`.
- Any lost fence/CAS: drop cleanly; never “repair” with an unconditional second write.

### Diagnostics

Persist only bounded stage/reason/attempt values. Log correlation by `run_id`/job id and type/code, not raw exceptions, model output, email bodies, names, or provider responses. `FinalAttemptLeaseExpired` must replace—not reinterpret—any earlier `last_error` when explaining a reaped final lease.

### Transport/business separation

`JobState` remains transport-only and `RunStatus` remains business-only. `dead` is for retry exhaustion/reaping; an explicitly terminal pipeline result means transport completed (`done`) while the run becomes `error`. Never add a queue-derived run status.

### Verification split

- Hermetic tests prove return mapping, SQL shape, drift, routing, templates, and counts.
- Live Postgres tests prove atomicity, locking, exact predicates, rollback, and zombie fencing.
- Every negative/static guard needs a positive anti-vacuity companion or a behavioral route proof.

## Planning Warnings

1. Do not enqueue a resume retry as `run_pipeline`; it loses the client's persisted clarification reply.
2. Do not edit only the jobs table's inline CHECK; deployed tables ignore `CREATE TABLE IF NOT EXISTS` changes.
3. Do not split job dead-letter and run error writes across transactions or plans.
4. Do not count a reaped row as claimed.
5. Do not retry ambiguous clarification/delivery sends before Phase 20 idempotency.
6. Do not delete webhook redelivery or manual Retrigger behavior while deleting dashboard sweep recovery.
7. Do not touch the unrelated `.planning/ROADMAP.md` modification.
8. Do not convert retryable operator-resume provider failures to terminal; persist the complete validated mapping in typed rows and enqueue `OPERATOR_RESUME`.
