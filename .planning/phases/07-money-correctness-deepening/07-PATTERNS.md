# Phase 7: Money-Correctness Deepening — Pattern Map

**Mapped:** 2026-06-27
**Files analyzed:** 10 new/modified files
**Analogs found:** 10 / 10

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `app/pipeline/validate.py` (modify) | pure-function judgment | transform | self (existing `any_hours` + D-05 OT guard) | exact — editing in place |
| `app/pipeline/reconcile_names.py` (modify `_norm`) | pure-function normalizer | transform | self (existing `_norm` at line 32) | exact — editing in place |
| `app/models/contracts.py` (modify `ValidationIssue` + new `FieldDrop`) | model/contract | — | existing `ValidationIssue` (roster.py:205) + `ExtractedEmployee` (contracts.py:60) | exact — same model style |
| `app/pipeline/decide.py` (modify Rule 2 + new Rule 2b) | pure-function judgment | transform | existing Rule 2 at decide.py:124 | exact — symmetric new rule |
| `app/db/schema.sql` (add 2 JSONB columns) | schema DDL | — | `alias_candidates` column declare + ALTER block (schema.sql:90, 107) | exact — same column style |
| `app/db/repo.py` (4 new helpers) | data-access | CRUD | `set_alias_candidates` (repo.py:509) + `persist_extracted` (repo.py:407) + `claim_status` (repo.py:342) | exact — same pattern |
| `app/pipeline/orchestrator.py` (modify `_clarify` + `_run_stages` + `resume_pipeline`) | orchestrator | request-response | `_clarify` (orchestrator.py:292), `resume_pipeline` (orchestrator.py:94), `_run_stages` (orchestrator.py:260) | exact — editing in place |
| `eval/run_eval.py` (modify `_normalize`) | eval utility | transform | existing `_normalize` (run_eval.py:51) | exact — editing in place |
| `eval/fixtures/16_*.json` + `_extraction.json` (new) | eval fixture pair | — | `eval/fixtures/07_missing_hours_coastal.json` + `_extraction.json` | exact — same structure |
| `tests/test_validate.py` (new/modify) | test | — | existing test files (`tests/test_*.py`) | role-match |

---

## Pattern Assignments

### 1. `app/pipeline/validate.py` — `_is_paid` predicate + `any_hours` fix + `prior=` seam

**Analog:** self — `validate.py` lines 84–100 (existing `any_hours`) and lines 102–141 (D-05 OT guard)

**Current `any_hours` gate (line 84–88) — THE BUG TO FIX:**
```python
# validate.py:84–88 — CURRENT (D-01 bug: Decimal("0") passes the gate)
any_hours = any(
    getattr(emp, f) is not None for f in _HOURS_FIELDS
)
if any_hours:
    continue
```

**D-05 OT guard predicate (line 113) — the `_is_paid` PRECEDENT to mirror:**
```python
# validate.py:113 — existing "explicit zero = absent" pattern (D-09 precedent)
ot_missing = ot is None or ot == 0  # D-05: explicit zero treated same as absent
```

**Current `validate()` signature (lines 69–73) — shows WHERE `prior=None` kwarg slots in:**
```python
# validate.py:69–73 — CURRENT (D-17/D-18: add `prior: Extracted | None = None` as 4th param)
def validate(
    extracted: Extracted,
    roster: Roster,
    matches: list[NameMatchResult],
) -> list[ValidationIssue]:
```

**`_HOURS_FIELDS` tuple (lines 27–33) — `detect_field_regression` MUST reuse this, not redefine it:**
```python
# validate.py:27–33 — module-level constant; import/reuse in detect_field_regression (DRY, D-09)
_HOURS_FIELDS = (
    "hours_regular",
    "hours_overtime",
    "hours_vacation",
    "hours_sick",
    "hours_holiday",
)
```

**Module-level docstring pattern (lines 1–21) — new helpers must follow same docstring style:**
The existing docstring explicitly lists what `validate` does NOT do (FIX 1 block at lines 15–21). Any new module-level comments for `_is_paid` / `detect_field_regression` should follow the same "what it does / what it does NOT do" pattern.

**Imports block (lines 22–25) — where to add `Extracted` type import for `prior=` kwarg:**
```python
# validate.py:22–25 — CURRENT imports
from __future__ import annotations

from app.models.contracts import Extracted
from app.models.roster import NameMatchResult, Roster, ValidationIssue
```
`Extracted` is already imported. Add `FieldDrop` from `app.models.contracts` when `detect_field_regression` is added.

**New helper placement:** Place `_is_paid` immediately after `_HOURS_FIELDS` (before `_employee_pay_type`). Place `detect_field_regression` between `_employee_pay_periods_per_year` (line 66) and `validate()` (line 69).

**D-15 note for planner:** `validate()` gains a second new kwarg: `resolved_drops: set[tuple[UUID, str]] | None = None`. This set is built in `resume_pipeline` from the `confirmed_dropped` entries in `clarified_fields` BEFORE calling `_run_stages`. The `any_hours` gate inside `validate()` skips MONEY-01 for `(employee_id, field)` pairs present in `resolved_drops` — so a field the client explicitly zeroed does not re-trigger clarification.

---

### 2. `app/pipeline/reconcile_names.py` — `_norm` NFC fix

**Analog:** self — `reconcile_names.py` lines 32–34

**Current `_norm` (line 32–34) — the one-line fix target:**
```python
# reconcile_names.py:32–34 — CURRENT (D-04 bug: no NFC; NFD ≠ NFC after casefold)
def _norm(name: str) -> str:
    """Whitespace-normalize + casefold for deterministic comparison."""
    return " ".join(name.split()).casefold()
```

**Target form (D-05 hardened — double NFC around casefold):**
```python
# reconcile_names.py:32 — TARGET (add `import unicodedata` at top of file)
def _norm(name: str) -> str:
    """Whitespace-normalize + NFC(casefold(NFC(s))) for deterministic comparison (D-05)."""
    nfc = unicodedata.normalize("NFC", name)
    return " ".join(unicodedata.normalize("NFC", nfc.casefold()).split())
```
Add `import unicodedata` to the imports block (currently only `from __future__ import annotations` and the roster model import).

**Call-site inventory (do NOT change these — they benefit automatically):**
- Line 50: `norm = _norm(name)` — in `deterministic_match`
- Line 52: `_norm(emp.full_name)` — exact tier check
- Line 56: `_norm(alias)` — alias tier check
- Line 134: `_safe_to_learn_alias` uses `_norm` internally via `deterministic_match`
- `orchestrator.py:198, 204, 346` — imports `_norm` directly; benefits automatically

---

### 3. `app/models/contracts.py` — Widen `ValidationIssue.issue_type` Literal + add `FieldDrop`

**Analog:** `app/models/roster.py:205–216` (`ValidationIssue`) + `contracts.py:60–80` (`ExtractedEmployee`)

**Current `ValidationIssue` declaration (roster.py:205–216) — Literal MUST be widened (C-1 fix):**
```python
# roster.py:205–216 — CURRENT (add "field_regression" to Literal)
class ValidationIssue(BaseModel):
    """One field-validation issue produced by the validate stage.

    issue_type Literal covers the 3 legal values from LLM-06
    (Finding #7 — constrained to known value set).
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    issue_type: Literal["missing", "out_of_bounds", "non_numeric"]
    message: str
```
Change `Literal["missing", "out_of_bounds", "non_numeric"]` to `Literal["missing", "out_of_bounds", "non_numeric", "field_regression"]`.

**`ExtractedEmployee` (contracts.py:60–80) — style template for new `FieldDrop` model:**
```python
# contracts.py:60–80 — model pattern to COPY for FieldDrop
class ExtractedEmployee(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submitted_name: str
    hours_regular: Decimal | None = Field(default=None, ge=0)
    hours_overtime: Decimal | None = Field(default=None, ge=0)
    hours_vacation: Decimal | None = Field(default=None, ge=0)
    hours_sick: Decimal | None = Field(default=None, ge=0)
    hours_holiday: Decimal | None = Field(default=None, ge=0)
    contribution_401k_override: Decimal | None = Field(default=None, ge=0, le=1)
```

**New `FieldDrop` model to add to `contracts.py`** (place before `Decision`, after `Extracted`):
```python
# contracts.py — NEW (mirror ExtractedEmployee style: ConfigDict(extra="forbid"), typed fields)
class FieldDrop(BaseModel):
    """One hours-field regression detected between snapshot and resumed extraction (D-10/D-11).

    resumed_value=None means the field is absent (silence); resumed_value=Decimal("0")
    means the client explicitly zeroed it. D-14: None → carried_forward; Decimal("0")
    → confirmed_dropped.
    """

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID            # resolved employee id (keyed from snapshot)
    field: str                   # e.g. "hours_overtime"
    original_value: Decimal      # _is_paid() True in snapshot
    resumed_value: Decimal | None  # None = absent; Decimal("0") = explicit zero
```
Add `UUID` to the imports block (already imported: `from uuid import UUID`).

---

### 4. `app/pipeline/decide.py` — New Rule 2b for `field_regression`

**Analog:** `decide.py:123–125` (existing Rule 2 — symmetric new rule adds 2 lines immediately after)

**Current Rule 2 (lines 123–125) — the template to copy symmetrically:**
```python
# decide.py:123–125 — CURRENT Rule 2 (the model for Rule 2b)
    # Rule 2 — missing required field.
    missing = [i.field for i in issues if i.issue_type == "missing"]
    gate_reasons += [f"missing required field: {f}" for f in missing]
```

**New Rule 2b (add immediately after line 125):**
```python
# decide.py — NEW Rule 2b (2 lines; mirrors Rule 2 exactly; resolves C-1 contradiction)
    # Rule 2b — field regression detected (D-17; symmetric with Rule 2).
    regressions = [i.field for i in issues if i.issue_type == "field_regression"]
    gate_reasons += [f"field regression: {f}" for f in regressions]
```
The `missing_fields` field on `Decision` need NOT be widened — `regressions` feeds `gate_reasons` only (field regression is surfaced via the gate reason message, not a separate `Decision` field). This is intentional: the operator sees the gate reason; the regression detail lives in `clarified_fields`.

---

### 5. `app/db/schema.sql` — Two new nullable JSONB columns

**Analog:** `schema.sql:90` (`alias_candidates` inline declaration) + `schema.sql:107` (ALTER block)

**Existing `alias_candidates` inline declaration (schema.sql:89–90):**
```sql
-- schema.sql:89–90 — the EXACT pattern to copy (add two lines after this)
    -- D-04: separate JSONB column for alias candidates so persist_reconciliation can
    -- never overwrite it on resume. Written by repo.set_alias_candidates in Wave 4.
    alias_candidates JSONB,
```

**Existing ALTER block (schema.sql:105–108):**
```sql
-- schema.sql:105–108 — the ADD COLUMN IF NOT EXISTS pattern to mirror
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS reconciliation    JSONB;  -- D-A3-05
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS error_reason      TEXT;   -- D-A1-03
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS alias_candidates  JSONB;  -- D-04 (Plan 05-03)
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS record_only       BOOLEAN NOT NULL DEFAULT FALSE;
```

**New columns to add inline after `alias_candidates JSONB,` (schema.sql:90):**
```sql
    pre_clarify_extracted JSONB,    -- D-19: snapshot of extracted_data at awaiting_reply pause (MONEY-03)
    clarified_fields JSONB,          -- D-13: {employee_id: {field: outcome}} field-regression outcomes (MONEY-03)
```

**New ALTER statements to add after the `alias_candidates` ALTER (schema.sql:107):**
```sql
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS pre_clarify_extracted JSONB;  -- D-19 MONEY-03
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS clarified_fields JSONB;       -- D-13 MONEY-03
```

---

### 6. `app/db/repo.py` — Four new repo helpers

**Analog:** `set_alias_candidates` (repo.py:509–524) + `persist_extracted` (repo.py:407–424) + `claim_status` (repo.py:342–367)

**`set_alias_candidates` (repo.py:509–524) — EXACT template for `set_clarified_fields`:**
```python
# repo.py:509–524 — copy this pattern for set_clarified_fields
def set_alias_candidates(
    run_id: uuid.UUID,
    candidates: dict,
    conn=None,
) -> None:
    """Write alias_candidates to payroll_runs.alias_candidates JSONB column (D-04)."""
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET alias_candidates = %s, updated_at = now() WHERE id = %s",
                (json.dumps(candidates), str(run_id)),
            )
```

**`persist_extracted` (repo.py:407–424) — serialization pattern for `set_pre_clarify_extracted`:**
```python
# repo.py:407–424 — json.dumps(extracted.model_dump(mode="json")) is the correct serializer
def persist_extracted(run_id: uuid.UUID, extracted: Extracted, conn=None) -> None:
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET extracted_data = %s, "
                "pay_period_start = %s, pay_period_end = %s, updated_at = now() "
                "WHERE id = %s",
                (
                    json.dumps(extracted.model_dump(mode="json")),
                    extracted.pay_period_start,
                    extracted.pay_period_end,
                    str(run_id),
                ),
            )
```

**`claim_status` (repo.py:342–367) — `WHERE id = %s AND <condition> RETURNING id` CAS pattern for snapshot-once:**
```python
# repo.py:342–367 — the RETURNING id CAS style; adapt for IS NULL guard in set_pre_clarify_extracted
def claim_status(run_id, expected, new, conn=None) -> bool:
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                "UPDATE payroll_runs SET status = %s, updated_at = now() "
                "WHERE id = %s AND status = %s RETURNING id",
                (RunStatus(new).value, str(run_id), RunStatus(expected).value),
            ).fetchone()
    return row is not None
```

**Four new helpers to add to `repo.py` (place after `set_alias_candidates` at line 524):**

`set_pre_clarify_extracted` — snapshot-once write with IS NULL guard (D-19):
```python
def set_pre_clarify_extracted(
    run_id: uuid.UUID,
    extracted: Extracted,
    conn=None,
) -> bool:
    """Write pre_clarify_extracted ONLY IF NULL (snapshot-once, D-19).

    The IS NULL guard is in SQL so the check-and-write is atomic — no separate
    read-then-write race. Returns True if written, False if already set (idempotent).
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                "UPDATE payroll_runs SET pre_clarify_extracted = %s, updated_at = now() "
                "WHERE id = %s AND pre_clarify_extracted IS NULL RETURNING id",
                (json.dumps(extracted.model_dump(mode="json")), str(run_id)),
            ).fetchone()
    return row is not None
```

`load_pre_clarify_extracted` — targeted SELECT (not via RUN_COLS, following alias_candidates precedent):
```python
def load_pre_clarify_extracted(run_id: uuid.UUID, conn=None) -> Extracted | None:
    """Load the pre-clarification snapshot or None if not yet written (D-19)."""
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                "SELECT pre_clarify_extracted FROM payroll_runs WHERE id = %s",
                (str(run_id),),
            ).fetchone()
    if row is None or row[0] is None:
        return None
    return Extracted.model_validate(json.loads(row[0]) if isinstance(row[0], str) else row[0])
```

`set_clarified_fields` — plain dict write (mirrors `set_alias_candidates`):
```python
def set_clarified_fields(run_id: uuid.UUID, clarified: dict, conn=None) -> None:
    """Write clarified_fields JSONB (D-13). Shape: {employee_id: {field: outcome}}."""
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET clarified_fields = %s, updated_at = now() WHERE id = %s",
                (json.dumps(clarified), str(run_id)),
            )
```

`load_clarified_fields` — returns `{}` on NULL (mirrors `_pre_candidates` fallback in `resume_pipeline:154`):
```python
def load_clarified_fields(run_id: uuid.UUID, conn=None) -> dict:
    """Load clarified_fields or {} if not yet written (D-13)."""
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                "SELECT clarified_fields FROM payroll_runs WHERE id = %s",
                (str(run_id),),
            ).fetchone()
    if row is None or row[0] is None:
        return {}
    return json.loads(row[0]) if isinstance(row[0], str) else row[0]
```

**Note:** `RUN_COLS` at repo.py:90–93 does NOT include `alias_candidates`. The new columns follow the same pattern — loaded via separate targeted helpers, NOT via `load_run()`. Do not add `pre_clarify_extracted` or `clarified_fields` to `RUN_COLS`.

---

### 7. `app/pipeline/orchestrator.py` — D-20 wiring: `_clarify`, `_run_stages`, `resume_pipeline`

**Analog:** self — `_clarify` (lines 292–399), `_run_stages` (lines 260–289), `resume_pipeline` (lines 94–241)

**`_run_stages` (lines 260–289) — current call pattern showing where `prior=None` threads through:**
```python
# orchestrator.py:260–289 — CURRENT _run_stages (add `prior=None` kwarg; pass to validate())
def _run_stages(run_id, email, roster, *, llm) -> None:
    """The shared four-stage gate path..."""
    extract_kwargs = {"run_id": run_id}
    if llm is not None:
        extract_kwargs["llm"] = llm
    extracted = extract(email, roster, **extract_kwargs)

    submitted_names = [e.submitted_name for e in extracted.employees]
    matches = reconcile_names(submitted_names, roster)
    issues = validate(extracted, roster, matches)          # <-- gains prior=prior kwarg

    decision = decide(extracted, matches, issues)

    repo.persist_extracted(run_id, extracted)
    repo.persist_decision(run_id, decision)
    repo.persist_reconciliation(run_id, matches)

    if decision.final_action == "process":
        line_items = _compute_line_items(run_id, extracted, matches, roster)
        repo.replace_line_items(run_id, line_items)
        repo.set_status(run_id, RunStatus.COMPUTED)
        repo.set_status(run_id, RunStatus.AWAITING_APPROVAL)
    else:
        _clarify(run_id, email, decision, roster, llm=llm)
```

**D-20 wiring plan for `_run_stages` signature change:**
- Add `prior: Extracted | None = None` kwarg (after `*, llm`)
- Add `resolved_drops: set | None = None` kwarg (for D-15 MONEY-01 short-circuit)
- Pass both through to `validate(extracted, roster, matches, prior=prior, resolved_drops=resolved_drops)`
- `_run_stages` must return `extracted` (currently returns `None`) so `_clarify` can receive it

**`resume_pipeline` (lines 119–241) — the existing CAS + alias-diff structure to preserve:**
```python
# orchestrator.py:124 — DO NOT TOUCH (D-22: CAS already exists, never re-add)
claimed = repo.claim_status(run_id, RunStatus.AWAITING_REPLY, RunStatus.EXTRACTING)
if not claimed:
    logger.info("resume aborted: ...")
    return
```

```python
# orchestrator.py:153–165 — alias diff pre/post pattern (model for D-11 diff in resume)
pre_run_data = repo.load_run(run_id)
_pre_candidates = (pre_run_data.get("alias_candidates") or {}) if pre_run_data else {}
_pre_reconciliation = (pre_run_data.get("reconciliation") or []) if pre_run_data else []
_pre_resolved_ids: set[str] = set()
if isinstance(_pre_reconciliation, list):
    for _m in _pre_reconciliation:
        if isinstance(_m, dict) and _m.get("matched_employee_id") is not None:
            _pre_resolved_ids.add(str(_m["matched_employee_id"]))

# STEP B: Run the four judgment stages as normal.
_run_stages(run_id, combined_email, roster, llm=llm)
```

**D-20 new steps to insert in `resume_pipeline` BEFORE the `_run_stages` call (between lines 140 and 165):**
```
# NEW Step D-20.1: load snapshot + clarified_fields
snapshot = repo.load_pre_clarify_extracted(run_id)
clarified = repo.load_clarified_fields(run_id)
# Build resolved_drops from confirmed_dropped entries (D-15 short-circuit)
resolved_drops = {
    (uuid.UUID(emp_id), field)
    for emp_id, fields in clarified.items()
    for field, outcome in fields.items()
    if outcome == "confirmed_dropped"
}
# NEW Step D-20.2: pass snapshot + resolved_drops into _run_stages
_run_stages(run_id, combined_email, roster, prior=snapshot, resolved_drops=resolved_drops, llm=llm)
```

**`_clarify` (lines 292–399) — WHERE `set_pre_clarify_extracted` call is inserted (D-19/D-21):**
The snapshot must be written BEFORE `repo.set_status(run_id, RunStatus.AWAITING_REPLY)`. The function currently receives `decision` and `roster` but not `extracted`. It needs `extracted` threaded in as a new parameter.

```python
# orchestrator.py:292 — CURRENT _clarify signature (add extracted parameter)
def _clarify(run_id, email, decision, roster, *, llm) -> None:
```

**New `_clarify` signature:**
```python
def _clarify(run_id, email, decision, roster, extracted, *, llm) -> None:
```

**Snapshot write inside `_clarify` — add immediately before the `repo.set_status(AWAITING_REPLY)` call.** The `IS NULL` guard in SQL makes this safe to call on every `_clarify` invocation (second call is a no-op):
```python
    # D-19/D-21: snapshot at the awaiting_reply pause (IS NULL guard in SQL = snapshot-once)
    repo.set_pre_clarify_extracted(run_id, extracted)
    repo.set_status(run_id, RunStatus.AWAITING_REPLY)
```

**Error boundary (lines 235–241) — ALL new resume code must stay inside this try/except:**
```python
# orchestrator.py:235–241 — EXISTING boundary; keep all new code inside it
except Exception as exc:  # noqa: BLE001 — the D-A1-03 error-wrap boundary (resume)
    reason = type(exc).__name__
    logger.warning("resume of run %s failed: %s", run_id, reason)
    repo.record_run_error(run_id, reason)
```

---

### 8. `eval/run_eval.py` — `_normalize` NFC fix (C-4)

**Analog:** self — `run_eval.py:51–53` (the function to update)

**Current `_normalize` (lines 51–53) — THE BUG (separate from `_norm`; will diverge after MONEY-02):**
```python
# run_eval.py:51–53 — CURRENT (no NFC; diverges from _norm after MONEY-02 fix)
def _normalize(name: str) -> str:
    """casefold + collapse whitespace -- same normalization reconcile_names uses."""
    return " ".join(name.casefold().split())
```

**Fix — import `_norm` directly or replicate the NFC form (recommended: import `_norm` to keep DRY):**
```python
# run_eval.py — TARGET (Option A: import _norm directly; DRY by construction)
from app.pipeline.reconcile_names import _norm as _normalize
```
OR (Option B — replicate for minimal change to call sites):
```python
def _normalize(name: str) -> str:
    """NFC(casefold(NFC(s))) + whitespace-normalize -- matches reconcile_names._norm (D-05/C-4)."""
    import unicodedata
    nfc = unicodedata.normalize("NFC", name)
    return " ".join(unicodedata.normalize("NFC", nfc.casefold()).split())
```
**Recommendation: Option A (`from app.pipeline.reconcile_names import _norm as _normalize`)** eliminates the second copy entirely. The eval already imports from `app.pipeline`; this is the natural DRY resolution. The existing 6 call sites of `_normalize` at lines 167, 168, 173, 196, 197, 234 need no change.

**CRITICAL ORDER:** Fix `run_eval.py:_normalize` in the SAME wave as `reconcile_names._norm` (MONEY-02). Adding the NFD fixture (fixture 17) before this fix causes false eval score regressions.

---

### 9. New eval fixtures 16, 17, 18 — `eval/fixtures/`

**Analog:** `eval/fixtures/07_missing_hours_coastal.json` + `07_missing_hours_coastal_extraction.json`

**Fixture JSON structure (copy from `07_missing_hours_coastal.json`):**
```json
{
  "id": "f0000007-0000-0000-0000-000000000007",
  "message_id": "<eval-07-missing-hours@coastalcleaning.example>",
  "in_reply_to": null,
  "references_header": null,
  "subject": "Payroll submission week of 6/15",
  "from_addr": "payroll@coastalcleaning.example",
  "to_addr": "agent@payroll-agent.local",
  "body_text": "...",
  "created_at": "2026-06-16T11:00:00Z",
  "fixture_category": "missing-hours",
  "expected": {
    "extracted": { "employees": [...], "pay_period_start": "...", "pay_period_end": null },
    "reconciliation": [{ "submitted_name": "...", "name_category": "exact", "expected_source": "exact", "expected_resolved": true, "expected_matched_employee_id": "..." }],
    "decision": { "final_action": "request_clarification", "gate_reasons_contains": ["hours"], "unresolved_names": [], "missing_fields": ["..."] }
  }
}
```

**Extraction cache structure (copy from `07_missing_hours_coastal_extraction.json`):**
```json
{
  "run_id": "00000000-0000-0000-0000-000000000000",
  "employees": [
    {
      "submitted_name": "...",
      "hours_regular": null,
      "hours_overtime": null,
      "hours_vacation": null,
      "hours_sick": null,
      "hours_holiday": null,
      "contribution_401k_override": null
    }
  ],
  "pay_period_start": "...",
  "pay_period_end": null
}
```

**D-24 constraint:** The `_extraction.json` file MUST be produced via `extracted.model_dump_json(indent=2)` (as confirmed at `eval/run_eval.py:655`), NOT hand-typed. For test fixtures, run `--record` with a mocked LLM that returns the correct shape, or write a small script using `Extracted.model_dump_json()`. Decimal values serialize as JSON strings (e.g. `"40.00"`), not bare numbers.

**Numbering:** Existing fixtures are 01–15 (15 fixture files confirmed). New fixtures start at 16.
- `eval/fixtures/16_zero_hours_hourly_{business}.json` + `16_zero_hours_hourly_{business}_extraction.json`
- `eval/fixtures/17_nfd_name_{business}.json` + `17_nfd_name_{business}_extraction.json`
- `eval/fixtures/18_field_drop_clarify_carry_{business}.json` + `18_field_drop_clarify_carry_{business}_extraction.json`

**Fixture 18 note (D-24):** The `prior` fixture (snapshot) for fixture 18 must be produced by serializing a real `Extracted` through `model_dump_json()` — it is the pre-clarify snapshot value that will be passed as `prior=` to `validate()` in the eval's PATH A. The fixture JSON needs a new `"prior_extracted"` key to carry the snapshot, or the eval runner needs to build it from a separate sibling file.

---

## Shared Patterns

### Transaction / connection context pattern
**Source:** `repo.py:360–367` (`claim_status` body) — every repo helper
**Apply to:** All four new repo helpers
```python
with _conn_ctx(conn) as (c, owns):
    with c.transaction() if owns else _nulltx():
        c.execute("...", (param1, str(run_id))).fetchone()
```
- Always use `%s` placeholders — never f-string SQL
- Always `str(run_id)` when binding a UUID parameter
- Always `json.dumps(obj)` for JSONB writes (never pass a dict directly)

### JSONB serialization rule
**Source:** `repo.py:419` (`persist_extracted`) + `repo.py:523` (`set_alias_candidates`)
**Apply to:** `set_pre_clarify_extracted`, `set_clarified_fields`
- `Extracted` objects: `json.dumps(extracted.model_dump(mode="json"))`
- Plain dicts: `json.dumps(the_dict)`
- Never hand-serialize — Decimal → JSON string precision is handled by Pydantic's `mode="json"` serializer

### PII-safe error handling
**Source:** `orchestrator.py:235–241` (resume error boundary)
**Apply to:** Any new code in `resume_pipeline`
```python
except Exception as exc:  # noqa: BLE001
    reason = type(exc).__name__   # type name ONLY — never str(exc)
    logger.warning("resume of run %s failed: %s", run_id, reason)
    repo.record_run_error(run_id, reason)
```

### Pure-function model style (`extra="forbid"`)
**Source:** `contracts.py:60–80` (`ExtractedEmployee`) + `roster.py:205–216` (`ValidationIssue`)
**Apply to:** New `FieldDrop` model
```python
class NewModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # typed fields with Decimal | None + ge=0 where numeric
```

### Pydantic v2 JSONB read-back
**Source:** Implied by `_load_extraction_cache` (run_eval.py:117):
```python
Extracted.model_validate(json.loads(cache_path.read_text()))
```
**Apply to:** `load_pre_clarify_extracted` when parsing the stored JSONB back into `Extracted`. psycopg returns JSONB columns as already-deserialized dicts (not JSON strings) when using dict_row; if using plain tuple rows the value may be a string. Handle both: `json.loads(row[0]) if isinstance(row[0], str) else row[0]`.

---

## No Analog Found

All 10 files have direct codebase analogs. No file requires inventing a new pattern from scratch.

---

## Key Notes for Planner

### D-15 interaction (MONEY-01 short-circuit for `confirmed_dropped`)
The mechanism is: **`resume_pipeline` builds `resolved_drops: set[tuple[UUID, str]]`** from the `clarified_fields` dict (all `confirmed_dropped` entries), then threads it into `_run_stages(..., resolved_drops=resolved_drops)`, which passes it to `validate(..., resolved_drops=resolved_drops)`. Inside `validate()`, the `any_hours` gate skips MONEY-01 for `(employee_id, field)` pairs in `resolved_drops`. This prevents a client's explicit "remove it" answer from being re-flagged as missing on the next pass.

### D-20 termination ordering — strictly non-negotiable
The backfill of `carried_forward` values MUST happen inside `validate()` (or before it is called) so that `validate` sees the backfilled value and emits NO `field_regression` issue on pass 2. If the backfill happens after `validate`, `decide` will see a stray `field_regression` issue and clarify again — infinite loop.

### D-21 snapshot timing
`set_pre_clarify_extracted` belongs in `_clarify()`, NOT in `resume_pipeline`. At resume time, `extracted_data` has already been overwritten. The snapshot captures the state AT the `awaiting_reply` pause. This requires threading `extracted` from `_run_stages()` → `_clarify()` (make `_run_stages` return `extracted`; pass it as a new `extracted` param to `_clarify`).

### C-1 contradiction resolution (locked: Option B)
`decide.py` is NOT unchanged — add exactly 2 lines (Rule 2b) AND widen `ValidationIssue.issue_type` Literal. The CONTEXT.md claim that "decide.py is UNCHANGED" was imprecise.

### C-4 eval normalizer (locked: fix before adding NFD fixture)
Fix `run_eval.py:_normalize` (import `_norm` directly) in the same task/wave as `reconcile_names._norm`. Add fixture 17 only after both fixes are applied.

---

## Metadata

**Analog search scope:** `app/pipeline/`, `app/models/`, `app/db/`, `eval/`
**Files read:** `validate.py`, `reconcile_names.py`, `contracts.py`, `roster.py` (ValidationIssue section), `decide.py`, `repo.py` (lines 1–100, 340–524), `orchestrator.py` (lines 1–400), `schema.sql` (lines 1–130), `run_eval.py` (lines 1–80, 100–180, 640–660), `eval/fixtures/07_missing_hours_coastal.json`, `07_missing_hours_coastal_extraction.json`
**Pattern extraction date:** 2026-06-27

---

## PATTERN MAPPING COMPLETE
