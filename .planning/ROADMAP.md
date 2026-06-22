# Roadmap: Payroll Agent

## Overview

A messy real-world payroll email goes in; a correct, human-approved payroll comes out — with every money-moving judgment call gated by code: deterministic, auditable, never guesses (each submitted name resolved against the roster in pure code; the LLM reads and suggests, but never decides — Phase 2.1). The build is a **Vertical MVP**: a thin foundation, then a walking skeleton that proves the whole gated slice end-to-end ~one-third in (calc deliberately thin — gross + FICA only, net honestly labeled "pre-federal"), then deepening rings ordered by risk. Penny-accurate IRS Pub 15-T federal withholding is hardened in its own ring *before* any correctness claim; the eval (the proof) rides the exact same pure judgment functions as production; the dashboard and delivery wrap the working slice; and the one risky external dependency — real inbound email — is wired last so it never threatens priority #1 (visibly works end-to-end).

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Thin Foundation** - Contracts, minimal schema for the slice, and seed data for one happy-path + one name-mismatch case (completed 2026-06-21)
- [x] **Phase 2: Walking Skeleton** - First end-to-end proof: messy fixture flows through the four gated judgment stages to a code-gated decision (calc thin, net pre-federal) (completed 2026-06-22)
- [x] **Phase 2.1: Deterministic Decisioning** *(INSERTED)* - Replace the confidence-threshold gate with deterministic resolution + collision safety + alias read-side; never guesses on a money-moving decision; LLM kept for extraction + clarification suggestion only (completed 2026-06-22)
- [x] **Phase 3: Harden the Calc** - Real Pub 15-T 2026 federal withholding + full-fidelity gross/FICA/net, golden-tested to the penny (completed 2026-06-22)
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

  1. POST a messy fixture and watch it reach a gated decision — including the code gate deterministically forcing clarification on an unresolvable or ambiguous name (DEMO-01). The canonical demo fixtures (one clean-to-approval, the unknown-shorthand hero that clarifies with a specific suggested employee, and a collision-safety fixture) are committed and replayable. (Note: Phase 2.1 superseded the original "model says process but gate blocks at 0.8" framing with deterministic resolution.)
  2. `decide.py` computes a code-owned `final_action` that hard-blocks on any missing required field, any unresolved name, or any run-level collision — resolving each submitted name against the roster in pure code (exact / stored-alias / none), with no LLM call and no confidence number (superseded the original 0.8 threshold in Phase 2.1); `final_action` is the SOLE branch source — the orchestrator never branches on a model action — and the four judgment stages are pure importable functions (data in, data out).
  3. Reconciliation enforces a one-to-one roster mapping: a duplicate submitted name, two names resolving to one employee, or a name resolving to no employee gates the run to clarification (a name cannot silently collapse onto another, LLM-09).
  4. The orchestrator drives the run state machine through both pause states — a clarify run reaches `awaiting_reply`, an injected fixture reply (zero real email) routes back via the RFC In-Reply-To/References chain, resumes at extraction idempotently, and a computed run pauses at `awaiting_approval` where a crude approve/reject proves the gate pauses and resumes.
  5. Computed paystubs show gross and FICA with net labeled "pre-federal" — no fabricated federal figure appears anywhere.

**Plans**: 4 plans
Plans:
**Wave 1**

- [x] 02-01-PLAN.md — substrate: deps + LLM client wrapper (per-tier, JSON mode, reflective retry, DeepSeek non-thinking) + stub email gateway + DB repo + reconciliation JSONB column + live_llm marker
**Wave 2** *(blocked on Wave 1)*

- [x] 02-02-PLAN.md — slice (a) clean happy path E2E: webhook+BackgroundTasks, four pure stages + the code gate (decide.py), thin gross+FICA (net pre-federal), orchestrator state machine, awaiting_approval pause + crude approve/reject, README disclaimer stub
**Wave 3** *(blocked on Wave 2)*

- [x] 02-03-PLAN.md — slice (b) gate-block: layer-2 LLM reconcile, one-to-one mapping enforcement (LLM-09), clarify draft+send -> awaiting_reply, David Reyez hero fixture (mock proves the gate)
**Wave 4** *(blocked on Wave 3)*

- [~] 02-04-PLAN.md — slice (c) clarify->reply->resume loop: header-chain routing (CLAR-02), idempotent re-entry (CLAR-03), reply-fixture injection (EMAIL-01) — **Tasks 1-2 COMPLETE (CLAR-02/03/EMAIL-01 green; mocked suite 159 passed)**; Task 3 the LIVE hero-run exit gate (D-A4-01a) is a PENDING human-verify checkpoint (env-gated test authored, skips by default)

### Phase 2.1: Deterministic Decisioning *(INSERTED)*

**Goal**: The confidence-threshold gate is replaced by deterministic decisioning that never guesses on a money-moving decision — `decide.py` resolves each submitted name against the roster in pure code (exact / stored-alias / none), enforces run-level collision safety, and computes `final_action` with no LLM call and no confidence number; the LLM is kept for extraction and an optional clarification suggestion only. Alias learning lands READ-side here (WRITE side is Phase 5, operator-gated).
**Mode:** standard (re-architecture of completed, working Phase 2 code — 168 tests green)
**Depends on**: Phase 2
**Requirements**: LLM-04, LLM-05, LLM-07 (rewritten — deterministic resolver, suggestion-only call, code-owned `final_action`); LLM-09 (collision safety, now pure run-level code); DEMO-01 (hero reframed)
**Success Criteria** (what must be TRUE):

  1. No `confidence` / `model_action` / `gate_triggered` / `0.8` threshold anywhere in `app/` (grep-clean); the decision is deterministic.
  2. `decide.py` is pure code (resolution + run-level collision + missing-field → `final_action` with `gate_reasons`; no LLM call); `reconcile_names` is pure code (exact + stored-alias READ only). Both stay importable functions the eval reuses.
  3. `NameMatchResult` = `source`/`resolved`; `Decision` = `final_action`/`gate_reasons`/`unresolved_names`/`missing_fields` + per-name resolutions in JSONB; `name_matches` table dropped from live local + Supabase; `match_confidence` gone; status-drift guard green.
  4. The optional clarification-suggestion call exists (cheap tier, suggestion-only, never feeds decide) and the clarification email names a specific suggested employee.
  5. Config has TWO model tiers (extraction + suggestion/draft); the mid/decision tier is removed from Settings/.env.example/.env.
  6. Full mocked suite green with a new deterministic-resolution taxonomy suite (exact / stored-alias / first-time-alias / typo / collision / unknown / empty-extraction); DEMO-01 fixtures reframed (unknown-shorthand-clarify-with-suggestion + collision-safety; learning beat deferred to P5); CLAUDE.md/REQUIREMENTS.md/PROJECT.md no longer reference the 0.8 gate.

**Plans**: 5 plans
Plans:
**Wave 1**

- [x] 02.1-01-PLAN.md — re-shape the shared contracts: NameMatchResult → source/resolved, Decision → deterministic 4 fields + resolutions, drop PaystubLineItem.match_confidence, delete NameReconciliationResponse

**Wave 2** *(blocked on Wave 1)*

- [x] 02.1-02-PLAN.md — rewrite reconcile_names (pure exact + stored-alias) and decide (pure resolution + run-level collisions + missing-field → final_action); delete the decide/reconcile prompts; new deterministic test taxonomy

**Wave 3** *(blocked on Wave 2)*

- [x] 02.1-03-PLAN.md — wire deterministic stages through orchestrator/repo/schema; DROP name_matches on live local + Supabase + drop match_confidence; remove the mid/decision config tier; keep the drift guard green (NOT autonomous — live-DB DROP + .env checkpoint)

**Wave 4** *(blocked on Wave 3)*

- [x] 02.1-04-PLAN.md — NEW suggestion-only LLM call (cheap tier, never feeds decide): unresolved name → likely employee → the clarification email names a specific suggested employee

**Wave 5** *(blocked on Wave 4)*

- [x] 02.1-05-PLAN.md — reframe DEMO-01 fixtures (hero + collision-safety) + finish the residual test/live-LLM sweep + rewrite CLAUDE.md/REQUIREMENTS.md/PROJECT.md + eval taxonomy; final grep-clean acceptance

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

**Plans**: 3 plans

Plans:
**Wave 1**

- [x] 03-01-PLAN.md — New pure-function modules: tax_tables_2026.py (all 2026 bracket tables + FICA constants, dated header) + federal_withholding.py (Worksheet 1A engine)

**Wave 2** *(blocked on Wave 1)*

- [x] 03-03-PLAN.md — Deepen calculate.py: salaried leave pay (annual/2080 form), FICA constants migration, real federal withholding call, real net, Additional-Medicare limitation flag, reconciliation backstop via PayrollCalculationError + extend tests/test_calculate.py (CALC-01/02/03/04/07/08)

**Wave 3** *(blocked on Wave 2)*

- [x] 03-02-PLAN.md — Golden-value test suite: tests/test_federal_withholding.py covering all 6 Worksheet 1A schedules + D-04 edge cases + the in-PDF wage-bracket PRIMARY oracle + bracket-boundary tests (autonomous: false — layer-B over-ceiling oracle verification checkpoint)

### Phase 4: The Eval (the proof)

**Goal**: A reproducible eval imports and scores the exact same production judgment functions over ~15-25 committed hand-curated fixtures, producing a legible per-category chart that proves the gated decisioning works — the credibility lever for the recruiter audience.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05
**Success Criteria** (what must be TRUE):

  1. `run_eval.py` imports and runs the SAME production pipeline functions and scores the code-owned `final_action` (not the model's raw action), proving the eval tests the production path, not a parallel one.
  2. ~15-25 hand-curated email+label fixtures spanning the name-resolution case taxonomy (Phase 2.1: **exact / stored-alias / first-time-alias / typo / collision / unknown**) plus the field cases (missing hours, vague hours, buried reply) are committed to the repo; the bootstrap drafting helper is named honestly as a drafting aid, and the committed fixtures are the source of truth (no train/test leakage).
  3. Scoring produces the three core thesis metrics — extraction field accuracy, name-reconciliation accuracy (over the deterministic resolver, scored across the exact / stored-alias / first-time-alias / typo / collision / unknown taxonomy), decision accuracy — broken out per category, plus (drop-if-tight) a secondary rubric'd LLM-as-judge email-quality score (EVAL-04).
  4. Eval results (including the pinned model IDs used) write to `eval_results` and render as one clean per-category chart; local eval is authoritative and CI scores against cached/committed fixture outputs with no live LLM calls on push.

**Plans**: 4 plans (3 exit-bar + 1 if-time)
Plans:
**Wave 1**

- [x] 04-01-PLAN.md — Fixture corpus: 15 labeled eval fixtures + stubbed extraction caches + draft_candidate_emails.py helper (D-01..D-05, D-18, D-19 — EVAL-01, EVAL-02)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 04-02-PLAN.md — Core scorer: eval/run_eval.py (extraction F1, per-NAME reconciliation, two-level decision accuracy, confusion matrix, summary.json, --check) + tests/test_eval_wiring.py D-09 smoke test (D-06..D-11 — EVAL-03)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 04-03-PLAN.md — Chart + CI: eval/chart.svg (SVG, committed, recruiter-visible), .github/workflows/eval.yml (hermetic push check + live workflow_dispatch), matplotlib dev dep (D-08, D-17 — EVAL-04, EVAL-05)

**Wave 4** *(if-time, optional — drop first under time pressure)*

- [ ] 04-04-PLAN.md — Optional: D-14 DB write stub + D-15/D-16 LLM-as-judge quality scorer (local-only, correctness floor, never CI — EVAL-04 secondary)

### Phase 5: Dashboard & Delivery

**Goal**: A human operator can approve real payrolls through an honest gate — seeing the raw cleaned inbound email beside the LLM's extraction beside the computed paystubs — then a confirmation email with on-demand PDFs sends only after approval, with idempotent sends and a visible error path.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, HITL-02, HITL-03, CLAR-04, INGEST-05, FOUND-04
**Success Criteria** (what must be TRUE):

  1. A run detail view shows three columns left-to-right — the raw cleaned inbound email body (leftmost, mandatory), the LLM's `extracted_data`, then the computed paystubs — plus the decision object's reasons, so the operator verifies the LLM's *reading* against what the client actually sent (DASH-02, the honest gate).
  2. A runs list shows every run with a status badge; a pending run exposes Approve-and-send and Reject controls (the single operator gate), guarded by `SELECT ... FOR UPDATE` against double-approval (FOUND-04). **⚠ MUST READ `.planning/backlog.md` → "Atomic status claim":** the orchestrator's resume/approve status guards are currently load-then-set (NOT atomic) — a known CR-02 residual found 3× in review. Build the atomic-claim helper (`UPDATE … WHERE status=? RETURNING` / `FOR UPDATE`) HERE and reuse it for approve/reject, resume, and re-trigger so this criterion and #4 are actually race-safe.
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

**Build Notes (uv + Docker):**

The project uses **uv** (not pip/requirements.txt) — see `CLAUDE.md` Tooling Rule. For the `python:3.12-slim` image, do NOT hand-write a `requirements.txt`; generate a pinned, hash-free runtime-only list from the committed `uv.lock` at build time, or use uv directly in the Dockerfile. Two viable approaches:

- **Export then pip install (simplest, smallest base):**
  ```dockerfile
  # On the build host (or a builder stage), regenerate the pinned list from the lock:
  #   uv export --no-dev --no-emit-project --no-hashes -o requirements.txt
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  ```
  Treat the exported `requirements.txt` as a build artifact (gitignore it or generate in CI) — never a tracked source file.

- **uv in the image (reproducible, uses the lock directly):**
  ```dockerfile
  COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
  COPY pyproject.toml uv.lock ./
  RUN uv sync --frozen --no-dev   # installs runtime deps only, exactly from the lock
  # then run via: uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT
  ```

`--no-dev` keeps pytest/ruff out of the runtime image. Bind `0.0.0.0:$PORT` (Render injects `$PORT`, default 10000) per the Render gotcha in CLAUDE.md.

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 2.1 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Thin Foundation | 3/3 | Complete    | 2026-06-21 |
| 2. Walking Skeleton | 4/4 | Complete    | 2026-06-22 |
| 2.1 Deterministic Decisioning *(INSERTED)* | 5/5 | Complete    | 2026-06-22 |
| 3. Harden the Calc | 3/3 | Complete    | 2026-06-22 |
| 4. The Eval | 3/4 | In Progress|  |
| 5. Dashboard & Delivery | 0/TBD | Not started | - |
| 6. Real Integration & Ship | 0/TBD | Not started | - |
