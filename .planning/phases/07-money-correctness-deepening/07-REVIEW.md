---
phase: 07-money-correctness-deepening
reviewed: 2026-06-27T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - app/models/roster.py
  - app/models/contracts.py
  - app/pipeline/validate.py
  - app/pipeline/reconcile_names.py
  - eval/run_eval.py
  - tests/test_validate.py
  - tests/test_reconcile.py
  - tests/test_eval_wiring.py
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: issues_found
---

# Phase 7: Code Review Report

**Reviewed:** 2026-06-27
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Phase 7 delivered two money-moving fixes via TDD (MONEY-01 zero-hours gate, MONEY-02
NFC normalization) plus forward-compat scaffolding for Phase 7.5. I reviewed each
changed source file in context, traced the affected predicates through their call
sites, and exercised the edge cases directly (not just trusting the green suite).

**Both core fixes are correct.** The `_is_paid` predicate correctly collapses
`None` and `Decimal('0')` (and, defensively, negatives) to "absent", and the
`any_hours` rewiring now gates a zero-hours hourly employee to clarification instead
of shipping a silent $0 paystub. The NFC-hardened `_norm` correctly matches NFD/NFC
name forms; I verified the precomposed-vs-combining case resolves identically and
that whitespace-only/empty inputs normalize cleanly. The eval `_normalize`→`_norm`
alias is a genuine DRY improvement: I ran `eval/run_eval.py --check` and it passes,
confirming the normalization change introduces **no silent eval regression**, and the
orchestrator's alias-learning write path imports the same `_norm`, so read/write
normalization can no longer drift.

I verified there are **no BLOCKERS**: no correctness bug, no security issue, no data-
loss path. The forward-compat additions (`FieldDrop`, the `field_regression` Literal
value) are confirmed inert in Phase 7 — defined/declared but never instantiated or
emitted — exactly as the brief states.

The findings below are quality/maintainability issues. The most substantive is a DRY
gap: the phase introduced `_is_paid` as *the* shared "is this hours value paid?"
predicate, but the over-40-no-OT loop in the same function still open-codes the
identical logic (`ot is None or ot == 0`) instead of calling it.

All 29 tests across the three reviewed test files pass.

## Warnings

### WR-01: OT-rule loop duplicates the `_is_paid` predicate it was meant to share

**File:** `app/pipeline/validate.py:125` (also referenced at `:38`, `:97`)
**Issue:** The phase added `_is_paid(v) -> v is not None and v > 0` explicitly as the
*shared* "paid hours" predicate (its docstring even names the zero-hours gate and the
Phase-7.5 call site as its two consumers). But the over-40-no-OT loop, in the same
`validate()` function, re-derives the identical test by hand:

```python
ot = emp.hours_overtime
ot_missing = ot is None or ot == 0  # D-05: explicit zero treated same as absent
```

`ot is None or ot == 0` is exactly `not _is_paid(ot)` over the field's legal domain
(`ge=0` + `None`) — I verified equivalence across `{None, 0, 0.00, 1, 40}`. Two
copies of "zero-or-absent hours means absent" is precisely the duplication the new
predicate exists to eliminate; if the definition of "paid" ever changes (e.g. a
fractional-hours floor), one site will silently drift from the other. This is the
project's stated DRY priority ("flag repetition aggressively").
**Fix:**
```python
ot = emp.hours_overtime
ot_missing = not _is_paid(ot)  # D-05: explicit zero treated same as absent (shared predicate)
```
(Leave the `# D-05` rationale comment; only the predicate changes.)

### WR-02: `_is_paid` docstring asserts a Phase-7.5 call site that does not yet exist

**File:** `app/pipeline/validate.py:41-44`
**Issue:** The docstring states: *"Phase 7.5 detect_field_regression will use this
same predicate as its second call site."* As of Phase 7 there is exactly **one** call
site (`any_hours`, line 97); `detect_field_regression` does not exist (grep confirms
it appears only in docstrings). A reader auditing call sites will look for the second
consumer and not find it. This is a forward-reference in a docstring describing
current behavior, which makes the code's actual coupling harder to reason about.
Note this also undercuts WR-01: the OT loop is, today, the obvious *real* second call
site that the predicate should already serve.
**Fix:** Soften to a forward-looking note rather than a present-tense claim, e.g.
*"Intended to be reused by Phase 7.5's `detect_field_regression` (not yet built)."*
Better still, adopt WR-01 so there genuinely is a second in-phase call site.

### WR-03: Eval name-keying can silently drop a duplicate-normalized employee (pre-existing, widened-surface)

**File:** `eval/run_eval.py:191-195` (and `:233`)
**Issue:** `actual_by_name` / `expected_emps` / `match_by_name` are built as dict
comprehensions keyed on `_normalize(name)`:

```python
actual_by_name = {_normalize(e.submitted_name): e for e in cached_extracted.employees}
```

If two employees in a single fixture normalize to the same key (now *more* likely
since `_norm` collapses NFC/NFD **and** casefold/ligatures together, e.g. `"José"` and
`"JOSÉ"` or an NFD/NFC pair), the later entry silently overwrites the earlier one and
field-accuracy/reconciliation for the dropped employee is scored against the wrong
record — with no error. The extraction precision/recall path correctly uses a
`Counter` (multiset) so it counts duplicates as FP, but the **field-accuracy and
reconciliation** keying paths do not. This collision risk pre-existed the phase (the
old `_normalize` already keyed dicts on a casefold normalizer), so it is not a Phase-7
regression — but the phase's broader normalization equivalence enlarges the set of
names that now collide, so it is worth recording.
**Fix:** Detect collisions explicitly rather than letting dict construction swallow
them, e.g. build with a guard and fail loud on a within-fixture duplicate key:
```python
actual_by_name: dict = {}
for e in cached_extracted.employees:
    k = _normalize(e.submitted_name)
    if k in actual_by_name:
        raise ValueError(f"normalized-name collision in fixture: {k!r}")
    actual_by_name[k] = e
```
(Or score field-accuracy off the same multiset alignment the precision path uses.)
Low urgency given current fixtures are collision-free, but it converts a silent
mis-score into a visible failure.

## Info

### IN-01: `_norm` double-NFC is correct but the rationale is only weakly demonstrable

**File:** `app/pipeline/reconcile_names.py:34-44`
**Issue:** The docstring justifies the outer `NFC(...)` with "casefold can de-normalize
its output on some Unicode sequences." That is true in principle, but the claim is
load-bearing for a money-routing comparison and there is no test that pins a concrete
sequence where `NFC(casefold(x)) != casefold(NFC(x))`. The implementation is the
safe/conservative choice and I am not flagging it as wrong — but a one-line table-driven
test capturing an actual divergent codepoint would lock the invariant the docstring
asserts, in a module the project explicitly wants "the most tested."
**Fix:** Add a small unit test asserting `_norm` stability on a known casefold-
denormalizing input (or, if no such input is found for the names domain, downgrade the
docstring claim to "defense-in-depth — harmless even where casefold is NFC-stable").

### IN-02: `FieldDrop` and the `field_regression` Literal value are dead until Phase 7.5

**File:** `app/models/contracts.py:124-147`, `app/models/roster.py:219`
**Issue:** `FieldDrop` is defined but never constructed/imported anywhere, and the
`field_regression` value is in `ValidationIssue.issue_type`'s Literal but is never
emitted (grep confirms both appear only in their own definitions plus docstrings).
This is **intentional forward-compat scaffolding** per the phase brief and is correctly
documented as a no-op — recorded here only for completeness so a future reader does
not mistake the unused model for an oversight. No action needed in Phase 7; Phase 7.5
should consume both or remove them if the design shifts.
**Fix:** None required this phase. Track that Phase 7.5 either wires these in or
deletes them so the scaffold cannot ossify into permanent dead code.

---

_Reviewed: 2026-06-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
