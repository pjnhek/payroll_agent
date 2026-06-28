---
phase: 7
slug: money-correctness-deepening
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-27
---

# Phase 7 — Validation Strategy (Pure-Function Gates)

> Per-phase validation contract for feedback sampling during execution.
> **Re-scoped 2026-06-27:** Phase 7 = MONEY-01 + MONEY-02 only. MONEY-03's field-regression
> validation (the eval/integration two-layer split, snapshot/loop-guard tests, fixtures 16–18)
> moved to Phase 7.5 — see `.planning/phases/07.5-clarification-reply-field-regression/`. This
> doc covers only the two pure-function fixes, all unit-level.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (run via `uv run pytest`) |
| **Config file** | none found — pytest auto-discovers `tests/` |
| **Quick run command** | `uv run pytest tests/test_validate.py tests/test_reconcile.py -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~30 seconds (all unit) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_validate.py tests/test_reconcile.py tests/test_eval_wiring.py -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite green
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

> All Phase 7 behaviors are unit-level (pure-function fixes — no DB, no state machine).

| Requirement | Behavior | Threat Ref | Test Type | Automated Command | File Exists | Status |
|-------------|----------|------------|-----------|-------------------|-------------|--------|
| MONEY-01 | Hourly + `hours_regular=0`, all other hours None/0 → `request_clarification` (never $0 stub) | — | unit | `uv run pytest tests/test_validate.py -k "zero_hours" -x` | ✅ extend | ⬜ pending |
| MONEY-01 | `hours_regular=0` + `hours_holiday=8` (partial week) → NOT gated (D-03 edge) | — | unit | `uv run pytest tests/test_validate.py -k "partial_week" -x` | ✅ extend | ⬜ pending |
| MONEY-01 | Salaried + no hours → NOT gated (D-03: never reaches gate) | — | unit | `uv run pytest tests/test_validate.py -k "salaried" -x` | ✅ extend | ⬜ pending |
| MONEY-01 | D-25 predicate-consistency: `OT 2→0` gates identically to `OT 2→absent` | — | unit | `uv run pytest tests/test_validate.py -k "predicate_consistency" -x` | ✅ extend | ⬜ pending |
| MONEY-02 | NFD "José" matches NFC "José" in roster via `_norm` → same `matched_employee_id` (D-07) | — | unit | `uv run pytest tests/test_reconcile.py -k "nfd" -x` | ✅ extend | ⬜ pending |
| MONEY-02 | `run_eval.py:_normalize` NFC-normalizes (imported from `_norm`) — eval scorer parity (C-4) | — | unit | `uv run pytest tests/test_eval_wiring.py -k "nfd" -x` | ✅ extend | ⬜ pending |
| (scaffold) | `ValidationIssue(issue_type="field_regression")` constructs; `FieldDrop` constructs with `extra="forbid"` — forward-compat for Phase 7.5, no behavior | V5 | unit | `uv run pytest tests/test_models_contracts.py -q` | ✅ extend | ⬜ pending |

*Note on the `unknown_pay_type` edge (D-03): `Employee.pay_type` is a non-nullable `Literal["hourly","salary"]` and `ExtractedEmployee` has no `pay_type` field, so `Employee(pay_type=None)` is not constructible. The "uncertain pay_type" fail-safe is handled upstream by `decide.py` (an unresolved employee never reaches the hourly gate). No Phase-7 test constructs `pay_type=None`; the branch is documented as structurally handled rather than unit-tested here.*

---

## Wave 0 Requirements

All target test files already EXIST — extend them, don't create:
- [ ] `tests/test_validate.py` — MONEY-01 tests (zero-hours, partial-week, salaried-not-gated, predicate-consistency)
- [ ] `tests/test_reconcile.py` — MONEY-02 NFD test
- [ ] `tests/test_eval_wiring.py` — `run_eval.py:_normalize` NFC parity (C-4)
- [ ] `tests/test_models_contracts.py` — `field_regression` Literal + `FieldDrop` construction tests (forward-compat scaffolding)

*No new test files in Phase 7. (`test_decide.py` and `test_resume_pipeline.py` are Phase 7.5.)*

---

## Manual-Only Verifications

*None — both Phase 7 behaviors have automated unit verification.* (The field-regression email-copy manual check moved to Phase 7.5.)

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all referenced test files (all exist — extend)
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

*`wave_0_complete` stays `false` until the RED test scaffolds are written in Wave 1 of execution.*

**Approval:** approved 2026-06-27 (re-scoped to MONEY-01/02)
