---
phase: 11-clarification-round-machine-alias-learning
reviewed: 2026-07-06T20:15:39Z
depth: deep
review_mode: cross-ai (gsd-code-reviewer [Sonnet] + Codex CLI 0.135.0, findings reconciled and source-verified by orchestrator)
diff_range: c2f1f64..bb78046 (app/** only, 1088 insertions / 11 files)
files_reviewed: 11 production + 8 test
findings:
  critical: 5
  warning: 3
  info: 2
status: gaps_found
verified: true
---

# Phase 11 Code Review — Clarification Round Machine & Alias Learning

Two independent reviewers (internal `gsd-code-reviewer` on Sonnet + Codex CLI) reviewed the same 1088-line production diff. **Both converged on the bind-on-inference bug and the unauthenticated `/resolve` route** — the strongest confidence signal. The orchestrator then **traced argument flow through the actual source for every critical claim** (per this project's Phase-7.5 lesson: prose-reading missed 6 bugs that arg-tracing caught) and recorded a CONFIRMED/REFUTED verdict per finding.

**Headline:** 5 CONFIRMED critical bugs, 4 of them a single coherent class — **Phase 11's new retrigger/redelivery/stranded/operator-resume seams read state from `email_messages` and re-key CAS transitions, but the surrounding code either (a) clears the wrong table, (b) double-claims the same status, or (c) skips the sender check.** All five are money-path or security. None was caught by the (green, 588-passing) suite because the relevant tests **mock the very seam that fails** (`resume_pipeline` mocked; two-tokens-across-two-rounds untested; spoofed-sender-then-redelivery untested).

---

## CRITICAL

### CR-1 — Operator `/resolve` double-CAS strands the run in `EXTRACTING` forever  ✅ CONFIRMED
- **Where:** `app/main.py:859` (route claims `NEEDS_OPERATOR → EXTRACTING`) → dispatches `_operator_resume` → `app/pipeline/orchestrator.py:328` (`resume_pipeline` claims `NEEDS_OPERATOR → EXTRACTING` **again**).
- **Sources:** Codex (CRITICAL #1). Orchestrator-verified.
- **Defect:** The `/resolve` route already transitions the run to `EXTRACTING` at line 859, then background-dispatches `resume_pipeline(from_status=NEEDS_OPERATOR)`, which does a *second* `claim_status(NEEDS_OPERATOR → EXTRACTING)`. That CAS sees status is already `EXTRACTING`, returns `False`, and `resume_pipeline` **returns early at orchestrator.py:336 doing nothing** (line 329-336).
- **Failure scenario:** Operator opens a `needs_operator` run, maps "Dave"→David via the resolve form, submits. Route validates, claims `EXTRACTING`, schedules resume. Resume's CAS fails → no extraction, no reconcile, no compute. **The run is now stuck in `EXTRACTING` with no processing and no error** — it never reaches approval, never pays, and only a stale-sweep/retrigger can recover it. The operator's resolution is silently dropped.
- **Why the suite missed it:** `tests/test_needs_operator.py:528-532` **mocks `resume_pipeline`** and only asserts the route reached `EXTRACTING` + recorded a call. The real double-claim is never exercised. (This is the project's documented "green hermetic test hides the money bug" anti-pattern.)
- **Fix direction:** `/resolve` must NOT pre-claim. Either dispatch `_operator_resume` from `needs_operator` and let `resume_pipeline` own the single CAS (`from_status=NEEDS_OPERATOR`), or have the route claim and pass `resume_pipeline` a `from_status=EXTRACTING`-aware "already claimed" path. Add an end-to-end test that drives REAL `resume_pipeline` to `AWAITING_APPROVAL`.

### CR-2 — Retrigger silently re-strands: old round-0 outbound row suppresses the fresh clarification send  ✅ CONFIRMED
- **Where:** `app/main.py:1000` (`clear_reply_context` on retrigger) + `app/db/repo.py:974` (clears `payroll_runs` only) + `app/pipeline/orchestrator.py:1240-1257` (`_clarify` guard reads `email_messages`).
- **Sources:** Codex (CRITICAL #2). Orchestrator-verified.
- **Defect:** `clear_reply_context` resets `payroll_runs.clarification_round = 0` but does **not** touch `email_messages`. The prior round-0 `sent` outbound clarification row survives. On the retriggered run's first clarification, `_clarify` calls `get_outbound_for_round(purpose='clarification', round=0)` (orchestrator.py:1252), which finds the stale round-0 `sent` row → treats it as a duplicate → sets `AWAITING_REPLY` **without sending an email** (orchestrator.py:1257-1268).
- **Failure scenario:** A run sends a round-0 clarification, later errors. Operator retriggers. The fresh run again needs the same clarification, but `_clarify` sees the old sent row at round 0 and parks at `awaiting_reply` with no email out. **This is WR-05 — the exact silent-park bug Phase 11 was built to eliminate — re-introduced through the retrigger path.**
- **Fix direction:** On retrigger, either delete/tombstone the run's prior outbound clarification rows, or advance a per-retrigger epoch so the round space is fresh, or key the guard on `(purpose, round, epoch)`. Add a test: retrigger a run that already sent round-0, assert a NEW outbound clarification row is written.

### CR-3 — Retrigger re-injects a stale consumed reply into extraction (mispay)  ✅ CONFIRMED
- **Where:** `app/db/repo.py:974` (`clear_reply_context` doesn't clear `email_messages.consumed_round`) + `load_consumed_replies` (reads all consumed rows for the run) via `resume_pipeline`.
- **Sources:** Codex (CRITICAL #4). Orchestrator-verified (nothing on the retrigger path resets `consumed_round`; the only writer is `mark_reply_consumed`, repo.py:1216).
- **Defect:** Prior consumed replies keep their `consumed_round` stamp across a retrigger. If the retriggered run reaches a resume, `load_consumed_replies` re-injects those stale replies into the combined extraction context.
- **Failure scenario:** Round-1 reply said "John should be 30, not 40". Run errors, operator retriggers, a fresh clarification cycle answers a *different* name. On resume, the stale "John 30" reply is re-accumulated into the extraction context and John is paid 30 in a run he was never part of this cycle — **under/mis-payment from a conversation that no longer exists.**
- **Fix direction:** `clear_reply_context` should also null/namespace `consumed_round` for the run's inbound rows (or scope `load_consumed_replies` to the current epoch). Same epoch mechanism as CR-2 would close both.

### CR-4 — Alias bind fires on inference, not confirmation (silent misroute) — **DUAL-SOURCE**  ✅ CONFIRMED
- **Where:** `app/pipeline/orchestrator.py:845-857` (bind-on-confirmation STEP C).
- **Sources:** Codex (CRITICAL #3) **AND** internal `gsd-code-reviewer` (CR-03) — independent convergence. Orchestrator-verified.
- **Defect:** The bind fires when two facts, computed **independently over the whole run's reconciliation**, are both true: (a) the persisted SUGGESTED id newly appears in `_post_resolved_ids`, and (b) the token string is absent from `_post_unresolved_names`. These are not tied to the *same* submitted-name record, so a coincidence satisfies them without the client ever confirming the token.
- **Failure scenario:** Token "Dave" (suggestion → David). Client replies "No, Dave didn't work this period; David worked 5 hours separately." Post-reconciliation now contains David (newly resolved, via the *separate* "David" line) and "Dave" is gone from unresolved (client said he didn't work) → the guard binds **`Dave → David`**. Future "Dave" submissions silently pay David. **This is exactly the never-learn-from-inference / misname class the guard is supposed to make impossible.**
- **Why the suite missed it:** `test_alias_full_loop.py` proves the *positive* confirmation path and one misname case, but not the "suggested id resolves via an unrelated line while the token independently drops out" case.
- **Fix direction:** Bind only when the SAME submitted-name record for the token resolves to the suggested id (tie fact (a) and (b) to one reconciliation entry), i.e. the token itself must resolve to S — not "S resolved somewhere AND token vanished."

### CR-5 — Redelivery / stranded auto-resume bypass FIX-5 sender revalidation (spoof reopen)  ✅ CONFIRMED
- **Where:** `app/main.py:463-489` (WR-04 duplicate-redelivery reschedule) and the D-11-05 stranded sweep (`app/main.py:~1276` + `app/db/repo.py` `find_stranded_unconsumed_replies`), vs. FIX-5 which lives only in `_finish_reply_resume` (`app/main.py`, post-commit).
- **Sources:** Internal `gsd-code-reviewer` (CR-01). Orchestrator-verified.
- **Defect:** The ingest transaction links a header-matched reply to its run (`link_email_to_run`, main.py:418) **inside the committed transaction, based purely on the RFC header chain** (`in_reply_to`/`references` — attacker-controllable), with `consumed_round=NULL`. FIX-5 (`find_business_by_sender` match) runs only **post-commit** in `_finish_reply_resume`. A reply that FAILS FIX-5 returns `sender_mismatch` but **leaves a linked, unconsumed row**. The WR-04 redelivery branch (main.py:477-483) and the stranded sweep both re-schedule resume checking only `consumed_round IS NULL` + `status==awaiting_reply` — **neither re-runs the sender check.**
- **Failure scenario:** Attacker sends a reply with the correct `References` header for a victim run but a spoofed `From`. FIX-5 blocks the immediate resume — but the row is persisted linked+unconsumed. The attacker re-sends the same message (redelivery) → WR-04 resumes it with no sender check; OR the operator simply loads `/runs` after the 15-min spin-down → the stranded sweep auto-resumes it. **The spoofed reply drives the victim's payroll extraction — the exact class FIX-5 exists to close.**
- **Fix direction:** Both re-schedule seams must re-assert FIX-5 (`find_business_by_sender(from_addr) == run.business_id`) before dispatching resume — route them through `_finish_reply_resume`'s guard rather than straight to `_resume_pipeline`. Add a test: persist a FIX-5-failed linked reply, trigger redelivery and the sweep, assert NO resume.

---

## WARNING

### WR-1 — `set_alias_candidates` is a full-column overwrite; concurrent/sequential writes clobber  ⚠️ CONFIRMED (narrower)
- **Where:** `app/db/repo.py:831-846` (`UPDATE ... SET alias_candidates = %s`), written by `_clarify` capture (orchestrator.py:~1371), the STEP-C bind (orchestrator.py:824-872, off a pre-`_run_stages` snapshot), and `/resolve` remember (main.py:851-857).
- **Sources:** Internal `gsd-code-reviewer` (CR-02).
- **Defect:** Full-column overwrite, not a JSONB merge. With ≥2 distinct tokens across ≥2 rounds, the last writer erases the others; a client-confirmed bind from an earlier round can be wiped before `_write_aliases_if_safe` reads it at approval. Ranked WARNING (not Critical) because the current single-token-per-clarify capture rule limits the multi-token surface today — but the bind/resolve writes still snapshot-then-overwrite. No test exercises two tokens across two rounds of one run.
- **Fix direction:** Make the write a merge (`alias_candidates = alias_candidates || %s::jsonb`) or read-modify-write under the run row lock.

### WR-2 — Operator-resume with mixed collision + field-regression history extracts against an empty body
- **Where:** `resume_pipeline` operator path (synthetic empty-body InboundEmail) → Round-2 classify-first branch / `_unresolvable_asked`.
- **Sources:** Internal `gsd-code-reviewer` (WR-01).
- **Defect:** A `needs_operator` run whose history includes a field-regression clarification, when operator-resumed with `inbound=None`, can route into the classify-first branch that extracts against the synthetic empty body and force-nulls previously-asked fields — silently under-filling data the client supplied in the original email. Verify against the actual `is_round_2`/classify predicate; may be partially mitigated by the operator override path. Needs a targeted test.

### WR-3 — `/resolve` (and all dashboard routes) have no auth/CSRF — money-adjacent  ⚠️ KNOWN/ACCEPTED
- **Where:** `app/main.py:771` `/resolve`; also `/approve`, `/reject`, `/retrigger`, `/simulate-reply`.
- **Sources:** Codex (CRITICAL #5) + internal (WR). **Reconciled DOWN to Warning:** the entire dashboard is intentionally unauthenticated (single-operator demo; the webhook has sender auth, the dashboard does not). `/resolve` is **consistent with the existing architecture**, not a Phase-11 regression — Security V4's server-side roster validation (which IS present and correct, main.py:832-844) scopes it to the run's own business so there's no cross-business escalation. Flagged so it's a conscious standing risk, not a silent one. Codex's CRITICAL rating is the correct severity *if* this app were ever exposed beyond a trusted single operator.

---

## INFO

- **IN-1 — `run["business_id"]` unguarded subscript in `_write_aliases_if_safe`** (internal): a legacy/malformed run row missing `business_id` would `KeyError` inside the approval-gate write rather than degrading. Low likelihood; harden with `.get`.
- **IN-2 — Silent no-op on roster-load failure in `/resolve`** (main.py:820-822): a transient roster-load error returns a bare 303 with no operator-visible signal; the operator sees the same page and may not know why nothing happened. Consider a flash message.

---

## Verified clean (both reviewers agree)
- Round-cap boundary (`>= MAX_CLARIFICATION_ROUNDS`) and its escalation-only-write transaction; the `(purpose, round)` guard semantics **within a single non-retriggered run**.
- Security V4 server-side roster validation on `/resolve` — whole-POST rejection, scoped to the run's own business (no cross-business `employee_id` acceptance — Codex explicitly re-checked and cleared this).
- `needs_operator` exclusion from `IN_FLIGHT_STATUSES`, the stranded scope, and retrigger `stale_statuses`.
- Schema migration idempotency.
- Money-path test assertions in `test_multiround_context_edge.py` / `test_alias_full_loop.py` assert genuine persisted `Decimal` paystub values, not labels.

## Suite-quality note (cross-cutting)
This repo's `.env` carries LIVE LLM keys, so any test reaching clarify/suggest/extract without stubbing hits the real nondeterministic model (already bit `test_alias_write.py` during execution — fixed in `2f024bf`). The deeper pattern behind CR-1/CR-4/CR-5: **the tests mock the exact seam that fails** (`resume_pipeline` mocked in the resolve test; no spoof-then-redelivery test; no two-token/two-round test). Green + 588-passing did NOT prove money-safety here — consistent with the project's standing lesson.
