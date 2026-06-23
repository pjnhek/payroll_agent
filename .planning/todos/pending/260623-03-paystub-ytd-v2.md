---
id: 260623-03
created: 2026-06-23
source: Phase 05 UAT — paystub redesign discussion
resolves_phase:
priority: low
---

# Paystub YTD columns — defer to v2

The redesigned paystub PDF (professional QuickBooks-style stub) deliberately shows
**no YTD figures**. Rationale (decided during Phase 05 UAT):

- A real pay stub has YTD columns for gross, each tax, and net. The system stores
  only `employees.ytd_ss_wages` (for the SS wage-base cap) — there is NO per-category
  YTD accumulation (gross/FIT/Medicare/state/net) and each run is computed standalone.
- Showing ONE YTD number (ytd_ss_wages) while every other YTD cell is blank looks
  half-built and invites "why don't these reconcile?" — worse than showing none.
  All-or-none: "all" needs a real feature; so "none" for now.

**v2 feature to enable full YTD:** add a YTD-accumulation step — sum each employee's
prior `reconciled` runs (per category: gross, FIT, FICA-SS, Medicare, state, net) as of
the current pay-period, and thread those totals into `generate_paystub_pdf`. Then the
stub can carry the standard Current | YTD two-column earnings/deductions layout.
The PDF function should take optional YTD params so this slots in without a rewrite.

Until then the stub is Current-only, which is honest and correct for a single run.
