**1. SCOPE GAPS**

1. **FOUND-06 / CALC-09**: Define employee calc inputs explicitly: pay frequency/pay periods, wage type/rate/salary, W-4 filing status, Step-2 checkbox, any assumed Step 3/4 values, and static YTD Social Security wages. Without this, `CALC-04/05` cannot be tested honestly.

2. **LLM-09**: Enforce one-to-one roster mapping after reconciliation. Duplicate submitted names, two names mapping to the same employee, or non-roster IDs must gate to clarification.

3. **DEMO-01**: Commit canonical demo fixtures for the 60-90s demo: one clean happy path and one code-gated clarify path, both replayable from `DASH-05`.

4. **EMAIL-01**: Stub gateway must record outbound clarification/confirmation messages with synthetic Message-IDs and allow fixture reply injection. Otherwise the clarify/resume demo depends too much on the final real provider wiring.

**2. OVER-SCOPED**

1. **EVAL-01**: A synthetic fixture generator should not be required for v1. Hand-curated committed fixtures are faster, more credible, and enough for the chart. Defer generator code to v2.

2. **EVAL-04**: LLM-as-judge email-quality scoring is weak signal for the core thesis. Keep extraction, name reconciliation, and decision accuracy in v1; move email-quality judging to v2 unless time remains.

3. **EVAL-05**: Live eval in GitHub Actions on every push is risky for a two-week demo because of secrets, provider flakiness, and cost. Keep local eval plus persisted dashboard results; make CI eval manual or cached-output only.

4. **LLM-03**: “Any 401k change” is a scope trap unless semantics are specified. Either cut it from v1 or define it as current-run-only. Do not mutate employee defaults in v1.

**3. MIS-CLASSIFIED**

1. **CALC-V2-02** is correctly v2 as a full YTD ledger, but v1 still needs a static YTD wage input to support the Social Security wage-base cap claim.

2. The **fixture generator** and **LLM-as-judge email-quality metric** belong in v2. The v1 requirement should be the committed fixture corpus plus the core three metrics.

3. State withholding, spreadsheet parsing, dashboard auth, CRUD UI, LangGraph, and client-side confirmation are correctly deferred or out of scope.

**4. RISK / SEQUENCING**

1. **CALC-08 is not a correctness oracle.** Reconciliation only catches arithmetic drift, not stale tax tables or wrong Pub 15-T logic. `CALC-06` golden tests must land before dashboard/eval trust the math.

2. **LLM-07 must be the only branch source.** Orchestrator, dashboard, and eval must use code-owned `final_action`, never `model_action`. Otherwise the “LLM proposes, code gates” story is fake.

3. **EVAL-03 depends on the DRY seam.** If judgment functions accept `run_id` or mutate DB state, the eval will diverge from production. Contracts and pure functions must precede persistence wiring.

4. **CLAR-01 / HITL-02 need outbound idempotency.** Retrying approval or re-triggering an errored run must not send duplicate clarification or confirmation emails.

5. The requirements say **44 v1 requirements**, but the file contains **46**. Fix the count before roadmap traceability is locked.

**5. Bottom Line**

The v1 scope is close, but I would not lock it as-is. Add the missing calc-input/YTD and one-to-one reconciliation requirements, add canonical replayable demo fixtures with a stub gateway, and cut the eval generator/live-CI/email-judge pieces from required v1. After that, the scope is coherent for a recruiter-facing two-week build.
