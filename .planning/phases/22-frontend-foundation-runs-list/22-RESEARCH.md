# Phase 22: Frontend Foundation & Runs List - Research

**Researched:** 2026-08-17
**Domain:** React + TypeScript presentation-layer conversion grafted onto a shipped FastAPI + Jinja2 money-moving operator console — toolchain, Docker, CI, DTO-allowlist, six guards, test-assertion inventory, and one converted page (`/runs`)
**Confidence:** HIGH — every codebase claim below was re-verified against live source this session (not copied from the four prior research passes or from CONTEXT.md without a fresh `Read`/`grep`); package versions were re-confirmed against the live npm registry this session, 2026-08-17.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

All architecture-level choices were locked before planning (`PROJECT.md` Key Decisions, commit `a37e64c`;
`research/STACK.md` DECISION OVERRIDE) and are NOT reopened here. The decisions below are the
implementation-level questions that lock left open.

**Build, deploy, and dev toolchain**

- **D-22-01: A missing Vite manifest raises; pytest gets a committed fixture manifest.**
  `render_react_page()` fails closed when `app/static/dist/.vite/manifest.json` is absent, so a bundle-less
  production deploy is a 500 rather than a silent blank console. A small committed fixture manifest lets the
  hermetic pytest suite render the boot-tag path deterministically without Node in `ci.yml`'s test job. No
  code path exists that emits a bundle-less shell, which is the mechanism by which the markup assertions
  would go vacuous. Matches the repo's fail-closed precedent (pump token, bootstrap fence,
  `UnclassifiedColumnError`).
  **Note for the planner:** `TestClient` never executes JavaScript, so no pytest test can assert
  React-rendered DOM regardless of this choice. What pytest can see on a converted page is the Jinja shell,
  the `__INITIAL_DATA__` block, and the server-rendered forms. Plan assertions accordingly.

- **D-22-02: SHELL-05 is proven in three parts, and the load-bearing part is inside the Dockerfile.**
  (1) Add `app/static/dist` to `.dockerignore` so a locally built bundle can never enter the build context,
  making a local `docker build` behave identically to Render's clone-based build.
  (2) A `RUN test -f app/static/dist/.vite/manifest.json` (or equivalent) assertion in the runtime stage, so a
  missing bundle turns **Render's own build** red instead of shipping a blank console.
  (3) A CI `docker build` job so the failure is caught pre-merge rather than at deploy, avoiding the v4
  Phase 21 "CI green, prod broken" shape.
  Verified latent today: `.gitignore:5` is `dist/`, `.dockerignore` has no `dist` entry, `Dockerfile:38` is
  `COPY . .`.

- **D-22-03: Local dev is the Vite dev server proxying to uvicorn, with a fail-closed dev branch in
  `render_react_page()`.** Browse `localhost:5173`; Vite's `server.proxy` forwards to uvicorn, and the server
  emits `@vite/client` plus the entry source path instead of manifest-hashed tags when a dev setting is on.
  This satisfies SHELL-04 literally ("hot reload that proxies to uvicorn") and gives real React Fast Refresh.
  **Named cost:** a second code path in the server-side template layer. Required mitigations: the setting
  defaults off, the Dockerfile never sets it, and a test asserts a default-settings render contains no
  `localhost` URL.
  — **Reversibility:** costly — removing the dev branch later means re-answering SHELL-04, and any leak of the
  dev setting into production serves script tags pointing at a developer's machine.
  > **Researcher flag:** this decision (D-22-03) reads as the inverse direction from `ARCHITECTURE.md`
  > Pattern 1's "Local dev flow" recommendation, which explicitly rejects "Vite dev server proxying to
  > uvicorn" as "the wrong direction" (uvicorn should stay the document origin; Vite should be a secondary
  > asset origin the browser talks to directly via CORS). CONTEXT.md's D-22-03 was reached during
  > `/gsd-discuss-phase` with the user present and is the locked decision this phase must implement — but the
  > planner should read `ARCHITECTURE.md`'s "Local dev flow" section (reproduced below, Pattern: Local Dev)
  > before wiring the proxy, because the CORS/redirect-origin failure mode ARCHITECTURE.md names (a 303
  > `Location` header authored against `:5173` instead of `:8000`) is a real risk under a reverse-proxy setup
  > too if the proxy strips or rewrites `Host`/`Origin`. Confirm which side owns the redirect origin before
  > building the dev branch, and record the resolution in the plan.

- **D-22-04: TypeScript types generate from a Pydantic-derived OpenAPI document, not from a new endpoint.**
  A script collects `app/schemas/` models via `model_json_schema()` into a `components.schemas`-only OpenAPI
  document and feeds it to `openapi-typescript`, CI-gated for staleness the same way `eval/chart.svg` is
  regenerated and diffed. No new HTTP surface is invented for an embedded-only DTO. The key-set assertion
  behind SHELL-07 and GUARD-04 works by parsing `__INITIAL_DATA__` out of `response.text`, so a route buys
  nothing for testability. (`GET /runs/{id}/status` separately gains a `response_model`, see D-22-11, and
  therefore appears in FastAPI's own OpenAPI natively.)

**Test-suite integrity (GUARD-01, GUARD-02)**

- **D-22-05: The inventory is a machine registry with a generated markdown view.**
  The registry is the source of truth and the guard's input. Each entry carries: file, line, the assertion's
  source text captured at inventory time, the route it exercises, presence-or-absence class, the layer that
  will render the guarded content after conversion (Jinja shell / JSON island / React DOM), and a
  `replaced_by` field a later rewrite fills in. A committed markdown view is regenerated and diffed in CI so a
  reviewer reads prose while the guard reads code. The `replaced_by` trail is what lets Phase 24 assert no
  assertion was silently dropped.

- **D-22-06: The guard asserts completeness, not pinned counts.**
  An AST walk collects every `.text` comparison in scope and fails if any is missing from the registry or
  lacks a layer classification. Counts are derived output printed in the generated view, never hand-pinned.
  Adding an unclassified assertion fails CI; renumbering lines does not. Same shape as
  `scripts/check_proof_inventory.py`.
  **Consequence, and this needs recording:** `ROADMAP.md` Phase 22 Success Criterion 1's parenthetical
  ("`test_dashboard.py` 42 presence / 31 absence; `test_needs_operator.py` 5 / 7") is **illustrative, not
  normative.** See the SC-1 amendment note below.

- **D-22-07: Scope is every file under `tests/` containing `.text`, with explicit recorded zeros.**
  17 files match live. A file with no assertion against `/runs`, `/runs/{id}`, or `/eval` gets an entry
  stating zero affected and the reason (`/ops` stays Jinja; `caplog.text` is not an HTTP response; this body
  is JSON). Nothing is silently out of scope and the exclusion reasoning is reviewable. This is the v3
  lesson: a passing guard proves nothing about what it does not scan.

- **D-22-08: GUARD-01's gate is plan ordering plus a CI check.**
  The inventory is the phase's first plan, and a CI check fails if any file exists under `frontend/src` while
  the registry is absent, or if a page's Jinja markup was converted while its assertions are still
  unclassified. Roughly five lines, and it turns a planning convention into something that can stop a merge.
  — **Reversibility:** one-way — the route-attribution and layer classification can only be performed while
  the Jinja pages still render. After conversion a vacuous absence assertion is indistinguishable from a valid
  one, and no later phase can honestly redo this pass.

- **D-22-09: GUARD-02 = convert by default, mutation-pin the safety subset.** *(This is the concrete,
  testable formulation the roadmap flagged as still needed — do not re-derive it, implement it.)*
  Every assertion whose guarded content moves into React DOM is rewritten as a positive exact-shape assertion
  against the parsed `__INITIAL_DATA__` block, or relocated to a Vitest component test. A positive assertion
  cannot go vacuous, so this is the structural fix. On top of that, only the safety-critical assertions
  (PII scrubbing, XSS, path traversal, the delivery-review Reject gate) get a named falsifying mutation in a
  registry. This mirrors PROOF-05, which pins four durability proofs rather than all 1,400 tests.
  **Locked decision 3 shrinks this problem more than the research assumed.** Because mutation forms stay
  server-rendered Jinja, assertions like `tests/test_dashboard.py:1384` (`">Retry same question</button>"`),
  `:1394` (`"Mark delivered"`) and `:1395` (`"Authorize a new confirmation"`) stay meaningful for free. So do
  the PII proofs at `:523-526`, because the scrubbed `error_detail` travels inside `__INITIAL_DATA__`. The
  genuinely vacuous class is small: content that moves into JSX, such as `:66`
  (`"No payroll runs yet"`). **Do not assume the research's ~44-of-131 figure is the reclassified count; the
  inventory pass measures it.**
  — **Reversibility:** costly — the rewrite touches many test call sites, though the registry preserves each
  original assertion's source text so nothing is unrecoverable.

- **D-22-10: Classify all in Phase 22, pin and rewrite per slice.**
  Phase 22 classifies every affected assertion while the Jinja pages still render (the part that becomes
  impossible later), but only pins and rewrites the assertions for the page it actually converts. Phases 23
  and 24 inherit a finished classification. This avoids Phase 22 writing pins against `run_detail.html`
  markup that Phase 23 replaces.

- **D-22-11: The safety-subset mutation registry is a new hermetic sibling, run by `ci.yml`'s existing test
  job.** Same AST-anchored idiom as `MUTATION_TARGETS` / `check_proof_inventory.py`, but its own registry and
  its own completeness check. These mutations are markup and DTO edits with no database in the loop, so they
  must NOT be wired into `concurrency-proof.yml`, where a missing `DATABASE_URL` silently converts a proof
  into a skip. That failure mode has already bitten this project.

**The `/runs` island, DTO shape, and poller**

- **D-22-12: React owns `runs_list.html:64-115` only.**
  One mount point replacing the `{% if runs %}` branch: the `.table-scroll` region, the table, and the empty
  state. Jinja keeps `:62` `<h1>`, `:61` the `_operator_notice.html` include, and `:117-128` the demo
  send-test form. The `?notice=` operator-feedback channel added by quick task `260814-q0y` stays entirely
  server-side and never round-trips through JSON, and SHELL-10's per-page `<title>` plus `aria-current` story
  is untouched.
  **This is the convention Phase 23 inherits:** React owns data-driven regions, Jinja owns chrome and
  mutations.
  — **Reversibility:** costly — Phase 23 applies this rule across 14 forms and 5 confirm guards, so changing
  it afterward means re-cutting both pages.

- **D-22-13: The poll DTO is a declared sub-shape of the list row DTO.**
  `RunStatusPoll` holds the seven volatile fields (`status`, `badge_class`, `badge_label`, `queue_label`,
  `queue_badge_class`, `has_open_job`, `failure`). `RunListRow` composes it with the static fields (`id`,
  `created_at`, `business_name`, `summary_gate_reason`, `employee_count`). The poller replaces the volatile
  part wholesale and TypeScript enforces the merge. `GET /runs/{id}/status` gains
  `response_model=RunStatusPoll`, which is a legal edit (it is a GET, not one of the 14 fenced mutation
  handlers) and puts the DTO into FastAPI's OpenAPI natively. Phase 23 reuses `RunStatusPoll` unchanged.
  **Presentation vocabulary is server-owned.** `badge_class` and `badge_label` are computed by
  `app/routes/templating.py:48-55` and shipped as fields; they are never re-derived in TypeScript. The Jinja
  filter registrations stay in place for `/` and `/ops`.
  — **Reversibility:** costly — the shape becomes a published contract consumed by generated TypeScript and
  by Phase 23.

- **D-22-14: `usePoller` is a single-URL hook, instantiated once per in-flight row.**
  `usePoller(url, {intervalMs, maxAttempts, stopWhen})`. `/runs` mounts one instance per in-flight row,
  preserving today's per-row network shape and per-row stop behavior (`runs_list.html:54-58`). Phase 23's
  `/runs/{id}` uses one instance and needs no adaptation. Keeps the hook's dependency array small, which
  matters because `exhaustive-deps` on this hook is the entire reason ESLint was chosen over Biome.
  A batch status endpoint was considered and deferred to backlog: it changes the wire shape this milestone
  claims to preserve.

- **D-22-15: The three `js-` poller hooks are dropped on converted pages; the guard is replaced, not
  re-pointed.** The `js-` convention existed to stop someone deleting a `document.querySelector` target that
  looked like dead markup. React holds the badge in state and re-renders it, so there is no selector and
  keeping the classNames would create actually-dead markup, which is the thing the convention opposes.
  `tests/test_design_tokens.py:356-370` is deleted **with a written justification in the commit** and replaced
  by a Vitest test that the badge updates in place on a new status.
  **This amends `ROADMAP.md` Phase 22 Success Criterion 5.** See the amendment note below.

- **D-22-16: The design-token and a11y guards are widened before the first markup moves.**
  `tests/test_design_tokens.py:183` allowlists suffixes `{.css, .html, .py}`, so `.tsx` is invisible; `:191`
  and `:337` glob `app/templates/*.html`. Widen the suffix allowlist to `.ts`/`.tsx`, extend the globs to
  `frontend/src`, and **pin the scanned-file count against a harvested inventory** so the guard cannot
  silently narrow as pages convert. Note `runs_list.html` survives as the shell (it owns the demo form, the
  mount point, and the `__INITIAL_DATA__` block), so the module-import-time read at `:352` does not error at
  collection in this phase; it will need attention if a template is ever fully deleted.

**Guard enforcement**

- **D-22-17: GUARD-06 is enforced twice.** An ESLint restricted-globals rule bans `fetch`,
  `XMLHttpRequest`, and `axios` everywhere under `frontend/src` except the single `usePoller` module (the
  poller legitimately calls `fetch` for GET, so a blanket ban is wrong), giving editor-time feedback. A
  hermetic pytest AST/regex guard asserts the same invariant in `ci.yml`'s existing test job, so the ban
  survives someone disabling, renaming, or misconfiguring the frontend job. Repo precedent for the second
  half: BOUND-01, the `BackgroundTasks` producer guard, and the jobs CAS-only guard are all pytest AST
  guards, not lint config.

### Claude's Discretion

Settled by repo precedent; the planner may refine but should not relitigate:

- **GUARD-04's internal-only declaration.** An explicit three-way partition in `app/schemas/` (exposed on the
  list shape / exposed on the detail shape / named internal-only) with a test that cross-references
  `RUN_COLS`, failing by column name. Precedent: the `RunStatus` vs CHECK-constraint drift test and
  `test_job_kind_drift.py`.
- **GUARD-05's no-HTML assertion.** Both a response-level test asserting `content-type` for
  `POST /webhook/inbound`, `/health/*`, and `/internal/pump`, and a route-table guard asserting no catch-all
  route exists (the only `Mount` remains `/static`, `app/main.py:11`). The catch-all failure mode is the
  severe one: `/health/live` returning 200+HTML makes Render mark a broken deploy healthy while
  `pump.yml`'s `curl -f` goes green and the durable queue is never drained.
- **CI job placement.** The `frontend` job and the `docker build` job are added to the existing
  `.github/workflows/ci.yml` as additional jobs, not a new workflow file, so they inherit its
  `pull_request` + `push: branches: [master]` triggers, its `concurrency` group, and its
  `permissions: contents: read` for free and cannot drift. `eval.yml`'s push-only trigger must not be copied;
  `ci.yml:7-16`'s own comment explains why `pull_request` is what makes a job a pre-merge gate.
- **Phase exit includes a real deploy.** SC-2 requires an operator loading `/runs` on the deployed Render
  service. Before UAT, confirm `git rev-list --count origin/master..master` is 0. v4 Phase 21's largest UAT
  catch was an entire phase sitting unpushed (master 94 ahead) while CI was green and the routes 404'd in
  production.

### Deferred Ideas (OUT OF SCOPE)

- **A batch `/runs` status endpoint.** One request per tick instead of N would be better network behavior, and
  it changes a wire shape this milestone claims to preserve, in the phase whose claim is that nothing changed.
  Backlog candidate, not Phase 22 work.
- **Playwright / real-browser E2E**, a `/` conversion, an `/ops` conversion, and client-side type generation
  against a live server in CI. All already recorded in `REQUIREMENTS.md` → Deferred / Out of Scope.
- **Adding `clarification_round` to `RUN_COLS`** and bounding `load_all_runs`. Both are `app/db/` edits behind
  the untouchable fence. Already in the milestone's deferred list.

### Two roadmap amendments this discussion produced (carry into planning)

1. **SC-1's parenthetical is illustrative, not normative.** Read as "the inventory records the measured counts
   per file." The criterion's real content is that the inventory exists and precedes every conversion commit.
2. **SC-5's third sentence needs amending.** Originally: "the three `js-` poller hooks still resolve... and
   deleting them would break this phase's own headline feature." Under D-22-15 the hooks are **removed** on
   converted pages and the invariant is carried by a Vitest in-place-update test instead. The criterion's
   intent (polling must not be silently broken by markup tidying) survives; its mechanism does not.

### Install-time verification — RESOLVED this session (see Standard Stack below)

`STATE.md` and `research/SUMMARY.md` flagged that Vite 8.2.1 / `@vitejs/plugin-react@6.0.5` / Vitest 4.1.10
peer ranges were validated against TypeScript 7.0.2, not the pinned 6.0.3, and that this needed re-verification
before the stack is treated as settled. **This research session ran that verification live against the npm
registry** — see "TypeScript 6.0.3 install-time compatibility" under Standard Stack. Short answer: clean, no
conflicts. The exact Vite manifest path and multi-entry `rollupOptions.input` config remain unverified against
a real build (no `frontend/` directory exists yet in this repo) — flagged in Open Questions.
</user_constraints>

## Project Constraints (from CLAUDE.md)

- **`uv` only for the Python side** — never `pip`, `venv`, `poetry`, `requirements.txt`. Run everything via
  `uv run <cmd>`; add deps via `uv add` / `uv add --dev`. Docker exports a pinned `requirements.txt` from the
  lock at build time if ever needed — never hand-maintained. (This constraint governs the Python/`app/schemas/`
  side of this phase only; the frontend toolchain is `npm`/`package-lock.json`, a separate ecosystem, and this
  is intentional per the locked stack decision — do not try to unify them.)
- **Two-tier LLM model routing (DeepSeek extraction / Kimi drafting), non-reasoning only, config-driven IDs.**
  Not touched by this phase — the presentation-layer conversion has zero LLM surface.
- **Deterministic decisioning: `decide.py` is pure code, no LLM, no confidence number.** Not touched by this
  phase; `app/pipeline/`, `app/db/`, `app/llm/` are explicitly out of scope and diff-fenced (see Common
  Pitfalls, Pitfall 9).
- **Human-in-the-loop: exactly one gate (operator approves).** This phase does not touch mutation handlers;
  the approval gate's route bodies are byte-identical constraints that this phase's guards must protect, not
  edit.
- **Structured LLM calls: JSON mode + Pydantic + one retry.** Not touched by this phase.
- **FICA/Pub 15-T constants transcribed from source docs, never memory.** Not touched by this phase.
- **Render free-tier constraints** (spin-down after 15 idle min, ~1 min cold start, `$PORT` env var,
  `0.0.0.0` bind, ephemeral filesystem, inbound-HTTP-only wake, 750 free instance-hours/month) — directly
  relevant to this phase's Docker/CI/bundle-size decisions; see Common Pitfalls (Pitfall 8) and Environment
  Availability.
- **`reportlab` not `WeasyPrint`; `psycopg` not `supabase-py`/an ORM; one OpenAI-compatible client for both
  LLM tiers.** "Least moving parts" precedent this phase's stack decisions should mirror (and the locked
  stack decisions already do: no Tailwind, no CSS-in-JS, no component library, no router, no TanStack Query,
  no monorepo tool).
- **GSD workflow enforcement.** File-changing work happens through a GSD command
  (`/gsd-plan-phase` → `/gsd-execute-phase`), not direct ad-hoc edits.
- No emojis in code/commits/filenames; conventional commits; small reviewable diffs; DRY flagged aggressively;
  comments explain WHY not WHAT.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SHELL-01 | `/runs` rendered by React from a built bundle, served from `/static`, no catch-all | Architecture Pattern 1/2; Dockerfile/CI plan below; route-table guard test in Code Examples |
| SHELL-02 | Page data present in the HTML response (no post-load fetch) | Architecture Pattern 5 (`json_script()` + `__INITIAL_DATA__`); D-22-01/D-22-12 |
| SHELL-03 | JS-disabled operator can still read `/runs` and submit the demo form | D-22-12 (Jinja owns the form); Progressive Enhancement table below |
| SHELL-04 | One dev-server command, one typecheck+lint command | D-22-03 (with the flagged reversal caveat); package.json scripts in Code Examples |
| SHELL-05 | Deployed bundle == locally built bundle | D-22-02; Pitfall 2 below; verified-latent `.gitignore`/`.dockerignore`/`Dockerfile` facts |
| SHELL-06 | Broken TS build/lint/test blocks the PR | `pull_request` trigger fact verified below; Pitfall "orchestrator addendum A" |
| SHELL-07 | `/runs` and `/runs/{id}` have separate response shapes | `RUN_COLS` vs `load_all_runs` verified live below (Pattern 4) |
| SHELL-09 | `/` and `/ops` stay Jinja; `/ops` stays script-free | `base.html`/`test_ops_route.py` verified below (Pitfall 6/Anti-Pattern 6) |
| SHELL-10 | Per-page `<title>`, single `aria-current`, no color literal outside `:root` | `base.html:6,12-15` verified below; D-22-16 (guard widening) |
| GUARD-01 | Inventory committed before any page converts | D-22-05/06/07/08; verified file-count re-derivation below |
| GUARD-02 | Engineer can tell a passing absence assertion from a vacuous one | D-22-09 (the concrete formulation) |
| GUARD-04 | New `RUN_COLS` column fails CI unless exposed/internal-only | Pattern 4 (`RowProjection`/`UnclassifiedColumnError`); Claude's Discretion note |
| GUARD-05 | `/webhook/inbound`, `/health/*`, `/internal/pump` never return HTML | Anti-Pattern 1; Pitfall 5; route-table test in Code Examples |
| GUARD-06 | `fetch`/`axios` mutation banned, enforced twice | D-22-17; Pitfall 4; ESLint config in Code Examples |
| LIST-01 | Same columns/badges/ordering/empty state as Jinja | `runs_list.html` verified verbatim below (§1.1 behavior table) |
| LIST-02 | In-place status/queue/failure badge updates, polling stops on settle | `usePoller` design (D-22-14); `runs_list.html:10-59` verified below |
| LIST-03 | Demo send-test redirects to new run; queue failure shows retry sentence | `app/routes/demo.py:264-355` verified below (exact redirect + notice code) |
| LIST-04 | No horizontal overflow at 375px; table scrolls in its own region | `.table-scroll role="region" tabindex="0"` verified at `runs_list.html:65` |
</phase_requirements>

## Summary

Phase 22 is not primarily a UI-building phase — it is the phase that stands up every shared mechanism the
other two v5 slices ride on (Vite/React/TS toolchain, a third Docker stage, a fourth blocking CI job, an
allowlist DTO seam, six guards, and a committed test-assertion inventory) and proves it with the smallest of
the three converted pages. `/gsd-discuss-phase` already resolved every implementation-level decision this
phase needs (D-22-01 through D-22-17, all in CONTEXT.md above) — this research's job is to (a) re-verify every
citation those decisions depend on against live source, since this repo's own history is that a 3-day-old
scope doc drifted five ways, and (b) hand the planner code-shaped patterns, verified package versions, and a
Package Legitimacy Audit so plans can be written prescriptively rather than exploratorily.

Every live-source fact cited in CONTEXT.md and the four prior research passes (SUMMARY/STACK/ARCHITECTURE/
PITFALLS/FEATURES.md) that this phase depends on was re-read or re-grepped this session and **confirmed
accurate, with zero drift** — including the exact `.gitignore`/`.dockerignore`/`Dockerfile` facts behind
SHELL-05, `RUN_COLS`'s 15-column string and the `_safe_run_for_browser` denylist behind SHELL-07/GUARD-04, the
`ci.yml`/`eval.yml` trigger-block difference behind SHELL-06, `runs_list.html`'s exact line boundaries behind
D-22-12, and — critically — the file-count claim behind GUARD-01: `grep -rlE 'assert[^#]*\.text' tests/`
returns **exactly 14 files** this session, matching the PITFALLS.md orchestrator addendum and *not* matching
either REQUIREMENTS.md's stale "14 files, 85 refs" figure (close on file count, off on ref count) or an
earlier 6-file undercount. Trust the AST-registry approach (D-22-06), not any hand-copied number, including
this document's.

The one net-new finding this session adds beyond what CONTEXT.md and the four research passes already
resolved: **the TypeScript 6.0.3 + ESLint peer-dependency verification CONTEXT.md flagged as still-needed is
now done.** `typescript-eslint@8.67.0`'s peer range is `typescript: >=4.8.4 <6.1.0` — TypeScript 6.0.3 sits
inside that range with room to spare (`<6.1.0`, and 6.0.3 is the last stable 6.x release), and neither
`vite@8.2.1`, `@vitejs/plugin-react@6.0.5`, nor `vitest@4.1.10` declares a `typescript` peer dependency at
all (TypeScript is a devDependency consumed only by `tsc`/`tsconfig`, not a peer of the build tools). There is
no install-time conflict to resolve. The remaining unverified item from STATE.md — the exact Vite manifest
path and multi-entry `rollupOptions.input` shape — genuinely cannot be verified without running a real build,
because no `frontend/` directory exists in this repo yet; it is flagged in Open Questions as a first-plan-step
confirmation, not a blocker.

**Primary recommendation:** implement CONTEXT.md's 17 locked decisions as written; use this document's
Standard Stack table (versions re-verified live) and Code Examples (patterns re-derived from live source, not
copied) as the plan's technical backbone; treat the Package Legitimacy Audit's "SUS" verdicts as false
positives from a too-new heuristic (see that section) rather than a reason to substitute unverified
alternative packages.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `/runs` table rendering (rows, badges, empty state) | Browser / Client (React island) | Frontend Server (Jinja shell) | React owns the data-driven `.table-scroll` region (`runs_list.html:64-115`); Jinja owns everything around it (nav, h1, notice, form) — D-22-12 |
| Initial page data | Frontend Server (SSR via Jinja) | — | Embedded in `<script id="__INITIAL_DATA__">` at request time; never fetched client-side — Architecture Pattern 5 |
| Status/queue/failure badge polling | Browser / Client (React `usePoller` hook) | API / Backend (`GET /runs/{id}/status`) | The one legitimate `fetch()` in the frontend; server computes and returns the presentation vocabulary, client only swaps DOM state — D-22-13/14 |
| Mutation submission (demo send-test form) | Frontend Server (Jinja `<form>`) | API / Backend (303 redirect) | Native POST, never `fetch` — GUARD-06 exists specifically to keep this tier assignment enforced |
| DTO field allowlisting | API / Backend (`app/schemas/`) | — | `RowProjection.from_row` raises on any unclassified repo-row key; this must happen server-side before anything reaches the browser — Architecture Pattern 4 |
| Design tokens / CSS | CDN / Static (`app/static/style.css`) | Browser (consumed via `className`) | One `:root` source of truth; React imports zero CSS, applies existing class names only — locked stack decision |
| Build artifact (`dist/`) | CDN / Static (served via existing `/static` mount) | — | No new mount, no new route; Node never reaches the runtime image — Architecture "Recommended Project Structure" |
| Route table / catch-all absence | API / Backend (`app/main.py`) | — | Structural guarantee, not convention — Anti-Pattern 1, GUARD-05 |
| Test-assertion inventory | (process artifact, not a runtime tier) | — | A committed registry + CI completeness gate, consumed by the planner and by Phases 23/24 — GUARD-01 |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Vite | `8.2.1` | Build/dev server, multi-entry per-page bundling | Zero-config multi-page build matches the "three independently-shippable slices" architecture without a monorepo tool `[CITED: npm registry — SUS-flagged too-new, see Package Legitimacy Audit]` |
| React | `19.2.8` | UI library for the page islands | Current stable line; brand-new frontend, no legacy React to preserve compatibility with `[CITED: npm registry — SUS-flagged too-new]` |
| react-dom | `19.2.8` | DOM renderer paired 1:1 with `react` | `[CITED: npm registry — SUS-flagged too-new]` |
| TypeScript | `6.0.3` | Type checking (locked override, NOT the 7.0.2 STACK.md recommended) | Last stable 6.x, published 2026-04-16; required so `typescript-eslint`'s peer range accepts it — confirmed compatible this session `[VERIFIED: npm registry]` |
| `@vitejs/plugin-react` | `6.0.5` | React Fast Refresh via Babel | Official Vite React template default; peers `vite: ^8.0.0`, satisfied `[CITED: npm registry — SUS-flagged too-new]` |
| Node.js (Docker builder stage only) | `24` (`node:24-slim`) | Toolchain runtime; never reaches the runtime image | Active LTS; satisfies every declared `engines.node` range across the stack — `[CITED: webfetch, Docker Hub API confirmation carried from STACK.md, MEDIUM]`. Not independently re-confirmed this session (no `docker pull` run — daemon was not running locally, see Environment Availability). |

**TypeScript 6.0.3 install-time compatibility — verified this session, resolving the STATE.md/CONTEXT.md flag:**

| Package | Declares a `typescript` peer? | Range | TS 6.0.3 inside range? |
|---|---|---|---|
| `typescript-eslint@8.67.0` | Yes | `>=4.8.4 <6.1.0` | **Yes** `[VERIFIED: npm registry]` — `npm view typescript-eslint@8.67.0 peerDependencies` returned `{ eslint: '^8.57.0 \|\| ^9.0.0 \|\| ^10.0.0', typescript: '>=4.8.4 <6.1.0' }` this session |
| `vite@8.2.1` | No | — | N/A — no conflict possible; `npm view vite@8.2.1 engines` returned only `{ node: '^20.19.0 \|\| >=22.12.0' }` `[VERIFIED: npm registry]` |
| `@vitejs/plugin-react@6.0.5` | No | — | N/A — peers are `{ vite: '^8.0.0', '@rolldown/plugin-babel': ..., 'babel-plugin-react-compiler': ... }`, no `typescript` entry `[VERIFIED: npm registry]` |
| `vitest@4.1.10` | No | — | N/A — full peer list re-read this session has no `typescript` key `[VERIFIED: npm registry]` |
| `eslint-plugin-react-hooks` | No (peers only on `eslint`) | — | Latest is `7.1.1`, peer `eslint: '^3.0.0 \|\| ... \|\| ^10.0.0'` `[VERIFIED: npm registry]` — this is a version bump from the unversioned STACK.md mention; pin `7.1.1` |
| `eslint` | — | — | Latest `10.8.1` `[CITED: npm registry — SUS-flagged too-new]`; satisfies `typescript-eslint`'s `eslint: ^8.57.0 \|\| ^9.0.0 \|\| ^10.0.0` peer |

**Conclusion:** there is no install-time conflict between TypeScript 6.0.3 and any other pinned package in
this stack. The STACK.md-era uncertainty was specifically about `typescript-eslint`'s upper bound (`<6.1.0`)
— 6.0.3 clears it. This closes the CONTEXT.md-flagged verification item; no further action needed before
treating the matrix as settled, beyond the still-open Vite-manifest-path item in Open Questions.

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Vitest | `4.1.10` | Component/unit tests for `frontend/` | Same Vite-native toolchain, no second config format `[CITED: npm registry — SUS-flagged too-new? No — OK verdict]` — see Package Legitimacy Audit; `[VERIFIED: npm registry]` for the version+peers |
| `@testing-library/react` | `16.3.2` | React component testing | Peers `react: ^18 \|\| ^19` — satisfied `[VERIFIED: npm registry]` |
| `@testing-library/dom` | (installed alongside `@testing-library/react`, `^10.0.0` per its peer) | DOM query primitives | Required by `@testing-library/react`'s own peer declaration `[VERIFIED: npm registry]` |
| `@testing-library/jest-dom` | `7.0.1` per STACK.md; not independently re-pinned this session — re-verify at install | Custom Vitest matchers | `[CITED: npm registry — SUS-flagged too-new, carried from STACK.md not independently re-checked this session — ASSUMED version, re-confirm at install]` |
| jsdom | `30.0.1` | DOM emulation for Vitest | Testing Library's own recommended default over `happy-dom` for fidelity `[CITED: npm registry — SUS-flagged too-new]` |
| `openapi-typescript` | `7.13.0` | Generate TS types from the Pydantic-derived OpenAPI doc (D-22-04) | Types-only, zero runtime cost, devDependency `[VERIFIED: npm registry]` |
| `@types/react` | `19.2.18` (per STACK.md; not independently re-pinned this session) | Type declarations for React 19 | Tracks the React 19 line 1:1 `[ASSUMED — carried from STACK.md, re-confirm at install]` |
| `@types/react-dom` | `19.2.4` (per STACK.md; not independently re-pinned this session) | Type declarations for react-dom 19 | `[ASSUMED — carried from STACK.md, re-confirm at install]` |
| `@types/node` | `26.2.0` (per STACK.md; not independently re-pinned this session) | Node typings for Vitest/`@types/node` peer (`>=24.0.0` satisfied) | `[ASSUMED — carried from STACK.md, re-confirm at install]` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ESLint + `typescript-eslint` + `eslint-plugin-react-hooks` | Biome | Rejected by the DECISION OVERRIDE — Biome's `exhaustive-deps`-equivalent coverage is thinner, and the poller's correctness IS an effect-dependency problem. Do not relitigate. |
| TypeScript 6.0.3 | TypeScript 7.0.2 | Rejected by the same override — 7.0.2's peer conflict with `typescript-eslint` (`<6.1.0` cap) is the actual reason ESLint would have been unusable at 7.0.2; 6.0.3 removes that conflict entirely, which is a second, independent argument (beyond the `exhaustive-deps` one) for the override. |
| Plain `fetch` in `usePoller` | TanStack Query | Rejected — no cross-component cache sharing need exists at 3 pages; adds a `QueryClientProvider` and bundle weight for nothing this milestone uses. |
| `openapi-typescript` (types-only) | `orval` (types + generated client) | Rejected — `orval`'s value-add is generated mutation functions, which directly conflicts with the native-form-POST decision. |
| No client router | `react-router@8.3.0` | Rejected — peers `react: >=19.2.7`, `node: >=22.22.0` (tight coupling `[CITED: npm registry, carried from STACK.md]`), and buys nothing when every "route" is a full-page 303 anyway. |

**Installation (frontend, once `frontend/` exists — Phase 22's first infra task):**
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install                                    # react, react-dom, vite (template defaults — re-pin per table above if the template scaffolds different versions)
npm install -D typescript@6.0.3 @vitejs/plugin-react@6.0.5 \
               @types/react@19.2.18 @types/react-dom@19.2.4 @types/node@26.2.0
npm install -D vitest@4.1.10 @testing-library/react@16.3.2 \
               @testing-library/jest-dom@7.0.1 @testing-library/dom jsdom@30.0.1
npm install -D eslint@latest typescript-eslint@8.67.0 eslint-plugin-react-hooks@7.1.1
npm install -D openapi-typescript@7.13.0
```
Commit `package-lock.json`; use `npm ci` everywhere (CI, Docker) — never `npm install` — mirroring this
repo's `uv sync --locked` discipline (`.github/workflows/ci.yml:43-45` `[VERIFIED: .github/workflows/ci.yml:43-45]`, quoted: `"# --locked asserts uv.lock matches pyproject.toml instead of silently\n# re-resolving -- a stale lockfile fails the job rather than merging green.\nrun: uv sync --locked"`).

**Version verification performed this session:** every version in the Core table and every version marked
`[VERIFIED: npm registry]` in the Supporting table was confirmed via `npm view <pkg>@<version> version` /
`peerDependencies` / `engines` against the live registry on 2026-08-17 (today). Versions marked `[ASSUMED —
carried from STACK.md]` were in the prior research pass (also dated 2026-08-17, also npm-registry-sourced) but
were not independently re-queried in this session; re-confirm them at install time as a cheap first-plan-step
(`npm view <pkg> version`), the same discipline the `npm view typescript-eslint@8.67.0 peerDependencies` check
above already modeled.

## Package Legitimacy Audit

Ran `gsd-tools query package-legitimacy check --ecosystem npm` against every package this phase installs.

| Package | Registry | Published | Downloads/wk | Source Repo | Verdict | Disposition |
|---------|----------|-----------|--------------|--------------|---------|-------------|
| `vite` | npm | 2026-08-06 | 142,923,941 | `github.com/vitejs/vite` | SUS (`too-new`) | **Approved** — false positive, see note |
| `react` | npm | 2026-07-21 | 115,573,856 | `github.com/react/react` | SUS (`too-new`) | **Approved** — false positive |
| `react-dom` | npm | 2026-07-21 | 135,787,407 | `github.com/react/react` | SUS (`too-new`) | **Approved** — false positive |
| `typescript` | npm | 2026-07-08 | 180,404,383 | `github.com/microsoft/TypeScript` | OK | Approved |
| `@vitejs/plugin-react` | npm | 2026-07-30 | 71,177,531 | `github.com/vitejs/vite-plugin-react` | SUS (`too-new`) | **Approved** — false positive |
| `vitest` | npm | 2026-07-06 | 77,612,487 | `github.com/vitest-dev/vitest` | OK | Approved |
| `@testing-library/react` | npm | 2026-01-19 | 46,158,999 | `github.com/testing-library/react-testing-library` | OK | Approved |
| `@testing-library/jest-dom` | npm | 2026-08-09 | 41,434,985 | `github.com/testing-library/jest-dom` | SUS (`too-new`) | **Approved** — false positive |
| `jsdom` | npm | 2026-07-29 | 79,674,479 | `github.com/jsdom/jsdom` | SUS (`too-new`) | **Approved** — false positive |
| `eslint` | npm | 2026-08-07 | 135,093,798 | `github.com/eslint/eslint` | SUS (`too-new`) | **Approved** — false positive |
| `typescript-eslint` | npm | 2026-08-10 | 61,153,896 | `github.com/typescript-eslint/typescript-eslint` | SUS (`too-new`) | **Approved** — false positive |
| `eslint-plugin-react-hooks` | npm | 2026-04-17 | 67,364,259 | `github.com/facebook/react` | OK | Approved |
| `openapi-typescript` | npm | 2026-02-11 | 5,385,009 | `github.com/openapi-ts/openapi-typescript` | OK | Approved |

**Packages removed due to `[SLOP]` verdict:** none.
**Packages flagged `[SUS]`:** `vite`, `react`, `react-dom`, `@vitejs/plugin-react`, `@testing-library/jest-dom`,
`jsdom`, `eslint`, `typescript-eslint` — all flagged **solely** on the `too-new` signal (most recent version on
the registry published within the tool's recency window). Every one of these packages: (a) has a
publicly-known, long-established official GitHub org as its source repo (`vitejs`, `react` (Meta's own),
`microsoft`, `vitest-dev`, `testing-library`, `jsdom`, `eslint`, the `typescript-eslint` org itself), (b) has
weekly download counts between 41M and 180M — orders of magnitude above any plausible slopsquat, (c) has no
`postinstall` script, and (d) is not deprecated. The `too-new` heuristic is designed to catch a brand-new,
zero-history package masquerading as legitimate — it produces a false positive here because these are
extremely high-velocity, actively-maintained tools that happen to have shipped a routine point release
recently. **No `checkpoint:human-verify` task is warranted for these installs** given the overwhelming
download/repo evidence, but the planner should still install them via the pinned versions in the Standard
Stack table above (not `@latest`) so a future point-release cannot silently substitute an unvetted version.

**Packages carried forward from STACK.md without independent this-session verification** (`@testing-library/dom`
implicit version, `@types/react`, `@types/react-dom`, `@types/node`): all are official `@types/*` scoped
packages or a `testing-library`-org package; risk profile is the same as the table above. Re-run
`npm view <pkg> version` at install time as a cheap sanity check (first-plan-step, not a blocking gate).

## Architecture Patterns

### System Architecture Diagram

```
┌───────────────────────────────── BROWSER ──────────────────────────────────────┐
│  Jinja-only pages         React-rendered page (Phase 22 ships ONE)             │
│  ┌──────────┐ ┌────────┐   ┌───────────────────────────────────────────────┐   │
│  │ / index  │ │ /ops   │   │ /runs                                          │   │
│  │ (Jinja)  │ │(Jinja, │   │ react_page.html shell (Jinja) → <div id="root">│   │
│  │          │ │ NO js) │   │   → runs.tsx mounts <RunsPage>                 │   │
│  └────┬─────┘ └───┬────┘   │   → reads <script id="__INITIAL_DATA__">       │   │
│       │           │        │   → per in-flight row: usePoller(2s) → GET     │   │
│       │           │        │      /runs/{id}/status → badge swap in place   │   │
│       │           │        └──────────────────┬──────────────────────────────┘  │
│       │           │        Jinja-owned (D-22-12): h1, _operator_notice.html,     │
│       │           │        demo send-test <form method="post"> (no fetch)        │
│       │  ONE stylesheet: /static/style.css      ONE nav: base.html (no <script>) │
└───────┼───────────┼──────────────────────────┬───────────────┬──────────────────┘
        │           │      native <form> POST → 303 →  │  GET /runs/{id}/status   │
        │           │      full navigation (unchanged)  │  (2s poll, JSON, the ONE │
        │           │                                    │  legitimate fetch())    │
┌───────┴───────────┴────────────────────────────────────┴───────────────┴────────┐
│                  FastAPI (app/main.py — 19 lines, unchanged shape)               │
│  mount /static (main.py:11)  +  7 include_router calls (main.py:13-19)           │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │ NEW: app/routes/templating.py grows render_react_page() + json_script()  │   │
│  │      reads app/static/dist/.vite/manifest.json → hashed <script>/<link>  │   │
│  │      fails closed if manifest absent (D-22-01)                           │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │ NEW: app/schemas/ — RowProjection.from_row allowlist DTOs;                │   │
│  │      RunListRow (composes RunStatusPoll) for /runs; UnclassifiedColumn-   │   │
│  │      Error raised on any RUN_COLS key not in EXPOSED or EXCLUDED         │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│  Mutation routes (`/demo/send-test` and 14 others) — BYTE-IDENTICAL              │
├────────────────────────────────────────────────────────────────────────────────┤
│  OUT OF SCOPE, DIFF-FENCED: app/pipeline/ app/queue/ app/db/ app/llm/ app/email/ │
└────────────────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure
```
frontend/                          # NEW — sibling to app/, not nested under it
├── package.json + package-lock.json
├── vite.config.ts                 # manifest:true, base:'/static/dist/', input: runs entry only (Phase 22)
├── tsconfig.json                  # strict:true
├── eslint.config.js               # bans <form> outside MutationForm/ConfirmForm; bans fetch outside usePoller
├── vitest.config.ts
└── src/
    ├── entries/
    │   └── runs.tsx                # Phase 22's only entry — mounts <RunsPage>
    ├── generated/
    │   └── dtos.d.ts                # COMMITTED, gated by a --check (eval/chart.svg pattern)
    ├── boot/
    │   └── pageData.ts              # reads <script id="__INITIAL_DATA__">, typed by dtos.d.ts
    ├── components/
    │   ├── MutationForm.tsx         # pulled forward for Phase 23 — THE only file allowed to emit <form>
    │   ├── ConfirmForm.tsx          # pulled forward for Phase 23 — MutationForm + native confirm() guard
    │   ├── StatusBadge.tsx
    │   ├── QueueBadge.tsx
    │   ├── FailureSummary.tsx
    │   └── OperatorNotice.tsx       # mirrors _operator_notice.html markup (stays server-rendered per D-22-12; component may be unused in Phase 22 if the notice truly stays 100% Jinja — confirm at plan time)
    ├── hooks/
    │   └── usePoller.ts             # the ONE legitimate fetch() call site
    └── pages/
        └── RunsPage.tsx

app/schemas/                       # NEW — presentation DTOs, sibling to app/models/, NOT inside it
├── __init__.py
├── _projection.py                 # RowProjection + UnclassifiedColumnError
├── runs_list.py                   # RunListRow, RunsListPage
└── run_status.py                  # RunStatusPoll — shared by /runs poller AND Phase 23's page

app/templates/react_page.html      # NEW — the only template that emits Vite boot tags
app/static/dist/                   # BUILD OUTPUT — gitignored (fixed per D-22-02), dockerignored, baked into image
```

### Pattern 1: Multi-page app with React-rendered islands (the locked architecture)

**What:** `/runs` becomes a thin Jinja shell (`react_page.html`, extends `base.html`) whose
`{% block content %}` is Jinja-owned chrome (h1, notice, demo form) plus one `<div id="root">` React mounts
into. No client router, no `history.pushState`. `/` and `/ops` are completely untouched.

**When to use:** exactly this shape, for all three v5 slices — it is a locked architecture decision, not a
per-phase choice.

**Example — the boot mechanism (adapted from Architecture research, re-verified against live `templating.py` this session):**
```jinja
{# app/templates/react_page.html — NEW. Boot tags live HERE, never in base.html —
   that placement is the entire reason /ops never gets a <script> tag. #}
{% extends "base.html" %}
{% block title %}{{ page_title }}{% endblock %}
{% block content %}
  <div id="root"></div>
  <script id="__INITIAL_DATA__" type="application/json">{{ page_data_json }}</script>
  {% for href in asset_css %}<link rel="stylesheet" href="{{ href }}">{% endfor %}
  <script type="module" src="{{ asset_entry }}"></script>
{% endblock %}
```
```python
# app/routes/templating.py — MODIFIED. Current file is 59 lines, only 2 filters registered.
# Confirmed this session: `templates = Jinja2Templates(directory="app/templates")` at line 10;
# badge_class_filter at :48-50, badge_label_filter at :53-55. [VERIFIED: app/routes/templating.py:10,48-55]
def render_react_page(request, *, entry: str, page_title: str, data: BaseModel) -> Response:
    manifest = _load_manifest()  # raises if app/static/dist/.vite/manifest.json is absent (D-22-01)
    chunk = manifest[f"src/entries/{entry}.tsx"]
    return templates.TemplateResponse(request, "react_page.html", {
        "page_title": page_title,
        "page_data_json": json_script(data),
        "asset_css": chunk.get("css", []),
        "asset_entry": f"/static/dist/{chunk['file']}",
    })
```

**Why MPA and not SPA:** every mutation is a native `<form method="post">` producing a full 303 navigation —
confirmed this session at `app/routes/demo.py:352` (`return RedirectResponse(url=f"/runs/{run_id}", status_code=303)`
`[VERIFIED: app/routes/demo.py:352]`, quoted verbatim). Under an SPA every one of those submits tears the
document down anyway, so the SPA's defining premise is already false for this app's primary workflow.

### Pattern 2: Route-shadowing protection by absence of a catch-all

**What:** verified this session — `app/main.py` is exactly **19 lines**
`[VERIFIED: app/main.py:1-19]`. Line 11 is `app.mount("/static", StaticFiles(directory="app/static"), name="static")`;
lines 13-19 are seven `app.include_router(...)` calls in this exact order:
`health.router, webhook.router, runs.router, dashboard.router, demo.router, pump.router, ops.router`
`[VERIFIED: app/main.py:13-19]`. No `{path:path}` converter exists anywhere in the file. `/static` is the
only `Mount`, and it is a literal prefix that cannot shadow `/webhook/inbound`, `/health/*`, or
`/internal/pump`. **This phase must add no second mount and no catch-all** — the guarantee is structural
today and must stay structural.

**Enforcement (new test, this phase):**
```python
# tests/test_route_shadowing.py — NEW
RESERVED = ("/webhook/inbound", "/health/live", "/health/ready", "/health/queue",
            "/health/schema", "/internal/pump", "/ops", "/runs", "/eval", "/")

def test_only_mount_is_static():
    mounts = [r for r in app.routes if isinstance(r, Mount)]
    assert [m.path for m in mounts] == ["/static"]

def test_no_route_shadows_a_reserved_prefix():
    # Behavioral, not status-code: resolve each reserved path through the real
    # app and assert the MATCHED ENDPOINT OBJECT — a catch-all with html=True
    # would return 200 for everything, making a status-code assertion useless.
    for path in RESERVED:
        scope = {"type": "http", "method": "GET", "path": path}
        match, _ = next(r for r in app.router.routes if r.matches(scope)[0] != Match.NONE).matches(scope)
        # assert the resolved endpoint is the expected function, not a StaticFiles/catch-all
```
Falsifying mutation: add `app.mount("/", StaticFiles(directory="frontend/dist", html=True))` before line 13 →
must red.

### Pattern 3: The allowlist DTO seam (SHELL-07 / GUARD-04) — re-verified against live source

**What:** confirmed this session. `_safe_run_for_browser` (`app/routes/runs.py:220-244`) is a **denylist**:
```python
# app/routes/runs.py:232-241 [VERIFIED: app/routes/runs.py:232-241]
raw_fields = {
    "error_reason",
    "error_detail",
    "last_error",
    "available_at",
    "attempts",
    "max_attempts",
    "payload",
    "diagnostics",
}
```
`RUN_COLS` (`app/db/repo/runs.py:38-42`) is confirmed this session, quoted verbatim:
```python
# app/db/repo/runs.py:38-42 [VERIFIED: app/db/repo/runs.py:38-42]
RUN_COLS = (
    "id, business_id, source_email_id, status, reply_epoch, extracted_data, decision,"
    " reconciliation, error_reason, error_detail, alias_candidates, hours_changes,"
    " pay_period_start, pay_period_end, updated_at"
)
```
Subtracting `raw_fields` from the 15 `RUN_COLS` columns, what **survives** the denylist today:
`id, business_id, source_email_id, status, reply_epoch, extracted_data, decision, reconciliation,
alias_candidates, hours_changes, pay_period_start, pay_period_end, updated_at`. `business_id`,
`source_email_id`, `reply_epoch`, `alias_candidates`, `extracted_data`, `reconciliation`, and `decision` are
all PII-or-internal and all pass the denylist untouched — confirming the ARCHITECTURE.md/PITFALLS.md finding
exactly, from a fresh read.

Confirmed this session: `created_at` is genuinely absent from `RUN_COLS` (`grep -c "created_at" app/db/repo/runs.py`
found no match inside the `RUN_COLS` string) but **is** present in `load_all_runs`'s own projection —
`app/db/repo/demo.py:230` — quoted: `"SELECT pr.id, pr.business_id, pr.status, pr.created_at, pr.updated_at,"`
`[VERIFIED: app/db/repo/demo.py:230]`. **`/runs` and `/runs/{id}` genuinely cannot share one DTO** — SHELL-07
is not a stylistic preference, it is forced by this schema fact.

**The pattern that replaces discipline (per ARCHITECTURE.md, reproduced here as the load-bearing code shape
for this phase's `app/schemas/` package):**
```python
# app/schemas/_projection.py — NEW
class UnclassifiedColumnError(RuntimeError):
    """A repo row carried a key that is neither exposed nor consciously excluded."""

class RowProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    EXCLUDED: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Self:
        unknown = set(row) - set(cls.model_fields) - cls.EXCLUDED
        if unknown:
            raise UnclassifiedColumnError(f"{cls.__name__}: unclassified {sorted(unknown)}")
        return cls.model_validate({k: v for k, v in row.items() if k in cls.model_fields})
```
```python
# tests/test_schema_projection.py — NEW, this phase, hermetic (RUN_COLS is a module constant)
def test_every_run_col_is_classified() -> None:
    cols = {c.strip() for c in repo.runs.RUN_COLS.split(",")}
    classified = set(RunListRow.model_fields) | RunListRow.EXCLUDED
    assert not (cols - classified), (
        f"New payroll_runs column(s) {sorted(cols - classified)} reached RUN_COLS but "
        "were neither exposed in RunListRow nor named in RunListRow.EXCLUDED."
    )
```
Falsifying mutation for GUARD-04: append `, ssn` to `RUN_COLS` in a scratch branch → this test must red;
revert byte-identically.

### Pattern 4: `json_script()` — the XSS seam for embedded data (SHELL-02)

**What:** `model_dump_json()` output is not protected by Jinja autoescape once passed through `| safe`, and a
body containing the literal `</script>` terminates the element early. This is a real risk surface for this
app specifically because the DTO carries client-supplied text (`business_name` from a business row,
eventually conversation bodies in Phase 23).
```python
# app/routes/templating.py — MODIFIED. Django's json_script is the precedent pattern.
_JSON_SCRIPT_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"}

def json_script(model: BaseModel) -> Markup:
    raw = model.model_dump_json()
    for ch, esc in _JSON_SCRIPT_ESCAPES.items():
        raw = raw.replace(ch, esc)
    return Markup(raw)
```
Test (this phase, able to fail): construct a `RunListRow` whose `business_name` is
`</script><img src=x onerror=alert(1)>`, render `/runs`, assert the response body contains no literal
`</script>` before the closing tag of the data island. Falsifying mutation: remove the `<` replacement →
test reds.

### Pattern 5: `usePoller` and the `/runs` list poller — re-verified against live `runs_list.html`

**What:** `runs_list.html` was read in full this session (129 lines). Confirmed exact boundaries CONTEXT.md's
D-22-12 depends on:

| Region | Lines | Content |
|---|---|---|
| Poller `<script>` | `:4-60` (comment `:4-9`, `<script>` opens `:10`, closes `:60`) | Vanilla-JS per-row poller `[VERIFIED: app/templates/runs_list.html:4-60]` |
| Notice include | `:61` | `{% include "_operator_notice.html" %}` `[VERIFIED: app/templates/runs_list.html:61]` |
| `<h1>` | `:62` | `<h1>Payroll Runs</h1>` `[VERIFIED: app/templates/runs_list.html:62]` |
| React region (D-22-12) | `:64-115` | `{% if runs %}` ... table ... `{% else %}` empty state ... `{% endif %}` `[VERIFIED: app/templates/runs_list.html:64-115]` |
| Demo form | `:117-128` | `<form method="post" action="/demo/send-test">` `[VERIFIED: app/templates/runs_list.html:118-128]` |

The poller (`:15-52`) polls `GET /runs/{id}/status` every 2000ms, caps at 60 attempts, swaps 4 targets
(`.js-status-badge`, `.queue-badge`, `.js-failure-secondary`, `.js-failure-summary`) via `document.querySelector`
scoped to `[data-run-id="..."]`, stops when `!IN_FLIGHT.has(data.status) && !data.has_open_job`
`[VERIFIED: app/templates/runs_list.html:46-48]`, and swallows fetch errors per tick (`.catch(function() {})`)
`[VERIFIED: app/templates/runs_list.html:50]`. `usePoller` must reproduce every one of these five properties
(URL shape, interval, cap, stop condition, error-swallow) exactly — LIST-02's parity claim depends on it.

```typescript
// frontend/src/hooks/usePoller.ts — the ONE legitimate fetch() call site (GUARD-06)
export function usePoller<T>(
  url: string,
  opts: { intervalMs: number; maxAttempts: number; stopWhen: (data: T) => boolean },
  onUpdate: (data: T) => void,
): void {
  useEffect(() => {
    let attempts = 0;
    let cancelled = false;
    const timer = setInterval(() => {
      if (cancelled || attempts >= opts.maxAttempts) { clearInterval(timer); return; }
      attempts++;
      fetch(url)
        .then((r) => (r.ok ? r.json() : null))
        .then((data: T | null) => {
          if (!data || cancelled) return;
          onUpdate(data);
          if (opts.stopWhen(data)) clearInterval(timer);
        })
        .catch(() => {}); // deliberate — matches runs_list.html:50, a network-blip guard, not error hiding
    }, opts.intervalMs);
    return () => { cancelled = true; clearInterval(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- url/opts intentionally
    // captured once per mount; re-deriving them per render would restart every
    // row's poll on every parent re-render. This is exactly the class of decision
    // exhaustive-deps exists to force an explicit acknowledgement of (STACK.md
    // DECISION OVERRIDE rationale) — do not silently widen the dep array to satisfy lint.
  }, []);
}
```
**Teardown-observable test (Pitfall 10, applies directly here):** assert the interval is actually cleared on
unmount — e.g. stub `global.fetch` with a call counter, unmount the component, advance fake timers, assert
the call count does not increase. Do not wrap this assertion in `try`/`catch` — this repo has a recorded scar
where a cleanup-as-assertion test was wrapped in `try/finally` and stayed green while the underlying invariant
broke (`gsd-cleanup-as-subject-is-suppression` memory).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Badge class/label vocabulary (11 statuses) | A `Record<string, string>` in TypeScript | Consume `badge_class`/`badge_label` as plain string fields on the DTO, computed server-side by `app/routes/templating.py:48-55` | Two sources of truth for the same operator-facing vocabulary is the exact drift class this milestone exists to prevent; `[VERIFIED: app/routes/templating.py:18-45]` these maps are 11+11 entries today and will grow |
| `?notice=<code>` label rendering | Reading `?notice=` in TypeScript and rendering the raw code | Never read `?notice=` client-side; it stays 100% server-reduced via `notice_label()` and rendered by `_operator_notice.html` (Jinja) | `notice_label` reduces an unknown code to `None` server-side specifically so a hand-crafted URL renders nothing (`app/routes/operator_feedback.py:98-100`) `[VERIFIED: app/routes/operator_feedback.py:98,100]`; client-side rendering reopens exactly the injection surface the module was written to close |
| TypeScript↔Pydantic type sync | Hand-written `interface RunListRow {...}` | `openapi-typescript` generating from a Pydantic-derived OpenAPI doc (D-22-04), CI-gated for staleness | A second manually-maintained shape drifts silently; a mistyped field or a new column just doesn't type-error |
| Field allowlisting for the browser payload | A denylist (`.pop()` a list of forbidden fields) or wholesale `model_dump()` | `RowProjection.from_row` — allowlist by declared field, `EXCLUDED` naming withheld fields, raises on anything else | The existing `_safe_run_for_browser` denylist already leaks `business_id`/`reply_epoch`/`alias_candidates` today (re-verified this session, Pattern 3 above); a denylist plus a generic serializer is opt-out security on a table that grows |
| The confirm-guard/mutation-form abstraction | Inline `<form onSubmit={...}>` per mutation | `MutationForm`/`ConfirmForm`, pulled forward into this phase against `/runs`'s one trivial form (D-22-12 note; no confirm guard needed here, but the component should exist so Phase 23 is composition not invention) | React's `onSubmit` returning `false` does NOT cancel submission — only `event.preventDefault()` does; building this the first time under Phase 23's 14-form/5-confirm-guard pressure is exactly where the regression lands unnoticed |

**Key insight:** every "Don't Hand-Roll" row above is really the same rule from a different angle — this app
already has a single, tested owner for each piece of operator-facing vocabulary or security boundary (a
Python dict, a Python function, a Python class). React's job in every case is to *consume* that owner's output
as a typed prop, never to reconstruct the logic behind it.

## Common Pitfalls

*(Full pitfall catalog with all 16 items lives in `.planning/research/PITFALLS.md`; the items below are the
ones with `Prevention slice: 1` — i.e. Phase 22 owns them per that document's own Pitfall-to-Phase Mapping.
This section re-verifies the load-bearing facts behind each against live source, this session.)*

### Pitfall 1: The vacuous parity test — GUARD-01/GUARD-02's whole reason to exist

**What goes wrong:** `assert X not in response.text` is satisfied trivially by a page that renders nothing.
When the poller/table moves into a React bundle, the positive half of a paired positive/absence assertion
turns RED and gets fixed; the negative half turns GREEN and gets silently left proving nothing.

**Verified this session — the file-count claim behind GUARD-01/D-22-07:**
```
grep -rl "\.text" tests/            → 17 files (16 excluding conftest.py)
grep -rlE "assert[^#]*\.text" tests/ → 14 files (excludes conftest.py, test_clarify_round_hours_safety.py,
                                                  test_gateway.py — these 3 contain ".text" but not inside a
                                                  single-line-regex-matchable assert statement)
```
`[VERIFIED: shell command run this session against tests/]`. This confirms CONTEXT.md's D-22-07 "17 files
match live" and the PITFALLS.md orchestrator-addendum's "14 files" (same `assert[^#]*\.text` regex, same
result) **exactly**. It also demonstrates *why* D-22-06 mandates an AST walk over a regex: the 3-file gap
between "17 files contain `.text`" and "14 files match this regex" is almost certainly multi-line `assert`
statements the single-line regex misses — a regex-based inventory would silently under-count, which is the
exact failure class GUARD-01 exists to prevent. **Do not build the inventory guard on a regex; use `ast.walk`
over `ast.Compare` nodes**, per D-22-06 and the `scripts/check_proof_inventory.py` precedent.

**How to avoid:** the three enforceable moves from PITFALLS.md, already adopted as D-22-05/06/09: (1)
mutation-gate every migrated absence assertion against the safety subset, (2) convert the rest to positive
exact-shape assertions, (3) ban the AST shape `assert <expr> not in <response>.text` in the six-plus affected
files after the owning slice ships (a follow-up CI guard, not required day one of Phase 22).

**Detection command for the plan:** after `/runs` converts, `git stash` the React entry component, run the
suite, require ≥1 failure per Class-C pin owned by this slice (the ~7-9 absence assertions in
`test_dashboard.py` that target `runs_list.html`-rendered content — the inventory pass will produce the exact
list; do not guess it here).

### Pitfall 2: `dist/` is already gitignored — re-verified this session, still latent

**What goes wrong:** confirmed this session, byte-for-byte:
- `.gitignore:5` is `dist/` `[VERIFIED: .gitignore:5]`
- `.dockerignore` (39 lines, full read this session) has **no** `dist` entry anywhere `[VERIFIED: .dockerignore:1-39]`
- `Dockerfile:38` is `COPY . .` (inside the **builder** stage, immediately followed by `:39` `RUN uv sync
  --frozen --no-dev`) `[VERIFIED: Dockerfile:38-39]`
- `Dockerfile:53` is `COPY --from=builder /app /app` (inside the **runtime** stage) `[VERIFIED: Dockerfile:53]`

So: build `dist/` at `app/static/dist/`, it is gitignored → Render's Git-clone-based build never sees it →
`docker build` from the local working tree succeeds (the tree has `dist/` on disk, `.dockerignore` doesn't
exclude it) → CI succeeds (the Python suite doesn't need the bundle) → Render deploys a blank `<div id="root">`
with a 404 on the bundle asset. **Green everywhere except production.**

**How to avoid (per D-22-02, build in the image, do not commit):** add a fourth Docker stage
`FROM node:24-slim AS frontend`; the runtime stage's `COPY --from=frontend /frontend/dist app/static/dist`
must land **after** `Dockerfile:53`'s `COPY --from=builder /app /app`, which otherwise clobbers it (this is
the exact ordering trap PITFALLS.md names, and it is real: `Dockerfile:53` copies the whole `/app` tree
wholesale). Add a `RUN test -f app/static/dist/.vite/manifest.json` assertion after the COPY, with a comment
naming the failure it prevents, matching this Dockerfile's own established comment convention (e.g. the
WORKDIR comment block at `Dockerfile:44-47` `[VERIFIED: Dockerfile:44-47]`, quoted: `"WORKDIR=/app required —
uvicorn launched from here so relative paths resolve:\n#   app/templates  → Jinja2Templates..."`). Add
`app/static/dist` to `.dockerignore` (D-22-02 part 1) so a locally-built bundle riding in via `COPY . .`
cannot mask the same failure locally that Render would hit.

**Warning signs:** `git status` clean while `app/static/dist/` has files on disk; `.dockerignore` never
edited during this phase; a docker build that succeeds locally but was never run against a fresh `git clone`.

### Pitfall 5: An SPA fallback route would swallow `/webhook` — re-verified, structurally absent today

**What goes wrong (if ever introduced):** a catch-all registered before line 13 in `app/main.py` would
FULL-match every path, including `/webhook/inbound` (`app/routes/webhook.py`), silently 200-ing an inbound
payroll email with an HTML body — the provider considers delivery successful and never retries; the run
simply never exists.

**Verified this session:** no such route exists. `app/main.py` is 19 lines total, zero `{path:path}`
converters, one `Mount` (`/static`). This phase must not introduce one — GUARD-05's "no catch-all route"
requirement and this pattern are the same guarantee from two directions. See Pattern 2 above for the
enforcement test.

### Pitfall 6: Design-token/a11y guards go blind on `.tsx` and die at import — re-verified this session

All four sub-findings confirmed against live `tests/test_design_tokens.py` this session:

| Sub-finding | Verified line | Verbatim |
|---|---|---|
| Hardcoded suffix allowlist | `:183` | `if path.suffix not in {".css", ".html", ".py"}:` `[VERIFIED: tests/test_design_tokens.py:183]` |
| Template glob #1 | `:191` | `for path in [_STYLE_PATH, *_REPO_ROOT.glob("app/templates/*.html")]:` `[VERIFIED: tests/test_design_tokens.py:191]` |
| Template glob #2 | `:337` | `for path in _REPO_ROOT.glob("app/templates/*.html"):` `[VERIFIED: tests/test_design_tokens.py:337]` |
| Module-import-time read | `:352` | `_RUNS_LIST_HTML = (_REPO_ROOT / "app" / "templates" / "runs_list.html").read_text()` `[VERIFIED: tests/test_design_tokens.py:352]` |
| `js-` hook presence assertions | `:361-362` | `for hook in ("js-status-badge", "js-failure-summary", "js-failure-secondary"): assert hook in _RUNS_LIST_HTML, ...` `[VERIFIED: tests/test_design_tokens.py:361-362]` |

**Consequence for this phase, precisely stated per D-22-15/D-22-16:** `runs_list.html` itself is **not**
deleted in Phase 22 (it survives as the shell per D-22-12), so `:352`'s module-level read does not error at
collection this phase. But the three `js-` hooks (`:361-362`'s target) ARE removed from the table region once
React owns it — so `:355-370`'s assertions (asserting those hooks are present in `runs_list.html` and absent
from `style.css`) must be **deleted with a written justification**, per D-22-15, and replaced by a Vitest
test asserting the badge updates in place. Do this widening/deletion **before** the table region converts, not
after — a guard that still expects `js-status-badge` inside `runs_list.html` after the table moves to React
will red for the wrong reason (a real regression vs. an expected structural change) and mask real signal.

**How to avoid:** widen `:183`'s suffix set to include `.ts`/`.tsx`; extend both globs (`:191`, `:337`) to
also scan `frontend/src`; add a companion assertion that the scanned file count is non-zero per extension
present in the repo (so a future extension can't silently escape scanning); move `:352`'s read into the
relevant test body rather than module scope (protects the *next* template deletion, in Phase 23/24).

### Pitfall 8: Render free-tier realities — the demo's first impression becomes a spinner

**Verified this session:** `app/static/style.css` is present and the design-token guard reads it at
`:191`/module scope; Docker CLI is present locally (`Docker version 28.4.0`) but the daemon was not running
during this research session (`Cannot connect to the Docker daemon` — see Environment Availability), so the
image-size/build-time claims from `STACK.md §6` were not independently re-measured this session and remain
`[CITED: STACK.md, carried forward, MEDIUM]`.

**How to avoid (all D-22-01/D-22-12 already commit to this):** server-render the shell + Jinja-owned chrome
(nav, h1, notice, form); embed the DTO server-side (Pattern 4 above) so first paint on a cold Render instance
shows real content, never a bare spinner; add `node_modules/` and any local `frontend/dist` to
`.dockerignore` (D-22-02) so the runtime image doesn't inflate; keep `/ops` script-free (already true, see
Anti-Pattern below) as the mitigation for "the page you read when everything else is broken."

### Pitfall 9: Scope creep into money-moving code — the diff-scope gate

**What goes wrong:** the DTO seam, the badge-vocabulary port, and the denylist-to-allowlist migration are all
genuinely better designs that are also each one step from an `app/db/` or `app/pipeline/` edit (a new SQL
column, moving badge computation into the pipeline so it can be "computed once," a `?format=json` branch on a
mutation route). Every one of these is out of scope per the untouchable-fences list.

**Enforcement, fold into the existing `lint` job (verified this session — `ci.yml`'s `lint` job runs `uv run
ruff check .` at line 48, an easy place to append a `grep` step):**
```bash
git diff --name-only "${BASE_SHA}"..HEAD | grep -E '^app/(pipeline|queue|db|llm|email)/' && exit 1 || true
```
Confirmed this session: `.github/workflows/ci.yml` has exactly **3** jobs today (`lint`, `test`, `typecheck`)
`[VERIFIED: .github/workflows/ci.yml:30,50,79]` — this phase adds a 4th (`frontend`) and a 5th (`docker
build`), per Claude's Discretion "CI job placement" above, both as new jobs in the same file (not a new
workflow), inheriting the `pull_request` + `push: branches: [master]` trigger and the `concurrency` group
already declared at `ci.yml:17-27` `[VERIFIED: .github/workflows/ci.yml:17-27]`.

### Anti-Pattern: `/ops` gaining a script tag from a shared layout

**Verified this session, exact citations:** `app/templates/base.html` is 21 lines total, full read this
session — contains **zero** `<script>` elements `[VERIFIED: app/templates/base.html:1-21]`. The pin is
`tests/test_ops_route.py`, confirmed at two distinct lines this session:
- `:364` — `def test_ops_page_has_no_script_or_polling(fake_repo):` `[VERIFIED: tests/test_ops_route.py:364]`
- `:366` — `assert "<script" not in response.text` `[VERIFIED: tests/test_ops_route.py:366]`

(CONTEXT.md cites `:364`; PITFALLS.md's own correction cites `:366` for the actual assertion line — both are
accurate, they're citing the `def` and the assertion respectively; re-verified here so the planner has the
exact split.) **Rule:** Vite boot tags belong only in `react_page.html`, never hoisted into `base.html` — the
DRY-looking move is exactly the mistake, and `:366` reds immediately if it happens.

## Runtime State Inventory

Not applicable — Phase 22 is new infrastructure plus one page conversion, not a rename/refactor/migration.
No existing stored data, live service config, OS-registered state, secret/env-var names, or build artifacts
change identity in this phase. (The GUARD-01 test-assertion inventory is a *different* kind of "inventory" —
a completeness registry for test coverage, not a runtime-state migration audit — and is fully specified under
Common Pitfalls Pitfall 1 / D-22-05 through D-22-08 above.)

## Code Examples

### package.json scripts (SHELL-04 — "one command to typecheck+lint")
```json
{
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "typecheck": "tsc --noEmit",
    "lint": "eslint .",
    "check": "npm run typecheck && npm run lint",
    "test": "vitest run",
    "gen:types": "node scripts/generate-openapi-doc.py | openapi-typescript /dev/stdin -o src/generated/dtos.d.ts"
  }
}
```
`npm run check` satisfies "one command to typecheck and lint." `npm run dev` (Vite dev server) is the "one
command for the hot-reloading dev server" — but re-read the D-22-03 flag under User Constraints before wiring
the proxy direction.

### ESLint restricted-syntax rules (R1/R2/R3 from ARCHITECTURE.md, GUARD-06 enforcement half 1)
```javascript
// frontend/eslint.config.js — excerpt
{
  rules: {
    "no-restricted-syntax": [
      "error",
      {
        selector: "JSXOpeningElement[name.name='form']",
        message: "Only MutationForm/ConfirmForm may emit <form>. See D-22-12 / ARCHITECTURE.md Pattern 3.",
      },
    ],
    "no-restricted-globals": [
      "error",
      { name: "fetch", message: "fetch is banned outside src/hooks/usePoller.ts (GUARD-06)." },
    ],
  },
},
{
  files: ["src/components/MutationForm.tsx", "src/components/ConfirmForm.tsx"],
  rules: { "no-restricted-syntax": "off" },
},
{
  files: ["src/hooks/usePoller.ts"],
  rules: { "no-restricted-globals": "off" },
}
```

### Hermetic pytest AST guard mirroring GUARD-06's second enforcement half
```python
# tests/test_no_fetch_outside_poller.py — NEW, hermetic, no Node required
import ast
from pathlib import Path

ALLOWED = {Path("frontend/src/hooks/usePoller.ts")}

def test_fetch_confined_to_poller_hook() -> None:
    offenders = []
    for path in Path("frontend/src").rglob("*.ts*"):
        if path in ALLOWED:
            continue
        text = path.read_text()
        if "fetch(" in text or "axios" in text or "XMLHttpRequest" in text:
            offenders.append(str(path))
    assert not offenders, f"fetch/axios/XMLHttpRequest found outside usePoller.ts: {offenders}"
```
This is a text-scan, not a real TS `ast` walk (Python's `ast` cannot parse `.tsx` — PITFALLS.md's own
warning, and this repo has been burned before by a `git grep -E` that silently ignored `\b`). Treat it as a
belt to the ESLint suspenders, not a standalone proof; a determined obfuscation (`window["fe" + "tch"]`) would
defeat it, and that's an acceptable gap given ESLint is the primary enforcement layer per D-22-17.

### GUARD-05's no-HTML response assertion
```python
# tests/test_no_html_on_service_routes.py — NEW
import pytest

@pytest.mark.parametrize("path,method", [
    ("/webhook/inbound", "post"),
    ("/health/live", "get"), ("/health/ready", "get"),
    ("/health/queue", "get"), ("/health/schema", "get"),
    ("/internal/pump", "get"),
])
def test_service_route_never_returns_html(client, path, method):
    response = getattr(client, method)(path)
    assert "text/html" not in response.headers.get("content-type", "")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|---|---|---|---|
| STACK.md's original recommendation: TypeScript 7.0.2 + Biome | **Overridden, locked**: TypeScript 6.0.3 + ESLint + `eslint-plugin-react-hooks` | 2026-08-17, same day as the STACK.md research pass, recorded in its own "DECISION OVERRIDE" trailer | `exhaustive-deps` coverage on the poller effect is the deciding factor; this session's peer-range check additionally confirms TS 6.0.3 removes the `typescript-eslint` peer conflict that would have made ESLint genuinely broken at 7.0.2 |
| `_safe_run_for_browser` denylist as the sole reduction boundary | `RowProjection` allowlist as an **additional outer layer** (denylist stays as an inner layer, not deleted) | This phase | Belt-and-braces: two independent reductions, either one alone would prevent the leak this phase's schema work targets |
| Vanilla-JS per-row `document.querySelector` poller (`js-*` classes) | Typed `usePoller` React hook, component state instead of DOM selectors | This phase (for `/runs`) | The `js-` hooks are removed, not re-pointed — D-22-15; this is a deliberate, recorded departure from the milestone's original SC-5 wording |

**Deprecated/outdated:** the `js-status-badge` / `js-failure-secondary` / `js-failure-summary` selector
convention on the converted table region — superseded by React component state. Still live and required on
any page/region that has NOT yet converted (there are none in this repo outside `/runs` and `/runs/{id}`, and
`/runs/{id}` doesn't convert until Phase 23).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `@testing-library/jest-dom@7.0.1`, `@types/react@19.2.18`, `@types/react-dom@19.2.4`, `@types/node@26.2.0` — versions carried from STACK.md, not independently re-queried against the npm registry this session | Standard Stack (Supporting) | Low — these are minor/patch version pins on official `@types/*`/`testing-library`-org packages; worst case is a one-line version bump at install time, not a wrong package |
| A2 | `node:24-slim` Docker Hub tag still exists and Node 24 remains Active LTS as of today | Standard Stack (Core) | Low-Medium — carried from STACK.md's Docker Hub API check (same day); if the tag were pulled this would surface immediately as a Docker build failure, not a silent bug |
| A3 | Vite's manifest path is `.vite/manifest.json` relative to `build.outDir`, and the multi-entry `rollupOptions.input` config works as documented for incrementally-added entries | Architecture Pattern 1 | Medium — this is the one item that literally cannot be verified without running `npm create vite` + a build, which this session did not do (no `frontend/` directory exists in the repo yet). Confirm as the first concrete step of the toolchain plan, before writing `render_react_page()`'s manifest loader against an assumed shape. |
| A4 | The exact reversibility/direction tension flagged in D-22-03 (dev-server-proxies-to-uvicorn vs. ARCHITECTURE.md's stated preference for the reverse) resolves cleanly without a redirect-origin bug | User Constraints note under D-22-03 | Medium — if unresolved, a 303 `Location` header could resolve against `localhost:5173` instead of the uvicorn origin in dev only (not production), producing a dev-only-broken-mutation bug that would be confusing to debug without this note |

## Open Questions

1. **Exact Vite manifest path and multi-entry input config** (A3 above).
   - What we know: `vite.dev/config/build-options` documents `build.manifest` default path
     `.vite/manifest.json` relative to `build.outDir`, and `ManifestChunk` fields (`file`, `css`, `imports`,
     `isEntry`). Cited by ARCHITECTURE.md to official docs, but the `classify-confidence` seam pins `webfetch`
     at LOW regardless of source quality — this was never independently confirmed by running a real build, in
     any research pass including this one.
   - What's unclear: whether the path assumption holds exactly, and what the multi-entry `rollupOptions.input`
     (or top-level `build.rollupOptions.input`, per ARCHITECTURE.md's note that top-level `input` is preferred)
     looks like once only one entry (`runs.tsx`) exists — this affects how cleanly Phase 23/24 can each add
     one more entry without reshaping the config.
   - Recommendation: the plan's first concrete task should be `npm create vite@latest frontend -- --template
     react-ts` followed by one real `npm run build`, confirming the manifest's actual on-disk shape, **before**
     `render_react_page()`'s manifest loader is written against an assumed shape. This is cheap (minutes) and
     removes the single largest unverified assumption in the whole phase.

2. **D-22-03's dev-proxy direction vs. ARCHITECTURE.md's stated preference (A4 above).**
   - What we know: D-22-03 (locked, from `/gsd-discuss-phase`) says Vite dev server proxies to uvicorn.
     ARCHITECTURE.md's "Local dev flow" section explicitly argues the opposite direction is correct (uvicorn
     stays the document origin; Vite is a secondary asset origin the browser calls directly, with CORS) and
     calls the proxy-to-uvicorn direction "the wrong direction," citing the specific failure mode of a 303
     `Location` header resolving against the wrong origin.
   - What's unclear: whether D-22-03 was reached with this specific tension already considered and
     deliberately overridden (in which case: implement as locked, no further discussion needed) or whether it
     is a genuine oversight worth a one-message confirmation before the plan commits to the proxy-to-uvicorn
     shape.
   - Recommendation: the planner should resolve this explicitly — either by re-reading the full
     `/gsd-discuss-phase` transcript for D-22-03's reasoning (not available to this research pass; the
     DISCUSSION-LOG.md's Q3 table only records the four options and the selection, not a rebuttal of
     ARCHITECTURE.md's specific concern), or by flagging it as a `checkpoint:human-verify` note in the plan
     if the reasoning isn't recoverable. This is a dev-only risk (never touches production), so it should not
     block planning, but it should not be silently implemented against unaddressed contrary research either.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | Frontend toolchain (local dev only; Docker uses its own `node:24-slim` stage) | ✓ | v26.5.0 (local) | — (Docker stage pins 24 independently; local dev node version is not required to match) |
| npm | Package install/build | ✓ | 11.17.0 | — |
| Docker CLI | `docker build` verification, the new CI job | ✓ | 28.4.0 | — |
| Docker daemon | Actually running a `docker build` locally | ✗ (not running during this research session) | — | Not a blocker for planning; the executor will need the daemon running to verify SHELL-05 locally before relying solely on CI's docker-build job |
| `uv` | Python-side `app/schemas/` package, existing test suite | ✓ | 0.9.9 | — |
| `pytest` | Existing hermetic suite (1,510 tests collected this session) | ✓ | 9.1.1 | — |

**Missing dependencies with no fallback:** none — the Docker daemon gap is a "not running right now," not
"not installed," and does not block writing plans; it blocks a specific local-verification step the executor
should start before attempting it.

**Missing dependencies with fallback:** none needed.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Python framework | pytest 9.1.1, config in `pyproject.toml` `[tool.pytest.ini_options]` (`:40-47`) `[VERIFIED: pyproject.toml:40-47]` |
| Frontend framework | Vitest 4.1.10 + `@testing-library/react` 16.3.2 + jsdom 30.0.1 — config file does not exist yet (`frontend/vitest.config.ts` is a Wave 0 gap) |
| Python config file | `pyproject.toml` — `[tool.pytest.ini_options]`, `[tool.ruff]` (`:49-54`), `[tool.mypy]` `files = ["app", "eval", "scripts", "tests"]` (`:70`) `[VERIFIED: pyproject.toml:70]` — no `frontend/` in scope, confirming Pitfall integration-gotcha "nothing Python-side will ever lint or scan the frontend" |
| Quick run command (Python) | `uv run pytest -q -x -k <pattern>` |
| Full suite command (Python) | `uv run pytest -q` — **1,510 tests collected** this session `[VERIFIED: shell command run this session]` |
| Quick run command (frontend) | `npm run test -- <pattern>` (once Vitest config exists) |
| Full suite command (frontend) | `npm run test` |
| Combined pre-merge gate | `uv run ruff check .` + `uv run pytest -q` + `uv run mypy` (existing 3 CI jobs, unchanged) + `npm run check && npm run test && npm run build` (2 new CI jobs — `frontend`, `docker build`) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SHELL-01 | `/runs` React-rendered, no catch-all, served from `/static` | integration + hermetic | `uv run pytest tests/test_route_shadowing.py -x` | ❌ Wave 0 |
| SHELL-02 | Data present in HTML response, no post-load fetch | hermetic (parse `__INITIAL_DATA__` out of `response.text`) | `uv run pytest tests/test_react_page_render.py -x` | ❌ Wave 0 |
| SHELL-03 | JS-disabled operator reads `/runs`, submits demo form | hermetic (`TestClient` never executes JS — this IS the no-JS case) | `uv run pytest tests/test_dashboard.py -k demo_send_test -x` (existing test, must still pass unmodified) | ✅ existing |
| SHELL-04 | One dev command, one typecheck+lint command | manual (documented in README, not test-automatable) | `npm run dev`; `npm run check` | — |
| SHELL-05 | Deployed bundle == locally built bundle | CI job (docker build) + hermetic existence-check test | `docker build .` (new CI job); `uv run pytest tests/test_bundle_asset_exists.py -x` | ❌ Wave 0 |
| SHELL-06 | Broken TS build/lint/test blocks PR | CI trigger config (not a pytest) | inspect `.github/workflows/ci.yml`'s `frontend` job `on:` block includes `pull_request` | ❌ Wave 0 (CI config) |
| SHELL-07 | `/runs`/`/runs/{id}` separate response shapes | hermetic | `uv run pytest tests/test_schema_projection.py -x` | ❌ Wave 0 |
| SHELL-09 | `/ops` stays Jinja + script-free | hermetic, existing | `uv run pytest tests/test_ops_route.py::test_ops_page_has_no_script_or_polling -x` | ✅ existing, must stay green unmodified |
| SHELL-10 | Per-page `<title>`, single `aria-current`, tokens intact | hermetic, existing + 1 new pin | `uv run pytest tests/test_dashboard.py -k aria_current -x`; new `<title>` pin — ❌ Wave 0 (PITFALLS.md notes **zero** existing `<title>` test) |
| GUARD-01 | Inventory committed before conversion | CI check | `uv run pytest tests/test_inventory_completeness.py -x` | ❌ Wave 0 — this is the phase's first plan |
| GUARD-02 | Vacuous-vs-real absence distinguishable | mutation-pinned subset | `uv run pytest tests/test_safety_mutation_registry.py -x` (per-mutation, see D-22-11) | ❌ Wave 0 |
| GUARD-04 | New `RUN_COLS` column fails CI | hermetic | `uv run pytest tests/test_schema_projection.py::test_every_run_col_is_classified -x` | ❌ Wave 0 |
| GUARD-05 | No-HTML on service routes | hermetic | `uv run pytest tests/test_no_html_on_service_routes.py -x` | ❌ Wave 0 |
| GUARD-06 | No `fetch`/`axios` mutation | ESLint + hermetic text-scan | `npm run lint`; `uv run pytest tests/test_no_fetch_outside_poller.py -x` | ❌ Wave 0 |
| LIST-01 | Same columns/badges/order/empty state | Vitest component test (positive, exact-shape) | `npm run test -- RunsPage` | ❌ Wave 0 |
| LIST-02 | In-place badge updates, polling stops | Vitest (teardown-observable) | `npm run test -- usePoller` | ❌ Wave 0 |
| LIST-03 | Redirect to new run; queue-failure retry sentence | hermetic, existing (route-level) | `uv run pytest tests/test_dashboard.py -k demo_send_test -x` (existing — verify it still covers the `demo_queue_error` branch at `app/routes/demo.py:355`) | ✅ existing, re-verify coverage |
| LIST-04 | No 375px overflow, focusable scroll region | manual visual check (no automated 375px pin exists today, per PITFALLS.md) | manual, Chrome DevTools responsive mode | ❌ no automated pin exists in this repo for this property |

### Sampling Rate
- **Per task commit:** `uv run pytest -q -x <relevant file>` (Python); `npm run check && npm run test` (frontend, once toolchain exists)
- **Per wave merge:** full suite both sides — `uv run pytest -q` (1,510+ tests) and `npm run test`
- **Phase gate:** all 5 CI jobs green (`lint`, `test`, `typecheck`, `frontend`, `docker build`) before `/gsd-verify-work`, plus a live deploy check (`git rev-list --count origin/master..master` == 0, then hit the live `/runs` URL) per Claude's Discretion "Phase exit includes a real deploy"

### Wave 0 Gaps
- [ ] `frontend/vitest.config.ts` — framework install, `test.environment: "jsdom"`
- [ ] `frontend/` scaffold itself (`npm create vite@latest frontend -- --template react-ts`) — confirms the Vite manifest path (Open Question 1) as a side effect
- [ ] `tests/test_route_shadowing.py` — covers SHELL-01/GUARD-05's catch-all-absence half
- [ ] `tests/test_react_page_render.py` — covers SHELL-02
- [ ] `tests/test_bundle_asset_exists.py` — covers SHELL-05's hermetic half
- [ ] `tests/test_schema_projection.py` — covers SHELL-07/GUARD-04
- [ ] `tests/test_no_html_on_service_routes.py` — covers GUARD-05
- [ ] `tests/test_no_fetch_outside_poller.py` — covers GUARD-06's Python-side half
- [ ] `tests/test_inventory_completeness.py` — covers GUARD-01 (the phase's first plan's own deliverable)
- [ ] `tests/test_safety_mutation_registry.py` — covers GUARD-02's mutation-pinned subset (D-22-11)
- [ ] A `<title>`-per-page pin — PITFALLS.md notes zero existing coverage (`grep -rn "title>" tests/*.py` → 0 hits, not independently re-run this session but flagged as a known gap to close, not re-verify)
- [ ] A 375px-overflow automated pin — none exists today per PITFALLS.md; LIST-04 currently relies on manual verification only, matching this repo's existing precedent (quick task `260726-ugm` was manually verified, not automated)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | This dashboard is deliberately unauthenticated (a locked project characteristic, confirmed by the "no auth" framing throughout STACK/ARCHITECTURE/PITFALLS research and by there being no auth middleware in `app/main.py`) — not something this phase introduces or removes |
| V3 Session Management | No | No sessions exist |
| V4 Access Control | No | Single-operator, unauthenticated demo app — access control is out of scope for this milestone entirely |
| V5 Input Validation | Yes | Pydantic `RowProjection` DTOs with `extra="forbid"` (Pattern 3); FastAPI's own request validation for the unchanged mutation routes |
| V6 Cryptography | No | No new cryptographic surface in this phase |
| V7 Error Handling & Logging | Yes | The existing PII-safe failure-vocabulary reduction (`_safe_failure_presentation`, out of this phase's edit scope but consumed by the new DTO) must not be bypassed — GUARD-04's `EXCLUDED` set must classify `error_detail`/`last_error` consistently with the existing denylist |
| V12 Files & Resources | No (this phase) | Becomes relevant in Phase 24 (`/eval` fixture path-traversal sentinel) — flagged there, not here |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Wholesale DTO serialization exposing internal/PII fields (`business_id`, `reply_epoch`, `alias_candidates`, `extracted_data`, `reconciliation`, `decision` — all confirmed this session to survive the existing denylist, see Pattern 3) | Information Disclosure | `RowProjection.from_row` allowlist + the `RUN_COLS` classification drift test (GUARD-04) |
| `</script>`-injection breaking out of the embedded JSON data island | Tampering / XSS | `json_script()`'s character-escaping (Pattern 4), with a dedicated test constructing a hostile `business_name` |
| A catch-all route shadowing `/webhook/inbound`, `/health/*`, or `/internal/pump` | Denial of Service (silent — the provider believes delivery succeeded) | Structural absence of any catch-all/second mount (Pattern 2) + the route-shadowing test |
| `fetch`-based mutation losing the native `confirm()` guard or the `?resolution_superseded=1`/`?notice=` redirect-encoded state | Tampering (a destructive action proceeds without confirmation) | Native `<form method="post">` only (D-22-12), enforced by ESLint R1/R3 + the hermetic text-scan guard (GUARD-06, both halves) |
| `dangerouslySetInnerHTML` reintroducing an XSS surface for client-supplied text (not present in `/runs` itself — `business_name` is the only client-influenced text this phase renders, but the precedent must be set now) | Tampering / XSS | Never use `dangerouslySetInnerHTML`; React's default text-node escaping is sufficient and is the reason this pattern is safe by default — lint-ban it (`react/no-danger`) as a standing rule for Phase 23's larger conversation-thread surface |

## Sources

### Primary (HIGH confidence)
- Live repository reads this session, 2026-08-17: `app/main.py` (full, 19 lines), `app/routes/runs.py` (targeted, `:210-260`, `:845-920`), `app/db/repo/runs.py` (`RUN_COLS` at `:38-42`), `app/db/repo/demo.py` (`load_all_runs` signature + SELECT at `:210,230,245,257`), `app/routes/templating.py` (full, 59 lines), `app/routes/operator_feedback.py` (`:1-30`, `:84-90`, `:98-118`), `app/routes/demo.py` (`:150-355`), `app/templates/runs_list.html` (full, 129 lines), `app/templates/base.html` (full, 21 lines), `.gitignore` (`:5`), `.dockerignore` (full, 39 lines), `Dockerfile` (full, 61 lines), `.github/workflows/ci.yml` (full, 95 lines), `.github/workflows/eval.yml` (`:1-20`), `tests/test_design_tokens.py` (`:180-370` targeted), `tests/test_ops_route.py` (`:360-368`), `pyproject.toml` (`:40-70` targeted), `.planning/config.json`.
- Live registry reads this session: `npm view` against `typescript@6.0.3`, `typescript@7.0.2`(dist-tag check), `vite@8.2.1`, `@vitejs/plugin-react@6.0.5`, `vitest@4.1.10`, `react@19.2.8`, `react-dom@19.2.8`, `eslint-plugin-react-hooks`, `@testing-library/react@16.3.2`, `jsdom@30.0.1`, `openapi-typescript@7.13.0`, `typescript-eslint@8.67.0`, `eslint` — all 2026-08-17.
- `gsd-tools query package-legitimacy check --ecosystem npm` against all 13 frontend packages, this session.
- Shell verification: `grep -rl "\.text" tests/`, `grep -rlE "assert[^#]*\.text" tests/`, `wc -l tests/test_dashboard.py tests/test_needs_operator.py`, `uv run pytest -q --collect-only` (1,510 tests), `node --version`/`npm --version`/`docker --version`/`docker info`/`uv --version` — all this session.

### Secondary (MEDIUM confidence)
- `.planning/research/ARCHITECTURE.md`, `.planning/research/PITFALLS.md`, `.planning/research/FEATURES.md`, `.planning/research/STACK.md`, `.planning/research/SUMMARY.md` (all dated 2026-08-17, same day, HIGH-confidence four-pass research already grounded in live `file:line` reads at the time they were written) — used as the architectural backbone for this document, with every load-bearing citation independently re-verified this session (see Primary sources above) rather than trusted blind.
- `.planning/phases/22-frontend-foundation-runs-list/22-CONTEXT.md` and `22-DISCUSSION-LOG.md` — the locked implementation decisions (D-22-01 through D-22-17), reproduced verbatim in User Constraints per the downstream-consumer contract.
- Official Vite docs (`vite.dev/guide/backend-integration`, `vite.dev/config/build-options`) for the manifest-based asset-serving mechanism — carried from ARCHITECTURE.md, itself pinned MEDIUM by the `classify-confidence` seam's `webfetch` policy regardless of source quality; **not independently re-verified this session** (no build was run) — see Open Question 1.

### Tertiary (LOW confidence)
- `node:24-slim` Docker Hub tag existence and Node 24 Active-LTS status — carried from STACK.md's WebSearch + Docker Hub API check, not independently re-confirmed this session (Docker daemon was not running locally during this research pass).
- `@testing-library/jest-dom@7.0.1`, `@types/react@19.2.18`, `@types/react-dom@19.2.4`, `@types/node@26.2.0` exact versions — carried from STACK.md, not independently re-queried against the registry this session (flagged as Assumption A1).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every Core-table version and the TypeScript-6.0.3-compatibility finding independently re-verified against the live npm registry this session; a small number of Supporting-table versions carried from same-day prior research without independent re-query (flagged `[ASSUMED]`).
- Architecture: HIGH — every structural claim (route table, denylist contents, `RUN_COLS`, Dockerfile stage boundaries, CI trigger blocks, `runs_list.html`/`base.html` exact line boundaries) independently re-read/re-grepped this session with zero drift found from the four prior research passes or CONTEXT.md.
- Pitfalls: HIGH — the GUARD-01 file-count claim (the single most load-bearing number in this phase) was independently re-derived via shell command this session and matches PITFALLS.md's orchestrator addendum exactly (14 files via the `assert[^#]*\.text` AST-adjacent regex), while also demonstrating live why an AST walk (D-22-06) is required over a regex (17 vs 14 file counts diverge on multi-line asserts).
- Validation Architecture / Security Domain: MEDIUM — test-file paths listed are proposed (Wave 0 gaps), not yet existing; the actual test framework (pytest) and its current scale (1,510 tests) are HIGH-confidence measured facts.

**Research date:** 2026-08-17
**Valid until:** ~14 days for the npm-registry version pins (fast-moving ecosystem — Vite/React/ESLint/typescript-eslint all published within the last two weeks per the Package Legitimacy Audit's `too-new` flags); ~30 days for the codebase-structural facts (Dockerfile, CI, route table, RUN_COLS), which change only on a merged phase.
