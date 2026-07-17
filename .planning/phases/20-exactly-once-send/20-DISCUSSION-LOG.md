# Phase 20: Exactly-Once Send - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-17
**Phase:** 20-Exactly-Once Send
**Areas discussed:** Retry ownership, Human escalation, Immutable send record

---

## Retry ownership

| Decision | Alternatives considered | Selected |
|---|---|---|
| Retry initiator | Automatic bounded retry; operator-triggered; manual-only | Automatic bounded retry |
| Eligible failures | Classified transient failures; any exception; timeouts only | Classified transient failures |
| Replay content | Frozen snapshot only; rebuild current state; recompose text | Frozen snapshot only |
| In-flight run state | Approved + Retry queued; error; new status | Approved + Retry queued |
| Safe cutoff | 20h; 23h; 12h | 20h from reservation |
| Payload mismatch | Escalate; rebuild same key; mint replacement | Escalate |
| Retry history | Separate PII-safe attempt history; overwrite; new row per attempt | Separate history |
| Restart behavior | Resume schedule; reset ladder; escalate | Resume schedule |
| Manual control | Advance existing job; no control; direct send | Advance existing job |
| Changed source data | Frozen snapshot wins; update; cancel | Frozen snapshot wins |
| Concurrent manual/scheduled retry | One fenced job; allow both; reject manual retry | One fenced job |

**User's choice:** Automatic, bounded, transient-only replay with a 20-hour,
reservation-timestamp cutoff. No retry may rebuild content or create concurrent send
work.

---

## Human escalation

| Decision | Alternatives considered | Selected |
|---|---|---|
| Terminal state | needs_operator; error; approved warning | needs_operator delivery review |
| Operator actions | Mark delivered / authorize new confirmation; retrigger; opening detail resends | Two explicit actions |
| Review information | Safe concise card + frozen payload; generic status; raw provider dumps | Safe concise card + frozen payload |
| New confirmation safety | Typed acknowledgement; one click; second approval | Typed acknowledgement |

**User's choice:** Delivery ambiguity receives its own explicit human review. A new
confirmation is intentional, acknowledged, and never automatic.

---

## Immutable send record

| Decision | Alternatives considered | Selected |
|---|---|---|
| Stored content | Complete provider envelope; text plus payroll data; metadata only | Complete provider envelope |
| Freeze timing | At reservation; after provider acceptance; after failure | At reservation |
| Mutation model | Append-only snapshot + separate events; overwrite row; replace snapshot | Append-only snapshot + separate events |
| Retention | Existing append-only audit; delete bytes; delete all | Existing append-only audit |
| Human-authorized repeat | Original snapshot; current data with approval; current data without approval | Original snapshot |

**User's choice:** Persist byte-identical provider-ready data before the first send and
retain it as the authoritative audit/replay source.

---

## the agent's Discretion

- Verify current Resend API and retention semantics before setting the concrete ladder.
- Choose schema, repository, queue, and UI implementation details that preserve the
  locked safety rules.

## Deferred Ideas

None. The user explicitly selected three low-priority polish todos for visibility as
secondary folded items; CONTEXT.md fences them from delaying SEND-01 through SEND-03.
