---
phase: 09-atomic-data-integrity
fixed_at: 2026-07-04T09:05:00Z
review_path: .planning/phases/09-atomic-data-integrity/09-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 2
skipped: 3
status: partial
---

# Phase 9: Code Review Fix Report

**Fixed at:** 2026-07-04T09:05:00Z
**Source review:** .planning/phases/09-atomic-data-integrity/09-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (WR-03, WR-04, WR-05, WR-06, WR-07 — 0 Critical)
- Fixed: 2 (WR-03, WR-07)
- Skipped: 3 (WR-04, WR-05, WR-06 — each requires design work on the money path; see reasons)

Verification after each fix: `uv run ruff check` on touched files + targeted test module,
then the FULL offline suite. Final state: **547 passed, 48 skipped** (live-DB tests skip
without `DATABASE_URL` + `ALLOW_DB_RESET=1`, as expected).

## Fixed Issues

### WR-03: Real-webhook reply rows are never linked to their run (`run_id=None`)

**Files modified:** `app/db/repo.py`, `app/main.py`, `tests/conftest.py`, `tests/test_webhook.py`
**Commit:** 8eb937e
**Applied fix:** Added `repo.link_email_to_run(email_id, run_id, conn=None)` (parameterized
`UPDATE email_messages SET run_id = %s WHERE id = %s`, `_conn_ctx`/`_nulltx` pattern like every
other helper) and call it INSIDE the existing ingest transaction in `app/main.py` for both
classified outcomes: `reply_candidate` (link to `reply_run_id`) and `late_reply` (link to
`late_run_id`). Real client replies now appear in `load_thread_messages`' run-detail thread
view and in join-based audits, matching the simulate-reply demo path.

Safety was traced against every `email_messages` consumer before applying (this is the
money-path ingest):
- `uq_email_run_purpose UNIQUE (run_id, purpose)`: inbound rows keep `purpose=NULL`, and
  Postgres never treats `(run_id, NULL)` rows as conflicting — no constraint risk.
- Every routing/idempotency query keyed on `email_messages.run_id` filters
  `direction='outbound'` (`find_awaiting_reply_for_header`, `find_any_run_for_header`,
  `get_outbound_message_id`, `get_outbound_references_chain`, `load_outbound_emails`) — linking
  inbound rows cannot affect reply routing, resume classification, or send idempotency.
- `find_run_by_message_id` (dedup-loser lookup) joins via `payroll_runs.source_email_id`,
  not `run_id` — unaffected.
- The FK target run is looked up inside the SAME transaction, so the link can never dangle.

Test infra: `InMemoryRepo.link_email_to_run` mirror added to `tests/conftest.py` + the
`fake_repo` patch list. New regression test
`tests/test_webhook.py::test_reply_and_late_reply_rows_linked_to_run` asserts BOTH classified
outcomes back-fill `run_id`.

### WR-07: Stale `strict=True` xfail on an implemented behavior guarantees a live-suite failure

**Files modified:** `tests/test_gateway.py`, `.planning/phases/09-atomic-data-integrity/deferred-items.md`
**Commit:** a676c52
**Applied fix:** Removed `@pytest.mark.xfail(strict=True, reason="implemented in 06-04")` from
`test_inbound_reply_routes_to_correct_run_integration` (kept `@pytest.mark.integration` and the
in-body two-factor skip guard), per the file's own documented convention that an XPASS is the
signal to remove the markers. Also corrected the inaccurate `deferred-items.md` entry that
attributed this test's live failure to a missing `ALLOW_UNSIGNED_FIXTURES` env var — the test
makes no HTTP request (it calls `find_awaiting_reply_for_header` directly), so its actual live
failure mode was the strict-xfail XPASS; the entry now records the correction and keeps the
still-valid `test_ingest.py::test_duplicate_delivery_pipeline_runs_once` action item.

Note: `uv run ruff check tests/test_gateway.py` reports 4 findings (E402/F841/F401 x2) — all
verified PRE-EXISTING at HEAD (identical output with the fix stashed); not introduced or
addressed here (they are also outside this review's IN-07 list).

## Skipped Issues

### WR-04: A persisted reply can be permanently dropped — duplicate redelivery never re-attempts the resume

**File:** `app/main.py:385-394`, `445-454`, `600-611`, `766-771`
**Reason:** Skipped — the suggested fix ("on the `duplicate` outcome, when the duplicate carries
reply headers and `find_awaiting_reply_for_header` still matches, re-schedule
`_resume_pipeline`") is unsafe as stated in multi-round scenarios. A run returns to
`awaiting_reply` after each subsequent clarification round, so a provider redelivery of an
ALREADY-CONSUMED Round-1 reply would still match the run (header finders match ANY sent outbound
row for the run) and would re-schedule a resume that processes the STALE Round-1 body as the
answer to the CURRENT round's different question — trading today's fail-safe hang (run never
processes; no wrong pay) for a potential wrong-processing path on a money-moving pipeline.
Distinguishing "durably persisted but never consumed" from "already consumed" replies requires
new state (e.g., per-reply consumed/round linkage — exactly the "new linking semantics for reply
rows" design work 09-VERIFICATION.md deferred). Note: the WR-03 fix (reply rows now carry
`run_id`) provides a building block for that future design.
**Original issue:** A post-commit failure before `background_tasks.add_task` makes the provider
redeliver, but the redelivery takes the `duplicate` path and returns 200 without re-running reply
classification; a resume task dying pre-claim leaves the run at `awaiting_reply` with no operator
recovery route.

### WR-05: `_clarify`'s purpose-scoped idempotency guard is round-blind — a second same-purpose clarification is silently never sent

**File:** `app/pipeline/orchestrator.py:980-995`, `app/db/repo.py` (`get_outbound_message_id`), `app/main.py:766-771`
**Reason:** Skipped — all three fix options the review offers are design choices on the CLAR-04
crash-safety guard, a money-path idempotency mechanism that multiple prior review rounds (finding
#2/CLAR-04, R3-2 purpose-scoping, N7 snapshot ordering, D-9-06 transaction shape) deliberately
pinned: (a) storing an asked-fields hash on the outbound row adds new persisted semantics; (b)
scoping the guard to the arrival transition requires plumbing origin-status knowledge into
`_clarify` and re-proving the CLAR-04 duplicate-send safety for every re-trigger path; (c) a
round counter in the uniqueness key changes the `uq_email_run_purpose` one-row-per-(run,purpose)
contract that `insert_email_message`'s upsert relies on. Weakening this guard incorrectly
re-introduces duplicate clarification emails; picking among the options is a design decision that
belongs in a planned phase (e.g. `/gsd-plan-phase` gap closure), not a review-fix pass instructed
to avoid speculative orchestrator changes. Not a wrong-pay path (the run parks and never
processes).
**Original issue:** `get_outbound_message_id(run_id, purpose=purpose)` cannot distinguish a
re-trigger of the SAME clarification from a genuinely NEW question in a later round, so a second
same-purpose clarification is skipped and the run parks at `awaiting_reply` with no operator
recovery route.

### WR-06: Terminal `clarified_fields` labels can survive a rolled-back run, then mislabel provenance after retrigger

**File:** `app/pipeline/orchestrator.py:589-618`, `app/main.py:690-798`
**Reason:** Skipped — the suggested fix ("at retrigger time, clear or archive `clarified_fields`
and `pre_clarify_extracted`") is not safely scoped as a blanket action. The retrigger route
claims from MULTIPLE states (ERROR, APPROVED, and stale RECEIVED/EXTRACTING/COMPUTED/SENT); for
several of them (e.g. an APPROVED run whose delivery failed AFTER a fully-persisted Round-2, or a
stale SENT run) the clarified provenance labels are CORRECT and clearing them would destroy a
valid audit trail at the exact human checkpoint the system relies on. Clearing only when the
labels are orphaned requires distinguishing "crash inside `_run_stages` rolled the values back"
from "values persisted, later stage failed" — new state or a consistency check between labels and
paid values (the review's alternative), both design work. The retrigger docstring already
documents reply-context-loss as an accepted limitation deferred alongside 260623-08 in
09-CONTEXT.md Deferred Ideas; this finding extends that same deferred design space. Additionally,
a wrong clear interacts with WR-05 (`is_round_2 = bool(clarified)` feeds the clarify guard), so
these two should be designed together.
**Original issue:** A crash inside `_run_stages` after the (correct) WR-02 fix leaves durable
terminal `clarified_fields` labels whose justifying values rolled back; after an operator
retrigger (which restarts from the original email), the run-detail provenance badges mislabel
paid values at the approval gate, and stale terminals feed future round logic.

---

_Fixed: 2026-07-04T09:05:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
