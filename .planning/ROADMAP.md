# Roadmap: Payroll Agent

## Milestones

- ✅ **v1.0 — MVP** (shipped 2026-06-25) — Email-driven payroll agent: messy email in, correct human-approved payroll out, every money-moving decision code-gated (deterministic, auditable, never guesses). 7 phases, deployed live on a free stack with a recorded demo. → [full archive](milestones/v1.0-ROADMAP.md) · [requirements](milestones/v1.0-REQUIREMENTS.md)
- ✅ **v2 — Production Hardening** (shipped 2026-07-07) — Took the working v1.0 MVP and made its money-logic and data layer genuinely production-grade — correct under real, messy, concurrent load, not just the demo path. 6 phases (7, 7.5, 8, 9, 10, 11), 16 requirements, scope discovered via an adversarial audit. → [full archive](milestones/v2-ROADMAP.md) · [requirements](milestones/v2-REQUIREMENTS.md) · [audit](milestones/v2-MILESTONE-AUDIT.md)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1–6, incl. 2.1) — SHIPPED 2026-06-25</summary>

Foundation → Walking Skeleton → Deterministic Decisioning → Harden the Calc → Eval → Dashboard & Delivery → Real Integration & Ship. Full phase details in [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md).

</details>

<details>
<summary>✅ v2 Production Hardening (Phases 7–11, incl. 7.5) — SHIPPED 2026-07-07</summary>

- [x] **Phase 7: Money-Correctness Deepening (Pure-Function Gates)** — zero-hours $0-paystub gate + Unicode (NFC) name normalization (MONEY-01, MONEY-02) — completed 2026-06-28
- [x] **Phase 7.5: Clarification-Reply Field-Regression (MONEY-03)** — `_run_stages` split refactor + detect-a-dropped-money-field, clarify once, carry forward or honor removal, no infinite loop (MONEY-03) — completed 2026-06-28
- [x] **Phase 8: Data-Layer Hygiene & Diagnostics** — PII-safe `error_detail`, hot-path indexes, explicit column lists (OPS2-01, OPS2-02) — completed 2026-07-02
- [x] **Phase 9: Atomic Data Integrity** — atomic multi-write transactions, transactional webhook-dedup CAS, stuck-run recovery (DATA-01, DATA-02, DATA-03) — completed 2026-07-04
- [x] **Phase 10: Concurrency Proof** — N-thread real-Postgres proof of the Phase-9 invariants, wired into CI (OPS2-03) — completed 2026-07-07
- [x] **Phase 11: Clarification Round Machine & Alias Learning** — round-aware clarify idempotency + 3-round `needs_operator` cap, question-anchored context accumulation, reachable bind-on-confirmation alias learning (CLAR2-01…07) — completed 2026-07-07

Full phase details (goals, success criteria, per-plan breakdown) in [milestones/v2-ROADMAP.md](milestones/v2-ROADMAP.md).

</details>

## Backlog

Captured ideas not yet scheduled into a milestone live in [`backlog.md`](backlog.md). Notable candidates carried forward / deferred from v2 scope:

- Real-email A5 threading verification (Path-2 inbound proven; the deep header-survival check stays a live-gate task, not a code change)
- Paystub YTD columns; eval-chart restyle; frontend progressive enhancement (no build step); Phase 05 code-review deferred warnings
- Custom email domain (send FROM a real address) — documented upgrade path in README
- Additional Medicare 0.9% surtax modeling; SS wage-base straddle exactness (per-employee YTD Medicare ledger) — accepted limitations, tax-completeness features not hardening

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
