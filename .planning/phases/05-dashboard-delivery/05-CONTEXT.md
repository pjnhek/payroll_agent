# Phase 5: Dashboard & Delivery - Context

**Gathered:** 2026-06-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 5 builds the **operator-facing dashboard + the post-approval delivery pipeline** that wraps the working slice: a no-auth Jinja2 web UI (runs list → three-column run detail → approve/reject), the post-approval delivery (LLM-drafted confirmation email + on-demand reportlab PDFs), the **mandated atomic status-claim helper** that makes approve/resume/re-trigger race-safe, the eval view (reads Phase 4's committed `summary.json` + `chart.svg`), and the "Send test email" demo trigger + visible error path.

**The 10 Phase-5 requirements (authoritative, per ROADMAP.md / REQUIREMENTS.md):** DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, HITL-02, HITL-03, CLAR-04, INGEST-05 (drop-if-tight), FOUND-04.

**PLUS two deliberate scope additions decided in this discussion (see D-01, D-02):**
- **The alias WRITE-side learning loop** (the "learns and stops asking" demo beat) — four docs (CLAUDE.md, PROJECT.md, ROADMAP.md, `.planning/backlog.md`) commit it to land HERE at the operator gate; it was absent from the 10 listed requirements, and this discussion confirmed it IS in.
- **The over-40-no-OT validation rule** (silent-underpay guard) — `.planning/backlog.md` flagged it for "its own insertion BEFORE Phase 5" but it was never inserted; this discussion folds it into Phase 5 as a named deliverable.

**Locked by requirements / prior phases (NOT re-opened in discussion):**
- **No-SPA Jinja2 + vanilla forms, NO auth** (PROJECT.md "no auth on the dashboard"; CLAUDE.md §7). `reportlab==5.0.0`, `jinja2==3.1.6`, `python-multipart==0.0.20` are ALREADY in runtime deps — no new deps needed for the UI/PDF stack.
- **DASH-02 three-column layout is locked: raw cleaned inbound email LEFTMOST, then `extracted_data`, then computed paystubs, + the decision object's reasons** (the honest operator gate — verifies the LLM's *reading* against what the client *sent*). The *rendering* was open and is now decided (D-06).
- **HITL-03: PDFs generate on demand in memory (reportlab + BytesIO), NOTHING persisted to disk or a storage bucket.**
- **HITL-02 status flow: `approved → sent → reconciled`, confirmation email is LLM-drafted.**
- **`set_status` is currently the sole `payroll_runs.status` writer** — the atomic-claim helper (D-09) revises this invariant to two sanctioned writers.
- **DASH-04 consumes Phase 4's committed artifacts** (`eval/summary.json`, `eval/chart.svg`) — both present; eval is hermetic (no live LLM, no DB on the dashboard read path).
- **The clarify→reply→resume loop, the orchestrator state machine, ERROR persistence (`error_reason` + `ERROR` status), and the `compose_clarification` draft+fallback pattern already exist** (Phases 2 / 2.1) and are reused, not rebuilt.

**Phase priority framing:** Phase 5 directly serves priority #1 (visibly works end-to-end) and #2 (clean 60–90s demo). The dashboard IS the demo surface; bias every choice toward reliability on a cold Render dyno over polish.

</domain>

<decisions>
## Implementation Decisions

### Area 1 — Alias WRITE-side learning loop (SCOPE: IN)

- **D-01 (IN — operator-gated alias write):** Build the minimal write path per `.planning/backlog.md` → "Learn aliases from confirmed clarifications." When the operator **approves** a run whose original submission contained an unresolved name that the client's reply later resolved to employee X, **persist that original shorthand into `X.known_aliases`** (idempotent — do not double-add). A subsequent run with the same nickname then resolves at the deterministic stored-alias fast-path with **no clarification**. This completes the headline narrative ("clarifies *once, then learns*") and is the demo's third beat.
- **D-02 (write fires at the operator-approval gate):** The alias persists **only** when the human operator approves the resolved run — the one moment a human has verified the entire resolved run is correct. Reuses the single existing gate; **no auto-write on the clarification reply** (a reply might *correct* the name, not confirm it — auto-learning a wrong alias would silently poison future resolution, violating "never guesses on a money-moving decision"). This is the backlog's "safer, human-in-the-loop" recommendation.
- **D-03 (eval stays seed-bound — no Phase-4 corpus change):** The alias write lands in the **live DB only**; the Phase 4 eval reads static `app/db/seed.py` values, so it is insulated by construction. The **demo proves the loop**; no change to the existing eval corpus. (Proving the loop *in* the eval via a seedable before/after fixture is noted as a deferred "if-time" idea, not in scope.)
- **D-04 (the mapping the approval gate needs — RESEARCH ITEM, not yet decided):** The approval gate must know **which original shorthand resolved to which employee**. Today the resume path re-extracts the corrected name but does NOT retain the original-unresolved → resolved-employee pairing. The planner/researcher must find a place to persist that mapping across clarify→reply→resume→approval. **Candidate (Claude's lean, not locked):** the run's existing `decision`/`reconciliation` JSONB column (`payroll_runs.reconciliation`, `app/db/schema.sql:87`) — already the home for per-run resolution facts. Decide the exact storage spot during planning.

### Area 2 — Over-40-no-OT validation rule (SCOPE: folded into Phase 5)

- **D-05 (fold in as a named deliverable with its own success criterion + demo beat):** Add the per-**workweek** silent-underpay guard to `app/pipeline/validate.py` (pure function, calc untouched — Phase 3 D-03 "trust the submitted split, never auto-derive" is unchanged; the catch is purely upstream in validation, emitting a `ValidationIssue` into the **already-built** clarification gate). Spec (from `.planning/backlog.md` → "Over-40-no-OT validation rule"):
  - **Weekly** (`pay_periods_per_year=52`, 1 workweek): `hours_regular > 40` with no `hours_overtime` field → emit `ValidationIssue` → `decide` gates to `request_clarification`.
  - **Biweekly** (`=26`, 2 workweeks): `hours_regular > 80` with no OT → clarify (>80 guarantees a week passed 40).
  - **Semi-monthly** (`=24`) / **Monthly** (`=12`): period boundaries cut across workweeks → **documented README limitation, NO flag** (the only place the "client must state OT explicitly" line is correct — the undetectable slice only).
  - Testable against already-seeded employees (the seed covers weekly + biweekly). Demo beat: weekly "Bob worked 45 hours" with no OT field → "is that 40 regular + 5 overtime, or 45 straight?" — puts the never-wrong-on-money thesis on camera.

### Area 3 — Operator UI: shape & polish

- **D-06 (interaction mechanism — plain server-rendered forms + POST-redirect-GET):** Approve / reject / send-test / re-trigger are `<form method=post>`; the handler does the work and **303-redirects** back to the run detail or runs list. `python-multipart` is in deps exactly for this. No JS state machine, no partial-render edge cases — lowest risk, demos reliably on a cold dyno. Full-page reloads are imperceptible at ~4 pages with one operator action per run. (The existing JSON `/runs/{id}/approve|reject` endpoints may remain as an API, but the UI does not depend on hand-written fetch glue.)
- **D-07 (three-column run-detail rendering — literal 3-col CSS grid):** raw cleaned email as a **monospace `<pre>`** (shows exactly what the client sent, cruft and all — the point of the honest gate) | `extracted_data` as a **readable per-employee table** (employee → the 5 hours fields + any 401k override) | computed paystubs as a **table** (gross / FICA / federal / net per employee). The decision object's reasons (`gate_reasons` / `unresolved_names` / `missing_fields`, or "process") render in a **prominent banner** so *why this run is in this state* is unmissable. **NO responsive** (single-screen demo; PROJECT.md makes responsive a non-goal). Optimize for the operator scanning the raw email column against the extracted column.
- **D-08 (runs list — DASH-01):** reverse-chronological **table**: created-at, business, status badge, a one-line summary (e.g. # employees or the gate reason), action link to detail. **Badge colored by status class:** pending-action (`awaiting_approval`) **emphasized**, in-flight (extracting/computing/awaiting_reply) neutral, terminal-good (sent/reconciled) green, terminal-bad (rejected/error) red. The runs list is the operator's triage queue — "what needs me" at a glance.
- **D-09a (eval view — DASH-04 — embed the committed SVG, render the rest from `summary.json`):** Serve Phase 4's committed `eval/chart.svg` **as-is** (it is *the* recruiter-visible proof artifact — do NOT rebuild a second chart renderer in the dashboard; that would violate the DRY seam). Read `eval/summary.json` for the **headline metrics** (false-process count + the three core metrics) and the **per-fixture drill-in** (each fixture's raw email beside expected vs actual extraction/decision — `summary.json` already carries per-fixture details, stored in Phase 4 D-08 precisely so the dashboard could read them). Hermetic: no live eval, no DB on this path. The drill-in table is the only genuinely new work.

### Area 4 — Delivery: confirmation email + PDF + concurrency

- **D-10 (confirmation email — `compose_confirmation` mirroring `compose_clarification`):** New composer in the same DRY shape as `app/pipeline/compose_email.py:88` — cheap `draft` tier for warmth + a **deterministic template floor** (run total, per-employee net, pay date) so a draft-tier failure **never strands an already-approved send** (even more critical post-approval than on the clarify path). The PDFs carry the authoritative numbers; the email body is the cover note. Satisfies HITL-02's "LLM-drafted" while keeping reliability via the floor; keeps both composers structurally identical.
- **D-11 (paystub PDF — one PDF per employee, on-demand):** reportlab + BytesIO, in-memory (HITL-03 locked). **One PDF per employee** (how real paystubs are issued — the builder's accounting-days authenticity), each containing the `PaystubLineItem` fields Phase 3 computes: gross (with OT / leave breakdown), pre-tax 401k, FICA (SS + Medicare), federal withholding, **net**. Attached to the confirmation email **and** downloadable per-line-item from the run-detail page. **The PDF generator is a PURE function of `PaystubLineItem` + employee + run metadata** (mirrors the pure-stage seam) so it is testable without a DB and reused by both the email-attach path and the on-demand download route.
- **D-12 (atomic status-claim helper — FOUND-04 — `claim_status()` via conditional `UPDATE … RETURNING`):** Add `claim_status(run_id, expected, new) -> bool` to `app/db/repo.py`: `UPDATE payroll_runs SET status=%s, updated_at=now() WHERE id=%s AND status=%s RETURNING id`. A claim succeeds **only if the row was still in `expected`**; a losing concurrent caller gets no row → logs a late/duplicate and **drops cleanly** (does not re-run). This becomes the **second sanctioned status writer**: `set_status` stays for *unguarded* forward transitions inside a run that already holds the path (e.g. computing → computed → awaiting_approval); `claim_status` is the **atomic guarded** transition for every contended gate — **(a) approve/reject** (claim `awaiting_approval → approved/rejected`), **(b) resume** (claim `awaiting_reply → extracting` — closes the `resume_pipeline` non-atomic load-then-set documented at `orchestrator.py:115-116`), **(c) re-trigger** (claim `error → received`/extracting), and **(d) the initial run claim**. **MUST update the "ONE AND ONLY writer of payroll_runs.status" invariant doc** (`repo.py` set_status docstring) to "two writers: `set_status` (unguarded) + `claim_status` (atomic, guarded)" so the codebase's own rule stays honest. A single-row `UPDATE … WHERE status=? RETURNING` is atomic in Postgres without an explicit transaction and composes with the existing optional-`conn=` pattern. **FOUND-04's literal `SELECT … FOR UPDATE` wording is read as satisfied-in-spirit** by the atomic conditional UPDATE (both structurally prevent double-approval) — see Specific Ideas.
- **D-13 (idempotent send + error path / re-trigger — CLAR-04 + INGEST-05, BUILD both):** Idempotency is two layers: (1) the **`claim_status` claim** means only one caller wins `approved → sent`, so the send fires once; (2) **before sending, check for an existing outbound confirmation row** for the run (reuse the existing `repo.get_outbound_message_id` pattern, `repo.py:467`) — if one exists, **skip the send and just advance**. Re-trigger claims `error → received` atomically and re-runs from the **start of the run**; the claim + already-sent check make a re-trigger structurally unable to duplicate a confirmation. **Error path:** the orchestrator already persists `ERROR` + `error_reason` on any stage failure — the dashboard surfaces it (red badge + the reason) with a **re-trigger button**. "Nothing silently hangs" is a real recruiter-facing reliability beat, nearly free once the claim helper exists. **If the phase runs long, INGEST-05's re-trigger route is the clean drop** (per its drop-if-tight flag), keeping the CLAR-04 send guard.

### Claude's Discretion
- **Exact template/static file layout** (e.g. `app/templates/`, `app/static/`), Jinja2 wiring (`Jinja2Templates`), CSS approach (inline vs one stylesheet), and route paths (`/runs`, `/runs/{id}`, `/eval`, etc.) — the decisions fix the *shape* (no-SPA, plain forms, 3-col grid, class-colored badges); the layout is the planner's call.
- **The exact storage spot for the original-shorthand → resolved-employee mapping (D-04)** — candidate is the existing `reconciliation` JSONB; the planner/researcher decides after reading the resume path.
- **reportlab table layout details** for the paystub (fonts, column widths, header) — D-11 fixes the *contents* (the `PaystubLineItem` fields, per-employee, pure generator); the visual layout is the planner's.
- **`claim_status` signature/return shape details** (bool vs returning the row; how the losing caller's log line reads) — D-12 fixes the *mechanism* (conditional UPDATE … RETURNING, second sanctioned writer, the four call sites, the invariant-doc update).
- **Confirmation email subject + the template floor's exact prose** — D-10 fixes the *pattern* (mirror `compose_clarification`, draft tier + deterministic floor that never strands the send); the copy is the planner/researcher's.
- **Eval drill-in table columns + exact `summary.json` fields consumed** — D-09a fixes that the committed SVG is embedded as-is and the metrics/drill-in come from `summary.json`; the precise rendering is the planner's.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap (the locked scope)
- `.planning/REQUIREMENTS.md` — **DASH-01..05, HITL-02, HITL-03, CLAR-04, INGEST-05, FOUND-04** (full text). Note DASH-02's raw-body-leftmost honest-gate rationale; INGEST-05's "re-trigger from the START of the run" scoping + drop-if-tight flag; FOUND-04's `SELECT … FOR UPDATE` wording (read as satisfied-in-spirit by D-12's atomic conditional UPDATE); DASH-04's per-fixture drill-in requirement.
- `.planning/ROADMAP.md` §Phase 5 — the goal + the 5 success criteria. **Criterion #2 carries the ⚠ "MUST READ `.planning/backlog.md` → Atomic status claim"** flag (the CR-02 residual, found 3×) — that is D-12.
- `.planning/backlog.md` — **THREE items, all in Phase-5 scope now:** (1) "Learn aliases from confirmed clarifications" (= D-01..D-04, the operator-gated alias write + its acceptance sketch); (2) "Atomic status claim — close the resume/approve race" (= D-12, the full problem statement + the `UPDATE … WHERE status=? RETURNING` fix + the acceptance sketch: two concurrent approvals → exactly ONE advance + ONE send); (3) "Over-40-no-OT validation rule" (= D-05, the full per-workweek spec + thresholds + the documented semi-monthly/monthly limitation).
- `.planning/PROJECT.md` — Core Value (the human-confirmation learning loop, alias WRITE side = Phase 5); §Context (the two pause states; the `status` column IS the orchestration engine; the DRY pure-function seam); §Constraints (one operator gate; no auth; PDFs on demand). Key Decisions: operator gate shows the raw cleaned email as the leftmost column.
- `./CLAUDE.md` — §7 (dashboard = FastAPI + Jinja2, no SPA), §4 (reportlab on-demand in-memory PDFs, BytesIO → StreamingResponse), Render free realities (ephemeral FS, `$PORT`, cold start), and the **uv** tooling rule (`uv run`, `uv add` — never pip).

### Prior-phase context that constrains Phase 5
- `.planning/phases/02-walking-skeleton/02-CONTEXT.md` + `.planning/phases/02.1-deterministic-decisioning/02.1-CONTEXT.md` — the orchestrator state machine, the two pause states (`awaiting_reply` / `awaiting_approval`), the deterministic decisioning model the dashboard renders, and the clarify→reply→resume loop the alias-write loop hooks into.
- `.planning/phases/03-harden-the-calc/03-CONTEXT.md` — the `calculate` / `PaystubLineItem` fields the PDF renders + the Pub 15-T disclaimers (OBBBA, no Additional Medicare) the README/confirmation must honor.
- `.planning/phases/04-the-eval-the-proof/04-CONTEXT.md` — D-08 (`summary.json` + committed SVG are what DASH-04 consumes; per-fixture details stored for the drill-in) and the explicit deferral note: "the Phase 5 dashboard eval view (DASH-04) renders Phase 4's artifacts."

### Code Phase 5 extends / reuses (verified signatures — file:line)
- `app/main.py:224` `approve` / `:234` `reject` / `:240` `_operator_transition` — the **crude** existing gate (load-then-set, no FOR-UPDATE, no email/PDF); Phase 5 hardens this with D-12 + adds the confirmation send + the alias write.
- `app/db/repo.py:267` `set_status` (the current "sole writer" — D-12 revises the invariant), `:201` `load_run`, `:173` `create_run`, `:372` `replace_line_items`, `:467` `get_outbound_message_id` (the already-sent-row read D-13 reuses), `:242` `load_inbound_email` (the raw cleaned body for the DASH-02 leftmost column).
- `app/pipeline/orchestrator.py:55` `run_pipeline`, `:87` `resume_pipeline` (non-atomic load-then-set at `:115-116` — D-12 closes it), `:168` `_run_stages`, `:195` the `AWAITING_APPROVAL` pause (the gate Phase 5's send fires AFTER), `:200` `_clarify`.
- `app/pipeline/compose_email.py:88` `compose_clarification` + `:135` `clarification_subject` — the DRY pattern D-10's `compose_confirmation` mirrors (draft tier + deterministic floor).
- `app/pipeline/validate.py:50` `validate(extracted, roster, matches) -> list[ValidationIssue]` — PURE; D-05 adds the over-40-no-OT rule here (today only flags missing-hours).
- `app/pipeline/calculate.py:180` `calculate(...) -> PaystubLineItem` — PURE; the source of the numbers D-11's PDF renders.
- `app/pipeline/reconcile_names.py:95` `reconcile_names` + `:56` the alias READ (normalized exact match over `emp.known_aliases`) — the read side D-01's write completes.

### Contracts & schema Phase 5 touches (file:line)
- `app/models/contracts.py:35` `InboundEmail`, `:103` `Extracted` (+ `:60` `ExtractedEmployee`), `:119` `Decision` (`final_action`/`gate_reasons`/`unresolved_names`/`missing_fields`/`resolutions`), `:149` `PaystubLineItem`.
- `app/models/roster.py:26` `Employee` (`known_aliases: list[str]`, `:39` — the alias-write target; the full calc-input set), `:115` `Roster`, `:205` `ValidationIssue`.
- `app/db/schema.sql:61` `payroll_runs` (the 11-value `status` enum, `:79` `extracted_data` JSONB, `:80` `decision` JSONB, `:87` `reconciliation` JSONB — the D-04 candidate storage, `:88` `error_reason`), `:106` `paystub_line_items`, `:129` `email_messages` (`:132` `direction` inbound/outbound — the already-sent guard), `:145` `eval_results`.
- `app/db/seed.py:83/138/249` `known_aliases` (Maria Chen has aliases; the David/Daniel Reyes collision pair share `"D. Reyes"`) — the seeded data the alias-write loop demo and the OT rule (weekly/biweekly employees) test against.

### Artifacts DASH-04 consumes (committed by Phase 4)
- `eval/summary.json` — headline metrics + per-fixture details (the drill-in source) + pinned model IDs.
- `eval/chart.svg` — the committed per-category chart embedded as-is (do NOT re-render).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **UI/PDF stack already in runtime deps** — `reportlab==5.0.0`, `jinja2==3.1.6`, `python-multipart==0.0.20` are in `pyproject.toml`. Phase 5 adds **no** new runtime deps for the dashboard or PDFs.
- **`compose_clarification` (draft tier + deterministic template floor)** is the exact pattern `compose_confirmation` (D-10) clones — including the load-bearing "a draft failure never strands the run" fallback.
- **`get_outbound_message_id` + the `email_messages.direction` column** already implement reading back a linked outbound row — the basis for D-13's idempotent already-sent check (no new mechanism).
- **The orchestrator already persists `ERROR` + `error_reason`** on any stage failure — D-13's error path just *surfaces* it on the dashboard + adds the re-trigger claim (no new error-capture machinery).
- **`calculate` → `PaystubLineItem`** is a pure function with all the numbers the PDF needs (gross/OT/leave/401k/FICA/federal/net) — the PDF generator (D-11) is a pure renderer over it.
- **The deterministic resolver's alias READ (`reconcile_names` normalized exact match over `known_aliases`)** already consumes what D-01's write produces — the write side is the only missing half.

### Established Patterns
- **`set_status` as the sole status writer** — D-12 deliberately revises this to two sanctioned writers (`set_status` unguarded + `claim_status` atomic). The invariant doc MUST be updated so the codebase rule stays honest.
- **Pure-function seam** — D-05 (OT rule in `validate.py`) and D-11 (PDF generator) both stay pure (data in, artifact/issues out, no DB) consistent with the project's load-bearing DRY seam.
- **Draft-tier-with-deterministic-floor** — every LLM-drafted email (clarify, now confirmation) degrades to a templated body so a model failure never strands a run. Even more important post-approval.
- **`uv run` for everything; `uv add` for any new dep** — but no new runtime dep is expected; any new dev/test dep goes via `uv add --dev`.
- **Optional `conn=` on repo helpers** — repo functions take an optional connection so a route/orchestrator can share a transaction; `claim_status` (D-12) follows the same convention.

### Integration Points
- **New `app/templates/` + Jinja2 routes** (runs list, run detail, eval view) wired into `app/main.py` (currently a thin webhook + crude JSON approve/reject adapter) — Phase 5 turns it into the operator UI.
- **`claim_status` (new in `repo.py`)** rewires four call sites: `_operator_transition` (approve/reject), `resume_pipeline` (the documented non-atomic seam), the re-trigger route (new), and the initial run claim.
- **The post-approval delivery path is NEW orchestrator work** — after the `awaiting_approval` gate is approved: `compose_confirmation` → generate PDFs (in memory) → `gateway.send_outbound` with attachments → advance `approved → sent → reconciled`, all guarded by the claim + already-sent check.
- **The alias write (D-01)** hooks into the approval handler: read the original-shorthand→resolved-employee mapping (D-04 storage TBD) and idempotently append to `employees.known_aliases` (a new repo write).
- **The eval view** reads committed `eval/summary.json` + `eval/chart.svg` from disk (no DB, no live eval) — a pure render route.
- **The "Send test email" button (DASH-05)** POSTs a committed `fixtures/*.json` demo fixture through the same `/webhook/inbound` path (the deterministic demo trigger + live-email fallback).

</code_context>

<specifics>
## Specific Ideas

- **The alias-write loop is the demo's *third beat* — "clarifies once, then learns."** Beat 1: clean run → approve → confirmation+PDFs. Beat 2: unknown shorthand "David Reyez" → gate clarifies (names the suggested employee). **Beat 3: operator approves the resolved run → the shorthand is learned → a re-run with the same shorthand resolves with NO clarification.** This is the narrative payoff the deterministic-resolution + single-human-gate architecture was built to enable.
- **FOUND-04 literally says `SELECT … FOR UPDATE`; D-12 uses a conditional `UPDATE … WHERE status=? RETURNING` instead.** Both structurally prevent double-approval. The conditional UPDATE is simpler for a single-row status claim (atomic without an explicit transaction block, composes with the optional-`conn=` pattern). Treat FOUND-04's wording as **satisfied-in-spirit, not literally** — and say so in the plan so a reviewer doesn't flag a "missing FOR UPDATE." (If a reviewer insists on the literal `FOR UPDATE`, it's a drop-in swap inside the same helper.)
- **Update the "sole status writer" invariant doc when D-12 lands** — the current `set_status` docstring claims it is "the ONE AND ONLY writer." Leaving that text while adding `claim_status` makes the codebase's own rule a lie. The honest statement: "two writers — `set_status` (unguarded forward transitions inside an owned path) and `claim_status` (atomic guarded claim at every contended gate)."
- **The over-40-no-OT rule is a DEMO beat, not just a guard** — weekly "Bob worked 45 hours" with no OT field on camera, producing "is that 40 regular + 5 overtime, or 45 straight?", visibly catches a money-affecting ambiguity instead of silently under-paying. Under-paying is worse than over-paying for this project's thesis.
- **PDFs per-employee, downloadable per line item, generated in memory** — clicking a line item on the run detail streams that employee's real paystub PDF (reportlab → BytesIO → StreamingResponse). Authenticity beat for anyone who knows payroll; reportlab was chosen for exactly this tabular layout.
- **Reliability over polish on every UI choice** — plain forms + 303 redirects, no JS state, embed the already-committed SVG, no responsive. The dashboard IS the demo surface on a cold Render dyno; nothing should have a JS failure mode on camera.

</specifics>

<deferred>
## Deferred Ideas

- **Seedable before/after eval fixture proving the alias-learning loop** (vs. just demoing it) → **if-time / v2.** D-03 keeps the eval seed-bound and insulated; proving the loop *in* the eval is a dedicated fixture, not a Phase-5 exit-bar item.
- **htmx partial updates / responsive layout** → **out of scope.** Plain forms + a single-screen non-responsive layout is the locked choice (D-06/D-07). Revisit only if the dashboard ever becomes a real product (it's a no-auth demo).
- **Real email provider + Docker/Render/Supabase deploy + keep-alive + README/disclaimer + demo recording** → **Phase 6** (the fixture path Phase 5 builds is unchanged when the provider is wired). The Phase-5 "Send test email" button doubles as the live-email fallback.
- **Full resume-from-arbitrary-status** → **v2.** INGEST-05 is explicitly re-trigger-from-the-START only ("nothing silently hangs"), not mid-pipeline resume.
- **Client-side confirmation step / state withholding / persisted PDFs / dashboard auth** → already **Out of Scope** in PROJECT.md; not reopened.

### Reviewed Todos (not folded)
None — `todo.match-phase 5` returned zero matches; STATE.md "Pending Todos" is empty. (The three `.planning/backlog.md` items were folded into scope via D-01..D-05/D-12/D-13, not via the todo system.)

</deferred>

---

*Phase: 5-Dashboard & Delivery*
*Context gathered: 2026-06-22*
