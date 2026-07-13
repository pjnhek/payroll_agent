---
phase: 15-comment-hygiene-deferred-polish-triage
plan: 07
requirements-completed: [COMM-01, COMM-03]
subsystem: tests
tags: [comment-hygiene, tests, docs]
requires:
  - tests/conftest.py (shared fixtures)
provides:
  - provenance-free calculation/persistence/alias test cluster
  - provenance-free shared fixtures with seam documentation intact
affects:
  - tests/conftest.py
  - tests/test_alias_write.py
  - tests/test_persistence.py
  - tests/test_federal_withholding.py
  - tests/test_models_contracts.py
  - tests/test_needs_operator.py
  - tests/test_calculate.py
  - tests/test_clarify_rounds.py
  - tests/test_seed_roundtrip.py
  - tests/test_detect_field_regression.py
  - tests/test_alias_full_loop.py
  - tests/test_tax_tables_2026.py
tech-stack:
  added: []
  patterns:
    - "comment rewrite policy: keep the constraint and its failure mode, drop the ticket label"
    - "assertion-message strings are runtime strings — they state the invariant, not its provenance"
key-files:
  created: []
  modified:
    - tests/conftest.py
    - tests/test_alias_write.py
    - tests/test_persistence.py
    - tests/test_federal_withholding.py
    - tests/test_models_contracts.py
    - tests/test_needs_operator.py
    - tests/test_calculate.py
    - tests/test_clarify_rounds.py
    - tests/test_seed_roundtrip.py
    - tests/test_detect_field_regression.py
    - tests/test_alias_full_loop.py
    - tests/test_tax_tables_2026.py
decisions:
  - "Requirement IDs (CALC-*, CLAR2-*, MONEY-*, FOUND-*) were removed alongside the guard-blocked ticket IDs where they were pure provenance — the guard does not require it, but the audience test does: a reader should see zero trace of the project's ticket vocabulary."
  - "One test renamed off a phase reference: test_calc_federal_is_real_in_phase3 -> test_calc_federal_withholding_is_nonzero (count-neutral, no other file references it)."
  - "Two import-block reflows in conftest.py and test_alias_write.py were required after comment deletion collapsed the blank lines ruff's isort relied on (I001). Whitespace only — no import added, removed, or reordered semantically."
metrics:
  tasks: 3
  commits: 3
  files_modified: 12
  gate_hits_removed: 414
  suite_before: "615 passed / 51 skipped"
  suite_after: "615 passed / 51 skipped"
  completed: 2026-07-13
status: complete
---

# Phase 15 Plan 07: Comment Sweep — Calculation/Persistence/Alias Test Cluster Summary

Swept `tests/conftest.py` and eleven test files clean of ticket-ID and process references (414 gate-regex hits → 0), rewriting each comment as the constraint it documents and each failure-message string as the invariant it protects — with zero assertion-logic changes and an identical suite result.

## What Was Built

Twelve comment-clean test files. The rewrite policy throughout: **keep the constraint, keep the failure mode, drop the label.**

The money-path files kept full depth per the phase's D-02 rule. Where a comment previously said *what review found the bug*, it now says *what the bug does to someone's paycheck*:

- **`test_calculate.py`** — the leave-pay frequency-invariant docstring now spells out the actual mispay (a period-proportion denominator pays ~$2,166 instead of $200.00 at p=24, and is only *accidentally* correct at p=52 — which is exactly why a p=52-only test would let it through).
- **`test_calculate.py`** — the source-scan guard's assertion message (called out explicitly in the plan) now states the invariant plainly: the reconciliation backstop must **raise `PayrollCalculationError`**, not use a bare `assert`, because `python -O` strips bare asserts silently and would disable the only runtime guard against a mispay.
- **`test_federal_withholding.py`** — every IRS Pub 15-T citation, the transcription provenance, and the paycheckcity.com penny-exact oracle trace **stay** (external sources, not process history). The structural-independence rule is now stated as a rule: a test that computes its expectation from the code under test proves only self-consistency.
- **`test_alias_write.py`** — assertion messages now say *why* a colliding alias can never be learned (it would permanently bind an ambiguous name to one of two people) rather than citing the finding that demanded the guard.
- **`conftest.py`** — the fixture docstrings keep every monkeypatch-seam explanation the suite depends on (why the seams are module-attribute patches, why the LLM must stay stubbed, why `_STRANDED_SCOPE_STATUSES` is re-declared rather than imported, why the epoch filter makes prior-epoch replies invisible without deleting rows).

## How It Works

Nothing executes differently. The sweep touched only comments, docstrings, and assertion-message strings.

Three atomic commits, one per task, each gated on its own grep + tests:

| Task | Commit | Files |
|------|--------|-------|
| 1 | `3485daa` | conftest.py, test_alias_write.py, test_persistence.py |
| 2 | `be567de` | test_federal_withholding.py, test_models_contracts.py, test_needs_operator.py, test_calculate.py |
| 3 | `555b2d7` | test_clarify_rounds.py, test_seed_roundtrip.py, test_detect_field_regression.py, test_alias_full_loop.py, test_tax_tables_2026.py |

## Key Decisions

**Requirement IDs went too, where they were pure provenance.** The sweep rubric explicitly does *not* guard-block `CALC-*` / `CLAR2-*` / `MONEY-*` / `FOUND-*`. But the phase's audience test is "a hiring manager sees zero clue the project ever had ticket numbers," so where a requirement ID was decoration on a sentence that read fine without it, it was removed. Behavioral explanations were kept and, in several cases, deepened.

**A fresh manifest was generated before editing** (per the review's LOW finding), not trusted from the plan's discussion-time counts. The real distribution differed from the estimates — `test_alias_write.py` carried 85 hits, not ~66; `test_clarify_rounds.py` carried 21, not ~80-combined-with-others. Working from the live grep is what caught the assertion-message strings in `test_alias_write.py` that the estimates missed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Import-block reflow after comment deletion (I001)**
- **Found during:** Task 1 verification (`uv run ruff check`)
- **Issue:** Deleting the provenance comment above `import resend` in `conftest.py` (and above the `alias_learning` import in `test_alias_write.py`) collapsed the blank-line separators ruff's isort rule was using as import-group boundaries. Both files failed `I001` — an error introduced directly by this task's own edits, and blocking its verification gate.
- **Fix:** Merged each orphaned import back into its correct group (whitespace only). No import was added, removed, or reordered semantically.
- **Files modified:** `tests/conftest.py`, `tests/test_alias_write.py`
- **Commit:** `3485daa`

### Test Rename (D-06)

`test_calc_federal_is_real_in_phase3` → `test_calc_federal_withholding_is_nonzero` in `test_persistence.py`. The old name embedded a phase reference. Verified no other file references it; count-neutral.

## Verification

Neutrality proof — the suite result is byte-identical before and after:

```
before:  615 passed, 51 skipped
after:   615 passed, 51 skipped
```

| Gate | Result |
|------|--------|
| Gate grep, all 12 files | **0 hits** (was 414) |
| `uv run pytest -q` | 615 passed, 51 skipped |
| `uv run ruff check` | All checks passed |
| `uv run mypy` | Success: no issues found in 114 source files |
| Assert-statement count, per file, before vs after | **Identical in all 12** (3 / 31 / 64 / 27 / 44 / 35 / 24 / 20 / 51 / 25 / 25 / 42) |
| IRS source citations preserved | `test_federal_withholding.py`: 3 · `test_tax_tables_2026.py`: 4 |

The per-file assert-count parity check (`git show HEAD~3:<file> | grep -c '^\s*assert '` vs the working tree) is the mechanical proof that no assertion was added, removed, or restructured — only message strings inside them were rewritten.

## Known Stubs

None.

## Threat Flags

None. This plan introduces no network endpoint, auth path, file-access pattern, or schema change. `T-15-04` (a test sweep silently altering suite behavior) is mitigated as planned: message-strings-only rule, unchanged pass count, and full suite + ruff + mypy green at every commit.

## Self-Check: PASSED

- All 12 modified files exist and are committed.
- Commits `3485daa`, `be567de`, `555b2d7` verified present in `git log`.
