# Phase 12: CI Quality Gates - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-08
**Phase:** 12-CI Quality Gates
**Areas discussed:** Ruff ruleset & the 42 existing errors, Trigger & branch scope, Test lane composition, Red-proof demo & visibility

---

## Ruff ruleset & the 42 existing errors

| Option | Description | Selected |
|--------|-------------|----------|
| Curated extended set | E, F, I (isort), B (bugbear), UP (pyupgrade), SIM (simplify) — deliberate production config, mostly autofixable | ✓ |
| Ruff defaults only | E4/E7/E9 + F — minimal, near-zero churn, but reads as box-ticking | |
| Aggressive (N, D, RUF, C4…) | Max rigor but large non-autofixable churn fighting Phases 13–15 | |

**User's choice:** Curated extended set (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| 100 | 160 existing violations — manageable mechanical pass; common modern production choice | ✓ |
| 88 (ruff/black default) | 1,297 existing violations — huge diff in a behavior-neutral milestone | |
| 120 (permissive) | Only 16 violations but reads as "check turned off" | |

**User's choice:** 100 (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Fix everything, zero blanket ignores | Autofix bulk, hand-fix rest; noqa only individually justified; F821s get TYPE_CHECKING imports | ✓ |
| Autofix + per-file-ignores for the tail | Smaller diff but visible tech debt in a polish milestone | |
| You decide | Claude picks per category during planning | |

**User's choice:** Fix everything, zero blanket ignores (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Lint only, per requirements | `ruff check` exactly as CI-01 specifies; no whole-repo reformat diff | ✓ |
| Add ruff format --check too | One-time reformat now, locked before Phase 13 moves — beyond written requirements | |
| You decide | Claude weighs diff size vs consistency | |

**User's choice:** Lint only, per requirements (Recommended)
**Notes:** Baseline scouting found 42 default-rule errors; the 7 F821s are quoted `"Employee"` forward-refs in test helpers, not real bugs.

---

## Trigger & branch scope

| Option | Description | Selected |
|--------|-------------|----------|
| Push on ALL branches + workflow_dispatch | Literal "every push"; makes criterion-4 red-proof a simple branch push | ✓ |
| Push to master + pull_request | Conventional team pattern but repo rarely uses PRs | |
| Match existing: master-only | Consistent with other workflows but weakens the safety net | |

**User's choice:** Push on ALL branches + workflow_dispatch (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| New standalone ci.yml, others untouched | Focused, behavior-neutral, low-risk | ✓ |
| Fold eval.yml's hermetic check into ci.yml | One "quality gates" workflow but edits a proven workflow | |
| You decide | | |

**User's choice:** New standalone ci.yml, leave the others untouched (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Cancel-in-progress per branch | Standard pattern; lint/test safely cancellable (unlike deploy-migrate) | ✓ |
| No concurrency config | Simplest; redundant runs both finish | |
| You decide | | |

**User's choice:** Yes — cancel-in-progress per branch (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Two parallel jobs: lint + test | Each gate its own named check; matches criterion 4's per-step redness; fast lint feedback | ✓ |
| One job, sequential steps | One uv sync, cheaper, but first failure masks the second | |
| You decide | | |

**User's choice:** Two parallel jobs: lint + test (Recommended)

---

## Test lane composition

| Option | Description | Selected |
|--------|-------------|----------|
| Bare `uv run pytest -q`, no DB service | Exactly CI-02; hermetic via existing two-factor env guards; no duplication of concurrency-proof.yml | ✓ |
| Also spin up Postgres in ci.yml | Integration tests on every push but duplicates concurrency-proof.yml | |
| Explicit -m 'not integration and not live_llm' | Visible exclusion but redundant and deviates from CI-02's literal command | |

**User's choice:** Bare `uv run pytest -q`, no DB service (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| No guard — keep it simple | Pinned count = permanent maintenance burden; can't catch design-level vacuousness | ✓ |
| Assert a minimum passed-test floor | Catches catastrophic mass-skips, needs the magic number maintained | |
| You decide | | |

**User's choice:** No guard — keep it simple (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| No coverage in this phase | Stays on CI-01–03; no new dep or threshold | ✓ |
| Report-only coverage | Cheap visibility but unenforced numbers drift | |
| Coverage gate (fail under N%) | Real gate but N is guesswork and could block Phase 13 | |

**User's choice:** No coverage in this phase (Recommended)
**Notes:** Scouting confirmed 663 tests collected; live-DB and live-LLM tests are two-factor env-gated and auto-skip in CI.

---

## Red-proof demo & visibility

| Option | Description | Selected |
|--------|-------------|----------|
| Throwaway branches + run links in VERIFICATION.md | Durable, checkable evidence; red runs in history show the gates work | ✓ |
| Demonstrate live, don't record links | Satisfies the letter but leaves no auditable artifact | |
| You decide | | |

**User's choice:** Throwaway branches + run links in VERIFICATION.md (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — ci.yml badge in README | One line; makes the gate legible to a recruiter skimming the repo | ✓ |
| No badge — requirements only | Strictly CI-01–03 | |
| Badges for CI + eval both | More signal but starts a badge row needing curation | |

**User's choice:** Yes — ci.yml badge in README (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| After-the-fact signal; keep direct pushes | No PR round-trip friction on the solo GSD flow; red on master is still loud | ✓ |
| Branch protection: require green CI | Genuinely blocking but changes the whole working rhythm mid-milestone | |
| You decide | | |

**User's choice:** After-the-fact signal; keep direct pushes (Recommended)

---

## Claude's Discretion

- Exact ruff config layout in `pyproject.toml` (section structure, isort settings)
- uv caching, action version pins, job naming — follow the existing workflows' house pattern
- Cleanup-commit grouping (autofix vs hand-fix), provided each commit is behavior-neutral with a green suite

## Deferred Ideas

- `ruff format --check` CI gate (whole-repo one-time reformat; cheapest before Phase 13 file moves)
- Coverage reporting/gating (pytest-cov) — future milestone candidate
- Branch protection requiring green CI on master — revisit if collaborators join
