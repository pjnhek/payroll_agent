# Feature Research

**Domain:** LLM-driven email-to-payroll automation pipeline with a single human approval gate (portfolio/demo for hiring managers)
**Researched:** 2026-06-20
**Confidence:** HIGH

> **Framing note.** This is a *portfolio artifact*, not a commercial payroll product. "Users" here are **hiring managers / recruiters / technical reviewers**, not payroll clerks. So "table stakes" means *what makes this read as a credible agentic system in a 60–90s look*, not *what a real payroll SaaS needs*. The recruiter-facing priority order — **(1) visibly works end-to-end → (2) clean 60–90s demo → (3) a real, legible eval chart** — drives every categorization below. Research on what gets ML/AI projects hired confirms the lens: reviewers spend <2 minutes, scan for a deployment link they can try, quantified metrics tied to impact, clean runnable code, and visible safety/interpretability mechanisms ([Let's Data Science](https://letsdatascience.com/blog/the-ml-portfolio-that-actually-gets-you-hired-in-2026), [Interview Kickstart](https://interviewkickstart.com/blogs/articles/machine-learning-engineer-portfolio)).

---

## Feature Landscape

### Table Stakes (Reviewers Expect These — absence makes the demo not credible)

These are the features without which the system either doesn't visibly run end-to-end or doesn't read as a *real* agentic pipeline. Reviewers give no credit for having them but disqualify the project for missing them.

| Feature | Why Expected (for credibility) | Complexity | Notes |
|---------|--------------------------------|------------|-------|
| **Stage 1 — Ingest & route (sender → business match)** | The entry point must look real: a message resolves to a known business or is rejected, never guessed. "Never guess the sender" is the first signal of a disciplined system. | LOW | Deterministic email→`businesses.contact_email` match. Unknown sender logged and stopped. Cheap, but its *absence* makes the front door look naive. |
| **Stage 2 — LLM extraction (messy email → structured per-employee JSON)** | This is the "LLM does the reading" half of the narrative. Without structured extraction from messy prose, there's no agent — just a form. | MEDIUM | JSON mode + Pydantic, retry once on parse failure. The stronger model. The reliability story (retry, schema validation) is itself a credibility signal. |
| **Stage 4 — Deterministic field validation** | Shows the system *checks its inputs* before computing. A pipeline that computes on unvalidated data reads as a toy. | LOW | Presence, sanity bounds (no negative hours, weekly ceiling), numeric. Pure code. Feeds the decision and the gates. |
| **Stage 6b/Payroll calc — gross, FICA, real IRS Pub 15-T federal withholding** | A payroll demo that fakes the math is not a payroll demo. The *real* Pub 15-T percentage method is what makes a paystub believable to anyone who's seen one. | HIGH | Highest bug risk → must be an isolated, well-unit-tested module guarded by the Stage 9 reconciliation check. FLSA 1.5× OT over 40h, salary ÷ pay periods, SS wage-base cap, Medicare 1.45%. |
| **Stage 7 — Single operator approval gate (side-by-side submitted vs computed)** | The narrative's spine: "a human approves only the final payroll." Reviewers scan for *where the human is* in an agentic system. This is the answer. | MEDIUM | Must gate **before** the side effect (send), not after — the cardinal HITL rule ([Towards Data Science](https://towardsdatascience.com/building-human-in-the-loop-agentic-workflows/)). The diff must be obvious at a glance; "draft-and-approve is fast only if the UI makes diffs obvious" ([same](https://towardsdatascience.com/building-human-in-the-loop-agentic-workflows/)). |
| **Stage 8 — Send confirmation to client (after approval only)** | Closes the loop. Without an actual outbound result, "end-to-end" is a claim, not a demo. | LOW–MEDIUM | Confirmation email + on-demand paystub PDF. Auto-send is *blocked* until approval — the gate has teeth. |
| **Runs list + status badges** | The reviewer's map of the system. Status transitions (`received → extracting → awaiting_approval → sent → reconciled`) make the pipeline *visible* and tell the agentic story without words. | LOW | The status enum is a free storytelling device; design it to read like a pipeline. |
| **"Send test email" demo button** | The single most important *demo* feature. Lets the whole flow fire on camera (and on a recruiter's screen) without leaving the page or touching email infra. Recruiters want a link they can try in <2 min ([Let's Data Science](https://letsdatascience.com/blog/the-ml-portfolio-that-actually-gets-you-hired-in-2026)). | LOW | Doubles as the live-email fallback if the gateway flakes. Directly serves priority #2. |
| **Deployed, reachable instance (Render free) + README with disclaimer** | "Deployed link they can try" is the #1 thing reviewers scan for; a Jupyter-notebook-only project loses. README must state plainly this is educational, not tax-compliant — honesty *is* a credibility signal to a technical reviewer. | MEDIUM | Cold-start <1 min is acceptable for a demo; design around the 15-min sleep (webhook, not polling). |
| **Stage 9 — Reconciliation check (net + taxes + deductions ties out)** | Borderline table-stakes for *this* project specifically: it's the safety net that makes the risky Pub 15-T math trustworthy, and it's a cheap, impressive "the system checks its own work" beat. | LOW | Pure arithmetic assertion. Flag drift. Small effort, outsized credibility. |

### Differentiators (What Makes a Technical Reviewer Lean In)

These are where the project *competes* against every other "I built an LLM wrapper" portfolio piece. They map directly to PROJECT.md's Core Value. Do not spread effort thin — these three are the headline.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **★ Name reconciliation: typo vs nickname vs different-person, with confidence + reason** (Stage 3) | **The headline.** It's a real, legible NLP judgment problem with a *correct* deterministic-first architecture. A reviewer immediately sees: cheap exact/alias matches never hit a model; only genuine ambiguity does; and every model call returns a *score and a human-readable reason*. This is the single feature most likely to make a technical reviewer lean in. | MEDIUM | See "What 'good' looks like" below. The deterministic-first split is itself the impressive part — it shows you know *when not to call a model*. Industry entity-resolution practice independently arrives at exactly this layered, confidence-scored design ([Salesforce Engineering](https://engineering.salesforce.com/ai-based-identity-resolution-the-key-for-linking-diverse-customer-data/), [Babel Street](https://www.babelstreet.com/blog/fuzzy-name-matching-techniques)). |
| **★ Gated process-vs-clarify decisioning (LLM proposes, code disposes)** (Stage 5) | The trust mechanism. The LLM *proposes* `process`/`request_clarification`; **code hard-gates** it — a missing required field or any name below 0.8 confidence blocks the run *even if the model said "process."* This is the difference between "I trust the LLM" (gimmick) and "I bound the LLM" (engineering). Reviewers reward visible safety/interpretability mechanisms ([Let's Data Science](https://letsdatascience.com/blog/the-ml-portfolio-that-actually-gets-you-hired-in-2026)). | MEDIUM | See "trustworthy vs gimmicky" below. The decision object (action + issues + confidence + reasons) stored on the run is the audit trail *and* the eval input. |
| **★ The eval chart (4 metrics over committed fixtures, one clean summary)** | **The proof, not the demo** (PROJECT.md's own words). Quantified accuracy tied to the judgment claims is exactly what gets ML projects shortlisted ([Interview Kickstart](https://interviewkickstart.com/blogs/articles/machine-learning-engineer-portfolio)). Four metrics — extraction accuracy, name-reconciliation accuracy, decision accuracy, LLM-as-judge email quality — over committed, reproducible fixtures, rendered as one legible chart. | MEDIUM–HIGH | See "credible eval presentation" below. Depends on extraction + decision code being *reusable* outside the request path. |
| **Clarification round-trip on the email thread (auto-send, client replies, run resumes)** | Differentiator, not table stakes (see analysis below). When it works on camera — system asks a real question, a reply on the thread resumes the exact run via RFC headers — it demonstrates *stateful, resumable* agentic flow, which is rare in portfolio pieces. | HIGH | Highest-risk feature relative to demo payoff. RFC `In-Reply-To`/`References` anchoring + Postgres pause/resume. The *capability* is the differentiator; the *live email plumbing* is the risk. Mitigate by proving it via fixtures + the test button, wiring the real gateway last. |
| **Deterministic fast-path / model-tiering discipline** | Cross-cutting but worth naming: exact/alias matches and all arithmetic never touch a model; model tiers (strong extraction → mid decision → cheap drafting) are config-driven. Reads as cost/latency awareness, which reviewers explicitly look for ([Medium — ML portfolio](https://medium.com/@santosh.rout.cr7/ml-engineer-portfolio-projects-that-will-get-you-hired-in-2025-d1f2e20d6c79)). | LOW | Mostly a *consequence* of the architecture, not a separate build. Surface it in the README and architecture diagram so it's legible. |

### Anti-Features (Tempting but Wrong for This Demo)

Already correctly scoped out in PROJECT.md (all confirmed below), plus newly identified traps.

| Feature | Why Requested (surface appeal) | Why Problematic (for this demo) | Alternative |
|---------|-------------------------------|---------------------------------|-------------|
| **Client-confirm step (second human gate)** ✅ *already deferred* | "Real payroll double-confirms." | Adds a *second* pause/resume state and muddies the clean "single human gate" narrative — the narrative *is* the asset. | Keep exactly one gate (operator). Correctly deferred. |
| **State withholding** ✅ *already deferred* | Looks "more complete." | Per-state rules are genuinely complex, error-prone, and *not core to the judgment story*. High effort, near-zero demo payoff. | Federal + FICA only, with a plain disclaimer. `state_withholding` column stays nullable. Correctly deferred. |
| **Cached/persisted PDFs + Storage bucket** ✅ *already deferred* | "Don't regenerate every time." | Adds stateful file infra that fights Render's ephemeral filesystem; no demo value. | Generate on demand from run data. Correctly deferred. |
| **LangGraph / autonomous agent loop** ✅ *already deferred* | "Agents should be agentic / it's the trendy framework." | The path is *fixed and controlled*. A graph framework adds a dependency and obscures the point that **code controls the LLM**, which is the differentiator. Plain Python + Postgres-as-checkpoint is *more* impressive here because it's deliberate. | Plain Python workflow, Postgres for the HITL pause. Correctly deferred. (Note: LangGraph is the *de facto* HITL framework per [Permit.io](https://www.permit.io/blog/human-in-the-loop-for-ai-agents-best-practices-frameworks-use-cases-and-demo) — deliberately *not* using it, and being able to say why, is the stronger signal.) |
| **Reasoning models** ✅ *already deferred* | "Smarter = better." | Over-thinking adds latency; this is not multi-step logic. Slower demo, no accuracy gain on these short structured calls. | Non-reasoning chat variants. Correctly deferred. |
| **Dashboard auth** ✅ *already deferred* | "Production needs login." | A login wall is friction between a recruiter and the working demo — actively *harms* priority #2. | No auth. It's a demo. Correctly deferred. |
| **Spreadsheet-attachment parsing** ✅ *already deferred* | "Real clients send spreadsheets." | Opens a whole parsing/format surface (xlsx/csv/merged-cells) for marginal narrative gain; the messy-*email* case is already the interesting one. | Email-body extraction only for v1. Correctly deferred. Keep one fixture category as a *labeled-but-unimplemented* stretch note. |
| **⚠ NEW: Login/multi-tenant business onboarding UI** | "Let me add new businesses from the UI." | Seed businesses/employees via SQL. A CRUD admin UI is pure plumbing that steals time from the three differentiators and lengthens the demo. | Seed 1–2 businesses + ~5 employees with aliases via `schema.sql`/seed script. |
| **⚠ NEW: Real-time / streaming token UI on the dashboard** | "Show the LLM thinking live." | Streaming UX is fiddly, adds latency-perception risk on cold starts, and distracts from the *decision object* (which is the real artifact). | Show the finished structured decision (action + issues + confidence + reasons). Static and legible beats live and jittery. |
| **⚠ NEW: Multi-provider / model A-B switching in the UI** | "Show off the config-driven routing." | Config-driven routing belongs in `.env` + README, not a UI toggle. A model picker is a feature nobody asked for and another surface to break on camera. | Document the tiering in the README/architecture diagram. Routing is invisible plumbing done right. |
| **⚠ NEW: Eval exotica (positional-swap bias harness, multi-judge ensembles, confidence calibration curves)** | "Rigorous LLM-as-judge needs bias controls" — true in research ([DeepEval](https://deepeval.com/blog/llm-as-a-judge), [Label Studio](https://labelstud.io/blog/who-watches-the-watchdogs-evaluating-llm-as-a-judge/)). | For a recruiter audience, *one legible chart over committed fixtures* beats a methodologically ornate harness they won't read. PROJECT.md explicitly says "over eval exotica." | Four clear metrics, committed fixtures, one chart. *Mention* the known LLM-judge biases in the README to show awareness — don't build the harness. |
| **⚠ NEW: Retry/queue/observability infra (Celery, Redis, OpenTelemetry, dead-letter queues)** | "Production resilience." | Massive plumbing for a single-flow demo on a free tier. The pipeline is synchronous-enough; Postgres status *is* the state machine. | Postgres status enum + one retry on parse failure. Nothing more. |
| **⚠ NEW: Per-employee tax YTD / pay-history tracking** | "Real payroll is cumulative (wage-base caps need YTD)." | Tempting because the SS wage-base cap *technically* needs YTD earnings. But tracking history adds a whole temporal data model for a single-run demo. | Compute the cap against the *current run's* annualized figure with a disclaimer; note YTD as out-of-scope. Don't build a ledger. |

---

## Feature Dependencies

```
Stage 1 (Ingest/route)
    └──requires──> businesses table seeded

Stage 2 (LLM extraction)  ──structured JSON──>  Stage 3, 4, 5, 6b
    └──requires──> Pydantic schemas + JSON-mode LLM client

Stage 3 (Name reconciliation) ★
    └──requires──> Stage 2 output (submitted names)
    └──requires──> employees.known_aliases (deterministic matcher)
    └──feeds confidence into──> Stage 5 GATE (0.8 threshold)

Stage 4 (Field validation)
    └──requires──> Stage 2 output
    └──feeds issues into──> Stage 5 GATE (missing-required block)

Stage 5 (Gated decision) ★
    └──requires──> Stage 3 confidences + Stage 4 issues
    └──code gate OVERRIDES──> LLM action
    └──branches──> 6a (clarify)  OR  6b (process)

Stage 6a (Clarify path)
    └──requires──> LLM drafting + email gateway (outbound)
    └──requires──> RFC Message-ID stored on run
    └──resume requires──> threading anchor (In-Reply-To/References) ──re-enters──> Stage 2

Stage 6b (Process path)
    └──requires──> Stage 5 = process
    └──invokes──> Payroll calc (gross/FICA/Pub15-T) ──> Stage 9 reconciliation

Stage 7 (Operator approval)
    └──requires──> Stage 6b computed paystubs + decision object
    └──requires──> Dashboard run-detail (side-by-side)
    └──gates BEFORE──> Stage 8 (side effect)

Stage 8 (Send) ──requires──> approval + PDF generation + email gateway

EVAL CHART ★
    └──requires──> Stage 2 + Stage 3 + Stage 5 code be REUSABLE off the request path
    └──requires──> committed fixtures (generator output)
    └──LLM-as-judge metric requires──> Stage 6a drafting code reusable

"Send test email" button ──fires──> entire pipeline (demo + fallback for 6a plumbing)
```

### Dependency Notes

- **Eval depends on extraction/reconciliation/decision being callable as pure functions.** This is the single most important architectural consequence: Stages 2, 3, 5 (and 6a drafting) must be importable and runnable on a fixture *without* an HTTP request, DB write, or email send. Build the pipeline functions first as pure, then wire the webhook/DB around them — otherwise the eval harness (differentiator #3) becomes a rewrite. **Flag for roadmap: sequence pipeline-as-library before pipeline-as-endpoint.**
- **Clarification round-trip depends on threading, which depends on the real (or simulated) gateway.** The *resume* logic (header lookup → run) can and should be proven against POSTed JSON fixtures long before the real provider is wired. Decouple "resume-on-reply logic" (build early, test via fixtures) from "real inbound email provider" (wire last). The test-email button is the bridge.
- **Stage 5 gate depends on Stage 3 confidence and Stage 4 issues existing in a stable shape.** Lock the decision-object schema (action, issues[], per-name confidence, reasons) early — it's consumed by the gate, the dashboard, *and* the eval. A schema change late ripples into all three.
- **Payroll calc (Pub 15-T) is independent of all LLM stages** — it's pure code keyed off resolved employees + validated hours. It can be built and unit-tested in complete isolation, and *should* be, because it's the highest bug-risk module. Stage 9 reconciliation is its guardrail.
- **Dashboard run-detail (side-by-side) gates the operator-approval feature.** No detail view → no approval gate → no narrative spine. The list view is independent and cheaper.

---

## Deep-Dive: The Four Questions That Decide Credibility

### 1. Name reconciliation — what "good" looks like to a technical reviewer

The *architecture* is the impressive part, more than the model's raw accuracy:

- **Deterministic-first is non-negotiable and visible.** Exact / case / whitespace / known-alias matches resolve in code and **never call a model**. Only genuine ambiguity escalates. A reviewer who sees "you don't burn a model call on `'Bob' → 'Bob Smith'`" reads competence. This mirrors how production entity-resolution systems are actually built — layered, with the model reserved for the hard residual ([Salesforce Engineering](https://engineering.salesforce.com/ai-based-identity-resolution-the-key-for-linking-diverse-customer-data/), [Babel Street](https://www.babelstreet.com/blog/fuzzy-name-matching-techniques)).
- **The three-way classification is the right framing.** *Typo* (→ correct to roster, high confidence), *nickname* (→ map via reasoning, medium-high), *genuinely different person / not on roster* (→ low/zero confidence → block). Reviewers recognize that "not on the roster" is a *correct* answer, not a failure — the eval must reward correctly calling unknown.
- **Confidence + a one-line reason per ambiguous name is what makes it impressive.** "Matched `Jon` → `John Davis` (confidence 0.92): common short form, single John on roster." The *reason* is the interpretability beat reviewers reward ([Let's Data Science](https://letsdatascience.com/blog/the-ml-portfolio-that-actually-gets-you-hired-in-2026)). A bare score is forgettable; a score *with a defensible reason* reads as a real judgment.
- **The 0.8 threshold is honest, not arbitrary — say so.** State that it's a conservative default tuned against the eval, and that below it code *forces* clarify/block regardless of the model's stated action. "We picked a threshold and validated it against labeled data" is a credibility multiplier.
- **"Good" numeric target:** high accuracy on clean/typo/nickname AND correct unknown-detection, surfaced as the name-reconciliation metric in the chart. The failure mode to avoid: a confident wrong match slipping past the gate — which is exactly what the 0.8 hard gate exists to prevent.

### 2. Process-vs-clarify decisioning — trustworthy vs gimmicky

The dividing line is **whether code can override the model, visibly.**

- **Gimmicky:** "The LLM decides whether to process." Reviewer reaction: *what stops a hallucinated 'process' on garbage input?*
- **Trustworthy:** "The LLM *proposes*; code *disposes*." A missing required field or any name < 0.8 **blocks the run even when the model said `process`.** This is the whole ballgame. It demonstrates the engineer understands LLMs are *proposers under constraints*, not *deciders*. Best-practice HITL guidance frames exactly this: the gate must sit *before the side effect*, and rule-enforcement must be in code, not prompt ([Towards Data Science](https://towardsdatascience.com/building-human-in-the-loop-agentic-workflows/), [DeepEval](https://deepeval.com/blog/llm-as-a-judge)).
- **Make the override observable.** When the gate overrides the model, store and show *both*: "model said process; gate forced clarify (reason: `Maria` unresolved at 0.71 < 0.8)." A reviewer seeing the gate *catch* the model on camera is the strongest possible trust signal. Consider seeding one demo fixture specifically to trigger this.
- **The decision object is an audit artifact, not just control flow.** Persisting `{action, issues[], confidences, reasons}` on the run — visible on the dashboard and fed to the eval — is what separates "auditable system" from "vibes."

### 3. Email threading + clarification round-trip — table stakes or differentiator?

**Differentiator, not table stakes — and the riskiest feature relative to payoff.**

- **Why differentiator:** A stateful, resumable agent loop (ask → pause → client replies on the thread → *the same run* resumes via RFC headers) is genuinely uncommon in portfolio projects and demonstrates real systems thinking. When it works on camera it's a memorable beat.
- **Why NOT table stakes:** The end-to-end story is *already* credible with extraction → reconciliation → gated decision → calc → approval → send. The clarification loop is the *cherry*, and live inbound email is the single most fragile external dependency in the whole system (provider parsing quirks, header munging, spam routing).
- **Recommendation tying to priority order:** Build and *prove* the resume logic against fixtures and the test-email button (priority #1, robust). Treat the *real inbound provider* as the last, riskiest wire-up; if it's flaky on demo day, the test button still shows the full loop. Never let live email be on the critical path for "visibly works." **This directly protects priority #1.**

### 4. Operator-approval HITL + side-by-side dashboard — what makes it convincing

- **The diff must be obvious at a glance.** "Draft-and-approve is fast only if the UI makes diffs obvious" ([Towards Data Science](https://towardsdatascience.com/building-human-in-the-loop-agentic-workflows/)). Submitted hours/names on the left, computed gross/taxes/net on the right, with the decision object and its reasons in between. A reviewer should understand the operator's job in 3 seconds.
- **The gate must have teeth.** The confirmation email *cannot* send before approval — approval-before-side-effect is the cardinal rule ([MachineLearningMastery](https://machinelearningmastery.com/building-a-human-in-the-loop-approval-gate-for-autonomous-agents/), [Towards Data Science](https://towardsdatascience.com/building-human-in-the-loop-agentic-workflows/)). Show the run sitting in `awaiting_approval` and *only* transitioning to `sent` on click. That visible pause/resume *is* the HITL demo.
- **One gate, clearly the highest-stakes step.** The narrative — "the human approves only the final payroll, the highest-stakes moment" — lands precisely *because* everything before it is automated. Resist adding review checkpoints elsewhere.

### 5. Eval-as-a-feature — credible presentation for a recruiter audience

- **One chart, four metrics, committed fixtures.** Extraction field accuracy, name-reconciliation accuracy, decision accuracy, LLM-as-judge email quality — rendered as a single legible summary on the dashboard. Quantified accuracy tied to the judgment claims is exactly the signal that shortlists ML projects ([Interview Kickstart](https://interviewkickstart.com/blogs/articles/machine-learning-engineer-portfolio), [Let's Data Science](https://letsdatascience.com/blog/the-ml-portfolio-that-actually-gets-you-hired-in-2026)).
- **Reproducibility is the credibility lever.** Fixtures committed to the repo + eval runnable locally *and* in GitHub Actions on push = "anyone can verify these numbers." That's worth more than a higher number nobody can reproduce.
- **Show awareness of LLM-as-judge limitations without building the harness.** A well-prompted judge agrees with humans ~85% of the time (slightly above human–human agreement ~81%) but carries positional, verbosity, and self-enhancement biases ([DeepEval](https://deepeval.com/blog/llm-as-a-judge), [Label Studio](https://labelstud.io/blog/who-watches-the-watchdogs-evaluating-llm-as-a-judge/)). One README sentence acknowledging this — and noting the judge uses a fixed rubric and explains its verdicts — signals maturity. **Do not** build bias-control machinery (anti-feature above).
- **Seed fixtures on purpose, by category.** Clean / typo / missing-hours / unknown-employee / nickname / vague-hours / buried-reply. Per-category breakdown in or beside the chart tells the judgment story far better than one aggregate bar. The category coverage *is* the argument that the system is robust.
- **The chart is the proof, not the demo** (PROJECT.md). Keep the demo (priority #2) and the eval (priority #3) as distinct beats: the demo shows it *works*; the chart shows it works *measurably*.

---

## MVP Definition

### Launch With (v1 — the spine that must visibly work end-to-end)

- [ ] **Pipeline as pure, importable functions** (Stages 2–5 + drafting) — *prerequisite for the eval*; build before the webhook
- [ ] **Stage 1 ingest/route** — sender→business, reject unknown
- [ ] **Stage 2 LLM extraction** (JSON + Pydantic, 1 retry) — the "LLM reads" beat
- [ ] **Stage 3 name reconciliation** ★ (deterministic-first + LLM-on-ambiguous, confidence + reason) — *the headline*
- [ ] **Stage 4 field validation** — feeds the gate
- [ ] **Stage 5 gated decision** ★ (LLM proposes, code disposes at 0.8) — *the trust mechanism*
- [ ] **Payroll calc** (gross, FLSA OT, FICA, **real Pub 15-T**) — isolated, unit-tested
- [ ] **Stage 9 reconciliation check** — guards the calc
- [ ] **Operator approval gate + side-by-side run-detail** — the narrative spine, side-effect-gated
- [ ] **Stage 8 send** (confirmation + on-demand PDF)
- [ ] **Runs list + status badges**
- [ ] **"Send test email" demo button** — the on-camera trigger; serves priority #2
- [ ] **Deployed Render instance + README with disclaimer + architecture diagram**

### Add After Validation (v1.x — proof and the resumable loop)

- [ ] **Clarification round-trip on the thread** (auto-send + RFC-anchored resume) — differentiator; prove via fixtures first, real provider last
- [ ] **Eval harness: generator + ~15–25 committed fixtures + 4 metrics + dashboard chart** ★ — the proof (priority #3)
- [ ] **GitHub Actions: eval-on-push + Supabase keep-alive**
- [ ] **Cheap-model routing for email drafts** (cost/latency polish)
- [ ] **Expanded edge fixtures** (impossible hours, duplicate name, multiple ambiguous names at once)
- [ ] **60–90s demo recording**

### Future Consideration (v2+ — explicitly deferred)

- [ ] State withholding (flat-rate line) — *only if* a reviewer asks for "more complete" tax
- [ ] Spreadsheet-attachment parsing — *only if* a real client format demands it
- [ ] Cached PDFs / Storage bucket — *only if* on-demand generation proves too slow on Render
- [ ] Client-confirm second gate — *avoid*; breaks the single-gate narrative

---

## Feature Prioritization Matrix

| Feature | User (Reviewer) Value | Implementation Cost | Priority |
|---------|----------------------|---------------------|----------|
| Name reconciliation (confidence + reason) ★ | HIGH | MEDIUM | P1 |
| Gated process-vs-clarify decision ★ | HIGH | MEDIUM | P1 |
| LLM extraction (structured) | HIGH | MEDIUM | P1 |
| Operator approval + side-by-side dashboard | HIGH | MEDIUM | P1 |
| Payroll calc (real Pub 15-T) + reconciliation | HIGH | HIGH | P1 |
| "Send test email" demo button | HIGH | LOW | P1 |
| Deployed instance + README/diagram | HIGH | MEDIUM | P1 |
| Ingest/route + runs list + status badges | MEDIUM | LOW | P1 |
| Eval chart (4 metrics, committed fixtures) ★ | HIGH | MEDIUM–HIGH | P1 (proof) |
| Clarification round-trip (resume on thread) | MEDIUM–HIGH | HIGH | P2 |
| GitHub Actions (eval + keep-alive) | MEDIUM | LOW | P2 |
| Cheap-model routing for drafts | LOW | LOW | P2 |
| Expanded edge-case fixtures | MEDIUM | LOW–MEDIUM | P2 |
| State withholding | LOW | HIGH | P3 |
| Spreadsheet parsing | LOW | HIGH | P3 |

**Priority key:** P1 = must have for a credible end-to-end demo · P2 = add to sharpen and prove · P3 = future / deliberately deferred

---

## Competitor Feature Analysis

"Competitors" here = the field of LLM-agent *portfolio projects* a reviewer compares this against.

| Feature | Typical "LLM wrapper" portfolio project | Typical "agent framework demo" (LangGraph/CrewAI) | Our Approach |
|---------|------------------------------------------|---------------------------------------------------|--------------|
| LLM judgment | One prompt, trust the output | Multi-agent, hard to audit | **Deterministic-first; model only on residual ambiguity; code-gated** |
| Safety/guardrails | None, or prompt-only "please be careful" | Framework-level interrupts | **Hard code gates that override the model at a tuned threshold** |
| Human-in-the-loop | Absent, or a chat back-and-forth | Framework interrupt node | **One explicit operator gate, side-effect-gated, side-by-side diff** |
| Evaluation | None, or a vibes screenshot | Sometimes a trace viewer | **4 metrics over committed fixtures, reproducible in CI, one chart** |
| Deployability | Notebook / localhost only | Often localhost | **Live Render URL + one-click test button** |
| Honesty | Overclaims production-readiness | Overclaims autonomy | **Plain "educational, not tax-compliant" disclaimer** |

The thesis the comparison surfaces: this project competes by being *disciplined and measurable* where the field is *flashy and unverifiable*. Every differentiator (deterministic-first reconciliation, code-gated decision, reproducible eval) is a deliberate counter to the most common portfolio weaknesses.

---

## Sources

- [Towards Data Science — Building Human-in-the-Loop Agentic Workflows](https://towardsdatascience.com/building-human-in-the-loop-agentic-workflows/) (HIGH — HITL gate-before-side-effect, draft-and-approve diff UX)
- [MachineLearningMastery — Human-in-the-Loop Approval Gate for Autonomous Agents](https://machinelearningmastery.com/building-a-human-in-the-loop-approval-gate-for-autonomous-agents/) (MEDIUM — approval-before-execution pattern)
- [Permit.io — Human-in-the-Loop for AI Agents](https://www.permit.io/blog/human-in-the-loop-for-ai-agents-best-practices-frameworks-use-cases-and-demo) (MEDIUM — LangGraph as the default HITL framework; context for deliberately not using it)
- [DeepEval — LLM-as-a-Judge in 2026: techniques and best practices](https://deepeval.com/blog/llm-as-a-judge) (HIGH — rubric judges, explain verdicts, hard-rule branches, known biases)
- [Label Studio — Can You Trust LLM-as-a-Judge?](https://labelstud.io/blog/who-watches-the-watchdogs-evaluating-llm-as-a-judge/) (MEDIUM — judge–human agreement ~85% vs human–human ~81%, bias taxonomy)
- [Salesforce Engineering — AI-based Identity Resolution](https://engineering.salesforce.com/ai-based-identity-resolution-the-key-for-linking-diverse-customer-data/) (MEDIUM — layered, confidence-scored, LLM-on-residual entity resolution validates the Stage 3 design)
- [Babel Street — Fuzzy Name Matching Techniques](https://www.babelstreet.com/blog/fuzzy-name-matching-techniques) (MEDIUM — deterministic + fuzzy + confidence-threshold layering)
- [Interview Kickstart — ML Engineer Portfolio Playbook](https://interviewkickstart.com/blogs/articles/machine-learning-engineer-portfolio) (MEDIUM — quantified metrics, deployment link, end-to-end completeness as hiring signals)
- [Let's Data Science — The ML Portfolio That Actually Gets You Hired in 2026](https://letsdatascience.com/blog/the-ml-portfolio-that-actually-gets-you-hired-in-2026) (MEDIUM — <2-min review window, deployment link, interpretability/safety as signals)
- [Medium — ML Engineer Portfolio Projects (Santosh Rout)](https://medium.com/@santosh.rout.cr7/ml-engineer-portfolio-projects-that-will-get-you-hired-in-2025-d1f2e20d6c79) (LOW — cost/latency awareness as a hiring signal)

---
*Feature research for: LLM-driven email-to-payroll pipeline (portfolio/demo)*
*Researched: 2026-06-20*
