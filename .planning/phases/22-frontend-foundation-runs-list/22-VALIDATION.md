---
phase: 22
slug: frontend-foundation-runs-list
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-17
---

# Phase 22 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded from `22-RESEARCH.md` `## Validation Architecture`. The Per-Task Verification Map
> is filled once PLAN.md task IDs exist; everything else below is measured or research-verified.

---

## Test Infrastructure

This phase has **two** test stacks. Both must be sampled — a green Python suite proves nothing
about the React bundle, and vice versa.

| Property | Value |
|----------|-------|
| **Framework (Python)** | pytest 9.1.1 — config in `pyproject.toml` `[tool.pytest.ini_options]` |
| **Framework (frontend)** | Vitest 4.1.10 + `@testing-library/react` 16.3.2 + jsdom 30.0.1 — **config file does not exist yet** (`frontend/vitest.config.ts` is a Wave 0 gap) |
| **Config file** | `pyproject.toml` (Python) · `frontend/vitest.config.ts` (none — Wave 0 installs) |
| **Quick run command** | `uv run pytest -q -x -k <pattern>` · `npm run test -- <pattern>` |
| **Full suite command** | `uv run pytest -q` · `npm run test` |
| **Estimated runtime** | Python: **1,510 tests collected** (measured during research) · frontend: n/a until Wave 0 |

**Scope gap to respect:** `pyproject.toml` `[tool.mypy] files = ["app", "eval", "scripts", "tests"]`
does not include `frontend/`. Nothing Python-side will ever lint, typecheck, or scan the frontend —
the `npm run check` command and the CI `frontend` job are the *only* gates on that half.

---

## Sampling Rate

- **After every task commit:** `uv run pytest -q -x <relevant file>` (Python side) and, once the
  toolchain exists, `npm run check && npm run test` (frontend side)
- **After every plan wave:** full suite **both sides** — `uv run pytest -q` and `npm run test`
- **Before `/gsd-verify-work`:** all 5 CI jobs green — `lint`, `test`, `typecheck`, `frontend`,
  `docker build` — plus a live deploy check: `git rev-list --count origin/master..master` == 0,
  then load the live `/runs` URL (v4 Phase 21 shipped CI-green-but-unpushed; this closes that hole)
- **Max feedback latency:** 60 seconds for the per-task quick run

---

## Per-Task Verification Map

Filled at planning, 2026-08-17. 12 plans, 35 tasks, 6 waves. Every task carries an `<automated>`
verify; the one checkpoint (22-03-01) is a blocking package-legitimacy gate and is verified by human
confirmation rather than a command.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 22-01-01 | 01 | 1 | GUARD-01 | T-22-01 | registry entries re-resolve against live source | hermetic | `uv run python -c "from tests.assertion_inventory import ASSERTION_INVENTORY"` + ruff + mypy | ❌ creates | ⬜ pending |
| 22-01-02 | 01 | 1 | GUARD-01 | T-22-01/03 | AST walk, no execution of parsed files | hermetic | `uv run pytest tests/test_inventory_completeness.py -x -q` | ❌ creates | ⬜ pending |
| 22-01-03 | 01 | 1 | GUARD-01 | T-22-02 | conversion-ordering gate blocks a merge | CI + hermetic | `uv run python scripts/render_assertion_inventory.py --check` | ❌ creates | ⬜ pending |
| 22-02-01 | 02 | 1 | SHELL-10 | T-22-07 | guard scan cannot silently narrow | hermetic | `uv run pytest tests/test_design_tokens.py -x -q` | ✅ modifies | ⬜ pending |
| 22-02-02 | 02 | 1 | SHELL-01, GUARD-05 | T-22-05/06 | no catch-all; service routes never HTML | hermetic | `uv run pytest tests/test_route_shadowing.py tests/test_no_html_on_service_routes.py -x -q` | ❌ creates | ⬜ pending |
| 22-02-03 | 02 | 1 | SHELL-09, SHELL-10 | T-22-08 | per-page title, single nav match | hermetic | `uv run pytest tests/test_page_shell_pins.py -x -q` | ❌ creates | ⬜ pending |
| 22-03-01 | 03 | 2 | SHELL-06 | T-22-SC | package legitimacy confirmed before install | blocking human checkpoint | — (human confirmation; never auto-approvable) | — | ⬜ pending |
| 22-03-02 | 03 | 2 | SHELL-04, SHELL-06 | T-22-SC/11 | pinned versions, committed lockfile | build | `cd frontend && npm ci && npm run build` | ❌ creates | ⬜ pending |
| 22-03-03 | 03 | 2 | SHELL-04, SHELL-06 | T-22-09/10/12 | network-call, form and raw-markup bans | lint + unit | `cd frontend && npm run check && npm run test` | ❌ creates | ⬜ pending |
| 22-04-01 | 04 | 3 | SHELL-01, SHELL-02, SHELL-03, SHELL-07 | T-22-13/14/15/16/17 | allowlist DTO, island escaping, fail-closed manifest | hermetic (parse island from `response.text`) | `uv run pytest tests/test_react_page_render.py tests/test_schema_projection.py -x -q` | ❌ creates | ⬜ pending |
| 22-04-02 | 04 | 3 | GUARD-01 | T-22-01 | rewritten assertions cannot go vacuous | hermetic | `uv run pytest tests/test_dashboard.py tests/test_inventory_completeness.py -q` | ✅ modifies | ⬜ pending |
| 22-04-03 | 04 | 3 | SHELL-05 | T-22-15/18 | image build fails without a bundle | image build + hermetic | `uv run pytest tests/test_bundle_asset_exists.py -x -q` + real `docker build` from `git archive` export | ❌ creates | ⬜ pending |
| 22-05-01 | 05 | 4 | SHELL-05, SHELL-06 | T-22-19/21/22/23 | pre-merge trigger inherited, clone-based build | CI config | `uv run pytest tests/test_ci_gate_config.py -x -q` | ✅ modifies | ⬜ pending |
| 22-05-02 | 05 | 4 | SHELL-06 | T-22-20 | untouchable directories fenced | CI config | `uv run pytest tests/test_ci_gate_config.py -x -q` | ✅ modifies | ⬜ pending |
| 22-05-03 | 05 | 4 | SHELL-06 | T-22-19/20/21 | gate config itself covered and red-proven | hermetic | `uv run pytest tests/test_ci_gate_config.py -x -q` | ❌ creates | ⬜ pending |
| 22-06-01 | 06 | 4 | LIST-01 | T-22-24/26 | text nodes only, server-owned vocabulary | Vitest component | `cd frontend && npm run test -- RunsPage` | ❌ creates | ⬜ pending |
| 22-06-02 | 06 | 4 | LIST-01 | T-22-25 | failure never renders as an empty list | Vitest component | `cd frontend && npm run test -- RunsPage` | ✅ modifies | ⬜ pending |
| 22-06-03 | 06 | 4 | LIST-04 | T-22-27 | scroll region structure; manual 375px check | Vitest + manual | `cd frontend && npm run test -- RunsPage`; Chrome DevTools at 375/374/376px | ⚠️ partial | ⬜ pending |
| 22-07-01 | 07 | 4 | SHELL-07 | T-22-30/31 | enforced response model, unchanged wire body | hermetic | `uv run pytest tests/test_dashboard.py -k status -q` | ❌ creates | ⬜ pending |
| 22-07-02 | 07 | 4 | GUARD-04 | T-22-29/32 | every column deliberately classified | hermetic | `uv run python -c "from app.schemas.run_columns import RUN_COL_CLASSIFICATION"` | ❌ creates | ⬜ pending |
| 22-07-03 | 07 | 4 | GUARD-04 | T-22-28 | new column fails CI by name | hermetic | `uv run pytest tests/test_schema_projection.py -x -q` | ✅ modifies | ⬜ pending |
| 22-08-01 | 08 | 4 | SHELL-03 | T-22-33/34/37 | native form; decline cancels via prevent-default | Vitest component | `cd frontend && npm run test -- MutationForm` | ❌ creates | ⬜ pending |
| 22-08-02 | 08 | 4 | SHELL-03 | T-22-35/36 | armless banner variant is a compile error | Vitest + typecheck | `cd frontend && npm run test -- DecisionBanner && npm run check` | ❌ creates | ⬜ pending |
| 22-09-01 | 09 | 4 | SHELL-04 | T-22-38/39 | dev branch unreachable in a deployed image | hermetic | `uv run pytest tests/test_react_dev_mode.py -x -q` | ❌ creates | ⬜ pending |
| 22-09-02 | 09 | 4 | SHELL-04 | T-22-40/41 | explicit proxy prefixes; redirect origin measured | manual (two servers) | `cd frontend && npm run check` + recorded redirect-origin measurements | ✅ modifies | ⬜ pending |
| 22-09-03 | 09 | 4 | SHELL-04 | T-22-42 | documented commands were executed | manual (documented in README) | `npm run dev`; `npm run check` | ✅ modifies | ⬜ pending |
| 22-10-01 | 10 | 5 | LIST-02, GUARD-06 | T-22-45/47 | teardown observable, single request call site | Vitest (fake timers) | `cd frontend && npm run test -- usePoller` | ❌ creates | ⬜ pending |
| 22-10-02 | 10 | 5 | LIST-02 | T-22-46 | settled rows never poll; in-place badge update | Vitest component | `cd frontend && npm run test -- RunsPage` | ✅ modifies | ⬜ pending |
| 22-10-03 | 10 | 5 | GUARD-06 | T-22-43/44 | two independent enforcement paths, non-vacuous | hermetic text scan | `uv run pytest tests/test_no_fetch_outside_poller.py -x -q` | ❌ creates | ⬜ pending |
| 22-11-01 | 11 | 5 | SHELL-07 | T-22-50/51 | deterministic generation, no new HTTP surface | hermetic | `uv run python scripts/generate_openapi_doc.py` | ❌ creates | ⬜ pending |
| 22-11-02 | 11 | 5 | SHELL-07 | T-22-49 | withheld field is a compile error | typecheck | `cd frontend && npm run check && npm run test` | ✅ modifies | ⬜ pending |
| 22-11-03 | 11 | 5 | SHELL-06 | T-22-48/52 | stale declarations fail CI, no runtime skip | hermetic + CI | `uv run pytest tests/test_generated_types_staleness.py tests/test_ci_gate_config.py -x -q` | ❌ creates | ⬜ pending |
| 22-12-01 | 12 | 6 | GUARD-02 | T-22-53/57 | safety pins resolve; hermetic, not DB-gated | hermetic | `uv run pytest tests/test_safety_mutation_registry.py -x -q` | ❌ creates | ⬜ pending |
| 22-12-02 | 12 | 6 | GUARD-02 | T-22-53 | every pin demonstrated able to fail | mutation sweep | `uv run pytest tests/test_safety_mutation_registry.py -x -q` + recorded per-entry red runs | ✅ modifies | ⬜ pending |
| 22-12-03 | 12 | 6 | LIST-03, SHELL-03, GUARD-01 | T-22-54/55/56 | notice channel allowlisted; replacement trail closed | hermetic | `uv run pytest tests/test_dashboard.py tests/test_inventory_completeness.py -x -q` | ✅ modifies | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Sampling continuity:** no three consecutive tasks lack an automated verify — the only task without
one is the blocking package-legitimacy checkpoint 22-03-01, and both of its plan siblings carry
automated commands.

### Requirement → command map (research-verified, inherited by tasks)

| Req ID | Test Type | Automated Command | File Exists? |
|--------|-----------|-------------------|--------------|
| SHELL-01 | integration + hermetic | `uv run pytest tests/test_route_shadowing.py -x` | ❌ W0 |
| SHELL-02 | hermetic (parse `__INITIAL_DATA__` out of `response.text`) | `uv run pytest tests/test_react_page_render.py -x` | ❌ W0 |
| SHELL-03 | hermetic (`TestClient` never executes JS — this IS the no-JS case) | `uv run pytest tests/test_dashboard.py -k demo_send_test -x` | ✅ existing, must pass unmodified |
| SHELL-04 | manual (documented in README) | `npm run dev`; `npm run check` | — |
| SHELL-05 | CI job + hermetic existence check | `docker build .` (new CI job); `uv run pytest tests/test_bundle_asset_exists.py -x` | ❌ W0 |
| SHELL-06 | CI trigger config (not a pytest) | `frontend` job's `on:` block includes `pull_request` | ❌ W0 (CI config) |
| SHELL-07 | hermetic | `uv run pytest tests/test_schema_projection.py -x` | ❌ W0 |
| SHELL-09 | hermetic, existing | `uv run pytest tests/test_ops_route.py::test_ops_page_has_no_script_or_polling -x` | ✅ existing, stay green unmodified |
| SHELL-10 | hermetic, existing + 1 new pin | `uv run pytest tests/test_dashboard.py -k aria_current -x`; new `<title>` pin | ⚠️ partial — **zero** existing `<title>` coverage |
| GUARD-01 | hermetic | `uv run pytest tests/test_inventory_completeness.py -x` | ❌ W0 — the phase's first plan |
| GUARD-02 | mutation-pinned subset | `uv run pytest tests/test_safety_mutation_registry.py -x` | ❌ W0 |
| GUARD-04 | hermetic | `uv run pytest tests/test_schema_projection.py::test_every_run_col_is_classified -x` | ❌ W0 |
| GUARD-05 | hermetic | `uv run pytest tests/test_no_html_on_service_routes.py -x` | ❌ W0 |
| GUARD-06 | ESLint + hermetic text-scan | `npm run lint`; `uv run pytest tests/test_no_fetch_outside_poller.py -x` | ❌ W0 |
| LIST-01 | Vitest component test (positive, exact-shape) | `npm run test -- RunsPage` | ❌ W0 |
| LIST-02 | Vitest (teardown-observable) | `npm run test -- usePoller` | ❌ W0 |
| LIST-03 | hermetic, existing (route-level) | `uv run pytest tests/test_dashboard.py -k demo_send_test -x` | ✅ existing, re-verify it covers the `demo_queue_error` branch |
| LIST-04 | manual visual check | Chrome DevTools responsive mode at 375px | ❌ no automated pin exists |

---

## Wave 0 Requirements

Every gap below is assigned to a named plan and task; none is left to be discovered during execution.

- [ ] `frontend/` scaffold — plan 22-03 task 2. Also resolves Open Question 1 (real manifest path and
      the multi-entry input shape), recorded in `frontend/MANIFEST-SHAPE.md` BEFORE plan 22-04 writes
      the loader
- [ ] `frontend/vitest.config.ts` + `frontend/src/test/setup.ts` — plan 22-03 task 3
- [ ] `tests/assertion_inventory.py` + `tests/test_inventory_completeness.py` — plan 22-01 tasks 1-2
      (GUARD-01; must land before any conversion commit, enforced by a CI step in 22-01 task 3)
- [ ] `tests/test_design_tokens.py` widening — plan 22-02 task 1 (must land before any markup moves)
- [ ] `tests/test_route_shadowing.py` + `tests/test_no_html_on_service_routes.py` — plan 22-02 task 2
- [ ] `tests/test_page_shell_pins.py` (per-page `<title>` pin, zero existing coverage) — plan 22-02 task 3
- [ ] `tests/test_react_page_render.py` + `tests/test_schema_projection.py` — plan 22-04 task 1
- [ ] `tests/test_bundle_asset_exists.py` — plan 22-04 task 3
- [ ] `tests/test_ci_gate_config.py` — plan 22-05 task 3
- [ ] `tests/test_react_dev_mode.py` — plan 22-09 task 1
- [ ] `tests/test_no_fetch_outside_poller.py` — plan 22-10 task 3
- [ ] `tests/test_generated_types_staleness.py` — plan 22-11 task 3
- [ ] `tests/safety_mutation_registry.py` + `tests/test_safety_mutation_registry.py` — plan 22-12 tasks 1-2
- [ ] A 375px-overflow automated pin — still NOT created. jsdom performs no layout, so no automated
      pin is written; plan 22-06 task 3 performs and records a manual measurement at 375/374/376px and
      leaves LIST-04's manual row open if no browser is available

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| One dev command + one typecheck/lint command work as documented | SHELL-04 | A test asserting "a developer can run this" would assert the script key exists, not that it works; the real proof is running it | `npm run dev` serves with hot reload against uvicorn; `npm run check` typechecks + lints and exits non-zero on either failure |
| No horizontal overflow at 375px; wide table scrolls inside its own keyboard-reachable region | LIST-04 | No automated 375px pin exists in this repo; matches existing precedent (quick task `260726-ugm` was manually verified) | Chrome DevTools responsive mode at 375px: page body does not scroll horizontally; table region is reachable and scrollable via keyboard alone |
| Live deploy renders the React `/runs` from the Docker-built bundle | SHELL-05 | The SHELL-05 trap (`.gitignore` `dist/` + `COPY . .`) is invisible to a local build by construction — only a build from the Git clone exposes it | After push: confirm `git rev-list --count origin/master..master` == 0, then load the live Render `/runs` and confirm rows render (not a blank console) |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags (Vitest must run `--run`, not watch, in CI and in task verify commands)
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
