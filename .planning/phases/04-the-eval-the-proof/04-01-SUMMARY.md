---
phase: 04-the-eval-the-proof
plan: "01"
subsystem: eval
tags: [eval, fixtures, json, pydantic, seed]

requires:
  - phase: 02.1-deterministic-decisioning
    provides: "reconcile_names + decide as pure deterministic code; final taxonomy (exact/stored-alias/first-time-alias/typo/collision/unknown); seed data with collision pair and all 7 employees"
  - phase: 01-thin-foundation
    provides: "InboundEmail/Extracted/Decision Pydantic contracts (extra=forbid); seed.py importable roster with fixed UUIDs"

provides:
  - "15 hand-labeled eval fixtures in eval/fixtures/ spanning all 9 taxonomy categories with full per-stage expected blocks"
  - "15 stubbed _extraction.json caches committed alongside fixtures enabling hermetic --check CI with no live LLM"
  - "DIVERGENCES.md documenting 2 deliberate cache divergences (precision miss + field miss) so extraction metrics are non-trivial on day one"
  - "eval/draft_candidate_emails.py throwaway drafting helper using Kimi (draft tier) with allow_live_llm gate"

affects:
  - "04-02 (run_eval.py scorer imports these fixtures + caches as its data plane)"
  - "04-03 (chart emitter reads per-category results derived from these fixture labels)"
  - "04-04 (CI workflow runs --check over these fixtures)"

tech-stack:
  added: []
  patterns:
    - "Fixture-as-self-contained-labeled-JSON: input envelope + fixture_category + expected block in one file (D-01/D-02/D-03)"
    - "Record-once/replay-from-cache: _extraction.json committed beside each fixture for hermetic CI (D-05)"
    - "Deliberate cache divergence for non-trivial extraction metrics: phantom employee (precision miss) on fixture 10, wrong hours (field miss) on fixture 08 (D-06)"
    - "Dual-category grouping: fixture_category (per-fixture decision chart) + name_category per reconciliation entry (per-name chart) (D-03)"

key-files:
  created:
    - "eval/fixtures/01_exact_match_coastal.json"
    - "eval/fixtures/02_stored_alias_metro.json"
    - "eval/fixtures/03_collision_metro.json"
    - "eval/fixtures/04_unknown_shorthand_metro.json"
    - "eval/fixtures/05_typo_coastal.json"
    - "eval/fixtures/06_first_time_alias_metro.json"
    - "eval/fixtures/07_missing_hours_coastal.json"
    - "eval/fixtures/08_vague_hours_coastal.json"
    - "eval/fixtures/09_buried_reply_metro.json"
    - "eval/fixtures/10_multi_employee_coastal.json"
    - "eval/fixtures/11_multi_employee_metro.json"
    - "eval/fixtures/12_exact_process_summit.json"
    - "eval/fixtures/13_exact_process_metro.json"
    - "eval/fixtures/14_collision_process_summit.json"
    - "eval/fixtures/15_stored_alias_process_coastal.json"
    - "eval/fixtures/*_extraction.json (15 files)"
    - "eval/fixtures/DIVERGENCES.md"
    - "eval/draft_candidate_emails.py"
  modified: []

key-decisions:
  - "Use Priya Nair's 'P. Nair' alias for fixture 02 (stored-alias PROCESS) — David Reyes has only 'D. Reyes' (the collision alias), so Priya Nair is the only Metro Deli employee with a unique stored alias"
  - "Fixture 10 hosts the precision-miss divergence (phantom 'John Smith') as a multi-employee fixture where a phantom is the clearest failure the deterministic gate can't catch"
  - "Fixture 08 hosts the field-miss divergence (cache guesses 40 hours where expected is null) — vague-hours is the clearest case of an extractor inventing a number"
  - "7 PROCESS fixtures out of 15 ensures always-clarify baseline fails visibly (D-11 floor is 4; we have 7 for headroom)"

patterns-established:
  - "Eval fixture schema: top-level id/message_id/from_addr/body_text/created_at (InboundEmail fields) + fixture_category + expected{extracted,reconciliation,decision}"
  - "Extraction cache schema: Extracted JSON with run_id=all-zeros + employees + pay_period_start (no extra keys — Extracted has extra=forbid)"
  - "Divergence documentation: separate DIVERGENCES.md sidecar listing fixture, type, and why — no extra keys in cache JSON itself"

requirements-completed: [EVAL-01, EVAL-02]

duration: 6min
completed: 2026-06-22
---

# Phase 04 Plan 01: Eval Fixture Corpus Summary

**15 hand-labeled eval fixtures spanning all 9 taxonomy categories committed with full per-stage expected blocks, stubbed extraction caches, and a throwaway Kimi-tier drafting helper — the data plane for the 04-02 scorer.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-06-22T20:05:56Z
- **Completed:** 2026-06-22T20:12:01Z
- **Tasks:** 2 / 2
- **Files modified:** 32 (30 JSON fixtures + DIVERGENCES.md + draft_candidate_emails.py)

## Accomplishments

- Created 15 labeled eval fixtures covering all 9 taxonomy categories: exact (4), stored-alias (2), collision (2), typo (2), unknown (1), first-time-alias (1), missing-hours (1), vague-hours (1), buried-reply (1)
- 7 PROCESS fixtures (01, 02, 09, 12, 13, 14, 15) — well above the D-11 minimum of 4, ensuring an always-clarify baseline fails visibly on the confusion matrix
- 2 multi-employee fixtures (10: Coastal exact+typo; 11: Metro exact+collision+exact) covering multiple name_categories in one email (D-18)
- 15 stubbed _extraction.json caches committed beside each fixture (D-05), with 2 deliberate divergences: fixture 10 has phantom "John Smith" (precision miss) and fixture 08 guesses "40" where expected is null (field miss) — extraction F1 and field_accuracy will be < 1.0 on day-one scoring
- eval/draft_candidate_emails.py: throwaway helper, Kimi draft tier, allow_live_llm gate, raises SystemExit when flag is absent

## Task Commits

1. **Task 1: Fixture corpus — 15 labeled eval fixtures with stubbed cached extractions** - `90c297d` (feat)
2. **Task 2: Bootstrap drafting helper — draft_candidate_emails.py** - `4b34ef0` (feat)

## Files Created/Modified

- `eval/fixtures/01_exact_match_coastal.json` — Single exact match: Maria Chen 40h, PROCESS
- `eval/fixtures/02_stored_alias_metro.json` — Stored alias: P. Nair (Priya Nair), PROCESS
- `eval/fixtures/03_collision_metro.json` — Collision: D. Reyes (both David + Daniel Reyes), CLARIFY
- `eval/fixtures/04_unknown_shorthand_metro.json` — Unknown: "Dave Reyes" (no alias), CLARIFY
- `eval/fixtures/05_typo_coastal.json` — Typo: "James Okafr" (dropped letter), CLARIFY
- `eval/fixtures/06_first_time_alias_metro.json` — First-time alias: "Priya" (no stored alias), CLARIFY
- `eval/fixtures/07_missing_hours_coastal.json` — Missing hours: Maria Chen hourly, all null, CLARIFY
- `eval/fixtures/08_vague_hours_coastal.json` — Vague hours: "about the same as usual", null, CLARIFY
- `eval/fixtures/09_buried_reply_metro.json` — Buried reply: David Reyes + Priya Nair in reply thread, PROCESS
- `eval/fixtures/10_multi_employee_coastal.json` — Multi-employee (exact+typo): Maria Chen + "Jame Okafor", CLARIFY
- `eval/fixtures/11_multi_employee_metro.json` — Multi-employee (exact+collision+exact): David Reyes + D.Reyes + Priya Nair, CLARIFY
- `eval/fixtures/12_exact_process_summit.json` — Exact: Thomas Bergmann salaried, PROCESS (D-11)
- `eval/fixtures/13_exact_process_metro.json` — Exact: David Reyes full name 40h, PROCESS (D-11)
- `eval/fixtures/14_collision_process_summit.json` — Exact: Sandra Kim 80h biweekly, PROCESS (D-11)
- `eval/fixtures/15_stored_alias_process_coastal.json` — Stored alias: M. Chen (Maria Chen), PROCESS
- `eval/fixtures/*_extraction.json` — 15 stubbed caches; 08 and 10 deliberately diverge
- `eval/fixtures/DIVERGENCES.md` — Table documenting 2 deliberate cache divergences
- `eval/draft_candidate_emails.py` — Throwaway Kimi drafting helper, allow_live_llm gate

## Deviations from Plan

None — plan executed exactly as written. All Codex review fixes pre-applied in the plan were honored:
- UUIDs verified against seed.py for all matched employees
- David Reyes has only the collision alias "D. Reyes" — Priya Nair's "P. Nair" used for fixture 02
- Character-level typos used (dropped letter), not whitespace variants that normalize to exact
- James Okafor is salaried (no missing-hours fixture), Maria Chen (hourly) used for fixture 07
- Fixture 08 cache hosts the field-miss divergence; fixture 10 hosts the precision-miss (phantom employee, not same-name hours change)

## Self-Check

- [x] All 15 fixture files exist in eval/fixtures/
- [x] All 15 extraction cache files exist
- [x] eval/draft_candidate_emails.py exists
- [x] eval/fixtures/DIVERGENCES.md exists
- [x] Commits 90c297d and 4b34ef0 exist
- [x] Full validation script exits 0 with "All fixture validations passed."
- [x] 7 PROCESS fixtures (>= 4 required by D-11)
- [x] precision_miss_fixtures >= 1 (fixture 10: phantom John Smith)
- [x] field_miss_fixtures >= 1 (fixture 08: guessed 40 vs null)

## Self-Check: PASSED
