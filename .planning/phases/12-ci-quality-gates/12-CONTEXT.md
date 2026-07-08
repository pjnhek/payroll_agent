# Phase 12: CI Quality Gates - Context

**Gathered:** 2026-07-08
**Status:** Ready for planning

<domain>
## Phase Boundary

A GitHub Actions workflow `ci.yml` runs `ruff check` and the full hermetic test suite (`uv run pytest -q`) on every push, backed by a committed ruff configuration in `pyproject.toml`, so every subsequent v3 refactor phase (module splits, mypy, comment pass) is protected by lint+test CI from the start. Requirements: CI-01, CI-02, CI-03. Behavior-neutral: no pipeline/money behavior changes; the existing test suite is the safety net for the lint-cleanup diff.

</domain>

<decisions>
## Implementation Decisions

### Ruff ruleset & existing-violation cleanup
- **D-01:** Committed ruleset is a curated extended set: `E`, `F`, `I` (import sorting), `B` (bugbear), `UP` (pyupgrade), `SIM` (simplify) — a deliberate production config, not the bare defaults.
- **D-02:** Line length = **100**. (Measured: 160 existing lines exceed 100; 1,297 exceed 88 — 100 is the manageable, deliberate choice.)
- **D-03:** Bring the repo to green by **fixing everything, zero blanket ignores**. Autofix the mechanical bulk; hand-fix the rest. A `noqa` is allowed only where individually justified with a stated reason. No per-file-ignore blocks in the config.
- **D-04:** The 7 existing F821 errors are quoted `"Employee"` forward-references in test helpers (imports inside functions) — fix properly with `TYPE_CHECKING` imports, not suppressions.
- **D-05:** Lint only — `ruff check` per CI-01. No `ruff format --check` gate in this phase (formatter adoption deferred; see Deferred Ideas).
- **D-06:** Lint scope is the whole repo (`app/`, `eval/`, `scripts/`, `tests/`) — CI-03 says local and CI results must agree byte-for-byte, so the CI command and local command are identical.

### Workflow triggers & structure
- **D-07:** `ci.yml` triggers on **push to ALL branches** + `workflow_dispatch` (literal reading of "every push"; makes the criterion-4 red-proof a simple branch push). This deliberately differs from the 4 existing workflows, which are master-only.
- **D-08:** `ci.yml` is a **new standalone workflow**; `eval.yml`, `keepalive.yml`, `deploy-migrate.yml`, `concurrency-proof.yml` are left untouched.
- **D-09:** Per-branch concurrency group with `cancel-in-progress: true` (lint/test runs are safely cancellable — unlike deploy-migrate, which correctly uses `cancel-in-progress: false`).
- **D-10:** **Two parallel jobs — `lint` and `test`** — so each gate is its own named red/green check on the commit and criterion 4's "red on the lint step / red on the test step" is directly visible.

### Test lane
- **D-11:** The test job runs **bare `uv run pytest -q` with no DB service and no marker flags**. The suite's existing two-factor env guards (`DATABASE_URL`+`ALLOW_DB_RESET=1` for live-DB; `ALLOW_LIVE_LLM` for live-LLM) make it hermetic in CI by design — skips are intentional, not omissions. No duplication of `concurrency-proof.yml`'s Postgres-backed integration lane.
- **D-12:** No minimum-passed-test-count guard against mass-skipping — pinned counts are permanent maintenance burden and can't catch design-level vacuousness anyway.
- **D-13:** No coverage measurement or gate in this phase.

### Red-proof demonstration & visibility
- **D-14:** Criterion-4 red-proof: push **throwaway branches** (one per failure mode — injected lint error, deliberately broken test), capture the red run URLs plus the green master run URL in the phase VERIFICATION.md, then delete the branches. Red runs remaining in Actions history are acceptable (they show the gates work).
- **D-15:** Add a **ci.yml status badge to README.md** — the recruiter-facing visible face of the gate. (Single badge; no eval badge row.)
- **D-16:** CI stays an **after-the-fact signal**: no branch protection / required checks on master. Direct pushes (the solo GSD commit flow) are preserved.

### Claude's Discretion
- Exact ruff config layout in `pyproject.toml` (`[tool.ruff]` / `[tool.ruff.lint]` sections, isort settings).
- uv caching in CI (`enable-cache` on `astral-sh/setup-uv`), action version pins, job names — follow the established house pattern in the existing workflows.
- Order and grouping of the cleanup commits (e.g., autofix commit separate from hand-fix commits) as long as each is behavior-neutral and the suite passes at every commit.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements & milestone framing
- `.planning/ROADMAP.md` — Phase 12 goal, success criteria 1–4, and the v3 dependency chain (CI must land before Phases 13–15).
- `.planning/REQUIREMENTS.md` — CI-01, CI-02, CI-03 exact wording.

### Existing CI house pattern (reuse, don't reinvent)
- `.github/workflows/eval.yml` — hermetic push-time gate pattern: `astral-sh/setup-uv@v5` + `python-version: "3.12"` + `uv sync`.
- `.github/workflows/deploy-migrate.yml` — concurrency-group pattern (note: it uses `cancel-in-progress: false` for good reason; ci.yml uses `true`).
- `.github/workflows/concurrency-proof.yml` — the Postgres-backed integration lane ci.yml must NOT duplicate.

### Tooling rules
- `CLAUDE.md` §Tooling Rule — uv-only environment; `uv run` for every command; no pip/requirements.txt.
- `pyproject.toml` — where the ruff config lands; existing `[tool.pytest.ini_options]` marker registrations.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- 4 existing workflows establish the setup recipe: checkout@v4 → `astral-sh/setup-uv@v5` with Python 3.12 → `uv sync` → `uv run …`. ci.yml should read as a sibling of these.
- `ruff` is already a dev dependency (`[dependency-groups].dev`) — no dependency change needed, only config + cleanup.

### Established Patterns
- Hermeticity via two-factor env guards in `tests/conftest.py` (`_HAS_DB` + `ALLOW_DB_RESET`) and `tests/test_live_llm.py` (`ALLOW_LIVE_LLM`) — CI gets hermetic behavior for free by simply not setting those vars.
- `eval.yml` sets `DATABASE_URL: "placeholder"` for its job; the planner should verify whether the test job needs the same stub for settings validation (conftest monkeypatches it per-test, so likely not — verify, don't assume).

### Integration Points
- Baseline violation inventory (measured 2026-07-08, default rules): 42 errors — 30 F401 unused-import (autofixable), 7 F821 (quoted forward-refs in `tests/test_calculate.py`, `tests/test_detect_field_regression.py`, etc.), 3 E402 (deliberate late imports in `tests/test_gateway.py` with existing noqa-style comments), 2 F841. The curated set + 100-char limit will add more findings (~160 E501 lines plus I/UP/B/SIM hits) — the cleanup diff is the bulk of the phase's code churn.
- 663 tests collected; suite must stay green at every cleanup commit.
- Phase 14 will extend this same `ci.yml` with a mypy job — keep the workflow structured so adding a third job is trivial.

</code_context>

<specifics>
## Specific Ideas

- The badge + the recorded red-run links serve the milestone's hiring-manager audience: the gate must be *visibly* enforced, not just configured.
- Success criterion 3 (local `uv run ruff check` agrees byte-for-byte with CI) means the CI lint step must be exactly that command with no extra flags or path arguments.

</specifics>

<deferred>
## Deferred Ideas

- **`ruff format --check` as a CI gate** — one-time whole-repo reformat; if ever adopted, the cheapest moment is before the Phase 13 file moves. Explicitly not in Phase 12.
- **Coverage reporting/gating (pytest-cov)** — considered and rejected for this phase; candidate for a future milestone if a legible number is wanted.
- **Branch protection requiring green CI on master** — rejected for now (would force PR round-trips on the solo GSD flow); revisit if the repo ever gains collaborators.

### Reviewed Todos (not folded)
- `260623-01` (Phase 05 review warnings) and `260623-05` (fixture_category label) — tagged `resolves_phase: 15` (POLISH-01/POLISH-02); keyword match with Phase 12 was a false positive.
- `260623-02/03/04` (frontend enhancement, paystub YTD, eval-chart restyle) — explicitly deferred out of v3 per ROADMAP backlog.

</deferred>

---

*Phase: 12-CI Quality Gates*
*Context gathered: 2026-07-08*
