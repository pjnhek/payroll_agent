---
phase: 6
reviewers: [codex]
reviewed_at: 2026-06-23
review_round: 2
plans_reviewed: [06-01-PLAN.md, 06-02-PLAN.md, 06-03-PLAN.md, 06-04-PLAN.md, 06-05-PLAN.md, 06-06-PLAN.md, 06-07-PLAN.md]
codex_cli_version: codex-cli 0.135.0
overall_risk: HIGH (round-1 HIGHs resolved; new deeper integration HIGHs surfaced)
prior_round: round-1 06-REVIEWS committed at 9619ffe (superseded by this file)
---

# Cross-AI Plan Review — Phase 6 (Round 2)

> Round 1's 9 findings were incorporated (commit f5bacee) + 3 follow-on blockers closed; plan-checker
> re-verified PASSED. This is the second independent Codex pass on the revised plans.

## Codex Review (Round 2)

### Summary
Not yet execution-ready. The revised plans are much stronger and the round-1 HIGHs are materially resolved (Docker `.venv/bin/uvicorn`; dual-path fixture preservation; explicit dedup short-circuit; send-failure→failed; reset `--confirm`+FK-safety+reseed; Mermaid+mandatory PNG). But new thesis-critical gaps remain that can break real reply routing, weaken webhook authenticity, or make the live demo fail once the real provider is active.

### Strengths (round-1 fixes confirmed)
- 06-02 Docker runtime fixed cleanly (builder `uv sync --frozen --no-dev`; runtime `.venv/bin/uvicorn` with `$PORT`).
- 06-04 separates Resend-envelope parsing from canonical fixture parsing (protects the fixture/dev path).
- 06-04 dedup is explicit: insert-or-skip before enqueueing pipeline work.
- 06-04 adds failed-state handling around provider send failures (no more stranded reserved row).
- 06-06 reset script safer: explicit `--confirm`, FK-aware cleanup, reseed to reset learned aliases.
- 06-06 README/artifact consistency mostly fixed: Mermaid source + mandatory PNG.

### Concerns
- **HIGH — Public webhook still has an unsigned canonical bypass (06-04 Task 2).** Canonical `InboundEmail` payloads skip signature verification entirely while only Resend-shaped payloads require Svix verify. That leaves `/webhook/inbound` publicly forgeable in prod: an attacker POSTs the canonical shape with a spoofed `from_addr` matching a business contact and bypasses D-17. Fix: gate unsigned canonical POSTs behind `ALLOW_UNSIGNED_FIXTURES=true` too; keep it false and absent from Render; tests enable the flag explicitly.
- **HIGH — Outbound reply routing may store the wrong Message-ID (06-04 Task 1).** `send_outbound` stores a synthetic `message_id`, sends via Resend, stores the provider id separately, returns the synthetic id. But reply routing matches incoming `In-Reply-To`/`References` against `email_messages.message_id`. If Resend sends with its OWN RFC Message-ID, client replies reference Resend's ID, not the synthetic one in the DB → clarify→reply→resume fails. The A5 human confirmation in 06-05 is too late to compensate for a schema/repo design that assumes synthetic IDs. Fix BEFORE implementation: either (a) set the outbound `Message-ID` header to the synthetic ID and verify Resend preserves it, or (b) add a separate stable internal key and store the ACTUAL outbound RFC Message-ID in `email_messages.message_id`, then route replies on that.
- **HIGH — Real inbound round-trip will likely stop at `unknown_sender` (06-05 Task 1).** The user sends from a personal email, but production seed data uses `.example` business-contact emails and `find_business_by_sender` is exact-match → the real inbound is logged and stopped, not processed. Same issue hits the live demo: `/demo/send-test` fixtures use `.example` senders, and live `send_outbound` may attempt to email `.example` recipients. Fix: add a production demo sender/recipient setup step (update one seeded business contact email to the exact real sender used for the round-trip; use demo fixtures for that same business).
- **HIGH — Real confirmation emails may drop PDF attachments (06-04 Task 1).** The `resend.Emails.send` payload includes `from`/`to`/`subject`/`text`/`headers` but NOT `attachments`. Existing `_deliver` passes generated PDF bytes into `gateway.send_outbound`. As written, the confirmation path silently loses paystub PDFs. Fix: add attachment mapping to the Resend send payload + a gateway test asserting PDFs pass through.
- **MEDIUM — Reply-routing test still too mocked (06-01/06-04).** `test_inbound_reply_routes_to_correct_run` monkeypatches `repo.find_awaiting_reply_for_header` to return a fake run id — proves the route reacts to a mocked match, not that the stored outbound row + normalized headers + SQL predicate + route work together. Add one test that stores an outbound row and posts a reply whose `In-Reply-To` matches it WITHOUT monkeypatching the matcher.
- **MEDIUM — Durable References chain only partially durable (06-04 Task 1).** Loading the most recent sent outbound `references_header` and appending the new `in_reply_to` does not persist a true per-thread chain including inbound reply headers; multi-turn clarification can lose parts of the chain. Weaker than D-14's "full References chain per thread." (May not break the 60–90s demo.)
- **MEDIUM — Keepalive workflow hides failure (06-02 Task 2).** `curl -sf ... || echo "Ping failed..."` makes the workflow green even when the ping failed or `RENDER_URL` is missing → OPS-03 silently stops. Fix: fail the workflow on missing URL or failed curl.
- **MEDIUM — Gateway test assumes fixed SQL order D-14 violates.** `test_send_outbound_reserved_before_sent_ordering` expects `fake_conn.executed[0]/[1]` positions, but D-14 adds a DB READ before the reserved insert. Assert RELATIVE order (reserved insert before provider send; sent/failed update after) instead of absolute positions.
- **LOW — 06-03 has a Resend/header must-have before Resend exists.** "three threading headers confirmed on manual raw payload logging" is a 06-05 activity; move it out of 06-03 so the thin-deploy gate isn't blocked on impossible evidence.
- **LOW — Address normalization underspecified.** Real provider `from` may include display names; `parse_inbound` should `email.utils.parseaddr` before `find_business_by_sender`, or real known senders get rejected.

### Risk Assessment: HIGH
Close but not execution-ready. The remaining HIGHs can break the public webhook trust boundary, the real clarify→reply→resume loop, the live email round-trip, and PDF delivery — core Phase 6 success criteria, not polish.

---

## Orchestrator Triage (Claude Code)

These round-2 findings are materially DEEPER than round-1 — Codex confirmed the round-1 HIGHs are resolved and found integration-semantics bugs the internal plan-checker structurally can't (it checks plan quality, not live-provider behavior). I judge ALL four HIGHs and three of four MEDIUMs as REAL and actionable. Driving a Pass-2 replan (`/gsd-plan-phase 6 --reviews`).

**REAL — fix in Pass 2:**
1. **HIGH — Outbound Message-ID identity (06-04).** The strongest finding. Cross-check against `contracts.py`/`repo.py`/the reply-routing code: decide the ownership rule. Cleanest given Resend lets you SET the `Message-ID` header (D-01b/A5): mint the synthetic RFC Message-ID, pass it as the outbound `Message-ID` header to `resend.Emails.send`, store THAT same id in `email_messages.message_id` (what reply routing matches on), and treat Resend's returned provider id as a separate audit value. Promote A5 from "confirm at 06-05" to a *design assumption the plan commits to*, with 06-05 verifying the header survived (not discovering the design was wrong). This removes the "synthetic-vs-provider id" mismatch entirely.
2. **HIGH — `.example` sender vs real round-trip + demo (06-05/06-06/06-07).** Add an explicit "production demo identity" setup: update one seeded business's contact email to the real sender address used for the D-09b round-trip (and the demo), so `find_business_by_sender` matches. Make it a documented step in 06-05 (round-trip) and ensure the demo-reset/seed (06-06) keeps that identity. Confirm `/demo/send-test` uses a fixture whose sender matches a seeded business.
3. **HIGH — PDF attachments dropped (06-04).** `send_outbound` must map the paystub PDF bytes `_deliver` passes into the `resend.Emails.send` `attachments` param (base64/content per the resend SDK shape — confirm against RESEARCH.md / the SDK). Add a gateway test asserting attachments are forwarded. This is a HITL-03 regression guard on the real provider.
4. **HIGH — Unsigned canonical bypass (06-04).** Tighten: ANY unsigned inbound (canonical shape included) is rejected in prod unless `ALLOW_UNSIGNED_FIXTURES=true`. Keep the flag default-False and absent from render.yaml (already enforced). Update the fixture tests + the DASH-05/`/demo/send-test` path to set the flag in the dev/test env. Confirms D-17 covers the whole public surface, not just Resend-shaped payloads.
5. **MEDIUM — Reply-routing test still mocked (06-01/06-04).** Add a test that inserts a real outbound row (FakeConnection or live-DB integration) and posts a reply whose `In-Reply-To` matches, WITHOUT monkeypatching `find_awaiting_reply_for_header` — exercises the real SQL predicate + header normalization end to end.
6. **MEDIUM — Positional SQL assertion (06-01).** Change `test_send_outbound_reserved_before_sent_ordering` to assert RELATIVE order (reserved-insert before provider-send; sent/failed-update after), not `executed[0]/[1]` absolute indices — D-14's chain-load read now precedes the reserved insert.
7. **MEDIUM — Keepalive hides failure (06-02).** Remove the `|| echo` swallow; fail the job on missing `RENDER_URL` or non-2xx (`curl -f` + check the URL is set). OPS-03 must go red when the ping actually fails.
8. **LOW — 06-03 threading-header must-have (move to 06-05).** The three-headers-confirmed evidence belongs at the round-trip gate, not the thin-deploy gate.
9. **LOW — parseaddr normalization (06-04).** `parse_inbound` runs `email.utils.parseaddr` on the provider `from` before `find_business_by_sender`.

**Partially-defer (document, don't over-build):**
- **MEDIUM — fully-durable multi-turn References chain (06-04).** D-14's "full chain per thread" is stronger than "last sent + append." The demo is single-turn so the current design suffices for the recording, but it's a real gap vs the locked decision. Fix if cheap (persist/accumulate the inbound reply's References too, not just the last outbound); otherwise narrow the D-14 must_have wording to the implemented scope and document the multi-turn limitation explicitly (don't claim full-chain if only last-hop is built). Planner's call on cost.

## Consensus Summary
Single reviewer (Codex) + orchestrator triage.

### Agreed Strengths
Round-1 HIGHs are resolved (Docker, dual-path, dedup, send-failure, reset, docs). Architecture + sequencing + human gates remain sound.

### Agreed Concerns (priority → Pass 2)
1. Outbound Message-ID identity breaks reply routing (clarify→reply→resume) — **thesis-critical**.
2. `.example` seed senders break the real round-trip + live demo.
3. PDF attachments dropped on the real send path.
4. Unsigned canonical webhook bypass = prod forgery hole.
5. Reply-routing test too mocked; positional SQL assertion; keepalive hides failure.

### Divergent Views
None (single reviewer). Round-1 findings explicitly marked resolved by Codex.

### Next step
`/gsd-plan-phase 6 --reviews` (Pass 2). Per the convergence directive, a 3rd Codex review follows; a Pass-3 replan runs only if that review still shows blockers.
