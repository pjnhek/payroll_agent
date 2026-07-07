---
id: 260705-02
created: 2026-07-05
source: Phase 9 code review (WR-04/05/06) + post-review conversation tracing of ambiguous-reply scenarios
resolves_phase: 11
priority: high
files:
  - app/pipeline/orchestrator.py:986-1010 (_clarify purpose-scoped idempotency guard — WR-05)
  - app/pipeline/orchestrator.py:837-850 (_combined_context_email — questions not in context)
  - app/pipeline/orchestrator.py:315-330 (is_round_2 = bool(clarified))
  - .planning/phases/09-atomic-data-integrity/09-REVIEW.md (WR-04/WR-05/WR-06 details)
  - .planning/todos/pending/260623-08-reclarification-loop-cap.md (related: round cap / operator escape)
---

# Clarification round machine redesign (WR-05 silent-park + ambiguous-reply attribution)

## Problem

Three coupled defects in multi-round clarification, all traced against live source
(2026-07-04/05); the phase-9 review-fix pass deliberately skipped them as point-fixes
because they change CLAR-04 semantics together:

1. **WR-05 — round-blind send guard silently parks runs.** `_clarify`'s idempotency
   guard is purpose-scoped: any second clarification with the same purpose finds the
   round-1 outbound row and suppresses the send, but the run still advances to
   `awaiting_reply`. No email goes out; the client doesn't know they're being waited on;
   `awaiting_reply` is outside both the sweep scope and retrigger's claimable statuses.
   Reproduced concretely: employee A resolved/no hours + employee B unresolved/has hours
   → one clarification asks both questions → client replies only "40 hours" → B still
   unresolved → re-clarify → send suppressed → parked silently. Same for any partial
   answer, any new unresolved name in a reply, or a second field-regression round.
   (Note: [260623-08]'s premise "sends a fresh clarification email each round" is
   FALSE post-tracing — the loop doesn't spam, it silently stops. Its ask — a round
   cap + operator escape — still applies and belongs in this same redesign.)

2. **Ambiguous-reply field attribution is unanchored LLM judgment.** The resume
   extraction context is ORIGINAL + REPLY only — the outbound clarification's QUESTIONS
   are not included. A bare reply ("40") with two hour-less resolved employees leaves
   attribution entirely to the model: assign-to-both → run computes with
   plausible-but-unconfirmed hours, caught only at the human gate (no code gate fires:
   nonzero hours pass the zero-hours gate, 40 is not >40); assign-to-one/neither →
   re-clarify → WR-05 park. Under-attribution should degrade to a second question, not
   a silent stall.

3. **WR-06 — stale provenance after a rolled-back round** (terminal clarified_fields
   labels can survive a crash-rolled-back round; approval-gate badges then mislead).
   WR-04 (redelivered reply after pre-claim death is dropped fail-safe) is the fourth
   member of the cluster. CX-03 (carried_forward reopened) was already fixed in a6d4e2e.

## Solution

Design as one phase (candidate: the clarify-cluster / MONEY-followup phase, alongside
[260705-01] alias-bind-on-confirmation and CX-01 multi-round context loss):

- **Round-aware send guard**: key the idempotency check on (purpose, round) or an
  asked-fields hash instead of purpose alone, so a genuinely new question sends while a
  true duplicate is still suppressed. Add [260623-08]'s round counter + operator-escape
  ("needs manual resolution" state) in the same change.
- **Questions in context**: include the outbound clarification body (or a structured
  summary of asked fields/names) in the resume extraction context so bare answers have
  an attribution anchor; consider requiring the LLM to leave unaddressed asked fields
  absent rather than guessing.
- **Recoverability**: make silently-parked `awaiting_reply` impossible (either the send
  always happens, or the run routes to a visible operator state); revisit sweep/retrigger
  scope for awaiting_reply-with-no-outbound as a diagnosable inconsistency.
- Fold WR-06's provenance scoping and WR-04's redelivery handling into the same round
  state design (round/consumed linkage on reply rows — the WR-03 fix's link_email_to_run
  provides a building block).
