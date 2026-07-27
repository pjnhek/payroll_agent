---
phase: quick-260726-tog
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - app/templates/base.html
  - app/static/style.css
  - tests/test_design_tokens.py
  - eval/run_eval.py
  - eval/chart.svg
  - tests/test_eval.py
  - DESIGN.md
  - .impeccable/design.json
  - PRODUCT.md
autonomous: true
requirements: [260726-tog]

must_haves:
  truths:
    - "Loading any page issues zero third-party network requests; the interface renders in the platform's own UI face."
    - "The single accent reads as deep teal everywhere it appears: primary button, in-table links, focus rings, the outbound thread stripe, the disclosure marker, page-footer links."
    - "No status badge wears the accent family, so the accent stays scarce enough to read as a pointer."
    - "Every accent-bearing text and control pair clears WCAG AA 4.5:1, proven by a computed ratio rather than asserted."
    - "The committed eval chart carries the new accent and no superseded indigo."
    - "DESIGN.md, .impeccable/design.json and PRODUCT.md state what is true after the change, with no surviving reference to a webfont request or a provisional accent."
  artifacts:
    - app/static/style.css
    - app/templates/base.html
    - tests/test_design_tokens.py
    - eval/chart.svg
    - DESIGN.md
    - .impeccable/design.json
  key_links:
    - "style.css :root token block -> every component rule that references it (the swap must be a token edit, not 28 literal edits)"
    - "style.css :root -> tests/test_design_tokens.py (the test parses the live stylesheet, so a future token edit cannot drift past the contrast gate)"
    - "eval/summary.json -> run_eval._write_svg_chart -> eval/chart.svg (the regeneration path that does not rescore and does not touch summary.json)"
---

<objective>
Remove the render-blocking Google Fonts request and swap the provisional indigo accent for a
deep teal, across the runtime interface, the committed eval chart, and the three documents that
record the design as fact.

Purpose: `base.html:10` is where a mechanical detector located the project's own confirmed
anti-reference. Inter-on-white with an indigo accent is the literal center of "generic
AI-generated SaaS", and the accent has been carried in DESIGN.md as provisional and scheduled
for replacement since the design was first recorded. This closes both, and it removes a
third-party request from the first paint of a page whose first impression may already be a
cold start.

Output: a native-stack, teal-accented interface with zero font downloads; a `:root` token layer
where the waiting-status family finally owns its own colors instead of borrowing the accent's;
a durable contrast + token guard test; a regenerated chart; and three documents that no longer
contain a false statement.

## Confirmed decisions being implemented

- **D-01 — Drop the webfont entirely; use a native system stack.** Remove both `preconnect`
  links and the `fonts.googleapis.com` stylesheet from `app/templates/base.html`, and point
  `--font-sans` at a platform-native UI stack. Zero new assets, zero build step, zero downloads.
- **D-02 — Replace the indigo accent with a deep teal.** `--accent` becomes `#0F5F5C`; the
  hover / ring members of the family are chosen here and stated below.

## Value mapping (authoritative; the executor applies this table, and writes only the new values)

| Where | Superseded | New | Note |
|---|---|---|---|
| `style.css` `--font-sans` | `"Inter", system-ui, …` | `system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif` | D-01. Adds Roboto for Android/ChromeOS; otherwise the current stack minus the webfont. |
| `style.css` `--accent` | `#4F46E5` | `#0F5F5C` | D-02. |
| `style.css` `--accent-hover` | `#4338CA` | `#0B4A48` | Darker than the accent, so hover raises contrast rather than lowering it. |
| `style.css` `--accent-ring` | `rgba(79, 70, 229, 0.18)` | `rgba(15, 95, 92, 0.18)` | Same geometry and alpha; the accent's own channels. |
| `style.css` `--accent-soft` | `#EEF0FE` | *(token deleted)* | See "Why the accent loses its soft member" below. |
| `style.css` `--state-pending-fg` | *(literal `#3730A3` in 3 rules)* | `#3730A3` | Value unchanged; promoted from literal to token. |
| `style.css` `--state-pending-bg` | *(`var(--accent-soft)` in 3 rules)* | `#EEF0FE` | Value as rendered today; now this family's own token, not the accent's. |
| `style.css` `--state-pending-edge` | *(literal `#C7D2FE` in `.callout-info`)* | `#C7D2FE` | Hairline weight, for a tinted wash. |
| `style.css` `--state-pending-edge-strong` | *(literal `#A5B4FC` in the clarification card)* | `#A5B4FC` | Stated-edge weight, for an attention card. |
| `.delivery-review-card--clarification` background | `#EEF2FF` | `var(--state-pending-bg)` (`#EEF0FE`) | The two differ by 2/255 on G and 1/255 on B; body-text contrast moves 15.13:1 -> 14.92:1. |
| `run_eval.py` `CHART_PALETTE["accent"]` | `#4F46E5` | `#0F5F5C` | Subplot 2 reconciliation bars. |
| `run_eval.py` line ~945 hard-coded bar color | `#A5B4FC` | new `CHART_PALETTE["accent_light"]` = `#7FBFB9` | Subplot 1 F1 bars; promotes a literal into the palette. |

## Three judgment calls, decided here rather than left to the executor

**1. Why the waiting-status family keeps indigo.** `badge-pending` and `badge-running` currently
*are* the accent family: `#3730A3` on `var(--accent-soft)`. If only `--accent` moved, every
`awaiting_approval` and `running` row in the runs list would wear the accent, and the Accent Is A
Pointer Rule would be dead on the busiest surface in the product. The accent instead vacates
indigo entirely, and indigo becomes the waiting family's exclusive property. This is what the
confirmed rationale for teal already implies: teal was chosen precisely because the status palette
already consumes green, red, amber **and indigo**. Nothing about the pending badge changes visually;
what changes is that it stops borrowing. Its four values move from literals scattered across four
component rules into named `:root` tokens, which is the drift DESIGN.md's own Token-First Rule
records as the system's main risk.

**2. Why `--accent-soft` is deleted rather than retinted.** Its only three consumers are
`.badge-pending`, `.badge-running` and `.callout-info` — all three of which move to
`--state-pending-bg`. A retinted teal `--accent-soft` would have zero consumers, and a pale teal
wash is a thing the accent must never become anyway: the accent is a pointer, never a large fill.
Deleting it makes that rule structurally true instead of aspirational.

**3. Why the chart is regenerated, and how, given the `--check` gate.** `--check` compares fresh
scoring against the committed `eval/summary.json`; it does **not** look at the SVG, and it neither
imports matplotlib nor touches a database. The chart is only rewritten under `--chart`, and that
full path also rewrites `summary.json` with a fresh `suite_run_id`. So the naive
`run_eval.py --chart` would churn the scored report as a side effect of a color change. The correct
path — the one `tests/test_eval.py::_render_committed_aggregate` already uses — renders
`_write_svg_chart` directly from the **committed** `summary.json`, which rescores nothing, mutates
nothing, and needs no live model. Verified in this planning session: it reproduces the committed
chart's color census exactly (139 / 25 / 22 / 13 / 9 / 6), and `--check` was confirmed green
against a clean tree beforehand.

## Computed contrast (all values below were computed during planning, not estimated)

| Pair | Ratio | Baseline it replaces |
|---|---|---|
| `#FFFFFF` on `--accent` (primary button) | **7.47:1** | 6.29:1 |
| `#FFFFFF` on `--accent-hover` | **10.06:1** | — |
| `--accent` on `--surface` `#FFFFFF` (in-table links) | **7.47:1** | 6.29:1 |
| `--accent` on `--bg` `#F7F8FA` (page-footer links) | **7.03:1** | 5.92:1 |
| `--accent` on `--surface-subtle` `#F9FAFB` | **7.15:1** | — |
| `--state-pending-fg` on `--state-pending-bg` | **8.77:1** | 8.77:1 (unchanged) |
| `--text` on the clarification card fill | **14.92:1** | 15.13:1 |

Every accent pair improves on the indigo it replaces. The lowest accent ratio is 7.03:1, well
clear of AA's 4.5:1 and clear of AAA's 7:1.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@CLAUDE.md
@DESIGN.md
@PRODUCT.md
@app/static/style.css
@app/templates/base.html
</context>

<tasks>

<task type="tracer">
  <name>Task 1: Native font stack and teal accent, end to end through the token layer</name>
  <files>app/templates/base.html, app/static/style.css, tests/test_design_tokens.py</files>
  <precondition>The working tree is clean and `uv sync` has been run, so `uv run pytest` and `uv run mypy` execute against the committed dependency set.</precondition>
  <behavior>
    tests/test_design_tokens.py, a new file, parses `app/static/style.css` and
    `app/templates/base.html` from disk and asserts:
    - Test 1 (D-01): base.html requests no third-party origin — no `fonts.googleapis.com`,
      no `fonts.gstatic.com`, no `preconnect` link, and no `<link rel="stylesheet">` whose
      href is an absolute URL. The only stylesheet is the local one.
    - Test 2 (D-01): the `--font-sans` declaration begins with `system-ui` and names no
      downloadable family.
    - Test 3 (D-02): `:root` declares `--accent`, `--accent-hover` and `--accent-ring` at the
      new values, and declares all four `--state-pending-*` tokens.
    - Test 4: `--accent-soft` appears nowhere under `app/`.
    - Test 5: neither superseded accent hex nor the superseded ring rgba survives anywhere in
      `app/static/style.css` or `app/templates/*.html` (case-insensitive).
    - Test 6 (Token-First Rule, made enforceable): each of the four waiting-family hexes appears
      exactly once in style.css — in its `:root` declaration and nowhere else — and the
      clarification card's former background hex appears zero times.
    - Test 7 (contrast): a local WCAG 2.x relative-luminance function computes the ratio for
      white-on-accent, white-on-accent-hover, accent-on-surface, accent-on-page-ground, and
      pending-fg-on-pending-bg, reading every hex out of the parsed `:root` block so the gate can
      never drift from the stylesheet. Each ratio is asserted `>= 4.5`, with the measured value in
      the assertion message.
  </behavior>
  <action>
    In `app/templates/base.html`, delete the two `preconnect` link elements and the external
    font stylesheet link (currently lines 7-10). Leave the local `/static/style.css` link and
    everything else untouched.

    In `app/static/style.css`, apply the value-mapping table in this plan's objective:

    - Rewrite the file's opening comment. It currently describes the system as Inter type with an
      indigo accent, which becomes false. Describe what is true: a cool-neutral audit surface on a
      native platform sans with no font downloads, one deep-teal accent reserved for the next
      action, soft surfaces with subtle elevation, 8px radius, token-driven spacing.
    - Update `--font-sans` per D-01.
    - Update `--accent`, `--accent-hover` and `--accent-ring` per D-02, and delete the
      `--accent-soft` declaration.
    - Add the four `--state-pending-*` declarations in a new commented block directly beneath the
      accent block. The comment states WHY the family owns these rather than borrowing: a badge
      that appears on every row must never wear the accent, or the accent stops being a pointer.
    - Repoint the four component rules that carried those literals — `.badge-pending`,
      `.badge-running`, `.callout-info`, and `.delivery-review-card--clarification` — at the new
      tokens. `.callout-info` takes fg, bg and edge; the clarification card takes bg and the strong
      edge.

    Do not record the superseded values in a code comment anywhere. The token record in DESIGN.md
    is where the history belongs, and a comment naming a retired color is exactly the drift this
    change is removing.

    Touch no rule other than those named above. In particular the `?bound=1` callout, the single
    accent-weighted call to action on `/`, the carded roster and composer, and the `<noscript>`
    picker fallback are all load-bearing prior work and must survive byte-for-byte in behavior.

    Then create `tests/test_design_tokens.py` implementing the seven behaviors above. Give the
    module a docstring explaining that it guards the token layer specifically — the layer DESIGN.md
    names as the system's main drift risk — and that the contrast function is deliberately local so
    the suite gains no dependency. Type-annotate it fully; `tests` is inside the strict mypy scope.
  </action>
  <verify>
    <automated>cd "$(git rev-parse --show-toplevel)" && uv run pytest tests/test_design_tokens.py -q && uv run pytest tests/test_demo_landing.py tests/test_dashboard.py tests/test_ops_route.py -q && uv run ruff check app tests && uv run mypy && git diff --name-only | grep -Ev '^(app/templates/base\.html|app/static/style\.css|tests/test_design_tokens\.py)$' | { ! grep -q . ; }</automated>
    <human-check>Start the app and load `/`, `/runs`, a run detail page, and `/ops`. Confirm the type renders in the platform UI face with no flash of fallback and no font request in the network panel, that the primary button and links read as deep teal, that pending/running badges still read as a distinct waiting state next to the teal, and that nothing has reflowed at the 640/820/960/1280 measures now that the metrics differ from Inter's.</human-check>
  </verify>
  <done>`tests/test_design_tokens.py` passes all seven assertions; the landing, dashboard and ops suites stay green; ruff and strict mypy are clean; and the diff is confined to the two interface files plus the new test.</done>
</task>

<task type="auto">
  <name>Task 2: Bring the committed eval chart onto the new accent</name>
  <files>eval/run_eval.py, eval/chart.svg, tests/test_eval.py</files>
  <precondition>`uv run python eval/run_eval.py --check` exits 0 against the current tree, so a later green `--check` proves the scorer was untouched rather than proving nothing.</precondition>
  <behavior>
    - Test 1: `test_chart_style_metadata_matches_dashboard_tokens` pins `CHART_PALETTE` by exact
      equality, now including the new accent value and the new `accent_light` key.
    - Test 2: `test_chart_svg_is_styled_aggregate_only_and_does_not_mutate_summary` keeps every
      existing assertion and gains four more — both new chart hexes present, both superseded
      indigo hexes absent — against the freshly rendered SVG.
    - Test 3: `test_committed_chart_is_the_styled_aggregate_artifact` gains the same four
      assertions against the checked-in file, so the committed artifact and the generator cannot
      disagree.
  </behavior>
  <action>
    In `eval/run_eval.py`, set `CHART_PALETTE["accent"]` to the new accent per the objective's
    mapping table, and add an `accent_light` key at `#7FBFB9`. Replace the hard-coded bar color at
    the subplot-1 F1 series (around line 945) with `palette["accent_light"]`, so the chart's two
    accent weights both come from the palette. Extend the palette's existing comment to note that
    `accent_light` is the lighter partner of the accent used for the second series of a grouped
    bar pair; do not name it after a stylesheet token, because the accent no longer has a soft
    member.

    Regenerate `eval/chart.svg` from the committed report, not by rescoring. Run, from the repo
    root:

        uv run python -c "import json, pathlib; from eval import run_eval; s = json.loads(pathlib.Path('eval/summary.json').read_text()); run_eval._write_svg_chart(s['per_fixture'], s)"

    Two things to expect and not be alarmed by. The success message is a fixed string that always
    names the chart path regardless of where the write went, and matplotlib emits a benign
    `findfont: Failed to find font weight semibold` warning that predates this change. Two things
    that would be real problems: `git status` showing `eval/summary.json` as modified, or the
    chart's color census showing anything other than the intended substitution.

    The diff on the SVG will be much larger than the color change alone: matplotlib regenerates
    its clip-path and glyph element ids on every render and stamps a fresh `dc:date`. That churn is
    expected and semantically empty. Do not try to hand-edit the SVG to shrink the diff.

    Then extend `tests/test_eval.py` per the behaviors above. Add assertions only; the file's own
    docstring explains that it pins presence and absence rather than unstable matplotlib bytes, so
    follow that convention and do not assert occurrence counts.
  </action>
  <verify>
    <automated>cd "$(git rev-parse --show-toplevel)" && uv run pytest tests/test_eval.py tests/test_eval_wiring.py -q && uv run python eval/run_eval.py --check && git diff --name-only eval/summary.json | { ! grep -q . ; } && uv run ruff check eval tests && uv run mypy</automated>
  </verify>
  <done>The three eval chart tests pass with the new values pinned and the superseded ones asserted absent; `--check` still exits 0; `eval/summary.json` is unmodified in the diff; ruff and strict mypy are clean.</done>
</task>

<task type="auto">
  <name>Task 3: Make the three design records true again</name>
  <files>DESIGN.md, .impeccable/design.json, PRODUCT.md</files>
  <action>
    Four statements across three documents became false in Tasks 1 and 2. Update them rather than
    leaving them to rot, and keep DESIGN.md and `.impeccable/design.json` mutually consistent —
    the sidecar is the machine-readable mirror of the same record.

    **DESIGN.md, frontmatter.** In `colors`: apply the new accent and accent-hover, remove
    `accent-soft`, and add `state-pending-edge` and `state-pending-edge-strong` beside the
    `state-pending-fg` / `state-pending-bg` entries that already exist there. In `typography`:
    replace the `fontFamily` value on all six entries that name the retired display face with the
    native stack from the objective's mapping table, written without the surrounding quotes on
    individual families to match the existing style of that block. The `mono` entry is already a
    platform stack and does not change.

    **DESIGN.md, prose.** The head comment above Overview calls one value deliberately provisional
    — replace it with a note that the accent was replaced and the waiting family was moved onto its
    own tokens at the same time. In Overview, the passage explaining that the current implementation
    sits inside the "generic AI-generated SaaS" anti-reference and that this "is why the accent is
    being replaced" now describes completed work: state what was done, and stay honest that hue and
    a native stack alone do not finish the job — distinctiveness still has to be earned through
    typography, tabular rigor, measure and the signature components. In Colors > Primary, rename
    the accent from its indigo name to **Ledger Teal** and delete the Provisional blockquote,
    replacing it with a short record of the swap and of the fact that the status families were
    re-checked against it. In Colors > Semantic: state, extend the pending bullet to record that
    indigo is now this family's exclusively and is no longer shared with the accent. Update The
    Token-First Rule: it currently says every status color lives as a literal inside its component
    rule, which is now only partly true — record that the waiting family was promoted to `:root`
    and name the families that still have not been. In Typography, update the Display / Body /
    Label font lines and rewrite the Character paragraph's claim that the webfont request loads
    exactly three weights: there is no request. In Elevation, update the focus-ring value.

    **DESIGN.md, Don'ts.** Two entries are now wrong. The one forbidding another indigo literal
    "while the accent is pending replacement" is self-retiring but leaves a real rule unstated —
    replace it with the rule that actually holds now: the waiting indigo family is a status family,
    not a second accent, and nothing outside pending/running may use it. The one tying the three
    permitted font weights to the webfont request needs a new and still-valid reason: platform
    stacks vary in which weights they ship, so a fourth weight risks a browser-synthesized fake.

    **.impeccable/design.json.** Mirror all of the above: `colorMeta.accent` (canonical,
    displayName, and the note, which must stop calling the value provisional), `colorMeta.accent-hover`,
    delete `colorMeta.accent-soft`, add the two new `state-pending-*` entries. Replace the accent's
    `tonalRamp` — it is a violet ramp — with the teal family across the same eight lightness stops:
    `oklch(15% 0.06 185)` through `oklch(95% 0.06 185)` at 15/26/37/48/59/70/82/95. The ramp is a
    documentation artifact with no consumer, so approximate family placement is the intent, not a
    round-trip of the canonical hex. Update the `focus-ring-accent` entry under `shadows`. In every
    `components[].css` string, update the `--font-sans` fallback, the `--accent` and `--accent-hover`
    fallbacks, and the focus-ring rgba; leave the `ds-badge-pending` colors alone, since the waiting
    family keeps its values. Mirror the Overview text into `narrative.overview`, the Token-First
    Rule body into `narrative.rules`, and the two rewritten Don'ts into `narrative.donts`.

    **PRODUCT.md.** The binding-constraints bullet recording that the display face is fetched from
    a CDN at a cited line range is now false. It was explicitly written as a fact rather than a
    commitment, so replace it with the fact that now holds: the interface uses the platform's native
    UI stack and issues no third-party font request, which keeps first paint free of a
    render-blocking dependency on a service that is not this app. Change nothing else in that
    section; the one-stylesheet and no-build-step constraints are unaffected and remain binding.
  </action>
  <verify>
    <automated>cd "$(git rev-parse --show-toplevel)" && uv run python -c "import json, pathlib, yaml, sys; json.loads(pathlib.Path('.impeccable/design.json').read_text()); t = pathlib.Path('DESIGN.md').read_text(); assert t.startswith('---\n'); fm = yaml.safe_load(t.split('---\n', 2)[1]); assert 'accent-soft' not in fm['colors'], 'retired token still in the record'; assert fm['colors']['accent'] == '#0F5F5C'; assert {'state-pending-edge', 'state-pending-edge-strong'} <= set(fm['colors']); assert all('system-ui' in v['fontFamily'] for k, v in fm['typography'].items() if k != 'mono'); print('records parse and agree')" && uv run pytest -q && git diff --name-only | grep -Ev '^(app/templates/base\.html|app/static/style\.css|tests/test_design_tokens\.py|eval/run_eval\.py|eval/chart\.svg|tests/test_eval\.py|DESIGN\.md|\.impeccable/design\.json|PRODUCT\.md)$' | { ! grep -q . ; }</automated>
  </verify>
  <done>DESIGN.md frontmatter parses as YAML with the retired token gone, the new accent and the two new pending edge tokens present, and the native stack on every non-mono typography entry; `.impeccable/design.json` parses as JSON; the full suite is green; and the whole change touches exactly the nine intended files and nothing under the pipeline or demo route.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| browser -> third-party origin | Removed by this change. Before it, every page load reached a font CDN, which could observe visitor IP and user-agent for a payroll product and could block first paint if degraded. |
| repo -> committed eval artifact | `eval/chart.svg` is served as a static file, so its bytes reach a browser directly. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-tog-01 | Information disclosure | `app/templates/base.html` external font request | low | mitigate | Task 1 removes the third-party origin entirely; Test 1 in `tests/test_design_tokens.py` keeps it removed by asserting no absolute-URL stylesheet and no preconnect survives. |
| T-tog-02 | Denial of service | first paint blocked on a CDN outside this deployment | low | mitigate | Same removal. A native stack cannot fail to load, which matters most on the cold-start path where the page is already slowest. |
| T-tog-03 | Tampering | regenerating `eval/chart.svg` via the full `--chart` path would rewrite the scored report as a side effect | medium | mitigate | Task 2 renders from the committed `summary.json` instead of rescoring, and gates on `git diff --name-only eval/summary.json` being empty plus `--check` exiting 0. |
| T-tog-04 | Tampering | a display-only change reaching money, tax or decision logic | high | mitigate | All three tasks gate on an explicit `git diff --name-only` allowlist; nothing under `app/pipeline/`, `app/routes/demo.py`, or the calc modules can appear in the diff without failing the task. |
| T-tog-SC | Tampering | package-manager installs | n/a | accept | No dependency is added or changed. `uv.lock` and `pyproject.toml` are outside the diff allowlist, so a stray install would fail the gate. |
</threat_model>

<verification>
- `uv run pytest -q` green across the whole suite.
- `uv run ruff check app tests eval` clean.
- `uv run mypy` clean under the committed strict config, which covers `app`, `eval`, `scripts` and `tests`.
- `uv run python eval/run_eval.py --check` exits 0, and `eval/summary.json` is absent from the diff.
- `git diff --name-only` lists exactly the nine files in `files_modified` and nothing else.
- Human visual pass per Task 1's `<human-check>`: native face renders, accent reads teal, waiting badges stay distinct, no reflow at the established measures.
</verification>

<success_criteria>
- Zero third-party requests on page load, enforced by test rather than by inspection.
- `--accent` is `#0F5F5C` and reaches every accent surface through the token, not through 28 edits.
- No status badge or callout uses the accent family; the waiting family owns four named `:root` tokens carrying its current values.
- Every accent-bearing pair clears 4.5:1, with the ratio computed by the guard test from the live stylesheet.
- The committed chart carries the new accent and no superseded indigo, with `summary.json` untouched.
- No document states that a webfont is fetched or that the accent is provisional.
- Prior work from groups 1 and 2 is untouched; exactly one accent-weighted call to action remains on `/`.
</success_criteria>

<output>
Create `.planning/quick/260726-tog-drop-the-google-fonts-webfont-for-a-nati/260726-tog-SUMMARY.md` when done.
</output>
