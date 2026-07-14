---
phase: 16-queue-substrate-unblocked-webhook
plan: 01
subsystem: api
tags: [fastapi, starlette, run_in_threadpool, asyncio, httpx, webhook, psycopg]

# Dependency graph
requires: []
provides:
  - "app/routes/webhook.py::_parse_and_ingest_sync — sync helper (gateway.parse_inbound fetch + the 5-outcome ingest transaction), invoked via run_in_threadpool"
  - "app/routes/webhook.py::_duplicate_redelivery_sync — sync helper for the duplicate-branch redelivery-reschedule check, invoked via run_in_threadpool"
  - "app/routes/webhook.py::IngestResult — frozen dataclass carrying the ingest outcome across the worker-thread boundary"
  - "tests/test_webhook_unblocked.py — Proof 1 (event-loop non-blocking) + the reply-candidate BackgroundTask threadpool-hop proof"
affects: [16-02, 16-03, 16-06, 16-07, 16-08, 16-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "run_in_threadpool around blocking I/O in an async def route — the route stays async def; only the blocking body moves to a worker thread"
    - "httpx.AsyncClient + ASGITransport + asyncio.gather for genuine event-loop concurrency proofs, never starlette.testclient.TestClient (its portal serializes concurrent callers onto one thread)"
    - "cross-thread BackgroundTasks handoff documented at the call site AND proven by a spy test, not assumed safe in a comment"

key-files:
  created:
    - tests/test_webhook_unblocked.py
  modified:
    - app/routes/webhook.py

key-decisions:
  - "IngestResult is a frozen dataclass carrying exactly the locals the post-commit response-shaping block needs (outcome, email, cleaned, email_id, existing_run_id, reply_run_id, late_run_id, business_id, run_id, parse_error) — mirrors the plan's must_haves artifact spec verbatim."
  - "_duplicate_redelivery_sync returns (run_id, InboundEmail) | None rather than scheduling the BackgroundTask itself — scheduling from inside a worker thread would attach the task to the wrong context; the route (back on the loop after the await) does the actual background_tasks.add_task call."
  - "pipeline_glue.finish_reply_resume is wrapped in run_in_threadpool by reference (pipeline_glue.finish_reply_resume, not a bare-name import) so the existing monkeypatch seam stays live (BOUND-01)."

patterns-established:
  - "Pattern: a blocking-I/O route body is split into ONE synchronous helper function returning a small immutable result type, called via `await run_in_threadpool(helper, *args)`; response shaping and BackgroundTasks scheduling stay strictly on the loop, after the await returns."

requirements-completed: [QUEUE-01]

coverage:
  - id: D1
    description: "The webhook route no longer blocks the event loop on gateway.parse_inbound's Resend fetch or the 5-outcome ingest transaction — both run in a worker thread via run_in_threadpool, proven by two concurrent slow requests completing in ~1x, not ~2x, the slow duration."
    requirement: "QUEUE-01"
    verification:
      - kind: unit
        ref: "tests/test_webhook_unblocked.py#test_two_concurrent_webhooks_run_in_parallel_not_serially"
        status: pass
    human_judgment: false
  - id: D2
    description: "The duplicate-redelivery branch's blocking repo reads (get_inbound_by_message_id, load_run, the reply_sender_ok spoof guard) also run off-loop via run_in_threadpool (D-11) — closing the loop-blocking surface outside the main ingest transaction's cited file:line scope."
    verification:
      - kind: unit
        ref: "tests/test_reply_redelivery.py (full module, unchanged, still green)"
        status: pass
    human_judgment: false
  - id: D3
    description: "The reply-candidate branch's finish_reply_resume (which appends to the request-owned BackgroundTasks from inside a worker thread) is proven to actually schedule and actually execute after the run_in_threadpool hop — not merely assumed safe in a comment."
    verification:
      - kind: unit
        ref: "tests/test_webhook_unblocked.py#test_reply_candidate_background_task_survives_the_threadpool_hop"
        status: pass
    human_judgment: false
  - id: D4
    description: "The entire pre-existing webhook suite (test_webhook.py, test_ingest.py, test_gateway.py, test_reply_redelivery.py) passes UNCHANGED — the response contract for all five ingest outcomes plus 400/502 is byte-identical after the refactor, with zero edits to any existing test file."
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_webhook.py tests/test_ingest.py tests/test_gateway.py tests/test_reply_redelivery.py -q"
        status: pass
    human_judgment: false

# Metrics
duration: 12min
completed: 2026-07-14
status: complete
---

# Phase 16 Plan 01: Unblocked Webhook Summary

**The webhook's Resend fetch, 5-outcome ingest transaction, duplicate-redelivery reads, and reply-candidate resume all now run in a worker thread via `run_in_threadpool` — the event loop's only remaining work in `/webhook/inbound` is reading the body, verifying the HMAC, and shaping JSON, proven by two concurrent 0.6s-slow requests completing in ~0.6s wall-clock, not ~1.2s.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-14T11:04:00-07:00 (approx.)
- **Completed:** 2026-07-14T11:16:00-07:00 (approx.)
- **Tasks:** 3
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments

- Extracted `_parse_and_ingest_sync` — the Resend fetch (`gateway.parse_inbound`) plus the 5-outcome ingest transaction — into one module-level sync helper returning a frozen `IngestResult` dataclass, invoked from the still-`async def` route via `await run_in_threadpool(...)`. The `await request.body()` read and the full Svix HMAC verification block stay unchanged, in the same order, on the loop.
- Closed the remaining loop-blocking surface outside the main ingest transaction's cited scope (D-11): the duplicate-branch redelivery-reschedule check (`get_inbound_by_message_id`, `load_run`, the `reply_sender_ok` spoof guard) moved into a new `_duplicate_redelivery_sync` helper, and the reply-candidate branch's `pipeline_glue.finish_reply_resume` call is now wrapped in `run_in_threadpool` too — resolved as a module attribute at call time so the existing `monkeypatch.setattr(pipeline_glue, ...)` seam stays live.
- Wrote Proof 1 (`tests/test_webhook_unblocked.py`): two concurrent POSTs against a plain-sync `gateway.parse_inbound` stub that blocks 0.6s via `time.sleep` complete in `< 1.5 * SLOW_S` wall-clock, both responses are 200/`accepted`, and the stub ran exactly twice (anti-vacuity — a route that 400s/502s on both requests would otherwise satisfy the timing assertion trivially). Driven via `httpx.AsyncClient(transport=ASGITransport(app=app))` + `asyncio.gather`, never `starlette.testclient.TestClient` (whose internal portal serializes concurrent callers onto one thread — the exact vacuous-proof failure mode this repo already shipped once, per `tests/test_concurrency_proof.py`'s own documented precedent).
- Wrote a second proof in the same file proving the cross-thread `BackgroundTasks` handoff on the reply path actually works: seeds an `AWAITING_REPLY` run with a matching outbound clarification row, spies on `resume_pipeline_bg`, and asserts the spy WAS called with the matched `run_id` AND the CLEANED body (not the raw one) — a response-shape assertion (`200`/`"resumed"`) alone cannot see a `BackgroundTasks.add_task` call that appended successfully but whose task never drained.
- Both falsifying mutations were executed against the live code and confirmed RED, then reverted (see below).

## Task Commits

Each task was committed atomically:

1. **Task 1: Move the Resend fetch and the 5-outcome ingest transaction off the event loop** - `e46419d` (feat)
2. **Task 2: Move the duplicate-redelivery and reply-candidate branches' blocking repo reads off-loop (D-11)** - `c0061f8` (feat)
3. **Task 3: Proof 1 — two concurrent webhooks run in parallel; plus the reply-candidate BackgroundTask survives the threadpool hop** - `f62196a` (test)

_Note: Task 3's commit also carries a small comment-provenance fix to app/routes/webhook.py (see Deviations below) — no separate commit was warranted for a two-line docstring/comment rewrite discovered while verifying Task 3._

## Files Created/Modified

- `app/routes/webhook.py` - Route body split into `_parse_and_ingest_sync` (parse + 5-outcome ingest transaction) and `_duplicate_redelivery_sync` (duplicate-branch redelivery check), both invoked via `run_in_threadpool`; `pipeline_glue.finish_reply_resume` also wrapped in `run_in_threadpool`; new `IngestResult` frozen dataclass carries the outcome across the worker-thread boundary. Route stays `async def`; `await request.body()` and the Svix HMAC verification block are unchanged.
- `tests/test_webhook_unblocked.py` - NEW. Proof 1 (event-loop non-blocking, `httpx.AsyncClient` + `ASGITransport` + `asyncio.gather`) and the reply-candidate cross-thread `BackgroundTasks` proof. Hermetic — `fake_repo`, no live DB, no live LLM.

## Decisions Made

- `IngestResult` is a frozen dataclass carrying exactly the locals the post-commit response-shaping block reads today (`outcome`, `email`, `cleaned`, `email_id`, `existing_run_id`, `reply_run_id`, `late_run_id`, `business_id`, `run_id`, `parse_error`) — matches the plan's must_haves artifact spec verbatim, no extra/missing fields.
- `_duplicate_redelivery_sync` returns `(run_id, InboundEmail) | None` rather than scheduling the `BackgroundTask` itself from inside the worker thread — the route (back on the loop, after the `await` resumes) performs the actual `background_tasks.add_task` call, keeping task scheduling strictly on the loop everywhere in this file.
- `pipeline_glue.finish_reply_resume` is invoked as `run_in_threadpool(pipeline_glue.finish_reply_resume, ...)` — a module-attribute reference, not a bare-name import — so `monkeypatch.setattr(pipeline_glue, "finish_reply_resume", ...)` continues to intercept it in any future test that needs to (BOUND-01 discipline, matching this repo's existing convention).
- The `late_reply`, `unknown_sender`, and `new_run` branches were left untouched on the loop, per the plan's explicit scope fence: they perform no DB I/O in this branch shape, and migrating the other `BackgroundTasks` producers (including `new_run`'s `run_pipeline_bg` scheduling) is Phase 19 (QUEUE-04), not this plan.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug / CLAUDE.md enforcement] Removed two `D-11` decision-ID citations from webhook.py comments**
- **Found during:** Task 3 (running the full hermetic suite before committing)
- **Issue:** `tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree` — a pre-existing, always-on CI guard in this repo — failed because two comments/docstrings I wrote in Task 2 cited `(D-11)`/`D-11:` as provenance for the duplicate-redelivery-check refactor. This repo's comment-hygiene convention (established in v3 Phase 15, enforced repo-wide) requires comments to state the constraint directly rather than cite the planning decision that produced it — a decision-ID citation decays once the planning document is archived, while the constraint itself does not.
- **Fix:** Rewrote both citations to state the constraint in plain English instead: the class docstring now reads "Every blocking repo read the response-shaping 'duplicate' branch performs is moved off the event loop here, not just the main ingest transaction — otherwise 'the webhook never blocks the event loop' would be true only on the happy path," and the inline comment drops the `D-11:` prefix entirely.
- **Files modified:** `app/routes/webhook.py` (2 comment/docstring edits, no code-behavior change)
- **Verification:** `uv run pytest -q` — full hermetic suite (645 passed, 53 skipped) including the comment-provenance guard, green.
- **Committed in:** `f62196a` (part of Task 3's commit — discovered while verifying Task 3, a two-line comment fix not warranting its own commit)

**2. [Rule 3 - Blocking] `tests/test_webhook_unblocked.py`'s own module docstring also tripped the same guard on a `16-01-SUMMARY.md` citation**
- **Found during:** Task 3 (same suite run as above)
- **Issue:** The `planning-doc-ref` pattern in the same guard flags citations of planning documents (`SUMMARY.md`, `PLAN.md`, etc.) inside source text, since a future reader of the test file has no access to that document.
- **Fix:** Reworded the falsifying-mutations docstring section to say "the RED output is recorded in this phase's execution record" instead of naming `16-01-SUMMARY.md` directly.
- **Files modified:** `tests/test_webhook_unblocked.py` (1 docstring edit, written before the file's first commit — no separate commit needed)
- **Verification:** Same full-suite green run as above.
- **Committed in:** `f62196a` (the file's only commit — this fix was applied before Task 3 was ever committed)

---

**Total deviations:** 2 auto-fixed (both Rule 1/CLAUDE.md-driven comment-provenance fixes, zero behavior change)
**Impact on plan:** Both fixes are pure comment rewording required by this repo's pre-existing, unrelated comment-hygiene CI guard. No scope creep, no behavior change, no test assertions altered.

## Issues Encountered

None beyond the comment-provenance guard trips documented above — both caught by the plan's own instruction to run `uv run pytest -q` before considering each task done.

## Falsifying Mutations — RED Evidence (required by the plan's `<output>` spec)

Both mutations were applied directly to the committed code, run, confirmed RED, then reverted (git diff confirmed clean before re-committing nothing further — these mutations never touched a committed state).

### Mutation (a) — Proof 1: direct call instead of `run_in_threadpool`

Reverted `result = await run_in_threadpool(_parse_and_ingest_sync, raw_body)` to `result = _parse_and_ingest_sync(raw_body)` (a direct call, no threadpool hop) and re-ran Proof 1's first test:

```
FAILED tests/test_webhook_unblocked.py::test_two_concurrent_webhooks_run_in_parallel_not_serially
AssertionError: elapsed=1.23s suggests the two requests were serialized, not run concurrently
off the event loop (expected ~0.6s, not ~1.2s)
assert 1.2341972090071067 < (1.5 * 0.6)
1 failed in 1.87s
```

Wall-clock jumped from ~0.6s (parallel, GREEN) to ~1.23s (serial, RED) — confirming the two slow parses genuinely serialize on the event loop without the `run_in_threadpool` hop, and that the test can actually detect the regression it exists to catch. Reverted immediately after capturing this output; `git diff --stat app/routes/webhook.py` confirmed clean before proceeding.

### Mutation (b) — Proof 2: no-op the `background_tasks.add_task` call inside `finish_reply_resume`

Commented out `background_tasks.add_task(resume_pipeline_bg, run_id, reply_for_resume)` inside `app/routes/pipeline_glue.py::finish_reply_resume` and re-ran the second test:

```
FAILED tests/test_webhook_unblocked.py::test_reply_candidate_background_task_survives_the_threadpool_hop
AssertionError: resume_pipeline_bg must actually be invoked after the response — a
BackgroundTasks.add_task appended from inside the worker thread finish_reply_resume ran in
must survive the run_in_threadpool hop, not merely produce a 'resumed' response body
assert 0 == 1
 +  where 0 = len([])
1 failed in 0.48s
```

The test reached and failed on the "spy WAS called" assertion (`0 == 1`) — meaning the prior `response.status_code == 200` and `body["status"] == "resumed"` assertions still PASSED, exactly demonstrating why a response-shape check alone cannot see a silently-dropped `BackgroundTask`. Reverted immediately after capturing this output; `git diff --stat app/routes/pipeline_glue.py` confirmed clean (no diff) before proceeding.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- QUEUE-01 is fully closed: the webhook route never blocks the event loop on any branch (main ingest, duplicate-redelivery, reply-candidate resume) — zero new schema, as scoped.
- `app/routes/webhook.py`'s `_parse_and_ingest_sync`, `_duplicate_redelivery_sync`, and `IngestResult` are now the load-bearing symbols other 16-0x plans reference per the phase's artifact inventory table — no further changes to this file are expected from those plans (they build the `jobs` table, the queue package, and retrigger's transaction refactor in `app/routes/runs.py` instead).
- No blockers. `uv run pytest -q` is green (645 passed, 53 skipped), `uv run ruff check .` and `uv run mypy app` are clean.

## Self-Check: PASSED

- FOUND: app/routes/webhook.py
- FOUND: tests/test_webhook_unblocked.py
- FOUND: .planning/phases/16-queue-substrate-unblocked-webhook/16-01-SUMMARY.md
- FOUND: e46419d (Task 1 commit)
- FOUND: c0061f8 (Task 2 commit)
- FOUND: f62196a (Task 3 commit)

---
*Phase: 16-queue-substrate-unblocked-webhook*
*Completed: 2026-07-14*
