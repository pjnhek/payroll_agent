---
phase: 2
reviewers: [codex]
reviewed_at: 2026-06-21T09:32:08.061Z
plans_reviewed: [02-01-PLAN.md, 02-02-PLAN.md, 02-03-PLAN.md, 02-04-PLAN.md]
reviewer_model: gpt-5.5 (xhigh reasoning)
---

# Cross-AI Plan Review — Phase 2 (Walking Skeleton)

## Codex Review (gpt-5.5, xhigh)

**Summary**

The four-plan sequence is strong and mostly phase-faithful. It preserves the locked build order, keeps the code gate in `decide.py`, separates mocked proof from live demo proof, and avoids pulling Phase 3/5 work forward. The main risks are not scope gaps; they are contract/persistence ambiguities around reply threading, outbound Message-ID storage, typed extraction validation, and whether the clarification reply can resume without losing original hours.

**02-01 Strengths**

- Clean substrate-first plan: LLM wrapper, gateway, repo, config, marker, and reconciliation persistence are the right Wave 1 seams.
- Correctly avoids `.parse()` and uses `json_object` + Pydantic + one reflective retry.
- Dedicated `payroll_runs.reconciliation JSONB` is the cleaner choice for Phase 4/5 reuse.
- Good security posture around parameterized SQL and no new package names.

**02-01 Concerns**

- **MEDIUM:** `app/db/repo.py` is under-specified for later consumers. Plans 02-04 need sender lookup, run loading, outbound Message-ID retrieval/storage, late-reply lookup, and failure-reason persistence, but Plan 01 only commits the narrower base helpers.
- **MEDIUM:** `send_outbound` assumes `email_messages` has fields such as `to_addr`, `direction`, and `body_text`; the plan should explicitly align with the real Phase 1 schema or add migrations.
- **LOW:** `requirements.txt` is listed in `files_modified`, but the plan says no dependency changes. That creates noise for implementers.

**02-01 Suggestions**

- Add explicit repo helper names for later waves: `find_business_by_sender`, `load_run`, `load_source_email`, `record_run_error`, `store_clarification_message_id` or explicitly state outbound IDs are stored only via linked `email_messages`.
- Make the schema alignment a checklist item before implementing gateway inserts.
- Remove `requirements.txt` from `files_modified` unless it will actually change.

**02-01 Risk Assessment**

**MEDIUM.** The architecture is sound, but later waves depend heavily on repo semantics that are not fully pinned here.

**02-02 Strengths**

- Strong MVP slice: clean fixture reaches `awaiting_approval` through the real spine.
- Good insistence that stages are pure and the orchestrator branches only on `final_action`.
- The gate tests directly cover the central thesis: sub-0.8 confidence blocks even when `model_action == process`.
- Good restraint on Phase 2 body cleaning: no new parser dependency for authored fixtures.

**02-02 Concerns**

- **HIGH:** `validate.py` is expected to emit `non_numeric`, but if `ExtractedEmployee` fields are already `Decimal | None`, non-numeric values will fail Pydantic validation before `validate(extracted)` can see them. This creates a mismatch with LLM-06.
- **MEDIUM:** `net_pay_label="pre-federal"` may not fit the existing `PaystubLineItem` contract if it is `extra="forbid"`. The plan should avoid inventing fields unless the model contract already supports them.
- **MEDIUM:** “orchestrator owns legal transitions” is asserted, but no transition guard/table is planned. `repo.set_status` alone can still allow illegal transitions.
- **MEDIUM:** Error reason persistence is required, but the storage location is not defined.
- **LOW:** The temporary `request_clarification -> needs_clarification` branch is acceptable for the clean slice, but it should be clearly marked as superseded by Plan 03.

**02-02 Suggestions**

- Decide how numeric validation works: either accept Pydantic parse failure as extraction-stage error, or introduce a raw extraction schema that lets `validate.py` classify `non_numeric`.
- Keep “pre-federal” as a display/serialization label outside `PaystubLineItem` unless the contract already has a field.
- Add an orchestrator transition helper such as `transition(run_id, from_statuses, to_status, reason=None)`.
- Define where `ERROR` reason is stored before Task 3.

**02-02 Risk Assessment**

**MEDIUM.** It should deliver the clean path, but typed validation and status-transition enforcement need tightening.

**02-03 Strengths**

- Correctly builds the gate-block story after the clean path.
- Extending the existing `check_one_to_one` function is a good sequencing choice.
- The two distinct mocks for reconcile and advisory decision are important and well specified.
- Clarification drafting has the right fallback behavior so a draft failure does not strand the run.

**02-03 Concerns**

- **HIGH:** Layer-2 reconcile needs an explicit Pydantic wrapper model for `list[NameMatchResult]`; `call_structured(..., response_model=list[NameMatchResult])` will not work if the wrapper expects `.model_validate_json`.
- **HIGH:** CLAR-01 says the outbound Message-ID is “stored on the run,” but no run column or exact storage contract is defined. Plan 04 later uses linked `email_messages`, so the plans conflict.
- **MEDIUM:** The hero mock allows `match_type="unknown"`. That weakens the intended narrative: the cleanest demo is `matched_employee_id=David Reyes`, `match_type="llm_typo"`, `confidence=0.6`, `model_action="process"`.
- **MEDIUM:** Clarification send needs a precise recipient source: original sender vs business contact email, and this should be loaded through repo.

**02-03 Suggestions**

- Add `NameReconciliationResponse(BaseModel): matches: list[NameMatchResult]`.
- Resolve Message-ID storage: either add `payroll_runs.clarification_message_id` or explicitly state the canonical anchor is `email_messages(direction='outbound', run_id=...)`.
- Force the hero fixture/mock to use `llm_typo` with a matched employee and sub-threshold confidence.
- Add a test that the clarification email is addressed to the source email/business contact.

**02-03 Risk Assessment**

**MEDIUM-HIGH.** The gate behavior is well covered, but Message-ID persistence and reconcile response shape are likely implementation traps.

**02-04 Strengths**

- Correctly leaves clarify→reply→resume until last.
- Good header-chain priority and explicit `awaiting_reply` restriction.
- The reply fixture substitution assertion is excellent; it prevents false-positive no-match tests.
- The manual live hero gate is the right standard for proving the demo, not just the code.

**02-04 Concerns**

- **HIGH:** Reply routing appears to happen before re-checking sender authorization against the matched run/business. That can bypass INGEST-03 on replies.
- **HIGH:** A clarification reply often contains only the answer, not the full payroll submission. If resume extraction overwrites `extracted_data` using only the reply body, the run can lose original hours. The plan must define either “client must resend full corrected payroll” or “extract from original cleaned body + reply body context.”
- **MEDIUM:** `find_run_for_reply` restricted to `awaiting_reply` cannot also detect and log late replies to resolved runs unless there is a second any-status lookup.
- **MEDIUM:** The live tuning loop may need edits to `app/llm/prompts/reconcile.py` or `fixtures/gate_block_hero.json`, but those files are not in `files_modified`.
- **LOW:** The live-vs-mock marker is still vague. If it is required, choose structured log field vs schema column now.

**02-04 Suggestions**

- After header match, require `reply.from_addr` to match the matched run’s business contact or original sender.
- Feed extraction a resume context containing both the original cleaned inbound body and the clarification reply, then overwrite `extracted_data` with the new full result.
- Split lookup into `find_awaiting_reply_for_header` and `find_any_run_for_header` so late replies are observable.
- Add prompt/fixture files to `files_modified` for the live tuning task.
- Use a structured log field for the live-vs-mock marker unless a schema column is explicitly needed.

**02-04 Risk Assessment**

**HIGH.** The threading design is close, but sender revalidation and partial-reply semantics are load-bearing for a safe resume loop.

**Overall Risk**

**MEDIUM-HIGH.** The plans do achieve the phase’s core intent on paper: mocked clean path, mocked code-gated block, reply resume, and a separate live hero exit gate. The main fixes before execution should be: define outbound Message-ID storage, make reply resume preserve original context, revalidate reply sender, clarify typed validation limits, and add an explicit reconcile response wrapper. These are bounded changes and do not expand Phase 2 scope.

---

## Consensus Summary

Single external reviewer (Codex/gpt-5.5 at xhigh). The plans are assessed as phase-faithful and structurally strong; the flagged risks are contract/persistence ambiguities, not scope gaps. Orchestrator overall risk: MEDIUM-HIGH, with the threading/resume loop (Plan 04) the highest-risk area.

### Agreed Strengths
- Locked build order (a→b→c) preserved; gate lives in `decide.py`; mocked-proof vs live-demo-proof cleanly separated; no Phase 3/5 work pulled forward.
- Central thesis directly tested: sub-0.8 confidence blocks even when `model_action == process`, with two distinct mocks.
- Good restraint: no new reply-parser dependency; dedicated `reconciliation` JSONB; reply-fixture substitution assertion prevents false-positive no-match tests.

### Agreed Concerns (highest priority — verified against the real codebase)
- **[HIGH — confirmed] `non_numeric` validation is unreachable through the typed path.** `ExtractedEmployee` hours are `Decimal | None` + `extra="forbid"` — a non-numeric value raises `ValidationError` at extraction parse time before `validate.py` runs. LLM-06's `non_numeric` issue type needs a defined path (treat parse failure as an extraction-stage error feeding the reflective retry, OR document that `non_numeric` manifests as the retry/error path, not a `validate.py` issue).
- **[HIGH — confirmed] `PaystubLineItem` is `extra="forbid"`** — a `net_pay_label="pre-federal"` field cannot be added to the contract. The "pre-federal" labeling must be a display/serialization concern outside `PaystubLineItem` (or use an existing field), not an invented model field.
- **[HIGH — partly resolved by schema] Outbound Message-ID storage.** `email_messages` already has `run_id`, `direction`, `message_id`, `in_reply_to`, `references_header` — so the canonical anchor IS `email_messages(direction='outbound', run_id=...)`. No `payroll_runs.clarification_message_id` column is needed; 02-03 ("stored on the run") and 02-04 ("linked email_messages") must be reconciled to this single anchor explicitly.
- **[HIGH — confirmed, correctness] Partial-reply overwrite (Plan 04).** A clarification reply often contains only the answer, not the full payroll. Overwriting `extracted_data` from the reply body alone loses original hours. Resume must extract from (original cleaned body + reply body) context, then overwrite with the full result.
- **[HIGH — confirmed, safety] Reply sender revalidation (Plan 04).** Reply routing must re-assert sender authorization (INGEST-03) against the matched run's business/original sender, or a spoofed reply on a header match bypasses access control.
- **[HIGH — confirmed] Reconcile response wrapper (Plan 03).** `call_structured(response_model=list[NameMatchResult])` won't work with a Pydantic `.model_validate_json` client — add a `NameReconciliationResponse(BaseModel){ matches: list[NameMatchResult] }` wrapper.
- **[MEDIUM] Error-reason persistence (Plan 02):** `payroll_runs` has no `error_reason` column — define where the failure reason is stored before the orchestrator error path is built.
- **[MEDIUM] Hero mock narrative (Plan 03):** prefer `match_type="llm_typo"` + `matched_employee_id=David Reyes` + `confidence=0.6` over `match_type="unknown"` — the cleanest "model willing, code said no" story.
- **[MEDIUM] Repo helper completeness (Plan 01):** name the later-wave helpers (sender lookup, run load, late-reply lookup, error persistence) so Wave 1 commits the full repo surface.
- **[MEDIUM] Late-reply observability (Plan 04):** a lookup restricted to `awaiting_reply` can't also log late replies to resolved runs — needs a second any-status lookup.
- **[LOW] `requirements.txt` in 02-01 `files_modified`** despite "no dependency changes" — remove the noise.
- **[LOW] Live-vs-mock marker** still vague — pick a structured log field now (NICE-TO-HAVE).

### Divergent Views
- Single reviewer — no inter-reviewer divergence to report.

---

## Codex Review — ROUND 2 (re-review after round-1 fixes, gpt-5.5 xhigh)

**Prior Findings**

1. **CONFIRMED-FIXED** — `non_numeric` is now extraction `ValidationError` → one retry → `ERROR`, and `validate.py` asserts typed `Extracted` never yields `non_numeric`. See `02-02 Task 2`.
2. **CONFIRMED-FIXED** — pre-federal net is a `PRE_FEDERAL_NET_LABEL`/README/display concern, not a `PaystubLineItem` field. See `02-02 Tasks 3-4`.
3. **CONFIRMED-FIXED** — outbound clarification Message-ID anchor is `email_messages(direction='outbound', run_id)`, with no `payroll_runs` column. See `02-01 Task 3`, `02-03 Task 2`.
4. **CONFIRMED-FIXED** — resume re-extracts over original cleaned inbound body plus reply body; partial-reply preservation is tested. See `02-04 Task 1`.
5. **CONFIRMED-FIXED** — reply sender is revalidated against the matched run’s business before resume. See `02-04 Task 1`.
6. **CONFIRMED-FIXED** — layer-2 reconcile uses `NameReconciliationResponse(BaseModel){matches: ...}`. See `02-03 Task 1`.
7. **CONFIRMED-FIXED** — `payroll_runs.error_reason` plus `repo.record_run_error` are planned and consumed by orchestrator error handling. See `02-01 Tasks 1/3`, `02-02 Task 3`.
8. **CONFIRMED-FIXED** — hero mock is now `llm_typo`, David Reyes employee id, confidence `0.6`, decision `model_action="process"`. See `02-03 Task 3`.
9. **CONFIRMED-FIXED** — 02-01 now commits the full repo helper surface. See `02-01 Task 3`.
10. **CONFIRMED-FIXED** — late-reply observability uses separate awaiting-only and any-status header lookups. See `02-01 Task 3`, `02-04 Task 1`.
11. **CONFIRMED-FIXED** — `requirements.txt` is removed from 02-01 `files_modified`; plan installs only. See `02-01 Task 1`.
12. **PARTIALLY-FIXED** — the marker is correctly specified as `source="live"/"mock"` structured logging outside `Decision`. Remaining gap: the concrete implementation point/source derivation is still vague in `02-04 Task 3`.

**New Concerns**

- **HIGH — 02-02 Task 2:** `extract(email, roster, *, llm) -> Extracted` forbids `run_id`, but the authoritative `Extracted` contract requires `run_id`. This either forces the LLM to invent/echo a trusted run id or makes validation fail. Fix by passing `run_id` as code-owned input and constructing/overwriting `Extracted.run_id`, or use an LLM payload model without `run_id`.

- **MEDIUM — 02-01 Task 3:** `persist_decision(run_id, Decision, final_status)` conflicts with “`set_status` is the only status writer.” Either remove `final_status` from `persist_decision`, or define `record_run_error`/status writes as explicit wrappers over `set_status`.

- **LOW — 02-04 Task 1:** Plan depends on `repo.load_source_email` returning the original *cleaned* body, but 02-02 is not fully explicit that the cleaned body is what gets persisted. Pin this: either persist cleaned `body_text` or have `load_source_email` apply `clean_body`.

**Overall Verdict**

**NOT READY** — blocking item is the `Extracted.run_id` contradiction in `02-02 Task 2`. That needs to be resolved before execution; otherwise the pure extraction stage cannot safely produce the Phase 1 contract.
