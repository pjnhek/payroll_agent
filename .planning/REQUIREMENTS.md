# Requirements: Payroll Agent — v5 React/TypeScript Operator Console

**Defined:** 2026-08-17
**Milestone:** v5 — React/TypeScript Operator Console (Phases 22–24)
**Core Value:** A messy real-world payroll email goes in; a correct, human-approved payroll comes out — and every money-moving judgment call is deterministic, auditable decisioning that never guesses.

**How this milestone relates to that core value:** it does not advance it. This is a presentation-layer
conversion undertaken for portfolio signal, and the honest framing is that **its job is to change how the
operator console is built without changing anything it does.** A cross-AI scope review argued the existing
server-rendered console is the stronger artifact on engineering merit alone; that dissent is on the record in
`PROJECT.md`. Consequently the requirements below are weighted toward *behavior preservation and leak
prevention* rather than new capability — the research's own conclusion was that this is "a leak-prevention and
behavior-preservation exercise wearing a frontend-framework costume."

**Locked architecture (decided 2026-08-17, before planning — see `PROJECT.md` Key Decisions, commit `a37e64c`):**

1. **MPA with per-page React islands, never an SPA.** FastAPI keeps owning routing, mutations, and the
   303-redirect state machine. No client router. No catch-all route.

2. **Initial page data embedded server-side** in a `<script type="application/json" id="__INITIAL_DATA__">`
   block, not fetched on mount.

3. **Mutation forms stay server-rendered** in the Jinja shell, including all five
   `onsubmit="return confirm(...)"` guards. React renders data islands only.

4. **TypeScript 6.0.3 + ESLint + `eslint-plugin-react-hooks`**, overriding the research's TS 7.0.2 + Biome.

**Measured scope facts (verified against live source 2026-08-17; these supersede earlier estimates):**

- **15** `@router.post` routes repo-wide, no PUT/PATCH/DELETE anywhere. **14 operator/demo-facing** (11 in
  `app/routes/runs.py`, 3 in `app/routes/demo.py`); `POST /webhook/inbound` is the 15th and is out of scope.

- **14** test files contain `.text` assertions — not the 2 the milestone originally scoped.
  `test_dashboard.py` = 2,296 LOC / 295 asserts / 85 `*.text` refs, split **42 presence vs 31 absence**.
  `test_needs_operator.py` = 2,223 LOC / 167 asserts / 8 real markup refs, split **5 presence vs 7 absence**.
  `test_phase20_clarification_review.py` = 30 `.text` asserts / 11 `client.get`. `test_reply_redelivery.py` = 4 / 4.

- **38 absence assertions** (`assert X not in ...text`) are the conversion's silent-failure surface, and they
  skew toward the safety proofs (PII scrubbing, XSS, path traversal, the delivery-review Reject gate).

- **Zero** tests reference `onsubmit` or `confirm(` anywhere in `tests/`.
- The `/runs/{id}` decision banner is **6 mutually-exclusive `elif` branches + 1 implicit no-banner
  fallthrough + 1 orthogonal `hours_changes` overlay** (`run_detail.html:99-208`), not a flat 8-way switch.

- Delivery review has **three** renderable states (clarification, confirmation, degraded "unavailable"), not two.

---

## v5 Requirements

### Shell & Toolchain (foundation — Slice 1)

- [x] **SHELL-01**: An operator loads `/runs`, `/runs/{id}`, and `/eval` and the pages are rendered by React from a built bundle, served from the existing `/static` mount, with no catch-all route added to the app.
- [ ] **SHELL-02**: An operator's browser receives each page's data already present in the HTML response — no post-load fetch is required before payroll data is visible, so a cold-started instance shows content rather than a spinner.
- [ ] **SHELL-03**: An operator with JavaScript disabled can still read every converted page's server-rendered shell and submit every mutation form on it.
- [ ] **SHELL-04**: A developer runs one command to start a local dev server with hot reload that proxies to uvicorn, and one command to typecheck and lint the frontend.
- [ ] **SHELL-05**: A deployed Render build serves the same built assets a local `docker build` serves — the build output cannot be present locally and absent in the deployed image.
- [ ] **SHELL-06**: A broken TypeScript build, a lint failure, or a failing frontend test blocks a pull request from merging, in the same way `ruff`/`pytest`/`mypy --strict` already do.
- [ ] **SHELL-07**: A JSON response for a converted page exposes only fields explicitly declared for that page; `/runs` and `/runs/{id}` have separate response shapes rather than one shared shape.

### Test-Suite Integrity (foundation — Slice 1)

- [x] **GUARD-01**: Before any page is converted, every `.text` assertion across all 14 affected test files is attributed to the route it exercises and classified as presence or absence, and that inventory is committed as the migration's baseline.
- [ ] **GUARD-02**: An engineer can tell, for any absence assertion that still passes after conversion, whether it passes because the guarded content is genuinely absent or because the assertion can no longer see it.
- [ ] **GUARD-03**: All five destructive-action confirmation guards are covered by tests, so removing or neutralizing one fails the suite.
- [ ] **GUARD-04**: Adding a column to `RUN_COLS` without either exposing it in a page's response shape or naming it internal-only fails CI, identifying the column by name.
- [x] **GUARD-05**: `POST /webhook/inbound`, `/health/*`, and `/internal/pump` never return HTML, and a change that makes them do so fails CI.
- [ ] **GUARD-06**: A mutation issued via `fetch` or `axios` from frontend source fails CI, so the native-form-POST decision is enforced rather than trusted.

### Runs List (Slice 1)

- [ ] **LIST-01**: An operator sees the runs list with every column, badge, and empty state the Jinja page showed, in the same order.
- [ ] **LIST-02**: An operator watching an in-flight run sees its status, queue, and failure badges update in place without a full page reload, and the polling stops when the run settles.
- [ ] **LIST-03**: An operator who submits the demo send-test form is redirected to the newly created run, and a queue failure surfaces the existing one-sentence retry message rather than claiming nothing was recorded.
- [ ] **LIST-04**: An operator reading the list on a 375px-wide viewport sees no horizontal page overflow, and the wide table scrolls inside its own keyboard-reachable region.

### Run Detail (Slice 2)

- [ ] **DETAIL-01**: An operator sees exactly one decision banner for a run's state, or none where the current page shows none, and the hours-changed notice renders alongside whichever banner is showing rather than replacing it.
- [ ] **DETAIL-02**: An operator sees the correct one of the three delivery-review states, with only the actions that state permits — and where a new confirmation cannot be authorized, Reject is offered instead of leaving "Mark delivered" as the only exit.
- [ ] **DETAIL-03**: An operator reads the run's emails as one chronological conversation, with inbound and outbound distinguished, no message body silently truncated, and record-only messages labeled as recorded rather than sent.
- [ ] **DETAIL-04**: An operator expands the payroll details disclosure and sees per-employee extraction, reconciliation, and computed paystub figures, with each field's provenance badge matching what the Jinja page showed.
- [ ] **DETAIL-05**: An operator performs every mutation the run's status permits — approve, reject, resolve, retrigger, simulate-reply, and each delivery-review action — with the same confirmation prompts, the same redirect targets, and the same post-redirect notices as before.
- [ ] **DETAIL-06**: An operator on a run whose status changes while the page is open sees the page re-sync, including when only the queue label changed and the status did not.
- [ ] **DETAIL-07**: An operator viewing a failed run sees only diagnostic text that passes the existing validation, and never a raw exception detail or an unredacted employee name.
- [ ] **DETAIL-08**: An operator on a run that exhausted its clarification rounds reads a statement that is true without depending on data the page does not load.

### Eval View (Slice 3)

- [ ] **EVALUI-01**: A visitor sees the headline eval metrics and the committed chart exactly as the Jinja page presented them.
- [ ] **EVALUI-02**: A visitor drills into a per-fixture result and sees its scored outcome and fixture body, with the existing path-traversal protection intact.
- [ ] **EVALUI-03**: A visitor reading `/eval` on a narrow viewport sees the wide results table scroll inside its own keyboard-reachable region without the page overflowing.

### Preservation Invariants (all slices)

- [ ] **SHELL-08**: `app/pipeline/`, `app/queue/`, `app/db/`, `app/llm/`, and `app/email/` are unmodified at milestone close, and a diff proves it.
- [x] **SHELL-09**: `/` and `/ops` remain Jinja2, and `/ops` remains free of any script tag, `setInterval`, or meta-refresh.
- [x] **SHELL-10**: Every converted page keeps its per-page `<title>`, its single `aria-current="page"` nav match, and the design tokens from `app/static/style.css` — no color literal is introduced outside `:root`.

---

## Deferred (not in this milestone)

### Frontend depth

- **Playwright / real-browser E2E.** The behavior most worth proving in a browser is the native form-POST → 303 chain, which the existing `pytest` + `TestClient` suite already exercises server-side. Revisit only if a genuine cross-boundary regression appears.
- **A `/` (landing) conversion.** Deliberately excluded; it is a marketing surface, not an operator surface.
- **An `/ops` conversion.** Permanently excluded, not deferred — see Out of Scope.
- **Client-side type generation wired to a live server in CI.** `openapi-typescript` runs as a staleness gate in this milestone; generating against a running instance is a later refinement.

### Pre-existing gaps surfaced but not owned here

- **`clarification_round` absent from `RUN_COLS`.** The banner text is being rewritten so it is true without the data (DETAIL-08). Adding the column so the real per-run count can be displayed is a separate, `app/db/`-touching change.
- **The 10+ dormant `integration`-marked test modules that never execute in CI.** A pre-existing gap with its own inventory in `backlog.md`; unrelated to this conversion.

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Converting `/ops` to React | The page an operator reads when everything else is broken must not depend on a JS bundle. Permanently Jinja and permanently script-free; pinned by `tests/test_ops_route.py:364`. |
| Converting `/` (landing) | Not an operator surface. Its `<noscript>` fallback at `index.html:53` is on a page that is not converted, so this milestone must not claim credit for preserving it. |
| A client-side router | FastAPI owns all three URLs; mutations are already full browser navigations, so a router buys nothing and costs a re-hydrate per approve/reject on a cold-startable instance. |
| `fetch`-based mutations | Loses the redirect-encoded `?resolution_superseded=1` (`app/routes/runs.py:626`), the redirect-to-new-run at `app/routes/demo.py:252`/`:352`, and the five native `confirm()` guards. |
| A catch-all SPA fallback route | `/health/live` and `/internal/pump` returning 200+HTML would make Render mark a broken deploy healthy AND `pump.yml`'s `curl -f` go green while the durable queue is never drained — v4's durability guarantee silently voided by a routing choice. |
| Optimistic UI on any mutation | These are money-moving actions guarded by a `claim_status` CAS the backend was deliberately hardened around. Showing success before the server confirms it is the one UI pattern this project cannot have. |
| A cross-page client cache of run state | Can display stale payroll status at the approval gate. |
| Tailwind, CSS-in-JS, or a component library | `tests/test_design_tokens.py` parses the live `:root` and recomputes WCAG contrast from actual hex values, enforcing one-definition-per-color. A utility-class or per-component color model fragments exactly that single source of truth. |
| Redux or any global state manager | No cross-page client state exists to manage. |
| Next.js / SSR framework | Would run a second server framework inside a single Render container. |
| A monorepo tool | One `frontend/` directory, three entry points. |
| Storybook | No consumer. |
| Biome | Overridden in favor of ESLint + `eslint-plugin-react-hooks`; `exhaustive-deps` is the guard for the poller's effect-dependency correctness. |
| Any change to the 14 operator-facing mutation route handlers | The milestone's auditable claim is that no money-moving route was edited. |

---

## Traceability

Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SHELL-01 | Phase 22 | Complete |
| SHELL-02 | Phase 22 | Pending |
| SHELL-03 | Phase 22 | Pending |
| SHELL-04 | Phase 22 | Pending |
| SHELL-05 | Phase 22 | Pending |
| SHELL-06 | Phase 22 | Pending |
| SHELL-07 | Phase 22 | Pending |
| SHELL-08 | Phase 24 | Pending |
| SHELL-09 | Phase 22 | Complete |
| SHELL-10 | Phase 22 | Complete |
| GUARD-01 | Phase 22 | Complete |
| GUARD-02 | Phase 22 | Pending |
| GUARD-03 | Phase 23 | Pending |
| GUARD-04 | Phase 22 | Pending |
| GUARD-05 | Phase 22 | Complete |
| GUARD-06 | Phase 22 | Pending |
| LIST-01 | Phase 22 | Pending |
| LIST-02 | Phase 22 | Pending |
| LIST-03 | Phase 22 | Pending |
| LIST-04 | Phase 22 | Pending |
| DETAIL-01 | Phase 23 | Pending |
| DETAIL-02 | Phase 23 | Pending |
| DETAIL-03 | Phase 23 | Pending |
| DETAIL-04 | Phase 23 | Pending |
| DETAIL-05 | Phase 23 | Pending |
| DETAIL-06 | Phase 23 | Pending |
| DETAIL-07 | Phase 23 | Pending |
| DETAIL-08 | Phase 23 | Pending |
| EVALUI-01 | Phase 24 | Pending |
| EVALUI-02 | Phase 24 | Pending |
| EVALUI-03 | Phase 24 | Pending |

**Coverage:**

- v5 requirements: 31 total
- Mapped to phases: 31 ✓ (every requirement maps to exactly one phase; no orphans, no duplicates)
- Unmapped: 0

**Per-phase distribution** (requirement count is NOT a cost proxy — see the sizing note below):

| Phase | Requirements | Count |
|-------|--------------|-------|
| Phase 22 — Frontend Foundation & Runs List | SHELL-01…07, SHELL-09, SHELL-10, GUARD-01, GUARD-02, GUARD-04, GUARD-05, GUARD-06, LIST-01…04 | 18 |
| Phase 23 — Run Detail (The Operator Gate) | GUARD-03, DETAIL-01…08 | 9 |
| Phase 24 — Eval View & Preservation Proof | SHELL-08, EVALUI-01…03 | 4 |

**SHELL-08 / SHELL-09 / SHELL-10 are milestone-wide preservation invariants.** Each is booked to exactly one
phase for traceability — SHELL-08 to Phase 24 because that is where the closing diff proof is produced,
SHELL-09 and SHELL-10 to Phase 22 because that is where the shared-shell and guard-scope risks are created —
but all three are asserted **continuously, in every phase**, via the per-slice diff-scope CI gate and the
widened design-token / a11y guards that land in Phase 22.

---

## Sizing note for the roadmapper

The three slices are **not** equal thirds, and must not be planned as such. Slice 2 (`/runs/{id}`) carries
roughly 80% of the real conversion cost by several independent measures — 44 of 60 test GETs, 14 of 18 forms,
all 5 confirm guards, the 6+1+1 decision-banner structure, and all three delivery-review states. Slice 1
carries a comparatively light page plus the entire one-time toolchain, Docker, CI, DTO-pattern, and guard cost.
Slice 3 (`/eval`) is genuinely small: static-artifact display, no poller, no mutation-guard logic.

---
*Requirements defined: 2026-08-17*
*Last updated: 2026-08-17 — traceability populated at roadmap creation (Phases 22-24)*
