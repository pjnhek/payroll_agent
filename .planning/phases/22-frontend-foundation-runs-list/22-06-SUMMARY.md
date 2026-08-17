---
phase: 22-frontend-foundation-runs-list
plan: 06
subsystem: ui
tags: [react, vitest, testing-library, badges, runs-list]

# Dependency graph
requires:
  - phase: 22-frontend-foundation-runs-list
    provides: "the tracer's already-working React /runs page (RunsPage.tsx,
      RunListRow/FailureInfo DTO shape, pageData.ts island reader) from plan
      22-04, and the pinned Vite/Vitest/Testing-Library toolchain from 22-03"
provides:
  - "frontend/src/components/StatusBadge.tsx, QueueBadge.tsx,
    FailureSummary.tsx -- the status cluster, queue badge and failure
    presentation lifted out of RunsPage's inline table into three focused,
    independently testable components"
  - "RunsPage.tsx rebuilt on top of those three components, with full
    column/ordering/empty-state parity against the pre-conversion
    runs_list.html verified by a positive Vitest suite"
  - "frontend/src/pages/RunsPage.test.tsx -- the repo's first component test
    suite (23 cases), proven able to fail via two demonstrated-red
    transcripts"
affects: [22-10]

# Actuals (#2632)
actuals:
  tokens: 5400
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Badge/failure components consume server-computed vocabulary
      (badge_class/badge_label/queue_badge_class/failure fields) as plain
      string props -- no status-to-class or status-to-label mapping exists
      in TypeScript anywhere in this repo"
    - "FailureSummary is a single component rendering BOTH the secondary
      'Retries exhausted' badge and the joined stage/reason/attempts summary
      line as a Fragment, each independently hidden/absent when its own
      inputs are absent -- see key-decisions for why this moves the
      secondary badge out of the Status column into the Summary column"
    - "afterEach(cleanup) explicitly imported and registered per test file
      (not global) because vitest.config.ts sets test.globals=false"

key-files:
  created:
    - frontend/src/components/StatusBadge.tsx
    - frontend/src/components/QueueBadge.tsx
    - frontend/src/components/FailureSummary.tsx
    - frontend/src/pages/RunsPage.test.tsx
  modified:
    - frontend/src/pages/RunsPage.tsx

key-decisions:
  - "FailureSummary renders both the secondary badge and the joined summary
    line as one component call, placed entirely in the Summary column --
    NOT split across the Status column (badge) and Summary column (text)
    the way the pre-conversion Jinja markup was. This is a deliberate
    reading of Task 1's explicit instruction ('FailureSummary ... renders
    both the secondary badge and the joined summary line'), which requires
    a single render call producing both pieces. It is behaviorally
    equivalent to the original: app/routes/runs.py::_safe_failure_presentation
    only ever sets `secondary_label` non-null alongside non-null
    stage/reason (never independently), so the secondary badge was already
    guaranteed to appear only when the Summary column's failure branch was
    reached. No must_haves.truth or GUARD-01 assertion pins the secondary
    badge to the Status column specifically -- only the Summary column's
    four-way precedence is pinned, which this preserves exactly."
  - "Component tests are split across three commits by task, all living in
    one frontend/src/pages/RunsPage.test.tsx file (per the plan's explicit
    files_modified list, which names one test file, not one per
    component). Task 1's commit adds the file with only the
    StatusBadge/QueueBadge/FailureSummary describe blocks; Task 2's commit
    extends it with the RunsPage describe block; Task 3's commit adds the
    scroll-region structural describe block. Each commit's `npm run test --
    RunsPage` was verified green before committing."
  - "afterEach(cleanup) is registered explicitly inside RunsPage.test.tsx
    (not added to frontend/src/test/setup.ts) to stay within this plan's
    files_modified list -- setup.ts is not one of the five files this plan
    is scoped to touch. Without it, jsdom accumulated every prior test's
    rendered DOM across the file (vitest.config.ts sets test.globals=false,
    so @testing-library/react's automatic afterEach registration never
    fires) and getByText calls collided across tests; this was the first
    real bug this suite caught in itself before any deliberate red proof."

patterns-established:
  - "Pattern: presentational badge components consume plain string/boolean
    props (no re-derivation of server vocabulary)"
  - "Pattern: a jsdom-level 'structural pin' (element nesting/attributes/
    presence-absence) is written and committed separately from the
    layout-derived measurement it cannot make (scroll width, overflow at a
    pixel boundary) -- the latter stays an explicit manual/backstop
    verification, never faked in jsdom"

requirements-completed: [LIST-01, LIST-04]

coverage:
  - id: D1
    description: "StatusBadge, QueueBadge and FailureSummary reproduce the pre-conversion status cluster, queue badge and failure presentation markup exactly, consuming server-computed vocabulary as plain props with no status-to-class/label mapping re-derived in TypeScript"
    requirement: "LIST-01"
    verification:
      - kind: unit
        ref: "frontend/src/pages/RunsPage.test.tsx -- StatusBadge/QueueBadge/FailureSummary describe blocks, 9 cases"
        status: pass
    human_judgment: false
  - id: D2
    description: "RunsPage renders full column/ordering/empty-state parity against the pre-conversion runs_list.html: five headers in order, per-row data attributes, identical-timestamp rows staying distinct, no client-side sort, the four-way summary precedence as an explicit ordered branch, and the empty state with no table"
    requirement: "LIST-01"
    verification:
      - kind: unit
        ref: "frontend/src/pages/RunsPage.test.tsx -- RunsPage describe block, 12 cases"
        status: pass
      - kind: integration
        ref: "uv run pytest tests/test_react_page_render.py -x -q (9 passed) -- server contract unchanged"
        status: pass
    human_judgment: false
  - id: D3
    description: "The scroll region is a jsdom-provable structural fact: the table's direct parent, region role, zero tab index, accessible label, and absent entirely with zero rows"
    requirement: "LIST-04"
    verification:
      - kind: unit
        ref: "frontend/src/pages/RunsPage.test.tsx -- 'RunsPage scroll region structure' describe block, 2 cases"
        status: pass
    human_judgment: false
  - id: D4
    description: "Real 375/374/376px narrow-viewport overflow measurement (LIST-04's manual verification row)"
    verification: []
    human_judgment: true
    rationale: "No browser is reachable from this worktree/sandbox and no headless-browser tooling (Playwright/Puppeteer) is installed in this project. Per the plan's own fallback instruction, this measurement was not performed and is not claimed -- it remains an open manual verification row, not silently marked done."

duration: ~55min
completed: 2026-08-17
status: complete
---

# Phase 22 Plan 06: RunsPage Full Parity -- Badges, Failure Summary, Component Tests Summary

**Three focused presentational components (StatusBadge/QueueBadge/FailureSummary) lifted out of the tracer's inline table, RunsPage rebuilt on top of them with verified full parity against the pre-conversion Jinja markup, and the repo's first component test suite (23 Vitest cases) proven able to fail via two demonstrated-red transcripts.**

## Performance

- **Duration:** ~55min
- **Tasks:** 3 of 3 complete
- **Files modified:** 5 (3 created, 2 modified)

## Accomplishments

- `StatusBadge.tsx`: one span carrying the base + status-suffixed badge class
  and the label, consuming `badge_class`/`badge_label` as plain server-computed
  strings.
- `QueueBadge.tsx`: the live-region queue badge, hidden (not unmounted) with
  no open job, its text forced to empty string rather than the literal
  `"null"` for a null label.
- `FailureSummary.tsx`: renders both the secondary "Retries exhausted" badge
  and the middle-dot-joined stage/reason/attempts summary line as a single
  Fragment, each independently hidden/absent based on its own inputs --
  renders nothing at all (no empty visible element) when none of the three
  are present.
- `RunsPage.tsx` rewired to use all three components in place of the
  tracer's inline markup -- zero behavior change to the tracer's
  already-correct output, purely an extraction. Full parity verified: five
  headers in the existing order (Created/Business/Status/Summary/Action),
  per-row `data-run-id`/`data-in-flight`/`data-has-open-job` attributes,
  two rows with an identical `created_at` staying distinct, payload order
  rendered with no client-side sort, the four-way summary precedence
  (failure summary -> gate reason -> employee count with singular/plural
  agreement -> em-dash) implemented as an explicit ordered branch, and the
  empty state rendering with no table element.
- `RunsPage.test.tsx`: the repo's first component test suite -- 23 Vitest
  cases across four `describe` blocks (StatusBadge, QueueBadge,
  FailureSummary, RunsPage, RunsPage scroll region structure). Every case
  asserts on rendered class names, hidden state, attribute values or text
  content -- none merely assert "the component mounted."
- A jsdom-level structural pin for the scroll region (Task 3): the region
  is asserted to be the table's DIRECT parent (`:scope > table`, not merely
  a shared ancestor), carrying `role="region"`, `tabindex="0"` and the
  `"Payroll runs"` accessible label, and to not exist at all with zero
  rows. No assertion reads a layout-derived measurement (scroll width,
  overflow, viewport boundary) from jsdom -- jsdom cannot measure layout,
  and this suite does not pretend it can.
- Suite proven able to fail: deleting the empty-state block and reordering
  two of the five headers both produced the expected failing cases, with a
  byte-identical `git diff --stat RunsPage.tsx` after each revert (full
  transcripts below).
- Full verification green: `cd frontend && npm run check && npm run test
  && npm run build` (23/23 tests, typecheck/lint/build all exit 0);
  `uv run pytest -q` 1449 passed / 107 skipped (unchanged from the 22-04
  baseline); `uv run pytest tests/test_design_tokens.py -x -q` 12 passed
  (the widened `.ts`/`.tsx` scan now covers these new files).

## Task Commits

1. **Task 1: Badge and failure-summary components matching the existing
   markup exactly** -- `b5b6f9f` (test)
2. **Task 2: RunsPage full column, ordering, empty-state and scroll-region
   parity** -- `67c27a9` (feat)
3. **Task 3: Narrow-viewport verification and the component suite's own
   red proof** -- `5834d60` (test)

## Files Created/Modified

- `frontend/src/components/StatusBadge.tsx` -- status badge span
- `frontend/src/components/QueueBadge.tsx` -- queue live-region badge
- `frontend/src/components/FailureSummary.tsx` -- secondary badge + joined
  summary line
- `frontend/src/pages/RunsPage.tsx` -- rewired onto the three new
  components; no other behavior change
- `frontend/src/pages/RunsPage.test.tsx` -- 23-case Vitest suite (new file)

## Decisions Made

See `key-decisions` in the frontmatter for the full rationale on:
1. Consolidating the secondary badge and the summary line into one
   `FailureSummary` call placed in the Summary column (a deliberate, narrow
   DOM-position departure from the two-column pre-conversion split,
   required by Task 1's explicit "renders both ... in one component"
   instruction, and behaviorally equivalent since the server never sets
   `secondary_label` independently of `stage`/`reason`).
2. Splitting the one test file's 23 cases across three per-task commits.
3. Registering `afterEach(cleanup)` explicitly in the test file rather than
   in `frontend/src/test/setup.ts`, to stay within this plan's
   `files_modified` list.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Component comments containing literal
`class="..."`-shaped Jinja excerpts polluted the class-token grep check**
- **Found during:** Task 1, while running the acceptance criterion's own
  comparison command.
- **Issue:** `grep -rEo 'class(Name)?="[^"]*"' frontend/src/components/*.tsx`
  is the acceptance criterion's literal verification command. My initial
  component file comments quoted the pre-conversion Jinja markup verbatim
  (e.g. `` `<span class="badge badge-neutral js-failure-secondary" ...` ``)
  to document what was being reproduced. The regex cannot distinguish a
  comment from live JSX, so it captured `js-failure-secondary` and
  `js-failure-summary` as if they were applied class tokens -- and neither
  exists in `app/static/style.css` (they were pure JS query hooks, per
  quick task 260726-ugm's own finding), which would have made the
  acceptance criterion's "empty diff" claim false.
- **Fix:** Reworded all three components' header comments to describe the
  pre-conversion markup in prose rather than quoting it as a literal HTML
  attribute string, so the grep only matches genuinely applied class names.
- **Files modified:** `frontend/src/components/StatusBadge.tsx`,
  `QueueBadge.tsx`, `FailureSummary.tsx`.
- **Verification:** `grep -rEo 'class(Name)?="[^"]*"'
  frontend/src/components/*.tsx` now yields exactly one line --
  `frontend/src/components/FailureSummary.tsx:className="badge
  badge-neutral"` -- both tokens (`badge`, `badge-neutral`) present in
  `app/static/style.css`.
- **Committed in:** `b5b6f9f`

**2. [Rule 1 - Bug] `afterEach(cleanup)` missing caused cross-test DOM
leakage**
- **Found during:** Task 1, first test run.
- **Issue:** `vitest.config.ts` sets `test.globals: false` deliberately, so
  `@testing-library/react`'s automatic `afterEach(cleanup)` registration
  never fires. Without an explicit cleanup, every prior test's rendered DOM
  persisted in `document.body`, and a `getByText`/`querySelector` call in a
  later test intermittently matched a leftover node from an earlier one
  (11 of 23 cases failed on the first full run with "multiple elements
  found" errors).
- **Fix:** Imported `cleanup` from `@testing-library/react` and `afterEach`
  from `vitest`, and registered `afterEach(cleanup)` once at the top of
  `RunsPage.test.tsx`.
- **Files modified:** `frontend/src/pages/RunsPage.test.tsx`.
- **Verification:** `cd frontend && npm run test -- RunsPage` -- 23/23
  pass, no cross-test collisions.
- **Committed in:** `b5b6f9f`

---

**Total deviations:** 2 auto-fixed (both Rule 1 -- bugs found and fixed
while satisfying this plan's own acceptance criteria). No scope creep;
both fixes are internal to the test/component files this plan already
owns.

## Class-token verification (Task 1 acceptance criterion)

```
$ grep -rEo 'class(Name)?="[^"]*"' frontend/src/components/*.tsx
frontend/src/components/FailureSummary.tsx:className="badge badge-neutral"
```

Both tokens (`badge`, `badge-neutral`) exist in `app/static/style.css`.

The other two components apply class names via template-literal
interpolation (`` `badge badge-${badgeClass}` ``, `` `badge
badge-${badgeClass} queue-badge` ``), which a static grep on a literal
quoted string cannot see -- this is inherent to any dynamically-composed
`className`, not a gap specific to this plan. Traced by source instead:
every `badge_class`/`queue_badge_class` value the server can produce is
enumerated in `app/routes/templating.py::_BADGE_CLASS` (`neutral`,
`pending`, `good`, `bad`, `escalate`) and `app/routes/runs.py::_QUEUE_BADGE_CLASSES`
(`running`, `neutral`) -- every one of `badge-neutral`, `badge-pending`,
`badge-good`, `badge-bad`, `badge-escalate`, `badge-running` and
`queue-badge`/`status-cluster`/`text-muted`/`table-scroll`/`empty-state`/
`empty-state__title`/`cell-time` is present in `app/static/style.css`
(confirmed by direct read of both files). No new class name and no
stylesheet was introduced (`find frontend/src -name '*.css' | wc -l`
reports `0`).

No file under `frontend/src/components/` declares an object or record
literal mapping a run status to a class or a label -- confirmed by reading
all three files; each consumes `badgeClass`/`label`/`badge`/`badgeClass`
props verbatim with no lookup table.

## Demonstrated-red proof (Task 3)

**Mutation 1 -- deleted the empty-state block from `RunsPage.tsx`:**

```
$ npm run test -- RunsPage
 FAIL  src/pages/RunsPage.test.tsx > RunsPage > given an empty rows array renders the empty-state title and helper sentence, and no table element
 FAIL  src/pages/RunsPage.test.tsx > RunsPage scroll region structure > with zero rows renders no such region element at all
 Test Files  1 failed (1)
      Tests  2 failed | 21 passed (23)
```

Restored, then confirmed:

```
$ git diff --stat frontend/src/pages/RunsPage.tsx
(no output -- byte-identical)
```

**Mutation 2 -- reordered the Created/Business headers:**

```
$ npm run test -- RunsPage
 FAIL  src/pages/RunsPage.test.tsx > RunsPage > renders the five column headers in the order Created, Business, Status, Summary, Action
AssertionError: expected [ 'Business', 'Created', …(3) ] to deeply equal [ 'Created', 'Business', …(3) ]
 Test Files  1 failed (1)
      Tests  1 failed | 22 passed (23)
```

Restored, then confirmed:

```
$ git diff --stat frontend/src/pages/RunsPage.tsx
(no output -- byte-identical)
```

Both mutations were made and reverted in the working tree only, never
committed -- the three commits in this plan contain only the real
implementation and test code.

## Narrow-viewport verification (LIST-04, Task 3)

**Not performed.** No browser is reachable from this worktree/sandboxed
execution environment, and no headless-browser tooling (Playwright,
Puppeteer) is installed in this project (`frontend/package.json` has
neither). Per the plan's explicit instruction ("If no browser is
available, say so explicitly in SUMMARY.md and leave LIST-04's manual row
open rather than claiming it"), the real 375/374/376px overflow
measurement is **not claimed** here and remains an open manual
verification row for LIST-04, matching the repo's own documented
precedent of a previously-deferred visual check
(`.planning/STATE.md`'s quick task 260726-tog entry) that was later
performed for real in 260726-ugm. What jsdom CAN prove -- the scroll
region's structural correctness (direct table parentage, role, tab index,
accessible label, absence with zero rows) -- is pinned by the two cases in
Task 3's commit (`5834d60`) instead of being faked as a layout assertion.

## Issues Encountered

None beyond the two auto-fixed deviations documented above.

## User Setup Required

None -- no external service configuration required. A real browser (or
Playwright/Puppeteer installation) is needed to close LIST-04's remaining
manual verification row; no action is required from the user for this
plan's own scope.

## Next Phase Readiness

- All three tasks complete, committed, and verified: `cd frontend && npm
  run check && npm run test && npm run build` all exit 0 (23/23 tests);
  `uv run pytest -q` 1449 passed / 107 skipped (unchanged); `uv run pytest
  tests/test_react_page_render.py -x -q` 9 passed (server contract
  unchanged); `uv run pytest tests/test_design_tokens.py -x -q` 12 passed.
- `StatusBadge`/`QueueBadge`/`FailureSummary` are real, tested, reusable
  components any future page needing the same badge vocabulary (e.g. plan
  22-10's live poller re-render, or a future run-detail page) can import
  directly rather than re-deriving.
- LIST-04's narrow-viewport pixel measurement remains an open manual
  verification row -- flagged explicitly above, not silently marked done.
  A future execution with browser access (or an added Playwright
  dependency) should close it.
- No changes were made to `app/schemas/`, `app/routes/`, or any Python
  file -- this plan's scope was strictly the three new frontend
  components plus `RunsPage.tsx`/`RunsPage.test.tsx`, as scoped by
  `files_modified`.

## Self-Check: PASSED

- Commits `b5b6f9f`, `67c27a9`, `5834d60` all found in `git log --oneline
  --all`.
- All five files claimed present via `git show --stat` on each commit.
- `cd frontend && npm run check && npm run test && npm run build` -- all
  exit 0, 23/23 tests pass.
- `uv run pytest -q` -- 1449 passed, 107 skipped (matches the 22-04
  baseline exactly).
- `uv run pytest tests/test_react_page_render.py -x -q` -- 9 passed.
- `uv run pytest tests/test_design_tokens.py -x -q` -- 12 passed.
- `find frontend/src -name '*.css' | wc -l` -- reports `0`.
- No missing items.

---
*Phase: 22-frontend-foundation-runs-list*
*Completed: 2026-08-17*
