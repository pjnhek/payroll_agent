---
phase: quick-260726-sje
plan: 01
subsystem: ui
tags: [jinja2, fastapi, landing-page, design-system]

requires:
  - phase: quick-260726-rtt
    provides: "h1 claim, standing disclaimer, ?bound=1 route-level gate, Payroll submission subject default, honest queue-error copy"
provides:
  - "Landing page (/) restructured as a proof surface: claim, then one-click proof, then composer, then supporting evidence"
  - "LANDING_GATE_FIXTURE_KEY constant + _gate_fixture_body() reader in dashboard.py, pinned by test to the DEMO_FIXTURES allowlist and to a request_clarification expectation"
  - "Composer + roster carded together with card vocabulary; standing disclaimer through .page-disclaimer (no inline style)"
  - "Picker usable with JavaScript disabled via a <noscript> submit fallback"
affects: [landing-page, demo-affordances, design-review]

tech-stack:
  added: []
  patterns:
    - "Server-owned fixture-path resolution (DEMO_FIXTURES allowlist, never a request value) reused for a landing-page evidence read"
    - "Shared 640px .landing-panel measure across cards and the walkthrough section"

key-files:
  created: []
  modified:
    - app/routes/dashboard.py
    - app/templates/index.html
    - app/static/style.css
    - tests/test_demo_landing.py

key-decisions:
  - "LANDING_GATE_FIXTURE_KEY lives as a named dashboard.py constant, not a template literal, because an unknown fixture_key silently falls back to a clean-run default with nothing failing anywhere"
  - "The gate fixture's own email body is rendered server-side into the existing .raw-email treatment, resolved only from the server-owned DEMO_FIXTURES allowlist"
  - "Composer submit drops to the neutral .btn-retrigger so exactly one accent-weighted button (the gate CTA) remains on the page"
  - "Roster and composer share one card because the same picker drives both"
  - "Picker gains a <noscript>-wrapped neutral submit button; no <script> tag added"
  - "Accent play-circle removed from the walkthrough poster; a visible text link (.page-links) replaces it as the video affordance"

patterns-established:
  - "A route helper that reads a committed, allowlist-resolved artifact must be total (never raise) and degrade to an empty evidence block rather than a 500"

requirements-completed: [QUICK-260726-sje]

coverage:
  - id: D1
    description: "GET / leads with the gate-tripping fixture (unknown_shorthand_metro) as the primary action, its own email rendered verbatim above the button, positioned before the composer"
    requirement: "QUICK-260726-sje"
    verification:
      - kind: unit
        ref: "tests/test_demo_landing.py::test_landing_gate_fixture_key_is_valid_and_forces_clarification"
        status: pass
      - kind: unit
        ref: "tests/test_demo_landing.py::test_landing_gate_proof_renders_verbatim_before_composer"
        status: pass
    human_judgment: false
  - id: D2
    description: "Roster and composer share one card with the subtable nesting pattern; the composer submit is neutral so exactly one accent button remains; the standing disclaimer renders through .page-disclaimer with no inline style; at most one eyebrow survives with real h2 headings elsewhere"
    requirement: "QUICK-260726-sje"
    verification:
      - kind: unit
        ref: "tests/test_demo_landing.py::test_landing_structural_counts_headings_and_accent_button"
        status: pass
      - kind: unit
        ref: "tests/test_demo_landing.py::test_landing_roster_renders_carded_with_subtable_and_eyebrow"
        status: pass
      - kind: unit
        ref: "tests/test_demo_landing.py::test_landing_disclaimer_uses_class_not_inline_style"
        status: pass
    human_judgment: false
  - id: D3
    description: "The picker is usable with JavaScript disabled (noscript submit); the accent play-circle is removed from the poster and replaced with a visible text link, Loom URL bound once"
    requirement: "QUICK-260726-sje"
    verification:
      - kind: manual_procedural
        ref: "By-inspection confirmation recorded below: grep for <script> (none added), grep for the walkthrough_url Jinja set (bound once, used by two anchors)"
        status: pass
    human_judgment: true
    rationale: "The noscript fallback's functional behavior (form still submits with JS off) and the visual removal of the accent circle are structural/visual facts best confirmed by direct source inspection rather than a brittle DOM-structure test; the structural class-name tests (D1/D2) already pin the machine-checkable parts."
  - id: D4
    description: "Full verification sweep: pytest, ruff, mypy, diff-scope limited to the four planned files, no app/routes/demo.py or app/pipeline/ change, no new hex literal in the stylesheet diff, and the removed class names (demo-thumb__play, stack-roster) pinned absent by test"
    requirement: "QUICK-260726-sje"
    verification:
      - kind: unit
        ref: "tests/test_demo_landing.py::test_landing_removed_classes_stay_removed_from_stylesheet_and_template"
        status: pass
      - kind: other
        ref: "uv run pytest -q (full suite, 1313 passed, 107 skipped)"
        status: pass
      - kind: other
        ref: "uv run ruff check app tests"
        status: pass
      - kind: other
        ref: "uv run mypy (strict, 170 source files)"
        status: pass
    human_judgment: false

duration: ~5min (commit span; session including reading/planning was longer)
completed: 2026-07-26
status: complete
---

# Quick Task 260726-sje: Landing Page Restructured as a Proof Surface Summary

**Landing page (/) now leads with the gate-tripping demo fixture as a one-click proof, ranked above the free-form composer, with the fixture's own email rendered verbatim server-side and pinned by test to never silently degrade into a clean-run demo.**

## Performance

- **Duration:** ~5 min across three atomic commits (79db6e4 → 1d81d2f → 28cd06c)
- **Started:** 2026-07-26T20:47:47-07:00 (first task commit)
- **Completed:** 2026-07-26T20:52:33-07:00 (final task commit)
- **Tasks:** 3 of 3 completed
- **Files modified:** 4 (`app/routes/dashboard.py`, `app/templates/index.html`, `app/static/style.css`, `tests/test_demo_landing.py`)

## Accomplishments

- The page's first interactive element is now the gate-tripping fixture (`unknown_shorthand_metro`): its own email body renders verbatim above a single accent button that posts to the existing `/demo/send-test`, ranked above the composer. `LANDING_GATE_FIXTURE_KEY` in `dashboard.py` is pinned by test to the `DEMO_FIXTURES` allowlist and to the fixture's own `expected.decision.final_action == "request_clarification"`, so a rename or fixture edit that would silently swap the demonstrated refusal for a clean run fails loudly.
- The business picker, roster, and free-form composer now share one card (`.card card-pad landing-panel`); the roster table drops its shadow via the `.subtable` nesting pattern already used on `run_detail.html`. Exactly one accent-weighted button (`.btn-approve`) remains on the page — the gate CTA — since the composer's submit dropped to the neutral `.btn-retrigger`.
- The standing disclaimer renders in ink at 13px through a new `.page-disclaimer` class, replacing the muted `.form-help` + inline `style="max-width: 640px;"`.
- At most one uppercase eyebrow survives (the roster's `{business} — roster` label); the proof, composer, and walkthrough sections each carry a real `<h2>` instead.
- The picker gains a `<noscript>`-wrapped neutral submit button so it is operable with JavaScript disabled, with no `<script>` tag added anywhere.
- The walkthrough poster's accent play-circle overlay is removed; a visible text link (`.page-links`) below the poster replaces it as the video affordance, with the Loom URL bound once via `{% set walkthrough_url %}` and used by both anchors.

## Task Commits

Each task was committed atomically:

1. **Task 1: Lead with the gate-tripping fixture as the page's primary action** — `79db6e4` (feat, tracer)
2. **Task 2: Give the roster and composer card vocabulary, cut the eyebrows, and quiet the poster** — `1d81d2f` (feat)
3. **Task 3: Prove the blast radius and the design rules held** — `28cd06c` (test)

_Task 1 was executed as a `type="tracer"` task: committed like `type="auto"` (real implementation, real `<verify>`), then its `<verify>` was re-run end-to-end before Task 2's expansion began (autonomous quick-task run). It passed on the first re-run, so no halt was needed._

## Files Created/Modified

- `app/routes/dashboard.py` — `LANDING_GATE_FIXTURE_KEY` constant, total `_gate_fixture_body()` reader (never raises; degrades to an empty string on any failure), two new `landing()` context keys
- `app/templates/index.html` — proof card (Task 1), composer card carrying the picker/roster/queue-error/compose form (Task 2), `.page-disclaimer` class, walkthrough section with `<h2>` + bound Loom URL + text link, `<noscript>` picker fallback
- `app/static/style.css` — added `.landing-panel` (640px measure) and `.raw-email--nested`; added `.page-disclaimer`; deleted `.demo-thumb__play` (+ its hover variant) and `.stack-roster`, both now dead
- `tests/test_demo_landing.py` — six new tests total: two in Task 1 (fixture-key validity, verbatim-body + ordering), three in Task 2 (structural counts, carded roster, disclaimer class), one in Task 3 (removed-class guard). No existing assertion was weakened or deleted.

## Decisions Made

All eleven planner decisions in `<decisions_locked>` were implemented as written; none were re-litigated. Notable implementation choices within that scope:

- `_gate_fixture_body()` is written as a total function (try/except over `KeyError, OSError, ValueError`, then `isinstance` narrowing with no `cast`) so `mypy --strict` is satisfied and any fixture-file failure costs the page its evidence block, never its response.
- The composer card's `<h2>` reads "Write your own payroll email" (naming it as the instrument); the proof card's `<h2>` reads "Watch the gate refuse to guess"; the walkthrough's `<h2>` reads "The recorded email round-trip" — all real headings replacing the eyebrow labels the plan called out for removal.
- The carded-roster test (`test_landing_roster_renders_carded_with_subtable_and_eyebrow`) asserts on the exact `class="card card-pad landing-panel section"` string count (2 — proof card + composer card) rather than positional DOM parsing, since both cards intentionally share identical classes.

## Deviations from Plan

None — plan executed exactly as written, including all four accepted planner findings (named fixture constant pinned by test, server-rendered fixture body via the allowlist, `<noscript>` picker fallback, and the single text-link video cue with `walkthrough_url` set once).

## Threat Flags

None. All threats identified in the plan's `<threat_model>` (T-sje-01 through T-sje-06, T-sje-SC) were pre-registered and mitigated or accepted as designed; no new security-relevant surface was introduced beyond what the threat model already covers.

## Known Stubs

None.

## Issues Encountered

None. `markupsafe` (used in the two Task 1 tests to compute the expected escaped body) is already available as a transitive Jinja2 dependency via `uv run` — no new dependency was added.

## Verification Evidence

Recorded from the actual commands run against the final commit (`28cd06c`), base SHA `5eaeb26418dfeb665377fe4e40df4b29eb675951` (the worktree's fork point, captured at session start before Task 1's edits):

```
$ uv run pytest -q
1313 passed, 107 skipped, 1 warning in 26.05s

$ uv run ruff check app tests
All checks passed!

$ uv run mypy
Success: no issues found in 170 source files

$ git diff --name-only 5eaeb26418dfeb665377fe4e40df4b29eb675951..HEAD
app/routes/dashboard.py
app/static/style.css
app/templates/index.html
tests/test_demo_landing.py

$ git diff --name-only 5eaeb26418dfeb665377fe4e40df4b29eb675951..HEAD -- app/pipeline app/routes/demo.py | wc -l
0

$ git diff -U0 5eaeb26418dfeb665377fe4e40df4b29eb675951..HEAD -- app/static/style.css | grep '^+' | grep -v '^+++' | grep -cE '#[0-9A-Fa-f]{3,8}'
0
```

By-inspection confirmations (per Task 3's action):

- **Exactly one accent-weighted button remains on `/`** (Accent Is A Pointer Rule) — confirmed both by a rendered-page count (`btn-approve` appears exactly once) and by the structural test `test_landing_structural_counts_headings_and_accent_button`.
- **No third elevation, no nested container carrying both a border and a shadow** (The Two-Step Rule, The No Double Frame Rule) — `.raw-email--nested` and `.subtable` each only set `box-shadow: none`, keeping their inherited border; no new `box-shadow` value was introduced anywhere in the diff.
- **No `<script>` tag was added**; every form on the page is a plain GET or POST — confirmed via `grep -n "<script" app/templates/index.html` (no match) and a grep of every `<form method=...>` occurrence (all `get` or `post`).
- **`app/routes/demo.py` behavior is untouched** — 0 files changed under `app/pipeline/` or `app/routes/demo.py` since the base SHA (confirmed above); the gate CTA's cold-start failure path still redirects to `/runs?demo_queue_error=1`, handled unchanged by `runs_list.html:115`.

## Self-Check: PASSED

- `app/routes/dashboard.py` — FOUND
- `app/templates/index.html` — FOUND
- `app/static/style.css` — FOUND
- `tests/test_demo_landing.py` — FOUND
- Commit `79db6e4` — FOUND in `git log --oneline --all`
- Commit `1d81d2f` — FOUND in `git log --oneline --all`
- Commit `28cd06c` — FOUND in `git log --oneline --all`

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

The landing page now demonstrates the deterministic-gate claim one click from arrival, with the composer unchanged and ranked second as the instrument. No blockers. Group 3 of 3 from the `/impeccable` critique (the remaining `.btn` base-class drift noted in decision 4 of this plan) is out of this plan's scope and can be picked up independently.

---
*Phase: quick-260726-sje*
*Completed: 2026-07-26*
