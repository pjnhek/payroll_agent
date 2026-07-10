---
gsd_state_version: 1.0
milestone: v3
milestone_name: — Production-Ready Codebase
current_phase: 14
current_phase_name: full-type-checking-mypy
status: executing
stopped_at: Completed 14-01-PLAN.md
last_updated: "2026-07-10T18:28:22.365Z"
last_activity: 2026-07-10
last_activity_desc: Phase 14 execution started
progress:
  total_phases: 4
  completed_phases: 2
  total_plans: 18
  completed_plans: 10
  percent: 50
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-07 after v2 milestone)

**Core value:** A messy real-world payroll email goes in; a correct, human-approved payroll comes out — every name-match and process-vs-clarify call is made deterministically by code (no confidence guessing). **v3 makes the codebase read as production-quality: enforced CI, right-sized modules, full type-checking, constraint-documenting comments.**
**Current focus:** Phase 14 — full-type-checking-mypy

## Current Position

Phase: 14 (full-type-checking-mypy) — EXECUTING
Plan: 3 of 10
Status: Ready to execute
Last activity: 2026-07-10 — Phase 14 execution started

## Performance Metrics

**Velocity:**

- Total plans completed: 60
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 3 | - | - |
| 02.1 | 5 | - | - |
| 2 | 4 | - | - |
| 03 | 3 | - | - |
| 04 | 4 | - | - |
| 05 | 7 | - | - |
| 07 | 2 | - | - |
| 07.5 | 4 | - | - |
| 08 | 3 | - | - |
| 09 | 6 | - | - |
| 10 | 2 | - | - |
| 12 | 4 | - | - |
| 13 | 4 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 01-thin-foundation P01 | 22 | 2 tasks | 11 files |
| Phase 01 P03 | 5 | 2 tasks | 3 files |
| Phase 02 P01 | 34 | 3 tasks | 14 files |
| Phase 02 P02 | 38 | 4 tasks | 25 files |
| Phase 02 P03 | 24 | 3 tasks | 14 files |
| Phase 02 P04 (Tasks 1-2; Task 3 = human checkpoint) | 8 | 2 of 3 tasks | 6 files |
| Phase 02.1 P01 | 4 | 2 tasks | 3 files |
| Phase 02.1 P02 | 5 | 2 tasks | 5 files |
| Phase 02.1 P03 (Tasks 1-2; Task 3 = human checkpoint) | 7m | 2 of 3 tasks tasks | 12 files files |
| Phase 02.1 P04 | 5m | 2 tasks | 7 files |
| Phase 02.1 P05 | 14min | 3 tasks | 13 files |
| Phase 05-dashboard-delivery P03 | 35 | 3 tasks | 8 files |
| Phase 11 P05 | 50min | 4 tasks | 4 files |
| Phase 11 P07 | 35min | 1 tasks | 2 files |
| Phase 11 P10 | 25min | 1 tasks | 2 files |
| Phase 10 P02 | 25min | 2 tasks | 2 files |
| Phase 12 P04 | 100min | 3 tasks | 1 files |
| Phase 14 P01 | 4 | 3 tasks | 6 files |
| Phase 14 P02 | 10 min | 3 tasks | 12 files |

## Accumulated Context

### Roadmap Evolution

- v3 roadmap created (2026-07-08): 4 phases (12-15), continuing global phase numbering from v2's Phase 11. Phase 12 CI Quality Gates -> Phase 13 Module Structure & Boundaries -> Phase 14 Full Type-Checking (mypy) -> Phase 15 Comment Hygiene & Deferred-Polish Triage. Hard-ordered per the milestone's ordering constraint: CI first (protects every later refactor), STRUCT (incl. BOUND-01) before COMM (comments rewritten once, in final file locations), TYPE its own phase after STRUCT (smaller split modules are easier to annotate; user explicitly ruled out squeezing full mypy adoption into a shared phase). 16/16 v3 requirements mapped, no orphans.
- Phase 11 added (2026-07-05): Clarification Round Machine & Alias Learning — clarify-cluster design phase from phase-9 review findings (WR-04/05/06, CX-01) + conversation-traced findings (alias-learning bind unreachable, ambiguous-reply attribution); sources: todos 260705-01, 260705-02, 260623-08

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: Vertical MVP shape — thin foundation (P1), then walking skeleton as the FIRST end-to-end proof (P2), then deepening rings ordered by risk.
- [Roadmap]: Calc is deliberately thin in P2 (gross + FICA only; federal LEFT OUT; net labeled "pre-federal" — never a fake federal number). Full Pub 15-T penny-accuracy is P3, before any correctness claim.
- [Roadmap]: The DRY seam — judgment stages are pure functions; hard gates live INSIDE `decide.py` computing a code-owned `final_action` that is the SOLE branch source (orchestrator/dashboard/eval never branch on `model_action`).
- [Roadmap]: Operator gate (DASH-02) shows the raw cleaned inbound email as the leftmost column — the honest operator gate.
- [Roadmap]: Drop-if-tight items — EVAL-04 (LLM-judge metric), INGEST-05 (error recovery).
- [Phase ?]: D-10/D-11/Finding#5/FIX-B applied in seed.py: Pydantic validation at import, fixed UUIDs, SS straddle on per-period wages vs remaining wage base, Sandra Kim pay_periods=26
- [Phase ?]: [Phase 2 P01]: D-A3-05 option (a) — dedicated payroll_runs.reconciliation JSONB column (not nested under decision); keeps Decision contract exact + Phase 5 dashboard query clean.
- [Phase ?]: [Phase 2 P01]: repo helpers take optional conn= so the webhook shares a transaction and tests assert SQL offline via a FakeConnection (no live DB needed for parameterized-SQL/serialization/status-write contracts).
- [Phase ?]: [Phase 2 P02]: validate() is pay-type aware via the roster (a pure value) so the missing-hours rule distinguishes hourly (hours required) from salaried (legitimately none) — keeps purity AND the clean path green.
- [Phase ?]: [Phase 2 P02]: the code gate in decide.py uses per-name Decimal('0.8') (never the collapsed min() scalar); check_one_to_one ships empty-but-real for Plan 03 to extend.
- [Phase ?]: [Phase 2 P03]: Layer-2 LLM reconcile is residual-only via the NameReconciliationResponse{matches} wrapper (FIX 6 — model_validate_json needs a BaseModel, not a bare list); a layer-1 hit is never re-decided.
- [Phase ?]: [Phase 2 P03]: check_one_to_one EXTENDED (signature unchanged) into full one-to-one mapping enforcement (two->one emp / dup name / name->no emp); a high-confidence collision still gates (G6).
- [Phase ?]: [Phase 2 P03]: clarify drafts via DRAFT_* call_text (templated fallback), sends via gateway.send_outbound (Message-ID on the outbound email_messages row — single FIX-3 anchor, no payroll_runs column), pauses at awaiting_reply via set_status; one persist_reconciliation covers both branches (D-A3-05).
- [Phase ?]: [Phase 2 P04]: reply routing happens in the webhook BEFORE first ingest, gated on the inbound carrying an in_reply_to/references — find_awaiting_reply_for_header (awaiting_reply only) for resume, FIX-5 sender revalidation against the run's business, find_any_run_for_header for late-reply log (FIX 10); no-header inbounds fall through unchanged.
- [Phase ?]: [Phase 2 P04]: resume_pipeline re-extracts over (original cleaned body via load_source_email + reply body) so a partial reply is lossless (FIX 4 + FIX C), passes the code-owned run_id into extract (FIX A), overwrites extracted_data + replaces line items; the four stages are factored into a shared _run_stages() so first-run and resume share the identical gate path (DRY).
- [Phase ?]: [Phase 2 P04]: the live-vs-mock provenance marker (FIX 12) is a structured LOG field source="live"/"mock" derived from Settings.allow_live_llm — never a key in the extra=forbid Decision and never a schema column (an always-runs guard test pins this).
- [Phase ?]: [Phase 02.1 P01]: Contracts reshaped deterministic — NameMatchResult=source(exact|alias|none)+explicit resolved bool; Decision=final_action/gate_reasons/unresolved_names/missing_fields+resolutions:list[NameMatchResult] (folded into decision JSONB, no name_matches table); PaystubLineItem drops match_confidence; reconcile.py/NameReconciliationResponse deleted. No confidence anywhere (D-21-01/04/05/06).
- [Phase 02.1]: [Phase 02.1 P02]: reconcile_names + decide are now PURE deterministic code — no LLM, no confidence, no model_action; final_action computed from unresolved (resolved is False) + run-level collisions + missing fields is the SOLE branch source (D-21-01/02/03)
- [Phase 02.1]: [Phase 02.1 P02]: collision safety lives in TWO places — deterministic_match refuses to resolve a name matching 2+ employees (None -> unresolved); check_one_to_one stays a run-level authority gating even when both colliding names are resolved=True (D-21-02); decide Rule 1 keys off resolved and the old check_one_to_one no-roster-employee branch was dropped to avoid double-counting Rule 1
- [Phase 02.1]: [Phase 02.1 P03]: orchestrator wired to the pure stages (decide/reconcile called with no llm; no m.confidence stamp; branches solely on final_action); repo INSERT + schema.sql drop match_confidence; bootstrap drops the dead name_matches on EVERY apply (default path + _DROP_ORDER front) for the live-DB migration; config two-tier (extraction+draft), mid/decision tier removed from Settings/client/.env.example (D-21-05/06). Live-DB DROP + human .env edit = PENDING blocking checkpoint (Task 3).
- [Phase 02.1]: [Phase 02.1 P04]: Suggestion-only call (LLM-05/D-21-05) — a cheap draft-tier call maps an unresolved name to the likely roster employee for the clarification email ONLY; wired strictly after decide() inside _clarify, degrades to {} on any failure, structurally walled off from decide (decide never imports suggest; a test asserts the suggested id never leaks into the persisted Decision).
- [Phase 02.1]: [Phase 02.1 P04]: compose_clarification gains suggestions= threaded into BOTH the draft prompt and the deterministic _template_body floor so the 'did you mean David Reyes?' hero survives a total draft failure (WR-03); a suggested name must be an exact roster full_name or it is dropped.
- [Phase ?]: [Phase 02.1 P05]: DEMO-01 reframed deterministic — gate_block_hero = unknown-shorthand 'David Reyez' resolves to source=none -> request_clarification (suggestion call names David Reyes); NEW collision_safety.json + constraint-safe seed pair (Daniel Reyes e0000007 shares 'D. Reyes' alias with David Reyes; DISTINCT full_names so UNIQUE holds). Never guesses on a money-moving decision (D-21-01/02).
- [Phase ?]: [Phase 02.1 P05]: Final sweep — all residual tests on deterministic source/resolved+Decision shapes (no confidence/model_action/match_type/0.8); CLAUDE.md/REQUIREMENTS.md/PROJECT.md/ROADMAP.md rewritten to deterministic auditable decisioning + learning loop (WRITE side P5); eval taxonomy=exact/stored-alias/first-time-alias/typo/collision/unknown. Mocked suite GREEN (195); app/+docs grep-clean. Phase 2.1 COMPLETE.
- [Phase ?]: D-12 closed: claim_status is the second sanctioned status writer; all contended gates use CAS not load-then-set
- [Phase ?]: D-13b: RunStatus.APPROVED removed from _TERMINAL_STATUSES — delivery failure after approval routes to ERROR for retriggering
- [Phase ?]: D-13c sharpened NEW-1: insert_email_message upserts on (run_id, purpose) for outbound rows — retry-over-reserved advances to sent instead of crashing on uq_email_run_purpose
- [Phase ?]: D-05 OT explicit-zero decision: hours_overtime=0 treated same as absent — never silently underpays a weekly employee
- [Phase 11 P05]: clear_reply_context is called ONCE at the retrigger route's single 'if claimed:' post-claim convergence point (reached by both the ERROR/APPROVED CAS and the stale in-flight CAS) rather than duplicated inside each branch — satisfies WR-06/D-11-04 clearing ALL reply-round context (clarified_fields, pre_clarify_extracted, clarification_round, alias_candidates) before _run_pipeline is scheduled.
- [Phase 11 P05]: _row_to_inbound is a pure app.main helper (not repo.py) building an InboundEmail from a persisted email_messages row, reused by both the WR-04 redelivery re-schedule and the D-11-05 stranded auto-resume — never re-cleans a redelivered request body (Pitfall #11a).
- [Phase 11]: Route validates+applies overrides then unconditionally schedules background resume; resume_pipeline is the sole CAS claimer (no route-level pre-claim), matching the webhook reply-resume path
- [Phase 11]: Shared _reply_sender_ok(row, run) predicate re-asserts FIX-5 sender revalidation at both the WR-04 redelivery re-schedule and the D-11-05 stranded-sweep seam (GAP-5/CR-5) — A FIX-5-failed linked reply left unconsumed could otherwise be resumed later via redelivery or dashboard load, bypassing sender auth entirely
- [Phase ?]: Surfaces A and C bypass the async /webhook/inbound route entirely and race repo.insert_inbound_email/repo.create_run directly from barrier-released OS threads (CR-01 fix).
- [Phase ?]: N_INGEST=5 matches the app pool max_size=5 because Surfaces A/C threads are simultaneous connection HOLDERS for the full ingest transaction, unlike Surface B's brief CAS (kept at N_APPROVE=8).
- [Phase ?]: CI schema step drops bootstrap --reset; the seeded_db fixture is the sole reset owner behind its ALLOW_DB_RESET two-factor guard (WR-04).
- [Phase 12 P04]: Master pushed to origin (fast-forward 2eaa5fc..157633d) before the red-proof branches — the plan's assumed prior master ci.yml run did not exist (Rule 3 deviation, covered by push authorization); this triggered the repo's first-ever ci.yml run, green on both jobs
- [Phase 12 P04]: Red-proof injections single-cause by design: one F401 (unused import sys, app/main.py) failed ONLY lint; one broken assertion (test_check_schema_cli.py) failed ONLY test — both locally verified pre-push, human-verified live, branches deleted per D-14 (run history persists)
- [Phase 14]: Phase 14 Plan 01: Keep mypy scope and strictness in committed pyproject.toml config so bare local and CI commands have identical coverage.
- [Phase 14]: Phase 14 Plan 01: Use a narrow _ReceivedEmailLike Protocol plus cast for Resend's ResponseDict runtime attributes; preserve existing attribute access and avoid Any.
- [Phase 14]: Phase 14 Plan 01: Keep the eval import regression fix separate from its RED test, and keep the BracketRow annotation separate from the gateway change.
- [Phase 14]: Repository facade export style remains unchanged after direct mypy measurement found no re-export errors.
- [Phase 14]: Dynamic psycopg row and JSONB boundaries use dict[str, Any], while OpenAI chat messages use ChatCompletionMessageParam.

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

5 pending (see `.planning/todos/pending/`) — all low/medium post-demo polish, carried as Deferred Items (below). The two high-priority design todos that drove Phase 11 (260705-01 alias-learning bind + 260705-02 clarify round machine) are **DONE** — they became Phase 11 (CLAR2-01…07, shipped 2026-07-07). Remaining pending todos: Phase 05 code-review warnings (medium), frontend progressive enhancement, paystub YTD columns, eval-chart restyle, Fixture-10 category-label note (all low).

### Blockers/Concerns

[Issues that affect future work]

_None open._ All v1/v2 research flags and checkpoints were resolved as their phases shipped:

- 2026 Pub 15-T brackets — transcribed + unit-tested against the IRS PDF (Phase 3, v1.0).
- DeepSeek/Kimi model IDs — confirmed + pinned (Phase 2, v1.0).
- Real gateway payload/signing/reply-field — resolved with Resend at deploy (Phase 6, v1.0).
- Phase 02.1 name_matches DROP + `.env` decision-tier removal — applied + human-verified at the blocking checkpoint (v1.0).

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260621-11x | Fix order-dependent test test_no_db_connection_needed + add close_pool() for clean pool shutdown (IN-04) | 2026-06-21 | dc7ce86 | [260621-11x-fix-order-dependent-test-test-no-db-conn](./quick/260621-11x-fix-order-dependent-test-test-no-db-conn/) |
| 260709-uvz | Ignore personal system-design audit files and commit Phase 13 governance artifacts | 2026-07-10 | 56afd4f | [260709-uvz-ignore-personal-system-design-audit-file](./quick/260709-uvz-ignore-personal-system-design-audit-file/) |

### Build-time guidance (author review at roadmap lock — pull these forward, do not let them sit in the last phase)

- **[Pull forward from P6 — threading round-trip] The one assumption fixtures structurally CANNOT test.** The EMAIL-01 stub always preserves Message-ID/In-Reply-To/References because we control them, so CLAR-02's resume looks bulletproof through P5 and only meets reality in P6. Real providers/mail apps vary in whether they surface those headers cleanly in the inbound webhook payload; if the provider drops or rewrites them, the resume path collapses onto brittle subject-line matching. **Action:** the moment the provider is picked (same moment as model-ID confirmation, before P2 ideally), send ONE real email, reply to it, and confirm the headers arrive intact. ~30 min; retires a last-phase landmine.
- **[Pull forward from P6 — deploy path] Prove Render+Supabase early.** P6 is otherwise the first time anything touches Render + Supabase-from-Render + the `$PORT` bind + cold-start-vs-inbound-webhook. **Action:** do a hello-world deploy during P1/P2 (just the webhook returning 200 and reading from Supabase via the pooler) so the deploy path is proven while there's slack. Leaves the fixture path unchanged.
- **[P3 — golden-test independence] The oracle must not be computed from the tables it checks.** If CALC-06's golden values are derived from the same transcribed `tax_tables_2026` module, a transcription error makes code and test wrong in the same direction and they tie out — the CALC-08 trap recreated in the oracle. **Action:** hand-compute golden paystubs from the IRS worksheet, or cross-check against an independent payroll calculator / the IRS's own worked examples, so the oracle is genuinely independent of the tables.
- **[P2 — internal sequencing] 19 reqs is the heaviest phase; "skeleton" hides that it's 18 thin pieces integrated.** Sequence INSIDE the phase: (a) clean happy path end-to-end first (POST fixture → all-clean match → process → thin calc → done — this alone lands the one-third end-to-end proof), then (b) the gate-block case, then (c) the clarify-reply-resume loop LAST (CLAR-03 re-entrancy is the trickiest sub-piece). The phase exit criteria must name all three behaviors so it can't be called done with resume half-wired.
- **[Slack management] Phase 3 is the safest place to absorb a slip.** The three core eval metrics (extraction, name-reconciliation, decision accuracy) measure the judgment layer and do NOT depend on P3 — only computed-payroll-correctness does. If Pub 15-T runs long, the spine (working slice + thesis metrics) still stands. Absorb schedule slip in P3, not P2 or P4.

## Deferred Items

Items acknowledged and deferred at milestone close. All benign — intentional
post-demo polish deferrals + already-passed UATs + one stale pointer; none block a milestone.
The v2 milestone audit (`milestones/v2-MILESTONE-AUDIT.md`) independently dispositioned each
as non-blocking tech debt.

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| quick_task | 260621-11x-fix-order-dependent-test-test-no-db-conn | done (stale pointer) | v1.0 / v2 |
| todo | Phase 05 code-review: deferred Warnings + Info | deferred | v1.0 / v2 |
| todo | Frontend progressive enhancement (no build step) — post-demo polish | deferred | v1.0 / v2 |
| todo | Paystub YTD columns | deferred | v1.0 / v2 |
| todo | Eval chart restyle (away from matplotlib look) | deferred | v1.0 / v2 |
| todo | Fixture 10 category-label vs expected-clarification note | deferred | v1.0 / v2 |
| uat | Phase 03 HUMAN-UAT | passed (no open scenarios) | v1.0 |
| uat | Phase 05 HUMAN-UAT | passed (no open scenarios) | v1.0 |

*These 6 open artifacts (1 quick task + 5 todos) were re-acknowledged and carried forward at the
v2 close (2026-07-07). The 2 UAT "gaps" are scanner false positives — both passed with zero
pending scenarios.*

## Session Continuity

Last session: 2026-07-10T18:27:58.449Z
Stopped at: Completed 14-01-PLAN.md
Resume file: None

## Operator Next Steps

- Discuss the next phase with /gsd-discuss-phase 14 (full mypy)
