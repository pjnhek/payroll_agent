---
phase: 4
reviewers: [codex]
reviewed_at: 2026-06-22T18:31:29Z
plans_reviewed: [04-01-PLAN.md, 04-02-PLAN.md, 04-03-PLAN.md, 04-04-PLAN.md]
reviewer_versions:
  codex: codex-cli 0.135.0
---

# Cross-AI Plan Review — Phase 4 (The Eval)

## Codex Review

## Summary

The plans are directionally strong and mostly aligned with the phase thesis: they preserve the DRY seam by importing production `reconcile_names`, `validate`, and `decide`; they make false-process visible; and they keep the judge/DB work optional. However, there are several credibility-breaking issues that should be fixed before execution. The biggest problems are that extraction caches are planned as hand-authored "correct stubs," path-A deterministic scoring uses cached extraction instead of labeled expected extraction, reconciliation scoring ignores `matched_employee_id`, and the false-process rate/chart are defined incorrectly enough to mislead.

## Strengths

- The DRY-seam intent is explicit: `run_eval.py` imports the real `reconcile_names`, `validate`, and `decide`, not parallel logic.
- The phase is sensibly split: fixture corpus, scorer, chart/CI, then optional judge/DB.
- D-09 is well scoped: one `calculate()` smoke test reusing the Phase-3 Thomas Bergmann golden, avoiding a second net-pay oracle.
- The suite includes multiple intended `process` fixtures, so "always clarify" is at least visible as a bad baseline.
- CI correctly aims to use the same `run_eval.py --check` entrypoint, not a separate scorer.
- Scope discipline is mostly good: 04-04 is explicitly optional and 04-01..03 are intended to ship alone.

## Concerns

- **HIGH — 04-01 Task 1 / 04-02 Task 2:** The `_extraction.json` files are described as "stubbed" caches that match expected extraction. That makes extraction F1 artificially perfect and does not test the real LLM extraction failure mode D-06 is meant to catch. If these are not raw recorded extractor outputs, the extraction metric is not credible.
- **HIGH — 04-02 Task 2:** Path-A deterministic scoring is wrong as written. D-07 says isolated scoring should feed the labeled expected extraction into `reconcile_names → validate → decide`; the plan feeds `actual_extracted` from cache. Once caches become real LLM output, deterministic decision accuracy becomes confounded by extraction errors.
- **HIGH — 04-02 Task 2:** Reconciliation scoring ignores `expected_matched_employee_id`. It only checks `source` and `resolved`, so a wrong-but-real match can pass as correct. That directly violates D-02's reason for labeling the intended employee.
- **HIGH — 04-02 Task 2 / 04-03 Task 1:** The false-process rate denominator is likely wrong. The plan uses `false_process / (false_process + true_process)`, which is "among actual process decisions, how many were wrong." The risk metric should be at least reported as `false_process / expected_clarify_total`, because the dangerous failure is "cases that should clarify but processed."
- **HIGH — 04-03 Task 1:** The chart highlights the wrong confusion-matrix cell. With the proposed table, `table[1, 2]` is false-process; `table[2, 2]` is true-clarify. The current plan would visually mark the safe cell as dangerous.
- **HIGH — 04-01 Task 1:** Several fixture instructions show wrong employee UUIDs, e.g. `00000000-...0001` instead of seeded `e0000001-...0001`. The validation script does not check `expected_matched_employee_id` against seed data, so bad labels could silently land.
- **MEDIUM — 04-02 Task 2:** Extraction precision/recall uses dicts keyed by normalized name, which collapses duplicate extracted employees. A duplicated pay line is a dangerous extraction failure and should count as an extra/hallucinated employee, not disappear during scoring.
- **MEDIUM — 04-02 Task 2:** `--check` appears to compare only a subset of metrics. It should include gate-structure accuracy, per-category decision fractions, confusion counts, reconciliation counts, and extraction field accuracy, or regressions can pass CI.
- **MEDIUM — 04-02 Task 2 / 04-03 Task 1:** The chart leads with extraction F1, but the phase requirement says extraction field accuracy. Employee-set F1 alone can stay perfect while hours are wrong. Field accuracy should be first-class in summary and chart.
- **MEDIUM — 04-02 Task 2:** `_write_summary_json()` imports `app.config` to get `extraction_model_id`, which requires `DATABASE_URL`. That makes local eval require `DATABASE_URL=placeholder`, even though eval should be DB-free by default.
- **MEDIUM — 04-04 Task 1:** The DB write is said to derive from `summary.json`, but the action writes from in-memory `fixture_results`/`aggregated`. That breaks the "summary is authoritative" rule.
- **LOW — 04-03 Task 2:** The YAML verification uses `import yaml`, but PyYAML is not a declared dependency. Either add it as dev-only or verify with a simpler grep/parse strategy.
- **LOW — 04-04 Task 1:** The verification command masks failure with `|| echo`, so a broken `--db` implementation could appear acceptable.

## Suggestions

- **04-01 Task 1:** For D-05 caches, require a separate `*_extraction.json` generated by `--record`, with metadata showing model ID and recorded timestamp. Include at least one fixture whose cache deliberately diverges from expected (invented employee / hours) so F1 < 1.0 is demonstrable.
- **04-02 Task 2:** Implement two explicit inputs: `expected_extracted = Extracted.model_validate(...)` for isolated deterministic scoring (path A), and `cached_extracted` only for extraction scoring or optional end-to-end scoring (path B).
- **04-02 Task 2:** Reconciliation correctness should require `source`, `resolved`, and `matched_employee_id` to match expected. For unresolved cases, assert `matched_employee_id is None`.
- **04-02/04-03:** Report false-process as both count and rate over expected-clarify cases: `false_process / (false_process + true_clarify)`. Optionally also show precision-style `false_process / actual_process_total`, but do not make that the headline.
- **04-03 Task 1:** Fix the confusion-matrix cell highlight to `table[1, 2]`.
- **04-01 Task 1:** Add fixture validation that every non-null `expected_matched_employee_id` exists in the roster for that fixture's `from_addr`.
- **04-02 Task 2:** Use multiset/list alignment for extracted employees so duplicates count as false positives.
- **04-02/04-03:** Make extraction field accuracy visible in `summary.json`, `--check`, and `chart.svg`, not only employee-set F1.
- **04-02 Task 2:** Avoid importing `app.config` for `extraction_model_id` during normal eval. Read `EXTRACTION_MODEL` from env with a default, or catch settings failure and record the default model string.
- **04-04 Task 1:** If implemented, load `eval/summary.json` inside `_write_db_results()` and derive rows from that parsed object.

## Risk Assessment

**HIGH** until the extraction-cache and scoring issues are corrected. The plan has the right architecture, but as written it can produce a polished chart that overstates proof: hand-authored extraction caches hide LLM invention, deterministic scoring is not isolated, wrong-real name matches can pass, and the false-process headline can be mathematically misleading. Once those are fixed, the phase risk drops to **MEDIUM/LOW** because the DRY production-function seam and CI shape are otherwise solid.

---

## Consensus Summary

Single reviewer (Codex). Findings independently verified against the plan text and the codebase before acceptance:

### Verified-correct, accepted for fix
1. **Hand-authored extraction caches make F1 vacuously perfect** (HIGH) — the D-06 invention-guard tests nothing as written. Confirmed: 04-01 Task 1 says the stub "MATCHES what a correct extraction would return."
2. **Path-A feeds cache, not labeled expected** (HIGH) — confirmed at 04-02:204-210; contradicts D-07's "feed the labeled expected extraction" for isolated scoring.
3. **Reconciliation ignores `matched_employee_id`** (HIGH) — confirmed at 04-02:234-238; a wrong-but-real match passes, defeating D-02's stated purpose.
4. **Chart highlights `table[2,2]` (true-clarify, the SAFE cell)** (HIGH) — confirmed at 04-03:145-146; false-process is at `table[1,2]`. Verified against matplotlib 0-indexed-including-header table semantics.
5. **Wrong/malformed seed UUIDs in fixtures** (HIGH) — confirmed: plan writes `00000000-...-00000000001` (wrong prefix + 11-digit final group); real seed UUIDs are `e0000001-0000-0000-0000-000000000001` (verified in app/db/seed.py:80). No validation guards `expected_matched_employee_id`.
6. **Dict-keyed extraction collapses duplicate employees** (MEDIUM) — a duplicated pay line is a dangerous failure that should count as a false positive.
7. **`--check` compares only a metric subset** (MEDIUM) — gate-structure / decision / field-accuracy regressions could pass CI.
8. **Extraction *field* accuracy under-surfaced vs employee-set F1** (MEDIUM) — EVAL-04 specifies "extraction field accuracy"; F1 can be perfect while hours are wrong.
9. **Normal eval requires `DATABASE_URL=placeholder`** (MEDIUM) — `_write_summary_json` imports `app.config` for the model id; eval should be DB-free.
10. **DB write derives from in-memory, not `summary.json`** (MEDIUM) — confirmed at 04-04:95; violates "summary is authoritative."
11. **`|| echo` masks `--db` failure in verify** (LOW) — confirmed at 04-04:105.

### Accepted with modification
- **False-process denominator** (HIGH): the **count** is the unambiguous headline and stays loudest; add the risk-style rate `false_process / (false_process + true_clarify)` = false_process / expected_clarify_total as the primary rate, and keep (optionally) the precision-style rate clearly labeled — do NOT make precision-style the headline.

### Pushed back / down-scoped
- **PyYAML not declared** (LOW): rather than add a dep, the verify is switched to a dependency-free parse so the eval doesn't grow a dev dependency just for a CI-yaml smoke check.

All fixes applied directly to the plan files (concrete + surgical); see commit. The DRY seam, D-09 golden reuse, hermetic-CI shape, and scope tiering were confirmed sound and unchanged.
