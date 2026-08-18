---
phase: 22-frontend-foundation-runs-list
plan: 11
subsystem: infra
tags: [pydantic, openapi-typescript, typescript, codegen, ci, staleness-gate]

# Dependency graph
requires:
  - phase: 22-frontend-foundation-runs-list
    provides: "plan 22-07's app/schemas/ package (RunStatusPoll, RunListRow,
      RunsListPage, FailureInfo, RowProjection) this plan discovers models from;
      plan 22-05's frontend CI job this plan extends with the staleness step;
      plan 22-04's readInitialData<T>() boot module this plan retypes"
provides:
  - "scripts/generate_openapi_doc.py -- build_components_document()/main(), a
    components-schemas-only document generated from every Pydantic model named
    in app.schemas.__all__ (discovered, not hard-coded)"
  - "frontend/src/generated/dtos.d.ts -- the committed, generated TypeScript view
    of every response shape, replacing hand-written interfaces as the frontend's
    declared contract"
  - "frontend/package.json's generate:types / generate:types:check npm scripts"
  - "frontend/src/boot/pageData.ts's readInitialData() now returns the generated
    RunsListPage type instead of a caller-supplied generic <T>"
  - "SHELL-06's staleness gate: tests/test_generated_types_staleness.py (hermetic
    half, no Node) + .github/workflows/ci.yml's frontend job 'Generated DTO
    staleness' step (the Node+Python half)"
affects: [22-12]

# Actuals (#2632)
actuals:
  tokens: 6623
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pydantic's models_json_schema([(model, mode), ...], ref_template=...) used
      to build a single shared components/schemas document across multiple
      models, so a model nested inside another resolves as one shared $ref
      instead of being inlined once per referencing parent -- the same
      ref_template shape FastAPI's own OpenAPI generation uses internally"
    - "openapi-typescript 7.13.0's CLI does not accept '-' for stdin (attempted;
      throws ResolveError) -- the generate:types / generate:types:check npm
      scripts route the Python generator's stdout through a temp file
      (mktemp, no args, confirmed portable across macOS/Linux) rather than a
      pipe into the TS generator's argv"
    - "A staleness gate that needs two runtimes (Python to regenerate the source
      document, Node to run openapi-typescript) is placed in the one CI job that
      already has both, rather than split across job boundaries or given its own
      job -- the frontend job gained a Python setup step for this reason"

key-files:
  created:
    - scripts/generate_openapi_doc.py
    - frontend/src/generated/dtos.d.ts
    - tests/test_generated_types_staleness.py
  modified:
    - app/schemas/__init__.py
    - frontend/package.json
    - frontend/src/boot/pageData.ts
    - frontend/src/entries/runs.tsx
    - .github/workflows/ci.yml
    - tests/test_ci_gate_config.py

key-decisions:
  - "app/schemas/__init__.py now exports RunStatusPoll in __all__. It was
    declared in plan 22-07 but never added to the package's public export
    list -- since the generator discovers models purely from __all__ (per this
    plan's own instruction: 'discover from the package's declared public
    exports rather than a hard-coded list'), the status poll shape would have
    been silently omitted from the generated declarations without this fix.
    Not in this plan's files_modified frontmatter; edited anyway because Task
    1's own acceptance criteria ('components-schemas mapping ... includes ...
    the poll shape by name') cannot pass without it -- same precedent as plan
    22-07's own Deviation #1."
  - "frontend/src/boot/pageData.ts's readInitialData() changed from a fully
    generic <T>(): T to a concrete (): RunsListPage, where RunsListPage is a
    type alias onto the generated components['schemas']['RunsListPage']. A
    generic parameter with no constraint lets ANY caller-supplied type stand
    in regardless of what the server actually returns -- 'the boot module's
    return type is the generated list-page type' (this plan's own must_have)
    is only true if the reader's OWN declared return type is sourced from the
    generated file, not a type argument a caller happens to pass."
  - "frontend/src/entries/runs.tsx updated (not in files_modified) to drop the
    now-invalid readInitialData<RunsListPage>() type argument and the
    hand-rolled RunsListPage import from ../pages/RunsPage -- a non-generic
    function called with an explicit type argument is a compile error
    (TS2558), so this was a required fix to keep the app building, not an
    optional one. frontend/src/pages/RunsPage.tsx needed NO change: its own
    hand-rolled RunsListPage/RunListRow interfaces are structurally identical
    to the generated ones (verified field-for-field), so TypeScript's
    structural typing accepts <RunsPage data={data} /> without a cast."
  - "The 'Generated DTO staleness' CI step lives in the frontend job, which
    gained a Python setup (astral-sh/setup-uv + uv sync --locked) for it. The
    hermetic Python test job has no Node to run openapi-typescript; the
    frontend job already has Node and now also has Python -- splitting the
    check across a job boundary would mean neither job alone could prove the
    generated file matches source, so the whole check runs in one job that has
    both runtimes."
  - "RowProjection (the allowlist base class, zero fields of its own) is
    included in the generated document because it is exported in
    app.schemas.__all__ and the generator's whole point is discovering public
    models rather than curating a list by hand. It renders as
    RowProjection: Record<string, never> in the generated declarations --
    harmless, and excluding it manually would reintroduce the hand-maintained
    list this plan exists to eliminate."

requirements-completed: [SHELL-06, SHELL-07]

coverage:
  - id: D1
    description: "The frontend's view of every response shape is generated
      deterministically from the Pydantic models (never hand-written), with no
      new HTTP endpoint added to serve the document"
    requirement: "SHELL-07"
    verification:
      - kind: unit
        ref: "tests/test_generated_types_staleness.py::test_generated_document_schema_keys_equal_the_public_model_set (pass)"
        status: pass
      - kind: other
        ref: "uv run python scripts/generate_openapi_doc.py | node -e '...' -- exits 0, prints [\"FailureInfo\",\"RowProjection\",\"RunListRow\",\"RunStatusPoll\",\"RunsListPage\"]"
        status: pass
      - kind: other
        ref: "git grep -n \"app.schemas\" -- app/routes -- 2 hits, both pre-existing imports in app/routes/runs.py from plan 22-07; no new route module"
        status: pass
    human_judgment: false
  - id: D2
    description: "The generated declaration file is committed and CI fails when
      it is stale, using the same regenerate-and-diff contract the assertion
      inventory gate already uses -- split across two independent halves since
      no single CI job has both a Python and a Node runtime plus... actually
      the frontend job now has both"
    requirement: "SHELL-06"
    verification:
      - kind: unit
        ref: "tests/test_ci_gate_config.py::test_frontend_job_has_a_generated_dto_staleness_step_with_no_runtime_conditional (pass)"
        status: pass
      - kind: other
        ref: "Real red run: renamed RunListRow.employee_count -> employee_count_total, ran `cd frontend && npm run generate:types:check` -- exit 1, unified diff naming the field. See 'Demonstrated-Red Transcripts' below."
        status: pass
    human_judgment: false
  - id: D3
    description: "Regenerating the document twice produces byte-identical
      output -- the generator's own key ordering is deterministic, so the
      staleness gate cannot fail spuriously"
    requirement: "SHELL-06"
    verification:
      - kind: unit
        ref: "tests/test_generated_types_staleness.py::test_generated_document_is_byte_identical_across_two_generations (pass)"
        status: pass
      - kind: other
        ref: "Two independent `uv run python scripts/generate_openapi_doc.py` captures diffed with `diff` -- no output (byte identical); two independent full generate-and-openapi-typescript runs diffed the same way -- no output"
        status: pass
    human_judgment: false
  - id: D4
    description: "The boot module's return type is the generated list-page
      type, so reading a field the allowlist withheld is a compile error
      rather than an undefined value at runtime"
    requirement: "SHELL-07"
    verification:
      - kind: unit
        ref: "cd frontend && npm run check && npm run test -- exit 0 (typecheck/lint/43 tests)"
        status: pass
      - kind: other
        ref: "Compile-error proof: temporarily read data.runs[0]?.business_id in frontend/src/entries/runs.tsx (business_id is named in RunListRow.EXCLUDED) -- tsc failed with TS2339 naming the field. Reverted; git diff confirmed entries/runs.tsx returned to its committed state. See 'Demonstrated-Red Transcripts' below."
        status: pass
    human_judgment: false
  - id: D5
    description: "A field renamed in a Pydantic model and not regenerated
      fails CI, demonstrated for real and reverted byte-identically -- proven
      independently from both halves of the gate on the same mutation"
    requirement: "SHELL-06"
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_generated_types_staleness.py -x -q against the live employee_count -> employee_count_total rename -- 1 failed naming the field, 3 passed; reverted, then 4 passed"
        status: pass
      - kind: other
        ref: "grep -n employee_count app/schemas/runs_list.py confirmed line 94 is the live field declaration (not the docstring, which ends at line 48); git diff --stat app/schemas/runs_list.py confirmed clean after revert"
        status: pass
    human_judgment: false

duration: ~55min
completed: 2026-08-17
status: complete
---

# Phase 22 Plan 11: Generated Frontend DTOs + Staleness Gate Summary

**A components-schemas-only document generated from `app/schemas/`'s public Pydantic models feeds `openapi-typescript`, producing the committed `frontend/src/generated/dtos.d.ts` that `readInitialData()` now returns instead of a caller-supplied generic type -- closed with a two-runtime CI staleness gate demonstrated red by an actual field rename, on both halves, from the same mutation.**

## Performance

- **Duration:** ~55 min
- **Tasks:** 3 of 3 complete
- **Files modified:** 9 (3 created, 6 modified)

## Accomplishments

- `scripts/generate_openapi_doc.py`'s `build_components_document()` discovers
  every Pydantic model named in `app.schemas.__all__` (never a hard-coded
  list), guards on a non-empty discovered set, and assembles a
  components-schemas-only document via `pydantic.json_schema.models_json_schema`
  with `ref_template="#/components/schemas/{model}"` -- the same ref shape
  FastAPI's own OpenAPI generation uses, so `FailureInfo` nested inside
  `RunStatusPoll` resolves as one shared `$ref` instead of being inlined
  twice. Schema keys are sorted; two independent runs produce byte-identical
  output, verified both by the CLI (`diff`, no output) and by a hermetic test.
- `frontend/package.json` gained `generate:types` (writes the committed
  `frontend/src/generated/dtos.d.ts`) and `generate:types:check` (diffs a
  fresh regeneration against the committed file, non-zero exit on any
  difference). Both route the Python generator's stdout through a temp file
  into `openapi-typescript`'s CLI -- its `-` stdin form was tried first and
  throws a `ResolveError`, confirmed live before committing to the temp-file
  approach.
- `frontend/src/generated/dtos.d.ts` committed: five interfaces
  (`FailureInfo`, `RowProjection`, `RunListRow`, `RunStatusPoll`,
  `RunsListPage`), including the list row, the list page, and the poll shape
  by name, matching this plan's own acceptance criterion.
- `frontend/src/boot/pageData.ts`'s `readInitialData()` retyped from a fully
  generic `<T>(): T` to a concrete `(): RunsListPage`, where `RunsListPage`
  is a type alias onto the generated
  `components["schemas"]["RunsListPage"]`. Runtime behavior is byte-identical
  to before: locate the island element, parse its text content, throw a
  descriptive error when missing or unparsable -- no cast replaces the throw,
  no silent fallback to an empty object.
- `frontend/src/entries/runs.tsx` updated for the narrowed signature (dropped
  the now-invalid explicit `<RunsListPage>` type argument and the hand-rolled
  import). `frontend/src/pages/RunsPage.tsx` needed no change at all --
  verified its hand-rolled interfaces are structurally identical to the
  generated ones, so TypeScript's structural typing accepted the prop
  assignment without a cast.
- `tests/test_generated_types_staleness.py`: four hermetic (no Node) tests --
  the generated document's schema key set equals `app.schemas.__all__`'s
  model set, two generations are byte-identical, every generated schema name
  has a declared type in the committed file, and every `RunListRow` field
  (the common real failure mode -- a field added or renamed and never
  regenerated) appears in that file.
- `.github/workflows/ci.yml`'s `frontend` job gained a Python setup
  (`astral-sh/setup-uv` + `uv sync --locked`) and a "Generated DTO staleness"
  step running `npm run generate:types:check`, with no `if:` conditional
  gating it on a runtime being present. `tests/test_ci_gate_config.py` gained
  a matching structural assertion.
- Full Python suite: 1476 passed / 107 skipped (baseline 1471/107 plus 5 new
  tests -- 4 staleness + 1 CI-config). `ruff check .` and `uv run mypy` both
  clean (196 source files). Frontend: `npm run check && npm run test && npm
  run build` all exit 0 (43 tests unchanged). Regenerating both the document
  and the declarations leaves `git status --porcelain` clean.

## Task Commits

1. **Task 1: Generate a components-schemas-only document from the Pydantic
   models** -- `709234d` (feat)
2. **Task 2: Type the boot module against the generated declarations** --
   `b835ad3` (feat)
3. **Task 3: Staleness gate in CI, demonstrated red by a real field rename**
   -- `287a8ec` (test)

## Files Created/Modified

**Task 1 (`709234d`):**
- `scripts/generate_openapi_doc.py` -- new: `build_components_document()`,
  `main()`
- `app/schemas/__init__.py` -- `RunStatusPoll` added to `__all__` (see
  Deviations)
- `frontend/package.json` -- `generate:types` / `generate:types:check` scripts
- `frontend/src/generated/dtos.d.ts` -- new, generated and committed

**Task 2 (`b835ad3`):**
- `frontend/src/boot/pageData.ts` -- `readInitialData()` retyped, generated
  `RunsListPage` re-exported
- `frontend/src/entries/runs.tsx` -- call site updated for the narrowed
  signature (see Deviations)

**Task 3 (`287a8ec`):**
- `tests/test_generated_types_staleness.py` -- new: four hermetic tests
- `.github/workflows/ci.yml` -- frontend job gains Python setup + "Generated
  DTO staleness" step
- `tests/test_ci_gate_config.py` -- one new structural assertion

## Decisions Made

See `key-decisions` in the frontmatter above for the full rationale on each of:
`RunStatusPoll`'s missing `__all__` export, the generic-to-concrete
`readInitialData()` retype, the required `entries/runs.tsx` fix, the
staleness step's placement in the frontend job, and `RowProjection`'s
inclusion in the generated document.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] `app/schemas/__init__.py` did not export
`RunStatusPoll` in `__all__`**
- **Found during:** Task 1
- **Issue:** `RunStatusPoll` was declared in plan 22-07 (`app/schemas/run_status.py`)
  but plan 22-07's `__init__.py` edit never added it to `__all__`. This
  plan's generator discovers models purely via `app.schemas.__all__` (per its
  own action text: "Discover the models from the package's declared public
  exports rather than a hard-coded list"), so without this fix the poll shape
  would have been silently omitted -- failing this plan's own acceptance
  criterion ("includes the list row, the list page and the poll shape by
  name").
- **Fix:** Added `from app.schemas.run_status import RunStatusPoll` and
  `"RunStatusPoll"` to `__all__` in `app/schemas/__init__.py`. Not listed in
  this plan's frontmatter `files_modified`; edited anyway per the precedent
  plan 22-07's own Deviation #1 set (task's own acceptance criteria cannot
  pass without it).
- **Files modified:** `app/schemas/__init__.py`
- **Verification:** `uv run python scripts/generate_openapi_doc.py | node -e
  '...'` confirms `RunStatusPoll` present; `uv run pytest -q` 1476/107, no
  regressions; `uv run ruff check .` and `uv run mypy` both clean.
- **Committed in:** `709234d` (Task 1 commit)

**2. [Rule 3 - Blocking] `frontend/src/entries/runs.tsx`'s
`readInitialData<RunsListPage>()` call no longer typechecks after the boot
module's generic parameter was removed**
- **Found during:** Task 2
- **Issue:** Retyping `readInitialData` from `<T>(): T` to `(): RunsListPage`
  (required by this plan's own must_have: "the boot module's return type is
  the generated list-page type") makes any caller that still supplies an
  explicit type argument a compile error: `tsc` failed with `TS2558:
  Expected 0 type arguments, but got 1` at the real call site.
- **Fix:** Changed `readInitialData<RunsListPage>()` to `readInitialData()`
  and dropped the now-unused `type RunsListPage` import from
  `../pages/RunsPage`. `frontend/src/pages/RunsPage.tsx` was NOT edited --
  confirmed the generated type is structurally identical to its hand-rolled
  interfaces, so the prop assignment still typechecks.
- **Files modified:** `frontend/src/entries/runs.tsx` (not in this plan's
  `files_modified` frontmatter -- necessary because the app would not
  compile otherwise)
- **Verification:** `cd frontend && npm run check && npm run test` exits 0
  (43/43 tests); `npm run build` exits 0.
- **Committed in:** `b835ad3` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 Rule 2 - missing critical, 1 Rule 3 -
blocking). **Impact on plan:** No scope creep. Both fixes were necessary for
the plan's own stated acceptance criteria/must_haves to be achievable at all
-- without #1 the generated document would silently omit the poll shape;
without #2 the frontend would not compile.

## Issues Encountered

- `openapi-typescript@7.13.0`'s CLI does not accept `-` as a stdin
  placeholder for its input argument (confirmed live: throws
  `ResolveError: ENOENT ... /frontend/-`). Worked around by routing the
  Python generator's stdout through a `mktemp`-created temp file before
  invoking the TS generator, in both `generate:types` and
  `generate:types:check`. This does not change the plan's intended behavior
  (still Python generator -> TypeScript generator -> committed file); it is
  an implementation detail of how the two CLIs are joined.

## User Setup Required

None -- no external service configuration required.

## Demonstrated-Red Transcripts

### 1. Compile-error proof (Task 2): reading a withheld field from a consuming component

Confirmed `business_id` is in `RunListRow.EXCLUDED`:
```
$ grep -n "business_id" app/schemas/runs_list.py
56:            "business_id",
```

Temporarily added to `frontend/src/entries/runs.tsx`:
```ts
const data = readInitialData();
const _CI_GATE_PROOF_WITHHELD_FIELD = data.runs[0]?.business_id;
const mountElement = document.getElementById(MOUNT_ELEMENT_ID);
```

```
$ cd frontend && npm run typecheck
> tsc --noEmit -p tsconfig.json && tsc --noEmit -p tsconfig.node.json
src/entries/runs.tsx(13,7): error TS6133: '_CI_GATE_PROOF_WITHHELD_FIELD' is declared but its value is never read.
src/entries/runs.tsx(13,53): error TS2339: Property 'business_id' does not exist on type '{ status: string; badge_class: string; badge_label: string; failure: { secondary_label: string | null; stage: string | null; reason: string | null; attempts: string | null; }; queue_label: string | null; ... 7 more ...; employee_count: number; }'.
EXIT: 2
```

Reverted:
```
$ git diff frontend/src/entries/runs.tsx
diff --git a/frontend/src/entries/runs.tsx b/frontend/src/entries/runs.tsx
index 8583e21..f626503 100644
--- a/frontend/src/entries/runs.tsx
+++ b/frontend/src/entries/runs.tsx
@@ -4,12 +4,12 @@
 import { createRoot } from "react-dom/client";

 import { readInitialData } from "../boot/pageData";
-import { RunsPage, type RunsListPage } from "../pages/RunsPage";
+import { RunsPage } from "../pages/RunsPage";

 // Must match app/routes/templating.py's REACT_MOUNT_ID literal exactly.
 const MOUNT_ELEMENT_ID = "react-root";

-const data = readInitialData<RunsListPage>();
+const data = readInitialData();
 const mountElement = document.getElementById(MOUNT_ELEMENT_ID);
```
(This diff is the required permanent fix, not the proof mutation -- the proof
line itself left no trace once removed; `npm run typecheck` then exits 0
again.)

### 2. Staleness gate, hermetic half (Task 3): real field rename

Confirmed the mutation target is the live field, not a docstring copy:
```
$ grep -n "class RunListRow" -A3 app/schemas/runs_list.py
27:class RunListRow(RunStatusPoll, RowProjection):
28-    """One row of the /runs list -- exactly the fields `runs_list.html` rendered
29-    before conversion, no more.
30-
$ grep -n "employee_count" app/schemas/runs_list.py
94:    employee_count: int = 0
```
Line 94 is well past the docstring (which ends at line 48) and the `EXCLUDED`
block (ends line 84) -- it is the live Pydantic field declaration.

**The mutation:**
```diff
-    employee_count: int = 0
+    employee_count_total: int = 0
```

**The RED** -- `uv run pytest tests/test_generated_types_staleness.py -x -q`:
```
...F
=================================== FAILURES ===================================
_____ test_every_run_list_row_field_appears_in_the_committed_declarations ______
E       AssertionError: field(s) ['employee_count_total'] are declared on RunListRow but do not appear in the committed frontend/src/generated/dtos.d.ts -- regenerate with `npm run generate:types` from inside frontend/.
E       assert not ['employee_count_total']
tests/test_generated_types_staleness.py:116: AssertionError
1 failed, 3 passed, 1 warning in 0.19s
```

### 3. Staleness gate, frontend-job half (Task 3): same mutation, different transcript

```
$ cd frontend && npm run generate:types:check
✨ openapi-typescript 7.13.0
🚀 <tmp> → <tmp> [20.1ms]
--- src/generated/dtos.d.ts	2026-08-17 17:02:23
+++ <tmp>	2026-08-17 17:11:03
@@ -98,10 +98,10 @@
              */
             summary_gate_reason: string | null;
             /**
-             * Employee Count
+             * Employee Count Total
              * @default 0
              */
-            employee_count: number;
+            employee_count_total: number;
         };
         /**
          * RunStatusPoll
exit:1
```

**The revert:**
```
$ git diff --stat app/schemas/runs_list.py
 app/schemas/runs_list.py | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)
$ git checkout -- app/schemas/runs_list.py
$ git diff --stat app/schemas/runs_list.py
(no output -- clean)
```

**Green again (both halves):**
```
$ uv run pytest tests/test_generated_types_staleness.py tests/test_ci_gate_config.py -x -q
18 passed, 1 warning in 0.25s
$ cd frontend && npm run generate:types:check
exit:0
```

## Next Phase Readiness

- Every response shape the `/runs` page reads is now generated from the same
  Pydantic models FastAPI itself validates against, and CI fails on drift
  from two independent directions (a Node+Python job diff, and a hermetic
  Python-only field-presence check) -- both demonstrated red on the same
  real mutation.
- A future page conversion that adds a new schema to `app/schemas/__all__`
  is picked up by the generator automatically; forgetting to run
  `npm run generate:types` after such a change fails CI by name via either
  half of the gate.
- No new HTTP endpoint exists to serve the generated document -- confirmed by
  `git grep` and unchanged by this plan (2 pre-existing hits in
  `app/routes/runs.py`, both from plan 22-07).
- `RowProjection`'s appearance in the generated declarations
  (`Record<string, never>`) is a harmless side effect of __all__-driven
  discovery, not something a future plan needs to clean up.

## Self-Check: PASSED

- All three created files (`scripts/generate_openapi_doc.py`,
  `frontend/src/generated/dtos.d.ts`, `tests/test_generated_types_staleness.py`)
  confirmed present via `Read`.
- All three task commits (`709234d`, `b835ad3`, `287a8ec`) confirmed present
  via `git log --oneline`.
- `uv run pytest tests/test_generated_types_staleness.py tests/test_ci_gate_config.py -x -q`
  -- 18 passed.
- `uv run pytest -q` -- 1476 passed, 107 skipped (matches baseline 1471/107 +
  5 new tests).
- `uv run ruff check .` and `uv run mypy` both clean (196 source files).
- `cd frontend && npm run check && npm run test && npm run build` -- all exit
  0 (43/43 tests).
- Regenerating the document and the declarations (`npm run generate:types`)
  leaves `git status --porcelain` clean.
- `git diff --name-only <fork-base> HEAD` confirmed limited to
  `.github/workflows/ci.yml`, `app/schemas/__init__.py`,
  `frontend/package.json`, `frontend/src/boot/pageData.ts`,
  `frontend/src/entries/runs.tsx`, `frontend/src/generated/dtos.d.ts`,
  `scripts/generate_openapi_doc.py`, `tests/test_ci_gate_config.py`,
  `tests/test_generated_types_staleness.py` -- none of plan 22-10's claimed
  files (`frontend/src/hooks/usePoller.ts`, `frontend/src/pages/RunsPage.tsx`,
  `RunsPage.test.tsx`, `tests/test_no_fetch_outside_poller.py`) touched.
- No missing items.

---
*Phase: 22-frontend-foundation-runs-list*
*Completed: 2026-08-17*
