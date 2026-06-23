---
phase: 05-dashboard-delivery
reviewed: 2026-06-22T00:00:00Z
depth: standard
files_reviewed: 15
files_reviewed_list:
  - app/db/repo.py
  - app/db/schema.sql
  - app/db/supabase.py
  - app/email/gateway.py
  - app/llm/client.py
  - app/main.py
  - app/pipeline/compose_email.py
  - app/pipeline/orchestrator.py
  - app/pipeline/pdf.py
  - app/pipeline/reconcile_names.py
  - app/pipeline/validate.py
  - app/templates/base.html
  - app/templates/eval.html
  - app/templates/run_detail.html
  - app/templates/runs_list.html
findings:
  critical: 3
  warning: 5
  info: 2
  total: 10
resolved:
  critical: 3   # CR-01, CR-02, CR-03 fixed in commits 3eb5993, c57756f, bb2f694; regression tests 4e4d741
  warning: 0    # WR-01..05 deferred (see resolution note below)
  info: 0
status: criticals_resolved
resolution_note: >
  All 3 Critical findings fixed during phase execution and verified (372 tests pass;
  CR-01 additionally verified with a live-DB round-trip of update_known_alias on the
  TEXT[] column). The 5 Warnings and 2 Info findings are deferred to follow-up
  (candidate 05.1 gap phase / todos): WR-01 reply-threading after crash+retrigger,
  WR-02 thread-unsafe pool singleton, WR-03 SELECT pr.* full-JSONB on runs-list,
  WR-04 Content-Disposition header injection via employee name, WR-05 fixture path
  containment; INFO-01 needs_clarification badge map gap, INFO-02 LLM retry echoes
  raw ValidationError content.
---

# Phase 05: Code Review Report

**Reviewed:** 2026-06-22
**Depth:** standard
**Files Reviewed:** 15
**Status:** issues_found

## Summary

Reviewed the Phase 5 delivery wave: claim-status CAS, the `_deliver` path, alias write-side learning loop, Jinja2 dashboard, and all supporting layers. The deterministic decision flow (reconcile → decide) is correctly kept free of model output — `decide.py` and `reconcile_names.py` are pure code with no LLM call or confidence gate, satisfying the load-bearing thesis invariant.

Three critical defects found. Two are runtime crashes that will always fire in production (the `known_aliases` type mismatch corrupts every alias write; the missing `updated_at` in `RUN_COLS` silently disables the stale-run recovery guard). The third is a silent data quality failure: `confirmation_subject()` and `compose_confirmation()` always produce fallback values ("Payroll Run" / blank period) because `load_run()` never returns `business_name` or `pay_period_label`. Five warnings and two info items round out the report.

---

## Critical Issues

### CR-01: `update_known_alias` uses JSONB operators on a `TEXT[]` column — runtime crash on every alias write

**File:** `app/db/repo.py:495-509`
**Issue:** The schema declares `employees.known_aliases` as `TEXT[]` (line 32 of `schema.sql`), but `update_known_alias` issues SQL using JSONB-specific operators and functions against that column:

- `known_aliases || to_jsonb(ARRAY[%s::text])` — `TEXT[] || jsonb` is a PostgreSQL type error
- `jsonb_array_elements_text(known_aliases ...)` — expects `jsonb` input, receives `TEXT[]`
- `known_aliases @> to_jsonb(...)` — `@>` on `TEXT[]` with `jsonb` operand is a type error
- `jsonb_agg(DISTINCT elem)` — result is `jsonb`, which cannot be assigned back to `TEXT[]`

Every call to `update_known_alias` (the alias write-side learning loop, called from `_write_aliases_if_safe` during approval) will raise a PostgreSQL `ERROR: operator does not exist: text[] @> jsonb` (or similar). This means the alias learning loop **never works** — every approval silently swallows the error (wrapped by `_deliver`'s `try/except`) and the roster never learns new aliases.

**Fix:** Either rewrite the SQL to use native `TEXT[]` array operators, or change the schema to `JSONB`. The `TEXT[]` path is simpler and consistent with the schema:

```sql
UPDATE employees
SET known_aliases = array_append(known_aliases, %s)
WHERE id = %s
  AND NOT (%s = ANY(known_aliases))
RETURNING id
```

Or to match the deduplication intent:
```sql
UPDATE employees
SET known_aliases = array(SELECT DISTINCT unnest(known_aliases || ARRAY[%s::text]))
WHERE id = %s
  AND NOT (%s = ANY(known_aliases))
RETURNING id
```

---

### CR-02: `updated_at` not in `RUN_COLS` — stale-run retrigger guard silently always skips, stale runs are permanently stuck

**File:** `app/db/repo.py:79-82`, `app/main.py:379-381`
**Issue:** `RUN_COLS` (the column list used by `load_run()`) does not include `updated_at`:

```python
RUN_COLS = (
    "id, business_id, source_email_id, status, extracted_data, decision,"
    " reconciliation, error_reason, pay_period_start, pay_period_end"
)
```

The `retrigger` handler in `main.py` reads `updated_at` from the dict returned by `load_run()`:

```python
updated_at = run.get("updated_at")  # always None
stale = (
    updated_at is not None              # always False
    and datetime.now(tz=timezone.utc) - updated_at > STALE_THRESHOLD
)
```

Because `updated_at` is always `None`, `stale` is always `False`. The entire stale in-flight recovery branch (`RunStatus.RECEIVED`, `EXTRACTING`, `COMPUTED`, `SENT`) is permanently disabled. A run stuck in any of those states cannot be retriggered — the operator's "Re-trigger" button silently redirects with no action taken.

**Fix:** Add `updated_at` to `RUN_COLS`:

```python
RUN_COLS = (
    "id, business_id, source_email_id, status, extracted_data, decision,"
    " reconciliation, error_reason, pay_period_start, pay_period_end, updated_at"
)
```

---

### CR-03: `confirmation_subject()` and `compose_confirmation()` always use fallback values — confirmation email sent with wrong subject and no business name

**File:** `app/pipeline/compose_email.py:181-183`, `app/pipeline/orchestrator.py:466-554`, `app/db/repo.py:79-82`
**Issue:** `confirmation_subject(run)` calls `run.get("business_name", "Payroll Run")` and `run.get("pay_period_label", "")`. Neither `business_name` nor `pay_period_label` is present in the `run` dict passed to `_deliver`.

In `_deliver` (called from the `approve` handler in `main.py` line 315-317), `run = repo.load_run(run_id)` — which uses `RUN_COLS`. `RUN_COLS` contains neither `business_name` (a computed JOIN from `businesses.name`) nor `pay_period_label` (a non-existent column — `payroll_runs` has `pay_period_start`/`pay_period_end`, not a pre-formatted label).

Every confirmation email will be sent with subject `"Payroll Confirmation — Payroll Run — "` instead of the intended `"Payroll Confirmation — Coastal Cleaning — 2026-06-01 to 2026-06-07"`. This is a visible data quality failure on the single human-facing output of the pipeline.

**Fix:** `_deliver` needs a business name. Two options:

Option A — Load business name in `_deliver` before calling confirmation helpers:
```python
# In _deliver, after existing = ...:
biz_row = conn.execute("SELECT name FROM businesses WHERE id = %s",
                       (str(run["business_id"]),)).fetchone()
run = dict(run)
run["business_name"] = biz_row[0] if biz_row else "Payroll Run"
run["pay_period_label"] = (
    f"{run.get('pay_period_start')} to {run.get('pay_period_end')}"
    if run.get("pay_period_start") and run.get("pay_period_end")
    else ""
)
```

Option B — Add `business_name` to `RUN_COLS` by changing `load_run` to JOIN `businesses`, or create a separate `load_run_with_business` helper used by `_deliver` and the dashboard.

---

## Warnings

### WR-01: `insert_email_message` upsert overwrites `message_id` on conflict — breaks reply threading after crash + retrigger

**File:** `app/db/repo.py:556-562`
**Issue:** The `ON CONFLICT (run_id, purpose) DO UPDATE` clause updates `message_id = EXCLUDED.message_id`. If a clarification email is sent (or partly recorded as `send_state='reserved'`) and then the run is retriggered, `_clarify`'s idempotency guard checks `get_outbound_message_id(..., send_state='sent')`. A `reserved` row returns `None` from that guard, so `_clarify` calls `send_outbound` again with a fresh `uuid4` `message_id`. The upsert then replaces the stored `message_id` with the new one. Any client reply that already arrived with `In-Reply-To: <old-uuid@...>` will no longer match `find_awaiting_reply_for_header`, breaking the reply-threading chain permanently for that run.

This scenario only occurs when a crash happens between the `reserved` write and the `sent` flip — a Phase 6 / live-provider concern, but the upsert behavior is present now.

**Fix:** The `DO UPDATE` clause should NOT update `message_id` — once a `message_id` has been communicated to the external party (even provisionally), it must be preserved. Only `send_state` (and possibly `body_text`/`subject`) should be updated on conflict:

```sql
ON CONFLICT (run_id, purpose) DO UPDATE
    SET send_state = EXCLUDED.send_state,
        subject = EXCLUDED.subject,
        body_text = EXCLUDED.body_text,
        created_at = now()
-- Do NOT update message_id: the ID already sent to the client must remain stable.
```

---

### WR-02: `get_pool()` singleton initialization is not thread-safe — two concurrent requests can create duplicate pools

**File:** `app/db/supabase.py:37-51`
**Issue:** `get_pool()` uses a `global _pool` check-then-act pattern without a lock:

```python
if _pool is None:
    # ... two threads can both enter here simultaneously
    _pool = ConnectionPool(...)
```

FastAPI runs synchronous routes in a thread pool under uvicorn. Two simultaneous cold requests can both see `_pool is None` and both create a `ConnectionPool`, leaking one (the background worker thread inside the overwritten pool is orphaned and never closes).

**Fix:** Use `threading.Lock`:

```python
import threading
_pool_lock = threading.Lock()

def get_pool() -> ConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:   # double-checked locking
            settings = get_settings()
            _pool = ConnectionPool(...)
    return _pool
```

---

### WR-03: `load_all_runs` uses `SELECT pr.*` — adds all `payroll_runs` columns including large JSONB blobs to every runs-list query

**File:** `app/db/repo.py:755`
**Issue:** `load_all_runs` uses `"SELECT pr.*, b.name as business_name"`. The runs-list page only displays `id`, `created_at`, `business_name`, `status`, `decision.gate_reasons[0]`, and `extracted_data.employees | length`. But `SELECT *` fetches the full `extracted_data`, `decision`, `reconciliation`, and `alias_candidates` JSONB columns for every row — potentially large blobs on every page load. The comment elsewhere in `repo.py` calls out that `SELECT *` is a violation of the module's discipline.

**Fix:** Use an explicit column list matching what the template actually reads:

```python
sql = (
    "SELECT pr.id, pr.status, pr.created_at, pr.decision, pr.extracted_data,"
    " b.name as business_name"
    " FROM payroll_runs pr"
    " JOIN businesses b ON pr.business_id = b.id"
    " ORDER BY pr.created_at DESC"
)
```

---

### WR-04: `Content-Disposition` header in PDF route is injectable via employee full name — malformed/broken headers for names containing `"` or `\n`

**File:** `app/main.py:547-551`
**Issue:** The `safe_name` transformation only replaces spaces with underscores:

```python
safe_name = emp_name.replace(" ", "_")
headers={"Content-Disposition": f'attachment; filename="paystub_{safe_name}.pdf"'}
```

An employee name containing a double-quote (e.g., `O"Brien, Pat`) produces a malformed header: `attachment; filename="paystub_O"Brien,_Pat.pdf"`. A name containing `\r\n` would inject a new header line. Employee names come from the database (`emp.full_name` or `item.submitted_name`) which originate from the LLM extraction stage and ultimately from untrusted email input.

**Fix:** Strip all non-safe characters from the filename and use RFC 6266 `filename*` encoding for non-ASCII:

```python
import re
safe_name = re.sub(r'[^\w\-.]', '_', emp_name)
# Or at minimum: safe_name = emp_name.replace('"', '').replace('\n', '').replace('\r', '').replace(' ', '_')
```

---

### WR-05: `eval_view` has no path containment guard on `fixture["fixture_path"]` — path traversal from a crafted `eval/summary.json`

**File:** `app/main.py:490-495`
**Issue:** The fixture path from `eval/summary.json` is joined directly to `eval/fixtures/` without checking that the resolved path stays within that directory:

```python
fixture_file = fixtures_dir / fixture["fixture_path"]
if fixture_file.exists():
    fixture_data = json.loads(fixture_file.read_text())
```

A `fixture_path` of `../../app/config.py` resolves to `app/config.py`. In the demo context `eval/summary.json` is a committed artifact and not user-controlled at runtime, but this is a defense-in-depth gap: any workflow that writes `eval/summary.json` (including the eval runner) could inadvertently include a traversal path.

**Fix:** Add a containment check after constructing the path:

```python
fixture_file = (fixtures_dir / fixture["fixture_path"]).resolve()
fixtures_root = fixtures_dir.resolve()
if not str(fixture_file).startswith(str(fixtures_root) + "/"):
    fixture["raw_body"] = "‹invalid fixture path›"
    continue
if fixture_file.exists():
    ...
```

---

## Info

### IN-01: `needs_clarification` status value is defined in `RunStatus` and `schema.sql` but absent from `_BADGE_CLASS` and `_BADGE_LABEL`

**File:** `app/main.py:76-103`
**Issue:** `RunStatus.NEEDS_CLARIFICATION = "needs_clarification"` exists in the model and in the schema CHECK constraint, but is not present in either `_BADGE_CLASS` or `_BADGE_LABEL`. If a run ever reaches this status, the badge renders with class `"neutral"` and label `"Needs Clarification"` (fallback title-case), which is acceptable but inconsistent with the explicit copy contract for other statuses. The orchestrator never writes this status today (the `_clarify` path writes `AWAITING_REPLY`), so this is currently dead code.

**Fix:** Either add `"needs_clarification": ("neutral", "Needs Clarification")` to both maps for correctness, or remove `NEEDS_CLARIFICATION` from `RunStatus` and the schema CHECK list if it's truly unused. Leaving an unreachable status value in the enum and schema is misleading.

---

### IN-02: `call_structured` retry prompt includes raw `ValidationError` message — LLM extraction output (potentially containing employee names / hours) echoed back to the LLM provider

**File:** `app/llm/client.py:146`
**Issue:** On a schema-validation failure, the retry prompt is:

```python
f"Your last output failed validation: {exc}. Return ONLY valid JSON matching the schema."
```

Pydantic `ValidationError.__str__()` includes the actual bad values from the model's response — e.g., `value_error: ... got 'Maria Chen'`. Since the extraction model may include PII (employee names, hours figures) in its malformed output, this echo is sent back to the LLM provider's API. This is not a security issue (it's still within the same provider session), but it is a PII-in-logs/PII-in-prompt hygiene concern consistent with the project's stated `D-A1-03` policy of not echoing PII.

**Fix:** Log only the error type and strip values from the retry prompt:

```python
convo = convo + [{
    "role": "user",
    "content": (
        f"Your last output failed validation ({type(exc).__name__}). "
        "Return ONLY valid JSON matching the schema, with all required fields."
    ),
}]
```

---

_Reviewed: 2026-06-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
