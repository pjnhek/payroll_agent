# Project Research Summary

**Project:** Payroll Agent — v5 "React/TypeScript Operator Console" milestone
**Domain:** Presentation-layer conversion of 3 of 5 pages in a shipped, single-container FastAPI + Jinja2 money-moving operator dashboard to React + TypeScript, via 3 independently-deployable vertical slices (Phases 22-24)
**Researched:** 2026-08-17
**Confidence:** HIGH — all four research passes are grounded in live `file:line` reads against this repo, not memory.

## Executive Summary

This is not really a "build a React app" milestone — it is a leak-prevention and behavior-preservation exercise wearing a frontend-framework costume. The four research passes converge, independently, on the same architecture: a multi-page app where FastAPI keeps owning routing, mutations, and the 303-redirect state machine, and React is mounted per-page as an island that only ever reads server-embedded JSON and writes through native `<form method="post">`. Every alternative shape a React developer would reach for by default — a client router, `fetch`-based mutations, a `GET /api/runs` endpoint, TanStack Query, a `dangerouslySetInnerHTML` shortcut — independently collapses the 303-redirect-encoded operator-feedback channel, the allowlist DTO boundary, or the route-shadowing guarantee that keeps `/webhook/inbound`, `/health/*`, and `/internal/pump` reachable.

The recommended approach: Vite + React 19 + TypeScript builds three small entry bundles served from the existing `/static` mount via a new `render_react_page()` + Jinja shell; a new `app/schemas/` package makes the DTO boundary an allowlist-by-construction rather than the current denylist; DTO/TypeScript drift is closed with generated types gated in CI. Toolchain choices trace to the same "least moving parts" pattern used everywhere else in this project.

The key risks are not "can React render this UI" — they are a test suite where roughly a third of its markup assertions are absence checks that go silently vacuous once guarded content moves into a JS bundle (about 20 of them guard PII/XSS/path-traversal/anti-BUG-1 safety); `dist/` already being gitignored with `Dockerfile:38`'s `COPY . .`, which ships a blank console to Render while everything else stays green; and Slice 2 carrying roughly 80% of the real migration cost, meaning the three phases must not be sized as equal thirds.

## Key Findings

### Recommended Stack

Vite 8.2.1 + React 19.2.8 + TypeScript 7.0.2, built as a third Docker stage (`node:24-slim`) that a Python runtime stage copies only `dist/` output from. No client router. No TanStack Query — a ~20-line `usePoller` hook replaces it. Type safety across the Python/TS boundary via `openapi-typescript` (types-only). Biome, not ESLint+Prettier — `typescript-eslint@8.67.0`'s peer range cannot accept TypeScript 7 yet; named cost: Biome's React-hooks rule coverage is thinner than `eslint-plugin-react-hooks`.

**Core technologies:** Vite 8.2.1 (multi-entry build); React 19.2.8; TypeScript 7.0.2 (Go-native compiler); Biome 2.5.8 (lint+format, one tool, no config debate — direct analogue of `ruff`); Vitest 4.1.10 + @testing-library/react 16.3.2 + jsdom 30.0.1; openapi-typescript 7.13.0 (CI-gated for staleness like `eval/chart.svg`). Explicitly rejected: Playwright, Tailwind/CSS-in-JS, any component library, any global-state library, Next.js/SSR, any monorepo tool.

### Expected Features (behavioral parity contract)

**Must have (table stakes):** all enumerated per-page behaviors verbatim, including exact DOM ordering and fallback-priority chains threaded from the server. The `/runs/{id}` decision-banner logic is **6 real mutually-exclusive `elif` branches + 1 implicit no-banner state + 1 independent hours-changed overlay that is NOT an `elif`** — not "8 branches." Both delivery-review variants plus a degraded "unavailable" state, with the confirmation variant's Authorize/Reject mutual exclusivity preserved (an anti-BUG-1 pin currently proven only by a template comment, no direct test — flag for Slice 2). Native `<form>` + 303 for all 15 POST routes. Progressive enhancement. PII-safe failure vocabulary, record-only labeling, no silent body truncation.

**Should have (differentiators):** the poller as one typed hook; the decision-banner matrix as a TS discriminated union with exhaustiveness checking; delivery-review eligibility booleans consumed as typed props, never re-derived; shared demo send-test form component.

**Defer / refuse (anti-features):** client-side routing between the pages; optimistic UI on any money-moving mutation; cross-navigation client cache of run state; a spinner replacing server-rendered first paint on a cold-started free instance; re-deriving server-computed booleans/vocabularies client-side; generic toast-on-fetch-error on the pollers.

### Architecture Approach

Multi-page app with React-rendered islands, not an SPA. `/` and `/ops` stay pure Jinja (`/ops` provably script-free). `/runs`, `/runs/{id}`, `/eval` become a thin Jinja shell with `<div id="root">`, an XSS-escaped JSON data island, and Vite manifest-driven boot tags. No client router, no catch-all — route-shadowing protection is structural (the only `Mount` remains `/static`).

**Major components:**
1. `app/schemas/` (new, sibling to `app/models/`) — `RowProjection.from_row` allowlist DTOs; any unclassified repo-row key raises `UnclassifiedColumnError`, replacing today's denylist (`_safe_run_for_browser`, `app/routes/runs.py:220`, whose denylist at `:232-244` still leaves `business_id`, `source_email_id`, `reply_epoch`, `alias_candidates` unguarded).
2. `app/routes/templating.py` (grown) — Vite-manifest loader + `render_react_page()`.
3. `frontend/` (new, sibling to `app/`) — per-page Vite entries, one `MutationForm`/`ConfirmForm` pair as the only place a `<form>` may be emitted, one `usePoller` hook as the only place `fetch` may be called (both lint-enforced).
4. A new fourth blocking CI job (`frontend`) — build the bundle in Docker, don't commit it (unlike `eval/chart.svg`, a minified bundle isn't evidence a reviewer reads).
5. The 15 mutation routes — byte-identical.

## Critical Pitfalls

1. **`dist/` gitignored + `Dockerfile:38` `COPY . .`** — blank-console deploy trap, green everywhere except production. Fix: build bundle in a Docker Node stage, placed after the existing builder COPY so it isn't clobbered, plus an existence-check test.
2. **Vacuous absence-assertion trap** — ~44 of 131 markup assertions across 6 test files are `not in response.text`, satisfied trivially by an empty React shell; ~20 guard PII/XSS/path-traversal/anti-BUG-1 safety. Fix: mutation-gate every migrated absence assertion, convert to positive exact-shape assertions.
3. **Catch-all route shadowing** — would 200-with-HTML `/webhook/inbound` (lost payroll email, no provider retry) and `/internal/pump` (queue never drains, `pump.yml` false-green). The MPA/no-catch-all architecture makes this structurally absent.
4. **`fetch` for mutations** silently deletes the redirect-encoded `?resolution_superseded=1` flag, redirect-to-new-run-id, the 5 untested `confirm()` guards, and the `?notice=` channel. Fix is architectural (keep forms native) plus lint bans.
5. **Design-token/accessibility guards go blind, not red, on `.tsx`** — hardcoded suffix allowlists and template globs silently narrow scope as pages convert; one test reads `runs_list.html` at module-import time and errors the whole file at collection if deleted first.

## Implications for Roadmap

### Decisions the research converged on

Four independent passes reached the same structural answer from different angles:
- **MPA with React-rendered islands over an SPA** — Architecture argues it structurally; Features independently lists client routing as an anti-feature; Pitfalls shows this one decision collapses roughly five separate named pitfalls; Stack reaches the same place via dependency hygiene (`react-router`'s tight peer coupling buys nothing here).
- **No client router.**
- **No TanStack Query / no fetch beyond one poller hook.**
- **Reuse `app/static/style.css` class names; no Tailwind, no CSS-in-JS, no re-declared design tokens** — Stack names the live WCAG-contrast-test mechanism; Pitfalls independently derives the same conclusion from the test-guard-scope angle.
- **Server-embedded initial data, not fetch-on-mount** — Architecture and Pitfalls converge independently on avoiding a second round trip stacked behind Render free's ~1-minute cold start.

### Decisions the research deliberately did NOT make

(a) **Initial page data: embedded vs. fetched on mount.** Strongly recommended (embed) but not locked the way native-form-POST is — no document names a fallback path or regression test for the read side specifically. Roadmapper should decide whether embedding-only is a phase-exit criterion for all three slices.

(b) **Whether operator mutation controls stay server-rendered enough to work with JS off, or JS becomes required for the three converted pages, with `/ops` as the sole guaranteed no-JS surface.** The current app is fully JS-optional. No research document commits to preserving this for the converted pages vs. accepting JS as assumed. This changes what Slice 1's CI needs to gate and should be decided before Slice 1's DTO/shell design is finalized.

(c) **TypeScript 7.0.2 + Biome vs. TypeScript 6.0.3 + ESLint.** Stack recommends the newer pair for compiler speed and concedes Biome's React-hooks coverage is thinner. The specific intersection that makes this non-cosmetic: the `/runs/{id}` poller's correctness IS an effect-dependency problem — the documented, already-fixed regression (missing the `extracting → awaiting_reply` transition) is exactly the class of bug `exhaustive-deps` catches. Whichever slice ports the poller must prove the reload trigger behaviorally (both halves of the `status`/`queue_label` OR condition) rather than relying on lint, if Biome is kept.

### Highest-damage traps, ranked

1. **`dist/` gitignored blank-console deploy trap** (Slice 1) — must be resolved in Slice 1's Docker/CI work, not discovered on first deploy.
2. **The absence-assertion vacuous-parity surface** (created in Slice 1, most damaging in Slice 2) — the tests that survive a bad port skew toward the security proofs: PII scrubbing, XSS, path traversal, the delivery-review Reject gate.
3. **The catch-all route-shadowing failure mode** (structural, must never be introduced in any slice) — `/health/live` and `/internal/pump` returning 200+HTML makes Render mark a broken deploy healthy AND makes `pump.yml`'s `curl -f` go green while the durable queue is never drained.
4. **The untested `confirm()` guards combined with React `onSubmit` returning `false` not cancelling submission** (Slice 2) — zero test coverage exists today; the React footgun (must call `preventDefault()`, not `return false`) makes Reject a one-click irreversible action if missed.
5. **The wholesale-serialization leak** (pattern/guard in Slice 1, largest exposure in Slice 2) — reusing the existing denylist directly in a JSON API exposes `business_id`, `source_email_id`, `reply_epoch`, `alias_candidates`, `extracted_data`, `reconciliation` on an app with no auth.

### Explicit slice-sizing statement

**The three phases must NOT be sized equally.** Multiple independent measures converge: Slice 2 (`/runs/{id}`) owns roughly **80% of the real migration cost** — 44 of 60 measured GET calls in the affected test files target `/runs/{id}`, 14 of 18 server-rendered forms and all 5 `confirm()` guards live in `run_detail.html`, and Slice 2's behavior-count tally is ~30 table-stakes items (2 HIGH-complexity) versus Slice 1's 14 (1 HIGH) and Slice 3's 10 (0 HIGH). Slice 1 additionally carries one-time toolchain, Docker, and CI cost orthogonal to `/runs`'s own light page complexity — Slice 1's true cost is dominated by infrastructure risk, not UI risk. Treat Slice 1 as medium effort/high setup risk, Slice 2 as the large majority of the milestone's actual work, Slice 3 as genuinely light.

### Pull forward into Slice 1

1. `frontend/` workspace + strict TS + Biome lint rules + Vitest — unavoidably first.
2. `app/schemas/` + `RowProjection.from_row` + `UnclassifiedColumnError` — deferring means Slice 2 must reopen `/runs` to retrofit the allowlist pattern.
3. The three classification tests (mechanism, `RUN_COLS`, AST-read `load_all_runs`) — the seam's value is preventing a leak from the first shipped page.
4. Manifest loader + `render_react_page()` + shell template — deferring creates drifting duplicate boot logic.
5. `json_script()` + its `</script>`-injection XSS test — deferring ships the injection surface unguarded on page one.
6. `MutationForm` + `ConfirmForm` + the Vitest cancel/allow (`preventDefault`) tests — building the guarded-form abstraction for the first time in Slice 2, under 10 forms and 5 confirm sites at once, is precisely where the regression lands unnoticed.
7. DTO→TS generation with CI staleness gates — deferring lets hand-written interfaces become the source of truth by inertia.
8. Dockerfile node stage + `.dockerignore`/`.gitignore` fixes + the new `frontend` CI job — this is where the `dist/`-gitignored trap must be closed.
9. `RunStatusPoll` DTO + `usePoller` hook — both pages poll; build once.
10. The nav decision (React renders inside `base.html`'s content block; never owns nav) — deferring risks visual drift.
11. The `DecisionBanner` discriminated-union shape — Slice 2's banner matrix is the hardest thing in the milestone; deciding the DTO base-class shape under Slice 2 time pressure is how the logic ends up duplicated in TypeScript.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Versions read live from npm registry 2026-08-17. Medium sub-flag: TS 7.0 GA is five weeks old; Vite manifest mechanics unverified against a real build. |
| Features | HIGH | Every behavior cited to file:line against live templates/routes, cross-checked against the ~7,271-LOC test suite. |
| Architecture | HIGH | Every integration point read at the cited line; self-corrected a line-number drift vs PROJECT.md. Medium sub-flag: Vite docs marked CONFIRM-at-plan-time by policy. |
| Pitfalls | HIGH | Independently measured and corrected the milestone's own scope estimate (2 files/~4,650 LOC/95 assertions -> 6 files/7,271 LOC/131 assertions) rather than repeating it. |

**Overall confidence:** HIGH — four independently-produced documents converged on the same core architecture and actively corrected errors in their own upstream brief rather than propagating them.

### Gaps to Address

- Exact Vite manifest path / multi-entry config unverified against a real build — confirm early in Slice 1.
- Decisions (a) embed-vs-fetch and (b) no-JS support scope are strong defaults, not locked constraints — resolve explicitly before Slice 1's DTO/shell design is finalized.
- Decision (c) TS7/Biome vs TS6/ESLint trades compiler speed against a named regression-detection gap on the poller; if Biome is kept, Slice 2 must add an explicit behavioral proof of both halves of the reload-trigger OR condition.
- The anti-BUG-1 Authorize/Reject mutual-exclusivity pin has no direct positive test today — add one in Slice 2.
- `clarification_round` DTO conversion trap (latent, not live) — Slice 2 must model "3 or more" explicitly rather than relying on Pydantic to silently resolve a missing field the way Jinja does.
- `created_at` is in the `/runs` list projection but not in `RUN_COLS` — the list and detail pages cannot share one DTO; state this constraint explicitly in Slice 1/2 schema work.

## Sources

### Primary (HIGH confidence)
Live repository reads across all four research passes: `app/main.py`, `app/routes/runs.py` (1,534 lines), `app/routes/dashboard.py`, `app/routes/operator_feedback.py`, `app/routes/demo.py`, `app/routes/templating.py`, `app/routes/health.py`, `app/routes/pump.py`, `app/routes/webhook.py`, `app/db/repo/runs.py`, `app/db/repo/demo.py`, `app/templates/*.html`, `app/static/style.css`, `Dockerfile`, `.gitignore`, `.dockerignore`, `.github/workflows/ci.yml`, `app/config.py`, `pyproject.toml`, `tests/test_dashboard.py` (2,296 LOC), `tests/test_needs_operator.py` (2,223 LOC), `tests/test_phase20_clarification_review.py`, `tests/test_reply_redelivery.py`, `tests/test_hitl.py`, `tests/test_clarify_round_hours_safety.py`, `tests/test_design_tokens.py`, `tests/test_ops_route.py`, `.planning/PROJECT.md` (v5 section). `registry.npmjs.org/<package>` live reads for every stack package, 2026-08-17. Docker Hub API confirmation of `node:24-slim`.

### Secondary (MEDIUM confidence)
Official Vite docs (backend-integration, build-options) for manifest-based asset serving — pinned MEDIUM by the research's own `webfetch`-provider confidence policy regardless of source quality. WebSearch-sourced Node.js LTS schedule and TypeScript 7.0 GA release coverage.

---
*Research completed: 2026-08-17*
*Ready for roadmap: yes*
