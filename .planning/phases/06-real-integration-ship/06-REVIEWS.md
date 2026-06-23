---
phase: 6
reviewers: [codex]
reviewed_at: 2026-06-23
review_round: 4
plans_reviewed: [06-01-PLAN.md, 06-02-PLAN.md, 06-03-PLAN.md, 06-04-PLAN.md, 06-05-PLAN.md, 06-06-PLAN.md, 06-07-PLAN.md]
codex_cli_version: codex-cli 0.135.0
overall_risk: HIGH until the demo-routing fix is tightened (1 HIGH remains); then MEDIUM
prior_rounds: round-1, round-2, round-3 — all superseded by this file
---

# Cross-AI Plan Review — Phase 6 (Round 4)

> Round 1 (6 HIGH) + Round 2 (4 HIGH) + Round 3 (2 HIGH) all incorporated and re-verified PASSED.
> Fourth independent Codex pass (user-requested, since round 3 still had HIGHs). Codex confirmed
> Round-3 HIGH #1 (schema) fully resolved; found ONE new HIGH introduced by the round-3 demo fix.

## Codex Review (Round 4)

### Summary
- **Round-3 HIGH #1 (schema mismatch): RESOLVED.** 06-04 WAIVE path — `update_email_message_sent`/`update_email_message_state` set only `send_state` keyed by the synthetic `message_id`; Resend provider id logged only. Codex independently confirmed `email_messages` has no `provider_message_id` or `updated_at`.
- **Round-3 HIGH #2 (/demo/send-test identity): PARTIALLY resolved — not execution-ready.** 06-06 correctly adds the hero fixture and fixes its `.example` sender, BUT the preferred GLOBAL `DEMO_CONTACT_EMAIL` override can break the multi-business recording path (Beat 1 `coastal_exact` vs Beat 2 Metro Deli). One remaining HIGH.

### Strengths
- 06-04 much stronger: schema-safe updates, failed-send flip, attachment forwarding, signature behavior, canonical prod/dev split, SDK smoke check — all explicit.
- 06-05 correctly treats A5 as a blocking human gate, not polish.
- 06-06/06-07 now treat the demo path as a first-class deliverable (reset + pre-recording smoke tests).

### Concerns
- **HIGH — 06-06/06-07: global `DEMO_CONTACT_EMAIL` can misroute other fixtures.** 06-06 Task 1 overrides `fixture_data["from_addr"]` from a SINGLE `DEMO_CONTACT_EMAIL`. 06-07 records Beat 1 with `coastal_exact` (Coastal) and Beat 2 with the Metro Deli clarify fixture. If `DEMO_CONTACT_EMAIL` = the Metro real sender, `coastal_exact` routes to Metro Deli while its body contains Coastal employees (and vice versa). Tests only prove the hero fixture, not that the full three-beat set still routes to the correct businesses. **[VERIFIED by orchestrator: `_DEMO_FIXTURES` (main.py:82) carries only label+path, NO business identity; fixtures span 3 businesses — coastal_exact/coastal_multi→Coastal payroll@coastalcleaning.example, metro_alias→Metro hr@metrodeli.example, summit_exact→Summit. A single global override misroutes the others.]**
- **MEDIUM — 06-05 A5 Branch B under-specified.** The "store Resend's actual RFC Message-ID and re-route" branch mostly describes a manual row update after observing a reply; it doesn't clearly change FUTURE `send_outbound` behavior, and the referenced outbound `WEBHOOK_DEBUG` evidence may not exist (the debug guard logs INBOUND fetches). OK as a human gate, but Branch B needs a real mini-plan if it fires — or an explicit fall back to the D-03a subject-token (already spec'd, deferred) when the provider-assigned RFC id can't be known before replies arrive.
- **MEDIUM — stale 06-PATTERNS.md reintroduces the schema bug.** 06-PATTERNS.md still shows the old `provider_message_id`/`updated_at` send pattern, and 06-04 tells executors to read it. The plan overrides it clearly (not HIGH), but it's a footgun.
- **LOW — 06-06 reset mentions `alias_audit` but the schema may not have that table.** The detailed task sequence omits it; remove it or use conditional deletion.

### Suggestions
- Change `_DEMO_FIXTURES` to include `business_name`/`business_id`, then override `from_addr` from THAT fixture's current `businesses.contact_email`, not one global env var.
- Add tests: `coastal_exact` routes to Coastal after Metro's contact is swapped; the hero fixture routes to Metro after the swap; all recording fixtures route to their expected business.
- For A5 Branch B: define an actual code remediation, or explicitly fall back to D-03a subject token if the provider RFC id can't be known before replies arrive.
- Update 06-PATTERNS.md to remove the stale provider-id persistence snippet.

### Risk Assessment
**HIGH until the demo routing fix is tightened** — the remaining blocker can break the final recording path (a core Phase 6 deliverable). After replacing the global sender override with per-fixture business-contact resolution, risk drops to **MEDIUM** (remaining uncertainty is live-provider behavior behind explicit human gates).

---

## Orchestrator Triage (Claude Code)

The remaining HIGH is real and is a defect in the ROUND-3 fix itself (a single global override can't serve a multi-business demo) — VERIFIED against main.py:82 + seed.py (3 businesses, fixtures carry no business id). Driving Pass 4. The 2 MEDIUMs + 1 LOW are cheap and worth folding in.

**REAL — fix in Pass 4:**
1. **HIGH — per-fixture business-contact resolution (06-06 main.py + tests).** Replace the global `DEMO_CONTACT_EMAIL`-overrides-everything approach with per-fixture identity:
   - Tag each `_DEMO_FIXTURES` entry with its `business_name` (or business_id) — coastal_exact/coastal_multi→Coastal, metro_alias→Metro Deli, summit_exact→Summit.
   - At demo-send time, resolve `from_addr` from THAT fixture's business's CURRENT `businesses.contact_email` (look it up by name/id), NOT a single global env var. So after 06-05 swaps ONE business's contact to the real round-trip sender, that business's fixtures use the real sender and ALL OTHER fixtures keep resolving to their own seeded contacts. Every beat routes to the correct business.
   - The clarify beat (D-06 beat 2) is the Metro Deli unknown-shorthand path — the committed fixture today is `metro_alias` / `02_stored_alias_metro.json` (NOTE: there is no committed `gate_block_hero` file; either add one or use the existing Metro clarify fixture and drop the gate_block_hero name — the executor advisory already allows the closest Metro fixture). Make the plan name the REAL fixture, not a nonexistent key.
   - Tests: coastal_exact routes to Coastal AND the Metro hero fixture routes to Metro, BOTH after the identity swap (prove the multi-business set is correct, not just one fixture). demo_reset preserves the swapped identity. Add the validation rows.
   - Update 06-07's pre-recording smoke test to verify EACH beat's fixture routes to its intended business (not just the hero).

**MEDIUM — fold in:**
2. **A5 Branch B real remediation (06-05).** Make Branch B concrete: if Resend overwrites our Message-ID, either (a) a small code change so send_outbound stores Resend's returned RFC id in email_messages.message_id going forward (and a one-time UPDATE for the in-flight thread), re-verify; OR (b) explicitly fall back to the pre-spec'd D-03a subject-token anchor (it's already locked in CONTEXT for exactly this "headers don't survive" case) — state which, with steps. Also fix the evidence pointer: the LOG_WEBHOOK_DEBUG_IDS guard logs INBOUND fetches, so A5's "did our outbound Message-ID survive" is observed from the REPLY's In-Reply-To (inbound), which is correct — make 06-05 say that precisely, not "outbound WEBHOOK_DEBUG."
3. **Stale 06-PATTERNS.md (footgun).** Update 06-PATTERNS.md to remove the old provider_message_id/updated_at send-pattern snippet so an executor reading it can't reintroduce the schema bug 06-04 just waived. (06-PATTERNS is a planning artifact — safe to edit.)

**LOW:**
4. **06-06 reset alias_audit.** Confirm whether an `alias_audit` table exists in schema.sql; if not, remove it from the reset ordering or make the delete conditional (IF EXISTS / catch). Don't reference a nonexistent table.

## Consensus Summary
Single reviewer (Codex, 4 rounds) + orchestrator triage, code-verified.

### Convergence trend
- Round 1: 6 HIGH (broad mechanical) → Round 2: 4 HIGH (live-integration semantics) → Round 3: 2 HIGH (narrow, schema/demo) → Round 4: **1 HIGH** (a defect in the round-3 demo fix: global vs per-fixture identity).
- 6 → 4 → 2 → 1. Each round narrower and more concrete; round-4's HIGH is a regression introduced by round-3's own fix, now pinpointed. One more targeted pass should close it.

### Agreed Concerns (→ Pass 4)
1. Global demo-sender override misroutes the multi-business recording — replace with per-fixture business-contact resolution + multi-fixture routing tests.
2. A5 Branch B needs a concrete remediation (code change or D-03a fallback); fix the evidence-source wording.
3. Stale 06-PATTERNS.md provider-id snippet; alias_audit table existence in reset.

### Next step
`/gsd-plan-phase 6 --reviews` (Pass 4) — close the per-fixture routing HIGH + the MEDIUMs. A round-5 Codex review follows if the user wants continued verification; given the monotonic 6→4→2→1 trend, this pass is expected to converge.
