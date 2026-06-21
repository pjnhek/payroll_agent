# Claude (build-plan author) scope review — REQUIREMENTS.md v1

Reviewer context: the Claude conversation that authored the original `payroll-agent-build-plan.md`, holding the deepest context on intent. Reviewed the post-Codex 51-requirement v1 scope.

**Verdict:** Sound to lock after three changes (one goes to core value). Independently verified CALC-04's 2026 SS wage base = $184,500 against SSA (employee SS tax cap $11,439/yr).

## Findings applied

1. **DASH-02 (core value, accepted in full).** The original wording compared "submitted data" against computed paystubs. If "submitted data" = `extracted_data`, the operator compares the LLM's reading against a calc built on that same reading — both agree by construction, so an extraction error (40→44, dropped employee) passes the human gate invisibly. Fix: the **raw cleaned inbound email body** (INGEST-02) is now the mandatory leftmost column in run detail; also surfaced in the eval drill-down (DASH-04). The gate now verifies the LLM's *reading*, not just arithmetic.

2. **EVAL-01 (Codex override reversed, accepted).** For a ~20-fixture corpus, hand-curated fixtures are faster, more realistic, and kill the train/test-leakage critique. The "scales to thousands" narrative isn't realized at 20 fixtures, and the prior wording paid for both a generator and hand-labeling. v1 now: a throwaway **bootstrap drafting helper** + hand-curated committed fixtures (EVAL-02). Full decoupled-persona generator → v2 (EVAL-V2-02).

3. **INGEST-05 (descoped, accepted).** "Resume from last persisted status" across 11 statuses requires every stage to be re-runnable from its predecessor's exact state — more than the demo needs ("nothing silently hangs"). v1 now: errored runs show `error` and re-trigger idempotently **from the start**. Full mid-pipeline resume → v2 (INGEST-V2-02).

4. **EVAL-04 (rubric added, kept).** An unrubric'd LLM-judge is a vanity number. Now scored against a one-line rubric + 2–3 calibration anchors; the three core metrics stay front-and-center, the judge score is secondary.

5. **Additional Medicare 0.9% over $200k YTD** — not modeled (never triggers weekly); disclaimed in README alongside OBBBA (CALC-04, OPS-04).

## Carried to the roadmapper as sequencing constraints

- **Front-load CALC-05/06.** The Pub 15-T calc engine (Worksheet 1A, three filing statuses, Step-2 branch, Decimal-exact golden tests) is the single biggest rock. Golden tests must land before the dashboard or eval trust the math, because CALC-08 reconciliation only catches arithmetic drift, not a stale table or wrong Pub 15-T logic.
- **Designated drop-if-tight items:** EVAL-04 (LLM-judge metric) and INGEST-05 (error recovery). Honest timeline read at part-time: closer to 2.5–3 weeks than 2.
- The DRY seam (LLM-07 `final_action` as sole branch source; gates inside `decide.py`; eval imports the same functions) is the load-bearing invariant — protect it.
