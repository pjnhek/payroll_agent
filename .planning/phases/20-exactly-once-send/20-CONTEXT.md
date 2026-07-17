# Phase 20: Exactly-Once Send - Context

**Gathered:** 2026-07-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 20 makes outbound payroll confirmation delivery safely replayable within a
bounded Resend idempotency window. A client receives at most one confirmation per
approved run and epoch unless an operator explicitly authorizes a new confirmation.
The phase replaces the current fail-closed treatment of every unconfirmed outbound
reservation with a safer bounded path: reserve one immutable provider-ready snapshot,
replay it under the same Message-ID-derived idempotency key for eligible transient
failures, and hand uncertain or stale delivery to a human.

This phase covers the shared outbound-send primitive for every `send_outbound` call,
while its user-facing safety criterion is payroll confirmation delivery. It must not
redraft through an LLM, regenerate ReportLab PDFs, mint a replacement Message-ID, or
silently turn an ambiguous send into a second email. The Phase 21 operations proof and
ops view remain out of scope.

</domain>

<decisions>
## Implementation Decisions

### Bounded automatic replay

- **D-01: Own retries automatically, not through repeated operator clicks.** The durable
  queue automatically retries a send inside the provider-safe window; an operator can
  use a `retry now` control only to advance that same durable job, never to send
  synchronously or create a second attempt.
- **D-02: Retry only classified transient provider or transport failures.** Timeouts,
  connection failures, Resend 5xx responses, and rate-limit responses are eligible.
  Validation, authorization, configuration, and payload errors stop rather than retry.
- **D-03: Cap automatic replay at 20 hours from the durable reservation timestamp.** The
  reservation's database timestamp is authoritative. It is deliberately four hours
  below Resend's confirmed 24-hour retention window and is never reset by a restart,
  later failure, or manual retry.
- **D-04: Replay only the frozen provider-ready snapshot.** Once reserved, a retry may
  not redraft, reload current payroll data, regenerate PDFs, or otherwise rebuild the
  outgoing content. Later edits can affect only a separately human-authorized future
  send.
- **D-05: Keep the run `approved` while a safe retry is outstanding.** Existing
  secondary queue presentation shows `Retry queued`; do not add a payroll status or set
  `error` while automatic retry remains eligible.
- **D-06: An idempotency payload-mismatch rejection stops immediately.** Keep the
  original reservation and escalate; never automatically mint a new Message-ID or key.
- **D-07: Preserve a PII-safe attempt history beside the single logical send.** A
  successful replay finishes as sent, but the preceding uncertainty remains auditable.
  Restart recovery resumes the persisted reservation and schedule. Scheduled and
  operator-accelerated retries converge on one fenced queue job, so at most one attempt
  is active for a reservation.

### Human delivery review

- **D-08: Expired or otherwise non-replayable ambiguity enters `needs_operator` as a
  delivery-review state.** It must not look like an ordinary transient error and must
  never remain silently `approved`.
- **D-09: Give the operator two explicit outcomes.** `Mark delivered` completes the
  run without another email. `Authorize a new confirmation` creates a clearly distinct,
  human-authorized send slot only after a typed acknowledgement that it may create a
  second email.
- **D-10: Show the basis for the human decision without raw provider dumps.** The
  delivery-review card shows recipient, subject, reservation time, attempt count, safe
  failure category, Message-ID/key, and the exact frozen email/PDFs. Raw provider
  requests and responses are not rendered.
- **D-11: A human-authorized new confirmation reuses the original frozen snapshot.** It
  produces the same content and attachments under a distinct, explicitly authorized
  send slot; it does not silently use changed payroll or contact data.

### Immutable record

- **D-12: Freeze the full provider-ready envelope atomically with reservation before
  any provider call.** It includes sender, recipient, reply-to, headers, subject, text,
  attachment filenames, and exact attachment bytes.
- **D-13: Keep the snapshot append-only.** State transitions and PII-safe attempt events
  are separate from snapshot content; a retry never overwrites it. Retain completed and
  manually resolved snapshots in the existing append-only email audit—Phase 20 adds no
  purge rule.

### Folded Todos

The user explicitly selected all three pending polish todos when the phase matcher
presented them. They are secondary to SEND-01 through SEND-03 and must never delay or
weaken the delivery-safety path.

- **Frontend progressive enhancement** (`.planning/todos/pending/260623-02-frontend-progressive-enhancement.md`)
  — fold only any small progressive enhancement naturally needed to make delivery review
  legible; do not expand Phase 20 into a frontend redesign.
- **Paystub YTD columns** (`.planning/todos/pending/260623-03-paystub-ytd-v2.md`) — keep
  visible as a user-selected item, but do not alter the immutable replay contract or
  regenerate an already-reserved PDF.
- **Eval chart restyle** (`.planning/todos/pending/260623-04-eval-chart-restyle-v2.md`) —
  may be planned only as non-blocking polish after the SEND requirements; it is unrelated
  to the outbound-send correctness gate.

### the agent's Discretion

- Confirm Resend's current SDK mechanism and documented idempotency-window semantics
  before setting the concrete retry ladder and response classification.
- Choose the schema, repository, and queue-handler boundaries that preserve the frozen
  snapshot and one-fenced-job invariant.
- Choose the exact wording, routing, and styling of the delivery-review card and typed
  acknowledgement, provided the two explicit outcomes and safe-data boundary hold.
- Choose compact, PII-safe attempt-history fields and how the existing queue badge is
  connected to delivery retry work.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and locked requirements

- `.planning/ROADMAP.md` — Phase 20 goal, SEND-01 through SEND-03, and the four success
  criteria that define the at-most-one claim.
- `.planning/REQUIREMENTS.md` — authoritative SEND-01, SEND-02, and SEND-03 language;
  names the current Message-ID overwrite, LLM/PDF drift, Resend header, and retention
  hazards.
- `.planning/PROJECT.md` — v4 durable-execution narrative and the product safety
  priority: a human approves payroll before any final client confirmation.
- `.planning/STATE.md` — current verified Phase 19 closeout, Phase 18 failure-policy
  constraints, and the required live re-confirmation of Resend's retention window.

### Approved durable-execution design

- `docs/superpowers/specs/2026-07-13-durable-execution-design.md` — authoritative
  exactly-once claim, pre-send reservation model, provider-side 24-hour idempotency
  window, and human escalation past that window.
- `.planning/research/ARCHITECTURE.md` — durable queue ownership, fencing, and handler
  design that a send-retry job must preserve.
- `.planning/research/SUMMARY.md` — adversarial design corrections and Phase 21 proof
  obligations that consume Phase 20's resulting behavior.
- `.planning/research/PITFALLS.md` — provider, PII, retention, and durable-execution
  failure modes.

### Existing implementation and upstream contracts

- `app/email/gateway.py` — current pre-send reservation, synthetic Message-ID creation,
  Resend call, and state flips; its current mint-before-read behavior is the central
  SEND-01 defect.
- `app/db/repo/emails.py` — current outbound upsert and sent/unconfirmed lookups. Its
  conflict update currently overwrites `message_id`, `subject`, and `body_text`.
- `app/pipeline/delivery.py` — confirmation draft/PDF creation and current unconfirmed
  guard; this is the no-redraft/no-regenerate integration seam.
- `app/pipeline/send_guard.py` — current fail-closed unconfirmed-send predicate to
  evolve into bounded safe replay without weakening its detection boundary.
- `app/db/schema.sql` — `email_messages` columns and the
  `uq_email_run_purpose_round_epoch` send-slot identity.
- `app/routes/runs.py` — operator approval error boundary and the delivery-review route
  integration point.
- `tests/test_send_idempotency.py` — existing false-positive protection and live-DB
  epoch-scoping proof.
- `tests/test_delivery.py` — current confirmation idempotency, reserved/failed upsert,
  and delivery error-boundary coverage.
- `.planning/phases/18-failure-policy-sweep-deletion/18-CONTEXT.md` — shared bounded
  `PipelineResult`, retry, terminal settlement, fencing, and queue-owned recovery
  contract.
- `.planning/phases/19-webhook-cutover-durable-ingest/19-CONTEXT.md` — durable producer
  cutover, identifier-only job convention, secondary queue indicators, and no
  BackgroundTask recovery path.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `app/db/repo/emails.py`: purpose/round/epoch-scoped outbound rows and
  `get_unconfirmed_outbound()` already expose the current send-slot predicate.
- `app/pipeline/send_guard.py`: a single shared fail-closed detector used by
  clarification and confirmation flows; keep detection centralized while changing the
  allowed response for safe, bounded replay.
- `app/queue/`: Phase 16–19 durable job, lease, fenced settlement, and `Retry queued`
  presentation machinery provides the retry ownership model.
- `tests/test_send_idempotency.py`: hermetic and real-Postgres guard proofs already
  distinguish proven sent from possible sent and provide a non-vacuity pattern.

### Established Patterns

- Outbound send slots are keyed by `(run_id, purpose, round, epoch)`; retry must reuse
  the same slot and a human-authorized repeat must enter a distinct slot.
- No database transaction spans a provider call. Persist durable intent and frozen
  content first, then call Resend, then settle through fenced durable mechanisms.
- `payroll_runs.status` is payroll business state; queue state is a secondary UI
  indicator. Do not add a send-status variant to the run status enum.
- Diagnostics crossing the browser boundary are bounded and PII-safe. Preserve raw
  provider data only outside rendered error surfaces.

### Integration Points

- `gateway.send_outbound()` must become read-or-reserve and replay from persisted
  content; its Resend invocation gains the key derived from the reserved Message-ID.
- `delivery.deliver()` must freeze the confirmation before calling the gateway and hand
  transient results to a durable queue path rather than regenerate its LLM draft/PDFs.
- The runs router and existing run-detail template are the delivery-review and manual
  `retry now` / explicit-authorization surfaces.
- Repo fakes and live Postgres proofs need to evolve alongside the schema so the
  immutable-snapshot and single-active-retry invariants are falsifiable.

</code_context>

<specifics>
## Specific Ideas

- The automatic replay cutoff is **20 hours from reservation**, deliberately not from a
  later failure or a restart.
- The provider payload mismatch is an escalation signal, never an excuse to mint a new
  identifier automatically.
- The operator's safe outcomes are intentionally phrased as **“mark delivered”** and
  **“authorize a new confirmation.”**
- A duplicate the operator intentionally authorizes must still be byte-identical in
  content to the original frozen snapshot.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within the Phase 20 delivery-safety boundary. The three
user-selected polish todos are captured above as secondary folded items.

</deferred>

---

*Phase: 20-Exactly-Once Send*
*Context gathered: 2026-07-17*
