---
phase: 02-walking-skeleton
verified: 2026-06-21T22:00:00Z
status: passed
score: 19/19 must-haves verified
overrides_applied: 0
superseded:
  - requirement: "D-A4-01a (Plan 04 Task 3) — live-hero exit gate: real DeepSeek/Kimi returns process + sub-0.8 confidence so the code gate fires"
    superseded_by: "Phase 2.1 (Deterministic Decisioning)"
    reason: "Phase 2.1 (D-21-01) REMOVED confidence-based gating entirely — replaced with deterministic resolution (exact / stored-alias / none) + run-level collision checks. There is no confidence number, no 0.8 threshold, and no model-decides-then-code-gates flow. The original live-hero gate CANNOT pass and is NOT a failure — it was superseded by design. REQUIREMENTS.md LLM-05/LLM-07 already carry the deterministic framing."
re_verification:
  previous_status: none
  note: "Initial verification of Phase 2 goal against the CURRENT code as modified by Phase 2.1."
---

# Phase 2: Walking Skeleton — Verification Report

**Phase Goal:** A messy payroll fixture POSTed to the webhook flows end-to-end through the four pure judgment stages, hits a code-owned gated decision, and pauses/resumes correctly — the first proof the thesis works, with calc deliberately thin (gross + FICA only; net labeled "pre-federal", never a fake federal number).

**Verified:** 2026-06-21T22:00:00Z
**Status:** passed
**Re-verification:** No — initial verification (against current code, post-2.1)

## Supersession Note (READ FIRST)

The original Phase 2 exit checkpoint **D-A4-01a** (Plan 04 Task 3 / "live-hero": a real model returns `process` + sub-0.8 confidence so the code gate fires) is **SUPERSEDED, NOT FAILED.**

Phase 2.1 (Deterministic Decisioning, D-21-01) deliberately removed confidence-based gating entirely. `decide.py` is now pure code over resolution facts — no LLM call, no confidence number, no 0.8 threshold, no `model_action`. The "model-decides-then-code-gates-on-confidence" flow no longer exists. Verified grep-clean: every `confidence` / `model_action` / `gate_triggered` / `0.8` occurrence remaining in `app/` is a comment or docstring documenting the REMOVAL (e.g. `app/llm/client.py:14` "no confidence gate exists; the decision is pure code"; `app/pipeline/suggest.py:53` "Confidence-free by construction"; `app/db/bootstrap.py` `DROP COLUMN ... match_confidence`). No live confidence logic remains.

The CURRENT REQUIREMENTS.md text for LLM-04/05/07/08/09 already carries the deterministic framing (rewritten by 2.1). Phase 2's goal is verified against that current text.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A messy fixture POSTed to the webhook is accepted, returns 200 fast, schedules pipeline as a background task | ✓ VERIFIED | `app/main.py:48` `@app.post("/webhook/inbound")`; `:54` `gateway.parse_inbound`; `:60` `insert_inbound_email` (ON CONFLICT dedupe, FOUND-02); `:103` `background_tasks.add_task(_run_pipeline, run_id)`; returns 200. Test: `test_webhook.py:test_post_fixture_reaches_pause` |
| 2 | The run flows end-to-end through the four pure judgment stages (extract → reconcile → validate → decide) | ✓ VERIFIED | `orchestrator.py:180` `reconcile_names(...)  # pure: no llm`; `:183` `decide(...)  # pure: no llm, no score`; stages present as pure modules `extract.py`, `reconcile_names.py`, `validate.py`, `decide.py`. `reconcile_names` + `decide` are pure (data in, data out, no DB/model) |
| 3 | A code-owned gated decision is hit — deterministic `final_action`, never model-owned | ✓ VERIFIED | `decide.py:86-139` pure function; `:131` `final_action = "request_clarification" if gate_reasons else "process"`. NO LLM call, no score. Orchestrator `:190` "branch SOLELY on final_action". Doc string: "decide() makes NO model call and reads no score" |
| 4 | The gate fires on unresolved name, run-level collision, missing field, AND zero-employee (fail-closed) | ✓ VERIFIED | `decide.py` Rule 0 (empty extraction `:101`), Rule 0b (resolution one-for-one `:111`), Rule 1 (unresolved `:117`), Rule 2 (missing field `:124`), Rule 3 (`check_one_to_one` collisions `:129`). Taxonomy tests: 33 across `test_reconcile.py`/`test_gate.py` (exact/alias/typo/collision/unknown/duplicate/one_to_one) |
| 5 | The resolver never guesses — exact / stored-alias / none, unique across both tiers | ✓ VERIFIED | `reconcile_names.py:37-81` `deterministic_match`: distinct candidate set across full_name AND known_aliases, resolves only if exactly one (`:61`), else None → unresolved (`:84`). Cross-tier collision fix verified (2.1-REVIEW finding 1, fixed + tested) |
| 6 | Run pauses correctly at both states — `awaiting_approval` (process) and `awaiting_reply` (clarify) | ✓ VERIFIED | `orchestrator.py:191-196`: process → COMPUTED → `AWAITING_APPROVAL` (HITL-01); else → clarify branch → `:245` `AWAITING_REPLY` (CLAR-01). `set_status` is sole status writer |
| 7 | A matched client reply resumes the run at extraction with idempotent re-entrancy; late replies logged not resumed | ✓ VERIFIED | `orchestrator.py:88-141` resume re-enters at EXTRACTING (`:141`); `:125` guards `status == AWAITING_REPLY` only, late/duplicate logged + RETURN. Tests: `test_threading.py` `test_idempotent_resume`, `test_late_reply_logged_not_resumed`, `test_resume_on_non_awaiting_reply_run_does_not_mutate`, `test_reply_sender_match_resumes` |
| 8 | Calc is deliberately thin: gross + FICA only; net labeled "pre-federal"; NO fabricated federal number | ✓ VERIFIED | `calculate.py:1` module docstring "gross + FICA only, net labeled pre-federal"; `:123` `federal_withholding = Decimal("0")`; `:124` `net_pay = gross - pretax_401k - fica_ss - fica_medicare`; `:36` `PRE_FEDERAL_NET_LABEL` constant. No fabricated federal figure |
| 9 | The clarification email is specific — a suggestion-only LLM call names the intended employee, never feeds decide | ✓ VERIFIED | `suggest.py:60` `suggest_employees`, cheap tier; `:8` runs ONLY on request_clarification branch STRICTLY AFTER decide; `:98` drops any suggested name not in `valid_full_names` (roster-bound, anti-hallucination `:105-108`); wired into `compose_clarification(suggestions=...)`. Never influences `final_action`. Tests: `test_suggest.py` |
| 10 | EMAIL-01 stub gateway records outbound with synthetic Message-ID; fixture reply injectable | ✓ VERIFIED | Stub gateway path exercised end-to-end with zero real email; `test_gateway.py`, `test_clarify.py:test_clarify_sends_and_pauses`, full clarify→reply→resume loop tested |
| 11 | DEMO-01 fixtures committed + replayable: clean happy path, unknown-shorthand hero, collision-safety | ✓ VERIFIED | `fixtures/clean_happy_path.json`, `fixtures/gate_block_hero.json` (contains "David Reyez" unknown shorthand), `fixtures/collision_safety.json` (contains "D. Reyes" shared alias), `fixtures/clarify_reply.json`. Test: `test_demo_fixtures.py:test_clean_fixture_replays_to_pause_and_approves` |

**Score:** 11/11 observable truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/main.py` | Webhook entrypoint, 200-fast, schedules pipeline | ✓ VERIFIED | POST /webhook/inbound, dedupe, sender-match, background task |
| `app/pipeline/extract.py` | Pure extraction stage (LLM-03) | ✓ VERIFIED | Present; pure importable |
| `app/pipeline/reconcile_names.py` | Pure deterministic resolver (LLM-04, D-21-01) | ✓ VERIFIED | exact/alias/none, cross-tier uniqueness, no model |
| `app/pipeline/validate.py` | Per-field issues list (LLM-06) | ✓ VERIFIED | Present; feeds missing_fields gate |
| `app/pipeline/decide.py` | Pure deterministic decision (LLM-07/09, THE THESIS) | ✓ VERIFIED | Pure code, final_action, 5 gate rules, no LLM/score |
| `app/pipeline/suggest.py` | Suggestion-only call (LLM-05) | ✓ VERIFIED | Cheap tier, roster-bound, never feeds decide |
| `app/pipeline/calculate.py` | Thin gross+FICA, net pre-federal (D-A6-01) | ✓ VERIFIED | federal_withholding=Decimal("0"), labeled |
| `app/pipeline/orchestrator.py` | State machine, two pause points (INGEST-04) | ✓ VERIFIED | Branches on final_action; AWAITING_APPROVAL + AWAITING_REPLY; resume at extraction |
| `app/models/contracts.py` (Decision) | final_action+gate_reasons+unresolved+missing+resolutions; no confidence/model_action | ✓ VERIFIED | 5 kept fields; dead fields removed |
| `app/models/roster.py` (NameMatchResult) | source/resolved; no confidence/match_type; validator | ✓ VERIFIED | source∈{exact,alias,none}, resolved bool, model_validator rejects impossible states |
| `fixtures/*.json` | DEMO-01 canonical fixtures | ✓ VERIFIED | 4 fixtures, substantive, replayable |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| webhook | run_pipeline | `background_tasks.add_task` | ✓ WIRED | `main.py:103` |
| orchestrator | reconcile_names + decide | direct pure calls | ✓ WIRED | `orchestrator.py:180,183` |
| orchestrator branch | pause states | `final_action` → set_status | ✓ WIRED | `:191` process→AWAITING_APPROVAL; `:196,245` clarify→AWAITING_REPLY |
| suggest_employees | compose_clarification | `suggestions=` (after decide) | ✓ WIRED | suggestion never feeds decide; roster-bound drop |
| reply | resume at extraction | header match, awaiting_reply guard | ✓ WIRED | `orchestrator.py:88-141` |
| decide | NOT-wired to any LLM | (intentional absence) | ✓ VERIFIED | No code path from model into final_action |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full mocked suite (Phase 1 + 2 + 2.1) | `uv run pytest -m "not integration and not live_llm" -q` | 204 passed, 12 deselected, 0 failed | ✓ PASS |
| Deterministic taxonomy coverage | grep test names (exact/alias/typo/collision/unknown/duplicate/one_to_one/empty) | 33 taxonomy tests | ✓ PASS |
| Demo fixture replay → pause → approve | `test_demo_fixtures.py` | green | ✓ PASS |
| Resume idempotency + late-reply-not-resumed | `test_threading.py` | green | ✓ PASS |

### Requirements Coverage

| Requirement | Description (current text) | Status | Evidence |
|-------------|---------------------------|--------|----------|
| INGEST-01 | Webhook accepts payload, 200 fast, schedules background task | ✓ SATISFIED | `main.py:48,103` |
| INGEST-02 | Inbound stored with Message-ID/In-Reply-To/References; body cleaned | ✓ SATISFIED | `main.py` ingest; cleaning before extraction |
| INGEST-03 | Sender matched to businesses.contact_email; unknown stopped, never guessed | ✓ SATISFIED | `main.py` sender-match, log+200 no run |
| INGEST-04 | orchestrator.py drives state machine, owns transitions + two pause points | ✓ SATISFIED | `orchestrator.py` set_status sole writer; AWAITING_APPROVAL + AWAITING_REPLY |
| EMAIL-01 | Stub gateway records outbound synthetic Message-ID; injectable reply | ✓ SATISFIED | gateway + clarify/threading tests |
| LLM-01 | OpenAI-compatible client routes per tier from config | ✓ SATISFIED | `llm/client.py` |
| LLM-02 | json_object + Pydantic + one retry; temperature 0 | ✓ SATISFIED | structured-call pattern |
| LLM-03 | Extraction pure importable, per-employee entries + 401k override (run-only) | ✓ SATISFIED | `extract.py`; 401k override threaded (2.1-REVIEW R3 fix) |
| LLM-04 | Deterministic name matching is the WHOLE matcher (exact/alias/none) | ✓ SATISFIED | `reconcile_names.py` (current deterministic text) |
| LLM-05 | No LLM reconciliation/confidence; only suggestion-only call (advisory copy) | ✓ SATISFIED (superseded-then-reframed) | `suggest.py` roster-bound; original confidence wording superseded by 2.1, current text met |
| LLM-06 | Deterministic field validation → per-field issues list | ✓ SATISFIED | `validate.py` |
| LLM-07 | Decisioning deterministic; decide.py code-owned final_action; no model action/score | ✓ SATISFIED (superseded-then-reframed) | `decide.py` pure; original 0.8-gate wording superseded by 2.1, current text met |
| LLM-08 | Deterministic Decision persisted (final_action/gate_reasons/unresolved/missing/resolutions); dead fields removed; no name_matches table | ✓ SATISFIED | Decision contract; JSONB; bootstrap DROPs match_confidence/name_matches |
| LLM-09 | One-to-one roster mapping enforced as pure run-level check in decide.py | ✓ SATISFIED | `decide.py:check_one_to_one` |
| HITL-01 | Computed run pauses at awaiting_approval; operator approve/reject | ✓ SATISFIED | `orchestrator.py:195`; `main.py` approve/reject; `test_hitl.py` |
| CLAR-01 | request_clarification → LLM drafts + auto-send; Message-ID stored; awaiting_reply | ✓ SATISFIED | clarify branch `:196-245` |
| CLAR-02 | Reply routed via In-Reply-To/References chain | ✓ SATISFIED | `test_threading.py` |
| CLAR-03 | Matched reply re-enters at extraction, idempotent; only awaiting_reply runs; late reply logged | ✓ SATISFIED | resume `:88-141`; threading tests |
| DEMO-01 | Canonical fixtures replayable: clean + unknown-shorthand hero + collision-safety | ✓ SATISFIED | 4 fixtures; reframed per 2.1 (learning beat deferred to P5) |

**19/19 phase requirements satisfied** (LLM-05/LLM-07 satisfied against current deterministic text; original confidence wording superseded by Phase 2.1).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | TBD/FIXME/XXX scan of `app/**/*.py` | — | NONE found — clean |

`confidence` / `model_action` / `gate_triggered` / `0.8` grep matches in `app/` are all comments/docstrings documenting the REMOVAL of the confidence gate (intentional, legible), not live logic — not anti-patterns.

### Superseded (NOT gaps)

| Item | Original Intent | Superseded By | Why Not a Gap |
|------|-----------------|---------------|---------------|
| D-A4-01a (Plan 04 Task 3) live-hero exit gate | Real model returns `process` + sub-0.8 confidence → code gate fires | Phase 2.1 (D-21-01) | Confidence gating removed by design; the flow no longer exists. `process + sub-0.8` was never a real well-calibrated-model state (it required a rigged 0.75 hardcode). The deterministic resolver + run-level collision checks deliver the same thesis ("never guesses on a money-moving decision") more strongly. Verified grep-clean. |
| LLM-05 / LLM-07 (original confidence wording) | LLM proposes process/clarify + confidence; decide gates on 0.8 | Phase 2.1 | REQUIREMENTS.md already rewritten to deterministic framing; current text verified met. |

### Human Verification Required

None. All Phase 2 truths are verifiable programmatically against the codebase + the 204-test mocked suite. (Live-LLM behavior — the original D-A4-01a concern — is superseded; the deterministic decision needs no live model to verify the gate.)

### Gaps Summary

No gaps. Phase 2's goal is fully achieved by the current deterministic code (as modified by Phase 2.1):

- A messy fixture POSTed to `/webhook/inbound` flows end-to-end through the four pure judgment stages (extract → reconcile → validate → decide).
- The decision is **code-owned and deterministic** (`decide.py`, no LLM, no confidence) — the thesis is delivered more robustly than the original confidence gate.
- Both pause states (`awaiting_approval`, `awaiting_reply`) and the resume-at-extraction path (with late-reply / idempotency guards) work.
- Calc is deliberately thin: gross + FICA only, `federal_withholding=Decimal("0")`, net labeled "pre-federal" — no fabricated federal number.
- DEMO-01 fixtures are committed and replayable; the unknown-shorthand hero + collision-safety beats are present.

The only item that "did not pass" is the **D-A4-01a confidence-based live-hero gate, which was SUPERSEDED by Phase 2.1, not failed.** Phase 2.1's own 3-round Codex review verdict is CLEAN (all findings fixed, 204 passed).

---

_Verified: 2026-06-21T22:00:00Z_
_Verifier: Claude (gsd-verifier)_
