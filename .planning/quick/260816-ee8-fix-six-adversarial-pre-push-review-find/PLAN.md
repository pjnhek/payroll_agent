---
id: 260816-ee8
slug: fix-six-adversarial-pre-push-review-find
date: 2026-08-16
type: quick
---

# Fix six adversarial pre-push review findings

An adversarial review of `8f42d60..HEAD` (23 commits, 18 deployed + 5 unpushed) found
six defects. Two are in the unpushed set and are real-inbox-facing; one is a live
reintroduction of the exact bug class the session existed to fix. The declared
invariants (at-most-once delivery, `get_outbound_message_id`'s `send_state='sent'`
filter, `approve()` semantics, `?notice=` allow-listing, record-only fencing) were all
verified intact and must stay intact.

## Task 1 — the confirmation delivery-review card strands the operator (BLOCKING, live)

`app/templates/run_detail.html:282` gates "Authorize a new confirmation" behind
`can_fresh_send`. `app/models/delivery_review.py` sets `fresh_send_ok=False` for
`authorization`, `validation`, and `configuration`. That card carries no Reject form
(the clarification card at :274 does), and the `elif` chain at :112 suppresses the
generic `needs_operator` Reject at :142 while the `awaiting_approval` controls at :315
do not apply.

Net: for those three categories the entire page offers exactly one action, **Mark
delivered**, which CASes to `RECONCILED` and asserts the client received the
confirmation. For `validation` the category's own `uncertainty` string says the
provider rejected the message because the recipient could not accept mail. The
operator's only exit requires asserting the opposite of what the card just told them.

**Fix:** render a Reject form in the existing `{% else %}` branch of the
`can_fresh_send` check, beside the blocker sentence.

Conditional, not unconditional, on purpose. Reject is added exactly where the operator
is otherwise stranded, and those are exactly the categories where the provider
definitively refused the message, so "nothing was delivered" is the truth. For the
retryable categories delivery genuinely may have happened, and Mark delivered /
Authorize remain the correct pair; an unconditional Reject there would introduce a new
hazard (rejecting a run whose confirmation already reached the client).

`reject()` already accepts `NEEDS_OPERATOR -> REJECTED`, and the provider handoff was
already released by `release_outbound_provider_handoff_to_delivery_review`
(`app/db/repo/job_settlement.py:578`) before the review was created, so no route change
is needed.

**Tests:** extend `test_validation_confirmation_card_hides_both_actions_and_shows_blocker`
to require the reject form and prove the POST reaches `REJECTED`; pin that
`transport` does NOT offer it.

## Task 2 — the confirmation format guard does not do what it claims (BLOCKING, unpushed)

`app/pipeline/compose_email.py:235` claims the two regexes make both BUG-13 violations
"IMPOSSIBLE". Measured against the live function:

- `"...\n\nBest regards,\n[Your Name]\nPayroll Team"` becomes
  `"...\n\nBest regards,\n\nPayroll Team"`. The bracket token goes; the sign-off
  survives. BUG-13's actual symptom was a broken-looking sign-off, and that is still
  what a client gets.
- `_BRACKET_PLACEHOLDER_RE` deletes *any* bracketed span of 1-80 chars unconditionally.
  `"net pay for [pay period ending 2026-08-15] is below."` becomes
  `"net pay for  is below."` — silent content deletion from a money email.

Related (finding 3): `app/llm/prompts/confirm.py:29` tells the model "the system
appends its own closing line, so end the email right after the net pay summary."
Nothing appends anything. `app/pipeline/delivery.py:110` passes the return value
straight to `body_text=body` at :169. So the *drafted* path ends abruptly on a dollar
figure while the *fallback* `_confirmation_template_body` (`compose_email.py:274`)
closes properly with "Please contact us if you have any questions." The failure path
produces a better email than the happy path.

**Fix, one coherent change:**

1. Extract `_CONFIRMATION_CLOSING` as a module constant; `_confirmation_template_body`
   consumes it so the two paths cannot drift.
2. `_strip_format_violations` keeps the `Subject:` strip and gains a sign-off
   truncation: cut from the first line that is *only* a sign-off phrase. That removes
   the sign-off and the placeholder under it together, which is what BUG-13 was
   actually about.
3. `_BRACKET_PLACEHOLDER_RE` stops being a substituter and becomes a **detector**. A
   residual placeholder rejects the whole draft to the deterministic template floor
   rather than surgically deleting words. Failing toward the known-good template is
   correct for a client-facing money email, and it lets the detector stay broad
   without the risk of mangling a sentence.
4. `compose_confirmation` appends `_CONFIRMATION_CLOSING` to an accepted draft (no-op
   if the model already wrote it), which makes the prompt's claim true.

**Tests:** update `test_compose_confirmation_uses_draft_when_present` (behavior change
is intentional); add coverage for sign-off truncation, the bracketed-prose fallback,
the closing append, and idempotence of the append.

## Task 3 — `reject()`'s docstring states the opposite of the code (WARNING, live)

`app/routes/runs.py:483` asserts "a still-in-flight clarification send holds no active
handoff by the time a run is observably sitting at awaiting_reply."
`app/pipeline/clarification.py:489-500` sets `AWAITING_REPLY` in the **same
transaction** that enqueues `SEND_OUTBOUND`, so the run sits at `awaiting_reply` for
the entire send lifecycle: enqueue, lease, handoff authorize, provider POST.

The behavior is nonetheless safe, for a different reason than the one written down:
settlement's `expected_status` check (`app/db/repo/job_settlement.py:441`) fences the
send, and reply routing refuses a non-`awaiting_reply` run at `app/ingest.py:50` and
`app/routes/pipeline_glue.py:120`. Keep the behavior; replace the false premise with
the real one, and record the residue the fence leaves behind.

## Task 4 — `render.yaml` commits a personal address; `.env.example` lacks the key

`render.yaml:77` hardcodes a personal Gmail address into a recruiter-facing repo. The
comment directly above it already prescribes `sync: false` and then does not do it.
Switch to `sync: false`. Separately add `DEMO_OUTBOUND_TO=` to `.env.example` (a dotenv
guard may block this; report if so).

## Out of scope

`app/pipeline` money logic, `federal_withholding.py`, `tax_tables_2026.py`,
`calculate.py`, `app/queue` durability. No schema change. No behavior change to
`approve()`, the `?notice=` mechanism, or the at-most-once send path.

## Verification

`uv run pytest -q` green (baseline: 1390 passed, 107 skipped), `uv run ruff check`
clean, and each finding covered by a test that fails without its fix.
