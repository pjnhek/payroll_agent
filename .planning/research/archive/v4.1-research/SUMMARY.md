# Project Research Summary

**Project:** Payroll Agent — v4.1 "Demo Polish & Run-Detail UI" (mini)
**Domain:** Current-state verification of a subsequent, UI-only polish milestone
**Researched:** 2026-07-20
**Confidence:** HIGH (three independent codebase-grounded researchers corroborated; the one conflict was resolved by direct source read)

## Executive Summary

This milestone was scoped from four demo/UI-polish items bundled in `backlog.md → "Next milestone (mini)"`
at v4 close. **The four researchers found that backlog section is stale: the work it describes as future is
already shipped.** Cross-checked against `master` (git log + full file reads, not backlog text), **three of
the four items are fully shipped and test-covered, and the fourth is ~90% shipped** — its only genuine gap is
a small dashboard/email parity bug.

This is the exact failure documented in the project's own MEMORY.md: work landed inside another phase / an
untracked quick task, and the tracking artifact (backlog, todo, flag) was never updated to match. Items #1
and #2 shipped together in an **untracked** quick task (`260718-hie`, commit `91bc6ca`, 2026-07-18); item #3's
YTD engine + email wiring shipped as **Phase 20 plans 20-07/20-08** (2026-07-17); item #4 shipped 2026-07-17
(`1159b6a` + `fe53d46`).

**Net remaining work across the whole milestone: one ~10-line dashboard-download YTD-parity fix + a
regression test.** The honest correction is to reconcile the records and right-size (or retire) the milestone,
not to plan four build phases for work that is already done.

## Key Findings

### Per-item current state (verdict · evidence)

| # | Item | Verdict | Evidence |
|---|------|---------|----------|
| 1 | Run-detail → chronological email conversation | **SHIPPED** | Commit `91bc6ca` (2026-07-18, untracked quick task `260718-hie`). 3-column grid + duplicate "Sent Emails"/"Conversation thread" gone; single chronological conversation, collapsed `<details class="payroll-details">`, one composer last. Pinned by `tests/test_dashboard.py::test_run_detail_is_one_ordered_conversation_with_final_reply_composer` + a `>300-char` no-silent-truncation test (`test_dashboard.py:926`). |
| 2 | Frontend progressive enhancement (no build step) | **SHIPPED** | `GET /runs/{run_id}/status` at `app/routes/runs.py:844`; ~70-line vanilla-JS 2s poller in `run_detail.html` + `runs_list.html` that stops on terminal status and never resets form state. **Zero `<meta http-equiv="refresh">` remains anywhere in `app/`.** |
| 3 | Paystub YTD columns | **~90% SHIPPED — 1 gap** | Display layer (`PaystubYtdTotals`, `generate_paystub_pdf(..., ytd=)`, full Current\|YTD reportlab table) + accumulation query `load_prior_reconciled_paystub_totals` (`app/db/repo/demo.py:144`, exported in `repo/__init__.py`) both exist and are wired into the **emailed** confirmation PDF (`app/pipeline/delivery.py:115`). **GAP:** the on-demand dashboard "Download PDF" route `paystub_pdf()` (`app/routes/runs.py:1242`) calls `generate_paystub_pdf(...)` **without `ytd=`**, so an operator's manual download silently shows Current-as-YTD while the emailed copy of the same run shows real YTD. |
| 4 | Eval chart restyle | **SHIPPED** | Commits `1159b6a` + `fe53d46` (2026-07-17). Dashboard palette (`#1E3A5F`/`#6B7280`), spines/gridlines removed, sans-serif; `eval/chart.svg` regenerated + committed; matplotlib is a **dev-group-only** dep imported inside the offline generator (no serve-time cost — `/eval/chart.svg` serves a static committed file). |

### Conflict resolved (item #3)

The Pitfalls researcher claimed the accumulation query "doesn't exist anywhere in `app/db/repo/`" and item #3
was "genuinely unbuilt." **This was wrong** — it looked in `repo/runs.py`/`repo/emails.py` and missed
`repo/demo.py`. Direct read confirms `load_prior_reconciled_paystub_totals` exists at `app/db/repo/demo.py:144`
and is actively called at `app/pipeline/delivery.py:115`. Features/Stack/Architecture (which cited the exact
line) are correct: item #3 is a wiring-parity fix, not a build.

### Zero new dependencies

All four items use primitives already in `pyproject.toml` (native `<details>`/`<summary>`, CSS class
modifiers, `reportlab` Table/TableStyle, the existing `psycopg` pool, dev-only `matplotlib`). Nothing new to
add.

### The one genuine gap — exact fix

In `paystub_pdf()` (`app/routes/runs.py:1242`), mirror the `delivery.py:115` pattern: load
`repo.load_prior_reconciled_paystub_totals(run["business_id"], [employee_id], run.get("pay_period_start"))`,
build `PaystubYtdTotals.from_prior(prior.get(employee_id), item)`, and pass `ytd=` into
`generate_paystub_pdf(...)`. No schema change, no PDF-layout change. Add a `test_dashboard.py` test asserting
the downloaded PDF's YTD ≠ current when strictly-prior `reconciled` runs exist for that employee.

## Safety constraints any residual change must preserve

The run-detail page hosts the **Phase-20 delivery-review card**. Any markup reorg near it must preserve 6
properties (enumerated in `ARCHITECTURE.md`/`PITFALLS.md`): purpose isolation, frozen-evidence URLs, exact-
string typed acknowledgement, no auto-recovery, safe-projection-only fields, correct routes. The download-route
fix does not touch this card, so risk is low — but the regression suite (`test_phase20_clarification_review.py`,
18 tests) must stay green.

Independent-by-design note (from PITFALLS.md): `employees.ytd_ss_wages` (the SS wage-base-cap input used by
the calc engine) and the new **display-YTD** summed from prior paystub line items are structurally decoupled
and will never naturally reconcile — document them as independent; do not try to sync them.

## Implications for Roadmap

- **Do NOT write build-from-scratch requirements for items #1, #2, #4** — they are shipped. At most, lock
  them with the already-passing regression tests named above.
- **The only concrete code requirement is the item-#3 dashboard-download `ytd=` wiring fix** — small,
  single-file, well-understood, no schema/layout change.
- **The bigger deliverable is a records correction:** update `PROJECT.md` (the "four target features"
  framing) and `backlog.md → "Next milestone (mini)"` to reflect that the work is done, and note the
  untracked `260718-hie` quick task in history.
- **Right-size or retire the milestone.** A full GSD milestone (research → requirements → multi-phase roadmap
  → verify → secure → audit → complete) is disproportionate to a ~10-line fix. Options for the operator:
  (A) skip the milestone, do the fix as `/gsd-quick`, correct the records; (B) keep v4.1 as a single-phase
  "verify + fix + reconcile" milestone; (C) re-scope to genuinely new polish (net-new, not from this backlog).

## Optional (net-new, NOT in the original backlog acceptance criteria)

Flagged by researchers as available but **not required** — only if the operator wants to spend polish budget:
- YTD in the HTML "Payroll details" table (not just the PDF).
- Per-message `<details>` collapse for exceptionally long individual emails; relative timestamps; thread
  connector rail; timezone label on the conversation view.
- Item #4 option (b): replace the static SVG with an inline HTML/CSS bar chart (removes the SVG-vs-scorer
  drift vector by construction) — a **fresh** design choice, since option (a) matplotlib-restyle already shipped.
- Hygiene: delete the now-dead `load_outbound_emails` route load; fix a stale run-detail docstring.

## Sources

- Direct source reads on `master`: `app/routes/runs.py` (:844 status route, :1242 `paystub_pdf`), `app/templates/run_detail.html`, `app/templates/runs_list.html`, `app/pipeline/pdf.py`, `app/pipeline/delivery.py` (:115 YTD wiring), `app/db/repo/demo.py` (:144 accumulation query), `app/db/repo/__init__.py`, `eval/run_eval.py`, `app/routes/dashboard.py`, `app/templates/eval.html`, `pyproject.toml`. **HIGH.**
- `git log` provenance: `91bc6ca` (items #1/#2, 2026-07-18), `20-07`/`20-08` in Phase 20 (item #3 engine+email, 2026-07-17), `1159b6a`+`fe53d46` (item #4, 2026-07-17). **HIGH.**
- Passing regression tests: `tests/test_dashboard.py` (conversation order, >300-char), `tests/test_demo_landing.py`, `tests/test_phase20_clarification_review.py` (18 delivery-review safety tests). **HIGH.**
- Per-dimension research: `.planning/research/STACK.md`, `FEATURES.md`, `ARCHITECTURE.md`, `PITFALLS.md` (this session).
