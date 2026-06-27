---
phase: 7
slug: money-correctness-deepening
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-27
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `07-RESEARCH.md` § Validation Architecture. Honors the **D-23 two-layer split**:
> the eval certifies *judgment* (import `validate`/`decide` directly); integration tests certify
> the *state machine* (snapshot / `clarified_fields` loop-guard / backfill) the eval cannot see.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (run via `uv run pytest`) |
| **Config file** | none found — pytest auto-discovers `tests/` |
| **Quick run command** | `uv run pytest tests/test_validate.py tests/test_reconcile.py -q` |
| **Full suite command** | `uv run pytest -q` |
| **Eval check** | `uv run python eval/run_eval.py --check` |
| **Estimated runtime** | ~30 seconds (unit); integration adds DB round-trips |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_validate.py tests/test_reconcile.py -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite green AND `uv run python eval/run_eval.py --check` passes
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

> Plan/Task IDs are assigned by the planner; this map is keyed by requirement + behavior so the
> planner can attach `<automated>` commands. `unit` = import-`validate`/`decide` judgment (eval layer,
> D-23). `integration` = real DB columns + `resume_pipeline` (state-machine layer, D-23).

| Requirement | Behavior | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|----------|------------|-----------------|-----------|-------------------|-------------|--------|
| MONEY-01 | Hourly + `hours_regular=0`, all other hours None/0 → `request_clarification` (never $0 stub) | — | N/A | unit | `uv run pytest tests/test_validate.py -k "zero_hours" -x` | ❌ W0 | ⬜ pending |
| MONEY-01 | `hours_regular=0` + `hours_holiday=8` (partial week) → NOT gated (D-03 edge) | — | N/A | unit | `uv run pytest tests/test_validate.py -k "partial_week" -x` | ❌ W0 | ⬜ pending |
| MONEY-01 | `pay_type=None`/unknown + all-zero hours → fail-safe gate (D-03) | — | N/A | unit | `uv run pytest tests/test_validate.py -k "unknown_pay_type" -x` | ❌ W0 | ⬜ pending |
| MONEY-01 | Salaried + no hours → NOT gated (D-03: never reaches gate) | — | N/A | unit | `uv run pytest tests/test_validate.py -k "salaried_no_gate" -x` | ❌ W0 | ⬜ pending |
| MONEY-01 | D-25 predicate-consistency: `OT 2→0` gates identically to `OT 2→absent` | — | N/A | unit | `uv run pytest tests/test_validate.py -k "predicate_consistency" -x` | ❌ W0 | ⬜ pending |
| MONEY-02 | NFD "José" matches NFC "José" in roster via `_norm` → same `matched_employee_id` (D-07) | — | N/A | unit | `uv run pytest tests/test_reconcile.py -k "nfd" -x` | ❌ W0 | ⬜ pending |
| MONEY-02 | `run_eval.py:_normalize` NFC-normalizes before casefold (C-4 fix — eval scorer parity) | — | N/A | unit | `uv run pytest tests/test_eval_wiring.py -k "nfd" -x` | ❌ W0 | ⬜ pending |
| MONEY-03 | `detect_field_regression`: `OT=2` snapshot, `OT=None` resumed → returns `FieldDrop` for OT | — | N/A | unit | `uv run pytest tests/test_validate.py -k "detect_regression" -x` | ❌ W0 | ⬜ pending |
| MONEY-03 | `field_regression` ValidationIssue gates to `request_clarification` via decide (C-1: widened Literal + decide rule) | V5 | Pydantic `extra="forbid"`; JSONB via `json.dumps` | unit | `uv run pytest tests/test_decide.py -k "field_regression" -x` | ❌ W0 | ⬜ pending |
| MONEY-03 | D-26 explicit-drop: reply `OT=0` → `confirmed_dropped`, NO carry-forward (fails today) | — | N/A | unit | `uv run pytest tests/test_validate.py -k "explicit_drop" -x` | ❌ W0 | ⬜ pending |
| MONEY-03 | D-27 determinism: no-op reply → `detect_field_regression` returns `[]` | — | N/A | unit | `uv run pytest tests/test_validate.py -k "no_regression" -x` | ❌ W0 | ⬜ pending |
| MONEY-03 | D-28 multi-round baseline: second clarification does NOT overwrite `pre_clarify_extracted` (D-19 snapshot-once) | V5 | `IS NULL` SQL guard | integration | `uv run pytest tests/test_resume_pipeline.py -k "snapshot_once" -x` | ❌ W0 | ⬜ pending |
| MONEY-03 | Loop guard: field-regression clarify fires exactly ONCE, then carry-forward; no infinite re-clarify (D-13/D-16/D-20) | — | N/A | integration | `uv run pytest tests/test_resume_pipeline.py -k "loop_guard" -x` | ❌ W0 | ⬜ pending |
| MONEY-03 | D-15: `confirmed_dropped` field short-circuits MONEY-01 (does not re-flag) | — | N/A | integration | `uv run pytest tests/test_resume_pipeline.py -k "confirmed_dropped_no_reflag" -x` | ❌ W0 | ⬜ pending |
| MONEY-01/02/03 | Three new eval judgment fixtures score correctly (D-24: serialized via `model_dump_json`) | — | N/A | unit (eval) | `uv run python eval/run_eval.py --check` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_validate.py` — MONEY-01 + MONEY-03 detection tests (zero-hours, partial-week, unknown-pay-type, salaried-no-gate, predicate-consistency, detect-regression, explicit-drop, no-regression)
- [ ] `tests/test_reconcile.py` — MONEY-02 NFD test (file EXISTS — extend it)
- [ ] `tests/test_decide.py` — `field_regression` issue gates to clarification (NEW file — does not exist yet)
- [ ] `tests/test_eval_wiring.py` — `run_eval.py:_normalize` NFC parity (file EXISTS — extend it; covers C-4)
- [ ] `tests/test_resume_pipeline.py` — integration: snapshot-once, loop-guard, confirmed-dropped-no-reflag (NEW file; needs live DATABASE_URL)
- [ ] `eval/fixtures/` — three new fixtures (zero-hours-hourly, NFD-name, field-drop/carry-forward) + their `_extraction.json`, serialized through `extracted.model_dump_json()` per D-24

*Confirmed against live `tests/` (2026-06-27): `test_validate.py`, `test_reconcile.py`, `test_eval_wiring.py` EXIST (extend them); `test_decide.py` and `test_resume_pipeline.py` are NEW. There is no `test_reconcile_names.py` — the canonical reconcile test file is `test_reconcile.py`.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Clarification-email copy reads naturally ("did you forget the overtime?") and phrases the question so "yes, remove it" lands as an explicit `0` in re-extraction (D-14) | MONEY-03 | Email copy quality + LLM re-extraction behavior is judgment, not a pure assertion | Send the worked-example reply ("40", no OT) end-to-end on the dev deploy; confirm one clarification, then carry-forward of OT=2; separately reply "remove the OT" and confirm `confirmed_dropped` (no backfill) |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (every plan task uses a `uv run` command)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (new files: `test_decide.py`, `test_resume_pipeline.py`, fixtures 16–18)
- [x] No watch-mode flags
- [x] Feedback latency < 30s (unit suite ~30s; integration adds DB round-trips)
- [x] `nyquist_compliant: true` set in frontmatter

*`wave_0_complete` stays `false` until the RED test scaffolds are actually written in Wave 1 of execution.*

**Approval:** approved 2026-06-27
