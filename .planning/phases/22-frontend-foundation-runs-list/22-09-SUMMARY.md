---
phase: 22-frontend-foundation-runs-list
plan: 09
subsystem: ui
tags: [vite, fastapi, jinja2, dev-server, proxy, pydantic-settings]

# Dependency graph
requires:
  - phase: 22-frontend-foundation-runs-list
    provides: "render_react_page()/load_manifest()/react_page.html from plan 22-04, the
      shared entrypoint and shell this plan's dev branch extends"
provides:
  - "Settings.vite_dev_server_url -- the fail-closed local-dev opt-in that switches
    render_react_page() between the Vite build manifest (production) and the Vite dev
    client + raw entry source (dev)"
  - "frontend/vite.config.ts's server.proxy -- an explicitly enumerated (no catch-all)
    dev-server proxy to uvicorn, live-verified to preserve the dev origin across a 303
    redirect"
  - "README.md Frontend development section -- the two developer commands (npm run dev,
    npm run check) an operator needs, each run by the executor before being documented"
affects: [23, 24]

# Actuals (#2632)
actuals:
  tokens: 4671
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Settings field defaulting to the disabled value (empty string), with the
      consuming function taking a single early return on the non-default branch so the
      production code path can never be reached through the dev path's code -- same
      convention as the pump token / ALLOW_UNSIGNED_FIXTURES / demo-operator-email
      fail-closed fields"
    - "Vite server.proxy enumerated from the live route table (app/main.py's
      APIRouters + the static mount), never a catch-all; the bare root path uses a
      regex key (Vite treats any proxy key starting with '^' as a RegExp tested
      against the full URL) rather than a string-prefix entry, since a plain '/' key
      would prefix-match every path"

key-files:
  created:
    - tests/test_react_dev_mode.py
  modified:
    - app/config.py
    - app/routes/templating.py
    - app/templates/react_page.html
    - frontend/vite.config.ts
    - tests/assertion_inventory.py
    - README.md

key-decisions:
  - "app/templates/react_page.html required a change beyond this plan's stated
    files_modified list (app/config.py, app/routes/templating.py,
    frontend/vite.config.ts, tests/test_react_dev_mode.py, README.md). The dev branch
    cannot emit the Vite dev client as a second <script type=\"module\"> tag without
    extending the shared shell every React page renders through -- there is no way to
    satisfy the task's own acceptance criteria (dev client module present in a dev-mode
    render) without it. Treated as a Rule 3 (blocking) deviation, not a scope
    expansion: the change is a single conditional script tag, additive, and does not
    touch the production branch's existing markup."
  - "render_react_page() keeps ONE early return for the dev branch, not a shared
    context dict mutated in place. When Settings.vite_dev_server_url is set, the
    function returns from inside that branch before the manifest-loading code below it
    is ever reached; when it is unset, that branch's body never executes at all. This
    is what makes 'the production path cannot be reached through the dev path's code'
    a structural property of the function rather than a documentation claim."
  - "The Vite dev-server proxy targets uvicorn on :8000 explicitly (BACKEND_TARGET),
    matching the port named in this task's own precondition
    (uv run uvicorn app.main:app --port 8000) and the README's documented workflow --
    not a configurable value, since this is a local-only dev affordance with one
    conventional pairing."

patterns-established:
  - "Pattern: fail-closed dev-server setting, single early return, dev branch never
    reads the manifest"
  - "Pattern: enumerated (non-catch-all) Vite dev-server proxy derived from the live
    route table, with a regex key for the one exact-match root path"

requirements-completed: [SHELL-04]

coverage:
  - id: D1
    description: "A dev-server setting defaults off; a default-settings render of /runs
      emits no developer-host URL; the production fail-closed manifest behavior is
      unchanged; the image build never sets the setting"
    requirement: "SHELL-04"
    verification:
      - kind: unit
        ref: "tests/test_react_dev_mode.py::test_default_settings_render_emits_no_developer_host_url"
        status: pass
      - kind: unit
        ref: "tests/test_react_dev_mode.py::test_default_settings_missing_manifest_still_raises"
        status: pass
      - kind: unit
        ref: "tests/test_react_dev_mode.py::test_dev_setting_enabled_renders_dev_client_and_skips_manifest"
        status: pass
      - kind: unit
        ref: "tests/test_react_dev_mode.py::test_dockerfile_never_sets_the_dev_server_env_var"
        status: pass
    human_judgment: false
  - id: D2
    description: "The Vite dev server proxies an explicitly enumerated route list (no
      catch-all) to uvicorn, and a 303 redirect the app emits through the dev origin
      lands back on the dev origin, not uvicorn's origin -- the specific failure mode
      the architecture research named for this proxy direction"
    requirement: "SHELL-04"
    verification:
      - kind: other
        ref: "live check against a throwaway local Postgres + uvicorn :8000 +
          Vite dev server :5173 -- see 'Redirect-Origin Check' section below for raw
          header values"
        status: pass
    human_judgment: false
  - id: D3
    description: "The README documents exactly two developer commands (npm run dev,
      npm run check), each actually run by the executor before being written down"
    requirement: "SHELL-04"
    verification:
      - kind: other
        ref: "npm ci / npm run dev / npm run check all run this session -- see
          'README Commands Run' section below"
        status: pass
    human_judgment: false

duration: ~50min
completed: 2026-08-17
status: complete
---

# Phase 22 Plan 09: Frontend Dev Server (Vite Proxy to Uvicorn) + README Summary

**A `VITE_DEV_SERVER_URL` setting that defaults off and gates a fail-closed dev branch in
`render_react_page()`, a Vite dev-server proxy to uvicorn enumerated from the live route table
(no catch-all), a live-verified 303 redirect that stays on the dev origin, and README
instructions for the two developer commands -- all pinning the SHELL-04 risk the architecture
research flagged for this proxy direction.**

## Performance

- **Duration:** ~50 min
- **Tasks:** 3 of 3 complete
- **Files modified:** 7 (1 created, 6 modified) across 3 commits

## Accomplishments

- `app/config.py` gained `Settings.vite_dev_server_url` (empty-string default, the
  production-safe value), following the pump-token/`ALLOW_UNSIGNED_FIXTURES`/demo-operator-email
  convention of defaulting to the safe state and refusing rather than degrading.
- `app/routes/templating.py::render_react_page()` branches on that setting with a single early
  return: dev-mode emits the Vite dev client module and the entry's raw source path from the
  configured origin and never reads the manifest; production resolves hashed asset paths through
  the manifest exactly as before, still raising `ManifestMissingError` when it is absent.
- `app/templates/react_page.html` gained one conditional script tag for the dev client module
  (see Deviations -- this file was not in the plan's stated `files_modified`).
- `tests/test_react_dev_mode.py` (4 tests) asserts all four required properties: a
  default-settings render carries no `localhost` substring or the configured dev origin's value;
  the production fail-closed manifest behavior is unchanged; the dev branch renders successfully
  with the manifest pointed at a nonexistent file; the Dockerfile text never contains
  `VITE_DEV_SERVER_URL`.
- `frontend/vite.config.ts` gained a `server.proxy` section forwarding every non-Vite-served
  request path to uvicorn, enumerated from `app/main.py`'s live route table (health, webhook,
  runs, dashboard, demo, pump/internal, ops routers, plus the static mount) -- 9 entries, no
  catch-all. The bare root path (`/`) uses a regex key (`"^/$"`) rather than a string-prefix
  entry, confirmed against Vite's own source (`context[0] === "^"` triggers RegExp matching,
  otherwise `url.startsWith(context)`) since a plain `"/"` string key would prefix-match every
  request.
- The redirect-origin failure mode the architecture research named was checked for real, not
  assumed -- see "Redirect-Origin Check" below.
- `README.md` gained a "Frontend development" section documenting `npm ci`, the two-process
  dev workflow (`VITE_DEV_SERVER_URL` exported before uvicorn, `npm run dev` in a second
  terminal), and `npm run check` -- see "README Commands Run" below for what was actually
  executed.
- Full suite: 1453 passed / 107 skipped (baseline 1449/107 plus 4 new tests in
  `test_react_dev_mode.py`; 5 assertions folded into the existing `assertion_inventory.py`
  registry, no new test functions from that file). `ruff check .` and `uv run mypy` both clean
  (191 source files). `cd frontend && npm run check` exits 0.

## Task Commits

1. **Task 1: A dev-server setting that defaults off and a fail-closed dev branch in the page
   renderer** -- `6259380` (feat)
2. **Task 2: Vite dev server proxying to uvicorn, with the redirect-origin failure mode
   checked** -- `caff873` (feat)
3. **Task 3: README developer instructions for both commands** -- `84a6378` (docs)

## Files Created/Modified

**Task 1 (`6259380`):**
- `app/config.py` -- `Settings.vite_dev_server_url` field
- `app/routes/templating.py` -- `render_react_page()` dev/production branch split
- `app/templates/react_page.html` -- optional dev-client `<script>` tag (deviation, see below)
- `tests/test_react_dev_mode.py` -- 4 tests covering all required mitigations
- `tests/assertion_inventory.py` -- GUARD-01 registry entries for 5 new `.text` comparisons

**Task 2 (`caff873`):**
- `frontend/vite.config.ts` -- `server.proxy` section

**Task 3 (`84a6378`):**
- `README.md` -- Frontend development section

## Decisions Made

- **`app/templates/react_page.html` required editing despite being outside this plan's stated
  `files_modified` list.** The dev branch cannot emit a second `<script type="module">` tag for
  the Vite dev client without extending the one shared shell every React-rendered page renders
  through (`react_page.html`). Without this change, Task 1's own acceptance criterion (a
  dev-mode render must actually emit the dev client module) is unsatisfiable. Applied as a
  single additive conditional block (`{% if dev_client_src %}...{% endif %}`) that leaves the
  existing production markup untouched -- documented here as a Rule 3 (blocking) deviation
  rather than silently expanded scope.
- **`render_react_page()` keeps a single early return for the dev branch**, not a shared
  mutable context dict. This makes "the production path cannot be reached through the dev
  path's code" a structural guarantee (the manifest-loading code physically cannot execute when
  the dev branch's `return` has already fired) rather than a comment asserting intent.
- **The Vite proxy targets `http://localhost:8000` as a fixed constant**, matching the port
  named in Task 2's own precondition and the README's documented two-process workflow. This is a
  local-only dev affordance with one conventional pairing, not a value that needed to be
  configurable.
- **`changeOrigin: false` set explicitly on every proxy entry**, rather than using Vite's string
  shorthand (which defaults `changeOrigin: true`). `changeOrigin` only rewrites the outbound
  `Host` header sent to uvicorn and has no effect on the proxied response's `Location` header --
  confirmed by reading Vite's own bundled proxy middleware source
  (`frontend/node_modules/vite/dist/node/chunks/node.js`) -- but explicit `false` keeps the
  config self-documenting about "no origin rewriting" rather than relying on a reader knowing
  the shorthand's hidden default.

## Redirect-Origin Check

Performed for real against a throwaway local Postgres (Docker `postgres:16`, removed after this
check), bootstrapped and seeded via `app/db/bootstrap.py` and `app/db/seed.py`. Two processes:

```
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/payroll \
  WORKER_COUNT=0 VITE_DEV_SERVER_URL=http://localhost:5173 \
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

cd frontend && npm run dev -- --port 5173 --strictPort
```

`WORKER_COUNT=0` kept the durable queue from spawning real workers (no live LLM calls); both
routes below produce their redirect entirely inside the synchronous route handler, before any
queued job is drained, so this does not affect the check.

**Route 1 -- `POST /demo/send-test` through the dev origin:**

```
$ curl -sD - -o /dev/null http://localhost:5173/demo/send-test -X POST -d "fixture_key=coastal_exact"
HTTP/1.1 303 See Other
location: /runs/46cf1b63-0d0e-447d-baa7-b9111c919280
```

Raw `location` header value: `/runs/46cf1b63-0d0e-447d-baa7-b9111c919280` (relative, no
scheme/host). Following the redirect (`curl -sL`, letting curl demote 303 to GET as a browser
does):

```
$ curl -sL -o /dev/null -w "final_url:%{url_effective}\nfinal_status:%{http_code}\n" \
    http://localhost:5173/demo/send-test --data "fixture_key=summit_exact"
final_url:http://localhost:5173/runs/32555656-c555-40fc-8a64-4598417583db
final_status:200
```

**Landing origin: `localhost:5173` (the dev origin). PASS** -- not `localhost:8000` (uvicorn's
origin), the failure mode the architecture research named.

**Route 2 -- `POST /runs/{run_id}/approve` through the dev origin** (second redirecting
operator route, so the result is not a single-sample claim; `WORKER_COUNT=0` means the run never
reaches `awaiting_approval`, so `claim_status` legitimately loses the claim and the route takes
its `notice_redirect` branch -- still a real 303 through the identical code path a successful
approval uses):

```
$ curl -sD - -o /dev/null http://localhost:5173/runs/32555656-c555-40fc-8a64-4598417583db/approve -X POST
HTTP/1.1 303 See Other
location: /runs/32555656-c555-40fc-8a64-4598417583db?notice=approve_claim_lost
```

Raw `location` header value: `/runs/32555656-c555-40fc-8a64-4598417583db?notice=approve_claim_lost`
(relative). Following the redirect:

```
$ curl -sL -o /dev/null -w "final_url:%{url_effective}\nfinal_status:%{http_code}\n" \
    http://localhost:5173/runs/32555656-c555-40fc-8a64-4598417583db/approve --data ""
final_url:http://localhost:5173/runs/32555656-c555-40fc-8a64-4598417583db?notice=approve_claim_lost
final_status:200
```

**Landing origin: `localhost:5173` (the dev origin). PASS.**

Both processes and the Postgres container were torn down after this check
(`pkill -f uvicorn`, `pkill -f "vite --port 5173"`, `docker rm -f p22-dev-pg`); `git status
--short` confirmed only `frontend/vite.config.ts` carried a tracked change afterward.

Also spot-checked the remaining proxy entries through the dev origin while the servers were up
(all `200`): `/` (root, exact-match regex entry), `/health/live`, `/ops`, `/eval`,
`/static/style.css`.

## README Commands Run

Every command documented in README.md's new Frontend development section was run by this
executor before being written down:

- **`cd frontend && npm ci`** -- ran during Task 2 setup: `added 258 packages, and audited 259
  packages in 2s`, `found 0 vulnerabilities`.
- **`npm run dev` (Vite dev server)** -- ran for the Redirect-Origin Check above:
  `VITE v8.2.1 ready in 783 ms`, served at `http://localhost:5173`, proxied every checked path
  to uvicorn successfully.
- **`cd frontend && npm run check`** (`typecheck` + `lint`) -- ran after both Task 2's and
  Task 3's changes: exits 0, no output beyond the two sub-command headers (a clean pass produces
  no diagnostics).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `app/templates/react_page.html` needed a change outside this plan's
stated `files_modified` list**
- **Found during:** Task 1
- **Issue:** The dev branch's acceptance criterion requires the render to emit the Vite dev
  client module as a second `<script type="module">` tag. The shared shell
  (`react_page.html`) only rendered one such tag (`module_src`), with no seam for a second one.
- **Fix:** Added `{% if dev_client_src %}<script type="module" src="{{ dev_client_src }}">
  </script>{% endif %}` immediately before the existing module script tag. `dev_client_src` is
  `None` on the production branch, so the conditional never renders in production.
- **Files modified:** `app/templates/react_page.html`
- **Verification:** `tests/test_react_dev_mode.py::test_dev_setting_enabled_renders_dev_client_and_skips_manifest`
  passes; production-branch tests in `tests/test_react_page_render.py` (9 tests) still pass
  unmodified.
- **Committed in:** `6259380`

**2. [Rule 3 - Blocking] The pre-existing comment-provenance guard rejected `D-22-03`/`T-22-xx`
citations in the new docstrings**
- **Found during:** Task 1, first `uv run pytest -q` full-suite run
- **Issue:** `tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree`
  flagged `D-22-03` (matches the `decision-id` pattern) and `T-22-38`/`T-22-39` (matches the
  `task-id` pattern) in docstrings across `app/routes/templating.py` and
  `tests/test_react_dev_mode.py`.
- **Fix:** Rewrote every flagged docstring in plain language, describing the property being
  tested/implemented instead of citing the decision or threat ID.
- **Files modified:** `app/routes/templating.py`, `tests/test_react_dev_mode.py`
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree -x -q`
  passes.
- **Committed in:** `6259380`

**3. [Rule 3 - Blocking] The GUARD-01 completeness gate (`tests/test_inventory_completeness.py`)
had no registry entries for the 5 new `.text` comparisons `tests/test_react_dev_mode.py` adds**
- **Found during:** Task 1, first `uv run pytest -q` full-suite run
- **Issue:** `test_every_text_bearing_file_is_scoped` and `test_every_discovered_assertion_has_a_registry_entry`
  both failed: the new test file was neither named in `FILE_SCOPE_NOTES` nor did its 5
  `.text`-comparing assertions have `ASSERTION_INVENTORY` entries.
- **Fix:** Added a `FILE_SCOPE_NOTES` entry for `tests/test_react_dev_mode.py` and 5
  `ASSERTION_INVENTORY` entries (all `route='/runs'`, `layer=JINJA_SHELL` -- the boot-tag script
  elements `react_page.html` renders around the mount point, not React DOM or the JSON data
  island), classified by hand against the assertions' actual behavior, matching the registry's
  established methodology (D-22-05/D-22-06).
- **Files modified:** `tests/assertion_inventory.py`
- **Verification:** `uv run pytest tests/test_inventory_completeness.py -q` (7/7 pass).
- **Committed in:** `6259380`

---

**Total deviations:** 3 auto-fixed (all Rule 3 - blocking issues; none change scope, all were
necessary to satisfy this plan's own acceptance criteria and pre-existing repo guards).
**Impact on plan:** No scope creep. All three are narrow fixes required by the dev branch's own
acceptance criteria and by guards this repo already enforces on every commit.

## Issues Encountered

- `.env.example` could not be edited: this repo has a recorded harness guard denying writes to
  that path. Per this task's own instruction ("do not work around it -- record the exact line to
  paste in SUMMARY.md and flag it as a manual step"), the line to paste manually is:

  ```
  # ── Frontend dev server (local dev only, never set in a deployed image) ─────
  # Empty = production asset tags via the Vite build manifest. Setting this
  # (e.g. http://localhost:5173) switches render_react_page() to emit the Vite
  # dev client module and the entry's raw source path from this origin instead.
  # See app/config.py and app/routes/templating.py.
  VITE_DEV_SERVER_URL=
  ```

  **Manual step required:** append the block above to `.env.example`.

## User Setup Required

**One manual step, documented above:** append the `VITE_DEV_SERVER_URL=` block to
`.env.example` (blocked by a harness write guard, same precedent as prior quick tasks in this
repo). No other external service configuration required -- the dev-server setting is local-only
and the image build never sets it.

## Next Phase Readiness

- SHELL-04 is complete: one command (`npm run dev`, paired with `VITE_DEV_SERVER_URL` exported
  before starting uvicorn) gives real Vite Fast Refresh against uvicorn, one command
  (`npm run check`) typechecks and lints, and both were run by this executor. The named
  redirect-origin risk from the architecture research was measured against two real routes, not
  assumed, and both landed on the dev origin.
- The dev branch is proven fail-closed on three independent axes: it defaults off (tested), the
  image build cannot set it (tested against the tracked Dockerfile text), and enabling it does
  not weaken the production branch's manifest-missing fail-closed behavior (tested).
- Phase 23 and 24 inherit the same `render_react_page()`/`react_page.html` dev/production split
  with no further changes needed -- the dev branch is entry-agnostic (it interpolates whatever
  `entry` the caller passes), so a second or third React page gets Fast Refresh for free.
- The one open item is the `.env.example` manual paste above; it does not block any other work in
  this phase.

## Self-Check: PASSED

- Commits `6259380`, `caff873`, `84a6378` all found in `git log --oneline --all`.
- All files claimed for each task confirmed present via the commit diffs shown above
  (`git diff --stat 4777a13 84a6378`).
- `uv run pytest -q` -- 1453 passed, 107 skipped (matches baseline 1449/107 + 4 new tests).
- `uv run ruff check .` and `uv run mypy` both clean (191 source files).
- `cd frontend && npm run check` exits 0.
- Redirect-origin check performed live against a real (throwaway) Postgres + uvicorn + Vite dev
  server, not simulated; raw header values and final landing origins captured verbatim above for
  two independent routes.
- No missing items.

---
*Phase: 22-frontend-foundation-runs-list*
*Completed: 2026-08-17*
