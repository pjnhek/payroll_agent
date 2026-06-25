---
phase: "06"
plan: "07"
type: checkpoint
status: complete
completed: 2026-06-24
requirements:
  - OPS-04
---

# 06-07 SUMMARY — Demo recording + README link (final Phase 6 deliverable)

**Type:** `autonomous: false` — human-recorded demo. The last deliverable for Phase 6.

## Outcome: ✅ COMPLETE — demo recorded, linked, phase closed

## Deliverable

**Demo recording (Loom):** https://www.loom.com/share/b844c3e0a3364a91b114ab892cc41db4

Recorded against the **live deployed service** (Render + Supabase + Resend), driven from the
in-app `/demo/compose` surface (record_only — no SMTP needed during the take). The fresh-start
baseline was set with `scripts/demo_reset.py --confirm` (runs/emails/paystubs cleared, learned
aliases reset, Metro Deli demo identity re-armed) and verified clean before recording
(runs=0, David Reyes aliases=['D. Reyes']).

## The three thesis beats (D-06)

1. **Clean run** — compose payroll for a seeded business → operator approves → confirmation sent.
2. **Unknown shorthand → clarify** — "Dave Reyes" (ambiguous: David vs Daniel Reyes at Metro Deli)
   resolves to `source=none` → the **code gate** requests clarification; the LLM only *suggests*
   the likely employee, it never decides the money-moving call.
3. **It learned** — after the operator confirms, the alias persists; re-composing the same
   shorthand resolves automatically (`source=alias`) with no clarification — "won't ask again."

Closing shot: the `/eval` view with **false_process_count = 0** — the thesis metric (a name the
system can't resolve never reaches a real payroll calculation).

## Wired into the product

- **README.md** — demo placeholder replaced with the Loom link + a beat-by-beat description.
- **Landing page** (`index.html`) — the proof-section video slot now links to the Loom recording
  (clickable card with hover affordance) instead of the "06-07 delivers the asset" placeholder.

## Final validation (06-07 success criteria — all green on the live service)

| Check | Result |
|-------|--------|
| `GET /health/live` | ✅ `{"status":"ok"}` |
| `GET /health/ready` | ✅ `{"status":"ready"}` (Supabase 6543 pooler reachable from Render) |
| `GET /eval/chart.svg` | ✅ `200` (eval chart static asset, D-21) |
| Demo reset → clean baseline | ✅ runs=0, aliases reset, identity re-armed |
| Alias-learning arc | ✅ verified at logic level (clarify → learn → auto-resolve) + recorded live |

## Bugs found and fixed during the live demo prep (the value of real use)

The act of recording exercised real paths fixtures never could, surfacing and fixing:
- `pay_period_start` required → nullable (real dateless email crashed extraction) — `344bada`
- Webhook returned opaque 500 on parse failure → legible 502 — `e629447`
- **RESEND_API_KEY scope** was send-only → couldn't read received emails (operator fixed to full access)
- PDF attachment filename had no `.pdf` extension (arrived as an unopenable blob) — `6fc7e0d`
- Reply emails didn't thread (no `Re:` subject) — `6fc7e0d`
- Landing page showed the armed business raw UUID instead of its name (Jinja loop-scope) — `16fb9eb`
- Full UI restyle (Linear/Stripe-class) so the recording reads as credible software — `5334ebc`

## Phase 6 — COMPLETE

All 8 plans done (06-01..06-08). The free-stack deployment (Render + Supabase + GitHub Actions
keep-alive) is confirmed end-to-end; OPS-01..OPS-04 satisfied. Deferred to backlog: the real-email
A5 threading verification (Path-2 inbound proven; the deep header-survival check) and the
field-regression "did you forget the OT?" clarification.
