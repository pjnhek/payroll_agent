---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: "Phase 01 shipped — PR #1"
last_updated: "2026-06-21T07:11:02.256Z"
last_activity: 2026-06-21
progress:
  total_phases: 6
  completed_phases: 1
  total_plans: 3
  completed_plans: 3
  percent: 17
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-20)

**Core value:** A messy real-world payroll email goes in; a correct, human-approved payroll comes out — and every LLM judgment call (name match, process-vs-clarify) is gated by code so a low-confidence match can never reach a real payroll calculation.
**Current focus:** Phase 2 — walking skeleton

## Current Position

Phase: 2
Plan: Not started
Status: Phase 01 shipped — PR #1
Last activity: 2026-06-21

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**

- Total plans completed: 3
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 3 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 01-thin-foundation P01 | 22 | 2 tasks | 11 files |
| Phase 01 P03 | 5 | 2 tasks | 3 files |

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

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None yet.

### Blockers/Concerns

[Issues that affect future work]

- [Phase 3]: Confirm 2026 Pub 15-T bracket tables + Step-1 standard amounts against the live IRS PDF before coding — any number from memory is stale (research flag; LOW confidence on the numbers until transcribed).
- [Phase 2]: Confirm exact non-reasoning model IDs against the consoles (DeepSeek/Kimi) and pin versioned IDs for reproducibility (research flag).
- [Phase 6]: Real gateway payload shape, signing-secret verification, and reply-only field are unknown until the provider is picked (research flag).

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

Last session: 2026-06-21T06:19:21.177Z
Stopped at: Completed Phase 01-03-PLAN.md — seed loader + round-trip tests
Resume file: None
