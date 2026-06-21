# Requirements: Payroll Agent

**Defined:** 2026-06-20
**Core Value:** A messy real-world payroll email goes in; a correct, human-approved payroll comes out — and every LLM judgment call (name match, process-vs-clarify) is gated by code so a low-confidence match can never reach a real payroll calculation.

## v1 Requirements

Requirements for the initial release. Each maps to a roadmap phase (see Traceability).

### Foundations

- [ ] **FOUND-01**: Postgres schema exists for all 6 tables (businesses, employees, payroll_runs, paystub_line_items, email_messages, eval_results) with the 11-value `payroll_runs.status` enum
- [ ] **FOUND-02**: `email_messages.message_id` has a unique index so duplicate webhook deliveries cannot create a second run (idempotency)
- [ ] **FOUND-03**: Pydantic v2 contract models exist and are shared by the pipeline and the eval (InboundEmail, Extracted, Decision, PaystubLineItem)
- [ ] **FOUND-04**: A typed DB access layer (psycopg3, pooler connection) performs atomic status transitions and uses `SELECT ... FOR UPDATE` to prevent double-approval
- [ ] **FOUND-05**: Seed data loads 3+ businesses and their employees (mixed hourly/salary, known aliases, filing statuses) sufficient to exercise every calc path and name-match case
- [ ] **FOUND-06**: Each seeded employee carries the full set of calc inputs — pay frequency / pay periods, wage type + rate or annual salary, W-4 filing status, Step-2 checkbox flag, assumed Step-3/Step-4 values, and a static year-to-date Social Security wages figure (so the SS wage-base cap in CALC-04 is testable and honest)

### Payroll Calculation

- [ ] **CALC-01**: Gross pay computes hourly × rate with FLSA overtime at 1.5× for hours worked over 40 in the week (paid-leave hours excluded from the 40-hour threshold)
- [ ] **CALC-02**: Salary gross computes as annual ÷ pay periods, plus added vacation/sick/holiday pay
- [ ] **CALC-03**: 401k pre-tax deduction computes as a percent of gross and reduces the federal taxable base but NOT the FICA base
- [ ] **CALC-04**: FICA computes Social Security at 6.2% up to the current-year wage base ($184,500 for 2026), honoring the employee's static YTD SS wages (FOUND-06) so the cap is respected, and Medicare at 1.45% (no cap)
- [ ] **CALC-05**: Federal withholding computes via the real IRS Pub 15-T 2026 percentage method (Worksheet 1A, all three filing statuses + the Step-2-checkbox branch), standard method only (OBBBA disclaimed)
- [ ] **CALC-06**: Tax constants live in a dated, year-keyed module (source + retrieval date in header); a golden-value test suite asserts hand-computed 2026 paystubs to the penny using `Decimal`
- [ ] **CALC-07**: Net pay computes as gross − pre-tax − FICA − federal withholding
- [ ] **CALC-08**: A reconciliation check confirms net + taxes + deductions ties to the run total and flags any arithmetic drift — this is an arithmetic backstop only, NOT the correctness oracle for the tax math (CALC-06 golden tests are the oracle; stale tables and wrong Pub 15-T logic still tie out internally)

### Ingest & Orchestration

- [ ] **INGEST-01**: A FastAPI webhook accepts an inbound-email payload, returns 200 quickly, and schedules pipeline work as a background task
- [ ] **INGEST-02**: The inbound payload is stored in `email_messages` with Message-ID, In-Reply-To, and References headers; reply quoted-history/signatures are stripped before extraction
- [ ] **INGEST-03**: The sender address is matched to `businesses.contact_email`; an unknown sender is logged and stopped, never guessed
- [ ] **INGEST-04**: An explicit `orchestrator.py` drives the run state machine — it owns the legal `status` transitions and the two pause points (`awaiting_reply`, `awaiting_approval`)
- [ ] **INGEST-05**: A stuck/errored run surfaces an `error` status on the dashboard and can be re-triggered idempotently, resuming from the last persisted status

### LLM Judgment (the gated decisioning core)

- [ ] **LLM-01**: One OpenAI-compatible client wrapper routes per task tier (strong/mid/cheap) by swapping base_url/model/key from config; model IDs are versioned env placeholders recorded for reproducibility
- [ ] **LLM-02**: Structured LLM calls use `response_format={"type":"json_object"}` + Pydantic validation with one reflective retry on a parse failure; temperature 0
- [ ] **LLM-03**: Extraction returns structured per-employee entries (name as written, regular/OT/vacation/sick/holiday hours, and an optional current-run-only 401k contribution override) as a pure importable function — the 401k override applies to this run only and never mutates the employee's stored default
- [ ] **LLM-04**: Deterministic name matching resolves exact / case / whitespace / known-alias hits with no model call; only residual ambiguous names go to the model
- [ ] **LLM-05**: LLM name reconciliation classifies each residual name (typo of a roster employee, nickname, or genuinely-different/unknown person) and returns a match + confidence + short reason; it never re-decides a clean deterministic match
- [ ] **LLM-06**: Deterministic field validation produces a per-field issues list (presence, sanity bounds, numeric)
- [ ] **LLM-07**: The LLM proposes `process` or `request_clarification` with issues, but `decide.py` computes a code-owned `final_action` that hard-blocks on any missing required field or any name unresolved below the 0.8 confidence threshold — even when the model said process. `final_action` is the SOLE branch source consumed downstream; the orchestrator, dashboard, and eval never branch on `model_action`
- [ ] **LLM-08**: The decision object (`model_action`, `gate_triggered`, `gate_reasons`, `final_action`, `unresolved_names`, `missing_fields`, confidence, reasons) is persisted on the run for audit and the eval
- [ ] **LLM-09**: Reconciliation enforces a one-to-one roster mapping — a duplicate submitted name, two submitted names resolving to the same employee, or a name resolving to no roster employee gates the run to clarification (a name cannot silently collapse onto another employee)

### Clarification & Resume

- [ ] **CLAR-01**: When `final_action` is request_clarification, the LLM drafts a clarification email (cheap model) and the system auto-sends it; the outbound Message-ID is stored on the run and status moves to `awaiting_reply`
- [ ] **CLAR-02**: A client reply is routed to its run via the RFC In-Reply-To/References header chain (subject/provider-thread are only fallbacks)
- [ ] **CLAR-03**: A matched reply re-enters the pipeline at extraction and resumes the run, with idempotent re-entrancy (overwrite `extracted_data`, replace line items by run, match only runs in `awaiting_reply`; a header match to a sent/reconciled run is logged as a late reply, not resumed)
- [ ] **CLAR-04**: Outbound sends are idempotent — retrying an approval or re-triggering an errored run (INGEST-05) never sends a duplicate clarification or confirmation email (guard on already-sent state per run)
- [ ] **EMAIL-01**: The stub email gateway records every outbound clarification/confirmation with a synthetic Message-ID in `email_messages` and supports injecting a fixture reply, so the full clarify → reply → resume loop and DEMO-01 are exercisable with zero real email

### Human-in-the-Loop & Delivery

- [ ] **HITL-01**: A computed run pauses at `awaiting_approval`; the operator approves or rejects from the dashboard
- [ ] **HITL-02**: On approval, a confirmation email (LLM-drafted) is sent to the client with paystub PDFs generated on demand; status advances through `approved` → `sent` → `reconciled`
- [ ] **HITL-03**: Paystub PDFs generate on demand from run data in memory (reportlab, BytesIO) — nothing is persisted to disk or a storage bucket

### Dashboard

- [ ] **DASH-01**: A runs list shows every payroll run with a status badge
- [ ] **DASH-02**: A run detail view shows the client's submitted data side-by-side with the computed paystubs and the decision object's reasons
- [ ] **DASH-03**: A pending run's detail view shows Approve-and-send and Reject controls (the operator gate)
- [ ] **DASH-04**: An eval view renders the latest eval summary with the headline metrics and a per-category breakdown chart (clean / typo / missing / unknown / nickname / vague)
- [ ] **DASH-05**: A "Send test email" button fires a fixture through the whole pipeline from the page (demo trigger and live-email fallback)

### Eval (the proof)

- [ ] **EVAL-01**: A synthetic generator produces realistic messy payroll emails + ground-truth JSON, decoupled from the extractor (different model/persona) to prevent train/test leakage; decision-critical cases are hand-labeled
- [ ] **EVAL-02**: ~15–25 email+label fixtures across all seeded categories (clean, name typo, missing hours, unknown employee, nickname, vague hours, buried reply) are committed to the repo for reproducibility
- [ ] **EVAL-03**: `run_eval.py` imports and runs the SAME production pipeline functions over the fixtures and scores the code-owned `final_action` (not the model's raw action)
- [ ] **EVAL-04**: Scoring computes four metrics — extraction field accuracy, name-reconciliation accuracy, decision accuracy (the three core thesis metrics), and an LLM-as-judge email-quality score (lowest-priority metric; first to drop if time is short) — broken out per category
- [ ] **EVAL-05**: Eval results (including the pinned model IDs used) write to `eval_results` and render on the dashboard chart; local eval is authoritative, and CI runs the scorers against cached/committed fixture outputs (no live LLM calls on push) with a manual-dispatch live eval
- [ ] **DEMO-01**: Two canonical demo fixtures are committed and replayable from DASH-05 — one clean happy path (run completes to operator approval) and one code-gated clarify path (the model says process but the gate blocks and forces clarification) — so the 60–90s demo is deterministic and the gate is visible on camera

### Hosting & Ops

- [ ] **OPS-01**: The FastAPI app is containerized in one Dockerfile (binds `0.0.0.0:$PORT`) and deploys as a single Render free web service
- [ ] **OPS-02**: A real email gateway provider is wired behind the existing interface (`parse_inbound`, `send`) as the final integration step, with the fixture path unchanged
- [ ] **OPS-03**: A GitHub Actions keep-alive workflow pings Supabase a couple of times a week so the free project does not pause
- [ ] **OPS-04**: A README documents the system, states the educational/not-tax-compliant disclaimer (including the OBBBA exclusion), and includes an architecture diagram; a 60–90s demo recording exists

## v2 Requirements

Deferred to a future release. Tracked but not in the current roadmap.

### Calculation

- **CALC-V2-01**: Flat-rate state withholding line (the `state_withholding` column already exists, nullable)
- **CALC-V2-02**: Per-employee YTD tax tracking / ledger

### Ingest

- **INGEST-V2-01**: Spreadsheet-attachment parsing (CSV/XLSX timesheets)

### Eval

- **EVAL-V2-01**: Larger fixture corpus with confusion-matrix-style breakdowns and a multi-judge ensemble for email quality

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Client-side confirmation step (second gate) | Breaks the single human-gate narrative; operator approval is the only gate |
| Full OBBBA tax provisions (qualified-tips/overtime deductions, expanded 15-line W-4) | Against the educational-model framing; engine + eval must share the standard-method assumption; disclaimed in README |
| Cached/persisted PDFs + Supabase Storage bucket | PDFs generate on demand; fits Render's ephemeral filesystem; no state to persist |
| Autonomous agent loop / LangGraph | The pipeline path is fixed and controlled; Postgres `status` is the state machine |
| Reasoning models | Non-reasoning chat variants only — lower latency, and this is not multi-step reasoning |
| Dashboard authentication | It's a demo |
| Business/employee onboarding CRUD UI | Seed data covers the demo; CRUD is scope creep |
| In-UI model A/B switching, streaming token UI, eval bias harnesses, retry/queue/observability infra | Tempting-but-wrong traps flagged by research; out of scope for a focused demo |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| (populated by roadmapper) | | |

**Coverage:**
- v1 requirements: 51 total
- Mapped to phases: 0 (pending roadmap)
- Unmapped: 51 ⚠️

---
*Requirements defined: 2026-06-20*
*Last updated: 2026-06-20 after initial definition + Codex cross-AI scope review (added FOUND-06, LLM-09, CLAR-04, EMAIL-01, DEMO-01; clarified CALC-04/08, LLM-03/07, EVAL-04/05)*
