# Requirements — Milestone v3: Production-Ready Codebase

**Defined:** 2026-07-08
**Goal:** Make the entire existing codebase read as production-quality — surface and substance — for the hiring-manager/recruiter audience: enforced CI quality gates, right-sized modules, full type-checking, and comments that document constraints instead of process history.

**Ordering constraint:** module splits (STRUCT) land BEFORE the comment pass (COMM), so comments aren't edited in files about to move. Every refactor is behavior-neutral, guarded by the existing 613-test suite.

## v3 Requirements

### CI Quality Gates (CI)

- [x] **CI-01**: Every push runs `ruff check` in CI and fails the build on any lint error
- [x] **CI-02**: Every push runs the full hermetic test suite (`uv run pytest -q`) in CI and fails the build on any test failure
- [ ] **CI-03**: A committed ruff configuration in `pyproject.toml` defines the ruleset (rule selection, line length) so local and CI results agree

### Module Structure (STRUCT)

- [ ] **STRUCT-01**: `app/main.py` (~1,822 lines) is split into APIRouter modules by concern (webhook / runs+HITL / dashboard / demo / health), leaving `main.py` as thin app assembly (app creation, router registration, filters/startup)
- [ ] **STRUCT-02**: `app/db/repo.py` (~1,765 lines, 55 functions) is split into per-aggregate modules (runs / emails / roster) with a stable import surface so callers and tests migrate mechanically
- [ ] **STRUCT-03**: Alias-learning helpers are carved out of `app/pipeline/orchestrator.py` (~1,845 lines) into their own module
- [ ] **STRUCT-04**: Every split is behavior-neutral — the full test suite passes with no assertion changes (import-path updates only)

### Type Checking (TYPE)

- [ ] **TYPE-01**: mypy (with the pydantic plugin) is configured in `pyproject.toml` and runs clean over `app/`
- [ ] **TYPE-02**: mypy runs clean over the rest of the codebase (`eval/`, `scripts/`, `tests/`) — the entire repo is type-clean, code written before and going forward
- [ ] **TYPE-03**: mypy is a blocking check in the CI workflow

### Comment Hygiene (COMM)

- [ ] **COMM-01**: Ticket-ID/provenance comments (`D-21-01`, `FIX B`, `CR-01`, `(review fix)`, `Pitfall #6`…) are stripped across `app/`, preserving the constraints they document as plain maintainer-facing comments
- [ ] **COMM-02**: The hand-maintained function-index docstring style (repo.py's 76-line table of contents) is replaced with short module-purpose statements across the split DB modules
- [ ] **COMM-03**: Module docstrings state purpose and invariants, not phase history or review provenance

### Module Boundaries (BOUND)

- [ ] **BOUND-01**: Cross-module `_private` imports (`_safe_to_learn_alias`, `_is_paid`, `_norm`, `_HOURS_FIELDS`) are promoted to deliberate public names; no function-body private imports remain

### Deferred-Polish Triage (POLISH)

- [ ] **POLISH-01**: Phase 05 review warnings (todo 260623-01) are resolved or explicitly dispositioned — WR-01 threading-after-retrigger verified; WR-02 pool singleton was already fixed in Phase 8 (verify and close the todo)
- [ ] **POLISH-02**: Fixture 10's `fixture_category` label is corrected and the eval chart's per-category grouping verified unaffected (todo 260623-05)

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
