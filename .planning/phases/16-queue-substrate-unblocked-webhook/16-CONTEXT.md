# Phase 16: Queue Substrate & Unblocked Webhook - Context

**Gathered:** 2026-07-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Two things land, and nothing else:

1. **The inbound webhook stops blocking the event loop.** The synchronous Resend body-fetch
   (`webhook.py:96` → `gateway.py:175`, a blocking `resend.EmailsReceiving.get()` on an `async def`
   route) and the synchronous psycopg ingest transaction (`webhook.py:139-220`) move off-loop via
   `run_in_threadpool`. The route stays `async def` because HMAC verification needs
   `await request.body()` over the raw bytes. **Zero new schema.**

2. **A durable Postgres job queue exists** — the `jobs` table, the `FOR UPDATE SKIP LOCKED` claim
   protocol with expired-lease reclaim, lease-token fencing, 2 daemon worker threads managed by a
   new FastAPI `lifespan`, and graceful lease release on shutdown — **proven on exactly one
   producer: the operator "Retrigger" button** (`runs.py:266-381`). The lowest-risk, already-manual
   path. Nothing on the money path moves.

`BackgroundTasks` and the queue coexist for exactly this one phase, safely, because each producer
uses exactly one mechanism. The other 7 `add_task` sites are untouched until Phase 19.

**Requirements:** QUEUE-01, QUEUE-02, QUEUE-03, QUEUE-05.

</domain>

<decisions>
## Implementation Decisions

### Mid-run reclaim semantics (the money-adjacent one)

The trap: operator retriggers → CAS `ERROR → RECEIVED` → job enqueued → worker W1 starts
`run_pipeline`, advancing the run to `EXTRACTING`/`COMPUTED` → W1's process dies. The lease expires,
W2 reclaims the job and calls `run_pipeline` against a run at `COMPUTED`. The orchestrator's internal
`RECEIVED → EXTRACTING` CAS fails. Under a naive reading of INVARIANT J-1 ("a failed CAS is a DONE
job, not a retry") the job goes `done` and **the run is stranded forever** — which is exactly what
success criterion #2 forbids.

- **D-01: Rewind only on reclaim, discriminated by `attempts`.** If `attempts > 1`, this is a
  reclaim after a crash → the handler rewinds the run to `RECEIVED` (clearing derived pipeline
  state) and re-runs from scratch. If `attempts == 1`, a failed CAS means another worker
  legitimately advanced the run → mark the job `done`, do nothing (**strict J-1 preserved where it
  actually applies**). The `attempts` counter — incremented *at claim*, per QUEUE-02 — is the
  discriminator between "someone else already did this" and "the previous me died halfway."
  This pulls part of Phase 18's planned "rewind preamble" forward, deliberately: it lands where its
  proof lives.

- **D-02: The automatic rewind MUST NOT bump `reply_epoch`.** `clear_reply_context`
  (`repo/runs.py`, called at `runs.py:378`) bumps the epoch, and the epoch is what mints a fresh
  `message_id` under `uq_email_run_purpose_round_epoch` (`schema.sql:279`). That bump is the
  *deliberate, documented* residual risk for an **operator** retrigger (REQUIREMENTS.md → "Accepted
  residual risk"). If an **automatic** reclaim also bumped it, the machine would silently grant
  itself the same license to send a second confirmation, and the milestone's headline claim ("at
  most one confirmation per approved run, **per epoch**") would stop being enforceable by the DB
  constraint that backs it. **The rewind path must be distinct from `clear_reply_context`** (or take
  a `bump_epoch=False` flag). Consequence, and it is the right one: a run that crashed between
  `SENT` and `RECONCILED` is reclaimed, rewound, re-run — and delivery's already-sent guard
  (`get_outbound_message_id(purpose='confirmation')`) suppresses the second email *because the epoch
  still matches*.

- **D-03: `LEASE_SECONDS` is a load-bearing safety parameter, generously sized and documented.**
  Rewinding makes the CAS always succeed, so the lease becomes the only thing standing between a
  *slow-but-alive* worker and a genuine double-run. Set it well above the pipeline's observed worst
  case (the pipeline is ~1–2 LLM calls + a PDF), and write down, as a constraint comment: the chosen
  number, the measured runtime it is derived from, and the double-run-is-harmless argument
  (delivery's already-sent guard + `replace_line_items`' delete-then-insert idempotence — the same
  argument `retrigger`'s own docstring already makes for allowing stale `SENT` claims). **No lease
  heartbeat** — it would burn a connection per extension against the `max_size=5` budget and add a
  failure mode (heartbeat thread dies, work continues) worse than the one it prevents.

### CI proof surface

- **D-04: Generalize `concurrency-proof.yml` NOW, in this phase.** Change line 89 from a hard-coded
  file list (`tests/test_concurrency_proof.py tests/test_email_epoch_arbiter_integration.py`) to
  collection over the whole suite (`pytest tests/ -m integration`), so **any** `@pytest.mark.integration`
  test is picked up automatically, forever. **Keep the existing skip-guard** (lines 90–97) — it reds
  the build on any skip, which turns a mis-collected test into a loud failure instead of a silent
  one. Note `deselected` ≠ `skipped`, so the guard does not false-positive on hermetic tests.
  Rationale: this is the milestone's own named cross-cutting hazard #1, Phase 16 is the first phase
  to trip it (criteria 2, 3, and 4 all need a real Postgres), and fixing it here means Phases 17–21
  add proofs with zero workflow edits. Research recommended this pull-forward independently
  (`ARCHITECTURE.md` §8 Q3).

- **D-05: Replace the magic-number guards in `tests/test_status_drift.py` with inventory-pinned
  assertions.** The `jobs` table will detonate two of them on contact:
  `test_exactly_three_new_indexes` asserts `sql.count("CREATE INDEX IF NOT EXISTS") == 3`
  (`test_status_drift.py:329`), and `test_do_block_constraint_drops_are_column_anchored` asserts
  `sql.count("ANY (c.conkey)") == 2` (`:228`). Do **not** just bump 3→4 and 2→3 — pin against a
  harvested inventory of the actual index/constraint names so the guard stays meaningful as the
  schema grows. (Evidence it already rots: `test_status_exact_count_is_ten` asserts `== 11`.)

### Worker posture, tests, and config

- **D-06: Workers are OFF under test; tests call `drain_once()` explicitly.** The entire existing
  suite depends on TestClient running `BackgroundTasks` **synchronously** — tests POST a route and
  immediately assert the pipeline already ran (`tests/test_webhook.py`, `test_concurrency_proof.py:99`,
  `test_webhook_dedup_race.py:51`). Moving retrigger to the queue breaks that for retrigger's tests.
  The fix: a test POSTs Retrigger, asserts a `jobs` row exists, then calls `drain_once()` directly
  and asserts the pipeline ran. Deterministic, no sleeps, no flakes — and it exercises the **exact**
  function the pump (Phase 17) and the worker threads both call, so the test proves the real path.
  Aligns with PROOF-05's mandate: races drive the **sync seam** under a `threading.Barrier`, never an
  HTTP route. Explicitly rejected: real threads + polling (a flake factory), and a test-mode inline
  executor (would stay green with the queue completely broken — the vacuous-proof pattern).

- **D-07: A pool-budget violation hard-fails at boot.** The `lifespan` asserts
  `WORKER_COUNT + 2 ≤ pool max_size (5)` (`supabase.py:60`) and **refuses to start** if violated. A
  misconfigured deploy fails loudly and visibly on Render rather than booting into a state where
  requests silently hang waiting for a connection the workers have all checked out. Fail-fast on a
  startup-time config error is the money-system default. (Not: clamp-and-warn.)

- **D-08: Config knobs are env-driven** (`WORKER_COUNT`, `LEASE_SECONDS`, `MAX_ATTEMPTS`), using the
  repo's existing CI-gated `pydantic-settings` machinery. `WORKER_COUNT=0` is the test/dev off switch.

### Retrigger operator UX

- **D-09: In-process wake + slow durable poll.** `LISTEN/NOTIFY` and session advisory locks are
  banned under Supavisor transaction-mode pooling (they fail *silently*) — but the retrigger route
  and the worker threads live in the **same process**. After the enqueue transaction **commits**, set
  a `threading.Event` that wakes an idle worker immediately, so Retrigger stays instant for the
  60–90s demo. Demote DB polling to a **slow durable fallback** (~15–30s) covering what the in-process
  signal cannot: future-dated backoff retries (Phase 18), expired-lease reclaims, and a cold-started
  instance where the enqueuing process no longer exists. Result: the DB is never the latency path for
  the common case, and there is no constant claim-query chatter against a 5-connection free-tier pool
  for a system handling ~1 email/client/week. **The wake must fire after commit**, never inside the
  transaction, or the worker races and finds no row.

- **D-10: No UI change in this phase.** The retrigger CAS already lands the run at `RECEIVED`, which
  is in `IN_FLIGHT_STATUSES` (`runs.py:79-81`) and therefore already drives the run page's
  auto-refresh — the operator already sees "working on it" and watches it advance. Queue depth,
  oldest-pending age, attempts, and the dead-letter list are explicitly **OPS-01 (Phase 21)**;
  building a job-status UI now is scope creep into that phase.

### Claude's Discretion

- **No `ON DELETE CASCADE` from `payroll_runs` to `jobs`.** Keep the attempt history append-only,
  matching the deliberate `email_messages` precedent. (Resolves `ARCHITECTURE.md` §8 Q4. Runs are
  never deleted today, so this is theoretical either way — but a cascade would silently vaporize a
  run's attempt history, which is the one thing the queue exists to make auditable.)
- Exact numeric values for `LEASE_SECONDS`, the poll interval, and `MAX_ATTEMPTS` — pick them from
  the pipeline's measured runtime and **document the derivation** (D-03).
- The precise `jobs` index set and the shape of the inventory-pinned guard rewrite (D-05).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The approved design (authoritative — this phase is largely transcription, not design)
- `docs/superpowers/specs/2026-07-13-durable-execution-design.md` — the approved v4 design, revised
  2026-07-14 after adversarial research. **§"The `jobs` table"** (columns), **§"The claim protocol —
  CORRECTED"** (the exact SQL, with the expired-lease reclaim fix), **§"Graceful shutdown"**,
  **§"Two state machines, one authority — INVARIANT J-1"**.
- `.planning/research/ARCHITECTURE.md` **§3** (`dedup_key` scheme + the `enqueue_job` SQL), **§4**
  (the full claim/lease/fencing protocol and the `CREATE TABLE jobs` DDL — *"this is transcription,
  not design"*), **§8** (open questions; Q3 and Q4 are resolved by D-04 and Claude's Discretion above).
- `.planning/research/SUMMARY.md` — the 4-researcher adversarial validation. C1 (the claim SQL cannot
  reclaim an expired lease — **the fix is already baked into the design's SQL**), C7 (the lease fences
  the `jobs` row only; the **CAS** is the correctness), C9 (graceful lease release).
- `.planning/REQUIREMENTS.md` — QUEUE-01/02/03/05 verbatim, plus **"Accepted residual risk"** (the
  epoch-bump license that D-02 protects) and **"Out of Scope"** (no fairness, no priority lanes, no
  backpressure, no circuit breakers, no `uvicorn --workers N`).
- `.planning/ROADMAP.md` § "Phase 16" — the 5 success criteria this phase is graded against.

### Code seams this phase modifies (read before planning)
- `app/routes/webhook.py:29-30` (async route), `:57` (`await request.body()` — why it stays async),
  `:63-85` (HMAC), **`:95-106`** (the blocking Resend fetch), **`:139-220`** (the blocking ingest
  transaction). The docstring at `:112-130` explicitly pins "the transaction commits BEFORE
  `add_task`" — that comment needs rewriting when the enqueue moves inside the transaction.
- `app/email/gateway.py:158-175` — `_parse_resend_envelope`; `:175` is the sync HTTP call on the loop.
- `app/routes/runs.py:266-381` — **the one producer being cut over.** The CAS claims (`:312-316`),
  the stale in-flight fallback (`:318-366`, scope = 4 statuses, deliberately divergent from the
  sweep's 3 — see the DO-NOT-CONVERGE comment at `:327-337`), and `:378-380`
  (`clear_reply_context` → `add_task(run_pipeline_bg)`).
- `app/routes/pipeline_glue.py:195/210/227` — the three background entrypoints that become job
  handlers. Note the BOUND-01 module-object import discipline (`:1-8`): a dispatcher resolving
  handlers by name must preserve the monkeypatch seams.
- `app/db/supabase.py:38-70` — the pool. **`max_size=5` at `:60`** is the hard budget behind D-07.
- `app/db/repo/_shared.py:19-48` — `_conn_ctx(conn)` / `_nulltx()`. **The convention a new
  `app/db/repo/jobs.py` must follow**: every function takes `conn: psycopg.Connection | None = None`,
  so `enqueue_job(..., conn=conn)` drops straight into the retrigger route's existing transaction.
- `app/db/repo/__init__.py` — the facade (~55 re-exported names). New job functions must be exported
  here.
- `app/main.py` — **16 lines, no `lifespan`, no `on_event`.** The worker start/stop wiring is net-new.
- `app/db/schema.sql` + `app/db/bootstrap.py` — **no migrations directory**; schema.sql is applied
  whole-file and idempotently. `deploy-migrate.yml` runs `python -m app.db.bootstrap` (additive, no
  `--reset`) on push to master, then `check_schema`. `/health/schema` (`app/routes/health.py:50-73` →
  `app/db/schema_introspect.py`) is the live drift probe — **confirm whether a new table is
  auto-covered by `diff_against_live` or needs registration.**
- `app/models/status.py` — `RunStatus`, 11 members. `jobs.kind` values must never collide with these
  (success criterion #5).

### CI / test landmines (all confirmed by direct read — every one of these will bite)
- **`.github/workflows/concurrency-proof.yml:89`** — the only workflow with a real Postgres, and it
  selects test files **by name**. Its own comment (`:65-68`): *"A new live-DB test that is not added
  to this list will skip silently and forever."* → **D-04 fixes this.**
- **`tests/test_status_drift.py:329`** (`CREATE INDEX` count `== 3`) and **`:228`** (`ANY (c.conkey)`
  count `== 2`) — both break when `jobs` lands. → **D-05.**
- **`tests/conftest.py:994-1052`** — the `fake_repo` hard-coded monkeypatch **name tuple**. Its own
  comment (`:1033-1036`): a method on `InMemoryRepo` that is **missing from this tuple** is *silently*
  never patched — no error, just a fall-through to the real DB. Every new `jobs` repo function
  (`enqueue_job`, `claim_job`, `mark_done`, `release_lease`, …) must be added **both** to
  `InMemoryRepo` **and** to this tuple.
- **`tests/test_threading.py:340-354` and `:421-435`** — two *more* hard-coded tuples with the same
  silent-fallthrough hazard. **Three tuples total must be kept in sync, not one.**
- The suite-wide assumption that **TestClient runs `BackgroundTasks` synchronously** — this is what
  D-06 addresses for the retrigger path.
- `tests/test_bound01_private_imports.py` — `SCAN_ROOTS = ["app", "eval", "scripts"]`, so a new
  `app/queue/` package is auto-scanned; any cross-module `_private` reference there fails CI.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`_conn_ctx(conn)` / caller-owns-transaction** (`app/db/repo/_shared.py:19-48`): the enqueue drops
  directly into the retrigger route's existing transaction with no new plumbing. This is the single
  most load-bearing existing pattern for this phase.
- **`claim_status(expected → next)` CAS** (`app/db/repo/runs.py`): already the repo's proven
  conditional-advance idiom, already used by `retrigger` at `runs.py:312-316`. INVARIANT J-1 is not a
  new mechanism — it's this one, applied to job handlers.
- **`clear_reply_context`** (called at `runs.py:378`): already clears `clarified_fields`,
  `pre_clarify_extracted`, the round counter, and suggestion state — i.e. it *is* the rewind, except
  for the epoch bump that D-02 forbids on the automatic path.
- **`gen_random_uuid()` / `pgcrypto`** (`schema.sql:13`): already the PK default on 6 tables; the
  lease token needs no new extension.
- **Delivery's already-sent guard** + **`replace_line_items`' delete-then-insert**: the two existing
  idempotence properties that make a rewind-and-re-run harmless. They are why D-01 is safe.
- **The `RunStatus` ↔ SQL CHECK drift test** (`tests/test_status_drift.py`): the exact guard shape to
  imitate for success criterion #5 (`jobs.kind` ↔ `JobKind` ↔ the SQL CHECK).

### Established Patterns
- **Zero new dependencies** (validated by all 4 researchers). `SKIP LOCKED`, `gen_random_uuid()`,
  transactional enqueue, `threading.Thread`, `run_in_threadpool`, FastAPI `lifespan` — all already
  present or stdlib.
- **Supavisor transaction-mode pooling** (`app/db/supabase.py:1-18`, `prepare_threshold=None`):
  **no session state, no `LISTEN/NOTIFY`, no session advisory locks** — they fail *silently*, not
  loudly. Row leases + CAS only. This is what forces D-09's in-process wake.
- **SQL discipline** (`_shared.py:4-9`): pooled connection, `%s` placeholders, never f-strings.

### Integration Points
- `app/main.py` gains its **first** `lifespan` (start/stop N daemon workers; release held leases on
  shutdown; assert the pool budget).
- `app/db/schema.sql` gains the `jobs` table (+ indexes + CHECKs) — applied by the existing
  `bootstrap` / `deploy-migrate` path, monitored by `/health/schema`.
- New: `app/models/job.py` (`JobKind`/`JobState`), `app/db/repo/jobs.py`, `app/queue/{worker,dispatch}.py`.
- `app/routes/runs.py:380` — the single `add_task` → `enqueue_job` swap. The other 7 `add_task` sites
  stay untouched.

</code_context>

<specifics>
## Specific Ideas

- **The `attempts` counter is the reclaim discriminator** (D-01) — this is the one genuinely novel
  idea from the discussion, and it is what lets the phase satisfy success criterion #2 *without*
  abandoning INVARIANT J-1. `attempts` is already incremented **at claim** (QUEUE-02, for poison-job
  bounding), so the signal is free.
- **In-process `threading.Event` wake** (D-09) — the design doc reaches for polling because
  `LISTEN/NOTIFY` is unavailable, but never notices that the producer and the consumer are in the
  same process. Instant demo latency with no DB chatter and no new machinery.
- **"The queue let me delete the three recovery hacks"** is the story (per `ARCHITECTURE.md` §7) —
  but that deletion is **Phase 18**, not this one. Phase 16 must resist starting it.

</specifics>

<deferred>
## Deferred Ideas

- **The `operator_resume` `dedup_key` discriminator** (`ARCHITECTURE.md` §8 Q1) — an operator may
  legitimately re-resolve a `needs_operator` run with a *different* name mapping without an epoch
  bump, and `ON CONFLICT DO NOTHING` would swallow the second resolve. **Not a Phase 16 problem:**
  that producer (`runs.py:262`) does not migrate until **Phase 19**. Decide it there.
- **Ops view** — queue depth, oldest-pending age, attempts distribution, dead-letter list, and the
  swallowing-bug alarm (*job success ≈100% while `status='error' > 0`*). This is **OPS-01, Phase 21**.
  D-10 deliberately keeps it out of this phase.
- **Deleting `sweep_stranded_runs` / `find_stranded_unconsumed_replies` / the `runs_list()` sweep
  block** — **FAIL-03, Phase 18.** The sweep and the queue must not coexist long-term (they race), but
  in Phase 16 only the *retrigger* producer is on the queue, so there is nothing yet for the sweep to
  race. Do not start the deletion here.
- **The orchestrator's `ok`/`retryable`/`terminal` result contract** — **FAIL-01, Phase 18.** In Phase
  16 the orchestrator still swallows stage failures and returns normally, so a retrigger job whose
  pipeline errors will be recorded `done`. This is **not a regression**: today's `BackgroundTasks`
  retrigger swallows identically, and the run still lands visibly in `ERROR` for the operator. Accept
  the window; it closes in Phase 18, which is why the roadmap forces Phase 18 *before* the webhook
  cutover.
- **Migrating the other 7 `BackgroundTasks` producers** — **QUEUE-04, Phase 19.**
- **Versioned migrations + a hard deploy gate** — pre-existing backlog item, unchanged by this phase.

</deferred>

---

*Phase: 16-Queue Substrate & Unblocked Webhook*
*Context gathered: 2026-07-14*
