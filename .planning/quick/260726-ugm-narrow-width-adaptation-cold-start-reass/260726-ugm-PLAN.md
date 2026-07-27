---
phase: quick-260726-ugm
plan: 01
type: execute
wave: 1
depends_on: []
autonomous: true
requirements: [UGM-A-NARROW, UGM-B-COLDSTART, UGM-C-POLISH]
files_modified:
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

must_haves:
  truths:
    - "At 390px the shell inset steps down from 64px to 16px, so content gets ~358px instead of ~262px."
    - "The business picker and the demo-scenario select stop asserting a fixed minimum width below 700px and fill their container instead."
    - "Each of the five pages carries a distinct browser tab title."
    - "The nav marks the current page with aria-current plus a visual weight/ink change, with no JavaScript and no underline."
    - "grep for btn-approve finds exactly one markup site: the Approve & Send money gate on run detail."
    - "Every button in every template composes the base .btn plus one modifier; no modifier re-declares a base property."
    - "app/templates/index.html carries zero inline presentational attributes."
    - "Muted ink on the page ground is pinned above WCAG AA 4.5:1 by a test that recomputes the ratio from the live :root block."
    - "No class name in any template lacks either a CSS rule or a js- prefix marking it a script hook."
    - "No source-of-truth design record (DESIGN.md, .impeccable/design.json) makes a claim this commit falsified."
  artifacts:
    - app/static/style.css
    - app/templates/base.html
    - tests/test_design_tokens.py
    - DESIGN.md
    - .impeccable/design.json
  key_links:
    - "base.html {% block title %} -> the five content templates that must each override it"
    - "base.html request.url.path -> nav a[aria-current=page] rule in style.css"
    - "runs_list.html js- hook class names -> the three querySelector calls in the same file's poller"
    - "tests/test_demo_landing.py:948 accent-count pin -> the btn-accent rename"
    - "ops.html inline grid-template-columns -> the media-query stacking rule it would otherwise defeat"
---

<objective>
Close the final group (3b of 3) of the /impeccable critique: narrow-width adaptation, an
honest cold-start assessment, and the remaining polish items (titles, nav state, button
semantics, dead classes, inline styles, stale design records).

Purpose: the app is recruiter-facing. A 390px viewport currently gets ~262px of usable
content against a 240px-minimum select; every tab reads `Pyrl`; the nav never says where
you are; and the design record asserts several things that are no longer true.

Output: display and copy changes only, plus durable test guards so the fixes cannot
silently erode, plus a reconciled DESIGN.md / design.json.

**No pipeline, money, tax, decision, or queue logic changes.** `app/pipeline/` and
`app/routes/demo.py` are untouched, gated by a diff check.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@CLAUDE.md
@PRODUCT.md
@DESIGN.md
@.impeccable/design.json
@app/static/style.css
@app/templates/base.html
@app/templates/index.html
@app/templates/runs_list.html
@app/templates/run_detail.html
@app/templates/eval.html
@app/templates/ops.html
@tests/test_design_tokens.py
</context>

<constraints_restated>
Binding for every task below:

- `uv` only. Never `pip`, never `.venv/bin/python`.
- Server-rendered Jinja2. No build step, no bundler, no client framework, no new runtime dependency.
- Every surface stays legible and usable with JavaScript disabled.
- Reuse existing `:root` tokens. No new hard-coded status hex values.
- Do NOT touch `app/pipeline/` or `app/routes/demo.py`.
- Do NOT undo groups 1, 2, or 3a. Preserved verbatim: the claim h1, the standing
  disclaimer, the `?bound=1` route gate, the `Payroll submission` subject default, the
  queue-error copy, the gate-fixture proof card with its verbatim fixture email, the
  carded roster/composer, the single accent CTA, the `<noscript>` picker fallback, the
  native font stack, and the Ledger Teal accent with indigo retained as the waiting
  family's own `state-pending-*` tokens.
- Exactly ONE accent-weighted call to action remains on `/`.
- Do NOT weaken any existing test assertion. Where a pin must change, it changes by
  becoming stricter (the old literal becomes a negative assertion).
- If DESIGN.md or `.impeccable/design.json` becomes false as a result of this work,
  correct it in the same commit. Four such statements went stale earlier in this
  sequence; do not add a fifth.
</constraints_restated>

<tasks>

<task type="tracer">
  <name>Task 1: Narrow-width adaptation — relax the shell, unpin the fixed-width controls, give wide tables a scroll treatment</name>
  <files>
    app/static/style.css,
    app/templates/index.html,
    app/templates/runs_list.html,
    app/templates/eval.html,
    app/templates/ops.html,
    tests/test_design_tokens.py
  </files>
  <read_first>
    app/static/style.css:82-127 (nav + page-wrapper 64px inset),
    app/static/style.css:583-594 (.form-inline, .form-help),
    app/static/style.css:1036-1053 (.demo-select min-width 260px),
    app/static/style.css:1100-1130 (spacing helpers + the single existing breakpoint),
    app/templates/index.html:40-52 (business picker with the fixed-width select),
    app/templates/ops.html:35 (metric-strip carrying an inline grid-template-columns
    that would override any media-query stacking rule)
  </read_first>
  <action>
Structural causes first, then the two markup changes the CSS cannot reach on its own.

**1a. Extend the existing `@media (max-width: 700px)` block in `app/static/style.css`.**
Keep its two current rules exactly as they are (the conversation heading and the
disclosure summary already stack there) and add, in the same block:

- `nav` and `.page-wrapper` horizontal padding drop from `var(--space-3xl)` to
  `var(--space-md)`. Keep the nav's 56px height: with 16px insets the four nav items
  (brand plus three links at 24px gap) occupy roughly 207px of 358px at 390px, so the
  row still fits on one line and needs no wrap.
- `.card-pad` padding drops from `var(--space-xl)` to `var(--space-lg)`.
- `.form-inline` gains `flex-wrap: wrap` and `align-items: flex-start`, so a label plus
  control plus helper sentence stops forcing a single unbreakable row.
- `.select-inline` and `.demo-select` get `width: 100%; min-width: 0;` — this is the
  rule that actually fixes the overflow, since a 240px/260px floor cannot fit a 198px
  card interior.
- `.ops-panels` and `.metric-strip` collapse to `grid-template-columns: 1fr`.
- `.table-scroll > table` gets `min-width: 560px`, so a wide table scrolls inside its
  wrapper instead of crushing five to seven columns into 358px.

Write a short comment above the added rules stating the arithmetic that motivated them
(64px insets each side leave ~262px at 390px) and that the fix is unverified visually.

**1b. Add the `.table-scroll` wrapper rule** near the table rules, outside the media
query so it is never a class without CSS behind it:

```
.table-scroll {
  overflow-x: auto;
  /* Room so the table's resting shadow is not clipped by the scroll box. */
  padding-bottom: 4px;
}
.table-scroll:focus-visible {
  outline: none;
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 3px var(--accent-ring);
}
```

The focus rule is required by the design record's standing instruction that a removed
outline is always replaced by the 3px ring at the same geometry — a scroll container has
to be focusable to be keyboard-operable, and a focusable element needs a visible ring.

**1c. Wrap the three wide data tables.** In `runs_list.html` (the five-column runs
table), `eval.html` (the seven-column fixture drill-in), and `ops.html` (the attempts
table and the dead-letter table), wrap each `<table>` in:

```
<div class="table-scroll" role="region" tabindex="0" aria-label="...">
```

with a specific `aria-label` per table (`Payroll runs`, `Fixture drill-in`,
`Attempts distribution`, `Dead letter`). `role="region"` plus a name plus `tabindex="0"`
is the standard treatment for a scrollable region; without `tabindex` a keyboard-only
user cannot reach the overflowed columns. Do NOT wrap `.subtable` elements in
`run_detail.html` or `index.html` — those are two-column and already fit.

**1d. Add the two new width classes** to `app/static/style.css` (used by Task 2's
inline-attribute removal, declared here because they are part of the narrow-width fix):

```
.select-inline { width: auto; min-width: 240px; }
```

**1e. Move `ops.html`'s inline grid override to a class.** The metric strip on the
queue-depth panel carries an inline two-column grid declaration, and an inline
declaration outranks a media query — so the stacking rule in 1a would silently not
apply there. Replace it with `.metric-strip--pair { grid-template-columns: repeat(2, 1fr); }`
in the stylesheet and the class in the markup. This is the ONE inline attribute to
remove outside `index.html` in this task; leave `ops.html`'s two metric-value font-size
overrides alone (out of scope).

**1f. Add a parse-level guard** to `tests/test_design_tokens.py` that reads the live
stylesheet, extracts the `@media (max-width: 700px)` block, and asserts it names `nav`,
`.page-wrapper`, `.form-inline`, and `.demo-select`, and that the shell padding inside
that block is not the 64px token. Reuse the file's existing module-level `_STYLE_CSS`
read; do not add a second disk read.

**Honesty requirement, binding on this task:** browser automation is unavailable this
session. Every claim this task makes is CSS arithmetic against the stylesheet source, not
an observed render. Do not write a verification step, a comment, or a SUMMARY line that
implies a rendered layout was seen at any width.
  </action>
  <verify>
    <automated>uv run pytest -q tests/test_design_tokens.py tests/test_demo_landing.py tests/test_dashboard.py tests/test_ops_route.py</automated>
    <automated>uv run ruff check app tests</automated>
  </verify>
  <done>
The single breakpoint now adjusts the shell inset, card padding, inline-form wrapping,
both fixed-width selects, both multi-column grids, and wide-table minimum width. The four
wide tables sit in focusable, labelled scroll regions. `ops.html`'s inline grid override
is a class, so the stacking rule is not defeated by specificity. A parse-level test pins
the breakpoint's contents. No rendered-visual claim is made anywhere.
  </done>
</task>

<task type="auto">
  <name>Task 2: Titles, nav current-page state, button base composition and the money-gate split, dead classes, inline attributes</name>
  <files>
    app/templates/base.html,
    app/templates/index.html,
    app/templates/runs_list.html,
    app/templates/run_detail.html,
    app/templates/eval.html,
    app/templates/ops.html,
    app/static/style.css,
    tests/test_demo_landing.py
  </files>
  <read_first>
    app/templates/base.html:1-20,
    app/static/style.css:426-527 (the .btn base and its three cloning variants),
    app/templates/runs_list.html:20-45 and :84-92 (the poller's three query hooks and
    the markup they select),
    tests/test_demo_landing.py:934-950 (the accent-count pin that this task must
    deliberately update)
  </read_first>
  <action>
**2a. Per-page titles.** In `base.html`, turn the bare title into
`<title>{% block title %}Pyrl{% endblock %}</title>`. Each content template overrides it,
page name first so a truncated tab still shows the distinguishing part:

- `index.html` -> `Pyrl · Deterministic payroll decisioning` (brand first: this is home)
- `runs_list.html` -> `Payroll runs · Pyrl`
- `run_detail.html` -> `Run detail · Pyrl`
- `eval.html` -> `Eval results · Pyrl`
- `ops.html` -> `Transport ops · Pyrl`

Use the middle-dot separator, matching the separator the failure-summary join already
uses. Keep the titles static; do not interpolate a run id.

**2b. Nav current-page indicator, no JavaScript.** All five routes render through
`templates.TemplateResponse(request, ...)`, so `request` is in the template context
(confirmed at `app/routes/dashboard.py:127`, `:185`, `app/routes/ops.py:65`,
`app/routes/runs.py:827`, `:1208`). In `base.html`, bind `{% set nav_path = request.url.path %}`
and emit ` aria-current="page"` on: the brand when the path is exactly `/`; the Runs link
when the path is `/runs` or starts with `/runs/`; the Eval link when the path starts with
`/eval`; the Ops link when the path starts with `/ops`. Do not add a defensive
`if request` fallback — all five call sites pass it and Task 2's test proves it.

Style it in `app/static/style.css` as:

```
nav a[aria-current="page"] {
  color: var(--text);
  font-weight: 600;
}
```

Two signals (ink and weight), no underline (the design record forbids underline for nav
state), and no accent (the accent marks the next action, not the current location).
`aria-current` carries the non-visual half.

**2c. Buttons: one base, real modifiers, and the money gate split out.** Rewrite the
button section of `app/static/style.css` so `.btn` is the only place the seven base
properties are declared (display, padding, radius, font family/size/weight, border,
cursor, transition) along with the focus ring and the half-pixel press. Each modifier
then declares ONLY its deltas:

- `.btn-accent` — accent background, white label, resting lift; hover deepens the accent
  and raises to the hover lift. This is the accent fill, and it replaces the current
  approve class at every site EXCEPT one.
- `.btn-approve` — retained for exactly ONE site: `Approve & Send` on `/runs/{id}`. It is
  the money gate: the single irreversible action that releases a payroll to a client. It
  composes `.btn .btn-accent .btn-approve` and carries a real visual delta rather than
  being a name with no CSS behind it — `padding: 10px 22px; font-weight: 600;` so the
  button that spends money is never the same size as a demo trigger. 600 is inside the
  system's three permitted weights.
- `.btn-reject` and `.btn-retrigger` keep their names (already unambiguous) and shed
  their duplicated base properties, keeping only background, color, border-color, hover,
  and the danger-tinted focus ring on reject.

Then update every button in every template to `class="btn btn-X"`. The full site list:
`index.html` gate CTA -> `btn btn-accent`; `index.html` noscript picker submit and
`Run pipeline` -> `btn btn-retrigger`; `runs_list.html` and `eval.html` Send Test Email
-> `btn btn-accent`; `run_detail.html` Resolve &amp; Resume, the two clarification
delivery-review actions, Mark delivered, and Simulate client reply -> `btn btn-accent`;
`run_detail.html` all three Reject buttons and Authorize a new confirmation ->
`btn btn-reject`; `run_detail.html` Re-trigger from Start -> `btn btn-retrigger`;
`run_detail.html` Approve &amp; Send -> `btn btn-accent btn-approve`.

**2d. Update the accent-count pin deliberately** at `tests/test_demo_landing.py:948`.
Its current assertion counts the old approve class, which the landing page no longer
carries. Replace it with a STRICTLY STRONGER pair: assert the accent class appears
exactly once (the one accent CTA constraint, preserved), AND assert the money-gate class
appears zero times on `/`. Update the test's docstring at :936 to match. This is the only
pre-existing assertion this plan changes, and it changes by gaining a clause.

**2e. Resolve the four class names with no CSS behind them, per class, not by blanket
deletion.** The audit splits them one-to-three:

- `mt-md` (run_detail.html, the retrigger wrapper) is a genuinely missing style: the
  element duplicates the spacing inline instead. Add `.mt-md { margin-top: var(--space-md); }`
  beside its `mt-lg` / `mt-xl` / `mt-2xl` siblings and delete the now-redundant inline
  attribute from the markup.
- `status-badge`, `failure-summary`, and `failure-secondary` are NOT dead markup and NOT
  missing styles — they are the three query hooks the runs-list poller selects on
  (`runs_list.html` lines 23, 34, 39, and the className rebuild on line 25). Rename all
  three to a `js-` prefix (`js-status-badge`, `js-failure-summary`,
  `js-failure-secondary`) in BOTH the markup and every selector and className rebuild in
  the same file, so their nature is visible from the markup alone. Do not touch
  `run_detail.html`'s `id="run-status-badge"` — that is an id, not one of these classes,
  and its poller selects it by id.

**2f. Move `index.html`'s four inline presentational attributes to classes.** Add to the
stylesheet: `.form-label--flush { margin-bottom: 0; }`,
`.form-inline--flush { margin-bottom: 0; }`,
`.form-help--stacked { margin: 0 0 var(--space-sm) 0; }` (the 8px literal it replaces is
exactly the small spacing token), plus `.select-inline` from Task 1d. Apply them to the
picker label, the picker select, the composer's flush inline row, and the walkthrough
helper paragraph. `index.html` must end with zero inline presentational attributes.

Reuse `.form-inline--flush` at the two other sites carrying the identical duplicated
literal (`runs_list.html` and `eval.html` demo-scenario forms) — same commit, same class,
two-token swap, and the duplication is exactly what DRY forbids leaving behind. Leave
every other inline attribute in `runs_list.html`, `eval.html`, `run_detail.html`, and
`ops.html` alone; they are out of this task's scope and only `index.html` is gated at zero.
  </action>
  <verify>
    <automated>uv run pytest -q tests/test_demo_landing.py tests/test_dashboard.py tests/test_ops_route.py</automated>
    <automated>uv run ruff check app tests</automated>
  </verify>
  <done>
Five distinct tab titles. The nav marks the current page with `aria-current` plus ink and
weight, with JavaScript off. One `.btn` base, four modifiers, no re-declared base
properties, and the money-gate class present at exactly one markup site. The four
CSS-less class names are resolved individually: one gained a rule, three gained a `js-`
prefix marking them script hooks. `index.html` carries no inline presentational
attributes. The accent-count pin is stricter than it was.
  </done>
</task>

<task type="auto">
  <name>Task 3: Durable guards, the cold-start assessment, and reconciling the design record</name>
  <files>
    tests/test_design_tokens.py,
    tests/test_dashboard.py,
    DESIGN.md,
    .impeccable/design.json
  </files>
  <read_first>
    tests/test_design_tokens.py:95-100 and :176-203 (the existing contrast helper and
    the pair table this task extends),
    tests/test_dashboard.py:480-540 (the existing error-status run-detail render test),
    DESIGN.md:289-306 (the layout "known gap" paragraph),
    DESIGN.md:327 and :345-355 and :387-392 and :419-433 (the shapes note, the button
    "known drift" note, the navigation "no mobile treatment" note, and the don'ts list),
    .impeccable/design.json:128-153 (the stale shadow entry and the breakpoints array)
  </read_first>
  <action>
**3a. Pin the muted-ink contrast cluster.** Extend the pair table in
`tests/test_design_tokens.py`'s existing contrast test — or add a sibling test reusing
the same `_contrast_ratio` helper and `_ROOT_TOKENS` — covering muted ink against the
page ground, against surface white, and against recessed white. The page-ground pair is
the tight one: it computes to roughly 4.55:1, clearing AA by 0.05, and it is what
`.lede`, `.form-help`, and `.column-label` all render on. Name those three consumers in
the test docstring so a future reader knows what the pin protects. Ratios must be
recomputed from the parsed `:root` block, never hard-coded, so the gate cannot drift from
the stylesheet.

**3b. Pin the button composition.** Add a test that parses the live stylesheet and
asserts each button modifier rule body declares none of the base properties (display,
font-family, font-size, cursor, border-radius, padding — except the money gate, which
legitimately overrides padding and weight and should be allowlisted by name with a
comment saying why). Add a second assertion that walks `app/templates/*.html` and, for
every class attribute containing a modifier token, requires the bare base token to be
present in the same attribute — the composition rule made enforceable.

**3c. Pin the class-hygiene rule.** Add a test asserting that the three renamed script
hooks appear in `runs_list.html` under their `js-` prefix and appear nowhere in
`app/static/style.css`, and that their unprefixed former names appear in neither file.
Also assert the spacing helper that was missing now has a rule.

**3d. Strengthen the existing error-render test rather than adding a new one.** The
post-redirect failure path IS already covered: `tests/test_dashboard.py:480` renders an
`error`-status run detail, proves the PII-safe reduction at
`app/routes/runs.py:165` holds, and includes a falsification step. The one thing it does
not pin is that the page offers the operator a way out. Add one assertion to that
existing test that the retrigger affordance renders. Do not weaken or restructure
anything else in it.

**3e. Prove the nav mechanism live.** Add a test asserting `aria-current="page"` appears
exactly once on each of `/`, `/runs`, and `/eval` using the existing client fixture.
Three routes is enough to prove `request.url.path` resolves through `base.html`; do not
build new fixtures for `/runs/{id}` or `/ops` just for this.

**3f. Cold start — record the finding, build nothing.** Write this into the SUMMARY as an
explicit assessment, not as work:

- A real cold start was measured at roughly 23s this session: HTTP 503 with
  `Retry-After: 5`, showing Render's own unbranded loading page. This is consistent with
  the 30-60s range PRODUCT.md:68-69 already records, so PRODUCT.md is not false and must
  NOT be edited.
- The 503 originates at Render's edge before any FastAPI worker exists. There is no
  in-app surface to style, no template that runs, and nothing this codebase can do about
  the platform loading page. Do not add a spinner, a fake progress indicator, or a
  "waking up" banner — a sleeping app cannot render one, and shipping one would be the
  overclaiming failure PRODUCT.md warns against.
- The only in-app affordance that exists already shipped in group 1: the landing page's
  queue-error callout names the 15-minute sleep and the wake latency, and the walkthrough
  section offers the recording as a stand-in while the service wakes.
- A demo run that fails AFTER the redirect to `/runs/{run_id}` is covered today. Phase 8's
  PII-safe `error_detail` column renders through `_safe_failure_presentation` into the
  error banner with stage, reason, and attempts, plus a Re-trigger button
  (`run_detail.html` error banner and retrigger block). Report this as **already
  covered**; the only change is the one added assertion in 3d.

**3g. Reconcile DESIGN.md and `.impeccable/design.json`.** Every statement below is
falsified by this commit and must be corrected in it:

In `DESIGN.md`:
- The layout section's "Known gap" paragraph claiming one breakpoint adjusting only two
  things, and that wide data tables have no small-screen treatment.
- The Navigation component's "Mobile: no treatment. The nav does not adapt below 700px."
- The Navigation component gains a current-page state line.
- The Buttons section's "Known drift" note that the base class is used by no template
  (also stale on its line number).
- The don't "Don't clone the button base into a new class, as the three current variants
  do" — the trailing clause is now false.
- The don't naming four class names with no CSS behind them — replace it with the
  standing rule and the `js-` prefix convention.
- The Shapes section's claim that nothing is circular except the badge dot and the play
  overlay — the play overlay was deleted in commit `1d81d2f`.
- Add a named rule for the `js-` prefix convention: a class that exists only as a script
  query hook carries a `js-` prefix and never appears in the stylesheet; a class without
  that prefix has CSS behind it.

In `.impeccable/design.json`:
- Delete the `play-overlay` entry from the `shadows` array (its button was deleted in
  `1d81d2f`).
- Correct the `breakpoints` entry: it is no longer "the only breakpoint... adjusts the
  conversation heading and disclosure summary... coverage is thin."
- Mirror the two corrected `donts` strings so the sidecar and the prose agree.
- Leave `generatedAt` untouched: it records when the scan ran, and bumping it by hand
  would assert a scan that did not happen.

Do NOT re-run any design scan and do NOT regenerate either file wholesale — these are
targeted corrections to specific false statements.
  </action>
  <verify>
    <automated>uv run pytest -q</automated>
    <automated>uv run ruff check app tests</automated>
    <automated>uv run mypy</automated>
    <automated>test -z "$(git diff --name-only HEAD -- app/pipeline app/routes/demo.py)"</automated>
  </verify>
  <done>
The muted-ink cluster, the button composition rule, and the class-hygiene rule are all
pinned by tests that recompute from live source. The existing error-render test gained a
recovery-affordance assertion. The nav mechanism is proven on three live routes. The
cold-start finding is recorded as an assessment with the honest boundary between what is
fixable in-app and what belongs to the platform, and the post-redirect failure path is
reported as already covered. Neither design record makes a claim this commit falsified.
Full suite, lint, and strict type check are green, and the pipeline and demo route are
byte-identical to HEAD.
  </done>
</task>

</tasks>

<verification>
**Automated, complete:**

```
uv run pytest -q
uv run ruff check app tests
uv run mypy
test -z "$(git diff --name-only HEAD -- app/pipeline app/routes/demo.py)"
```

**Manual, one-time confirmation before commit:**

- `grep -rn 'btn-approve' app/templates` returns exactly one line (the Approve &amp; Send
  money gate in `run_detail.html`).
- Each of the five content templates declares a distinct title block.

**NOT VERIFIED — and this must survive into the SUMMARY verbatim:**

> Browser automation was unavailable this session. No rendered visual confirmation of any
> layout at any viewport width was possible. The narrow-width work in Task 1 is CSS
> arithmetic against the stylesheet source (64px insets each side leave roughly 262px of
> content at 390px, against a 240px-minimum select), not an observed screenshot. The
> structural causes are fixed and pinned by a parse-level test; whether the result looks
> right at 390px, 700px, or anywhere between is **unverified**. The user explicitly chose
> "fix now, mark unverified." This item carries forward as an open visual check, alongside
> the identical outstanding check from group 3a (reflow at 640/820/960/1280).

Do not write, in any commit message, comment, or SUMMARY line, that a layout was seen,
checked visually, or confirmed at any width.
</verification>

<success_criteria>
- At 390px the shell inset is 16px, not 64px, and neither select asserts a fixed minimum.
- The four wide tables scroll inside focusable, labelled regions instead of crushing.
- Five distinct tab titles; the nav marks the current page without JavaScript and without
  an underline.
- One `.btn` base with four non-cloning modifiers; the money-gate class has exactly one
  markup site.
- `index.html` has zero inline presentational attributes.
- Zero class names in templates without either a CSS rule or a `js-` prefix.
- Muted-ink contrast is pinned above 4.5:1 by a live recomputation.
- The cold-start assessment is recorded honestly, with the post-redirect error path
  reported as already covered and nothing built to fake platform control.
- DESIGN.md and `.impeccable/design.json` contain no statement this commit falsified.
- `app/pipeline/` and `app/routes/demo.py` are byte-identical to HEAD.
</success_criteria>

<output>
Create `.planning/quick/260726-ugm-narrow-width-adaptation-cold-start-reass/260726-ugm-SUMMARY.md` when done.

The SUMMARY must carry, in its own section and not buried in a list:
1. The unverified-visual statement from `<verification>` above, verbatim.
2. The cold-start assessment from Task 3f, including the "already covered" finding for the
   post-redirect error path and the explicit statement that the 503 is Render's, not the
   app's.
3. The one pre-existing assertion this plan changed (`tests/test_demo_landing.py:948`) and
   why the change is a strengthening rather than a weakening.
</output>
