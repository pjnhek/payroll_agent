---
phase: 05-dashboard-delivery
plan: "07"
subsystem: pipeline/alias-learning
tags: [alias-write, collision-guard, deterministic, learning-loop, wave-5]
dependency_graph:
  requires: ["05-05", "05-03"]
  provides: ["alias-write-side", "_safe_to_learn_alias", "update_known_alias", "_write_aliases_if_safe"]
  affects: ["app/pipeline/reconcile_names.py", "app/pipeline/orchestrator.py", "app/db/repo.py"]
tech_stack:
  added: []
  patterns:
    - "Synthetic-roster collision guard: model_copy to simulate post-write state, delegate to deterministic_match"
    - "Pre-vs-post diff binding: snapshot resolved_id sets before/after _run_stages to isolate newly-resolved employee (NEW-2)"
    - "Batch-safe alias writes: roster refresh after each accepted write prevents inter-candidate interactions"
    - "D-13b defensive isolation: try/except wrapper at _write_aliases_if_safe call site, never strands a sent run"
    - "Candidate_ids count (not deterministic_match None) as collision signal — R2-HIGH fix"
key_files:
  created: []
  modified:
    - app/pipeline/reconcile_names.py
    - app/db/repo.py
    - app/pipeline/orchestrator.py
    - tests/test_alias_write.py
decisions:
  - "D-01b write-side collision guard: _safe_to_learn_alias uses synthetic roster + deterministic_match; never mutates real roster objects (Pydantic v2 model_copy)"
  - "R2-HIGH collision detection: count candidate_ids directly at capture time, not from deterministic_match return value (None is ambiguous — means both zero-match AND collision)"
  - "Finding #4 single-token-only restriction: alias_candidates not written for 2+ unresolved names — binding is unsolvable for multi-token runs without a UI-confirmed mapping"
  - "Finding #5 capture-time exclusion: colliding tokens excluded AT emit time in _clarify, not just filtered at write time (D-04 locked constraint)"
  - "NEW-2 pre-vs-post diff binding: diff resolved_id sets before/after _run_stages to isolate newly-resolved employee; old 'exactly one resolved' check would no-op on realistic multi-employee runs"
  - "D-13b ordering: _write_aliases_if_safe called BEFORE set_status(SENT) in _deliver (PATTERNS.md line 611); wrapped in try/except for defensive isolation"
metrics:
  duration_minutes: 45
  completed_date: "2026-06-22"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 4
---

# Phase 5 Plan 07: Alias Write-Side Learning Loop Summary

Implemented the WRITE side of the human-confirmation learning loop (Beat 3, D-15 independently droppable). When the operator approves a resolved run, the original unresolved shorthand that the client's reply corrected is permanently learned — but only when unambiguous, non-colliding, and a single-token run.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | `_safe_to_learn_alias` + `update_known_alias` | `9457c0d` | app/pipeline/reconcile_names.py, app/db/repo.py |
| 2 | alias_candidates capture + resume binding + `_write_aliases_if_safe` | `dd53d0e` | app/pipeline/orchestrator.py, tests/test_alias_write.py |

## What Was Built

**Task 1 — `_safe_to_learn_alias` (reconcile_names.py):**
Write-side collision guard (D-01b). Builds a synthetic roster with the candidate alias appended to the target employee only, then delegates to `deterministic_match`. Returns True only if the token uniquely resolves to the target employee post-append. The David/Daniel Reyes trap is explicitly tested: "D. Reyes" shared by both employees returns False even when re-adding to either one.

**Task 1 — `update_known_alias` (repo.py):**
Idempotent JSONB append via `NOT (known_aliases @> to_jsonb(ARRAY[%s::text]))` WHERE guard. Returns True if alias added, False if already present. Caller must have already called `_safe_to_learn_alias` — this function does not re-check collision.

**Task 2 — `_clarify` capture (orchestrator.py):**
Three-tier gate at capture time (before send_outbound):
1. `len(unresolved_names) != 1` — no capture (finding #4 single-token-only)
2. `candidate_ids count > 1` — no capture (finding #5 + R2-HIGH collision)
3. `candidate_ids count == 1` — already resolves; skip (not a learning target)
4. `candidate_ids count == 0` — genuinely unresolved — capture `{token: None}`

Collision detection uses direct `exact_ids | alias_ids` counting, NOT `deterministic_match` return value (None is ambiguous — means both zero-match and collision).

**Task 2 — `resume_pipeline` binding (orchestrator.py):**
Pre-vs-post diff binding (NEW-2): snapshots resolved employee_id set BEFORE `_run_stages`, runs stages, snapshots AFTER. The diff (post minus pre) isolates the single newly-resolved employee. Handles multi-employee runs where other employees were already resolved — the old "exactly one resolved match" assumption would have silently no-oped on every realistic run.

**Task 2 — `_write_aliases_if_safe` + `_deliver` hook (orchestrator.py):**
Module-level helper called in `_deliver` BEFORE `set_status(SENT)` (D-13b ordering). Wrapped in try/except at call site — any alias write failure logs a warning and the run advances to SENT/RECONCILED normally. Batch-safe: refreshes `current_roster` after each accepted write so the next candidate validates against the updated roster state.

## Deviations from Plan

**[Rule 1 - Bug] Fixed idempotency test mock missing `purpose` kwarg**
- **Found during:** Task 2 (running existing tests)
- **Issue:** `test_clarify_idempotency_skips_if_clarification_already_sent` patched `get_outbound_message_id` with `lambda run_id, conn=None: existing_mid` but the orchestrator calls `repo.get_outbound_message_id(run_id, purpose="clarification")` — TypeError on the purpose kwarg
- **Fix:** Updated mock signature to `lambda run_id, purpose=None, conn=None: existing_mid`
- **Files modified:** tests/test_alias_write.py
- **Commit:** dd53d0e

## Tests

All 21 tests in `tests/test_alias_write.py` + `tests/test_delivery.py` pass GREEN:

**Group 1 — `_safe_to_learn_alias` unit tests (D-01b):**
- `test_safe_to_learn_alias_refuses_d_reyes_for_david` — canonical D. Reyes trap returns False
- `test_safe_to_learn_alias_accepts_unambiguous_token` — "Dave Reyez" returns True
- `test_safe_to_learn_alias_idempotent` — collision check fires even when token already in target's aliases
- `test_safe_to_learn_alias_idempotent_unambiguous` — re-add of unambiguous token returns True

**Group 2 — Clarify idempotency (CLAR-04):**
- `test_clarify_idempotency_skips_if_clarification_already_sent` — send_outbound not called twice

**Group 3 — Alias capture gates (finding #4, #5, R2-HIGH):**
- `test_alias_capture_no_capture_when_multiple_unresolved` — 2+ tokens, no capture
- `test_alias_capture_unambiguous_single_token_is_captured` — single zero-candidate token, captured
- `test_alias_capture_colliding_single_token_not_captured` — 2 candidate_ids, not captured

**Group 4 — D-04 timing + NEW-2 pre-vs-post diff (new tests added this plan):**
- `test_clarify_captures_alias_candidates_before_send` — set_alias_candidates before send_outbound in call log
- `test_resume_binding_uses_pre_vs_post_diff_not_single_resolved_count` — multi-employee run (maria + david) correctly binds "Dave Reyez" to david.id via diff
- `test_resume_binding_skips_when_no_newly_resolved_employee` — no binding when diff is empty

**Delivery tests (test_delivery.py):** All 10 pass, confirming alias write failure does not strand a sent run.

Pre-existing failures in `tests/test_llm_client.py`, `tests/test_orchestrator_states.py`, `tests/test_threading.py`, and `tests/test_webhook.py` (22 total) are unchanged from the Wave 3 base — not introduced by this plan.

## Known Stubs

None. All implemented paths are wired.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. `update_known_alias` writes to `employees.known_aliases` (pre-existing column, D-04 DDL from Plan 03). Trust boundary T-05-25 (alias write to money-routing) is mitigated by `_safe_to_learn_alias` as planned.

## Self-Check: PASSED

- [x] `app/pipeline/reconcile_names.py` contains `def _safe_to_learn_alias(` at line 112
- [x] `app/db/repo.py` contains `def update_known_alias(` at line 474
- [x] `app/pipeline/orchestrator.py` contains `alias_candidates` (9 occurrences — clarify capture, resume binding, _write_aliases_if_safe)
- [x] `app/pipeline/orchestrator.py` imports `_safe_to_learn_alias` (line 55)
- [x] `_write_aliases_if_safe` call (line 543) appears BEFORE `set_status(SENT)` (line 553) in `_deliver`
- [x] `uv run python -c "from app.pipeline.reconcile_names import _safe_to_learn_alias"` exits 0
- [x] `uv run pytest tests/test_alias_write.py tests/test_delivery.py -q` — 21 passed
- [x] app/main.py, app/templates/, app/static/ NOT touched (05-06 owns those)
- [x] Commits: 9457c0d (Task 1), dd53d0e (Task 2)
