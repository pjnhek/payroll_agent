# Architecture Research

**Domain:** LLM-driven email-to-payroll pipeline with Postgres-backed state and a single human-in-the-loop gate
**Researched:** 2026-06-20
**Confidence:** HIGH (architecture is locked; this document deepens it. The three load-bearing mechanisms — FastAPI `BackgroundTasks`, OpenAI-compatible `base_url`/`response_format` routing, and Postgres-as-state-machine — are verified against current docs.)

> Scope note: The architecture is fully specified in `PROJECT.md` and `payroll-agent-build-plan.md`. This document does **not** propose an alternative. It pins down the run state machine, the fixture seam, re-entrancy invariants, the eval/production DRY seam, the component/data-flow map, the build-order dependency graph, and the Render-constraint implications — and surfaces the non-obvious decisions the build plan leaves implicit.

---

## Standard Architecture

### System Overview

```
┌───────────────────────────────────────────────────────────────────────┐
│  EDGE  (one FastAPI process, single Render free web service)            │
│                                                                         │
│   POST /webhook/inbound  ──┐         GET  /            (runs list)      │
│   POST /webhook/test-email │         GET  /runs/{id}   (run detail)     │
│                            │         POST /runs/{id}/approve            │
│                            │         POST /runs/{id}/reject             │
│                            │         GET  /eval        (eval summary)   │
└────────────┬───────────────┴──────────────────────┬────────────────────┘
             │ returns 200 immediately               │ reads + mutates
             │ schedules BackgroundTask              │ state synchronously
             ▼                                       ▼
┌───────────────────────────────────────┐  ┌──────────────────────────────┐
│  PIPELINE ORCHESTRATOR (plain Python)  │  │  DASHBOARD (server-rendered)  │
│  run_pipeline(run_id) — advances the   │  │  read-only except the 2       │
│  status state machine stage by stage   │  │  operator buttons (approve/   │
│                                        │  │  reject), which re-enter the  │
│  Stage 1 ingest/route   (det)          │  │  pipeline at the send stage.  │
│  Stage 2 extract        (LLM strong)   │  └───────────────┬──────────────┘
│  Stage 3 reconcile names(det→LLM)      │                  │
│  Stage 4 validate       (det)          │                  │
│  Stage 5 decide         (LLM mid+gate) │                  │
│  Stage 6a clarify  / 6b process        │                  │
│  Stage 7 PAUSE → awaiting_approval     │                  │
│  Stage 8 send           (det)          │                  │
│  Stage 9 reconcile $    (det)          │                  │
└───┬───────────┬──────────────┬─────────┘                  │
    │           │              │                            │
    ▼           ▼              ▼                            ▼
┌────────┐ ┌──────────┐ ┌──────────────┐         ┌──────────────────────┐
│  LLM   │ │  CALC    │ │   EMAIL      │          │      DB LAYER        │
│ client │ │ engine   │ │  gateway     │◄────────►│  (Supabase Postgres) │
│ +route │ │(pure fn) │ │ (1 interface)│  threads │  6 tables; status    │
│        │ │          │ │              │  on RFC  │  column = state mac. │
└───┬────┘ └──────────┘ └──────┬───────┘  headers └──────────┬───────────┘
    │ base_url/model/key                  │                   │
    ▼ swapped per task                    ▼ provider wired    ▼
 Kimi / DeepSeek                     LAST (n8n / inbound-  all state, incl.
 (OpenAI-compatible)                 parse svc)           HITL checkpoint
                                                          + PDF source data

   PDF generator (app/pdf): pure function, run row → bytes, on demand only.
```

**The one idea that makes the whole thing work:** there is no in-memory orchestration state and no message queue. `payroll_runs.status` IS the state machine. Every stage reads the run, does its work, and writes the next status. A pause is just a status the orchestrator stops at; a resume is just an inbound event that re-invokes the orchestrator on a run already in a paused status. This is why "plain Python + Postgres" replaces LangGraph cleanly — the durable state engine is the database, not a framework.

### Component Responsibilities

| Component | Owns | Boundary rule (what it must NOT do) |
|-----------|------|-------------------------------------|
| **Edge / FastAPI (`app/main.py`)** | HTTP surface: webhook ingress, dashboard routes, operator actions. Returns 200 fast, schedules pipeline work. | No business logic, no LLM calls, no calc. It is a thin adapter that translates HTTP ↔ pipeline calls. |
| **Pipeline orchestrator (`app/pipeline/`)** | Advancing one run through the 9 stages by reading/writing `status`. Owns transition rules and the hard gates. | Does not know about HTTP, gateways' wire formats, or model vendors. Calls stage functions + lower components. |
| **LLM client (`app/llm/client.py`)** | One OpenAI-compatible client; per-task routing (strong/mid/cheap) via swapped `base_url`/`model`/`key`; JSON mode; one retry on parse failure; Pydantic validation. | Knows nothing about payroll or pipeline stages. Vendor-agnostic call surface only. |
| **Calc engine (`app/pipeline/calculate.py`)** | Gross, FLSA OT, salary proration, 401k, FICA, IRS Pub 15-T federal withholding, net. **Pure functions** (roster + hours in → numbers out). | No DB, no I/O, no LLM. This is what makes it independently buildable and trivially testable. |
| **Email gateway (`app/email/gateway.py`)** | The ONE seam to the outside mail world: parse inbound payload → canonical dict; send outbound; return the outbound `Message-ID`. | The only file that knows the provider. Everything upstream sees the canonical interface, never provider-specific fields. |
| **DB layer (`app/db/`)** | Schema (`schema.sql`) + typed accessors for the 6 tables. The single place that mutates `status`. | No business decisions; it persists what the pipeline decides. |
| **PDF generator (`app/pdf/paystub.py`)** | Run/line-item rows → PDF bytes, generated on demand. | Stateless; writes nothing to disk (Render is ephemeral). |
| **Dashboard (`app/dashboard/`)** | Render existing state; expose the two operator buttons + the demo button. | Read-only except approve/reject, which are pipeline re-entry, not direct DB edits. |
| **Eval harness (`eval/`)** | Run the **same** extract/reconcile/validate/decide/score code over committed fixtures; write `eval_results`. | Must import production components, never reimplement them. (See the DRY seam.) |

---

## Recommended Project Structure

The structure is already specified in the build plan; the rationale below is what the roadmap needs.

```
payroll-agent/
  app/
    main.py                  # FastAPI: webhook ingress + dashboard routes (thin adapter)
    pipeline/
      orchestrator.py        # (ADD) run_pipeline(run_id): the state machine driver
      ingest.py              # stage 1  (deterministic)
      extract.py             # stage 2  (LLM strong)  — eval imports this
      reconcile_names.py     # stage 3  (det→LLM)     — eval imports this
      validate.py            # stage 4  (deterministic) — eval imports this
      decide.py              # stage 5  (LLM mid + the hard gates) — eval imports this
      calculate.py           # stage 6b (pure functions)
      reconcile_payroll.py   # stage 9  (pure functions)
      compose_email.py       # stage 6a/6b/8 drafting (LLM cheap)
    models/                  # Pydantic schemas (the shared contracts)
    llm/
      client.py              # OpenAI-compatible wrapper + per-task routing
      prompts/
    email/
      gateway.py             # inbound parse, outbound send, threading (the one seam)
    db/
      supabase.py            # typed accessors + the status mutators
      schema.sql             # 6 tables, status enum
    pdf/
      paystub.py             # on-demand bytes
    dashboard/
      templates/
  eval/
    generate_fixtures.py     # synthetic email+ground-truth generator
    fixtures/                # ~15-25 committed email+label pairs
    run_eval.py              # imports app.pipeline.* — never reimplements
    scorers.py               # field acc, name recon, decision, LLM-judge
  .github/workflows/
    keepalive.yml            # pings Supabase so the free project doesn't pause
    eval.yml                 # runs eval on push
  Dockerfile  requirements.txt  .env.example  README.md
```

### Structure Rationale (the parts the build plan leaves implicit)

- **`pipeline/orchestrator.py` is the one file the build plan never names but the design demands.** The stage modules are the *what*; the orchestrator is the *when and what-next*. It is the only code that knows the legal status transitions and where the pauses are. Keep transition logic here, not scattered across stage files, or the state machine becomes un-auditable. Put it in the roadmap explicitly.
- **`models/` (Pydantic) is the contract layer that lets eval and production share code.** Stage functions take and return Pydantic models, not raw dicts. The eval feeds fixtures through the same models; the dashboard renders the same `decision` object. One schema, three consumers.
- **`calculate.py` and `reconcile_payroll.py` are pure on purpose.** No DB import in either file. The orchestrator loads the roster + extracted data, calls them, persists the result. This is what lets the calc engine be built and unit-tested in parallel with everything else (it is the only component with zero upstream dependencies).
- **`email/gateway.py` is the only provider-aware file.** Two functions — `parse_inbound(payload) -> InboundEmail` and `send(outbound) -> message_id` — are the entire abstraction. This is the fixture seam (below).

---

## The Run State Machine (`payroll_runs.status`)

This is the spine. The `status` column is simultaneously the workflow position, the durable checkpoint, the HITL gate, and the crash-recovery anchor.

### State transition diagram

```
                  inbound webhook (new thread, known sender)
                              │
                              ▼
                       ┌────────────┐   unknown sender → log to email_messages,
   (no run created  ◄──┤  received  │   NO run created, stop. (edge case, stage 1)
    on unknown send)   └─────┬──────┘
                             │ orchestrator picks up
                             ▼
                       ┌────────────┐
                       │ extracting │  stage 2 (LLM strong). On unrecoverable
                       └─────┬──────┘  LLM/parse failure after retry → error.
                             │  (stage 3 reconcile + stage 4 validate run inline;
                             │   they don't need their own statuses — see note)
                             ▼
                       ┌────────────┐
                       │  decided?  │  stage 5: LLM proposes, CODE GATES enforce
                       └──┬──────┬──┘
            gate/LLM says │      │ gate passes AND LLM says "process"
       "request_clarify"  │      │
                          ▼      ▼
              ┌────────────────────┐   ┌──────────┐
              │ needs_clarification│   │ computed │  stage 6b: calc engine runs,
              └─────────┬──────────┘   └────┬─────┘  line items written, conf.
                        │ 6a: LLM drafts,   │        email drafted (not sent)
                        │ gateway sends,     │
                        │ outbound msg-id    ▼
                        │ stored on run ┌──────────────────┐
                        ▼               │ awaiting_approval│ ◄── THE HITL PAUSE.
              ┌────────────────┐        └───┬──────────┬───┘     Orchestrator stops.
              │ awaiting_reply │            │ approve  │ reject
              └───────┬────────┘            ▼          ▼
                      │              ┌──────────┐ ┌──────────┐
   client reply on    │              │ approved │ │ rejected │ (terminal)
   thread (In-Reply-  │              └────┬─────┘ └──────────┘
   To matches stored  │                   │ stage 8: gateway sends confirmation
   msg-id) RE-ENTERS  │                   ▼   + on-demand PDFs
   AT STAGE 2 ────────┘              ┌──────────┐
   status → extracting               │   sent   │
                                     └────┬─────┘
                                          │ stage 9: net+taxes+deductions
                                          ▼   ties to run total (or flags drift)
                                     ┌────────────┐
                                     │ reconciled │ (terminal, success)
                                     └────────────┘

   error  — terminal-ish: any stage's unrecoverable failure. Surfaced on the
            dashboard; an operator/dev can inspect and (optionally) re-trigger.
```

### Status semantics table

| Status | Set by | Meaning | Orchestrator behavior |
|--------|--------|---------|-----------------------|
| `received` | webhook (ingest) | Run row created, source email linked, business routed. | Hand off to orchestrator. |
| `extracting` | orchestrator (stage 2 entry) | Extraction → reconcile → validate → decide are running, OR a reply just re-entered here. | Active; runs to a pause or terminal. |
| `needs_clarification` | stage 5 (gate or LLM) | Decision = clarify; clarification email being drafted/sent. | Transient; advances to `awaiting_reply` once the outbound msg-id is stored. |
| `awaiting_reply` | stage 6a | Clarification sent; outbound `Message-ID` saved on run. **PAUSE #1.** | Stops. Only an inbound threaded reply resumes it. |
| `computed` | stage 6b | Line items + taxes computed, confirmation drafted (not sent). | Advances to `awaiting_approval`. |
| `awaiting_approval` | stage 6b→7 | **THE single HITL gate. PAUSE #2.** | Stops. Only an operator approve/reject resumes it. |
| `approved` | operator action | Operator approved; about to send. | Advances to stage 8. |
| `sent` | stage 8 | Confirmation + PDFs delivered. | Advances to stage 9. |
| `reconciled` | stage 9 | Arithmetic ties out (or drift flagged in `decision`/details). | Terminal success. |
| `rejected` | operator action | Operator rejected the computed payroll. | Terminal. |
| `error` | any stage | Unrecoverable failure (LLM after retry, gateway send fail, etc.). | Terminal-ish; dashboard-visible, re-triggerable. |

### The two pauses, precisely

There are **two** places the orchestrator stops, and only one is the "human gate":

1. **`awaiting_reply` (machine pause, external):** waiting on the *client*. Resumed by an inbound email whose `In-Reply-To`/`References` matches the outbound `Message-ID` stored on the run. **Resume point: stage 2 (extract).**
2. **`awaiting_approval` (the HITL gate):** waiting on the *operator*. Resumed by `POST /runs/{id}/approve` or `/reject` from the dashboard. **Resume point: stage 8 (send) on approve, terminal on reject.**

Both are implemented identically: the orchestrator function simply has no work to do for a run in a paused status, and an *external event* (webhook or button) flips the status and re-invokes the orchestrator. **There is no waiting thread, no timer, no queue** — which is exactly what survives a Render cold start.

### Non-obvious decisions this surfaces (flag for the roadmap)

- **Stages 3 and 4 do not get their own status values.** The enum jumps `extracting → needs_clarification | computed`. Reconcile-names and validate run *inline within the extracting span*. This is correct (they're fast, deterministic-first, and never pause), but it means "where did this run fail?" is answered by `decision.issues` + `error` context, not by status granularity. Decide deliberately: status = pause points + terminal states, not every stage. (The 11 enum values already encode this.)
- **`error` is not in the happy path enum list but must be a first-class recovery state.** Because pipeline work runs in a `BackgroundTask` (below), a crash mid-stage leaves a run stuck in `extracting`/`computed`. The roadmap needs a "stuck-run" story: at minimum dashboard visibility; ideally an idempotent re-trigger that re-runs from the last persisted status.
- **`received` → `extracting` is itself a re-entry seam.** A fresh run and a resumed reply both land in `extracting`. The difference is whether `extracted_data`/line items already exist (see Re-entrancy).

---

## The Fixture-First Seam

The single most strategically important boundary in the build, because it decouples the one risky external dependency (inbound email) from everything that proves the system works.

### The interchangeable payload

Define **one** canonical inbound shape (a Pydantic model in `app/models/`). The webhook accepts exactly this JSON; nothing else.

```python
class InboundEmail(BaseModel):          # the canonical interface
    message_id: str                     # RFC Message-ID of THIS email
    in_reply_to: str | None = None      # set when it's a reply
    references: str | None = None       # RFC References chain
    subject: str
    from_addr: str
    to_addr: str
    body_text: str
    # (attachments deferred — spreadsheet parsing is out of scope for v1)
```

### Where the seam sits

```
  A JSON fixture file        Real provider's webhook
  (curl POST in dev)         (n8n / inbound-parse, wired LAST)
          │                          │
          │                          │ provider-specific JSON
          ▼                          ▼
   POST /webhook/inbound      app/email/gateway.parse_inbound(raw) ─► InboundEmail
          │                          │
          └──────────► InboundEmail ◄┘   ← BOTH paths converge here
                            │
                            ▼
              the pipeline only ever sees InboundEmail
```

Two interchange strategies, both valid; pick one and state it:

- **(Recommended) Fixtures are already-canonical `InboundEmail` JSON.** The dev `POST /webhook/inbound` receives exactly what the gateway would emit. `parse_inbound` is bypassed in dev and exercised only once, when the real provider is wired. Simplest; the whole pipeline is built and demoed without the gateway existing.
- **(Alternative) Fixtures mimic the chosen provider's raw shape**, and `parse_inbound` runs in dev too. More faithful, but couples fixtures to a provider you haven't chosen yet — contradicts "provider wired last."

**Recommendation:** canonical-fixture path. The gateway's `parse_inbound` becomes the *last* thing implemented and the *only* thing that changes when you pick n8n vs a hosted parser. The webhook endpoint, the orchestrator, and every stage are provider-agnostic from day one. The "send test email" button posts a canonical `InboundEmail` to the same endpoint — it is literally a fixture replay, which is why it doubles as demo *and* live-email fallback.

### Outbound symmetry

The gateway's send side must **return the outbound `Message-ID`** so the orchestrator can store it on the run for threading. In dev, the gateway's send is a no-op stub that returns a synthetic `Message-ID` and logs the draft. This lets the full clarify→reply→resume loop be tested end to end with **zero** real email — post a "reply" fixture whose `in_reply_to` equals the synthetic id.

---

## Pipeline Re-entrancy (resume on threaded reply)

The build plan says a clarification reply "re-enters at stage 2 (extract) and the run resumes." For that to be safe, re-running stages 2–5 on an existing run must be idempotent.

### Fresh run vs resumed run

| | Fresh run | Resumed run (reply) |
|---|---|---|
| Trigger | Inbound email, no `In-Reply-To` match | Inbound email whose `In-Reply-To`/`References` matches an outbound msg-id stored on a run in `awaiting_reply` |
| Run row | **Created** | **Reused** (looked up by header → run_id) |
| `source_email_id` | the new inbound | unchanged (original); the reply is appended to `email_messages` with `run_id` set |
| Status on entry | `received` → `extracting` | `awaiting_reply` → `extracting` |
| `extracted_data` | empty → filled | **already populated** → must be *replaced/merged* by the new extraction over original + reply text |
| Line items | none yet | possibly none (clarify happened before compute) — clean |

### Idempotency invariants the roadmap must enforce

1. **Stage 2 (extract) must overwrite, not append.** Re-extraction sets `extracted_data` fresh from the combined context (original email + the reply that answered the question). Treat `extracted_data` as a single replaceable cell, not an accumulator. The jsonb column makes this a single write.
2. **Stage 3 line-item writes must be replace-by-run, not insert-only.** If a resume ever reaches compute twice, deleting/replacing `paystub_line_items WHERE run_id = ?` before re-inserting prevents duplicate paystubs. (Because clarify precedes compute, this is usually moot — but it is the invariant that makes a re-trigger of a stuck `computed` run safe.)
3. **`decision` is overwritten each pass.** The stored decision object always reflects the latest evaluation, so the dashboard and eval read one truth.
4. **The reply must be matched to a run in `awaiting_reply` specifically.** A header match to a run already `sent`/`reconciled`/`rejected` is a late/duplicate reply — log it, do not resume. This guard is the boundary between "resume" and "ignore."
5. **`email_messages` is append-only and is the audit log.** Every inbound and outbound is a row. The run's `extracted_data` is mutable; the message history is not. This split is what keeps the pipeline re-runnable while preserving a complete audit trail.

### Why re-entry targets stage 2 (not stage 5)

The reply contains *new information* ("Jane worked 38 not 48"). Resuming at decide would re-decide stale extracted data. Resuming at extract re-reads the corrected facts and flows naturally back through reconcile → validate → decide, which may now pass the gate. **The whole 2→5 segment is designed to be safe to re-run; that is the architectural cost of the resume feature, and it is paid by making those four stages stateless-over-their-inputs.**

---

## The Eval / Production DRY Seam

> Hard requirement: the eval runs "the same extraction and decision code over the fixtures." Zero duplication.

### The boundary that makes it work

The four "judgment" stages must be written as **pure-ish functions that take Pydantic inputs and return Pydantic outputs, with the DB and the LLM client passed in (or imported), not entangled.**

```
                app/pipeline/  (the single implementation)
                ┌──────────────────────────────────────────┐
                │ extract(email_text, *, llm) -> Extracted  │
                │ reconcile_names(extracted, roster, *, llm)│
                │ validate(extracted) -> Issues             │
                │ decide(extracted, recon, issues, *, llm)  │
                │   -> Decision   (incl. the hard gates)    │
                └───────────────┬───────────────┬──────────┘
                                │               │
           imported by         │               │   imported by
        ┌───────────────────────▼┐            ┌─▼──────────────────────┐
        │ orchestrator (live)     │            │ eval/run_eval.py       │
        │ loads run from DB,      │            │ loads fixtures from     │
        │ calls the 4 fns,        │            │ disk, calls the SAME    │
        │ persists status+jsonb   │            │ 4 fns, scores vs labels │
        └─────────────────────────┘            │ writes eval_results     │
                                               └─────────────────────────┘
```

The seam is: **`app/pipeline/{extract,reconcile_names,validate,decide}.py` know nothing about runs, statuses, webhooks, or the DB.** They are functions over `models/` types. The *orchestrator* is the only thing that ties them to persistence; the *eval* ties the identical functions to fixtures + scorers. Neither extraction logic nor the gate logic exists in two places.

### Concrete DRY rules for the roadmap

- **Stage functions take data, return data.** No `def extract(run_id)`. Instead `def extract(email_text, *, llm) -> Extracted`. The orchestrator does the DB load/store around it; the eval does fixture load + scoring around it. This single signature decision is what satisfies the DRY requirement.
- **The hard gates live inside `decide.py`, not in the orchestrator.** Critical: the eval must exercise the *gates*, not just the LLM. If the orchestrator applied the gate, the eval would test a different decision path than production. So `decide()` returns the *gated* `Decision` (LLM proposal + code override), and both callers get identical behavior. The orchestrator merely *acts* on the decision (which status to set); it never *makes* it.
- **The LLM client is injected/imported, not stubbed differently.** Eval and production hit the same `app/llm/client.py`. (Eval may pin temperature 0 for reproducibility, but it is the same client/router.)
- **Calc + reconcile_payroll are already pure** — eval can score computed payroll against ground truth by importing them directly too, if the suite grows to cover compute.

### Where the three decisioning layers live as code

| Layer | Lives in | Callable by |
|-------|----------|-------------|
| Deterministic fast-path | `reconcile_names.py` (exact/normalized/alias match) + `validate.py` (presence, bounds, numeric) | orchestrator + eval |
| LLM judgment | `reconcile_names.py` (fuzzy, only on det-match leftovers) + `decide.py` (process-vs-clarify proposal) | orchestrator + eval |
| Hard gates (code) | **inside `decide.py`** — block on missing required field or any name < 0.8 confidence, even on LLM "process" | orchestrator + eval |

Putting the gate *inside* `decide.py` (not in the orchestrator) is the single decision that keeps the auditable, gated decision identical in the live system and in the eval. **This is the load-bearing DRY decision.** Call it out in the roadmap.

---

## Component Boundaries & Data Flow

### What talks to what (allowed dependency directions)

```
main.py ──► orchestrator ──► {extract, reconcile_names, validate, decide,
                              calculate, reconcile_payroll, compose_email}
                │                       │              │           │
                │                       ▼              ▼           ▼
                │                   llm/client    (pure, no I/O)  llm/client
                ▼
            db/supabase  ◄──── dashboard (read) ; ◄──── operator actions (write status)
                ▲
                │
            email/gateway  (called by orchestrator for send; calls back via webhook)

eval/run_eval ──► {extract, reconcile_names, validate, decide} ──► llm/client
              └─► scorers ──► db/supabase (eval_results)        [reuses prod fns]

pdf/paystub ◄── orchestrator (stage 8) / dashboard (on-demand render)
```

Rules: arrows point only downward/inward. `main.py` and `eval/run_eval.py` are the two *entry points*; both depend on pipeline components, never the reverse. Stage functions depend on `models/`, `llm/client`, and (for calc) nothing. Only the orchestrator and the operator actions mutate `status`.

### Key data flows

1. **Fresh intake:** webhook → `parse_inbound`→`InboundEmail` → create `payroll_runs(received)` + `email_messages(inbound)` → 200 returned → `BackgroundTask(run_pipeline)` → extract→reconcile→validate→decide → pause at `awaiting_approval` or `awaiting_reply`.
2. **Clarify→resume:** decide=clarify → `compose_email`(LLM cheap) → `gateway.send` returns outbound msg-id → stored on run, status `awaiting_reply`, `email_messages(outbound)` row → … client replies … → webhook → header lookup finds the run → status `extracting` → re-run 2–5.
3. **HITL approve:** operator opens `/runs/{id}` → sees submitted vs computed + decision object → `POST approve` → status `approved` → `BackgroundTask` resumes orchestrator at stage 8 → `gateway.send` confirmation + `pdf/paystub` bytes attached → `sent` → stage 9 → `reconciled`.
4. **Eval:** CI/local runs `run_eval.py` → load fixtures → same `extract/reconcile/validate/decide` → `scorers` compare to labels → write `eval_results(suite_run_id,...)` → dashboard `/eval` renders the summary chart.

---

## Suggested Build Order (the dependency graph)

This is the section that drives phase sequencing. Read top-to-bottom; items on the same tier are parallelizable.

```
TIER 0 — Foundations (nothing works without these)
  ┌─────────────────────────────────────────────────────────┐
  │ db/schema.sql (6 tables, status enum)  +  db/supabase.py │
  │ models/ (Pydantic: InboundEmail, Extracted, Decision,    │
  │          PaystubLineItem, …)  — the shared contracts     │
  └───────────────┬─────────────────────────────┬───────────┘
                  │                             │
TIER 1 — Independent leaves (build in parallel) │
  ┌───────────────▼──────────┐   ┌──────────────▼───────────┐
  │ llm/client.py + routing  │   │ calculate.py +           │
  │ (base_url/model/key swap,│   │ reconcile_payroll.py     │
  │  JSON mode, retry-once)   │   │ (PURE — no deps at all,  │
  │  ◄ unblocks all LLM stages│   │  unit-test against IRS   │
  └───────────────┬──────────┘   │  Pub 15-T worked examples)│
                  │              └──────────────────────────┘
TIER 2 — The pipeline seam + judgment stages
  ┌───────────────▼─────────────────────────────────────────┐
  │ main.py webhook  +  InboundEmail contract  +  ingest.py  │
  │   (POST a fixture → create run → 200 + BackgroundTask)    │
  │ orchestrator.py skeleton (status state machine driver)    │
  │ extract.py → reconcile_names.py → validate.py → decide.py │
  │   (decide.py CONTAINS the hard gates)                      │
  │ email/gateway.py with STUB send (returns synthetic msgid) │
  └───────────────┬─────────────────────────────────────────┘
                  │  ← at this point the whole happy path +
                  │    name-mismatch + clarify→reply→resume
                  │    runs end-to-end with ZERO real email
TIER 3 — Close the loop (needs runs to exist)
  ┌───────────────▼──────────┐   ┌──────────────────────────┐
  │ compose_email.py (LLM    │   │ dashboard (list, detail,  │
  │ cheap) + clarify auto-   │   │ approve/reject buttons,   │
  │ send + threading store   │   │ side-by-side submitted vs │
  │ + resume-on-reply lookup │   │ computed) — reads existing │
  └───────────────┬──────────┘   │ state, so it comes AFTER  │
                  │              │ runs exist                │
                  │              └──────────────────────────┘
TIER 4 — Proof + delivery (needs extract+decide reusable)
  ┌───────────────▼─────────────────────────────────────────┐
  │ eval/: generate_fixtures → fixtures/ → run_eval (imports  │
  │   TIER-2 stage fns) → scorers → eval_results              │
  │ eval view on dashboard (the chart = the proof)            │
  │ pdf/paystub.py (on-demand) + stage 8 attach + stage 9     │
  └───────────────┬─────────────────────────────────────────┘
                  │
TIER 5 — Wire reality + ops (LAST, by design)
  ┌───────────────▼─────────────────────────────────────────┐
  │ email/gateway.py REAL provider (n8n / inbound-parse)      │
  │   — only parse_inbound + real send change                │
  │ Dockerfile, Render deploy, Supabase project              │
  │ .github/workflows: keepalive.yml + eval.yml              │
  │ README + architecture diagram + 60-90s demo              │
  └─────────────────────────────────────────────────────────┘
```

### Hard ordering constraints (the "X before Y" the roadmap must respect)

- **Schema + `models/` before everything.** They are the contracts every other component imports. (Tier 0.)
- **`llm/client.py` before extract/reconcile/decide/compose.** Every LLM stage is a no-op without the router. (Tier 1 → Tier 2.)
- **Calc engine is the one component with no upstream dependency** — buildable Tier 1, fully unit-tested in isolation against IRS Pub 15-T examples, *in parallel* with the LLM client. It is the highest-bug-risk unit, so isolating it early de-risks the schedule.
- **The webhook + fixture seam before any stage can be exercised end-to-end** — but the stages themselves only need `models/` + `llm/client`, so stage *logic* can be drafted in parallel with the webhook and joined by the orchestrator.
- **Gateway send can be a stub until Tier 5.** The entire clarify→reply→resume loop is testable with a synthetic-msgid stub + reply fixtures. The real provider is wired *last* and touches only `gateway.py`.
- **Dashboard after runs exist.** It reads state; there's nothing to render until the pipeline produces runs. (Tier 3.)
- **Eval after extract + decide are reusable.** Eval's entire value is reusing those functions; it cannot precede them. (Tier 4.)
- **Deploy/CI last.** Dockerfile, Render, keep-alive, and the eval workflow are packaging, not logic. (Tier 5.)

### The earliest "it visibly works end to end" milestone

End of **Tier 2 + the clarify loop from Tier 3** = a recruiter-demoable system with no email provider, no PDFs, and a stub dashboard: POST a messy fixture → watch the run move `received→extracting→needs_clarification→awaiting_reply`, POST a reply fixture → `extracting→computed→awaiting_approval`, approve via a curl or a one-button page → `sent→reconciled`. Optimizing for "visibly works end to end" (the stated #1 priority) means front-loading Tiers 0–2 and treating Tier 5 (real email, deploy) as the safe, isolated tail.

---

## Render Free-Tier Architectural Implications

These constraints are not ops trivia — they shaped the core design, and getting them wrong breaks the demo.

| Constraint | Architectural consequence | Concrete rule |
|------------|---------------------------|---------------|
| **Sleeps after 15 min idle; only inbound HTTP wakes it** | **Webhook-driven, never polling.** There is no background loop to "check for new email." All progress is event-triggered: an inbound POST or an operator button. | No `while True`, no cron-in-process, no scheduler. Every state advance is caused by an HTTP request. |
| **Cold start < 1 min** | First request after sleep is slow; the *gateway* must tolerate a one-time delay. A provider retry/timeout on the inbound webhook must not drop the email. | Webhook returns 200 *fast* (before pipeline work) so the provider sees success even during a cold start. Pipeline runs in a `BackgroundTask` after the response. |
| **In-process `BackgroundTasks` + a dyno that can sleep mid-task** | A run can be stranded mid-`extracting`/`computed` if the dyno sleeps before the task finishes. **This is why the Postgres `status` column must double as a crash-recovery anchor, not just a HITL gate.** | Persist status transitions *as each stage completes*, so a re-trigger resumes from the last durable status. Make stages 2–5 idempotent (already required by the resume feature). Surface `error`/stuck runs on the dashboard with a re-trigger. |
| **Ephemeral filesystem** | Nothing on local disk survives. PDFs cannot be cached to disk; fixtures must be in the repo (they are). | `pdf/paystub.py` returns bytes, generated on demand from the run row, streamed in the response — never written to disk. (This is exactly why "generate on demand, no storage bucket" was chosen.) |
| **Free Supabase project pauses when idle** | The single source of truth can go away. | `keepalive.yml` GitHub Action pings Supabase a couple times a week. State integrity depends on this workflow, so it is part of the architecture, not an afterthought. |
| **Single process, no queue/Redis** | No external durable queue. The "queue" is the set of runs in non-terminal statuses. | The state machine *is* the work queue. Recovery = "find runs not in a terminal status and re-drive them," which a re-trigger or a manual dashboard action handles. |

**The synthesis:** Render-free forces an event-sourced, database-as-truth design where every unit of progress is (a) triggered by an HTTP event, (b) short enough to finish before a likely sleep, and (c) durably checkpointed in `status` so a cold start never loses a run. The webhook+Postgres+BackgroundTask combination is not incidental — it is the minimal architecture that survives this hosting tier. (FastAPI `BackgroundTasks` running after the response is returned: verified against current FastAPI docs.)

---

## Anti-Patterns (specific to this build)

### Anti-Pattern 1: Smuggling the hard gate into the orchestrator
**What people do:** Let `decide.py` return the raw LLM proposal and have the orchestrator apply the 0.8/missing-field gate before setting status.
**Why it's wrong:** The eval calls `decide.py` directly and would test the *ungated* decision — a different code path than production. The auditable, gated decision (the project's core value) would be untested.
**Do this instead:** The gate lives **inside** `decide.py`; it returns the final gated `Decision`. The orchestrator only maps that decision to a status.

### Anti-Pattern 2: Stage functions that take a `run_id` and do their own DB I/O
**What people do:** `def extract(run_id): row = db.get(run_id); ...; db.save(...)`.
**Why it's wrong:** Couples judgment logic to persistence, making the eval unable to reuse it without a database and fixtures masquerading as runs. Breaks the DRY requirement.
**Do this instead:** `def extract(email_text, *, llm) -> Extracted`. Persistence lives only in the orchestrator.

### Anti-Pattern 3: A polling loop or in-process scheduler to "check for replies"
**What people do:** A background thread that periodically scans for new mail or stuck runs.
**Why it's wrong:** Render sleeps the dyno; the loop dies. Only inbound HTTP wakes the service, so the loop is both unreliable and pointless.
**Do this instead:** Everything is webhook/button-triggered. The reply *arrives* as an inbound POST and resumes the run by header lookup.

### Anti-Pattern 4: Treating `extracted_data` as an accumulator across resumes
**What people do:** Merge new extraction into the old jsonb on a reply.
**Why it's wrong:** Re-extraction over the corrected context should *replace* the picture; merging creates inconsistent half-states and breaks idempotency.
**Do this instead:** Stage 2 overwrites `extracted_data` wholesale each pass; append-only history lives in `email_messages`.

### Anti-Pattern 5: Coupling fixtures (or the webhook) to the chosen email provider before it's chosen
**What people do:** Shape fixtures like n8n's payload and parse provider fields in the webhook.
**Why it's wrong:** Violates "provider wired last"; you'd rework fixtures + webhook when the provider changes.
**Do this instead:** Fixtures and the webhook speak the canonical `InboundEmail`. `gateway.parse_inbound` is the only provider-aware code and is implemented last.

---

## Integration Points

### External Services

| Service | Integration pattern | Notes / gotchas |
|---------|---------------------|-----------------|
| Kimi / DeepSeek (LLM) | OpenAI-compatible client; swap `base_url`+`model`+`key` per task tier; `response_format={"type":"json_object"}`; one retry on parse failure → Pydantic validate | Model IDs config-driven (env). Non-reasoning chat variants only. Verified: `base_url` swap + JSON mode are the standard OpenAI-compatible mechanisms. |
| Email gateway (n8n / inbound-parse) | Inbound: provider POSTs → `parse_inbound` → `InboundEmail`. Outbound: `gateway.send` returns `Message-ID`. | The ONE provider-aware seam. Wired last. Threading anchored on RFC `In-Reply-To`/`References` vs the stored outbound `Message-ID`. |
| Supabase Postgres | Python client / typed accessors; all 6 tables; `status` is the state machine. | Free project pauses when idle → keep-alive workflow is load-bearing. No file storage used. |
| GitHub Actions | `keepalive.yml` (ping Supabase), `eval.yml` (run eval on push, import pipeline fns). | Eval workflow must have LLM keys as secrets; reproducibility favors temperature 0. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `main.py` ↔ orchestrator | direct call + `BackgroundTask(run_pipeline, run_id)` | Webhook returns 200 before pipeline runs. |
| orchestrator ↔ stage fns | direct calls over `models/` types | Orchestrator owns persistence + status; stages own logic. |
| stage fns ↔ `llm/client` | injected/imported client | Stages are vendor-agnostic. |
| orchestrator ↔ `email/gateway` | `send(outbound) -> message_id` | Stub in dev; real provider last. |
| dashboard ↔ db | read; + approve/reject **write status only** | Operator actions are pipeline re-entry, not arbitrary edits. |
| eval ↔ stage fns | imports the SAME functions | The DRY seam; zero reimplementation. |

---

## Scaling Considerations

This is a single-operator educational demo for a recruiter audience; "scale" means "survives a live demo on a free tier," not throughput.

| Scale | Adjustment |
|-------|------------|
| Demo (1 operator, a handful of runs) | Current architecture is exactly right. Single FastAPI process, `BackgroundTasks`, Postgres state. |
| If it ever grew (out of scope) | First bottleneck would be in-process `BackgroundTasks` on a sleeping dyno → move pipeline work to a durable external queue (the `status` column already makes runs re-drivable, so this is a localized change). Second: per-task LLM latency → already mitigated by tiered routing + non-reasoning models. |

**Scaling priority #1 (the only one that matters here):** never lose a run to a cold start. Solved by durable status checkpoints + idempotent stages 2–5 + dashboard-visible re-trigger.

---

## Sources

- `payroll-agent-build-plan.md` — full data model, 9-stage table, email/threading section, repo structure, build phases (project-internal, authoritative for the locked design).
- `.planning/PROJECT.md` — decisioning model, constraints, key decisions (project-internal, authoritative).
- FastAPI `BackgroundTasks` — runs after the response is returned; integrates with DI. Verified via Context7 (`/fastapi/fastapi`). Confirms the "return 200 fast, run pipeline after" pattern that the Render cold-start constraint requires. HIGH.
- OpenAI Python client — `base_url` swap for OpenAI-compatible providers + `response_format={"type":"json_object"}`. Verified via Context7 (`/openai/openai-python`). Confirms the single-client per-task-tier routing design. HIGH.
- Supabase Python client (`/supabase/supabase-py`) — Postgres accessors for the state-as-table model. Verified available; HIGH that the pattern is supported.

---
*Architecture research for: LLM email-to-payroll pipeline with Postgres state machine + single HITL gate*
*Researched: 2026-06-20*
