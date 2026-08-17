# Phase 22: Frontend Foundation & Runs List - Pattern Map

**Mapped:** 2026-08-17
**Files analyzed:** ~24 new/modified files (Python side: 10 new, 3 modified; frontend side: ~11 new files with
no in-repo analog; CI: 1 modified)
**Analogs found:** 10 / 13 Python-side files have a strong live-source analog. Frontend-side files (React/TS)
have **no in-repo analog** — see "No Analog Found" below; they are mapped to conventions instead of code.

**Grounding note:** every `file:line` citation below was re-read live this session (not copied from
CONTEXT.md/RESEARCH.md verbatim), per this repo's own "scope citations drift within days" lesson. Where a line
range is cited, it was confirmed against the current file content in this session's Read calls.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `tests/test_assertion_inventory.py` (registry + completeness guard, GUARD-01) | test/guard | batch/AST-walk | `tests/test_proof_mutation_targets.py` | exact (same registry+resolver shape) |
| `assertion_inventory_registry.py` or similar (the machine registry itself, GUARD-01) | utility/config | batch | `tests/test_proof_mutation_targets.py`'s `MUTATION_TARGETS` dict | exact |
| `tests/test_safety_mutation_registry.py` (GUARD-02 mutation-pinned subset) | test/guard | batch/AST-walk | `tests/test_proof_mutation_targets.py` (whole file — resolver classes `TargetPredicate`, `RegistryEntry`, the three predicate kinds) | exact |
| `app/schemas/_projection.py` (`RowProjection`, `UnclassifiedColumnError`) | model | CRUD/transform | `app/routes/runs.py::_safe_run_for_browser` (the denylist this replaces) + `app/models/status.py`-style enum/constant modules | role-match (new pattern, but the denylist it supersedes is the direct analog for *what fields matter*) |
| `app/schemas/runs_list.py` (`RunListRow`, `RunsListPage`) | model | CRUD/transform | `app/db/repo/demo.py::load_all_runs` (list projection SQL) | role-match |
| `app/schemas/run_status.py` (`RunStatusPoll`) | model | request-response | `app/routes/runs.py::run_status` (`GET /runs/{id}/status`, lines 890-917) | exact (this route's JSON body IS the DTO's field set today) |
| `tests/test_schema_projection.py` (GUARD-04) | test | CRUD/transform | precedent: `RunStatus` vs CHECK-constraint drift test, `tests/test_job_kind_drift.py` | role-match (drift-detection-by-column-name shape) |
| `tests/test_route_shadowing.py` (SHELL-01/GUARD-05 structural half) | test | request-response | none identical; closest is `tests/test_ops_route.py::test_ops_page_has_no_script_or_polling` for "read the live route table / response text and assert an absence structurally" | role-match |
| `tests/test_no_html_on_service_routes.py` (GUARD-05 response half) | test | request-response | `tests/test_ops_route.py::test_ops_page_has_no_script_or_polling` | role-match (both are content-type/body structural assertions over `TestClient`) |
| `tests/test_no_fetch_outside_poller.py` (GUARD-06 Python half) | test | batch (text-scan) | `tests/test_proof_mutation_targets.py`'s AST-scoped-search discipline (used as the "don't do a bare substring scan" cautionary precedent, explicitly acknowledged as a *weaker* text-scan in RESEARCH.md) | partial-match (pattern shape only, not full AST) |
| `app/routes/templating.py` (MODIFIED — grows `render_react_page()` + `json_script()`) | utility/config | transform | itself (existing file, 59 lines, full content read this session) | exact — this IS the file being extended |
| `app/templates/react_page.html` (NEW shell template) | component | request-response | `app/templates/runs_list.html` / `app/templates/base.html` (extends-pattern, block structure) | role-match |
| `app/main.py` (MODIFIED — no structural change expected, but the route-shadowing guard reads it) | route | request-response | itself (19 lines, already read this session) | exact |
| `Dockerfile` (MODIFIED — 3rd/4th stage added) | config | file-I/O | itself (61 lines; existing 2-stage builder/runtime split) | exact |
| `.github/workflows/ci.yml` (MODIFIED — 2 new jobs) | config | event-driven | itself (`lint`/`test`/`typecheck` jobs, lines 1-50+) | exact — copy the existing job shape, NOT `.github/workflows/eval.yml` |
| `frontend/src/hooks/usePoller.ts` | hook | streaming (polling) | **no in-repo analog** — closest *behavioral* spec is the vanilla-JS poller inline in `app/templates/runs_list.html:10-60` | no analog (cross-language); spec analog only |
| `frontend/src/pages/RunsPage.tsx`, `components/*.tsx`, `entries/runs.tsx`, `boot/pageData.ts` | component | CRUD/render | **no in-repo analog** (first frontend/ files in the repo) | no analog |
| `frontend/eslint.config.js`, `vite.config.ts`, `tsconfig.json`, `vitest.config.ts`, `package.json` | config | — | **no in-repo analog** — Python-side analogs are `pyproject.toml`'s `[tool.ruff]`/`[tool.mypy]`/`[tool.pytest.ini_options]` sections for "one config file per tool, no scattered settings" convention only | no analog (convention-only) |

## Pattern Assignments

### `tests/test_assertion_inventory.py` + the registry it reads (GUARD-01)

**Analog:** `tests/test_proof_mutation_targets.py` (full file, this session — 900+ lines; excerpts below are the
load-bearing shape, not the whole file)

**Docstring/rationale pattern** (lines 1-15, paraphrased above in this doc — copy the *reasoning style*, not the
literal text): state plainly (a) what the guard establishes, (b) what it explicitly does NOT establish, (c) why
a naive substring/regex scan was rejected in favor of an AST walk. This repo's guards are expected to carry this
kind of self-documenting justification comment, not just an assertion.

**Registry shape** (lines 746-762):
```python
MUTATION_TARGETS: dict[str, RegistryEntry] = {
    "PROOF-01": RegistryEntry(
        file="app/db/repo/jobs.py",
        function_name="claim_job",
        predicate=TargetPredicate(
            kind="sql_fragment",
            fragment="attempts = j.attempts + 1",
        ),
        proof_test_file="tests/test_queue_durability.py",
        proof_test_name="test_retrigger_survives_worker_crash_mid_lease",
        assertion_text="claimed.attempts == 1",
    ),
    ...
}
```
For GUARD-01 the registry entry shape per D-22-05 needs: `file`, `line`, `source text at inventory time`,
`route exercised`, `presence-or-absence class`, `layer (jinja/json-island/react-dom)`, `replaced_by`. Model it as
a parallel `dataclass`/`NamedTuple`, same dict-keyed-by-id shape as `RegistryEntry` above.

**Completeness-gate pattern** (lines 803-816):
```python
assert sorted(MUTATION_TARGETS) == sorted(EXPECTED_PROOF_IDS), (
    "the registry's key set must equal the canonical proof-id set exactly — "
    "no missing id, no extra id"
)

def test_registry_targets_are_mutually_distinct() -> None:
    triples = [
        (entry.file, entry.function_name, entry.predicate) for entry in MUTATION_TARGETS.values()
    ]
    assert len(triples) == len(set(triples)), (
        "two proofs sharing one (file, function, predicate) triple would mean "
        "one of them was never independently falsified"
    )
```
GUARD-01's own completeness check (D-22-06) is an AST walk over every `ast.Compare` in `tests/` scope, failing
if any `.text` comparison is missing a registry entry or lacks a layer classification — this is the *same
shape* one level up: walk source, compare found-set to registry-key-set, assert equality or explicit-zero
justification (D-22-07).

**Resolve-against-live-source pattern** (line 819 onward): `test_every_registry_entry_resolves_against_live_source`
walks to the named function via `ast.parse`, scoped to that function's subtree, explicitly excluding the
docstring node — copy this discipline for GUARD-01/02's own resolvers so a registry entry can't survive a
refactor as a stale pointer.

---

### `tests/test_safety_mutation_registry.py` (GUARD-02, D-22-11)

**Analog:** same file as above, `tests/test_proof_mutation_targets.py` — this is explicitly named in
CONTEXT.md/RESEARCH.md as the idiom to copy for the *new, sibling* safety-subset registry (D-22-11: "new
hermetic sibling, run by `ci.yml`'s existing test job... must NOT be wired into `concurrency-proof.yml`").
Reuse the three `TargetPredicate` kinds (`sql_fragment`, `assignment`, `dict_value`) as-is if the safety-critical
targets (PII scrubbing, XSS, path traversal, Reject gate) are Python-side; the JSX/TSX predicate kind (matching
an assertion inside `__INITIAL_DATA__`-parsed JSON or a Vitest DOM query) will need a **new** predicate kind —
do not force a `sql_fragment` match against TypeScript source.

**Import pattern for the new registry file:**
```python
# tests/test_safety_mutation_registry.py — NEW
from tests.test_proof_mutation_targets import RegistryEntry, TargetPredicate  # reuse the shapes if importable,
# or duplicate the small dataclasses locally if test_proof_mutation_targets.py is not meant to be an import
# target from another test module — confirm the repo's convention (grep for cross-test-file imports first).
```

---

### `app/schemas/_projection.py` (`RowProjection`, `UnclassifiedColumnError`)

**Analog:** `app/routes/runs.py::_safe_run_for_browser` (lines 220-245, read in full this session) — the
denylist this allowlist layer sits ABOVE (not replaces outright; RESEARCH.md's "State of the Art" table is
explicit: "denylist stays as an inner layer, not deleted").

**The denylist being wrapped** (verified `app/routes/runs.py:232-241`):
```python
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
for field in tuple(safe_run):
    if field in raw_fields or field.startswith("job_"):
        safe_run.pop(field, None)
```
**What survives this denylist today, confirmed this session against `RUN_COLS`** (`app/db/repo/runs.py:38-42`,
quoted verbatim):
```python
RUN_COLS = (
    "id, business_id, source_email_id, status, reply_epoch, extracted_data, decision,"
    " reconciliation, error_reason, error_detail, alias_candidates, hours_changes,"
    " pay_period_start, pay_period_end, updated_at"
)
```
Subtracting `raw_fields`: `id, business_id, source_email_id, status, reply_epoch, extracted_data, decision,
reconciliation, alias_candidates, hours_changes, pay_period_start, pay_period_end, updated_at` survive
untouched — `business_id`, `source_email_id`, `reply_epoch`, `alias_candidates`, `extracted_data`,
`reconciliation`, `decision` are all PII-or-internal and leak today. This is the concrete list `RunListRow`'s
`EXCLUDED` set must classify.

**Core pattern to write** (from RESEARCH.md Pattern 3, itself derived from this repo's Pydantic v2 usage
elsewhere in `app/models/`):
```python
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

---

### `app/schemas/runs_list.py` (`RunListRow`)

**Analog:** `app/db/repo/demo.py::load_all_runs` — the list-page SQL projection (verified this session,
`app/db/repo/demo.py:228-256`):
```python
sql = (
    "SELECT pr.id, pr.business_id, pr.status, pr.created_at, pr.updated_at,"
    " pr.error_reason, pr.error_detail,"
    " b.name AS business_name,"
    " pr.decision->'gate_reasons'->>0 AS summary_gate_reason,"
    " CASE WHEN jsonb_typeof(pr.extracted_data->'employees') = 'array'"
    "      THEN jsonb_array_length(pr.extracted_data->'employees')"
    "      ELSE 0 END AS employee_count,"
    " latest_job.attempts AS job_attempts,"
    " latest_job.max_attempts AS job_max_attempts,"
    " open_job.queue_label"
    " FROM payroll_runs pr"
    " JOIN businesses b ON pr.business_id = b.id"
    " ..."
)
```
Note `created_at` is present here but genuinely **absent** from `RUN_COLS` (confirmed by grep this session — no
match inside the `RUN_COLS` string). This is the forcing fact behind SHELL-07: `RunListRow` and a future
`RunDetailRow` (Phase 23) cannot share one Pydantic model; `RunListRow` must be built from `load_all_runs`'s
own row shape, not from `RUN_COLS`.

**Composition pattern (D-22-13):** `RunListRow` composes `RunStatusPoll` (see below) plus the five static
fields `id, created_at, business_name, summary_gate_reason, employee_count`. Model this as Pydantic model
composition (a `poll: RunStatusPoll` field or field-level inheritance — confirm which reads cleaner against
`openapi-typescript`'s output; a flat field union is likely safer for the generated TS merge logic D-22-13
describes ("TypeScript enforces the merge")).

---

### `app/schemas/run_status.py` (`RunStatusPoll`)

**Analog:** `app/routes/runs.py::run_status` (verified this session, lines 890-917) — this route's response
body IS today's de facto `RunStatusPoll` shape:
```python
@router.get("/runs/{run_id}/status")
def run_status(run_id: uuid.UUID) -> JSONResponse:
    ...
    safe_run = _safe_run_with_queue_projection(run_id, run)
    status = safe_run.get("status", "")
    return JSONResponse(
        content={
            "status": status,
            "badge_class": badge_class_filter(status),
            "badge_label": badge_label_filter(status),
            "failure": safe_run["failure"],
            "queue_label": safe_run["queue_label"],
            "queue_badge_class": safe_run["queue_badge_class"],
            "has_open_job": safe_run["has_open_job"],
        }
    )
```
Field-for-field this is the seven-field `RunStatusPoll` D-22-13 specifies (`status`, `badge_class`,
`badge_label`, `queue_label`, `queue_badge_class`, `has_open_job`, `failure`). D-22-13 says: add
`response_model=RunStatusPoll` to this exact route — a legal edit since it's a GET, not one of the 14 fenced
mutation handlers.

**Badge vocabulary source (must not be re-derived client-side):** `app/routes/templating.py:48-55`, full file
read this session (59 lines):
```python
def badge_class_filter(status: str) -> str:
    """Map a payroll_runs.status to a CSS badge class suffix."""
    return _BADGE_CLASS.get(str(status), "neutral")

def badge_label_filter(status: str) -> str:
    """Map a payroll_runs.status to its display label."""
    return _BADGE_LABEL.get(str(status), str(status).replace("_", " ").title())
```
`_BADGE_CLASS`/`_BADGE_LABEL` are 11-entry dicts (`:18-45`) — the DTO builder calls these same two functions;
never re-implement the mapping in TypeScript (RESEARCH.md's "Don't Hand-Roll" table, row 1).

---

### `app/routes/templating.py` (MODIFIED — `render_react_page()` + `json_script()`)

**Analog:** itself. Current file (full, 59 lines, read this session) has exactly one `Jinja2Templates` instance
at line 10 and two filter registrations at lines 58-59. New code is additive to this same file, not a new
module — this repo's convention is one shared `templates` object, imported by every router
(`from app.routes.templating import badge_class_filter, badge_label_filter, templates` — confirmed import line
in `app/routes/runs.py:33`).

**Fail-closed manifest loader (D-22-01) — pattern to follow, no direct analog exists yet, but the *fail-closed
default* convention is established elsewhere in this codebase** (pump token / bootstrap fence / the exact
`UnclassifiedColumnError` this phase itself introduces) — raise, don't degrade, when `manifest.json` is absent.

**`json_script()` XSS-escaping pattern (Pattern 4 in RESEARCH.md, Django precedent, not an in-repo analog but
the load-bearing shape):**
```python
_JSON_SCRIPT_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"}

def json_script(model: BaseModel) -> Markup:
    raw = model.model_dump_json()
    for ch, esc in _JSON_SCRIPT_ESCAPES.items():
        raw = raw.replace(ch, esc)
    return Markup(raw)
```

---

### `app/templates/react_page.html` (NEW)

**Analog:** `app/templates/runs_list.html` (129 lines, `{% extends "base.html" %}` structure) + `base.html` (21
lines, zero `<script>` tags, verified this session). Copy the `extends`/`block` structure; the critical rule
(Anti-Pattern in RESEARCH.md, pinned by `tests/test_ops_route.py:364,366`) is that Vite boot tags go ONLY in
`react_page.html`'s own `{% block content %}`, never hoisted into `base.html` — that placement is the entire
reason `/ops` stays script-free.

---

### `tests/test_route_shadowing.py` / `tests/test_no_html_on_service_routes.py` (GUARD-05)

**Analog:** `tests/test_ops_route.py::test_ops_page_has_no_script_or_polling` (verified this session at line
364 `def test_ops_page_has_no_script_or_polling(fake_repo):` and line 366
`assert "<script" not in response.text`) — the structural-absence assertion shape to copy: resolve the real
route table / real response through a `TestClient`, assert on the matched endpoint object or response
content-type, not on a hand-maintained string list.

**`app/main.py` route table (verified this session, full 19-line file):** line 11 is the sole `Mount`
(`/static`); lines 13-19 are seven `include_router` calls in order `health, webhook, runs, dashboard, demo,
pump, ops`. No `{path:path}` converter anywhere. New guard tests assert this stays true.

---

### `.github/workflows/ci.yml` (MODIFIED — add `frontend` + `docker build` jobs)

**Analog:** the existing `lint` job in the same file (verified this session, lines 1-50):
```yaml
on:
  pull_request:
  push:
    branches: ["master"]
  workflow_dispatch:

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    name: "Lint (ruff check)"
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4.3.1 (v4)
      - name: Set up uv + Python 3.12
        uses: astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86  # v5.4.2 (v5)
        with:
          python-version: "3.12"
      - name: Install deps (all groups)
        run: uv sync --locked
      - name: Run ruff check
        run: uv run ruff check .
```
New `frontend` and `docker build` jobs go into **this file**, as new `jobs.*` entries, inheriting the top-level
`on:`/`concurrency:`/`permissions:` block verbatim — do not create a new workflow file.

**Anti-analog, explicitly do NOT copy:** `.github/workflows/eval.yml` (verified this session, lines 1-11) has
```yaml
on:
  push:
    branches: ["master"]
  workflow_dispatch:
    ...
```
— **no `pull_request` trigger**. `ci.yml`'s own comment (lines 7-16) explains why `pull_request` is what makes
a job a pre-merge gate; copying `eval.yml`'s trigger block would silently make the new frontend/docker jobs
push-only, defeating SHELL-06.

## Shared Patterns

### Fail-closed defaults
**Source:** established convention across pump token, bootstrap fence, and (as of this phase) `UnclassifiedColumnError`/manifest-absent-raises.
**Apply to:** `render_react_page()`'s manifest loader (D-22-01), the dev-server branch default (D-22-03).
No single canonical file to cite — this is a cross-cutting house style, not one function to copy.

### Registry + completeness gate
**Source:** `tests/test_proof_mutation_targets.py` (`MUTATION_TARGETS`, `EXPECTED_PROOF_IDS`, the three
`test_registry_*` functions at lines 803-830+) and `scripts/check_proof_inventory.py` (not read this session in
full — RESEARCH.md and CONTEXT.md both name it as the same idiom; confirm its exact shape before the planner
finalizes the GUARD-01 registry file layout).
**Apply to:** GUARD-01's inventory registry, GUARD-02's safety-mutation registry, GUARD-04's `RUN_COLS`
classification test.

### Presentation vocabulary stays server-owned
**Source:** `app/routes/templating.py:18-55` (`_BADGE_CLASS`, `_BADGE_LABEL`, `badge_class_filter`,
`badge_label_filter`).
**Apply to:** every DTO that carries a `badge_class`/`badge_label`/`queue_label` field — TypeScript consumes
these as plain strings, never re-derives them.

### Allowlist over denylist, layered not replaced
**Source:** `app/routes/runs.py:220-245` (`_safe_run_for_browser`).
**Apply to:** `app/schemas/_projection.py` — the new `RowProjection` allowlist sits as an outer layer; the
existing denylist inside `_safe_run_for_browser` is not deleted this phase.

### `pull_request` trigger is what makes a CI job a pre-merge gate
**Source:** `.github/workflows/ci.yml:7-16` (comment) vs `.github/workflows/eval.yml:1-11` (anti-pattern).
**Apply to:** the new `frontend` and `docker build` jobs — add to `ci.yml`, inherit its `on:` block, never
create a separate workflow file.

## No Analog Found

Files with no close match in the codebase because `frontend/` does not exist yet — this is genuinely new
infrastructure, not a gap in analog search. The planner should use RESEARCH.md's Architecture Patterns and Code
Examples sections (package.json scripts, ESLint config, `usePoller` shape, `RunsPage`/`MutationForm` component
sketches) as the technical backbone instead of forcing a bad in-repo analog:

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `frontend/src/hooks/usePoller.ts` | hook | streaming/polling | No React/TS exists in this repo. Behavioral spec (not code shape) comes from the vanilla-JS poller at `app/templates/runs_list.html:10-60` — same URL shape, 2000ms interval, 60-attempt cap, stop condition, and swallowed fetch errors must be reproduced exactly (LIST-02 parity). |
| `frontend/src/pages/RunsPage.tsx`, `components/StatusBadge.tsx`, `components/QueueBadge.tsx`, `components/FailureSummary.tsx`, `components/OperatorNotice.tsx` | component | CRUD/render | First React components in the repo. Visual/markup spec comes from `app/templates/runs_list.html:64-115` (the exact region being replaced) — reproduce existing `.btn`/`.badge`/`.empty-state`/`state-pending-*` class names from `app/static/style.css`, do not invent new ones. |
| `frontend/src/components/MutationForm.tsx`, `ConfirmForm.tsx` | component | request-response (native POST) | No client-side form abstraction exists (all forms today are plain Jinja `<form>`, e.g. `app/templates/runs_list.html:118-128`). Being pulled forward per D-22-12/RESEARCH.md "Pull forward for Phase 23" — build against `/runs`'s one trivial demo-form use case. |
| `frontend/src/entries/runs.tsx`, `boot/pageData.ts`, `src/generated/dtos.d.ts` | entry/boot/generated-types | transform | No Vite entry points or generated-types pipeline exists. `dtos.d.ts` generation mirrors `eval/chart.svg`'s regenerate-and-`--check`-in-CI pattern (a Python-side precedent, not a frontend one). |
| `frontend/eslint.config.js`, `vite.config.ts`, `tsconfig.json`, `vitest.config.ts`, `package.json` | config | — | No JS/TS tooling config exists. `pyproject.toml`'s `[tool.ruff]`/`[tool.mypy]`/`[tool.pytest.ini_options]` sections are the only "one config file per tool" convention precedent, and it's a weak match across ecosystems. |

## Metadata

**Analog search scope:** `app/routes/`, `app/db/repo/`, `app/schemas/` (target, does not yet exist),
`app/templates/`, `tests/` (guard/proof files), `.github/workflows/`, `Dockerfile`, `app/main.py`.
**Files scanned (read or grepped live this session):** `app/routes/runs.py` (full, 1534 lines — read in two
passes), `app/routes/templating.py` (full, 59 lines), `app/db/repo/runs.py` (targeted, `RUN_COLS` at 35-45),
`app/db/repo/demo.py` (targeted, `load_all_runs` SQL at 220-260), `tests/test_proof_mutation_targets.py`
(targeted, docstring + registry + completeness-gate sections), `.github/workflows/ci.yml` (targeted, 1-60),
`.github/workflows/eval.yml` (targeted, 1-20), plus the full CONTEXT.md and RESEARCH.md (RESEARCH.md's own
live-source citations, e.g. `runs_list.html`/`base.html`/`app/main.py` line boundaries, were trusted as
already-re-verified within the same research session and not independently re-read a third time here, per the
no-re-read discipline).
**Pattern extraction date:** 2026-08-17
