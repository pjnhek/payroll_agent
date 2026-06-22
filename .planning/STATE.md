---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
last_updated: "2026-06-22T23:11:31.943Z"
last_activity: 2026-06-22 -- Phase 05 planning complete
progress:
  total_phases: 7
  completed_phases: 5
  total_plans: 26
  completed_plans: 19
  percent: 71
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-20)

**Core value:** A messy real-world payroll email goes in; a correct, human-approved payroll comes out — every name-match and process-vs-clarify call is made deterministically by code (no confidence guessing), so a name the system can't resolve never reaches a real payroll calculation.
**Current focus:** Phase 5 — dashboard & delivery

## Current Position

Phase: 5
Plan: Not started
Status: Ready to execute
Last activity: 2026-06-22 -- Phase 05 planning complete

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**

- Total plans completed: 28
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

## Accumulated Context

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

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None yet.

### Blockers/Concerns

[Issues that affect future work]

- [Phase 3]: Confirm 2026 Pub 15-T bracket tables + Step-1 standard amounts against the live IRS PDF before coding — any number from memory is stale (research flag; LOW confidence on the numbers until transcribed).
- [Phase 2]: Confirm exact non-reasoning model IDs against the consoles (DeepSeek/Kimi) and pin versioned IDs for reproducibility (research flag).
- [Phase 6]: Real gateway payload shape, signing-secret verification, and reply-only field are unknown until the provider is picked (research flag).
- [Phase 02.1 P03 — Task 3 CHECKPOINT]: Apply the live-DB name_matches DROP on local + Supabase (uv run python -m app.db.bootstrap) and remove DECISION_MODEL/DECISION_BASE_URL/DECISION_API_KEY from the local .env. Bootstrap CODE is committed; the live execution + .env edit are the blocking human-verify gate.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260621-11x | Fix order-dependent test test_no_db_connection_needed + add close_pool() for clean pool shutdown (IN-04) | 2026-06-21 | dc7ce86 | [260621-11x-fix-order-dependent-test-test-no-db-conn](./quick/260621-11x-fix-order-dependent-test-test-no-db-conn/) |

### Build-time guidance (author review at roadmap lock — pull these forward, do not let them sit in the last phase)

- **[Pull forward from P6 — threading round-trip] The one assumption fixtures structurally CANNOT test.** The EMAIL-01 stub always preserves Message-ID/In-Reply-To/References because we control them, so CLAR-02's resume looks bulletproof through P5 and only meets reality in P6. Real providers/mail apps vary in whether they surface those headers cleanly in the inbound webhook payload; if the provider drops or rewrites them, the resume path collapses onto brittle subject-line matching. **Action:** the moment the provider is picked (same moment as model-ID confirmation, before P2 ideally), send ONE real email, reply to it, and confirm the headers arrive intact. ~30 min; retires a last-phase landmine.
- **[Pull forward from P6 — deploy path] Prove Render+Supabase early.** P6 is otherwise the first time anything touches Render + Supabase-from-Render + the `$PORT` bind + cold-start-vs-inbound-webhook. **Action:** do a hello-world deploy during P1/P2 (just the webhook returning 200 and reading from Supabase via the pooler) so the deploy path is proven while there's slack. Leaves the fixture path unchanged.
- **[P3 — golden-test independence] The oracle must not be computed from the tables it checks.** If CALC-06's golden values are derived from the same transcribed `tax_tables_2026` module, a transcription error makes code and test wrong in the same direction and they tie out — the CALC-08 trap recreated in the oracle. **Action:** hand-compute golden paystubs from the IRS worksheet, or cross-check against an independent payroll calculator / the IRS's own worked examples, so the oracle is genuinely independent of the tables.
- **[P2 — internal sequencing] 19 reqs is the heaviest phase; "skeleton" hides that it's 18 thin pieces integrated.** Sequence INSIDE the phase: (a) clean happy path end-to-end first (POST fixture → all-clean match → process → thin calc → done — this alone lands the one-third end-to-end proof), then (b) the gate-block case, then (c) the clarify-reply-resume loop LAST (CLAR-03 re-entrancy is the trickiest sub-piece). The phase exit criteria must name all three behaviors so it can't be called done with resume half-wired.
- **[Slack management] Phase 3 is the safest place to absorb a slip.** The three core eval metrics (extraction, name-reconciliation, decision accuracy) measure the judgment layer and do NOT depend on P3 — only computed-payroll-correctness does. If Pub 15-T runs long, the spine (working slice + thesis metrics) still stands. Absorb schedule slip in P3, not P2 or P4.

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-06-22T22:28:31.149Z
Stopped at: Phase 5 UI-SPEC approved
Resume file: .planning/phases/05-dashboard-delivery/05-UI-SPEC.md
