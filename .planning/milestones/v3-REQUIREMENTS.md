# v3 — Production-Ready Codebase — Requirements (ARCHIVED)

**Status:** Complete — 16/16 satisfied
**Audit:** [v3-MILESTONE-AUDIT.md](../v3-MILESTONE-AUDIT.md) — PASSED
**Verified:** three-source cross-reference (phase VERIFICATION.md + SUMMARY frontmatter +
traceability table). Zero orphans; zero requirements claimed but not defined.

---

# Requirements — Milestone v3: Production-Ready Codebase

**Defined:** 2026-07-08
**Goal:** Make the entire existing codebase read as production-quality — surface and substance — for the hiring-manager/recruiter audience: enforced CI quality gates, right-sized modules, full type-checking, and comments that document constraints instead of process history.

**Ordering constraint:** module splits (STRUCT) land BEFORE the comment pass (COMM), so comments aren't edited in files about to move. Every refactor is behavior-neutral, guarded by the existing 613-test suite.

## v3 Requirements

### CI Quality Gates (CI)

- [x] **CI-01**: Every push runs `ruff check` in CI and fails the build on any lint error
- [x] **CI-02**: Every push runs the full hermetic test suite (`uv run pytest -q`) in CI and fails the build on any test failure
- [x] **CI-03**: A committed ruff configuration in `pyproject.toml` defines the ruleset (rule selection, line length) so local and CI results agree

### Module Structure (STRUCT)

- [x] **STRUCT-01**: `app/main.py` (~1,822 lines) is split into APIRouter modules by concern (webhook / runs+HITL / dashboard / demo / health), leaving `main.py` as thin app assembly (app creation, router registration, filters/startup)
- [x] **STRUCT-02**: `app/db/repo.py` (~1,765 lines, 55 functions) is split into per-aggregate modules (runs / emails / roster) with a stable import surface so callers and tests migrate mechanically
- [x] **STRUCT-03**: Alias-learning helpers are carved out of `app/pipeline/orchestrator.py` (~1,845 lines) into their own module
- [x] **STRUCT-04**: Every split is behavior-neutral — the full test suite passes with no assertion changes (import-path updates only)

### Type Checking (TYPE)

- [x] **TYPE-01**: mypy (with the pydantic plugin) is configured in `pyproject.toml` and runs clean over `app/`
- [x] **TYPE-02**: mypy runs clean over the rest of the codebase (`eval/`, `scripts/`, `tests/`) — the entire repo is type-clean, code written before and going forward
- [x] **TYPE-03**: mypy is a blocking check in the CI workflow

### Comment Hygiene (COMM)

- [x] **COMM-01**: Ticket-ID/provenance comments (`D-21-01`, `FIX B`, `CR-01`, `(review fix)`, `Pitfall #6`…) are stripped across `app/`, preserving the constraints they document as plain maintainer-facing comments
- [x] **COMM-02**: The hand-maintained function-index docstring style (repo.py's 76-line table of contents) is replaced with short module-purpose statements across the split DB modules
- [x] **COMM-03**: Module docstrings state purpose and invariants, not phase history or review provenance

### Module Boundaries (BOUND)

- [x] **BOUND-01**: Cross-module `_private` imports (`_safe_to_learn_alias`, `_is_paid`, `_norm`, `_HOURS_FIELDS`) are promoted to deliberate public names; no function-body private imports remain

### Deferred-Polish Triage (POLISH)

- [x] **POLISH-01**: Phase 05 review warnings (todo 260623-01) are resolved or explicitly dispositioned — WR-01 threading-after-retrigger verified; WR-02 pool singleton was already fixed in Phase 8 (verify and close the todo)
- [x] **POLISH-02**: Fixture 10's `fixture_category` label is corrected and the eval chart's per-category grouping verified unaffected (todo 260623-05)

## Future Requirements

Deferred to later milestones:

- Versioned/ordered migrations + migration-history table (schema-parity backlog)
- Hard deploy gate blocking Render deploy on drift (schema-parity backlog; needs paid plan or self-managed release step)
- Frontend progressive enhancement, no build step (todo 260623-02)
- Paystub YTD columns (todo 260623-03)
- Eval chart restyle away from matplotlib look (todo 260623-04)

## Out of Scope

| Item | Reason |
|------|--------|
| Any behavior change to pipeline/money logic | This milestone is refactor + tooling only; the 613-test suite must pass unmodified |
| Schema-parity backlog (migrations, deploy gate) | Infrastructure work, separate future milestone |
| SPA / frontend framework adoption | Locked project decision (no build step) |
| Dashboard auth | Known/accepted demo posture (WR-3) |
| pyright | mypy chosen (conventional for Python-only repos, official pydantic plugin, plain uv dev dep) |

## Traceability

| REQ-ID | Phase |
|--------|-------|
| CI-01 | Phase 12 |
| CI-02 | Phase 12 |
| CI-03 | Phase 12 |
| STRUCT-01 | Phase 13 |
| STRUCT-02 | Phase 13 |
| STRUCT-03 | Phase 13 |
| STRUCT-04 | Phase 13 |
| TYPE-01 | Phase 14 |
| TYPE-02 | Phase 14 |
| TYPE-03 | Phase 14 |
| COMM-01 | Phase 15 |
| COMM-02 | Phase 15 |
| COMM-03 | Phase 15 |
| BOUND-01 | Phase 13 |
| POLISH-01 | Phase 15 |
| POLISH-02 | Phase 15 |

---

## Final Traceability

| Requirement | Phase | Verification | Outcome |
|-------------|-------|--------------|---------|
| CI-01 | 12 | passed (12/12) | **satisfied** — ruff blocking on push |
| CI-02 | 12 | passed | **satisfied** — full hermetic suite blocking |
| CI-03 | 12 | passed | **satisfied** — committed ruff config in pyproject.toml |
| STRUCT-01 | 13 | passed (5/5) | **satisfied** — main.py 1,857 → 16 lines, 5 APIRouters |
| STRUCT-02 | 13 | passed | **satisfied** — repo.py → per-aggregate package + facade (63 names) |
| STRUCT-03 | 13 | passed | **satisfied** — alias helpers carved out of orchestrator.py |
| STRUCT-04 | 13 | passed | **satisfied** — behavior-neutral; suite green, import-path changes only |
| BOUND-01 | 13 | passed | **satisfied** — `_private` imports promoted; AST guard proven able to fail |
| TYPE-01 | 14 | passed (3/3) | **satisfied** — mypy strict clean over app/ |
| TYPE-02 | 14 | passed | **satisfied** — clean over eval/, scripts/, tests/ (117 files total) |
| TYPE-03 | 14 | passed | **satisfied** — blocking `Type check (mypy --strict)` CI job, red-proofed |
| COMM-01 | 15 | passed (5/5) | **satisfied** — provenance stripped; CI guard pinned to a harvested family inventory |
| COMM-02 | 15 | passed | **satisfied** — repo.py's 76-line function index replaced with module-purpose statements |
| COMM-03 | 15 | passed | **satisfied** — docstrings state invariants, not phase history |
| POLISH-01 | 15 | passed | **satisfied** — WR-01 threading proved (mutation-tested); WR-05 path traversal and the prompt-echo leak fixed test-first |
| POLISH-02 | 15 | passed | **satisfied** — fixture-10 relabel; exposed a real eval-chart defect (exact.f1 0.96 → 1.00) |

## Notes on requirements that changed shape

- **POLISH-01** was scoped as "resolve or explicitly disposition the Phase 05 review warnings." It
  grew: WR-01 turned out to be no bug at all (the epoch machinery already held), so it became a
  permanent regression gate proved capable of failing by mutation testing. Two *new* security issues
  surfaced while working in the area — a live path traversal and a prompt-echo leak — and were fixed
  test-first with genuine RED evidence.
- **POLISH-02** was filed as cosmetic ("no eval impact"). True of accuracy, false of the chart: the
  mislabel was misreporting an entire category. Fixing it moved `exact.f1` 0.96 → 1.00 and
  `typo.f1` 1.00 → 0.90 (n=2, now honestly carrying the intentional miss). Overall F1 (0.9889) and
  the confusion matrix (`false_process = 0`) unchanged — relabeling rebuckets, it does not rescore.
- **COMM-01** was the hardest to actually satisfy. Stripping the comments was easy; making the
  removal *stick* was not. The guard shipped green four times while blind to a ticket family or an
  entire directory. Final form asserts the pattern table against the real inventory harvested from
  git history, and pins the no-false-positive half so it can never fail CI on live requirement IDs.
