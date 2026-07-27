---
phase: quick-260726-tog
plan: 01
subsystem: ui
tags: [css, design-tokens, wcag, matplotlib, design-system]

requires:
  - phase: quick-260726-rtt
    provides: landing page claim h1 and standing disclaimer
  - phase: quick-260726-sje
    provides: landing page proof-surface restructure, carded roster/composer, single accent CTA
provides:
  - Native system-font stack; zero third-party requests on any page load
  - Deep-teal accent (#0F5F5C) replacing the indigo accent across every accent surface
  - Named :root state-pending-* tokens; waiting-status family no longer borrows the accent
  - Regenerated eval/chart.svg carrying the new accent, with summary.json untouched
  - DESIGN.md / .impeccable/design.json / PRODUCT.md corrected to state current fact
affects: [ui, design-system]

tech-stack:
  added: []
  patterns:
    - "Named :root tokens for a status family that previously borrowed the accent's token, closing a drift risk DESIGN.md itself named"
    - "Regenerating a committed chart artifact via the internal _write_svg_chart function against the committed report, never via the full --record/--chart CLI path that would rescore"

key-files:
  created:
    - tests/test_design_tokens.py
  modified:
    - app/templates/base.html
    - app/static/style.css
    - eval/run_eval.py
    - eval/chart.svg
    - tests/test_eval.py
    - DESIGN.md
    - .impeccable/design.json
    - PRODUCT.md

key-decisions:
  - "Waiting-status family (pending/running badges, clarification card, callout-info) kept its exact current appearance but moved off --accent-soft onto four new named --state-pending-* tokens, so the accent is never worn by a status that appears on every row."
  - "--accent-soft was deleted rather than retinted: a pale accent wash is a thing the accent must never be, and its only three consumers all moved to --state-pending-bg."
  - "Chart regeneration used _write_svg_chart directly against the committed summary.json (the path tests/test_eval.py already uses), never the --chart CLI flag, which would rewrite summary.json's suite_run_id as a side effect."

requirements-completed: [260726-tog]

coverage:
  - id: D1
    description: "Zero third-party network requests on page load (Google Fonts preconnect/stylesheet removed; native font stack)"
    requirement: "260726-tog"
    verification:
      - kind: unit
        ref: "tests/test_design_tokens.py::test_no_third_party_font_request"
        status: pass
      - kind: unit
        ref: "tests/test_design_tokens.py::test_font_sans_is_a_native_stack"
        status: pass
    human_judgment: false
  - id: D2
    description: "Single accent reads as deep teal everywhere it appears, at new :root values, with superseded indigo hexes fully absent"
    requirement: "260726-tog"
    verification:
      - kind: unit
        ref: "tests/test_design_tokens.py::test_accent_and_pending_tokens_declared_at_new_values"
        status: pass
      - kind: unit
        ref: "tests/test_design_tokens.py::test_superseded_accent_values_absent"
        status: pass
    human_judgment: false
  - id: D3
    description: "No status badge wears the accent family; waiting family owns four named :root tokens; Token-First Rule made enforceable"
    requirement: "260726-tog"
    verification:
      - kind: unit
        ref: "tests/test_design_tokens.py::test_accent_soft_deleted"
        status: pass
      - kind: unit
        ref: "tests/test_design_tokens.py::test_pending_family_tokens_are_the_single_source"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every accent-bearing and pending-status text/control pair clears WCAG AA 4.5:1, computed from the live stylesheet"
    requirement: "260726-tog"
    verification:
      - kind: unit
        ref: "tests/test_design_tokens.py::test_accent_and_pending_contrast_clears_aa"
        status: pass
    human_judgment: false
  - id: D5
    description: "Committed eval/chart.svg carries the new accent and no superseded indigo; summary.json untouched"
    requirement: "260726-tog"
    verification:
      - kind: unit
        ref: "tests/test_eval.py::test_chart_style_metadata_matches_dashboard_tokens"
        status: pass
      - kind: unit
        ref: "tests/test_eval.py::test_chart_svg_is_styled_aggregate_only_and_does_not_mutate_summary"
        status: pass
      - kind: unit
        ref: "tests/test_eval.py::test_committed_chart_is_the_styled_aggregate_artifact"
        status: pass
    human_judgment: false
  - id: D6
    description: "DESIGN.md, .impeccable/design.json and PRODUCT.md state what is true after the change; no surviving webfont/provisional claims"
    requirement: "260726-tog"
    verification:
      - kind: other
        ref: "uv run python -c \"...records parse and agree...\" (Task 3 <verify> command, DESIGN.md frontmatter YAML parse + design.json JSON parse + assertions on accent/pending tokens/fontFamily)"
        status: pass
    human_judgment: false
  - id: D7
    description: "Human visual pass at 640/820/960/1280: native face renders, accent reads teal, waiting badges stay distinct, no reflow"
    verification: []
    human_judgment: true
    rationale: "Browser automation was unavailable this session (the claude-in-chrome extension was not connected). All automated verification for this plan passed (full suite, ruff, mypy, --check, diff-scope gate), but the rendered visual confirmation at the four measures could not be performed and is not claimed as done."

duration: 12min
completed: 2026-07-26
status: complete
---

# Quick Task 260726-tog: Native Font Stack and Teal Accent Summary

**Removed the render-blocking Google Fonts request for a native system-font stack, and swapped the provisional indigo accent for a deep teal (`#0F5F5C`) across the runtime interface, the committed eval chart, and the three documents that record the design as fact.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-26T21:33:09-07:00 (base commit)
- **Completed:** 2026-07-26T21:45:04-07:00
- **Tasks:** 3
- **Files modified:** 9 (1 created, 8 modified) across 4 commits

## Accomplishments

- Removed both `preconnect` links and the `fonts.googleapis.com` stylesheet from `base.html`; every page now issues zero third-party network requests, enforced by a new test that parses the live template.
- `--accent` / `--accent-hover` / `--accent-ring` moved from indigo (`#4F46E5` / `#4338CA`) to deep teal (`#0F5F5C` / `#0B4A48`); `--accent-soft` was deleted (not retinted), since a pale accent wash is exactly what the accent must never become.
- The waiting-status family (`.badge-pending`, `.badge-running`, `.callout-info`, `.delivery-review-card--clarification`) kept its exact current appearance but now reads from four new named `--state-pending-*` tokens instead of borrowing `--accent-soft` — closing the drift risk DESIGN.md itself flagged as the system's main risk.
- Added `tests/test_design_tokens.py`: parses `app/static/style.css` and `app/templates/base.html` from disk and asserts zero third-party requests, the native font stack, the new token values, `--accent-soft` deletion, absence of every superseded hex, single-source token discipline for the pending family, and computed WCAG AA contrast (>=4.5:1) on every accent/pending pair.
- Regenerated `eval/chart.svg` from the committed `summary.json` via `_write_svg_chart` directly (never `--chart`, which would rewrite `summary.json`'s `suite_run_id` as a side effect); the color census confirms an exact 1:1 substitution (old accent hex count 6 -> new accent hex count 6; old F1-bar hex count 13 -> new `accent_light` hex count 13; `#1e3a5f`/`#6b7280`/`#e8eaed` unchanged at 22/139/25). `summary.json`'s git hash is byte-identical before and after.
- Corrected the four false statements the swap created: `DESIGN.md`'s `colors.accent` value + its Provisional blockquote; `DESIGN.md`'s Don't tying font weights to the webfont request; the typography `fontFamily` values on all six non-mono entries; `PRODUCT.md`'s CDN-fetch constraint. Mirrored every change into `.impeccable/design.json` (`colorMeta.accent`/`accent-hover`, the two new `state-pending-*` entries, the teal `tonalRamp`, `focus-ring-accent`, every component's CSS fallbacks, and `narrative.overview`/`rules`/`donts`).

## Task Commits

Each task was committed atomically:

1. **Task 1: Native font stack and teal accent, end to end through the token layer** - `aa5d195` (feat)
2. **Task 2: Bring the committed eval chart onto the new accent** - `cd70483` (feat)
   - **Fix (caught during Task 3's full-suite verify):** `3ed79be` (fix) — see Deviations below.
3. **Task 3: Make the three design records true again** - `48e0d46` (docs)

_No separate plan-metadata commit was made by this executor; the orchestrator commits SUMMARY.md/STATE.md/ROADMAP.md separately per the execute-plan protocol._

## Files Created/Modified

- `app/templates/base.html` - Removed the two `preconnect` links and the Google Fonts stylesheet link
- `app/static/style.css` - New accent trio, deleted `--accent-soft`, four new `--state-pending-*` tokens, native `--font-sans`, four component rules repointed
- `tests/test_design_tokens.py` - New: 7 assertions guarding the token layer, parsed live from disk
- `eval/run_eval.py` - `CHART_PALETTE["accent"]` -> teal; added `accent_light`; subplot-1 F1 bars now read from the palette instead of a hard-coded hex
- `eval/chart.svg` - Regenerated from the committed `summary.json`; color census confirms exact substitution
- `tests/test_eval.py` - Extended to pin the new palette values and assert both superseded hexes are absent from both the freshly rendered and the committed SVG
- `DESIGN.md` - Frontmatter (`colors`, `typography`) and prose (Overview, Colors > Primary/Semantic, Token-First Rule, Typography, Elevation, Don'ts) corrected to state current fact
- `.impeccable/design.json` - Mirrors every DESIGN.md change; `ds-badge-pending` colors deliberately left untouched (the waiting family keeps its values)
- `PRODUCT.md` - Replaced the CDN-fetch binding constraint with the native-stack fact that now holds

## Decisions Made

- Waiting-status family kept its exact current appearance (indigo `#3730A3` on `#EEF0FE`) but stopped borrowing `--accent-soft`; it now owns four named `:root` tokens. Nothing about the pending/running badges changed visually — only where their values live.
- `--accent-soft` was deleted, not retinted, since its only three consumers all moved to `--state-pending-bg` and a retinted teal soft variant would have had zero consumers while re-establishing the very "accent as a wash" pattern the design system's own rules forbid.
- The clarification card kept two separately named edge tokens (`--state-pending-edge` / `--state-pending-edge-strong`) rather than collapsing to one, preserving the higher-weight edge an operator-attention surface needs.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed a plan-provenance decision citation from a test comment**
- **Found during:** Task 3's `<verify>` full-suite run (`uv run pytest -q`)
- **Issue:** `tests/test_design_tokens.py:28`'s comment cited a decision ID (`D-02`), which `tests/test_comment_provenance_guard.py` correctly flags — a permanent source file must not carry a plan-provenance reference the reader does not have.
- **Fix:** Reworded the comment to state its rationale in plain terms with no decision citation.
- **Files modified:** `tests/test_design_tokens.py`
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py -q` passes; full suite subsequently green (1320 passed, 107 skipped).
- **Committed in:** `3ed79be`

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Necessary for the repo's existing comment-provenance guard to pass; zero behavior change, test-comment wording only.

## Issues Encountered

None beyond the deviation above.

## Human Verification Outstanding

**The plan's Task 1 `<human-check>` (visual reflow confirmation at the 640/820/960/1280 measures) was not performed this session.** Browser automation was unavailable (the claude-in-chrome extension was not connected). Every automated check in the plan passed — the full test suite (1320 passed, 107 skipped), ruff, strict mypy, `eval/run_eval.py --check`, and the diff-scope gate confirming exactly the 9 intended files changed and nothing under `app/pipeline/` or `app/routes/demo.py` — but the rendered confirmation that the interface actually looks correct in a browser (native type face, teal accent, distinct waiting badges, no reflow now that system-font metrics differ from Inter's) is still outstanding and should be performed by a human or a future session with browser automation available before this is treated as fully verified.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All three plan tasks executed and committed; cumulative diff since base is exactly the 9 files in `files_modified`.
- The outstanding human visual pass (above) is the only unclosed item from this plan's own `<verification>` list.
- Groups 1 and 2 of the earlier landing-page work (`260726-rtt`, `260726-sje`) remain intact: claim h1, standing disclaimer, `?bound=1` gate, `Payroll submission` subject default, queue-error copy, carded roster/composer, `<noscript>` picker fallback, and exactly one accent-weighted CTA on `/` (`btn-approve` at `index.html:25`; the other two buttons are `btn-retrigger`, neutral).

---
*Phase: quick-260726-tog*
*Completed: 2026-07-26*

## Self-Check: PASSED

All 9 claimed files (`app/templates/base.html`, `app/static/style.css`, `tests/test_design_tokens.py`, `eval/run_eval.py`, `eval/chart.svg`, `tests/test_eval.py`, `DESIGN.md`, `.impeccable/design.json`, `PRODUCT.md`) confirmed present on disk. All 4 claimed commit hashes (`aa5d195`, `cd70483`, `3ed79be`, `48e0d46`) confirmed present in `git log`.
