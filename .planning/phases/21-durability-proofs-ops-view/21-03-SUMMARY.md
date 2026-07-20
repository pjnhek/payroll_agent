---
phase: 21-durability-proofs-ops-view
plan: 03
subsystem: testing
tags: [pytest, postgres, queue, durability-proof, falsifying-mutation]

requires:
  - phase: 21-durability-proofs-ops-view
    provides: "21-01's registered proof(id=...) marker + selection-layer completeness checker; 21-13's repair of test_queue_durability.py back to -m queueproof green"
provides:
  - "PROOF-01 identity (@pytest.mark.proof(id=\"PROOF-01\")) applied to the sole node test_retrigger_survives_worker_crash_mid_lease"
  - "Executed, evidenced falsification of the attempts-increment half of ROADMAP criterion 1 against a real Postgres — mutation diff, red pytest output, byte-identical revert, and post-revert green all captured below"
affects: [21-10, 21-11]

tech-stack:
  added: []
  patterns:
    - "Module docstring's lettered falsifying-mutation inventory (a)-(i) extended with entry (j) for the attempts-increment mutation, matching the file's existing self-documentation convention"

key-files:
  created: []
  modified:
    - tests/test_queue_durability.py

key-decisions:
  - "D-06 correction from cross-AI review confirmed empirically: freezing claim_job's attempts-increment reds FIRST at the step-3 initial-claim assertion (assert claimed.attempts == 1), not the step-6 post-reclaim assertion — execution never reaches step 6 under this mutation, exactly as the plan's corrected prediction stated."
  - "No test logic was added (D-01): the audit in Task 1 confirmed both halves of criterion 1 (reclaim path fired; attempts incremented) were already asserted in the incumbent test before this plan touched it — only the marker, docstring naming, and module inventory entry were added."

requirements-completed: [PROOF-01]

coverage:
  - id: D1
    description: "test_retrigger_survives_worker_crash_mid_lease carries @pytest.mark.proof(id=\"PROOF-01\") as the sole node with that id, and also carries queueproof via the module-level pytestmark"
    requirement: PROOF-01
    verification:
      - kind: unit
        ref: "uv run pytest tests/ -m \"proof(id='PROOF-01')\" --collect-only -q -> 1 node id (tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease)"
        status: pass
      - kind: unit
        ref: "uv run pytest tests/ -m proof --collect-only -q -> same 1 node id (only PROOF-01 exists at this point in the phase)"
        status: pass
    human_judgment: false
  - id: D2
    description: "The falsifying mutation (freeze claim_job's attempts-increment) was executed live against a real Postgres, produced a red in the named initial-claim assertion, and was reverted byte-identically"
    requirement: PROOF-01
    verification:
      - kind: integration
        ref: "GREEN baseline -> mutation -> RED (assert claimed.attempts == 1, AssertionError: assert 0 == 1) -> byte-identical revert (git diff --stat app/db/repo/jobs.py empty) -> GREEN again; full transcript pasted below"
        status: pass
    human_judgment: false

duration: ~20min
completed: 2026-07-20
status: complete
---

# Phase 21 Plan 03: PROOF-01 Identity + Executed Falsification of the Attempts-Increment Summary

**Applied `@pytest.mark.proof(id="PROOF-01")` to the audited-complete mid-lease reclaim test and executed the attempts-increment falsifying mutation live against a real Postgres — the red landed exactly where the plan's cross-AI-corrected prediction said it would (the step-3 initial-claim assertion, not the step-6 post-reclaim one), then reverted byte-identically.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 2 completed (Task 2 produced no lasting source change — the mutation was reverted byte-identically, so there is nothing new to commit beyond Task 1's marker application)
- **Files modified:** 1 (`tests/test_queue_durability.py`)

## Accomplishments

- **Task 1 — audit + identity.** Audited `test_retrigger_survives_worker_crash_mid_lease` against ROADMAP criterion 1 and REQUIREMENTS' PROOF-01 vacuity clause. Both halves were already present in the incumbent test:
  - **Reclaim path fired:** established by `assert drain.drain_once() == DrainOutcome.DONE` (step 5) and `assert final_row["state"] == "done"` (step 6), both depending on `claim_job`'s `OR (c.state = 'leased' AND c.leased_until < now())` WHERE clause (`app/db/repo/jobs.py:443`).
  - **Attempts incremented:** established by the initial-claim assertion `assert claimed.attempts == 1` (step 3, `tests/test_queue_durability.py:3048` post-edit) and the post-reclaim assertion `assert final_row["attempts"] == 2` (step 6, the test's own named vacuity detector), both depending on `claim_job`'s `attempts = j.attempts + 1` SET clause (`app/db/repo/jobs.py:435`).

  Per D-01, no test logic was added — only `@pytest.mark.proof(id="PROOF-01")` (keyword form), a docstring section naming both attempts assertions and stating which one the coming mutation reddens first, and a new lettered entry (j) in the module docstring's falsifying-mutation inventory.

- **Task 2 — executed falsification.** Confirmed `DATABASE_URL` reachable (`postgresql://pnhek@localhost:5432/pa_p21_03`, local throwaway Postgres) and `uv run python -m app.db.bootstrap` succeeded. Ran the GREEN baseline (1 passed, empty `-rs` skip report). `grep -n`'d the mutation target first and confirmed the SET clause at `app/db/repo/jobs.py:435` is the live executable SQL — line 415 is a docstring copy of the same text and was left untouched. Applied the mutation (`attempts = j.attempts + 1` → `attempts = j.attempts`), re-ran the proof, observed the predicted RED at the step-3 initial-claim assertion, reverted byte-identically (`git diff --stat app/db/repo/jobs.py` empty), and re-ran to confirm GREEN.

## Task Commits

1. **Task 1: Audit the incumbent against criterion 1 and give it its PROOF-01 identity** - `fb3b10a` (feat)
2. **Task 2: Execute the falsifying mutation live and capture the red run** - no commit (mutation applied and reverted byte-identically within this task; `git diff --stat app/db/repo/jobs.py` is empty at task end, so there is nothing to stage)

## Files Created/Modified

- `tests/test_queue_durability.py` - added `@pytest.mark.proof(id="PROOF-01")` to `test_retrigger_survives_worker_crash_mid_lease`, extended its docstring naming both attempts assertions and which one the mutation reddens first, and added lettered entry (j) to the module docstring's falsifying-mutation inventory.

## Mutation Evidence (published verbatim per plan's `<output>` contract — consumed by plans 21-10 and 21-11)

**Claim:** PROOF-01 (`test_retrigger_survives_worker_crash_mid_lease`) genuinely depends on `claim_job`'s attempts-increment (`app/db/repo/jobs.py:435`). Freezing that increment makes the proof go red at the initial-claim assertion in step 3.

**Commit SHA the mutation ran against:** `fb3b10a69902693eda83cee66f082b6bd4797a38`

**Mutation diff:**

```diff
--- a/app/db/repo/jobs.py
+++ b/app/db/repo/jobs.py
@@ -432,7 +432,7 @@ def claim_job(
                    SET state        = 'leased',
                        lease_token  = gen_random_uuid(),
                        leased_until = now() + (%(lease_seconds)s || ' seconds')::interval,
-                       attempts     = j.attempts + 1,
+                       attempts     = j.attempts,
                        updated_at   = now()
                  WHERE j.id = (
                        SELECT c.id
```

**GREEN baseline (before mutation):**

```
tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease PASSED [100%]
================= 1 passed, 57 deselected, 1 warning in 0.62s ==================
```
`-rs` skip report: empty.

**RED run (with mutation applied) — full pytest output:**

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.1.1, pluggy-1.6.0
collecting ... collected 58 items / 57 deselected / 1 selected

tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease FAILED [100%]

=================================== FAILURES ===================================
________________ test_retrigger_survives_worker_crash_mid_lease ________________

    ... (steps 1-2 pass) ...

        # --- Step 3: simulate a worker that claims the job, gets partway through
        # (its own forward CAS lands the run at EXTRACTING, mirroring what
        # handle_run_pipeline itself would have done on a first attempt), and
        # then dies mid-lease. NEVER drain_once() here — that would run the
        # handler to completion; repo.claim_job() is what lets this test stop
        # MID-LEASE. ------------------------------------------------------------
        claimed = repo.claim_job()
        assert claimed is not None
        assert claimed.id == job_id, "the claim in step 3 must be THIS test's own job"
>       assert claimed.attempts == 1
E       AssertionError: assert 0 == 1
E        +  where 0 = Job(id=UUID('05d76540-708e-429a-8caf-3230bdf12572'), kind=<JobKind.RUN_PIPELINE: 'run_pipeline'>, run_id=UUID('cfd895b0-12b2-44e4-9088-2e3907ca39e3'), email_id=None, operator_resolution_id=None, event_id=None, attempts=0, max_attempts=5, lease_token=UUID('e47295b3-3b81-4b4c-a9c0-621886c03e45')).attempts

tests/test_queue_durability.py:3048: AssertionError
---------------------------- Captured stdout setup -----------------------------
Bootstrap target: postgresql://pnhek@localhost:5432/pa_p21_03
RESET: dropping all tables in reverse dependency order — this is destructive
  DROP TABLE IF EXISTS name_matches CASCADE
  DROP TABLE IF EXISTS paystub_line_items CASCADE
  DROP TABLE IF EXISTS eval_results CASCADE
  DROP TABLE IF EXISTS operator_resume_overrides CASCADE
  DROP TABLE IF EXISTS jobs CASCADE
  DROP TABLE IF EXISTS inbound_events CASCADE
  DROP TABLE IF EXISTS operator_resume_resolutions CASCADE
  DROP TABLE IF EXISTS operator_resolution_writer_fence CASCADE
  DROP TABLE IF EXISTS email_messages CASCADE
  DROP TABLE IF EXISTS payroll_runs CASCADE
  DROP TABLE IF EXISTS employees CASCADE
  DROP TABLE IF EXISTS businesses CASCADE
  DROP TABLE IF EXISTS name_matches CASCADE  (dead-table migration)
  ALTER TABLE paystub_line_items DROP COLUMN IF EXISTS match_confidence  (dead-column migration)
Bootstrap complete. Tables applied.
Seeded 3 businesses, 7 employees.
================= 1 failed, 57 deselected, 1 warning in 0.70s ==================
```

**Named failing assertion:** the **initial-claim assertion**, `assert claimed.attempts == 1` at `tests/test_queue_durability.py:3048` (step 3) — exactly the assertion the plan's cross-AI-corrected prediction named, not the post-reclaim assertion in step 6. Execution never reached step 6 under this mutation, confirming the plan's D-06 correction empirically.

**Byte-identical revert confirmation:** `git diff --stat app/db/repo/jobs.py` produced no output after reverting.

**Post-revert GREEN run:**

```
tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease PASSED [100%]
================= 1 passed, 57 deselected, 1 warning in 0.62s ==================
```
`-rs` skip report: empty.

**Exact re-run command for the full cycle:**

```bash
export DATABASE_URL="postgresql://<local-throwaway-db>"
export ALLOW_DB_RESET=1
uv run python -m app.db.bootstrap
uv run pytest tests/test_queue_durability.py -m "proof(id='PROOF-01')" -v -rs   # GREEN baseline
# apply the diff above to app/db/repo/jobs.py
uv run pytest tests/test_queue_durability.py -m "proof(id='PROOF-01')" -v -rs   # RED
git checkout -- app/db/repo/jobs.py                                            # byte-identical revert
uv run pytest tests/test_queue_durability.py -m "proof(id='PROOF-01')" -v -rs   # GREEN again
```

## Decisions Made

- No test logic added — the audit confirmed both halves of criterion 1 were already present in the incumbent test; only marker/docstring/naming were added (D-01 compliance).
- Confirmed empirically, not just predicted, that the attempts-increment mutation reds at the step-3 initial-claim assertion, matching the plan's cross-AI-corrected (Codex) prediction. No further correction needed.

## Deviations from Plan

None — plan executed exactly as written, including the corrected D-06 prediction which was confirmed to match the observed red exactly.

## Issues Encountered

None.

## Full-Suite Verification (post-plan, confirms no regression)

- `ALLOW_DB_RESET=1 uv run pytest tests/ -m queueproof -v -rs` → **71 passed, 1245 deselected, 0 skipped** (matches the stated current baseline).
- `env -u DATABASE_URL uv run pytest -q` (hermetic) → **1212 passed, 104 skipped** (matches the stated current baseline, unchanged).
- `uv run ruff check .` → All checks passed.
- `uv run mypy --strict app` → Success: no issues found in 73 source files.
- `git status --porcelain app/` → empty (no production source change survives this plan).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- PROOF-01's identity and executed falsification evidence are ready for plan 21-10's AST guard/inventory registration and plan 21-11's `docs/DURABILITY-PROOFS.md` publication — this SUMMARY's "Mutation Evidence" section is written to be consumed verbatim.
- `tests/test_queue_durability.py`'s module docstring inventory now has entries (a) through (j), staying truthful about every falsifying mutation this file's proofs claim.

## Self-Check: PASSED

- FOUND: tests/test_queue_durability.py
- FOUND: commit fb3b10a69902693eda83cee66f082b6bd4797a38

---
*Phase: 21-durability-proofs-ops-view*
*Completed: 2026-07-20*
