---
phase: 22-frontend-foundation-runs-list
plan: 08
subsystem: ui
tags: [react, typescript, vitest, eslint, discriminated-union, forms]

# Dependency graph
requires:
  - phase: 22-frontend-foundation-runs-list
    provides: "frontend/ toolchain (22-03), the JSX-form-element lint ban with its
      MutationForm/ConfirmForm override already scoped (eslint.config.js), and the
      React-mounted /runs page + build/test pipeline (22-04) this plan's tests build
      against"
provides:
  - "frontend/src/components/MutationForm.tsx -- the one sanctioned native-form
    emitter besides ConfirmForm; typed action prop against the real
    app/routes/runs.py mutation paths"
  - "frontend/src/components/ConfirmForm.tsx -- composes MutationForm, cancels
    submission via event.preventDefault() (never a handler return value),
    cancellation semantics proven by two independent falsifying mutations"
  - "frontend/src/types/banner.ts -- BannerBranch discriminated union (six
    mutually-exclusive arms + explicit none) and DecisionBannerState with an
    orthogonal hoursChangesOverlay field"
  - "frontend/src/components/DecisionBanner.tsx -- one rendering arm per variant,
    closed by a never-typed exhaustiveness check"
  - "frontend/src/test/setup.ts gained explicit RTL cleanup() in afterEach -- a
    reusable fix any future *.test.tsx file needs, since vitest.config.ts's
    globals:false means RTL's auto-cleanup never self-registers"
affects: [23]

# Actuals (#2632)
actuals:
  tokens: 5526
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Native-form mutation pair: MutationForm renders a bare <form method=\"post\">
      with an onSubmit prop that is undefined unless a composing wrapper (ConfirmForm)
      supplies it -- standalone use is always a plain browser navigation."
    - "Cancellation-by-mutation proof: a component's safety property (preventDefault
      cancels submission) is proven by two independent source mutations (call removed;
      call replaced by a bare falsy return) that both reproduce the identical RED set,
      each reverted byte-identical against a pre-mutation backup copy."
    - "Discriminated union + never-typed exhaustiveness check in the switch's default
      arm, so an armless variant is a compile error rather than a silently missing
      render."
    - "Orthogonal overlay as a separate state field, not a union variant, when the
      source template's conditional is a standalone `if` outside the mutually
      exclusive if/elif chain it visually sits next to."
    - "Vite's `?raw` import (declared via a project vite-env.d.ts) to read a sibling
      TSX file's source as a string inside a test, keeping src/ free of Node `fs`/
      `path`/`process` -- tsconfig.json deliberately omits `\"types\": [\"node\"]` for
      src/, since that tree ships into the browser bundle."

key-files:
  created:
    - frontend/src/components/MutationForm.tsx
    - frontend/src/components/ConfirmForm.tsx
    - frontend/src/components/MutationForm.test.tsx
    - frontend/src/components/DecisionBanner.tsx
    - frontend/src/components/DecisionBanner.test.tsx
    - frontend/src/types/banner.ts
    - frontend/src/vite-env.d.ts
  modified:
    - frontend/src/test/setup.ts

key-decisions:
  - "MutationForm accepts an optional onSubmit prop used ONLY by ConfirmForm's
    composition; a caller that mounts MutationForm directly never supplies it, so
    standalone MutationForm truly attaches no handler of its own. This lets ConfirmForm
    compose MutationForm (as the plan's action text requires) instead of duplicating a
    second raw <form> element, while keeping MutationForm's own default behavior
    (no handler, no preventDefault) intact and independently testable."
  - "action is typed as a MutationActionPath template-literal union derived from
    every @router.post path in app/routes/runs.py, not a free-form string -- per the
    plan's read_first instruction to type the action prop against real paths."
  - "DecisionBanner.test.tsx was added even though only MutationForm.test.tsx was
    named in the plan's files_modified list. The plan's own verify command for Task 2
    is `npm run test -- DecisionBanner`, which requires a matching test file to exist;
    without one the command would pass vacuously (zero tests collected) rather than
    proving the behaviors. Treated as Rule 2 (missing critical functionality)."
  - "frontend/src/test/setup.ts gained an explicit `afterEach(() => cleanup())`. This
    project's vitest.config.ts sets `globals: false`, which prevents
    @testing-library/react's automatic cleanup from self-registering (it only
    auto-detects an ambient global afterEach). Without this, every test after the
    first in a multi-test file would see prior tests' unmounted-but-still-in-DOM trees,
    which is exactly what caused the disabled-button test to fail with 'multiple
    elements found' before this fix. Treated as Rule 3 (blocking) -- this file is a
    Task 1 dependency but not itself in files_modified."
  - "Added frontend/src/vite-env.d.ts declaring the `*?raw` module suffix. tsconfig.json
    deliberately has no `\"types\": [\"node\"]` for src/ (that tree ships to the
    browser), so MutationForm.test.tsx's assertion that RunsPage.tsx does not import
    either component reads RunsPage.tsx's source via Vite's `?raw` import instead of
    Node's `fs`, keeping the test inside the same browser-bundle type boundary as the
    rest of src/. Treated as Rule 3 (blocking) -- required to compile the acceptance
    criterion at all."

patterns-established:
  - "Pattern: native-form + confirm-wrapper pair, with the wrapper composing the base
    form component rather than emitting its own <form>"
  - "Pattern: cancellation-by-mutation proof (two independent mutations, same RED set,
    byte-identical revert against a backup copy) for any React handler whose safety
    property depends on preventDefault vs a return value"
  - "Pattern: discriminated union + never-typed exhaustiveness check for template-derived
    render branches"
  - "Pattern: orthogonal overlay as a state field, never a union variant, for template
    conditionals that are independent `if`s rather than `elif` arms of the branch chain"

requirements-completed: [SHELL-03]

coverage:
  - id: D1
    description: "MutationForm renders exactly one native <form method=\"post\"
      action=...> with the caller's children and nothing else; no submit handler, no
      network call, no preventDefault by default"
    requirement: "SHELL-03"
    verification:
      - kind: unit
        ref: "frontend/src/components/MutationForm.test.tsx -- 3 tests (single form
          element with method/action, no extra interactive elements, default not
          prevented when caller supplies no handler)"
        status: pass
    human_judgment: false
  - id: D2
    description: "ConfirmForm cancels submission on decline by calling
      event.preventDefault(), never by a handler return value; proven false by two
      independent source mutations that both reproduce the identical failing test set"
    requirement: "SHELL-03"
    verification:
      - kind: unit
        ref: "frontend/src/components/MutationForm.test.tsx -- ConfirmForm describe
          block, 6 tests (renders same native form, prompt passed verbatim, confirm
          does not suppress, decline prevents default, submit-without-confirm twice,
          double-submit resolves independently, disabled button blocks handler)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Raw JSX <form> elements outside MutationForm/ConfirmForm fail lint
      (eslint.config.js's no-restricted-syntax rule from 22-03), demonstrated for real
      against a scratch component and then removed"
    requirement: "SHELL-03"
    verification:
      - kind: other
        ref: "cd frontend && npm run lint against a scratch
          _scratchFormBanProof.tsx -- captured error transcript in this SUMMARY's
          Verification section; file deleted, git status --porcelain frontend/src
          confirmed clean of the scratch file"
        status: pass
    human_judgment: false
  - id: D4
    description: "BannerBranch is a discriminated union of the six mutually exclusive
      branches read off run_detail.html:99-208 plus an explicit no-banner variant;
      hoursChangesOverlay is a separate, orthogonal field, not a union variant"
    requirement: "SHELL-03"
    verification:
      - kind: unit
        ref: "frontend/src/components/DecisionBanner.test.tsx -- 9 tests (one per
          branch rendering exactly one banner with correct class/heading, no-banner
          with no overlay renders nothing, no-banner with overlay renders only the
          overlay, a branch with overlay renders both)"
        status: pass
    human_judgment: false
  - id: D5
    description: "Adding a BannerBranch variant without a DecisionBanner rendering arm
      is a compile error, demonstrated for real and reverted byte-identical"
    requirement: "SHELL-03"
    verification:
      - kind: other
        ref: "cd frontend && npm run typecheck against a scratch
          scratch_variant_without_arm branch added to banner.ts -- captured TS2322
          error transcript in this SUMMARY's Verification section; reverted, diff
          confirmed byte-identical against a pre-mutation backup"
        status: pass
    human_judgment: false
  - id: D6
    description: "Neither MutationForm nor ConfirmForm is imported by RunsPage.tsx;
      the JavaScript-disabled demo send-test form path is unmodified"
    requirement: "SHELL-03"
    verification:
      - kind: unit
        ref: "frontend/src/components/MutationForm.test.tsx::RunsPage.tsx imports
          neither MutationForm nor ConfirmForm"
        status: pass
      - kind: unit
        ref: "uv run pytest tests/test_dashboard.py -k demo_send_test -x -q -- 2
          passed, unmodified"
        status: pass
    human_judgment: false

duration: ~25min
completed: 2026-08-17
status: complete
---

# Phase 22 Plan 08: Native-Form Mutation Pair and Decision-Banner Union Summary

**MutationForm/ConfirmForm native-form pair with cancellation semantics proven by two
independent falsifying mutations, and a BannerBranch discriminated union (six branches
+ explicit no-banner + an orthogonal hours-changed overlay) closed by a compiler
exhaustiveness check -- both pulled forward for Phase 23, neither mounted anywhere yet.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2 of 2 complete
- **Files modified:** 8 (5 created for Task 1 including the setup.ts fix and
  vite-env.d.ts, 3 created for Task 2)

## Accomplishments

- `MutationForm.tsx`: the sole standalone native-form emitter. Renders exactly one
  `<form method="post" action={action}>` with the caller's children and nothing else.
  `action` is typed as `MutationActionPath`, a template-literal union enumerating every
  real `@router.post` path in `app/routes/runs.py`, so a typo'd action string fails at
  compile time. Accepts an optional `onSubmit` used only by `ConfirmForm`'s composition
  -- standalone use attaches no handler.
- `ConfirmForm.tsx`: composes `MutationForm` (not a second raw `<form>`) and adds a
  submit handler that calls the caller-supplied `confirmFn` (default `window.confirm`)
  with the caller-supplied prompt text verbatim, then calls `event.preventDefault()`
  on decline -- never relies on the handler's return value, which does NOT cancel a
  React form submission.
- `MutationForm.test.tsx`: 11 tests covering both components -- native form shape, no
  default handler, confirm/decline semantics asserted on `event.defaultPrevented`, two
  negative-path tests explicitly requested by the orchestrator (submit-without-confirm
  across two attempts, and a double-submit proving no state leaks between the two
  resolutions), a disabled-submit-button test, and a source-text check that
  `RunsPage.tsx` imports neither component.
- Two independent falsifying mutations against `ConfirmForm.tsx`, both reproducing the
  identical 3-test RED set and both reverted byte-identical against a pre-mutation
  backup: (1) the `preventDefault()` call deleted outright; (2) the call replaced with a
  bare falsy `return`. See Verification section below for both transcripts.
- The `no-restricted-syntax` JSX-form-element lint ban (already scoped to these two
  components in `eslint.config.js` from plan 22-03) proven to fire for real against a
  scratch component, then the scratch file deleted.
- `banner.ts`: `BannerBranch`, a discriminated union of the six mutually exclusive
  branches read directly off `app/templates/run_detail.html:99-208`'s if/elif chain
  (`error`, `delivery_review_required`, `needs_operator`, `awaiting_reply`,
  `decision_process`, `decision_clarification_requested`), plus an explicit `none`
  variant for the implicit fallthrough. `HoursChangesOverlay` is a separate field on
  `DecisionBannerState`, not a seventh union variant, matching the template's
  independent `{% if run.hours_changes %}` at line 196.
- `DecisionBanner.tsx`: one rendering arm per variant plus the overlay when present,
  closed by a `never`-typed exhaustiveness check in the switch's default arm.
- `DecisionBanner.test.tsx` (added -- see Deviations): 9 tests, one per branch plus the
  four no-banner/overlay composition cases.
- A source mutation adding a `BannerBranch` variant without a `DecisionBanner` arm
  produced the exact expected `TS2322: Type '{ kind: "scratch_variant_without_arm"; }'
  is not assignable to type 'never'` compile error, then reverted byte-identical.
- `frontend/src/test/setup.ts` gained an explicit `afterEach(() => cleanup())` --
  required for correctness of any multi-test `*.test.tsx` file under this project's
  `globals: false` Vitest config, and is now load-bearing for both test files this plan
  added.
- Full verification: `cd frontend && npm run check && npm run test && npm run build`
  all exit 0 (20 tests across the two new files, a real Vite production build).
  `uv run pytest -q` -- 1449 passed, 107 skipped, matching the wave-4 fork-point
  baseline exactly (no regression). `uv run pytest tests/test_dashboard.py -k
  demo_send_test -x -q` -- 2 passed, unmodified. `uv run pytest
  tests/test_design_tokens.py -q` -- 12 passed (design-token guard clean; no hardcoded
  colors introduced).

## Task Commits

1. **Task 1: MutationForm and ConfirmForm, with the cancellation semantics proven by
   mutation** -- `0d977f4` (feat)
2. **Task 2: The decision-banner discriminated union -- six branches, a no-banner case,
   one orthogonal overlay** -- `a43e55c` (feat)

## Files Created/Modified

**Task 1 (`0d977f4`):**
- `frontend/src/components/MutationForm.tsx` -- native-form component
- `frontend/src/components/ConfirmForm.tsx` -- confirm-wrapping composition
- `frontend/src/components/MutationForm.test.tsx` -- both components' test suite
- `frontend/src/test/setup.ts` -- added RTL `cleanup()` in `afterEach` (deviation)
- `frontend/src/vite-env.d.ts` -- new file, declares `*?raw` module type (deviation)

**Task 2 (`a43e55c`):**
- `frontend/src/types/banner.ts` -- `BannerBranch`, `HoursChangeItem`,
  `HoursChangesOverlay`, `DecisionBannerState`
- `frontend/src/components/DecisionBanner.tsx` -- rendering component
- `frontend/src/components/DecisionBanner.test.tsx` -- new file, test suite (deviation)

## Decisions Made

- **MutationForm's `onSubmit` prop is a composition seam, not a public feature.** The
  task text says MutationForm "must not attach a submit handler" while also saying
  ConfirmForm "composes MutationForm and adds a submit handler." The only way to satisfy
  both without ConfirmForm emitting a second raw `<form>` (which the lint ban's own
  override list treats as two independent authorized emitters, not one delegating to
  the other) is an optional prop that MutationForm never populates by default. Standalone
  callers -- the only consumers in this phase are the tests -- never pass it, so
  MutationForm's own behavior tests (no handler attached, default never prevented)
  remain meaningful.
- **`action` is a template-literal union (`MutationActionPath`) enumerating every real
  `@router.post` path in `app/routes/runs.py`**, per the plan's own read_first
  instruction ("the component's action prop is typed against real paths rather than
  free-form strings"). This is the mechanism Phase 23's 14 mutation forms will use
  directly; no new paths need to be invented, only consumed.
  Phase 23 that add a new mutation route will extend this union.
- **`DecisionBanner`'s per-arm content is exactly a callout class and a heading string**,
  matching the plan's explicit instruction to pull forward the shape, not Phase 23's
  branch bodies (gate-reason lists, unresolved-name displays, the resolve/reject
  sub-forms). A `Banner` helper component takes `variant`/`heading` so each of the six
  cases is a one-line call.
- **The hours-changed overlay renders its `changes` list only when non-empty** (an empty
  `changes: []` array still renders the heading with no divider), matching the
  template's own defensive `{% for change in run.hours_changes %}` loop, which
  degrades gracefully to an empty list rather than assuming at least one entry.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `frontend/src/test/setup.ts` had no automatic RTL cleanup
between tests**
- **Found during:** Task 1, while writing the disabled-submit-button test
- **Issue:** This project's `vitest.config.ts` sets `globals: false` (explicit
  `import { afterEach } from "vitest"` over ambient globals per the project's own
  comment). `@testing-library/react`'s automatic `cleanup()` self-registration only
  fires when it detects a global `afterEach`, so with `globals: false` it never runs.
  Every rendered tree stayed mounted in `document.body` for the rest of the file,
  which made `screen.getByRole("button", { name: "Reject" })` in the disabled-button
  test match multiple leftover buttons from earlier tests in the same `describe` block
  and throw a "multiple elements found" error -- not the assertion the test was written
  to make.
- **Fix:** Added an explicit `afterEach(() => cleanup())` to `frontend/src/test/setup.ts`,
  registered via `vitest.config.ts`'s existing `setupFiles`.
- **Files modified:** `frontend/src/test/setup.ts`
- **Verification:** `cd frontend && npm run test -- MutationForm` -- all 11 tests pass
  in isolation and in the full file.
- **Committed in:** `0d977f4` (Task 1 commit)

**2. [Rule 3 - Blocking] `RunsPage.tsx`-does-not-import-either-component` assertion had
no Node-free way to read a sibling file's source**
- **Found during:** Task 1, implementing the acceptance criterion "`RunsPage.tsx`
  imports neither component"
- **Issue:** `frontend/tsconfig.json` (the config governing everything under `src/`,
  including test files) deliberately has no `"types": ["node"]` entry -- only
  `tsconfig.node.json` (scoped to `vite.config.ts`/`vitest.config.ts` only) does,
  because `src/` ships into the browser production bundle and is meant to stay free of
  Node-only APIs. Using `node:fs`'s `readFileSync` plus `process.cwd()` from
  `MutationForm.test.tsx` therefore failed `npm run typecheck` with `TS2591: Cannot
  find name 'process'` and the equivalent for the two `node:` imports.
- **Fix:** Added `frontend/src/vite-env.d.ts` declaring the `*?raw` module suffix (a
  documented, common Vite pattern not included in Vite's own `client.d.ts` by default),
  and changed the test to `import runsPageSource from "../pages/RunsPage.tsx?raw"`,
  which reads the file's source as a plain string via Vite's own asset-import pipeline
  -- identical under Vitest and a real build, and inside the same browser-bundle type
  boundary as the rest of `src/`.
- **Files modified:** `frontend/src/vite-env.d.ts` (new), `frontend/src/components/
  MutationForm.test.tsx`
- **Verification:** `cd frontend && npm run check` exits 0 (typecheck + lint clean);
  the source-text assertion test passes.
- **Committed in:** `0d977f4` (Task 1 commit)

**3. [Rule 2 - Missing Critical] Task 2's verify command needed a matching test file
that was not in the plan's `files_modified` list**
- **Found during:** Task 2
- **Issue:** The plan's Task 2 `<verify>` is `cd frontend && npm run test --
  DecisionBanner`, and its `files_modified` frontmatter lists only
  `frontend/src/types/banner.ts` and `frontend/src/components/DecisionBanner.tsx` (no
  `DecisionBanner.test.tsx`). Without a file whose path contains "DecisionBanner" and
  matches Vitest's `include` glob (`src/**/*.test.{ts,tsx}`), `npm run test --
  DecisionBanner` would collect zero test files and pass vacuously
  (`vitest.config.ts`'s `passWithNoTests: true`) -- proving nothing about the nine
  behaviors the task's `<behavior>` and `<acceptance_criteria>` sections require.
- **Fix:** Added `frontend/src/components/DecisionBanner.test.tsx` with the nine tests
  the acceptance criteria describe (one per branch, plus the four no-banner/overlay
  composition cases).
- **Files modified:** `frontend/src/components/DecisionBanner.test.tsx` (new)
- **Verification:** `cd frontend && npm run test -- DecisionBanner` -- 9 tests pass,
  matching the plan's own verify command.
- **Committed in:** `a43e55c` (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (2 Rule 3 - blocking, 1 Rule 2 - missing critical).
**Impact on plan:** No scope creep -- all three are infrastructure the plan's own stated
acceptance criteria and verify commands required to actually run and prove anything.
None touch `RunsPage.tsx` or any file outside this plan's component/type/test surface.

## Issues Encountered

None beyond the three deviations documented above.

## User Setup Required

None -- no external service configuration required.

## Verification Transcripts

### Mutation 1: `preventDefault()` call removed from `ConfirmForm.tsx`

Live-source confirmation before mutating:
```
$ grep -n "preventDefault" frontend/src/components/ConfirmForm.tsx
6:// `onSubmit` handler does NOT cancel form submission -- only calling `preventDefault()`
40:      // The decline path, and the whole point of this component. Only preventDefault()
44:      event.preventDefault();
46:    // On confirm, no preventDefault is called: the native POST proceeds exactly as
```
Line 44 (the live call) removed; lines 6/40/46 are comments, left untouched.

RED (`cd frontend && npm run test -- MutationForm`):
```
FAIL  src/components/MutationForm.test.tsx > ConfirmForm > cancels the submit event by
  calling preventDefault when the operator declines ...
  AssertionError: expected false to be true

FAIL  src/components/MutationForm.test.tsx > ConfirmForm > submit-without-confirm: a
  decline never lets the submission through ...
  AssertionError: expected false to be true

FAIL  src/components/MutationForm.test.tsx > ConfirmForm > double-submit: two
  submissions in a row each resolve independently ...
  AssertionError: expected false to be true

Test Files  1 failed (1)
     Tests  3 failed | 8 passed (11)
```
Restored from a pre-mutation backup copy; `diff` against the backup: identical (no
output). `git diff --stat frontend/src/components/ConfirmForm.tsx` and `npm run test --
MutationForm` afterward: 11/11 pass. (`git diff --stat` is trivially empty for this file
regardless of content, since it was still untracked at mutation time -- the byte-identical
`diff` against the backup copy is the real proof; the same caveat applies to the Task 2
`banner.ts` mutation below.)

### Mutation 2: `preventDefault()` replaced with a bare falsy return

```diff
- function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
-   const confirmed = confirmFn(confirmMessage);
-   if (!confirmed) {
-     event.preventDefault();
-   }
- }
+ function handleSubmit(): boolean {
+   const confirmed = confirmFn(confirmMessage);
+   return confirmed;
+ }
```
`grep -n "preventDefault"` confirmed zero remaining occurrences in the mutated file
before running tests.

RED (`cd frontend && npm run test -- MutationForm`): the identical 3 tests failed with
the identical `expected false to be true` assertion errors as Mutation 1 -- proving the
test suite is asserting the return-value-does-not-cancel distinction specifically, not
merely "some preventDefault-shaped code exists."

Restored from the same pre-mutation backup; `diff` against the backup: identical.
`npm run check` and `npm run test -- MutationForm` afterward: both clean, 11/11 pass.

### Lint ban proof

Scratch file `frontend/src/components/_scratchFormBanProof.tsx`:
```tsx
export function ScratchFormBanProof() {
  return <form method="post" action="/scratch"></form>;
}
```

```
$ cd frontend && npm run lint
.../frontend/src/components/_scratchFormBanProof.tsx
  4:10  error  Raw <form> elements are banned outside MutationForm and ConfirmForm.
  Every mutation submission must go through one of those two shared wrapper
  components so the confirm() dialog and preventDefault() safety guard are never
  silently bypassed by a hand-written form  no-restricted-syntax

✖ 1 problem (1 error, 0 warnings)
```
File deleted; `git status --porcelain frontend/src` afterward showed only this plan's
own real files (no scratch file remaining).

### Banner exhaustiveness compile-error proof

```diff
  | { kind: "none" }
+ | { kind: "scratch_variant_without_arm" };
```

```
$ cd frontend && npm run typecheck
src/components/DecisionBanner.tsx(43,13): error TS2322: Type '{ kind:
"scratch_variant_without_arm"; }' is not assignable to type 'never'.
```
Restored from a pre-mutation backup copy of `banner.ts`; `diff` against the backup:
identical. `npm run check` and `npm run test -- DecisionBanner` afterward: both clean,
9/9 pass.

## Next Phase Readiness

- `MutationForm`/`ConfirmForm` and `BannerBranch`/`DecisionBanner` are real, tested, and
  ready for Phase 23 to compose directly: 14 mutation forms reuse `MutationForm`
  (extending `MutationActionPath` with any genuinely new routes), the 5 confirm sites
  reuse `ConfirmForm`, and the run-detail page's decision banner fills in each arm's
  body content without touching the union shape, discriminator, or overlay composition
  established here.
- Neither component is mounted anywhere yet -- by design (D-22-12): the demo send-test
  form on `/runs` stays server-rendered Jinja, and `RunsPage.tsx` (owned concurrently by
  plan 22-06 in this same wave) was not touched.
- No blockers. Full verification (frontend check/test/build, the two targeted pytest
  checks, and the full `uv run pytest -q` suite at 1449 passed / 107 skipped) all green.

## Self-Check: PASSED

- All 8 claimed files confirmed present via `ls -la`.
- Commits `0d977f4` and `a43e55c` both found in `git log --oneline --all`.
- `cd frontend && npm run check && npm run test && npm run build` all exit 0 (20 tests,
  real production build).
- `uv run pytest -q` -- 1449 passed, 107 skipped (matches wave-4 fork-point baseline
  exactly).
- `uv run pytest tests/test_dashboard.py -k demo_send_test -x -q` -- 2 passed,
  unmodified.
- `uv run pytest tests/test_design_tokens.py -q` -- 12 passed (no hardcoded colors
  introduced).
- No missing items.

---
*Phase: 22-frontend-foundation-runs-list*
*Completed: 2026-08-17*
