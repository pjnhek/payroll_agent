---
phase: 03-harden-the-calc
reviewed: 2026-06-22T00:00:00Z
depth: deep
files_reviewed: 9
files_reviewed_list:
  - app/models/contracts.py
  - app/pipeline/calculate.py
  - app/pipeline/federal_withholding.py
  - app/pipeline/tax_tables_2026.py
  - tests/test_calculate.py
  - tests/test_federal_withholding.py
  - tests/test_persistence.py
  - tests/test_tax_tables_2026.py
  - README.md
findings:
  critical: 0
  warning: 4
  info: 4
  total: 8
status: issues_found
---

# Phase 3: Code Review Report (Round 2)

**Reviewed:** 2026-06-22
**Depth:** deep
**Files Reviewed:** 9
**Status:** issues_found

## Summary

This is round 2 of the Phase 3 "harden-the-calc" review — the full-fidelity IRS Pub 15-T
2026 federal-withholding engine, the highest-bug-risk money-moving unit in the repo.

The round-1 fixes are sound and verified against new evidence:

- **No regressions from round-1 fixes.** The `_to_decimal()` float-reject, the
  `_raise_if_reconciliation_drift()` named-exception backstop (no bare `assert`), the
  ROUND_HALF_UP `_money()` rounding, the `/2080` frequency-independent leave-pay formula,
  the FICA-on-gross vs federal-on-(gross − 401k) split, the `head_of_household` ValueError
  guard, the `$0` floors on line_1i / line_3c, and the MFS-aliases-Single routing are all
  correct and well-tested. The full suite passes (99 passed, 1 skip, 1 xfail).
- **The disputed round-1 bracket boundary ($328,350 / base $96,489.63) is NOT re-raised.**
  No new authoritative evidence contradicts the verified transcription; the continuity
  smoke-test's sub-dollar drift is a real IRS artifact, not a bug. The intentional skip
  (Thomas Bergmann over-ceiling) and strict-xfail (MFJ Standard wage-bracket independence
  gap) are honest, documented coverage gaps — not defects.

**However**, several genuine correctness/robustness gaps remain, none rising to BLOCKER
because they are either conservative-in-direction (over-flagging) or guarded by upstream
typing. The two highest-value findings are the silent `bool`-as-hours coercion (WR-01)
and the silent-drop of unknown hours keys (WR-02) — both undermine the stated
"a programming error must fail loudly, never silently coerce" invariant the round-1
`_to_decimal()` work explicitly set out to enforce.

No structural-findings substrate was supplied for this round, so all findings below are
narrative (direct-read).

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: `_to_decimal()` silently accepts `bool` as an hours value (`True` → 1 hour)

**File:** `app/pipeline/calculate.py:54-74`
**Issue:** `_to_decimal()` was added in round 1 to enforce "Decimal everywhere, never
float — a float is a programming error, raise loudly rather than silently coercing." It
rejects `float` but **not `bool`**. Because `bool` is a subclass of `int`,
`isinstance(True, float)` is `False`, so a stray boolean sails through to
`Decimal(value)`: `Decimal(True) == Decimal("1")`, `Decimal(False) == Decimal("0")`.
A caller bug that passes `hours_regular=True` (e.g. a truthiness mistake, or a
mis-deserialized JSON `true`) is silently treated as **1 hour of pay** instead of
raising — exactly the silent-coercion failure mode the function's docstring promises to
prevent. This contradicts the function's own stated contract ("we raise loudly rather
than silently coercing... A float is a programming error").
**Fix:**
```python
if isinstance(value, bool):
    raise TypeError(
        f"hours value must not be bool (D-05: Decimal everywhere): got {value!r}. "
        "Pass an int, str, or Decimal."
    )
if isinstance(value, float):
    ...
```
(Place the `bool` check *before* the `float`/`int` paths since `bool` ⊂ `int`.)

### WR-02: `_resolved_hours()` silently drops unknown/misspelled hours keys

**File:** `app/pipeline/calculate.py:77-86`
**Issue:** `_resolved_hours()` reads only the five known keys via `resolved.get(f)`. Any
extra or misspelled key in the input dict — e.g. `hours_regualr` (typo),
`hours_overtimes`, or a stray `overtime` — is **silently ignored**, producing
`Decimal('0')` for the intended field with no error. `calculate()` takes a raw `dict`
(not a Pydantic model with `extra="forbid"`), so this is the only line that can catch a
malformed hours payload, and it doesn't. A typo in an upstream caller or eval fixture
would silently zero-out an employee's regular pay and produce a wrong (but
internally-consistent, so reconciliation-passing) paystub. Given the whole module's
thesis is "never silently produce a wrong money number," an unknown-key check is
warranted at this seam.
**Fix:**
```python
def _resolved_hours(resolved: dict) -> dict[str, Decimal]:
    fields = ("hours_regular", "hours_overtime", "hours_vacation", "hours_sick", "hours_holiday")
    unknown = set(resolved) - set(fields)
    if unknown:
        raise ValueError(f"Unknown hours key(s): {sorted(unknown)}. Expected only {fields}.")
    return {f: _to_decimal(resolved.get(f)) for f in fields}
```

### WR-03: Additional-Medicare flag hardcodes $200k for ALL filing statuses (MFJ threshold is $250k)

**File:** `app/pipeline/calculate.py:220-221`
**Issue:** `_ADDITIONAL_MEDICARE_THRESHOLD = Decimal("200000")` is applied regardless of
filing status. The README (`README.md:28-29`) and the IRS itself state the Additional
Medicare 0.9% surtax threshold is **$200,000 (single/MFS)** but **$250,000 (MFJ)** /
$125,000 (MFS). The flag therefore fires for an MFJ employee between $200k–$250k of
proxy Medicare wages where the surtax does **not** actually apply. Because the flag only
*disclaims* a non-modeled feature (it withholds nothing), this is conservative
(over-flagging, not under-withholding) and so not a BLOCKER — but it is an internal
inconsistency: the code's trigger contradicts the documented threshold semantics in the
same repo. At minimum the flat threshold should be documented as deliberately
filing-status-agnostic, or made status-aware.
**Fix:** make the threshold status-aware, mirroring the documented values:
```python
_ADDL_MEDICARE_THRESHOLDS = {
    "single": Decimal("200000"),
    "married_separately": Decimal("125000"),
    "married_jointly": Decimal("250000"),
}
threshold = _ADDL_MEDICARE_THRESHOLDS[employee.filing_status]
additional_medicare_not_modeled = (employee.ytd_ss_wages + gross) > threshold
```
…or add an explicit comment that $200k is an intentional conservative lower bound for all
statuses and update the README to match.

### WR-04: `BracketRow.upper` is carried on every row but never read — silent staleness risk

**File:** `app/pipeline/tax_tables_2026.py:24-39, 48-138`; `app/pipeline/federal_withholding.py:45-55`
**Issue:** `BracketRow.upper` is transcribed for all 48 rows but `_find_bracket()` uses
only `row.lower` (it scans in reverse for the first `annual_wage >= row.lower`). The
`upper` column is pure dead data in the calc path. This is a maintenance hazard: an
`upper` value can silently drift out of sync with the *next row's* `lower` (the real
boundary) with no test or runtime path detecting it, giving a false sense that the
boundaries are validated. The continuity smoke-test only checks `base` against `lower`,
not `upper` vs the next `lower`. Either drop the field or add a structural test asserting
`row[i].upper == row[i+1].lower` for every non-top row so the unused column can't rot.
**Fix:** add a guard test (preferred over deletion, since `upper` documents the table):
```python
def test_bracket_upper_ties_to_next_lower() -> None:
    for table in (STANDARD_BRACKETS, STEP2_BRACKETS):
        for status, rows in table.items():
            for i in range(len(rows) - 1):
                assert rows[i].upper == rows[i + 1].lower, (status, i)
            assert rows[-1].upper is None
```

## Info

### IN-01: Unreachable HoH table data (`_HOH_STANDARD`, `_HOH_STEP2`, three HoH dict entries)

**File:** `app/pipeline/tax_tables_2026.py:72-82, 92, 128-138, 146, 169`
**Issue:** `_HOH_STANDARD`, `_HOH_STEP2`, and the `"head_of_household"` keys in all three
dicts are dead data. `Employee.filing_status` is `Literal["single", "married_jointly",
"married_separately"]` (cannot be HoH), and `federal_withholding_2026()` raises
`ValueError` on any non-supported status *before* any table lookup. So these ~18 rows can
never be reached through any code path. The inline comments label them "out of scope /
listed for completeness," which is a reasonable transcription-completeness decision, but
they are untested numbers presented as authoritative — if ever wired up (the ValueError
message even instructs "Add HoH table mapping before enabling this path") they would ship
unverified. Note also `test_bracket_base_continuity_smoke` *does* exercise these HoH rows
(it iterates all dict values), so they are at least continuity-checked, but never golden-
or wage-bracket-cross-checked.
**Fix:** either keep with an explicit `# UNTESTED — not cross-checked against IRS golden
values; verify before enabling` marker, or move the HoH tables to a clearly-marked
`_UNVERIFIED_FUTURE` section so a future implementer knows they need independent
verification, not just a dict-key wiring.

### IN-02: Duplicated `_money()` helper across two modules (documented, but unguarded for drift)

**File:** `app/pipeline/calculate.py:41-51` and `app/pipeline/federal_withholding.py:33-42`
**Issue:** `_money()` is intentionally duplicated (documented round-1 decision for
independent importability — acknowledged, not re-litigated). The risk is drift: the two
copies must stay byte-identical in rounding mode. There is no test asserting the two
helpers produce identical output, so a future edit to one (e.g. switching one to
ROUND_HALF_EVEN) would not be caught. Given DRY is a stated project value and this is a
correctness-relevant helper, a one-line equivalence test would lock the duplication.
**Fix:**
```python
def test_money_helpers_agree() -> None:
    from app.pipeline.calculate import _money as m1
    from app.pipeline.federal_withholding import _money as m2
    for v in ["1.005", "2.675", "0.125", "-1.005"]:
        assert m1(Decimal(v)) == m2(Decimal(v))
```

### IN-03: `_find_bracket()` zero-bracket fallback is documented as unreachable but never asserted

**File:** `app/pipeline/federal_withholding.py:45-55`
**Issue:** `_find_bracket()` ends with `return brackets[0]  # should never trigger`. This
branch is genuinely unreachable for all shipped tables (every first row has `lower == 0`,
and `line_1i` floors at `0`, so `annual_wage >= 0 >= brackets[0].lower` always matches on
the first reverse-scan hit). It is dead-but-defensive. No test pins the invariant that
makes it dead (first row `lower == 0`). If a future table edit set the first row's `lower`
to a non-zero value, the fallback would silently return the wrong (zero-rate) row for
sub-threshold wages instead of erroring. The existing
`test_*_first_bracket_lower_is_zero` tests cover Single/MFJ standard+step2 but not the
aliased MFS or (untested) HoH first rows — close enough, but the dead branch's safety
contract is implicit.
**Fix:** none required (defensive default is fine); optionally tighten the comment to
state the invariant the dead branch relies on, or `raise` instead of returning
`brackets[0]` so a future broken table fails loudly rather than under-withholding.

### IN-04: Redundant final `gross = _money(gross)` after both branches already quantize

**File:** `app/pipeline/calculate.py:179, 183`
**Issue:** The salaried branch sets `gross = _money(period_salary + leave_pay)` at line
179, then line 183 re-applies `gross = _money(gross)`. The inline comment (IN-01 in the
source) explains line 183 is "the single rounding point for the HOURLY branch" — true,
the hourly branch's `gross` is *not* pre-rounded — but the comment also makes the
double-`_money()` on the salaried path look intentional/load-bearing when it is a no-op
(`_money(_money(x)) == _money(x)`). It is harmless but slightly misleading: a reader may
think the salaried branch needs it. Consider rounding once per branch (hourly branch wraps
its own `gross` in `_money()`), removing the shared trailing line, to make each branch's
single rounding point obvious.
**Fix:** wrap the hourly branch result directly —
`gross = _money(rate * straight + rate * Decimal("1.5") * hours["hours_overtime"])` — and
delete the trailing `gross = _money(gross)` line, so neither branch double-rounds.

---

## Round 2 — Disposition (orchestrator, 2026-06-22)

All 8 findings verified and addressed. No blockers; no regressions from round 1.

| ID | Verdict | Action taken |
|----|---------|--------------|
| **WR-01** | **VALID** | `_to_decimal()` now rejects `bool` (checked before float, since bool ⊂ int) — `hours_regular=True` raises `TypeError` instead of silently becoming 1 hour. Regression test `test_bool_hours_rejected`. |
| **WR-02** | **VALID** | `_resolved_hours()` now rejects unknown/misspelled keys (`ValueError`) — a `hours_regualr` typo can no longer silently zero a pay field. Regression test `test_unknown_hours_key_rejected`. |
| **WR-03** | **VALID** | Additional-Medicare flag is now filing-status-aware (`$200k single / $250k MFJ / $125k MFS`) via `_ADDITIONAL_MEDICARE_THRESHOLDS`, matching the README. README updated to the per-status wording. Regression test `test_additional_medicare_threshold_is_status_aware`. |
| **WR-04** | **VALID** | Added `test_bracket_upper_ties_to_next_lower` — pins `row[i].upper == row[i+1].lower` (and top `upper is None`) so the otherwise-unused `upper` column can't rot. |
| **IN-01** | **VALID** | HoH tables (`_HOH_STANDARD`, `_HOH_STEP2`) marked `# UNTESTED — verify against live PDF before enabling`. |
| **IN-02** | **VALID** | Added `test_money_helpers_agree` — locks the two intentionally-duplicated `_money()` helpers to identical rounding so drift is caught. |
| **IN-03** | **VALID (no behavior change needed)** | Tightened the `_find_bracket()` fallback comment to state the first-row-lower-is-zero invariant the dead branch relies on. |
| **IN-04** | **VALID** | Each branch now rounds `gross` exactly once (hourly branch wraps its own result; trailing shared `_money(gross)` removed) — no more misleading double-`_money()`. |

**Net:** 4 warnings + 4 info all addressed; 6 new regression/guard tests. Full suite: 305 passed, 13 skipped, 1 xfailed, 0 failed. N1 gate passes.

---

_Reviewed: 2026-06-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
