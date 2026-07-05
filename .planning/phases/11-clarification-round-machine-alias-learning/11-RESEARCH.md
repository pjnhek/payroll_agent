# Phase 11: Clarification Round Machine & Alias Learning - Research

**Researched:** 2026-07-05
**Domain:** Internal state-machine redesign (multi-round clarification + alias learning) over the existing FastAPI/psycopg/Supabase stack — no new external dependencies
**Confidence:** HIGH (every claim traced against live source in this session; file:line refs verified 2026-07-05)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Round identity & send guard (WR-05 + WR-04 + WR-06)**
- **D-11-01 Round key = explicit counter.** New `payroll_runs.clarification_round INT` (default 0). The `_clarify` idempotency guard keys on **(purpose, round)** instead of purpose alone; `uq_email_run_purpose` widens to `UNIQUE(run_id, purpose, round)` so every round's outbound is a real, preserved row (no upsert-replace of history). Schema migration at the human checkpoint per the Phase 8 pattern.
- **D-11-02 Round lifecycle: increment at send, consume at claim.** The round increments inside `_clarify`'s post-send finalize transaction (status-advance-last, D-9-02). A new consumed marker on inbound reply rows (e.g. `email_messages.consumed_round`) is set when `resume_pipeline`'s CAS claim (`AWAITING_REPLY → EXTRACTING`) succeeds — the reply is "consumed" only once processing actually started.
- **D-11-03 WR-04 fix rides on consumed state.** On a duplicate webhook delivery carrying reply headers: if the persisted reply row has `consumed_round IS NULL` and the run is still `awaiting_reply`, re-schedule `_resume_pipeline` (the CAS claim makes double-scheduling safe). A consumed reply's redelivery stays a no-op duplicate.
- **D-11-04 WR-06 fix: clear at retrigger.** At the retrigger seam (where reply context is knowingly discarded), clear `clarified_fields` + `pre_clarify_extracted` + reset round state (counter and suggestion/candidate state per D-11-14) — "context lost means ALL of it." `is_round_2 = bool(clarified)` then correctly sees a fresh run; provenance badges cannot outlive the data that produced them.
- **D-11-05 Stranded-unconsumed-reply recovery: auto re-schedule on dashboard load.** Same trigger point as the D-9-11 sweep: the runs-list load finds `awaiting_reply` runs having an unconsumed linked reply older than the stale threshold and re-schedules `_resume_pipeline`. This is NOT a D-9-10 autonomous-restart violation: the client's reply already authorized this processing (the webhook resume path is identically autonomous); this completes interrupted work. CAS claim gates double-scheduling.

**Round cap & operator escape (260623-08)**
- **D-11-06 Escape state = new status `needs_operator`.** Added to the `payroll_runs.status` enum + CHECK constraint (idempotent DO-block migration, Phase 8 pattern, applied live at a blocking human checkpoint). Excluded from sweep scope, retrigger's stale-claim scope, and D-11-05 auto-resume by design. Own dashboard badge. NOT ERROR-with-sentinel: ERROR's only exit (retrigger-from-original) discards exactly the reply context a human needs.
- **D-11-07 Cap = 3 total rounds, one constant.** When `clarification_round >= 3` at the next would-be send, escalate to `needs_operator` instead of sending. Counts ALL clarification sends per run regardless of purpose; single module-level constant (STALE_THRESHOLD style, documented derivation).
- **D-11-08 Operator exits: resolve + resume, or reject.** The run-detail page for a `needs_operator` run gains a minimal resolve form: per unresolved name, a dropdown of the business's roster employees (the LLM suggestion pre-selected as advisory copy only) + a Resume action that applies the mapping deterministically and re-runs from the last combined context; plus the existing Reject. The human states the name-match — a decision, not a guess; the no-guess guarantee holds.
- **D-11-09 Silent handoff.** No client-facing email at escalation; no new outbound purpose or template. The client's next email is the normal post-approval confirmation.

**Reply attribution & context (item 2 + CX-01)**
- **D-11-10 Question anchor = structured asked-summary.** `_combined_context_email` gains a deterministic, code-owned "QUESTIONS WE ASKED" section rendered from decision facts (unresolved names, missing/regressed fields per employee) — the same asked-set the round machine tracks. NOT the LLM-drafted outbound body: the anchor's content stays code-owned and string-for-string testable.
- **D-11-11 No-guess extraction policy: absent-if-unaddressed, re-ask.** The resume extraction prompt instructs: an asked field may only be filled if the reply attributably answers it (names the employee, or only ONE question was asked so a bare answer is unambiguous); otherwise leave it absent. Still-missing fields flow through the normal `decide` gate → a genuinely NEW, narrower question — which now sends, thanks to D-11-01. Under-attribution degrades to a second question, never a silent stall and never a guessed paystub.
- **D-11-12 CX-01 closure = accumulate all reply bodies (fix (a)).** `_combined_context_email` combines ORIGINAL + ALL consumed replies in round order (delimited and round-numbered). A Round-1 correction ("30, not 40") stays in every later round's context and cannot silently revert. Bounded by the cap (≤3 replies). The known-edge fixture `tests/test_multiround_context_edge.py::test_multi_round_context_loss_known_edge` flips its assertion per its own flip-on-fix instructions. Fix (b) (diff vs last-persisted extraction) is explicitly rejected — no second diff state machine.
- **D-11-13 Reply source = `email_messages` rows.** At resume, load the run's inbound rows with `consumed_round` set (plus the currently-being-consumed reply), ordered by round — enabled by the WR-03 `link_email_to_run` backfill + D-11-02's consumed marker. No duplicate JSONB copy of bodies on the run row; the email table is the single source of truth.

**Alias bind-on-confirmation (260705-01)**
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

### Deferred Ideas (OUT OF SCOPE)
- **260623-01 — Phase 5 review warnings remainder** (Content-Disposition filename injection, path containment, LLM retry-prompt scrub): security hygiene, unrelated to the round machine. Stays pending for a security-flavored slot.
- **260623-02/03/04/05 — cosmetic items** (frontend progressive enhancement, paystub YTD, eval-chart restyle, fixture category labels): locked out of v2 scope per REQUIREMENTS.md; not re-litigated.
- **Paid→paid cross-round value-change diff (CX-01 fix (b))** — rejected for this phase in favor of accumulation; revisit only if a future finding shows accumulation alone misses a real unrequested-change case.
- **Courtesy email at escalation** — deliberately not built (D-11-09); a future polish phase could add it if real-client usage shows confusion during the silent-handoff window.
- **Widening alias capture beyond single-token (D-04)** — explicitly out of scope; the bind redesign works within the existing single-candidate capture.
</user_constraints>

<phase_requirements>
## Phase Requirements

ROADMAP marks requirements as "TBD — derive at plan time." REQUIREMENTS.md has no Phase 11 IDs yet. The following derived IDs map the phase goal's five items plus the folded review findings to concrete, testable requirements. The planner should register these (or renamed equivalents) in REQUIREMENTS.md's traceability table. All are MONEY-class follow-ups per the roadmap note.

| ID | Description | Source finding | Research Support |
|----|-------------|----------------|------------------|
| CLAR2-01 | A genuinely new clarification question always sends; a true duplicate (re-trigger of the same round) is still suppressed. No run can silently park at `awaiting_reply` with no email out. | WR-05 (09-REVIEW.md:68-75), 260705-02 | Guard-key change traced at `orchestrator.py:1022-1037`; round column design in Architecture Patterns §1; pitfalls #1-#3 |
| CLAR2-02 | After 3 total clarification rounds, the run escalates to a first-class `needs_operator` status instead of sending; the operator can resolve names deterministically and resume, or reject. | 260623-08 (premise-corrected) | Status-addition checklist in Pitfalls #4; escalation write sequence in Architecture Patterns §2 |
| CLAR2-03 | The resume extraction context includes a code-owned "questions we asked" anchor, and the extraction prompt enforces absent-if-unaddressed; a bare "40" is never blindly attributed. | 260705-02 item 2 | `_combined_context_email` at `orchestrator.py:837-850`; extraction prompt seam in `app/pipeline/extract.py`; Patterns §3 |
| CLAR2-04 | The alias-learning write side is reachable: a client-confirmed suggestion binds `{token: suggested_id}` deterministically; the misname guard's never-learn-from-inference intent survives; a full-loop test proves the system stops asking. | 260705-01 | Bind chain traced at `orchestrator.py:667-734` + `1181-1260`; `suggest_employees` shape gotcha in Pitfalls #5 |
| CLAR2-05 | Multi-round context loss is closed: the combined context accumulates ORIGINAL + ALL consumed replies in round order; the known-edge fixture flips its assertion (Round-1 "30, not 40" pays 30, not 40). | CX-01 (09-REVIEWS.md:138-142), T-09-21 | Fixture flip instructions verified (`tests/test_multiround_context_edge.py:14-46, 303-308`); reply-row accumulation via D-11-13 |
| CLAR2-06 | A redelivered, still-unconsumed reply re-schedules the resume (no permanently-dropped replies); a consumed reply's redelivery stays a no-op. A stranded unconsumed reply is auto-re-scheduled from the runs-list load. | WR-04 (09-REVIEW.md:62-66) | Duplicate path traced at `main.py:385-465`; consumed-marker design; Pitfalls #11 |
| CLAR2-07 | Retrigger clears ALL reply context (`clarified_fields`, `pre_clarify_extracted`, round counter, suggestion state) so provenance badges cannot outlive the data that produced them. | WR-06 (09-REVIEW.md:77-81) | Retrigger seam traced at `main.py:701-800`; clear-after-claim ordering in Pitfalls #8 |
</phase_requirements>

## Summary

This phase is a pure internal redesign: no new libraries, no new services, no new external APIs. Everything needed already exists in the repo — the work is re-keying an idempotency guard, adding two columns and one status value, rewriting one context-assembly function, replacing one bind condition, and adding one dashboard form. The research risk is therefore not "what stack to use" but "which existing seams to land each change in without breaking the dense web of prior invariants (D-9-01/02, D-12, D-13c, CLAR-04, the 7.5 four-outcome state machine)." All code touch points listed in CONTEXT.md were re-verified against live source this session; line numbers below are current.

The highest-leverage findings for the planner: (1) widening `uq_email_run_purpose` to include a round column **breaks `insert_email_message`'s `ON CONFLICT (run_id, purpose)` upsert** unless the arbiter clause is updated in the same change — and the new round column must be `NOT NULL DEFAULT 0` on outbound rows or Postgres NULL-distinctness silently disables confirmation dedup; (2) the round-increment has a **crash-idempotency subtlety** across `_clarify`'s three finalize paths (early-return, record_only, live gateway) — deriving the next round from the found sent row rather than blind `+1` makes all paths idempotent; (3) `suggest_employees` returns `{submitted_name: suggested_full_name}` (a NAME, not an employee id) — D-11-14's persisted suggestion needs a deterministic name→id roster lookup at persist time; (4) adding a status value touches **seven pinned places** (enum, two spots in schema.sql, drift-guard test, badge maps, IN_FLIGHT set, scope-pin tests, conftest fake) — miss one and CI fails or the dashboard renders a raw string.

Live-data migration matters: production has runs with `alias_candidates` in the old flat `{token: null|id}` shape and `awaiting_reply` runs with no round counter. The plan must include a backfill/read-compat story (initialize `clarification_round` from the count of sent clarification-purpose rows; read-compat or one-shot migrate for the alias shape) applied at the same blocking human checkpoint as the DDL.

**Primary recommendation:** Structure plans around the three independent sub-machines — (A) round counter + send guard + cap/escape (schema first), (B) accumulation + question anchor + no-guess prompt, (C) suggestion persistence + bind-on-confirmation + operator form — with the schema migration checkpoint as Wave 0/1 and the D-11-17 full-loop test as the phase gate. A and B meet only at `resume_pipeline`; C consumes both.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Round counter + (purpose, round) send guard | DB schema + `app/db/repo.py` | `orchestrator._clarify` | The counter and uniqueness are durable facts; the guard is code over those facts (project rule: deterministic decisions live in code over persisted state) |
| Round cap + escalation to `needs_operator` | `orchestrator._clarify` (check) + DB status enum | Dashboard (badge) | Cap check must sit where the would-be send happens; status is the orchestration engine (established pattern) |
| Consumed-reply marker | `app/db/repo.py` + `resume_pipeline` claim seam | Webhook duplicate path (`main.py`) | Set only when the CAS claim succeeds (D-11-02); read by WR-04 redelivery logic and D-11-05 sweep |
| Redelivered-reply re-schedule (WR-04) | Webhook `inbound()` duplicate branch (`main.py`) | — | The duplicate outcome is shaped post-commit in the route; the CAS claim downstream makes double-scheduling safe |
| Stranded-unconsumed-reply auto-resume (D-11-05) | Runs-list route (`main.py:1062-1076`) + new repo query | — | Same trigger point as the D-9-11 sweep, by design |
| Accumulated combined context + asked-summary anchor | `orchestrator._combined_context_email` + `resume_pipeline` | `app/db/repo.py` (consumed-rows query) | Code-owned, string-testable; email table is the single source of truth (D-11-13) |
| No-guess extraction policy | `app/pipeline/extract.py` prompt + `app/llm` seam | — | Prompt instruction only; enforcement stays deterministic downstream (`decide` gate re-asks) |
| Suggestion persistence + bind-on-confirmation | `orchestrator._clarify` (persist) + `resume_pipeline` STEP C/D rewrite | `repo.set_alias_candidates` | LLM proposes (advisory), human confirms (reply), code verifies (reconciliation facts) |
| Operator resolve form + resume | Dashboard routes + `run_detail.html` (Jinja2) | Orchestrator re-entry point | No-SPA idiom; POST form like approve/reject; deterministic mapping applied before reconcile |
| Alias write at approval gate | `_write_aliases_if_safe` (`orchestrator.py:1181+`) | — | Unchanged seam; only the value shape and skip condition update |

## Standard Stack

### Core (unchanged — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psycopg[binary,pool] | 3.3.4 (pinned in uv.lock) | New columns, DO-block migrations, consumed-row queries, CAS claims | Already the sole DB layer; `claim_status`/`set_status` are the two sanctioned status writers [VERIFIED: codebase `app/db/repo.py:405-458`] |
| FastAPI + Jinja2 | 0.138.0 / 3.1.6 | `needs_operator` badge, resolve form, resume/reject routes | Existing dashboard idiom — approve/reject are plain HTML form POSTs [VERIFIED: codebase `app/main.py:642-698`, `app/templates/run_detail.html`] |
| Pydantic v2 | 2.13.4 | No new schemas expected; `Extracted`/`Decision`/`NameMatchResult` unchanged | Existing contracts [VERIFIED: codebase `app/models/`] |
| pytest | dev group | New hermetic modules + the D-11-17 full-loop test | 568 offline tests collect today with `-m "not integration and not live_llm"` [VERIFIED: ran collection this session] |

**Installation:** none. `uv sync` as-is. **This phase adds zero packages** — do not add any; the project CLAUDE.md locks the stack and the phase is internal logic.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Round column + widened unique constraint (D-11-01, locked) | Asked-fields hash on the outbound row (WR-05 fix option a) | Locked out by D-11-01 — hash compares question content but loses the explicit round history rows the cap and audit need |
| Accumulate reply bodies (D-11-12, locked) | Diff vs last-persisted extraction (fix b) | Explicitly rejected in CONTEXT.md — no second diff state machine |
| New `needs_operator` status (D-11-06, locked) | ERROR + sentinel flag | Locked out — ERROR's only exit (retrigger) discards exactly the reply context the operator needs |

## Package Legitimacy Audit

**No external packages are installed by this phase.** All work is internal to the existing repo using already-locked dependencies (`uv.lock` committed, unchanged). slopcheck run not applicable — nothing to verify. **Packages removed due to slopcheck [SLOP] verdict:** none. **Packages flagged as suspicious [SUS]:** none.

## Architecture Patterns

### System Architecture Diagram

```
                         ┌─────────────────────────────────────────────────────┐
 client reply email      │  POST /webhook/inbound  (app/main.py:~340-500)       │
 ───────────────────────▶│  ingest txn: dedupe → classify → link_email_to_run   │
                         │  ├─ inserted + header match → reply_candidate         │
                         │  │    └─▶ _finish_reply_resume → bg _resume_pipeline  │
                         │  └─ NOT inserted (duplicate) ──────────────┐          │
                         └────────────────────────────────────────────┼──────────┘
                                                                      │ WR-04 (NEW):
                                                                      │ reply headers +
                                                                      │ consumed_round IS NULL +
                                                                      │ run awaiting_reply?
                                                                      ▼
                         ┌──────────────────────────────────────────────────────┐
                         │  resume_pipeline (orchestrator.py:227+)               │
                         │  1. CAS claim AWAITING_REPLY→EXTRACTING (existing)    │
                         │  2. NEW: mark reply consumed_round = current round    │
                         │  3. NEW: load ALL consumed replies (email_messages,   │
                         │     ordered by round) + original body                 │
                         │  4. NEW: _combined_context_email = ORIGINAL           │
                         │     + QUESTIONS-WE-ASKED anchor (code-owned)          │
                         │     + replies round-1..N (delimited, numbered)        │
                         │  5. classify-first / _run_stages (7.5 machine,        │
                         │     UNCHANGED semantics)                              │
                         │  6. NEW bind check: suggested_id newly resolved AND   │
                         │     token gone from unresolved → bind {token:sugg_id} │
                         └───────────────┬──────────────────────────────────────┘
                                         │ decision = request_clarification
                                         ▼
                         ┌──────────────────────────────────────────────────────┐
                         │  _clarify (orchestrator.py:986+)                      │
                         │  0. NEW cap check: clarification_round >= 3 →         │
                         │     escalate needs_operator (status-advance-last),    │
                         │     NO send, return                                   │
                         │  1. guard: sent row exists for (purpose, CURRENT      │
                         │     round)? → true duplicate → finalize + return      │
                         │  2. alias capture (existing gates, unchanged)         │
                         │  3. suggest_employees → NEW: persist suggestion       │
                         │     {token: {suggested: id, bound: null}}             │
                         │  4. compose + send (round stamped on outbound row)    │
                         │  5. finalize txn: snapshot + round increment +        │
                         │     set_status(AWAITING_REPLY)  ← D-9-02 order        │
                         └───────────────┬──────────────────────────────────────┘
                                         │ round >= cap
                                         ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  needs_operator (NEW status)                                      │
   │  dashboard run-detail: resolve form (dropdown per unresolved      │
   │  name, suggestion pre-selected, "remember alias" checkbox) →      │
   │  POST resolve+resume: apply mapping deterministically, CAS        │
   │  claim needs_operator→EXTRACTING, re-run from accumulated         │
   │  context   |   or existing Reject                                 │
   └──────────────────────────────────────────────────────────────────┘

 operator approves at the existing single human gate → _deliver →
 _write_aliases_if_safe reads {token:{suggested,bound}} → known_aliases write
```

### Recommended Project Structure (unchanged — files touched)

```
app/
├── db/
│   ├── schema.sql          # +clarification_round, +email_messages.round, +consumed_round,
│   │                       #  +needs_operator in status CHECK (BOTH places), widened uq constraint
│   └── repo.py             # round-aware guard lookup, consumed-marker fns, consumed-replies query,
│                           #  clear-context fn, unconsumed-stranded query, insert_email_message round param
├── models/status.py        # RunStatus.NEEDS_OPERATOR
├── pipeline/
│   ├── orchestrator.py     # _clarify (guard/cap/persist-suggestion/finalize), resume_pipeline
│   │                       #  (consume marker, accumulation, bind rewrite), _combined_context_email
│   ├── extract.py          # absent-if-unaddressed prompt instruction (resume context only)
│   └── suggest.py          # unchanged (output mapped name→id at persist site)
├── main.py                 # WR-04 duplicate re-schedule, D-11-05 runs-list hook, retrigger clear,
│                           #  needs_operator badge maps + resolve/resume routes
└── templates/run_detail.html  # needs_operator banner + resolve form
tests/
├── test_multiround_context_edge.py  # assertion flips per its own instructions
├── test_alias_write.py              # update to new candidate shape
├── conftest.py                      # InMemoryRepo mirrors every new repo fn
└── (new unguarded modules)          # round machine, cap/escape, WR-04, full-loop D-11-17
```

### Pattern 1: Round-aware idempotency guard (the WR-05 fix core)

**What:** Guard keys on (purpose, round); the outbound row records the round it was sent for.
**When to use:** `_clarify` entry, replacing the purpose-only `get_outbound_message_id` check at `orchestrator.py:1022`.

```python
# Current (round-blind, WR-05): orchestrator.py:1022
existing_clari = repo.get_outbound_message_id(run_id, purpose=purpose)

# New shape: the guard asks "was THIS round's question already sent?"
current_round = repo.get_clarification_round(run_id)          # payroll_runs.clarification_round
existing = repo.get_outbound_for_round(run_id, purpose=purpose, round=current_round)
# existing is not None  → true duplicate (re-trigger of the same round): suppress send,
#                         finalize (snapshot + ensure round advanced past the sent row + status)
# existing is None      → genuinely new question: proceed to capture/suggest/send
```

Semantics that make this correct: the counter increments only in the post-send finalize transaction (D-11-02). Arriving from EXTRACTING with a fresh decision, `current_round` is already past every sent row → guard finds nothing → sends (CLAR2-01). A crash-retrigger that re-enters before the finalize ran finds the sent row at the still-current round → suppresses (CLAR-04 preserved). See Pitfall #3 for the increment-idempotency requirement on the early-return path.

### Pattern 2: Escalation write sequence (D-9-02 compliant)

**What:** The cap check runs at the top of `_clarify` BEFORE any LLM/provider call; escalation is a pure DB write.

```python
# Top of _clarify, before the guard/draft/send (no LLM call has happened yet — D-9-01 trivially safe)
if repo.get_clarification_round(run_id) >= MAX_CLARIFICATION_ROUNDS:   # module constant = 3, documented derivation
    with repo.get_connection() as conn:
        with conn.transaction():
            # any bookkeeping writes first ...
            repo.set_status(run_id, RunStatus.NEEDS_OPERATOR, conn=conn)  # status-advance-LAST (D-9-02)
    logger.info("run %s escalated to needs_operator after %d rounds (D-11-07)", run_id, MAX_CLARIFICATION_ROUNDS)
    return
```

Placing it inside `_clarify` covers both call sites (`_run_stages` direct call at `orchestrator.py:980` and `_defer_field_regression_clarification` step 5 at `orchestrator.py:826`) with one check — D-11-07's "counts ALL sends regardless of purpose" falls out for free because the counter is per-run, not per-purpose.

### Pattern 3: Code-owned asked-summary anchor + accumulated context

**What:** `_combined_context_email` becomes a pure function over (original body, asked-facts, ordered consumed replies). String-for-string testable with zero LLM involvement.

```python
# Sketch — exact delimiters/wording are Claude's discretion (CONTEXT.md)
def _combined_context_email(reply, original_body, *, asked_summary_lines, prior_replies):
    parts = ["ORIGINAL PAYROLL EMAIL:\n" + original_body]
    if asked_summary_lines:                       # rendered from decision facts, NOT the LLM draft (D-11-10)
        parts.append("QUESTIONS WE ASKED:\n" + "\n".join(asked_summary_lines))
    for i, body in enumerate(prior_replies, start=1):   # consumed rows, round order (D-11-12/13)
        parts.append(f"CLARIFICATION REPLY {i} FROM CLIENT:\n{body}")
    parts.append(f"CLARIFICATION REPLY {len(prior_replies)+1} FROM CLIENT (CURRENT):\n{reply.body_text}")
    return reply.model_copy(update={"body_text": "\n\n".join(parts)})
```

The asked-summary source of truth is the same decision facts the round machine tracks: `decision.unresolved_names` + the `clarified_fields` entries currently `"asked"` (per employee). Both are persisted (`payroll_runs.decision`, `clarified_fields`) — loadable at resume with no new state.

### Pattern 4: Bind-on-confirmation (replaces the circular STEP C/D diff)

**What:** The existing pre-vs-post diff at `orchestrator.py:667-734` is replaced by a check against the persisted suggestion.

```python
# After _run_stages, on the resume path (replaces the NEW-2 pre/post diff):
cand = (run_data.get("alias_candidates") or {}).get(token)   # {"suggested": id|None, "bound": None}
suggested_id = cand and cand.get("suggested")
post = load post-resume reconciliation (as today, orchestrator.py:674-680)
token_gone   = token not in {m["submitted_name"] for m in post if not m["resolved"]}  # (b)
sugg_resolved = suggested_id in post_resolved_ids and suggested_id not in pre_resolved_ids  # (a) newly
if suggested_id and sugg_resolved and token_gone:
    bind {token: {"suggested": suggested_id, "bound": suggested_id}}
# "no, I meant James": James resolves (non-suggested id) → sugg_resolved False → no bind.  Misname class stays dead.
```

`_write_aliases_if_safe` (`orchestrator.py:1181-1260`) keeps its structure; the skip condition changes from `employee_id_str is None` to `cand.get("bound") is None`, and the D-01b collision re-check + batch-roster-refresh stay verbatim.

### Anti-Patterns to Avoid

- **LLM-drafted text as the attribution anchor:** D-11-10 explicitly requires the anchor be rendered from decision facts. The LLM-drafted outbound body is neither stable nor testable and can itself hallucinate a question.
- **A second diff state machine for cross-round value changes:** rejected fix (b). Accumulation is the whole design.
- **Reply-confirmation detection via an LLM "did they say yes?" call:** D-11-15 locks the bind chain LLM-free — confirmation evidence is the deterministic post-resume resolution of the suggested employee, full stop.
- **Merging scope lists "for consistency":** sweep scope (exactly 3 statuses, D-9-12), retrigger stale scope (4, includes SENT), D-11-05 auto-resume scope, and IN_FLIGHT_STATUSES all deliberately diverge and are each pinned by tests. `needs_operator` joins NONE of them. The retrigger docstring at `main.py:766-776` says "Do NOT 'fix' this into parity" — honor it.
- **Adding hermetic tests to `tests/test_resume_pipeline.py`:** module-level `DATABASE_URL` skip guard silently skips everything added there (09-REVIEWS Codex finding; warning restated at `tests/test_multiround_context_edge.py:3-12`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Double-scheduling safety for resume/redelivery | A locks table or advisory-lock scheme | Existing `repo.claim_status` CAS (`repo.py:422`) | Already the project's fencing primitive; D-11-02/03/05 all lean on it by decision. Phase 10 may add more — compose with, never depend on (CONTEXT.md) |
| Reply-row ↔ run linkage | New join table or JSONB body copies on the run row | `link_email_to_run` (`repo.py:199`, WR-03 fix) + `load_thread_messages` (`repo.py:1257`) as the query template | D-11-13 locks email_messages as the single source of truth |
| Idempotent live DDL | Ad-hoc ALTERs or a migration framework | Phase 8 DO-block patterns already in `schema.sql` (column-anchored CHECK drop at :141-171; named-constraint guard at :267-278) | Both exact patterns needed (status CHECK re-ADD; uq drop/re-add) already exist in-file as copy targets |
| Suggestion computation | A new "confirmation classifier" | `suggest_employees` (`suggest.py:60`) unchanged; persist its output | D-11-14: persist what it already produces |
| Status transitions | Direct SQL UPDATEs | `set_status` / `claim_status` only | D-12: two sanctioned status writers; tests pin this |
| Round bookkeeping in Python memory | Module-level counters/dicts | `payroll_runs.clarification_round` column | Render free tier restarts wipe process state; Postgres IS the state machine (project constraint) |

**Key insight:** every mechanism this phase needs already has a proven in-repo primitive; the failure mode is inventing a parallel one, not missing one.

## Runtime State Inventory

This phase migrates a **live production schema** (Supabase, Render deploy — Phase 6 facts). Grep finds files; these are the runtime items:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | (1) Live `payroll_runs` rows: `awaiting_reply` runs predate `clarification_round` → column default 0 undercounts runs that already sent a clarification. (2) Live `alias_candidates` JSONB in old flat shape `{token: null\|id_str}` predating D-11-14. (3) Existing `email_messages` outbound rows have no round value. | (1) Backfill at migration: `clarification_round = COUNT(sent outbound rows with clarification purposes)` per run — deterministic from existing data. (2) Read-compat in `_write_aliases_if_safe`/bind code OR one-shot UPDATE migrating flat→nested at the checkpoint (recommend the one-shot migrate — simpler code). (3) Backfill `round = 0` (or row-number per (run,purpose)) — with only ≤1 row per (run,purpose) possible under the old constraint, `DEFAULT 0 NOT NULL` is sufficient. |
| Live service config | Render web service runs the OLD code until deploy; Supabase schema changes are applied via `python -m app.db.bootstrap` against the live pooler (Phase 8 pattern: blocking human checkpoint). | Order: additive DDL first (new columns + widened constraint are backward-compatible with old code — old code never writes `round`, default covers it; old ON CONFLICT (run_id,purpose) **breaks** once the uq constraint is widened → see Pitfalls #1: the constraint widening and the code deploy must be sequenced in the same checkpoint window, or keep the old 2-col unique index alive until code deploys). |
| OS-registered state | GitHub Actions keep-alive cron pings the Render URL; eval workflow on push. | None — no workflow references statuses or schema. Verified: workflows only hit HTTP endpoints. |
| Secrets/env vars | None referenced by this phase's changes (no new env vars; model IDs/DB URL unchanged). | None — verified against `app/config.py` usage; no new settings introduced by locked decisions. |
| Build artifacts | None — no package rename, no Docker change. `uv.lock` unchanged (zero new deps). | None. |

## Common Pitfalls

### Pitfall 1: Widening `uq_email_run_purpose` breaks the existing upsert arbiter
**What goes wrong:** `insert_email_message` uses `ON CONFLICT (run_id, purpose) DO UPDATE` (`repo.py:1001`). Postgres requires the ON CONFLICT column list to exactly match a unique index. Drop/replace the constraint with `(run_id, purpose, round)` and every outbound insert raises `InvalidColumnReference: there is no unique or exclusion constraint matching the ON CONFLICT specification`.
**Why it happens:** the arbiter is inferred from the constraint; the code and DDL are coupled invisibly. [VERIFIED: codebase — the coupling is documented at `repo.py:980-987` and `schema.sql:219-221`]
**How to avoid:** change the DDL and the `ON CONFLICT` clause (and `gateway.send_outbound`'s insert path, which routes through `insert_email_message`) in the same plan step; sequence the live migration and deploy in one checkpoint window. The upsert’s purpose (reserved→sent advancement retry, D-13c NEW-1) is per-round now — retry within a round still upserts; a new round is a new row (D-11-01 "no upsert-replace of history").
**Warning signs:** any test writing two outbound rows for one run crashing with InvalidColumnReference.

### Pitfall 2: A nullable round column silently disables confirmation dedup
**What goes wrong:** Postgres treats NULLs as distinct in unique constraints (the codebase relies on this for inbound rows — comment at `schema.sql:219-220`). If `email_messages.round` is nullable and confirmation rows get NULL, `UNIQUE(run_id, purpose, round)` no longer prevents duplicate confirmation rows, and `_deliver`'s already-sent guard degrades.
**How to avoid:** `round INT NOT NULL DEFAULT 0` on email_messages. Inbound rows still never conflict (their `purpose` is NULL, unchanged). Confirmation rows always round 0 → still one per run. Clarification rows carry the real round.
**Warning signs:** `test_delivery.py` / retrigger tests showing two confirmation rows for one run.

### Pitfall 3: Round increment is not crash-idempotent if it's a blind `+1`
**What goes wrong:** `_clarify` has THREE finalize paths (early-return duplicate at :1033-1037, record_only at :1154-1158, live gateway at :1175-1178). D-11-02 puts the increment in the post-send finalize txn. If the process crashes after the provider send but before the finalize txn, retrigger re-enters `_clarify`, the guard finds the sent row for the CURRENT round and takes the early-return path — which must ALSO advance the round (it is finalizing a send that never finalized), or the next genuine question is suppressed forever (WR-05 reborn).
**How to avoid:** in every finalize path, set `clarification_round = (round of the found/just-written sent row) + 1` rather than `clarification_round + 1` — idempotent regardless of which path runs or how many times. The early-return path's repo lookup should therefore return the row's round, not just its message_id.
**Warning signs:** a crash-injection test (Phase 9 style, `tests/test_atomic_persist.py` pattern) where round stays behind the sent-row count.

### Pitfall 4: Adding a status value touches seven pinned places
**What goes wrong:** `needs_operator` added to the enum but CI fails or the dashboard misrenders because one mirror was missed.
**The complete checklist** (all verified in-source this session):
1. `app/models/status.py` — `RunStatus.NEEDS_OPERATOR` (docstring says "Ten-state" — update).
2. `schema.sql` inline CHECK (:68-80) — fresh-bootstrap path.
3. `schema.sql` DO-block re-ADD (:141-171) — live-migration path. Both must list the new value or the drift guard fails on one of them.
4. `tests/test_status_drift.py` — parses schema.sql CHECK vs live enum; will fail until BOTH sql spots and the enum agree (this is the desired forcing function).
5. `app/main.py` `_BADGE_CLASS`/`_BADGE_LABEL` (:185-212) — else the badge renders fallback "neutral"/title-case (label fallback is graceful; class fallback hides the operator-attention color). D-11-06 wants its own badge.
6. `app/main.py` `IN_FLIGHT_STATUSES` (:111-113) — `needs_operator` must NOT be added (it's a settled gate state like awaiting_approval; polling it forever is wrong).
7. Scope pins: `tests/test_stuck_run_recovery.py` (sweep scope exactly `["received","extracting","computed"]`), retrigger `stale_statuses` (`main.py:777-782`), conftest `_STRANDED_SCOPE_STATUSES` (:~250) — `needs_operator` joins none; add explicit exclusion assertions per CONTEXT.md ("must be added to the exclusion tests").

### Pitfall 5: `suggest_employees` returns names, not employee ids
**What goes wrong:** D-11-14 persists `{token: {suggested: id|null, ...}}`, but `suggest_employees` returns `dict[submitted_name → suggested roster full_name]` (`suggest.py:60-72`). Persisting the raw output stores a name where the bind check expects an id.
**How to avoid:** at the persist site in `_clarify`, map full_name → employee id via the already-loaded roster (`full_name` is UNIQUE per business — `schema.sql:52`); a name not found in the roster (the function already filters to valid roster names, but belt-and-braces) → `suggested: null`. Keep `suggest_employees` itself unchanged (compose still needs names for the email copy).
**Warning signs:** bind check comparing a UUID string against "Robert Nguyen".

### Pitfall 6: Old alias_candidates shape in live rows
**What goes wrong:** live runs carry `{token: null}` or `{token: "uuid-str"}`. New code doing `cand.get("suggested")` on a `None`/`str` value raises AttributeError inside `_write_aliases_if_safe` — which swallows exceptions by design (D-13b), so the alias write silently dies instead of crashing loudly.
**How to avoid:** one-shot migration UPDATE at the checkpoint (flat→nested: `null` → `{"suggested": null, "bound": null}`, `"id"` → `{"suggested": null, "bound": "id"}`), OR a small normalize-on-read helper used by both the bind check and `_write_aliases_if_safe`. Pick one; test both shapes.

### Pitfall 7: The fake repo must mirror every new repo function
**What goes wrong:** `tests/conftest.py`'s `InMemoryRepo` (:236+) monkeypatches the full repo surface the orchestrator/webhook touch. Every new function (`get_clarification_round`, `get_outbound_for_round`, `mark_reply_consumed`, `load_consumed_replies`, `clear_reply_context`, `find_stranded_unconsumed_replies`, round param on `insert_email_message`) needs a faithful in-memory mirror or hermetic tests crash on AttributeError — or worse, silently exercise stale semantics.
**How to avoid:** treat the InMemoryRepo update as a first-class task in the same plan as the repo change, mirroring real semantics (the file's own convention). Note the fake deliberately duplicates scope constants rather than importing them — follow that pattern for the new cap constant only if the fake needs it.

### Pitfall 8: Clear-at-retrigger before the claim, or on a losing claim
**What goes wrong:** D-11-04's clear (clarified_fields + snapshot + round + suggestion state) executed before `claim_status` succeeds — a losing concurrent retrigger wipes the context of a live, healthily-processing run.
**How to avoid:** clear strictly AFTER a successful claim, inside the retrigger route (`main.py:701-800`), in a transaction that commits before `_run_pipeline` is scheduled. Both retrigger branches (ERROR/APPROVED CAS and the stale in-flight CAS) need it — both dispatch `_run_pipeline` and lose reply context.
**Warning signs:** a concurrency test where retrigger-lost clears state; WR-06's stale-badge scenario still reproducible after the "fix."

### Pitfall 9: The no-guess prompt is policy, not enforcement — don't test it like code
**What goes wrong:** D-11-11 is an extraction-prompt instruction; an LLM can still mis-attribute. Tests that mock the LLM prove nothing about the prompt (Phase 7.5 lesson: green hermetic tests that mock the LLM can't prove money-safety).
**How to avoid:** the deterministic backstop is the design itself — an unattributed field stays absent → `decide` gates → a NEW narrower question now actually sends (D-11-01). Test the backstop deterministically (absent field → clarification round 2 sends) and the anchor string exactly (code-owned). Optionally add an eval fixture for the attribution behavior; do not gate the phase on LLM behavior.

### Pitfall 10: Fixture flip is a rename-and-rewrite, not a `not`
**What goes wrong:** `test_multi_round_context_loss_known_edge` asserts CURRENT behavior with extensive "this documents a real deferred gap" prose (:14-46, :303-308). Just negating the assertion leaves misleading documentation and a test name that says "known edge."
**How to avoid:** per its own flip-on-fix instructions, rewrite the test to assert DESIRED behavior (final_regular == 30) and update the module docstring; keep the scenario identical so the regression target is preserved. Its sibling CX-03 test (asserting desired behavior, paid VALUES) is the style model.

### Pitfall 11: WR-04 duplicate re-schedule needs the PERSISTED reply, and must stay out of the ingest transaction
**What goes wrong:** two traps. (a) Building the resume `InboundEmail` from the redelivered request body re-cleans/re-parses; the persisted row (cleaned at first ingest) is authoritative — load it by message_id (it has run_id via WR-03 linking, body_text, headers, and the new consumed_round). (b) Scheduling `_resume_pipeline` inside the ingest transaction violates the established post-commit-scheduling seam (`main.py:453-454` comment: everything below is post-commit).
**How to avoid:** in the `duplicate` outcome branch (post-commit, `main.py:456-465`), when the parsed email carries reply headers: load the persisted row; if `consumed_round IS NULL` AND its linked run is `awaiting_reply` → `background_tasks.add_task(_resume_pipeline, run_id, persisted_as_inbound)`. The CAS claim absorbs any double-schedule. Consumed → keep today's no-op duplicate response.

### Pitfall 12: Don't conflate `clarification_round` with `is_round_2`
**What goes wrong:** `is_round_2 = bool(clarified)` (`orchestrator.py:346`) drives the 7.5 classify-first machine — it means "there are clarified_fields entries," NOT "round counter > 0." A plain-name clarification round (no field regression) has `clarified == {}` and must keep taking the Round-1 branch. Replacing `is_round_2` with a counter check breaks the 7.5 four-outcome machine (a prior-phase contract this phase must not break).
**How to avoid:** leave `is_round_2` exactly as is. The round counter is send-guard/cap state; `clarified_fields` is classify state. D-11-04 resets both at retrigger, which is the only place they must agree.

## Code Examples

Verified patterns from the codebase (the authoritative "docs" for this phase):

### Idempotent named-constraint replacement (for widening `uq_email_run_purpose`)
```sql
-- Source: app/db/schema.sql:263-278 (existing add-if-absent) + :141-171 (drop/re-add pattern)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint
               WHERE conname = 'uq_email_run_purpose'
                 AND conrelid = 'email_messages'::regclass) THEN
        ALTER TABLE email_messages DROP CONSTRAINT uq_email_run_purpose;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'uq_email_run_purpose_round'
                     AND conrelid = 'email_messages'::regclass) THEN
        ALTER TABLE email_messages
            ADD CONSTRAINT uq_email_run_purpose_round UNIQUE (run_id, purpose, round);
    END IF;
END;
$$;
-- Prereq in the same file, before this block:
-- ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS round INT NOT NULL DEFAULT 0;
-- ALTER TABLE payroll_runs  ADD COLUMN IF NOT EXISTS clarification_round INT NOT NULL DEFAULT 0;
-- ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS consumed_round INT;   -- nullable: NULL = unconsumed
```
(Use one atomic DO-block for the drop+re-add per the D-7.5-03a comment at `schema.sql:126-129` — a failed ADD rolls back the DROP.)

### CAS claim (the double-scheduling fence every new trigger reuses)
```python
# Source: app/pipeline/orchestrator.py:263-269 (live usage)
claimed = repo.claim_status(run_id, RunStatus.AWAITING_REPLY, RunStatus.EXTRACTING)
if not claimed:
    return  # late/duplicate — drops cleanly, no error
# NEW, immediately after a successful claim (D-11-02):
repo.mark_reply_consumed(inbound.message_id, round=repo.get_clarification_round(run_id))
```

### Finalize transaction shape (all `_clarify` exit paths)
```python
# Source: app/pipeline/orchestrator.py:1175-1178 (live-gateway finalize), extended per D-11-02
with repo.get_connection() as conn:
    with conn.transaction():
        repo.set_pre_clarify_extracted(run_id, extracted, conn=conn)   # IS NULL write-once guard, unchanged
        repo.set_clarification_round(run_id, sent_row_round + 1, conn=conn)  # idempotent (Pitfall #3)
        repo.set_status(run_id, RunStatus.AWAITING_REPLY, conn=conn)   # status-advance-LAST (D-9-02)
```

### Runs-list hook for D-11-05 (existing seam)
```python
# Source: app/main.py:1062-1076 — the sweep already hooks here; add beside it
try:
    repo.sweep_stranded_runs(STALE_THRESHOLD_SECONDS)                       # existing (D-9-11)
    for run_id, reply_row in repo.find_stranded_unconsumed_replies(STALE_THRESHOLD_SECONDS):
        background_tasks.add_task(_resume_pipeline, run_id, _row_to_inbound(reply_row))  # CAS-gated downstream
except Exception:
    logger.debug("recovery sweep unavailable — skipping this page load")
```

### Operator resolve-form route shape (mirror of approve/reject)
```python
# Source pattern: app/main.py:642-698 (approve — CAS claim + guarded work + 303 redirect)
@app.post("/runs/{run_id}/resolve")
def resolve(run_id: uuid.UUID, background_tasks: BackgroundTasks, ...form fields...):
    # Validate: run is needs_operator; every posted employee_id ∈ the RUN'S BUSINESS roster (security §);
    # apply mapping deterministically (write bound candidates / per-run resolution) BEFORE the claim's
    # dispatched work reads it; then:
    claimed = repo.claim_status(run_id, RunStatus.NEEDS_OPERATOR, RunStatus.EXTRACTING)
    if claimed:
        background_tasks.add_task(_operator_resume, run_id)   # re-enters from accumulated context (D-11-13)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
```
Needs `python-multipart` for form POSTs — already a runtime dependency (project CLAUDE.md stack table).

## State of the Art

| Old Approach (current code) | Current Approach (this phase) | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Purpose-only send guard (`get_outbound_message_id(run_id, purpose)`) | (purpose, round) guard over an explicit counter | D-11-01 | Round 2+ questions actually send; true duplicates still suppressed |
| One outbound row per (run, purpose), upsert-replaced | One row per (run, purpose, round), preserved history | D-11-01 | Full audit trail of every question asked |
| Combined context = ORIGINAL + latest reply | ORIGINAL + asked-anchor + ALL consumed replies, round-ordered | D-11-10/12/13 | CX-01 closed; bare replies attributable |
| Alias bind = circular re-extraction diff (unreachable) | Bind on deterministically-verified confirmation of the persisted suggestion | D-11-14/15 | The learning loop actually learns; misname guard intent preserved |
| Stranded `awaiting_reply` = permanent (no recovery route) | Cap→`needs_operator` escape + WR-04 redelivery re-schedule + D-11-05 sweep | D-11-03/05/06/07 | "Nothing silently hangs" invariant restored for the reply path |
| Retrigger leaves stale provenance labels | Clear-all-reply-context at retrigger | D-11-04 | Approval-gate badges never lie |

**Deprecated/outdated by this phase:** the NEW-2 pre-vs-post diff bind logic (`orchestrator.py:682-734`) — replaced wholesale; its tests (`tests/test_alias_write.py:720-1100`) update to the new evidence model per D-11-17.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Live production rows exist in the old `alias_candidates` flat shape and at `awaiting_reply` with prior clarification sends (inferred from deployment history — Phase 6 shipped live, phases 7-9 ran against it; not queried this session) | Runtime State Inventory | If no such rows exist, backfill steps are no-ops (harmless); if they exist and are skipped, Pitfall #6/undercounted rounds |
| A2 | `git log`/deploy cadence means the schema checkpoint and Render deploy can be sequenced in one operator session (the Phase 8 checkpoint pattern assumed the same) | Runtime State Inventory | If deploy lags migration, old code's `ON CONFLICT (run_id, purpose)` errors on new-constraint DB (Pitfall #1) — mitigate by keeping a temporary 2-col unique index until deploy completes, or doing DDL+deploy in one window |

All other claims verified against live source this session (file:line cited inline).

## Open Questions

1. **Operator-resume entry point (Claude's discretion, needs a plan-time decision)**
   - What we know: retrigger's `_run_pipeline` is explicitly wrong (discards reply context — the very reason D-11-06 rejected ERROR-with-sentinel). `resume_pipeline` expects a new `inbound` reply and claims from AWAITING_REPLY.
   - What's unclear: whether to (i) generalize `resume_pipeline` to accept `from_status=NEEDS_OPERATOR` and a synthetic/absent reply, rebuilding context purely from consumed rows (D-11-13 makes this possible), or (ii) add a thin `_operator_resume` that assembles the accumulated context and calls `_run_stages` directly.
   - Recommendation: (i) — one resume path, one context-assembly function, no drift; the "current reply" section is simply absent for operator resumes.
2. **How the operator mapping is "applied deterministically before reconcile"**
   - What we know: `reconcile_names` resolves exact/stored-alias only; the form's mapping must make the token resolve without guessing.
   - Options: (a) write the mapping as bound alias_candidates and, when the remember-checkbox is ON, let the normal approval-gate write persist it — but reconcile at resume still wouldn't resolve the token unless the mapping is also injected into the resolution step; (b) pass a per-run override map into `reconcile_names` (new optional param: overrides win before exact/alias, tagged `source: "operator"`); (c) write `known_aliases` immediately on resolve (violates the one-human-gate write timing D-11-16 implies for the checkbox-OFF case).
   - Recommendation: (b) + (a): per-run override drives resolution; checkbox ON additionally sets `bound` so the existing approval-gate write path persists it. Checkbox OFF = override only, nothing learned.
3. **Backfill formula for `clarification_round` on live runs**
   - What we know: sent clarification-purpose outbound rows per run are countable; under the old constraint there is ≤1 per purpose, so the max historical count is 2 (clarification + field_regression).
   - Recommendation: `clarification_round = (SELECT count(*) FROM email_messages WHERE run_id=... AND direction='outbound' AND purpose IN ('clarification','clarification_field_regression') AND send_state='sent')` in the migration DO-block; document it as one-shot.
4. **Round-3 boundary semantics** — "Cap = 3 total rounds... when `clarification_round >= 3` at the next would-be send" (D-11-07): with increment-at-send, rounds 0→1→2→3 mean three sends have happened when the counter reads 3; the 4th would-be send escalates. Confirm at plan time that "3 total rounds" = 3 sends allowed (the reading above) — off-by-one here changes when a client gets cut off. The single constant + a boundary test pins it either way.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv + Python 3.12 venv | all dev work | ✓ | per `.python-version` / uv.lock | — |
| pytest (offline suite) | hermetic tests | ✓ | 568 tests collect with `-m "not integration and not live_llm"` (verified this session) | — |
| Live Supabase (pooler 6543) + `DATABASE_URL` | schema migration checkpoint, integration tests | ✓ (per phase-6 deploy facts; not probed this session — keys live in operator shell, not repo) | — | Hermetic tests cover everything except the live DDL apply; the migration is a blocking human checkpoint by design |
| Render deploy | shipping the code that pairs with the migration | ✓ (live service, phase 6) | — | Sequenced with the migration checkpoint (Pitfall #1 / A2) |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** live DB access at plan-execution time is operator-provided at the checkpoint (established Phase 8 flow).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (dev group in pyproject.toml; markers `integration`, `live_llm` registered) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest -q -m "not integration and not live_llm"` (568 tests, fully offline) |
| Full suite command | `uv run pytest -q` (requires `DATABASE_URL` + `ALLOW_DB_RESET=1` in shell env for integration; live keys for live_llm) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CLAR2-01 | Round-2 new question sends; same-round re-trigger suppressed; no silent park | unit/hermetic (fake_repo + mock_llm) | `uv run pytest -q tests/test_clarify_rounds.py` (new) | ❌ Wave 0 |
| CLAR2-02 | 4th would-be send escalates to needs_operator; excluded from sweep/retrigger/auto-resume scopes; operator resolve+resume works | hermetic + scope-pin updates | `uv run pytest -q tests/test_needs_operator.py tests/test_stuck_run_recovery.py tests/test_status_drift.py` | ❌ Wave 0 (new module) + ✅ (pins to update) |
| CLAR2-03 | Asked-summary anchor rendered string-for-string from decision facts; absent-if-unaddressed backstop re-asks (round-2 sends) | unit (pure function) + hermetic | `uv run pytest -q tests/test_combined_context.py` (new) | ❌ Wave 0 |
| CLAR2-04 | Full loop: capture → suggest persist → confirm → bind → approve → known_aliases → second submission resolves with NO clarification | hermetic full-loop (D-11-17) + updated `test_alias_write.py` | `uv run pytest -q tests/test_alias_full_loop.py tests/test_alias_write.py` | ❌ Wave 0 (full-loop) + ✅ (rewrite) |
| CLAR2-05 | Round-1 "30, not 40" pays 30 in Round-2 (paystub VALUE, not label) | hermetic — the flipped known-edge fixture | `uv run pytest -q tests/test_multiround_context_edge.py` | ✅ (assertion flips + docstring rewrite) |
| CLAR2-06 | Unconsumed redelivery re-schedules resume; consumed redelivery no-ops; runs-list sweep re-schedules stale unconsumed | hermetic (TestClient + fake_repo) | `uv run pytest -q tests/test_reply_redelivery.py` (new) + `tests/test_ingest.py` (extend) | ❌ Wave 0 / ✅ |
| CLAR2-07 | Retrigger clears clarified_fields + snapshot + round + suggestion state, only after winning the claim | hermetic | `uv run pytest -q tests/test_cr_regressions.py` (extend) or new module | ✅ (extend) |
| — (drift) | needs_operator in CHECK == enum; badge/scope maps updated | static | `uv run pytest -q tests/test_status_drift.py tests/test_dashboard.py` | ✅ (auto-forces) |

Per Phase 7.5 lesson (memory + CONTEXT.md): money assertions target **persisted paystub line-item values** (`load_line_items(...).hours_regular == Decimal("30")`), never classification labels.

### Sampling Rate
- **Per task commit:** `uv run pytest -q -m "not integration and not live_llm"` (~fast, fully offline)
- **Per wave merge:** same command + the specific new modules verbosely
- **Phase gate:** full offline suite green; integration suite green in an env with DATABASE_URL (operator checkpoint); D-11-17 full-loop test passing with REAL resolution (no faked reconciliation state)

### Wave 0 Gaps
- [ ] `tests/test_clarify_rounds.py` — CLAR2-01 round guard + increment idempotency (crash-injection style per `tests/test_atomic_persist.py`)
- [ ] `tests/test_needs_operator.py` — CLAR2-02 cap boundary, escalation write order (AST/source-order guard pattern exists in `test_atomic_persist.py`), resolve form, scope exclusions
- [ ] `tests/test_combined_context.py` — CLAR2-03 anchor string + accumulation ordering
- [ ] `tests/test_alias_full_loop.py` — CLAR2-04 stops-asking loop (hermetic; real `reconcile_names`, real `_write_aliases_if_safe`, mock LLM only for extraction/suggestion text)
- [ ] `tests/test_reply_redelivery.py` — CLAR2-06 duplicate/consumed matrix
- [ ] `tests/conftest.py` InMemoryRepo extensions (Pitfall #7) — prerequisite for every module above
- All new modules MUST be unguarded (no module-level DATABASE_URL skip) — established pattern.

## Security Domain

`security_enforcement: true`, ASVS level 1. The new attack surface is the operator resolve form and the redelivery re-schedule path.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (accepted posture: no-auth demo dashboard, documented project constraint — unchanged by this phase) | — |
| V3 Session Management | no | — |
| V4 Access Control | **yes** | Resolve-form POST must validate every submitted `employee_id` belongs to the RUN'S business roster (server-side, from `load_roster_for_business(run.business_id)`) — never trust the dropdown. Mirrors the existing `_DEMO_FIXTURES` allowlist philosophy (`main.py:115-120`) |
| V5 Input Validation | yes | FastAPI path/typed params (uuid.UUID coercion already 422s bad ids); form fields validated against roster; checkbox coerced to bool; unknown/extra tokens in the posted mapping rejected |
| V6 Cryptography | no new use | Existing webhook signature verification unchanged |

### Known Threat Patterns for this phase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Parameter tampering on resolve form: post an employee_id from ANOTHER business (or arbitrary UUID) → alias learned/paystub routed to wrong person — a MONEY-class misroute | Tampering / Elevation | Server-side roster-membership check per posted id; reject the whole POST on any invalid id (no partial apply). Test: cross-business id → 4xx/no-op, no state change |
| Forged/replayed "duplicate" webhook triggering resume storms | DoS / Spoofing | Existing signature verification gates the route; CAS claim makes N re-schedules collapse to one; consumed marker makes post-consumption redeliveries no-ops. No new mitigation needed — assert in tests |
| Alias poisoning via crafted reply ("confirming" a suggestion for a colliding token) | Tampering | Preserved write-time collision re-check in `_write_aliases_if_safe` (D-01b) + capture-time collision exclusion (unchanged) + bind requires the SUGGESTED id specifically (D-11-15) — an attacker cannot choose the target; the suggestion was computed server-side |
| Prompt injection via accumulated reply bodies (a reply containing "QUESTIONS WE ASKED:" spoofing the anchor) | Tampering | Anchor is code-owned and positioned by code; extraction output is still schema-validated and every money decision remains deterministic downstream (`decide` gate + human approval). Note as residual/accepted: same class as existing reply-body injection surface, unchanged posture. Optional hardening: distinctive delimiters the cleaner strips from client text |
| PII in logs from new paths (tokens, names in escalation/bind logging) | Information Disclosure | Follow the established type-only/no-name logging discipline (`orchestrator.py:735-743`, `suggest.py:82-85`); new log lines log run_id + counts, never tokens with roster names alongside |

## Sources

### Primary (HIGH confidence — live source, verified 2026-07-05)
- `app/pipeline/orchestrator.py` — `_clarify` guard/capture/suggest/finalize (:986-1178), resume claim + bind (:227-734), `_defer_field_regression_clarification` (:746-834), `_combined_context_email` (:837-850), `is_round_2` (:346), `_write_aliases_if_safe` (:1181-1260)
- `app/main.py` — ingest txn + duplicate outcome (:370-465), `_finish_reply_resume`/`_route_reply`/`_resume_pipeline` (:545-622), approve/reject (:642-698), retrigger + stale scope (:701-800), badge maps + IN_FLIGHT (:103-226), runs-list sweep hook (:1062-1076)
- `app/db/repo.py` — `insert_email_message` upsert (:963-1051), `get_outbound_message_id` (:1054-1080), `link_email_to_run` (:199), `claim_status` (:422), `load_thread_messages` (:1257)
- `app/db/schema.sql` — status CHECK ×2 (:68-80, :141-171), purpose CHECK + uq constraint (:194-278)
- `app/pipeline/suggest.py` — `suggest_employees` returns name→full_name (:60-72)
- `app/models/status.py` — RunStatus 10 values
- `tests/` — `test_multiround_context_edge.py` (flip instructions :14-46), `conftest.py` InMemoryRepo (:236+), `test_status_drift.py`, `test_stuck_run_recovery.py` scope pins; offline collection verified (568 tests)

### Secondary (HIGH — project planning artifacts)
- `.planning/phases/09-atomic-data-integrity/09-REVIEW.md` (WR-03/04/05/06 full findings), `09-REVIEWS.md` (CX-01 :138-142), `09-CONTEXT.md` (deferred dispositions :120-164)
- `.planning/todos/pending/260705-01.md`, `260705-02.md`, `260623-08.md` (traced repros + premise correction)
- `.planning/ROADMAP.md` Phase 11 entry (:156-164), `.planning/REQUIREMENTS.md` (no Phase 11 IDs yet)

### Tertiary
- Postgres semantics (NULL-distinct unique constraints; ON CONFLICT arbiter inference) — standard documented behavior, additionally evidenced by in-repo comments that rely on it (`schema.sql:219-220`, `repo.py:985-986`). Treated HIGH via codebase corroboration.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies; existing pins verified in repo
- Architecture: HIGH — all seams and invariants re-traced against live source this session; decisions locked in CONTEXT.md
- Pitfalls: HIGH — each derives from a verified code coupling (constraint↔ON CONFLICT, three finalize paths, seven status mirrors, suggest name-vs-id, fake-repo mirroring)
- Live-data migration details: MEDIUM — production row shapes inferred, not queried (Assumptions A1/A2); backfill formulas are deterministic either way

**Research date:** 2026-07-05
**Valid until:** ~2026-08-05 (internal codebase research — invalidated only by intervening commits to the touched files, notably if Phase 10 lands first and adds fencing primitives)
