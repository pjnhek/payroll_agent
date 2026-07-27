---
phase: quick-260726-sje
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - app/templates/index.html
  - app/routes/dashboard.py
  - app/static/style.css
  - tests/test_demo_landing.py
autonomous: true
requirements: [QUICK-260726-sje]
must_haves:
  truths:
    - "The first action offered on / runs the gate-tripping fixture (an unresolved name that forces a clarification), not the free-form composer and not a clean-process fixture."
    - "The gate fixture's own email body is rendered verbatim on / above its button, so the evaluator sees the input before the claim is tested."
    - "The composer is still fully present and working, ranked second, below the one-click proof."
    - "Exactly one accent-weighted call to action exists on the page."
    - "The roster and the composer sit inside the system's card vocabulary instead of floating on the bare page ground."
    - "The standing disclaimer renders in ink at a legible size through a class, with no inline style."
    - "At most one uppercase eyebrow survives on the page; each region carries a real heading instead."
    - "The walkthrough poster and its Loom link survive; the accent circle over it does not."
  artifacts:
    - app/templates/index.html
    - app/routes/dashboard.py
    - app/static/style.css
    - tests/test_demo_landing.py
  key_links:
    - "dashboard.LANDING_GATE_FIXTURE_KEY -> DEMO_FIXTURES allowlist -> the hidden fixture_key field -> POST /demo/send-test (app/routes/demo.py:249-252) -> 303 /runs/{id}."
    - "dashboard._gate_fixture_body() reads DEMO_FIXTURES[key]['path'] (a server-owned constant, never a request value) and renders it into <pre class=\"raw-email raw-email--nested\">."
    - "The fixture's own expected.decision.final_action == request_clarification is what makes the page's claim true; a test pins that, so a fixture edit fails loudly instead of quietly turning the lead into a clean run."
---

<objective>
Group 2 of 3 from the `/` design critique. Restructure the landing page as a proof surface: claim, then proof-in-one-click, then substantiation. The gate-tripping fixture becomes the page's primary action; the free-form composer stops being the opening move and becomes the instrument, ranked second and fully intact.

Purpose: the audience is an outside evaluator with roughly 90 seconds and no codebase context, deciding whether the deterministic-gate claim is real. Today the page states the claim (group 1 landed that) and then hands the evaluator a blank textarea. Verifying the claim currently requires knowing which name will trip the gate. The focal moment must be one click away.

Output: a restructured `index.html`, one route constant plus one small fixture-body reader in `dashboard.py`, four stylesheet changes (two rules added, two rules deleted), and five new tests.

**Hard scope boundary: `app/routes/demo.py` is NOT modified, and no file under `app/pipeline/` is touched.** `/demo/send-test`, `/demo/compose`, and `/demo/bind` keep their exact current behavior, validation, and redirects. Both are gated by a diff check in Task 3.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md
@PRODUCT.md
@DESIGN.md
@app/templates/index.html
@app/routes/dashboard.py
@app/static/style.css
@tests/test_demo_landing.py
@.planning/quick/260726-rtt-landing-page-state-the-product-claim-rem/260726-rtt-SUMMARY.md
</context>

<decisions_locked>
These were resolved during planning against the live source. Do not re-litigate them; implement as written.

1. **The primary action posts `fixture_key=unknown_shorthand_metro` to the existing `/demo/send-test`.** No new route. `app/routes/demo.py:249-252` already accepts `fixture_key: str = Form(default=DEMO_FIXTURE_DEFAULT_KEY)` and validates it against `DEMO_FIXTURES` (`:267-269`). `tests/test_dashboard.py:2096-2104` already exercises that exact key end to end.

2. **The key lives in `app/routes/dashboard.py` as `LANDING_GATE_FIXTURE_KEY`, not as a bare literal in the template.** An unknown key does not error, it silently falls back to `DEMO_FIXTURE_DEFAULT_KEY` (`coastal_exact`, a clean exact-match run). A rename inside `DEMO_FIXTURES` would therefore swap the page's demonstrated refusal for its exact opposite with nothing failing anywhere. Task 1 adds a test pinning the key to the allowlist AND to the fixture's own `expected.decision.final_action == "request_clarification"`.

3. **The gate fixture's email body is rendered verbatim above the button**, read server-side from `DEMO_FIXTURES[key]["path"]`. PRODUCT.md Principle 2 ("Show the gate, don't assert it") requires the evidence to include what the client actually sent, and hardcoding the body in the template would let the page drift away from the fixture it fires. Rejected: paraphrasing the body in prose (drifts, and asserts rather than shows).

4. **The gate CTA is the page's only accent-weighted button.** The composer's submit drops from `.btn-approve` to the system's neutral variant `.btn-retrigger` (DESIGN.md calls it "Tertiary / neutral"). The class name reads oddly on a "Run pipeline" button; that is recorded drift from the known dead `.btn` base (DESIGN.md, Buttons, "Known drift") and is group-3 system work, not this plan's. Do not invent a new button class here.

5. **The poster keeps its thumbnail, its Loom link, and its hover lift; the accent circle goes.** Delete both the overlay span in the template and its two stylesheet rules, then give the poster a visible text link so the affordance survives its removal. The `.demo-thumb:hover` lift stays: DESIGN.md sanctions it by name as one of exactly two hover-lift users.

6. **The roster and the composer share ONE card, not two.** The business picker drives both the roster and the composer's hidden `business_name`, so splitting them puts a control in one container and its two effects in another. The roster table inside that card takes the existing `.subtable` class (`box-shadow: none`), which is the system's sanctioned answer to The No Double Frame Rule and the same pattern `run_detail.html:281` uses.

7. **The surviving eyebrow is the roster's `{{ business }} — roster` label.** It names a region inside a card that already has a heading, which is exactly what The Eyebrow Is Not A Heading Rule describes. The composer, the proof, and the walkthrough each get a real `<h2>` instead.

8. **The disclaimer moves from `.form-help` + inline width to a new `.page-disclaimer` class at 13px/500 in `var(--text)`.** No new hex, no new custom property; ink on the page ground is roughly 15:1. Rejected: a tinted callout box, which would cross the two status palettes for something that is not a state.

9. **Two stylesheet rules are added and two are deleted.** Added: `.page-disclaimer` and `.landing-panel` (a 640px measure used by both cards and the walkthrough section, replacing two inline `max-width` styles). Deleted: the poster overlay rules, and `.stack-roster` (`app/static/style.css:604-606`), which is referenced only at `index.html:30` and becomes dead the moment that line is rewritten. `.raw-email` (`:619-633`) is currently dead CSS with zero template references; this plan revives it plus one nesting modifier rather than authoring a new panel style.

10. **The picker gets a `<noscript>` submit button.** It currently submits via `onchange="this.form.submit()"` with no fallback, so with JavaScript off the picker cannot be changed at all. PRODUCT.md states every surface must stay legible AND usable with JavaScript disabled, and this plan is rewriting that exact markup. One `<noscript>`-wrapped neutral button closes it; no script is added.

11. **The queue-error callout stays in the composer card and keeps its group-1 copy verbatim.** It is produced only by `POST /demo/compose`'s failure redirect (`app/routes/demo.py:241`). The gate CTA's own failure redirects to `/runs?demo_queue_error=1` (`:340`), which `runs_list.html:115` already handles. Do not move it, do not duplicate it into the proof card, and do not restate a cold-start caveat next to the gate CTA.
</decisions_locked>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: Lead with the gate-tripping fixture as the page's primary action</name>
  <files>app/routes/dashboard.py, app/templates/index.html, app/static/style.css, tests/test_demo_landing.py</files>
  <read_first>app/routes/demo.py:36-63 (DEMO_FIXTURES, the label and path for the gate fixture, and DEMO_FIXTURE_DEFAULT_KEY), app/routes/demo.py:249-269 (the send-test signature and its allowlist fallback), app/routes/dashboard.py:33-107 (landing handler and its context dict), eval/fixtures/04_unknown_shorthand_metro.json (body_text and expected.decision), app/static/style.css:619-633 (.raw-email), app/templates/eval.html:87-95 (the existing send-test form shape)</read_first>
  <behavior>
    - `dashboard.LANDING_GATE_FIXTURE_KEY` is a key in `DEMO_FIXTURES`, is not `DEMO_FIXTURE_DEFAULT_KEY`, and its fixture file declares `expected.decision.final_action == "request_clarification"`.
    - `GET /` contains a form posting to `/demo/send-test` carrying a hidden `fixture_key` whose value equals `dashboard.LANDING_GATE_FIXTURE_KEY`.
    - `GET /` contains the gate fixture's `body_text` verbatim (HTML-escaped), read from the fixture file by the test so the assertion cannot drift from the shipped fixture.
    - In the response bytes, the `/demo/send-test` form appears BEFORE the `/demo/compose` form: proof outranks composer.
    - `GET /` still contains `demo/compose`, still contains the h1 claim, and still contains `not tax-compliant payroll software`.
  </behavior>
  <action>
In `app/routes/dashboard.py`, add a module-level constant beside the existing `EVAL_*` constants:

`LANDING_GATE_FIXTURE_KEY = "unknown_shorthand_metro"`

Comment it with WHY it is a named constant and not a template literal: `/demo/send-test` silently falls back to `DEMO_FIXTURE_DEFAULT_KEY` on an unknown key, so a rename inside `DEMO_FIXTURES` would replace the page's demonstrated refusal with a clean process run and nothing would fail.

Add a small private helper `_gate_fixture_body() -> str` next to it that returns the gate fixture's `body_text`, or the empty string when it cannot be read. Resolve the path from `DEMO_FIXTURES[LANDING_GATE_FIXTURE_KEY]["path"]` (already imported at `:12`), reusing the module's existing `json` and `Path` imports. It must be total: a missing key, an `OSError`, a `ValueError` from a malformed file, a non-dict payload, or a non-string `body_text` all return the empty string rather than raising, because this runs on the route an evaluator hits first and a broken fixture must cost the page its evidence block, not its response. Write it so `mypy --strict` is satisfied without a cast: reject a non-dict parse result, then narrow `body_text` with `isinstance`. Record in a comment that the path comes from a server-owned constant and never from a request value, so no query parameter can steer the read.

In `landing()`, add two keys to the template context: `gate_fixture_key` set to the constant, and `gate_fixture_body` set to `_gate_fixture_body()`. Change nothing else in that handler; the `bound == "1"` gate and the existing context keys stay exactly as group 1 left them.

In `app/static/style.css`, add two rules only:
- `.landing-panel { max-width: 640px; }` with a comment tying it to The Measure Rule: 640px is the prose cap, and inside a 32px-padded card the controls land near 576px, inside the form measure.
- `.raw-email--nested`, placed directly after the existing `.raw-email` block, setting `box-shadow: none`, `white-space: pre-wrap`, `overflow-wrap: anywhere`, and `margin-bottom: var(--space-md)`. Comment the two reasons: a container nested in a card drops its shadow (The No Double Frame Rule), and evidence wraps rather than scrolling sideways at this measure (evidence is never truncated).

Introduce no hex literal, no new custom property, and no third elevation.

In `app/templates/index.html`, insert the proof section directly below the disclaimer paragraph and above the business picker, as the page's first interactive element. Use `<div class="card card-pad landing-panel section">` containing, in order:
- an `<h2>` naming the focal moment: watch the gate refuse to guess;
- one short paragraph of setup, written WITHOUT naming the employee, the hours, or the business, so it cannot drift from the fixture: a client sends hours for a name that is not on its roster, no employee resolves, deterministic code refuses to calculate payroll and asks the client who was meant, and the LLM only suggests the likely employee for that question rather than making the call;
- `{% if gate_fixture_body %}<pre class="raw-email raw-email--nested">{{ gate_fixture_body | e }}</pre>{% endif %}` on ONE line, with no leading whitespace or newline inside the `<pre>`, since a `<pre>` renders its own indentation;
- a plain `<form method="post" action="/demo/send-test">` (no `.form-inline`, no inline style) holding `<input type="hidden" name="fixture_key" value="{{ gate_fixture_key | e }}">` and one `<button type="submit" class="btn-approve">` whose label says it runs this email through the pipeline;
- one `<p class="form-help">` stating that it runs the real extraction and decision code and then opens the run it creates. State no latency figure and make no claim about how fast the result appears.

Keep the h1, the lede, and the disclaimer text exactly as group 1 shipped them; this task only inserts a section beneath them.

Add two tests to `tests/test_demo_landing.py` beside the existing landing tests, using the module's `client` fixture: one covering the constant behaviors (allowlist membership, difference from the default key, and the fixture's own `expected.decision.final_action`), and one covering the rendered behaviors (hidden field value, verbatim body, and the send-test-before-compose ordering). Derive the expected body in the test by reading the fixture file through `DEMO_FIXTURES`, and compare with `markupsafe.escape` so the assertion holds whatever the body text becomes.
  </action>
  <verify>
    <automated>uv run pytest -q tests/test_demo_landing.py tests/test_dashboard.py -k "landing or gate or fixture"</automated>
  </verify>
  <done>GET / renders the gate fixture's own email verbatim above one accent button that posts the gate fixture key to /demo/send-test, positioned above the composer; the key is pinned by test to the DEMO_FIXTURES allowlist and to a request_clarification expectation; app/routes/demo.py is unmodified.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Give the roster and composer card vocabulary, cut the eyebrows, and quiet the poster</name>
  <files>app/templates/index.html, app/static/style.css, tests/test_demo_landing.py</files>
  <read_first>app/templates/index.html (current state after Task 1), app/static/style.css:595-616 (.composer, .field-group, .section, .stack-roster, .column-label), app/static/style.css:716-729 (.card, .card-pad), app/static/style.css:1023-1071 (.demo-thumb and the overlay rules), app/static/style.css:1073-1091 (.page-links), app/templates/run_detail.html:281 (the subtable-inside-a-panel precedent), DESIGN.md sections "Elevation and Depth" and "Typography > Named Rules"</read_first>
  <behavior>
    - `GET /` renders at most one `class="column-label"` and at least three `<h2` elements, with exactly one `<h1`.
    - `GET /` renders exactly one occurrence of `btn-approve`; the composer's submit button carries the neutral button class instead.
    - With a monkeypatched non-empty roster, `GET /` renders the roster table with the `subtable` class, inside card markup, and the roster eyebrow still names the selected business.
    - `GET /` renders the disclaimer text through `class="page-disclaimer"`, and `app/templates/index.html` no longer contains the string `style="max-width: 640px;"`.
    - `GET /` still contains `demo/compose`, `value="Payroll submission"`, no occurrence of `week of`, and no `action="/demo/bind"`.
    - `GET /?demo_queue_error=1` still renders the group-1 callout copy including the `/runs` link.
    - The poster still links to the Loom URL and still renders `demo-thumbnail.gif`, and the page carries a visible text link to that same URL.
  </behavior>
  <action>
Restructure the rest of `app/templates/index.html`. Preserve every group-1 string verbatim: the h1, the lede, the disclaimer sentence, the composer subject default `Payroll submission`, the queue-error callout copy, and the `bound == "1"` confirmation block. This task moves and re-containers markup; it does not rewrite that copy.

Disclaimer: change its class from `form-help` to `page-disclaimer` and delete its inline `style="max-width: 640px;"`. Add the matching rule to `app/static/style.css` near the other text rules: 13px, weight 500, `color: var(--text)`, `max-width: 640px`, `margin: 0 0 var(--space-lg) 0`. Comment WHY it is ink rather than muted: a prominent claim paired with a whisper-quiet limit is a subtler form of the overclaiming failure PRODUCT.md says this product cannot afford.

Composer card: wrap the business picker, the roster block, the queue-error callout, and the compose form in ONE `<div class="card card-pad landing-panel section">`, placed after the proof card. Give it an `<h2>` that ranks it second and names it as the instrument (writing your own payroll email). Inside:
- the existing picker `<form method="get" action="/">` unchanged except for one addition: a `<noscript>` block holding `<button type="submit" class="btn-retrigger">Show roster</button>`, so the picker is operable with JavaScript off. Keep the `onchange` handler; do not add any script tag.
- the roster block still gated on `{% if employees %}`. Keep `<div class="field-group">` but drop `stack-roster` from its class list, keep the single `<p class="column-label">{{ selected_business_name | e }} — roster</p>`, and add `class="subtable"` to the `<table>` so the nested table drops its shadow. The table's contents and escaping filters are unchanged.
- the queue-error callout block, moved verbatim.
- the compose `<form>` unchanged except its submit button, which becomes `class="btn-retrigger"`. Keep the `.form-help` sentence beside it.

The `bound == "1"` callout block stays where it is in the flow, outside both cards, unchanged.

Walkthrough section: replace the current `<div class="section" style="max-width: 640px;">` with `<div class="section landing-panel">`. Give it an `<h2>` naming it as the recorded email round-trip, keep the existing explanatory `.form-help` paragraph, and add one clause noting the recording also stands in while the free host is still waking (PRODUCT.md records the cold start as part of the first impression). Bind the Loom URL once with `{% set walkthrough_url = "https://www.loom.com/share/b844c3e0a3364a91b114ab892cc41db4" %}` and use it for both anchors, so the URL exists exactly once in the file. Keep the `<a class="demo-thumb">` wrapping the `<img>`, and DELETE the play-overlay `<span>` inside it. Because the overlay carried the only visual signal that this is a video, add one visible text link below the poster using the existing `.page-links` rule: `<p class="page-links"><a href="{{ walkthrough_url }}" target="_blank" rel="noopener">Watch the recorded walkthrough &rarr;</a></p>`. Align the poster anchor's `aria-label` with that link text. This link is a text link, not a second accent-weighted call to action; add no second button anywhere.

Leave the closing `.page-links` navigation block as the last element on the page.

In `app/static/style.css`, delete the two overlay rules (the 56px circle and its hover variant, at `:1044-1061` and `:1068-1071`) and delete the now-unused `.stack-roster` rule at `:604-606`. Keep `.demo-thumb` and its `:hover` lift. Do not touch any other rule.
<!-- planner-discipline-allow: demo-thumb__play -->
<!-- planner-discipline-allow: stack-roster -->

Add three tests to `tests/test_demo_landing.py`: one for the structural counts (one h1, at least three h2, at most one column-label, exactly one btn-approve occurrence); one for the carded roster, which needs its own client with `load_roster_for_business` monkeypatched to return an object whose `employees` list holds two simple stand-ins carrying `full_name`, `pay_type`, and `filing_status`, asserting the `subtable` class, the eyebrow naming the business, and the card markup; and one for the disclaimer, asserting the `page-disclaimer` class in the response and the absence of the inline max-width string from the template source read off disk. Do not weaken or delete any existing assertion in this file or in `tests/test_dashboard.py`.
  </action>
  <verify>
    <automated>uv run pytest -q tests/test_demo_landing.py tests/test_dashboard.py</automated>
  </verify>
  <done>Roster and composer share one card with one surviving eyebrow and real headings; the disclaimer renders in ink through a class with no inline style; the composer submit is neutral so exactly one accent button remains; the poster keeps its thumbnail and Loom link and gained a text link while losing the accent circle; the picker works with JavaScript off; every group-1 string and assertion is intact.</done>
</task>

<task type="auto">
  <name>Task 3: Prove the blast radius and the design rules held</name>
  <files>tests/test_demo_landing.py</files>
  <read_first>the full diff produced by Tasks 1 and 2 (`git diff`), DESIGN.md "Do's and Don'ts", .planning/quick/260726-rtt-landing-page-state-the-product-claim-rem/260726-rtt-SUMMARY.md:157-165 (the verification-evidence shape this repo expects)</read_first>
  <behavior>
    - The stylesheet is free of dead selectors introduced or orphaned by this plan: neither deleted class name appears in `app/static/style.css` or `app/templates/index.html`.
    - `uv run pytest -q` is green, `uv run ruff check app tests` is clean, and `uv run mypy` is clean (the new helper in `dashboard.py` is typed).
    - The cumulative diff touches only the four files in this plan's frontmatter: nothing under `app/pipeline/`, and `app/routes/demo.py` absent.
    - The stylesheet diff adds no hex literal.
  </behavior>
  <action>
Record the base commit for this quick task in the SUMMARY before editing anything else (`git rev-parse HEAD`), and use that SHA in the diff-scope checks below so the gate covers the committed work of Tasks 1 and 2, not just the working tree.

Add one final test to `tests/test_demo_landing.py` that reads `app/static/style.css` and `app/templates/index.html` off disk and asserts the two removed class names appear in neither file. This is the guard that the overlay and the orphaned measure rule stayed removed, and it is a source-text test rather than a shell grep so it runs inside the same suite CI already gates on.
<!-- planner-discipline-allow: demo-thumb__play -->
<!-- planner-discipline-allow: stack-roster -->

Then run the full verification sweep and paste the actual output into the SUMMARY's Verification Evidence section. Do not summarize a command you did not run. If the diff-scope check prints any file outside this plan's four, stop and report rather than adjusting the check.

Confirm by inspection, and record in the SUMMARY:
- exactly one accent-weighted button remains on `/` (Accent Is A Pointer Rule);
- no third elevation was introduced and no nested container carries both a border and a shadow (The Two-Step Rule, The No Double Frame Rule);
- no `<script>` tag was added and every form on the page is a plain GET or POST, so the surface is usable with JavaScript disabled;
- `app/routes/demo.py` behavior is untouched, so the gate CTA's cold-start failure still redirects to `/runs?demo_queue_error=1` where `runs_list.html:115` already handles it.
  </action>
  <verify>
    <automated>uv run pytest -q && uv run ruff check app tests && uv run mypy && test "$(git diff --name-only "$BASE_SHA"..HEAD -- app/pipeline app/routes/demo.py | wc -l | tr -d ' ')" = "0" && test "$(git diff -U0 "$BASE_SHA"..HEAD -- app/static/style.css | grep '^+' | grep -v '^+++' | grep -cE '#[0-9A-Fa-f]{3,8}')" = "0"</automated>
  </verify>
  <done>Full suite green, ruff clean, mypy clean; the cumulative diff since the recorded base SHA lists only the four planned files; no pipeline file and no app/routes/demo.py change; no new hex in the stylesheet diff; the removed class names are absent from both the stylesheet and the template, pinned by a test.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| committed fixture file -> landing template | `eval/fixtures/04_unknown_shorthand_metro.json`'s `body_text` is now read at request time and rendered into HTML on the most-visited route |
| public internet -> state-changing POST | `/` now offers `POST /demo/send-test` as its primary action; the app has no authentication by design |
| form field -> fixture selection | `fixture_key` is client-supplied on every send-test POST (unchanged by this plan) |
| query string -> landing template | `?business=`, `?bound=`, `?demo_queue_error=` remain attacker-controlled and reach a rendered page |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-sje-01 | Tampering (XSS via file content) | `gate_fixture_body` rendered into `<pre>` on `/` | medium | mitigate | Jinja autoescape plus an explicit `\| e`, rendered as a text node inside `<pre>` with no attribute interpolation; Task 1's test compares against `markupsafe.escape(body)` so an unescaped render fails the suite |
| T-sje-02 | Information disclosure (path traversal) | `_gate_fixture_body()`'s file read | low | mitigate | The path is resolved from the module-level `DEMO_FIXTURES` allowlist keyed by a module-level constant; no request value, query parameter, or form field reaches the read, so there is no attacker-controlled path component |
| T-sje-03 | Denial of service (per-request disk read) | `_gate_fixture_body()` on `GET /` | low | accept | One read of a committed sub-kilobyte artifact baked into the image, on a route already doing DB work; `/eval` already reads eighteen such files per request. Every failure mode returns the empty string and the evidence block is skipped, so a broken fixture costs the section, not the response. Rewriting the fixture requires code execution on the container, which is out of scope per the same argument recorded at `app/routes/dashboard.py:135-142` |
| T-sje-04 | Spoofing (CSRF on the new primary action) | `POST /demo/send-test` from `/` | low | accept | Unchanged surface: the same route is already posted from `/runs` and `/eval`. There is no authentication and no privilege to escalate (PRODUCT.md records the no-auth demo as deliberate); a forged post creates one demo run against a seeded `.example` business and nothing else |
| T-sje-05 | Elevation of privilege (fixture selection) | client-supplied `fixture_key` | low | accept | Unchanged by this plan: `app/routes/demo.py:267-269` validates against the allowlist and falls back to the default on a miss; the client never supplies a path |
| T-sje-06 | Repudiation / silent misrepresentation | the page claiming a refusal while firing a clean fixture | medium | mitigate | Task 1's test pins `LANDING_GATE_FIXTURE_KEY` to the allowlist, asserts it differs from `DEMO_FIXTURE_DEFAULT_KEY`, and asserts the fixture's own `expected.decision.final_action == "request_clarification"` so a fixture or key edit fails loudly |
| T-sje-SC | Tampering | npm/pip/cargo installs | high | n/a | No package is installed, added, or upgraded by this plan; `markupsafe` is already a Jinja2 dependency and is test-only usage. No dependency change, so the legitimacy gate does not apply |
</threat_model>

<verification>
1. `uv run pytest -q` — full suite green. Existing assertions are only added to, never relaxed; specifically `tests/test_demo_landing.py::test_landing_get_returns_200_no_bind_form`, `::test_landing_get_states_product_claim_with_disclaimer`, `::test_landing_binding_state_gated_on_bound_query_param`, `::test_bind_route_not_on_landing_page`, `::test_landing_subject_default_complete_and_queue_error_actionable`, and `tests/test_dashboard.py::test_demo_queue_error_notice_uses_fixed_copy_not_query_text` must all still pass untouched.
2. `uv run ruff check app tests` — clean. `uv run mypy` — clean (CI runs `uv run mypy` with `strict = true` over `app` and `tests`).
3. `git diff --name-only "$BASE_SHA"..HEAD` lists at most `app/templates/index.html`, `app/routes/dashboard.py`, `app/static/style.css`, `tests/test_demo_landing.py`. Nothing under `app/pipeline/`. `app/routes/demo.py` absent.
4. `git diff -U0 "$BASE_SHA"..HEAD -- app/static/style.css` adds no hex literal and no new custom property (DESIGN.md Token-First Rule).
5. Exactly one accent-weighted call to action on `/` (Accent Is A Pointer Rule), asserted by an occurrence count in the suite, not by inspection alone.
6. JS-disabled: no `<script>` tag added, every form is a plain GET or POST, and the picker gained a `<noscript>` submit so it is operable without JavaScript for the first time.
7. Anti-goals held: no marketing hero, no testimonials, no invented metrics, no card grid as page structure, no nested cards, no font change, no accent or hue change, no breakpoint work, no per-page `<title>`, no nav active state.
</verification>

<success_criteria>
- The first thing an evaluator can act on at `/` is a single accent button that fires the gate-tripping fixture, with that fixture's own email shown verbatim directly above it.
- The composer is intact, works exactly as before, and ranks second.
- Reading order on the page is claim, then one-click proof, then composer, then supporting evidence links.
- Roster and composer sit inside the card vocabulary; the roster table drops its shadow rather than double-framing.
- The standing disclaimer is legible ink at 13px through `.page-disclaimer`, with no inline style.
- One eyebrow survives; the proof, composer, and walkthrough sections carry real `<h2>` headings.
- The walkthrough poster and its Loom link survive, with a visible text link replacing the deleted accent circle.
- Five new tests; `uv run pytest -q`, `uv run ruff check app tests`, and `uv run mypy` all green; `app/routes/demo.py` and `app/pipeline/` untouched.
</success_criteria>

<output>
Create `.planning/quick/260726-sje-landing-page-restructure-as-a-proof-surf/260726-sje-SUMMARY.md` when done.
</output>
