---
phase: 22-frontend-foundation-runs-list
plan: 10
subsystem: ui
tags: [react, vitest, usepoller, polling, guard-06, hermetic-guard]

# Dependency graph
requires:
  - phase: 22-frontend-foundation-runs-list
    provides: "plan 22-06's full-parity RunsPage.tsx (StatusBadge/QueueBadge/FailureSummary
      components) and plan 22-07's RunStatusPoll response_model on GET
      /runs/{run_id}/status, which this plan polls against unchanged"
provides:
  - "frontend/src/hooks/usePoller.ts -- a typed, single-URL, one-instance-per-caller
    polling hook reproducing the replaced vanilla-JS poller's five observable
    properties exactly, with teardown proven observable via a request-counter stub
    (not assumed via inspection)"
  - "RunsPage.tsx wired to usePoller: one instance per in-flight-or-open-job row,
    merging each tick's seven volatile fields over row-local state so only the
    badges re-render in place"
  - "tests/test_no_fetch_outside_poller.py -- GUARD-06's second, independent
    enforcement path in the hermetic Python test job"
affects: []

# Actuals (#2632)
actuals:
  tokens: 9121
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "usePoller<T>(url, {intervalMs, maxAttempts, stopWhen}, onUpdate) -- single-URL,
      one instance per caller (D-22-14); a row mounts its own instance via a
      conditionally RENDERED child component (RowPoller), never a conditionally
      CALLED hook, so the Rules of Hooks hold while still issuing zero requests for
      settled rows"
    - "The interval tick's synchronous entry checks only the attempt cap, not a
      `cancelled` flag -- clearInterval() in the effect cleanup is what stops future
      ticks; `cancelled` is checked only inside the async .then() callback, to guard
      the one race clearInterval cannot (a fetch already in flight at the moment of
      unmount). This split is what makes 'delete the interval-clearing call' a real,
      observable regression rather than a self-healing no-op -- see Decisions."
    - "React state updates driven by a fake-timer-advanced promise chain (usePoller's
      onUpdate -> a row's setState) must be wrapped in `act()` around
      `vi.advanceTimersByTimeAsync()`, or the state update never flushes to the DOM
      in the test even though the mock/effect machinery all fires correctly -- see
      Issues Encountered."

key-files:
  created:
    - frontend/src/hooks/usePoller.ts
    - frontend/src/hooks/usePoller.test.ts
    - tests/test_no_fetch_outside_poller.py
  modified:
    - frontend/src/pages/RunsPage.tsx
    - frontend/src/pages/RunsPage.test.tsx

key-decisions:
  - "The `cancelled` guard was moved OUT of the interval tick's synchronous entry
    condition (present in the plan's own research code example) and kept ONLY in the
    async .then() callback. With the research example's version (`if (cancelled ||
    attempts >= maxAttempts)`), removing the cleanup's `clearInterval(timer)` call
    while keeping `cancelled = true` does NOT red the teardown test: the next tick
    still fires, sees `cancelled === true` at its own synchronous entry, and
    self-clears the interval as a side effect -- meaning the acceptance criterion's
    required RED proof ('delete the interval-clearing call, confirm RED') would have
    passed vacuously. Splitting the two concerns (interval-level stop via
    clearInterval only; in-flight-request-level stop via `cancelled` only in the
    promise chain) makes the mutation genuinely observable, matching the acceptance
    criterion's intent rather than merely its literal instruction."
  - "RunRow holds only the seven volatile fields in local state (`useState<PollUpdate>`)
    and reads static fields straight off the `run` prop each render, rather than
    copying the whole row into state. This is what makes the merge
    (`{...run, ...volatile}`) the single place badge-affecting data can diverge from
    the initial server render, and keeps the diff between ticks small."
  - "A row's poller is a conditionally RENDERED child (`<RowPoller>` or `null`), not a
    conditionally called hook inside RunRow itself -- Rules of Hooks require every
    hook call site to be unconditional within one component's render; usePoller
    itself is still called unconditionally, just from a component that may or may not
    be present in the tree that render."

patterns-established:
  - "Pattern: fake-timer-driven async ticks that trigger a React state update must be
    wrapped in `act(async () => { await vi.advanceTimersByTimeAsync(ms); })`, not a
    bare `await vi.advanceTimersByTimeAsync(ms)` -- the latter leaves the DOM showing
    stale content even though the underlying state setter was called, because the
    update is applied outside React's batching/commit boundary that a bare await
    never triggers a flush for."

requirements-completed: [LIST-02, GUARD-06]

coverage:
  - id: D1
    description: "usePoller reproduces the replaced vanilla-JS poller's five observable properties (request path shape, 2s interval, 60-attempt cap, settle condition, per-tick error swallowing) with a teardown proven observable via a request-counter stub and two demonstrated-red mutations, each reverted byte-identical"
    requirement: "LIST-02"
    verification:
      - kind: unit
        ref: "frontend/src/hooks/usePoller.test.ts -- 7 cases, all passing"
        status: pass
    human_judgment: false
  - id: D2
    description: "RunsPage mounts one usePoller instance per in-flight-or-open-job row, merging each tick's seven volatile fields in place; a settled row with no open job issues zero requests; an unchanged-status tick is byte-identical with no duplicate node"
    requirement: "LIST-02"
    verification:
      - kind: unit
        ref: "frontend/src/pages/RunsPage.test.tsx -- 'RunsPage live polling' describe block, 7 cases, all passing"
        status: pass
      - kind: integration
        ref: "cd frontend && npm run check && npm run build (exit 0)"
        status: pass
    human_judgment: false
  - id: D3
    description: "GUARD-06's second, independent enforcement path: a hermetic Python text-scan guard confining fetch/axios/XMLHttpRequest to usePoller.ts, demonstrated red on a scratch module both via the guard and via ESLint independently, and demonstrated still-red with the frontend CI job disabled"
    requirement: "GUARD-06"
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_no_fetch_outside_poller.py -x -q (5 passed)"
        status: pass
      - kind: other
        ref: "manual falsification run -- see 'GUARD-06 Independence Proof' section below for the full transcript"
        status: pass
    human_judgment: false

duration: ~25min
completed: 2026-08-17
status: complete
---

# Phase 22 Plan 10: usePoller + Live Badge Updates + GUARD-06's Second Enforcement Path Summary

**A typed `usePoller` hook reproducing the replaced vanilla-JS poller's five observable properties exactly (teardown proven observable, not assumed), wired into `RunsPage` as one instance per in-flight row for in-place badge updates, plus GUARD-06's second, independent hermetic enforcement path.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 3 of 3 complete
- **Files modified:** 5 (3 created, 2 modified)

## Accomplishments

- `usePoller<T>(url, {intervalMs, maxAttempts, stopWhen}, onUpdate)`: the single
  sanctioned browser-request call site in the frontend tree. Reproduces all five
  observable properties of the pre-conversion vanilla-JS poller (recovered via `git
  show d23bf6d~1:app/templates/runs_list.html`): the same `/runs/{id}/status` request
  path shape, the same 2000ms interval, the same 60-attempt cap, the same settle
  condition (caller-supplied `stopWhen`), and the same per-tick error swallowing
  (documented in-source as a network-blip guard, not error hiding).
- Teardown proven observable, not assumed: a request-counter stub asserts the counter
  stops increasing after unmount with NO try/finally or other suppressing construct
  around the assertion. Two demonstrated-red mutations, each with a byte-identical
  revert: removing the cleanup's `clearInterval` call, and disabling the attempt-cap
  check.
- `RunsPage.tsx`: each row that is in-flight or carries an open job mounts its own
  `RowPoller` child (a conditionally rendered component, not a conditionally called
  hook), merging each tick's seven volatile fields over row-local state. Badges
  update in place with no full table re-render (row element identity preserved); an
  unchanged-status tick is byte-identical with no duplicate badge node; a settled row
  stops polling while a still-in-flight sibling keeps going.
- `tests/test_no_fetch_outside_poller.py`: GUARD-06's second, independent
  enforcement path. A hermetic text-scan walk over `frontend/src` confining
  fetch/axios/XMLHttpRequest to `usePoller.ts`, with companion tests closing this
  repo's own recorded blind spot (a walk that visits nothing, or a stale allowlist
  entry) plus a positive/negative control pair on synthetic files.
- Independence demonstrated for real: a scratch module (`ScratchFetch.tsx`) calling
  `fetch()` outside the hook reds BOTH enforcement paths independently (the hermetic
  guard naming the file, ESLint's `no-restricted-globals` rule separately), and the
  hermetic guard still reds with the frontend CI job disabled in the working-tree
  copy of `ci.yml`. Both mutations reverted byte-identical.
- Full verification green: `cd frontend && npm run check && npm run test && npm run
  build` (57/57 tests, typecheck/lint/build all exit 0); `uv run pytest -q` 1476
  passed / 107 skipped (1471/107 baseline plus 5 new guard tests); `uv run ruff check
  .` and `uv run mypy` both clean (195 source files); `git diff --name-only` against
  the wave-5 fork base touches exactly the 5 files this plan's `files_modified` names.

## Task Commits

1. **Task 1: usePoller -- five-property parity, teardown proven observable** --
   `87a549c` (test)
2. **Task 2: Wire the poller into the runs list, pin the in-place badge update** --
   `8900b0e` (feat)
3. **Task 3: GUARD-06's second, independent enforcement path** -- `6478e32` (test)

## Files Created/Modified

- `frontend/src/hooks/usePoller.ts` -- the typed polling hook, single call site
- `frontend/src/hooks/usePoller.test.ts` -- 7-case teardown-observable test suite
- `frontend/src/pages/RunsPage.tsx` -- wired to `usePoller`, one instance per
  in-flight-or-open-job row via a conditionally rendered `RowPoller` child
- `frontend/src/pages/RunsPage.test.tsx` -- extended with a "RunsPage live polling"
  describe block, 7 new cases
- `tests/test_no_fetch_outside_poller.py` -- GUARD-06's hermetic second half, 5 cases

## Decisions Made

See `key-decisions` in the frontmatter for the full rationale on:
1. Moving the `cancelled` guard out of the interval tick's synchronous entry and into
   only the async `.then()` callback, so the "remove the interval-clearing call"
   mutation is genuinely observable rather than self-healing on the next tick.
2. Holding only the seven volatile fields in `RunRow`'s local state, reading static
   fields straight off the `run` prop.
3. A row's poller as a conditionally rendered child component, not a conditionally
   called hook, to satisfy the Rules of Hooks while still issuing zero requests for
   settled rows.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The research code example's `cancelled` placement would have
made one required RED proof pass vacuously**
- **Found during:** Task 1, while writing the teardown-observable test.
- **Issue:** The plan's own research code example (`22-RESEARCH.md`) checks
  `if (cancelled || attempts >= opts.maxAttempts)` at the interval tick's
  synchronous entry, in addition to setting `cancelled = true` in the cleanup. With
  that shape, removing `clearInterval(timer)` from the cleanup (keeping only
  `cancelled = true`) does NOT stop the interval from firing again -- but the next
  tick's own entry check sees `cancelled === true`, self-clears the interval, and
  returns without ever calling `fetch`. The request counter this plan's own
  acceptance criterion requires ("counter does not increase after unmount") would
  therefore stay flat regardless of whether `clearInterval` was ever called in the
  cleanup -- the mutation would not red, failing the acceptance criterion's explicit
  requirement that this exact mutation reds the test.
- **Fix:** Moved the `cancelled` check out of the interval tick's synchronous entry
  (which now checks only the attempt cap) and kept it solely inside the async
  `.then()` callback, where it guards the one race `clearInterval` genuinely cannot
  cover (a fetch already in flight at the moment of unmount). With this split,
  removing `clearInterval` from the cleanup lets the interval keep firing forever
  (since nothing else stops it), which correctly reds the request-counter assertion.
- **Files modified:** `frontend/src/hooks/usePoller.ts`
- **Verification:** Both required RED transcripts (removed `clearInterval`, disabled
  attempt cap) captured below, each with a byte-identical revert confirmed via
  `diff`.
- **Committed in:** `87a549c` (Task 1 commit)

**2. [Rule 1 - Bug] Fake-timer-advanced React state updates were not flushing to
the DOM**
- **Found during:** Task 2, while writing the "new status" in-place update test.
- **Issue:** `await vi.advanceTimersByTimeAsync(2000)` alone advanced the fake timer
  and resolved the mock fetch promise chain (confirmed: the mock was called), but
  the resulting `setState` call inside `RowPoller`'s `onUpdate` never committed to
  the DOM -- three of seven new tests failed with the badge still showing its
  pre-tick value. Isolated via a standalone reproduction: a bare
  `vi.advanceTimersByTimeAsync` call outside `act()` lets React's state update apply
  internally but does not force the flush a synchronous DOM read afterward depends
  on.
- **Fix:** Wrapped every timer advance in this describe block's `advance()` helper:
  `await act(async () => { await vi.advanceTimersByTimeAsync(ms); })`.
- **Files modified:** `frontend/src/pages/RunsPage.test.tsx`
- **Verification:** All 7 new cases pass; confirmed via a throwaway debug test
  (never committed) that isolated the fix before applying it here.
- **Committed in:** `8900b0e` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 -- bugs found and fixed while
satisfying this plan's own acceptance criteria and behavior specification). No scope
creep; both fixes are internal to the hook/test files this plan already owns.

## GUARD-06 Independence Proof (Task 3)

**Scratch module added** (`frontend/src/ScratchFetch.tsx`, never committed):
```typescript
export function ScratchFetch() {
  return fetch("/x");
}
```

**Hermetic guard RED, naming the file:**
```
$ uv run pytest tests/test_no_fetch_outside_poller.py -x -q
F
=================================== FAILURES ===================================
______________________ test_fetch_confined_to_poller_hook ______________________
E       AssertionError: fetch/axios/XMLHttpRequest found outside usePoller.ts: ['ScratchFetch.tsx']
1 failed, 1 warning in 0.16s
```

**ESLint RED, independently, on the same file, with its rule id:**
```
$ npm run lint
frontend/src/ScratchFetch.tsx
  2:10  error  Unexpected use of 'fetch'. fetch is banned outside src/hooks/usePoller.ts,
  the one reviewed network call site. See eslint.config.js for the sanctioned override
  no-restricted-globals

✖ 1 problem (1 error, 0 warnings)
```

**Independence: the hermetic guard still reds with the frontend CI job disabled**
(mutated `.github/workflows/ci.yml`'s `frontend:` job key to
`frontend-DISABLED-FOR-INDEPENDENCE-DEMO:` with `if: false`, working-tree only):
```
$ uv run pytest tests/test_no_fetch_outside_poller.py::test_fetch_confined_to_poller_hook -x -q
F
E       AssertionError: fetch/axios/XMLHttpRequest found outside usePoller.ts: ['ScratchFetch.tsx']
1 failed, 1 warning in 0.14s
```
This test never reads `ci.yml`, so the CI job's state has no bearing on it -- the two
enforcement paths do not depend on each other's run order or configuration.

**Both mutations reverted, confirmed byte-identical:**
```
$ git diff --stat .github/workflows/ci.yml
(no output -- clean)

$ git status --porcelain frontend/src
(no output -- clean)
```

## usePoller Teardown RED Proofs (Task 1)

**Mutation 1 -- removed `clearInterval(timer)` from the cleanup:**
```
$ npm run test -- usePoller
 × on unmount, the request counter stops increasing when fake timers are advanced past several further intervals
   AssertionError: expected 7 to be 2
 × mounts one poller per instance -- unmounting one leaves the other's counter still increasing
   AssertionError: expected 3 to be 1
Tests  2 failed | 5 passed (7)
```
Restored, confirmed: `git diff` against the saved-good copy -- byte-identical.

**Mutation 2 -- widened the attempt-cap check so it never fires
(`attempts >= opts.maxAttempts + 999999`):**
```
$ npm run test -- usePoller
 × given a settle predicate that never returns true, issues one request per interval
   tick and stops after exactly the configured attempt cap
   AssertionError: expected "vi.fn()" to be called 3 times, but got 8 times
Tests  1 failed | 6 passed (7)
```
Restored, confirmed: `git diff` against the saved-good copy -- byte-identical. Only
this one case reddened, per the acceptance criterion.

## Issues Encountered

Both documented above under Deviations (Rule 1 fixes): the `cancelled`-placement
issue in Task 1, and the `act()`-wrapping issue in Task 2. No unresolved issues.

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

- All three tasks complete, committed, and verified: `cd frontend && npm run check
  && npm run test && npm run build` all exit 0 (57/57 tests); `uv run pytest -q`
  1476 passed / 107 skipped; `uv run ruff check .` and `uv run mypy` both clean.
- `git diff --name-only` against the wave-5 fork base is exactly this plan's five
  `files_modified` entries -- no untouchable-directory path touched.
- `usePoller` is a real, reusable hook: Phase 23's `/runs/{id}` detail page reuses it
  unchanged with a single instance, per D-22-14.
- LIST-02 and GUARD-06 are both fully closed by this plan.

## Self-Check: PASSED

- Commits `87a549c`, `8900b0e`, `6478e32` all found in `git log --oneline --all`.
- All five files claimed present via `git show --stat` on each commit.
- `cd frontend && npm run check && npm run test && npm run build` -- all exit 0,
  57/57 tests pass.
- `uv run pytest -q` -- 1476 passed, 107 skipped (1471/107 baseline + 5 new guard
  tests).
- `uv run pytest tests/test_no_fetch_outside_poller.py tests/test_design_tokens.py -x -q`
  -- 17 passed.
- `uv run ruff check .` and `uv run mypy` -- both clean (195 source files).
- `git diff --name-only` against the wave-5 fork base confirmed limited to the five
  `files_modified` paths.
- No missing items.

---
*Phase: 22-frontend-foundation-runs-list*
*Completed: 2026-08-17*
