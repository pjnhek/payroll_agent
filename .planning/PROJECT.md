# Payroll Agent

## What This Is

An email-driven system that automates the weekly payroll intake the builder used to do by hand as a tax analyst. A client business emails its employees' hours; an LLM-driven pipeline reads the email, reconciles the submitted names against the business's roster, decides whether it can process the run or must ask the client a clarifying question, computes the payroll (gross, FICA, real IRS Pub 15-T federal withholding), and routes the result to a single human operator for one approval before the confirmation goes back to the client. Built end-to-end on a free stack so it runs and demos cleanly.

The narrative for the writeup: the manual payroll process from the builder's accounting days, rebuilt as an agentic pipeline — the LLM does the reading and an optional clarification *suggestion*; the name-match and process-vs-clarify decisions are resolved deterministically by code; a human approves only the final payroll before it reaches the client. **Primary audience: hiring managers / recruiters.** Optimize for *visibly works end to end* > *clean 60–90s demo* > *a real, legible eval chart*.

## Core Value

A messy real-world payroll email goes in; a correct, human-approved payroll comes out — and every money-moving judgment call (name match, process-vs-clarify) is **deterministic, auditable decisioning that never guesses, with a human-confirmation learning loop.** Each submitted name resolves against the roster in pure code (exact / stored-alias / none), collisions always clarify, and the LLM never decides — it only reads (extraction) and suggests a likely employee for the clarification email. The learning loop reads stored aliases and, since Phase 11, its write side is reachable end-to-end: a client-confirmed suggestion binds the alias deterministically (bind-on-confirmation, same-record evidence) at the operator-approval gate, so the system provably stops re-asking. If that deterministic decision flow works, everything else is plumbing.

## Current State

**v4 — Durable Execution — SHIPPED 2026-07-20.** No accepted email is ever lost, every failure recovers
automatically within ~30 minutes without a human noticing, and a client is sent at most one confirmation per
approved run, per epoch — and, per Phase 21's four falsifiable proofs, the property is demonstrated *able to
fail*. 6 phases (16–21), 19/19 requirements, 84 plans; milestone audit PASSED (19/19 reqs · 6/6 phases · 6/6
cross-phase seams · OPS-01 live UAT 2/2).

- **Accepted means durable** — the authenticated webhook commits a bounded inbound event and identifier-only
  `INGEST` job before returning 200; provider body fetch, sender routing, run creation, and orchestration happen
  only in later durable execution. All eight historical in-process producers were migrated; an AST guard fails
  CI if `BackgroundTasks` returns.
- **Recovery without a warm process** — a durable `jobs` table (SKIP-LOCKED claim, lease + double-fence,
  epoch-stable reclaim) drained by BOTH an in-process 2-thread worker pool and an authenticated `/internal/pump`
  on a 30-min cron; on Render free the pump is what makes the queue durable *execution*, not just storage.
- **At most once to the client** — confirmation delivery is frozen into an immutable snapshot handed to the
  worker over a row-locked provider-handoff authorization; a retry reuses the reserved `message_id` as the
  Resend `Idempotency-Key` and replays the persisted payload. Exactly-once is impossible (Two Generals);
  ambiguity escalates to operator review, documented honestly.
- **Demonstrated able to fail** — PROOF-01..04 (kill-mid-run, Svix redelivery, crash-between-provider-accept-
  and-`sent`-commit, expired-lease zombie fence) each carry a falsifying mutation executed red and byte-
  identically reverted, registered in the `queueproof`/`proof` CI gate; `/ops` + `GET /health/queue` surface
  queue health; `docs/DURABILITY-PROOFS.md` published and re-run end-to-end at UAT.

**v3 — Production-Ready Codebase — SHIPPED 2026-07-13.** The codebase now reads as production-quality
without a line of money behavior changed. 4 phases (12–15), 16/16 requirements, 227 commits, audit PASSED.

- **Enforced CI** — `ci.yml` runs `ruff check`, the full hermetic suite, and `mypy --strict` as three
  blocking jobs. The real-Postgres concurrency proofs now gate **pull requests**, not just post-merge
  master — they are the only tests in the repo that touch a real database, and before v3 they had never
  run in CI at all.
- **Right-sized modules** — `main.py` 1,857 → 16 lines (5 APIRouters + glue); `repo.py` 1,765 → a
  per-aggregate `app/db/repo/` package behind a stable facade; `orchestrator.py` 1,843 → 1,029. Cross-module
  `_private` imports promoted to public names, enforced by an AST guard proven able to fail.
- **Fully type-clean** — `mypy --strict` over **117 files** (app + eval + scripts + tests), blocking in CI.
- **Constraint-documenting comments** — ticket-ID/provenance archaeology stripped repo-wide and replaced with
  comments that name the failure they prevent, enforced by a CI guard pinned against the real ticket-family
  inventory harvested from git history.

**Three real defects surfaced by phases scoped as "hygiene":** the eval chart was misreporting exact-match
extraction as failing at 0.96 when it never had (a mislabeled fixture); a path traversal that actually
rendered a file from outside `eval/fixtures/` onto the eval page; and an LLM retry prompt echoing the model's
own output back to the provider. All three fixed test-first.

**Money-path safety, verified not asserted:** AST-diffed against the pre-milestone base with docstrings
stripped and string constants blanked — all **194** numeric/Decimal literals in `tax_tables_2026.py` are
identical, as are those in `federal_withholding.py` and `calculate.py`. `decide.py` still contains no scoring
concept. The deterministic-decisioning thesis survived three phases of refactoring intact.

- **Live:** https://payroll-agent.onrender.com (FastAPI on Render free + Supabase Postgres + Resend email)
- **Demo:** https://www.loom.com/share/b844c3e0a3364a91b114ab892cc41db4
- **Code:** https://github.com/pjnhek/payroll_agent
- **Suite (v4):** `queueproof` 73 passed / 0 skipped on ephemeral Postgres · full hermetic suite green · ruff clean · mypy --strict clean · all CI workflows green (milestone-audit-verified 2026-07-20)

<details>
<summary>Prior milestones (v1.0, v2)</summary>

**v2 — Production Hardening — SHIPPED 2026-07-07.** Took the working v1.0 pipeline and made its money-logic
and data layer genuinely production-grade — correct under real, messy, concurrent load, not just the demo path.
6 phases (7, 7.5, 8, 9, 10, 11), 16 requirements, scope discovered via an adversarial audit.

- **Money-correctness:** zero-hours silent-$0 gate (MONEY-01), Unicode-NFC name normalization (MONEY-02),
  field-regression clarification carrying the original value forward (MONEY-03).
- **Data integrity:** atomic multi-write transactions (DATA-01), webhook-dedup race fix (DATA-02), stuck-run
  recovery (DATA-03).
- **Operability + evidence:** PII-safe `error_detail` (OPS2-01), hot-path indexes (OPS2-02), a real-Postgres
  concurrency-proof test in CI (OPS2-03).
- **Clarification round machine & alias learning:** round-aware idempotency, 3-round cap escalating to
  `needs_operator`, multi-round context accumulation, and alias-learning that binds on client confirmation so
  the system provably stops re-asking (CLAR2-01…07).

**v1.0 — MVP — SHIPPED 2026-06-25.** The full email-driven pipeline: ingest & threading, deterministic
extraction/reconciliation/decide, penny-accurate Pub 15-T calc, one-gate HITL + PDF delivery, the 4-page
dashboard, the eval proof, and Render/Supabase/Resend hosting. 7 phases.

</details>

## Requirements

### Validated

- **Phase 21 (Durability Proofs & Ops View), 2026-07-20:** Every durability and exactly-once claim from
  Phases 16–20 is now demonstrated *able to fail*, not just shown passing, and an operator can read
  "is the queue healthy" as a fact. **PROOF-01..04:** four falsification-backed proofs against real
  Postgres — worker-killed-mid-run reclaim (attempts-increment mutation reds it), same-Svix redelivery
  = exactly one job/run/email (dedup-key mutation reds it), crash-between-Resend-accept-and-`sent` sends
  no second email (fresh-Idempotency-Key mutation reds it), and expired-lease reclaim with the zombie's
  late `mark_failed`/reschedule fenced (genuine two-OS-thread race, `threading.Barrier`, both fences
  named). **PROOF-05:** the completeness gate — a `proof` pytest marker + `check_proof_inventory.py` +
  an AST-anchored `MUTATION_TARGETS` registry wired into `concurrency-proof.yml` at the *selection*
  layer, so a proof can never silently stop running (the old hard-coded-file-list blind spot, and the
  Phase-10-v2 vacuous-proof precedent, both closed). **OPS-01:** `GET /ops` (queue depth split
  pending/leased, oldest-due-pending age vs the 30-min pump cadence, attempts vs max, dead-letter list)
  and `GET /health/queue` (503 while a run sits `error` with no equality-correlated job settlement — an
  anti-join, never a false-positive ratio), with `pump.yml`'s alarm step pinned last + `always()` and
  the drain step pinned to carry no `if:` (recovery-first). Verification independently re-ran two of the
  four mutations against a fresh local Postgres. **UAT this session against the LIVE deployed service:**
  discovered the phase was unpushed (master 94 ahead), pushed + redeployed; live alarm baseline = 0
  unaccounted error runs (clean); `pump.yml` dispatched (run 29773910333) proving drain-before-alarm
  ordering live; `/ops` verified legible + JS-free; and the published `docs/DURABILITY-PROOFS.md`
  re-run end-to-end (PROOF-01 green→apply doc's diff→red at `assert claimed.attempts == 1`→revert→green).
  Verified 6/6, UAT 2/2, 0 issues. PROOF-01, PROOF-02, PROOF-03, PROOF-04, PROOF-05, OPS-01.

- **Phase 20 (Exactly-Once Send), 2026-07-19:** Confirmation delivery is now at-most-once per approved run,
  per epoch. **SEND-01:** a retry reuses the reserved `message_id` (read-before-mint) as both Message-ID and
  Resend `Idempotency-Key`; the reservation upsert stops minting fresh uuids. **SEND-02:** a retry replays the
  persisted `subject`/`body_text`/`to_addr` snapshot rather than recomposing. **SEND-03:** delivery is frozen
  into an immutable snapshot handed to the worker over a row-locked (`FOR UPDATE`) provider-handoff
  authorization gated on the run's current `reply_epoch`; a `SEND_OUTBOUND` job gets provider authority ONLY
  through that durable handoff, and an ambiguous pre-provider window becomes a purpose-aware operator review
  with frozen evidence instead of an auto-resend. Re-verified 4/4 after 20-26/20-27 closed the delivery-expiry
  + live-evidence gaps. SEND-01, SEND-02, SEND-03.

- **Phase 19 (Webhook Cutover & Durable Ingest), 2026-07-17:** An authenticated inbound receipt now commits
  the bounded provider envelope and one identifier-only `INGEST` job atomically before HTTP 200; provider fetch,
  sender checks, RFC Message-ID dedup, run creation, and orchestration occur only in durable handlers. All eight
  historical in-process payroll producers were migrated, stale wrappers deleted, demo/reply/operator paths made
  transactionally queue-owned, and terminal-only inbound retention added without erasing job audit. Immutable
  operator generations make the first valid committed winner authoritative while later generations remain safe
  no-ops. Verified 40/40, UAT 1/1, security threats open 0; exact real-Postgres same-Svix proof passed in GitHub
  concurrency run `29589513220` with one event, one `INGEST` job, and one run. QUEUE-04.

- **Phase 18 (Failure Policy & Sweep Deletion), 2026-07-16:** Initial and clarification-resume orchestration
  now share one bounded `PipelineResult`; replay-safe failures bridge into durable backoff while terminal work,
  attempt exhaustion, and expired final-attempt leases settle atomically with bounded diagnostics. Persisted
  clarification replies must prove exact run ownership before conversion or replay, pump accounting reports
  final-lease reaping honestly, manual Retrigger preserves dead history while creating a fresh job generation,
  and the legacy stuck-run sweep surfaces are deleted so viewing the runs list cannot mutate state. Gap closure
  made final-lease settlement exhaustive and starvation-free and restored always-run resume-handler coverage.
  Verified 9/9 with a clean standard-depth code review; full hermetic suite 900 passed / 68 guarded skips.
  FAIL-01, FAIL-02, FAIL-03.

- **Phase 17 (The Pump), 2026-07-15:** Durable *storage* became durable *execution* on a platform with no
  worker dyno. **PUMP-01:** an authenticated, fail-closed (constant-time Bearer) `GET /internal/pump` claims and
  drains due jobs through the SAME `drain_once()` the in-process workers use — one drain path, two triggers,
  503 only on genuine infra failure. **PUMP-02:** cron drives the pump every 30 minutes, folded into a single
  `pump.yml` alongside the keepalive + schema-drift checks, and the README documents the duty-cycle / 750h /
  best-effort math honestly. A live `queueproof` test proves the pump (not the worker threads) drains a
  future-due job to `state='done'` on a zero-worker instance. PUMP-01, PUMP-02.

- **Phase 16 (Queue Substrate & Unblocked Webhook), 2026-07-14:** The durable substrate and the non-blocking
  webhook. **QUEUE-01:** the webhook's blocking work (Resend fetch, ingest transaction, dedup reads, reply
  resume) moves to `run_in_threadpool`, so `/webhook/inbound` never stalls the event loop (two 0.6s-slow
  requests finish in ~0.6s, not ~1.2s). **QUEUE-02/03:** a durable `jobs` table (UNIQUE `dedup_key`, SKIP-LOCKED
  claim, lease token + expiry, dual-fenced complete/fail, epoch-stable `rewind_for_reclaim`) drained by 2 daemon
  threads owned by the app's first-ever FastAPI `lifespan`, with a boot-time pool-budget guard that raises
  rather than clamps and an unconditional graceful-shutdown lease release proven against a real held lease.
  **QUEUE-05 / INVARIANT J-1:** `jobs` carries transport state ONLY, never a business status — enforced by an
  AST CAS-only guard that fails closed on six independent bypass shapes and by `test_job_kind_drift.py`.
  QUEUE-01, QUEUE-02, QUEUE-03, QUEUE-05.

- **Phase 1 (Thin Foundation), 2026-06-21:** The shared contract substrate exists and is proven by tests — the Postgres schema (6 tables, 11-value `payroll_runs.status` enum, `email_messages.message_id` idempotency UNIQUE), the shared `app/models/` Pydantic v2 contracts imported by both pipeline and eval, and seed data covering 3 businesses / 6 employees across every calc path and name-match case (happy-path + name-mismatch). FOUND-01, FOUND-02, FOUND-03, FOUND-05, FOUND-06. (Live-DB round-trip tests are written and skip-guarded pending Supabase credentials.)

- **Phase 4 (The Eval, the proof), 2026-06-22:** A reproducible offline eval imports and scores the *same* production judgment functions (`reconcile_names → validate → decide → _compute_line_items`) over 15 committed hand-curated fixtures spanning the full name-resolution taxonomy (exact / stored-alias / first-time-alias / typo / collision / unknown) plus field cases (missing/vague hours, buried reply). `eval/run_eval.py` scores the code-owned `final_action` (never the model's raw action), producing the three core metrics (extraction F1, per-NAME reconciliation accuracy, two-level decision accuracy) per category with a confusion matrix; headline `false_process_count=0`. Renders one committed per-category SVG chart (`eval/chart.svg`), guarded by a DB-free `--check` regression gate and the project's first CI workflow (`eval.yml`: hermetic push check + gated live re-record). Optional secondary LLM-as-judge (`eval/judge.py`) and `eval_results` write stub (`--db`) wired but local-only. Verified 4/4; code review found 8 issues, all fixed (commit 744a203). EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05.

- **Phase 5 (Dashboard & Delivery), 2026-06-23:** The operator gate and delivery path are live end-to-end. A 4-page Jinja2 dashboard (no SPA/build step): runs list with live-polling status badges, the DASH-02 *honest gate* run detail (3-column grid — raw cleaned email leftmost | LLM extraction | computed paystubs — with the code-owned decision banner), an eval view, and a demo "Send Test Email" picker across seeded businesses. On the single operator approval, the run advances `approved → sent → reconciled`: `_deliver` composes an LLM-drafted confirmation (deterministic floor on failure) with on-demand in-memory reportlab paystub PDFs (professional stub: company header, earnings w/ hourly rate + OT, deductions reconciling to net, net-pay band — no YTD/check, deferred). Concurrency is gated by an atomic `claim_status` CAS reused across approve/reject/resume/retrigger; sends are purpose-aware idempotent (`uq_email_run_purpose`); failures route to ERROR (retriggerable — nothing silently hangs). The alias WRITE-side learning loop (collision-safe, single-token, capture-time exclusion) persists a confirmed alias at the approval gate. A demo "Simulate client reply" completes the clarify→reply→resume loop through the real reply path. **The thesis held under adversarial test: no reply (off-roster/ambiguous/wrong) can make it process the wrong person — it re-clarifies.** Verified 5/5 must-haves + human UAT approved; 5 code-review rounds converged clean (3→1→1→1→0 findings), all fixed with regression tests; full suite 409 passing. DASH-01..05, HITL-02, HITL-03, CLAR-04, INGEST-05, FOUND-04.

- **Phase 7 (Money-Correctness Deepening), 2026-06-28:** The headline thesis — "never silently pays wrong" — now holds against two messy-input paths in the pure-function judgment layer, fixed via TDD (RED tests first, then GREEN). **MONEY-01:** a shared `_is_paid(v) -> v is not None and v > 0` predicate in `validate.py` replaces the old `any_hours = … is not None` check, so an hourly employee submitted with explicit zero hours (`hours_regular=0`, no others) gates to `request_clarification` instead of shipping a $0 paystub the reconciliation backstop can't catch; salaried-exception and partial-week (`hours_holiday=8`) guards hold. **MONEY-02:** `reconcile_names._norm` is hardened to the double-NFC form `NFC(casefold(NFC(s)))` so visually-identical names in different Unicode normalization forms (e.g. "José" NFC vs NFD) resolve to the same employee; `eval/run_eval.py` now imports that same `_norm as _normalize` (C-4 parity) so the eval scorer can never drift from production normalization. Phase also lands inert forward-compat scaffolding for Phase 7.5 — a widened `ValidationIssue.issue_type` Literal (`+field_regression`) and a `FieldDrop` model — defined but never instantiated/emitted in Phase 7 (scope fence held). *(Scope reduced 2026-06-27: MONEY-03 field-regression moved to Phase 7.5 — its resume state machine needs a `_run_stages` split refactor as a foundation.)* Verified 7/7 must-haves; code review 0 blockers / 3 advisory warnings; full suite 466 passing, 0 regressions. MONEY-01, MONEY-02.

- **Phase 7.5 (Clarification-Reply Field-Regression), 2026-06-28:** **MONEY-03 — the field-regression clarification state machine** ("did you forget the OT?") is live and money-safe. Built on a foundational `_run_stages` split refactor (Plan A, no-op seam landed + regression-tested first) so the carry-forward backfill lands *between* reconcile and validate/decide/calc — the only correct seam, proven across three cross-AI review rounds. The pipeline now: (1) **detects** a dropped money field on the RAW reply via `detect_field_regression` (employee-id-keyed on BOTH prior and current matches, so a restated name survives the diff), called before backfill in the D-7.5-10 three-phase ordering (detect < backfill < validate < calc); (2) **clarifies exactly once** — a two-inbound state machine persists `clarified_fields` with four outcomes (asked / carried_forward / confirmed_dropped / client_supplied) and a classify-first Round-2 path with a `suppress_detection` set that stops any answered field from re-clarifying (no infinite loop); (3) **carries forward or honors removal** — silent reply → original value restored from the write-once `pre_clarify_extracted` snapshot (paystub OT=2); explicit zero → honored as removal, NOT re-backfilled (paystub OT=0, the overpay guard); restated positive → client value used. A live Supabase schema migration added two JSONB columns + the N4 purpose CHECK. **Two real money-path bugs were caught and fixed mid-phase** (a `/gsd-code-review` pass + executor self-fix, both traced against live source): CR-01 (a restated name left an asked field unclassified → snapshot re-fill of a client-zeroed field = *overpay*; fixed by unioning current-roster reconciliation with prior_matches in the classify lookup) and R2-2 (a restated name at Round-1 made backfill miss the snapshot employee → *underpay* OT=0; fixed by also reconciling the snapshot's own names into the backfill lookup). A flagged CR-02 (migration non-atomicity) was verified a false positive — `bootstrap.py` applies `schema.sql` as one `conn.execute()`+one `commit()`, so the `DO $$` DROP+ADD is atomic. Evidence: 15/15 hermetic integration tests in `test_resume_pipeline.py` PASS live (0 skipped), 5 CR-01 unit tests, eval fixtures 16/17/18 + `eval --check` green, four D-7.5-08 provenance badges in `run_detail.html`. Verified 6/6 must-haves; full suite 507 passing (16 unrelated two-factor-guarded skips), 0 regressions. MONEY-03.

- **Phase 8 (Data-Layer Hygiene & Diagnostics), 2026-07-02:** Production failures are now diagnosable from the dashboard/DB without log access, and the project's stated schema-hygiene discipline is restored — the clean baseline Phase 9's transaction surgery builds on. **OPS2-01:** a nullable `payroll_runs.error_detail` column stores a PII-safe, stage-prefixed, truncated exception detail written by a centralized fail-open scrub-before-truncate helper (`_scrub`/`_build_error_detail` in `repo.py` — roster names Unicode-form/mark-aware redacted, emails regex-redacted) wired into all 3 production error boundaries (pipeline `_run`'s own except block after a roster-scope root-fix, `resume_pipeline`, the approve/delivery boundary); `RUN_COLS` returns it and `run_detail.html` renders it autoescaped. **OPS2-02:** the first 3 declared `CREATE INDEX IF NOT EXISTS` statements land the hot-path indexes (`email_messages(run_id, direction, send_state)`, `payroll_runs(created_at DESC)`, `payroll_runs(status)`; `businesses.contact_email` verified covered by its existing UNIQUE constraint, deliberately not duplicated — D-8-09), and `load_all_runs` selects an explicit scalar column list with a `jsonb_typeof`-guarded `employee_count` alias (no `SELECT *`, no JSONB blob over the wire for the list view). Also folded: the dead `needs_clarification` status removed from enum + CHECK (idempotent DO-block swap, todo 260623-06), the WR-02 thread-safe pool singleton, and an end-to-end DB-column→RUN_COLS→template integration test. Live Supabase migration applied + 6-check verified at the 08-03 blocking human checkpoint (schema-before-code deploy order held). Verified 3/3 must-haves; code review: 1 pre-existing Critical (CR-01 `alias_candidates` missing from RUN_COLS — alias-learning WRITE side is a production no-op, tracked for follow-up) + 6 advisory warnings; full suite 515 passing, 0 regressions. OPS2-01, OPS2-02.

- **Phase 9 (Atomic Data Integrity), 2026-07-04:** The data layer is now correct under concurrency and crashes — the senior-engineer signal of the milestone. **DATA-01:** every multi-write pipeline operation commits atomically — the persist+branch+status sequence in `_run_stages` and the send+alias+status sequence in `_deliver` each wrap in one `with conn.transaction()` (the alias write isolated in a nested SAVEPOINT so a DB-level failure can't poison finalize; the classify-first Round-2 resume persists `clarified_fields` in its own closed transaction before `_run_stages`), so a crash mid-sequence leaves the run wholly un-advanced, never half-written. **DATA-02:** `inbound()` is restructured around one atomic ingest-decision transaction that classifies duplicate/reply/unknown-sender/new-run *before* `create_run` is ever reachable, so duplicate webhook deliveries (Resend retries) can never create a second run even under parallel delivery — exactly one run per inbound `message_id`. **DATA-03:** an LLM-call timeout + `max_retries=0` bounds the worst-case run duration (65min → 15min), a sanctioned `sweep_stranded_runs` CAS-writer recovers orphaned in-flight runs, and the sweep is wired into every dashboard runs-list load. Initial verification found 2 DATA-01 gaps (WR-01/WR-02); gap-closure plan 09-06 fixed both (one write reordered + one nested SAVEPOINT), independently re-proved via fault-injection against a real local Postgres. Verified 7/7; 547 tests offline (591 live), 0 regressions. DATA-01, DATA-02, DATA-03.

- **Phase 10 (Concurrency Proof), 2026-07-05:** The evidence behind the "production-grade" claim — the capstone artifact. **OPS2-03:** `tests/test_concurrency_proof.py` fires N=8 real OS threads across three risk surfaces (webhook dedup, HTTP approval race, concurrent distinct ingests) against a real Postgres and asserts the four Phase-9 invariants hold — no double-approval, no lost update, no duplicate run, no half-written state — with a GitHub Actions job (`concurrency-proof.yml`) re-running it on an ephemeral `postgres:16` container on every push (standing CI evidence, not a local smoke test). A code-review round found CR-01: Surfaces A/C were serializing through the async webhook route rather than racing under true parallelism; the gap-closure (10-02) rewrote them to race the real sync DB seam under a `threading.Barrier` (pool `max_size=5` respected), closing CR-01 plus five corollary findings so the proof is genuine. Verified 9/9. OPS2-03.

- **Phase 11 (Clarification Round Machine & Alias Learning), 2026-07-07:** The multi-round clarification state machine is correct and unstrandable, and the alias-learning loop actually learns. **CLAR2-01:** `_clarify`'s idempotency guard re-keyed from purpose-only to `(purpose, round)` via `get_outbound_for_round`, so a genuinely-new round-2+ question always sends (no run silently parks at `awaiting_reply` with no email out) while a true re-trigger stays suppressed. **CLAR2-02:** a 3-round cap escalates to a first-class `needs_operator` status/badge with an operator resolve+resume surface (server-side roster validation) or reject. **CLAR2-03/05:** `resume_pipeline` writes the consumed marker at its own CAS claim and `_combined_context_email` accumulates ORIGINAL + all consumed replies in round order behind a code-owned "questions we asked" anchor — the known-edge fixture flips from documenting a silent-mispay to asserting it closed (Round-1 "30, not 40" pays 30). **CLAR2-04:** the unreachable count-diff alias bind is replaced with deterministic bind-on-confirmation against a persisted `{suggested, bound}` candidate shape, requiring same-record evidence (`_bind_evidence_for_token`) so the misname guard's never-learn-from-inference intent survives; a full-loop hermetic test drives REAL name resolution and proves the system stops asking. **CLAR2-06/07:** a redelivered/stranded unconsumed reply re-drives the CAS-gated resume (no permanently-dropped replies), and a per-run `reply_epoch` counter + retrigger context-wipe ensure no provenance badge outlives its data — without ever mutating the append-only `email_messages` audit log. Cross-AI review (Codex + internal) of the initially-passing phase found 5 CONFIRMED critical money/security bugs; all 5 + a warning were fixed via gap plans 11-06/07/09/10 and re-verified (exploits traced dead in merged source). Verified 9/9; full suite 596 passing, 0 regressions. CLAR2-01…CLAR2-07.

## Next Milestone: Demo Polish & Run-Detail UI (mini)

**v4 — Durable Execution — SHIPPED 2026-07-20** (full scope archived in `milestones/v4-ROADMAP.md` +
`milestones/v4-REQUIREMENTS.md`; the durable-handoff / pump / failure-policy / exactly-once-send / proofs
target features all landed). The next milestone is a small, demo-facing polish pass, to be formalized via
`/gsd-new-milestone`. Its scope is the four items reclassified from open todos / quick-tasks at v4 close,
preserved in full in `backlog.md` → "Next milestone (mini)":

1. **Run-detail page → chronological email conversation** — collapse the three-column debug view into one
   top-to-bottom email exchange (inbound first), demote extraction/paystub tables to a collapsed "Payroll
   details", single reply composer last; all Phase-20 delivery-review safety contracts unchanged. (Full plan
   preserved in backlog — was quick-task `260718-hie`, previously untracked.)
2. **Frontend progressive enhancement (no build step)** — optional ~30-line vanilla-JS status poll to replace
   the `<meta refresh>`; no SPA / bundler / TypeScript.
3. **Paystub YTD columns** — add per-category YTD accumulation (sum prior `reconciled` runs) so the stub can
   carry the standard Current | YTD layout; `generate_paystub_pdf` takes optional YTD params.
4. **Eval chart restyle** — bring `eval/chart.svg` onto the dashboard palette, or replace it with an inline
   HTML/CSS bar chart (no serve-time matplotlib).

### Active

Next-milestone requirements will be defined by `/gsd-new-milestone` from the four backlog items above. The v4
`REQUIREMENTS.md` was archived to `milestones/v4-REQUIREMENTS.md` and removed at close (fresh one created for
the next milestone).

Prior milestones: **v1.0** (email-driven pipeline, `milestones/v1.0-REQUIREMENTS.md`), **v2 Production
Hardening** (16 reqs: MONEY/OPS2/DATA/CLAR2, `milestones/v2-REQUIREMENTS.md`), **v3 Production-Ready Codebase**
(16 reqs: CI/STRUCT/TYPE/COMM/POLISH/BOUND, `milestones/v3-REQUIREMENTS.md`), and **v4 Durable Execution**
(19 reqs: QUEUE/PUMP/FAIL/SEND/PROOF/OPS, `milestones/v4-REQUIREMENTS.md`) — all shipped and validated.

### Out of Scope

- **Client-side confirmation step** — operator approval is the only gate; the single-gate story is the narrative. (Open decision #2, resolved.)
- **State withholding** — federal + FICA only, with a clear disclaimer; per-state withholding is genuinely complex and not core to the demo. `state_withholding` column stays nullable for later. (Open decision #3, resolved.)
- **Cached/persisted PDFs + Supabase Storage bucket** — paystubs generate on demand from run data; fits Render's ephemeral filesystem. (Open decision #1, resolved.)
- **Autonomous agent loop / LangGraph** — the path is fixed and controlled; a plain Python workflow with Postgres state is the orchestration.
- **Reasoning models** — non-reasoning chat variants only; over-thinking adds latency and this is not multi-step logic.
- **Tax-compliant production accuracy** — this is an explicitly educational model; the README says so plainly.
- **Auth on the dashboard** — it's a demo.
- **Spreadsheet-attachment parsing** — noted as a "later" stretch in the source plan; deferred from v1.
- **OBBBA tax provisions** — qualified-tips/overtime above-the-line deductions and the expanded 15-line W-4 Step-4(b) worksheet (new in the 2026 Pub 15-T) are explicitly disclaimed in the README; the engine implements the standard percentage method only. (Surfaced by research; resolved.)
- **v4: Throughput machinery** — per-tenant fairness lanes, priority lanes, adaptive backpressure, circuit breakers, and an N-concurrent-email load chart are all explicitly OUT. At ~1 payroll email per client per week these are machinery for load that will never arrive; the honest claim is *durability*, not throughput. The `jobs` schema still carries `business_id` / `priority` / `available_at` so each remains a later `ORDER BY` change rather than a migration. (Codex's over-engineering call; accepted.)
- **v4: Production-grade scheduling guarantees** — the pump is driven by GitHub Actions cron, which can be delayed and auto-disables after 60 quiet days. The guarantee is documented as *best-effort recovery within minutes*, with operator retry as the stated fallback. Claiming more would be a lie of the same class as the eval chart v3 had to fix.

## Context

- **Origin:** rebuild of the builder's real manual weekly-payroll intake from their tax-analyst/accounting days. The operator role is the role the builder personally played.
- **Decisioning model (the heart of the design), as shipped in Phase 2.1 — deterministic, no confidence anywhere:**
  1. *Deterministic resolution* (code, no model): each submitted name resolves against the roster as **exact** (unique normalized full_name), **stored-alias** (unique `known_aliases` hit — the READ side of the learning loop), or **none** (no match, typo, first-time nickname, garbled, or ambiguous). Required-field presence, sanity bounds, and arithmetic are likewise pure code. The resolver never guesses.
  2. *LLM judgment* (only where language understanding helps, and only as advisory copy): the **clarification-suggestion** call maps an unresolved name to the likely intended employee so the email is specific ("did you mean David Reyes?"). It is wired strictly AFTER the gate and never feeds the decision (D-21-05). Extraction is the other LLM judgment role.
  3. *The pure decide* (code): `decide.py` computes `final_action` purely from the resolution facts — `request_clarification` on any unresolved name, any run-level collision, or any missing required field. There is no model action to override and no score is read anywhere; the decision is deterministic and auditable.
- **Pipeline stages (9):** ingest/route → extract → name resolve (deterministic) → field validate → decide (pure code) → clarify-path (with the suggestion call) or process-path → operator approval → send → reconciliation check.
- **Model tiering (two tiers — the decision is pure code, so no decision/mid tier):** extraction = DeepSeek (stronger); drafting + the clarification suggestion = Kimi (cheap). One OpenAI-compatible client, base URL/model/key swapped per task.
- **Fixture-first development:** the whole pipeline is built and demoable by POSTing JSON fixtures to the webhook; the real email provider (n8n or a hosted inbound-parse service) is wired **last**, and the "send test email" button is both a demo feature and a live-email fallback. (Open decision #4, resolved.)
- **Render free realities to design around:** web service sleeps after 15 min, cold-starts under a minute, ephemeral filesystem, only inbound HTTP keeps it awake — so the webhook model fits and a polling loop would not.
- **The `status` column IS the orchestration engine** (surfaced by research): `payroll_runs.status` is simultaneously workflow position, durable checkpoint, the HITL gate, and the crash-recovery anchor — this is what cleanly replaces LangGraph. There are **two pause states** (still one *human* gate): `awaiting_reply` (machine pause on the client, resumes at stage 2) and `awaiting_approval` (the single operator gate, resumes at stage 8).
- **The DRY seam (load-bearing):** the four judgment stages are pure importable functions (data in, data out — never `extract(run_id)`); the hard gates live **inside `decide.py`** computing a code-owned `final_action`; the eval imports and scores those exact same functions. This is what makes the eval credible and tests the core thesis. Established early, not refactored to later.
- **Architecture additions** (surfaced by research, both adopted): an explicit `app/pipeline/orchestrator.py` state-machine driver, and a stuck-run/error recovery path (dashboard-visible `error` state + idempotent re-trigger) since an in-process `BackgroundTask` on a sleeping dyno can strand a run mid-stage.

## Constraints

- **Tech stack**: FastAPI in Docker on a Render free web service; Supabase Postgres for all state — chosen to run end-to-end on a free tier and demo cleanly.
- **Models**: Kimi and DeepSeek via OpenAI-compatible clients, non-reasoning chat variants — latency, and the task isn't multi-step reasoning. Model IDs are **config-driven** (env vars + `.env.example` placeholders); real strings pasted from the consoles later. (Open decision #5, resolved.)
- **Email**: a gateway catches inbound mail and posts to the app and sends outbound; threading is anchored on the RFC `Message-ID` header. Written gateway-agnostic behind one small interface.
- **Orchestration**: plain Python workflow, fixed path, state in Postgres — deliberately not an autonomous agent and not LangGraph.
- **Human-in-the-loop**: exactly one gate (operator approves computed payroll before send). Everything before it is automated.
- **Structured LLM calls**: JSON mode + Pydantic schema, one retry on parse failure.
- **Deterministic decisioning**: `decide.py` is pure code over resolution facts (exact / stored-alias / none + run-level collisions + missing fields → `final_action`) — no LLM call, no confidence number. (Phase 2.1 superseded the original 0.8-confidence-gate decision; the LLM is kept for extraction + the clarification suggestion only.)
- **Audience**: hiring-manager / recruiter facing — bias effort toward a rock-solid end-to-end happy-path-plus-name-mismatch flow and a real, legible eval chart over eval exotica.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Operator approval is the only human gate (no client confirm) | Keeps the single-gate narrative clean; one pause/resume state instead of two | ✓ Good — held through v2; the alias-learning write and `needs_operator` escalation both reuse this one gate |
| Skip state withholding (federal + FICA only, disclaimed) | Per-state withholding is complex and not core to an educational demo | ✓ Good — shipped, `state_withholding` stays nullable |
| Generate paystub PDFs on demand, no storage bucket | Fits Render's ephemeral filesystem; no state to persist | ✓ Good — in-memory reportlab on Render's ephemeral FS |
| Gateway-agnostic + fixture-first build sequencing | Decouples the one risky external dependency (inbound email) from everything that proves the system works; "send test email" doubles as demo + fallback | ✓ Good — Resend wired last behind the interface; fixture path still the dev/test spine |
| Config-driven model routing with placeholder IDs | Builder pastes real Kimi/DeepSeek strings from consoles; keeps tiers swappable | ✓ Good — env-driven two-tier routing live |
| Real IRS Pub 15-T percentage method for federal withholding | Most credible paystub; highest bug risk, so it's an isolated well-tested unit guarded by the reconciliation check | ✓ Good — penny-accurate, reconciliation backstop holds |
| Deterministic decisioning — resolve each name in pure code (exact / stored-alias / none), collisions always clarify, no confidence number (Phase 2.1, supersedes the original 0.8 threshold) | The "model says process, code blocks at 0.8" hero was not a real state for a well-calibrated model (an uncertain model self-clarifies); a pure resolver is auditable, reproducible, and genuinely never guesses on a money-moving decision | ✓ Good — the core thesis; held under v2's adversarial money-path review (Phase 7/7.5/11) |
| Eval = all 4 metrics over ~15–25 fixtures, one summary chart | Covers the full "judgment" narrative for a recruiter audience while staying achievable; the chart is the proof, not the demo | ✓ Good — 15→18 fixtures (v2 added field-regression cases), `false_process_count=0` |
| Plain Python workflow over LangGraph/agent loop | Path is fixed and controlled; Postgres is the checkpoint for the HITL pause | ✓ Good — the `status` column-as-state-machine survived v2's atomicity + round-machine work cleanly |
| Tax basis: 2026 Pub 15-T standard percentage method, disclaim OBBBA | Current-year credibility ($184,500 wage base, 2026 brackets) without OBBBA complexity; engine + eval ground truth share one assumption | ✓ Good — shipped and disclaimed in README |
| Add explicit `orchestrator.py` + stuck-run/error recovery | Keeps transition logic auditable in one place; a sleeping dyno can strand a run, so recovery is a first-class state, not an afterthought | ✓ Good — v2's DATA-03 sweep + retrigger made recovery a proven, dashboard-visible path |
| Hard gates live inside `decide.py` (not the orchestrator), computing `final_action` | The one placement that lets the eval test the same gated path as production — makes the eval credible and the thesis verifiable | ✓ Good — eval and production share the exact functions; verified across every v2 money phase |
| Operator gate shows the raw cleaned inbound email as the leftmost column (not just extracted vs computed) | Comparing computed paystubs against the LLM's own extraction agrees by construction; the human must verify the LLM's *reading* against what the client actually sent, or extraction errors pass the gate invisibly | ✓ Good — the honest 3-column gate shipped in Phase 5 |
| v1 eval uses hand-curated fixtures + a throwaway bootstrap drafting helper (full synthetic generator → v2) | At ~20 fixtures, hand-curation is faster, more realistic, and kills the train/test-leakage critique; the "scales to thousands" generator story isn't realized at demo scale | ✓ Good — hand-curation held; v2 extended fixtures by hand, not a generator |
| **v2:** `_run_stages` split so field-regression backfill lands between reconcile and validate/calc (Phase 7.5) | Three cross-AI review rounds proved it's the only correct seam; first-run and both resume rounds share one gated spine (DRY) | ✓ Good — the shared spine composed cleanly with the DATA-01 atomic wrapping |
| **v2:** Every multi-write op wrapped in one transaction; dedup + run-creation resolved transactionally; alias write in a nested SAVEPOINT (Phase 9) | A half-written run (paystubs replaced but status stale; email sent but status not advanced; duplicate run on a raced webhook) is the exact senior-engineer failure the milestone must not have | ✓ Good — proven via fault injection + the Phase 10 concurrency capstone under genuine parallelism |
| **v2:** Alias learning binds on explicit client confirmation of the suggestion, not a re-extraction count-diff (Phase 11) | The original count-diff condition was circular and unreachable, so the write side never fired; binding on human-stated evidence preserves the misname guard's never-learn-from-inference intent | ✓ Good — full-loop hermetic test proves the system stops re-asking; same-record evidence guard added after review |
| **v2:** Round cap escalates to a first-class `needs_operator` status rather than spamming or silently stalling (Phase 11) | The real failure was a silent park at `awaiting_reply` with no email out (WR-05), not spam; a bounded machine with a human escape is the safe terminal | ✓ Good — round-aware idempotency + 3-round cap + operator resolve/resume shipped |
| **v4:** `jobs` is transport state ONLY; `payroll_runs.status` stays the sole business state machine | A job row that also encodes "what payroll status comes next" creates two sources of truth for the same question — the classic way a queue corrupts a state machine it was added to protect | ✓ Good — held through v4 close; INVARIANT J-1 machine-enforced by an AST CAS-only guard + `test_job_kind_drift.py`, queue state stays a bounded secondary projection |
| **v4:** An authenticated pump endpoint + frequent cron, not an internal timer loop | Render free wakes only on **inbound HTTP**; internal sleeps do not keep it alive. Without an external pump, a queue is durable *storage* and never durable *execution* — a job retried with a future `available_at` would sit forever | ✓ Good — held through v4 close; the pump shares the single `drain_once()` with the workers and OPS-01's live UAT proved drain-before-alarm ordering on a real dispatch |
| **v4:** Exactly-once send via Resend's `Idempotency-Key`, keyed on the existing pre-send reserved `message_id` | `gateway.py` already mints a durable unique synthetic `message_id` and writes a `reserved` row *before* calling Resend — it just discards it. Handing it to the provider (and reusing it on retry, never minting a fresh uuid4) closes the double-payroll-email window that retries would otherwise open | ✓ Good — shipped Phase 20; PROOF-03 (Phase 21) demonstrates a crash between provider-accept and the local `sent` commit sends no second email, byte-identical `message_id` across attempts, and reds against a fresh-per-attempt key |
| **v4:** Milestone scoped to durability, not throughput | At ~1 payroll email per client per week, fairness/priority/backpressure machinery is building for load that never arrives; durability is the claim that is both true and load-bearing for any future productization | ✓ Good — v4 shipped durability (proofs able-to-fail, ops view, best-effort recovery) with zero throughput machinery; the honest claim held end to end |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-20 after the **v4 — Durable Execution milestone** shipped (Phases 16–21; all 19
requirements validated). v4 made the payroll pipeline durable end-to-end: a non-blocking webhook + durable
`jobs` queue (QUEUE-01..05), a shared-`drain_once()` worker pool + authenticated `/internal/pump` cron
(PUMP-01/02), an explicit `ok`/`retryable`/`terminal` failure policy with backoff + dead-letter and the
old age-based sweep deleted (FAIL-01/02/03), all 8 `BackgroundTasks` producers cut over to durable INGEST
(QUEUE-04), at-most-once confirmation via reserved-`message_id`/Resend-idempotency + a row-locked
provider-handoff (SEND-01/02/03), and four falsifiable durability proofs + `/ops`/`/health/queue`
observability with `docs/DURABILITY-PROOFS.md` (PROOF-01..05, OPS-01). Milestone audit PASSED (19/19 reqs,
6/6 phases, 6/6 cross-phase seams; OPS-01 live UAT 2/2). At close, 6 open artifacts were resolved (2 stale
status flags) and 4 demo/UI-polish items reclassified to `backlog.md` as the next mini-milestone scope.
Prior milestone: v3 — Production-Ready Codebase SHIPPED 2026-07-13. Next: `/gsd-new-milestone` (mini —
demo polish & run-detail UI). Full history below.*

<!-- Prior footer (v4 Phase 21): Last updated: 2026-07-20 — **v4 Phase 21 (Durability Proofs & Ops View) complete — MILESTONE v4 100% (all 6 phases 16–21 done).** Every durability/exactly-once claim from Phases 16–20 is now demonstrated able to fail (PROOF-01..04, each with an executed falsifying mutation against real Postgres), the completeness gate (PROOF-05) makes a proof unable to silently stop running, and an operator can read queue health as a fact via `GET /ops` + the `/health/queue` alarm (OPS-01). Verified 6/6; UAT 2/2 (0 issues) against the LIVE deployed service — which surfaced that the phase was unpushed (master 94 ahead); pushed + redeployed, live alarm baseline clean (0 unaccounted error runs), drain-before-alarm ordering proven via a real `workflow_dispatch` run, and `docs/DURABILITY-PROOFS.md` re-run end-to-end (green → apply the doc's own diff → red → revert → green). Verification canonicalized `human_needed` → `passed`. Next: `/gsd-complete-milestone v4` to archive. Prior: v4 Phase 19 complete 2026-07-17; Milestone v4 started 2026-07-13; v3 SHIPPED 2026-07-13. -->


<!-- Prior footer (v4 Phase 19): Last updated: 2026-07-17 — **v4 Phase 19 (Webhook Cutover & Durable Ingest) complete.** The webhook now commits an authenticated event plus `INGEST` job before 200, all eight historical in-process payroll producers are durable, and immutable operator generations preserve one commit-selected authority. Canonical verification passed 40/40, UAT passed 1/1, security threats open 0, and exact real-Postgres same-Svix concurrency passed in GitHub run `29589513220`. Phase 20 is next: make confirmation delivery exactly-once through provider idempotency. Prior: Milestone v4 started 2026-07-13; v3 — Production-Ready Codebase SHIPPED 2026-07-13. -->

<!-- Prior footer (v4 start): Last updated: 2026-07-13 — Milestone v4 Durable Execution started. Scoped from an adversarial audit finding two independent break-under-pressure defects: in-memory BackgroundTask durability and synchronous webhook work blocking the event loop. Target features: durable handoff, authenticated external pump, explicit failure policy, exactly-once send, and durability proofs. Throughput machinery explicitly out of scope. Design: docs/superpowers/specs/2026-07-13-durable-execution-design.md. -->

<!-- Prior footer (v3): Last updated: 2026-07-10 — **v3 Phase 13 (Module Structure & Boundaries) complete**; god-file splits landed behavior-neutral (suite 615 green), BOUND-01 guard live in CI. Milestone v3 started 2026-07-08: CI quality gates (ruff + full suite on push), god-file splits (main.py / repo.py / orchestrator.py), full mypy adoption wired into CI, comment-archaeology pass after the splits, public module boundaries, plus triaged v2 polish (Phase 05 review warnings, fixture-10 label). All refactors behavior-neutral against the 613-test suite. Prior: v2 — Production Hardening SHIPPED 2026-07-07. -->

<!-- Prior footer (v2): Last updated: 2026-07-07 after the **v2 — Production Hardening milestone** shipped (Phases 7, 7.5, 8, 9, 10, 11; all 16 requirements validated). v2 took the working v1.0 MVP and made its money-logic and data layer production-grade: MONEY-01/02/03 (zero-hours gate, Unicode-NFC names, field-regression carry-forward), OPS2-01/02/03 (PII-safe error_detail, hot-path indexes, real-Postgres concurrency proof in CI), DATA-01/02/03 (atomic multi-writes, webhook-dedup race fix, stuck-run recovery), CLAR2-01…07 (round-aware clarify idempotency, 3-round `needs_operator` cap, multi-round context accumulation, reachable bind-on-confirmation alias learning). Milestone audit PASSED (13/13 reqs, 6/6 phases, 5/5 integration seams, 3/3 E2E flows). Deferred: 6 non-blocking post-demo polish items (STATE.md → Deferred Items). Prior milestone: v1.0 SHIPPED 2026-06-25. Full history below.* -->

<!-- Prior footer (Phase 9): Last updated: 2026-07-04 after Phase 9 (Atomic Data Integrity) complete — DATA-01/02/03 are live: every multi-write pipeline operation commits atomically (classify-first Round-2 resume persists `clarified_fields` in its own closed transaction before `_run_stages`; alias write isolated in a SAVEPOINT so a DB-level failure can't poison finalize), transactional webhook-dedup CAS (Resend redelivery never duplicates a run), and stuck-run sweep recovery for orphaned in-flight runs. Initial verification found 2 DATA-01 gaps (WR-01/WR-02); gap-closure plan 09-06 fixed both, independently re-proved via falsification testing against a real local Postgres. Re-verified 7/7; 547 tests passing offline (591 live), 0 regressions. Known follow-ups (advisory, 09-REVIEW.md): WR-05 round-blind clarify idempotency guard, WR-07 stale strict xfail in test_gateway.py. Prior: Phase 8 (Data-Layer Hygiene & Diagnostics) complete 2026-07-02 — OPS2-01/OPS2-02 are live: PII-safe `error_detail` written at all 3 error boundaries and surfaced on the run-detail page, 3 hot-path indexes + explicit-column `load_all_runs` projection, dead `needs_clarification` status removed, live Supabase migration applied at the blocking human checkpoint (schema-before-code order held). Verified 3/3; 515 tests passing, 0 regressions. Known follow-up: pre-existing CR-01 — `alias_candidates` missing from RUN_COLS makes the alias-learning WRITE side a production no-op (see 08-REVIEW.md). Prior: Phase 7.5 (Clarification-Reply Field-Regression) complete 2026-06-28 — MONEY-03 is live: the field-regression clarification state machine detects a dropped money field on the raw reply, clarifies exactly once (four `clarified_fields` outcomes, no re-clarify loop), and carries the original value forward or honors an explicit removal — money-safe (no overpay, no underpay) under restated names, on the `_run_stages` split-refactor seam. Two real money-path bugs (CR-01 overpay, R2-2 underpay) were caught + fixed mid-phase via `/gsd-code-review` + executor self-fix; CR-02 was a verified false positive. Verified 6/6; 507 tests passing (15/15 live integration tests), 0 regressions. Prior v2 phase: Phase 7 (MONEY-01 zero-hours gate, MONEY-02 Unicode NFC normalization), 2026-06-28. Prior milestone: v1.0 SHIPPED 2026-06-25 (all 7 v1 phases, live on Render + Supabase + Resend). -->

<!-- Prior footer (v1.0): Last updated 2026-06-23 after Phase 5 (Dashboard & Delivery) complete — the operator gate + delivery path are live end-to-end: a 4-page Jinja2 dashboard (honest 3-column gate, live status polling, demo trigger), single-approval `approved → sent → reconciled` delivery with in-memory reportlab paystubs + idempotent confirmation email, atomic claim_status CAS across all gates, error path that never hangs, and the alias write-side learning loop. Verified 5/5 + human UAT approved; 5 code-review rounds converged clean; 409 tests passing. Prior: Phases 1, 2, 2.1, 3, 4 complete (contract substrate, walking skeleton, deterministic decisioning, penny-accurate Pub 15-T calc, the eval proof). Remaining: Phase 6 — real email provider + Docker/Render/Supabase deploy + README/demo.* -->
