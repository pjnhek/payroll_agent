# Phase 6: Real Integration & Ship - Context

**Gathered:** 2026-06-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 6 takes the working slice (Phases 1–5: full pipeline, dashboard, delivery — 409 tests green against a STUB email gateway + local Postgres) and **ships it on the public free stack**: a real inbound-email provider wired behind the existing `EmailGateway` seam (fixture path unchanged), the FastAPI app containerized and deployed to a single **Render free** web service against a freshly-provisioned **Supabase** Postgres (via the Supavisor pooler), a GitHub Actions keep-alive, and a recruiter-facing README + architecture diagram + a 60–90s demo recording.

**The 4 Phase-6 requirements (authoritative, per ROADMAP.md / REQUIREMENTS.md):** OPS-01 (Docker + Render), OPS-02 (real email provider behind the interface), OPS-03 (keep-alive), OPS-04 (README + disclaimer + diagram + demo).

**PLUS correctness/robustness additions surfaced by an external review of this discussion (see D-13..D-18) — these are NOT in the 4 listed requirements but are folded in as in-scope because they are the production realities the STUB structurally hid:**
- **Inbound webhook idempotency** keyed on the provider Message-ID (real providers deliver at-least-once; a duplicated/replayed inbound that re-runs `decide.py` is exactly the false-process the thesis forbids — and it is invisible in the stub world). **Highest-value fix in the phase.**
- **Durable threading** — persist the full References chain per thread in Postgres and rebuild outbound In-Reply-To/References from that row on every send (Resend makes you own the chain; a dropped/duplicated delivery must not corrupt threading).
- **Inbound webhook signature verification** (the webhook is a public, unauthenticated, money-themed endpoint).

**Locked by requirements / prior phases / CLAUDE.md (NOT re-opened in discussion):**
- **psycopg3 against the Supabase Supavisor pooler, transaction mode port 6543** for app runtime (the direct `db.<ref>.supabase.co` host is IPv6-only; Render is IPv4 — the locked gotcha). `prepare_threshold=None` is **ALREADY set** on the pool (`app/db/supabase.py:46`) and bootstrap (`app/db/bootstrap.py:96`) — the runtime prepared-statement gotcha is already handled.
- **Bind `0.0.0.0:$PORT`** (Render injects `$PORT`, default 10000). Hardcoding the host/port fails the deploy.
- **uv toolchain** (never a tracked `requirements.txt`). Docker uses uv-from-lock (D-12).
- **reportlab PDFs in-memory** (ephemeral FS); **no auth** on the dashboard; **single** Render service (one always-on service fits 750 free instance-hrs/mo).
- **Keep-alive must ping an HTTP endpoint that triggers a DB query** — Render stays awake only on inbound HTTP; the app pinging itself does not work; Supabase pause is measured by actual DB queries.
- **The `EmailGateway` seam already exists** (`app/email/gateway.py`): `parse_inbound(raw)->InboundEmail` and `send_outbound(...)->message_id`. The real provider swaps in touching ideally ONLY this file. The **D-13c crash-safe ordering is already stubbed**: write the outbound intent row `send_state='reserved'` BEFORE the provider call, flip to `'sent'/'failed'` after — so live wiring should be a near-no-op, not a retrofit.
- **Resume is anchored on the RFC `In-Reply-To`/`References` header chain** (subject is only a documented fallback in the existing reply-routing code).
- **Locked disclaimer content** (CALC/README): educational-only / not-tax-compliant; OBBBA provisions excluded; Additional Medicare 0.9% over $200k YTD unmodeled.

**Phase priority framing (PROJECT.md):** *visibly works end-to-end* > *clean 60–90s demo* > *a real, legible eval chart*. Audience: hiring managers / recruiters. Bias every choice toward reliability on a cold free-tier dyno over polish.

**This phase has multiple BLOCKING human checkpoints** (consistent with how every prior real-world integration — live DB, live LLM — was gated): the Render deploy and the email round-trip are `autonomous:false` gates where the agent prepares all artifacts and the human executes the credentialed step. See D-09, D-10.

</domain>

<decisions>
## Implementation Decisions

### Area 1 — Email provider + threading

- **D-01 (provider = Resend — hold the free line):** Wire **Resend** behind the gateway. Research during this discussion confirmed the two locked criteria ("free tier" + "same provider in/out") **collide for Postmark**: Postmark inbound is locked to **Pro (~$16.50/mo)+**; its free Developer tier (100/mo) is **outbound-only** (verified, postmarkapp.com/pricing, Jun 2026). **Resend** satisfies BOTH criteria — free tier 3,000/mo (100/day), one verified domain (or the auto-created `.resend.app` address), webhooks, AND inbound (GA Nov 2025). Same provider handles inbound parse + outbound send (one account/credentials; outbound threading headers set by the same system that parses replies).
- **D-01a (Resend inbound is TWO-STEP — the real shape difference the stub hides):** Resend's `email.received` webhook payload is **metadata-only** (sender, recipient, subject, attachment filenames) — **NOT the body/headers** (verified, resend.com/docs/dashboard/receiving, Jun 2026). Retrieving the body requires a follow-up `resend.emails.receiving.get(email_id)` API call (the design supports large attachments in serverless body-size limits). **Therefore `parse_inbound` for Resend is a two-step operation (webhook → fetch), NOT the near-passthrough the Phase-2 stub implies.** This is the single biggest hidden shape difference and the thing most likely to break the "no-op swap" assumption — the planner must scope `parse_inbound` to own both steps.
- **D-01b (you own the References chain):** Resend does not synthesize threading for you. Resend's own guidance: extract the inbound `message_id`, set outbound `In-Reply-To` to it, and append all previous IDs to `References` **in your own code/DB**. This is the basis for D-14 (durable threading).
- **D-02 (provider candidates documented for the record):** Postmark = paid (Pro ~$16.50/mo) but self-contained JSON inbound payload with full headers + base64 attachments + a free `hash@inbound.postmarkapp.com` address (best header fidelity); Mailgun routes = multipart-form inbound, sandbox restricts recipients; n8n self-host = max control, another moving part to host. **Resend chosen; these recorded so the tradeoff is auditable and a swap is informed if Resend disappoints.**
- **D-03 (threading risk handling — verify-first, header-chain primary, NO proactive fallback):** The known landmine: the EMAIL-01 stub ALWAYS preserves threading headers because we mint them, so the clarify→reply→resume loop looks bulletproof through P5 and only meets reality here. Decision: **keep the RFC header chain as the sole resume anchor; do NOT build a subject-token fallback up front.** Build it ONLY if the verify round-trip (D-09b) reveals headers don't survive. Rationale: defensible under the priority order (visibly-works > demo > eval), and the demo uses one known client. **Acknowledged thin spot (from review):** the verify step only tests OUR mail client; real variance comes from the SENDER's client (Outlook/Exchange notoriously mangles `References`). If the fallback is ever built, the spec is LOCKED in D-03a.
- **D-03a (subject-token fallback SPEC — only if D-03's verify fails, or as a fast-follow if a poke reveals breakage):** header chain PRIMARY; an **opaque embedded token** (e.g. `[#a1b2c3]`, chosen to survive `Re:` stripping and subject edits) fires **ONLY on a header no-match**, **never in parallel** (parallel invites double-match bugs). This rule is fixed now so a later build doesn't re-litigate it.

### Area 2 — Demo recording

- **D-04 (venue = HYBRID — revised from the initial "live real inbound IS the demo path"):** Prove the transport is real ONCE (the D-09b verify gate + one real send→reply→approve round-trip on the deployed service), then **record the thesis beats via the DASH-05 "Send test email" button driving the SAME `decide.py`.** The live Render URL is shown as genuinely deployed/real, but the money-shot beats are NOT hostage to inbound-webhook latency on a cold dyno. **Rationale (review, accepted):** every thesis beat (clarify, learned-alias, eval) exercises `decide.py`, which does not depend on the transport being live — a hard "real inbound IS the demo path" gate imports email-latency risk into every take to prove something the email transport doesn't prove. **This RELAXES the recording dependency** (the live round-trip no longer hard-gates the recording) **but the D-09b verify gate itself still stands** (transport must be proven real once).
- **D-05 (de-risk the recording):** pre-warm the Render URL 30–60s before recording (the CLAUDE.md pre-warm note + the keep-alive workflow reduce cold starts), and edit out dead-air / latency waits in post so the final 60–90s is tight. **Caution (review):** visible cuts landing exactly on network boundaries can read as suspicious to a sharp engineer — favor the controllable button path (D-04) over heavy cuts.
- **D-06 (beats — all three + eval closing shot):** (1) clean → approve → deliver (confirmation email + per-employee PDFs); (2) unknown shorthand "David Reyez" → code gate clarifies + the suggestion call names the specific employee (**the thesis**); (3) operator approves the resolved run → shorthand is LEARNED → a re-run resolves with NO clarification ("clarifies once, then learns"); **+ a ~5–10s closing shot on the eval view** (per-category chart + `false_process_count=0`).
- **D-07 (demo-reset script — MUST build before recording, from review):** Beat 3 persists the learned alias to prod Supabase, so a SECOND take of beat 2 will NOT clarify (the shorthand is already learned). Build a **reset script** that clears the demo's learned aliases + run rows between takes (or use a fresh shorthand per take). This WILL bite mid-recording if not built first — treat it as a named deliverable, not an afterthought.

### Area 3 — Deploy scope & verification

- **D-08 (sequence — thin deploy FIRST, then wire the provider):** Phase 6 is the first time anything touches Render + Supabase-from-Render + `$PORT` + cold-start (the recommended early hello-world deploy in P1/P2 never happened). Deploy a minimal slice — container binding `0.0.0.0:$PORT`, reaching Supabase via the pooler, serving the dashboard + a health route — **BEFORE** wiring Resend. Provider + demo then land on a known-good deployment.
- **D-08a (local pooler pre-check BEFORE the Render deploy — from review; a cheap step, NOT a 4th gate):** First prove pooler connectivity from the laptop (6543, prepared statements already off) and apply schema/seed via the **session pooler (5432)** — see D-15. This **isolates** the IPv4/pooler/prepared-statement failure class from the container/`$PORT`/cold-start failure class, so when the thin deploy fails you know which layer broke.
- **D-09 (Render deploy = BLOCKING human checkpoint, `autonomous:false`):** The agent prepares ALL artifacts (Dockerfile, render config / `render.yaml`, env+secrets list, keep-alive workflow, health route); the **human executes the credentialed deploy** (create service, set env/secrets) and confirms it serves + reaches Supabase + survives a cold-start wake. Render account creation + secret injection need a human; a half-finished agent-driven deploy is worse than a clean handoff.
- **D-09a (Supabase stood up THIS phase, folded into the deploy checkpoint):** Create the production Supabase project, apply `schema.sql` + seed via the pooler, confirm Render→Supabase connectivity. Prior phases ran local Postgres with live-DB tests skip-guarded pending Supabase creds — this is the moment they go live.
- **D-09b (email round-trip = BLOCKING human checkpoint, `autonomous:false`):** Resend is not "wired" until the human has personally done a real send→reply→**headers-intact** round-trip against the deployed service and confirmed the three threading headers survive (the ~30-min check that retires the one assumption fixtures structurally cannot test). This gate STILL stands even though the demo no longer hard-depends on live inbound (D-04).
- **D-10 (dependency chain — LOCKED order):** `local pooler pre-check (D-08a)` → `Supabase up (D-09a)` → `thin Render deploy proves the stack (D-08/D-09)` → `wire Resend provider (D-01)` → `inbound dedup + durable threading in place (D-13/D-14)` → `email round-trip verify gate (D-09b)` → `record demo (D-04..D-07)`. Don't merge the gates — the failure domains are distinct.

### Area 4 — README + architecture diagram

- **D-11 (two-tier README):** A punchy recruiter-facing top — thesis (deterministic, never-guesses gated decisioning), embedded demo video/GIF, the eval chart, the architecture diagram, and the **locked disclaimers prominent near the top** — then a clearly-marked `## For engineers` section with full setup / run / deploy / testing detail. Serves both audiences without compromising either. **State plainly (review):** the recorded demo is the hero artifact; the live link is "bonus, may take ~30s to wake from free-tier sleep."
- **D-11a (architecture diagram = BOTH):** Mermaid source fenced in the README (diffable, native GitHub render) **PLUS an exported image (commit both SVG and PNG — SVG embedding in GitHub READMEs is inconsistent)** for guaranteed rendering. Show the pipeline stages + the two pause states (`awaiting_reply`, `awaiting_approval`) + the code gate (`decide.py`).

### Area 5 — Production-reality additions (folded in from the external review; technical correctness, no user-preference conflict)

- **D-13 (inbound webhook idempotency — HIGHEST-VALUE FIX):** As the **very first thing** the webhook handler does (before extraction / any pipeline work), dedup on the **provider inbound Message-ID** via a unique-constraint insert-or-skip (a dedicated dedup table, or reuse the existing `email_messages.message_id` UNIQUE — planner's call). Real providers (Resend stores+retries+replays; Postmark retries non-200 POSTs) deliver at-least-once; a duplicate that re-runs `decide.py` and re-processes is a false-process the `claim_status` send-guard does NOT cover (it guards sends, not the decision re-run). This is the single highest-value addition in the phase.
- **D-14 (durable threading from persisted state, NOT the last webhook):** Persist the full `References` chain per thread in Postgres; rebuild outbound `In-Reply-To`/`References` from that row on every send. Building it off "the last webhook I saw" lets a dropped/duplicated delivery silently corrupt threading. This also makes the D-13c crash-safe ordering actually crash-safe for *threading*, not just for send-state. Directly follows from D-01b (Resend makes you own the chain) + D-13 (at-least-once delivery).
- **D-15 (psycopg3 + pooler specifics beyond the locked IPv4 one):** (a) prepared statements — **already handled** (`prepare_threshold=None` set on pool + bootstrap); (b) **NEW:** run `schema.sql` + seed over the **session pooler (port 5432 on the same pooler host)** or the direct connection — NOT 6543. Transaction mode (6543) is for the app's short-lived runtime queries; migrations over it can misbehave. Confirm against current Supabase docs when standing up the fresh project.
- **D-16 (keep-alive — one cron, DB-touching health route, serves BOTH pause problems):** Render cold-start (15-min spin-down, 30–60s wake) and Supabase pause (7-day, measured by actual DB queries, ~30s wake) are **two different problems**. A GitHub Actions cron (daily or twice-weekly) is the right tool for the **Supabase** half but a poor tool for keeping Render warm 24/7 (scheduled Actions are unreliable sub-15-min and auto-disable after ~60 days of repo inactivity — on a portfolio repo you don't push to, the keep-alive silently dies and Supabase pauses anyway). **Decision:** make the cron hit a **Render HTTP health route that runs a real `SELECT`** — one ping keeps both warm (Render needs inbound HTTP; Supabase needs a DB query). Accept that a recruiter clicking the link cold still eats a 30–60s Render wake (stated in the README per D-11).
- **D-17 (webhook signature verification — step zero in the handler):** The inbound webhook is a public, unauthenticated, money-themed endpoint. Verify the provider signature as the FIRST action (Resend ships a signing secret + headers + `resend.webhooks.verify()`). Signature verification needs the **raw request body** + the secret at the route layer — put a `verify()` in the gateway module so the route stays provider-agnostic (see D-18). "What stops me POSTing a fake inbound payroll email?" is a question a good interviewer asks.
- **D-18 (close the gateway leak points — keep the seam honest):** Three places the provider can leak past `gateway.py`: (1) signature verify needs raw body + secret → put `verify()` in the gateway; (2) body parsing differs by provider (Resend = metadata-then-API-fetch, Postmark = self-contained JSON, Mailgun = multipart) → `parse_inbound` owns ALL of it, including Resend's second call (D-01a); (3) **normalize** headers into `InboundEmail` (`message_id`/`in_reply_to`/`references` as typed fields) so NO downstream code indexes a raw provider headers blob — same for the reply path (caller passes a normalized reply-to-message-id, not a provider object).
- **D-19 (Docker = uv-in-image, multi-stage):** Use `uv sync --frozen --no-dev` in the image (lockfile is the single source of truth, honors the "never a tracked requirements.txt" rule). The export-requirements approach reintroduces exactly the artifact uv exists to avoid + adds a drift surface. Builder stage runs `uv sync` to a venv; runtime stage copies it. Run via `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- **D-20 (health endpoint split):** A **liveness** route with NO DB hit (for Render's deploy health check — a brief Supabase blip must not fail the deploy) PLUS a **readiness / keep-alive** route that does the `SELECT` (D-16's cron target). For a portfolio project one DB-touching route is acceptable; the split is the "correct" answer if asked.
- **D-21 (eval chart must be a baked-in STATIC asset):** The FS is ephemeral, so the eval page serves the committed `eval/chart.svg` from the image — NOT a runtime-regenerated file. (The existing `@app.get("/eval/chart.svg")` route exists; confirm it serves the committed asset, not a regen.) Mirror the D-11a logic: commit SVG + PNG.

### Claude's Discretion

- **Exact storage spot for the dedup key + the durable References chain (D-13/D-14)** — a dedicated table vs. reusing `email_messages.message_id` UNIQUE / `references_header`; the planner decides after reading the reply path. Only the *mechanism* (insert-or-skip on provider Message-ID as step one; rebuild threading from a persisted row) is locked.
- **Dockerfile layer details** (base tag pin, exact multi-stage layout, caching) — D-19 fixes the *approach* (uv-in-image, multi-stage, `--no-dev`); the layout is the planner's.
- **`render.yaml` vs dashboard-only config**, exact env-var names, and `sync:false` secret handling — D-09 fixes that secrets live in Render env and never flash on camera; the encoding is the planner's.
- **Health route paths + exact `SELECT`** (D-16/D-20) and keep-alive cron cadence (daily vs twice-weekly) — the *split* (no-DB liveness + DB readiness) and the *target* (Render route that runs a query) are locked; the rest is discretionary.
- **README prose, section ordering below the two-tier split, and the demo embed format** (GIF vs linked video) — D-11 fixes the two-tier shape + prominent disclaimers; the copy is the planner's.
- **Mermaid diagram exact node set** — D-11a fixes "stages + two pause states + the code gate" and "both Mermaid + image"; the drawing is the planner's.
- **Demo-reset script form** (SQL script vs `python -m` helper vs fresh-shorthand-per-take) — D-07 fixes that it MUST exist before recording; the form is the planner's.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap (the locked scope)
- `.planning/REQUIREMENTS.md` — **OPS-01, OPS-02, OPS-03, OPS-04** (full text), the Out-of-Scope table (state withholding / persisted PDFs / auth stay out), and the locked disclaimer content under CALC-04/05 (OBBBA exclusion, Additional Medicare unmodeled).
- `.planning/ROADMAP.md` §Phase 6 — the goal + the 3 success criteria + the **Build Notes (uv + Docker)** block (the two Docker patterns; D-19 selects uv-in-image). Note the `--no-dev` + `0.0.0.0:$PORT` reminders.
- `.planning/PROJECT.md` — §Context (the two pause states; the `status` column IS the orchestration engine; the gateway-agnostic + fixture-first sequencing — provider wired LAST; the "Send test email" button doubles as demo + live-email fallback, which D-04 now uses); §Constraints (single Render service, Supabase pooler, one operator gate, no auth); the Render-free realities paragraph.
- `./CLAUDE.md` — the **uv Tooling Rule** (the Phase 6 Docker export/`uv sync` guidance), §8 (Render Docker specifics: `$PORT`/`0.0.0.0`, 15-min sleep, ephemeral FS, 750 hrs, keep-alive must ping HTTP), the Supabase pooler rows in "What NOT to Use" (direct host is IPv6-only → use pooler 6543), and §5 FICA / Additional-Medicare disclaimer text for the README.

### Prior-phase context that constrains Phase 6
- `.planning/phases/02-walking-skeleton/02-CONTEXT.md` + `.planning/phases/02.1-deterministic-decisioning/02.1-CONTEXT.md` — the orchestrator state machine, the two pause states, the deterministic decisioning the demo showcases, and the clarify→reply→resume loop the real provider must not break.
- `.planning/phases/05-dashboard-delivery/05-CONTEXT.md` — **D-13c** (the crash-safe `send_state='reserved'`-before-send ordering the live provider wiring must honor — D-14 makes it real for threading too), the `claim_status` CAS (guards sends, NOT the inbound decision re-run that D-13 closes), the alias write-side loop (the demo's beat 3 + the D-07 reset need), and the DASH-05 "Send test email" path D-04 records against.
- `.planning/phases/03-harden-the-calc/03-CONTEXT.md` — the Pub 15-T disclaimers (OBBBA, no Additional Medicare) the README must reproduce verbatim.
- `.planning/phases/04-the-eval-the-proof/04-CONTEXT.md` — the committed `eval/summary.json` + `eval/chart.svg` the README embeds and the dashboard serves as a static asset (D-21).

### Code Phase 6 wires / extends (verified — file:line)
- `app/email/gateway.py:27` `parse_inbound` (Resend two-step lands here — D-01a/D-18) / `:40` `send_outbound` (already has the D-13c `send_state='reserved'` forward-compat stub the live provider activates). **The provider should ideally touch ONLY this file** (D-18 keeps it honest).
- `app/main.py:158` `@app.post("/webhook/inbound")` (D-13 dedup + D-17 signature verify go HERE, as step zero); `:780` `/demo/send-test` (the DASH-05 button D-04 records against); `:598` `@app.get("/eval/chart.svg")` (confirm it serves the committed asset, not a regen — D-21). **NO health route exists yet** — D-20's liveness/readiness split is new work.
- `app/config.py:16` `Settings` (TWO LLM tiers + `database_url`; Phase 6 ADDS the Resend API key + webhook signing secret env vars — D-17).
- `app/db/supabase.py:46` (`prepare_threshold=None` on the pool — already correct, D-15a) + `app/db/bootstrap.py:96` (`prepare_threshold=None` for schema apply; D-15b says run migrate/seed over the SESSION pooler 5432, not 6543).
- `app/models/contracts.py:35` `InboundEmail` (the normalized target for D-18: `message_id`/`in_reply_to`/`references_header`/`body_text` as typed fields — no raw provider blob downstream).

### External provider docs (verified Jun 2026 — read before wiring)
- Resend receiving: `https://resend.com/docs/dashboard/receiving/introduction` — `email.received` is metadata-only; body via `resend.emails.receiving.get(email_id)` (D-01a).
- Resend webhooks/verify + threading guidance: `https://resend.com/blog/inbound-emails`, `https://resend.com/blog/webhooks` — signing secret + `resend.webhooks.verify()` (D-17); "set In-Reply-To + append to References yourself" (D-01b/D-14).
- Postmark pricing (the rejected option, for the record): `https://postmarkapp.com/pricing` — inbound locked to Pro (~$16.50/mo)+; free Developer tier is outbound-only (D-01/D-02).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **The `EmailGateway` seam (`app/email/gateway.py`)** is the entire provider abstraction by design — two functions, provider swaps in here. The D-13c `send_state='reserved'`-before-send ordering is ALREADY stubbed for exactly this moment.
- **`prepare_threshold=None`** is already set on the pool + bootstrap — the Supavisor runtime prepared-statement gotcha is solved; Phase 6 only adds the 5432-for-migration nuance (D-15).
- **`email_messages.message_id` UNIQUE** (FOUND-02 idempotency index) is a candidate home for the D-13 inbound dedup — the mechanism may already mostly exist; the planner confirms whether the webhook actually dedups on it BEFORE running the pipeline.
- **`@app.get("/eval/chart.svg")` + the committed `eval/chart.svg`/`summary.json`** already serve the proof artifacts — D-21 just confirms they're served as static baked-in assets (no regen on the ephemeral FS).
- **The DASH-05 "Send test email" button (`/demo/send-test`)** is the controllable demo path D-04 records the thesis beats against — already built, doubles as the live-email fallback per PROJECT.md.
- **The alias write-side loop (Phase 5)** is what makes beat 3 ("learns") work — and is exactly why the D-07 reset script is needed between takes.

### Established Patterns
- **Provider-agnostic-behind-one-seam** — keep ALL Resend specifics (two-step fetch, signature verify, header normalization) inside `gateway.py` so the fixture path and every caller are unchanged (D-18). This is the project's load-bearing decoupling.
- **Crash-safe intent-before-side-effect** (D-13c) — write the durable record BEFORE the irreversible external call; D-14 extends it to threading state.
- **`uv run` / `uv sync --frozen --no-dev`** for everything; the lock is authoritative — Docker honors this (D-19), never a tracked `requirements.txt`.
- **BLOCKING human checkpoints for real-world integration** (live DB, live LLM in prior phases) — Phase 6 continues it for the Render deploy (D-09) and the email round-trip (D-09b).
- **Draft-tier-with-deterministic-floor** for any LLM-drafted email — unchanged; the live provider only changes transport, not composition.

### Integration Points
- **Webhook handler (`/webhook/inbound`)** gains TWO new step-zero actions: signature verify (D-17) then inbound dedup (D-13) — both BEFORE any extraction/pipeline work.
- **`parse_inbound`** gains the Resend two-step (webhook metadata → body fetch) + header normalization (D-01a/D-18).
- **`send_outbound`** activates the D-13c reserved-before-send ordering against the real Resend send API + rebuilds threading from the persisted References chain (D-14).
- **New Dockerfile + render config + GitHub Actions keep-alive workflow** (the `.github/workflows/` dir already exists with `eval.yml` — the keep-alive is a second workflow).
- **New health routes** (liveness no-DB + readiness with-`SELECT`) wired into `app/main.py` (D-20) — the keep-alive cron target (D-16).
- **Production Supabase** — schema + seed applied via the 5432 session pooler (D-15); runtime via 6543 (locked).

</code_context>

<specifics>
## Specific Ideas

- **The free-stack ethos is a value, not a recruiter checkbox** — the user chose Resend to hold the free line over Postmark Pro's cleaner integration. If Resend's two-step fetch or self-owned threading proves painful in practice, Postmark Pro (~$16.50/mo) is the documented, defensible escape hatch (D-02) — "I paid for the lower-bug path on a money-correctness project" is a fine story. Surface that escape hatch to the user; don't silently eat pain.
- **The demo's hero artifact is the RECORDING, not the live link** (D-04/D-11). The live URL is real and deployed (proven once via D-09b) but is "bonus, may take ~30s to wake." Recording the thesis beats off the deterministic `/demo/send-test` button means a provider hiccup or cold-dyno latency never lands mid-take. Prove transport once; record on the controllable path.
- **The single highest-value line of code in the phase** is the inbound dedup on the provider Message-ID (D-13) — it closes a false-process hole the stub structurally hid, on a project whose entire thesis is "never wrong on a money-moving decision." It is invisible until a real at-least-once provider is wired, which is now.
- **"What stops a fake inbound?"** (D-17 signature verify) and **"what happens on a duplicate delivery?"** (D-13 dedup) are the two interviewer questions a money-themed public webhook invites — building both is cheap and turns a gap into a talking point.
- **Beat 3 poisons beat 2 on a second take** (D-07) — the learned alias persists to prod, so the reset script is a hard pre-recording dependency, not polish. Build it first.
- **Isolate the deploy failure classes** (D-08a) — prove the pooler/IPv4/prepared-statement layer from the laptop before the container/`$PORT`/cold-start layer on Render, so a failed thin deploy points at one layer, not a fog of two.

</specifics>

<deferred>
## Deferred Ideas

- **Subject-token threading fallback** → built ONLY if the D-09b verify round-trip shows headers don't survive, or as a fast-follow if a post-demo poke reveals breakage (esp. an Outlook/Exchange sender). The spec is pre-locked in D-03a so a later build doesn't re-litigate ordering. NOT built proactively (D-03).
- **Postmark Pro (paid, self-contained inbound)** → the documented escape hatch if Resend's free two-step/own-threading proves painful (D-02). Not chosen now; recorded so a swap is informed.
- **Full per-week biweekly OT detection, larger eval corpus, synthetic generator, state withholding, mid-pipeline resume, dashboard auth, spreadsheet attachments** → already v2 / Out-of-Scope in REQUIREMENTS.md + PROJECT.md; not reopened.
- **Continuous-take unedited recording** → rejected in favor of pre-warm + light cuts on the controllable path (D-04/D-05); a continuous take is hostage to whatever latency the dyno/APIs serve that take.
- **Agent-driven Render deploy** → rejected (D-09): account creation + secret injection need a human; a half-finished deploy is worse than a clean artifact handoff.

### Reviewed Todos (not folded)
None — `.planning/STATE.md` "Pending Todos" is empty and `todo.match-phase 6` returned no matches. The Phase-6 research flags in STATE.md "Blockers/Concerns" (real gateway payload shape / signing secret / reply field) are RESOLVED by this discussion: D-01a (Resend two-step payload), D-17 (signing secret + verify), D-18 (normalized reply field). The two pulled-forward build-time-guidance items (threading round-trip; prove Render+Supabase early) are addressed by D-09b and D-08/D-08a respectively.

</deferred>

---

*Phase: 6-Real Integration & Ship*
*Context gathered: 2026-06-23*
