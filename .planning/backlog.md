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
