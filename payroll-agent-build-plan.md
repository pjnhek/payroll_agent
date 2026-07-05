# Payroll Agent: Build Plan

## What this is

An email-driven system that automates the weekly payroll intake I used to do by hand as a tax analyst. A client emails their employees' hours, an LLM-driven pipeline reads the email, reconciles the names against the business's roster, decides whether it can process the run or needs to ask the client a question, computes the payroll, and routes the result to a human for a single approval before it goes back to the client. Built on a free stack so it runs end to end and demos cleanly.

The narrative for the writeup: I rebuilt the manual payroll process from my accounting days as an agentic pipeline, with the LLM doing the reading, name matching, and decisioning, and a human approving only the final payroll before it reaches the client.

## Locked decisions

- Data layer: Supabase Postgres. Paystub PDFs are generated on demand from run data, so there is nothing to persist as a file. The Supabase Storage bucket stays available on the same project if we later decide to cache generated PDFs, but the plan does not depend on it.
- Compute: FastAPI in a Docker container on a Render free web service.
- Email: an email gateway (n8n or a hosted inbound-parse service) catches inbound mail and posts it to the app, and sends outbound mail. Threading is anchored on the RFC `Message-ID` header.
- Models: Kimi and DeepSeek through OpenAI-compatible clients. Use the non-reasoning chat variants for latency. Structured calls use JSON mode plus a Pydantic schema with one retry on a parse failure.
- Orchestration: a plain Python workflow, not an autonomous agent loop and not LangGraph. The path is fixed and we control it. State lives in Postgres, which is also the checkpoint for the human-in-the-loop pause.
- Human-in-the-loop: exactly one gate. The operator approves the computed payroll before it is sent to the client. Everything before that is automated.

## Actors

- Client (business): emails hours, receives results. A dedicated test inbox for the demo.
- Operator: the only human in the loop. Reviews the computed payroll against what the client sent and approves the send. This is the role I played as the accountant.
- The system: does everything in between with no human involvement.

## Decisioning model

This is the core of the design, so it is spelled out.

Three layers:

1. Deterministic fast-path (code, no model). Exact and normalized name match against the roster, including a known-aliases list per employee. Required-field presence (are hours there). Sanity bounds (hours not negative, not above a weekly ceiling, numeric). Arithmetic. Anything unambiguous resolves here and never touches a model.

2. LLM judgment (only where language understanding is needed). Two jobs. First, fuzzy name reconciliation: for any submitted name that fails the deterministic match, the model decides whether it is a typo of a roster employee, a nickname, or a genuinely different person, and returns a match plus a confidence score and a short reason. Second, the process-vs-clarify decision: given the extracted data, the roster, the name reconciliation results, and the field validation, the model returns a structured decision to either process or request clarification, with the list of issues.

3. Hard gates (code). Even if the model returns "process," code blocks it when a required field is truly missing or any name is unresolved below the confidence threshold. This keeps the decision auditable and keeps a low-confidence match from slipping through to a real payroll calculation.

All email drafting (clarification and confirmation) is done by the LLM. No human is involved until the final approval gate.

## Pipeline stages

| # | Stage | Type | Model tier | Output |
|---|-------|------|-----------|--------|
| 1 | Ingest and route | Deterministic | none | matched `business_id`, or unknown-sender flag |
| 2 | Extract timesheet | LLM | stronger | structured per-employee entries |
| 3 | Name reconciliation | Deterministic first, LLM on ambiguous | stronger/mid | per-name match + confidence |
| 4 | Field validation | Deterministic | none | per-field issues list |
| 5 | Decision | LLM, gated by code | mid | `process` or `request_clarification` + issues |
| 6a | Clarify path | LLM draft + auto-send | cheap | clarification email, status set to awaiting reply |
| 6b | Process path | Deterministic calc + LLM draft | cheap | paystub line items + draft confirmation |
| 7 | Operator approval | Human | none | approve and send, or reject |
| 8 | Send to client | Deterministic | none | confirmation email + paystub PDFs |
| 9 | Reconciliation check | Deterministic | none | net + taxes + deductions ties to run total |

Stage notes:

- Stage 1: match the sender address to `businesses.contact_email`. No match is an edge case (unknown sender); log it and stop, do not guess.
- Stage 2: this is the hardest reasoning step, so it gets the stronger model. Returns, per employee: name as written, regular hours, overtime hours, vacation, sick, holiday, and any 401k change.
- Stage 3: deterministic match handles exact, case, whitespace, and aliases. Only the leftovers go to the model. The model never re-decides a name that already matched cleanly.
- Stage 5: the model proposes the action and code enforces the gates. The decision object is stored on the run for the eval and the audit trail.
- Stage 6a: when clarification is needed the model drafts the email and the system sends it automatically. The client replies on the same thread. The reply re-enters at stage 2 and the run resumes.
- Stage 7: the only human step. The dashboard shows the client's submitted data next to the computed paystubs. The operator approves or rejects. Approval triggers stage 8.
- Stage 9: runs after send. Sum of net pay, taxes, and deductions should equal the run total. Flag any drift.

## Data model (Supabase Postgres)

`businesses`
- `id` uuid pk
- `name` text
- `contact_email` text (address clients send from and we reply to)
- `pay_period` text (weekly, biweekly)
- `created_at` timestamptz

`employees`
- `id` uuid pk
- `business_id` uuid fk
- `full_name` text
- `known_aliases` text[] (nicknames and short forms, used by the deterministic matcher)
- `pay_type` text (hourly, salary)
- `hourly_rate` numeric (null if salary)
- `annual_salary` numeric (null if hourly)
- `retirement_contribution_pct` numeric
- `filing_status` text (for federal withholding)
- `created_at` timestamptz

`payroll_runs`
- `id` uuid pk
- `business_id` uuid fk
- `source_email_id` uuid fk to `email_messages`
- `status` text (received, extracting, needs_clarification, awaiting_reply, computed, awaiting_approval, approved, sent, reconciled, rejected, error)
- `extracted_data` jsonb (the structured timesheet)
- `decision` jsonb (action, issues, confidence, reasons)
- `pay_period_start` date
- `pay_period_end` date
- `created_at` timestamptz
- `updated_at` timestamptz

`paystub_line_items` (one row per employee per run)
- `id` uuid pk
- `run_id` uuid fk
- `employee_id` uuid fk (nullable if unresolved)
- `submitted_name` text (what the client wrote)
- `match_confidence` numeric
- `hours_regular` numeric
- `hours_overtime` numeric
- `vacation_hours` numeric
- `sick_hours` numeric
- `holiday_hours` numeric
- `gross_pay` numeric
- `pretax_401k` numeric
- `fica_ss` numeric
- `fica_medicare` numeric
- `federal_withholding` numeric
- `state_withholding` numeric (nullable)
- `net_pay` numeric
- `created_at` timestamptz

`email_messages` (threading and audit)
- `id` uuid pk
- `run_id` uuid fk (nullable for the first inbound before a run exists)
- `direction` text (inbound, outbound)
- `message_id` text (RFC Message-ID header)
- `in_reply_to` text
- `references_header` text
- `subject` text
- `from_addr` text
- `to_addr` text
- `body_text` text
- `created_at` timestamptz

`eval_results`
- `id` uuid pk
- `suite_run_id` uuid (one eval pass)
- `fixture_id` text
- `metric_name` text (extraction_field_accuracy, decision_correct, name_reconciliation_correct, email_judge_score)
- `value` numeric
- `details` jsonb
- `created_at` timestamptz

## Email layer and threading

- Inbound: the gateway parses the email and posts the fields to a FastAPI webhook. Store a row in `email_messages`, including the `Message-ID`, `In-Reply-To`, and `References` headers.
- Routing a reply to its run: when the system sends a clarification email, save that outbound message's `Message-ID` on the run. The client's reply carries that ID in its `In-Reply-To` and `References` headers, so the webhook looks up the run by that header and resumes. Subject and provider thread id are fallbacks; the header match is the anchor.
- Outbound: drafted by the LLM, sent through the gateway. Clarification emails send automatically. The final payroll email sends only after the operator approves.
- Write the gateway behind one small interface so the app does not care whether it is n8n or a hosted inbound-parse service.

## Payroll calculation engine

Deliberately simplified but structurally correct. This is an educational model, not tax-compliant software, and the README says so plainly.

- Gross pay: hourly is hours times rate, with FLSA overtime at 1.5x for hours over 40 in the week. Salary is annual divided by pay periods.
- Add vacation, sick, and holiday pay.
- Pre-tax deduction: 401k contribution as a percent of gross.
- FICA: Social Security at 6.2 percent up to the annual wage base, Medicare at 1.45 percent. Look up the current year's wage base rather than hardcoding an old number.
- Federal withholding: IRS Publication 15-T percentage method.
- State: skip for the first build, or a flat rate with a disclaimer. Default is skip.
- Net pay is gross minus pre-tax, minus FICA, minus federal (minus state if enabled).
- Reconciliation: sum of net pay, taxes, and deductions across the run should equal the run total. Flag drift.

## Frontend

Deliberately thin. Served by FastAPI, or a tiny static site if preferred.

- Runs list: every payroll run with a status badge.
- Run detail: the client's submitted data next to the computed paystubs, the decision object with reasons, and on an approval-pending run, an Approve and send button plus a Reject option. This is the operator gate.
- Eval view: the latest eval summary, the headline metrics, and a small chart.
- Demo control: one button that fires a test email so the whole flow can be triggered on camera without leaving the page.
- No auth. It is a demo.

## Test generation and eval

This runs entirely offline and is the part that proves the system works.

- Generator: a script prompts a model to write realistic but messy payroll emails and, in the same call, emit the ground-truth JSON for each. Seed the categories on purpose: clean, name typo, missing hours, an employee not on the roster, a nickname, vague hours like "40ish", a reply buried under a signature, and later a spreadsheet attachment.
- Fixtures: the email-and-label pairs are committed to the repo so the eval is reproducible.
- Scoring: run the same extraction and decision code over the fixtures and measure field-level extraction accuracy, name reconciliation accuracy (did it match, flag, or correctly call unknown), decision accuracy (process vs clarify on the cases that should clarify), and an LLM-as-judge pass on clarification email quality.
- Output: results write to `eval_results` and render on the dashboard. Runs locally and in GitHub Actions on each push.

## Model routing

Use one OpenAI-compatible client and swap base URL, model, and key per task. Confirm exact model ids against the Kimi and DeepSeek consoles.

- Extraction: stronger model (DeepSeek V3 family or Kimi K2, non-reasoning), JSON mode, retry once.
- Name reconciliation: stronger or mid model, small structured call, only on names that failed the deterministic match.
- Decision: mid model, structured decision object, code enforces the gates.
- Email drafting: cheap or small model.
- Do not use reasoning models here. The over-thinking adds latency and this is not multi-step logic.

## Hosting, containerization, deploy

- Containerize only the FastAPI app. One Dockerfile, deploy as a single Render free web service.
- Supabase project holds Postgres. No file storage needed for the default build.
- Email gateway is cloud-hosted or its own container if self-hosted. Optional plumbing, not our code.
- GitHub Actions: a keep-alive workflow that pings Supabase a couple of times a week so the free project does not pause, and the eval workflow on each push.
- Render free notes to design around: the web service sleeps after 15 minutes and cold-starts in under a minute, the filesystem is ephemeral so nothing is written to local disk, and only inbound HTTP keeps it awake. The webhook model fits this; a polling loop would not.

## Build phases

Week 1, an MVP that runs end to end on the happy path plus the name-mismatch edge:
- Supabase schema, seed one or two businesses and about five employees with aliases.
- FastAPI skeleton and inbound webhook. Start by posting a JSON fixture, then wire the real gateway.
- Extraction (LLM, structured).
- Deterministic name match and field validation.
- LLM name reconciliation for the ambiguous case.
- LLM decision with the code gates.
- Payroll calc (gross, FICA, simplified federal).
- Draft and auto-send the clarification email, resume on the threaded reply.
- Operator approval gate with a minimal dashboard (list, detail, approve and send).
- Send the confirmation to the client.

Week 2, sharpen and prove it:
- Cheap-model routing wired for the email drafts.
- More edge cases (missing hours, impossible hours, new hire not on roster, duplicate name, multiple ambiguous names at once).
- Synthetic generator, fixtures, and the eval harness with all four metrics.
- Reconciliation step and on-demand paystub PDF generation.
- Dashboard polish: side-by-side input vs computed, eval summary, send-test-email button.
- Dockerfile, Render deploy, Supabase project, GitHub Actions for keep-alive and eval.
- README, architecture diagram, and a 60 to 90 second demo recording.

## Repo structure

```
payroll-agent/
  app/
    main.py                 FastAPI: webhook + dashboard routes
    pipeline/
      ingest.py
      extract.py
      reconcile_names.py
      validate.py
      decide.py
      calculate.py
      reconcile_payroll.py
      compose_email.py
    models/                 pydantic schemas
    llm/
      client.py             OpenAI-compatible wrapper + routing
      prompts/
    email/
      gateway.py            inbound parse, outbound send, threading
    db/
      supabase.py
      schema.sql
    pdf/
      paystub.py            generate on demand
    dashboard/
      templates/
  eval/
    generate_fixtures.py
    fixtures/
    run_eval.py
    scorers.py
  .github/workflows/
    keepalive.yml
    eval.yml
  Dockerfile
  requirements.txt
  .env.example
  README.md
```

## Open decisions to confirm in review

1. PDF storage. Default is generate-on-demand from Postgres, no bucket. Confirm, or switch on the Supabase Storage bucket to cache them.
2. Client confirmation. Default is that the operator approval is the only gate and the client simply receives the final payroll. Your earlier description had the client confirming too; say if you want a client-side confirm step added back.
3. State tax. Default is federal and FICA only with a disclaimer. Say if you want a flat-rate state line.
4. Email gateway. Plan is written gateway-agnostic. Pick n8n or a hosted inbound-parse service when you are ready.
5. Model ids per tier. Confirm the exact Kimi and DeepSeek model strings against your consoles.
6. Name-reconciliation confidence threshold for auto-clarify. Start with a value and tune it against the eval.

## LinkedIn framing

Lead with the before and after: the weekly payroll intake I used to do by hand, now an LLM-driven pipeline. Call out the name reconciliation (typo vs nickname vs different person, with confidence), the automated process-vs-clarify decisioning, and the single human approval at the highest-stakes step. Close on the eval numbers. The eval chart is the proof, not the demo.
