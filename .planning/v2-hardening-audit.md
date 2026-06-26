# v2 "Production Hardening" — Discovery Audit Findings

**Generated:** 2026-06-26 (two parallel adversarial read-only sweeps: correctness + data-layer)
**Purpose:** Concrete evidence base for the v2 milestone. v1.0 shipped a working MVP; v2 makes
the **core logic + data layer genuinely production-grade** — correct under real, messy, concurrent
load, not just the demo path. Scope is backend/logic only (cosmetic items like custom email domain,
chart restyle deliberately excluded — they don't matter for a personal project).

Findings are cross-checked against existing project decisions; the audit's over-flags (intentional
decisions, already-mitigated, false alarms) are demoted to "out of scope" below.

---

## Recommended shape: 3 rings

### Ring 1 — Money-correctness (deepens the core thesis: "never silently pays wrong")

- **[HIGH] Zero-hours silent $0 payment.** `validate.py` `any_hours` uses `is not None`, so an
  hourly employee with `hours_regular=Decimal("0")` (and nothing else) PASSES the gate → calc
  produces $0 gross → ships a $0 paystub with no clarification. The reconciliation backstop can't
  catch it ($0 is arithmetically self-consistent). Fix: treat explicit 0 like missing for hourly
  (`is not None and != 0`) so it gates to clarification. *Confirm first whether the extraction LLM
  ever emits Decimal("0") — the prompt says use null — but defend regardless.*
- **[MED, on-thesis] Unicode name normalization.** `reconcile_names._norm` does casefold +
  whitespace only, not NFC. "José" (NFC) won't resolve "José" (NFD) → silent fail-to-resolve.
  Fix: `unicodedata.normalize("NFC", name)` before casefold (~3 lines).
- **[from v1 backlog] Field-regression clarification** ("did you forget the OT?"). A reply that
  drops a money field the original stated → silent under/over-pay. Already scoped in backlog.md;
  complements the zero-hours fix. Watch the clarify-loop guard (clarify once, then carry-forward).

### Ring 2 — Data integrity (the concurrency/atomicity story — senior-engineer signal)

- **[HIGH] Multi-write operations not atomic.** `orchestrator._run_stages` (persist_extracted +
  persist_decision + persist_reconciliation + replace_line_items + status writes) and `_deliver`
  (outbound email row + alias write + SENT + RECONCILED) are SEPARATE auto-commits. A crash
  mid-sequence leaves half-written state (paystubs replaced but status stale; email sent but status
  never advances → run stuck in APPROVED). Fix: wrap each multi-write sequence in ONE
  `with conn.transaction():`.
- **[HIGH] Webhook dedup race.** Resend WILL redeliver; two concurrent duplicates can both pass the
  read-only idempotency check and race to `create_run` → duplicate runs for one email. Fix: make
  dedup + run-existence check transactional (only the webhook that actually INSERTED the email row
  creates the run; the loser checks for an existing run for that source_email_id). NOTE: the audit's
  own fix sketch had a subtle gap — design the CAS carefully.
- **[MED] Stuck-run recovery.** If a background task dies, a run is stranded in `extracting`/
  `computing` forever; retrigger's stale threshold is 5 min (too long). Fix: a recovery sweep or a
  shorter/force-retrigger path for orphaned in-flight runs.

### Ring 3 — Operability + evidence (backs the "production-grade" claim)

- **[HIGH] Enrich `error_reason`.** Stores only `type(exc).__name__` ("ValueError") — no message,
  no context. Felt directly during v1 live debugging (the webhook 500). Fix: add a PII-safe
  `error_detail` (sanitized `str(exc)[:200]`) so prod failures are diagnosable without log access.
- **[MED] Missing indexes** on hot paths (`businesses.contact_email`, `email_messages(run_id,
  direction, send_state)`, `payroll_runs(created_at DESC)`, `payroll_runs(status)`). Cheap; needed
  for any load claim.
- **[MED] `SELECT *` in `load_all_runs`** (repo.py:1003) — violates the project's OWN stated
  explicit-column discipline; schema creep could leak columns to the dashboard. Trivial fix.
- **[NEW — proposed deliverable] Load/concurrency proof.** A test that fires N concurrent runs /
  duplicate webhooks / simultaneous approvals and ASSERTS no double-approval, no lost update, no
  duplicate run, no half-write. This is the evidence the "production-grade" claim needs.

---

## Out of scope for v2 (audit over-flags — demoted with reason)

- **Additional Medicare 0.9% surtax** — flagged HIGH, but it's an INTENTIONAL, documented decision
  (never triggers at demo wages; disclaimed in README/PDF). Modeling it is a tax-completeness
  *feature*, not hardening. Leave disclaimed unless tax-completeness becomes a goal.
- **SS wage-base straddle proxy** — documented accepted limitation of the static-seed model
  (no per-employee YTD Medicare ledger). Schema-level feature, not a v2 hardening item.
- **`or Decimal("0")` rate default** — audit admitted it's already mitigated by Employee model
  validation. Low value; optionally tighten to an explicit raise.
- **NOT NULL on email columns / `created_at` on upsert / circular-FK trigger** — minor defensive
  or audit-trail nits. Optional cleanup, not headline.
- **MED-4 resume/approve race** — the data-layer agent self-corrected: a run is AWAITING_REPLY xor
  AWAITING_APPROVAL, so the race doesn't occur. False alarm; just document the state invariant.

---

## Source

Two read-only Explore agents (2026-06-26): correctness sweep (pipeline + tax math) and data-layer
sweep (repo/schema/concurrency). Full findings preserved in session transcript. Every Tier-1/2 item
above has an exact file:line in the original agent outputs.
