---
phase: 12
reviewers: [codex]
reviewed_at: 2026-07-09T14:51:34Z
plans_reviewed: [12-01-PLAN.md, 12-02-PLAN.md, 12-03-PLAN.md, 12-04-PLAN.md]
---

# Cross-AI Plan Review — Phase 12

## Codex Review

**Summary**  
The plans are materially strong and mostly executable. I verified the main ruff baseline: `ruff 0.15.18` reports 416 violations with `E,F,I,B,UP,SIM` at line length 100, including the stated 46 `SIM117` sites. The workflow patterns also match the existing GitHub Actions house style. The main issues are dependency/branch hygiene, hard-coded post-autofix counts, and a few rule-fix details that could create avoidable churn or later mypy friction.

**Strengths**
- The phase sequencing is conceptually sound: configure ruff, clean baseline, add CI, then prove red/green behavior.
- `SIM117` is correctly called out as structurally risky enough to isolate from the mechanical autofix pass.
- The CI command requirements are crisp: `uv run ruff check .` and `uv run pytest -q` exactly, which supports CI-03.
- The red-proof plan directly validates the acceptance criterion rather than treating YAML as proof.
- The no-blanket-ignore policy is appropriate for the milestone’s “production-quality” goal.

**Concerns**
- **HIGH:** Current worktree is dirty with many unrelated `.planning` deletions. Any plan that commits or creates throwaway branches needs an explicit `git status --short` preflight and pathspec staging, or it risks committing unrelated deletions.
- **MEDIUM:** `12-03-PLAN.md` has `depends_on: []`, but it relies on the ruff config from 12-01 and ideally the clean lint baseline from 12-02. If landed early, `ci.yml` will likely make pushed branches red immediately.
- **MEDIUM:** Plan 12-01 hard-codes post-autofix expectations (`222 remaining`, “269 fixed”) while ruff’s own count semantics are inconsistent with simple arithmetic. I verified `--fix --diff --unfixable SIM117` says “Would fix 269 errors,” but I could not safely apply it in this read-only sandbox to confirm the remaining count.
- **MEDIUM:** Plan 12-02’s UP047 fix should preserve the existing `TypeVar(..., bound=BaseModel)` constraint. Use `def call_structured[T: BaseModel](...) -> T`, not an unbounded `T`.
- **LOW:** Plan 12-03’s YAML verification with PyYAML proves syntax only, not GitHub Actions semantics. That is acceptable, but it should not be treated as full workflow validation.
- **LOW:** Plan 12-04 deletes local branches without explicitly checking out `master` first. If the executor is still on a throwaway branch, local deletion will fail or leave cleanup incomplete.

**Suggestions**
- Add a cross-plan preflight: `git status --short`, confirm only expected dirty files, and use `git add <specific paths>` for every commit.
- Change 12-03 frontmatter to `depends_on: ["12-01", "12-02"]`, or at minimum `["12-01"]` with an explicit “do not push/land before 12-02 is green” gate.
- Replace exact post-autofix count gates with measured gates: “no I001/UP017/F401/UP037/SIM300/UP035 remain” and “SIM117 still reports 46 sites.” Record the actual remaining count in the summary after execution.
- In 12-04, explicitly `git switch master && git pull --ff-only` before creating each red-proof branch, and `git switch master` before deleting local branches.
- Add `target-version = "py312"` to `[tool.ruff]` for explicitness, even though ruff can infer from `requires-python`.
- For workflow validation, use `actionlint` if available; otherwise keep the PyYAML check but label it as YAML syntax validation only.

**Risk Assessment**  
Overall risk: **MEDIUM**. The plans achieve the phase goals if executed carefully, and the technical direction is solid. The biggest risks are operational rather than architectural: dirty-worktree commits, dependency ordering that can create premature red CI, and brittle exact-count assertions around ruff autofix behavior. Fixing those would bring the plan set close to low risk.

---

## Consensus Summary

Single external reviewer (Codex, GPT-5 series via codex CLI) — consensus is drawn against the internal gsd-plan-checker's three verification rounds.

### Agreed Strengths
- Phase sequencing (config → autofix → hand-fix/CI in parallel → red-proof) is sound; both Codex and the internal checker independently endorsed isolating SIM117 from the mechanical autofix pass.
- CI commands are exactly `uv run ruff check .` / `uv run pytest -q`, satisfying CI-03's byte-for-byte local/CI agreement.
- The red-proof plan (12-04) validates the gates behaviorally rather than treating the YAML as proof.
- Codex independently reproduced the 416-violation baseline and the 46 SIM117 sites — matching the internal checker's empirical verification.

### Agreed Concerns
- **Exact-count brittleness (Codex MEDIUM; internal checker touched this in round 2):** the 269-fixed/222-remaining figures are measured but ruff's count semantics make exact-count acceptance gates brittle; rule-absence gates ("no I001/UP017/F401/UP037/SIM300/UP035 remain; SIM117 still reports 46") are more robust.

### Divergent Views / New Findings (Codex only — not caught internally)
- **HIGH — dirty worktree:** many unrelated `.planning` deletions are sitting in the working tree; any plan that commits or pushes throwaway branches must preflight `git status --short` and stage by pathspec, or it risks committing unrelated deletions.
- **MEDIUM — 12-03 dependency:** `depends_on: []` lets ci.yml land in wave 2 before 12-02 finishes the cleanup, making every push red in the interim. Suggested `depends_on: ["12-01"]` minimum, ideally an explicit do-not-land-before-12-02-green gate (12-04 already depends on both).
- **MEDIUM — UP047 fix detail:** the generic-syntax rewrite must preserve the existing `TypeVar(..., bound=BaseModel)` bound — `def call_structured[T: BaseModel](...)`, not an unbounded `T` (mypy friction in Phase 14 otherwise).
- **LOW — 12-04 branch hygiene:** `git switch master` before creating/deleting throwaway branches.
- **LOW — PyYAML check scope:** it proves YAML syntax only, not Actions semantics; label it as such (or use actionlint if available).
