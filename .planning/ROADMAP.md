# Roadmap: Payroll Agent

## Milestones

- ✅ **v1.0 — MVP** (shipped 2026-06-25) — Email-driven payroll agent: messy email in, correct human-approved payroll out, every money-moving decision code-gated (deterministic, auditable, never guesses). 7 phases, deployed live on a free stack with a recorded demo. → [full archive](milestones/v1.0-ROADMAP.md) · [requirements](milestones/v1.0-REQUIREMENTS.md)

## Active Milestone: v2 — Production Hardening

**Goal:** Take the working v1.0 MVP and make its core money-logic and data layer genuinely production-grade — correct under real, messy, concurrent load, not just the demo path. Backend/logic only; scope was discovered via an adversarial audit (`v2-hardening-audit.md`), and every phase below closes concrete findings with file:line.

**Shape:** A focused, risk-ordered hardening pass on a shipped, deployed codebase — vertical slices, each phase independently shippable, "thin then deepen." Three audit rings (money-correctness → data-integrity → operability+evidence) split into four phases so the highest-risk work (the atomic transaction model + the dedup CAS race) lands as its own coherent, atomically-shippable unit, on top of a clean schema/diagnostics baseline, and is then *proven* by a concurrency capstone. Tech stack unchanged (FastAPI, psycopg3, Supabase Postgres, Pydantic v2, uv, pytest); TDD discipline throughout (failing test first for every fix).

### Phases

**Phase Numbering:** v2 continues the global phase sequence from v1.0 (last phase: 6). Integer phases (7, 8, 9, 10) are planned milestone work; decimal phases (e.g. 9.1) are reserved for urgent insertions.

- [ ] **Phase 7: Money-Correctness Deepening (Pure-Function Gates)** - Close the two pure-function silent-mispay gaps: zero-hours $0 paystub and Unicode (NFC) name normalization — the engine never silently pays wrong on these messy-input paths. *(Scope reduced 2026-06-27: MONEY-03 field-regression moved to Phase 7.5 after three cross-AI review rounds showed it requires a `_run_stages` split refactor as its foundation — see 07-REVIEWS.md.)*
- [ ] **Phase 7.5: Clarification-Reply Field-Regression (MONEY-03)** - The clarification-reply field-regression state machine, built on a foundational `_run_stages` split refactor so carry-forward can land between reconcile and validate — detect a dropped money field, clarify once, carry forward (or honor an explicit removal) without an infinite loop
- [ ] **Phase 8: Data-Layer Hygiene & Diagnostics** - Restore schema-hygiene discipline (hot-path indexes, explicit column lists) and make production failures diagnosable from the DB (PII-safe `error_detail`) — the clean baseline the atomicity work builds on
- [ ] **Phase 9: Atomic Data Integrity** - The senior-engineer ring: atomic multi-write pipeline transactions (no half-written runs on crash), a transactional webhook-dedup CAS (Resend redelivery never duplicates a run), and a stuck-run recovery path for orphaned in-flight runs
- [ ] **Phase 10: Concurrency Proof** - The evidence capstone: a test fires N simultaneous runs / duplicate webhooks / concurrent approvals and asserts the invariants hold — no double-approval, lost update, duplicate run, or half-write — backing the production-grade claim

## Phase Details

### Phase 7: Money-Correctness Deepening (Pure-Function Gates)

**Goal**: The core thesis — "never silently pays wrong" — holds against two messy-input paths in the pure-function judgment layer: an explicit-zero-hours submission and a Unicode-form mismatch on a roster name. *(Scope reduced 2026-06-27: MONEY-03 field-regression moved to Phase 7.5 — three cross-AI review rounds, 07-REVIEWS.md, showed its resume state machine needs a `_run_stages` split refactor as a foundation, distinct from these two self-contained pure-function fixes.)*
**Mode:** standard (brownfield correctness fixes on shipped pure-function modules)
**Depends on**: Nothing (independent of the data-layer phases; first v2 phase by risk-ordering — lowest blast radius, deepens the headline claim)
**Requirements**: MONEY-01, MONEY-02
**Closes audit findings**: HIGH-01 (zero-hours silent $0, `validate.py` `any_hours`), MED-01 (Unicode NFC, `reconcile_names._norm`)
**Success Criteria** (what must be TRUE):

  1. An hourly employee submitted with explicitly-zero hours (`hours_regular=0`, no other hours) gates to `request_clarification` instead of producing a $0 paystub — the validation `any_hours` check treats explicit `0` as missing for hourly, and a failing test proves the old `is not None` path no longer ships a $0 stub (the reconciliation backstop can't catch $0, so this gate is the only defense).
  2. Two visually-identical names in different Unicode normalization forms (e.g. "José" NFC vs the NFD decomposition) resolve as a match — `reconcile_names._norm` applies `unicodedata.normalize("NFC", …)` before casefold — with a test asserting the previously-failing NFD case now resolves to the same employee.

**Plans**: 2 plans
Plans:
**Wave 1**

- [x] 07-01-PLAN.md — Contracts widening (ValidationIssue Literal + FieldDrop model as forward-compat scaffolding for Phase 7.5) + RED failing tests for MONEY-01 and MONEY-02 *(RawFieldDrop and all MONEY-03 tests belong to Phase 7.5; this plan is strictly MONEY-01/02 RED scaffolding)*

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 07-02-PLAN.md — MONEY-01 `_is_paid` predicate + `any_hours` fix; MONEY-02 NFC `_norm` + eval `_normalize` parity

### Phase 7.5: Clarification-Reply Field-Regression (MONEY-03)

**Goal**: A clarification reply that drops a money-affecting field the original submission stated (original "40 + 2 OT", reply "40" with no OT) is detected as a regression, clarifies exactly once, then carries the original value forward — or honors an explicit removal — and never enters an infinite re-clarify loop. **This phase is built on a foundational refactor first**: `_run_stages` is split so the carry-forward backfill lands *between* reconcile and validate/decide/calc, which three cross-AI review rounds proved is the only correct seam (see 07-REVIEWS.md rounds 1–3).
**Mode:** standard (a structural refactor of shipped orchestration code, then the field-regression state machine layered on top)
**Depends on**: Phase 7 (reuses the `_is_paid` predicate, the `field_regression` ValidationIssue Literal, and the FieldDrop model that Phase 7 lands as scaffolding). Independent of Phases 8–10.
**Requirements**: MONEY-03
**Closes audit findings**: v1-backlog field-regression clarification
**Foundational refactor (Plan A, MUST land + be regression-tested BEFORE the feature)**:
  - Split `_run_stages` into `(a) extract + reconcile` and `(b) validate + decide + persist + branch`, returning a structured result, so an optional carry-forward backfill can run *between* (a) and (b). The existing `run_pipeline` and `resume_pipeline` callers are updated and their behavior is pinned by regression tests BEFORE any field-regression logic is added. This directly resolves 07-REVIEWS round-3 R3-1 (post-return backfill is too late because `_run_stages` already persisted + branched).
**Success Criteria** (what must be TRUE):

  1. **Foundation:** `_run_stages` is split so a carry-forward backfill can be injected between reconcile and validate/decide/calc; both `run_pipeline` and `resume_pipeline` behave identically to today on all non-regression paths, proven by the existing orchestrator/clarify/persistence test suites staying green.
  2. A clarification reply that drops a money field (original "40 + 2 OT", reply "40" with no OT) is detected as a regression and clarifies once ("did you forget the overtime?") before processing; the diff is keyed by the SAME `employee_id` resolved in BOTH the pre-clarify snapshot and the reply (a restated name resolving to the same employee is still diffed; a re-resolution to a different employee is skipped) — proven by tests including a restated-name case.
  3. If the regression is still unaddressed after that one clarification round, the original value is **carried forward into the computed paystub** (backfill lands before calc, not after); if the reply explicitly zeroes the field ("remove it"), that is honored as `confirmed_dropped` with NO carry-forward — proven by a test that distinguishes silence from an explicit zero, and a loop-guard test proving the clarification fires exactly once with no infinite re-clarify.
  4. A run with a MIXED clarification (a field-regression issue AND a normal missing-field/unresolved-name in the same reply) still durably records the field-regression `asked` state and still asks the field-regression question in the email — proven by a mixed-issue test (resolves 07-REVIEWS round-3 R3-2).

**Plans**: TBD *(start the foundational split-refactor plan FIRST, then layer detection → state machine → eval/integration; carry forward the verified design from 07-CONTEXT.md decisions D-08..D-30 and the 07-REVIEWS.md round-1/2/3 findings)*

### Phase 8: Data-Layer Hygiene & Diagnostics

**Goal**: Restore the project's own stated schema-hygiene discipline and make production failures diagnosable from the dashboard/DB without log access — landing as a clean, low-risk baseline *before* the high-skill transaction surgery in Phase 9 (the atomicity work reads/writes these same hot paths and benefits from the richer error detail while it's being built).
**Mode:** standard (cheap, additive data-layer fixes — indexes, column list, one nullable column)
**Depends on**: Nothing structurally; sequenced after Phase 7 and before Phase 9 by risk-ordering (cheap baseline first, so the atomic-transaction phase builds on a clean schema and has real error visibility)
**Requirements**: OPS2-01, OPS2-02
**Closes audit findings**: HIGH-05 (`error_reason` stores only `type(exc).__name__` — enrich with PII-safe `error_detail`), MED data-layer (missing hot-path indexes), MED `SELECT *` in `load_all_runs` (repo.py:1003)
**Success Criteria** (what must be TRUE):

  1. A failed run records a PII-safe `error_detail` (sanitized `str(exc)[:200]` + context, not just the exception type), surfaced on the dashboard/DB so a production failure (e.g. the v1 webhook 500) is diagnosable without log access — proven by a test asserting the stored detail contains the message and excludes PII.
  2. The hot query paths have supporting indexes — `businesses.contact_email`, `email_messages(run_id, direction, send_state)`, `payroll_runs(created_at DESC)`, `payroll_runs(status)` — applied via `schema.sql` and verified present after bootstrap; the status-drift / schema guard stays green.
  3. `load_all_runs` selects an explicit column list (no `SELECT *`), so schema creep cannot silently leak new columns to the dashboard — restoring the project's stated explicit-column discipline, with a test asserting the query names its columns.

**Plans**: TBD
**UI hint**: yes

### Phase 9: Atomic Data Integrity

**Goal**: The data layer becomes correct under concurrency and crashes — the senior-engineer signal of the milestone. Every multi-write pipeline operation commits atomically, duplicate webhook deliveries can never create a second run even when raced, and a background task that dies mid-flight leaves a *recoverable* run rather than a permanently-stranded one.
**Mode:** standard (highest-skill, highest-risk phase — touches the transaction model and the webhook→create_run path the whole pipeline depends on)
**Depends on**: Phase 8 (builds on the clean schema baseline + richer `error_detail`; the dedup CAS and recovery paths are easier to diagnose with Phase 8's diagnostics in place). Independent of Phase 7.
**Requirements**: DATA-01, DATA-02, DATA-03
**Closes audit findings**: HIGH-03 (`orchestrator._run_stages` + `_deliver` are separate auto-commits → half-written state on crash), HIGH-04 (webhook dedup race in `main.py` + `repo.insert_inbound_email` → duplicate runs), MED-05 (stuck-run recovery; current 5-min stale threshold too long)
**Success Criteria** (what must be TRUE):

  1. The persist+branch+status sequence in `_run_stages` and the send+alias+status sequence in `_deliver` each commit in a single `with conn.transaction():` — a crash injected mid-sequence (test forces an exception between writes) leaves the run wholly un-advanced, never half-written (no paystubs-replaced-but-status-stale, no email-sent-but-status-stuck-in-`approved`).
  2. Two concurrent duplicate webhook deliveries for the same inbound `message_id` (Resend retry) result in exactly one payroll run — dedup and run-creation are resolved in one transaction so only the webhook that actually INSERTed the email row creates the run, and the loser attaches to the existing run; a test races two inserts and asserts a single run exists (the CAS is designed carefully — the audit's own fix sketch had a subtle gap).
  3. A run whose background task died mid-flight (stranded in `extracting`/`computing`) is recoverable without waiting out an over-long stale threshold — via a recovery sweep or an operator force-retrigger path — proven by a test that strands a run and then recovers it to a terminal-or-progressing state.

**Plans**: TBD

### Phase 10: Concurrency Proof

**Goal**: Produce the evidence behind the "production-grade" claim — a load/concurrency test that exercises the real invariants the Phase 9 work guarantees, under genuine parallelism, and asserts they hold. This is the capstone deliverable: the artifact a hiring manager can point to.
**Mode:** standard (test-only deliverable; no production code change beyond what it exercises)
**Depends on**: Phase 9 (this phase *validates* the atomicity + dedup + recovery work; it must come last because it asserts the invariants those fixes establish). Also exercises the Phase 8 indexes under load.
**Requirements**: OPS2-03
**Closes audit findings**: NEW proposed deliverable — load/concurrency proof (the evidence the production-grade claim needs)
**Success Criteria** (what must be TRUE):

  1. A concurrency proof test fires N simultaneous operations across the three risk surfaces — concurrent payroll runs, duplicate webhook deliveries for one `message_id`, and simultaneous approvals on a single run — under real parallelism (threads/processes against the DB, not serialized mocks).
  2. The test asserts every invariant holds: no double-approval (the `claim_status` CAS wins exactly once), no lost update, no duplicate run per inbound `message_id`, and no half-written run state — and fails loudly if any invariant is violated, so it stands as a genuine regression guard rather than a smoke test.

**Plans**: TBD

## Backlog

Captured ideas not yet scheduled into a milestone live in [`backlog.md`](backlog.md). Notable candidates carried forward / deferred from v2 scope:

- Real-email A5 threading verification (Path-2 inbound proven; the deep header-survival check stays a live-gate task, not a code change)
- Paystub YTD columns; eval-chart restyle; learn-aliases-from-confirmed-clarifications write-side polish
- Custom email domain (send FROM a real address) — documented upgrade path in README
- Additional Medicare 0.9% surtax modeling; SS wage-base straddle exactness (per-employee YTD Medicare ledger) — accepted limitations, tax-completeness features not hardening

## Progress

**Execution Order:** v2 phases execute in numeric order: 7 → 8 → 9 → 10

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 7. Money-Correctness Deepening | 1/2 | In Progress|  |
| 8. Data-Layer Hygiene & Diagnostics | 0/TBD | Not started | - |
| 9. Atomic Data Integrity | 0/TBD | Not started | - |
| 10. Concurrency Proof | 0/TBD | Not started | - |
