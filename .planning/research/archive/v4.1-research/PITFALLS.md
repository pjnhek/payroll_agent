# Pitfalls Research — v4.1 Demo Polish & Run-Detail UI

**Domain:** UI/demo polish on a shipped, money-safe payroll app (run-detail conversation view, status poll, paystub YTD, eval chart)
**Researched:** 2026-07-20
**Confidence:** HIGH — every pitfall below is grounded in a direct read of the live source (`app/templates/run_detail.html`, `app/routes/runs.py`, `app/pipeline/pdf.py`, `app/db/schema.sql`, `app/routes/templating.py`, `app/routes/dashboard.py`, `eval/run_eval.py`, `tests/test_dashboard.py`, `tests/test_phase20_clarification_review.py`) as of 2026-07-20, not generic web advice.

## Important scoping finding (read this before planning phases)

Items **1** (chronological conversation) and **2** (progressive-enhancement status poll) are **already implemented and tested** in the current codebase, not greenfield work:

- `app/templates/run_detail.html` already renders one `<section class="conversation">` from `thread_messages`, ascending `created_at`, with **no `[:300]` truncation anywhere** (`<pre class="conversation-message__body">{{ msg.body_text or '' }}</pre>` — full body, autoescaped). The old three-column grid and duplicate `Sent Emails`/`Conversation thread` blocks are gone. Extraction/paystub tables are already inside `<details class="payroll-details">`. The reply composer is already the final element for `awaiting_reply`.
- `app/routes/runs.py` already has `GET /runs/{id}/status` returning the safe JSON projection, and the template already has the ~90-line poll script (stops on terminal status via `POLL_WHILE`, reloads once on status/queue-label change, caps at 60 attempts, silently skips fetch errors).
- Tests already lock this in: `test_run_detail_is_one_ordered_conversation_with_final_reply_composer`, `test_run_detail_has_no_meta_refresh`, `test_run_detail_inflight_poll_reloads_on_settle`, `test_run_detail_poll_reloads_on_status_change_not_just_settle`, `test_run_detail_never_renders_raw_error_detail`, the full `test_phase20_clarification_review.py` suite.
- `app/pipeline/pdf.py` already has the **display** layer for item 3 — `PaystubYtdTotals` dataclass + `.from_prior()` combiner + `generate_paystub_pdf(..., ytd: PaystubYtdTotals | None = None)` — but nothing calls it with real data yet. `app/routes/runs.py::paystub_pdf` calls `generate_paystub_pdf` with **no `ytd=` argument**, so today's paystub silently displays current-period-as-YTD (the honest "none" state the backlog itself calls out). **The actual accumulation query (sum prior `reconciled` runs) does not exist anywhere in `app/db/repo/`.**
- `eval/chart.svg` is already served as a **static committed file** (`app/routes/dashboard.py::GET /eval/chart.svg` reads `Path("eval/chart.svg")` off disk; matplotlib is imported only inside `eval/run_eval.py::_write_svg_chart`, never at request time) — so the serve-time-matplotlib risk is already avoided structurally; item 4 is pure restyle-and-regenerate-offline or replace-with-inline-HTML.

**Implication for the roadmap:** items 1–2 should be scoped as *regression-lockout + incremental polish* (if anything remains), not net-new builds — re-planning them as new builds risks a well-meaning "rewrite" that reintroduces the exact truncation/XSS/safety regressions this doc warns about. Item 3 (YTD accumulation) is genuinely new, money-adjacent code and is where most of the real risk in this milestone lives. Item 4 is genuinely new but low-risk (display only, no serve-time compute).

---

## Critical Pitfalls

### Pitfall 1: Reintroducing silent truncation while "improving" the conversation view

**What goes wrong:** A well-intentioned follow-up pass (e.g. "the page feels long, let's add an accordion per message") reintroduces a hard `body_text[:N]` cut, or an expand/collapse whose *collapsed* state renders truncated text with no visual signal that more exists — the exact bug the milestone was scoped to close.

**Why it happens:** Long email bodies make demo screenshots ugly, so the instinct is to shorten the DOM. `str[:300]` is one line and looks harmless; a collapsed `<details>` with the full text inside looks harmless too, but if anyone "optimizes" it to only inject the tail on expand (via a second fetch/JS swap), that reintroduces silent loss on network failure.

**How to avoid:** Any future collapse must keep the **full body in the initial server-rendered HTML** (already true today — `msg.body_text` is unconditionally in the DOM); CSS-only collapse (max-height + fade + a "show more" toggle) is safe because the full text is already present and just visually clipped, never network-fetched on demand. Never move body content behind a second request.

**Warning signs:** Any `[:N]` slice on `body_text`/`raw_email.body_text` in a template or route; any JS that fetches message content lazily; a collapse element without the text already present in the DOM (inspect via view-source, not just visually).

**Prevention test (regression lock, already exists, keep it green):** `tests/test_dashboard.py::test_run_detail_is_one_ordered_conversation_with_final_reply_composer` — extend with a `>300`-char fixture message and assert a distinctive post-300 suffix literal appears in the raw HTML response body (`response.text`), not just "the page renders 200". Any PR touching `run_detail.html`'s conversation block must keep this assertion green.

**Phase to address:** Any phase that touches `run_detail.html`'s conversation rendering (should be none new, per the scoping finding above — treat as a guard, not a build item).

---

### Pitfall 2: A new `|safe` or innerHTML path introduced by "just one" convenience feature

**What goes wrong:** Someone adds a "nicely formatted" email body (e.g. auto-linkify URLs, render `**bold**` markdown the client typed, or preserve line breaks via `<br>` injection) and reaches for `{{ msg.body_text | safe }}` or builds it via JS `innerHTML =` from the `/runs/{id}/status` JSON. Both bypass Jinja/DOM autoescaping on attacker-controllable text (a client's email body/subject is fully attacker-controlled input).

**Why it happens:** `<pre>` with autoescaped text already preserves whitespace/line breaks (this is *why* the current code uses `<pre>` — verified in `run_detail.html`), so there is no real need for `|safe` — but a future contributor who doesn't know that reaches for it to "fix" perceived formatting loss.

**How to avoid:** Explicit rule for this milestone: **zero new `|safe`, `|Markup`, `{% autoescape false %}`, or JS `innerHTML =` assignments of email-derived fields.** Today there are zero `|safe` uses in `app/templates/*.html` (verified by grep) — that count must stay zero. For the poll JS, all DOM writes already use `textContent` (`badge.textContent = data.badge_label`, etc.) — any new field the poll surfaces must follow the same rule, never `innerHTML`.

**Warning signs:** `git grep -n '| *safe\|Markup(\|autoescape false\|innerHTML' app/templates app/static` returning any hit; a PR diff touching `run_detail.html` or the poll script that adds an `innerHTML` assignment.

**Prevention test (CI guard, new):** Add a repo-wide grep-based test (mirrors the project's existing pattern of AST/regex CI guards, e.g. the `BackgroundTasks`-return guard from v4) asserting `app/templates/**/*.html` contains no `|safe`/`|Markup`/`autoescape false`, and `app/static/**/*.js` (or inline `<script>` blocks) contain no `.innerHTML =` assignment. Cheap, deterministic, catches the regression at PR time rather than at review.

**Phase to address:** Whichever phase touches templates/poll JS in this milestone — bake the guard test in alongside the YTD/eval-chart phase(s) even if no template changes are otherwise planned, since it's a standing regression lock worth having now.

---

### Pitfall 3: Breaking Phase-20 delivery-review safety while moving surrounding markup

**What goes wrong:** `run_detail.html`'s delivery-review card (`_load_delivery_review` → `_safe_delivery_review_projection` in `app/routes/runs.py`) is safety-critical: purpose-specific wording (`clarification` vs `confirmation` review kinds render different copy and different action sets), frozen-evidence links (`/runs/{id}/delivery-review/email`, `/delivery-review/attachments/{id}` — never a live re-fetch), a typed acknowledgement gate (`AUTHORIZE A NEW CONFIRMATION` exact-string match in `authorize_new_confirmation`), and **no auto-recovery** (every action requires an explicit POST from a rendered form, never triggered by the poll JS or a page load). A UI restructuring pass that moves this card's position, wraps it in a new collapsible, or merges its markup with the conversation timeline risks silently changing form `action` URLs, dropping the `acknowledgement` input's `required`/exact-label wiring, or letting the status poll's reload-on-change logic fire a GET that races an in-progress review action.

**Why it happens:** The card looks like "just another section" to move around when reorganizing the page for readability; the safety properties (frozen evidence, typed ack, purpose isolation) live in Python (`_load_delivery_review`, `_is_delivery_review_marker`) and are invisible from the template alone, so a template-only refactor feels safe but can drop an `action` attribute or reorder the DOM such that the ack `<input>` and its `<label for>` become mismatched.

**What the rework must preserve (enumerated from the live source, verified against `_DELIVERY_REVIEW_PURPOSES`, `_load_delivery_review`, and `app/routes/runs.py:940-1116`):**
1. Two distinct `review_kind`s (`clarification` vs `confirmation`) render **different action sets** — clarification never offers "authorize a new confirmation"; confirmation never offers "retry same question". Never merge the two branches into one generic template block.
2. Every action form's `action="/runs/{{ run.id }}/delivery-review/..."` route string must stay byte-identical (routes are matched by exact path in `app/routes/runs.py`); a URL typo during a template rewrite fails silently (POST returns 404, not caught by any UI test unless the test posts to the rendered form's actual `action` attribute).
3. `authorize_new_confirmation` requires `acknowledgement == "AUTHORIZE A NEW CONFIRMATION"` **exact string match** (`app/routes/runs.py:1054`) — the `<label for="new-confirmation-ack">` text and the `<input id="new-confirmation-ack" name="acknowledgement" required>` must both survive verbatim; changing the label copy without changing the check (or vice versa) creates a UX trap where the visible instructions no longer match the code's gate.
4. `email_url`/`attachments[].url` in `_safe_delivery_review_projection` point at the **frozen-evidence routes**, never a live re-render — a template change must not swap these for anything that re-composes content.
5. No form on this card may be wired to auto-submit from JS (the poll script only ever touches `run-status-badge`/`run-queue-badge`/`run-durability-note` by `id` — verify a UI rewrite doesn't accidentally give a delivery-review element one of those three ids, which would make the poll script silently mutate the wrong DOM node).
6. `_safe_run_for_browser` strips `error_reason`/`error_detail`/`last_error`/`payload`/`diagnostics`/`job_*` fields before the template ever sees the raw run dict (`app/routes/runs.py:236-248`) — any new template variable added for item 3/4 must be threaded through an equivalent safe-projection function, never `run` (or a raw provider payload) passed straight through.

**How to avoid:** Treat the delivery-review section as a black box during any reorganization — move the whole `{% if delivery_review %}...{% endif %}` block as one unit, never restructure its internals in the same change as the conversation/YTD/eval-chart work. If it must move, diff the rendered HTML's `action=`, `id=`, `for=`/`id` label pairs, and `required` attributes before/after.

**Prevention test:** Run the full existing `tests/test_phase20_clarification_review.py` suite (18 tests, all currently green) unmodified after any `run_detail.html` change — it already asserts frozen evidence, purpose isolation, no-auto-recovery, and the typed-ack gate. Add one new assertion if the page is reorganized: **order** — the delivery-review section still renders after the conversation section in the byte offset of the response (`text.index("delivery-review") > text.index("Conversation")`), matching the existing pattern already used for `Payroll details < Reply to client` ordering (`tests/test_dashboard.py:1005`).

**Phase to address:** Guard-only (no planned rework) — call out explicitly in the phase that touches `run_detail.html` for any reason (YTD/eval work should not need to, but if it does, this is the checklist).

---

### Pitfall 4: YTD "which runs count" ambiguity produces silently wrong accumulation

**What goes wrong:** The backlog says "sum each employee's prior `reconciled` runs per category... as of the current pay-period" but the schema has no explicit guardrails for this query, and several wrong-but-plausible implementations exist:
- Summing **all** `reconciled` runs regardless of `pay_period_start` — double-counts if a `reconciled` run's period is *after* the current one being displayed (e.g. viewing an older run's PDF after a later period was already processed and approved).
- Summing across **tax years** — `payroll_runs` has no `tax_year` column; only `pay_period_start`/`pay_period_end DATE` and `config.tax_year: int = 2026`. A YTD query with no year filter silently accumulates 2025 wages into a 2026 paystub the moment the demo data spans a year boundary.
- Joining on `submitted_name` instead of `employee_id` — `paystub_line_items.employee_id` is nullable (a resolved-then-later-removed roster employee, or a historical mismatch) and `submitted_name` is free text that can vary run to run (nickname vs full name) for the *same* employee; joining on the wrong key either misses prior runs or merges two different people's totals.

**Why it happens:** "Sum the prior runs" reads as a one-line `SUM(...) WHERE status='reconciled'` query; the year boundary and identity-join subtleties only surface once real multi-period demo data exists, by which point the PDF looks plausible and nobody re-derives it by hand.

**How to avoid — the concrete filter set (derived from the schema, not assumed):**
1. **Status filter:** `payroll_runs.status = 'reconciled'` only (matches the backlog's own wording — `approved`/`sent` runs haven't cleared the reconciliation check yet and could still error out).
2. **Identity filter:** join on `paystub_line_items.employee_id = <this employee's id>` (never `submitted_name`), and require `employee_id IS NOT NULL` on both sides.
3. **Scope filter:** `payroll_runs.business_id = <this run's business_id>` — an employee's YTD must never accumulate across businesses even if two demo businesses seed the same employee_id by coincidence (they won't today, but don't rely on that).
4. **Time filter, both parts:** `EXTRACT(YEAR FROM payroll_runs.pay_period_start) = EXTRACT(YEAR FROM <this run's pay_period_start>)` (derive the year from the run being displayed, not from `config.tax_year`, so a demo intentionally showing a prior year still self-consistently accumulates within that year) **AND** `payroll_runs.pay_period_start < <this run's pay_period_start>` (strictly prior periods only — never `<=`, which would double the current run if its own line item happens to already be persisted when the query runs, and never include periods *after* the one being viewed).
5. **Self-exclusion:** the above `<` on `pay_period_start` already excludes the current run by construction as long as no two runs for the same employee share the exact same `pay_period_start` — if the schema doesn't enforce that uniqueness, additionally exclude `payroll_runs.id != <this run's id>` explicitly rather than relying on date strictness alone.

**Prevention test:** A hermetic repo-level test seeding 3 `reconciled` runs for one employee across two tax years (2 in year Y, 1 in year Y-1) plus one `approved`-but-not-`reconciled` run and one run for a *different* employee/business with identical `pay_period_start` — assert the computed YTD sum includes exactly the 2 same-year `reconciled` runs' amounts and nothing else, for every category (gross, FIT, SS, Medicare, state, net). Table-driven, mirrors the project's existing Pub-15-T table-driven test discipline.

**Phase to address:** The phase implementing item 3 (paystub YTD) — this is the single highest-value test to write first (TDD: write the failing accumulation test against the filter set above before writing the query).

---

### Pitfall 5: Duplicate-submission double-counts YTD even though the filter set above is followed correctly

**What goes wrong:** The filters in Pitfall 4 are followed exactly, and YTD is still wrong: a client accidentally re-emails the same pay period as a **new** email (different RFC `Message-ID`, so webhook dedup — which dedupes on `message_id`, not on `(business, employee, pay_period)` — does not catch it), it becomes a second, independent `payroll_runs` row, gets approved and reaches `reconciled` like any other run, and now legitimately satisfies every filter in Pitfall 4 while being a real-world duplicate.

**Why it happens:** The system's dedup guarantee (`DATA-02`, verified in `v2`) is scoped to "one run per inbound Message-ID," which is the correct scope for *ingest* safety — it was never designed to prevent two distinct, legitimately-different emails from describing the same pay period. YTD accumulation is the first feature in the project that actually cares about pay-period uniqueness per employee, so this gap was invisible until now.

**How to avoid:** This is a **known, accepted limitation** to document rather than silently "fix" with new dedup machinery (which would be scope creep for a UI-polish mini-milestone and touches money-adjacent ingest logic the project has spent 4 milestones hardening). State it explicitly in the phase's scope notes: YTD accumulation trusts that each `reconciled` run for an employee represents a distinct pay period; it does not independently verify non-overlapping `pay_period_start`/`pay_period_end` ranges across runs. If two runs for the same employee share an overlapping period, YTD overcounts and nothing surfaces it. Do not silently paper over this with a same-employee-same-period `UNIQUE` constraint change inside this milestone (that's a `payroll_runs`-level, potentially money-behavior-adjacent decision, and the milestone is explicitly "no money behavior changed").

**Prevention test/guard:** No code guard is owed within this milestone's scope; instead, add one line to the phase's SUMMARY/PROJECT.md decision log stating the limitation (mirrors the project's existing pattern of documenting the pump's "best-effort, not guaranteed" honesty rather than overclaiming — see `PROJECT.md`'s "v4: Production-grade scheduling guarantees" entry). If a demo run happens to hit this, it's a known, disclosed gap, not a silent lie.

**Phase to address:** Same phase as item 3 — a documentation/scope-note deliverable, not a code deliverable.

---

### Pitfall 6: "One YTD number with the rest blank" reappears at the per-category level, not just per-paystub

**What goes wrong:** The backlog already flags the paystub-level version of this trap ("showing one YTD number with the rest blank looks half-built... all-or-none"). The same trap re-appears one level down: `_build_deductions_table` in `pdf.py` already **conditionally omits** the State Withholding and Pre-tax 401(k) rows when both current and YTD are zero (`if item.state_withholding or ytd.state_withholding:`). If the accumulation query is implemented for federal/SS/Medicare/gross/net but the caller forgets to also thread `state_withholding`/`pretax_401k` sums into `PaystubYtdTotals`, those two rows will show a **real** Current value next to a **wrong, silently-zero** YTD value (since `PaystubYtdTotals` defaults every field to `Decimal("0")`) — which is worse than omitting the row, because it looks like a deliberately reported "$0.00 YTD" rather than "not computed."

**Why it happens:** `PaystubYtdTotals` has 7 fields (`gross_pay, federal_withholding, fica_ss, fica_medicare, state_withholding, pretax_401k, net_pay`) and it's easy to write an accumulation query that covers the "big 3" (gross, FIT, net) first and ship it, treating state/401k as an afterthought since they're already optional/conditionally-rendered elsewhere in the codebase.

**How to avoid:** The accumulation query must produce **all 7** categories in one pass (a single `SUM(...)` per column over the same filtered row set from Pitfall 4 — cheap, one query, not 7), and `PaystubYtdTotals.from_prior`'s existing per-field `.get(key, _ZERO)` pattern should be replaced by passing the fully-populated repo result directly, not partially. Never call `generate_paystub_pdf(..., ytd=PaystubYtdTotals(gross_pay=X, federal_withholding=Y))` with some fields left at their dataclass default while others are computed — that's indistinguishable from "we checked and it's genuinely zero."

**Prevention test:** Assert on the constructed `PaystubYtdTotals` object (or the repo function's return dict) that when a prior run had non-zero `state_withholding`/`pretax_401k`, the resulting YTD total reflects it — not just that the Current-column value is right (existing tests likely already cover Current). Pair with the Pitfall 4 test's fixture (make at least one prior run include state withholding and a 401k contribution).

**Phase to address:** Same phase as item 3.

---

### Pitfall 7: SS-wage-base-capped current-period Medicare/SS math silently disagrees with a naive YTD sum

**What goes wrong:** `app/pipeline/calculate.py` already caps Social Security withholding per pay period against `employee.ytd_ss_wages` (`remaining_cap = _SS_WAGE_BASE - employee.ytd_ss_wages`) — i.e. the **calc engine** already has its own, separate notion of YTD SS wages, seeded from `employees.ytd_ss_wages` (a static seed value, not derived from `paystub_line_items`). If the new *display* YTD (summed from `paystub_line_items.fica_ss` across prior reconciled runs) and the *calc* YTD (`employees.ytd_ss_wages`, used to decide whether THIS period's SS should be capped) drift apart — which they will, structurally, since one is a live sum of runs and the other is a static seeded column never updated by any of the runs it's supposed to track — the paystub can display a YTD SS figure that doesn't match what the wage-base cap logic actually used to compute the Current period's SS withholding. This isn't a money bug (the cap logic is unchanged, out of scope) but it is a **credibility bug** for a "senior engineer, never-wrong" demo: an alert viewer doing the arithmetic (Current + prior YTD ?= displayed YTD) will find it doesn't reconcile with the cap math.

**Why it happens:** `employees.ytd_ss_wages` was built in v1/v2 purely as an input to the wage-base-cap calc, never as a display value, and nothing keeps it in sync with `paystub_line_items` — the two concepts were never designed to be shown side by side until this milestone.

**How to avoid:** Do not claim the displayed YTD SS wages and the calc engine's `ytd_ss_wages` are the same number without checking, in the phase's own README/footnote if needed, similar to the existing `additional_medicare_not_modeled` footnote pattern already in `pdf.py` (`"* Additional Medicare (0.9% over $200k) not modeled."`). If the demo seed data is internally consistent (seeded `ytd_ss_wages` matches the sum of seeded prior `reconciled` runs' `fica_ss`), this is invisible in the demo — but if `--check`/seed data changes later without updating both, it will silently diverge. Cheapest safe move: leave `employees.ytd_ss_wages` and the wage-base cap logic **completely untouched** (this milestone's own "no money behavior changed" constraint already forbids touching it) and treat the new accumulated `fica_ss` YTD as purely a **display total of already-computed per-run amounts** — which is honest regardless of whether it happens to match the seed column, because it's summing the actual numbers the client was actually charged, not re-deriving them.

**Prevention test:** A reconciliation-style test (mirrors the project's own "reconciliation check" pattern from `PITFALLS`-worthy money code): for the seed data used in any demo/UAT walkthrough, assert `employees.ytd_ss_wages ± tolerance == SUM(paystub_line_items.fica_ss / 0.062-derived-gross-portion...)` is **not required to hold** — instead assert the display code never reads `employees.ytd_ss_wages` at all (grep guard: the new repo function/route touching item 3 does not reference `ytd_ss_wages`). This keeps the two systems provably decoupled rather than accidentally-coincidentally-consistent.

**Phase to address:** Same phase as item 3 — call out as an explicit non-goal in the phase's scope note ("this phase does not reconcile display-YTD with the calc engine's wage-base-cap YTD; they are intentionally independent").

---

### Pitfall 8: Committing a `chart.svg` that drifts from the actual eval numbers

**What goes wrong:** `eval/chart.svg` is a **committed, hand-regenerated artifact** (confirmed: served statically by `app/routes/dashboard.py`, generated by `eval/run_eval.py --chart` as a local/CI dev-only step, not at request time). A restyle pass (palette swap, spine/gridline cleanup per the backlog's own instructions) requires re-running `--chart` and re-committing the SVG. If the restyle is done by hand-editing the SVG's colors/CSS directly (tempting — it's just XML) instead of regenerating from `run_eval.py`, the committed chart can silently diverge from whatever numbers `eval/run_eval.py` would currently produce — reintroducing exactly the class of bug v3 already found and fixed once ("the eval chart was misreporting exact-match extraction as failing at 0.96 when it never had — a mislabeled fixture").

**Why it happens:** Restyling by directly editing SVG markup is faster than reinstalling matplotlib deps and re-running the eval, especially if the dev environment's matplotlib (a dev-only dependency, per the project's own "Development / Reference Libraries" stack note) isn't currently installed.

**How to avoid:** Any palette/style change must go through `eval/run_eval.py`'s `_write_svg_chart` (matplotlib rcParams / colors), regenerated via `uv run python eval/run_eval.py --chart` (or equivalent), never hand-edited SVG markup. If choosing option (b) instead — inline HTML/CSS bar chart in `eval.html`, avoiding the SVG file and matplotlib entirely — the chart's bar heights/labels must be computed from the **same** `eval/run_eval.py` scoring functions' output (or a small JSON the eval script emits) rather than hardcoded percentages in the template, for the identical reason: hardcoded numbers drift the moment fixtures change and nothing re-validates them.

**Prevention test:** The project already has `eval/run_eval.py --check` as a DB-free regression gate wired into `eval.yml` CI. If choosing option (b) (inline HTML/CSS chart), extend that gate (or a new one) to assert the numbers rendered in `eval.html`'s inline chart match `--check`'s scored output — e.g. a template-rendering test that feeds the same fixture-derived metrics dict into `eval.html` and asserts the bar-width/label values equal the scored percentages, so the chart can never independently drift from the scorer the way the pre-v3 SVG did.

**Phase to address:** The eval-chart-restyle phase — whichever option is chosen, wire the regeneration/consistency check into the same phase, not as a follow-up.

---

### Pitfall 9: Reviving matplotlib as a request-time cost by "simplifying" the serving path

**What goes wrong:** Not currently a risk (verified: `GET /eval/chart.svg` in `app/routes/dashboard.py` reads the committed file off disk; `matplotlib` is imported only inside `_write_svg_chart`, gated behind `--chart`), but a plausible regression during this milestone: someone "simplifies" the eval page by making `/eval/chart.svg` regenerate on the fly (e.g. to avoid the two-step "run eval, commit svg, deploy" workflow) — which reintroduces exactly the serve-time matplotlib import + render cost the project's own STACK.md explicitly steered away from for Render free cold starts (slim image, no heavy native deps, fast cold start).

**Why it happens:** Regenerating at request time feels more "correct" (always fresh) than a committed artifact that can go stale (see Pitfall 8) — the instinct to fix staleness by making it dynamic is natural but wrong for this platform.

**How to avoid:** Keep the two-step workflow (regenerate offline/in CI, commit, serve statically) as the fix for Pitfall 8 (drift) rather than reaching for on-demand regeneration to fix it. If choosing inline HTML/CSS (option b) instead of SVG, this pitfall disappears structurally — one more reason (b) is the lower-risk option for a Render-free-constrained project, though (a) restyle-in-place is fine as long as the static-serve path is untouched.

**Prevention test/guard:** A guard test asserting `app/routes/dashboard.py` (or wherever `/eval/chart.svg` is served from after any refactor) contains no `import matplotlib` / no call into `eval.run_eval` at module or request-handler level — mirrors the project's existing pattern of AST/import guards for architectural invariants (e.g. the `BackgroundTasks`-return guard, the CAS-only `jobs` guard). Cheap and durable against future "helpful" refactors.

**Phase to address:** The eval-chart-restyle phase, as a standing guard regardless of which restyle option is chosen.

---

### Pitfall 10: Poll JS edge cases if any further work touches `run_detail.html`'s script

**What goes wrong (already-mitigated, but the reasoning needs to survive any future edit):** The existing poll script already handles the three classic progressive-enhancement traps correctly — verify any future change doesn't undo them: (a) it stops polling on terminal status (`MAX_ATTEMPTS = 60` hard cap **and** an `if (!POLL_WHILE.has(data.status) && !data.has_open_job) { clearInterval(timer); }` early exit), so it does not poll forever and does not artificially keep the Render-free dyno "busy" past the point where the underlying work is done; (b) it does **not** reset in-progress form state on every tick — it only swaps `textContent` on three specific `id`-targeted elements (`run-status-badge`, `run-queue-badge`, `run-durability-note`) and does a **full page reload only once**, gated on `data.status !== INITIAL_STATUS || data.queue_label !== INITIAL_QUEUE_LABEL` (a real content-invalidating transition), not on every poll tick — so a partially-filled `resolve` form or the reply-composer textarea is never silently wiped by a background tick; (c) polling itself is *client-initiated inbound HTTP*, which is exactly what the project's own Render-free architecture already depends on to stay awake during an active operator session — it does not fight the "only inbound HTTP wakes the dyno" constraint, it exploits it correctly (the dyno would need to be awake for the operator's browser tab to be open anyway).

**Why it's worth stating even though it's already correct:** A future contributor extending the poll to surface a new field (e.g. YTD-in-progress state, if that were ever async) could easily reintroduce (b) by doing a blanket `document.body.innerHTML` swap or an unconditional reload-every-tick "to keep it simple" — undoing the exact fix this script represents.

**How to avoid:** Any new field the poll surfaces must follow the existing pattern exactly: target a specific `id` by `textContent`, never reload except on the existing `INITIAL_STATUS`/`INITIAL_QUEUE_LABEL` divergence check, never add a new unconditional-reload branch.

**Prevention test (already exists, keep green):** `test_run_detail_inflight_poll_reloads_on_settle`, `test_run_detail_poll_reloads_on_status_change_not_just_settle`, `test_run_detail_has_no_meta_refresh`. If the poll's JSON payload grows (e.g. to carry a YTD-computation-pending flag), add one assertion that a form's textarea `value` attribute (or a distinguishing marker) still round-trips through a simulated poll tick unchanged — proving state isn't wiped.

**Phase to address:** Guard-only — no new poll-JS work is currently scoped, but flag this for whichever phase (if any) extends `/runs/{id}/status`'s JSON shape.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|-----------------|------------------|
| Hand-editing `eval/chart.svg` colors instead of regenerating via `run_eval.py --chart` | Faster, no matplotlib install needed | Silent drift from real eval numbers (the exact v3 bug class) | Never |
| Skipping the tax-year/prior-period filter set (Pitfall 4) and just `SUM(...) WHERE status='reconciled' AND employee_id=X` | One-line query, ships fast | Silently wrong YTD across year boundaries or future-dated runs | Never — write the filtered query from the start; it's not more code, just more `WHERE` clauses |
| Leaving `PaystubYtdTotals` partially populated (state/401k left at default `Decimal("0")`) while gross/FIT/SS/Medicare/net are wired | Ships the "headline" categories first | Indistinguishable from "genuinely $0 YTD" — a worse UX than the current honest all-zero state | Never — compute all 7 categories in the same query or don't ship YTD yet |
| Reworking the delivery-review card's internal markup "while we're in the file anyway" for item 1/2 polish | Feels efficient (one PR) | Highest-risk touch in the whole milestone (Pitfall 3); reviewers must re-verify 18 Phase-20 safety properties | Never in this milestone — treat it as a black box |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|-----------------|-------------------|
| `paystub_line_items` ↔ `payroll_runs` for YTD | Joining/filtering by `submitted_name` (free text, varies by run) | Join on `employee_id`, require non-null on both sides (Pitfall 4) |
| `employees.ytd_ss_wages` (calc-engine YTD) vs new display YTD (Pitfall 7) | Treating them as the same number / trying to reconcile them | Keep them structurally independent; document the non-goal explicitly |
| `eval/run_eval.py --chart` (matplotlib, dev-only dep) ↔ served `/eval/chart.svg` | Wiring chart generation into the request path "to always be fresh" | Keep the offline-generate/commit/static-serve split (Pitfall 9) |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|-----------------|
| Serve-time matplotlib import (Pitfall 9) | Slower Render free cold start on `/eval/chart.svg`, fatter image if matplotlib becomes a runtime dep | Keep matplotlib a dev-only dependency, chart served statically | Immediately on the first cold start after the regression lands — not a "at scale" trap, a correctness-of-architecture trap |
| N+1 YTD query per employee on a run with many employees | Paystub PDF route (`GET /runs/{run_id}/pdf/{employee_id}`) already generates one PDF per employee per request, so this is naturally bounded — but a run-detail page that eagerly computes YTD for *every* employee on the run (not just the one being downloaded) could issue one query per employee | Compute YTD lazily, only for the employee whose PDF is being generated (matches the existing route's per-employee scope) — do not pre-compute YTD for the whole roster on `run_detail` page load | At demo scale (a handful of employees) this is invisible either way; still worth doing the cheap-correct thing from the start since the query pattern from Pitfall 4/6 is one `SUM(...) GROUP BY category` per employee, trivially cheap on Supabase free tier |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| New `|safe`/`innerHTML` path for "nicer" email formatting (Pitfall 2) | Stored XSS via client-controlled email body/subject rendered on an internal operator dashboard with no auth (per PROJECT.md: "Auth on the dashboard — it's a demo") — an attacker-controlled payroll email could execute JS in the operator's session | Zero new `|safe`/`innerHTML`; CI grep guard (Pitfall 2) |
| Delivery-review card exposing a raw provider field during restyle (Pitfall 3, item 5 of the enumerated list) | Violates the milestone's own locked constraint ("no provider diagnostics on page"); could leak Resend-internal error codes/ids to whoever views the (unauthenticated) dashboard | Route all new template variables through a safe-projection function (`_safe_run_for_browser`-equivalent), never pass `run` or a raw provider payload straight through |
| Poll JS surfacing a new raw field without going through `_safe_run_with_queue_projection` | Same diagnostic-leak risk as above, reachable via the unauthenticated `GET /runs/{id}/status` JSON endpoint (no auth, per project constraints) | Any new field added to the `/status` JSON must be added to the safe projection function, not read ad hoc off the raw `run` dict in the route handler |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-------------------|
| Paystub shows a YTD column with 2 of 7 categories silently zeroed (Pitfall 6) | A hiring-manager viewer who checks the arithmetic finds it doesn't add up — undermines the "never-wrong" narrative this whole project is built on | Compute all 7 categories together or ship none (all-or-none, per the backlog's own instinct, applied one level deeper than the backlog stated it) |
| Chart restyle changes the visual encoding (e.g. swaps a stacked bar for a grouped bar) without re-validating the confusion-matrix story still reads correctly | The chart's *purpose* — "the proof, not the demo" per PROJECT.md — gets diluted by a purely aesthetic change that accidentally changes what's easy to compare | Restyle color/spine/gridline/font only; keep the chart *type* and data mapping unchanged unless that's an explicit, separately-reviewed decision |

## "Looks Done But Isn't" Checklist

- [ ] **Chronological conversation (item 1):** Verify it isn't re-planned as new work — it's already shipped; the checklist item here is "did the PR touch it at all, and if so did `test_phase20_clarification_review.py` + the >300-char regression test both stay green."
- [ ] **Progressive-enhancement poll (item 2):** Same — verify no new poll-JS work reintroduces a full-reload-every-tick or an `innerHTML` write.
- [ ] **Paystub YTD (item 3):** "The PDF shows a YTD column" is not the finish line — verify (a) all 7 categories are populated together (Pitfall 6), (b) the year/status/identity filter set is exact (Pitfall 4), (c) the `employees.ytd_ss_wages` calc-engine value is never read by the new code (Pitfall 7), (d) a table-driven accumulation test exists before the query is trusted.
- [ ] **Eval chart restyle (item 4):** "The chart looks better" is not the finish line — verify the committed SVG (or inline chart's numbers) were regenerated from `eval/run_eval.py`'s actual scoring output, not hand-tuned, and that `/eval/chart.svg` (or its replacement) still serves with zero request-time matplotlib import.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|----------------|-----------------|
| Silent truncation reintroduced (Pitfall 1) | LOW | Revert the offending slice/lazy-fetch; the regression test (extended per Pitfall 1) will have caught it in CI before merge if wired in |
| New `|safe`/XSS path (Pitfall 2) | LOW–MEDIUM | Revert the template change; audit whether any real email content was rendered unescaped in the interim (check logs/DB, not just fix forward) |
| Phase-20 safety property broken (Pitfall 3) | MEDIUM–HIGH | Revert the `run_detail.html` change wholesale rather than attempting a targeted patch; re-run the full 18-test `test_phase20_clarification_review.py` suite plus a manual walkthrough of both `review_kind` branches before re-attempting |
| YTD accumulation wrong (Pitfalls 4–7) | LOW (display-only, per the milestone's "no money behavior changed" framing — the underlying `paystub_line_items`/calc data is untouched) | Fix the query/filter set, re-run the table-driven accumulation test; no data migration needed since nothing was persisted incorrectly, only displayed incorrectly |
| Chart drift or serve-time matplotlib (Pitfalls 8–9) | LOW | Regenerate `chart.svg` from `run_eval.py --chart` and re-commit, or revert the dynamic-serving change |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-------------------|----------------|
| 1. Silent truncation regression | Guard only (no new build) — bundle into whichever phase touches `run_detail.html` | Extended `test_run_detail_is_one_ordered_conversation_with_final_reply_composer` with >300-char fixture assertion stays green |
| 2. New `|safe`/innerHTML XSS path | New CI guard, land alongside the YTD or eval-chart phase | `git grep` guard test for `|safe`/`Markup(`/`autoescape false`/`.innerHTML =` returns zero hits |
| 3. Phase-20 safety broken during restructuring | Guard only — explicit checklist for any phase touching `run_detail.html` | Full `test_phase20_clarification_review.py` green + section-ordering assertion |
| 4. YTD "which runs count" ambiguity | Item 3's phase | Table-driven accumulation test with the exact filter set (status/identity/scope/time) from Pitfall 4 |
| 5. Duplicate-submission double-count | Item 3's phase (documentation only) | Explicit limitation note in the phase's decision log / PROJECT.md |
| 6. Partial-category YTD ("half-built" one level deeper) | Item 3's phase | Test asserting all 7 `PaystubYtdTotals` fields populated together, including state/401k |
| 7. Display-YTD vs calc-engine-YTD drift | Item 3's phase | Grep guard: new YTD code never reads `employees.ytd_ss_wages`; explicit non-goal note |
| 8. Committed SVG drifts from real eval numbers | Item 4's phase | `--check` (or extended) gate ties displayed numbers to the scorer's actual output |
| 9. Serve-time matplotlib reintroduced | Item 4's phase | Import guard: no `matplotlib`/`eval.run_eval` reference in the request-serving path |
| 10. Poll JS state-reset/infinite-poll regression | Guard only — flag for any phase extending `/runs/{id}/status`'s JSON shape | Existing poll-reload/no-meta-refresh tests stay green; new field follows `textContent`-only pattern |

## Sources

- Direct read of live source, 2026-07-20: `app/templates/run_detail.html`, `app/routes/runs.py`, `app/pipeline/pdf.py`, `app/db/schema.sql`, `app/routes/templating.py`, `app/routes/dashboard.py`, `app/pipeline/calculate.py`, `app/config.py`, `app/db/repo/emails.py`, `app/db/repo/pipeline_state.py`. **HIGH** confidence — these are the exact files this milestone will touch.
- `tests/test_dashboard.py`, `tests/test_phase20_clarification_review.py` — existing regression-lock test names and assertion patterns cited verbatim. **HIGH.**
- `.planning/PROJECT.md` — locked constraints (Jinja2 + vanilla JS, no SPA, no provider diagnostics, no money behavior changes), Phase 20/21 requirement summaries, prior pitfall precedent (v3's mislabeled-fixture eval chart bug, cited as the direct precedent for Pitfall 8). **HIGH.**
- `.planning/backlog.md` → "Next milestone (mini)" section — the four target items' original scope language, quoted and extended. **HIGH.**
- `eval/run_eval.py` — confirmed matplotlib is imported only inside `_write_svg_chart`, gated behind `--chart`, never at module load or request time. **HIGH.**

---
*Pitfalls research for: v4.1 Demo Polish & Run-Detail UI (mini milestone)*
*Researched: 2026-07-20*
