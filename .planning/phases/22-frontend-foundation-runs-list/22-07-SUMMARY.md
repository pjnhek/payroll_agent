---
phase: 22-frontend-foundation-runs-list
plan: 07
subsystem: api
tags: [pydantic, fastapi, openapi, allowlist-dto, guard-04]

# Dependency graph
requires:
  - phase: 22-frontend-foundation-runs-list
    provides: "plan 22-04's RowProjection allowlist base, RunListRow/RunsListPage
      DTOs, and the app/schemas/ package this plan extends"
provides:
  - "app/schemas/run_status.py -- RunStatusPoll (the declared, OpenAPI-visible
    response_model for GET /runs/{run_id}/status) and FailureInfo"
  - "app/schemas/run_columns.py -- ColumnExposure + RUN_COL_CLASSIFICATION, an
    explicit three-way exposure decision for every one of the fifteen live
    app.db.repo.runs.RUN_COLS columns"
  - "GUARD-04: a hermetic drift test that fails by column name the moment an
    unclassified column reaches RUN_COLS, demonstrated red against a real
    mutation and reverted byte-identical"
  - "RunListRow now composes RunStatusPoll's seven volatile fields via multiple
    inheritance instead of restating them"
affects: [22-10, 22-11, 22-23]

# Actuals (#2632)
actuals:
  tokens: 5178
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Declared response_model on a GET route that previously built its own
      JSONResponse -- returning the model instance itself (not a pre-built
      Response) is what makes response_model validation actually run"
    - "Flat-field multiple inheritance for a shared volatile sub-shape
      (RunListRow(RunStatusPoll, RowProjection)) instead of a nested
      sub-object field, chosen so a poller can merge its response straight
      onto an existing row object with an object spread"
    - "Three-way exposure classification (list_exposed / detail_exposed /
      internal_only) as a dict keyed by live-parsed column names, checked by
      a hermetic drift test rather than trusted by inspection"

key-files:
  created:
    - app/schemas/run_status.py
    - app/schemas/run_columns.py
  modified:
    - app/routes/runs.py
    - app/schemas/runs_list.py
    - tests/test_schema_projection.py

key-decisions:
  - "RunListRow composes RunStatusPoll's seven fields via Python multiple
    inheritance (class RunListRow(RunStatusPoll, RowProjection)) rather than
    a nested `poll: RunStatusPoll` field. A flat field union is what lets a
    future poller merge its RunStatusPoll response straight onto an existing
    row object with a plain object spread ({...row, ...pollResponse}); a
    nested field would force every call site to merge into a sub-key instead.
    Verified in Pydantic directly: RunListRow.model_fields carries all
    thirteen fields (six from RunStatusPoll, seven of its own) with a single
    merged model_config (extra=forbid, frozen=True)."
  - "FailureInfo moved from app/schemas/runs_list.py to app/schemas/run_status.py
    (RunStatusPoll's own nested shape) and is re-exported from runs_list.py by
    import, not redefinition -- app/schemas/__init__.py's existing
    `from app.schemas.runs_list import FailureInfo` import keeps working
    unmodified."
  - "RUN_COL_CLASSIFICATION classifies extracted_data/reconciliation/decision/
    hours_changes as detail_exposed because all four are rendered raw in
    app/templates/run_detail.html today (grep-confirmed), while business_id/
    source_email_id/reply_epoch/alias_candidates are internal_only because none
    of the four ever appears in that template's markup -- they drive
    server-side roster lookups, dedup bookkeeping, and pipeline resolution
    state only."
  - "pay_period_start/pay_period_end classified internal_only, not
    detail_exposed. Both are read server-side to build the on-demand paystub
    PDF (app/routes/runs.py::paystub_pdf -> app/pipeline/pdf.py), a separate,
    already-gated download route -- neither date appears as raw text in the
    run detail page's own HTML/JSON response shape (grep-confirmed against
    app/templates/run_detail.html). Reaching the operator only through a
    distinct downstream artifact is not the same exposure surface this
    phase's threat model addresses (the payroll_runs table -> browser JSON/
    HTML trust boundary), so a future page-DTO conversion is not implicitly
    promised for these two columns the way it is for the four detail_exposed
    ones."
  - "app/schemas/runs_list.py was edited even though it is not listed in this
    plan's frontmatter files_modified -- see Deviations. The refactor Task 1's
    own action text and acceptance criteria require it (RunListRow must
    compose RunStatusPoll's fields), and no other wave-4 plan claims this
    file."

requirements-completed: [SHELL-07, GUARD-04]

coverage:
  - id: D1
    description: "RunStatusPoll declared and enforced as GET /runs/{run_id}/status's response_model, appears natively in the app's OpenAPI document, and the wire body is verified byte-identical to the pre-change hand-built JSON for two fixtures"
    requirement: "SHELL-07"
    verification:
      - kind: unit
        ref: "tests/test_dashboard.py -k status (4 passed)"
        status: pass
      - kind: other
        ref: "uv run python -c \"from app.schemas.run_status import RunStatusPoll; f=set(RunStatusPoll.model_fields); assert f=={'status','badge_class','badge_label','queue_label','queue_badge_class','has_open_job','failure'}\" (exit 0)"
        status: pass
      - kind: other
        ref: "uv run python -c \"...get_openapi(...); assert 'RunStatusPoll' in s['components']['schemas']\" (exit 0)"
        status: pass
    human_judgment: false
  - id: D2
    description: "RunListRow composes RunStatusPoll's seven fields via multiple inheritance rather than restating them"
    requirement: "SHELL-07"
    verification:
      - kind: unit
        ref: "uv run python -c \"from app.schemas.runs_list import RunListRow; print(sorted(RunListRow.model_fields))\" -- all 13 fields present, single merged model_config"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every one of the fifteen live RUN_COLS columns has exactly one deliberate exposure classification (list_exposed / detail_exposed / internal_only)"
    requirement: "GUARD-04"
    verification:
      - kind: unit
        ref: "uv run python -c \"from app.schemas.run_columns import RUN_COL_CLASSIFICATION as C, ColumnExposure; assert len(C)==15\" (exit 0)"
        status: pass
      - kind: unit
        ref: "tests/test_schema_projection.py::test_run_col_set_is_non_empty_and_known, ::test_every_run_col_is_classified, ::test_no_classification_entry_is_stale, ::test_list_exposed_columns_are_declared_on_the_list_shape, ::test_list_and_detail_shapes_are_separate (5/5 pass)"
        status: pass
    human_judgment: false
  - id: D4
    description: "GUARD-04 demonstrated red: a plausible sensitive column appended to the live RUN_COLS constant fails the suite naming the column, then reverts byte-identical"
    requirement: "GUARD-04"
    verification:
      - kind: other
        ref: "manual falsification run -- see 'GUARD-04 Falsification Proof' section below for the full verbatim transcript"
        status: pass
    human_judgment: false

duration: ~20min
completed: 2026-08-17
status: complete
---

# Phase 22 Plan 07: RunStatusPoll + GUARD-04 Column Classification Summary

**`RunStatusPoll` declared and enforced as `GET /runs/{run_id}/status`'s response_model (wire body verified byte-identical), `RunListRow` refactored to compose it via multiple inheritance, and a fifteen-column exposure classification (`RUN_COL_CLASSIFICATION`) closing GUARD-04 with a real demonstrated-red falsification.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 3 of 3 complete
- **Files modified:** 5 (2 created, 3 modified)

## Accomplishments

- `app/schemas/run_status.py`'s `RunStatusPoll`: a frozen, extra-forbidding
  Pydantic model carrying exactly the seven volatile fields the status poll
  endpoint already returned field-for-field (`status`, `badge_class`,
  `badge_label`, `failure`, `queue_label`, `queue_badge_class`,
  `has_open_job`), field order matching the original hand-built dict so the
  wire body stays byte-identical. Not a `RowProjection` subclass -- it is
  built from computed presentation values, never a raw repository row, so
  the allowlist's `from_row` machinery has nothing to project over.
- `app/routes/runs.py::run_status` now declares
  `response_model=RunStatusPoll` and returns the model instance directly
  instead of a hand-built `JSONResponse` -- the change that actually makes
  the declaration enforced, since a pre-built response object bypasses
  FastAPI's response-model validation entirely. Verified against two
  fixtures (an error-status run with no open job, and a received-status run
  with an active `Running` job) that the wire body is byte-for-byte
  identical to what the old hand-built dict produced.
- `app/schemas/runs_list.py`'s `RunListRow` refactored to
  `class RunListRow(RunStatusPoll, RowProjection)` -- composes
  `RunStatusPoll`'s seven fields via Python multiple inheritance (a flat
  field union) instead of restating them. `FailureInfo` moved to
  `app/schemas/run_status.py` and is re-exported from `runs_list.py` by
  import, so `app/schemas/__init__.py`'s existing import needed no edit.
- `app/schemas/run_columns.py`'s `ColumnExposure` (three members:
  `list_exposed` / `detail_exposed` / `internal_only`) and
  `RUN_COL_CLASSIFICATION`: every one of the fifteen live
  `app.db.repo.runs.RUN_COLS` columns gets a deliberate classification, with
  the seven PII/internal columns that pass `_safe_run_for_browser`'s
  denylist untouched today classified explicitly (four internal_only, three
  detail_exposed based on live grep evidence against
  `app/templates/run_detail.html`).
- `tests/test_schema_projection.py` extended with five hermetic GUARD-04
  tests (non-empty/known column set, every-column-classified, no-stale-entry,
  list-shape/internal-only cross-check, list-vs-detail structural
  separation), plus a real demonstrated-red falsification (see below).
- Full suite: 1454 passed / 107 skipped (baseline 1449/107 plus 5 new
  tests). `ruff check .` and `uv run mypy` both clean (192 source files).
  `git diff --name-only` against the wave-4 fork base touches only
  `app/routes/runs.py`, `app/schemas/run_columns.py`,
  `app/schemas/run_status.py`, `app/schemas/runs_list.py`,
  `tests/test_schema_projection.py` -- no path under `app/pipeline/`,
  `app/queue/`, `app/db/`, `app/llm/`, or `app/email/`.

## Task Commits

1. **Task 1: RunStatusPoll and a response model on the status poll endpoint** -- `649a0e3` (feat)
2. **Task 2: Explicit three-way classification of every run column** -- `324d746` (feat)
3. **Task 3: GUARD-04 drift test, demonstrated red by a real new column** -- `739e054` (test)

## Files Created/Modified

**Task 1 (`649a0e3`):**
- `app/schemas/run_status.py` -- new: `RunStatusPoll`, `FailureInfo`
- `app/schemas/runs_list.py` -- `RunListRow` refactored to compose
  `RunStatusPoll`; `FailureInfo` re-exported from `run_status.py`
- `app/routes/runs.py` -- `run_status()` route declares
  `response_model=RunStatusPoll` and returns the model; unused `JSONResponse`
  import dropped

**Task 2 (`324d746`):**
- `app/schemas/run_columns.py` -- new: `ColumnExposure`,
  `RUN_COL_CLASSIFICATION`

**Task 3 (`739e054`):**
- `tests/test_schema_projection.py` -- five new GUARD-04 tests

## Decisions Made

- **`RunListRow(RunStatusPoll, RowProjection)` -- flat multiple inheritance,
  not a nested `poll` field.** A flat field union is what lets a poller merge
  its `RunStatusPoll` response straight onto an existing row object with a
  plain object spread; a nested sub-object would force a different,
  asymmetric merge shape at every call site. Verified directly in Pydantic:
  `RunListRow.model_fields` carries all thirteen fields (the six inherited
  from `RunStatusPoll` plus `RunListRow`'s own seven, one of which --
  `status` -- is inherited too) under one merged `model_config`
  (`extra='forbid', frozen=True`).
- **`FailureInfo` relocated to `app/schemas/run_status.py`, re-exported from
  `runs_list.py` by import.** `RunStatusPoll`'s `failure` field needed
  `FailureInfo` and `RunListRow` needed the same shape (inherited via
  `RunStatusPoll` now); rather than declaring it twice or introducing a
  circular import, it now lives beside `RunStatusPoll` and `runs_list.py`
  imports it back. `app/schemas/__init__.py`'s existing
  `from app.schemas.runs_list import FailureInfo` import needed no change.
- **Seven-column exposure split: four internal_only, three detail_exposed.**
  `business_id`, `source_email_id`, `reply_epoch`, and `alias_candidates`
  never appear in `app/templates/run_detail.html`'s markup (grep-confirmed)
  -- they drive server-side roster lookups, dedup bookkeeping, and pipeline
  resolution state only, so they are `internal_only`. `extracted_data`,
  `reconciliation`, and `decision` ARE rendered raw in that template today
  (the "Extracted data and reconciliation" section and the decision banner),
  so they are `detail_exposed` with a comment naming a future detail-page
  conversion as the phase that turns them into declared DTO fields.
- **`pay_period_start`/`pay_period_end` classified `internal_only`, not
  `detail_exposed`.** Both are read server-side only, to build the on-demand
  paystub PDF (`app/routes/runs.py::paystub_pdf` -> `app/pipeline/pdf.py`,
  confirmed via `grep -n -i "period" app/templates/run_detail.html` returning
  no hits for either raw field). The PDF route is a separate, already-gated
  download surface, not part of the run detail page's own JSON/HTML response
  shape this phase's threat model addresses -- classifying these two
  `detail_exposed` would have implied a promise a future detail-page DTO
  conversion is not actually making for them.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `app/schemas/runs_list.py` edited despite being
absent from this plan's frontmatter `files_modified` list**
- **Found during:** Task 1
- **Issue:** The plan's frontmatter `files_modified` lists only
  `app/schemas/run_status.py`, `app/schemas/run_columns.py`,
  `app/routes/runs.py`, and `tests/test_schema_projection.py`. Task 1's own
  action text is explicit and unambiguous: "Refactor
  `app/schemas/runs_list.py`'s `RunListRow` to compose these seven fields
  from `RunStatusPoll` rather than restating them" -- and Task 1's own
  acceptance criteria requires it ("`RunListRow` composes the seven fields
  from `RunStatusPoll` rather than restating them, confirmed by reading
  `app/schemas/runs_list.py`"). The task cannot be completed as written
  without editing this file.
- **Fix:** Edited `app/schemas/runs_list.py` as instructed by the task body.
  Confirmed no other wave-4 plan in this phase claims this file (the
  hazards section names only `frontend/src/pages/RunsPage.tsx` (plan 22-06)
  and `frontend/src/generated/dtos.d.ts` (plan 22-11) as contested).
- **Files modified:** `app/schemas/runs_list.py`
- **Verification:** `uv run pytest -q` (1454/107, no regressions);
  `uv run ruff check .` and `uv run mypy` both clean.
- **Committed in:** `649a0e3` (Task 1 commit)

**2. [Rule 3 - Blocking] `ColumnExposure(str, Enum)` failed ruff's
UP042 (`str, Enum` should be `enum.StrEnum`)**
- **Found during:** Task 2
- **Issue:** `class ColumnExposure(str, Enum)` triggered ruff rule UP042.
  The repo's own enum precedent (`RunStatus`, `JobKind`, `JobState` in
  `app/models/`) already uses `enum.StrEnum`, not the `str, Enum` mixin.
- **Fix:** Changed to `class ColumnExposure(enum.StrEnum)`, matching the
  repo's existing convention exactly.
- **Files modified:** `app/schemas/run_columns.py`
- **Verification:** `uv run ruff check app/schemas/run_columns.py` and
  `uv run mypy app/schemas/run_columns.py` both clean.
- **Committed in:** `324d746` (Task 2 commit)

**3. [Rule 3 - Blocking] Initial docstrings tripped the comment-provenance
guard (`D-22-13`, `T-22-31`, `Phase 23`, `this plan's SUMMARY.md`)**
- **Found during:** Task 1
- **Issue:** `tests/test_comment_provenance_guard.py` failed with 8
  offenders across `app/routes/runs.py`, `app/schemas/run_status.py`, and
  `app/schemas/runs_list.py` -- decision-ID citations (`D-22-13`), a
  task-ID citation (`T-22-31`), a capital-P phase reference (`Phase 23`),
  and a planning-doc reference (`this plan's SUMMARY.md`), all forbidden
  because they cite provenance a future reader of the code does not have
  access to.
- **Fix:** Rewrote every flagged comment to state the underlying reasoning
  in plain language instead of citing the ticket/phase/document that
  produced it, per the plan's own "KNOWN GATE" warning in the hazards
  section.
- **Files modified:** `app/routes/runs.py`, `app/schemas/run_status.py`,
  `app/schemas/runs_list.py`
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py -q`
  (5/5 pass).
- **Committed in:** `649a0e3` (Task 1 commit)

---

**Total deviations:** 3 auto-fixed (all Rule 3 - blocking issues; none
change scope). **Impact on plan:** No scope creep. Deviation #1 is a plan
frontmatter/task-text inconsistency that had to be resolved in favor of the
task's own explicit instructions and acceptance criteria; #2 and #3 are
narrow tooling-conformance fixes.

## Issues Encountered

None beyond the three deviations documented above.

## User Setup Required

None -- no external service configuration required.

## GUARD-04 Falsification Proof (Task 3)

**Confirm the mutation target is the live constant, not a comment or
docstring:**

```
$ grep -n "RUN_COLS = (" app/db/repo/runs.py
38:RUN_COLS = (
```

Lines 20-37 (above the constant) are all `#`-prefixed comment lines; the
live string literal is lines 38-42.

**The mutation** -- appended a plausible sensitive column name
(`ssn_last_four`) to the live `RUN_COLS` constant in
`app/db/repo/runs.py`:

```diff
 RUN_COLS = (
     "id, business_id, source_email_id, status, reply_epoch, extracted_data, decision,"
     " reconciliation, error_reason, error_detail, alias_candidates, hours_changes,"
-    " pay_period_start, pay_period_end, updated_at"
+    " pay_period_start, pay_period_end, updated_at, ssn_last_four"
 )
```

**Confirm the edit landed inside the live constant:**

```
$ grep -n "ssn_last_four" app/db/repo/runs.py
41:    " pay_period_start, pay_period_end, updated_at, ssn_last_four"
```

**The pasted RED** -- `uv run pytest tests/test_schema_projection.py -q`
with the mutation in place, two failures, both naming the added column:

```
.......FF...
=================================== FAILURES ===================================
___________________ test_run_col_set_is_non_empty_and_known ____________________

    def test_run_col_set_is_non_empty_and_known() -> None:
        """Guard the guard: without this, an unparseable or emptied RUN_COLS
        constant would make every difference-based assertion below pass on an
        empty set, which is precisely the vacuous pass this guard exists to
        prevent."""
        parsed = _parse_run_cols()
        assert parsed, "RUN_COLS parsed to an empty column set"
>       assert parsed == _EXPECTED_RUN_COLS, (
            "RUN_COLS drifted from the expected fifteen columns.\n"
            f"  Missing: {sorted(_EXPECTED_RUN_COLS - parsed)}\n"
            f"  Added:   {sorted(parsed - _EXPECTED_RUN_COLS)}"
        )
E       AssertionError: RUN_COLS drifted from the expected fifteen columns.
E           Missing: []
E           Added:   ['ssn_last_four']
E       assert {'alias_candi...ed_data', ...} == frozenset({'a...d_data', ...})
E
E         Extra items in the left set:
E         'ssn_last_four'
E         Use -v to get more diff

tests/test_schema_projection.py:148: AssertionError
_______________________ test_every_run_col_is_classified _______________________

    def test_every_run_col_is_classified() -> None:
        """A column reaching RUN_COLS with no entry in RUN_COL_CLASSIFICATION is
        neither exposed in a page's response shape nor named internal-only -- the
        exact silent-leak shape GUARD-04 exists to catch, named by column."""
        parsed = _parse_run_cols()
        unclassified = parsed - set(RUN_COL_CLASSIFICATION)
>       assert not unclassified, (
            f"column(s) {sorted(unclassified)} reached RUN_COLS while neither "
            "exposed on a page's response shape nor named internal-only in "
            "RUN_COL_CLASSIFICATION (app/schemas/run_columns.py)"
        )
E       AssertionError: column(s) ['ssn_last_four'] reached RUN_COLS while neither exposed on a page's response shape nor named internal-only in RUN_COL_CLASSIFICATION (app/schemas/run_columns.py)
E       assert not {'ssn_last_four'}

tests/test_schema_projection.py:161: AssertionError
=============================== warnings summary ===============================
2 failed, 10 passed, 1 warning in 0.39s
```

**The revert** -- `git checkout -- app/db/repo/runs.py`, then confirmed
byte-identical:

```
$ git diff --stat app/db/repo/runs.py
(no output -- clean)
```

**Green again:**

```
$ uv run pytest tests/test_schema_projection.py -x -q
............                                                             [100%]
12 passed, 1 warning in 0.36s
```

## Status Poll Wire-Body Byte-Identical Proof (Task 1)

**Fixture 1 -- `error` status, no open job, retries-exhausted failure:**

```
BEFORE: {"status":"error","badge_class":"bad","badge_label":"Error","failure":{"secondary_label":"Retries exhausted","stage":"Extraction","reason":"Provider timeout","attempts":"5 of 5 attempts"},"queue_label":null,"queue_badge_class":"neutral","has_open_job":false}
AFTER:  {"status":"error","badge_class":"bad","badge_label":"Error","failure":{"secondary_label":"Retries exhausted","stage":"Extraction","reason":"Provider timeout","attempts":"5 of 5 attempts"},"queue_label":null,"queue_badge_class":"neutral","has_open_job":false}
BYTE IDENTICAL: True
```

**Fixture 2 -- `received` status, `Running` open job, no failure:**

```
BEFORE: {"status":"received","badge_class":"neutral","badge_label":"Received","failure":{"secondary_label":null,"stage":null,"reason":null,"attempts":null},"queue_label":"Running","queue_badge_class":"running","has_open_job":true}
AFTER:  {"status":"received","badge_class":"neutral","badge_label":"Received","failure":{"secondary_label":null,"stage":null,"reason":null,"attempts":null},"queue_label":"Running","queue_badge_class":"running","has_open_job":true}
BYTE IDENTICAL: True
```

The "BEFORE" body was reconstructed by building the exact dict literal the
pre-change route handler constructed (same key order, same values, from the
same `_safe_run_with_queue_projection` reduction), then serializing it with
Starlette's `JSONResponse` rendering options
(`json.dumps(..., ensure_ascii=False, allow_nan=False, indent=None,
separators=(",", ":"))`) -- the same options FastAPI's default JSON response
class uses, whether the route builds the response object itself or returns
a validated Pydantic model.

## Next Phase Readiness

- `RunStatusPoll` is a real, tested, OpenAPI-visible contract; `RunListRow`
  composes it structurally so a future poller can merge its response onto an
  existing row object with a plain spread.
- `RUN_COL_CLASSIFICATION` gives a future detail-page conversion a
  ready-made, already-derived exposure decision for every column it will
  need to place on its own DTO -- three columns (`extracted_data`,
  `reconciliation`, `decision`) plus `hours_changes` are already flagged
  `detail_exposed` with the live evidence for why.
- The GUARD-04 drift test is live and hermetic (no database needed); any
  future column added to `RUN_COLS` without a corresponding
  `RUN_COL_CLASSIFICATION` entry fails CI by name.
- No path under `app/pipeline/`, `app/queue/`, `app/db/`, `app/llm/`, or
  `app/email/` was touched by this plan.

## Self-Check: PASSED

- All five claimed files (`app/schemas/run_status.py`,
  `app/schemas/run_columns.py`, `app/schemas/runs_list.py`,
  `app/routes/runs.py`, `tests/test_schema_projection.py`) confirmed present
  on disk via `ls -la`.
- All three task commits (`649a0e3`, `324d746`, `739e054`) confirmed present
  via `git log --oneline --all`.
- `uv run pytest -q` -- 1454 passed, 107 skipped (matches baseline 1449/107
  plus 5 new GUARD-04 tests).
- `uv run ruff check .` and `uv run mypy` both clean (192 source files).
- `git diff --name-only` against the wave-4 fork base confirmed limited to
  `app/routes/runs.py`, `app/schemas/run_columns.py`,
  `app/schemas/run_status.py`, `app/schemas/runs_list.py`,
  `tests/test_schema_projection.py` -- no fenced path touched.
- No missing items.

---
*Phase: 22-frontend-foundation-runs-list*
*Completed: 2026-08-17*
