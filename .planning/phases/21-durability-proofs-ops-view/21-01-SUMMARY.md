---
phase: 21-durability-proofs-ops-view
plan: 01
subsystem: testing
tags: [pytest, markers, ci-gate, static-analysis, durability-proofs]

# Dependency graph
requires:
  - phase: 21-durability-proofs-ops-view
    provides: "21-12/13/14/15 (wave 0 groundwork already landed on this branch's base)"
provides:
  - "Registered `proof` pytest marker carrying a stable id via the keyword argument `id`"
  - "Pure `evaluate_inventory()` decision function detecting four independent selection-layer failure shapes"
  - "`collect_inventory()` subprocess collector selecting the exact intersection CI executes (`queueproof and proof(id=...)`)"
  - "An anchored, exported node-id parsing regex (`NODE_ID_PATTERN`) that raises rather than silently drops unparseable collection lines"
affects: [21-03, 21-04, 21-05, 21-08, 21-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure decision function + thin impure collector, mirroring scripts/check_operator_resolution_inventory.py's shape and tests/test_bound01_private_imports.py's scan_tree_for_violations/synthetic-violation pairing"
    - "Config-registration pin test (TestProofMarkerRegistered) mirroring TestQueueproofMarkerRegistered exactly"

key-files:
  created:
    - scripts/check_proof_inventory.py
    - tests/test_proof_inventory.py
  modified:
    - pyproject.toml
    - tests/test_queue_config.py

key-decisions:
  - "evaluate_inventory's stray-id check is gated on membership in queueproof_marked: a node absent from queueproof_marked is reported only as the missing-queueproof shape, not double-reported as stray too — since a node lacking queueproof necessarily has an empty per_id[X] entry regardless of whether its id is valid, so an ungated stray check would misleadingly co-fire 'id typo' language on a node whose id may in fact be perfectly valid."
  - "Marker description embedded as a single-line TOML string (not Python-style adjacent string-literal concatenation, which TOML does not support) — caught during Task 1 by re-parsing the file with tomllib before proceeding."
  - "Warnings-block lines in collect_inventory's parser are recognized by a stateful start/end marker pair (=== warnings summary === ... -- Docs: ...) rather than swallowed by a permissive catch-all, preserving the 'raise on anything unrecognized' contract for genuinely broken collection output."

requirements-completed: [PROOF-05]

coverage:
  - id: D1
    description: "proof marker registered in pyproject.toml with keyword-id contract recorded as the reason (not a style choice), pinned by TestProofMarkerRegistered"
    requirement: "PROOF-05"
    verification:
      - kind: unit
        ref: "tests/test_queue_config.py::TestProofMarkerRegistered::test_proof_registered_in_pyproject"
        status: pass
      - kind: unit
        ref: "tests/test_queue_config.py::TestProofMarkerRegistered::test_proof_marker_description_records_keyword_id_rationale"
        status: pass
    human_judgment: false
  - id: D2
    description: "evaluate_inventory reds on missing id, duplicate id, stray/typo'd id, and a proof-marked node absent from the queueproof selection, each proven by content-asserting tests; conforming inventory returns no violations"
    requirement: "PROOF-05"
    verification:
      - kind: unit
        ref: "tests/test_proof_inventory.py::TestConformingInventory::test_no_violations_when_everything_lines_up"
        status: pass
      - kind: unit
        ref: "tests/test_proof_inventory.py::TestMissingId::test_missing_id_names_the_offending_id"
        status: pass
      - kind: unit
        ref: "tests/test_proof_inventory.py::TestDuplicateId::test_duplicate_id_names_the_id_and_both_node_ids"
        status: pass
      - kind: unit
        ref: "tests/test_proof_inventory.py::TestStrayId::test_stray_id_names_the_offending_node_id"
        status: pass
      - kind: unit
        ref: "tests/test_proof_inventory.py::TestMissingQueueproofMarker::test_absent_from_queueproof_selection_names_queueproof_and_node_id"
        status: pass
      - kind: unit
        ref: "tests/test_proof_inventory.py::TestAllFourShapesSimultaneously::test_all_four_shapes_reported_at_once"
        status: pass
    human_judgment: false
  - id: D3
    description: "Node-id parsing pinned against an anchored pattern (plain + parametrized node ids match; trailing summary line + bare directory path are rejected)"
    verification:
      - kind: unit
        ref: "tests/test_proof_inventory.py::TestNodeIdPattern::test_matches_plain_and_parametrized_node_ids"
        status: pass
      - kind: unit
        ref: "tests/test_proof_inventory.py::TestNodeIdPattern::test_rejects_trailing_summary_and_bare_directory"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-07-20
status: complete
---

# Phase 21 Plan 01: Proof-Identity Substrate & Selection-Layer Completeness Checker Summary

**Registered a `proof(id=...)` pytest marker and built `scripts/check_proof_inventory.py`'s pure `evaluate_inventory()`, red-proofed against four independent selection-layer failure shapes — including the one that catches a durability proof carrying a valid id but never actually selected by CI's `queueproof` marker.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-20T00:00:00Z (approx.)
- **Completed:** 2026-07-20
- **Tasks:** 2 completed
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments

- Registered the `proof` pytest marker in `pyproject.toml`, with its description recording (as a correctness reason, not a style note) that the id must be passed as the keyword argument `id` — pytest's `-m` marker-expression syntax only supports selecting on keyword marker arguments.
- Added `TestProofMarkerRegistered` to `tests/test_queue_config.py`, sibling to the existing `TestQueueproofMarkerRegistered`, pinning both the registration and the keyword-`id` rationale substring.
- Built `scripts/check_proof_inventory.py`: `EXPECTED_PROOF_IDS`, the pure `evaluate_inventory()` decision function, the impure `collect_inventory()` subprocess collector (selecting the exact intersection `.github/workflows/concurrency-proof.yml` executes: `queueproof and proof(id='PROOF-0N')`), an exported anchored `NODE_ID_PATTERN`, and `main()`.
- Proved via `tests/test_proof_inventory.py` (8 tests) that `evaluate_inventory` reds on all four independent failure shapes — missing id, duplicate id, stray/typo'd id, and a `proof`-marked node absent from the `queueproof` selection — each isolated to its own test and asserted on violation *content*, plus a conforming-inventory no-false-positive case, an all-four-at-once case, and two node-id-pattern pin tests.
- Confirmed `.github/workflows/concurrency-proof.yml` is byte-unchanged (`git diff --stat` shows no entry) — wiring is 21-09's job.

## Task Commits

Each task was committed atomically:

1. **Task 1: Register the `proof` marker with a keyword id argument** - `34fde41` (feat)
2. **Task 2: Build the inventory checker as a pure decision function plus a thin collector** - RED `ed57a5d` (test) → GREEN `2741d1a` (feat)

_TDD task: RED phase committed the failing test module (ModuleNotFoundError, since scripts/check_proof_inventory.py did not exist yet); GREEN phase committed the implementation plus one test fix (see Deviations)._

## Files Created/Modified

- `pyproject.toml` — appended the `proof` marker registration (4th entry in `[tool.pytest.ini_options] markers`)
- `tests/test_queue_config.py` — added `TestProofMarkerRegistered` (2 test methods)
- `scripts/check_proof_inventory.py` (NEW) — `EXPECTED_PROOF_IDS`, `NODE_ID_PATTERN`, `evaluate_inventory()`, `collect_inventory()`, `_run_collect_only()`, `_parse_node_ids()`, `main()`
- `tests/test_proof_inventory.py` (NEW) — 8 hermetic tests over `evaluate_inventory` and `NODE_ID_PATTERN`

## Decisions Made

- **Stray-check gating on `queueproof_marked`:** the literal spec definition of "stray" ("any node id present in `all_marked` that appears under no expected id") would, read completely literally, also fire for a node that lacks the `queueproof` marker (since its own `per_id` entry is necessarily empty too, by construction of the intersection query) — even when that node's id is perfectly valid. Gating the stray check on `node_id in queueproof_set` avoids misleadingly labeling a "just needs `@pytest.mark.queueproof`" test as an "id typo" — the missing-queueproof violation alone already names the correct fix. All plan-supplied acceptance-criteria one-liners (which don't rely on this distinction) still pass unchanged.
- **TOML string, not Python string concatenation:** the first edit to `pyproject.toml` used Python-style adjacent-string-literal concatenation across lines, which TOML does not support. Caught immediately by re-parsing the file with `tomllib` before moving on; collapsed to one valid single-line TOML string.
- **Warnings-block parsing via stateful markers:** `_parse_node_ids` recognizes pytest's `=== warnings summary ===` / `-- Docs: ...` block by tracking a boolean between those two literal markers, rather than a permissive "ignore anything I don't recognize" fallback — preserving the requirement that a genuinely broken/unparseable collection line still raises.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Own test's queueproof-shape filter also matched the co-occurring missing-id violation**
- **Found during:** Task 2, GREEN phase, first test run
- **Issue:** `TestMissingQueueproofMarker`'s assertion filtered violations on the substring `"queueproof"`, but the missing-id violation's own message text quotes the selection expression `"queueproof and proof(id='PROOF-03')"`, so it also matched the filter — the test asserted `len(...) == 1` and got `2`.
- **Fix:** Narrowed the filter to the node-id substring (unique to the missing-queueproof-shape violation), then asserted `"queueproof"` is present within that narrowed match.
- **Files modified:** `tests/test_proof_inventory.py`
- **Verification:** `uv run pytest tests/test_proof_inventory.py -v` — all 8 tests pass.
- **Committed in:** `2741d1a` (Task 2 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug in test assertion, caught during the RED→GREEN loop itself, not a defect in the shipped implementation).
**Impact on plan:** No scope creep. The fix sharpened test isolation; `evaluate_inventory`'s implementation was correct on first pass against all plan-supplied acceptance-criteria one-liners.

## Issues Encountered

None beyond the two auto-fixed items documented above (both caught and resolved within the normal TDD/verification loop, not left open).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- The canonical marker application form for plans 21-03/04/05/08 is `@pytest.mark.proof(id="PROOF-0N")` (keyword `id`, not positional — the registered marker description in `pyproject.toml` records this as the reason).
- `evaluate_inventory(per_id, all_marked, queueproof_marked, expected_ids)` and `collect_inventory(expected_ids) -> (per_id, all_marked, queueproof_marked)` signatures are final; both now carry the `queueproof_marked` selection alongside `per_id`/`all_marked`, as plan 21-09 will consume all three when wiring `main()` into `.github/workflows/concurrency-proof.yml`.
- `NODE_ID_PATTERN` is exported and pinned; plan 21-09's live-repo assertion can reuse it directly rather than reinventing node-id parsing.
- `.github/workflows/concurrency-proof.yml` remains byte-unchanged — confirmed via `git diff --stat`.
- Hermetic suite: 1201 passed, 96 skipped (baseline 1191 + 10 new tests, 0 regression). `ruff check .` and `uv run mypy --strict app` both clean.

---
*Phase: 21-durability-proofs-ops-view*
*Completed: 2026-07-20*

## Self-Check: PASSED

- FOUND: scripts/check_proof_inventory.py
- FOUND: tests/test_proof_inventory.py
- FOUND: .planning/phases/21-durability-proofs-ops-view/21-01-SUMMARY.md
- FOUND commit: 34fde41 (feat: register proof marker)
- FOUND commit: ed57a5d (test: RED failing tests)
- FOUND commit: 2741d1a (feat: GREEN implementation)
