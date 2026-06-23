---
id: 260623-07
created: 2026-06-23
source: Phase 05 REVIEW-3 (IN-01)
resolves_phase:
priority: low
---

# load_all_runs uses SELECT pr.* — switch to explicit column list

`app/db/repo.py` `load_all_runs` does `SELECT pr.*, b.name AS business_name`. Functionally
safe today (returns a plain dict for the runs-list template, not a Pydantic extra="forbid"
parse, so an extra column won't crash). But it's inconsistent with the explicit-column-list
discipline used everywhere else in repo.py (RUN_COLS, EMPLOYEE_COLS, _INBOUND_COLS), and a
future schema column would silently widen the payload handed to the template (incl. large
JSONB blobs — also overlaps the WR-03 perf note in todo 260623-01).

Fix (low priority): replace `pr.*` with an explicit projection of exactly the columns the
runs-list row needs (id, business_id, status, created_at, updated_at, decision/extracted
summary fields used by the Summary cell) + `b.name AS business_name`. Keep it lean — the
list view does not need the full extracted_data/decision/reconciliation JSONB.
