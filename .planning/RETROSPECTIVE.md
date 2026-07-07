# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v2 — Production Hardening

**Shipped:** 2026-07-07
**Phases:** 6 (7, 7.5, 8, 9, 10, 11) | **Plans:** 26 | **Timeline:** 11 days (2026-06-27 → 2026-07-07)

### What Was Built
- **Money-correctness deepening** — zero-hours $0-paystub gate (MONEY-01), Unicode-NFC name normalization (MONEY-02), and the field-regression clarification state machine that carries the original value forward or honors an explicit removal (MONEY-03, on a `_run_stages` split refactor).
- **Atomic, concurrency-correct data layer** — every multi-write op in one transaction (DATA-01), a transactional webhook-dedup path that survives parallel Resend retries (DATA-02), stuck-run recovery (DATA-03), PII-safe `error_detail` + hot-path indexes (OPS2-01/02), and a real-Postgres N-thread concurrency proof wired into CI (OPS2-03).
- **Clarification round machine & reachable alias learning** — round-aware clarify idempotency + a 3-round `needs_operator` cap, multi-round context accumulation behind a code-owned "questions we asked" anchor, and an alias-learning write side that finally fires (bind-on-confirmation with same-record evidence) so the system provably stops re-asking (CLAR2-01…07).

### What Worked
- **Adversarial-audit-driven scope.** Every phase traced to a concrete finding with file:line from `v2-hardening-audit.md`. No vague "make it better" phases — each closed a named defect, which made verification objective.
- **Risk-ordering the phases.** Cheap pure-function fixes (7) and a clean schema baseline (8) landed before the highest-risk transaction surgery (9), which was then *proven* by a dedicated capstone (10). The atomicity work built on a clean, diagnosable foundation instead of racing it.
- **Cross-AI review as a standing gate.** External review (Codex) + internal argument-tracing caught real money/security bugs at every money-touching phase — 2 mispay bugs in 7.5, 5 confirmed critical bugs in an *already-VERIFIED-passing* Phase 11. This was the single highest-leverage practice of the milestone.
- **Fault injection against real Postgres.** The atomicity and concurrency claims were proven by forcing exceptions mid-sequence and racing real OS threads, not by asserting against mocks.

### What Was Inefficient
- **"Green tests" gave false confidence repeatedly.** Hermetic suites that mock the LLM passed while real money bugs sat in the merged source. Phase 7.5 and Phase 11 both reached "complete/VERIFIED" and *then* review found overpay/underpay/misroute defects. The verification gate had to be re-run after review, every time.
- **The concurrency proof was initially vacuous.** Phase 10's first cut fired 8 threads at an `async` webhook route whose DB body had no `await`, so a shared TestClient serialized them — the ON CONFLICT race never triggered and the test passed even with the clause deleted. A whole gap-closure plan (10-02) was needed to make the proof genuine (race the sync DB seam under a `threading.Barrier`).
- **Fixing a classify *label* is not fixing the *paid value*.** Multiple review rounds hit the same spot: the label was corrected but the paystub still paid from the wrong source. Asserting the line-item value (not the intermediate classification) would have caught these one round earlier.

### Patterns Established
- **Verification is not terminal until cross-AI review + a confirming round run against merged source.** In-house checkers missed bugs that argument-tracing and an external reviewer caught. "Passed" now means "passed, then survived an adversarial refutation pass traced to live source."
- **Money-path plan verification TRACES argument flow vs live source**, not prose. Assert the paid line-item value and trace it back to `_compute_line_items`; don't trust that a corrected decision label implies a corrected payment.
- **Concurrency tests must exercise genuine parallelism** — drive the sync repo seam directly from N threads with a `threading.Barrier`, mind the connection-pool `max_size`, and confirm the test *fails* with the guard removed before trusting a pass.
- **Never learn an alias from a corrected misname.** Only bind a token that matches the resolved name, on human-stated confirmation evidence — the never-learn-from-inference intent is load-bearing against silent misroute.
- **Schema strictly before code at the live-DB checkpoint.** Every phase touching the schema applied + human-verified the Supabase migration at a blocking checkpoint before the code that depends on it.

### Key Lessons
1. **Green hermetic tests that mock the LLM cannot prove money-safety.** They prove the plumbing; the money-correctness must be proven by value-level assertions on the paystub and by adversarial review of the merged source.
2. **A concurrency test that passes with the invariant removed is worthless.** Prove the negative (it fails without the guard) before trusting the positive.
3. **When reviews keep hitting one spot, the design is the bug, not the test.** The repeated classify-label-vs-paid-value findings in 7.5 pointed at a seam that needed the three-phase detect→backfill→calc ordering, not another patch.
4. **"VERIFIED passing" is a checkpoint, not a finish line** — schedule the external review pass *as part of* done, not after.

### Cost Observations
- Model mix: predominantly Opus for planning/review/execution (GSD orchestrator + executors).
- Notable: the cross-AI review loops were the most cost-effective spend of the milestone — each round that "wasted" tokens re-reviewing a passing phase found real money/security bugs that would have shipped otherwise.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Key Change |
|-----------|--------|------------|
| v1.0 | 7 | Vertical-MVP shape: thin foundation → walking skeleton as the FIRST end-to-end proof → deepening rings by risk. Deterministic decisioning (Phase 2.1) replaced the original 0.8-confidence gate. |
| v2 | 6 | Adversarial-audit-driven scoping (every phase = named finding); cross-AI review promoted from optional to a standing money-path gate; genuine-parallelism concurrency proof + fault injection as the "production-grade" evidence. |

### Cumulative Quality

| Milestone | Tests (suite) | Notable |
|-----------|---------------|---------|
| v1.0 | 458 green | Full pipeline live on Render + Supabase + Resend; eval `false_process_count=0`. |
| v2 | 596 green | Atomicity + dedup proven via fault injection; concurrency invariants standing CI evidence; 0 regressions across all 6 phases. |

### Top Lessons (Verified Across Milestones)

1. **The deterministic decision core is the thesis; everything else is plumbing** — it held under v1.0's adversarial demo test and v2's money-path review. Keep money-moving judgment in pure, auditable code that never guesses.
2. **Green tests are necessary but not sufficient for money-safety** — value-level assertions + adversarial cross-AI review are what actually caught the mispay bugs (verified across Phase 7.5 and Phase 11).
