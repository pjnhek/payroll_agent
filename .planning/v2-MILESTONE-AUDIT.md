---
milestone: v2
milestone_name: Production Hardening
audited: 2026-07-07
status: passed
scores:
  requirements: 13/13
  phases: 6/6
  integration: 5/5
  flows: 3/3
gaps:
  requirements: []
  integration: []
  flows: []
tech_debt:
  - phase: 10-concurrency-proof
    items:
      - "10-VALIDATION.md is stale: frontmatter status: draft, nyquist_compliant: false, wave_0_complete: false — never flipped post-execution. Not a real coverage gap: the phase's VERIFICATION.md passed 9/9, and its integration proof is CI-only by design (D-10-04), so wave-0 local sampling of the integration test structurally cannot complete locally. Optionally run /gsd-validate-phase 10 to reconcile the doc."
  - phase: 07.5-clarification-reply-field-regression
    items:
      - "No 07.5-VALIDATION.md (decimal regression-fix phase; VERIFICATION.md passed). Nyquist discovery flag only, non-blocking."
  - phase: 11-clarification-round-machine-alias-learning
    items:
      - "Cosmetic: insert_email_message docstring SUMMARY line (app/db/repo.py:1100) narrates the legacy 3-column ON CONFLICT arbiter; the authoritative docstring paragraph (:1122-1134) and executed SQL (:1152) both use the correct 4-column (run_id, purpose, round, epoch) arbiter matching the live constraint. Behavior correct; stale comment only."
nyquist:
  compliant_phases: [07, 08, 09, 11]
  partial_phases: [10]
  missing_phases: ["07.5"]
  overall: partial
---

# v2 — Production Hardening — Milestone Audit

**Status: PASSED** · Audited 2026-07-07

**Goal (from ROADMAP):** Take the working v1.0 MVP and make its core money-logic and
data layer genuinely production-grade — correct under real, messy, concurrent load,
not just the demo path. Scope discovered via an adversarial audit; every phase closes
concrete findings with file:line.

## Scores

| Dimension | Score |
|-----------|-------|
| Requirements satisfied | 13 / 13 |
| Phases verified (`passed`) | 6 / 6 |
| Cross-phase integration seams WIRED | 5 / 5 |
| End-to-end flows complete | 3 / 3 |

No critical blockers. No unsatisfied requirements. No orphaned requirements. No broken flows.

## Requirements Coverage (3-source cross-reference)

Each requirement was cross-checked against three independent sources: the REQUIREMENTS.md
traceability table (`[x]`/Complete), the phase VERIFICATION.md (`passed`), and the phase
SUMMARY.md `requirements-completed` frontmatter. All three agree for every requirement.

| REQ-ID | Phase | Traceability | VERIFICATION | SUMMARY frontmatter | Final |
|--------|-------|--------------|--------------|---------------------|-------|
| MONEY-01 | 7 | [x] | passed | listed | satisfied |
| MONEY-02 | 7 | [x] | passed | listed | satisfied |
| MONEY-03 | 7.5 | [x] | passed | listed | satisfied |
| OPS2-01 | 8 | [x] | passed | listed | satisfied |
| OPS2-02 | 8 | [x] | passed | listed | satisfied |
| DATA-01 | 9 | [x] | passed | listed | satisfied |
| DATA-02 | 9 | [x] | passed | listed | satisfied |
| DATA-03 | 9 | [x] | passed | listed | satisfied |
| OPS2-03 | 10 | [x] | passed | listed | satisfied |
| CLAR2-01 | 11 | [x] | passed | listed | satisfied |
| CLAR2-02 | 11 | [x] | passed | listed | satisfied |
| CLAR2-03 | 11 | [x] | passed | listed | satisfied |
| CLAR2-04 | 11 | [x] | passed | listed | satisfied |
| CLAR2-05 | 11 | [x] | passed | listed | satisfied |
| CLAR2-06 | 11 | [x] | passed | listed | satisfied |
| CLAR2-07 | 11 | [x] | passed | listed | satisfied |

## Phase Verification Summary

| Phase | Name | Plans | VERIFICATION |
|-------|------|-------|--------------|
| 07 | money-correctness-deepening | 2/2 | passed |
| 07.5 | clarification-reply-field-regression | 4/4 | passed |
| 08 | data-layer-hygiene-diagnostics | 3/3 | passed |
| 09 | atomic-data-integrity | 6/6 | passed |
| 10 | concurrency-proof | 2/2 | passed (incl. gap-closure 10-02 for code-review CR-01) |
| 11 | clarification-round-machine-alias-learning | 9/9 | passed |

## Cross-Phase Integration (5/5 WIRED)

Traced live against `app/` source by the integration checker — not from docs.

1. **`_run_stages` refactor (7.5) shared by first-run + both resume rounds, composed with DATA-01 atomic wrapping (9).** Single shared spine (`orchestrator.py:1086`), persist+branch+status commits atomically in one `with conn.transaction()` (`:1189-1197`). [MONEY-03 + DATA-01] — WIRED
2. **DATA-02 dedup CAS + Phase 10 proof reference the SAME seams.** The proof calls the shipped `repo.insert_inbound_email`/`create_run` and the real `/approve` CAS — no parallel copy. [DATA-02 + OPS2-03] — WIRED
3. **Phase 11 round machine composes with Phase 9 recovery + Phase 8 status/index model.** `needs_operator` is a human-gate correctly excluded from all three recovery scopes (sweep / retrigger / reply-sweep); retrigger's `clear_reply_context` + `reply_epoch` bump genuinely hides stale round/candidate state; the `(run_id, purpose, round, epoch)` ON CONFLICT arbiter matches `uq_email_run_purpose_round_epoch`. [CLAR2-01..07 + DATA-03] — WIRED
4. **End-to-end status state machine — no unhandled transition.** 11 statuses incl. `needs_operator` in schema CHECK + enum (drift-tested); reply to a `needs_operator` run correctly falls to `late_reply` (waits for operator); round cap escapes to `needs_operator` before any provider call; `/reject` and `/resolve` both accept `needs_operator`. — WIRED
5. **Alias learning (CLAR2-04) write side in `_deliver` behind the operator gate, composed atomically with DATA-01.** Bind on confirmation → `_write_aliases_if_safe` inside the finalize txn as a nested SAVEPOINT before `set_status(SENT)`; already-sent retry re-runs the idempotent alias write. No half-written alias, no unlearned-but-sent case. [CLAR2-04 + DATA-01] — WIRED

## End-to-End Flows (3/3 COMPLETE)

- **(A) Happy path:** clean email → extract → all-clear reconcile → compute → `awaiting_approval` → `/approve` CAS → `_deliver` → sent → reconciled. COMPLETE
- **(B) Clarify-resume incl. 3-round cap:** mismatch → clarify → reply → resume (shared `_run_stages`) → round counter advances per send → cap escapes to `needs_operator` → operator `/resolve` (with overrides) or `/reject`. COMPLETE
- **(C) Concurrency:** duplicate webhooks → one run (ON CONFLICT); concurrent approvals → one `_deliver` (CAS). Proven by `tests/test_concurrency_proof.py` against real Postgres under genuine parallelism. COMPLETE

## Nyquist Compliance Discovery (non-blocking)

| Phase | VALIDATION.md | nyquist_compliant | Action |
|-------|---------------|-------------------|--------|
| 07 | exists | true | — |
| 07.5 | missing | — | decimal regression-fix phase; VERIFICATION passed. Optional. |
| 08 | exists | true | — |
| 09 | exists | true | — |
| 10 | exists | false (stale draft) | `/gsd-validate-phase 10` to reconcile the doc — real coverage is fine (VERIFICATION 9/9; proof is CI-only by design) |
| 11 | exists | true | — |

## Tech Debt (deferred, non-blocking)

- **Phase 10:** `10-VALIDATION.md` stale (never flipped from pre-execution draft). Real coverage is sound; only the doc lags.
- **Phase 07.5:** no VALIDATION.md (decimal phase).
- **Phase 11:** cosmetic stale docstring summary line at `app/db/repo.py:1100` (SQL + authoritative docstring are correct).
- **Backlog (5 pending todos):** all low/medium v2/post-demo polish — Phase 05 deferred code-review warnings, frontend progressive enhancement, paystub YTD columns, eval-chart restyle, a Fixture 10 category-label note. None block the milestone.

## Verdict

v2 — Production Hardening achieved its definition of done. All 13 requirements are
satisfied across 6 verified phases; the phases wire together correctly (5/5 seams,
traced live); all 3 end-to-end flows complete. The milestone's headline claim —
"correct under real, messy, concurrent load, not just the demo path" — is backed by
the Phase 10 concurrency proof (genuine parallelism after the CR-01 gap-closure) and
the Phase 9 atomic/dedup/recovery work it validates. The only outstanding items are
documentation-staleness and low-priority polish, none of which gate milestone
completion.
