# Extraction Cache Divergences

These committed caches deliberately diverge from their fixture's `expected.extracted` so the extraction metric (D-06) is exercised and the committed `summary.json` shows F1/field_accuracy < 1.0. All other caches mirror their fixture's expected block exactly.

| Fixture | Divergence Type | Why |
|---------|-----------------|-----|
| `10_multi_employee_coastal_extraction.json` | PRECISION miss (phantom employee) | Cache adds "John Smith" with 32 regular hours — a name not in `expected.extracted`. This produces `false_positives > 0`, exercising the precision side of D-06 and proving the metric can catch hallucinated employees that `validate.py` cannot (any_hours=True passes the deterministic gate). |
| `08_vague_hours_coastal_extraction.json` | FIELD_ACCURACY miss (wrong hours value) | Cache reports `hours_regular = "40"` for Maria Chen, but `expected.extracted` has `hours_regular = null` (vague body — extractor should return null). Same employee name, wrong field value — exercises the field_accuracy branch of D-06. |

After `--record` regenerates these caches with live extractor output, the real model's behavior replaces these placeholders and the metric measures actual extraction quality.
