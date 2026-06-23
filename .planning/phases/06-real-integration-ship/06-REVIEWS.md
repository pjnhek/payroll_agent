---
phase: 6
reviewers: [codex]
reviewed_at: 2026-06-23
review_round: "demo-1"
scope: interactive-demo expansion (06-08 + gate runbooks); integration plans 06-01..07 converged separately
plans_reviewed: [06-01-PLAN.md, 06-02-PLAN.md, 06-03-PLAN.md, 06-04-PLAN.md, 06-05-PLAN.md, 06-06-PLAN.md, 06-07-PLAN.md, 06-08-PLAN.md]
codex_cli_version: codex-cli 0.135.0
overall_risk: HIGH until outbound-suppression + sender-state decoupling fixed
---

# Cross-AI Plan Review — Phase 6 Interactive Demo (Round demo-1)

## Codex Review

### Summary
06-03/06-05 runbooks mostly execution-ready (one MEDIUM gap in 06-05 DB-query self-containment). **06-08 is NOT execution-ready** — two HIGH blockers around outbound email and shared sender state, plus a thread-view linkage bug.

### Strengths
- Two-path narrative correct; stateless-compose is the right instinct.
- Business names allowlisted; fixture paths server-side; alias rationale presentation-only.
- 06-05 A5 gate strong (DB evidence, explicit branch, subject-token fallback).

### Concerns

**HIGH — 06-08 Task 2: `/demo/compose` is NOT actually "no email/SMTP".** Compose schedules the real `_run_pipeline`; on clarification/delivery the orchestrator calls `gateway.send_outbound(...)`, which after 06-04 is REAL Resend. Compose stamps seed `.example` senders, so a clarification would try to send real email to `hr@metrodeli.example` — violating the Path-1 "no SMTP" requirement AND the Resend free-tier (sends only to account-owner). Impact: clarify beat can error before `awaiting_reply`; no outbound clarification row → `/simulate-reply` has no clarification message to resume against. **[VERIFIED: pipeline calls gateway.send_outbound on clarify/deliver; 06-04 makes it real Resend.]** Fix: an in-app/demo delivery sink for compose runs — write the outbound `email_messages` row (synthetic Message-ID, `send_state='sent'`) but DO NOT call Resend. Test: compose clarification does NOT call `resend.Emails.send` and still exposes a clarification message + simulate-reply path.

**HIGH — 06-08: stateless compose still depends on mutable global sender state.** Compose uses `_SEED_CONTACTS[business_name]` → `find_business_by_sender(seed_addr)`. But `/demo/bind` mutates `businesses.contact_email` for the target business to `pjnhek@gmail.com`. Once Metro is bound, `hr@metrodeli.example` NO LONGER resolves to Metro. Also breaks the reply loop: `_route_reply` re-validates the reply `from_addr` via `find_business_by_sender` (the FIX-5 spoof guard) — if bind moved that business off its seed contact, the synthetic reply is spoof-rejected. **[VERIFIED: main.py _route_reply:253 re-resolves from_addr; FIX-5 guard:258 rejects on mismatch; bind mutates businesses.contact_email.]** Impact: operator Path-2 arming BREAKS recruiter Path-1 for the same business, and silently fails the clarify resume. Fix: STOP mutating canonical `businesses.contact_email` for demo binding — use a SEPARATE demo/operator sender-binding (alias/lookup table or route-specific mapping) so seed contacts stay stable; OR make compose create runs by allowlisted business_id and have simulate-reply validate against the run's source email, not current `businesses.contact_email`.

**MEDIUM — 06-08: thread view misses the original inbound.** Ingest inserts the source inbound `email_messages` row with `run_id=NULL`; the run links it via `payroll_runs.source_email_id`. `load_thread_messages(run_id) WHERE run_id=%s` misses the first/most-important inbound. **[VERIFIED: repo.py joins source via pr.source_email_id:250,281; inbound run_id nullable at ingest.]** Fix: backfill `email_messages.run_id` after `create_run`, OR `load_thread_messages` includes `em.id = payroll_runs.source_email_id OR em.run_id = %s`. Add a repo test for the real source-email linkage.

**MEDIUM — 06-08: `/demo/bind` rendered on the public landing page** despite the "unlinked" residual claim. As written, index.html renders the operator bind form on the public page → easier accidental/malicious rebind, compounding the sender-state HIGH. Fix: remove it from the recruiter landing page; keep an unlinked operator URL or a manual runbook step; at minimum 06-05 must require "bind immediately before Path 2 and verify the selected business."

**MEDIUM — 06-05 A5 runbook not fully self-contained for DB queries.** It gives SQL but not how to run it post-/clear. Fix: include exact Supabase SQL Editor instructions or copy-paste `uv run python -c` commands using `DATABASE_URL` per A5 query.

**LOW — `bind_demo_business` rowcount with FakeConnection.** Plan returns `rowcount >= 1` but FakeConnection has no rowcount. Extend the fake or avoid rowcount assertions.

**LOW — picker/roster update underspecified.** "selecting a business renders that roster" but "no JS needed" — use a GET form with onchange-submit, or render all rosters and toggle.

### Risk
**HIGH** until outbound-suppression + sender-state are fixed — the recruiter clarify path can call real Resend and/or fail the spoof guard after an operator bind, threatening the demo's core correctness.

---

## Orchestrator Triage (Claude Code)

Both HIGHs + the thread-view MEDIUM are VERIFIED against real code — they're genuine, and HIGH-2 invalidates my earlier "stateless compose" claim (compose reads `businesses.contact_email` transitively through `find_business_by_sender`, which bind mutates). Root cause of HIGH-2: **demo binding mutating the canonical `businesses.contact_email` was the wrong mechanism.** Driving a Pass.

**REAL — fix in the Pass:**
1. **HIGH-1 — record-only delivery sink for Path-1 compose.** Compose-created (in-app) runs must NOT hit real Resend on clarify/deliver. Add a demo/record-only mode: the pipeline (or a delivery flag on the run) writes the outbound `email_messages` row (synthetic Message-ID, `send_state='sent'`) WITHOUT calling `gateway.send_outbound`'s Resend path. The clarification message must still appear (so the in-page reply + simulate-reply works). Tests: a compose run that clarifies does NOT call `resend.Emails.send`, AND a clarification email_messages row exists + simulate-reply resumes it. Decide the cleanest seam (a run-level `delivery_mode`/`record_only` flag set by /demo/compose and honored where the pipeline would call send_outbound; or a demo gateway shim). Keep Path-2 (real email) on the real Resend send.
2. **HIGH-2 — decouple operator binding from `businesses.contact_email` (the architectural fix that dissolves the stomp).** STOP rewriting the canonical contact. Instead: (a) compose creates the run by allowlisted **business_id** directly (not by stamping a seed sender that must resolve back), so Path-1 routing never depends on `businesses.contact_email` at all; AND (b) the operator Path-2 binding becomes a SEPARATE sender→business mapping (a small `demo_sender_binding` lookup, or a route-specific operator mapping) that the webhook/_route_reply consults FOR THE OPERATOR EMAIL ONLY — leaving every seed `.example` contact stable. Then: binding Metro for Path-2 never changes what `hr@metrodeli.example` resolves to, recruiter Path-1 for Metro keeps working, and the spoof guard for compose runs validates against the run's own source business_id, not a mutated contact. Update `find_business_by_sender` usage / `_route_reply` so the operator-email binding is an ADDITIVE lookup, not a destructive contact rewrite. Add regression tests: bind Metro then compose Metro (routes to Metro); bind Metro then simulate-reply a Metro compose run (resumes, not spoof-rejected).
3. **MEDIUM — thread view includes the source inbound.** `load_thread_messages` must include the run's source email: `WHERE em.run_id = %s OR em.id = (SELECT source_email_id FROM payroll_runs WHERE id=%s)` (or backfill run_id after create_run). Add the repo test.
4. **MEDIUM — /demo/bind off the public landing page.** Remove the bind form from index.html (recruiter UI). Keep `/demo/bind` as an unlinked operator route (reachable directly) — consistent with the user's decision. 06-05 runbook: "bind immediately before Path-2 and verify the selected business resolves."
5. **MEDIUM — 06-05 A5 self-contained DB queries.** Add copy-paste `uv run python -c "..."` (using DATABASE_URL) or Supabase SQL Editor steps for each A5 check, so the gate stands alone post-/clear.
6. **LOW — FakeConnection rowcount; picker/roster JS.** Extend the fake or drop rowcount assertions; specify a GET-form onchange-submit (or render-all-and-toggle) for the roster — keep it no-build/vanilla per the stack.

**Suggestion to adopt:** add body/subject length limits on `/demo/compose` to cap public LLM/DB abuse (cheap guard on a public input that hits the paid-ish LLM + DB).

## Next step
Replan (the Pass) to fix HIGH-1 + HIGH-2 + the MEDIUMs, re-verify, then re-review with Codex (round demo-2). HIGH-2's decoupling is the load-bearing fix; HIGH-1's record-only sink makes Path-1 genuinely no-SMTP.
