# Stack Research — v5 React/TypeScript Operator Console

**Domain:** Adding a React + TypeScript frontend (3 vertical slices) to a shipped FastAPI + Jinja2 app
**Researched:** 2026-08-17
**Confidence:** HIGH on all version numbers (live npm registry reads, 2026-08-17). MEDIUM on TypeScript 7.0
maturity (GA five weeks old — see flag below). MEDIUM on the exact Docker asset-path wiring until a
frontend build config exists to test against.

All versions below were read directly from `https://registry.npmjs.org/<pkg>` (dist-tags.latest) on
2026-08-17, not from memory or search-engine summaries (which returned stale/rounded numbers for several
packages — e.g. a websearch claimed React "19.2.8, last published a month ago" while the registry itself
confirms `19.2.8` is in fact `dist-tags.latest` today, so that one happened to agree; treat any number in
this file that is NOT sourced from a `curl registry.npmjs.org` call as unverified).

---

## 1. Core build toolchain

| Technology | Version | Purpose | Why (for THIS repo) |
|---|---|---|---|
| **Vite** | `8.2.1` | Build/dev server | Zero-config multi-page (multi-entry) build — exactly what 3 independently-shippable slices need without a monorepo tool (see §7). No server component, so it doesn't fight FastAPI for ownership of routing. |
| **React** | `19.2.8` | UI library | Current stable line; `@types/react` and `@types/react-dom` track it 1:1 (see below). No reason to pin lower — this is a brand-new frontend, there is no legacy React code to preserve compatibility with. |
| **TypeScript** | `7.0.2` | Type checking | GA'd 2026-07-08 (npm `dist-tags.latest`, confirmed via `registry.npmjs.org/typescript`). This is the Go-native compiler rewrite ("tsgo" merged into the mainline `tsc` binary) — 8-12x faster `tsc --noEmit`, same CLI surface. **Flag:** Microsoft's own release notes say the *programmatic* compiler API (what IDE/tool integrations, not the CLI, use) won't be stable until 7.1, and `typescript-eslint@8.67.0`'s peer range is hard-capped at `typescript >=4.8.4 <6.1.0` (confirmed via registry) — it does not accept TS 7 at all yet. This is why §7 recommends Biome over ESLint (Biome has no TypeScript-compiler-API dependency, so it never blocks on this gap). If you want ESLint's plugin ecosystem instead, pin `typescript@6.0.3` (latest 6.x, confirmed via registry) rather than fighting the peer range. |
| **@vitejs/plugin-react** | `6.0.5` | React Fast Refresh via Babel | The official Vite React template default (`npm create vite@latest -- --template react-ts`). Peer-requires `vite ^8.0.0` — satisfied. Recommended over the SWC variant for a 3-page app: Babel is the well-trodden path with the broadest plugin compatibility, and this milestone has no HMR-latency problem the SWC variant exists to solve. |
| **Node.js** | `24` (Active LTS) | Toolchain runtime, Docker builder stage | Per endoflife.date / Node release schedule (WebSearch, 2026-08-17): Node 22 is now Maintenance LTS, **Node 24 is Active LTS**, Node 26 is Current (enters LTS Oct 2026). `node:24-slim` exists on Docker Hub (confirmed via Docker Hub API). Vite 8, `@vitejs/plugin-react@6`, and Vitest 4 all declare `engines.node` ranges (`^20.19.0 \|\| >=22.12.0` / `^20.0.0 \|\| ^22.0.0 \|\| >=24.0.0`) that Node 24 satisfies. |

**Peer-dependency constraints that matter here (all confirmed via `registry.npmjs.org`):**
- `@vitejs/plugin-react@6.0.5` → `vite: ^8.0.0` — locks the plugin/Vite pairing above.
- `vitest@4.1.10` → `vite: ^6.0.0 || ^7.0.0 || ^8.0.0` — Vite 8 is inside range.
- `@testing-library/react@16.3.2` → `react: ^18.0.0 || ^19.0.0` — React 19 is inside range.
- `@tanstack/react-query@5.101.4` → `react: ^18 || ^19` — inside range (not recommended here, see §3).
- `react-router@8.3.0` → `react: >=19.2.7`, `node: >=22.22.0` — this is unusually tight (a router requiring a *specific recent patch* of React); one more reason it's not worth pulling in for this milestone (see §2).
- `@types/react@19.2.18` and `@types/react-dom@19.2.4` track the React 19 line (confirmed via registry).

---

## 2. Routing — do NOT add a client router

**Recommendation: no `react-router` / `@tanstack/react-router`. Plain `<a href>` between pages.**

Argument for adding one: React Router is the default reflex for "a React app has multiple pages," and each
of `/runs`, `/runs/{id}`, `/eval` could in principle be "routes" in one SPA shell.

Argument against, and why it wins here:
- **FastAPI already owns the URL space.** `/runs`, `/runs/{id}`, `/eval` are real server routes rendered by
  `app.include_router(...)` in `app/main.py` — a client router would create a second, competing source of
  truth for the same three paths.
- **The milestone's own falsified decision #3 locks "vertical slices, each independently deployable."** A
  single client router spanning all three pages implies one SPA shell mounted once, which is the *horizontal*
  shape the scope review explicitly rejected (an unconsumed JSON API / half-migrated dashboard risk). Three
  separate Vite entry points, each mounted into its own page, has no need for client-side route matching
  *between* those entries — that's what full-page navigation via `<a href="/runs/123">` already does, and it
  is what a browser link has always done.
- **Mutations are native `<form method="post">` + 303** (falsified decision #1). A 303 redirect is a real
  HTTP navigation the browser performs — a client router doesn't participate in it and adds nothing.
- **`react-router@8.3.0` requires `react >=19.2.7` and `node >=22.22.0`** — a tight coupling to buy a
  capability (nested client routes, loaders, in-SPA navigation) this milestone does not use.

If a *future* milestone unifies all three pages into one true SPA shell with in-page navigation, revisit
then — that is a different, larger scope than three independently-shippable slices.

---

## 3. Data fetching — plain `fetch` in a hook, not TanStack Query

**Recommendation: no `@tanstack/react-query`. A small custom hook wrapping `fetch` + `setInterval`.**

The concrete live-behavior requirement is one thing: poll `GET /runs/{id}/status` every 2 seconds and update
a badge — the exact same shape as the vanilla-JS poller already shipped in `run_detail.html` /
`runs_list.html` (v4.1, "Frontend progressive enhancement" — see PROJECT.md), just re-hosted in React.

- **TanStack Query (`@tanstack/react-query@5.101.4`, peer `react: ^18 || ^19` — satisfied)** is the right
  tool when you need: cross-component cache sharing, request de-duplication across many consumers,
  background refetch-on-focus, optimistic mutation state, retry/backoff policy tuning. None of that applies
  to a single poller owned by a single component with no sibling that needs the same data. Its cost here is
  a `QueryClientProvider` wrapper, a new mental model (`queryKey` cache semantics) for a one-off interval,
  and bytes in the bundle that buy nothing this milestone uses.
- **Plain `fetch` in a `usePollingStatus(runId)` hook** (an effect that `fetch`es, updates state, and
  `setTimeout`/`setInterval`s itself, with cleanup on unmount) is a ~20-line direct port of the existing
  vanilla-JS poller's *logic*, just moved behind a React hook. It's the honest choice because it does exactly
  what the milestone needs and nothing else — matching this repo's stated preference for the smaller,
  well-trodden, dependency-light tool (reportlab over WeasyPrint, psycopg over an ORM, one client class for
  two LLM providers).
- Cost of the plain-fetch route: if a later slice needs the *same* run's data in two places at once (e.g. a
  header badge AND a status table both polling `/runs/{id}/status`), you'll hand-roll de-duplication that
  TanStack Query gives for free. That is a real, deferred cost — revisit if slice 2 or 3 actually needs it;
  don't pre-pay it now.

---

## 4. Test tooling

| Tool | Version | Notes |
|---|---|---|
| **Vitest** | `4.1.10` | Peer `vite: ^6.0.0 \|\| ^7.0.0 \|\| ^8.0.0` (satisfied by Vite 8), `@types/node: ^20.0.0 \|\| ^22.0.0 \|\| >=24.0.0` (satisfied by Node 24 + `@types/node@26.2.0`, itself inside `>=24.0.0`). Same tool family as the build (both Vite-native) — no second config format to maintain, mirroring the "one tool, no config debate" ruff pattern already in `pyproject.toml`. |
| **@testing-library/react** | `16.3.2` | Peer `react: ^18.0.0 \|\| ^19.0.0`, `@testing-library/dom: ^10.0.0` — install `@testing-library/dom` alongside it. |
| **@testing-library/jest-dom** | `7.0.1` | Custom matchers (`toBeInTheDocument()`, etc.) for Vitest's `expect`. |
| **jsdom** | `30.0.1`, **recommended over `happy-dom` (20.11.2)** | jsdom is the long-standing, spec-closer DOM emulation and is Testing Library's own default recommendation; `happy-dom` is faster but has a history of edge-case gaps (`getComputedStyle`, canvas, some event timing). For 3 pages, the marginal speed of `happy-dom` is not worth trading away fidelity in a codebase that otherwise treats test correctness as non-negotiable (mypy `--strict`, `pytest -q` full-suite discipline). Set via Vitest config `test.environment: "jsdom"`. |
| **Playwright** (`@playwright/test`, `1.62.1`) | **Not recommended for this milestone.** | The behavior most worth proving end-to-end — the native `<form method="post">` → 303 redirect chain, and the `onsubmit="return confirm(...)"` Reject guard — is server-side behavior FastAPI already owns and the existing `pytest` + `TestClient` suite already exercises (that's exactly what falsified decision #1 protects). What Playwright would add is proof that the *built* SPA bundle mounts correctly in a real browser post-Docker-build — legitimate, but it's a second testing paradigm (browser automation, a browser download/cache step in CI, non-trivial minutes) for a milestone whose explicit scope is three small conversions, not an E2E buildout. **Recommendation: skip Playwright for phases 22-24; revisit if a real cross-boundary regression appears** (e.g., something breaking the `/ops` no-script guarantee — see `tests/test_ops_route.py:364` — as a side effect of the React bundle). Vitest + RTL component tests plus the existing Python integration suite is the honest coverage line for this scope. |

---

## 5. Type-safety across the boundary (TS types ↔ Pydantic response DTOs)

**Recommendation: `openapi-typescript@7.13.0` (types-only, devDependency, no runtime cost).**

Three options, evaluated against this specific gotcha: falsified decision #2 (`docs`) found that
`_safe_run_for_browser` (`app/routes/runs.py:224`) is a **denylist**, not an allowlist — meaning any column
later added to `RUN_COLS` is exposed by default unless someone remembers to add it to the denylist. Hand-
written TS interfaces make this *worse*: a second, manually-maintained shape that has to be remembered every
time the Python side changes, with silent drift as the failure mode (a mistyped field or new column present
in the JSON just doesn't type-error).

| Option | What it is | Verdict for this milestone |
|---|---|---|
| **Hand-written interfaces** | Manually type each response shape in TS | Reject — this is the exact repetition the user's own "DRY is critical, flag repetition aggressively" preference and the denylist gotcha above both argue against; two independently-maintained sources of truth for the same wire shape. |
| **`openapi-typescript` `7.13.0`** | Generates *types only* from FastAPI's built-in `/openapi.json` | **Recommended.** FastAPI auto-serves `/openapi.json` from the route's `response_model`; run `npx openapi-typescript http://localhost:$PORT/openapi.json -o frontend/src/api-types.ts` as an `npm run gen:types` script. Zero runtime dependency (pure devDependency, emits `.ts` type declarations, no client code), so it doesn't collide with the native-form-POST decision (it generates nothing that talks over the wire — it only describes shapes). Wire a CI staleness check the same way `eval.yml` already regenerates-and-diffs `eval/chart.svg`: regenerate, then `git diff --exit-code frontend/src/api-types.ts`. |
| **`orval` `8.24.0`** | Generates types **and** a full HTTP client (fetch/axios, optionally React-Query hooks) | Reject for this milestone — its main value-add is generated *mutation* functions/hooks, which directly conflicts with falsified decision #1 (mutations stay native `<form>` POSTs, never `fetch`). Using it only for its GET-side types means paying for a heavier, more opinionated tool to get the subset `openapi-typescript` already provides directly. |

---

## 6. Node builder stage in the existing Dockerfile

The existing `Dockerfile` (read at repo root, 2026-08-17) is a 2-stage `builder` → `runtime` build. The
frontend becomes a **third, independent stage** that the `runtime` stage copies *built output* from — it
never touches the Python `builder` stage's `WORKDIR /app`, and Node itself never reaches the runtime image.

```dockerfile
# ── Frontend builder stage ──────────────────────────────────────────────────
FROM node:24-slim AS frontend

# Own WORKDIR — independent of the Python builder's /app; no collision.
WORKDIR /frontend

# Layer 1: install deps only (cached until package.json/package-lock.json change) —
# same two-layer cache pattern already used for `uv sync --no-install-project`.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Layer 2: copy source, build. Vite's multi-page (multi-entry) config emits one
# bundle per slice as each phase (22/23/24) adds an entry — no new toolchain per slice.
COPY frontend/ .
RUN npm run build   # outputs to frontend/dist/ by Vite convention

# ── Runtime stage (unchanged Python builder → runtime flow, plus one more COPY) ──
FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=builder /app /app
# Built assets land under the *existing* /static mount (app.mount("/static", ...) in
# app/main.py) rather than a second app.mount() call — Jinja's CSS/JS and React's
# built bundle share one StaticFiles root.
COPY --from=frontend /frontend/dist /app/app/static/dist
ENV PATH="/app/.venv/bin:$PATH"
CMD ["/bin/sh", "-c", ".venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
```

**Why this preserves the documented constraints:**
- `WORKDIR /app` is untouched in both the Python `builder` and `runtime` stages — the frontend stage has its
  own `WORKDIR /frontend` that exists only during build, in a stage that is never the final image.
- **Runtime image size:** Node itself, `node_modules`, and the frontend source never reach the `runtime`
  stage — only the built `dist/` output (a handful of hashed `.js`/`.css` files, typically tens to a few
  hundred KB for 3 small pages) is copied in, via the same `COPY --from=<stage>` pattern already used for the
  Python venv. This is the same reasoning the Dockerfile's own comments already apply to the `uv` binary
  ("not copied — a build tool only"): Node is a build tool here too.
  Render cold-start time (image pull + `uvicorn` boot) is governed by final image size, which grows by
  kilobytes, not by the ~150-250MB `node:24-slim` layer, which never leaves the builder stage.
- **Build-time cost:** `npm ci` + `vite build` adds real wall-clock time to `docker build` (roughly 20-60s
  for a project this size, dominated by `npm ci` unless the dependency layer cache hits), but this runs at
  build/deploy time on Render/CI, not at request time — it does not affect cold-start latency for an already-
  built image.
- **`app/static` is already the mount root** (`app.mount("/static", StaticFiles(directory="app/static"), name="static")` in `app/main.py`, confirmed by reading the file) — landing built assets at `app/static/dist/` needs zero new FastAPI route/mount code, only a new relative asset path in whatever Jinja shell page (or router-added page) mounts each React entry.

---

## 7. What NOT to add

| Avoid | Why (specific to this project) | Instead |
|---|---|---|
| **Tailwind CSS** | `tests/test_design_tokens.py` parses the live `app/static/style.css` `:root` block and asserts WCAG AA contrast ratios computed from the actual hex values, plus a "Token-First Rule" (each hex appears exactly once, only in `:root`). Tailwind's utility-class model puts color decisions in class names at every call site, not in one token file — it doesn't add an equivalent contrast guard, and it fragments the exact single-source-of-truth the test suite already enforces. It would also add a JIT build step duplicating what one hand-written CSS file already does correctly for this specific design. | React components import nothing new — they apply the **same** `className`s (`.btn`, `.btn-accent`, `.badge`, the `state-pending-*` family, etc.) already defined in `app/static/style.css` and already covered by `test_design_tokens.py`. That test file continues to guard the token layer unchanged. |
| **CSS-in-JS (styled-components, Emotion, vanilla-extract)** | Same reasoning as Tailwind: the token system of record is one CSS file with tests asserting real computed contrast ratios against the *live* file. A CSS-in-JS library either duplicates those tokens in JS (drift risk) or requires re-deriving the contrast guard in a different language, for zero benefit — there's no dynamic/computed styling need here. | Same as above — plain `className` against the existing stylesheet. |
| **Component library (MUI, shadcn/ui, Chakra)** | MUI ships its own theming/CSS-in-JS engine that would fight the hand-tuned token system head-on. shadcn/ui is a copy-paste-over-Radix pattern that assumes Tailwind, already ruled out above. The existing `.btn`/`.badge`/decision-banner CSS classes, hardened over multiple design-review rounds (per `DESIGN.md`'s changelog references), **are** this project's component library. | Hand-rolled React components (`<Button>`, `<Badge>`, `<DecisionBanner>`, etc.) that render the existing class names — a thin typed wrapper over CSS that already exists and is already tested. |
| **Global state (Redux, Zustand, Jotai, MobX)** | Three independently-shippable slices with no shared client-side state: no auth store (single operator, no login flow described in scope), no cross-page cache (routing is native `<a href>` per §2), and every mutation triggers a full page reload via 303 (falsified decision #1) — which already resets any client state a store would have held. There is no cross-component state-sharing problem in this milestone for a store to solve. | `useState`/`useReducer` local to each page's root component; the 2s poller's state lives in the hook from §3. |
| **SSR / Next.js** | The server-rendering layer for this app already exists and is FastAPI + Jinja2 (kept for `/` and `/ops` by design). Next.js requires its own Node server process — incompatible with the single-Docker-image, single-process Render free deployment this app is built around (a second service would burn a second slice of the 750 free instance-hours, or force a bespoke custom-server integration fighting FastAPI's own routing). The locked scope is client-side React *mounted into* specific FastAPI-served pages, not replacing FastAPI as the server. | Vite's plain client build (`npm run build` → static `dist/` assets), served by FastAPI's existing `StaticFiles` mount, exactly as built in §6. |
| **A monorepo tool (Turborepo, Nx, pnpm workspaces)** | One `frontend/` directory, one `package.json`, Vite's native multi-entry (multi-page) config covers all 3 slices as they land across phases 22-24 — there is only ever one JS package in this repo. This mirrors the project's own stated "least moving parts" pattern (`uv` not Poetry, direct `psycopg` not an ORM, one OpenAI-compatible client class for two providers instead of two SDKs). | Plain `npm`/`vite` in a single `frontend/` folder; no workspace config. |
| **ESLint + Prettier** | `typescript-eslint@8.67.0`'s peer range is `typescript: >=4.8.4 <6.1.0` (confirmed via `registry.npmjs.org`) — it **cannot** lint against TypeScript 7.0.2 today. Recommending ESLint here means either pinning TypeScript back to `6.0.3` (fighting the version this milestone should actually ship) or running ESLint's TS parsing unsupported. | **`@biomejs/biome@2.5.8`** — lint + format in one tool/one config, with no dependency on the TypeScript compiler API at all (it parses TS syntax directly), so it never blocks on this gap. This is the direct frontend analog of the existing `ruff` choice: `pyproject.toml`'s own comment on `[tool.ruff]` says "One tool, fast, no config debate" — Biome is that same tradeoff for TS/JS. **Named cost:** Biome's React-specific rule coverage (e.g. `exhaustive-deps`-equivalent hook linting) is comparatively newer/thinner than the mature `eslint-plugin-react-hooks`; acceptable for 3 pages, worth re-checking if the frontend grows substantially. |
| **Storybook** | No design system to catalog in isolation — the handful of components this milestone builds are each consumed directly by one of the 3 concrete pages, not developed/shared as a reusable library across many consumers. Its cost (a second dev server, its own build config, visual-review workflow) doesn't pay for itself at this scope. | Vitest + RTL component tests (§4) cover the same "does this component render correctly" need without a second toolchain. |

---

## Installation

```bash
# In a new frontend/ directory at the repo root
npm create vite@latest frontend -- --template react-ts

cd frontend
npm install                          # react@19.2.8, react-dom@19.2.8, vite@8.2.1 (template defaults)
npm install -D typescript@7.0.2 @vitejs/plugin-react@6.0.5 \
               @types/react@19.2.18 @types/react-dom@19.2.4 @types/node@26.2.0

# Test tooling
npm install -D vitest@4.1.10 @testing-library/react@16.3.2 \
               @testing-library/jest-dom@7.0.1 @testing-library/dom jsdom@30.0.1

# Lint/format (Biome, not ESLint+Prettier — see §7)
npm install -D @biomejs/biome@2.5.8

# Type generation from FastAPI's OpenAPI schema (devDependency only, no runtime client)
npm install -D openapi-typescript@7.13.0
```

## Alternatives Considered

| Recommended | Alternative | When the alternative would win |
|---|---|---|
| No client router | `react-router@8.3.0` | If a future milestone unifies all 3 pages into one true single-page shell with in-app navigation instead of full reloads — a materially larger scope than this milestone's 3 independent slices. |
| Plain `fetch` hook | `@tanstack/react-query@5.101.4` | If a later slice needs the same polled resource shared/de-duplicated across multiple components, or needs retry/backoff tuning beyond a fixed 2s interval. |
| `openapi-typescript@7.13.0` | `orval@8.24.0` | If a future milestone adds a real fetch-based mutation surface (contradicting falsified decision #1) and wants generated request functions/hooks alongside types. |
| `@vitejs/plugin-react@6.0.5` (Babel) | `@vitejs/plugin-react-swc@4.3.3` | If HMR latency becomes a real friction point as the frontend grows well past 3 pages — its peer range (`vite: ^4..^8`) is more permissive but buys nothing at this scale. |
| Biome `2.5.8` | ESLint + `typescript-eslint` | Only if pinning `typescript@6.0.3` instead of `7.0.2` — trades the 8-12x faster Go compiler for ESLint's more mature React-hooks lint rules. Not recommended for this milestone. |
| jsdom `30.0.1` | happy-dom `20.11.2` | If Vitest run time becomes a measured bottleneck — not a concern at 3 pages. |
| No Playwright | `@playwright/test@1.62.1` | If a real cross-boundary regression appears post-ship (e.g., the React bundle breaking `/ops`'s script-free guarantee) — add a narrow smoke suite then, not preemptively. |

## Version Compatibility

| Package A | Compatible With | Notes |
|---|---|---|
| `vite@8.2.1` | `node ^20.19.0 \|\| >=22.12.0` | Node 24 (Active LTS) satisfies this; confirmed via `registry.npmjs.org/vite`. |
| `@vitejs/plugin-react@6.0.5` | `vite ^8.0.0` | Locks the plugin to Vite 8.x specifically — confirmed peer range. |
| `vitest@4.1.10` | `vite ^6.0.0 \|\| ^7.0.0 \|\| ^8.0.0` | Vite 8 is inside range. |
| `@testing-library/react@16.3.2` | `react ^18.0.0 \|\| ^19.0.0` | React 19.2.8 is inside range. |
| `typescript-eslint@8.67.0` | `typescript >=4.8.4 <6.1.0` | **Does not accept TypeScript 7.x** — the load-bearing reason for choosing Biome over ESLint in this milestone. |
| `react-router@8.3.0` | `react >=19.2.7`, `node >=22.22.0` | Tight coupling, noted for completeness — not adopted (§2). |
| `node:24-slim` (Docker) | Docker Hub `library/node` | Tag confirmed present via Docker Hub API, 2026-08-17. |

## Sources

- `registry.npmjs.org/<package>` (dist-tags.latest, engines, peerDependencies) for: `vite`, `react`,
  `react-dom`, `typescript`, `@vitejs/plugin-react`, `@vitejs/plugin-react-swc`, `react-router`,
  `@tanstack/react-router`, `@tanstack/react-query`, `vitest`, `@testing-library/react`,
  `@testing-library/jest-dom`, `jsdom`, `happy-dom`, `@playwright/test`, `openapi-typescript`, `orval`,
  `eslint`, `prettier`, `@biomejs/biome`, `typescript-eslint`, `@types/react`, `@types/react-dom`,
  `@types/node`. Fetched live 2026-08-17. **HIGH.**
- Docker Hub API (`hub.docker.com/v2/repositories/library/node/tags`) — confirmed `24-slim` tag exists.
  **HIGH.**
- WebSearch, Node.js release schedule (endoflife.date-sourced summary) — Node 22 Maintenance LTS / Node 24
  Active LTS / Node 26 Current as of August 2026. **MEDIUM** (search-summary, not a primary registry read,
  but internally consistent with the `engines` ranges pulled directly from npm).
- WebSearch, TypeScript 7.0 GA coverage (Microsoft DevBlogs "Announcing TypeScript 7.0", InfoQ, Visual
  Studio Magazine) — GA date 2026-07-08, Go-native compiler, programmatic API stability deferred to 7.1.
  **MEDIUM-HIGH** (multiple independent outlets agree; devblogs.microsoft.com is the primary source cited
  by all of them, not independently re-fetched here).
- WebSearch, React Router v8 release notes (remix.run/blog/react-router-v8, reactrouter.com/changelog) —
  Node/React minimum version bump, ESM-only. **MEDIUM** (not adopted; cited for the peer-range explanation
  only).
- Direct file reads: `Dockerfile`, `pyproject.toml`, `.github/workflows/ci.yml`, `app/static/style.css`,
  `app/main.py`, `tests/test_design_tokens.py`, `.planning/PROJECT.md` (v5 milestone section) — repo root,
  2026-08-17. **HIGH** (primary source, this repo).

**Not independently verified (flag for the roadmapper):** the exact Vite multi-page `rollupOptions.input`
config for 3 incrementally-added entries, and the exact relative asset path a Jinja shell page (or the new
router-added page) will reference once `app/static/dist/` exists — both are implementation details for
Phase 22's planner to work out against a real `vite.config.ts`, not stack-selection questions.

---
*Stack research for: v5 React/TypeScript Operator Console milestone*
*Researched: 2026-08-17*

---

## DECISION OVERRIDE (human, 2026-08-17) — read this before installing anything

The recommendations above are preserved as written, including their reasoning. **One of them was
overridden by the project owner during milestone definition. The override wins.**

### Pin `typescript@6.0.3` + ESLint, NOT `typescript@7.0.2` + Biome

**Decision:** `typescript@6.0.3` (last stable 6.x, published 2026-04-16) with
ESLint + `typescript-eslint@8.67.0` + `eslint-plugin-react-hooks`. Do NOT install
`typescript@7.0.2`, and do NOT install `@biomejs/biome` for this milestone.

**Why the override, stated against this document's own argument.** §7 recommends Biome partly because
it escapes `typescript-eslint`'s `typescript >=4.8.4 <6.1.0` peer cap, which is true. But it also
concedes, in the same row, that Biome's React-hooks rule coverage is thinner than
`eslint-plugin-react-hooks`. That concession lands directly on this milestone's single
highest-risk converted behavior:

The `/runs/{id}` poller's correctness is an **effect-dependency problem**. Its reload trigger is
`data.status !== INITIAL_STATUS || data.queue_label !== INITIAL_QUEUE_LABEL`
(`app/templates/run_detail.html:76`), and the in-source comment at `:39-44` records that an earlier,
narrower version of this check *missed the `extracting → awaiting_reply` transition, so the
clarification banner never appeared without a manual refresh*. A React port with a stale dependency
array reintroduces exactly that class of bug, and `exhaustive-deps` is the rule that catches it.

Trading a real guard against the riskiest behavior for an 8-12x faster `tsc` is a bad trade at
three pages — compile time is not a constraint at this scale. TS 7's programmatic Compiler API also
remains unstable until 7.1, which adds tooling risk for no benefit here.

**Accepted costs, named honestly:** two tools instead of one (a genuine departure from the `ruff`
"one tool, no config debate" precedent this document correctly cites); not the newest TypeScript;
and an ESLint + Prettier config surface to maintain.

**What does NOT change:** every other recommendation in this document stands — Vite `8.2.1`,
React `19.2.8`, `@vitejs/plugin-react@6.0.5`, Node 24 builder stage, Vitest `4.1.10` + React Testing
Library `16.3.2` + jsdom, `openapi-typescript@7.13.0` for types-only generation, no client router, no
TanStack Query, no Tailwind/CSS-in-JS/component library/Redux/Next.js/monorepo tool/Storybook.
Verify `@vitejs/plugin-react@6.0.5` and Vitest `4.1.10` peer ranges accept TypeScript 6.0.3 at
install time — the version matrix above was validated against 7.0.2.

**Regardless of linter:** the poller's reload trigger must be proven *behaviorally* — a test for a
`status` change AND a separate test for a `queue_label`-only change — rather than trusted to lint.
Lint is the cheap guard; the behavioral test is the real one.

### Two further decisions locked at the same time (both affect this stack)

- **Initial page data is embedded server-side** in a `<script type="application/json" id="__INITIAL_DATA__">`
  block and hydrated from, NOT fetched on mount. Driver: Render free cold-starts in ~1 min and
  fetch-on-mount stacks a second round trip, putting a spinner over the operator approval gate.
- **Mutation forms stay server-rendered.** `base.html` remains a server-rendered shell owning every
  `<form method="post">` and all five `onsubmit="return confirm(...)"` guards; React renders only the
  data islands inside it. This preserves the existing no-JavaScript property and keeps the five
  confirm guards out of JSX, where returning `false` from `onSubmit` does not cancel submission.
