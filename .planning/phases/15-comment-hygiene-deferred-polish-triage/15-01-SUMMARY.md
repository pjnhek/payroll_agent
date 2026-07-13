---
phase: 15-comment-hygiene-deferred-polish-triage
plan: 01
subsystem: testing / CI
tags: [threading, retrigger, epoch-arbiter, append-only-audit-log, ci-gate]
requires:
  - app/routes/runs.py (POST /runs/{run_id}/retrigger)
  - app/routes/pipeline_glue.py (run_pipeline_bg)
  - app/pipeline/orchestrator.py (run_pipeline error boundary, _run_stages)
  - app/pipeline/clarification.py (clarify: send-then-persist ordering)
  - app/email/gateway.py (send_outbound threading-header derivation)
  - app/db/repo/emails.py (insert_email_message ON CONFLICT arbiter)
  - app/db/repo/pipeline_state.py (clear_reply_context reply_epoch bump)
  - app/db/schema.sql (uq_email_run_purpose_round_epoch)
provides:
  - executable proof that reply threading survives crash -> retrigger -> re-send
  - executable proof that the production 4-column ON CONFLICT arbiter appends
    rather than clobbering the delivered outbound row
  - a CI job that reds itself when a live-DB proof skips instead of executing
affects:
  - .github/workflows/concurrency-proof.yml (now runs two proofs + an execution guard)
tech-stack:
  added: []
  patterns:
    - one-shot failure injection at a post-send persistence step to manufacture a
      genuine crashed run through real pipeline code
    - whole-row SELECT * snapshot compare as the exact mutation surface of
      ON CONFLICT DO UPDATE SET
    - CI skip-guard: assert zero-skipped + at-least-one-passed rather than a
      hardcoded expected test count
key-files:
  created:
    - tests/test_retrigger_threading.py
    - tests/test_email_epoch_arbiter_integration.py
  modified:
    - .github/workflows/concurrency-proof.yml
decisions:
  - Stubbed suggest_employees on app.pipeline.clarification, not app.pipeline.suggest —
    clarification.py imports the bare name, so patching the source module would have
    been a no-op stub that silently left the seam live.
  - Kept "byte-for-byte unchanged" as a literal claim by comparing the whole row,
    and gave the compare teeth with a deliberately different subject/body on the
    second write.
metrics:
  duration: ~40 min
  tasks: 3
  files: 3
  completed: 2026-07-13
status: complete
---

# Phase 15 Plan 01: WR-01 Executable Threading + Epoch-Arbiter Proof Summary

The retrigger threading claim now has proof that is honest about which seam it
executes: a hermetic route-driven test for route/pipeline/gateway, a real-Postgres
test for the SQL upsert arbiter, and the CI wiring that makes the second one actually
run instead of silently skipping forever.

## What Was Built

**Task 1 — `tests/test_retrigger_threading.py`** (commit `c8553ba`, GREEN on first run).
Two hermetic tests driving the real `POST /runs/{run_id}/retrigger` route and the real
background pipeline. The crashed state is produced by real code: a one-shot failure
injected at `repo.set_pre_clarify_extracted` — the first persistence step *after*
`gateway.send_outbound` has returned — so the clarification email is genuinely recorded
as `sent` before the run dies, and the orchestrator's own error boundary persists ERROR.
The recovery pass is the real route (303 asserted); FastAPI's TestClient runs the
scheduled `run_pipeline_bg` inline. Assertions land on the captured `send_outbound`
kwargs *and* on the persisted outbound row, plus the pre-crash row being untouched.

**Task 2 — `tests/test_email_epoch_arbiter_integration.py`** (commit `7d0fb3e`).
Two `@pytest.mark.integration` tests taking neither `fake_repo` nor `mock_llm`, executing
the production `insert_email_message` and `clear_reply_context` against real Postgres.
Test 1 snapshots the *whole* epoch-0 row (`SELECT *`), calls the real epoch bump, writes
again at the same `(run_id, purpose, round)` with a different message_id/subject/body, and
asserts two rows exist with the historical one equal to the snapshot as a whole dict.
Test 2 pins the other half of the contract: a same-epoch retry still upserts in place.

**Task 3 — `.github/workflows/concurrency-proof.yml`** (commit `09dec25`).
The only job with a real Postgres now selects both proof modules on one pytest
invocation, and — the actual point — captures the summary via `tee` and **fails the job
if any selected test skipped, or if none passed**. Selection is not execution: these
tests are *designed* to self-skip without a database, so a lost `DATABASE_URL` would
otherwise downgrade the proof to a no-op while CI stayed green.

## Required Recordings

**Hermetic test: GREEN on the first run.** No production fix was needed — the epoch
machinery already resolved WR-01's premise. The test is kept as the permanent regression
gate. Suite: 617 passed / 53 skipped; ruff and mypy clean.

**The mandatory failure injection worked — the narrow fallback was NOT taken.** The
one-shot wrapper fires (`fail_once.fired` asserted), the run lands in `error` with exactly
one `sent` clarification row at round 0 / epoch 0, and the retrigger route recovers it.
The word "crash" is therefore used honestly throughout the file.

**Executed (non-skipped) integration run.** Against a real local Postgres 17
(`DATABASE_URL` + `ALLOW_DB_RESET=1`):

```
tests/test_email_epoch_arbiter_integration.py::test_a_retriggered_send_appends_and_never_edits_the_delivered_email PASSED [ 50%]
tests/test_email_epoch_arbiter_integration.py::test_a_retry_within_the_same_conversation_updates_the_row_in_place PASSED [100%]
============================== 2 passed in 0.12s ===============================
```

Default (no DB): `2 skipped` — the hermetic suite is preserved.

**The whole-row compare's behavior: the epoch-0 row survived the second write untouched
on the first try.** No clobber was present to expose. But the compare was *proven capable
of exposing one*: I injected genuine drift — narrowed the `ON CONFLICT` clause **and** the
`uq_email_run_purpose_round_epoch` constraint to three columns — and re-ran. Test 1 failed
with exactly the intended message ("the table holds 1 row(s) … the delivered one is gone
from the audit trail"), while Test 2 still passed. That is the concrete demonstration that
Test 2 alone would not have caught the drift, and that Test 1 is not vacuous. Source was
restored and re-verified green.

**Guard self-test, all three synthetic cases:**
- `=== 2 passed, 1 skipped in 1.0s ===` → guard **fires** (matches `[0-9]+ skipped`).
- `=== 2 passed in 1.0s ===` → guard **quiet**.
- `=== 3 passed, 4 deselected in 1.0s ===` → guard **quiet** ("deselected" is not "skipped").

The guard was additionally exercised end-to-end as a shell body, not just as a regex:
with no `DATABASE_URL` the proofs self-skipped and the guard exited **1**; against the real
Postgres all 5 selected integration tests executed (3 concurrency + 2 arbiter) and it
exited **0**.

**CI limitation (stated, not hidden):** these proofs gate push-to-master and manual
dispatch, **not pull requests** — so they are a post-merge gate on master, not a pre-merge
one. Recorded in a comment above the workflow's `on:` block. Adding a `pull_request:`
trigger is a CI-policy change outside POLISH-01's scope.

## Deviations from Plan

**1. [Rule 3 - Blocking] Stubbed `suggest_employees` on the consuming module, not the source module**
- **Found during:** Task 1
- **Issue:** The plan said to stub `app.pipeline.suggest.suggest_employees`. But
  `app/pipeline/clarification.py` does `from app.pipeline.suggest import suggest_employees`
  — a bare-name import bound at import time. Patching the source module would have left
  `clarification`'s own binding pointing at the real function: a stub that *looks* applied,
  changes nothing, and leaves the live-key seam open.
- **Fix:** `monkeypatch.setattr(clarification_mod, "suggest_employees", ...)` — the binding
  the code actually calls. (The `mock_llm` fixture is a second layer of protection here, but
  a stub that does nothing is worse than no stub, because it reads as safety.)
- **Files modified:** tests/test_retrigger_threading.py
- **Commit:** c8553ba

No other deviations. No package installs.

## Known Stubs

None. Both test files execute real production code paths within their stated scope; the
only stubs are the three sanctioned ones (the provider send — already no-op'd globally by
conftest, `suggest_employees`, and the one-shot post-send failure injection).

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes.
Threat register items T-15-03 / T-15-08 / T-15-09 are all mitigated as planned.

## Self-Check: PASSED

- `tests/test_retrigger_threading.py` — FOUND
- `tests/test_email_epoch_arbiter_integration.py` — FOUND
- `.github/workflows/concurrency-proof.yml` — FOUND (modified)
- Commits `c8553ba`, `7d0fb3e`, `09dec25` — all FOUND in git log
- Final verification: `uv run pytest -q` → 617 passed, 53 skipped; `uv run ruff check` →
  clean; `uv run mypy` → clean (116 source files)
