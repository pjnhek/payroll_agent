# Phase 9: Atomic Data Integrity - Pattern Map

**Mapped:** 2026-07-03
**Files analyzed:** 6 modified, 3 new (test files)
**Analogs found:** 9 / 9 (every touch point already has an established in-repo idiom — this phase is 100% wiring, no new pattern vocabulary)

This phase modifies existing files rather than creating new modules (per RESEARCH.md
"Recommended Project Structure" — no new app/ files). The "analog" for each modified
file is therefore **the file's own existing sibling helpers** — the closest precedent
already lives a few lines away in the same file. Test files are the only new files
and their closest analog is `tests/test_claim_status.py` (the only existing test that
already does live-DB CAS/concurrency proof work).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|-----------------|---------------|
| `app/db/repo.py` — NEW `sweep_stranded_runs()` | repository/CRUD helper | CRUD (single CAS UPDATE) | `app/db/repo.py::claim_status` (:354-379) | exact — same CAS-UPDATE-WHERE-RETURNING shape |
| `app/db/repo.py` — NEW `find_run_by_message_id()` (corrected per round-1 checker BLOCKER 1 — supersedes the earlier `find_run_by_source_email` draft; see 09-01-PLAN.md) | repository/CRUD helper | CRUD (read) | `app/db/repo.py::find_business_by_sender` (:187-210) | exact — same single-lookup-by-column shape (joined through `email_messages`, not a direct column) |
| `app/pipeline/orchestrator.py` — `_run_stages` (MODIFY, wrap persist sequence :868-895) | service/orchestrator | transform + CRUD (multi-write transaction) | `app/db/repo.py::record_run_error` (:514-586) — the one existing multi-step-then-status-write sequence already inside one function | role-match (CAS-then-status idiom, extended to a longer write sequence) |
| `app/pipeline/orchestrator.py` — `_clarify` (MODIFY, wrap finalize writes :1074-1077 and snapshot ordering) | service/orchestrator | event-driven (LLM + provider side effect, then DB finalize) | `app/email/gateway.py::send_outbound` (:182-311) — the existing reserved-before-send/flip-after-send split | exact — D-9-06/D-9-07 explicitly model this split on send_outbound's own D-13c lifecycle |
| `app/pipeline/orchestrator.py` — `_deliver` (MODIFY, wrap finalize writes :1288-1304) | service/orchestrator | event-driven (provider send, then DB finalize) | `app/email/gateway.py::send_outbound` (:182-311) | exact — same reserved/finalize split, one level up the call stack |
| `app/main.py` — `inbound()` webhook route (MODIFY, wrap ingest sequence :311-354) | controller/route | request-response + CRUD (dedup insert + read + create) | `app/main.py::retrigger` (:534-613) — the existing CAS-claim-then-background-task route | role-match (both are routes that CAS/insert then conditionally `background_tasks.add_task`) |
| `app/main.py` — `runs_list()` (MODIFY, call sweep before load :865-884) | controller/route | request-response (read, with a pre-read side effect) | `app/main.py::runs_list` itself (existing, minimal change) | exact — trivial one-line addition before the existing `repo.load_all_runs()` call |
| `tests/test_atomic_persist.py` (NEW) | test | integration (fault-injection, real DB) | `tests/test_claim_status.py::test_claim_status_concurrent_calls_exactly_one_true` (:158-176) for the `@pytest.mark.integration` skip-guard shape; RESEARCH.md Pattern 2 for the fault-injection body | role-match |
| `tests/test_webhook_dedup_race.py` (NEW) | test | integration (threaded race, real DB) | `tests/test_claim_status.py::test_claim_status_concurrent_calls_exactly_one_true` (:158-176) | exact — RESEARCH.md explicitly derives this test from that stub's own comment |
| `tests/test_stuck_run_recovery.py` (NEW) | test | unit + integration (CAS scope assertion + sweep/retrigger interplay) | `tests/test_claim_status.py` (whole file, :1-176) for both the FakeConnection unit-test shape (`test_claim_status_sql_contains_where_status_and_returning`, :80-106) and the integration skip-guard shape | exact |

## Pattern Assignments

### `app/db/repo.py` — NEW `sweep_stranded_runs()` (repository, CRUD/CAS)

**Analog:** `app/db/repo.py::claim_status` (lines 354-379) and `record_run_error`'s WR-03 CAS fix (lines 565-577)

**The `_conn_ctx` + transaction-or-nulltx seam every helper in this file already uses** (lines 125-133):
```python
@contextlib.contextmanager
def _conn_ctx(conn):
    """Yield (conn, owns): use the caller's conn, or open a pooled one we own."""
    if conn is not None:
        yield conn, False
    else:
        with get_connection() as owned:
            yield owned, True
```

**The CAS-UPDATE-WHERE-RETURNING idiom to copy exactly** (`claim_status`, lines 354-379):
```python
def claim_status(
    run_id: uuid.UUID,
    expected: RunStatus,
    new: RunStatus,
    conn=None,
) -> bool:
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                "UPDATE payroll_runs SET status = %s, updated_at = now() "
                "WHERE id = %s AND status = %s RETURNING id",
                (RunStatus(new).value, str(run_id), RunStatus(expected).value),
            ).fetchone()
    return row is not None
```

**The multi-row array-scoped CAS variant to copy** (`record_run_error`'s WR-03 guard, lines 565-586 — this is the closer shape since the sweep also uses `status <> ALL(%s)` / `status = ANY(%s)` array parameterization, not a single-value equality):
```python
with _conn_ctx(conn) as (c, owns):
    with c.transaction() if owns else _nulltx():
        row = c.execute(
            "UPDATE payroll_runs SET error_reason = %s, error_detail = %s,"
            " updated_at = now() WHERE id = %s AND status <> ALL(%s)"
            " RETURNING id",
            (reason, detail, str(run_id), sorted(_TERMINAL_STATUSES)),
        ).fetchone()
        if row is None:
            logger.info(...)
            return
        set_status(run_id, RunStatus.ERROR, conn=c)
```

**Write it as (RESEARCH.md Pattern 5, already drafted — copy verbatim, it already matches this file's idiom):**
```python
def sweep_stranded_runs(threshold_seconds: int, conn=None) -> list[uuid.UUID]:
    """D-9-10/11/12: mark runs stranded in-flight (background task died) as ERROR.

    Scope is EXACTLY {received, extracting, computed} (D-9-12) — never
    awaiting_reply/awaiting_approval/approved, which are legitimately parked.
    Single CAS statement (claim_status idiom) — no read-then-write race.
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            rows = c.execute(
                """
                UPDATE payroll_runs
                SET status = %s, error_reason = %s, error_detail = %s, updated_at = now()
                WHERE status = ANY(%s)
                  AND updated_at < now() - (%s || ' seconds')::interval
                RETURNING id
                """,
                (
                    RunStatus.ERROR.value,
                    "StrandedRunSwept",
                    "recovery: stranded in-flight (background task died) — swept",
                    ["received", "extracting", "computed"],
                    str(threshold_seconds),
                ),
            ).fetchall()
    return [uuid.UUID(str(r[0])) for r in rows]
```

**Placement:** goes in the `# Status / persistence` section of repo.py (after `claim_status`, line 380, before the PII-scrub block) — same section as its two closest siblings.

---

### `app/db/repo.py` — NEW lookup for the webhook loser's "existing run" (repository, CRUD read)

**Analog:** `find_business_by_sender` (lines 187-210) — the established shape for "single lookup by a foreign column, returns `uuid.UUID | None`, no transaction needed (read-only)."

```python
def find_business_by_sender(from_addr: str, conn=None) -> uuid.UUID | None:
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT id FROM businesses WHERE contact_email = %s",
            (from_addr,),
        ).fetchone()
        if row is not None:
            return uuid.UUID(str(row[0]))
        ...
        return uuid.UUID(str(binding_row[0])) if binding_row else None
```

**Corrected per round-1 checker BLOCKER 1** (the original `find_run_by_source_email(email_id, ...)`
draft is dead — `repo.insert_inbound_email` returns `(None, False)` on conflict, so the loser
never has an `email_id` to pass): the helper is `find_run_by_message_id(message_id: str,
conn=None) -> uuid.UUID | None`, joining `email_messages` (on `message_id`, `uq_message_id`
UNIQUE) to `payroll_runs` (via `payroll_runs.source_email_id = email_messages.id`) — same
no-transaction read-only shape as `find_business_by_sender`, called **inside** the same
ingest transaction as the loser (so it observes a consistent snapshot after the winner's
commit/rollback resolves). Built in 09-01; see `09-01-PLAN.md` for the exact SQL and
`09-01-SUMMARY.md` for its as-implemented shape.

---

### `app/pipeline/orchestrator.py` — `_run_stages` process branch (orchestrator, CRUD transaction)

**Analog for the wrapping mechanism:** the `_conn_ctx`/`conn.transaction()` seam (repo.py:125-133), threaded through via `conn=` kwargs already accepted by every helper called here.

**Existing sequence to wrap (lines 868-895 — UNCHANGED call order, ADD the transaction envelope around it):**
```python
# --- persist DATA on EVERY run BEFORE branching (D-A3-05); OVERWRITES on resume ---
repo.persist_extracted(run_id, extracted)
repo.persist_decision(run_id, decision)  # data-only (FIX B), two-arg call
repo.persist_reconciliation(run_id, matches)  # never NULL on a clean run

# --- branch SOLELY on final_action (the code-owned deterministic decision) ---
clarify_deferred = False
if decision.final_action == "process":
    line_items = _compute_line_items(run_id, extracted, matches, roster)
    repo.replace_line_items(run_id, line_items)  # DELETE-by-run then insert
    repo.set_status(run_id, RunStatus.COMPUTED)
    repo.set_status(run_id, RunStatus.AWAITING_APPROVAL)  # HITL-01 pause
    clarify_deferred = False
else:  # request_clarification
    ...
```

**Target shape per D-9-04 / RESEARCH.md Pattern 1 (open ONE connection, pass `conn=` through every repo call, status-advance-last per D-9-02):**
```python
with get_connection() as conn:
    with conn.transaction():
        repo.persist_extracted(run_id, extracted, conn=conn)
        repo.persist_decision(run_id, decision, conn=conn)
        repo.persist_reconciliation(run_id, matches, conn=conn)
        if decision.final_action == "process":
            line_items = _compute_line_items(run_id, extracted, matches, roster)  # pure — already computed BEFORE the txn per D-9-04
            repo.replace_line_items(run_id, line_items, conn=conn)
            repo.set_status(run_id, RunStatus.COMPUTED, conn=conn)
            repo.set_status(run_id, RunStatus.AWAITING_APPROVAL, conn=conn)  # LAST (D-9-02)
```
Note: `_compute_line_items` is pure (no DB/LLM) — D-9-04 requires it run BEFORE the transaction opens so a calc exception never opens a doomed txn; keep it exactly where it already is in the call sequence (line 876), just ensure no repo write happens before it.

**Error propagation — nothing to change here.** `conn.transaction()` re-raises any exception it catches after rolling back (RESEARCH.md verified psycopg3 semantics) — the existing outer error-wrap boundary in `run_pipeline`/`resume_pipeline` (D-A1-03) still sees the same exception type it always did.

---

### `app/pipeline/orchestrator.py` — `_clarify` finalize (orchestrator, event-driven + CRUD finalize)

**Analog:** `app/email/gateway.py::send_outbound`'s own D-13c reserved→send→flip lifecycle (lines 182-311) — this is the pattern D-9-06/D-9-07 explicitly model the NEW finalize transaction on.

**Send lifecycle already correct, unchanged (gateway.py:236-311):**
```python
message_id = f"<{uuid.uuid4()}@{_OUTBOUND_DOMAIN}>"
repo.insert_email_message(..., send_state="reserved", conn=conn)   # commits BEFORE send
try:
    response = resend.Emails.send(send_params)
except Exception as exc:
    repo.update_email_message_state(message_id, "failed", conn=conn)
    raise exc
repo.update_email_message_sent(message_id, conn=conn)              # flips to 'sent' after
return message_id
```

**Existing post-send sequence in `_clarify` to wrap in a finalize transaction (orchestrator.py:1074-1077, the live-gateway path — the record_only and idempotency-guard paths at lines 942-946 and 1058-1062 need the SAME treatment):**
```python
gateway.send_outbound(
    run_id=run_id, to_addr=email.from_addr, subject=clarification_subject(email.subject),
    body=body, in_reply_to=email.message_id, references_header=email.message_id,
    purpose=purpose, send_state="sent",
)
repo.set_pre_clarify_extracted(run_id, extracted)
repo.set_status(run_id, RunStatus.AWAITING_REPLY)  # CLAR-01 pause
```

**Target shape per D-9-06 (send_outbound itself is OUTSIDE the txn — D-9-01 forbids wrapping the provider call; only the writes AFTER it return share one commit):**
```python
message_id = gateway.send_outbound(
    run_id=run_id, to_addr=email.from_addr, subject=clarification_subject(email.subject),
    body=body, in_reply_to=email.message_id, references_header=email.message_id,
    purpose=purpose, send_state="sent",
)  # its own reserved/flip transactions, per D-9-07 — do NOT pass an outer conn here
with get_connection() as conn:
    with conn.transaction():
        repo.set_pre_clarify_extracted(run_id, extracted, conn=conn)   # ordering is Claude's discretion (D-9-06)
        repo.set_status(run_id, RunStatus.AWAITING_REPLY, conn=conn)   # LAST (D-9-02)
```
Apply the identical wrap to the two other exit paths in `_clarify` (idempotency early-return, lines 942-946; record_only branch, lines 1058-1062) — same two-statement finalize, `set_status` last.

---

### `app/pipeline/orchestrator.py` — `_deliver` finalize (orchestrator, event-driven + CRUD finalize)

**Analog:** same `send_outbound` D-13c split, one call frame up. **Also see Pitfall 2** (RESEARCH.md) — this is the highest-risk wiring change in the phase.

**Existing sequence to wrap (orchestrator.py:1288-1304 — the try/except around `_write_aliases_if_safe` MUST stay exactly where it is, nested INSIDE, per D-13b):**
```python
try:
    _write_aliases_if_safe(run_id, run, roster)
except Exception as alias_exc:  # noqa: BLE001 — D-13b defensive isolation
    logger.warning(
        "alias write skipped for run %s: %s (run continues to SENT)",
        run_id, type(alias_exc).__name__,
    )

repo.set_status(run_id, RunStatus.SENT)
repo.set_status(run_id, RunStatus.RECONCILED)
```

**Target shape per D-9-07 (RESEARCH.md Pattern 3, copy verbatim — the try/except stays nested INSIDE `with conn.transaction()`, never wrapping it):**
```python
with get_connection() as conn:
    with conn.transaction():
        try:
            _write_aliases_if_safe(run_id, run, roster, conn=conn)  # D-13b isolation preserved
        except Exception as alias_exc:  # noqa: BLE001 — D-13b defensive isolation
            logger.warning(
                "alias write skipped for run %s: %s (run continues to SENT)",
                run_id, type(alias_exc).__name__,
            )
        repo.set_status(run_id, RunStatus.SENT, conn=conn)
        repo.set_status(run_id, RunStatus.RECONCILED, conn=conn)  # LAST (D-9-02)
```
**Warning (Pitfall 2, load-bearing):** if the try/except is accidentally moved OUTSIDE the `with conn.transaction():` block, an alias-write failure would roll back `SENT`/`RECONCILED` too — a real regression since the confirmation email was already, genuinely sent. Add a test asserting a forced `_write_aliases_if_safe` exception still yields `status == RECONCILED`.

The identical wrap applies to the two earlier exit paths in `_deliver`: the CLAR-04 idempotency early-return (lines 1197-1207, `set_status(SENT)` + `set_status(RECONCILED)` already adjacent — just needs `conn=`/txn) and the record_only branch (falls through to the same finalize block, no separate wrap needed).

---

### `app/main.py` — webhook `inbound()` route (controller, request-response + CRUD ingest transaction)

**Analog:** `app/main.py::retrigger` (lines 534-613) — the existing route that does a CAS-style claim then conditionally schedules `background_tasks.add_task`, i.e. the same "DB decision, THEN maybe enqueue" shape this webhook route needs.

**Retrigger's existing claim-then-enqueue shape to copy the STRUCTURE from (lines 611-613):**
```python
if claimed:
    background_tasks.add_task(_run_pipeline, run_id)
return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
```

**Existing webhook sequence to wrap (main.py:311-354 — currently THREE independently-committing repo calls):**
```python
email_id, inserted = repo.insert_inbound_email(
    message_id=email.message_id, in_reply_to=email.in_reply_to,
    references_header=email.references_header, subject=email.subject,
    from_addr=email.from_addr, to_addr=email.to_addr, body_text=cleaned, run_id=None,
)
if not inserted:
    ...  # duplicate: return 200, no run
...
business_id = repo.find_business_by_sender(email.from_addr)
if business_id is None:
    ...  # unknown sender: return 200, no run
run_id = repo.create_run(business_id=business_id, source_email_id=email_id)
background_tasks.add_task(_run_pipeline, run_id)
```

**Target shape per D-9-09 (RESEARCH.md Pattern 4 — commit BEFORE `background_tasks.add_task`, which stays OUTSIDE the `with` block):**
```python
inserted = False
business_id = None
run_id = None
existing_run_id = None
with get_connection() as conn:
    with conn.transaction():
        email_id, inserted = repo.insert_inbound_email(..., conn=conn)
        if not inserted:
            existing_run_id = repo.find_run_by_message_id(email.message_id, conn=conn)  # loser path, D-9-09 (corrected: email_id is always None on the loser branch, per checker BLOCKER 1)
        else:
            business_id = repo.find_business_by_sender(email.from_addr, conn=conn)
            if business_id is not None:
                run_id = repo.create_run(business_id=business_id, source_email_id=email_id, conn=conn)
    # transaction committed here — conn released back to pool

if inserted and business_id is not None:
    background_tasks.add_task(_run_pipeline, run_id)   # AFTER commit, never inside the `with` (D-9-09 anti-pattern)
```
Note reply-routing (`_route_reply`, called separately at line 337 for header-bearing inbounds) and the unknown-sender/duplicate response bodies are UNCHANGED in shape — D-9-09 only changes which connection/transaction the dedup+create_run share, and upgrades the duplicate response to include `existing_run_id` when found.

---

### `app/main.py` — `runs_list()` sweep hook (controller, request-response)

**Analog:** the route's own existing body (main.py:865-884) — trivial one-line addition, no new pattern needed.

**Existing route (lines 865-884, UNCHANGED except one new line before `repo.load_all_runs()`):**
```python
@app.get("/runs")
def runs_list(request: Request):
    """DASH-01: Render the reverse-chronological runs list with status badges."""
    try:
        runs = repo.load_all_runs()
    except Exception:
        logger.debug("load_all_runs unavailable — rendering empty list")
        runs = []
    return templates.TemplateResponse(request, "runs_list.html", {...})
```

**Target (D-9-11 — sweep call added before the load, same try/except-swallow-on-DB-unavailable philosophy the route already has):**
```python
@app.get("/runs")
def runs_list(request: Request):
    try:
        repo.sweep_stranded_runs(STALE_THRESHOLD_SECONDS)  # D-9-10/11 recovery hook
    except Exception:
        logger.debug("sweep_stranded_runs unavailable — skipping (DB not ready)")
    try:
        runs = repo.load_all_runs()
    except Exception:
        logger.debug("load_all_runs unavailable — rendering empty list")
        runs = []
    return templates.TemplateResponse(request, "runs_list.html", {...})
```
Reuse the existing `STALE_THRESHOLD` constant (main.py:64, currently `timedelta(minutes=5)`) — D-9-13 says derive ONE shared value for both the sweep and retrigger's stale-in-flight claim; convert/reference it as seconds for the sweep's `%s || ' seconds'` cast, or pass `.total_seconds()`.

---

## Shared Patterns

### The `conn=` + `_conn_ctx` transaction-threading seam
**Source:** `app/db/repo.py::_conn_ctx` (lines 125-133) + `_nulltx` (lines 1326-1329)
**Apply to:** every one of the six modified call sites above — this is the SINGLE mechanism for all of DATA-01/02/03. No new abstraction is introduced anywhere in this phase.
```python
@contextlib.contextmanager
def _conn_ctx(conn):
    if conn is not None:
        yield conn, False
    else:
        with get_connection() as owned:
            yield owned, True

@contextlib.contextmanager
def _nulltx():
    """No-op CM: when a caller passes their own conn, they own the transaction."""
    yield
```
Every repo helper already does `with _conn_ctx(conn) as (c, owns): with c.transaction() if owns else _nulltx(): ...` — passing the orchestrator's/webhook's own `conn=` into these calls makes the inner `c.transaction()` become a no-op automatically (`owns=False`), so the OUTER `with conn.transaction():` block the caller opens is the only transaction boundary that actually commits/rolls back.

### Status-advance-last (D-9-02)
**Source:** `app/db/repo.py::set_status` (lines 337-351) and `claim_status` (lines 354-379) — the two sanctioned status writers.
**Apply to:** the LAST statement inside every wrapped transaction block above must be a `set_status(...)`/`claim_status(...)` call — never a data write. This is what makes "a crash leaves the run wholly un-advanced" true by construction rather than by convention.

### CAS-UPDATE-WHERE-RETURNING idiom
**Source:** `app/db/repo.py::claim_status` (lines 354-379), extended in `record_run_error`'s WR-03 fix (lines 565-586) to an array-scoped predicate.
**Apply to:** `sweep_stranded_runs` (new) and the webhook's `insert_inbound_email` `ON CONFLICT DO NOTHING ... RETURNING id` (already existing, lines 160-184) — both are single-statement CAS, never read-then-write.

### Reserved-before-send / flip-after-send provider lifecycle (D-13c)
**Source:** `app/email/gateway.py::send_outbound` (lines 182-311).
**Apply to:** `_clarify` and `_deliver` — the NEW finalize transactions this phase adds wrap around this EXISTING lifecycle, never inside it (D-9-01: no transaction ever spans the Resend call).

### Defensive exception isolation nested strictly inside the boundary it protects
**Source:** `app/pipeline/orchestrator.py::_deliver`'s alias-write try/except (lines 1292-1299, D-13b) and `app/db/repo.py::_build_error_detail`'s fail-open try/except (lines 500-511, D-8-01b).
**Apply to:** `_deliver`'s finalize transaction — the alias try/except MUST stay nested inside `with conn.transaction():`, wrapping ONLY the `_write_aliases_if_safe` call (Pitfall 2 — the single highest-risk regression this phase can introduce).

## No Analog Found

None. Every touch point in this phase either extends an existing in-file idiom
(`claim_status`'s CAS shape, `send_outbound`'s reserved/flip split, `_conn_ctx`'s
transaction seam) or is a trivial one-line addition to an existing route
(`runs_list`'s sweep call). This is consistent with RESEARCH.md's own framing: "a
wiring/verification phase, not a design phase."

## Test File Patterns

### `tests/test_atomic_persist.py` (NEW, SC1)
**Analog:** RESEARCH.md's own worked example (Pattern 2, "Fault injection for SC1"), structurally modeled on `tests/test_claim_status.py`'s `@pytest.mark.integration` skip-guard (lines 158-176).
**Key constraint (Pitfall 3):** MUST use a real/local Postgres connection, never `FakeConnection` — `FakeConnection.transaction()` is a no-op `FakeTransaction` (see `tests/conftest.py:114+`) that cannot prove rollback semantics, only SQL shape.
```python
@pytest.mark.integration
def test_process_branch_crash_leaves_run_unadvanced(seeded_db):
    ...
    with pytest.raises(RuntimeError):
        with get_connection() as conn:
            with conn.transaction():
                repo.persist_extracted(run_id, extracted, conn=conn)
                repo.persist_decision(run_id, decision, conn=conn)
                repo.persist_reconciliation(run_id, matches, conn=conn)
                _boom(run_id, line_items, conn=conn)   # injected raise
                repo.set_status(run_id, RunStatus.COMPUTED, conn=conn)
                repo.set_status(run_id, RunStatus.AWAITING_APPROVAL, conn=conn)
    reloaded = repo.load_run(run_id)
    assert reloaded["status"] == original_status
    assert reloaded["extracted_data"] is None
```

### `tests/test_webhook_dedup_race.py` (NEW, SC2)
**Analog:** `tests/test_claim_status.py::test_claim_status_concurrent_calls_exactly_one_true` (lines 158-176) — the exact stub comment RESEARCH.md says to generalize ("Implementation note for Wave 1: use threading ... to fire both claims at near-simultaneously").
```python
@pytest.mark.integration
def test_duplicate_webhook_delivery_creates_exactly_one_run(seeded_db, client):
    import os, threading
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — skipping live-DB integration test")
    results = []
    def _post():
        r = client.post("/webhook/inbound", json={...same message_id...})
        results.append(r.json())
    t1 = threading.Thread(target=_post); t2 = threading.Thread(target=_post)
    t1.start(); t2.start(); t1.join(); t2.join()
    run_ids = {r.get("run_id") for r in results if r.get("run_id")}
    assert len(run_ids) == 1
```

### `tests/test_stuck_run_recovery.py` (NEW, SC3 + scope pin)
**Analog:** `tests/test_claim_status.py` in full (lines 1-176) — both its FakeConnection unit-shape assertions (e.g. `test_claim_status_sql_contains_where_status_and_returning`, lines 80-106, for the "sweep scope is exactly {received, extracting, computed}" pure SQL-shape test, D-9-12) and its live-DB integration skip-guard (lines 158-176, for the sweep→ERROR→retrigger interplay test).

## Metadata

**Analog search scope:** `app/db/repo.py` (full, 1328 lines), `app/pipeline/orchestrator.py` (targeted reads: 760-1155, 1150-1325), `app/main.py` (targeted reads: 1-70, 220-400, 534-654, 860-895), `app/email/gateway.py` (full, 311 lines), `app/db/supabase.py` (full, 95 lines), `tests/test_claim_status.py` (full, 176 lines).
**Files scanned:** 6 (all read in full or via targeted non-overlapping offsets; no re-reads).
**Pattern extraction date:** 2026-07-03
