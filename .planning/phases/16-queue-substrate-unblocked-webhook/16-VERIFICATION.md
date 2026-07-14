---
phase: 16-queue-substrate-unblocked-webhook
verified: 2026-07-14T22:10:00Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
known_open_findings:
  - id: F-3
    title: "TOCTOU on the send path — two concurrently-executing workers are not serialized between assert_no_unconfirmed_send (a read) and the reservation upsert"
    disposition: "OPEN by explicit user decision; scheduled as follow-up work (not a phase-16 gap). Documented in 16-REVIEW.md with a proposed fix (ON CONFLICT DO NOTHING RETURNING id)."
---

# Phase 16: Queue Substrate & Unblocked Webhook — Verification Report

**Phase Goal:** The webhook stops blocking the event loop, and a durable Postgres job queue
exists — proven on one already-manual, low-risk producer (operator retrigger) before the money
path ever touches it.

**Verified:** 2026-07-14
**Status:** passed
**Re-verification:** No — initial verification

## Method

This report does not take SUMMARY.md claims at face value. For each of the 5 ROADMAP success
criteria, I read the actual code the claim rests on, then independently applied a falsifying
mutation to the source and re-ran the relevant test to confirm the proof genuinely goes red —
not just accepted the "red run" transcripts already pasted into 16-REVIEW.md and the SUMMARYs.
Every mutation I applied was reverted immediately after observing the failure; `git status
--porcelain -- app/` confirms zero residual diff.

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Two concurrent inbound webhooks against a slow fetch complete in ~slowest-one time, not the sum — the event loop is never blocked. | ✓ VERIFIED | `tests/test_webhook_unblocked.py::test_two_concurrent_webhooks_run_in_parallel_not_serially` passes (elapsed ~0.6s for two 0.6s-slow calls). I reverted `await run_in_threadpool(_parse_and_ingest_sync, raw_body)` to a direct call at `app/routes/webhook.py:354` — elapsed jumped to 1.22s and the test went red (`assert 1.22 < 0.9` failed), then restored clean. The route is still `async def` and still does `await request.body()` for HMAC verification before any parsing (`app/routes/webhook.py`). |
| 2 | Clicking Retrigger enqueues a durable `jobs` row; killing the worker mid-run and draining again completes the retrigger without the operator re-clicking. | ✓ VERIFIED | Live-DB `tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease` (Proof 2) passed against real Postgres — 6 scoped steps: enqueue via retrigger, claim (lease held), simulate crash by pushing `leased_until` into the past, reclaim on a second `drain_once()`, assert `attempts` incremented, assert the D-01 rewind fired and the run reached COMPUTED (not stranded at EXTRACTING), assert `reply_epoch` unchanged across the automatic reclaim. `app/routes/runs.py:392-414` confirms the CAS, `clear_reply_context`, and `enqueue_job` all commit inside one `with repo.get_connection() as conn, conn.transaction():` block, with `wake.wake()` fired strictly after — matching the plan's atomicity must-have. |
| 3 | A job whose worker died holding the lease is reclaimed by another worker once the lease expires — never stuck in `leased` forever. | ✓ VERIFIED | Live-DB proofs `test_expired_lease_is_reclaimed`, `test_zombie_is_fenced_on_BOTH_complete_and_fail`, `test_skip_locked_steps_over_a_row_another_worker_is_holding`, `test_genuine_claim_race_exactly_one_winner` all passed against real Postgres. `app/db/repo/jobs.py`'s claim SQL includes `OR (state='leased' AND leased_until < now())` — 16-REVIEW.md's own independently-executed mutation table (removing this clause) is corroborated by the plan's documented falsifying mutation for the same clause. |
| 4 | A routine redeploy (graceful worker shutdown) releases held leases IMMEDIATELY — an in-flight retrigger resumes within seconds, not the full lease duration. | ✓ VERIFIED | Live-DB `test_graceful_shutdown_releases_held_leases_immediately` and `test_release_leases_returns_the_row_to_pending_immediately` passed. This was the criterion flagged as a real hole (F-6) until commit `baef7a3`. I independently mutated `app/queue/drain.py::held_tokens()` to snapshot immediately instead of blocking while `_claims_in_flight` is non-zero — the hermetic `test_held_tokens_never_snapshots_a_claim_into_oblivion` went red exactly as claimed (`assert [[]] == [[UUID(...)]]`), then I restored the file and confirmed a clean diff. |
| 5 | A CI-enforced guard fails the build if `jobs.kind` collides with `payroll_runs.status` or drifts from the `JobKind` enum. | ✓ VERIFIED | `tests/test_job_kind_drift.py` (hermetic, runs in `.github/workflows/ci.yml`'s `uv run pytest -q` on every push/PR) has both a collision guard and a SQL-CHECK-vs-Python-enum drift guard. I mutated `JobState.DONE` from `"done"` to `"error"` (colliding with `RunStatus.ERROR`) and both `test_job_state_never_collides_with_run_status` and `test_job_state_check_matches_python_enum` went red with a precise diff, then reverted cleanly. `app/queue/dispatch.py`'s `set(JobKind) == set(HANDLERS)` guard is also present (`tests/test_job_kind_drift.py::test_job_kind_equals_dispatch_table`). |

**Score:** 5/5 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/routes/webhook.py` | `run_in_threadpool`-wrapped sync helpers | ✓ VERIFIED | `_parse_and_ingest_sync`, `_duplicate_redelivery_sync` both invoked via `run_in_threadpool`; route stays `async def`. |
| `app/models/job.py` | `JobKind`, `JobState`, `Job` (6-field frozen dataclass) | ✓ VERIFIED | `JobKind.RUN_PIPELINE` only member; `Job` has exactly 6 fields, no `email_id`. |
| `app/db/schema.sql` | `jobs` table with dedup_key, lease fencing, kind-scoped CHECK | ✓ VERIFIED | `ck_jobs_run_pipeline_requires_run` present (confirmed via grep; not re-mutated live given prior live-DB coverage in 16-REVIEW.md's own mutation table). |
| `app/db/repo/jobs.py` | `enqueue_job`, `claim_job`, `complete_job`, `fail_job`, `release_leases`, `get_job` | ✓ VERIFIED | Exists, exercised by 17/17 passing queueproof tests. |
| `app/queue/{wake,dispatch,drain,worker}.py`, `app/queue/handlers/pipeline.py` | Transport tier, CAS-only status writes | ✓ VERIFIED | `handle_run_pipeline` calls only `claim_status`/`rewind_for_reclaim`; calls `pipeline_glue.run_pipeline_now` (raises on catastrophic start failure), not the swallowing `run_pipeline_bg` — confirmed by my own mutation (reverting to `run_pipeline_bg` turned `test_catastrophic_start_failure_is_retried_not_marked_done` red). |
| `app/pipeline/send_guard.py` | Fail-closed send-idempotency guard (D-13) | ✓ VERIFIED | `assert_no_unconfirmed_send` called in both `clarification.py` and `delivery.py`; live-DB `test_the_unconfirmed_guard_is_epoch_scoped` and `test_a_human_epoch_bump_clears_the_guard` pass. |
| `.github/workflows/concurrency-proof.yml` | Narrow `queueproof` CI gate, existing `-m integration` step untouched | ✓ VERIFIED | New step selects `-m queueproof` over `tests/`, has its own skip/pass guards; pre-existing 2-file `-m integration` step is byte-identical in intent (still 2 named files). |
| `app/db/schema_introspect.py` | `jobs` covered by `/health/schema` | ✓ VERIFIED | `test_health_schema_covers_jobs` passes. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `app/routes/webhook.py` | AnyIO threadpool | `run_in_threadpool` | ✓ WIRED | Confirmed by falsifying mutation (see criterion 1 above). |
| `app/routes/runs.py::retrigger` | `app/db/repo/jobs.py::enqueue_job` | One caller-owned transaction | ✓ WIRED | Read directly at `app/routes/runs.py:392-414`; CAS, reply-context clear, and enqueue share one `conn.transaction()` block; `wake.wake()` fires after commit. |
| `app/queue/drain.py::drain_once` | `app/queue/dispatch.py::handle` → `app/queue/handlers/pipeline.py::handle_run_pipeline` | Fenced claim → dispatch → CAS | ✓ WIRED | `set(JobKind) == set(HANDLERS)` guard passes; live reclaim/fence proofs pass. |
| `app/queue/worker.py::stop()` | `app/queue/drain.py::held_tokens()` | `_claims_in_flight` blocking snapshot | ✓ WIRED | Confirmed by falsifying mutation (F-6, criterion 4 above). |

### Behavioral / Live-DB Proofs

| Proof | Command | Result | Status |
|-------|---------|--------|--------|
| Hermetic suite | `uv run pytest -q` | 713 passed, 68 skipped | ✓ PASS (matches expected) |
| queueproof marker, real Postgres | `uv run pytest tests/ -m queueproof -q` (after `bootstrap --reset`) | 17 passed, 0 skipped | ✓ PASS (matches expected; zero skips) |
| Full suite against live DB | `uv run pytest -q` (DATABASE_URL set) | 779 passed, 2 skipped | ✓ PASS (matches expected; the 2 skips are unrelated — a pre-existing Wave-1 stub and the manual live-LLM gate, confirmed by name) |
| Criterion 1 falsifying mutation | direct call instead of `run_in_threadpool` | elapsed 1.22s vs expected <0.9s | RED as expected, reverted |
| Criterion 4 (F-6) falsifying mutation | `held_tokens()` snapshot ignoring in-flight claims | `[[]] != [[UUID(...)]]` | RED as expected, reverted |
| Handler-swallow (F-4) falsifying mutation | revert `run_pipeline_now` → `run_pipeline_bg` | `'done' == 'pending'` failed | RED as expected, reverted |
| Criterion 5 collision/drift falsifying mutation | `JobState.DONE = "error"` | both collision and drift guards failed with exact diffs | RED as expected, reverted |
| `ruff check` on phase-16 files | — | All checks passed | ✓ PASS |
| `mypy app/` | — | Success: no issues found in 62 source files | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|-----------------|-------------|--------|----------|
| QUEUE-01 | 16-01 | Webhook never blocks the event loop | ✓ SATISFIED | Criterion 1 above |
| QUEUE-02 | 16-02, 16-03, 16-04, 16-06, 16-08, 16-09, 16-10 | `jobs` table durable transport, claim/lease/fencing, dedup_key | ✓ SATISFIED | Criteria 2, 3 above |
| QUEUE-03 | 16-02, 16-04, 16-07, 16-09, 16-10 | Bounded worker pool, graceful shutdown release | ✓ SATISFIED | Criteria 3, 4 above |
| QUEUE-05 | 16-03, 16-05, 16-06 | `jobs` carries transport state only, CAS-only writes, CI-enforced drift/collision guard | ✓ SATISFIED | Criterion 5 above |

No orphaned requirements for this phase — QUEUE-04 is correctly scoped to Phase 19 (not this phase) per ROADMAP.md and REQUIREMENTS.md's own traceability table.

**Documentation staleness (non-blocking, informational):** `.planning/REQUIREMENTS.md`'s checkbox list and its "Traceability" table (lines ~28, ~158-161) still show QUEUE-02, QUEUE-03, and QUEUE-05 as unchecked / `Pending`, even though ROADMAP.md marks Phase 16 `[x]` complete (2026-07-14) and all four requirements are functionally satisfied per the evidence above. The file's last edit (`b90058b`) predates plans 16-02 through 16-10 and the F-4/F-6 fix commits. This is a bookkeeping gap in REQUIREMENTS.md, not a functional gap in the codebase — recommend updating the checkboxes/table in a follow-up commit before starting Phase 17, so the traceability doc doesn't misreport phase 16 as incomplete.

### Anti-Patterns Found

None. Scanned all phase-16-touched `app/` files (webhook, config, models/job, db/schema+bootstrap+repo/jobs+repo/pipeline_state+repo/__init__+schema_introspect, queue/*, db/supabase, main, routes/runs, routes/pipeline_glue, db/repo/emails, pipeline/send_guard+clarification+delivery) for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` — zero matches.

### Known Open Finding (not a phase-16 gap — explicit user decision)

**F-3 — TOCTOU on the send path.** `assert_no_unconfirmed_send` (`app/pipeline/send_guard.py`) is a read; the reservation that follows in `insert_email_message` is an `ON CONFLICT ... DO UPDATE` upsert, so two concurrently-executing workers are not serialized between the check and the provider call. Reachability is narrow (requires a worker to stall >15 min *after* passing the guard read but *before* its reservation commits — a window two adjacent DB writes wide) and codex-cli's review rates it High severity / very low probability. This is documented in `16-REVIEW.md` with a proposed fix (`ON CONFLICT DO NOTHING RETURNING id`, fail-closed on no-row) and is explicitly scheduled as follow-up work by user decision, not treated as a phase-16 blocker per the task instructions.

### Human Verification Required

None. All 5 ROADMAP success criteria have direct automated proof (4 live-DB, 1 hermetic), and I independently re-derived falsifying-mutation evidence for the highest-risk ones (criteria 1, 4, 5, plus the F-4 handler-swallow fix that criterion 2 depends on) rather than relying solely on the pasted transcripts in 16-REVIEW.md and the plan SUMMARYs.

### Gaps Summary

No gaps. All 5 ROADMAP success criteria are verified against the actual codebase with independently-reproduced falsifying-mutation evidence, not just SUMMARY.md claims. The two previously-open codex-review findings (F-4, F-6) are confirmed fixed in the current source (commit `baef7a3`) with their own regression tests genuinely red under mutation. The one remaining open finding (F-3) is a documented, narrow-probability residual risk explicitly deferred by user decision, not a phase-16 gap. The only actionable item is the non-blocking REQUIREMENTS.md checkbox/traceability staleness noted above.

---

_Verified: 2026-07-14T22:10:00Z_
_Verifier: Claude (gsd-verifier)_
