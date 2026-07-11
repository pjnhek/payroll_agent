---
phase: 15
reviewers: [codex]
reviewed_at: 2026-07-11T18:11:53Z
plans_reviewed: [15-01-PLAN.md, 15-02-PLAN.md, 15-03-PLAN.md, 15-04-PLAN.md, 15-05-PLAN.md, 15-06-PLAN.md, 15-07-PLAN.md, 15-08-PLAN.md, 15-09-PLAN.md, 15-10-PLAN.md]
---

# Cross-AI Plan Review — Phase 15

## Codex Review

## Summary

The plans are unusually thorough and largely grounded in the current architecture. The sanctioned fixes are correctly identified, the sweep is inventory-driven, and the eval regeneration/guard strategy is strong. Overall risk is medium: the main weaknesses are an incomplete sweep inventory, an under-specified end-to-end threading test, and excessive reliance on per-plan grep checks before the final guard exists.

## Strengths

- Plan 15-01 correctly identifies the raw `ValidationError` echo in `app/llm/client.py:167-187`; structured `errors(..., include_input=False)` is an appropriate mitigation.
- The proposed WR-05 containment fix matches the actual vulnerable join at `app/routes/dashboard.py:115-123`; `resolve()` plus `is_relative_to()` is the correct primitive.
- The epoch arbiter is correctly understood. `app/db/repo/emails.py:57-67` distinguishes retries within an epoch from fresh retriggers, while `app/email/gateway.py:240-250` rebuilds the References chain from durable state.
- Plan 15-02 correctly traces fixture-category aggregation through `eval/run_eval.py:486-503` and `:578-596`; the `--check` gate really compares per-category metrics at `:707-764`.
- Plan 15-06’s collection-count baseline is a good defense against accidental pytest name collisions and silent test loss.
- The final provenance guard has the right architecture: reusable scanner, synthetic self-test, live-tree test, and explicit exclusion of its own pattern table.
- The plans preserve important rationale rather than mechanically deleting comments, especially around SQL arbitration, payroll safety, threading, and model-output isolation.

## Concerns

- **HIGH — The end-to-end WR-01 test is not specified tightly enough.**  
  `gateway.send_outbound()` does not itself derive `in_reply_to`; callers provide it at `app/email/gateway.py:255-267`. The plan’s proposed assertion on captured `send_outbound` kwargs could pass merely because the test supplied the original Message-ID, without proving retrigger recovery preserved it. The existing retrigger route explicitly clears reply context and restarts from the original inbound at `app/routes/runs.py:282-296`, so the test must prove the actual route/pipeline reconstructed the correct inbound context.

- **HIGH — The plan’s claimed whole-codebase sweep omits `app/templates/eval.html`.**  
  This file contains project-process references at `app/templates/eval.html:7`, `:77`, and `:85`, including `UI-SPEC` and `UAT #6`. It is within the stated D-05 template scope, but Plan 15-09 lists only `run_detail.html`. The final D-08 guard will not catch all of these strings because `UI-SPEC` and `UAT` are outside its pattern subset.

- **MEDIUM — The guard enforces only a subset of the stated cleanup policy.**  
  D-03 says to remove phase numbers, review rounds, planning-document citations, and secondary process IDs, but the proposed guard only blocks patterns such as `D-*`, `WR-*`, `Phase N`, and `Pitfall #N`. Current examples outside that guard include `HIGH-1-AUTH` and `Codex` references in `app/email/gateway.py:207-235`, and `UI-SPEC`/`UAT` references in `app/templates/eval.html`. Editorial cleanup may remove them, but the permanent guard will not prevent their return.

- **MEDIUM — Plan 15-01’s fallback weakens its own requirement.**  
  The task allows replacing the POST retrigger route with directly calling lower-level seams “if route wiring proves awkward.” That no longer proves crash → operator retrigger → outbound send. Given the explicit D-10 requirement, the fallback should be limited to setup helpers, while the actual retrigger route and background pipeline must remain under test.

- **MEDIUM — The test harness can mask the provider boundary.**  
  `tests/conftest.py:1035-1045` globally replaces `resend.Emails.send` with a no-op. That is fine for hermeticity, but the plan should explicitly assert both the captured gateway arguments and the persisted outbound row/header values after the real gateway function runs. Otherwise it proves only caller arguments, not the durable threading write.

- **MEDIUM — Plan 15-09 has an overly large scope.**  
  It covers 34 files and mixes route, LLM, email, template, CSS, and 16 test files. Even with mechanical edits, this increases merge conflicts and makes it harder to identify accidental executable-line changes. The final guard is a backstop, but it comes after the large change set rather than constraining each batch.

- **LOW — Several plan descriptions rely on stale inventory counts.**  
  The current tree already shows references not reflected in the stated inventory, for example `tests/test_models_contracts.py:1-12` and `tests/test_retrigger_epoch.py:1-25`. Plans do say to re-grep, but each plan should explicitly treat the research counts as sizing only and require a fresh manifest before editing.

- **LOW — Test renames are broader than the requirement.**  
  D-06 requires function-name cleanup, while Plan 15-06 also renames test files. This is reasonable, but it adds git-detection and import/reference risks without materially improving runtime behavior. If retained, the plan should include `rg` over all tooling, editor configs, documentation, and CI—not only workflows and tests.

## Suggestions

- Strengthen WR-01 acceptance criteria to require:

  - actual `POST /runs/{id}/retrigger`;
  - the real background pipeline wrapper;
  - a simulated post-send crash;
  - a real gateway call with only the provider method stubbed;
  - assertions on both captured headers and the persisted new outbound row;
  - proof that the stale outbound row remains unchanged and a new epoch row exists.

- Add `app/templates/eval.html` to Plan 15-09, and run a broader process-reference inventory over all D-05 paths before Plan 15-10.

- Either expand the guard to cover the complete D-03 vocabulary or explicitly narrow the requirement wording. At minimum, consider patterns for `UI-SPEC`, `UAT #`, `Codex`, `HIGH-*`, `MEDIUM`, `finding #`, and planning-document filenames, after checking false positives.

- Make Plan 15-10’s guard run before the straggler cleanup is considered complete, then require a second full-tree scan after all straggler edits.

- Add a mechanical “executable content unchanged” check for comment-only plans, such as comparing AST-normalized code or using a script that rejects changed non-comment tokens. `git diff` inspection is useful but not fully automated.

- Record the exact baseline test count in the plan summary and verify it after every rename batch, not only at Plan 15-06’s beginning and end.

## Risk Assessment

**Overall: MEDIUM.**

The actual code fixes are low-risk and technically appropriate. The principal risks are process completeness and proof quality: the current sweep inventory is demonstrably incomplete, the guard intentionally covers only part of the cleanup policy, and the WR-01 test could become a non-vacuous-looking but insufficient caller-argument test unless it is forced through the actual retrigger route and durable persistence path.

---

## Consensus Summary

Single-reviewer round (Codex only) — no cross-reviewer consensus available; treat the findings below as one grounded external perspective rather than agreed consensus. Codex verified claims against the live tree (132k tokens of repo inspection) and cited file:line evidence throughout.

### Agreed Strengths
N/A (single reviewer). Codex's strongest validations: the WR-05 containment fix targets the real vulnerable join (`app/routes/dashboard.py:115-123`), the epoch arbiter and References-chain rebuild are correctly understood (`app/db/repo/emails.py:57-67`, `app/email/gateway.py:240-250`), and the fixture-category aggregation trace through `eval/run_eval.py` is accurate.

### Agreed Concerns
N/A (single reviewer). Highest-priority findings:
1. **HIGH — WR-01 test under-specified:** asserting captured `send_outbound` kwargs can pass without proving retrigger recovery reconstructed threading from durable state; the test must go through the real `POST /runs/{id}/retrigger` route and pipeline (`app/routes/runs.py:282-296`) and assert the persisted outbound row, not just caller arguments.
2. **HIGH — Sweep inventory incomplete:** `app/templates/eval.html:7,77,85` carries `UI-SPEC`/`UAT #6` process references inside D-05 scope but is absent from plan 15-09's file list, and those strings are outside the D-08 guard subset.
3. **MEDIUM — Guard narrower than policy:** D-03's full vocabulary (`HIGH-1-AUTH`, `Codex`, `UI-SPEC`, `UAT`) is not guard-enforced; editorial cleanup removes them once but nothing prevents their return.
4. **MEDIUM — 15-01's route-wiring fallback** would weaken D-10's end-to-end proof if exercised; fallback should be limited to setup helpers.

### Divergent Views
N/A (single reviewer).
