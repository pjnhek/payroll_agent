---
phase: 09-atomic-data-integrity
reviewed: 2026-07-04T03:50:41Z
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
  - tests/test_webhook_dedup_race.py
  - tests/test_webhook.py
findings:
  critical: 0
  warning: 4
  info: 6
  total: 10
status: issues_found
---

# Phase 9: Code Review Report

**Reviewed:** 2026-07-04T03:50:41Z
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

Reviewed the Phase 9 atomic-data-integrity change surface (diff base `d395e64`): the DATA-01 transaction wiring in `orchestrator.py` (`_run_stages` persist block, `_clarify`'s three exit paths, `_deliver`'s finalize block, `_defer_field_regression_clarification`), the DATA-02 transactional ingest classification in `main.py::inbound` plus `repo.find_run_by_message_id`, the DATA-03 stranded-run sweep (`repo.sweep_stranded_runs` wired into `GET /runs` + the retrigger stale claim), and the LLM latency bounding in `client.py` / `compose_email.py`, along with all new/modified tests.

The core money-path claims verified as sound:

- The `_run_stages` process-branch transaction genuinely covers persist_extracted / persist_decision / persist_reconciliation / replace_line_items / both status advances, with `_compute_line_items` (the one business-raise site) hoisted before the transaction opens, and `_clarify` confirmed a sibling statement outside every `with` block (D-9-01) — both by reading the code and by the AST-pin tests.
- The `inbound()` ingest transaction correctly makes a header-bearing reply structurally unable to reach `create_run` (Codex HIGH-1), and the dedup race resolves via the unique-index block-then-DO-NOTHING semantics: the loser's `find_run_by_message_id` runs on a fresh READ COMMITTED snapshot after the winner's whole transaction (including `create_run`) has committed, so `test_webhook_dedup_race.py` is asserting a real property.
- `sweep_stranded_runs` is a single-statement CAS with the D-9-12 scope pinned in SQL params and by two tests; `%s || status` correctly captures the pre-update status (standard UPDATE SET semantics); parked statuses are excluded; concurrent sweep-vs-retrigger resolves via row-lock CAS in both directions.
- `record_run_error`'s WR-03 CAS row-locks the run between the terminal-guard UPDATE and `set_status(ERROR)` in the same transaction, so the terminal-clobber race is genuinely closed.
- `call_structured`/`call_text` verified to pass `timeout=`/`max_retries=0` (and API exceptions from attempt 1 correctly bypass the reflective retry, so the 2x ceiling holds).
- Verified empirically that `ValidationError.from_exception_data(name, [])` does not raise on this pydantic version, so `call_structured`'s double-empty-content fallback path is safe.

Four warnings below. None is a direct wrong-pay or double-pay path — the money values stay correct in every traced failure mode — but three are crash-window integrity gaps that sit squarely inside this phase's own DATA-01/DATA-02 mandate, and one is a claimed isolation guarantee (`_deliver`'s alias-failure isolation) that does not actually hold for database-level errors.

## Warnings

### WR-01: `_deliver` finalize try/except cannot isolate a DB error from the alias write — the claimed "alias failure never fails a sent run" invariant is false for psycopg errors

**File:** `app/pipeline/orchestrator.py:1368-1389` (finalize transaction), `app/db/repo.py:911-925` / `app/db/repo.py:134-141` + `1416-1419` (`_conn_ctx` → `_nulltx` when conn supplied)
**Issue:** `_write_aliases_if_safe(run_id, run, roster, conn=conn)` runs inside the finalize `with conn.transaction():` block, wrapped in try/except so "an alias-learning failure NEVER rolls back a genuine delivery." That isolation only works for pure-Python exceptions (which is exactly what `test_deliver_finalize_alias_failure_still_reaches_reconciled` injects — a monkeypatched function that raises before touching the connection). If any SQL statement issued by the alias path fails at the database level (`update_known_alias`, `load_run(conn=conn)`, `load_roster_for_business(conn=conn)` — e.g. a constraint error, lock timeout, or serialization failure), the enclosing Postgres transaction enters the aborted state. The except clause swallows the exception, but the very next statement — `set_status(run_id, RunStatus.SENT, conn=conn)` — raises `InFailedSqlTransaction`, the whole finalize block rolls back, `_deliver` raises, and the run routes to ERROR even though the confirmation email was already durably sent. Because every repo helper uses `_nulltx()` when a caller-supplied `conn` is present, there is no savepoint anywhere in this chain. Recovery exists (retrigger → already-sent guard → no duplicate email), but the run ERRORs after a successful send and the entire pipeline re-runs — the precise outcome the comment claims is impossible.
**Fix:** Give the alias write its own savepoint so a DB error rolls back only the alias work, not the finalize transaction:

```python
try:
    with conn.transaction():  # psycopg3 nested block = SAVEPOINT
        _write_aliases_if_safe(run_id, run, roster, conn=conn)
except Exception as alias_exc:  # noqa: BLE001
    logger.warning("alias write skipped for run %s: %s (run continues to SENT)",
                   run_id, type(alias_exc).__name__)
```

Add a live-DB fault-injection test that makes `update_known_alias` fail with a real SQL error (not a monkeypatched Python raise) and asserts the run still reaches RECONCILED.

### WR-02: Round-2 terminal classify outcomes persist in a separate transaction AFTER the run has already committed AWAITING_APPROVAL — a crash in between leaves an approvable run with stale 'asked' provenance and skips alias binding

**File:** `app/pipeline/orchestrator.py:615-618` (`repo.set_clarified_fields(run_id, clarified)` after the `_run_stages` call), vs. `app/pipeline/orchestrator.py:890-899` (the `_run_stages` persist transaction)
**Issue:** On the Round-2 non-deferred path, `_run_stages` commits its atomic transaction — including `set_status(AWAITING_APPROVAL)` — and only then does `resume_pipeline` persist the classify-first terminal outcomes via `set_clarified_fields` in its own pooled transaction. A crash between the two commits leaves: (a) a run at AWAITING_APPROVAL whose `clarified_fields` still read `asked` for fields the client actually answered (the run-detail provenance badges then contradict the paid line items — the exact classify-label-vs-paid-value divergence family Phase 7.5 was about, here as a display/audit divergence rather than a pay divergence, since the line items were computed from the corrected `raw_extracted`); and (b) the STEP C/D alias diff never runs, silently dropping the alias-candidate binding. This is the one persist sequence on the resume path that the DATA-01 transaction work did not fold in — note the deferred branch got the ordering right (`set_clarified_fields` commits before `_clarify`), only the fall-through branch is split from the status advance.
**Fix:** Persist the terminal outcomes atomically with (or strictly before) the status advance. Simplest structure-preserving option: persist `clarified` BEFORE calling `_run_stages` on the Round-2 path (the outcomes are final at the end of STEP 1 and do not depend on `_run_stages`' result), mirroring the asked-before-send ordering the deferred branch already uses. Alternatively pass a `conn` through so `set_clarified_fields` joins the `_run_stages` transaction.

### WR-03: Real-webhook reply rows are never linked to their run (`run_id=None`) — real client replies are invisible in the thread view and join-based audit queries

**File:** `app/main.py:373-383` (ingest insert with `run_id=None`), `app/db/repo.py:1227-1248` (`load_thread_messages` matches only `run_id = %s OR id = source_email_id`)
**Issue:** The ingest transaction inserts every inbound row with `run_id=None`, then classifies it. On the `reply_candidate` and `late_reply` outcomes the code has `reply_run_id`/`late_run_id` in hand, inside the same open transaction, but never back-fills `email_messages.run_id`. Result: a real client clarification reply persists as an orphan row that `load_thread_messages` cannot find, so the run-detail thread view shows the clarification question but not the client's answer — and any join-based audit of "which emails belong to this run" misses the reply entirely. The simulate-reply path was explicitly fixed for this (IN-01: it passes `run_id=run_id`), so the demo shows a complete thread while production shows a hole. This gap predates Phase 9, but this phase restructured exactly this block, has the run id in scope inside the transaction, and left it unlinked.
**Fix:** Inside the ingest transaction, after classification, link the row:

```python
if reply_run_id is not None or late_run_id is not None:
    c.execute("UPDATE email_messages SET run_id = %s WHERE id = %s",
              (str(reply_run_id or late_run_id), str(email_id)))
```

(or add a small `repo.link_email_to_run(email_id, run_id, conn=)` helper to keep SQL out of main.py).

### WR-04: A classified reply can still be permanently dropped: duplicate redelivery never re-attempts the resume, and a resume task that dies pre-claim leaves the run in a state neither the sweep nor retrigger can recover

**File:** `app/main.py:385-394` + `445-454` (duplicate outcome), `app/main.py:600-611` (`_resume_pipeline` safety net), `app/db/repo.py:426` (sweep scope excludes `awaiting_reply` — correctly), `app/main.py:766-771` (retrigger `stale_statuses` excludes `awaiting_reply`)
**Issue:** Two windows around the DATA-02 work where a reply is received, durably persisted, and then silently never processed:
1. **Post-commit failure before scheduling.** If anything between the ingest commit and `background_tasks.add_task` raises (e.g. the `repo.load_run` / `find_business_by_sender` reads inside `_finish_reply_resume` hit a pooler blip), the webhook 500s. The provider redelivers — but the redelivery now takes the `duplicate` path (`insert` conflicts), which returns 200 without ever re-running reply classification. The reply is permanently dropped while the run parks at `awaiting_reply`.
2. **Background task dies before the claim.** `_resume_pipeline`'s catastrophic-failure guard logs and returns; if the task dies before `claim_status(AWAITING_REPLY → EXTRACTING)`, the run is still `awaiting_reply` — deliberately outside the sweep scope (D-9-12, correct) but ALSO outside retrigger's claimable set, so there is no operator recovery route for the lost resume. (Post-claim deaths are covered: the run is EXTRACTING and the sweep/retrigger handle it, with the documented reply-context-loss caveat.)
In both cases the only recovery is the client sending a fresh reply (new message_id) or the operator using the demo-only simulate-reply form. For a system whose stated phase goal includes "no run silently dropped," a persisted-but-never-processed reply is the same failure class.
**Fix:** On the `duplicate` outcome, when the duplicate row carries reply headers and `find_awaiting_reply_for_header` still matches a run in `awaiting_reply`, treat the redelivery as a resume retry (schedule `_resume_pipeline` again — `claim_status` already makes double-scheduling safe). That single change closes window 1 and gives window 2 a natural at-least-once recovery via provider retries. Alternatively/additionally: log window-2 drops at WARNING with the run_id so the operator can at least see them.

## Info

### IN-01: Redundant/over-broad exception tuple on signature verification

**File:** `app/main.py:311`
**Issue:** `except (ValueError, Exception) as exc:` — `Exception` subsumes `ValueError`, and the breadth means any programming error inside `gateway.verify` (e.g. an AttributeError) is reported to the caller as "invalid signature" 400 rather than surfacing as a bug.
**Fix:** Catch `ValueError` (the documented verify failure) plus the specific SDK error type; let genuine bugs 500 loudly or log them distinctly.

### IN-02: STALE_THRESHOLD derivation comment is mis-composed — it omits the `suggest_employees` structured call (90s ceiling) and the Resend send (30s SDK default) from its "correctly-derived worst-case" accounting

**File:** `app/main.py:66-101`
**Issue:** The comment sums (b) 180s + (c) 30s = 210s as "the full, correctly-derived worst-case gap between two consecutive DB writes." But (b) and (c) are not the same inter-write gap: the clarify branch's real gap is `suggest_employees` (a `call_structured` caller: 45s x 2 = 90s, acknowledged in point (a) but never counted) + compose (30s) + the Resend provider send (bounded at 30s by the SDK's default `timeout=30`, uncounted). True max single gap is the Round-2 double extraction at 180s, so the 15-minute threshold remains safe with ~5x margin — but given this project's history of retry-math findings, the stated derivation should be corrected before someone tightens the threshold based on it. Also note the backstop if the bound is ever violated is soft: a swept-to-ERROR run whose task is still alive gets its ERROR silently overwritten by the task's unguarded `set_status` calls.
**Fix:** Correct the comment to enumerate per-gap ceilings (double-extraction 180s; alias-write → AWAITING_REPLY gap = 90s suggest + 30s compose + 30s provider send = 150s) and cite the Resend SDK's 30s default timeout as a counted component.

### IN-03: `_NON_THINKING_EXTRA_BODY` handled inconsistently — `call_text` deep-copies it, `call_structured` passes the shared module-level dict by reference

**File:** `app/llm/client.py:78, 146-148, 240-242`
**Issue:** If anything downstream ever mutates `extra_body`, `call_structured` corrupts the module constant for every future call while `call_text` is protected. One of the two is wrong; the asymmetry invites drift.
**Fix:** Deep-copy in both (or make the constant an immutable mapping / factory function).

### IN-04: `approve()` declares an unused `background_tasks` parameter

**File:** `app/main.py:631-635`
**Issue:** Delivery is synchronous in `approve()`; the injected `BackgroundTasks` is never used. Dead parameter suggests a scheduling path that doesn't exist.
**Fix:** Remove the parameter.

### IN-05: Sweep failures on GET /runs are logged at DEBUG — a persistently failing recovery sweep is invisible in production

**File:** `app/main.py:1062-1065`
**Issue:** `sweep_stranded_runs` is the DATA-03 recovery mechanism; if it starts failing on every page load (e.g. after a schema drift), `logger.debug` means nobody sees it at default log levels while stranded runs quietly stop being recovered. The load_all_runs debug precedent is weaker justification here because the sweep failure has no user-visible symptom (the list still renders).
**Fix:** Log at WARNING with the exception type.

### IN-06: Redundant condition in the alias-diff gate

**File:** `app/pipeline/orchestrator.py:624-625`
**Issue:** `if _none_tokens and _pre_candidates:` — `_none_tokens` is derived from `_pre_candidates`, so a non-empty `_none_tokens` implies a non-empty `_pre_candidates`; the second operand is dead.
**Fix:** `if _none_tokens:`.

---

_Reviewed: 2026-07-04T03:50:41Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
