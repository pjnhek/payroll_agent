# Backlog

Ideas captured but not yet scheduled into a milestone phase. Promote via `/gsd-review-backlog`.

---

## Learn aliases from confirmed clarifications

**Captured:** 2026-06-21 (during Phase 2 live-gate tuning)
**Suggested home:** Phase 5 (Dashboard & Delivery) — fits the operator-confirmation flow.

**Idea:** When a `llm_nickname` (or low-confidence) match is gated to clarification and the
client/operator subsequently CONFIRMS that the submitted name does refer to a given employee,
**persist that submitted name as a `known_alias` on the employee** so the same nickname
resolves deterministically (Layer 1, confidence 1.0, no model call, no clarification) on every
future run. A real payroll system learns its clients' shorthand instead of re-asking weekly.

**Why deferred from Phase 2:** It's a new capability with design decisions that belong with the
Phase 5 operator gate, not the Phase 2 walking skeleton:
- **What counts as "confirmed"?** Auto-learn on any clarification reply (risky — the reply might
  correct the name, not confirm it), or only when the human operator approves the match at the
  Phase 5 gate (safer, human-in-the-loop — the natural fit).
- **Write-back path:** touches the resume/reply path + the `employees.known_aliases` persistence
  (currently aliases are seed-only). Needs a repo write + idempotency (don't double-add).
- **Eval impact:** alias-learning changes reconciliation behavior across runs; Phase 4's eval
  rides the same functions, so the learning must be reproducible/seedable for scoring.

**Acceptance sketch (for whoever plans it):** an operator-approved nickname match writes the
submitted name into the matched employee's `known_aliases`; a subsequent run with the same
nickname resolves at Layer 1 (deterministic, confidence 1.0) with no clarification.

**Related:** the confidence-rubric change (Phase 2, 2026-06-21) that makes `llm_nickname` gate
at 0.75 is what makes this valuable — without learning, every nickname re-asks forever.
*(Superseded note: 2.1 removed the confidence rubric entirely — the alias-learning value now
rests on the deterministic `source="none"` clarify path instead, but the idea is unchanged.)*

---

## Atomic status claim — close the resume/approve race (Phase 5 idempotency)

**Captured:** 2026-06-22 (Codex review round 3 of Phase 2.1 — independently rediscovered the
known CR-02 residual).
**Suggested home:** **Phase 5 (Dashboard & Delivery)** — it is already scoped here via
**FOUND-04** (`SELECT ... FOR UPDATE` against double-approval), **CLAR-04** (idempotent sends),
and **INGEST-05** (idempotent re-trigger). This is the implementation detail of those three.

**Problem (HIGH, found 3× now — overnight code-review CR-02, then Codex 2.1 round 3):** the
run status guards are **load-then-set, not atomic**. In `app/pipeline/orchestrator.py`
`resume_pipeline`, two distinct clarification replies can BOTH read `status == awaiting_reply`,
BOTH set `EXTRACTING`, and BOTH run stages / send / replace line items → double-resume. The
operator approve/reject path (`app/main.py`) has the same race → double-pay / double-send. The
initial run claim is similarly unguarded. The in-code comment in `resume_pipeline` already
documents this as the accepted Phase-2 minimum, deferred here.

**Fix:** an atomic claim helper in `app/db/repo.py` —
`UPDATE payroll_runs SET status = %s WHERE id = %s AND status = %s RETURNING id` (claim succeeds
only if the row was still in the expected status), or `SELECT ... FOR UPDATE` inside the
transaction. Use it for **(a)** resume (claim `awaiting_reply → extracting`), **(b)** approve/reject
(claim the pending status), and **(c)** the initial run claim. A losing concurrent caller gets no
row back and drops cleanly (logs a late/duplicate, does not re-run). This is exactly the
FOUND-04 `FOR UPDATE` guard Phase 5 already promises.

**Why not in 2.1:** 2.1 was a decisioning re-architecture; this is concurrency/idempotency work
that belongs with the Phase 5 operator gate (where approve/reject and re-trigger are built), so
the claim helper is written once and used across all three paths. Pulling it into 2.1 would have
been scope creep into Phase 5. The current Phase-2 status-precondition removes the WIDE window;
the atomic close is the Phase 5 deliverable.

**Acceptance sketch (for whoever plans Phase 5):** two concurrent approvals of the same run
result in exactly ONE `approved → sent → reconciled` advance and ONE outbound send; two
concurrent clarification replies resume the run exactly once; a re-triggered errored run cannot
double-process. Tested with a concurrency/locking test against the live (or a transactional) DB.
