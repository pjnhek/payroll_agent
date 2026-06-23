---
phase: 6
reviewers: [codex]
reviewed_at: 2026-06-23
review_round: 3
plans_reviewed: [06-01-PLAN.md, 06-02-PLAN.md, 06-03-PLAN.md, 06-04-PLAN.md, 06-05-PLAN.md, 06-06-PLAN.md, 06-07-PLAN.md]
codex_cli_version: codex-cli 0.135.0
overall_risk: HIGH until 2 narrow ship-critical HIGHs patched, then MEDIUM
prior_rounds: round-1 (9619ffe), round-2 (committed) — both superseded by this file
note: Codex verified Resend assumptions against official live docs this round (sources cited).
---

# Cross-AI Plan Review — Phase 6 (Round 3, Final)

> Round 1 (6 HIGH) + Round 2 (4 HIGH) findings all incorporated and re-verified PASSED.
> This is the third independent Codex pass. Codex checked the Resend assumptions against the
> official docs (receiving = metadata-only; verify needs raw body; threading on In-Reply-To/References;
> attachments accept Base64) — all confirmed accurate.

## Codex Review (Round 3)

### Summary
Not execution-ready YET — but narrowly. The Round-3 plans are much stronger and the Resend assumptions match official docs. Round-2 HIGH status:
- **Outbound Message-ID identity:** MOSTLY resolved for reply routing (06-04 commits to app-minted RFC Message-ID as the stored routing anchor; A5 verified in 06-05). BUT provider audit storage is not executable — schema has no `provider_message_id` column.
- **`.example` seed sender round-trip:** resolved for real INBOUND, but NOT end-to-end for the dashboard demo path (`/demo/send-test` fixtures still use `.example` senders; the hero fixture isn't in the picker).
- **PDF attachments dropped:** RESOLVED (06-04 maps attachments + test).
- **Unsigned canonical webhook bypass:** RESOLVED (all unsigned inbound rejected in prod unless ALLOW_UNSIGNED_FIXTURES=true; flag absent from render.yaml).

### Strengths
- D-10 sequencing correct: pooler check → thin deploy → Resend wiring → real round-trip → reset/docs → recording.
- D-13 dedup explicit: parse to RFC message id, insert with conflict guard, enqueue only on new insert.
- D-17 verification correctly at the raw-request route layer.
- 06-02 Docker/Render solid: uv in builder, `.venv/bin/uvicorn` runtime, `$PORT` shell expansion, health split.
- 06-05 is the right place for A1/A5/A6 + threading evidence.
- 06-06 correctly treats demo reset as a hard dependency and preserves production demo identity after reseed.

### Concerns

#### HIGH
1. **06-04 Task 2 schema mismatch can break live sends.** The plan's `update_email_message_sent`/`update_email_message_state` write `updated_at=now()` and store `provider_message_id`, but `app/db/schema.sql` `email_messages` has `created_at` only — NO `updated_at`, NO `provider_message_id`. Implementing literally FAILS after the provider call, on the live send path. **[VERIFIED by orchestrator: schema.sql email_messages block has created_at at :152 only; grep finds no provider_message_id anywhere; no updated_at on email_messages.]**
2. **06-05/06-07 demo identity still broken for `/demo/send-test`.** The final recording uses the dashboard fixture path, but `app/main.py:82` `_DEMO_FIXTURES` lists only existing eval fixtures (not `gate_block_hero`), and `:831`/`:717` use the fixture's baked `from_addr`. Those fixture files still contain `.example` senders. After 06-05 updates the business contact to the real sender, the dashboard demo can hit `unknown_sender`. **[VERIFIED: main.py:78 comment confirms demo fixtures gate on from_addr resolving via find_business_by_sender; :201 is exact-match.]**

#### MEDIUM
- **A5 fallback is fail-closed but not scheduled.** 06-05 says "document the fallback if Resend overwrites Message-ID"; it should explicitly BLOCK 06-06 and add a remediation mini-plan if A5 fails.
- **Canonical fixture wording contradictory.** Some 06-04 success criteria still say canonical POSTs work unsigned, while the fixed prod behavior returns 400 unless ALLOW_UNSIGNED_FIXTURES=true.
- **SDK call shapes assumed.** Tests mock `resend.*`; add one small 06-01/06-04 check against the installed `resend==2.32.2` signatures so implementation doesn't discover a Python SDK naming mismatch late.

#### LOW
- Some xfail cleanup criteria contradict themselves about whether integration xfails may remain.
- Resend API idempotency key not used for outbound sends (would reduce duplicate-send risk after "provider sent, DB update failed" crashes). Not a blocker.

### Suggestions
- Add `app/db/schema.sql` to 06-04 files and either add nullable `provider_message_id` + `updated_at`, or remove both from the planned SQL and explicitly waive provider-id persistence.
- Add a 06-06 task to update `app/main.py`: include `gate_block_hero` in `_DEMO_FIXTURES`, override fixture `from_addr` from `DEMO_CONTACT_EMAIL` or the selected business's current `contact_email`.
- Add tests for the real demo path after identity swap: `demo_send_test_gate_block_hero_routes_to_business` and `demo_reset_preserves_demo_contact_then_demo_send_test_still_accepts`.
- Add a conditional "A5 failed remediation" step before 06-06.

### Risk Assessment
**HIGH until the two HIGH concerns are patched** — narrow but ship-critical: one fails live outbound state updates, one breaks the exact 60–90s dashboard recording path. After those, **MEDIUM** due to normal live-provider/header variability, with the human gates appropriately controlling it.

---

## Orchestrator Triage (Claude Code)

Both HIGHs VERIFIED against the live code (see bracketed notes above). Both are real, narrow, and ship-critical. The 3 MEDIUMs are also worth folding in (the A5-fallback-as-gate and the contradictory-canonical-wording are cheap correctness/consistency fixes; the real-SDK smoke check is a small de-risk). Driving Pass 3 (`/gsd-plan-phase 6 --reviews`).

**REAL — fix in Pass 3:**
1. **HIGH-1 — schema columns (06-04 + add schema.sql to files_modified).** Decide and commit: EITHER add nullable `provider_message_id TEXT` + `updated_at TIMESTAMPTZ` to the `email_messages` table in schema.sql (and apply via the 06-03 session-pooler migration step) AND have the helpers write them; OR drop `updated_at`/`provider_message_id` from the planned SQL entirely and explicitly WAIVE provider-id persistence (store nothing extra; the synthetic message_id is the only anchor needed). Pick the simpler that satisfies the design — the synthetic-id-as-anchor already works WITHOUT provider_message_id, so waiving it is the lighter path unless audit value is wanted. Whichever: the planned UPDATE SQL must reference only columns that exist. Add a done criterion grepping schema.sql for whatever columns the helpers write.
2. **HIGH-2 — demo-identity for /demo/send-test (06-06 + 06-05/06-07 wiring).** Add a 06-06 task to update app/main.py: (a) include the hero fixture (`gate_block_hero` or whichever the demo's beat-2 uses) in `_DEMO_FIXTURES`; (b) override the fixture's `from_addr` at send time from `DEMO_CONTACT_EMAIL` (or the selected business's CURRENT contact_email) so it resolves via find_business_by_sender after the 06-05 identity swap. Add tests: demo-send-test with the hero fixture routes to the seeded business (not unknown_sender), and demo_reset preserves the demo contact so a subsequent demo-send-test still accepts. Make sure 06-07's recording checklist depends on this (the dashboard path must work post-identity-swap).

**MEDIUM — fold in:**
3. **A5 fallback as a scheduled gate (06-05→06-06).** 06-05 must EXPLICITLY block 06-06 on A5: if the round-trip shows Resend OVERWROTE our Message-ID (reply In-Reply-To != our stored synthetic id), trigger a remediation mini-step (store Resend's returned RFC Message-ID in email_messages.message_id instead, re-point routing) BEFORE proceeding to reset/demo. Not just "documented" — a conditional gate.
4. **Canonical-fixture wording (06-04).** Remove the stale success-criteria lines that say "canonical POSTs work unsigned." The single correct statement: unsigned canonical → 400 in prod; only accepted when ALLOW_UNSIGNED_FIXTURES=true (dev/test). Make every 06-04 mention consistent.
5. **Real-SDK signature smoke check (06-01 or 06-04).** Add one tiny test/check that asserts the actual `resend==2.32.2` call surfaces used (`resend.Webhooks.verify`, `resend.EmailsReceiving.get`, `resend.Emails.send` with headers= and attachments=) exist with the assumed names — so a Python SDK naming mismatch is caught at Wave 0, not at the live gate. (The researcher verified these by source inspection; this just locks it as an executable guard.)

**LOW — optional / document:**
6. xfail-cleanup wording: make it unambiguous whether integration-marked xfails may remain after 06-04 Task 3 (they should not, unless the test genuinely needs a live DB — state which).
7. Resend idempotency key on outbound sends — note as a v2 hardening; not built now.

## Consensus Summary
Single reviewer (Codex, 3 rounds) + orchestrator triage, both code-verified.

### Convergence trend (the signal that matters)
- Round 1: 6 HIGH (Docker won't start, fixture path, send-failure, dedup, …) — broad architectural/mechanical gaps.
- Round 2: 4 HIGH (Message-ID routing, .example senders, attachments, canonical bypass) — deeper live-integration semantics; round-1 explicitly resolved.
- Round 3: 2 HIGH (schema columns, demo-path identity) — narrow, ship-critical, both verified; round-2 mostly resolved.
The HIGH count is monotonically decreasing (6 → 4 → 2) and the issues are getting narrower and more concrete each round — healthy convergence, not churn.

### Agreed Concerns (priority → Pass 3)
1. email_messages schema lacks updated_at/provider_message_id the helpers write → live-send failure.
2. /demo/send-test still uses .example senders + hero fixture missing from picker → demo breaks post-identity-swap.
3. A5 fallback should be a gate; canonical-fixture wording consistency; real-SDK smoke check.

### Next step
`/gsd-plan-phase 6 --reviews` (Pass 3 — the final replan in the convergence loop). Per the directive, no further Codex round follows Pass 3 unless requested; Pass 3 closes the round-3 blockers and the loop ends.
