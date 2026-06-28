---
phase: 7
reviewers: [codex]
reviewed_at: 2026-06-28T00:10:39Z
plans_reviewed: [07-01-PLAN.md, 07-02-PLAN.md, 07-03-PLAN.md, 07-04-PLAN.md, 07-05-PLAN.md]
verdict: HIGH risk — revise Plan 03/04/05 before execution
---

# Cross-AI Plan Review — Phase 7

> Reviewer: **Codex** (codex-cli 0.135.0, default model). Independent adversarial read of the
> 5 plans after the internal plan-checker had passed them. Several HIGH findings were
> cross-verified against the live orchestrator/repo/models by the orchestrator and **confirmed**.

## Codex Review

## Summary

Plans 07-01 and 07-02 are mostly sound for MONEY-01 and MONEY-02, but the set does **not** safely achieve Phase 7 as written. MONEY-03 is the load-bearing feature, and Plan 04’s state-machine design has several correctness holes that can either skip the second clarification, process before the client answers, or lose the carried-forward value before calculation. I would not execute these plans without revising Plan 03/04/05.

## Strengths

- The `_is_paid(v is not None and v > 0)` predicate is the right shared boundary for MONEY-01 and MONEY-03.
- NFC normalization plus eval `_normalize` parity is correctly identified.
- `ValidationIssue.issue_type="field_regression"` plus a `decide.py` Rule 2b is the right resolution to the live-code contradiction.
- Snapshot-once via `WHERE pre_clarify_extracted IS NULL RETURNING id` is the right storage primitive.
- The D-23 split is conceptually right: eval proves pure judgment; integration tests prove the resume state machine.

## Concerns

- **HIGH: Plan 04 processes too early after sending the field-regression clarification.**  
  In Plan 04 Task 2b, first `_run_stages(prior=snapshot)` can call `_clarify()` and set `AWAITING_REPLY`, but the same `resume_pipeline()` call then proceeds to resolve outcomes and run `_run_stages(prior=None)` again. That collapses “ask the client once” and “handle the client’s answer” into one call. For original `40 + 2 OT`, reply `40`, the system must ask “did you forget OT?” and return, not immediately carry forward/process before the client answers.

- **HIGH: `clarified_fields["asked"]` is never actually written.**  
  Plan 04 Task 2a only adds `set_pre_clarify_extracted()` in `_clarify()`. No step writes `clarified_fields={employee_id: {field: "asked"}}` before sending the field-regression clarification. Task 2b then checks the preloaded `clarified` dict, which is stale and likely `{}`. The core loop guard has no durable “asked” state.

- **HIGH: Carry-forward can be overwritten by the second `_run_stages()` pass.**  
  Task 2b backfills `extracted`, calls `repo.persist_extracted()`, then calls `_run_stages()` again. `_run_stages()` re-extracts from the same email and overwrites `extracted_data`, losing the backfilled OT before calc. That reintroduces the silent underpay MONEY-03 exists to prevent.

- **HIGH: `prior=None` is too blunt as the termination mechanism.**  
  Passing `prior=None` on pass 2 suppresses all field-regression detection, not just the one resolved drop. A reply could newly drop another money field, and the second pass would process it silently. Termination should filter only resolved `(employee_id, field)` drops, while still detecting new unresolved drops.

- **HIGH: Existing `_clarify()` idempotency likely blocks the second clarification email.**  
  `_clarify()` checks `get_outbound_message_id(run_id, purpose="clarification")` and skips sending if one already exists. MONEY-03 necessarily happens after a prior clarification, so the “did you forget OT?” email may never be sent. The plan needs a clarification generation/fingerprint/purpose distinction.

- **HIGH: The `detect_field_regression()` qualified-field trick is fragile and violates D-11/D-12.**  
  Encoding `"{submitted_name}.{field}"` breaks for names with periods, e.g. seeded aliases like `D. Reyes`; `split(".", 1)` would recover submitted name `"D"`. More importantly, the helper keys by `submitted_name`, not resolved `employee_id`, so it does not satisfy D-11/D-12’s “same employee_id in both snapshots” rule.

- **HIGH: Plan 04 outcome resolution lacks the data it says it will use.**  
  `_run_stages()` returns only `extracted`, but Task 2b needs current matches/reconciliation to map drops to employee IDs. The plan handwaves “from matches persisted to DB or mapping,” but does not specify a reliable implementation. This should be a concrete `StageResult(extracted, matches, issues, decision)` or a split pipeline.

- **MEDIUM: `resolved_drops` only addresses MONEY-01, not field-regression suppression.**  
  A `confirmed_dropped` field must suppress both the zero-hours gate and repeated field-regression issues for that exact pair. The current plan relies on `prior=None` for the latter, which is unsafe.

- **MEDIUM: Some RED tests fail for the wrong reason.**  
  Plan 01 explicitly accepts `ImportError` for `detect_field_regression` as RED. That is weak TDD for money logic. Add stubs or write tests after symbol creation so failures are behavioral assertions. Also `pay_type=None` is not constructible with the current `Employee.pay_type` Literal, so that test will fail during setup unless redesigned.

- **MEDIUM: Plan 05 eval fixture work is incomplete.**  
  `eval/run_eval.py` currently has no `prior_extracted` support, `_load_fixture()` strips only `expected` and `fixture_category`, and adding fixtures makes `--check` fail unless `summary.json` is regenerated. Plan 05 must include `eval/run_eval.py` and likely `eval/summary.json`/chart updates.

- **MEDIUM: The NFD eval fixture is not concrete.**  
  Seed data appears to have no accented names. The plan’s fallback to a whitespace-only fixture would not prove MONEY-02. Either add an accented seeded employee intentionally, or keep MONEY-02 proof as a unit test and do not claim eval fixture 17 proves NFD matching.

- **MEDIUM: Integration evidence can silently skip.**  
  Plan 05 allows state-machine tests to SKIP without `DATABASE_URL`, while still treating the phase as complete. For D-23, skip is not evidence. Phase completion should require these integration tests to pass in an environment with the new columns applied.

## Suggestions

- Replace Plan 04 Task 2b with a single-pass resume algorithm: extract once, reconcile once, detect drops, then either record `asked` + send clarification + return, or resolve prior `asked` outcomes and continue to calc using the adjusted in-memory `Extracted`.
- Make `_run_stages` return a structured result or split it into `extract/reconcile/validate/decide` and `persist/branch`, so orchestration can insert drop resolution before persistence and calc without re-extracting.
- Replace the `FieldDrop` sentinel/qualified-field trick with either `RawFieldDrop(submitted_name, field, ...)` internally, or pass prior/current name-match maps into detection so `FieldDrop.employee_id` is always real.
- Add support for multiple clarification sends per run, keyed by generation or issue fingerprint, while preserving idempotency for duplicate sends of the same clarification.
- Move real integration tests into Plan 04 before/with the state-machine wiring, and make them assert exact statuses after each resume.
- Update `run_eval.py` explicitly for `prior_extracted`, fixture stripping, summary regeneration, and `validate(..., prior=...)`.

## Risk Assessment

**Overall risk: HIGH.** MONEY-01 and MONEY-02 are low-risk, but MONEY-03 as planned can still silently underpay, skip the required clarification, or lose the carried-forward value. The loop guard needs a design revision before implementation.

---

## Orchestrator Verification of Codex's HIGH/MEDIUM Findings (against live code)

Checked the most damaging claims against the actual shipped files (Codex reasoned from
plans+research, not the orchestrator source):

| Finding | Severity | Verified? | Evidence in live code |
|---------|----------|-----------|-----------------------|
| `_clarify()` idempotency guard would suppress the 2nd ("did you forget OT?") clarification | HIGH | **CONFIRMED** | `orchestrator.py:318` — `_clarify` skips send if `get_outbound_message_id(run_id, purpose="clarification")` already exists; `repo.py:659` `get_outbound_message_id(run_id, purpose)` has NO fingerprint/generation param |
| Backfill is lost: `_run_stages` re-extracts + `persist_extracted` overwrites `extracted_data` wholesale, so the planned "backfill → persist → 2nd `_run_stages`" blows away the carried-forward value before calc | HIGH | **CONFIRMED** | `orchestrator.py:28–30` docstring + `260–278` — `_run_stages` calls `extract()` then `persist_extracted` (single JSONB cell, overwrite) |
| Process-too-early: `_run_stages` itself calls `_clarify` + pauses at `AWAITING_REPLY`, so resolving outcomes + a 2nd `_run_stages` in ONE `resume_pipeline` call conflates "ask" with "answer" | HIGH | **CONFIRMED** | `orchestrator.py:288` (`_run_stages` → `_clarify` → pause) |
| Qualified-`field` `"{submitted_name}.{field}"` split-on-`.` is fragile for names containing a period | HIGH | **CONFIRMED (hits real seed data)** | `seed.py:83` seeds `known_aliases=["Maria", "M. Chen"]` — a submitted name `M. Chen` → `split(".",1)` recovers `"M"`. (Note: this qualified-field trick was introduced by the orchestrator during the revision loop — Codex caught a defect I added.) |
| `clarified_fields["asked"]` is never written before the clarification send → loop guard has no durable state | HIGH | **CONFIRMED** | Plan 04 Task 2a only adds `set_pre_clarify_extracted`; no `set_clarified_fields(...asked)` precedes the send |
| `prior=None` on pass 2 suppresses ALL field-regression detection, not just the resolved drop → a newly-dropped field on the reply processes silently | HIGH | **CONFIRMED (by design in plan)** | Plan 04 Task 2b step 5 |
| `_run_stages` returns only `extracted`, but outcome-resolution needs `matches` to map drops→employee_id | HIGH | **CONFIRMED** | `orchestrator.py:260` returns nothing structured; plan handwaves the matches source |
| `pay_type=None` not constructible (Literal) → Plan 01 MONEY-01 "unknown pay_type" test setup fails | MEDIUM | **CONFIRMED on roster.Employee** | `roster.py:42` `pay_type: Literal["hourly","salary"]`. (Planner must confirm whether `ExtractedEmployee` allows None — D-03 targets the extracted side.) |
| Eval `run_eval.py` has no `prior_extracted` support; `--check` fails unless `summary.json` regenerated | MEDIUM | Plausible — Plan 05 must include `run_eval.py` + summary regen | (not re-verified line-by-line) |
| Integration tests may SKIP without `DATABASE_URL` yet phase still "complete" | MEDIUM | **CONFIRMED as a real evidence gap** | Plan 05 allows skip; D-23 says skip ≠ evidence |

**Bottom line:** Codex's HIGH findings are real. The MONEY-03 resume design in Plans 03–05
needs a revision before execution — most importantly (a) split "ask once" from "handle the
reply" across two `resume_pipeline` invocations, (b) stop re-extracting on the post-reply pass
(or carry the resolved values in a way `_run_stages` cannot overwrite), (c) drop the
qualified-`field` string trick in favor of a real `employee_id` (or an internal
`RawFieldDrop(submitted_name, ...)`), (d) give the field-regression clarification its own
`purpose`/fingerprint so the idempotency guard doesn't suppress it, and (e) write
`clarified_fields[...]="asked"` durably before sending.

## Consensus / Next Step

Single external reviewer (Codex), so no cross-reviewer consensus — but the orchestrator
independently confirmed the HIGH findings against source, which is stronger than a second
opinion. Recommended: `/gsd-plan-phase 7 --reviews` to replan Plans 03/04/05 incorporating
this feedback. MONEY-01 (Plan 02) and MONEY-02 (Plan 02) are low-risk and largely stand.
