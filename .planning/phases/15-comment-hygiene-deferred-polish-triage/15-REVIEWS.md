---
phase: 15
reviewers: [codex]
review_rounds: 2
reviewed_at: 2026-07-13T15:43:29Z
plans_reviewed: [15-01-PLAN.md, 15-02-PLAN.md, 15-03-PLAN.md, 15-04-PLAN.md, 15-05-PLAN.md, 15-06-PLAN.md, 15-07-PLAN.md, 15-08-PLAN.md, 15-09-PLAN.md, 15-10-PLAN.md]
---

# Cross-AI Plan Review — Phase 15

## Codex Review — Round 1 (2026-07-11) — HISTORICAL

> Status: all Round-1 findings were incorporated/dispositioned at commit `1bd0dbb` and verified by the plan checker. Round 2 below re-verified each disposition against the revised plans. Kept for provenance; the CURRENT actionable set is Round 2.


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


---

## Codex Review — Round 2 (2026-07-13) — CURRENT

> Confirming review of the revised plans (post-1bd0dbb). Codex received its Round-1 findings and verified each disposition against plan text + live repo, then did a fresh pass.

## Round-1 Disposition Table

| Finding | Disposition | Evidence |
|---|---|---|
| WR-01 test did not require the real retrigger route/pipeline | **PARTIALLY CLOSED** | Plan 15-01 now mandates `POST /runs/{run_id}/retrigger`, synchronous background execution, and captured plus persisted assertions. However, it still permits directly seeding the post-crash state rather than exercising an actual post-send crash. |
| `app/templates/eval.html` omitted from sweep | **VERIFIED CLOSED** | Plan 15-09 includes `eval.html`; it also adds `runs_list.html`, which the revised manifest found. |
| Guard covered only part of D-03 cleanup policy | **VERIFIED CLOSED** | Plan 15-10 requires evaluating UI-SPEC, UAT, HIGH, Codex, finding, planning-document, OPS, and task-ID patterns, adding zero-false-positive patterns to the guard and documenting exclusions. |
| 15-01 fallback weakened D-10 | **VERIFIED CLOSED** | The fallback is explicitly withdrawn. Recovery must use the real POST route and background pipeline; lower-level seams are allowed only for setup. |
| Provider-boundary masking | **PARTIALLY CLOSED** | The plan now requires a real `send_outbound` wrapper and persisted-row assertions. However, the mandated `fake_repo` fixture replaces `app.db.repo.insert_email_message` with `InMemoryRepo.insert_email_message` at `tests/conftest.py:972-1027`. Thus the test does not exercise the production SQL persistence seam. |
| 15-09 scope was too large | **PARTIALLY CLOSED** | The plan documents and accepts the 36-file scope, with per-task gates and a final straggler pass. The risk is mitigated but not removed; it remains a large mechanically edited batch. |
| Inventory counts were stale | **VERIFIED CLOSED** | Plans 15-02 through 15-09 now require fresh manifests before editing; 15-06 also adds an exact collection-count baseline. |
| File renames lacked broad reference checks | **VERIFIED CLOSED** | Plan 15-06 requires a repository-wide search across CI, tooling, docs, scripts, and tests before `git mv`, plus collection-count verification. |

## New Concerns

### MEDIUM — The WR-05 regression test will likely break template loading

Plan 15-01 instructs the test to call `monkeypatch.chdir(tmp_path)` and then `GET /eval`. The route reads relative paths as intended at `app/routes/dashboard.py:112-123`, but the shared template loader is also relative:

```python
templates = Jinja2Templates(directory="app/templates")
```

at `app/routes/templating.py:5`.

After changing to `tmp_path`, rendering `eval.html` may search for `tmp_path/app/templates/eval.html` and raise `TemplateNotFound`. The plan should either patch the template loader to an absolute repository path, patch only the dashboard file paths, or construct the test with a controlled absolute template configuration.

### HIGH — The revised WR-01 “real persistence” proof still tests the fake persistence implementation

The plan says not to stub `insert_email_message`, but its required fixtures do exactly that indirectly:

- `tests/conftest.py:992` includes `"insert_email_message"` in the fake-repo patch list.
- `tests/conftest.py:1027` replaces the production repository function.
- `tests/conftest.py:709+` implements a separate in-memory epoch/upsert algorithm.

Consequently, the test can prove that the route and gateway call the fake repository correctly, but not that the production `(run_id, purpose, round, epoch)` SQL arbiter preserves the historical row. The plan should explicitly choose one of:

- a real local-Postgres integration test for the persistence assertion; or
- state that the test proves route/gateway threading only, while existing SQL tests separately prove the arbiter.

The current acceptance language overstates what the test demonstrates.

### MEDIUM — The “crash → retrigger” proof still allows no crash to occur

Plan 15-01 permits directly seeding `ERROR` plus a sent outbound row as setup. That proves recovery from a durable state, but not that a post-send crash produces that state or that the actual failure boundary preserves it. Since the review specifically emphasized crash behavior, the preferred injected post-send failure should be mandatory, with direct state seeding retained only as a narrowly documented fallback if the production crash setup is impossible.

### LOW — Guard enforcement remains dependent on manual interpretation of “zero false positives”

Plan 15-10 says every extended pattern with zero false positives should be added, while excluded patterns should be documented. This is reasonable, but the acceptance criterion does not require a machine-readable record of the corpus scan or an explicit assertion for each excluded pattern. A future executor could satisfy the wording with a narrative claim. Require the guard module to contain an explicit `EDITORIAL_ONLY_PATTERNS` constant and a synthetic test for those exclusions.

## Suggestions

- Change the WR-05 test setup to preserve the repository’s template path while redirecting only `summary.json` and fixture reads.
- Split WR-01 into:
  1. a route/background hermetic test using `fake_repo`, and
  2. a real-Postgres persistence test proving the epoch arbiter and durable headers.
- Make the post-send failure injection mandatory for WR-01, or rename the test’s claim from “crash” to “durable recovery state.”
- Require the final guard summary to record the exact extended regex, scanned file count, and excluded-pattern list.

## Verdict

**NOT READY**

The revision genuinely closes most Round-1 findings, especially route wiring, sweep inventory, guard breadth, and rename safety. However, the WR-01 proof still conflicts with its own anti-vacuous requirements because `fake_repo` replaces the production persistence function, and the proposed WR-05 test setup is likely incompatible with the relative Jinja template loader. These should be resolved before execution.

---

## Consensus Summary

Single-reviewer confirming round (Codex). Round-2 verdict: **NOT READY** — two findings must be resolved before execution.

### Current Actionable Findings (Round 2)
1. **HIGH — WR-01's "real persistence" proof tests the fake repo:** the mandated `fake_repo` fixture patches `insert_email_message` (`tests/conftest.py:992`, `:1027`) with an in-memory epoch/upsert reimplementation (`:709+`), so the test proves route/gateway behavior against the fake, not the production `(run_id, purpose, round, epoch)` SQL arbiter. Either split into (a) hermetic route/threading test + (b) real-Postgres persistence test, or narrow the acceptance language to what the hermetic test actually proves and lean on existing SQL arbiter tests.
2. **MEDIUM — WR-05 test setup likely breaks template loading:** `monkeypatch.chdir(tmp_path)` + `GET /eval` will make the relative `Jinja2Templates(directory="app/templates")` (`app/routes/templating.py:5`) raise `TemplateNotFound`. Patch only the dashboard file paths or use an absolute template config.
3. **MEDIUM — crash-seeding fallback:** direct ERROR-state seeding proves recovery-from-state, not crash-produces-state; make post-send failure injection the mandatory path (seeding only as documented fallback).
4. **LOW — guard zero-FP evaluation needs a machine-readable record:** require an `EDITORIAL_ONLY_PATTERNS` constant in the guard module plus a synthetic test for exclusions, so a narrative claim can't satisfy the criterion.

### Verified Closed (Round 1 → Round 2)
eval.html/runs_list.html inventory closure, guard vocabulary expansion, 15-01 fallback withdrawal, fresh-manifest rule, rename reference checks. Partially closed: provider-boundary (subsumed by finding 1), crash realism (finding 3), 15-09 scope (accepted risk, documented).
