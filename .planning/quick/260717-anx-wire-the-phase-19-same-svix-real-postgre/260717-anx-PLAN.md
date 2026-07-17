---
quick_id: 260717-anx
status: complete
description: Wire the Phase 19 same-Svix real-Postgres deduplication test into the ephemeral queueproof CI gate and verify its exact execution
---

# Quick Task 260717-anx Plan

## Task 1: Close the same-Svix CI proof gap

**Files:** `tests/test_webhook_dedup_race.py`, `.github/workflows/concurrency-proof.yml`

**Action:** Mark only the existing concurrent same-Svix durability proof as `queueproof`, preserving its `integration` marker and production-safe live-DB guard. Update the workflow commentary so it no longer claims the entire module is dormant.

**Verify:** Confirm queueproof collection names the exact test, run the hermetic local checks, push, and require the ephemeral-Postgres GitHub log to show the exact test passed without skips.

**Done:** The exact same-Svix test is executed by the real-Postgres CI gate and its passing node ID is visible in the run log.
