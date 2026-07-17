---
gsd_state_version: 1.0
milestone: v4
milestone_name: — Durable Execution
current_phase: 19
current_phase_name: webhook-cutover-durable-ingest
status: executing
stopped_at: Completed 19-03-PLAN.md
last_updated: "2026-07-17T00:42:48.303Z"
last_activity: 2026-07-16
last_activity_desc: Phase 19 Plan 02 completed
progress:
  total_phases: 6
  completed_phases: 3
  total_plans: 41
  completed_plans: 32
  percent: 50
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-13 — Milestone v4 — Durable Execution started)

**Core value:** A messy real-world payroll email goes in; a correct, human-approved payroll comes out — every name-match and process-vs-clarify call is made deterministically by code (no confidence guessing). **v4 makes the pipeline durable: no accepted email is ever lost, every failure recovers automatically within ~30 minutes, and a client is sent at most one confirmation per approved run, per epoch.**
**Current focus:** Phase 19 — webhook-cutover-durable-ingest

## Current Position

Phase: 19 (webhook-cutover-durable-ingest) — EXECUTING
Plan: 4 of 12
Status: Ready to execute
Last activity: 2026-07-16 — Phase 19 Plan 02 completed

## Performance Metrics

**Velocity:**

- Total plans completed: 101
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 3 | - | - |
| 02.1 | 5 | - | - |
| 2 | 4 | - | - |
| 03 | 3 | - | - |
| 04 | 4 | - | - |
| 05 | 7 | - | - |
| 07 | 2 | - | - |
| 07.5 | 4 | - | - |
| 08 | 3 | - | - |
| 09 | 6 | - | - |
| 10 | 2 | - | - |
| 12 | 4 | - | - |
| 13 | 4 | - | - |
| 14 | 10 | - | - |
| 15 | 11 | - | - |
| 16 | 10 | - | - |
| 17 | 5 | - | - |
| 18 | 14 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 01-thin-foundation P01 | 22 | 2 tasks | 11 files |
| Phase 01 P03 | 5 | 2 tasks | 3 files |
| Phase 02 P01 | 34 | 3 tasks | 14 files |
| Phase 02 P02 | 38 | 4 tasks | 25 files |
| Phase 02 P03 | 24 | 3 tasks | 14 files |
| Phase 02 P04 (Tasks 1-2; Task 3 = human checkpoint) | 8 | 2 of 3 tasks | 6 files |
| Phase 02.1 P01 | 4 | 2 tasks | 3 files |
| Phase 02.1 P02 | 5 | 2 tasks | 5 files |
| Phase 02.1 P03 (Tasks 1-2; Task 3 = human checkpoint) | 7m | 2 of 3 tasks tasks | 12 files files |
| Phase 02.1 P04 | 5m | 2 tasks | 7 files |
| Phase 02.1 P05 | 14min | 3 tasks | 13 files |
| Phase 05-dashboard-delivery P03 | 35 | 3 tasks | 8 files |
| Phase 11 P05 | 50min | 4 tasks | 4 files |
| Phase 11 P07 | 35min | 1 tasks | 2 files |
| Phase 11 P10 | 25min | 1 tasks | 2 files |
| Phase 10 P02 | 25min | 2 tasks | 2 files |
| Phase 12 P04 | 100min | 3 tasks | 1 files |
| Phase 14 P01 | 4 | 3 tasks | 6 files |
| Phase 14 P02 | 10 min | 3 tasks | 12 files |
| Phase 14 P03 | 13 min | 3 tasks | 12 files |
| Phase 14 P04 | 7min | 3 tasks | 5 files |
| Phase 14 P05 | 8 | 2 tasks | 5 files |
| Phase 14 P10 | resumed closeout | 4 tasks | 3 files |
| Phase 17 P01 | 20min | 2 tasks | 8 files |
| Phase 17 P02 | 9min | 2 tasks | 3 files |
| Phase 17 P03 | 15min | 3 tasks | 4 files |
| Phase 17 P04 | ~12min | 2 tasks | 4 files |
| Phase 17 P05 | 9min | 2 tasks | 1 files |
| Phase 18 P01 | 4min | 2 tasks | 2 files |
| Phase 18 P02 | 15min | 3 tasks | 10 files |
| Phase 18 P12 | 5min | 1 tasks | 2 files |
| Phase 18 P09 | 17min | 3 tasks | 10 files |
| Phase 18 P03 | 25min | 3 tasks | 9 files |
| Phase 18 P04 | 11min | 2 tasks | 6 files |
| Phase 18 P06 | 7min | 2 tasks | 7 files |
| Phase 18 P05 | 8min | 2 tasks | 3 files |
| Phase 18 P10 | 9min | 1 tasks | 3 files |
| Phase 18 P11 | 21min | 2 tasks | 15 files |
| Phase 18 P07 | 12min | 2 tasks | 6 files |
| Phase 18 P08 | 10min | 2 tasks | 9 files |
| Phase 19 P01 | 12min | 3 tasks | 9 files |
| Phase 19 P02 | 12min | 2 tasks | 2 files |
| Phase 19 P03 | 13min | 3 tasks | 4 files |

## Accumulated Context

### Roadmap Evolution

- **v4 roadmap created (2026-07-14):** 6 phases (16–21), continuing global phase numbering from v3's Phase 15. Phase 16 Queue Substrate & Unblocked Webhook (merges research's Phase 1 "unblock the event loop" — zero schema, no forced-order dependency — into the queue-substrate phase, since granularity is "standard" and a single-requirement standalone phase for QUEUE-01 alone would fragment unnecessarily) -> Phase 17 The Pump -> Phase 18 Failure Policy & Sweep Deletion -> Phase 19 Webhook Cutover & Durable Ingest -> Phase 20 Exactly-Once Send -> Phase 21 Durability Proofs & Ops View. Hard-ordered per the milestone's non-negotiable constraint (from `.planning/research/ARCHITECTURE.md`): the pump (17) and the failure policy (18) MUST precede the webhook cutover (19), or the cutover ships a regression window where a worker records SUCCESS on a FAILED payroll while the old sweep races the new queue. Phase 20 (send) is independent of Phase 19 and could ship in parallel, but is sequenced after for planning clarity. Phase 21 (proofs) is last by definition — it proves all 5 preceding phases, and explicitly encodes the two cross-cutting hazards flagged in REQUIREMENTS.md (concurrency-proof.yml's hard-coded test-file list; the precedent of a vacuous "concurrency proof" from Phase 10 of v2 that passed while proving nothing). 19/19 v4 requirements mapped, no orphans (note: the milestone's own header text says "17 REQ-IDs," which undercounts the actual enumerated set by 2 — traceability was built against the real 19).
- v3 roadmap created (2026-07-08): 4 phases (12-15), continuing global phase numbering from v2's Phase 11. Phase 12 CI Quality Gates -> Phase 13 Module Structure & Boundaries -> Phase 14 Full Type-Checking (mypy) -> Phase 15 Comment Hygiene & Deferred-Polish Triage. Hard-ordered per the milestone's ordering constraint: CI first (protects every later refactor), STRUCT (incl. BOUND-01) before COMM (comments rewritten once, in final file locations), TYPE its own phase after STRUCT (smaller split modules are easier to annotate; user explicitly ruled out squeezing full mypy adoption into a shared phase). 16/16 v3 requirements mapped, no orphans.
- Phase 11 added (2026-07-05): Clarification Round Machine & Alias Learning — clarify-cluster design phase from phase-9 review findings (WR-04/05/06, CX-01) + conversation-traced findings (alias-learning bind unreachable, ambiguous-reply attribution); sources: todos 260705-01, 260705-02, 260623-08

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: v4 — `jobs` is transport state ONLY; `payroll_runs.status` stays the sole business state machine (INVARIANT J-1, enforced by a CI drift guard analogous to the existing `RunStatus`↔CHECK test).
- [Roadmap]: v4 — Forced phase order 16→17→18→19 (queue substrate → pump → failure policy → webhook cutover) is non-negotiable; deleting `sweep_stranded_runs` happens in the SAME phase the failure policy lands (Phase 18), not deferred until "the queue is proven."
- [Roadmap]: v4 — Every durability proof (Phase 21) must ship with a demonstrated red run, per the Phase-10 (v2) precedent of a vacuous concurrency proof that passed while proving nothing.
- [Roadmap]: Vertical MVP shape — thin foundation (P1), then walking skeleton as the FIRST end-to-end proof (P2), then deepening rings ordered by risk.
- [Roadmap]: Calc is deliberately thin in P2 (gross + FICA only; federal LEFT OUT; net labeled "pre-federal" — never a fake federal number). Full Pub 15-T penny-accuracy is P3, before any correctness claim.
- [Roadmap]: The DRY seam — judgment stages are pure functions; hard gates live INSIDE `decide.py` computing a code-owned `final_action` that is the SOLE branch source (orchestrator/dashboard/eval never branch on `model_action`).
- [Roadmap]: Operator gate (DASH-02) shows the raw cleaned inbound email as the leftmost column — the honest operator gate.
- [Roadmap]: Drop-if-tight items — EVAL-04 (LLM-judge metric), INGEST-05 (error recovery).
- [Phase ?]: D-10/D-11/Finding#5/FIX-B applied in seed.py: Pydantic validation at import, fixed UUIDs, SS straddle on per-period wages vs remaining wage base, Sandra Kim pay_periods=26
- [Phase ?]: [Phase 2 P01]: D-A3-05 option (a) — dedicated payroll_runs.reconciliation JSONB column (not nested under decision); keeps Decision contract exact + Phase 5 dashboard query clean.
- [Phase ?]: [Phase 2 P01]: repo helpers take optional conn= so the webhook shares a transaction and tests assert SQL offline via a FakeConnection (no live DB needed for parameterized-SQL/serialization/status-write contracts).
- [Phase ?]: [Phase 2 P02]: validate() is pay-type aware via the roster (a pure value) so the missing-hours rule distinguishes hourly (hours required) from salaried (legitimately none) — keeps purity AND the clean path green.
- [Phase ?]: [Phase 2 P02]: the code gate in decide.py uses per-name Decimal('0.8') (never the collapsed min() scalar); check_one_to_one ships empty-but-real for Plan 03 to extend.
- [Phase ?]: [Phase 2 P03]: Layer-2 LLM reconcile is residual-only via the NameReconciliationResponse{matches} wrapper (FIX 6 — model_validate_json needs a BaseModel, not a bare list); a layer-1 hit is never re-decided.
- [Phase ?]: [Phase 2 P03]: check_one_to_one EXTENDED (signature unchanged) into full one-to-one mapping enforcement (two->one emp / dup name / name->no emp); a high-confidence collision still gates (G6).
- [Phase ?]: [Phase 2 P03]: clarify drafts via DRAFT_* call_text (templated fallback), sends via gateway.send_outbound (Message-ID on the outbound email_messages row — single FIX-3 anchor, no payroll_runs column), pauses at awaiting_reply via set_status; one persist_reconciliation covers both branches (D-A3-05).
- [Phase ?]: [Phase 2 P04]: reply routing happens in the webhook BEFORE first ingest, gated on the inbound carrying an in_reply_to/references — find_awaiting_reply_for_header (awaiting_reply only) for resume, FIX-5 sender revalidation against the run's business, find_any_run_for_header for late-reply log (FIX 10); no-header inbounds fall through unchanged.
- [Phase ?]: [Phase 2 P04]: resume_pipeline re-extracts over (original cleaned body via load_source_email + reply body) so a partial reply is lossless (FIX 4 + FIX C), passes the code-owned run_id into extract (FIX A), overwrites extracted_data + replaces line items; the four stages are factored into a shared _run_stages() so first-run and resume share the identical gate path (DRY).
- [Phase ?]: [Phase 2 P04]: the live-vs-mock provenance marker (FIX 12) is a structured LOG field source="live"/"mock" derived from Settings.allow_live_llm — never a key in the extra=forbid Decision and never a schema column (an always-runs guard test pins this).
- [Phase ?]: [Phase 02.1 P01]: Contracts reshaped deterministic — NameMatchResult=source(exact|alias|none)+explicit resolved bool; Decision=final_action/gate_reasons/unresolved_names/missing_fields+resolutions:list[NameMatchResult] (folded into decision JSONB, no name_matches table); PaystubLineItem drops match_confidence; reconcile.py/NameReconciliationResponse deleted. No confidence anywhere (D-21-01/04/05/06).
- [Phase 02.1]: [Phase 02.1 P02]: reconcile_names + decide are now PURE deterministic code — no LLM, no confidence, no model_action; final_action computed from unresolved (resolved is False) + run-level collisions + missing fields is the SOLE branch source (D-21-01/02/03)
- [Phase 02.1]: [Phase 02.1 P02]: collision safety lives in TWO places — deterministic_match refuses to resolve a name matching 2+ employees (None -> unresolved); check_one_to_one stays a run-level authority gating even when both colliding names are resolved=True (D-21-02); decide Rule 1 keys off resolved and the old check_one_to_one no-roster-employee branch was dropped to avoid double-counting Rule 1
- [Phase 02.1]: [Phase 02.1 P03]: orchestrator wired to the pure stages (decide/reconcile called with no llm; no m.confidence stamp; branches solely on final_action); repo INSERT + schema.sql drop match_confidence; bootstrap drops the dead name_matches on EVERY apply (default path + _DROP_ORDER front) for the live-DB migration; config two-tier (extraction+draft), mid/decision tier removed from Settings/client/.env.example (D-21-05/06). Live-DB DROP + human .env edit = PENDING blocking checkpoint (Task 3).
- [Phase 02.1]: [Phase 02.1 P04]: Suggestion-only call (LLM-05/D-21-05) — a cheap draft-tier call maps an unresolved name to the likely roster employee for the clarification email ONLY; wired strictly after decide() inside _clarify, degrades to {} on any failure, structurally walled off from decide (decide never imports suggest; a test asserts the suggested id never leaks into the persisted Decision).
- [Phase 02.1]: [Phase 02.1 P04]: compose_clarification gains suggestions= threaded into BOTH the draft prompt and the deterministic _template_body floor so the 'did you mean David Reyes?' hero survives a total draft failure (WR-03); a suggested name must be an exact roster full_name or it is dropped.
- [Phase ?]: [Phase 02.1 P05]: DEMO-01 reframed deterministic — gate_block_hero = unknown-shorthand 'David Reyez' resolves to source=none -> request_clarification (suggestion call names David Reyes); NEW collision_safety.json + constraint-safe seed pair (Daniel Reyes e0000007 shares 'D. Reyes' alias with David Reyes; DISTINCT full_names so UNIQUE holds). Never guesses on a money-moving decision (D-21-01/02).
- [Phase ?]: [Phase 02.1 P05]: Final sweep — all residual tests on deterministic source/resolved+Decision shapes (no confidence/model_action/match_type/0.8); CLAUDE.md/REQUIREMENTS.md/PROJECT.md/ROADMAP.md rewritten to deterministic auditable decisioning + learning loop (WRITE side P5); eval taxonomy=exact/stored-alias/first-time-alias/typo/collision/unknown. Mocked suite GREEN (195); app/+docs grep-clean. Phase 2.1 COMPLETE.
- [Phase ?]: D-12 closed: claim_status is the second sanctioned status writer; all contended gates use CAS not load-then-set
- [Phase ?]: D-13b: RunStatus.APPROVED removed from _TERMINAL_STATUSES — delivery failure after approval routes to ERROR for retriggering
- [Phase ?]: D-13c sharpened NEW-1: insert_email_message upserts on (run_id, purpose) for outbound rows — retry-over-reserved advances to sent instead of crashing on uq_email_run_purpose
- [Phase ?]: D-05 OT explicit-zero decision: hours_overtime=0 treated same as absent — never silently underpays a weekly employee
- [Phase 11 P05]: clear_reply_context is called ONCE at the retrigger route's single 'if claimed:' post-claim convergence point (reached by both the ERROR/APPROVED CAS and the stale in-flight CAS) rather than duplicated inside each branch — satisfies WR-06/D-11-04 clearing ALL reply-round context (clarified_fields, pre_clarify_extracted, clarification_round, alias_candidates) before _run_pipeline is scheduled.
- [Phase 11 P05]: _row_to_inbound is a pure app.main helper (not repo.py) building an InboundEmail from a persisted email_messages row, reused by both the WR-04 redelivery re-schedule and the D-11-05 stranded auto-resume — never re-cleans a redelivered request body (Pitfall #11a).
- [Phase 11]: Route validates+applies overrides then unconditionally schedules background resume; resume_pipeline is the sole CAS claimer (no route-level pre-claim), matching the webhook reply-resume path
- [Phase 11]: Shared _reply_sender_ok(row, run) predicate re-asserts FIX-5 sender revalidation at both the WR-04 redelivery re-schedule and the D-11-05 stranded-sweep seam (GAP-5/CR-5) — A FIX-5-failed linked reply left unconsumed could otherwise be resumed later via redelivery or dashboard load, bypassing sender auth entirely
- [Phase ?]: Surfaces A and C bypass the async /webhook/inbound route entirely and race repo.insert_inbound_email/repo.create_run directly from barrier-released OS threads (CR-01 fix).
- [Phase ?]: N_INGEST=5 matches the app pool max_size=5 because Surfaces A/C threads are simultaneous connection HOLDERS for the full ingest transaction, unlike Surface B's brief CAS (kept at N_APPROVE=8).
- [Phase ?]: CI schema step drops bootstrap --reset; the seeded_db fixture is the sole reset owner behind its ALLOW_DB_RESET two-factor guard (WR-04).
- [Phase 12 P04]: Master pushed to origin (fast-forward 2eaa5fc..157633d) before the red-proof branches — the plan's assumed prior master ci.yml run did not exist (Rule 3 deviation, covered by push authorization); this triggered the repo's first-ever ci.yml run, green on both jobs
- [Phase 12 P04]: Red-proof injections single-cause by design: one F401 (unused import sys, app/main.py) failed ONLY lint; one broken assertion (test_check_schema_cli.py) failed ONLY test — both locally verified pre-push, human-verified live, branches deleted per D-14 (run history persists)
- [Phase 14]: Phase 14 Plan 01: Keep mypy scope and strictness in committed pyproject.toml config so bare local and CI commands have identical coverage.
- [Phase 14]: Phase 14 Plan 01: Use a narrow _ReceivedEmailLike Protocol plus cast for Resend's ResponseDict runtime attributes; preserve existing attribute access and avoid Any.
- [Phase 14]: Phase 14 Plan 01: Keep the eval import regression fix separate from its RED test, and keep the BracketRow annotation separate from the gateway change.
- [Phase 14]: Repository facade export style remains unchanged after direct mypy measurement found no re-export errors.
- [Phase 14]: Dynamic psycopg row and JSONB boundaries use dict[str, Any], while OpenAI chat messages use ChatCompletionMessageParam.
- [Phase 14]: Confirmed Resend's installed EmailsReceiving.get runtime returns an attribute-style ReceivedEmail, so the existing _ReceivedEmailLike Protocol/cast remains the correct boundary.
- [Phase 14]: Used concrete types for money-path values and typed collections, retaining Any only for dynamic payloads and injected provider objects.
- [Phase 14]: Preserved delivery exception handling exactly and scoped the only new ignore to exc.payroll_roster with the WR-04 rationale.
- [Phase 14]: Keep app/main.py unchanged because its baseline mypy check was already clean.
- [Phase 14]: Use concrete route response/domain types and explicit None narrowing at optional database-result boundaries.
- [Phase 14]: Plan 14-05 uses TypedDicts for stable eval scoring and aggregation shapes, with Any retained only at JSON and DB dynamic boundaries.
- [Phase 14]: Operational scripts are verified with side-effect-free py_compile rather than execution because they touch the live database.
- [Phase ?]: v4 Phase 17 Plan 01: the fail_job()-itself-fails double-failure branch RE-RAISES out of drain_once() rather than mapping to a truthy DrainOutcome.FENCED — an infra outage must never look like a settled success to a caller (worker or the eventual pump route).
- [Phase 17]: count_open_jobs stays a plain state IN ('pending','leased') count -- no strand-exclusion special-casing, so queue_depth honestly reflects the documented final-attempt lease-strand residual until Phase 18's dead-letter transition reaps it.
- [Phase 17]: pump.yml's --max-time 420 pump step is a NOMINAL operating budget (cold-start 60 + 120s between-jobs cap + ~240s external-call allowance, no headroom claimed); correctness rests on lease-reclaim (lease_seconds=900), not the curl timeout.
- [Phase 17]: keepalive.yml deleted and folded into pump.yml as the sole 30-min cron with a workflow-level concurrency group; both keepalive jobs (wake + schema-drift) carried forward verbatim.
- [Phase 17]: README's BackgroundTasks limitation bullet corrected to state the durable queue's true partial-migration state (proven only on operator Retrigger) rather than overclaiming a full cutover not yet shipped.
- [Phase 17]: 17-04: GET (not POST) for /internal/pump — simplest for a curl cron; the drain is idempotent (SKIP LOCKED).
- [Phase 17]: 17-04: pump_token fail-closed logic lives in the route's _authorized(), not as Settings field validation (matches ALLOW_UNSIGNED_FIXTURES precedent).
- [Phase ?]: [Phase 17]: 17-05: falsifying mutation targeted /internal/pump's drain while-loop (while False:) — a smaller, more surgical revert than claim_job's SQL — RED confirmed claimed==0, GREEN confirmed byte-identical revert.
- [Phase 18]: Only extraction-stage connection, timeout, rate-limit, and 5xx provider failures are retryable; unclassified failures and ambiguous sends fail closed. — Extraction is replay-safe, while clarification and delivery can be ambiguous after provider acceptance.
- [Phase 18]: Legacy None has one temporary meaning through normalize_pipeline_result; explicit results preserve identity and invalid values raise. — One compatibility seam prevents consumers from inventing conflicting None policies before producer cutover.
- [Phase 18]: Future resume kinds remain dormant bounded kind.value branches until Plan 18-09 atomically widens JobKind, SQL, and dispatch. — Keeps the one-kind drift equality green while making identifier validation ready.
- [Phase 18]: Operator mappings persist as immutable UUID generations with typed submitted-name child rows independent of reply_epoch. — Allows exact idempotent replay and multiple valid same-epoch submissions without jobs payloads or alias-candidate authority.
- [Phase 18]: Exact catalog tuples gate typed operator-resolution schema health — Same-named indexes or constraints with wrong table, columns, type, or references are drift.
- [Phase 18]: Both retry handlers re-enter resume_pipeline from RECEIVED; only reclaimed attempts use rewind_for_reclaim without advancing reply_epoch.
- [Phase 18]: Operator retry authority comes only from immutable resolution rows, exact unresolved-name equality, and run-roster membership; alias_candidates is never authority.
- [Phase 18]: One fenced repository coordinator owns cross-aggregate queue/run settlement; retry diagnostics remain on jobs until terminal or exhaustion. — Prevents transport and business state from committing incompatible outcomes.
- [Phase 18]: Operator authority is a complete immutable UUID generation; remember choices affect only optional alias learning. — Keeps retries reconstructable without mapping payloads or alias_candidates authority.
- [Phase 18]: Queue consumers normalize legacy None only through normalize_pipeline_result; every normalized result uses the fenced settlement coordinator. — One compatibility seam prevents queue consumers from assigning conflicting meanings before producer cutover.
- [Phase 18]: Final-attempt reaping preserves jobs.last_error as prior-attempt history while assigning FinalAttemptLeaseExpired to the run. — The final diagnostic must identify lease expiry without discarding or misattributing an earlier attempt failure.
- [Phase 18]: Browser routes derive a strict safe failure projection and remove raw diagnostics before template or JSON use.
- [Phase 18]: Error remains canonical; exhausted retries are a bounded secondary label only.
- [Phase 18]: Use a separate drained counter for the request cap so final-lease reaps remain bounded without inflating claimed work. — This preserves both the 20-outcome request bound and the operator-facing meaning of claimed.
- [Phase 18]: Represent final-lease maintenance as dead plus reaped_final_lease while preserving every legacy outcome counter exactly. — D-14 requires dead-letter visibility without pretending the maintenance path executed a claimed job.
- [Phase 18]: Both orchestrator producers classify and return bounded outcomes; background wrappers and the queue drain remain the sole terminal persistence owners. — This preserves one failure persistence owner per execution mode after the producer cutover.
- [Phase 18]: Dynamic forwarding boundaries validate PipelineResult at runtime even though static annotations are exact, so unsound values fail loudly instead of becoming success. — Static typing cannot protect dynamic handler lookup or injected test doubles.
- [Phase 18]: Background wrappers remain None-returning terminal procedures, while every value-producing seam is PipelineResult-only. — Procedures exhaustively consume and settle policy values rather than forwarding them.
- [Phase 18]: GET /runs is strictly read-only and owns no automatic recovery behavior. — Durable queue workers own automatic recovery; explicit mutation routes own operator recovery.
- [Phase 18]: Webhook redelivery and durable resume handlers remain the supported automatic resume entry points. — Caller subtraction removes page-load recovery without weakening sender, consumption, mapping, or epoch safeguards.
- [Phase 18]: The durable queue is the only automatic recovery policy; no legacy age-based repository or fake fallback remains. — Complete caller-first deletion prevents competing recovery writers.
- [Phase 18]: Durable persisted-context, operator-resolution, settlement, retry, and final-lease seams remain explicitly public and fake-paired. — Negative deletion gates are paired with positive replacement assertions.
- [Phase 19]: Initialize the singleton writer fence with insert-if-absent semantics so schema reapplication cannot reopen a closed cutover boundary.
- [Phase 19]: Classify only an unresolved run's sole legacy generation as authoritative; any multiple-generation history aborts before the first authority write.
- [Phase 19]: Reopen requires a deployed revision plus schema, fence, and authority postflights under an access-exclusive lock.
- [Phase 19]: Exact resolution UUID replay is idempotent only when mapping and remember intent are byte-for-byte equivalent. — Conflicting reuse must fail closed even after the run advances.
- [Phase 19]: New operator generations validate unresolved-name completeness and business-roster ownership while holding the target run row lock. — Commit serialization, not worker order or timestamps, selects payroll authority.
- [Phase 19]: Only authoritative preparation merges remember=true bindings into alias_candidates; superseded preparation is a bounded no-op. — Alias learning must follow the same generation that owns payroll authority.
- [Phase 19]: Delayed ingest returns only a bounded PipelineResult while its internal outcome enum keeps normal business classifications payload-free. — Queue handlers need a settlement-safe value boundary without exposing message or provider data.
- [Phase 19]: New-run and reply dedup keys are derived only from persisted run and email identifiers. — Identifier-only queue records preserve transport and payroll state separation.
- [Phase 19]: RFC duplicate replies rehydrate the stored inbound row and must pass consumption, same-run, awaiting-reply, and sender-ownership checks before enqueue. — Transport retry must not weaken reply authorization or reconstruct authority from a redelivered payload.

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

3 pending (see `.planning/todos/pending/`) — all low post-demo polish, carried as Deferred Items (below). Phase 15 closed two: **260623-01** (Phase 05 code-review Warnings + Info) and **260623-05** (Fixture-10 category-label mismatch — which turned out to be a real eval-chart defect, not cosmetics: the mislabel was reporting exact-match extraction as failing at 0.96 when it had never failed). Remaining pending todos: frontend progressive enhancement, paystub YTD columns, eval-chart restyle (all low).

### Blockers/Concerns

[Issues that affect future work]

_None open._ All v1/v2/v3 research flags and checkpoints were resolved as their phases shipped:

- 2026 Pub 15-T brackets — transcribed + unit-tested against the IRS PDF (Phase 3, v1.0).
- DeepSeek/Kimi model IDs — confirmed + pinned (Phase 2, v1.0).
- Real gateway payload/signing/reply-field — resolved with Resend at deploy (Phase 6, v1.0).
- Phase 02.1 name_matches DROP + `.env` decision-tier removal — applied + human-verified at the blocking checkpoint (v1.0).

Open items surfaced by v4 research, to resolve during phase planning (not blocking the roadmap):

- `operator_resume`'s `dedup_key` needs a discriminator (an operator may legitimately re-resolve a `needs_operator` run with a different mapping without an epoch bump) — resolve during Phase 19 planning.
- Resend's exact `Idempotency-Key` retention window (24h stated by research, flagged as not independently re-verified in this pass) — re-confirm before finalizing Phase 20's retry-ladder cap.
- The precise current Render 750-instance-hour/month cap should be re-confirmed against live Render docs before Phase 17 is planned in detail — the arithmetic is certain, the exact number should be pinned to a dated citation.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260621-11x | Fix order-dependent test test_no_db_connection_needed + add close_pool() for clean pool shutdown (IN-04) | 2026-06-21 | dc7ce86 | [260621-11x-fix-order-dependent-test-test-no-db-conn](./quick/260621-11x-fix-order-dependent-test-test-no-db-conn/) |
| 260713-oi6 | Harden clarify-round hours safety: fix drop-detection blind spot for the clarified employee, and surface cross-round hours changes to the operator | 2026-07-14 | 43ed368 | [260713-oi6-harden-clarify-round-hours-safety-fix-dr](./quick/260713-oi6-harden-clarify-round-hours-safety-fix-dr/) |
| 260709-uvz | Ignore personal system-design audit files and commit Phase 13 governance artifacts | 2026-07-10 | 56afd4f | [260709-uvz-ignore-personal-system-design-audit-file](./quick/260709-uvz-ignore-personal-system-design-audit-file/) |
| 260710-iw0 | Rewrite README for recruiter-first clarity and correct inaccurate claims | 2026-07-10 | 5b9eda1 | [260710-iw0-rewrite-readme-for-recruiter-first-clari](./quick/260710-iw0-rewrite-readme-for-recruiter-first-clari/) |

### Build-time guidance (author review at roadmap lock — pull these forward, do not let them sit in the last phase)

- **[Pull forward from P6 — threading round-trip] The one assumption fixtures structurally CANNOT test.** The EMAIL-01 stub always preserves Message-ID/In-Reply-To/References because we control them, so CLAR-02's resume looks bulletproof through P5 and only meets reality in P6. Real providers/mail apps vary in whether they surface those headers cleanly in the inbound webhook payload; if the provider drops or rewrites them, the resume path collapses onto brittle subject-line matching. **Action:** the moment the provider is picked (same moment as model-ID confirmation, before P2 ideally), send ONE real email, reply to it, and confirm the headers arrive intact. ~30 min; retires a last-phase landmine.
- **[Pull forward from P6 — deploy path] Prove Render+Supabase early.** P6 is otherwise the first time anything touches Render + Supabase-from-Render + the `$PORT` bind + cold-start-vs-inbound-webhook. **Action:** do a hello-world deploy during P1/P2 (just the webhook returning 200 and reading from Supabase via the pooler) so the deploy path is proven while there's slack. Leaves the fixture path unchanged.
- **[P3 — golden-test independence] The oracle must not be computed from the tables it checks.** If CALC-06's golden values are derived from the same transcribed `tax_tables_2026` module, a transcription error makes code and test wrong in the same direction and they tie out — the CALC-08 trap recreated in the oracle. **Action:** hand-compute golden paystubs from the IRS worksheet, or cross-check against an independent payroll calculator / the IRS's own worked examples, so the oracle is genuinely independent of the tables.
- **[P2 — internal sequencing] 19 reqs is the heaviest phase; "skeleton" hides that it's 18 thin pieces integrated.** Sequence INSIDE the phase: (a) clean happy path end-to-end first (POST fixture → all-clean match → process → thin calc → done — this alone lands the one-third end-to-end proof), then (b) the gate-block case, then (c) the clarify-reply-resume loop LAST (CLAR-03 re-entrancy is the trickiest sub-piece). The phase exit criteria must name all three behaviors so it can't be called done with resume half-wired.
- **[Slack management] Phase 3 is the safest place to absorb a slip.** The three core eval metrics (extraction, name-reconciliation, decision accuracy) measure the judgment layer and do NOT depend on P3 — only computed-payroll-correctness does. If Pub 15-T runs long, the spine (working slice + thesis metrics) still stands. Absorb schedule slip in P3, not P2 or P4.
- **[v4 — Phase 17 planning] Pump cadence vs. the 750h budget is a human decision already made in the design** (30-minute cadence, ~365 h/month, chosen over the 10-minute/at-the-cap option) — plan Phase 17 with that decision as a given, and write the duty-cycle arithmetic into the README as part of the phase's own deliverable, not as a follow-up.
- **[v4 — Phase 19 planning] The two-layer dedup argument (Svix event ID vs. RFC Message-ID) is subtle enough to need its own callout in the phase plan** — both layers are required (the ingest job's own retry is exactly the case that needs both), and that reasoning should survive into the eventual PR description, not just live in ARCHITECTURE.md.
- **[v4 — Phase 16 planning] Pull the `concurrency-proof.yml` generalization forward if convenient.** Research flags that generalizing the workflow (removing the hard-coded single test file) is a prerequisite for Phase 21 and "probably deserves to be pulled forward into Phase 2" (this roadmap's Phase 16) so the queue's own tests run in CI from the start rather than accumulating ungated until Phase 21.

## Deferred Items

Acknowledged and deferred at the **v3** milestone close (2026-07-13). All benign; the v3 milestone
audit independently dispositioned each as non-blocking. Phase 15 CLOSED the two that mattered
(260623-01 Phase-05 review warnings, 260623-05 fixture-10 label — the latter turned out to be a real
eval-chart defect, not cosmetics).

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| quick_task | 260621-11x-fix-order-dependent-test-test-no-db-conn | done (stale pointer — work shipped, tracking file never closed) | v1.0 / v2 / v3 |
| todo | Frontend progressive enhancement (no build step) — post-demo polish | deferred | v1.0 / v2 / v3 |
| todo | Paystub YTD columns | deferred | v1.0 / v2 / v3 |
| todo | Eval chart restyle (away from matplotlib look) | deferred | v1.0 / v2 / v3 |
| validation | Phase 12 has no VALIDATION.md; Phase 15's is an unfilled draft template | deferred (Nyquist process artifact, not code debt) | v3 |
| uat | Phase 03 HUMAN-UAT | passed (no open scenarios) | v1.0 |
| uat | Phase 05 HUMAN-UAT | passed (no open scenarios) | v1.0 |

*The 2 UAT "gaps" are scanner false positives — both passed with zero pending scenarios.*

## Session Continuity

Last session: 2026-07-17T00:42:08.271Z
Stopped at: Completed 19-03-PLAN.md
Resume file: None

## Operator Next Steps

- Discuss the first v4 phase with `/gsd-discuss-phase 16` (Queue Substrate & Unblocked Webhook)
