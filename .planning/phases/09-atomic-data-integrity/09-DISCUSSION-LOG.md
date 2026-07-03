# Phase 9: Atomic Data Integrity - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-02
**Phase:** 9-Atomic Data Integrity
**Areas discussed:** Email-send vs transaction, Duplicate-webhook contract, Stuck-run recovery path, Transaction granularity (all four selected; approach decisions delegated to Claude)

---

## Todo folding (cross-reference step)

| Option | Description | Selected |
|--------|-------------|----------|
| Fold neither (Recommended) | Keep Phase 9 tightly scoped to DATA-01/02/03 | ✓ |
| 260623-08 loop cap | Re-clarification loop cap + operator-escape state | |
| 260623-01 security remainder | WR-04/WR-05/INFO-02 security hygiene | |

**User's choice:** Fold neither.
**Notes:** Four other keyword matches (260623-02/03/04/05) were not presented — REQUIREMENTS.md locks them out of v2 scope; re-litigating locked decisions is a workflow anti-pattern.

---

## Area selection

| Option | Description | Selected |
|--------|-------------|----------|
| Email-send vs transaction | How atomicity treats the un-rollbackable provider send in `_deliver`/`_clarify` | ✓ |
| Duplicate-webhook contract | Loser behavior + orphaned-email-row handling in the dedup CAS | ✓ |
| Stuck-run recovery path | Sweep vs force-retrigger vs threshold change; restart vs mark-ERROR | ✓ |
| Transaction granularity | Whether `_run_stages`' transaction spans the clarify path (LLM + send inside) | ✓ |

**User's choice:** All four, plus free text: "u decide on the best approach for all of this."
**Notes:** Per-area question loops were therefore skipped; Claude made the calls after tracing orchestrator.py, main.py, repo.py, gateway.py, supabase.py.

---

## Email-send vs transaction (Claude's decision)

Alternatives considered:
- **Wrap everything including the Resend call in one DB txn** — rejected: rollback after a successful send makes the DB lie ("no email sent"), and pins a pooled connection (max=5) across network latency.
- **Commit-first-then-send** — rejected: a crash after commit-to-SENT but before the send means the DB claims delivery that never happened — the worst inversion for a payroll confirmation.
- **Selected: keep D-13c reserved-before-send (own commit) → send → ONE post-send finalize txn (flip-to-sent + alias + SENT + RECONCILED), with explicit at-least-once semantics** (crash between provider-accept and finalize → retrigger re-sends; duplicate email accepted as benign vs never-delivered). → D-9-01/07/08.

## Transaction granularity (Claude's decision)

Alternatives considered:
- **One big txn spanning the whole `_run_stages` including `_clarify`** — rejected: two LLM calls + a send inside a DB txn (D-9-01 violation).
- **Selected: process branch = one pure-DB txn (persists + line items + COMPUTED + AWAITING_APPROVAL); clarify branch = persists commit first, `_clarify` is its own post-commit unit with its own post-send finalize txn.** Status-advance-last invariant across all units. Crash inside `_clarify` yields exactly the stranded shape the DATA-03 sweep recovers. → D-9-02/04/05/06.

## Duplicate-webhook contract (Claude's decision)

Alternatives considered:
- **Loser repairs orphans (creates the missing run on redelivery)** — rejected: requires distinguishing crash-orphans from rows that have no run BY DESIGN (unknown sender, late reply) — the exact subtle gap the audit warned about in its own sketch.
- **Keep current bare `{"status":"duplicate"}`** — rejected: fails the roadmap's "loser attaches to the existing run" and leaves the crash-orphan hole open.
- **Selected: single-transaction ingest (insert + routing reads + create_run commit together, enqueue after commit) so crash-orphans become impossible; loser reports the existing run_id when one exists, never creates/repairs.** Winner-aborts case verified: loser's blocked INSERT then succeeds and the loser creates the run — exactly-one-run holds in every interleaving. → D-9-09.

## Stuck-run recovery path (Claude's decision)

Alternatives considered:
- **Just lower STALE_THRESHOLD** — rejected alone: doesn't make stranding visible; too-low a value risks claiming live runs.
- **Operator force-retrigger bypassing the threshold** — rejected: adds a bypass that can claim a live run; with sweep-to-ERROR the existing retrigger already covers the operator action.
- **Auto-restarting sweep** — rejected: autonomous pipeline restarts violate the one-human-gate philosophy.
- **Selected: single-statement CAS sweep marking stale `{received, extracting, computed}` runs to ERROR with a Phase-8 error_detail, triggered on dashboard runs-list load (Render free tier has no background loops); operator recovers via the existing ERROR→retrigger. Threshold lowered from 5 min, exact value planner-bounded by worst-case LLM stage latency (90s–3min zone).** `awaiting_reply`/`awaiting_approval`/`approved` explicitly excluded and test-pinned. → D-9-10/11/12/13.

## Claude's Discretion

- Exact stale threshold value (within the D-9-13 evidence bound); sweep function name/wiring.
- Loser's existing-run lookup mechanism (source_email_id join vs header chain).
- Snapshot-write ordering inside `_clarify` (status-advance-last is the only locked part).
- Connection plumbing details for gateway's reserved/flip writes and the persist-txn open point.

## Deferred Ideas

- 260623-08 loop cap (own phase), 260623-01 security remainder (security slot) — reviewed, not folded.
- Guard-hardening unguarded `set_status` against swept-to-ERROR runs — revisit only if Phase 10's proof shows the window matters.
