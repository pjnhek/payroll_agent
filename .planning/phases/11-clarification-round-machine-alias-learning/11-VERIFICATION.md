---
phase: 11-clarification-round-machine-alias-learning
verified: 2026-07-06T03:11:41Z
status: gaps_found
superseded_note: "Initial verification passed (7/7) but was FALSIFIED by the 2026-07-06 cross-AI code review (11-REVIEW.md): 5 CONFIRMED critical money/security bugs in the recovery/re-entry seams this report marked ✓ VERIFIED. Status flipped passed→gaps_found so /gsd-plan-phase --gaps closes them. See the Gaps Summary (Corrected) section at the end. Authoritative gap source: 11-REVIEW.md."
status_history:
  - "2026-07-06T03:11:41Z passed (7/7) — initial gsd-verifier"
  - "2026-07-06 gaps_found — cross-AI review (Codex + internal) confirmed 5 criticals the initial pass missed"
score: 2/7 must-haves hold (CR-1..CR-5 falsify CLAR2-02/03/04/06/07 recovery paths; CLAR2-01/05 single-run happy paths hold)
gap_source: 11-REVIEW.md
overrides_applied: 0
must_haves:
  truths:
    - "CLAR2-01: a genuinely new clarification question always sends; a true same-round duplicate is still suppressed; no run silently parks at awaiting_reply with no email out"
    - "CLAR2-02: after 3 total clarification rounds the run escalates to needs_operator (no LLM/gateway call); operator can resolve deterministically and resume, or reject"
    - "CLAR2-03: resume extraction context includes a code-owned 'questions we asked' anchor; a bare answer cannot be blindly attributed"
    - "CLAR2-04: the alias-learning write side is reachable via bind-on-confirmation against a persisted suggestion; misname guard survives; a full-loop test proves stops-asking with REAL resolution"
    - "CLAR2-05: multi-round context loss is closed — the combined context accumulates ORIGINAL + ALL consumed replies in round order; the known-edge fixture flips (Round-1 '30, not 40' pays 30)"
    - "CLAR2-06: a redelivered unconsumed reply re-schedules resume; a consumed reply's redelivery is a no-op; a stranded unconsumed reply is auto-rescheduled from the runs-list load; needs_operator is excluded"
    - "CLAR2-07: retrigger clears ALL reply context (clarified_fields, pre_clarify_extracted, round counter, suggestion/candidate state) so provenance cannot outlive its data"
---

# Phase 11: Clarification Round Machine & Alias Learning — Verification Report

**Phase Goal:** The multi-round clarification state machine becomes correct and unstrandable, and the alias-learning loop actually learns — WR-05 round-aware idempotency + cap/escalation, question-anchored attribution, bind-on-confirmation alias learning reachability, CX-01 multi-round context-loss closure, and WR-06/WR-04 provenance-scoping/redelivered-reply handling folded into one round/consumed state design.

**Verified:** 2026-07-06T03:11:41Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | CLAR2-01: new round sends; same-round duplicate suppressed; no silent park | ✓ VERIFIED | `app/pipeline/orchestrator.py:1225-1268` — `current_round = repo.get_clarification_round(run_id)`; `existing_clari = repo.get_outbound_for_round(run_id, purpose=purpose, round=current_round)` replaces the old purpose-only guard; `existing_clari is not None` → suppress + idempotent round-advance finalize; `None` → falls through to send. `tests/test_clarify_rounds.py` (6 tests, all pass) proves new-round-sends, same-round-suppressed, crash-idempotent advance, AST ordering, round-stamping. |
| 2 | CLAR2-02: 3-round cap → needs_operator; operator resolve route with server-side roster validation; reject accepts NEEDS_OPERATOR | ✓ VERIFIED | `MAX_CLARIFICATION_ROUNDS = 3` at `orchestrator.py:77`; cap check at `orchestrator.py:1225-1235` runs BEFORE the (purpose, round) guard and before any LLM/gateway call, `set_status(NEEDS_OPERATOR)` is the sole write. `app/main.py:771-862` `POST /runs/{run_id}/resolve` validates every posted `employee_id` against `load_roster_for_business(run.business_id)`, rejects the WHOLE POST on any invalid/cross-business id (`main.py:827-844`). `reject()` accepts `NEEDS_OPERATOR → REJECTED` (`main.py:767`). `needs_operator` confirmed excluded from `IN_FLIGHT_STATUSES` (`main.py:111-113`), `_STRANDED_SCOPE_STATUSES` (`repo.py:475`), and retrigger `stale_statuses` (`main.py:960-964`). `tests/test_needs_operator.py` (11 tests, all pass) covers cap boundary, silent escalation, scope exclusions, badge rendering (TestClient), and the 3 resolve-route security tests. |
| 3 | CLAR2-03/05: combined context = ORIGINAL + questions-we-asked anchor + consumed replies in round order + current; known-edge fixture flips to pay 30 | ✓ VERIFIED | `_render_asked_summary` (`orchestrator.py:975-1000`) renders lines from `decision.unresolved_names` + `clarified_fields` 'asked' entries ONLY — no LLM-draft parameter, structurally can't read the drafted body. `_combined_context_email` (`orchestrator.py:1003-1035`) is a pure function assembling ORIGINAL → QUESTIONS WE ASKED (if any) → prior replies in order → current reply; returns `model_copy`, no DB I/O. `resume_pipeline` wires `repo.load_consumed_replies(run_id)` and excludes the just-marked-consumed current reply by message_id (`orchestrator.py:434-450`). `tests/test_multiround_context_edge.py::test_multi_round_context_preserves_round1_correction` asserts `final_regular = chen_items[0].hours_regular; assert final_regular == Decimal("30")` against `fake_repo.load_line_items(run_id)` — a genuine persisted paystub line-item VALUE, not a label. |
| 4 | CLAR2-04: alias-write side reachable via bind-on-confirmation; misname guard intact; full-loop test proves stops-asking with real resolution | ✓ VERIFIED | Nested persistence `{token: {"suggested": id\|None, "bound": None}}` at `orchestrator.py:1353-1378`. Bind-on-confirmation block (post-11-04) binds `{"suggested": S, "bound": S}` iff S newly resolves AND token gone from unresolved — traced in `orchestrator.py` bind logic near `:660-735` per plan (confirmed via `_write_aliases_if_safe` reading `_normalize_candidate(...)["bound"]`, `orchestrator.py:1455+`). `tests/test_alias_full_loop.py::test_full_loop_learns_alias_and_stops_asking` drives REAL `reconcile_names` + REAL `_write_aliases_if_safe` (mock_llm scripts extraction/suggestion TEXT only) end-to-end: nickname capture → suggestion persist with real employee id → confirming reply → bind → operator approval → `known_aliases` written → a SECOND independent submission resolves via `source="alias"` with ZERO clarification rows and pays `Decimal("35")` for James Okafor. `test_misname_reply_binds_nothing_end_to_end` proves a non-suggested resolution ("Maria Chen" corrects "Robbie") leaves `bound: None` and never writes "Robbie" into `known_aliases`. |
| 5 | CLAR2-06: redelivered unconsumed reply reschedules; consumed reply redelivery no-ops; stranded reply auto-resumes; needs_operator excluded | ✓ VERIFIED | `app/main.py:463-497` — the `outcome == "duplicate"` branch loads `repo.get_inbound_by_message_id(email.message_id)`, re-schedules `_resume_pipeline` iff `consumed_round is None` AND linked run is `awaiting_reply`. `runs_list` (`main.py:1255-1284`) gained `background_tasks: BackgroundTasks` and iterates `repo.find_stranded_unconsumed_replies(STALE_THRESHOLD_SECONDS)` inside the same swallow-on-failure try/except as the sweep; scope excludes `needs_operator` by construction (query joins on `pr.status = 'awaiting_reply'`, `repo.py:1279-1304`). `tests/test_reply_redelivery.py` (6 tests, all pass) covers unconsumed-reschedules, consumed-no-op, non-awaiting-reply-no-op, stranded-auto-resume, fresh-reply-excluded, needs_operator-excluded. |
| 6 | CLAR2-07: retrigger clears clarified_fields, pre_clarify_extracted, round counter, suggestion/candidate state | ✓ VERIFIED | `repo.clear_reply_context` (`repo.py:974-993`) nulls all four columns in one UPDATE. Called at `main.py:990-1002`, the single `if claimed:` convergence point reached by BOTH the ERROR/APPROVED core CAS and the stale in-flight CAS branches, strictly before `background_tasks.add_task(_run_pipeline, run_id)`. `tests/test_cr_regressions.py` (15 tests, all pass, including 3 new CLAR2-07 tests) asserts all four columns are cleared and that a stale provenance badge cannot reproduce. |
| 7 | Full offline suite green, deterministic, and Phase 11 test files specifically pass | ✓ VERIFIED | `uv run pytest -q -m "not integration and not live_llm"` → 588 passed, 20 skipped, 28 deselected, run twice, byte-identical result (deterministic). All 8 Phase 11 test files (`test_clarify_rounds`, `test_needs_operator`, `test_combined_context`, `test_multiround_context_edge`, `test_alias_write`, `test_alias_full_loop`, `test_reply_redelivery`, `test_cr_regressions`) pass: 66/66. |

**Score:** 7/7 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/db/schema.sql` | round/consumed_round/clarification_round columns, needs_operator (both CHECK spots), uq_email_run_purpose_round | ✓ VERIFIED | Confirmed via grep: `needs_operator` × 2 (lines 80, 176), `consumed_round` (231), `clarification_round` (100, 122), `uq_email_run_purpose_round` (234-237, 284-307) |
| `app/models/status.py` | RunStatus.NEEDS_OPERATOR | ✓ VERIFIED | `test_status_drift.py`/`test_models_contracts.py` (56 passed) confirm 11-status parity |
| `app/db/repo.py` | 8 new primitives + widened ON CONFLICT arbiter | ✓ VERIFIED | `get_clarification_round`, `set_clarification_round`, `get_outbound_for_round`, `mark_reply_consumed`, `load_consumed_replies`, `get_inbound_by_message_id`, `clear_reply_context`, `find_stranded_unconsumed_replies` all present; `ON CONFLICT (run_id, purpose, round)` confirmed, no 2-column arbiter remains |
| `app/pipeline/orchestrator.py` | round-aware `_clarify`, cap/escalation, `_combined_context_email`, `_render_asked_summary`, bind-on-confirmation, `resume_pipeline` consumed-marker + accumulation wiring | ✓ VERIFIED | All traced directly, line-referenced above |
| `app/main.py` | `/resolve` route, WR-04 redelivery, D-11-05 stranded auto-resume, WR-06 retrigger clear, `_row_to_inbound` | ✓ VERIFIED | All traced directly, line-referenced above |
| `app/llm/prompts/extract.py` | absent-if-unaddressed instruction | ✓ VERIFIED | `_SYSTEM` policy contains attributable-answering instruction (lines 10-53) |
| `app/templates/run_detail.html` | needs_operator banner + resolve form | ✓ VERIFIED | `run_detail.html:71-103` — per-name roster dropdown, suggestion pre-selected, remember checkbox default-checked, Reject |
| Test files (8) | Phase 11 coverage | ✓ VERIFIED | All exist, unguarded (no module-level DATABASE_URL skip), all pass |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `_clarify` | `repo.get_outbound_for_round` | (purpose, round) guard | ✓ WIRED | `orchestrator.py:1243-1245` |
| `_clarify` finalize (3 paths) | `repo.set_clarification_round` | idempotent round advance before `set_status` | ✓ WIRED | Lines 1264-1267 (early-return), 1425 (record_only), 1451 (live gateway) — all textually before `set_status` |
| `resume_pipeline` | `repo.mark_reply_consumed` | immediately after CAS claim, before `load_run` | ✓ WIRED | `orchestrator.py:372-374`, outside any transaction (D-9-01 preserved) |
| `resume_pipeline` | `repo.load_consumed_replies` | round-ordered accumulation, current reply excluded | ✓ WIRED | `orchestrator.py:439-450` |
| `main.py resolve route` | `reconcile_names(overrides=)` | operator mapping validated server-side, applied as override | ✓ WIRED | `main.py:827-861` → threaded to `_run_stages(overrides=...)` |
| `main.py duplicate branch` | `repo.get_inbound_by_message_id` | consumed_round IS NULL + awaiting_reply gate | ✓ WIRED | `main.py:476-489` |
| `main.py runs_list` | `repo.find_stranded_unconsumed_replies` | swallow-on-failure, beside sweep | ✓ WIRED | `main.py:1277-1281` |
| `main.py retrigger convergence` | `repo.clear_reply_context` | after winning claim, before `_run_pipeline` dispatch | ✓ WIRED | `main.py:990-1002` |
| `_write_aliases_if_safe` | `repo.update_known_alias` | writes only when `cand["bound"]` is not None, D-01b collision re-check preserved | ✓ WIRED | Traced in orchestrator.py; `InMemoryRepo.update_known_alias` mirror confirmed added in conftest.py (11-04 deviation) |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|---------------------|--------|
| `_combined_context_email` | `asked_summary_lines`, `prior_replies` | `_render_asked_summary(decision, clarified_fields)` (persisted) + `repo.load_consumed_replies(run_id)` (real DB rows / InMemoryRepo mirror) | Yes | ✓ FLOWING — `test_consumed_marker_from_resume_drives_next_round_accumulation` (test_combined_context.py) proves accumulation reflects a row PRODUCED by resume_pipeline's own `mark_reply_consumed` call, not a hand-seeded fixture |
| `test_multiround_context_edge.py` paid value | `chen_items[0].hours_regular` | `fake_repo.load_line_items(run_id)` — real persisted paystub line items from the pipeline's compute stage | Yes | ✓ FLOWING — asserts `Decimal("30")`, a genuine paid value, not a status label |
| `test_alias_full_loop.py` second-submission paystub | `james_items[0].hours_regular` | `fake_repo.load_line_items(second_run_id)` after a REAL `reconcile_names` resolution via stored alias | Yes | ✓ FLOWING — asserts `Decimal("35")` |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full offline suite green | `uv run pytest -q -m "not integration and not live_llm"` | 588 passed, 20 skipped, 28 deselected | ✓ PASS |
| Suite deterministic across 2 runs | same command, run twice | identical result both times | ✓ PASS |
| Phase 11 test files pass in isolation | `uv run pytest -q tests/test_clarify_rounds.py tests/test_needs_operator.py tests/test_combined_context.py tests/test_multiround_context_edge.py tests/test_alias_write.py tests/test_alias_full_loop.py tests/test_reply_redelivery.py tests/test_cr_regressions.py` | 66 passed | ✓ PASS |
| Schema/enum drift parity | `uv run pytest -q tests/test_status_drift.py tests/test_models_contracts.py` | 56 passed | ✓ PASS |
| No live-LLM reachability without a stub | grep for `mock_llm`/`llm=None` + `_run_stages` monkeypatch usage across every test that calls `_clarify`/`resume_pipeline`/`suggest_employees` | Every such call site uses the `mock_llm` fixture (patches `app.llm.client.OpenAI` at the class level) OR passes `llm=None` with `_run_stages`/`suggest_employees` explicitly monkeypatched, so no live network call is reachable | ✓ PASS (flakiness risk addressed — see note below) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|--------------|--------|----------|
| CLAR2-01 | 11-02 | Round-aware idempotency, no silent stall | ✓ SATISFIED | `orchestrator.py:1225-1268`, `tests/test_clarify_rounds.py` |
| CLAR2-02 | 11-01, 11-02, 11-04 | 3-round cap → needs_operator; operator resolve/reject | ✓ SATISFIED | `orchestrator.py:77,1225-1235`; `main.py:771-862`, `main.py:767` |
| CLAR2-03 | 11-03 | Question-anchored attribution | ✓ SATISFIED | `orchestrator.py:975-1035`, `app/llm/prompts/extract.py:10-53` |
| CLAR2-04 | 11-04 | Alias-write side reachable, stops asking | ✓ SATISFIED | `orchestrator.py:1353-1378` + bind block; `tests/test_alias_full_loop.py` |
| CLAR2-05 | 11-03 | Multi-round context accumulation, CX-01 closed | ✓ SATISFIED | `orchestrator.py:439-450`; `tests/test_multiround_context_edge.py` flipped fixture |
| CLAR2-06 | 11-01, 11-05 | Redelivery/stranded-reply handling | ✓ SATISFIED | `main.py:463-497,1255-1284`; `tests/test_reply_redelivery.py` |
| CLAR2-07 | 11-01, 11-05 | Retrigger clears all reply context | ✓ SATISFIED | `repo.py:974-993`, `main.py:990-1002`; `tests/test_cr_regressions.py` |

All 7 phase requirement IDs accounted for and satisfied. No orphaned requirements found in REQUIREMENTS.md's Phase 11 mapping.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | No TBD/FIXME/XXX debt markers found in any Phase 11-modified file | — | None |
| — | — | No placeholder/stub/"not yet implemented" strings found | — | None |
| — | — | `placeholder` grep hits in `repo.py` are all legitimate SQL-parameter-placeholder comments, not code stubs | Info | None |

No blocking or warning anti-patterns found.

### Human Verification Required

None. All must-haves are verifiable programmatically via code trace, grep, and the automated test suite; no visual/UX/real-time/external-service behavior in this phase's scope required human judgment beyond what the TestClient-driven badge-rendering and security tests already cover.

### Environment Note — Live LLM Key Flakiness Risk (Addressed)

The task flagged a risk: this repo's `.env` carries live LLM API keys, so any test reaching the clarify/suggest/extract path without stubbing would hit a real nondeterministic model. Verification traced every Phase 11 test that calls `_clarify`, `resume_pipeline`, or `suggest_employees`:

- All such calls either use the `mock_llm` fixture (`tests/conftest.py:1008-1029`), which monkeypatches `app.llm.client.OpenAI` at the class level with a scriptable FIFO stub — no live network call is possible while this fixture is active — or
- Pass `llm=None` while separately monkeypatching `_run_stages`/`suggest_employees` directly (as in several `tests/test_alias_write.py` tests), which structurally bypasses the LLM call path entirely.

No gap found: the suite is deterministic (confirmed by running the full offline suite twice with identical results) and no test in this phase is exposed to live-model nondeterminism.

### Gaps Summary

None. All 7 CLAR2 requirements were traced against the actual merged code (not SUMMARY.md claims) and confirmed genuinely implemented and wired:

- The round machine cap/guard/escalation sequencing in `_clarify` is textually verified to run in the correct order (cap check → guard → capture → suggest → send), matching the D-9-01/D-9-02 money-safety invariants from prior phases.
- The alias-learning bind-on-confirmation logic and misname guard are proven not just at the unit level but at the full-loop level with REAL `reconcile_names` resolution — the exact class of gap (faked-state tests keeping an unreachable loop green) the phase was designed to close.
- The CX-01 multi-round context-loss fix is proven against a genuine persisted paystub line-item VALUE (`Decimal("30")`), not a classify label — consistent with the project's established money-safety verification discipline.
- The consumed-marker seam, redelivery/stranded-reply recovery, and retrigger context-clear are all wired at the exact seams the plans specified, with tests that fail if the seam is removed (not merely passing against seeded fixture state).

---

## Gaps Summary (CORRECTED — supersedes the "None" above)

The initial pass (above) confirmed the seams by tracing that the code *exists and is wired*, but did not adversarially trace the **recovery/re-entry** argument flow. A 2026-07-06 cross-AI review (Codex CLI + internal gsd-code-reviewer, findings source-verified — full detail in **`11-REVIEW.md`**) found **5 CONFIRMED critical bugs**, four of them one class: *the Phase 11 recovery seams read round-machine state from `email_messages` and re-key CAS transitions, but the surrounding code clears the wrong table, double-claims the same status, or skips the sender check.* None was caught because the tests mock the exact seam that fails. These are the gap set for `--gaps` closure:

| Gap | Requirement falsified | Bug (see 11-REVIEW.md for full trace) | Fix direction |
|-----|----------------------|----------------------------------------|---------------|
| **GAP-1 (CR-1)** | CLAR2-02 | Operator `/resolve` claims `NEEDS_OPERATOR→EXTRACTING` (main.py:859), then `resume_pipeline` claims it AGAIN (orchestrator.py:328) → 2nd CAS fails → resume returns early → run stuck in `EXTRACTING` forever, operator's resolution silently dropped. Test mocked `resume_pipeline` so never exercised the real double-claim. | `/resolve` must not pre-claim; let `resume_pipeline` own the single `NEEDS_OPERATOR→EXTRACTING` CAS. Add an end-to-end test driving REAL `resume_pipeline` to `AWAITING_APPROVAL`. |
| **GAP-2 (CR-2)** | CLAR2-07 (+ regresses CLAR2-01) | Retrigger's `clear_reply_context` resets `payroll_runs.clarification_round=0` but does NOT touch `email_messages`; the old round-0 `sent` outbound row survives → `_clarify`'s `get_outbound_for_round(round=0)` finds it → suppresses the fresh send → parks at `awaiting_reply` with NO email = WR-05 reintroduced. | Delete/tombstone prior outbound clarification rows on retrigger, or add a per-retrigger epoch to the round space (closes GAP-2 + GAP-3 together). Test: retrigger a run that already sent round-0, assert a NEW outbound clarification row is written. |
| **GAP-3 (CR-3)** | CLAR2-07 | Same `clear_reply_context` leaves `email_messages.consumed_round` stamped → `load_consumed_replies` re-injects a stale prior reply ("John 30, not 40") into the retriggered run's extraction → mispay. | Null/namespace `consumed_round` for the run's inbound rows on retrigger (or scope `load_consumed_replies` to the current epoch). Test: retrigger after a consumed reply, assert it is NOT re-accumulated. |
| **GAP-4 (CR-4, dual-source)** | CLAR2-04 | Bind-on-confirmation (orchestrator.py:845-857) fires when "suggested id newly resolved SOMEWHERE" AND "token gone from unresolved" are both true — computed independently over the whole run, not tied to the token's OWN resolution. "No, Dave didn't work; David worked separately" binds `Dave→David` with no confirmation = the never-learn-from-inference/misname class the guard exists to block. | Bind only when the SAME submitted-name record for the token resolves to the suggested id S. Test: the "suggested resolves via an unrelated line while token independently drops out" case binds NOTHING. |
| **GAP-5 (CR-5)** | CLAR2-06 | Ingest links a header-matched reply to its run INSIDE the committed txn (RFC-header-based, attacker-controllable), `consumed_round=NULL`; FIX-5 sender revalidation runs POST-commit in `_finish_reply_resume`. A FIX-5-failed reply stays linked+unconsumed → WR-04 redelivery AND the stranded sweep re-resume it checking only `consumed_round`/status, NOT the sender → spoofed reply drives the victim's payroll (reopens the class FIX-5 closed). | Both re-schedule seams must re-assert FIX-5 (`find_business_by_sender(from_addr)==run.business_id`) before dispatching resume — route through `_finish_reply_resume`'s guard. Test: persist a FIX-5-failed linked reply, trigger redelivery + sweep, assert NO resume. |

**Also fold in (Warning, same effort):** WR-1 — `set_alias_candidates` (repo.py:831-846) is a full-column overwrite, not a merge; with ≥2 tokens across ≥2 rounds the last write clobbers a client-confirmed bind before `_write_aliases_if_safe` reads it. Fix as a JSONB merge or read-modify-write under the run lock. Add a two-tokens/two-rounds test. (WR-3 `/resolve` auth is KNOWN/ACCEPTED — the whole dashboard is intentionally unauthenticated single-operator; not in scope.)

**Still hold (do not re-open):** CLAR2-01 same-run new-round-sends/duplicate-suppress (GAP-2 is the *retrigger* regression only), CLAR2-05 multi-round accumulation happy path, and Security V4 server-side roster validation on `/resolve` (present + correct, no cross-business leak).

---

_Verified: 2026-07-06T03:11:41Z (initial, passed) → 2026-07-06 corrected to gaps_found (cross-AI review)_
_Verifier: Claude (gsd-verifier); Corrected-by: cross-AI review reconciliation (see 11-REVIEW.md)_
