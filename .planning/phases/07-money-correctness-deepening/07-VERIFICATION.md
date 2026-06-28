---
phase: 07-money-correctness-deepening
verified: 2026-06-28T00:00:00Z
status: passed
score: 7/7 must-haves verified
overrides_applied: 0
---

# Phase 7: Money-Correctness Deepening — Verification Report

**Phase Goal:** The core thesis — "never silently pays wrong" — holds against two messy-input paths in the pure-function judgment layer: an explicit-zero-hours submission and a Unicode-form mismatch on a roster name.

**Verified:** 2026-06-28
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | An hourly employee with hours_regular=0 (no other hours) gates to request_clarification instead of producing a $0 paystub — the `any_hours` check treats explicit 0 as missing for hourly | VERIFIED | `_is_paid(v)` at `validate.py:38-45` returns `v is not None and v > 0`; used in `any_hours` generator at line 96-98; `test_zero_hours_hourly_gates` PASSES |
| 2 | A failing test proves the old "is not None" path no longer ships a $0 stub | VERIFIED | `test_zero_hours_hourly_gates` (test_validate.py:321) asserts issues non-empty and issue_type="missing"; PASSES in live run |
| 3 | Two visually-identical names in different Unicode normalization forms resolve as a match — `_norm` applies NFC before casefold | VERIFIED | `_norm` at `reconcile_names.py:34-44` applies double NFC: `NFC(casefold(NFC(s)))`; `import unicodedata` present at line 29 |
| 4 | Test asserts the previously-failing NFD case now resolves to the same employee | VERIFIED | `test_nfd_name_resolves_same_as_nfc` (test_reconcile.py:241) PASSES; asserts `resolved=True` and correct `matched_employee_id` |
| 5 | `_is_paid` shared predicate exists at module scope in validate.py | VERIFIED | `def _is_paid(v: Decimal | None) -> bool` at validate.py:38; `from decimal import Decimal` at line 24; used in `any_hours` at line 97 |
| 6 | `ValidationIssue.issue_type` Literal includes "field_regression" (forward-compat scaffolding) | VERIFIED | `roster.py:219` — `Literal["missing", "out_of_bounds", "non_numeric", "field_regression"]`; docstring documents it as Phase 7.5 no-op scaffold |
| 7 | `FieldDrop` Pydantic model exists in contracts.py with correct fields and extra="forbid" (forward-compat scaffolding) | VERIFIED | `contracts.py:124-146` — `class FieldDrop(BaseModel)` with `ConfigDict(extra="forbid")`, fields `employee_id: UUID`, `field: str`, `original_value: Decimal`, `resumed_value: Decimal | None` |

**Score:** 7/7 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/pipeline/validate.py` | `_is_paid` predicate at module scope + `any_hours` fixed | VERIFIED | `def _is_paid` at line 38; `any_hours = any(_is_paid(getattr(emp, f)) for f in _HOURS_FIELDS)` at lines 96-98 |
| `app/pipeline/reconcile_names.py` | NFC-hardened `_norm` using double-NFC form | VERIFIED | `import unicodedata` at line 29; `_norm` body is `NFC(casefold(NFC(s)))` with whitespace-normalize; 2 `unicodedata.normalize` calls (lines 41, 43) |
| `eval/run_eval.py` | `_normalize` is import alias of `_norm`, no local def | VERIFIED | Line 33: `from app.pipeline.reconcile_names import reconcile_names, _norm as _normalize`; no `def _normalize` anywhere in the file |
| `app/models/roster.py` | `ValidationIssue.issue_type` Literal widened | VERIFIED | Line 219: `Literal["missing", "out_of_bounds", "non_numeric", "field_regression"]` |
| `app/models/contracts.py` | `FieldDrop` forward-compat model | VERIFIED | Lines 124-146: `class FieldDrop(BaseModel)` with `extra="forbid"`, correct field types |
| `tests/test_validate.py` | 4 MONEY-01 tests (zero_hours_hourly_gates, partial_week_not_gated, predicate_consistency, salaried_not_gated) | VERIFIED | All 4 tests present at lines 321-436; all PASS after Wave 2 fix |
| `tests/test_reconcile.py` | MONEY-02 NFD test (nfd_name_resolves_same_as_nfc) | VERIFIED | Test at line 241; PASSES |
| `tests/test_eval_wiring.py` | C-4 parity test (eval_normalize_nfd_matches_nfc) | VERIFIED | Test at line 130; PASSES |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `validate.py:_is_paid` | `validate.py:any_hours` | replaces `is not None` predicate | VERIFIED | `any(_is_paid(getattr(emp, f)) for f in _HOURS_FIELDS)` at line 96-98; `_is_paid` occurs 2 times in file (definition + usage) |
| `reconcile_names.py:_norm` | `eval/run_eval.py:_normalize` | direct import alias `_norm as _normalize` | VERIFIED | `from app.pipeline.reconcile_names import reconcile_names, _norm as _normalize` at run_eval.py:33; no local `def _normalize` |
| `roster.py:ValidationIssue.issue_type` | Phase 7.5 `decide.py` (forward-compat) | Literal must include `field_regression` before Phase 7.5 decide rule can reference it | VERIFIED | `"field_regression"` present in Literal at roster.py:219; no Phase 7 code emits it (docstring-only references) |

---

### Data-Flow Trace (Level 4)

Not applicable. All modified artifacts are pure functions and Pydantic model definitions — no rendering, no DB, no UI. No hollow data-flow risk.

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| MONEY-01: zero-hours hourly gates | `uv run pytest tests/test_validate.py -k "zero_hours"` | 1 passed | PASS |
| MONEY-01: predicate consistency (0 == None for gate) | `uv run pytest tests/test_validate.py -k "predicate_consistency"` | 1 passed | PASS |
| MONEY-01: D-03 partial week not gated | `uv run pytest tests/test_validate.py -k "partial_week"` | 1 passed | PASS |
| MONEY-01: salaried regression guard | `uv run pytest tests/test_validate.py -k "salaried_not_gated"` | 1 passed | PASS |
| MONEY-02: NFD resolves same as NFC | `uv run pytest tests/test_reconcile.py -k "nfd"` | 1 passed | PASS |
| C-4: eval _normalize parity | `uv run pytest tests/test_eval_wiring.py -k "nfd"` | 1 passed | PASS |
| Full suite (no regressions) | `uv run pytest -q` | 466 passed, 16 skipped | PASS |

---

### Probe Execution

No probes declared for this phase. Spot-checks above serve as empirical verification.

---

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| MONEY-01 | 07-01-PLAN.md, 07-02-PLAN.md | Hourly employee with hours_regular=0 gates to request_clarification, never silently produces $0 paystub | SATISFIED | `_is_paid` predicate in validate.py; `test_zero_hours_hourly_gates` and `test_predicate_consistency` both PASS |
| MONEY-02 | 07-01-PLAN.md, 07-02-PLAN.md | Name reconciliation NFC-normalizes before casefold so NFD/NFC visually-identical names resolve as a match | SATISFIED | Double-NFC `_norm` in reconcile_names.py; `test_nfd_name_resolves_same_as_nfc` PASSES |
| MONEY-03 | NOT in this phase (per scope override 2026-06-27) | Clarification-reply field-regression detection | DEFERRED to Phase 7.5 | Scope override documented in CONTEXT.md and plan frontmatter; forward-compat scaffolding (ValidationIssue Literal + FieldDrop) landed as inert no-ops |

No orphaned requirements: REQUIREMENTS.md maps MONEY-01 and MONEY-02 to Phase 7 only. MONEY-03 is explicitly mapped to Phase 7.5.

---

### Anti-Patterns Found

Scanned all 5 modified files (`app/pipeline/validate.py`, `app/pipeline/reconcile_names.py`, `eval/run_eval.py`, `app/models/roster.py`, `app/models/contracts.py`) and 3 test files.

| File | Pattern | Severity | Assessment |
|------|---------|----------|------------|
| `validate.py:42`, `contracts.py:138` | `detect_field_regression` in docstring | Info | Docstring-only, not an import or call. Intentional forward-reference to Phase 7.5. Not a stub. |

**Debt marker gate:** Zero `TBD`, `FIXME`, or `XXX` markers found in any file modified by this phase. Gate PASSES.

**Scope fence check:** `class RawFieldDrop` absent from codebase. `detect_field_regression` appears only in docstrings (2 occurrences), not as an import or function definition. `tests/test_resume_pipeline.py` does not exist. Scope fence HOLDS.

---

### Human Verification Required

None. All success criteria are verifiable programmatically via the test suite. The phase delivers pure-function logic changes and Pydantic model definitions with no UI, no external service integration, and no real-time behavior.

---

### Gaps Summary

No gaps. All 7 must-haves are verified. The full test suite runs clean at 466 passed, 16 skipped, matching the claimed count. The scope fence is intact — no MONEY-03 code leaked into Phase 7.

---

_Verified: 2026-06-28_
_Verifier: Claude (gsd-verifier)_
