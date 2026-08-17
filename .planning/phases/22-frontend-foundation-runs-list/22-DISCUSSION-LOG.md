# Phase 22: Frontend Foundation & Runs List - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md, this log preserves the alternatives considered.

**Date:** 2026-08-17
**Phase:** 22-frontend-foundation-runs-list
**Areas discussed:** Bundle presence in the test suite, GUARD-02 and where absence assertions land, GUARD-01 inventory artifact shape, the `/runs` island boundary

**Areas offered:** the same four. All four were selected.

**Not re-asked (locked before planning, `PROJECT.md` Key Decisions `a37e64c` + `research/STACK.md` DECISION
OVERRIDE):** MPA with React islands and no catch-all; server-embedded `__INITIAL_DATA__`; mutation forms stay
Jinja; TypeScript 6.0.3 + ESLint + `eslint-plugin-react-hooks`; the Vite/React/Vitest/openapi-typescript
version matrix; the Node 24 Docker stage landing `dist/` under the existing `/static` mount; separate list and
detail DTOs; no Tailwind, CSS-in-JS, component library, router, TanStack Query, Redux, Next.js, monorepo tool,
Playwright, or Storybook.

---

## Bundle presence in the test suite

Framing given before the questions: `TestClient` never executes JavaScript, so the question is not whether
tests can see React output (they never can) but whether pytest fails loudly or silently when no bundle exists.

### Q1: When `app/static/dist/.vite/manifest.json` is absent, what should `render_react_page()` do?

| Option | Description | Selected |
|--------|-------------|----------|
| Raise, with a committed test fixture manifest | Production hard-fails; tests render the boot-tag path deterministically without Node in the pytest job | ✓ |
| Raise always; add Node to the pytest job | Strongest fidelity, but every local `pytest -q` needs a built frontend and `ci.yml`'s test job grows npm | |
| Degrade to a bundle-less shell | Cheapest, and exactly the vacuity mechanism the milestone exists to prevent | |
| You decide | | |

### Q2: How should SHELL-05 be proven?

| Option | Description | Selected |
|--------|-------------|----------|
| Dockerfile `RUN` assertion + `.dockerignore` exclusion + a CI docker-build job | The Dockerfile assertion is load-bearing because it fires inside Render's own build | ✓ |
| CI docker-build job only | Catches it pre-merge; Render's build stays able to succeed with no bundle | |
| Dockerfile assertion only | No new CI job, but discovery moves to deploy time, the v4 Phase 21 shape | |
| You decide | | |

### Q3: How should local frontend development work, and does `render_react_page()` get a dev branch?

| Option | Description | Selected |
|--------|-------------|----------|
| Vite dev server proxying to uvicorn + a fail-closed dev branch | Satisfies SHELL-04 literally, real Fast Refresh, at the cost of a second code path in the template layer | ✓ |
| `vite build --watch`, no dev branch | Zero dev/prod divergence, but rebuild-on-save rather than HMR and it narrows SHELL-04's wording | |
| Both, dev branch off by default | Full coverage, carries option A's cost without removing option B's | |
| You decide | | |

### Q4: How do TypeScript types generate for a DTO that is only embedded, never served by a route?

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal OpenAPI doc from the Pydantic models, fed to `openapi-typescript` | No new HTTP surface; the key-set assertion works by parsing `__INITIAL_DATA__` | ✓ |
| A real JSON endpoint per converted page | FastAPI generates OpenAPI natively, at the cost of a new endpoint edging toward the rejected stranded-API shape | |
| Hand-written TS interfaces | Two sources of truth for one wire shape; the thing `openapi-typescript` was chosen to prevent | |
| You decide | | |

**Notes:** Not asked, settled by precedent: which CI file the new jobs live in, whether Vitest shares the
build job, and how the fixture manifest is kept from drifting from real Vite output.

---

## GUARD-02 and where absence assertions land

Framing given before the questions, verified against live source: locked decision 3 (mutation forms stay
Jinja) means `tests/test_dashboard.py:1384`, `:1394`, `:1395` stay meaningful for free, and `:523-526` (the
PII proofs) stay meaningful because the scrubbed `error_detail` travels inside `__INITIAL_DATA__`. The
genuinely vacuous class is content that moves into JSX, such as `:66` (`"No payroll runs yet"`). The real
work is a three-way classification by rendering layer, not a flat presence-vs-absence split.

### Q1: What is GUARD-02's concrete testable formulation?

| Option | Description | Selected |
|--------|-------------|----------|
| Convert by default, mutation-pin the safety subset | Positive exact-shape assertions make vacuity structurally impossible; named mutations reserved for PII, XSS, path traversal, and the Reject gate. Mirrors PROOF-05 | ✓ |
| Full mutation-pin registry for every reclassified assertion | Most literal reading of GUARD-02; cost lands mostly in Phase 23, already the 80% phase | |
| Positive-conversion only, no registry | Cheapest and defensible, gives up the demonstrated-able-to-fail evidence applied to every other safety claim since v2 | |
| You decide | | |

### Q2: Does classification and pinning happen all at once in Phase 22?

| Option | Description | Selected |
|--------|-------------|----------|
| Classify all in 22, pin per slice | Classification is the part that becomes impossible later; pinning belongs to the phase that owns the page | ✓ |
| Classify and pin everything in 22 | One pass, but pins written against markup Phase 23 replaces | |
| Classify per slice too | Least up-front work, violates the roadmap gate outright | |
| You decide | | |

### Q3: Where does the safety-subset mutation registry live, and which CI gate runs it?

| Option | Description | Selected |
|--------|-------------|----------|
| New sibling registry, hermetic, in `ci.yml`'s existing test job | Markup and DTO mutations need no database; keeping them out of `concurrency-proof.yml` avoids the missing-`DATABASE_URL` silent-skip that has already bitten this project | ✓ |
| Extend the existing `MUTATION_TARGETS` registry | One registry repo-wide, at the cost of inheriting a real-Postgres job and a skip path these pins should never have | |
| You decide | | |

### Q4: What happens to the three `js-` poller hooks and their guard?

| Option | Description | Selected |
|--------|-------------|----------|
| Drop them on converted pages; replace the guard with the real invariant | React has no `querySelector`, so keeping the classNames creates actually-dead markup. `test_design_tokens.py:356-370` deleted with written justification, replaced by a Vitest in-place-update test. Requires amending SC-5 | ✓ |
| Keep the classNames in JSX and re-point the guard | Preserves SC-5 verbatim, at the cost of guarded markup nothing reads | |
| Keep on `/runs` in Phase 22, revisit in Phase 23 | Defers the call across a phase boundary, into the phase with the least slack | |
| You decide | | |

**Notes:** All options in Q4 also carried the guard widening as a given (suffix allowlist at `:183` extended
to `.ts`/`.tsx`, globs at `:191`/`:337` extended to `frontend/src`, scanned-file count pinned against a
harvested inventory).

---

## GUARD-01 inventory artifact shape

Framing given before the questions: `REQUIREMENTS.md` pins "14 files / 85 `.text` refs / 42 presence / 31
absence", while live counts are 17 files containing `.text` and 90 refs in `test_dashboard.py` alone. A prose
baseline was wrong within a day of being written.

### Q1: What form does the committed inventory take?

| Option | Description | Selected |
|--------|-------------|----------|
| Machine registry as source of truth, generated markdown view | Registry keyed on file, line, captured assertion text, route, class, target layer, and a `replaced_by` field; markdown regenerated and diffed in CI like `eval/chart.svg` | ✓ |
| Machine registry only | One artifact, but the milestone's central gate becomes a dict a reviewer reads as code | |
| Markdown document only | Most readable, disqualified by the drift evidence above | |
| You decide | | |

### Q2: What does the inventory guard actually assert?

| Option | Description | Selected |
|--------|-------------|----------|
| Completeness: every `.text` assertion is classified | AST walk fails on any unregistered or unclassified assertion; counts become derived output. Same shape as `check_proof_inventory.py` | ✓ |
| Pinned counts | Legible in a success criterion, already demonstrably fragile, green on a wrong classification | |
| Both | Catches more, at the cost of a guard that reds for two unrelated reasons | |
| You decide | | |

### Q3: Which files are in scope?

| Option | Description | Selected |
|--------|-------------|----------|
| Walk every file containing `.text`; record explicit zeros with reasons | All 17; files with no assertion against the three routes get an entry stating zero affected and why. The v3 lesson that a guard proves nothing about what it does not scan | ✓ |
| Walk only files asserting against the three converted routes | Smaller and faster; the scope boundary then lives in whoever picked the list | |
| You decide | | |

### Q4: How is GUARD-01's gate enforced?

| Option | Description | Selected |
|--------|-------------|----------|
| Plan ordering plus a CI check | Inventory is plan 22-01, and a check fails if `frontend/src` exists without the registry or a page is converted while unclassified | ✓ |
| Plan ordering only | Zero tooling, holds only as long as every future phase remembers it | |
| You decide | | |

---

## The `/runs` island boundary

Framing given before the questions, from live `runs_list.html`: `:10-60` poller script, `:61` notice include,
`:62` h1, `:64-115` the `{% if runs %}` table and empty-state branch, `:117-128` the demo form.

### Q1: What does React own, and what stays Jinja?

| Option | Description | Selected |
|--------|-------------|----------|
| React owns `:64-115` only | One mount point; Jinja keeps the h1, the notice, and the form. The `?notice=` channel never round-trips through JSON and SHELL-10 is untouched. Gives Phase 23 a clean rule | ✓ |
| React owns the whole content block except the demo form | Fewer seams, at the cost of putting an operator-feedback surface behind the bundle | |
| Per-widget islands, table stays Jinja | Preserves the most markup assertions; two renderers interleaved in one table and a convention Phase 23 cannot use | |
| You decide | | |

### Q2: How should the list row DTO and the poll DTO relate?

| Option | Description | Selected |
|--------|-------------|----------|
| Poll DTO is a declared sub-shape of the list row DTO | `RunStatusPoll` (7 volatile fields) composed into `RunListRow`; `/runs/{id}/status` gains `response_model`, a legal edit since it is a GET, not a fenced mutation handler | ✓ |
| Two independent DTOs that overlap | Simpler to write, drift possible between embedded and polled shapes | |
| DTO carries raw status, TypeScript maps it | Smallest payload, duplicates `_BADGE_CLASS`/`_BADGE_LABEL` in TS, an explicit anti-feature | |
| You decide | | |

### Q3: What signature does `usePoller` get?

| Option | Description | Selected |
|--------|-------------|----------|
| Single-URL hook, one instance per in-flight row | Preserves today's network shape and per-row stop; Phase 23 uses one instance unchanged; keeps the `exhaustive-deps` surface small | ✓ |
| Table-level poller taking an array of run ids | One instance, simpler stop logic, grows state and dependencies for a case only one page has | |
| Add a batch status endpoint | Better network behavior, changes a wire shape the milestone claims to preserve | |
| You decide | | |

### Q4: How is GUARD-06 enforced, given `usePoller` legitimately calls `fetch` for GET?

| Option | Description | Selected |
|--------|-------------|----------|
| ESLint rule plus a hermetic pytest guard over `frontend/src` | Editor-time feedback plus an invariant that survives the frontend job being disabled or misconfigured. Matches BOUND-01 and the `BackgroundTasks` guard | ✓ |
| ESLint rule only | One mechanism, its force depends entirely on the new job existing and being required | |
| pytest guard only | Cannot be bypassed by frontend tooling changes, gives no editor feedback | |
| You decide | | |

---

## Claude's Discretion

The user chose "I'm ready for context" with these explicitly delegated:

- GUARD-04's internal-only column declaration mechanism.
- GUARD-05's no-HTML assertion for `POST /webhook/inbound`, `/health/*`, and `/internal/pump`, plus the
  no-catch-all assertion.
- Which CI file the `frontend` and `docker build` jobs live in.
- The SC-1 and SC-5 amendments this discussion produced.

Resolutions are recorded in CONTEXT.md under "Claude's Discretion" and "Specific Ideas".

## Deferred Ideas

- A batch `/runs` status endpoint (better network behavior, changes a preserved wire shape).
- Playwright / real-browser E2E, a `/` conversion, an `/ops` conversion, client-side type generation against
  a live server in CI. Already in `REQUIREMENTS.md` Deferred / Out of Scope.
- Adding `clarification_round` to `RUN_COLS`; bounding `load_all_runs`. Both `app/db/` edits behind the fence.
