---
id: 260816-ee8
slug: fix-six-adversarial-pre-push-review-find
date: 2026-08-16
type: quick
status: complete
---

# Summary: six adversarial pre-push review findings

Five of six fixed and committed. One blocked by tooling, with the exact remediation
recorded below.

Suite: 1390 passed before, **1400 passed / 107 skipped** after. `ruff check` clean.

## Commits

| Commit | Finding | What changed |
|---|---|---|
| `2984aa1` | 1 (blocking, live) | Reject exit on the unsendable confirmation card |
| `0bfd07b` | 2 + 3 (blocking, unpushed) | Sign-off truncation, no silent deletion, closing line appended |
| `20618b8` | 4 (warning, live) | `reject()` docstring corrected + fence pinned by test |
| `1132fdc` | 5 (warning, live) | `render.yaml` `DEMO_OUTBOUND_TO` -> `sync: false` |

## 1. Confirmation delivery review had no honest exit (was live)

For `authorization` / `validation` / `configuration`, hiding "Authorize a new
confirmation" left **Mark delivered** as the operator's only action, and that action
CASes to `RECONCILED`, asserting a delivery the provider had definitively refused.

Reject now renders on the `{% else %}` branch of the `can_fresh_send` check only.
Conditional on purpose: those categories mean nothing was delivered, so Reject is the
truth. On the retryable branch delivery may genuinely have happened, so Mark delivered
/ Authorize stay the correct pair and an unconditional Reject would have introduced a
new hazard (rejecting a run whose confirmation already reached the client).

Red-proofed: the three parametrized cases fail against the pre-fix template.

## 2 + 3. Confirmation draft format guard did not do what it claimed (was unpushed)

Measured, not inferred:
- `"Best regards,\n[Your Name]\nPayroll Team"` became `"Best regards,\n\nPayroll Team"`.
  The token went; the broken close BUG-13 was reported for survived.
- `"net pay for [pay period ending 2026-06-15] is below"` became `"net pay for  is
  below"`. Silent content deletion from a money-approved client email.
- `app/llm/prompts/confirm.py:29` told the model "the system appends its own closing
  line". Nothing appended anything, so the drafted path ended on a dollar figure while
  the *fallback* template was the only path that closed properly.

Now: `_SIGN_OFF_RE` truncates the sign-off block (taking its placeholder with it);
`_BRACKET_PLACEHOLDER_RE` is a **detector** whose hit disqualifies the whole draft to
the deterministic template floor rather than editing it; `_CONFIRMATION_CLOSING` is one
constant appended to an accepted draft and used by the template floor, so both paths
end identically and the prompt's claim is true.

Verified against the four reviewed inputs: sign-off truncated cleanly with the net-pay
summary intact; bracketed prose preserved and routed to the floor; "Thanks for sending
your hours." (a legitimate sentence opening with a sign-off word) correctly NOT
matched, while the real "Thank you!" sign-off below it was.

Red-proofed: 4 of 5 new tests fail against the pre-fix module.

## 4. `reject()` docstring stated the opposite of the code (was live)

It claimed an `awaiting_reply` run holds no in-flight send. `clarification.py:489-500`
sets `AWAITING_REPLY` in the **same transaction** that enqueues `SEND_OUTBOUND`, so the
run occupies that status for the whole send lifecycle and rejecting mid-flight is
reachable.

Behavior kept (it is safe), premise replaced with the real fences: handoff
authorization and settlement both require `AWAITING_REPLY`; reply routing refuses a
non-`awaiting_reply` run. The accepted residue is now named: reject in the window
between provider POST and settlement leaves `send_state='reserved'` with an unreleased
handoff on a terminal run.

Mutation-proofed: `test_reject_from_awaiting_reply_is_not_revived_by_a_late_client_reply`
fails when both `app/ingest.py:50` and `app/routes/pipeline_glue.py:120` are mutated to
`False`; source restored with a clean `git diff`.

## 5. Personal address in `render.yaml` — PARTIAL

`render.yaml` now uses `sync: false`. **The address is not scrubbed from the repo**:
`app/routes/demo.py:72` defines `DEMO_OPERATOR_EMAIL = "pjnhek@gmail.com"` as a source
constant, referenced by 7 test assertions. That predates this session's diff. Making it
config-driven touches Path-2 sender binding (money-adjacent routing) and was left out
of scope rather than done unasked. Open follow-up.

## 6. `.env.example` — NOT DONE

A dotenv guard denies both read and write on `.env.example`. Needs a manual paste:

```
# Demo-only: redirect EVERY outbound client email to this address at snapshot
# reservation. Empty = off (production-safe default). See app/email/routing.py.
DEMO_OUTBOUND_TO=
```

## Invariants re-verified as untouched

`get_outbound_message_id`'s `send_state='sent'` filter; the reserved-message_id
Idempotency-Key path and frozen-snapshot replay; `approve()`'s CAS, error boundary and
roster stashing; `?notice=` allow-listing (probes for `<script>` and a quote breakout
both return `None`, autoescape on); record-only fencing at
`app/db/repo/outbound_handoffs.py:266`. No schema change; no `app/pipeline` money
logic, `app/queue`, or tax-table edits.
