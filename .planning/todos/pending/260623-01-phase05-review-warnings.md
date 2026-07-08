---
id: 260623-01
created: 2026-06-23
source: 05-REVIEW.md
resolves_phase: 15
priority: medium
---

# Phase 05 code-review: deferred Warnings + Info

The 3 Criticals (CR-01/02/03) were fixed during Phase 05 execution. These lower-severity
findings were deferred — candidates for a 05.1 gap phase or standalone fixes. Full detail
in `.planning/phases/05-dashboard-delivery/05-REVIEW.md`.

## Warnings
- **WR-01** — Reply-threading broken after crash+retrigger: the outbound `insert_email_message`
  upsert on `(run_id, purpose)` overwrites `message_id`, so a resumed/retriggered run can lose
  the original thread anchor. Verify the threading round-trip survives retrigger.
- **WR-02** — Thread-unsafe pool singleton in `app/db/supabase.py` (module-level `ConnectionPool`
  init not guarded). Low risk on a single-worker demo, but document or guard.
- **WR-03** — `load_all_runs` uses `SELECT pr.*`, fetching full `extracted_data`/`decision`/
  `reconciliation` JSONB blobs on every runs-list page load. Project to the columns the list needs.
- **WR-04** — `Content-Disposition` header for the paystub PDF is injectable via an employee name
  containing `"` or newline. Sanitize/quote the filename.
- **WR-05** — Missing path-containment check on `eval/summary.json` (and fixture) path reads.
  Confirm no traversal surface even though paths are currently committed/static.

## Info
- **INFO-01** — `needs_clarification` status missing from the dashboard badge maps (inconsistent;
  currently dead but should be added for completeness).
- **INFO-02** — The LLM retry prompt echoes raw `ValidationError` content (which can include model
  output) back to the provider. Scrub before re-sending.
