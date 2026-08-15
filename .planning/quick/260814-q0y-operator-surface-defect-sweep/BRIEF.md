# Brief: operator-surface defect sweep (12 bugs + demo deliverability)

Every item was verified against live source this session. Do NOT re-derive the diagnosis, but DO
re-confirm each line reference before editing, since line numbers shift as you work.

**Baseline: commit `78542f1`** (landed, verified green: 1331 passed / 1 skipped, ruff clean,
mypy --strict clean over 171 files). Do NOT re-fix what it covered: the mark-handled dead end, the
three `simulate_reply` guard-rejection 303s (now `?simulate_reply_error=` codes at
`runs.py:1407/:1419/:1454`), or `awaiting_reply` lacking an operator escape.

---

## TIER 1 — visitor-reachable, highest priority

### BUG-1: a terminal state that demands action and offers none
`app/templates/run_detail.html:276` + `app/routes/runs.py:1247-1255`

When `delivery_review_marker` is set but `_load_delivery_review` returns `None` or raises (exception
swallowed at `runs.py:1254`), the `{% elif %}` at `run_detail.html:111` fires on the marker alone,
which **suppresses** the resolve-names form and Reject at `:115`. The card at `:276` then renders a
red "Action required" badge with zero buttons. Re-trigger at `:318` excludes `needs_operator`;
Approve/Reject at `:305` is `awaiting_approval` only. Net: no resolve, no reject, no retrigger.

**Fix intent:** this state must always offer at least one working escape (Reject at minimum,
ideally Re-trigger too). Decide deliberately whether the right fix is to stop the `:111` branch
firing when `delivery_review` is None, or to give the `:276` card its own actions. Do NOT simply
delete the "Action required" badge — the state genuinely does require action.

### BUG-2: Retry offered on a permanently unretryable failure
`failure_category` is **display-only**: `app/routes/runs.py:355`
(`_DELIVERY_REVIEW_CATEGORY_LABELS`) and `run_detail.html:263` / `:271` as a `<dd>` value, and in
**zero** conditionals. Both Retry buttons render unconditionally.

Confirmed live: category `validation` ("Provider validation issue"), attempts 1, recipient
`hr@metrodeli.example`. **Proven this session:** Resend returns HTTP 403 `validation_error` for a
non-verified recipient. That is permanent, so retrying the identical frozen email to the identical
address can never succeed.

Category enum: `app/pipeline/result.py:classify_delivery_exception` →
`{transport, provider_5xx, rate_limited, payload_mismatch, authorization, validation,
configuration, final_attempt_lease_expired, unknown}`.

**Fix intent:** classify which categories are terminal vs retryable, and suppress or relabel Retry
for terminal ones on **both** delivery-review card variants (clarification ~`:255-268`,
confirmation ~`:269-276`). An operator must never be offered an action that cannot succeed.

---

## TIER 2 — operator-facing silent failures

One defect repeated nine times: a guard rejects, the handler returns a bare
`RedirectResponse(..., 303)`, the page reloads identically, nothing says why.

Use the pattern established by `78542f1` and the pre-existing precedents `?resolution_superseded=1`
(`runs.py:580` → `:1170` → `:1270` → `run_detail.html:18`) and `?demo_queue_error=1`
(`demo.py:340`): an **allow-listed** query-param code mapped to a fixed safe label server-side (see
`_SIMULATE_REPLY_ERROR_LABELS` near `runs.py:141` for the shape). Never interpolate raw text into a
URL or the page.

| ID | Handler | Lines | Silently fails when |
|----|---------|-------|---------------------|
| BUG-3 | `approve` | `runs.py:432` | CAS lost. **THE MONEY GATE.** |
| BUG-4 | `authorize_new_confirmation` | `:1102`, `:1109`, `:1116` | mistyped ack phrase; wrong review kind; CAS lost. Guards sending a client a SECOND email |
| BUG-5 | `resolve` | `:541`, `:546`, `:553`, `:559`, `:579`, `:606` | six guards; `:579` is an invalid employee_id submission returning nothing |
| BUG-6 | `retrigger` | `:737`, `:769` | blocked by delivery-review marker; blocked by active provider handoff |
| BUG-7 | `mark_delivery_delivered` | `:1081`, `:1092` | CAS lost; exception swallowed |
| BUG-8 | `_finish_clarification_delivery_review` | `:1049` | exception swallowed, so BOTH "Mark handled" and clarification "Reject" silently no-op |
| BUG-9 | `retry_delivery_now` `:990`, `retry_clarification_delivery_now` `:1013` | single exit; "retried" and "could not retry" are indistinguishable |
| BUG-10 | `demo_bind` `demo.py:154`, `demo_compose` `demo.py:191`, `:195` | unknown business; oversized body or subject |

**BUG-3 is the single human money gate.** Treat its diff with extra care. Do NOT alter the
`claim_status` CAS semantics, the error boundary, or the roster-stashing behavior. Add operator
feedback ONLY.

`runs.py:1388` (`simulate_reply` status guard) is a deliberate stale-resubmit guard matching every
other handler. Leave it or give it a code, your call, but do not report it as new.

---

## TIER 3

**BUG-11:** the delivery-review card never states WHAT was uncertain about the delivery. Its three
buttons are unexplained. The owner, who built this system, could not tell what the card wanted. Add
a plain-language sentence naming the actual uncertainty, driven by the failure category. Ties
directly to BUG-2.

**BUG-12:** `app/routes/templating.py` has a `computing` entry in both `_BADGE_CLASS` and
`_BADGE_LABEL` that is not among the 11 `RunStatus` values in `app/models/status.py`. Dead config.
Remove it, or add a test pinning the badge maps to the enum.

---

## FIX A — demo email deliverability (approach A3)

**Root cause, proven not inferred:** seeded contact emails are `payroll@coastalcleaning.example`,
`hr@metrodeli.example`, `finance@summittech.example` (`app/db/seed.py:56-68`). `.example` is an
RFC 2606 reserved TLD. Resend free tier with `from=onboarding@resend.dev` returns HTTP 403
`validation_error`: "You can only send testing emails to your own email address
(pjnhek@gmail.com)." Live-tested against the real API this session, including a plus-addressed
variant (`pjnhek+metrodeli@gmail.com`), which was **also rejected**. Only the literal
`pjnhek@gmail.com` is deliverable.

So every clarification/confirmation send fails, and the landing-page gate demo ALWAYS escalates to
delivery review instead of completing the clarify → reply → resume loop.

**Approach A3, chosen deliberately over the alternatives.** Add a config-driven outbound override
(e.g. `DEMO_OUTBOUND_TO`, via `app/config.py` settings + `.env.example` + `render.yaml`) that
redirects outbound recipient resolution to a single deliverable address when set.

Requirements:
- Must NOT mutate `businesses.contact_email`. That column is `NOT NULL UNIQUE`
  (`app/db/schema.sql:19`) so the three businesses cannot share one address, AND it is the
  access-control seam consumed by `find_business_by_sender` (`app/db/repo/runs.py:149`), which
  refuses unknown senders rather than guessing.
- Must therefore require NO live Supabase data mutation.
- Must fix all three seeded businesses, not just the landing-gate one
  (`LANDING_GATE_FIXTURE_KEY = "unknown_shorthand_metro"`, `app/routes/dashboard.py:34` = Metro Deli).
- Keep the override branch narrow and well away from the Phase 20 at-most-once machinery: do NOT
  touch the reserved-`message_id` / Idempotency-Key reuse, the frozen snapshot replay, or the
  row-locked provider handoff.
- Compose with the existing `demo_sender_bindings` inbound mechanism
  (`app/db/repo/runs.py:157-159`) rather than duplicating it.
- Document honestly in README (demo mode routes client email to the operator) and set it in
  `render.yaml` for the deployed service.

---

## Constraints

- **uv only:** `uv run pytest -q`, `uv run ruff check .`, `uv run mypy`. Never pip/venv/poetry.
  Python pinned 3.12.
- **Scope fence:** do not touch `app/pipeline/` money logic, `federal_withholding.py`,
  `tax_tables_2026.py`, `calculate.py`, or `app/queue/` durability.
- **`/ops` must stay script-free:** `tests/test_ops_route.py:364` asserts `"<script"` not in the
  response. Do not add JS to `ops.html`.
- **Test placement:** tests must land where `uv run pytest -q` actually executes them.
  `tests/test_dashboard.py` and `tests/test_needs_operator.py` are `@pytest.mark.integration` and
  do NOT run in CI (only `concurrency-proof.yml` has a real Postgres and it selects files BY NAME).
- **RED-first** hermetic regression test per fix. Money-gate and delivery-review paths especially.
- Full suite green + ruff + mypy --strict before finishing.
- Small reviewable commits, conventional-commit messages, no emojis, no em-dashes.

## Deploy note (record only, do NOT deploy)

`78542f1` adds column `email_messages.operator_acknowledged_at` (`app/db/schema.sql`). It is NOT
applied to live Supabase and NOT deployed. Two commits are unpushed (`abd2170`, `78542f1`).
Deploying code before the migration would break the live delivery-review path and turn
`/health/schema` red. Schema-before-code ordering, per the Phase 8 precedent. Leave deployment to
the operator; just record what will be required.

## Context

Milestone v5 (React/TypeScript Operator Console) is parked at `abd2170`. These same Jinja surfaces
are what v5 Phase 23 will convert, so where a defect is inherent to the current Jinja structure,
say so in the summary as a spec input for that conversion.
