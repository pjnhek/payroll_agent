---
phase: quick-260717-anx
status: complete
completed: 2026-07-17
commits: [3179e4a, 7f3f1aa, 130c038]
files_modified:
  - tests/test_webhook_dedup_race.py
  - .github/workflows/concurrency-proof.yml
---

# Quick Task 260717-anx: Same-Svix Real-Postgres CI Proof

**One-liner:** The exact concurrent same-Svix redelivery test now runs against GitHub's isolated Postgres service and proves one event, one INGEST job, and one run.

## Completed

- Promoted only the exact same-Svix durability test to the existing `queueproof` marker gate while retaining its `integration` marker.
- Made the proof provider-faithful: a signed provider envelope enters the webhook, the delayed provider parse seam returns the bounded fixture email, and `seeded_db` resets and seeds the isolated database.
- Kept the wider integration module outside the marker-selected CI surface.
- Removed workflow-comment provenance wording rejected by the repository guard.

## Verification

- GitHub concurrency-proof run `29589513220`: exact node `tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run` **PASSED** against ephemeral Postgres.
- Queueproof result: **44 passed, 1060 deselected, 1 warning**.
- GitHub CI run `29589513261`: test suite, mypy strict, and Ruff all passed.
- GitHub eval run `29589513190`: passed.
- GitHub deploy-migrate run `29589513283`: passed.
- Local provenance guard: 1 passed. Local Ruff: all checks passed.

## Course Correction

The first CI execution exposed a stale fixture-shaped signed payload and failed with HTTP 400. The test was corrected to use the production provider envelope before accepting the proof; no production behavior was weakened.

## Self-Check: PASSED

- [x] Exact test node is visible and passed in the GitHub log.
- [x] Real Postgres was initialized and seeded by the CI job.
- [x] Full companion CI is green at the same source revision.
