---
phase: 22-frontend-foundation-runs-list
reviewed: 2026-08-17T00:00:00Z
depth: standard
files_reviewed: 66
files_reviewed_list:
  - .dockerignore
  - .github/workflows/ci.yml
  - .gitignore
  - Dockerfile
  - README.md
  - app/config.py
  - app/routes/runs.py
  - app/routes/templating.py
  - app/schemas/__init__.py
  - app/schemas/_projection.py
  - app/schemas/run_columns.py
  - app/schemas/run_status.py
  - app/schemas/runs_list.py
  - app/templates/react_page.html
  - app/templates/runs_list.html
  - docs/ASSERTION-INVENTORY.md
  - frontend/.gitignore
  - frontend/MANIFEST-SHAPE.md
  - frontend/README.md
  - frontend/eslint.config.js
  - frontend/package-lock.json
  - frontend/package.json
  - frontend/src/boot/pageData.ts
  - frontend/src/components/ConfirmForm.tsx
  - frontend/src/components/DecisionBanner.test.tsx
  - frontend/src/components/DecisionBanner.tsx
  - frontend/src/components/FailureSummary.tsx
  - frontend/src/components/MutationForm.test.tsx
  - frontend/src/components/MutationForm.tsx
  - frontend/src/components/QueueBadge.tsx
  - frontend/src/components/StatusBadge.tsx
  - frontend/src/entries/runs.tsx
  - frontend/src/generated/dtos.d.ts
  - frontend/src/hooks/usePoller.test.ts
  - frontend/src/hooks/usePoller.ts
  - frontend/src/pages/RunsPage.test.tsx
  - frontend/src/pages/RunsPage.tsx
  - frontend/src/test/setup.ts
  - frontend/src/types/banner.ts
  - frontend/src/vite-env.d.ts
  - frontend/tsconfig.json
  - frontend/tsconfig.node.json
  - frontend/vite.config.ts
  - frontend/vitest.config.ts
  - scripts/generate_openapi_doc.py
  - scripts/render_assertion_inventory.py
  - tests/assertion_inventory.py
  - tests/conftest.py
  - tests/fixtures/vite_manifest.json
  - tests/safety_mutation_registry.py
  - tests/test_bundle_asset_exists.py
  - tests/test_ci_gate_config.py
  - tests/test_dashboard.py
  - tests/test_design_tokens.py
  - tests/test_generated_types_staleness.py
  - tests/test_inventory_completeness.py
  - tests/test_needs_operator.py
  - tests/test_no_fetch_outside_poller.py
  - tests/test_no_html_on_service_routes.py
  - tests/test_page_shell_pins.py
  - tests/test_react_dev_mode.py
  - tests/test_react_page_render.py
  - tests/test_route_shadowing.py
  - tests/test_safety_mutation_registry.py
  - tests/test_schema_projection.py
  - tests/test_stuck_run_recovery.py
findings:
  critical: 0
  warning: 1
  info: 1
  total: 2
status: issues_found
---

# Phase 22: Code Review Report

**Reviewed:** 2026-08-17
**Depth:** standard
**Files Reviewed:** 66 (all source files changed `4c756bb..HEAD`, `.planning/` excluded)
**Status:** issues_found (1 warning, 1 info — no blockers)

## Summary

I read every file in the six risk areas the assignment ranked highest — the allowlist DTO
projection (`_projection.py`, `runs_list.py`, `run_columns.py`, `run_status.py`,
`runs.py`), the manifest loader and JSON data-island render path
(`templating.py`, `react_page.html`), the dev-mode branch (`config.py`), the Docker
multi-stage build, `usePoller.ts`, and `MutationForm`/`ConfirmForm.tsx` — plus their
paired test suites, the CI workflow, the generated DTO file, and the SQL-to-DTO field
mapping. I traced the real `load_all_runs` SQL against `RunListRow`'s declared fields and
`EXCLUDED` set by hand (not just by reading the guard tests) and confirmed every column
the query selects is accounted for.

I could not find a way to make a PII/internal field reach the browser, break the
`<script type="application/json">` boundary, or reach the dev-server code path in a
deployed container. The XSS-escaping in `json_script()` (`app/routes/templating.py:93`)
is the standard Django `json_script` pattern and is exercised by a genuine hostile-input
test (`tests/test_react_page_render.py:102`) that asserts on the raw, unparsed response
text, not just the parsed JSON — a meaningfully strong proof. `ConfirmForm`'s
`preventDefault()`-based cancellation (the actual footgun the component exists to close)
is correctly implemented and tested against the event's `defaultPrevented` state, never a
handler return value. The Docker build's frontend stage, `.dockerignore`, and the
`docker-build` CI job together close the "gitignored dist directory" deploy trap this
milestone was explicitly built around.

This phase's own test suite is unusually adversarial against itself — most guards ship
with a negative control, a "walk visited something" sanity check, and a synthetic-offender
proof, closing exactly the "guard that scans nothing" failure class this project has hit
before. One guard in that suite did NOT get that treatment when converting `/runs`: see
WR-01 below.

## Warnings

### WR-01: The runs_list read-only AST guard lost its only positive pin on the render step

**File:** `tests/test_stuck_run_recovery.py:43-60` (the weakened assertion), compare
`app/routes/runs.py:919` (the call it no longer sees)

**Issue:** `test_runs_list_ast_is_read_only_and_has_no_background_tasks_parameter` proves
read-only-ness by asserting the exact set of `module.attr(...)`-shaped calls
(`_qualified_call`, `tests/test_stuck_run_recovery.py:24`) found in `runs_list`'s own
source text. Before this phase, that set was
`{"logger.debug", "repo.load_all_runs", "router.get", "templates.TemplateResponse"}` — four
items, one of which (`templates.TemplateResponse`) was the render call itself, so *any*
edit to that call site (swapped for a different qualified call, or for an unqualified one)
would change the set and fail the test.

After this phase, the render call is `render_react_page(...)` — a bare-name import, not an
attribute call — so `_qualified_call` returns `None` for it and it is silently dropped
from the scanned set entirely (the test's own comment at line 49 says so explicitly). The
expected set shrank to three items with no entry standing in for the render step at all.
Concretely: if a future edit replaced `render_react_page(request, ...)` with a bare-name
call to some other helper — including a hypothetical one that internally reaches
`repo.claim_status(...)` or `wake.wake()` — `calls` would be unchanged
(`{"logger.debug", "repo.load_all_runs", "router.get"}`) and this specific test would keep
passing. The docstring's claim ("The route shape permits only list reads, presentation,
and rendering") is no longer backed by what the assertion actually checks for that one
call site.

Mitigating factor, so this doesn't read as worse than it is: the sibling test in the same
file, `test_runs_list_returns_200_without_touching_any_mutation_or_schedule_seam`
(`tests/test_stuck_run_recovery.py:72`), monkeypatches the real mutation/enqueue/resume
seams (`repo.claim_status`, `repo.set_status`, `repo.enqueue_job`, `wake.wake`,
`drain.drain_once`, etc.) to raise on call and drives a real `GET /runs`. That guard
operates on the function objects, not on call-site text shape, so it *would* catch a
mutation reached through `render_react_page` or any other bare-name helper, regardless of
how it's spelled in `runs_list`'s source. The practical exposure from WR-01 is therefore
narrower than the AST test's docstring alone suggests — but it is still a real, demonstrated
loss of what that specific test proves, and it is exactly the "guard that scans a narrower
surface than it appears to" pattern this project has been bitten by before (see
`tests/test_no_fetch_outside_poller.py`'s own docstring, which treats an analogous gap as
worth a deliberate primary/redundant-secondary split rather than silence).

**Fix:** (recommendation first)

A. **Extend the guard to also enumerate unqualified (bare-name) calls found in
   `runs_list`'s body, and assert that set equals the small known-safe list
   (`render_react_page`, `RunsListPage`) it should be.** Cheap (a second `ast.walk` pass
   collecting `ast.Call` nodes whose `.func` is an `ast.Name`), restores the exact
   protective property the old `templates.TemplateResponse` entry provided, and matches
   this same phase's own established pattern of pairing every AST-based guard with a
   completeness/negative-control companion (`test_no_fetch_outside_poller.py`,
   `test_inventory_completeness.py`, `test_safety_mutation_registry.py`). Recommended
   because it is the cheapest fix that is also consistent with the rigor this phase
   already applied everywhere else it touched an AST-scanning guard.
B. **Do nothing**, relying on `test_runs_list_returns_200_without_touching_any_mutation_or_schedule_seam`'s
   function-level seam patching, which — as argued above — already catches the actual
   mutation risk regardless of call-site shape. Reasonable if the team judges the AST
   test's textual-shape proof to be redundant now that a stronger behavioral proof exists
   in the same file, and doesn't want to maintain a second bare-name allowlist that would
   need updating on every legitimate new helper call.
C. Delete `test_runs_list_ast_is_read_only_and_has_no_background_tasks_parameter`
   outright and fold its still-useful argument-shape assertion
   (`function.args.args == ["request", "notice"]`) into a comment on the behavioral test.
   Only worth doing if (A) is rejected as not worth the upkeep — leaving a test whose
   docstring overstates its own coverage is worse than removing it.

## Info

### IN-01: `DecisionBanner`/`types/banner.ts` ship in this phase with zero production consumers

**File:** `frontend/src/components/DecisionBanner.tsx`, `frontend/src/types/banner.ts`

**Issue:** Neither file is imported by `RunsPage.tsx` or `entries/runs.tsx` — the only
route this phase actually mounts. `DecisionBanner` exists solely for its own test file
(`DecisionBanner.test.tsx`) today; nothing in the `/runs` page tree reaches it. This is
scaffolding for Phase 23's run-detail page, and the code says so directly (component
docstring: "Phase 23 fills in each arm's full body"). Not a defect — the exhaustiveness
check it demonstrates (`renderBranch`'s `never`-typed default arm) is real and tested —
but it is, by strict definition, dead code in this phase's own diff, and worth naming so
it doesn't get missed if it silently rots before Phase 23 actually wires it in.

**Fix:** No action needed now. If Phase 23 stalls or is rescoped, revisit whether
`DecisionBanner.tsx`/`banner.ts` should be deleted (and reintroduced when the run-detail
conversion actually lands) rather than carried forward unused.

---

_Reviewed: 2026-08-17_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
