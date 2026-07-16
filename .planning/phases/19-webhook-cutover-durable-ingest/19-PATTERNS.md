# Phase 19: Webhook Cutover & Durable Ingest - Pattern Map

**Mapped:** 2026-07-16
**Files classified:** 38 new or modified files
**Analogs found:** 37 / 38
**Scope:** QUEUE-04 only; Phase 20 provider-send idempotency and Phase 21 queue operations remain deferred.

## File Classification

| New/Modified File | Role | Data Flow | Closest Existing Analog | Match Quality |
|---|---|---|---|---|
| `app/db/schema.sql` | migration/config | CRUD + event-driven | Existing jobs/operator DDL at lines 452-663 | exact |
| `app/db/bootstrap.py` | config | destructive reset ordering | `_DROP_ORDER` at lines 74-96 | exact |
| `app/db/schema_introspect.py` | config/health | schema introspection | required catalog maps and `expected_schema()` at lines 38-76, 186-221 | exact |
| `scripts/check_operator_resolution_inventory.py` and `scripts/migrate_operator_resolution_authority.py` (new) | deployment safety | read-only inventory + guarded data migration | existing Settings/psycopg operational CLI boundary plus caller-owned transaction/row-lock patterns | role-match |
| `app/models/job.py` | model | event-driven | `JobKind`/identifier-only `Job` at lines 25-89 | exact |
| `app/db/repo/inbound_events.py` (new) | repository/store | CRUD + event-driven | `runs.insert_inbound_email` at lines 62-106 plus `jobs.enqueue_job` at lines 55-159 | role-match |
| `app/db/repo/__init__.py` | provider/facade | module API | explicit imports and `__all__` at lines 17-150 | exact |
| `app/db/repo/jobs.py` | repository/store | event-driven | caller-owned idempotent enqueue at lines 55-159 | exact |
| `app/db/repo/job_settlement.py` | service/repository | event-driven + transactional settlement | fenced run-associated settlement at lines 295-373 and reaper at lines 419-457 | exact seam, new transport branch |
| `app/db/repo/operator_resume_resolutions.py` | repository/store | CRUD + concurrency | immutable generation create/load at lines 74-137 | exact |
| `app/db/repo/runs.py` | repository/store | CRUD projection | explicit bounded `RUN_COLS` at lines 20-42 and CAS at lines 356-381 | role-match |
| `app/db/repo/demo.py` | repository/store | read projection | bounded list query at lines 142-182 | exact |
| `app/queue/dispatch.py` | service/router | event-driven | module/name handler registry at lines 25-50 | exact |
| `app/queue/handlers/ingest.py` (new) | service/consumer | event-driven | `resume_reply.py` lines 47-82 and `operator_resume.py` lines 70-104 | role-match |
| `app/queue/handlers/resume_reply.py` | service/consumer | event-driven | its existing durable rehydration at lines 47-82 plus shared sender guard | exact |
| `app/queue/handlers/operator_resume.py` | service/consumer | event-driven | its existing immutable-context validation at lines 40-104 | exact |
| `app/routes/webhook.py` | controller/route | request-response -> event | current auth ordering at lines 289-350; DATA-02 transaction at lines 136-218 | exact seam |
| `app/routes/demo.py` | controller/route | request-response -> event | `runs.retrigger` caller-owned transaction at lines 539-573 | exact transaction analog |
| `app/routes/runs.py` | controller/route | request-response -> event | `retrigger` at lines 539-573; current resolution lock at lines 374-419 | exact |
| `app/routes/pipeline_glue.py` | utility/service | transform + authorization | `row_to_inbound` lines 35-62 and `reply_sender_ok` lines 65-87 | exact |
| `app/templates/runs_list.html` | component | polling/request-response | current in-place poller at lines 3-50 and badge cell at lines 67-75 | exact |
| `app/templates/run_detail.html` | component | polling/request-response | current reload-on-transition poller at lines 7-64 | exact |
| `app/static/style.css` | component/style | presentation | tokens lines 5-50 and badges lines 243-301 | exact |
| `tests/conftest.py` | fake/provider | in-memory event flow | queue mirror lines 759-846 and patch inventory lines 1496-1587 | exact |
| `tests/test_durable_ingest.py` (new) | test | request-response + event-driven | webhook tests plus queue durability matrix | role-match |
| `tests/test_webhook_unblocked.py` | test | request-response | current non-blocking/auth webhook tests | exact |
| `tests/test_webhook.py` | test | request-response + ingest outcomes | current five-outcome webhook coverage | exact |
| `tests/test_webhook_dedup_race.py` | test | concurrency/CRUD | existing RFC Message-ID race proof | exact |
| `tests/test_reply_redelivery.py` | test | event-driven | persisted redelivery and sender-guard coverage | exact |
| `tests/test_queue_durability.py` | test | live event-driven/concurrency | existing lease/settlement/reaper proofs | exact |
| `tests/test_queue_drain.py` | test/architecture guard | event-driven + AST batch scan | fail-closed queue-tier scanner at lines 11-37, 1332-1391 | exact |
| `tests/test_resume_pipeline.py` | test | event-driven authorization | current resume rehydration/sender tests | exact |
| `tests/test_needs_operator.py` | test | concurrency + request-response | current complete mapping/resolution tests | exact |
| `tests/test_demo_landing.py` and `tests/test_demo_fixtures.py` | tests | request-response -> event | existing demo route tests | exact |
| `tests/test_job_kind_drift.py` | test/config guard | static schema/dispatch drift | set-equality guards at lines 100-129, 202-241 | exact |
| `tests/test_repo_jobs_sql.py` and `tests/test_schema_introspect.py` | tests | SQL shape/schema health | enqueue/context checks at lines 161-272; catalog assertions at lines 17-87 | exact |
| `tests/test_operator_resolution_inventory.py` and `tests/test_operator_resolution_migration.py` (new) | tests | deployment contract + transaction safety | scripted fake-connection SQL-shape tests and guarded repository migration checks | role-match |
| `tests/test_fake_repo_pairing.py` and `tests/test_dashboard.py` | tests/architecture guard | AST inventory + UI request-response | fake pairing at lines 120-185; current bounded dashboard projections | exact |

## Pattern Assignments

### Queue contract: `schema.sql`, `models/job.py`, `repo/jobs.py`, `dispatch.py`

Widen the SQL check, Python enum/dataclass, enqueue validation, claim `RETURNING`, handler registry, fake, and drift tests as one commit. The current files explicitly require atomic widening.

**Identifier-only model pattern** — `app/models/job.py:66-89`:

```python
@dataclasses.dataclass(frozen=True, kw_only=True)
class Job:
    id: uuid.UUID
    kind: JobKind
    run_id: uuid.UUID | None
    email_id: uuid.UUID | None = None
    operator_resolution_id: uuid.UUID | None = None
    attempts: int
    max_attempts: int
    lease_token: uuid.UUID
```

Add `event_id` as another persisted identifier. Do not add an envelope, reply body, mapping, next status, or generic payload.

**Caller-owned, idempotent enqueue pattern** — `app/db/repo/jobs.py:127-159`:

```python
with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
    row = c.execute(
        """INSERT INTO jobs (...) VALUES (...)
           ON CONFLICT (dedup_key) DO NOTHING
           RETURNING id""",
        params,
    ).fetchone()
return None if row is None else uuid.UUID(str(row[0]))
```

The ingest context must be exact: `event_id IS NOT NULL` and `run_id`, `email_id`, `operator_resolution_id`, and business payload fields absent. Terminal retention may set `event_id` null only if the SQL context check explicitly permits that terminal state.

**Module-object dispatch pattern** — `app/queue/dispatch.py:29-50`:

```python
HANDLERS = {
    JobKind.RUN_PIPELINE: (pipeline, "handle_run_pipeline"),
    JobKind.RESUME_REPLY: (resume_reply, "handle_resume_reply"),
    JobKind.OPERATOR_RESUME: (operator_resume, "handle_operator_resume"),
}
module, name = HANDLERS[job.kind]
return normalize_pipeline_result(getattr(module, name)(job))
```

Import the new `ingest` module and register `(ingest, "handle_ingest")`; do not bind the function object early because monkeypatch seams depend on runtime attribute lookup.

**Live-safe DDL pattern** — `app/db/schema.sql:600-663`: use additive `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, catalog-anchored CHECK replacement, and guarded FK installation. Update the initial CREATE and live migration together. Preserve reverse-dependency reset order by placing `inbound_events` immediately after `jobs` in `app/db/bootstrap.py::_DROP_ORDER`: the referencing `jobs` table must be dropped before its referenced target. Register the table/index/FK in `schema_introspect.py` following lines 38-76 and 186-221.

### Durable inbox: `repo/inbound_events.py`, facade, retention

**Closest analog:** `app/db/repo/runs.py:62-106`.

```python
with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
    row = c.execute(
        """INSERT INTO email_messages (...)
           VALUES (...)
           ON CONFLICT (message_id) DO NOTHING
           RETURNING id""",
        params,
    ).fetchone()
if row is None:
    return None, False
return uuid.UUID(str(row[0])), True
```

Apply this repository convention to `inbound_events`: parameterized SQL, optional `conn`, explicit columns, stable lookup of the existing internal UUID on external Svix-key conflict, and no raw exception projection. The accept operation must create the event and `ingest:{event_id}` job in one caller-owned transaction. A post-commit wake is acceleration only.

The 30-day terminal-only purge has no exact repository analog; use the established `_conn_ctx`/parameterized SQL style, but derive the predicate from the locked retention contract: delete only old events with no pending/leased ingest dependency, preserve the terminal job audit through `ON DELETE SET NULL`, and never pull a Phase 21 scheduler or operations screen into this phase.

Export each new repository function through `app/db/repo/__init__.py` in both its import block and `__all__`, mirroring lines 17-150.

### Moved DATA-02 transaction: `queue/handlers/ingest.py` and `routes/webhook.py`

Do not redesign the outcome ordering. The canonical current transaction is `app/routes/webhook.py:136-218`:

```python
with repo.get_connection() as conn, conn.transaction():
    email_id, inserted = repo.insert_inbound_email(..., conn=conn)
    if not inserted:
        outcome = "duplicate"
    elif email.in_reply_to or email.references_header:
        reply_run_id = repo.find_awaiting_reply_for_header(..., conn=conn)
        if reply_run_id is not None:
            outcome = "reply_candidate"
            repo.link_email_to_run(email_id, reply_run_id, conn=conn)
        else:
            late_run_id = repo.find_any_run_for_header(..., conn=conn)
            # late_reply, unknown_sender, or new_run
    else:
        # unknown_sender or new_run
```

Preserve the five outcomes exactly: duplicate, reply candidate, late reply, unknown sender, new run. The only internal change is that an owed `resume_reply` or `run_pipeline` job is enqueued with `conn=conn` before commit. The handler loads `job.event_id`, loads the persisted verified envelope, calls `gateway.parse_inbound` later, and returns a bounded `PipelineResult`.

Follow the handler fail-closed shape in `app/queue/handlers/resume_reply.py:47-82`: validate every required identifier, load exact durable context, treat invalid/advanced state as bounded no-op, and let retryable infrastructure failures propagate to settlement. Do not log provider bodies, sender addresses, submitted names, or mappings.

The webhook route retains the current verify-before-parse ordering at `app/routes/webhook.py:320-350`, but replaces `await request.body()` with the approved 256 KiB bounded stream. After verification, parse only the minimal transport envelope, atomically accept event+job, commit, wake, and return only `{status, event_id}`. Delete the body fetch, DATA-02 business transaction, run ID response, and every `BackgroundTasks` parameter/add call from the route.

### Null-run settlement and reaping: `repo/job_settlement.py`

The current run-associated coordinator locks the exact leased row and fence at `app/db/repo/job_settlement.py:295-373`. Reuse that fence and bounded `PipelineResult`, but branch by job kind before requiring a run:

```python
locked = _locked_job(c, job)
if locked is None:
    return SettlementOutcome.FENCED
attempts, max_attempts, stored_run_id = locked
```

For `ingest`, success marks the job done; retryable failure reschedules or dead-letters it; neither path writes `payroll_runs`. The existing final-attempt reaper currently does this at `app/db/repo/job_settlement.py:419-457`:

```python
run_id = uuid.UUID(str(row[1])) if row[1] is not None else None
if run_id is None:
    return SettlementOutcome.FENCED
```

That exact null-run fence is the Phase 19 bug seam. Replace it with a kind-aware transport-only dead-letter branch for expired final-attempt ingest leases while preserving the existing run-associated status policy unchanged.

### Durable reply seam and sender revalidation

Rehydrate from the persisted row using `app/routes/pipeline_glue.py:35-62`; never rebuild from the redelivered request or re-clean the body.

The shared authorization predicate is `app/routes/pipeline_glue.py:65-87`:

```python
reply_business_id = repo.find_business_by_sender(row.get("from_addr") or "")
return reply_business_id is not None and str(reply_business_id) == str(
    run.get("business_id")
)
```

Call this on every durable `resume_reply` attempt after verifying the email belongs to the job's run and before `row_to_inbound` or orchestration. Sender mismatch and cross-run context are intentional bounded no-ops. Do not use `job.attempts` as authorization or as the sole first-delivery test; authoritative stored status/CAS controls whether work may resume.

Delete the durable-path dependence on `finish_reply_resume`, `route_reply(..., BackgroundTasks)`, `resume_pipeline_bg`, `run_pipeline_bg`, and `operator_resume_bg`. If small pure helpers remain useful, keep module-object imports so existing monkeypatch seams stay live.

### Atomic producer cutover: `routes/demo.py`, `routes/runs.py`

Copy the proven retrigger transaction at `app/routes/runs.py:539-573`:

```python
with repo.get_connection() as conn, conn.transaction():
    claimed = ...
    if claimed:
        epoch = repo.clear_reply_context(run_id, conn=conn)
        repo.enqueue_job(..., conn=conn)
if claimed:
    wake.wake()
```

Apply it to both demo routes: inbound email + run + `run_pipeline` job share one transaction, then wake after commit and redirect to `/runs/{run_id}`. Rollback must leave no email, run, or job and redirect with only the approved retry notice.

Apply it to reply classification/simulation and operator resolution: domain state and owed job are co-tenants. `app/routes/demo.py:182-206` and `291-317` show the rows currently created before process-memory scheduling; move those exact writes under one connection and replace `.add_task()`.

### First-commit operator authority and winner-only alias learning

The route already serializes on the run row at `app/routes/runs.py:374-401`:

```python
with repo.get_connection() as conn, conn.transaction():
    conn.execute(
        "SELECT id FROM payroll_runs WHERE id = %s FOR UPDATE",
        (str(run_id),),
    )
    current = repo.load_run(run_id, conn=conn)
    repo.create_operator_resume_resolution(..., conn=conn)
```

Move this responsibility into the operator-resolution repository so commit-serialized authority, immutable generation creation, supersession, remember intent, and enqueue happen under one repository transaction. The existing immutable/idempotent parent-child insert is `app/db/repo/operator_resume_resolutions.py:74-121`; extend it instead of inventing transient override dictionaries.

The current route projects alias candidates before worker authority is known at `app/routes/runs.py:402-411`. Remove that write. Persist `remember` per override row; only an authoritative generation's handler/repository preparation may project alias candidates. A superseded generation and job remain audit records, and its handler returns OK/no-op before any payroll or alias mutation. Return only a bounded loser flag to select the approved redirect notice.

### Bounded queue projection and browser safety

Extend the explicit list query pattern in `app/db/repo/demo.py:161-182`, not the Phase 21 operations surface:

```python
SELECT pr.id, pr.business_id, pr.status, ...
FROM payroll_runs pr
LEFT JOIN LATERAL (
  SELECT ... FROM jobs j WHERE j.run_id = pr.id ...
) latest_job ON TRUE
ORDER BY pr.created_at DESC
```

Project exactly one safe label with precedence: leased -> `Running`; otherwise due pending -> `Queued`; otherwise delayed pending -> `Retry queued`. Do not expose IDs, attempts, timestamps, or diagnostics. Add the same bounded projection to detail and `/status`.

Pass it through the hostile-data scrub boundary modeled by `app/routes/runs.py:198-210`, which copies the row, builds a bounded presentation, and removes raw fields before template/JSON use.

**List polling analog** — `app/templates/runs_list.html:14-49`: update badges in place and preserve controls/scroll.

**Detail polling analog** — `app/templates/run_detail.html:15-62`: reload once on meaningful state change. Change the cap from 30 to 60 attempts, continue while either business status is in flight or an open-job projection exists, and never enqueue or retrigger on timeout.

Render the queue badge beside the primary badge and the exact durability copy only while open work exists. Give the live queue badge/note container `aria-live="polite"`. Reuse `style.css` tokens at lines 5-50 and badge rules at lines 243-301; `Running` may use the soft indigo treatment, while `Queued`/`Retry queued` stay neutral.

### Fake parity, schema drift, and architecture guards

Every new facade method needs a fake implementation and patch-list entry. The exact in-memory queue analog is `tests/conftest.py:759-846`, and the patch inventory is `tests/conftest.py:1496-1587`.

Keep the fail-closed pairing proof in `tests/test_fake_repo_pairing.py:120-185`: it verifies facade methods resolve back to the active fake rather than silently calling the real DB.

Keep set equality, never subset checks:

```python
# tests/test_job_kind_drift.py:103-115, 219-233
assert sql_values == {m.value for m in JobKind}
assert {m.value for m in JobKind} == set(dispatch.HANDLERS.keys())
```

Extend SQL-shape tests after `tests/test_repo_jobs_sql.py:161-272` for ingest identifier validation, parameterization, `ON CONFLICT`, and the claim dataclass bijection. Extend `tests/test_schema_introspect.py:17-87` for `inbound_events`, `jobs.event_id`, retention index, authority uniqueness, remember columns, and FK shapes.

For the complete producer cutover, copy the non-vacuous source inventory style from `tests/test_fake_repo_pairing.py:67-117`: assert the scanned inventory is nonempty, scan all production Python routes/pipeline helpers, reject `BackgroundTasks` imports/parameters and pipeline `.add_task()` calls, and include a synthetic positive proof that the scanner detects a reintroduction. Do not rely on `rg` output or a vacuously green AST result.

## Shared Patterns

### Caller-Owned Transactions

**Source:** `app/db/repo/jobs.py:127-159`, `app/routes/runs.py:539-573`

All state that creates owed work and the job itself share one transaction. Repository functions accept `conn`; they open a transaction only when they own the connection. Wake strictly after commit.

### Lost-Race Semantics

**Source:** `app/db/repo/runs.py:356-381`, `app/queue/handlers/pipeline.py:145-157`

A failed CAS, superseded authority, duplicate event, or advanced business state is a bounded successful no-op when another actor already owns the result. Do not raise, re-enqueue, or write a payroll error for a lost race.

### PII-Safe Errors and Browser Projection

**Source:** `app/db/repo/jobs.py:278-305`, `app/routes/runs.py:140-210`

Persist bounded stage/reason codes only; templates and JSON receive fixed labels, never raw exception strings, event bodies, sender addresses, submitted mappings, job IDs, or attempts.

### Module-Object Monkeypatch Seams

**Source:** `app/queue/dispatch.py:1-17`, `app/routes/webhook.py:67-72`

Import modules and resolve functions as attributes at call time. Pair every facade addition with the fake and the patch inventory.

### Queue/Business-State Separation

**Source:** `app/models/job.py:1-16`, `app/db/repo/jobs.py:11-15`

Jobs describe transport work only. `payroll_runs.status` remains the sole payroll business state; no `queued` RunStatus, business payload, or next-status field is permitted.

## No Exact Analog Found

| File/Capability | Role | Data Flow | Reason / Research Fallback |
|---|---|---|---|
| `app/db/repo/inbound_events.py` terminal-only 30-day purge | repository/retention | batch CRUD | No current raw inbox retention executor exists. Use the repository transaction/SQL conventions above and the retention-safe FK/predicate from `19-RESEARCH.md`; do not add a scheduler or operations UI. |

## Deferred Scope Fence

- Phase 20 owns provider-side exactly-once confirmation send and retry-window proof. Phase 19 must not redesign outbound send idempotency.
- Phase 21 owns queue depth/age operations UI, dead-letter views, alarms, diagnostics, manual job retry, final CI registration, and red-run proof packaging.
- Phase 19 may expose only the three bounded per-run labels and durability copy approved in `19-UI-SPEC.md`.
- Paystub, eval-chart, and broad progressive-enhancement todos remain outside this phase.

## Metadata

**Analog search scope:** `app/db`, `app/models`, `app/queue`, `app/routes`, `app/templates`, `app/static`, and focused queue/webhook/dashboard tests.
**Strong analog clusters:** 5 (queue contract, transactional producer, handler/settlement, operator authority, bounded UI/test guards).
**Pattern extraction date:** 2026-07-16
**Operational dispatch:** Generic-agent workaround for the installed `gsd-pattern-mapper` role; typed GSD agent dispatch was unavailable. This affects orchestration metadata only.
