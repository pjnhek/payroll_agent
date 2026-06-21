---
phase: 02-walking-skeleton
reviewed: 2026-06-21T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - app/db/repo.py
  - app/email/clean.py
  - app/email/gateway.py
  - app/llm/client.py
  - app/llm/prompts/clarify.py
  - app/llm/prompts/decide.py
  - app/llm/prompts/extract.py
  - app/llm/prompts/reconcile.py
  - app/models/contracts.py
  - app/models/reconcile.py
  - app/pipeline/calculate.py
  - app/pipeline/compose_email.py
  - app/pipeline/decide.py
  - app/pipeline/extract.py
  - app/pipeline/orchestrator.py
  - app/pipeline/reconcile_names.py
  - app/pipeline/validate.py
  - app/main.py
findings:
  critical: 2
  warning: 6
  info: 5
  total: 13
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-06-21
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

This is a carefully-built walking skeleton. The thesis property — a **code-owned
`final_action` that the orchestrator branches on, never `model_action`** — is
implemented correctly and is the load-bearing achievement of the phase:

- The gate evaluates confidence **per name** (`decide.py:140-146`), not against a
  collapsed scalar, so a single sub-0.8 name cannot hide behind high-confidence
  peers. The `min()` scalar at `decide.py:168` is correctly documented as
  audit-only and is never the gate input.
- Threshold is `< Decimal("0.8")` (`decide.py:51, 141`) — correct strictness
  (0.8 itself passes, which is the documented intent) and Decimal-vs-Decimal
  comparison throughout (`NameMatchResult.confidence` is `Decimal`).
- The orchestrator branches **solely** on `decision.final_action`
  (`orchestrator.py:159`); `model_action` never drives control flow downstream.
- `NameMatchResult.confidence` is bounded `le=1` (`roster.py:146`), so a model
  trying to dodge the gate by returning `confidence: 9.99` fails Pydantic
  validation → retry → ERROR. This is a real, closed injection vector.
- All SQL in `repo.py` is `%s`/named-placeholder parameterized; the two
  `"SELECT " + COLS` concatenations (`repo.py:188, 490`) use trusted module
  constants with no external input, and values stay parameterized. No injection.
- Money/hours are `Decimal` throughout the calc path; `_money()` quantizes to
  cents. No float creep in the monetary path.
- The LLM client does exactly one reflective retry then raises (`client.py:120`),
  uses `temperature=0` + `json_object` (not `.parse()`), and treats DeepSeek empty
  content as a failure.

**However**, there are two correctness holes that let a degenerate run reach a
`process` decision, plus several robustness/observability gaps. The most serious
is an **empty-matches gate bypass**: a run that extracts zero employees sails
through the gate to `awaiting_approval` as a zero-line-item payroll if the model
says "process". Details below.

## Critical Issues

### CR-01: Empty-matches / empty-extraction bypasses the gate to `process`

**File:** `app/pipeline/decide.py:136-163` (and `orchestrator.py:142-163`)

**Issue:** The gate is *reason-additive*: it only blocks when it can append a
`gate_reason`. Every gate rule iterates over `matches` or `issues`. If
`matches == []` and `issues == []`, **no rule fires**, `gate_reasons` stays
empty, `gate_fired` is `False`, and `final_action = model_action`. A run that
extracted **zero employees** (an empty or junk email, or a prompt-injected email
crafted to yield `"employees": []`) therefore reaches the gate with empty inputs;
if the advisory model returns `model_action="process"` (the decide prompt does
not forbid "process" on an empty roster), the run proceeds:

```
orchestrator.py:159  if decision.final_action == "process":
orchestrator.py:160      line_items = _compute_line_items(...)   # → [] (no employees)
orchestrator.py:161      repo.replace_line_items(run_id, [])      # deletes, inserts nothing
orchestrator.py:162-163  set_status(COMPUTED) → AWAITING_APPROVAL
```

The operator is then asked to approve an **empty payroll run** that the system
asserts is clean. The whole thesis is "a low-confidence/unresolved name can never
reach a real payroll calculation" — but a run with *no resolvable employees at
all* is the degenerate case that slips through, because the gate has nothing to
iterate over. `confidence` even defaults to `Decimal("1.0")` (`decide.py:169`),
falsely signaling maximum confidence on a zero-employee run.

**Fix:** Make the gate fail-closed on an empty/degenerate run. The orchestrator
already knows the extracted employee count; gate on it explicitly inside
`decide()` (it has `extracted`):

```python
# Rule 0 — a run with no extractable employees is never auto-processable.
if not extracted.employees:
    gate_reasons.append("no employees could be extracted from the email")
# (existing rules 1–4 follow)
```

Equivalently, guard at the branch: `if decision.final_action == "process" and
line_items:` — but gating in `decide()` is correct because `final_action` is the
single source of truth and the dashboard/eval read it.

### CR-02: Resume can process a stale run on a status race — `resume_pipeline` re-asserts `EXTRACTING` without re-checking the run is still `awaiting_reply`

**File:** `app/pipeline/orchestrator.py:82-110` (with `main.py:133-165`)

**Issue:** The CLAR-03 invariant is "a late reply must not resume a
sent/reconciled run." That invariant is enforced **only** in `main.py`’s
`_route_reply`, which checks `find_awaiting_reply_for_header` (status-restricted)
at webhook time. But the actual resume work runs later in a `BackgroundTask`
(`_resume_pipeline` → `resume_pipeline`), and `resume_pipeline` itself
**unconditionally** loads the run and calls `set_status(run_id,
RunStatus.EXTRACTING)` (`orchestrator.py:109`) with **no status precondition**.

Between the webhook’s `find_awaiting_reply_for_header` check and the background
task running, the run’s status can change (operator approves the *first*
computed result via a concurrently-arriving path, a second reply for the same
run, a re-delivery). `resume_pipeline` will then yank an `approved`/`computed`/
`sent` run back to `EXTRACTING` and re-run the whole gate path, overwriting
`extracted_data`, replacing line items, and landing it back at
`awaiting_approval` — silently discarding a human approval. `main.py` even sets
`EXTRACTING` a *second* time at `main.py:159` before scheduling, widening the
window where the run is mutated outside any precondition.

This is the data-loss face of the resume design: the status guard is not where
the mutation is, so it is not atomic with it.

**Fix:** Make `resume_pipeline` itself fail-closed on the precondition, inside
the same transaction that flips the status (use `FOR UPDATE` so the check and the
transition are atomic — `psycopg` `conn.transaction()` + a guarded `set_status`):

```python
run = repo.load_run(run_id)
if run is None:
    raise ValueError(f"run {run_id} not found")
if run["status"] != RunStatus.AWAITING_REPLY.value:
    logger.info("resume aborted: run %s is %s, not awaiting_reply",
                run_id, run["status"])
    return  # not an error — a late/duplicate reply, drop it
```

Also remove the redundant `set_status(EXTRACTING)` at `main.py:159` — the
orchestrator owns that transition (`orchestrator.py:109`), and doing it twice
across two contexts is exactly the seam this bug lives in.

## Warnings

### WR-01: `_compute_line_items` silently drops resolved-but-not-in-roster employees

**File:** `app/pipeline/orchestrator.py:204-208`

**Issue:** On a `process` run, if a match has a `matched_employee_id` that is not
present in `emp_by_id` (roster loaded for a *different* business, or a stale
reconciliation persisted from a prior resume against a since-changed roster),
the loop `continue`s and the employee is **silently omitted** from the payroll —
no error, no gate, no log. The run still reaches `awaiting_approval` as if
complete. Given the gate guarantees a `process` run has only resolved names, a
missing roster employee here is an *invariant violation*, not an expected skip,
and should be loud.

**Fix:** Treat a resolved match with no roster employee as an error condition:

```python
employee = emp_by_id.get(m.matched_employee_id)
if employee is None:
    raise ValueError(
        f"process-run integrity: matched employee {m.matched_employee_id} "
        f"for {ee.submitted_name!r} not in roster"
    )
```

### WR-02: Header-chain `LIKE` can false-match an unrelated run via Message-ID substring

**File:** `app/db/repo.py:450-451, 472-473`

**Issue:** `%(references)s LIKE '%%' || em.message_id || '%%'` matches if the
reply’s `References` header *contains* the stored outbound Message-ID as a
substring. Synthetic IDs are `<uuid4@payroll-agent.local>` so collisions are
unlikely *today*, but the match is unanchored: any stored `message_id` that is a
substring of another (or of arbitrary attacker-supplied `References` text) will
match. A real provider’s Message-IDs (P6) are not guaranteed substring-disjoint.
Because `find_any_run_for_header` is unrestricted by status, a crafted
`References` value could resolve to an arbitrary run id for observability log
lines (low blast radius now, but a latent routing-confusion bug).

**Fix:** Match the full angle-bracketed token rather than a bare substring, e.g.
require the surrounding `<`/`>` to be present, or split the `References` header
into tokens in Python and compare equality. At minimum, document that synthetic
IDs are uuid4 and add a test asserting no two stored IDs are substrings.

### WR-03: `call_text` empty-content failure silently degrades to a templated email with no signal

**File:** `app/llm/client.py:180-188`, `app/pipeline/compose_email.py:71-74`

**Issue:** This is intended behavior (a draft failure must not strand the run),
but `call_text` returns `None` on *any* falsy content and `compose_clarification`
falls back to the template with **no log**. If the draft tier is misconfigured
(wrong key, wrong model id) *every* clarification silently uses the template and
the failure is invisible during the demo — exactly when you want to know the LLM
draft path is dead. Note also `call_text` does **not** catch exceptions: an API
error (auth, rate limit) raises out of `compose_clarification` →
`orchestrator._clarify` → caught by the run-level wrap → the run goes to **ERROR**
instead of falling back to the template. So the "draft failure never strands the
run" guarantee only holds for *empty content*, not for an API error.

**Fix:** Log the fallback at `compose_email.py:73` (`logger.warning("draft
empty — using templated clarification body")`), and wrap the `call_text` call in
`compose_clarification` in a `try/except` so an API error also falls back to the
template rather than ERRORing the run:

```python
try:
    body = llm.call_text("draft", messages, temperature=0.3)
except Exception:
    logger.warning("draft call failed — using template", exc_info=True)
    body = None
```

### WR-04: `record_run_error` overwrites the status even when the run is already terminal

**File:** `app/db/repo.py:264-278`, `app/pipeline/orchestrator.py:65, 114`

**Issue:** Any unhandled exception in the resume path routes through
`record_run_error`, which **unconditionally** sets status to `ERROR`. Combined
with CR-02, a late/duplicate reply that resumes an `approved` or `sent` run and
then hits an exception will flip a terminal, human-approved run to `ERROR`,
destroying the run’s real state and the approval audit trail. Even absent CR-02,
`record_run_error` should not blindly clobber `sent`/`reconciled`/`approved`.

**Fix:** Guard the ERROR transition on a non-terminal status, or make
`record_run_error` a no-op (log only) when the run is already in a terminal
state. The clean fix is CR-02 (don’t resume terminal runs), but defense-in-depth
here is cheap.

### WR-05: `clarification_subject` ignores its `decision` argument (dead parameter / misleading API)

**File:** `app/pipeline/compose_email.py:77-79`

**Issue:** `clarification_subject(decision)` takes a `Decision` and returns a
constant `_SUBJECT`, ignoring the argument entirely. This is a misleading
signature — a caller reasonably expects the subject to reflect the decision. It
also means clarification threads share an identical subject, which can confuse a
real provider’s subject-based threading fallback (deferred to P6, but the seam is
here). Either use the argument or drop it.

**Fix:** Drop the unused parameter (`def clarification_subject() -> str`) and
update the call site `orchestrator.py:189`, or incorporate a run/decision detail
into the subject. Removing the parameter is the honest minimum.

### WR-06: `_money` docstring claims "banker-safe" but uses `ROUND_HALF_UP` (not banker's rounding)

**File:** `app/pipeline/calculate.py:48-50`

**Issue:** The docstring says `"banker-safe HALF_UP for currency"`. `ROUND_HALF_UP`
is *not* banker's rounding — banker's rounding is `ROUND_HALF_EVEN`. The
*behavior* (`ROUND_HALF_UP`) is a defensible choice for payroll, but the comment
is actively wrong and will mislead the next reader (and the IRS Pub 15-T port in
Phase 3, where rounding mode is correctness-relevant). This is a documentation
bug on the highest-bug-risk module.

**Fix:** Correct the comment to state the actual mode and rationale: `"round to
cents, ROUND_HALF_UP (round half away from zero) — standard payroll rounding,
not banker's rounding"`.

## Info

### IN-01: `last_error` retry-feedback branch is effectively unreachable / overly defensive

**File:** `app/llm/client.py:119, 141-145`

**Issue:** On attempt 2, if the failure is a `ValueError` (empty content) and a
prior `ValidationError` was stored, the code raises the *stored* `last_error`.
But `last_error` is only set when attempt-1 failed with a `ValidationError`
(`client.py:146-147`); an attempt-1 empty-content `ValueError` does not set it,
so the `from_exception_data(...)` fallback at `client.py:143` is the realistic
path for "empty, then empty". The logic is correct but the branching is hard to
follow for a 2-iteration loop. Consider flattening to two explicit attempts.

**Fix:** Optional. A flat `try attempt 1 / on fail append feedback / try attempt
2 / raise` reads more obviously than the `for attempt in (1, 2)` with embedded
`if attempt == 2` branches.

### IN-02: `calculate()` stamps placeholder `run_id=uuid.uuid4()` then relies on the caller to overwrite

**File:** `app/pipeline/calculate.py:106`, `orchestrator.py:218-224`

**Issue:** `calculate()` constructs a `PaystubLineItem` with a throwaway
`run_id=uuid.uuid4()` and a placeholder `submitted_name=employee.full_name` /
`match_confidence=Decimal("1.0")`, which the orchestrator then `model_copy`s over.
If a future caller forgets the overwrite, line items get a random orphan `run_id`
and a fake 1.0 confidence with no error. The contract (`PaystubLineItem.run_id`
required) makes the placeholder necessary, but it’s a footgun.

**Fix:** Optional. Pass `run_id` / `submitted_name` / `match_confidence` into
`calculate()` as parameters so the value is correct at construction and there is
no placeholder to forget.

### IN-03: `clean_body` cuts at the *first* `>` line, can over-truncate a legitimate body

**File:** `app/email/clean.py:50-60`

**Issue:** The first line starting with `>` truncates everything below it. A
legitimate payroll line like `> 40 hrs Jane (per our call)` or a quoted figure in
the *current* message would drop the rest of the body, including unmentioned
employees. Acceptable for the Phase 2 fixtures (documented), but the truncation
is aggressive and silent. Worth a fixture asserting a body with an inline `>` is
not mangled.

**Fix:** Optional for Phase 2. Note in the docstring that an inline `>` mid-body
is a known false-positive deferred to the P6 reply-parser.

### IN-04: Two `OpenAI()` clients constructed per call (no reuse)

**File:** `app/llm/client.py:110, 174`

**Issue:** Every `call_structured` / `call_text` constructs a fresh `OpenAI(...)`
client. Functionally correct and out of the v1 perf scope, but it also means the
underlying `httpx` connection pool is rebuilt each call. Noted only because it’s
a trivial, low-risk cleanup if a tier client is cached alongside `get_settings()`.

**Fix:** Optional. Cache the client per resolved tier (e.g. `@lru_cache` on a
`(base_url, api_key, model)` factory).

### IN-05: `find_business_by_sender` is an exact-equality email match — case/whitespace sensitive

**File:** `app/db/repo.py:148-151`, used in spoof guard `main.py:143`

**Issue:** `WHERE contact_email = %s` is exact. Email addresses are
case-insensitive in the domain part (and commonly the local part too). A sender
`Owner@Acme.com` vs a stored `owner@acme.com` returns `None` → unknown sender →
run dropped, *and* on the reply path the spoof guard rejects a legitimate reply.
This is a correctness-adjacent robustness gap, but for the controlled fixtures
it’s benign. Flag because the same comparison gates both ingest access-control
and the reply spoof guard, so a case mismatch fails *closed* (safe) but
surprising.

**Fix:** Optional. Normalize with `lower(contact_email) = lower(%s)` (and seed
addresses lowercased), or document the case-sensitivity as an intentional Phase 2
simplification.

---

_Reviewed: 2026-06-21_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
