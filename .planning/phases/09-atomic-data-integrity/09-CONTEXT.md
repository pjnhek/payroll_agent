# Phase 9: Atomic Data Integrity - Context

**Gathered:** 2026-07-02
**Status:** Ready for planning

<domain>
## Phase Boundary

The data layer becomes correct under concurrency and crashes — the senior-engineer ring of v2. Three requirements, all backend/logic:

1. **DATA-01 (atomic multi-writes, audit HIGH-03):** the persist+branch+status sequence in `orchestrator._run_stages` and the send+alias+status sequence in `_deliver` commit atomically — a crash injected mid-sequence leaves the run wholly un-advanced, never half-written.
2. **DATA-02 (transactional webhook dedup, audit HIGH-04):** duplicate/concurrent Resend deliveries for one inbound `message_id` produce exactly one payroll run; the ingest path can no longer strand an email row with no run.
3. **DATA-03 (stuck-run recovery, audit MED-05):** a run whose background task died mid-flight (`received`/`extracting`/`computed`) is recoverable without waiting out an over-long stale threshold.

Not in scope: new run states or state-machine capabilities (loop cap), security-hygiene items, the concurrency proof test itself (Phase 10 asserts these invariants under real parallelism), any UI beyond what recovery strictly needs.

**Discussion mode note:** the user selected all four gray areas and delegated the approach decisions to Claude ("you decide on the best approach for all of this"). The decisions below were made by Claude after tracing the live code (orchestrator.py, main.py, repo.py, gateway.py, supabase.py) and are LOCKED for research/planning; the researcher should validate mechanics (psycopg3 transaction semantics, ON CONFLICT blocking behavior), not re-open the approach.

</domain>

<decisions>
## Implementation Decisions

### Core atomicity principle
- **D-9-01 No DB transaction ever spans an LLM call or a provider (Resend) call.** "Atomic" for this system means: every run of consecutive DB writes between external side effects commits in ONE `conn.transaction()`. Wrapping a network call in a DB transaction is rejected twice over: (a) a rollback after a successful send makes the DB assert "no email sent" when one WAS sent — a lie worse than the crash it guards; (b) it pins a pooled connection (pool max=5) across multi-second network latency. If DATA-01's literal wording ("the send+alias+status sequence … in a single transaction") matters at phase close, update REQUIREMENTS.md wording per the D-8-11 precedent — the honest claim is "all DB writes between side effects are atomic; the side effect itself is bracketed by durable intent/outcome markers (D-13c reserved/sent/failed)".
- **D-9-02 Status-advance-last invariant.** Within any atomic unit, the run-status write is the LAST statement before commit — a run is only ever observable in an advanced status when all data that status implies is already committed. This is what makes a crash leave the run "wholly un-advanced" (success criterion 1) rather than half-written.
- **D-9-03 Mechanism = the existing `conn=` seam.** Nearly every repo helper already accepts `conn=` (`_conn_ctx` pattern, Phase 2 decision). The orchestrator/webhook opens one pooled connection per atomic unit (`get_connection()` + `conn.transaction()`) and threads it through the repo calls. No new abstraction, no ORM, no unit-of-work class — plain psycopg3 transactions over the seam built for exactly this.

### Transaction granularity in `_run_stages` (DATA-01, part 1)
- **D-9-04 Process branch = ONE transaction.** `persist_extracted` + `persist_decision` + `persist_reconciliation` + `replace_line_items` + `set_status(COMPUTED)` + `set_status(AWAITING_APPROVAL)` all commit together (no external side effects on this branch — pure DB). Note `_compute_line_items` is pure computation; run it BEFORE opening the transaction so a calc exception never opens a doomed txn.
- **D-9-05 Clarify branch = persist-txn, then `_clarify` as its own post-commit unit.** The three data persists commit in one transaction (run status remains in-flight, un-advanced); `_clarify` runs after that commit because it contains two LLM calls (suggestion + draft) and a provider send. Crash anywhere inside `_clarify` leaves the run with persisted data but an un-advanced status — which is exactly the stranded-in-flight shape D-9-10's recovery sweep handles, and `_clarify`'s existing CLAR-04 idempotency guard makes retriggered re-entry safe (no duplicate clarification email once a row is `sent`).
- **D-9-06 Inside `_clarify`/`_deliver`, post-send DB writes are one finalize transaction.** For `_clarify`: flip-to-sent + `set_pre_clarify_extracted` + `set_status(AWAITING_REPLY)` commit together after the send returns (the snapshot's IS NULL guard keeps this idempotent; planner may order the snapshot write before the send if tracing shows that's safer — the locked part is that the status advance commits last, D-9-02). The alias-candidates write (`set_alias_candidates`) joins whichever unit it currently precedes. Resume-path (`resume_pipeline`) multi-writes get the same treatment — same principle, planner maps the exact sequences.

### `_deliver` and the un-rollbackable send (DATA-01, part 2)
- **D-9-07 Keep D-13c's reserved-before-send in its own commit; add a post-send finalize transaction.** The `send_state='reserved'` row MUST commit before the provider call (it is the durable crash marker — folding it into a later transaction would erase the evidence a crash needs). After `gateway.send_outbound` returns, ONE transaction commits: flip reserved→sent + alias write (`_write_aliases_if_safe`, still try/except-isolated per D-13b — its failure must not roll back the delivery finalize) + `set_status(SENT)` + `set_status(RECONCILED)`.
- **D-9-08 Delivery semantics = at-least-once, explicitly.** Crash window: Resend accepted the email but the finalize txn never committed → row still `reserved`, run still APPROVED → operator retrigger re-runs `_deliver`, the CLAR-04 sent-guard (which counts only `send_state='sent'` as proof) does NOT suppress, and the confirmation is re-sent. A duplicate confirmation email to the client is accepted as benign; a never-delivered payroll confirmation is not. Document this choice in the code comment at the finalize seam. (The D-13c upsert on `(run_id, purpose)` already makes retry-over-reserved advance instead of crash.)

### Webhook dedup CAS (DATA-02)
- **D-9-09 Single-transaction ingest closes the orphan window; the loser reports, it does not repair.** Wrap the webhook's DB sequence — `insert_inbound_email` (ON CONFLICT DO NOTHING) + routing/sender reads + `create_run` — in ONE transaction on one connection, committed BEFORE `background_tasks.add_task` is called (a background task must never race a not-yet-committed row; note TestClient runs BackgroundTasks synchronously after the response — verify the enqueue-after-commit ordering holds in both prod and test paths). Consequences, which ARE the CAS design the audit warned about:
  - Crash mid-ingest → the email row itself rolls back → Resend redelivery starts clean and creates the run. The "email row exists but no run ever will" orphan becomes impossible going forward, so no repair/adoption path is needed — that's the subtle gap in the audit's own sketch, dissolved rather than patched.
  - Two concurrent duplicates: under READ COMMITTED, the loser's INSERT blocks on the winner's in-flight txn; if the winner commits, the loser sees the conflict (`inserted=False`); if the winner ABORTS, the loser's insert succeeds and the loser creates the run. Exactly-one-run holds in every interleaving.
  - The loser's response upgrades from bare `{"status": "duplicate"}` to include the existing run's id when one exists (lookup via `payroll_runs.source_email_id` for first-ingest rows; a reply/unknown-sender duplicate legitimately has no run and returns the bare duplicate shape). This is what "the loser attaches to the existing run" means — report/associate, never create.
  - Rows with no run BY DESIGN (unknown sender, late reply, reply-routed resume) are unchanged — the transaction still commits the email row without a run on those paths.

### Stuck-run recovery (DATA-03)
- **D-9-10 Recovery = sweep-to-ERROR + the existing retrigger; never auto-restart.** A single-statement CAS sweep (`UPDATE payroll_runs SET status='error', error_detail=… WHERE status IN ('received','extracting','computed') AND updated_at < now() - <threshold> RETURNING id`) marks stranded runs as ERROR with a Phase-8 `error_detail` like `"recovery: stranded in-flight (background task died) — swept from {status}"`. The operator then uses the EXISTING ERROR→retrigger path. Rationale: marking-not-restarting keeps the one-human-gate philosophy (no autonomous pipeline restarts), reuses D-13b retrigger machinery wholesale, and converts an invisible stranding into a visible, diagnosable dashboard state. `error_reason` for swept runs is a fixed sentinel (e.g. `StrandedRunSwept`) so dashboards/tests can distinguish sweep-errors from real exceptions.
- **D-9-11 Sweep trigger = dashboard runs-list load.** Render free tier has no background loops (only inbound HTTP wakes the service), and the operator opening the dashboard is exactly the moment recovery matters. The runs-list GET route calls the sweep function (cheap single UPDATE) before loading runs; tests call the function directly. No new cron, no new endpoint required (planner MAY additionally expose it on an existing admin/ops route if trivially cheap, but the dashboard hook is the required path).
- **D-9-12 Sweep scope is exactly `{received, extracting, computed}`.** NOT `awaiting_reply` (legitimately parked for days awaiting the client), NOT `awaiting_approval` (parked at the human gate), NOT `approved` (has its own retrigger claim path, D-13b). This list must be pinned by a test — sweeping a parked-by-design status would be a correctness bug.
- **D-9-13 Threshold: lower from 5 min; exact value is a planner call bounded by evidence.** The bound: threshold must exceed the worst-case legitimate gap between two consecutive DB writes in a live pipeline (≈ the longest LLM call + its retry, since every stage write bumps `updated_at`) with comfortable margin — researcher verifies the configured LLM client timeouts and retry counts to compute it; expected landing zone 90s–3min. Keep ONE shared constant serving both the sweep and retrigger's existing stale-in-flight claim unless tracing shows they genuinely need different values. Known accepted tension (document, don't solve): a pathologically-slow-but-alive task swept to ERROR could later have its unguarded `set_status` overwrite ERROR and advance the run anyway — the margin makes this pathological, and Phase 10's concurrency proof is where any residual guard-hardening evidence would come from.

### Test shape (from success criteria)
- **D-9-14 Crash injection via fault-hook, not mocks-all-the-way.** SC1's test forces an exception between writes inside an atomic unit (e.g. monkeypatched repo helper raising after N calls) and asserts the run is wholly un-advanced — status unchanged AND no partial rows (line items, decision, snapshot). Phase 7.5's lesson applies: assert the PERSISTED values, not just labels. SC2's race test runs two real concurrent ingests (threads against a real/local DB — the FakeConnection offline pattern cannot prove blocking semantics; a live-DB-gated test or the Phase 10 harness seam is acceptable, planner decides placement) and asserts exactly one run. SC3's test strands a run (in-flight status + backdated `updated_at`), runs the sweep, asserts ERROR + error_detail, then retriggers to a progressing state.

### Claude's Discretion
- Exact threshold value within the D-9-13 bound; sweep function name and exact wiring point in the runs-list route.
- Whether the loser's existing-run lookup uses `source_email_id` join or a header-chain query.
- Ordering of `set_pre_clarify_extracted` relative to the send inside `_clarify` (D-9-06 locks only status-advance-last).
- How `gateway.send_outbound`'s internal reserved/flip writes get their connections (they intentionally stay OUTSIDE the caller's finalize txn per D-9-07 — plumb `conn=` only where it serves that design).
- Whether `_run_stages`' persist-txn connection is opened by the orchestrator per-call or passed from `run_pipeline`/`resume_pipeline`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase definition + audit evidence
- `.planning/ROADMAP.md` — Phase 9 entry: goal, success criteria 1–3, closes HIGH-03/HIGH-04/MED-05
- `.planning/REQUIREMENTS.md` — DATA-01/02/03 exact wording; Out of Scope table
- `.planning/v2-hardening-audit.md` — Ring 2 findings (lines 31–46), including the explicit warning that the audit's own dedup fix sketch had a subtle gap (dissolved by D-9-09's single-transaction ingest)

### Code touch points (verified 2026-07-02)
- `app/pipeline/orchestrator.py` — `_run_stages` :788 (persist+branch sequence :868–895), `_clarify` :898 (LLM suggestion + draft + send + snapshot + AWAITING_REPLY), `_deliver` :1157 (reserved/sent guard :1197, send :1278, alias :1293, SENT+RECONCILED :1303–1304), `_compute_line_items` :1315
- `app/main.py` — webhook `inbound` :231 (dedup insert :311, create_run :350, enqueue :354), `_route_reply` :362, retrigger :534 (claim-from-ERROR/APPROVED/stale, STALE_THRESHOLD :64 = 5 min), approve claim_status CAS :492
- `app/db/repo.py` — `_conn_ctx` :126 (the conn= seam), `insert_inbound_email` :140 (ON CONFLICT (message_id) DO NOTHING), `create_run` :228, `set_status` :337 / `claim_status` :354 (the two sanctioned status writers, D-12), `record_run_error` :514 (Phase 8 scrub + error_detail — the sweep writes through this surface or matches its contract), `insert_email_message` :842 (D-13c upsert on (run_id, purpose)), `update_email_message_sent` :962
- `app/email/gateway.py` — `send_outbound` reserved-before-send → send → flip-to-sent/failed (D-13c, the pattern D-9-07 preserves)
- `app/db/supabase.py` — pool singleton (max=5 — why D-9-01 forbids holding a txn across network calls), `get_connection()`
- `app/db/schema.sql` — `payroll_runs.status` CHECK (post-Phase-8, no NEEDS_CLARIFICATION), `error_detail` column, `uq` constraints on email_messages

### Prior-phase contracts that constrain this work
- `.planning/phases/08-data-layer-hygiene-diagnostics/08-CONTEXT.md` — error_detail scrub contract (D-8-01/01b/02: scrub-then-truncate, fail-open, stage-prefixed) the sweep's error_detail must honor; live-DB-migration-at-human-checkpoint pattern (if any schema change proves necessary)
- `.planning/phases/07.5-clarification-reply-field-regression/07.5-CONTEXT.md` — resume_pipeline Round-1/Round-2 write sequences that D-9-06's principle must be mapped onto
- Key decision log (STATE.md Accumulated Context): D-12 (claim_status is the second sanctioned status writer; contended gates use CAS not load-then-set), D-13b (APPROVED not terminal; delivery failure routes to ERROR for retrigger), D-13c (outbound upsert on (run_id, purpose); retry-over-reserved advances)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- The `conn=` parameter on ~30 repo helpers + `_conn_ctx` (repo.py:126): the transaction-threading seam already exists — Phase 9 is largely wiring, not surgery.
- `claim_status` CAS (repo.py:354): the model for every contended transition; the sweep's single-statement UPDATE…WHERE…RETURNING is the same shape.
- `gateway.send_outbound`'s D-13c reserved→send→sent/failed lifecycle: already the correct side-effect bracket; D-9-07 builds the finalize txn around it rather than replacing it.
- Phase 8's `record_run_error` + `_scrub`: the sweep's error_detail writes reuse this diagnostics surface.
- Retrigger endpoint (main.py:534) with claim-from-stale logic: recovery reuses it wholesale; only the marking (sweep) is new.

### Established Patterns
- Two sanctioned status writers only (`set_status` owned-path, `claim_status` CAS) — the sweep must be implemented as one of these shapes, not a third pattern.
- D-A1-03 error-wrap: orchestrator catches stage failures and persists ERROR — the new transactions live INSIDE that boundary (a rolled-back txn still surfaces as ERROR with detail).
- Prepared statements disabled (`prepare_threshold=None`) for Supavisor transaction-mode pooling — new transaction code changes nothing about connection acquisition.
- TestClient runs BackgroundTasks synchronously — ingest-txn-commits-before-enqueue ordering must be verified under both TestClient and real ASGI serving.

### Integration Points
- `_run_stages` is shared by `run_pipeline` AND `resume_pipeline` — transaction wrapping lands once, both paths inherit it (same DRY seam as Phase 7.5).
- The runs-list dashboard route is the sweep's trigger point (D-9-11).
- Phase 10's concurrency proof will drive these exact seams under parallelism — keep the sweep + ingest txn callable as plain functions so the proof harness can exercise them directly.

</code_context>

<specifics>
## Specific Ideas

- The user's single directive: all four discussion areas delegated — "u decide on the best approach for all of this." Decisions D-9-01…D-9-14 are Claude's, made against the live code, and are locked for downstream agents.
- Tone for the deliverable: this phase is the "senior-engineer signal" of the milestone — code comments at the three seams (persist-txn, finalize-txn, ingest-txn) should state the invariant they enforce and the crash window they close, in the same explain-the-why style the codebase already uses.

</specifics>

<deferred>
## Deferred Ideas

### Reviewed Todos (not folded — user confirmed "Fold neither")
- **260623-08 — re-clarification loop cap with operator-escape state:** a new state-machine capability (counter column, new run state, dashboard controls) — its own phase, not atomicity work. Stays pending.
- **260623-01 remainder — WR-04 (Content-Disposition filename injection), WR-05 (path containment), INFO-02 (LLM retry-prompt scrub):** security hygiene, unrelated to data integrity. Stays pending for a security-flavored slot.
- Cosmetic todos (260623-02/03/04/05) remain locked out of v2 scope per REQUIREMENTS.md — not re-litigated.

### Noted for later
- Guard-hardening the pipeline's unguarded `set_status` writes against a swept-to-ERROR run (the D-9-13 accepted tension) — only if Phase 10's concurrency proof shows the window matters in practice.

</deferred>

---

*Phase: 9-Atomic Data Integrity*
*Context gathered: 2026-07-02*
