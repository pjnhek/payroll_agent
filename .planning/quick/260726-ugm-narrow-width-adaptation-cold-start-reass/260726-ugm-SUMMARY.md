---
phase: quick-260726-ugm
plan: 01
subsystem: ui
tags: [css, jinja2, accessibility, design-system, wcag]

requires:
  - phase: quick-260726-tog
    provides: Ledger Teal accent + state-pending-* tokens, native font stack
provides:
  - Narrow-width (@media max-width:700px) adaptation reaching the shell inset, card padding, inline-form wrap, both fixed-width selects, and the ops/eval grid strips
  - .table-scroll wrapper (focusable, aria-labelled) around the four wide data tables
  - Five distinct per-page <title> blocks via base.html's {% block title %}
  - Nav aria-current="page" server-side wiring (request.url.path, no JavaScript)
  - One-base button composition (.btn + .btn-accent/.btn-reject/.btn-retrigger, .btn-approve allowlisted for the money gate) replacing three cloned button classes
  - js- prefix convention applied to the three runs-list poller query hooks
  - Zero inline presentational attributes on index.html
  - Durable parse-level test guards for all of the above, recomputed from live source
  - DESIGN.md / .impeccable/design.json reconciled against every statement this commit falsified
affects: [ui, design-system, accessibility]

tech-stack:
  added: []
  patterns:
    - "One CSS base class + non-cloning modifiers (.btn), enforced by a test that parses style.css and asserts no modifier redeclares a base property"
    - "js- prefix for classes that exist only as JavaScript query hooks, enforced by a test that the prefix appears in markup and never in style.css"

key-files:
  created: []
  modified:
    - app/static/style.css
    - app/templates/base.html
    - app/templates/index.html
    - app/templates/runs_list.html
    - app/templates/run_detail.html
    - app/templates/eval.html
    - app/templates/ops.html
    - tests/test_design_tokens.py
    - tests/test_demo_landing.py
    - tests/test_dashboard.py
    - DESIGN.md
    - .impeccable/design.json

key-decisions:
  - "Narrow-width fix is CSS arithmetic against the stylesheet source, not an observed render — browser automation was unavailable this session, so the result is explicitly unverified visually (user-approved: fix now, mark unverified)."
  - "status-badge/failure-summary/failure-secondary are live JS query hooks (runs-list poller), not dead markup — renamed to a js- prefix rather than deleted."
  - "tests/test_demo_landing.py:948 accent-count pin strengthened (not weakened): now also asserts the money-gate class is absent from the landing page."
  - "Cold start (~23s measured, 503 + Retry-After from Render's edge) is the platform's, not the app's — nothing was built to fake a loading state the app cannot render before its own process starts."

requirements-completed: [UGM-A-NARROW, UGM-B-COLDSTART, UGM-C-POLISH]

coverage:
  - id: D1
    description: "Narrow-width shell/select/table adaptation via the extended @media (max-width:700px) block"
    requirement: UGM-A-NARROW
    verification:
      - kind: unit
        ref: "tests/test_design_tokens.py#test_narrow_breakpoint_adjusts_shell_and_controls"
        status: pass
    human_judgment: true
    rationale: "Browser automation was unavailable this session — no rendered visual confirmation exists at any viewport width. The parse-level test proves the CSS rules exist and target the right selectors; it cannot prove the layout looks correct. A human must visually verify at 390px/700px before this can be marked visually confirmed."
  - id: D2
    description: "Four wide data tables wrapped in focusable, aria-labelled .table-scroll regions"
    requirement: UGM-A-NARROW
    verification:
      - kind: unit
        ref: "tests/test_dashboard.py, tests/test_ops_route.py (route render tests, full suite green)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Cold-start honesty assessment recorded; post-redirect error path confirmed already-covered with one added Re-trigger assertion"
    requirement: UGM-B-COLDSTART
    verification:
      - kind: unit
        ref: "tests/test_dashboard.py#test_run_detail_never_renders_raw_error_detail"
        status: pass
    human_judgment: false
  - id: D4
    description: "Five per-page titles, nav aria-current wiring, one-base button composition, class hygiene (js- prefix + mt-md), zero inline attrs on index.html"
    requirement: UGM-C-POLISH
    verification:
      - kind: unit
        ref: "tests/test_design_tokens.py (button-composition, class-hygiene, contrast guards); tests/test_dashboard.py#test_nav_marks_current_page_with_aria_current"
        status: pass
    human_judgment: false

duration: ~55min
completed: 2026-07-27
status: complete
---

# Quick Task 260726-ugm: Narrow-width adaptation, cold-start honesty, and remaining polish — Summary

**Extended the single 700px breakpoint from 2 rules to 10 (shell inset, card padding, form wrap, two selects, two grid strips, table minimum-width), wrapped 4 wide tables in focusable scroll regions, gave every page a distinct title and JS-free nav current-page state, rebuilt buttons as one composable base instead of three clones, and reconciled DESIGN.md/design.json against everything this commit changed — all pinned by parse-level tests that recompute from live source.**

## Performance

- **Duration:** ~55 min
- **Completed:** 2026-07-27T05:25Z
- **Tasks:** 3 (tracer + auto + auto)
- **Files modified:** 12

## Accomplishments

- **Narrow-width adaptation (Task 1):** the `@media (max-width: 700px)` block now also drops the 64px shell inset to 16px, shrinks card padding, wraps `.form-inline`, unpins `.select-inline`/`.demo-select` to `width: 100%`, collapses `.ops-panels`/`.metric-strip` to one column, and floors `.table-scroll > table` at 560px. Four wide tables (runs list, eval drill-in, ops attempts, ops dead-letter) sit in `role="region" tabindex="0" aria-label="..."` scroll wrappers with a visible focus ring. `ops.html`'s inline `grid-template-columns` override moved to a class (`.metric-strip--pair`) so it no longer defeats the media query via specificity.
- **Per-page titles + nav state (Task 2):** `base.html` gained `{% block title %}`, overridden distinctly by all five content templates. The nav marks the current page via `{% set nav_path = request.url.path %}` and `aria-current="page"`, styled with ink + 600 weight only — no JavaScript, no underline, no accent.
- **Button composition (Task 2):** `.btn` is now the sole owner of the seven base properties; `.btn-accent`/`.btn-reject`/`.btn-retrigger` declare only color/border deltas. `.btn-approve` is the allowlisted money-gate exception (padding + font-weight), composed at exactly one site — Approve & Send on `/runs/{id}`. Every button in every template now composes `btn btn-X`.
- **Class hygiene + inline attributes (Task 2):** the four class names with no CSS behind them were resolved individually — `mt-md` gained a real rule (and `run_detail.html`'s duplicated inline `margin-top` was deleted); `status-badge`/`failure-summary`/`failure-secondary` turned out to be the runs-list poller's live query hooks, so they were renamed to a `js-` prefix in both markup and script, not deleted. `index.html` now has zero inline presentational attributes (`.form-label--flush`, `.select-inline`, `.form-inline--flush`, `.form-help--stacked`); the same `.form-inline--flush` class was reused at the two other sites with the identical duplicated literal.
- **Durable guards + design record (Task 3):** new parse-level tests in `tests/test_design_tokens.py` pin the breakpoint's contents, the muted-ink contrast cluster (page ground, surface, surface-subtle — all above 4.5:1), the button-composition rule (both directions: no redeclared base property, and every modifier class always rides with the bare `btn`), and the class-hygiene rule (js- prefix present, unprefixed names absent, `mt-md` has a rule). `tests/test_dashboard.py` gained one assertion on the existing error-render test (Re-trigger affordance renders) and a new nav-mechanism proof across three live routes. `DESIGN.md` and `.impeccable/design.json` were corrected everywhere they had gone false: the layout "known gap" paragraph, the Navigation "no mobile treatment" line, the Buttons "known drift" note, two Don'ts, and the Shapes section's play-overlay claim.

## Task Commits

Each task was committed atomically:

1. **Task 1: Narrow-width adaptation** — `c878af9` (feat)
2. **Task 2: Titles, nav state, button composition, class hygiene, inline attributes** — `cfc12cf` (feat)
3. **Task 3: Durable guards, cold-start assessment, design record reconciliation** — `727d9c6` (test)

**Commit-grouping note:** a few small pieces landed a commit earlier than the plan's per-task file list implied — `.select-inline`, `.form-inline--flush`, `.form-help--stacked`, and `.form-label--flush` were declared in the Task 1 commit (contiguous with `.select-inline`'s declaration in the same stylesheet edit) rather than split across Task 1/Task 2, and the plan's 1f narrow-breakpoint test helper landed in the Task 3 commit alongside the 3a/3b/3c guards (they were appended to `tests/test_design_tokens.py` in one contiguous block with no unchanged-context boundary `git add -p` could split without manual patch surgery). Every task's own `<verify>` command was still run and passed against the full working tree before its commit — this is a commit-boundary simplification, not a correctness or verification gap.

## Files Created/Modified

- `app/static/style.css` — narrow-width breakpoint, `.table-scroll`, button base/modifiers, `.select-inline`/`.form-*--flush`/`.form-help--stacked`, `.metric-strip--pair`, `.mt-md`, `nav a[aria-current="page"]`
- `app/templates/base.html` — `{% block title %}`, nav `aria-current` wiring
- `app/templates/index.html` — title block, button classes, zero inline attributes
- `app/templates/runs_list.html` — title block, `.table-scroll` wrap, `js-` prefixed hooks (markup + script), button class
- `app/templates/run_detail.html` — title block, button classes, `mt-md` inline-style removal
- `app/templates/eval.html` — title block, `.table-scroll` wrap, button class, `.form-inline--flush`
- `app/templates/ops.html` — title block, `.metric-strip--pair`, two `.table-scroll` wraps
- `tests/test_design_tokens.py` — narrow-breakpoint, muted-ink-contrast, button-composition, class-hygiene guards
- `tests/test_demo_landing.py` — strengthened accent-count pin (btn-accent count + btn-approve absence)
- `tests/test_dashboard.py` — Re-trigger-affordance assertion, nav aria-current route proof
- `DESIGN.md` — layout/navigation/buttons/shapes sections and two Don'ts corrected; js- prefix rule added
- `.impeccable/design.json` — `play-overlay` shadow removed, `breakpoints` entry corrected, two `donts` strings mirrored

## Decisions Made

- Narrow-width fix committed as CSS arithmetic against the stylesheet, explicitly marked unverified visually (see NOT VERIFIED section below) — user-approved path.
- `status-badge`/`failure-summary`/`failure-secondary` renamed rather than deleted, since they are live JavaScript query hooks for the runs-list poller (deleting them would have broken status polling).
- `tests/test_demo_landing.py:948` — the one pre-existing assertion this plan touched — was strengthened, not weakened (see below).
- Cold start recorded as an honest assessment; nothing built to simulate a loading state the app cannot itself render before its process starts.

## Deviations from Plan

None — plan executed exactly as written, with one intentional commit-boundary simplification documented above under "Commit-grouping note" (not a deviation from the plan's implementation content, only from strict per-task-file commit granularity).

## Issues Encountered

None.

## NOT VERIFIED — carried forward verbatim from the plan's `<verification>` block

> Browser automation was unavailable this session. No rendered visual confirmation of any
> layout at any viewport width was possible. The narrow-width work in Task 1 is CSS
> arithmetic against the stylesheet source (64px insets each side leave roughly 262px of
> content at 390px, against a 240px-minimum select), not an observed screenshot. The
> structural causes are fixed and pinned by a parse-level test; whether the result looks
> right at 390px, 700px, or anywhere between is **unverified**. The user explicitly chose
> "fix now, mark unverified." This item carries forward as an open visual check, alongside
> the identical outstanding check from group 3a (reflow at 640/820/960/1280).

## Cold-start assessment (Task 3f) — recorded as fact, not built as a feature

- A real cold start was measured at roughly 23s this session: HTTP 503 with `Retry-After: 5`,
  showing Render's own unbranded loading page. This is consistent with the 30-60s range
  PRODUCT.md:68-69 already records, so **PRODUCT.md is not false and was not edited.**
- The 503 originates at Render's edge before any FastAPI worker exists. There is no in-app
  surface to style, no template that runs, and nothing this codebase can do about the
  platform loading page. **Nothing was built** — no spinner, no fake progress indicator, no
  "waking up" banner — because a sleeping app cannot render one, and shipping one would be
  the overclaiming failure PRODUCT.md warns against.
- The only in-app affordance that exists already shipped in group 1 (quick task `260726-rtt`):
  the landing page's queue-error callout names the 15-minute sleep and the wake latency, and
  the walkthrough section offers the recording as a stand-in while the service wakes.
- A demo run that fails **after** the redirect to `/runs/{run_id}` is **already covered**:
  Phase 8's PII-safe `error_detail` column renders through `_safe_failure_presentation` into
  the error banner with stage, reason, and attempts, plus a Re-trigger button. The only change
  made here is one added assertion (`tests/test_dashboard.py`) pinning that the Re-trigger
  affordance renders — the redaction itself was already proven by that test's existing
  falsification step.

## The one pre-existing assertion this plan changed

`tests/test_demo_landing.py:948` (`test_landing_structural_counts_headings_and_accent_button`)
previously asserted `body_text.count("btn-approve") == 1` on the landing page. After the
button-class rename, the landing page's accent CTA carries `btn-accent`, not `btn-approve` (the
money-gate class is now reserved for exactly one site: Approve & Send on `/runs/{id}`). The
replacement assertion is **strictly stronger**, not weaker: it keeps the original intent (exactly
one accent-weighted CTA — now checked via `btn-accent`) **and adds** a new negative assertion that
`btn-approve` is **absent** from the landing page entirely. A test that only checked the new
literal would have been a like-for-like swap; adding the absence check closes the gap that a
future accidental render of the money-gate button on `/` would otherwise slip through unnoticed.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- All three tasks complete; full suite (1326 passed, 107 skipped), ruff, and strict mypy are
  green; `app/pipeline/` and `app/routes/demo.py` are byte-identical to HEAD.
- **Open visual check carried forward:** the narrow-width work (this task) and the reflow check
  at 640/820/960/1280 (group 3a, quick task `260726-tog`) are both unverified against a real
  browser. The next session with browser automation available should visually confirm both in
  one pass.
- No blockers.

---
*Phase: quick-260726-ugm*
*Completed: 2026-07-27*

## Self-Check: PASSED

All three task commits (`c878af9`, `cfc12cf`, `727d9c6`) verified present in `git log --oneline --all`.
All 12 modified files verified present on disk (style.css, base.html, index.html, runs_list.html,
run_detail.html, eval.html, ops.html, test_design_tokens.py, test_demo_landing.py, test_dashboard.py,
DESIGN.md, .impeccable/design.json). No missing items.

## Post-execution verification (2026-07-27)

The `NOT VERIFIED` statement above was accurate at execution time and is now **closed**. The Chrome
extension was connected afterwards and the work was verified against a real render.

Method: app run locally with `WORKER_COUNT=0` so no worker threads spawned (no queue drain, no
outbound email); only read-only `GET`s were issued; the server log recorded 0 POSTs. A same-origin
iframe was used to obtain a true narrow viewport, since macOS Chrome will not size a window below
roughly 945px.

Results at a real 375px viewport:

- Horizontal page overflow: **0px**. Elements wider than the viewport: **none**.
- `nav` and `.page-wrapper` horizontal padding collapsed 64px -> 16px as designed.
- The business picker's 240px `min-width` is unpinned (computed `0px`); the control renders 293px
  inside 375px.
- `/eval`'s 1024px table overflows *inside* its `.table-scroll` region (`overflow-x: auto`,
  `tabIndex=0`, `scrollWidth > clientWidth`) while the page itself does not overflow — the intended
  behavior, and keyboard-reachable.
- `/ops` and `/runs` required no scroll region and showed no overflow.

Live computed contrast (measured, not derived): white-on-accent **7.469:1**, `.form-help` and
`.column-label` **4.834:1**, `.lede` **4.550:1** (the marginal pair, confirmed to clear 4.5:1),
disclaimer and `h1` **15.916:1**, nav links **16.913:1**.

Per-page `<title>` and nav `aria-current="page"` confirmed correct on `/`, `/runs`, `/eval`, `/ops`.

Body font resolved to the native stack with no Inter and no third-party font request.
