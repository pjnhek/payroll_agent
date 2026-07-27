# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary: an evaluator watching an operator work.** A hiring manager, recruiter, or engineer who
arrives from a resume link, the README, or the GitHub repo. They are not running payroll. Their job
is to decide, in a short bounded session, whether the engineering claim behind this project is real.
They have no prior context on the codebase and are not payroll experts. Confirmed this session:
**legibility to an outsider outranks operator efficiency.**

**Demonstrated, not served: the payroll operator.** The person who approves a computed run before it
reaches the client. This is the role the builder personally played as a tax analyst, and the workflow
the product reconstructs. The operator is the character in the demonstration, not the user whose
throughput the interface optimizes for.

**Never in the interface: the client business contact.** They only send and receive email (hours in,
clarification questions in, payroll confirmation and paystub PDFs out). No client-facing screen
exists, by design.

## Product Purpose

Pyrl automates the weekly payroll intake the builder used to do by hand. A client business emails its
employees' hours; the pipeline reads the email, resolves the submitted names against that business's
roster, decides whether it can process the run or must ask a clarifying question, computes the payroll
(gross, FICA, real IRS Pub 15-T federal withholding), and routes the result to a single human operator
for one approval before the confirmation goes back to the client.

Success is not payroll throughput. Success is an evaluator concluding, from the interface itself and
without being told, that the money-moving decisions are genuinely code-owned and auditable.

## Positioning

**The LLM reads. Deterministic code decides.**

Every money-moving judgment call is resolved in pure code. Each submitted name resolves against the
roster as exact / stored-alias / none; any unresolved name, any run-level collision, or any missing
required field forces a clarification. `decide.py` computes `final_action` with no LLM call, no
confidence number, and no scoring concept anywhere in it. The LLM has exactly two jobs: extraction,
and an advisory suggestion for the clarification email's wording, wired strictly after the gate so it
can never feed the decision.

The offline eval imports and scores those same production functions over hand-curated fixtures, so
the proof and the product cannot drift apart. The durability claims are each accompanied by an
executed falsifying mutation, so they are demonstrated *able to fail* rather than merely shown
passing.

A neighboring project can call itself an AI payroll agent. It cannot truthfully claim that its money
decisions are code-owned, that its eval runs the same functions production runs, or that its failure
guarantees have been proven able to fail.

## Operating Context

- **Email is the real interface for the client.** Threading is anchored on the RFC `Message-ID`
  header. `payroll@jiodnel.resend.app` is a live inbound address. The in-app composer at `/` exists
  so an evaluator can drive a real run without an email client.
- **Six web surfaces:** `/` (roster + composer + recorded round-trip), `/runs` (list with live status
  badges), `/runs/{id}` (the run detail — the human gate), `/eval` (the proof), `/ops` (queue health),
  and an on-demand paystub PDF download.
- **The run-detail page is the single human gate.** It carries the chronological email conversation,
  the LLM's extraction, the computed paystubs, and the code-owned decision banner. Its purpose is to
  let a human verify the LLM's *reading* against what the client actually sent.
- **Render free tier shapes the first impression.** The service sleeps after 15 minutes of no inbound
  traffic and takes roughly 30–60 seconds to wake, showing a platform loading page. An evaluator's
  session frequently begins cold. The recorded walkthrough exists as the reliable alternative.
- **Recovery is best-effort, on a 30-minute cadence.** A GitHub Actions cron drives an authenticated
  pump endpoint; Render free wakes only on inbound HTTP, so nothing internal can be trusted to run.
- **No authentication.** Anyone with the URL sees every run. Deliberate: it is a demo.
- **Two machine pause states, one human gate:** `awaiting_reply` (waiting on the client, resumes at
  extraction) and `awaiting_approval` (the operator gate, resumes at delivery).

## Capabilities and Constraints

**Confirmed functionality:** LLM extraction (DeepSeek tier) and clarification suggestion + email
drafting (Kimi tier), both non-reasoning chat variants behind one OpenAI-compatible client; pure-code
roster reconciliation with Unicode-NFC-hardened matching; pure-code decide; 2026 Pub 15-T standard
percentage method plus FICA, penny-accurate and guarded by a reconciliation check; a bounded
clarification round machine (3-round cap escalating to a first-class `needs_operator` status with an
operator resolve-and-resume surface); field-regression detection and carry-forward; alias learning
that binds only on explicit client confirmation with same-record evidence; one operator approval gate
with atomic CAS; on-demand in-memory paystub PDFs including YTD columns; a durable jobs queue with
at-most-once confirmation delivery; a committed offline eval with a per-category chart.

**Binding technical constraints:**

- **Server-rendered, no build step — permanent.** FastAPI + Jinja2 templates, one hand-authored
  stylesheet, vanilla JS for progressive enhancement. No bundler, no npm, no TypeScript, no component
  framework, no SPA. Confirmed binding this session: any future design must be achievable in
  hand-authored CSS and server-rendered HTML, or it is not the design.
- **One stylesheet:** `app/static/style.css`, token-driven (spacing, surfaces, text, accent,
  semantic, radius, elevation, motion, type all declared as custom properties on `:root`).
- **The interface uses the platform's native UI stack and issues no third-party font request.**
  First paint carries no render-blocking dependency on a service that is not this app.
- **Ephemeral filesystem.** Nothing written to disk survives a restart or spin-down. PDFs are
  generated in memory on demand; there is no storage bucket.
- **Nothing heavy at serve time.** matplotlib is a dev-group-only dependency; `eval/chart.svg` is
  committed and served as a file, never rendered per request.
- **Every surface must stay legible and usable with JavaScript disabled.** The 2-second status poller
  on `/runs` and `/runs/{id}` is progressive enhancement only; `/ops` was verified JS-free at UAT.
- **Postgres is the only state.** `payroll_runs.status` is simultaneously the workflow position, the
  durable checkpoint, the human gate, and the crash-recovery anchor. The `jobs` table carries
  transport state only and never a business status.

**Product vocabulary** future copy must use rather than invent around: run, roster, client business,
operator, clarification, alias, `final_action`, exact / stored-alias / none, `awaiting_reply`,
`awaiting_approval`, `needs_operator`, `reconciled`, epoch, pump, dead-letter.

**Deliberately out of scope** (do not design toward these): per-state withholding, OBBBA tax
provisions, spreadsheet-attachment parsing, a client-side confirmation step, persisted or cached PDFs,
dashboard authentication, an autonomous agent loop or graph framework, and throughput machinery
(fairness lanes, priority, backpressure, circuit breakers) for load that will never arrive at roughly
one payroll email per client per week.

## Brand Commitments

- **Name: Pyrl.** Confirmed binding this session. It is what the interface says
  (`app/templates/base.html:6`, `:15`). "Payroll Agent" is the repository and project title, not the
  product name.
- **Voice: plain, precise, disclaimer-forward.** Claim exactly what is true and name what is not
  covered. This is a demonstrated discipline, not an aspiration: a v3 phase fixed an eval chart that
  had been misreporting a metric; the recovery guarantee is stated as *best-effort within minutes*
  rather than a guarantee, because GitHub Actions cron can be delayed; exactly-once send is called
  impossible (Two Generals) and the ambiguous window escalates to a human instead of resending.
  **Overclaiming is the one brand failure this product cannot afford** — the whole thesis is that it
  does not guess.
- **Required standing disclaimer:** educational portfolio project, not tax-compliant payroll
  software, must not be used to pay real employees.
- **No logo, wordmark, or brand asset exists.**

## Evidence on Hand

Real and reachable:

- Live deployment: `https://payroll-agent.onrender.com`
- Recorded walkthrough: `https://www.loom.com/share/b844c3e0a3364a91b114ab892cc41db4`
- Source: `https://github.com/pjnhek/payroll_agent`, with a passing CI badge in the README
- `app/static/demo-thumbnail.gif` (382 KB animated) — the only image asset in the project
- `eval/chart.svg` — committed per-category chart over 18 hand-curated fixtures spanning the full
  name-resolution taxonomy; headline result `false_process_count = 0`
- `docs/architecture.svg`, `.png`, `.mmd` — implementation-level flow diagram
- `docs/DURABILITY-PROOFS.md` — four durability proofs, each with the falsifying mutation and the red
  pytest run behind it, plus what the claims deliberately do not cover
- Seeded demo data: 3 client businesses, 6 employees, covering every calc path and name-match case
- Named real fixture cases usable as copy: `David Reyez` → `David Reyes` (typo, must clarify);
  `D. Reyes` (alias shared by David Reyes and Daniel Reyes, must always clarify)

Absences that future work must not fabricate: there are **no** customers, users, testimonials, case
studies, press mentions, pricing, team, funding, compliance certification, logo, or photography. There
are no uptime, latency, or accuracy figures beyond the committed eval output and CI results above.

## Product Principles

1. **Legibility to an outsider outranks operator efficiency.** The primary user is evaluating, not
   working. A screen that a payroll operator would find dense is a failure here.
2. **Show the gate, don't assert it.** Comparing computed output against the LLM's own extraction
   agrees by construction. The evidence must always include what the client actually sent.
3. **Claim only what is demonstrated, and name what is not covered.** Every strong claim in this
   product is paired with its limit. Design must not strip the limit to make the claim louder.
4. **Achievable in hand-authored server-rendered code, or it is not the design.** No build step is a
   constraint on ambition, not an excuse for plainness.
5. **A cold start is part of the first impression.** Weight, request count, and third-party fetches
   are product decisions, not implementation details.

## Accessibility & Inclusion

No formal conformance standard was established as a product requirement. One product-level
requirement is confirmed: **every surface must remain legible and usable with JavaScript disabled**,
since the status poller is progressive enhancement only. The existing implementation already carries
`lang`, `alt` text, `role="alert"`, `aria-label`, and `aria-hidden` where appropriate.
