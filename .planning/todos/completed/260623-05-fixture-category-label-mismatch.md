---
id: 260623-05
created: 2026-06-23
source: Phase 05 UAT — multi-employee demo investigation
resolves_phase: 15
priority: low
---

# Fixture 10 labeled `fixture_category: "exact"` but expects clarification

`eval/fixtures/10_multi_employee_coastal.json` has `fixture_category: "exact"`, but it
submits "Jame Okafor" (typo of roster "James Okafor") and its `expected.decision.final_action`
is correctly `request_clarification`. The label is cosmetically wrong.

**No eval impact:** run_eval.py scores against `expected.decision.final_action` (correct =
clarification), NOT the `fixture_category` string. So accuracy is computed correctly. The
mismatch only matters if the chart/report groups or labels fixtures by `fixture_category`.

Fix (low priority): relabel fixture 10's category to something accurate (e.g. "typo" or
"unknown_shorthand" / "clarify"), and double-check the eval chart's per-category grouping
still reads sensibly afterward. Verify no test asserts category=="exact" for this fixture.
Also a clean multi-employee PROCESS fixture (all names resolve) would let the demo show a
straight-through 2-employee approval if desired — currently the multi-employee demo always
goes through clarification (which is fine, and now completable via Simulate client reply).

## Resolution (Phase 15, plan 15-02)

**Relabeled** `eval/fixtures/10_multi_employee_coastal.json` → `"fixture_category": "typo"`
(per D-13 — matches the established taxonomy; fixture 05 already uses `"typo"`, and
"Jame Okafor" is a typo of roster "James Okafor").

**Pre-checked no coupling:** `grep -rn "10_multi\|multi_employee_coastal" tests/` returns
nothing — no test asserts `category == "exact"` for this fixture.

**Regenerated hermetically** from the committed extraction caches (no live LLM, no DB):
`uv run python eval/run_eval.py` → `--chart` → `--check` (exits 0). Fixture JSON,
`eval/summary.json`, and `eval/chart.svg` committed together so the push-time eval gate
never sees a half-applied state.

**Chart grouping is now honest** (this was the substantive part, not just cosmetics). The
todo assumed "no eval impact," and that is true of *accuracy* — but the per-category
grouping was actively misleading. Fixture 10's extraction cache carries a deliberate
phantom employee ("John Smith", see `eval/fixtures/DIVERGENCES.md`) to exercise the
precision metric, so its extraction F1 is 0.80. Under the wrong `"exact"` label that miss
was averaged into the **exact** bucket, dragging it to 0.96 — i.e. the chart showed the
exact-match category failing at extraction when nothing about exact matching had failed.
After the relabel:

| Bucket | Before | After |
|--------|--------|-------|
| `per_category_extraction.exact.f1` | 0.96 | **1.00** |
| `per_category_extraction.typo.f1` | 1.00 | **0.90** (n=2, absorbs fixture 10's phantom-employee precision miss) |
| `per_category_decision.exact` | 5/5 | **4/4** |
| `per_category_decision.typo` | 1/1 | **2/2** |

`per_category_reconciliation` is unchanged — it groups by per-NAME category, not by
`fixture_category`. Overall F1 (0.9889) and the confusion matrix (false_process = 0) are
unchanged, as expected: relabeling moves a fixture between buckets, it does not rescore it.

Full suite green (615 passed, 51 skipped).
