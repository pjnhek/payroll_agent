---
phase: 15-comment-hygiene-deferred-polish-triage
plan: 04
requirements-completed: [COMM-01, COMM-03]
subsystem: pipeline + models
tags: [comment-hygiene, money-core, docstrings, COMM-01, COMM-03]
requires:
  - app/pipeline/* (existing money-core + stage modules)
  - app/models/* (existing contracts/roster/status)
provides:
  - fourteen comment-clean source files with zero ticket/process references
  - decide.py module docstring stating the no-guess invariant
  - preserved IRS Pub 15-T + SSA external citation URLs
affects:
  - none (text-only sweep; no behavior change)
tech-stack:
  added: []
  patterns:
    - "keep constraint + failure mode, drop the label"
    - "external authoritative citations (IRS/SSA URLs) survive; process history does not"
key-files:
  created: []
  modified:
    - app/pipeline/calculate.py
    - app/pipeline/tax_tables_2026.py
    - app/pipeline/federal_withholding.py
    - app/pipeline/decide.py
    - app/pipeline/validate.py
    - app/pipeline/alias_learning.py
    - app/pipeline/reconcile_names.py
    - app/pipeline/compose_email.py
    - app/pipeline/extract.py
    - app/pipeline/suggest.py
    - app/pipeline/pdf.py
    - app/models/contracts.py
    - app/models/roster.py
    - app/models/status.py
decisions:
  - "decide.py states its no-guess invariant WITHOUT the literal token 'confidence' — an existing source-guard test bans that substring in the module. Guard left untouched."
  - "Two stale comments corrected rather than preserved verbatim (ValidationIssue.field_regression, FieldDrop). Comment-only; no code removed."
metrics:
  duration: ~50m
  completed: 2026-07-13
status: complete
---

# Phase 15 Plan 04: Money-Core & Models Comment Sweep Summary

Swept fourteen files — the money core, the remaining pipeline stages, and `app/models/` — clean of every ticket-ID and project-process reference, while deepening (not trimming) the failure-mode narration that guards the money path.

## What Changed

Comment, docstring, and message-text edits only. No control flow, no numeric constant, no bracket row, no field, no rename.

**Task 1 — money core** (`6fcd45f`): calculate, tax_tables_2026, federal_withholding, decide, validate.
**Task 2 — remaining stages** (`bf31a7f`): alias_learning, reconcile_names, compose_email, extract, suggest, pdf.
**Task 3 — models** (`377641d`): contracts, roster, status.

Every surviving money rule now names the mispay it prevents, per the D-02 full-depth bar. Examples:

- `tax_tables_2026.py` — MFS aliasing the Single table: "Do NOT point married_separately at the MFJ table: the MFJ brackets are roughly twice as wide, so an MFS employee would be withheld at roughly HALF the correct amount."
- `tax_tables_2026.py` — the Step-1 line-1g proxies: they "look like stale numbers and are not"; substituting the real 2026 standard deductions would under-withhold every employee.
- `calculate.py` — salaried leave pay: the period-relative form "OVERPAYS non-weekly schedules badly (semi-monthly → ~4.7x too high; monthly → ~18.8x too high)."
- `alias_learning.py` — the misname guard: the two-fact bind would learn `Dave -> David` from a reply that explicitly *denied* the match, silently misrouting all future payroll.
- `validate.py` — the over-40-no-OT rule: `calculate()` pays OT only when reported explicitly, so a client who lumps OT into regular hours would be silently underpaid.

`decide.py`'s docstring now leads with the thesis: pure code, no model call, no score, collisions always clarify, gate fails closed.

**Preserved:** the IRS Pub 15-T PDF URL (3 occurrences) and SSA wage-base URL in the tax modules — external sources, not process history. All `# noqa:` markers kept, with reason text rewritten in plain English.

## Deviations from Plan

### 1. [Rule 3 - Blocking] `decide.py` docstring collided with an existing source-guard test

**Found during:** Task 2 verification (full suite).
**Issue:** `tests/test_gate.py::test_decide_source_has_no_confidence_or_model_action` asserts `"confidence" not in decide.py.lower()` — a blunt substring scan over the whole file, comments included. The plan's acceptance criterion asked for a "no-LLM/no-confidence invariant statement" in that docstring; writing it with the obvious word turned the guard red.
**Resolution:** I did **not** weaken the guard. It is a money-path thesis guard, and its intent — keep the *concept* of a match score out of this module entirely — is sound. Instead the invariant is stated in words the guard permits: "NO score, NO probability, NO cutoff… Grading a match on a number and paying anything above a cutoff would, by construction, pay somebody on a guess at the margin." The docstring also now notes that a source-level guard enforces this. Same invariant, guard untouched, suite green.
**Files:** `app/pipeline/decide.py`. **Commit:** `bf31a7f`.

### 2. [Rule 1 - Stale comment] Two comments asserted things that are no longer true

Per the executor brief ("If a comment appears to contradict the code, do NOT fix the code"), I fixed the *comments* and changed no code. Both are in `377641d`.

- **`ValidationIssue`** (`app/models/roster.py`) claimed `"field_regression"` was "a forward-compat value… Nothing in Phase 7 emits it — a harmless no-op scaffold." `validate.py` emits it today. The docstring now documents all four `issue_type` values factually, including why `out_of_bounds`/`non_numeric` are legal-but-unreachable from the typed pipeline.
- **`FieldDrop`** (`app/models/contracts.py`) claimed a later phase "builds detect_field_regression on top of it." It did not — `detect_field_regression` was built on `RawFieldDrop`, and `FieldDrop` is referenced nowhere in `app/`, `tests/`, or `eval/`. Verified by grep. It is now honestly documented as **currently unused**, with its intended semantics retained should it ever be revived.

## Deferred Items

**`FieldDrop` is dead code.** Nothing constructs, imports, or reads it. Deleting it is a code change and therefore out of scope for a comment-only sweep, so I documented it rather than removed it. It is a clean one-line deletion whenever someone wants it — flagging it here so it is not silently open.

## Verification

Run at plan end, all green:

| Gate | Result |
|------|--------|
| Gate grep (all 14 files) | 0 matches |
| `irs.gov` in tax_tables_2026.py | 3 occurrences preserved |
| `uv run pytest -q` | **615 passed**, 51 skipped |
| `uv run ruff check` | All checks passed |
| `uv run mypy` | Success: no issues in **114** source files |

**Text-only proof:** each file's AST was parsed pre- and post-edit with docstrings stripped and compared. All are identical except two deliberate, permitted string-literal edits, both in `calculate.py`: `(D-05: Decimal everywhere)` → `(Decimal everywhere, never float)` in the bool/float `TypeError` messages. The `pytest.raises(match=...)` substrings those tests key on (`"bool"`, `"float"`, `"Unknown hours key"`, `"non-negative"`, `"not a valid number"`) are all intact — confirmed by grep before editing and by the green suite after.

Suite count is unchanged from baseline and no assertion was touched — that, plus strict mypy across 114 files, is the behavior-neutrality proof for the money core.

## Self-Check: PASSED

- `app/pipeline/{calculate,tax_tables_2026,federal_withholding,decide,validate,alias_learning,reconcile_names,compose_email,extract,suggest,pdf}.py` — all present, all modified.
- `app/models/{contracts,roster,status}.py` — all present, all modified.
- Commits `6fcd45f`, `bf31a7f`, `377641d` — all verified present in `git log`.
