---
phase: 5
reviewers: [codex, codex-round2, codex-round3]
reviewed_at: 2026-06-22T23:17:02Z
round2_reviewed_at: 2026-06-22T23:40:00Z
plans_reviewed: [05-01-PLAN.md, 05-02-PLAN.md, 05-03-PLAN.md, 05-04-PLAN.md, 05-05-PLAN.md, 05-06-PLAN.md, 05-07-PLAN.md]
codex_model: default (codex-cli 0.135.0)
overall_risk: NOT-READY (round 3 — all 9 round-2 findings + COMPUTING RESOLVED; 1 NEW HIGH: send_state guard + uq_email_run_purpose interact → insert collides on reserved/failed row, needs ON CONFLICT DO UPDATE)
round1_status: addressed via reviews-mode replan (commit 1a8f066) — see round-2 verification below
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

---

# Cross-AI Plan Review — Phase 5 — ROUND 2 (verification of fixes)

> After the round-1 findings were folded in via the reviews-mode replan (commit 1a8f066),
> Codex re-reviewed the revised plans to confirm resolution and hunt for new issues.
> Two round-2 HIGH findings were spot-verified by the orchestrator against the actual
> artifacts and CONFIRMED real:
> - DDL: 05-03 line 183 uses `ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS` — INVALID Postgres syntax (Postgres has ADD COLUMN IF NOT EXISTS but NOT ADD CONSTRAINT IF NOT EXISTS); would crash bootstrap.
> - Collision: `deterministic_match` returns None for BOTH no-match AND ambiguous collision (reconcile_names.py:32-35), so the 05-07 capture-time guard would still capture "D. Reyes" as a learnable candidate — capture-time exclusion is NOT actually achieved (write-side backstop still catches it).

## Codex Round-2 Review

## Prior-Findings Resolution Table

| Finding | Status | Evidence |
|---|---|---|
| HIGH #1: purpose-blind `get_outbound_message_id(run_id)` could skip confirmation after clarification | RESOLVED | Plan 03 changes signature to `get_outbound_message_id(run_id, purpose)` and filters `AND purpose = %s` in [05-03-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-03-PLAN.md:151>). Plan 05 calls it with `purpose='confirmation'` in `_deliver` in [05-05-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-05-PLAN.md:180>). |
| HIGH #2: `_clarify` not idempotent | RESOLVED | Plan 05 adds a pre-send guard using `purpose='clarification'`, skips duplicate send, and restores `AWAITING_REPLY` in [05-05-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-05-PLAN.md:167>). Tests are specified in Plan 01/02. |
| HIGH #3: `outbound-pending` invalid and pending row not proof of sent | PARTIALLY RESOLVED | Invalid `direction` overload is fixed: Plan 03 adds `purpose`/`send_state` columns in [05-03-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-03-PLAN.md:171>) and Plan 05 forbids `outbound-pending` in [05-05-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-05-PLAN.md:150>). Still short: the read guard is still “row exists by purpose,” not “sent row exists,” so `reserved`/`failed` semantics are not actually wired. |
| HIGH #4: alias binding at resume unsolved | PARTIALLY RESOLVED | Plan 07 scopes learning to exactly one unresolved token in [05-07-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-07-PLAN.md:63>). That removes multi-token ambiguity, but the resume update still says to match the original token against post-resume submitted names in [05-07-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-07-PLAN.md:228>), which is the original failure mode. |
| HIGH #5: ambiguous/colliding tokens captured | PARTIALLY RESOLVED | Plan 07 states capture-time exclusion in [05-07-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-07-PLAN.md:76>). But the action block uses `deterministic_match`; that returns `None` for both no-match and collision, so a colliding token like `D. Reyes` can still be treated as “genuinely unresolved” and stored. |
| HIGH #6: strandable in-flight states / `sent` terminality | RESOLVED for route coverage, PARTIAL for concurrency | Plan 05 removes `APPROVED` terminality via Plan 03, adds stale recovery for `received/extracting/computing/sent`, and treats `reconciled` as the only success terminal in [05-05-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-05-PLAN.md:81>). Remaining risk: stale retry is not fenced against a slow original worker. |
| MEDIUM: batch-unsafe multi-alias writes | RESOLVED | Plan 07 refreshes `current_roster` after each accepted alias write in [05-07-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-07-PLAN.md:252>). |
| MEDIUM: demo send-test reuses fixture `Message-ID` | RESOLVED | Plan 06 requires uuid4 synthetic Message-ID per click in [05-06-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-06-PLAN.md:297>). |
| MEDIUM: DASH-04 drill-in missing raw fixture body | PARTIALLY RESOLVED | Plan 06 adds a `Raw Input` column in [05-06-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-06-PLAN.md:172>), but current `eval/summary.json` does not include raw body fields; the plan allows rendering `—`, which does not satisfy the actual drill-in requirement. |
| MEDIUM: `compose_confirmation timeout_s` breaks fake LLM stubs | RESOLVED | Plan 02 requires fake stubs to accept `**kwargs` in [05-02-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-02-PLAN.md:124>); Plan 04 updates `call_text`/timeout handling in [05-04-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-04-PLAN.md:198>). |
| LOW: 05-04/05-05 mislabeled concurrent | PARTIALLY RESOLVED | Plan metadata is fixed: 05-05 is wave 3 and depends on 05-04 in [05-05-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-05-PLAN.md:5>). The roadmap excerpt still says they run concurrently. |
| LOW: `load_line_items SELECT *` | PARTIALLY RESOLVED | Plan 05 requires explicit columns in [05-05-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/05-dashboard-delivery/05-05-PLAN.md:207>), but the proposed example selects `additional_medicare_not_modeled`, which is not in current `paystub_line_items`, and omits required `created_at`. |

## New Issues

- **HIGH: Plan 03 DDL is not safely executable as written.** `ALTER TABLE email_messages ADD COLUMN...` is instructed before the table exists, and `ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS` is not valid Postgres syntax. Use `ALTER TABLE IF EXISTS` after table creation and a `DO $$ ... pg_constraint ... ALTER TABLE ADD CONSTRAINT ... $$` block, matching the existing FK pattern.

- **HIGH: `send_state` state machine still conflates reserved/failed/sent.** `get_outbound_message_id(run_id, purpose)` should either filter `send_state='sent'` when proving delivery, or the system needs explicit `reserve_outbound_send` / `mark_outbound_sent` / `mark_outbound_failed` helpers. As planned, a future `reserved` or `failed` row can still make retry skip as if sent.

- **HIGH: stale `received -> received` CAS is not exclusive.** Plan 05’s stale retry can call `claim_status(run_id, RECEIVED, RECEIVED)`. Because the status does not change, two concurrent retrigger clicks can both return true and enqueue duplicate workers. Claim stale `received` to `extracting`, or add an `updated_at`/attempt-token predicate.

- **MEDIUM: stale re-trigger has no worker fencing.** A slow original worker can continue after the UI declares the run stale and starts a second worker. Status CAS reduces some downstream damage, but it does not prevent stale writes from the old attempt. An `attempt_id` or updated-at compare in write helpers would make this robust.

- **MEDIUM: Plan 01 and Plan 07 alias-capture tests conflict.** Plan 01 expects a multi-unresolved run to capture only the unambiguous token; Plan 07’s single-token-only rule expects no capture at all for 2+ unresolved names. That will produce contradictory test guidance.

- **MEDIUM: inbound rows get `send_state='sent'` by default.** Because `send_state` is `NOT NULL DEFAULT 'sent'` on all `email_messages`, inbound rows become “sent” too. Queries filter `direction='outbound'`, so this is not immediately fatal, but it weakens the audit semantics. Prefer nullable `send_state` with a direction-aware check.

## Updated Risk Assessment

**Overall risk: MEDIUM-HIGH.** The major prior idempotency holes are mostly addressed: purpose-aware confirmation/clarification guards, no `outbound-pending` direction value, stale recovery coverage, fresh demo Message-IDs, and fake-LLM timeout compatibility are all materially better. I would not drop this to MEDIUM yet because Plan 03’s DDL can fail outright, the new `send_state` model does not yet define real reserve/sent/failed behavior, and the alias learning plan remains internally inconsistent around collision detection and resume binding.

---

# Cross-AI Plan Review — Phase 5 — ROUND 3 (verify round-2 fixes)

> After the round-2 fixes (commits 623f41b, 110f8d6) and the internal-checker COMPUTING fix
> (commit 86bb27b), Codex re-reviewed. Verdict: all 9 round-2 findings + the COMPUTING blocker
> are RESOLVED. ONE new HIGH found — an INTERACTION between two round-2 fixes:
> filtering the already-sent guard to send_state='sent' (so reserved/failed don't count) means
> _deliver no longer skips on a reserved/failed row, but send_outbound then INSERTs a new
> (run_id, purpose) row that collides with the new uq_email_run_purpose UNIQUE constraint.
> Fix: the send path must UPSERT (ON CONFLICT (run_id, purpose) DO UPDATE), not plain INSERT.
> Plus MEDIUM NEW-2 (single-token resume bind assumes exactly one resolved match — breaks on
> realistic multi-employee runs; needs pre-vs-post resolved-id diff) and LOW NEW-3 (05-06 still
> names some non-existent top-level summary.json fields; use nested .decision/.extraction paths).

## Codex Round-3 Review

## Round-2 Findings Resolution Table

| Finding | Status | Evidence |
|---|---:|---|
| HIGH R2-1: invalid `ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS` | RESOLVED | Plan 03 Task 1 now requires a `DO $$` block guarded by `pg_constraint` for `uq_email_run_purpose`; verification explicitly greps that `ADD CONSTRAINT IF NOT EXISTS` is absent. |
| HIGH R2-2: purpose-only send guard skipped on reserved/failed rows | RESOLVED for read guard | Plan 03 Task 1 changes `get_outbound_message_id(run_id, purpose)` to filter `direction='outbound' AND purpose=%s AND send_state='sent'`; `send_state` is nullable with no default. See new HIGH issue below for the write/retry side. |
| HIGH R2-3: stale `received → received` CAS no-op | RESOLVED | Plan 05 Task 2 now claims stale `RECEIVED → EXTRACTING`, and all other stale in-flight states `→ RECEIVED`; it also adds `test_two_concurrent_stale_retriggers_only_one_wins`. |
| PARTIAL R2-4: capture collision used `deterministic_match is None` | RESOLVED | Plan 07 Task 2 now counts `candidate_ids = exact_ids | alias_ids`; `len > 1` excludes colliders like `D. Reyes`, and tests explicitly assert collision despite `deterministic_match` returning `None`. |
| PARTIAL R2-5: resume binding matched original token against corrected submitted names | RESOLVED in intended direction | Plan 07 Task 2 now specifies direct single-token binding: one `None` alias candidate is bound to the resolved employee id after resume, with no submitted-name matching. See new MEDIUM issue for multi-employee resume coverage. |
| MEDIUM R2-6: Plan 01 vs Plan 07 alias-capture test conflict | RESOLVED | Plan 01 now has three distinct stubs: multi-token no capture, single zero-candidate capture, single colliding token no capture. Plan 07 matches the same single-token-only rule. |
| MEDIUM R2-7: DASH-04 drill-in rendered `—` instead of raw fixture body | RESOLVED | Plan 06 Task 2 enriches each `summary["per_fixture"]` row by reading `eval/fixtures/<fixture_path>` and storing `raw_body`; template uses `fixture.raw_body`, not `—`. |
| MEDIUM R2-8: inbound rows got `send_state='sent'` by default | RESOLVED | Plan 03 DDL makes `send_state TEXT CHECK (...)` nullable, no default; inbound rows keep `send_state=NULL`. |
| LOW R2-9: `load_line_items` listed nonexistent column and omitted `created_at` | RESOLVED | Plan 05 Task 1 explicit SELECT excludes `additional_medicare_not_modeled` and includes `created_at`. |
| Internal checker: `RunStatus.COMPUTING` does not exist | RESOLVED | Plans now use `RunStatus.COMPUTED`; remaining `COMPUTING` references are warnings saying it is not valid. |

## New Issues

**HIGH NEW-1: Sent-only guard plus `UNIQUE(run_id, purpose)` can still strand retries.**  
Plan 03 correctly makes `get_outbound_message_id` ignore `reserved`/`failed`, but the same plan adds `uq_email_run_purpose UNIQUE(run_id, purpose)`. Plan 05’s gateway path is still described as an insert into `email_messages`, not an update/upsert of an existing non-sent row. If a `reserved` or `failed` row exists, `_deliver` will not skip, then `send_outbound` will try to insert another `(run_id, purpose)` row and hit the unique constraint. Fix by either making the send path reuse/update non-sent rows with `ON CONFLICT (run_id, purpose) DO UPDATE ...`, or changing the uniqueness model, then add a test with existing `reserved` and `failed` rows.

**MEDIUM NEW-2: Plan 07 resume binding assumes exactly one resolved match after resume.**  
In normal multi-employee payroll, post-resume reconciliation may include several resolved employees: already-resolved original employees plus the corrected one. Plan 07 says to bind only if there is exactly one resolved match, so alias learning can silently skip in realistic runs. Fix by comparing pre-resume vs post-resume matched employee ids, or otherwise identifying the single newly resolved employee, and add a test with one already-resolved employee plus one corrected alias.

**LOW NEW-3: Plan 06 eval table still names some nonexistent top-level fields.**  
The plan correctly notes `per_fixture` has nested `extraction` and `decision`, but the template instructions still mention top-level `expected_decision`, `actual_decision`, and `extraction_f1`. Use `fixture.decision.expected_final_action`, `fixture.decision.final_action`, and `fixture.extraction.f1`.

## Updated Risk Assessment

Round-2 findings are materially closed, but the revised plan set is **not ready to execute as-is** because NEW-1 is a HIGH execution defect in the idempotent send-state design. After adding the non-sent-row retry/update path and its tests, the residual risk drops to medium, mostly around optional Plan 07 alias learning.
