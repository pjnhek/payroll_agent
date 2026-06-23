# Phase 6: Real Integration & Ship - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-23
**Phase:** 6-Real Integration & Ship
**Areas discussed:** Email provider + threading, Demo recording strategy, Deploy scope & verification, README + architecture diagram

> **Note on flow:** the area-selection question initially routed into a "clarify" path; the user confirmed they had selected all four areas to discuss. After the four areas were discussed, the user requested a shareable decision summary to get an external review in a separate chat. That review returned substantive findings; the load-bearing factual claims (Postmark free-tier inbound exclusion; Resend metadata-only inbound) were independently web-verified by the agent, and three user decisions were re-surfaced with the new facts and changed.

---

## Area 1 — Email provider

| Option | Description | Selected |
|--------|-------------|----------|
| Postmark inbound+outbound | Best header fidelity, self-contained JSON, free hash@ address | (initially leaning) |
| Mailgun routes | Inbound routes, sandbox recipient restriction | |
| n8n / self-host relay | Max control, another moving part | |
| You pick / research first | Defer to research; lock criteria only | ✓ (first pass) |

**User's choice (first pass):** "You pick / research first" — lock criteria (free tier, preserves RFC threading headers cleanly, simple webhook + send API).
**Revised after external review + web verification:** **Resend (hold the free line).** Web-verified: Postmark inbound is locked to Pro (~$16.50/mo); free Developer tier is outbound-only — fails the "free tier" criterion. Resend is free (3k/mo) and same-provider in/out, but inbound is metadata-only (parse_inbound becomes two-step) and you own the References chain.
**Notes:** Postmark Pro recorded as the documented paid escape hatch if Resend's two-step/own-threading proves painful.

## Area 1 — Threading risk

| Option | Description | Selected |
|--------|-------------|----------|
| Verify-first, header chain primary | Send real email + reply, confirm headers intact, then trust header chain | ✓ |
| Add subject-token fallback | Belt-and-suspenders run token in subject | |
| Header chain only, document risk | Trust provider, note risk in README | |

**User's choice:** Verify-first, header-chain primary.
**Revised after review:** Held — verify-first ONLY; build the subject-token fallback only if the verify round-trip fails. New fact acknowledged: the verify step only tests the agent's own mail client; the sender's client (Outlook/Exchange) is the real `References`-mangling risk. Fallback spec pre-locked (opaque token, header-primary, fire-on-no-match-only) for a later build.

## Area 1 — Verify gate treatment

| Option | Description | Selected |
|--------|-------------|----------|
| Blocking human checkpoint | autonomous:false; provider not "wired" until human does the real round-trip | ✓ |
| Best-effort, non-blocking | Wire + ship; fix only if demo breaks | |
| Build a header-assertion test | Capture one real payload as a fixture + assert headers present | |

**User's choice:** Blocking human checkpoint.
**Notes:** Consistent with prior live-DB / live-LLM gates. Still stands after the demo venue switched to hybrid.

## Area 1 — Outbound provider

| Option | Description | Selected |
|--------|-------------|----------|
| Same provider in + out | One account/credentials; same system sets outbound threading | ✓ |
| Decouple in vs out | Different outbound sender behind send_outbound | |

**User's choice:** Same provider in + out.

---

## Area 2 — Demo venue

| Option | Description | Selected |
|--------|-------------|----------|
| Local "Send test email" button | Deterministic, no cold-start/latency on camera | |
| Live on Render, real email | Most authentic; exposes cold-start/latency/threading on camera | ✓ (first pass) |
| Hybrid | Live deploy proof + deterministic button beats | ✓ (revised) |

**User's choice (first pass):** Live on Render with real email.
**Revised after review:** **Hybrid.** Review argument accepted: all thesis beats exercise decide.py, which does not depend on live transport — a hard "real inbound IS the demo path" gate imports email-latency risk to prove something email doesn't prove. Prove transport once (verify gate), record beats on the controllable button path. The D-09b verify gate still stands.

## Area 2 — De-risk the recording

| Option | Description | Selected |
|--------|-------------|----------|
| Pre-warm + allow edit cuts | Ping URL 30–60s before, edit out latency | ✓ |
| One continuous take, no cuts | Maximally honest, hostage to that take's latency | |
| Live deploy proof + local beats | (this became the hybrid above) | (folded into D-04) |

**User's choice:** Pre-warm + allow edit cuts.
**Notes:** Review caution recorded — cuts landing on network boundaries can read as suspicious; favor the controllable button path over heavy cuts.

## Area 2 — Beats

| Option | Description | Selected |
|--------|-------------|----------|
| Clean → approve → deliver | End-to-end proof | ✓ |
| Unknown shorthand → clarify | The thesis | ✓ |
| Learns the alias | "Clarifies once, then learns" payoff | ✓ |
| Eval chart | ~5–10s credibility closing shot | ✓ |

**User's choice:** All three beats + eval closing shot.
**Notes:** Review surfaced the demo-reset trap — beat 3 persists the learned alias to prod, so a second take of beat 2 won't clarify; a reset script is a hard pre-recording dependency (D-07).

---

## Area 3 — Deploy sequence

| Option | Description | Selected |
|--------|-------------|----------|
| Thin deploy first, then wire | Prove Render+Supabase+$PORT+cold-start before the provider | ✓ |
| Build everything, deploy once | Fewer cycles, all unknowns stacked late | |
| Deploy locally in Docker first | Prove the container locally before Render | (folded as a pre-step) |

**User's choice:** Thin deploy first, then wire.
**Notes:** Review added a local pooler pre-check (5432 migrate/seed, 6543 runtime) BEFORE the Render deploy to isolate the failure class (D-08a) — a cheap step, not a fourth gate.

## Area 3 — Deploy gate

| Option | Description | Selected |
|--------|-------------|----------|
| Blocking human checkpoint | Agent prepares artifacts; human executes credentialed deploy | ✓ |
| Agent attempts deploy | CLI/API if creds present | |

**User's choice:** Blocking human checkpoint.

## Area 3 — Demo dependency on real inbound

| Option | Description | Selected |
|--------|-------------|----------|
| Real inbound is the demo path | Round-trip gate must pass before recording | ✓ (first pass) |
| Button is the safety net | Real inbound a passed gate; demo can use button | (effectively chosen via the D-04 hybrid switch) |

**User's choice (first pass):** Real inbound is the demo path.
**Superseded:** The later hybrid switch (D-04) means the demo records via the button; the email round-trip remains a passed BLOCKING gate (D-09b) but no longer hard-gates the recording.

## Area 3 — Supabase

| Option | Description | Selected |
|--------|-------------|----------|
| Stand up as part of this phase | Create project + schema + seed + connectivity | ✓ |
| Already exists | Only point DATABASE_URL at the pooler | |

**User's choice:** Stand up as part of this phase.

---

## Area 4 — README

| Option | Description | Selected |
|--------|-------------|----------|
| Recruiter-first narrative | Thesis + demo + chart + diagram up top | |
| Standard technical README | Conventional overview→setup→…→disclaimers | |
| Two-tier | Punchy recruiter top + "## For engineers" section | ✓ |

**User's choice:** Two-tier.

## Area 4 — Architecture diagram

| Option | Description | Selected |
|--------|-------------|----------|
| Mermaid in markdown | Diffable, native GitHub render | |
| Committed image (PNG/SVG) | Visual polish, binary asset to maintain | |
| Both | Mermaid source + exported image | ✓ |

**User's choice:** Both. (Review: commit SVG + PNG — GitHub SVG embedding is inconsistent.)

---

## External-review findings folded in as accepted (no user-preference conflict)

These came from the external review and were accepted on technical correctness:
- **Inbound webhook idempotency** keyed on the provider Message-ID (D-13) — highest-value fix.
- **Durable threading** from persisted state, not the last webhook (D-14).
- **psycopg3/pooler specifics** — prepared statements already off; migrate/seed over 5432 session pooler (D-15).
- **Keep-alive** — one cron hits a DB-touching Render health route to keep BOTH Render and Supabase warm (D-16).
- **Webhook signature verification** as step zero (D-17).
- **Gateway leak points** closed — verify()/two-step parse/header normalization inside gateway.py (D-18).
- **Docker = uv-in-image, multi-stage** (D-19).
- **Health-endpoint split** — no-DB liveness + DB readiness (D-20).
- **Eval chart = baked-in static asset** (D-21).
- **Local pooler pre-check** before the Render deploy (D-08a).
- **Demo-reset script** before recording (D-07).

## Claude's Discretion

- Storage spot for the dedup key + durable References chain (mechanism locked, spot open).
- Dockerfile layer details; `render.yaml` vs dashboard config + env-var names + `sync:false` secrets.
- Health route paths + exact `SELECT`; keep-alive cron cadence.
- README prose/ordering below the two-tier split; demo embed format (GIF vs video).
- Mermaid diagram exact node set.
- Demo-reset script form.

## Deferred Ideas

- Subject-token threading fallback — built only if verify fails or a post-demo poke reveals breakage (spec pre-locked in D-03a).
- Postmark Pro (paid) — documented escape hatch if Resend proves painful.
- Continuous unedited recording — rejected for pre-warm + light cuts on the controllable path.
- Agent-driven Render deploy — rejected; human executes the credentialed deploy.
- v2 / Out-of-Scope items (per-week biweekly OT, larger eval corpus, synthetic generator, state withholding, mid-pipeline resume, dashboard auth, spreadsheet attachments) — not reopened.
