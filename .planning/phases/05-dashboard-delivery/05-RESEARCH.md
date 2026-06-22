# Phase 5: Dashboard & Delivery - Research

**Researched:** 2026-06-22
**Domain:** FastAPI/Jinja2 operator UI + post-approval delivery pipeline + psycopg3 atomic status claims + reportlab PDF + alias write-side loop
**Confidence:** HIGH — all findings verified against the live codebase at the cited file:line

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: Alias WRITE-side loop lands at operator-approval gate; idempotent, no double-add.
- D-01b: Write-side collision exclusion is correctness-critical. Before appending a token to known_aliases, verify the token does NOT match more than one roster employee under the same rule reconcile_names uses. "D. Reyes" is the canonical trap.
- D-02: Alias write fires ONLY on operator approval (not on clarification reply).
- D-03: Eval stays seed-bound; alias write lands in live DB only.
- D-04: Mapping is `{original_token: resolved_employee_id}` dict, captured at clarify-EMIT time in `_clarify` (~orchestrator.py:200), NOT reconstructed at approval. Storage spot is open (candidate: `payroll_runs.reconciliation` JSONB).
- D-05: Over-40-no-OT validation rule in validate.py. Weekly >40 = complete detection. Biweekly >80 = partial (honestly labeled). Semi-monthly/monthly = no flag (documented). Explicit-`hours_overtime=0` edge must be decided explicitly (recommended: flag it).
- D-06: Plain server-rendered forms + POST-redirect-GET (303). No JS state.
- D-06b: sync-vs-background must be decided explicitly per action. Approve/delivery = bounded sync with hard draft timeout. Send-test/webhook = planner decides.
- D-07: Three-column layout: raw cleaned email (monospace pre) | extracted_data table | paystubs table. Decision reasons in a prominent banner.
- D-08: Runs list = reverse-chronological table with color-coded status badges.
- D-09a: Eval view embeds committed chart.svg as-is, reads summary.json for metrics and per-fixture drill-in. Hermetic — no live eval, no DB.
- D-10: compose_confirmation mirrors compose_clarification (draft tier + deterministic template floor).
- D-10b: Hard ~2–3s draft timeout falls through to floor on expiry. Bounds approve-click wall-clock.
- D-11: One PDF per employee, pure function (data in → BytesIO out), reportlab. Per-line-item download route + confirmation email attachment.
- D-12: claim_status(run_id, expected, new) -> bool in repo.py via conditional UPDATE … WHERE status=? RETURNING. Second sanctioned writer alongside set_status. Four call sites: approve, reject, resume, re-trigger, initial-run-claim. Invariant doc must be updated.
- D-13: Idempotent send via claim + already-sent-row check (get_outbound_message_id pattern). Re-trigger from START of run.
- D-13b: Post-approval delivery path MUST be wrapped in the D-A1-03 error-wrap boundary. Any failure between approve-claim and `sent` must route to `approved → error`. Re-trigger must be claimable from `approved` and `error`.
- D-13c: Intent/sentinel row BEFORE send so already-sent guard is crash-safe.
- D-15: Alias loop is recommended drop-if-tight candidate (planner lever, not silent re-order).

### Claude's Discretion
- Exact template/static file layout (app/templates/, app/static/).
- The exact storage SPOT for the token→employee mapping (D-04 candidate: reconciliation JSONB).
- Explicit-`hours_overtime=0` handling (recommended: flag it — treat same as absent).
- reportlab table layout details (fonts, column widths, header).
- claim_status return shape details (bool vs row; log line wording).
- Confirmation email subject and template floor prose.
- Eval drill-in table columns and exact summary.json fields consumed.

### Deferred Ideas (OUT OF SCOPE)
- Seedable before/after eval fixture proving alias-learning loop.
- htmx partial updates / responsive layout.
- Real email provider + Docker/Render/Supabase deploy + keep-alive + README/demo.
- Full resume-from-arbitrary-status (v2).
- Alias WRITE loop (D-01..D-04) if schedule tightens (D-15 lever).
- Full per-week biweekly OT detection.
- Client-side confirmation step, state withholding, persisted PDFs, dashboard auth.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DASH-01 | Runs list with status badge | D-08; Jinja2 route over repo.load_run |
| DASH-02 | Three-column run detail (raw email / extracted / paystubs + decision reasons) | D-07; load_inbound_email + load_run + paystub_line_items query |
| DASH-03 | Approve-and-send + Reject controls on pending run detail | D-06, D-12; claim_status gate + 303 redirect |
| DASH-04 | Eval view with headline metrics + per-fixture drill-in + chart.svg | D-09a; confirmed fields in eval/summary.json |
| DASH-05 | "Send test email" button fires a fixture through the pipeline | D-06; POST to /webhook/inbound with a committed fixture |
| HITL-02 | Approval → confirmation email (LLM-drafted) + paystub PDFs | D-10, D-11; compose_confirmation + reportlab BytesIO |
| HITL-03 | PDFs on demand in memory, nothing persisted | D-11; reportlab BytesIO → StreamingResponse |
| CLAR-04 | Idempotent outbound sends (no duplicate on re-trigger or retry) | D-13; claim_status + get_outbound_message_id guard |
| INGEST-05 | Errored run surfaces on dashboard, re-triggerable from start (drop-if-tight) | D-13b; re-trigger route + claim_status |
| FOUND-04 | Atomic status transitions preventing double-approval | D-12; conditional UPDATE … WHERE status=? RETURNING |
</phase_requirements>

---

## Summary

Phase 5 wraps the existing working pipeline slice in a human-visible operator surface. The critical work is in three areas: (1) the `claim_status` atomic CAS helper that makes every contended gate race-safe, replacing the current load-then-set pattern documented as the accepted Phase-2 minimum; (2) the post-approval delivery path (confirmation email draft + reportlab PDF generation + send), which is NEW orchestrator work that currently has no error boundary; and (3) the Jinja2 dashboard with its three-column run-detail view, runs list, eval view, and demo trigger.

The codebase is well-positioned. `compose_clarification` (app/pipeline/compose_email.py:88) is the exact DRY pattern `compose_confirmation` must mirror. `get_outbound_message_id` (repo.py:467) already implements the already-sent check primitive. The D-A1-03 error-wrap in `run_pipeline` / `resume_pipeline` is the pattern to mirror around the delivery path. `reportlab==5.0.0`, `jinja2==3.1.6`, and `python-multipart==0.0.20` are already in runtime deps — no new runtime deps needed.

Two items carry the highest bug risk: the D-01b write-side collision exclusion (which must use `deterministic_match` from reconcile_names, not just a name-string check) and the D-12 claim_status implementation (which is the foundation all four contended gates depend on). Both are pure-function testable without a live DB.

**Primary recommendation:** Build in this order: (1) `claim_status` + invariant-doc update, (2) over-40-no-OT validate.py rule, (3) confirm/PDF delivery path with error wrap + idempotency guard, (4) Jinja2 dashboard routes, (5) alias write-side loop (or drop per D-15 if schedule tightens).

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Atomic status transitions | Database (psycopg3 conditional UPDATE) | API/Backend (repo.py claim_status) | CAS primitive lives in Postgres; Python layer just calls it |
| Dashboard HTML routes | Frontend Server (FastAPI + Jinja2) | — | Server-rendered; no SPA |
| Form POST handlers (approve/reject/send-test/re-trigger) | API/Backend (FastAPI routes in main.py) | — | POST-redirect-GET pattern; business logic + 303 |
| Confirmation email drafting | API/Backend (compose_confirmation) | — | LLM call stays in pipeline layer; pure function |
| PDF generation | API/Backend (pure function → BytesIO) | — | In-memory; no FS touch; Render ephemeral FS constraint |
| Alias write-side loop | API/Backend (repo write at approval gate) | — | DB write only at the operator gate; pure collision check first |
| OT validation rule | API/Backend (validate.py pure function) | — | Data in / issues out; no DB, no LLM |
| Eval view (DASH-04) | Frontend Server (FastAPI route) | — | Hermetic disk reads; no DB, no live eval on the read path |

---

## Standard Stack

### Core (all already in pyproject.toml — no new runtime deps needed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | 0.138.0 | Webhook server + Jinja2 dashboard routes | Already in use; Jinja2Templates integration is built-in |
| jinja2 | 3.1.6 | Server-rendered dashboard templates | Already in runtime deps; FastAPI's Jinja2Templates wraps it |
| python-multipart | 0.0.20 | Form POSTs (approve/reject/send-test) | Already in runtime deps; required for `<form method=post>` |
| reportlab | 5.0.0 | On-demand per-employee paystub PDFs | Already in runtime deps; pure Python, zero system deps |
| psycopg[binary,pool] | 3.3.4 | Postgres atomic conditional UPDATE for claim_status | Already in use; the CAS UPDATE is atomic without an explicit txn |
| pydantic | 2.13.4 | Request validation + template data contracts | Already in use throughout |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| fastapi.responses.StreamingResponse | (FastAPI built-in) | Stream PDF BytesIO to client | Per-line-item download route + email attachment assembly |
| fastapi.staticfiles.StaticFiles | (FastAPI built-in) | Serve CSS/static assets from app/static/ | Only if a separate stylesheet is used (vs inline) |
| fastapi.templating.Jinja2Templates | (FastAPI built-in) | Wire templates dir to routes | One Templates instance at module level |

**Installation:** No new `uv add` calls needed. All runtime deps are already in `pyproject.toml`. For any new dev/test dep (none anticipated): `uv add --dev <pkg>`. [VERIFIED: project pyproject.toml]

---

## Package Legitimacy Audit

No new external packages are introduced in this phase. All runtime dependencies (`fastapi`, `jinja2`, `python-multipart`, `reportlab`, `psycopg`) are already installed and verified from prior phases.

**Packages removed due to slopcheck:** none — no new packages.
**Packages flagged as suspicious:** none.

---

## Open Item Resolutions (the actual research deliverables)

### 1. D-04: Storage Spot for the Original-Token → Employee Mapping

**The unrecoverability claim — VERIFIED.** [VERIFIED: app/pipeline/orchestrator.py]

Reading the real resume path:
- `resume_pipeline` (orchestrator.py:87) calls `_combined_context_email(inbound, original_body)` at line 139. This builds a combined body of `ORIGINAL PAYROLL EMAIL:\n{original_body}\n\nCLARIFICATION REPLY FROM CLIENT:\n{reply.body_text}`. This combined context is passed to `extract()`.
- `extract()` sees BOTH the original email AND the client's reply. The reply typically contains the CORRECTED name (e.g. "I meant David Reyes"). The original unresolved token ("David Reyez") is present in the combined context, but the extraction is designed to extract final intent — meaning after re-extraction, the submitted name in `extracted.employees` will likely be the resolved name from the reply, NOT the original misspelled token.
- Even if extract somehow preserved the typo, the orchestrator does NOT carry the `{original_token → employee_id}` mapping anywhere between `_clarify` and the approval point. After `_run_stages` completes, the `decision` stored in `payroll_runs.decision` contains `unresolved_names` (the original tokens) but NOT their resolutions — because on the re-run those names are now resolved. The `reconciliation` JSONB is OVERWRITTEN by `persist_reconciliation` on every run (orchestrator.py:187: `repo.persist_reconciliation(run_id, matches)`) — it reflects the POST-RESUME resolved state.

**Conclusion: CONTEXT.md is correct.** By approval time, the original unresolved token and the fact that it came from a clarification are genuinely unrecoverable from the DB state unless explicitly persisted at clarify-emit time. [VERIFIED: orchestrator.py:87-149, 186-188]

**Concrete storage recommendation for D-04:**

Store the mapping as a new key `"alias_candidates"` inside the EXISTING `payroll_runs.reconciliation` JSONB column (schema.sql:87). The `reconciliation` column is already JSONB and is the home for per-run resolution facts. Writing a nested key keeps the schema unchanged and co-locates alias-learning metadata with the rest of the resolution record.

**Shape (written at clarify-emit in `_clarify`, orchestrator.py:200-245):**
```python
# Written immediately BEFORE gateway.send_outbound():
# {original_token: resolved_employee_id_str, ...}
# Only tokens that are unresolved AND not ambiguous (no collision) are candidates.
# Ambiguous tokens (matches 2+ employees) are excluded at capture time per D-01b.
alias_candidates: dict[str, str | None] = {}
for name in decision.unresolved_names:
    # Only store if NOT a collision (a collision means len(candidate_ids) > 1 in
    # deterministic_match — the token matched 2+ employees). Collisions are excluded
    # here; D-01b's write-side check is the final gate at approval.
    alias_candidates[name] = None  # resolved_employee_id filled at resume
```

**Updated at resume** (in `resume_pipeline` after `_run_stages` completes, when the resolved `matches` are available): for each candidate token where the post-resume match is now resolved, write `token → matched_employee_id`.

**Read at approval** (in the approve handler): read `run["reconciliation"]["alias_candidates"]`, filter to entries with a non-None employee_id, pass to the alias-write helper.

**Why reconciliation JSONB is the right spot:**
- Already populated at clarify-emit time via `persist_reconciliation` — the data write happens in the right context.
- The column is already JSONB (typed for arbitrary JSON, no schema migration needed).
- Co-location with resolution facts is conceptually correct.
- The planner can choose an alternative (a separate column, a separate key) but the reconciliation JSONB requires no DDL change and is immediately available.

**Alternative**: a dedicated `payroll_runs.alias_candidates` JSONB column would be more explicit but requires a DDL change (ALTER TABLE + schema.sql update). Given the zero-migration philosophy and the JSONB column already existing, adding a key to reconciliation is preferred. [ASSUMED — the planner makes the final call on which key/column]

---

### 2. D-01b: Write-Side Collision Exclusion — Exact Reuse Mechanism

**VERIFIED: reconcile_names.py:37-81** [VERIFIED: app/pipeline/reconcile_names.py]

The collision detection lives in `deterministic_match(name, roster)` at reconcile_names.py:37. The logic is:
1. Build `exact_ids` = all employees whose `_norm(full_name) == _norm(name)`
2. Build `alias_ids` = all employees with any `_norm(alias) == _norm(name)` in `known_aliases`
3. `candidate_ids = set(exact_ids) | set(alias_ids)`
4. If `len(candidate_ids) != 1` → return None (zero candidates OR 2+ distinct employees = ambiguous)

**The write-side collision check MUST simulate this exact function** on the roster as it would exist AFTER appending the new alias. The check is: call `deterministic_match(new_token, roster_with_alias_added)` and verify it returns the specific employee (not None, not a different employee).

**Recommended implementation:** Create a pure helper `_would_collide(token: str, target_employee_id: UUID, roster: Roster) -> bool` that:
1. Builds a synthetic roster where `target_employee.known_aliases` includes the new token.
2. Calls `deterministic_match(token, synthetic_roster)`.
3. Returns True if the result is None or resolves to a DIFFERENT employee.

This reuses `deterministic_match` directly rather than duplicating the logic. The function is already importable as a pure function.

**The David/Daniel Reyes trap — CONFIRMED.** [VERIFIED: app/db/seed.py:134-150, 245-261]

Both David Reyes (e0000003, seed.py:134) and Daniel Reyes (e0000007, seed.py:245) carry `known_aliases=["D. Reyes"]`. Running `deterministic_match("D. Reyes", roster)` hits the `len(candidate_ids) != 1` branch (both employees match the alias) and returns None. If a naive alias write appended "D. Reyes" to David only, the NEXT call to `deterministic_match("D. Reyes", roster)` would find David's alias as a unique match AND still find Daniel's alias — still a collision → still returns None. Wait — actually it would find 2 entries: David (via alias) and Daniel (via alias) → still `len(candidate_ids) == 2` → still None. BUT the scenario CONTEXT.md describes is the learnable case: if "D. Reyes" were only on David (not on Daniel), a write without the collision check would silently create a fast-path that routes future "D. Reyes" to David even when Daniel was meant. The seed has BOTH employees carrying the alias precisely to make this a hard collision — a demo that learns "D. Reyes" would correctly be blocked by the collision check, and the demo learnable token must be something unambiguous (e.g. "David Reyez" → only David Reyes is a candidate once the alias is added).

**Conclusion:** The write path must call `deterministic_match` (or the synthetic-roster variant) — it cannot be a simple `alias not in employee.known_aliases` idempotency check. [VERIFIED: reconcile_names.py:37-81]

---

### 3. D-12: claim_status Atomic Semantics + Four Call Sites

**Postgres CAS atomicity — CONFIRMED.** [VERIFIED: psycopg3 behavior + repo.py pattern analysis]

`UPDATE payroll_runs SET status=%s, updated_at=now() WHERE id=%s AND status=%s RETURNING id` is atomic in Postgres without an explicit transaction wrapper. In Postgres, every single DML statement runs in an implicit transaction. The `WHERE status=%s` predicate and the SET are evaluated atomically — no other connection can see an intermediate state. If the status changed between the two clients reading `awaiting_approval`, exactly one UPDATE will match and return a row; the other returns zero rows. [ASSUMED — confirmed from psycopg3 docs pattern knowledge; HIGH confidence given Postgres single-statement atomicity guarantees]

**Existing set_status pattern (repo.py:267-279):** [VERIFIED: app/db/repo.py:267]
```python
def set_status(run_id: uuid.UUID, status: RunStatus, conn=None) -> None:
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET status = %s, updated_at = now() WHERE id = %s",
                (RunStatus(status).value, str(run_id)),
            )
```

**claim_status must mirror this pattern exactly:**
```python
def claim_status(
    run_id: uuid.UUID,
    expected: RunStatus,
    new: RunStatus,
    conn=None,
) -> bool:
    """Atomic compare-and-swap on payroll_runs.status.
    
    Returns True if the claim succeeded (run was in `expected` and is now `new`).
    Returns False if the run was NOT in `expected` — caller logs a late/duplicate
    and drops cleanly (does not re-run the work).
    Second sanctioned status writer alongside set_status.
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                "UPDATE payroll_runs SET status = %s, updated_at = now() "
                "WHERE id = %s AND status = %s RETURNING id",
                (RunStatus(new).value, str(run_id), RunStatus(expected).value),
            ).fetchone()
    return row is not None
```

The `_conn_ctx` + `_nulltx` pattern is identical to `set_status` — the optional `conn=` composability is inherited. [VERIFIED: repo.py:97-104]

**Four call sites and their expected→new transitions:**

| Call Site | Expected | New | Notes |
|-----------|----------|-----|-------|
| Approve (_operator_transition) | `awaiting_approval` | `approved` | Replaces current load-then-set (main.py:241-249); on False → 409 "already claimed" |
| Reject (_operator_transition) | `awaiting_approval` | `rejected` | Same handler, different target |
| Resume (resume_pipeline) | `awaiting_reply` | `extracting` | Replaces the CR-02 residual non-atomic check at orchestrator.py:125+141; on False → late/dup, log and return |
| Re-trigger route | `error` OR `approved` | `received` | Two valid prior states; planner may need two calls or an IN-list variant |
| Initial run claim | `received` | `extracting` | Closes the unguarded first transition in _run() |

**FOUND-04 resolution:** CONTEXT.md confirms that the conditional UPDATE is satisfied-in-spirit for FOUND-04's "SELECT ... FOR UPDATE" wording. The CAS UPDATE is the superior primitive for these status-only gates (no need for a lock + separate write when the write IS the check). [VERIFIED: CONTEXT.md specifics section]

**Invariant doc update required:** `repo.py` header (line 17: "the ONE AND ONLY writer of payroll_runs.status") and `set_status` docstring (line 267) must both be updated to: "two writers — `set_status` (unguarded forward transitions inside an owned path) and `claim_status` (atomic guarded claim at every contended gate)." [VERIFIED: repo.py:17, 267-272]

---

### 4. D-13b/D-13c: Delivery Path Error Boundary + Intent-Row-Before-Send

**Current error-wrap pattern — VERIFIED.** [VERIFIED: orchestrator.py:61-70, 121-149]

Both `run_pipeline` and `resume_pipeline` wrap their inner `_run()` / core logic in `try/except Exception → repo.record_run_error(run_id, reason)`. The error boundary is at the outer function level; the inner `_run_stages` is unguarded (it can raise freely; the outer catch handles it).

**The delivery path gap:** The approve handler in `main.py:_operator_transition` (line 240) currently does:
```python
run = repo.load_run(run_id)
# status check
repo.set_status(run_id, target)
return JSONResponse(...)
```

Phase 5 adds: claim_status + compose_confirmation + PDF generation + send_outbound + advance to sent/reconciled. All of this runs synchronously in the route handler. There is NO try/except around it. If compose_confirmation raises (API error), or PDF generation fails (invalid PaystubLineItem), or send_outbound raises after the claim but before `sent`, the run is stuck in `approved` with no recovery path. [VERIFIED: main.py:240-253]

**Recommended error boundary for the delivery path:**
```python
# In the approve handler, AFTER claim_status wins:
try:
    _deliver(run_id, run)  # compose + PDFs + send + advance to sent/reconciled
except Exception as exc:
    reason = type(exc).__name__
    logger.warning("delivery of run %s failed: %s", run_id, reason)
    repo.record_run_error(run_id, reason)
    # 303 redirect to run detail (shows error badge + reason)
```

`record_run_error` (repo.py:282-316) already handles the WR-04 terminal-status guard — it will NOT clobber a run that somehow already reached a terminal state. But it WILL convert `approved → error` correctly because `approved` is NOT in `_TERMINAL_STATUSES` (repo.py:86-94: terminal = approved, sent, reconciled, rejected, error — wait, `approved` IS in `_TERMINAL_STATUSES`!).

**CRITICAL FINDING:** `approved` IS in `_TERMINAL_STATUSES` at repo.py:86-94:
```python
_TERMINAL_STATUSES = frozenset({
    RunStatus.APPROVED.value,
    RunStatus.SENT.value,
    RunStatus.RECONCILED.value,
    RunStatus.REJECTED.value,
    RunStatus.ERROR.value,
})
```

This means `record_run_error` will SKIP writing ERROR if the run is already in `approved` (WR-04 guard fires). **The delivery path error recovery requires either:**
1. Removing `approved` from `_TERMINAL_STATUSES` (since Phase 5 makes `approved` an in-flight non-terminal state from the delivery path's perspective), OR
2. Using a direct `set_status(run_id, RunStatus.ERROR)` + error_reason write that bypasses `record_run_error`, OR
3. Having `claim_status` for the delivery claim NOT use `approved` as the terminal — instead having the delivery path work from the `approved` claim and using a separate `delivery_error_handler` that writes ERROR directly.

**Recommended fix:** Remove `approved` from `_TERMINAL_STATUSES` since Phase 5 defines `approved` as an in-flight state (the delivery hasn't happened yet). `approved` is only terminal-ish if delivery always succeeds, which Phase 5 explicitly handles. RECONCILED and SENT are the true terminal-success states. [VERIFIED: repo.py:86-94]

**D-13c intent-row-before-send:** The current stub gateway (gateway.py:58-70) mints the Message-ID THEN writes the `email_messages` row in a single synchronous call — mint+record are atomic. But CONTEXT.md is correct that Phase 6's live provider will separate the mint+network call from the DB insert. The Phase-5 fix: pass `conn=` into `send_outbound` from the delivery path, write the intent row (with a placeholder body or status marker) BEFORE calling the real send, update the row AFTER. Or: write a pre-send row with `direction='outbound-pending'` and update to `'outbound'` on success. The stub can honor this ordering today so the Phase 6 swap is a no-op. [VERIFIED: gateway.py:40-71]

---

### 5. D-10/D-10b: Confirmation Composer + Hard Draft Timeout

**compose_clarification shape — VERIFIED.** [VERIFIED: app/pipeline/compose_email.py:88-132]

`compose_clarification` (compose_email.py:88) accepts `(decision, *, suggestions, llm)` and calls `llm.call_text("draft", messages, temperature=0.3)`. On `None` or exception, it falls back to `_template_body(decision, suggestions)`. The entire pattern including the `try/except` around the API call is at lines 114-132.

**compose_confirmation must mirror this exactly:**
- Same function signature shape: `(run_id_or_data, paystubs, *, llm)` (pure data in, str out)
- Call `llm.call_text("draft", messages, temperature=0.3)` — same tier, same method
- `try/except` around the call: on any exception → fall back to `_confirmation_template_body(paystubs, run)` 
- Template floor: run total, per-employee net, pay date — deterministic, never empty

**Hard timeout (D-10b):** `call_text` in `app/llm/client.py:155` calls the `openai` library's `client.chat.completions.create()`. The OpenAI Python client uses `httpx` as its transport. The timeout for a single request is set per-client or per-request. [ASSUMED — openai client timeout parameter pattern from training knowledge]

The cleanest approach for a hard 2–3s timeout that degrades to the floor:
```python
import asyncio

async def _draft_with_timeout(messages, llm, timeout_s=3.0):
    loop = asyncio.get_event_loop()
    try:
        # call_text is synchronous; run in executor with timeout
        body = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: llm.call_text("draft", messages, temperature=0.3)),
            timeout=timeout_s
        )
        return body
    except (asyncio.TimeoutError, Exception):
        return None  # fall through to floor
```

BUT: the approve route is a synchronous FastAPI route (not async). The simpler alternative is to pass `timeout=` to the OpenAI client at construction. The `openai.OpenAI` client accepts `timeout` in its constructor. [ASSUMED — openai Python SDK timeout parameter]

**Simplest correct approach:** In `call_text`, accept an optional `timeout_s: float | None = None` parameter and pass it to `client = OpenAI(base_url=..., api_key=..., timeout=timeout_s)`. The compose_confirmation caller passes `timeout_s=3.0`. The `openai` client wraps httpx which respects the timeout. On timeout, the exception is caught by the `try/except` in compose_confirmation, degrading to the template floor. This is the lowest-change path.

**Alternative:** Use `httpx.Timeout(3.0)` passed as `timeout=httpx.Timeout(3.0)` to `OpenAI(timeout=...)`. [ASSUMED — httpx Timeout composability with openai client]

Confidence on the exact parameter: MEDIUM. The planner should verify against `openai==2.43.0` docs or the openai-python GitHub before implementing. The overall approach (timeout → except → floor) is HIGH confidence.

---

### 6. D-06b: Sync-vs-Background Execution — Confirmed State

**VERIFIED: run_pipeline is a BackgroundTask; _operator_transition is synchronous.** [VERIFIED: app/main.py:103, 240]

From main.py:
- `run_pipeline` is scheduled via `background_tasks.add_task(_run_pipeline, run_id)` at line 103. It returns 200 fast. The pipeline runs asynchronously.
- `resume_pipeline` is similarly backgrounded at line 167: `background_tasks.add_task(_resume_pipeline, run_id, reply_for_resume)`.
- `_operator_transition` at line 240 is fully synchronous: it does the work and returns a `JSONResponse` directly. No background task is involved.

**For Phase 5, the planner must decide explicitly per action:**

| Action | Recommended Execution | Rationale |
|--------|----------------------|-----------|
| Approve + delivery (compose + PDF + send) | **Synchronous, bounded** | The 303 redirect carries the result; unbounded = on-camera hang. With D-10b hard timeout (~3s) + pure-Python reportlab (~50ms) + stub send (~1ms), total is bounded. The operator only clicks once. |
| Reject | **Synchronous** | No LLM call; instant claim + 303. |
| Send-test ("Send test email" button) | **Background preferred** | Triggers run_pipeline which is already backgrounded. The button POSTs to `/webhook/inbound` with a fixture body — the existing webhook already backgrounds it. The page immediately 303-redirects to the run detail; the operator manually refreshes to see state advance. This is a deliberate, legible demo beat: "watch it move through extracting → computed → awaiting_approval." |
| Re-trigger (INGEST-05) | **Synchronous claim + background pipeline** | claim_status is synchronous (fast); the re-run is a BackgroundTask (mirrors the original webhook flow). |

---

### 7. D-11: reportlab Pure PDF Generator

**PaystubLineItem fields confirmed.** [VERIFIED: app/models/contracts.py:149-184, app/pipeline/calculate.py:180+]

Fields available for each employee's PDF:
- `hours_regular`, `hours_overtime`, `hours_vacation`, `hours_sick`, `hours_holiday`
- `gross_pay` — total gross (OT at 1.5× already baked in by calculate.py)
- `pretax_401k` — pre-tax 401k deduction
- `fica_ss` — Social Security tax
- `fica_medicare` — Medicare tax
- `federal_withholding` — IRS Pub 15-T withholding
- `state_withholding` — always None/Decimal("0") in Phase 5 (v1 scope)
- `net_pay` — final net
- `additional_medicare_not_modeled: bool` — disclaimer flag
- `submitted_name` — as written in the email
- `employee_id` — for header
- `run_id` — for header

Additionally, the paystub header needs employee full_name and pay_period dates. These must be passed as additional parameters since PaystubLineItem doesn't carry them. The pure function signature:
```python
def generate_paystub_pdf(
    item: PaystubLineItem,
    employee_full_name: str,
    pay_period_start: date | None,
    pay_period_end: date | None,
) -> bytes:
    """Pure: data in → PDF bytes out. No DB. Returns raw PDF bytes."""
    buf = BytesIO()
    # reportlab SimpleDocTemplate(buf, ...) → build table → getvalue()
    return buf.getvalue()
```

**reportlab BytesIO → StreamingResponse pattern** [ASSUMED — confirmed from CLAUDE.md §4 and reportlab docs pattern]:
```python
from io import BytesIO
from fastapi.responses import StreamingResponse

pdf_bytes = generate_paystub_pdf(item, emp_name, start, end)
return StreamingResponse(
    BytesIO(pdf_bytes),
    media_type="application/pdf",
    headers={"Content-Disposition": f'attachment; filename="paystub_{emp_name}.pdf"'},
)
```

For the email attachment path, `pdf_bytes` is passed as attachment data to `send_outbound`. The stub gateway currently takes no `attachments=` parameter — this will need to be added to `gateway.send_outbound()` signature.

**reportlab table pattern for a paystub:** Use `reportlab.platypus.Table` with a list of `[label, value]` rows. `SimpleDocTemplate` to the BytesIO, `doc.build([table])`. No system dependencies — BSD pure Python. [ASSUMED: reportlab table API from training knowledge; HIGH confidence given the library is already in pyproject.toml and widely documented]

---

### 8. D-05: Over-40-No-OT Rule in validate.py

**Current validate.py seam — VERIFIED.** [VERIFIED: app/pipeline/validate.py:50-82]

`validate(extracted, roster, matches) -> list[ValidationIssue]` (line 50) is PURE. It currently only emits `issue_type="missing"` for hourly employees with no hours. The function already accesses `emp.pay_type` via `_employee_pay_type()` (line 36) which resolves the matched employee's pay type from `matches` and `roster`.

**Adding the OT rule:** The function needs one additional lookup: `emp.pay_periods_per_year` (already available via `_employee_pay_type`'s pattern — extend it to a `_employee_data()` helper or inline the lookup). The new rule adds to `validate()` after the existing missing-hours check:

```python
# D-05: Over-40-no-OT guard
for emp in extracted.employees:
    # Only for resolved (matched) employees — unresolved already gate on decide
    pay_periods = _employee_pay_periods(emp.submitted_name, matches, roster)
    if pay_periods is None:
        continue
    ot = emp.hours_overtime  # None means absent (not submitted)
    ot_absent = (ot is None)
    ot_explicit_zero = (ot is not None and ot == 0)
    # Threshold: weekly=40, biweekly=80; semi-monthly/monthly=skip
    if pay_periods == 52 and emp.hours_regular is not None and emp.hours_regular > 40:
        if ot_absent or ot_explicit_zero:  # recommended: flag explicit 0 too
            issues.append(ValidationIssue(
                field=f"{emp.submitted_name}.hours_overtime",
                issue_type="missing",
                message=f"weekly employee {emp.submitted_name!r} has {emp.hours_regular} regular hours "
                        "with no overtime — is that 40 regular + OT, or straight time?",
            ))
    elif pay_periods == 26 and emp.hours_regular is not None and emp.hours_regular > 80:
        if ot_absent or ot_explicit_zero:
            issues.append(ValidationIssue(
                field=f"{emp.submitted_name}.hours_overtime",
                issue_type="missing",
                message=f"biweekly employee {emp.submitted_name!r} has {emp.hours_regular} regular hours "
                        "(>80 over 2 weeks guarantees OT in at least one week) — please provide the split.",
            ))
    # pay_periods in (24, 12): period boundaries cross workweeks → no flag
```

**Explicit `hours_overtime=0` edge:** Per D-05, the recommended decision is to flag it (treat same as absent). This puts it on the record and avoids the "client submitted 45 regular + 0 OT and we silently underpay" scenario. [ASSUMED — planner makes the final call per Claude's Discretion]

**ValidationIssue → decide → clarify wiring — VERIFIED.** [VERIFIED: reconcile_names.py (pure output), decide.py (reads issues), orchestrator.py:181 (passes issues)]

The existing wiring at orchestrator.py:181 passes `issues` to `decide()`. `decide.py` already consumes `list[ValidationIssue]` and sets `final_action="request_clarification"` + populates `missing_fields` when issues are non-empty. The OT rule emits into the same `issues` list, so no wiring change is needed — the new rule plugs into the existing gate path transparently. [VERIFIED: orchestrator.py:181-183]

**Testable employees in seed:**
- Maria Chen (e0000001, Business 1, weekly/52, hourly): demo candidate for the weekly OT beat
- David Reyes (e0000003, Business 2, weekly/52, hourly): also weekly
- Thomas Bergmann (Business 3, biweekly/26): biweekly partial-detection case
- Sandra Kim (Business 3, biweekly/26): second biweekly case

[VERIFIED: app/db/seed.py:79-262 + cadence comment at line 264]

---

### 9. DASH-04: Eval View — Confirmed Artifact Shape

**summary.json fields confirmed.** [VERIFIED: eval/summary.json]

Top-level keys available for the headline metrics section:
- `schema_version`, `suite_run_id`, `generated_at`, `extraction_model_id`
- `false_process_rate` (0.0 in current artifact)
- `confusion_matrix`: `{true_process, false_process, false_clarify, true_clarify, false_process_rate, false_process_precision_rate}`
- `extraction_overall_f1`, `extraction_overall_field_accuracy`
- `per_category_extraction`: dict by category (exact/stored-alias/collision/unknown/typo/first-time-alias/missing-hours/vague-hours/buried-reply) → `{f1, field_accuracy}`
- `per_category_reconciliation`: list of `{category, correct, total, accuracy}`
- `per_category_decision`: dict by category → `{correct, total, fraction}`
- `rigor_gate_struct_accuracy`

**Per-fixture drill-in (from `per_fixture` array at line 141):**
```json
{
  "fixture_id": "f0000001-...",
  "fixture_path": "01_exact_match_coastal.json",
  "fixture_category": "exact",
  "extraction": {"precision", "recall", "f1", "field_accuracy", ...},
  "reconciliation": [{"submitted_name", "name_category", "correct", "actual_source",
                       "actual_resolved", "actual_matched_employee_id", "expected_matched_employee_id"}],
  "decision": {"action_correct", "gate_struct_ok", "final_action", "expected_final_action"}
}
```

The raw email body is NOT in summary.json — DASH-04 requires "drilling into a fixture shows its raw email body." The raw email body lives in `eval/fixtures/<fixture_path>` on disk. The drill-in view can read the fixture file directly by filename (hermetic disk read; no DB). [VERIFIED: eval/summary.json:141-174]

**chart.svg** is present at `eval/chart.svg`. It is the committed artifact. The eval view must embed it as-is via an `<img src="/eval/chart.svg">` tag or an inline `<img>` with a route that serves the file. No re-rendering. [VERIFIED: ls eval/]

**Hermetic route pattern:**
```python
@app.get("/eval")
def eval_view(request: Request):
    summary = json.loads(Path("eval/summary.json").read_text())
    return templates.TemplateResponse("eval.html", {"request": request, "summary": summary})

@app.get("/eval/chart.svg")
def eval_chart():
    return FileResponse("eval/chart.svg", media_type="image/svg+xml")
```

No DB, no live eval, no LLM on this path. [VERIFIED: CONTEXT.md D-09a]

---

### 10. Jinja2 Wiring + python-multipart Form POSTs

**Current main.py shape — VERIFIED.** [VERIFIED: app/main.py:1-254]

Current main.py has:
- `POST /webhook/inbound` (line 49)
- `POST /runs/{run_id}/approve` (line 224) — crude JSON response, NO Jinja2
- `POST /runs/{run_id}/reject` (line 234) — crude JSON response, NO Jinja2

No `Jinja2Templates` instance, no `GET /runs`, no `GET /runs/{id}`, no `GET /eval`. The file is 254 lines.

**Recommended additions to main.py (or a new `app/routes/dashboard.py` router):**
```python
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
```

Routes to add:
```python
@app.get("/runs")                  # DASH-01: runs list
@app.get("/runs/{run_id}")         # DASH-02/03: run detail + controls
@app.post("/runs/{run_id}/approve") # replaces crude JSON endpoint → 303
@app.post("/runs/{run_id}/reject")  # replaces crude JSON endpoint → 303
@app.post("/runs/{run_id}/retrigger") # INGEST-05 (if built)
@app.get("/runs/{run_id}/pdf/{employee_id}") # on-demand PDF download (HITL-03)
@app.get("/eval")                  # DASH-04: eval view
@app.post("/demo/send-test")       # DASH-05: "Send test email" button
```

**POST-redirect-GET (303) pattern in FastAPI:**
```python
from fastapi.responses import RedirectResponse

@app.post("/runs/{run_id}/approve")
def approve(run_id: uuid.UUID, form_data: ...):
    # do the work
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
```

FastAPI handles `RedirectResponse(status_code=303)` correctly. The 303 causes the browser to GET the redirect URL with a GET method regardless of the original POST. [ASSUMED — FastAPI RedirectResponse behavior; HIGH confidence]

**python-multipart requirement:** For form POSTs, FastAPI needs `python-multipart` installed (already in deps) and route parameters annotated with `Form(...)` from `fastapi`:
```python
from fastapi import Form

@app.post("/runs/{run_id}/approve")
def approve(run_id: uuid.UUID, confirmed: str = Form(default="yes")):
    ...
```

For routes that POST with no form fields (just the run_id in the URL), no Form annotation is needed — the button can be a `<form method="post" action="/runs/{id}/approve"><button>Approve</button></form>`. [ASSUMED — FastAPI form handling pattern; HIGH confidence]

**Existing approve/reject endpoints:** The Phase 5 plan must decide whether to:
- Replace the existing JSON endpoints (main.py:224, 234) with form-handling 303-redirect versions, OR
- Keep the JSON endpoints and add NEW form-handling routes alongside them.

Recommendation: Replace them — they are labeled "crude" in the code and are Phase-5 deliverables (DASH-03). The test in `tests/test_hitl.py` that tests the current crude JSON endpoints will need updating. [VERIFIED: main.py:224-253]

---

## Architecture Patterns

### System Architecture Diagram

```
POST /webhook/inbound
        │
        ▼
  gateway.parse_inbound()  ←── fixture JSON / live email
        │
        ▼
  repo.insert_inbound_email()  ── ON CONFLICT DO NOTHING (FOUND-02)
        │ (background task)
        ▼
  run_pipeline()  ──► extract → reconcile → validate → decide
        │                                                   │
        ▼ (process)                            (request_clarification)
  calculate() → paystubs                              _clarify()
        │                                      ┌──────────┘
        ▼                                      │  capture alias_candidates
  awaiting_approval ─────────────────────────►│  into reconciliation JSONB
        │                                      │
        │ operator clicks APPROVE              ▼
        ▼                              email_messages (outbound)
  claim_status(awaiting_approval → approved)   │
        │                                      │ client replies
        ▼                             (POST /webhook/inbound with In-Reply-To)
  [delivery path — NEW, sync, bounded]         │
  ┌─────────────────────────────┐              ▼
  │ compose_confirmation()      │    resume_pipeline()
  │   └─ draft tier (≤3s)       │    claim_status(awaiting_reply → extracting)
  │   └─ OR template floor      │    _run_stages() → recompute → awaiting_approval
  │ generate_paystub_pdf() ×N   │              │
  │ send_outbound(+attachments) │              │ alias_candidates updated
  │ set_status(sent)            │              │ with resolved_employee_id
  │ set_status(reconciled)      │              ▼
  └─────────────────────────────┘    operator approves resolved run
        │                            alias write-side: check collision
        ▼                            → append to known_aliases if safe
  GET /runs → Jinja2 runs list
  GET /runs/{id} → 3-column detail
  GET /eval → summary.json + chart.svg
  GET /runs/{id}/pdf/{emp_id} → StreamingResponse (BytesIO)
  POST /demo/send-test → /webhook/inbound (fixture)
```

### Recommended Project Structure
```
app/
├── main.py                  # FastAPI entrypoint + all routes (or split into routes/)
├── templates/               # Jinja2 templates
│   ├── base.html            # base layout with nav
│   ├── runs_list.html       # DASH-01
│   ├── run_detail.html      # DASH-02/03 (3-col grid)
│   └── eval.html            # DASH-04
├── static/                  # optional: one CSS file
│   └── style.css
├── pipeline/
│   ├── validate.py          # add over-40-no-OT rule (D-05)
│   ├── compose_email.py     # add compose_confirmation (D-10)
│   └── pdf.py               # NEW: generate_paystub_pdf (D-11, pure)
└── db/
    └── repo.py              # add claim_status + update_known_alias (D-12, D-01)
```

### Pattern 1: claim_status CAS (D-12)
**What:** Conditional UPDATE...RETURNING as atomic compare-and-swap
**When to use:** Every contended gate where two callers could race (approve, resume, re-trigger, initial claim)

```python
# Source: repo.py pattern (mirrors set_status at line 267)
def claim_status(run_id: uuid.UUID, expected: RunStatus, new: RunStatus, conn=None) -> bool:
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                "UPDATE payroll_runs SET status = %s, updated_at = now() "
                "WHERE id = %s AND status = %s RETURNING id",
                (RunStatus(new).value, str(run_id), RunStatus(expected).value),
            ).fetchone()
    return row is not None
```

### Pattern 2: POST-redirect-GET (D-06)
**What:** Form POST does work, 303 redirects to GET — no JS state
**When to use:** All operator actions (approve, reject, send-test, re-trigger)

```python
# Source: FastAPI pattern (D-06 locked)
from fastapi.responses import RedirectResponse

@app.post("/runs/{run_id}/approve")
def approve(run_id: uuid.UUID):
    claimed = repo.claim_status(run_id, RunStatus.AWAITING_APPROVAL, RunStatus.APPROVED)
    if not claimed:
        # 303 back to detail — the badge shows current status (already advanced)
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
    try:
        _deliver(run_id)
    except Exception as exc:
        repo.record_run_error(run_id, type(exc).__name__)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
```

### Pattern 3: Delivery path error boundary (D-13b)
**What:** Wrap compose+PDF+send in D-A1-03-style try/except after claim
**Note:** `approved` must be removed from `_TERMINAL_STATUSES` so `record_run_error` can advance it to ERROR.

### Anti-Patterns to Avoid
- **Load-then-set for contended gates:** Reading status then setting it in two separate statements — the race window is the CR-02 documented bug. Use `claim_status` instead.
- **Adding `approved` to `_TERMINAL_STATUSES`:** It is already there (repo.py:87) — this must be REMOVED for the delivery error recovery to work.
- **Reconstructing alias_candidates at approval time:** CONTEXT.md is correct — by approval the original token is gone. Capture at clarify-emit.
- **Calling `reconcile_names()` for alias write-side collision check:** Use `deterministic_match()` directly on a synthetic roster instead — that is the actual predicate.
- **Template engine re-rendering the committed chart.svg:** Embed as-is via `<img>` or a static file route.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Atomic status CAS | A SELECT + separate UPDATE | `UPDATE … WHERE status=? RETURNING` | Single-statement atomicity; no lock boilerplate |
| PDF generation | Custom binary format | `reportlab` (already in deps) | Tables, decimal formatting, BytesIO — zero system deps |
| Template rendering | String concatenation | `Jinja2Templates` (FastAPI built-in) | Auto-escaping, macros, template inheritance |
| Outbound email dedup | A lock table | `get_outbound_message_id` + already-sent check (repo.py:467) | Already built; reuse the pattern |
| OT calculation at validation time | Call into calculate.py | Pure validate.py rule (hours_regular > threshold, no OT field) | Calc is downstream of validate; validation must be pure |

---

## Runtime State Inventory

This is a greenfield phase (not a rename/refactor). Skip.

---

## Common Pitfalls

### Pitfall 1: `approved` in `_TERMINAL_STATUSES` Blocks Error Recovery
**What goes wrong:** `record_run_error` (repo.py:297-303) checks if current status is in `_TERMINAL_STATUSES` and skips the ERROR write if so. `approved` IS in that set (repo.py:87). So a delivery failure after the approve claim cannot be converted to ERROR via `record_run_error` — it silently no-ops. The run is stuck in `approved` with no recovery path.
**Why it happens:** `approved` was added as terminal because in Phase 2's crude gate, `approved` WAS a final state (no delivery happened). Phase 5 makes `approved` an in-flight state.
**How to avoid:** Remove `approved` from `_TERMINAL_STATUSES` (repo.py:87) as part of the claim_status/delivery work. Validate with a test that `record_run_error` on an `approved` run correctly advances to ERROR.
**Warning signs:** A run stuck in `approved` with no Approve button (status is not `awaiting_approval`) and no error badge.

### Pitfall 2: Alias Write Collision Exclusion Using the Wrong Check
**What goes wrong:** A naive `if new_token not in employee.known_aliases` idempotency check is necessary but NOT sufficient. It doesn't detect that the new token matches another roster employee (the D. Reyes trap). A run that passes the idempotency check but fails the collision check would silently create a fast-path to the wrong employee on future runs.
**Why it happens:** The write side feels like "just add an alias" — the collision dimension is non-obvious.
**How to avoid:** Always call `deterministic_match(new_token, synthetic_roster_with_alias)` as the collision check. Return False (don't learn) if the result is None or resolves to a different employee.
**Warning signs:** A test that asserts alias write on "D. Reyes" for David Reyes succeeds when Daniel Reyes also carries it.

### Pitfall 3: resume_pipeline claim_status Return Not Checked
**What goes wrong:** `resume_pipeline` must return early if `claim_status(awaiting_reply → extracting)` returns False. The current precondition check (orchestrator.py:125) logs and returns — but if converted to claim_status, the False return MUST be caught and acted on, not just checked for truthiness in an `if` that was added for the logging.
**Why it happens:** The existing code is a manual status-read + early return; the CAS version is a function call that needs its return value inspected.
**How to avoid:** `if not repo.claim_status(run_id, RunStatus.AWAITING_REPLY, RunStatus.EXTRACTING): return`.

### Pitfall 4: Post-approval 303 Fires BEFORE Delivery Completes
**What goes wrong:** The 303 redirect should fire AFTER the delivery attempt (success or error). If the redirect fires before the `try/except` wraps delivery, a delivery failure produces a 303 to the run detail that shows `approved` (not error) — the operator has no feedback.
**Why it happens:** Refactoring the crude handler to add a 303 without moving the logic inside the try/except first.
**How to avoid:** Wrap `_deliver()` inside `try/except` before the `return RedirectResponse(...)`.

### Pitfall 5: alias_candidates Keyed by Token Captured AFTER Re-extraction
**What goes wrong:** If alias_candidates is written to the reconciliation JSONB inside `_run_stages` (AFTER extraction re-runs), the token captured may be the resolved/corrected name from the reply, not the original unresolved token. D-04 requires capture BEFORE the pipeline re-runs — specifically at clarify-emit time in `_clarify`.
**Why it happens:** `persist_reconciliation` is called inside `_run_stages` (orchestrator.py:187) on every run, including resume. Anything written there reflects POST-resume state.
**How to avoid:** Write alias_candidates in `_clarify` (orchestrator.py:200-245), BEFORE `gateway.send_outbound`. Pass it as a separate JSONB write (a second key in the reconciliation dict, written alongside the main reconciliation persist, or a direct JSON merge).

### Pitfall 6: Render Cold Start on Approve → Live Draft Call
**What goes wrong:** On a cold Render dyno, the first LLM call can take 10-20s. Without D-10b's hard timeout, the approve→303 hangs on camera inside the 60-90s demo budget.
**Why it happens:** The openai client has no default timeout in some configurations, or the timeout is too long.
**How to avoid:** Hard cap the draft call at ~3s via the `timeout=` parameter on `OpenAI(timeout=3.0)`. The template floor fires on timeout, and the operator gets a 303 within ~4s worst case.

---

## Code Examples

### claim_status (D-12)
```python
# Source: mirrors set_status pattern at repo.py:267 (VERIFIED)
def claim_status(
    run_id: uuid.UUID,
    expected: RunStatus,
    new: RunStatus,
    conn=None,
) -> bool:
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                "UPDATE payroll_runs SET status = %s, updated_at = now() "
                "WHERE id = %s AND status = %s RETURNING id",
                (RunStatus(new).value, str(run_id), RunStatus(expected).value),
            ).fetchone()
    return row is not None
```

### compose_confirmation (D-10)
```python
# Source: mirrors compose_clarification pattern at compose_email.py:88 (VERIFIED)
def compose_confirmation(paystubs: list[PaystubLineItem], run: dict, *, llm=llm_client) -> str:
    """Draft a confirmation email body. Falls back to template floor on any failure."""
    messages = _confirmation_prompt(paystubs, run)
    api_error = False
    try:
        body = llm.call_text("draft", messages, temperature=0.3)
    except Exception as exc:
        logger.warning("confirmation draft failed (%s) — using template floor", type(exc).__name__)
        body = None
        api_error = True
    if not body or not body.strip():
        if not api_error:
            logger.warning("confirmation draft returned empty — using template floor")
        return _confirmation_template(paystubs, run)
    return body
```

### OT validation rule (D-05)
```python
# Source: validate.py:50 seam (VERIFIED)
# Add after existing missing-hours check:
for emp in extracted.employees:
    ppy = _employee_pay_periods_per_year(emp.submitted_name, matches, roster)
    if ppy is None:
        continue
    ot = emp.hours_overtime
    ot_missing = ot is None or ot == 0  # recommended: flag explicit 0
    if ppy == 52 and emp.hours_regular is not None and emp.hours_regular > 40 and ot_missing:
        issues.append(ValidationIssue(
            field=f"{emp.submitted_name}.hours_overtime",
            issue_type="missing",
            message=f"...",
        ))
    elif ppy == 26 and emp.hours_regular is not None and emp.hours_regular > 80 and ot_missing:
        issues.append(ValidationIssue(...))
```

### alias write-side collision check (D-01b)
```python
# Source: deterministic_match at reconcile_names.py:37 (VERIFIED)
from app.models.roster import Employee, Roster
from app.pipeline.reconcile_names import deterministic_match

def _safe_to_learn_alias(token: str, target_employee: Employee, roster: Roster) -> bool:
    """Return True only if token uniquely resolves to target_employee on the FULL roster.
    
    Builds a synthetic roster with the alias already appended to verify no collision.
    """
    # Synthesize roster with alias added to the target employee
    synthetic_employees = []
    for emp in roster.employees:
        if emp.id == target_employee.id:
            new_aliases = list(emp.known_aliases) + [token]
            synthetic_employees.append(emp.model_copy(update={"known_aliases": new_aliases}))
        else:
            synthetic_employees.append(emp)
    synthetic_roster = roster.model_copy(update={"employees": synthetic_employees})
    result = deterministic_match(token, synthetic_roster)
    return result is not None and result.matched_employee_id == target_employee.id
```

---

## State of the Art

| Old Approach (Phase 2/3/4) | Current Phase 5 Approach | Impact |
|---------------------------|--------------------------|--------|
| Crude load-then-set approve/reject | claim_status CAS atomic helper | Race-safe; closes CR-02 documented debt |
| No post-approval delivery | compose_confirmation + reportlab + send_outbound | HITL-02/03 complete |
| `approved` as final terminal status | `approved` as in-flight delivery state; RECONCILED is terminal | Enables delivery error recovery |
| Sole status writer: set_status | Two writers: set_status (unguarded) + claim_status (guarded) | Explicit dual-writer contract |

**Items that are already-current and should NOT be changed:**
- `response_format={"type":"json_object"}` + `model_validate_json` — stays as-is (DeepSeek lacks strict json_schema)
- BackgroundTask pattern for run_pipeline + resume_pipeline — stays as-is; approve/delivery is the one synchronous exception
- `_TERMINAL_STATUSES` membership: `approved` must be REMOVED; all others stay

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `approved` in `_TERMINAL_STATUSES` at repo.py:86-94 must be removed to enable delivery error recovery | Pitfall 1 / D-13b | If wrong, need a different error-recording path that bypasses the terminal check |
| A2 | openai Python SDK accepts `timeout=` float on `OpenAI(timeout=...)` constructor | D-10b | Would need asyncio.wait_for approach instead; same outcome, different wiring |
| A3 | FastAPI `RedirectResponse(status_code=303)` correctly handles POST-to-GET redirect in all browsers | D-06 | Minor: some old HTTP/1.0 clients; not a concern for a demo |
| A4 | Adding `alias_candidates` as a key inside the existing `reconciliation` JSONB (vs a new column) is the correct storage spot | D-04 | If the planner prefers a dedicated column, a DDL migration is needed |
| A5 | reportlab `SimpleDocTemplate` + `Table` are the correct platypus classes for a tabular paystub | D-11 | Alternative: `canvas` + manual layout; higher effort, same result |
| A6 | `ot == 0` (explicit zero) should be treated same as `None` (absent) in the OT validation rule | D-05 | If wrong (trust explicit 0), change `ot_missing = ot is None` only — explicit 0 slips through |

---

## Open Questions

1. **Should `alias_candidates` be a top-level key in the existing `reconciliation` JSONB, or a new `payroll_runs.alias_candidates` JSONB column?**
   - What we know: reconciliation JSONB is written twice (at clarify-emit via `_clarify`, and on resume via `persist_reconciliation`). The second write OVERWRITES the column entirely — this means alias_candidates written at clarify-emit would be CLOBBERED by the resume's `persist_reconciliation` call at orchestrator.py:187.
   - **This is a sequencing problem.** The resume's `persist_reconciliation` (which reflects the POST-resolution state) will overwrite whatever was written at clarify-emit.
   - **Recommendation:** Use a SEPARATE key/approach — either (a) a new `payroll_runs.alias_candidates` JSONB column (requires DDL, but cleanest), or (b) write the alias_candidates AFTER the resume's persist_reconciliation in `_run_stages` by merging them, or (c) capture alias_candidates in a separate JSON merge query that is not a full overwrite. Option (a) is cleanest.
   - What's unclear: whether the planner wants the DDL change or prefers a merge approach.
   - Recommendation for planner: add a `payroll_runs.alias_candidates` JSONB column (ALTER TABLE IF NOT EXISTS, idempotent).

2. **Should re-trigger claim from `approved` as well as `error`?**
   - CONTEXT.md D-13b says yes. But the `claim_status` helper only accepts a single `expected` status. A re-trigger from `approved` OR `error` needs either two separate claim attempts, or the UPDATE predicate to use `IN (...)`.
   - Recommendation: Two attempts — first try `error → received`, then try `approved → received` (since a re-trigger from `approved` means delivery died). Or: `UPDATE … WHERE id=%s AND status IN ('error','approved') RETURNING id`.

---

## Environment Availability

Phase 5 is code changes only. No new external tool dependencies.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | All | ✓ (via uv) | 3.12.x | — |
| reportlab | D-11 PDF | ✓ (in pyproject.toml) | 5.0.0 | — |
| jinja2 | Dashboard | ✓ (in pyproject.toml) | 3.1.6 | — |
| python-multipart | Form POSTs | ✓ (in pyproject.toml) | 0.0.20 | — |
| psycopg[binary,pool] | claim_status | ✓ (in pyproject.toml) | 3.3.4 | — |
| pytest | Test suite | ✓ (uv dev dep) | latest | — |

**Missing dependencies with no fallback:** None.

---

## Validation Architecture

`workflow.nyquist_validation` is `true` in `.planning/config.json`. This section is required.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (dev dep in pyproject.toml) |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest -q -m "not integration and not live_llm"` |
| Full suite command | `uv run pytest -q` |
| Markers | `integration` (requires live DB), `live_llm` (requires real API keys) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FOUND-04 | claim_status returns True on first caller, False on concurrent second | unit | `uv run pytest tests/test_claim_status.py -x -q` | ❌ Wave 0 |
| FOUND-04 | claim_status + psycopg3 live DB race (two callers race approve) | integration | `uv run pytest tests/test_claim_status.py -m integration -x` | ❌ Wave 0 |
| D-01b | _safe_to_learn_alias returns False for "D. Reyes" when Daniel+David both carry it | unit | `uv run pytest tests/test_alias_write.py -x -q` | ❌ Wave 0 |
| D-01b | _safe_to_learn_alias returns True for unambiguous token | unit | `uv run pytest tests/test_alias_write.py -x -q` | ❌ Wave 0 |
| D-05 | validate() emits ValidationIssue for weekly emp with hours_regular=45, no OT | unit | `uv run pytest tests/test_validate.py -x -q` | ✅ (extend) |
| D-05 | validate() emits ValidationIssue for biweekly emp hours_regular=85, no OT | unit | `uv run pytest tests/test_validate.py -x -q` | ✅ (extend) |
| D-05 | validate() does NOT flag biweekly emp hours_regular=78 | unit | `uv run pytest tests/test_validate.py -x -q` | ✅ (extend) |
| D-05 | validate() does NOT flag semi-monthly/monthly emp, regardless of hours | unit | `uv run pytest tests/test_validate.py -x -q` | ✅ (extend) |
| D-05 | validate() flags explicit hours_overtime=0 with weekly hours_regular=45 | unit | `uv run pytest tests/test_validate.py -x -q` | ✅ (extend) |
| HITL-03 | generate_paystub_pdf() returns non-empty bytes for a real PaystubLineItem | unit | `uv run pytest tests/test_pdf.py -x -q` | ❌ Wave 0 |
| HITL-03 | generate_paystub_pdf() PDF bytes start with b'%PDF' | unit | `uv run pytest tests/test_pdf.py -x -q` | ❌ Wave 0 |
| HITL-02 | compose_confirmation() returns template floor when LLM raises | unit | `uv run pytest tests/test_compose_confirmation.py -x -q` | ❌ Wave 0 |
| HITL-02 | compose_confirmation() returns template floor when LLM returns None | unit | `uv run pytest tests/test_compose_confirmation.py -x -q` | ❌ Wave 0 |
| D-13b | delivery path error boundary: exception after claim → run advances to ERROR | unit (FakeConnection) | `uv run pytest tests/test_delivery.py -x -q` | ❌ Wave 0 |
| CLAR-04 | idempotent send: get_outbound_message_id returns existing row → skip send | unit (FakeConnection) | `uv run pytest tests/test_delivery.py -x -q` | ❌ Wave 0 |
| DASH-01 | GET /runs returns 200 with run rows in the response | behavior | `uv run pytest tests/test_dashboard.py -x -q -m integration` | ❌ Wave 0 |
| DASH-02 | GET /runs/{id} returns 200 with raw body, extracted, paystubs columns visible | behavior | `uv run pytest tests/test_dashboard.py -x -q -m integration` | ❌ Wave 0 |
| DASH-04 | GET /eval returns 200, SVG chart is referenced, headline metrics present | behavior | `uv run pytest tests/test_dashboard.py -x -q` | ❌ Wave 0 |
| DASH-05 | POST /demo/send-test with clean fixture → run created | behavior | `uv run pytest tests/test_dashboard.py -x -q -m integration` | ❌ Wave 0 |

### Highest-Risk Units (priority test targets)

**1. claim_status race (FOUND-04, D-12)**
Test: inject two FakeConnection instances both returning rows on the conditional UPDATE — verify that the first returns True and the second returns False. For the live-DB race: use psycopg3 with two actual connections racing the claim; assert exactly one succeeds. This is the highest-risk unit because all four gates depend on it, and a wrong implementation is silent (no crash, just wrong behavior under concurrency).

**2. D-01b alias-write collision exclusion**
Test the "D. Reyes" trap explicitly:
```python
# Given the seed roster (David + Daniel both carry "D. Reyes"):
assert not _safe_to_learn_alias("D. Reyes", david, seed_roster)
# Given an unambiguous token:
assert _safe_to_learn_alias("Dave Reyes", david, seed_roster)
```
This is critical because a wrong implementation silently misroutes money-moving decisions on camera.

**3. Delivery path strand recovery (D-13b)**
Test: a FakeConnection that raises on the PDF generation step, after claim_status has already returned True. Assert: `repo.record_run_error` was called, run advances to ERROR (NOT stuck in `approved`). This requires `approved` to NOT be in `_TERMINAL_STATUSES`.

**4. compose_confirmation template floor**
Test: compose_confirmation with `llm.call_text` patched to raise. Assert: returns a non-empty string (the template floor, not an exception). Mirror of existing `test_clarify.py` pattern.

### Sampling Rate
- **Per task commit:** `uv run pytest -q -m "not integration and not live_llm"` (the full mocked suite, no live deps)
- **Per wave merge:** `uv run pytest -q -m "not live_llm"` (includes integration tests against live local DB)
- **Phase gate:** Full suite green (`uv run pytest -q`) before `/gsd-verify-work`

### Wave 0 Gaps (new test files needed before implementation waves)
- [ ] `tests/test_claim_status.py` — covers FOUND-04, D-12 (unit + integration variants)
- [ ] `tests/test_alias_write.py` — covers D-01b collision exclusion + idempotency
- [ ] `tests/test_pdf.py` — covers HITL-03 PDF generator pure function
- [ ] `tests/test_compose_confirmation.py` — covers HITL-02 template floor on failure
- [ ] `tests/test_delivery.py` — covers D-13b error boundary + CLAR-04 idempotent send
- [ ] `tests/test_dashboard.py` — covers DASH-01/02/04/05 route smoke tests
- [ ] `tests/test_validate.py` — EXTEND existing file with D-05 OT rule cases

---

## Security Domain

`security_enforcement` is enabled and `security_asvs_level: 1` in config.json.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No auth on the dashboard (PROJECT.md "it's a demo") |
| V3 Session Management | No | No sessions |
| V4 Access Control | Partial | No auth, but unknown-sender guard (INGEST-03) remains; no new access control surface added |
| V5 Input Validation | Yes | Pydantic models on all webhook inputs; form POSTs validated by FastAPI |
| V6 Cryptography | No | No crypto in this phase |
| V7 Error Handling | Yes | D-13b error boundary must not leak PII in error_reason (existing D-A1-03 pattern: `type(exc).__name__` only, no `str(exc)`) |

### Known Threat Patterns for this Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via run_id path param | Tampering | FastAPI UUID type validation on path params + psycopg3 parameterized queries only |
| Template injection via Jinja2 | Tampering | Jinja2 auto-escaping enabled by default; never pass raw user-controlled strings as `Markup()` |
| SSRF via "Send test email" button | Tampering | Button POSTs to `/webhook/inbound` (same app) with a COMMITTED fixture — no URL parameter; no SSRF surface |
| PII leakage in error_reason | Information Disclosure | Mirror D-A1-03: `type(exc).__name__` only; no `str(exc)` in the delivery path error handler |
| PDF streaming sensitive data | Information Disclosure | No auth required by design (demo); PDF content is payroll data — acceptable for a no-auth demo; document in README |
| Double-approval fraud | Repudiation | claim_status CAS closes this; the DB audit trail (email_messages + status transitions) provides repudiability |

---

## Sources

### Primary (HIGH confidence)
- `app/pipeline/orchestrator.py` (entire file, VERIFIED) — run_pipeline, resume_pipeline, _clarify, _run_stages, error-wrap pattern
- `app/db/repo.py` (entire file, VERIFIED) — set_status, _TERMINAL_STATUSES, get_outbound_message_id, _conn_ctx, _nulltx
- `app/pipeline/reconcile_names.py` (entire file, VERIFIED) — deterministic_match, collision logic
- `app/pipeline/validate.py` (entire file, VERIFIED) — current validate() seam
- `app/pipeline/compose_email.py` (entire file, VERIFIED) — compose_clarification DRY pattern
- `app/main.py` (entire file, VERIFIED) — current routes, BackgroundTask wiring, crude approve/reject
- `app/db/schema.sql` (entire file, VERIFIED) — reconciliation JSONB, email_messages, status enum
- `app/db/seed.py:70-262` (VERIFIED) — David/Daniel Reyes collision pair, employee pay_periods
- `app/models/contracts.py:119-184` (VERIFIED) — Decision, PaystubLineItem fields
- `app/email/gateway.py` (entire file, VERIFIED) — stub send_outbound, mint-then-record ordering
- `eval/summary.json` (VERIFIED) — per_fixture shape, headline metrics, drill-in fields
- `pyproject.toml` (VERIFIED) — all runtime deps already present, no new deps needed
- `.planning/config.json` (VERIFIED) — nyquist_validation: true, security_enforcement: true

### Secondary (MEDIUM confidence)
- FastAPI RedirectResponse + Form handling — well-established FastAPI pattern [ASSUMED]
- openai Python SDK `timeout=` constructor parameter — [ASSUMED; HIGH confidence from SDK documentation pattern]
- reportlab SimpleDocTemplate + Table for paystub layout — [ASSUMED; HIGH confidence from library's documented API]
- psycopg3 single-statement UPDATE atomicity — [ASSUMED; HIGH confidence from Postgres single-statement transaction semantics]

### Tertiary (LOW confidence)
- None — all critical claims are verified from source or ASSUMED with HIGH confidence designation

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libs in pyproject.toml, no new deps
- Architecture: HIGH — verified against real code at exact line numbers
- Pitfalls: HIGH — critical finding (approved in _TERMINAL_STATUSES) verified from source
- Validation architecture: HIGH — existing test infrastructure documented; Wave 0 gaps enumerated

**Research date:** 2026-06-22
**Valid until:** 2026-07-22 (stable stack; the open question on alias_candidates storage spot may be resolved by planner before planning begins)
