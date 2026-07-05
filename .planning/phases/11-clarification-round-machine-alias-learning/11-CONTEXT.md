# Phase 11: Clarification Round Machine & Alias Learning - Context

**Gathered:** 2026-07-05
**Status:** Ready for planning

<domain>
## Phase Boundary

The multi-round clarification state machine becomes correct and unstrandable, and the alias-learning loop actually learns. Five coupled roadmap items, all traced to live findings:

1. **WR-05 fix** — round-aware clarification send guard: a genuinely new question always sends; a true duplicate is still suppressed. Today's purpose-only guard silently parks round 2+ at `awaiting_reply` with no email out.
2. **Round cap + operator escape** (260623-08, premise corrected: the failure is silent-stall, not spam) — after N non-converging rounds, route to a human instead of another send.
3. **Question-anchored reply extraction** — the outbound clarification's questions enter the resume extraction context so a bare "40" can't be blindly attributed.
4. **Alias-learning WRITE side becomes reachable** (260705-01) — bind on explicit client confirmation of the clarification *suggestion*, replacing the circular re-extraction evidence requirement, preserving the misname guard's never-learn-from-inference intent.
5. **CX-01/T-09-21 multi-round context loss closed** — the known-edge fixture in `tests/test_multiround_context_edge.py` flips its assertion; **WR-06** stale provenance and **WR-04** redelivered-reply handling fold into the same round/consumed state design.

Not in scope: security-hygiene items (260623-01), cosmetic items (locked out of v2 per REQUIREMENTS.md), a courtesy-email-to-client at escalation, a paid→paid cross-round diff state machine (fix (b) — rejected in favor of accumulation), full manual field editing from the escape state.

**Sequencing note:** ROADMAP marks Phase 11 as depending on Phase 10 (concurrency proof, not started as of this discussion). The user chose to discuss 11 first; decide at plan time whether Phase 10 executes first or whether the dependency is soft (fencing primitives the round machine could reuse).

**Prior decisions that constrain this phase (carried forward, not re-litigated):**
- D-9-01: no DB transaction spans an LLM or provider call; D-9-02: status-advance-last in every atomic unit.
- D-9-12: sweep scope stays exactly `{received, extracting, computed}` — this phase's recoverability mechanisms are separate from the sweep.
- One-human-gate philosophy: the operator escape hands off to a human; the system never starts guessing.
- The misname guard (NEW-2) is correct and its intent survives: aliases are never learned from inference, only from stated human evidence.
- Phase 7.5 lesson: tests assert persisted paid VALUES and downstream behavior, not labels.

</domain>

<decisions>
## Implementation Decisions

### Round identity & send guard (WR-05 + WR-04 + WR-06)
- **D-11-01 Round key = explicit counter.** New `payroll_runs.clarification_round INT` (default 0). The `_clarify` idempotency guard keys on **(purpose, round)** instead of purpose alone; `uq_email_run_purpose` widens to `UNIQUE(run_id, purpose, round)` so every round's outbound is a real, preserved row (no upsert-replace of history). Schema migration at the human checkpoint per the Phase 8 pattern.
- **D-11-02 Round lifecycle: increment at send, consume at claim.** The round increments inside `_clarify`'s post-send finalize transaction (status-advance-last, D-9-02). A new consumed marker on inbound reply rows (e.g. `email_messages.consumed_round`) is set when `resume_pipeline`'s CAS claim (`AWAITING_REPLY → EXTRACTING`) succeeds — the reply is "consumed" only once processing actually started.
- **D-11-03 WR-04 fix rides on consumed state.** On a duplicate webhook delivery carrying reply headers: if the persisted reply row has `consumed_round IS NULL` and the run is still `awaiting_reply`, re-schedule `_resume_pipeline` (the CAS claim makes double-scheduling safe). A consumed reply's redelivery stays a no-op duplicate.
- **D-11-04 WR-06 fix: clear at retrigger.** At the retrigger seam (where reply context is knowingly discarded), clear `clarified_fields` + `pre_clarify_extracted` + reset round state (counter and suggestion/candidate state per D-11-14) — "context lost means ALL of it." `is_round_2 = bool(clarified)` then correctly sees a fresh run; provenance badges cannot outlive the data that produced them.
- **D-11-05 Stranded-unconsumed-reply recovery: auto re-schedule on dashboard load.** Same trigger point as the D-9-11 sweep: the runs-list load finds `awaiting_reply` runs having an unconsumed linked reply older than the stale threshold and re-schedules `_resume_pipeline`. This is NOT a D-9-10 autonomous-restart violation: the client's reply already authorized this processing (the webhook resume path is identically autonomous); this completes interrupted work. CAS claim gates double-scheduling.

### Round cap & operator escape (260623-08)
- **D-11-06 Escape state = new status `needs_operator`.** Added to the `payroll_runs.status` enum + CHECK constraint (idempotent DO-block migration, Phase 8 pattern, applied live at a blocking human checkpoint). Excluded from sweep scope, retrigger's stale-claim scope, and D-11-05 auto-resume by design. Own dashboard badge. NOT ERROR-with-sentinel: ERROR's only exit (retrigger-from-original) discards exactly the reply context a human needs.
- **D-11-07 Cap = 3 total rounds, one constant.** When `clarification_round >= 3` at the next would-be send, escalate to `needs_operator` instead of sending. Counts ALL clarification sends per run regardless of purpose; single module-level constant (STALE_THRESHOLD style, documented derivation).
- **D-11-08 Operator exits: resolve + resume, or reject.** The run-detail page for a `needs_operator` run gains a minimal resolve form: per unresolved name, a dropdown of the business's roster employees (the LLM suggestion pre-selected as advisory copy only) + a Resume action that applies the mapping deterministically and re-runs from the last combined context; plus the existing Reject. The human states the name-match — a decision, not a guess; the no-guess guarantee holds.
- **D-11-09 Silent handoff.** No client-facing email at escalation; no new outbound purpose or template. The client's next email is the normal post-approval confirmation.

### Reply attribution & context (item 2 + CX-01)
- **D-11-10 Question anchor = structured asked-summary.** `_combined_context_email` gains a deterministic, code-owned "QUESTIONS WE ASKED" section rendered from decision facts (unresolved names, missing/regressed fields per employee) — the same asked-set the round machine tracks. NOT the LLM-drafted outbound body: the anchor's content stays code-owned and string-for-string testable.
- **D-11-11 No-guess extraction policy: absent-if-unaddressed, re-ask.** The resume extraction prompt instructs: an asked field may only be filled if the reply attributably answers it (names the employee, or only ONE question was asked so a bare answer is unambiguous); otherwise leave it absent. Still-missing fields flow through the normal `decide` gate → a genuinely NEW, narrower question — which now sends, thanks to D-11-01. Under-attribution degrades to a second question, never a silent stall and never a guessed paystub.
- **D-11-12 CX-01 closure = accumulate all reply bodies (fix (a)).** `_combined_context_email` combines ORIGINAL + ALL consumed replies in round order (delimited and round-numbered). A Round-1 correction ("30, not 40") stays in every later round's context and cannot silently revert. Bounded by the cap (≤3 replies). The known-edge fixture `tests/test_multiround_context_edge.py::test_multi_round_context_loss_known_edge` flips its assertion per its own flip-on-fix instructions. Fix (b) (diff vs last-persisted extraction) is explicitly rejected — no second diff state machine.
- **D-11-13 Reply source = `email_messages` rows.** At resume, load the run's inbound rows with `consumed_round` set (plus the currently-being-consumed reply), ordered by round — enabled by the WR-03 `link_email_to_run` backfill + D-11-02's consumed marker. No duplicate JSONB copy of bodies on the run row; the email table is the single source of truth.

### Alias bind-on-confirmation (260705-01)
- **D-11-14 Suggestion persistence = richer `alias_candidates` values.** Extend the JSONB from `{token: null|bound_id}` to `{token: {suggested: id|null, bound: id|null}}` — one column owns the capture→suggest→bind lifecycle; D-11-04's clear-at-retrigger covers it; no cross-column sync. The suggestion is written when the clarification sends (where `suggest_employees` runs). Write side (`_write_aliases_if_safe`) and its tests update to the new shape; the existing write-time collision re-check is preserved.
- **D-11-15 Bind evidence = deterministic post-resume resolution of the SUGGESTED employee.** Bind `{token: suggested_id}` iff (a) the suggested employee newly appears as resolved in the post-resume reconciliation AND (b) the token is gone from unresolved submitted names. A bare "yes" works because the D-11-10 anchor lets extraction attribute it to the proposed canonical name. The misname case cannot slip: "no, I meant James" resolves a NON-suggested id → no bind (and nobody proposed James for the token, so the original misroute class stays impossible). No LLM call sits in the bind chain — the LLM proposed (advisory), the human confirmed (reply), code verified (reconciliation facts).
- **D-11-16 Operator resolve form binds via checkbox, default ON.** Each manual name mapping in the D-11-08 form carries a "remember this alias" checkbox, checked by default — operator mapping is the strongest human-stated evidence, but a one-off typo need not become a permanent `known_aliases` entry. Unchecked = resolve this run only.
- **D-11-17 Proof standard = full-loop stops-asking test.** One hermetic integration test drives the REAL path end-to-end: nickname email → capture → clarification with suggestion → confirming reply → resume binds → operator approves → `known_aliases` written → a SECOND submission with the same nickname resolves via stored-alias with NO clarification. The existing binding tests that fake the resolved state are updated to the new shape, and at least the full-loop test must exercise real resolution (the todo's core finding: faked-state tests kept an unreachable loop green).

### Claude's Discretion
- Exact column/marker names (`clarification_round`, `consumed_round`, etc.), constraint naming, and migration DDL mechanics (follow the Phase 8 idempotent DO-block pattern).
- Where the cap check lives inside `_clarify`/`_run_stages` and the exact escalation write sequence (must respect D-9-02 status-advance-last).
- Delimiter/numbering format of the accumulated combined context and the asked-summary section wording.
- Resolve-form UI details (layout, badge styling) within the existing Jinja2/no-SPA dashboard idiom.
- How the operator-resolve Resume path re-enters the pipeline (which existing entry point it reuses), provided the mapping is applied deterministically before reconcile.
- Whether `suggest_employees` output for multi-name clarifications persists one suggestion per token or only the single-capture token (capture is currently single-token-only, D-04 — widening capture is NOT in scope).

### Folded Todos
- **260705-02 — Clarify round machine redesign (priority: high).** WR-05 silent-park, ambiguous-reply attribution, WR-06/WR-04 fold-in. This todo IS items 1/2/3/5 of the phase; resolved by D-11-01…D-11-13.
- **260705-01 — Alias-learning bind unreachable (priority: medium).** The circular evidence requirement and its bind-on-confirmation solution sketch. Resolved by D-11-14…D-11-17.
- **260623-08 — Re-clarification loop cap (priority: low, analysis superseded).** Its premise ("sends a fresh email each round") is false post-tracing — the real failure is silent-stall — but its ask (round cap + operator escape) lands here as D-11-06…D-11-09.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase definition + source findings
- `.planning/ROADMAP.md` — Phase 11 entry: goal items (1)–(5), dependency on Phase 10
- `.planning/todos/pending/260705-02-clarify-round-machine-redesign.md` — the traced WR-05 repro, attribution failure modes, and solution sketch (file:line pointers current as of 2026-07-05)
- `.planning/todos/pending/260705-01-alias-learning-bind-unreachable.md` — the circular-evidence trace, why reply phrasing cannot fix it, and the bind-on-confirmation design intent
- `.planning/todos/pending/260623-08-reclarification-loop-cap.md` — cap/escape ask + the 2026-07-05 premise correction
- `.planning/phases/09-atomic-data-integrity/09-REVIEW.md` — WR-03 (fixed; `link_email_to_run`), WR-04, WR-05 (incl. fix options a/b/c), WR-06 full findings with file:line
- `.planning/phases/09-atomic-data-integrity/09-CONTEXT.md` — deferred section: the CX-01 multi-round context-loss verified chain + fix dispositions (a)/(b)/(c); D-9-01/02/10/11/12 decisions this phase must respect

### Code touch points (verified during discussion, 2026-07-04/05)
- `app/pipeline/orchestrator.py` — `_clarify` idempotency guard (~:986-1010), alias capture gates (~:1039-1095), resume binding + misname guard (~:660-730), `_write_aliases_if_safe` (~:1200+), `_combined_context_email` (~:837-855), `is_round_2 = bool(clarified)` + CX-03 terminal-set construction (~:310-335)
- `app/main.py` — webhook duplicate outcome (~:385-454), `_route_reply`/`_finish_reply_resume`/`_resume_pipeline` (~:560-615), retrigger claimable scope + the deliberate sweep-vs-retrigger scope divergence comment (~:760-775)
- `app/db/repo.py` — `get_outbound_message_id` (purpose-scoped guard lookup, ~:1055), `insert_email_message` upsert on (run_id, purpose), `link_email_to_run` (:199), `find_awaiting_reply_for_header`
- `app/db/schema.sql` — `payroll_runs.status` CHECK (needs `needs_operator` added), `uq_email_run_purpose` UNIQUE(run_id, purpose) (needs round), `alias_candidates`/`pre_clarify_extracted`/`clarified_fields` JSONB columns, purpose CHECK (~:209-260)
- `tests/test_multiround_context_edge.py` — the CX-01 known-edge fixture whose assertion flips on D-11-12
- `tests/test_alias_write.py` (~:720-1100) — binding tests that fake resolved state; update per D-11-17

### Prior-phase contracts that constrain this work
- `.planning/phases/07.5-clarification-reply-field-regression/07.5-CONTEXT.md` — clarified_fields four-outcome state machine, snapshot semantics, suppress_detection/backfill sets the round machine must not break
- Phase 8 pattern for live schema migration at a blocking human checkpoint (`.planning/phases/08-data-layer-hygiene-diagnostics/08-CONTEXT.md`)
- STATE.md accumulated decisions: D-12 (two sanctioned status writers), D-13b (retrigger machinery), D-13c (reserved/sent outbound lifecycle), CLAR-04 (the idempotency intent the round-aware guard must preserve for true duplicates)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `link_email_to_run` (repo.py:199, WR-03 fix) — the reply-row↔run linkage the consumed-round marker and reply accumulation build on.
- `claim_status` CAS — already gates resume entry (`AWAITING_REPLY → EXTRACTING`); D-11-02/03/05 all lean on it for double-scheduling safety.
- D-9-11's dashboard-load trigger (runs-list route calls the sweep) — D-11-05's auto-re-schedule hooks the same point.
- `suggest_employees` — already computes the token→employee suggestion at clarify time; D-11-14 persists what it already produces.
- Phase 8 idempotent DO-block migration pattern — reused for the status CHECK + uq constraint changes.
- The `_RunStagesResult`/`clarify_deferred` seam and the D-9-05/06 transaction shapes — the round increment and consumed marker land inside existing atomic units, not new ones.

### Established Patterns
- Status column IS the orchestration engine — `needs_operator` is a first-class state with explicit entry/exit, not a flag.
- Two sanctioned status writers only (`set_status`, `claim_status`) — escalation and operator-resume use these shapes.
- Scope lists (sweep, retrigger, auto-resume) deliberately diverge and are each pinned by tests — `needs_operator` must be added to the exclusion tests.
- LLM roles stay extraction + advisory copy; every new judgment introduced this phase (bind, attribution fallback, escalation) is deterministic code over persisted facts.
- Hermetic tests must not land in `tests/test_resume_pipeline.py` (module-level DATABASE_URL skip guard — the 09-REVIEWS Codex finding); new offline tests go in unguarded modules.

### Integration Points
- `_clarify` — guard key change, round increment, suggestion persistence, cap check all land here.
- `resume_pipeline` — consumed marker at claim, bind-on-confirmation check after `_run_stages`, accumulated-context assembly before extraction.
- Webhook `inbound()` duplicate path — WR-04 re-schedule.
- Runs-list route — D-11-05 unconsumed-reply re-schedule beside the existing sweep call.
- Run-detail template + approve/reject routes — `needs_operator` badge, resolve form, resume action.
- Phase 10 (if executed first) may add fencing primitives; the round machine's CAS-based consume/claim design should compose with, not depend on, them.

</code_context>

<specifics>
## Specific Ideas

- The user answered a mid-discussion question about reply routing: run-level attachment (header-chain → run) is understood to be already-solid v1 behavior; this phase's value is making the *consumption* of the answer correct — right employee, right field, every round, under redelivery. Frame the phase writeup that way.
- The confirmation-evidence chain for alias learning should be narratable in one line: "the LLM proposed, the human confirmed, code verified" — it extends the project's deterministic-decisioning story rather than diluting it.

</specifics>

<deferred>
## Deferred Ideas

### Reviewed Todos (not folded)
- **260623-01 — Phase 5 review warnings remainder** (Content-Disposition filename injection, path containment, LLM retry-prompt scrub): security hygiene, unrelated to the round machine. Stays pending for a security-flavored slot.
- **260623-02/03/04/05 — cosmetic items** (frontend progressive enhancement, paystub YTD, eval-chart restyle, fixture category labels): locked out of v2 scope per REQUIREMENTS.md; not re-litigated.

### Noted for later
- **Paid→paid cross-round value-change diff (CX-01 fix (b))** — rejected for this phase in favor of accumulation; revisit only if a future finding shows accumulation alone misses a real unrequested-change case.
- **Courtesy email at escalation** — deliberately not built (D-11-09); a future polish phase could add it if real-client usage shows confusion during the silent-handoff window.
- **Widening alias capture beyond single-token (D-04)** — explicitly out of scope; the bind redesign works within the existing single-candidate capture.

</deferred>

---

*Phase: 11-Clarification Round Machine & Alias Learning*
*Context gathered: 2026-07-05*
