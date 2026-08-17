# Feature Research — v4.1 "Demo Polish & Run-Detail UI"

**Domain:** Recruiter-facing demo polish for an existing FastAPI + Jinja2 payroll pipeline
**Researched:** 2026-07-20
**Confidence:** HIGH (current-state verdicts are read directly from live source + passing tests, not inferred)

---

## Part A — Current State (the load-bearing finding)

**Headline: all four backlog items are already SHIPPED in code.** `.planning/backlog.md` →
"Next milestone (mini)" describes all four as forward-looking work, but this is **stale
documentation, not an accurate scope gap.** Three of the four (#2, #3, #4) were executed and
closed as tracked plans inside Phase 20 (`20-07`, `20-08` — `.planning/phases/20-exactly-once-send/`),
whose headline was unrelated (SEND-01/02/03, exactly-once confirmation delivery); the fourth (#1)
landed as an untracked quick task (`260718-hie`, commit `91bc6ca`, 2026-07-18) that was correctly
*executed* but whose plan file was deleted before the v4 close audit, so the audit saw an "open"
artifact and the milestone-close step reclassified already-done work into the backlog as if it
still needed building. This is the same failure mode captured in this user's own MEMORY.md
("GSD milestone-close audit resolution" — a passed audit can still show stale-open items that are
actually done; resolve honestly rather than re-planning them).

**Practical consequence for `/gsd-new-milestone`:** there is no v4.1 feature-build work here. The
milestone's real job is (a) a verification/close pass that confirms and documents what already
shipped, (b) fixing the one genuine gap found below (dashboard PDF download doesn't wire YTD),
and (c) optional judgment-call polish (see Part B). Do not write REQUIREMENTS.md items that
re-build any of the four target features from scratch.

### Item 1 — Run-detail → chronological email conversation

**Verdict: SHIPPED.** Commit `91bc6ca` "feat(dashboard): make run detail email-first" (2026-07-18),
touching `app/routes/runs.py`, `app/templates/run_detail.html`, `app/static/style.css`,
`tests/test_dashboard.py` (+88 lines of new tests).

Evidence against the milestone context's specific "confirm the rework is genuinely open" ask:
- **The old 3-column grid is gone.** `run_detail.html:201-248` is a single `<section class="conversation">`
  rendering `thread_messages` in ascending `created_at` order (inbound-first by construction — the
  thread read includes the inbound source row via an OR subquery, per the route comment at
  `runs.py:1139-1141`). There is no raw/extracted/computed 3-column layout anywhere in the file.
- **No duplicate "Sent Emails" / "Conversation thread" surfaces.** `grep -rn "Sent Emails"
  app/templates/` returns nothing; `tests/test_dashboard.py:999` asserts
  `"Sent Emails" not in text and "Conversation thread" not in text` and passes against the live
  template. `tests/test_dashboard.py:990` asserts `text.count(">Conversation<") == 1`.
- **Extraction/paystub tables are demoted to a collapsed details block.** `run_detail.html:272-294`
  — `<details class="payroll-details mt-xl"><summary>...Payroll details...</summary>` containing
  the reconciliation subtable and computed-paystub subtable, exactly as specced. `test_dashboard.py:1001`
  asserts `'<details class="payroll-details mt-xl">' in text`.
  `load_outbound_emails` (`app/db/repo/emails.py:723`) is now dead in the route layer — it is still
  exported from `app/db/repo/__init__.py` but `run_detail()` in `runs.py` no longer imports or calls
  it (confirmed by grep; only `repo.load_thread_messages` is used). Minor cleanup opportunity, not a
  functional gap.
- **Single reply composer, positioned last.** `run_detail.html:318-331` — the `awaiting_reply`
  composer (`<section class="reply-composer">`) is the final block in the template, after the
  conversation, delivery-review card, and collapsed payroll details. The duplicate awaiting-reply
  form that used to sit in the top status banner is gone (`run_detail.html:147-151` shows only a
  short waiting note, no form). `tests/test_dashboard.py:1318,1365` assert conversation content
  precedes the composer/details in the raw response text.
- **No silent truncation.** `run_detail.html:227` renders `{{ msg.body_text or '' }}` inside a
  `<pre>` with no `truncate`/`[:300]` filter — full body every time.
- **Phase-20 delivery-review safety contracts are unchanged.** The delivery-review card
  (`run_detail.html:250-270`) still carries purpose-specific wording, frozen-evidence links
  (`/runs/{id}/delivery-review/email`, `/attachments/{id}`), the typed
  `AUTHORIZE A NEW CONFIRMATION` acknowledgement input, and no provider diagnostics — all
  autoescaped Jinja, `|safe` used nowhere in the file.

**Nothing to plan here.** At most: (a) delete the now-dead `load_outbound_emails` from
`app/db/repo/` if the milestone wants a hygiene pass, (b) minor visual polish (see Part B).

### Item 2 — Frontend progressive enhancement (status poll vs meta-refresh)

**Verdict: SHIPPED. Confirmed nothing remains.** `grep -rn 'http-equiv="refresh"'
app/templates/` returns **zero matches** — there is no meta-refresh anywhere in the codebase to
replace.

- `GET /runs/{run_id}/status` exists at `app/routes/runs.py:844-871`, returning
  `{status, badge_class, badge_label, failure, queue_label, queue_badge_class, has_open_job}` as
  JSON, built from the same safe-projection helpers (`_safe_run_with_queue_projection`) the HTML
  route uses.
- `run_detail.html:23-93` — a ~70-line vanilla-JS IIFE (`setInterval(poll, 2000)`), no framework,
  no `<script src>` beyond the inline block: polls every 2s while `run.status` is in
  `IN_FLIGHT_STATUSES` (`{received, extracting, computed, awaiting_reply}`, `runs.py:77-79`) or has
  an open queue job, swaps the status/queue badges and durability note in place, does a **single**
  full reload only when status or queue label actually changes (loop-safe — the reloaded page
  re-seeds its own `INITIAL_STATUS`), caps at 60 attempts (120s), and silently no-ops on fetch
  errors (network-blip guard).
- `runs_list.html:3-59` — the equivalent per-row poller for the runs-list table, same 2s/60-attempt
  contract, updates each row's badges via `data-run-id` without disturbing the demo-business
  `<select>` or scroll position (the exact failure mode a meta-refresh would have caused).
- No TypeScript, no bundler, no SPA framework anywhere in `app/` (`grep -rn
  "TypeScript\|webpack\|bundler" app/` returns nothing) — the locked no-build-step constraint holds.

**Nothing to plan here.** This item can be struck from requirements outright.

### Item 3 — Paystub YTD columns

**Verdict: SHIPPED for the emailed confirmation PDF; PARTIAL for the dashboard's standalone
PDF-download link.**

- `app/pipeline/pdf.py` — `generate_paystub_pdf()` already takes an optional `ytd:
  PaystubYtdTotals | None = None` kwarg (line 558) and renders a genuine two-column
  **Current | YTD** layout across the earnings table (`_build_earnings_table`, lines 251-381),
  deductions table (`_build_deductions_table`, lines 384-462), and the net-pay summary band
  (`_build_net_pay_band`, lines 465-541). `PaystubYtdTotals` (lines 112-143) is a frozen dataclass
  covering exactly the categories the backlog named: `gross_pay`, `federal_withholding`, `fica_ss`,
  `fica_medicare`, `state_withholding`, `pretax_401k`, `net_pay`.
- **Real accumulation is wired**, not stubbed: `app/db/repo/demo.py:144-189`
  `load_prior_reconciled_paystub_totals(business_id, employee_ids, pay_period_start, conn)` sums
  `paystub_line_items` joined to `payroll_runs WHERE status = 'reconciled' AND
  pay_period_start >= date_trunc('year', ...) AND pay_period_end < <this period's start>` — a
  correct calendar-year-to-date, per-employee, business-scoped query. `app/pipeline/delivery.py:115-136`
  calls it and threads `PaystubYtdTotals.from_prior(prior_ytd.get(item.employee_id), item)` into
  every attachment on the confirmation email. Verified by
  `tests/test_delivery.py:514,572,618` and `tests/test_pdf.py:287-…`
  (`test_current_and_ytd_columns_render_complete_honest_totals`, PDF-text-extraction assertions on
  every Current/YTD label and figure).
- Landed as tracked plan `20-07` ("feat(20-07): derive complete paystub YTD totals" /
  "feat(20-07): render current and YTD paystubs"), i.e. this genuinely closed, not a stray commit.
- **The gap:** `app/routes/runs.py:1233-1275` (`GET /runs/{run_id}/pdf/{employee_id}`, the
  dashboard's standalone "Download PDF" link inside the collapsed Payroll details section) calls
  `generate_paystub_pdf(...)` **without an `ytd=` argument**, so it falls back to
  `PaystubYtdTotals.from_prior(None, item)` — Current and YTD columns print identical numbers for
  every operator-initiated download. The emailed confirmation attachment (the artifact a real
  client sees) is correct; the dashboard's own preview download is not. This is the one concrete,
  small fix left in this milestone's actual scope: thread the same
  `repo.load_prior_reconciled_paystub_totals` call into that route (roughly a 5-line change,
  reusing the existing helper — no new design needed).

### Item 4 — Eval chart restyle

**Verdict: SHIPPED and committed.** `eval/run_eval.py:146-170` defines `CHART_PALETTE` using
the exact dashboard tokens named in the backlog (`"primary": "#1E3A5F"`, `"secondary": "#6B7280"`,
plus `accent`/`surface`/`background`/`border`/`danger`/`danger_soft`) and `CHART_STYLE` (DejaVu
Sans sans-serif, `svg.fonttype: none` for legible embedded text, styled axis/tick/edge colors).
`_write_svg_chart()` (lines 884-1092) strips top/right spines and heavy gridlines (`ax.spines["top"
/"right"].set_visible(False)`, `axis.grid(axis="x", ...)` only), uses horizontal bar charts with
inline value/fraction annotations, and highlights the single dangerous confusion-matrix cell
(false-process) in a distinct danger color — a genuinely on-brand, legible chart, not a raw
matplotlib default. `eval/chart.svg` is committed and was regenerated to match (`git log`:
`chore(20-08): regenerate dashboard-aligned eval chart`, same commit date as the styling change,
39KB file present at HEAD — not stale). `eval.html:29-32` serves it via a plain `<img src="/eval/chart.svg">`
inside a centered card, consistent with the rest of the dashboard's card system.

Landed as tracked plan `20-08` ("feat(20-08): align eval chart with dashboard styling"). **Nothing
to plan here.**

---

## Part B — What "good" looks like (for the residual/polish scope only)

Since three of four items need no build work and the fourth needs a ~5-line data-plumbing fix,
this section exists to (1) give the roadmap a **verification checklist** to confirm the shipped
work actually reads as polished to the target audience, and (2) flag optional refinements if the
milestone wants to spend more than a fix-and-verify pass. Split strictly into table-stakes
(should already be true — verify, don't rebuild) vs. nice-to-have (only if there's spare scope).

### 3.1 Email-conversation run view

**Table stakes (already met — verify, don't rebuild):**

| Expectation | Why it matters to a recruiter reading the code/demo | Status |
|---|---|---|
| Single top-to-bottom timeline, inbound first | This is literally the pitch — "the payroll came from an email conversation" — a fragmented 3-column debug view undercuts the narrative before the reviewer reads a line of code | Met (`run_detail.html:201-248`) |
| Inbound vs outbound visually distinguished | Without this the "here's what the client sent vs. what the system sent back" story is unreadable at a glance | Met — `.conversation-message--inbound` / `--outbound` classes + `neutral`/`pending` direction badges (`run_detail.html:212-214`) |
| Purpose label on outbound messages (clarification / confirmation / field-regression) | Recruiter needs to see the system asked a *specific* question, not a generic bot reply | Met (`run_detail.html:215-217`) |
| Timestamp per message | Establishes the conversation actually happened over time, not synthetically | Met, `%Y-%m-%d %H:%M` (`run_detail.html:218-220`) |
| No silent truncation of message bodies | A recruiter who clicks "expand" and finds nothing, or a body that just stops mid-sentence, reads as a bug, not a feature | Met — full `<pre>` render |
| Collapsed (not deleted) technical detail | The extraction/reconciliation/paystub data is real engineering signal for a technical reviewer — hiding it entirely would remove exactly the depth this portfolio piece is supposed to demonstrate | Met — `<details>` with descriptive summary |

**Nice-to-have (only if the milestone wants extra polish, not required for a credible demo):**
- Human-relative timestamps ("2 minutes ago") alongside the absolute stamp — helps a live demo
  read as real-time without changing the underlying data model.
- A visual "thread connector" (vertical line/rail) between messages, the common email-client
  affordance — currently each message is a standalone card with spacing only; acceptable but a
  connecting rail reads more explicitly as "one conversation."
- An explicit timezone label if timestamps are UTC and the demo audience is elsewhere — small
  legibility win, not required.

### 3.2 Paystub Current | YTD layout

**Table stakes (standard US paystub, what a real one carries — already matched by the schema):**

| Row/column | Present in this build |
|---|---|
| Gross pay (Current + YTD) | Yes |
| Federal income tax withholding (Current + YTD) | Yes |
| Social Security / FICA-SS 6.2% (Current + YTD) | Yes |
| Medicare 1.45% (Current + YTD) | Yes |
| State withholding (Current + YTD, omitted cleanly when absent — correctly disclaimed per PROJECT.md's federal-only scope) | Yes |
| Pre-tax 401(k) (Current + YTD, omitted when zero) | Yes |
| Net pay (Current + YTD) | Yes |
| Rate/hours breakdown for hourly employees | Yes (bonus beyond the standard ask) |

This is already the correct, standard two-column stub shape — no additional category is
missing relative to what a real ADP/Gusto-style stub shows for federal + FICA (state detail
lines beyond a single total, or YTD hours, are the only things a "real" stub sometimes adds, and
the PROJECT.md explicitly disclaims deeper state complexity as out of scope — do not add it).

**The one real gap (table stakes, not polish):** wire `ytd=` into
`GET /runs/{run_id}/pdf/{employee_id}` in `runs.py` so the operator's own download link matches
the emailed client artifact. Skipping this is the one way this milestone could still ship with an
honest defect: a recruiter who clicks "Download PDF" from the dashboard would see Current==YTD
even on a run with real prior history, while the same run's emailed PDF shows correct
accumulation — an inconsistency a careful reviewer could catch.

**Nice-to-have:** none identified — the category list and layout already match the honest,
federal-plus-FICA scope this project deliberately holds to.

### 3.3 Eval chart

**Table stakes (already met):** on-brand palette, legible sans-serif, no chart-junk (spines/heavy
grid), the single dangerous cell (false-process) visually flagged, an honest caption
distinguishing replayed-cache extraction scoring from live deterministic-stage scoring — this
last point is notable: the chart is more forthright about its own methodology than most portfolio
eval charts, which is exactly the "real, legible eval chart over eval exotica" bar PROJECT.md sets.

**Nice-to-have:** none — restyling further (e.g., converting to an inline HTML/CSS chart per the
backlog's "alternative (b)") would be pure churn against an already-shipped, tested, on-brand SVG.
Do not re-open this.

---

## Feature Dependencies

```
Item 3 fix (dashboard PDF ytd= wiring)
    └──requires──> repo.load_prior_reconciled_paystub_totals (already exists, app/db/repo/demo.py)
                       └──requires──> run.business_id + run.pay_period_start (already loaded in paystub_pdf route)

Item 1 verification ──requires──> none (already shipped; read-only confirmation pass)
Item 2 verification ──requires──> none (already shipped; read-only confirmation pass)
Item 4 verification ──requires──> none (already shipped; read-only confirmation pass)
```

No item blocks another. The only code change with any dependency chain is the Item 3 fix, and its
one dependency already exists and is already tested via the confirmation-email path.

## Anti-Features (scope creep to explicitly reject for this milestone)

| Anti-feature | Why it's tempting | Why it hurts the "small, honest, works" story | Do instead |
|---|---|---|---|
| Rebuilding the run-detail conversation view "properly" from scratch | Not knowing it already shipped, a planner might propose a full redesign | Wastes the milestone on work already done, tested, and reviewed; risks regressing a page with real safety-contract tests (`test_phase20_clarification_review.py`, `test_send_idempotency.py`) that already pass against it | Verify with the existing tests + a UAT pass; only fix the dashboard PDF `ytd=` gap |
| Adding htmx/Alpine/a JS framework "since we're already touching the JS" | The backlog text mentions htmx as an *optional* fallback if meta-refresh feels janky | There is no meta-refresh left to replace, and the vanilla-JS poller already works, is tested, and has zero build-step cost — swapping it introduces a new dependency and cold-start risk on Render free for no behavior change | Leave the ~70-line vanilla poller as-is |
| Full state-level withholding rows on the paystub, or per-check MICR/bank details | "Might as well make the stub complete while we're in here" | Explicitly out of scope per PROJECT.md ("State withholding" and the paystub's own docstring: "NO check / MICR line... nothing on this document is fabricated") | Leave as-is; the federal+FICA(+optional single state line) shape is the correct, disclosed scope |
| Converting `eval/chart.svg` to an inline HTML/CSS chart (backlog's alternative (b)) | The backlog still lists it as an option | The SVG path is already shipped, styled, tested, and regenerated — switching rendering approaches now is pure rework with no user-visible benefit and a nonzero regression risk to the CI eval gate | Leave as-is |
| Deleting `load_outbound_emails` as part of this milestone's "must-fix" list | It's genuinely dead code now | It's a hygiene item, not a demo-facing defect; bundling unrelated cleanup into a UI-polish milestone dilutes the honest scope story this project has held to across v2–v4 | Note it in backlog.md as an optional follow-up, don't block v4.1 on it |

## Sources

- Live source read at HEAD (`master`, `31aa1e3`): `app/templates/run_detail.html`,
  `app/templates/runs_list.html`, `app/routes/runs.py`, `app/pipeline/pdf.py`,
  `app/pipeline/delivery.py`, `app/db/repo/demo.py`, `eval/run_eval.py`, `app/templates/eval.html`.
- `git log` on each file confirming commit provenance and dates: `91bc6ca` (run-detail rework,
  2026-07-18), `773adf5`/`76c20f3` (YTD paystub, plan `20-07`), `1159b6a`/`fe53d46` (eval chart
  restyle, plan `20-08`).
- Tracked plan artifacts: `.planning/phases/20-exactly-once-send/20-07-PLAN.md` +
  `20-07-SUMMARY.md`, `20-08-PLAN.md` + `20-08-SUMMARY.md` (confirm items 3 and 4 as closed,
  reviewed work, not speculative).
- Test evidence: `tests/test_dashboard.py` (conversation ordering, no-duplicate-heading,
  collapsed-details assertions), `tests/test_delivery.py` + `tests/test_pdf.py` (YTD accumulation
  correctness and PDF rendering).
- `.planning/PROJECT.md` and `.planning/backlog.md` — milestone framing and the (stale) source
  description of the four target features being reconciled here.

---
*Feature research for: v4.1 Demo Polish & Run-Detail UI (payroll_agent)*
*Researched: 2026-07-20*
