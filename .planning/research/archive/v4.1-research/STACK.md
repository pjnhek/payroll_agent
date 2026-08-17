# Stack Research

**Domain:** Server-rendered Jinja2 dashboard polish (mini UI milestone, no new domain)
**Researched:** 2026-07-20
**Confidence:** HIGH — every finding below is verified directly against the live repo (file:line), not
assumed from the backlog description. The backlog's per-item scope was written 2026-07-20 at v4 close and
is **already stale**: three of the four items are fully shipped in `master`, and the fourth is ~90% shipped.
This file corrects the scope before `/gsd-new-milestone` writes requirements against it.

## Headline finding — re-verify scope before planning

`git log` + direct file reads show **items #1, #2, and #4 are already fully implemented and merged**, and
**item #3 is implemented everywhere except one call site**. None of this is v4.1 work in progress — it
landed earlier, mostly under Phase 20 (`20-07`, `20-08`) and one untracked `feat(dashboard): make run
detail email-first` commit (`91bc6ca`, 2026-07-18) that predates the backlog's "was quick-task 260718-hie,
previously untracked" note. The backlog text describing these as open work was written from a stale
snapshot. **Recommendation to the roadmap:** scope v4.1 down to the one real gap (the PDF-download YTD
wiring) plus a verification/regression-lock phase for the other three, rather than planning four full
build phases.

| # | Item | Actual current state | Real remaining work |
|---|------|----------------------|----------------------|
| 1 | Run-detail → chronological conversation | **DONE.** `app/templates/run_detail.html` (commit `91bc6ca`) | None found. Optionally: nothing — see (a) below. |
| 2 | Frontend progressive enhancement (status poll) | **DONE.** `GET /runs/{run_id}/status` (`app/routes/runs.py:844`) + vanilla-JS poll in both templates. Zero `<meta http-equiv="refresh">` anywhere in `app/` (grep-verified). | None found. |
| 3 | Paystub YTD columns | **~90% DONE.** Query, dataclass, PDF layout, and the *emailed* confirmation PDF are all wired (`app/db/repo/demo.py:144` `load_prior_reconciled_paystub_totals`, `app/pipeline/delivery.py:115-136`). | Wire the same call into the **on-demand download route** `app/routes/runs.py:1233` `paystub_pdf()` — it currently omits `ytd=`, so "Download PDF" ≠ what was emailed. See (c) below. |
| 4 | Eval chart restyle | **DONE.** `eval/run_eval.py` `CHART_PALETTE`/`CHART_STYLE` (commit `1159b6a`) already match the dashboard's `#1E3A5F`/`#6B7280`, spines/junk removed, sans-serif. Committed `eval/chart.svg` (2026-07-17) reflects it. Zero serve-time matplotlib (confirmed: import is local to `_write_svg_chart`, matplotlib is `[dependency-groups].dev`-only, never installed in the `--no-dev` Docker image). | None found. |

---

## (a) Accessible expand/collapse for long email bodies + "Payroll details"

**Current state: DONE, using the simpler of the two acceptable options.**

- `app/templates/run_detail.html:227` renders `msg.body_text` in full inside `<pre class="conversation-message__body">` — no truncation, no length cap, no `truncate()` filter. `app/static/style.css:880-891` confirms no `max-height`/`overflow:hidden` is applied to that class — the full body is always in the DOM and visible.
- The 300-char hazard is closed by test: `tests/test_dashboard.py:926` `test_run_detail_is_one_ordered_conversation_with_final_reply_composer` builds a 301+-char inbound body with a distinctive suffix and asserts `long_suffix in text` (line ~995) — a real regression lock, not just a manual check.
- The "Payroll details" section already uses the **native disclosure widget**: `<details class="payroll-details mt-xl"><summary>...` (`run_detail.html:272`), styled in `style.css:914-966` (custom marker, `[open]` state). This is the correct zero-JS choice — `<details>`/`<summary>` is natively keyboard-focusable (Tab), natively toggles on Enter/Space, and is recognized by screen readers as a disclosure widget with the summary as its accessible name ([MDN `<details>`](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/details), [MDN `<summary>`](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/summary)). No ARIA attributes, no JS, and no dependency are needed for this pattern — that is the entire point of the element.

**If a future pass wants a true per-message collapse** (e.g. one truly enormous pasted email dominating the page), the same native pattern is the right tool — wrap `conversation-message__body` in its own `<details>` instead of a full-body `<pre>`, with `<summary>Show full message ({{ msg.body_text | length }} chars)</summary>`. **Do not** build a custom ARIA `aria-expanded`/`aria-controls` JS toggle — that duplicates behavior the browser gives for free and is the exact kind of hand-rolled accessibility surface that regresses silently. Zero new dependency either way.

**Confirmed no new dependency.**

## (b) Chronological email thread (inbound/outbound) in Jinja2 + CSS

**Current state: DONE.**

- Single source of truth: `run_detail.html:210` iterates `thread_messages` (ascending `created_at`) — the route (`app/routes/runs.py`, `GET /runs/{run_id}`) dropped the old `load_outbound_emails` three-column load entirely (test asserts it's never called: `tests/test_dashboard.py:978-979` `pytest.fail("run detail must use thread_messages only")` if it is).
- Direction distinction is pure CSS, not JS: `.conversation-message--inbound` / `--outbound` (`style.css:825-831`) apply a colored left border (`#94A3B8` slate for inbound, `var(--accent)` indigo for outbound) plus a `badge-neutral`/`badge-pending` badge (`run_detail.html:214`). This is the standard "chat-bubble-by-CSS-class" technique — one Jinja `{% for %}` loop, a `msg.direction`-driven class suffix, and BEM-style modifier CSS. No framework needed for this at 4 static pages.
- Fallback path (`raw_email` when `thread_messages` is empty) reuses the identical markup so there is only one visual template to maintain.

**Confirmed no new dependency** — plain Jinja2 loop + CSS class modifiers, already shipped.

## (c) reportlab two-column Current | YTD table — slot into the existing stub

**Current state: layout is DONE and reusable; one caller still needs wiring.**

`app/pipeline/pdf.py` already has the exact non-rewrite shape the backlog asked for:
- `PaystubYtdTotals` (frozen dataclass, `pdf.py:112-143`) with `.from_prior(prior: Mapping[str, Decimal] | None, item: PaystubLineItem)` — combines a prior-totals mapping with the current period's `PaystubLineItem`, defaulting every field to `Decimal("0")` when `prior` is `None`. This is the "slots in without a rewrite" seam: every table builder (`_build_earnings_table`, `_build_deductions_table`, `_build_net_pay_band`) already takes `ytd: PaystubYtdTotals` as a required positional and renders a `Current | YTD` column pair (`pdf.py:292-294`, `393`, `504-523`).
- `generate_paystub_pdf(..., ytd: PaystubYtdTotals | None = None)` (`pdf.py:549-559`) is backward-compatible by construction: omitting `ytd` falls back to `PaystubYtdTotals.from_prior(None, item)` — an honest current-period-as-YTD display, not a crash or a blank column (`pdf.py:600`).
- **The real DB accumulation query already exists**: `app/db/repo/demo.py:144` `load_prior_reconciled_paystub_totals(business_id, employee_ids, pay_period_start, conn=None) -> dict[UUID, dict[str, Decimal]]`. It sums `paystub_line_items` joined to `payroll_runs` **filtered to `historical.status = 'reconciled'`**, scoped to the calendar year (`date_trunc('year', pay_period_start)` through the day before the current period start) — exactly the "sum prior reconciled runs per category, calendar-year scope" the backlog specified. `COALESCE(SUM(...), 0)` on every column means a first-ever run for an employee returns an empty dict (not a crash), and the caller's `PaystubYtdTotals.from_prior(prior_ytd.get(employee_id), item)` handles the missing-key case identically.
- **Already wired end-to-end for the emailed confirmation PDF**: `app/pipeline/delivery.py:115-136` calls `load_prior_reconciled_paystub_totals` once per run (not per employee — batched by `employee_ids` list, avoiding an N+1), then threads `ytd=PaystubYtdTotals.from_prior(...)` into `generate_paystub_pdf` per attachment.
- **The one gap**: `app/routes/runs.py:1233` `paystub_pdf()` (the `GET /runs/{run_id}/pdf/{employee_id}` on-demand download link the operator clicks from "Payroll details") calls `generate_paystub_pdf` **without** `ytd=` — confirmed by direct read (`runs.py:1253-1261`), so that download shows current-period-as-YTD while the emailed copy for the same run shows real accumulated YTD. This is a real, narrow, well-scoped fix: call `repo.load_prior_reconciled_paystub_totals(run["business_id"], [employee_id], run.get("pay_period_start"))` and pass `ytd=PaystubYtdTotals.from_prior(prior.get(employee_id), item)` the same way `delivery.py` does. No new query, no new dataclass, no schema change — just parity between the two existing call sites.
- **Optional, not required by backlog**: the HTML "Payroll details" `<details>` section in `run_detail.html:287-292` still renders current-period-only figures (no YTD column) — the backlog only asked for the *PDF* to gain Current | YTD, so leaving the HTML table as-is is in-scope-complete. If the roadmap wants dashboard/PDF parity too, the same `load_prior_reconciled_paystub_totals` call plugged into the run-detail route context would drive it — same zero-new-dependency technique, just an additional call site.

**Confirmed no new dependency** — pure SQL (already-used `psycopg`) + a dataclass + existing `reportlab` `Table`/`TableStyle` primitives already in the file.

## (d) On-brand chart: matplotlib SVG restyle (chosen) vs inline HTML/CSS bar chart

**Current state: DONE, option (a) — restyled matplotlib SVG, committed statically.**

`eval/run_eval.py` already implements the "restyle, not replace" path:
- `CHART_PALETTE` (`run_eval.py:146-155`) and `CHART_STYLE` (`157-170`) are dashboard-token-driven: `primary=#1E3A5F`, `secondary=#6B7280` — byte-identical to `app/static/style.css`'s `--text-muted: #6B7280` and the navy used across `pdf.py`'s `_C_NAVY`. One shared vocabulary across paystub PDF, dashboard CSS, and eval chart — not three separate palettes to keep in sync by hand.
- Junk removal is applied per-axis (`run_eval.py:916-923`): `axis.spines["top"].set_visible(False)`, `spines["right"].set_visible(False)`, remaining spines recolored to the border token, gridlines restricted to `axis="x"` only at `border` color/0.8pt — the standard "remove chartjunk" moves (top/right spine removal, muted gridlines, no default matplotlib gray).
- Font stack is forced sans-serif (`"font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"]`) rather than matplotlib's default serif-adjacent look, and `svg.fonttype: "none"` keeps the SVG text as real `<text>` (selectable/searchable, not path-outlined glyphs) — worth calling out because that flag is what makes the SVG accessible/copyable in a browser rather than a rasterized-looking blob.
- **Zero serve-time cost, verified two ways**: (1) `matplotlib`/`numpy` live only in `pyproject.toml`'s `[dependency-groups].dev` (`pyproject.toml:23-30`) which `uv sync --no-dev` (the Docker build command per `CLAUDE.md`) never installs — matplotlib is not in the running container at all; (2) even in dev, `import matplotlib` is local to `_write_svg_chart()` (`run_eval.py:899-902`), explicitly walled off from the module top level so `--check`/scoring stays matplotlib-free, and the app itself never imports `eval/run_eval.py`. `app/routes/dashboard.py`'s `GET /eval/chart.svg` (`dashboard.py:160-170`) just streams the committed `eval/chart.svg` file bytes off disk (`Path("eval/chart.svg")`, 404 if absent) — no generation on request.

**Why this option over inline HTML/CSS bars (option b), for the record:** the eval chart's subplot 3 is a 2×2 confusion-matrix *table* with a highlighted danger cell (`run_eval.py:1023-1066`), not just bar magnitudes — reproducing a highlighted-cell table + two grouped-bar subplots in hand-rolled CSS would be more code than the already-working, already-on-brand matplotlib path, for zero runtime benefit (both are static/serve-time-free once generated). If a future pass ever wants literal zero-matplotlib-anywhere (not even in `--chart` dev mode), option (b) is still available and equally zero-new-dependency (`<div>` bars sized via inline `style="width: {{ pct }}%"`, already the technique this codebase uses nowhere else but would fit the no-build-step constraint identically) — but there is no constraint forcing that trade today.

**Confirmed no new dependency**, and confirmed the runtime/cold-start cost this milestone's constraints worried about does not exist (dev-only, request-path-free).

---

## Recommended Stack

### Core Technologies (all already in the project — nothing new to add)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Native `<details>`/`<summary>` | HTML5 (browser built-in) | Collapsed "Payroll details" section | Zero-JS, natively keyboard-operable (Tab, Enter/Space), native screen-reader disclosure semantics — see (a). Already shipped. |
| Jinja2 loop + CSS BEM modifiers | `jinja2==3.1.6` (already pinned) | Chronological inbound/outbound thread rendering | One `{% for msg in thread_messages %}` + `conversation-message--{{ msg.direction }}` class suffix is the entire pattern — no JS needed for direction styling. Already shipped. |
| `reportlab` Table/TableStyle | `reportlab==5.0.0` (already pinned) | Current \| YTD paystub columns | Already-used primitives; `PaystubYtdTotals` + the two already-built column layouts are the reusable seam — see (c). |
| `psycopg` (existing pool) | `psycopg[binary,pool]==3.3.4` (already pinned) | YTD accumulation query | `load_prior_reconciled_paystub_totals` is one parameterized `SUM(...) ... WHERE status='reconciled'` query against the existing pool — no ORM, no new query layer. |
| `matplotlib` (dev-only) + `numpy` (dev-only) | `matplotlib>=3.11.0`, `numpy>=1.26.0` (already dev-group pinned) | Static `eval/chart.svg` generation, offline | Never enters the runtime image (`--no-dev`); import is function-local so even the DB-free `--check` scoring path never touches it. Already shipped and committed. |
| Vanilla JS `fetch()` poll (~40 lines, no framework) | Browser built-in | `/runs/{id}/status` badge swap | Already shipped in both `run_detail.html` and `runs_list.html`; replaces the old `<meta refresh>` entirely (grep-confirmed zero remaining meta-refresh in `app/`). |

### Supporting Libraries

None needed. Every technique in this milestone's four target items is achievable — and already achieved, in three of four cases — with primitives already in `pyproject.toml`. No `uv add` is required for any of items #1, #2, #3, or #4.

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `matplotlib` / `numpy` (dev group) | Regenerate `eval/chart.svg` locally via `uv run python eval/run_eval.py --chart` | Only invoked manually/offline; not part of any CI workflow step (`eval.yml` has no chart step) — the committed SVG is the artifact of record. |

## Installation

No installation needed — zero new runtime or dev dependencies for any of the four target items. If the roadmap adds the one real gap (item #3's download-route wiring), it is a code change to two existing files (`app/routes/runs.py`, possibly none to `pdf.py` since the signature already accepts `ytd=`), not a dependency change.

```bash
# Nothing to add. Confirm the existing env is current:
uv sync
```

## Alternatives Considered

| Recommended (already shipped) | Alternative | When the alternative would win |
|-------------------------------|-------------|----------------------------------|
| Native `<details>`/`<summary>` for collapsed sections | Hand-rolled `aria-expanded` + JS toggle | Only if collapse state needed to persist across page loads (localStorage) or animate height — neither is a stated requirement here; `<details>` has no built-in open/close transition, but nothing in the UI-SPEC/backlog asks for one. |
| CSS class modifier (`--inbound`/`--outbound`) for thread direction | A JS-driven chat-bubble library (e.g. a Slack-style component) | Never, at 4 static pages with no build step — that's exactly the SPA-creep this project's constraints forbid. |
| Restyled matplotlib SVG, statically committed | Inline HTML/CSS bar chart (`eval.html`) | If the eval chart ever needs to be interactive (hover tooltips, live-filterable fixtures) — a static SVG can't do that without JS. Not a current requirement; see (d) for the 2×2-table complexity argument too. |
| `load_prior_reconciled_paystub_totals` (one batched SQL query) | Per-employee N+1 queries in a loop | Never — the existing implementation already batches via `employee_ids = ANY(%s::uuid[])`, avoiding the N+1 a naive per-employee call would introduce. |

## What NOT to Use

| Avoid | Why (specific to this project) | Use Instead |
|-------|--------------------------------|--------------|
| Any JS accordion/collapse library (Bootstrap Collapse, a11y-dialog, etc.) | Locked constraint: no bundler, no SPA, no build step; a library import for something `<details>` already does natively is pure overhead and the exact anti-pattern the milestone's constraints call out. | Native `<details>`/`<summary>` (already shipped). |
| Serve-time matplotlib import (module-level `import matplotlib` in any file reachable from `app/main.py`) | Cold-start cost on Render free is the whole reason this stack avoids WeasyPrint elsewhere; the same logic applies to matplotlib. Already correctly avoided — `import matplotlib` is function-local in `eval/run_eval.py` only, a dev-tool file the running app never imports. | Static committed `eval/chart.svg` served as a file (already shipped, `dashboard.py:160`). |
| Re-deriving YTD by re-querying/re-summing inside `pdf.py` itself | `pdf.py` is documented as a PURE function (data in, PDF bytes out — no DB, no connection). Adding a DB call there would break that boundary and duplicate the query that already exists in `app/db/repo/demo.py`. | Call `repo.load_prior_reconciled_paystub_totals` at the route/pipeline layer (as `delivery.py` already does) and pass the result in via the existing `ytd=` parameter. |
| Building a second, HTML-table-specific YTD query for the "Payroll details" section (if that's added later) | Would duplicate `load_prior_reconciled_paystub_totals`'s exact semantics (reconciled-only, calendar-year-scoped) in a second place, risking drift. | Reuse the same repo function; it already returns a plain `dict[UUID, dict[str, Decimal]]` that a Jinja context can consume directly. |

## Stack Patterns by Variant

**If the roadmap decides item #3's HTML "Payroll details" table should also show YTD (optional, not backlog-required):**
- Reuse `load_prior_reconciled_paystub_totals` from the run-detail route (`app/routes/runs.py`, the `GET /runs/{run_id}` handler), passing it into the template context alongside `paystubs`.
- In `run_detail.html`'s `<section><p class="column-label">Computed paystubs</p>` block (`run_detail.html:287-292`), add a second `<td>` per row sourced from that dict — same zero-dependency technique as (c), just a second consumer of the existing query.

**If the roadmap wants item #1's per-message collapse for exceptionally long individual emails (optional, not backlog-required):**
- Wrap `conversation-message__body` in a nested `<details>` per message, per the note under (a) — still zero JS, zero new dependency.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `reportlab==5.0.0` | `PaystubYtdTotals` (plain stdlib `dataclass` + `Decimal`) | No version coupling — `PaystubYtdTotals` is pure Python, already in `pdf.py`, no reportlab-specific typing dependency beyond the `Table`/`TableStyle` calls already used throughout the file. |
| `matplotlib>=3.11.0` (dev) | `python:3.12-slim` Docker target | Irrelevant to the Docker image — dev-group only, never installed via `uv sync --no-dev`. |
| `psycopg[binary,pool]==3.3.4` | `load_prior_reconciled_paystub_totals`'s `ANY(%s::uuid[])` array-bind pattern | Standard psycopg3 array adaptation; already used elsewhere in `app/db/repo/`, no new pattern introduced. |

## Sources

- Direct repo verification (git log, grep, full file reads) — `app/templates/run_detail.html`, `app/templates/runs_list.html`, `app/templates/eval.html`, `app/routes/runs.py`, `app/routes/dashboard.py`, `app/pipeline/pdf.py`, `app/pipeline/delivery.py`, `app/db/repo/demo.py`, `eval/run_eval.py`, `app/static/style.css`, `pyproject.toml`, `tests/test_dashboard.py`. **HIGH** — this is the primary source for every "current state" claim in this file; no finding above is inferred from the backlog description alone.
- Git commit provenance: `91bc6ca` (2026-07-18, "feat(dashboard): make run detail email-first" — item #1 + #2), `773adf5` (2026-07-17, "feat(20-07): render current and YTD paystubs" — item #3 PDF layout), `20-08`/`1159b6a` (2026-07-17, "feat(20-08): align eval chart with dashboard styling" — item #4). **HIGH.**
- [MDN — `<details>` HTML disclosure element](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/details) — confirms native keyboard operability (Tab focus, Enter/Space toggle) and screen-reader disclosure-widget semantics cited in (a). **HIGH.**
- [MDN — `<summary>` HTML disclosure summary element](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/summary) — confirms the summary text becomes the accessible name for the widget. **HIGH.**

---
*Stack research for: Payroll Agent v4.1 (Demo Polish & Run-Detail UI, mini milestone)*
*Researched: 2026-07-20*
