---
phase: 6
reviewers: [codex]
reviewed_at: 2026-06-23
review_round: "demo-2"
scope: interactive-demo expansion (06-08 + gate runbooks)
codex_cli_version: codex-cli 0.135.0
overall_risk: MEDIUM-HIGH until schema-apply step + _clarify alias-capture ordering fixed; then MEDIUM/LOW
prior: demo-round-1 (2 HIGH) — both CONFIRMED RESOLVED by Codex this round
---

# Cross-AI Plan Review — Phase 6 Interactive Demo (Round demo-2)

## Codex Review

### Summary
Both demo-round-1 HIGHs RESOLVED: HIGH-1 closed for /demo/compose (record_only=True; orchestrator gates both _clarify + _deliver send sites, writes synthetic outbound rows instead of calling Resend); HIGH-2 closed architecturally (compose routes by _SEED_BUSINESS_IDS; /demo/bind writes only demo_sender_bindings; find_business_by_sender uses the binding as an additive fallback after the stable seed-contact match). NOT fully execution-ready — 2 new HIGH + MEDIUM drift/runbook issues.

### Strengths
- Record-only outbound rows carry the right primitives (synthetic message_id, purpose, send_state='sent') → thread view, simulate-reply, purpose-scoped idempotency work.
- Additive binding no longer breaks recruiter Path-1 or seed .example senders.
- Source inbound thread inclusion via source_email_id fixes the half-thread UX.
- /demo/bind unlinked = correctly a no-auth residual, not HIGH.
- 06-05 A5 logic conceptually right (DB in_reply_to primary, not debug logs).

### Concerns

**HIGH-1 — production schema migration step is missing.** 06-03 applies Supabase schema (Wave 2) BEFORE 06-08 (Wave 3) adds `payroll_runs.record_only` + `demo_sender_bindings`. The DDL is idempotent in schema.sql, but there's no explicit NON-reset re-apply over the 5432 session pooler after 06-08 and before 06-05 uses /demo/bind. Deployed /demo/bind + /demo/compose can fail on missing table/column. **[VERIFIED: 06-03 Step 4 runs bootstrap --reset at the Wave-2 deploy gate, before 06-08's columns exist in code; no post-06-08 DDL apply step exists.]** Fix: add a post-06-08 / pre-06-05 step — `DATABASE_URL=<session-5432> uv run python -m app.db.bootstrap` (NO --reset), then verify record_only + demo_sender_bindings exist.

**HIGH-2 — record-only _clarify placement can skip alias capture (breaks Beat 3).** The action text places the record_only check before the D-04 alias-capture block; if implemented there and returned early, `repo.set_alias_candidates` never runs → Beat 3 ("clarifies once, then learns") silently fails for in-app (record-only) runs. **[VERIFIED: set_alias_candidates (repo.py:480) is the D-04 capture; a record_only early-return before it would skip capture.]** Fix: state explicitly that alias-candidate capture (and clarification drafting) ALWAYS runs; record_only changes ONLY the transport side effect (write synthetic outbound row vs call Resend), placed at the send site, not before capture. Test: a record-only clarification calls set_alias_candidates; then simulate-reply + approve + rerun proves NO second clarification (alias learned).

**MEDIUM — 06-07 records via /demo/send-test, not /demo/compose; and send-test is not record_only.** The recruiter hero path is /demo/compose (no-SMTP), but 06-07 records the old fixture-button path, which calls real Resend during the take. **[VERIFIED: 06-07 lines 25,32-34 record via /demo/send-test; /demo/send-test is not record_only.]** **USER DECISION: record via /demo/compose (the self-serve hero, record_only), with Path-2 real-email as supporting recorded proof.** Re-point 06-07.

**MEDIUM — stale contact_email language in 06-07 + 06-VALIDATION.** 06-07's HIGH-1-confirmation + key_links still describe per-fixture `SELECT contact_email FROM businesses` lookups premised on a contact swap; the model is now _SEED_CONTACTS + demo_sender_bindings. (06-VALIDATION bind row already fixed by the orchestrator this round.) Fix: replace 06-07's contact-lookup wording with _SEED_CONTACTS / business_id routing.

**MEDIUM — 06-05 A5 copy-paste DB commands have broken shell quoting.** The `python -c "... conn.execute("SELECT ...") ..."` examples nest double-quotes → will fail when the operator runs them. **[real bug in the runbook.]** Fix: outer single-quotes around the -c body, or escape the inner SQL quotes.

**LOW** — public /demo/bind nuisance not abuse (no-auth residual, accepted). Prefer `repo.create_run(..., record_only=True)` directly in /demo/compose over create-then-set_record_only (probably safe before BackgroundTasks.add_task, but cleaner).

### Risk
MEDIUM-HIGH until the schema-apply step + _clarify alias-capture ordering are fixed; then MEDIUM/LOW (remaining risk in human-gate execution + no-auth constraints).

---

## Orchestrator Triage (Claude Code)

Both demo-round-1 HIGHs confirmed closed. The 2 new HIGHs + 3 MEDIUMs are all VERIFIED real. Driving a Pass.

**REAL — fix in the Pass:**
1. **HIGH-1 — post-06-08 production DDL apply.** Add a step (in 06-08 as a final note AND/OR as a pre-flight in 06-05) instructing: after 06-08 ships, re-apply DDL over the 5432 session pooler WITHOUT --reset (`DATABASE_URL=<session-5432> uv run python -m app.db.bootstrap`), and verify `payroll_runs.record_only` + `demo_sender_bindings` exist before /demo/bind or /demo/compose are exercised live. Since 06-03's --reset apply happens before 06-08's columns exist in code, this non-reset re-apply is mandatory. (bootstrap must be idempotent / additive — confirm it applies new DDL without dropping data; if bootstrap only runs on --reset, add the additive path or a dedicated migrate step.)
2. **HIGH-2 — _clarify ordering (protect Beat 3).** In 06-08, make explicit: in `_clarify`, the D-04 alias-candidate capture (`repo.set_alias_candidates`) and the clarification draft ALWAYS execute; the `record_only` branch is placed ONLY at the `gateway.send_outbound` transport step (write synthetic outbound row vs real send), AFTER capture. Add a test: a record_only clarification calls set_alias_candidates AND produces a clarification outbound row; then a simulate-reply→approve→rerun shows the alias was learned (no 2nd clarification) — proving Beat 3 works on the in-app path.
3. **MEDIUM — re-point 06-07 to /demo/compose (USER-CONFIRMED).** The recorded 60-90s demo is driven through the /demo/compose landing page (record_only, no real Resend during the take): pick business → employees → type payroll → thread view (request → clarify 'Dave→David known nickname' → in-page reply → approve → paystubs). Path-2 real-email round-trip is a SEPARATE supporting recorded-proof clip. Update 06-07's success_criteria, key_links, and pre-recording smoke test to use /demo/compose (and the in-page reply for the clarify beat), keeping the fixture buttons only as an optional fallback. Watch the 60-90s budget.
4. **MEDIUM — purge stale contact_email language in 06-07.** Replace per-fixture `SELECT contact_email FROM businesses` premise with _SEED_CONTACTS / business_id routing + the demo_sender_bindings identity model. (06-VALIDATION bind row already corrected.)
5. **MEDIUM — fix 06-05 A5 shell quoting.** Rewrite the `uv run python -c "..."` A5 evidence commands with correct quoting (outer single-quotes, or escaped inner SQL), so they run as-is post-/clear. Verify each one is copy-paste-safe.
6. **LOW — create_run(record_only=True) directly** in /demo/compose (cleaner than create-then-set). Apply if trivial.

## Convergence note
demo-round-1: 2 HIGH (real-Resend leak on compose; sender-state coupling) → demo-round-2: 2 HIGH (schema-apply gap; alias-capture ordering), both confirmed closed for round-1's issues. The new HIGHs are narrower (a missing migration step; an ordering nuance) and the recording-path MEDIUM is a now-resolved design decision. One more pass should converge.

## Next step
Pass to fix HIGH-1 + HIGH-2 + the MEDIUMs, re-verify, then Codex demo-round-3.
