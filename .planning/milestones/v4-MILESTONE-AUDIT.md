---
milestone: v4
milestone_name: Durable Execution
audited: 2026-07-20T20:59:38Z
status: passed
scores:
  requirements: 19/19
  phases: 6/6
  integration: 6/6   # cross-phase seams wired
  flows: 6/6          # end-to-end flows complete
definition_of_done: >
  No accepted email is ever lost; every failure recovers automatically within ~30 minutes
  without a human noticing; and a client is sent at most one confirmation per approved run,
  per epoch.
gaps:
  requirements: []     # none unsatisfied, none orphaned
  integration: []      # 0 blockers, 0 broken flows
  flows: []
nyquist:
  compliant_phases: [17, 18, 20]
  partial_phases: [16, 19, 21]   # VALIDATION.md planning maps not refreshed post-execution; underlying tests exist & pass per each VERIFICATION.md
  missing_phases: []
  overall: partial   # discovery-only, non-blocking — no coverage gap, only stale planning docs
tech_debt:
  - phase: 16-queue-substrate-unblocked-webhook
    items:
      - "F-3 (TOCTOU on the send path): assert_no_unconfirmed_send is a read; the reservation upsert follows unserialized. Explicitly deferred by user decision in 16-REVIEW.md. APPEARS SUPERSEDED by Phase 20's row-locked handoff authorization (authorize_outbound_provider_handoff uses FOR UPDATE on the leased job + frozen snapshot + handoff) — recommend a formal re-adjudication to close it rather than leaving it tracked as OPEN."
      - "Nyquist VALIDATION.md still status:draft / nyquist_compliant:false — a plan-time map never refreshed after the phase executed and verified passed. Optional: /gsd-validate-phase 16."
  - phase: 19-webhook-cutover-durable-ingest
    items:
      - "Nyquist VALIDATION.md still status:planned / wave_0_complete:false — plan-time map, not refreshed post-execution (durable-ingest tests exist and pass per 19-VERIFICATION.md). Optional: /gsd-validate-phase 19."
  - phase: 21-durability-proofs-ops-view
    items:
      - "Nyquist VALIDATION.md still status:approved / wave_0_complete:false — plan-time map, not refreshed post-execution (all four proofs + CI gate exist and pass per 21-VERIFICATION.md and the live UAT). Optional: /gsd-validate-phase 21."
      - "PROOF-05 is a documentation/CI-registration proof (completeness gate), lower-weight than the live PROOF-01..04 exploits — accepted per its own definition, not a runtime scenario."
  - phase: cross-milestone (pre-existing, deferred to own work)
    items:
      - "10 dormant @pytest.mark.integration test modules never execute in CI — concurrency-proof.yml selects test files by name and only the queueproof marker runs live. Known pre-existing gap, explicitly out of v4 scope (ROADMAP backlog). Needs its own dedicated phase: inventory, make each reliable under a shared Postgres (or isolate), then bring into CI."
accepted_residual_risk:   # intended design, published honestly — NOT debt
  - "An operator retrigger can legitimately send a second confirmation: it bumps reply_epoch by design, minting a new key under uq_email_run_purpose_round_epoch. This is exactly why the claim is 'at most once per approved run, per epoch', not a flat 'never twice'."
  - "Exactly-once delivery is not achievable (Two Generals problem, not a library gap). Phase 20 claims at-most-once automatic confirmation and escalates ambiguity to human review; the honest limitation is documented in docs/DURABILITY-PROOFS.md."
out_of_scope:   # explicit exclusions from REQUIREMENTS.md — not debt
  - "Operator authentication (known/accepted gap, a different axis from durability)"
  - "Per-tenant fairness / priority lanes (jobs.business_id/priority written but unread — a future ORDER BY change, not a migration)"
  - "Adaptive backpressure, circuit breakers, N-concurrent-email load chart, autoscaling/tracing/metrics stack, async psycopg, uvicorn --workers N"
---

# Milestone v4 — Durable Execution — Audit Report

**Audited:** 2026-07-20
**Status:** ✅ **PASSED**
**Scope:** Phases 16–21 (84 plans, all complete) · 19 requirements
**Definition of done:** *No accepted email is ever lost; every failure recovers automatically within ~30 minutes without a human noticing; and a client is sent at most one confirmation per approved run, per epoch.*

Milestone v4 achieves its definition of done. All 19 requirements are satisfied across a
three-source cross-reference (VERIFICATION.md + SUMMARY frontmatter + REQUIREMENTS.md
traceability), every cross-phase seam is wired end-to-end at the source level, the one durable
path connects across all phase boundaries, and both OPS-01 human checkpoints were closed PASS
against the **live deployed service**. No unsatisfied or orphaned requirements. No integration
blockers. Remaining items are minor, non-blocking, and mostly documentation hygiene.

---

## 1. Requirements Coverage — 19/19 satisfied

Three-source cross-reference: each REQ-ID's phase VERIFICATION.md status, its claiming SUMMARY.md
`requirements-completed` frontmatter, and its REQUIREMENTS.md traceability checkbox all agree.

| REQ-ID | Phase | VERIFICATION | SUMMARY frontmatter | REQUIREMENTS.md | Final |
|--------|-------|--------------|---------------------|-----------------|-------|
| QUEUE-01 | 16 | passed | 16-01 | `[x]` | ✅ satisfied |
| QUEUE-02 | 16 | passed | 16-02/03/04/06/08/09/10 | `[x]` | ✅ satisfied |
| QUEUE-03 | 16 | passed | 16-02/04/07/09/10 | `[x]` | ✅ satisfied |
| QUEUE-05 | 16 | passed | 16-03/05/06 | `[x]` | ✅ satisfied |
| PUMP-01 | 17 | passed | 17-01/02/04/05 | `[x]` | ✅ satisfied |
| PUMP-02 | 17 | passed | 17-03 | `[x]` | ✅ satisfied |
| FAIL-01 | 18 | passed | 18-01/02/04/09/10/11/14 | `[x]` | ✅ satisfied |
| FAIL-02 | 18 | passed | 18-02/03/04/05/06/09–14 | `[x]` | ✅ satisfied |
| FAIL-03 | 18 | passed | 18-07/08 | `[x]` | ✅ satisfied |
| QUEUE-04 | 19 | passed | 19-01…19-12 | `[x]` | ✅ satisfied |
| SEND-01 | 20 | passed | 20-01/04/05/17/18/21/23/25 | `[x]` | ✅ satisfied |
| SEND-02 | 20 | passed | 20-01/03/04/05/07/10/12 | `[x]` | ✅ satisfied |
| SEND-03 | 20 | passed | 20-02/03/09/13/21/22/24/26/27 | `[x]` | ✅ satisfied |
| PROOF-01 | 21 | passed | 21-03/10/13 | `[x]` | ✅ satisfied |
| PROOF-02 | 21 | passed | 21-04/10 | `[x]` | ✅ satisfied |
| PROOF-03 | 21 | passed | 21-05/10 | `[x]` | ✅ satisfied |
| PROOF-04 | 21 | passed | 21-08/10/13/14 | `[x]` | ✅ satisfied |
| PROOF-05 | 21 | passed | 21-01/09/12/13/14 | `[x]` | ✅ satisfied |
| OPS-01 | 21 | passed | 21-02/06 (+ UAT 2/2) | `[x]` | ✅ satisfied |

**Orphan detection:** none. Every REQ-ID in the traceability table maps to at least one phase
VERIFICATION.md and one claiming SUMMARY.

**One resolved discrepancy (not a gap):** 21-07-SUMMARY and 21-11-SUMMARY declare
`requirements-completed: []`, written while OPS-01's two live human checkpoints were still open.
`21-UAT.md` (2026-07-20) subsequently closed both **PASS (2/2, 0 issues)** against the live
deployed service, and 21-VERIFICATION.md was canonicalized `human_needed → passed`. The empty
SUMMARY frontmatter is a stale snapshot from before that closure, not an uncovered requirement.

---

## 2. Phase Verifications — 6/6 passed

| Phase | Status | Score | Note |
|-------|--------|-------|------|
| 16 · Queue Substrate & Unblocked Webhook | passed | 5/5 | Falsifying mutations independently re-run; F-4/F-6 fixed |
| 17 · The Pump | passed | 5/5 | One post-verify gap (comment-provenance guard trip) resolved in aa5e567; pump.yml live-run later confirmed by Ph21 UAT |
| 18 · Failure Policy & Sweep Deletion | passed | 9/9 | Re-verified 7/9 → 9/9 after gap-closure plans 18-13/18-14 (CR-01, CR-02, WR-01 closed) |
| 19 · Webhook Cutover & Durable Ingest | passed | 40/40 | Same-Svix real-Postgres race observed green in CI (run 29589513220) |
| 20 · Exactly-Once Send | passed | 4/4 | Re-verified 3/4 → 4/4 after 20-26/20-27 closed the delivery-expiry + live-evidence gaps |
| 21 · Durability Proofs & Ops View | passed | 6/6 | PROOF-01/04 re-falsified this session; OPS-01 human checkpoints closed via UAT 2/2 |

No phase is missing a VERIFICATION.md. Every phase also has a VALIDATION.md and its full SUMMARY set.

---

## 3. Cross-Phase Integration — 6/6 seams wired, 0 blockers

Verified by the integration checker against actual source (not SUMMARY claims):

| # | Seam | Phases | Status |
|---|------|--------|--------|
| 1 | Ingest → execution: webhook commits `inbound_events` + INGEST job atomically → `ingest.py` → the **single** `drain_once()` called by BOTH worker threads and `GET /internal/pump` | 19→16→17 | ✅ WIRED |
| 2 | Execution → failure-policy: `dispatch.normalize_pipeline_result` → centralized `settle_pipeline_job` / `settle_infrastructure_failure`; no handler swallows a failure into silent `done` | 16→18 | ✅ WIRED |
| 3 | Approval → send: `delivery.deliver()` only reserves + enqueues SEND_OUTBOUND; `send_outbound.py` reuses the reserved `message_id` as both Message-ID and Resend `idempotency_key`; no inline send remains | 18→20 | ✅ WIRED |
| 4 | Observability: `/ops` and `/health/queue` both read the same `list_unaccounted_error_runs` + `jobs` state the pipeline writes | all→21 | ✅ WIRED |
| 5 | Dedup layering: three independent UNIQUE constraints — `inbound_events.external_event_id` (Svix), `jobs.dedup_key` (queue), `email_messages` (RFC/epoch) — no coupling | 19/16/11 | ✅ WIRED |
| 6 | Sweep deletion: `grep sweep_stranded` → 0 hits in `app/`+`.github/`; no lingering second status-writer racing the lease recovery | 18 | ✅ CONFIRMED GONE |

**End-to-end durable path** — `webhook → INGEST job → drain (worker or pump) → pipeline →
PipelineResult-gated settlement → SEND_OUTBOUND job → reserved-snapshot delivery with
idempotency key → /ops & /health/queue observability` — is genuinely connected at the source
level, not merely present per-phase. `/internal/pump` is fail-closed on an empty/unset
`PUMP_TOKEN` (constant-time compare).

---

## 4. Live UAT Evidence (OPS-01)

`21-UAT.md` — **2/2 passed, 0 issues**, against `https://payroll-agent.onrender.com`:

1. **Live alarm baseline + drain-while-firing** — `list_unaccounted_error_runs()` vs live Supabase = **0 rows** (clean baseline: 0 error runs, 25 jobs all done). `pump.yml` dispatched (run 29773910333, green): drain step ran before the alarm step (recovery-first ordering proven live). Operator-accepted caveat: a clean baseline means the alarm ran GREEN, not RED; the RED path stays covered by hermetic tests (`test_ops_alarm_predicate.py` 8/8 + `TestAlarmStepOrdering`).
2. **/ops legibility + published evidence** — four comparison panels + both bound lines present, static as-of stamp, nav `Pyrl | Runs | Eval | Ops` with 0 button/form/dismiss controls, rows link to `/runs/{id}`, full render with JS disabled. `docs/DURABILITY-PROOFS.md` re-runnable end-to-end (ran PROOF-01 verbatim → green; applied the doc's diff → RED; reverted → green).

> **Deploy-state note (the classic v4 trap, checked and clear):** the UAT itself discovered
> Phase 21 was 94 commits ahead of `origin/master` and pushed `b50d982..eeb1c78`. **As of this
> audit, `git rev-list --count origin/master..master` = 0 (0 ahead, 0 behind)** — the milestone
> is fully pushed and the live service reflects it. Working tree is clean except one unrelated
> untracked quick-task dir.

---

## 5. Nyquist Coverage (discovery-only, non-blocking)

| Phase | VALIDATION.md | `nyquist_compliant` | Classification |
|-------|---------------|---------------------|----------------|
| 16 | exists | false | PARTIAL — plan-time map, `status:draft`, never refreshed |
| 17 | exists | true | ✅ COMPLIANT |
| 18 | exists | true | ✅ COMPLIANT |
| 19 | exists | true | PARTIAL — `status:planned`, `wave_0_complete:false`, never refreshed |
| 20 | exists | true | ✅ COMPLIANT |
| 21 | exists | true | PARTIAL — `status:approved`, `wave_0_complete:false`, never refreshed |

The PARTIAL phases are **documentation staleness, not coverage gaps**: each phase's VERIFICATION.md
independently confirms the automated tests those VALIDATION.md maps planned now exist and pass
(Phase 21 even re-ran `-m proof --collect-only → 4 ids` and `-m queueproof → 73 passed, 0 skipped`
this session). Optional cleanup: `/gsd-validate-phase 16 | 19 | 21` to refresh the maps to
`nyquist_compliant`/complete. Not required to complete the milestone.

---

## 6. Tech Debt & Deferred Items (non-blocking)

1. **Phase 16 F-3 — TOCTOU on the send path (money path).** Deferred by explicit user decision.
   **Appears superseded** by Phase 20's row-locked handoff authorization
   (`authorize_outbound_provider_handoff` takes `FOR UPDATE` on the leased job + frozen snapshot +
   handoff before any provider I/O). Recommend a **formal re-adjudication to close it** rather than
   leaving it tracked as OPEN; if any residual window survives Phase 20, re-file it explicitly.
2. **Nyquist VALIDATION.md refresh** for phases 16, 19, 21 (see §5). Doc hygiene.
3. **Pre-existing: 10 dormant `@pytest.mark.integration` modules never run in CI** — `concurrency-proof.yml`
   selects test files by name and only the `queueproof` marker runs live. Known, explicitly
   **out of v4 scope** (ROADMAP backlog). Needs its own dedicated phase: inventory each, make it
   reliable under a shared Postgres (or isolate it), then bring it into CI.
4. **PROOF-05 is a documentation/CI-registration proof** (completeness gate), lower-weight than the
   live PROOF-01..04 exploits — accepted per its own definition.

**Accepted residual risk (intended design, published honestly — not debt):** an operator
retrigger can legitimately send a second confirmation (it bumps `reply_epoch` by design — the exact
reason the claim is *per epoch*); exactly-once delivery is not achievable (Two Generals) and Phase
20 honestly claims at-most-once automatic confirmation with human escalation for ambiguity.

**Out of scope (explicit exclusions, not debt):** operator authentication, per-tenant fairness /
priority lanes, adaptive backpressure, circuit breakers, N-concurrent load chart, autoscaling /
tracing / metrics stack, async psycopg, `uvicorn --workers N`.

---

## Verdict

**PASSED.** 19/19 requirements satisfied, 6/6 phases verified passed, 6/6 cross-phase seams wired
with 0 blockers, and OPS-01's live human checkpoints closed 2/2 against the deployed service. The
durable-execution property is demonstrated end-to-end and — per Phase 21's four falsifiable proofs
— demonstrated *able to fail*. Remaining items are minor documentation hygiene and one pre-existing,
explicitly-deferred CI-coverage backlog item. Ready for `/gsd-complete-milestone v4`.
