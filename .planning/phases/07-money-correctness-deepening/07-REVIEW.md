---
phase: 07-money-correctness-deepening
reviewed: 2026-06-27T20:15:00Z
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
  warning: 1
  info: 2
  total: 3
status: issues_found
---

# Phase 07: Code Review Report

**Reviewed:** 2026-06-27T20:15:00Z
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Independent adversarial re-run of the Phase 07 (money-correctness-deepening) diff
(`4d9e4a06^..HEAD`). Every fix was verified **empirically** — by exercising the
predicate/normalizer boundaries directly, tracing the zero-hours gate end-to-end
through `validate → decide → final_action`, and running the eval regression gate —
not by trusting the prior review or the green test names.

**The two money-moving fixes are correct. No blockers.**

- **MONEY-01 (`_is_paid`)** — correct end-to-end. A zero-hours hourly employee
  (`hours_regular=Decimal('0')`, others None/0) now gates to
  `request_clarification`; a genuine partial week (`hours_holiday=8`) still
  processes; a salaried employee with zero hours is never gated. The OT guard does
  not double-fire on these cases. `Decimal('NaN')`/`Infinity` cannot reach the
  predicate — the `ExtractedEmployee` contract (`Decimal | None`, `ge=0`) rejects
  them at the parse boundary, so `v > 0` can never raise `InvalidOperation` in
  production. The predicate is safe given its only call site.
- **MONEY-02 (`_norm` NFC + eval `_normalize` aliasing)** — NFD/NFC parity holds;
  the alias is a true identity (`eval.run_eval._normalize is reconcile_names._norm`
  → `True`), so C-4 parity is structural and cannot drift. `_norm` is idempotent.
  `uv run python eval/run_eval.py --check` passes, confirming the alias swap shifted
  **zero** committed metrics (old casefold-only `_normalize` and the new NFC form
  are identical on the ASCII fixtures).

**Gates run, not assumed:** the 3 reviewed test files → 29 passed; full suite →
466 passed, 16 skipped; `ruff check` on all changed source → clean; eval `--check`
→ passed.

The forward-compat scaffolding (`ValidationIssue` widened Literal +
`contracts.FieldDrop`) is correctly inert: the Literal stays closed (rejects bogus
values), `field_regression` constructs, nothing in Phase 7 emits either. Per scope,
its non-use and the absence of `detect_field_regression`/MONEY-03 are NOT flagged.

**Divergence from the prior review (0 BLOCKER / 3 WARN / 2 INFO).** This pass lands
at 1 WARN / 2 INFO. Specifically:
- Prior **WR-02** (docstring names a future `detect_field_regression` call site) is
  **dropped** — the brief explicitly designates `detect_field_regression` docstring
  mentions as intentional forward-compat references, out of scope.
- Prior **WR-03** (eval dict-keying collision) is **downgraded out of the warning
  tier**: it is pre-existing (the prior review itself says so), and the `_norm`
  change is empirically behavior-preserving on the fixtures (`--check` clean), so it
  is not a Phase 07 defect. Noted inline under IN-02 caveats for completeness only.
- Prior **IN-01** is **strengthened into WR-adjacent IN-01**: the prior review called
  the double-NFC rationale "weakly demonstrable." A full-Unicode scan proves the
  *inner* (pre-casefold) NFC is dead and the docstring's rationale for the *double*
  NFC is backwards — only the post-casefold NFC is load-bearing.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: `_is_paid` shipped as "the shared predicate" but the sibling `ot_missing` test in the same function was left hand-rolled

**File:** `app/pipeline/validate.py:38-45` (`_is_paid`) and `app/pipeline/validate.py:125` (`ot_missing`)

**Issue:** The headline of MONEY-01 / D-09 is a *shared* "is this hours value paid?"
predicate. `_is_paid(v) -> v is not None and v > 0` was added and correctly wired
into `any_hours`. But the very next rule, in the same `validate()` function,
re-derives the identical concept by hand:

```python
ot = emp.hours_overtime
ot_missing = ot is None or ot == 0   # line 125
```

This is the exact "absent OR zero" test `_is_paid` was created to own, expressed a
second time, a dozen lines apart. Per the project DRY mandate ("flag repetition
aggressively; duplicated logic must be consolidated"), this is a duplicated
money-gate predicate — the kind the phase set out to unify. Phase 7.5 is documented
to add a *third* consumer, so the divergence will widen.

**Trap a fixer must respect:** `ot_missing` is NOT a blind swap for `not _is_paid(ot)`.
They diverge on negatives — verified empirically:

| ot value | `ot is None or ot == 0` | `not _is_paid(ot)` |
|----------|--------------------------|---------------------|
| `None`   | True                     | True                |
| `0`      | True                     | True                |
| `-1`     | **False**                | **True**            |
| `5`      | False                    | False               |

A negative is unreachable in production (`hours_overtime` is `ge=0`), so the two are
behaviorally identical on every valid input — which is exactly why consolidation is
safe **and** why it must be done deliberately, with the rationale retained.

**Fix:**

```python
ot = emp.hours_overtime
ot_missing = not _is_paid(ot)  # D-05/D-09: absent or zero == "no paid OT" (shared predicate)
```

Negative OT is impossible (`ge=0` contract), so this is behavior-preserving on all
valid inputs while collapsing the duplicated predicate to a single definition and
giving the phase a genuine in-phase second call site.

## Info

### IN-01: The inner (pre-casefold) NFC in `_norm` is provably dead code; the docstring's rationale for the *double* NFC is empirically backwards

**File:** `app/pipeline/reconcile_names.py:34-44`

**Issue:** `_norm` computes `NFC(casefold(NFC(s)))` and justifies it: *"The double
NFC is deliberate: casefold can de-normalize its output on some Unicode sequences."*
That is correct **only for the outer NFC** (applied *after* casefold). The **inner**
NFC (applied *before* casefold) is a no-op, proven empirically:

- Full scan of all 1,114,112 Unicode code points: `NFC(casefold(NFC(ch)))` equals
  `NFC(casefold(ch))` for **every** code point — 0 divergences.
- Multi-combining-mark sequences (base + permuted combining marks, where pre-casefold
  reordering could in principle matter): **0** divergences.

So the load-bearing normalization is `NFC(casefold(s))`. The first
`unicodedata.normalize("NFC", name)` never changes the result — redundant
computation, and the docstring attributes the de-normalization fix to a *double* NFC
when a single *post-casefold* NFC is what actually handles it. A maintainer reading
this will preserve the dead call indefinitely. Behavior is correct; this is a
dead-computation + incorrect-explanation issue only — no functional bug, no score
impact (`--check` clean).

**Fix:** Drop the inner NFC and correct the comment to the one call that matters:

```python
def _norm(name: str) -> str:
    """Whitespace-normalize + NFC(casefold(s)) for Unicode-safe comparison (D-05).

    NFC is applied AFTER casefold: casefold can emit a non-NFC sequence for some
    inputs, so re-normalizing afterward makes NFD/NFC submissions compare equal.
    NFC (not NFKC) is deliberate -- NFKC over-folds compatibility chars in names (D-06).
    """
    return " ".join(unicodedata.normalize("NFC", name.casefold()).split())
```

If the inner NFC is kept as belt-and-suspenders, keep it but fix the docstring to
stop claiming the *double* NFC is what handles casefold de-normalization — it is the
post-casefold NFC alone.

### IN-02: `FieldDrop` money fields lack the `ge=0` gate every other money field carries — forward-compat scaffold, out of Phase 7 scope, recorded for Phase 7.5

**File:** `app/models/contracts.py:143-146`

**Issue:** `FieldDrop.original_value` and `FieldDrop.resumed_value` are bare
`Decimal` / `Decimal | None` with no `ge=0`, so the model accepts
`original_value=Decimal('-999')`. Every other monetary/hours field in the codebase
(`ExtractedEmployee.hours_*`, `Employee.*`) closes that gate. Since `FieldDrop`
carries hours-field values destined for the calc path in Phase 7.5, the missing
constraint is a latent trap for whoever builds `detect_field_regression`.

**Per the explicit review scope this is NOT a Phase 7 defect** — `FieldDrop` is
intentionally inert scaffolding with zero construction sites, so nothing can produce
a bad value yet. Recorded so the constraint is added *when* Phase 7.5 wires it up
(`original_value = Field(ge=0)`, `resumed_value = Field(default=..., ge=0)`).

**Also noted here (not a Phase 07 finding):** the eval name-keying dict
comprehensions (`eval/run_eval.py:191-195, 233`) silently drop a within-fixture
duplicate-normalized employee. This is **pre-existing** (the old `_normalize` already
keyed on a casefold normalizer) and the current fixtures are collision-free
(`--check` clean), so it is out of Phase 07 scope. If revisited later, prefer
building those dicts with an explicit collision guard that raises rather than
overwriting, converting a silent mis-score into a visible failure.

---

_Reviewed: 2026-06-27T20:15:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
