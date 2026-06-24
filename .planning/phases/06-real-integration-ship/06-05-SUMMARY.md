---
phase: "06"
plan: "05"
type: checkpoint
status: complete
completed: 2026-06-24
requirements:
  - OPS-02
---

# 06-05 SUMMARY — Email round-trip verify gate (D-09b)

**Type:** `autonomous: false` — human-executed live verification.

## Outcome: ✅ PASS (Path-1 verified) — real-email round-trip / A5 deferred

The gate was exercised against the **deployed** Render+Supabase+Resend stack and did exactly
what it exists to do: surfaced a real-world failure that fixtures structurally could not.

## What was verified

- **Live DDL applied** to production Supabase (06-08 schema: `payroll_runs.record_only` +
  `demo_sender_bindings`) — confirmed present; `/demo/bind` succeeds (303), proving the table exists.
- **Demo identity armed** via `POST /demo/bind` (additive `demo_sender_bindings` row;
  `businesses.contact_email` never mutated — HIGH-2 invariant holds).
- **Path-1 (in-app composer) runs end-to-end on the deployed service.** A recruiter can complete
  the full payroll flow in-app (`/demo/compose`, `record_only=True`, no SMTP) — the hero surface.
- **Service health on the live stack:** `/health/live` 200, `/health/ready` 200 (Supabase 6543
  pooler reachable from Render), landing page + dashboard render.

## Real bug surfaced and fixed at this gate (the point of the gate)

The first live run crashed with `ValidationError` (shown as "Error — ValidationError" on the run
page). Root cause: a casual real submission ("hours for this week: Dave Reyes 38") states **no pay
period**, so the extraction LLM returns `pay_period_start=null` — but `ExtractionPayload`/`Extracted`
declared it a REQUIRED non-nullable `date`, so parse raised before `decide()` could run. Every
fixture carried a clean date, hiding this until a real submission hit the deployed service.

**Fix (commit `344bada`, deployed):** `pay_period_start -> date | None` (same nullable-to-avoid-
parse-crash pattern the hours fields use, D-05/Finding #3) + an extraction-prompt instruction to
emit null when no date is stated. Reproduced RED first, then GREEN; full mocked suite 455 passed.
Downstream (`pdf._period_label`, repo, dashboard) already tolerated a null pay period.
See [[live-gate-dateless-email-bug]].

Also shipped at this gate: the "Payroll Agent" nav brand is now a link back to the landing page
(`e566955`), found while clicking through the live Path-1 demo.

## Deferred to a follow-up gate (not blocking the demo spine)

- **Real-email round-trip (Path 2)** and the **A5 threading check** (does the synthetic Message-ID
  survive a real client reply's In-Reply-To). Owner deferred this — Path 1 is the demo hero and
  needs no SMTP. The A5 evidence (and the Branch-B D-03a subject-token fallback, if A5 fails) remain
  an open item to run once before relying on the clarify→reply→resume loop over real email.
- ⚠ CONFIRM flags A1 (header casing) and A6 (email_id vs rfc_message_id) are observed during that
  same real-email round-trip; deferred with it.

## Address topology (confirmed in config, exercised on Path-1; real-email leg deferred)

Inbound `payroll@jiodnel.resend.app` (webhook); outbound From `onboarding@resend.dev` (free tier,
account-owner only); `RESEND_REPLY_TO=payroll@jiodnel.resend.app` set so client replies reach the
inbound address. Documented for the README "For Engineers" note (06-06).
