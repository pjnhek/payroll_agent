---
phase: 15-comment-hygiene-deferred-polish-triage
plan: 02
subsystem: eval-harness
tags: [comment-hygiene, eval, fixtures, polish]
requires: []
provides:
  - "eval/ and scripts/ sources free of ticket-ID and process references"
  - "fixture 10 labeled fixture_category 'typo'"
  - "regenerated eval/summary.json + eval/chart.svg with honest per-category grouping"
affects:
  - eval/run_eval.py
  - eval/judge.py
  - eval/fixtures/DIVERGENCES.md
  - eval/fixtures/10_multi_employee_coastal.json
  - eval/summary.json
  - eval/chart.svg
  - scripts/show_confirmation_subject.py
  - scripts/demo_reset.py
  - scripts/reset_stuck_runs.py
tech-stack:
  added: []
  patterns:
    - "comment rubric: keep the constraint, drop the ticket label; money-path comments keep BOTH constraint AND failure mode"
    - "hermetic eval regeneration from committed extraction caches (no live LLM, no DB)"
key-files:
  created:
    - .planning/todos/completed/260623-05-fixture-category-label-mismatch.md
  modified:
    - eval/run_eval.py
    - eval/judge.py
    - eval/fixtures/DIVERGENCES.md
    - eval/fixtures/10_multi_employee_coastal.json
    - eval/summary.json
    - eval/chart.svg
    - scripts/show_confirmation_subject.py
    - scripts/demo_reset.py
    - scripts/reset_stuck_runs.py
decisions:
  - "Fixture 10 relabeled 'exact' -> 'typo' (D-13): matches fixture 05's existing category; 'Jame Okafor' is a typo of roster 'James Okafor'"
  - "The relabel is substantive, not cosmetic: it moves fixture 10's deliberate phantom-employee precision miss out of the 'exact' extraction bucket, which was misreporting exact-matching as failing extraction"
metrics:
  duration: ~25m
  completed: 2026-07-13
requirements: [COMM-01, COMM-03, POLISH-02]
status: complete
---

# Phase 15 Plan 02: Sweep eval/ + scripts/, Close POLISH-02 Summary

Swept `eval/` and `scripts/` clean of ticket/provenance references under the keep-constraint-drop-label rubric, then relabeled eval fixture 10 to `"typo"` and regenerated the committed eval artifacts hermetically — which turned out to fix a genuinely misleading chart, not just a cosmetic label.

## What Was Built

**Task 1 — comment/docstring/runtime-string sweep (commit `8a7318a`).** Regenerated a fresh gate-regex manifest over the six files first (per the plan's "fresh manifest, not discussion-time counts" rule) and worked from it: 60 matching lines across `eval/run_eval.py` (40), `eval/judge.py` (11), `eval/fixtures/DIVERGENCES.md` (3), `scripts/demo_reset.py` (4), `scripts/show_confirmation_subject.py` (3), `scripts/reset_stuck_runs.py` (2). Every surviving comment now stands alone for a maintainer who has never seen `.planning/`.

Money-path comments kept **both** the constraint and the failure mode, per D-02. Four examples where the consequence narration is what stops a future "simplification" from reintroducing a bug:

- The confusion-matrix cell highlight (`table[1, 2]`) now says *why* the indices are load-bearing — highlighting `[2, 2]` instead would colour true-clarify, "a chart that advertises safety exactly where it should warn."
- The judge's correctness floor now says it runs in code, not the prompt, "because the judge model cannot be trusted to enforce the one rule that matters most."
- The reconciliation scorer now says scoring only `source`/`resolved` would let "matched *an* employee" count as correct when it matched the **wrong** one.
- The three-phase eval branch now says skipping backfill would score a round-2 carry-forward as "missing fields" while production processes it cleanly — "a silent eval/production gap that would hide a real decision regression behind a green eval."

The `run_eval.py` argparse **runtime string** `"Payroll Agent eval scorer -- Phase 4"` → `"Payroll Agent eval scorer"`, as flagged. No `# noqa` / `# type: ignore` marker was moved or deleted (mypy `warn_unused_ignores` is on) — only reason text was rewritten.

**Task 2 — POLISH-02 (commit `7496020`).** Fixture 10 `fixture_category`: `"exact"` → `"typo"`. Artifacts regenerated hermetically from the committed extraction caches, then fixture + `summary.json` + `chart.svg` committed **together** in one commit so the push-time eval gate never sees a half-applied state. Todo 260623-05 moved to `completed/` with a resolution record.

## The Interesting Part: the label was not cosmetic

The todo (and the plan) framed this as a low-priority cosmetic mismatch with "no eval impact." That's true of *accuracy* — `run_eval.py` scores against `expected.decision.final_action`, never the category string. But the grouping was actively **misreporting** a category.

Fixture 10's extraction cache carries a deliberate phantom employee ("John Smith" — see `eval/fixtures/DIVERGENCES.md`) to exercise the precision metric, giving it extraction F1 = 0.80. Under the wrong `"exact"` label, that intentional miss was averaged into the **exact** bucket:

| Bucket | Before | After |
|--------|--------|-------|
| `per_category_extraction.exact.f1` | 0.96 | **1.00** |
| `per_category_extraction.typo.f1` | 1.00 | **0.90** (n=2, honestly carries the miss) |
| `per_category_decision.exact` | 5/5 | **4/4** |
| `per_category_decision.typo` | 1/1 | **2/2** |

So the chart was showing the **exact-match category failing at extraction (0.96) when nothing about exact matching had failed** — the miss belonged to a typo fixture all along. For a chart whose entire audience is hiring managers reading it cold, that is a real defect, not a cosmetic one. Post-relabel the exact bar is a clean 1.00 and the typo bar honestly absorbs the phantom-employee precision miss, which is the reading DIVERGENCES.md describes.

`per_category_reconciliation` is unchanged, exactly as the plan predicted — it groups by per-NAME category, not `fixture_category`. Overall F1 (0.9889) and the confusion matrix (`false_process = 0`) are unchanged: relabeling moves a fixture between buckets, it does not rescore it.

## Verification

| Check | Result |
|-------|--------|
| Gate regex over the six swept files | **zero hits** |
| `run_eval.py --check` BEFORE relabel (sweep output-neutrality) | **exit 0** |
| `run_eval.py --check` after regeneration | **exit 0** |
| `uv run ruff check` (whole repo) | All checks passed |
| `uv run mypy` | Success: no issues in 114 source files |
| `uv run pytest -q` | **615 passed, 51 skipped** |
| `grep -rn "10_multi\|multi_employee_coastal" tests/` | nothing — no test coupling |
| Todo 260623-05 | in `completed/` with resolution record |

The 51 skips are the `-m integration` / `-m live_llm` tests that auto-skip without `DATABASE_URL` / `ALLOW_LIVE_LLM` — expected in a worktree with no `.env`.

The key evidence for the threat register's T-15-04 (sweep silently altering scored output): `--check` exited 0 against the **still-committed** `summary.json` after Task 1 and before Task 2's relabel. The comment sweep provably changed no scored value.

## Deviations from Plan

None — plan executed exactly as written. No architectural decisions (Rule 4) were required, and no auto-fixes (Rules 1-3) were needed.

Two mechanical notes, neither a behavior change:

1. `git mv` stages the rename immediately, so the later `git add` of the *pending* path failed with `pathspec did not match`. Re-ran the add against the `completed/` path only. Same tree, same commit contents.
2. Two provenance strings in `run_eval.py` (`"so 04-04 can reuse it"`, `"per-fixture shape from 04-02"`) did **not** match the gate regex but are plan-ID references under D-03. Cleaned them anyway — the rubric is "stands alone for a maintainer," not "passes the grep."

## Known Stubs

None.

## Threat Flags

None. This plan touched comment text, one fixture label, and two regenerated artifacts — it introduced no network endpoint, auth path, file-access pattern, or schema change. No packages installed.

## Commits

| Commit | Description |
|--------|-------------|
| `8a7318a` | `docs(15-02)`: sweep ticket/provenance references from eval/ and scripts/ (6 files) |
| `7496020` | `fix(15-02)`: relabel fixture 10 as typo, regenerate eval artifacts, close todo 260623-05 |

## Self-Check: PASSED

- `eval/fixtures/10_multi_employee_coastal.json` — FOUND, contains `"fixture_category": "typo"`
- `eval/summary.json` — FOUND, fixture 10 grouped under `typo` in both `per_category_extraction` and `per_category_decision`
- `eval/chart.svg` — FOUND, regenerated (141,287 bytes)
- `.planning/todos/completed/260623-05-fixture-category-label-mismatch.md` — FOUND
- `.planning/todos/pending/260623-05-fixture-category-label-mismatch.md` — correctly ABSENT
- Commit `8a7318a` — FOUND in git log
- Commit `7496020` — FOUND in git log
