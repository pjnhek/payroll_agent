---
phase: 02-walking-skeleton
plan: 03
subsystem: pipeline
tags: [llm-reconciliation, code-gate, clarification-email, message-id-threading, demo-fixture, pydantic, json-mode]

# Dependency graph
requires:
  - phase: 02-walking-skeleton (Plan 01)
    provides: "The one LLM client (call_structured JSON-mode + reflective retry, call_text free-text draft path), the stub EmailGateway (send_outbound minting a synthetic Message-ID on an outbound email_messages row), the FULL repo surface (set_status sole writer, persist_reconciliation, insert_email_message, get_outbound_message_id, the header-chain lookups)"
  - phase: 02-walking-skeleton (Plan 02)
    provides: "The four pure stages + the code gate (decide.py with the empty-but-real check_one_to_one + per-name Decimal('0.8') test), reconcile_names layer-1, the orchestrator state machine (persists Extracted+Decision+reconciliation on EVERY run, branches SOLELY on final_action), the in-memory fake_repo + scriptable mock_llm conftest, the clean_happy_path fixture + demo replay"
provides:
  - "Layer-2 LLM name reconciliation: ONLY residual (failed-deterministic) names reach the model via the NameReconciliationResponse{matches: list[NameMatchResult]} wrapper (FIX 6 — call_structured validates via model_validate_json, which a bare list cannot satisfy); unwraps .matches; merges with layer-1 (one per submitted name); a layer-1 hit is NEVER re-decided (LLM-05); DB-free (FIX A)"
  - "check_one_to_one EXTENDED (signature unchanged from Plan 02) into full one-to-one mapping enforcement: two names→one employee / duplicate submitted name / name→no employee each gate to clarify even with a confident model (LLM-09, D-A3-02); the high-confidence collision still gates (G6)"
  - "compose_email.py: compose_clarification(decision, *, llm) via the cheap DRAFT_* call_text free-text path (NOT json mode, no schema retry); templated fallback on empty content so a draft failure never strands the run (CLAR-01)"
  - "The orchestrator request_clarification branch: draft → gateway.send_outbound (Message-ID anchored on email_messages(direction='outbound', run_id), threaded off the inbound In-Reply-To/References — the SINGLE FIX-3 anchor, NO payroll_runs column) → set_status(AWAITING_REPLY) (sole writer, FIX B); persist_reconciliation reached by BOTH branches (grep -c == 1, D-A3-05)"
  - "fixtures/gate_block_hero.json: David Reyez (y→z typo of seeded David Reyes) replays end-to-end on TWO distinct mocks → final_action==request_clarification WHILE model_action==process → awaiting_reply (the 'model was willing; code said no' money shot on mocks; the live proof is Plan 04)"
affects: [02-04, walking-skeleton, pipeline, orchestrator, eval, dashboard]

# Tech tracking
tech-stack:
  added: []  # no new packages — reuses Plan 01/02 deps; no install task (T-03-SC)
  patterns:
    - "Layer ordering as a residual filter: layer-1 deterministic hits are computed FIRST and excluded from the model prompt; only residuals (kept in submitted order) reach layer-2, then both merge back one-per-submitted-name — the model can never re-decide a clean hit (LLM-05, D-A3-01)"
    - "Structured-output wrapper for a list response: a bare list[Model] has no model_validate_json, so the layer-2 schema is a one-field BaseModel (NameReconciliationResponse{matches}) that the stage unwraps — the FIX-6 pattern for any list-shaped LLM output"
    - "The clarify branch is a pure compose (Decision→str, DB-free) + an orchestrator-owned send + set_status; the draft has a deterministic templated floor so an empty model body still pauses the run cleanly"
    - "Two structurally-distinct LLM surfaces (layer-2 reconcile vs decision-advisory) are separate call_structured invocations, so the FIFO mock_llm script feeds DIFFERENT responses per call (extract → reconcile → decide → draft) — the override test asserts BOTH model_action and final_action"

key-files:
  created:
    - app/models/reconcile.py
    - app/llm/prompts/reconcile.py
    - app/llm/prompts/clarify.py
    - app/pipeline/compose_email.py
    - fixtures/gate_block_hero.json
    - tests/test_clarify.py
  modified:
    - app/pipeline/reconcile_names.py
    - app/pipeline/decide.py
    - app/pipeline/orchestrator.py
    - tests/conftest.py
    - tests/test_reconcile.py
    - tests/test_gate.py
    - tests/test_orchestrator_states.py
    - tests/test_demo_fixtures.py

key-decisions:
  - "Layer-2 residual-only call defaults llm=client module (not the orchestrator's run-level llm kwarg) so the webhook path — run_pipeline(run_id) with no llm — still routes reconcile through the patched OpenAI in mocked E2E tests; the clean fixture (all-deterministic) makes NO layer-2 call, so its 2-entry FIFO script is unchanged."
  - "compose_clarification stays pure (Decision→str, no DB); the orchestrator owns gateway.send_outbound + set_status. The clarification threads off the inbound message_id (In-Reply-To + References) so Plan 04's header-chain reply match resolves to this run."
  - "The gated-branch outbound is exercised fully offline by adding insert_email_message + get_outbound_message_id to the conftest InMemoryRepo — the real gateway.send_outbound runs against the in-memory store, so no test needs a live DB to prove the Message-ID anchor (FIX 3)."

patterns-established:
  - "Residual-filter reconciliation: deterministic-first, model-only-on-residuals, merge one-per-name in submitted order."
  - "List-shaped structured output via a one-field BaseModel wrapper the stage unwraps (model_validate_json requires a BaseModel — FIX 6)."
  - "The gate-block money-shot test shape: TWO distinct mocks (reconcile llm_typo→real employee @ sub-0.8 + decision process) asserting final_action==request_clarification WHILE model_action==process."

requirements-completed: [LLM-05, LLM-09, CLAR-01, DEMO-01]

# Metrics
duration: 24min
completed: 2026-06-21
---

# Phase 2 Plan 03: Gate-Block Slice (b) Summary

**Slice (b), the gate-block case: layer-2 LLM reconciliation (residual-only, via the NameReconciliationResponse wrapper) + the EXTENDED one-to-one mapping gate (LLM-09) + the clarification draft+send loop into awaiting_reply — proven end-to-end by the David Reyez hero fixture where the code gate OVERRIDES a willing model (model_action=process) into request_clarification on a sub-0.8 typo match. The "model was willing; code said no" money shot, on mocks; the live proof is Plan 04.**

## Performance

- **Duration:** ~24 min
- **Started:** 2026-06-21
- **Completed:** 2026-06-21
- **Tasks:** 3 (all TDD: RED → GREEN)
- **Files modified:** 14 (6 created, 8 modified)

## Accomplishments
- **Layer-2 LLM reconciliation, residual-only (LLM-05):** `reconcile_names` now resolves deterministically first, sends ONLY the residual names to the model with the FULL roster in-context, validates the untrusted output through the new `NameReconciliationResponse{matches: list[NameMatchResult]}` wrapper (FIX 6 — `call_structured` validates via `model_validate_json`, which a bare `list` cannot satisfy), unwraps `.matches`, and merges back one-per-submitted-name in order. A layer-1 hit is never re-decided by the model; the stage stays DB-free (FIX A — `grep -L` purity guard lists both reconcile + decide, and `test_reconcile_is_db_free` passes).
- **The one-to-one mapping gate, EXTENDED not rewritten (LLM-09):** `check_one_to_one` keeps its Plan-02 signature (`test_check_one_to_one_stub_shape` still passes) and is now full enforcement — two names→one employee, a duplicate submitted name, and a name→no employee each become a distinct `gate_reason`. A high-confidence collision STILL gates (`test_high_confidence_collision_still_gates`, G6): the mapping gate is independent of confidence, so a confident model can never let a name silently collapse onto another (T-03-02).
- **Clarification draft+send into awaiting_reply (CLAR-01):** `compose_clarification` drafts via the cheap DRAFT_* `call_text` free-text path (NOT json mode, no schema retry) with a deterministic templated fallback on empty content (a draft failure never strands the run); the orchestrator's `request_clarification` branch sends it via `gateway.send_outbound` (synthetic Message-ID anchored on the outbound `email_messages` row, threaded off the inbound In-Reply-To/References — the single FIX-3 anchor, NO `payroll_runs` column) and pauses at AWAITING_REPLY via `repo.set_status` (sole writer, FIX B). The SAME `persist_reconciliation` call (Plan 02) covers both branches (`grep -c == 1`, D-A3-05).
- **The David Reyez hero fixture replays the override end-to-end (DEMO-01 gate-block half):** `fixtures/gate_block_hero.json` (David Reyez, y→z typo of seeded David Reyes, from `hr@metrodeli.example`, explicit 38 hours so the ONLY trigger is the sub-0.8 name) POSTs through the webhook and, driven by TWO structurally-distinct mocks (reconcile → `llm_typo` → David Reyes's seeded id @ `0.6`; decision → `model_action=process`), produces `final_action=="request_clarification"` WHILE `model_action=="process"` (the override asserted on BOTH fields) and reaches `awaiting_reply`. Both fixtures (clean + gate-block) replay via POST.
- **Mocked suite green: 145 passed, 11 deselected** (up from 129; +16 new tests, no regressions). The live-DB integration round-trips skip without creds, as designed.

## Task Commits

Each task was committed atomically (all TDD — the RED test was authored, run-to-fail, then driven GREEN within the same task):

1. **Task 1: Layer-2 LLM reconcile (NameReconciliationResponse wrapper) + EXTEND check_one_to_one one-to-one gate** — `6a64135` (feat)
2. **Task 2: Clarification draft+send into awaiting_reply (CLAR-01); reuse persist_reconciliation on the gated branch** — `d7925f4` (feat)
3. **Task 3: David Reyez gate-block hero fixture + end-to-end override replay (DEMO-01 gate-block half)** — `152cd0c` (feat)

**Plan metadata:** committed separately with SUMMARY.md + STATE.md + ROADMAP.md + REQUIREMENTS.md.

## Files Created/Modified
- `app/models/reconcile.py` — `NameReconciliationResponse{matches: list[NameMatchResult]}` (extra="forbid"), the layer-2 structured-output wrapper (FIX 6).
- `app/llm/prompts/reconcile.py` — layer-2 reconcile prompt: literal "json" + a `{"matches": [...]}` example + the FULL roster in-context (the tuning surface for the live hero run, Plan 04).
- `app/llm/prompts/clarify.py` — free-text clarification drafting prompt (no json/schema; no PII echo, no dollar figures — T-03-04).
- `app/pipeline/compose_email.py` — `compose_clarification(decision, *, llm)` via DRAFT_* `call_text`; templated `_template_body` fallback floor.
- `fixtures/gate_block_hero.json` — the David Reyez gate-block hero InboundEmail.
- `tests/test_clarify.py` — clarify tests (sends+pauses, empty-content fallback, draft-tier-not-json source, single persist_reconciliation, no payroll_runs Message-ID column).
- `app/pipeline/reconcile_names.py` — extended with layer-2 (residual-only, wrapper-unwrap, merge); DB-free.
- `app/pipeline/decide.py` — `check_one_to_one` extended with the three collision rules (signature unchanged).
- `app/pipeline/orchestrator.py` — `request_clarification` branch now drafts + sends + AWAITING_REPLY via the new `_clarify` helper.
- `tests/conftest.py` — InMemoryRepo gains `insert_email_message` + `get_outbound_message_id` (+ outbound store) so the gated path runs fully offline.
- `tests/test_reconcile.py`, `tests/test_gate.py`, `tests/test_orchestrator_states.py`, `tests/test_demo_fixtures.py` — new layer-2 / collision / gate-block tests + the FIFO-ordering / awaiting_reply updates (see Deviations).

## Decisions Made
- **Layer-2 reconcile defaults `llm=client` module** (not the orchestrator's run-level `llm`): the webhook path calls `run_pipeline(run_id)` with no llm, so reconcile must route through the patched `OpenAI` to be mockable. The clean fixture is all-deterministic → no layer-2 call → its 2-entry FIFO script is unchanged; the gate-block fixture has one residual → one layer-2 call → a reconcile entry slots between extract and decide.
- **`compose_clarification` is pure (Decision→str, no DB);** the orchestrator owns the send + status. The clarification threads off the inbound `message_id` (In-Reply-To + References) so Plan 04's header-chain reply match resolves to this run.
- **The gated outbound is exercised fully offline** by mirroring `insert_email_message` + `get_outbound_message_id` in the conftest InMemoryRepo — the real `gateway.send_outbound` runs against RAM, so no test needs a live DB to prove the FIX-3 Message-ID anchor.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan-02 orchestrator gated-branch test updated for the new FIFO order + the awaiting_reply terminal**
- **Found during:** Task 1 (then completed in Task 2)
- **Issue:** `test_orchestrator_states.py::test_branches_on_final_action_not_model_action` (shipped in Plan 02) scripted only 2 LLM responses (extract + decide) and asserted the gated terminal was `needs_clarification`. This plan's own work breaks BOTH assumptions: (a) wiring layer-2 means a residual name now triggers a 3rd LLM call (reconcile) between extract and decide, so the 2-entry FIFO mis-feeds the decision JSON into the reconcile wrapper (a `NameReconciliationResponse` ValidationError → ERROR); and (b) wiring the clarify draft+send replaces the `needs_clarification` terminal with the `awaiting_reply` pause (the very behavior CLAR-01 adds). Left as-is, a correct implementation would fail a stale test.
- **Fix:** Updated the test's FIFO script to 4 entries (extract → reconcile(unknown) → decide(process) → draft body) and changed the terminal assertion to `awaiting_reply`, adding a `get_outbound_message_id` non-NULL check. The test's INTENT (orchestrator follows `final_action`, never `model_action`) is preserved and strengthened.
- **Files modified:** tests/test_orchestrator_states.py (Task 1 for the FIFO order; Task 2 for the awaiting_reply terminal + outbound assert)
- **Verification:** `test_branches_on_final_action_not_model_action` green; `grep -c "model_action" app/pipeline/orchestrator.py` still 0.
- **Committed in:** `6a64135` (Task 1) + `d7925f4` (Task 2)

**2. [Rule 3 - Blocking] conftest InMemoryRepo extended with the outbound email surface**
- **Found during:** Task 2 (gated E2E run)
- **Issue:** The orchestrator's new `request_clarification` branch calls `gateway.send_outbound`, which calls `repo.insert_email_message`. The Plan-02 `fake_repo` did not patch `insert_email_message`/`get_outbound_message_id`, so the real repo ran against the LIVE DB → ForeignKeyViolation (the run row only exists in RAM) → the error-wrap routed the run to ERROR instead of awaiting_reply. The gated path could not be asserted offline.
- **Fix:** Added `insert_email_message` + `get_outbound_message_id` (and an `outbound` store) to `InMemoryRepo`, and registered both in the `fake_repo` monkeypatch list. The real `gateway.send_outbound` now runs fully in-memory, recording the synthetic Message-ID on the in-RAM outbound row — the FIX-3 anchor is provable with no live DB.
- **Files modified:** tests/conftest.py
- **Verification:** `test_clarify.py` (6) + the orchestrator gated test + the gate-block E2E all green offline; integration tests still collect (11 deselected).
- **Committed in:** `d7925f4` (Task 2)

**3. [Rule 1 - Bug] FIX-3 "no payroll_runs Message-ID column" test narrowed to avoid a prose false-positive**
- **Found during:** Task 2 (authoring the FIX-3 guard test)
- **Issue:** The first cut of `test_no_clarification_message_id_column_written` asserted the literal string `clarification_message_id` appears in NEITHER orchestrator nor repo source. But `repo.py`'s `get_outbound_message_id` docstring legitimately DOCUMENTS the deliberate absence ("there is no payroll_runs.clarification_message_id column") — a correct, intentional mention. The naive grep flagged the documentation as a violation.
- **Fix:** Narrowed the assertion: the orchestrator must not mention the token at all (it doesn't), and the repo must never `UPDATE payroll_runs ... SET ... clarification_message_id` (a regex over the actual write), while prose documenting the absence is allowed.
- **Files modified:** tests/test_clarify.py
- **Verification:** `test_no_clarification_message_id_column_written` green; the real guarantee (no Message-ID written to a payroll_runs column) holds.
- **Committed in:** `d7925f4` (Task 2)

---

**Total deviations:** 3 auto-fixed (2 bugs in test fixtures, 1 blocking test-harness gap).
**Impact on plan:** All three were test-side corrections demanded by this plan's own production wiring (layer-2 + clarify-send) — no production scope creep, no contract field added, no new dependency, no signature change. Every locked invariant holds: residual-only layer-2, the wrapper (FIX 6), purity (FIX A), the extended-not-replaced `check_one_to_one`, the single `persist_reconciliation` (D-A3-05), the FIX-3 anchor, the FIX-B sole status writer, and the two-distinct-mocks override.

## Known Stubs
None. The layer-2 LLM path, the one-to-one gate, the clarify draft+send, and the hero fixture are all wired and exercised by green tests. The only remaining Plan-02 stub (the layer-2 reconcile path) is RESOLVED by this plan.

(One `grep` hit for "placeholder" in `app/llm/prompts/clarify.py` is a prompt instruction telling the model NOT to include a signature placeholder — not a code stub.)

## Issues Encountered
- The conftest `mock_llm` is a single class-level FIFO queue, which is exactly what the two-distinct-mocks requirement needs: sequential `call_structured`/`call_text` invocations pop different scripted responses in order (extract → reconcile → decide → draft). No conftest change to the FIFO mechanism was needed — only the per-test scripts and the outbound-repo surface (Deviation 2).

## User Setup Required
None for this plan. Forward-looking blocker (carried in STATE.md, unchanged): confirm the exact DeepSeek non-thinking request parameter + the exact DeepSeek/Kimi model IDs from the consoles before the LIVE hero-fixture exit run (D-A4-01a). Config-driven, so confirmation is a one-line `.env` change, not a code change. The live hero run itself is Plan 04 + the Phase 2 exit gate (the mock here proves the gate; the live run proves David Reyez actually lands sub-0.8 against the real model).

## Next Phase Readiness
- **Slice (b) — the gate-block case — is complete.** Plan 04 (slice c) builds on a stable spine: the clarification is already sent with its Message-ID anchored on the outbound `email_messages` row and the run paused at `awaiting_reply`. Plan 04 wires the reply-fixture injection + the header-chain routing (CLAR-02, via `find_awaiting_reply_for_header` / `find_any_run_for_header`, both already in the repo) + idempotent re-entry at extraction (CLAR-03), then runs the LIVE hero exit gate (D-A4-01a).
- The layer-2 reconcile + the extended gate are eval-reusable (Phase 4 calls the identical pure functions); per-name reconciliation + the Decision are persisted on EVERY run (clean + gated) for offline scoring.
- Open blocker (unchanged): exact provider model IDs + the non-thinking request param before the live hero run.

## Self-Check: PASSED

All 6 created files (+ this SUMMARY) verified present on disk; all 3 task commits (`6a64135`, `d7925f4`, `152cd0c`) present in git history.

---
*Phase: 02-walking-skeleton*
*Completed: 2026-06-21*
