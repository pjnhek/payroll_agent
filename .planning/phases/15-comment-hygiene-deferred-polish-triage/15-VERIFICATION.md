---
status: gaps_found
phase: 15-comment-hygiene-deferred-polish-triage
requirements: [COMM-01, COMM-02, COMM-03, POLISH-01, POLISH-02]
verified_by: orchestrator (gsd-verifier agent died on a session/usage limit before producing output)
date: 2026-07-13
score: 4/5 must-haves verified
---

# Phase 15 Verification

All 11 plans executed, merged, and green. Four of five requirements fully verified against the
live codebase. **COMM-01 is materially incomplete** — the guard it delivers has a vocabulary hole
and a scope hole, both demonstrated below with live examples.

## Gates (merged tree, HEAD)

| Gate | Result |
|------|--------|
| `uv run pytest -q` | 623 passed / 52 skipped |
| `uv run ruff check .` | clean |
| `uv run mypy` (strict) | clean, 117 files |
| Worktrees outstanding | 0 |
| SUMMARY.md present | 11/11 |

## VERIFIED

### POLISH-01 — behavior fixes ✅
Both fixes landed test-first with genuine RED evidence, and both survive 15-09's later sweep of
the same files:
- **Path traversal (WR-05)** — `app/routes/dashboard.py` uses `resolve()` +
  `is_relative_to(fixtures_root)`. The RED run rendered a file from *outside* the fixtures
  directory onto the eval page via `../`. Regression test passes.
- **Prompt echo (INFO-02)** — `app/llm/client.py::_scrubbed_validation_summary()` uses
  `exc.errors(include_url=False, include_input=False)`, so model output is no longer returned to
  the provider in the retry prompt. Regression test passes.
- **Reply threading (WR-01)** — no production bug existed; the epoch machinery already held. The
  test is a regression gate, and it was **proven capable of failing**: narrowing the `ON CONFLICT`
  arbiter and the `uq_email_run_purpose_round_epoch` constraint to three columns makes test 1 fail
  while test 2 still passes — concrete evidence the same-epoch-retry test alone would have missed
  a clobbered delivered email.

### POLISH-02 — deferred-polish triage ✅
Todos `260623-01` and `260623-05` moved `pending/` → `completed/`. The fixture-10 item, filed as
cosmetic, was a **real eval-chart defect**: a mislabeled fixture was dumping an intentional
phantom-employee miss into the `exact` bucket, so the chart reported exact-match extraction failing
at 0.96 when it had never failed. Now `exact.f1 = 1.00`, `typo.f1 = 0.90`. Overall F1 (0.9889) and
the confusion matrix (`false_process = 0`) unchanged, as expected — relabeling rebuckets, it does
not rescore.

### COMM-02 — money-path comment depth ✅
Comments document constraints, not history. Independently verified **no damage to the money path**:

| File | AST identity (docstrings stripped) | Numeric/Decimal literals |
|------|-----------------------------------|--------------------------|
| `tax_tables_2026.py` | IDENTICAL | **194 — all identical** |
| `federal_withholding.py` | IDENTICAL | 5 — all identical |
| `decide.py` | IDENTICAL | — |
| `validate.py` | IDENTICAL | — |
| `calculate.py` | 2 string constants only* | 14 — all identical |

\* the only delta is two exception messages with `D-05:` stripped — no control flow, no arithmetic.
**Zero 2026 tax constants changed.** IRS `irs.gov` citations preserved (3 + 2 in source, 4 + 3 in tests).

The `decide.py` no-confidence guard is intact: 0 occurrences of "confidence", `test_gate.py` 15
passed. Plan 15-04 hit a direct conflict between its own acceptance criteria and this guard and
chose to obey the guard — rewriting its invariant without the banned word rather than weakening the
test that protects the deterministic-decisioning thesis.

### COMM-03 — test identity ✅
32 function renames + 2 file renames. **Test count neutral: 666 → 666 → 666**, proving no test was
silently dropped or duplicated. Assert *conditions* proven untouched by AST comparison (172 + 77
`ast.Assert.test` nodes identical); only assert *messages* changed.

## GAPS — COMM-01 ❌

The comment-provenance guard (`tests/test_comment_provenance_guard.py`) works and is **not**
vacuous — I independently falsified it rather than trusting the SUMMARY:

| Injection | Expected | Actual |
|---|---|---|
| `CR-02 / Phase 9 / D-11-01 / Finding #3` | red | red ✓ |
| `D-A3-05` (letter-prefixed decision ID) | red | red ✓ |
| `BOUND-01` / `FOUND-04` (live requirement IDs) | green | green ✓ |

But it has two holes, and the tree is green *because of them*, not because it is clean.

### GAP-1 — the `IN-NN` ticket family is absent from the guard's vocabulary
`IN-` appears nowhere in the pattern table. Three live provenance refs survive **in files the guard
actively scans**, and the guard is green:

- `app/db/seed.py:355` — `# (IN-08): no model_dump is called here.` *(owned by plan 15-05)*
- `tests/test_tax_tables_2026.py:287` — `"""IN-02 (review round 2): ..."""` *(owned by plan 15-07)*
- `eval/draft_candidate_emails.py:9` — `...consistent with the other eval scripts (IN-03).`
  *(owned by **no plan** — this file is in no plan's `files_modified`)*

Three separate plans swept these files and left the refs, because every per-plan regex and the final
guard share the same blind spot. This is the same class of miss 15-10 caught with `D-A3-05` — found
by extending the vocabulary — except this one was not caught.

### GAP-2 — `SCAN_GLOBS` excludes the infra/CI surface
The guard's own docstring states its surface is *"every file whose text a maintainer reads."* Its
globs cover `app/`, `eval/`, `scripts/`, `tests/` — but not the build, CI, or config files. **17
provenance refs survive there, unenforced:**

| File | Refs |
|------|------|
| `pyproject.toml` | 9 — `IN-09`, `D-01` ×2, `D-02` ×2, `D-03` ×2, `D-04`, `D-06` |
| `Dockerfile` | 3 — `D-19`, `D-21` ×2 |
| `.github/workflows/eval.yml` | 2 — `CR-01` ×2 |
| `.github/workflows/concurrency-proof.yml` | 2 — `WR-04`, `Phase 9` |
| `.github/workflows/ci.yml` | 1 — `WR-01` |
| `.github/workflows/keepalive.yml` | 2 — `D-16`, `D-20` |
| `.dockerignore` | 1 — `D-21` |
| `.env.example` | 1 — `Phase 6` |

These are rot by the phase's own D-01/D-02 rubric. Several carry genuine rationale that should be
*kept* while the ticket ID is dropped — e.g. `pyproject.toml:47` reads
`# D-02: 100 is the measured tradeoff — 160 lines exceed 100 vs 1,297 that exceed the 88 default.`
The constraint is worth keeping; the `D-02:` prefix is not.

**Out of scope (correctly):** `CLAUDE.md` / `AGENTS.md` (3 `Phase N` refs each) and `docs/**` are
project documents describing the roadmap — narrating project history is their *purpose*, not rot.

## Known, recorded limitation (not a new finding)

The concurrency/epoch proofs gate **push-to-master and manual dispatch, but not `pull_request`**. A
PR can go green without a real database ever executing them. Recorded by plan 15-01 in a comment
above the workflow's `on:` block; adding a `pull_request:` trigger is a CI-policy change outside
POLISH-01's scope.

## Recommendation

GAP-1 and GAP-2 are contained and mechanical. Closing them means: add `IN` to the review-ticket
pattern, sweep 3 refs in scanned files, extend `SCAN_GLOBS` to the infra surface, and sweep the 17
refs there (keeping the rationale, dropping the IDs). No money-path code is involved.
