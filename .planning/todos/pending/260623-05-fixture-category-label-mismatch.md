---
id: 260623-05
created: 2026-06-23
source: Phase 05 UAT — multi-employee demo investigation
resolves_phase:
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
