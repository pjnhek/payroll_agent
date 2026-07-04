# Requirements: Payroll Agent — v2 Production Hardening

**Defined:** 2026-06-26
**Core Value:** A messy real-world payroll email goes in; a correct, human-approved payroll comes out — every money-moving judgment is deterministic, auditable code that never guesses. **v2 deepens this claim: the engine must stay correct under real, messy, concurrent load — not just the demo path.**

**Source:** Scope discovered via an adversarial audit (`.planning/v2-hardening-audit.md`); every requirement traces to a concrete finding with file:line. Backend/logic only — cosmetic items excluded.

## v2 Requirements

### Ring 1 — Money-correctness (the thesis: never silently pays wrong)

- [x] **MONEY-01**: An hourly employee submitted with explicitly-zero hours (`hours_regular=0` and no other hours) is treated as a missing-field case and gates to `request_clarification` — it never silently produces a $0 paystub. (Audit HIGH-01, `validate.py`.)
- [x] **MONEY-02**: Name reconciliation is Unicode-normalized (NFC) before casefold, so visually-identical names in different Unicode forms (e.g. "José" NFC vs "José" NFD) resolve as a match instead of silently failing. (Audit MED-01, `reconcile_names._norm`.)
- [x] **MONEY-03**: When a clarification reply drops or changes a money-affecting field the original submission stated (e.g. original "40 + 2 OT", reply "40" with no OT), the system detects the regression and clarifies once ("did you forget the overtime?") before processing — then carries the original value forward if still unaddressed (no infinite re-clarify loop). (v1 backlog: field-regression.)

### Ring 2 — Data integrity (correct under concurrency and crashes)

- [x] **DATA-01**: Each multi-write pipeline operation is atomic — the persist+branch+status sequence in `_run_stages` and the send+alias+status sequence in `_deliver` each commit in a single transaction, so a crash mid-sequence never leaves a half-written run (e.g. paystubs replaced but status stale, or email sent but status never advanced). (Audit HIGH-03, `orchestrator.py`.)
- [x] **DATA-02**: Duplicate webhook deliveries for the same inbound email (Resend retries) never create a second payroll run, even under concurrent/parallel delivery — dedup and run-creation are resolved transactionally so exactly one run exists per inbound message_id. (Audit HIGH-04, `main.py` + `repo.insert_inbound_email`.)
- [x] **DATA-03**: A run whose background task died mid-flight (stuck in `extracting`/`computing`) is recoverable — there is a recovery path (sweep or operator force-retrigger) that does not require waiting out an over-long stale threshold. (Audit MED-05, `main.py` retrigger.)

### Ring 3 — Operability + evidence (back the "production-grade" claim)

- [x] **OPS2-01**: A failed run records a PII-safe error detail (sanitized exception message + context), not just the exception type — so production failures are diagnosable from the dashboard/DB without log access. (Audit HIGH-05, `record_run_error` + schema.)
- [x] **OPS2-02**: Hot query paths have supporting indexes (`businesses.contact_email`, `email_messages(run_id, direction, send_state)`, `payroll_runs(created_at DESC)`, `payroll_runs(status)`) and `load_all_runs` uses an explicit column list (no `SELECT *`), restoring the project's stated schema-hygiene discipline. (Audit HIGH-01/HIGH-02 data-layer.)
- [ ] **OPS2-03**: A concurrency proof test fires N simultaneous operations (concurrent runs, duplicate webhooks, simultaneous approvals on one run) and asserts the invariants hold — no double-approval, no lost update, no duplicate run, no half-written state. This is the evidence behind the production-grade claim.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Custom email domain (send FROM a real address) | Free-tier/personal-project cosmetic; documented upgrade path already in README |
| Eval-chart restyle, paystub YTD columns, frontend polish | Cosmetic; no correctness/robustness value |
| Additional Medicare 0.9% surtax modeling | Intentional documented decision (never triggers at demo wages); a tax-completeness feature, not hardening |
| SS wage-base straddle exactness (per-employee YTD Medicare ledger) | Accepted limitation of the static-seed model; schema-level feature, not v2 hardening |
| Real-email A5 threading verification | Path-2 inbound already proven; deep header-survival check stays in backlog (live-gate task, not a code change) |

## Traceability

Which phases cover which requirements. v2 phases continue the global sequence from v1.0 (last phase: 6).

| Requirement | Phase | Status |
|-------------|-------|--------|
| MONEY-01 | Phase 7 — Money-Correctness Deepening (Pure-Function Gates) | Complete |
| MONEY-02 | Phase 7 — Money-Correctness Deepening (Pure-Function Gates) | Complete |
| MONEY-03 | Phase 7.5 — Clarification-Reply Field-Regression | Complete |
| OPS2-01 | Phase 8 — Data-Layer Hygiene & Diagnostics | Complete |
| OPS2-02 | Phase 8 — Data-Layer Hygiene & Diagnostics | Complete |
| DATA-01 | Phase 9 — Atomic Data Integrity | Complete |
| DATA-02 | Phase 9 — Atomic Data Integrity | Complete |
| DATA-03 | Phase 9 — Atomic Data Integrity | Complete |
| OPS2-03 | Phase 10 — Concurrency Proof | Pending |

**Coverage:**
- v2 requirements: 9 total
- Mapped to phases: 9 ✓
- Unmapped: 0 ✓

Mapping by phase:
- **Phase 7 — Money-Correctness Deepening (Pure-Function Gates):** MONEY-01, MONEY-02
- **Phase 7.5 — Clarification-Reply Field-Regression:** MONEY-03 *(re-scoped out of Phase 7 on 2026-06-27 after 3 cross-AI review rounds; needs a `_run_stages` split refactor as its foundation — see `.planning/phases/07-money-correctness-deepening/07-REVIEWS.md`)*
- **Phase 8 — Data-Layer Hygiene & Diagnostics:** OPS2-01, OPS2-02
- **Phase 9 — Atomic Data Integrity:** DATA-01, DATA-02, DATA-03
- **Phase 10 — Concurrency Proof:** OPS2-03 (depends on Phase 9 — validates the atomicity/dedup/recovery invariants)

---
*Requirements defined: 2026-06-26*
*Last updated: 2026-06-26 after v2 roadmap creation — all 9 requirements mapped to Phases 7–10*
