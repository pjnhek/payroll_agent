# Payroll Agent

## What This Is

An email-driven system that automates the weekly payroll intake the builder used to do by hand as a tax analyst. A client business emails its employees' hours; an LLM-driven pipeline reads the email, reconciles the submitted names against the business's roster, decides whether it can process the run or must ask the client a clarifying question, computes the payroll (gross, FICA, real IRS Pub 15-T federal withholding), and routes the result to a single human operator for one approval before the confirmation goes back to the client. Built end-to-end on a free stack so it runs and demos cleanly.

The narrative for the writeup: the manual payroll process from the builder's accounting days, rebuilt as an agentic pipeline — the LLM does the reading, name matching, and decisioning; a human approves only the final payroll before it reaches the client. **Primary audience: hiring managers / recruiters.** Optimize for *visibly works end to end* > *clean 60–90s demo* > *a real, legible eval chart*.

## Core Value

A messy real-world payroll email goes in; a correct, human-approved payroll comes out — and every judgment call (name match, process-vs-clarify) is made by the LLM but **gated by code so a low-confidence match can never reach a real payroll calculation.** If that gated decision flow works, everything else is plumbing.

## Requirements

### Validated

- **Phase 1 (Thin Foundation), 2026-06-21:** The shared contract substrate exists and is proven by tests — the Postgres schema (6 tables, 11-value `payroll_runs.status` enum, `email_messages.message_id` idempotency UNIQUE), the shared `app/models/` Pydantic v2 contracts imported by both pipeline and eval, and seed data covering 3 businesses / 6 employees across every calc path and name-match case (happy-path + name-mismatch). FOUND-01, FOUND-02, FOUND-03, FOUND-05, FOUND-06. (Live-DB round-trip tests are written and skip-guarded pending Supabase credentials.)

### Active

<!-- All hypotheses until shipped and validated. Grouped by capability. -->

**Ingest & threading**
- [ ] Inbound email is parsed and posted to a FastAPI webhook; row stored in `email_messages` with `Message-ID`, `In-Reply-To`, `References`
- [ ] Sender address is matched to `businesses.contact_email`; unknown sender is logged and stopped (never guessed)
- [ ] A clarification reply is routed back to its run via the RFC `In-Reply-To`/`References` header anchor and resumes the pipeline
- [ ] Email gateway sits behind one interface; whole pipeline is developable by POSTing JSON fixtures (provider wired last)

**Extraction & reconciliation (the judgment layer)**
- [ ] LLM extracts structured per-employee entries (name as written, regular/OT/vacation/sick/holiday hours, any 401k change) via JSON mode + Pydantic, retry once on parse failure
- [ ] Deterministic name match resolves exact / case / whitespace / known-alias hits with no model call
- [ ] LLM name reconciliation runs only on names that fail the deterministic match; returns match + confidence + short reason; never re-decides a clean match
- [ ] Deterministic field validation produces a per-field issues list (presence, sanity bounds, numeric)
- [ ] LLM decision returns `process` or `request_clarification` + issues; **code hard-gates** it (block on missing required field or any name unresolved below the 0.8 confidence threshold)

**Payroll calculation**
- [ ] Gross pay: hourly × rate with FLSA overtime at 1.5× over 40 hrs/week; salary = annual ÷ pay periods; plus vacation/sick/holiday
- [ ] Pre-tax 401k as a percent of gross
- [ ] FICA: Social Security 6.2% up to the current-year wage base, Medicare 1.45%
- [ ] Federal withholding via the **real IRS Pub 15-T percentage method** (annualized, per filing status)
- [ ] Net pay = gross − pre-tax − FICA − federal
- [ ] Reconciliation check: net + taxes + deductions ties to the run total; drift is flagged

**Human-in-the-loop & delivery**
- [ ] One operator gate: dashboard shows client's submitted data beside computed paystubs + the decision object; operator approves or rejects
- [ ] Clarification emails are LLM-drafted and auto-sent; the confirmation email sends only after operator approval
- [ ] Approved run sends a confirmation email to the client with on-demand-generated paystub PDFs

**Dashboard**
- [ ] Runs list with status badges
- [ ] Run detail: side-by-side submitted vs computed, decision object with reasons, Approve/Reject on a pending run
- [ ] Eval view: latest eval summary + headline metrics + a small chart
- [ ] "Send test email" demo button that fires the whole flow from the page

**Eval (the proof)**
- [ ] Synthetic generator prompts a model to emit realistic messy payroll emails + ground-truth JSON, seeded across categories (clean, typo, missing hours, unknown employee, nickname, vague hours, buried reply)
- [ ] ~15–25 email+label fixtures committed to the repo for reproducibility
- [ ] Scoring over fixtures: extraction field accuracy, name-reconciliation accuracy, decision accuracy, LLM-as-judge email quality
- [ ] Results write to `eval_results` and render on the dashboard as one clean summary chart
- [ ] Eval runs locally and in GitHub Actions on each push

**Hosting & ops**
- [ ] FastAPI app containerized in one Dockerfile, deployed as a single Render free web service
- [ ] Supabase Postgres holds all state (it is also the human-in-the-loop checkpoint)
- [ ] GitHub Actions keep-alive pings Supabase so the free project doesn't pause; eval workflow runs on push

### Out of Scope

- **Client-side confirmation step** — operator approval is the only gate; the single-gate story is the narrative. (Open decision #2, resolved.)
- **State withholding** — federal + FICA only, with a clear disclaimer; per-state withholding is genuinely complex and not core to the demo. `state_withholding` column stays nullable for later. (Open decision #3, resolved.)
- **Cached/persisted PDFs + Supabase Storage bucket** — paystubs generate on demand from run data; fits Render's ephemeral filesystem. (Open decision #1, resolved.)
- **Autonomous agent loop / LangGraph** — the path is fixed and controlled; a plain Python workflow with Postgres state is the orchestration.
- **Reasoning models** — non-reasoning chat variants only; over-thinking adds latency and this is not multi-step logic.
- **Tax-compliant production accuracy** — this is an explicitly educational model; the README says so plainly.
- **Auth on the dashboard** — it's a demo.
- **Spreadsheet-attachment parsing** — noted as a "later" stretch in the source plan; deferred from v1.
- **OBBBA tax provisions** — qualified-tips/overtime above-the-line deductions and the expanded 15-line W-4 Step-4(b) worksheet (new in the 2026 Pub 15-T) are explicitly disclaimed in the README; the engine implements the standard percentage method only. (Surfaced by research; resolved.)

## Context

- **Origin:** rebuild of the builder's real manual weekly-payroll intake from their tax-analyst/accounting days. The operator role is the role the builder personally played.
- **Decisioning model (the heart of the design), three layers:**
  1. *Deterministic fast-path* (code, no model): exact/normalized/alias name match, required-field presence, sanity bounds, arithmetic. Anything unambiguous resolves here and never touches a model.
  2. *LLM judgment* (only where language understanding is needed): fuzzy name reconciliation (typo vs nickname vs different person, with confidence + reason) and the process-vs-clarify decision.
  3. *Hard gates* (code): even on a model "process," code blocks a truly-missing field or any name unresolved below the 0.8 threshold. Keeps the decision auditable.
- **Pipeline stages (9):** ingest/route → extract → name reconcile → field validate → decide (gated) → clarify-path or process-path → operator approval → send → reconciliation check.
- **Model tiering:** extraction = stronger model; name reconcile = strong/mid; decision = mid (gated); email drafting = cheap. One OpenAI-compatible client, base URL/model/key swapped per task.
- **Fixture-first development:** the whole pipeline is built and demoable by POSTing JSON fixtures to the webhook; the real email provider (n8n or a hosted inbound-parse service) is wired **last**, and the "send test email" button is both a demo feature and a live-email fallback. (Open decision #4, resolved.)
- **Render free realities to design around:** web service sleeps after 15 min, cold-starts under a minute, ephemeral filesystem, only inbound HTTP keeps it awake — so the webhook model fits and a polling loop would not.
- **The `status` column IS the orchestration engine** (surfaced by research): `payroll_runs.status` is simultaneously workflow position, durable checkpoint, the HITL gate, and the crash-recovery anchor — this is what cleanly replaces LangGraph. There are **two pause states** (still one *human* gate): `awaiting_reply` (machine pause on the client, resumes at stage 2) and `awaiting_approval` (the single operator gate, resumes at stage 8).
- **The DRY seam (load-bearing):** the four judgment stages are pure importable functions (data in, data out — never `extract(run_id)`); the hard gates live **inside `decide.py`** computing a code-owned `final_action`; the eval imports and scores those exact same functions. This is what makes the eval credible and tests the core thesis. Established early, not refactored to later.
- **Architecture additions** (surfaced by research, both adopted): an explicit `app/pipeline/orchestrator.py` state-machine driver, and a stuck-run/error recovery path (dashboard-visible `error` state + idempotent re-trigger) since an in-process `BackgroundTask` on a sleeping dyno can strand a run mid-stage.

## Constraints

- **Tech stack**: FastAPI in Docker on a Render free web service; Supabase Postgres for all state — chosen to run end-to-end on a free tier and demo cleanly.
- **Models**: Kimi and DeepSeek via OpenAI-compatible clients, non-reasoning chat variants — latency, and the task isn't multi-step reasoning. Model IDs are **config-driven** (env vars + `.env.example` placeholders); real strings pasted from the consoles later. (Open decision #5, resolved.)
- **Email**: a gateway catches inbound mail and posts to the app and sends outbound; threading is anchored on the RFC `Message-ID` header. Written gateway-agnostic behind one small interface.
- **Orchestration**: plain Python workflow, fixed path, state in Postgres — deliberately not an autonomous agent and not LangGraph.
- **Human-in-the-loop**: exactly one gate (operator approves computed payroll before send). Everything before it is automated.
- **Structured LLM calls**: JSON mode + Pydantic schema, one retry on parse failure.
- **Confidence threshold**: name-reconciliation auto-clarify starts at **0.8**, tuned against the eval. (Open decision #6, resolved.)
- **Audience**: hiring-manager / recruiter facing — bias effort toward a rock-solid end-to-end happy-path-plus-name-mismatch flow and a real, legible eval chart over eval exotica.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Operator approval is the only human gate (no client confirm) | Keeps the single-gate narrative clean; one pause/resume state instead of two | — Pending |
| Skip state withholding (federal + FICA only, disclaimed) | Per-state withholding is complex and not core to an educational demo | — Pending |
| Generate paystub PDFs on demand, no storage bucket | Fits Render's ephemeral filesystem; no state to persist | — Pending |
| Gateway-agnostic + fixture-first build sequencing | Decouples the one risky external dependency (inbound email) from everything that proves the system works; "send test email" doubles as demo + fallback | — Pending |
| Config-driven model routing with placeholder IDs | Builder pastes real Kimi/DeepSeek strings from consoles; keeps tiers swappable | — Pending |
| Real IRS Pub 15-T percentage method for federal withholding | Most credible paystub; highest bug risk, so it's an isolated well-tested unit guarded by the reconciliation check | — Pending |
| Name-reconciliation auto-clarify threshold starts at 0.8 | Conservative default; below it, code forces clarify/block; tuned against the eval | — Pending |
| Eval = all 4 metrics over ~15–25 fixtures, one summary chart | Covers the full "judgment" narrative for a recruiter audience while staying achievable; the chart is the proof, not the demo | — Pending |
| Plain Python workflow over LangGraph/agent loop | Path is fixed and controlled; Postgres is the checkpoint for the HITL pause | — Pending |
| Tax basis: 2026 Pub 15-T standard percentage method, disclaim OBBBA | Current-year credibility ($184,500 wage base, 2026 brackets) without OBBBA complexity; engine + eval ground truth share one assumption | — Pending |
| Add explicit `orchestrator.py` + stuck-run/error recovery | Keeps transition logic auditable in one place; a sleeping dyno can strand a run, so recovery is a first-class state, not an afterthought | — Pending |
| Hard gates live inside `decide.py` (not the orchestrator), computing `final_action` | The one placement that lets the eval test the same gated path as production — makes the eval credible and the thesis verifiable | — Pending |
| Operator gate shows the raw cleaned inbound email as the leftmost column (not just extracted vs computed) | Comparing computed paystubs against the LLM's own extraction agrees by construction; the human must verify the LLM's *reading* against what the client actually sent, or extraction errors pass the gate invisibly | — Pending |
| v1 eval uses hand-curated fixtures + a throwaway bootstrap drafting helper (full synthetic generator → v2) | At ~20 fixtures, hand-curation is faster, more realistic, and kills the train/test-leakage critique; the "scales to thousands" generator story isn't realized at demo scale | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-21 after Phase 1 (Thin Foundation) complete — contract substrate, schema, and seed data validated by tests. Initialization + research + dual cross-AI scope review (Codex + the build-plan-author Claude); scope locked at 51 v1 requirements.*
