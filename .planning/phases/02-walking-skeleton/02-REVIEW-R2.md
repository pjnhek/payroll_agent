---
phase: 02-walking-skeleton
reviewed: 2026-06-21T00:00:00Z
depth: standard
round: 2
files_reviewed: 6
files_reviewed_list:
  - app/pipeline/decide.py
  - app/pipeline/orchestrator.py
  - app/main.py
  - app/db/repo.py
  - app/pipeline/compose_email.py
  - app/pipeline/calculate.py
findings:
  critical: 0
  warning: 0
  info: 1
  total: 1
prior_findings:
  resolved: 8
  partially_resolved: 0
  not_resolved: 0
status: clean
verdict: CLEAN
---

# Phase 2: Code Review Report — ROUND 2 (fix verification)

**Reviewed:** 2026-06-21
**Depth:** standard
**Files Reviewed:** 6
**Status:** clean
**Verdict:** CLEAN (ready)

## Summary

Round 1 raised 2 Critical + 6 Warning findings. All 8 are **genuinely
RESOLVED** in the submitted code, each with a matching test that exercises the
specific failure mode the finding described. The fixes are surgical and do not
introduce new correctness, security, or status-transition regressions. The full
suite (168 tests, integration/live-LLM deselected) is green, including the five
files I re-ran in isolation (59 passed).

I traced every NEW-bug hypothesis the round-2 brief called out and found none of
them materialized:

- **Webhook pre-flip removal does not strand a reply.** `_route_reply`
  (`main.py:158-171`) no longer flips `EXTRACTING`; it schedules
  `_resume_pipeline` and returns `resumed`. `resume_pipeline`
  (`orchestrator.py:120-137`) re-asserts `awaiting_reply`, sets `EXTRACTING`,
  and runs the shared `_run_stages` spine, which advances the run to
  `awaiting_approval`/`computed`. The end-to-end TestClient path is proven by
  `test_header_chain_match` (`test_threading.py:157-174`): the reply advances the
  run *past* `awaiting_reply`. No stranding path exists.
- **The empty-employees gate rule composes correctly with the other rules.**
  When `extracted.employees == []`, `submitted_names == []` →
  `reconcile_names([], roster) == []` → `validate(...) == []`. Rule 0 fires once;
  Rules 1-3 iterate empty collections (no-ops); `check_one_to_one([], extracted)`
  iterates empty `matches` and returns `[]` (no exception, no double-count). One
  `gate_reason`, `final_action == request_clarification`. Proven by
  `test_empty_extraction_blocks_process` (`test_gate.py:114-132`). The per-name
  confidence test (`< Decimal("0.8")`, strict) and the audit-only `min()` collapse
  are both unchanged (`decide.py:155-161, 183-185`).
- **The terminal no-op in `record_run_error` does not swallow legitimate errors.**
  The guard is `current is not None and current[0] in _TERMINAL_STATUSES`
  (`repo.py:303`). A non-terminal run (`received`/`extracting`/`computed`/
  `awaiting_approval`/`needs_clarification`/`awaiting_reply`) still records
  `error_reason` and advances to `ERROR`. Both branches are pinned:
  `test_record_run_error_skips_terminal_run` (terminal → no write) and
  `test_record_run_error_writes_for_non_terminal_run` (non-terminal → writes),
  `test_persistence.py:117-146`.
- **No Decimal/float, parameterized-SQL, or status-transition regression.** Money
  stays `Decimal` + `ROUND_HALF_UP` (`calculate.py:48-58`); all repo SQL stays
  `%s`/named-placeholder (`%(references)s`, `repo.py:497-500`); `set_status`
  remains the sole status writer and the nested `set_status(..., conn=c)` inside
  `record_run_error` correctly reuses the caller's transaction via `_nulltx()`.

The structural thesis (code-owned `final_action`, never `model_action`) remains
intact and is now strictly more robust on the degenerate zero-employee path.

## Prior-Finding Verification

### CR-01 — empty-extraction bypassed the gate → **RESOLVED**

**Evidence:** `decide.py:151-152` adds Rule 0:
`if not extracted.employees: gate_reasons.append("no employees could be extracted from the email")`.
A zero-employee `Extracted` with `model_action="process"` now yields
`final_action="request_clarification"` (`decide.py:177-178`,
`gate_fired = bool(gate_reasons)` is `True`). The per-name confidence evaluation
is UNCHANGED — still `m.confidence < _THRESHOLD` per `NameMatchResult`, strict
`<`, `_THRESHOLD = Decimal("0.8")` (`decide.py:54, 156`). The `min()` collapse at
`decide.py:183-185` is still audit-only (documented `decide.py:180-182`; the gate
never reads it). Test: `test_empty_extraction_blocks_process`
(`test_gate.py:114-132`) asserts `final_action == "request_clarification"`,
`gate_triggered is True`, and a "no employees" `gate_reason`.

### CR-02 — resume could clobber a terminal/approved run on a status race → **RESOLVED**

**Evidence:** `resume_pipeline` now re-asserts the precondition immediately before
mutating (`orchestrator.py:120-129`):
`if run["status"] != RunStatus.AWAITING_REPLY.value: ... return` — it RETURNS
(does not raise), so a late/duplicate reply is dropped and never routes through
`record_run_error` to ERROR. The `EXTRACTING` flip and `_run_stages` happen only
*after* the precondition passes (`orchestrator.py:136-137`). The webhook no longer
pre-flips status: `_route_reply` schedules `_resume_pipeline` and returns
`resumed` with NO `set_status` call (`main.py:158-171`, the deleted pre-flip is
documented at `main.py:159-165`). Tests: `test_resume_precondition` family
(`test_threading.py:359-422`) proves a resume on an already-`approved` run does
NOT mutate status, does NOT call `extract`, and is NOT clobbered to ERROR;
`test_header_chain_match` proves the happy path still advances. The residual
non-row-locked race is the documented, ACCEPTED Phase-2 limitation
(`orchestrator.py:109-114`) — the precondition is effective (it guards the actual
mutation in the same function/context), so per the brief it is NOT re-flagged.

### WR-01 — silent employee-drop on a process run with an out-of-roster match → **RESOLVED**

**Evidence:** `_compute_line_items` now RAISES on the invariant violation
(`orchestrator.py:233-245`): `employee = emp_by_id.get(m.matched_employee_id);
if employee is None: raise ValueError("process-run integrity: ...")`. The raise
propagates to `run_pipeline`'s error-wrap (`orchestrator.py:59-65`) →
`record_run_error` → ERROR, rather than shipping a short payroll. The
unresolved-name `continue` at `orchestrator.py:231-232` is correct and unrelated
(those never reach a process run — the gate blocks them).

### WR-02 — unanchored Message-ID `References` LIKE → **RESOLVED**

**Evidence:** `_pad_references` (`repo.py:473-488`) normalizes the header to a
space-padded, whitespace-collapsed token string; the shared predicate
`_HEADER_MATCH_PREDICATE` (`repo.py:497-500`) matches
`%(references)s LIKE '%% ' || em.message_id || ' %%'` — a whitespace-bounded
WHOLE-token comparison, so `<a@x>` cannot match inside `<a@xtra>`. SQL stays
parameterized: both `in_reply_to` and `references` are NAMED placeholders
(`repo.py:521-525, 547-552`), no f-string/%-format SQL introduced (verified by
`test_repo_has_no_fstring_sql` and `test_references_like_is_parameterized`).
Anchoring proven by `test_pad_references_anchors_whole_tokens`
(`test_threading.py:211-235`).

### WR-03 — `call_text` API error ERRORed the run → **RESOLVED**

**Evidence:** `compose_clarification` now wraps the `call_text` call in
`try/except Exception` (`compose_email.py:83-91`), logs, sets `body=None` +
`api_error=True`, and falls through to `_template_body(decision)` on both an API
error AND empty content (`compose_email.py:92-97`). The empty-content case is also
now logged (`compose_email.py:95-96`), closing the "silently templating" gap. So a
draft auth/rate-limit failure degrades to the template instead of routing the run
to ERROR. Tests: `test_clarify.py` covers both the API-error fallback (the
raising stub, lines 79-115) and the no-args subject.

### WR-04 — `record_run_error` clobbered terminal status → **RESOLVED**

**Evidence:** `record_run_error` reads the current status inside the same
transaction and no-ops on a terminal run (`repo.py:298-316`):
`_TERMINAL_STATUSES = {APPROVED, SENT, RECONCILED, REJECTED, ERROR}`
(`repo.py:86-94`); the guard `if current is not None and current[0] in
_TERMINAL_STATUSES: ... return` skips the `error_reason` UPDATE and the
`set_status(ERROR)`. A non-terminal run still records + advances. Both branches
tested (`test_persistence.py:117-146`). The `InMemoryRepo` mirror
(`conftest.py:270-278`) matches the real guard, so the orchestrator-level CR-02
test correctly sees an approved run stay approved.

### WR-05 — dead `decision` param on `clarification_subject` → **RESOLVED**

**Evidence:** `clarification_subject()` now takes NO arguments
(`compose_email.py:101-109`) and the sole call site passes none
(`orchestrator.py:215`). No dangling references remain (grep across `app/` +
`tests/` confirms every call is `clarification_subject()`). Test:
`test_clarification_subject_takes_no_args` (`test_clarify.py:122-135`) asserts an
empty signature and that calling it with an argument raises `TypeError`.

### WR-06 — misleading "banker-safe" docstring on `_money` → **RESOLVED**

**Evidence:** `_money` docstring now correctly states ROUND_HALF_UP is "round half
AWAY from zero" and explicitly contrasts it with banker's rounding
(ROUND_HALF_EVEN) (`calculate.py:48-58`). The behavior is UNCHANGED:
`value.quantize(_CENTS, rounding=ROUND_HALF_UP)` (`calculate.py:58`), money stays
`Decimal` throughout the calc path. No rounding behavior changed; only the comment
was corrected.

## Narrative Findings (AI reviewer)

No NEW Critical or Warning findings. One Info-level observation below; it is a
non-blocking test-coverage note, not a defect in the shipped code.

## Info

### IN-01: The DB-free `record_run_error` happy-path test does not exercise the new terminal guard

**File:** `tests/test_gateway.py:163-182`
**Issue:** `test_record_run_error_writes_reason_and_routes_through_set_status`
passes a fresh `FakeConnection` with no scripted `fetchone`, so the new
`SELECT status` read-back returns `None`. With `current is None`, the terminal
guard at `repo.py:303` is short-circuited and the error is written — the test
passes, but it silently relies on the `None` path rather than asserting the guard.
This is harmless because the *behavioral* terminal/non-terminal branches ARE
explicitly covered by `test_record_run_error_skips_terminal_run` and
`test_record_run_error_writes_for_non_terminal_run` (`test_persistence.py:117-146`),
which script `("approved",)` and `("extracting",)` respectively. The shipped code
is correct and well-tested; this is only a note that the older gateway test now
exercises a degenerate (`status row missing`) path.
**Fix:** Optional. Script a non-terminal status in the gateway test
(`fake_conn.script_fetchone(("extracting",))`) so its `SELECT status` read-back is
realistic, or rely solely on the two persistence tests and leave a comment.

---

_Reviewed: 2026-06-21_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard (Round 2 fix-verification)_
