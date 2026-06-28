---
phase: 07-money-correctness-deepening
fixed_at: 2026-06-28T03:19:00Z
review_path: .planning/phases/07-money-correctness-deepening/07-REVIEW.md
iteration: 1
findings_in_scope: 1
fixed: 1
skipped: 0
status: all_fixed
---

# Phase 07: Code Review Fix Report

**Fixed at:** 2026-06-28T03:19:00Z
**Source review:** .planning/phases/07-money-correctness-deepening/07-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope (critical_warning): 1
- Fixed: 1
- Skipped: 0

**Scope note:** This run used `fix_scope = critical_warning` (no `--all` flag).
Critical findings: 0. Warning findings: 1 (WR-01). The two Info findings
(IN-01, IN-02) are deliberately OUT OF SCOPE for this run and were not touched.

## Fixed Issues

### WR-01: `_is_paid` shipped as "the shared predicate" but the sibling `ot_missing` test in the same function was left hand-rolled

**Files modified:** `app/pipeline/validate.py`
**Commit:** a0c17e6
**Applied fix:** Replaced the hand-rolled OT-absence predicate at line 125

```python
ot_missing = ot is None or ot == 0  # D-05: explicit zero treated same as absent
```

with a call to the shared `_is_paid` predicate:

```python
ot_missing = not _is_paid(ot)  # D-05/D-09: absent or zero == "no paid OT" (shared predicate)
```

This collapses the duplicated "absent OR zero" money-gate predicate onto the
single `_is_paid` definition introduced by MONEY-01, giving the phase a genuine
in-phase second call site and satisfying the project DRY mandate.

**Behavioral equivalence (verified):** `ot_missing` and `not _is_paid(ot)`
diverge only on negative inputs (`-1` → old `False`, new `True`). Negative
`hours_overtime` is unreachable in production: the `ExtractedEmployee` contract
declares `Decimal | None` with `ge=0`, rejecting negatives at the parse
boundary. The change is therefore behavior-preserving on every valid input.

**Verification performed:**
- Tier 1: re-read modified section — fix present, surrounding code intact.
- Tier 2: Python AST parse — OK.
- `uv run pytest tests/test_validate.py -q` — 13 passed (includes the
  over-40-no-OT and MONEY-01 zero-hours gate tests).
- `uv run pytest -q` — 465 passed, 17 skipped, 0 failed (no regressions). The
  pass/skip split differs by 1 from the expected 466/16 due to an
  environment-dependent skip in the fresh worktree venv, not from this change;
  zero tests failed.
- `uv run ruff check app/pipeline/validate.py` — All checks passed.

## Skipped Issues

The following findings were NOT skipped due to error — they are simply out of
scope for the `critical_warning` fix run (Info tier, no `--all` flag).

### IN-01: The inner (pre-casefold) NFC in `_norm` is provably dead code

**File:** `app/pipeline/reconcile_names.py:34-44`
**Reason:** Out of scope — Info-tier finding, `critical_warning` run does not
include Info findings.
**Original issue:** `_norm` computes `NFC(casefold(NFC(s)))`; the inner NFC is a
proven no-op and the docstring's rationale for the *double* NFC is backwards
(only the post-casefold NFC is load-bearing). Dead-computation + incorrect-
explanation only; no functional bug.

### IN-02: `FieldDrop` money fields lack the `ge=0` gate every other money field carries

**File:** `app/models/contracts.py:143-146`
**Reason:** Out of scope — Info-tier finding, `critical_warning` run does not
include Info findings. (Also explicitly recorded in the review as NOT a Phase 7
defect — `FieldDrop` is inert forward-compat scaffolding for Phase 7.5.)
**Original issue:** `FieldDrop.original_value` / `resumed_value` are bare
`Decimal` with no `ge=0` constraint, unlike every other monetary/hours field.
Latent trap for the Phase 7.5 `detect_field_regression` consumer.

---

_Fixed: 2026-06-28T03:19:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
