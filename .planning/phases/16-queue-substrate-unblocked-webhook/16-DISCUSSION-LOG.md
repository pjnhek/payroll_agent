# Phase 16: Queue Substrate & Unblocked Webhook - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-14
**Phase:** 16-Queue Substrate & Unblocked Webhook
**Areas discussed:** Mid-run reclaim semantics, CI proof surface, Worker posture in dev/test, Retrigger operator UX

**Not re-asked (already locked upstream):** the `jobs` table shape, the `FOR UPDATE SKIP LOCKED` claim
SQL with expired-lease reclaim, lease-token fencing, `attempts`-at-claim, graceful lease release,
2 daemon threads under `lifespan`, zero new dependencies, env-driven config, schema delivery via
`schema.sql` + `bootstrap` + `deploy-migrate` + `/health/schema`, and the retrigger `dedup_key`
(`run_pipeline:{run_id}:{reply_epoch}`). All fully specified in the design doc and
`.planning/research/ARCHITECTURE.md` §3–§4.

---

## Mid-run reclaim semantics

**The trap surfaced during discussion:** a worker dies mid-pipeline holding the lease, leaving the run
at `EXTRACTING`/`COMPUTED`. A reclaiming worker calls `run_pipeline` against a run whose status no
longer matches the expected `RECEIVED`, so the CAS fails. A naive reading of INVARIANT J-1 ("a failed
CAS is a DONE job") marks the job `done` and strands the run forever — violating success criterion #2.

### Q1 — What should the handler do on a failed CAS?

| Option | Description | Selected |
|--------|-------------|----------|
| Rewind only on reclaim | `attempts > 1` → rewind to RECEIVED and re-run; `attempts == 1` → failed CAS means someone else advanced it → job `done` (strict J-1). The attempts counter is the discriminator. | ✓ |
| Rewind unconditionally | Every handler entry force-resets to RECEIVED. Simplest, but disarms the CAS entirely — a duplicate delivery would re-run a payroll another worker is actively processing. | |
| Strict J-1, no rewind | Failed CAS → job done, no re-run. Purest, but a mid-pipeline crash strands the run until a human re-clicks; criterion #2 would have to be narrowed to the vacuous case. | |

**User's choice:** Rewind only on reclaim.
**Notes:** `attempts` is already incremented at claim (QUEUE-02, for poison-job bounding), so the
discriminator is free. Pulls part of Phase 18's "rewind preamble" forward, deliberately — it lands
where its proof lives.

### Q2 — Should the automatic rewind bump `reply_epoch`?

**Why it matters:** the epoch mints a fresh `message_id` under `uq_email_run_purpose_round_epoch`. An
operator retrigger bumping it is the *documented, deliberate* residual risk. A machine bumping it
would silently widen that license and break the milestone's headline claim.

| Option | Description | Selected |
|--------|-------------|----------|
| Never bump on auto-rewind | Rewind resets status + derived state but preserves the epoch. Only an explicit operator click bumps it. Needs a rewind path distinct from `clear_reply_context`. | ✓ |
| Reuse `clear_reply_context` as-is | One function, already tested — but every automatic reclaim silently opens a new epoch, and the DB constraint enforcing the headline claim stops covering the auto-recovery path. | |

**User's choice:** Never bump on auto-rewind.
**Notes:** Consequence, and it's the right one — a run that crashed between `SENT` and `RECONCILED` is
reclaimed, rewound, re-run, and delivery's already-sent guard suppresses the second email *because the
epoch still matches*.

### Q3 — What protects a slow-but-alive worker from having its lease expire underneath it?

| Option | Description | Selected |
|--------|-------------|----------|
| Generous fixed lease + document | Size `LEASE_SECONDS` well above observed worst-case pipeline runtime; write down the number, its derivation, and the double-run-is-harmless argument. No new machinery. | ✓ |
| Lease heartbeat | Worker extends `leased_until` while working. Strictly safer, but burns a connection per extension against the `max_size=5` budget and adds a heartbeat-dies-but-work-continues failure mode. | |
| Short lease, accept double-run | Keep 5 min and lean entirely on the idempotence guards. Fastest recovery, but makes the double-run routine rather than exceptional. | |

**User's choice:** Generous fixed lease + document.

---

## CI proof surface

**Context:** criteria 2, 3, and 4 all need a real Postgres. `concurrency-proof.yml:89` is the only
workflow that has one, and it selects test files **by name** — its own comment warns that an unlisted
live-DB test "will skip silently and forever."

### Q1 — How do this phase's durability tests get into CI?

| Option | Description | Selected |
|--------|-------------|----------|
| Generalize the workflow now | `pytest tests/ -m integration` so any marked test is collected automatically, forever. Keep the skip-guard so a mis-collection reds the build loudly. | ✓ |
| Just append the filename | One line, zero risk — but the landmine stays armed for Phases 18/20/21, and a forgotten append is silent. | |
| Defer to Phase 21 | Land the proofs as local-only tests. Means five phases of unverified durability claims — the exact pattern the milestone was written to avoid. | |

**User's choice:** Generalize the workflow now.
**Notes:** This is the milestone's own named cross-cutting hazard #1, and Phase 16 is the first phase
to trip it. Research recommended the same pull-forward independently (`ARCHITECTURE.md` §8 Q3).

### Q2 — The `jobs` table breaks two magic-number guards in `test_status_drift.py`.

| Option | Description | Selected |
|--------|-------------|----------|
| Replace counts with inventory | Pin against a harvested inventory of actual index/constraint names, so the guard stays meaningful as the schema grows. | ✓ |
| Just bump the numbers | 3→4 and 2→3. Minimal diff — but the test named `test_status_exact_count_is_ten` already asserts 11, so it has demonstrably rotted once. | |
| You decide | Let the planner pick after reading what the guard protects. | |

**User's choice:** Replace counts with inventory.

---

## Worker posture in dev/test

**Context surfaced by the scout:** the entire existing suite depends on TestClient running
`BackgroundTasks` **synchronously** — tests POST a route and immediately assert the pipeline already
ran. Moving retrigger onto a queue makes that untrue for its tests.

### Q1 — How should tests exercise the queue?

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit `drain_once()` in tests | Workers off under test. Test POSTs, asserts a `jobs` row, calls `drain_once()` directly, asserts the pipeline ran. Deterministic; exercises the exact function the pump and the threads both call. | ✓ |
| Real worker threads + wait | Closest to end-to-end, but every test gains a timing window — a flake factory on a slow CI box. | |
| Inline executor in test mode | Existing tests pass untouched, but it bypasses claim/lease/fencing entirely — tests stay green with the queue completely broken. | |

**User's choice:** Explicit `drain_once()` in tests.
**Notes:** Aligns with PROOF-05's standing mandate — races drive the sync seam under a
`threading.Barrier`, never an HTTP route. This repo has already shipped one "concurrency proof" whose
threads serialized through an async route and proved nothing.

### Q2 — What happens if a bad `WORKER_COUNT` violates `workers + 2 ≤ max_size=5` at startup?

| Option | Description | Selected |
|--------|-------------|----------|
| Hard fail at boot | Lifespan asserts the budget and refuses to start. A misconfigured deploy fails loudly instead of booting into silent connection starvation. | ✓ |
| Clamp and warn | Service always boots; the misconfiguration survives unnoticed at the wrong concurrency. | |

**User's choice:** Hard fail at boot.

---

## Retrigger operator UX

**Context:** the retrigger CAS already lands the run at `RECEIVED`, which is in `IN_FLIGHT_STATUSES`
and already drives the run page's auto-refresh. The only real degradation is latency — how long the run
sits at `RECEIVED` before a worker picks it up.

### Q1 — How does a worker learn there's a job to do?

| Option | Description | Selected |
|--------|-------------|----------|
| In-process wake + slow poll | `threading.Event` set after the enqueue **commits** wakes an idle worker instantly (same process). Slow DB poll (~15–30s) remains as the durable fallback for future-dated retries, expired-lease reclaims, and cold starts. | ✓ |
| Fast poll only | Simple, near-instant — but constant claim-query chatter against a 5-connection free pool, forever, for ~1 email/client/week. | |
| Slow poll only | Cheapest — but a dead pause of up to 30s after clicking Retrigger during a recorded demo, and "a clean 60–90s demo" is a stated project priority. | |

**User's choice:** In-process wake + slow poll.
**Notes:** `LISTEN/NOTIFY` is banned under Supavisor transaction-mode pooling (it fails *silently*) —
but the design never noticed the producer and consumer share a process. The wake must fire **after**
commit, or the worker races and finds no row.

### Q2 — Should the run page show a distinct "queued" state?

| Option | Description | Selected |
|--------|-------------|----------|
| No UI change | `RECEIVED` + existing auto-refresh already communicates "working on it." Queue depth / attempts / dead-letter are explicitly OPS-01 (Phase 21). | ✓ |
| Add a queued indicator | More honest about what the system is doing — but it's the first slice of the ops view and would be rebuilt in Phase 21 anyway. | |

**User's choice:** No UI change.

---

## Claude's Discretion

- **No `ON DELETE CASCADE`** from `payroll_runs` to `jobs` — keep attempt history append-only,
  matching the deliberate `email_messages` precedent. (Resolves `ARCHITECTURE.md` §8 Q4.)
- Exact numeric values for `LEASE_SECONDS`, the poll interval, and `MAX_ATTEMPTS` — derived from the
  pipeline's measured runtime, with the derivation documented.
- The precise `jobs` index set and the shape of the inventory-pinned guard rewrite.

## Deferred Ideas

- **`operator_resume` `dedup_key` discriminator** (`ARCHITECTURE.md` §8 Q1) — that producer doesn't
  migrate until **Phase 19**. Decide it there.
- **Ops view** (queue depth, oldest-pending age, attempts, dead-letter, the swallowing-bug alarm) —
  **OPS-01, Phase 21.**
- **Deleting `sweep_stranded_runs` / `find_stranded_unconsumed_replies` / the `runs_list()` sweep
  block** — **FAIL-03, Phase 18.** Nothing for the sweep to race in Phase 16, since only retrigger is
  on the queue.
- **The orchestrator's `ok`/`retryable`/`terminal` result contract** — **FAIL-01, Phase 18.** Phase 16
  accepts that a failed retrigger job records `done`; today's `BackgroundTasks` retrigger swallows
  identically, so this is not a regression.
- **Migrating the other 7 `BackgroundTasks` producers** — **QUEUE-04, Phase 19.**
- **Versioned migrations + a hard deploy gate** — pre-existing backlog item, unchanged.
