---
phase: 22-frontend-foundation-runs-list
plan: 03
subsystem: infra
tags: [vite, react, typescript, eslint, vitest, npm, frontend-toolchain, docker]

# Dependency graph
requires:
  - phase: 22-frontend-foundation-runs-list
    provides: GUARD-01 test-assertion inventory (plan 22-01), which must exist before any
      file lands under frontend/src per the CI gate at .github/workflows/ci.yml
provides:
  - A pinned, lockfile-committed frontend/ toolchain (Vite, React 19, TypeScript 6.0.3,
    ESLint flat config with GUARD-06 bans, Vitest) that builds a real bundle into
    app/static/dist/ through the existing /static mount
  - frontend/MANIFEST-SHAPE.md, the verbatim real Vite manifest shape a later plan's
    manifest loader is written against
  - One npm command (`check`) that typechecks then lints and is proven able to fail on
    either half; one command (`test`) that runs Vitest once and exits
  - .gitignore/.dockerignore entries excluding frontend/node_modules and the build output
    from both git and the Docker build context
affects: [22-04, 22-05, 22-06, 22-08, 22-09, 22-10, 22-11]

# Actuals (#2632)
actuals:
  tokens: 40949
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: [vite@8.2.1, react@19.2.8, react-dom@19.2.8, typescript@6.0.3, "@vitejs/plugin-react@6.0.5", vitest@4.1.10, "@testing-library/react@16.3.2", "@testing-library/jest-dom@7.0.1", "@testing-library/dom@10.4.1", jsdom@30.0.1, eslint@10.8.1, typescript-eslint@8.67.0, eslint-plugin-react-hooks@7.1.1, openapi-typescript@7.13.0]
  patterns:
    - "npm package.json overrides block to force acceptance of a stale peer-dependency
      range, applied narrowly to one package and verified functionally (not just
      resolver-accepted) before use"
    - "ESLint flat config composing typescript-eslint's type-checked recommended set with
      a plugin's recommended set, then two narrow path-scoped override blocks that turn a
      project-wide ban back on only for its one sanctioned file"
    - "projectService.allowDefaultProject for TS config files (vite.config.ts,
      vitest.config.ts) that sit outside the app tsconfig's include list"

key-files:
  created:
    - frontend/package.json
    - frontend/package-lock.json
    - frontend/vite.config.ts
    - frontend/tsconfig.json
    - frontend/tsconfig.node.json
    - frontend/eslint.config.js
    - frontend/vitest.config.ts
    - frontend/src/test/setup.ts
    - frontend/src/entries/runs.tsx
    - frontend/MANIFEST-SHAPE.md
    - frontend/README.md
  modified:
    - .gitignore
    - .dockerignore

key-decisions:
  - "Resolved the openapi-typescript@^5.x vs locked typescript@6.0.3 peer conflict with a
    scoped npm overrides entry, applied only after the orchestrator independently verified
    it end to end (real OpenAPI doc, real codegen, strict typecheck of the output under
    6.0.3, all exit 0) -- not accepted on the resolver's say-so alone"
  - "Consolidated the current Vite react-ts template's tsconfig.json + tsconfig.app.json
    project-references split down to the single tsconfig.json the plan specifies, and
    dropped the template's default oxlint tooling in favor of the plan's ESLint stack"
  - "vitest.config.ts sets passWithNoTests: true because this plan creates no .test.tsx
    file -- an empty suite is a legitimate pass here, not a masked failure"

patterns-established:
  - "Pattern: scoped npm overrides + functional verification, not --legacy-peer-deps, for
    a stale peer-dependency range on an otherwise-correct pinned version"
  - "Pattern: ESLint flat-config project rules scoped to src/**, with narrow path-scoped
    override blocks that are inert until the file they target exists"

requirements-completed: [SHELL-04, SHELL-06]

coverage:
  - id: D1
    description: "Pinned, lockfile-committed frontend/ toolchain installs cleanly with npm
      ci and zero unmet peer dependencies"
    requirement: "SHELL-06"
    verification:
      - kind: other
        ref: "cd frontend && npm ci (258 packages, 0 vulnerabilities, exit 0)"
        status: pass
    human_judgment: false
  - id: D2
    description: "One command (npm run check) typechecks then lints and is proven able to
      fail on either half; one command (npm run test) runs Vitest once and exits without
      a watcher"
    requirement: "SHELL-04"
    verification:
      - kind: other
        ref: "cd frontend && npm run check && npm run test (exit 0); deliberate type error
          and deliberate lint violation each captured failing then reverted clean, see
          Deviations section"
        status: pass
    human_judgment: false
  - id: D3
    description: "A real npm run build produces app/static/dist/.vite/manifest.json, and
      frontend/MANIFEST-SHAPE.md records its verbatim shape (path, top-level key form,
      chunk key set) from that real build, not from documentation"
    verification:
      - kind: other
        ref: "cd frontend && npm run build; diff against frontend/MANIFEST-SHAPE.md's
          embedded JSON block (byte-identical)"
        status: pass
    human_judgment: false
  - id: D4
    description: "SHELL-04's dev-server-with-hot-reload half is NOT delivered by this plan
      -- only the typecheck-and-lint half. The dev-server proxy is plan 22-09, per this
      plan's own flagged planner assumption note."
    verification: []
    human_judgment: true
    rationale: "No dev-server code exists yet to verify; this deliverable is a scope
      boundary fact for a human/later-plan to confirm, not something this plan can prove."

duration: 13min (this continuation dispatch, Task 2 + Task 3; Task 1's package-legitimacy
  checkpoint was approved in a prior session)
completed: 2026-08-17
status: complete
---

# Phase 22 Plan 03: Frontend Toolchain, Real Build, Manifest Shape Summary

**Pinned Vite 8 + React 19 + TypeScript 6.0.3 + ESLint 10 + Vitest 4 toolchain, installed
via a scoped `overrides` fix for a real peer conflict verified end to end, with a real
build recording the exact Vite manifest shape a later plan's loader is written against.**

## Performance

- **Duration:** 13 min (this dispatch; resumed after Task 1's human-approved
  package-legitimacy checkpoint from a prior session)
- **Started:** 2026-08-17T22:00:00Z (approx, this continuation dispatch)
- **Completed:** 2026-08-17T22:15:00Z
- **Tasks:** 3 of 3 (Task 1 approved in a prior session; Task 2 and Task 3 executed and
  committed in this dispatch)
- **Files modified:** 13 (11 created, 2 modified) plus `frontend/package-lock.json`

## Accomplishments

- Scaffolded `frontend/` from the Vite `react-ts` template, deleted every template
  artefact this project does not use (static HTML entry, `App.tsx`/`App.css`, `index.css`,
  `main.tsx`, `src/assets/`, `public/`, the template's default `oxlint` tooling), and
  pinned all 17 approved packages at exact versions (no floating dist-tags).
- Resolved a real `npm install` peer-dependency conflict — every published
  `openapi-typescript` release (including the pinned `7.13.0`, which is also `latest`)
  declares `typescript: ^5.x` as its only accepted peer, which does not admit the locked
  `6.0.3` pin — via a scoped `overrides` entry, applied only after functional verification
  (not just resolver acceptance) that the pinned combination works: actually-resolved
  TypeScript is `6.0.3`, `openapi-typescript` ran against this project's real generated
  OpenAPI document and produced real output, and that output typechecks clean under
  `tsc --strict` on `6.0.3`. Documented in `frontend/README.md`.
- Ran a real `npm run build` and recorded the verbatim manifest shape in
  `frontend/MANIFEST-SHAPE.md`: the manifest lands at `.vite/manifest.json` relative to
  the configured `outDir`, its top-level keys are the entry's source path
  (`src/entries/runs.tsx`, not the short `rollupOptions.input` key `runs`), the chunk
  object's key set is `file, name, src, isEntry`, and no `css` key appears at all (not an
  empty array) when the entry imports no stylesheet.
- Wrote `frontend/eslint.config.js`: typescript-eslint's type-checked recommended rules
  composed with the React Hooks plugin's recommended set (`exhaustive-deps` bumped to
  `error`), plus project rules over `src/**` banning `fetch`/`XMLHttpRequest` outside the
  poller hook, banning `axios` everywhere, banning a raw `<form>` JSX element outside the
  two sanctioned form components, and banning the raw-HTML JSX attribute everywhere — with
  exactly two narrow path-scoped overrides re-enabling each ban only at its one sanctioned
  (not-yet-existing) file.
- Wrote `frontend/vitest.config.ts` (jsdom environment, explicit test-API imports,
  `src/test/setup.ts` registered, scoped to `src/**/*.test.{ts,tsx}`) and
  `frontend/src/test/setup.ts` (imports the DOM matcher extensions).
- Set the `package.json` scripts block to `dev`, `build`, `typecheck`, `lint`, `check`
  (chains typecheck then lint), and `test` (Vitest run mode, never a watcher), and proved
  `check` can actually fail on both halves — see the Deviations section for the captured
  output.
- `.gitignore` gained a `node_modules` entry; `.dockerignore` gained
  `frontend/node_modules/` and `app/static/dist/`, each with a comment naming the specific
  failure it prevents (a local dependency tree or bundle riding into the Docker build
  context while the actual in-image install/build silently never runs).

## Task Commits

Each task was committed atomically:

1. **Task 1: Package legitimacy confirmation before the first install** — approved by the
   human in a prior session (checkpoint, no code change; see Package Evidence table below)
2. **Task 2: Scaffold frontend/, pin every version, run one real build, record the
   manifest shape** — `6faf442` (chore, WIP scaffold committed while blocked on the peer
   conflict) then `b8e6efa` (feat, completed after the coordinator's tested Option A
   decision)
3. **Task 3: ESLint flat config with the GUARD-06 bans, Vitest config, and the npm script
   surface** — `b820df9` (feat)

_Note: Task 2 has two commits because it was interrupted by a genuine blocking finding
(the peer-dependency conflict) that required a checkpoint; both commits are part of Task 2._

## Files Created/Modified

- `frontend/package.json` — pins all 17 packages at exact versions; carries the scoped
  `openapi-typescript` → `typescript` override; scripts block (`dev`, `build`,
  `typecheck`, `lint`, `check`, `test`)
- `frontend/package-lock.json` — committed lockfile, `npm ci` reproduces it exactly
- `frontend/vite.config.ts` — React plugin, `base: "/static/dist/"`,
  `build.outDir: "../app/static/dist"`, `build.emptyOutDir: true`, `build.manifest: true`,
  named `rollupOptions.input.runs`
- `frontend/tsconfig.json` — single-file strict config (consolidated from the template's
  project-references split), automatic JSX runtime, bundler resolution, `src` included
- `frontend/tsconfig.node.json` — covers `vite.config.ts` and `vitest.config.ts`
- `frontend/eslint.config.js` — flat config, type-checked rules, GUARD-06 bans, two
  narrow overrides
- `frontend/vitest.config.ts` — jsdom, `passWithNoTests: true`, `setupFiles`, `include`
- `frontend/src/test/setup.ts` — imports `@testing-library/jest-dom/vitest`
- `frontend/src/entries/runs.tsx` — placeholder entry, replaced by plan 22-04
- `frontend/MANIFEST-SHAPE.md` — verbatim real-build manifest shape record
- `frontend/README.md` — documents the `openapi-typescript`/TypeScript override and its
  verification
- `.gitignore` — `node_modules/` entry
- `.dockerignore` — `frontend/node_modules/` and `app/static/dist/` entries, each commented

## Decisions Made

- **Scoped `overrides` over `--legacy-peer-deps`, verified before use, not assumed.** The
  plan's own acceptance criteria singled out this exact failure mode ("if it does not
  [complete with zero unmet peer deps], stop and report rather than forcing it with a
  legacy-peer flag"). I halted and returned a `checkpoint:decision` with the finding, the
  verified-working override mechanism, and three options. The orchestrator did not decide
  on judgment — it independently tested the override in an isolated sandbox against this
  project's real generated OpenAPI document (30 paths, 7 schemas), confirmed the
  actually-resolved TypeScript was `6.0.3` (not a silent `5.x` fallback), and confirmed the
  generated `.d.ts` typechecks clean under `tsc --strict` on `6.0.3`. Only then did I apply
  the override and continue.
- **Consolidated the Vite template's tsconfig split.** The current `npm create vite@latest
  -- --template react-ts` scaffolder ships `tsconfig.json` (project references) +
  `tsconfig.app.json` + `tsconfig.node.json` and `oxlint` as the default linter — a newer
  shape than the plan/research anticipated. Deleted `tsconfig.app.json` and `.oxlintrc.json`,
  rewrote `tsconfig.json` as the single strict-mode file the plan specifies, and built the
  ESLint stack the plan calls for instead of the scaffolded `oxlint`.
- **`passWithNoTests: true` in `vitest.config.ts`.** This plan's file list creates no
  `.test.tsx` file (the first component tests land in later plans per the phase's file
  inventory). An empty suite exiting 0 is the honest outcome here, not a masked failure —
  documented inline in the config with a comment explaining why.

## Package Evidence Table (Task 1 gate, recorded per orchestrator instruction)

The 4 packages never previously run through `package-legitimacy check` were checked live
by the orchestrator before Task 1's checkpoint was approved:

| Package | Verdict | Downloads/wk | Published | Repo | postinstall | Deprecated |
|---|---|---|---|---|---|---|
| `@types/react` | SUS (`too-new` only) | 132,238,902 | 2026-07-30 | DefinitelyTyped | null | false |
| `@types/react-dom` | SUS (`too-new` only) | 88,068,836 | 2026-07-30 | DefinitelyTyped | null | false |
| `@types/node` | SUS (`too-new` only) | 351,512,174 | 2026-08-07 | DefinitelyTyped | null | false |
| `@testing-library/dom` | OK | 56,415,905 | 2025-07-27 | testing-library/dom-testing-library | null | false |

All 17 packages installed by this plan are therefore measured rather than inferred; every
one has `postinstall: null` (no install-time script execution); none is deprecated; every
SUS verdict across the whole set carries the single `too-new` reason and nothing else.
TypeScript is pinned at `6.0.3` as a deliberate locked override of the research's `7.0.2`
recommendation; ESLint (not Biome) is used because of
`eslint-plugin-react-hooks`'s `exhaustive-deps` rule.

## `openapi-typescript` / TypeScript Peer Conflict — Verification Table (recorded per
orchestrator instruction)

Verified by the orchestrator in an isolated sandbox, outside this worktree, before
directing Option A:

| Check | Result |
|---|---|
| `npm install` with the scoped override | clean, exit 0, 33 packages (isolated minimal repro) |
| Resolved TypeScript version | `6.0.3` — the locked pin, not a silent `5.x` fallback |
| `openapi-typescript@7.13.0` against this project's real OpenAPI doc (`app.main:app`, 30 paths, 7 schemas) | clean, exit 0, 1,802 lines emitted in 38.5ms |
| Generated `.d.ts` typechecked under `tsc --noEmit --strict --skipLibCheck false` on TS `6.0.3` | exit 0, zero errors |
| Output content is real, not stubs | all 7 component schemas present by name (`HTTPValidationError`, `ValidationError`, 5 `Body_*` types), 102 typed members |
| `openapi-typescript` latest dist-tag | `7.13.0` — confirmed there is no `8.x`; "bump the major" was never available |

Reproduced independently in this worktree (not just trusted from the sandbox report):
`npm ci` here resolves 258 packages / 0 vulnerabilities, `node_modules/typescript`'s own
`package.json` reports `6.0.3`, and `npm run build` produces a real bundle + manifest.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 4, resolved via orchestrator-tested decision] `openapi-typescript` peer
conflict with the locked TypeScript pin**
- **Found during:** Task 2
- **Issue:** `npm install` failed with `ERESOLVE` before installing anything — every
  published `openapi-typescript` version declares `typescript: ^5.x` as its only accepted
  peer, which does not admit the locked `6.0.3`. The plan's own acceptance criteria named
  this exact failure mode and forbade forcing it with `--legacy-peer-deps`.
- **Fix:** Halted, returned a `checkpoint:decision` with three options (recommended: a
  scoped `overrides` block, verified working via `npm install --dry-run`). The
  orchestrator independently tested the fix functionally (real codegen against the real
  OpenAPI doc, strict typecheck of the output, both exit 0 on TS `6.0.3`) before directing
  Option A. Applied exactly the tested `overrides` block; documented the reasoning and
  evidence in `frontend/README.md`.
- **Files modified:** `frontend/package.json`, `frontend/README.md`
- **Verification:** `npm ci` — 258 packages, 0 vulnerabilities, `node_modules/typescript`
  reports `6.0.3`.
- **Committed in:** `b8e6efa`

**2. [Rule 3 - Blocking] ESLint `projectService` could not find `vite.config.ts` /
`vitest.config.ts`**
- **Found during:** Task 3
- **Issue:** `npm run lint` failed with `Parsing error: ... was not found by the project
  service` for both config files — `projectService` auto-discovers only files literally
  named `tsconfig.json`; it does not walk `tsconfig.node.json`'s own `include` list even
  though both files are listed there.
- **Fix:** Added `parserOptions.projectService.allowDefaultProject: ["vite.config.ts",
  "vitest.config.ts"]`, giving those two files an inferred single-file project instead of
  erroring.
- **Files modified:** `frontend/eslint.config.js`
- **Verification:** `npm run lint` exits 0.
- **Committed in:** `b820df9`

**3. [Rule 3 - Blocking] `eslint.config.js` itself had no covering tsconfig for
type-aware parsing**
- **Found during:** Task 3
- **Issue:** The type-checked rule set applies broadly by default; `eslint.config.js` is
  plain JS with no `tsconfig.json`/`tsconfig.node.json` entry covering it, so linting the
  config file itself would error the same way.
- **Fix:** Added an override scoped to `files: ["eslint.config.js"]` spreading
  `tseslint.configs.disableTypeChecked`, which sets `projectService: false` for that one
  file.
- **Files modified:** `frontend/eslint.config.js`
- **Verification:** `npm run lint` exits 0 with no parse error on `eslint.config.js`.
- **Committed in:** `b820df9`

**4. [Rule 3 - Blocking] `npm run test` exited 1 on an empty suite**
- **Found during:** Task 3
- **Issue:** No `.test.tsx` file exists yet in this plan's file list (the first component
  tests land in later plans), and Vitest's default behavior is to exit 1 when no test
  files match.
- **Fix:** Added `test.passWithNoTests: true` to `vitest.config.ts`, with a comment
  explaining why an empty suite is a legitimate pass here rather than a masked failure.
- **Files modified:** `frontend/vitest.config.ts`
- **Verification:** `npm run test` exits 0.
- **Committed in:** `b820df9`

**5. [Rule 1 - cleanup] Removed the scaffolder's default `oxlint` tooling and consolidated
the tsconfig split**
- **Found during:** Task 2
- **Issue:** `npm create vite@latest -- --template react-ts` currently scaffolds
  `oxlint`/`.oxlintrc.json` as the default linter and a three-file `tsconfig.json` +
  `tsconfig.app.json` + `tsconfig.node.json` project-references split — neither matches
  the plan's explicit single-file `tsconfig.json` + ESLint-stack specification (the
  scaffolder has moved on since the plan/research was written).
  - **Fix:** Deleted `tsconfig.app.json` and `.oxlintrc.json`; rewrote `tsconfig.json` as
    the single strict-mode file the plan specifies; removed `oxlint` from
    `devDependencies` and did not carry its `lint` script forward.
- **Files modified:** `frontend/package.json`, `frontend/tsconfig.json`
  (`frontend/tsconfig.app.json` and `frontend/.oxlintrc.json` deleted, never committed)
- **Verification:** `npm run check` exits 0 against the consolidated config.
- **Committed in:** `6faf442`

---

**Total deviations:** 5 (1 architectural conflict resolved via checkpoint + orchestrator
verification, 3 blocking-issue auto-fixes, 1 cleanup).
**Impact on plan:** All fixes were necessary to complete the plan's own acceptance
criteria; none change the plan's locked stack pins (TypeScript stays `6.0.3`,
`openapi-typescript` stays `7.13.0`). No scope creep.

## Known Stubs

- **`frontend/src/entries/runs.tsx`** — a single side-effect-free placeholder export
  (`RUNS_ENTRY_PLACEHOLDER`), with no real mounting logic. This is intentional and named
  in the plan itself: "Create `frontend/src/entries/runs.tsx` as a minimal placeholder
  module with a single side-effect-free export, purely so the build has an input; plan
  22-04 replaces it with the real mounting entry." It exists only so `npm run build` has a
  real input to produce the manifest this plan records. Not a gap this plan should have
  closed.

**Broken-windows ledger:** attempted to append this stub via `gsd-tools query windows
append`, but `gsd-core/bin/gsd-tools.cjs` was not reachable from inside this sandboxed
worktree at any of the documented lookup paths (no `gsd-core/` under the worktree root,
and the sandbox's own path guard refused shell commands referencing locations outside the
worktree, including read-only lookups under `$HOME`). Per the ledger's own contract this
is best-effort and non-blocking; recording the attempt here so the orchestrator can
populate it centrally if desired.

## Issues Encountered

An early Bash command in this dispatch used an absolute path pointing at the shared main
checkout instead of this worktree, so the first `npm create vite` scaffold landed in the
wrong location. Caught before any commit (the Write tool's worktree-path guard refused a
subsequent write into that location), the erroneous `frontend/` directory in the main
checkout was removed (`rm -rf`, a plain filesystem cleanup of files created seconds
earlier in this same session, not a git operation), and the scaffold was redone correctly
inside the worktree. No commit, file, or other agent's work was affected.

## User Setup Required

None — no external service configuration required. This plan only touches `frontend/` and
two ignore files.

## Next Phase Readiness

- `frontend/` has a real, pinned, npm-ci-reproducible toolchain and a real build producing
  `app/static/dist/.vite/manifest.json` — plan 22-04's manifest loader can be written
  against `frontend/MANIFEST-SHAPE.md`'s recorded shape with no further discovery needed.
- `frontend/eslint.config.js`'s two override blocks (`src/hooks/usePoller.ts`;
  `src/components/MutationForm.tsx` + `ConfirmForm.tsx`) are inert until those files exist
  — later plans (22-08, 22-10 per the phase's file inventory) create them and inherit the
  ban/override wiring for free.
- SHELL-04 is only half-delivered: `npm run check`/`npm run dev` exist, but the dev-server
  proxy-to-uvicorn behavior itself is plan 22-09's responsibility, as flagged in this
  plan's own text.
- The full Python suite (1428 passed / 107 skipped), `ruff check .`, and `mypy` all stay
  green — this plan added no Python code and disturbed nothing on that side.
- `git status --porcelain` is clean; `app/static/dist` and `frontend/node_modules` are
  untracked and correctly ignored by both `.gitignore` and `.dockerignore`.

## Self-Check: PASSED

- Commits `6faf442`, `b8e6efa`, `b820df9` all found in `git log --oneline --all`.
- All 13 claimed files confirmed present via `git ls-files frontend/ .gitignore
  .dockerignore` (11 created under `frontend/`, `.gitignore` and `.dockerignore`
  modified, plus the auto-generated `frontend/package-lock.json`).
- No missing items.

---
*Phase: 22-frontend-foundation-runs-list*
*Completed: 2026-08-17*
