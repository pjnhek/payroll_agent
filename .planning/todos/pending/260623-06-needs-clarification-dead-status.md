---
id: 260623-06
created: 2026-06-23
source: Phase 05 REVIEW-2 (WR-03)
resolves_phase:
priority: low
---

# RunStatus.NEEDS_CLARIFICATION is declared but never written (dead UI status)

`NEEDS_CLARIFICATION` exists in `app/models/status.py` and the `schema.sql` status CHECK,
but `_clarify()` goes straight to `AWAITING_REPLY` — nothing ever writes NEEDS_CLARIFICATION.
A run somehow in that status (legacy data / manual write) has no badge class, no operator
controls, no retrigger — an invisible dashboard dead-end.

Deferred (not fixed mid-phase) because touching the status enum/schema risks the schema-drift
CI guard (test_status_drift), and this is a pre-existing latent state, not introduced by Phase 5.

Fix (pick one):
- Remove NEEDS_CLARIFICATION from the enum + schema CHECK (tightest — the drift test will
  confirm code/DB agree). Verify nothing references it first.
- OR add it to _BADGE_CLASS / _BADGE_LABEL maps + the retrigger eligibility list so it renders
  and is recoverable if it ever occurs.
