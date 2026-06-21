---
phase: 02-walking-skeleton
plan: 02
subsystem: pipeline
tags: [fastapi, background-tasks, pydantic, code-gate, fica, orchestrator, llm-pipeline, hitl]

# Dependency graph
requires:
  - phase: 02-walking-skeleton (Plan 01)
    provides: "The one OpenAI-compatible LLM client (call_structured/call_text, JSON mode, one reflective retry), the stub EmailGateway (parse_inbound/send_outbound), the FULL DB repo surface (set_status sole writer, record_run_error, persist_extracted/decision/reconciliation data-only, insert_inbound_email cleaned-body source-of-truth, find_business_by_sender, create_run, load_run/source_email, header-chain lookups), reconciliation/error_reason columns, FakeConnection + conftest fixtures"
provides:
  - "The clean happy path end-to-end: POST clean fixture → webhook (BackgroundTasks, fast 200, dedupe, sender-match, body-clean) → four PURE judgment stages → code-gated decision → thin gross+FICA calc → awaiting_approval → crude approve/reject"
  - "decide.py — THE CODE GATE: advisory model_action + code-owned final_action; per-name Decimal('0.8') gate (not the collapsed scalar); unresolved/missing/one-to-one rules; check_one_to_one real-but-empty (Plan 03 extends); min() confidence collapse"
  - "The four pure stages: extract (ExtractionPayload + code-owned run_id, FIX A), reconcile_names (Layer-1 deterministic), validate (pay-type-aware missing-hours), decide (the gate) — all DB-free, eval-reusable"
  - "orchestrator.run_pipeline: state machine, error-wrap via record_run_error, persists Extracted+Decision+reconciliation on EVERY run, branches SOLELY on final_action"
  - "calculate.py: thin gross+FICA (SS wage-base cap honored), federal=0, PRE_FEDERAL_NET_LABEL display constant (no contract field)"
  - "app/main.py: FastAPI webhook + crude approve/reject; ExtractionPayload contract; clean_body() in-house body-strip; clean_happy_path.json fixture; README disclaimer stub"
affects: [02-03, 02-04, walking-skeleton, pipeline, orchestrator, eval, dashboard]

# Tech tracking
tech-stack:
  added: []  # no new packages — webhook + body-clean are in-house code (FIX C); requirements.txt unchanged
  patterns:
    - "Pure judgment stages (extract/reconcile/validate/decide) take typed values + a code-owned run_id but NO DB connection — eval-reusable; purity = no-DB, not no-run_id"
    - "The code gate lives INSIDE decide.py (never the orchestrator); final_action is the SOLE branch source; nothing downstream reads the model's advisory action"
    - "In-memory fake_repo + scriptable mock_llm conftest fixtures let the FULL pipeline run offline; TestClient runs BackgroundTasks synchronously so the E2E pause is asserted with no server/sleeps"
    - "Persistence helpers write data-only; the orchestrator advances state via the sole set_status writer SEPARATELY (FIX B)"
    - "Pre-federal net is a (net_pay, federal_withholding=0) PAIR + a module-constant display label, NOT a contract field (FIX 2)"

key-files:
  created:
    - app/main.py
    - app/email/clean.py
    - app/pipeline/extract.py
    - app/pipeline/reconcile_names.py
    - app/pipeline/validate.py
    - app/pipeline/decide.py
    - app/pipeline/calculate.py
    - app/pipeline/orchestrator.py
    - app/llm/prompts/extract.py
    - app/llm/prompts/decide.py
    - fixtures/clean_happy_path.json
    - README.md
    - tests/test_webhook.py
    - tests/test_ingest.py
    - tests/test_extract.py
    - tests/test_reconcile.py
    - tests/test_validate.py
    - tests/test_gate.py
    - tests/test_orchestrator_states.py
    - tests/test_persistence.py
    - tests/test_hitl.py
    - tests/test_demo_fixtures.py
  modified:
    - app/models/contracts.py
    - app/db/repo.py
    - tests/conftest.py

key-decisions:
  - "validate() takes (extracted, roster, matches) not just (extracted): 'required' hours is pay-type-aware — an hourly employee with no hours is missing data; a salaried employee legitimately reports none. Roster is a pure value (no DB), so purity is preserved while the missing-field rule stays correct and the clean path (salaried James Okafor) stays green."
  - "Added repo.load_inbound_email(run_id) (explicit cols + dict_row, cleaned body unchanged — FIX C) so the orchestrator can hand the pure extract() stage a typed InboundEmail without re-cleaning."
  - "check_one_to_one returns [] (empty-but-real) — a real, called function with the final signature that Plan 03 extends with the three collision rules; a stub-shape test pins it."

patterns-established:
  - "Offline full-pipeline testing: an in-memory InMemoryRepo store patched over app.db.repo + a class-level FIFO MockOpenAI script, driven through TestClient's synchronous BackgroundTasks."
  - "The thesis test shape: feed decide() a sub-0.8 match + model_action='process' → assert final_action='request_clarification' (the gate overrides the willing model)."

requirements-completed: [INGEST-01, INGEST-02, INGEST-03, INGEST-04, LLM-03, LLM-04, LLM-06, LLM-07, LLM-08, HITL-01, DEMO-01]

# Metrics
duration: 38min
completed: 2026-06-21
---

# Phase 2 Plan 02: Clean Happy Path End-to-End Summary

**The judgment spine's clean half: a clean fixture POSTed to /webhook/inbound flows through four PURE judgment stages to the code-owned gate in decide.py (per-name Decimal("0.8") test, never the collapsed scalar), runs a thin gross+FICA calc (net pre-federal, federal=0), pauses at awaiting_approval, and a crude approve/reject proves the operator gate pauses and resumes — the one-third end-to-end proof, with the thesis (the model proposes, code disposes) exhaustively tested.**

## Performance

- **Duration:** ~38 min
- **Started:** 2026-06-21
- **Completed:** 2026-06-21
- **Tasks:** 4 (all TDD)
- **Files modified:** 25 (22 created, 3 modified)

## Accomplishments
- **THE CODE GATE (decide.py) — the thesis, shipped and exhaustively tested:** advisory `model_action` from the LLM + code-owned `final_action`; the per-name `Decimal("0.8")` test (proven NOT to gate on the collapsed `min()` scalar via `test_per_name_not_average`), unresolved/missing-field/one-to-one rules; `check_one_to_one` is a real, called, empty-but-real function with the final signature for Plan 03 to extend; `min()` confidence collapse. The thesis test `test_sub_threshold_blocks_process` passes: a sub-0.8 name forces clarify even when the model says `process`.
- **The clean happy path runs end-to-end:** `test_post_fixture_reaches_pause` is GREEN — POST `clean_happy_path.json` → webhook (fast 200, dedupe, sender access-control, in-house body-clean before insert) → BackgroundTask → extract (code-owned run_id stamped, FIX A) → reconcile (Layer-1 deterministic, no model) → validate → decide (gate) → thin gross+FICA calc → `awaiting_approval` → crude approve → `approved`.
- **Four PURE stages, all DB-free** (`grep -L "supabase\|get_connection\|repo\."` lists all four): extract returns `ExtractionPayload` (no run_id) then stamps the code-owned run_id to build the required `Extracted` (FIX A); the `non_numeric` path is honestly reconciled to the extraction-stage parse failure → reflective retry → ERROR (FIX 1), so validate.py structurally never classifies it.
- **Orchestrator state machine** branches SOLELY on `final_action` (`grep -c "model_action"` returns 0), persists Extracted + Decision (data-only) + per-name reconciliation on EVERY run (never NULL on a clean run, D-A3-05), and error-wraps via `repo.record_run_error` (PII-safe reason + ERROR via the sole `set_status` writer, FIX 7 + FIX B).
- **Thin calc, honest numbers:** gross + FICA only (SS 6.2% honoring the $184,500 wage-base cap via `ytd_ss_wages`, straddle-tested; Medicare 1.45% no cap); `federal_withholding=Decimal("0")`; the "pre-federal" label is the `PRE_FEDERAL_NET_LABEL` module constant (NOT a `PaystubLineItem` field — FIX 2), reused verbatim by the README disclaimer.
- **No new dependency:** the INGEST-02 body-clean is in-house code (`app/email/clean.py`); `requirements.txt` is unchanged — no package-legitimacy gate.
- **Full mocked suite green: 129 passed, 11 deselected** (the live-DB integration round-trips skip without creds, as designed).

## Task Commits

Each task was committed atomically (all TDD; the RED end-to-end test was authored in Task 1 and went GREEN in Task 3 when the orchestrator landed):

1. **Task 1: Failing E2E webhook test + ingest (webhook, BackgroundTasks, dedupe, sender match, body clean)** — `a010dcd` (feat)
2. **Task 2: The four pure judgment stages + the code gate in decide.py** — `2b69182` (feat)
3. **Task 3: Orchestrator state machine + thin gross+FICA calc + persistence + error_reason** — `76ecf35` (feat)
4. **Task 4: Crude approve/reject re-entry + demo replay green + README stub** — `038d439` (feat)

**Plan metadata:** committed separately with SUMMARY.md + STATE.md + ROADMAP.md.

## Files Created/Modified
- `app/main.py` — FastAPI POST /webhook/inbound (BackgroundTasks, fast 200, dedupe, sender access-control, body-clean before insert) + crude approve/reject endpoints.
- `app/email/clean.py` — minimal in-house quoted-history + signature strip (no new dependency; disjoint from gateway.py for parallel safety).
- `app/pipeline/extract.py` — pure extract(email, roster, *, run_id, llm); ExtractionPayload → Extracted run_id stamping (FIX A).
- `app/pipeline/reconcile_names.py` — Layer-1 deterministic match (Layer-2 LLM is Plan 03).
- `app/pipeline/validate.py` — pay-type-aware missing-hours; never emits non_numeric (FIX 1).
- `app/pipeline/decide.py` — THE CODE GATE.
- `app/pipeline/calculate.py` — thin gross+FICA, PRE_FEDERAL_NET_LABEL, federal=0 (FIX 2).
- `app/pipeline/orchestrator.py` — run_pipeline state machine + error-wrap + persistence.
- `app/llm/prompts/extract.py`, `app/llm/prompts/decide.py` — JSON-mode prompts carrying "json" + an example shape (Pitfall 1).
- `fixtures/clean_happy_path.json` — canonical clean InboundEmail (Maria Chen + James Okafor, seeded contact_email).
- `README.md` — minimal honesty disclaimers (educational model + net pre-federal).
- `app/models/contracts.py` — added ExtractionPayload (no run_id, extra="forbid").
- `app/db/repo.py` — added load_inbound_email (cleaned body, explicit cols).
- `tests/conftest.py` — in-memory fake_repo store + scriptable mock_llm fixtures.
- `tests/test_*.py` — 11 new test modules (webhook, ingest, extract, reconcile, validate, gate, orchestrator_states, persistence, hitl, demo_fixtures).

## Decisions Made
- **validate() is pay-type aware via the roster (a pure value).** The plan's `validate(extracted)` sketch could not distinguish a salaried employee (legitimately no hours) from an hourly employee who is missing hours. Passing the `Roster` + reconciliation `matches` (both pure values, no DB) keeps purity intact while making the missing-field rule correct AND keeping the clean path (salaried James Okafor) green. Documented as a deviation below.
- **Added `repo.load_inbound_email(run_id)`** so the orchestrator hands the pure `extract()` a typed `InboundEmail` rebuilt from the cleaned source-email row (no re-clean — FIX C).
- **`check_one_to_one` ships as `return []`** — a real, called function with the final signature pinned by `test_check_one_to_one_stub_shape`; Plan 03 extends it with the three collision rules.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] validate() made pay-type aware (roster + matches args)**
- **Found during:** Task 2 (validate stage) / Task 3 (clean-path verification)
- **Issue:** The plan's pure `validate(extracted) -> list[ValidationIssue]` sketch, applied literally, would flag a salaried employee with no hours as `missing` — which would gate the CLEAN happy-path fixture (salaried James Okafor) to clarification and prevent it from reaching `awaiting_approval`, breaking the slice's marquee success criterion. validate is roster-blind in the sketch and cannot tell "salaried, no hours needed" from "hourly, hours missing."
- **Fix:** `validate(extracted, roster, matches)` — both extra args are PURE values (no DB), so purity is preserved (the `grep -L` purity guard still lists validate.py). The missing-hours rule is now pay-type aware: an HOURLY employee with all-None hours → `missing`; a SALARIED employee with no hours → no issue (calc uses annual_salary). The genuine missing-field case still fires (test_missing_hours_for_hourly_employee).
- **Files modified:** app/pipeline/validate.py, app/pipeline/orchestrator.py (call site), tests/test_validate.py
- **Verification:** test_validate.py green (missing fires for hourly, not for salaried); the clean E2E path reaches awaiting_approval.
- **Committed in:** `2b69182` (Task 2) + `76ecf35` (Task 3 call site)

**2. [Rule 3 - Blocking] Added repo.load_inbound_email helper**
- **Found during:** Task 3 (orchestrator)
- **Issue:** The pure extract() stage needs a typed InboundEmail, but the Plan 01 repo surface exposed only load_source_email (body string), not a full InboundEmail rebuild. Without it the orchestrator couldn't construct the stage input.
- **Fix:** Added load_inbound_email(run_id) (explicit _INBOUND_COLS + dict_row, no SELECT *; returns the cleaned body unchanged — FIX C) following the existing repo read-back discipline.
- **Files modified:** app/db/repo.py
- **Verification:** test_extract_called_with_run_id + the E2E pause test green; the in-memory fake_repo mirrors the helper offline.
- **Committed in:** `76ecf35` (Task 3)

**3. [Rule 3 - Blocking] Orchestrator docstring/comment reworded to satisfy the model_action==0 source assertion**
- **Found during:** Task 3 (test_orchestrator_source_never_reads_model_action)
- **Issue:** The acceptance criterion is `grep -c "model_action" app/pipeline/orchestrator.py` returns 0. The orchestrator's explanatory docstring/comment literally used the token "model_action" (to say it must NOT read it), which made the count non-zero.
- **Fix:** Reworded the docstring + inline comment to "the model's advisory action" so the literal token count is 0 while the meaning is unchanged. The orchestrator genuinely never branches on the advisory action — only on final_action.
- **Files modified:** app/pipeline/orchestrator.py
- **Verification:** `grep -c "model_action"` returns 0; test_orchestrator_source_never_reads_model_action green.
- **Committed in:** `76ecf35` (Task 3)

---

**Total deviations:** 3 auto-fixed (1 missing-critical, 2 blocking).
**Impact on plan:** All three were correctness/wiring fixes that preserve every locked invariant — purity (validate still DB-free), the gate ownership, FIX A/B/C/1/2, and the slice's end-to-end success criterion. No scope creep, no contract field added, no new dependency.

## Known Stubs

- **`app/pipeline/decide.py::check_one_to_one(matches, extracted) -> list[str]` returns `[]`** — this is an INTENTIONAL, plan-mandated empty-but-real function (the plan's `<artifacts>` spec and `test_check_one_to_one_stub_shape` both pin it as such). It has the FINAL signature and is genuinely called inside `decide()` so its (currently empty) gate_reasons are already unioned into the gate. Plan 03 EXTENDS this same function with the three one-to-one collision rules (duplicate name / two names → one employee / name → no roster employee, LLM-09 / D-A3-02). It does NOT block this plan's goal (the clean happy path has no collisions) and the resolving plan (03) is named.
- **`app/pipeline/reconcile_names.py` Layer-2 LLM path** — residual (non-deterministic) names currently resolve to `unknown` (gated). The Layer-2 LLM classification (`llm_typo`/`llm_nickname` + confidence) is Plan 03 (the gate-block hero fixture). The clean happy-path fixture is all-deterministic so this is not exercised here; resolved in Plan 03.

## Issues Encountered
- The marquee `test_post_fixture_reaches_pause` was authored RED in Task 1 (per MVP mode — the failing test defines the slice) and stayed RED through Task 2; it went GREEN in Task 3 when the orchestrator landed. The Task-1 webhook BackgroundTask wrapper (`_run_pipeline`) was given a defensive try/except so a missing/failing orchestrator could never propagate out of the BackgroundTask (the webhook has already returned 200) — this is forward-compatible production behavior (D-A1-03 owns stage-error persistence; this guard only catches a catastrophic start failure and logs it).

## User Setup Required
None for this plan. Forward-looking blocker (carried in STATE.md, unchanged): confirm the exact DeepSeek non-thinking request parameter + the exact DeepSeek/Kimi model IDs from the consoles before the live hero-fixture exit run (D-A4-01a). Config-driven, so confirmation is a one-line `.env` change, not a code change. The live hero run itself (gate-block fixture) is Plan 03 + the Phase 2 exit gate.

## Next Phase Readiness
- **Slice (a) — the clean happy path — is complete and is the one-third end-to-end proof.** Plan 03 (slice b, the gate-block case) builds on a stable, tested spine: the gate in decide.py (extend `check_one_to_one`), the Layer-2 LLM reconcile path (extend `reconcile_names`), the clarify branch (already wired in the orchestrator to `needs_clarification`; add the compose+send + AWAITING_REPLY pause).
- The pure stages + the gate are eval-reusable (Phase 4 calls the identical functions); per-name reconciliation + the Decision are persisted now so Phase 4 scores without re-running the model.
- Open blocker (unchanged): exact provider model IDs + the non-thinking param before the live hero run.

## Self-Check: PASSED

All created files verified present on disk; all 4 task commits present in git history (see below).

---
*Phase: 02-walking-skeleton*
*Completed: 2026-06-21*
