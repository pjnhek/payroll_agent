---
phase: 05-dashboard-delivery
plan: "01"
subsystem: tests
tags: [tdd, wave-0, red-stubs, claim_status, alias_write, validate, D-12, D-01b, D-05, CLAR-04]
dependency_graph:
  requires: []
  provides:
    - "Wave 0 RED spec for repo.claim_status CAS helper (FOUND-04/D-12)"
    - "Wave 0 RED spec for _safe_to_learn_alias collision guard (D-01b)"
    - "Wave 0 RED spec for validate() D-05 OT rule (weekly/biweekly/explicit-zero)"
    - "Wave 0 RED stub for _clarify idempotency guard (CLAR-04 finding #2)"
    - "Wave 0 RED stubs for alias capture single-token-only rule (D-04 finding #4/#5)"
  affects:
    - "app/db/repo.py — claim_status to be added in Wave 1"
    - "app/pipeline/reconcile_names.py — _safe_to_learn_alias to be added in Wave 4"
    - "app/pipeline/validate.py — OT rule to be added in Wave 1 Plan 03"
    - "app/pipeline/orchestrator.py — _clarify idempotency to be added in Wave 3"
tech_stack:
  added: []
  patterns:
    - "FakeConnection (from conftest.py) for offline SQL assertion in test_claim_status.py"
    - "Inline Employee/Roster construction for non-seed-business employees in OT tests"
    - "monkeypatch for repo/gateway surface in alias capture stub tests"
key_files:
  created:
    - tests/test_claim_status.py
    - tests/test_alias_write.py
  modified:
    - tests/test_validate.py
decisions:
  - "Used existing FakeConnection from conftest.py (import, not duplicate) for claim_status SQL assertion tests"
  - "Inline Employee construction for OT tests — roster_from_seed is Business 1 only; biweekly/semi-monthly need custom employees"
  - "2 negative OT assertions (below-threshold, semi-monthly no-flag) pass GREEN in Wave 0 — correct: validate() emits no OT issues until Wave 1 adds the rule; positive assertions (weekly_flagged, biweekly_flagged, explicit_zero) fail RED as required"
  - "test_safe_to_learn_alias_idempotent verifies collision check wins over idempotency — 'D. Reyes' with both employees in roster is permanently ambiguous regardless of which employee already carries it"
metrics:
  duration_minutes: 15
  completed_date: "2026-06-23"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 3
---

# Phase 5 Plan 01: Wave 0 RED Test Stubs (claim_status, alias_write, validate D-05) Summary

Wave 0 test stubs written RED-first. Three test files establish the verification contract for the highest-risk units before Wave 1+ builds the implementations.

## What Was Built

**test_claim_status.py** (176 lines) — Wave 0 spec for `repo.claim_status` (FOUND-04/D-12):
- `test_claim_status_returns_true_when_row_returned`: FakeConnection returns a row → `True`
- `test_claim_status_returns_false_when_no_row`: FakeConnection returns None → `False`
- `test_claim_status_sql_contains_where_status_and_returning`: SQL shape assertion pinning `AND status = %s RETURNING id` (T-05-01)
- `test_claim_status_passes_expected_and_new_status_as_params`: parameterized SQL check
- `test_claim_status_invariant_doc_updated`: sentinel for the "two writers" docstring update (D-12)
- `test_claim_status_concurrent_calls_exactly_one_true`: `@pytest.mark.integration`, skip-guarded

**test_alias_write.py** (567 lines) — Wave 0 spec for `_safe_to_learn_alias` + alias capture + clarify idempotency:

Group 1 — D-01b collision guard:
- `test_safe_to_learn_alias_refuses_d_reyes_for_david`: canonical D. Reyes trap — both David Reyes AND Daniel Reyes carry "D. Reyes" → asserts `False` (T-05-02)
- `test_safe_to_learn_alias_accepts_unambiguous_token`: "Dave Reyez" → `True`
- `test_safe_to_learn_alias_idempotent`: token already in target, still collides with other employee → `False`
- `test_safe_to_learn_alias_idempotent_unambiguous`: token already only in target → `True`

Group 2 — CLAR-04 finding #2:
- `test_clarify_idempotency_skips_if_clarification_already_sent`: when `get_outbound_message_id` returns existing mid, `send_outbound` NOT called

Group 3 — D-04 single-token-only rule (R2-MEDIUM fix):
- `test_alias_capture_no_capture_when_multiple_unresolved`: 2+ unresolved names → `set_alias_candidates` NOT called
- `test_alias_capture_unambiguous_single_token_is_captured`: 1 token, 0 candidates → called with `{"Dave Reyez": None}`
- `test_alias_capture_colliding_single_token_not_captured`: 1 token, 2 candidates → NOT called (finding #5)

**tests/test_validate.py** (extended +226 lines) — 5 D-05 OT rule cases:
- `test_ot_rule_weekly_flagged`: weekly ppy=52, regular=45, OT=None → expects issue
- `test_ot_rule_biweekly_flagged`: biweekly ppy=26, regular=85, OT=None → expects issue
- `test_ot_rule_biweekly_not_flagged_below_threshold`: biweekly, regular=78 (below 80) → no issue
- `test_ot_rule_no_flag_semimonthly`: ppy=24, regular=100 → no issue (documented limitation)
- `test_ot_rule_explicit_zero_flagged`: weekly, regular=45, OT=Decimal("0") → expects issue (explicit-zero treated same as absent)

## RED State Verification

**test_claim_status.py**: 5 fail (AttributeError on missing `repo.claim_status`), 1 skipped (integration)

**test_alias_write.py**: Collection ERROR — `ImportError: cannot import name '_safe_to_learn_alias'` from `app.pipeline.reconcile_names` — correct RED at module level

**test_validate.py (ot_rule tests)**: 3 fail (positive assertions on missing OT rule), 2 pass (negative assertions — correct, validate() emits nothing until Wave 1 adds the rule)

**Existing suite**: 284 passed, 30 pre-existing failures (not caused by this plan — these are Phase 5 targets for later waves), no regressions

## Deviations from Plan

None — plan executed exactly as written. The 2 "negative assertion" OT tests that pass GREEN in Wave 0 are consistent with the plan's intent: they assert the *absence* of incorrect behavior, which is trivially satisfied before the implementation exists.

## TDD Gate Compliance

This is a Wave 0 RED-only plan. No GREEN or REFACTOR gates — those are owned by the implementation waves (Wave 1 for validate/repo, Wave 3 for clarify idempotency, Wave 4 for alias capture).

RED gate committed: `test(05-01): add Wave 0 RED stubs for claim_status CAS + alias write guards` (e9fca06)
RED gate committed: `test(05-01): extend test_validate.py with D-05 OT rule RED stubs` (3429fd2)

## Self-Check: PASSED

Files exist:
- tests/test_claim_status.py — FOUND
- tests/test_alias_write.py — FOUND
- tests/test_validate.py — FOUND (extended)

Commits:
- e9fca06 — test(05-01): add Wave 0 RED stubs for claim_status CAS + alias write guards
- 3429fd2 — test(05-01): extend test_validate.py with D-05 OT rule RED stubs

Line counts (all above min_lines: 40):
- test_claim_status.py: 176 lines
- test_alias_write.py: 567 lines
- test_validate.py: 308 lines (extended)

Artifact requirements:
- test_claim_status.py contains "claim_status" ✓
- test_alias_write.py contains "D. Reyes" ✓
- test_validate.py contains "hours_overtime" ✓ (7 occurrences)
- test_validate.py has 5 functions prefixed "test_ot_rule_" ✓
