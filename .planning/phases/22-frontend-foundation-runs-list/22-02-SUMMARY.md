---
phase: 22-frontend-foundation-runs-list
plan: 02
subsystem: testing
tags: [pytest, fastapi, starlette, jinja2, route-guards, wcag, comment-hygiene]

requires:
  - phase: 22-01
    provides: (parallel wave-1 plan; no dependency declared — depends_on: [])
provides:
  - "tests/test_route_shadowing.py — five structural guards asserting the sole Mount is /static and every reserved path resolves to its expected endpoint object"
  - "tests/test_no_html_on_service_routes.py — content-type guard over the six unauthenticated service routes"
  - "tests/test_page_shell_pins.py — first <title> coverage in the repo, plus the /runs vs /runs/{uuid} single-aria-current adjacency"
  - "tests/test_design_tokens.py widened to scan frontend/src (.ts/.tsx), with an anti-narrowing pin and the js- script-hook pin deleted with a written justification"
  - "tests/conftest.py gains a shared `client` TestClient fixture"
affects: [22-04, 22-05, 22-06, 22-07, 22-08, 22-09, 22-10, 22-11, 22-12]

actuals:
  tokens: 7200
  tasks: 3
  commits: 4

tech-stack:
  added: []
  patterns:
    - "FastAPI 0.138's lazy-include routing (_IncludedRouter/effective_route_contexts) must be flattened via duck-typing before app.router.routes can be walked for true dispatch order"
    - "Route-table structural guards assert on the resolved endpoint object, never on status code, because a catch-all mount returns 200 for everything"

key-files:
  created:
    - tests/test_route_shadowing.py
    - tests/test_no_html_on_service_routes.py
    - tests/test_page_shell_pins.py
  modified:
    - tests/test_design_tokens.py
    - tests/conftest.py

key-decisions:
  - "Added a shared `client` pytest fixture to tests/conftest.py (not in the plan's declared files) because the plan's read_first assumed one already existed; every existing test module instead duplicated its own module-level TestClient(app, ...), and the plan's own acceptance criterion required the new files to construct none."
  - "The plan's specified RED mutation for GUARD-05 (a bare StaticFiles(html=True) root Mount) does not by itself make a service route answer HTML in this Starlette version — a 404 on a StaticFiles miss returns JSON, not markup. Added a temporary app/static/404.html alongside the same mount so the mutation genuinely demonstrates the threat (StaticFiles' html-mode 404.html fallback serves real text/html), then removed it. The route-shadowing guard (which asserts on the matched route object, not the response) still reds correctly under the bare mount alone."
  - "Deleted test_script_hook_classes_carry_js_prefix_and_stay_out_of_css and its module-scope runs_list.html read together, rather than moving the read into a separate consumer — its sole consumer was the deleted test, so nothing remained to move the read into."

requirements-completed: [SHELL-01, SHELL-09, SHELL-10, GUARD-05]

coverage:
  - id: D1
    description: "Design-token/a11y guard scans .ts/.tsx and frontend/src in addition to app/templates/*.html, pins its own scan breadth against a live repo walk, and no longer depends on runs_list.html at collection time"
    requirement: "SHELL-01"
    verification:
      - kind: unit
        ref: "tests/test_design_tokens.py::test_token_scan_covers_every_present_extension"
        status: pass
      - kind: unit
        ref: "tests/test_design_tokens.py (12 tests) -x -q"
        status: pass
    human_judgment: false
  - id: D2
    description: "No catch-all route can shadow a reserved service path; the sole Mount is /static; each of ten reserved paths resolves to its expected endpoint object"
    requirement: "GUARD-05"
    verification:
      - kind: unit
        ref: "tests/test_route_shadowing.py::test_only_mount_is_static"
        status: pass
      - kind: unit
        ref: "tests/test_route_shadowing.py::test_no_route_shadows_a_reserved_prefix"
        status: pass
      - kind: unit
        ref: "tests/test_route_shadowing.py::test_unregistered_path_is_not_swallowed"
        status: pass
    human_judgment: false
  - id: D3
    description: "The six unauthenticated service routes (webhook + health + pump) never answer with an HTML content-type"
    requirement: "GUARD-05"
    verification:
      - kind: unit
        ref: "tests/test_no_html_on_service_routes.py::test_service_route_never_answers_html (parametrized x6)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every operator page declares a distinct <title>; a missing title block falls back to the base title; /runs and /runs/{uuid} both mark exactly one nav aria-current"
    requirement: "SHELL-10"
    verification:
      - kind: unit
        ref: "tests/test_page_shell_pins.py (7 tests) -x -q"
        status: pass
    human_judgment: false
  - id: D5
    description: "SHELL-09 (/ and /ops remain Jinja, /ops stays script-free) — unchanged; existing pin verified still passing, not modified"
    requirement: "SHELL-09"
    verification:
      - kind: unit
        ref: "tests/test_ops_route.py::test_ops_page_has_no_script_or_polling"
        status: pass
    human_judgment: false

duration: ~30min
completed: 2026-08-17
status: complete
---

# Phase 22 Plan 02: Guard Widening & Structural Pins Summary

**Widened the design-token/a11y guard to see the future frontend tree, added route-shadowing and no-HTML-on-service-route structural guards demonstrated red under a real injected catch-all mount, and added the repo's first per-page `<title>` coverage plus the `/runs`↔`/runs/{uuid}` single-nav-match pin — all before any markup moves.**

## Performance

- **Duration:** ~30 min
- **Tasks:** 3 of 3
- **Files modified:** 5 (3 created, 2 modified)

## Accomplishments

- `tests/test_design_tokens.py` widened: suffix allowlist gains `.ts`/`.tsx`, three scans now also walk `frontend/src` (a structural no-op today since the directory doesn't exist yet), and a new `test_token_scan_covers_every_present_extension` pins the guard's own scan breadth against a live repo walk so a future glob edit that drops an extension reds instead of silently narrowing.
- The module-scope `runs_list.html` read and its sole consumer (`test_script_hook_classes_carry_js_prefix_and_stay_out_of_css`) were deleted together, with a written justification recorded as a comment block: the `js-` convention protected a `document.querySelector` target that no longer exists once React holds the badge in component state.
- `tests/test_route_shadowing.py` (5 tests) reads the live route table from `app.main.app` and asserts: the sole `Mount` is `/static`; each of ten reserved paths resolves to its expected endpoint object; no route declares a `:path` converter; an unregistered path 404s non-HTML; and health/webhook register ahead of runs. Had to reverse-engineer FastAPI 0.138's lazy-include routing (`_IncludedRouter`/`effective_route_contexts`) since `app.router.routes` no longer flattens included routers directly in this version.
- `tests/test_no_html_on_service_routes.py` (6 parametrized cases) asserts a non-HTML content-type on the six unauthenticated service routes, reusing the hermetic `client`/`fake_repo` fixtures.
- `tests/test_page_shell_pins.py` (4 test functions, 7 collected tests) is the repo's first `<title>` coverage: every operator page declares a distinct title, a title-less template falls back to the base title (rendered through the real shared `Jinja2Templates` instance), `/runs`/`/runs/{uuid}`/`/eval`/`/ops`/`/` each mark exactly one nav `aria-current` (scoped to the `<nav>` region only), and nav link order is pinned.
- All four guards' RED-proof requirements were demonstrated and byte-identically reverted (transcripts below).
- A full-suite run surfaced a real Rule-1 bug: the new comment blocks cited `D-22-xx`/`T-22-xx` decision and task IDs, which the repo's permanent comment-provenance gate (`tests/test_comment_provenance_guard.py`, established at the v3 comment-hygiene sweep) forbids. Fixed in a follow-up commit — every citation reworded to state the reason directly.

## Task Commits

1. **Task 1: Widen the design-token and a11y guard scope before the first markup moves** - `82bc9bf` (test)
2. **Task 2: Route-shadowing and no-HTML-on-service-routes guards, both demonstrated red** - `e0911e5` (test)
3. **Task 3: Per-page title and single-aria-current pins (zero coverage today)** - `5425930` (test)
4. **Fix: strip decision/task-ID provenance citations caught by the full-suite verification** - `af824bc` (fix)

## Files Created/Modified

- `tests/test_design_tokens.py` — widened suffix allowlist + frontend/src scan, anti-narrowing pin, deleted script-hook test with justification
- `tests/test_route_shadowing.py` — new: five route-table structural guards
- `tests/test_no_html_on_service_routes.py` — new: content-type guard over six service routes
- `tests/test_page_shell_pins.py` — new: title + single-aria-current coverage
- `tests/conftest.py` — new shared `client` TestClient fixture (additive; existing module-level `TestClient(...)` instances elsewhere untouched)

## Decisions Made

- **Added `client` fixture to conftest.py (Rule 3 — missing referenced fixture).** The plan's read_first for Task 2 says the new tests must reuse "the `client` / `fake_repo` fixtures these tests must reuse rather than constructing a second `TestClient`," and Task 2's acceptance criteria explicitly require "the absence of a `TestClient(` construction in each file." No such fixture existed anywhere in `conftest.py` — every one of the ~9 existing test modules (`test_ops_route.py`, `test_dashboard.py`, `test_needs_operator.py`, etc.) instead duplicates its own module-level `client = TestClient(app, raise_server_exceptions=False)`. Rather than reintroduce that duplication a tenth time (CLAUDE.md: "DRY is critical. Flag repetition aggressively"), added a real `client` fixture matching the established `raise_server_exceptions=False` convention. This is additive only — no existing module-level instance was touched or removed.
- **The plan's literal GUARD-05 mutation (a bare `StaticFiles(html=True)` root Mount) does not make a service route answer HTML by itself.** Verified empirically: `StaticFiles.get_response` raises a plain `HTTPException(404)` on a miss when no `404.html` exists, which FastAPI's default handler serializes as JSON, not markup — so `GET /health/live` under the bare mutation returns `404 application/json`, not `200 text/html`. The route-shadowing structural guard (which asserts on the *matched route object*, not the response body) still reds correctly under the bare mount alone, proving the shadowing exists at the routing layer. To also demonstrate the no-HTML guard's RED proof — the actual threat GUARD-05 exists to catch — a temporary `app/static/404.html` was added alongside the same mount for the duration of the proof (StaticFiles' html-mode 404-fallback path then serves genuine `text/html`), then removed. Both the mount and the temp file were reverted byte-identically; `git status --porcelain` confirmed clean on `app/main.py` and `app/static/`.
- **Deleted the module-scope `runs_list.html` read alongside its sole consumer**, rather than moving it into a different test, per plan-Task-1 item 4's intent ("so a template deletion... cannot error the whole module at collection") — since the only consumer of that read was the exact test being deleted (item 5), nothing remained that needed the read moved into it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added shared `client` pytest fixture to conftest.py**
- **Found during:** Task 2 (route-shadowing / no-HTML guards)
- **Issue:** Plan's read_first and acceptance criteria assumed a `client` fixture already existed in `tests/conftest.py`; it did not. Without it, satisfying the explicit "no `TestClient(` construction in each file" acceptance criterion was impossible without either reintroducing the repo-wide duplication pattern or leaving the criterion unmet.
- **Fix:** Added a function-scoped `client` fixture in `tests/conftest.py` returning `TestClient(app, raise_server_exceptions=False)` (the repo's dominant existing convention). Wired both new guard modules and `tests/test_page_shell_pins.py` to consume it as a fixture parameter instead of constructing their own.
- **Files modified:** `tests/conftest.py`, `tests/test_route_shadowing.py`, `tests/test_no_html_on_service_routes.py`, `tests/test_page_shell_pins.py`
- **Verification:** `grep -n "TestClient(" tests/test_route_shadowing.py tests/test_no_html_on_service_routes.py` returns nothing; full suite (`tests/test_ops_route.py tests/test_dashboard.py tests/test_needs_operator.py`, which all construct their own module-level `TestClient`) still 116 passed / 3 skipped — the addition did not disturb the existing convention.
- **Committed in:** `e0911e5` (Task 2 commit)

**2. [Rule 1 - Bug] Stripped decision/task-ID provenance citations from new comments**
- **Found during:** post-Task-3 full-suite verification (`uv run pytest -q`)
- **Issue:** `tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree` — the permanent gate established at the v3 comment-hygiene sweep, forbidding decision-ID (`D-04`), task-ID (`T-8-07`), phase-ref (`Phase 9`), and planning-doc-ref (`ROADMAP.md`) citations in source comments — failed with 16 violations across the three new/widened guard files. New comment blocks I wrote had cited `D-22-15`, `D-22-16`, `D-22-06`, `D-22-01`, `D-22-05`, `T-22-05`, `T-22-06`, a `Phase 22` reference, and a `SUMMARY.md` citation.
- **Fix:** Reworded every flagged docstring/comment in `tests/test_design_tokens.py`, `tests/test_route_shadowing.py`, and `tests/test_no_html_on_service_routes.py` to state the underlying reason directly instead of citing the planning artifact that produced it. No behavior change, no test added or removed.
- **Files modified:** `tests/test_design_tokens.py`, `tests/test_route_shadowing.py`, `tests/test_no_html_on_service_routes.py`
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree -q` → 1 passed (was failing with 16 violations). Full suite re-run clean afterward.
- **Committed in:** `af824bc` (separate fix commit, after all three task commits)

---

**Total deviations:** 2 auto-fixed (1 Rule 3 — missing fixture, 1 Rule 1 — bug caught by an existing repo gate)
**Impact on plan:** Both fixes were necessary to satisfy the plan's own stated acceptance criteria and this repo's pre-existing, enforced conventions. No scope creep — no application code (`app/`) was permanently touched; every mutation used to demonstrate a RED proof was reverted byte-identically before the corresponding commit.

## Issues Encountered

**FastAPI 0.138.0's routing internals are not what the plan's read_first assumed.** `app.router.routes` does not flatten `include_router()`-registered routes into plain `APIRoute` objects the way older FastAPI versions did; each `include_router()` call is wrapped in an internal `_IncludedRouter` object whose own `matches()` discards the child scope, so walking `app.router.routes` directly cannot reveal which concrete route a request resolves to. Resolved by duck-typing (`hasattr(route, "effective_route_contexts")`) rather than importing the underscore-prefixed class name, so a future FastAPI upgrade degrades to "treat it as an opaque route" instead of an `ImportError`. Verified this reproduces the exact same ordered dispatch list as reading each router module's own `.routes` attribute directly (each router in this app registers absolute paths with no prefix, so there was no prefix-computation risk to cross-check separately).

## Known Stubs

None — this plan is pure test infrastructure; no application code, no UI, no data flow was touched.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The design-token guard, the route-shadowing/no-HTML guards, and the title/nav pins are all in place and green on the current Jinja-only app, ready for plan 22-03/22-04 (the frontend scaffold and the `/runs` tracer) to build on without going blind.
- Plan 22-04 (the tracer) must land the `frontend/` scaffold before the design-token guard's `.ts`/`.tsx` scan produces non-zero counts — that is expected and already handled: `_frontend_src_files()` treats an absent `frontend/src` as a structural no-op.
- The `js-` script-hook pin is gone; plan 22-10 (the `/runs` React conversion) is responsible for landing the replacement Vitest in-place-update test before or alongside the markup that removes `.js-status-badge`/`.js-failure-summary`/`.js-failure-secondary` from `runs_list.html`.
- The shared `client` fixture in `conftest.py` is available for any later plan's new test modules — existing modules' own `TestClient(...)` instances were left untouched and do not need migrating.
- No blockers.

## Demonstrated-RED Transcripts

Four RED proofs were required by this plan's acceptance criteria and verification block, each with a byte-identical revert.

### 1. Collection-safety proof (Task 1) — `app/templates/runs_list.html` temporarily renamed

```
tests/test_design_tokens.py::test_no_third_party_font_request
tests/test_design_tokens.py::test_font_sans_is_a_native_stack
tests/test_design_tokens.py::test_accent_and_pending_tokens_declared_at_new_values
tests/test_design_tokens.py::test_accent_soft_deleted
tests/test_design_tokens.py::test_token_scan_covers_every_present_extension
tests/test_design_tokens.py::test_superseded_accent_values_absent
tests/test_design_tokens.py::test_pending_family_tokens_are_the_single_source
tests/test_design_tokens.py::test_accent_and_pending_contrast_clears_aa
tests/test_design_tokens.py::test_narrow_breakpoint_adjusts_shell_and_controls
tests/test_design_tokens.py::test_muted_ink_contrast_clears_aa
tests/test_design_tokens.py::test_button_modifiers_do_not_redeclare_base_properties
tests/test_design_tokens.py::test_button_modifier_classes_always_compose_the_base

12 tests collected in 0.01s
EXIT_CODE=0
```

Collection exits 0 with `runs_list.html` absent — proving collection no longer depends on the template's existence. Reverted: `mv app/templates/runs_list.html.bak app/templates/runs_list.html`; `git status --porcelain app/templates/` returned empty.

### 2. Route-shadowing + no-HTML guards RED — injected root `Mount("/", StaticFiles(..., html=True))` + a temporary `app/static/404.html`

Mutation confirmed live source via `grep -n 'app.mount("/", StaticFiles' app/main.py` → `12:app.mount("/", StaticFiles(directory="app/static", html=True), name="root_catchall")`.

```
FAILED tests/test_route_shadowing.py::test_only_mount_is_static - AssertionError: expected the sole Mount to be ['/static'], found ['/static', '']
FAILED tests/test_route_shadowing.py::test_no_route_shadows_a_reserved_prefix - AssertionError: POST /webhook/inbound matched a non-APIRoute route Mount(path='', name='root_catchall', ...)
FAILED tests/test_route_shadowing.py::test_unregistered_path_is_not_swallowed - AssertionError: unregistered path answered with content-type 'text/html; charset=utf-8'
FAILED tests/test_no_html_on_service_routes.py::test_service_route_never_answers_html[/health/live] - AssertionError: GET /health/live answered with content-type 'text/html; charset=utf-8' (status 404)
FAILED tests/test_no_html_on_service_routes.py::test_service_route_never_answers_html[/health/ready] - AssertionError: GET /health/ready answered with content-type 'text/html; charset=utf-8' (status 404)
FAILED tests/test_no_html_on_service_routes.py::test_service_route_never_answers_html[/health/queue] - AssertionError: GET /health/queue answered with content-type 'text/html; charset=utf-8' (status 404)
FAILED tests/test_no_html_on_service_routes.py::test_service_route_never_answers_html[/health/schema] - AssertionError: GET /health/schema answered with content-type 'text/html; charset=utf-8' (status 404)
FAILED tests/test_no_html_on_service_routes.py::test_service_route_never_answers_html[/internal/pump] - AssertionError: GET /internal/pump answered with content-type 'text/html; charset=utf-8' (status 404)
8 failed, 3 passed, 1 warning in 0.56s
```

`POST /webhook/inbound` stayed green under the no-HTML guard — StaticFiles' 405-for-POST path returns JSON, a different, still-correctly-non-HTML failure mode, not a gap in the guard (the route-shadowing test's `test_no_route_shadows_a_reserved_prefix` independently proves POST /webhook/inbound IS shadowed at the routing layer, shown above).

Reverted: `rm -f app/static/404.html && git checkout -- app/main.py`. `git diff --stat app/main.py` returned empty; `git status --porcelain app/static/ app/main.py` returned empty.

### 3. Title-block deletion RED (Task 3) — `{% block title %}` line removed from `app/templates/runs_list.html`

```
FAILED tests/test_page_shell_pins.py::test_every_operator_page_declares_a_distinct_title[/runs]
AssertionError: GET /runs rendered the bare base fallback title 'Pyrl' — it must declare its own {% block title %}
assert 'Pyrl' != 'Pyrl'
1 failed, 3 passed, 1 warning in 0.51s
```

Reverted: `git checkout -- app/templates/runs_list.html`; `git diff --stat app/templates/runs_list.html` returned empty.

### 4. Duplicate `aria-current` RED (Task 3) — unconditional `aria-current="page"` added to the Ops nav link in `app/templates/base.html`

Mutation confirmed live source via `grep -n 'aria-current="page"' app/templates/base.html` → line 15: `<a href="/ops" aria-current="page"{% if nav_path.startswith('/ops') %} aria-current="page"{% endif %}>Ops</a>`.

```
FAILED tests/test_page_shell_pins.py::test_exactly_one_aria_current_per_page
AssertionError: GET / must mark exactly one nav item aria-current="page" within the <nav> region; found 2
assert 2 == 1
1 failed, 1 warning in 0.49s
```

Reverted: `git checkout -- app/templates/base.html`; `git diff --stat app/templates/base.html` returned empty; `grep -n aria-current` afterward showed all four nav links back to their single-conditional form.

## Self-Check: PASSED

- FOUND: tests/test_route_shadowing.py
- FOUND: tests/test_no_html_on_service_routes.py
- FOUND: tests/test_page_shell_pins.py
- FOUND: tests/test_design_tokens.py
- FOUND: tests/conftest.py
- FOUND: 82bc9bf (test(22-02): widen design-token/a11y guard to frontend/src, drop js-hook pin)
- FOUND: e0911e5 (test(22-02): add route-shadowing and no-HTML-on-service-routes guards)
- FOUND: 5425930 (test(22-02): add per-page title and single-aria-current pins (SHELL-10))
- FOUND: af824bc (fix(22-02): strip decision/task-ID provenance citations from new guard comments)

---
*Phase: 22-frontend-foundation-runs-list*
*Completed: 2026-08-17*
