---
phase: 5
reviewers: [codex]
reviewed_at: 2026-06-22T23:17:02Z
plans_reviewed: [05-01-PLAN.md, 05-02-PLAN.md, 05-03-PLAN.md, 05-04-PLAN.md, 05-05-PLAN.md, 05-06-PLAN.md, 05-07-PLAN.md]
codex_model: default (codex-cli 0.135.0)
overall_risk: HIGH (until outbound purpose-aware idempotency + alias-candidate binding fixed)
---

# Cross-AI Plan Review — Phase 5

> Single-reviewer run (Codex). Requested explicitly by the operator after the internal
> gsd-plan-checker passed. Codex reviews independently of the GSD planning loop, so its
> HIGH-severity findings below are NOT duplicates of the checker's — they are new blind spots.

## Codex Review

## Summary

The plan set is strong in structure and intent: it identifies the real load-bearing risks, sequences the core primitives before UI work, and treats `claim_status`, delivery recovery, PDF generation, and the alias write loop as separately testable slices. I would not execute it unchanged. The biggest gaps are around outbound idempotency semantics, alias-candidate binding after clarification, and strandable in-flight statuses. The plans are close, but several "exactly once / never silently hangs / learns safely" claims are not yet true under the described implementation.

## Strengths

- Clear wave sequencing: tests first, DB/status primitives before delivery, delivery before UI, alias learning isolated as droppable Wave 4.
- `claim_status` via conditional `UPDATE ... WHERE status=? RETURNING` is the right primitive for status-only gates.
- Removing `approved` from `_TERMINAL_STATUSES` correctly recognizes that Phase 5 makes `approved` an in-flight delivery state.
- The three-column dashboard contract directly serves the "honest operator gate" requirement.
- The PDF and confirmation composer are correctly kept pure/testable before wiring delivery.
- Alias write-side safety is correctly framed as a write-time guard, not just read-time reconciliation.
- D-15 is handled well structurally: Plan 07 can be dropped without blocking Beats 1 and 2.

## Concerns

- **HIGH — Outbound idempotency is under-specified and likely wrong for clarify + confirmation.** `_deliver` checks `get_outbound_message_id(run_id)` without distinguishing outbound purpose. If a run already sent a clarification, approval could mistake that clarification row for an existing confirmation and skip the confirmation send. CLAR-04 needs purpose-aware outbound rows: at least `clarification` vs `confirmation`.

- **HIGH — D-13c "outbound-pending" likely violates schema and does not prove exactly-once.** `email_messages.direction` appears scoped to inbound/outbound. Adding `outbound-pending` without schema changes may fail. More importantly, a pending intent row is not the same as a sent confirmation. If retry sees "pending" and skips send, it can falsely mark a never-sent email as delivered; if it ignores pending, it can double-send after a crash.

- **HIGH — Clarification send idempotency is not actually handled.** The plans guard confirmation delivery but do not add an idempotent guard to `_clarify`. Re-triggering an errored run from the start can resend the same clarification unless `_clarify` checks for an existing clarification outbound record by purpose.

- **HIGH — Resume/dead-worker strandability remains.** `resume_pipeline` claims `awaiting_reply → extracting`, but if the worker dies after the claim and before `record_run_error`, the run is stuck in `extracting`. D-13b explicitly names this class of state, but the UI only exposes re-trigger for `error` and `approved`.

- **HIGH — Alias-candidate binding at resume is not concrete enough to be safe.** The plan says to update `{original_token: resolved_employee_id}` after `_run_stages`, possibly from post-resume reconciliation. But the research itself says post-resume extraction likely contains the corrected name, not the original token. Matching original token to resolved employee remains unsolved, especially with multiple unresolved names.

- **HIGH — Alias-candidate capture includes ambiguous tokens.** Plan 07 captures `{name: None for name in decision.unresolved_names}`. D-04/D-01b says ambiguous/colliding tokens should not be stored as learning candidates, or should be flagged ineligible. Final write-side rejection prevents silent misroute, but the plan still violates the locked capture constraint.

- **MEDIUM — `SENT → RECONCILED` can still strand short of the required final state.** Since `sent` remains terminal, a crash or DB error after `set_status(SENT)` but before `set_status(RECONCILED)` leaves the run permanently `sent`. Decide whether `sent` is terminal-success or transitional; the current requirement says the run advances to `reconciled`.

- **MEDIUM — Alias write safety is not batch-safe.** `_write_aliases_if_safe` checks each candidate against the original roster. If multiple accepted aliases in one approval normalize to the same token or interact across employees, later checks may not see earlier writes. Update the synthetic roster after each accepted alias or validate the whole batch before writing.

- **MEDIUM — `POST /demo/send-test` may not be repeatable.** If it reuses a fixture `Message-ID`, the existing idempotency unique constraint can drop later demo clicks. The route should mint a fresh synthetic `Message-ID` per click while preserving the fixture body.

- **MEDIUM — DASH-04 drill-in is incomplete.** The eval plan renders metrics, chart, and a per-fixture table, but not the required raw fixture body beside expected vs actual extraction/decision. That is explicitly part of DASH-04.

- **MEDIUM — `compose_confirmation` timeout wiring may break fake LLM tests.** If `compose_confirmation` passes `timeout_s=` to arbitrary fake LLMs copied from clarification tests, fakes without `**kwargs` will raise and force the fallback, causing the "uses draft when present" test to fail.

- **LOW — Wave labeling is inconsistent.** The roadmap says 05-04 and 05-05 run concurrently, but 05-05 depends on 05-04. Sequential is probably correct, but update the wave notes to avoid executor confusion.

- **LOW — `load_line_items SELECT *` is risky.** If `paystub_line_items` has DB-only columns not accepted by `PaystubLineItem`, model validation can fail. Prefer explicit column selection matching the contract.

## Suggestions

- Add an outbound purpose/status model before implementing `_deliver`:
  - `purpose`: `clarification` or `confirmation`
  - `send_state`: `reserved`, `sent`, `failed`
  - unique key on `(run_id, purpose)`
  - replace `get_outbound_message_id(run_id)` with `get_outbound_message_id(run_id, purpose="confirmation")`

- Make `_clarify` idempotent too:
  - before drafting/sending, check existing `purpose="clarification"` row for the run
  - if already sent, skip duplicate send and leave/restore `awaiting_reply`

- Replace `outbound-pending` as a fake `direction` value with a real send-state field or a separate delivery-intent table. Do not overload `direction`.

- Add stale-state recovery for claimed in-flight statuses:
  - show re-trigger for stale `received`, `extracting`, `computing`, and `approved`, or
  - add a watchdog-style route that CAS-claims only if `updated_at < now() - interval`
  - avoid force-restarting fresh in-flight work without a stale threshold.

- Make alias binding explicit before Plan 07 executes. Acceptable options:
  - defer alias learning to a UI-confirmed mapping in the approval form
  - store clarification prompts with stable labels and parse/bind replies by label
  - only support alias learning for exactly one unresolved token per run, with a test proving the mapping
  - otherwise drop Plan 07 per D-15.

- Add tests for alias capture exclusions:
  - `D. Reyes` must not be stored as a learnable candidate, or must be stored with `eligible=false`
  - multiple unresolved names must bind deterministically or refuse learning.

- Make demo fixture replay generate a unique `Message-ID` on every click.

- Complete DASH-04 with either inline expandable fixture rows or a detail route that reads `eval/fixtures/<fixture_path>` and renders raw email beside expected vs actual results.

- Clarify `sent` semantics. If `reconciled` is the only successful terminal state, remove `sent` from terminal handling or add a recovery/advance route from `sent`.

## Risk Assessment

**HIGH** until outbound purpose-aware idempotency and alias-candidate binding are fixed. The plan quality is otherwise good, but the current version can still skip a required confirmation after a prior clarification, resend clarifications on re-trigger, strand runs in claimed in-flight states, and claim a safe alias-learning loop without a reliable original-token-to-employee binding algorithm. Once those are addressed, the plan would drop to **MEDIUM/LOW** execution risk, with most remaining issues being ordinary integration and UI polish.

---

## Consensus Summary

Single reviewer (Codex), so "consensus" = Codex's verdict cross-checked against the internal
gsd-plan-checker (which had passed). The two reviews are complementary, not contradictory: the
checker validated structure, coverage, dependency ordering, and locked-decision presence; Codex
attacked the *semantics* of the idempotency and alias-binding claims and found real holes the
checker accepted at face value.

### Agreed Strengths (Codex + internal checker)
- Wave sequencing (tests → primitives → delivery → UI; alias loop isolated as droppable Wave 4).
- `claim_status` conditional-UPDATE CAS is the correct primitive.
- Removing `approved` from `_TERMINAL_STATUSES` is correct for the new in-flight delivery state.
- Pure/testable PDF + confirmation composer before delivery wiring.
- D-15 droppability structurally sound.

### New HIGH-severity concerns from Codex (NOT caught by the internal checker — action needed)
1. **Purpose-blind outbound idempotency** — `get_outbound_message_id(run_id)` can match a prior
   *clarification* row and skip the *confirmation* send. Needs purpose-aware outbound
   `(run_id, purpose)` keying. **Directly threatens CLAR-04 correctness.**
2. **`_clarify` is not idempotent** — re-trigger from start can resend the clarification.
3. **D-13c `outbound-pending` overloads `email_messages.direction`** — likely schema-invalid, and
   a pending intent row ≠ proof-of-sent (can false-mark delivered OR double-send after crash).
4. **Alias-candidate binding at resume is unsolved** — resume re-extracts the *corrected* name, so
   the original-token→employee mapping isn't reliably reconstructable (worse with multiple
   unresolved names). The write-side D-01b guard prevents *misroute* but not *failed/garbled
   learning*. This is the schedule-risky beat D-15 already flags as the drop candidate.
5. **Capture stores ambiguous tokens** — Plan 07 captures all `unresolved_names` including
   colliding ones, violating the D-04 "exclude ambiguous at capture time" locked constraint
   (write-side guard is the backstop, not the only gate).
6. **Strandable in-flight states remain** — dead worker after the `resume` claim leaves
   `extracting` with no recovery UI; `SENT→RECONCILED` crash strands in terminal `sent`. D-13b's
   "no claimed state strands" invariant is not fully satisfied.

### Divergent Views (Codex vs internal checker)
- The internal checker rated D-13/D-13c **COVERED**; Codex rates the same area **HIGH risk**. Codex
  is correct on the semantics: presence of the mechanism ≠ correctness of the mechanism. The
  checker verified the intent row exists; Codex verified it doesn't actually prove exactly-once.
- The checker treated the alias loop as covered-and-droppable; Codex agrees it's droppable but
  argues the *binding algorithm itself* is unspecified — reinforcing D-15's "drop if tight."

### Lower-severity (MEDIUM/LOW) — fold in if replanning anyway
- Batch-safety of multi-alias writes in one approval; demo `Message-ID` reuse breaking replay;
  DASH-04 drill-in missing the raw-fixture-body column; `compose_confirmation` `timeout_s=` kwarg
  breaking fake-LLM tests lacking `**kwargs`; wave-label inconsistency (05-04/05-05); `SELECT *`
  on `load_line_items`.

### Recommended Disposition
Replan via `/gsd-plan-phase 5 --reviews`. The four idempotency/binding HIGHs (#1–#3, #5) are the
priority — they make the "exactly once" and "learns safely" claims false as written. #4 and #6
are genuine but partly mitigated by D-15 (drop the alias loop) and the existing error-wrap; the
clean fix for #6 is to add stale/in-flight recovery and decide `sent` terminality.
