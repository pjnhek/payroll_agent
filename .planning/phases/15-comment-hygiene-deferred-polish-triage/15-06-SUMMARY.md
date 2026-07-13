---
phase: 15-comment-hygiene-deferred-polish-triage
plan: 06
requirements-completed: [COMM-01, COMM-03]
subsystem: tests
tags: [comment-hygiene, test-naming, D-06, COMM-01, COMM-03]
requires:
  - tests/ (the eight rename-affected test files, as of phase 15 base)
provides:
  - tests/test_alias_and_run_column_regressions.py (renamed regression file)
  - tests/test_reply_classify_union.py (renamed reply-classification file)
  - ticket-free test function names across tests/
affects:
  - plan 15-10 (guard work reads the rename list below)
  - phase 15 verification (gate regex over tests/)
tech-stack:
  added: []
  patterns:
    - "Pure rename proven count-neutral: collect-only count machine-compared against a pre-rename baseline file"
    - "Comment sweep proven behavior-neutral: assert CONDITIONS compared as AST dumps against the prior commit"
key-files:
  created:
    - .planning/phases/15-comment-hygiene-deferred-polish-triage/15-06-SUMMARY.md
  modified:
    - tests/test_alias_and_run_column_regressions.py
    - tests/test_reply_classify_union.py
    - tests/test_resume_pipeline.py
    - tests/test_atomic_persist.py
    - tests/test_compose_email_field_regression.py
    - tests/test_reply_redelivery.py
    - tests/test_retrigger_epoch.py
    - tests/test_multiround_context_edge.py
decisions:
  - "Renamed 32 functions, not the 28 the plan's grep found: test_in03_* (2) and test_n1_/test_n2_ (2) are ticket/plan-note prefixes the plan's narrower regex missed but D-06's stated intent covers. 32 matches 15-RESEARCH's own inventory count."
  - "Deleted 20 '# Test N - <func_name> (TICKET)' banner blocks in test_resume_pipeline.py rather than rewriting them: each restated the def two lines below and cited a review ticket, so there was nothing left to keep."
  - "Interpreted the 'no assert-statement changes' acceptance criterion as 'no assert CONDITION changes': the sweep_rubric explicitly puts failure-message strings in scope, and gate hits lived inside them. Proved conditions unchanged by AST-comparing every assert test against the prior commit (172 in Task 2, 77 in Task 3, all identical)."
metrics:
  duration: ~50m
  completed: 2026-07-13
status: complete
---

# Phase 15 Plan 06: Test-Identity Cleanup (D-06) Summary

Stripped every ticket-ID prefix from test function names, renamed the two ticket-named test
files, and swept the same eight files' comments/docstrings/failure-messages — proven
count-neutral (666 collected before and after) and behavior-neutral (every assert condition
AST-identical).

## What Was Built

**Task 1 — D-06 renames** (commit `dd08741`, rename-only, zero assertion changes):
32 test functions renamed, plus two `git mv` file renames detected by git as R095/R098.

**Task 2 — comment sweep, four files** (commit `053f102`): the two renamed files +
`test_resume_pipeline.py` (the repo's heaviest, 115 gate hits) + `test_atomic_persist.py`.

**Task 3 — comment sweep, remaining four files** (commit `b867e34`):
`test_compose_email_field_regression.py`, `test_reply_redelivery.py`,
`test_retrigger_epoch.py`, `test_multiround_context_edge.py`.

## Count-Neutrality Proof (threat T-15-05)

Baseline written to `/tmp/collect_baseline_15_06` **before** the first rename:

| Checkpoint | Collected | Suite |
|---|---|---|
| Pre-rename baseline | **666** | — |
| After the (single) rename commit `dd08741` | **666** | 615 passed / 51 skipped |
| After Task 3 (plan end) | **666** | 615 passed / 51 skipped |

The renames landed as ONE commit, so the after-every-rename-commit comparison is the single
row above. `uv run ruff check` clean; `uv run mypy` clean (114 source files).

## Function Renames (32) — old → new

Plan 15-10's guard work reads this list.

### tests/test_cr_regressions.py → tests/test_alias_and_run_column_regressions.py
| Old | New |
|---|---|
| `test_cr01_update_known_alias_sql_uses_text_array_ops` | `test_update_known_alias_sql_uses_text_array_ops` |
| `test_cr01_update_known_alias_returns_false_when_alias_absent` | `test_update_known_alias_returns_false_when_alias_absent` |
| `test_cr01_update_known_alias_returns_true_when_row_returned` | `test_update_known_alias_returns_true_when_row_returned` |
| `test_cr02_run_cols_contains_updated_at` | `test_run_cols_contains_updated_at` |
| `test_cr02_load_run_select_includes_updated_at` | `test_load_run_select_includes_updated_at` |
| `test_cr01_run_cols_contains_alias_candidates` | `test_run_cols_contains_alias_candidates` |
| `test_cr01_alias_candidates_roundtrips_through_real_load_run` | `test_alias_candidates_roundtrips_through_real_load_run` |
| `test_cr03_confirmation_subject_with_real_business_name` | `test_confirmation_subject_with_real_business_name` |
| `test_cr03_confirmation_subject_with_pay_period` | `test_confirmation_subject_with_pay_period` |
| `test_cr03_confirmation_subject_fallback_when_empty_dict` | `test_confirmation_subject_fallback_when_empty_dict` |
| `test_cr03_deliver_enriches_run_dict_with_business_name` | `test_deliver_enriches_run_dict_with_business_name` |
| `test_cr03_load_business_name_sql_uses_businesses_table` | `test_load_business_name_sql_uses_businesses_table` |
| `test_clar207_retrigger_clears_all_reply_context` | `test_retrigger_clears_all_reply_context` |
| `test_clar207_retrigger_clears_context_on_stale_inflight_claim` | `test_retrigger_clears_context_on_stale_inflight_claim` |
| `test_clar207_stale_provenance_cannot_reproduce_after_retrigger` | `test_stale_provenance_cannot_reproduce_after_retrigger` |

### tests/test_cr01_classify_union.py → tests/test_reply_classify_union.py
| Old | New |
|---|---|
| `test_cr01_restated_name_classify_resolves_to_correct_employee` | `test_restated_name_classify_resolves_to_correct_employee` |
| `test_cr01_restated_name_zeroed_field_classified_as_confirmed_dropped` | `test_restated_name_zeroed_field_classified_as_confirmed_dropped` |
| `test_wr01_unresolvable_asked_field_added_to_backfill_skip` | `test_unresolvable_asked_field_added_to_backfill_skip` |
| `test_in03_field_regression_lines_skips_malformed_reason` | `test_field_regression_lines_skips_malformed_reason` |
| `test_in03_field_regression_lines_normal_case_still_works` | `test_field_regression_lines_normal_case_still_works` |

### tests/test_resume_pipeline.py
| Old | New |
|---|---|
| `test_n1_single_run_stages_call` | `test_resume_calls_run_stages_exactly_once` |
| `test_n2_asked_written_before_send` | `test_asked_written_before_clarification_send` |
| `test_cr02_round2_new_regression_reaches_awaiting_reply` | `test_round2_new_regression_reaches_awaiting_reply` |
| `test_cr01_explicit_zero_overpay_guard_with_prompt_inspecting_mock` | `test_explicit_zero_overpay_guard_with_prompt_inspecting_mock` |
| `test_cr01_divergence_confirmed_dropped_paystub_value` | `test_extraction_divergence_confirmed_dropped_paystub_value` |
| `test_cr01_divergence_client_supplied_paystub_value` | `test_extraction_divergence_client_supplied_paystub_value` |
| `test_cr01_divergence_unresolvable_asked_money_safe` | `test_extraction_divergence_unresolvable_asked_money_safe` |

### tests/test_atomic_persist.py
| Old | New |
|---|---|
| `test_deliver_finalize_crash_preserves_wr04_payroll_roster_attribute` | `test_deliver_finalize_crash_preserves_payroll_roster_attribute` |

### tests/test_compose_email_field_regression.py
| Old | New |
|---|---|
| `test_field_regression_line_d7509_wording` | `test_field_regression_line_exact_wording_in_template_path` |
| `test_d7509_wording_present_even_when_llm_draft_nonempty` | `test_field_regression_wording_present_even_when_llm_draft_nonempty` |

### tests/test_reply_redelivery.py
| Old | New |
|---|---|
| `test_redelivery_never_resumes_fix5_failed_reply` | `test_redelivery_never_resumes_sender_mismatched_reply` |
| `test_stranded_sweep_never_resumes_fix5_failed_reply` | `test_stranded_sweep_never_resumes_sender_mismatched_reply` |

**Not renamed (deliberate):** `tests/test_bound01_private_imports.py` — BOUND-01 is a
requirements-traceability ID, not a review ticket. Domain vocabulary kept throughout:
`round0`/`round2` (clarification rounds), `epoch`, `resume`, `divergence`.

## Repo-Wide Reference Check (review LOW finding)

Before the `git mv`, searched the **entire repo** excluding `.git` and `.planning` — covering
`.github/` (all workflows and configs), `pyproject.toml`, `README.md`, `AGENTS.md`,
`CLAUDE.md`, `scripts/`, `eval/`, and `tests/` itself:

- refs to `test_cr_regressions` / `test_cr01_classify_union` → **zero hits** (including
  in-file self-references), so no call site needed updating in the rename commit.
- refs to any renamed function name outside `tests/` → **zero hits**.
- Re-verified post-rename: still zero.

CI workflows reference test FILES, not function names, and neither renamed file appears in
`deploy-migrate.yml` or `concurrency-proof.yml`.

## Behavior-Neutrality Proof (threat T-15-04)

The sweep_rubric puts failure-message strings in scope, and gate hits lived inside assert
messages — so the sweep necessarily edits assert *message* text. To prove no assert
*condition* changed, every `ast.Assert.test` node was dumped and compared against the prior
commit:

| Commit | File | Assert conditions | Result |
|---|---|---|---|
| `053f102` | test_alias_and_run_column_regressions.py | 39 | identical |
| `053f102` | test_reply_classify_union.py | 17 | identical |
| `053f102` | test_resume_pipeline.py | 82 | identical |
| `053f102` | test_atomic_persist.py | 34 | identical |
| `b867e34` | test_compose_email_field_regression.py | 12 | identical |
| `b867e34` | test_reply_redelivery.py | 27 | identical |
| `b867e34` | test_retrigger_epoch.py | 17 | identical |
| `b867e34` | test_multiround_context_edge.py | 21 | identical |

The Task 1 rename commit is separately clean: zero `assert`-bearing lines in its diff.

## Sweep Character

Comments were not merely stripped — the constraint each guard protects was rewritten as plain
English naming the concrete failure it prevents. Examples:

- explicit-zero overpay guard: now explains *why* it needs a dedicated guard
  (`_is_paid(Decimal('0'))` is False, so an explicit zero is indistinguishable from silence by
  value alone — only the outcome label separates them) and why `confirmed_dropped` and
  `carried_forward` land in deliberately different sets.
- retrigger epoch module: now states the two stale rows that survive a reset and what each
  corrupts (a silently-never-sent clarification; a mispay from a re-injected consumed reply).
- extraction-divergence tests: now say the combined body legitimately contains both values, so
  classify must never read it — and that fixing the classify LABEL is not the same as fixing
  the PAID VALUE, which is why label and value are asserted separately.

## Deviations from Plan

### Auto-fixed / judgment calls

**1. [Rule 2 - Scope completeness] Renamed 4 functions the plan's grep did not match**
- **Found during:** Task 1 enumeration
- **Issue:** The plan's detection grep (`cr[0-9]|wr[0-9]|cx[0-9]|fix[0-9]|gap[0-9]|d7509|clar207`)
  found 28 functions, but 15-RESEARCH's inventory says 32. The gap: `test_in03_*` (2, an
  internal-review ticket ID) and `test_n1_`/`test_n2_` (2, plan-note IDs). Both are ticket
  prefixes under D-06's stated intent ("No test function name embeds a ticket-ID prefix");
  the regex was simply narrower than the rule.
- **Fix:** Renamed all 4. Total 32 — matching 15-RESEARCH's own count.
- **Files:** `tests/test_reply_classify_union.py`, `tests/test_resume_pipeline.py`
- **Commit:** `dd08741`

**2. [Rule 3 - Rubric application] Deleted 20 provenance banner blocks rather than rewriting**
- **Found during:** Task 2 sweep of `test_resume_pipeline.py`
- **Issue:** 20 identical 3-line blocks of the form `# Test N — test_foo (TICKET)`. Each
  restated the function name defined two lines below and cited a ticket. Under D-01 ("keep
  constraint, drop label") there was no constraint to keep — the whole block was label.
- **Fix:** Deleted all 20 (mechanically, with a leftover-check assertion). Ruff clean after.
- **Commit:** `053f102`

**3. [Judgment] Read "no assert-statement changes" as "no assert-condition changes"**
- **Found during:** Task 2 planning
- **Issue:** The task acceptance criteria say "No assert-statement changes in the commit diff",
  but the sweep_rubric explicitly says "Failure-message strings are in scope", and gate hits
  genuinely lived inside assert messages. A literal reading makes the task unsatisfiable.
- **Fix:** Treated assert *conditions* as the neutrality invariant and proved it by AST
  comparison (table above). Assert *messages* were rewritten as the rubric requires. The
  rename commit satisfies the literal criterion too (zero assert lines in its diff).

**Also swept beyond the plan's gate regex** (same D-03 intent, regex too narrow to catch):
`D-A1-03`, `SC1`/`SC4`, `IN-01`/`IN-03`, `N1`–`N8`, `R3-1`–`R3-3`, `Finding 4`/`Finding 8`,
`BLOCKER FIX`, `CLAR2-07`, `Test 18`/`Test 19` inline message prefixes.

No architectural changes. No package installs. No Rule 4 checkpoints.

## Threat Flags

None. This plan touches test comments and test function names only — no network endpoints,
auth paths, file access patterns, or schema changes. The one security-relevant *comment* edit
(the sender-mismatch redelivery guard in `test_reply_redelivery.py`) strengthened the stated
rationale ("resuming it would let an outsider drive another business's payroll") without
touching the assertion.

## Known Stubs

None.

## Self-Check: PASSED

- `tests/test_alias_and_run_column_regressions.py` — FOUND
- `tests/test_reply_classify_union.py` — FOUND
- `tests/test_cr_regressions.py` — absent (correct; renamed)
- `tests/test_cr01_classify_union.py` — absent (correct; renamed)
- Commit `dd08741` — FOUND (`git log --diff-filter=R` shows R095/R098 rename detection)
- Commit `053f102` — FOUND
- Commit `b867e34` — FOUND
- Collected-test count 666 = baseline 666
- `uv run pytest -q` → 615 passed, 51 skipped
- `uv run ruff check` → clean
- `uv run mypy` → clean (114 source files)
- Gate regex over all eight post-rename files → zero hits
