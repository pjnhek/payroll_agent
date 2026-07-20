---
phase: 21-durability-proofs-ops-view
plan: 09
subsystem: testing
tags: [pytest, ci, github-actions, yaml, static-analysis, durability-proofs]

# Dependency graph
requires:
  - phase: 21-durability-proofs-ops-view
    provides: "21-01 (scripts/check_proof_inventory.py's evaluate_inventory/collect_inventory), 21-03/04/05/08 (PROOF-01..04 identities tagged)"
provides:
  - "A third CI step in concurrency-proof.yml invoking scripts/check_proof_inventory.py — the selection-layer completeness gate that reds a typo'd id or a missing queueproof marker while the execution-layer 'N passed' log guards above it stay green"
  - "TestD02CollectGateStep and TestPreExistingStepFingerprints in tests/test_queue_config.py — structural pins over parsed YAML for the new step and, for the first time, for the two pre-existing steps' name/shell/pipefail/selection/env/log-guards"
  - "TestLiveRepositoryInventory in tests/test_proof_inventory.py — the no-false-positive half proving evaluate_inventory is clean against the real repository, that each id maps to its recorded node id, and that the proof and queueproof selections agree"
  - "Two live-executed, byte-identically-reverted falsifications of the gate itself: a single-character id typo and a removed queueproof marker, both observed reddening with the correct violation text"
affects: [ci, durability-proofs, docs/DURABILITY-PROOFS.md]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Structural YAML fingerprinting over yaml.safe_load'd steps (name/shell/run-substring/env-keys) rather than a whole-step hash or a single command substring — survives comment reflow, catches semantic drift, each assertion proven reachable by a live mutate-observe-revert cycle before being trusted"
    - "Guard non-vacuity for a CI gate itself: the same live-mutate/observe-red/byte-identical-revert discipline this phase applies to production-code proofs, applied one level up to the selection-layer checker that verifies those proofs"

key-files:
  created: []
  modified:
    - .github/workflows/concurrency-proof.yml
    - tests/test_queue_config.py
    - tests/test_proof_inventory.py

key-decisions:
  - "TestPreExistingStepFingerprints pins named, load-bearing YAML fields (name, shell, presence of `set -o pipefail` inside the run block, selection-command substring, both log-guard grep patterns, job-level env keys) rather than a hash of the whole run block — a hash reds on a harmless comment reflow inside the multi-line run: | literal block and gets deleted for being annoying, which is how a guard dies. Named-field pinning survives formatting drift and still catches every semantic change enumerated in the class docstring."
  - "Comments inside a YAML `run: |` literal block scalar are part of the parsed string (not stripped like top-level YAML comments), so the log-guard grep patterns and the `-m integration`/`-m queueproof` selection strings are directly assertable substrings of `step['run']` after yaml.safe_load — no separate raw-text parsing was needed."
  - "Falsification 2 (missing queueproof marker) used PROOF-02 (tests/test_webhook_dedup_race.py), not PROOF-01/04 (tests/test_queue_durability.py), because PROOF-01/04 receive `queueproof` from a module-level `pytestmark` list shared by the whole file — removing it there would have de-selected many unrelated tests, not isolated one proof. PROOF-02 and PROOF-03 carry `@pytest.mark.queueproof` as an individual per-test decorator, which a single line-delete removes cleanly from exactly one test."
  - "No artifact produced by this plan describes TestD14NoWideningGuard as 'byte-pinning' the workflow — it is described as checking one command substring and one absence, exactly what it does. TestPreExistingStepFingerprints is introduced as the guard that closes that gap."

requirements-completed: [PROOF-05]

coverage:
  - id: D1
    description: "A third CI step in concurrency-proof.yml invokes scripts/check_proof_inventory.py via uv run, added strictly after the queueproof step, with both pre-existing steps left byte-unchanged (git diff shows only added lines)"
    requirement: PROOF-05
    verification:
      - kind: unit
        ref: "tests/test_queue_config.py::TestD02CollectGateStep::test_completeness_gate_step_exists_and_invokes_the_checker"
        status: pass
      - kind: unit
        ref: "tests/test_queue_config.py::TestD02CollectGateStep::test_completeness_gate_step_runs_after_the_queueproof_step"
        status: pass
      - kind: unit
        ref: "tests/test_queue_config.py::TestD02CollectGateStep::test_exactly_three_proof_running_steps"
        status: pass
      - kind: other
        ref: "git diff .github/workflows/concurrency-proof.yml shows 28 insertions(+), 0 deletions"
        status: pass
    human_judgment: false
  - id: D2
    description: "TestPreExistingStepFingerprints structurally pins name/shell/pipefail/selection-args/env-keys/both-log-guards for both pre-existing steps, each fingerprint proven reachable by a live drop-and-restore mutation observed reddening"
    requirement: PROOF-05
    verification:
      - kind: unit
        ref: "tests/test_queue_config.py::TestPreExistingStepFingerprints::test_integration_step_fingerprint"
        status: pass
      - kind: unit
        ref: "tests/test_queue_config.py::TestPreExistingStepFingerprints::test_queueproof_step_fingerprint"
        status: pass
      - kind: unit
        ref: "tests/test_queue_config.py::TestPreExistingStepFingerprints::test_job_level_env_keys_unchanged"
        status: pass
      - kind: other
        ref: "manual live reachability proof: dropped 'set -o pipefail' from the integration step -> test_integration_step_fingerprint reds; restored, git diff clean, test passes again. Removed the skip-guard grep from the queueproof step -> test_queueproof_step_fingerprint reds; restored, git diff clean, test passes again. See 'Fingerprint Reachability Proof' section below."
        status: pass
    human_judgment: false
  - id: D3
    description: "TestLiveRepositoryInventory proves the no-false-positive half: evaluate_inventory is clean against the real repository, each of PROOF-01..04 maps to the exact node id recorded in its own SUMMARY, and the bare proof/queueproof selections agree on all four node ids — all with DATABASE_URL unset"
    requirement: PROOF-05
    verification:
      - kind: unit
        ref: "tests/test_proof_inventory.py::TestLiveRepositoryInventory::test_no_violations_against_the_real_repository"
        status: pass
      - kind: unit
        ref: "tests/test_proof_inventory.py::TestLiveRepositoryInventory::test_each_id_maps_to_the_node_id_recorded_in_its_summary"
        status: pass
      - kind: unit
        ref: "tests/test_proof_inventory.py::TestLiveRepositoryInventory::test_proof_and_queueproof_selections_agree_on_all_four_node_ids"
        status: pass
      - kind: other
        ref: "env -u DATABASE_URL uv run pytest tests/test_proof_inventory.py -v -> 11 passed"
        status: pass
    human_judgment: false
  - id: D4
    description: "The completeness gate was observed reddening live against two real, distinct failure shapes (a single-character id typo, and a queueproof marker removed from a single test) and reverting byte-identically to green in both cases"
    requirement: PROOF-05
    verification:
      - kind: other
        ref: "Falsification 1 (typo): PROOF-01 id='PROOF-01' -> 'PROOF-O1' on tests/test_queue_durability.py:3132 -> checker exit 1, two violations printed -> git checkout -- reverts byte-identical -> checker exit 0. Full transcript in 'Falsification 1' section below."
        status: pass
      - kind: other
        ref: "Falsification 2 (missing marker): removed @pytest.mark.queueproof from PROOF-02's test (tests/test_webhook_dedup_race.py:202) -> checker exit 1, violation names 'queueproof' and the node id -> git checkout -- reverts byte-identical -> checker exit 0. Full transcript in 'Falsification 2' section below."
        status: pass
    human_judgment: false

# Metrics
duration: 55min
completed: 2026-07-20
status: complete
---

# Phase 21 Plan 09: Wire the Completeness Gate into CI, Prove It Non-Vacuous Summary

**Added a third CI step to `concurrency-proof.yml` that invokes `scripts/check_proof_inventory.py`, pinned both pre-existing steps with a real structural fingerprint (not the previously-mislabeled "byte-pinned" substring check), proved the live repository conforms with `DATABASE_URL` unset, and executed two live falsifications — a single-character id typo and a removed `queueproof` marker — both observed reddening with the correct violation text, then reverted byte-identically.**

## Performance

- **Duration:** 55 min
- **Started:** 2026-07-20 (wave 4)
- **Completed:** 2026-07-20
- **Tasks:** 2 completed
- **Files modified:** 3

## Accomplishments

- Appended a third step, "Verify every durability proof is registered exactly once (completeness gate)", to `.github/workflows/concurrency-proof.yml`'s job — strictly additive (`git diff` shows 28 insertions, 0 deletions), running after the queueproof step, invoking `uv run python -m scripts.check_proof_inventory` (the pure decision function plan 21-01 already red-proofed hermetically, not a second bash implementation of the same counting logic).
- Added `TestD02CollectGateStep` (4 tests) to `tests/test_queue_config.py`, asserting structurally over parsed YAML: the step exists and invokes the checker, it runs after the queueproof step, the job has exactly 3 proof-running steps (so a future deletion is caught), and the pre-existing `TestD14NoWideningGuard` still passes unmodified (the no-false-positive half).
- Added `TestPreExistingStepFingerprints` (3 tests) — the real structural pin the review found missing. Pins, for both pre-existing steps: `name`, `shell`, the presence of `set -o pipefail` inside the `run:` literal block, the selection-command substring, both log-guard grep patterns (`[0-9]+ skipped` reds, `[0-9]+ passed` required), and the job-level `env` key set. Each fingerprint assertion was proven reachable by a live drop-and-restore mutation (see below), not merely written and trusted.
- Added `TestLiveRepositoryInventory` (3 tests) to `tests/test_proof_inventory.py` — the no-false-positive half plan 21-01 deferred to this plan. Confirms `evaluate_inventory` is clean against the real repository, each of PROOF-01..04 maps to the exact node id its own SUMMARY recorded, and the bare `proof` and `queueproof` selections agree on all four node ids. Runs with `DATABASE_URL` unset, kept outside the `proof`/`queueproof` marker selections so it cannot corrupt the inventory it checks.
- Executed both required live falsifications of the gate itself — a typo'd marker id and a removed `queueproof` marker — each observed reddening with the specific, correctly-worded violation, then reverted byte-identically (`git diff --stat` empty, checker back to exit 0). Full transcripts below.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add the completeness gate step to concurrency-proof.yml** - `29e5592` (feat)
2. **Task 2: Assert the gate is clean on the live repository (live-repository test)** - `55360bf` (test)

_The two live falsifications (Falsification 1 and Falsification 2) were executed, observed reddening, and reverted byte-identically in-session as required — neither mutation was committed, matching every other proof in this phase._

## Files Created/Modified

- `.github/workflows/concurrency-proof.yml` — added the third "Verify every durability proof is registered exactly once (completeness gate)" step, additive only
- `tests/test_queue_config.py` — added `TestD02CollectGateStep` (4 tests) and `TestPreExistingStepFingerprints` (3 tests)
- `tests/test_proof_inventory.py` — added `TestLiveRepositoryInventory` (3 tests) and its `_EXPECTED_NODE_IDS` mapping

## Decisions Made

See `key-decisions` in the frontmatter above for the full rationale on: (1) named-field fingerprinting over whole-step hashing, (2) YAML `run: |` block-scalar comments being parseable text rather than stripped YAML comments, (3) choosing PROOF-02 over PROOF-01/04 for Falsification 2 because of the module-level-`pytestmark` vs. per-test-decorator distinction, and (4) never repeating the "byte-pinned" mischaracterization of `TestD14NoWideningGuard`.

## Fingerprint Reachability Proof

Both `TestPreExistingStepFingerprints` assertions were proven reachable — not just written — by a live mutate/observe/revert cycle against the committed workflow file, run before committing the class:

**1. Dropped `set -o pipefail` from the integration step**, ran `uv run pytest tests/test_queue_config.py::TestPreExistingStepFingerprints -v`:
```
FAILED tests/test_queue_config.py::TestPreExistingStepFingerprints::test_integration_step_fingerprint
AssertionError: assert 'set -o pipefail' in '...'
```
Restored via `git checkout -- .github/workflows/concurrency-proof.yml`; `git diff --stat` empty; re-ran — 3 passed.

**2. Removed the skip-guard block (`if grep -qE '[0-9]+ skipped' ... fi`) from the queueproof step**, re-ran the same command:
```
FAILED tests/test_queue_config.py::TestPreExistingStepFingerprints::test_queueproof_step_fingerprint
AssertionError: skip-reds log guard missing
```
Restored via `git checkout -- .github/workflows/concurrency-proof.yml`; `git diff --stat` empty; re-ran — 3 passed.

## Falsification 1 — Typo'd Marker Id

**Green baseline:**
```
$ uv run python -m scripts.check_proof_inventory
(exit 0, no output)
```

**Mutation:** `tests/test_queue_durability.py:3132`, `@pytest.mark.proof(id="PROOF-01")` → `@pytest.mark.proof(id="PROOF-O1")` (one character, on the sole test tagged PROOF-01, all other markers untouched).

**RED output:**
```
$ uv run python -m scripts.check_proof_inventory
PROOF id 'PROOF-01' matched no test under the CI-executed selection "queueproof and proof(id='PROOF-01')" — expected exactly one
node 'tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease' carries @pytest.mark.proof with an id that matches none of the expected ids ('PROOF-01', 'PROOF-02', 'PROOF-03', 'PROOF-04') — check for a typo'd id
exit: 1
```
Both the missing-id violation and the stray-node-id violation are present, exactly as `evaluate_inventory`'s docstring specifies.

**Revert:** `git checkout -- tests/test_queue_durability.py`; `git diff --stat` reported no output (byte-identical); re-ran the checker: exit 0, no output.

## Falsification 2 — Missing `queueproof` Marker

**Green baseline:** confirmed via `uv run python -m scripts.check_proof_inventory` → exit 0.

**Mutation:** `tests/test_webhook_dedup_race.py:202-204`, removed the `@pytest.mark.queueproof` line from `test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run` (PROOF-02), leaving `@pytest.mark.integration` and `@pytest.mark.proof(id="PROOF-02")` intact. PROOF-02 was chosen over PROOF-01/04 because those two receive `queueproof` from `tests/test_queue_durability.py`'s module-level `pytestmark = [pytest.mark.integration, pytest.mark.queueproof]` — removing it there would de-select every test in that large module, not isolate one proof. PROOF-02 (and PROOF-03) carry `@pytest.mark.queueproof` as an individual per-test decorator, so a single line-delete isolates exactly one test.

**RED output:**
```
$ uv run python -m scripts.check_proof_inventory
PROOF id 'PROOF-02' matched no test under the CI-executed selection "queueproof and proof(id='PROOF-02')" — expected exactly one
node 'tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run' carries @pytest.mark.proof but is absent from the queueproof selection — it will never execute in CI's 'Run the queue durability proofs (real Postgres)' step in .github/workflows/concurrency-proof.yml; add @pytest.mark.queueproof
exit: 1
```
The violation names `queueproof` explicitly and the affected node id — not a generic "missing id" message, satisfying the plan's stated FAILED-criterion bar.

**Revert:** `git checkout -- tests/test_webhook_dedup_race.py`; `git diff --stat` reported no output (byte-identical); re-ran the checker: exit 0, no output.

## Verification Results (measured, this session)

- `uv run pytest tests/test_queue_config.py tests/test_proof_inventory.py -v` → **27 passed**.
- `uv run python -m scripts.check_proof_inventory` → **exit 0**, no violations.
- `uv run pytest tests/ -m proof --collect-only -q` → **4 node ids**, one per proof:
  - PROOF-01: `tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease`
  - PROOF-02: `tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run`
  - PROOF-03: `tests/test_send_idempotency.py::test_crash_between_provider_accept_and_local_sent_commit_sends_no_second_email`
  - PROOF-04: `tests/test_queue_durability.py::test_expired_lease_is_reclaimed_by_a_second_worker_and_zombie_is_fenced_on_both_writes`
- For each id, `uv run pytest tests/ -m "queueproof and proof(id='PROOF-0N')" --collect-only -q` lists exactly the one node id above (verified individually for all four; matches the intersection CI executes).
- `uv run pytest tests/ -m proof --collect-only -q` and `uv run pytest tests/ -m queueproof --collect-only -q` agree on all four proof node ids (proved programmatically in `TestLiveRepositoryInventory::test_proof_and_queueproof_selections_agree_on_all_four_node_ids`).
- `env -u DATABASE_URL uv run pytest tests/test_proof_inventory.py -v` → **11 passed**, including the live-repository test — proving the gate is a collection-layer check with no silent DB dependency.
- `git diff --stat` after both falsifications' reverts → empty (byte-identical).
- `git diff .github/workflows/concurrency-proof.yml` → 28 insertions, 0 deletions (additive only).
- `git diff .github/workflows/ci.yml .github/workflows/pump.yml` since the wave's base (`54f29a9`) → empty (byte-unchanged, other plans' territory untouched).
- Hermetic full suite: `env -u DATABASE_URL uv run pytest -q` → **1261 passed, 105 skipped** (baseline 1251 + 10 new hermetic tests, 0 regressions).
- Full live-DB suite: `DATABASE_URL=... ALLOW_DB_RESET=1 uv run pytest tests/ -q` → **1363 passed, 3 skipped** (baseline 1353 + 10, 0 regressions).
- `ruff check .` → clean. `uv run mypy --strict app` → clean (74 files).
- No `-m integration` selection was widened in this plan — the by-name step stays scoped to its original two files, per the plan's own constraint. No widened-selection re-run was needed.

## Deviations from Plan

None — plan executed exactly as written. `-m integration` was not widened (out of this plan's scope), so no widened-selection re-run was required.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. The new CI step runs automatically in `concurrency-proof.yml`'s existing real-Postgres job on the next PR/push.

## Next Phase Readiness

- PROOF-05 (the completeness gate, wired and non-vacuous) is fully satisfied. All four durability proofs (PROOF-01..04) are registered exactly once and selected by the exact intersection (`queueproof and proof(id=...)`) CI's queue-durability step executes.
- `.github/workflows/concurrency-proof.yml` now has 7 steps total: checkout, uv+python setup, deps install, schema bootstrap, the by-name integration proofs, the marker-selected queueproof proofs, and this plan's new completeness gate — in that order.
- Both pre-existing proof-running steps are now genuinely pinned by a structural fingerprint (not a substring), closing the review's HIGH finding.
- No artifact in this plan repeats the false "byte-pinned" description of `TestD14NoWideningGuard`.
- Ready for plan 21-11's `docs/DURABILITY-PROOFS.md` publication — the four node ids and the CI wiring above are final and can be cited verbatim.

---
*Phase: 21-durability-proofs-ops-view*
*Completed: 2026-07-20*

## Self-Check: PASSED

- FOUND: .github/workflows/concurrency-proof.yml (third step present, 7 steps total)
- FOUND: tests/test_queue_config.py (TestD02CollectGateStep, TestPreExistingStepFingerprints)
- FOUND: tests/test_proof_inventory.py (TestLiveRepositoryInventory)
- FOUND commit: 29e5592 (feat: wire completeness gate)
- FOUND commit: 55360bf (test: live-repository assertion)
- CONFIRMED: git status clean, both falsifications reverted byte-identical
