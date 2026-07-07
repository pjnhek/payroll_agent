# Requirements Archive: v2 Production Hardening

**Archived:** 2026-07-07
**Status:** SHIPPED

For current requirements, see `.planning/REQUIREMENTS.md`.

---

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
- [x] **OPS2-03**: A concurrency proof test fires N simultaneous operations (concurrent runs, duplicate webhooks, simultaneous approvals on one run) and asserts the invariants hold — no double-approval, no lost update, no duplicate run, no half-written state. This is the evidence behind the production-grade claim.

### Ring 4 — Clarification round machine & alias learning (Phase 11; MONEY-class follow-ups)

*Registered 2026-07-05 at plan time from 260705-01/260705-02/260623-08 + 09-REVIEW.md WR-04/05/06 + 09-REVIEWS.md CX-01, per the ROADMAP Phase 11 note. IDs proposed in 11-RESEARCH.md.*

- [x] **CLAR2-01**: A genuinely new clarification question always sends; a true duplicate (re-trigger of the same round) is still suppressed. No run can silently park at `awaiting_reply` with no email out. (WR-05, `orchestrator._clarify` purpose-only guard; 260705-02.)
- [x] **CLAR2-02**: After 3 total clarification rounds, the run escalates to a first-class `needs_operator` status instead of sending; the operator can resolve names deterministically and resume, or reject. (260623-08, premise-corrected: the failure is silent-stall, not spam.)
- [x] **CLAR2-03**: The resume extraction context includes a code-owned "questions we asked" anchor, and the extraction prompt enforces absent-if-unaddressed; a bare "40" is never blindly attributed. (260705-02 item 2.)
- [x] **CLAR2-04**: The alias-learning write side is reachable: a client-confirmed suggestion binds `{token: suggested_id}` deterministically; the misname guard's never-learn-from-inference intent survives; a full-loop test proves the system stops asking. (260705-01.)
- [x] **CLAR2-05**: Multi-round context loss is closed: the combined context accumulates ORIGINAL + ALL consumed replies in round order; the known-edge fixture flips its assertion (Round-1 "30, not 40" pays 30, not 40). (CX-01 / T-09-21.)
- [x] **CLAR2-06**: A redelivered, still-unconsumed reply re-schedules the resume (no permanently-dropped replies); a consumed reply's redelivery stays a no-op. A stranded unconsumed reply is auto-re-scheduled from the runs-list load. (WR-04.)
- [x] **CLAR2-07**: Retrigger clears ALL reply context (`clarified_fields`, `pre_clarify_extracted`, round counter, suggestion/candidate state) so provenance badges cannot outlive the data that produced them. (WR-06.)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Custom email domain (send FROM a real address) | Free-tier/personal-project cosmetic; documented upgrade path already in README |
| Eval-chart restyle, paystub YTD columns, frontend polish | Cosmetic; no correctness/robustness value |
| Additional Medicare 0.9% surtax modeling | Intentional documented decision (never triggers at demo wages); a tax-completeness feature, not hardening |
| SS wage-base straddle exactness (per-employee YTD Medicare ledger) | Accepted limitation of the static-seed model; schema-level feature, not v2 hardening |
| Real-email A5 threading verification | Path-2 inbound already proven; deep header-survival check stays in backlog (live-gate task, not a code change) |
| Courtesy email to client at operator escalation | Deliberately not built (D-11-09); silent handoff |
| Paid→paid cross-round value-change diff (CX-01 fix (b)) | Rejected in favor of accumulation (D-11-12); no second diff state machine |
| Widening alias capture beyond single-token (D-04) | Bind redesign works within existing single-candidate capture |

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
| OPS2-03 | Phase 10 — Concurrency Proof | Complete |
| CLAR2-01 | Phase 11 — Clarification Round Machine & Alias Learning | Complete |
| CLAR2-02 | Phase 11 — Clarification Round Machine & Alias Learning | Complete |
| CLAR2-03 | Phase 11 — Clarification Round Machine & Alias Learning | Complete |
| CLAR2-04 | Phase 11 — Clarification Round Machine & Alias Learning | Complete |
| CLAR2-05 | Phase 11 — Clarification Round Machine & Alias Learning | Complete |
| CLAR2-06 | Phase 11 — Clarification Round Machine & Alias Learning | Complete |
| CLAR2-07 | Phase 11 — Clarification Round Machine & Alias Learning | Complete |

**Coverage:**
- v2 requirements: 16 total
- Mapped to phases: 16 ✓
- Unmapped: 0 ✓

Mapping by phase:
- **Phase 7 — Money-Correctness Deepening (Pure-Function Gates):** MONEY-01, MONEY-02
- **Phase 7.5 — Clarification-Reply Field-Regression:** MONEY-03 *(re-scoped out of Phase 7 on 2026-06-27 after 3 cross-AI review rounds; needs a `_run_stages` split refactor as its foundation — see `.planning/phases/07-money-correctness-deepening/07-REVIEWS.md`)*
- **Phase 8 — Data-Layer Hygiene & Diagnostics:** OPS2-01, OPS2-02
- **Phase 9 — Atomic Data Integrity:** DATA-01, DATA-02, DATA-03
- **Phase 10 — Concurrency Proof:** OPS2-03 (depends on Phase 9 — validates the atomicity/dedup/recovery invariants)
- **Phase 11 — Clarification Round Machine & Alias Learning:** CLAR2-01…CLAR2-07 (soft-depends on Phase 10: the round machine composes with, never depends on, future fencing primitives)

---
*Requirements defined: 2026-06-26*
*Last updated: 2026-07-05 — Phase 11 requirements CLAR2-01…07 registered at plan time*
