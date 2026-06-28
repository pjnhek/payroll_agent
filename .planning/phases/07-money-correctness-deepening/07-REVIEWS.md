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


═══════════════════════════════════════════════════════════════

# Cross-AI Plan Review — Phase 7 — ROUND 2 (re-review of the redesign)

> Reviewer: **Codex** (codex-cli 0.135.0). Re-review of the review-incorporated plans
> (commit 8b37432). Round 1's 9 findings: **6 CLOSED, 3 PARTIALLY CLOSED**. The redesign
> introduced **6 new HIGH defects** — ALL verified against live source by the orchestrator.
> Verdict: **HIGH risk — Plan 04 needs another revision before execution.**

## Codex Round-2 Review

**Summary**  
The redesign is materially better, but I would not execute it yet. The two-inbound concept is the right direction, and several Round-1 holes are closed on paper. The remaining risk is concentrated in Plan 04: its stated invariants and its task instructions disagree in several places, and those disagreements can still produce duplicate asks, lost backfill, or processing after an answer that was never actually asked.

**Round-1 Findings Status**

1. **PARTIALLY CLOSED** — `post_extract_hook` addresses re-extraction overwrite, but 07-04 Task 3 says to “continue to the existing alias-diff block,” whose current Step B calls `_run_stages` again in `orchestrator.py`; that can re-clobber backfill.

2. **CLOSED** — 07-04 adopts two inbound calls: Round 1 asks and returns; Round 2 processes the answer.

3. **CLOSED** — New purpose `clarification_field_regression` plus repo allowlist avoids the old `purpose="clarification"` idempotency suppression.

4. **STILL OPEN** — 07-04 must-haves say write `clarified_fields="asked"` before send, but Task 3 writes it only after `_run_stages` returns, and `_run_stages` has already called `_clarify`/sent.

5. **PARTIALLY CLOSED** — The sentinel UUID and period-split field trick are removed, but 07-03 still detects/reduces by `submitted_name` and maps via current matches only; it does not prove “same employee_id in both snapshots” per D-11/D-12.

6. **CLOSED** — 07-01 explicitly avoids constructing `Employee(pay_type=None)` and requires a constructible/structurally-unreachable test path.

7. **CLOSED** — 07-05 adds `prior_extracted`, fixture stripping, and `summary.json` regeneration.

8. **CLOSED** — 07-05 stops over-claiming eval NFD proof and scopes fixture 17 honestly unless an accented seeded employee exists.

9. **CLOSED** — 07-05 makes DB-backed integration evidence a phase gate, not an optional skip, though this still relies on the checkpoint being honored.

**New Concerns**

- **HIGH: Plan 04 can still run `_run_stages` twice and overwrite carried-forward values.**  
  07-04 Task 3 says Round 2 calls `_run_stages(... post_extract_hook=backfill)` and then “continue to the existing alias-diff block (STEP A/B/C).” In current `resume_pipeline`, STEP B is another `_run_stages(...)` call. This reintroduces finding #1 unless the alias block is refactored to reuse the already-run result. Cite: 07-04 Task 3 Change C; `app/pipeline/orchestrator.py`.

- **HIGH: The “asked before send” invariant is contradicted by the implementation steps.**  
  07-04 must-have requires `clarified_fields[emp][field]="asked"` before send. Task 3 instead calls `_run_stages`, which calls `_clarify`, which sends, then only afterward re-detects and writes `asked`. A crash after send but before write leaves no durable loop guard. Cite: 07-04 must_haves vs Task 3 Round 1.

- **HIGH: Round 2 explicit-zero handling is logically broken.**  
  07-04 says the hook backfills asked fields, then resolves outcomes by running `detect_field_regression(snapshot, extracted_after_hook)`. After backfill, the drop has disappeared, so the code can no longer distinguish silence from explicit `0`. This violates D-14 and can turn “remove OT” into carried-forward OT. Cite: 07-04 Task 3 Round 2; D-14/D-16.

- **HIGH: Existing DBs will still reject `clarification_field_regression`.**  
  Updating the inline `CREATE TABLE` check and `ADD COLUMN IF NOT EXISTS purpose TEXT CHECK (...)` does not alter the existing `email_messages.purpose` check constraint. Plan 04 needs an explicit drop/re-add constraint migration. Cite: 07-04 Task 1; `app/db/schema.sql`.

- **HIGH: Field-regression emails may not ask the field-regression question.**  
  07-03 keeps regressions out of `Decision.missing_fields`; current `compose_clarification` only falls back to raw `gate_reasons` if there are no unresolved names and no missing fields. If a regression coexists with a normal clarification, the client may never be asked “keep/remove OT,” yet `clarified_fields` can be marked `asked`. Cite: 07-03 Rule 2b; `app/pipeline/compose_email.py`.

- **HIGH: D-11/D-12 employee identity is still not enforced.**  
  07-03 `detect_field_regression` reduces by `submitted_name`, not `employee_id`, and `validate()` maps using only current `matches`. Name clarification, alias learning, or two submitted names for one roster employee can produce phantom/missed drops. Cite: 07-03 Task 1; D-11/D-12.

- **MEDIUM: `_clarify` snapshot timing misses the idempotency path.**  
  07-04 Task 2 says add snapshot writes before both `AWAITING_REPLY` status writes, but current `_clarify` has a third early idempotency `set_status(AWAITING_REPLY)` path. Snapshot-once is not guaranteed on that path. Cite: 07-04 Task 2; `app/pipeline/orchestrator.py`.

- **MEDIUM: `resolved_drops` suppresses MONEY-01 too broadly.**  
  07-03 instructs skipping the whole missing-hours gate if any `(employee_id, field)` is resolved. That can mask a zero-hours employee when only one field was confirmed dropped. It should suppress only the specific resolved field, not the employee-level gate wholesale. Cite: 07-03 Task 1; D-15.

**Suggestions**

1. Refactor `resume_pipeline` into `pre_alias_state → run_stages_once → post_alias_binding`; never fall through to a block that calls `_run_stages` again.

2. Make `_run_stages` return a structured `StageResult(extracted, matches, issues, decision)` so Plan 04 does not re-derive drop state from strings or repeat detection inconsistently.

3. Resolve Round 2 outcomes before mutation: inspect the raw resumed extraction, classify `confirmed_dropped` vs `carried_forward`, then backfill only carried-forward fields.

4. Move field-regression ask-state write into the same orchestration point that calls `_clarify`, or add an outbound intent/outbox state so “asked but never sent” and “sent but not marked asked” are both recoverable.

5. Add an explicit Postgres migration block to replace the existing purpose CHECK constraint.

6. Add field-regression-specific clarification copy and tests proving the sent body asks about the dropped field even when other clarification reasons exist.

**Risk Assessment**  
**HIGH.** The redesign closes several conceptual holes, but Plan 04 still has execution-level contradictions in the money-moving path. The most serious are double `_run_stages`, post-backfill outcome detection, and the `asked` write ordering. Those are not polish issues; they can still cause silent underpay/overpay or a wedged clarification loop.

---

## Orchestrator Verification of Round-2 NEW Findings (against live code)

| # | New Finding | Severity | Verified? | Evidence |
|---|-------------|----------|-----------|----------|
| N1 | Round 2 falls through to the alias-diff block which calls `_run_stages` AGAIN → re-extracts + re-clobbers the backfill (reopens R1 finding #1) | HIGH | **CONFIRMED** | `orchestrator.py:165` — STEP B of the resume alias-diff is a second `_run_stages(combined_email,...)` call after line 91/Round-1; plan says 'continue to the existing alias-diff block' |
| N2 | 'asked' written AFTER `_run_stages` (which already called `_clarify`+sent) → crash-after-send-before-write leaves no durable loop guard; contradicts the must-have | HIGH | **CONFIRMED** | Plan 04 Task 3 orders detect→write after `_run_stages` returns; `_clarify` sends inside `_run_stages` |
| N3 | Outcome classified by re-running detect AFTER the hook backfills → the drop is gone, so silence (carried_forward) vs explicit-0 (confirmed_dropped) is indistinguishable → 'remove OT' becomes carried-forward OT (D-14 violation, OVERPAY) | HIGH | **CONFIRMED (logic)** | Plan 04 Task 3 Round 2: hook backfills asked fields, THEN resolves outcomes via detect on the post-hook Extracted |
| N4 | New `purpose='clarification_field_regression'` rejected on EXISTING DBs — `ADD COLUMN IF NOT EXISTS` is a no-op when the column exists, so the old CHECK constraint survives | HIGH | **CONFIRMED** | `schema.sql:147` inline `CHECK (purpose IN ('clarification','confirmation'))` + `:164-165` ADD-COLUMN also only those two; no DROP/RE-ADD constraint migration |
| N5 | Field-regression line dropped from the email when a normal clarification coexists — `compose_clarification` only falls back to `gate_reasons` when no unresolved_names AND no missing_fields → client never asked 'keep/remove OT' yet `clarified_fields`='asked' → wedged loop | HIGH | **CONFIRMED** | `compose_email.py:93` `if not decision.unresolved_names and not decision.missing_fields` |
| N6 | `detect_field_regression` reduces by `submitted_name` + maps via CURRENT matches only — does not enforce D-11/D-12 'same employee_id in BOTH snapshots'; alias-learning / re-resolution across rounds → phantom/missed drops | HIGH | **CONFIRMED (design)** | Plan 03 Task 1 keys diff by submitted_name; D-11/D-12 require employee_id-in-both |
| N7 | `_clarify` snapshot-write added before only 2 of 3 `AWAITING_REPLY` paths — the idempotency early-return path is missed → snapshot-once not guaranteed there | MEDIUM | **CONFIRMED** | `_clarify` has 3 `set_status(AWAITING_REPLY)`: idempotency (line ~325), collision (~438), normal (~451) |
| N8 | `resolved_drops` skips the WHOLE missing-hours gate for an employee if ANY (emp,field) is resolved → can mask a genuinely zero-hours employee; should suppress only the specific field | MEDIUM | **CONFIRMED (design)** | Plan 03 Task 1 D-15 wording skips `any_hours` at employee level |

**Bottom line:** Round 1 closed the conceptual holes; Round 2 finds Plan 04's TASK INSTRUCTIONS
contradict its own must-have invariants, and the new machinery has real execution-level bugs in
the money path. The three most dangerous: **N1 (double `_run_stages` re-clobbers backfill)**,
**N3 (post-backfill outcome detection can't tell 'remove it' from silence → overpay)**, and
**N4 (existing DBs reject the new purpose → the field-regression clarification can't even be
stored)**. N2/N5 can wedge the clarification loop. A second `--reviews` revision of Plan 03/04 is
warranted, centered on: (a) make `_run_stages` return a StageResult and NEVER fall through to a
second `_run_stages`; (b) classify Round-2 outcomes from the RAW resumed extraction BEFORE any
backfill; (c) an explicit DROP/RE-ADD CHECK-constraint migration; (d) write 'asked' at the same
orchestration point that sends (or an outbox state); (e) ensure the field-regression question
actually reaches the email body; (f) key the diff by resolved employee_id in both snapshots.


═══════════════════════════════════════════════════════════════

# Cross-AI Plan Review — Phase 7 — ROUND 3 (re-review after the StageResult refactor)

> Reviewer: **Codex** (codex-cli 0.135.0). Third pass, on the StageResult-refactor plans
> (commit b8c6b08). Round-2 status: **N1/N4/N5/N7/N8 CLOSED; N2/N3/N6 PARTIALLY CLOSED.**
> Found **3 new/residual HIGH** — the deepest one verified against live `_run_stages`.
> Verdict: **HIGH — still not safe to execute. Root cause: `_run_stages` is still side-effecting.**

## Codex Round-3 Review

**Summary**

Not safe to execute yet. The redesign closes several Round-2 defects on paper, but the StageResult refactor leaves one load-bearing ordering bug: Round 2 still calls side-effecting `_run_stages()` before outcome resolution/backfill, while live `_run_stages()` persists, decides, computes line items, and may clarify before returning. That violates D-16/D-20 and can still silently underpay or loop. Mixed field-regression + normal clarification also falls between the deferred and inline paths.

**Round-2 Findings Status**

- **N1: CLOSED** — Plan 04 requires one `_run_stages` call and reuses `StageResult.matches` for post state. See [07-04-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-04-PLAN.md:29) and [07-04-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-04-PLAN.md:373).
- **N2: PARTIALLY CLOSED** — all-field-regression path writes `asked` before send, but mixed issues still call `_clarify` inline with no durable `asked`. See [07-04-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-04-PLAN.md:297).
- **N3: PARTIALLY CLOSED** — explicit-zero classification is from raw `StageResult.extracted`, but it happens after `_run_stages()` has already branched. See [07-04-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-04-PLAN.md:356).
- **N4: CLOSED** — explicit drop/re-add CHECK migration plus live insert verify are specified. See [07-04-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-04-PLAN.md:156).
- **N5: CLOSED for email body** — unconditional field-regression lines and `rsplit(".", 1)` are specified. See [07-03-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-03-PLAN.md:222).
- **N6: PARTIALLY CLOSED** — `prior_matches` filtering is specified, but the diff is still generated by `submitted_name` first, so same employee under a changed/restated name can be missed before employee-id filtering ever runs. See [07-03-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-03-PLAN.md:142).
- **N7: CLOSED** — all three `_clarify` AWAITING_REPLY paths get snapshot writes. See [07-04-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-04-PLAN.md:291).
- **N8: CLOSED** — suppression is scoped to `(employee_id, field)` for field-regression re-emission, not the employee-level MONEY-01 gate. See [07-03-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-03-PLAN.md:159).

**New Concerns**

- **HIGH: Round-2 backfill is too late because `_run_stages()` is still side-effecting.**  
  Plan 04 keeps existing side effects in `_run_stages()` ([07-04-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-04-PLAN.md:74)), then Round 2 backfills after the call ([07-04-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-04-PLAN.md:356)). Live source persists, validates/decides, computes line items, and sets status inside `_run_stages()` before return ([orchestrator.py](/Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:277)). This violates D-16/D-20, which require backfill before validate/decide/calc ([07-CONTEXT.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-CONTEXT.md:50)). Fix requires splitting `_run_stages` or adding a pre-validate/pre-branch hook, not post-return mutation.

- **HIGH: Mixed field-regression + normal clarification still has no durable `asked`, and may not send at all after a prior normal clarification.**  
  Plan 04 defers only when every issue is `field_regression`; mixed issues call `_clarify(... purpose="clarification")` inline ([07-04-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-04-PLAN.md:302)). The `asked` write only happens after `clarify_deferred=True` ([07-04-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-04-PLAN.md:365)). Existing `_clarify` skips if a sent `purpose="clarification"` row already exists ([orchestrator.py](/Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:318)), so a later mixed clarification after an initial name clarification can be suppressed.

- **HIGH: N6’s employee-id diff is not actually the diff source.**  
  D-11/D-12 require reducing both snapshots by `employee_id` before diffing ([07-CONTEXT.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-CONTEXT.md:43)). Plan 03 first builds raw drops by intersecting `submitted_name` dictionaries ([07-03-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-03-PLAN.md:142)), then filters those by IDs. If `M. Chen` becomes `Maria Chen` but resolves to the same employee, the drop is never produced.

- **MEDIUM: Alias-diff refactor under-specifies the misname guard data shape.**  
  Plan 04 replaces post-run DB reconciliation with `StageResult.matches` only for `_post_resolved_ids` ([07-04-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/07-money-correctness-deepening/07-04-PLAN.md:373)). Live alias binding also needs `_post_reconciliation` with `submitted_name` for the token-must-match guard ([orchestrator.py](/Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:200)). The plan should explicitly convert `StageResult.matches` or rewrite that guard over model objects.

**Risk Assessment**

**HIGH.** MONEY-01/MONEY-02 and several N-fixes are solid, but MONEY-03 is still unsafe because the Round-2 carry-forward path mutates after `_run_stages()` has already processed. The mixed-issue path also violates “clarify once” and durable loop-guard semantics. The next revision should split `_run_stages` into extract/reconcile/validate/decide vs branch, or make Round-2 outcome resolution/backfill happen before validate/decide/calc.

---

## Orchestrator Verification of Round-3 Findings (against live code)

| # | Finding | Severity | Verified? | Evidence |
|---|---------|----------|-----------|----------|
| R3-1 | **Backfill is too late**: the round-2 plan calls `_run_stages` then backfills into the returned `stage_result.extracted` — but `_run_stages` ALREADY persisted the non-backfilled extracted, computed line items from the non-backfilled OT, and set AWAITING_APPROVAL, all BEFORE returning. Post-return mutation drives nothing → silent underpay survives (violates D-16/D-20). | HIGH | **CONFIRMED** | `orchestrator.py:277-289` — persist_extracted/decision/reconciliation then branch (process→compute_line_items+replace_line_items+AWAITING_APPROVAL, else _clarify) ALL inside the call before return. The StageResult refactor made it RETURN data but did NOT move the branch out, so a post-extract hook placed AFTER the call cannot precede validate/decide/calc. |
| R3-2 | **Mixed field-regression + normal clarification** falls between paths: clarify_deferred is True only when ALL issues are field_regression; a mixed decision calls _clarify inline with purpose='clarification' and writes NO durable 'asked'; and a later mixed clarification after an earlier normal one can be SUPPRESSED by the existing purpose='clarification' idempotency guard. | HIGH | **CONFIRMED** | Plan 04 defers only all-field_regression; `orchestrator.py:318` _clarify skips when a purpose='clarification' row exists. The mixed case has no durable loop guard and can silently not-send. |
| R3-3 | **N6 diff is BUILT by submitted_name, then filtered by id** — so a same-employee drop under a restated name (e.g. 'M. Chen' → 'Maria Chen', both resolving to the same employee) is never PRODUCED as a raw drop, so the employee_id filter never sees it. D-11/D-12 require reducing BOTH snapshots by employee_id BEFORE diffing. | HIGH | **CONFIRMED (design)** | Plan 03 builds {submitted_name: emp} dicts and intersects by name first; the employee_id check is a post-filter, not the diff key. |
| R3-4 | Alias-diff refactor under-specifies the misname guard: it derives _post_resolved_ids from StageResult.matches but the existing token-must-match misname guard (orchestrator.py:200) also needs post-reconciliation with submitted_name. | MEDIUM | **CONFIRMED** | `orchestrator.py:200` token guard reads submitted_name from reconciliation; plan only maps ids. |

**Bottom line (round 3):** The StageResult refactor correctly fixed N1 (single call) and the
verify/test gaps, but it did NOT address the ROOT structural problem Codex named in round 2 —
`_run_stages` PERSISTS + BRANCHES internally. Returning a StageResult is necessary but not
sufficient: the carry-forward backfill MUST happen BETWEEN reconcile and validate/decide/calc,
INSIDE the stage path — not as a post-return mutation. The genuine fix is to SPLIT `_run_stages`
into (a) extract+reconcile and (b) validate+decide+persist+branch, so Round-2 resolution+backfill
slots between them. The mixed-issue clarification path (R3-2) and the build-diff-by-name (R3-3)
are real correctness holes too. This is the THIRD external pass finding real money-path bugs in
the same orchestrator surgery — a strong signal the MONEY-03 state machine needs the split-pipeline
refactor as its foundation, and is worth re-scoping rather than patching a 4th time in place.
