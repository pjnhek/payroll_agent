# Milestones

## v4 Durable Execution (Shipped: 2026-07-20)

**Phases completed:** 6 phases (16–21), 84 plans, 164 tasks
**Timeline:** 7 days (2026-07-13 → 2026-07-20)
**Git range:** `v3` (`a508abd`) → HEAD (566 commits) · 380 files changed (+93,573 / −9,127)
**Codebase:** ~17,936 LOC Python in `app/`
**Requirements:** 19/19 checked off (0 gaps)
**Closeout:** verified_closeout — pre-close artifact audit clear, all 6 phases verified `passed`, milestone audit PASSED (19/19 reqs · 6/6 seams · OPS-01 live UAT 2/2)
**Deferred at close:** 4 demo/UI-polish items reclassified to `backlog.md` → "Next milestone (mini)" (run-detail UI rework, progressive-enhancement, paystub YTD, eval-chart restyle) — not requirements, bundled as the next mini-milestone scope.

**Delivered:** Made the payroll pipeline durable end-to-end — no accepted email is ever lost, every failure recovers automatically within ~30 minutes without a human noticing, and a client is sent at most one confirmation per approved run, per epoch — and, per Phase 21's four falsifiable proofs, demonstrated *able to fail*.

**Key accomplishments:**

- **Non-blocking durable queue substrate** (Phase 16) — A durable `jobs` table (UNIQUE `dedup_key`, `SKIP LOCKED` claim, lease + double-fence protocol, epoch-stable auto-reclaim) drained by a 2-thread worker pool owned by the app's first-ever FastAPI `lifespan`; the webhook's blocking ingest work moves to `run_in_threadpool` so the event loop never stalls (two 0.6s-slow requests finish in ~0.6s, not ~1.2s). INVARIANT J-1 (transport state is never a business status) is machine-enforced by an AST guard + a kind/state drift test.
- **The pump — recovery without a warm process** (Phase 17) — An authenticated, fail-closed `GET /internal/pump` sharing the single `drain_once()` with the workers, driven by a 30-min cron folded into one `pump.yml` alongside the keepalive + schema-drift checks; on Render free this is what makes the queue durable *execution*, not merely durable storage.
- **Explicit failure policy + sweep deletion** (Phase 18) — The orchestrator returns an explicit result type (`ok` / `retryable` / `terminal`); retries use exponential backoff + jitter via `available_at` with an attempt cap that dead-letters; the old age-based `sweep_stranded_runs` second status-writer is DELETED, leaving the durable queue as the sole automatic recovery path.
- **Durable webhook cutover** (Phase 19) — All 8 `BackgroundTasks` producers migrated to a durable INGEST job: the webhook commits an `inbound_events` receipt + one identifier-only job atomically and only then returns 200; two independent dedup layers (Svix `external_event_id`, queue `dedup_key`) stay uncoupled; an AST inventory makes reintroducing `BackgroundTasks` fail CI deterministically.
- **At-most-once send** (Phase 20) — Confirmation delivery is frozen into an immutable snapshot and handed to the worker over a row-locked (`FOR UPDATE`) provider-handoff authorization; a retry reuses the reserved `message_id` as both Message-ID and Resend `Idempotency-Key` and replays the persisted payload; an epoch fence plus operator review for ambiguity give at-most-once-per-approved-run-per-epoch confirmation (exactly-once is impossible — Two Generals — and the limitation is documented honestly).
- **Four falsifiable durability proofs + ops view** (Phase 21) — Live-Postgres proofs for kill-mid-run, Svix redelivery, crash-between-provider-accept-and-`sent`-commit, and expired-lease zombie-fencing — each with a falsifying mutation executed red and byte-identically reverted — registered in the `queueproof`/`proof` CI gate; a read-only `/ops` page + `GET /health/queue` alarm surface queue depth, oldest-pending age, attempts, and the dead-letter list; `docs/DURABILITY-PROOFS.md` published; OPS-01 closed live 2/2 against the deployed service.

<details>
<summary>Full per-plan accomplishment log (84 plans)</summary>

The complete per-plan one-liner log is preserved in each phase's `*-SUMMARY.md` under
`.planning/milestones/v4-phases/` (or `.planning/phases/16..21/` if phases were not archived)
and in the archived `.planning/milestones/v4-ROADMAP.md`. It was intentionally not inlined here:
the six accomplishments above are the curated milestone-level record.

</details>

---

## v2 Production Hardening (Shipped: 2026-07-07)

**Phases completed:** 6 phases (7, 7.5, 8, 9, 10, 11), 26 plans, 55 tasks
**Timeline:** 11 days (2026-06-27 → 2026-07-07)
**Git range:** `30f3d79` → `eb2a270` (264 commits) · 183 files changed (+41,189 / −645)
**Codebase:** ~35,600 LOC Python across 84 files (`app/` + `tests/`)
**Requirements:** 16/16 checked off (0 gaps)
**Known deferred items at close:** 6 (see STATE.md → Deferred Items) — all non-blocking post-demo polish

**Delivered:** Took the working v1.0 MVP and made its money-logic and data layer genuinely production-grade — correct under real, messy, concurrent load, not just the demo path — with every phase closing concrete audit findings by file:line.

**Key accomplishments:**

- **Money-logic never silently pays wrong** (Phase 7) — an explicitly-zero-hours submission gates to clarification instead of producing a $0 paystub, and name reconciliation is Unicode-NFC-normalized so visually-identical names in different Unicode forms resolve as a match.
- **Clarification-reply field regression closed** (Phase 7.5) — a reply that drops a money-affecting field ("40 + 2 OT" → "40") is detected, clarifies exactly once, then carries the original value forward (or honors an explicit removal) with no infinite re-clarify loop; built on a `_run_stages` split so the carry-forward backfill lands between reconcile and validate/calc, plus a two-set model that prevents both explicit-zero overpay and silence underpay.
- **Diagnosable failures + schema hygiene** (Phase 8) — every error boundary writes a PII-safe, roster-scrubbed, stage-prefixed `error_detail` the dashboard renders end-to-end; hot-path indexes and explicit column lists restore the project's stated schema discipline; live Supabase schema migrated and human-verified at the blocking checkpoint.
- **Atomic data layer under concurrency & crashes** (Phase 9) — the persist+branch+status and send+alias+status sequences each commit in one transaction (crash mid-sequence leaves the run wholly un-advanced, never half-written); one atomic ingest-decision transaction makes duplicate webhooks unable to create a second run; a dead mid-flight run is recoverable via sweep/retrigger — all proven with fault injection against real Postgres.
- **Concurrency proof** (Phase 10) — a capstone test fires N=8 real OS threads across webhook dedup, HTTP approval race, and concurrent distinct ingests against real Postgres (races the real sync DB seam under a `threading.Barrier`, after the CR-01 gap-closure), wired into CI on an ephemeral `postgres:16` container so the invariants are standing evidence, not a local smoke test.
- **Clarification round machine + alias learning** (Phase 11) — genuinely-new questions always send (round-aware idempotency ends the silent park at `awaiting_reply`), a 3-round cap escalates to a first-class `needs_operator` operator-resolve state, combined context accumulates all consumed replies in round order behind a code-owned "questions we asked" anchor, and the alias-learning write side finally binds on client confirmation (with same-record evidence) so the system provably stops re-asking.

<details>
<summary>Full per-plan accomplishment log (26 plans)</summary>

- ClarifiedFields typed model (4 outcomes), two JSONB columns with IS-NULL snapshot helpers, N4 purpose-CHECK migration, D-7.5-11 classify-first Round-2 stranding fix, D-7.5-10 three-phase detect→backfill→calc ordering, and TWO-SET MODEL that prevents both explicit-zero overpay and silence underpay
- 15 hermetic integration tests proving all MONEY-03 state-machine invariants (D-7.5-11 answered-round tests, D-7.5-10 detect-on-raw, R2-2 backfill fix, R3-3 prior_matches threading, BLOCKER FIX), eval fixtures 16/17/18 with D-7.5-10 three-phase eval wiring, and four provenance badges for field-regression outcomes in the run-detail view.
- Landed the additive `error_detail` column, the project's first 3 `CREATE INDEX IF NOT EXISTS` statements, and the `payroll_runs.status` CHECK swap removing the dead `needs_clarification` value — with a new dedicated DO-block drift guard that closes a codex-review-flagged gap where the original enum/CHECK parser could only ever see the first CHECK match in the file.
- Every error boundary now writes a roster-scrubbed, stage-prefixed `error_detail` (with the HIGH #1 roster-scope gap fixed at the root by moving the error-wrap into `_run`), the dashboard renders it end-to-end, and the live Supabase schema was migrated and human-verified at the blocking checkpoint — schema strictly before code, per the deploy-order gate.
- Added the sanctioned third status writer (`sweep_stranded_runs`) and the dedup-loser run finder (`find_run_by_message_id`) to `app/db/repo.py`, and made `app.db.repo.get_connection` mockable inside the existing `fake_repo` test fixture — the prerequisite every later Phase 9 plan's transaction-wrapping work depends on.
- Wired D-9-04 through D-9-08's transaction boundaries into `_run_stages`, `_clarify`, `_defer_field_regression_clarification`, and `_deliver` — a crash injected mid-sequence now leaves the run wholly un-advanced (never half-written), proven by 6 fault-injection tests run against a real local Postgres instance, plus hardened `_deliver`'s already-sent guard so a retry-over-sent no longer silently skips alias learning (Codex HIGH-2 closed).
- Restructured `inbound()` around one atomic ingest-decision transaction that classifies duplicate/reply/unknown-sender/new-run BEFORE `create_run` is ever reachable (closing the Codex HIGH-1 reply-vs-new-run race), wired the stranded-run recovery sweep into every `GET /runs` dashboard load, and proved the SC2 concurrency race against real Postgres threads.
- Closed the compounding-retry gap on BOTH LLM call surfaces (`call_structured` and `call_text`) by pairing an explicit bounded timeout with an unconditional `max_retries=0`, re-derived the stranded-run sweep threshold against the now fully-and-correctly-counted worst case (65min → 15min), and proved DATA-03's SC3 success criterion end-to-end through the actual operator-facing `retrigger` route.
- A hermetic, unguarded regression fixture (`tests/test_multiround_context_edge.py`) proves the current silent-discard bug where a Round-1 clarification correction is reverted by Round-2's combined-context re-extraction — recorded as an explicit deferred finding in 09-CONTEXT.md, no production code touched.
- Closed both remaining DATA-01 verification gaps (WR-01/WR-02) by reordering one write and adding one nested SAVEPOINT — no new abstractions, both fixes verified against a real local Postgres instance with fault injection proving the pre-fix failure mode and the post-fix recovery.
- One capstone test module (tests/test_concurrency_proof.py) fires N=8 real OS threads across three risk surfaces — webhook dedup, HTTP approval race, concurrent distinct ingests — against a real Postgres, plus a GitHub Actions job (concurrency-proof.yml) that runs it on an ephemeral postgres:16 container on every push, making the four Phase-9 concurrency invariants standing CI evidence rather than a local-only smoke test.
- Rewrote Surfaces A/C of the concurrency capstone to race the real sync DB seam under a threading.Barrier instead of serializing through the async webhook route, closing the confirmed CR-01 blocker plus five corollary review findings.
- Round/consumed-round columns, the needs_operator status, a widened (run_id, purpose, round) uniqueness constraint, and 8 new repo.py accessors — landed with zero behavior change (round defaults to 0 everywhere, nothing yet reads the new state).
- Re-keyed `_clarify`'s idempotency guard from purpose-only to (purpose, round) via a new `get_outbound_for_round` lookup, closing WR-05 (round-2+ questions no longer silently swallowed), and added a 3-round cap that escalates silently to a new `needs_operator` dashboard state with its own badge and confirmed scope exclusions.
- resume_pipeline now writes the D-11-02 consumed marker at its own CAS claim, `_combined_context_email` accumulates every consumed reply in round order behind a code-owned "QUESTIONS WE ASKED" anchor, and the known-edge fixture flips from documenting a silent-mispay gap to asserting it's closed (Round-1 "30, not 40" now pays 30).
- Replaced the unreachable NEW-2 pre-vs-post count-diff alias bind with deterministic bind-on-confirmation against a persisted, nested `{suggested, bound}` candidate shape, added the `needs_operator` operator resolve+resume surface with server-side roster validation, and proved the alias-learning loop actually stops asking with a full-loop hermetic test that drives REAL name resolution end to end.
- Three main.py runtime seams wired to the Phase 11 round/consumed state: a redelivered or stranded unconsumed reply now re-drives the CAS-gated resume instead of being permanently dropped, and a retrigger wipes all reply-round context so no provenance badge can outlive its data.
- Per-run `reply_epoch` counter closes GAP-2 (stale round-0 'sent' row silently suppressing a retriggered clarification) and GAP-3 (stale consumed reply re-injected into post-retrigger extraction, mispay risk) without ever deleting or mutating the append-only `email_messages` audit log.
- Removed `/resolve`'s route-level `claim_status(NEEDS_OPERATOR, EXTRACTING)` pre-claim so `resume_pipeline`'s own CAS is the sole claimer, closing the silent-strand bug where every valid operator resolution was dropped and the run stuck forever in `EXTRACTING`.
- Bind-on-confirmation now requires same-record evidence via a new `_bind_evidence_for_token` helper, and `set_alias_candidates` is a JSONB merge write instead of a full-column overwrite — closing the exact "Dave/David worked separately" silent-misroute exploit and the multi-token clobber defect from the phase-11 code review.
- Closed GAP-5/CR-5: added a shared `_reply_sender_ok` predicate re-asserting FIX-5 sender revalidation at both the WR-04 redelivery re-schedule and the D-11-05 stranded-sweep re-schedule, so a reply that already failed sender auth on first delivery can never drive a victim's payroll via redelivery or a later dashboard load.

</details>

---
