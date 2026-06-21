# Roadmap: Payroll Agent

## Overview

A messy real-world payroll email goes in; a correct, human-approved payroll comes out — with every LLM judgment call gated by code so a low-confidence match can never reach a real payroll calculation. The build is a **Vertical MVP**: a thin foundation, then a walking skeleton that proves the whole gated slice end-to-end ~one-third in (calc deliberately thin — gross + FICA only, net honestly labeled "pre-federal"), then deepening rings ordered by risk. Penny-accurate IRS Pub 15-T federal withholding is hardened in its own ring *before* any correctness claim; the eval (the proof) rides the exact same pure judgment functions as production; the dashboard and delivery wrap the working slice; and the one risky external dependency — real inbound email — is wired last so it never threatens priority #1 (visibly works end-to-end).

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Thin Foundation** - Contracts, minimal schema for the slice, and seed data for one happy-path + one name-mismatch case (completed 2026-06-21)
- [ ] **Phase 2: Walking Skeleton** - First end-to-end proof: messy fixture flows through the four gated judgment stages to a code-gated decision (calc thin, net pre-federal)
- [ ] **Phase 3: Harden the Calc** - Real Pub 15-T 2026 federal withholding + full-fidelity gross/FICA/net, golden-tested to the penny
- [ ] **Phase 4: The Eval (the proof)** - Hand-curated fixtures scored over the same production functions, rendered as one legible per-category chart
- [ ] **Phase 5: Dashboard & Delivery** - Operator gate UI (raw email beside extracted beside computed), runs/eval views, confirmation email + on-demand PDFs, idempotency + error path
- [ ] **Phase 6: Real Integration & Ship** - Real email provider behind the interface, Docker + Render + Supabase + keep-alive, README with disclaimer + demo recording

## Phase Details

### Phase 1: Thin Foundation

**Goal**: The shared contract substrate exists — schema for the tables the slice touches, Pydantic contracts imported by both pipeline and eval, and seed data rich enough to exercise the happy path and a name mismatch.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: FOUND-01, FOUND-02, FOUND-03, FOUND-05, FOUND-06
**Success Criteria** (what must be TRUE):

  1. The Postgres schema applies cleanly with all 6 tables and the 11-value `payroll_runs.status` enum present.
  2. A duplicate webhook delivery cannot create a second run — `email_messages.message_id` rejects a repeated insert (idempotency, FOUND-02).
  3. The shared `models/` Pydantic v2 contracts (InboundEmail, Extracted, Decision, PaystubLineItem) import and validate sample data, and are the SAME types the eval will later import.
  4. Seed data loads 3+ businesses with employees spanning mixed hourly/salary, known aliases, and filing statuses — including one happy-path business and one name-mismatch case — and every seeded employee carries the full calc-input set (pay frequency/periods, wage type + rate or salary, filing status, Step-2 flag, assumed Step-3/4 values, static YTD SS wages so the wage-base cap is honest).

**Plans**: 3 plans
Plans:
**Wave 1**

- [x] 01-01-PLAN.md — Project scaffold + all shared Pydantic v2 contracts (RunStatus, InboundEmail, Extracted, Decision, PaystubLineItem, Roster, Employee, NameMatchResult, ValidationIssue)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md — schema.sql (6 tables, CHECK, UNIQUE), config.py, supabase.py (prepare_threshold=None), bootstrap.py (--reset), test_status_drift.py (CI drift guard)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 01-03-PLAN.md — seed.py (Pydantic-validated upsert, fixed UUIDs, coverage-driven 3 businesses/6 employees), test_seed_roundtrip.py (live-DB round-trip)

### Phase 2: Walking Skeleton

**Goal**: A messy payroll fixture POSTed to the webhook flows end-to-end through the four pure judgment stages, hits a code-owned gated decision, and pauses/resumes correctly — the first proof the thesis works, with calc deliberately thin (gross + FICA only; net labeled "pre-federal," never a fake federal number).
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: INGEST-01, INGEST-02, INGEST-03, INGEST-04, EMAIL-01, LLM-01, LLM-02, LLM-03, LLM-04, LLM-05, LLM-06, LLM-07, LLM-08, LLM-09, HITL-01, CLAR-01, CLAR-02, CLAR-03, DEMO-01
**Success Criteria** (what must be TRUE):

  1. POST a messy fixture and watch it reach a gated decision — including the gate blocking a model that said `process` and forcing clarification (DEMO-01). The two canonical demo fixtures (one clean-to-approval, one model-says-process-but-gate-blocks) are committed and replayable.
  2. `decide.py` computes a code-owned `final_action` that hard-blocks on any missing required field or any name unresolved below 0.8 confidence even when the model said process; `final_action` is the SOLE branch source — the orchestrator never branches on `model_action` — and the four judgment stages are pure importable functions (data in, data out).
  3. Reconciliation enforces a one-to-one roster mapping: a duplicate submitted name, two names resolving to one employee, or a name resolving to no employee gates the run to clarification (a name cannot silently collapse onto another, LLM-09).
  4. The orchestrator drives the run state machine through both pause states — a clarify run reaches `awaiting_reply`, an injected fixture reply (zero real email) routes back via the RFC In-Reply-To/References chain, resumes at extraction idempotently, and a computed run pauses at `awaiting_approval` where a crude approve/reject proves the gate pauses and resumes.
  5. Computed paystubs show gross and FICA with net labeled "pre-federal" — no fabricated federal figure appears anywhere.

**Plans**: TBD

### Phase 3: Harden the Calc

**Goal**: The payroll math becomes trustworthy to the penny — real IRS Pub 15-T 2026 federal withholding plus full-fidelity gross/FICA/401k/net, asserted by golden-value tests against hand-computed 2026 paystubs — landing BEFORE the eval or dashboard ever present a number as correct.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: CALC-01, CALC-02, CALC-03, CALC-04, CALC-05, CALC-06, CALC-07, CALC-08
**Success Criteria** (what must be TRUE):

  1. Federal withholding computes via the real Pub 15-T 2026 percentage method (Worksheet 1A, all three filing statuses + the Step-2-checkbox branch), standard method only with OBBBA disclaimed; the run's net is now a real net (gross − pre-tax − FICA − federal), no longer "pre-federal."
  2. Gross handles FLSA overtime at 1.5× over 40 worked hours with paid-leave hours excluded from the 40-hour threshold, salary proration (annual ÷ pay periods plus added leave pay), and a 401k pre-tax deduction that reduces the federal taxable base but NOT the FICA base.
  3. FICA computes Social Security at 6.2% up to the 2026 $184,500 wage base — honoring each employee's static YTD SS wages so the cap is respected — and Medicare at 1.45% with no cap.
  4. A golden-value test suite asserts hand-computed 2026 paystubs to the penny using `Decimal`, sourced from a dated, year-keyed tax-constants module (source + retrieval date in header).
  5. The reconciliation check confirms net + taxes + deductions ties to the run total and flags arithmetic drift — understood as an arithmetic backstop only, not the correctness oracle (the golden tests are the oracle).

**Plans**: TBD

### Phase 4: The Eval (the proof)

**Goal**: A reproducible eval imports and scores the exact same production judgment functions over ~15-25 committed hand-curated fixtures, producing a legible per-category chart that proves the gated decisioning works — the credibility lever for the recruiter audience.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05
**Success Criteria** (what must be TRUE):

  1. `run_eval.py` imports and runs the SAME production pipeline functions and scores the code-owned `final_action` (not the model's raw action), proving the eval tests the production path, not a parallel one.
  2. ~15-25 hand-curated email+label fixtures spanning all categories (clean, name typo, missing hours, unknown employee, nickname, vague hours, buried reply) are committed to the repo; the bootstrap drafting helper is named honestly as a drafting aid, and the committed fixtures are the source of truth (no train/test leakage).
  3. Scoring produces the three core thesis metrics — extraction field accuracy, name-reconciliation accuracy, decision accuracy — broken out per category, plus (drop-if-tight) a secondary rubric'd LLM-as-judge email-quality score (EVAL-04).
  4. Eval results (including the pinned model IDs used) write to `eval_results` and render as one clean per-category chart; local eval is authoritative and CI scores against cached/committed fixture outputs with no live LLM calls on push.

**Plans**: TBD

### Phase 5: Dashboard & Delivery

**Goal**: A human operator can approve real payrolls through an honest gate — seeing the raw cleaned inbound email beside the LLM's extraction beside the computed paystubs — then a confirmation email with on-demand PDFs sends only after approval, with idempotent sends and a visible error path.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, HITL-02, HITL-03, CLAR-04, INGEST-05, FOUND-04
**Success Criteria** (what must be TRUE):

  1. A run detail view shows three columns left-to-right — the raw cleaned inbound email body (leftmost, mandatory), the LLM's `extracted_data`, then the computed paystubs — plus the decision object's reasons, so the operator verifies the LLM's *reading* against what the client actually sent (DASH-02, the honest gate).
  2. A runs list shows every run with a status badge; a pending run exposes Approve-and-send and Reject controls (the single operator gate), guarded by `SELECT ... FOR UPDATE` against double-approval (FOUND-04).
  3. On approval the run advances `approved` → `sent` → `reconciled`, sending an LLM-drafted confirmation email with paystub PDFs generated on demand from run data in memory (reportlab, BytesIO — nothing persisted to disk).
  4. Outbound sends are idempotent — retrying an approval or re-triggering an errored run never sends a duplicate clarification or confirmation (CLAR-04) — and a stuck/errored run surfaces an `error` status on the dashboard, re-triggerable idempotently from the start of the run (INGEST-05, drop-if-tight: "nothing silently hangs").
  5. An eval view renders the latest summary with headline metrics and a per-category breakdown chart, and a "Send test email" button fires a fixture through the whole pipeline from the page (demo trigger and live-email fallback).

**Plans**: TBD
**UI hint**: yes

### Phase 6: Real Integration & Ship

**Goal**: The system runs on the public free stack with a real inbound-email provider wired behind the existing interface (fixture path unchanged), deployed and documented well enough that a hiring manager can read the README, see the disclaimer, and watch a 60-90s demo.
**Mode:** mvp
**Depends on**: Phase 5
**Requirements**: OPS-01, OPS-02, OPS-03, OPS-04
**Success Criteria** (what must be TRUE):

  1. A real email gateway provider is wired behind the existing `parse_inbound`/`send` interface as the final integration step, with the fixture path unchanged (OPS-02).
  2. The FastAPI app is containerized in one Dockerfile (binds `0.0.0.0:$PORT`) and deploys as a single Render free web service against Supabase Postgres via the pooler, with a GitHub Actions keep-alive pinging Supabase so the free project does not pause (OPS-01, OPS-03).
  3. A README documents the system, states the educational/not-tax-compliant disclaimer (including the OBBBA exclusion and the unmodeled Additional Medicare 0.9% over $200k YTD), and includes an architecture diagram; a 60-90s demo recording exists (OPS-04).

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Thin Foundation | 3/3 | Complete    | 2026-06-21 |
| 2. Walking Skeleton | 0/TBD | Not started | - |
| 3. Harden the Calc | 0/TBD | Not started | - |
| 4. The Eval | 0/TBD | Not started | - |
| 5. Dashboard & Delivery | 0/TBD | Not started | - |
| 6. Real Integration & Ship | 0/TBD | Not started | - |
