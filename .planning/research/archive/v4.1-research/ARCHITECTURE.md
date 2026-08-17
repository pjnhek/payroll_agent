# Architecture Research — v4.1 "Demo Polish & Run-Detail UI"

**Domain:** Integration-point mapping for 4 UI/polish backlog items against the live codebase
**Researched:** 2026-07-20
**Confidence:** HIGH (every claim below is grounded in `git log`, `grep`, and direct file reads of the code as it exists on `master` today — not the backlog's description of it)

## Critical Finding — read this before scoping the milestone

**The `backlog.md` → "Next milestone (mini)" section is STALE.** It was written at v4 close (2026-07-20) as if all four items were still pending, but git history proves **three of the four are already fully implemented and tested on `master`**, and the fourth is ~90% implemented with one narrow, real gap. This was done as undocumented/untracked work *before* v4 closed:

| # | Item | Actual state | Evidence |
|---|------|---------------|----------|
| 1 | Run-detail → chronological conversation | **DONE.** Shipped 2026-07-18, `91bc6ca feat(dashboard): make run detail email-first` + `31aa1e3 fix(dashboard): timestamp fallback messages`. | `app/templates/run_detail.html` already has ONE `<section class="conversation">` driven solely by `thread_messages`; `load_outbound_emails` is not called anywhere in `app/routes/runs.py`; `tests/test_dashboard.py::test_run_detail_is_one_ordered_conversation_with_final_reply_composer` asserts ordering, no `Sent Emails`/`Conversation thread` duplicates, no silent 300-char truncation, single reply composer last. |
| 2 | Progressive enhancement (status poll) | **DONE.** `GET /runs/{run_id}/status` exists (`app/routes/runs.py:844-871`) and the ~90-line vanilla-JS poller is live in `run_detail.html:23-94` (2s interval, 60-attempt cap, reloads once on status/queue-label change, no `<meta refresh>` anywhere). | Same commit as #1. |
| 3 | Paystub YTD columns | **~90% DONE**, shipped as Phase 20 Plan 07 (2026-07-17, `76c20f3`/`773adf5`, `.planning/phases/20-exactly-once-send/20-07-SUMMARY.md`). `generate_paystub_pdf` already renders a full Current\|YTD two-column stub, and the accumulation query already exists and is wired into the **confirmation-email PDF attachment path**. **The one real gap:** the standalone dashboard "Download PDF" route does not call the accumulation query, so a PDF downloaded from the run-detail page shows no real YTD (silently defaults to current-period-only). See Item 3 below. | `app/pipeline/pdf.py`, `app/pipeline/delivery.py:115-133`, `app/db/repo/demo.py:144-205`, `app/routes/runs.py:1233-1275`. |
| 4 | Eval chart restyle | **DONE.** Shipped 2026-07-17, `1159b6a feat(20-08): align eval chart with dashboard styling` + `fe53d46 chore(20-08): regenerate dashboard-aligned eval chart`. Option (a) (restyle matplotlib, not the inline-HTML swap) was chosen. | `eval/run_eval.py:144-170` (`CHART_PALETTE`/`CHART_STYLE` constants use `#1E3A5F`/`#6B7280`, drop top/right spines, DejaVu Sans); `eval/chart.svg` committed with those exact hex values (`grep -c` confirms 22×`#1e3a5f`, 6×`#4f46e5`, 139×`#6b7280`). |

**Implication for the roadmapper:** this "mini milestone" is very close to already-shipped. The only concrete remaining code work identified by this research is **threading the existing YTD accumulation query into the dashboard's on-demand PDF download route** (Item 3, narrow). Before writing requirements/phases, the milestone should open with a **verification/audit phase**, not a build phase: re-run the four backlog acceptance criteria against the live code and tests, confirm nothing regressed, and scope exactly the Item-3 gap (plus any other UI polish the user still wants beyond the four backlog items, since the original scope is functionally already met).

---

## Item 1 — Run-detail → chronological conversation (ALREADY SHIPPED)

### What the code does today

`GET /runs/{run_id}` — `app/routes/runs.py:1118-1225` (`run_detail`):
- Loads `run`, `raw_email` (fallback only), `paystubs`, and **`thread_messages`** via `repo.load_thread_messages(run_id)` (`runs.py:1143`).
- Does **not** call `repo.load_outbound_emails` anywhere — that function still exists (`app/db/repo/emails.py:723-742`) and is still exported from `app/db/repo/__init__.py`, but has zero production call sites (`grep` confirms). It is dead code from before the rework; a cleanup pass could delete it, but nothing depends on removing it.
- `thread_messages` seam: `repo.load_thread_messages` (`app/db/repo/emails.py:745-767`) — one SQL query, `WHERE run_id = %s OR id = (SELECT source_email_id FROM payroll_runs WHERE id = %s)`, `ORDER BY created_at ASC`. This is the single normal message-display source; `raw_email` is used in the template only as a fallback when `thread_messages` is empty (`run_detail.html:230-244`).

`app/templates/run_detail.html`:
- One `<section class="conversation">` (`run_detail.html:201-248`) iterates `thread_messages` in ascending order, rendering direction/purpose badges, from/to, timestamp, full `body_text` (no truncation — a `<pre>` block, not a 300-char slice).
- Extraction + reconciliation + computed paystubs are inside a collapsed `<details class="payroll-details">` block (`run_detail.html:272-294`), labeled "Payroll details" — hierarchy demoted exactly as the backlog specified, evidence preserved (badges, PDF download links, provenance badges via the `provenance_badge` macro).
- The Phase-20 delivery-review card renders **after** the conversation section and **before** the collapsed details (`run_detail.html:250-270`), matching the backlog's "operator action after conversation context" requirement.
- Single reply composer (`<section class="reply-composer">`, `run_detail.html:318-331`) is the last block in the template, gated on `run.status == 'awaiting_reply'` — one `simulate-reply` form only (the old duplicate top-banner form is gone).

`app/static/style.css`: 158 lines added in the same commit for `.conversation`, `.conversation-message`, `.payroll-details`, `.reply-composer` — the old 3-column grid CSS was retired in the same diff.

### Tests already in place

`tests/test_dashboard.py::test_run_detail_is_one_ordered_conversation_with_final_reply_composer` (added in `91bc6ca`) is a comprehensive pin: asserts message ordering, direction counts, no `Sent Emails`/`Conversation thread`/`run-detail-grid` legacy strings, a >300-char body renders in full, `Payroll details` appears before `Reply to client`, exactly one `simulate-reply` form. Two more assertions were added to the existing Phase-20 delivery-review tests to check the conversation renders **before** the review card's heading (`test_delivery_review_card_uses_only_the_safe_projection`, `test_clarification_delivery_review_card_is_purpose_isolated`).

### New vs modified (for reference — already committed, nothing to plan)

- Modified: `app/routes/runs.py` (route already trimmed to the single `thread_messages` load), `app/templates/run_detail.html` (rewritten), `app/static/style.css` (new selectors added, old ones retired), `tests/test_dashboard.py` (new pin test + 2 assertions).
- Nothing new to create for this item.

### Residual, optional cleanup (not required, worth flagging to the roadmapper)

- `app/db/repo/emails.py:723-742` `load_outbound_emails` is dead code (no callers) — a candidate for deletion in a hygiene pass, not required for this milestone.
- `app/db/repo/runs.py:130` still has a docstring mentioning `load_outbound_emails` in a list of read seams for the resume path — stale comment, harmless, worth a one-line fix if a cleanup pass touches that file.

---

## Item 2 — Frontend progressive enhancement (ALREADY SHIPPED, confirmed complete)

### Confirmation

- `GET /runs/{run_id}/status` — `app/routes/runs.py:844-871`. Returns `{status, badge_class, badge_label, failure, queue_label, queue_badge_class, has_open_job}` via `_safe_run_with_queue_projection` (same safe-projection helper the route already used elsewhere — no new leak surface).
- Poll JS — `run_detail.html:23-94`. Vanilla JS, no framework, no bundler: `fetch('/runs/' + RUN_ID + '/status')` every 2000ms, `MAX_ATTEMPTS = 60` (120s cap), swaps `#run-status-badge` / `#run-queue-badge` / `#run-durability-note` text/class in place, does exactly ONE `window.location.reload()` when `status` or `queue_label` diverges from the page's server-rendered initial values (so every status-dependent block — banners, forms, gated controls — gets correctly re-rendered rather than trying to patch each one in JS), and stops polling when the status leaves `IN_FLIGHT_STATUSES` and no job is open. Fetch errors are caught and silently skipped (network-blip guard) — no error surfaced to the user, no crash.
- The equivalent poller exists in `runs_list.html` too (per-row badges) — confirmed via the constant name and the `_QUEUE_LABELS`/`_QUEUE_BADGE_CLASSES` vocabulary shared between the route and both templates.
- **No `<meta http-equiv="refresh">` remains anywhere in the templates** — grep for it returns nothing; it was fully replaced.
- **No TypeScript/bundler/SPA was introduced** — the constraint is honored; this is exactly the ~30-90 line vanilla-JS poll the backlog asked for, no CDN scripts, no build step.

### Verdict for the roadmapper

**This item is architecturally complete.** There is nothing to plan or build. If the milestone still wants a phase here, it should be a verification-only step (re-run `tests/test_dashboard.py -k queue_feedback` or similar, confirm `/runs/{id}/status` still returns the safe projection, confirm no meta-refresh regressed back in) rather than an implementation phase.

---

## Item 3 — Paystub YTD columns (SHIPPED for delivery; ONE real gap in the dashboard download route)

### What's already built (Phase 20 Plan 07, `.planning/phases/20-exactly-once-send/20-07-SUMMARY.md`)

**`generate_paystub_pdf`** — `app/pipeline/pdf.py:549-647`. Signature already carries the optional param exactly as the backlog specified:

```python
def generate_paystub_pdf(
    item: PaystubLineItem,
    employee_full_name: str,
    pay_period_start: date | None,
    pay_period_end: date | None,
    *,
    business_name: str | None = None,
    filing_status: str | None = None,
    hourly_rate: Decimal | None = None,
    ytd: PaystubYtdTotals | None = None,   # <-- the "optional YTD params" the backlog asked for
) -> bytes:
```

`PaystubYtdTotals` is a frozen dataclass (`pdf.py:112-143`) with all six categories: `gross_pay`, `federal_withholding`, `fica_ss`, `fica_medicare`, `state_withholding`, `pretax_401k`, `net_pay`. Its classmethod `PaystubYtdTotals.from_prior(prior, item)` combines a prior-totals mapping with the current period's `PaystubLineItem` for display. When `ytd=None` is passed, `generate_paystub_pdf` calls `PaystubYtdTotals.from_prior(None, item)` internally (`pdf.py:600`) — i.e. **it degrades to "current period as its own YTD"** rather than erroring; this is the honest-for-a-single-run default the backlog wanted, now literally the fallback path. Earnings table, deductions table, and net-pay band (`pdf.py:251-541`) all already render aligned **Current | YTD** columns — the "slots in without a rewrite" promise is fulfilled; there is no PDF-layout work left.

**The accumulation query** — `app/db.repo.demo.load_prior_reconciled_paystub_totals` (`app/db/repo/demo.py:144-205`). This is the seam the backlog asked "where should that query live (`app/db/repo/runs.py`?)" — **the actual answer is `app/db/repo/demo.py`**, not `runs.py`. (Worth flagging: this placement is a little surprising — `demo.py` otherwise holds demo-fixture and `load_line_items`/`load_all_runs` helpers, not obviously "the YTD home" — but it's already there, tested, and exported through `app/db/repo/__init__.py`; a future refactor could relocate it to `runs.py` for naming clarity, but that is optional hygiene, not required.)

```python
def load_prior_reconciled_paystub_totals(
    business_id: uuid.UUID,
    employee_ids: list[uuid.UUID],
    pay_period_start: date | None,
    conn: psycopg.Connection | None = None,
) -> dict[uuid.UUID, dict[str, Decimal]]:
```

SQL: `SUM(...)` over `paystub_line_items JOIN payroll_runs` `WHERE historical.status = 'reconciled' AND item.employee_id = ANY(...) AND historical.pay_period_start >= date_trunc('year', %s::date)::date AND historical.pay_period_end < %s`. Sums the **actual stored `paystub_line_items` columns** (`gross_pay`, `federal_withholding`, `fica_ss`, `fica_medicare`, `state_withholding`, `pretax_401k`, `net_pay` — all present in `app/db/schema.sql:200-218`), scoped to `status = 'reconciled'` runs only, within the calendar year, strictly before the current pay period. It **deliberately does not use `employees.ytd_ss_wages`** (that column still exists, `schema.sql:50`, but stays reserved for the SS wage-base cap calc only — key decision recorded in `20-07-SUMMARY.md`: "YTD totals are reconstructed from reconciled historical line items, never the partial Social Security wage-base field"). Returns `{}` (no prior values) if `pay_period_start is None or not employee_ids` — an honest "no calendar scope" degrade, not a crash.

**Where it's wired today** — `app/pipeline/delivery.py:115-133` (`_deliver`, the confirmation-email path only):

```python
prior_ytd = repo.load_prior_reconciled_paystub_totals(
    run["business_id"], employee_ids, run.get("pay_period_start"), conn=conn
)
...
pdf_bytes = generate_paystub_pdf(
    item, employee_name, ..., 
    ytd=PaystubYtdTotals.from_prior(
        prior_ytd.get(item.employee_id) if item.employee_id else None, item,
    ),
)
```

This only fires on a **first-time** confirmation snapshot reservation (`delivery.py`'s `policy.has_existing_snapshot` guard short-circuits before this code on any replay/retry) — by design, per `20-07-SUMMARY.md`'s decision: "Historical reads and PDF generation occur only before an absent confirmation snapshot is reserved; existing slots replay stored bytes." This is the correct Phase-20 seam: SEND-01/02/03 require a retry to replay the exact frozen bytes, never regenerate — so YTD derivation happening only at first-reservation time, and never again for that run, is not incidental, it's load-bearing for the exactly-once-send contract. **Do not move this call outside that guard.**

### The real gap

`GET /runs/{run_id}/pdf/{employee_id}` — `app/routes/runs.py:1233-1275` (`paystub_pdf`, the "Download PDF" link rendered inside the collapsed "Payroll details" section). This route calls `generate_paystub_pdf(...)` **without an `ytd=` argument** (`runs.py:1253-1261`). It is a separate, unfrozen, on-demand render (unlike the confirmation-email attachment, this route is not idempotency-guarded and is not part of the SEND-01/02/03 frozen-snapshot contract — it's a live re-render every click, same pattern as the existing `hourly_rate`/`filing_status` lookups already in that route). So today, clicking "Download PDF" from the run-detail page always shows current-period-as-YTD, even for a `reconciled` run that has prior history — the one place in the app where the promised YTD experience does not appear.

**Fix shape (for the planner):** thread the same `load_prior_reconciled_paystub_totals` call into `paystub_pdf`, exactly mirroring `delivery.py`'s pattern — load `employee_ids` (here, just the one `employee_id` in scope, or all paystubs for the run if a full-set call is preferred for consistency with `delivery.py`), call the repo function with `run["business_id"]`, `employee_ids`, `run.get("pay_period_start")`, wrap the result in `PaystubYtdTotals.from_prior(...)`, pass as `ytd=`. No PDF layout change needed, no schema change, no new repo function — purely a call-site wiring change in `app/routes/runs.py`. This route is NOT gated by the Phase-20 frozen-snapshot/idempotency contract (it isn't a `SEND_OUTBOUND` job, isn't reserved, isn't replayed) — it's safe to re-derive YTD on every request the same way `hourly_rate`/`filing_status` are already re-derived on every request in this same function.

### Test coverage already in place / to extend

- `tests/test_pdf.py::test_current_and_ytd_columns_render_complete_honest_totals` (line 287) — pins the PDF layout given an explicit `ytd=` value. Reusable as-is; no change needed for the layout.
- `tests/test_delivery.py::test_new_confirmation_passes_complete_prior_ytd_to_paystub` and `test_prior_ytd_query_is_employee_scoped_and_complete` — pin the `delivery.py` wiring and the query's employee-scoping/completeness. Good pattern to mirror for a new `test_dashboard.py` (or `test_pdf.py`) test asserting the `/runs/{run_id}/pdf/{employee_id}` route also passes a real `ytd=` derived from prior reconciled runs.

### New vs modified for a plan closing this gap

- Modified: `app/routes/runs.py` (`paystub_pdf` — add the `load_prior_reconciled_paystub_totals` call + `ytd=` param), `tests/test_dashboard.py` or a new test in `tests/test_pdf.py` (assert the download route reflects real accumulated YTD for a business/employee with a prior `reconciled` run in the same calendar year).
- Nothing new to create in `app/pipeline/pdf.py`, `app/db/repo/demo.py`, or `schema.sql` — all already correct and reusable as-is.

---

## Item 4 — Eval chart restyle (ALREADY SHIPPED, option (a) chosen)

### What's already built

`eval/run_eval.py`:
- `CHART_PALETTE` (`run_eval.py:146-155`) — `primary #1E3A5F`, `secondary #6B7280`, `accent #4F46E5`, `danger #DC2626`/`danger_soft #FEE2E2`, matching the dashboard's own palette (same hex values referenced in the project's UI conventions).
- `CHART_STYLE` (`run_eval.py:157-170`) — sets `font.family: sans-serif` / `DejaVu Sans`, `svg.fonttype: none` (keeps text as real text in the SVG, not paths — accessible/selectable), text/axis/tick colors to the secondary gray, `axes.facecolor`/`figure.facecolor` to the dashboard's surface/background tokens.
- `_write_svg_chart` (`run_eval.py:884-1092`) drops chart-junk explicitly: `axis.spines["top"].set_visible(False)`, `spines["right"].set_visible(False)` (`run_eval.py:919-920`), light x-only gridlines (`axis.grid(axis="x", color=palette["border"], linewidth=0.8)`), tightened `k/n` bar labels instead of raw percentages at small n, and a highlighted false-process cell in the confusion-matrix subplot using `danger`/`danger_soft` — deliberately calling out the one dangerous cell rather than a generic heatmap.
- The committed `eval/chart.svg` was regenerated in the same phase (`fe53d46 chore(20-08): regenerate dashboard-aligned eval chart`) and verified (via `grep`) to actually contain the palette hex values, not just the generating code.

**Serve path (confirmed, unchanged by this work and correct for the "no serve-time matplotlib" constraint):** `GET /eval/chart.svg` — `app/routes/dashboard.py:160-171` — serves the **committed static file** via `FileResponse`, baked into the Docker image at build/CI time (via `eval.yml`'s `--check`/`--chart` invocation of `run_eval.py`, not at request time). `matplotlib` is imported lazily inside `_write_svg_chart` only (`run_eval.py:899`), so it never loads on the `--check`/scoring/request path — this was already a hard invariant before this milestone and remains true. `app/templates/eval.html:31` embeds it as a plain `<img src="/eval/chart.svg">` — no inline-HTML/CSS chart was built (option (b) from the backlog was not chosen; option (a) was).

### Verdict for the roadmapper

**This item is complete as option (a).** If there's still a design objection to the current restyle (e.g. it isn't polished enough, or the team now prefers option (b) inline HTML/CSS for on-brand consistency with zero raster/vector image dependency), that is a **fresh design decision to make explicitly**, not a "finish the backlog item" task — the backlog's stated acceptance criteria (dashboard palette, dropped chart junk, clean sans-serif, tighter labels, regenerated + recommitted SVG) are all met. Re-scoping to option (b) would be new work: a template-only rewrite of the three subplots as HTML/CSS bar charts in `eval.html`, deleting the `_write_svg_chart` function and the `--chart` CLI flag, and dropping `matplotlib` from dev deps — a nontrivial redesign, not a "restyle," and should be requirements-gated with the user rather than assumed.

---

## Phase-20 delivery-review safety contracts the run-detail rework must preserve

These were the load-bearing invariants from Phase 20 (SEND-01/02/03) that Item 1's rework had to hold, and that any FUTURE touch to `run_detail.html`/`runs.py` must continue to hold. Confirmed intact in the current code:

1. **Purpose-specific wording** — the delivery-review card renders different copy/actions for `review_kind == 'clarification'` vs the confirmation (default) branch (`run_detail.html:251-267`); `_DELIVERY_REVIEW_PURPOSES` (`runs.py:134-139`) keeps `DeliveryReview`/`ClarificationDeliveryReview` markers mutually exclusive by `error_reason`.
2. **Frozen-evidence links, never regenerated content** — `delivery_review.email_url` / `.attachments[].url` point at `/runs/{run_id}/delivery-review/email` and `/runs/{run_id}/delivery-review/attachments/{id}` (`runs.py:342`, `329`), which stream the **stored snapshot bytes** (`repo.load_outbound_snapshot`, `repo.load_snapshot_attachment`) — never recompose content.
3. **Routes unchanged** — `/runs/{run_id}/delivery-review/{retry-now,mark-delivered,authorize,clarification/*}` are all still present, unmodified in path or method, in the current `runs.py` (lines 940-1116).
4. **Typed acknowledgement requirement** — `authorize_new_confirmation` still gates on the exact literal `acknowledgement != _NEW_CONFIRMATION_ACKNOWLEDGEMENT` ("AUTHORIZE A NEW CONFIRMATION") before doing anything (`runs.py:1054`); the template still requires the operator to type that exact string into a text input (`run_detail.html:265`).
5. **No auto-recovery** — every delivery-review action requires an explicit POST from a rendered form; nothing in `run_detail`'s GET path or the status-poll JSON mutates state.
6. **No provider diagnostics on page** — `_safe_delivery_review_projection` (`runs.py:315-344`) exposes only the finite, allow-listed fields (`purpose`, `recipient`, `subject`, `reserved_at`, `attempt_count`, a human `failure_category` string mapped through `_DELIVERY_REVIEW_CATEGORY_LABELS`, `message_id`, evidence URLs) — no raw provider response/request body ever reaches the template. `tests/test_dashboard.py` asserts several unsafe field names (`provider_response`, `provider_request`, `last_error`, `queue_id`, `error_detail`) are absent from the rendered HTML.
7. **Conversation-before-action ordering** — newly pinned by the 2026-07-18 rework itself: both delivery-review tests now additionally assert `>Conversation<` appears before the review card's heading in the rendered HTML — i.e., Item 1's rework didn't just coexist with the Phase-20 contracts, it added a NEW ordering guarantee on top of them.

Any future plan touching `run_detail.html` or `runs.py`'s delivery-review helpers must re-run (at minimum) `tests/test_phase20_clarification_review.py`, `tests/test_send_idempotency.py`, and the `test_dashboard.py` delivery-review tests, and must not alter the `_DELIVERY_REVIEW_*` constants' semantics.

---

## Suggested build order for whatever remains

Given the finding above, the "roadmap" for this milestone should be very small:

1. **Verification pass (no code)** — re-run the full suite plus the specific pinned tests named above for Items 1, 2, and 4; confirm they still pass on current `master`; treat this as closing out backlog items 1/2/4 as **already done**, not as new phase work. This also produces the audit trail the milestone needs (backlog.md and PROJECT.md should be updated to reflect reality — this is a documentation/bookkeeping task, not a build task).
2. **Item 3 gap closure** — the only real code change: thread `load_prior_reconciled_paystub_totals` into `GET /runs/{run_id}/pdf/{employee_id}` (`app/routes/runs.py`), mirroring `delivery.py`'s existing pattern exactly. Small, single-file change plus one new test. No dependency on Items 1/2/4 (different route, different template region — the "Download PDF" link already lives inside Item 1's collapsed "Payroll details" section, but its behavior is independent of the surrounding markup). Can run in parallel with the verification pass.
3. **Optional hygiene (only if the milestone wants it)** — delete the now-dead `load_outbound_emails` (`app/db/repo/emails.py`), fix the stale docstring reference in `app/db/repo/runs.py:130`, and consider relocating `load_prior_reconciled_paystub_totals` from `app/db/repo/demo.py` to `app/db/repo/runs.py` for naming clarity (backlog explicitly guessed `runs.py` as the natural home). None of this is required for correctness; it's discretionary code-quality cleanup that could be folded into step 2's plan or skipped.

There is no meaningful dependency chain between the four original backlog items — they touch different files/routes (run_detail template+route for #1/#2, PDF generation for #3, the eval scorer for #4) and were in fact built and shipped independently and in parallel already. If the milestone chooses to add genuinely new UI polish beyond the four backlog items (the "mini milestone" scope as originally imagined), that should be captured as fresh requirements now that the actual gap is understood to be much smaller than believed.

## Sources

- `git log --oneline -- app/templates/run_detail.html app/routes/runs.py` (commit `91bc6ca`, 2026-07-18) — Item 1
- `git show 91bc6ca --stat` and its `tests/test_dashboard.py` diff — Item 1 test coverage
- `app/routes/runs.py:844-871` (`run_status`), `run_detail.html:23-94` (poll JS) — Item 2
- `git log --oneline -- app/pipeline/pdf.py` (commits `773adf5`, `bf31a7f`) and `.planning/phases/20-exactly-once-send/20-07-SUMMARY.md` — Item 3
- `app/pipeline/pdf.py:112-143,549-647`, `app/pipeline/delivery.py:90-150`, `app/db/repo/demo.py:144-205`, `app/db/schema.sql:40-55,199-218` — Item 3 seam + schema
- `app/routes/runs.py:1233-1275` (`paystub_pdf`) — Item 3 gap
- `git log --oneline -- eval/run_eval.py eval/chart.svg` (commits `1159b6a`, `fe53d46`) — Item 4
- `eval/run_eval.py:144-170,884-1092`, `app/routes/dashboard.py:160-171`, `app/templates/eval.html:29-31` — Item 4 styling + serve path
- `.planning/PROJECT.md` (v4.1 milestone section, Phase 20 requirements SEND-01/02/03) and `.planning/backlog.md` ("Next milestone (mini)" section) — milestone context vs. actual state

---
*Architecture research for: Payroll Agent v4.1 (Demo Polish & Run-Detail UI)*
*Researched: 2026-07-20*
