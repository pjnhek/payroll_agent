# Payroll Agent

## What This Is

An email-driven system that automates the weekly payroll intake the builder used to do by hand as a tax analyst. A client business emails its employees' hours; an LLM-driven pipeline reads the email, reconciles the submitted names against the business's roster, decides whether it can process the run or must ask the client a clarifying question, computes the payroll (gross, FICA, real IRS Pub 15-T federal withholding), and routes the result to a single human operator for one approval before the confirmation goes back to the client. Built end-to-end on a free stack so it runs and demos cleanly.

The narrative for the writeup: the manual payroll process from the builder's accounting days, rebuilt as an agentic pipeline — the LLM does the reading and an optional clarification *suggestion*; the name-match and process-vs-clarify decisions are resolved deterministically by code; a human approves only the final payroll before it reaches the client. **Primary audience: hiring managers / recruiters.** Optimize for *visibly works end to end* > *clean 60–90s demo* > *a real, legible eval chart*.

## Core Value

A messy real-world payroll email goes in; a correct, human-approved payroll comes out — and every money-moving judgment call (name match, process-vs-clarify) is **deterministic, auditable decisioning that never guesses, with a human-confirmation learning loop.** Each submitted name resolves against the roster in pure code (exact / stored-alias / none), collisions always clarify, and the LLM never decides — it only reads (extraction) and suggests a likely employee for the clarification email. The learning loop reads stored aliases now; it writes a newly-confirmed alias at the operator-approval gate (Phase 5). If that deterministic decision flow works, everything else is plumbing.

## Requirements

### Validated

- **Phase 1 (Thin Foundation), 2026-06-21:** The shared contract substrate exists and is proven by tests — the Postgres schema (6 tables, 11-value `payroll_runs.status` enum, `email_messages.message_id` idempotency UNIQUE), the shared `app/models/` Pydantic v2 contracts imported by both pipeline and eval, and seed data covering 3 businesses / 6 employees across every calc path and name-match case (happy-path + name-mismatch). FOUND-01, FOUND-02, FOUND-03, FOUND-05, FOUND-06. (Live-DB round-trip tests are written and skip-guarded pending Supabase credentials.)

- **Phase 4 (The Eval, the proof), 2026-06-22:** A reproducible offline eval imports and scores the *same* production judgment functions (`reconcile_names → validate → decide → _compute_line_items`) over 15 committed hand-curated fixtures spanning the full name-resolution taxonomy (exact / stored-alias / first-time-alias / typo / collision / unknown) plus field cases (missing/vague hours, buried reply). `eval/run_eval.py` scores the code-owned `final_action` (never the model's raw action), producing the three core metrics (extraction F1, per-NAME reconciliation accuracy, two-level decision accuracy) per category with a confusion matrix; headline `false_process_count=0`. Renders one committed per-category SVG chart (`eval/chart.svg`), guarded by a DB-free `--check` regression gate and the project's first CI workflow (`eval.yml`: hermetic push check + gated live re-record). Optional secondary LLM-as-judge (`eval/judge.py`) and `eval_results` write stub (`--db`) wired but local-only. Verified 4/4; code review found 8 issues, all fixed (commit 744a203). EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05.

### Active

<!-- All hypotheses until shipped and validated. Grouped by capability. -->

**Ingest & threading**
- [ ] Inbound email is parsed and posted to a FastAPI webhook; row stored in `email_messages` with `Message-ID`, `In-Reply-To`, `References`
- [ ] Sender address is matched to `businesses.contact_email`; unknown sender is logged and stopped (never guessed)
- [ ] A clarification reply is routed back to its run via the RFC `In-Reply-To`/`References` header anchor and resumes the pipeline
- [ ] Email gateway sits behind one interface; whole pipeline is developable by POSTing JSON fixtures (provider wired last)

**Extraction & reconciliation (the judgment layer)**
- [ ] LLM extracts structured per-employee entries (name as written, regular/OT/vacation/sick/holiday hours, any 401k change) via JSON mode + Pydantic, retry once on parse failure
- [ ] Deterministic name resolver is the WHOLE matcher — pure code resolves each name as exact / stored-alias / none, with no model call and no confidence score
- [ ] An optional clarification-SUGGESTION call (cheap tier) maps an unresolved name to the likely roster employee for the email copy only — it never feeds the decision
- [ ] Deterministic field validation produces a per-field issues list (presence, sanity bounds, numeric)
- [ ] Deterministic decision: `decide.py` computes `final_action` purely from the resolution facts — unresolved name, run-level collision, or missing required field → `request_clarification`; no model action, no confidence number

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

**Eval (the proof)** — _validated in Phase 4 (2026-06-22)_
- [x] Bootstrap drafting helper (`draft_candidate_emails.py`) prompts a model for messy candidate emails — named honestly as a throwaway aid; the committed fixtures are the source of truth (no train/test leakage)
- [x] 15 email+label fixtures committed to the repo for reproducibility, spanning the full taxonomy (exact/stored-alias/first-time-alias/typo/collision/unknown + missing/vague hours + buried reply)
- [x] Scoring over fixtures: extraction F1/field accuracy, per-category name-reconciliation accuracy, two-level decision accuracy, + optional local LLM-as-judge email quality (`eval/judge.py`)
- [x] Results render as one committed per-category SVG chart (`eval/chart.svg`); `eval_results` write wired as a local-only `--db` stub. _Dashboard rendering of the chart lands in Phase 5._
- [x] Eval runs locally (authoritative) and in GitHub Actions on each push (hermetic `--check`, no live LLM)

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
- **Decisioning model (the heart of the design), as shipped in Phase 2.1 — deterministic, no confidence anywhere:**
  1. *Deterministic resolution* (code, no model): each submitted name resolves against the roster as **exact** (unique normalized full_name), **stored-alias** (unique `known_aliases` hit — the READ side of the learning loop), or **none** (no match, typo, first-time nickname, garbled, or ambiguous). Required-field presence, sanity bounds, and arithmetic are likewise pure code. The resolver never guesses.
  2. *LLM judgment* (only where language understanding helps, and only as advisory copy): the **clarification-suggestion** call maps an unresolved name to the likely intended employee so the email is specific ("did you mean David Reyes?"). It is wired strictly AFTER the gate and never feeds the decision (D-21-05). Extraction is the other LLM judgment role.
  3. *The pure decide* (code): `decide.py` computes `final_action` purely from the resolution facts — `request_clarification` on any unresolved name, any run-level collision, or any missing required field. There is no model action to override and no score is read anywhere; the decision is deterministic and auditable.
- **Pipeline stages (9):** ingest/route → extract → name resolve (deterministic) → field validate → decide (pure code) → clarify-path (with the suggestion call) or process-path → operator approval → send → reconciliation check.
- **Model tiering (two tiers — the decision is pure code, so no decision/mid tier):** extraction = DeepSeek (stronger); drafting + the clarification suggestion = Kimi (cheap). One OpenAI-compatible client, base URL/model/key swapped per task.
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
- **Deterministic decisioning**: `decide.py` is pure code over resolution facts (exact / stored-alias / none + run-level collisions + missing fields → `final_action`) — no LLM call, no confidence number. (Phase 2.1 superseded the original 0.8-confidence-gate decision; the LLM is kept for extraction + the clarification suggestion only.)
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
| Deterministic decisioning — resolve each name in pure code (exact / stored-alias / none), collisions always clarify, no confidence number (Phase 2.1, supersedes the original 0.8 threshold) | The "model says process, code blocks at 0.8" hero was not a real state for a well-calibrated model (an uncertain model self-clarifies); a pure resolver is auditable, reproducible, and genuinely never guesses on a money-moving decision | Decided (Phase 2.1) |
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
*Last updated: 2026-06-22 after Phase 4 (The Eval, the proof) complete — a reproducible offline eval scores the same production judgment functions over 15 committed fixtures, headline `false_process_count=0`, rendered as one per-category SVG chart with a DB-free `--check` CI gate. Verified 4/4; 8 code-review findings fixed. Prior: Phases 1, 2, 2.1, 3 complete (contract substrate, walking skeleton, deterministic decisioning, penny-accurate Pub 15-T calc).*
