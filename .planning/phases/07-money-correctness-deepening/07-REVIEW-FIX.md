---
phase: 07-money-correctness-deepening
fixed_at: 2026-06-28T03:26:12Z
review_path: .planning/phases/07-money-correctness-deepening/07-REVIEW.md
iteration: 2
findings_in_scope: 3
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 07: Code Review Fix Report

**Fixed at:** 2026-06-28T03:26:12Z
**Source review:** .planning/phases/07-money-correctness-deepening/07-REVIEW.md
**Iteration:** 2

**Summary:**
- Findings in scope (`all` — Critical + Warning + Info): 3
- Fixed: 2 (new this pass: IN-01, IN-02)
- Already fixed in iteration 1: 1 (WR-01)
- Skipped: 0

**Scope note:** This run used `fix_scope = all` (the `--all` flag), so the two
Info-tier findings (IN-01, IN-02) — deferred in iteration 1 — are now in scope and
fixed. WR-01 was already applied in iteration 1 (commit `a0c17e6`); it was confirmed
present on disk and NOT re-applied.

## Fixed Issues

### IN-01: The inner (pre-casefold) NFC in `_norm` is provably dead code; the docstring's rationale for the *double* NFC is empirically backwards

**Files modified:** `app/pipeline/reconcile_names.py`
**Commit:** dbcef44
**Applied fix:** Replaced the four-line `_norm` body that computed
`NFC(casefold(NFC(s)))` with the single load-bearing form `NFC(casefold(s))`, and
corrected the docstring.

Before:

```python
def _norm(name: str) -> str:
    """Whitespace-normalize + NFC(casefold(NFC(s))) ... The double NFC is deliberate ..."""
    nfc = unicodedata.normalize("NFC", name)
    casefolded = nfc.casefold()
    renfc = unicodedata.normalize("NFC", casefolded)
    return " ".join(renfc.split())
```

After:

```python
def _norm(name: str) -> str:
    """Whitespace-normalize + NFC(casefold(s)) ... NFC is applied AFTER casefold ..."""
    return " ".join(unicodedata.normalize("NFC", name.casefold()).split())
```

The review PROVED the inner pre-casefold NFC is dead: a full scan of all 1,114,112
Unicode code points plus multi-combining-mark permutations showed
`NFC(casefold(NFC(ch)))` equals `NFC(casefold(ch))` with **zero** divergences. Only
the post-casefold NFC is load-bearing. The change is therefore behavior-identical
across all Unicode while removing the dead computation and correcting the docstring,
which had attributed the de-normalization fix to a *double* NFC rather than to the
single post-casefold NFC that actually handles it.

**Verification performed:**
- Tier 1: re-read modified section — fix present, surrounding code intact,
  `import unicodedata` still used.
- Tier 2: Python AST parse — OK.
- `uv run pytest tests/test_reconcile.py tests/test_eval_wiring.py
  tests/test_models_contracts.py tests/test_validate.py -q` — 67 passed.
- `uv run python eval/run_eval.py --check` — passed: **zero** eval metric drift,
  empirically confirming the change is behavior-preserving on the fixtures.
- `uv run ruff check app/pipeline/reconcile_names.py` — clean.

### IN-02: `FieldDrop` money fields lack the `ge=0` gate every other money field carries

**Files modified:** `app/models/contracts.py`
**Commit:** 08abff9
**Applied fix:** Added the `ge=0` constraint via Pydantic `Field` to both `FieldDrop`
money fields, matching every other monetary/hours field in the codebase
(`ExtractedEmployee.hours_*`, etc.):

```python
original_value: Decimal = Field(ge=0)
resumed_value: Decimal | None = Field(ge=0)
```

`Field` was already imported from pydantic (contracts.py line 20) — no import change
needed.

**Scope rationale:** The review SUGGESTED deferring this to Phase 7.5 because
`FieldDrop` is inert forward-compat scaffolding with zero construction sites in
Phase 7. The user explicitly invoked `--all`, so the constraint is added now. Adding
it is safe and non-breaking: it only tightens validation on a currently-unconstructed
model and cannot affect any existing behavior (no code path constructs `FieldDrop`
yet; no test references it).

**Behavioral equivalence + new guard (verified):** Both fields remain REQUIRED (no
default leaked in — `Field(ge=0)` with no default keeps required-ness). The `ge=0`
constraint applies only to the `Decimal` branch of `Decimal | None`, so the
documented `resumed_value` semantics are preserved:
- `resumed_value=None` (carried_forward) — still accepted.
- `resumed_value=Decimal('0')` (confirmed_dropped) — still accepted.
- `original_value=Decimal('2')` — accepted.
- Negative `original_value` or `resumed_value` — now correctly raises
  `ValidationError`.

**Verification performed:**
- Tier 1: re-read modified section — fix present, surrounding code intact.
- Tier 2: Python AST parse — OK.
- Targeted behavioral check (constructed `FieldDrop` directly): None accepted,
  `Decimal('0')` accepted, valid positives accepted, negatives rejected, both fields
  still required — all 5 assertions passed.
- `uv run pytest tests/test_reconcile.py tests/test_eval_wiring.py
  tests/test_models_contracts.py tests/test_validate.py -q` — 67 passed.
- `uv run ruff check app/models/contracts.py` — clean.

## Already Fixed (Prior Iteration)

### WR-01: `_is_paid` shipped as "the shared predicate" but the sibling `ot_missing` test was left hand-rolled

**Status:** Already fixed in iteration 1 — **not re-applied this pass.**
**Commit:** a0c17e6 (iteration 1)
**Confirmed on disk:** `app/pipeline/validate.py:125` reads
`ot_missing = not _is_paid(ot)  # D-05/D-09: absent or zero == "no paid OT" (shared predicate)`.
The hand-rolled `ot is None or ot == 0` predicate has been consolidated onto the
shared `_is_paid` predicate, giving the phase a genuine in-phase second call site
(satisfying the DRY mandate). Behavior-preserving on all valid inputs (the two forms
diverge only on negatives, which `hours_overtime`'s `ge=0` contract makes
unreachable). No change required in iteration 2.

## Skipped Issues

None — all in-scope findings are resolved (2 fixed this pass, 1 already fixed in
iteration 1).

## Full-Suite Regression Gate

- `uv run pytest -q` — **465 passed, 17 skipped, 0 failed.** Zero regressions.
  The pass/skip split is 465/17 rather than the 466/16 baseline because all 17 skips
  are environment-gated (live-DB tests requiring `DATABASE_URL`/`ALLOW_DB_RESET`,
  and the live-LLM hero test requiring `ALLOW_LIVE_LLM`) and none of those env vars
  are set in the fresh isolated worktree venv. The total test count (482) and the
  zero-failures result are unchanged; this is the same env-dependent split iteration 1
  documented, not a regression from these fixes.
- `uv run python eval/run_eval.py --check` — passed (no metric regression; confirms
  IN-01's `_norm` change shifted zero eval metrics).

---

_Fixed: 2026-06-28T03:26:12Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
