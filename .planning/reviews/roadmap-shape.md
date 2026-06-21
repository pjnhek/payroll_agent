# Roadmap shape — author-specified (Vertical MVP)

`PROJECT_MODE=mvp`. The build-plan author specified the exact phase shape; the roadmapper must follow THIS decomposition, not a generic one. Rationale: the end-to-end gated slice IS the thesis and priority #1; risk lives at the seams and in two stages (Pub 15-T, clarify-resume), not in breadth; the eval rides the same pure functions as production. Vertical forces every seam on day one; stable contracts (FOUND-03) up front make later deepening local.

**Core principle:** a thin foundation, then a walking skeleton (first end-to-end proof ~one-third in), then deepening rings ordered by risk. Calc is deliberately thin in the skeleton — gross + FICA only (real and easy); **federal is left out and net is labeled "pre-federal" rather than showing a fake number** (a plausible-looking wrong figure in a screenshot is the failure to avoid). Penny-accurate Pub 15-T is the very next ring, before any correctness claim. This is how "end-to-end early" and "golden tests before anyone trusts the math" coexist.

## Phases

**Phase 1 — Thin foundation.** Contracts (FOUND-03), minimal schema for the tables the slice touches (FOUND-01 core + `email_messages`), seed one happy-path business + one name-mismatch case (FOUND-05/06). Don't gold-plate. `SELECT ... FOR UPDATE` (FOUND-04) waits until approval concurrency matters.

**Phase 2 — Walking skeleton (first end-to-end proof).** Stub gateway + webhook (EMAIL-01, INGEST-01/02), route (INGEST-03), the four judgment stages as pure functions with real LLM calls and v0 prompts (LLM-01–06), `decide.py` gate computing `final_action` (LLM-07/08/09), orchestrator state machine with both pause states (INGEST-04), crude approve/reject proving the gate pauses+resumes (HITL-01 minimal), clarify-reply-resume via fixture injection (CLAR-01/02/03). Calc thin: gross + FICA only, net labeled pre-federal. Outcome: POST a messy fixture → flows to a gated decision, including the DEMO-01 gate-blocks-the-model case.

**Phase 3 — Harden the calc (first deepening ring, highest correctness risk).** Real Pub 15-T 2026 (CALC-05), dated tax-constants module (CALC-06), golden tests to the penny with `Decimal` (also CALC-01/02/03/04/07/08 brought to full fidelity). Lands BEFORE eval or dashboard present numbers as correct — CALC-08 reconciliation catches arithmetic drift only, not a wrong table.

**Phase 4 — The eval (the proof).** Hand-curated fixtures + bootstrap drafting helper (EVAL-01/02), `run_eval.py` importing the same functions, scoring `final_action` (EVAL-03), three core metrics + optional rubric'd judge per category (EVAL-04), results→chart with cached-output CI (EVAL-05).

**Phase 5 — Dashboard & delivery.** Full run detail with raw email beside extracted beside computed (DASH-02, the gate-theater fix), runs list, eval view, send-test-email (DASH-01/03/04/05), confirmation email + on-demand PDFs (HITL-02/03), outbound idempotency + descoped error path (CLAR-04, INGEST-05), FOUND-04 `SELECT ... FOR UPDATE`.

**Phase 6 — Real integration & ship.** Real provider behind the interface, fixture path unchanged (OPS-02), Docker + Render + Supabase + keep-alive (OPS-01/03), README with disclaimer + diagram + demo recording (OPS-04).

## Constraints for the roadmapper
- Map all 51 v1 requirements to exactly one phase, following the placement above.
- Protect the DRY seam (LLM-07 `final_action` sole branch source; gates in `decide.py`; eval imports the same functions).
- Drop-if-tight items: EVAL-04 (judge metric), INGEST-05 (error recovery).
- Success criteria per phase = observable user/system behaviors (e.g. Phase 2: "POST a messy fixture and watch it reach a gated decision, including the gate blocking a model 'process'").
