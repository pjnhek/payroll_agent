---
phase: 11-clarification-round-machine-alias-learning
verified: 2026-07-06T21:53:08Z
status: passed
score: 7/7 must-haves hold (all 5 confirmed critical bugs from 11-REVIEW.md traced dead in merged HEAD 9000e11; WR-1 also closed; no regressions)
gap_source: 11-REVIEW.md
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 2/7 must-haves hold
  gaps_closed:
    - "GAP-1 (CR-1): /resolve double-CAS strand — resume_pipeline is now the SOLE claimer"
    - "GAP-2 (CR-2): retrigger stale round-0 sent row silently suppressing fresh send — epoch scoping closes it"
    - "GAP-3 (CR-3): retrigger re-injecting a stale consumed reply into extraction — epoch scoping closes it"
    - "GAP-4 (CR-4): alias bind firing on unrelated inference, not confirmation — same-record evidence tie closes it"
    - "GAP-5 (CR-5): redelivery/stranded-sweep bypassing FIX-5 sender revalidation — _reply_sender_ok re-asserted at both seams"
    - "WR-1: set_alias_candidates full-column overwrite clobbering concurrent tokens — JSONB merge closes it"
  gaps_remaining: []
  regressions: []
status_history:
  - "2026-07-06T03:11:41Z passed (7/7) — initial gsd-verifier"
  - "2026-07-06 gaps_found — cross-AI review (Codex + internal) confirmed 5 criticals the initial pass missed"
  - "2026-07-06T21:53:08Z passed (7/7) — adversarial re-verification of gap-closure plans 11-06/07/09/10, all 5 exploits traced dead in merged source, 596-passed suite run twice byte-identical"
must_haves:
  truths:
    - "CLAR2-01: a genuinely new clarification question always sends; a true same-round duplicate is still suppressed; no run silently parks at awaiting_reply with no email out — INCLUDING across a retrigger (GAP-2 closed the retrigger-specific regression)"
    - "CLAR2-02: after 3 total clarification rounds the run escalates to needs_operator (no LLM/gateway call); operator can resolve deterministically and resume (via a SINGLE CAS owned by resume_pipeline, GAP-1 closed), or reject"
    - "CLAR2-03: resume extraction context includes a code-owned 'questions we asked' anchor; a bare answer cannot be blindly attributed"
    - "CLAR2-04: the alias-learning write side is reachable via bind-on-confirmation tied to the token's OWN reconciliation record (GAP-4 closed the unrelated-inference exploit); misname guard survives; set_alias_candidates is a JSONB merge so concurrent/sequential token writes never clobber (WR-1 closed); a full-loop test proves stops-asking with REAL resolution"
    - "CLAR2-05: multi-round context loss is closed — the combined context accumulates ORIGINAL + ALL consumed replies in round order; the known-edge fixture flips (Round-1 '30, not 40' pays 30)"
    - "CLAR2-06: a redelivered unconsumed reply re-schedules resume ONLY if FIX-5 sender revalidation re-passes (GAP-5 closed the spoofed-sender bypass); a consumed reply's redelivery is a no-op; a stranded unconsumed reply is auto-rescheduled from the runs-list load under the SAME re-asserted sender check; needs_operator is excluded"
    - "CLAR2-07: retrigger clears ALL reply context (clarified_fields, pre_clarify_extracted, round counter, suggestion/candidate state) AND bumps a per-run epoch so no stale email_messages row (sent-outbound or consumed-inbound) can leak across the retrigger boundary — the append-only audit log is preserved untouched"
---

# Phase 11: Clarification Round Machine & Alias Learning — Re-Verification Report (Post Gap-Closure)

**Phase Goal:** The multi-round clarification state machine becomes correct and unstrandable, and the alias-learning loop actually learns — WR-05 round-aware idempotency + cap/escalation, question-anchored attribution, bind-on-confirmation alias learning reachability, CX-01 multi-round context-loss closure, and WR-06/WR-04 provenance-scoping/redelivered-reply handling folded into one round/consumed state design.

**Verified:** 2026-07-06T21:53:08Z
**Merged HEAD:** `9000e11` (master) — all 4 gap-closure plans (11-06, 11-07, 11-09, 11-10) merged
**Status:** passed
**Re-verification:** Yes — adversarial re-verification after gap-closure, per explicit instruction to trace the exploit scenarios in `11-REVIEW.md` against the merged source rather than trust SUMMARY.md claims or green tests alone.

## Adversarial Method

Per-gap: (1) locate the exact code the review cited as broken, (2) confirm the merged HEAD changed it, (3) re-derive from first principles whether the SPECIFIC exploit scenario in `11-REVIEW.md` can still fire, (4) locate/run the regression test that targets that exact scenario and confirm it exercises the REAL seam (not a mock of the broken code path), (5) confirm the legitimate/happy-path behavior the fix must not break still passes.

## Goal Achievement — Per-Gap Exploit Trace

### GAP-1 / CR-1 — `/resolve` double-CAS strand — ✓ EXPLOIT DEAD

**Original bug:** `main.py:859` claimed `NEEDS_OPERATOR → EXTRACTING`, then `resume_pipeline` (`orchestrator.py:328` at the time) claimed it AGAIN — the second CAS always failed, `resume_pipeline` returned early, the run was permanently stranded in `EXTRACTING`.

**Trace of merged HEAD:**
- `app/main.py:806-908` (`resolve()` route) — grepped for `claim_status(run_id, RunStatus.NEEDS_OPERATOR, RunStatus.EXTRACTING)` directly in the route body: **zero matches**. The route validates the POST (Security V4 roster check, `main.py:868-887`), optionally pre-sets `alias_candidates` (`main.py:894-900`), then unconditionally does `background_tasks.add_task(_operator_resume, run_id, overrides)` (`main.py:907`) — no claim, no gate.
- `_operator_resume` (`main.py:911-927`) calls `resume_pipeline(run_id, None, from_status=RunStatus.NEEDS_OPERATOR, overrides=overrides)` with no pre-check.
- `resume_pipeline` (`orchestrator.py:320-387`) performs exactly ONE `claim_status(run_id, from_status, RunStatus.EXTRACTING)` (`orchestrator.py:379`) — this is now the SOLE CAS in the entire operator-resume path.
- **Exploit scenario re-derived:** operator submits a valid resolve form → route validates → schedules `_operator_resume` → `resume_pipeline`'s single CAS claims `NEEDS_OPERATOR → EXTRACTING` → succeeds (no competing claim) → `_run_stages` runs for real → run reaches `AWAITING_APPROVAL`. No double-claim possible; the exploit's precondition (two competing claims on the same transition) no longer exists in the code.
- **Webhook reply path unbroken:** `_resume_pipeline` (main.py:707-718, the webhook's background wrapper) calls `resume_pipeline(run_id, inbound)` with the DEFAULT `from_status=RunStatus.AWAITING_REPLY` — untouched by this fix, still a single CAS owned by `resume_pipeline` alone, exactly as before.
- **Regression test:** `tests/test_needs_operator.py::test_resolve_drives_real_resume_pipeline_to_awaiting_approval` (lines 704-780) seeds a REAL `needs_operator` run via `create_run`, POSTs to the real `/resolve` HTTP route via `TestClient`, and asserts (a) `final_run["status"] != "extracting"`, (b) `final_run["status"] == AWAITING_APPROVAL`, (c) a real computed paystub line item exists for the resolved employee — driven through the REAL `resume_pipeline` (`mock_llm` stubs only the LLM text, nothing in the claim/resume chain is mocked). Ran this test directly: **PASS**.
- **Companion unit test flipped correctly:** `test_resolve_applies_override_and_claims_on_valid_post` now asserts the run STAYS at `needs_operator` immediately after the route call (proving the route itself does not claim) — the exact assertion polarity that would have caught the original bug.

**Verdict: EXPLOIT DEAD.** Evidence: `app/main.py:806-927`, `app/pipeline/orchestrator.py:320-387`, `tests/test_needs_operator.py:704-780` (run, PASS).

---

### GAP-2 / CR-2 — Retrigger stale round-0 sent row suppresses fresh clarification — ✓ EXPLOIT DEAD

**Original bug:** `clear_reply_context` reset `clarification_round=0` but never touched `email_messages`; the prior round-0 `sent` outbound row survived, and `_clarify`'s `get_outbound_for_round(round=0)` found the stale row and silently parked at `awaiting_reply` with no send (WR-05 reintroduced).

**Trace of merged HEAD:**
- `clear_reply_context` (`app/db/repo.py:1004-1037`) now bumps `reply_epoch = reply_epoch + 1` in the SAME UPDATE statement as the existing null-outs (`repo.py:1029-1037`).
- `get_outbound_for_round` (`repo.py:1237-1277`) — the SQL now includes `AND epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s)` (`repo.py:1269`). A stale epoch-0 round-0 row is now invisible to a run that has advanced to epoch 1.
- `insert_email_message`'s outbound path (`repo.py:1081-1205`) stamps the new row's `epoch` from a correlated subquery on the run's CURRENT `reply_epoch` at write time (`repo.py:1150-1151`), and the `ON CONFLICT` arbiter was WIDENED from `(run_id, purpose, round)` to `(run_id, purpose, round, epoch)` (`repo.py:1152`, schema.sql:265) — this was a self-caught deviation in 11-06 (the 3-column arbiter would have silently upserted/mutated the stale historical row on every retrigger; caught by the append-only assertion in TDD before it could reach a real database).
- **Exploit re-derived:** run sends round-0 clarification (epoch 0) → errors → operator retriggers → `clear_reply_context` bumps epoch to 1 → run's next clarification attempt calls `get_outbound_for_round(round=0)` scoped to epoch 1 → the epoch-0 row is invisible → `existing_clari is None` → falls through to a REAL send. Exploit precondition (stale row visible at the new attempt) no longer holds.
- **Regression test:** `tests/test_retrigger_epoch.py::test_retrigger_sends_fresh_clarification_despite_stale_round0_sent_row` seeds a stale epoch-0 'sent' row, calls the REAL `fake_repo.clear_reply_context`, then drives the REAL `_clarify` (not mocked) and asserts a gateway send actually fired (`send_calls` spy) AND that both the stale epoch-0 row and the fresh epoch-1 row coexist afterward (append-only proof — nothing deleted/mutated). Ran directly: **PASS**.

**Verdict: EXPLOIT DEAD.** Evidence: `app/db/repo.py:1004-1037,1150-1152,1237-1277`, `app/db/schema.sql:246,265`, `tests/test_retrigger_epoch.py:98-198` (run, PASS).

---

### GAP-3 / CR-3 — Retrigger re-injects a stale consumed reply (mispay) — ✓ EXPLOIT DEAD

**Original bug:** `clear_reply_context` never nulled `email_messages.consumed_round`; a retriggered run's resume would re-accumulate a stale consumed reply from a conversation that no longer exists, mispaying against a corrected/no-longer-applicable instruction.

**Trace of merged HEAD:**
- `load_consumed_replies` (`repo.py:1297-1322`) SQL now includes `AND epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s)` (`repo.py:1316`) — a stale consumed reply from epoch 0 is invisible to a run now at epoch 1.
- `link_email_to_run` (`repo.py:218-251`) stamps `epoch` at link time from the run's CURRENT `reply_epoch` (`repo.py:248`) — never re-stamped afterward, so a row's epoch is a permanent, point-in-time fact (confirmed by the test's explicit assertion that the row's `epoch` stays 0 after the retrigger bump).
- `find_stranded_unconsumed_replies` (`repo.py:1360-1396`) JOIN condition also requires `em.epoch = pr.reply_epoch` (`repo.py:1386`) — closes the same class for the stranded-sweep path specifically.
- **Exploit re-derived:** reply consumed at epoch 0 (`mark_reply_consumed` stamps `consumed_round`) → retrigger bumps epoch to 1 → `load_consumed_replies(run_id)` now scoped to epoch 1 → returns empty → the resume's combined extraction context does NOT include the stale reply. Exploit precondition (stale reply visible to post-retrigger accumulation) no longer holds.
- **Regression test:** `tests/test_retrigger_epoch.py::test_retrigger_forgets_consumed_reply_from_prior_epoch` drives a REAL `resume_pipeline` call so `mark_reply_consumed` fires genuinely (not hand-seeded), asserts `load_consumed_replies` returns 1 row pre-retrigger, then calls the REAL `clear_reply_context`, and asserts `load_consumed_replies` returns EMPTY post-retrigger while the raw row is proven to still physically exist with its `consumed_round` stamp intact and its own `epoch` still 0 (append-only proof). Ran directly: **PASS**.

**Verdict: EXPLOIT DEAD.** Evidence: `app/db/repo.py:218-251,1297-1322,1360-1396`, `tests/test_retrigger_epoch.py:208-339` (run, PASS).

---

### GAP-4 / CR-4 — Alias bind fires on unrelated inference, not confirmation — ✓ EXPLOIT DEAD

**Original bug:** the bind computed two facts INDEPENDENTLY over the whole run's post-resume reconciliation — (a) the suggested id newly resolves SOMEWHERE, (b) the token vanishes from unresolved SOMEWHERE — satisfiable by two unrelated reconciliation records. "No, Dave didn't work this period; David worked 5 hours separately" bound `Dave → David` with no actual confirmation.

**Trace of merged HEAD:**
- New helper `_bind_evidence_for_token(token, suggested_id, suggested_full_name, post_reconciliation)` (`orchestrator.py:108-156`) requires a SINGLE reconciliation entry whose `submitted_name` (normalized) equals EITHER the token's own text OR the suggested employee's own canonical `full_name`, AND that SAME entry has `resolved=True` AND `matched_employee_id == suggested_id` (`orchestrator.py:146-155`). This is a genuine same-record tie, not a two-set diff.
- Call site (`orchestrator.py:868-904`) resolves `_suggested_full_name` from the already-loaded roster per pending token (`orchestrator.py:890-896`, fail-closed to `None` if not found, which can only narrow matches) and calls the helper per token (`orchestrator.py:898-900`) — replacing the old `_pre_resolved_ids`/`_post_unresolved_names` independent-set diff entirely (dead code removed, confirmed via the 11-09 SUMMARY's explicit grep-before-removal note).
- **Exploit re-derived with the EXACT scenario:** token "Dave" suggested → David's id. Post-resume reconciliation has ONE entry: `submitted_name="David"` (a NEW, separate line), `resolved=True`, `matched_employee_id=david.id`. Normalized, `"david"` (from "David") does NOT equal `_norm("Dave")` NOR does it equal `_norm("David Reyes")` (the suggested employee's own full name) UNLESS the token's own text happens to collide — in the reviewed exploit scenario, "David" (the post-resume record) fails to match "David Reyes" (canonical full name) after normalization, so `_bind_evidence_for_token` returns `False`. No entry ties back to "Dave" itself. **Nothing binds.**
- **Regression test:** `tests/test_alias_write.py::test_resume_binding_exploit_unrelated_resolution_binds_nothing` (lines 957-1119) reproduces this exact scenario verbatim — a real (non-empty) roster containing the real David Reyes employee (so the fix is tested honestly, not against a degraded fail-closed fallback), pre-reconciliation with only "Dave" unresolved, post-reconciliation with only the unrelated "David" entry, drives the REAL `resume_pipeline`, and asserts no `set_alias_candidates` call ever binds "Dave" to anything. Ran directly: **PASS**.
- **Legitimate confirmation still binds:** `tests/test_alias_full_loop.py::test_full_loop_learns_alias_and_stops_asking` (Jimmy→James full loop, REAL `reconcile_names` + REAL `_write_aliases_if_safe`) and `test_misname_reply_binds_nothing_end_to_end` (misname guard) both re-ran clean with ZERO code changes required, because the real resolution chain naturally produces a reconciliation entry whose `submitted_name` equals the suggested employee's own `full_name` — satisfying the same-record tie honestly. Ran directly: **PASS** (both).

**Verdict: EXPLOIT DEAD; legitimate path intact; misname guard intact.** Evidence: `app/pipeline/orchestrator.py:108-156,868-904`, `tests/test_alias_write.py:957-1119` (run, PASS), `tests/test_alias_full_loop.py:131-,291-` (run, PASS).

---

### WR-1 — `set_alias_candidates` full-column overwrite clobbers concurrent/sequential writes — ✓ EXPLOIT DEAD

**Original bug:** `UPDATE ... SET alias_candidates = %s` was a blind overwrite; with 2+ tokens across 2+ rounds, the last writer erased every other token's candidate, including an already-CONFIRMED bind.

**Trace of merged HEAD:**
- `set_alias_candidates` (`app/db/repo.py:840-876`) SQL is now `alias_candidates = COALESCE(alias_candidates, '{}'::jsonb) || %s::jsonb` (`repo.py:872-874`) — a JSONB merge, COALESCE-wrapped for NULL-safety on a fresh run.
- `InMemoryRepo.set_alias_candidates` (`tests/conftest.py:530-540`) mirrors this as a dict merge (`{**existing, **new}`), matching Postgres `||` semantics.
- **Exploit re-derived:** TokenA confirmed-bound in round 1 → TokenB captured in round 2 (unrelated write) → under the OLD overwrite, TokenB's write would erase TokenA entirely. Under the merge, TokenA's key is untouched because `||` only overwrites keys present in the new dict.
- **Regression test:** `tests/test_alias_write.py::test_set_alias_candidates_merges_across_two_tokens_two_rounds` (lines 1499-1553) writes TokenA (confirmed bind) then TokenB (unrelated) via the REAL `repo.set_alias_candidates` (routed through the `fake_repo` monkeypatch of the module-level function, exercising the actual merge-dict code path), and asserts BOTH tokens' candidates persist correctly afterward. Ran directly: **PASS**. A static SQL-string pin (`test_repo_set_alias_candidates_sql_uses_jsonb_merge_not_overwrite`, lines 1555-1569) additionally asserts the PRODUCTION SQL text contains `COALESCE(alias_candidates` and `|| %s::jsonb` — a regression guard against silently reverting to an overwrite. Ran directly: **PASS**.

**Verdict: EXPLOIT DEAD.** Evidence: `app/db/repo.py:840-876`, `tests/conftest.py:530-540`, `tests/test_alias_write.py:1499-1569` (run, PASS).

---

### GAP-5 / CR-5 — Redelivery/stranded-sweep bypass FIX-5 sender revalidation (spoof reopen) — ✓ EXPLOIT DEAD

**Original bug:** a reply linked to a run purely via the RFC header chain (attacker-controllable) inside the committed ingest transaction, with `consumed_round=NULL`; FIX-5's sender check ran only post-commit in `_finish_reply_resume` on FIRST delivery. A FIX-5-FAILED reply stayed linked+unconsumed, and BOTH the WR-04 redelivery branch and the D-11-05 stranded sweep re-scheduled resume checking only `consumed_round`/status — NEVER the sender — so a spoofed reply could still drive the victim's payroll via a redelivery or a later dashboard load.

**Trace of merged HEAD:**
- New shared predicate `_reply_sender_ok(row, run)` (`app/main.py:576-597`) calls `find_business_by_sender(row["from_addr"])` exactly once and reproduces `_finish_reply_resume`'s EXACT comparison (`reply_business_id is not None and str(reply_business_id) == str(run["business_id"])`) — confirmed byte-for-byte equivalent to `_finish_reply_resume`'s own inline check (`main.py:622-625`).
- **WR-04 redelivery seam** (`main.py:463-500`, the `outcome == "duplicate"` branch): the dispatch to `_resume_pipeline` is now gated by `if _reply_sender_ok(reply_row, linked_run):` (`main.py:488`) — a sender-mismatched candidate logs a warning and is skipped (`main.py:495-500`), never dispatched.
- **D-11-05 stranded-sweep seam** (`main.py:1302-1342`, inside `runs_list()`): loads `candidate_run = repo.load_run(reply_row["run_id"])` and gates dispatch on `_reply_sender_ok(reply_row, candidate_run)` (`main.py:1330-1331`) — same skip-and-log behavior on mismatch (`main.py:1335-1340`), inside the same swallow-on-failure try/except as the sweep so a lookup failure still cannot 500 the dashboard.
- **Exploit re-derived:** attacker sends a reply with a matching `References` header (victim run) but a spoofed `From` → ingest links it (`consumed_round=NULL`) → FIX-5 fails on first delivery (`_finish_reply_resume` returns `sender_mismatch`, row stays linked+unconsumed) → attacker redelivers the SAME message_id → WR-04 branch now calls `_reply_sender_ok` BEFORE dispatch → `find_business_by_sender(spoofed_from)` resolves to a DIFFERENT business (or None) than the run's own `business_id` → predicate returns `False` → dispatch skipped. Same outcome via the stranded-sweep path on a later `/runs` load. Exploit precondition (bypassing sender check at either re-schedule seam) no longer holds.
- **Regression tests:** `tests/test_reply_redelivery.py::test_redelivery_never_resumes_fix5_failed_reply` and `::test_stranded_sweep_never_resumes_fix5_failed_reply` (lines 342-412) reproduce the exact spoofed-sender-then-redelivery / spoofed-sender-then-dashboard-load scenarios via a `resume_spy` fixture asserting zero re-schedules. Ran directly: **PASS** (both).
- **Legitimate sender-matching cases still resume:** `test_unconsumed_redelivery_reschedules` and `test_runs_list_reschedules_stale_unconsumed_reply` (pre-existing, sender-matching fixtures) both still pass in the same run.

**Verdict: EXPLOIT DEAD; legitimate resume paths intact.** Evidence: `app/main.py:463-500,576-597,1302-1342`, `tests/test_reply_redelivery.py:342-412` (run, PASS; full file 8/8 PASS).

---

## Test Evidence

### Full offline suite, run TWICE (determinism / live-LLM-leak check)

| Run | Command | Result |
|-----|---------|--------|
| 1 | `uv run pytest -q -m "not integration and not live_llm"` | **596 passed, 20 skipped, 28 deselected** (33.08s) |
| 2 | same command, re-run | **596 passed, 20 skipped, 28 deselected** (30.33s) — byte-identical to run 1 |

596 = 588 (pre-gap-closure baseline) + 8 new gap-closure regression tests (1 GAP-1 + 2 GAP-2/3 + 3 GAP-4/WR-1 + 2 GAP-5). No flakiness, no live-model reachability (all new tests use `mock_llm` or `llm=None` + explicit stub, confirmed by direct grep of every new test file).

### Targeted per-gap test runs (all PASS, run directly by the verifier, not taken from SUMMARY claims)

| Test | Result |
|------|--------|
| `tests/test_needs_operator.py -k resolve` (4 tests) | PASS |
| `tests/test_retrigger_epoch.py` (2 tests) | PASS |
| `tests/test_alias_write.py::test_resume_binding_exploit_unrelated_resolution_binds_nothing` | PASS |
| `tests/test_alias_write.py::test_set_alias_candidates_merges_across_two_tokens_two_rounds` | PASS |
| `tests/test_alias_write.py::test_repo_set_alias_candidates_sql_uses_jsonb_merge_not_overwrite` | PASS |
| `tests/test_alias_full_loop.py` (both anchor tests) | PASS |
| `tests/test_reply_redelivery.py` (full file, 8 tests) | PASS |
| `tests/test_needs_operator.py` (full file, 12 tests) | PASS |
| `tests/test_clarify_rounds.py`, `test_multiround_context_edge.py`, `test_combined_context.py`, `test_cr_regressions.py` (31 tests, standing-invariant regression check) | PASS |
| All Phase 11 test files incl. `test_retrigger_epoch.py` (74 tests) | PASS |

### Standing invariants re-confirmed (not re-opened)

- Round cap boundary + escalation-only-write transaction (`test_clarify_rounds.py`) — PASS, unchanged.
- Security V4 server-side roster validation on `/resolve` (`test_needs_operator.py`) — PASS, unchanged (whole-POST rejection, scoped to run's own business).
- D-9-01/D-9-02 ordering (`mark_reply_consumed` before `load_run`, outside any transaction) — traced unchanged at `orchestrator.py:372-374` (line numbers shifted slightly due to the new `_bind_evidence_for_token` helper inserted earlier in the file, but the ordering relationship is intact).
- CLAR2-01 same-run new-round-sends/duplicate-suppress (non-retrigger case) — PASS, unchanged.
- CLAR2-05 multi-round accumulation happy path (`test_multiround_context_edge.py`) — PASS, unchanged.
- Append-only audit log invariant — explicitly re-proven by both `test_retrigger_epoch.py` tests (historical rows physically survive a retrigger, only become epoch-scope-invisible to reads).

### Anti-pattern scan on touched files

`grep -n -E "TBD|FIXME|XXX"` across `app/main.py`, `app/pipeline/orchestrator.py`, `app/db/repo.py`, `app/db/schema.sql`: **zero matches**. No debt markers introduced by the gap-closure plans.

## Requirements Coverage

| Requirement | Gap(s) closed | Status | Evidence |
|-------------|---------------|--------|----------|
| CLAR2-02 | GAP-1/CR-1 | ✓ SATISFIED | `main.py:806-927`, `orchestrator.py:320-387`, `test_needs_operator.py:704-780` |
| CLAR2-07 | GAP-2/CR-2, GAP-3/CR-3 | ✓ SATISFIED | `repo.py:218-251,1004-1037,1150-1152,1237-1277,1297-1322,1360-1396`, `schema.sql:246,265`, `test_retrigger_epoch.py` |
| CLAR2-04 | GAP-4/CR-4, WR-1 | ✓ SATISFIED | `orchestrator.py:108-156,868-904`, `repo.py:840-876`, `test_alias_write.py`, `test_alias_full_loop.py` |
| CLAR2-06 | GAP-5/CR-5 | ✓ SATISFIED | `main.py:463-500,576-597,1302-1342`, `test_reply_redelivery.py` |

All 4 requirement IDs implicated by the 5 confirmed bugs (+ WR-1) are satisfied by traced, running code — not SUMMARY.md narrative.

## Human Verification Required

None. Every gap in `11-REVIEW.md` was closed with a deterministic code-level fix (CAS ownership, epoch scoping, same-record evidence tie, JSONB merge, shared sender predicate) verifiable by direct source trace + a targeted regression test reproducing the exact exploit scenario. No visual/UX/real-time/external-service behavior is implicated in any of the 5 gaps.

## Gaps Summary

None remaining. All 5 CONFIRMED critical bugs from the 2026-07-06 cross-AI review (`11-REVIEW.md`) — CR-1 (operator-resolve double-CAS strand), CR-2 (retrigger stale-row send suppression), CR-3 (retrigger stale-reply mispay), CR-4 (bind-on-inference misroute), CR-5 (redelivery/stranded-sweep spoof bypass) — plus WR-1 (alias-candidates clobber) were traced against the merged source at HEAD `9000e11`, and for each the verifier:

1. Located the exact original defect in the pre-fix code (via the SUMMARY's own diff references and `git show` on the fix commits).
2. Confirmed the merged code structurally closes the defect (CAS ownership consolidated to one caller; epoch-scoping added to all three named readers plus the two writers; bind evidence tied to a single reconciliation record instead of two independent set memberships; JSONB merge replacing a column overwrite; a shared sender-revalidation predicate re-asserted at both re-schedule seams).
3. Re-derived the SPECIFIC exploit scenario from `11-REVIEW.md` against the new code and confirmed the exploit's precondition no longer holds.
4. Located and RAN (not merely cited) the regression test targeting that exact scenario, confirming it drives the REAL seam (not a mock of the broken code) and PASSES.
5. Confirmed the legitimate/happy-path behavior each fix must not break (webhook reply-resume CAS, sender-matching redelivery/stranded-sweep, Jimmy→James full-loop confirmation, misname guard, CLAR2-01/05 non-retrigger happy paths, round cap, Security V4) still passes.

The full offline suite (596 tests) was run twice with byte-identical results, confirming no flakiness and no live-LLM leakage was introduced by any of the 4 gap-closure plans. No regressions were found in any previously-verified invariant.

---

_Verified: 2026-07-06T03:11:41Z (initial, passed) → 2026-07-06 (gaps_found, cross-AI review) → 2026-07-06T21:53:08Z (re-verified, passed — adversarial exploit-trace against merged gap-closure code)_
_Verifier: Claude (gsd-verifier); Re-verification traced every exploit scenario in 11-REVIEW.md directly against source at HEAD 9000e11 and ran (not cited) every targeted regression test._
