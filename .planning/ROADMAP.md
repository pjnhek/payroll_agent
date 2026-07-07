# Roadmap: Payroll Agent

## Milestones

- ✅ **v1.0 — MVP** (shipped 2026-06-25) — Email-driven payroll agent: messy email in, correct human-approved payroll out, every money-moving decision code-gated (deterministic, auditable, never guesses). 7 phases, deployed live on a free stack with a recorded demo. → [full archive](milestones/v1.0-ROADMAP.md) · [requirements](milestones/v1.0-REQUIREMENTS.md)

## Active Milestone: v2 — Production Hardening

**Goal:** Take the working v1.0 MVP and make its core money-logic and data layer genuinely production-grade — correct under real, messy, concurrent load, not just the demo path. Backend/logic only; scope was discovered via an adversarial audit (`v2-hardening-audit.md`), and every phase below closes concrete findings with file:line.

**Shape:** A focused, risk-ordered hardening pass on a shipped, deployed codebase — vertical slices, each phase independently shippable, "thin then deepen." Three audit rings (money-correctness → data-integrity → operability+evidence) split into four phases so the highest-risk work (the atomic transaction model + the dedup CAS race) lands as its own coherent, atomically-shippable unit, on top of a clean schema/diagnostics baseline, and is then *proven* by a concurrency capstone. Tech stack unchanged (FastAPI, psycopg3, Supabase Postgres, Pydantic v2, uv, pytest); TDD discipline throughout (failing test first for every fix).

### Phases

**Phase Numbering:** v2 continues the global phase sequence from v1.0 (last phase: 6). Integer phases (7, 8, 9, 10) are planned milestone work; decimal phases (e.g. 9.1) are reserved for urgent insertions.

- [x] **Phase 7: Money-Correctness Deepening (Pure-Function Gates)** - Close the two pure-function silent-mispay gaps: zero-hours $0 paystub and Unicode (NFC) name normalization — the engine never silently pays wrong on these messy-input paths. *(Scope reduced 2026-06-27: MONEY-03 field-regression moved to Phase 7.5 after three cross-AI review rounds showed it requires a `_run_stages` split refactor as its foundation — see 07-REVIEWS.md.)* (completed 2026-06-28)
- [x] **Phase 7.5: Clarification-Reply Field-Regression (MONEY-03)** - The clarification-reply field-regression state machine, built on a foundational `_run_stages` split refactor so carry-forward can land between reconcile and validate — detect a dropped money field, clarify once, carry forward (or honor an explicit removal) without an infinite loop (completed 2026-06-28)
- [x] **Phase 8: Data-Layer Hygiene & Diagnostics** - Restore schema-hygiene discipline (hot-path indexes, explicit column lists) and make production failures diagnosable from the DB (PII-safe `error_detail`) — the clean baseline the atomicity work builds on (completed 2026-07-02)
- [x] **Phase 9: Atomic Data Integrity** - The senior-engineer ring: atomic multi-write pipeline transactions (no half-written runs on crash), a transactional webhook-dedup CAS (Resend redelivery never duplicates a run), and a stuck-run recovery path for orphaned in-flight runs (completed 2026-07-04)
- [x] **Phase 10: Concurrency Proof** - The evidence capstone: a test fires N simultaneous runs / duplicate webhooks / concurrent approvals and asserts the invariants hold — no double-approval, lost update, duplicate run, or half-write — backing the production-grade claim (completed 2026-07-07)
- [x] **Phase 11: Clarification Round Machine & Alias Learning** - The clarify-cluster design phase: round-aware clarification (WR-05 silent-park fix + round cap/operator escape), question-anchored reply extraction, alias learning that binds on explicit client confirmation, and closure of the CX-01 multi-round context-loss deferred finding (completed 2026-07-06)

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

- [x] 07-02-PLAN.md — MONEY-01 `_is_paid` predicate + `any_hours` fix; MONEY-02 NFC `_norm` + eval `_normalize` parity

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

**Plans**: 4 plans
**Wave 1**

- [x] 07.5-01-PLAN.md — PLAN A: add no-op prior=/resolved_drops= kwargs to _run_stages and validate() (pure structural seam, zero behavior change)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 07.5-02-PLAN.md — RawFieldDrop + detect_field_regression + validate(prior=) (N6/N8 correct) + decide Rule 2b + compose_email N5/D-7.5-09 wording

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 07.5-03-PLAN.md — ClarifiedFields model + schema DDL (N4 DO$) + repo helpers + _clarify N7 snapshot + _RunStagesResult + resume_pipeline Round-1/Round-2 block (N1/N2/N3)

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 07.5-04-PLAN.md — 8 integration tests (D-7.5-04a ordering + D-7.5-04b/c + SC4 mixed-issue + loop-guard) + eval fixtures 16/17/18 + run_detail.html D-7.5-08 provenance badges

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

**Plans**: 3 plans
Plans:
**Wave 1**

- [x] 08-01-PLAN.md — Schema DDL: error_detail column, 3 hot-path indexes, businesses.contact_email coverage comment, payroll_runs.status CHECK swap (NEEDS_CLARIFICATION removal) + RunStatus enum edit
- [x] 08-02-PLAN.md — repo.py: centralized PII scrub-then-truncate helper wired into record_run_error; load_all_runs explicit-column projection with SQL-computed aliases

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 08-03-PLAN.md — Wire all 3 record_run_error call sites + templates + pool-singleton lock + test-double updates, then a blocking live-DB checkpoint applying the schema to Supabase

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

**Plans**: 6 plans *(revised 2026-07-03 after cross-AI review, 09-REVIEWS.md: 09-02/09-03/09-04 revised for Codex HIGH-1/2/3 + MEDIUMs/LOW; 09-01 gains a small doc/SQL correction; 09-05 added — a test-only fixture recording a Claude in-session HIGH finding (multi-round context loss) as an explicit deferred known-edge, disposition (c), out of Phase 9's atomicity/concurrency/recovery scope; 09-06 added 2026-07-04 — gap closure for 09-VERIFICATION.md's 2 DATA-01 gaps (resume_pipeline Round-2 unwrapped set_clarified_fields write, WR-02; _deliver's alias-write isolation not holding for DB-level errors, WR-01))*
Plans:
**Wave 1**

- [x] 09-01-PLAN.md — repo.py foundations: sweep_stranded_runs + find_run_by_message_id + get_connection test-mockability seam
- [x] 09-05-PLAN.md — (independent, no atomicity dependency) known-edge fixture + 09-CONTEXT.md deferred entry for the multi-round context-loss finding (09-REVIEWS.md Claude in-session HIGH, disposition (c))

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 09-02-PLAN.md — orchestrator.py DATA-01: _run_stages/_clarify/_deliver transaction boundaries (SC1); already-sent guard hardened for idempotent alias finalization (Codex HIGH-2)
- [x] 09-03-PLAN.md — main.py DATA-02/03: webhook dedup transaction restructured around a transactional ingest-decision (reply classified BEFORE create_run is reachable, Codex HIGH-1) + recovery sweep wiring + shared threshold

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 09-04-PLAN.md — llm/client.py timeout tightening (call_structured AND compose_clarification's call_text, Codex HIGH-3) + SC3 end-to-end sweep→retrigger proof

**Wave 1 (gap closure, 2026-07-04)**

- [x] 09-06-PLAN.md — gap_closure: resume_pipeline Round-2 clarified_fields persisted before _run_stages (WR-02); _deliver's alias write wrapped in a nested conn.transaction() SAVEPOINT (WR-01)

### Phase 10: Concurrency Proof

**Goal**: Produce the evidence behind the "production-grade" claim — a load/concurrency test that exercises the real invariants the Phase 9 work guarantees, under genuine parallelism, and asserts they hold. This is the capstone deliverable: the artifact a hiring manager can point to.
**Mode:** standard (test-only deliverable; no production code change beyond what it exercises)
**Depends on**: Phase 9 (this phase *validates* the atomicity + dedup + recovery work; it must come last because it asserts the invariants those fixes establish). Also exercises the Phase 8 indexes under load.
**Requirements**: OPS2-03
**Closes audit findings**: NEW proposed deliverable — load/concurrency proof (the evidence the production-grade claim needs)
**Success Criteria** (what must be TRUE):

  1. A concurrency proof test fires N simultaneous operations across the three risk surfaces — concurrent payroll runs, duplicate webhook deliveries for one `message_id`, and simultaneous approvals on a single run — under real parallelism (threads/processes against the DB, not serialized mocks).
  2. The test asserts every invariant holds: no double-approval (the `claim_status` CAS wins exactly once), no lost update, no duplicate run per inbound `message_id`, and no half-written run state — and fails loudly if any invariant is violated, so it stands as a genuine regression guard rather than a smoke test.

**Plans**: 1 planPlans:

- [x] 10-01-PLAN.md — Build the OPS2-03 concurrency proof capstone (tests/test_concurrency_proof.py: 3 surfaces, 4 invariants, N=8 real threads) + the CI job (concurrency-proof.yml) that runs it against an ephemeral postgres:16 on every push.

### Phase 11: Clarification Round Machine & Alias Learning

**Goal:** The multi-round clarification state machine becomes correct and unstrandable, and the alias-learning loop actually learns. Concretely: (1) WR-05 fix — a genuinely new clarification question always sends (round-aware idempotency instead of the purpose-only guard that today silently parks a run at `awaiting_reply` with no email out), with a round cap + operator-escape state (260623-08); (2) ambiguous replies get an attribution anchor — the outbound clarification's questions are included in the resume extraction context so a bare "40" can't be blindly attributed; (3) the alias-learning WRITE side binds on explicit client confirmation of the clarification *suggestion* (human-stated evidence) instead of the circular re-extraction condition that makes it unreachable today (260705-01), preserving the misname guard's never-learn-from-inference intent; (4) CX-01/T-09-21 multi-round context loss is closed (accumulate reply bodies or diff against last-persisted extraction — the known-edge fixture in `tests/test_multiround_context_edge.py` flips its assertion); (5) WR-06 provenance scoping and WR-04 redelivered-reply handling fold into the same round/consumed state design.
**Requirements**: CLAR2-01, CLAR2-02, CLAR2-03, CLAR2-04, CLAR2-05, CLAR2-06, CLAR2-07 (MONEY-class follow-ups derived from 260705-01/260705-02/260623-08 + 09-REVIEW.md WR-04/05/06 + 09-REVIEWS.md CX-01 + 09-CONTEXT.md deferred ideas)
**Depends on:** Phase 10 (concurrency proof may add fencing primitives the round machine reuses)
**Plans:** 9/9 plans complete

Plans:

- [x] 11-01-PLAN.md — Data-layer substrate: round/consumed-round columns, needs_operator status, widened uniqueness, all new repo primitives + InMemoryRepo mirrors (zero behavior change)
- [x] 11-02-PLAN.md — Round-aware _clarify: (purpose, round) guard (WR-05), round cap + needs_operator escalation, dashboard badge + scope exclusions
- [x] 11-03-PLAN.md — resume_pipeline consumed marker (D-11-02) + accumulated context with code-owned asked anchor (CX-01/D-11-12) + no-guess extraction; flipped known-edge fixture
- [x] 11-04-PLAN.md — Alias bind-on-confirmation (nested suggestion shape), operator resolve form + resume route with server-side roster validation, full-loop stops-asking test
- [x] 11-05-PLAN.md — main.py wiring: WR-04 redelivery re-schedule + D-11-05 stranded auto-resume + WR-06 retrigger-clears-all-context (CLAR2-06/07)

Gap closure (2026-07-06, cross-AI review findings — 11-REVIEW.md):

- [x] 11-06-PLAN.md — GAP-2/GAP-3 (CR-2/CR-3): payroll_runs.reply_epoch + email_messages.epoch so retrigger's clear_reply_context scopes the round machine to a fresh conversation without deleting the append-only audit log
- [x] 11-07-PLAN.md — GAP-1 (CR-1): remove /resolve's pre-claim double-CAS race that stranded operator-resolved runs in EXTRACTING forever
- [x] 11-09-PLAN.md — GAP-4 (CR-4, dual-source) + WR-1: bind-on-confirmation tied to the SAME reconciliation record (not two independent whole-run facts); set_alias_candidates becomes a JSONB merge, not an overwrite
- [x] 11-10-PLAN.md — GAP-5 (CR-5): re-assert FIX-5 sender revalidation at both the WR-04 redelivery re-schedule and the D-11-05 stranded-reply sweep

## Backlog

Captured ideas not yet scheduled into a milestone live in [`backlog.md`](backlog.md). Notable candidates carried forward / deferred from v2 scope:

- Real-email A5 threading verification (Path-2 inbound proven; the deep header-survival check stays a live-gate task, not a code change)
- Paystub YTD columns; eval-chart restyle; learn-aliases-from-confirmed-clarifications write-side polish
- Custom email domain (send FROM a real address) — documented upgrade path in README
- Additional Medicare 0.9% surtax modeling; SS wage-base straddle exactness (per-employee YTD Medicare ledger) — accepted limitations, tax-completeness features not hardening

## Progress

**Execution Order:** v2 phases execute in numeric order: 7 → 8 → 9 → 10 → 11

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 7. Money-Correctness Deepening | 2/2 | Complete    | 2026-06-28 |
| 8. Data-Layer Hygiene & Diagnostics | 3/3 | Complete    | 2026-07-02 |
| 9. Atomic Data Integrity | 6/6 | Complete    | 2026-07-04 |
| 10. Concurrency Proof | 1/1 | Complete   | 2026-07-07 |
| 11. Clarification Round Machine & Alias Learning | 9/9 | Complete   | 2026-07-06 |
