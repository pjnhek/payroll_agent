# Roadmap: Payroll Agent

## Milestones

- ✅ **v1.0 — MVP** (shipped 2026-06-25) — Email-driven payroll agent: messy email in, correct human-approved payroll out, every money-moving decision code-gated (deterministic, auditable, never guesses). 7 phases, deployed live on a free stack with a recorded demo. → [full archive](milestones/v1.0-ROADMAP.md) · [requirements](milestones/v1.0-REQUIREMENTS.md)
- ✅ **v2 — Production Hardening** (shipped 2026-07-07) — Took the working v1.0 MVP and made its money-logic and data layer genuinely production-grade — correct under real, messy, concurrent load, not just the demo path. 6 phases (7, 7.5, 8, 9, 10, 11), 16 requirements, scope discovered via an adversarial audit. → [full archive](milestones/v2-ROADMAP.md) · [requirements](milestones/v2-REQUIREMENTS.md) · [audit](milestones/v2-MILESTONE-AUDIT.md)

## Active Milestone: v3 — Production-Ready Codebase

**Goal:** Make the entire existing codebase read as production-quality — surface and substance — for the hiring-manager/recruiter audience: enforced CI quality gates, right-sized modules, full type-checking, and comments that document constraints instead of process history.

**Shape:** A behavior-neutral refactor + tooling milestone over an already-shipped, live app. The existing 613-test suite is the safety net for every phase; no pipeline/money behavior changes anywhere in v3. Phases are strictly ordered by a hard dependency chain: CI gates land first so every later refactor is protected by lint+test CI in the loop; module splits (and the module-boundary cleanup that naturally rides with them) land before the comment-hygiene pass so comments aren't rewritten in files about to move; mypy adoption lands after the splits (smaller modules are easier to annotate) and gets its own phase per an explicit scope call (full mypy adoption may double the milestone — it is not squeezed into a shared phase); deferred-polish triage closes out the milestone as small, independent items.

### Phases

**Phase Numbering:** v3 continues the global phase sequence from v2 (last phase: 11). Integer phases (12, 13, 14, 15) are planned milestone work; decimal phases (e.g. 12.1) are reserved for urgent insertions.

- [ ] **Phase 12: CI Quality Gates** - `ci.yml` runs `ruff check` and the full hermetic test suite on every push, backed by a committed ruff config, so every subsequent refactor phase in this milestone is protected by CI from the start (CI-01, CI-02, CI-03)
- [ ] **Phase 13: Module Structure & Boundaries** - The three god-files (`main.py`, `repo.py`, `orchestrator.py`) split into right-sized, per-concern modules with a stable import surface and zero behavior change, and cross-module `_private` imports are promoted to deliberate public names (STRUCT-01, STRUCT-02, STRUCT-03, STRUCT-04, BOUND-01)
- [ ] **Phase 14: Full Type-Checking (mypy)** - mypy with the pydantic plugin runs clean over the entire codebase (`app/`, `eval/`, `scripts/`, `tests/`) and is wired in as a blocking CI check (TYPE-01, TYPE-02, TYPE-03)
- [ ] **Phase 15: Comment Hygiene & Deferred-Polish Triage** - Ticket-ID/provenance comments are stripped in favor of plain maintainer-facing constraint comments, the hand-maintained `repo.py` function-index docstring is replaced across the split DB modules, and the two remaining v2 deferred-polish todos are closed (COMM-01, COMM-02, COMM-03, POLISH-01, POLISH-02)

## Phase Details

### Phase 12: CI Quality Gates

**Goal**: The project has enforced, automated quality gates — every push is checked for lint and test regressions before anything else in the milestone changes a line of code, so the god-file splits, mypy adoption, and comment pass that follow are all built on top of a working CI safety net rather than relying solely on local runs.
**Depends on**: Nothing (first v3 phase — deliberately ordered before every other refactor so it protects them)
**Requirements**: CI-01, CI-02, CI-03
**Success Criteria** (what must be TRUE):

  1. A GitHub Actions workflow (`ci.yml`) runs on every push and runs `ruff check` against the repo, failing the build on any lint violation.
  2. The same workflow runs the full hermetic test suite (`uv run pytest -q`) on every push and fails the build on any test failure.
  3. A committed ruff configuration in `pyproject.toml` defines the ruleset (rule selection, line length) so a local `uv run ruff check` and the CI run agree byte-for-byte on results.
  4. Pushing a branch with a deliberately injected lint error (e.g. an unused import) shows CI going red on the lint step, and a deliberately broken test shows CI going red on the test step — both demonstrated, not just configured.

**Plans**: 4 plans
Plans:
**Wave 1**

- [ ] 12-01-PLAN.md — Committed ruff config (pyproject.toml) + mechanical autofix pass across the repo, suite verified green

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 12-02-PLAN.md — Hand-fix remaining ruff violations (TYPE_CHECKING, exception chaining, SIM117 structural collapse, E501) to a fully green `ruff check`

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 12-03-PLAN.md — ci.yml workflow (lint + test jobs) and README CI badge — lands only after the repo lints green

**Wave 4** *(blocked on Wave 3 completion)*

- [ ] 12-04-PLAN.md — Red-proof checkpoint: push throwaway branches, capture red/green run URLs, delete branches

### Phase 13: Module Structure & Boundaries

**Goal**: The three largest files in the codebase (`app/main.py` ~1,822 lines, `app/db/repo.py` ~1,765 lines / 55 functions, `app/pipeline/orchestrator.py` ~1,845 lines) are decomposed into right-sized, per-concern modules that read as intentional architecture rather than accretion, with no behavior change anywhere and no private cross-module imports left over.
**Depends on**: Phase 12 (CI must be green and gating before large mechanical refactors land, so any accidental behavior change is caught immediately)
**Requirements**: STRUCT-01, STRUCT-02, STRUCT-03, STRUCT-04, BOUND-01
**Success Criteria** (what must be TRUE):

  1. `app/main.py` is reduced to thin app assembly (app creation, router registration, filters/startup) with its routes split into APIRouter modules by concern — webhook, runs+HITL, dashboard, demo, health.
  2. `app/db/repo.py` is split into per-aggregate modules (runs / emails / roster) behind a stable import surface, so callers and tests migrate via mechanical import-path updates only.
  3. Alias-learning helpers are carved out of `app/pipeline/orchestrator.py` into their own module.
  4. The full 613-test suite passes after every split with no assertion changes — only import-path updates — proving each split is behavior-neutral.
  5. No function body anywhere in the codebase imports a `_private` name from another module (e.g. `_safe_to_learn_alias`, `_is_paid`, `_norm`, `_HOURS_FIELDS`); each has been promoted to a deliberate public name at its module's boundary.

**Plans**: TBD

### Phase 14: Full Type-Checking (mypy)

**Goal**: The entire codebase — code written before this milestone and everything going forward — is statically type-clean under mypy, and that guarantee is enforced in CI so it can't silently regress.
**Depends on**: Phase 13 (smaller, right-sized modules from the split are materially easier to annotate correctly than the three original god-files; annotating before the split would mean re-annotating after every file move)
**Requirements**: TYPE-01, TYPE-02, TYPE-03
**Success Criteria** (what must be TRUE):

  1. mypy (configured with the pydantic plugin in `pyproject.toml`) runs with zero errors over `app/`.
  2. mypy runs with zero errors over the rest of the repo (`eval/`, `scripts/`, `tests/`) — there is no type-checking blind spot anywhere in the codebase.
  3. The CI workflow from Phase 12 is extended with a blocking mypy step, so a push that introduces a type error fails CI the same way a lint or test failure does.

**Plans**: TBD

### Phase 15: Comment Hygiene & Deferred-Polish Triage

**Goal**: Comments across the codebase document constraints and invariants for a future maintainer, not this project's ticket/review history, and the two remaining pieces of v2 deferred-polish debt are explicitly closed — leaving no unaddressed loose ends at the end of the milestone.
**Depends on**: Phase 13 (comments are rewritten in the final, post-split file locations so the pass isn't redone when files move) and Phase 14 (the comment pass touches the same files mypy just annotated; doing it last avoids re-reviewing type annotations for comment-only diffs)
**Requirements**: COMM-01, COMM-02, COMM-03, POLISH-01, POLISH-02
**Success Criteria** (what must be TRUE):

  1. Ticket-ID/provenance comments (`D-21-01`, `FIX B`, `CR-01`, `(review fix)`, `Pitfall #6`, etc.) no longer appear anywhere under `app/`; wherever such a comment documented a real constraint, that constraint is preserved as a plain maintainer-facing comment with no ticket reference.
  2. The old hand-maintained 76-line function-index docstring style from `repo.py` is gone from the split DB modules, replaced by short module-purpose statements.
  3. Module docstrings across the codebase state purpose and invariants, not phase history or review provenance.
  4. Todo 260623-01 (Phase 05 review warnings) is resolved or explicitly dispositioned — WR-01 threading-after-retrigger is verified, and WR-02's Phase-8 pool-singleton fix is confirmed and the todo closed.
  5. Todo 260623-05 (fixture 10's `fixture_category` label) is corrected, and the eval chart's per-category grouping is verified unaffected by the fix.

**Plans**: TBD

## Backlog

Captured ideas not yet scheduled into a milestone live in [`backlog.md`](backlog.md). Notable candidates carried forward / deferred from v2 and v3 scope:

- Real-email A5 threading verification (Path-2 inbound proven; the deep header-survival check stays a live-gate task, not a code change)
- Frontend progressive enhancement (no build step); paystub YTD columns; eval-chart restyle away from matplotlib look (all deferred out of v3, todos 260623-02/03/04)
- Custom email domain (send FROM a real address) — documented upgrade path in README
- Additional Medicare 0.9% surtax modeling; SS wage-base straddle exactness (per-employee YTD Medicare ledger) — accepted limitations, tax-completeness features not hardening
- Schema-parity backlog: versioned/ordered migrations + migration-history table, hard deploy gate blocking Render deploy on drift — separate future milestone, needs paid plan or self-managed release step

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Thin Foundation | v1.0 | — | Complete | 2026-06-21 |
| 2. Walking Skeleton | v1.0 | — | Complete | 2026-06 |
| 2.1. Deterministic Decisioning | v1.0 | — | Complete | 2026-06 |
| 3. Harden the Calc | v1.0 | — | Complete | 2026-06 |
| 4. The Eval, the Proof | v1.0 | — | Complete | 2026-06-22 |
| 5. Dashboard & Delivery | v1.0 | — | Complete | 2026-06-23 |
| 6. Real Integration & Ship | v1.0 | — | Complete | 2026-06-25 |
| 7. Money-Correctness Deepening | v2 | 2/2 | Complete | 2026-06-28 |
| 7.5. Clarification-Reply Field-Regression | v2 | 4/4 | Complete | 2026-06-28 |
| 8. Data-Layer Hygiene & Diagnostics | v2 | 3/3 | Complete | 2026-07-02 |
| 9. Atomic Data Integrity | v2 | 6/6 | Complete | 2026-07-04 |
| 10. Concurrency Proof | v2 | 2/2 | Complete | 2026-07-07 |
| 11. Clarification Round Machine & Alias Learning | v2 | 9/9 | Complete | 2026-07-07 |
| 12. CI Quality Gates | v3 | 0/TBD | Not started | - |
| 13. Module Structure & Boundaries | v3 | 0/TBD | Not started | - |
| 14. Full Type-Checking (mypy) | v3 | 0/TBD | Not started | - |
| 15. Comment Hygiene & Deferred-Polish Triage | v3 | 0/TBD | Not started | - |
