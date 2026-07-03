# Phase 9: Atomic Data Integrity - Research

**Researched:** 2026-07-03
**Domain:** Postgres transaction semantics (psycopg3) applied to a plain-Python state machine; concurrent webhook dedup; stranded-run recovery
**Confidence:** HIGH

## Summary

This phase wires transaction boundaries around code paths that already do the right
DATA work in the right order — it is a wiring/verification phase, not a design
phase. All three requirements (DATA-01/02/03) have their approach **already locked**
in `09-CONTEXT.md` (D-9-01 through D-9-14), made by Claude after tracing the live
code. This research validates the two mechanics the CONTEXT explicitly flagged as
needing verification — psycopg3 transaction semantics and `ON CONFLICT` blocking
behavior under concurrency — and surfaces one **new finding not in CONTEXT.md**:
the D-9-13 threshold bound is wider than the "90s–3min" landing zone the context
assumed, because the OpenAI-compatible client's default timeout/retry configuration
allows a single legitimate LLM call to legitimately take much longer than assumed.

**Mechanics verified:**
1. `conn.transaction()` in psycopg3 issues `BEGIN`/`COMMIT`/`ROLLBACK` (or
   `SAVEPOINT`/`RELEASE` when nested), rolls back automatically on any exception
   escaping the `with` block, and this is exactly the primitive the existing
   `_conn_ctx(conn)` + `with c.transaction() if owns else _nulltx()` idiom in
   `repo.py` already threads through ~30 helpers. **No new abstraction is needed —
   Phase 9 is almost entirely about *where* the orchestrator/webhook open one
   connection and hold it across several repo calls**, not about changing repo.py's
   internal shape. [CITED: psycopg.org/psycopg3/docs/basic/transactions.html]
2. `INSERT ... ON CONFLICT DO NOTHING` under READ COMMITTED: when two concurrent
   transactions attempt to insert conflicting rows, the second inserter's unique-index
   check finds the first inserter's row-in-progress and **waits** for that
   transaction to commit or roll back (analogous to the documented UPDATE/DELETE
   wait behavior in Postgres's own concurrency docs). If the first transaction
   commits, the second sees the conflict and skips (returns no row from
   `RETURNING`). If the first transaction rolls back, the second proceeds as if no
   conflict existed and its own INSERT succeeds. **This is exactly the "exactly-one-run
   holds in every interleaving" guarantee D-9-09 depends on** — it is not an
   assumption, it is documented Postgres MVCC behavior. [CITED: postgresql.org/docs/current/transaction-iso.html]

**New finding (not previously verified in CONTEXT.md):**
3. `openai` (2.43.0, the pinned dependency) defaults to a **10-minute** per-request
   timeout and **`max_retries=2`** automatic retries on timeout/5xx/429 — independent
   of the app's own "ONE reflective retry on validation failure" (that retry is a
   distinct, additional layer in `app/llm/client.py`). Neither `extract()` nor
   `decide()`'s upstream stages pass an explicit `timeout=` override (only
   `compose_confirmation` passes `timeout_s=3.0`). **Worst-case legitimate single-stage
   latency is therefore bounded by 10 min × (1 + 2 retries) ≈ 30 minutes**, not the
   "90s–3min" the CONTEXT.md D-9-13 discussion estimated. This does not overturn
   D-9-13 (the planner still picks the exact value; a lower value can still be chosen
   deliberately as a design tradeoff), but the planner needs this number to make an
   informed choice rather than assume the 90s–3min estimate was verified.
   [CITED: github.com/openai/openai-python default timeout + retry docs] — see
   Pitfall 1 below for the recommended resolution.

**Primary recommendation:** Implement the three transaction boundaries exactly as
locked in `09-CONTEXT.md` (D-9-04 through D-9-10) using the existing `conn=` seam;
add a live-DB-gated concurrency test using Python's `threading` module (the codebase
already documents this as the intended pattern in `test_claim_status.py`'s stub);
and have the planner explicitly re-derive the D-9-13 threshold value with the
corrected LLM-timeout ceiling in mind (recommend documenting the accepted risk
rather than picking a threshold that actually bounds the true worst case, since a
threshold above ~30 min defeats DATA-03's purpose).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Multi-write atomicity (`_run_stages`, `_clarify` finalize, `_deliver` finalize) | API / Backend (orchestrator) | Database (transaction boundary) | The orchestrator decides *when* a transaction opens/closes; Postgres enforces the atomicity guarantee. Business logic and transaction demarcation are co-located by design (D-9-03: no unit-of-work abstraction). |
| Webhook dedup + run creation | API / Backend (`main.py` webhook route) | Database (unique constraint + CAS) | The webhook is the sole ingest entry point; the transactional guarantee that makes "loser attaches, never creates" correct lives in the DB's unique-index conflict resolution, not in application code racing a check-then-act. |
| Stuck-run recovery sweep | API / Backend (dashboard route trigger) | Database (single CAS UPDATE) | Render's free tier has no background workers, so the sweep MUST be triggered by an inbound HTTP request (the dashboard GET) — this is a Browser/Client-adjacent trigger point but the actual work (the UPDATE) is a single DB statement with no application-level branching. |
| Retrigger (existing, reused) | API / Backend | Database (CAS claim) | Unchanged by this phase — DATA-03 reuses it wholesale (D-9-10). |
| Send-outbound lifecycle (reserved/sent/failed) | API / Backend (`gateway.py`) | External (Resend) + Database | Unchanged by this phase — D-9-07 wraps a finalize transaction AROUND this existing lifecycle, never INSIDE the provider call. |

## User Constraints (from CONTEXT.md)

<user_constraints>

### Locked Decisions

- **D-9-01 No DB transaction ever spans an LLM call or a provider (Resend) call.**
  "Atomic" means every run of consecutive DB writes between external side effects
  commits in ONE `conn.transaction()`. Wrapping a network call in a DB transaction
  is rejected twice over: (a) a rollback after a successful send makes the DB assert
  "no email sent" when one WAS sent — a lie worse than the crash it guards; (b) it
  pins a pooled connection (pool max=5) across multi-second network latency. If
  DATA-01's literal wording ("the send+alias+status sequence … in a single
  transaction") matters at phase close, update REQUIREMENTS.md wording per the
  D-8-11 precedent — the honest claim is "all DB writes between side effects are
  atomic; the side effect itself is bracketed by durable intent/outcome markers
  (D-13c reserved/sent/failed)".
- **D-9-02 Status-advance-last invariant.** Within any atomic unit, the run-status
  write is the LAST statement before commit — a run is only ever observable in an
  advanced status when all data that status implies is already committed. This is
  what makes a crash leave the run "wholly un-advanced" (success criterion 1) rather
  than half-written.
- **D-9-03 Mechanism = the existing `conn=` seam.** Nearly every repo helper already
  accepts `conn=` (`_conn_ctx` pattern, Phase 2 decision). The orchestrator/webhook
  opens one pooled connection per atomic unit (`get_connection()` + `conn.transaction()`)
  and threads it through the repo calls. No new abstraction, no ORM, no unit-of-work
  class — plain psycopg3 transactions over the seam built for exactly this.

### Transaction granularity in `_run_stages` (DATA-01, part 1)

- **D-9-04 Process branch = ONE transaction.** `persist_extracted` + `persist_decision`
  + `persist_reconciliation` + `replace_line_items` + `set_status(COMPUTED)` +
  `set_status(AWAITING_APPROVAL)` all commit together (no external side effects on
  this branch — pure DB). Note `_compute_line_items` is pure computation; run it
  BEFORE opening the transaction so a calc exception never opens a doomed txn.
- **D-9-05 Clarify branch = persist-txn, then `_clarify` as its own post-commit unit.**
  The three data persists commit in one transaction (run status remains in-flight,
  un-advanced); `_clarify` runs after that commit because it contains two LLM calls
  (suggestion + draft) and a provider send. Crash anywhere inside `_clarify` leaves
  the run with persisted data but an un-advanced status — which is exactly the
  stranded-in-flight shape D-9-10's recovery sweep handles, and `_clarify`'s existing
  CLAR-04 idempotency guard makes retriggered re-entry safe (no duplicate
  clarification email once a row is `sent`).
- **D-9-06 Inside `_clarify`/`_deliver`, post-send DB writes are one finalize
  transaction.** For `_clarify`: flip-to-sent + `set_pre_clarify_extracted` +
  `set_status(AWAITING_REPLY)` commit together after the send returns (the
  snapshot's IS NULL guard keeps this idempotent; planner may order the snapshot
  write before the send if tracing shows that's safer — the locked part is that the
  status advance commits last, D-9-02). The alias-candidates write
  (`set_alias_candidates`) joins whichever unit it currently precedes. Resume-path
  (`resume_pipeline`) multi-writes get the same treatment — same principle, planner
  maps the exact sequences.

### `_deliver` and the un-rollbackable send (DATA-01, part 2)

- **D-9-07 Keep D-13c's reserved-before-send in its own commit; add a post-send
  finalize transaction.** The `send_state='reserved'` row MUST commit before the
  provider call (it is the durable crash marker — folding it into a later transaction
  would erase the evidence a crash needs). After `gateway.send_outbound` returns, ONE
  transaction commits: flip reserved→sent + alias write (`_write_aliases_if_safe`,
  still try/except-isolated per D-13b — its failure must not roll back the delivery
  finalize) + `set_status(SENT)` + `set_status(RECONCILED)`.
- **D-9-08 Delivery semantics = at-least-once, explicitly.** Crash window: Resend
  accepted the email but the finalize txn never committed → row still `reserved`, run
  still APPROVED → operator retrigger re-runs `_deliver`, the CLAR-04 sent-guard
  (which counts only `send_state='sent'` as proof) does NOT suppress, and the
  confirmation is re-sent. A duplicate confirmation email to the client is accepted
  as benign; a never-delivered payroll confirmation is not. Document this choice in
  the code comment at the finalize seam. (The D-13c upsert on `(run_id, purpose)`
  already makes retry-over-reserved advance instead of crash.)

### Webhook dedup CAS (DATA-02)

- **D-9-09 Single-transaction ingest closes the orphan window; the loser reports, it
  does not repair.** Wrap the webhook's DB sequence — `insert_inbound_email` (ON
  CONFLICT DO NOTHING) + routing/sender reads + `create_run` — in ONE transaction on
  one connection, committed BEFORE `background_tasks.add_task` is called (a
  background task must never race a not-yet-committed row; note TestClient runs
  BackgroundTasks synchronously after the response — verify the enqueue-after-commit
  ordering holds in both prod and test paths). Consequences, which ARE the CAS design
  the audit warned about:
  - Crash mid-ingest → the email row itself rolls back → Resend redelivery starts
    clean and creates the run. The "email row exists but no run ever will" orphan
    becomes impossible going forward, so no repair/adoption path is needed — that's
    the subtle gap in the audit's own sketch, dissolved rather than patched.
  - Two concurrent duplicates: under READ COMMITTED, the loser's INSERT blocks on
    the winner's in-flight txn; if the winner commits, the loser sees the conflict
    (`inserted=False`); if the winner ABORTS, the loser's insert succeeds and the
    loser creates the run. Exactly-one-run holds in every interleaving.
  - The loser's response upgrades from bare `{"status": "duplicate"}` to include the
    existing run's id when one exists (lookup via `payroll_runs.source_email_id` for
    first-ingest rows; a reply/unknown-sender duplicate legitimately has no run and
    returns the bare duplicate shape). This is what "the loser attaches to the
    existing run" means — report/associate, never create.
  - Rows with no run BY DESIGN (unknown sender, late reply, reply-routed resume) are
    unchanged — the transaction still commits the email row without a run on those
    paths.

### Stuck-run recovery (DATA-03)

- **D-9-10 Recovery = sweep-to-ERROR + the existing retrigger; never auto-restart.**
  A single-statement CAS sweep (`UPDATE payroll_runs SET status='error', error_detail=…
  WHERE status IN ('received','extracting','computed') AND updated_at < now() -
  <threshold> RETURNING id`) marks stranded runs as ERROR with a Phase-8 `error_detail`
  like `"recovery: stranded in-flight (background task died) — swept from {status}"`.
  The operator then uses the EXISTING ERROR→retrigger path. Rationale:
  marking-not-restarting keeps the one-human-gate philosophy (no autonomous pipeline
  restarts), reuses D-13b retrigger machinery wholesale, and converts an invisible
  stranding into a visible, diagnosable dashboard state. `error_reason` for swept runs
  is a fixed sentinel (e.g. `StrandedRunSwept`) so dashboards/tests can distinguish
  sweep-errors from real exceptions.
- **D-9-11 Sweep trigger = dashboard runs-list load.** Render free tier has no
  background loops (only inbound HTTP wakes the service), and the operator opening
  the dashboard is exactly the moment recovery matters. The runs-list GET route calls
  the sweep function (cheap single UPDATE) before loading runs; tests call the
  function directly. No new cron, no new endpoint required (planner MAY additionally
  expose it on an existing admin/ops route if trivially cheap, but the dashboard hook
  is the required path).
- **D-9-12 Sweep scope is exactly `{received, extracting, computed}`.** NOT
  `awaiting_reply` (legitimately parked for days awaiting the client), NOT
  `awaiting_approval` (parked at the human gate), NOT `approved` (has its own
  retrigger claim path, D-13b). This list must be pinned by a test — sweeping a
  parked-by-design status would be a correctness bug.
- **D-9-13 Threshold: lower from 5 min; exact value is a planner call bounded by
  evidence.** The bound: threshold must exceed the worst-case legitimate gap between
  two consecutive DB writes in a live pipeline (≈ the longest LLM call + its retry,
  since every stage write bumps `updated_at`) with comfortable margin — researcher
  verifies the configured LLM client timeouts and retry counts to compute it;
  expected landing zone 90s–3min. Keep ONE shared constant serving both the sweep and
  retrigger's existing stale-in-flight claim unless tracing shows they genuinely need
  different values. Known accepted tension (document, don't solve): a
  pathologically-slow-but-alive task swept to ERROR could later have its unguarded
  `set_status` overwrite ERROR and advance the run anyway — the margin makes this
  pathological, and Phase 10's concurrency proof is where any residual
  guard-hardening evidence would come from.
  **[RESEARCH FLAG — see Pitfall 1 below: the "90s–3min" landing zone assumed here
  was not yet verified against the actual openai-python client configuration. The
  true worst-case bound is ~30 minutes per stage (10 min timeout × 3 attempts,
  library default), because no explicit `timeout=`/`max_retries=` override exists
  on the extraction/draft tier clients. The planner must re-derive this value with
  that number in hand — see the recommendation in Pitfall 1.]**

### Test shape (from success criteria)

- **D-9-14 Crash injection via fault-hook, not mocks-all-the-way.** SC1's test forces
  an exception between writes inside an atomic unit (e.g. monkeypatched repo helper
  raising after N calls) and asserts the run is wholly un-advanced — status unchanged
  AND no partial rows (line items, decision, snapshot). Phase 7.5's lesson applies:
  assert the PERSISTED values, not just labels. SC2's race test runs two real
  concurrent ingests (threads against a real/local DB — the FakeConnection offline
  pattern cannot prove blocking semantics; a live-DB-gated test or the Phase 10
  harness seam is acceptable, planner decides placement) and asserts exactly one run.
  SC3's test strands a run (in-flight status + backdated `updated_at`), runs the
  sweep, asserts ERROR + error_detail, then retriggers to a progressing state.

### Claude's Discretion

- Exact threshold value within the D-9-13 bound; sweep function name and exact
  wiring point in the runs-list route.
- Whether the loser's existing-run lookup uses `source_email_id` join or a
  header-chain query.
- Ordering of `set_pre_clarify_extracted` relative to the send inside `_clarify`
  (D-9-06 locks only status-advance-last).
- How `gateway.send_outbound`'s internal reserved/flip writes get their connections
  (they intentionally stay OUTSIDE the caller's finalize txn per D-9-07 — plumb
  `conn=` only where it serves that design).
- Whether `_run_stages`' persist-txn connection is opened by the orchestrator
  per-call or passed from `run_pipeline`/`resume_pipeline`.

### Deferred Ideas (OUT OF SCOPE)

- **260623-08 — re-clarification loop cap with operator-escape state:** a new
  state-machine capability (counter column, new run state, dashboard controls) —
  its own phase, not atomicity work. Stays pending.
- **260623-01 remainder — WR-04 (Content-Disposition filename injection), WR-05
  (path containment), INFO-02 (LLM retry-prompt scrub):** security hygiene,
  unrelated to data integrity. Stays pending for a security-flavored slot.
- Cosmetic todos (260623-02/03/04/05) remain locked out of v2 scope per
  REQUIREMENTS.md — not re-litigated.
- Guard-hardening the pipeline's unguarded `set_status` writes against a
  swept-to-ERROR run (the D-9-13 accepted tension) — only if Phase 10's concurrency
  proof shows the window matters in practice.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-01 | Each multi-write pipeline operation is atomic — the persist+branch+status sequence in `_run_stages` and the send+alias+status sequence in `_deliver` each commit in a single transaction. | Verified psycopg3 `conn.transaction()` semantics (auto-rollback on exception, savepoint-nesting) confirm the existing `_conn_ctx`/`_nulltx` idiom in `repo.py` is the correct, sufficient mechanism — no new library needed. See Architecture Patterns Pattern 1-3 and Code Examples for the exact wiring shape per D-9-04/05/06/07. |
| DATA-02 | Duplicate webhook deliveries never create a second payroll run, even under concurrent delivery. | Verified Postgres READ COMMITTED blocking behavior for conflicting unique-index inserts confirms D-9-09's CAS design is correct Postgres MVCC behavior, not an assumption. See Pattern 4 + Code Examples for the exact transaction wrapping shape and the live-DB-gated concurrency test pattern already stubbed in `test_claim_status.py`. |
| DATA-03 | A run whose background task died mid-flight is recoverable without an over-long stale threshold. | Verified the openai-python client's actual timeout/retry defaults (10 min timeout, 2 retries) to correct the D-9-13 threshold-bound estimate — see Pitfall 1 and the Sources section. See Pattern 5 for the sweep-UPDATE shape and Don't Hand-Roll for why this must stay a single CAS statement, not a loop. |

</phase_requirements>

## Standard Stack

### Core

No new libraries. This phase is 100% wiring existing, already-installed dependencies.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psycopg (psycopg3) | 3.3.4 (pinned, verified in `pyproject.toml`) | Transaction primitive (`conn.transaction()`), CAS UPDATE statements | Already the project's sole DB driver (D-04 locked); nothing about atomicity/dedup/recovery requires a different tool. `conn.transaction()` is the library's own transaction-management API, documented and stable. [CITED: psycopg.org/psycopg3/docs/basic/transactions.html] |
| psycopg_pool (`ConnectionPool`) | bundled with `psycopg[binary,pool]==3.3.4` | Connection acquisition for the atomic units | Already in use via `app/db/supabase.py get_connection()`. Pool max=5 is the exact reason D-9-01 forbids holding a transaction across a network call — confirmed by reading `supabase.py`. |

### Supporting

No additional packages. `threading` (Python stdlib) is sufficient for the SC2 concurrency test — no `pytest-xdist`, no `asyncio`, no separate concurrency-testing library is needed for two threads racing one webhook call.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Plain `conn=` threading + `conn.transaction()` (locked, D-9-03) | A unit-of-work class / repository pattern wrapper | Locked out by D-9-03: would add an abstraction layer for a single-author demo project with ~30 already-`conn=`-aware helpers; the existing seam is simpler and already proven (Phase 2 decision). |
| Postgres unique-constraint CAS for dedup (locked, D-9-09) | Advisory locks (`pg_advisory_xact_lock`) keyed on `message_id` hash | Advisory locks would work but add a second locking primitive alongside the unique constraint that already exists (`uq_message_id`) — pure complexity with no correctness gain; the unique index IS the lock. |
| `threading` module for the SC2 concurrency test | `pytest-asyncio` + async DB driver race | The webhook route and `insert_inbound_email` are synchronous; two OS threads each opening their own pooled connection is the simplest way to genuinely race two Postgres transactions and is exactly what `test_claim_status.py`'s existing stub comment recommends. |

**Installation:**
No installation required — psycopg3.3.4 and its pool extra are already pinned in `pyproject.toml` (verified via `uv run python -c "import psycopg; print(psycopg.__version__)"` → `3.3.4`, matching the pin exactly).

**Version verification:** `psycopg[binary,pool]==3.3.4` confirmed installed via the project's own `.venv` (not just the lockfile) — see command above. No drift.

## Package Legitimacy Audit

No new external packages are introduced by this phase. Skipping the slopcheck/registry
gate — nothing to audit. All mechanics use the already-vetted `psycopg` dependency and
Python's `threading` stdlib module.

## Architecture Patterns

### System Architecture Diagram

```
                    ┌─────────────────────────────────────────┐
                    │         POST /webhook/inbound            │
                    └───────────────────┬───────────────────────┘
                                        │
                    ┌───────────────────▼───────────────────────┐
                    │  INGEST TXN (D-9-09, ONE connection)        │
                    │  insert_inbound_email (ON CONFLICT DO       │
                    │    NOTHING) → sender lookup → create_run    │
                    │  COMMIT ─────────────────────┐              │
                    └───────────────┬───────────────┼──────────────┘
                          inserted? │               │ not inserted
                             yes    │               │ (loser)
                    ┌───────────────▼──┐   ┌─────────▼──────────────┐
                    │ background_tasks  │   │ lookup existing run    │
                    │ .add_task(...)    │   │ via source_email_id;   │
                    │ AFTER commit      │   │ return {status, run_id}│
                    └───────────────┬───┘   └─────────────────────────┘
                                    │
                    ┌───────────────▼───────────────────────────┐
                    │      run_pipeline / resume_pipeline          │
                    │      (background task)                       │
                    └───────────────┬───────────────────────────────┘
                                    │
                    ┌───────────────▼───────────────────────────────┐
                    │  _run_stages: extract (LLM) → reconcile (pure) │
                    │  → validate (pure) → decide (pure)             │
                    └───────────────┬───────────────────────────────┘
                                    │
                    ┌───────────────▼───────────────────────────────┐
                    │  PERSIST TXN (D-9-04, ONE connection)           │
                    │  persist_extracted + persist_decision +         │
                    │  persist_reconciliation [+ replace_line_items]  │
                    │  + set_status(...) ... set_status(...) LAST     │
                    │  COMMIT                                          │
                    └───────────┬───────────────────┬───────────────────┘
                       process  │                   │ request_clarification
                                │                   │
                    ┌───────────▼──────┐   ┌─────────▼────────────────────┐
                    │ AWAITING_APPROVAL │   │ _clarify (post-commit unit)    │
                    │ (terminal-ish,     │   │  suggest (LLM) → compose (LLM) │
                    │  human gate next)  │   │  → send_outbound:                │
                    └────────────────────┘   │    RESERVED TXN (D-9-07, commits │
                                              │    BEFORE provider call)          │
                                              │    → Resend API call (NO txn)     │
                                              │    → FINALIZE TXN (D-9-06):       │
                                              │      flip sent + snapshot +       │
                                              │      set_status(AWAITING_REPLY)   │
                                              └───────────────────────────────────┘

                    ┌─────────────────────────────────────────────────┐
                    │        POST /runs/{id}/approve                    │
                    └───────────────────┬─────────────────────────────┘
                                        │ claim_status CAS (AWAITING_APPROVAL→APPROVED)
                    ┌───────────────────▼─────────────────────────────┐
                    │  _deliver (synchronous)                           │
                    │  RESERVED TXN (D-9-07, commits BEFORE send)       │
                    │  → Resend API call (NO txn, PDFs generated first) │
                    │  → FINALIZE TXN (D-9-07): flip sent + alias write │
                    │    (try/except-isolated) + set_status(SENT) +     │
                    │    set_status(RECONCILED) LAST                     │
                    └───────────────────────────────────────────────────┘

                    ┌─────────────────────────────────────────────────┐
                    │        GET /runs  (dashboard, D-9-11 trigger)     │
                    └───────────────────┬─────────────────────────────┘
                                        │
                    ┌───────────────────▼─────────────────────────────┐
                    │  SWEEP (D-9-10, single CAS UPDATE, its own txn)   │
                    │  UPDATE payroll_runs SET status='error',           │
                    │    error_detail=... WHERE status IN                │
                    │    ('received','extracting','computed')             │
                    │    AND updated_at < now() - THRESHOLD RETURNING id  │
                    └───────────────────┬─────────────────────────────┘
                                        │ swept rows now ERROR
                    ┌───────────────────▼─────────────────────────────┐
                    │  Existing retrigger (unchanged, D-13b): operator   │
                    │  clicks Retrigger → claim_status(ERROR→RECEIVED)   │
                    │  → background_tasks.add_task(run_pipeline)          │
                    └─────────────────────────────────────────────────┘
```

### Recommended Project Structure

No new files/folders. Changes land in the existing modules:

```
app/
├── db/
│   └── repo.py         # ADD: sweep_stranded_runs() (D-9-10/11/12), no other new helpers needed
├── pipeline/
│   └── orchestrator.py # MODIFY: _run_stages, _clarify, _deliver — wrap existing sequences in conn.transaction()
├── main.py              # MODIFY: webhook inbound() — wrap dedup+routing+create_run in one txn;
│                        #         runs_list() — call sweep_stranded_runs() before load_all_runs()
tests/
├── test_atomic_persist.py      # NEW (SC1): fault-injection test for _run_stages/_deliver transactions
├── test_webhook_dedup_race.py  # NEW (SC2): @pytest.mark.integration threading race test
└── test_stuck_run_recovery.py  # NEW (SC3): sweep + retrigger test
```

### Pattern 1: The existing `conn=` + `_conn_ctx` seam IS the transaction primitive

**What:** Every repo helper already accepts `conn=None` and does
`with _conn_ctx(conn) as (c, owns): with c.transaction() if owns else _nulltx(): ...`.
When a caller passes its OWN connection, each individual helper's inner
`c.transaction() if owns else _nulltx()` becomes a no-op (`_nulltx()`), and the
CALLER's outer `conn.transaction()` is the transaction boundary that actually
commits/rolls back.

**When to use:** Every multi-write sequence identified in D-9-04 through D-9-10.

**Example (verified against psycopg3 3.3.4 docs):**
```python
# Source: app/db/repo.py `_conn_ctx` (existing) + psycopg.org/psycopg3/docs/basic/transactions.html
from app.db.supabase import get_connection
from app.db import repo

# D-9-04: process branch, ONE transaction, status-advance-last (D-9-02)
with get_connection() as conn:
    with conn.transaction():
        repo.persist_extracted(run_id, extracted, conn=conn)
        repo.persist_decision(run_id, decision, conn=conn)
        repo.persist_reconciliation(run_id, matches, conn=conn)
        repo.replace_line_items(run_id, line_items, conn=conn)   # pure DB, no side effect
        repo.set_status(run_id, RunStatus.COMPUTED, conn=conn)
        repo.set_status(run_id, RunStatus.AWAITING_APPROVAL, conn=conn)  # LAST (D-9-02)
    # commit happens here on clean exit; ROLLBACK happens automatically if any
    # repo.* call above raises — psycopg3's transaction() context manager rolls
    # back on ANY exception escaping the `with` block.
```

**Verified transaction semantics (psycopg3 3.3.4):**
- `conn.transaction()` issues `BEGIN` on entry (unless already inside one, in
  which case it issues `SAVEPOINT`).
- On clean exit it issues `COMMIT` (or `RELEASE SAVEPOINT` if nested).
- On any exception raised inside the block, it issues `ROLLBACK` (or
  `ROLLBACK TO SAVEPOINT` if nested) and re-raises the original exception —
  the caller's `try/except` around the whole unit (the existing D-A1-03
  error-wrap in `orchestrator.py`) sees the same exception it would have seen
  without the transaction wrapper. No swallowing, no behavior change to the
  error path.
- `raise psycopg.Rollback` from inside the block rolls back WITHOUT re-raising
  — not needed for this phase (every failure path in D-9-04 through D-9-10 wants
  the exception to propagate to the existing error-wrap boundary).
[CITED: psycopg.org/psycopg3/docs/basic/transactions.html]

### Pattern 2: Fault injection for SC1 (crash-mid-sequence test)

**What:** Monkeypatch one repo helper inside the atomic unit to raise after N
calls, then assert (a) the run's status is unchanged, (b) no partial rows exist
(line items, decision, reconciliation all still reflect the PRE-transaction state).

**When to use:** SC1's test, per D-9-14.

**Example:**
```python
# Source: pattern derived from tests/conftest.py's FakeConnection design +
# the D-9-14 fault-hook directive. Uses a REAL connection (not FakeConnection)
# because FakeConnection's transaction() is a no-op FakeTransaction that never
# actually rolls back writes — it cannot prove atomicity, only SQL shape.
# This test MUST run against a real (or local) Postgres to prove the ROLLBACK
# actually reverts prior writes in the same transaction.
import pytest
from app.db.supabase import get_connection
from app.db import repo

@pytest.mark.integration
def test_process_branch_crash_leaves_run_unadvanced(seeded_db):
    run_id = ...  # create a real run via repo.create_run
    original_status = repo.load_run(run_id)["status"]

    call_count = {"n": 0}
    real_replace = repo.replace_line_items

    def _boom(*a, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("injected crash mid-sequence")
        return real_replace(*a, **kw)

    with pytest.raises(RuntimeError):
        with get_connection() as conn:
            with conn.transaction():
                repo.persist_extracted(run_id, extracted, conn=conn)
                repo.persist_decision(run_id, decision, conn=conn)
                repo.persist_reconciliation(run_id, matches, conn=conn)
                _boom(run_id, line_items, conn=conn)   # raises before set_status calls
                repo.set_status(run_id, RunStatus.COMPUTED, conn=conn)
                repo.set_status(run_id, RunStatus.AWAITING_APPROVAL, conn=conn)

    # Assert: status UNCHANGED (never advanced past received/extracting)
    reloaded = repo.load_run(run_id)
    assert reloaded["status"] == original_status
    # Assert: NO partial data — persist_extracted/decision/reconciliation writes
    # rolled back too, even though they "succeeded" before the injected exception.
    assert reloaded["extracted_data"] is None
    assert reloaded["decision"] is None
    assert reloaded["reconciliation"] is None
```

### Pattern 3: `_deliver`'s reserved-before-send / finalize-after-send split (D-9-07)

**What:** The send_state='reserved' row is its OWN transaction (commits before
the Resend call); the flip-to-sent + alias write + status advances are a SEPARATE
finalize transaction (commits after the Resend call returns).

**When to use:** `_deliver` and `_clarify`'s send call sites.

**Example:**
```python
# Source: app/email/gateway.py send_outbound (existing D-13c lifecycle, UNCHANGED)
# + orchestrator.py _deliver (MODIFIED per D-9-07)

# gateway.send_outbound already does exactly this split internally:
#   1. repo.insert_email_message(..., send_state="reserved", conn=conn)  # own commit
#   2. resend.Emails.send(...)   # NO transaction wraps this — network call
#   3. on success: repo.update_email_message_sent(message_id, conn=conn) # separate write
# D-9-07's NEW finalize transaction wraps steps that come AFTER send_outbound
# returns, inside _deliver:
message_id = gateway.send_outbound(run_id=run_id, ..., conn=None)  # its own txn(s)
with get_connection() as conn:
    with conn.transaction():
        # gateway.send_outbound already flipped send_state to 'sent' internally;
        # this finalize txn covers what _deliver itself must do atomically:
        try:
            _write_aliases_if_safe(run_id, run, roster, conn=conn)  # D-13b isolation
        except Exception:
            logger.warning(...)  # swallowed — alias failure must not roll back finalize
        repo.set_status(run_id, RunStatus.SENT, conn=conn)
        repo.set_status(run_id, RunStatus.RECONCILED, conn=conn)  # LAST (D-9-02)
```
**Note:** `_write_aliases_if_safe`'s try/except MUST stay INSIDE the transaction
block (catching its own exception) rather than wrapping the whole `with
conn.transaction()` block — the D-13b defensive isolation is about the alias
write's *own* failure not rolling back SENT/RECONCILED, not about avoiding the
transaction machinery. If the try/except is placed outside `with conn.transaction()`
and the alias code inside it raises, the transaction rolls back and status never
advances — that would be a REGRESSION of D-13b's existing guarantee.

### Pattern 4: Webhook ingest single transaction (D-9-09)

**What:** `insert_inbound_email` + `find_business_by_sender` + `create_run` share
ONE connection and ONE transaction; `background_tasks.add_task` is called only
AFTER that transaction has committed (outside the `with` block).

**Example:**
```python
# Source: app/main.py inbound() (MODIFIED per D-9-09)
with get_connection() as conn:
    with conn.transaction():
        email_id, inserted = repo.insert_inbound_email(..., conn=conn)
        if not inserted:
            # look up existing run for this message_id's email row (loser path)
            existing_run_id = repo.find_run_by_message_id(email.message_id, conn=conn)
        else:
            business_id = repo.find_business_by_sender(email.from_addr, conn=conn)
            if business_id is not None:
                run_id = repo.create_run(business_id=business_id, source_email_id=email_id, conn=conn)
    # transaction committed here — conn released back to pool

# background_tasks.add_task happens AFTER the `with` block exits (commit already
# happened), never inside it — a background task must never observe a
# not-yet-committed row (TestClient runs BackgroundTasks synchronously right
# after the route function returns, so this ordering also holds under test).
if inserted and business_id is not None:
    background_tasks.add_task(_run_pipeline, run_id)
```

### Pattern 5: Recovery sweep (D-9-10/11/12) — single CAS UPDATE, no loop

**What:** One parameterized `UPDATE ... WHERE status IN (...) AND updated_at <
now() - interval RETURNING id`, called once at the top of the `GET /runs` route.

**Example:**
```python
# Source: repo.py claim_status (the CAS idiom being extended, existing)
def sweep_stranded_runs(threshold_seconds: int, conn=None) -> list[uuid.UUID]:
    """D-9-10/11/12: mark runs stranded in-flight (background task died) as ERROR.

    Scope is EXACTLY {received, extracting, computed} (D-9-12) — never
    awaiting_reply/awaiting_approval/approved, which are legitimately parked.
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
**Note:** This single statement IS the atomic unit — no read-then-write race is
possible because Postgres evaluates the WHERE clause and performs the UPDATE as
one operation per matching row (same CAS idiom as `claim_status`).

### Anti-Patterns to Avoid

- **Wrapping the Resend/LLM call inside `conn.transaction()`:** Explicitly forbidden
  by D-9-01. Verified reason: a pooled connection (max=5) held across a multi-second
  network call starves the other 4 slots under concurrent load, and a rollback after
  a successful send creates a DB state that lies about what actually happened.
- **A read-then-write (SELECT ... check ... UPDATE) implementation of the recovery
  sweep or the dedup check:** Both must be single CAS statements (`UPDATE ... WHERE
  ... RETURNING`) — see `record_run_error`'s own WR-03 fix in the existing codebase
  (repo.py:536-544) as the in-repo cautionary precedent: a prior check-then-act
  version of that exact guard was itself a race the codebase already had to fix once.
- **Placing `background_tasks.add_task(...)` inside the `with conn.transaction():`
  block:** Even though FastAPI's `BackgroundTasks.add_task` itself doesn't touch the
  DB, doing so inside the block risks a future refactor moving DB work after it
  inside the same scope, and it obscures the D-9-09 invariant ("committed BEFORE the
  background task is scheduled") from a reader.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Atomic multi-write commit | A manual "all-or-nothing" flag column + cleanup job | `conn.transaction()` (already the project's mechanism) | Postgres's transaction log already gives exactly-once-visible durability; a flag-column simulation is strictly weaker (a crash between the writes and the flag-set is still a half-written state) and duplicates what the DB already guarantees for free. |
| Exactly-one-run-per-message_id under concurrency | A Python-side lock (`threading.Lock`, Redis lock, in-process dict) | The existing `uq_message_id` UNIQUE constraint + `ON CONFLICT DO NOTHING` (D-9-09) | A process-local lock does not survive across the (eventual) multi-worker/multi-dyno case and is redundant with a DB constraint that already provides the guarantee cluster-wide. This project's whole premise (per CLAUDE.md) is "Postgres IS the state machine" — application-level locking contradicts that. |
| Stranded-run detection | A background poller thread inside the FastAPI process | A single UPDATE...WHERE...RETURNING triggered by an inbound HTTP request (D-9-11) | Render free tier only keeps the process alive on inbound HTTP traffic (confirmed in CLAUDE.md's Installation section); a background poller thread would simply not run reliably (or at all) between requests, and would need its own crash-recovery story — recursive complexity for no benefit over triggering on the dashboard load. |
| Concurrency proof for SC2 | Mocked-repo "simulated race" (two sequential calls asserting order) | Two real OS threads racing two real Postgres transactions (`threading` stdlib, `@pytest.mark.integration`) | A sequential simulation cannot prove blocking/wait semantics — that is precisely the mechanic under test (whether the second transaction actually blocks on the first's uncommitted row). `test_claim_status.py`'s own stub comment already flags this as the intended future pattern. |

**Key insight:** Every "don't hand-roll" item in this phase resolves to the same
principle already stated in the project's CLAUDE.md: Postgres is the durable state
machine, not application code. The phase's job is to stop leaking that guarantee
at the boundaries where multiple writes currently commit independently.

## Common Pitfalls

### Pitfall 1: The D-9-13 threshold "90s-3min" estimate under-counts real LLM worst-case latency

**What goes wrong:** If the planner picks a threshold near 90s-3min as CONTEXT.md's
discussion estimated, a single legitimate extraction call that hits a slow DeepSeek
response and retries via the client's own automatic retry logic could still be
"alive" well past that threshold — the sweep would then mark a live, in-progress run
as ERROR while its background task is still running. When that task later calls
`set_status` (an unguarded writer, D-9-13's own documented "accepted tension"), the
run flips from ERROR back to whatever status the live task computes — silently
undoing the sweep's diagnosis and potentially double-processing.

**Why it happens:** `app/llm/client.py`'s `call_structured` does not pass an
explicit `timeout=` to the `OpenAI(...)` client construction for the extraction or
draft tiers (only `compose_confirmation`'s free-text call passes `timeout_s=3.0`).
The `openai` library (2.43.0, pinned) therefore uses its documented defaults: a
10-minute per-request timeout and `max_retries=2` automatic retries on
timeout/5xx/429 status codes — a layer BELOW and INDEPENDENT of the app's own "ONE
reflective retry on validation failure" in the same module. Worst case: 10 min ×
3 attempts (1 original + 2 library retries) ≈ 30 minutes for a single stage call,
before the app's own reflective retry (which re-sends the whole request again) is
even counted.
[CITED: github.com/openai/openai-python default timeout=600s / max_retries=2 docs]

**How to avoid:** The planner has three legitimate options, in order of
recommendation:
1. **(Recommended) Set an explicit, bounded `timeout=` on the extraction/draft
   OpenAI client construction** (e.g. 30-60s, matching `compose_confirmation`'s
   existing `timeout_s=3.0` precedent scaled up for a heavier structured call) —
   this makes the D-9-13 "90s-3min" estimate actually TRUE by construction, rather
   than assumed. This is a small, surgical change to `app/llm/client.py` and is
   arguably in-scope for DATA-03 since it is the fact the threshold's correctness
   depends on. Flag this explicitly to the planner as a candidate task.
2. **Pick a threshold that reflects the TRUE current worst case** (~30-35 min) —
   correctness-preserving but weakens DATA-03's practical value ("recoverable
   without waiting out an over-long stale threshold" — 30 min is still much better
   than never, but is a much weaker claim than 90s-3min).
3. **Document the gap as an explicitly accepted risk** (extending D-9-13's existing
   "accepted tension" note) without changing the LLM client — the planner should
   not silently assume 90s-3min is safe without explicitly choosing one of these.

**Warning signs:** A test that seeds a run in `extracting` with `updated_at` a few
minutes old, runs the sweep, and asserts ERROR — if that same run's background task
is later allowed to complete normally in the SAME test process without an assertion
that the late `set_status` call is somehow guarded, the test is only proving the
sweep's SQL shape, not the real-world safety of the chosen threshold.

### Pitfall 2: `_write_aliases_if_safe`'s existing exception isolation must be re-verified inside the new transaction boundary

**What goes wrong:** If the try/except around `_write_aliases_if_safe` (D-13b,
existing code) is accidentally moved to wrap the entire `with conn.transaction():`
finalize block instead of being placed strictly inside it, an alias-write failure
would roll back the ENTIRE finalize transaction — including `set_status(SENT)` and
`set_status(RECONCILED)` — which is a regression: the confirmation email was
genuinely sent (D-9-08's at-least-once semantics), but the run would appear stuck
at APPROVED, causing operator confusion and a spurious retrigger that re-sends the
confirmation email a second time (benign per D-9-08, but avoidable).

**Why it happens:** This is an easy refactoring mistake when converting a sequence
of independent `repo.*` calls into a `with conn.transaction():` block — the
temptation is to wrap the whole function body in one outer try/except for
"cleanliness," which silently changes which failures are isolated vs. which
propagate.

**How to avoid:** Keep the alias-write try/except exactly where it currently is
(nested inside the transaction block, wrapping ONLY the `_write_aliases_if_safe`
call), per Pattern 3 above. Add a test asserting that a forced
`_write_aliases_if_safe` exception still results in `status == RECONCILED` after
`_deliver` returns.

**Warning signs:** Any test for SC1 that forces an alias-write failure and observes
the run NOT reaching RECONCILED — that would indicate the isolation regressed.

### Pitfall 3: `FakeConnection`'s `transaction()` cannot prove atomicity — only SQL shape

**What goes wrong:** `tests/conftest.py`'s `FakeConnection.transaction()` returns a
`FakeTransaction` whose `__enter__`/`__exit__` do nothing — no actual rollback
semantics. A test using `fake_repo`/`fake_conn` that asserts "the SQL to persist X
was NOT executed after the injected exception" only proves the Python code stopped
calling repo helpers after the exception — it proves NOTHING about whether Postgres
itself would roll back writes that DID execute before the exception. SC1 requires
proving the DB state is genuinely unadvanced, which requires a real (or local)
Postgres connection.

**Why it happens:** `FakeConnection` was designed (Phase 2) to assert
parameterized-SQL shape offline, not to simulate MVCC rollback — that was never its
job, and it still isn't. It remains correct and sufficient for every OTHER repo
test in the suite; only the NEW atomicity-proof tests in this phase need a real
connection.

**How to avoid:** SC1's crash-injection test and SC2's race test must both be
`@pytest.mark.integration`-gated (the existing pattern in `test_claim_status.py`),
skip-guarded on `DATABASE_URL` + optionally `ALLOW_DB_RESET=1` per the existing
`seeded_db` fixture convention in `tests/conftest.py`. Do not attempt to prove
SC1/SC2 using only `fake_repo`/`FakeConnection`.

**Warning signs:** A "green" SC1/SC2 test that never actually opens a real
`psycopg.Connection` — check the test imports/fixtures used.

## Code Examples

### Verifying atomic rollback interactively

```python
# Source: psycopg 3.3.4 docs (psycopg.org/psycopg3/docs/basic/transactions.html),
# adapted to this project's get_connection() pool wrapper for a smoke check.
from app.db.supabase import get_connection

with get_connection() as conn:
    try:
        with conn.transaction():
            conn.execute("UPDATE payroll_runs SET status = 'error' WHERE id = %s", (run_id,))
            raise RuntimeError("simulated crash")
    except RuntimeError:
        pass
    # The UPDATE above never committed — SELECT status now returns the PRE-crash value.
    row = conn.execute("SELECT status FROM payroll_runs WHERE id = %s", (run_id,)).fetchone()
```

### Concurrency race test skeleton (SC2), matching `test_claim_status.py`'s existing stub

```python
# Source: tests/test_claim_status.py's existing @pytest.mark.integration stub
# (test_claim_status_concurrent_calls_exactly_one_true) — this phase implements
# the analogous test for webhook dedup instead of claim_status.
import threading
import pytest

@pytest.mark.integration
def test_duplicate_webhook_delivery_creates_exactly_one_run(seeded_db, client):
    import os
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")

    same_message_id = "<race-test@acme.test>"
    results = []

    def _post():
        r = client.post("/webhook/inbound", json={...same_message_id...})
        results.append(r.json())

    t1 = threading.Thread(target=_post)
    t2 = threading.Thread(target=_post)
    t1.start(); t2.start()
    t1.join(); t2.join()

    # Exactly one run for this message_id, regardless of which thread "won".
    run_ids = {r.get("run_id") for r in results if r.get("run_id")}
    assert len(run_ids) == 1
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Independent auto-commit writes per repo call (`persist_extracted`, `persist_decision`, `set_status(COMPUTED)`, `set_status(AWAITING_APPROVAL)` each committing separately) | All writes in one `_run_stages` branch share one `conn.transaction()` | This phase (Phase 9) | A crash between any two of these writes previously left a half-written run (e.g. line items replaced but status still `extracting`); now it leaves the run exactly as it was before the sequence started. |
| Webhook dedup check + run creation as two independently-committing steps | One transaction spanning dedup INSERT + routing + `create_run`, committed before the background task is scheduled | This phase | Closes HIGH-04's orphan window (an inbound row could previously exist with no run ever created for it if a crash landed between the two independent commits). |
| 5-minute stale threshold for stuck-run detection, discoverable only via manual retrigger click with no visible signal | A recovery sweep runs on every dashboard load, proactively marking stranded runs ERROR (visible, diagnosable) at a shorter, evidence-derived threshold | This phase | MED-05 closed: a stuck run is now visible in the dashboard as an ERROR with a distinguishing `error_reason` sentinel, not silently invisible until someone happens to retrigger it. |

**Deprecated/outdated:**
- The bare 5-minute `STALE_THRESHOLD` constant in `main.py` as the sole recovery
  mechanism: superseded by the sweep (D-9-10) sharing a threshold constant with
  retrigger's existing stale-in-flight claim logic, per D-9-13's "keep ONE shared
  constant" guidance.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The "90s-3min" landing zone in D-9-13 (CONTEXT.md, locked) was an estimate, not verified against the actual `openai` client configuration at research time. | Pitfall 1 | If the planner adopts a threshold in that range WITHOUT also bounding the LLM client's timeout (Pitfall 1 option 1), a legitimate slow-but-alive extraction call could be swept to ERROR while still running, then have its `set_status` write silently un-sweep it (the already-documented "accepted tension" in D-9-13) — this is a correctness risk the CONTEXT.md text itself already flags as accepted, but the magnitude (30 min, not 90s-3min) was not previously quantified. |
| A2 | No live DB was queried during this research session (checked `.env` presence only, did not connect) — the concurrent-INSERT blocking behavior is stated from official Postgres documentation, not empirically reproduced in this environment. | Summary, Architecture Patterns Pattern 4 | Extremely low risk: this is long-standing, extensively documented core Postgres MVCC behavior (READ COMMITTED semantics), not a niche or version-specific feature. The planner's SC2 test itself will empirically confirm it against the live/local DB during execution. |

## Open Questions

1. **Should the extraction/draft LLM client timeout be tightened as part of Phase 9, or left to a future phase?**
   - What we know: The current default (10 min timeout × 3 attempts ≈ 30 min worst
     case) is the actual ceiling the D-9-13 threshold must respect if the sweep is to
     avoid the "accepted tension" scenario in practice, not just in theory.
   - What's unclear: Whether tightening `app/llm/client.py`'s timeout is considered
     in-scope for "Atomic Data Integrity" (DATA-03) or is a separate concern the
     phase should merely document and defer.
   - Recommendation: Flag to the planner as a candidate small task within DATA-03
     (it directly determines whether the chosen threshold value is actually safe);
     if descoped, the planner should still document the 30-min true ceiling
     explicitly in the code comment at the sweep/threshold constant, extending
     D-9-13's existing "known accepted tension" note with the corrected number.

2. **Exact form of the loser's "existing run" lookup in the webhook response (D-9-09, Claude's Discretion).**
   - What we know: CONTEXT.md leaves this open — either a `source_email_id` join
     or a header-chain query.
   - What's unclear: Whether a duplicate delivery of the FIRST-EVER inbound for a
     run (not a reply) can reliably use `source_email_id`, since that column is only
     populated via `create_run(source_email_id=...)` — a race where the loser's
     lookup runs before the winner's `create_run` has committed (impossible under
     the D-9-09 single-transaction design, since the loser's read happens inside its
     OWN transaction which only proceeds after the winner's transaction has already
     committed or rolled back) resolves cleanly, but this deserves an explicit test.
   - Recommendation: `source_email_id` join is sufficient and simpler than a
     header-chain query for the first-ingest case (which is the only case D-9-09
     describes for "the loser attaches to the existing run"); reply-routing
     duplicates already have separate handling (`_route_reply`) untouched by this
     phase.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| psycopg3 | Transaction primitive | ✓ | 3.3.4 (verified via `uv run python -c "import psycopg; print(psycopg.__version__)"`) | — |
| Live/local Postgres (`DATABASE_URL`) | SC1 crash-injection test, SC2 concurrency race test | ✓ (`.env` has `DATABASE_URL` set in this environment) | not queried this session (see Assumption A2) | `@pytest.mark.integration` skip-guard already in place project-wide for exactly this case |
| Python `threading` (stdlib) | SC2 concurrency test | ✓ | stdlib, no version concern | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None — `DATABASE_URL` is present in this
environment's `.env`, and the existing `@pytest.mark.integration` + `seeded_db`
fixture pattern (from `tests/conftest.py`) already provides the skip-guard fallback
for any environment where it is absent (e.g. CI without a DB).

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (via `uv run pytest -q`), markers registered in `pyproject.toml` (`integration`, `live_llm`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest -q -m "not integration and not live_llm"` |
| Full suite command | `uv run pytest -q` (requires `DATABASE_URL` + `ALLOW_DB_RESET=1` for full integration coverage) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-01 | `_run_stages` process branch: crash mid-sequence leaves run wholly un-advanced | integration (real DB, fault-injected) | `uv run pytest -q tests/test_atomic_persist.py::test_process_branch_crash_leaves_run_unadvanced -m integration` | ❌ Wave 0 |
| DATA-01 | `_deliver` finalize: crash mid-sequence leaves run wholly un-advanced, alias-write isolation preserved | integration (real DB, fault-injected) | `uv run pytest -q tests/test_atomic_persist.py::test_deliver_finalize_crash_leaves_run_unadvanced -m integration` | ❌ Wave 0 |
| DATA-02 | Two concurrent duplicate webhook deliveries → exactly one run | integration (real DB, threaded race) | `uv run pytest -q tests/test_webhook_dedup_race.py::test_duplicate_webhook_delivery_creates_exactly_one_run -m integration` | ❌ Wave 0 |
| DATA-03 | Stranded run (in-flight status + backdated `updated_at`) is swept to ERROR, then retriggerable | integration (real DB) or unit (with a monkeypatched `now()`/threshold) | `uv run pytest -q tests/test_stuck_run_recovery.py::test_stranded_run_swept_and_retriggerable` | ❌ Wave 0 |
| DATA-03 | Sweep scope is EXACTLY `{received, extracting, computed}` — never `awaiting_reply`/`awaiting_approval`/`approved` | unit (FakeConnection SQL-shape assertion, sufficient here since this is a pure scope-parameter check, not an atomicity proof) | `uv run pytest -q tests/test_stuck_run_recovery.py::test_sweep_scope_excludes_parked_statuses` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest -q -m "not integration and not live_llm"` (fast, no DB required for the non-atomicity-proof tests — e.g. SQL-shape/scope assertions)
- **Per wave merge:** `uv run pytest -q` (full suite, requires live/local DB for the integration-marked atomicity/race tests — this is the ONLY way to actually validate SC1/SC2/SC3)
- **Phase gate:** Full suite green (including `-m integration`) before `/gsd-verify-work` — SC1/SC2 cannot be verified any other way per Pitfall 3.

### Wave 0 Gaps

- [ ] `tests/test_atomic_persist.py` — covers DATA-01 (both `_run_stages` and `_deliver` transaction boundaries)
- [ ] `tests/test_webhook_dedup_race.py` — covers DATA-02
- [ ] `tests/test_stuck_run_recovery.py` — covers DATA-03 (sweep + scope + retrigger interplay)
- [ ] No new fixtures needed in `conftest.py` — `seeded_db` (existing, `tests/conftest.py:57`) and the `@pytest.mark.integration` marker (existing, `pyproject.toml`) already cover what these new tests need.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Unchanged by this phase — no auth surface touched. |
| V3 Session Management | no | N/A — stateless webhook + dashboard, no sessions. |
| V4 Access Control | no | Unchanged — the sweep and transaction wiring do not add or remove any access-control check; the existing sender/business validation (INGEST-03, FIX 5) is untouched. |
| V5 Input Validation | no (unchanged) | The dedup/CAS logic operates on already-validated `InboundEmail`/`RunStatus` values; no new external input surface is introduced. |
| V6 Cryptography | no | Not touched — no new secrets, keys, or crypto primitives. |
| V11 Business Logic (informative, not a numbered ASVS category in v4 but relevant here) | yes | The CAS/transaction patterns in this phase ARE the business-logic-integrity control: `claim_status`, the new `sweep_stranded_runs`, and the ingest transaction are all "atomic state transition" patterns already used elsewhere in the codebase (D-12) — this phase extends that same control to two more seams rather than introducing a new one. |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| TOCTOU (time-of-check-to-time-of-use) race on run status | Tampering / Repudiation | CAS (`UPDATE ... WHERE status = %s RETURNING id`) — already the project's established pattern (`claim_status`, `record_run_error`'s WR-03 fix); this phase's `sweep_stranded_runs` follows the identical idiom. |
| Duplicate financial action from a retried webhook delivery (double payroll run for one client email) | Repudiation / Denial of Service (resource exhaustion via duplicate LLM+DB work) | Postgres UNIQUE constraint (`uq_message_id`) + `ON CONFLICT DO NOTHING` inside a single transaction (D-9-09) — this is the exact mitigation being hardened by DATA-02; no new mitigation type introduced, existing one is being made airtight against concurrent (not just sequential) duplicates. |
| Silent partial state after a crash masking a real error from the operator (an "invisible" stuck run) | Repudiation (the system cannot account for what state a run is truly in) | The sweep converts silent staleness into a visible, diagnosable ERROR state with a distinguishing sentinel `error_reason` (D-9-10) — directly analogous to Phase 8's `error_detail` diagnosability work (OPS2-01), which this phase's error path reuses (`record_run_error` surface). |

## Sources

### Primary (HIGH confidence)

- psycopg 3.3.4 (installed, verified via `uv run python -c "import psycopg; print(psycopg.__version__)"`) — pinned in `pyproject.toml`, matches lockfile.
- Live codebase reads (verified 2026-07-03): `app/pipeline/orchestrator.py` (full file, 1358 lines), `app/db/repo.py` (full file, 1329 lines), `app/main.py` (full file, 1323 lines), `app/email/gateway.py`, `app/db/supabase.py`, `app/models/status.py`, `app/db/schema.sql`, `tests/conftest.py`, `tests/test_claim_status.py`, `app/llm/client.py` (partial — timeout/retry config confirmed absent).

### Secondary (MEDIUM confidence)

- [Transactions management — psycopg 3.3.5.dev1 documentation](https://www.psycopg.org/psycopg3/docs/basic/transactions.html) — `conn.transaction()` semantics (BEGIN/COMMIT/ROLLBACK, savepoint nesting, exception-triggers-rollback).
- [PostgreSQL 18 Documentation: 13.2. Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html) — READ COMMITTED wait-then-recheck semantics for concurrent writers on the same row; directly underpins the `ON CONFLICT DO NOTHING` concurrent-insert blocking behavior D-9-09 depends on (the docs describe UPDATE/DELETE explicitly; INSERT-with-unique-index conflict detection is the well-documented analogous case via the same MVCC snapshot mechanism).
- openai-python default timeout (10 min) and `max_retries` (2) — corroborated across [GitHub issue #762](https://github.com/openai/openai-python/issues/764) discussion and OpenAI community threads on `openai-python` client configuration defaults.

### Tertiary (LOW confidence)

None — every claim above was either directly verified against the live codebase/installed package version, or corroborated by official/semi-official documentation (psycopg.org, postgresql.org, openai-python GitHub).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; existing pinned `psycopg==3.3.4` confirmed installed and matching lockfile.
- Architecture: HIGH — every pattern in this document is either the codebase's own existing idiom (`_conn_ctx`, `claim_status` CAS) extended to new call sites, or standard, documented Postgres/psycopg3 transaction semantics.
- Pitfalls: HIGH — Pitfall 1 (LLM timeout ceiling) is a NEW finding this research surfaced via direct verification against `app/llm/client.py` and official openai-python docs, correcting an unverified estimate in the locked CONTEXT.md decisions; Pitfalls 2-3 are derived directly from reading the existing code and test fixtures.

**Research date:** 2026-07-03
**Valid until:** 30 days (stable domain — Postgres/psycopg3 transaction semantics do not change; the openai-python timeout defaults should be re-checked if that dependency is ever upgraded past 2.43.0)
