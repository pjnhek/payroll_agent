# Phase 7.5 — Clarification-Reply Field-Regression (MONEY-03)

**Created:** 2026-06-27 (re-scoped out of Phase 7)
**Status:** Not yet planned — start with `/gsd-discuss-phase 7.5` then `/gsd-plan-phase 7.5`
**Requirement:** MONEY-03

## Why this phase exists

MONEY-03 (clarification-reply field-regression: detect a dropped money field → clarify once →
carry forward or honor an explicit removal) was originally Phase 7's third success criterion. It
went through a full plan → verify → execute-ready cycle PLUS **three independent Codex cross-AI
review rounds**. Each round found real, source-verified money-path bugs in the same place: the
`resume_pipeline` / `_run_stages` orchestration surgery.

The root cause (07-REVIEWS.md round 3, R3-1, verified against `orchestrator.py:277-289`):
**`_run_stages` is one indivisible side-effecting unit** — it persists `extracted_data`, decides,
computes line items, sets status, and may clarify, all before it returns. MONEY-03's carry-forward
backfill must run *between* reconcile and validate/decide/calc, but a `StageResult`-returning
function alone can't provide that seam — the function still branches internally, so any
post-return backfill is too late (the non-backfilled paystub is already computed and awaiting
approval → silent underpay survives).

MONEY-01 and MONEY-02 are self-contained pure-function fixes with no such dependency, so they
shipped as Phase 7. MONEY-03 was split out to get the foundation it actually needs.

## The plan for 7.5

**Plan A (foundation, FIRST — land + regression-test BEFORE any feature code):**
Split `_run_stages` into `(a) extract + reconcile` and `(b) validate + decide + persist + branch`,
returning a structured result, so a carry-forward backfill can be injected between (a) and (b).
Update `run_pipeline` and `resume_pipeline`; pin their current behavior with the existing
orchestrator/clarify/persistence suites BEFORE touching field-regression logic.

**Plans B+ (the feature, on the clean split):**
Detection (`detect_field_regression` + `validate(prior=, prior_matches=, resolved_drops=)` +
`decide` Rule 2b) → two-inbound state machine (snapshot-once, `clarified_fields` outcomes,
`purpose="clarification_field_regression"`, asked-before-send) → eval fixtures + integration tests.

## Inputs (READ THESE when planning 7.5)

- `07.5-03-PLAN.seed.md`, `07.5-04-PLAN.seed.md`, `07.5-05-PLAN.seed.md` — the three MONEY-03
  plans as they stood at the end of Phase 7's third review round. They contain a large amount of
  **verified, correct** design (the two-inbound architecture, `RawFieldDrop`, the constraint
  migration, the `_is_paid`/`resolved_drops` predicate, N4/N5/N7/N8 fixes) — reuse them. But they
  also still carry the **R3-1/R3-2/R3-3 HIGH bugs** (post-return backfill, mixed-issue clarification
  gap, build-diff-by-submitted_name). Plan 7.5 must fix those via the split refactor + the
  round-3 guidance, NOT re-adopt them verbatim. Treat the seeds as design input, not as final plans.
- `../07-money-correctness-deepening/07-CONTEXT.md` — the 30 locked decisions D-01..D-30. D-08..D-30
  are the MONEY-03 design (still valid in spirit); D-20's single-call ordering and the
  qualified-field trick are SUPERSEDED (see CONTEXT Deferred Ideas + the seeds). The accepted
  second-order-drop and N6 Round-1 no-op scope limitations are documented there too.
- `../07-money-correctness-deepening/07-REVIEWS.md` — **the most important input.** Rounds 1, 2, 3
  with the orchestrator's source-verification tables. This is the full record of what's hard about
  this feature and exactly which bugs to avoid. Round 3's "New Concerns" + Risk Assessment name the
  split-`_run_stages` fix directly.
- `../07-money-correctness-deepening/07-RESEARCH.md`, `07-PATTERNS.md`, `07-VALIDATION.md` — the
  code anchors, analog patterns, and test map. Largely reusable (line numbers may have drifted —
  re-verify against live source, which is the whole lesson of this phase).
- Phase 7's shipped code: Plan 01 lands the `field_regression` ValidationIssue Literal value and the
  `FieldDrop`/`RawFieldDrop` models as forward-compatible scaffolding; Plan 02 lands `_is_paid`.
  7.5 builds on both — confirm they exist before re-adding.

## The discipline that paid off here

Every Codex finding in all three rounds was VERIFIED against live source before being trusted —
several times the review's reasoning was right but its suggested line/mechanism needed checking,
and once the review caught a bug the orchestrator itself had introduced. Re-verify against the
actual code when planning 7.5; the recurring lesson of this thread is that plan-text reasoning
about `_run_stages` drifts from what the function actually does.
