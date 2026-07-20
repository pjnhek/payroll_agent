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

## Milestone: v4 — Durable Execution

**Shipped:** 2026-07-20
**Phases:** 6 (16–21) | **Plans:** 84 | **Timeline:** 7 days (2026-07-13 → 2026-07-20)

### What Was Built
- **Non-blocking webhook + durable queue** — the event loop stops blocking on the Resend fetch (`run_in_threadpool`), and a durable `jobs` table (SKIP-LOCKED claim, lease + double-fence, epoch-stable reclaim) drained by a 2-thread pool on the app's first FastAPI `lifespan`; INVARIANT J-1 (transport state ≠ business status) machine-enforced by an AST guard (QUEUE-01..05).
- **Recovery without a warm process** — an authenticated, fail-closed `/internal/pump` sharing the single `drain_once()` with the workers, on a 30-min cron folded into one `pump.yml` (PUMP-01/02); the piece that makes the queue durable *execution* on Render free.
- **Explicit failure policy + sweep deletion** — an `ok`/`retryable`/`terminal` result contract, backoff+jitter with an attempt cap that dead-letters, and the racing age-based `sweep_stranded_runs` DELETED (FAIL-01/02/03); all 8 `BackgroundTasks` producers cut over to durable INGEST (QUEUE-04).
- **At-most-once send** — reserved-`message_id` reuse as Resend `Idempotency-Key`, persisted-payload replay, and a row-locked (`FOR UPDATE`) provider-handoff authorization gated on `reply_epoch`; ambiguity escalates to operator review (SEND-01/02/03).
- **Four falsifiable durability proofs + ops view** — kill-mid-run, Svix redelivery, crash-between-accept-and-commit, expired-lease zombie fence, each with a mutation executed red and byte-identically reverted, registered in the `queueproof`/`proof` CI gate; `/ops` + `/health/queue` + `docs/DURABILITY-PROOFS.md` (PROOF-01..05, OPS-01); OPS-01 closed live 2/2.

### What Worked
- **Ordering the milestone by a non-negotiable dependency constraint.** The pump and failure policy MUST precede the webhook cutover, or the cutover ships a regression window where a worker records SUCCESS on a payroll that FAILED while the old sweep races the new queue. Making that an explicit roadmap constraint — not an emergent surprise — kept the money path safe through the cutover.
- **Proofs that ship red-first.** Every durability proof carried a demonstrated falsifying mutation (executed, observed red at a named assertion, byte-identically reverted) — the direct answer to v2's vacuous-concurrency-proof lesson.
- **A completeness gate against the CI blind spot.** PROOF-05 (`check_proof_inventory.py` + a `proof` marker + an AST-anchored `MUTATION_TARGETS` registry wired at the *selection* layer) closed the "a proof landed outside the hard-coded file list never runs" hazard flagged up front.
- **Live UAT against the deployed service, not localhost.** The UAT caught that the whole phase was 94 commits unpushed (CI green, prod 404ing) before it could poison the milestone claim.

### What Was Inefficient
- **CI-invisible live-DB contract drift accumulated across phases.** ~8 failures spanning three phases' settlement/ingest/delivery contract changes were invisible to the hermetic suite and only surfaced when the `queueproof` gate ran them together (13 failed/50 passed → 63 passed). Deferred live-DB proofs (16-04) also sat unclosed until a later phase. Root cause: worktrees have no `.env`/live DB, so DB-heavy proofs (and their mutations) silently defer.
- **A fixed, CI-green debug session sat at `awaiting_human_verify` for 4 days.** `jobs-kind-array-mismatch`'s schema-cast fix and its green concurrency-proof rerun were done, but the status flag was never flipped — surfacing as an "open" item at milestone close.
- **Nyquist VALIDATION.md maps went stale.** Phases 16/19/21's plan-time coverage maps were never refreshed post-execution (the underlying tests exist and pass per each VERIFICATION.md) — documentation staleness that reads as a coverage gap.

### Patterns Established
- **A durability proof is not done until it has been shown to fail.** Ship each with an executed mutation, the pasted red, and the named failing assertion — bound to a machine-checked registry so the doc can't drift from the code.
- **Wire coverage gates at the selection layer, not a hard-coded file list.** If CI picks tests by name, a correct new test that isn't named never runs; enforce membership with a marker + an inventory check that itself red-proofs.
- **Give each live-DB executor its own throwaway Postgres.** Worktrees without a DB silently defer every live proof AND its falsifying mutation; a per-executor DB closes the "deferred to CI" gap that never actually runs the mutation.
- **`git rev-list --count origin/master..master` BEFORE any UAT of a deployed phase.** Green CI on an unpushed branch is a live 404; verify the deploy reflects the branch first.
- **Publish the honest, narrower claim.** Exactly-once is impossible (Two Generals); the shipped claim is "at most one confirmation per approved run, per epoch," ambiguity escalated to a human, limitation documented — the same discipline as v3's eval-chart honesty fix.

### Key Lessons
1. **Durable *storage* is not durable *execution*.** On a platform that wakes only on inbound HTTP, a queue without an external pump is a table that never drains — the pump is load-bearing, not a nicety.
2. **A queue fixes the lost handoff, not the blocked event loop.** The audit found two independent defects; the queue *and* moving the blocking fetch off the request path were both required. Don't let one fix's success mask the untouched second defect.
3. **Transport state must never become a second business-status source of truth** — J-1 held only because it was machine-enforced (AST guard + drift test), not merely intended.
4. **The deploy-state trap is real and silent.** CI-green ≠ shipped; the milestone's biggest catch was an unpushed 94-commit branch found only by UATing the live URL.

### Cost Observations
- Model mix: predominantly Opus for planning/review/execution across the GSD orchestrator + executors; parallel-wave execution across 84 plans / 6 phases.
- Notable: red-first proofs and the live UAT were the highest-leverage spend — they caught the CI-invisible drift and the unpushed-branch trap that green hermetic tests could not.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Key Change |
|-----------|--------|------------|
| v1.0 | 7 | Vertical-MVP shape: thin foundation → walking skeleton as the FIRST end-to-end proof → deepening rings by risk. Deterministic decisioning (Phase 2.1) replaced the original 0.8-confidence gate. |
| v2 | 6 | Adversarial-audit-driven scoping (every phase = named finding); cross-AI review promoted from optional to a standing money-path gate; genuine-parallelism concurrency proof + fault injection as the "production-grade" evidence. |
| v3 | 4 | Codebase-quality milestone with zero money-behavior change, AST-diff-proven; god-file splits behind stable facades; full `mypy --strict` + comment-hygiene guards wired blocking into CI; 3 real defects surfaced by "hygiene" phases. |
| v4 | 6 | Durability milestone on a shipped pipeline; dependency-ordered phases (pump + failure policy MUST precede the webhook cutover); every proof ships red-first with a machine-checked mutation registry; live UAT against the deployed service caught an unpushed 94-commit branch. |

### Cumulative Quality

| Milestone | Tests (suite) | Notable |
|-----------|---------------|---------|
| v1.0 | 458 green | Full pipeline live on Render + Supabase + Resend; eval `false_process_count=0`. |
| v2 | 596 green | Atomicity + dedup proven via fault injection; concurrency invariants standing CI evidence; 0 regressions across all 6 phases. |
| v3 | 628 green | `mypy --strict` clean across 117 files; money literals AST-diff-identical to pre-milestone; 3 real defects found in "hygiene" phases (lying eval chart, path traversal, prompt-echo leak). |
| v4 | `queueproof` 73 green (real Postgres) + full hermetic suite green | Durability demonstrated *able to fail* (PROOF-01..04 mutations); `/ops` + `/health/queue` observability; at-most-once send; audit 19/19 reqs · 6/6 phases · OPS-01 live UAT 2/2. |

### Top Lessons (Verified Across Milestones)

1. **The deterministic decision core is the thesis; everything else is plumbing** — it held under v1.0's adversarial demo test and v2's money-path review. Keep money-moving judgment in pure, auditable code that never guesses.
2. **Green tests are necessary but not sufficient for money-safety** — value-level assertions + adversarial cross-AI review are what actually caught the mispay bugs (verified across Phase 7.5 and Phase 11), and red-first falsifying mutations are what made v4's durability proofs non-vacuous.
3. **Durable storage ≠ durable execution, and CI-green ≠ shipped** (v4) — an external pump is what actually drains a queue on a spin-down-happy free tier, and the biggest milestone catch was an unpushed branch found only by UATing the live URL. Prove the negative (red-first) and verify the deploy, every time.
