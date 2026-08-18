---
phase: 22-frontend-foundation-runs-list
plan: 12
subsystem: testing
tags: [ast, pytest, guard, registry, xss, allowlist, route-table, vitest]

requires:
  - phase: 22-frontend-foundation-runs-list
    provides: "22-01's GUARD-01 machine registry (tests/assertion_inventory.py) and
      completeness guard, and 22-04/22-06/22-07/22-10's converted /runs page, DTO
      allowlist, and RunsPage Vitest suite -- this plan's registry entries and
      pinning tests all resolve against that live source"
provides:
  - "tests/safety_mutation_registry.py -- GUARD-02's concrete formulation: a
    3-entry SAFETY_MUTATION_TARGETS registry (island XSS escaping, the PII
    allowlist exclusion, the catch-all-mount route-table invariant), each with
    a demonstrated-red-and-reverted mutation, plus a declared (but this-pass-
    unused) tsx_fragment predicate kind for future TypeScript-sourced targets"
  - "tests/test_safety_mutation_registry.py -- the registry's own completeness
    guard: synthetic-source proofs of every resolver kind (incl. docstring/
    comment-copy traps) and the six registry-driven completeness tests"
  - "GUARD-02 closed: every safety-critical assertion on /runs has a named,
    demonstrated mutation; the coarse sweep ran and named its one residual gap"
  - "The demo send-test path's empty-input, post-commit-wake-failure, and
    unknown-notice cases are asserted with rendered-text checks, not just
    redirect locations"
  - "Every REACT_DOM-layer inventory entry's replaced_by pointer now names an
    exact Vitest test (file::test name) and a completeness test proves it
    resolves to a real it()/test() call on disk"
affects: [23-run-detail-operator-gate, 24-eval-view-preservation-proof]

actuals:
  tokens: 14970
  tasks: 3
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Safety-subset mutation registry as a hermetic sibling of the durability
      registry, generalized to resolve against Module/ClassDef scope (not
      only FunctionDef), since two of the three Python targets are module-
      or class-level constants, not function bodies"
    - "Compound dict-entry predicate (ALL named key/value pairs must be
      present, not just one) -- discovered necessary live: a single escaped
      character in a two-character escape map can be removed without redding
      its own pinning test, because the surviving escape of the sibling
      character already breaks the test's exact-substring assertion"
    - "Text-based (non-AST) resolver kind for TypeScript/JSX source, declared
      and capability-tested against real live .ts source, explicitly NOT
      populated with a registry entry this pass (no existing Vitest test to
      pin it to, and this plan's frontmatter forbids adding one)"
    - "replaced_by pointer format upgraded from a bare file reference to
      \"{file}::{test name} -- {explanation}\", with a new completeness test
      resolving the pointer against real it()/test() calls on disk"

key-files:
  created:
    - tests/safety_mutation_registry.py
    - tests/test_safety_mutation_registry.py
  modified:
    - tests/assertion_inventory.py
    - tests/test_dashboard.py
    - tests/test_inventory_completeness.py
    - docs/ASSERTION-INVENTORY.md

key-decisions:
  - "SAFETY-01's dict_entry predicate is compound (checks BOTH '<' and '>' in
    _JSON_SCRIPT_ESCAPES together), not single-key, because the live
    demonstration proved removing either character alone does not red
    test_hostile_business_name_does_not_terminate_island_early -- the
    surviving escape of the sibling character already breaks the exact
    substring match the test asserts. This is recorded as a real finding
    (RED-proved with the wrong shape first, then corrected), not assumed."
  - "SAFETY-03 keeps only ONE pinning test (test_route_shadowing.py::
    test_only_mount_is_static), not two. A second app.mount(...) call, tried
    at every plausible registration position, never reds
    tests/test_no_html_on_service_routes.py -- FastAPI 0.138's lazy-include
    mechanism gives every include_router-registered APIRoute precedence over
    an interleaved Mount regardless of order (confirmed empirically), and
    Starlette's StaticFiles renders a missing-file 404 through the same
    HTTPException(404) JSON path every other route uses, so even a
    hypothetical shadow would not demonstrate an HTML leak by itself. This
    property is recorded as genuinely unpinnable by a catch-all-mount
    mutation given the framework's actual behavior, not silently dropped --
    see the Deviations and Coarse Sweep sections below, and
    .planning/WINDOWS.md entry #2."
  - "The tsx_fragment predicate kind is declared, resolver-implemented, and
    capability-tested against real live TypeScript source
    (frontend/src/boot/pageData.ts's element.textContent-before-JSON.parse
    discipline), but is NOT populated with an entry in SAFETY_MUTATION_TARGETS
    this pass: no existing Vitest test pins it, and this plan's frontmatter
    scopes files_modified to tests/ files only, so no new Vitest test may be
    added to create one. Declared now so a future genuinely TypeScript-sourced
    safety target (e.g. a MutationForm preventDefault() guard) needs no schema
    change."
  - "Two-consecutive-submissions-create-two-distinct-runs (the plan's D4
    backstop truth) is NOT newly tested here. tests/test_dashboard.py::
    test_send_test_mints_fresh_message_id_each_click already covers it
    (pre-existing, @pytest.mark.integration, requires seeded_db + a live
    Postgres). It did not run in this pass (no DATABASE_URL/.env in this
    worktree) -- recorded honestly as a backstop the hermetic suite does not
    close, per the plan's own instruction not to fabricate hermetic coverage
    for a property whose real guarantee is a live UNIQUE-constraint
    non-collision, which an in-memory fake cannot meaningfully exercise."
  - "New tests were appended at the END of tests/test_dashboard.py rather than
    interleaved near the existing send-test/notice tests they logically
    belong beside. ASSERTION_INVENTORY keys by exact (file, line, col_offset);
    an earlier attempt to insert mid-file shifted every subsequent registered
    entry's line number and broke test_every_discovered_assertion_has_a_registry_entry
    for dozens of unrelated, untouched entries. Reverted and redone
    append-only. The two existing notice tests were strengthened by adding
    NEW, separate test functions at the end rather than editing them in
    place, for the same reason."

requirements-completed: [GUARD-02, LIST-03, SHELL-03]

coverage:
  - id: D1
    description: "Submitting the demo send-test form with no scenario selected uses the default scenario key and still redirects to a run detail path"
    requirement: "SHELL-03"
    verification:
      - kind: unit
        ref: "tests/test_dashboard.py::test_send_test_with_no_scenario_selected_uses_the_default_fixture"
        status: pass
    human_judgment: false
  - id: D2
    description: "The queue-failure banner renders only the server-reduced notice label; an unrecognised ?notice= code renders no banner element at all"
    requirement: "LIST-03"
    verification:
      - kind: unit
        ref: "tests/test_dashboard.py::test_demo_queue_error_unknown_notice_renders_no_banner_element_at_all"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard.py::test_demo_queue_error_labeled_notice_carries_the_full_fixed_sentence"
        status: pass
    human_judgment: false
  - id: D3
    description: "A wake() failure after the durable commit still surfaces the existing fixed retry sentence and never claims nothing was recorded"
    requirement: "SHELL-03"
    verification:
      - kind: unit
        ref: "tests/test_dashboard.py::test_demo_send_test_wake_failure_after_commit_shows_retry_notice_not_nothing_recorded"
        status: pass
    human_judgment: false
  - id: D4
    description: "Two consecutive demo send-test submissions create two distinct runs with distinct message identifiers and two distinct redirect targets"
    requirement: "SHELL-03"
    verification:
      - kind: integration
        ref: "tests/test_dashboard.py::test_send_test_mints_fresh_message_id_each_click"
        status: unknown
    human_judgment: true
    rationale: "Pre-existing @pytest.mark.integration test requiring seeded_db + a live
      Postgres (DATABASE_URL, ALLOW_DB_RESET=1). This worktree has no .env/live database,
      so the test did not execute in this pass -- its last-known status is not
      re-confirmable here. A human (or a CI run with a real database) must confirm it
      still passes before this deliverable is trusted."
  - id: D5
    description: "Every safety-critical assertion on /runs (island XSS escaping, PII allowlist exclusion, catch-all mount absence) has a named mutation, demonstrated once by hand to actually red its pinning test, then reverted byte-identically"
    requirement: "GUARD-02"
    verification:
      - kind: unit
        ref: "tests/test_safety_mutation_registry.py (26 tests: synthetic-source proofs + the six registry-driven completeness tests)"
        status: pass
      - kind: other
        ref: "manual falsification runs -- see 'Demonstrated Red' section below for all three verbatim transcripts"
        status: pass
    human_judgment: false
  - id: D6
    description: "Every registry entry resolves against live source (docstring/comment-copy excluded) and every pinning test's node id is real"
    requirement: "GUARD-02"
    verification:
      - kind: unit
        ref: "tests/test_safety_mutation_registry.py::test_every_registry_entry_resolves_against_live_source"
        status: pass
      - kind: unit
        ref: "tests/test_safety_mutation_registry.py::test_every_registry_entrys_pinning_test_node_id_is_real"
        status: pass
    human_judgment: false
  - id: D7
    description: "The safety registry is hermetic and is NOT wired into the real-database concurrency-proof workflow"
    requirement: "GUARD-02"
    verification:
      - kind: other
        ref: "uv run python -c \"import yaml, json; d=yaml.safe_load(open('.github/workflows/concurrency-proof.yml')); assert 'safety_mutation' not in json.dumps(d)\" (exit 0)"
        status: pass
    human_judgment: false
  - id: D8
    description: "Every browser-DOM-classified inventory entry (both REACT_DOM entries for /runs) carries a non-null replacement pointer naming an exact Vitest test that exists on disk, and a completeness test proves it -- demonstrated red against a deliberately stale pointer"
    requirement: "GUARD-02"
    verification:
      - kind: unit
        ref: "tests/test_inventory_completeness.py::test_every_react_dom_replacement_pointer_names_a_real_vitest_test"
        status: pass
      - kind: other
        ref: "manual falsification run -- pointer mutated to a nonexistent test name, captured RED, reverted byte-identical (see 'Demonstrated Red' below)"
        status: pass
    human_judgment: false

duration: ~85min
completed: 2026-08-18
status: complete
---

# Phase 22 Plan 12: GUARD-02 Safety Mutation Registry + Demo Path Preservation Summary

**A 3-entry safety mutation registry (island XSS escaping, PII allowlist exclusion, catch-all-mount route-table invariant) with every mutation demonstrated red by hand and reverted, a coarse detection sweep that found and named one genuine coverage gap, and the demo send-test path re-verified for its empty-input, post-commit-wake-failure, and unknown-notice cases with rendered-text assertions.**

## Performance

- **Duration:** ~85 min
- **Tasks:** 3 of 3 complete
- **Commits:** 3 (feat, test, test)
- **Files modified:** 6 (2 created, 4 modified)

## Accomplishments

- **Task 1 -- the registry.** `tests/safety_mutation_registry.py` declares `SafetyPredicate` (kinds: `dict_entry`, `frozenset_member`, `call_count`, all Python-AST-based and generalized to resolve against a Module or a ClassDef in addition to a function, plus `tsx_fragment`, a text-based kind for TypeScript/JSX source), `PinnedAssertion`, and `SafetyTarget`. Populated with 3 entries derived from `tests/assertion_inventory.py`'s absence entries for `/runs` plus this codebase's own security-relevant surfaces: SAFETY-01 (island escaping in `app/routes/templating.py`), SAFETY-02 (the `RunListRow.EXCLUDED` allowlist in `app/schemas/runs_list.py`), SAFETY-03 (the single-`Mount` invariant in `app/main.py`). `tests/test_safety_mutation_registry.py` carries 26 tests: synthetic-source proofs of every resolver kind (including docstring-copy and comment-copy traps, matching `tests/test_proof_mutation_targets.py`'s own idiom) and the six registry-driven completeness tests the plan requires.
- **Task 2 -- the real detection sweep.** Every registry entry's mutation was applied to live source by hand, its pinning test run, the RED output captured, then reverted via `git checkout --` with a confirmed empty `git diff --stat`. This surfaced two real findings requiring a mid-task correction (see Deviations): SAFETY-01's original single-key predicate did not independently red its pinning test, and SAFETY-03's second planned pinning test could never be reddened by any mount placement. Both were corrected honestly rather than reported as false positives. The coarse sweep (stashing `frontend/src/entries/runs.tsx` to a no-op, running the full Python suite and the full Vitest suite) produced zero new failures in either -- an expected, already-anticipated finding (D-22-01: `TestClient` never executes JavaScript) -- and a follow-up targeted mutation against `RunsPage.tsx` proved the REAL covering test (`RunsPage.test.tsx`'s direct-render empty-state test) genuinely catches the regression the coarse sweep's mechanism could not.
- **Task 3 -- demo path + inventory trail.** `tests/test_dashboard.py` gained 5 new tests (appended at the end of the file to avoid shifting any existing `ASSERTION_INVENTORY` line-keyed entry) covering the empty-input default-fixture case, the post-commit wake-failure banner text, a strengthened no-banner-at-all check for unrecognised notice codes, the full fixed retry sentence, and the demo form's `method="post"` presence. Both REACT_DOM-layer `replaced_by` pointers were upgraded from a bare file reference to `"{file}::{test name} -- {explanation}"`, and a new completeness test (`tests/test_inventory_completeness.py::test_every_react_dom_replacement_pointer_names_a_real_vitest_test`) resolves every such pointer against a real `it()`/`test()` call on disk -- demonstrated red against a deliberately stale pointer and reverted. `docs/ASSERTION-INVENTORY.md` regenerated; `--check` passes.
- Full suite: **1513 passed / 107 skipped** (baseline 1481/107 plus 32 new tests: 26 registry + 1 pointer-completeness + 5 demo-path). `ruff check .`, `uv run mypy .` (199 files), `cd frontend && npm run check && npm run test && npm run build` all clean.

## Task Commits

1. **Task 1: The safety mutation registry -- GUARD-02's concrete formulation** -- `9cbc5d3` (feat)
2. **Task 2: Run the detection sweep -- prove each pin actually fires** -- `a9b5f16` (test)
3. **Task 3: Preserve the demo send-test path and close the inventory's replacement trail** -- `f82179d` (test)

## Files Created/Modified

- `tests/safety_mutation_registry.py` (416 lines) -- the registry: dataclasses, resolvers (`dict_entry`, `frozenset_member`, `call_count`, `tsx_fragment`), `SAFETY_MUTATION_TARGETS` (3 entries)
- `tests/test_safety_mutation_registry.py` (~470 lines) -- 26 tests: synthetic-source proofs + the six completeness tests
- `tests/assertion_inventory.py` -- +2 `FILE_SCOPE_NOTES` entries (the two new registry files, zero real hits), 2 `replaced_by` pointers upgraded, 5 new `.text` entries classified (route=/runs, layer=JINJA_SHELL)
- `tests/test_dashboard.py` -- +5 tests, appended at end of file
- `tests/test_inventory_completeness.py` -- +1 completeness test, docstring updated
- `docs/ASSERTION-INVENTORY.md` -- regenerated

## Decisions Made

See `key-decisions` in frontmatter for the full rationale on: SAFETY-01's compound predicate, SAFETY-03's single pinning test, the declared-but-unpopulated `tsx_fragment` kind, the D4 backstop's live-DB dependency, and the append-only edit strategy for `tests/test_dashboard.py`.

## Registry Derivation (Task 1)

`tests/assertion_inventory.py`'s absence entries for `/runs` were reviewed for safety relevance. Of the 23 `/runs`-attributed entries, only 2 are `layer=REACT_DOM` (both the empty-state copy "No payroll runs yet" -- not safety-critical, already `replaced_by`-pointed at `RunsPage.test.tsx`). The genuinely safety-critical surfaces for `/runs` are NOT primarily `.text`-comparison absence entries at all -- they are the `JSON_ISLAND`-layer XSS/PII proofs already covered by `test_react_page_render.py` (`test_hostile_business_name_does_not_terminate_island_early`, `test_payload_excludes_internal_and_pii_fields`) plus GUARD-05's route-table invariant (`test_route_shadowing.py`, `test_no_html_on_service_routes.py`). GUARD-02's own scope note ("PII scrubbing, XSS, path traversal, the delivery-review Reject gate") and this plan's threat register (T-22-53..T-22-57) name exactly these three concerns for `/runs`; path traversal and the delivery-review Reject gate belong to `/eval` and `/runs/{run_id}` respectively (out of this phase's scope). This yielded the 3-entry registry above.

**Why SAFETY-03 covers both "catch-all absence" and "non-HTML service-route" as ONE target, not two:** both properties are protected by the exact same live invariant (`app/main.py` declares exactly one `Mount`, at `/static`). A second registry entry sharing that identical (file, scope, predicate) triple would violate the registry's own no-duplicate-triple completeness guard -- and, as Task 2's live demonstration proved, the second property is not independently falsifiable by this mutation vehicle anyway (see below).

## Demonstrated Red (Task 2)

### SAFETY-01 -- island escaping

**Finding:** the first attempt (removing only `_JSON_SCRIPT_ESCAPES["<"]`) did NOT red the pinning test. Confirmed via a scratch diagnostic: with `<` escaped away but `>` still escaped, the hostile substring renders as `<script>alert(1)<\/script>` -- the exact-match assertion `"<script>alert(1)</script>" not in response.text` still holds (no literal `>` present). Removing only `>` (keeping `<`) produces the mirror-image result, also passing. **Both characters had to be removed together** to genuinely red the test. The registry's `dict_entry` predicate was corrected to be compound (checks both `"<"` and `">"` present) as a result -- this is recorded as a real finding, not assumed in advance.

```
$ grep -n '"<": "\\u003c"' app/routes/templating.py
87:    "<": "\\u003c",
```

Mutation (`app/routes/templating.py`): removed both `"<"` and `">"` entries from `_JSON_SCRIPT_ESCAPES`, leaving only `"&"`.

```
$ uv run pytest tests/test_react_page_render.py::test_hostile_business_name_does_not_terminate_island_early -q
...
>       assert "<script>alert(1)</script>" not in response.text
E       assert '<script>alert(1)</script>' not in '<!DOCTYPE h...dy>\n</html>'
E         '<script>alert(1)</script>' is contained here:
E           "</script><script>alert(1)</script>&\"<img src=x>", ...
FAILED tests/test_react_page_render.py::test_hostile_business_name_does_not_terminate_island_early
```

Revert: `git checkout -- app/routes/templating.py`; `git diff --stat app/routes/templating.py` produced no output (byte-identical). Re-ran the pinning test: 1 passed.

### SAFETY-02 -- allowlist exclusion

```
$ grep -n "source_email_id" app/schemas/runs_list.py
67:            "source_email_id",
```

Mutation (`app/schemas/runs_list.py`): added `source_email_id: UUID | None = None` as a declared field on `RunListRow` (the withheld key added back to the declared fields, per the plan's own description).

```
$ uv run pytest tests/test_react_page_render.py::test_payload_excludes_internal_and_pii_fields -q
...
>           assert key not in row, f"{key!r} must never reach the /runs data island"
E           AssertionError: 'source_email_id' must never reach the /runs data island
FAILED tests/test_react_page_render.py::test_payload_excludes_internal_and_pii_fields
```

Revert: `git checkout -- app/schemas/runs_list.py`; `git diff --stat` produced no output. Re-ran: 1 passed.

### SAFETY-03 -- catch-all mount absence (and the finding it produced)

```
$ grep -n "mount\|include_router" app/main.py
11:app.mount("/static", StaticFiles(directory="app/static"), name="static")
13:app.include_router(health.router)
...
```

Mutation (`app/main.py`): added a second `app.mount("/assets", StaticFiles(directory="app/static"), name="assets_alias")` immediately after the `/static` mount.

```
$ uv run pytest tests/test_route_shadowing.py::test_only_mount_is_static -q
...
E       AssertionError: expected the sole Mount to be ['/static'], found ['/static', '/assets']
FAILED tests/test_route_shadowing.py::test_only_mount_is_static
```

Revert: `git checkout -- app/main.py`; `git diff --stat` produced no output. Re-ran both `test_route_shadowing.py` and `test_no_html_on_service_routes.py`: 11 passed.

**The finding this pass produced:** the plan's own read_first assumed "the same root mount must red" `test_no_html_on_service_routes.py` too. Before accepting that, a second `Mount("/", ...)` was tried at every plausible position -- immediately after `/static` (ahead of every `include_router` call) and after all seven `include_router` calls (behind every one) -- and in **every** position, all 6 parametrized cases in `test_no_html_on_service_routes.py` stayed green. Direct probing (`client.get("/health/live")`, `/does-not-exist`, `/style.css`) confirmed the real handlers still answer for `/health/live` regardless of the catch-all mount's position or presence: FastAPI 0.138's lazy-include mechanism (the same one `tests/test_route_shadowing.py`'s own module docstring names) gives every `include_router`-registered `APIRoute` precedence over an interleaved `Mount`. Separately, `StaticFiles`'s own missing-file behavior raises `HTTPException(404)`, which FastAPI renders as the SAME JSON body every other 404 uses -- so even a hypothetical successful shadow would not, by itself, demonstrate an HTML leak. **Neither mechanism the plan assumed actually applies to this codebase's real routing behavior.** This is recorded honestly (Deviations below and `.planning/WINDOWS.md` entry #2) rather than reporting a false "reds both tests" claim; SAFETY-03 was narrowed to its ONE genuinely-demonstrated pinning test.

### The replacement-pointer completeness guard (Task 3)

```
$ grep -n "given an empty rows array renders the" tests/assertion_inventory.py
298: (in a replaced_by string, live source, not a docstring)
```

Mutation (`tests/assertion_inventory.py`): changed one `replaced_by` pointer to `'frontend/src/pages/RunsPage.test.tsx::a test name that does not exist -- MUTATION-PROOF: deliberately stale pointer'`.

```
$ uv run pytest tests/test_inventory_completeness.py::test_every_react_dom_replacement_pointer_names_a_real_vitest_test -q
...
E       AssertionError: test_dashboard:66:11: pointer names frontend/src/pages/RunsPage.test.tsx::'a test name that does not exist', which does not resolve to a real it()/test() call on disk
FAILED tests/test_inventory_completeness.py::test_every_react_dom_replacement_pointer_names_a_real_vitest_test
```

Revert: `git checkout -- tests/assertion_inventory.py`. This checkout reverted the mutation but also wiped two other in-progress, uncommitted edits (the `FILE_SCOPE_NOTES` additions and the legitimate pointer refresh) since none of Task 3's work was committed yet -- both were redone correctly afterward (see Issues Encountered). Re-ran: 8 passed. Regenerated `docs/ASSERTION-INVENTORY.md`; `--check` passed.

## Coarse Detection Sweep (Task 2)

**Mechanism:** `frontend/src/entries/runs.tsx` (the mounting entry, 20 lines) was replaced with a no-op module (`export {};`, no `createRoot`/`render` call). Ran `npm run test` (Vitest, full suite) and `uv run pytest -q` (full Python suite). Reverted via `git checkout --`; `git status --porcelain frontend/` produced no output.

**Result:** **zero new failures in either suite** (Vitest: 57/57 passed both before and after; Python: unaffected, since `TestClient` never loads or executes any `.tsx`/`.js` bundle at all).

**Inventory-entry-to-failure mapping** for the two `layer=REACT_DOM` absence entries this phase's inventory attributes to `/runs` (`test_dashboard:66:11`, `test_dashboard:74:11`, both "No payroll runs yet" empty-state copy):

| Entry | Covered by the coarse sweep? | Covered by anything? |
|---|---|---|
| `test_dashboard:66:11` / `:74:11` | **No** -- stashing the entry module does not touch `RunsPage.tsx`, which `RunsPage.test.tsx` renders directly, bypassing the entry entirely | **Yes** -- `RunsPage.test.tsx`'s own "given an empty rows array..." test. Proven with a targeted follow-up mutation: changed `RunsPage.tsx`'s empty-state text to "Nothing here", ran `npx vitest run src/pages/RunsPage.test.tsx`, captured a real failure (`TestingLibraryElementError: Unable to find an element with the text: No payroll runs yet`), reverted (`git checkout --`, confirmed byte-identical). |

**The named, accepted gap:** no test anywhere in this suite (Python or Vitest) exercises `frontend/src/entries/runs.tsx`'s OWN mounting call (`createRoot(mountElement).render(<RunsPage data={data} />)`). A regression that deleted that line entirely -- shipping a page that never mounts React at all -- would pass every currently-existing test. This is recorded here by name, per the plan's own instruction, rather than silently tolerated: the file is 20 lines of straightforward, unbranching glue code (read the island, find the mount element, render), and adding a synthetic-DOM entry-level test was judged out of proportion to the risk for this pass. Logged to `.planning/WINDOWS.md` is the SAFETY-03 finding (a genuine registry-scope deviation); this entry-mounting gap is recorded here in prose as it is not itself a stub, skipped test, or unrun verify -- it is a documented absence of coverage for a specific, narrow code path.

## Demo Send-Test Path Re-Verification (Task 3)

**Existing coverage confirmed before adding anything**, per the plan's instruction:

| Case | Already covered? | Test |
|---|---|---|
| 303 + real persisted run on success | Yes (pre-existing) | `test_send_test_returns_303` |
| Fresh Message-ID per click, two distinct runs | Yes (pre-existing, live-DB only) | `test_send_test_mints_fresh_message_id_each_click` (`@pytest.mark.integration`) |
| Per-fixture routing | Yes (pre-existing) | `test_demo_send_test_coastal_routes_to_coastal`, `test_demo_send_test_metro_unknown_shorthand_routes_to_metro` |
| Fixed-copy notice, hostile substring rejected | Partially (pre-existing, checked substring only) | `test_demo_queue_error_notice_uses_fixed_copy_not_query_text` |
| **Empty-input default-fixture identity** | **No -- added** | `test_send_test_with_no_scenario_selected_uses_the_default_fixture` |
| **Post-commit wake failure -> retry banner, not "nothing recorded"** | **No -- added** | `test_demo_send_test_wake_failure_after_commit_shows_retry_notice_not_nothing_recorded` |
| **Unrecognised notice -> no banner element at all** | **No -- strengthened (new function)** | `test_demo_queue_error_unknown_notice_renders_no_banner_element_at_all` |
| **Full fixed retry sentence rendered, not truncated** | **No -- strengthened (new function)** | `test_demo_queue_error_labeled_notice_carries_the_full_fixed_sentence` |
| **Demo form has both method="post" and action** | **No -- added** | `test_runs_list_demo_form_is_server_rendered_with_post_method_and_action` |

**The two-consecutive-submissions backstop (D4):** `test_send_test_mints_fresh_message_id_each_click` already exists and already proves this property, but it is `@pytest.mark.integration` and requires `seeded_db` (live Postgres, `DATABASE_URL` + `ALLOW_DB_RESET=1`). This worktree has no `.env`/live database, so it did NOT run in this pass -- its collection was confirmed (`uv run pytest --collect-only -k test_send_test_mints_fresh_message_id_each_click` finds it) but its pass/fail status could not be re-verified here. Per the plan's own instruction not to write a hermetic test that "appears to prove it and does not," no new hermetic version was added; the existing live-DB test remains the sole proof and is recorded as a backstop (D4, `human_judgment: true`) for a human or a CI run with a real database to re-confirm.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] SAFETY-01's original single-key predicate did not independently red its pinning test**
- **Found during:** Task 2, first live demonstration of the SAFETY-01 mutation
- **Issue:** Removing only `_JSON_SCRIPT_ESCAPES["<"]` (keeping `">"`) left `test_hostile_business_name_does_not_terminate_island_early` GREEN -- the surviving `>` escape already breaks the test's exact-substring assertion (`"<script>alert(1)</script>" not in response.text` requires BOTH literal characters). The same held in reverse (removing only `>`).
- **Fix:** Redesigned `dict_entry` from a single-key check to a compound check (`dict_keys`/`dict_values` tuples, ALL pairs must be present). Re-ran the mutation removing both keys together: confirmed RED, reverted byte-identical.
- **Files modified:** `tests/safety_mutation_registry.py`, `tests/test_safety_mutation_registry.py`
- **Verification:** `uv run pytest tests/test_safety_mutation_registry.py -q` (26/26); re-demonstrated SAFETY-01's mutation with the corrected shape, RED confirmed, reverted.
- **Committed in:** `a9b5f16` (Task 2 commit)

**2. [Rule 1 - Bug] SAFETY-03's second planned pinning test could not be demonstrated red**
- **Found during:** Task 2, live demonstration of the SAFETY-03 mutation
- **Issue:** The plan's read_first assumed "the same root mount must red the shadowing test... and the same root mount must red [the non-HTML service-route] test." A second `Mount` was applied at every plausible position; `tests/test_no_html_on_service_routes.py::test_service_route_never_answers_html` never reddened at any position, because FastAPI 0.138 gives `include_router`-registered `APIRoute`s precedence over any interleaved `Mount` (confirmed empirically), and `StaticFiles`'s 404 renders through the same JSON path as every other route's 404.
- **Fix:** Removed the unsubstantiated `PinnedAssertion` from SAFETY-03, keeping only `test_route_shadowing.py::test_only_mount_is_static` (which DID reliably red). Documented the finding in the module docstring, this SUMMARY, and `.planning/WINDOWS.md`.
- **Files modified:** `tests/safety_mutation_registry.py`
- **Verification:** `uv run pytest tests/test_safety_mutation_registry.py -q` (26/26, no dangling reference to the removed pin).
- **Committed in:** `a9b5f16` (Task 2 commit)

**3. [Rule 2 - Missing critical] FILE_SCOPE_NOTES entries missing for the two new registry files**
- **Found during:** Task 2's coarse sweep, running the FULL Python suite for the first time (Task 1's own scoped test run never exercised `tests/test_inventory_completeness.py`'s file-scope check against these two new files)
- **Issue:** `tests/test_inventory_completeness.py::test_every_text_bearing_file_is_scoped` failed: `tests/safety_mutation_registry.py` and `tests/test_safety_mutation_registry.py` both contain the substring `.text` (inside string-literal values, e.g. `assertion_text="... not in response.text"` and the TS fragment `element.textContent`) but had no `FILE_SCOPE_NOTES` entry.
- **Fix:** Added two zero-affected `FILE_SCOPE_NOTES` entries, matching the precedent `tests/assertion_inventory.py` and `tests/test_inventory_completeness.py` already set for themselves.
- **Files modified:** `tests/assertion_inventory.py`
- **Verification:** `uv run pytest tests/test_inventory_completeness.py -q` (8/8); `docs/ASSERTION-INVENTORY.md` regenerated, `--check` passes.
- **Committed in:** `f82179d` (Task 3 commit, since `tests/assertion_inventory.py` is already a Task 3 file)

**4. [Rule 3 - Blocking] `tests/test_inventory_completeness.py` edited despite being absent from Task 3's `<files>` list**
- **Found during:** Task 3
- **Issue:** Task 3's frontmatter/`<files>` names only `tests/test_dashboard.py, tests/assertion_inventory.py`. Task 3's own action text is explicit: "Add a test to the completeness guard's module -- or extend an existing one -- asserting that every such pointer names a Vitest test file and test name that exist on disk." That module is `tests/test_inventory_completeness.py`. The task cannot be completed as written without editing it.
- **Fix:** Added `test_every_react_dom_replacement_pointer_names_a_real_vitest_test` plus its two small helpers, matching the existing module's style.
- **Files modified:** `tests/test_inventory_completeness.py`
- **Verification:** `uv run pytest tests/test_inventory_completeness.py -q` (8/8); demonstrated red against a deliberately stale pointer (see Demonstrated Red above).
- **Committed in:** `f82179d` (Task 3 commit)

---

**Total deviations:** 4 auto-fixed (2 Rule 1 bug fixes discovered live during the mandated detection sweep -- exactly the class of finding GUARD-02 exists to surface, not a planning error to apologize for; 1 Rule 2 missing-critical fix; 1 Rule 3 blocking-file fix consistent with this phase's own established precedent for frontmatter/task-text mismatches).
**Impact on plan:** No scope creep. Both Rule 1 findings are the mechanism working as designed: a plan's assumption about mutation behavior was tested against real live source and found wrong twice, and both times the registry was corrected to describe what was ACTUALLY demonstrated rather than what was assumed.

## Blind Spots / What This Plan Does NOT Cover

Stated explicitly, per this plan's own instruction that a guard's blind spots are part of its specification:

- **The `tsx_fragment` predicate kind exists but pins nothing this pass.** No TypeScript-sourced safety target for `/runs` has an existing Vitest test to attach to, and this plan's frontmatter forbids adding a new frontend test. `frontend/src/boot/pageData.ts`'s `element.textContent`-before-`JSON.parse` discipline is capability-tested (the resolver can genuinely read it) but not registered as a `SAFETY_MUTATION_TARGETS` entry.
- **`frontend/src/entries/runs.tsx`'s own mounting call has zero test coverage**, Python or Vitest (see Coarse Detection Sweep above). A regression that deleted the `createRoot(...).render(...)` call entirely would pass every test in this suite.
- **The non-HTML-service-route guarantee (GUARD-05) is not covered by GUARD-02's registry at all.** It is fully covered by `tests/test_no_html_on_service_routes.py` and `tests/test_route_shadowing.py` themselves (both pre-existing, both hermetic, both run on every commit) -- GUARD-02's registry adds nothing on top because no catch-all-mount mutation independently threatens it given this framework's actual routing precedence. This is a statement about GUARD-02's marginal contribution, not about the underlying property being unguarded.
- **D4 (two distinct runs per two clicks) is unverified in this pass** -- see the dedicated section above and the `coverage: D4` entry (`human_judgment: true`).

## Issues Encountered

**Mid-file edits to `tests/test_dashboard.py` shifted every subsequent `ASSERTION_INVENTORY` entry's line number.** An initial attempt inserted the new demo-path tests near the existing `test_send_test_returns_303`/`test_demo_queue_error_notice_uses_fixed_copy_not_query_text` functions, and edited the latter in place. `ASSERTION_INVENTORY` keys by exact `(file, line, col_offset)`, so this broke `test_every_discovered_assertion_has_a_registry_entry` for roughly 70 unrelated, untouched entries elsewhere in the same file. Reverted (`git checkout -- tests/test_dashboard.py`) and redone entirely append-only at the end of the file, with the two "strengthened" checks implemented as NEW, separate test functions rather than edits to the existing ones. No existing entry's line number was disturbed in the final version.

**A `git checkout --` mid-Task-3 wiped uncommitted, legitimate prior edits along with a deliberate mutation.** While demonstrating the replacement-pointer completeness guard's RED behavior, `git checkout -- tests/assertion_inventory.py` was used to revert the deliberate stale-pointer mutation -- but since none of Task 3's `FILE_SCOPE_NOTES` additions or the pointer-refresh had been committed yet, the checkout wiped ALL uncommitted changes to that file, not just the mutation. Both legitimate edits were redone immediately afterward and re-verified (`uv run pytest tests/test_inventory_completeness.py -q`, `--check`). No data was lost permanently; this cost extra time, not correctness. Lesson for future plans doing live demonstrated-red proofs mid-task: commit legitimate work BEFORE applying a temporary mutation to the same file, or use a narrower revert than `git checkout --`.

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

- **GUARD-02 is closed for the `/runs` page's safety subset.** Phase 23 (`/runs/{id}`, the operator gate) inherits the same registry SHAPE (`SafetyPredicate`/`PinnedAssertion`/`SafetyTarget`, the `tsx_fragment` kind ready for its first real user) and can add entries for its own safety-critical surfaces (the delivery-review Reject gate is explicitly named in GUARD-02's scope and belongs there, not here).
- **The `replaced_by` pointer format and its completeness guard are now load-bearing conventions** for any future page conversion: `"{file}::{test name} -- {explanation}"`, checked by `tests/test_inventory_completeness.py::test_every_react_dom_replacement_pointer_names_a_real_vitest_test`.
- **D4 (live-DB two-distinct-runs backstop) needs a real-Postgres CI run or a human to re-confirm** before this plan's deliverables are considered fully closed at the milestone level -- see `coverage: D4` above.
- **`.planning/WINDOWS.md` carries one new `deviation` entry** (SAFETY-03's narrowed scope) for cross-phase visibility before ship.
- This is the LAST plan of Phase 22. No blockers for closing the phase from this plan's own work; the D4 live-DB gap and the entries/runs.tsx mounting-coverage gap are both named above for whoever runs phase-close verification.

## Self-Check: PASSED

- FOUND: `tests/safety_mutation_registry.py`
- FOUND: `tests/test_safety_mutation_registry.py`
- FOUND: `tests/assertion_inventory.py` (modified)
- FOUND: `tests/test_dashboard.py` (modified)
- FOUND: `tests/test_inventory_completeness.py` (modified)
- FOUND: `docs/ASSERTION-INVENTORY.md` (modified)
- FOUND commit: `9cbc5d3`
- FOUND commit: `a9b5f16`
- FOUND commit: `f82179d`
- Full suite: 1513 passed / 107 skipped (verified via `uv run pytest -q` immediately before writing this summary)
- `uv run ruff check .`, `uv run mypy .` (199 files), `cd frontend && npm run check && npm run test && npm run build` all clean
- No missing items.

---
*Phase: 22-frontend-foundation-runs-list*
*Completed: 2026-08-18*
