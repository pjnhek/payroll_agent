---
phase: 21-durability-proofs-ops-view
verified: 2026-07-20T00:00:00Z
status: human_needed
score: 5/6 must-haves verified (PROOF-01 through PROOF-05 verified; OPS-01 code-complete but not human-verified)
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Live alarm baseline disposition + drain-runs-while-firing proof (21-07 Task 3)"
    expected: "repo.list_unaccounted_error_runs() queried against the LIVE database, every row dispositioned (retriggered / terminally settled / intentionally retained), and pump.yml manually triggered via workflow_dispatch with the real Actions log confirming the drain step executed and reported counts, the alarm step ran last and red, and the drain was not skipped or short-circuited by the alarm."
    why_human: "Requires live Supabase access and a real GitHub Actions run; this is an operator judgment call (baseline disposition) that the phase's own design deliberately refuses to automate (D-16: no mute). Confirmed genuinely open via .planning/phases/21-durability-proofs-ops-view/21-UAT.md (status: testing, 0/2 passed) and 21-07-SUMMARY.md's own `requirements-completed: []`."
  - test: "/ops legibility and published-evidence readability (21-11 Task 3)"
    expected: "Each of the four /ops panels reads as a comparison, not a bare number; the as-of stamp is static; nav reads Pyrl | Runs | Eval | Ops with no dismiss control; a dead-letter/alarm row links to run detail; the page renders with JavaScript disabled; and one section of docs/DURABILITY-PROOFS.md read end-to-end is re-runnable as written."
    why_human: "Legibility and 'does the evidence read as evidence' are judgment calls the plan itself routes to a human checkpoint; no deployed-service access exists in this verification session. Confirmed open via 21-UAT.md and 21-11-SUMMARY.md's own `requirements-completed: []`."
---

# Phase 21: Durability Proofs & Ops View Verification Report

**Phase Goal:** Every durability and exactly-once claim made in Phases 16-20 is demonstrated able to
fail, not just shown passing — and an operator can check "is the queue healthy" as a fact, not a vibe.
**Verified:** 2026-07-20
**Status:** human_needed
**Re-verification:** No — initial verification

## Summary

The four durability proofs (PROOF-01..04) and the CI completeness gate (PROOF-05) are genuinely
delivered: real code, real tests, real executed falsifying mutations, all independently reproduced
in this session against a fresh local Postgres (not merely re-read from SUMMARY claims). OPS-01's
code is also genuinely delivered (data layer, `/ops` route, `/health/queue` alarm, `pump.yml`
wiring, all hermetically tested) — but the phase's own plans (21-07, 21-11) correctly self-report
`requirements-completed: []` because two **blocking human-verify checkpoints remain open**:
the live alarm-baseline disposition + drain-while-firing proof, and `/ops` legibility + evidence
readability. `.planning/phases/21-durability-proofs-ops-view/21-UAT.md` confirms both are still
`pending` (0/2 passed). Per the task's explicit instruction, these are reported as outstanding, not
inferred complete from code inspection.

Separately, `.planning/REQUIREMENTS.md` and `.planning/STATE.md` were **not updated** to reflect
this phase's actual delivery — see Anti-Patterns / Documentation Gaps below. This does not affect
code correctness but means the two source-of-truth tracking documents currently misstate the
project's status.

## Goal Achievement

### Observable Truths (ROADMAP Phase 21 success criteria, verbatim)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Killing a worker mid-run and draining again completes the run; the same test with the lease-reclaim clause or attempts-increment removed demonstrably reds. | VERIFIED | Independently reproduced in this session: applied the exact attempts-increment mutation to `app/db/repo/jobs.py:435` (`attempts = j.attempts` instead of `+ 1`), ran `pytest tests/test_queue_durability.py -m "proof(id='PROOF-01')"` against a fresh local Postgres — red at `assert claimed.attempts == 1` (`AssertionError: assert 0 == 1`), byte-identical revert confirmed (`git diff --stat` empty), re-ran green. Matches `21-03-SUMMARY.md` exactly. |
| 2 | Redelivering the same inbound event produces exactly one `jobs` row, one run, one email; the same test fails if dedup is keyed on the RFC Message-ID alone. | VERIFIED | `tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run` carries `@pytest.mark.proof(id="PROOF-02")`; a companion AST/dataflow guard (`test_prefetch_dedup_key_derivation_guard`) structurally proves `external_event_id` derives only from `request.headers["svix-id"]` or a raw-body digest, never a post-fetch value. `21-04-SUMMARY.md` documents the dedup-key-stability mutation executed live (`external_event_id = str(uuid.uuid4())`), reddening at the response-status-set assertion (`{'accepted'} == {'accepted','duplicate'}`), byte-identical revert confirmed. Cross-checked verbatim against `docs/DURABILITY-PROOFS.md`'s PROOF-02 section — matches. |
| 3 | Crashing between Resend-accept and the local `sent` commit results in zero second emails, `message_id` byte-identical across attempts; fails against the pre-Phase-20 send path. | VERIFIED | `tests/test_send_idempotency.py::test_crash_between_provider_accept_and_local_sent_commit_sends_no_second_email` (PROOF-03) — new test, no incumbent. Two declared halves (fence-refusal at count=1, genuine replay at count=2 with identical Idempotency-Key) per `21-05-SUMMARY.md`. Falsifying mutation (fresh-per-attempt Idempotency-Key at `app/email/gateway.py`'s `send_reserved_outbound_snapshot`) executed live, reddened at the identical-Idempotency-Key assertion, byte-identical revert confirmed. Cross-checked against `docs/DURABILITY-PROOFS.md` — matches. |
| 4 | An expired lease is reclaimed by a second, genuinely concurrent (real OS thread) worker; the zombie's late `mark_failed`/reschedule — not just `mark_done` — is rejected by the fence; fails against pre-fix claim SQL. | VERIFIED | Read `tests/test_queue_durability.py:2371-2650` directly: two real `threading.Thread`s, distinct `repo.get_connection()` connections, released by `threading.Barrier(2)`, driving `repo.claim_job`/`repo.complete_job`/`repo.fail_job` directly (never `TestClient`/HTTP). The `PROOF-04`-tagged test asserts BOTH `complete_job` (`False`) and `fail_job` (`None`) are fenced as independently named assertions ("the fence people forget"). A companion untagged test removes the ordering `Event` and asserts the two threads' `time.monotonic_ns()` intervals **intersect** (genuine overlap, not inferred from thread count) plus the order-independent invariant across both branches. Independently reproduced in this session: deleted the `OR (c.state = 'leased' AND c.leased_until < now())` disjunct from `app/db/repo/jobs.py:443`, ran the PROOF-04 test — red at `assert reclaimed is not None` exactly as claimed, byte-identical revert confirmed, re-ran green. |
| 5 | All four proofs are registered in `concurrency-proof.yml` and demonstrably run in CI against real Postgres — none silently skipped by the workflow's file list. | VERIFIED | Read `.github/workflows/concurrency-proof.yml` directly: a third step (`check_proof_inventory.py`) runs after the marker-selected `-m queueproof` step, itself after the by-name step; comment block confirms the selection-layer completeness rationale. Independently ran `uv run python -m scripts.check_proof_inventory` → exit 0; `uv run pytest tests/ -m proof --collect-only -q` → exactly 4 node ids; `uv run pytest tests/ -m queueproof -q -rs` → 73 passed, 0 skipped (matches claimed baseline). Both the typo-id and missing-`queueproof`-marker falsifications are documented with pasted red output in `21-09-SUMMARY.md` (not independently re-run by this verifier, but the checker's live-repository no-false-positive test (`TestLiveRepositoryInventory`) and its synthetic red-proofs were confirmed present and passing in the live suite run). |
| 6 | An operator can view queue depth, oldest-pending-job age, attempts distribution, and the dead-letter list on one page, surfacing an alarm when a run is `error` with no corresponding terminal/dead job settlement. | CODE VERIFIED, NOT HUMAN-VERIFIED | `GET /ops` (`app/routes/ops.py`, `app/templates/ops.html`) and `GET /health/queue` (`app/routes/health.py`) are both implemented, side-effect-free (proven against the whole `app.db.repo.__all__` mutation surface), and hermetically tested (30 tests across `test_ops_route.py` + `test_health_queue_alarm.py`). The D-13 alarm predicate (`list_unaccounted_error_runs`, equality-correlated, never `>=`) is proven live-Postgres-silent on all legitimate settlement paths and live-Postgres-firing on the unaccounted shape (`tests/test_ops_alarm_predicate.py`, 8/8 passed, independently re-run in this session). `pump.yml`'s alarm step is structurally pinned last, `always()`-guarded, and the drain step is pinned to carry no `if:` key (`TestAlarmStepOrdering`, 5 tests). **However, the plan's own Task 3 checkpoints (21-07, 21-11) — which require live Supabase baseline dispositioning and a real `workflow_dispatch` run log, plus a human read of `/ops` and the published doc — are still open** per `21-UAT.md` (0/2 passed). Both 21-07-SUMMARY.md and 21-11-SUMMARY.md self-report `requirements-completed: []` for exactly this reason. |

**Score:** 5/6 truths fully verified (PROOF-01 through PROOF-05); truth 6 (OPS-01) is code-complete
and hermetically proven but requires the two pending human checkpoints below before it can be
counted verified.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `pyproject.toml` `proof` marker | registered, keyword-`id` contract | VERIFIED | Present; `TestProofMarkerRegistered` pins it. |
| `scripts/check_proof_inventory.py` | pure decision function + collector | VERIFIED | Exit 0 on live repo; 4 failure shapes red-proofed (`tests/test_proof_inventory.py`). |
| `tests/test_proof_mutation_targets.py` | AST-anchored `MUTATION_TARGETS` registry (4 entries) | VERIFIED | Read directly; three predicate kinds (`sql_fragment`, `assignment`, `dict_value`); live red-proof + green-proof both demonstrated in `21-10-SUMMARY.md`. |
| `app/db/repo/jobs.py` (4 metric reads) + `job_settlement.py` (`list_unaccounted_error_runs`) | OPS-01 data layer | VERIFIED | Present, hermetically shape-tested, live-proven (8/8, independently re-run). |
| `app/routes/ops.py`, `app/templates/ops.html` | `/ops` page | VERIFIED (code) | Present, wired, side-effect-free, hermetically tested. |
| `app/routes/health.py` (`GET /health/queue`) | cron-checkable alarm | VERIFIED (code) | Present; 200 clear / 503 firing with bounded `{status,count}` body only; 3 pre-existing health contracts unweakened. |
| `.github/workflows/pump.yml` alarm step | last, `always()`-guarded, after drain | VERIFIED | Read directly; structurally pinned by `TestAlarmStepOrdering`. |
| `docs/DURABILITY-PROOFS.md` | published evidence, linked from README | VERIFIED | Read in full — accurate, does not overclaim, explicitly states the 26-tests-unwatched-by-CI residual and the three D-08 limits. Rot-guard (`tests/test_durability_docs.py`) binds it to `MUTATION_TARGETS` and `EXPECTED_PROOF_IDS`. |
| `21-UAT.md` | tracks the 2 open human checkpoints | VERIFIED PRESENT | Confirms both items are `pending`, 0/2 passed — consistent with 21-07/21-11 SUMMARYs. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `scripts/check_proof_inventory.py::main()` | `.github/workflows/concurrency-proof.yml` third step | `uv run python -m scripts.check_proof_inventory` | WIRED | Confirmed by direct file read; step runs after the `queueproof` step. |
| `list_unaccounted_error_runs` | `/ops` alarm banner (21-06) and `/health/queue` (21-07) | direct facade call, no re-derivation | WIRED | Both consumers call the same function; 21-07 gated explicitly on 21-02's equality-correlation confirmation before being written. |
| `proof` marker ⇄ `queueproof` marker | CI-executed selection | intersection (`queueproof and proof(id=...)`) | WIRED | Verified independently: `-m proof --collect-only` → 4 ids; `-m queueproof` → 73 passed, 0 skipped; per-id intersection collect-only confirmed for all 4 in `21-09-SUMMARY.md` and spot-checked here. |

### Behavioral Spot-Checks (independently executed in this verification session)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| PROOF-01 falsifies and reverts | mutate `jobs.py:435`, run PROOF-01, revert | Red at `assert claimed.attempts == 1` (`0 == 1`); byte-identical revert; green after | PASS |
| PROOF-04 falsifies and reverts | delete `jobs.py:443`'s expired-lease disjunct, run PROOF-04, revert | Red at `assert reclaimed is not None`; byte-identical revert; green after | PASS |
| Hermetic suite (no `DATABASE_URL`) | `env -u DATABASE_URL uv run pytest -q` | 1303 passed, 105 skipped | PASS (matches claimed baseline) |
| `-m queueproof` against real Postgres | `uv run pytest tests/ -m queueproof -q -rs` | 73 passed, 0 skipped | PASS (matches claimed baseline) |
| `-m proof --collect-only` | `uv run pytest tests/ -m proof --collect-only -q` | 4 node ids (PROOF-01..04) | PASS |
| Completeness gate | `uv run python -m scripts.check_proof_inventory` | exit 0 | PASS |
| Full live-DB suite | `uv run pytest tests/ -q -rf` | 1405 passed, 3 skipped | PASS (matches claimed baseline) |
| Hermetic pool fail-fast guard, both halves | `test_hermetic_pool_access_fails_fast` (no DB) + `test_hermetic_pool_access_inert_with_real_database_url` (real DB) | Both pass in their respective environment (first self-skips under real `DATABASE_URL`, as designed) | PASS |
| Lint/typecheck | `uv run ruff check .` / `uv run mypy --strict app` | All checks passed / no issues in 74 files | PASS |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|---|---|---|---|---|
| PROOF-01 | 21-03 (delivered), 21-01 (substrate) | Kill-worker-mid-run proof + executed falsification | SATISFIED | Independently reproduced in this session. |
| PROOF-02 | 21-04 (delivered), 21-01 (substrate) | Same-Svix-redelivery dedup proof + pre-fetch structural guard + executed falsification | SATISFIED | Reviewed thoroughly; cross-checked against published doc. |
| PROOF-03 | 21-05 (delivered), 21-01 (substrate) | Crash-between-accept-and-commit proof, two halves, executed falsification | SATISFIED | Reviewed thoroughly; cross-checked against published doc. |
| PROOF-04 | 21-08 (delivered), 21-01 (substrate) | Genuine two-thread race, both fences, executed falsification | SATISFIED | Independently reproduced in this session (both code read and mutation re-run). |
| PROOF-05 | 21-01, 21-09 (delivered), 21-10 (mutation-target registry) | CI completeness gate at the selection layer | SATISFIED | Independently verified: workflow read, checker run, both-halves guard tests read and confirmed present. |
| OPS-01 | 21-02 (data layer), 21-06 (`/ops`), 21-07 (alarm endpoint + pending checkpoint), 21-11 (doc + pending checkpoint) | Ops view + cron alarm | **NOT YET SATISFIED** | Code fully delivered and hermetically/live-proven; **two blocking human-verify checkpoints remain open** (21-07 Task 3, 21-11 Task 3). Both plans' own SUMMARYs declare `requirements-completed: []` for this exact reason. `21-UAT.md` confirms 0/2 passed. |

No orphaned requirement IDs — all six (PROOF-01..05, OPS-01) are claimed by at least one plan's
frontmatter and traced above.

### Anti-Patterns / Documentation Gaps Found

| File | Issue | Severity | Impact |
|------|-------|----------|--------|
| `.planning/REQUIREMENTS.md` (~lines 105-176) | Stale and internally self-contradictory: the bullet checklist marks PROOF-01, PROOF-04, PROOF-05 as `[x]` (done) and PROOF-02, PROOF-03, OPS-01 as `[ ]` (not done) — but the Traceability table immediately below lists **all six**, including the three checked ones, as `Status: Pending`. Neither the checked/unchecked split nor the "Pending" table row reflects this verification's findings (PROOF-01..05 are fully delivered; OPS-01 is not, but for a different reason than the checklist implies — code is done, human checkpoints are open). | WARNING | Does not affect code correctness. Whoever next reads REQUIREMENTS.md for status will be misled in both directions: told PROOF-02/03 aren't done when they are, and told PROOF-01/04/05 are "Pending" when they're fully verified. Should be corrected as part of closing this phase. |
| `.planning/STATE.md` (top-of-file status block, "Session Continuity", "Operator Next Steps") | Still reads "Phase: 21 — EXECUTING", "Last activity: 2026-07-20 — Phase 21 execution started", resume file pointing at `21-CONTEXT.md`, and "Operator Next Steps: Verify Phase 20... then plan Phase 21" — all pre-execution content, not updated to reflect that all 15 plans have since executed. | WARNING | Likely expected to be updated by the phase-close step following this verification; flagged so it isn't missed. |

No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers found in any phase-21-touched file
(20 files scanned directly, including all new test modules, `scripts/check_proof_inventory.py`,
the two workflow YAMLs, and `docs/DURABILITY-PROOFS.md`).

### Human Verification Required

### 1. Live alarm baseline disposition + drain-runs-while-firing proof (21-07 Task 3)

**Test:** Query `repo.list_unaccounted_error_runs()` against the **live** database (Supabase), record
the count and run ids, and disposition each row as retriggered / terminally settled / intentionally
retained. Then trigger `pump.yml` manually via `workflow_dispatch` with at least one unaccounted
error run present, and confirm in the real GitHub Actions log that the drain step executed and
reported its counts, the alarm step ran last and red, and the drain was not skipped or
short-circuited.
**Expected:** A recorded baseline count, an explicit disposition for every row, and confirmation
from a real Actions run log that recovery-first ordering holds under a firing alarm.
**Why human:** Requires live Supabase credentials and a real GitHub Actions trigger, neither
available in this verification session; the baseline disposition is a deliberate, non-automatable
operator judgment call (D-16 rules out any mute).

### 2. `/ops` legibility and the published evidence reading as evidence (21-11 Task 3)

**Test:** Load `/ops` on the deployed service; confirm each of the four panels reads as a comparison
(not a bare number), the "as of" stamp is present and static, nav reads `Pyrl | Runs | Eval | Ops`
with no dismiss control anywhere, a dead-letter/alarm row links to run detail, and the page renders
fully with JavaScript disabled. Then open `docs/DURABILITY-PROOFS.md` from the README link, read one
proof section end to end and confirm it is re-runnable as written, and read the residuals section.
**Expected:** A human confirms the page reads as intended and the document reads as evidence rather
than assertion.
**Why human:** Legibility and "does this read as evidence" are judgment calls the plan itself routes
to a blocking human checkpoint; no deployed-service access exists in this verification session.

### Gaps Summary

No code-level gaps were found. All four durability proofs and the CI completeness gate
(PROOF-01 through PROOF-05) are genuinely delivered, non-vacuous, and — for two of the four
(PROOF-01, PROOF-04) — independently re-falsified in this verification session with results matching
the phase's own SUMMARYs exactly. The remaining two proofs (PROOF-02, PROOF-03) were verified by
close reading of code, tests, and cross-checking the published evidence document rather than
re-executing the mutation myself, but showed no inconsistency across the SUMMARY, the
`MUTATION_TARGETS` registry, and `docs/DURABILITY-PROOFS.md`.

OPS-01's code is complete and proven (data layer, route, alarm endpoint, CI wiring), but the phase
cannot be marked fully complete because two blocking human-verify checkpoints — baked into the plans
themselves (21-07 Task 3, 21-11 Task 3) — are still open, exactly as `21-UAT.md` and both plans' own
SUMMARYs (`requirements-completed: []`) honestly report. This is not a gap the phase's plans failed
to close; it is a genuinely outstanding item that needs an operator with live-service access.

Separately, `.planning/REQUIREMENTS.md` and `.planning/STATE.md` were not updated to reflect the
phase's actual delivery and should be corrected when the phase is closed.

---

*Verified: 2026-07-20*
*Verifier: Claude (gsd-verifier)*
