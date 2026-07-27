---
phase: quick-260726-rtt
plan: 01
subsystem: ui
tags: [jinja2, fastapi, landing-page, copy, css-tokens]

requires:
  - phase: v4
    provides: seeded demo businesses, /demo/bind operator routing, the durable demo composer
provides:
  - "/ states the differentiating claim (LLM reads, deterministic code decides) above the fold with the required standing disclaimer"
  - "Operator binding state (get_demo_binding read + confirmation copy) is gated on ?bound=1 and structurally absent from every plain GET /"
  - "Composer subject default renders as a complete literal string, byte-identical to the server default"
  - "Queue-error callout names the failure, states the honest cold-start fact, and links to /runs instead of asserting nothing was recorded"
affects: []

tech-stack:
  added: []
  patterns:
    - "Route-level context gating (bound == \"1\") to keep operator-only state out of the template context on the common path, not just out of the rendered DOM"
    - "Jinja whitespace-control (-%}/{%-) to keep a sentence assembled by an if/else block byte-contiguous for substring assertions"

key-files:
  created: []
  modified:
    - app/templates/index.html
    - app/routes/dashboard.py
    - app/static/style.css
    - tests/test_demo_landing.py

key-decisions:
  - "Operator binding state is gated on bound == \"1\" in the route (not just hidden in the template) — removes the DB read from every plain landing render and makes the no-leak property structural, not cosmetic"
  - "The two armed/bound callouts merged into one callout-info block using outsider-legible copy; dropped Path-2/armed jargon and the raw-UUID fallback"
  - "Subject default became the literal 'Payroll submission', byte-identical to the server default at app/routes/demo.py:170/:213 — no wall-clock date, one canonical string"
  - "Queue-error copy states the honest 15-minute-sleep/up-to-a-minute-wake fact and points to /runs, since wake.wake() sits inside the try block and a post-commit wake failure still means the run was created"
  - "tests/test_dashboard.py:1105 (the /runs variant's copy-presence pin) was left untouched per locked decision 6 — copy divergence between / and /runs for this callout is a recorded, deliberate leftover"

patterns-established:
  - "New status-adjacent link color rules reference tokens (var(--danger-hover)) rather than hex, mirroring .ops-alarm-banner a"

requirements-completed: [QUICK-260726-rtt]

coverage:
  - id: D1
    description: "GET / states the h1 claim 'The LLM reads. Deterministic code decides.' plus a lede naming code-owned employee resolution/process-or-clarify, paired with the PRODUCT.md standing disclaimer"
    requirement: "QUICK-260726-rtt"
    verification:
      - kind: unit
        ref: "tests/test_demo_landing.py#test_landing_get_states_product_claim_with_disclaimer"
        status: pass
      - kind: unit
        ref: "tests/test_demo_landing.py#test_landing_get_returns_200_no_bind_form"
        status: pass
    human_judgment: false
  - id: D2
    description: "Operator binding state (confirmation sentence, 'Path-2', 'armed for') is absent from a plain GET / and only appears on GET /?bound=1, naming the bound business by full sentence fragment, with no raw UUID fallback"
    requirement: "QUICK-260726-rtt"
    verification:
      - kind: unit
        ref: "tests/test_demo_landing.py#test_landing_binding_state_gated_on_bound_query_param"
        status: pass
      - kind: unit
        ref: "tests/test_demo_landing.py#test_bind_route_writes_demo_sender_bindings_not_contact_email"
        status: pass
    human_judgment: false
  - id: D3
    description: "Composer subject default renders as the complete literal 'Payroll submission' with no 'week of' dangling-Jinja artifact"
    requirement: "QUICK-260726-rtt"
    verification:
      - kind: unit
        ref: "tests/test_demo_landing.py#test_landing_subject_default_complete_and_queue_error_actionable"
        status: pass
    human_judgment: false
  - id: D4
    description: "Queue-error callout names the failure, states the cold-start fact, links to /runs, and never echoes a hostile query-string value"
    requirement: "QUICK-260726-rtt"
    verification:
      - kind: unit
        ref: "tests/test_demo_landing.py#test_landing_subject_default_complete_and_queue_error_actionable"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard.py#test_demo_queue_error_notice_uses_fixed_copy_not_query_text"
        status: pass
    human_judgment: false

duration: ~20min
completed: 2026-07-26
status: complete
---

# Quick Task 260726-rtt: Landing Page — State the Product Claim, Remove Operator Leakage Summary

**Rewrote `/`'s header to state the deterministic-decisioning claim with its required disclaimer, gated operator binding state on `?bound=1` at the route level, and made the composer subject default and queue-error callout complete and actionable — display/copy only, `app/routes/demo.py` and `app/pipeline/` untouched.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 3
- **Files modified:** 4 (`app/templates/index.html`, `app/routes/dashboard.py`, `app/static/style.css`, `tests/test_demo_landing.py`)

## Accomplishments

- `/` now opens with `The LLM reads. Deterministic code decides.` plus a two-sentence lede sourced from README.md and the PRODUCT.md-required standing disclaimer, replacing the generic "Try it live" header.
- The `get_demo_binding` read in `dashboard.py`'s `landing()` handler is gated on `bound == "1"`, so operator routing state never enters the template context (and never costs a DB round-trip) on a plain visit. The two armed/bound callouts merged into one `callout-info` block using outsider-legible copy — no more `Path-2` or `armed` jargon, and no raw-UUID fallback.
- The composer's subject default now renders the complete literal `Payroll submission`, byte-identical to the server default — the `week of {{ '' }}` dangling-Jinja artifact is gone.
- The `demo_queue_error` callout now names the failure, states the honest cold-start fact (15-minute sleep, up to a minute to wake), and links to `/runs` instead of asserting nothing was recorded; `.callout-error a` picked up `var(--danger-hover)`, mirroring `.ops-alarm-banner a`.

## Task Commits

Each task was committed atomically:

1. **Task 1: State the product claim on / with its standing disclaimer** - `075c79e` (feat)
2. **Task 2: Stop leaking operator binding state; keep the /demo/bind flow whole** - `3468044` (fix)
3. **Task 3: Complete the subject default and make the queue-error callout actionable** - `88a4c5f` (fix)

_No plan-metadata commit — per the constraints for this quick task, SUMMARY.md/STATE.md/PLAN.md are left for the orchestrator's docs commit._

## Files Created/Modified

- `app/templates/index.html` - Header claim + disclaimer, appended composer helper copy, merged bound-only confirmation callout, complete subject default, rewritten queue-error callout
- `app/routes/dashboard.py` - Gated the `get_demo_binding` read (and name resolution) on `bound == "1"`
- `app/static/style.css` - Added `.callout-error a { color: var(--danger-hover); }` (token-referenced, no new hex)
- `tests/test_demo_landing.py` - Strengthened the OR assertion at the original `:783` to an AND; added 3 new tests (claim+disclaimer, binding-state gating, subject-default+queue-error); updated one stale copy-pin assertion in the pre-existing compose-rollback test to match the new queue-error lead line

## Decisions Made

- Gated the binding read at the route level rather than only hiding it in the template, per the plan's locked decision — makes the no-leak property structural and removes a DB round-trip from the common path.
- Used Jinja whitespace control (`-%}` / `{%-`) around the bound-confirmation sentence so `armed_business_name` renders on the same line as "processed as a run for" — without it, Jinja's block-level indentation inserted a newline mid-sentence that broke both the intended readable output and the plan's literal test fragment (`processed as a run for Metro Deli Group`). This was discovered via a failing test during Task 2 and fixed before commit (Rule 1 — bug in the initial template edit, fixed inline).
- Consolidated Task 2's three locked behaviors into one test function (plain-GET absence, `?bound=1` presence with a resolved name, `?bound=1` presence with an unresolved binding) rather than splitting into two tests, to keep the total new-test count at exactly three per the plan's stated success criteria (three new tests plus one strengthened assertion).
- Updated the stale copy-pin in `test_demo_compose_rolls_back_every_write_failure_and_renders_bounded_notice` (previously asserting the old "We couldn't queue this demo run. Please try again." string) to assert the new lead line — this is a required sync with Task 3's intentional copy change, not a weakening: the assertion keeps its `.count(...) == 1` strictness.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Jinja block indentation broke the bound-confirmation sentence into two lines**
- **Found during:** Task 2, while running the tracer/task verify (`uv run pytest -q tests/test_demo_landing.py`)
- **Issue:** The first draft of the merged bound-confirmation block put `{{ armed_business_name | e }}` on its own indented line inside the `{% if %}`, so the rendered HTML contained `for\n    Metro Deli Group.` instead of `for Metro Deli Group.` — the test asserting the exact sentence fragment failed even though the visible (rendered-in-browser) text was correct.
- **Fix:** Added Jinja whitespace-control markers (`-%}` / `{%-`) so the sentence and the interpolated name land on one contiguous line in the raw response bytes.
- **Files modified:** `app/templates/index.html`
- **Verification:** `uv run pytest -q tests/test_demo_landing.py` — 34 passed after the fix
- **Committed in:** `3468044` (Task 2 commit — fixed before commit, not a separate commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug, fixed inline before commit)
**Impact on plan:** Cosmetic template-whitespace fix only; no scope creep, no behavior beyond what Task 2 already specified.

## Issues Encountered

None beyond the deviation above.

## User Setup Required

None - no external service configuration required.

## Verification Evidence

- `uv run pytest -q` — **1307 passed, 107 skipped** (full suite, run after each task and again at the end). All 107 skips are pre-existing live-DB integration tests gated on `DATABASE_URL`/`ALLOW_DB_RESET=1` (this worktree has no `.env`); none are in `tests/test_demo_landing.py`, which has zero skips and is fully exercised.
- `uv run ruff check app tests` — All checks passed.
- `git diff --name-only HEAD -- app/pipeline app/routes/demo.py | wc -l` → `0` — no pipeline file touched, `app/routes/demo.py` unmodified, confirmed after every task.
- `git diff -U0 HEAD -- app/static/style.css | grep '^+' | grep -v '^+++' | grep -cE '#[0-9A-Fa-f]{3,8}'` → `0` — no new hex literal in the stylesheet diff.
- Pinned tests confirmed still passing untouched: `tests/test_dashboard.py::test_demo_queue_error_notice_uses_fixed_copy_not_query_text` (the `/runs` copy pin, locked decision 6), `tests/test_demo_landing.py::test_landing_get_returns_200_no_bind_form`, `::test_bind_route_not_on_landing_page`, `::test_bind_route_writes_demo_sender_bindings_not_contact_email`.
- Diff scope check: `git diff --name-only HEAD` (cumulative, base commit `f66c923`) lists exactly `app/static/style.css`, `app/templates/index.html`, `tests/test_demo_landing.py`, and `app/routes/dashboard.py` — matches the plan's `files_modified` frontmatter exactly.
- JS-disabled legibility: every change is server-rendered text, one CSS color rule, and one plain `<a href="/runs">` anchor; no `<script>` tag added; the picker's existing inline `onchange` untouched. One primary button (`.btn-approve`, pre-existing) remains on the page — Accent Is A Pointer Rule intact.

## Known Stubs

None.

## Threat Flags

None — this plan's own `<threat_model>` register (T-rtt-01 through T-rtt-05) covers all new surface introduced; no additional surface was found during implementation beyond what the plan already disposed.

## Next Phase Readiness

- This closes group 1 of 3 from the `/` design critique (21/36 items). Groups 2 and 3 remain open in the critique document for future quick tasks or a phase.
- No blockers for follow-on work; `/demo/bind` → `/?bound=1` → the bound-confirmation block is intact and covered.

## Self-Check: PASSED

- Files confirmed present: `app/templates/index.html`, `app/routes/dashboard.py`, `app/static/style.css`, `tests/test_demo_landing.py`, this SUMMARY.md.
- Commits confirmed present in `git log`: `075c79e`, `3468044`, `88a4c5f`.

---
*Phase: quick-260726-rtt*
*Completed: 2026-07-26*
