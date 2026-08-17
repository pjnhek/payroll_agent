# Architecture Research

**Domain:** React + TypeScript presentation layer grafted onto a shipped, single-container FastAPI + Jinja2 app (v5 Operator Console, Phases 22-24)
**Researched:** 2026-08-17
**Confidence:** HIGH on every codebase integration point (read directly from live source at the `file:line` cited). MEDIUM on Vite mechanics (cited to official vite.dev docs, but the `classify-confidence` seam pins `webfetch` at LOW regardless of source, so the two Vite facts below are marked CONFIRM-at-plan-time). No claim here rests on remembered library behavior.

> **Line-number drift notice.** `PROJECT.md:211-214` cites `_safe_run_for_browser` at `app/routes/runs.py:224` and its denylist at `:246`. Against live source today those are **`app/routes/runs.py:220`** (def) and **`app/routes/runs.py:232-244`** (the `raw_fields` set + the pop loop). The finding is confirmed; only the line numbers moved. Every `file:line` in this document was read today.

---

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              BROWSER                                          │
│  Jinja-only pages          React-rendered pages (MPA, one bundle per page)    │
│  ┌──────────┐ ┌────────┐   ┌────────────┐ ┌───────────────┐ ┌─────────────┐  │
│  │ /  index │ │ /ops   │   │ /runs      │ │ /runs/{id}    │ │ /eval       │  │
│  │  (Jinja) │ │(Jinja, │   │ runs.tsx   │ │ runDetail.tsx │ │ evalView.tsx│  │
│  │          │ │ NO js) │   │            │ │               │ │             │  │
│  └────┬─────┘ └───┬────┘   └──────┬─────┘ └───────┬───────┘ └──────┬──────┘  │
│       │           │               │               │                │          │
│       │  ONE stylesheet: /static/style.css (293 CSS custom properties)         │
│       │  ONE nav: base.html:9-16   ONE notice vocabulary: server-side          │
└───────┼───────────┼───────────────┼───────────────┼────────────────┼──────────┘
        │           │               │  native form POST → 303 → full navigation │
        │           │               │  GET /runs/{id}/status  (2s poll, JSON)   │
┌───────┴───────────┴───────────────┴───────────────┴────────────────┴──────────┐
│                     FastAPI (app/main.py — 20 lines, unchanged shape)          │
│  mount /static (main.py:11)  +  7 APIRouters (main.py:13-19)                   │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │ NEW: app/routes/templating.py grows render_react_page() + json_script()  │ │
│  │      one Jinja shell react_page.html extends base.html                   │ │
│  │      reads app/static/dist/.vite/manifest.json → hashed <script>/<link>  │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │ NEW: app/schemas/  — per-route Pydantic response DTOs, allowlist-by-     │ │
│  │      construction (RowProjection.from_row raises on unclassified key)    │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│  20 mutation routes UNCHANGED (form POST + 303 + ?notice= / ?superseded=1)     │
├───────────────────────────────────────────────────────────────────────────────┤
│  OUT OF SCOPE, UNTOUCHED: app/pipeline/ app/queue/ app/db/ app/llm/ app/email/ │
└───────────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | New / Modified | Anchor |
|-----------|----------------|----------------|--------|
| `app/main.py` | Router assembly + `/static` mount. **Adds nothing.** No catch-all, no second mount. | **unchanged** | `app/main.py:11-19` |
| `app/routes/templating.py` | Single `Jinja2Templates` instance + badge filters. Grows the Vite manifest loader, `render_react_page()`, and `json_script()`. | **modified** | `app/routes/templating.py:10`, `:18-45`, `:58-59` |
| `app/templates/react_page.html` | The one Jinja shell that emits boot tags. `{% extends "base.html" %}`. **The reason `/ops` never gets a script tag.** | **new** | extends `app/templates/base.html:1-22` |
| `app/schemas/` | Per-route response DTOs. Allowlist enforced by construction, not convention. | **new package** | consumes `app/db/repo/runs.py:38-42` |
| `frontend/` | Vite + React 19 + TS workspace. Three page entries, shared components, no router. | **new** | — |
| `app/routes/runs.py` | Read routes swap `TemplateResponse(runs_list.html/run_detail.html)` for `render_react_page(...)`. Mutation handlers **byte-identical**. | **modified (read routes only)** | `app/routes/runs.py:855-882`, `:1232-1354` |
| `app/routes/dashboard.py` | `/eval` swaps its template call. `/` and `/eval/chart.svg` untouched. | **modified (`eval_view` only)** | `app/routes/dashboard.py:150-192`; untouched `:67-142`, `:200-211` |
| `Dockerfile` | Gains a node stage; the python builder copies `dist` in; **runtime stage unchanged**. | **modified** | `Dockerfile` builder stage, `COPY . .` line |
| `.github/workflows/ci.yml` | Gains a **fourth** blocking job: `frontend`. | **modified** | `.github/workflows/ci.yml` (3 jobs today: `lint`, `test`, `typecheck`) |
| `app/static/style.css` | **Unchanged.** The token system is consumed by class name, never ported. | **unchanged** | `app/static/style.css:7-60` (`:root`), 293 `--` declarations total |
| `app/templates/ops.html`, `index.html`, `base.html` | **Unchanged.** | **unchanged** | pinned by `tests/test_ops_route.py:364` |

---

## Recommended Project Structure

```
frontend/                          # NEW — the entire node surface lives here
├── package.json                   # + package-lock.json (npm ci in Docker)
├── vite.config.ts                 # manifest:true, base:'/static/dist/', 3 inputs
├── tsconfig.json                  # strict:true — the TS analogue of mypy --strict
├── eslint.config.js               # the three structural bans (R1/R3/R7 below)
├── vitest.config.ts
└── src/
    ├── entries/
    │   ├── runs.tsx               # slice 1 — mounts <RunsPage>
    │   ├── runDetail.tsx          # slice 2
    │   └── evalView.tsx           # slice 3
    ├── generated/
    │   └── dtos.d.ts              # COMMITTED, gated by --check (eval/chart.svg pattern)
    ├── boot/
    │   └── pageData.ts            # reads <script id="page-data">, typed by dtos.d.ts
    ├── components/
    │   ├── MutationForm.tsx       # THE ONLY file allowed to emit a <form>
    │   ├── ConfirmForm.tsx        # MutationForm + native confirm() guard
    │   ├── StatusBadge.tsx        # renders server-supplied badge_class/badge_label
    │   └── OperatorNotice.tsx     # mirrors _operator_notice.html markup exactly
    ├── hooks/
    │   └── usePoller.ts           # the ONE legitimate fetch() in the codebase
    └── pages/
        ├── RunsPage.tsx           # slice 1
        ├── RunDetailPage.tsx      # slice 2
        └── EvalPage.tsx           # slice 3

app/schemas/                       # NEW — presentation DTOs, deliberately NOT app/models/
├── __init__.py                    # ALL_DTOS registry (feeds schema generation)
├── _projection.py                 # RowProjection + UnclassifiedColumnError
├── runs_list.py                   # RunListItem, RunsListPage
├── run_detail.py                  # RunDetail, DecisionBanner (discriminated), ...
├── run_status.py                  # RunStatusPoll  ← shared by poller + initial data
├── eval_view.py                   # EvalSummary, EvalFixtureRow
└── schemas.json                   # COMMITTED JSON Schema, gated by a pytest --check

app/templates/react_page.html      # NEW — the only template that emits boot tags
app/static/dist/                   # BUILD OUTPUT — gitignored, dockerignored, baked in image
```

### Structure Rationale

- **`app/schemas/` is a new package, not `app/models/` and not inline in the routers.** `app/models/` holds the domain contracts the eval imports (`contracts.py`, `roster.py`, `status.py`) — PROJECT.md calls that the load-bearing DRY seam of the whole thesis (`PROJECT.md:292`). Wire DTOs are presentation and must be free to change shape without touching anything `eval/run_eval.py` imports; putting them in `app/models/` would let a UI edit ripple into the eval's import surface. Inline-in-router is worse: `app/routes/runs.py` is already **1,534 lines** and is the largest remaining router after v3's god-file split (`PROJECT.md:44-46`) — adding ~200 lines of schema to it reverses that milestone.
- **`frontend/` is a sibling, not nested under `app/`.** `app/` is Python-only today and is what `mypy --strict` walks over 117 files. A `node_modules` inside it invites both toolchains to scan each other's tree.
- **Build output lands at `app/static/dist/`, under the existing mount.** `app/main.py:11` already mounts `/static` → `app/static`. Hashed assets are therefore served by a mount that **already exists** — no second `app.mount()`, no new route, and nothing added to the shadowing surface. This is the single most important structural choice in the document.

---

## Architectural Patterns

### Pattern 1: Multi-page app with React-rendered pages (the recommendation)

**What:** Five URLs, five server-rendered HTML documents. Three of them (`/runs`, `/runs/{id}`, `/eval`) are a thin Jinja shell whose `{% block content %}` is a single `<div id="root">` plus an embedded JSON island plus the boot tags for **that page's own bundle**. `/` and `/ops` render Jinja as today. There is no client-side router, no `history.pushState`, and no single document that outlives a navigation.

This is precisely Vite's officially documented **Backend Integration** pattern: build with `manifest: true` and a JS entry (not an `.html` entry), then have the backend read `.vite/manifest.json` and render, in order, `<link rel="stylesheet">` for the entry chunk's `css[]` (recursively including imported chunks' CSS), then `<script type="module" src="{chunk.file}">`, then optional `<link rel="modulepreload">` for imported chunks. `ManifestChunk` carries `file`, `css`, `imports`, `dynamicImports`, `isEntry`, `isDynamicEntry`. ⚠️ **CONFIRM:** the manifest path is `.vite/manifest.json` *relative to `build.outDir`* (not `outDir/manifest.json`) — cited to vite.dev/config/build-options, but verify by running the build once in slice 1 before writing the loader.

**Why MPA and not SPA — the decisive argument:** locked constraint #1 says every mutation is a native `<form method="post">` that produces a **full browser navigation** and a server `303`. There are **20** such routes; `app/templates/run_detail.html` alone contains **10** `<form method="post">` elements. Under an SPA, each of those submits tears down the document and reloads the shell from the server anyway. So the SPA's defining premise — one long-lived document, client-side transitions — is *already false* for the primary operator workflow. What remains of the SPA is pure cost: a catch-all route, a client router that never routes the interesting transitions, and a full JS re-parse + re-hydrate on every approve/reject/retrigger, on a free instance that may have just cold-started.

**Trade-offs, honestly:** three bundles means shared React/vendor code is duplicated across pages unless you configure a shared vendor chunk (`build.rollupOptions.output.manualChunks`) — do that, and the pages share a cached vendor chunk. Cross-page client state is impossible — which is correct here, because the server is the state machine (`PROJECT.md:291`).

**Example — the shell and the boot:**

```jinja
{# app/templates/react_page.html — NEW. Note: extends base.html, and the boot tags
   live HERE, never in base.html. That placement is what keeps /ops script-free. #}
{% extends "base.html" %}
{% block title %}{{ page_title }}{% endblock %}
{% block content %}
  <div id="root"></div>
  {# json_script() escapes < > & to < > & — see Pattern 4 #}
  <script id="page-data" type="application/json">{{ page_data_json }}</script>
  {% for href in asset_css %}<link rel="stylesheet" href="{{ href }}">{% endfor %}
  {% for href in asset_preload %}<link rel="modulepreload" href="{{ href }}">{% endfor %}
  <script type="module" src="{{ asset_entry }}"></script>
{% endblock %}
```

```python
# app/routes/runs.py — MODIFIED read route only. Mutations untouched.
@router.get("/runs")
def runs_list(request: Request, notice: str = Query(default="")) -> Response:
    try:
        runs = [_safe_run_for_browser(run) for run in repo.load_all_runs()]
    except Exception:
        logger.debug("load_all_runs unavailable — rendering empty list")
        runs = []
    page = RunsListPage(
        runs=[RunListItem.from_row(r) for r in runs],
        demo_fixtures=[...],
        in_flight_statuses=sorted(IN_FLIGHT_STATUSES),
        notice_label=notice_label(notice),     # STILL the server's allowlist
    )
    return render_react_page(request, entry="runs", page_title="Payroll runs · Pyrl", data=page)
```

### Pattern 2: Route-shadowing protection by *absence* of a catch-all

**What:** The shadowing question is dissolved rather than solved. Starlette matches routes in **registration order**, first match wins; a `Mount` is itself a route in that list. Today `app/main.py` registers exactly one mount (`app/main.py:11`, prefix `/static`) and seven routers (`app/main.py:13-19`). No route in the app uses a `{path:path}` converter — verify with `git grep -n "path:path" app/` returning nothing.

Under the MPA recommendation, **that stays true**: assets are served by the pre-existing `/static` mount, so nothing is added that could prefix-match `/webhook` (`app/routes/webhook.py:111`), `/health/*` (`app/routes/health.py:18,30,51,77`), `/internal/pump` (`app/routes/pump.py:79`), or a future `/api`. The `/static` prefix is a literal that cannot be a prefix of any of them. The guarantee is structural, not ordering-dependent, and therefore survives a future `app.include_router(...)` being appended at `app/main.py:20`.

**Enforcement (new test, slice 1):** a hermetic pytest that walks `app.main.app.routes` and asserts (a) no route path contains `:path`, and (b) the only `Mount` is `/static`. Falsifying mutation: add `@app.get("/{p:path}")` to `main.py` → the test must red. This is the same "guard proven able to fail" discipline as PROOF-05 (`PROJECT.md:99-103`).

**When option (b) — a catch-all serving `index.html` — would be needed:** only if you wanted client-side routing. Its **failure mode is a false-green health check, and it is severe.** A catch-all registered anywhere before a router, or a router appended after it, makes `GET /health/live` return `200` with an HTML body. `render.yaml`'s `healthCheckPath` points at that route (`app/routes/health.py:20-25`), so Render would mark a broken deploy healthy. Worse, `GET /internal/pump` would return `200`+HTML instead of `401`, and `pump.yml`'s `curl -f` drain step would go **green while the durable queue is never drained** — silently reverting PUMP-01/02 (`PROJECT.md:145-151`) and reintroducing exactly the "durable storage, not durable execution" failure v4 was built to close. That risk is not worth a client router that constraint #1 makes unusable.

**Option (c), per-page entries / islands, is not a rejected alternative — it is the recommendation.** "MPA with React-rendered pages" and "per-page entry points" are the same architecture described from two angles: option (a) is the serving mechanism (`StaticFiles` + a Jinja shell that boots the bundle), option (c) is the bundling shape (one entry per page). Adopt both. The only genuine sub-decision is granularity: one entry per **page** (recommended — matches the slice boundary exactly, so slice 1 ships one entry and slices 2/3 each add one file to `vite.config.ts`) versus many small islands per page (rejected: three pages do not justify an island runtime, and the run-detail page is one coherent operator surface, not a set of independent widgets).

### Pattern 3: The form-POST + 303 hybrid inside a React tree

**What:** React DOM does **not** intercept form submission for a `<form>` with a string `action` and no `onSubmit` handler — it renders a real DOM `<form>` and the browser performs the native POST and follows the `303`. That is the whole mechanism. The engineering work is not making it work; it is making it **impossible to break**.

Three things must survive, and each has a named source anchor:

1. **Redirect-encoded query state.** `app/routes/runs.py:626-627` computes `suffix = "?resolution_superseded=1" if not submission.authoritative else ""` and 303s to `/runs/{id}{suffix}`. `app/routes/demo.py:352` 303s to `/runs/{new_run_id}` — a run that did not exist when the form was submitted. `app/routes/operator_feedback.py:118-123` (`notice_redirect`) produces `?notice=<code>` for ~30 distinct outcomes (`app/routes/operator_feedback.py:25-95`). All three are *server-authored URLs*; the browser navigation is what delivers them. React never sees them as anything but props in the next page's embedded data.
2. **The native `confirm()` guard.** Four sites today: `app/templates/run_detail.html:143`, `:155`, `:282`, `:286`, `:320` (five `onsubmit="return confirm(...)"` occurrences across those lines). This is the fragile one.
3. **The index-keyed dynamic field names.** `app/routes/runs.py:586-597` reads `employee_id_{i}` / `remember_{i}` keyed by the **loop index over `decision.unresolved_names`, never by the raw token text** — the docstring at `app/routes/runs.py:523-533` states this is deliberate so a field name can never collide with an injected token. React must reproduce the index keying exactly; a "nicer" `employee_id[{token}]` shape silently breaks every resolve, and an unchecked checkbox must post **nothing at all** for its key (`app/routes/runs.py:597` treats absence as OFF).

**The three enforceable rules (structure, not discipline):**

- **R1 — one form element in the whole frontend.** ESLint `no-restricted-syntax` on `JSXOpeningElement[name.name="form"]`, allowed only in `src/components/MutationForm.tsx`. Every mutation therefore routes through one reviewable file.
- **R2 — `action` is typed `string`, never a function.** React 19 accepts `action={someFn}` (form Actions) and **silently converts a native POST into a client-side action with no navigation** — the single most likely accidental regression, because it looks like an improvement and the type checker would allow it if the prop were widened. `MutationForm`'s prop is `action: string`, and `tsc --noEmit` with `strict: true` (new CI job) makes the function form unrepresentable.
- **R3 — `fetch` is banned outside `src/hooks/usePoller.ts`.** ESLint `no-restricted-globals` / `no-restricted-properties`. A developer "improving" Approve into a fetch has to first delete a lint rule, which shows up in the diff.

**The confirm guard, precisely.** In React the HTML string form does not exist; `onSubmit` must be a function, and **returning `false` from a React `onSubmit` handler does not cancel the submit** — only `event.preventDefault()` does. Get that wrong and Reject becomes a one-click irreversible action with no visible symptom.

```tsx
// src/components/ConfirmForm.tsx — the ONLY confirm-guarded mutation surface.
export function ConfirmForm({ action, confirmMessage, children }: {
  action: string; confirmMessage: string; children: React.ReactNode;
}) {
  return (
    <form
      method="post"
      action={action}                               // string, never a function (R2)
      onSubmit={(e) => { if (!window.confirm(confirmMessage)) e.preventDefault(); }}
    >
      {children}
    </form>
  );
}
```

**What makes the regression detectable — four independent nets:**

| Regression | Detected by | Able to fail? |
|---|---|---|
| Approve/Reject becomes `fetch` | ESLint R3 in the new `frontend` CI job | delete the rule → diff review; add a `fetch` → job reds |
| `action={fn}` (React form Action) | `tsc --noEmit` strict, `action: string` | change the prop type → tsc reds |
| A raw `<form>` bypasses the component | ESLint R1 | add `<form>` in a page → job reds |
| `preventDefault()` dropped from the guard | Vitest: stub `window.confirm → false`, dispatch submit, assert `event.defaultPrevented === true`; and with `→ true` assert `false` | **delete the `preventDefault()` line → test reds.** Register this as the slice-2 falsifying mutation, per the repo's PROOF-05 convention |
| A redirect-`Location` assertion deleted during the markup-test rewrite | the existing pytest suite | see the warning below |

**⚠️ The subtle one, and the biggest real risk in slice 2.** The server-side proof that `?resolution_superseded=1` / `?notice=` semantics hold lives in `tests/test_dashboard.py` and `tests/test_needs_operator.py` as assertions on `response.headers["location"]`. Those assertions are **renderer-agnostic and must not be deleted.** But the same two files carry ~4,650 LOC of *markup* assertions (`tests/test_dashboard.py` is 2,296 lines with 63 `response.text` references; `tests/test_needs_operator.py` is 2,223 lines) which *must* be rewritten. The failure mode is a bulk delete-and-rewrite that throws the redirect-location assertions out with the HTML, silently removing the only proof that constraint #1 still holds. **Mitigation, and it should be a stated plan step: before touching either file, grep out every `headers["location"]` / `status_code == 303` assertion into an inventory, and pin the count.** This is the same "harvest the inventory first, then pin the guard against it" move that closed v3's comment-hygiene blind spots (`PROJECT.md:48-50`).

### Pattern 4: The allowlist DTO seam — the leak-prevention structure

**What:** Today's reduction helper is a **denylist**. `app/routes/runs.py:232-241` names eight raw fields plus a `job_` prefix to *remove*, and `app/routes/runs.py:242-244` pops them. Everything not named survives. `RUN_COLS` (`app/db/repo/runs.py:38-42`) currently selects `id, business_id, source_email_id, status, reply_epoch, extracted_data, decision, reconciliation, error_reason, error_detail, alias_candidates, hours_changes, pay_period_start, pay_period_end, updated_at` — so `business_id`, `reply_epoch`, `alias_candidates`, and `source_email_id` all pass the denylist untouched. That is fine while a Jinja template only reads what it names; it is a leak the moment anything serializes the dict wholesale, and it auto-exposes any column added to `RUN_COLS` later. This is the falsified decision at `PROJECT.md:211-214`, confirmed against live source.

**The structure that replaces discipline** — a base class where *both* halves of the decision are declared, and a row key that is in neither half is a hard error:

```python
# app/schemas/_projection.py — NEW
class UnclassifiedColumnError(RuntimeError):
    """A repo row carried a key that is neither exposed nor consciously excluded."""

class RowProjection(BaseModel):
    """Base for any DTO constructed directly from a repo row dict.

    The model's own declared fields ARE the allowlist. EXCLUDED names the fields
    consciously withheld, one by one. A row key in neither set raises: the column
    reached RUN_COLS and nobody decided whether the browser may see it.
    """
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
# app/schemas/run_detail.py — NEW. The three named leaks become typed constants.
class RunDetail(RowProjection):
    EXCLUDED = frozenset({
        "business_id",        # tenant identifier — never leaves the server
        "reply_epoch",        # internal fence counter (CLAR2-07)
        "alias_candidates",   # the LLM's advisory guess; projected only via
                              # unresolved_suggestions, deliberately not raw
        "source_email_id",    # internal FK
    })
    id: uuid.UUID
    status: str
    badge_class: str          # from templating.py:48 — NEVER re-derived in TS
    badge_label: str          # from templating.py:53 — NEVER re-derived in TS
    banner: DecisionBanner    # server-computed discriminated union (see below)
    ...
```

Note what this buys beyond leak prevention: `EXCLUDED` is a *reviewable list of secrets*, greppable and diffable, where today the equivalent knowledge is a set literal of eight strings buried in a private helper.

**The failing-test story — three tests, each able to fail:**

1. **Mechanism (does `from_row` actually refuse?)** — `RunDetail.from_row({**good_row, "surprise": 1})` raises `UnclassifiedColumnError`. Falsifying mutation: delete the `if unknown:` block → this test reds.
2. **Coupling for `load_run` (the RUN_COLS question, answered directly).** `RUN_COLS` is an importable module constant string, so this is a **pure hermetic test with no DB**:

```python
# tests/test_schema_projection.py — NEW, slice 1
def test_every_run_col_is_classified() -> None:
    cols = {c.strip() for c in repo.runs.RUN_COLS.split(",")}
    classified = set(RunDetail.model_fields) | RunDetail.EXCLUDED | _DERIVED_FIELDS
    assert not (cols - classified), (
        f"New payroll_runs column(s) {sorted(cols - classified)} reached RUN_COLS but "
        "were neither exposed in RunDetail nor named in RunDetail.EXCLUDED. Decide, "
        "then add the column to exactly one of them."
    )
```

   This is the answer to "how can a test fail when a new `RUN_COLS` column is added but not consciously exposed or excluded": appending `, ssn` to `app/db/repo/runs.py:38-42` reds this test in the **already-existing hermetic `test` job**, with no database, no fixture, and an error message that names the decision to make. Register `, ssn` as the falsifying mutation.
3. **Coupling for `load_all_runs`.** Harder, because that projection is a function-local `sql` string, not a constant (`app/db/repo/demo.py:229-258`). Three options, letter-labeled:
   - **(a) RECOMMENDED — AST-read the function source in the test.** `ast.parse(inspect.getsource(repo.load_all_runs))`, find the `sql` assignment, join its string literals, regex out the projected names and `AS` aliases (`created_at`, `business_name`, `summary_gate_reason`, `employee_count`, `job_attempts`, `job_max_attempts`, `queue_label`), assert each is classified in `RunListItem`. **Zero production edit**, keeps `app/db/` genuinely untouched as the milestone requires, and matches four existing AST-guard precedents in this repo (BOUND-01, the CAS-only queue guard, `check_proof_inventory.py`, and the call-site drift pin in `tests/test_operator_feedback.py:110-111`).
   - **(b) Extract the column list into a module constant `RUNS_LIST_COLS`.** Cleaner test, but it is an edit to `app/db/repo/demo.py`, which `PROJECT.md:253-254` puts out of scope. Only take this if a planner judges the AST regex too brittle.
   - **(c) Do nothing; rely on the `extra="forbid"` runtime failure.** Rejected: the leak surfaces as a production 500 on the runs list instead of a red test, and Render's ephemeral logs make it a bad place to learn about it.

**Third and fourth nets, free:** `mypy --strict` already covers `app/` and will prove a converted read route cannot return a raw dict once its return annotation is the DTO. And because FastAPI infers `response_model` from the return annotation, FastAPI's own serializer applies the field allowlist a second time on any DTO returned from a JSON route (`/runs/{id}/status`).

**A latent bug this seam surfaces immediately — flag for the slice-2 planner.** `app/templates/run_detail.html:118` renders `run.clarification_round if run.clarification_round else 3`, but **`clarification_round` is not in `RUN_COLS`** (`app/db/repo/runs.py:38-42`). Jinja resolves the missing key to `Undefined`, which is falsy, so the page has always silently displayed "3 clarification round(s)" regardless of the real count. Pydantic will not be so forgiving. Options: **(a) RECOMMENDED** — declare `clarification_round: int | None = None` on the DTO and render "3 or more" when `None`, which is presentation-only and honest; (b) add the column to `RUN_COLS`, which is an `app/db/` edit and out of scope; (c) hardcode 3 in the DTO, which preserves the existing lie. Similarly, `created_at` appears in `load_all_runs`'s projection and is used at `app/templates/runs_list.html:82` but is **absent from `RUN_COLS`** — so the list and detail DTOs are genuinely different projections of the same table. **Do not try to share one `Run` DTO across `/runs` and `/runs/{id}`.**

### Pattern 5: Server-embedded initial data (not fetch-on-mount)

**What:** the route builds its DTO and the shell embeds it as `<script id="page-data" type="application/json">`. React parses it synchronously on mount. No loading state, no spinner, no second request.

**Why, concretely for this app:**
- **Cold start.** Render free spins down after 15 idle minutes with a cold start of up to ~1 minute (`PROJECT.md:290`). Fetch-on-mount serializes a second round trip *behind* that cold start, so the first thing a hiring manager sees is a spinner on a page that already took 40 seconds. `PROJECT.md:7` ranks "visibly works end to end" first.
- **The redirect-encoded state already arrives server-side.** `app/routes/runs.py:1236-1237` reads `resolution_superseded` and `notice` from the query string and `app/routes/operator_feedback.py:98-100` reduces the notice code to a fixed label. Embedding means React never parses a query param and the `NOTICE_LABELS` vocabulary (30 entries, `app/routes/operator_feedback.py:25-95`) is never duplicated into TypeScript.
- **No new public data surface.** The dashboard is deliberately unauthenticated (`PROJECT.md:274`). A `GET /api/runs` returning the same DTO would be a *new* anonymous JSON endpoint — and would be exactly the "unconsumed JSON API" that falsified decision #3 rules out (`PROJECT.md:215-217`).

**The XSS seam — name it and give it one owner.** The DTO carries client-supplied text: `submitted_name` from LLM extraction, email bodies in the conversation thread, and (for `/eval`) raw fixture bodies joined in at `app/routes/dashboard.py:181`. JSON inside a `<script>` element is **not** protected by Jinja autoescape once passed through `| safe`, and a body containing the literal `</script>` terminates the element early. Add **one** helper, with one test:

```python
# app/routes/templating.py — MODIFIED. Django's json_script is the precedent.
_JSON_SCRIPT_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"}

def json_script(model: BaseModel) -> Markup:
    """Serialize a DTO for embedding in <script type="application/json">."""
    raw = model.model_dump_json()
    for ch, esc in _JSON_SCRIPT_ESCAPES.items():
        raw = raw.replace(ch, esc)
    return Markup(raw)
```

Test (slice 1, able to fail): construct a DTO whose `submitted_name` is `</script><img src=x onerror=alert(1)>`, render the page, assert the response body contains **no** literal `</script>` before the closing tag of the data island and no literal `<img`. Falsifying mutation: remove the `<` replacement → test reds.

**How the existing 2-second poller fits — unchanged mechanism, shared type.** `GET /runs/{run_id}/status` (`app/routes/runs.py:890-917`) already returns exactly the poll projection, already reduced through `_safe_run_with_queue_projection` (`app/routes/runs.py:248-258`), and already hand-builds its response dict at `:907-917` — i.e. it is *already* an allowlist. Convert that dict into a `RunStatusPoll` DTO (low risk, high value) so the poller and the embedded initial data share **one** generated TS type. The vanilla-JS pollers at `app/templates/runs_list.html:10-60` (60 attempts / 120 s, per-row, keyed on `[data-run-id]`) and `app/templates/run_detail.html:32-95` become one `usePoller` hook with the same 2 s cadence, the same attempt cap, and the same stop condition (`!IN_FLIGHT.has(status) && !has_open_job`, `app/templates/runs_list.html:47-49`). `IN_FLIGHT_STATUSES` keeps coming from the server (`app/routes/runs.py:84-86`, threaded into the page today at `:879`) — do not hardcode the status list in TS.

### Pattern 6: Server-computed discriminated unions (extend an existing convention)

**What:** the run-detail decision banner is an 8-branch `if/elif` chain over three independent inputs (`app/templates/run_detail.html:99`, `:112`, `:116`, `:149`, `:161`, `:165`, plus the independent hours-changed banner at `:196` and the delivery-review-unavailable branch at `:285`). If React re-derives the branch from `status` + `decision.final_action` + `delivery_review_marker`, that logic exists twice and can diverge — and one of those branches decides whether **Reject is offered on a confirmation that may already have reached the client**, which the template comment at `app/templates/run_detail.html:282` documents at length as the anti-BUG-1 pin.

**This convention already exists in the codebase and is documented.** `_safe_delivery_review_projection` (`app/routes/runs.py:311-353`) derives `can_replay` / `can_fresh_send` / `uncertainty` / `blocker` server-side from `DELIVERY_REVIEW_CATEGORIES`, and its docstring (`app/routes/runs.py:314-322`) states the rule outright: *"The template receives only booleans, never a category string to re-derive from, so a template edit can never accidentally offer an action the classification says cannot succeed."*

**Recommendation:** extend that exact rule to the banner. The DTO carries `banner: DecisionBanner` as a Pydantic discriminated union (`Literal` `kind` field + per-kind payload), and React switches on `kind` with an exhaustiveness check (`default: assertNever(kind)`), so adding a ninth kind server-side becomes a **TypeScript compile error** in the new CI job rather than a silently unrendered banner. Do the same for the operator controls: the DTO carries `controls: {can_approve, can_reject, can_retrigger, can_simulate_reply}` booleans rather than the status string, so the retrigger visibility rule at `app/templates/run_detail.html:327` (`status in ['error','approved','received','extracting','computed','sent']`) is not restated in TS. **Decide this shape in slice 1's DTO base design, even though it is only consumed in slice 2** — see the pull-forward list.

---

## Data Flow

### Read flow (a page load)

```
GET /runs/{id}
    ↓
app/routes/runs.py:1232 run_detail()      ← 10 best-effort repo reads, unchanged
    ↓
_safe_run_with_queue_projection  (runs.py:248)   ← existing denylist, KEPT as an inner layer
    ↓
RunDetail.from_row(row)          (app/schemas/run_detail.py)  ← ALLOWLIST; raises on
    ↓                                                            an unclassified key
render_react_page(request, entry="runDetail", data=dto)  (templating.py, NEW)
    ↓                    ↓
json_script(dto)    manifest.json lookup → hashed <script>/<link>
    ↓                    ↓
react_page.html → base.html (nav, /static/style.css)
    ↓
browser: parse #page-data → mount <RunDetailPage> → 0 additional requests
    ↓
usePoller (2s) → GET /runs/{id}/status → RunStatusPoll → badge swap in place
```

Note the belt-and-braces ordering: the existing denylist is **not deleted**, it becomes the inner layer, and the new allowlist is the outer one. Two independent reductions, each of which alone would prevent the leak.

### Mutation flow (the locked constraint, drawn)

```
operator clicks "Resolve & Resume"
    ↓
<ConfirmForm action="/runs/{id}/resolve" method="post">   ← real DOM form; no fetch
    ↓  (browser-native POST — full navigation)
app/routes/runs.py:517 resolve()          ← BYTE-IDENTICAL to today
    ↓  server-side roster validation, whole-POST-or-nothing (runs.py:584-597)
    ↓  commit generation + OPERATOR_RESUME job in one transaction (runs.py:601-617)
    ↓
303 Location: /runs/{id}?resolution_superseded=1   ← authored by runs.py:626-627
    ↓  (browser follows — a NEW document, not a re-render)
GET /runs/{id}  →  runs.py:1236 reads the query param  →  into the DTO
    ↓
React renders the superseded banner from embedded data. It never saw the query string.
```

The same shape holds for `notice_redirect` (`app/routes/operator_feedback.py:118`) across ~30 outcomes and for `/demo/send-test` → `303 /runs/{brand-new-id}` (`app/routes/demo.py:352`).

### Build / deploy flow

```
git push
    ↓
ci.yml (4 blocking jobs)
  lint (ruff) │ test (pytest, hermetic) │ typecheck (mypy --strict) │ frontend (NEW)
                    │                                                    │
                    │ gates app/schemas/schemas.json --check              │ npm ci
                    │ (Python-only; no node needed)                       │ tsc --noEmit
                    │                                                     │ eslint (R1/R2/R3)
                    │                                                     │ vitest (confirm guard)
                    │                                                     │ npm run build
                    │                                                     │ dtos.d.ts --check
    ↓
Render builds the Dockerfile
  stage 1 frontend (node)  → npm ci → npm run build → /app/frontend/dist
  stage 2 builder (python) → COPY . .  → COPY --from=frontend dist → app/static/dist
                           → uv sync --frozen --no-dev
  stage 3 runtime          → COPY --from=builder /app /app     ← UNCHANGED
                           → WORKDIR /app (required: relative app/templates, app/static,
                             app/static/dist/.vite/manifest.json, eval/chart.svg)
                           → .venv/bin/uvicorn --host 0.0.0.0 --port ${PORT:-10000}
```

**Commit `dist/` to git, or build it in Docker? — build in Docker. Do not commit.** The question deserves the `eval/chart.svg` comparison, so here it is honestly: `chart.svg` is committed because it is **evidence** — a reviewer opens the repo on GitHub and sees the proof — and because its generator (matplotlib) is dev-group-only and must not become a serve-time or image cost (`PROJECT.md:243`). Its `--check` gate exists to catch a stale artifact. A minified JS bundle is not evidence; nobody reads it. Committing it buys 200 KB of churn in every PR diff and *still* requires a "was this bundle actually built from this source" `--check` gate, which requires node in CI anyway. So you pay the node cost either way and additionally pay the diff noise.

**But the corollary is mandatory, not optional.** Because the bundle is built in Docker, `ci.yml`'s existing three jobs never build it — so a TS type error or a broken import would pass CI green and fail the **Render deploy**. Add `dist/` to `.gitignore` and add `frontend/node_modules/` + `frontend/dist/` to `.dockerignore` (so a local dev build cannot ride in via `COPY . .` and shadow the stage output — and make sure `frontend/` itself is **not** excluded). **The new `frontend` CI job is what makes "build in Docker" safe; treat the two as one coupled decision.** That coupling is worth stating explicitly to the roadmapper: a slice that ships the Docker stage without the CI job has moved a class of failure from CI to production.

**And a second corollary the planner will hit on day one:** with `dist/` gitignored, the hermetic pytest job has **no manifest**. The loader therefore needs an explicit, non-silent missing-manifest fallback: render the shell with a clearly-marked "assets not built" marker rather than raising. This turns out to be a *benefit* — it means the migrated pytest assertions can target the **embedded DTO JSON** (`assert "needs_operator" in data["banner"]["kind"]`) instead of rendered HTML, which is **renderer-independent** and is the single best answer to the 4,650-LOC markup-test cost center. Migrated that way, those tests would survive a future frontend rewrite untouched.

### Local dev flow

`app/config.py` (`app/config.py:16` `Settings`) gains one optional field, `vite_dev_server_url: str = ""`:

- **unset (default, and what CI/Docker use):** read `app/static/dist/.vite/manifest.json`, emit hashed tags per the backend-integration pattern.
- **set to `http://localhost:5173`:** emit `<script type="module" src="{base}/@vite/client">`, the React refresh preamble, then `<script type="module" src="{base}/src/entries/{entry}.tsx">`. Requires Vite's `server.cors.origin` to allow `http://localhost:8000`.

**Vite dev server proxying to uvicorn is the wrong direction and should be rejected explicitly.** uvicorn owns the HTML, the routing, the `303`s, and the embedded data — the browser must talk to uvicorn as the origin, with Vite as a secondary *asset* origin. Put Vite in front as a proxy and every form POST's `303 Location` is authored against the wrong origin: `app/routes/runs.py:627`'s `/runs/{id}?resolution_superseded=1` resolves relative to `:5173`, and you spend the milestone debugging proxy rewrites for the exact mechanism constraint #1 exists to protect.

**Rejected alternative — no dev server, `npm run build --watch`.** Failure mode is behavioral, not technical: no HMR means every change is a full rebuild plus reload, which is slow enough that a developer starts avoiding reloads — and the way you avoid a reload is by turning a form POST into a `fetch`. That is how constraint #1 erodes, not by a decision but by friction.

---

## Slice Boundaries and Build Order

Slices are `/runs` (Phase 22) → `/runs/{id}` (Phase 23) → `/eval` (Phase 24). Each must deploy on its own.

### MUST land in slice 1 (shared foundation)

| # | Item | New/Mod | Retrofit pain if deferred |
|---|------|---------|---------------------------|
| 1 | `frontend/` workspace: Vite, React, `tsconfig` strict, ESLint R1/R2/R3, Vitest | new | — (unavoidably slice 1) |
| 2 | `app/schemas/` + `RowProjection.from_row` + `UnclassifiedColumnError` | new | slice 1 ships an ad-hoc dict; slice 2 re-opens `/runs` to retrofit it |
| 3 | The three classification tests (mechanism, `RUN_COLS`, AST-read `load_all_runs`) | new | the seam's whole value is preventing a leak **from the first shipped page**; the AST guard is the most punt-able item on this list |
| 4 | Manifest loader + `render_react_page()` in `templating.py` + `react_page.html` | mod + new | three copies of the boot logic, drifting |
| 5 | `json_script()` + its `</script>`-injection test | new | slice 1 ships the XSS surface unguarded |
| 6 | `MutationForm` + `ConfirmForm` + the Vitest cancel/allow tests | new | **pull forward — see below** |
| 7 | DTO→TS generation: `schemas.json` (pytest `--check`) + `dtos.d.ts` (frontend-job `--check`) | new | hand-written interfaces become the source of truth by inertia; drift is exactly the bug class this milestone claims to prevent |
| 8 | Dockerfile node stage + `.dockerignore` + `.gitignore` + the new `frontend` CI job | mod | slice 1 is "independently deployable", which means it must deploy — and safely |
| 9 | `RunStatusPoll` DTO + `usePoller` hook | new | slice 2 rewrites the poller; both pages poll |
| 10 | Nav decision: React pages render inside `base.html`'s `{% block content %}`; React never renders nav | (structural) | `/` and `/ops` drift visually from the converted pages |
| 11 | **The `DecisionBanner` discriminated-union *shape*** (base pattern + exhaustiveness convention), even though only `/eval` and `/runs` consume trivial banners | new | slice 2's 8-branch matrix is the hardest thing in the milestone; deciding its shape under slice-2 time pressure is how the logic ends up duplicated in TS |

**Why #6 is a genuine pull-forward and not gold-plating.** Slice 1's `/runs` contains exactly **one** form — the demo fixture picker at `app/templates/runs_list.html:126-135` — and it needs no confirm guard. So the natural instinct is to inline it and build the component in slice 2. But slice 2 has **10** `<form method="post">` elements in one template and **all five** `onsubmit confirm` sites. Building the guarded-form abstraction there means inventing it under the pressure of the largest page in the app, which is precisely where the `preventDefault()` regression lands. Build the component with one trivial consumer in slice 1, prove the guard reds without `preventDefault()`, and slice 2 becomes composition rather than invention.

### Genuinely per-slice

- **Slice 1 (`/runs`):** `RunListItem` / `RunsListPage` DTOs; the runs table; per-row poll wiring keyed on `data-run-id` (`app/templates/runs_list.html:79`); the empty state; the demo picker form. Read route: `app/routes/runs.py:855-882`.
- **Slice 2 (`/runs/{id}`):** `RunDetail` DTO; the 8-branch banner as a server-computed union; **both** delivery-review card variants (clarification at `app/templates/run_detail.html:269-275`, confirmation at `:277-283`, plus the unavailable variant at `:285-286`); the conversation thread (`:210-266`); the `<details class="payroll-details">` disclosure; six operator-control forms; the resolve form's index-keyed dynamic fields (`app/routes/runs.py:586-597`); the independent hours-changed banner (`:196`). Read route: `app/routes/runs.py:1232-1354`.
- **Slice 3 (`/eval`):** `EvalSummary` / `EvalFixtureRow` DTOs; the three headline metrics — note the percentage arithmetic currently lives **in the template** (`app/templates/eval.html:16-21` computes decision accuracy from the confusion matrix) and should move into the DTO, not into TS; `<img src="/eval/chart.svg">` unchanged (`app/routes/dashboard.py:200-211` untouched); the drill-in table. Read route: `app/routes/dashboard.py:150-192`.

### Flagged for the roadmapper

1. **Pull the banner union's *shape* into slice 1** (item 11). Its consumer is slice 2, but its design constrains the DTO base class.
2. **Pull `MutationForm`/`ConfirmForm` into slice 1** (item 6), with the falsifying-mutation test.
3. **Harvest the redirect-assertion inventory before rewriting markup tests** (Pattern 3's warning). This is a plan step, not a nicety.
4. **`clarification_round` is a latent display bug the DTO seam will surface** (`app/templates/run_detail.html:118` vs `app/db/repo/runs.py:38-42`). Slice 2 must decide; recommendation (a) above is presentation-only and in scope.
5. **`load_all_runs` is unbounded** (`app/db/repo/demo.py:257` — `ORDER BY pr.created_at DESC`, no `LIMIT`). Not a v5 problem at demo scale, and adding a `LIMIT` is an `app/db/` edit that is out of scope. Note it so a planner does not "fix" it inside a presentation slice.
6. **Decide "Vite emits no CSS" in slice 1** (see Coexistence). It is a one-line lint-able invariant now and a refactor later.

---

## Coexistence with the Remaining Jinja Pages

**Design tokens — consumed, never duplicated.** `app/static/style.css` declares 293 custom properties, the `:root` block at `app/static/style.css:7-60`. React pages keep the `<link rel="stylesheet" href="/static/style.css">` inherited from `app/templates/base.html:7` and use the **existing class names** (`badge badge-good`, `card card-pad`, `banner banner-error`, `btn btn-accent`, `form-inline`, `table-scroll`, `callout callout-error`). No CSS-in-JS, no Tailwind, no re-declared `:root`.

**Recommendation: emit no CSS from Vite at all in this milestone** — import no `.css` from any `.tsx`. Then `style.css` remains the only stylesheet, every manifest chunk's `css[]` array stays empty, and the "no design-system duplication" claim is *literally* true rather than aspirational. It is also testable: assert every `ManifestChunk.css` is empty in the frontend job.

**The two vocabularies that must never be ported to TypeScript:**

| Vocabulary | Server home | How React gets it |
|---|---|---|
| `_BADGE_CLASS` / `_BADGE_LABEL` (11 statuses each) | `app/routes/templating.py:18-30`, `:33-45`, filters at `:48`/`:53` | DTO fields `badge_class` / `badge_label` as plain strings — exactly what `run_status` already returns at `app/routes/runs.py:910-911` |
| `NOTICE_LABELS` (~30 codes) | `app/routes/operator_feedback.py:25-95`, reduced by `notice_label()` at `:98` | DTO field `notice_label: str | None` — the **already-reduced label**, never the raw code |

The notice mechanism therefore stays wholly server-side, unchanged. `app/templates/_operator_notice.html` continues to serve `/` and `/ops`; React renders an `OperatorNotice` component with the same markup (`callout callout-error`, `role="alert"`), so one CSS rule covers both. The AST drift pin in `tests/test_operator_feedback.py` inspects **Python** call sites (`app/routes/operator_feedback.py:110-111` documents this) and is unaffected by the renderer change.

**Nav — one implementation, in Jinja.** `app/templates/base.html:9-16` derives `aria-current="page"` from `request.url.path`, with the prefix rules `/runs/` and `/eval` already handled. React pages render inside `{% block content %}` of that same `base.html`, so the nav has exactly one implementation across all five pages and `tests/test_ops_route.py:355-356` (which asserts nav order `/`, `/runs`, `/eval`, `/ops`) keeps passing for every page.

**`/ops` gains no script tag — the structural reason.** `app/templates/base.html` contains **no** `<script>` element today. `app/templates/ops.html` extends it. Therefore: **the Vite boot tags go in `react_page.html`, never in `base.html`.** Hoisting them into `base.html` is the tempting DRY move and it is exactly the mistake; `tests/test_ops_route.py:364-368` (`assert "<script" not in response.text`, plus `setInterval` and `meta refresh`) is the enforcement, and it will red immediately. Say this to the planner as a rule with its guard named, because the guard firing is the design working, not a test to relax.

---

## Anti-Patterns

### 1. SPA catch-all route
**What people do:** `@app.get("/{full_path:path}")` returning `index.html`.
**Why it's wrong here:** `/health/live` (`app/routes/health.py:18`) returns `200`+HTML → Render's `healthCheckPath` marks a broken deploy healthy. `/internal/pump` (`app/routes/pump.py:79`) returns `200`+HTML instead of `401` → `pump.yml`'s `curl -f` goes green while the durable queue is never drained, silently reverting PUMP-01/02. Protection depends on registration order in `app/main.py`, which is invisible at review time.
**Instead:** MPA. No catch-all exists; assets ride the pre-existing `/static` mount (`app/main.py:11`). Pin it with a route-table test.

### 2. Serializing `_safe_run_for_browser` output wholesale
**What people do:** `JSONResponse(_safe_run_for_browser(run))` or `model_dump()` over the whole dict.
**Why it's wrong:** `app/routes/runs.py:232-244` is a **denylist**. `business_id`, `reply_epoch`, `alias_candidates`, and `source_email_id` all survive it, and any future `RUN_COLS` column is auto-exposed.
**Instead:** `RunDetail.from_row(...)` — allowlist by declared fields, with `EXCLUDED` naming each withheld field, plus the `RUN_COLS` classification test.

### 3. "Improving" a mutation into `fetch`
**What people do:** `await fetch('/runs/'+id+'/approve', {method:'POST'})` then re-fetch the page data.
**Why it's wrong:** loses `?resolution_superseded=1` (`app/routes/runs.py:626-627`), loses the redirect to a brand-new run id (`app/routes/demo.py:352`), loses ~30 `?notice=` codes (`app/routes/operator_feedback.py:118`), and loses the native `confirm()` guard on an irreversible Reject (`app/templates/run_detail.html:143`).
**Instead:** `MutationForm` with a string `action`; ESLint R3 bans `fetch` outside `usePoller`.

### 4. React 19 form Actions (`action={fn}`)
**What people do:** pass a function to `action` because React 19 supports it.
**Why it's wrong:** React intercepts the submit, there is no navigation, and the `303` is never followed — anti-pattern 3 with no diff that says `fetch`.
**Instead:** `action: string` in the component's prop type; `tsc --noEmit` strict makes the function form unrepresentable.

### 5. Porting `_BADGE_*` or `NOTICE_LABELS` into TypeScript
**What people do:** a `const BADGE_LABELS: Record<string,string>` in TS because "the client needs the label".
**Why it's wrong:** two sources of truth for operator-facing vocabulary, with no test that they agree. `app/routes/runs.py:910-911` already established the correct shape.
**Instead:** the server sends the resolved strings in the DTO.

### 6. Hoisting the Vite boot tags into `base.html`
**What people do:** the DRY move — one place for the script tags.
**Why it's wrong:** `/ops` inherits a script tag, breaking the deliberate "the page you read when everything else is broken must not depend on a bundle" property (`PROJECT.md:195-197`), and `tests/test_ops_route.py:364` reds.
**Instead:** the tags live in `react_page.html` only.

### 7. `dangerouslySetInnerHTML` for email bodies
**What people do:** render the conversation thread's HTML-ish body with `dangerouslySetInnerHTML` to preserve line breaks.
**Why it's wrong:** thread bodies are client-supplied. Jinja's autoescape is what protects them today (`app/templates/run_detail.html:190` documents the "`{{ }}` only, autoescaping ON, never `|safe`" rule for `submitted_name`). React escapes by default, so the *only* way to lose that is `dangerouslySetInnerHTML`.
**Instead:** render as text with `white-space: pre-wrap`. Ban it with ESLint `react/no-danger`.

### 8. A `GET /api/runs` JSON endpoint "for the frontend"
**What people do:** build the API first, consume it later.
**Why it's wrong:** falsified decision #3 (`PROJECT.md:215-217`) — it strands an unconsumed API; and on an unauthenticated dashboard (`PROJECT.md:274`) it is a *new* anonymous bulk-data surface with the same serialization risk constraint #2 exists to bound.
**Instead:** embedded page data. The only JSON route is the pre-existing `GET /runs/{id}/status` (`app/routes/runs.py:890`), which already has a consumer.

---

## Scaling Considerations

The template's user-count framing does not apply — this is a single-operator demo at roughly one payroll email per client per week (`PROJECT.md:277`). The dimensions that actually bite:

| Dimension | Today | First thing that breaks | Fix when it does |
|---|---|---|---|
| Runs in the list | `load_all_runs` has **no `LIMIT`** (`app/db/repo/demo.py:257`) and one poller per in-flight row (`app/templates/runs_list.html:53-58`) | ~200 runs: the embedded JSON island grows and N concurrent 2 s polls hit one pool | `LIMIT`/pagination in the repo — an `app/db/` edit, **out of scope for v5**; flagged only so nobody fixes it inside a presentation slice |
| Bundle size vs cold start | 0 KB today | React + the largest page beyond a few hundred KB adds parse time on top of a ~1-minute cold start | shared vendor chunk via `manualChunks`; keep the page bundles thin; no chart/table library |
| Page count | 5 (3 converted) | ~10 entries makes hand-maintaining `vite.config.ts` inputs tedious | glob the `src/entries/` directory into `input` |
| DTO ↔ TS drift | prevented by the two committed-artifact `--check` gates | someone regenerates one and not the other | both gates run on every push; they are in different jobs by toolchain, not by choice |

---

## Integration Points

### Internal boundaries

| Boundary | Communication | Notes |
|---|---|---|
| React page ↔ FastAPI read route | embedded JSON island (`<script id="page-data" type="application/json">`) | one document, zero extra requests; escaped by `json_script()` |
| React page ↔ FastAPI mutation route | native form POST → `303` → full navigation | **locked constraint #1**; enforced by ESLint R1/R3 + `tsc` R2 + a Vitest guard test |
| React poller ↔ `GET /runs/{id}/status` | `fetch`, 2 s, JSON | `app/routes/runs.py:890-917`; the **only** sanctioned `fetch` in the frontend |
| Route ↔ repo row | `RowProjection.from_row` | allowlist boundary; raises `UnclassifiedColumnError` on an unclassified key |
| Pydantic DTO ↔ TypeScript type | `app/schemas/schemas.json` (pytest `--check`) → `frontend/src/generated/dtos.d.ts` (frontend-job `--check`) | two committed artifacts, gated in whichever job already has the toolchain; the `eval/chart.svg` + `eval --check` precedent |
| React pages ↔ Jinja pages | shared `base.html` (nav) + shared `/static/style.css` (tokens) + server-side `notice_label()` | no duplication in either direction; `/ops` provably script-free |
| Presentation ↔ everything else | none | `app/pipeline/`, `app/queue/`, `app/db/`, `app/llm/`, `app/email/` are read-only for this milestone; the only `app/db/` *read* is the AST-inspection test of `load_all_runs`, which imports nothing new |

### External / platform

| Service | Integration | Gotchas |
|---|---|---|
| Render free (single container) | one Docker image, `$PORT`, `0.0.0.0` | ephemeral FS is fine — the bundle is baked into the image; the runtime stage's `WORKDIR /app` is **required** for the relative manifest path, same reason `eval/chart.svg` needs it (`app/routes/dashboard.py:203-206`) |
| Vite dev server (local only) | secondary asset origin at `:5173`; uvicorn stays the document origin | needs `server.cors.origin` allowing `:8000`; **never** proxy uvicorn behind Vite |
| GitHub Actions | fourth blocking job in `ci.yml` | `frontend` job is what makes "build in Docker, don't commit `dist/`" safe |
| npm registry | `npm ci` in the Docker node stage | commit `package-lock.json`; mirror the repo's `uv.lock --locked` discipline (`ci.yml` uses `uv sync --locked` in all three jobs) |

---

## Sources

**Codebase (HIGH — every line read today, 2026-08-17):** `app/main.py:1-20`; `app/routes/runs.py` (1,534 lines; `_safe_run_for_browser` `:220-245`, denylist `:232-244`, `_safe_run_with_queue_projection` `:248-258`, `_safe_delivery_review_projection` `:311-353` and its convention docstring `:314-322`, `resolve` `:517-627` incl. the superseded redirect `:626-627` and index-keyed form parsing `:586-597`, `runs_list` `:855-882`, `run_status` `:890-917`, `run_detail` `:1232-1354`, `IN_FLIGHT_STATUSES` `:84-86`); `app/routes/dashboard.py:150-192`, `:200-211`; `app/routes/operator_feedback.py:25-95`, `:98-123`; `app/routes/demo.py:264`, `:352`; `app/routes/health.py:18,30,51,77`; `app/routes/pump.py:79`; `app/routes/webhook.py:111`; `app/routes/templating.py:10,18-45,48-59`; `app/db/repo/runs.py:38-42` (`RUN_COLS`); `app/db/repo/demo.py:210-260` (`load_all_runs`); `app/templates/base.html:1-22`; `app/templates/runs_list.html:10-60,79-135`; `app/templates/run_detail.html:99-200,210-287,314-348`; `app/templates/eval.html:1-100`; `app/templates/_operator_notice.html`; `app/static/style.css:7-60`; `Dockerfile`; `.dockerignore`; `.gitignore`; `.github/workflows/ci.yml`; `app/config.py:1-40`; `tests/test_ops_route.py:355-368`; test sizes via `wc -l` (`test_dashboard.py` 2,296 / `test_needs_operator.py` 2,223 / `test_ops_route.py` 429).

**Vite (⚠️ CONFIRM before writing the manifest loader):** vite.dev/guide/backend-integration (the manifest + server-rendered-tags pattern, `ManifestChunk` fields, dev-server injection incl. the React refresh preamble, CORS) and vite.dev/config/build-options (`build.manifest` default path `.vite/manifest.json` relative to `build.outDir`; top-level `input` preferred over `build.rollupOptions.input`; relative `base` uses `import.meta.url`). Both fetched from the official docs, but the `classify-confidence` seam pins the `webfetch` provider at **LOW** regardless of source — so **verify the manifest path by running `npm run build` once in slice 1** rather than coding against it. Cached under keys `90f34b01…` and `67a4b67d…`.

**Project artifacts (HIGH):** `.planning/PROJECT.md:182-217` (v5 locked scope, non-goals, the three falsified decisions), `:243` (matplotlib dev-group-only), `:253-256` (out-of-scope layers, the 4,650-LOC markup-test cost center), `:274` (no dashboard auth), `:277` (no throughput machinery), `:290-292` (Render free realities, the DRY seam), `:145-151` (PUMP-01/02), `:99-103` (PROOF-05 completeness-gate discipline).

---
*Architecture research for: React + TypeScript operator console grafted onto a shipped FastAPI + Jinja2 single-container app*
*Researched: 2026-08-17*
