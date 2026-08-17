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

Filled after planning — task IDs do not exist until PLAN.md files are written. Requirement-level
mapping is already fixed below and each task must inherit its requirement's command.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 22-01-01 | 01 | 1 | GUARD-01 | — | N/A | hermetic | `uv run pytest tests/test_inventory_completeness.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

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

- [ ] `frontend/` scaffold (`npm create vite@latest frontend -- --template react-ts`) — also resolves
      Open Question 1 (exact Vite manifest path / multi-entry `rollupOptions.input` shape) as a side effect
- [ ] `frontend/vitest.config.ts` — framework install, `test.environment: "jsdom"`
- [ ] `tests/test_inventory_completeness.py` — GUARD-01 (must land before any conversion commit)
- [ ] `tests/test_safety_mutation_registry.py` — GUARD-02's mutation-pinned subset
- [ ] `tests/test_route_shadowing.py` — SHELL-01 / GUARD-05 catch-all-absence half
- [ ] `tests/test_react_page_render.py` — SHELL-02
- [ ] `tests/test_bundle_asset_exists.py` — SHELL-05 hermetic half
- [ ] `tests/test_schema_projection.py` — SHELL-07 / GUARD-04
- [ ] `tests/test_no_html_on_service_routes.py` — GUARD-05
- [ ] `tests/test_no_fetch_outside_poller.py` — GUARD-06 Python-side half
- [ ] A `<title>`-per-page pin — SHELL-10; zero existing coverage in the repo today

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
