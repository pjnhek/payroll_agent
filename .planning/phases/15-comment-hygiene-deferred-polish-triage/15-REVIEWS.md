---
phase: 15
reviewers: [codex]
review_rounds: 3
reviewed_at: 2026-07-13T00:00:00Z
plans_reviewed: [15-01-PLAN.md, 15-02-PLAN.md, 15-03-PLAN.md, 15-04-PLAN.md, 15-05-PLAN.md, 15-06-PLAN.md, 15-07-PLAN.md, 15-08-PLAN.md, 15-09-PLAN.md, 15-10-PLAN.md, 15-11-PLAN.md]
reviewers_attempted: [codex, cursor]
reviewers_failed:
  cursor: "Authentication required (agent login / CURSOR_API_KEY not set)"
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

## Codex Review — Round 2 (2026-07-13) — HISTORICAL

> Status: Round-2 verdict was NOT READY on 4 findings. All four were incorporated at commit `de5783c` and re-verified by Codex in Round 3 below (all VERIFIED CLOSED). Kept for provenance; the CURRENT actionable set is Round 3.

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

### Round-2 Actionable Findings (all now CLOSED — see Round 3)
1. **HIGH — WR-01's "real persistence" proof tests the fake repo.**
2. **MEDIUM — WR-05 test setup likely breaks template loading** (`monkeypatch.chdir` vs the relative Jinja searchpath).
3. **MEDIUM — crash-seeding fallback** proves recovery-from-state, not crash-produces-state.
4. **LOW — guard zero-FP evaluation needs a machine-readable record** (`EDITORIAL_ONLY_PATTERNS` + synthetic exclusion test).

---

## Codex Review — Round 3 (2026-07-13) — CURRENT

> Confirming pass on **the fix** (post-`de5783c`, 11 plans). Codex re-verified each Round-2 disposition against live source, then did a fresh adversarial pass looking for defects introduced *by the revision itself*. It was also given the CI-vacuity constraint discovered during replanning (see below) and told to scrutinize it hardest.

### Round-2 Disposition Table

| Finding | Disposition | Evidence |
|---|---|---|
| 1. WR-01 tested the fake repository | **VERIFIED CLOSED** | Revised plan separates the hermetic test from the production SQL proof (`15-01-PLAN.md:49-60`). The fixture does patch `insert_email_message` (`tests/conftest.py:972-1027`), and the new integration test is forbidden from using `fake_repo`, calling production repo functions directly (`15-01-PLAN.md:321-338`). |
| 2. WR-05 test broke template loading | **VERIFIED CLOSED** | Hazard is real: relative loader at `app/routes/templating.py:9-11`, relative data paths at `app/routes/dashboard.py:112-123`. Revised plan removes `chdir`, hoists paths to monkeypatchable constants, redirects only those (`15-11-PLAN.md:127-159`). |
| 3. Crash proof allowed seeded ERROR state | **VERIFIED CLOSED** | One-shot failure now mandatory after `send_outbound`, before clarification persistence (`15-01-PLAN.md:152-170`) — matches real production ordering (`app/pipeline/clarification.py:456-477`); orchestrator catches and persists ERROR (`app/pipeline/orchestrator.py:208-234`). |
| 4. Zero-FP guard was unenforceable | **VERIFIED CLOSED** | Named `EDITORIAL_ONLY_PATTERNS` table + synthetic exclusion test + emitted machine-readable record (`15-10-PLAN.md:120-139`, `:172-182`). |
| **CI-vacuity constraint** (found during replanning, not by any review) | **VERIFIED CLOSED** | Workflow does select only one file (`concurrency-proof.yml:50-53`); normal CI job has no DB vars (`ci.yml:55-58`). Revised plan changes the real-Postgres run line to name both files and retain `-m integration` (`15-01-PLAN.md:415-427`). **If that edit is omitted, the specified run-line grep fails.** |

### New Concerns

#### MEDIUM — "Byte-for-byte unchanged" is not actually tested

The plan repeatedly claims the historical row is byte-for-byte unchanged (`15-01-PLAN.md:18`, `:307-313`), but the proposed SQL read-back selects only `message_id, round, epoch, send_state` (`15-01-PLAN.md:349-353`). It would not detect mutation of `in_reply_to`, `references_header`, `subject`, `body_text`, addresses, or timestamps. **The core append/no-clobber proof is still valid, but the wording overclaims the assertion surface.**

#### LOW — The CI check proves selection wiring, not execution outcome

The workflow run line will correctly select the new module, and its environment satisfies the two-factor guard. But the acceptance check is text-based (a grep) and does not require CI output to show the integration tests *executed* rather than *skipped*. Partially addressed by the required non-skipped local run (`15-01-PLAN.md:365-368`). The acknowledged push-to-master/not-PR limitation is accurate and correctly documented (`15-01-PLAN.md:429-434`).

### Suggestions
- Expand the integration `SELECT` to include all audit-relevant columns, **or** rename the claim from "byte-for-byte unchanged" to "identity and lifecycle fields unchanged."
- Assert the new epoch-1 row's `send_state` and `message_id` explicitly.
- In the CI verification, require a nonzero executed-test count or a post-run assertion that no selected integration test was skipped.

### Verdict

**READY**

> All four Round-2 findings and the CI-vacuity constraint are substantively closed in the revised plans. The remaining issues are assertion-strength and CI-observability improvements, not a recurrence of the prior vacuity or fake-repository defect.

---

## Consensus Summary

Single-reviewer confirming round (Codex; Cursor was attempted but is unauthenticated). **Round-3 verdict: READY.** The phase is executable as planned.

### Current Actionable Findings (Round 3) — both non-blocking

1. **MEDIUM — the "byte-for-byte unchanged" claim exceeds the proof.** The integration test's read-back selects only 4 columns, so it cannot detect mutation of `in_reply_to`, `references_header`, `subject`, `body_text`, addresses, or timestamps. This is the *same class of defect* the whole phase has been fighting — a claim stronger than its evidence — so it should be fixed rather than accepted. Fix: either widen the `SELECT` to the audit-relevant columns, or narrow the wording to "identity and lifecycle fields unchanged."
2. **LOW — the CI acceptance criterion greps the workflow text, proving *selection*, not *execution*.** A run where both integration tests silently skip would still satisfy the grep. Fix: assert a nonzero executed-test count (or no-skips) in the CI/verification step, not just that the path appears in the run line.

### Verified Closed (Round 2 → Round 3)
All four Round-2 findings — the `fake_repo` persistence contradiction (HIGH), the `chdir`/Jinja template break (MEDIUM), the crash-seeding fallback (MEDIUM), and the narrative guard rule (LOW) — plus the CI-vacuity constraint surfaced during replanning. No regressions introduced by the revision.

### Divergent Views
None — single reviewer this round.
