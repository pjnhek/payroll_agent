---
phase: 9
reviewers: [codex, claude-insession]
reviewed_at: 2026-07-03T00:00:00Z
plans_reviewed: [09-01-PLAN.md, 09-02-PLAN.md, 09-03-PLAN.md, 09-04-PLAN.md]
reviewer_models:
  codex: gpt-5.5
  claude-insession: claude-fable-5
---

# Cross-AI Plan Review — Phase 9

## Codex Review

## Summary

The plans are strong on the basic transaction strategy, but I would not approve them as-is. The biggest risks are in the exact call flow: 09-03 can accidentally create a new run for a clarification reply, 09-02 overstates `_deliver` atomicity because `gateway.send_outbound()` already marks the email row `sent` before `_deliver`’s planned transaction, and 09-04 still undercounts live in-flight latency because clarification drafting and multi-extraction resume paths are not fully bounded.

## Strengths

- The repo-level `conn=` seam is real and suitable: helpers use `_conn_ctx` and no-op inner transactions when a caller passes `conn` ([repo.py](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo.py:125>)).
- `insert_inbound_email()` really returns `(None, False)` on conflict, so the corrected `find_run_by_message_id(message_id)` plan is necessary and well-founded ([repo.py](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo.py:140>)).
- The planned sweep scope `{received, extracting, computed}` is consistent with the status enum and avoids parked statuses ([status.py](</Users/pnhek/usf msds/github/payroll_agent/app/models/status.py:17>)).
- The plans correctly avoid DB transactions around LLM/provider calls in principle.
- The requirement for real Postgres integration tests for rollback/race behavior is correct; `FakeConnection.transaction()` cannot prove rollback.

## Concerns

- **HIGH — 09-03 can break reply routing.** Current `inbound()` routes header-bearing replies after dedup but before sender lookup and `create_run()` ([main.py](</Users/pnhek/usf msds/github/payroll_agent/app/main.py:336>), [main.py](</Users/pnhek/usf msds/github/payroll_agent/app/main.py:342>)). The plan says the transaction wraps `insert_inbound_email + find_business_by_sender + create_run`, then keeps `_route_reply` after the duplicate check. If implemented literally, a clarification reply can create a brand-new run before `_route_reply()` handles it.

- **HIGH — 09-02’s delivery crash semantics do not match live gateway code.** `gateway.send_outbound()` inserts `reserved`, calls Resend, then flips the row to `sent` before returning ([gateway.py](</Users/pnhek/usf msds/github/payroll_agent/app/email/gateway.py:239>), [gateway.py](</Users/pnhek/usf msds/github/payroll_agent/app/email/gateway.py:308>)). `_deliver`’s planned finalize transaction therefore cannot atomically include the email sent-state flip. A crash after gateway returns but before alias/status finalize leaves `email_messages.send_state='sent'` and run `approved`; retry will hit `_deliver`’s already-sent guard ([orchestrator.py](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:1197>)) and can skip alias learning unless that path is changed.

- **HIGH — 09-04 still underbounds the recovery threshold.** `call_structured()` is used not only for extraction but also suggestion (`suggest_employees()` calls `call_structured("draft", ...)`) ([suggest.py](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/suggest.py:81>)). `compose_clarification()` uses `call_text()` with no timeout ([compose_email.py](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/compose_email.py:167>)). Resume Round 2 can run two extractions before the next DB write ([orchestrator.py](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:374>), [orchestrator.py](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:379>)). A threshold based only on `_STRUCTURED_TIMEOUT_S * 2` is not safe.

- **MEDIUM — sweep becomes another status writer.** `repo.py` currently documents only `set_status` and `claim_status` as status writers ([repo.py](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo.py:16>), [repo.py](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo.py:337>)). `sweep_stranded_runs()` directly updating `status='error'` is reasonable, but the invariant/docs/tests need to name it as a sanctioned CAS exception.

- **MEDIUM — reply-derived stranded runs are not fully specified.** `_defer_field_regression_clarification()` can persist `clarified_fields` during `resume_pipeline` ([orchestrator.py](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:744>)); if swept to ERROR, the existing retrigger route schedules `_run_pipeline`, not `_resume_pipeline` ([main.py](</Users/pnhek/usf msds/github/payroll_agent/app/main.py:611>)). That may restart from the original inbound email and lose the reply context.

- **MEDIUM — SC2 test shape may not be isolated.** A threaded TestClient race will run FastAPI BackgroundTasks synchronously, so the winner may launch the real pipeline and LLM work unless `_run_pipeline` is monkeypatched or the ingest logic is extracted for direct testing.

- **LOW — sweep `error_detail` should not literally contain `{status}`.** Use SQL concatenation from the pre-update `status`, e.g. `... || status`, so the operator sees the swept-from state.

## Suggestions

- Refactor 09-03 around a small transactional ingest decision helper: insert inbound, classify duplicate/reply/unknown/new-run inside one transaction, but schedule `_run_pipeline`/`_resume_pipeline` only after commit.
- Either split `gateway.send_outbound()` so `_deliver` can mark sent in the same finalize transaction as alias/status, or explicitly accept the existing sent-row-before-run-status window and make the already-sent guard perform idempotent alias finalization before `SENT → RECONCILED`.
- Bound all in-flight external gaps used by the sweep threshold: `call_structured`, `compose_clarification`’s `call_text`, and ideally provider send behavior. Then size the threshold to the longest real sequence between DB writes, not a single structured call.
- Make SC2 and SC3 tests avoid real LLM/provider calls by monkeypatching `_run_pipeline`, `_resume_pipeline`, and/or send functions while still using real Postgres for the race/rollback property.
- For SC3, exercise the actual retrigger route or route function, not just `repo.claim_status(ERROR, RECEIVED)`, so the recovery path is proven end to end.

## Risk Assessment

**Overall risk: HIGH.** The plans have the right architectural direction, but several claimed guarantees do not follow from the live code as written. The reply-routing transaction shape and delivery finalize mismatch are correctness risks in money-moving state transitions, and the recovery threshold remains unsafe unless all LLM/provider gaps between DB writes are bounded and counted.

---

## Claude (in-session) Review

One additional finding, discovered while tracing the multi-round clarification flow end-to-end and verified against live source (not present in the Codex review):

- **HIGH — Multi-round context loss: a paid→paid correction stated in an intermediate reply and not restated later is silently discarded (overpay).** Verified chain:
  1. `clean_body` strips quoted reply history (">"-lines, "On … wrote:" blocks) at ingest, before persisting (`app/email/clean.py:35-56`) — so thread quoting cannot preserve intermediate replies.
  2. `load_source_email` returns only the ingest-time ORIGINAL cleaned body (`app/db/repo.py:279`).
  3. `_combined_context_email` builds the resume extraction context as ORIGINAL + LATEST reply only (`app/pipeline/orchestrator.py:772`) — intermediate replies never accumulate into the context.
  4. `detect_field_regression` only fires on paid→unpaid (`app/pipeline/validate.py:147`); a paid→paid value change (40→30) is invisible to it.
  5. The four-outcome classifier only touches fields marked `asked`; `backfill_extracted` only fills `None` fields.

  Concrete failure: Round-1 reply says "Maria worked 30, not 40" (extraction persists 30). A field-regression clarification triggers Round 2 for unrelated fields; the Round-2 reply answers only those. Round-2 combined extraction re-reads the ORIGINAL body → regular=40 again; 40 is paid → no backfill, not asked → no override, 40 vs 40 → no regression. The paystub pays 40; the client said 30. Silent overpay with no gate, no clarification, no operator visibility of the discrepancy.

  Fix directions (planner to choose): (a) accumulate reply bodies into the resume context (e.g., append each reply to the persisted source context, or store a reply log and combine original + ALL replies at `_combined_context_email`); or (b) diff the new combined extraction against the LAST PERSISTED extraction (not just the Round-0 snapshot) and treat paid→paid changes on non-asked fields across rounds as a clarify-worthy discrepancy; or (c) at minimum, an integration fixture proving current behavior + a documented known-edge. Option (a) is the smallest-surface fix and matches the existing "lossless combined extraction" (FIX 4) intent — the current implementation is lossless for round 1 only.

  Scope note: this touches `resume_pipeline`/`_combined_context_email`/`load_source_email` — the same resume path Phase 9's 09-02 already rewires — and it is MONEY-path (overpay class, same family as the Phase 7.5 CR-01/R2 findings). If the planner judges it out of Phase 9's atomicity scope, it must be recorded as an explicit deferred known-edge with the fixture (option c) still landing in Phase 9's test set, not silently dropped.

---

## Consensus Summary

Single external reviewer (Codex / gpt-5.5) — no cross-reviewer consensus available. Codex verified plan claims against live source per the review instructions (file:line citations throughout).

### Agreed Strengths
(single reviewer; its verified strengths)
- The `conn=` / `_conn_ctx` seam in `app/db/repo.py:125` is real and suitable — the transaction-wiring approach is sound.
- `find_run_by_message_id` correction is necessary and well-founded (`insert_inbound_email` really returns `(None, False)` on conflict).
- Sweep scope `{received, extracting, computed}` is consistent with the status enum.
- Plans correctly keep DB transactions off LLM/provider calls in principle.
- Real-Postgres integration tests for rollback/race are the right call; `FakeConnection` cannot prove rollback.

### Agreed Concerns
(single reviewer; its HIGH findings, all source-verified)
1. **HIGH — 09-03 can break reply routing:** wrapping `insert_inbound_email + find_business_by_sender + create_run` in one transaction while keeping `_route_reply` after the duplicate check means a clarification reply (header-bearing, non-duplicate) could create a brand-new run before `_route_reply` handles it (`app/main.py:336, 342`).
2. **HIGH — 09-02's `_deliver` crash semantics don't match the live gateway:** `gateway.send_outbound()` already flips the email row to `sent` before returning (`app/email/gateway.py:239, 308`), so the finalize transaction cannot atomically include the sent-state flip; a crash after gateway-return but before finalize leaves `send_state='sent'` + run `approved`, and the already-sent guard (`orchestrator.py:1197`) can skip alias learning on retry.
3. **HIGH — 09-04 still underbounds the recovery threshold:** `call_structured` is also used by `suggest_employees` (`suggest.py:81`), `compose_clarification` uses `call_text` with no timeout (`compose_email.py:167`), and resume Round 2 runs two extractions before the next DB write (`orchestrator.py:374, 379`). `_STRUCTURED_TIMEOUT_S × 2` is not the longest real gap between DB writes.

### Divergent Views
None conflicting. The two reviews are complementary: Codex's three HIGHs are call-flow gaps in the plans' own claims (reply routing order, gateway send-state flip, threshold undercount); the in-session HIGH (multi-round context loss) is a live-code money bug adjacent to the same resume path 09-02 rewires. Note: the in-house plan-checker passed these plans after 3 rounds; all four HIGH findings are in areas the checker did not re-derive from live call flow — consistent with the project's prior experience that external arg-flow tracing catches what prose review misses.

---

## Codex Review — Round 2 (re-review of the revised 5-plan set, 2026-07-03)

**Per-Prior-Finding Verdicts**

| Finding | Disposition claimed | Verdict |
|---|---|---|
| 09-03 reply routing could create a new run before `_route_reply()` | Move reply classification inside the ingest transaction before `create_run` | **CLOSED.** Live header finders already accept `conn=` ([repo.py](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo.py:1190>), [repo.py](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo.py:1217>)), and current risky order is real: `_route_reply` precedes `create_run` today ([main.py](</Users/pnhek/usf msds/github/payroll_agent/app/main.py:336>), [main.py](</Users/pnhek/usf msds/github/payroll_agent/app/main.py:350>)). The revised ingest-decision shape closes it if implemented as written. |
| 09-02 `_deliver` overclaimed atomicity because gateway flips `sent` internally | Accept sent-row-before-finalize window; harden already-sent guard to run alias finalization before statuses | **CLOSED.** Gateway really writes reserved, sends, then flips `sent` before returning ([gateway.py](</Users/pnhek/usf msds/github/payroll_agent/app/email/gateway.py:239>), [gateway.py](</Users/pnhek/usf msds/github/payroll_agent/app/email/gateway.py:295>), [gateway.py](</Users/pnhek/usf msds/github/payroll_agent/app/email/gateway.py:309>)). Current guard skips alias writes ([orchestrator.py](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:1197>)); revised retry-over-sent alias attempt closes the specific loss. |
| 09-04 recovery threshold undercounted live LLM gaps | Bound `call_structured`, add `compose_clarification` `call_text(timeout_s=...)`, count Round-2 double extraction | **STILL OPEN.** The revised plan suppresses OpenAI retries only for `call_structured`. Live `call_text` builds `OpenAI(..., **client_kwargs)` with `timeout` only, no `max_retries=0` ([client.py](</Users/pnhek/usf msds/github/payroll_agent/app/llm/client.py:182>)); local OpenAI defaults `max_retries=2` (`.venv/.../openai/_constants.py:10`, `_client.py:134`). So `compose_clarification` remains `timeout_s × 3` unless `call_text` is also changed or the threshold counts it. The disposition’s threshold math still undercounts. |
| Sweep becomes a third status writer | Document `sweep_stranded_runs` as sanctioned third writer | **CLOSED.** Current doc says two writers ([repo.py](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo.py:16>)); 09-01 explicitly updates this and pins CAS shape. |
| Reply-derived stranded runs lose reply context on retrigger | Explicitly accept/document limitation | **CLOSED AS DEFERRED, NOT FIXED.** Live risk remains: `_defer_field_regression_clarification` writes `clarified_fields` ([orchestrator.py](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:744>)), while retrigger schedules `_run_pipeline`, not `_resume_pipeline` ([main.py](</Users/pnhek/usf msds/github/payroll_agent/app/main.py:611>)). The revised plan now documents this accepted limitation. |
| SC2 race test could launch real pipeline/LLM | Monkeypatch `_run_pipeline`/`_resume_pipeline` in race test | **CLOSED.** This directly addresses TestClient synchronous BackgroundTasks behavior noted in current docs ([main.py](</Users/pnhek/usf msds/github/payroll_agent/app/main.py:34>)). |
| Sweep `error_detail` literal `{status}` | Use SQL concatenation with old row status | **CLOSED.** 09-01 specifies `error_detail = %s || status`, which is the correct old-value capture shape. |
| Multi-round context loss | Disposition (c): documented known-edge fixture + deferred entry | **CLOSED AS DEFERRED, NOT FIXED.** Live chain is real: reply cleaning drops quoted history ([clean.py](</Users/pnhek/usf msds/github/payroll_agent/app/email/clean.py:50>)), source email loads only original body ([repo.py](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo.py:279>)), combined context uses original + latest reply only ([orchestrator.py](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:779>)), and regression detects only paid→unpaid ([validate.py](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/validate.py:143>)). 09-05’s fixture disposition is adequate for deferral. |

**New Concerns**

- **MEDIUM — 09-05 known-edge fixture may be skipped in the normal offline suite.** `tests/test_resume_pipeline.py` has a module-level skip unless shell `DATABASE_URL` is set ([test_resume_pipeline.py](</Users/pnhek/usf msds/github/payroll_agent/tests/test_resume_pipeline.py:41>)). 09-05 says the fixture is hermetic and should run with `-m "not integration"`, but this skip prevents that in DB-less environments.

- **MEDIUM — 09-03 SC2 race test will 400 unless it enables unsigned fixtures or signs the webhook.** `inbound()` rejects unsigned requests when `ALLOW_UNSIGNED_FIXTURES` is false ([main.py](</Users/pnhek/usf msds/github/payroll_agent/app/main.py:277>)); the default is false ([config.py](</Users/pnhek/usf msds/github/payroll_agent/app/config.py:59>)). Existing webhook tests explicitly set the env var ([test_webhook.py](</Users/pnhek/usf msds/github/payroll_agent/tests/test_webhook.py:31>)); the new race test plan does not say to.

- **MEDIUM — SC3 is not truly end-to-end as specified.** 09-04’s test plan calls `repo.claim_status(ERROR, RECEIVED)` directly, bypassing the actual `POST /runs/{run_id}/retrigger` route and its background scheduling ([main.py](</Users/pnhek/usf msds/github/payroll_agent/app/main.py:534>), [main.py](</Users/pnhek/usf msds/github/payroll_agent/app/main.py:611>)). It proves claimability, not the operator recovery path.

- **LOW — Offline transaction-shape tests may overclaim.** Current `FakeTransaction` records no enter/exit boundaries ([conftest.py](</Users/pnhek/usf msds/github/payroll_agent/tests/conftest.py:104>)); `FakeConnection` records SQL only ([conftest.py](</Users/pnhek/usf msds/github/payroll_agent/tests/conftest.py:144>)). Use AST checks or enhance the fake if tests claim a call was inside a transaction.

**Risk Assessment**

Overall risk: **HIGH as written**, because one prior HIGH remains open: `call_text` still has the OpenAI retry layer unless the plan either passes `max_retries=0` in `call_text` or counts `timeout_s × 3` in `STALE_THRESHOLD_SECONDS`.

**NO-GO** until 09-04 is revised for `call_text` retry math. The transaction and webhook ordering revisions are otherwise directionally sound.

---

# Cross-AI CODE Review — Phase 9 (post-execution, post-gap-closure)

**Reviewer:** codex (gpt-5.5, codex-cli 0.135.0, read-only sandbox) | **Reviewed:** 2026-07-04, at commit `fd62a04` (after 09-06 gap closure + WR-03/WR-07 fixes) | **Confirming round:** claude-fable-5 (in-session, traced each finding against live source)

## Codex verdict: 1 critical, 2 warning

### CX-01 — Multi-round resume can discard an intermediate paid-hours correction (CRITICAL per Codex)

**Confirming-round disposition: KNOWN — duplicate of the 09-05 deferred finding. Not a new bug.**

Codex's trace (resume rebuilds extraction from original email + current reply only; a Round-1 paid-to-paid correction to a *non-asked* field is silently reverted by Round-2's combined re-extraction; e.g. corrected 40→30 regular hours pays 40 again, $185 gross overpay at $18.50/hr) is exactly the multi-round context-loss finding that plan 09-05 recorded WITHOUT fixing: proven by the known-edge fixture `tests/test_multiround_context_edge.py` and logged in 09-CONTEXT.md as deferred to a future MONEY-class phase (fix direction: accumulate reply bodies or diff against last-persisted extraction). Independent rediscovery by a second model is strong validation that the deferred finding is real and CRITICAL-class — it should stay at the top of the future MONEY-phase queue.

### CX-02 — Recovery paths do not fence off old workers (WARNING)

**Confirming-round disposition: PLAUSIBLE — new advisory, not previously documented.**

After `sweep_stranded_runs` marks a stale `extracting` run `error`, or retrigger moves `approved → received`, a still-live old worker's later writes use plain `set_status WHERE id = %s` (no lease/attempt-token/CAS on the finalize side), so the zombie can overwrite the recovered state (`_clarify` unconditionally writes `awaiting_reply`; a stalled `_deliver` can finalize `sent/reconciled` over a retriggered run). Requires a worker outlasting the 15-min sweep threshold (e.g. `gateway.send_outbound()` has no explicit provider timeout) or a concurrent manual retrigger. Codex confidence medium-high; operationally unlikely at demo scale but a genuine design gap if this ever runs multi-worker. Candidate fix: attempt-token column checked by a CAS variant of `set_status` on finalize writes — belongs with the Phase 10 concurrency work.

### CX-03 — Prior `carried_forward` outcomes can be reopened as `asked` (WARNING)

**Confirming-round disposition: CONFIRMED against live source — new real bug. Also corrects one over-claim in 09-REVIEW.md.**

Trace (verified in-session):
- `orchestrator.py:322-326` — `_resolved_by_name` includes only `confirmed_dropped`/`client_supplied`, omitting the third terminal `carried_forward`, even though the SET A comment at line 488 says it holds "prior terminals" (intent: all of them).
- Within round N, `carried_forward` IS suppressed via `newly_classified` (lines 492-494) — but in round N+1 it is in neither set, so `detect_field_regression` can re-emit the same paid-to-absent drop.
- `orchestrator.py:759` — `clarified.setdefault(emp_id, {})[field] = "asked"`: `setdefault` protects only the outer dict; the field-level assignment OVERWRITES the terminal `carried_forward` back to `asked`. (09-REVIEW.md's claim that the deferred helper "only ADDS new asked entries, never mutating the terminals" is wrong at field level for re-detected fields.)
- Failure scenario: OT classified `carried_forward` in Round 2; a Round-3 reply answers a different field and is silent on OT; snapshot still has positive OT → re-flagged, terminal flipped to `asked`, run re-asks a resolved question — and combined with WR-05's round-blind send guard, the second same-purpose clarification is silently never sent, parking the run at `awaiting_reply` unrecoverable by sweep.
- Minimal fix candidate: add `"carried_forward"` to the tuple at line 325 — but this interacts with the WR-05/WR-06 cluster (`is_round_2 = bool(clarified)`, SET B intentionally excludes carried_forward for backfill) and should be designed with them, per the 09-REVIEW-FIX.md skip rationale for that cluster.

## Verified sound by Codex (independent confirmation of the gap fixes)

`_run_stages` persist writes are one transaction with status last; the `_deliver` alias write is isolated by a real nested SAVEPOINT; `link_email_to_run` (WR-03 fix) does not conflict with `uq_email_run_purpose` (inbound rows keep `purpose=NULL`) and routing queries filter `direction='outbound'`.

## Net effect

Phase 9's shipped mechanisms (DATA-01/02/03) survive the external review — no new critical in the phase's own scope. The one CRITICAL is the pre-existing, already-recorded 09-05 deferred finding. New follow-ups for the backlog: CX-03 (confirmed, pairs with WR-05/WR-06 cluster) and CX-02 (pairs with Phase 10 concurrency work).
