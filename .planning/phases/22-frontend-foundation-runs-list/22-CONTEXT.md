# Phase 22: Frontend Foundation & Runs List - Context

**Gathered:** 2026-08-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 22 delivers the one-time shared infrastructure every v5 slice rides on (frontend toolchain, Docker node
stage, blocking CI job, allowlist DTO pattern, six guards, the committed test-assertion inventory) together
with a React-rendered `/runs` that deploys on its own.

18 requirements: SHELL-01..07, SHELL-09, SHELL-10, GUARD-01, GUARD-02, GUARD-04, GUARD-05, GUARD-06,
LIST-01..04.

**Requirement count is not a cost proxy.** Phase 22 holds 18 of 31 requirements but Phase 23 is by far the
larger build. Phase 22's cost is infrastructure risk, not UI risk. Do not rebalance the three phases
(`ROADMAP.md`, "Sizing is deliberately uneven").

**Not in this phase:** `/runs/{id}` (Phase 23), `/eval` (Phase 24), the closing diff proof (Phase 24), any
conversion of `/` or `/ops` (permanently excluded).

</domain>

<decisions>
## Implementation Decisions

All architecture-level choices were locked before planning (`PROJECT.md` Key Decisions, commit `a37e64c`;
`research/STACK.md` DECISION OVERRIDE) and are NOT reopened here. The decisions below are the
implementation-level questions that lock left open.

### Build, deploy, and dev toolchain

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

- **D-22-03: Local dev is the Vite dev server proxying to uvicorn.** With a fail-closed dev branch in
  `render_react_page()`. Browse `localhost:5173`; Vite's `server.proxy` forwards to uvicorn, and the server
  emits `@vite/client` plus the entry source path instead of manifest-hashed tags when a dev setting is on.
  This satisfies SHELL-04 literally ("hot reload that proxies to uvicorn") and gives real React Fast Refresh.
  **Named cost:** a second code path in the server-side template layer. Required mitigations: the setting
  defaults off, the Dockerfile never sets it, and a test asserts a default-settings render contains no
  `localhost` URL.
  — **Reversibility:** costly — removing the dev branch later means re-answering SHELL-04, and any leak of the
  dev setting into production serves script tags pointing at a developer's machine.

- **D-22-04: TypeScript types generate from a Pydantic-derived OpenAPI document, not from a new endpoint.**
  A script collects `app/schemas/` models via `model_json_schema()` into a `components.schemas`-only OpenAPI
  document and feeds it to `openapi-typescript`, CI-gated for staleness the same way `eval/chart.svg` is
  regenerated and diffed. No new HTTP surface is invented for an embedded-only DTO. The key-set assertion
  behind SHELL-07 and GUARD-04 works by parsing `__INITIAL_DATA__` out of `response.text`, so a route buys
  nothing for testability. (`GET /runs/{id}/status` separately gains a `response_model`, see D-22-11, and
  therefore appears in FastAPI's own OpenAPI natively.)

### Test-suite integrity (GUARD-01, GUARD-02)

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

- **D-22-09: GUARD-02 = convert by default, mutation-pin the safety subset.**
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

- **D-22-11: The safety-subset mutation registry is a new hermetic sibling.** It is run by `ci.yml`'s existing
  test job. Same AST-anchored idiom as `MUTATION_TARGETS` / `check_proof_inventory.py`, but its own registry and
  its own completeness check. These mutations are markup and DTO edits with no database in the loop, so they
  must NOT be wired into `concurrency-proof.yml`, where a missing `DATABASE_URL` silently converts a proof
  into a skip. That failure mode has already bitten this project.

### The `/runs` island, DTO shape, and poller

- **D-22-12: React owns one region of `runs_list.html` and nothing else.** That region is lines 64-115.
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

- **D-22-15: The three `js-` poller hooks are dropped on converted pages.** The guard is replaced, not
  re-pointed. The `js-` convention existed to stop someone deleting a `document.querySelector` target that
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

### Guard enforcement

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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone scope and locked architecture
- `.planning/ROADMAP.md` (Phase 22 section, plus "Sizing is deliberately uneven" and the phase notes for the
  planner) — the four locked architecture decisions, the untouchable fences, and the do-not-rebalance
  instruction.
- `.planning/REQUIREMENTS.md` — the 18 Phase 22 requirements, the Deferred and Out of Scope tables, and the
  measured scope facts. Treat its counts as superseded by the inventory pass (see the SC-1 note below).
- `.planning/PROJECT.md` (Current Milestone + Key Decisions rows tagged **v5:**) — the four locked decisions
  with their rationale and the recorded dissent that the server-rendered console may be the stronger artifact.

### Research (all four passes, 2026-08-17, grounded in live file:line reads)
- `.planning/research/SUMMARY.md` — the executive synthesis, the three resolved open decisions, the ranked
  traps, and the 11-item "Pull forward into Slice 1" list.
- `.planning/research/STACK.md` — the version matrix, and its trailing **DECISION OVERRIDE** section pinning
  TypeScript 6.0.3 + ESLint over TS 7.0.2 + Biome. Read the override, not just the body.
- `.planning/research/ARCHITECTURE.md` — `app/schemas/`, `RowProjection.from_row`,
  `UnclassifiedColumnError`, `render_react_page()`, the manifest loader, and the `frontend/` layout.
- `.planning/research/PITFALLS.md` — the 16 named preventions, 9 of which land in this phase.
- `.planning/research/FEATURES.md` — the per-page behavioral parity contract.

### Live source this phase touches or must not touch
- `app/routes/runs.py:855-882` — the `/runs` route; `:890-916` — `GET /runs/{id}/status`;
  `:220-246` — `_safe_run_for_browser`, the **denylist** the allowlist DTO replaces.
- `app/db/repo/runs.py:38-42` — `RUN_COLS`. `app/db/repo/demo.py` — `load_all_runs`'s list projection, which
  carries `created_at` while `RUN_COLS` does not. The two pages genuinely cannot share one shape.
- `app/routes/templating.py:18-59` — the single `Jinja2Templates` instance and the badge class/label maps.
- `app/templates/runs_list.html` — `:10-60` poller script, `:61` notice include, `:62` h1, `:64-115` the
  React region, `:117-128` the demo form.
- `app/templates/base.html` — the shell, the nav `aria-current` logic, the `<title>` block.
- `app/main.py:11` — the single `/static` mount. No second mount, no catch-all.
- `Dockerfile` (2 stages today; `:38` is `COPY . .`), `.gitignore:5` (`dist/`), `.dockerignore` (no `dist`).
- `.github/workflows/ci.yml` — 3 jobs, `:7-16` explains why `pull_request` is the gate.
- `tests/test_design_tokens.py:183`, `:191`, `:337`, `:352`, `:356-370` — the guards that must be widened
  before markup moves.
- `tests/test_ops_route.py:364` — pins `/ops` script-free. Never converted, never in the inventory's affected
  set.

### Repo conventions the new guards must follow
- `scripts/check_proof_inventory.py` and the `MUTATION_TARGETS` registry — the completeness-gate idiom the
  inventory guard and the mutation registry both copy.
- `docs/DURABILITY-PROOFS.md` — the PROOF-05 convention of shipping every proof with a demonstrated red run
  and a byte-identical revert.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`app/routes/templating.py:48-55`** (`badge_class_filter`, `badge_label_filter`): already the single owner
  of status vocabulary, and already called from JSON at `app/routes/runs.py:906-907`. The DTO builder calls
  the same functions; the Jinja filter registrations stay for `/` and `/ops`.
- **`GET /runs/{id}/status` (`app/routes/runs.py:890-916`)**: already returns exactly the seven volatile
  fields `RunStatusPoll` needs. Adding a `response_model` formalizes a shape that exists.
- **`.table-scroll` region pattern** (`runs_list.html:65`, `role="region" tabindex="0" aria-label=...`):
  LIST-04 and EVALUI-03 both need this; it already exists and was verified at a real 375px viewport in quick
  task `260726-ugm`. React reproduces the same markup, it does not invent a new one.
- **`_operator_notice.html` + `notice_label()`** (`app/routes/operator_feedback.py`): the allowlisted
  `?notice=` channel stays entirely in Jinja under D-22-12.
- **`app/static/style.css`**: the component library. React components apply the existing `.btn`, `.badge`,
  `.empty-state`, `state-pending-*` class names. No Tailwind, no CSS-in-JS, no re-declared tokens.

### Established Patterns
- **Fail-closed settings.** The pump token, `ALLOW_UNSIGNED_FIXTURES`, and the demo-operator refusal fence
  all default to the safe state and refuse rather than degrade. D-22-01 and D-22-03 follow this.
- **AST guards live in pytest, in the hermetic test job.** BOUND-01, the `BackgroundTasks` producer guard,
  the jobs CAS-only guard, `test_job_kind_drift.py`. New guards follow, and specifically do not go into
  `concurrency-proof.yml`.
- **Registry + completeness gate, wired at the selection layer.** `check_proof_inventory.py` exists because a
  hard-coded file list let proofs silently stop running. Both new registries copy that shape.
- **Generated artifact committed and diffed in CI.** `eval/chart.svg` is regenerated and `--check`ed. The
  generated inventory view and `api-types.ts` use the same staleness pattern.
- **Explicit column projection, never `SELECT *`.** `load_all_runs`'s comment states the rule. The allowlist
  DTO is the same discipline one layer up.

### Integration Points
- `app/schemas/` is new, sibling to `app/models/`. It is NOT under `app/db/`, so it does not breach the fence.
- `app/routes/templating.py` grows the manifest loader and `render_react_page()`.
- `frontend/` is new, sibling to `app/`; built output lands at `app/static/dist/` under the existing mount.
- `Dockerfile` gains a third stage; the runtime stage gains one `COPY --from=frontend` and one assertion.
- `.github/workflows/ci.yml` gains two jobs.

### Do NOT "fix" these while you are in here
- `load_all_runs` is unbounded (no `LIMIT`) and `clarification_round` is missing from `RUN_COLS`. Both are
  `app/db/` edits and both are out of scope. `ROADMAP.md` names them explicitly.

</code_context>

<specifics>
## Specific Ideas

### Correction to the planning docs, found while scouting

`REQUIREMENTS.md` records the GUARD-01 baseline as "**14** test files contain `.text` assertions" and
"`test_dashboard.py` = 85 `*.text` refs, split **42 presence vs 31 absence**". Measured live during this
discussion: **17** files under `tests/` contain `.text` (16 excluding `conftest.py`), and `test_dashboard.py`
carries **90** `.text` references. The split may have been derived with a narrower, unstated methodology.

**Consequence, and this is the decision:** the phase re-derives these numbers in the inventory pass and pins
what it measures. It does not copy `REQUIREMENTS.md`'s figures into a test or a success criterion. D-22-06
makes the guard assert completeness rather than counts precisely so this class of drift cannot recur.

### Two roadmap amendments this discussion produced

1. **SC-1's parenthetical is illustrative, not normative.** "the migration's baseline counts are pinned
   (`test_dashboard.py` 42 presence / 31 absence; `test_needs_operator.py` 5 / 7; plus the remaining 12
   files)" should be read as "the inventory records the measured counts per file". The criterion's real
   content, which stands unchanged, is that the inventory exists and precedes every conversion commit.

2. **SC-5's third sentence needs amending.** It reads: "The three `js-` poller hooks still resolve, they have
   zero CSS and look like dead markup, and deleting them would break this phase's own headline feature."
   That property was true of a `document.querySelector` poller. Under D-22-15 the hooks are removed on
   converted pages and the invariant is carried by a Vitest in-place-update test instead. The criterion's
   intent (the polling feature must not be silently broken by someone tidying markup) survives; its
   mechanism does not.

### Install-time verification required before the stack is treated as settled

`STATE.md` Operator Next Steps and `research/SUMMARY.md` both flag this: the peer ranges for Vite 8.2.1,
`@vitejs/plugin-react@6.0.5`, and Vitest 4.1.10 were validated against TypeScript **7.0.2**, not the pinned
**6.0.3**. Re-verify at install time, in this phase, before building on the matrix. Also unverified: the exact
Vite manifest path and the multi-entry `rollupOptions.input` config for three incrementally added entries.

### Pull forward for Phase 23, even though Phase 23 is the consumer

Build these here, against `/runs`'s single trivial form, so Phase 23 is composition rather than invention
under the pressure of 14 forms and 5 confirm sites:

- The `MutationForm` / `ConfirmForm` pair, with its `preventDefault()` falsifying-mutation Vitest test. The
  React footgun is that returning `false` from `onSubmit` does not cancel submission, which would make Reject
  a one-click irreversible action. Zero tests reference `onsubmit` or `confirm(` anywhere in `tests/` today.
- The `DecisionBanner` discriminated-union **shape** (not Phase 23's branch content). The real structure is
  6 mutually exclusive branches + 1 implicit no-banner fallthrough + 1 orthogonal `hours_changes` overlay.
  Modeling it as a flat switch silently drops the overlay.
- `RunStatusPoll` + `usePoller` (D-22-13, D-22-14).
- `json_script()` with its `</script>`-injection escaping and XSS test. Deferring it ships the injection
  surface unguarded on page one.

</specifics>

<deferred>
## Deferred Ideas

- **A batch `/runs` status endpoint.** One request per tick instead of N would be better network behavior, and
  it changes a wire shape this milestone claims to preserve, in the phase whose claim is that nothing changed.
  Backlog candidate, not Phase 22 work.
- **Playwright / real-browser E2E**, a `/` conversion, an `/ops` conversion, and client-side type generation
  against a live server in CI. All already recorded in `REQUIREMENTS.md` → Deferred / Out of Scope.
- **Adding `clarification_round` to `RUN_COLS`** and bounding `load_all_runs`. Both are `app/db/` edits behind
  the untouchable fence. Already in the milestone's deferred list.

</deferred>

---

*Phase: 22-Frontend Foundation & Runs List*
*Context gathered: 2026-08-17*
