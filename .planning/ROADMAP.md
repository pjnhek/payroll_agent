# Roadmap: Payroll Agent

## Milestones

- ✅ **v1.0 — MVP** (shipped 2026-06-25) — Email-driven payroll agent: messy email in, correct human-approved payroll out, every money-moving decision code-gated (deterministic, auditable, never guesses). 7 phases, deployed live on a free stack with a recorded demo. → [full archive](milestones/v1.0-ROADMAP.md) · [requirements](milestones/v1.0-REQUIREMENTS.md)
- ✅ **v2 — Production Hardening** (shipped 2026-07-07) — Took the working v1.0 MVP and made its money-logic and data layer genuinely production-grade — correct under real, messy, concurrent load, not just the demo path. 6 phases (7, 7.5, 8, 9, 10, 11), 16 requirements, scope discovered via an adversarial audit. → [full archive](milestones/v2-ROADMAP.md) · [requirements](milestones/v2-REQUIREMENTS.md) · [audit](milestones/v2-MILESTONE-AUDIT.md)
- ✅ **v3 — Production-Ready Codebase** (shipped 2026-07-13) — Made the codebase itself read as production-quality without changing a line of money behavior: enforced CI (ruff + full suite + `mypy --strict`, all blocking), the three god-files split into right-sized modules, the entire repo type-clean across 117 files, and provenance comments replaced with constraint-documenting ones behind a CI guard. 4 phases (12–15), 16/16 requirements, 227 commits. Found 3 real defects on the way — a lying eval chart, a path traversal, and a prompt-echo leak. → [full archive](milestones/v3-ROADMAP.md) · [requirements](milestones/v3-REQUIREMENTS.md) · [audit](v3-MILESTONE-AUDIT.md)

## Active Milestone

_None — v3 shipped 2026-07-13. Start the next with `/gsd-new-milestone`._

## Backlog

Captured ideas not yet scheduled into a milestone live in [`backlog.md`](backlog.md). Notable candidates carried forward / deferred from v2 and v3 scope:

- Real-email A5 threading verification (Path-2 inbound proven; the deep header-survival check stays a live-gate task, not a code change)
- Frontend progressive enhancement (no build step); paystub YTD columns; eval-chart restyle away from matplotlib look (all deferred out of v3, todos 260623-02/03/04)
- Custom email domain (send FROM a real address) — documented upgrade path in README
- Additional Medicare 0.9% surtax modeling; SS wage-base straddle exactness (per-employee YTD Medicare ledger) — accepted limitations, tax-completeness features not hardening
- Schema-parity backlog: versioned/ordered migrations + migration-history table, hard deploy gate blocking Render deploy on drift — separate future milestone, needs paid plan or self-managed release step

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
