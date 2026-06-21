---
phase: 2
slug: walking-skeleton
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-21
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> **Central subtlety: the mock proves the gate; only the live run proves the demo.** Both are required exit gates (see §The mock/live distinction).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 (installed in `.venv`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (markers registered here — ADD `live_llm` alongside existing `integration`) |
| **Quick run command** | `.venv/bin/python -m pytest -m "not integration and not live_llm" -x -q` |
| **Full suite command** | `.venv/bin/python -m pytest -q` (adds `integration` + `live_llm` when their two-factor env guards are satisfied) |
| **Estimated runtime** | ~a few seconds (mocked suite; no network) |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest -m "not integration and not live_llm" -x -q` (deterministic, free, no network)
- **After every plan wave:** Run the full mocked suite + (if `DATABASE_URL` present) `.venv/bin/python -m pytest -m integration`
- **Before `/gsd-verify-work`:** Full mocked suite green **AND** the D-A4-01a live hero run produces *model-says-process + gate-blocks-on-sub-0.8* (the distinct live exit gate)
- **Max feedback latency:** < ~5 seconds (mocked suite)

---

## Per-Task Verification Map

> Derived from RESEARCH.md §Validation Architecture → "Phase Requirements → Test Map". Plan/Wave/Task IDs are assigned by the planner; the (Req → Test) pairing below is authoritative.

| Requirement | Wave | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|------|------------|-----------------|-----------|-------------------|-------------|--------|
| INGEST-01 | early | — | webhook returns 200 fast + schedules pipeline; TestClient runs it synchronously | integration (in-process, no server) | `pytest tests/test_webhook.py::test_post_fixture_reaches_pause -x` | ❌ W0 | ⬜ pending |
| INGEST-01 / FOUND-02 | early | T-replay | duplicate POST (same Message-ID) creates no second run | unit | `pytest tests/test_webhook.py::test_duplicate_delivery_idempotent -x` | ❌ W0 | ⬜ pending |
| INGEST-02 | early | T-PII | inbound stored with headers; quoted history/signatures stripped before extraction by an in-house code-strip (no third-party parser in Phase 2) | unit | `pytest tests/test_ingest.py::test_body_cleaned -x` | ❌ W0 | ⬜ pending |
| INGEST-03 | early | T-spoof | unknown sender logged + stopped, no run created | unit | `pytest tests/test_webhook.py::test_unknown_sender_no_run -x` | ❌ W0 | ⬜ pending |
| INGEST-04 | mid | — | orchestrator reaches `awaiting_approval` (clean) and `awaiting_reply` (gate) | unit (mocked LLM) | `pytest tests/test_orchestrator_states.py -x` | ❌ W0 | ⬜ pending |
| INGEST-04 | mid | T-hang | unhandled stage exception → run set to ERROR with reason (no silent hang) | unit | `pytest tests/test_orchestrator_states.py::test_stage_raise_sets_error -x` | ❌ W0 | ⬜ pending |
| LLM-01 / LLM-02 | early | T-inject | client routes per tier; JSON-mode call validates; reflective retry fires once then raises | unit (mocked responses) | `pytest tests/test_llm_client.py -x` | ❌ W0 | ⬜ pending |
| LLM-03 | early | — | extraction returns per-employee entries incl. optional run-only 401k override | unit (mocked) | `pytest tests/test_extract.py -x` | ❌ W0 | ⬜ pending |
| LLM-04 | early | — | deterministic exact/case/whitespace/alias match, NO model call | unit | `pytest tests/test_reconcile.py::test_layer1_deterministic -x` | ❌ W0 | ⬜ pending |
| LLM-05 | early | — | only residual names reach the LLM; layer-1 hits never re-decided | unit (mocked) | `pytest tests/test_reconcile.py::test_residual_only_to_llm -x` | ❌ W0 | ⬜ pending |
| LLM-06 | early | T-inject | validation emits `missing` / `out_of_bounds` / `non_numeric` issues | unit | `pytest tests/test_validate.py -x` | ❌ W0 | ⬜ pending |
| **LLM-07** | **mid** | **T-inject** | **gate fires on a sub-0.8 name even when `model_action=process` (THE THESIS)** | unit (mocked, deterministic) | `pytest tests/test_gate.py::test_sub_threshold_blocks_process -x` | ❌ W0 | ⬜ pending |
| LLM-07 | mid | — | gate evaluates EACH name's confidence, not the collapsed scalar (D-A3-03a) | unit | `pytest tests/test_gate.py::test_per_name_not_average -x` | ❌ W0 | ⬜ pending |
| LLM-08 | mid | — | a clean run persists BOTH `Decision` (to `payroll_runs.decision`) AND the per-name `list[NameMatchResult]` (to `payroll_runs.reconciliation`, never NULL on a clean run); both round-trip from `payroll_runs` (D-A3-05) | integration | `pytest tests/test_persistence.py::test_decision_roundtrip -x` | ❌ W0 (Plan 02 Task 3) | ⬜ pending |
| LLM-09 | mid | — | one-to-one mapping collisions (dup name / two→one emp / name→no emp) gate to clarify; Plan 03 EXTENDS the empty-but-real check_one_to_one shipped in Plan 02 | unit | `pytest tests/test_gate.py::test_one_to_one_collisions -x` | ❌ W0 | ⬜ pending |
| HITL-01 | mid | — | computed run pauses at `awaiting_approval`; crude approve→approved, reject→rejected | unit | `pytest tests/test_hitl.py -x` | ❌ W0 | ⬜ pending |
| CLAR-01 | late | — | clarify drafts + stub-sends; outbound Message-ID stored; status→`awaiting_reply` | unit (mocked draft) | `pytest tests/test_clarify.py::test_clarify_sends_and_pauses -x` | ❌ W0 | ⬜ pending |
| CLAR-02 / EMAIL-01 | late | T-inject(SQL) | reply routes to its run via In-Reply-To/References (subject fallback only); Message-ID parameterized | unit | `pytest tests/test_threading.py::test_header_chain_match -x` | ❌ W0 | ⬜ pending |
| CLAR-03 | late | — | matched reply re-enters extraction idempotently (overwrite data, replace line items); late reply to sent/reconciled run logged not resumed | unit | `pytest tests/test_threading.py::test_idempotent_resume -x` | ❌ W0 | ⬜ pending |
| DEMO-01 | late | — | both committed fixtures replay end-to-end via POST (gate-block driven by TWO distinct mocks: reconcile 0.6 + decision process) | integration (mocked LLM) | `pytest tests/test_demo_fixtures.py -x` | ❌ W0 | ⬜ pending |
| **D-A4-01a** | **exit gate** | — | **REAL model returns process + sub-0.8 for `David Reyez`; gate blocks (LIVE)** | live_llm (env-gated) | `ALLOW_LIVE_LLM=1 pytest tests/test_live_llm.py::test_hero_fixture_live -x` | ❌ W0 | ⬜ pending (manual/human) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## The mock-proves-the-gate / live-proves-the-demo distinction (central subtlety)

- **Mocked tests (default CI):** feed `decide()` a hand-authored `list[NameMatchResult]` with `confidence=0.6` and `model_action=process`, assert `final_action=request_clarification`. This **proves the gate** deterministically — given a sub-0.8 input, the code blocks. It does NOT prove the real model produces that input, because *we authored the 0.6*. The gate-block fixture replay (DEMO-01) drives this with **two structurally-distinct mocks** — the layer-2 reconcile call returns the 0.6 NameMatchResult and the decision-advisory call returns `model_action=process` — so the test asserts the override (`final_action==request_clarification` WHILE `model_action==process`), not a degenerate single-mock.
- **Live test (D-A4-01a, env-gated):** runs the actual `David Reyez` fixture through the real DeepSeek/Kimi models and asserts the model *genuinely* returns `process` + sub-0.8 confidence so the gate fires on real output. This **proves the demo**. The mock alone CANNOT prove the demo (two invisible failure modes: model self-clarifies → gate never fires; or model returns ≥0.8 → mismatch processes).
- **Both are required.** Phase 2 cannot be called done on the mock alone (D-A4-01a, D-A5-01). The live run is budgeted with a tuning loop on the submitted-name variant + reconcile prompt — **a human-judgment step, not an automated pass/fail.**

---

## Wave 0 Requirements

- [ ] `.venv/bin/python -m pip install -r requirements.txt` — activate `openai` / `fastapi` / `uvicorn` / `python-multipart` (pinned, not yet installed)
- [ ] Register the `live_llm` marker in `pyproject.toml` (mirror the existing `integration` marker)
- [ ] `tests/conftest.py` — shared fixtures: a mocked-LLM client factory (supporting DISTINCT per-call/per-tier responses so the reconcile + decision surfaces can differ), the committed `InboundEmail` fixtures, a Roster builder from seed
- [ ] `tests/test_gate.py` — the deterministic gate suite (LLM-07/09, D-A3-03a) incl. the check_one_to_one stub-shape test — **highest priority, this is the thesis**
- [ ] `tests/test_persistence.py` — the decision + reconciliation round-trip test (LLM-08, D-A3-05) — asserts BOTH persist on a clean run
- [ ] `tests/test_orchestrator_states.py` — both pauses + error-on-raise
- [ ] `tests/test_threading.py` — header-chain routing + idempotent resume + late-reply-not-resumed
- [ ] `tests/test_llm_client.py` — JSON mode + reflective retry (mocked)
- [ ] `tests/test_live_llm.py` — the env-gated D-A4-01a live exit gate
- [ ] committed `fixtures/` — clean happy path, gate-block hero (`David Reyez`), the reply (with `in_reply_to` = the clarification's synthetic Message-ID)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live hero-fixture run: real model says `process` AND code gate blocks on sub-0.8 | D-A4-01a / DEMO-01 | Validates a **model-behavior + demo-narrative** property, not a code property — no reviewer/test can assert what the real model returns; needs a human to judge the on-camera story and tune the prompt/fixture until it genuinely produces "model willing, code said no" | 1. Confirm DeepSeek/Kimi model IDs + non-thinking param from consoles (STATE.md blocker). 2. `ALLOW_LIVE_LLM=1 pytest tests/test_live_llm.py::test_hero_fixture_live -x`. 3. If model self-clarifies or returns ≥0.8, tune the submitted-name variant + reconcile prompt and repeat. Confirm the live-vs-mock marker is a log field / separate column (NOT a key inside the extra="forbid" Decision object). |
| Live provider smoke-test (creds + model IDs resolve) | LLM-01 / D-A2-02 | Requires real API round-trip; provider IDs are an open blocker | After build installs `openai`: one tiny `temperature=0, max_tokens=5` call per tier; confirm 200 + non-thinking mode. |

---

## Validation Sign-Off

- [ ] All requirements have an `<automated>` verify or a Wave 0 dependency
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < ~5s (mocked suite)
- [ ] `nyquist_compliant: true` set in frontmatter (after planner wires `<automated>` blocks)

**Approval:** pending
