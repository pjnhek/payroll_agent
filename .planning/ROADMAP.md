# Roadmap: Payroll Agent

## Milestones

- ✅ **v1.0 — MVP** (shipped 2026-06-25) — Email-driven payroll agent: messy email in, correct human-approved payroll out, every money-moving decision code-gated (deterministic, auditable, never guesses). 7 phases, deployed live on a free stack with a recorded demo. → [full archive](milestones/v1.0-ROADMAP.md) · [requirements](milestones/v1.0-REQUIREMENTS.md)
- ✅ **v2 — Production Hardening** (shipped 2026-07-07) — Took the working v1.0 MVP and made its money-logic and data layer genuinely production-grade — correct under real, messy, concurrent load, not just the demo path. 6 phases (7, 7.5, 8, 9, 10, 11), 16 requirements, scope discovered via an adversarial audit. → [full archive](milestones/v2-ROADMAP.md) · [requirements](milestones/v2-REQUIREMENTS.md) · [audit](milestones/v2-MILESTONE-AUDIT.md)
- ✅ **v3 — Production-Ready Codebase** (shipped 2026-07-13) — Made the codebase itself read as production-quality without changing a line of money behavior: enforced CI (ruff + full suite + `mypy --strict`, all blocking), the three god-files split into right-sized modules, the entire repo type-clean across 117 files, and provenance comments replaced with constraint-documenting ones behind a CI guard. 4 phases (12–15), 16/16 requirements, 227 commits. Found 3 real defects on the way — a lying eval chart, a path traversal, and a prompt-echo leak. → [full archive](milestones/v3-ROADMAP.md) · [requirements](milestones/v3-REQUIREMENTS.md) · [audit](milestones/v3-MILESTONE-AUDIT.md)
- ✅ **v4 — Durable Execution** (shipped 2026-07-20) — No accepted email is ever lost; every failure recovers automatically within ~30 minutes without a human noticing; a client is sent at most one confirmation per approved run, per epoch (exactly-once delivery is not claimed — Two Generals, not a library gap). Origin: an adversarial audit found the pipeline's `BackgroundTask` handoff was durable in memory only and the webhook blocked the event loop on a synchronous Resend fetch. 6 phases (16–21), 19/19 requirements, 84 plans, 566 commits; audit PASSED (19/19 reqs · 6/6 phases · 6/6 cross-phase seams · OPS-01 live UAT 2/2), and per Phase 21's four falsifiable proofs the durability property is demonstrated *able to fail*. → [full archive](milestones/v4-ROADMAP.md) · [requirements](milestones/v4-REQUIREMENTS.md) · [audit](milestones/v4-MILESTONE-AUDIT.md)
- 🚧 **v5 — React/TypeScript Operator Console** (started 2026-08-14; roadmap cut 2026-08-17) — Convert the three operator-facing dashboard pages (`/runs`, `/runs/{id}`, `/eval`) to React + TypeScript as three independently deployable vertical slices, without editing a single money-moving route. `/` and `/ops` stay Jinja on purpose; `/ops` stays script-free because the page an operator reads when everything else is broken must not depend on a bundle. 3 phases (22–24), 31 requirements. Motivation recorded honestly: portfolio signal for a specific role, not a defect in the Jinja dashboard — a cross-AI scope review argued the server-rendered console is the stronger artifact on engineering merit alone, and that dissent is on the record in `PROJECT.md`.

## Active Milestone: v5 — React/TypeScript Operator Console

**Goal:** `/runs`, `/runs/{id}`, and `/eval` are rendered by React from a built TypeScript bundle, with every
behavior the Jinja pages had preserved — and with a diff at close proving no money-moving code was touched.

**Shape:** This is not a "build a React app" milestone. All four research passes converged independently on the
same conclusion: it is **a leak-prevention and behavior-preservation exercise wearing a frontend-framework
costume.** Nothing new is delivered to an operator; what changes is how the console is built. The requirements
are therefore weighted toward preservation, guards, and leak prevention rather than capability.

**Locked architecture (decided 2026-08-17, before any code — `PROJECT.md` Key Decisions, commit `a37e64c`):**

1. **MPA with per-page React islands, never an SPA.** FastAPI keeps owning routing, mutations, and the
   303-redirect state machine. No client router. **No catch-all route** — the rejected catch-all's failure mode
   is severe: `/health/live` and `/internal/pump` returning 200+HTML would make Render mark a broken deploy
   healthy AND `pump.yml`'s `curl -f` go green while the durable queue is never drained, voiding v4's guarantee
   through a frontend routing choice.
2. **Initial page data embedded server-side** in a `<script type="application/json" id="__INITIAL_DATA__">`
   block, never fetched on mount — Render free cold-starts in ~1 min and a second round trip would put a
   spinner over the operator approval gate, which is the money surface.
3. **Mutation forms stay server-rendered** in the Jinja shell, including all five
   `onsubmit="return confirm(...)"` guards. React renders data islands only. This preserves the existing
   no-JavaScript property for free and keeps the confirm guards out of JSX, where returning `false` from
   `onSubmit` does **not** cancel submission.
4. **TypeScript 6.0.3 + ESLint + `eslint-plugin-react-hooks`**, overriding the research's TS 7.0.2 + Biome —
   `exhaustive-deps` is the rule that guards the poller's effect-dependency correctness, which is the
   milestone's riskiest behavior.

**Untouchable fences (asserted continuously, in every phase, not at the end):** `app/pipeline/`, `app/queue/`,
`app/db/`, `app/llm/`, and `app/email/` are unmodified; the 14 operator-facing mutation route handlers are
byte-identical; `/` and `/ops` stay Jinja and `/ops` stays free of any script tag, `setInterval`, or
meta-refresh. A per-slice diff-scope CI gate lands in Phase 22 and runs on every phase; SHELL-08's closing
diff proof is booked to Phase 24 only because that is where the milestone ends.

### ⚠️ Sizing is deliberately uneven — do NOT rebalance these phases

**A future planner reading three phases will be tempted to even them out. Don't.** Multiple independent
measures converge on the same split:

| Phase | Share of conversion cost | Why |
|-------|--------------------------|-----|
| 22 — `/runs` + foundation | Light page, **all** the one-time infrastructure | 8 list-page test GETs, 3 `js-` poller hooks, 1 form (no confirm guard). Its cost is toolchain + Docker node stage + CI job + DTO pattern + 9 of 16 guard preventions + the test-inventory baseline — **infrastructure risk, not UI risk.** |
| 23 — `/runs/{id}` | **~80% of the real conversion cost** | 44 of 60 test GETs, 14 of 18 server-rendered forms, **all 5** confirm guards, the 6-`elif` + 1-fallthrough + 1-overlay banner structure, all three delivery-review states, and 42 of the 131 markup assertions. |
| 24 — `/eval` | Genuinely small | 3 GETs, 1 form, static-artifact display, no poller, no mutation-guard logic. Its one real risk is that a "small easy last slice" waves through the highest-severity security pin it owns (the path-traversal sentinel). |

**Requirement count is not a cost proxy here.** Phase 22 carries 18 of the 31 requirements and Phase 23 carries
9 — yet Phase 23 is by far the larger build. Phase 22's requirements are mostly one-time mechanisms (a
toolchain, a CI job, a DTO pattern, six guards); Phase 23's nine are the actual conversion of the app's most
complex page. Size by the table above, not by the traceability tally.

### Phases

**Phase Numbering:** v5 continues the global phase sequence from v4 (last phase: 21). Integer phases (22–24)
are planned milestone work; decimal phases (e.g. 22.1) are reserved for urgent insertions.

- [ ] **Phase 22: Frontend Foundation & Runs List** - The toolchain, Docker node stage, blocking CI job, allowlist DTO pattern, six guards, and the committed test-assertion inventory land together with a React-rendered `/runs` that deploys on its own.
- [ ] **Phase 23: Run Detail — The Operator Gate** - `/runs/{id}` converts with every decision banner, all three delivery-review states, the conversation thread, the payroll disclosure, and all 14 mutations behaving exactly as before — the ~80% phase.
- [ ] **Phase 24: Eval View & Preservation Proof** - `/eval` converts, and a closing diff proves the milestone's central claim: no money-moving code was edited.

## Phase Details

### Phase 22: Frontend Foundation & Runs List

**Goal**: An operator uses a React-rendered `/runs` on the deployed service, and every shared mechanism the
other two slices ride on — build, deploy, CI, DTO allowlist, guards, test inventory — exists and has been
demonstrated able to fail.
**Depends on**: Nothing (first v5 phase)
**Requirements**: SHELL-01, SHELL-02, SHELL-03, SHELL-04, SHELL-05, SHELL-06, SHELL-07, SHELL-09, SHELL-10, GUARD-01, GUARD-02, GUARD-04, GUARD-05, GUARD-06, LIST-01, LIST-02, LIST-03, LIST-04
**Success Criteria** (what must be TRUE):

  1. **The committed inventory exists before any page is converted.** For each of the 14 test files carrying `.text` assertions, the inventory names which route(s) its assertions exercise and classifies each as presence or absence, and the migration's baseline counts are pinned (`test_dashboard.py` 42 presence / 31 absence; `test_needs_operator.py` 5 / 7; plus the remaining 12 files). No conversion commit in any phase precedes it.
  2. **An operator loads `/runs` on the deployed Render service** and sees the same columns, badges, ordering, and empty state the Jinja page showed, rendered by React from a bundle that came out of the Docker build — with the page's data already present in the HTML response, so a cold-started instance shows content rather than a spinner. `/runs/{id}`, `/eval`, `/`, and `/ops` all still work, unconverted.
  3. **An operator watching an in-flight run** sees its status, queue, and failure badges update in place with no full reload, and polling stops when the run settles; the same operator with JavaScript disabled still reads the list and submits the demo send-test form, landing on the newly created run (and a queue failure still shows the existing one-sentence retry message rather than claiming nothing was recorded).
  4. **A pull request is blocked before merge** by each of: a broken TypeScript build, a frontend lint or test failure, a mutation issued via `fetch`/`axios`, a new column in `RUN_COLS` that is neither exposed in a page's response shape nor named internal-only (identified by name), a catch-all route, an HTML response from `POST /webhook/inbound` / `/health/*` / `/internal/pump`, or an edit under `app/pipeline|queue|db|llm|email/`. Each guard is demonstrated red and byte-identically reverted. A developer runs one command for the hot-reloading dev server against uvicorn and one command to typecheck + lint.
  5. **Nothing that already worked is quietly lost.** `/ops` still has no script tag, `setInterval`, or meta-refresh; `/runs` keeps its per-page `<title>`, its single `aria-current="page"` nav match, and the `app/static/style.css` tokens with no color literal outside `:root`; and at 375px the page does not overflow while the wide table scrolls inside its own keyboard-reachable region. The three `js-` poller hooks still resolve — they have zero CSS and look like dead markup, and deleting them would break this phase's own headline feature.

**Plans**: 12 plans (6 waves)

Plans:
- [ ] 22-01-PLAN.md — GUARD-01: the committed test-assertion inventory gate (wave 1)
- [ ] 22-02-PLAN.md — Widen the design-token/a11y guards and pin the service-route structure before any markup moves (wave 1)
- [ ] 22-03-PLAN.md — Frontend toolchain scaffold, pinned installs, and the real Vite manifest shape (wave 2)
- [ ] 22-04-PLAN.md — TRACER: React-rendered `/runs` end to end from a Docker-built bundle (wave 3)
- [ ] 22-05-PLAN.md — SHELL-06 CI gates: frontend job, image-build job, diff-scope fence (wave 4)
- [ ] 22-06-PLAN.md — LIST-01/LIST-04 parity: badge components, full RunsPage, Vitest suite (wave 4)
- [ ] 22-07-PLAN.md — `RunStatusPoll` DTO, enforced response model, GUARD-04 column drift test (wave 4)
- [ ] 22-08-PLAN.md — Pulled-forward Phase 23 foundations: MutationForm/ConfirmForm, DecisionBanner union (wave 4)
- [ ] 22-09-PLAN.md — SHELL-04: Vite dev server proxying to uvicorn, fail-closed dev branch, README (wave 4)
- [ ] 22-10-PLAN.md — LIST-02 poller and GUARD-06's two independent enforcement paths (wave 5)
- [ ] 22-11-PLAN.md — Generated TypeScript DTOs and the staleness gate (wave 5)
- [ ] 22-12-PLAN.md — GUARD-02 safety mutation registry, LIST-03 preservation, inventory backfill (wave 6)

**UI hint**: yes

**SC-5 amendment (recorded at planning, 2026-08-17):** Success Criterion 5's third sentence — "The
three `js-` poller hooks still resolve…" — is superseded by D-22-15. Those hooks were a
`document.querySelector` affordance; React holds the badge in component state, so the hooks are
removed on the converted page and the criterion's intent (the polling feature must not be silently
broken by someone tidying markup) is carried by a Vitest in-place-update test owned by plan 22-10.
Success Criterion 1's parenthetical counts are illustrative, not normative (D-22-06): the inventory
records the counts it measures.

**Phase notes for the planner:**

- **GUARD-01 is a gate, not a task.** The route-attribution and presence/absence classification pass can only be done while the Jinja pages still render. Afterward, a vacuous absence assertion is indistinguishable from a valid one. **No conversion work in any phase begins before its inventory is committed.**
- **GUARD-02 is the softest of the 31 requirements** — it describes a property an engineer must be able to *determine* rather than a behavior a test asserts. **It needs a concrete, testable formulation during Phase 22 planning** (the research's shape: a mutation registry mirroring `MUTATION_TARGETS` / `test_proof_mutation_targets.py`, where deleting the React component that renders the guarded content must red at least one pin per Class-C absence assertion). Do not silently drop it, and do not treat it as already crisp.
- **SHELL-05 is deploy-blocking and the trap is verified latent today.** `.gitignore:5` is `dist/`, `.dockerignore` does not list `dist`, and `Dockerfile:38` is `COPY . .` — so a local `docker build` succeeds from the working tree while Render, building from the Git clone, ships a blank console with nothing failing anywhere. Resolve it here, not on first deploy.
- **SHELL-06 must trigger on `pull_request`, not only `push`.** `.github/workflows/eval.yml` triggers on `push: branches: ["master"]` + `workflow_dispatch` with **no** `pull_request`; `ci.yml` has it and its own comment explains that `pull_request` is what makes it a pre-merge gate. A frontend job copying `eval.yml`'s shape lets a broken build merge green and surface at Render deploy — the v4 Phase 21 "CI green, prod broken" shape. SHELL-05 and SHELL-06 are one coupled decision: if the bundle is built rather than committed, the CI build IS the only gate.
- **SHELL-07: `/runs` and `/runs/{id}` cannot share one response shape.** `created_at` is in the list projection (`app/db/repo/demo.py:230`) but **not** in `RUN_COLS` (`app/db/repo/runs.py:38-42`). They are genuinely different projections of the same table. The existing `_safe_run_for_browser` (`app/routes/runs.py:220`) is a **denylist** (`:244`, `safe_run.pop(field, None)`) — serializing it wholesale would expose `alias_candidates`, `reply_epoch`, `business_id`, and auto-expose any column later added to `RUN_COLS`. The allowlist replaces it.
- **Pull forward even though Phase 23 is the consumer:** the `MutationForm`/`ConfirmForm` pair with its `preventDefault()` falsifying-mutation test (built here against one trivial form so Phase 23 is composition, not invention under the pressure of 14 forms and 5 confirm sites), the `DecisionBanner` discriminated-union *shape*, and the `RunStatusPoll` DTO + `usePoller` hook.
- **Do not "fix" these while you are in here:** `load_all_runs` is unbounded (`app/db/repo/demo.py:257`, no `LIMIT`) and `clarification_round` is missing from `RUN_COLS`. Both are `app/db/` edits and both are out of scope.
- **Widen the guards before the first template disappears.** `tests/test_design_tokens.py` has hard-coded suffix allowlists and template globs that silently *narrow* as pages convert, and one test reads `runs_list.html` at module-import time — deleting that template first errors the whole file at collection, taking the WCAG contrast gates with it.

### Phase 23: Run Detail — The Operator Gate

**Goal**: `/runs/{id}` — the single human approval gate for money — is rendered by React with every banner,
delivery-review state, conversation, disclosure, and mutation behaving exactly as it did in Jinja.
**Depends on**: Phase 22
**Requirements**: GUARD-03, DETAIL-01, DETAIL-02, DETAIL-03, DETAIL-04, DETAIL-05, DETAIL-06, DETAIL-07, DETAIL-08
**Success Criteria** (what must be TRUE):

  1. **For every run state the app can produce, an operator sees exactly one decision banner** — or none, where the Jinja page showed none — and when hours changed across clarification rounds, that notice renders *alongside* whichever banner is showing rather than replacing it.
  2. **An operator on a run in delivery review sees the correct one of the three states** (clarification, confirmation, degraded "unavailable") with only the actions that state permits; and where a new confirmation cannot be authorized, **Reject is offered** instead of leaving "Mark delivered" — which CASes to `RECONCILED` — as the only exit.
  3. **An operator performs every mutation the run's status permits** — approve, reject, resolve, retrigger, simulate-reply, and each of the six delivery-review actions — and gets the same confirmation prompt, the same redirect target, and the same post-redirect notice as before, including the redirect-encoded `?resolution_superseded=1`. Cancelling any of the five confirmations submits nothing, and removing or neutralizing any one of them fails the suite.
  4. **An operator reads the run's emails as one chronological conversation** with inbound and outbound distinguished, no message body silently truncated, and record-only messages labelled as recorded rather than sent; expands the payroll-details disclosure and sees per-employee extraction, reconciliation, and computed paystub figures with each field's provenance badge matching the Jinja page; and on a failed run sees only diagnostic text that passes the existing validation — never a raw exception detail or an unredacted employee name.
  5. **An operator with the page open sees it re-sync when the run's status changes AND when only the queue label changes**, each proven by its own behavioral test; and a run that exhausted its clarification rounds reads a statement that is true without depending on data the page does not load.

**Plans**: TBD
**UI hint**: yes

**Phase notes for the planner:**

- **DETAIL-01: the `hours_changes` overlay is an always-checked slot, not a branch.** It is an independent `{% if %}` at `run_detail.html:196`, *after* the `elif` chain's `{% endif %}` at `:179`. The real structure is **6 mutually-exclusive `elif` branches + 1 implicit no-banner fallthrough + 1 orthogonal overlay** — not a flat 8-way switch. Modeling the banner as a single discriminated-union switch silently drops the overlay.
- **DETAIL-06 must cover BOTH halves of the reload trigger:** `data.status !== INITIAL_STATUS || data.queue_label !== INITIAL_QUEUE_LABEL` (`run_detail.html:76`). A queue-label-only change must re-sync. The in-source comment at `:39-44` records that a narrower earlier check missed `extracting → awaiting_reply`, so the clarification banner never appeared without a manual refresh. **One behavioral test per half. `exhaustive-deps` lint is the cheap guard; the behavioral tests are the real one.**
- **DETAIL-08 is the `clarification_round` conversion trap.** `RUN_COLS` omits the field, so `run_detail.html:118` always renders the literal fallback `3`. It is **latent, not a live defect** — that line is reachable only on the clarification-cap path, where the true count IS 3. Jinja resolves the missing key to falsy `Undefined`; Pydantic will not. **The decision is to rewrite the text to state the cap as a cap** — true without the data — NOT to add the column, which would breach the `app/db/`-untouched fence.
- **GUARD-03: zero tests reference `onsubmit` or `confirm(` anywhere in `tests/` today.** The five sites are `run_detail.html:143`, `:155`, `:282`, `:286`, `:320`. The React footgun is that returning `false` from `onSubmit` does **not** cancel submission — `preventDefault()` is required — which would make Reject a one-click irreversible action on a terminal status that `record_run_error` must not clobber. Register the deleted-`preventDefault()` mutation as this phase's falsifying mutation, per the repo's PROOF-05 convention.
- **The delivery-review Authorize/Reject mutual-exclusivity pin has no direct positive test today** — only a template comment. Add one.
- **Harvest the redirect-assertion inventory before rewriting markup tests.** The renderer-agnostic proofs (`response.headers["location"]`, `status_code == 303`) live in the same two files as the ~4,650 LOC of markup assertions that must be rewritten. A bulk delete-and-rewrite that throws the redirect assertions out with the HTML silently removes the only proof that native-form semantics still hold. Grep them into an inventory and pin the count first — the same move that closed v3's comment-hygiene blind spots.

### Phase 24: Eval View & Preservation Proof

**Goal**: `/eval` is React-rendered, and the milestone's central claim — that no money-moving code was edited —
is proven by diff rather than asserted.
**Depends on**: Phase 22 (Phase 23 sequenced before it, but not a hard prerequisite)
**Requirements**: SHELL-08, EVALUI-01, EVALUI-02, EVALUI-03
**Success Criteria** (what must be TRUE):

  1. **A visitor loads `/eval`** and sees the headline metrics and the committed `chart.svg` exactly as the Jinja page presented them — with the percentage arithmetic that currently lives in the template (`eval.html:16-21`) moved into the server-side response shape, not into TypeScript, and `/eval/chart.svg` itself untouched.
  2. **A visitor drills into a per-fixture result** and sees its scored outcome and fixture body, with the existing path-traversal protection intact — a crafted `../` fixture key is still refused — and the response exposing only the fields declared for the eval page rather than the whole `summary` dict.
  3. **A visitor on a narrow viewport** sees the wide results table scroll inside its own keyboard-reachable region without the page overflowing.
  4. **A diff over the full v5 commit range shows zero modifications** under `app/pipeline/`, `app/queue/`, `app/db/`, `app/llm/`, and `app/email/`, and the 14 operator-facing mutation handlers AST-diff clean; `/` and `/ops` are still Jinja and `/ops` is still free of any script tag, `setInterval`, or meta-refresh.

**Plans**: TBD
**UI hint**: yes

**Phase notes for the planner:**

- **This is the small phase that owns the highest-severity security pin.** The `/eval` path-traversal sentinel (`tests/test_dashboard.py:309`) is exactly the kind of thing a "small easy last slice" waves through. v3 found a path traversal that actually rendered a file from outside `eval/fixtures/` onto this page; do not let the conversion re-open it.
- **`/eval` has the same wholesale-serialization exposure as `/runs`,** from the other direction: `app/routes/dashboard.py:186` hands the whole `summary` dict to the template, including the `raw_body` the route injects. The allowlist DTO from Phase 22 applies here.
- **SHELL-08 is booked here for bookkeeping only.** It is asserted continuously by the per-slice diff-scope CI gate that lands in Phase 22 and runs in all three phases. Phase 24 owns the *closing* proof because Phase 24 is where the milestone ends — not because the fence goes unenforced until then. The same is true of SHELL-09 and SHELL-10, which are booked to Phase 22 (where the shared-shell and guard-scope risks are created) but hold in every phase.

## Backlog

Captured ideas not yet scheduled into a milestone live in [`backlog.md`](backlog.md). Notable candidates carried forward / deferred:

- ~~Next mini-milestone bundle (reclassified at v4 close): run-detail chronological-conversation UI rework, frontend progressive enhancement, paystub YTD columns, eval-chart restyle~~ — **retired 2026-07-20: a `/gsd-new-milestone` research pass verified all four items had already shipped** (Phase 20 + untracked quick task `260718-hie`, `91bc6ca`) and were simply never marked done; the one real residual gap (dashboard paystub-download YTD parity) was closed by quick task `260720-lba`. Historical detail preserved in `backlog.md` → "Next milestone (mini)" and in `PROJECT.md`.
- Real-email A5 threading verification (Path-2 inbound proven; the deep header-survival check stays a live-gate task, not a code change)
- Custom email domain (send FROM a real address) — documented upgrade path in README
- Additional Medicare 0.9% surtax modeling; SS wage-base straddle exactness (per-employee YTD Medicare ledger) — accepted limitations, tax-completeness features not hardening
- Schema-parity backlog: versioned/ordered migrations + migration-history table, hard deploy gate blocking Render deploy on drift — separate future milestone, needs paid plan or self-managed release step
- **10 dormant `integration`-marked test modules never execute in CI.** `concurrency-proof.yml` is the only workflow with a real Postgres and selects test files BY NAME (2 files); **12** files under `tests/` carry `@pytest.mark.integration`. Phase 16 (D-14) deliberately did NOT widen the gate to fix this — collecting all 12 at once would wake 10 live-DB modules against a shared Postgres with a destructive module-scope reset (`tests/conftest.py:74-93`), which is a large, unbudgeted change to smuggle inside a durability phase. Phase 16 instead adds a NARROW `queueproof` gate for new durability proofs. **The 10 dormant modules are a pre-existing gap and need their own dedicated work:** inventory and classify each, make it reliable under a shared Postgres (or isolate it), then bring it into CI. Files: `test_atomic_persist`, `test_claim_status`, `test_dashboard`, `test_gateway`, `test_ingest`, `test_persistence`, `test_seed_roundtrip`, `test_stuck_run_recovery`, `test_threading`, `test_webhook_dedup_race`. *(v5 note: `test_dashboard` is in this list and is also v5's largest markup-test cost center — the two concerns are separate and v5 does not own the CI-selection gap.)*
- v4 out-of-scope, schema-shaped for later if traffic ever changes: per-tenant fairness lanes, priority lanes, adaptive backpressure, circuit breakers (LLM/Resend), an N-concurrent-email load chart, operator authentication (`jobs.business_id`/`priority` are written but unread — each stays a future `ORDER BY` change, not a migration)
- v5 deferred (see `REQUIREMENTS.md` → Deferred): Playwright / real-browser E2E; a `/` landing conversion; client-side type generation against a live server in CI; adding `clarification_round` to `RUN_COLS` so the real per-run count can be displayed.

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Thin Foundation | v1.0 | — | Complete | 2026-06-21 |
| 2. Walking Skeleton | v1.0 | — | Complete | 2026-06 |
| 2.1. Deterministic Decisioning | v1.0 | — | Complete | 2026-06 |
| 3. Harden the Calc | v1.0 | — | Complete | 2026-06 |
| 4. The Eval, the Proof | v1.0 | — | Complete | 2026-06-22 |
| 5. Dashboard & Delivery | v1.0 | — | Complete | 2026-06-23 |
| 6. Real Integration & Ship | v1.0 | — | Complete | 2026-06-25 |
| 7. Money-Correctness Deepening | v2 | 2/2 | Complete | 2026-06-28 |
| 7.5. Clarification-Reply Field-Regression | v2 | 4/4 | Complete | 2026-06-28 |
| 8. Data-Layer Hygiene & Diagnostics | v2 | 3/3 | Complete | 2026-07-02 |
| 9. Atomic Data Integrity | v2 | 6/6 | Complete | 2026-07-04 |
| 10. Concurrency Proof | v2 | 2/2 | Complete | 2026-07-07 |
| 11. Clarification Round Machine & Alias Learning | v2 | 9/9 | Complete | 2026-07-07 |
| 12. CI Quality Gates | v3 | 4/4 | Complete    | 2026-07-09 |
| 13. Module Structure & Boundaries | v3 | 4/4 | Complete    | 2026-07-10 |
| 14. Full Type-Checking (mypy) | v3 | 10/10 | Complete    | 2026-07-10 |
| 15. Comment Hygiene & Deferred-Polish Triage | v3 | 11/11 | Complete    | 2026-07-13 |
| 16. Queue Substrate & Unblocked Webhook | v4 | 10/10 | Complete    | 2026-07-14 |
| 17. The Pump | v4 | 5/5 | Complete    | 2026-07-15 |
| 18. Failure Policy & Sweep Deletion | v4 | 14/14 | Complete    | 2026-07-16 |
| 19. Webhook Cutover & Durable Ingest | v4 | 12/12 | Complete    | 2026-07-17 |
| 20. Exactly-Once Send | v4 | 27/27 | Complete    | 2026-07-18 |
| 21. Durability Proofs & Ops View | v4 | 16/16 | Complete    | 2026-07-20 |
| 22. Frontend Foundation & Runs List | v5 | — | Not started | — |
| 23. Run Detail — The Operator Gate | v5 | — | Not started | — |
| 24. Eval View & Preservation Proof | v5 | — | Not started | — |
