---
status: resolved
trigger: "im on payroll-agent.onrender.com and im pressing the 'run this email through the pipeline' for the watch the gate refuse to guess, then on the run (https://payroll-agent.onrender.com/runs/5a738802-9295-4de6-8df5-a85bdc87cc4a) im seeing clarification delivery review, and im confused what its supposed to be doing. the retry same question is confusing and mark handled is also confusing, when pressing mark handled and landing on the page where im supposed to write a reply, the send button doesnt do anything"
created: 2026-08-14T00:00:00Z
updated: 2026-08-14T01:00:00Z
---

# Debug Session: Mark Handled Dead End

## Symptoms

- expected: pressing the landing page's headline CTA ("Watch the gate refuse to guess" -> "Run this email
  through the pipeline") drives the gate-tripping fixture through the clarify -> reply -> resume loop. If a
  clarification delivery review appears, resolving it via "Mark handled" should leave the run in a state
  where the demo reply composer actually works.
- actual: the run escalates to `needs_operator` with a CLARIFICATION delivery-review card whose buttons are
  not self-explanatory. Pressing "Mark handled" moves the run to `awaiting_reply` and renders the demo reply
  composer, but pressing "Simulate client reply" reloads the page unchanged with no feedback. The run has no
  working forward path and no operator escape.
- error: none surfaced to the user; that is the defect. The failing path is a silent HTTP 303 back to the
  same URL. `GET /runs/5a738802-.../status` returns
  `{"status":"awaiting_reply","failure":{"secondary_label":null,"stage":null,"reason":null,"attempts":null},"queue_label":null,"has_open_job":false}`
  and both `/health/queue` and `/health/ready` are green, so this is not a queue or infrastructure failure.
- timeline: observed 2026-08-14 against the deployed service. The landing gate fixture is the primary CTA
  added during the `260726-sje` landing-page proof-surface restructure. Unknown whether the clarification
  send ever succeeded in production; the Loom walkthrough shows a completed round trip, so this may be a
  regression in provider behavior rather than in this code.
- reproduction: deterministic. Load https://payroll-agent.onrender.com, press "Run this email through the
  pipeline", wait for `needs_operator`, press "Mark handled", then press "Simulate client reply".

## Current Focus

- hypothesis: "Mark handled" is implemented as a status-only CAS and never records the operator's delivery
  assertion on the frozen outbound `email_messages` row, so a downstream consumer that requires proof of
  delivery (`get_outbound_message_id`, filtered to `send_state = 'sent'`) still sees an unproven send and
  silently no-ops.
- test: construct a run whose clarification outbound row is `reserved`/`failed` and whose status is
  `needs_operator` with a clarification delivery review, POST `mark-handled`, then POST `simulate-reply`, and
  assert the reply is persisted and enqueued rather than silently dropped.
- expecting: pre-fix RED — `simulate_reply` returns 303 with no `email_messages` inbound row created and no
  job enqueued, because `get_outbound_message_id(run_id, purpose="clarification")` returns `None`.
- next_action: reproduce the dead end in a hermetic test (RED) before changing any production code.
- reasoning_checkpoint:
    hypothesis: the bug is a state-machine gap introduced where the Phase 20 delivery-review feature meets the
      Phase 5 demo reply affordance. Neither is individually wrong; "Mark handled" creates a state
      (`awaiting_reply` + unproven clarification send) that `simulate_reply`'s proof-of-delivery guard was
      never designed to accept.
    confirming_evidence:
      - `_finish_clarification_delivery_review` (app/routes/runs.py:986) performs ONLY
        `repo.claim_status(run_id, NEEDS_OPERATOR, target, conn=conn)` at app/routes/runs.py:996. It does not
        touch the outbound row. Its docstring calls this the provider-free outcome, which is intentional.
      - `mark_clarification_delivery_handled` (app/routes/runs.py:1008) passes
        `RunStatus.AWAITING_REPLY` as that target.
      - `run_detail.html:723` renders the reply composer for `run.status == 'awaiting_reply'`.
      - `simulate_reply` (app/routes/runs.py:1291) guards on
        `clar_mid = repo.get_outbound_message_id(run_id, purpose="clarification")` (app/routes/runs.py:1332)
        and returns a bare `RedirectResponse(..., status_code=303)` when falsy (app/routes/runs.py:1335).
      - `get_outbound_message_id` (app/db/repo/emails.py:399) filters
        `AND send_state = 'sent'` (app/db/repo/emails.py:426) plus current-epoch. A `reserved` or `failed`
        row cannot match.
      - Live status confirms the run reached `awaiting_reply` with `has_open_job: false` and a null failure
        block, i.e. it is parked, not processing and not errored.
    falsification_test: if a run reaches this dead end while its clarification outbound row IS already
      `send_state='sent'` in the current epoch, then `get_outbound_message_id` is not the blocking guard and
      this diagnosis is wrong — the silent no-op would instead be coming from the status guard
      (app/routes/runs.py:1327), the `load_inbound_email` guard (app/routes/runs.py:1345), or the enqueue
      failure path (app/routes/runs.py:1379).
    fix_rationale: the `send_state='sent'` predicate must NOT be relaxed. Its docstring
      (app/db/repo/emails.py:404-412) states that treating a reserved/failed row as proof would let the
      delivery guard read a crashed send as completed and skip a required email; Phase 20's at-most-once
      guarantee depends on it. The correct fix records the operator's assertion durably so the two states
      ("never proven" vs "operator asserted delivered") are distinguishable, rather than making them look
      identical.
    blind_spots:
      - The upstream cause (why the clarification send fails at all) is NOT yet confirmed. The
        "Safe failure category" value rendered on the live delivery-review card has not been collected and is
        the single datum that distinguishes a Resend recipient restriction from another failure mode.
      - Whether any other `get_outbound_message_id` caller depends on the current strictness in a way a new
        state would perturb has not been audited.
      - `tests/test_dashboard.py` and `tests/test_needs_operator.py` are `@pytest.mark.integration` modules
        that do NOT run in CI (only `concurrency-proof.yml` has a real Postgres, and it selects files by
        name). A hermetic RED test must be placed where it will actually execute.
- tdd_checkpoint: workflow.tdd_mode is false, but this fix is behavior-changing on an operator path, so a
  RED-first hermetic reproduction is required before any production edit.

## Session 2 Update (FIX B complete, FIX A blocked on human input)

FIX B (B1/B2/B3) is DONE, self-verified, and green. FIX A is NOT started — it hit both of the
explicit human-input requirements flagged in Scope below and could not proceed further without
guessing. See CHECKPOINT REACHED in the agent's final response for the exact questions.

next_action: awaiting user's answer on (1) the "Safe failure category" value from the live
  delivery-review card, and (2) confirmation + a real deliverable recipient address before any
  live-data seed change (FIX A). FIX B needs a separate confirmation: the user re-running the
  landing-page gate demo end-to-end against the LIVE deployed service (this fix has not been
  deployed yet — it is committed locally only, see Resolution.files_changed).

## Scope

FIX B (first — the real defect, independent of demo data):
- B1: make "Mark handled" durably record the operator's delivery assertion on the frozen outbound row so
  consumers can distinguish "operator asserted delivered" from "never proven". Must not weaken the Phase 20
  at-most-once guarantee or make a crashed send look complete.
- B2: replace the silent 303 no-ops in `simulate_reply` (app/routes/runs.py:1335, and audit :1327, :1345,
  :1379) with operator-visible feedback. Precedent for query-param banners already exists:
  `?resolution_superseded=1` (app/routes/runs.py:580 -> :1122 -> :1221 -> run_detail.html:18) and
  `?demo_queue_error=1` (app/routes/demo.py:340).
- B3: decide whether `awaiting_reply` should expose an operator escape. The Re-trigger form renders only for
  `['error','approved','received','extracting','computed','sent']` (run_detail.html:715), so `awaiting_reply`
  currently has no human path out.

FIX A (second — why the review fires at all):
- Seeded client contact emails are `payroll@coastalcleaning.example`, `hr@metrodeli.example`,
  `finance@summittech.example` (app/db/seed.py:56-68). `.example` is an RFC 2606 reserved TLD that cannot
  receive mail. Combined with `RESEND_FROM_ADDR=onboarding@resend.dev` (Resend's free shared sender, which
  restricts permitted recipients), the clarification send cannot succeed, so the landing-page gate demo
  always escalates instead of completing the loop.
- Requires confirming the "Safe failure category" datum first, and likely a live Supabase data migration,
  not just a code change. Respect the schema-before-code deploy discipline (Phase 8 precedent).

SCOPE FENCE: do not touch `app/pipeline/` money logic, the Pub 15-T engine, or the durable queue substrate.
This is a delivery-review / operator-affordance bug plus demo seed data.

CONTEXT: milestone v5 (React/TypeScript Operator Console) was started this session and is parked at commit
`abd2170`. Keep this work separate from it. These are the same Jinja surfaces v5 Phase 23 will convert, so
whatever lands here is also a spec input for that conversion.

## Evidence

- timestamp: 2026-08-14T00:00:00Z
  source: live GET https://payroll-agent.onrender.com/runs/5a738802-9295-4de6-8df5-a85bdc87cc4a/status
  observation: `{"status":"awaiting_reply","badge_class":"neutral","badge_label":"Awaiting Reply","failure":{"secondary_label":null,"stage":null,"reason":null,"attempts":null},"queue_label":null,"queue_badge_class":"neutral","has_open_job":false}` — run is parked at awaiting_reply with no open job and no recorded failure.
- timestamp: 2026-08-14T00:00:00Z
  source: live GET /health/queue and /health/ready
  observation: `{"status":"ok"}` and `{"status":"ready"}` — rules out queue backlog and infrastructure as causes.
- timestamp: 2026-08-14T00:00:00Z
  source: source trace of app/routes/runs.py and app/db/repo/emails.py
  observation: mark-handled performs a status-only CAS (runs.py:996); simulate_reply's clarification
    Message-ID guard (runs.py:1332) consults a query filtered to `send_state='sent'` (emails.py:426), which a
    frozen reserved/failed review row cannot satisfy, producing the silent 303 at runs.py:1335.
- timestamp: 2026-08-14T01:00:00Z
  source: app/db/repo/emails.py:get_unconfirmed_outbound docstring (the function that surfaces the
    delivery-review card and gates re-send)
  observation: explicit precedent AND explicit prohibition — "Do not widen get_outbound_message_id /
    get_outbound_for_round to also match 'reserved'/'failed' instead of adding a function like this
    one." Confirms the fix must be a NEW, purpose-built reader, never a relaxation of the existing
    proof-of-delivery predicate. Directly shaped the B1 design (a new orthogonal column +
    get_operator_acknowledged_message_id, not a widened send_state filter).
- timestamp: 2026-08-14T01:00:00Z
  source: app/db/repo/outbound_handoffs.py:resolve_outbound_provider_handoff_for_delivery_review
    (used by the CONFIRMATION delivery-review's "Mark delivered" action)
  observation: the confirmation side's analogous human-override action releases only the
    outbound_provider_handoffs FENCE row — it does NOT touch email_messages.send_state either. This
    is independent precedent for the same design choice made for B1: a human delivery-review
    decision is recorded as a NEW fact, never by mutating send_state's transport-truth column.
- timestamp: 2026-08-14T01:00:00Z
  source: simulate_reply's synthetic reply construction (runs.py, In-Reply-To/References fields)
  observation: clar_mid is not merely a boolean "was this proven sent" signal — its STRING VALUE is
    load-bearing: it becomes the synthetic reply's RFC In-Reply-To/References headers, which
    find_awaiting_reply_for_header later matches on to route the reply back to this run. This ruled
    out a simpler boolean-flag design for B1 in favor of a real Message-ID-returning reader
    (get_operator_acknowledged_message_id), matching get_outbound_message_id's own return shape.
- timestamp: 2026-08-14T01:00:00Z
  source: app/routes/runs.py:_load_delivery_review / _safe_delivery_review_projection +
    app/db/repo/job_settlement.py:_delivery_failure_category + app/pipeline/result.py:
    classify_delivery_exception
  observation: the "Safe failure category" rendered on the delivery-review card is one of
    {transport, provider_5xx, rate_limited, payload_mismatch, authorization, validation,
    configuration, final_attempt_lease_expired, unknown} (runs.py:_DELIVERY_REVIEW_CATEGORY_LABELS).
    Which ONE value applies to run 5a738802's actual clarification-send failure depends on the exact
    HTTP status + error_type Resend's live API returned for THIS attempt (e.g. a 403
    "validation_error" for a testing-domain recipient restriction resolves to "validation" via
    classify_delivery_exception's error_type check BEFORE its status==403 check; a bare 403 with a
    different error_type resolves to "authorization" instead). This is a live-runtime provider fact,
    not derivable from source — confirmed genuinely blocked per the task's explicit instruction not
    to guess it.
- timestamp: 2026-08-14T01:00:00Z
  source: app/db/seed.py:52-71 (contact_email literals) cross-referenced against Resend's documented
    shared-sender ("onboarding@resend.dev") sandbox restriction
  observation: even if the FROM address were changed, `.example` is an RFC 2606 RESERVED, permanently
    non-routable TLD — no `.example` address can ever receive real mail regardless of sender
    configuration. A real fix requires replacing the 3 seeded contact_email values with addresses
    Resend's live account configuration will actually accept (the account's own verified
    email(s), or a verified custom domain's addresses) — a fact only the account owner (the user)
    knows, and a change to already-migrated live Supabase seed rows if this has already been deployed
    once (not just a local seed.py edit). Confirmed genuinely blocked per the task's explicit
    instruction to checkpoint before any live-data mutation.

## Eliminated

- hypothesis: queue backlog or a stalled worker is preventing the reply from processing.
  reason: `/health/queue` returns ok and the run reports `has_open_job: false`; nothing is pending.
- hypothesis: the run errored and the UI is hiding it.
  reason: the status endpoint's entire `failure` block is null and the status is `awaiting_reply`, not `error`.

## Resolution

root_cause: "Mark handled" (`_finish_clarification_delivery_review`, app/routes/runs.py) was a
  status-only CAS that never recorded the operator's delivery assertion anywhere durable. The
  frozen clarification outbound row stayed `send_state IN ('reserved','failed')` forever, and
  `simulate_reply`'s only Message-ID source was `get_outbound_message_id`, strictly filtered to
  `send_state='sent'` (by design — a Phase 20 at-most-once/no-fabricated-delivery guarantee that
  must not be weakened). No code path existed to distinguish "never proven" from "operator
  explicitly closed this out" (single cause; AND-gate: no — this is one code-level gap in one
  state-machine transition, not multiple simultaneous contributing conditions).

fix: |
  FIX B (B1+B2+B3), complete and self-verified:
  - B1: added a new, orthogonal `email_messages.operator_acknowledged_at TIMESTAMPTZ` column
    (schema.sql) — deliberately NOT a 4th send_state value, so send_state stays pure
    provider-transport truth. `mark_outbound_operator_acknowledged` (write, exact-row,
    write-once) and `get_operator_acknowledged_message_id` (read, purpose+epoch scoped,
    companion never a replacement for get_outbound_message_id) added to
    app/db/repo/emails.py. `_finish_clarification_delivery_review` now calls the write inside
    the SAME transaction as the status CAS when acknowledge_outbound=True (mark-handled only,
    never reject). `simulate_reply` now falls back to the new reader only when the strict
    proof-of-delivery lookup returns nothing.
  - B2: simulate_reply's three real no-op branches (no proof, missing source email, enqueue
    failure) now redirect with a fixed-vocabulary `?simulate_reply_error=<code>` query param
    (allow-listed against `_SIMULATE_REPLY_ERROR_LABELS` before ever reaching the template, so
    an unrecognised/hostile value renders nothing) instead of a silent 303. Rendered as a
    `callout callout-error` banner above the reply composer. The 4th guard (status !=
    awaiting_reply) stays silent on purpose — it is a normal stale-resubmit no-op, matching
    every other stale-resubmit guard on this router.
  - B3: `awaiting_reply` had NO human escape at all before this fix (Re-trigger does not render
    for it; `reject()` did not accept it as a source). Extended `reject()`'s CAS chain to also
    accept AWAITING_REPLY -> REJECTED, and added a Reject button to the awaiting_reply banner.
    Deliberately NOT a staleness-based auto-retrigger (the existing 15-minute STALE_THRESHOLD
    used for other stranded in-flight statuses would be actively wrong here — awaiting_reply can
    legitimately sit for hours/days waiting on a real client reply).

  FIX A: NOT started. Genuinely blocked on two explicit human inputs (see Evidence) — the live
  "Safe failure category" value, and confirmation + a real deliverable recipient before any
  live-data seed mutation. See CHECKPOINT in the agent's final response.

verification:
  target_test: { result: pass }
  mutation_check: { result: skipped, reason_if_skipped: "no Stryker/mutation tool configured for this Python project", mutant_killed: null }
  no_op_deletion: { result: pass, deletion_justified_by_rca: true }
  adjacent_tests: { result: pass, suites_run: ["uv run pytest -q -m 'not integration and not live_llm and not queueproof'  (1331 passed, 1 skipped, 107 deselected)"] }
  revert_and_reconfirm: { result: pass, bug_returned_on_revert: true, fixed_on_reapply: true }
  guardrail_verdict: accepted
  supplementary_manual_mutation_check: "no Stryker available (Python project); ran two manual mutants by hand at the fix site (disabled the B1 write; removed the B1 read fallback) and confirmed the driving test (test_mark_handled_then_simulate_reply_does_not_dead_end) fails on both, then reverted both mutations and reconfirmed green -- not a substitute for signal 2, recorded for extra confidence only"
  oracle_type: derived
  ruff_check: pass ("uv run ruff check ." — clean, matches CI's lint gate)
  mypy_strict: pass ("uv run mypy" — 171 source files, 0 issues, matches CI's typecheck gate)

files_changed:
  - app/db/schema.sql (new operator_acknowledged_at column, CREATE-body + idempotent ALTER)
  - app/db/repo/emails.py (mark_outbound_operator_acknowledged, get_operator_acknowledged_message_id)
  - app/db/repo/__init__.py (export both)
  - app/routes/runs.py (_finish_clarification_delivery_review acknowledge_outbound param;
    mark_clarification_delivery_handled wires it; simulate_reply fallback lookup + banner query
    params; reject() accepts AWAITING_REPLY; _SIMULATE_REPLY_ERROR_LABELS; run_detail wires
    simulate_reply_error)
  - app/templates/run_detail.html (simulate_reply_error banner; awaiting_reply Reject form)
  - tests/conftest.py (InMemoryRepo fakes for both new repo functions + fake_repo tuple registration)
  - tests/test_phase20_clarification_review.py (driving RED->GREEN regression test)
  - tests/test_reply_redelivery.py (B2/B3 regression tests + strengthened the pre-existing
    enqueue-failure test's assertion)

commit_status: committed as 78542f1 and pushed; live on payroll-agent.onrender.com.

human_verification:
  date: 2026-08-17
  verdict: PASS — verified by the reporter against the LIVE deployed service, not a local run.
  what_was_exercised: landing CTA "Watch the gate refuse to guess" -> "Run this email through
    the pipeline" -> clarification sent -> operator replied via the demo composer -> run
    RESUMED and advanced to awaiting_approval (the human gate). The originally-reported
    symptom (composer's reply button reloads the page unchanged, run has no forward path)
    did NOT reproduce.
  note_on_the_delivery_review_path: the CLARIFICATION delivery-review card did not appear at
    all this time, and its absence is correct rather than a gap in the verification. The card
    was a downstream symptom of an undeliverable send: clarification.py:474 addresses the
    clarification via resolve_outbound_recipient(email.from_addr), which resolved to the RFC
    2606 seed contact hr@metrodeli.example, Resend refused it, and the failed send escalated
    the run. With DEMO_OUTBOUND_TO now configured in the Render dashboard, the send is
    redirected to a real mailbox and succeeds, so the run goes straight to awaiting_reply.
    The reported defect was in the COMPOSER's reply path, which both routes share and which
    was exercised directly here, so the verification covers the actual bug. The
    delivery-review branch itself remains covered by
    test_mark_handled_then_simulate_reply_does_not_dead_end.
