---
milestone: v3
audited: 2026-07-13
status: passed
closeout_type: verified_closeout
scores:
  requirements: 16/16
  phases: 4/4
  integration: 5/5
  flows: 1/1
gaps:
  requirements: []
  integration: []
  flows: []
tech_debt:
  - phase: 12-ci-quality-gates
    items:
      - "No VALIDATION.md (Nyquist artifact absent — process, not code)"
  - phase: 15-comment-hygiene-deferred-polish-triage
    items:
      - "VALIDATION.md is an unfilled draft template (status: draft, body still has {pytest 7.x} placeholders)"
  - milestone
    items:
      - "3 deferred low-priority todos: frontend progressive enhancement, paystub YTD columns, eval chart restyle"
      - "1 stale quick-task pointer: 260621-11x (work was done; tracking file never closed)"
      - "concurrency proofs now gate PRs, but eval.yml/deploy-migrate remain push-only (correct: deploy-migrate issues live DDL)"
nyquist:
  compliant_phases: [13, 14]
  partial_phases: [15]
  missing_phases: [12]
  overall: partial
---

# v3 — Production-Ready Codebase — Milestone Audit

**Status: PASSED.** All 16 requirements satisfied across three independent sources. All 4 phases
verified. Cross-phase integration clean on all five seams, each independently checked against live
source (two of them adversarially falsified). CI green on the pushed HEAD.

## Requirements — 16/16 satisfied

Three-source cross-reference (phase VERIFICATION.md + SUMMARY frontmatter + REQUIREMENTS.md
traceability). **Zero orphans; zero requirements claimed but not defined.**

| Phase | Requirements | VERIFICATION | SUMMARY frontmatter | REQUIREMENTS.md | Status |
|-------|-------------|--------------|---------------------|-----------------|--------|
| 12 — CI Quality Gates | CI-01, CI-02, CI-03 | passed (12/12) | listed | `[x]` | **satisfied** |
| 13 — Module Structure | STRUCT-01…04, BOUND-01 | passed (5/5) | listed | `[x]` | **satisfied** |
| 14 — Full mypy | TYPE-01, TYPE-02, TYPE-03 | passed (3/3) | listed | `[x]` | **satisfied** |
| 15 — Comment Hygiene | COMM-01…03, POLISH-01, POLISH-02 | passed (5/5) | listed¹ | `[x]` | **satisfied** |

¹ Phase 15's executors never emitted the `requirements-completed` frontmatter field, which scored
its five requirements as *partial* under the 3-source matrix despite VERIFICATION.md passing 5/5.
Backfilled from each plan's own `requirements:` frontmatter (commit `4b0f72b`) so traceability is
machine-checkable rather than only human-readable. **A bookkeeping gap, not a coverage gap** — the
work was independently verified during phase 15's own audit.

## Cross-phase integration — 5/5 clean

The phases are sequential and **each rewrote the surface the previous one built** — 13 split the
god-files, 14 annotated the split modules, 15 rewrote their comments. That is exactly where
integration rots, and no single phase's verification looks across the boundary. All five seams were
checked against live source:

| # | Seam | Result | Evidence |
|---|------|--------|----------|
| 1 | 13→14→15 layering on the same files; repo facade re-exports; monkeypatch seams still intercepting | **CLEAN** | Full suite **628 passed / 52 skipped**; `app.db.repo` facade exposes 63 names; `app.main` + `orchestrator` import cleanly |
| 2 | BOUND-01 AST guard still enforcing after 15 rewrote its file | **CLEAN — falsified** | Guard green (2 passed). Planted a cross-module `_private` import → guard went **RED**. Restored. It can still fail, so its green means something. |
| 3 | CI gates from 12 + 14 + 15 all actually run | **CLEAN** | `ci.yml` has all three blocking jobs (Lint / Test suite / Type check). The phase-15 provenance guard **does** run in CI — it is collected by the test job's bare `uv run pytest -q` (5 tests). |
| 4 | E2E money flow intact across three refactors; `decide.py` has no scoring concept | **CLEAN** | `test_gate.py` 15 passed. `confidence` count in `decide.py` = **0**. The only scoring-adjacent string is the docstring *asserting the absence*: "NO score, NO probability, NO cutoff." |
| 5 | Nothing deleted that another phase still needs | **CLEAN** | `FieldDrop` — zero references repo-wide. `repo.py` / `main.py` bodies resolve via their new homes. |

**Note on method:** the `gsd-integration-checker` subagent went idle without returning a report, so
these seams were verified directly by the orchestrator against live source rather than accepted on
its word. Seams 2 and 4 were verified by *falsification* (plant a violation, confirm the guard goes
red, revert) rather than by observing a green run — a guard that has never failed proves nothing.

## Definition of done — met

v3's intent: *"make the codebase read as production-quality: enforced CI, right-sized modules, full
type-checking, constraint-documenting comments."*

- **Enforced CI** — lint, full hermetic test suite, and `mypy --strict` are all blocking jobs. The
  real-Postgres concurrency proofs now gate pull requests, not just post-merge master.
- **Right-sized modules** — `main.py` 1,857 → 16 lines (routers); `repo.py` → per-aggregate package;
  `orchestrator.py` 1,843 → 1,029. Cross-module `_private` imports promoted and AST-guarded.
- **Full type-checking** — `mypy --strict` clean over **117 files** (app + eval + scripts + tests).
- **Constraint-documenting comments** — provenance stripped repo-wide, enforced by a CI guard that
  is pinned against the real ticket-family inventory and proven capable of failing.

## Verified state (pushed HEAD `4126432`)

| Gate | Result |
|------|--------|
| `uv run pytest -q` | 628 passed / 52 skipped |
| `uv run ruff check .` | clean |
| `uv run mypy` | clean, 117 files |
| CI: ci / concurrency-proof / deploy-migrate / eval | **4/4 green** |
| concurrency-proof real-Postgres tests | **5 passed, 0 skipped** |

The concurrency-proof result is the load-bearing one: those are the **only** tests in the repo that
touch a real database (the rest mock it), and before this milestone they never ran in CI at all.

## Tech debt — accepted, non-blocking

| Item | Severity | Disposition |
|------|----------|-------------|
| Phase 12 has no VALIDATION.md | low | Nyquist process artifact, not code debt |
| Phase 15's VALIDATION.md is an unfilled draft (`{pytest 7.x}` placeholders) | low | Scaffolded at planning, never completed. Phases 13/14 are compliant. |
| 3 pending todos: frontend progressive enhancement, paystub YTD, eval chart restyle | low | Explicitly deferred to a future milestone; already dispositioned at the v2 close |
| Stale quick-task pointer `260621-11x` | low | Work was done; only the tracking file never closed |
| `eval.yml` / `deploy-migrate.yml` remain push-only | info | Correct by design — `deploy-migrate` issues DDL against the LIVE database and must never fire from a PR |

Phase 15 closed the two todos that mattered (`260623-01`, `260623-05`) — and `260623-05`, filed as
cosmetic, turned out to be a **real eval-chart defect**: a mislabeled fixture was reporting
exact-match extraction as failing at 0.96 when it had never failed.

## Notable outcomes beyond the requirements

- **Three real defects found by phases whose stated scope was hygiene**: the eval-chart mislabel
  above; a path traversal that actually rendered a file from outside `eval/fixtures/` onto the eval
  page; and a retry prompt echoing model output back to the provider.
- **A CRITICAL caught by reviewing the fix, not the code**: cross-AI review round 2 found that the
  prompt-echo fix scrubbed `ValidationError.input` but left `loc` open — under `extra="forbid"`, a
  model-invented field name lands in `loc` and was piped straight back to the provider. Round 3
  confirmed the corrected fix. **Always run a round that reviews the fix commits.**
- **The comment guard was green because it was blind, four separate times** (missing `IN-NN`, then
  the whole build/CI surface, then `render.yaml`, then `R3`/`BLOCKER`/`REVIEW`/`CHANGE`/`WARNING` —
  the last exposing 8 live rot references, 2 in production source). Fixed structurally: the pattern
  table is now asserted against the real family inventory harvested from git history, and the
  no-false-positive half is pinned too.
