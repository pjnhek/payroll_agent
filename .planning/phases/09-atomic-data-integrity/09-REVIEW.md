---
phase: 09-atomic-data-integrity
reviewed: 2026-07-04T07:54:58Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - app/db/repo.py
  - app/llm/client.py
  - app/main.py
  - app/pipeline/compose_email.py
  - app/pipeline/orchestrator.py
  - tests/conftest.py
  - tests/test_alias_write.py
  - tests/test_atomic_persist.py
  - tests/test_clarify.py
  - tests/test_cr_regressions.py
  - tests/test_demo_landing.py
  - tests/test_gateway.py
  - tests/test_ingest.py
  - tests/test_llm_client.py
  - tests/test_multiround_context_edge.py
  - tests/test_stuck_run_recovery.py
  - tests/test_webhook.py
  - tests/test_webhook_dedup_race.py
findings:
  critical: 0
  warning: 5
  info: 9
  total: 14
status: issues_found
---

# Phase 9: Code Review Report (Re-review after 09-06 gap closure)

**Reviewed:** 2026-07-04T07:54:58Z
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

This is a RE-REVIEW after the 09-06 gap-closure wave (commits `e192c37`, `da1e962`) that fixed the prior review's WR-01 (no SAVEPOINT around `_deliver`'s alias write) and WR-02 (Round-2 `clarified_fields` persisted after the status advance). Both fixes were traced against live source, argument-by-argument, and against their new live-DB crash-injection tests.

**Verdict on the two fixes: both are correct and complete.**

- **Prior WR-02 (gap 1, `e192c37`) — RESOLVED.** `repo.set_clarified_fields(run_id, clarified, conn=conn)` now runs in its own closed `with repo.get_connection(): with conn.transaction():` block at `app/pipeline/orchestrator.py:604-606`, strictly BEFORE the Round-2 `_run_stages` call at line 608. The safety claim ("terminal outcomes do not depend on `_run_stages`' return value") is true: classify-first STEP 1 (lines 431-483) fully resolves `client_supplied`/`confirmed_dropped`/`carried_forward` in memory before the persist, and the deferred helper only ADDS new `asked` entries (line 759), never mutating the terminals. D-9-01 is preserved: the new transaction opens after both `extract()` LLM calls (lines 377/380) and closes before `_run_stages`. The live crash-injection test (`tests/test_atomic_persist.py::test_round2_clarified_fields_persist_before_run_stages`) injects the crash at the correct point — the FIRST `set_status` call on this path is `set_status(COMPUTED)` inside `_run_stages`' own persist transaction (no earlier `set_status` exists on the resume path, which uses `claim_status`) — and asserts on the persisted VALUE (`client_supplied`, not `asked`) plus the run landing at ERROR, not AWAITING_APPROVAL. The AST source-order guard (`test_round2_clarified_fields_persist_call_order_before_run_stages`) correctly pins the write inside a `with` block and before the last `_run_stages` call. One residual consequence of the chosen "independently committed" design is recorded below as WR-06.

- **Prior WR-01 (gap 2, `da1e962`) — RESOLVED.** The nested `with conn.transaction():` at `app/pipeline/orchestrator.py:1407-1409` is a psycopg3 SAVEPOINT (nested transaction blocks emit SAVEPOINT/RELEASE/ROLLBACK TO), so a genuine DB-level error inside `_write_aliases_if_safe`'s repo helpers (all of which run under `_nulltx()` when a caller conn is supplied, `app/db/repo.py:134-141, 1416-1419`) now rolls back only to the savepoint; the outer connection stays clean for `set_status(SENT)`/`set_status(RECONCILED)`. The exception ordering is right: the savepoint CM rolls back and re-raises, the surrounding `try/except` (lines 1407-1415) swallows it, and the finalize continues. The new live-DB test (`test_deliver_finalize_genuine_db_alias_failure_still_reaches_reconciled`) injects a real `UndefinedColumn` against the shared conn — exactly the failure class the prior review said the pure-Python-raise test could not prove — and asserts the run still reaches `reconciled`. The retry-over-sent early-return path (line 1284, no conn) is unaffected and remains correctly isolated by its own try/except.

Offline suite for all 18 reviewed files: **141 passed, 15 skipped** (live-DB tests skip without `DATABASE_URL` + `ALLOW_DB_RESET=1`).

**Still open from the prior review:** WR-03, WR-04, and IN-01 through IN-06 were acknowledged in 09-VERIFICATION.md as real-but-not-phase-blocking and were NOT addressed by the gap-closure commits. They remain present in the code and are carried forward below under their original IDs. Three NEW findings from this pass are numbered WR-05/WR-06/WR-07 and IN-07/IN-08/IN-09.

## Warnings

### WR-03 (carried, still open): Real-webhook reply rows are never linked to their run (`run_id=None`)

**File:** `app/main.py:373-383` (ingest insert with `run_id=None` at line 381), `app/db/repo.py:1227-1248` (`load_thread_messages`)
**Issue:** Unchanged since the prior review. The ingest transaction inserts every inbound row with `run_id=None` and never back-fills it after classifying the row as `reply_candidate`/`late_reply`, so real client replies are invisible in the run-detail thread view and in any join-based audit. The simulate-reply demo path passes `run_id=run_id` (main.py:1381-1390), so the demo shows a complete thread while production shows a hole.
**Fix:** Inside the ingest transaction, after classification, `UPDATE email_messages SET run_id = %s WHERE id = %s` (or add a `repo.link_email_to_run` helper). Verified no such backfill exists anywhere in `app/` (`grep "SET run_id"` returns nothing).

### WR-04 (carried, still open): A persisted reply can be permanently dropped — duplicate redelivery never re-attempts the resume; a resume task that dies pre-claim has no recovery route

**File:** `app/main.py:385-394` + `445-454` (duplicate outcome), `app/main.py:600-611` (`_resume_pipeline` safety net), `app/main.py:766-771` (retrigger `stale_statuses` excludes `awaiting_reply`)
**Issue:** Unchanged since the prior review. (1) A post-commit failure before `background_tasks.add_task` makes the provider redeliver, but the redelivery takes the `duplicate` path and returns 200 without re-running reply classification — the reply is durably persisted yet never processed. (2) A resume task dying before `claim_status(AWAITING_REPLY → EXTRACTING)` leaves the run at `awaiting_reply`, which is (correctly) outside the sweep scope but ALSO outside retrigger's claimable set — no operator recovery route.
**Fix:** On the `duplicate` outcome, when the duplicate carries reply headers and `find_awaiting_reply_for_header` still matches, re-schedule `_resume_pipeline` (the CAS claim already makes double-scheduling safe).

### WR-05 (NEW): `_clarify`'s purpose-scoped idempotency guard is round-blind — a SECOND clarification with the same purpose is silently never sent, parking the run at `awaiting_reply` with no operator recovery route

**File:** `app/pipeline/orchestrator.py:980-995` (idempotency early-return), `app/db/repo.py:1024-1050` (`get_outbound_message_id`), `app/main.py:766-771` (retrigger cannot claim `awaiting_reply`)
**Issue:** `get_outbound_message_id(run_id, purpose=purpose)` returns the Message-ID of ANY prior sent row with that purpose for the run — it cannot distinguish "re-trigger of the same clarification" (the CLAR-04 case the guard exists for) from "a genuinely NEW question in a later round." Two reachable multi-round scenarios strand the run:
1. **Plain `clarification`, repeated.** Round-0 gates on an unresolved name → clarification sent (`purpose='clarification'`, `send_state='sent'`). The client's reply resolves that name but introduces a NEW unknown name (e.g. "also add Bob Smith, 10 hours"). `resume_pipeline` → `_run_stages` → decision = `request_clarification` (unresolved name, no field regression) → `_clarify(purpose='clarification')` → the guard finds the Round-0 row → logs "skipping duplicate send" and re-parks at AWAITING_REPLY **without sending anything**. The client is never asked about Bob.
2. **`clarification_field_regression`, repeated.** A Round-1 field-regression clarification was sent (e.g. about `hours_overtime`). In a LATER round a DIFFERENT field regresses (or an `_unresolvable_asked` field re-defers, which the WR-01-fix comments in the classify block explicitly describe as "under-fill that re-clarifies") → `_defer_field_regression_clarification` → `_clarify(purpose='clarification_field_regression')` → the guard finds the earlier round's sent row → skips the send. The re-clarify that the money-safety design depends on never reaches the client.
In both cases the run sits at `awaiting_reply` — a parked status the sweep (correctly) never touches and retrigger cannot claim — so the only recovery is the client spontaneously emailing again (which re-runs the same skip). This is not a wrong-pay path (the run never processes), but it violates the "nothing silently hangs" invariant on a code path the operator has no UI to recover.
**Fix:** Make the guard round-aware. Options: (a) compare the CURRENT drafted ask against what the existing row asked (cheap: store `gate_reasons`/asked-fields hash on the outbound row and skip only when it matches); (b) scope the guard to the current status transition — only skip when the run is being RE-triggered from `awaiting_reply` (idempotent retry), never when arriving from EXTRACTING with a fresh decision; (c) include a round counter in the purpose/uniqueness key (note `uq_email_run_purpose` currently enforces one row per (run, purpose), so the upsert in `insert_email_message` already supports replacing the row content — only the guard blocks the send).

### WR-06 (NEW): Residual crash window from the WR-02 fix — terminal `clarified_fields` labels can survive a rolled-back run, then mislabel provenance after an operator retrigger

**File:** `app/pipeline/orchestrator.py:589-618` (the new pre-`_run_stages` persist), `app/main.py:690-798` (retrigger dispatches `_run_pipeline`, losing reply context — documented accepted limitation)
**Issue:** The fix's chosen design ("independently committed and independently diagnosable") means a crash INSIDE `_run_stages` now leaves the inverse of the old gap: `clarified_fields` durably shows terminal outcomes (`client_supplied`/`confirmed_dropped`) while every value that justified those labels (extracted_data, line items) rolled back, and the run lands at ERROR. That ERROR state itself is fine (diagnosable, and the new test asserts it). The problem appears one step later: the operator's only recovery is retrigger, which restarts from the ORIGINAL email (documented reply-context-loss limitation). The retriggered run re-pays whatever the original email said (e.g. OT=2), while the run-detail provenance badges — driven by `clarified_fields` (main.py:1150-1170) — still show `client-removed`/`client-supplied` for those fields from the crashed round. The operator at the approval gate sees a paid OT=2 line labeled "client explicitly zeroed this," which is actively misleading at the exact human checkpoint the system relies on. Additionally, `is_round_2 = bool(clarified)` (orchestrator.py:329) means any FUTURE clarify/resume cycle on the retriggered run treats those stale terminals as `_resolved_by_name`, feeding `backfill_skip`/`suppress_detection` with outcomes from a round whose values no longer exist.
**Fix:** At retrigger time (the point where reply context is knowingly discarded), clear or archive `clarified_fields` and `pre_clarify_extracted` for the run so provenance labels cannot outlive the data that produced them — this also keeps the documented reply-context-loss limitation self-consistent (context lost means ALL of it, not just the values). Alternatively, render the provenance badge only when the labeled field's paid value is consistent with the label.

### WR-07 (NEW): Stale `strict=True` xfail on an implemented behavior guarantees a live-suite failure

**File:** `tests/test_gateway.py:1129-1200` (`test_inbound_reply_routes_to_correct_run_integration`)
**Issue:** The test is decorated `@pytest.mark.xfail(strict=True, reason="implemented in 06-04")`, but the behavior it exercises (the real `_HEADER_MATCH_PREDICATE` via a direct `find_awaiting_reply_for_header` call — note it never actually POSTs to the route despite its docstring) IS implemented and passes. In any environment with `DATABASE_URL` + `ALLOW_DB_RESET=1`, the test XPASSes, and `strict=True` converts the XPASS into a hard suite FAILURE. The convention documented in the same file (lines 450-456) says an XPASS "is the signal to REMOVE the markers in 06-04" — that removal never happened for this one test. (The deferred-items.md entry attributes this test's live failure to the missing `ALLOW_UNSIGNED_FIXTURES` env var, but the test makes no HTTP request — the actual live failure mode is the strict-xfail XPASS.)
**Fix:** Remove the `@pytest.mark.xfail(strict=True, ...)` decorator (keep `@pytest.mark.integration` and the in-body skip guard). Correct the deferred-items.md note for this test while touching it.

## Info

### IN-01 (carried, still open): Redundant/over-broad exception tuple on signature verification

**File:** `app/main.py:310`
**Issue:** `except (ValueError, Exception) as exc:` — `Exception` subsumes `ValueError`; any programming error inside `gateway.verify` is reported as an "invalid signature" 400.
**Fix:** Catch `ValueError` + the specific SDK error type; let genuine bugs surface distinctly.

### IN-02 (carried, still open): STALE_THRESHOLD derivation comment omits the `suggest_employees` 90s ceiling and the Resend SDK 30s timeout

**File:** `app/main.py:62-101`
**Issue:** The comment's 210s "correctly-derived worst-case" mis-composes the clarify-branch gap (suggest 90s + compose 30s + provider send 30s = 150s, vs. the counted 30s). The 15-minute threshold remains safe (~5x margin); only the stated math is wrong — risky if someone later tightens the threshold from it.
**Fix:** Correct the per-gap enumeration in the comment.

### IN-03 (carried, still open): `_NON_THINKING_EXTRA_BODY` deep-copied in `call_text` but passed by shared reference in `call_structured`

**File:** `app/llm/client.py:78, 146-148, 240-242`
**Issue:** Inconsistent handling of the shared mutable module constant; a downstream mutation through `call_structured` would corrupt every future call.
**Fix:** Deep-copy in both (or freeze the constant).

### IN-04 (carried, still open): `approve()` declares an unused `background_tasks` parameter

**File:** `app/main.py:632-635`
**Issue:** Delivery is synchronous; the injected `BackgroundTasks` is never used.
**Fix:** Remove the parameter.

### IN-05 (carried, still open): Sweep failures on GET /runs logged at DEBUG

**File:** `app/main.py:1062-1065`
**Issue:** A persistently failing DATA-03 recovery sweep is invisible at default log levels.
**Fix:** Log at WARNING with the exception type.

### IN-06 (carried, still open): Redundant condition in the alias-diff gate

**File:** `app/pipeline/orchestrator.py:641`
**Issue:** `if _none_tokens and _pre_candidates:` — non-empty `_none_tokens` implies non-empty `_pre_candidates`; the second operand is dead.
**Fix:** `if _none_tokens:`.

### IN-07 (NEW): Ruff-flagged dead code in the reviewed test files

**File:** `tests/test_atomic_persist.py:36` (`FakeConnection` imported but unused), `tests/test_atomic_persist.py:779` (`import psycopg` unused — ironic in the test that exists to prove a psycopg error class), `tests/test_cr_regressions.py:25` (`Decimal` unused), `:27` (`pytest` unused), `:57` (`result` assigned but never used), `:306` (`PaystubLineItem` unused)
**Issue:** Six F401/F841 findings; the project's own tooling (`uv run ruff check`) reports them. All are in files this phase touched. The application source files (`repo.py`, `client.py`, `main.py`, `compose_email.py`, `orchestrator.py`) are ruff-clean.
**Fix:** `uv run ruff check --fix tests/test_atomic_persist.py tests/test_cr_regressions.py` (the F841 needs a manual delete of the assignment).

### IN-08 (NEW): Stray duplicate POST with a repr-encoded body in the prod-auth test

**File:** `tests/test_gateway.py:1440-1446`
**Issue:** `test_allow_unsigned_fixtures_prod_default_returns_400` first POSTs `resend_envelope.__class__(resend_envelope).__repr__().encode()` (a Python-repr string, not JSON), immediately discards that response, and re-POSTs with `json=`. The first request is dead code that still executes against the route — the inline comment ("Actually use json= ...") shows it is leftover scaffolding.
**Fix:** Delete lines 1440-1445 (the first `client.post` and its comment).

### IN-09 (NEW): `call_text` silently swallows unknown keyword arguments

**File:** `app/llm/client.py:195-201`
**Issue:** The `**kwargs` in `call_text`'s signature exists so test fakes tolerate `timeout_s=`, but the real implementation never forwards `kwargs` anywhere — a production caller passing e.g. `max_tokens=` or `top_p=` gets a silent no-op instead of a TypeError.
**Fix:** Either drop `**kwargs` from the real function (fakes can keep it) or `raise TypeError` on unexpected keys.

## Notes (tracked elsewhere, not re-counted)

- **Multi-round context loss** (a Round-1 paid→paid correction silently reverting in Round-2) is a known, documented edge with a dedicated regression fixture (`tests/test_multiround_context_edge.py`) and a deferred-fix disposition in 09-CONTEXT.md — verified the fixture asserts the CURRENT behavior with clear flip-on-fix instructions. Not re-counted as a finding. Note that WR-05 scenario 1 interacts with this family: a new employee introduced only in a Round-1 reply is both never asked about (WR-05) and lost from later rounds' combined context.
- **`tests/test_ingest.py::test_duplicate_delivery_pipeline_runs_once` missing `ALLOW_UNSIGNED_FIXTURES=true`** (live-DB 400) is already logged in `.planning/phases/09-atomic-data-integrity/deferred-items.md` with a concrete action; not re-counted. The same deferred entry's claim about `test_inbound_reply_routes_to_correct_run_integration` is inaccurate — see WR-07.

---

_Reviewed: 2026-07-04T07:54:58Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
