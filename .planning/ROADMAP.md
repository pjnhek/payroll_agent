# Roadmap: Payroll Agent

## Milestones

- ✅ **v1.0 — MVP** (shipped 2026-06-25) — Email-driven payroll agent: messy email in, correct human-approved payroll out, every money-moving decision code-gated (deterministic, auditable, never guesses). 7 phases, deployed live on a free stack with a recorded demo. → [full archive](milestones/v1.0-ROADMAP.md) · [requirements](milestones/v1.0-REQUIREMENTS.md)
- ✅ **v2 — Production Hardening** (shipped 2026-07-07) — Took the working v1.0 MVP and made its money-logic and data layer genuinely production-grade — correct under real, messy, concurrent load, not just the demo path. 6 phases (7, 7.5, 8, 9, 10, 11), 16 requirements, scope discovered via an adversarial audit. → [full archive](milestones/v2-ROADMAP.md) · [requirements](milestones/v2-REQUIREMENTS.md) · [audit](milestones/v2-MILESTONE-AUDIT.md)
- ✅ **v3 — Production-Ready Codebase** (shipped 2026-07-13) — Made the codebase itself read as production-quality without changing a line of money behavior: enforced CI (ruff + full suite + `mypy --strict`, all blocking), the three god-files split into right-sized modules, the entire repo type-clean across 117 files, and provenance comments replaced with constraint-documenting ones behind a CI guard. 4 phases (12–15), 16/16 requirements, 227 commits. Found 3 real defects on the way — a lying eval chart, a path traversal, and a prompt-echo leak. → [full archive](milestones/v3-ROADMAP.md) · [requirements](milestones/v3-REQUIREMENTS.md) · [audit](milestones/v3-MILESTONE-AUDIT.md)
- ✅ **v4 — Durable Execution** (shipped 2026-07-20) — No accepted email is ever lost; every failure recovers automatically within ~30 minutes without a human noticing; a client is sent at most one confirmation per approved run, per epoch (exactly-once delivery is not claimed — Two Generals, not a library gap). Origin: an adversarial audit found the pipeline's `BackgroundTask` handoff was durable in memory only and the webhook blocked the event loop on a synchronous Resend fetch. 6 phases (16–21), 19/19 requirements, 84 plans, 566 commits; audit PASSED (19/19 reqs · 6/6 phases · 6/6 cross-phase seams · OPS-01 live UAT 2/2), and per Phase 21's four falsifiable proofs the durability property is demonstrated *able to fail*. → [full archive](milestones/v4-ROADMAP.md) · [requirements](milestones/v4-REQUIREMENTS.md) · [audit](milestones/v4-MILESTONE-AUDIT.md)
- 📋 **Next (mini) — Demo Polish & Run-Detail UI** (planned) — a small demo-facing polish pass, bundled from four items reclassified at v4 close: a run-detail chronological-email-conversation UI rework, frontend progressive enhancement (no build step), paystub YTD columns, and an eval-chart restyle. Scope preserved in full in [`backlog.md`](backlog.md) → "Next milestone (mini)"; version assigned when formalized via `/gsd-new-milestone`.

## Backlog

Captured ideas not yet scheduled into a milestone live in [`backlog.md`](backlog.md). Notable candidates carried forward / deferred:

- **Next mini-milestone bundle** (reclassified at v4 close): run-detail chronological-conversation UI rework, frontend progressive enhancement (no build step), paystub YTD columns, and eval-chart restyle away from the matplotlib look — full detail in `backlog.md` → "Next milestone (mini)" (was todos 260623-02/03/04 + quick-task 260718-hie).
- Real-email A5 threading verification (Path-2 inbound proven; the deep header-survival check stays a live-gate task, not a code change)
- Custom email domain (send FROM a real address) — documented upgrade path in README
- Additional Medicare 0.9% surtax modeling; SS wage-base straddle exactness (per-employee YTD Medicare ledger) — accepted limitations, tax-completeness features not hardening
- Schema-parity backlog: versioned/ordered migrations + migration-history table, hard deploy gate blocking Render deploy on drift — separate future milestone, needs paid plan or self-managed release step
- **10 dormant `integration`-marked test modules never execute in CI.** `concurrency-proof.yml` is the only workflow with a real Postgres and selects test files BY NAME (2 files); **12** files under `tests/` carry `@pytest.mark.integration`. Phase 16 (D-14) deliberately did NOT widen the gate to fix this — collecting all 12 at once would wake 10 live-DB modules against a shared Postgres with a destructive module-scope reset (`tests/conftest.py:74-93`), which is a large, unbudgeted change to smuggle inside a durability phase. Phase 16 instead adds a NARROW `queueproof` gate for new durability proofs. **The 10 dormant modules are a pre-existing gap and need their own dedicated work:** inventory and classify each, make it reliable under a shared Postgres (or isolate it), then bring it into CI. Files: `test_atomic_persist`, `test_claim_status`, `test_dashboard`, `test_gateway`, `test_ingest`, `test_persistence`, `test_seed_roundtrip`, `test_stuck_run_recovery`, `test_threading`, `test_webhook_dedup_race`.
- v4 out-of-scope, schema-shaped for later if traffic ever changes: per-tenant fairness lanes, priority lanes, adaptive backpressure, circuit breakers (LLM/Resend), an N-concurrent-email load chart, operator authentication (`jobs.business_id`/`priority` are written but unread — each stays a future `ORDER BY` change, not a migration)

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Thin Foundation | v1.0 | — | Complete | 2026-06-21 |
| 2. Walking Skeleton | v1.0 | — | Complete | 2026-06 |
| 2.1. Deterministic Decisioning | v1.0 | — | Complete | 2026-06 |
| 3. Harden the Calc | v1.0 | — | Complete | 2026-06 |
| 4. The Eval, the Proof | v1.0 | — | Complete | 2026-06-22 |
| 5. Dashboard & Delivery | v1.0 | — | Complete | 2026-06-23 |
| 6. Real Integration & Ship | v1.0 | — | Complete | 2026-06-25 |
| 7. Money-Correctness Deepening | v2 | 2/2 | Complete | 2026-06-28 |
| 7.5. Clarification-Reply Field-Regression | v2 | 4/4 | Complete | 2026-06-28 |
| 8. Data-Layer Hygiene & Diagnostics | v2 | 3/3 | Complete | 2026-07-02 |
| 9. Atomic Data Integrity | v2 | 6/6 | Complete | 2026-07-04 |
| 10. Concurrency Proof | v2 | 2/2 | Complete | 2026-07-07 |
| 11. Clarification Round Machine & Alias Learning | v2 | 9/9 | Complete | 2026-07-07 |
| 12. CI Quality Gates | v3 | 4/4 | Complete    | 2026-07-09 |
| 13. Module Structure & Boundaries | v3 | 4/4 | Complete    | 2026-07-10 |
| 14. Full Type-Checking (mypy) | v3 | 10/10 | Complete    | 2026-07-10 |
| 15. Comment Hygiene & Deferred-Polish Triage | v3 | 11/11 | Complete    | 2026-07-13 |
| 16. Queue Substrate & Unblocked Webhook | v4 | 10/10 | Complete    | 2026-07-14 |
| 17. The Pump | v4 | 5/5 | Complete    | 2026-07-15 |
| 18. Failure Policy & Sweep Deletion | v4 | 14/14 | Complete    | 2026-07-16 |
| 19. Webhook Cutover & Durable Ingest | v4 | 12/12 | Complete    | 2026-07-17 |
| 20. Exactly-Once Send | v4 | 27/27 | Complete    | 2026-07-18 |
| 21. Durability Proofs & Ops View | v4 | 16/16 | Complete    | 2026-07-20 |
