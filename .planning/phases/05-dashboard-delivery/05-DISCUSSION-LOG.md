# Phase 5: Dashboard & Delivery - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-22
**Phase:** 5-Dashboard & Delivery
**Areas discussed:** Alias WRITE-side learning loop, Over-40-no-OT validation rule, Operator UI shape & polish, Delivery (email + PDF + concurrency)

**Change-size mode:** BIG CHANGE (interactive, one area at a time, up to 4 issues per area).

---

## Area 1 — Alias WRITE-side learning loop (SCOPE)

### Issue #1 — Is the alias-write loop IN Phase 5?

| Option | Description | Selected |
|--------|-------------|----------|
| A — IN, operator-gated write | Build the minimal write path per backlog: operator approval persists the original shorthand as a known_alias; idempotent; a later run resolves with no clarification | ✓ |
| B — Defer to v2 + fix docs | Ship the 10 requirements only; move the loop to v2 and correct the four docs | |
| C — READ-side demo only (pre-seed) | Fake the auto-resolution for the demo without a real write | |

**User's choice:** A — IN, operator-gated write.

### Issue #2 — When does the alias write fire ("what counts as confirmed")?

| Option | Description | Selected |
|--------|-------------|----------|
| A — At the operator-approval gate | Persist only when the human approves the resolved run; reuses the single gate | ✓ |
| B — Auto-write on the clarification reply | Persist the moment the reply resolves the name (risk: a correcting reply learns a wrong alias) | |
| C — N/A (chose defer) | | |

**User's choice:** A — at the operator-approval gate.

### Issue #3 — Eval coverage for the loop

| Option | Description | Selected |
|--------|-------------|----------|
| A — None needed; eval is seed-bound | Write lands in live DB only; eval reads static seed values, insulated by construction | ✓ |
| B — Seedable before/after eval fixture | Prove the loop in the eval too (if-time) | |
| C — N/A (chose defer) | | |

**User's choice:** A — none needed; eval stays seed-bound. (B noted as deferred if-time.)

**Notes:** Implementation subtlety captured as a research item (D-04): the approval gate needs the original-shorthand → resolved-employee mapping, which the resume path does not currently retain. Candidate storage = the existing `payroll_runs.reconciliation` JSONB; final spot is the planner's call.

---

## Area 2 — Over-40-no-OT validation rule (SCOPE)

| Option | Description | Selected |
|--------|-------------|----------|
| A — Fold into Phase 5, named deliverable | Explicit line item + own success criterion + demo beat; pure rule in validate.py; tested on seeded weekly/biweekly | ✓ |
| B — Standalone quick task BEFORE Phase 5 | Honor backlog's literal "its own insertion before Phase 5"; costs a context switch | |
| C — Defer to v2 + README limitation | Document "client must state OT explicitly" for all frequencies; leaves a silent-underpay hole | |

**User's choice:** A — fold into Phase 5 as a named deliverable.

**Notes:** Rule is per-WORKWEEK (weekly >40, biweekly >80 → clarify; semi-monthly/monthly = documented limitation, no flag). Calc (Phase 3 D-03) untouched; the catch is purely upstream in validation, feeding the existing clarification gate. The backlog's "don't let it get lost in Phase 5" fear is addressed by naming it explicitly with the full spec now in hand.

---

## Area 3 — Operator UI: shape & polish

### Issue #1 — Interaction mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| A — Plain forms + POST-redirect-GET | `<form method=post>` → 303 redirect; lowest risk, no JS state, reliable on cold dyno | ✓ |
| B — htmx partial updates | Swap badge/controls in place; slicker, adds a dep + small failure surface | |
| C — Vanilla-JS fetch + JSON endpoints | Reuse JSON endpoints from JS; most to debug, least benefit | |

**User's choice:** A — plain forms + POST-redirect-GET.

### Issue #2 — Three-column run-detail rendering

| Option | Description | Selected |
|--------|-------------|----------|
| A — 3-col grid: raw `<pre>` \| extracted table \| computed table + reasons banner | Raw email monospace, extracted/computed scannable tables, reasons in a banner; no responsive | ✓ |
| B — Responsive (stacked narrow / 3-col wide) | Same content, reflows; effort the single-screen demo never sees | |

**User's choice:** A — 3-col grid, raw `<pre>`, no responsive.

### Issue #3 — Runs-list density

| Option | Description | Selected |
|--------|-------------|----------|
| A — Reverse-chron table, class-colored badges, awaiting_approval emphasized | created-at/business/badge/summary/detail link; the operator's triage queue | ✓ |
| B — Minimal (id + status only) | Bare list; can't triage without clicking | |

**User's choice:** A — reverse-chron table with class-colored badges.

### Issue #4 — Eval view (DASH-04)

| Option | Description | Selected |
|--------|-------------|----------|
| A — Embed committed chart.svg + metrics/drill-in from summary.json | Serve the SVG as-is; read summary.json for headline + per-fixture drill-in; hermetic, no 2nd renderer | ✓ |
| B — Re-render chart in-page from summary.json | Rebuild the chart in the dashboard; two renderers that can diverge | |

**User's choice:** A — embed the committed SVG, render the rest from summary.json.

---

## Area 4 — Delivery: confirmation email + PDF + concurrency

### Issue #1 — Confirmation email composer (HITL-02)

| Option | Description | Selected |
|--------|-------------|----------|
| A — compose_confirmation mirroring compose_clarification | Draft tier + deterministic template floor; never strands an approved send; DRY-identical | ✓ |
| B — Deterministic template only, no LLM | Simpler/more reliable, but contradicts "LLM-drafted" | |

**User's choice:** A — compose_confirmation mirroring the existing pattern.

### Issue #2 — Paystub PDF shape (HITL-03)

| Option | Description | Selected |
|--------|-------------|----------|
| A — One PDF per employee, on-demand | Real-paystub authenticity; per-line-item download; pure generator over PaystubLineItem | ✓ |
| B — One combined PDF (all employees) | Simpler to attach, less realistic, all-or-nothing download | |

**User's choice:** A — one PDF per employee.

### Issue #3 — Atomic status-claim helper (FOUND-04)

| Option | Description | Selected |
|--------|-------------|----------|
| A — claim_status() via UPDATE…WHERE status=? RETURNING | Guarded conditional UPDATE; 2nd sanctioned writer; reused across 4 gates; update invariant doc; FOR UPDATE satisfied-in-spirit | ✓ |
| B — SELECT…FOR UPDATE in an explicit transaction per gate | Most literal reading of FOUND-04; equivalent safety, more ceremony | |

**User's choice:** A — conditional UPDATE…RETURNING claim helper.

### Issue #4 — Idempotent send (CLAR-04) + error path / re-trigger (INGEST-05)

| Option | Description | Selected |
|--------|-------------|----------|
| A — Atomic claim + already-sent check; build error path + re-trigger | Claim wins approved→sent once; already-sent outbound-row check; re-trigger claims error→received; build INGEST-05 | ✓ |
| B — CLAR-04 send guard only; drop INGEST-05 re-trigger | Honor drop-if-tight; loses the "re-run a stranded run" beat | |

**User's choice:** A — build both; INGEST-05 re-trigger is the clean drop if the phase runs long.

---

## Claude's Discretion

- Exact template/static layout, Jinja2 wiring, CSS approach, route paths.
- The storage spot for the original-shorthand → resolved-employee mapping (D-04 candidate: `reconciliation` JSONB).
- reportlab paystub table layout details.
- `claim_status` signature/return-shape details.
- Confirmation email subject + template-floor prose.
- Eval drill-in table columns + exact `summary.json` fields consumed.

## Deferred Ideas

- Seedable before/after eval fixture proving the alias-learning loop → if-time / v2.
- htmx partial updates / responsive layout → out of scope (no-auth demo).
- Real provider + Docker/Render/Supabase + keep-alive + README/disclaimer + demo recording → Phase 6.
- Full resume-from-arbitrary-status → v2 (INGEST-05 is re-trigger-from-start only).
- Client confirm / state withholding / persisted PDFs / dashboard auth → already Out of Scope in PROJECT.md.
