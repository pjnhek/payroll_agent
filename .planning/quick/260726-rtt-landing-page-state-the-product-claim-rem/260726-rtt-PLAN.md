---
phase: quick-260726-rtt
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
requirements: [QUICK-260726-rtt]
must_haves:
  truths:
    - "A first-time visitor to / reads the product's differentiating claim (LLM reads, deterministic code decides) above the fold, paired with the required standing disclaimer."
    - "A plain GET / renders no operator binding state: the confirmation sentence, the literal 'Path-2', and the literal 'armed for' are all absent from the response body."
    - "GET /?bound=1 still renders a confirmation naming the bound client business, so the /demo/bind operator flow and the Path-2 live-email capability are intact."
    - "The composer's default subject renders as a complete string with no trailing dangling-Jinja artifact."
    - "The demo queue-error callout names what failed, gives a cold-start-aware next step, and never echoes the query-string value."
  artifacts:
    - app/templates/index.html
    - app/routes/dashboard.py
    - app/static/style.css
    - tests/test_demo_landing.py
  key_links:
    - "POST /demo/bind -> 303 /?bound=1 -> the landing template's bound branch (the only surface that renders binding state)."
    - "dashboard.landing's binding read is gated on bound == '1', so operator state never enters the template context on the common path."
    - ".callout-error a inherits var(--danger-hover), mirroring .ops-alarm-banner a at app/static/style.css:757."
---

<objective>
Group 1 of 3 from the `/` design critique (`.impeccable/critique/2026-07-27T02-42-19Z__app-templates-index-html.md`, 21/36). Display and copy only, on four items: state the product claim, stop leaking operator binding state to every visitor, fix the dangling-Jinja subject default, and make the queue-error callout actionable.

Purpose: `/` is the proof surface an outside evaluator lands on with roughly 90 seconds. Today it opens with "Try it live" and generic pipeline mechanics, never states the differentiator, and shows undefined operator jargon in success-green to everyone.

Output: a rewritten `index.html` header + two callouts, one route-level read gate, one token-referenced CSS line, and four test changes (three new, one strengthened).

**Hard scope boundary: no file under `app/pipeline/` is touched by this plan.** No pipeline, money, tax, decision, or queue logic changes. `app/routes/demo.py` is not modified — `/demo/bind`, `/demo/compose`, and `/demo/send-test` keep their exact current behavior and redirects.
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
</context>

<decisions_locked>
These were resolved during planning against the live source. Do not re-litigate them; implement as written.

1. **`app/routes/demo.py` is NOT modified.** Every fix lands in the template, the landing route's read gate, one CSS line, and tests.
2. **Operator state is gated on `?bound=1`, not moved to another page.** `/demo/bind` already redirects to `/?bound=1` (`app/routes/demo.py:158`, pinned by `tests/test_demo_landing.py:1147`). Rendering binding state only on that redirect removes it from every visitor while keeping the operator confirmation and the Path-2 capability intact. Moving it to `/ops` would pull a second surface into a copy-only change.
3. **The two callouts at `index.html:83-91` and `:93-100` merge into one** `bound`-gated `callout-info`. Rejected: `callout-success` — nothing money-moving succeeded, and DESIGN.md reserves the good/process families for real outcomes.
4. **Subject default becomes the literal `Payroll submission`** — byte-identical to the server default at `app/routes/demo.py:170` and `:213`, so one canonical string exists. Rejected: injecting a real date from the route, because a wall-clock-derived default makes the demo irreproducible across screenshots and adds a second date source of truth for a field the pipeline already treats as optional (`pay_period_start` is nullable).
5. **The queue-error callout must not claim nothing was recorded.** `wake.wake()` at `app/routes/demo.py:236` sits *inside* the try block, so a post-commit wake failure also redirects to `/?demo_queue_error=1` — in that path the run *was* created. Copy therefore points at `/runs` to check, instead of asserting an outcome the handler cannot know.
6. **`runs_list.html:117` keeps its current string.** `tests/test_dashboard.py:1115` pins it, and that template is not in this group. Copy divergence between `/` and `/runs` for this callout is a recorded, deliberate leftover for a later group — do not "fix" it here and do not weaken that test.
7. **The standing disclaimer is added under the lede.** PRODUCT.md:131 requires it and it exists on no web surface today (`base.html` has no footer). Principle 3 forbids strengthening the claim without its limit, so the two ship together.
</decisions_locked>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: State the product claim on / with its standing disclaimer</name>
  <files>app/templates/index.html, tests/test_demo_landing.py</files>
  <read_first>README.md:5-10 (canonical claim wording), PRODUCT.md:39-46 (Positioning), PRODUCT.md:131-132 (required disclaimer), DESIGN.md typography hierarchy (headline = the one h1; lede = 400/15px capped near 640px)</read_first>
  <behavior>
    - GET / response body contains the h1 text `The LLM reads. Deterministic code decides.`
    - GET / response body contains the phrase `owns employee resolution and the process-or-clarify decision`
    - GET / response body contains `not tax-compliant payroll software`
    - GET / still contains `demo/compose` (the composer affordance survives the header rewrite)
  </behavior>
  <action>
Rewrite `app/templates/index.html:3-7`.

Set the `h1` to the positioning line already confirmed in PRODUCT.md:39: `The LLM reads. Deterministic code decides.` One h1 per page; do not add a second heading.

Replace the lede with two sentences, both sourced from README.md:5-10 — introduce no factual claim beyond them. Sentence one: a client business emails its employees' hours; the pipeline reads the email, calculates the payroll, and pauses for one human approval before the confirmation goes back. Sentence two: deterministic code owns employee resolution and the process-or-clarify decision, and unresolved names, alias collisions, and missing required fields cannot silently advance to payroll calculation. Do not repeat "the LLM reads" in the lede — the h1 already carries it. Keep the existing `class="lede"`; add no new CSS class.

Directly below the lede add the standing disclaimer required by PRODUCT.md:131 as a single muted line reusing the existing `form-help` class, capped near the lede measure with an inline `max-width` (the file already uses inline one-off widths at lines 11, 12, 73, 103, 105 — stay consistent with that, add no stylesheet rule). Wording: educational portfolio project, not tax-compliant payroll software, not for paying real employees. No emoji, no em-dash in the disclaimer line.

The "Select a client business and compose a payroll email" / "No email client needed" affordance copy leaves the lede. Append `No email client needed.` to the existing composer helper at `index.html:75-77` so the affordance is stated where the control is, not in the page's claim slot. Change nothing else in that block.

Then strengthen the existing assertion at `tests/test_demo_landing.py:783`: it currently passes on `b"Try it live" in resp.content OR b"demo/compose"`, and "Try it live" is being removed. Convert it to require BOTH the new h1 text AND `demo/compose`. This is a tightening, not a weakening — the test must fail if either the claim or the composer disappears.

Add one new test in `tests/test_demo_landing.py` beside the existing landing tests (use the module's `client` fixture at :738), asserting the four behaviors above against a single `client.get("/")`.
  </action>
  <verify>
    <automated>uv run pytest -q tests/test_demo_landing.py -k "landing" </automated>
  </verify>
  <done>GET / opens with the code-owned-decision claim and its disclaimer; the strengthened assertion at test_demo_landing.py:783 requires both the claim and the composer; no reference to the removed "Try it live" string remains anywhere in tests/.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Stop leaking operator binding state; keep the /demo/bind flow whole</name>
  <files>app/templates/index.html, app/routes/dashboard.py, tests/test_demo_landing.py</files>
  <read_first>app/routes/dashboard.py:33-102 (landing handler and its context dict), app/routes/demo.py:139-159 (bind route and its 303 to /?bound=1), tests/test_demo_landing.py:1112-1150 (the test pinning that redirect)</read_first>
  <behavior>
    - Plain `GET /` with `get_demo_binding` returning a real business UUID renders NONE of: the confirmation sentence, the literal `Path-2`, the literal `armed for`.
    - `GET /?bound=1` with the same binding renders a confirmation naming the bound business, asserted on the full sentence fragment (for example `processed as a run for Metro Deli Group`) — NOT on the bare business name, which legitimately appears in the picker `<option>` list on every render.
    - `GET /?bound=1` with `get_demo_binding` returning `None` still renders a confirmation and renders no raw UUID.
  </behavior>
  <action>
In `app/routes/dashboard.py`, gate the binding read: perform the `repo.get_demo_binding(DEMO_OPERATOR_EMAIL)` lookup and the `armed_business_name` resolution only when the `bound` query value equals `"1"`. Otherwise leave both context values `None`. Keep the existing `try/except` around the repo call and the existing comment explaining why the UUID-to-name match happens in Python rather than in the template. Keep both keys present in the context dict so the template contract is unchanged. This makes the no-leak property structural — the value never reaches the template on the common path — and drops one DB round-trip from every landing render, which PRODUCT.md Principle 5 counts as a product decision.

In `app/templates/index.html`, replace both blocks at `:82-100` with ONE block gated on `bound == "1"`, using the existing `callout-info` class (do not use `callout-success`, and add no new CSS). Inside it: a bolded lead naming that operator routing was updated, then one sentence in outsider-legible product vocabulary — payroll email sent from the operator's own mailbox will now be processed as a run for `{{ armed_business_name | e }}`. Do not use the strings `Path-2` or `armed` in any rendered text. When `armed_business_name` is falsy, fall back to wording that does not name a business; never print the raw business UUID, which the old template did as its fallback. Keep the `| e` filter on the DB-derived name and keep Jinja autoescaping intact. Update the surrounding Jinja comments so the source describes the single bound-confirmation block rather than the two removed ones.

`POST /demo/bind` and its 303 to `/?bound=1` are unchanged, so the Path-2 live-email demo capability and the recorded walkthrough it backs both keep working. Do not add a bind form to this page — `tests/test_demo_landing.py:786` and `:795` require `action="/demo/bind"` to stay absent from `/`.

Add one new test covering all three behaviors above. Build the armed state by re-applying `monkeypatch.setattr` to `repo.get_demo_binding` after requesting the `client` fixture — the route resolves that attribute at request time, so a late patch takes effect. Use the seeded Metro Deli UUID `b0000002-0000-0000-0000-000000000002`, which the fixture's `list_businesses` already returns, so the name resolution has something to match. Assert both halves in one test: the plain-GET absence AND the `?bound=1` presence. An absence-only test would also pass if the confirmation were deleted outright, which would silently break the operator flow.
  </action>
  <verify>
    <automated>uv run pytest -q tests/test_demo_landing.py</automated>
  </verify>
  <done>Binding state renders only on the /demo/bind redirect and never enters the template context otherwise; the confirmation still names the bound business; no rendered text contains Path-2 or armed; the bind route, its redirect, and the no-bind-form-on-landing assertions are untouched and green.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Complete the subject default and make the queue-error callout actionable</name>
  <files>app/templates/index.html, app/static/style.css, tests/test_demo_landing.py</files>
  <read_first>app/routes/demo.py:167-241 (compose handler: subject default at :170, the `subject or "Payroll submission"` fallback at :213, and the except-block redirect at :239-241), app/static/style.css:704-709 (.callout-error), app/static/style.css:757-759 (.ops-alarm-banner a — the precedent for a link inside a tinted banner), PRODUCT.md:68-70 (cold-start facts)</read_first>
  <behavior>
    - GET / renders the subject input with value exactly `Payroll submission`; the response body contains no occurrence of `week of`.
    - `GET /?demo_queue_error=1` renders copy that names the failure, states the sleep/wake fact, and links to `/runs`.
    - `GET /?demo_queue_error=<hostile string with angle brackets and a script tag>` does not contain that hostile string anywhere in the response body.
  </behavior>
  <action>
Fix `app/templates/index.html:62`: set the input's `value` to the literal `Payroll submission`, byte-identical to the server default at `app/routes/demo.py:170`. This removes the `{{ '' }}` artifact and the orphaned `week of ` fragment together. Do not add a date, a route-supplied timestamp, or a `TAX_YEAR` reference.

Rewrite the callout body at `app/templates/index.html:51-55`, keeping the `callout callout-error` classes and `role="alert"` as they are. The copy must: (a) bold-lead with what failed in plain words — starting this payroll run; (b) state the honest, citable platform fact from PRODUCT.md:68-70 — the service sleeps after 15 idle minutes and takes up to a minute to wake, so a first attempt right after arriving can fail; (c) give the next step — wait a moment and submit again; (d) give the second step — if it fails again, check `/runs` via one inline text link to see whether the run was recorded, or watch the recorded walkthrough further down the page. Use PRODUCT.md's "up to a minute" framing; do not quote a precise measured latency figure. Do NOT assert that nothing was recorded (see locked decision 5) and do not name a cause the handler cannot know. Do not render the query value; the flag is already reduced to a boolean presence bit at `app/routes/dashboard.py:99`, so keep it that way. The inline link is a link, not a second primary button — do not add a button, and do not give this callout accent weight.

Add exactly one rule to `app/static/style.css`, adjacent to the `.callout-error` block, giving `.callout-error a` the color `var(--danger-hover)`. This mirrors `.ops-alarm-banner a` at `:757` verbatim in structure. Reference the token; introduce no hex literal, no new custom property, and no other stylesheet change.

Add one new test covering the three behaviors above. For the hostile-value case assert only that the hostile string is absent — on `/` a non-`"1"` value is falsy so the callout does not render at all, which differs from the `/runs` variant at `tests/test_dashboard.py:1105`; do not copy that test's copy-presence assertion across.

Then run the full suite and the lint pass. Confirm the diff's blast radius: no file under `app/pipeline/` appears in it, `app/routes/demo.py` is unmodified, and the stylesheet diff adds no hex literal.
  </action>
  <verify>
    <automated>uv run pytest -q && uv run ruff check app tests && test "$(git diff --name-only HEAD -- app/pipeline app/routes/demo.py | wc -l | tr -d ' ')" = "0" && test "$(git diff -U0 HEAD -- app/static/style.css | grep '^+' | grep -v '^+++' | grep -cE '#[0-9A-Fa-f]{3,8}')" = "0"</automated>
  </verify>
  <done>The subject default renders complete with no `week of` fragment; the queue-error callout names the failure with cold-start-aware guidance and a /runs link; `.callout-error a` uses var(--danger-hover) with no new hex; `uv run pytest -q` is green; ruff is clean; the diff touches no pipeline file and does not modify app/routes/demo.py.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| query string -> landing template | `?bound=`, `?demo_queue_error=`, `?business=` are attacker-controlled and reach a rendered page |
| Postgres -> landing template | `armed_business_name` is DB-derived text rendered into HTML |
| public internet -> operator-only state | `/` is unauthenticated; anyone can craft any query string |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-rtt-01 | Information disclosure | `GET /` binding display (`app/routes/dashboard.py:72-87`, `index.html:83-91`) | low | mitigate | Task 2 gates the `get_demo_binding` read on `bound == "1"`, so operator binding state is absent from the context and the DOM on every unflagged request |
| T-rtt-02 | Tampering (reflected XSS) | `demo_queue_error` query value | medium | mitigate | Value stays an allowlisted presence bit (`== "1"` at `app/routes/dashboard.py:99`); Task 3 renders fixed copy only and adds a test asserting a hostile value never appears in the body |
| T-rtt-03 | Tampering (stored XSS) | `armed_business_name` from Postgres | low | mitigate | Jinja autoescape plus an explicit `| e` retained on the name; raw-UUID fallback removed rather than widened |
| T-rtt-04 | Spoofing | `POST /demo/bind` | low | accept | Unchanged by this plan: `business_name` is allowlist-validated and `operator_email` is the hardcoded constant (`app/routes/demo.py:153-156`). No new attack surface added |
| T-rtt-05 | Elevation of privilege | crafted `?bound=1` by a non-operator | low | accept | `?bound=1` only reveals which seeded demo business is bound. The page has no auth by design (PRODUCT.md:73) and the copy is written to be legible rather than jargon, so disclosure value is nil |
| T-rtt-SC | Tampering | npm/pip/cargo installs | high | n/a | No package is installed, added, or upgraded by this plan; no dependency change, so the legitimacy gate does not apply |
</threat_model>

<verification>
1. `uv run pytest -q` — full suite green. Existing assertions are only ever tightened, never relaxed; specifically `tests/test_dashboard.py:1115` (the `/runs` copy pin) and `tests/test_demo_landing.py:786`, `:795`, `:1147` must all still pass untouched.
2. `uv run ruff check app tests` — clean.
3. `git diff --name-only HEAD` lists at most `app/templates/index.html`, `app/routes/dashboard.py`, `app/static/style.css`, `tests/test_demo_landing.py`. Nothing under `app/pipeline/`. `app/routes/demo.py` absent.
4. JS-disabled legibility: every change is server-rendered text, one CSS color rule, and one anchor. No script is added. The picker's existing inline `onchange` is untouched.
5. No new hard-coded status hex and no new custom property in `app/static/style.css` (DESIGN.md Token-First Rule). No second accent-weighted call to action added (Accent Is A Pointer Rule) — one primary button remains on the page.
</verification>

<success_criteria>
- `/` states the differentiating claim in the h1 plus one lede sentence drawn from README.md:5-10, paired with the PRODUCT.md:131 standing disclaimer.
- Operator binding state is invisible to a plain visitor at both the context and the DOM level, while `POST /demo/bind -> /?bound=1` still confirms the bound client business by name.
- The composer subject default renders as a complete string identical to the server default, with no `week of` remnant.
- The queue-error callout names the failure, states the cold-start fact honestly, offers two concrete next steps, and never echoes the query value.
- Four test changes: three new tests plus one strengthened assertion. Full `uv run pytest -q` green.
</success_criteria>

<output>
Create `.planning/quick/260726-rtt-landing-page-state-the-product-claim-rem/260726-rtt-SUMMARY.md` when done.
</output>
</content>
</invoke>
