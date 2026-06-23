---
phase: 6
reviewers: [codex]
reviewed_at: 2026-06-23
review_round: 5
plans_reviewed: [06-01-PLAN.md, 06-02-PLAN.md, 06-03-PLAN.md, 06-04-PLAN.md, 06-05-PLAN.md, 06-06-PLAN.md, 06-07-PLAN.md]
codex_cli_version: codex-cli 0.135.0
overall_risk: HIGH until the outbound Resend auth omission is patched; then MEDIUM
prior_rounds: rounds 1-4 (superseded). HIGH trend: 6 → 4 → 2 → 1 → 1.
---

# Cross-AI Plan Review — Phase 6 (Round 5)

> Round-4 HIGH (multi-business demo misrouting) is RESOLVED (Codex verified seed names + fixture file).
> Fifth independent Codex pass. One new HIGH (a live-path auth gap), 3 cheap MEDIUMs, 1 LOW (accepted).

## Codex Review (Round 5)

### Summary
Round-4 HIGH resolved: per-fixture `business_name` + DB `contact_email` lookup fixes the multi-business demo routing (verified seed business names + `eval/fixtures/04_unknown_shorthand_metro.json` exist). One remaining HIGH/blocker; plans not execution-ready until patched.

### Strengths
- D-13 inbound dedup explicit before pipeline enqueue (06-04 Task 2).
- D-17 unsigned public webhook surface materially closed (unsigned Resend AND unsigned canonical → 400 in prod).
- D-13c send ordering clear: reserved before provider call, failed on exception, sent only after success.
- PDF attachments explicitly carried into resend.Emails.send.
- Human gates correctly placed for Render/Supabase + real email threading.
- Demo routing has the right multi-business tests (06-06) + smoke checks (06-07).

### Concerns
- **HIGH — outbound Resend auth omission (06-04 Task 1).** `resend.api_key = get_settings().resend_api_key` is set only inside the Resend INBOUND parse path. It is NOT set before `resend.Emails.send`. The recording path uses `/demo/send-test`, which can send clarification/confirmation OUTBOUND without ever running the inbound parse path first. Unless the SDK is proven to auto-load `RESEND_API_KEY`, outbound sends fail live → the demo breaks. Fix: set `resend.api_key = get_settings().resend_api_key` at the START of `send_outbound`, plus a test that `Emails.send` sees the configured key. **[VERIFIED by orchestrator: the gateway is currently a stub — no `resend` import or api_key anywhere in app/; the auth setup is entirely new plan work, so single-path setup is a real risk to guard.]**
- **MEDIUM — stale A5 remediation wording (06-04 T-06-04-10).** Still says A5 remediation = "store Resend's returned RFC id in email_messages.message_id," contradicting 06-05 Branch B (which chose the D-03a subject-token fallback, NOT storing Resend's id). Remove the stale 06-04 wording.
- **MEDIUM — A5 evidence-source inconsistency (06-05).** Says `LOG_WEBHOOK_DEBUG_IDS` logs only header keys/IDs, but later tells the operator to find `in_reply_to=` in that log line. Make the DB `SELECT in_reply_to ... WHERE direction='inbound'` the PRIMARY A5 evidence, or log a sanitized `in_reply_to` explicitly.
- **MEDIUM — stray `paystubs` table name (06-06).** One must-have mentions `paystubs` in the reset deletion order, but the schema has only `paystub_line_items` (later task text is correct). Remove the stray `paystubs` reference. **[VERIFIED: schema.sql has paystub_line_items at :110; no `paystubs` table.]**
- **MEDIUM/LOW — "verify first" literalness (06-04).** Parses JSON before signature verification for signed Resend payloads. It still blocks before pipeline work (not thesis-critical), but to literally satisfy "verify first": if no svix headers + prod flag false → 400 before JSON parse; if svix headers present → verify raw body before parsing.
- **LOW — D-14 single-turn scope.** Acceptable for Phase 6; keep the multi-turn full-chain gap documented. (Already accepted/documented in prior rounds.)

### Risk Assessment
HIGH because the outbound Resend auth omission can break the live demo path. After that fix → MEDIUM (real-provider uncertainty + human-gated A5). Round-4 multi-business misrouting resolved.

---

## Orchestrator Triage (Claude Code)

Round-4 HIGH confirmed closed. The new HIGH is real and VERIFIED (gateway is a stub today; the resend auth setup is new plan work, and the demo's outbound-only path means inbound-path-only key-setting genuinely fails live). The 3 MEDIUMs are cheap consistency fixes; the "verify-first" item is a defensible tightening; the LOW is already accepted. Driving Pass 5 — the fixes are small and well-specified.

**REAL — fix in Pass 5:**
1. **HIGH — resend.api_key on the outbound path (06-04 Task 1).** Set `resend.api_key = get_settings().resend_api_key` at the START of `send_outbound` (not only in parse_inbound). Cleanest: set it once at module import / gateway init, OR at the top of BOTH parse_inbound and send_outbound (defensive, idempotent). Add a test asserting that calling send_outbound configures `resend.api_key` before `resend.Emails.send` is invoked (mock send, assert key set). This is the live-demo-critical fix.
2. **MEDIUM — stale A5 remediation in 06-04 T-06-04-10.** Rewrite that threat row's remediation to match 06-05 Branch B: A5 failure → D-03a subject-token fallback (NOT storing Resend's id in message_id). One source of truth for the A5 remediation.
3. **MEDIUM — A5 evidence source (06-05).** Make the DB `SELECT in_reply_to FROM email_messages WHERE direction='inbound' ORDER BY created_at DESC LIMIT 1` the PRIMARY/canonical A5 evidence. If LOG_WEBHOOK_DEBUG_IDS is also referenced, either drop the "find in_reply_to= in the log" instruction (it logs keys/IDs, not the value) or have it log a sanitized in_reply_to explicitly. One consistent evidence path.
4. **MEDIUM — stray `paystubs` (06-06).** Replace the `paystubs` mention in the reset must-have with `paystub_line_items` (the real table). VERIFIED: schema has paystub_line_items, no paystubs.
5. **MEDIUM/LOW — verify-before-parse (06-04).** Tighten the route: if a payload has no svix headers and the prod flag is false → 400 BEFORE json.loads; if svix headers present → verify the raw body BEFORE parsing. Keeps "verify first" literal (defense-in-depth; the current order already blocks before pipeline work, so this is a polish-grade hardening — apply if cheap).

**Accepted / no action:**
- LOW (D-14 single-turn) — already documented; no change.

## Consensus Summary
Single reviewer (Codex, 5 rounds) + orchestrator triage, code-verified.

### Convergence trend
6 → 4 → 2 → 1 → 1 HIGH. The count plateaued at 1, but each round's HIGH is a DIFFERENT, narrower, newly-exposed issue (round-4 = demo misrouting; round-5 = outbound auth) — not the same blocker recurring. This is the deep-review tail: each fixed layer exposes the next thinner one. Round-5's HIGH is a one-line auth fix + test. The remaining surface after Pass 5 is genuinely live-provider behavior that only the human deploy/round-trip gates (D-09/D-09b) can settle — not plannable away.

### Agreed Concerns (→ Pass 5)
1. Outbound `resend.api_key` not set on the send path → live demo send fails.
2. Stale A5 remediation wording (06-04) vs the D-03a decision (06-05).
3. A5 evidence-source inconsistency; stray `paystubs` table name.

### Next step
`/gsd-plan-phase 6 --reviews` (Pass 5) — close the outbound-auth HIGH + the consistency MEDIUMs. Whether a round-6 review follows is the user's call; the trend + the nature of the remaining surface suggest the plans are at/near the point where further review yields diminishing returns against the human gates.
