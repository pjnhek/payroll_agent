---
phase: 16-queue-substrate-unblocked-webhook
plan: 02
subsystem: infra
tags: [pytest, ci, github-actions, pydantic-settings, config]

# Dependency graph
requires: []
provides:
  - "`queueproof` pytest marker registered in pyproject.toml, orthogonal to `integration`"
  - "A second, narrow CI gate in concurrency-proof.yml selecting `-m queueproof` over tests/, with its own skip/passed guards"
  - "The pre-existing two-file `-m integration` gate proven byte-identical to its prior form"
  - "Settings.worker_count / .lease_seconds / .max_attempts / .queue_poll_seconds — env-driven with committed defaults"
  - "LEASE_SECONDS' derivation written down as a machine-checkable constraint comment (STALE_THRESHOLD cross-reference + the 210s ceiling)"
  - "render.yaml + .env.example carry the four knobs as committed non-secret values"
  - "tests/test_queue_config.py — defaults, env override, derivation-presence guard, no-widening guard, marker-registration guard"
affects: [16-04, 16-07, 16-09, 16-10, 21]

# Tech tracking
tech-stack:
  added: [types-pyyaml (dev-only, mypy stubs for PyYAML)]
  patterns:
    - "Marker-driven CI collection for durability proofs (collect by @pytest.mark.queueproof, not by filename) so future proof files need zero workflow edits"
    - "Config knob derivations cross-reference an existing documented constant (STALE_THRESHOLD) instead of duplicating the arithmetic"

key-files:
  created:
    - tests/test_queue_config.py
  modified:
    - pyproject.toml
    - .github/workflows/concurrency-proof.yml
    - app/config.py
    - render.yaml
    - .env.example

key-decisions:
  - "Kept the existing concurrency-proof.yml gate byte-identical (2 named files, -m integration) and added an entirely separate step selecting -m queueproof, rather than widening the existing step's selector — whole-suite -m integration collection would wake 10 dormant live-DB test modules against the shared ephemeral Postgres."
  - "LEASE_SECONDS=900 reuses runs.py's already-reviewed STALE_THRESHOLD derivation by cross-reference rather than re-deriving the 210s worst-case pipeline gap independently."
  - "The queueproof step's 'N passed' guard is documented as defense against a disarmed pipeline (|| true / dropped pipefail), not as the mechanism that catches a whole-marker typo — pytest's own NO_TESTS_COLLECTED exit code (5) plus pipefail already reds that case."

requirements-completed: [QUEUE-02, QUEUE-03]

coverage:
  - id: D1
    description: "queueproof marker registered in pyproject.toml; a new CI step collects `-m queueproof` over tests/ with its own skip/passed guards, while the pre-existing two-file integration gate stays byte-identical"
    requirement: "QUEUE-02"
    verification:
      - kind: other
        ref: "uv run python -c \"...yaml.safe_load...assert 'uv run pytest tests/ -m integration' not in s...\" (D-14 OK)"
        status: pass
      - kind: other
        ref: "uv run python -c \"...sel(old)[0] in sel(new)...\" (existing gate byte-identical)"
        status: pass
      - kind: unit
        ref: "tests/test_queue_config.py::TestD14NoWideningGuard (2 tests)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Settings.worker_count/.lease_seconds/.max_attempts/.queue_poll_seconds are env-driven with committed defaults (2, 900, 5, 20); LEASE_SECONDS carries its derivation as a constraint comment"
    requirement: "QUEUE-03"
    verification:
      - kind: unit
        ref: "tests/test_queue_config.py::TestQueueKnobDefaults (2 tests)"
        status: pass
      - kind: unit
        ref: "tests/test_queue_config.py::TestDerivationIsWrittenDown::test_lease_seconds_cites_stale_threshold_and_210"
        status: pass
      - kind: unit
        ref: "tests/test_queue_config.py::TestRenderYamlDriftGuard::test_render_yaml_carries_all_four_keys"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-07-14
status: complete
---

# Phase 16 Plan 02: Queue Proof Surface & Config Knobs Summary

**A marker-driven `queueproof` CI gate (byte-identical existing gate preserved) plus four env-driven job-queue knobs, with `LEASE_SECONDS`' derivation machine-pinned to `STALE_THRESHOLD` rather than left as a magic number.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-14T17:49:00Z (approx)
- **Completed:** 2026-07-14T18:14:01Z
- **Tasks:** 3
- **Files modified:** 6 (5 modified, 1 created)

## Accomplishments

- Registered the `queueproof` pytest marker (`pyproject.toml`) and added a NEW second step to `.github/workflows/concurrency-proof.yml` — "Run the queue durability proofs (real Postgres)" — that collects `tests/ -m queueproof`, mirroring the existing step's two-part skip/passed guard shape. The pre-existing "Run the real-Postgres invariant proofs" step is proven byte-identical to its prior form (its pytest line was diffed against `master` programmatically, not eyeballed).
- Added four env-driven `Settings` fields (`worker_count=2`, `lease_seconds=900`, `max_attempts=5`, `queue_poll_seconds=20`) to `app/config.py`, with `lease_seconds` carrying: (a) a cross-reference to `app/routes/runs.py`'s `STALE_THRESHOLD` derivation (210s worst-case pipeline gap, 900s ≈ 4x that ceiling) instead of re-deriving the arithmetic, (b) the narrowed (not "harmless") claim about what a double-run costs the client-facing send, pointing at `app/pipeline/send_guard.py` for the fix, and (c) why there is no lease heartbeat.
- Committed the four knobs to `render.yaml` (non-secret `value:` entries, with a note that `WORKER_COUNT + 2` must respect the pool's `max_size=5` budget) and `.env.example`.
- Created `tests/test_queue_config.py` (7 tests): the four defaults exact, `WORKER_COUNT=0` env override, `render.yaml` drift guard, `LEASE_SECONDS` derivation-presence guard, two no-widening guards against `concurrency-proof.yml`, and `queueproof` marker registration.

## Task Commits

Each task was committed atomically:

1. **Task 1: Register the `queueproof` marker and add a NARROW second CI gate** — `a75b13d` (feat)
2. **Task 2: Add the four env-driven queue knobs with their derivations** — `4832663` (feat)
3. **Task 3: Commit the knobs to render.yaml / .env.example and pin the config contract with a test** — `41b2ab5` (feat)

**Follow-up hygiene fix (discovered running the full suite, see Deviations):** `149d311` (docs)

_No TDD tasks in this plan — plain `type="auto"` tasks._

## Files Created/Modified

- `pyproject.toml` — registers the `queueproof` marker (Task 1); adds `types-pyyaml` dev dependency (Task 3, for `import yaml` mypy stubs)
- `.github/workflows/concurrency-proof.yml` — adds the new marker-driven step; existing step's pytest line proven byte-identical (Task 1)
- `app/config.py` — adds `worker_count`, `lease_seconds`, `max_attempts`, `queue_poll_seconds` fields with constraint comments (Task 2)
- `render.yaml` — commits the four knobs as non-secret `value:` entries (Task 3)
- `.env.example` — adds the four knob placeholders (Task 3)
- `tests/test_queue_config.py` — new file, 7 tests pinning the config contract (Task 3)
- `uv.lock` — updated by `uv add --dev types-pyyaml` (Task 3)

## Decisions Made

- Kept the existing `concurrency-proof.yml` gate byte-identical and added an entirely separate step for `queueproof`, per D-14 (whole-suite `-m integration` collection would wake 10 dormant live-DB test modules against the shared ephemeral Postgres — confirmed by `git grep -l 'pytest.mark.integration' -- tests/` returning 12 files against only 2 named in the existing gate).
- `LEASE_SECONDS=900` reuses `runs.py`'s already-reviewed `STALE_THRESHOLD` derivation by cross-reference rather than maintaining two independent copies of the "210s x ~4" arithmetic.
- The `queueproof` step's `[0-9]+ passed` guard is documented with its TRUE rationale (defense against a disarmed pipeline — `|| true` or a dropped `pipefail`) rather than the false claim (rejected in an earlier plan draft, per the plan's own instructions) that a zero-collecting marker "exits green"; pytest's own `NO_TESTS_COLLECTED` exit code (5) plus `set -o pipefail` already reds that case before the guard is reached.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Stripped decision-ID/phase-number citations from queue comments to satisfy the repo's comment-provenance guard**
- **Found during:** Running the full suite after Task 3 (`uv run pytest -q`)
- **Issue:** Task 1's workflow comments and Task 2's `app/config.py` comments — written per this plan's own explicit instructions to cite `D-03`, `D-14`, `D-04`, `Phase 16`, `Phase 18`, etc. — tripped `tests/test_comment_provenance_guard.py`, a repo-wide CI gate (from the v3 milestone's comment-hygiene phase) that forbids decision-ID and phase-number citations anywhere in source comments/docstrings/string literals: "keep the constraint, drop the label." This guard is not referenced in the 16-02-PLAN.md `<read_first>` list, so it was discovered only when the full suite was run for the first time in this plan.
- **Fix:** Rewrote the affected comments in `app/config.py`, `.github/workflows/concurrency-proof.yml`, `render.yaml`, `.env.example`, and `tests/test_queue_config.py` to state the identical underlying constraints and rationale without the decision-ID/phase-number labels. No behavior change — verified by re-running both falsifying mutations (derivation-comment strip, gate-widening) against the rewritten text and confirming they still go red as required, then confirming green again after restore.
- **Files modified:** `app/config.py`, `.github/workflows/concurrency-proof.yml` (both re-committed in the follow-up commit; `render.yaml`, `.env.example`, `tests/test_queue_config.py` were written clean the first time in Task 3's commit)
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree tests/test_queue_config.py -q` → 8 passed. Full suite re-run: 650 passed, 53 skipped. `ruff check .` and `mypy` (both bare `mypy` and `mypy app`) clean.
- **Committed in:** `149d311` (follow-up commit, since `a75b13d` and `4832663` were already committed when this was discovered)

---

**Total deviations:** 1 auto-fixed (Rule 1 — comment-provenance guard compliance)
**Impact on plan:** No behavior/logic change; purely comment text. All plan-specified content (derivations, rationale, gap statements) is preserved, only the ticket/decision/phase labels are removed per the repo's own established convention.

## Issues Encountered

None beyond the deviation above.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- The `queueproof` marker exists and is collected in CI by marker, not filename — plans 16-04, 16-07, 16-09, and 16-10 can each add `@pytest.mark.queueproof` tests with zero further workflow edits. Each of those plans must still run `uv run pytest tests/ -m queueproof --collect-only -q` at authoring time to confirm its new test is actually collected (the stated gap this CI gate cannot close on its own).
- The four config knobs (`WORKER_COUNT`, `LEASE_SECONDS`, `MAX_ATTEMPTS`, `QUEUE_POLL_SECONDS`) are available for `app/queue/worker.py` (plan 16-07), `app/db/repo/jobs.py`'s `claim_job`/`enqueue_job` (plan 16-04), and the pool-budget boot assertion (plan 16-07, `WORKER_COUNT + 2 <= max_size`).
- No blockers for downstream plans.

---
*Phase: 16-queue-substrate-unblocked-webhook*
*Completed: 2026-07-14*

## Self-Check: PASSED

All 4 task commit hashes (`a75b13d`, `4832663`, `41b2ab5`, `149d311`) confirmed present via
`git log --oneline --all`. All 6 modified/created files (`pyproject.toml`,
`.github/workflows/concurrency-proof.yml`, `app/config.py`, `render.yaml`, `.env.example`,
`tests/test_queue_config.py`) confirmed present on disk.
