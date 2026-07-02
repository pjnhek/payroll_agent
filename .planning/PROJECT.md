# Payroll Agent

## What This Is

An email-driven system that automates the weekly payroll intake the builder used to do by hand as a tax analyst. A client business emails its employees' hours; an LLM-driven pipeline reads the email, reconciles the submitted names against the business's roster, decides whether it can process the run or must ask the client a clarifying question, computes the payroll (gross, FICA, real IRS Pub 15-T federal withholding), and routes the result to a single human operator for one approval before the confirmation goes back to the client. Built end-to-end on a free stack so it runs and demos cleanly.

The narrative for the writeup: the manual payroll process from the builder's accounting days, rebuilt as an agentic pipeline — the LLM does the reading and an optional clarification *suggestion*; the name-match and process-vs-clarify decisions are resolved deterministically by code; a human approves only the final payroll before it reaches the client. **Primary audience: hiring managers / recruiters.** Optimize for *visibly works end to end* > *clean 60–90s demo* > *a real, legible eval chart*.

## Core Value

A messy real-world payroll email goes in; a correct, human-approved payroll comes out — and every money-moving judgment call (name match, process-vs-clarify) is **deterministic, auditable decisioning that never guesses, with a human-confirmation learning loop.** Each submitted name resolves against the roster in pure code (exact / stored-alias / none), collisions always clarify, and the LLM never decides — it only reads (extraction) and suggests a likely employee for the clarification email. The learning loop reads stored aliases now; it writes a newly-confirmed alias at the operator-approval gate (Phase 5). If that deterministic decision flow works, everything else is plumbing.

## Current State

**v1.0 — SHIPPED 2026-06-25.** All 7 phases complete (Foundation → Walking Skeleton → Deterministic Decisioning → Harden the Calc → Eval → Dashboard & Delivery → Real Integration & Ship). The full email-driven pipeline runs end-to-end on a free stack, deployed live and demoed.

- **Live:** https://payroll-agent.onrender.com (FastAPI on Render free + Supabase Postgres + Resend email)
- **Demo:** https://www.loom.com/share/b844c3e0a3364a91b114ab892cc41db4
- **Code:** https://github.com/pjnhek/payroll_agent
- **Scale:** ~5 days, 361 commits, ~23K lines Python (71 files), 458 mocked tests green.

Deferred to v2 (see `backlog.md` + STATE.md Deferred Items): real-email A5 threading verification, field-regression clarification ("did you forget the OT?"), paystub YTD columns, eval-chart restyle.

## Current Milestone: v2 — Production Hardening

**Goal:** Take the working v1.0 MVP and make its core money-logic and data layer genuinely production-grade — correct under real, messy, concurrent load, not just the demo path. Backend/logic only (cosmetic items deliberately excluded). Scope was discovered via an adversarial audit (`.planning/v2-hardening-audit.md`); every item traces to a real finding with file:line.

**Target features (three rings):**
- **Money-correctness:** zero-hours silent-$0 gate, unicode (NFC) name normalization, field-regression clarification ("did you forget the OT?").
- **Data integrity:** atomic multi-write transactions (no half-written run state on crash), webhook dedup race fix (Resend redelivery → no duplicate runs), stuck-run recovery (orphaned in-flight runs recoverable).
- **Operability + evidence:** richer PII-safe `error_reason`, hot-path indexes + remove `SELECT *`, and a load/concurrency proof test (N concurrent runs / duplicate webhooks / simultaneous approvals → assert no double-approval, lost-update, duplicate-run, or half-write).

**Out of scope:** custom email domain, eval-chart restyle, Additional Medicare surtax (intentional), SS-straddle proxy (accepted limitation).

## Requirements

### Validated

- **Phase 1 (Thin Foundation), 2026-06-21:** The shared contract substrate exists and is proven by tests — the Postgres schema (6 tables, 11-value `payroll_runs.status` enum, `email_messages.message_id` idempotency UNIQUE), the shared `app/models/` Pydantic v2 contracts imported by both pipeline and eval, and seed data covering 3 businesses / 6 employees across every calc path and name-match case (happy-path + name-mismatch). FOUND-01, FOUND-02, FOUND-03, FOUND-05, FOUND-06. (Live-DB round-trip tests are written and skip-guarded pending Supabase credentials.)

- **Phase 4 (The Eval, the proof), 2026-06-22:** A reproducible offline eval imports and scores the *same* production judgment functions (`reconcile_names → validate → decide → _compute_line_items`) over 15 committed hand-curated fixtures spanning the full name-resolution taxonomy (exact / stored-alias / first-time-alias / typo / collision / unknown) plus field cases (missing/vague hours, buried reply). `eval/run_eval.py` scores the code-owned `final_action` (never the model's raw action), producing the three core metrics (extraction F1, per-NAME reconciliation accuracy, two-level decision accuracy) per category with a confusion matrix; headline `false_process_count=0`. Renders one committed per-category SVG chart (`eval/chart.svg`), guarded by a DB-free `--check` regression gate and the project's first CI workflow (`eval.yml`: hermetic push check + gated live re-record). Optional secondary LLM-as-judge (`eval/judge.py`) and `eval_results` write stub (`--db`) wired but local-only. Verified 4/4; code review found 8 issues, all fixed (commit 744a203). EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05.

- **Phase 5 (Dashboard & Delivery), 2026-06-23:** The operator gate and delivery path are live end-to-end. A 4-page Jinja2 dashboard (no SPA/build step): runs list with live-polling status badges, the DASH-02 *honest gate* run detail (3-column grid — raw cleaned email leftmost | LLM extraction | computed paystubs — with the code-owned decision banner), an eval view, and a demo "Send Test Email" picker across seeded businesses. On the single operator approval, the run advances `approved → sent → reconciled`: `_deliver` composes an LLM-drafted confirmation (deterministic floor on failure) with on-demand in-memory reportlab paystub PDFs (professional stub: company header, earnings w/ hourly rate + OT, deductions reconciling to net, net-pay band — no YTD/check, deferred). Concurrency is gated by an atomic `claim_status` CAS reused across approve/reject/resume/retrigger; sends are purpose-aware idempotent (`uq_email_run_purpose`); failures route to ERROR (retriggerable — nothing silently hangs). The alias WRITE-side learning loop (collision-safe, single-token, capture-time exclusion) persists a confirmed alias at the approval gate. A demo "Simulate client reply" completes the clarify→reply→resume loop through the real reply path. **The thesis held under adversarial test: no reply (off-roster/ambiguous/wrong) can make it process the wrong person — it re-clarifies.** Verified 5/5 must-haves + human UAT approved; 5 code-review rounds converged clean (3→1→1→1→0 findings), all fixed with regression tests; full suite 409 passing. DASH-01..05, HITL-02, HITL-03, CLAR-04, INGEST-05, FOUND-04.

- **Phase 7 (Money-Correctness Deepening), 2026-06-28:** The headline thesis — "never silently pays wrong" — now holds against two messy-input paths in the pure-function judgment layer, fixed via TDD (RED tests first, then GREEN). **MONEY-01:** a shared `_is_paid(v) -> v is not None and v > 0` predicate in `validate.py` replaces the old `any_hours = … is not None` check, so an hourly employee submitted with explicit zero hours (`hours_regular=0`, no others) gates to `request_clarification` instead of shipping a $0 paystub the reconciliation backstop can't catch; salaried-exception and partial-week (`hours_holiday=8`) guards hold. **MONEY-02:** `reconcile_names._norm` is hardened to the double-NFC form `NFC(casefold(NFC(s)))` so visually-identical names in different Unicode normalization forms (e.g. "José" NFC vs NFD) resolve to the same employee; `eval/run_eval.py` now imports that same `_norm as _normalize` (C-4 parity) so the eval scorer can never drift from production normalization. Phase also lands inert forward-compat scaffolding for Phase 7.5 — a widened `ValidationIssue.issue_type` Literal (`+field_regression`) and a `FieldDrop` model — defined but never instantiated/emitted in Phase 7 (scope fence held). *(Scope reduced 2026-06-27: MONEY-03 field-regression moved to Phase 7.5 — its resume state machine needs a `_run_stages` split refactor as a foundation.)* Verified 7/7 must-haves; code review 0 blockers / 3 advisory warnings; full suite 466 passing, 0 regressions. MONEY-01, MONEY-02.

- **Phase 7.5 (Clarification-Reply Field-Regression), 2026-06-28:** **MONEY-03 — the field-regression clarification state machine** ("did you forget the OT?") is live and money-safe. Built on a foundational `_run_stages` split refactor (Plan A, no-op seam landed + regression-tested first) so the carry-forward backfill lands *between* reconcile and validate/decide/calc — the only correct seam, proven across three cross-AI review rounds. The pipeline now: (1) **detects** a dropped money field on the RAW reply via `detect_field_regression` (employee-id-keyed on BOTH prior and current matches, so a restated name survives the diff), called before backfill in the D-7.5-10 three-phase ordering (detect < backfill < validate < calc); (2) **clarifies exactly once** — a two-inbound state machine persists `clarified_fields` with four outcomes (asked / carried_forward / confirmed_dropped / client_supplied) and a classify-first Round-2 path with a `suppress_detection` set that stops any answered field from re-clarifying (no infinite loop); (3) **carries forward or honors removal** — silent reply → original value restored from the write-once `pre_clarify_extracted` snapshot (paystub OT=2); explicit zero → honored as removal, NOT re-backfilled (paystub OT=0, the overpay guard); restated positive → client value used. A live Supabase schema migration added two JSONB columns + the N4 purpose CHECK. **Two real money-path bugs were caught and fixed mid-phase** (a `/gsd-code-review` pass + executor self-fix, both traced against live source): CR-01 (a restated name left an asked field unclassified → snapshot re-fill of a client-zeroed field = *overpay*; fixed by unioning current-roster reconciliation with prior_matches in the classify lookup) and R2-2 (a restated name at Round-1 made backfill miss the snapshot employee → *underpay* OT=0; fixed by also reconciling the snapshot's own names into the backfill lookup). A flagged CR-02 (migration non-atomicity) was verified a false positive — `bootstrap.py` applies `schema.sql` as one `conn.execute()`+one `commit()`, so the `DO $$` DROP+ADD is atomic. Evidence: 15/15 hermetic integration tests in `test_resume_pipeline.py` PASS live (0 skipped), 5 CR-01 unit tests, eval fixtures 16/17/18 + `eval --check` green, four D-7.5-08 provenance badges in `run_detail.html`. Verified 6/6 must-haves; full suite 507 passing (16 unrelated two-factor-guarded skips), 0 regressions. MONEY-03.

- **Phase 8 (Data-Layer Hygiene & Diagnostics), 2026-07-02:** Production failures are now diagnosable from the dashboard/DB without log access, and the project's stated schema-hygiene discipline is restored — the clean baseline Phase 9's transaction surgery builds on. **OPS2-01:** a nullable `payroll_runs.error_detail` column stores a PII-safe, stage-prefixed, truncated exception detail written by a centralized fail-open scrub-before-truncate helper (`_scrub`/`_build_error_detail` in `repo.py` — roster names Unicode-form/mark-aware redacted, emails regex-redacted) wired into all 3 production error boundaries (pipeline `_run`'s own except block after a roster-scope root-fix, `resume_pipeline`, the approve/delivery boundary); `RUN_COLS` returns it and `run_detail.html` renders it autoescaped. **OPS2-02:** the first 3 declared `CREATE INDEX IF NOT EXISTS` statements land the hot-path indexes (`email_messages(run_id, direction, send_state)`, `payroll_runs(created_at DESC)`, `payroll_runs(status)`; `businesses.contact_email` verified covered by its existing UNIQUE constraint, deliberately not duplicated — D-8-09), and `load_all_runs` selects an explicit scalar column list with a `jsonb_typeof`-guarded `employee_count` alias (no `SELECT *`, no JSONB blob over the wire for the list view). Also folded: the dead `needs_clarification` status removed from enum + CHECK (idempotent DO-block swap, todo 260623-06), the WR-02 thread-safe pool singleton, and an end-to-end DB-column→RUN_COLS→template integration test. Live Supabase migration applied + 6-check verified at the 08-03 blocking human checkpoint (schema-before-code deploy order held). Verified 3/3 must-haves; code review: 1 pre-existing Critical (CR-01 `alias_candidates` missing from RUN_COLS — alias-learning WRITE side is a production no-op, tracked for follow-up) + 6 advisory warnings; full suite 515 passing, 0 regressions. OPS2-01, OPS2-02.

### Active

<!-- All hypotheses until shipped and validated. Grouped by capability. -->

**Ingest & threading**
- [ ] Inbound email is parsed and posted to a FastAPI webhook; row stored in `email_messages` with `Message-ID`, `In-Reply-To`, `References`
- [ ] Sender address is matched to `businesses.contact_email`; unknown sender is logged and stopped (never guessed)
- [ ] A clarification reply is routed back to its run via the RFC `In-Reply-To`/`References` header anchor and resumes the pipeline
- [ ] Email gateway sits behind one interface; whole pipeline is developable by POSTing JSON fixtures (provider wired last)

**Extraction & reconciliation (the judgment layer)**
- [ ] LLM extracts structured per-employee entries (name as written, regular/OT/vacation/sick/holiday hours, any 401k change) via JSON mode + Pydantic, retry once on parse failure
- [ ] Deterministic name resolver is the WHOLE matcher — pure code resolves each name as exact / stored-alias / none, with no model call and no confidence score
- [ ] An optional clarification-SUGGESTION call (cheap tier) maps an unresolved name to the likely roster employee for the email copy only — it never feeds the decision
- [ ] Deterministic field validation produces a per-field issues list (presence, sanity bounds, numeric)
- [ ] Deterministic decision: `decide.py` computes `final_action` purely from the resolution facts — unresolved name, run-level collision, or missing required field → `request_clarification`; no model action, no confidence number

**Payroll calculation**
- [ ] Gross pay: hourly × rate with FLSA overtime at 1.5× over 40 hrs/week; salary = annual ÷ pay periods; plus vacation/sick/holiday
- [ ] Pre-tax 401k as a percent of gross
- [ ] FICA: Social Security 6.2% up to the current-year wage base, Medicare 1.45%
- [ ] Federal withholding via the **real IRS Pub 15-T percentage method** (annualized, per filing status)
- [ ] Net pay = gross − pre-tax − FICA − federal
- [ ] Reconciliation check: net + taxes + deductions ties to the run total; drift is flagged

**Human-in-the-loop & delivery**
- [ ] One operator gate: dashboard shows client's submitted data beside computed paystubs + the decision object; operator approves or rejects
- [ ] Clarification emails are LLM-drafted and auto-sent; the confirmation email sends only after operator approval
- [ ] Approved run sends a confirmation email to the client with on-demand-generated paystub PDFs

**Dashboard**
- [ ] Runs list with status badges
- [ ] Run detail: side-by-side submitted vs computed, decision object with reasons, Approve/Reject on a pending run
- [ ] Eval view: latest eval summary + headline metrics + a small chart
- [ ] "Send test email" demo button that fires the whole flow from the page

**Eval (the proof)** — _validated in Phase 4 (2026-06-22)_
- [x] Bootstrap drafting helper (`draft_candidate_emails.py`) prompts a model for messy candidate emails — named honestly as a throwaway aid; the committed fixtures are the source of truth (no train/test leakage)
- [x] 15 email+label fixtures committed to the repo for reproducibility, spanning the full taxonomy (exact/stored-alias/first-time-alias/typo/collision/unknown + missing/vague hours + buried reply)
- [x] Scoring over fixtures: extraction F1/field accuracy, per-category name-reconciliation accuracy, two-level decision accuracy, + optional local LLM-as-judge email quality (`eval/judge.py`)
- [x] Results render as one committed per-category SVG chart (`eval/chart.svg`); `eval_results` write wired as a local-only `--db` stub. _Dashboard rendering of the chart lands in Phase 5._
- [x] Eval runs locally (authoritative) and in GitHub Actions on each push (hermetic `--check`, no live LLM)

**Hosting & ops**
- [ ] FastAPI app containerized in one Dockerfile, deployed as a single Render free web service
- [ ] Supabase Postgres holds all state (it is also the human-in-the-loop checkpoint)
- [ ] GitHub Actions keep-alive pings Supabase so the free project doesn't pause; eval workflow runs on push

### Out of Scope

- **Client-side confirmation step** — operator approval is the only gate; the single-gate story is the narrative. (Open decision #2, resolved.)
- **State withholding** — federal + FICA only, with a clear disclaimer; per-state withholding is genuinely complex and not core to the demo. `state_withholding` column stays nullable for later. (Open decision #3, resolved.)
- **Cached/persisted PDFs + Supabase Storage bucket** — paystubs generate on demand from run data; fits Render's ephemeral filesystem. (Open decision #1, resolved.)
- **Autonomous agent loop / LangGraph** — the path is fixed and controlled; a plain Python workflow with Postgres state is the orchestration.
- **Reasoning models** — non-reasoning chat variants only; over-thinking adds latency and this is not multi-step logic.
- **Tax-compliant production accuracy** — this is an explicitly educational model; the README says so plainly.
- **Auth on the dashboard** — it's a demo.
- **Spreadsheet-attachment parsing** — noted as a "later" stretch in the source plan; deferred from v1.
- **OBBBA tax provisions** — qualified-tips/overtime above-the-line deductions and the expanded 15-line W-4 Step-4(b) worksheet (new in the 2026 Pub 15-T) are explicitly disclaimed in the README; the engine implements the standard percentage method only. (Surfaced by research; resolved.)

## Context

- **Origin:** rebuild of the builder's real manual weekly-payroll intake from their tax-analyst/accounting days. The operator role is the role the builder personally played.
- **Decisioning model (the heart of the design), as shipped in Phase 2.1 — deterministic, no confidence anywhere:**
  1. *Deterministic resolution* (code, no model): each submitted name resolves against the roster as **exact** (unique normalized full_name), **stored-alias** (unique `known_aliases` hit — the READ side of the learning loop), or **none** (no match, typo, first-time nickname, garbled, or ambiguous). Required-field presence, sanity bounds, and arithmetic are likewise pure code. The resolver never guesses.
  2. *LLM judgment* (only where language understanding helps, and only as advisory copy): the **clarification-suggestion** call maps an unresolved name to the likely intended employee so the email is specific ("did you mean David Reyes?"). It is wired strictly AFTER the gate and never feeds the decision (D-21-05). Extraction is the other LLM judgment role.
  3. *The pure decide* (code): `decide.py` computes `final_action` purely from the resolution facts — `request_clarification` on any unresolved name, any run-level collision, or any missing required field. There is no model action to override and no score is read anywhere; the decision is deterministic and auditable.
- **Pipeline stages (9):** ingest/route → extract → name resolve (deterministic) → field validate → decide (pure code) → clarify-path (with the suggestion call) or process-path → operator approval → send → reconciliation check.
- **Model tiering (two tiers — the decision is pure code, so no decision/mid tier):** extraction = DeepSeek (stronger); drafting + the clarification suggestion = Kimi (cheap). One OpenAI-compatible client, base URL/model/key swapped per task.
- **Fixture-first development:** the whole pipeline is built and demoable by POSTing JSON fixtures to the webhook; the real email provider (n8n or a hosted inbound-parse service) is wired **last**, and the "send test email" button is both a demo feature and a live-email fallback. (Open decision #4, resolved.)
- **Render free realities to design around:** web service sleeps after 15 min, cold-starts under a minute, ephemeral filesystem, only inbound HTTP keeps it awake — so the webhook model fits and a polling loop would not.
- **The `status` column IS the orchestration engine** (surfaced by research): `payroll_runs.status` is simultaneously workflow position, durable checkpoint, the HITL gate, and the crash-recovery anchor — this is what cleanly replaces LangGraph. There are **two pause states** (still one *human* gate): `awaiting_reply` (machine pause on the client, resumes at stage 2) and `awaiting_approval` (the single operator gate, resumes at stage 8).
- **The DRY seam (load-bearing):** the four judgment stages are pure importable functions (data in, data out — never `extract(run_id)`); the hard gates live **inside `decide.py`** computing a code-owned `final_action`; the eval imports and scores those exact same functions. This is what makes the eval credible and tests the core thesis. Established early, not refactored to later.
- **Architecture additions** (surfaced by research, both adopted): an explicit `app/pipeline/orchestrator.py` state-machine driver, and a stuck-run/error recovery path (dashboard-visible `error` state + idempotent re-trigger) since an in-process `BackgroundTask` on a sleeping dyno can strand a run mid-stage.

## Constraints

- **Tech stack**: FastAPI in Docker on a Render free web service; Supabase Postgres for all state — chosen to run end-to-end on a free tier and demo cleanly.
- **Models**: Kimi and DeepSeek via OpenAI-compatible clients, non-reasoning chat variants — latency, and the task isn't multi-step reasoning. Model IDs are **config-driven** (env vars + `.env.example` placeholders); real strings pasted from the consoles later. (Open decision #5, resolved.)
- **Email**: a gateway catches inbound mail and posts to the app and sends outbound; threading is anchored on the RFC `Message-ID` header. Written gateway-agnostic behind one small interface.
- **Orchestration**: plain Python workflow, fixed path, state in Postgres — deliberately not an autonomous agent and not LangGraph.
- **Human-in-the-loop**: exactly one gate (operator approves computed payroll before send). Everything before it is automated.
- **Structured LLM calls**: JSON mode + Pydantic schema, one retry on parse failure.
- **Deterministic decisioning**: `decide.py` is pure code over resolution facts (exact / stored-alias / none + run-level collisions + missing fields → `final_action`) — no LLM call, no confidence number. (Phase 2.1 superseded the original 0.8-confidence-gate decision; the LLM is kept for extraction + the clarification suggestion only.)
- **Audience**: hiring-manager / recruiter facing — bias effort toward a rock-solid end-to-end happy-path-plus-name-mismatch flow and a real, legible eval chart over eval exotica.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Operator approval is the only human gate (no client confirm) | Keeps the single-gate narrative clean; one pause/resume state instead of two | — Pending |
| Skip state withholding (federal + FICA only, disclaimed) | Per-state withholding is complex and not core to an educational demo | — Pending |
| Generate paystub PDFs on demand, no storage bucket | Fits Render's ephemeral filesystem; no state to persist | — Pending |
| Gateway-agnostic + fixture-first build sequencing | Decouples the one risky external dependency (inbound email) from everything that proves the system works; "send test email" doubles as demo + fallback | — Pending |
| Config-driven model routing with placeholder IDs | Builder pastes real Kimi/DeepSeek strings from consoles; keeps tiers swappable | — Pending |
| Real IRS Pub 15-T percentage method for federal withholding | Most credible paystub; highest bug risk, so it's an isolated well-tested unit guarded by the reconciliation check | — Pending |
| Deterministic decisioning — resolve each name in pure code (exact / stored-alias / none), collisions always clarify, no confidence number (Phase 2.1, supersedes the original 0.8 threshold) | The "model says process, code blocks at 0.8" hero was not a real state for a well-calibrated model (an uncertain model self-clarifies); a pure resolver is auditable, reproducible, and genuinely never guesses on a money-moving decision | Decided (Phase 2.1) |
| Eval = all 4 metrics over ~15–25 fixtures, one summary chart | Covers the full "judgment" narrative for a recruiter audience while staying achievable; the chart is the proof, not the demo | — Pending |
| Plain Python workflow over LangGraph/agent loop | Path is fixed and controlled; Postgres is the checkpoint for the HITL pause | — Pending |
| Tax basis: 2026 Pub 15-T standard percentage method, disclaim OBBBA | Current-year credibility ($184,500 wage base, 2026 brackets) without OBBBA complexity; engine + eval ground truth share one assumption | — Pending |
| Add explicit `orchestrator.py` + stuck-run/error recovery | Keeps transition logic auditable in one place; a sleeping dyno can strand a run, so recovery is a first-class state, not an afterthought | — Pending |
| Hard gates live inside `decide.py` (not the orchestrator), computing `final_action` | The one placement that lets the eval test the same gated path as production — makes the eval credible and the thesis verifiable | — Pending |
| Operator gate shows the raw cleaned inbound email as the leftmost column (not just extracted vs computed) | Comparing computed paystubs against the LLM's own extraction agrees by construction; the human must verify the LLM's *reading* against what the client actually sent, or extraction errors pass the gate invisibly | — Pending |
| v1 eval uses hand-curated fixtures + a throwaway bootstrap drafting helper (full synthetic generator → v2) | At ~20 fixtures, hand-curation is faster, more realistic, and kills the train/test-leakage critique; the "scales to thousands" generator story isn't realized at demo scale | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-02 after Phase 8 (Data-Layer Hygiene & Diagnostics) complete — OPS2-01/OPS2-02 are live: PII-safe `error_detail` written at all 3 error boundaries and surfaced on the run-detail page, 3 hot-path indexes + explicit-column `load_all_runs` projection, dead `needs_clarification` status removed, live Supabase migration applied at the blocking human checkpoint (schema-before-code order held). Verified 3/3; 515 tests passing, 0 regressions. Known follow-up: pre-existing CR-01 — `alias_candidates` missing from RUN_COLS makes the alias-learning WRITE side a production no-op (see 08-REVIEW.md). Prior: Phase 7.5 (Clarification-Reply Field-Regression) complete 2026-06-28 — MONEY-03 is live: the field-regression clarification state machine detects a dropped money field on the raw reply, clarifies exactly once (four `clarified_fields` outcomes, no re-clarify loop), and carries the original value forward or honors an explicit removal — money-safe (no overpay, no underpay) under restated names, on the `_run_stages` split-refactor seam. Two real money-path bugs (CR-01 overpay, R2-2 underpay) were caught + fixed mid-phase via `/gsd-code-review` + executor self-fix; CR-02 was a verified false positive. Verified 6/6; 507 tests passing (15/15 live integration tests), 0 regressions. Prior v2 phase: Phase 7 (MONEY-01 zero-hours gate, MONEY-02 Unicode NFC normalization), 2026-06-28. Prior milestone: v1.0 SHIPPED 2026-06-25 (all 7 v1 phases, live on Render + Supabase + Resend).*

<!-- Prior footer (v1.0): Last updated 2026-06-23 after Phase 5 (Dashboard & Delivery) complete — the operator gate + delivery path are live end-to-end: a 4-page Jinja2 dashboard (honest 3-column gate, live status polling, demo trigger), single-approval `approved → sent → reconciled` delivery with in-memory reportlab paystubs + idempotent confirmation email, atomic claim_status CAS across all gates, error path that never hangs, and the alias write-side learning loop. Verified 5/5 + human UAT approved; 5 code-review rounds converged clean; 409 tests passing. Prior: Phases 1, 2, 2.1, 3, 4 complete (contract substrate, walking skeleton, deterministic decisioning, penny-accurate Pub 15-T calc, the eval proof). Remaining: Phase 6 — real email provider + Docker/Render/Supabase deploy + README/demo.* -->

