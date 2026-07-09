# Phase 13: Module Structure & Boundaries - Research

**Researched:** 2026-07-09
**Domain:** Codebase-internal, behavior-neutral Python module decomposition (FastAPI routers, DB repo layer, pipeline orchestrator)
**Confidence:** HIGH

## Summary

This phase is pure internal refactoring of three known files with a hard behavior-neutral
constraint, not a greenfield feature — so "research" here means an exhaustive, verified
inventory of what exists today, not library/ecosystem discovery. I read all three target files
end-to-end, ran `grep`/`ast`-level audits across `app/`, `eval/`, `scripts/`, and `tests/` for
every named BOUND-01 violation, and executed `ruff` directly to test the D-15 guard-mechanism
candidate against the real codebase rather than assuming it works.

The single most consequential finding: **`ruff`'s `PLC2701` (import-private-name) rule, even
with `--preview` enabled, does NOT catch the great majority of this codebase's actual BOUND-01
violations.** It has two blind spots that both apply here: (1) it has a documented same-package
exemption — `app.pipeline.orchestrator` importing a private name from `app.pipeline.reconcile_names`
is invisible to it because both are in the flat `app.pipeline` package; (2) it only inspects
module-level import statements, never function-body (`def f(): from x import _y`) imports, and
most of this codebase's real violations (`_deliver`, `_safe_to_learn_alias`, `_HOURS_FIELDS`,
`_is_paid`, and the two function-body `_norm` imports) are exactly that pattern. Live testing
confirms `ruff check --select PLC2701 --preview app/ eval/ scripts/` finds only 1 of the ~6 known
runtime violations. **D-15's fallback — a small AST-walking test — is not optional-if-ruff-fails;
it is the only mechanism that will actually work for this codebase's flat single-level packages
and prevalent late-import style, and the planner should treat it as the primary path, not the
fallback.**

The second major finding is a complete, verified function/route inventory for all three files
(exact line numbers, section banners, and call-graph edges below), plus a precise census of every
test-file coupling point that will need mechanical retargeting: 14 `monkeypatch.setattr(repo, "fn",
...)` seams across 10 test files, 9 orchestrator-attribute monkeypatch seams across 7 test files,
6 places that patch `app.main._run_pipeline` / `app.main._resume_pipeline` by string or module
attribute (which move under D-07 to `app.routes.pipeline_glue`), one `inspect.getsource(main_mod.retrigger)`
structural test that will silently need retargeting to `app.routes.runs.retrigger`, and one
`repo._scrub` cross-boundary test access (`tests/test_persistence.py`) that requires the `app/db/repo/`
package facade to re-export the private `_scrub` name too, not just the public API, or that test
breaks. All of this is consistent with — and sharpens — the D-01 through D-15 decisions already
locked in CONTEXT.md; nothing here contradicts them.

**Primary recommendation:** Build D-15's BOUND-01 guard as an AST-walking test from day one (skip
the ruff-rule attempt — it's proven not to work for this codebase's layout), and sequence the
repo/main/orchestrator splits with `git mv` + mechanical import-path retargeting exactly as D-01–D-14
specify, using the test-coupling census below as the literal checklist per split.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| HTTP route registration / app assembly | API / Backend (FastAPI) | — | `app/main.py` → thin assembly; routes move to `app/routes/*` APIRouters, same tier |
| Webhook ingest + reply routing | API / Backend | Pipeline (orchestrator) | Stays a route (`routes/webhook.py`); delegates to orchestrator via `pipeline_glue` |
| Operator gate (approve/reject/resolve/retrigger) | API / Backend | Pipeline (orchestrator) | `routes/runs.py`; calls into `orchestrator`/`delivery`/`alias_learning` via module-object imports |
| Dashboard rendering (Jinja2) | API / Backend (SSR) | — | `routes/dashboard.py`; no client-side framework, server-rendered only |
| Demo affordances | API / Backend | — | `routes/demo.py`; same tier as other routes, isolated by concern only |
| Health probes | API / Backend | Database / Storage | `routes/health.py`; `/health/ready` and `/health/schema` touch Postgres directly |
| DB persistence / state machine writes | Database / Storage | API / Backend (repo is the sole writer) | `app/db/repo/` package; CAS status writes, JSONB persistence |
| Pipeline orchestration (extract→reconcile→validate→decide→persist) | API / Backend (business logic) | — | `app/pipeline/orchestrator.py` core state machine, unchanged tier, just split internally |
| Alias-learning rule set | API / Backend (business logic) | Database / Storage (writes via repo) | New `app/pipeline/alias_learning.py`; pure decision logic + repo calls |
| Clarification drafting/sending | API / Backend | External (LLM + email gateway) | New `app/pipeline/clarification.py` |
| Confirmation delivery (PDF + email) | API / Backend | External (email gateway) | New `app/pipeline/delivery.py` |

This phase does not change any tier boundary — it only subdivides modules that already live in
the API/Backend and Database tiers into per-concern files. No capability moves tiers.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STRUCT-01 | `app/main.py` split into APIRouter modules by concern, `main.py` reduced to thin assembly | Full 19-route inventory below, mapped to `webhook.py`/`runs.py`/`dashboard.py`/`demo.py`/`health.py` per D-05/D-06; shared-helper landing zone (`pipeline_glue.py`, `templating.py`) verified against actual call sites |
| STRUCT-02 | `app/db/repo.py` split into per-aggregate modules behind a stable import surface | Full 55-function inventory below with existing section banners confirmed as accurate pre-existing cut lines; both `from app.db import repo` and `import app.db.repo as X` import styles confirmed in live use (17+ files), justifying the D-01 package-facade approach; intra-repo public→public call graph confirmed (matches CONTEXT.md's D-03 claim exactly) |
| STRUCT-03 | Alias-learning helpers carved out of `orchestrator.py` into their own module | Full function inventory of orchestrator.py with call-graph edges between `_normalize_candidate`/`_bind_evidence_for_token`/`_write_aliases_if_safe`/`_safe_to_learn_alias`/`_clarify`/`_deliver` traced precisely — confirms D-09/D-10's grouping is call-graph-correct |
| STRUCT-04 | Every split behavior-neutral; suite passes with import-path updates only | Complete test-coupling census: 14 repo monkeypatch seams, 9 orchestrator monkeypatch seams, 6 `app.main._run_pipeline`/`_resume_pipeline` patch sites, 1 `inspect.getsource` structural test, 1 cross-boundary `repo._scrub` test access — this is the literal list of files/lines STRUCT-04 verification must check |
| BOUND-01 | Cross-module `_private` imports promoted to public names; guard added | Verified all D-14-listed violations still exist at the stated locations; discovered PLC2701 (ruff's own candidate rule) does NOT catch same-package or function-body private imports — decisively informs the D-15 guard-mechanism choice toward the AST-walking test |

</phase_requirements>

## Standard Stack

Not applicable in the conventional sense — no new runtime dependencies are being added. This
phase touches only code organization. The one tooling question (BOUND-01's regression guard,
D-15) is answered below under Architecture Patterns / Don't Hand-Roll.

### Version verification

No new packages. `ruff 0.15.18` (already pinned via `uv.lock`, confirmed via `uv run ruff --version`)
is the version this research validated the `PLC2701` finding against.

## Package Legitimacy Audit

Not applicable — this phase installs no new packages. `ruff` and `pytest` are pre-existing dev
dependencies (added in Phase 12); no new entries.

## Architecture Patterns

### System Architecture Diagram

```
Inbound HTTP request
        │
        ▼
┌───────────────────────────┐
│  app/main.py (thin)       │  create app, register routers, wire startup
│  (~100 lines post-split)  │
└───────────┬────────────────┘
            │ app.include_router(...)
            ▼
┌─────────────────────────────────────────────────────────────────┐
│  app/routes/  (APIRouter modules, by URL-prefix concern)         │
│  webhook.py   → POST /webhook/inbound                            │
│  runs.py      → everything under /runs* (list/detail/status/     │
│                  approve/reject/resolve/retrigger/pdf/sim-reply) │
│  dashboard.py → GET /, /eval, /eval/chart.svg                    │
│  demo.py      → POST /demo/bind, /demo/compose, /demo/send-test  │
│  health.py    → GET /health/live, /ready, /schema                │
│  templating.py → shared Jinja2Templates instance + badge filters │
│  pipeline_glue.py → _run_pipeline/_resume_pipeline/_route_reply/ │
│                  _reply_sender_ok/_row_to_inbound/                │
│                  _finish_reply_resume/_operator_resume            │
└───────────────┬───────────────────────────────────────────────────┘
                │ module-object calls (repo.fn(...), delivery.deliver(...))
                ▼
┌─────────────────────────────────────────────────────────────────┐
│  app/pipeline/orchestrator.py (core state machine, ~800-900 lines)│
│  run_pipeline / _run / resume_pipeline / _run_stages /            │
│  _compute_line_items / backfill_extracted                        │
│        │ module-object calls                                     │
│        ├──▶ app/pipeline/alias_learning.py                       │
│        │    (normalize_candidate, bind_evidence_for_token,       │
│        │     write_aliases_if_safe, safe_to_learn_alias)         │
│        ├──▶ app/pipeline/clarification.py                        │
│        │    (clarify, combined_context_email, render_asked_      │
│        │     summary, defer_field_regression_clarification)      │
│        └──▶ app/pipeline/delivery.py                             │
│             (deliver)                                            │
└───────────────┬───────────────────────────────────────────────────┘
                │ module-object calls (repo.fn(...))
                ▼
┌─────────────────────────────────────────────────────────────────┐
│  app/db/repo/  (package; __init__.py re-exports full public API)  │
│  runs.py            — lifecycle, status CAS, sweep, error+scrub   │
│  pipeline_state.py  — extracted/decision/line-items/clarify JSONB │
│  emails.py          — email_messages, threading, header lookups   │
│  roster.py          — roster read                                 │
│  demo.py            — demo binding, dashboard list queries        │
│  _shared.py         — _conn_ctx / _nulltx (internal plumbing)     │
└───────────────┬───────────────────────────────────────────────────┘
                │ psycopg
                ▼
           Supabase Postgres
```

Reading order for a hiring manager: `app/main.py` (assembly) → `app/routes/runs.py` (the whole
operator-gate flow in one file, per the D-06 grouping decision) → `app/pipeline/orchestrator.py`
(the state machine) → `app/db/repo/` (persistence). Each arrow above is a module-object call
(`repo.fn(...)`, not `from repo import fn`), which is the load-bearing pattern for keeping every
test's monkeypatch seam valid post-split (see Don't Hand-Roll / D-11).

### Recommended Project Structure

```
app/
├── main.py                      # ~100 lines: create app, include_router x5, startup/shutdown
├── routes/
│   ├── __init__.py
│   ├── templating.py            # Jinja2Templates instance + badge_class/badge_label filters
│   ├── pipeline_glue.py         # HTTP<->orchestrator bridge helpers, PUBLIC names (BOUND-01)
│   ├── webhook.py                # POST /webhook/inbound
│   ├── runs.py                   # everything under /runs* + _build_alias_rationale_notes
│   ├── dashboard.py              # GET /, /eval, /eval/chart.svg
│   ├── demo.py                   # POST /demo/bind, /demo/compose, /demo/send-test
│   └── health.py                 # GET /health/live, /ready, /schema
├── db/
│   ├── repo/
│   │   ├── __init__.py           # re-exports full public API (facade, D-01)
│   │   ├── _shared.py            # _conn_ctx, _nulltx (internal)
│   │   ├── runs.py               # lifecycle + status CAS + sweep + error/scrub
│   │   ├── pipeline_state.py     # persist/load extracted/decision/line-items/clarify context
│   │   ├── emails.py             # email_messages + threading/header lookups
│   │   ├── roster.py             # load_roster_for_business
│   │   └── demo.py               # demo binding + dashboard list queries
│   ├── bootstrap.py               # unchanged
│   ├── schema_introspect.py       # unchanged
│   ├── schema.sql                 # unchanged
│   ├── seed.py                    # unchanged
│   └── supabase.py                # unchanged
└── pipeline/
    ├── orchestrator.py            # core state machine only, ~800-900 lines
    ├── alias_learning.py          # NEW — the single home for the learning rule set
    ├── clarification.py           # NEW — _clarify + its helper cluster
    ├── delivery.py                 # NEW — _deliver
    ├── reconcile_names.py          # unchanged except _norm -> normalize_name promotion
    ├── validate.py                 # unchanged except _is_paid/_HOURS_FIELDS promotion
    ├── calculate.py, decide.py, extract.py, compose_email.py, pdf.py,
    │   suggest.py, federal_withholding.py, tax_tables_2026.py    # unchanged
    └── __init__.py
```

### Pattern 1: Package-facade split (repo.py → repo/ package)

**What:** Convert a flat module into a package whose `__init__.py` re-exports every name the
old flat module exposed, so `from app.db import repo` and `import app.db.repo as repo_mod` both
keep working unchanged, and `repo.fn` / `monkeypatch.setattr(repo, "fn", ...)` resolve identically.

**When to use:** Any time a module has many external call sites using both import styles and a
locked no-hard-migration constraint (D-01).

**Example (pattern, not existing code):**
```python
# app/db/repo/__init__.py
"""DB repo package facade — re-exports the full public API so existing callers
(`from app.db import repo`, `import app.db.repo as repo_mod`) and test monkeypatch
seams (`monkeypatch.setattr(repo, "fn", ...)`) keep working unchanged post-split."""
from app.db.repo.runs import (
    insert_inbound_email, find_business_by_sender, create_run, load_run,
    set_status, claim_status, sweep_stranded_runs, record_run_error,
    # ... (and the private _scrub, since tests/test_persistence.py accesses
    # repo._scrub directly — see Common Pitfalls)
    _scrub,
)
from app.db.repo.pipeline_state import (
    persist_extracted, persist_decision, persist_reconciliation,
    replace_line_items, set_alias_candidates, clear_reply_context, # ...
)
from app.db.repo.emails import (
    insert_email_message, get_outbound_message_id, mark_reply_consumed, # ...
)
from app.db.repo.roster import load_roster_for_business
from app.db.repo.demo import list_businesses, bind_demo_business, get_demo_binding
```

Because `monkeypatch.setattr(repo, "fn", ...)` patches the **attribute on the `repo` package
object** (i.e. on `__init__.py`'s namespace), this only works transparently if the internal
call sites that need the patched behavior also go through the package object, not a direct
`from app.db.repo.runs import fn` inside another repo submodule. D-03's invariant ("no public
function calls another public function across aggregates today") is exactly what makes this
safe — the planner must still verify each new submodule that needs a sibling's public helper
imports the sibling module directly (`from app.db.repo import pipeline_state; pipeline_state.fn(...)`),
never re-importing through the package `__init__` (which would risk a circular import at package
init time).

### Pattern 2: Module-object import discipline for the orchestrator split (D-11)

**What:** Every carved-out orchestrator helper is imported as `from app.pipeline import <module>`
then called as `<module>.<fn>(...)`, never `from app.pipeline.<module> import <fn>`.

**When to use:** Any split where tests currently do `monkeypatch.setattr(orch, "_fn", ...)` — this
pattern gives the *new owning module* exactly one canonical patch seam (`monkeypatch.setattr(alias_learning,
"write_aliases_if_safe", ...)`), and lets `orchestrator.py` itself still expose a stable `orchestrator.deliver`-style
reference only if a caller explicitly needs it via the sub-module.

**Example (pattern):**
```python
# app/pipeline/orchestrator.py (post-split)
from app.pipeline import alias_learning, clarification, delivery

def _deliver_via_route(...):
    ...
    delivery.deliver(run_id, run)   # was: _deliver(run_id, run) in-module

# app/routes/runs.py
from app.pipeline import delivery
...
    delivery.deliver(run_id, run)   # replaces the old lazy `from app.pipeline.orchestrator import _deliver`
```

### Pattern 3: FastAPI APIRouter split sharing templates/DB/settings

**What:** Each `app/routes/*.py` module creates its own `router = APIRouter()`, imports the
shared `templates` object from `app/routes/templating.py` (not from `app.main`, avoiding a
routes→main circular import), and calls `repo.fn(...)` / `get_settings()` exactly as `main.py`
does today — no new DB pool or settings object is created per router.

**Example (pattern):**
```python
# app/routes/templating.py
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")

def _badge_class_filter(status: str) -> str: ...
def _badge_label_filter(status: str) -> str: ...

templates.env.filters["badge_class"] = _badge_class_filter
templates.env.filters["badge_label"] = _badge_label_filter

# app/routes/runs.py
from fastapi import APIRouter
from app.routes.templating import templates
from app.db import repo

router = APIRouter()

@router.get("/runs")
def runs_list(request: Request, background_tasks: BackgroundTasks):
    ...
    return templates.TemplateResponse(request, "runs_list.html", {...})

# app/main.py
from fastapi import FastAPI
from app.routes import webhook, runs, dashboard, demo, health

app = FastAPI(title="Payroll Agent")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(health.router)
app.include_router(webhook.router)
app.include_router(runs.router)
app.include_router(dashboard.router)
app.include_router(demo.router)
```

Verified: `app.main` is imported by zero files under `app/` today (confirmed via grep), and
`app.pipeline.orchestrator` is imported only by `app.main` today — so `routes/* → pipeline/*` is
strictly one-directional and introduces no circular-import risk.

### Anti-Patterns to Avoid

- **Re-deriving business logic while moving it:** D-11/CONTEXT.md's "verbatim move" rule is not
  optional — any signature change, added validation, or reordering during a split makes it
  impossible to distinguish a genuine STRUCT-04 regression from an intentional behavior tweak.
  Rename-only for BOUND-01 promotions; copy-verbatim for everything else.
- **Importing through the new `repo/__init__.py` facade from another repo submodule:** creates a
  circular import at package-init time (`repo/__init__.py` imports `runs.py`, which if it also
  did `from app.db import repo` to reach `pipeline_state.fn` would import the package that is
  still mid-init). Submodules must import siblings directly (`from app.db.repo import pipeline_state`).
- **Patching `orchestrator.repo` after the split and expecting it to reach the new `alias_learning.py`/`delivery.py`
  modules' own `repo` reference:** each new submodule that calls `repo.fn(...)` has its OWN
  `from app.db import repo` binding; `monkeypatch.setattr(orchestrator.repo, "fn", ...)` does
  NOT affect `alias_learning.repo` or `delivery.repo` — they're separate name bindings to the
  same underlying module object, but the *module* is what's shared, not orchestrator's local name.
  In practice this is fine because `repo` is itself a singleton module object (patching
  `app.db.repo.fn` patches it everywhere) — but `monkeypatch.setattr(module_obj, "fn", ...)` patches
  the attribute lookup at the `module_obj` level, and since all files reference the *same*
  `app.db.repo` module object, this actually works uniformly. The trap is the opposite direction:
  do NOT patch `orchestrator.repo.fn` expecting it to be a *different* object per submodule — it
  is the same repo package object everywhere, which is the useful invariant, not a pitfall, but
  worth calling out because it's easy to reason about wrong.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|--------------|-----|
| Detecting cross-module `_private` imports | A ruff config tweak assumed to "just work" | A small `ast`-based pytest test walking `app/`, `eval/`, `scripts/` source trees, flagging any `ast.ImportFrom`/`ast.Import` (module-level OR nested inside function bodies) whose imported name starts with `_` and whose target module differs from the importing module | **Verified live**: `ruff check --select PLC2701 --preview app/ eval/ scripts/` finds only 1 of ~6 known violations. PLC2701 has a documented same-package exemption (this flat `app.pipeline`/`app.db` layout is exactly the excluded case) AND does not inspect function-body imports at all (confirmed via direct test against `app/main.py` and `app/pipeline/orchestrator.py`, both of which have real function-body private imports that PLC2701 reports zero findings for). Building this from `ast.walk()` is ~30-40 lines, stdlib-only, no new dependency. |
| Determining which functions can move together without breaking call graphs | Guessing module boundaries from file size alone | Trace the actual call graph first (grep for every internal call site of a candidate helper before deciding its new home) | Confirmed necessary in this research: `_normalize_candidate` and `_bind_evidence_for_token` are called from BOTH `resume_pipeline` (which stays in `orchestrator.py`) AND `_write_aliases_if_safe` (which moves to `alias_learning.py`) — a naive move would either duplicate the helpers or leave `orchestrator.py` needing to import them back from `alias_learning.py`, which D-11's module-object-import pattern handles cleanly but only if planned for explicitly. |

**Key insight:** For a behavior-neutral internal refactor, "don't hand-roll" mostly means "don't
hand-roll assumptions about what a tool catches" — the highest-value thing this research did was
actually *running* the proposed BOUND-01 guard against the real code before recommending it,
rather than trusting that a plausible-sounding ruff rule name would work.

## Common Pitfalls

### Pitfall 1: PLC2701 silently under-catches BOUND-01 violations
**What goes wrong:** A CI/local check declares BOUND-01 "enforced" via `ruff check --select PLC2701
--preview`, but 5 of 6 known violations (all the function-body ones, e.g. `_deliver` imported inside
`approve()`) pass silently, and the same-package exemption means even module-level violations
between `app.pipeline.orchestrator` and its sibling `app.pipeline.*` modules are invisible.
**Why it happens:** PLC2701 is documented (in its own `ruff rule` help text) as having a "known
problem": it does not flag same-package private imports unless the package uses PEP 420 namespace
packages (this repo's packages all have `__init__.py`, so they are NOT namespace packages — the
exemption applies in full). Separately, and independently of that exemption, live testing shows it
simply does not walk into function bodies for import statements at all.
**How to avoid:** Build the AST-walking test per Don't Hand-Roll above; do not rely on PLC2701 as
the sole or primary guard. If desired, PLC2701 can still be added as defense-in-depth (it catches
the 1 genuinely module-level cross-package case, `eval/run_eval.py`'s `_norm` import), but it must
not be treated as sufficient on its own.
**Warning signs:** A "clean ruff run" after a BOUND-01 fix that hasn't actually removed the
function-body private imports (verify by re-grepping for the exact names in D-14's inventory after
the fix, not just re-running ruff).

### Pitfall 2: `repo._scrub` test access breaks if the facade only re-exports the *public* API
**What goes wrong:** `tests/test_persistence.py` does `monkeypatch.setattr(repo, "_scrub", _boom)`
and calls `repo._scrub(message, roster=roster)` directly (6 call sites) against `from app.db import
repo`. If the new `app/db/repo/__init__.py` facade only re-exports public names (the documented
intent of D-01, "re-exports the full public API"), `repo._scrub` becomes an `AttributeError` and
this pre-existing, in-scope test breaks — which would violate STRUCT-04 ("no assertion changes").
**Why it happens:** `_scrub` is one of the internal helpers D-02 assigns to `runs.py` alongside
`record_run_error`, but it's also directly imported/tested from outside `repo.py`'s own module
today (it already crosses the file boundary in the *pre-split* codebase because tests import the
flat `repo` module and reach into its private helper — this is allowed under D-14's "tests may keep
importing same-module privates to unit-test internals" carve-out, but that carve-out was written
assuming `repo` stays one file; post-split, `_scrub` lives in `app/db/repo/runs.py`, a *different*
module than the `app.db.repo` package tests still import).
**How to avoid:** The `__init__.py` facade must re-export `_scrub` (and any other repo-private
helper directly referenced by tests — verified this research found only `_scrub` in this category
for repo.py) alongside the public API, OR `tests/test_persistence.py` needs its import retargeted
to `from app.db.repo import runs as repo_runs; repo_runs._scrub(...)` as a deliberate, individually
justified exception to "public-API-only facade." Either is a valid STRUCT-04-compliant choice;
the planner must pick one explicitly rather than let it fall through the cracks.
**Warning signs:** `test_persistence.py` failing with `AttributeError: module 'app.db.repo' has no
attribute '_scrub'` after the repo split lands.

### Pitfall 3: `app.main._run_pipeline`/`_resume_pipeline` are patched by dotted-string path in some tests
**What goes wrong:** `tests/test_webhook.py` uses `monkeypatch.setattr("app.main._resume_pipeline", ...)`
and `monkeypatch.setattr("app.main._run_pipeline", ...)` (string-form patch target, not an attribute
reference) — after D-07 moves these to `app.routes.pipeline_glue`, these string literals must be
updated to `"app.routes.pipeline_glue._resume_pipeline"` etc. AND — separately — `webhook.py` must
call them in a way where patching `pipeline_glue`'s attribute actually takes effect at the call
site (i.e. `webhook.py` should do `from app.routes import pipeline_glue; pipeline_glue.resume_pipeline_bg(...)`,
never `from app.routes.pipeline_glue import resume_pipeline_bg` — the same module-object-import
discipline as D-11, applied here too even though D-07 doesn't say it explicitly for this seam).
**Why it happens:** String-form monkeypatch targets are invisible to a simple `grep "app.main\."` if
the search doesn't also match string literals; they're easy to miss during a "mechanical" migration
pass that only looks for `import` statements and `.attr` access.
**How to avoid:** Explicitly grep for `"app.main\._` (quoted string form) in addition to attribute-form
patches before considering the migration complete. This research found exactly 2 string-form patch
sites (`tests/test_webhook.py` lines ~232-235 and ~301) plus 4 attribute-form ones across
`test_demo_landing.py` (×3) and `test_reply_redelivery.py`/`test_stuck_run_recovery.py` (module-level
`import app.main as app_main` then presumably `app_main._resume_pipeline` — verify at implementation
time, this research confirms the import but not every subsequent attribute access).
**Warning signs:** A test that imports `app.main` successfully (no ImportError, since `app.main`
still exists post-split) but silently does NOT intercept the pipeline call because the patched name
no longer matches what `webhook.py` actually calls — this fails as a flaky/wrong-behavior test, not
a clean red, making it easy to miss in a fast review.

### Pitfall 4: `inspect.getsource(main_mod.retrigger)` is a structural test, not a monkeypatch — easy to miss in a patch-target grep
**What goes wrong:** `tests/test_needs_operator.py::test_needs_operator_excluded_from_retrigger_stale_statuses`
does `import app.main as main_mod; src = inspect.getsource(main_mod.retrigger)` then AST-parses the
source to inspect a set literal inside it. After `retrigger` moves to `app/routes/runs.py`
(D-06), `main_mod.retrigger` no longer exists (`AttributeError`) even though this isn't a
`monkeypatch.setattr` call — a grep pattern looking only for `monkeypatch.setattr(main` or
`patch("app.main` will not find this.
**Why it happens:** Structural/introspection-based tests (`inspect.getsource`, `ast.parse` on a
function's own source) are a less common but real test-coupling pattern distinct from monkeypatching,
and this codebase has at least one.
**How to avoid:** Grep for `inspect.getsource` and `import app.main as` (bare import, not just
patch calls) across `tests/` as a distinct migration-scan step, separate from the monkeypatch scan.
**Warning signs:** `AttributeError: module 'app.main' has no attribute 'retrigger'` in this specific test.

### Pitfall 5: Duplicated `_HOURS_FIELDS` constants in two different files are NOT the same symbol
**What goes wrong:** `app/pipeline/calculate.py` and `app/pipeline/validate.py` each independently
define their own `_HOURS_FIELDS` tuple with identical contents. Only `validate.py`'s copy is
imported cross-module by `orchestrator.py` (and is therefore the one BOUND-01 requires promoting
to `HOURS_FIELDS`). It would be tempting, but out of scope and NOT behavior-neutral, to "fix the
duplication" by having `calculate.py` import `validate.py`'s promoted constant during this phase.
**Why it happens:** The two constants look identical and a DRY-minded pass could easily conflate
"promote this to public" with "also de-duplicate it while I'm here."
**How to avoid:** Promote `validate._HOURS_FIELDS` → `validate.HOURS_FIELDS` only; leave
`calculate._HOURS_FIELDS` exactly as-is (it's a same-module-only reference of a different tuple
with the same shape — not a BOUND-01 violation, not in scope). De-duplication, if ever wanted, is
a separate DRY refactor for a future phase, explicitly excluded by "Out of Scope: any behavior
change to pipeline/money logic" combined with the "no refactoring-while-moving" rule in CONTEXT.md's
`<domain>` section.
**Warning signs:** A diff that touches `calculate.py` at all during the BOUND-01 promotion step.

## Code Examples

### Full route → module mapping (STRUCT-01, D-05/D-06)

Verified via direct read of `app/main.py` (1,857 lines) — every `@app.get`/`@app.post` decorator:

| Route | Method | Handler | Target module |
|-------|--------|---------|----------------|
| `/health/live` | GET | `health_live` | `routes/health.py` |
| `/health/ready` | GET | `health_ready` | `routes/health.py` |
| `/health/schema` | GET | `health_schema` | `routes/health.py` |
| `/webhook/inbound` | POST | `inbound` | `routes/webhook.py` |
| `/runs/{run_id}/approve` | POST | `approve` | `routes/runs.py` |
| `/runs/{run_id}/reject` | POST | `reject` | `routes/runs.py` |
| `/runs/{run_id}/resolve` | POST | `resolve` | `routes/runs.py` |
| `/runs/{run_id}/retrigger` | POST | `retrigger` | `routes/runs.py` |
| `/` | GET | `landing` | `routes/dashboard.py` |
| `/demo/bind` | POST | `demo_bind` | `routes/demo.py` |
| `/demo/compose` | POST | `demo_compose` | `routes/demo.py` |
| `/runs` | GET | `runs_list` | `routes/runs.py` |
| `/runs/{run_id}/status` | GET | `run_status` | `routes/runs.py` |
| `/runs/{run_id}` | GET | `run_detail` | `routes/runs.py` |
| `/eval` | GET | `eval_view` | `routes/dashboard.py` |
| `/eval/chart.svg` | GET | `eval_chart` | `routes/dashboard.py` |
| `/runs/{run_id}/pdf/{employee_id}` | GET | `paystub_pdf` | `routes/runs.py` |
| `/runs/{run_id}/simulate-reply` | POST | `simulate_reply` | `routes/runs.py` |
| `/demo/send-test` | POST | `demo_send_test` | `routes/demo.py` |

19 routes total: 3 health, 1 webhook, 9 runs (matches D-06's "everything under `/runs*`"), 3
dashboard, 3 demo. Shared helpers landing in `routes/pipeline_glue.py` per D-07: `_row_to_inbound`
(~578), `_reply_sender_ok` (~607), `_finish_reply_resume` (~631), `_route_reply` (~684),
`_resume_pipeline` (~738), `_run_pipeline` (~752), `_operator_resume` (~944). App-level state
(`STALE_THRESHOLD`, `IN_FLIGHT_STATUSES`, `_DEMO_FIXTURES`, `DEMO_OPERATOR_EMAIL`, `_SEED_CONTACTS`,
`_SEED_BUSINESS_IDS`, `_BADGE_CLASS`/`_BADGE_LABEL` + filters) needs a home too — badges go to
`templating.py` per D-08; the rest are used across multiple future route modules (`STALE_THRESHOLD`
by both `runs.py`'s retrigger/list and `pipeline_glue.py`'s stranded-sweep logic) and are Claude's
discretion where exactly to land, but must NOT be duplicated — pick one owning module (likely
`routes/runs.py` for `STALE_THRESHOLD`/`IN_FLIGHT_STATUSES` since retrigger/runs_list are their
primary consumers, `routes/demo.py` for the demo constants) and have others import it.

### Full function → aggregate mapping (STRUCT-02, D-02)

Verified via direct grep of `app/db/repo.py` (1,734 lines) — every `def` plus the pre-existing
section banners (which the planner should treat as authoritative pre-drawn boundaries, confirmed
accurate by inspection):

**Ingest / run lifecycle → `runs.py`** (banner: "Ingest / run lifecycle", line 167):
`insert_inbound_email`, `link_email_to_run`, `find_business_by_sender`, `find_run_by_message_id`,
`load_business_name`, `create_run`, `load_run`, `load_source_email`, `load_inbound_email`

**Status / persistence → split across `runs.py` (status/error) and `pipeline_state.py` (JSONB)**
(banner: "Status / persistence", line 424): `set_status`, `claim_status`, `sweep_stranded_runs`,
`_build_accent_class_map`, `_compile_name_pattern`, `_scrub`, `_build_error_detail`,
`record_run_error` → these 8 are the "lifecycle + status CAS + sweep + error recording with its
`_scrub` helpers" D-02 assigns to `runs.py`. `persist_extracted`, `persist_decision`,
`persist_reconciliation`, `replace_line_items`, `set_alias_candidates`, `set_pre_clarify_extracted`,
`load_pre_clarify_extracted`, `set_clarified_fields`, `load_clarified_fields`,
`get_clarification_round`, `set_clarification_round`, `clear_reply_context`, `update_known_alias`
→ these 13 are the "persist/load extracted/decision/line-items/clarify-round JSONB context" D-02
assigns to `pipeline_state.py`.

**Email / threading → `emails.py`** (banner line 1058): `insert_email_message`,
`get_outbound_message_id`, `get_outbound_for_round`, `mark_reply_consumed`,
`load_consumed_replies`, `get_inbound_by_message_id`, `find_stranded_unconsumed_replies`,
`update_email_message_sent`, `update_email_message_state`, `get_outbound_references_chain`,
`load_outbound_emails`, `_pad_references`, `find_awaiting_reply_for_header`,
`find_any_run_for_header`, `load_thread_messages`

**Demo/dashboard → `demo.py`** (banner line 1451): `list_businesses`, `bind_demo_business`,
`get_demo_binding`, `set_record_only`, `get_record_only_flag`, `load_line_items`, `load_all_runs`
— note `load_line_items`/`load_all_runs` are physically under the "Roster" banner in the current
file layout but are dashboard/list queries by function, matching D-02's "demo binding + dashboard
list queries" wording; the planner should verify each function's actual call sites (not just its
current section banner) since 2-3 functions sit slightly off their banner in the pre-split file.

**Roster → `roster.py`** (banner line 1653): `load_roster_for_business`

**Internal plumbing → `_shared.py`**: `_conn_ctx` (line 157), `_nulltx` (line 1732)

Confirmed intra-repo call graph (matches CONTEXT.md's D-03 claim exactly, verified by direct
read): `record_run_error`/`set_clarification_round`/`set_pre_clarify_extracted` each call
`set_status` (same-aggregate, `runs.py`-internal); `update_email_message_sent` calls
`update_email_message_state` (same-aggregate, `emails.py`-internal); `create_run` calls
`get_record_only_flag` (cross-aggregate: `runs.py` → `demo.py` — this is the one call the planner
must route through a direct sibling import, e.g. `from app.db.repo import demo as repo_demo`,
inside `runs.py`, never through the package `__init__` facade to avoid circular init).

### Full function → concern mapping (STRUCT-03, D-09/D-10)

Verified via direct read of `app/pipeline/orchestrator.py` (1,843 lines):

**Stays in `orchestrator.py` (core, D-09):** `MAX_CLARIFICATION_ROUNDS`, `backfill_extracted`
(176), `run_pipeline` (267), `_run` (283), `resume_pipeline` (322), `_run_stages` (1090),
`_compute_line_items` (1801), `_RunStagesResult` dataclass (160)

**→ `alias_learning.py` (D-10):** `_normalize_candidate` (80), `_bind_evidence_for_token` (108),
`_write_aliases_if_safe` (1503) — PLUS `_safe_to_learn_alias` relocated in from
`app/pipeline/reconcile_names.py` (line 167 there), importing `reconcile_names`'s promoted
`normalize_name` (formerly `_norm`, line 39 there).

**→ `clarification.py` (D-09):** `_defer_field_regression_clarification` (937),
`_render_asked_summary` (1027), `_combined_context_email` (1055), `_clarify` (1229)

**→ `delivery.py` (D-09):** `_deliver` (1592)

Verified call-graph edges the planner must handle via module-object imports (D-11):
`resume_pipeline` (stays) calls `_normalize_candidate`/`_bind_evidence_for_token` (moving to
`alias_learning.py`) at lines ~872/~903 — so post-split, `orchestrator.py` needs
`from app.pipeline import alias_learning` and calls become
`alias_learning.normalize_candidate(...)`/`alias_learning.bind_evidence_for_token(...)`.
`_defer_field_regression_clarification` (moving to `clarification.py`) calls `_clarify` (also
moving to `clarification.py`) — same-module post-split, no cross-import needed there.
`_deliver` (moving to `delivery.py`) calls `_write_aliases_if_safe` (moving to `alias_learning.py`)
at lines ~1655/~1778 — needs `from app.pipeline import alias_learning; alias_learning.write_aliases_if_safe(...)`.
`_write_aliases_if_safe` itself calls `_safe_to_learn_alias` (also landing in `alias_learning.py`
per D-10) — same-module post-split.

### BOUND-01 violation inventory (D-14), verified live

Confirmed via `grep -rn` across `app/`, `eval/`, `scripts/`, `tests/` (2026-07-09):

| Private name | Defined in | Cross-module reference(s) | Kind |
|---|---|---|---|
| `_safe_to_learn_alias` | `app/pipeline/reconcile_names.py:167` | `app/pipeline/orchestrator.py:60` (module-level import) | module-level |
| `_HOURS_FIELDS` | `app/pipeline/validate.py:30` | `app/pipeline/orchestrator.py:62` (module-level import) | module-level |
| `_is_paid` | `app/pipeline/validate.py:39` | `app/pipeline/orchestrator.py:62` (module-level import) | module-level |
| `_norm` | `app/pipeline/reconcile_names.py:39` | `app/pipeline/orchestrator.py:138` (function-body import, inside `_bind_evidence_for_token`) | **function-body** |
| `_norm` | `app/pipeline/reconcile_names.py:39` | `app/pipeline/orchestrator.py:1342` (function-body import, inside `_write_aliases_if_safe`) — *note: this call site moves to `alias_learning.py` under D-10, so this violation is resolved by relocation, not by promotion, exactly as CONTEXT.md's D-10 states* | **function-body** |
| `_deliver` | `app/pipeline/orchestrator.py:1592` | `app/main.py:784` (function-body import, inside `approve()`) | **function-body** |
| `_norm` | `app/pipeline/reconcile_names.py:39` | `eval/run_eval.py:39` (module-level import, aliased `as _normalize`) | module-level |

All 7 confirmed still present exactly where D-14 states. The `orchestrator.py:1341` reference in
CONTEXT.md corresponds to line 1342 in the current file (off-by-one, likely pre/post a small
unrelated edit — immaterial, same call site inside `_write_aliases_if_safe`).

Rename plan (D-12/D-13, rename-in-place, all references updated same commit):
`_is_paid` → `is_paid`; `_HOURS_FIELDS` → `HOURS_FIELDS`; `_safe_to_learn_alias` →
`safe_to_learn_alias`; `_deliver` → `deliver`; `_norm` → `normalize_name`.

### AST-based BOUND-01 guard (D-15 recommended implementation)

```python
# tests/test_bound01_private_imports.py (illustrative shape — planner finalizes)
"""BOUND-01 regression guard: no function-body or module-level import of a
`_private` name from a DIFFERENT module anywhere in app/, eval/, scripts/.

Exists because ruff's PLC2701 (import-private-name) does not catch this
codebase's actual violations: it exempts same-package imports (this repo's
flat app.pipeline/app.db packages are exactly that case) and does not walk
into function bodies at all (verified live against app/main.py and
app/pipeline/orchestrator.py, both of which have real function-body private
imports PLC2701 reports zero findings for)."""
from __future__ import annotations

import ast
from pathlib import Path

SCAN_ROOTS = ["app", "eval", "scripts"]


def _module_name_for(path: Path, root: Path) -> str:
    rel = path.relative_to(root.parent).with_suffix("")
    return ".".join(rel.parts)


def _iter_private_cross_module_imports(path: Path, own_module: str):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == own_module:
                continue  # same-module import (e.g. `from . import x`) — allowed
            for alias in node.names:
                if alias.name.startswith("_") and not alias.name.startswith("__"):
                    yield node.lineno, node.module, alias.name


def test_no_cross_module_private_imports():
    violations = []
    for root_name in SCAN_ROOTS:
        root = Path(root_name)
        for py_file in root.rglob("*.py"):
            own_module = _module_name_for(py_file, root)
            for lineno, module, name in _iter_private_cross_module_imports(py_file, own_module):
                violations.append(f"{py_file}:{lineno} imports private `{name}` from `{module}`")
    assert not violations, "BOUND-01 violation(s):\n" + "\n".join(violations)
```

Note this illustrative version does not exempt `tests/` (per D-14, tests intentionally keep
same-module-private access for unit-testing internals like `calculate._money` — but that is
same-module, not cross-module, so it's already correctly outside this guard's scope by
construction; the guard only needs to scan `app/`, `eval/`, `scripts/` per D-14's stated scope,
and should NOT be pointed at `tests/` at all).

## State of the Art

Not applicable — no external ecosystem shifted here; this is an internal-only structural change.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The exact final public names for `_norm`→`normalize_name` and similar are Claude's discretion per D-13, and this research's suggested names (`normalize_name`, `HOURS_FIELDS`, `is_paid`, `safe_to_learn_alias`, `deliver`) are illustrative, matching CONTEXT.md's own examples exactly — not independently re-derived | BOUND-01 rename plan | Low — CONTEXT.md D-12 already specifies these exact names for 4 of 5; only `_norm`→`normalize_name` needed reasoning, and CONTEXT.md D-13 already suggests exactly that name too |
| A2 | The `test_needs_operator.py` `inspect.getsource(main_mod.retrigger)` test should be retargeted to `app.routes.runs.retrigger` and continues to pass unmodified in assertions (only the import target changes) | Common Pitfalls #4 | Low-Medium — if the AST structure inspected (a `set` literal) is somehow altered by the verbatim move (it shouldn't be, since D-11's move rule is copy-verbatim), the test's assertions themselves would need no change; risk is purely "did the migration checklist include this non-monkeypatch coupling point" |
| A3 | 663 tests currently collected (verified via `pytest --collect-only`) vs. the 613 figure quoted in the phase description / CONTEXT.md — the suite has grown by 50 tests since CONTEXT.md was gathered, presumably from work between phase 12 and 13 context-gathering sessions | Summary / all references to "the test suite" | Low — STRUCT-04's requirement ("full suite passes, no assertion changes") is unaffected by the exact count; the planner should use the live count (663) as the baseline to verify against at each split commit, not a stale number |

## Open Questions

1. **Where do the shared `main.py` module-level constants land** (`STALE_THRESHOLD`,
   `STALE_THRESHOLD_SECONDS`, `IN_FLIGHT_STATUSES`, `_DEMO_FIXTURES`, `_DEMO_FIXTURE_DEFAULT_KEY`,
   `DEMO_OPERATOR_EMAIL`, `_SEED_CONTACTS`, `_SEED_BUSINESS_IDS`)?
   - What we know: `_BADGE_CLASS`/`_BADGE_LABEL` + their filter functions have an explicit home
     (`templating.py`, D-08). The others are used by more than one future route module (e.g.
     `STALE_THRESHOLD` by both `runs.py`'s `retrigger`/`runs_list` AND `pipeline_glue.py`'s
     stranded-sweep logic inside `_resume_pipeline`'s call chain).
   - What's unclear: CONTEXT.md doesn't explicitly assign these; D-08 only covers templates/badges
     and `_build_alias_rationale_notes`.
   - Recommendation: land `STALE_THRESHOLD`/`STALE_THRESHOLD_SECONDS`/`IN_FLIGHT_STATUSES` in
     `routes/runs.py` (their primary/heaviest consumer) and have `pipeline_glue.py` import them
     from there; land the demo constants (`_DEMO_FIXTURES`, `DEMO_OPERATOR_EMAIL`,
     `_SEED_CONTACTS`, `_SEED_BUSINESS_IDS`) in `routes/demo.py` since `demo_bind`/`demo_compose`/
     `demo_send_test` are their primary consumers, with `routes/dashboard.py`'s `landing` importing
     what it needs from `routes/demo.py`. This is Claude's Discretion per CONTEXT.md's discretion
     list ("Exact function-to-module assignment... bounded by D-02/D-03 invariants") extended
     analogously to the route split — the planner should make an explicit choice and record it.

2. **Does the `app/db/repo/__init__.py` facade need to re-export `_scrub` specifically, or should
   `test_persistence.py` be retargeted instead?**
   - What we know: both are valid, individually-justifiable choices under D-01/D-14; this research
     found exactly this one cross-boundary private-name test dependency in `repo.py` (see Pitfall 2).
   - What's unclear: CONTEXT.md doesn't address this specific case (it wasn't cited in D-14's
     runtime-scope inventory because `tests/test_persistence.py` is test code, not runtime code —
     but the *mechanism* of reaching it, via the package facade, is a structural question D-01
     doesn't explicitly resolve).
   - Recommendation: re-export `_scrub` from the facade (simplest, zero test changes, consistent
     with "no assertion changes" spirit of STRUCT-04) — but flag it explicitly as a deliberate,
     individually-justified facade addition, not an accidental leak of internals.

## Environment Availability

Skipped — this phase has no external dependencies beyond the existing dev toolchain (`uv`,
`ruff`, `pytest`), all already verified present and pinned via `uv.lock` from Phase 12. No new
services, runtimes, or CLIs are introduced.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (via `uv run pytest -q`), no version pin beyond `pyproject.toml`'s `dev` group |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (marker registrations only; no other config) |
| Quick run command | `uv run pytest -q` (full suite; no faster subset exists or is needed — see Sampling Rate) |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map

This phase's "test" is uniquely the existing 663-test suite itself — STRUCT-04 requires it to
pass, unmodified in assertions, after every split. There is no new test-writing requirement for
STRUCT-01/02/03; the new BOUND-01 guard (below) is the one genuinely new test this phase adds.

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|---------------------|-------------|
| STRUCT-01 | `main.py` route split behavior-neutral | full suite (esp. `test_webhook.py`, `test_hitl.py`, `test_dashboard.py`, `test_demo_landing.py`, `test_needs_operator.py`, `test_reply_redelivery.py`, `test_gateway.py`, `test_concurrency_proof.py`, `test_ingest.py`, `test_stuck_run_recovery.py`, `test_threading.py`, `test_webhook_dedup_race.py`, `test_health_schema.py`) | `uv run pytest -q` | ✅ all exist today |
| STRUCT-02 | `repo.py` aggregate split behavior-neutral | full suite (esp. `test_persistence.py`, `test_claim_status.py`, `test_atomic_persist.py`, plus every file monkeypatching `repo`) | `uv run pytest -q` | ✅ all exist today |
| STRUCT-03 | orchestrator split behavior-neutral | full suite (esp. `test_delivery.py`, `test_alias_write.py`, `test_alias_full_loop.py`, `test_clarify.py`, `test_clarify_rounds.py`, `test_resume_pipeline.py`, `test_cr01_classify_union.py`, `test_combined_context.py`, `test_multiround_context_edge.py`, `test_retrigger_epoch.py`, `test_orchestrator_states.py`) | `uv run pytest -q` | ✅ all exist today |
| STRUCT-04 | zero-assertion-change verification | full suite green at every commit | `uv run pytest -q` | ✅ |
| BOUND-01 | no cross-module private imports remain, guard enforces it | new AST-walking test | `uv run pytest -q -k test_bound01` (once added) | ❌ Wave 0 — must be written |

### Sampling Rate

- **Per task commit (each mechanical split step):** `uv run pytest -q` — the whole suite, every
  time. There is no meaningful faster subset for this phase: STRUCT-04's entire point is that
  "the suite passes at every commit" is the operational definition of behavior-neutral, so partial
  runs would defeat the phase's own success criterion. At ~663 tests with a hermetic (no live
  DB/LLM) suite, this should run in well under a minute locally.
- **Per wave merge:** `uv run pytest -q` (same command; no separate integration lane needed —
  Phase 12's `concurrency-proof.yml` Postgres-backed lane is untouched and out of scope here).
- **Phase gate:** Full suite green, plus `uv run ruff check .` green (Phase 12's CI gate, which
  this phase's new `app/routes/` and `app/db/repo/` packages are automatically covered by since
  `ruff check .` has no path restriction and `pyproject.toml`'s `include = ["app*"]` auto-discovers
  new subpackages) before `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] `tests/test_bound01_private_imports.py` (or similar name) — the AST-walking guard for
  BOUND-01 (D-15); does not exist yet, must be written as part of this phase's own work, ideally
  written and passing against the pre-split code FIRST (to prove it correctly finds zero cross-module
  violations once BOUND-01's promotions land, and correctly WOULD have found the current 7 violations
  before they're fixed — a quick manual check, not a permanent red-then-green test, since the guard
  itself should never assert against still-broken production code once merged) so its detection
  logic is validated against real positives before being trusted as a regression gate.

*No other gaps — the existing 663-test suite already covers every behavior this phase must not
change; the phase adds no new application behavior to test.*

## Security Domain

### Applicable ASVS Categories

This phase makes no security-relevant changes — no new input validation surface, no new auth/session
logic, no new cryptography, no new access-control decisions. Every route/handler moves verbatim; the
webhook signature verification, sender-spoof guards (FIX-5/GAP-5/CR-5), SSRF allowlists (demo fixture
key validation), and PII-scrub logic (`_scrub`) are relocated, not altered.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | no | unchanged — no auth exists in this demo posture (WR-3, known/accepted) |
| V3 Session Management | no | n/a |
| V4 Access Control | no | operator-gate CAS logic moves verbatim, no logic change |
| V5 Input Validation | no (moves, doesn't change) | webhook svix verification, demo fixture allowlist validation — all relocated verbatim to `routes/webhook.py`/`routes/demo.py` |
| V6 Cryptography | no | n/a — no crypto in this codebase beyond svix signature verification (unchanged, in `app/email/gateway.py`, not touched by this phase) |

### Known Threat Patterns for this stack

Not applicable — no new threat surface. The one thing worth flagging as a **regression risk, not
a new threat**: `_scrub`'s PII-redaction logic (used by `record_run_error`/`_build_error_detail`
to strip employee names from error details before persistence) must move verbatim and remain
wired into the exact same call chain post-split (`runs.py`'s `record_run_error` → `_build_error_detail`
→ `_scrub`) — a split that accidentally drops this wiring (e.g. by moving `_scrub` to a different
aggregate than `record_run_error`, contra D-02's explicit "record recording with its `_scrub`
helpers" instruction) would silently reintroduce a PII leak in error logs. This is exactly why
D-02 calls this out explicitly and why this research confirms all four scrub-related private
helpers (`_build_accent_class_map`, `_ACCENT_CLASS_MAP`, `_compile_name_pattern`, `_scrub`,
`_build_error_detail`) sit together in the current file and must land together in `runs.py`.

## Sources

### Primary (HIGH confidence — direct codebase inspection + live tool execution)
- `app/main.py` (full read, 1,857 lines) — route inventory, shared helpers, module constants
- `app/db/repo.py` (full read + targeted greps, 1,734 lines) — function inventory, section banners, call graph
- `app/pipeline/orchestrator.py` (full read + targeted greps, 1,843 lines) — function inventory, call graph
- `app/pipeline/reconcile_names.py` (full read) — `_norm`/`_safe_to_learn_alias`/`deterministic_match` definitions and internal usage
- `app/pipeline/validate.py`, `app/pipeline/calculate.py` (targeted reads) — `_HOURS_FIELDS`/`_is_paid` definitions, confirmed as two distinct constants
- Live `grep -rn` across `app/`, `eval/`, `scripts/`, `tests/` for every D-14-listed private name — confirms exact current line numbers
- Live `uv run ruff check --select PLC2701 --preview` against `.`, `app/ eval/ scripts/`, `tests/`, and isolated file pairs — the PLC2701 same-package-exemption and function-body-blindness findings are directly observed, not inferred
- Live `uv run ruff rule PLC2701` — confirms the documented "Known problems" section describing the namespace-package exemption
- `.github/workflows/ci.yml`, `pyproject.toml` `[tool.ruff]`/`[tool.setuptools.packages.find]` — confirms `ruff check .` and package auto-discovery need no config change for new subpackages
- `uv run pytest --collect-only -q` — live test count (663), superseding the 613 figure in CONTEXT.md

### Secondary (MEDIUM confidence)
- None — this phase required no external/ecosystem research; all findings are direct codebase facts.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Function/route inventories (STRUCT-01/02/03 mapping): HIGH — every line number verified by direct read/grep against the live files, not training-data recall
- BOUND-01 violation inventory: HIGH — every violation independently re-confirmed via grep against current source, matching D-14's inventory exactly (one line-number drift of 1, immaterial)
- BOUND-01 guard mechanism (PLC2701 insufficiency, AST-test recommendation): HIGH — directly tested against the live repository with the pinned ruff version, not assumed from documentation alone
- Test-coupling census (monkeypatch/patch-target inventory): HIGH — exhaustive grep-based census; two pitfalls (string-form patches, `inspect.getsource`) specifically surfaced by deliberately searching beyond simple `monkeypatch.setattr(repo,` patterns
- Open questions (constant placement, `_scrub` facade re-export): MEDIUM — genuinely underspecified by CONTEXT.md, correctly flagged as Claude's Discretion rather than resolved unilaterally

**Research date:** 2026-07-09
**Valid until:** This research is tied to the exact current state of `app/main.py`, `app/db/repo.py`,
and `app/pipeline/orchestrator.py` at commit-time 2026-07-09 (post `fbfeeab`). Any further commits
to these three files before planning/execution begins should trigger a re-check of line numbers
(the structural findings — call graphs, PLC2701 behavior, test-coupling patterns — are stable and
not expected to drift; only exact line numbers would need re-verification).
