# Project Research Summary

**Project:** Payroll Agent
**Domain:** LLM-driven email-to-payroll automation pipeline with a single human-in-the-loop gate (portfolio/demo, recruiter audience; free-tier hosting, Postgres-as-state-machine)
**Researched:** 2026-06-20
**Confidence:** HIGH (architecture/stack/features); MEDIUM-with-flags on two numeric/identifier surfaces (exact LLM model IDs, 2026 IRS Pub 15-T tables) that must be transcribed from live sources, not memory.

## Executive Summary

This is a **portfolio artifact, not a payroll product.** The "users" are hiring managers and technical reviewers who spend under two minutes scanning for a deployment link they can try, a quantified metric tied to impact, and visible safety/interpretability mechanisms. Every design choice serves a fixed priority order: **(1) visibly works end-to-end -> (2) clean 60-90s demo -> (3) a real, legible eval chart.** Experts build systems like this as a *deterministic-first, code-gated* pipeline where the LLM is a *proposer under constraints*, not a decider -- and where the durable state engine is Postgres (the `status` column IS the state machine and the HITL checkpoint), not an agent framework. The locked stack (FastAPI + Pydantic v2 + OpenAI-compatible client + psycopg3 + Supabase + reportlab on Render free) is exactly right for this; the research deepens rather than relitigates it.

The recommended approach has **one load-bearing design constraint that dominates everything else** -- call it the **DRY seam.** The four judgment stages (`extract`, `reconcile_names`, `validate`, `decide`) must be written as **pure importable functions** that take Pydantic data in and return Pydantic data out (`def extract(email_text, *, llm) -> Extracted`, **never** `def extract(run_id)`). The **hard gates must live INSIDE `decide.py`**, computing a code-owned `final_action` that overrides the LLM's proposal -- not in the orchestrator. And the **eval must import and score those exact same functions and that exact `final_action`.** This single choice is what makes the eval credible *and* tests the project's core thesis ("a low-confidence match can never reach a real payroll calculation"). If the gate lived in the orchestrator, the eval would test a different code path than production, and the whole portfolio story would be unverifiable. The roadmap must treat this seam as a hard, early constraint, not a refactor to discover later.

The key risks cluster on two surfaces. **First, the IRS Pub 15-T calc engine is the single highest bug-risk unit, and its bugs are INVISIBLE to the reconciliation check** -- a payroll computed with last year's wage base still ties out internally; it is just wrong against reality. Only *golden-value unit tests* against hand-computed 2026 paystubs catch stale constants, Worksheet 1A order-of-operations errors, the 401k/FICA pre-tax sequencing trap, and FLSA overtime miscounts. **Second, the resume-on-reply re-entrancy** requires strict idempotency invariants (overwrite `extracted_data`, replace-by-run line items, match replies only to runs in `awaiting_reply`). Both warrant isolated, heavily-tested phases. Mitigation is built into the architecture: a pure, isolated calc engine unit-tested in parallel with everything else, and durable status checkpoints so a Render cold-start never loses a run. Several **decisions emerged from research that must be made explicitly in requirements** (tax year + OBBBA scoping, exact model IDs, an explicit orchestrator module, a stuck-run recovery path) -- flagged below; do not let them resolve by accident.

## Key Findings

### Recommended Stack

The stack is locked and verified against PyPI + official docs (June 2026). It is a single FastAPI process on one Render free web service, with Postgres as the only state. The two soft spots are not library choices but *external values that drift*: the exact LLM model IDs and the 2026 tax tables -- both must be pulled from live sources and pinned, never remembered. See **STACK.md** for full version pins, usage patterns, and gotchas.

**Core technologies:**
- **FastAPI 0.138.0 + Pydantic v2 (2.13.4)** -- webhook + dashboard + the shared contract layer. Pydantic models are the contracts that let eval and production share code. Use v2 idioms (`model_validate_json`, `ConfigDict`), not v1.
- **openai 2.43.0 (OpenAI-compatible client)** -- ONE client, `base_url`/`model`/`key` swapped per task tier. **Use `response_format={"type":"json_object"}` + `model_validate_json()` + retry -- NOT `.parse()`/strict `json_schema`** (DeepSeek doesn't support strict schema; targeting it breaks the provider-agnostic path).
- **psycopg3 (3.3.4, `[binary,pool]`)** -- direct Postgres for real transactions + `SELECT ... FOR UPDATE` to prevent double-approval. NOT `supabase-py` (a REST wrapper with no transactions). Connect Render->Supabase via the **Supavisor pooler host, transaction mode port 6543** (the direct host is IPv6-only; Render is IPv4-only).
- **reportlab 5.0.0** -- pure-Python, BSD, zero native deps; generate PDFs in-memory to `BytesIO` and stream them (Render FS is ephemeral). Avoid WeasyPrint (heavy native deps bloat the slim image).
- **Jinja2 3.1.6, server-rendered** -- 4 dashboard pages, no SPA/build step.
- **Year-keyed tax constants module + `TAX_YEAR` env** -- SS wage base **$184,500** (2026), Medicare 1.45% no cap; Pub 15-T brackets transcribed from the live PDF. Never inline a tax number.

### Expected Features

The audience lens reframes "table stakes" as *what makes this read as a credible agentic system in a 60-90s look.* Three differentiators are the headline; do not spread effort thin. See **FEATURES.md** for the full landscape, dependencies, and anti-features.

**Must have (table stakes -- absence disqualifies):**
- **LLM extraction** (messy email -> structured per-employee JSON, JSON mode + Pydantic + retry) -- the "LLM reads" beat
- **Real IRS Pub 15-T federal withholding + gross/FICA/FLSA-OT** -- a payroll demo that fakes the math is not a payroll demo (highest bug risk -> isolated, unit-tested)
- **Single operator approval gate** (side-by-side submitted vs computed, gated BEFORE the send) -- the narrative spine
- **Reconciliation check** (net + taxes + deductions ties out) -- cheap "system checks its own work"
- **Runs list + status badges, "Send test email" button, deployed Render instance + README disclaimer** -- the demo surface; the test button is the on-camera trigger AND the live-email fallback

**Should have (the three differentiators that make a reviewer lean in):**
- *** Name reconciliation** (deterministic-first; LLM only on residual ambiguity; typo vs nickname vs different-person, with confidence + reason) -- *the headline*; the deterministic-first split is itself the impressive part
- *** Code-gated process-vs-clarify decisioning** (LLM proposes, code disposes at 0.8) -- *the trust mechanism*; the gate must visibly override the model
- *** The eval chart** (4 metrics over ~15-25 committed fixtures, one legible chart) -- *the proof, not the demo*; reproducibility is the credibility lever
- **Clarification round-trip** (auto-send, client replies on thread, run resumes via RFC headers) -- differentiator, *not* table stakes; highest-risk-vs-payoff, prove via fixtures, wire the real provider last

**Defer (v2+ -- already correctly scoped out):**
- State withholding (nullable column stays), spreadsheet-attachment parsing, cached/persisted PDFs + Storage bucket, client-confirm second gate (breaks the single-gate narrative), reasoning models, dashboard auth, eval exotica (bias harnesses), retry/queue/observability infra, per-employee YTD ledger.

### Architecture Approach

The one idea that makes it work: **there is no in-memory orchestration state and no message queue -- `payroll_runs.status` IS the state machine.** Every stage reads the run, does its work, writes the next status. A pause is a status the orchestrator stops at; a resume is an inbound event (webhook or button) that re-invokes the orchestrator on a paused run. There are exactly **two pauses**: `awaiting_reply` (machine pause on the client, resumes at stage 2) and `awaiting_approval` (the single HITL gate, resumes at stage 8). This is why "plain Python + Postgres" replaces LangGraph cleanly and survives Render cold starts. See **ARCHITECTURE.md** for the full state machine, the fixture seam, re-entrancy invariants, and the 6-tier build-order graph.

**Major components:**
1. **Edge / FastAPI (`app/main.py`)** -- thin HTTP adapter; returns 200 fast, schedules a `BackgroundTask`. No business logic.
2. **Pipeline orchestrator (`app/pipeline/orchestrator.py` -- ADD THIS)** -- the unnamed-but-required state-machine driver; owns legal status transitions and where the pauses are. *Not named in the original repo structure; the roadmap must add it explicitly.*
3. **Judgment stages (`extract`, `reconcile_names`, `validate`, `decide`)** -- pure importable functions over `models/` types; **`decide.py` contains the hard gates and computes `final_action`.** Imported by both the orchestrator AND the eval (the DRY seam).
4. **Calc engine (`calculate.py` + `reconcile_payroll.py`)** -- PURE functions, zero upstream deps; the only component buildable + unit-testable in complete isolation. Highest bug risk -> isolate early.
5. **LLM client (`llm/client.py`)** -- one OpenAI-compatible client, per-task routing, JSON mode, retry. Vendor-agnostic.
6. **Email gateway (`email/gateway.py`)** -- the ONE provider-aware seam (`parse_inbound`, `send -> message_id`); stubbed until last.
7. **DB layer, PDF generator, dashboard, eval harness** -- DB is the single status mutator; PDF is stateless on-demand bytes; dashboard is read-only except approve/reject; eval imports production functions.

**Build order (6 tiers, the spine of phase sequencing):** contracts/schema first -> LLM client + pure calc engine in parallel -> webhook + orchestrator + 4 judgment stages with a **stub gateway** (= first "visibly works end to end") -> clarify/threading/dashboard -> eval + PDFs + reconciliation -> real provider + deploy + CI **last**.

### Critical Pitfalls

The pitfalls are ranked by threat to (1) eval credibility, (2) demo stability, (3) payroll correctness. Payroll-math bugs are over-represented because they are the highest bug-risk surface AND invisible to the reconciliation check. See **PITFALLS.md** for all 18 with warning signs, recovery costs, and the pitfall-to-phase map.

1. **Stale/wrong-year tax constants (P1)** -- a code-writing LLM confidently emits last year's $176,100 wage base or stale brackets; the reconciliation check will NOT catch it. *Avoid:* one dated `tax_tables_2026.py` module with source + retrieval date in a header; a golden-value unit test asserting a hand-computed 2026 paystub to the penny.
2. **The LLM decision is trusted instead of code-gated (P6 -- the core narrative failure)** -- if a reviewer can produce one email where the model says `process` and code should have blocked it but didn't, the whole story collapses. *Avoid:* code computes the gate independently of the model's action; the decision object's `final_action` is code-owned; the eval scores `final_action`, not `model_action`. Seed a "model-says-process-but-field-missing" fixture.
3. **Eval doesn't exercise the production path / train-test leakage (P9, P10)** -- eval calls a parallel code path, or fixtures are generated by the same model/prompt that extracts them, so the chart proves the wrong thing (and a sharp reviewer asks exactly this). *Avoid:* eval imports the SAME functions; decouple the fixture generator from the extractor (different model/persona); hand-label the decision-critical cases.
4. **Non-deterministic / non-reproducible eval (P8)** -- the headline metric can't be reproduced a week later; CI flaps red/green. *Avoid:* `temperature=0`, **pin versioned model IDs (not floating aliases) and record them in `eval_results`**, consider caching raw model outputs for committed fixtures.
5. **Payroll-math sequencing traps (P2-P5)** -- Worksheet 1A order-of-operations, **401k reduces the federal base but NOT the FICA base**, FLSA OT computed on worked-hours-only (paid leave excluded from the 40-hr threshold), and `Decimal`-not-`float` to keep the reconciliation check honest. *Avoid:* named intermediates (`fica_wages`, `fed_taxable_wages`), table-driven tests across filing status x checkbox x credits, and targeted fixtures ("40 worked + 8 vacation" -> 0 OT; FICA constant as 401k% varies).

## Implications for Roadmap

Based on combined research, the suggested phase structure follows the architecture's 6-tier dependency graph, corroborated by the feature dependencies. The **non-negotiable sequencing principle**: build the judgment stages as **pure importable functions with the gate inside `decide.py`** (the DRY seam) before wiring any persistence or endpoints around them -- otherwise the eval (differentiator #3) becomes a rewrite. The calc engine, being the only zero-dependency component and the highest bug risk, is isolated and tested in parallel from the start.

### Phase 1: Contracts & Foundations
**Rationale:** The schema and Pydantic models are the contracts every other component imports (Tier 0); nothing works without them. Locking the `decision`-object schema (`{model_action, gate_triggered, gate_reasons[], final_action, unresolved_names[], missing_fields[]}`) early prevents late ripple into the gate, the dashboard, AND the eval.
**Delivers:** `db/schema.sql` (6 tables, the 11-value status enum, **a unique index on `email_messages.message_id` for idempotency**), `db/supabase.py` typed accessors, and all `models/` Pydantic contracts (InboundEmail, Extracted, Decision, PaystubLineItem).
**Addresses:** the shared-contract substrate beneath every feature.
**Avoids:** P13 (duplicate webhook -> no second run, via the unique index); late schema churn.

### Phase 2: Pure Calc Engine (isolated, golden-value tested)
**Rationale:** The only component with zero upstream dependencies (Tier 1), buildable in parallel with everything else, and the single highest bug-risk unit whose bugs are invisible to the reconciliation check. Isolating and over-testing it early de-risks the entire schedule.
**Delivers:** `calculate.py` + `reconcile_payroll.py` as pure functions -- gross, FLSA OT, salary proration, 401k, FICA, **real IRS Pub 15-T percentage method (Worksheet 1A, all three filing statuses + Step-2-checkbox branch)**, net, and the `Decimal`-exact reconciliation check; a dated `tax_tables_2026.py`; a table-driven golden-value test suite.
**Uses:** `Decimal` throughout; year-keyed constants (reportlab not yet).
**Avoids:** P1 (stale constants), P2 (Worksheet 1A order), P3 (FLSA OT base/threshold), P4 (401k/FICA sequencing), P5 (penny drift).
**Decision required first:** tax year (2025 vs 2026) and OBBBA scoping -- see Gaps.

### Phase 3: LLM Client + Judgment Stages with the Gate (the DRY seam) + Webhook + Orchestrator -- *"visibly works end to end"*
**Rationale:** This is the milestone that satisfies priority #1. With a **stub gateway** (synthetic `Message-ID`), the whole happy path + name-mismatch + clarify->reply->resume runs with ZERO real email. The judgment stages are pure functions; the orchestrator ties them to persistence; **the hard gates live inside `decide.py` computing `final_action`.**
**Delivers:** `llm/client.py` (base_url/model/key swap, `json_object` mode, reflective retry); `extract`/`reconcile_names`/`validate`/`decide` as pure functions; the **explicit `orchestrator.py`** state-machine driver; `main.py` webhook (returns 200 fast, schedules `BackgroundTask`); `ingest.py` with reply-body stripping; stub `email/gateway.py`.
**Implements:** the Edge, orchestrator, judgment stages, LLM client.
**Avoids:** P6 (code-gated decision -- *the thesis*), P7 (name match calibration), P8 (temperature 0, pinned model IDs), P12 (quoted-history pollution), P14 (JSON-mode failures, hallucinated-employee cross-check, reflective 2nd retry).
**This is the load-bearing phase** -- get the DRY seam and the in-`decide.py` gate right here or pay for it in Phase 5.

### Phase 4: Close the Loop -- Clarify Round-trip, Threading, Dashboard
**Rationale:** Tier 3; needs runs to exist before there's anything to render or resume. The resume logic is proven against fixtures (the test button replays a fixture), keeping real email off the critical path.
**Delivers:** `compose_email.py` (cheap model) + clarify auto-send + threading store; resume-on-reply lookup (RFC header chain, with strict re-entrancy idempotency); dashboard (runs list, run detail with side-by-side submitted vs computed + the decision object's reasons, approve/reject buttons, "Send test email" button).
**Addresses:** the clarification differentiator + the operator-gate narrative spine.
**Avoids:** P11 (header-not-subject threading), re-entrancy non-idempotency (overwrite `extracted_data`, replace-by-run line items, match replies only to `awaiting_reply` runs).

### Phase 5: The Proof -- Eval Harness + PDFs + Reconciliation View
**Rationale:** Tier 4; the eval's entire value is reusing the Phase 3 judgment functions, so it cannot precede them. The chart is priority #3.
**Delivers:** `generate_fixtures.py` (**decoupled from the extractor** -- different model/persona), ~15-25 committed fixtures across all categories, `run_eval.py` (imports the SAME pipeline functions, scores `final_action`), `scorers.py` (4 metrics), `eval_results` write + dashboard chart; on-demand paystub PDFs (stage 8 attach); the stage-9 reconciliation view.
**Implements:** the eval harness, PDF generator.
**Avoids:** P9 (train-test leakage -- design the generator correctly BEFORE generating; expensive to redo), P10 (eval path divergence -- integration test that the scorer sees the stored decision object).

### Phase 6: Wire Reality + Ops (LAST, by design)
**Rationale:** Tier 5; real email, deploy, and CI are packaging, not logic. The real provider touches only `gateway.parse_inbound` + real `send`. Treating this as the isolated tail protects priority #1.
**Delivers:** real `email/gateway.py` provider (n8n / inbound-parse), Dockerfile (bind `0.0.0.0:$PORT`), Render deploy, Supabase project via the pooler, `.github/workflows` (keepalive.yml + eval.yml), README + architecture diagram + 60-90s demo.
**Avoids:** P15 (cold-start -- pre-warm + fixture-replay fallback), P16 (ephemeral FS -- PDFs on demand), P17 (verify keep-alive actually ran), P18 (demo-day fallback -- fixture replay reproduces on-screen result without the gateway).

### Phase Ordering Rationale

- **The DRY seam dictates everything.** Pure functions + gate-in-`decide.py` + eval-imports-the-same-functions must be established in Phase 3 before the eval (Phase 5) exists. Reversing this turns the eval into a rewrite and leaves the project's core thesis untested.
- **Dependencies discovered:** contracts (P1) -> LLM client + calc engine in parallel (P2 calc has zero deps) -> webhook/orchestrator/stages with stub gateway (first end-to-end) -> dashboard/clarify (need runs to exist) -> eval (needs reusable judgment functions) -> real provider/deploy (packaging).
- **Risk isolation:** the two highest-risk units -- the Pub 15-T calc engine and the resume-on-reply re-entrancy -- get their own focused phases (2 and 4) with targeted golden/idempotency tests, because their bugs are invisible to the runtime backstops.
- **Priority alignment:** Phase 3 delivers "visibly works end to end" (#1) with zero external email risk; the test-email button and fixture-replay fallback (#2) are built into Phases 3-4; the eval chart (#3) lands in Phase 5; the riskiest external dependency (real inbound email) is deferred to Phase 6.

### Research Flags

Phases likely needing deeper research during planning (`/gsd-plan-phase --research-phase <N>`):
- **Phase 2 (calc engine):** **CONFIRM the 2026 Pub 15-T bracket tables + Step-1 standard amounts against the live IRS PDF** (`irs.gov/pub/irs-pdf/p15t.pdf`) -- the 2026 edition incorporates OBBBA; any number from memory is stale. Confidence on the *numbers* is LOW until transcribed. This is the single most research-dependent phase.
- **Phase 3 (LLM client):** **CONFIRM exact model IDs against the consoles** -- `deepseek-chat` deprecates 2026/07/24 (-> `deepseek-v4-flash` non-thinking); Kimi non-reasoning is `moonshot-v1-*` at `api.moonshot.ai/v1`. Verify how to force non-thinking mode and pin versioned IDs.
- **Phase 6 (real gateway):** the chosen provider's inbound payload shape, signing-secret verification, and whether it offers a `stripped-text`/reply-only field -- only known once the provider is picked.

Phases with standard patterns (skip research-phase):
- **Phase 1 (contracts/schema):** well-documented Pydantic v2 + Postgres DDL.
- **Phase 4 (dashboard):** standard FastAPI + Jinja2 server-rendered pages; RFC threading is well-specified.
- **Phase 5 (eval harness):** the patterns (import production fns, score `final_action`, decouple generator) are spelled out in research; the work is disciplined execution, not discovery.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Versions/hosting/DB/LLM-client mechanics verified against PyPI + official docs (Jun 2026). Two flagged exceptions: exact model IDs (MEDIUM) and 2026 tax tables (LOW until transcribed). |
| Features | HIGH | Recruiter-audience lens corroborated by multiple hiring-signal sources; HITL and entity-resolution best practices independently arrive at the same layered/gated design. |
| Architecture | HIGH | Locked design; the three load-bearing mechanisms (FastAPI BackgroundTasks, OpenAI-compatible routing, Postgres-as-state-machine) verified against current docs. The DRY seam and re-entrancy invariants are deeply specified. |
| Pitfalls | HIGH | Payroll-math facts verified against IRS.gov/SSA.gov; structured-output/eval/gating failure modes are well-established. MEDIUM only on model-specific JSON behavior (varies by provider/version). |

**Overall confidence:** HIGH -- with two narrowly-scoped numeric/identifier gaps (model IDs, 2026 tax tables) that are *known, flagged, and resolvable by transcription from live sources at the start of their respective phases.*

### Gaps to Address

These emerged from research and must be **decided explicitly during requirements/planning -- do not let them resolve by accident:**

- **Tax year + OBBBA scope (decide BEFORE Phase 2):** 2025 vs 2026 tables, and whether to scope to the standard percentage method and **explicitly DISCLAIM OBBBA** (qualified-tips/overtime deductions, expanded W-4 Step-4(b) 15-line worksheet). The 2026 Pub 15-T incorporates OBBBA. The eval's ground truth and the engine must share the same assumption or they will silently diverge. *Recommendation: scope to standard percentage method, disclaim OBBBA, in writing.*
- **Exact LLM model IDs (confirm at Phase 3):** `deepseek-chat`/`deepseek-reasoner` deprecate 2026/07/24; target `deepseek-v4-flash` non-thinking and `moonshot-v1-*`. Pin **versioned** IDs (not floating aliases) and **record them in `eval_results`** for reproducibility.
- **Explicit orchestrator module:** add `app/pipeline/orchestrator.py` (the state-machine driver) to the roadmap -- it is required by the design but unnamed in the original repo structure. Keep all transition logic here, not scattered across stage files.
- **Stuck-run / error recovery path:** in-process `BackgroundTasks` on a sleeping dyno can strand a run mid-`extracting`/`computed`. Specify at minimum dashboard visibility of `error`/stuck runs, ideally an idempotent re-trigger that resumes from the last persisted status. This is a first-class recovery state, not an afterthought.
- **Idempotency / re-entrancy invariants (enforce in Phase 4):** overwrite (not accumulate) `extracted_data`; replace-by-run (not insert-only) line items; match replies only to runs in `awaiting_reply` (a header match to a `sent`/`reconciled` run is a late reply -- log, don't resume).

**Carry-forward technical gotchas (cite in the relevant phases):** `response_format={"type":"json_object"}` not strict schema/`.parse()`; Supavisor pooler host port 6543 (IPv4/IPv6 mismatch otherwise); psycopg3 + `SELECT FOR UPDATE` against double-approval; reportlab 5.0.0 in-memory PDFs; 2026 SS wage base $184,500 / Medicare 1.45%; 401k reduces federal base but NOT FICA base; FLSA OT excludes paid-leave hours from the 40-hr threshold.

## Sources

### Primary (HIGH confidence)
- IRS Pub 15-T (2026) -- `irs.gov/publications/p15t`, `irs.gov/pub/irs-pdf/p15t.pdf` -- Worksheet 1A percentage method, three filing statuses, Step-2-checkbox tables. *Method HIGH; 2026 numbers must be transcribed.*
- SSA COLA 2026 + Contribution & Benefit Base -- `ssa.gov/oact/cola/cbb.html` -- 2026 SS wage base $184,500, OASDI 6.2%, Medicare 1.45%.
- IRS Topic 751 -- `irs.gov/taxtopics/tc751` -- FICA rates.
- PyPI JSON API -- verified version pins for fastapi 0.138.0, pydantic 2.13.4, openai 2.43.0, psycopg 3.3.4, reportlab 5.0.0 (BSD), jinja2 3.1.6, uvicorn 0.49.0, pydantic-settings 2.14.2 (Jun 20 2026).
- DeepSeek API docs (`api-docs.deepseek.com`) + Moonshot/Kimi docs (`platform.kimi.ai`) -- `json_object` only on DeepSeek; non-reasoning families; ID deprecations.
- openai-python README/helpers -- `base_url` swap; `.parse()` sends strict json_schema.
- FastAPI BackgroundTasks (Context7 `/fastapi/fastapi`), OpenAI Python client (Context7 `/openai/openai-python`) -- verified the return-200-fast + per-task-routing patterns.
- Render docs (`render.com/docs/free`) + Supabase docs (Supavisor/connection) -- 15-min sleep, $PORT, IPv4-only, ephemeral FS, 750 hrs; transaction mode 6543, pooler host for IPv4.
- FLSA overtime + RFC 5322 threading + webhook at-least-once delivery -- standard practice.

### Secondary (MEDIUM confidence)
- PayrollOrg / Grant Thornton -- 2026 Pub 15-T includes OBBBA (qualified-tips/overtime, expanded Step-4(b) worksheet).
- Mercer / Paycor / OnPay / Kiplinger -- corroborate SS wage base $176,100 (2025) -> $184,500 (2026), max employee tax $11,439.
- Salesforce Engineering, Babel Street -- layered, confidence-scored, LLM-on-residual entity resolution validates the Stage 3 design.
- Towards Data Science, MachineLearningMastery, Permit.io -- HITL gate-before-side-effect, draft-and-approve diff UX, LangGraph as the default (deliberately not used).
- DeepEval, Label Studio -- LLM-as-judge ~85% human agreement, known biases (acknowledge, don't build the harness).
- Interview Kickstart, Let's Data Science, Medium -- hiring signals: deployment link, quantified metrics, interpretability/safety, cost/latency awareness.
- python-taxes 0.7.0 (MIT, 2023-2025) + IRS-Public/tax-withholding-estimator -- Pub 15-T reference implementations / correctness oracle.

### Tertiary (LOW confidence -- needs validation during planning)
- Exact 2026 Pub 15-T bracket rows + Step-1 standard amounts -- transcribe from the live PDF at Phase 2.
- Exact DeepSeek/Kimi model IDs + how to force non-thinking mode -- confirm against the consoles at Phase 3.
- DeepSeek/Kimi JSON-mode reliability specifics -- vary by provider/version; verify per provider.

---
*Research completed: 2026-06-20*
*Ready for roadmap: yes*
